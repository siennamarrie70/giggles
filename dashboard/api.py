"""
The dashboard: serves the page (index.html, app.css, app.js in this folder) and the
JSON API it calls.

Locally it's at http://localhost:8000 and answers only on this computer (asked by its own name, from its own
address: started on every address by mistake, it still refuses the rest of the network). On Vercel it's
switched off unless DASHBOARD_USERNAME and DASHBOARD_PASSWORD are set, the password 12 characters or more.
With both set (on Vercel, or in .env here too) it opens only after the sign-in page (/login): a browser stays
signed in for 30 days through a signed cookie, a new username or password signs every browser out, and ten
wrong tries from one address and that address is refused for ten minutes.
Making cases, animating and uploading run in a background thread; the page polls progress.
While the database is on this computer, a loop here also runs the channel every minute: a due
slot first, then keeping cases ready to post, their previews rendered, and the day's numbers
(jobs.next_chore).
"""

import functools
import hashlib
import hmac
import ipaddress
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, quote, urlsplit

from dotenv import set_key
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

import cloud_secrets
import db
import draw
import host
import instagram
import jobs
import lipsync
import narration
import notify
import research_fetch
import short_render
import slots
import trends_fetch
import voiceprint
import youtube_auth
import youtube_upload
from agents import AGENTS, analyst, animator, editor, publisher, researcher, reviewer, writer
from agents.base import lessons_for, playbook
from common import ON_VERCEL, ROOT, TMP_DIR, background_priority, env, load_config, redact, tmp_path, update_config

UI_DIR = Path(__file__).resolve().parent
UI_FILES = {
    "app.css": (UI_DIR / "app.css", "text/css"),
    "app.js": (UI_DIR / "app.js", "text/javascript"),
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
CLIENT_FILE = ROOT / "credentials.json"
MAX_MUSIC_BYTES = 30 * 1024 * 1024
PREVIEW_PIECE = 2 * 1024 * 1024  # bytes of a case's video served a request
MIN_PASSWORD = 12                # characters, at least, in the dashboard's password
MIN_STRENGTH = 4                 # zxcvbn's score (0-4) the password needs: 4 = 10^10 guesses or more
SESSION_COOKIE, SESSION_DAYS = "dashboard_session", 30  # a browser stays signed in this long (or until it signs out)
WRONG_TRIES, WRONG_FOR = 10, 600  # wrong sign-ins from one address within WRONG_FOR seconds before it's refused
WRONG_ALL = 30                    # ...and from all addresses together, before sign-in rests here for everyone
MAX_FORM = 8192                   # bytes, at most, in a sign-in form
_wrong: dict[str, list[float]] = {}  # (per server instance: Vercel may run a few, so it's a brake, not a wall;
_wrong_lock = threading.Lock()       # Vercel's firewall rate limit is the wall: workflows/setup_accounts.md step 7)
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9 ._()-]+")
LEGACY = {"case": "Cartoon-host version", "sketch": "Cartoon version"}  # other earlier formats: the cute-animal version
HOST_FILES = {"base": "base.png", "sheet": "sheet.png"}  # the Professor's drawings the page may show
SIGN_IN_SAYS = {"wrong": ("bad", "Wrong username or password."),
                "wait": ("bad", f"Too many wrong tries from here. Try again in {WRONG_FOR // 60} minutes."),
                "busy": ("bad", f"Sign-in is resting after many wrong tries from around the internet. Try again in "
                                f"{WRONG_FOR // 60} minutes; browsers already signed in still work."),
                "out": ("ok", "You're signed out.")}


def _visitor(request: Request) -> str:
    """Who's asking, for counting wrong sign-ins: on Vercel the address in x-real-ip (Vercel sets it itself, so it
    can't be faked; here a request's own address). An IPv6 address counts with its whole /64, which one home or phone
    gets, so changing the rest of it wins no more tries."""
    who = (request.headers.get("x-real-ip") if ON_VERCEL else None) or (request.client.host if request.client else "?")
    try:
        ip = ipaddress.ip_address(who.strip())
    except ValueError:
        return who[:64]
    if ip.version == 6 and not ip.ipv4_mapped:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip.ipv4_mapped if ip.version == 6 else ip)


def _from_here(request: Request) -> bool:
    """Whether the request came from this computer itself."""
    address = request.client.host if request.client else ""
    if address == "testclient":  # (the test suite's)
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (ip.ipv4_mapped or ip).is_loopback if ip.version == 6 else ip.is_loopback


def _login() -> tuple[str, str] | None:
    """The dashboard's username and password (DASHBOARD_USERNAME, DASHBOARD_PASSWORD), when both are set."""
    user, password = (env("DASHBOARD_USERNAME") or "").strip(), env("DASHBOARD_PASSWORD") or ""
    return (user, password) if user and password else None


@functools.lru_cache(maxsize=4)
def _too_easy(user: str, password: str) -> str | None:
    """Why this password is too easy to guess, or None. zxcvbn knows common passwords, words, names, years, dates and
    keyboard patterns, and is told the username and the channel's names, so "Channel@2026" counts as guessable."""
    from zxcvbn import zxcvbn

    channel = load_config().get("channel") or {}
    known = [user, channel.get("name"), env("INSTAGRAM_USERNAME"), env("VERCEL_GIT_REPO_SLUG"),
             env("VERCEL_GIT_REPO_OWNER"), "professor", "dashboard", "control room"]
    result = zxcvbn(password[:100], user_inputs=[str(w) for w in known if w])
    if result["score"] >= MIN_STRENGTH:
        return None
    return (result["feedback"].get("warning") or "it follows a pattern people often use").rstrip(".")


def _open_here(request: Request) -> tuple[str, str] | None:
    """Whether the dashboard answers this request at all, and its login if it has one. Local: this computer only.
    Vercel: only with a login (the whole internet can try it). Only one of the two set, a password under MIN_PASSWORD
    characters, or one too easy to guess (_too_easy), keeps it off."""
    login = _login()
    half_set = not login and bool((env("DASHBOARD_USERNAME") or "").strip() or env("DASHBOARD_PASSWORD"))
    if ON_VERCEL:
        if not (login or half_set):
            raise HTTPException(404)
    elif request.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS or not _from_here(request):
        raise HTTPException(403, "The dashboard only answers on localhost.")
    if half_set:
        raise HTTPException(503, "The dashboard is off: it needs both DASHBOARD_USERNAME and DASHBOARD_PASSWORD.")
    if login and len(login[1]) < MIN_PASSWORD:
        raise HTTPException(503, f"The dashboard is off: its password (DASHBOARD_PASSWORD) needs {MIN_PASSWORD} "
                                 "characters or more.")
    if login and (why := _too_easy(*login)):
        raise HTTPException(503, f"The dashboard is off: its password (DASHBOARD_PASSWORD) is too easy to guess "
                                 f"({why}). Choose a longer one, such as four or five unrelated words.")
    return login


def _same(given: str, wanted: str) -> bool:
    """Equal, compared in constant time over fixed-length digests, so not even the length shows in the timing."""
    return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(wanted.encode()).digest())


