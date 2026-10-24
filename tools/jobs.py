"""
The jobs that run the channel. Vercel Cron calls them through app.py (the autopilot check
every hour, stats once a day); on your computer the dashboard runs the autopilot check itself.

  autopilot  the earliest posting slot that's due -> a Short for it (the oldest planned one,
             or a new one: trends -> concept -> clips -> frame check -> captions) -> render ->
             upload, scheduled to go public on the minute of its slot
  prepare    plans one Short and keeps it as "planned" (the autopilot uses those first)
  publish    renders and uploads one planned Short into the next open slot
  stats      numbers for published Shorts; on Sundays, a "what worked" note for future concepts

The slots come from `schedule` in config/channel.yaml (see tools/slots.py). A slot is due
from 150 minutes before it until an hour after: with the hourly check that gives each Short
two tries before its time, and a missed one still goes out late rather than not at all.

Setting PAUSED=true stops the autopilot and every cloud job (the kill switch). Planning,
previews and uploads you start yourself still work.
Each job reports its steps through `progress` (stderr by default; the dashboard shows them live).

Usage:
    python tools/jobs.py autopilot [--now]     # --now: the next open slot, even if it isn't due yet
    python tools/jobs.py prepare
    python tools/jobs.py publish [--dry-run]   # --dry-run renders but doesn't upload
    python tools/jobs.py stats
"""

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

import clip_check
import clips_search
import concept_write
import db
import notify
import short_render
import slots
import stats_pull
import trends_fetch
import youtube_upload
from common import TMP_DIR, is_true, load_config, tmp_path

MAKE_AHEAD = timedelta(minutes=150)    # a slot is due this long before its time
LATE_GRACE = timedelta(minutes=60)     # ...and stays due this long after it (the Short then goes live at once)
STALE_CLAIM = timedelta(minutes=15)    # "making" for longer means the run was cut off
GO_LIVE_MARGIN = timedelta(minutes=3)  # closer than this to its slot, a Short is uploaded as public right away
MANUAL_LEAD = timedelta(minutes=10)    # an upload you start yourself takes a slot at least this far ahead
RECENT_THEMES = 60                     # how many recent themes the planner is told not to repeat
TRENDS_FRESH = timedelta(hours=6)      # how long fetched trends are reused (worldwide is ~190 requests)


class NoClipsError(RuntimeError):
    pass


def _log(message: str) -> None:
    print(f"  {message}", file=sys.stderr, flush=True)


def _paused() -> dict | None:
    return {"skipped": "PAUSED is set"} if is_true("PAUSED") else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clock(slot: datetime, sched: dict) -> str:
    """A slot as the schedule's clock shows it, e.g. 10:00."""
    return slot.astimezone(sched["tz"]).strftime("%H:%M")


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
    """The cheap part of each hourly check: check in, free Shorts whose run was cut off, and
    say whether a slot is due."""
    db.beat("autopilot")
    for row in db.release_stale(slots.iso(_now() - STALE_CLAIM)):
        progress(f"Short #{row['id']} was interrupted while being made; it's now {row['status']}")
    return due_slot()


def tick(progress=_log) -> dict:
    """What Vercel Cron calls every hour: a full autopilot run only when a slot is due, so the
    quiet hours cost almost nothing."""
    if paused := _paused():
        return paused
    if not check(progress):
        return {"skipped": "no slot is due yet"}
    return run_job("autopilot", progress=progress)


# --- making Shorts --------------------------------------------------------

