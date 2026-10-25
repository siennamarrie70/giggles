"""
Agent 4, Publisher: puts each Short on YouTube in its posting slot.

It takes the oldest episode in the queue, has the Animator make the video if there's no preview yet
(a preview you watched is uploaded exactly as you saw it), and uploads it as private with the slot
as its publish time, so YouTube makes it public on the minute; a slot that's only minutes away, or
already passed, goes up public at once. The description gets the music's credit line. On a failure
the Short goes back to the queue for one more try, then counts as failed. Until a Short goes public
you can still delete it in YouTube Studio: that's the veto.

Usage:
    python tools/jobs.py publish        # Agent 4 uploads the oldest queued Short into the next open slot
"""

from datetime import datetime, timedelta, timezone

import db
import notify
import short_render
import slots
import youtube_upload
from agents import animator
from agents.base import act, log
from common import load_config

GO_LIVE_MARGIN = timedelta(minutes=3)  # closer than this to its slot, a Short is uploaded as public right away


def choose() -> dict | None:
    """The episode that takes the next slot: the oldest one written."""
    return db.next_planned()


def description(meta: dict, plan: dict) -> str:
    """The description with the music credit added, if the track needs one and it isn't there yet."""
    credit = short_render.music_credit(plan.get("music"))
    text = meta["description"] or ""
    return f"{text.rstrip()}\n\n{credit}" if credit and credit not in text else text


def upload(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    """Uploads a Short already claimed for `slot` (making its video first if needed)."""
    cfg = load_config()
    plan, out = row["plan"], animator.preview_path(row["id"])
    meta, when = plan["metadata"], slots.clock(slot, sched)
    try:
        if not out.exists() or "music" not in plan:  # no preview yet, or one from before tracks were remembered
            plan = animator.run(row, out, progress=progress)["plan"]
        db.update_video(row["id"], claimed_at=db.now_iso())  # still alive: animating can take a while
        live_now = slot - datetime.now(timezone.utc) <= GO_LIVE_MARGIN
        progress("Uploading to YouTube, public right away" if live_now
                 else f"Uploading to YouTube, scheduled for {when}")
        result = youtube_upload.run(out, meta["title"], description(meta, plan), meta["tags"],
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

    publish_at = slots.iso(datetime.now(timezone.utc)) if live_now else slots.iso(slot)
    db.update_video(row["id"], status="scheduled", youtube_id=result["id"], publish_at=publish_at, error=None)
    if live_now:
        notify.run(f"\U0001F3AC New Short is live (the {when} slot):\n{meta['title']}\n{result['url']}")
    else:
        notify.run(f"\U0001F3AC New Short goes live at {when}:\n{meta['title']}\n"
                   f"Watch, edit or delete it before then: {result['studio_url']}")
    return {"video_id": row["id"], "youtube_id": result["id"], "slot": slots.iso(slot), "publish_at": publish_at,
            "live_now": live_now, "title": meta["title"]}


def run(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    return act("publisher", f"Upload Short #{row['id']}", upload, row, slot, sched, progress=progress)
