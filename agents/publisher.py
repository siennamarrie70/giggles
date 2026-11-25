"""
Agent 5, Publisher: puts each video on YouTube in its slot (your plan of 2026-11-23, tools/slots.py): a Short (a story of
2-3 minutes, upright) as a YouTube Short, and as a Reel on Instagram at the same time; a long story (3-4 minutes) as an
ordinary video with its thumbnail. (A story made before the plan went up with its short version a few hours after it.)

It takes the oldest story that's ready: written in the look of now and not held by the Reviewer (choose()). Its film must
have passed the Reviewer (Agent 4): without a reviewed film, the Animator makes it and the Reviewer reviews it first, fixes
included (agents/reviewer.py, reviewed()). A film the Reviewer turns down after the fixes is never posted as it is:
it's made again by itself until it passes (agents/reviewer.py hold()), then takes a slot.

YouTube: the film is uploaded as private with the slot as its publish time, so YouTube makes it public on the minute; a
slot only minutes away, or already passed, goes up public at once. An ordinary video (Film & Animation, series.category_id;
no #shorts), "not made for kids", no synthetic-media label (it's animated: nothing a viewer could take for real footage),
its description carrying the story's two lines, its chapters (one at each part), how it was made and the music's credit
(the CC BY licence asks for it). Then its thumbnail (the Animator's wide one; custom thumbnails need a channel verified by
phone). A Short goes up the same way at its slot, with #shorts and without chapters or a thumbnail. (Until 2026-11-23 a
film's short version went up as a Short series.short_after_hours after it; one YouTube refused can still be sent again
from the dashboard while its file is on this computer: upload_short.)

Instagram (when it's connected and switched on: settings `instagram.enabled`): at a Short's time (a story made before the
plan: its short version's), if it's public on YouTube (not deleted there: that's still the veto), it goes up as a Reel (tools/instagram.py; Instagram
can't schedule them), its cover the moment its title is in, with a caption made from the same description. A failed try
waits longer each time (REEL_WAITS: Instagram drops uploads in spells), about nine hours in all. The short version is
kept on this computer until the Reel is up, or REEL_DAYS after its time. In the cloud (GitHub Actions, whose machine is wiped after each run) a Reel whose time comes while the run
that made it is still going is posted by that run (tools/jobs.py, morning); the others' videos are kept, encrypted, with
that run (tools/kept.py: the Reel records it as `kept_in`), and the Reels workflow (.github/workflows/reels.yml) fetches
each at its time. With the database in the cloud, this computer's dashboard only shows Reels: it neither posts nor makes
them again (_made_here).

When Meta refuses the connection itself, not one video (the token, its permissions, the Meta app or the account:
tools/instagram.py Disconnected), no Reel can go up until that's fixed. Then every Reel still to post waits for it with no
try counted (_hold_reels), the connection is asked again every DOWN_RECHECK with one harmless read, and once a Reel goes up
the others follow at once (_came_back). You're told: the dashboard's Overview page says so while it lasts, and a Reels run
fails once a day (DOWN_RETELL; tools/jobs.py reels), so GitHub emails you. Seen 2026-10-29, when Meta blocked the app.

Beside each story the Schedule page shows where it stands on YouTube and on Instagram (platforms()) with your buttons for
each. YouTube: Open, Post now (public at once; its slot stays its own and its Reel still waits for its short version's
time), Stop and Delete (take_off: the film and its short version both; a Reel not posted yet goes with them). Instagram:
Open, Post now, Delete. A Reel is claimed ("posting") before it's posted, so it goes up once whoever asks. A story that
went up while Reels were off has no short version kept: Schedule (remake_reel) makes it again for Instagram (only the
short version: the film is on YouTube), and its Reel then waits for its time.

On a failed upload the story goes back to the queue for one more try (its reviewed film kept), then counts as failed. Until
it goes public you can still delete it in YouTube Studio: that's the veto.

Usage:
    python tools/jobs.py publish        # Agent 5 uploads the oldest ready story into the next open slot
    python tools/jobs.py instagram      # ...and posts the Reels whose time has come
"""

import threading
from datetime import datetime, timedelta, timezone

import db
import instagram
import kept
import llm
import notify
import series
import slots
import story_film
import youtube_auth
import youtube_upload
from agents import animator, reviewer
from agents.base import act, log, playbook
from common import env, load_config

GO_LIVE_MARGIN = timedelta(minutes=3)  # closer than this to its slot, a story is uploaded as public right away
WEAK_HASHTAG = 0.7                     # a hashtag this far below the channel's usual is dropped
REEL_WAITS = (10, 20, 40, 60, 90, 120, 180)  # minutes before the next try of a Reel Instagram didn't take, by try
REEL_TRIES = len(REEL_WAITS) + 1
REEL_DAYS = 2                          # a Reel not posted within this long after its time is given up (its video deleted)
KEPT_SAFE = timedelta(days=2, hours=12)  # a cloud run's kept files are surely there this long (GitHub keeps them 3 days)
REEL_AFTER = timedelta(hours=12)         # a Reel's video must be there until this long after its time (its tries)
REKEEP_WITHIN = timedelta(hours=12)      # a kept copy that goes before then is kept again by a run within this of going
KEEP_RETRY = timedelta(hours=6)          # a Reel's video that couldn't be drawn again isn't tried again before this
REKEEP_MOST = 3                          # Reels' videos drawn again in one cloud run (each takes minutes)
VIDEO_WAIT = timedelta(minutes=30)       # a Reel whose video isn't kept anywhere yet looks again this long later
POSTING_STALE = timedelta(minutes=30)  # a Reel "posting" for longer was cut off (the dashboard stopped)
STUDIO_GRACE = timedelta(minutes=5)    # still private this long after its time: made private in YouTube Studio
PUBLISH_LAG = timedelta(minutes=30)    # a Reel waits this long for YouTube to make its Short public (it's a little late)
DOWN_RECHECK = timedelta(minutes=30)   # while Meta refuses Instagram's connection, it's asked again this often
DOWN_RETELL = timedelta(hours=24)      # ...and a Reels run fails this often meanwhile, so GitHub emails you
MADE_WITH = ("Animated in code, frame by frame: no AI pictures, no AI voice. "
             "Sounds: CC0 recordings (Freesound, Openverse).")
