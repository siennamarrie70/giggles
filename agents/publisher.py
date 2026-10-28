"""
Agent 6, Publisher: puts each case on YouTube in its posting slot, and on Instagram as a Reel.

It takes the oldest case that's ready: approved, or never needing approval (with cases.approval off
in the settings, as now, it approves news and politics itself: auto_approve), and not held by the
Reviewer. Its video must have passed the Reviewer (Agent 5): without a reviewed video, the Animator
makes it and the Reviewer reviews it first, fixes included (agents/reviewer.py, reviewed()). If
Gemini's voice is out, the case goes back to the queue untouched and waits for it (no other voice
reads him). A video the Reviewer turns down after the fixes is never posted as it is: the slot goes to the
next case, and it's made again by itself until it passes (agents/reviewer.py hold()), then takes a slot.

YouTube: uploaded as private with the slot as its publish time, so YouTube makes it public on the
minute; a slot only minutes away, or already passed, goes up public at once. Category Education, "not
made for kids", no synthetic-media label (a drawn host, real footage, real photos and charts aren't
realistic synthetic footage). Then its thumbnail: the Animator's wide one (16:9), which YouTube
shows in YouTube Studio, search on computers, shared links and embeds (verified channels only). The
Shorts tab and feed show a frame YouTube picks from the video: custom Shorts covers are only for
YouTube Partner Program channels (since 2026-07-24), set in YouTube Studio on a computer, not
through the API.

Instagram (when it's connected and switched on: settings `instagram.enabled`): when the Short's slot
comes and it's public on YouTube (not deleted there: that's still the veto), the same video goes up
as a Reel (tools/instagram.py; Instagram can't schedule them), with a caption made from the same
description and its cover frame at the thumbnail's shot. A failed try waits longer each time
(REEL_WAITS: Instagram drops uploads in spells, #46 ten times in a row over 90 minutes on 2026-10-27),
about nine hours in all. The video is kept on this computer until the Reel is up, or REEL_DAYS after
its slot. In the cloud (GitHub Actions, whose machine is wiped after each run) a Reel whose slot comes
while the run that made it is still going is posted by that run (tools/jobs.py, morning); the others'
videos are kept, encrypted, with that run (tools/kept.py: the Reel records it as `kept_in`), and the
Reels workflow (.github/workflows/reels.yml) fetches each at its slot. With the database in the cloud,
this computer's dashboard only shows Reels: it neither posts nor makes them again (_made_here).

Beside each Short the Schedule page shows where it stands on YouTube and on Instagram (platforms())
with your buttons for each. YouTube: Open, Post now (public at once; its slot stays its own and its
Reel still waits for the slot), Stop, Delete (public or not; a Reel not posted yet goes with it).
Instagram: Open, Post now (at once, even before it's public on YouTube), Delete (a posted Reel is
deleted from Instagram; one not posted yet is taken off, and Post now still can while its video is
kept). A Reel is claimed ("posting") before it's posted, so it goes up once whoever asks. A Short
that went up while Reels were off has no video kept: Schedule (remake_reel) makes it again for
Instagram (the same case, music and drawings, read again by the same voice) and its Reel then waits
for its slot.

The description is put together here, so its credits always match the final video: the Writer's
summary, the sources the script's facts came from, the photos, stock clips and archive films it shows
(stock clips are marked as illustrative; NASA is credited without suggesting it endorses anything),
part 1's link for a follow-up, the music's credit line, and the hashtags, of which any the Analyst's
numbers show doing clearly worse than usual are dropped. Once a Short is up, its clips count as used,
so no later case shows them again. On a failed upload the case goes back to the queue for one more
try (its reviewed video kept), then counts as failed. Until it goes public you can still delete it in
YouTube Studio: that's the veto.

Usage:
    python tools/jobs.py publish        # Agent 6 uploads the oldest ready case into the next open slot
    python tools/jobs.py instagram      # ...and posts the Reels whose slot has come
"""

import threading
from datetime import datetime, timedelta, timezone

import db
import instagram
import kept
import notify
import short_render
import slots
import text_clean
import youtube_auth
import youtube_upload
from agents import animator, reviewer
from agents.base import act, log, playbook
from common import TMP_DIR, env, load_config

