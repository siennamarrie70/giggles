"""
The dashboard: serves the page (index.html, app.css, app.js in this folder) and the
JSON API it calls.

Locally it's at http://localhost:8000 and answers only on this computer. On Vercel it's
switched off unless DASHBOARD_PASSWORD is set (the browser then asks for it).
Planning, rendering and uploading run in a background thread; the page polls progress.
While the database is on this computer, a loop here also runs the autopilot every minute.
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

import concept_write
import db
import jobs
import notify
import short_render
import slots
import trends_fetch
import youtube_auth
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


# --- autopilot on this computer ------------------------------------------

LOOP_SECONDS = 60
RETRY_AFTER_FAILURE = 20 * 60  # after a failed run, wait before the next try instead of hammering the APIs
_loop_started = False


def autopilot_here() -> bool:
    """With the database on this computer, the dashboard runs the autopilot itself. With a cloud
    database (DATABASE_URL), Vercel's hourly cron does: checking Neon every minute from here would
    keep its free database awake around the clock."""
    return not ON_VERCEL and not (env("DATABASE_URL") or env("POSTGRES_URL"))


def _autopilot_loop() -> None:
    last = None
    while True:
        time.sleep(LOOP_SECONDS)
        try:
            if last and last["status"] == "error" and time.time() - last["finished"] < RETRY_AFTER_FAILURE:
                continue
            if not autopilot_here() or is_true("PAUSED"):
                continue
            slot = jobs.check()
            if not slot:
                continue
            when = jobs.clock(slot, slots.plan())
            task = _start_task("autopilot", f"Autopilot: making the {when} Short",
                               lambda p: jobs.run_job("autopilot", progress=p))
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

def _music_files() -> list[Path]:
    folder = short_render.MUSIC_DIR
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in short_render.MUSIC_EXTS) if folder.exists() else []


def _slot_video(v: dict | None) -> dict | None:
    if not v:
        return None
    meta = v["plan"].get("metadata", {})
    return {"id": v["id"], "status": v["status"], "format": v["format"], "title": meta.get("title") or v["theme"],
            "youtube_id": v["youtube_id"], "publish_at": v["publish_at"]}


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


@router.get("/api/state")
def state():
    cfg = load_config()
    return {
        "channel": cfg["channel"]["name"],
        "local": not ON_VERCEL,
        "paused": is_true("PAUSED"),
        "services": {
            "gemini": bool(env("GEMINI_API_KEY")),
            "pexels": bool(env("PEXELS_API_KEY")),
            "pixabay": bool(env("PIXABAY_API_KEY")),
            "youtube": youtube_auth.is_configured(),
            "telegram": notify.is_configured(),
            "database": "cloud" if env("DATABASE_URL") or env("POSTGRES_URL") else "local",
            "music": len(_music_files()),
        },
        "autopilot": _autopilot_state(cfg),
        "events": trends_fetch.calendar_signals(datetime.now(timezone.utc).date(), 10)["events"],
        "counts": db.status_counts(),
        "task": next((_public(t) for t in _tasks.values() if t["status"] == "running"), None),
    }


@router.post("/api/pause")
async def set_pause(request: Request):
    _local_only("The pause switch")
    paused = bool((await request.json()).get("paused"))
    set_key(str(ROOT / ".env"), "PAUSED", "true" if paused else "false")
    os.environ["PAUSED"] = "true" if paused else "false"
    return {"paused": paused}


# --- Shorts ---------------------------------------------------------------

def _preview_path(video_id: int) -> Path:
    return tmp_path("out", f"short_{video_id}.mp4")


def _video_json(v: dict) -> dict:
    plan = v["plan"]
    concept, meta, edit = plan.get("concept", {}), plan.get("metadata", {}), plan.get("edit", {})
    preview = _preview_path(v["id"])
    return {
        "id": v["id"], "status": v["status"], "format": v["format"], "theme": v["theme"], "trend": v["trend"],
        "angle": concept.get("angle"), "animal": concept.get("animal"), "created_at": v["created_at"],
        "publish_at": v["publish_at"], "slot": v["slot"], "error": v["error"], "youtube_id": v["youtube_id"],
        "studio_url": f"https://studio.youtube.com/video/{v['youtube_id']}/edit" if v["youtube_id"] else None,
        "duration": edit.get("duration"),
        "metadata": {k: meta.get(k) for k in ("hook", "punchline", "captions", "title", "description", "hashtags")},
        "clips": [{
            "source": c.get("source"), "credit_name": c.get("credit_name"), "page_url": c.get("page_url"),
            "duration": c.get("duration"), "thumb": (c.get("preview_urls") or [None])[0],
            "what": (c.get("check") or {}).get("what_happens"), "score": (c.get("check") or {}).get("score"),
        } for c in plan.get("clips", [])],
        "preview": f"/media/preview/{v['id']}.mp4?v={int(preview.stat().st_mtime)}" if preview.exists() else None,
    }


def _planned_or_409(video_id) -> dict:
    video = db.get_video(int(video_id)) if video_id is not None else None
    if not video:
        raise HTTPException(404, "No such Short.")
    if video["status"] != "planned":
        raise HTTPException(409, f"Short #{video['id']} is {video['status']}; only planned Shorts can be changed.")
    return video


@router.get("/api/videos")
def videos(limit: int = 40):
    return [_video_json(v) for v in db.list_videos(limit)]


@router.patch("/api/videos/{video_id}")
async def edit_video(video_id: int, request: Request):
    video = _planned_or_409(video_id)
    try:
        plan = concept_write.apply_edits(video["plan"], await request.json(), load_config())
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.update_video(video_id, plan=plan)
    _preview_path(video_id).unlink(missing_ok=True)  # the old render no longer matches the text
    return _video_json(db.get_video(video_id))


@router.delete("/api/videos/{video_id}")
def discard_video(video_id: int):
    _planned_or_409(video_id)
    db.update_video(video_id, status="discarded")
    _preview_path(video_id).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/media/preview/{video_id}.mp4", include_in_schema=False)
def preview(video_id: int):
    path = _preview_path(video_id)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


# --- tasks ----------------------------------------------------------------

@router.post("/api/tasks/{kind}")
async def start_task(kind: str, request: Request):
    # On Vercel a thread can be frozen once the response is sent, and /tmp previews don't persist,
    # so in the cloud the daily cron jobs do this work and the dashboard only shows and edits.
    _local_only("Planning, rendering and uploading from the dashboard")
    body = json.loads(await request.body() or b"{}")
    video_id = body.get("video_id")
    if kind == "prepare":
        return _start_task(kind, "Planning a new Short", lambda p: jobs.run_job("prepare", count=1, progress=p))
    if kind == "render":
        _planned_or_409(video_id)
        return _start_task(kind, f"Rendering a preview of Short #{video_id}",
                           lambda p: jobs.run_job("publish", dry_run=True, video_id=video_id, progress=p), video_id)
    if kind == "publish":
        _planned_or_409(video_id)
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (YouTube tab).")
        return _start_task(kind, f"Uploading Short #{video_id} to YouTube",
                           lambda p: jobs.run_job("publish", video_id=video_id, progress=p), video_id)
    if kind == "autopilot":
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (YouTube tab).")
        return _start_task(kind, "Making the next Short now", _make_next_now)
    if kind == "stats":
        return _start_task(kind, "Refreshing stats", lambda p: jobs.run_job("stats", progress=p))
    if kind == "connect":
        _local_only("The YouTube connection")
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


# --- trends, activity -----------------------------------------------------

@router.get("/api/trends")
def trends(refresh: bool = False):
    return jobs.trend_signals(load_config(), days_ahead=10, refresh=refresh)


@router.get("/api/activity")
def activity():
    runs = []
    for r in db.recent_runs(30):
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
    return [{"name": p.name, "size": p.stat().st_size, "url": f"/media/music/{quote(p.name)}"} for p in _music_files()]


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
    return {**load_config(), "formats_available": list(concept_write.FORMATS), "editable": not ON_VERCEL}


def _validated(s: dict) -> dict:
    section = lambda name: s.get(name) or {}
    channel, content = section("channel"), section("content")
    name = str(channel.get("name", "")).strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("Channel name: 1 to 60 characters.")
    contact = str(channel.get("contact_email") or "").strip()
    if contact and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise ValueError("Contact email doesn't look like an email address.")
    schedule = slots.validate(section("schedule"))
    rotation = [str(f).strip() for f in section("formats").get("rotation", [])]
    if not 1 <= len(rotation) <= 8 or any(f not in concept_write.FORMATS for f in rotation):
        raise ValueError(f"Format rotation: 1 to 8 of {', '.join(concept_write.FORMATS)}.")
    animals = [str(a).strip().lower() for a in content.get("animals", []) if str(a).strip()]
    if not 1 <= len(animals) <= 30:
        raise ValueError("Animals: between 1 and 30.")
    hashtags = []
    for tag in section("metadata").get("base_hashtags", []):
        tag = "#" + re.sub(r"[^0-9a-z_]", "", str(tag).lower())
        if len(tag) > 1 and tag not in hashtags:
            hashtags.append(tag)
    region = str(section("trends").get("region", "US")).strip().upper()
    try:
        score, seconds = int(content.get("min_check_score")), int(content.get("max_short_seconds"))
        volume = float(section("music").get("volume"))
    except (TypeError, ValueError):
        raise ValueError("Score, length and volume must be numbers.")
    if not 0 <= score <= 10 or not 10 <= seconds <= 60 or not 0 <= volume <= 1.5:
        raise ValueError("Score 0-10, length 10-60 seconds, volume 0-1.5.")
    if region != "ALL" and not re.fullmatch(r"[A-Z]{2}", region):
        raise ValueError("Trends: ALL (every country) or a two-letter country code like US or GB.")
    return {"name": name, "contact": contact, "audience": str(channel.get("audience", "")).strip(),
            "voice": " ".join(str(channel.get("voice", "")).split()), "schedule": schedule, "rotation": rotation,
            "animals": animals, "allow_people": bool(content.get("allow_people")), "score": score,
            "seconds": seconds, "region": region, "hashtags": hashtags[:4], "volume": round(volume, 2)}


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
    data["schedule"].pop("publish_times_utc", None)  # the old setting, replaced by the four below
    for key in ("timezone", "first_post"):
        data["schedule"][key] = Q(v["schedule"][key])
    for key in ("every_hours", "posts_per_day"):
        data["schedule"][key] = v["schedule"][key]
    data["formats"]["rotation"] = flow(v["rotation"])
    data["content"]["animals"] = flow(v["animals"])
    data["content"]["allow_people"] = v["allow_people"]
    data["content"]["min_check_score"], data["content"]["max_short_seconds"] = v["score"], v["seconds"]
    data["trends"]["region"] = Q(v["region"])
    data["metadata"]["base_hashtags"] = flow(v["hashtags"])
    data["music"]["volume"] = v["volume"]
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return get_settings()
