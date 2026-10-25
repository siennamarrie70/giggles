"""
The dashboard: serves the page (index.html, app.css, app.js in this folder) and the
JSON API it calls.

Locally it's at http://localhost:8000 and answers only on this computer. On Vercel it's
switched off unless DASHBOARD_PASSWORD is set (the browser then asks for it).
Writing, animating and uploading run in a background thread; the page polls progress.
While the database is on this computer, a loop here also runs the channel every minute: a due
slot first, then keeping episodes written ahead, their previews rendered, and the day's numbers
(jobs.next_chore).
"""

import json
import os
import re
import secrets
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import set_key
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import character_spec
import db
import jobs
import lipsync
import notify
import puppet
import short_render
import slots
import trends_fetch
import voice_tts
import youtube_auth
from agents import AGENTS, analyst, animator, writer
from agents.base import playbook
from common import CONFIG_DIR, ON_VERCEL, ROOT, env, is_true, load_config, tmp_path

UI_DIR = Path(__file__).resolve().parent
UI_FILES = {
    "app.css": (UI_DIR / "app.css", "text/css"),
    "app.js": (UI_DIR / "app.js", "text/javascript"),
    "caption-font.ttf": (short_render.FONT_PATH, "font/ttf"),
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
CLIENT_FILE = ROOT / "credentials.json"
MAX_MUSIC_BYTES = 30 * 1024 * 1024
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9 ._()-]+")
_basic = HTTPBasic(auto_error=False)


