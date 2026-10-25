"""
Agent 5, Publisher: puts each case on YouTube in its posting slot.

It takes the oldest case that's ready (approved, or never needing approval: cases about this week's
news or politics wait for your OK in the Studio), has the Animator make the video if there's no
preview yet (a preview you watched is uploaded exactly as you saw it), and uploads it as private
with the slot as its publish time, so YouTube makes it public on the minute; a slot that's only
minutes away, or already passed, goes up public at once. Category Education, "not made for kids",
no synthetic-media label (cartoons, real photos and charts aren't realistic synthetic footage).

The description is put together here, so its credits always match the final video: the Writer's
summary, the sources the script's facts came from, the photos it shows, part 1's link for a
follow-up, the music's credit line, and the hashtags. On a failure the case goes back to the queue
for one more try, then counts as failed. Until it goes public you can still delete it in YouTube
Studio: that's the veto.

Usage:
    python tools/jobs.py publish        # Agent 5 uploads the oldest ready case into the next open slot
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
MAX_SOURCES = 6


def choose() -> dict | None:
    """The case that takes the next slot: the oldest one ready to go up."""
    return db.next_planned()


def approve(video_id: int) -> dict:
    """Your OK for a case that waits for it (news and politics)."""
    row = db.get_video(video_id)
    if not row or row["status"] != "planned" or row["plan"].get("approval") != "waiting":
        raise ValueError(f"Short #{video_id} isn't waiting for approval")
    db.update_video(video_id, plan={**row["plan"], "approval": "approved", "approved_at": db.now_iso()})
    return {"video_id": video_id, "approved": True}


def credits(plan: dict) -> dict:
    """The sources behind the facts the script uses, and the photos it shows."""
    pack, lines = plan.get("research") or {}, (plan.get("script") or {}).get("lines") or []
    used_facts = {f for line in lines for f in line.get("facts") or []}
    by_fact = {f["id"]: f["source"] for f in pack.get("facts") or []}
    cited = {by_fact[f] for f in used_facts if f in by_fact}
    sources = [s for s in pack.get("sources") or [] if s["id"] in cited][:MAX_SOURCES]
    shown = {line["visual"].split(":", 1)[1] for line in lines if line.get("visual", "").startswith("photo:")}
    photos = [i for i in pack.get("images") or [] if i["id"] in shown]
    return {"sources": sources, "photos": photos}


def description(meta: dict, plan: dict) -> str:
    parts = [meta.get("description") or ""]
    found = credits(plan)
    if found["sources"]:
        parts.append("Sources:\n" + "\n".join(f"- {s.get('publisher') or s['title']}: {s['title']} {s['url']}"
                                                if s.get("publisher") and s["publisher"] != s["title"]
                                                else f"- {s['title']}: {s['url']}" for s in found["sources"]))
    if found["photos"]:
        parts.append("Photos (Wikimedia Commons):\n" + "\n".join(
            f"- {p['title']} by {p['author']}, {p['licence']}: {p['page']}" for p in found["photos"]))
    earlier = (plan.get("brief") or {}).get("follow_up_of")
    if earlier and (row := db.get_video(earlier)) and row.get("youtube_id"):
        parts.append(f"Part 1: https://youtube.com/shorts/{row['youtube_id']}")
    credit = short_render.music_credit(plan.get("music"))
    if credit:
        parts.append(credit)
    if meta.get("hashtags"):
        parts.append(" ".join(meta["hashtags"]))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def upload(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    """Uploads a case already claimed for `slot` (making its video first if needed)."""
    cfg = load_config()
    plan, out = row["plan"], animator.preview_path(row["id"])
    meta, when = plan["metadata"], slots.clock(slot, sched)
    try:
        if not out.exists() or "music" not in plan:  # no preview yet
            plan = animator.run(row, out, progress=progress)["plan"]
        db.update_video(row["id"], claimed_at=db.now_iso())  # still alive: animating can take a while
        live_now = slot - datetime.now(timezone.utc) <= GO_LIVE_MARGIN
        progress("Uploading to YouTube, public right away" if live_now
                 else f"Uploading to YouTube, scheduled for {when}")
        result = youtube_upload.run(out, meta["title"], description(meta, plan), meta["tags"],
                                    publish_at=None if live_now else slots.iso(slot), public=live_now,
                                    category_id=cfg["metadata"]["category_id"], language=cfg["metadata"]["language"],
                                    synthetic_media=False)
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
        notify.run(f"\U0001F3AC New case is live (the {when} slot):\n{meta['title']}\n{result['url']}")
    else:
        notify.run(f"\U0001F3AC New case goes live at {when}:\n{meta['title']}\n"
                   f"Watch, edit or delete it before then: {result['studio_url']}")
    return {"video_id": row["id"], "youtube_id": result["id"], "slot": slots.iso(slot), "publish_at": publish_at,
            "live_now": live_now, "title": meta["title"]}


def run(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    return act("publisher", f"Upload Short #{row['id']}", upload, row, slot, sched, progress=progress)