@functools.lru_cache(maxsize=4)
def _session_key(user: str, password: str, pepper: str) -> bytes:
    """The key that signs this login's cookies: made slowly from the login (scrypt), then mixed with CRON_SECRET when
    it's set (a secret only the server has), so a stolen cookie can't be used to guess the password. A new username,
    password or CRON_SECRET gives a new key, which signs every browser out."""
    slow = hashlib.scrypt(password.encode(), salt=b"ezzy dashboard|" + user.encode(), n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.new(pepper.encode(), slow, hashlib.sha256).digest() if pepper else slow


def _session(login: tuple[str, str], until: int) -> str:
    """A sign-in cookie's value: when it ends (Unix time), and its signature."""
    key = _session_key(*login, env("CRON_SECRET") or "")
    return f"{until}.{hmac.new(key, str(until).encode(), hashlib.sha256).hexdigest()}"


def _signed_in(request: Request, login: tuple[str, str]) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    until = cookie.partition(".")[0]
    return (bool(re.fullmatch(r"[0-9]{1,12}", until)) and time.time() < int(until)
            and hmac.compare_digest(cookie.encode(), _session(login, int(until)).encode()))


def _same_site(request: Request) -> bool:
    """Whether a form was sent from this site's own page (as the browser says, or by the Origin it names)."""
    if site := request.headers.get("sec-fetch-site"):
        return site in ("same-origin", "none")
    origin = request.headers.get("origin")
    return not origin or urlsplit(origin).netloc == request.headers.get("host", "")


def _locked_out(who: str) -> str | None:
    """Why sign-in is refused now: "wait" when this address has had WRONG_TRIES wrong sign-ins within WRONG_FOR, "busy"
    when all addresses together have had WRONG_ALL (sign-in then rests here for everyone; signed-in browsers still
    work). None when it isn't."""
    now = time.time()
    with _wrong_lock:
        if sum(now - t < WRONG_FOR for t in _wrong.get(who, [])) >= WRONG_TRIES:
            return "wait"
        if sum(now - t < WRONG_FOR for times in _wrong.values() for t in times) >= WRONG_ALL:
            return "busy"
    return None


def _wrong_try(who: str) -> None:
    now = time.time()
    with _wrong_lock:
        for key in [k for k, times in _wrong.items() if now - max(times) > WRONG_FOR]:  # (the ones that stopped)
            _wrong.pop(key, None)
        _wrong[who] = [t for t in _wrong.get(who, []) if now - t < WRONG_FOR] + [now]
        count = len(_wrong[who])
    print(f"Dashboard: a wrong username or password from {who} ({count} in {WRONG_FOR // 60} minutes)", flush=True)


def guard(request: Request) -> None:
    """Where the dashboard answers (_open_here) and, with a login, only once signed in: the page itself goes to
    /login, and its calls get a 401 that sends it there. Changes need the page's own header, which a browser won't
    add for another website (so other sites can't press buttons here)."""
    login = _open_here(request)
    if login and not _signed_in(request, login):
        if request.method == "GET" and request.url.path == "/":
            raise HTTPException(303, headers={"Location": "/login"})
        raise HTTPException(401, {"message": "You're signed out: sign in again.", "signin": True})
    if request.method not in ("GET", "HEAD") and request.headers.get("x-dashboard") != "1":
        raise HTTPException(403, "Missing dashboard header.")


router = APIRouter(dependencies=[Depends(guard)])
sign_in = APIRouter()  # the sign-in page and the page's own files: open before signing in, unlike `router`


@sign_in.get("/login", include_in_schema=False)
def sign_in_page(request: Request, e: str = ""):
    login = _open_here(request)
    if not login or _signed_in(request, login):  # (nothing to sign in to, or signed in already)
        return RedirectResponse("/", 303)
    kind, says = SIGN_IN_SAYS.get(e, ("", ""))
    message = (f'<p class="signin-msg {kind}" role="{"alert" if kind == "bad" else "status"}">{says}</p>'
               if says else "")
    page = Template((UI_DIR / "login.html").read_text(encoding="utf-8")).substitute(message=message, days=SESSION_DAYS)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@sign_in.post("/login", include_in_schema=False)
async def sign_in_form(request: Request):
    """The sign-in form. Right: this browser gets a cookie signed for SESSION_DAYS, readable by this server only and
    sent only over https online. Wrong: back to the page; WRONG_TRIES from one address lock it out for WRONG_FOR, and
    WRONG_ALL from everywhere rest sign-in here for that long. Only the exact username and password open it: both are
    always compared (so a wrong username takes as long as a wrong password), with nothing trimmed but the username's
    outer spaces, and a form that isn't plain UTF-8 or is over MAX_FORM bytes counts for nothing."""
    login = _open_here(request)
    if not login:
        return RedirectResponse("/", 303)
    if not _same_site(request):
        raise HTTPException(403, "Sign in on the dashboard's own page.")
    who = _visitor(request)
    if why := _locked_out(who):
        return RedirectResponse(f"/login?e={why}", 303)
    body = b""
    async for piece in request.stream():  # (read up to MAX_FORM, never the whole of an oversized body)
        body += piece
        if len(body) > MAX_FORM:
            raise HTTPException(413, "The sign-in form is too long.")
    try:
        form = parse_qs(body.decode("utf-8"), max_num_fields=10, errors="strict")
    except (UnicodeDecodeError, ValueError):
        form = {}
    user, password = (form.get("username") or [""])[0].strip(), (form.get("password") or [""])[0]
    right_user, right_password = _same(user, login[0]), _same(password, login[1])
    if not (right_user and right_password):
        _wrong_try(who)
        return RedirectResponse("/login?e=wrong", 303)
    until = int(time.time()) + SESSION_DAYS * 86400
    answer = RedirectResponse("/", 303)
    answer.set_cookie(SESSION_COOKIE, _session(login, until), max_age=SESSION_DAYS * 86400, path="/", httponly=True,
                      secure=ON_VERCEL or request.url.scheme == "https", samesite="lax")
    return answer


@sign_in.post("/logout", include_in_schema=False)
def sign_out(request: Request, response: Response):
    _open_here(request)
    if request.headers.get("x-dashboard") != "1":
        raise HTTPException(403, "Missing dashboard header.")
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=ON_VERCEL or request.url.scheme == "https",
                           samesite="lax")
    return {"signed_out": True}


async def _json(request: Request) -> dict:
    """The request's JSON object (422 if it isn't one, instead of an error)."""
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(422, "The request isn't JSON.") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "The request isn't a JSON object.")
    return body


def _local_only(what: str) -> None:
    if ON_VERCEL:
        raise HTTPException(409, f"{what}: only from the dashboard on your computer.")


# --- background tasks -----------------------------------------------------

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _public(task: dict) -> dict:
    return {k: task[k] for k in ("id", "kind", "label", "status", "steps", "result", "error", "started",
                                 "finished", "video_id")}


def _awake(on: bool) -> None:
    """While a task runs, Windows doesn't put this computer to sleep (it sleeps after 5 idle minutes otherwise,
    and a sleeping laptop stops the morning run). Per thread: it ends with the task's thread anyway."""
    if sys.platform == "win32":
        import ctypes

        continuous, system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(continuous | (system_required if on else 0))


SIDE_TASKS = ("connect", "reel", "remake", "stats")  # Google's page waiting for you, Reels going out, a video made for
# its Reel, and the Analyst reading the numbers (a minute at most: it never waits for a morning run to end)