def guard(request: Request, creds: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """Local: this computer only. Vercel: DASHBOARD_PASSWORD. Changes need the page's own header,
    which a browser won't add for another website (so other sites can't press buttons here)."""
    if ON_VERCEL:
        password = env("DASHBOARD_PASSWORD")
        if not password:
            raise HTTPException(404)
        if not creds or not secrets.compare_digest(creds.password.encode(), password.encode()):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="dashboard"'})
    elif request.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
        raise HTTPException(403, "The dashboard only answers on localhost.")
    if request.method not in ("GET", "HEAD") and request.headers.get("x-dashboard") != "1":
        raise HTTPException(403, "Missing dashboard header.")


router = APIRouter(dependencies=[Depends(guard)])


def _local_only(what: str) -> None:
    if ON_VERCEL:
        raise HTTPException(409, f"{what}: only from the dashboard on your computer.")


# --- background tasks -----------------------------------------------------

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _public(task: dict) -> dict:
    return {k: task[k] for k in ("id", "kind", "label", "status", "steps", "result", "error", "started",
                                 "finished", "video_id")}


def _start_task(kind: str, label: str, work, video_id: int | None = None) -> dict:
    """One task at a time; `work(progress)` runs in a thread and reports steps through progress()."""
    with _tasks_lock:
        busy = next((t for t in _tasks.values() if t["status"] == "running"), None)
        if busy:
            raise HTTPException(409, f"Busy: {busy['label']}. Try again when it finishes.")
        task = {"id": uuid.uuid4().hex[:12], "kind": kind, "label": label, "status": "running", "steps": [],
                "result": None, "error": None, "started": time.time(), "finished": None, "video_id": video_id}
        _tasks[task["id"]] = task
        for old in sorted(_tasks.values(), key=lambda t: t["started"])[:-20]:
            _tasks.pop(old["id"], None)

    def progress(text: str) -> None:
        task["steps"].append({"at": round(time.time() - task["started"], 1), "text": text})

    def run() -> None:
        try:
            task["result"] = work(progress)
            task["status"] = "done"
        except Exception as e:
            task["error"] = str(e)
            task["status"] = "error"
        finally:
            task["finished"] = time.time()

    threading.Thread(target=run, name=f"task-{kind}", daemon=True).start()
    return _public(task)


def _make_next_now(progress) -> dict:
    jobs.check(progress)
    return jobs.run_job("autopilot", force=True, progress=progress)


def _connect_youtube(progress) -> dict:
    progress("A Google sign-in page opened in your browser: pick your channel and allow access.")
    result = youtube_auth.run(timeout_seconds=300)
    _channel_cache.update(at=time.time(), title=result["channel"], error=None)
    progress(f"Connected to {result['channel']}")
    return result


# --- the channel on this computer -----------------------------------------

LOOP_SECONDS = 60
RETRY_AFTER_FAILURE = 20 * 60  # after a failed run, wait before the next try instead of hammering the APIs
_loop_started = False


def autopilot_here() -> bool:
    """With the database on this computer, the dashboard runs the channel itself. With a cloud
    database (DATABASE_URL), Vercel's hourly cron does: checking Neon every minute from here would
    keep its free database awake around the clock."""
    return not ON_VERCEL and not (env("DATABASE_URL") or env("POSTGRES_URL"))


def _chore_label(name: str, kwargs: dict) -> str:
    if name == "autopilot":
        slot = jobs.due_slot()
        return f"Autopilot: making the {jobs.clock(slot, slots.plan())} Short" if slot else "Autopilot"
    if name == "prepare":
        return "Agents 1 and 2: writing the next episode"
    if name == "publish":
        return f"Agent 3: animating episode #{kwargs['video_id']}"
    return "Agent 5: reading the numbers"


def _autopilot_loop() -> None:
    last = None
    while True:
        time.sleep(LOOP_SECONDS)
        try:
            if last and last["status"] == "error" and time.time() - last["finished"] < RETRY_AFTER_FAILURE:
                continue
            if not autopilot_here() or is_true("PAUSED"):
                continue
            chore = jobs.next_chore()
            if not chore:
                continue
            name, kwargs = chore
            task = _start_task(name, _chore_label(name, kwargs),
                               lambda p, n=name, k=kwargs: jobs.run_job(n, progress=p, **k), kwargs.get("video_id"))
            last = _tasks[task["id"]]
        except HTTPException:
            pass  # busy with something you started; the next minute tries again
        except Exception as e:
            print(f"autopilot loop: {e}", file=sys.stderr, flush=True)


def start_autopilot_loop() -> None:
    global _loop_started
    if not _loop_started:
        _loop_started = True
        threading.Thread(target=_autopilot_loop, name="autopilot", daemon=True).start()


# --- page -----------------------------------------------------------------

@router.get("/", include_in_schema=False)
def page():
    return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/ui/{name}", include_in_schema=False)
def ui_file(name: str):
    if name not in UI_FILES:
        raise HTTPException(404)
    path, media_type = UI_FILES[name]
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


# --- overview -------------------------------------------------------------

def _slot_video(v: dict | None) -> dict | None:
    if not v:
        return None
    meta = v["plan"].get("metadata", {})
    return {"id": v["id"], "status": v["status"], "title": meta.get("title") or v["theme"],
            "setting": v["plan"].get("setting"), "youtube_id": v["youtube_id"], "publish_at": v["publish_at"]}


def _autopilot_state(cfg: dict) -> dict:
    sched = slots.plan(cfg)
    now = datetime.now(timezone.utc)
    day = slots.day_slots(slots.shown_day(now, sched), sched)
    board = jobs.slot_board(day[0], day[-1], sched, now)
    upcoming = jobs.slot_board(now, now + timedelta(days=2), sched, now)
    try:
        next_open = slots.iso(jobs.next_open_slot(jobs.MANUAL_LEAD, now, sched))
    except RuntimeError:
        next_open = None
    return {
        "here": autopilot_here(),
        "schedule": {k: sched[k] for k in ("timezone", "first_post", "every_hours", "posts_per_day")},
        "slots": [{"at": slots.iso(s["slot"]), "state": s["state"], "video": _slot_video(s["video"])} for s in board],
        "next": upcoming and {"at": slots.iso(upcoming[0]["slot"]), "state": upcoming[0]["state"]},
        "next_open": next_open,
        "last_check": db.last_beat("autopilot"),
    }


def _run_json(r: dict | None) -> dict | None:
    if not r:
        return None
    try:
        detail = json.loads(r["detail"]) if r["detail"] else {}
    except ValueError:
        detail = {"text": r["detail"]}
    return {"at": r["started_at"], "finished": r["finished_at"], "ok": r["ok"], "detail": detail}


def _agents(planned: list[dict]) -> list[dict]:
    """Each agent's card: its last run and the size of its part of the pipeline."""
    videos = db.list_videos(300)
    now = datetime.now(timezone.utc)
    scheduled = [v for v in videos if v["status"] == "scheduled" and v["publish_at"] and slots.parse(v["publish_at"]) > now]
    previews = [v for v in planned if animator.preview_path(v["id"]).exists()]
    book = playbook()
    metric = {
        "casting": (len(db.list_characters(10_000)), "characters created"),
        "writer": (len(planned), "episodes written and waiting"),
        "animator": (len(previews), "previews ready to watch"),
        "publisher": (len(scheduled), "Shorts scheduled ahead"),
        "analyst": (book.get("samples") or 0, "Shorts in the playbook"),
    }
    out = []
    for agent in AGENTS:
        count, what = metric[agent["key"]]
        out.append({**agent, "last": _run_json(db.last_run(agent["key"], ok=None)), "count": count, "what": what})
    return out


@router.get("/api/state")
def state():
    cfg = load_config()
    planned = db.planned_videos()
    return {
        "channel": cfg["channel"]["name"],
        "local": not ON_VERCEL,
        "paused": is_true("PAUSED"),
        "services": {
            "gemini": bool(env("GEMINI_API_KEY")),
            "youtube": youtube_auth.is_configured(),
            "telegram": notify.is_configured(),
            "database": "cloud" if env("DATABASE_URL") or env("POSTGRES_URL") else "local",
            "music": len(short_render.music_tracks()),
            "voices": voice_tts.ready(),
            "lipsync": lipsync.ready(),
        },
        "autopilot": _autopilot_state(cfg),
        "events": trends_fetch.calendar_signals(datetime.now(timezone.utc).date(), 10)["events"],
        "counts": db.status_counts(),
        "agents": _agents(planned),
        "task": next((_public(t) for t in _tasks.values() if t["status"] == "running"), None),
    }


@router.post("/api/pause")
async def set_pause(request: Request):
    _local_only("The pause switch")
    paused = bool((await request.json()).get("paused"))
    set_key(str(ROOT / ".env"), "PAUSED", "true" if paused else "false")
    os.environ["PAUSED"] = "true" if paused else "false"
    return {"paused": paused}


# --- episodes -------------------------------------------------------------

def _stamp(path: Path) -> str:
    return f"?v={int(path.stat().st_mtime)}"


def _cast_json(c: dict) -> dict:
    return {"id": c.get("id"), "name": c["name"], "role": c["role"], "voice": c["voice"], "speed": c.get("speed", 1.0),
            "image": f"/media/character/{c['id']}.png" if c.get("id") else None}


def _video_json(v: dict) -> dict:
    plan = v["plan"]
    script, meta, cast = plan.get("script") or {}, plan.get("metadata") or {}, plan.get("cast") or []
    preview, cover = animator.preview_path(v["id"]), animator.cover_path(v["id"])
    beats = script.get("beats") or []
    return {
        "id": v["id"], "status": v["status"], "created_at": v["created_at"], "publish_at": v["publish_at"],
        "legacy": v["format"] != "sketch",  # made by the cute-animal version
        "slot": v["slot"], "error": v["error"], "youtube_id": v["youtube_id"],
        "studio_url": f"https://studio.youtube.com/video/{v['youtube_id']}/edit" if v["youtube_id"] else None,
        "setting": plan.get("setting"), "premise": script.get("premise") or v["theme"],
        "trend": script.get("trend_used") or v["trend"], "hook": script.get("hook") or "", "beats": beats,
        "music_mood": script.get("music_mood"), "cast": [_cast_json(c) for c in cast],
        "title": meta.get("title"), "description": meta.get("description"), "hashtags": meta.get("hashtags") or [],
        "duration": (plan.get("render") or {}).get("seconds"),
        "estimate": round(writer.estimate_seconds(beats, cast), 1) if beats and cast else None,
        "music": plan.get("music"), "music_credit": short_render.music_credit(plan.get("music")),
        "preview": f"/media/preview/{v['id']}.mp4{_stamp(preview)}" if preview.exists() else None,
        "cover": f"/media/cover/{v['id']}.jpg{_stamp(cover)}" if cover.exists() else None,
    }


def _planned_or_409(video_id) -> dict:
    video = db.get_video(int(video_id)) if video_id is not None else None
    if not video:
        raise HTTPException(404, "No such Short.")
    if video["status"] != "planned":
        raise HTTPException(409, f"Short #{video['id']} is {video['status']}; only queued episodes can be changed.")
    return video


@router.get("/api/videos")
def videos(limit: int = 60):
    return [_video_json(v) for v in db.list_videos(limit)]


@router.patch("/api/videos/{video_id}")
async def edit_video(video_id: int, request: Request):
    video = _planned_or_409(video_id)
    try:
        plan = writer.apply_edits(video["plan"], await request.json())
    except (ValueError, IndexError, KeyError) as e:
        raise HTTPException(422, str(e))
    db.update_video(video_id, plan=plan)
    animator.preview_path(video_id).unlink(missing_ok=True)  # the old render no longer matches the script
    return _video_json(db.get_video(video_id))


@router.delete("/api/videos/{video_id}")
def discard_video(video_id: int):
    _planned_or_409(video_id)
    db.update_video(video_id, status="discarded")
    animator.preview_path(video_id).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/media/preview/{video_id}.mp4", include_in_schema=False)
def preview(video_id: int):
    path = animator.preview_path(video_id)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


@router.get("/media/cover/{video_id}.jpg", include_in_schema=False)
def cover(video_id: int):
    path = animator.cover_path(video_id)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


# --- the cast -------------------------------------------------------------

def _character_or_404(character_id: int) -> dict:
    found = db.get_characters([character_id])
    if not found:
        raise HTTPException(404, "No such character.")
    return found[0]


@router.get("/api/characters")
def characters(limit: int = 120):
    appearances: dict[int, list[dict]] = {}
    for v in db.list_videos(1000):
        for c in v["plan"].get("cast") or []:
            if c.get("id"):
                appearances.setdefault(c["id"], []).append({"id": v["id"], "status": v["status"]})
    return [{**c, "look": character_spec.describe(c), "voice_label": character_spec.VOICES.get(c["voice"], c["voice"]),
             "image": f"/media/character/{c['id']}.png", "voice_sample": f"/media/voice/{c['id']}.wav",
             "episodes": appearances.get(c["id"], [])} for c in db.list_characters(limit)]


@router.get("/media/character/{character_id}.png", include_in_schema=False)
def character_card(character_id: int):
    path = tmp_path("out", "cast", f"{character_id}.png")
    if not path.exists():
        puppet.card(_character_or_404(character_id)).save(path)
    return FileResponse(path, media_type="image/png")


@router.get("/media/voice/{character_id}.wav", include_in_schema=False)
def voice_sample(character_id: int):
    _local_only("Voice samples")
    path = tmp_path("out", "cast", f"{character_id}.wav")
    if not path.exists():
        spec = _character_or_404(character_id)
        voice_tts.speak(f"Hi, I'm {spec['name']}. {spec['personality']}", spec["voice"], spec["speed"], path)
    return FileResponse(path, media_type="audio/wav")


# --- tasks ----------------------------------------------------------------

@router.post("/api/tasks/{kind}")
async def start_task(kind: str, request: Request):
    # On Vercel a thread can be frozen once the response is sent, and /tmp previews don't persist,
    # so this work only runs from the dashboard on your computer.
    _local_only("Writing, animating and uploading from the dashboard")
    body = json.loads(await request.body() or b"{}")
    video_id = body.get("video_id")
    if kind == "prepare":
        return _start_task(kind, "Agents 1 and 2: writing a new episode",
                           lambda p: jobs.run_job("prepare", count=1, progress=p))
    if kind == "render":
        _planned_or_409(video_id)
        return _start_task(kind, f"Agent 3: animating episode #{video_id}",
                           lambda p: jobs.run_job("publish", dry_run=True, video_id=video_id, progress=p), video_id)
    if kind == "publish":
        _planned_or_409(video_id)
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the YouTube page).")
        return _start_task(kind, f"Agent 4: uploading episode #{video_id}",
                           lambda p: jobs.run_job("publish", video_id=video_id, progress=p), video_id)
    if kind == "autopilot":
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the YouTube page).")
        return _start_task(kind, "Making the next Short now", _make_next_now)
    if kind == "stats":
        return _start_task(kind, "Agent 5: reading the numbers", lambda p: jobs.run_job("stats", learn=True, progress=p))
    if kind == "connect":
        if not CLIENT_FILE.exists():
            raise HTTPException(409, "Add your OAuth client file first (step 2).")
        return _start_task(kind, "Connecting YouTube", _connect_youtube)
    raise HTTPException(404, "Unknown task.")