GO_LIVE_MARGIN = timedelta(minutes=3)  # closer than this to its slot, a Short is uploaded as public right away
MAX_SOURCES = 6
WEAK_HASHTAG = 0.7                     # a hashtag this far below the channel's usual views is dropped
REEL_WAITS = (10, 20, 40, 60, 90, 120, 180)  # minutes before the next try of a Reel Instagram didn't take, by try
REEL_TRIES = len(REEL_WAITS) + 1
REEL_DAYS = 2                          # a Reel not posted within this long after its slot is given up (its video deleted)
POSTING_STALE = timedelta(minutes=30)  # a Reel "posting" for longer was cut off (the dashboard stopped)
STUDIO_GRACE = timedelta(minutes=5)    # still private this long after its time: made private in YouTube Studio
PUBLISH_LAG = timedelta(minutes=30)    # a Reel waits this long for YouTube to make its Short public (it's a little late)
_reels = threading.RLock()             # one claim at a time, so a Reel goes up once whoever asks


def choose() -> dict | None:
    """The case that takes the next slot: the oldest one ready to go up."""
    return db.next_planned()


def approve(video_id: int, by: str = "you") -> dict:
    """The OK for a case that waits for it (news and politics): yours from the Studio, or the Publisher's own."""
    row = db.get_video(video_id)
    if not row or row["status"] != "planned" or row["plan"].get("approval") != "waiting":
        raise ValueError(f"Short #{video_id} isn't waiting for approval")
    db.update_video(video_id, plan={**row["plan"], "approval": "approved", "approved_at": db.now_iso(), "approved_by": by})
    return {"video_id": video_id, "approved": True}


def auto_approve(progress=log) -> list[int]:
    """The Publisher approves, by itself, every waiting case whose reason to wait is switched off in the settings
    (cases.approval: false for news and for politics means no case waits for anyone). Runs with every check."""
    approval = load_config()["cases"].get("approval") or {}
    approved = []
    for v in db.planned_videos():
        brief = v["plan"].get("brief") or {}
        if v["plan"].get("approval") != "waiting":
            continue
        still = ((brief.get("category") == "trending" and approval.get("trending", True))
                 or (brief.get("political") and approval.get("politics", True)))
        if not still:
            approve(v["id"], by="publisher")
            approved.append(v["id"])
            progress(f"The Publisher approved case #{v['id']} itself")
    return approved


def shown(plan: dict) -> dict[str, list[dict]]:
    """The pack's photos, stock clips and archive films that the script puts on screen, in order."""
    pack, lines = plan.get("research") or {}, (plan.get("script") or {}).get("lines") or []
    names = [v for line in lines for v in line.get("visuals") or []]
    if not names:  # v4 cases: one visual per line
        names = [line["visual"] for line in lines if line.get("visual")]
    out = {}
    for kind, key in (("photo", "images"), ("footage", "footage"), ("archive", "archive")):
        ids = list(dict.fromkeys(n.split(":", 1)[1] for n in names if n.startswith(f"{kind}:")))
        by_id = {x["id"]: x for x in pack.get(key) or []}
        out[kind] = [by_id[i] for i in ids if i in by_id]
    return out


def credits(plan: dict) -> dict:
    """The sources behind the facts the script uses, and the photos, clips and films it shows."""
    pack, lines = plan.get("research") or {}, (plan.get("script") or {}).get("lines") or []
    used_facts = {f for line in lines for f in line.get("facts") or []}
    by_fact = {f["id"]: f["source"] for f in pack.get("facts") or []}
    cited = {by_fact[f] for f in used_facts if f in by_fact}
    sources = [s for s in pack.get("sources") or [] if s["id"] in cited][:MAX_SOURCES]
    on_screen = shown(plan)
    return {"sources": sources, "photos": on_screen["photo"], "footage": on_screen["footage"],
            "archive": on_screen["archive"]}


def hashtags(tags: list[str]) -> list[str]:
    """The Writer's hashtags without any the playbook shows doing clearly worse than usual (never the channel's own
    base hashtags, and always at least two)."""
    lifts = (playbook().get("weights") or {}).get("hashtag") or {}
    base = set(load_config()["metadata"]["base_hashtags"])
    kept = [t for t in tags if t in base or lifts.get(t.lower(), 1.0) > WEAK_HASHTAG]
    return kept if len(kept) >= 2 else tags


