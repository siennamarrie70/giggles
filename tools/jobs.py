"""
The jobs that run the channel on its posting schedule, by calling the seven agents (agents/) in
order. GitHub Actions runs the morning run every day (.github/workflows/morning.yml); the dashboard
on this computer runs the same jobs while its database is the local one.

  morning    the day's run: from schedule.make_at (07:00), one Short after another for every open
             slot of the posting day, with no pause, until all are scheduled; then one summary to
             your phone and the day's numbers. Then it rests until the next morning.
  autopilot  one slot (the earliest that's due) -> the oldest case ready to go up (or a new one,
             made on the spot from a topic that needs nobody's OK) -> Agent 4 animates it and Agent 5
             reviews it (unless that's done; a video that fails goes back to Agent 4, at most twice,
             then another case takes the slot and the loop has it made again by itself, until it
             passes: unmade()) -> Agent 6 uploads it, scheduled
             to go public on the minute of its slot. A snag is fixed where it happens or the case is
             replaced at once (see "When an agent hits a snag" below)
  prepare    Agents 1, 2 and 3 make a case: the Editor picks it, the Researcher checks the facts, the
             Writer scripts and fact-checks it. News and politics can wait for your OK.
  publish    with --dry-run Agents 4 and 5 make and review a case's video (the dashboard's "Make the
             video" by itself, or "Make it now"); without it Agent 6 then uploads it into the next open slot
  instagram  Agent 6 posts a Short to Instagram as a Reel once its slot has come (Instagram's API
             can't schedule Reels), when Instagram is connected and switched on
  stats      Agent 7: today's numbers and comments; weekly, the playbook and every agent's lessons

When an agent hits a snag, it's fixed where it can be: the Researcher's topic that the sources can't
support, or a script the Writer can't get past the fact-check even rewritten, is swapped for another
topic (TOPIC_TRIES); a video the Reviewer fails goes back to the Animator with notes; a case whose
making or upload fails is tried once more. If that doesn't fix it, the whole process starts again at
once with a new case for the same slot (CASE_TRIES), with no waiting. Only what another case can't
fix makes the run wait: Gemini's voice out, or in the drawn look Cloudflare's drawing (out, or the
day's free drawing used up: until 00:00 UTC, 05:30 in India) (the case waits for it, nothing counted
against it), Gemini out of quota, or YouTube's sign-in.

Every job runs at below-normal priority (common.background_priority), and so do the renders it
starts: on this computer, whatever you're doing comes first and the run just takes a little longer
(measured 2026-10-27 with two renders at once: the worst stall of a normal-priority program fell from
0.31 to 0.21 s, the typical slow moments by about half).

A case that's waiting without its video (made from the Topics page, sent back with "Make it again",
or left from a run) is made and reviewed by the loop on this computer between runs, without anyone
pressing "Make the video" (unmade()): not while Gemini's voice (or Cloudflare's drawing) rests, a failed one again after
PREVIEW_RETRY, and given up after PREVIEW_TRIES failures (a new case takes its place in the run).

A slot is due once its posting day's run has started (make_at that morning; see tools/slots.py)
until an hour after the slot. next_chore() is what the dashboard's loop on this computer asks every
minute: the morning run while the day has open slots, then a waiting case's video, then the day's
numbers. Between runs nothing is made ahead. Reels whose slot has come are posted by the same loop
beside all that (the instagram job as a task of its own), so a long morning run doesn't hold them up. A case still waiting for approval after
cases.approval_expires_days is discarded (news goes stale).

In the cloud (GitHub Actions) there's no such loop, and the machine is wiped after each run: the
morning run posts the Reels whose slot comes while it goes, from a thread beside it (their videos are
on its machine: _reels_beside); at its end `keep` encrypts the videos of the Reels still waiting for
GitHub to keep with the run (tools/kept.py), and the Reels workflow (.github/workflows/reels.yml) runs
`instagram --stay 40` after each slot, which fetches them from there and posts them, staying a while
for retries and for YouTube being a little late making a Short public. While Meta refuses Instagram's
connection (the token or the Meta app, not one video) the Reels wait for it, no try counted, and a
Reels run fails once a day so GitHub emails you (agents/publisher.py).

PAUSED=true (in .env or GitHub's variables), or the dashboard's pause switch (kept in the database),
stops the morning run and every automatic job. Cases, videos and uploads you start yourself still
work. Each job reports its steps through `progress` (stderr by default; the dashboard shows them
live).

Usage:
    python tools/jobs.py morning               # the day's run (what GitHub runs at 06:55)
    python tools/jobs.py autopilot [--now]     # one Short; --now: the next open slot, even if it isn't due
    python tools/jobs.py prepare
    python tools/jobs.py publish [--dry-run]   # --dry-run makes and reviews but doesn't upload
    python tools/jobs.py instagram [--stay 40]  # posts the Reels whose slot has come (--stay: and those due soon)
    python tools/jobs.py keep                  # (the cloud, after a run) the waiting Reels' videos, kept
    python tools/jobs.py stats [--learn]
"""

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the agents/ package