_reels = threading.RLock()             # one claim at a time, so a Reel goes up once whoever asks


def choose(form: str | None = None) -> dict | None:
    """The story that takes the next slot (of `form`: a Short's or a long story's): the oldest one of that form ready to
    go up and written in the look of now (an older row, made by an earlier version of the channel, is never uploaded:
    series.current)."""
    return next((v for v in db.planned_videos() if db.ready(v) and series.current(v)
                 and form in (None, series.form_of(v))), None)


# --- the description -----------------------------------------------------------------------------------------------------

def hashtags(tags: list[str]) -> list[str]:
    """The story's hashtags without any the playbook shows doing clearly worse than usual (never the channel's own
    hashtags from the settings, and always at least two)."""
    lifts = (playbook().get("weights") or {}).get("hashtag") or {}
    base = set(series.settings().get("hashtags") or [])
    kept_tags = [t for t in tags if t in base or lifts.get(t.lower(), 1.0) > WEAK_HASHTAG]
    return kept_tags if len(kept_tags) >= 2 else tags


def description(meta: dict, plan: dict, links: bool = True) -> str:
    """A story's description: its two lines, its chapters (YouTube makes them from times starting at 0:00), how it was
    made, the music's credit, and the hashtags (never #shorts on the film). Without links (Instagram's caption) the
    chapters are left out."""
    parts = [meta.get("description") or ""]
    marks = (plan.get("render") or {}).get("chapters") or []
    if links and len(marks) >= 3:
        parts.append("\n".join(f"{story_film.clock(c['at'])} {c['name']}" for c in marks))
    parts.append(MADE_WITH)
    parts += [c for c in plan.get("credits") or [] if c]   # (the music's CC BY credit)
    if meta.get("hashtags"):
        parts.append(" ".join(t for t in hashtags(meta["hashtags"]) if t.lower() != "#shorts")[:300])
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def short_description(meta: dict, plan: dict, youtube_id: str) -> str:
    """The short version's description (the Short): the story's lines, a link to the whole film, how it was made, the
    music's credit (CC BY asks for it on every video it plays in) and the hashtags with #shorts."""
    tags = " ".join(["#shorts", *[t for t in hashtags(meta.get("hashtags") or []) if t.lower() != "#shorts"]])
    low, high = series.minutes()
    return "\n\n".join(p.strip() for p in [meta.get("description") or "",
                                             f"The full story ({low:g}-{high:g} min): https://www.youtube.com/watch?v={youtube_id}",
                                             MADE_WITH, *[c for c in plan.get("credits") or [] if c], tags[:300]]
                       if p and p.strip())


def short_story_description(meta: dict, plan: dict) -> str:
    """A Short's description (a story of its own since 2026-11-23): its lines, how it was made, the music's credit (CC BY
    asks for it on every video it plays in) and the hashtags with #shorts; no chapters (a Short shows none)."""
    tags = " ".join(["#shorts", *[t for t in hashtags(meta.get("hashtags") or []) if t.lower() != "#shorts"]])
    return "\n\n".join(p.strip() for p in [meta.get("description") or "", MADE_WITH,
                                             *[c for c in plan.get("credits") or [] if c], tags[:300]] if p and p.strip())


def caption(meta: dict, plan: dict) -> str:
    """The Reel's caption: the title, then the description without the chapters, within Instagram's limit."""
    return f"{meta['title']}\n\n{description(meta, plan, links=False)}"[:instagram.CAPTION_CHARS]


def reels_enabled() -> bool:
    """Reels switched on in the settings (whether Instagram's keys are here or not: the cloud's hourly check has none)."""
    return bool((load_config().get("instagram") or {}).get("enabled"))


def reels_on() -> bool:
    return reels_enabled() and instagram.is_configured()


# --- YouTube ---------------------------------------------------------------------------------------------------------------