def _named(text: str) -> str:
    """A name from a web page or a photo's details, as shown: no web addresses, no < or >, at most 120 characters."""
    return text_clean.no_brackets(text_clean.no_links(text))[:120]


def _source(s: dict) -> str:
    """A "Sources:" line; its address only if it's an ordinary page (text_clean.linkable)."""
    title, publisher = _named(s["title"]), _named(s.get("publisher") or "")
    link = s["url"] if text_clean.linkable(s["url"]) else ""
    if publisher and publisher != title:
        return f"- {publisher}: {title} {link}".rstrip()
    return f"- {title}: {link}" if link else f"- {title}"


def description(meta: dict, plan: dict, links: bool = True) -> str:
    """The description, credits included; without links (Instagram's caption), the sources are named but not linked."""
    parts = [meta.get("description") or ""]
    found = credits(plan)
    if found["sources"] and links:
        parts.append("Sources:\n" + "\n".join(_source(s) for s in found["sources"]))
    elif found["sources"]:
        parts.append("Sources: " + "; ".join(dict.fromkeys(_named(s.get("publisher") or s["title"])
                                                           for s in found["sources"])))
    if found["photos"]:
        parts.append("Photos (Wikimedia Commons):\n" + "\n".join(
            f"- {_named(p['title'])} by {_named(p['author'])}, {p['licence']}"
            + (f": {p['page']}" if text_clean.linkable(p["page"]) else "") for p in found["photos"]))
    if found["archive"]:
        parts.append("Archive footage:\n" + "\n".join(f"- {c['credit']}" for c in found["archive"]))
    if found["footage"]:
        parts.append("Stock footage (illustrative):\n" + "\n".join(f"- {c['credit']}" for c in found["footage"]))
    earlier = (plan.get("brief") or {}).get("follow_up_of")
    if earlier and links and (row := db.get_video(earlier)) and row.get("youtube_id"):
        parts.append(f"Part 1: https://youtube.com/shorts/{row['youtube_id']}")
    credit = short_render.music_credit(plan.get("music"))
    if credit:
        parts.append(credit)
    if meta.get("hashtags"):
        parts.append(" ".join(hashtags(meta["hashtags"])[:instagram.MAX_HASHTAGS]))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def caption(meta: dict, plan: dict) -> str:
    """The Reel's caption: the title, then the description without source links, within Instagram's 2,200
    characters (the stock and archive credits are shortened first if it's too long)."""
    text = f"{meta['title']}\n\n{description(meta, plan, links=False)}"
    if len(text) > instagram.CAPTION_CHARS:
        lean = {**plan, "research": {**(plan.get("research") or {}), "footage": [], "archive": []}}
        text = f"{meta['title']}\n\n{description(meta, lean, links=False)}"
    return text[:instagram.CAPTION_CHARS]


def reels_on() -> bool:
    return bool((load_config().get("instagram") or {}).get("enabled")) and instagram.is_configured()