def _start_task(kind: str, label: str, work, video_id: int | None = None) -> dict:
    """One task at a time; `work(progress)` runs in a thread and reports steps through progress(). Connecting YouTube
    only waits for you on Google's page, and Post now on Instagram only sends a finished video, so each runs beside the
    rest (a morning run takes hours), one of each at a time."""
    side = kind in SIDE_TASKS
    with _tasks_lock:
        busy = next((t for t in _tasks.values() if t["status"] == "running"
                     and (t["kind"] == kind if side else t["kind"] not in SIDE_TASKS)), None)
        if busy:
            raise HTTPException(409, f"Busy: {busy['label']}. Try again when it finishes.")
        task = {"id": uuid.uuid4().hex[:12], "kind": kind, "label": label, "status": "running", "steps": [],
                "result": None, "error": None, "started": time.time(), "finished": None, "video_id": video_id}
        _tasks[task["id"]] = task
        for old in sorted(_tasks.values(), key=lambda t: t["started"])[:-20]:
            _tasks.pop(old["id"], None)

    def progress(text: str) -> None:
        task["steps"].append({"at": round(time.time() - task["started"], 1), "text": redact(text)})

    def run() -> None:
        _awake(True)
        try:
            task["result"] = work(progress)
            task["status"] = "done"
        except Exception as e:
            task["error"] = redact(e)
            task["status"] = "error"
        finally:
            task["finished"] = time.time()
            _awake(False)

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
    if not result["manage"]:
        progress("Stop and Delete still can't work: “See, edit, and permanently delete your YouTube videos…” was "
                 "left unticked.")
    return result


# --- the channel on this computer -----------------------------------------

LOOP_SECONDS = 60
RETRY_AFTER_FAILURE = 20 * 60  # after a failed run, wait before the next try instead of hammering the APIs
_loop_started = False


def autopilot_here() -> bool:
    """With the database on this computer, the dashboard runs the channel itself. With a cloud
    database (DATABASE_URL), GitHub Actions does (.github/workflows/morning.yml and reels.yml): checking
    Neon every minute from here would keep its free database awake around the clock."""
    return not ON_VERCEL and not (env("DATABASE_URL") or env("POSTGRES_URL"))


def _chore_label(name: str, kwargs: dict) -> str:
    if name == "morning":
        return "Today's run: making the day's Shorts"
    if name == "autopilot":
        slot = jobs.due_slot()
        return f"Autopilot: making the {jobs.clock(slot, slots.plan())} Short" if slot else "Autopilot"
    if name == "prepare":
        return "Agents 1-3: making the next case"
    if name == "publish":
        turned_down = (((db.get_video(kwargs["video_id"]) or {}).get("plan") or {}).get("review") or {}).get("held")
        return (f"Agents 4-5: making case #{kwargs['video_id']} again (the Reviewer turned it down)" if turned_down
                else f"Agents 4-5: making and reviewing case #{kwargs['video_id']}")
    return "Agent 7: reading the numbers"


def _post_due_reels() -> None:
    """Reels whose slot has come go out beside whatever else is going (a morning run takes hours, or waits hours for
    Cloudflare), as a task of their own."""
    if publisher.reels_due():
        try:
            _start_task("reel", "Agent 6: posting to Instagram", lambda p: jobs.run_job("instagram", progress=p))
        except HTTPException:
            pass  # a Reel is going out already; the next minute looks again


def _read_due_numbers() -> None:
    """The Analyst reads the day's numbers beside whatever else is going (left for when nothing else was, it read
    nothing from 2026-10-26 to 28: there was always a morning run or a case to make)."""
    if jobs.stats_due():
        try:
            _start_task("stats", "Agent 7: reading the numbers", lambda p: jobs.run_job("stats", progress=p))
        except HTTPException:
            pass  # reading them already


def _autopilot_loop() -> None:
    last = None
    while True:
        time.sleep(LOOP_SECONDS)
        try:
            if not autopilot_here() or jobs.paused():
                continue
            _post_due_reels()
            _read_due_numbers()
            if last and last["status"] == "error" and time.time() - last["finished"] < RETRY_AFTER_FAILURE:
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
        background_priority()  # the morning run's renders give way to whatever you're doing on this computer
        if autopilot_here():  # the runs left open by the last time this program stopped, and the Shorts they were
            db.abandon_runs()  # making: picked up again at once, not 15 minutes later (nothing else makes them here)
            db.release_stale(db.now_iso(timedelta(seconds=1)))
        threading.Thread(target=_autopilot_loop, name="autopilot", daemon=True).start()


# --- page -----------------------------------------------------------------

@router.get("/", include_in_schema=False)
def page():
    return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})


@sign_in.get("/ui/{name}", include_in_schema=False)
def ui_file(name: str, request: Request):
    _open_here(request)  # (the sign-in page needs the style sheet before signing in; the code is public anyway)
    if name not in UI_FILES:
        raise HTTPException(404)
    path, media_type = UI_FILES[name]
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


# --- overview -------------------------------------------------------------

def _slot_video(v: dict | None, live: dict | None = None) -> dict | None:
    if not v:
        return None
    meta = v["plan"].get("metadata", {})
    return {"id": v["id"], "status": v["status"], "title": meta.get("title") or v["theme"],
            "category": (v["plan"].get("brief") or {}).get("category"), "youtube_id": v["youtube_id"],
            "publish_at": v["publish_at"], "slot": v["slot"], "platforms": publisher.platforms(v, live)}