def upload(row: dict, slot: datetime, sched: dict, progress=log) -> dict:
    """A story claimed for `slot`, made and reviewed now if needed, uploaded for the slot. A Short (plan "form"): as a
    YouTube Short, its Reel set for the same minute (its video kept for it). A long story: the film with its thumbnail
    (no short version since the plan of 2026-11-23). A story the Reviewer turns down gives the slot back and is made
    again by itself later (agents/reviewer.py hold()); nothing of it goes to YouTube meanwhile."""
    settings = series.settings()
    out = animator.preview_path(row["id"])
    when = slots.clock(slot, sched)
    form = series.form_of(row)
    word = slots.FORM_WORDS[form]
    _fetch_kept(row, progress)
    try:
        row = reviewer.reviewed(row, progress=progress, now=True)
        if not reviewer.passed(row["plan"]):
            db.update_video(row["id"], status="planned", slot=None, claimed_at=None)
            return {"skipped": f"the Reviewer turned story #{row['id']} down (it's made again by itself); the {when} "
                               "slot waits for the next story", "video_id": row["id"], "held": True}
        plan = row["plan"]
        meta = plan["metadata"]
        db.update_video(row["id"], claimed_at=db.now_iso())
        live_now = slot - datetime.now(timezone.utc) <= GO_LIVE_MARGIN
        what = "the Short" if form == "short" else "the film"
        progress(f"Uploading {what} to YouTube, public right away" if live_now
                 else f"Uploading {what} to YouTube, scheduled for {when}")
        text = short_story_description(meta, plan) if form == "short" else description(meta, plan)
        result = youtube_upload.run(out, meta["title"], text, meta["tags"],
                                    publish_at=None if live_now else slots.iso(slot), public=live_now,
                                    category_id=str(settings.get("category_id") or "1"),
                                    language=str(settings.get("language") or "en"), synthetic_media=False)
    except Exception as e:
        if isinstance(e, (animator.Resting, youtube_upload.UploadLimit)) or llm.down(e):  # not the story's fault: it
            db.update_video(row["id"], status="planned", slot=None, claimed_at=None)  # waits for Gemini (its voice, or
            raise                                                    # no model could answer) or YouTube's upload limit
        attempts = row["attempts"] + 1
        status = "planned" if attempts < 2 else "failed"
        db.update_video(row["id"], status=status, attempts=attempts, error=str(e)[:500], slot=None, claimed_at=None)
        outcome = "it goes back to the queue for another try" if status == "planned" else "gave up after 2 tries"
        raise RuntimeError(f"Story #{row['id']} for {when} not uploaded ({outcome}): {e}") from e
    now = datetime.now(timezone.utc)
    publish_at = slots.iso(now) if live_now else slots.iso(slot)
    db.update_video(row["id"], status="scheduled", youtube_id=result["id"], publish_at=publish_at, error=None)
    plan, note = dict(plan), ""
    if form == "short":  # its Reel: the same video, at the same minute (kept for it until it's posted)
        if reels_on():
            plan["instagram"] = {"status": "pending", "tries": 0, "at": publish_at, "youtube_id": result["id"]}
            if kept.in_cloud():  # (...kept with this run when it ends, for the Reels workflow: tools/kept.py)
                plan["instagram"]["kept_in"] = kept.this_run()
            note = "\nIts Reel goes on Instagram at the same time."
    else:
        plan["youtube_thumbnail"] = _thumbnail(result["id"], row["id"], progress)
    animator.forget(row["id"])
    if not plan.get("instagram"):
        animator.remove(out)  # (it's on YouTube)
    animator.remove(animator.short_path(row["id"]))  # (a short version made before the plan: not posted any more)
    db.update_video(row["id"], plan=plan)
    watch = f"https://www.youtube.com/watch?v={result['id']}"
    whose = slots.day_word(slot, sched)  # ("Tomorrow's" for a story made as soon as its slot was free)
    if live_now:
        notify.run(f"\U0001F3AC {whose} {word} is live (the {when} slot):\n{meta['title']}\n{watch}{note}")
    else:
        notify.run(f"\U0001F3AC {whose} {word} goes live at {when}:\n{meta['title']}\nWatch, edit or delete it before "
                   f"then: {result['studio_url']}{note}")
    return {"video_id": row["id"], "youtube_id": result["id"], "slot": slots.iso(slot), "publish_at": publish_at,
            "live_now": live_now, "title": meta["title"], "form": form,
            "thumbnail": (plan.get("youtube_thumbnail") or {}).get("set"), "short": None, "short_at": None}


def _send_short(video_id: int, meta: dict, plan: dict, film_id: str, at: datetime, progress=log) -> dict:
    """The story's short version uploaded as a Short, public at `at` (tried twice); what happened, for the story's plan."""
    path = animator.short_path(video_id)
    if not path.exists():
        return {"status": "failed", "error": "the short version wasn't made", "publish_at": slots.iso(at)}
    settings = series.settings()
    last = None
    for attempt in range(2):
        try:
            progress(f"Uploading the short version as a Short, public at {slots.clock(at, slots.plan())}")
            short = youtube_upload.run(path, meta["title"], short_description(meta, plan, film_id), meta["tags"],
                                       publish_at=slots.iso(at), category_id=str(settings.get("category_id") or "1"),
                                       language=str(settings.get("language") or "en"), synthetic_media=False)
            return {"status": "scheduled", "youtube_id": short["id"], "publish_at": slots.iso(at), "at": db.now_iso()}
        except youtube_upload.UploadLimit as e:
            last = e
            break
        except Exception as e:
            last = e
    progress(f"The short version wasn't uploaded ({str(last)[:160]})")
    return {"status": "failed", "error": str(last)[:300], "publish_at": slots.iso(at)}


def upload_short(video_id: int, progress=log) -> dict:
    """Your "Send the short version" on a story whose short version didn't go up with its film: uploaded now, public at
    its time (or in a few minutes if that has passed); its Reel is set for then."""
    row = db.get_video(video_id)
    if not row or not series.is_story(row) or not row["youtube_id"]:
        raise ValueError(f"Story #{video_id} isn't on YouTube")
    plan = row["plan"]
    if (plan.get("short_upload") or {}).get("youtube_id"):
        raise ValueError("Its short version is on YouTube already")
    at = max(slots.parse((plan.get("short_upload") or {}).get("publish_at") or slots.iso(datetime.now(timezone.utc))),
             datetime.now(timezone.utc) + timedelta(minutes=10))
    sent = _send_short(video_id, plan["metadata"], plan, row["youtube_id"], at, progress)
    plan = {**db.get_video(video_id)["plan"], "short_upload": sent}
    if sent.get("youtube_id") and reels_on():
        plan["instagram"] = {"status": "pending", "tries": 0, "at": sent["publish_at"], "youtube_id": sent["youtube_id"]}
    db.update_video(video_id, plan=plan)
    if not sent.get("youtube_id"):
        raise RuntimeError(f"YouTube didn't take the short version: {sent.get('error')}")
    return {"video_id": video_id, **sent}