def upload(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    """Uploads a case already claimed for `slot`, once its video has passed the Reviewer (made and reviewed now if
    needed). A case the Reviewer turns down gives the slot back, for the next case, and is made again by itself later
    (agents/reviewer.py hold()); nothing of it goes to YouTube meanwhile."""
    cfg = load_config()
    out = animator.preview_path(row["id"])
    when = slots.clock(slot, sched)
    try:
        row = reviewer.reviewed(row, progress=progress, now=True)
        if not reviewer.passed(row["plan"]):
            db.update_video(row["id"], status="planned", slot=None, claimed_at=None)
            return {"skipped": f"the Reviewer turned case #{row['id']} down (it's made again by itself); the {when} "
                               "slot goes to the next case", "video_id": row["id"], "held": True}
        plan = row["plan"]
        meta = plan["metadata"]
        db.update_video(row["id"], claimed_at=db.now_iso())  # still alive: making and reviewing can take a while
        live_now = slot - datetime.now(timezone.utc) <= GO_LIVE_MARGIN
        progress("Uploading to YouTube, public right away" if live_now
                 else f"Uploading to YouTube, scheduled for {when}")
        result = youtube_upload.run(out, meta["title"], description(meta, plan), meta["tags"],
                                    publish_at=None if live_now else slots.iso(slot), public=live_now,
                                    category_id=cfg["metadata"]["category_id"], language=cfg["metadata"]["language"],
                                    synthetic_media=False)
    except (animator.Resting, youtube_upload.UploadLimit):  # not the case's fault: it waits for Gemini's voice,
        db.update_video(row["id"], status="planned", slot=None, claimed_at=None)  # Cloudflare's drawing or YouTube's
        raise                                                                     # daily upload limit, no try counted
    except Exception as e:
        attempts = row["attempts"] + 1
        status = "planned" if attempts < 2 else "failed"
        db.update_video(row["id"], status=status, attempts=attempts, error=str(e)[:500], slot=None, claimed_at=None)
        outcome = "it goes back to the queue for another try" if status == "planned" else "gave up after 2 tries"
        raise RuntimeError(f"Short #{row['id']} for {when} not uploaded ({outcome}): {e}") from e

    publish_at = slots.iso(datetime.now(timezone.utc)) if live_now else slots.iso(slot)
    db.update_video(row["id"], status="scheduled", youtube_id=result["id"], publish_at=publish_at, error=None)
    plan = {**plan, "youtube_thumbnail": _thumbnail(result["id"], row["id"], progress)}
    on_screen = shown(plan)
    db.mark_clips_used([c["key"] for c in on_screen["footage"] + on_screen["archive"] if c.get("key")])
    for clip in on_screen["footage"] + on_screen["archive"]:  # 50-150 MB a case; fetched again if ever needed
        (TMP_DIR / clip["file"]).unlink(missing_ok=True)
    animator.forget(row["id"])
    if reels_on():
        plan["instagram"] = {"status": "pending", "tries": 0}  # the video stays until the Reel is up
        if kept.in_cloud():  # (...kept with this run when it ends, for the Reels workflow: tools/kept.py)
            plan["instagram"]["kept_in"] = kept.this_run()
    else:
        out.unlink(missing_ok=True)
    db.update_video(row["id"], plan=plan)
    reel = " It goes on Instagram then too." if reels_on() else ""
    if live_now:
        notify.run(f"\U0001F3AC New case is live (the {when} slot):\n{meta['title']}\n{result['url']}")
    else:
        notify.run(f"\U0001F3AC New case goes live at {when}:{reel}\n{meta['title']}\n"
                   f"Watch, edit or delete it before then: {result['studio_url']}")
    return {"video_id": row["id"], "youtube_id": result["id"], "slot": slots.iso(slot), "publish_at": publish_at,
            "live_now": live_now, "title": meta["title"], "thumbnail": plan["youtube_thumbnail"].get("set")}


def _thumbnail(youtube_id: str, video_id: int, progress=log) -> dict:
    """The Animator's thumbnail on the YouTube video, if YouTube takes it (never fails the upload). The wide one:
    YouTube puts a Short's custom thumbnail in its 16:9 places, where the tall cover came out small between blurred
    copies of itself (2026-10-27); the tall one is only used if there's no wide one."""
    cover, wide = animator.thumb_paths(video_id)
    image = wide if wide.exists() else cover
    if not image.exists():
        return {"set": False, "why": "no thumbnail was made"}
    try:
        done = youtube_upload.set_thumbnail(youtube_id, image)
    except Exception as e:
        done = {"set": False, "why": str(e)[:200]}
    if not done["set"]:
        progress(f"YouTube kept its own thumbnail ({done.get('why', '')[:120]})")
    return {**done, "image": "wide" if image == wide else "cover", "at": db.now_iso()}


def resend_thumbnail(video_id: int, progress=log) -> dict:
    """Puts a case's thumbnail on its YouTube video again (e.g. the wide one on a Short that got the tall one)."""
    row = db.get_video(video_id)
    if not row or not row["youtube_id"]:
        raise ValueError(f"Short #{video_id} isn't on YouTube")
    done = _thumbnail(row["youtube_id"], video_id, progress)
    db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "youtube_thumbnail": done})
    return done