import db  # noqa: E402
import kept  # noqa: E402
import notify  # noqa: E402
import slots  # noqa: E402
import trends_fetch  # noqa: E402
import youtube_auth  # noqa: E402
import youtube_upload  # noqa: E402
from agents import analyst, animator, editor, publisher, researcher, reviewer, writer  # noqa: E402
from common import background_priority, is_true, load_config, redact, tmp_path  # noqa: E402

LATE_GRACE = timedelta(minutes=60)     # a slot stays due this long after it (the Short then goes live at once)
STALE_CLAIM = timedelta(minutes=15)    # "making" for longer means the run was cut off
MANUAL_LEAD = timedelta(minutes=10)    # an upload you start yourself takes a slot at least this far ahead
TRENDS_FRESH = timedelta(hours=6)      # how long fetched trends are reused (worldwide is ~190 requests)
STATS_EVERY = timedelta(hours=20)      # the Analyst reads the numbers about once a day
STATS_RETRY = timedelta(hours=1)       # ...and after a failed read, tries again this long after
TOPIC_TRIES = 3                        # topics the Editor may pick before a case is given up
CASE_TRIES = 3                         # cases tried, one after another, for one slot before the run waits
PREVIEW_RETRY = timedelta(minutes=30)  # a waiting case whose video failed is made again this long after
PREVIEW_TRIES = 3                      # ...and given up after this many failures
MORNING_WAIT = timedelta(minutes=30)   # a run started this early waits for make_at (GitHub starts it at 06:55)
RETRY_FIRST = timedelta(minutes=2)     # after a Short fails: 2, 4, 8, 16 minutes before the next try...
RETRY_MOST = timedelta(minutes=20)     # ...up to 20, so Gemini's free per-minute limits recover
UPLOAD_WAIT = timedelta(hours=1)       # YouTube's daily upload limit reached: its case tried again this much later (the
                                       # limit seemed to count the last 24 hours' uploads, deleted and stopped ones too)
MAX_TRIES = 25                         # Shorts tried in one run before it stops (something's wrong every time)
RUN_LIMIT = timedelta(hours=5, minutes=40)  # a run stops before GitHub's 6-hour job limit
REELS_EVERY = 60                       # seconds: how often the cloud's morning run looks for Reels due (_reels_beside)
REELS_FINISH = timedelta(minutes=10)   # ...and how long it waits, at its end, for a Reel being posted
clock = slots.clock


def _log(message: str) -> None:
    print(f"  {redact(message)}", file=sys.stderr, flush=True)  # (the cloud run's log is public on GitHub)


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
    """Each slot from start to end, with the Short holding it and where it stands: posted, scheduled, making,
    late (its time has come), due (its day's run has started), open (made in a later run) or missed."""
    now = now or _now()
    holders = db.slot_holders(slots.iso(start - sched["every"]), slots.iso(end + sched["every"]))
    board = []
    for slot in slots.between(start, end, sched):
        key = slots.iso(slot)
        # Rows from before slots existed have only a publish time: they hold the nearest slot.
        video = next((v for v in holders if v["slot"] == key or not v["slot"] and v["publish_at"]
                      and abs(slots.parse(v["publish_at"]) - slot) < sched["every"] / 2), None)
        if video:
            live = video["status"] == "scheduled" and slots.parse(video["publish_at"]) <= now
            state = "posted" if live else video["status"]
        elif slot < now - LATE_GRACE:
            state = "missed"
        else:
            started = now >= slots.run_starts(slots.posting_day(slot, sched), sched)
            state = "late" if slot <= now else "due" if started else "open"
        board.append({"slot": slot, "state": state, "video": video})
    return board