def _pick_clips(concept: dict, used: set[str], cfg: dict, progress) -> list[dict]:
    fmt = concept_write.FORMATS[concept["format"]]
    content = cfg["content"]
    min_seconds = max(content["min_clip_seconds"], fmt["seconds"][0] + 0.5)  # long enough for the format
    query_sets = [concept["search_queries"], [f"cute {concept['animal']}", f"funny {concept['animal']}"]]
    for round_number, queries in enumerate(query_sets):  # second round: broader searches for the same animal
        progress(("Trying broader searches: " if round_number else "Searching stock clips: ") + ", ".join(queries))
        candidates = clips_search.run(queries, exclude=used, min_seconds=min_seconds)
        if not candidates:
            continue
        progress(f"Checking {len(candidates)} clips frame by frame")
        checked = clip_check.run(candidates, concept["theme"], content["allow_people"], content["min_check_score"],
                                 animal=concept["animal"])
        approved = [c for c in checked if c["ok"]]
        if len(approved) >= fmt["clips"]:
            return approved[:fmt["clips"]]
    raise NoClipsError(f"not enough suitable clips for '{concept['theme']}'")


def _plan_one(cfg: dict, trends: dict, fmt: str, recent_themes: list[str], learnings, used: set[str],
              progress) -> dict:
    progress(f"Planning a {fmt} Short")
    concept = concept_write.plan_concept(trends, fmt, recent_themes, learnings, cfg)
    progress(f"Idea: {concept['theme']}")
    clips = _pick_clips(concept, used, cfg, progress)
    progress("Writing the captions, title and hashtags")
    meta = concept_write.write_metadata(concept, clips, cfg)
    keep = ("key", "source", "id", "page_url", "credit_name", "credit_url", "duration", "width", "height",
            "download_url", "preview_urls", "check")
    return {"concept": concept, "clips": [{k: c.get(k) for k in keep} for c in clips], "metadata": meta,
            "edit": concept_write.build_edit(fmt, meta, clips, cfg)}


def _next_format(cfg: dict) -> str:
    rotation = cfg["formats"]["rotation"]
    return rotation[db.count_videos() % len(rotation)]


def trend_signals(cfg: dict, days_ahead: int | None = None, refresh: bool = False) -> dict:
    """Today's trend signals for the planner and the dashboard. What comes from the internet is
    kept for TRENDS_FRESH: trends move slowly, and Google's feed refuses to be asked by every
    country for every Short. The calendar part is worked out fresh each time."""
    region = str(cfg["trends"]["region"]).upper()
    online = None if refresh else db.fresh_note("trends", TRENDS_FRESH)
    if not online or online.get("region") != region:
        online = trends_fetch.online(region)
        if online["google_trends"] or online["youtube_popular"]:  # an empty fetch is retried next time
            db.keep_note("trends", online)
    today = _now().date()
    days = cfg["trends"]["calendar_days_ahead"] if days_ahead is None else days_ahead
    return {"date": today.isoformat(), "weekday": today.strftime("%A"), **trends_fetch.calendar_signals(today, days),
            **online}


def _plan_new(cfg: dict, fmt: str, progress) -> dict:
    """A fresh plan from today's trends; the caller saves it and marks its clips used."""
    progress("Reading today's trends and pet days"
             + (" from every country" if str(cfg["trends"]["region"]).upper() == "ALL" else ""))
    trends = trend_signals(cfg)
    recent_themes = [v["theme"] for v in db.recent_videos(days=21) if v["theme"]][:RECENT_THEMES]
    learnings = (db.latest_note("learnings") or {}).get("learnings")
    return _plan_one(cfg, trends, fmt, recent_themes, learnings, db.used_clip_keys(), progress)


def _save_plan(video_id: int, plan: dict) -> None:
    """Fills in a Short that was saved before its plan existed (to hold its slot)."""
    concept = plan["concept"]
    db.update_video(video_id, theme=concept["theme"], trend=concept.get("trend_used") or None, plan=plan)
    db.mark_clips_used([c["key"] for c in plan["clips"]])