# --- Instagram -------------------------------------------------------------------------

def _turn(row: dict) -> str | None:
    """When a Short's Reel goes: its slot, or when it went public on YouTube if that was later (a late upload). A Short
    you put on YouTube early with Post now keeps its Reel for the slot."""
    return max(row["slot"] or "", row["publish_at"] or "") or None


def _posting(reel: dict) -> bool:
    """Is the Reel being posted right now (not one whose posting was cut off)?"""
    return reel.get("status") == "posting" and (reel.get("posting_at") or "") > db.now_iso(-POSTING_STALE)


def _remaking(reel: dict) -> bool:
    """Is the Reel's video being made again right now (remake_reel)?"""
    return reel.get("status") == "remaking" and (reel.get("remaking_at") or "") > db.now_iso(-POSTING_STALE)


def reels_due() -> list[dict]:
    """Shorts whose slot has come and whose Reel is still to post (and not waiting to try again)."""
    if not instagram.is_configured():
        return []
    now = db.now_iso()
    return [v for v in db.published_videos(days=REEL_DAYS)
            if (v["plan"].get("instagram") or {}).get("status") == "pending"
            and ((v["plan"].get("instagram") or {}).get("retry_at") or "") <= now and _turn(v) <= now]


def reels_coming(until: str) -> list[dict]:
    """Shorts whose Reel is still to post and comes due by `until` (its slot, or its next try)."""
    if not instagram.is_configured():
        return []
    return [v for v in db.scheduled_videos(days=REEL_DAYS)
            if (v["plan"].get("instagram") or {}).get("status") == "pending"
            and max(_turn(v) or "", v["plan"]["instagram"].get("retry_at") or "") <= until]


def _made_here() -> bool:
    """Whether Reels are posted and made again from here: a run in the cloud, or this computer while the database is
    its own (with the database in the cloud, this computer's dashboard only shows them)."""
    return kept.in_cloud() or not (env("DATABASE_URL") or env("POSTGRES_URL"))


def expire_reels(progress=log) -> list[int]:
    """REEL_DAYS after a Short's slot its video is deleted from this computer (only its Reel needed it): a Reel still
    waiting then (this computer was off) is given up; one that failed or that you took off can't be posted any more."""
    cutoff = db.now_iso(-timedelta(days=REEL_DAYS))
    expired = []
    for v in db.published_videos(days=30):
        reel = v["plan"].get("instagram") or {}
        if (not reel or reel.get("status") in ("posted", "deleted", "expired") or _posting(reel) or _remaking(reel)
                or _turn(v) >= cutoff):
            continue
        if reel.get("status") in ("pending", "posting"):
            db.update_video(v["id"], plan={**v["plan"], "instagram": {**reel, "status": "expired"}})
            expired.append(v["id"])
            progress(f"The Reel for Short #{v['id']} waited more than {REEL_DAYS} days and was given up")
        animator.remove(animator.preview_path(v["id"]))
    return expired


def _on_youtube(youtube_id: str) -> str:
    """Where the Short is on YouTube: "public"; "publishing" (still private with its publish time: YouTube makes it
    public a little after the minute); or "vetoed" (deleted, or kept private: no Reel then)."""
    items = youtube_auth.yt_get("videos", {"part": "status", "id": youtube_id}).get("items") or []
    status = items[0]["status"] if items else {}
    if status.get("privacyStatus") == "public":
        return "public"
    return "publishing" if status.get("publishAt") else "vetoed"


def _claim_reel(video_id: int, now: bool) -> tuple[dict | None, str | None]:
    """Marks a Short's Reel as being posted, so it goes up once whoever asks (the loop at its slot, or your Post now):
    the row as claimed and the Reel's status before, or None if it isn't for posting (posted or being posted already;
    at its slot, anything but waiting for it)."""
    with _reels:
        row = db.get_video(video_id)
        reel = (row["plan"].get("instagram") or {}) if row else {}
        before = reel.get("status")
        if not row or before == "posted" or _posting(reel) or (not now and before != "pending"):
            return None, before
        plan = {**row["plan"], "instagram": {**reel, "status": "posting", "posting_at": db.now_iso()}}
        db.update_video(video_id, plan=plan)
        return {**row, "plan": plan}, before