def _autopilot_state(cfg: dict) -> dict:
    sched = slots.plan(cfg)
    now = datetime.now(timezone.utc)
    shown = slots.shown_day(now, sched)
    day = slots.day_slots(shown, sched)
    board = jobs.slot_board(day[0], day[-1], sched, now)
    last = db.last_run("morning")
    upcoming = jobs.slot_board(now, now + timedelta(days=2), sched, now)
    try:
        next_open = slots.iso(jobs.next_open_slot(jobs.MANUAL_LEAD, now, sched))
    except RuntimeError:
        next_open = None
    return {
        "here": autopilot_here(),
        "schedule": {k: sched[k] for k in ("timezone", "first_post", "every_hours", "posts_per_day", "make_at")},
        "run": {"starts": slots.iso(slots.run_starts(shown, sched)), "slots": len(board),
                "scheduled": sum(1 for s in board if s["state"] in ("scheduled", "posted")),
                "running": bool(last and not last["finished_at"]), "last": _run_json(last)},
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
    passed = [v for v in planned if reviewer.passed(v["plan"])]
    facts = sum(len((v["plan"].get("research") or {}).get("facts") or []) for v in planned)
    book = playbook()
    metric = {
        "editor": (len(cases), "cases chosen"),
        "researcher": (facts, "facts checked for the queue"),
        "writer": (len(planned), "scripts waiting"),
        "animator": (len(previews), "videos made for the queue"),
        "reviewer": (len(passed), "videos passed, ready to post"),
        "publisher": (len(scheduled), "Shorts scheduled ahead"),
        "analyst": (book.get("samples") or 0, "cases in the playbook"),
    }
    out = []
    for agent in AGENTS:
        count, what = metric[agent["key"]]
        out.append({**agent, "last": _run_json(db.last_run(agent["key"], ok=None)), "count": count, "what": what})
    return out


def _youtube_limit() -> dict | None:
    """While YouTube's daily upload limit holds: when it should take the channel's next upload (tools/jobs.py)."""
    room = jobs.upload_room_at()
    if not room or room <= datetime.now(timezone.utc):
        return None
    return {"room": slots.iso(room), "count": (db.fresh_note("youtube_limit", timedelta(hours=24)) or {}).get("count")}


@router.get("/api/state")
def state():
    cfg = load_config()
    planned = db.planned_videos()
    return {
        "channel": cfg["channel"]["name"],
        "local": not ON_VERCEL,
        "login": _login() is not None,  # (the page then offers Sign out)
        "paused": jobs.paused(),
        "services": {
            "gemini": bool(env("GEMINI_API_KEY")),
            "youtube": youtube_auth.is_configured(),
            "youtube_manage": _can_manage(),
            "telegram": notify.is_configured(),
            "database": "cloud" if env("DATABASE_URL") or env("POSTGRES_URL") else "local",
            "music": len(short_render.music_tracks()),
            "lipsync": lipsync.ready(),
            "instagram": {"connected": instagram.is_configured(), "on": publisher.reels_on(),
                          "username": env("INSTAGRAM_USERNAME"), "down": publisher.instagram_down()},
        },
        "autopilot": _autopilot_state(cfg),
        "events": trends_fetch.calendar_signals(datetime.now(timezone.utc).date(), 10)["events"],
        "counts": db.status_counts(),
        "agents": _agents(planned),
        "approvals": sum(1 for v in planned if v["plan"].get("approval") == "waiting"),
        "held": sum(1 for v in planned if (v["plan"].get("review") or {}).get("held")),
        "ready": sum(1 for v in planned if db.ready(v)),
        "requests": len(db.list_topics("waiting")),
        "host": {"ready": (host.HOST_DIR / "rig.json").exists(), "name": (cfg.get("host") or {}).get("name", "The Professor"),
                 "voice": (cfg.get("voice") or {}).get("name") or narration.VOICE, **_voice_state()},
        "drawing": _drawing_state(),
        "youtube_limit": _youtube_limit(),
        # Google's page waiting for you comes first, then a Reel you're posting: the dashboard follows it, then the run
        "task": next((_public(t) for t in sorted(_tasks.values(), key=lambda t: (t["kind"] != "connect", t["kind"] != "reel"))
                      if t["status"] == "running"), None),
    }


@router.post("/api/pause")
async def set_pause(request: Request):
    """The pause switch: kept in the database, so it stops the morning run in the cloud too (and in .env here)."""
    paused = bool((await _json(request)).get("paused"))
    db.set_paused(paused)
    if not ON_VERCEL:
        set_key(str(ROOT / ".env"), "PAUSED", "true" if paused else "false")
        os.environ["PAUSED"] = "true" if paused else "false"
    return {"paused": jobs.paused()}


# --- cases ------------------------------------------------------------------

def _stamp(path: Path) -> str:
    return f"?v={int(path.stat().st_mtime)}"


def _research_json(video_id: int, pack: dict) -> dict:
    clips = lambda key: [{**{k: c.get(k) for k in ("id", "shows", "query", "title", "year", "source", "credit", "page_url",  # noqa: E731
                                                     "duration")},
                          "thumb": f"/media/clip/{video_id}/{c['id']}.jpg"} for c in pack.get(key) or []]
    return {
        "sources": pack.get("sources") or [], "timeline": pack.get("timeline") or [], "stats": pack.get("stats") or [],
        "facts": [{k: f.get(k) for k in ("id", "claim", "source", "quote", "kind", "calculated")} for f in pack.get("facts") or []],
        "series": [{k: s.get(k) for k in ("id", "title", "country", "unit", "points", "forecast_from", "source", "url")}
                   for s in pack.get("series") or []],
        "images": [{**{k: i.get(k) for k in ("id", "shows", "title", "author", "licence", "page")},
                    "url": f"/media/research/{video_id}/{i['id']}.jpg"} for i in pack.get("images") or []],
        "footage": clips("footage"), "archive": clips("archive"), "story": pack.get("story") or {},
        "dropped": pack.get("dropped", 0), "notes": pack.get("notes") or [], "answer": pack.get("answer", ""),
    }


def _drawing_state() -> dict:
    """The drawn look's state: is it on, is Cloudflare connected, is it resting (and why), today's free drawing, and
    whether Shorts are made with real footage meanwhile (fallback) or wait."""
    rest = animator.drawing_resting()
    today = draw.spent_today()
    return {"look": draw.style(), "look_now": draw.style_now(), "fallback": draw.fallback(),
            "configured": draw.is_configured(), "resting": animator.drawing_rest_until(),
            "why": (rest or {}).get("why"), "pictures": today["pictures"], "neurons": round(today["neurons"]),
            "budget": draw.BUDGET}


def _drawings_json(video_id: int, plan: dict) -> dict:
    """A drawn case's drawings, by the number of the line each starts on: their pictures' addresses."""
    return {n: f"/media/scene/{video_id}/{n}.jpg{_stamp(Path(path))}" for n, path in (plan.get("drawings") or {}).items()
            if Path(path).exists()}


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
        "platforms": publisher.platforms(v) if v["status"] in ("making", "scheduled") else None,
    }
    if out["legacy"] or not plan.get("script"):
        return out
    brief, script, pack = plan.get("brief") or {}, plan["script"], plan.get("research") or {}
    drawn = script.get("look") == "drawn"
    return {
        **out,
        "look": "drawn" if drawn else "footage", "drawings": _drawings_json(v["id"], plan) if drawn else {},
        "switched": plan.get("switched"),
        "category": brief.get("category"), "topic": brief.get("topic"), "angle": brief.get("angle"),
        "paradox": brief.get("paradox"),
        "why_now": brief.get("why_now"), "trend": brief.get("trend"), "follow_up_of": brief.get("follow_up_of"),
        "from_request": bool(brief.get("request_id")), "from_comment": bool(brief.get("comment_id")),
        "approval": plan.get("approval"), "approved_at": plan.get("approved_at"), "approved_by": plan.get("approved_by"),
        "case_title": script.get("case_title"), "lines": script.get("lines") or [],
        "music_mood": script.get("music_mood"), "estimate": script.get("seconds"), "cut": script.get("cut", 0),
        "retention": script.get("retention") or {}, "habits": script.get("habits") or [],
        "voice": plan.get("voice"), "preview_failed_at": plan.get("preview_failed_at"),
        "review": _review_json(plan), "thumbnail": _thumbnail_json(v["id"], plan),
        "instagram": plan.get("instagram"), "youtube_thumbnail": plan.get("youtube_thumbnail"),
        "held_upload": plan.get("held_upload"),
        "research": _research_json(v["id"], pack),
        "visuals": writer.visual_menu(pack, brief, drawn),
        "full_description": publisher.description(meta, plan),
    }


def _clock(iso: str | None) -> str | None:
    """A time from the database on the schedule's clock (e.g. 21:40), or None."""
    try:
        return slots.clock(slots.parse(iso), slots.plan()) if iso else None
    except (TypeError, ValueError):
        return None


