"""
The jobs that run the channel on its posting schedule, by calling the six agents (agents/) in order: your plan of
2026-11-23 (tools/slots.py): two Shorts of 2-3 minutes a night (21:00 and 03:00 in India, each also a Reel) for three
nights, then a night with one long story of 3-4 minutes (21:00, YouTube only). Each slot is made with a video of its
form (plan["form"]). GitHub Actions looks every hour (.github/workflows/morning.yml: `due`, then `morning` when there's something to do); the
dashboard on this computer runs the same jobs while its database is the local one.

  due        the cloud's hourly check, with only the dashboard's packages installed: is there anything for a run to do
             now (a story due with its free quotas there, or the day's numbers)? Prints work=true or work=false
  morning    the autopilot's run: the next story, made and scheduled once its slot is due (as soon as the story before
             it is public: schedule.ahead) and the free quotas allow it (quota_short); then one summary to your phone and
             the day's numbers
  autopilot  the slot that's due (or, with --now / the dashboard's "Make the next video now", the next open one) -> the
             oldest story of its form ready to go up (or a new one, written on the spot) -> Agent 3 makes it and
             Agent 4 reviews it (unless that's done; a film that fails goes back to Agent 3, at most twice, then it's
             made again by itself until it passes: unmade()) -> Agent 5 uploads it, scheduled to go public on the minute
             of its slot, and its short version after it
  prepare    Agents 1 and 2 write a story: the theme and title, then the story and its moments with their bubbles
  publish    with --dry-run Agents 3 and 4 make and review a story's film and its short version (the dashboard's "Make it
             now"); without it Agent 5 then uploads them into the next open slot
  instagram  Agent 5 posts a story's short version to Instagram as a Reel once its time has come (Instagram's API can't
             schedule Reels), when Instagram is connected and switched on
  stats      Agent 6: today's numbers; weekly, the playbook and every agent's lessons

When an agent hits a snag, it's fixed where it can be: a theme the story can't be written for (it keeps breaking the
rules) is swapped for another (THEME_TRIES); a film the Reviewer fails goes back to the Animator with notes; a story whose
making or upload fails is tried once more. If that doesn't fix it, the whole process starts again at once with a new
story for the same slot (STORY_TRIES), with no waiting. Only what another story can't fix makes the run wait: Gemini out
of quota, or YouTube's sign-in.

Every job runs at below-normal priority (common.background_priority), and so do the renders it starts: on this computer,
whatever you're doing comes first and the run just takes a little longer.

A story that's waiting without its film (written from the Themes page, sent back with "Make it again", or left from a
run) is made and reviewed by the loop on this computer between runs, without anyone pressing "Make it now" (unmade()):
a failed one again after PREVIEW_RETRY, and given up after PREVIEW_TRIES failures.

A slot is due from when it opens until an hour after it (tools/slots.py opens): with schedule.ahead (on since 2026-11-19,
your choice), schedule.stories_ahead slots before it (2, your choice of 2026-11-19: tomorrow's story is always made and
the next one on its way, so one that gets stuck has a spare day); without it, from make_at on its own day. A story is
started only when YouTube has room for its two uploads and, while it still asks Gemini, in the hours stories are made in
(quota_short; story_window, your choice of 2026-11-20: from Gemini's free allowance renewing, 13:30 in India, until
midnight, so its stronger models have the day's requests and write it; a slot that would go empty by waiting doesn't
wait). The films are silent since 2026-11-19, so the narrator's free readings no longer count. When what it waits for
is there while the run still has time for the story (quota_ready_at, STORY_TIME), the run waits for it; otherwise it
ends and a later check starts it. The hourly check starts a run up to DUE_EARLY before then (GitHub starts its checks
about an hour late). Gemini's text quota can't be counted ahead: if it's out, the run stops and waits.
next_chore() is what the dashboard's loop on this computer asks every minute: the morning run while a slot is due and
its quotas are there, then a waiting story's film, then the day's numbers. Reels whose time has come are posted by the
same loop beside all that (the instagram job as a task of its own).

In the cloud (GitHub Actions) there's no such loop, and the machine is wiped after each run: the morning run posts the
Reels whose time comes while it goes, from a thread beside it (their videos are on its machine: _reels_beside); at its end
`keep` encrypts the videos of the Reels still waiting for GitHub to keep with the run (tools/kept.py), and the Reels
workflow (.github/workflows/reels.yml) runs `instagram --stay 40` at the short version's time, which fetches them from there and
posts them. While Meta refuses Instagram's connection the Reels wait for it, no try counted, and a Reels run fails once a
day so GitHub emails you (agents/publisher.py).

YouTube's daily upload limit (about 10 uploads in 24 hours for this channel on 2026-10-29, deleted ones counting too; not
documented, and it has varied): when YouTube refuses an upload for it, the story waits, nothing new is made meanwhile,
and it's tried again when YouTube should take one (upload_room_at). A run that would end before then stops at once (not a
failure) and the next run carries on; in the cloud a film already made is kept for it, not made again (keep_videos).

PAUSED=true (in .env or GitHub's variables), or the dashboard's pause switch (kept in the database), stops the morning
run and every automatic job. Stories, films and uploads you start yourself still work. Each job reports its steps
through `progress` (stderr by default; the dashboard shows them live). The morning run started from here (the cloud's)
also keeps its steps in the database as it goes (LiveSteps, note run:live), so the progress bar at the top of every
dashboard follows it too, and a new story's script is saved the moment it's written (plan "draft") for the Studio.

Usage:
    python tools/jobs.py due                   # anything to do? (GitHub's hourly check: work=true / work=false)
    python tools/jobs.py morning               # the autopilot's run (what GitHub runs when there is)
    python tools/jobs.py autopilot [--now]     # one story; --now: the next open slot, even if it isn't due
    python tools/jobs.py prepare
    python tools/jobs.py publish [--dry-run] [--newest]  # --dry-run makes and reviews but doesn't upload; --newest: the story written last
    python tools/jobs.py instagram [--stay 40]  # posts the Reels whose time has come (--stay: and those due soon)
    python tools/jobs.py keep                  # (the cloud, after a run) the videos still needed, kept
    python tools/jobs.py stats [--learn]
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the agents/ package

import db  # noqa: E402
import kept  # noqa: E402
import llm  # noqa: E402
import notify  # noqa: E402
import prompts  # noqa: E402
import series  # noqa: E402
import slots  # noqa: E402
import youtube_auth  # noqa: E402
import youtube_upload  # noqa: E402
from agents import analyst, animator, publisher, reviewer, story, theme, visuals  # noqa: E402,F401
from common import background_priority, env, hide_secrets_in_crashes, is_true, redact  # noqa: E402

LATE_GRACE = timedelta(minutes=60)     # a slot stays due this long after it (the story then goes live at once)
STALE_CLAIM = timedelta(minutes=45)    # "making" for longer means the run was cut off (a story takes 15-30 minutes)
MANUAL_LEAD = timedelta(minutes=10)    # an upload you start yourself takes a slot at least this far ahead
STATS_EVERY = timedelta(hours=20)      # the Analyst reads the numbers about once a day
STATS_RETRY = timedelta(hours=1)       # ...and after a failed read, tries again this long after
THEME_TRIES = 3                        # themes Agent 1 may pick before a story is given up
STORY_TRIES = 3                        # stories tried, one after another, for one slot before the run waits
PREVIEW_RETRY = timedelta(minutes=30)  # a waiting story whose film failed is made again this long after
PREVIEW_TRIES = 3                      # ...and given up after this many failures
MORNING_WAIT = timedelta(minutes=30)   # a run started this early waits for make_at (GitHub starts it at 06:55)
RETRY_FIRST = timedelta(minutes=2)     # after a story fails: 2, 4, 8, 16 minutes before the next try...
RETRY_MOST = timedelta(minutes=20)     # ...up to 20, so Gemini's free per-minute limits recover
UPLOAD_WAIT = timedelta(hours=1)       # YouTube's daily upload limit reached: its story tried again at most this much
                                       # later, or when YouTube should take one again (upload_room_at), if that's sooner
UPLOAD_SOONEST = timedelta(minutes=2)  # ...but not sooner than this
PACIFIC = ZoneInfo("America/Los_Angeles")  # (YouTube's days may be California's: its upload limit isn't documented)
LIMIT_STOP = "YouTube's daily upload limit"
MAX_TRIES = 6                          # stories tried in one run before it stops (something's wrong every time)
RUN_LIMIT = timedelta(hours=5, minutes=40)  # a run stops before GitHub's 6-hour job limit
REELS_EVERY = 60                       # seconds: how often the cloud's morning run looks for Reels due (_reels_beside)
SLOT_PARTS = ("metadata.title", "draft.title", "brief.theme", "instagram", "short_upload", "form", "review.passed",
              "review.held", "review.override", "render.id", "render.look")  # what the schedule
                                                                                                    # shows (db.LIGHT)
AHEAD_LOOK = timedelta(days=9)          # how far ahead the slots are looked at for one that's due (opens decides)
PAUSE_CHECK = timedelta(minutes=10)    # while a run waits, the dashboard's pause switch (in the database) is read this
                                       # often: every read wakes the database
REELS_FINISH = timedelta(minutes=10)   # ...and how long it waits, at its end, for a Reel being posted
QUOTA_WAIT = "it waits for the free quotas"  # (a run stopped for them: not a failure, a later check starts it)
GEMINI_DOWN = {"quota": "Gemini's free requests ran out (a later check tries again, the story's brief kept)",
               "busy": "Gemini is overloaded (Google's servers; a later check tries again, the story's brief kept)"}
KEPT_BRIEF_AGE = timedelta(days=2)  # a brief kept while Gemini was down (keep_brief) is written within this, or dropped
STORY_TIME = timedelta(hours=2)        # what a run keeps for a story after waiting for the free quotas (its moments,
                                       # storyboard, film and review): it waits only when that's still there after
QUOTA_WAITS = 6                        # waits for the free quotas in one run, at most
DUE_EARLY = timedelta(minutes=75)      # the hourly check starts a run this long before the free quotas a due story waits
                                       # for are back; the run waits for them (GitHub starts its checks about an hour late)
LIVE_JOBS = ("morning",)               # jobs whose steps are kept in the database as they go when started from here
LIVE_NOTE = "run:live"                 # ...in this note (the dashboards' progress bar for a run in the cloud)
LIVE_EVERY = 10                        # seconds: at most this often (the newest steps always reach it)
LIVE_KEEP = 60                         # steps kept in it
DRAFT_KEYS = ("title", "theme", "core_message", "script", "closing_line", "words", "estimate")  # a script's draft
clock = slots.clock


def _log(message: str) -> None:
    print(f"  {redact(message)}", file=sys.stderr, flush=True)  # (the cloud run's log is public on GitHub)


def _run_url() -> str | None:
    """This GitHub Actions run's page, when it is one."""
    server, repo, run = env("GITHUB_SERVER_URL"), env("GITHUB_REPOSITORY"), env("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else None


class LiveSteps:
    """A job's progress as it goes, for the dashboards: each line goes to the log (_log), and the steps so far go to the
    database (note run:live) at most every LIVE_EVERY seconds, the newest always, from a thread of its own (one shared
    connection), so that the progress bar at the top of the dashboard (here, online) follows a run in the cloud the way
    it follows one started from the dashboard. Keeping them never stops the run: a copy that can't be written waits for
    the next. end() writes the last one, with how the run ended."""

    def __init__(self, job: str):
        self.job, self.started, self.url = job, _now(), _run_url()
        self.steps: list[dict] = []
        self.lock, self.stop, self.dirty = threading.Lock(), threading.Event(), False
        self._keep("running")
        self.thread = threading.Thread(target=self._loop, name="live-steps", daemon=True)
        self.thread.start()

    def __call__(self, message: str) -> None:
        _log(message)
        with self.lock:
            self.steps.append({"at": round((_now() - self.started).total_seconds(), 1), "text": redact(str(message))[:300]})
            del self.steps[:-LIVE_KEEP]
            self.dirty = True

    def _loop(self) -> None:
        with db.held():  # (one connection for all its copies, not a new one every few seconds)
            while not self.stop.wait(LIVE_EVERY):
                if self.dirty:
                    self._keep("running")

    def _keep(self, status: str, **extra) -> None:
        with self.lock:
            body = {"job": self.job, "started": slots.iso(self.started), "status": status, "steps": list(self.steps),
                    "url": self.url, **extra, "at": db.now_iso()}
            self.dirty = False
        try:
            db.keep_note(LIVE_NOTE, body)
        except Exception:  # (the dashboard's copy can wait for the next step; the run can't)
            with self.lock:
                self.dirty = True

    def end(self, status: str, **extra) -> None:
        self.stop.set()
        self.thread.join(LIVE_EVERY + 30)
        self._keep(status, **extra)


def paused() -> bool:
    """The kill switch: PAUSED in .env (or GitHub's variables), or the dashboard's switch (kept in the database,
    so it also stops the run in the cloud)."""
    return is_true("PAUSED") or db.paused()


def _paused() -> dict | None:
    return {"skipped": "the autopilot is paused"} if paused() else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- slots ----------------------------------------------------------------

def slot_board(start: datetime, end: datetime, sched: dict, now: datetime | None = None) -> list[dict]:
    """Each slot from start to end, with the story holding it and where it stands: posted, scheduled, making, late (its
    time has come), due (it has opened: tools/slots.py opens), open (it opens later) or missed."""
    now = now or _now()
    holders = db.slot_holders(slots.iso(start - sched["every"]), slots.iso(end + sched["every"]), parts=SLOT_PARTS)
    board, taken = [], set()
    for slot in slots.between(start, end, sched):
        key, form = slots.iso(slot), slots.form(slot, sched)
        # A story holds its slot. One whose slot is on an earlier clock (the time was changed: retime moves it; until
        # then, and for one gone public, its night is still taken) or from before slots existed (only a publish time)
        # holds the nearest slot of its form that night.
        night = slots.posting_day(slot, sched)
        video = next((v for v in holders if v["slot"] == key), None) or next(
            (v for v in sorted(holders, key=lambda v: abs(slots.parse(v["slot"] or v["publish_at"]) - slot))
             if v["id"] not in taken and series.form_of(v) == form and not slots.parse(v["slot"] or v["publish_at"]) in
             slots.day_slots(night, sched) and slots.posting_day(slots.parse(v["slot"] or v["publish_at"]), sched) == night),
            None)
        if video:
            taken.add(video["id"])
            live = video["status"] == "scheduled" and slots.parse(video["publish_at"]) <= now
            state = "posted" if live else video["status"]
        elif slot < now - LATE_GRACE:
            state = "missed"
        else:
            state = "late" if slot <= now else "due" if now >= slots.opens(slot, sched) else "open"
        board.append({"slot": slot, "state": state, "video": video, "form": form})
    return board


def due_slot(now: datetime | None = None, sched: dict | None = None) -> datetime | None:
    """The earliest slot that needs a story now, if any: one no story holds that has opened (tools/slots.py opens: up to
    schedule.stories_ahead slots ahead). Its form (a Short or a long story) is slots.form."""
    now, sched = now or _now(), sched or slots.plan()
    return next((s["slot"] for s in slot_board(now - LATE_GRACE, now + AHEAD_LOOK, sched, now)
                 if s["state"] in ("late", "due")), None)


def next_open_slot(lead: timedelta, now: datetime | None = None, sched: dict | None = None,
                   form: str | None = None) -> datetime:
    """The earliest slot at least `lead` from now that no story holds (of `form`: a Short's or a long story's)."""
    now, sched = now or _now(), sched or slots.plan()
    found = next((s["slot"] for s in slot_board(now + lead, now + timedelta(days=12), sched, now)
                  if s["state"] in ("due", "open") and form in (None, s["form"])), None)
    if not found:
        raise RuntimeError(f"every {slots.FORM_WORDS.get(form, 'video')} slot of the next week and a half is taken")
    return found


LINE_AHEAD = timedelta(days=12)  # how far along the line of turns the next story's turn is looked for (next_to_make)


def waiting(rows: list[dict] | None = None) -> list[dict]:
    """The stories written and waiting for a turn, in the order the autopilot takes them (publisher.choose: the oldest
    first, not held by the Reviewer, not drawn in an earlier look), read in part (SLOT_PARTS); `rows`: the waiting
    rows already read."""
    rows = db.planned_videos(parts=SLOT_PARTS) if rows is None else rows
    return [v for v in rows if db.ready(v) and (not (v["plan"].get("render") or {}).get("id")
                                                or (v["plan"].get("render") or {}).get("look") == series.LOOK)]


def line(now: datetime | None = None, sched: dict | None = None, start: datetime | None = None,
         end: datetime | None = None, pending: list[dict] | None = None) -> list[dict]:
    """The turns from `start` (an hour ago) to `end` (LINE_AHEAD on) in posting order (tools/slots.py: two Shorts a
    night for three nights, then a long story), each with its form, its night and which night of its round that is
    (slots.cycle_day), where it stands (slot_board: posted, scheduled, making, late, due, open or missed), when its
    making opens (slots.opens) and its story: the one holding it (uploaded, or being made for it) or, for a turn no
    story holds, the written one the autopilot takes for it at its turn (`queued`: the oldest waiting story of its form,
    as publisher.choose takes them). The Studio, the Schedule page and prepare all read it, so a story is only ever
    written for the next turn's form. `pending`: waiting(), already read."""
    now, sched = now or _now(), sched or slots.plan()
    pending = waiting() if pending is None else pending
    turns, used = [], set()
    for s in slot_board(start or now - LATE_GRACE, end or now + LINE_AHEAD, sched, now):
        queued = None
        if s["state"] in ("late", "due", "open"):  # (no story holds it)
            queued = next((v for v in pending if v["id"] not in used and series.form_of(v) == s["form"]), None)
            if queued:
                used.add(queued["id"])
        night = slots.posting_day(s["slot"], sched)
        turns.append({**s, "queued": queued, "night": night, "night_no": slots.cycle_day(night, sched),
                      "opens": slots.opens(s["slot"], sched)})
    return turns


def next_to_make(now: datetime | None = None, sched: dict | None = None,
                 turns: list[dict] | None = None) -> dict | None:
    """The first turn in the line no story is for yet (none uploaded, being made, or written and waiting for it): the
    next story written is of its form (prepare). None when every turn of the next LINE_AHEAD has one. `turns`: the
    line, already read (from before now: its turns gone by aren't open)."""
    turns = line(now, sched) if turns is None else turns
    return next((t for t in turns if t["state"] in ("late", "due", "open") and not t["queued"]), None)


def check(progress=_log) -> datetime | None:
    """The cheap part of each check: check in, free stories whose run was cut off, give up Reels too old to post, and
    say whether a slot is due."""
    db.beat("autopilot")
    for row in db.release_stale(slots.iso(_now() - STALE_CLAIM)):
        progress(f"Story #{row['id']} was interrupted while being made; it's now {row['status']}")
    publisher.expire_reels(progress)
    if youtube_auth.is_configured():  # (the cloud's hourly check has no YouTube keys: due() starts a run for it)
        retime(progress)
    return due_slot()


RETIME_LEAD = timedelta(minutes=30)  # a story this close to going public isn't moved (YouTube is about to publish it)


def retime_moves(now: datetime | None = None, sched: dict | None = None) -> list[tuple[dict, datetime]]:
    """Stories whose time isn't on the schedule's clock any more (the time was changed: Settings, or channel.yaml;
    2026-11-23: the plan's 21:00), uploaded ones still to go public and ones being made, each with the slot of its form
    its night has now (the nearest, for a night of two Shorts; none, for a night of the other form: it stays where it
    is). None is moved within RETIME_LEAD of going public, nor to a time that close, nor to a slot another story holds."""
    now, sched = now or _now(), sched or slots.plan()
    holders = db.slot_holders(slots.iso(now + RETIME_LEAD), slots.iso(now + timedelta(days=60)), parts=("form",))
    held: dict[str, set] = {}  # (a time -> the stories on it)
    for v in holders:
        for t in {v["slot"], v["publish_at"]} - {None}:
            held.setdefault(t, set()).add(v["id"])
    moves = []
    for v in holders:
        when = v["publish_at"] if v["status"] == "scheduled" else v["slot"]
        if not when or slots.parse(when) <= now + RETIME_LEAD:
            continue
        old = slots.parse(when)
        night = slots.posting_day(old, sched)
        same = [s for s in slots.day_slots(night, sched) if slots.form(s, sched) == series.form_of(v)]
        if not same or old in same:
            continue
        new = min(same, key=lambda s: abs(s - old))
        if new > now + RETIME_LEAD and not held.get(slots.iso(new), set()) - {v["id"]}:
            moves.append((v, new))
            held.setdefault(slots.iso(new), set()).add(v["id"])
    return moves


def retime(progress=_log, now: datetime | None = None, sched: dict | None = None) -> list[int]:
    """Moves the stories retime_moves finds to their slot on the clock. An uploaded one: its video on YouTube (a story
    made before the plan: its short version too, series.short_after_hours after it), its Reel (a Short's, or the short
    version's) with it, its slot and publish time here.
    One being made: only its slot (so its day doesn't get a second story; its run uploads it at the old time and the
    next check moves it). A video public already, or made private in YouTube Studio, is left as it is. Never fails a
    check: a story that can't be moved is said and stays where it was."""
    sched = sched or slots.plan()
    moved = []
    for light, new in retime_moves(now, sched):
        v = db.get_video(light["id"])
        at = f"{new.astimezone(sched['tz']):%a %d %b} {clock(new, sched)}"
        try:
            if v["status"] == "making":
                db.update_video(v["id"], slot=slots.iso(new))
            else:
                film = youtube_upload.reschedule(v["youtube_id"], slots.iso(new))
                if not film.get("moved"):
                    progress(f"Story #{v['id']} wasn't moved to {at}: on YouTube it's {next(iter(film))} already")
                    continue
                plan = v["plan"]
                if series.form_of(v) == "short" and (plan.get("instagram") or {}).get("status") == "pending":
                    plan = {**plan, "instagram": {**plan["instagram"], "at": slots.iso(new)}}  # (a Short's Reel: with it)
                short = plan.get("short_upload") or {}
                if short.get("youtube_id") and short.get("publish_at") and slots.parse(short["publish_at"]) > _now():
                    short_at = slots.iso(new + timedelta(hours=series.short_after_hours()))
                    if youtube_upload.reschedule(short["youtube_id"], short_at).get("moved"):
                        plan = {**plan, "short_upload": {**short, "publish_at": short_at}}
                        if (plan.get("instagram") or {}).get("status") == "pending":
                            plan["instagram"] = {**plan["instagram"], "at": short_at}
                db.update_video(v["id"], slot=slots.iso(new), publish_at=slots.iso(new), plan=plan)
            moved.append(v["id"])
            progress(f"Story #{v['id']} moved to {at}, the schedule's time now")
        except Exception as e:
            progress(f"Story #{v['id']} couldn't be moved to {at} ({str(e)[:160]}): it stays at its old time")
    return moved


def tick(progress=_log) -> dict:
    """A full autopilot run only when a slot is due."""
    if paused := _paused():
        return paused
    if not check(progress):
        return {"skipped": "no slot is due yet"}
    return run_job("autopilot", progress=progress)


def next_chore() -> tuple[str, dict] | None:
    """What the loop on this computer should do now, most urgent first, or None: the autopilot's run while a slot is due
    and the free quotas its story needs are there, then a waiting story's film, then the day's numbers. (Reels aren't a
    chore: the loop posts them at their time beside whatever is going.)"""
    if (slot := check()) and not quota_short(publisher.choose(slots.form(slot, slots.plan())), slot=slot):
        return "morning", {}
    if waiting := unmade():
        return "publish", {"dry_run": True, "video_id": waiting["id"]}
    if stats_due():
        return "stats", {}
    return None


def story_window(now: datetime | None = None, sched: dict | None = None) -> tuple[datetime, datetime]:
    """The hours stories are made in (your choice, 2026-11-20): from Gemini's free allowance renewing (llm.renews_at:
    midnight in California, 13:30 in India in winter, 12:30 in summer) until midnight on the schedule's clock, so its
    stronger models have the day's requests and write them (late in Gemini's day they can be used up, and then a lighter
    model writes it after long waits). (opens, closes): the window open now, or the next one."""
    now = now or _now()
    tz = (sched or slots.plan())["tz"]

    def midnight_after(t):
        return datetime.combine(t.astimezone(tz).date() + timedelta(days=1), dtime(0), tzinfo=tz).astimezone(timezone.utc)

    opens = llm.renewed_at(now)
    if now >= midnight_after(opens):
        opens = llm.renews_at(now)
    return opens, midnight_after(opens)


def story_wait(now: datetime | None = None) -> datetime | None:
    """When a story may be started, if not now: the opening of the hours stories are made in (story_window); None while
    they're open."""
    now = now or _now()
    opens, closes = story_window(now)
    return None if opens <= now < closes else opens


def needs_gemini(row: dict | None) -> bool:
    """Would making this story ask Gemini: one not written yet, or one whose film and short version aren't made and
    passed yet? (One made and passed, waiting only for YouTube, doesn't: its upload never waits for story_window.)"""
    if row is None:
        return True
    plan = row["plan"]
    kept_by = plan.get("kept_video") or {}
    kept_film = bool(kept_by.get("run") and kept_by.get("render") == (plan.get("render") or {}).get("id"))
    made = kept_film or animator.preview_path(row["id"]).exists()   # (no short version since 2026-11-23)
    return not (made and reviewer.passed(plan))


def cant_wait(opens: datetime, slot: datetime | None) -> bool:
    """Would waiting for story_window's opening leave `slot` empty (less than STORY_TIME to make it)? Then the story is
    made at once: better a lighter model's story than an empty slot."""
    return slot is not None and opens + STORY_TIME > slot


def quota_short(row: dict | None = None, now: datetime | None = None, slot: datetime | None = None) -> str | None:
    """What a story needs that isn't there now, in plain words, or None when it's all there: YouTube's room for its
    upload (its daily upload limit) and, for one that still asks Gemini (needs_gemini), the hours stories are made in
    (story_window), unless waiting for them would leave its `slot` empty (cant_wait). A story is started only when this
    is None, so nothing is spent on one that would have to stop half-way. (The films are silent since 2026-11-19: the
    narrator's free readings no longer count.)"""
    now = now or _now()
    sched = slots.plan()
    room = upload_room_at(now)
    if room and room > now:
        return f"YouTube's daily upload limit (it should take uploads again at about {clock(room, sched)})"
    opens = story_wait(now)
    if opens and needs_gemini(row) and not cant_wait(opens, slot):
        return f"Gemini's free allowance (stories are made after it renews at {clock(opens, sched)})"
    return None


def quota_ready_at(row: dict | None = None, now: datetime | None = None, slot: datetime | None = None) -> datetime:
    """When what a story waits for (quota_short) should all be there: YouTube taking uploads again, and the hours
    stories are made in (story_window). Now when nothing is short."""
    now = now or _now()
    room = upload_room_at(now)
    at = room if room and room > now else now
    opens = story_wait(at)
    if opens and needs_gemini(row) and not cant_wait(opens, slot):
        at = max(at, opens)
    return at


def story_name(slot: datetime, sched: dict, first: bool = False) -> str:
    """A slot's video in words, e.g. "tomorrow's 21:00 Short" or "Monday's 21:00 long story" (`first`: to begin a
    sentence, "Tomorrow's 21:00 Short")."""
    word = slots.day_word(slot, sched, _now())
    if word in ("Today's", "Tomorrow's") and not first:
        word = word.lower()
    return f"{word} {clock(slot, sched)} {slots.FORM_WORDS[slots.form(slot, sched)]}"


def due(progress=_log) -> dict:
    """The cloud's hourly check (the first step of .github/workflows/morning.yml, before the video-making packages are
    installed): {"work", "why"}: is there anything for a run to do now? A story whose slot is due and whose free quotas
    are there (or are back within DUE_EARLY: the run starts now and waits for them, so the story starts the moment they
    are, not when GitHub gets round to the next check), or the day's numbers. Its verdict is kept for the dashboard (note
    autopilot:check); it isn't a run."""
    sched = slots.plan()
    if paused():
        found = {"work": False, "why": "the autopilot is paused"}
    elif slot := check(progress):
        row = publisher.choose(slots.form(slot, sched))
        name = story_name(slot, sched, first=True)
        short = quota_short(row, slot=slot)
        ready = quota_ready_at(row, slot=slot) if short else None
        if not short:
            found = {"work": True, "why": f"{name} is due: making it now"}
        elif ready and ready - _now() <= DUE_EARLY:
            found = {"work": True, "why": f"{name} is due and waits for {short}: the run starts now and waits until "
                                          f"about {clock(ready, sched)}", "waits": short}
        else:
            found = {"work": stats_due(), "why": f"{name} is due and waits for {short}", "waits": short}
    elif not youtube_auth.is_configured() and (moves := retime_moves()):
        found = {"work": True, "why": f"{len(moves)} {'story moves' if len(moves) == 1 else 'stories move'} to the "
                                      "schedule's new time"}
    elif stats_due():
        found = {"work": True, "why": "the day's numbers are due"}
    else:
        found = {"work": False, "why": "nothing to do: the next story is scheduled"}
    db.keep_note("autopilot:check", {**found, "at": db.now_iso()})
    return found


def stats_due() -> bool:
    """Is it time for the Analyst to read the numbers: STATS_EVERY since it last did, not within STATS_RETRY of a
    failed or unfinished try, and something published to read."""
    if not db.published_videos(days=60, parts=()):
        return False
    tried = db.last_run("analyst", ok=None)
    if tried and not tried["ok"] and _now() - slots.parse(tried["started_at"]) < STATS_RETRY:
        return False
    read = db.last_run("analyst")
    return not read or _now() - slots.parse(read["started_at"]) >= STATS_EVERY


def unmade() -> dict | None:
    """The oldest waiting story whose film isn't made, or isn't reviewed as it is now: the Animator makes it without
    anyone pressing "Make it now". One the Reviewer turned down after the fixes is made again by itself when its
    remake_at comes (until it passes: nothing waits for you, your call on 2026-10-27); one that failed is made again
    PREVIEW_RETRY later. Only in the hours stories are made in (story_window: its film asks Gemini)."""
    if story_wait():
        return None
    return next((v for v in db.planned_videos() if to_make(v)), None)


def to_make(v: dict) -> bool:
    """Is this waiting story's film, or its short version, for the loop to make now (unmade())?"""
    plan = v["plan"]
    review = plan.get("review") or {}
    if not plan.get("story") or not series.current({**v, "plan": {k: x for k, x in plan.items() if k != "render"}}):
        return False
    if review.get("held"):  # turned down after the fixes: made again by itself when its time comes
        return (review.get("remake_at") or "") <= db.now_iso()
    made = (animator.preview_path(v["id"]).exists() and (plan.get("render") or {}).get("id")
            and (plan.get("render") or {}).get("look") == series.LOOK)   # (no short version since 2026-11-23)
    if made and reviewer.current(plan):
        return False
    failed = plan.get("preview_failed_at")
    return not (failed and _now() - slots.parse(failed) < PREVIEW_RETRY)


def _must_wait(error: BaseException | None) -> bool:
    """Is it something no other story would get past: Gemini's voice out, Gemini out of quota or refusing the key,
    YouTube's sign-in or its daily upload limit, the look's description unreadable? Then the run waits instead of
    throwing away good stories."""
    while error:
        if isinstance(error, (animator.Resting, youtube_auth.YouTubeAuthError, youtube_upload.UploadLimit, prompts.NoPromptKey)):
            return True
        if any(sign in str(error) for sign in ("All Gemini models failed", "Gemini rejected the API key")):
            return True
        error = error.__cause__ or error.__context__
    return False


# --- making stories -----------------------------------------------------------

def keep_brief(brief: dict | None, form: str) -> None:
    """Keeps the brief of a story Gemini couldn't write (it was down: overloaded or out of its free requests, not the
    brief's fault) for the next try at a story of that form, which writes it first: while Gemini is down every new brief
    would use one of its few free requests for nothing (the evening of 2026-11-23: 16 briefs in 5 hours, and the
    stronger models' requests for the day were gone). None: clears it."""
    try:
        db.keep_note(f"kept_brief:{form}", brief or {})
    except Exception as e:
        _log(f"(the brief wasn't kept for the next try: {str(e)[:120]})")


def kept_brief(form: str) -> dict | None:
    """The brief kept for the next story of `form` (keep_brief), taken: cleared as it's read and kept again only if
    Gemini fails it again, so a brief that's itself the trouble isn't tried for ever."""
    try:
        brief = db.fresh_note(f"kept_brief:{form}", KEPT_BRIEF_AGE)
        if brief:
            keep_brief(None, form)
        return brief or None
    except Exception:
        return None


def make_story(progress=_log, on_script=None, form: str = "long") -> dict:
    """The next story of `form` ("short": a Short of 2-3 minutes, upright; "long": a long story of 3-4 minutes): Agent 1
    writes the brief, Agent 2 (your script writer) the script at the form's length, Agent 3 (Visuals, agents/visuals.py)
    its pictures: the storyboard from the library (its places, its people, a shot for every line), and any thing or
    bubble picture the library lacks made new as a silhouette. A brief the story can't be made for (it keeps
    breaking the rules) is swapped for another. `on_script(brief, story)`: told each script as soon as it's written,
    before Agent 3's storyboard (the Studio shows it meanwhile). A brief kept from a try Gemini couldn't answer
    (keep_brief) is written first: no new brief is asked of Gemini while it's down."""
    avoid, why = [], []
    kept = kept_brief(form)
    for attempt in range(THEME_TRIES):
        if attempt == 0 and kept:
            brief = kept
            progress(f"Writing the brief kept from when Gemini couldn't answer (“{brief.get('theme')}”)")
        else:
            brief = theme.run(progress=progress, avoid=avoid)["brief"]
        try:
            written = story.run(brief, progress=progress, form=form)
            if on_script:
                on_script(brief, written["story"])
            boarded = visuals.run(written["story"], progress=progress)   # (Agent 3: its pictures; new ones made)
            written = {"story": boarded, "metadata": story.metadata(boarded),
                       "script": {**written["script"], "lines": story.lines_of(boarded)}}
        except Exception as e:
            if _must_wait(e):
                if llm.down(e):  # (Gemini itself: no other brief would get past it, so this one is written next time)
                    keep_brief(brief, form)
                raise
            progress(f"Snag with “{brief['theme']}” ({str(e)[:160]})"
                     + ("; choosing another theme" if attempt + 1 < THEME_TRIES else ""))
            avoid.append(brief["theme"])
            why.append(f"{brief['theme']}: {str(e)[:120]}")
            continue
        return {"form": form, "brief": brief, "story": written["story"], "script": written["script"],
                "metadata": written["metadata"]}
    raise RuntimeError(f"no story could be written ({'; '.join(why)})")


def _draft_saved(video_id: int, brief: dict, written: dict, form: str = "long") -> None:
    """A story being made, as soon as its script is written: its draft (plan {"draft"}: its title, theme, core message,
    script and closing line, and the brief) for the Studio and the schedule while Agent 3 designs its pictures. The whole
    plan replaces it when the storyboard is done. Never stops the story: a draft that can't be saved isn't shown."""
    try:
        draft = {k: written.get(k) for k in DRAFT_KEYS} | {"brief": brief.get("instruction") or ""}
        db.update_video(video_id, theme=written.get("theme") or brief.get("theme") or None,
                        plan={"form": form, "draft": draft})
    except Exception as e:
        _log(f"(the script's draft wasn't saved for the dashboard: {str(e)[:120]})")


def _saved(plan: dict, video_id: int) -> None:
    """After a story is saved: mark the request it answers."""
    if plan["brief"].get("request_id"):
        db.set_topic(plan["brief"]["request_id"], "used", video_id=video_id)


def autopilot(force: bool = False, slot: datetime | None = None, progress=_log) -> dict:
    """Makes and uploads the video for `slot` (a story of the slot's form), or the earliest slot that's due. With force,
    takes the next open slot even if it isn't due yet (the dashboard's "Make the next video now"). A story that fails is tried once more (it goes
    back to the queue), then another story takes its place, up to STORY_TRIES, with no waiting; what no other story would
    fix (_must_wait) is raised at once."""
    sched = slots.plan()
    now = _now()
    slot = slot or due_slot(now, sched) or (next_open_slot(publisher.GO_LIVE_MARGIN, now, sched) if force else None)
    if not slot:
        return {"skipped": "no slot is due yet"}
    when = clock(slot, sched)
    snags = []
    for attempt in range(STORY_TRIES):
        try:
            return _fill(slot, sched, when, progress)
        except Exception as e:
            if _must_wait(e):
                raise
            snags.append(str(e)[:200])
            if attempt + 1 < STORY_TRIES:
                progress(f"Snag: {str(e)[:200]}. Starting again for the {when} slot")
    raise RuntimeError(f"Couldn't make the {when} story in {STORY_TRIES} tries: " + " | ".join(snags))


def _fill(slot: datetime, sched: dict, when: str, progress) -> dict:
    """One try at the slot: the oldest story of its form ready to go up (a failed try puts it back once), or a new one
    written on the spot; then the Publisher (the Animator and the Reviewer first)."""
    form = slots.form(slot, sched)
    row = publisher.choose(form)
    if row:
        if not db.claim(row["id"], slots.iso(slot)):
            return {"skipped": f"another run is already making the {when} story"}
        progress(f"Using story #{row['id']} for the {when} slot")
        row = db.get_video(row["id"])
    else:
        video_id = db.insert_video("making", db.fmt(), None, None, {"form": form}, slot=slots.iso(slot))
        if video_id is None:
            return {"skipped": f"another run is already making the {when} story"}
        progress(f"No {slots.FORM_WORDS[form]} ready: writing one for the {when} slot")
        try:
            plan = make_story(progress, form=form,
                              on_script=lambda brief, written: _draft_saved(video_id, brief, written, form))
        except Exception as e:
            db.update_video(video_id, status="skipped", error=str(e)[:500])
            raise RuntimeError(f"Couldn't make the {when} story: {e}") from e
        db.update_video(video_id, theme=plan["brief"]["theme"], plan=plan)
        _saved(plan, video_id)
        row = db.get_video(video_id)
    return publisher.run(row, slot, sched, progress=progress)


def upload_room_at(now: datetime | None = None) -> datetime | None:
    """When YouTube should take the channel's next upload, while its daily upload limit holds (it refused one in the
    last 24 hours): the moment the oldest of the uploads filling the limit is 24 hours old (the limit being as many as
    there were in the 24 hours before the refusal), or midnight in California if that's sooner (YouTube doesn't say
    whether its days roll or are calendar days); now if there's room. None if YouTube hasn't refused one for 24 hours."""
    now = now or _now()
    hit = db.fresh_note("youtube_limit", timedelta(hours=24))
    if not hit:
        return None
    times = [slots.parse(t) for t in db.upload_times(slots.iso(now - timedelta(hours=24)))]
    limit = int(hit.get("count") or 0)
    if not limit:  # (refused with none of ours in the 24 hours before: nothing to go by)
        return None
    if len(times) < limit:
        return now
    rolls = times[len(times) - limit] + timedelta(hours=24)
    midnight = datetime.combine(now.astimezone(PACIFIC).date() + timedelta(days=1), datetime.min.time(), tzinfo=PACIFIC)
    return min(rolls, midnight.astimezone(timezone.utc))


def upload_limit_hit() -> datetime:
    """YouTube just refused an upload for its daily limit: as many uploads as went up in the last 24 hours is the limit
    for now (recorded for upload_room_at and the dashboard); when it should take one again."""
    now = _now()
    db.keep_note("youtube_limit", {"at": slots.iso(now),
                                   "count": len(db.upload_times(slots.iso(now - timedelta(hours=24))))})
    return upload_room_at(now) or now + UPLOAD_WAIT


def _upload_limit(error: BaseException | None) -> bool:
    """Is it YouTube's daily upload limit? Then nothing goes up for a while, whichever story it is."""
    while error:
        if isinstance(error, youtube_upload.UploadLimit):
            return True
        error = error.__cause__ or error.__context__
    return False


def _signed_out(error: BaseException | None) -> bool:
    """Is it YouTube's sign-in (revoked or expired)? Then every story would fail the same way."""
    while error:
        if isinstance(error, youtube_auth.YouTubeAuthError):
            return True
        error = error.__cause__ or error.__context__
    return False


def day_count(day, sched: dict) -> tuple[int, int]:
    """How many of a posting day's slots have their story scheduled (or posted), and how many there are."""
    times = slots.day_slots(day, sched)
    board = slot_board(times[0], times[-1], sched)
    return sum(1 for s in board if s["state"] in ("scheduled", "posted")), len(board)


def morning(progress=_log) -> dict:
    """The autopilot's run: the story of the slot that's due (as soon as the story before it is public, with
    schedule.ahead; else from make_at on its day), made and scheduled when the free quotas it needs are there
    (quota_short: otherwise it stops at once, not a failure, and a later check starts it); then one summary to your
    phone and the day's numbers. A story that fails doesn't stop it: the next try waits RETRY_FIRST, twice as long after
    each failure in a row, up to RETRY_MOST. It stops early (an error, so GitHub marks the run failed and emails you) when
    YouTube's sign-in is broken, after MAX_TRIES stories, or at RUN_LIMIT; the pause switch stops it quietly. In the cloud
    the Reels whose time comes meanwhile are posted beside it (_reels_beside)."""
    try:
        if not (kept.in_cloud() and publisher.reels_on()):
            return _morning(progress)
        stop = threading.Event()
        beside = threading.Thread(target=_reels_beside, args=(stop, progress), name="reels", daemon=True)
        beside.start()
        try:
            return _morning(progress)
        finally:
            stop.set()
            beside.join(REELS_FINISH.total_seconds())  # (a Reel being posted isn't cut off)
    finally:
        progress(f"Gemini calls this run: {dict(llm.calls) or 'none'}")


def _reels_beside(stop: threading.Event, progress) -> None:
    """In the cloud, while the morning run goes: every REELS_EVERY seconds, the Reels whose time has come and whose
    video is on this machine (made by this run), posted. The others are the Reels workflow's (tools/kept.py)."""
    while not stop.wait(REELS_EVERY):
        try:
            if paused():
                continue
            for row in publisher.reels_due():
                if stop.is_set():
                    break
                if animator.reel_path(row).exists() and (whole := _whole(row)):
                    publisher.run_instagram(whole, progress=progress)
        except Exception as e:  # (a Reel's own failure is handled where it's posted: this is the database or YouTube)
            progress(f"Reels: {str(e)[:200]}")


def _morning(progress) -> dict:
    """The morning run itself (morning)."""
    sched = slots.plan()
    started = _now()
    start = slots.run_starts(started.astimezone(sched["tz"]).date(), sched)
    if not sched["ahead"] and started < start <= started + MORNING_WAIT:  # (a run started just before make_at)
        progress(f"The run starts at {clock(start, sched)}; waiting until then")
        time.sleep((start - started).total_seconds())
    if skipped := _paused():
        return skipped
    if not youtube_auth.is_configured():
        raise RuntimeError("YouTube isn't connected: connect it on the dashboard's Channels page")
    made, held, tries, failures, day, stopped, pending, waited = [], [], 0, 0, None, None, None, 0
    gemini_down = None  # (why the last try failed, if it was Gemini that couldn't answer: llm.down)
    while True:
        if paused():
            stopped = "the autopilot is paused"
            break
        slot = check(progress)
        if not slot:
            pending = None
            break
        pending = slot  # (the story being filled: the one named if the run stops before it's scheduled)
        day = day or slots.posting_day(slot, sched)
        if tries >= MAX_TRIES:
            stopped = (f"{QUOTA_WAIT}: {GEMINI_DOWN[gemini_down]}" if gemini_down  # (a wait, not a failure: a later
                       else f"{MAX_TRIES} stories were tried and the slot still isn't filled")  # check tries again)
            break
        if _now() - started >= RUN_LIMIT:
            stopped = "it ran out of time"
            break
        row = publisher.choose(slots.form(slot, sched))
        if short := quota_short(row, slot=slot):  # (nothing started that would have to stop half-way)
            ready = quota_ready_at(row, slot=slot)
            if ready and waited < QUOTA_WAITS and ready + STORY_TIME <= started + RUN_LIMIT:
                # (back in time for this run: it waits for them, keeping what it has read; no hour lost to GitHub)
                waited += 1
                progress(f"{story_name(slot, sched, first=True)} waits for {short}; this run waits until about "
                         f"{clock(ready + timedelta(minutes=1), sched)} and carries on")
                _wait(max(60.0, (ready - _now()).total_seconds() + 60))
                continue
            stopped = f"{QUOTA_WAIT}: {short}"
            progress(f"{story_name(slot, sched, first=True)} waits for {short}; a later check starts it")
            break
        tries += 1
        progress(f"Making {story_name(slot, sched)}")
        try:
            result = autopilot(slot=slot, progress=progress)
        except animator.Resting as e:  # the story waits for Gemini's voice: nothing counted
            tries -= 1
            rest = animator.resting()
            wait = max(60.0, (slots.parse(rest["until"]) - _now()).total_seconds()) if rest else 60.0
            if _now() + timedelta(seconds=wait) + STORY_TIME > started + RUN_LIMIT:  # (no time left for the story after)
                stopped = (f"{QUOTA_WAIT}: {str(e)[:200]}; that is after this run must end (its readings kept), "
                           "and a later run carries on")  # (a wait, not a failure)
                break
            progress(f"{str(e)[:200]}. The {clock(slot, sched)} story waits ({wait / 60:.0f} minutes)")
            _wait(wait)
            continue
        except Exception as e:
            if _signed_out(e):
                stopped = f"YouTube's sign-in needs renewing ({e})"
                break
            if _upload_limit(e):  # YouTube's daily upload limit: the story stays queued, nothing new is made meanwhile
                tries -= 1
                room = upload_limit_hit()
                if room > started + RUN_LIMIT:  # none before this run must end: a later run uploads it (its film kept)
                    stopped = f"{LIMIT_STOP}: YouTube should take uploads again at about {clock(room, sched)}"
                    break
                wait = min(max(room - _now(), UPLOAD_SOONEST), UPLOAD_WAIT)
                progress(f"YouTube takes no more uploads for now (the channel's daily upload limit); it should take one "
                         f"again at about {clock(room, sched)}. The {clock(slot, sched)} story waits until "
                         f"{clock(_now() + wait, sched)}, its film kept")
                _wait(wait.total_seconds())
                continue
            gemini_down = llm.down(e)
            failures += 1
            wait = min(RETRY_MOST, RETRY_FIRST * 2 ** min(failures - 1, 8))
            progress(f"The {clock(slot, sched)} story failed ({str(e)[:200]}); the next try in {wait.seconds // 60} "
                     "minutes")
            _wait(wait.total_seconds())
            continue
        failures, gemini_down = 0, None
        if result.get("youtube_id"):
            made.append(result)
        elif result.get("held"):
            held.append(result["video_id"])
    if not day:  # the day's slot was taken already (a catch-up run after a full morning)
        if stats_due():  # (in the cloud the runs are the Analyst's only chance to read the numbers)
            try:
                stats(progress=progress)
            except Exception as e:
                progress(f"The day's numbers couldn't be read ({str(e)[:200]})")
        return {"skipped": "the day's story is scheduled already"}
    done, total = day_count(day, sched)
    missed = sum(1 for s in slot_board(*(slots.day_slots(day, sched)[i] for i in (0, -1)), sched) if s["state"] == "missed")
    notes = (" Its slot had passed before the run." if missed else "") + (
        f" The Reviewer turned down {len(held)} after the Animator's fixes: each is made again by itself until it passes."
        if held else "")
    result = {"made": len(made), "held": held, "tries": tries, "scheduled": done, "slots": total, "missed": missed,
              "stopped": stopped}
    if stopped != "the autopilot is paused" and stats_due():  # (first: also after a run that stopped early)
        try:
            stats(progress=progress)
        except Exception as e:  # the numbers can wait for tomorrow; the story is what matters
            progress(f"The day's numbers couldn't be read ({str(e)[:200]})")
    # (not failures: a later run goes on when YouTube takes uploads, or when the free quotas are there)
    waits = (stopped or "").startswith((LIMIT_STOP, QUOTA_WAIT))
    slot = pending or slots.day_slots(day, sched)[0]
    if stopped and stopped != "the autopilot is paused" and not waits:
        raise RuntimeError(f"stopped without {story_name(slot, sched)} scheduled: {stopped}.{notes}")
    if (stopped or "").startswith(LIMIT_STOP):
        notify.run(f"⏳ The run stopped at YouTube's daily upload limit: {stopped[len(LIMIT_STOP) + 2:]}, and a later "
                   f"run carries on then.{notes}")
    elif held and not made:
        notify.run(f"⏸ {story_name(slot, sched, first=True)} isn't scheduled yet.{notes}")
    return result


def _wait(seconds: float) -> None:
    """Sleeps, and stops early when the pause switch goes on: PAUSED every minute, the dashboard's switch (in the
    database) at once and then every PAUSE_CHECK, so that a long wait lets the database sleep."""
    end = _now() + timedelta(seconds=seconds)
    asked = None
    while (left := (end - _now()).total_seconds()) > 0 and not is_true("PAUSED"):
        if asked is None or _now() - asked >= PAUSE_CHECK:
            if db.paused():
                break
            asked = _now()
        time.sleep(min(60.0, left))


def prepare(count: int = 1, progress=_log) -> dict:
    """Writes the story for the next turn in the line no story is for yet (next_to_make), in that turn's form (a Short
    for a Short's turn, the long story for the long story's), `count` times along the line; the autopilot takes each at
    its turn. Nothing is written out of turn: when every turn of the next LINE_AHEAD has its story, nothing is."""
    planned, sched = [], slots.plan()
    for _ in range(count):
        turn = next_to_make(sched=sched)
        if not turn:
            if not planned:
                return {"skipped": f"every turn of the next {LINE_AHEAD.days} days has its story: the next one is "
                                   "written when a turn needs it"}
            break
        form, when = turn["form"], f"{slots.day_word(turn['slot'], sched)} {clock(turn['slot'], sched)}"
        progress(f"Writing the {slots.FORM_WORDS[form]} for {when}, the next turn with no story")
        plan = make_story(progress, form=form)
        video_id = db.insert_video("planned", db.fmt(), plan["brief"]["theme"], None, plan)
        _saved(plan, video_id)
        planned.append({"id": video_id, "theme": plan["brief"]["theme"], "title": plan["metadata"]["title"],
                        "form": form, "turn": slots.iso(turn["slot"])})
        progress(f"Saved story #{video_id}: {plan['metadata']['title']} (the {slots.FORM_WORDS[form]} for {when})")
    return {"planned": planned}


def publish(dry_run: bool = False, video_id: int | None = None, progress=_log, now: bool = False) -> dict:
    """Agents 3 and 4 make and review one waiting story (the oldest ready one, or `video_id`); without dry_run Agent 5
    then uploads it into the next open slot. A real upload reuses an existing film, so what you watched in the dashboard
    is exactly what goes up. `now`: you pressed "Make it now". A film that fails PREVIEW_TRIES times gives the story
    up."""
    row = db.get_video(video_id) if video_id else publisher.choose()
    if not row:
        return {"skipped": "nothing ready to post"}
    if row["status"] != "planned":
        raise RuntimeError(f"Story #{row['id']} is {row['status']}, not waiting")
    if not series.current({**row, "plan": {k: x for k, x in row["plan"].items() if k != "render"}}):
        raise RuntimeError(f"#{row['id']} was made by an earlier version of the channel: it can't be made or posted now")
    if dry_run:
        try:
            if (row["plan"].get("review") or {}).get("held"):  # turned down after the fixes: made again by itself
                row = animator.make_again(row, progress)
            row = reviewer.reviewed(row, progress=progress, now=now)
        except Exception as e:
            if not isinstance(e, animator.Resting) and not llm.down(e):  # (a resting voice says itself when asked
                # again; Gemini down, overloaded or out of its free requests, isn't the story's fault: no try counted)
                failed = db.get_video(row["id"])
                tries = int(failed["plan"].get("preview_failures") or 0) + 1
                db.update_video(row["id"], plan={**failed["plan"], "preview_failed_at": slots.iso(_now()),
                                                 "preview_failures": tries})
                if tries >= PREVIEW_TRIES:
                    db.update_video(row["id"], status="failed",
                                    error=f"Its film couldn't be made in {tries} tries: {str(e)[:300]}")
                    raise RuntimeError(f"Story #{row['id']} given up after {tries} tries: {e}") from e
            raise
        verdict = row["plan"]["review"]
        return {"rendered": str(animator.preview_path(row["id"])), "video_id": row["id"],
                "title": row["plan"]["metadata"]["title"], "length": (row["plan"].get("render") or {}).get("seconds"),
                "passed": verdict["passed"], "held": verdict.get("held", False), "rounds": verdict["round"] + 1}
    if not db.ready(row):
        raise RuntimeError(f"Story #{row['id']} was turned down by the Reviewer: it's being made again")
    sched = slots.plan()
    slot = next_open_slot(MANUAL_LEAD, sched=sched, form=series.form_of(row))
    if not db.claim(row["id"], slots.iso(slot)):
        raise RuntimeError(f"Story #{row['id']} couldn't take the {clock(slot, sched)} slot; try again")
    return publisher.run(db.get_video(row["id"]), slot, sched, progress=progress)


def _whole(row: dict) -> dict | None:
    """The story to post a Reel from: one a list read in part (db.LIGHT) is read again whole (None if it's gone)."""
    return db.get_video(row["id"]) if (row.get("plan") or {}).get(db.LIGHT) else row


def reels(progress=_log, stay: float = 0) -> dict:
    """Agent 5 posts to Instagram every story whose Reel's time has come and is still to post. With `stay` minutes (the
    cloud's Reels workflow), it looks again every minute for Reels coming due meanwhile (a try again, or YouTube a little
    late making the Short public), until none is left to wait for. A Reel whose video is with a run still going is left
    to that run. While Meta refuses Instagram's connection the Reels wait for it (agents/publisher.py): the job doesn't
    stay, and once a day (DOWN_RETELL) it fails, so GitHub emails you."""
    until = _now() + timedelta(minutes=stay)
    posted, left = [], set()
    while True:
        for row in publisher.reels_due():
            if row["id"] not in left and (whole := _whole(row)):
                result = publisher.run_instagram(whole, progress=progress)
                posted.append(result)
                if result.get("waits_for_run") or result.get("waits_for_instagram"):
                    left.add(row["id"])
        coming = [v for v in publisher.reels_coming(slots.iso(until)) if v["id"] not in left]
        if not coming or _now() >= until or paused() or publisher.instagram_down():
            break
        soonest = min(publisher.reel_due_at(v) for v in coming)  # (asleep until then, the database can sleep too)
        due_in = (slots.parse(soonest) - _now()).total_seconds() if soonest else 0.0
        time.sleep(max(1.0, min(max(60.0, due_in), (until - _now()).total_seconds())))
    if down := publisher.tell_down():
        raise RuntimeError(publisher.down_message(down))
    return {"reels": posted} if posted else {"skipped": "no Reel is due"}


def keep_videos(progress=_log) -> dict:
    """At the end of a cloud run: what's still needed of its videos, encrypted for GitHub to keep with the run
    (tools/kept.py): its Reels still waiting (the Reels workflow posts them at their time), its stories made and
    reviewed but not uploaded (YouTube's daily upload limit: the next run uploads them instead of making them again),
    and the narrator's readings of stories it read in part (the next run reads only the rest: agents/animator.py
    _fetch_voice)."""
    run = kept.this_run()
    if not run:
        return {"skipped": "not a run in the cloud: the videos stay on this computer"}
    waiting = [v for v in db.scheduled_videos(days=publisher.REEL_DAYS, parts=("instagram", "form"))
               if (v["plan"].get("instagram") or {}).get("status") == "pending"
               and v["plan"]["instagram"].get("kept_in") == run]
    files = kept.keep([(v["id"], animator.reel_path(v)) for v in waiting])
    progress(f"{len(files)} video{'s' if len(files) != 1 else ''} kept for the Reels still to post")
    waiting_stories = db.planned_videos(limit=1000)
    made = [v for v in waiting_stories if animator.preview_path(v["id"]).exists() and reviewer.passed(v["plan"])
            and (v["plan"].get("render") or {}).get("id")]
    for v in made:
        files += kept.keep_files(publisher.kept_files(v["id"]))
        db.update_video(v["id"], plan={**v["plan"], "kept_video": {"run": run, "render": v["plan"]["render"]["id"],
                                                                    "at": db.now_iso()}})
    if made:
        progress(f"{len(made)} stor{'ies' if len(made) != 1 else 'y'} made but not uploaded yet kept for the next run: "
                 + ", ".join(f"#{v['id']}" for v in made))
    half = []  # (stories read in part before the run ended: their readings kept, so the next run reads only the rest)
    for v in waiting_stories:
        if animator.preview_path(v["id"]).exists():
            continue
        found = sorted(p for p in animator.voice_dir(v["id"]).glob("part_*") if p.suffix in (".wav", ".json", ".steady"))
        parts = sorted({p.stem for p in found if p.suffix == ".json" and p.with_suffix(".wav").exists()})
        if not parts:
            continue
        files += kept.keep_files([(f"voice-{v['id']}-{p.name}", p) for p in found])
        db.update_video(v["id"], plan={**v["plan"], "kept_voice": {"run": run, "parts": parts,
                                                                    "files": [p.name for p in found], "at": db.now_iso()}})
        half.append(f"#{v['id']} ({len(parts)} part{'s' if len(parts) != 1 else ''})")
    if half:
        progress("The narrator's readings of stories not finished kept for the next run: " + ", ".join(half))
    return {"kept": [f.name for f in files]}


def stats(learn: bool = False, progress=_log) -> dict:
    return analyst.run(progress=progress, learn_now=learn)


JOBS = {"morning": morning, "autopilot": autopilot, "prepare": prepare, "publish": publish, "instagram": reels,
        "stats": stats, "keep": keep_videos}


def run_job(name: str, **kwargs) -> dict:
    """Run a job with its start/finish logged to the runs table; failures also go to your phone."""
    started = time.monotonic()
    run_id = db.start_run(f"{name} (preview)" if kwargs.get("dry_run") else name)
    try:
        result = JOBS[name](**kwargs)
    except Exception as e:
        db.finish_run(run_id, False, {"error": str(e)})
        if not isinstance(e, animator.Resting):  # waiting for Gemini's voice isn't a failure
            what = (f"Making the film for story #{kwargs['video_id']}" if kwargs.get("dry_run") and kwargs.get("video_id")
                    else "The autopilot's run" if name == "morning" else f"The {name} job")
            notify.run(f"⚠️ {what} failed: {e}")
        raise
    result["seconds"] = round(time.monotonic() - started, 1)
    db.finish_run(run_id, True, result)
    return result


def main() -> int:
    hide_secrets_in_crashes()   # (the cloud run's log is public: a crash's report is cleaned like every other line)
    background_priority()
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("job", choices=[*JOBS, "due"])
    parser.add_argument("--dry-run", action="store_true", help="publish only: make and review but don't upload")
    parser.add_argument("--newest", action="store_true", help="publish only: the story written last, not the oldest ready one (the cloud test's)")
    parser.add_argument("--now", action="store_true", help="autopilot only: the next open slot, even if not due")
    parser.add_argument("--learn", action="store_true", help="stats only: rewrite the playbook now")
    parser.add_argument("--stay", type=float, default=0, help="instagram only: minutes to keep looking for Reels due")
    args = parser.parse_args()

    if args.job == "due":  # (GitHub's hourly check: the answer for $GITHUB_OUTPUT, the reason in the run's log)
        try:
            found = due()
        except Exception as e:
            print(f"Error: {redact(e)}", file=sys.stderr)
            return 1
        print(f"work={'true' if found['work'] else 'false'}")
        print(f"  {redact(found['why'])}", file=sys.stderr)
        return 0
    if args.job in ("morning", "autopilot", "instagram") and (skipped := _paused()):  # (automatic: the cloud's)
        print(json.dumps(skipped))
        return 0
    kwargs = {"dry_run": True} if args.dry_run and args.job == "publish" else {}
    if args.newest and args.job == "publish" and (queue := db.planned_videos(500)):
        kwargs["video_id"] = queue[-1]["id"]
    if args.job == "autopilot":
        check()
        kwargs = {"force": args.now}
    if args.job == "stats":
        kwargs = {"learn": args.learn}
    if args.job == "instagram":
        kwargs = {"stay": args.stay}
    live = None
    if args.job in LIVE_JOBS:  # (its steps also go to the database as they come: the dashboards' progress bar)
        try:
            live = LiveSteps(args.job)
            kwargs["progress"] = live
        except Exception as e:
            _log(f"(the steps won't show on the dashboard this time: {str(e)[:120]})")
    try:
        result = run_job(args.job, **kwargs)
    except Exception as e:
        print(f"Error: {redact(e)}", file=sys.stderr)
        if live:
            live.end("error", error=redact(str(e))[:300])
        return 1
    if live:
        live.end("done", result={k: result.get(k) for k in ("made", "held", "stopped", "skipped") if k in result})
    print(redact(json.dumps(result, indent=2, ensure_ascii=False, default=str)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