def post_reel(row: dict, progress=log, now: bool = False) -> dict:
    """Posts a Short to Instagram as a Reel: once its slot has come and it's public on YouTube, or at once when you
    press Post now (even before it's public on YouTube: your call). In the cloud a video kept by an earlier run is
    fetched from it first (tools/kept.py); one whose run is still going is left to that run, untouched."""
    video_id = row["id"]
    out = animator.preview_path(video_id)
    run = (row["plan"].get("instagram") or {}).get("kept_in")
    if run and not out.exists():
        if not kept.in_cloud():
            return {"video_id": video_id, "skipped": "its video is kept in the cloud, which posts its Reel"}
        if kept.still_running(run):
            progress(f"Short #{video_id}'s video is with run {run}, still going: that run posts its Reel")
            return {"video_id": video_id, "skipped": f"run {run}, which made it, is still going", "waits_for_run": run}
    row, before = _claim_reel(video_id, now)
    if not row:
        return {"video_id": video_id, "skipped": f"the Reel of Short #{video_id} is posted, or being posted, already"}
    plan = row["plan"]
    reel = {k: v for k, v in plan["instagram"].items() if k != "posting_at"}

    def done(status: str, **extra) -> dict:
        reel.update(status=status, **extra)
        db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "instagram": reel})
        if status == "posted":
            out.unlink(missing_ok=True)  # (a Reel that didn't go keeps it until REEL_DAYS after its slot, for Post now)
        return {"video_id": video_id, "instagram": status, **extra}

    def again(e: Exception, what: str) -> dict:
        """A try that didn't work: your Post now is tried once; at its slot it's tried again later (REEL_WAITS)."""
        if getattr(e, "link_refused", None):  # (why Instagram refused the temporary link before the sending failed)
            reel["link_refused"] = e.link_refused[:300]
        if now:  # your Post now: tried once; a Reel that was waiting for its slot still waits for it
            done("pending" if before == "pending" else "failed", error=str(e)[:300])
            raise RuntimeError(f"{what}: {e}") from e
        tries = int(reel.get("tries") or 0) + 1
        reel["tries"] = tries
        if tries < REEL_TRIES:
            wait = REEL_WAITS[tries - 1]
            progress(f"{what} ({e}); trying again in {wait} minutes")
            return done("pending", error=str(e)[:300], retry_at=db.now_iso(timedelta(minutes=wait)))
        notify.run(f"⚠️ Couldn't post to Instagram after {tries} tries: {plan['metadata']['title']}\n{e}")
        return done("failed", error=str(e)[:300])

    if run and not out.exists():
        progress(f"Getting Short #{video_id}'s video from run {run}, which kept it")
        try:
            kept.fetch(video_id, run, out)
        except FileNotFoundError as e:
            notify.run(f"⚠️ The Reel of \"{plan['metadata']['title']}\" can't be posted: {e}")
            return done("failed", error=str(e)[:300])
        except Exception as e:  # (GitHub or openssl, for now)
            return again(e, "Its video couldn't be fetched")
    if not out.exists():
        return done("failed", error="the video file was gone")
    where = "public" if now else _on_youtube(row["youtube_id"])
    if where == "publishing" and (row["publish_at"] or "") > db.now_iso(-PUBLISH_LAG):
        progress(f"YouTube hasn't made Short #{video_id} public yet; its Reel waits a few minutes more")
        return done("pending", retry_at=db.now_iso(timedelta(minutes=3)))  # (no try counted)
    if where != "public":
        progress(f"Short #{video_id} isn't public on YouTube (deleted or made private): no Reel")
        return done("skipped", error="not public on YouTube")
    meta = plan["metadata"]
    try:
        posted = instagram.publish(out, caption(meta, plan), float((plan.get("thumbnail") or {}).get("at") or 0),
                                   progress=progress)
    except Exception as e:
        return again(e, "Instagram didn't take it")
    notify.run(f"\U0001F4F8 On Instagram now: {meta['title']}" + (f"\n{posted['url']}" if posted.get("url") else ""))
    if posted.get("link_refused"):  # (sent instead: kept to find out why Instagram refused the temporary link)
        reel["link_refused"] = posted["link_refused"][:300]
    return done("posted", id=posted["id"], url=posted.get("url"), posted_at=db.now_iso(), error=None, retry_at=None)


