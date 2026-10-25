"""
The dashboard: serves the page (index.html, app.css, app.js in this folder) and the
JSON API it calls.

Locally it's at http://localhost:8000 and answers only on this computer. On Vercel it's
switched off unless DASHBOARD_PASSWORD is set (the browser then asks for it).
Making cases, animating and uploading run in a background thread; the page polls progress.
While the database is on this computer, a loop here also runs the channel every minute: a due
slot first, then keeping cases ready to post, their previews rendered, and the day's numbers
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
import research_fetch
import short_render
import slots
import trends_fetch
import voice_tts
import youtube_auth
from agents import AGENTS, analyst, animator, editor, hosts, publisher, researcher, writer
from agents.base import act, playbook
from common import ON_VERCEL, ROOT, env, is_true, load_config, tmp_path, update_config

UI_DIR = Path(__file__).resolve().parent
UI_FILES = {
    "app.css": (UI_DIR / "app.css", "text/css"),
    "app.js": (UI_DIR / "app.js", "text/javascript"),
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
CLIENT_FILE = ROOT / "credentials.json"
MAX_MUSIC_BYTES = 30 * 1024 * 1024
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9 ._()-]+")
LEGACY = {"sketch": "Cartoon version"}  # other earlier formats were the cute-animal version
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
        return "Agents 1-3: making the next case"
    if name == "publish":
        return f"Agent 4: animating case #{kwargs['video_id']}"
    return "Agent 6: reading the numbers"


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
            "category": (v["plan"].get("brief") or {}).get("category"), "youtube_id": v["youtube_id"],
            "publish_at": v["publish_at"]}


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
    cases = [v for v in videos if v["format"] == db.FORMAT and v["status"] != "skipped"]
    scheduled = [v for v in videos if v["status"] == "scheduled" and v["publish_at"] and slots.parse(v["publish_at"]) > now]
    previews = [v for v in planned if animator.preview_path(v["id"]).exists()]
    facts = sum(len((v["plan"].get("research") or {}).get("facts") or []) for v in planned)
    book = playbook()
    metric = {
        "editor": (len(cases), "cases chosen"),
        "researcher": (facts, "facts checked for the queue"),
        "writer": (len(planned), "scripts waiting"),
        "animator": (len(previews), "previews ready to watch"),
        "publisher": (len(scheduled), "Shorts scheduled ahead"),
        "analyst": (book.get("samples") or 0, "cases in the playbook"),
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
    ids = cfg.get("hosts") or {}
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
        "approvals": sum(1 for v in planned if v["plan"].get("approval") == "waiting"),
        "ready": sum(1 for v in planned if db.ready(v)),
        "requests": len(db.list_topics("waiting")),
        "hosts_ready": bool(ids.get("presenter") and ids.get("cohost")),
        "task": next((_public(t) for t in _tasks.values() if t["status"] == "running"), None),
    }


@router.post("/api/pause")
async def set_pause(request: Request):
    _local_only("The pause switch")
    paused = bool((await request.json()).get("paused"))
    set_key(str(ROOT / ".env"), "PAUSED", "true" if paused else "false")
    os.environ["PAUSED"] = "true" if paused else "false"
    return {"paused": paused}


# --- cases ------------------------------------------------------------------

def _stamp(path: Path) -> str:
    return f"?v={int(path.stat().st_mtime)}"


def _host_json(spec: dict) -> dict:
    return {"id": spec.get("id"), "name": spec["name"], "role": spec["role"], "voice": spec["voice"],
            "speed": spec.get("speed", 1.0), "image": f"/media/character/{spec['id']}.png" if spec.get("id") else None}


def _research_json(video_id: int, pack: dict) -> dict:
    return {
        "sources": pack.get("sources") or [], "timeline": pack.get("timeline") or [], "stats": pack.get("stats") or [],
        "facts": [{k: f.get(k) for k in ("id", "claim", "source", "quote", "kind", "calculated")} for f in pack.get("facts") or []],
        "series": [{k: s.get(k) for k in ("id", "title", "country", "unit", "points", "forecast_from", "source", "url")}
                   for s in pack.get("series") or []],
        "images": [{**{k: i.get(k) for k in ("id", "shows", "title", "author", "licence", "page")},
                    "url": f"/media/research/{video_id}/{i['id']}.jpg"} for i in pack.get("images") or []],
        "dropped": pack.get("dropped", 0), "notes": pack.get("notes") or [], "answer": pack.get("answer", ""),
    }


def _video_json(v: dict) -> dict:
    plan = v["plan"]
    meta = plan.get("metadata") or {}
    preview, cover = animator.preview_path(v["id"]), animator.cover_path(v["id"])
    out = {
        "id": v["id"], "status": v["status"], "created_at": v["created_at"], "publish_at": v["publish_at"],
        "slot": v["slot"], "error": v["error"], "youtube_id": v["youtube_id"],
        "studio_url": f"https://studio.youtube.com/video/{v['youtube_id']}/edit" if v["youtube_id"] else None,
        "legacy": None if v["format"] == db.FORMAT else LEGACY.get(v["format"], "Cute-animal version"),
        "title": meta.get("title") or v["theme"], "description": meta.get("description"),
        "hashtags": meta.get("hashtags") or [], "duration": (plan.get("render") or {}).get("seconds"),
        "music": plan.get("music"), "music_credit": short_render.music_credit(plan.get("music")),
        "preview": f"/media/preview/{v['id']}.mp4{_stamp(preview)}" if preview.exists() else None,
        "cover": f"/media/cover/{v['id']}.jpg{_stamp(cover)}" if cover.exists() else None,
    }
    if out["legacy"] or not plan.get("script"):
        return out
    brief, script, pack = plan["brief"], plan["script"], plan.get("research") or {}
    return {
        **out,
        "category": brief.get("category"), "topic": brief.get("topic"), "angle": brief.get("angle"),
        "why_now": brief.get("why_now"), "trend": brief.get("trend"), "follow_up_of": brief.get("follow_up_of"),
        "from_request": bool(brief.get("request_id")), "from_comment": bool(brief.get("comment_id")),
        "approval": plan.get("approval"), "approved_at": plan.get("approved_at"),
        "case_title": script.get("case_title"), "lines": script.get("lines") or [], "key_points": script.get("key_points") or [],
        "music_mood": script.get("music_mood"), "estimate": script.get("seconds"), "cut": script.get("cut", 0),
        "hosts": [_host_json(h) for h in plan.get("hosts") or []],
        "research": _research_json(v["id"], pack),
        "visuals": writer.visual_menu(pack, brief),
        "full_description": publisher.description(meta, plan),
    }


def _planned_or_409(video_id) -> dict:
    video = db.get_video(int(video_id)) if video_id is not None else None
    if not video:
        raise HTTPException(404, "No such Short.")
    if video["status"] != "planned":
        raise HTTPException(409, f"Short #{video['id']} is {video['status']}; only queued cases can be changed.")
    return video


@router.get("/api/videos")
def videos(limit: int = 60):
    return [_video_json(v) for v in db.list_videos(limit)]


@router.patch("/api/videos/{video_id}")
async def edit_video(video_id: int, request: Request):
    video = _planned_or_409(video_id)
    if video["format"] != db.FORMAT:
        raise HTTPException(409, "Shorts from earlier versions can't be edited here.")
    try:
        plan = writer.apply_edits(video["plan"], await request.json())
    except (ValueError, IndexError, KeyError) as e:
        raise HTTPException(422, str(e))
    db.update_video(video_id, plan=plan)
    animator.preview_path(video_id).unlink(missing_ok=True)  # the old render no longer matches the script
    return _video_json(db.get_video(video_id))


@router.post("/api/videos/{video_id}/approve")
def approve_video(video_id: int):
    try:
        publisher.approve(video_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
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


@router.get("/media/research/{video_id}/{image_id}.jpg", include_in_schema=False)
def research_image(video_id: int, image_id: str):
    video = db.get_video(video_id)
    image = next((i for i in ((video or {}).get("plan", {}).get("research") or {}).get("images") or []
                  if i["id"] == image_id), None)
    if not image:
        raise HTTPException(404)
    path = researcher.image_path(image)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


# --- topics: your requests, viewers' comments, the Editor's choices -----------

@router.get("/api/topics")
def topics():
    cfg = load_config()
    briefs = []
    for v in db.list_videos(80):
        brief = v["plan"].get("brief")
        if v["format"] == db.FORMAT and brief:
            briefs.append({"id": v["id"], "created_at": v["created_at"], "status": v["status"],
                           "approval": v["plan"].get("approval"), "title": v["plan"].get("metadata", {}).get("title"),
                           **{k: brief.get(k) for k in ("category", "topic", "angle", "why_now", "trend", "follow_up_of",
                                                        "needs_approval")},
                           "from_request": bool(brief.get("request_id")), "from_comment": bool(brief.get("comment_id"))})
    return {"requests": db.list_topics(limit=60), "comments": db.recent_comments(days=60, limit=60, unused=False),
            "briefs": briefs, "categories": editor.CATEGORIES, "weights": cfg["cases"].get("categories") or {},
            "follow_ups": cfg["cases"].get("follow_ups", True), "comment_requests": cfg["cases"].get("comment_requests", True)}


@router.post("/api/topics")
async def add_topic(request: Request):
    text = " ".join(str((await request.json()).get("text", "")).split())
    if not 3 <= len(text) <= 200:
        raise HTTPException(422, "Describe the case in 3 to 200 characters, e.g. “Why Nokia failed”.")
    topic_id = db.add_topic(text)
    return {"id": topic_id, "text": text}


@router.delete("/api/topics/{topic_id}")
def drop_topic(topic_id: int):
    found = next((t for t in db.list_topics("waiting", limit=500) if t["id"] == topic_id), None)
    if not found:
        raise HTTPException(409, "That request isn't waiting any more.")
    db.set_topic(topic_id, "dropped", reason="Removed by you")
    return {"ok": True}


# --- the hosts --------------------------------------------------------------

def _character_or_404(character_id: int) -> dict:
    found = db.get_characters([character_id])
    if not found:
        raise HTTPException(404, "No such character.")
    return found[0]


@router.get("/api/hosts")
def get_hosts():
    ids = load_config().get("hosts") or {}
    found = db.get_characters([ids[r] for r in hosts.ROLES if ids.get(r)])
    return {
        "hosts": [{**spec, "role_key": role, "look": character_spec.describe(spec),
                   "voice_label": character_spec.VOICES.get(spec["voice"], spec["voice"]),
                   "image": f"/media/character/{spec['id']}.png", "voice_sample": f"/media/voice/{spec['id']}.wav"}
                  for role, spec in zip(hosts.ROLES, found)] if len(found) == 2 else [],
        "parts": character_spec.PARTS, "skin": list(character_spec.SKIN_TONES),
        "hair_color": list(character_spec.HAIR_COLORS), "colors": list(character_spec.COLORS),
        "voices": character_spec.VOICES,
    }


@router.patch("/api/hosts/{role}")
async def edit_host(role: str, request: Request):
    _local_only("Changing the hosts")
    try:
        hosts.update(role, await request.json())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return get_hosts()


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
    _local_only("Making, animating and uploading from the dashboard")
    body = json.loads(await request.body() or b"{}")
    video_id = body.get("video_id")
    if kind == "prepare":
        return _start_task(kind, "Agents 1-3: making a new case",
                           lambda p: jobs.run_job("prepare", count=1, progress=p))
    if kind == "render":
        video = _planned_or_409(video_id)
        if video["format"] != db.FORMAT:
            raise HTTPException(409, "Shorts from earlier versions can't be animated again.")
        return _start_task(kind, f"Agent 4: animating case #{video_id}",
                           lambda p: jobs.run_job("publish", dry_run=True, video_id=video_id, progress=p), video_id)
    if kind == "publish":
        video = _planned_or_409(video_id)
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the YouTube page).")
        if video["format"] == db.FORMAT and not db.ready(video):
            raise HTTPException(409, "This case waits for your OK: approve it first.")
        return _start_task(kind, f"Agent 5: uploading case #{video_id}",
                           lambda p: jobs.run_job("publish", video_id=video_id, progress=p), video_id)
    if kind == "autopilot":
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the YouTube page).")
        return _start_task(kind, "Making the next Short now", _make_next_now)
    if kind == "stats":
        return _start_task(kind, "Agent 6: reading the numbers", lambda p: jobs.run_job("stats", learn=True, progress=p))
    if kind == "hosts":
        return _start_task(kind, "Designing the hosts", lambda p: act("hosts", "Design the hosts", hosts.design, progress=p))
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


# --- signals, results, activity -----------------------------------------------

_trends_lock = threading.Lock()


def _fetch_trends(cfg: dict, refresh: bool) -> dict:
    # One fetch at a time: asking every country takes minutes, and a second fetch alongside would
    # only make Google refuse both. Whoever waited for the lock finds the fresh copy already saved.
    with _trends_lock:
        return jobs.trend_signals(cfg, days_ahead=10, refresh=refresh)


def _wikipedia_signals() -> dict:
    """What the Editor also reads: Wikipedia's Current events and "On this day" (cached by research_fetch)."""
    out = {"news": [], "on_this_day": []}
    try:
        out["news"] = [{"date": e["date"], "section": e["section"], "text": e["text"], "outlets": [l["outlet"] for l in e["links"]]}
                       for e in research_fetch.current_events(3)][:25]
    except Exception as e:
        out["news_error"] = str(e)
    try:
        out["on_this_day"] = research_fetch.on_this_day()[:12]
    except Exception as e:
        out["on_this_day_error"] = str(e)
    return out