@router.get("/api/tasks/{task_id}")
def task_status(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found (the server may have restarted).")
    return _public(task)


# --- trends, results, activity --------------------------------------------

_trends_lock = threading.Lock()


def _fetch_trends(cfg: dict, refresh: bool) -> dict:
    # One fetch at a time: asking every country takes minutes, and a second fetch alongside would
    # only make Google refuse both. Whoever waited for the lock finds the fresh copy already saved.
    with _trends_lock:
        return jobs.trend_signals(cfg, days_ahead=10, refresh=refresh)


@router.get("/api/trends")
def trends(refresh: bool = False):
    cfg = load_config()
    if refresh or ON_VERCEL or db.fresh_note("trends", jobs.TRENDS_FRESH):
        return _fetch_trends(cfg, refresh)
    # Out of date: show the last fetch now and get today's in the background; the page asks again.
    if not _trends_lock.locked():
        threading.Thread(target=_fetch_trends, args=(cfg, False), name="trends", daemon=True).start()
    return {**jobs.trend_signals(cfg, days_ahead=10, cached_only=True), "refreshing": True}


@router.get("/api/results")
def results():
    table = analyst.rows(min_age=timedelta(0))
    return {"playbook": playbook(), "rows": table, "min_samples": analyst.MIN_SAMPLES,
            "judged": len(analyst.rows())}


@router.get("/api/activity")
def activity():
    runs = []
    for r in db.recent_runs(40):
        try:
            detail = json.loads(r["detail"]) if r["detail"] else None
        except ValueError:
            detail = {"text": r["detail"]}
        runs.append({"job": r["job"], "started_at": r["started_at"], "finished_at": r["finished_at"],
                     "ok": r["ok"], "detail": detail})
    return {"runs": runs, "alerts": list(notify.history), "telegram": notify.is_configured()}


@router.post("/api/notify/test")
def notify_test():
    if not notify.run("\U0001F44B Test message from your channel's control room"):
        raise HTTPException(409, "Telegram isn't set up, or the message didn't go through. "
                                 "Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
    return {"sent": True}


# --- YouTube connection ---------------------------------------------------

_channel_cache = {"at": 0.0, "title": None, "error": None}


@router.get("/api/youtube")
def youtube_status(refresh: bool = False):
    info = {"local": not ON_VERCEL, "client_file": CLIENT_FILE.exists(), "connected": youtube_auth.is_configured(),
            "channel": None, "error": None}
    if info["connected"]:
        if refresh or time.time() - _channel_cache["at"] > 600:
            try:
                _channel_cache.update(at=time.time(), title=youtube_auth.channel_title(), error=None)
            except Exception as e:
                _channel_cache.update(at=time.time(), title=None, error=str(e))
        info["channel"], info["error"] = _channel_cache["title"], _channel_cache["error"]
    return info


@router.put("/api/youtube/client")
async def save_client_file(request: Request):
    _local_only("The OAuth client file")
    try:
        data = json.loads(await request.body())
    except ValueError:
        raise HTTPException(422, "That file isn't JSON. Download the client's JSON file from Google Cloud.")
    if not isinstance(data, dict):
        raise HTTPException(422, "That isn't a Google OAuth client file.")
    if "web" in data:
        raise HTTPException(422, "This is a 'Web application' client. Create a 'Desktop app' client instead.")
    client = data.get("installed")
    if not isinstance(client, dict) or not client.get("client_id") or not client.get("client_secret"):
        raise HTTPException(422, "That isn't a Google OAuth client file (no client_id / client_secret).")
    CLIENT_FILE.write_text(json.dumps(data), encoding="utf-8")
    return {"ok": True}


# --- music ----------------------------------------------------------------

def _music_path(name: str) -> Path:
    clean = SAFE_FILENAME.sub("", Path(name).name).strip(" .")
    path = short_render.MUSIC_DIR / clean
    if not clean or path.suffix.lower() not in short_render.MUSIC_EXTS:
        raise HTTPException(422, "Use an mp3, m4a, aac, wav or ogg file.")
    return path


@router.get("/api/music")
def music():
    return [{"name": p.name, "size": p.stat().st_size, "url": f"/media/music/{quote(p.name)}",
             "credit": short_render.music_credit(p.name)} for p in short_render.music_tracks()]


@router.put("/api/music/{name}")
async def add_music(name: str, request: Request):
    _local_only("Music")
    path = _music_path(name)
    data = await request.body()
    if not data or len(data) > MAX_MUSIC_BYTES:
        raise HTTPException(422, f"Music files must be under {MAX_MUSIC_BYTES >> 20} MB.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"name": path.name, "size": len(data), "url": f"/media/music/{quote(path.name)}"}


@router.delete("/api/music/{name}")
def delete_music(name: str):
    _local_only("Music")
    _music_path(name).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/media/music/{name}", include_in_schema=False)
def music_file(name: str):
    path = _music_path(name)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


# --- settings -------------------------------------------------------------

@router.get("/api/settings")
def get_settings():
    return {**load_config(), "settings_available": character_spec.SETTINGS, "editable": not ON_VERCEL}


def _validated(s: dict) -> dict:
    section = lambda name: s.get(name) or {}
    channel, episodes = section("channel"), section("episodes")
    name = str(channel.get("name", "")).strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("Channel name: 1 to 60 characters.")
    contact = str(channel.get("contact_email") or "").strip()
    if contact and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise ValueError("Contact email doesn't look like an email address.")
    schedule = slots.validate(section("schedule"))
    settings = [str(x).strip() for x in episodes.get("settings", []) if str(x).strip() in character_spec.SETTINGS]
    if not settings:
        raise ValueError("Settings: pick at least one place for the sketches.")
    hashtags = []
    for tag in section("metadata").get("base_hashtags", []):
        tag = "#" + re.sub(r"[^0-9a-z_]", "", str(tag).lower())
        if len(tag) > 1 and tag not in hashtags:
            hashtags.append(tag)
    region = str(section("trends").get("region", "US")).strip().upper()
    try:
        max_cast, seconds, queue = int(episodes.get("max_cast")), int(episodes.get("max_seconds")), int(episodes.get("queue"))
        volume = float(section("music").get("volume"))
    except (TypeError, ValueError):
        raise ValueError("Characters, length, queue and volume must be numbers.")
    if max_cast not in (2, 3) or not 20 <= seconds <= 60 or not 0 <= queue <= 5 or not 0 <= volume <= 1.5:
        raise ValueError("Characters 2 or 3, length 20-60 seconds, queue 0-5, volume 0-1.5.")
    if region != "ALL" and not re.fullmatch(r"[A-Z]{2}", region):
        raise ValueError("Trends: ALL (every country) or a two-letter country code like US or GB.")
    return {"name": name, "contact": contact, "audience": str(channel.get("audience", "")).strip(),
            "voice": " ".join(str(channel.get("voice", "")).split()), "schedule": schedule, "settings": settings,
            "max_cast": max_cast, "seconds": seconds, "queue": queue, "region": region, "hashtags": hashtags[:4],
            "volume": round(volume, 2)}


@router.put("/api/settings")
async def save_settings(request: Request):
    _local_only("Settings")
    try:
        v = _validated(await request.json())
    except ValueError as e:
        raise HTTPException(422, str(e))

    # ruamel keeps the comments in channel.yaml; every user string is quoted so values like
    # 23:00 or NO can't be misread as numbers or booleans when the file is loaded again.
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedSeq
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q, FoldedScalarString

    def flow(items):
        seq = CommentedSeq([Q(i) for i in items])
        seq.fa.set_flow_style()
        return seq

    yaml = YAML()
    yaml.width = 100
    path = CONFIG_DIR / "channel.yaml"
    data = yaml.load(path.read_text(encoding="utf-8"))
    data["channel"]["name"], data["channel"]["audience"] = Q(v["name"]), Q(v["audience"])
    data["channel"]["contact_email"] = Q(v["contact"])
    data["channel"]["voice"] = FoldedScalarString(v["voice"])
    for key in ("timezone", "first_post"):
        data["schedule"][key] = Q(v["schedule"][key])
    for key in ("every_hours", "posts_per_day"):
        data["schedule"][key] = v["schedule"][key]
    data["episodes"]["settings"] = flow(v["settings"])
    data["episodes"]["max_cast"], data["episodes"]["max_seconds"] = v["max_cast"], v["seconds"]
    data["episodes"]["queue"] = v["queue"]
    data["trends"]["region"] = Q(v["region"])
    data["metadata"]["base_hashtags"] = flow(v["hashtags"])
    data["music"]["volume"] = v["volume"]
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return get_settings()