def _review_json(plan: dict) -> dict | None:
    """The Reviewer's verdict on the video as it is now (current: false when it's of an earlier version)."""
    verdict = plan.get("review")
    if not verdict:
        return None
    keep = ("passed", "round", "at", "issues", "changes", "held", "held_because", "override", "look", "match",
            "loudness", "peak", "seconds", "words_per_second")
    return {**{k: verdict.get(k) for k in keep}, "current": reviewer.current(plan) is not None,
            "history": [{k: h.get(k) for k in ("round", "passed", "issues", "changes")} for h in verdict.get("history") or []],
            "max_rounds": reviewer.MAX_ROUNDS, "remakes": int(plan.get("remakes") or 0),
            "remake_at": _clock(verdict.get("remake_at")) if verdict.get("held") else None}


def _still_thumb(video_id: int, name: str) -> str | None:
    kind, _, ref = name.partition(":")
    if kind == "scene":
        return f"/media/scene/{video_id}/{ref}.jpg"
    if kind == "photo":
        return f"/media/research/{video_id}/{ref}.jpg"
    if kind in ("footage", "archive"):
        return f"/media/clip/{video_id}/{ref}.jpg"
    return None


def _thumbnail_json(video_id: int, plan: dict) -> dict:
    """The thumbnail as made, and the stills it can be made from (for the Studio's thumbnail editor)."""
    cover, wide = animator.thumb_paths(video_id)
    made = plan.get("thumbnail") or {}
    drawn = (plan.get("script") or {}).get("look") == "drawn"
    menu = {**writer.visual_menu(plan.get("research") or {}, plan.get("brief") or {}, drawn),
            **{f"scene:{n}": f"the drawing of line {n}" for n in plan.get("drawings") or {}}}
    return {"cover": f"/media/thumb/{video_id}.jpg{_stamp(cover)}" if cover.exists() else None,
            "wide": f"/media/thumb/{video_id}/wide.jpg{_stamp(wide)}" if wide.exists() else None,
            "text": made.get("text") or (plan.get("metadata") or {}).get("thumbnail_text") or "",
            "background": made.get("background"),
            "choices": [{"name": n, "label": menu.get(n, n), "thumb": _still_thumb(video_id, n)}
                        for n in animator.stills(plan)]}


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
        plan = writer.apply_edits(video["plan"], await _json(request))
    except (ValueError, IndexError, KeyError) as e:
        raise HTTPException(422, str(e))
    plan.pop("review", None)  # the script changed: a new video, reviewed afresh, without the old version's fixes
    plan.pop("fixes", None)
    plan.pop("render", None)  # the old render no longer matches the script
    db.update_video(video_id, plan=plan)
    animator.remove(animator.preview_path(video_id))
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
    animator.remove(animator.preview_path(video_id))
    animator.forget(video_id)
    return {"ok": True}


@router.post("/api/videos/{video_id}/review")
async def review_action(video_id: int, request: Request):
    """Your answer to the Reviewer: "post" a video it held (it goes out as it is), or "remake" it (made and reviewed
    again from scratch, the earlier fixes forgotten)."""
    video = _planned_or_409(video_id)
    action = (await _json(request)).get("action")
    plan = video["plan"]
    if action == "post":
        if plan.get("held_upload"):
            raise HTTPException(409, "It's on YouTube as private already: publish or schedule it in YouTube Studio "
                                     f"({plan['held_upload']['studio_url']}), then discard it here.")
        if not plan.get("review") or not animator.preview_path(video_id).exists():
            raise HTTPException(409, "There's no reviewed video to post yet.")
        plan["review"] = {**plan["review"], "held": False, "override": "you", "override_at": db.now_iso()}
    elif action == "remake":
        if (plan.get("review") or {}).get("held"):  # (made again by itself anyway: this only doesn't wait for its time)
            animator.make_again(video, progress=lambda m: None)
            return _video_json(db.get_video(video_id))
        plan.pop("review", None)
        plan.pop("fixes", None)
        plan.pop("render", None)
        animator.remove(animator.preview_path(video_id))
    else:
        raise HTTPException(422, "Unknown answer.")
    db.update_video(video_id, plan=plan)
    return _video_json(db.get_video(video_id))


def _can_manage() -> bool:
    """Whether the YouTube sign-in may stop or delete scheduled Shorts (False if it can't be checked now)."""
    try:
        return youtube_auth.is_configured() and youtube_auth.can_manage()
    except Exception:
        return False


