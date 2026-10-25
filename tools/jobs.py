"""
The jobs that run the channel on its posting schedule, by calling the five agents (agents/) in
order. The dashboard on this computer runs them; Vercel Cron can call them through app.py.

  autopilot  the earliest posting slot that's due -> the oldest written episode (or a new one:
             Agent 1 casts, Agent 2 writes) -> Agent 3 animates it (unless its preview exists) ->
             Agent 4 uploads it, scheduled to go public on the minute of its slot
  prepare    Agents 1 and 2 write an episode into the queue (the autopilot uses those first)
  publish    with --dry-run Agent 3 renders a queued episode's preview; without it Agents 3 and 4
             upload it into the next open slot
  stats      Agent 5: today's numbers for published Shorts; weekly, the playbook

next_chore() is what the dashboard's loop on this computer asks every minute: a due slot first,
then keeping `episodes.queue` episodes written ahead, then rendering their previews, then the
day's numbers. The slots come from `schedule` in config/channel.yaml (see tools/slots.py). A slot
is due from 150 minutes before it until an hour after, so a missed one still goes out late.

Setting PAUSED=true stops the autopilot and every automatic job (the kill switch). Writing,
previews and uploads you start yourself still work. Each job reports its steps through `progress`
(stderr by default; the dashboard shows them live).

Usage:
    python tools/jobs.py autopilot [--now]     # --now: the next open slot, even if it isn't due yet
    python tools/jobs.py prepare
    python tools/jobs.py publish [--dry-run]   # --dry-run renders but doesn't upload
    python tools/jobs.py stats [--learn]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the agents/ package

import db  # noqa: E402
import notify  # noqa: E402
import slots  # noqa: E402
import trends_fetch  # noqa: E402
from agents import analyst, animator, casting, publisher, writer  # noqa: E402
from common import is_true, load_config  # noqa: E402

MAKE_AHEAD = timedelta(minutes=150)    # a slot is due this long before its time
LATE_GRACE = timedelta(minutes=60)     # ...and stays due this long after it (the Short then goes live at once)
STALE_CLAIM = timedelta(minutes=15)    # "making" for longer means the run was cut off
MANUAL_LEAD = timedelta(minutes=10)    # an upload you start yourself takes a slot at least this far ahead
TRENDS_FRESH = timedelta(hours=6)      # how long fetched trends are reused (worldwide is ~190 requests)
STATS_EVERY = timedelta(hours=20)      # the Analyst reads the numbers about once a day
clock = slots.clock


def _log(message: str) -> None:
    print(f"  {message}", file=sys.stderr, flush=True)


def _paused() -> dict | None:
    return {"skipped": "PAUSED is set"} if is_true("PAUSED") else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- slots ----------------------------------------------------------------

def slot_board(start: datetime, end: datetime, sched: dict, now: datetime | None = None) -> list[dict]:
    """Each slot from start to end, with the Short holding it and where it stands:
    posted, scheduled, making, late (due now), due (being made soon), open or missed."""
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
            state = "late" if slot <= now else "due" if slot - now <= MAKE_AHEAD else "open"
        board.append({"slot": slot, "state": state, "video": video})
    return board


def due_slot(now: datetime | None = None, sched: dict | None = None) -> datetime | None:
    """The earliest slot that needs a Short now, if any."""
    now, sched = now or _now(), sched or slots.plan()
    return next((s["slot"] for s in slot_board(now - LATE_GRACE, now + MAKE_AHEAD, sched, now)
                 if s["state"] in ("late", "due")), None)


def next_open_slot(lead: timedelta, now: datetime | None = None, sched: dict | None = None) -> datetime:
    """The earliest slot at least `lead` from now that no Short holds."""
    now, sched = now or _now(), sched or slots.plan()
    found = next((s["slot"] for s in slot_board(now + lead, now + timedelta(days=8), sched, now)
                  if s["state"] in ("due", "open")), None)
    if not found:
        raise RuntimeError("every slot of the next week is taken")
    return found


def check(progress=_log) -> datetime | None:
    """The cheap part of each check: check in, free Shorts whose run was cut off, and say whether a
    slot is due."""
    db.beat("autopilot")
    for row in db.release_stale(slots.iso(_now() - STALE_CLAIM)):
        progress(f"Short #{row['id']} was interrupted while being made; it's now {row['status']}")
    return due_slot()


def tick(progress=_log) -> dict:
    """What Vercel Cron calls every hour: a full autopilot run only when a slot is due."""
    if paused := _paused():
        return paused
    if not check(progress):
        return {"skipped": "no slot is due yet"}
    return run_job("autopilot", progress=progress)


def next_chore() -> tuple[str, dict] | None:
    """What the loop on this computer should do now, most urgent first, or None."""
    if check():
        return "autopilot", {}
    cfg = load_config()
    planned = db.planned_videos()
    if len(planned) < int(cfg["episodes"].get("queue", 2)):
        return "prepare", {"count": 1}
    waiting = next((v for v in planned if not animator.preview_path(v["id"]).exists()), None)
    if waiting:
        return "publish", {"dry_run": True, "video_id": waiting["id"]}
    last = db.last_run("analyst")
    if db.published_videos(days=60) and (not last or _now() - slots.parse(last["started_at"]) >= STATS_EVERY):
        return "stats", {}
    return None


# --- making Shorts --------------------------------------------------------

def trend_signals(cfg: dict, days_ahead: int | None = None, refresh: bool = False, cached_only: bool = False) -> dict:
    """Today's trend signals for the Writer and the dashboard. What comes from the internet is kept for
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