def take_off(video_id: int, action: str) -> dict:
    """Your Stop or Delete on a scheduled story: the film and its short version both, on YouTube ("stop": kept as
    private, never public by itself; "delete": gone for good), its slot freed and its Reel not posted. Returns the
    story's new status ("stopped" or "deleted") and what YouTube said of each. youtube_upload.NotAllowed when YouTube
    hasn't let this app change videos yet."""
    row = db.get_video(video_id)
    if not row or row["status"] != "scheduled" or not row["youtube_id"]:
        raise ValueError("Only a story on the schedule can be changed here.")
    act_on = {"stop": youtube_upload.unschedule, "delete": youtube_upload.delete}[action]
    film = act_on(row["youtube_id"])
    key = "short_upload" if row["plan"].get("short_upload") else "teaser_upload"  # (teaser: a story before 2026-11-16)
    short_id = (row["plan"].get(key) or {}).get("youtube_id")
    short = act_on(short_id) if short_id else None
    was = {"at": db.now_iso(), "slot": row["slot"], "publish_at": row["publish_at"]}
    status = "deleted" if action == "delete" or film.get("gone") else "stopped"
    plan = {**row["plan"], status: was}
    if short is not None:
        plan[key] = {**plan[key], status: db.now_iso()}
    db.update_video(video_id, status=status, slot=None, publish_at=None, plan=plan)
    cancel_reel(video_id, because=f"{status} on YouTube", keep_video=False)
    return {"video_id": video_id, "status": status, "film": film, "short": short}


def kept_files(video_id: int, every: bool = False) -> list:
    """A story's files a cloud run keeps when it ends before the story is uploaded: (name, file) for kept.keep_files.
    `every`: all a run may have kept (to fetch them on a machine that has none of them), not only those here."""
    short = animator.short_path(video_id)
    return [(p.name, p) for p in (animator.preview_path(video_id), *animator.thumb_paths(video_id))] + (
        [(short.name, short)] if every or short.exists() else [])


def _fetch_kept(row: dict, progress=log) -> None:
    """In the cloud, a story made and reviewed by an earlier run that ended before YouTube took it (its daily upload
    limit) is fetched from that run, with its thumbnail and short version, so it isn't made again. If it can't be,
    it's made again as before."""
    kept_by = row["plan"].get("kept_video") or {}
    out = animator.preview_path(row["id"])
    if (out.exists() or not kept_by.get("run") or not kept.in_cloud()
            or kept_by.get("render") != (row["plan"].get("render") or {}).get("id")):
        return
    try:
        kept.fetch(row["id"], kept_by["run"], out)
    except Exception as e:
        progress(f"Story #{row['id']}'s film kept by run {kept_by['run']} couldn't be fetched ({str(e)[:150]}): it's "
                 "made again")
        return
    for name, file in kept_files(row["id"], every=True)[1:]:
        try:
            kept.fetch_file(kept_by["run"], name, file)
        except Exception:  # (without its thumbnail, YouTube shows a frame it picks; without its short version, that's
            pass           # made again before the upload: agents/reviewer.py reviewed)
    progress(f"Story #{row['id']}'s film, made by run {kept_by['run']} before YouTube's upload limit, fetched from it")


def _thumbnail(youtube_id: str, video_id: int, progress=log) -> dict:
    """The Animator's thumbnail on the YouTube film, if YouTube takes it (never fails the upload)."""
    _, wide = animator.thumb_paths(video_id)
    if not wide.exists():
        return {"set": False, "why": "no thumbnail was made"}
    try:
        done = youtube_upload.set_thumbnail(youtube_id, wide)
    except Exception as e:
        done = {"set": False, "why": str(e)[:200]}
    if not done["set"]:
        progress(f"YouTube kept its own thumbnail ({done.get('why', '')[:120]})")
    return {**done, "image": "wide", "at": db.now_iso()}


def resend_thumbnail(video_id: int, progress=log) -> dict:
    """Puts a story's thumbnail on its YouTube film again."""
    row = db.get_video(video_id)
    if not row or not row["youtube_id"]:
        raise ValueError(f"Story #{video_id} isn't on YouTube")
    done = _thumbnail(row["youtube_id"], video_id, progress)
    db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "youtube_thumbnail": done})
    return done


# --- Instagram -------------------------------------------------------------------------

def _turn(row: dict) -> str | None:
    """When a story's Reel goes: at its short version's time (instagram.at), or its slot or publish time if that's
    later."""
    return max(row["slot"] or "", row["publish_at"] or "", ((row.get("plan") or {}).get("instagram") or {}).get("at") or "") or None


def _posting(reel: dict) -> bool:
    """Is the Reel being posted right now (not one whose posting was cut off)?"""
    return reel.get("status") == "posting" and (reel.get("posting_at") or "") > db.now_iso(-POSTING_STALE)


def _remaking(reel: dict) -> bool:
    """Is the Reel's video being made again right now (remake_reel)?"""
    return reel.get("status") == "remaking" and (reel.get("remaking_at") or "") > db.now_iso(-POSTING_STALE)