def due_slot(now: datetime | None = None, sched: dict | None = None) -> datetime | None:
    """The earliest slot that needs a Short now, if any: an open slot of a posting day whose run has started."""
    now, sched = now or _now(), sched or slots.plan()
    return next((s["slot"] for s in slot_board(now - LATE_GRACE, now + timedelta(days=1), sched, now)
                 if s["state"] in ("late", "due")), None)


def next_open_slot(lead: timedelta, now: datetime | None = None, sched: dict | None = None) -> datetime:
    """The earliest slot at least `lead` from now that no Short holds."""
    now, sched = now or _now(), sched or slots.plan()
    found = next((s["slot"] for s in slot_board(now + lead, now + timedelta(days=8), sched, now)
                  if s["state"] in ("due", "open")), None)
    if not found:
        raise RuntimeError("every slot of the next week is taken")
    return found


def expire_approvals(progress=_log) -> list[int]:
    """Cases that waited for your OK longer than cases.approval_expires_days: discarded (news goes stale)."""
    days = int(load_config()["cases"].get("approval_expires_days", 2))
    cutoff = _now() - timedelta(days=days)
    expired = []
    for v in db.planned_videos():
        if v["plan"].get("approval") == "waiting" and slots.parse(v["created_at"]) < cutoff:
            db.update_video(v["id"], status="discarded", error=f"Waited more than {days} days for approval")
            expired.append(v["id"])
            progress(f"Case #{v['id']} waited too long for your OK and was discarded")
    if expired:
        notify.run(f"\U0001F5D1 {len(expired)} case(s) waited more than {days} days for your OK and were discarded.")
    return expired


def check(progress=_log) -> datetime | None:
    """The cheap part of each check: check in, free Shorts whose run was cut off, drop stale approvals,
    and say whether a slot is due."""
    db.beat("autopilot")
    for row in db.release_stale(slots.iso(_now() - STALE_CLAIM)):
        progress(f"Short #{row['id']} was interrupted while being made; it's now {row['status']}")
    publisher.auto_approve(progress)  # with approvals off, nothing waits for anyone
    expire_approvals(progress)
    publisher.expire_reels(progress)
    return due_slot()


def tick(progress=_log) -> dict:
    """What Vercel Cron calls every hour: a full autopilot run only when a slot is due."""
    if paused := _paused():
        return paused
    if not check(progress):
        return {"skipped": "no slot is due yet"}
    return run_job("autopilot", progress=progress)


def next_chore() -> tuple[str, dict] | None:
    """What the loop on this computer should do now, most urgent first, or None. Between morning runs it rests:
    nothing is made ahead. (Reels aren't a chore: the loop posts them at their slot beside whatever is going, since
    a morning run can take hours, or wait hours for Cloudflare.)"""
    if check():
        return "morning", {}
    if waiting := unmade():
        return "publish", {"dry_run": True, "video_id": waiting["id"]}
    if stats_due():
        return "stats", {}
    return None


def stats_due() -> bool:
    """Is it time for the Analyst to read the numbers: STATS_EVERY since it last did, not within STATS_RETRY of a
    failed or unfinished try, and something published to read. (It's asked beside everything else, not only when the
    rest is done: a morning run that never finished cleanly kept it from reading anything from 2026-10-26 to 28.)"""
    if not db.published_videos(days=60):
        return False
    tried = db.last_run("analyst", ok=None)
    if tried and not tried["ok"] and _now() - slots.parse(tried["started_at"]) < STATS_RETRY:
        return False
    read = db.last_run("analyst")
    return not read or _now() - slots.parse(read["started_at"]) >= STATS_EVERY


def unmade() -> dict | None:
    """The oldest waiting case whose video isn't made, or isn't reviewed as it is now: the Animator makes it without
    anyone pressing "Make the video". None while Gemini's voice (or Cloudflare's drawing, with look.when_out: wait)
    rests; one the Reviewer turned down after the fixes is made again by itself when its remake_at comes (until it
    passes: nothing waits for you, your call on 2026-10-27); one that failed is made again PREVIEW_RETRY later."""
    if animator.resting():
        return None
    return next((v for v in db.planned_videos() if to_make(v)), None)