def cancel_reel(video_id: int, because: str = "you took it off", keep_video: bool = True) -> bool:
    """Takes a Reel that isn't posted off Instagram's schedule: it isn't posted (your Post now still can while its video
    is kept). False if there's none to take off (none, posted, or being posted). Without keep_video its video goes too
    (the Short was stopped or deleted on YouTube, so no Reel is wanted)."""
    with _reels:
        row = db.get_video(video_id)
        reel = (row["plan"].get("instagram") or {}) if row else {}
        taken = reel.get("status") in ("pending", "posting", "failed", "skipped", "remaking") and not _posting(reel)
        if taken:
            kept = {k: v for k, v in reel.items() if k not in ("retry_at", "posting_at", "remaking_at")}
            db.update_video(video_id, plan={**row["plan"], "instagram": {**kept, "status": "cancelled", "because": because,
                                                                          "cancelled_at": db.now_iso()}})
        if row and not keep_video and not _posting(reel) and not _remaking(reel):  # (remake_reel clears its own)
            animator.remove(animator.preview_path(video_id))
    return taken


def drop_reel(video_id: int) -> dict:
    """Your Delete on a Short's Instagram side: a posted Reel is deleted from Instagram; one not posted yet is taken off
    (cancel_reel). ValueError if there's neither; InstagramError if Instagram refuses."""
    with _reels:
        row = db.get_video(video_id)
        reel = (row["plan"].get("instagram") or {}) if row else {}
        if reel.get("status") == "posted":
            done = instagram.delete(reel["id"])
            db.update_video(video_id, plan={**row["plan"], "instagram": {**reel, "status": "deleted",
                                                                          "deleted_at": db.now_iso()}})
            return {"video_id": video_id, "instagram": "deleted", **done}
        if cancel_reel(video_id):
            return {"video_id": video_id, "instagram": "cancelled"}
    raise ValueError("There's no Reel to delete or take off.")


def remake_reel(row: dict, progress=log) -> dict:
    """A Short that went up while Reels were off (its video wasn't kept) made again for Instagram: the same case, music
    and drawings, read again by the same voice (the first reading isn't kept either), so its Reel is the same Short in
    a new take. The Reel then waits for its slot; what's saved about the YouTube video stays as it was."""
    video_id = row["id"]
    with _reels:
        row = db.get_video(video_id)
        if not row or not platforms(row)["instagram"]["can"]["schedule"]:
            raise ValueError(f"Short #{video_id} can't be made again for Instagram (on the schedule, Instagram connected, "
                             "and no Reel waiting or posted)")
        before = row["plan"].get("instagram")
        db.update_video(video_id, plan={**row["plan"], "instagram": {**(before or {}), "status": "remaking",
                                                                      "remaking_at": db.now_iso()}})
    try:
        progress(f"Making Short #{video_id}'s video again for Instagram")
        made = animator.animate(row, animator.preview_path(video_id), progress, now=True, again=True)
    except Exception:
        with _reels:  # as it was before
            db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "instagram": before})
        raise
    with _reels:
        fresh = db.get_video(video_id)
        if (fresh["plan"].get("instagram") or {}).get("status") != "remaking":  # taken off meanwhile (deleted on YouTube)
            animator.remove(animator.preview_path(video_id))
            return {**made, "instagram": "cancelled"}
        db.update_video(video_id, plan={**fresh["plan"], "instagram": {"status": "pending", "tries": 0,
                                                                        "remade_at": db.now_iso()}})
    progress(f"Its Reel goes on Instagram at its slot ({slots.clock(slots.parse(_turn(fresh)), slots.plan())})")
    return {**made, "instagram": "pending"}