def reels_to_keep() -> list[dict]:
    """The Reels still to post whose video no cloud run keeps until after their time (tools/kept.py), soonest first: a
    Short made and uploaded on the laptop (its video never reached GitHub), or one whose kept copy goes (KEPT_SAFE after
    it was kept) before REEL_AFTER past its time, once that is within REKEEP_WITHIN. One that couldn't be drawn again
    waits KEEP_RETRY. The database only: the cloud's hourly check asks it (jobs.due)."""
    now = datetime.now(timezone.utc)
    out = []
    for v in db.scheduled_videos(days=REEL_DAYS, parts=("instagram", "form")):
        reel = v["plan"].get("instagram") or {}
        if reel.get("status") != "pending" or not reel.get("at"):
            continue
        if reel.get("keep_failed_at") and now - slots.parse(reel["keep_failed_at"]) < KEEP_RETRY:
            continue
        if reel.get("kept_in"):
            gone = slots.parse(reel.get("kept_at") or v.get("created_at") or reel["at"]) + KEPT_SAFE
            if gone >= slots.parse(reel["at"]) + REEL_AFTER or gone - now > REKEEP_WITHIN:
                continue  # (kept long enough; or it goes later: kept again nearer the time)
        out.append(v)
    return sorted(out, key=lambda v: v["plan"]["instagram"]["at"])


def _draw_reel(row: dict, progress=log) -> dict:
    """A Reel's video drawn again from its story as it is on YouTube (nothing saved: what's recorded about the YouTube
    video stays as it was): a Short's own video, upright, or an older story's short version."""
    if series.form_of(row) == "short":
        plan = row["plan"]
        drawn = story_film.make({**plan["story"], "form": "short"}, animator.reel_path(row), progress,
                                beds=animator._beds(plan.get("fixes") or {}))
        return {"video_id": row["id"], "short": drawn["seconds"], "readings": 0, "voice": None}
    return animator.make_short(row, progress, now=True, again=True)


def keep_reels(progress=log) -> list[int]:
    """In a cloud run, before its story: each Reel reels_to_keep() names gets its video on this machine - fetched from
    the run that kept it, or drawn again from its story when no run has it (_draw_reel) - and this run keeps it
    (jobs.keep_videos at its end; _reels_beside posts one whose time comes meanwhile). At most REKEEP_MOST drawn again
    in one run. Returns the stories this run now keeps."""
    run = kept.this_run()
    if not run:
        return []
    kept_now, drawn = [], 0
    for row in reels_to_keep():
        vid, old = row["id"], (row["plan"].get("instagram") or {}).get("kept_in")
        if old and old != run and kept.still_running(old):
            continue  # (that run keeps it when it ends)
        out = animator.reel_path(row)
        try:
            if not out.exists() and old and old != run:
                try:
                    kept.fetch(vid, old, out)
                    progress(f"Story #{vid}'s Reel video fetched from run {old} and kept again, before GitHub deletes it")
                except FileNotFoundError:
                    pass  # (gone: drawn again below)
            if not out.exists():
                if drawn >= REKEEP_MOST:
                    continue
                drawn += 1
                progress(f"Story #{vid}'s Reel has no kept video (made on the laptop, or its kept copy is gone): "
                         "drawing it again from its story")
                _draw_reel(db.get_video(vid), progress)
        except Exception as e:  # (one Reel's trouble doesn't stop the others, nor the run)
            progress(f"Story #{vid}'s Reel video couldn't be drawn again ({type(e).__name__}: {str(e)[:160]}); "
                     "a later run tries again")
            with _reels:
                fresh = db.get_video(vid)
                reel = fresh["plan"].get("instagram") or {}
                if reel.get("status") == "pending":
                    db.update_video(vid, plan={**fresh["plan"], "instagram": {**reel, "keep_failed_at": db.now_iso()}})
            continue
        with _reels:
            fresh = db.get_video(vid)
            reel = fresh["plan"].get("instagram") or {}
            if reel.get("status") != "pending":  # (posted, taken off or deleted meanwhile)
                continue
            reel = {k: x for k, x in reel.items() if k != "keep_failed_at"}
            db.update_video(vid, plan={**fresh["plan"], "instagram": {**reel, "kept_in": run, "kept_at": db.now_iso()}})
        kept_now.append(vid)
    if kept_now:
        progress("Reels whose video this run keeps for Instagram: " + ", ".join(f"#{i}" for i in kept_now))
    return kept_now


def reels_due() -> list[dict]:
    """Stories whose Reel's time has come and is still to post (and not waiting to try again)."""
    if not instagram.is_configured():
        return []
    now = db.now_iso()
    return [v for v in db.published_videos(days=REEL_DAYS, parts=("instagram", "form"))
            if (v["plan"].get("instagram") or {}).get("status") == "pending"
            and ((v["plan"].get("instagram") or {}).get("retry_at") or "") <= now and _turn(v) <= now]


def reels_coming(until: str) -> list[dict]:
    """Stories whose Reel is still to post and comes due by `until` (its time, or its next try)."""
    if not instagram.is_configured():
        return []
    return [v for v in db.scheduled_videos(days=REEL_DAYS, parts=("instagram", "form"))
            if (v["plan"].get("instagram") or {}).get("status") == "pending" and reel_due_at(v) <= until]


def reel_due_at(row: dict) -> str:
    """When a Reel still to post comes due: its time, or its next try ("" if neither)."""
    turn = max(row.get("slot") or "", row.get("publish_at") or "",  # (as _turn, without raising on a partial row)
               ((row.get("plan") or {}).get("instagram") or {}).get("at") or "")
    return max(turn, ((row.get("plan") or {}).get("instagram") or {}).get("retry_at") or "")


def _made_here() -> bool:
    """Whether Reels are posted and made again from here: a run in the cloud, or this computer while the database is
    its own (with the database in the cloud, this computer's dashboard only shows them)."""
    return kept.in_cloud() or not (env("DATABASE_URL") or env("POSTGRES_URL"))