def to_make(v: dict) -> bool:
    """Is this waiting case's video for the loop to make now (unmade())?"""
    plan = v["plan"]
    review = plan.get("review") or {}
    if not plan.get("script"):
        return False
    if review.get("held"):  # turned down after the fixes: made again by itself when its time comes
        return (review.get("remake_at") or "") <= db.now_iso()
    made = (animator.preview_path(v["id"]).exists() and (plan.get("render") or {}).get("id")
            and not (plan.get("voice") or {}).get("backup"))
    if made and reviewer.current(plan):
        return False
    failed = plan.get("preview_failed_at")
    return not (failed and _now() - slots.parse(failed) < PREVIEW_RETRY)


def _must_wait(error: BaseException | None) -> bool:
    """Is it something no other case would get past: Gemini's voice or Cloudflare's drawing out, Gemini out of quota or
    refusing the key, YouTube's sign-in or its daily upload limit? Then the run waits instead of throwing away good
    cases (on 2026-10-27 the upload limit threw away 16 cases made one after another: #49-#64)."""
    while error:
        if isinstance(error, (animator.Resting, youtube_auth.YouTubeAuthError, youtube_upload.UploadLimit)):
            return True
        if any(sign in str(error) for sign in ("All Gemini models failed", "Gemini rejected the API key")):
            return True
        error = error.__cause__ or error.__context__
    return False


# --- making cases -----------------------------------------------------------

def trend_signals(cfg: dict, days_ahead: int | None = None, refresh: bool = False, cached_only: bool = False) -> dict:
    """Today's trend signals for the Editor and the dashboard. What comes from the internet is kept for
    TRENDS_FRESH: trends move slowly, and Google's feed refuses to be asked by every country for every
    Short. cached_only never goes online: the last fetch however old (for the dashboard to show at once).
    The calendar part is worked out fresh each time."""
    region = str(cfg["trends"]["region"]).upper()
    if cached_only:
        online = db.fresh_note("trends", timedelta(days=3650)) or {}
        if online.get("region") != region:
            online = {"region": region, "fetched_at": None, "google_trends": [], "youtube_popular": [], "errors": []}
    else:
        online = None if refresh else db.fresh_note("trends", TRENDS_FRESH)
        if not online or online.get("region") != region:
            online = trends_fetch.online(region)
            if online["google_trends"] or online["youtube_popular"]:  # an empty fetch is retried next time
                db.keep_note("trends", online)
    today = _now().date()
    days = cfg["trends"]["calendar_days_ahead"] if days_ahead is None else days_ahead
    return {"date": today.isoformat(), "weekday": today.strftime("%A"), **trends_fetch.calendar_signals(today, days),
            **online}


def research_folder(topic: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40] or "case"
    return tmp_path("research", f"{_now():%Y%m%d-%H%M%S}-{slug}", "x").parent


def _make_case(progress, ready_now: bool = False) -> dict:
    """Agent 1 picks the case, Agent 2 researches it, Agent 3 writes it: a plan ready for the queue. A
    topic the sources can't support, or that the Writer can't script past the fact-check (it rewrites
    once itself), is swapped for another one."""
    avoid, why = [], []
    for attempt in range(TOPIC_TRIES):
        brief = editor.run(progress=progress, avoid=avoid, ready_now=ready_now)["brief"]
        try:
            pack = researcher.run(brief, research_folder(brief["topic"]), progress=progress)["pack"]
            written = writer.run(brief, pack, progress=progress)
        except Exception as e:
            if _must_wait(e):
                raise
            progress(f"Snag with “{brief['topic']}” ({str(e)[:160]})"
                     + ("; choosing another case" if attempt + 1 < TOPIC_TRIES else ""))
            avoid.append(brief["topic"])
            why.append(f"{brief['topic']}: {str(e)[:120]}")
            continue
        return {"brief": brief, "research": pack, "script": written["script"], "metadata": written["metadata"],
                "approval": "waiting" if brief["needs_approval"] else None}
    raise RuntimeError(f"no case could be made ({'; '.join(why)})")


def _saved(plan: dict, video_id: int, progress) -> None:
    """After a case is saved: mark the request or comment it answers, and ask for approval if needed."""
    brief = plan["brief"]
    if brief.get("request_id"):
        db.set_topic(brief["request_id"], "used", video_id=video_id)
    if brief.get("comment_id"):
        db.use_comment(brief["comment_id"], video_id)
    if plan["approval"] == "waiting":
        progress(f"Case #{video_id} waits for your OK in the Studio")
        notify.run(f"\U0001F4F0 A case waits for your OK (news or politics): {plan['metadata']['title']}\n"
                   "Watch it in the dashboard's Studio, then approve or discard it.")


