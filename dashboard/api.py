"""
The dashboard: serves the page (index.html, app.css, app.js in this folder) and the JSON API it calls: the six agents'
pages for the daily motivation story (Themes, Stories, the Studio, Review, Schedule, Results), the Music page and The
look, the channels, the settings and the activity.

Locally it's at http://localhost:8000 and answers only on this computer (asked by its own name, from its own
address: started on every address by mistake, it still refuses the rest of the network). On Vercel it's
switched off unless DASHBOARD_USERNAME and DASHBOARD_PASSWORD are set, the password 12 characters or more.
With both set (on Vercel, or in .env here too) it opens only after the sign-in page (/login): a browser stays
signed in for 30 days through a signed cookie, a new username or password signs every browser out, and ten
wrong tries from one address and that address is refused for ten minutes.
Writing stories, making films and uploading run in a background thread; the page polls progress.
While the database is on this computer, a loop here also runs the channel every minute: the day's story when its run
starts, then keeping waiting stories' films made and reviewed, and the day's numbers (jobs.next_chore).

The code it runs is the code it started with: when the software on this computer changes while it runs (code_changed),
it starts no more work (its old code would mix with the new: on 2026-11-16 a dashboard started before an update crashed
making a story, then uploaded a story of the dropped look), and, started with `python app.py`, it restarts itself with
the new code as soon as nothing is running (RESTART).
"""

import functools
import hashlib
import hmac
import ipaddress
import json
import os
import re
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
import film_sound
import instagram
import jobs
import media
import narration
import narrator
import notify
import series
import slots
import story_film
import voiceprint
import youtube_auth
import youtube_upload
from agents import AGENTS, analyst, animator, publisher, reviewer
from agents import story as story_agent
from agents.base import lessons_for, playbook
from common import ON_VERCEL, ROOT, TMP_DIR, background_priority, env, load_config, redact, update_config

UI_DIR = Path(__file__).resolve().parent
UI_FILES = {
    "app.css": (UI_DIR / "app.css", "text/css"),
    "app.js": (UI_DIR / "app.js", "text/javascript"),
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
CLIENT_FILE = ROOT / "credentials.json"
MAX_MUSIC_BYTES = 30 * 1024 * 1024
MAX_CLIENT_FILE = 64 * 1024     # bytes: a Google OAuth client file is well under 1 KB
PREVIEW_PIECE = 2 * 1024 * 1024  # bytes of a story's film served a request
MIN_PASSWORD = 12                # characters, at least, in the dashboard's password
MIN_STRENGTH = 4                 # zxcvbn's score (0-4) the password needs: 4 = 10^10 guesses or more
SESSION_COOKIE, SESSION_DAYS = "dashboard_session", 30  # a browser stays signed in this long (or until it signs out)
WRONG_TRIES, WRONG_FOR = 10, 600  # wrong sign-ins from one address within WRONG_FOR seconds before it's refused
WRONG_ALL = 30                    # ...and from all addresses together, before sign-in rests here for everyone
MAX_FORM = 8192                   # bytes, at most, in a sign-in form
_wrong: dict[str, list[float]] = {}  # (per server instance: Vercel may run a few, so it's a brake, not a wall;
_wrong_lock = threading.Lock()       # Vercel's firewall rate limit is the wall: workflows/setup_accounts.md step 7)
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9 ._()-]+")
LEGACY = {"case": "Cartoon-host version", "sketch": "Cartoon version",  # rows earlier versions of the channel made
          "doc": "Documentary Shorts"}                                   # (anything else: the cute-animal version)
RESTART = 3          # the exit code that has app.py's launcher start the dashboard again (with the new code)
CODE_CHECK = 15      # seconds between looks at whether the software on this computer changed
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
             env("VERCEL_GIT_REPO_OWNER"), "narrator", "dashboard", "control room"]
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
        if request.method == "GET" and request.url.path in ("/", "/style-test"):
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


async def _body_upto(request: Request, most: int, too_big: str) -> bytes:
    """The request's body, read piece by piece and refused (422) as soon as it passes `most` bytes: never the whole of
    an oversized one in memory (a body sent in chunks has no length to check first)."""
    body = b""
    async for piece in request.stream():
        body += piece
        if len(body) > most:
            raise HTTPException(422, too_big)
    return body


JSON_MOST = 256 * 1024   # bytes: the largest JSON body a page sends is a few kilobytes


async def _json(request: Request) -> dict:
    """The request's JSON object (422 if it isn't one, instead of an error), read only up to JSON_MOST."""
    raw = await _body_upto(request, JSON_MOST, "The request is too big.")
    try:
        body = json.loads(raw or b"{}")
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


SIDE_TASKS = ("connect", "reel", "remake", "stats")  # Google's page waiting for you, Reels going out, a short version
# made again for its Reel, and the Analyst reading the numbers (a minute at most: it never waits for a morning run to end)