def _render_and_upload(row: dict, slot: datetime, cfg: dict, sched: dict, progress) -> dict:
    """Uploads a Short already claimed for `slot`: scheduled for the slot, or public at once
    if the slot is only minutes away or has passed. On failure the Short goes back to the
    queue for one more try, then counts as failed."""
    plan, out = row["plan"], tmp_path("out", f"short_{row['id']}.mp4")
    meta, when = plan["metadata"], clock(slot, sched)
    try:
        if not out.exists():  # reuse the preview you watched, if there is one
            progress("Downloading the clips and rendering the video")
            short_render.run(plan["edit"], out, "auto", cfg["music"]["volume"])
        db.update_video(row["id"], claimed_at=db.now_iso())  # still alive: rendering can take a while
        live_now = slot - _now() <= GO_LIVE_MARGIN
        progress("Uploading to YouTube, public right away" if live_now
                 else f"Uploading to YouTube, scheduled for {when}")
        upload = youtube_upload.run(out, meta["title"], meta["description"], meta["tags"],
                                    publish_at=None if live_now else slots.iso(slot), public=live_now,
                                    category_id=cfg["metadata"]["category_id"], language=cfg["metadata"]["language"])
    except Exception as e:
        attempts = row["attempts"] + 1
        status = "planned" if attempts < 2 else "failed"
        db.update_video(row["id"], status=status, attempts=attempts, error=str(e)[:500], slot=None, claimed_at=None)
        outcome = "it goes back to the queue for another try" if status == "planned" else "gave up after 2 tries"
        raise RuntimeError(f"Short #{row['id']} for {when} not uploaded ({outcome}): {e}") from e
    finally:
        out.unlink(missing_ok=True)
        shutil.rmtree(TMP_DIR / "clips", ignore_errors=True)

    publish_at = slots.iso(_now()) if live_now else slots.iso(slot)
    db.update_video(row["id"], status="scheduled", youtube_id=upload["id"], publish_at=publish_at, error=None)
    if live_now:
        notify.run(f"\U0001F43E New Short is live (the {when} slot):\n{meta['title']}\n{upload['url']}")
    else:
        notify.run(f"\U0001F43E New Short goes live at {when}:\n{meta['title']}\n"
                   f"Watch, edit or delete it before then: {upload['studio_url']}")
    return {"video_id": row["id"], "youtube_id": upload["id"], "slot": slots.iso(slot), "publish_at": publish_at,
            "live_now": live_now, "title": meta["title"]}


def autopilot(force: bool = False, progress=_log) -> dict:
    """Makes and uploads the Short for the earliest slot that's due. With force, takes the
    next open slot even if it isn't due yet (the dashboard's "make it now" button)."""
    cfg, sched = load_config(), slots.plan()
    now = _now()
    slot = due_slot(now, sched) or (next_open_slot(GO_LIVE_MARGIN, now, sched) if force else None)
    if not slot:
        return {"skipped": "no slot is due yet"}
    when = clock(slot, sched)

    row = db.next_planned()
    if row:
        if not db.claim(row["id"], slots.iso(slot)):
            return {"skipped": f"another run is already making the {when} Short"}
        progress(f"Using planned Short #{row['id']} for the {when} slot")
        row = db.get_video(row["id"])
    else:
        fmt = _next_format(cfg)
        video_id = db.insert_video("making", fmt, None, None, {}, slot=slots.iso(slot))
        if video_id is None:
            return {"skipped": f"another run is already making the {when} Short"}
        progress(f"Making a new Short for the {when} slot")
        try:
            plan = _plan_new(cfg, fmt, progress)
        except Exception as e:
            db.update_video(video_id, status="skipped", error=str(e)[:500])
            raise RuntimeError(f"Couldn't make the {when} Short: {e}") from e
        _save_plan(video_id, plan)
        progress(f"Saved Short #{video_id}: {plan['metadata']['title']}")
        row = db.get_video(video_id)
    return _render_and_upload(row, slot, cfg, sched, progress)