def autopilot(force: bool = False, slot: datetime | None = None, progress=_log) -> dict:
    """Makes and uploads the Short for `slot`, or the earliest slot that's due. With force, takes the
    next open slot even if it isn't due yet (the dashboard's "make it now" button). A case that fails is
    tried once more (it goes back to the queue), then another case takes its place, up to CASE_TRIES,
    with no waiting; what no other case would fix (_must_wait) is raised at once."""
    sched = slots.plan()
    now = _now()
    slot = slot or due_slot(now, sched) or (next_open_slot(publisher.GO_LIVE_MARGIN, now, sched) if force else None)
    if not slot:
        return {"skipped": "no slot is due yet"}
    when = clock(slot, sched)
    snags = []
    for attempt in range(CASE_TRIES):
        try:
            return _fill(slot, sched, when, progress)
        except Exception as e:
            if _must_wait(e):
                raise
            snags.append(str(e)[:200])
            if attempt + 1 < CASE_TRIES:
                progress(f"Snag: {str(e)[:200]}. Starting again for the {when} slot")
    raise RuntimeError(f"Couldn't make the {when} Short in {CASE_TRIES} tries: " + " | ".join(snags))


def _fill(slot: datetime, sched: dict, when: str, progress) -> dict:
    """One try at the slot: the oldest case ready to go up (a failed try puts it back once), or a new one made on
    the spot; then the Publisher (the Animator and the Reviewer first)."""
    row = publisher.choose()
    if row:
        if not db.claim(row["id"], slots.iso(slot)):
            return {"skipped": f"another run is already making the {when} Short"}
        progress(f"Using case #{row['id']} for the {when} slot")
        row = db.get_video(row["id"])
    else:
        video_id = db.insert_video("making", db.FORMAT, None, None, {}, slot=slots.iso(slot))
        if video_id is None:
            return {"skipped": f"another run is already making the {when} Short"}
        progress(f"No case ready: making one for the {when} slot")
        try:
            plan = _make_case(progress, ready_now=True)
        except Exception as e:
            db.update_video(video_id, status="skipped", error=str(e)[:500])
            raise RuntimeError(f"Couldn't make the {when} Short: {e}") from e
        if plan["approval"] == "waiting":  # it turned out to need your OK: it waits, the slot stays empty
            db.update_video(video_id, status="planned", slot=None, claimed_at=None, theme=plan["brief"]["topic"],
                            trend=plan["brief"]["trend"] or None, plan=plan)
            _saved(plan, video_id, progress)
            return {"skipped": f"the case made for {when} needs your OK first", "video_id": video_id}
        db.update_video(video_id, theme=plan["brief"]["topic"], trend=plan["brief"]["trend"] or None, plan=plan)
        _saved(plan, video_id, progress)
        row = db.get_video(video_id)
    return publisher.run(row, slot, sched, progress=progress)


def _upload_limit(error: BaseException | None) -> bool:
    """Is it YouTube's daily upload limit? Then no Short goes up for a while, whichever case it is."""
    while error:
        if isinstance(error, youtube_upload.UploadLimit):
            return True
        error = error.__cause__ or error.__context__
    return False


def _signed_out(error: BaseException | None) -> bool:
    """Is it YouTube's sign-in (revoked or expired)? Then every Short would fail the same way."""
    while error:
        if isinstance(error, youtube_auth.YouTubeAuthError):
            return True
        error = error.__cause__ or error.__context__
    return False


def day_count(day, sched: dict) -> tuple[int, int]:
    """How many of a posting day's slots have their Short scheduled (or posted), and how many there are."""
    times = slots.day_slots(day, sched)
    board = slot_board(times[0], times[-1], sched)
    return sum(1 for s in board if s["state"] in ("scheduled", "posted")), len(board)


def morning(progress=_log) -> dict:
    """The day's run: from schedule.make_at, a Short for every open slot of the posting day, one after another with
    no pause, until all are scheduled; then one summary to your phone and the day's numbers. A Short that fails
    doesn't stop it: the next try waits RETRY_FIRST, twice as long after each failure in a row, up to RETRY_MOST.
    It stops early (an error, so GitHub marks the run failed and emails you) when YouTube's sign-in is broken,
    after MAX_TRIES Shorts, or at RUN_LIMIT; the pause switch stops it quietly. In the cloud the Reels whose slot
    comes meanwhile are posted beside it (_reels_beside)."""
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