def expire_reels(progress=log) -> list[int]:
    """REEL_DAYS after a story's Reel time its short version is deleted from this computer (only its Reel needed it): a
    Reel still waiting then (this computer was off) is given up; one that failed or that you took off can't be posted any
    more."""
    cutoff = db.now_iso(-timedelta(days=REEL_DAYS))
    expired = []
    for v in db.published_videos(days=30, parts=("instagram", "form")):
        reel = v["plan"].get("instagram") or {}
        if (not reel or reel.get("status") in ("posted", "deleted", "expired") or _posting(reel) or _remaking(reel)
                or _turn(v) >= cutoff):
            continue
        if reel.get("status") in ("pending", "posting"):
            whole = db.get_video(v["id"])  # (the whole story, as it is now)
            reel = ((whole or {}).get("plan") or {}).get("instagram") or {}
            if whole and reel.get("status") in ("pending", "posting") and not _posting(reel):
                db.update_video(v["id"], plan={**whole["plan"], "instagram": {**reel, "status": "expired"}})
                expired.append(v["id"])
                progress(f"The Reel for story #{v['id']} waited more than {REEL_DAYS} days and was given up")
        animator.remove(animator.reel_path(v))
    return expired


def _on_youtube(youtube_id: str) -> str:
    """Where a video is on YouTube: "public"; "publishing" (still private with its publish time: YouTube makes it public a
    little after the minute); or "vetoed" (deleted, or kept private: no Reel then)."""
    items = youtube_auth.yt_get("videos", {"part": "status", "id": youtube_id}).get("items") or []
    status = items[0]["status"] if items else {}
    if status.get("privacyStatus") == "public":
        return "public"
    return "publishing" if status.get("publishAt") else "vetoed"


def instagram_down() -> dict | None:
    """While Meta refuses Instagram's connection (no Reel can go up): since when, why in Meta's words, and when it was
    last asked ("checked"). None while it works."""
    note = db.latest_note("instagram_down") or {}
    return note if note.get("since") else None


def _hold_reels(until: str | None) -> list[int]:
    """Every Reel still to post waits until `until` (None: it's due now) with its tries back to none, and one given up
    only because Meta refused the connection comes back: a refused connection isn't its video's fault."""
    held = []
    for v in db.scheduled_videos(days=REEL_DAYS, parts=("instagram", "form")):
        if (v["plan"].get("instagram") or {}).get("status") not in ("pending", "failed"):
            continue
        v = db.get_video(v["id"])  # (as it is now: another run may have just claimed it)
        reel = v["plan"].get("instagram") or {}
        lost = reel.get("status") == "failed" and instagram.refused_connection(reel.get("error"))
        if reel.get("status") == "pending" or lost:
            db.update_video(v["id"], plan={**v["plan"], "instagram": {**reel, "status": "pending", "tries": 0,
                                                                      "retry_at": until}})
            held.append(v["id"])
    return held


def _when(text: str) -> str:
    sched = slots.plan()
    return f"{slots.parse(text).astimezone(sched['tz']):%d %b %H:%M} ({sched['tz']})"


def down_message(down: dict) -> str:
    """What you're told while Meta refuses Instagram's connection."""
    return (f"Instagram has taken no Reels since {_when(down['since'])}: Meta refuses the connection "
            f"({down['error']}). The Reels wait (none is given up for this, until {REEL_DAYS} days after its time) and go "
            "up by themselves once it works again. To fix it: developers.facebook.com, My Apps, your app: it shows whether "
            "Meta blocked or restricted it, and why. With a new app or token, connect Instagram again on the dashboard's "
            "Channels page (workflows/setup_accounts.md, Instagram).")


def _went_down(error, progress=log) -> dict:
    """Meta refused the connection: recorded (instagram_down), every Reel waits for it (_hold_reels) until it's asked
    again after DOWN_RECHECK, and you're told the first time."""
    with _reels:
        before = instagram_down()
        down = {**(before or {"since": db.now_iso()}), "error": str(error)[:300], "checked": db.now_iso()}
        db.keep_note("instagram_down", down)
        _hold_reels(db.now_iso(DOWN_RECHECK))
    if not before:
        progress(f"Meta refuses Instagram's connection ({str(error)[:200]}): every Reel waits for it")
        notify.run(f"⚠️ {down_message(down)}")
    return down


def _came_back(progress=log) -> None:
    """A Reel went up while the connection was recorded as refused: it works again, and the Reels that waited are due
    now."""
    with _reels:
        down = instagram_down()
        if not down:
            return
        db.keep_note("instagram_down", {"since": None, "was": down, "back": db.now_iso()})
        waited = _hold_reels(None)
    progress(f"Instagram takes Reels again: {len(waited)} more waited, due now")
    notify.run(f"✅ Instagram takes Reels again (refused since {_when(down['since'])}): the {len(waited)} that waited "
               "go up now.")


def reconnected() -> None:
    """You connected Instagram again: if its connection was refused, the Reels waiting for it try again at once with
    the new token (not DOWN_RECHECK after the last ask)."""
    with _reels:
        down = instagram_down()
        if down:
            db.keep_note("instagram_down", {**down, "checked": ""})
            _hold_reels(None)


def tell_down() -> dict | None:
    """The refused connection if you haven't been told about it for DOWN_RETELL (now marked told), else None."""
    with _reels:
        down = instagram_down()
        if not down or (down.get("told") or "") > db.now_iso(-DOWN_RETELL):
            return None
        db.keep_note("instagram_down", {**down, "told": db.now_iso()})
        return down