@router.get("/api/trends")
def trends(refresh: bool = False):
    cfg = load_config()
    if refresh or ON_VERCEL or db.fresh_note("trends", jobs.TRENDS_FRESH):
        return {**_fetch_trends(cfg, refresh), **_wikipedia_signals()}
    # Out of date: show the last fetch now and get today's in the background; the page asks again.
    if not _trends_lock.locked():
        threading.Thread(target=_fetch_trends, args=(cfg, False), name="trends", daemon=True).start()
    return {**jobs.trend_signals(cfg, days_ahead=10, cached_only=True), **_wikipedia_signals(), "refreshing": True}


@router.get("/api/results")
def results():
    table = analyst.rows(min_age=timedelta(0))
    return {"playbook": playbook(), "rows": table, "min_samples": analyst.MIN_SAMPLES,
            "judged": len(analyst.rows()), "follow_ups": analyst.follow_up_candidates(),
            "comments": len(db.recent_comments(days=60, limit=10_000, unused=False))}


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
    return {**load_config(), "categories_available": editor.CATEGORIES, "editable": not ON_VERCEL}


def _number(value, name: str, low: float, high: float, whole: bool = True):
    try:
        n = int(value) if whole else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.")
    if not low <= n <= high:
        raise ValueError(f"{name}: {low:g} to {high:g}.")
    return n