def _reels_beside(stop: threading.Event, progress) -> None:
    """In the cloud, while the morning run goes: every REELS_EVERY seconds, the Reels whose slot has come and whose
    video is on this machine (made by this run), posted. The others are the Reels workflow's (tools/kept.py)."""
    while not stop.wait(REELS_EVERY):
        try:
            if paused():
                continue
            for row in publisher.reels_due():
                if stop.is_set():
                    break
                if animator.preview_path(row["id"]).exists():
                    publisher.run_instagram(row, progress=progress)
        except Exception as e:  # (a Reel's own failure is handled where it's posted: this is the database or YouTube)
            progress(f"Reels: {str(e)[:200]}")


def _morning(progress) -> dict:
    """The morning run itself (morning)."""
    sched = slots.plan()
    started = _now()
    start = slots.run_starts(started.astimezone(sched["tz"]).date(), sched)
    if started < start <= started + MORNING_WAIT:  # GitHub starts it at 06:55
        progress(f"The run starts at {clock(start, sched)}; waiting until then")
        time.sleep((start - started).total_seconds())
    if skipped := _paused():
        return skipped
    if not youtube_auth.is_configured():
        raise RuntimeError("YouTube isn't connected: connect it on the dashboard's YouTube page")
    made, held, tries, failures, day, stopped = [], [], 0, 0, None, None
    while True:
        if paused():
            stopped = "the autopilot is paused"
            break
        slot = check(progress)
        if not slot:
            break
        day = day or slots.posting_day(slot, sched)
        if tries >= MAX_TRIES:
            stopped = f"{MAX_TRIES} Shorts were tried and the slots still aren't filled"
            break
        if _now() - started >= RUN_LIMIT:
            stopped = "it ran out of time"
            break
        tries += 1
        progress(f"The {clock(slot, sched)} Short")
        try:
            result = autopilot(slot=slot, progress=progress)
        except animator.Resting as e:  # the case waits for Gemini's voice or Cloudflare's drawing: nothing counted
            tries -= 1
            rest = animator.resting()
            wait = max(60.0, (slots.parse(rest["until"]) - _now()).total_seconds()) if rest else 60.0
            progress(f"{str(e)[:200]}. The {clock(slot, sched)} Short waits ({wait / 60:.0f} minutes)")
            _wait(wait)
            continue
        except Exception as e:
            if _signed_out(e):
                stopped = f"YouTube's sign-in needs renewing ({e})"
                break
            if _upload_limit(e):  # YouTube's daily upload limit: the case stays queued, nothing new is made meanwhile
                tries -= 1
                progress(f"YouTube takes no more uploads for now (the channel's daily upload limit). The "
                         f"{clock(slot, sched)} Short waits {UPLOAD_WAIT.seconds // 60} minutes, its case kept")
                _wait(UPLOAD_WAIT.total_seconds())
                continue
            failures += 1
            wait = min(RETRY_MOST, RETRY_FIRST * 2 ** min(failures - 1, 8))
            progress(f"The {clock(slot, sched)} Short failed ({str(e)[:200]}); the next try in {wait.seconds // 60} "
                     "minutes")
            _wait(wait.total_seconds())
            continue
        failures = 0
        if result.get("youtube_id"):
            made.append(result)
        elif result.get("held"):
            held.append(result["video_id"])
    if not day:  # every slot was taken already (a catch-up run after a full morning)
        if stats_due():  # (in the cloud the runs are the Analyst's only chance to read the numbers)
            try:
                stats(progress=progress)
            except Exception as e:
                progress(f"The day's numbers couldn't be read ({str(e)[:200]})")
        return {"skipped": "every open slot of the day has its Short"}
    done, total = day_count(day, sched)
    times = slots.day_slots(day, sched)
    hours = f"{clock(times[0], sched)}–{clock(times[-1], sched)}"
    missed = sum(1 for s in slot_board(times[0], times[-1], sched) if s["state"] == "missed")
    notes = (f" {missed} slot{'s' if missed > 1 else ''} had passed before it ran." if missed else "") + (
        f" The Reviewer turned down {len(held)} after the Animator's fixes: each is made again by itself until it passes."
        if held else "")
    result = {"made": len(made), "held": held, "tries": tries, "scheduled": done, "slots": total, "missed": missed,
              "stopped": stopped}
    if stopped != "the autopilot is paused" and stats_due():  # (first: also after a run that stopped early)
        try:
            stats(progress=progress)
        except Exception as e:  # the numbers can wait for tomorrow; the Shorts are what matter
            progress(f"The day's numbers couldn't be read ({str(e)[:200]})")
    if stopped and stopped != "the autopilot is paused":
        raise RuntimeError(f"stopped with {done} of {total} Shorts of the day scheduled: {stopped}.{notes}")
    if made or held:
        if stopped:
            notify.run(f"⏸ Today's run is paused with {done} of {total} Shorts scheduled ({hours}).{notes}")
        else:
            notify.run(f"☀️ Today's run is done: {done} of {total} Shorts scheduled ({hours}).{notes}")
    return result