def _write_episode(cfg: dict, progress) -> dict:
    """Agent 1 casts, Agent 2 writes: a plan ready for the queue."""
    progress("Reading today's trends" + (" from every country" if str(cfg["trends"]["region"]).upper() == "ALL" else ""))
    trends = trend_signals(cfg)
    cast = casting.run(progress=progress)
    written = writer.run(cast["cast"], cast["setting"], cast["premise_hint"], trends, progress=progress)
    return {"setting": cast["setting"], "seed": cast["seed"], "premise_hint": cast["premise_hint"],
            "cast": cast["cast"], "script": written["script"], "metadata": written["metadata"]}


def autopilot(force: bool = False, progress=_log) -> dict:
    """Makes and uploads the Short for the earliest slot that's due. With force, takes the
    next open slot even if it isn't due yet (the dashboard's "make it now" button)."""
    cfg, sched = load_config(), slots.plan()
    now = _now()
    slot = due_slot(now, sched) or (next_open_slot(publisher.GO_LIVE_MARGIN, now, sched) if force else None)
    if not slot:
        return {"skipped": "no slot is due yet"}
    when = clock(slot, sched)

    row = publisher.choose()
    if row:
        if not db.claim(row["id"], slots.iso(slot)):
            return {"skipped": f"another run is already making the {when} Short"}
        progress(f"Using episode #{row['id']} for the {when} slot")
        row = db.get_video(row["id"])
    else:
        video_id = db.insert_video("making", "sketch", None, None, {}, slot=slots.iso(slot))
        if video_id is None:
            return {"skipped": f"another run is already making the {when} Short"}
        progress(f"No episode written yet: writing one for the {when} slot")
        try:
            plan = _write_episode(cfg, progress)
        except Exception as e:
            db.update_video(video_id, status="skipped", error=str(e)[:500])
            raise RuntimeError(f"Couldn't make the {when} Short: {e}") from e
        db.update_video(video_id, theme=plan["script"]["premise"], trend=plan["script"]["trend_used"] or None, plan=plan)
        row = db.get_video(video_id)
    return publisher.run(row, slot, sched, progress=progress)


def prepare(count: int = 1, progress=_log) -> dict:
    """Writes `count` episodes into the queue, where the autopilot picks them up oldest first."""
    cfg = load_config()
    planned = []
    for _ in range(count):
        plan = _write_episode(cfg, progress)
        video_id = db.insert_video("planned", "sketch", plan["script"]["premise"], plan["script"]["trend_used"] or None,
                                   plan)
        planned.append({"id": video_id, "theme": plan["script"]["premise"], "title": plan["metadata"]["title"]})
        progress(f"Saved episode #{video_id}: {plan['metadata']['title']}")
    return {"planned": planned}


def publish(dry_run: bool = False, video_id: int | None = None, progress=_log) -> dict:
    """Agent 3 renders one queued episode (the oldest, or `video_id`); without dry_run Agent 4 then
    uploads it into the next open slot. A real upload reuses an existing preview, so what you
    watched in the dashboard is exactly what goes up."""
    row = db.get_video(video_id) if video_id else publisher.choose()
    if not row:
        return {"skipped": "nothing planned"}
    if row["status"] != "planned":
        raise RuntimeError(f"Short #{row['id']} is {row['status']}, not planned")
    if dry_run:
        made = animator.run(row, progress=progress)
        return {"rendered": str(animator.preview_path(row["id"])), "video_id": row["id"],
                "title": made["plan"]["metadata"]["title"], "length": made["length"], "music": made["music"]}

    sched = slots.plan()
    slot = next_open_slot(MANUAL_LEAD, sched=sched)
    if not db.claim(row["id"], slots.iso(slot)):
        raise RuntimeError(f"Short #{row['id']} couldn't take the {clock(slot, sched)} slot; try again")
    return publisher.run(db.get_video(row["id"]), slot, sched, progress=progress)


def stats(learn: bool = False, progress=_log) -> dict:
    return analyst.run(progress=progress, learn_now=learn)


JOBS = {"autopilot": autopilot, "prepare": prepare, "publish": publish, "stats": stats}


def run_job(name: str, **kwargs) -> dict:
    """Run a job with its start/finish logged to the runs table; failures also go to your phone."""
    started = time.monotonic()
    run_id = db.start_run(f"{name} (preview)" if kwargs.get("dry_run") else name)
    try:
        result = JOBS[name](**kwargs)
    except Exception as e:
        db.finish_run(run_id, False, {"error": str(e)})
        notify.run(f"⚠️ The {name} job failed: {e}")
        raise
    result["seconds"] = round(time.monotonic() - started, 1)
    db.finish_run(run_id, True, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("job", choices=list(JOBS))
    parser.add_argument("--dry-run", action="store_true", help="publish only: render but don't upload")
    parser.add_argument("--now", action="store_true", help="autopilot only: the next open slot, even if not due")
    parser.add_argument("--learn", action="store_true", help="stats only: rewrite the playbook now")
    args = parser.parse_args()

    if args.job == "autopilot" and (paused := _paused()):
        print(json.dumps(paused))
        return 0
    kwargs = {"dry_run": True} if args.dry_run and args.job == "publish" else {}
    if args.job == "autopilot":
        check()
        kwargs = {"force": args.now}
    if args.job == "stats":
        kwargs = {"learn": args.learn}
    try:
        result = run_job(args.job, **kwargs)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