def prepare(count: int = 1, progress=_log) -> dict:
    """Plans `count` Shorts into the queue, where the autopilot picks them up oldest first."""
    cfg = load_config()
    planned, skipped = [], []
    for _ in range(count):
        fmt = _next_format(cfg)
        try:
            plan = _plan_new(cfg, fmt, progress)
        except NoClipsError as e:
            progress(f"Skipped: {e}")
            skipped.append(str(e))
            continue
        concept = plan["concept"]
        video_id = db.insert_video("planned", fmt, concept["theme"], concept.get("trend_used") or None, plan)
        db.mark_clips_used([c["key"] for c in plan["clips"]])
        planned.append({"id": video_id, "format": fmt, "theme": plan["concept"]["theme"],
                        "title": plan["metadata"]["title"]})
        progress(f"Saved Short #{video_id}: {plan['metadata']['title']}")
    if skipped:
        notify.run("Couldn't plan a Short: " + "; ".join(skipped))
    return {"planned": planned, "skipped": skipped}


def publish(dry_run: bool = False, video_id: int | None = None, progress=_log) -> dict:
    """Renders and uploads one planned Short (the oldest, or `video_id`) into the next open slot.

    dry_run renders a preview only. A real publish reuses an existing preview, so what you
    watched in the dashboard is exactly what gets uploaded.
    """
    cfg = load_config()
    row = db.get_video(video_id) if video_id else db.next_planned()
    if not row:
        return {"skipped": "nothing planned"}
    if row["status"] != "planned":
        raise RuntimeError(f"Short #{row['id']} is {row['status']}, not planned")
    if dry_run:
        out = tmp_path("out", f"short_{row['id']}.mp4")
        progress("Downloading the clips and rendering the video")
        short_render.run(row["plan"]["edit"], out, "auto", cfg["music"]["volume"])
        return {"rendered": str(out), "title": row["plan"]["metadata"]["title"]}

    sched = slots.plan(cfg)
    slot = next_open_slot(MANUAL_LEAD, sched=sched)
    if not db.claim(row["id"], slots.iso(slot)):
        raise RuntimeError(f"Short #{row['id']} couldn't take the {clock(slot, sched)} slot; try again")
    return _render_and_upload(db.get_video(row["id"]), slot, cfg, sched, progress)


def stats(progress=_log) -> dict:
    published = db.published_videos(days=60)
    if not published:
        return {"skipped": "no published Shorts yet"}

    progress(f"Fetching numbers for {len(published)} published Shorts")
    result = stats_pull.run([v["youtube_id"] for v in published])
    found = {s["youtube_id"] for s in result["videos"]}
    vetoed = [v for v in published if v["youtube_id"] not in found]  # deleted in YouTube Studio
    for v in vetoed:
        db.update_video(v["id"], status="vetoed")
    published = [v for v in published if v["youtube_id"] in found]
    today = datetime.now(timezone.utc).date()
    db.save_stats(result["videos"], today.isoformat())
    summary = {"updated": len(result["videos"]), "vetoed": len(vetoed), "analytics_error": result["analytics_error"]}

    if today.weekday() == 6 and len(published) >= 3:  # Sunday: learn from the numbers
        by_id = {s["youtube_id"]: s for s in result["videos"]}
        # Only public counts go to Gemini (free tier prompts may be used by Google): private
        # analytics like average % viewed stay in the database and dashboard (see /privacy).
        rows = [{"format": v["format"], "theme": v["theme"], "trend": v["trend"],
                 "hook": v["plan"]["metadata"]["hook"], "title": v["plan"]["metadata"]["title"],
                 "animal": v["plan"]["concept"]["animal"],
                 **{k: by_id.get(v["youtube_id"], {}).get(k) for k in ("views", "likes", "comments")}}
                for v in published]
        learnings = concept_write.write_learnings(rows, load_config())
        db.add_note("learnings", learnings)
        notify.run("\U0001F4CA Weekly check-in: " + learnings["summary"] + "\n- " + "\n- ".join(learnings["learnings"]))
        summary["learnings"] = learnings["learnings"]
    return summary


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
    args = parser.parse_args()

    if args.job == "autopilot" and (paused := _paused()):
        print(json.dumps(paused))
        return 0
    kwargs = {"dry_run": True} if args.dry_run and args.job == "publish" else {}
    if args.job == "autopilot":
        check()
        kwargs = {"force": args.now}
    try:
        result = run_job(args.job, **kwargs)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