def _validated(s: dict) -> dict:
    section = lambda name: s.get(name) or {}
    channel, cases = section("channel"), section("cases")
    name = str(channel.get("name", "")).strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("Channel name: 1 to 60 characters.")
    contact = str(channel.get("contact_email") or "").strip()
    if contact and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise ValueError("Contact email doesn't look like an email address.")
    schedule = slots.validate(section("schedule"))
    weights = {c: round(_number((cases.get("categories") or {}).get(c, 0), f"How often: {c}", 0, 5, whole=False), 1)
               for c in editor.CATEGORIES}
    if not any(weights.values()):
        raise ValueError("Case types: switch at least one on.")
    approval = cases.get("approval") or {}
    target = _number(cases.get("target_seconds"), "Target length", 40, 75)
    longest = _number(cases.get("max_seconds"), "Longest case", target, 90)
    hashtags = []
    for tag in section("metadata").get("base_hashtags", []):
        tag = "#" + re.sub(r"[^0-9a-z_]", "", str(tag).lower())
        if len(tag) > 1 and tag not in hashtags:
            hashtags.append(tag)
    region = str(section("trends").get("region", "US")).strip().upper()
    if region != "ALL" and not re.fullmatch(r"[A-Z]{2}", region):
        raise ValueError("Trends: ALL (every country) or a two-letter country code like US or GB.")
    return {"name": name, "show_name": bool(channel.get("show_name")), "contact": contact,
            "audience": str(channel.get("audience", "")).strip(), "voice": " ".join(str(channel.get("voice", "")).split()),
            "schedule": schedule, "weights": weights,
            "approval": {"trending": bool(approval.get("trending")), "politics": bool(approval.get("politics"))},
            "expires": _number(cases.get("approval_expires_days"), "Approval wait", 1, 14),
            "target": target, "longest": longest, "queue": _number(cases.get("queue"), "Ready ahead", 0, 5),
            "follow_ups": bool(cases.get("follow_ups")), "comment_requests": bool(cases.get("comment_requests")),
            "share_alike": bool(section("research").get("share_alike_images")),
            "region": region, "hashtags": hashtags[:4],
            "volume": round(_number(section("music").get("volume"), "Music volume", 0, 1.5, whole=False), 2)}