def _still_refused(progress=log) -> dict | None:
    """Whether a Reel must still wait for Instagram's connection: while it's recorded as refused, until DOWN_RECHECK
    after it was last asked; then one harmless read asks again. Still refused: every Reel waits on. The read works (or
    can't tell): this Reel tries for real (None), and once one goes up the others follow (_came_back)."""
    down = instagram_down()
    if not down:
        return None
    if (down.get("checked") or "") > db.now_iso(-DOWN_RECHECK):
        return down
    try:
        why = instagram.check()
    except Exception:  # (Meta unreachable, or another answer)
        return None
    return _went_down(why, progress) if why else None


def _claim_reel(video_id: int, now: bool) -> tuple[dict | None, str | None]:
    """Marks a story's Reel as being posted, so it goes up once whoever asks (the loop at its time, or your Post now):
    the row as claimed and the Reel's status before, or None if it isn't for posting (posted or being posted already;
    at its time, anything but waiting for it)."""
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
    """Posts a story's short version to Instagram as a Reel: once its time has come and its Short is public on YouTube,
    or at once when you press Post now (even before it's public on YouTube: your call). Its cover is the moment its title
    is in. In the cloud a short version kept by an earlier run is fetched from it first (tools/kept.py); one whose run is
    still going is left to that run, untouched. While Meta refuses Instagram's connection it waits, untouched, except for
    your Post now, which tries anyway."""
    video_id = row["id"]
    out = animator.reel_path(row)
    run = (row["plan"].get("instagram") or {}).get("kept_in")
    if run and not out.exists():
        if not kept.in_cloud():
            return {"video_id": video_id, "skipped": "its video is kept in the cloud, which posts its Reel"}
        if kept.still_running(run):
            progress(f"Story #{video_id}'s short version is with run {run}, still going: that run posts its Reel")
            return {"video_id": video_id, "skipped": f"run {run}, which made it, is still going", "waits_for_run": run}
    if not now and (down := _still_refused(progress)):
        return {"video_id": video_id, "skipped": f"Meta refuses Instagram's connection ({down['error'][:150]})",
                "waits_for_instagram": True}
    row, before = _claim_reel(video_id, now)
    if not row:
        return {"video_id": video_id, "skipped": f"the Reel of story #{video_id} is posted, or being posted, already"}
    plan = row["plan"]
    reel = {k: v for k, v in plan["instagram"].items() if k != "posting_at"}

    def done(status: str, **extra) -> dict:
        reel.update(status=status, **extra)
        db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "instagram": reel})
        if status == "posted":
            out.unlink(missing_ok=True)  # (a Reel that didn't go keeps it until REEL_DAYS after its time, for Post now)
        return {"video_id": video_id, "instagram": status, **extra}

    def again(e: Exception, what: str) -> dict:
        """A try that didn't work: your Post now is tried once; at its time it's tried again later (REEL_WAITS). Meta
        refusing the connection isn't counted as a try: every Reel waits for it (_went_down)."""
        if getattr(e, "link_refused", None):  # (why Instagram refused the temporary link before the sending failed)
            reel["link_refused"] = e.link_refused[:300]
        if isinstance(e, instagram.Disconnected):
            _went_down(e, progress)
            if now:
                done("pending" if before == "pending" else "failed", error=str(e)[:300])
                raise RuntimeError(f"{what}: Meta refuses Instagram's connection ({e}). Connect Instagram again on the "
                                   "Channels page; if that doesn't help, developers.facebook.com shows whether Meta "
                                   "blocked your app") from e
            return done("pending", error=str(e)[:300], tries=0, retry_at=db.now_iso(DOWN_RECHECK))
        if now:  # your Post now: tried once; a Reel that was waiting for its time still waits for it
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
        progress(f"Getting story #{video_id}'s short version from run {run}, which kept it")
        try:
            kept.fetch(video_id, run, out)
        except FileNotFoundError:
            pass  # (its kept copy is gone: below, it waits for a cloud run to draw it again)
        except Exception as e:  # (GitHub or openssl, for now)
            return again(e, "Its video couldn't be fetched")
    if not out.exists():  # (no run keeps it: made on the laptop, or its kept copy gone; a cloud run draws it again)
        if slots.parse(reel.get("at") or row["publish_at"]) + timedelta(days=REEL_DAYS) < datetime.now(timezone.utc):
            notify.run(f"⚠️ The Reel of \"{plan['metadata']['title']}\" can't be posted: its video was never kept")
            return done("failed", error="its video was never kept in time (made on the laptop, or its kept copy gone)")
        progress(f"Story #{video_id}'s Reel video isn't kept anywhere yet: the next cloud run draws it again")
        waiting = done("pending", error="its video isn't kept yet: the next cloud run draws it again from its story",
                       retry_at=db.now_iso(VIDEO_WAIT), kept_in=None)
        if now:
            raise RuntimeError(f"Story #{video_id}'s video isn't on this computer or kept in the cloud: the next cloud "
                               "run draws it again from its story, then its Reel goes up")
        return waiting
    where = "public" if now else _on_youtube(reel.get("youtube_id") or row["youtube_id"])
    if where == "publishing" and (_turn(row) or "") > db.now_iso(-PUBLISH_LAG):
        progress(f"YouTube hasn't made story #{video_id}'s short version public yet; its Reel waits a few minutes more")
        return done("pending", retry_at=db.now_iso(timedelta(minutes=3)))  # (no try counted)
    if where != "public":
        progress(f"Story #{video_id}'s short version isn't public on YouTube (deleted or made private): no Reel")
        return done("skipped", error="not public on YouTube")
    meta = plan["metadata"]
    cover = float((plan.get("short_render") or {}).get("cover_at") or story_film.SHORT_COVER_AT)
    try:
        posted = instagram.publish(out, caption(meta, plan), cover, progress=progress)
    except Exception as e:
        return again(e, "Instagram didn't take it")
    notify.run(f"\U0001F4F8 On Instagram now: {meta['title']}" + (f"\n{posted['url']}" if posted.get("url") else ""))
    _came_back(progress)  # (if the connection was refused until now, the Reels that waited go up next)
    if posted.get("link_refused"):  # (sent instead: kept to find out why Instagram refused the temporary link)
        reel["link_refused"] = posted["link_refused"][:300]
    return done("posted", id=posted["id"], url=posted.get("url"), posted_at=db.now_iso(), error=None, retry_at=None)