def platforms(row: dict, live: dict | None = None) -> dict:
    """Where a Short stands on YouTube and on Instagram, and which of your buttons work there now (the Schedule page's
    two parts; the dashboard's actions check the same). `live`: what YouTube said just now about the videos it was
    asked about (youtube_upload.statuses; None for one it doesn't have any more), to notice changes made in Studio."""
    now = db.now_iso()
    yid, status = row["youtube_id"], row["status"]
    public = status == "scheduled" and bool(row["publish_at"]) and row["publish_at"] <= now
    yt = {"state": "public" if public else status, "at": row["publish_at"], "url": None, "processing": False}
    if live is not None and yid in live and status == "scheduled":
        seen = live[yid]
        if not seen:
            yt["state"] = "gone"  # deleted in YouTube Studio
        elif seen["upload"] in ("rejected", "failed"):
            yt.update(state="rejected", why=seen.get("why"))
        elif seen["privacy"] == "public":
            yt["state"] = "public"  # (published early in YouTube Studio, if its time hasn't come)
        elif (public and row["publish_at"] < db.now_iso(-STUDIO_GRACE)) or (not public and not seen.get("publish_at")):
            yt.update(state="hidden", privacy=seen["privacy"])  # made private, or its publish time taken away, in Studio
        yt["processing"] = bool(seen) and seen["upload"] == "uploaded"
    there = bool(yid) and yt["state"] not in ("gone", "deleted")
    early = status == "scheduled" and not public
    if there:
        yt["url"] = (f"https://youtube.com/shorts/{yid}" if yt["state"] == "public"
                     else f"https://studio.youtube.com/video/{yid}/edit")
    yt["can"] = {"open": there, "now": early and there and yt["state"] not in ("public", "rejected"),
                 "stop": early and there, "delete": status == "scheduled" and bool(yid)}

    reel = row["plan"].get("instagram") or {}
    connected, video = instagram.is_configured(), animator.preview_path(row["id"]).exists()
    state, error = reel.get("status") or ("making" if status == "making" else "none"), reel.get("error")
    if state == "posting" and not _posting(reel):
        state, error = "failed", "its posting was cut off (the dashboard stopped)"
    if state == "remaking" and (reel.get("remaking_at") or "") <= db.now_iso(-POSTING_STALE):
        state = "none"  # (making it again was cut off: it can be scheduled again)
    at = _turn(row)
    if state == "pending":
        state = "waiting" if at and at > now else "retry" if (reel.get("retry_at") or "") > now else "due"
    why = ("Connect Instagram first (the Channels page)" if not connected
           else "It's on Instagram already" if state == "posted"
           else "It's being posted right now" if state == "posting"
           else "Its video is being made again for Instagram" if state == "remaking"
           else "It isn't on the schedule yet" if status != "scheduled"
           else None if video
           else "Its video is kept in the cloud, which posts its Reel at its slot"
           if reel.get("kept_in") and state in ("waiting", "due", "retry")
           else "Reels weren't on when it went up, so its video wasn't kept: Schedule makes it again" if state == "none"
           else f"Its video isn't kept any more (only until {REEL_DAYS} days after its slot)")
    username = env("INSTAGRAM_USERNAME")
    ig = {"state": state, "at": at, "url": reel.get("url"), "error": error, "retry_at": reel.get("retry_at"),
          "posted_at": reel.get("posted_at"), "because": reel.get("because"), "why": why,
          "profile": f"https://www.instagram.com/{username}/" if username else None,
          "can": {"open": state == "posted" and bool(reel.get("url") or username), "now": why is None,
                  "delete": (state == "posted" and connected)
                  or state in ("waiting", "due", "retry", "failed", "skipped", "remaking"),
                  "schedule": connected and status == "scheduled" and not video and _made_here()
                  and state in ("none", "cancelled", "expired", "failed", "skipped")}}
    return {"youtube": yt, "instagram": ig}


def run(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    return act("publisher", f"Upload Short #{row['id']}", upload, row, slot, sched, progress=progress)


def run_remake(row: dict, progress=log) -> dict:
    return act("animator", f"Make Short #{row['id']} again for Instagram", remake_reel, row, progress=progress)


def run_instagram(row: dict, progress=log, now: bool = False) -> dict:
    return act("publisher", f"Reel for Short #{row['id']}" + (" (Post now)" if now else ""), post_reel, row,
               progress=progress, now=now)