@router.put("/api/settings")
async def save_settings(request: Request):
    _local_only("Settings")
    try:
        v = _validated(await request.json())
    except ValueError as e:
        raise HTTPException(422, str(e))

    # ruamel keeps the comments in channel.yaml; every user string is quoted so values like
    # 23:00 or NO can't be misread as numbers or booleans when the file is loaded again.
    from ruamel.yaml.comments import CommentedSeq
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q, FoldedScalarString

    def flow(items):
        seq = CommentedSeq([Q(i) for i in items])
        seq.fa.set_flow_style()
        return seq

    def change(data):
        ch, cases = data["channel"], data["cases"]
        ch["name"], ch["audience"], ch["contact_email"] = Q(v["name"]), Q(v["audience"]), Q(v["contact"])
        ch["show_name"], ch["voice"] = v["show_name"], FoldedScalarString(v["voice"])
        for key in ("timezone", "first_post"):
            data["schedule"][key] = Q(v["schedule"][key])
        for key in ("every_hours", "posts_per_day"):
            data["schedule"][key] = v["schedule"][key]
        for key, weight in v["weights"].items():
            cases["categories"][key] = int(weight) if weight == int(weight) else weight
        cases["approval"]["trending"], cases["approval"]["politics"] = v["approval"]["trending"], v["approval"]["politics"]
        cases["approval_expires_days"], cases["queue"] = v["expires"], v["queue"]
        cases["target_seconds"], cases["max_seconds"] = v["target"], v["longest"]
        cases["follow_ups"], cases["comment_requests"] = v["follow_ups"], v["comment_requests"]
        data["research"]["share_alike_images"] = v["share_alike"]
        data["trends"]["region"] = Q(v["region"])
        data["metadata"]["base_hashtags"] = flow(v["hashtags"])
        data["music"]["volume"] = v["volume"]
    update_config(change)
    return get_settings()