def cancel_reel(video_id: int, because: str = "you took it off", keep_video: bool = True) -> bool:
    """Takes a Reel that isn't posted off Instagram's schedule: it isn't posted (your Post now still can while its video
    is kept). False if there's none to take off (none, posted, or being posted). Without keep_video its video goes too
    (the story was stopped or deleted on YouTube, so no Reel is wanted)."""
    with _reels:
        row = db.get_video(video_id)
        reel = (row["plan"].get("instagram") or {}) if row else {}
        taken = reel.get("status") in ("pending", "posting", "failed", "skipped", "remaking") and not _posting(reel)
        if taken:
            kept_parts = {k: v for k, v in reel.items() if k not in ("retry_at", "posting_at", "remaking_at")}
            db.update_video(video_id, plan={**row["plan"], "instagram": {**kept_parts, "status": "cancelled",
                                                                          "because": because,
                                                                          "cancelled_at": db.now_iso()}})
        if row and not keep_video and not _posting(reel) and not _remaking(reel):  # (remake_reel clears its own)
            animator.remove(animator.reel_path(row))
    return taken


def drop_reel(video_id: int) -> dict:
    """Your Delete on a story's Instagram side: a posted Reel is deleted from Instagram; one not posted yet is taken off
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
    """A story that went up while Reels were off (its short version wasn't kept) made again for Instagram: only its
    short version (the film is on YouTube), drawn again from its story. The Reel then waits for its time; what's saved
    about the YouTube videos stays as it was."""
    video_id = row["id"]
    with _reels:
        row = db.get_video(video_id)
        if not row or not platforms(row)["instagram"]["can"]["schedule"]:
            raise ValueError(f"Story #{video_id} can't be made again for Instagram (on the schedule, Instagram connected, "
                             "and no Reel waiting or posted)")
        before = row["plan"].get("instagram")
        db.update_video(video_id, plan={**row["plan"], "instagram": {**(before or {}), "status": "remaking",
                                                                      "remaking_at": db.now_iso()}})
    try:
        progress(f"Making {'Short' if series.form_of(row) == 'short' else 'the short version of story'} #{video_id} "
                 "again for Instagram")
        made = _draw_reel(row, progress)
    except Exception:
        with _reels:  # as it was before
            db.update_video(video_id, plan={**db.get_video(video_id)["plan"], "instagram": before})
        raise
    with _reels:
        fresh = db.get_video(video_id)
        if (fresh["plan"].get("instagram") or {}).get("status") != "remaking":  # taken off meanwhile (deleted on YouTube)
            animator.remove(animator.reel_path(fresh))
            return {**made, "instagram": "cancelled"}
        short = fresh["plan"].get("short_upload") or {}
        if series.form_of(fresh) == "short":
            short = {"publish_at": fresh["publish_at"], "youtube_id": fresh["youtube_id"]}
        db.update_video(video_id, plan={**fresh["plan"], "instagram": {
            "status": "pending", "tries": 0, "remade_at": db.now_iso(), "at": short.get("publish_at"),
            "youtube_id": short.get("youtube_id")}})
    progress(f"Its Reel goes on Instagram at its time ({slots.clock(slots.parse(_turn(db.get_video(video_id))), slots.plan())})")
    return {**made, "instagram": "pending"}


def platforms(row: dict, live: dict | None = None) -> dict:
    """Where a story stands on YouTube and on Instagram, and which of your buttons work there now (the Schedule page's
    two parts; the dashboard's actions check the same). `live`: what YouTube said just now about the videos it was asked
    about (youtube_upload.statuses; None for one it doesn't have any more), to notice changes made in Studio."""
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
        yt["url"] = (f"https://www.youtube.com/watch?v={yid}" if yt["state"] == "public"
                     else f"https://studio.youtube.com/video/{yid}/edit")
    yt["can"] = {"open": there, "now": early and there and yt["state"] not in ("public", "rejected"),
                 "stop": early and there, "delete": status == "scheduled" and bool(yid)}

    reel = row["plan"].get("instagram") or {}
    connected, video = instagram.is_configured(), animator.reel_path(row).exists()
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
           else "Its short version is being made again for Instagram" if state == "remaking"
           else "It isn't on the schedule yet" if status != "scheduled"
           else None if video
           else "Its short version is kept in the cloud, which posts its Reel at its time"
           if reel.get("kept_in") and state in ("waiting", "due", "retry")
           else "Reels weren't on when it went up, so its short version wasn't kept: Schedule makes it again"
           if state == "none"
           else f"Its short version isn't kept any more (only until {REEL_DAYS} days after its time)")
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
    return act("publisher", f"Upload story #{row['id']}", upload, row, slot, sched, progress=progress)


def run_remake(row: dict, progress=log) -> dict:
    return act("animator", f"Make story #{row['id']}'s short version again for Instagram", remake_reel, row,
               progress=progress)


def run_instagram(row: dict, progress=log, now: bool = False) -> dict:
    return act("publisher", f"Reel for story #{row['id']}" + (" (Post now)" if now else ""), post_reel, row,
               progress=progress, now=now)