@router.post("/api/videos/{video_id}/youtube")
@router.post("/api/videos/{video_id}/scheduled")  # (its name before 2026-10-27, for a page opened before)
async def youtube_action(video_id: int, request: Request):
    """Your YouTube buttons beside a Short on the Schedule page. Until it's public: "now" makes it public at once (its
    slot stays its own, so no other Short is made for it, and its Reel still waits for the slot); "stop" keeps it on
    YouTube as private (only you can see it; you can still publish it from YouTube Studio). "delete" removes it from
    YouTube, public or not. Stop and Delete free its slot, so the morning run gives it a new Short while the autopilot
    is on (a slot more than an hour gone stays empty), and its Reel goes too unless it's posted already."""
    video = db.get_video(video_id)
    if not video or video["status"] != "scheduled" or not video["youtube_id"]:
        raise HTTPException(409, "Only a Short on the schedule can be changed here.")
    action = (await _json(request)).get("action")
    if action not in ("now", "stop", "delete"):
        raise HTTPException(422, "Unknown action.")
    if action != "delete" and video["publish_at"] and slots.parse(video["publish_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(409, "It's public already: delete it here, or make it private in YouTube Studio.")
    actions = {"now": youtube_upload.publish_now, "stop": youtube_upload.unschedule, "delete": youtube_upload.delete}
    try:
        done = actions[action](video["youtube_id"])
    except youtube_upload.NotAllowed as e:  # the dashboard offers Google's page for it, then tries again
        raise HTTPException(403, {"message": str(e), "reconnect": True})
    except Exception as e:
        raise HTTPException(502, f"YouTube didn't do it: {e}")
    finally:
        _youtube_seen["at"] = 0.0  # what YouTube said a minute ago is out of date now
    if action == "now" and not done.get("gone"):
        db.update_video(video_id, publish_at=db.now_iso(),
                        plan={**video["plan"], "posted_now": {"at": db.now_iso(), "publish_at": video["publish_at"]}})
        return _video_json(db.get_video(video_id))
    was = {"at": db.now_iso(), "slot": video["slot"], "publish_at": video["publish_at"]}
    status = "deleted" if action == "delete" or done.get("gone") else "stopped"
    db.update_video(video_id, status=status, slot=None, publish_at=None, plan={**video["plan"], status: was})
    publisher.cancel_reel(video_id, because=f"{status} on YouTube", keep_video=False)
    return _video_json(db.get_video(video_id))


@router.post("/api/videos/{video_id}/instagram")
async def instagram_action(video_id: int, request: Request):
    """Your Instagram buttons beside a Short on the Schedule page: "now" posts its Reel at once (even before it's public
    on YouTube), as a task beside the rest, since the upload and Instagram's processing take a few minutes; "delete"
    deletes a posted Reel from Instagram, or takes one that isn't posted yet off (it isn't posted then); "schedule"
    makes the video of a Short that went up while Reels were off again (a few minutes), and its Reel then waits for
    its slot."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "No such Short.")
    action = (await _json(request)).get("action")
    reel = publisher.platforms(video)["instagram"]
    if action == "schedule":
        _local_only("Making a video for Instagram")
        if not reel["can"]["schedule"]:
            raise HTTPException(409, f"{reel['why'] or 'Its Reel is waiting or posted already'}.")
        return _start_task("remake", f"Agent 4: making case #{video_id} again for Instagram",
                           lambda p: publisher.run_remake(video, progress=p), video_id)
    if action == "now":
        _local_only("Posting to Instagram")
        if not reel["can"]["now"]:
            raise HTTPException(409, f"{reel['why']}.")
        return _start_task("reel", f"Agent 6: posting case #{video_id} to Instagram",
                           lambda p: publisher.run_instagram(video, progress=p, now=True), video_id)
    if action == "delete":
        if not reel["can"]["delete"]:
            raise HTTPException(409, "There's no Reel to delete or take off.")
        try:
            publisher.drop_reel(video_id)
        except ValueError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            raise HTTPException(502, str(e))
        return _video_json(db.get_video(video_id))
    raise HTTPException(422, "Unknown action.")


_youtube_seen = {"at": 0.0, "ids": frozenset(), "found": {}, "error": None}
ASK_YOUTUBE_EVERY = 120  # seconds: how often the Schedule page asks YouTube about its Shorts (1 unit of 10,000 a day)


def _youtube_now(ids: list[str]) -> dict | None:
    """What YouTube says about these videos (None for one it doesn't have any more), asked at most every
    ASK_YOUTUBE_EVERY seconds; None when it can't be asked."""
    ids = frozenset(i for i in ids if i)
    if not ids or not youtube_auth.is_configured():
        return None
    seen = _youtube_seen
    if time.time() - seen["at"] > ASK_YOUTUBE_EVERY or not ids <= seen["ids"]:
        try:
            seen.update(at=time.time(), ids=ids, found=youtube_upload.statuses(sorted(ids)), error=None)
        except Exception as e:
            seen.update(at=time.time(), ids=ids, found={}, error=str(e)[:200])
    return None if seen["error"] else {i: seen["found"].get(i) for i in ids}


@router.get("/api/schedule")
def schedule_page():
    """The Schedule page: the shown day's slots and the Shorts scheduled for later days, each with where it stands on
    YouTube (asked about them at most every 2 minutes, to notice changes made in YouTube Studio) and on Instagram."""
    sched = slots.plan(load_config())
    now = datetime.now(timezone.utc)
    day = slots.day_slots(slots.shown_day(now, sched), sched)
    board = jobs.slot_board(day[0], day[-1], sched, now)
    shown = {s["video"]["id"] for s in board if s["video"]}
    later = sorted((v for v in db.list_videos(100) if v["status"] == "scheduled" and v["id"] not in shown
                    and v["publish_at"] and slots.parse(v["publish_at"]) > now), key=lambda v: v["publish_at"])
    live = _youtube_now([s["video"]["youtube_id"] for s in board if s["video"]] + [v["youtube_id"] for v in later])
    return {"slots": [{"at": slots.iso(s["slot"]), "state": s["state"], "video": _slot_video(s["video"], live)}
                      for s in board],
            "later": [_slot_video(v, live) for v in later],
            "youtube": {"asked": live is not None, "error": _youtube_seen["error"]}}


@router.post("/api/videos/{video_id}/thumbnail")
async def edit_thumbnail(video_id: int, request: Request):
    """New words or another still for the thumbnail: made again at once (a second or two)."""
    video = _planned_or_409(video_id)
    if video["format"] != db.FORMAT or not video["plan"].get("script"):
        raise HTTPException(409, "Shorts from earlier versions have no thumbnail here.")
    body = await _json(request)
    text = " ".join(str(body.get("text") or "").split())
    if not 1 <= len(text.replace("*", " ").split()) <= 6 or len(text) > 60:
        raise HTTPException(422, "Use 1 to 6 words, 60 characters at most (mark the coloured one with *asterisks*).")
    background = body.get("background")
    if background and background not in animator.stills(video["plan"]):
        raise HTTPException(422, "Pick a still from this case's shots.")
    try:
        made = animator.make_thumbnail(video_id, video["plan"], text=text, background=background)
    except Exception as e:
        raise HTTPException(409, f"Couldn't make the thumbnail: {e}")
    db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "thumbnail": made})
    return _video_json(db.get_video(video_id))


@router.get("/media/thumb/{video_id}.jpg", include_in_schema=False)
def thumb_cover(video_id: int):
    path = animator.thumb_paths(video_id)[0]
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/media/thumb/{video_id}/wide.jpg", include_in_schema=False)
def thumb_wide(video_id: int):
    path = animator.thumb_paths(video_id)[1]
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/api/review")
def review_page():
    """Agent 5's page: what it checks, the cases it turned down (being made again by themselves), its recent reviews
    and the lessons it has taught."""
    history = list(db.latest_note("review:history") or [])[::-1]
    titles = {}
    for item in history:
        if item["video_id"] not in titles:
            row = db.get_video(item["video_id"])
            titles[item["video_id"]] = ((row or {}).get("plan", {}).get("metadata") or {}).get("title") if row else None
    planned = db.planned_videos()
    held = [{"id": v["id"], "title": (v["plan"].get("metadata") or {}).get("title") or v["theme"],
             "because": (v["plan"].get("review") or {}).get("held_because"), "remakes": int(v["plan"].get("remakes") or 0),
             "remake_at": _clock((v["plan"].get("review") or {}).get("remake_at"))}
            for v in planned if (v["plan"].get("review") or {}).get("held")]
    learned = db.latest_note("review:lessons") or {}
    return {"history": [{**h, "title": titles.get(h["video_id"])} for h in history], "held": held,
            "lessons": learned, "max_rounds": reviewer.MAX_ROUNDS,
            "checks": {"min_match": reviewer.MIN_MATCH, "his_pitch": voiceprint.PITCH, "line_pace": reviewer.LINE_PACE,
                       "pace": reviewer.PACE,
                       "loudness": reviewer.LOUDNESS, "frames": reviewer.FRAMES, "recurring": reviewer.RECURRING,
                       "lookback": reviewer.LOOKBACK}}


@router.get("/media/preview/{video_id}.mp4", include_in_schema=False)
def preview(video_id: int, request: Request):
    """The case's video, in pieces of at most PREVIEW_PIECE, each read and closed at once: served whole, the player
    kept the file open while the page showed it, and Windows then refused to delete or render it again (discarding
    #62 and #66 failed so, 2026-10-27). The player asks for the next piece itself."""
    path = animator.preview_path(video_id)
    asked = re.fullmatch(r"bytes=(\d+)-(\d*)", (request.headers.get("range") or "").strip())
    if not asked:
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4")
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            start = int(asked[1])
            end = min(int(asked[2]) if asked[2] else size - 1, start + PREVIEW_PIECE - 1, size - 1)
            if start >= size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            f.seek(start)
            body = f.read(end - start + 1)
    except FileNotFoundError:
        raise HTTPException(404)
    return Response(body, status_code=206, media_type="video/mp4", headers={
        "Content-Range": f"bytes {start}-{start + len(body) - 1}/{size}", "Accept-Ranges": "bytes"})


def _in_tmp(path: Path | str) -> Path:
    """A file named in a case's plan, if it's one of the channel's own in .tmp (never another file on this computer,
    whatever a plan says). 404 otherwise."""
    path = Path(path).resolve()
    if not path.is_relative_to(TMP_DIR.resolve()):
        raise HTTPException(404)
    return path


@router.get("/media/cover/{video_id}.jpg", include_in_schema=False)
def cover(video_id: int):
    path = animator.cover_path(video_id)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/media/scene/{video_id}/{number}.jpg", include_in_schema=False)
def scene_image(video_id: int, number: str):
    """One of a drawn case's drawings (by the number of the line it starts on)."""
    video = db.get_video(video_id)
    path = ((video or {}).get("plan", {}).get("drawings") or {}).get(number)
    if not path or not _in_tmp(path).exists():
        raise HTTPException(404)
    return FileResponse(_in_tmp(path), media_type="image/jpeg")


@router.get("/media/research/{video_id}/{image_id}.jpg", include_in_schema=False)
def research_image(video_id: int, image_id: str):
    video = db.get_video(video_id)
    image = next((i for i in ((video or {}).get("plan", {}).get("research") or {}).get("images") or []
                  if i["id"] == image_id), None)
    if not image or not image.get("file"):
        raise HTTPException(404)
    _in_tmp(TMP_DIR / image["file"])
    path = researcher.image_path(image)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/media/clip/{video_id}/{clip_id}.jpg", include_in_schema=False)
def clip_thumb(video_id: int, clip_id: str):
    """A frame of one of the case's clips (made once, kept next to the clip)."""
    video = db.get_video(video_id)
    pack = (video or {}).get("plan", {}).get("research") or {}
    clip = next((c for key in ("footage", "archive") for c in pack.get(key) or [] if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404)
    path = _in_tmp(TMP_DIR / clip["file"])
    thumb = path.with_suffix(".jpg")
    if not thumb.exists() and path.exists():
        subprocess.run([short_render.ffmpeg_exe(), "-y", "-v", "error", "-ss", "1", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=360:-2", str(thumb)], capture_output=True, timeout=60)
    if not thumb.exists():
        raise HTTPException(404)
    return FileResponse(thumb, media_type="image/jpeg")


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
    text = " ".join(str((await _json(request)).get("text", "")).split())
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


# --- the host: the Professor and his voice ------------------------------------

def _voice_state() -> dict:
    """His voice now: when it's asked again if it rests (and whether that's because today's free readings are used
    up), and the free readings left today of the day's total, renewed at `renews`."""
    left = narration.left_today()
    return {"resting": animator.rest_until(), "used_up": bool((animator.voice_resting() or {}).get("used_up")),
            "left": sum(left.values()), "daily": narration.DAILY * len(left), "renews": _clock(narration.renews_at())}


def _voice_settings(cfg: dict) -> dict:
    voice = cfg.get("voice") or {}
    return {"name": voice.get("name") or narration.VOICE, "model": voice.get("model") or narration.TTS_MODELS[0],
            "style": voice.get("style") or narration.STYLE, "deeper": int(voice.get("deeper") or 0)}


@router.get("/api/host")
def get_host():
    cfg = load_config()
    setup, voice = cfg.get("host") or {}, _voice_settings(cfg)
    measured = narration.measured()
    voices = []
    for name, label in narration.VOICES.items():
        sample = narration.sample_path(name, voice["deeper"], voice["style"])
        voices.append({"name": name, "label": label, "pitch": (measured.get(name) or {}).get("pitch_hz"),
                       "sample": f"/media/host/sample/{name}.wav{_stamp(sample)}" if sample.exists() else None})
    test = tmp_path("out", "host_test.mp4")
    return {
        "name": setup.get("name", "The Professor"), "size": setup.get("size", "M"), "sizes": host.SIZES,
        "enabled": setup.get("enabled", True), "voice": voice, "voices": voices,
        "images": {name: f"/media/host/{name}.png" for name in HOST_FILES},
        "test_clip": f"/media/host/test.mp4{_stamp(test)}" if test.exists() else None,
        **_voice_state(),
    }


@router.patch("/api/host")
async def edit_host(request: Request):
    _local_only("Changing the host")
    body = await _json(request)

    def change(data):
        setup, voice = data.setdefault("host", {}), data.setdefault("voice", {})
        if "name" in body:
            setup["name"] = " ".join(str(body["name"]).split())[:40] or "The Professor"
        if body.get("size") in host.SIZES:
            setup["size"] = body["size"]
        if body.get("voice") in narration.VOICES:
            voice["name"] = body["voice"]
        if "deeper" in body:
            voice["deeper"] = max(0, min(2, int(body["deeper"])))
        if "style" in body:
            voice["style"] = " ".join(str(body["style"]).split())[:400] or narration.STYLE
    update_config(change)
    return get_host()


@router.get("/media/host/{name}.png", include_in_schema=False)
def host_image(name: str):
    """His cut-out drawing, the sheet it came from, or his face (a small square, for the case cards)."""
    if name == "face":
        path = tmp_path("out", "host_face.png")
        if not path.exists():
            from PIL import Image

            Image.open(host.HOST_DIR / "base.png").crop((150, 110, 480, 440)).resize((160, 160), Image.LANCZOS).save(path)
        return FileResponse(path, media_type="image/png")
    if name not in HOST_FILES:
        raise HTTPException(404)
    return FileResponse(host.HOST_DIR / HOST_FILES[name], media_type="image/png")


@router.get("/media/host/sample/{voice}.wav", include_in_schema=False)
def host_sample(voice: str):
    if voice not in narration.VOICES:  # (first: a path from any other name would make its folders)
        raise HTTPException(404)
    settings = _voice_settings(load_config())
    path = narration.sample_path(voice, settings["deeper"], settings["style"])
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/wav")


@router.get("/media/host/test.mp4", include_in_schema=False)
def host_test_clip():
    path = tmp_path("out", "host_test.mp4")
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


# --- tasks ----------------------------------------------------------------

@router.post("/api/tasks/{kind}")
async def start_task(kind: str, request: Request):
    # On Vercel a thread can be frozen once the response is sent, and /tmp previews don't persist,
    # so this work only runs from the dashboard on your computer.
    _local_only("Making, animating and uploading from the dashboard")
    body = await _json(request)
    video_id = body.get("video_id")
    if kind == "prepare":
        return _start_task(kind, "Agents 1-3: making a new case",
                           lambda p: jobs.run_job("prepare", count=1, progress=p))
    if kind == "render":
        video = _planned_or_409(video_id)
        if video["format"] != db.FORMAT:
            raise HTTPException(409, "Shorts from earlier versions can't be animated again.")
        return _start_task(kind, f"Agents 4-5: making and reviewing case #{video_id}",
                           lambda p: jobs.run_job("publish", dry_run=True, video_id=video_id, now=True, progress=p),
                           video_id)
    if kind == "publish":
        video = _planned_or_409(video_id)
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the YouTube page).")
        if video["format"] == db.FORMAT and not db.ready(video):
            raise HTTPException(409, "This case waits for your OK (or the Reviewer held it): see the Studio.")
        return _start_task(kind, f"Agent 6: uploading case #{video_id}",
                           lambda p: jobs.run_job("publish", video_id=video_id, progress=p), video_id)
    if kind == "autopilot":
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the YouTube page).")
        return _start_task(kind, "Making the next Short now", _make_next_now)
    if kind == "stats":
        return _start_task(kind, "Agent 7: reading the numbers", lambda p: jobs.run_job("stats", learn=True, progress=p))
    if kind == "instagram":
        if not instagram.is_configured():
            raise HTTPException(409, "Connect Instagram first (the Channels page).")
        return _start_task(kind, "Agent 6: posting to Instagram", lambda p: jobs.run_job("instagram", progress=p))
    if kind == "host-sample":
        voice = body.get("voice")
        if voice not in narration.VOICES:
            raise HTTPException(422, "Unknown voice.")
        settings = _voice_settings(load_config())
        return _start_task(kind, f"Recording a sample of {voice}'s voice",
                           lambda p: narration.sample(voice, settings["deeper"], settings["style"], progress=p))
    if kind == "host-test":
        return _start_task(kind, "Making a test clip of the Professor",
                           lambda p: host.test_clip(tmp_path("out", "host_test.mp4"), progress=p))
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
            "taught": {a["key"]: lessons_for(a["key"]) for a in AGENTS if a["key"] != "analyst"},
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
            "channel": None, "error": None, "manage": _can_manage()}
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


# --- Instagram connection ---------------------------------------------------

@router.get("/api/instagram")
def instagram_status():
    cfg = load_config()
    return {**instagram.status(), "on": bool((cfg.get("instagram") or {}).get("enabled")), "send": instagram.send_way(),
            "app": bool(env("FACEBOOK_APP_ID") and env("FACEBOOK_APP_SECRET")), "local": not ON_VERCEL}


@router.post("/api/instagram/connect")
async def instagram_connect(request: Request):
    _local_only("Connecting Instagram")
    body = await _json(request)
    try:
        found = instagram.connect(str(body.get("token") or ""), body.get("app_id"), body.get("app_secret"))
    except Exception as e:
        raise HTTPException(422, f"Couldn't connect: {e}")
    try:  # the cloud's runs read their own copy of the token (GitHub's secrets): the new one goes there too
        cloud = cloud_secrets.copy(cloud_secrets.INSTAGRAM)
    except Exception as e:
        cloud = {"error": str(e)[:300]}
    publisher.reconnected()
    return {**instagram_status(), "page": found.get("page"), "long_lived": found.get("long_lived"), "cloud": cloud}


@router.patch("/api/instagram")
async def instagram_switch(request: Request):
    _local_only("Instagram")
    body = await _json(request)
    if "send" in body:  # how the video gets to Instagram (tools/instagram.py)
        if body["send"] not in instagram.SEND_WAYS:
            raise HTTPException(422, "Unknown way.")

        def change(data):
            data.setdefault("instagram", {})["send"] = body["send"]
        update_config(change)
        return instagram_status()
    on = bool(body.get("on"))
    if on and not instagram.is_configured():
        raise HTTPException(409, "Connect Instagram first.")

    def change(data):
        data.setdefault("instagram", {})["enabled"] = on
    update_config(change)
    return instagram_status()


@router.delete("/api/instagram")
def instagram_disconnect():
    _local_only("Instagram")
    instagram.disconnect()

    def change(data):
        data.setdefault("instagram", {})["enabled"] = False
    update_config(change)
    return instagram_status()


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
    if int(request.headers.get("content-length") or 0) > MAX_MUSIC_BYTES:  # (before it's all read into memory)
        raise HTTPException(422, f"Music files must be under {MAX_MUSIC_BYTES >> 20} MB.")
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
    cfg = load_config()
    return {**cfg, "look": {**draw.settings(), "style": draw.style(), "when_out": "footage" if draw.fallback() else "wait"},
            "drawing": _drawing_state(),
            "categories_available": editor.CATEGORIES, "editable": not ON_VERCEL}


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
    look = section("look")
    style = str(look.get("style") or "footage").strip().lower()
    if style not in ("drawn", "footage"):
        raise ValueError("The look: drawn or footage.")
    art = " ".join(str(look.get("art") or "").split())
    if style == "drawn" and not 40 <= len(art) <= 600:
        raise ValueError("The art: describe his style in 40 to 600 characters (every drawing starts with it).")
    when_out = str(look.get("when_out") or "footage").strip().lower()
    if when_out not in ("footage", "wait"):
        raise ValueError("When Cloudflare can't draw: footage or wait.")
    region = str(section("trends").get("region", "US")).strip().upper()
    if region != "ALL" and not re.fullmatch(r"[A-Z]{2}", region):
        raise ValueError("Trends: ALL (every country) or a two-letter country code like US or GB.")
    return {"name": name, "show_name": bool(channel.get("show_name")), "contact": contact,
            "audience": str(channel.get("audience", "")).strip(), "voice": " ".join(str(channel.get("voice", "")).split()),
            "schedule": schedule, "weights": weights,
            "approval": {"trending": bool(approval.get("trending")), "politics": bool(approval.get("politics"))},
            "expires": _number(cases.get("approval_expires_days"), "Approval wait", 1, 14),
            "target": target, "longest": longest,
            "follow_ups": bool(cases.get("follow_ups")), "comment_requests": bool(cases.get("comment_requests")),
            "share_alike": bool(section("research").get("share_alike_images")),
            "style": style, "art": art or None, "when_out": when_out,
            "region": region, "hashtags": hashtags[:4],
            "volume": round(_number(section("music").get("volume"), "Music volume", 0, 1.5, whole=False), 2)}


@router.put("/api/settings")
async def save_settings(request: Request):
    _local_only("Settings")
    try:
        v = _validated(await _json(request))
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
        for key in ("timezone", "first_post", "make_at"):
            data["schedule"][key] = Q(v["schedule"][key])
        for key in ("every_hours", "posts_per_day"):
            data["schedule"][key] = v["schedule"][key]
        for key, weight in v["weights"].items():
            cases["categories"][key] = int(weight) if weight == int(weight) else weight
        cases["approval"]["trending"], cases["approval"]["politics"] = v["approval"]["trending"], v["approval"]["politics"]
        cases["approval_expires_days"] = v["expires"]
        cases.pop("queue", None)  # (retired: the morning run makes each day's cases)
        cases["target_seconds"], cases["max_seconds"] = v["target"], v["longest"]
        cases["follow_ups"], cases["comment_requests"] = v["follow_ups"], v["comment_requests"]
        data["research"]["share_alike_images"] = v["share_alike"]
        if "look" not in data:
            data["look"] = {}
        data["look"]["style"] = Q(v["style"])
        data["look"]["when_out"] = Q(v["when_out"])
        if v["art"]:
            data["look"]["art"] = FoldedScalarString(v["art"])
        data["trends"]["region"] = Q(v["region"])
        data["metadata"]["base_hashtags"] = flow(v["hashtags"])
        data["music"]["volume"] = v["volume"]
    update_config(change)
    return get_settings()