def _code_stamp() -> str:
    """The software this server runs: every module of the agents, the tools and the dashboard, and app.py, by name,
    size and time."""
    parts = []
    for path in [ROOT / "app.py", *sorted((ROOT / "agents").glob("*.py")), *sorted((ROOT / "tools").glob("*.py")),
                 *sorted(UI_DIR.glob("*.py"))]:
        stat = path.stat()
        parts.append(f"{path.relative_to(ROOT).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


CODE_AT_START = _code_stamp()


def code_changed() -> bool:
    """Has the software on this computer changed since this server started? (On Vercel each version is a fresh start.)"""
    if ON_VERCEL:
        return False
    try:
        return _code_stamp() != CODE_AT_START
    except OSError:  # (a file being replaced right now)
        return True


STALE_CODE = ("The software on this computer was updated after this dashboard started, so it would run old code. "
              + ("It restarts by itself in a few seconds: reload the page, then press it again."
                 if os.environ.get("DASHBOARD_RESTARTS") else
                 "Restart the dashboard (start it with `python app.py` and it restarts by itself), then press it again."))


def _start_task(kind: str, label: str, work, video_id: int | None = None) -> dict:
    """One task at a time; `work(progress)` runs in a thread and reports steps through progress(). Connecting YouTube
    only waits for you on Google's page, and Post now on Instagram only sends a finished video, so each runs beside the
    rest (a morning run takes a while), one of each at a time. Nothing starts on old code (code_changed)."""
    if code_changed():
        raise HTTPException(409, STALE_CODE)
    if kind in CLOUD_WAITS and _cloud_going():
        raise HTTPException(409, "The autopilot's run is making a story on GitHub right now, with the same free quotas "
                                 "and YouTube uploads: try again when it's done (the bar at the top follows it).")
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


def _running() -> bool:
    return any(t["status"] == "running" for t in _tasks.values())


def _make_next_now(progress) -> dict:
    """"Make the 17:30 video now": the next open slot gets the oldest story ready to go up, or a new one written now;
    it's made, reviewed and uploaded for that slot (jobs.autopilot)."""
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
        return "Today's run: making the day's story"
    if name == "autopilot":
        slot = jobs.due_slot()
        return f"Autopilot: making the {jobs.clock(slot, slots.plan())} story" if slot else "Autopilot"
    if name == "prepare":
        return "Agents 1-2: writing the next story"
    if name == "publish":
        turned_down = (((db.get_video(kwargs["video_id"]) or {}).get("plan") or {}).get("review") or {}).get("held")
        return (f"Agents 4-5: making story #{kwargs['video_id']} again (the Reviewer turned it down)" if turned_down
                else f"Agents 4-5: making and reviewing story #{kwargs['video_id']}")
    return "Agent 7: reading the numbers"


def _post_due_reels() -> None:
    """Reels whose time has come go out beside whatever else is going (a morning run takes a while), as a task of their
    own."""
    if publisher.reels_due():
        try:
            _start_task("reel", "Agent 6: posting to Instagram", lambda p: jobs.run_job("instagram", progress=p))
        except HTTPException:
            pass  # a Reel is going out already; the next minute looks again


def _read_due_numbers() -> None:
    """The Analyst reads the day's numbers beside whatever else is going (left for when nothing else was, it read
    nothing from 2026-10-26 to 28: there was always something to make)."""
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
            if not autopilot_here() or jobs.paused() or code_changed():  # (on old code nothing starts: it restarts first)
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


def _restart_when_changed() -> None:
    """Started by app.py's launcher: once the software on this computer has changed and nothing is running, the
    dashboard leaves with RESTART and the launcher starts it again with the new code."""
    while True:
        time.sleep(CODE_CHECK)
        if code_changed() and not _running():
            print("The software on this computer changed: restarting the dashboard with it", file=sys.stderr, flush=True)
            os._exit(RESTART)


def start_autopilot_loop() -> None:
    global _loop_started
    if not _loop_started:
        _loop_started = True
        background_priority()  # the morning run's renders give way to whatever you're doing on this computer
        if autopilot_here():  # the runs left open by the last time this program stopped, and the stories they were
            db.abandon_runs()  # making: picked up again at once, not later (nothing else makes them here)
            db.release_stale(db.now_iso(timedelta(seconds=1)))
        threading.Thread(target=_autopilot_loop, name="autopilot", daemon=True).start()
        if os.environ.get("DASHBOARD_RESTARTS"):
            threading.Thread(target=_restart_when_changed, name="restart", daemon=True).start()


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
    plan = v["plan"]
    meta = plan.get("metadata", {})
    short = plan.get("short_upload") or {}
    # (a story stopped or deleted on YouTube: when, and the time it had then: publisher.take_off)
    off = plan.get(v["status"]) if v["status"] in ("stopped", "deleted") else None
    return {"id": v["id"], "status": v["status"], "form": series.form_of(v),
            "title": meta.get("title") or _draft_title(v) or v["theme"],
            "theme": (plan.get("brief") or {}).get("theme") or v["theme"], "youtube_id": v["youtube_id"],
            "publish_at": v["publish_at"], "slot": v["slot"], "platforms": publisher.platforms(v, live),
            "when": v["publish_at"] or (off or {}).get("publish_at") or (off or {}).get("slot") or v["slot"],
            "taken_off_at": (off or {}).get("at"),
            "short": {"status": short.get("status"), "at": short.get("publish_at"), "youtube_id": short.get("youtube_id"),
                      "error": short.get("error"), "taken_off": bool(short.get("stopped") or short.get("deleted"))}
            if short else None}


def _draft_title(v: dict) -> str | None:
    """The title of a story being made whose script is written but not yet storyboarded (jobs._draft_saved)."""
    return (v["plan"].get("draft") or {}).get("title")


def _autopilot_state(cfg: dict) -> dict:
    sched = slots.plan(cfg)
    now = datetime.now(timezone.utc)
    shown = slots.shown_day(now, sched)
    day = slots.day_slots(shown, sched)
    board = jobs.slot_board(day[0], day[-1], sched, now)
    last = db.last_run("morning", ok=None)  # (the latest run however it went: one still going, or one stopped early)
    going = _going(last, now)
    upcoming = jobs.slot_board(now, now + timedelta(days=2), sched, now)
    try:
        found = jobs.next_open_slot(jobs.MANUAL_LEAD, now, sched)
        next_open, next_open_form = slots.iso(found), slots.form(found, sched)
    except RuntimeError:
        next_open = next_open_form = None
    here = autopilot_here()
    return {
        "here": here,
        "schedule": {k: sched[k] for k in ("timezone", "post_at", "make_at", "ahead", "stories_ahead", "start",
                                           "short_days", "shorts_at", "long_at")},
        "check": db.latest_note("autopilot:check"),  # (the last check's verdict: is a story being made, or what it waits for)
        "run": {"starts": slots.iso(slots.opens(day[0], sched)), "slots": len(board),  # (when its story could start)
                "scheduled": sum(1 for s in board if s["state"] in ("scheduled", "posted")),
                "running": going, "last": _run_json(last)},
        # (the run going in the cloud, as the progress bar's task; on a PC that runs the autopilot itself, it's its own)
        "cloud": _cloud_task(last) if going and not here else None,
        "slots": [{"at": slots.iso(s["slot"]), "state": s["state"], "form": s["form"], "video": _slot_video(s["video"])}
                  for s in board],
        "next": upcoming and {"at": slots.iso(upcoming[0]["slot"]), "state": upcoming[0]["state"]},
        "next_open": next_open, "next_open_form": next_open_form,  # ("Make the Short for Sat 21:00 now")
        "next_to_make": _turn_brief(jobs.next_to_make(now, sched)),  # (what "Write the next Short" writes for)
        "last_check": db.last_beat("autopilot"),
    }


def _going(run: dict | None, now: datetime | None = None) -> bool:
    """Is this run still going? One cut off without finishing (by GitHub's 6-hour limit, or a closed laptop) isn't."""
    now = now or datetime.now(timezone.utc)
    return bool(run and not run["finished_at"]
                and now - slots.parse(run["started_at"]) < jobs.RUN_LIMIT + timedelta(minutes=20))


CLOUD_LABEL = "The autopilot's run on GitHub"
# What waits while the autopilot's run is going in the cloud: what makes a film (the same free quotas) or uploads.
CLOUD_WAITS = ("autopilot", "render", "publish", "short", "narrator-sample", "remake")


def _cloud_task(run: dict | None) -> dict | None:
    """The autopilot's run started outside this dashboard (GitHub's: tools/jobs.py morning) as a task for the progress
    bar at the top: the steps it keeps as it goes (note run:live, jobs.LiveSteps) and how it ended. A run from before
    it kept them shows without its steps."""
    if not run:
        return None
    note = db.latest_note(jobs.LIVE_NOTE) or {}
    try:  # (the note is this run's: it's started just before the run's row)
        if abs(slots.parse(note["started"]) - slots.parse(run["started_at"])) > timedelta(minutes=2):
            note = {}
    except (KeyError, TypeError, ValueError):
        note = {}
    detail = _run_json(run)["detail"]
    status = "running" if _going(run) else "done" if run["ok"] else "error"
    error = None
    if status == "error":
        error = detail.get("error") or ("it was cut off before it finished" if not run["finished_at"]
                                        else "it stopped without saying why")
    return {"id": f"cloud-{run['id']}", "kind": "cloud", "label": CLOUD_LABEL, "status": status,
            "steps": note.get("steps") or [], "result": detail if status == "done" else None, "error": error,
            "started": run["started_at"], "finished": run["finished_at"], "video_id": None, "cloud": True,
            "url": note.get("url")}


def _cloud_going() -> bool:
    """Is the autopilot's run going in the cloud (not this PC's own)?"""
    return not autopilot_here() and _going(db.last_run("morning", ok=None))


def _run_json(r: dict | None) -> dict | None:
    if not r:
        return None
    try:
        detail = json.loads(r["detail"]) if r["detail"] else {}
    except ValueError:
        detail = {"text": r["detail"]}
    return {"at": r["started_at"], "finished": r["finished_at"], "ok": r["ok"], "detail": detail}


# What the dashboard's status (read every 30 seconds) needs of each story waiting (db.LIGHT).
QUEUE_PARTS = ("review", "render.id", "short_render.id")


def _agents(planned: list[dict]) -> list[dict]:
    """Each agent's card: its last run and the size of its part of the pipeline."""
    videos = db.list_videos(300, parts=())
    now = datetime.now(timezone.utc)
    stories = [v for v in videos if v["format"] == db.fmt() and v["status"] != "skipped"]
    scheduled = [v for v in videos if v["status"] == "scheduled" and v["publish_at"] and slots.parse(v["publish_at"]) > now]
    films = [v for v in planned if animator.preview_path(v["id"]).exists()]
    passed = [v for v in planned if reviewer.passed(v["plan"])]
    book = playbook()
    metric = {"theme": (len(stories), "themes chosen"), "story": (len(planned), "stories waiting"),
              "visuals": (len(db.visuals()), "new silhouettes in the library"),
              "animator": (len(films), "films made for the queue"),
              "reviewer": (len(passed), "films passed, ready to post"),
              "publisher": (len(scheduled), "films scheduled ahead"),
              "analyst": (book.get("samples") or 0, "films in the playbook")}
    return [{**agent, "last": _run_json(db.last_run(agent["key"], ok=None)), "count": metric[agent["key"]][0],
             "what": metric[agent["key"]][1]} for agent in AGENTS]


def _story_hours() -> dict:
    """The hours stories are made in (jobs.story_window: after Gemini's free allowance renews, until midnight): open
    now, and when they open and close on the schedule's clock (the page asks before a story is made outside them)."""
    sched = slots.plan()
    opens, closes = jobs.story_window(sched=sched)
    now = datetime.now(timezone.utc)
    return {"open": opens <= now < closes, "opens": slots.clock(opens, sched), "closes": slots.clock(closes, sched)}


def _youtube_limit() -> dict | None:
    """While YouTube's daily upload limit holds: when it should take the channel's next upload (tools/jobs.py)."""
    room = jobs.upload_room_at()
    if not room or room <= datetime.now(timezone.utc):
        return None
    return {"room": slots.iso(room), "count": (db.fresh_note("youtube_limit", timedelta(hours=24)) or {}).get("count")}


@router.get("/api/state")
def state():
    cfg = load_config()
    planned = db.planned_videos(parts=QUEUE_PARTS)
    autopilot = _autopilot_state(cfg)
    return {
        "channel": cfg["channel"]["name"],
        "local": not ON_VERCEL,
        "login": _login() is not None,  # (the page then offers Sign out)
        "paused": jobs.paused(),
        "stale": {"restarts": bool(os.environ.get("DASHBOARD_RESTARTS"))} if code_changed() else None,
        "services": {
            "gemini": bool(env("GEMINI_API_KEY")),
            "youtube": youtube_auth.is_configured(),
            "youtube_manage": _can_manage(),
            "telegram": notify.is_configured(),
            "database": "cloud" if env("DATABASE_URL") or env("POSTGRES_URL") else "local",
            "music": len(media.music_tracks()),
            "instagram": {"connected": instagram.is_configured(), "on": publisher.reels_on(),
                          "username": env("INSTAGRAM_USERNAME"), "down": publisher.instagram_down()},
        },
        "autopilot": autopilot,
        "counts": db.status_counts(),
        "agents": _agents(planned),
        "held": sum(1 for v in planned if (v["plan"].get("review") or {}).get("held")),
        "ready": sum(1 for v in planned if db.ready(v)),
        "requests": len(db.list_topics("waiting")),
        "series": _series_state(),
        "gemini": _story_hours(),
        "youtube_limit": _youtube_limit(),
        # Google's page waiting for you comes first, then a Reel you're posting: the dashboard follows it, then the run
        "task": next((_public(t) for t in sorted(_tasks.values(), key=lambda t: (t["kind"] != "connect", t["kind"] != "reel"))
                      if t["status"] == "running"), None) or autopilot["cloud"],  # (else the autopilot's run on GitHub)
    }


def _series_state() -> dict:
    """The stories' settings, for every page (the Overview, the Studio, the Stories page)."""
    cfg = series.settings()
    return {"post_at": cfg["cycle"]["long_at"], "short_after_hours": series.short_after_hours(),
            "short_seconds": list(story_film.SHORT_SECONDS), "minutes": list(series.minutes()),
            "short_minutes": list(series.minutes("short")), "cycle": cfg["cycle"], "themes": series.themes()}


@router.post("/api/pause")
async def set_pause(request: Request):
    """The pause switch: kept in the database, so it stops the morning run in the cloud too (and in .env here)."""
    paused = bool((await _json(request)).get("paused"))
    db.set_paused(paused)
    if not ON_VERCEL:
        os.environ["PAUSED"] = "true" if paused else "false"
        for attempt in (1, 2):   # (.env mirrors the switch; Windows refuses the swap while another program reads it)
            try:
                set_key(str(ROOT / ".env"), "PAUSED", os.environ["PAUSED"])
                break
            except OSError as e:
                if attempt == 2:
                    print(f"The pause switch is saved, but .env couldn't be updated: {e}", flush=True)
                else:
                    time.sleep(0.3)
    return {"paused": jobs.paused()}


# --- stories ------------------------------------------------------------------

def _stamp(path: Path) -> str:
    return f"?v={int(path.stat().st_mtime)}"


def _video_json(v: dict) -> dict:
    plan = v["plan"]
    meta = plan.get("metadata") or {}
    preview, cover = animator.preview_path(v["id"]), animator.cover_path(v["id"])
    out = {
        "id": v["id"], "status": v["status"], "created_at": v["created_at"], "publish_at": v["publish_at"],
        "slot": v["slot"], "error": v["error"], "youtube_id": v["youtube_id"],
        "studio_url": f"https://studio.youtube.com/video/{v['youtube_id']}/edit" if v["youtube_id"] else None,
        "legacy": None if series.is_story(v) else LEGACY.get(v["format"], "Cute-animal version"),
        "title": meta.get("title") or _draft_title(v) or v["theme"], "description": meta.get("description"),
        "hashtags": meta.get("hashtags") or [], "duration": (plan.get("render") or {}).get("seconds"),
        "music": (plan.get("render") or {}).get("music"),
        "preview": f"/media/preview/{v['id']}.mp4{_stamp(preview)}" if preview.exists() else None,
        "cover": f"/media/cover/{v['id']}.jpg{_stamp(cover)}" if cover.exists() else None,
        "platforms": publisher.platforms(v) if v["status"] in ("making", "scheduled") else None,
    }
    if out["legacy"] or not plan.get("story"):
        return {**out, "draft": plan.get("draft")} if plan.get("draft") else out  # (a story being made: its script)
    return {**out, **_story_json(v)}


def _bubbles_of(shot: dict, when: list) -> list[dict]:
    """A shot's bubbles as the Studio shows them: who, the kind (say, think, shout, picture), the words, the picture,
    and the second each comes (`when`, once its film is made)."""
    return [{"who": b.get("who") or "him", "kind": b.get("kind") or "say", "text": b.get("text") or "",
             "picture": b.get("picture") or "", "at": when[i] if i < len(when) else None}
            for i, b in enumerate(shot.get("bubbles") or [])]


def _short_json(v: dict) -> dict | None:
    """A story's short version as the Studio shows it: its video (when it's made from the film as it is), its length,
    and its shots (each with the film's scene it shows, its bubbles, and the second it starts in the short version; a
    narrated one's line, from before 2026-11-19)."""
    plan = v["plan"]
    story = plan["story"]
    if not story.get("short"):
        return None
    made = plan.get("short_render") or {}
    path = animator.short_path(v["id"])
    ready = animator.short_made(v)
    spans = [(t.get("start") or 0.0, t.get("end") or 0.0) for t in made.get("shots") or []] if ready else []
    came = {}
    for b in made.get("bubbles") or [] if ready else []:   # (the short version's bubbles, by the shot they're in)
        j = next((j for j, (a, e) in enumerate(spans) if a <= b.get("start", -1) < e), None)
        if j is not None:
            came.setdefault(j, []).append(b["start"])
    said = {int(x.get("shot") or 0): x.get("line") or "" for x in story["short"].get("shots") or []}
    shots = [{"shot": x["film_shot"], "act": x.get("act"), "at": spans[j][0] if j < len(spans) else None,
              "bubbles": _bubbles_of(x, came.get(j, [])), "line": said.get(x["film_shot"], "")}
             for j, x in enumerate(story_film.short_story(story)["shots"])]
    words = sum(len(b["text"].split()) for x in shots for b in x["bubbles"])
    return {"video": f"/media/short/{v['id']}.mp4{_stamp(path)}" if ready else None,
            "seconds": made.get("seconds") if ready else None, "estimate": story["short"].get("estimate"),
            "scenes": len(shots), "words": words or story["short"].get("words"), "shots": shots,
            "voice": (made.get("voice") or {}).get("voice") if ready else None}


def _story_json(v: dict) -> dict:
    """A story as the Studio shows it: its film and its short version, every shot with what it shows and its bubbles
    (with the second each comes; a narrated film's line, from before 2026-11-19), its scenes, its chapters and the
    Reviewer's verdict."""
    plan = v["plan"]
    story, brief, meta = plan["story"], plan.get("brief") or {}, plan.get("metadata") or {}
    made = plan.get("render") or {}
    starts = [x.get("start") for x in made.get("shots") or []]
    came = {}
    for b in made.get("bubbles") or []:
        came.setdefault(int(b.get("shot") or 0) - 1, []).append(b.get("start"))
    times = iter(made.get("lines") or [])   # (a narrated film's lines)
    moments = []
    for k, shot in enumerate(story["shots"]):
        line_at = None
        if shot.get("line"):
            t = next(times, None)
            line_at = t["start"] if t else None
        moments.append({"shot": k + 1, "act": shot.get("act"), "plate": shot.get("plate"),
                        "shows": shot.get("shows") or "", "quiet": shot.get("line_index") is None,
                        "at": starts[k] if k < len(starts) else line_at, "line": shot.get("line") or "",
                        "bubbles": _bubbles_of(shot, came.get(k, []))})
    drawn = plan.get("plates") or {}
    plates = [{"id": pl["id"], "scene": pl["scene"], "him": pl.get("him"), "light": pl.get("light"),
               "redraws": int(pl.get("redraws") or 0),
               "thumb": f"/media/plate/{v['id']}/{pl['id']}.jpg" if pl["id"] in drawn else None}
              for pl in story["plates"]]
    chapters = made.get("chapters") or [{"act": a, "name": n, "at": None} for a, n in (story.get("chapters") or {}).items()]
    first_shot = {}
    for shot in story["shots"]:
        first_shot.setdefault(shot.get("place"), shot.get("plate"))
    places = [{"id": p["id"], "name": p.get("name"), "light": p.get("light"), "weather": p.get("weather"),
               "set": p.get("set"), "words": _place_words(p),
               "thumb": f"/media/plate/{v['id']}/{first_shot[p['id']]}.jpg" if first_shot.get(p["id"]) in drawn else None}
              for p in story.get("places") or []]
    cast = [{"id": c["id"], "role": c.get("role"), "words": _person_words(c)} for c in story.get("cast") or []]
    return {
        "story": True, "theme": brief.get("theme"), "kind": brief.get("kind"), "form": series.form_of(v),
        "why_now": brief.get("why_now"),
        "brief": brief.get("instruction"), "core_message": story.get("core_message"),
        "places": places, "cast": cast, "missing": story.get("missing") or [],
        "board_notes": story.get("board_notes") or [],
        "realization": (story["realization"] + 1) if story.get("realization") is not None else None,
        "stage_names": story.get("chapters") if isinstance(story.get("chapters"), dict) else {},
        "logline": story.get("logline") or story.get("core_message"), "closing_line": story.get("closing_line"),
        "chapters": chapters,
        "moments": moments, "plates": plates, "shot_count": len(story["shots"]), "words": story.get("words"),
        "bubble_count": sum(len(m["bubbles"]) for m in moments), "silent": animator.silent(story),
        "estimate": story.get("estimate"), "notes": story.get("notes") or [],
        "current": series.current(v),
        "short": _short_json(v), "short_upload": plan.get("short_upload"),
        "watch_url": f"https://www.youtube.com/watch?v={v['youtube_id']}" if v["youtube_id"] else None,
        "voice": plan.get("voice"), "preview_failed_at": plan.get("preview_failed_at"),
        "review": _review_json(plan), "thumbnail": _thumbnail_json(v["id"], plan),
        "instagram": plan.get("instagram"), "youtube_thumbnail": plan.get("youtube_thumbnail"),
        "remakes": int(plan.get("remakes") or 0), "full_description": publisher.description(meta, plan),
    }


def _place_words(place: dict) -> str:
    """A storyboard's place in a few words (the Studio): its kind and look, its things, its effects."""
    if place.get("set"):
        return f"the ready-made set “{place['set'].replace('_', ' ')}”"
    s = place.get("spec") or {}
    kind = s.get("nature") if s.get("kind") == "nature" else s.get("kind")
    bits = [kind or "room"]
    if s.get("kind") in ("room", "hall", "corridor"):
        bits.append(f"{s.get('wall')} walls")
    things = [t.replace("_", " ") for t in (s.get("things") or []) + (s.get("wall_things") or []) + (s.get("small") or [])]
    if things:
        bits.append(", ".join(things))
    if s.get("effects"):
        bits.append(", ".join(s["effects"]))
    return " · ".join(bits)


def _person_words(person: dict) -> str:
    """Someone of the storyboard's cast in a few words (the Studio): their hair, their clothes, their extras."""
    w = person.get("words") or {}
    bits = []
    if w.get("hair") and w["hair"] != "none":
        bits.append(f"{w.get('hair_color', '')} {w['hair']} hair".strip())
    if w.get("cloth"):
        bits.append(f"{w['cloth']} clothes")
    return ", ".join(bits + list(w.get("extras") or []))


def _clock(iso: str | None) -> str | None:
    """A time from the database on the schedule's clock (e.g. 21:40), or None."""
    try:
        return slots.clock(slots.parse(iso), slots.plan()) if iso else None
    except (TypeError, ValueError):
        return None


def _review_json(plan: dict) -> dict | None:
    """The Reviewer's verdict on the film as it is now (current: false when it's of an earlier version)."""
    verdict = plan.get("review")
    if not verdict:
        return None
    keep = ("passed", "round", "at", "issues", "changes", "held", "held_because", "override", "look", "match",
            "loudness", "peak", "seconds", "words_per_second")
    return {**{k: verdict.get(k) for k in keep}, "current": reviewer.current(plan) is not None,
            "history": [{k: h.get(k) for k in ("round", "passed", "issues", "changes")} for h in verdict.get("history") or []],
            "max_rounds": reviewer.MAX_ROUNDS, "remakes": int(plan.get("remakes") or 0),
            "remake_at": _clock(verdict.get("remake_at")) if verdict.get("held") else None}


def _thumbnail_json(video_id: int, plan: dict) -> dict:
    """The thumbnail as made, and the scenes it can be made from (for the Studio's thumbnail editor)."""
    _, wide = animator.thumb_paths(video_id)
    made = plan.get("thumbnail") or {}
    chosen = plan["story"].get("thumbnail") or {}
    return {"wide": f"/media/thumb/{video_id}/wide.jpg{_stamp(wide)}" if wide.exists() else None,
            "text": made.get("text") or chosen.get("words") or "",
            "lead": made["lead"] if "lead" in made else chosen.get("lead", ""),
            "punch": made["punch"] if "punch" in made else (chosen.get("punch") or made.get("text") or ""),
            "background": made.get("background"),
            "choices": [{"name": n, "label": f"scene {n.partition(':')[2].lstrip('s')}",
                         "thumb": f"/media/plate/{video_id}/{n.partition(':')[2]}.jpg"} for n in animator.stills(plan)]}


def _planned_or_409(video_id) -> dict:
    video = db.get_video(int(video_id)) if video_id is not None else None
    if not video:
        raise HTTPException(404, "No such story.")
    if video["status"] != "planned":
        raise HTTPException(409, f"Story #{video['id']} is {video['status']}; only waiting stories can be changed.")
    return video


@router.get("/api/videos")
def videos(limit: int = 60):
    return [_video_json(v) for v in db.list_videos(limit)]


@router.patch("/api/videos/{video_id}")
async def edit_video(video_id: int, request: Request):
    """Your changes to a waiting story's words (its title, a bubble's words, the closing line): its film is made
    again."""
    video = _planned_or_409(video_id)
    if not series.current(video):
        raise HTTPException(409, "This was made by an earlier version of the channel: it can't be edited here.")
    try:
        plan = story_agent.apply_edits(video["plan"], await _json(request))
    except (ValueError, IndexError, KeyError) as e:
        raise HTTPException(422, str(e))
    except (TypeError, AttributeError):  # (an edit not in the page's shape: a list or text where an object goes)
        raise HTTPException(422, "The changes aren't in the right shape: reload the page and try again.")
    animator.remove(animator.short_path(video_id))
    plan.pop("review", None)  # the words changed: a new film, reviewed afresh, without the old version's fixes
    plan.pop("fixes", None)
    plan.pop("render", None)  # the old film no longer matches the words
    plan.pop("short_render", None)  # (its short version keeps its own script; it's drawn again after the film)
    db.update_video(video_id, plan=plan)
    animator.remove(animator.preview_path(video_id))
    return _video_json(db.get_video(video_id))


@router.delete("/api/videos/{video_id}")
def discard_video(video_id: int):
    _planned_or_409(video_id)
    db.update_video(video_id, status="discarded")
    animator.remove(animator.preview_path(video_id))
    animator.remove(animator.short_path(video_id))
    animator.forget(video_id)
    return {"ok": True}


@router.post("/api/videos/{video_id}/review")
async def review_action(video_id: int, request: Request):
    """Your answer to the Reviewer: "post" a film it held (it goes out as it is), or "remake" it (made and reviewed
    again from scratch, the earlier fixes forgotten)."""
    video = _planned_or_409(video_id)
    action = (await _json(request)).get("action")
    plan = video["plan"]
    if action == "post":
        if not plan.get("review") or not animator.preview_path(video_id).exists():
            raise HTTPException(409, "There's no reviewed film to post yet.")
        plan["review"] = {**plan["review"], "held": False, "override": "you", "override_at": db.now_iso()}
    elif action == "remake":
        if (plan.get("review") or {}).get("held"):  # (made again by itself anyway: this only doesn't wait for its time)
            animator.make_again(video, progress=lambda m: None)
            return _video_json(db.get_video(video_id))
        plan.pop("review", None)
        plan.pop("fixes", None)
        plan.pop("render", None)
        plan.pop("short_render", None)
        animator.remove(animator.preview_path(video_id))
        animator.remove(animator.short_path(video_id))
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
    """Your YouTube buttons beside a story on the Schedule page. Until it's public: "now" makes the film public at once
    (its slot stays its own, so no other story is made for it; its short version still goes at its time); "stop" keeps
    the film and its short version on YouTube as private (only you can see them; you can still publish them from YouTube
    Studio).
    "delete" removes both from YouTube, public or not. Stop and Delete free its slot, so the morning run gives it a new
    story while the autopilot is on (a slot more than an hour gone stays empty), and its Reel goes too unless it's posted
    already (publisher.take_off)."""
    video = db.get_video(video_id)
    if not video or video["status"] != "scheduled" or not video["youtube_id"]:
        raise HTTPException(409, "Only a story on the schedule can be changed here.")
    action = (await _json(request)).get("action")
    if action not in ("now", "stop", "delete"):
        raise HTTPException(422, "Unknown action.")
    if action != "delete" and video["publish_at"] and slots.parse(video["publish_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(409, "It's public already: delete it here, or make it private in YouTube Studio.")
    try:
        if action == "now":
            done = youtube_upload.publish_now(video["youtube_id"])
        else:
            publisher.take_off(video_id, action)
    except youtube_upload.NotAllowed as e:  # the dashboard offers Google's page for it, then tries again
        raise HTTPException(403, {"message": str(e), "reconnect": True})
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"YouTube didn't do it: {e}")
    finally:
        _youtube_seen["at"] = 0.0  # what YouTube said a minute ago is out of date now
    if action == "now" and not done.get("gone"):
        db.update_video(video_id, publish_at=db.now_iso(),
                        plan={**video["plan"], "posted_now": {"at": db.now_iso(), "publish_at": video["publish_at"]}})
    return _video_json(db.get_video(video_id))


@router.post("/api/videos/{video_id}/instagram")
async def instagram_action(video_id: int, request: Request):
    """Your Instagram buttons beside a story on the Schedule page: "now" posts its Reel (its short version) at once (even
    before it's public on YouTube), as a task beside the rest, since the upload and Instagram's processing take a few
    minutes; "delete" deletes a posted Reel from Instagram, or takes one that isn't posted yet off (it isn't posted then);
    "schedule" makes the short version of a story that went up while Reels were off again, and its Reel then waits for
    its time."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "No such story.")
    action = (await _json(request)).get("action")
    reel = publisher.platforms(video)["instagram"]
    if action == "schedule":
        _local_only("Making a short version for Instagram")
        if not reel["can"]["schedule"]:
            raise HTTPException(409, f"{reel['why'] or 'Its Reel is waiting or posted already'}.")
        return _start_task("remake", f"Agent 4: making story #{video_id}'s short version again for Instagram",
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


SCHEDULE_DAYS = 7       # the Schedule page's "Will be posted" shows this many days of slots ahead
POSTED_MOST = 200       # ...and its "Posted" at most this many stories, newest first
LIVE_DAYS = 7           # YouTube is asked how the posts of the last week stand (older ones show what the dashboard knows)
SCHEDULE_PARTS = jobs.SLOT_PARTS + ("stopped", "deleted")
QUEUE_PARTS = jobs.SLOT_PARTS  # (with the review's and the film's marks: how far a waiting story is made)


def _queue() -> list[dict]:
    """The stories written and waiting for a turn, in the order the autopilot takes them (jobs.waiting)."""
    return jobs.waiting()


def _queued_json(v: dict) -> dict:
    """A waiting story on the Schedule page: as a slot shows it, and how far it's made."""
    review, made = v["plan"].get("review") or {}, (v["plan"].get("render") or {}).get("id")
    return {**_slot_video(v), "made": bool(made), "passed": bool(review.get("passed") or review.get("override")),
            "created_at": v["created_at"]}


LINE_NIGHTS = 8  # the Studio's line: from this round's first night, two rounds (four nights each, by the plan)


def _turn_story(v: dict) -> dict:
    """A story on the Studio's line, read in part: as a slot shows it, and how far it's made (the line's tracker:
    script, pictures, film, review, uploaded)."""
    plan = v["plan"]
    review, render = plan.get("review") or {}, plan.get("render") or {}
    return {**_slot_video(v), "created_at": v["created_at"], "written": bool(plan.get("draft") or plan.get("metadata")),
            "boarded": bool(plan.get("metadata")), "made": bool(render.get("id")),
            "passed": bool(review.get("passed") or review.get("override")), "held": bool(review.get("held")),
            "earlier": bool(render.get("id") and render.get("look") != series.LOOK)}


def _turn_brief(t: dict | None) -> dict | None:
    """A turn in a word: its time, its form, where it stands and when its making opens."""
    return t and {"at": slots.iso(t["slot"]), "form": t["form"], "state": t["state"], "opens": slots.iso(t["opens"])}


@router.get("/api/line")
def line_page():
    """The Studio's line (jobs.line): the turns from this round's first night through the next round, in posting order,
    each with its night and its story (uploaded or being made for it, or the written one waiting for it) and how far
    that is made; the next turn no story is for yet (what "Write the next Short" writes for); the stories written that
    no turn in view takes yet; how many of the next turns are ready; and this round's count."""
    sched = slots.plan(load_config())
    now = datetime.now(timezone.utc)
    ahead_slots = slots.between(now - jobs.LATE_GRACE, now + timedelta(days=3), sched)
    # (the night of the next video still to go out: at 04:43 on the 24th, the 24th, not the night gone by)
    tonight = slots.posting_day(ahead_slots[0], sched) if ahead_slots else slots.shown_day(now, sched)
    k = slots.cycle_day(tonight, sched)
    first = tonight - timedelta(days=k - 1) if k else tonight
    last = first + timedelta(days=LINE_NIGHTS - 1)
    planned = db.planned_videos(parts=jobs.SLOT_PARTS)
    pending = jobs.waiting(planned)
    turns = jobs.line(now, sched, start=slots.day_slots(first, sched)[0] - timedelta(seconds=1),
                      end=slots.day_slots(last, sched)[-1] + timedelta(seconds=1), pending=pending)
    used = {t["queued"]["id"] for t in turns if t["queued"]}
    ahead = int(sched.get("stories_ahead") or 1) if sched.get("ahead") else 1
    coming = [t for t in turns if t["state"] not in ("posted", "missed")][:ahead]
    nights = int(sched["short_days"]) + 1
    this_round = [t for t in turns if k and t["night"] < first + timedelta(days=nights)]
    make = jobs.next_to_make(turns=turns) or jobs.next_to_make(now, sched)
    shown = [{**_turn_brief(t), "night": t["night"].isoformat(), "night_no": t["night_no"],
              "story": _turn_story(t["video"] or t["queued"]) if (t["video"] or t["queued"]) else None,
              "queued": bool(t["queued"])} for t in turns]
    # (an upload holding none of the plan's turns, e.g. one scheduled at the old time before the plan began: shown on
    # its night as it is, marked "extra", so nothing uploaded goes missing from the Studio)
    held = {t["video"]["id"] for t in turns if t["video"]}
    night_starts = datetime.combine(first, slots.DAY_STARTS, tzinfo=sched["tz"])
    for v in db.slot_holders(slots.iso(night_starts), slots.iso(slots.day_slots(last, sched)[-1]), parts=jobs.SLOT_PARTS):
        at = slots.parse(v["publish_at"] or v["slot"])
        if v["id"] in held or not at:
            continue
        night = slots.posting_day(at, sched)
        shown.append({"at": slots.iso(at), "form": series.form_of(v), "opens": None, "night": night.isoformat(),
                      "night_no": slots.cycle_day(night, sched), "queued": False, "extra": True, "story": _turn_story(v),
                      "state": "posted" if v["status"] == "scheduled" and at <= now else v["status"]})
    shown.sort(key=lambda t: t["at"])
    return {
        "turns": shown,
        "tonight": tonight.isoformat(),
        "next_to_make": _turn_brief(make),
        "later": [_turn_story(v) for v in planned if v["id"] not in used],
        "ahead": {"n": ahead, "ready": sum(1 for t in coming if t["video"] or t["queued"])},
        "round": {"night": k, "nights": nights, **{form: {
            "posted": sum(1 for t in this_round if t["form"] == form and t["state"] == "posted"),
            "all": sum(1 for t in this_round if t["form"] == form)} for form in series.FORMS}} if k else None,
        "start": sched["cycle_start"].isoformat() if sched.get("cycle_start") else None,
        "minutes": {form: list(series.minutes(form)) for form in series.FORMS},
    }


@router.get("/api/videos/{video_id}")
def video_page(video_id: int):
    """One story whole (the Studio's line can show one older than the latest 60)."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "There's no such story.")
    return _video_json(video)


@router.get("/api/schedule")
def schedule_page():
    """The Schedule page, every story with its date: "Posted" (went out: public, or stopped or deleted on YouTube),
    "Scheduled" (uploaded, private until its time) and "Will be posted" (the next SCHEDULE_DAYS days' slots not uploaded
    yet, each with the story being made for it or the one in the queue that takes it). YouTube is asked how the
    uploads stand at most every 2 minutes, to notice changes made in YouTube Studio."""
    sched = slots.plan(load_config())
    now = datetime.now(timezone.utc)
    scheduled = db.scheduled_videos(days=0, parts=SCHEDULE_PARTS)
    scheduled = [v for v in scheduled if v["publish_at"] and slots.parse(v["publish_at"]) > now]
    posted = db.posted_history(POSTED_MOST, parts=SCHEDULE_PARTS)
    pending = _queue()
    turns = jobs.line(now, sched, end=now + timedelta(days=SCHEDULE_DAYS), pending=pending)  # (the Studio's line too)
    used = {t["queued"]["id"] for t in turns if t["queued"]}
    coming = [{"at": slots.iso(t["slot"]), "state": t["state"], "form": t["form"], "opens": slots.iso(t["opens"]),
               "video": _slot_video(t["video"]) if t["video"] else None,
               "queued": _queued_json(t["queued"]) if t["queued"] else None}
              for t in turns if t["state"] not in ("posted", "scheduled", "missed")]  # (in "Posted" and "Scheduled")
    queue = (v for v in pending if v["id"] not in used)
    recent = slots.iso(now - timedelta(days=LIVE_DAYS))
    live = _youtube_now([v["youtube_id"] for v in scheduled]
                        + [v["youtube_id"] for v in posted if v["status"] == "scheduled" and v["publish_at"] >= recent])
    posted = sorted((_slot_video(v, live) for v in posted), key=lambda v: v["when"] or "", reverse=True)
    return {"coming": coming, "queue_later": [_queued_json(v) for v in queue],
            "scheduled": [_slot_video(v, live) for v in scheduled], "posted": posted,
            "days": SCHEDULE_DAYS, "posted_most": POSTED_MOST, "paused": jobs.paused(),
            "youtube": {"asked": live is not None, "error": _youtube_seen["error"]}}


@router.post("/api/videos/{video_id}/thumbnail")
async def edit_thumbnail(video_id: int, request: Request):
    """New words or another scene for the thumbnail: made again at once (a few seconds)."""
    video = _planned_or_409(video_id)
    if not series.current(video):
        raise HTTPException(409, "This was made by an earlier version of the channel: it has no thumbnail here.")
    body = await _json(request)
    if "punch" not in body:   # (one line of words: a page from before the two)
        body = {**body, "lead": "", "punch": body.get("text")}
    lead = " ".join(str(body.get("lead") or "").replace("*", "").split())[:40]
    punch = " ".join(str(body.get("punch") or "").replace("*", "").split())[:40]
    if not 1 <= len(punch.split()) <= 4 or len(lead.split()) > 4:
        raise HTTPException(422, "The yellow words: 1 to 4; the white words above them: up to 4 (40 characters each).")
    background = body.get("background")
    if background and background not in animator.stills(video["plan"]):
        raise HTTPException(422, "Pick one of this story's scenes.")
    try:
        made = animator.make_thumbnail(video_id, video["plan"], lead=lead, punch=punch, background=background)
    except Exception as e:
        raise HTTPException(409, f"Couldn't make the thumbnail: {e}")
    db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "thumbnail": made})
    return _video_json(db.get_video(video_id))


@router.get("/media/thumb/{video_id}/wide.jpg", include_in_schema=False)
def thumb_wide(video_id: int):
    path = animator.thumb_paths(video_id)[1]
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/api/review")
def review_page():
    """Agent 5's page: what it checks, the stories it turned down (being made again by themselves), its recent reviews
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
    low, high = series.minutes()
    return {"history": [{**h, "title": titles.get(h["video_id"])} for h in history], "held": held,
            "lessons": learned, "max_rounds": reviewer.MAX_ROUNDS,
            "checks": {"min_match": reviewer.MIN_MATCH, "his_pitch": voiceprint.PITCH, "loudness": film_sound.LUFS_TARGET,
                       "bubbles_least": reviewer.BUBBLES_LEAST,
                       "minutes": [low, high], "short_seconds": list(story_film.SHORT_SECONDS),
                       "short_least": reviewer.SHORT_LEAST, "short_most": story_film.SHORT_MOST,
                       "frames": reviewer.MAX_STORY_FRAMES, "recurring": reviewer.RECURRING,
                       "lookback": reviewer.LOOKBACK}}


@router.get("/media/short/{video_id}.mp4", include_in_schema=False)
def short_version(video_id: int, request: Request):
    """A story's short version (its Short and its Reel), served like a preview (in pieces)."""
    return _pieces(animator.short_path(video_id), request)


@router.get("/media/plate/{video_id}/{plate}.jpg", include_in_schema=False)
def plate_image(video_id: int, plate: str):
    """One of a story's scenes (a still of a shot), 640 px wide (made once, kept beside it)."""
    if not re.fullmatch(r"[a-z0-9_-]{1,12}", plate):
        raise HTTPException(404)
    video = db.get_video(video_id)
    painted = animator.plate_files(video_id, (video or {}).get("plan") or {})
    if plate not in painted:
        raise HTTPException(404)
    source = _in_tmp(painted[plate])
    small = _in_tmp(animator.scenes_dir(video_id) / "small" / f"{Path(source).stem}.jpg")
    if not small.exists():
        from PIL import Image

        small.parent.mkdir(parents=True, exist_ok=True)
        image = Image.open(source).convert("RGB")
        image.thumbnail((640, 640))
        image.save(small, "JPEG", quality=84)
    return FileResponse(small, media_type="image/jpeg")


STYLE_TEST_DIR = ROOT / ".tmp" / "silhouette_test"
STYLE_TEST_NOTES = {  # what each style-test video is (the silhouette look's tests, 2026-11-15/16)
    "story_algieba": ("Algieba", "Google calls this voice smooth."),
    "story_umbriel": ("Umbriel", "Google calls this voice easy-going."),
    "story_achird": ("Achird", "Google calls this voice friendly."),
    "story_sadaltager": ("Sadaltager", "Google calls this voice knowledgeable."),
    "compare_side_by_side": ("Your GIF beside the code", "Left: your reference GIF. Right: the same scene drawn in code "
                             "(9:16). It plays twice."),
    "deadline_wide": ("The film's shape (16:9, 1920x1080)", "How the 3-4 minute videos will look: more of the room is "
                      "shown (a pinboard, a shelf, a mug)."),
    "deadline_tall": ("The short version's shape (9:16, 1080x1920)", "How the short versions (the Shorts and Reels) will "
                      "look: drawn again upright, not cropped."),
}
STYLE_TEST_GROUPS = [  # (heading, what it shows, its videos, with sound)
    ("Style test 2: a 34-second mini story, in four voices",
     "The desk at dusk, a rainy street at night, a hospital room at night. Music comes in at his mother's words and rises. "
     "The picture, sounds and music are the same in all four; only the narrator changes. Pick the voice you like best.",
     ["story_algieba", "story_umbriel", "story_achird", "story_sadaltager"], True),
    ("Style test 1: your GIF's scene", "The scene from your GIF, drawn in code.",
     ["compare_side_by_side", "deadline_wide", "deadline_tall"], False),
]


@router.get("/style-test", include_in_schema=False)
def style_test_page():
    """The silhouette look's test videos (.tmp/silhouette_test), to watch before the look is built into the agents."""
    from html import escape

    there = {p.stem for p in STYLE_TEST_DIR.glob("*.mp4") if re.fullmatch(r"[a-z0-9_]{1,60}", p.stem)}
    listed = {n for _, _, names, _ in STYLE_TEST_GROUPS for n in names}
    groups = STYLE_TEST_GROUPS + [("Other test videos", "", sorted(there - listed), False)]
    sections = []
    for heading, lede, names, sound in groups:
        cards = []
        for name in (n for n in names if n in there):
            title, note = STYLE_TEST_NOTES.get(name, (name.replace("_", " ").capitalize(), ""))
            shape = "tall" if "tall" in name else ("pair" if sound else "wide")
            play = "controls" if sound else "controls loop muted"
            poster = f' poster="/media/style-test/{name}.jpg"' if (STYLE_TEST_DIR / f"{name}.jpg").is_file() else ""
            cards.append(f'<figure class="{shape}"><video src="/media/style-test/{name}.mp4#t=0.1" {play} playsinline '
                         f'preload="{"metadata" if sound else "auto"}"{poster}></video><figcaption><b>{escape(title)}</b>'
                         f'<span>{escape(note)}</span></figcaption></figure>')
        if cards:
            sections.append(f'<section><h2>{escape(heading)}</h2>' + (f'<p class="lede">{escape(lede)}</p>' if lede else "")
                            + f'<div class="grid">{"".join(cards)}</div></section>')
    body = "".join(sections) or "<p>No test videos yet.</p>"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Style test</title><style>
:root {{ color-scheme: dark; }} body {{ margin: 0; background: #120d16; color: #efe8ee; font: 15px/1.5 system-ui, sans-serif; }}
main {{ max-width: 1240px; margin: 0 auto; padding: 28px 16px 60px; }} h1 {{ font-size: 22px; margin: 0 0 4px; }}
h2 {{ font-size: 18px; margin: 34px 0 4px; }} .lede {{ color: #b9aab8; margin: 0 0 18px; max-width: 820px; }}
a {{ color: #ff8a73; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; align-items: start; }}
figure {{ margin: 0; background: #1c1520; border: 1px solid #2e2433; border-radius: 10px; overflow: hidden; }}
figure.wide {{ grid-column: 1 / -1; }} video {{ display: block; width: 100%; background: #000; }}
@media (min-width: 760px) {{ .grid:has(figure.pair) {{ grid-template-columns: 1fr 1fr; }} }}
figure.tall video {{ max-height: 78vh; object-fit: contain; }}
figcaption {{ padding: 10px 14px 12px; display: grid; gap: 2px; }} figcaption span {{ color: #b9aab8; font-size: 14px; }}
</style></head><body><main><h1>Style test: the silhouette look</h1>
<p class="lede">Drawn entirely in code from your description and your GIF: no AI pictures, nothing uploaded.
<a href="/">Back to the dashboard</a></p>{body}</main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/media/style-test/{name}.jpg", include_in_schema=False)
def style_test_poster(name: str):
    path = STYLE_TEST_DIR / f"{name}.jpg"
    if not re.fullmatch(r"[a-z0-9_]{1,60}", name) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/media/style-test/{name}.mp4", include_in_schema=False)
def style_test_video(name: str, request: Request):
    if not re.fullmatch(r"[a-z0-9_]{1,60}", name):
        raise HTTPException(404)
    return _pieces(STYLE_TEST_DIR / f"{name}.mp4", request)


@router.get("/media/preview/{video_id}.mp4", include_in_schema=False)
def preview(video_id: int, request: Request):
    """The story's film, in pieces of at most PREVIEW_PIECE, each read and closed at once: served whole, the player
    kept the file open while the page showed it, and Windows then refused to delete or make it again (2026-10-27). The
    player asks for the next piece itself."""
    return _pieces(animator.preview_path(video_id), request)


def _pieces(path: Path, request: Request):
    """A video served in pieces of at most PREVIEW_PIECE (see preview)."""
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
            if start >= size or end < start:   # (a range ending before it starts would read the whole rest at once)
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            f.seek(start)
            body = f.read(end - start + 1)
    except FileNotFoundError:
        raise HTTPException(404)
    return Response(body, status_code=206, media_type="video/mp4", headers={
        "Content-Range": f"bytes {start}-{start + len(body) - 1}/{size}", "Accept-Ranges": "bytes"})


def _in_tmp(path: Path | str) -> Path:
    """A file named in a story's plan, if it's one of the channel's own in .tmp (never another file on this computer,
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


# --- themes: your requests and Agent 1's choices ------------------------------

@router.get("/api/topics")
def topics():
    """Agent 1's page: your requests (one that names a theme is taken first) and the stories named so far."""
    briefs = []
    for v in db.list_videos(80, parts=("brief", "metadata.title")):
        brief = v["plan"].get("brief")
        if series.is_story(v) and brief:
            briefs.append({"id": v["id"], "created_at": v["created_at"], "status": v["status"],
                           "title": v["plan"].get("metadata", {}).get("title"),
                           **{k: brief.get(k) for k in ("theme", "kind", "angle", "why_now", "instruction", "mode")},
                           "from_request": bool(brief.get("request_id"))})
    return {"requests": db.list_topics(limit=60), "briefs": briefs}


@router.post("/api/topics")
async def add_topic(request: Request):
    text = " ".join(str((await _json(request)).get("text", "")).split())
    if not 3 <= len(text) <= 800:
        raise HTTPException(422, "Write your brief in 3 to 800 characters, e.g. “Write a story about GREED. Let the "
                                 "incident cost him his oldest friend.”")
    topic_id = db.add_topic(text)
    return {"id": topic_id, "text": text}


@router.get("/api/missing")
def missing():
    """What the recent stories' scripts asked for that the library doesn't have yet (Agent 3's storyboards): each piece
    and the stories that wanted it, most wanted first. It's what's added to the library next."""
    wanted: dict[str, list[int]] = {}
    for v in db.list_videos(60, parts=("story.missing",)):
        for m in (v["plan"].get("story") or {}).get("missing") or []:
            what = str(m).split(" (")[0].strip().lower()
            if what:
                wanted.setdefault(what, []).append(v["id"])
    pieces = [{"what": w, "stories": sorted(set(ids), reverse=True)} for w, ids in wanted.items()]
    return {"pieces": sorted(pieces, key=lambda p: (-len(p["stories"]), p["what"]))}


@router.get("/api/visuals")
def made_visuals():
    """The silhouettes Agent 3 (Visuals) made for the library, newest first: each its words, kind, the story it was made
    for, when, and its preview."""
    return {"visuals": [{"name": v["name"], "kind": v["kind"], "says": v["says"], "layer": v.get("layer") or "",
                         "made_for": v.get("made_for") or "", "made_at": v.get("made_at"),
                         "preview": f"/media/visual/{quote(v['name'])}.png?v={quote(str(v.get('made_at') or ''))}"}
                        for v in reversed(db.visuals())]}


@router.post("/api/visuals/{name}/remove")
def remove_made_visual(name: str):
    """A made silhouette out of the library: no later story uses it (a story made with it keeps its own copy)."""
    if not re.fullmatch(r"[a-z0-9_]{1,40}", name) or not db.remove_visual(name):
        raise HTTPException(404, "There's no such visual in the library.")
    if "visual_recipes" in sys.modules:   # (drawn in this process: forgotten here too; online nothing is drawn or imported)
        sys.modules["visual_recipes"].forget([name])
    return made_visuals()


@router.get("/media/visual/{name}.png", include_in_schema=False)
def visual_preview(name: str):
    """A made visual drawn alone (a removed one too: a story may still use it): the picture kept with it when it was
    made; one without is drawn here and kept (online, where nothing is drawn: 404 until then)."""
    if not re.fullmatch(r"[a-z0-9_]{1,40}", name):
        raise HTTPException(404)
    png = db.visual_preview(name)
    if png is None:
        rec = next((v for v in db.visuals(removed=True) if v["name"] == name), None)
        if rec is None or ON_VERCEL:
            raise HTTPException(404)
        import io

        import numpy as np
        from PIL import Image

        import visual_recipes

        rgb, _ = visual_recipes.preview(rec)
        buf = io.BytesIO()
        Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(buf, "PNG")
        png = buf.getvalue()
        db.set_visual_preview(name, png)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/api/topics/{topic_id}")
def drop_topic(topic_id: int):
    found = next((t for t in db.list_topics("waiting", limit=500) if t["id"] == topic_id), None)
    if not found:
        raise HTTPException(409, "That request isn't waiting any more.")
    db.set_topic(topic_id, "dropped", reason="Removed by you")
    return {"ok": True}


# --- the narrator (the Narrator page) -----------------------------------------------------------------------------

def _voice_state() -> dict:
    """His voice now: when it's asked again if it rests (and whether that's because today's free readings are used
    up), and the free readings left today of the day's total, renewed at `renews`."""
    left = narration.left_today()
    return {"resting": animator.rest_until(), "used_up": bool((animator.voice_resting() or {}).get("used_up")),
            "left": sum(left.values()), "daily": narration.DAILY * len(left), "renews": _clock(narration.renews_at())}



@router.get("/api/narrator")
def get_narrator():
    cfg = narrator.voice_cfg()
    voices = []
    for name, label in narrator.VOICES.items():
        sample = narrator.sample_path({**cfg, "name": name})
        voices.append({"name": name, "label": label,
                       "sample": f"/media/narrator/sample/{name}.wav{_stamp(sample)}" if sample.exists() else None})
    return {"voice": {k: cfg.get(k) for k in ("name", "model", "style", "deeper")}, "voices": voices,
            "lines": narrator.SAMPLE_LINES, "images": {},
            "series": _series_state(), **_voice_state()}


@router.patch("/api/narrator")
async def edit_narrator(request: Request):
    _local_only("Changing the narrator")
    body = await _json(request)

    def change(data):
        voice = data.setdefault("series", {}).setdefault("narrator", {})
        if body.get("voice") in narrator.VOICES:
            voice["name"] = body["voice"]
        if "deeper" in body:
            voice["deeper"] = max(0, min(2, int(body["deeper"])))
        if "style" in body:
            from ruamel.yaml.scalarstring import FoldedScalarString

            voice["style"] = FoldedScalarString(" ".join(str(body["style"]).split())[:400] or series.DEFAULTS["narrator"]["style"])
    update_config(change)
    return get_narrator()


@router.get("/media/narrator/sample/{voice}.wav", include_in_schema=False)
def narrator_sample(voice: str):
    if voice not in narrator.VOICES:
        raise HTTPException(404)
    path = narrator.sample_path({**narrator.voice_cfg(), "name": voice})
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/wav")


@router.put("/api/series")
async def save_series(request: Request):
    """The stories' own settings (Settings, S2.1): when the film goes public, its short version after it, the length,
    the themes and the hashtags."""
    _local_only("Settings")
    body = await _json(request)
    try:
        sent = body.get("cycle") if isinstance(body.get("cycle"), dict) else {}
        cycle = {**series.settings()["cycle"], **sent}
        if body.get("post_at") and not sent.get("long_at"):  # (a page from before the plan: its one time, the long story's)
            cycle["long_at"] = str(body["post_at"]).strip()
        checked = slots.validate(load_config().get("schedule") or {}, cycle)
        cycle = {k: checked[k] for k in ("start", "short_days", "shorts_at", "long_at")}
        hours = _number(body.get("short_after_hours", body.get("teaser_after_hours", series.short_after_hours())),
                        "Short version after", 0, 12, whole=False)  # (stories made before the plan; teaser: until 11-16)
        minutes = body.get("minutes") or [3, 4]
        if not isinstance(minutes, list) or len(minutes) != 2:
            raise ValueError("A long story's length: its shortest and its longest, in minutes.")
        low = _number(minutes[0], "A long story's shortest", 2, 8, whole=False)
        high = _number(minutes[1], "A long story's longest", low, 10, whole=False)
        short_low = _number((body.get("short_minutes") or [2, 3])[0], "A Short's shortest", 1, 3, whole=False)
        short_high = _number((body.get("short_minutes") or [2, 3])[1], "A Short's longest", short_low, 3, whole=False)
        themes = {}
        for kind in ("vices", "virtues"):
            found = []
            for t in body.get(kind) or []:
                t = " ".join(re.sub(r"[^a-zA-Z' -]", "", str(t)).split()).lower()[:30]
                if t and t not in found:
                    found.append(t)
            if not found:
                raise ValueError(f"{kind.title()}: name at least one.")
            themes[kind] = found[:30]
        tags = []
        for tag in body.get("hashtags") or []:
            tag = "#" + re.sub(r"[^0-9a-z_]", "", str(tag).lower())
            if len(tag) > 1 and tag != "#shorts" and tag not in tags:
                tags.append(tag)
        repeat = _number(body.get("repeat_after_days"), "Repeat a theme after", 1, 365)
    except ValueError as e:
        raise HTTPException(422, str(e))

    from ruamel.yaml.comments import CommentedSeq
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q

    def flow(items):
        seq = CommentedSeq([Q(i) for i in items])
        seq.fa.set_flow_style()
        return seq

    def change(data):
        cfg = data.setdefault("series", {})
        cfg.pop("enabled", None)  # (retired 2026-11-16: the stories are all the channel makes)
        cfg.pop("teaser_after_hours", None)  # (its name until 2026-11-16)
        cfg.pop("post_at", None)  # (one story a day until 2026-11-23: now the plan's long story's time)
        plan_cfg = cfg.setdefault("cycle", {})
        plan_cfg["start"], plan_cfg["short_days"] = Q(cycle["start"]), cycle["short_days"]
        plan_cfg["shorts_at"], plan_cfg["long_at"] = flow(cycle["shorts_at"]), Q(cycle["long_at"])
        cfg["short_minutes"] = CommentedSeq([int(x) if x == int(x) else x for x in (short_low, short_high)])
        cfg["short_minutes"].fa.set_flow_style()
        cfg["short_after_hours"] = int(hours) if hours == int(hours) else hours
        cfg["minutes"] = CommentedSeq([int(x) if x == int(x) else x for x in (low, high)])
        cfg["minutes"].fa.set_flow_style()
        cfg["repeat_after_days"] = repeat
        cfg.setdefault("themes", {})
        cfg["themes"]["vices"], cfg["themes"]["virtues"] = flow(themes["vices"]), flow(themes["virtues"])
        cfg["hashtags"] = flow(tags[:6])
    update_config(change)
    return {"series": _series_state()}


# --- tasks ----------------------------------------------------------------

@router.post("/api/tasks/{kind}")
async def start_task(kind: str, request: Request):
    # On Vercel a thread can be frozen once the response is sent, and /tmp films don't persist,
    # so this work only runs from the dashboard on your computer.
    _local_only("Writing, making and uploading stories from the dashboard")
    body = await _json(request)
    video_id = body.get("video_id")
    if kind == "prepare":
        return _start_task(kind, "Agents 1-3: writing the story for the next turn",
                           lambda p: jobs.run_job("prepare", count=1, progress=p))
    if kind == "render":
        video = _planned_or_409(video_id)
        if not series.current(video):
            raise HTTPException(409, "This was made by an earlier version of the channel: it can't be made again.")
        return _start_task(kind, f"Agents 4-5: making and reviewing story #{video_id}",
                           lambda p: jobs.run_job("publish", dry_run=True, video_id=video_id, now=True, progress=p),
                           video_id)
    if kind == "publish":
        video = _planned_or_409(video_id)
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the Channels page).")
        if not db.ready(video):
            raise HTTPException(409, "The Reviewer turned this story down: it's being made again (see the Studio).")
        return _start_task(kind, f"Agent 6: uploading story #{video_id}",
                           lambda p: jobs.run_job("publish", video_id=video_id, progress=p), video_id)
    if kind == "autopilot":
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the Channels page).")
        return _start_task(kind, "Making the next story now", _make_next_now)
    if kind == "stats":
        return _start_task(kind, "Agent 7: reading the numbers", lambda p: jobs.run_job("stats", learn=True, progress=p))
    if kind == "instagram":
        if not instagram.is_configured():
            raise HTTPException(409, "Connect Instagram first (the Channels page).")
        return _start_task(kind, "Agent 6: posting to Instagram", lambda p: jobs.run_job("instagram", progress=p))
    if kind == "narrator-sample":
        voice = body.get("voice")
        if voice not in narrator.VOICES:
            raise HTTPException(422, "Unknown voice.")
        cfg = narrator.voice_cfg()
        return _start_task(kind, f"Recording a sample of {voice} as the narrator",
                           lambda p: narrator.sample({**cfg, "name": voice}, progress=p))
    if kind == "short":
        if not youtube_auth.is_configured():
            raise HTTPException(409, "Connect YouTube first (the Channels page).")
        return _start_task(kind, f"Agent 6: sending story #{video_id}'s short version",
                           lambda p: publisher.upload_short(int(video_id), progress=p), video_id)
    if kind == "connect":
        if not CLIENT_FILE.exists():
            raise HTTPException(409, "Add your OAuth client file first (step 2).")
        return _start_task(kind, "Connecting YouTube", _connect_youtube)
    raise HTTPException(404, "Unknown task.")


@router.get("/api/tasks/{task_id}")
def task_status(task_id: str):
    if task_id.startswith("cloud-") and task_id[6:].isdigit():  # (the autopilot's run on GitHub: _cloud_task)
        if cloud := _cloud_task(db.get_run(int(task_id[6:]))):
            return cloud
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found (the server may have restarted).")
    return _public(task)


# --- results, activity -----------------------------------------------------------

@router.get("/api/results")
def results():
    table = analyst.rows(min_age=timedelta(0))
    return {"playbook": playbook(), "rows": table, "min_samples": analyst.MIN_SAMPLES,
            "taught": {a["key"]: lessons_for(a["key"]) for a in AGENTS if a["key"] != "analyst"},
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
        data = json.loads(await _body_upto(request, MAX_CLIENT_FILE, "That file is too big for an OAuth client file."))
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


# --- music: the stories' tracks --------------------------------------------------

def _music_path(name: str) -> Path:
    clean = SAFE_FILENAME.sub("", Path(name).name).strip(" .")
    path = media.STORY_MUSIC / clean
    if not clean or path.suffix.lower() not in media.MUSIC_EXTS:
        raise HTTPException(422, "Use an mp3, m4a, aac, wav or ogg file.")
    return path


@router.get("/api/music")
def music():
    """The stories' music: each film gets one of these tracks, silent until the spark, then rising to the end."""
    return [{"name": p.name, "size": p.stat().st_size, "url": f"/media/music/{quote(p.name)}",
             "credit": media.music_credit(media.track_name(p))} for p in media.music_tracks()]


@router.put("/api/music/{name}")
async def add_music(name: str, request: Request):
    _local_only("Music")
    path = _music_path(name)
    too_big = f"Music files must be under {MAX_MUSIC_BYTES >> 20} MB."
    if int(request.headers.get("content-length") or 0) > MAX_MUSIC_BYTES:  # (before any of it is read)
        raise HTTPException(422, too_big)
    data = await _body_upto(request, MAX_MUSIC_BYTES, too_big)
    if not data:
        raise HTTPException(422, too_big)
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
    return {"channel": cfg.get("channel") or {},
            "schedule": {"ahead": True, "stories_ahead": slots.STORIES_AHEAD_DEFAULT, **(cfg.get("schedule") or {})},
            "series": series.settings(), "instagram": cfg.get("instagram") or {}, "editable": not ON_VERCEL}


def _number(value, name: str, low: float, high: float, whole: bool = True):
    try:
        n = int(value) if whole else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.")
    if not low <= n <= high:
        raise ValueError(f"{name}: {low:g} to {high:g}.")
    return n


def _validated(s: dict) -> dict:
    channel, sent = s.get("channel") or {}, s.get("schedule") or {}
    if not isinstance(channel, dict) or not isinstance(sent, dict):
        raise ValueError("The settings aren't in the right shape: reload the page and try again.")
    name = str(channel.get("name", "")).strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("Channel name: 1 to 60 characters.")
    contact = str(channel.get("contact_email") or "").strip()
    if contact and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise ValueError("Contact email doesn't look like an email address.")
    # (a setting a page doesn't send keeps its value: an older page has no "ahead" switch)
    schedule = slots.validate({**(load_config().get("schedule") or {}), **sent}, series.settings()["cycle"])
    return {"name": name, "contact": contact, "schedule": schedule}


@router.put("/api/settings")
async def save_settings(request: Request):
    _local_only("Settings")
    try:
        v = _validated(await _json(request))
    except ValueError as e:
        raise HTTPException(422, str(e))

    # ruamel keeps the comments in channel.yaml; every user string is quoted so values like
    # 23:00 or NO can't be misread as numbers or booleans when the file is loaded again.
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q

    def change(data):
        ch = data.setdefault("channel", {})
        ch["name"], ch["contact_email"] = Q(v["name"]), Q(v["contact"])
        for key in ("timezone", "make_at"):
            data.setdefault("schedule", {})[key] = Q(v["schedule"][key])
        data["schedule"]["ahead"] = bool(v["schedule"]["ahead"])
        data["schedule"]["stories_ahead"] = int(v["schedule"]["stories_ahead"])
    update_config(change)
    return get_settings()