def _wait(seconds: float) -> None:
    """Sleeps, a minute at a time, and stops early when the pause switch goes on."""
    end = _now() + timedelta(seconds=seconds)
    while (left := (end - _now()).total_seconds()) > 0 and not paused():
        time.sleep(min(60.0, left))


def prepare(count: int = 1, progress=_log) -> dict:
    """Makes `count` cases, which the autopilot picks up oldest first."""
    planned = []
    for _ in range(count):
        plan = _make_case(progress)
        video_id = db.insert_video("planned", db.FORMAT, plan["brief"]["topic"], plan["brief"]["trend"] or None, plan)
        _saved(plan, video_id, progress)
        planned.append({"id": video_id, "topic": plan["brief"]["topic"], "title": plan["metadata"]["title"],
                        "waits_for_approval": plan["approval"] == "waiting"})
        progress(f"Saved case #{video_id}: {plan['metadata']['title']}")
    return {"planned": planned}


def publish(dry_run: bool = False, video_id: int | None = None, progress=_log, now: bool = False) -> dict:
    """Agents 4 and 5 make and review one queued case (the oldest ready one, or `video_id`); without dry_run Agent 6
    then uploads it into the next open slot. A real upload reuses an existing preview, so what you
    watched in the dashboard is exactly what goes up. `now` (you pressed "Make the video"): Gemini's voice is asked
    even while it rests. A preview that fails PREVIEW_TRIES times gives the case up (a new case takes its place);
    Gemini's voice being out isn't counted."""
    row = db.get_video(video_id) if video_id else publisher.choose()
    if not row:
        return {"skipped": "nothing ready to post"}
    if row["status"] != "planned":
        raise RuntimeError(f"Short #{row['id']} is {row['status']}, not planned")
    if dry_run:
        try:
            if (row["plan"].get("review") or {}).get("held"):  # turned down after the fixes: made again by itself
                row = animator.make_again(row, progress)
            row = reviewer.reviewed(row, progress=progress, now=now)
        except Exception as e:
            if not isinstance(e, animator.Resting):  # (a resting voice or drawing says itself when it's asked again)
                failed = db.get_video(row["id"])
                tries = int(failed["plan"].get("preview_failures") or 0) + 1
                db.update_video(row["id"], plan={**failed["plan"], "preview_failed_at": slots.iso(_now()),
                                                 "preview_failures": tries})
                if tries >= PREVIEW_TRIES:
                    db.update_video(row["id"], status="failed",
                                    error=f"Its video couldn't be made in {tries} tries: {str(e)[:300]}")
                    raise RuntimeError(f"Short #{row['id']} given up after {tries} tries (a new case takes its place): "
                                       f"{e}") from e
            raise
        verdict = row["plan"]["review"]
        return {"rendered": str(animator.preview_path(row["id"])), "video_id": row["id"],
                "title": row["plan"]["metadata"]["title"], "length": (row["plan"].get("render") or {}).get("seconds"),
                "passed": verdict["passed"], "held": verdict.get("held", False), "rounds": verdict["round"] + 1}
    if row["format"] == db.FORMAT and not db.ready(row):
        raise RuntimeError(f"Short #{row['id']} waits for your OK: approve it in the Studio first")

    sched = slots.plan()
    slot = next_open_slot(MANUAL_LEAD, sched=sched)
    if not db.claim(row["id"], slots.iso(slot)):
        raise RuntimeError(f"Short #{row['id']} couldn't take the {clock(slot, sched)} slot; try again")
    return publisher.run(db.get_video(row["id"]), slot, sched, progress=progress)


def reels(progress=_log, stay: float = 0) -> dict:
    """Agent 6 posts to Instagram every Short whose slot has come and whose Reel is still to post. With `stay`
    minutes (the cloud's Reels workflow), it looks again every minute for Reels coming due meanwhile (a try again,
    or YouTube a little late making the Short public), until none is left to wait for. A Reel whose video is with a
    run still going is left to that run. While Meta refuses Instagram's connection the Reels wait for it
    (agents/publisher.py): the job doesn't stay, and once a day (DOWN_RETELL) it fails, so GitHub emails you."""
    until = _now() + timedelta(minutes=stay)
    posted, left = [], set()
    while True:
        for row in publisher.reels_due():
            if row["id"] not in left:
                result = publisher.run_instagram(row, progress=progress)
                posted.append(result)
                if result.get("waits_for_run") or result.get("waits_for_instagram"):
                    left.add(row["id"])
        coming = [v for v in publisher.reels_coming(slots.iso(until)) if v["id"] not in left]
        if not coming or _now() >= until or paused() or publisher.instagram_down():
            break
        time.sleep(60)
    if down := publisher.tell_down():
        raise RuntimeError(publisher.down_message(down))
    return {"reels": posted} if posted else {"skipped": "no Reel is due"}


def keep_reels(progress=_log) -> dict:
    """At the end of a cloud run: the videos of its Reels still waiting, encrypted for GitHub to keep with the run
    (tools/kept.py), so the Reels workflow can post them at their slots."""
    run = kept.this_run()
    if not run:
        return {"skipped": "not a run in the cloud: the videos stay on this computer"}
    waiting = [v for v in db.scheduled_videos(days=publisher.REEL_DAYS)
               if (v["plan"].get("instagram") or {}).get("status") == "pending"
               and v["plan"]["instagram"].get("kept_in") == run]
    files = kept.keep([(v["id"], animator.preview_path(v["id"])) for v in waiting])
    progress(f"{len(files)} video{'s' if len(files) != 1 else ''} kept for the Reels still to post")
    return {"kept": [f.name for f in files]}


def stats(learn: bool = False, progress=_log) -> dict:
    return analyst.run(progress=progress, learn_now=learn)


JOBS = {"morning": morning, "autopilot": autopilot, "prepare": prepare, "publish": publish, "instagram": reels,
        "stats": stats, "keep": keep_reels}


def run_job(name: str, **kwargs) -> dict:
    """Run a job with its start/finish logged to the runs table; failures also go to your phone."""
    started = time.monotonic()
    run_id = db.start_run(f"{name} (preview)" if kwargs.get("dry_run") else name)
    try:
        result = JOBS[name](**kwargs)
    except Exception as e:
        db.finish_run(run_id, False, {"error": str(e)})
        if not isinstance(e, animator.Resting):  # waiting for Gemini's voice or Cloudflare's drawing isn't a failure
            what = (f"Making the video for Short #{kwargs['video_id']}" if kwargs.get("dry_run") and kwargs.get("video_id")
                    else "Today's morning run" if name == "morning" else f"The {name} job")
            notify.run(f"⚠️ {what} failed: {e}")
        raise
    result["seconds"] = round(time.monotonic() - started, 1)
    db.finish_run(run_id, True, result)
    return result


def main() -> int:
    background_priority()
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("job", choices=list(JOBS))
    parser.add_argument("--dry-run", action="store_true", help="publish only: render but don't upload")
    parser.add_argument("--now", action="store_true", help="autopilot only: the next open slot, even if not due")
    parser.add_argument("--learn", action="store_true", help="stats only: rewrite the playbook now")
    parser.add_argument("--stay", type=float, default=0, help="instagram only: minutes to keep looking for Reels due")
    args = parser.parse_args()

    if args.job in ("morning", "autopilot", "instagram") and (skipped := _paused()):  # (automatic: the cloud's)
        print(json.dumps(skipped))
        return 0
    kwargs = {"dry_run": True} if args.dry_run and args.job == "publish" else {}
    if args.job == "autopilot":
        check()
        kwargs = {"force": args.now}
    if args.job == "stats":
        kwargs = {"learn": args.learn}
    if args.job == "instagram":
        kwargs = {"stay": args.stay}
    try:
        result = run_job(args.job, **kwargs)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
