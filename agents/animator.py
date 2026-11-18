"""
Agent 3, Animator: makes the day's film, its short version, its thumbnail and a still of every scene, in your silhouette
look, drawn entirely in code (no AI pictures).

  - The narrator reads the story (tools/narrator.py: a calm, warm voice, Gemini's text-to-speech on the free tier, in
    parts; a part whose words didn't change is never read again).
  - Every shot is timed to his lines, and the film is drawn in code with the music silent until the spark, then rising
    (tools/story_film.py, tools/silhouette_render.py), at 1920x1080. The thumbnail is the chosen scene at its strongest
    moment with Agent 1's words big beside him, and a still of every scene is kept for the dashboard and the Reviewer.
  - Then the short version (make_short; your choice, 2026-11-16: it replaced the teaser): the whole story in under a
    minute for YouTube Shorts and Instagram Reels. Agent 2 writes its script the first time it's needed (agents/story.py
    write_short: some of the film's shots and new lines over them), the narrator reads it (one reading, in its own
    folder), and it's drawn upright (1080x1920) from the film's shots. One that runs a minute or more when read is
    written again, shorter, once. It can be made on its own, the film as it is: for a story made before short versions,
    a fix only it needs, or its Reel.

Every film and its short version go to the Reviewer (Agent 4, agents/reviewer.py) before the Publisher may post them. A
film it fails comes back here with its notes, and improve() acts on them: a scene turned down is drawn again with a change
(a lighter light, a calmer camera, him alone: STORY_FIXES), the sounds under him are turned down when he's hard to hear,
a voice problem gets a new reading; a problem only the short version has is fixed in it alone (the sounds under him,
a new reading, or a new script from Agent 2). A film still turned down after the Reviewer's rounds is made again by
itself (make_again), and from the REWRITE_FROM-th time Agent 2 writes the story again. Problems that keep coming back
become standing settings from the Reviewer's lessons (agents/base.py lessons_for), applied to every film from the start.

The narrator has one voice, his own: Gemini's, from the models that take his persona, each reading measured against his
sample (tools/narration.py, tools/voiceprint.py; a reading that only came out too high is brought down into his range,
and a part both his models read unlike him is read again steadier). There's no backup voice. When his voice is out
(still unlike him, busy, or used up), it rests (a note in the
database, so nothing retries in the meantime) and the story waits (VoiceResting): until his models' free readings renew
(13:30 in India) when they're used up for the day, otherwise REST_FIRST, twice as long after each failure in a row, up to
REST_MOST. A film wanted now (its slot is due, or you pressed "Make it now") asks Gemini even while it rests.

His readings are kept (.tmp/voices/<id>, and <id>-short for the short version) until the story is posted or discarded.

Usage:
    python -m agents.animator --id 12          # makes story #12's film (.tmp/out/short_12.mp4) and its short version
    python -m agents.animator --id 12 --short  # ...only its short version (.tmp/out/shortv_12.mp4), the film as it is
"""

import argparse
import json
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import db
import media
import narration
import narrator
import series
import slots
import story_film
from agents import story as story_agent
from agents.base import act, lessons_for, log
from common import is_true, tmp_path

# After failing, Gemini's voice rests REST_FIRST, twice as long after each failure in a row, up to REST_MOST.
# (A whole hour from the first failure kept videos waiting long after Gemini was back: 2026-10-26.)
REST_FIRST, REST_MOST = timedelta(minutes=10), timedelta(hours=1)
MAX_REDRAWS = 2        # a scene the Reviewer turns down is drawn again at most this often a making
REWRITE_FROM = 3       # turned down this many times: Agent 2 writes the story again before it's made
REMOVE_FOR = 120       # seconds a file the dashboard was serving is tried again for deletion
STORY_FIXES = {  # how a scene the Reviewer turns down is drawn again (the drawing is code: a change, not a new seed)
    "too_dark": "a lighter light", "hard_to_read": "a calmer camera, nothing in the way", "crowded": "him alone",
    "mismatch": "a calmer camera", "broken_picture": "drawn again", "unsuitable": "him alone",
}
SHORT_FIXES = {  # the Reviewer's fixes for a problem only the short version has: it's made again alone
    "short_beds": "the sounds under him in the short version turned down", "short_reread": "the short version read again",
    "short_rewrite": "Agent 2 writes the short version again", "short_remake": "the short version made again",
}


# --- where a story's files are ---------------------------------------------------------------------------------------------

def preview_path(video_id: int) -> Path:
    """The film (1920x1080)."""
    return tmp_path("out", f"short_{video_id}.mp4")


def cover_path(video_id: int) -> Path:
    """A frame of the film, for the dashboard."""
    return tmp_path("out", f"cover_{video_id}.jpg")


def thumb_paths(video_id: int) -> tuple[Path, Path]:
    """The thumbnails: (an upright one, unused for films; the wide one, 1280x720)."""
    return tmp_path("out", f"thumb_{video_id}.jpg"), tmp_path("out", f"thumb_{video_id}_wide.jpg")


def short_path(video_id: int) -> Path:
    """The story's short version (1080x1920): its YouTube Short and its Instagram Reel."""
    return tmp_path("out", f"shortv_{video_id}.mp4")


def reel_path(row: dict) -> Path:
    """The video a story's Reel posts: its short version."""
    return short_path(row["id"])


def voice_dir(video_id: int) -> Path:
    return tmp_path("voices", str(video_id), "x").parent


def short_voice_dir(video_id: int) -> Path:
    """The short version's reading (its own folder: narrator.read clears out what isn't its own in the one it reads into)."""
    return tmp_path("voices", f"{video_id}-short", "x").parent


def scenes_dir(video_id: int) -> Path:
    """Where a story's scene stills are kept."""
    return tmp_path("scenes", str(video_id), "x").parent


def plate_files(video_id: int, plan: dict) -> dict[str, str]:
    """A story's scenes ({"s1": path, ...}): a still of every shot, as the Animator last drew them."""
    folder = scenes_dir(video_id)
    return {pid: str(folder / name) for pid, name in (plan.get("plates") or {}).items() if (folder / name).exists()}


def forget(video_id: int) -> None:
    """The story's kept readings, no longer needed (it's posted or discarded)."""
    shutil.rmtree(voice_dir(video_id), ignore_errors=True)
    shutil.rmtree(short_voice_dir(video_id), ignore_errors=True)


def short_made(row: dict) -> bool:
    """Is the story's short version made, from its film as it is now and from its script?"""
    plan = row["plan"]
    short, made = plan.get("short_render") or {}, plan.get("render") or {}
    return bool(short.get("id") and made.get("id") and short.get("of") == made["id"]
                and (plan.get("story") or {}).get("short") and short_path(row["id"]).exists())


def remove(path: Path) -> None:
    """Deletes a story's file that the dashboard may be serving right now: Windows refuses while it's open (2026-10-27),
    so it's tried again in the background for REMOVE_FOR, as long as it's still the same file (a new film in its place
    is left alone)."""
    try:
        path.unlink(missing_ok=True)
        return
    except PermissionError:
        try:
            was = path.stat().st_mtime_ns
        except OSError:
            return

    def later():
        deadline = time.monotonic() + REMOVE_FOR
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                if path.stat().st_mtime_ns != was:
                    return
                path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                continue

    threading.Thread(target=later, daemon=True).start()


# --- the narrator's voice resting --------------------------------------------------------------------------------------------

def is_his(spoken: dict) -> bool:
    """Is a reading (or a story's voice record) his voice: Gemini's, by a model that reads him, and like his sample when
    it was measured."""
    model = (spoken.get("voice") or "").rpartition("(")[2].rstrip(") ")
    return (spoken.get("engine") == "gemini" and model in narration.TTS_MODELS
            and (spoken.get("likeness") or {}).get("his", True))


def voice_resting() -> dict | None:
    """The note saying Gemini's voice is resting (it failed and its rest isn't over), if it is."""
    note = db.latest_note("voice:rest")
    return note if note and (note.get("until") or "") > db.now_iso() else None


def rest_until() -> str | None:
    """When Gemini's resting voice is asked again (e.g. 13:30, on the schedule's clock), or None if it isn't resting."""
    note = voice_resting()
    return _after(note) if note else None


def resting() -> dict | None:
    """What holds the stories back now, if anything: the narrator's voice resting."""
    return voice_resting()


def _rest(why: str, until: str | None = None) -> dict:
    """Gemini's voice failed: it rests until `until` (his free readings renew), else longer after each failure in a
    row."""
    failures = int((db.latest_note("voice:rest") or {}).get("failures") or 0) + 1
    rest = min(REST_MOST, REST_FIRST * 2 ** min(failures - 1, 8))
    note = {"why": why[:400], "at": db.now_iso(), "until": until or db.now_iso(rest), "failures": failures,
            "used_up": bool(until)}
    db.keep_note("voice:rest", note)
    return note


def _rested() -> None:
    """Gemini's voice answered: no more resting, and the next failure starts a short rest again."""
    if (db.latest_note("voice:rest") or {}).get("failures"):
        db.keep_note("voice:rest", {"at": db.now_iso(), "failures": 0})


class Resting(RuntimeError):
    """A free service the story needs is out for now (Gemini's voice): the story waits for it, with nothing counted
    against it."""


class VoiceResting(Resting):
    """Gemini's voice is out for now; the story is read when it's back."""


def _after(note: dict) -> str:
    """When a resting voice is tried again, on the posting schedule's clock (e.g. 21:40)."""
    try:
        return slots.clock(datetime.fromisoformat(note["until"].replace("Z", "+00:00")), slots.plan())
    except (KeyError, AttributeError, ValueError):
        return "a few minutes from now"


# --- the film ----------------------------------------------------------------------------------------------------------------

def _story_times(plan: dict) -> list[dict]:
    """The film's timing as it was made (each shot's start and length)."""
    return [{"start": s["start"], "seconds": round(s["end"] - s["start"], 3), "line_at": None}
            for s in (plan.get("render") or {}).get("shots") or []]


def _music_credit(track: str | None) -> list[str]:
    credit = media.music_credit(track)
    return [credit] if credit else []


def _read(lines: list[dict], folder: Path, take: int, video_id: int, progress=log) -> dict:
    """The narrator reads `lines` into `folder` (a part whose words didn't change isn't read again). When Gemini's voice
    is out, it rests and VoiceResting is raised: the story waits for it."""
    try:
        spoken = narrator.read(lines, folder, take=take, progress=progress)
    except narration.VoiceUnavailable as e:
        rest = _rest(str(e), e.until)
        if e.until:
            raise VoiceResting(f"The narrator's free readings for today are used up; story #{video_id} waits and is read "
                               f"when they renew (about {_after(rest)})") from e
        # (paused, nothing asks again by itself: on 2026-11-18 "tried again at about 23:59" read like a quota wait)
        again = ("is read again when you press “Make it now”" if is_true("PAUSED") or db.paused()
                 else f"is read again at about {_after(rest)}")
        if e.unlike:
            left = sum(narration.left_today().values())
            raise VoiceResting(f"Gemini's readings of “{e.words}…” came out {e.unlike} (not the narrator's voice), even "
                               f"read steadier; story #{video_id} waits and {again} (not the daily limit: {left} free "
                               "readings left today)") from e
        raise VoiceResting(f"Gemini's voice couldn't read it just now (busy or out of reach); story #{video_id} waits and "
                           f"{again}") from e
    _rested()
    return spoken


def _voice_record(spoken: dict, lines: list[dict]) -> dict:
    """What a reading was, kept with the story (the Reviewer checks it's his voice)."""
    words = sum(len(line["text"].split()) for line in lines)
    return {"engine": "gemini", "voice": spoken["voice"], "match": spoken["match"], "deeper": spoken["deeper"],
            "narrator": True, "readings": spoken["readings"], "his": spoken.get("his", True),
            "words_per_second": round(words / max(spoken["seconds"], 1), 2),
            **({"likeness": spoken["likeness"]} if spoken.get("likeness") else {})}


def _beds(fixes: dict, short: bool = False) -> float:
    """How far the sounds under him go down (dB): the Reviewer's fixes for this story, and its standing lessons."""
    standing = lessons_for("animator")["settings"]  # (the Reviewer's lessons: fixes every film gets from the start)
    return (float(fixes.get("beds") or 0) + float(standing.get("beds") or 0)
            + (float(fixes.get("short_beds") or 0) if short else 0.0))


def animate(row: dict, out: Path, progress=log, now: bool = False) -> dict:
    """The story's film, drawn in code in the silhouette look: the narrator's reading (only parts whose words changed are
    read again), the film timed to his lines with the music from the spark, a still of every scene and the thumbnail;
    the film is saved, then its short version is made (make_short). `now`: it's wanted now (its slot is due, or you
    asked), so Gemini is asked even while its voice rests; otherwise a resting voice raises VoiceResting at once and the
    story waits for it (a film made before his voice ran out is kept: only its short version waits)."""
    plan = row["plan"]
    story = plan.get("story")
    if not series.is_story(row) or not story:
        raise RuntimeError(f"#{row['id']} is from an earlier version of the channel: it has no story to animate")
    if not now and (rest := voice_resting()):
        raise VoiceResting(f"Gemini's voice is resting until about {_after(rest)}; story #{row['id']} is made then")
    started = time.monotonic()
    if not story.get("shots"):   # (written but not storyboarded yet: Agent 3 designs its pictures first)
        from agents import storyboard

        story = storyboard.run(story, progress=progress)
        plan = {**plan, "story": story, "metadata": {**(plan.get("metadata") or {}), **story_agent.metadata(story)},
                "script": {**(plan.get("script") or {}), "lines": story_agent.lines_of(story)}}
        db.update_video(row["id"], plan=plan)
    fixes = plan.get("fixes") or {}
    progress("The narrator is reading the story")
    lines = story_agent.lines_of(story)
    spoken = _read(lines, voice_dir(row["id"]), int(fixes.get("take") or 0), row["id"], progress)
    made = story_film.make(story, spoken["lines"], out, progress, beds=_beds(fixes))
    times = made["times"]
    story_film.cover(out, 2.6, cover_path(row["id"]))
    progress("Drawing a still of every scene")
    folder = scenes_dir(row["id"])
    for old in folder.glob("scene_*.jpg"):
        old.unlink(missing_ok=True)
    scenes = story_film.scenes(story, times, folder)
    seconds = round(time.monotonic() - started, 1)
    plan = {**{k: v for k, v in plan.items() if k not in ("short_render", "teaser")},  # (teaser: an earlier version's)
            "plates": {pid: Path(path).name for pid, path in scenes.items()},
            "voice": _voice_record(spoken, lines),
            "render": {"id": uuid.uuid4().hex[:10], "made_at": db.now_iso(), "look": series.LOOK, "seconds": made["seconds"],
                       "render_seconds": seconds, "title_until": 0.01, "chapters": made["chapters"],
                       "music": made.get("music"),
                       "shots": [{"start": t["start"], "end": round(t["start"] + t["seconds"], 3),
                                  "name": f"plate:{shot['plate']}", "act": shot["act"], "line": shot.get("line") or ""}
                                 for shot, t in zip(story["shots"], times)],
                       "lines": [{"start": t["line_at"], "end": round(t["line_at"] + t["line_seconds"], 3)}
                                 for t in times if t["line_at"] is not None]},
            "credits": _music_credit(made.get("music"))}
    try:
        plan["thumbnail"] = make_thumbnail(row["id"], plan)
    except Exception as e:  # a film without its thumbnail still goes out (YouTube picks a frame)
        progress(f"Couldn't make the thumbnail ({type(e).__name__}: {str(e)[:120]})")
    db.update_video(row["id"], plan=plan)  # (kept even if its short version has to wait for his voice)
    progress(f"Film ready: {made['seconds'] / 60:.1f} minutes, made in {seconds / 60:.0f} minutes")
    short = make_short({**row, "plan": plan}, progress, now=True)
    return {"plan": short["plan"], "video_id": row["id"], "length": made["seconds"],
            "render_seconds": round(time.monotonic() - started, 1), "voice": spoken["voice"],
            "readings": spoken["readings"] + short["readings"], "short": short["short"]}


def make_short(row: dict, progress=log, now: bool = False, again: bool = False) -> dict:
    """The story's short version (1080x1920), from its film as it is: Agent 2 writes its script if it has none (a story
    written before short versions, or written again: kept with the story at once), the narrator reads it (one reading,
    its own folder) and it's drawn upright from the film's shots. One that runs a minute or more when read is written
    again, shorter, once. `now` as animate(). `again`: a posted story's short version made again for its Reel (nothing
    saved, so its plan still describes what's on YouTube)."""
    plan = row["plan"]
    story = plan.get("story")
    if not series.is_story(row) or not story:
        raise RuntimeError(f"#{row['id']} is from an earlier version of the channel: it has no story to animate")
    if not again and not (plan.get("render") or {}).get("id"):
        raise RuntimeError(f"Story #{row['id']}'s film isn't made yet: its short version comes after it")
    if not now and (rest := voice_resting()):
        raise VoiceResting(f"Gemini's voice is resting until about {_after(rest)}; story #{row['id']}'s short version "
                           "is made then")
    started = time.monotonic()
    fixes = plan.get("fixes") or {}
    complaint, readings = None, 0
    for attempt in range(2):
        if not story.get("short"):
            story = {**story, "short": story_agent.run_short(story, progress=progress, complaint=complaint)}
            if not again:  # (kept at once: if his voice has to wait, the same script is read when it's back)
                plan = {**plan, "story": story}
                db.update_video(row["id"], plan=plan)
        lines = story_film.short_lines(story)
        progress("The narrator is reading the short version")
        spoken = _read(lines, short_voice_dir(row["id"]), int(fixes.get("short_take") or 0), row["id"], progress)
        readings += spoken["readings"]
        length = sum(t["seconds"] for t in story_film.short_timeline(story_film.short_story(story), spoken["lines"]))
        if length < story_film.SHORT_MOST:
            break
        if attempt:
            raise RuntimeError(f"story #{row['id']}'s short version runs {length:.0f} s when read, a minute or more, even "
                               "written again shorter")
        complaint = (f"Read aloud, your last short version ran {length:.0f} s: write it with about 15 fewer words, so it "
                     "stays well under a minute")
        progress(f"The short version runs {length:.0f} s when read: Agent 2 writes it again, shorter")
        story = {**story, "short": None}
    made = story_film.make_short(story, spoken["lines"], short_path(row["id"]), progress, beds=_beds(fixes, short=True))
    seconds = round(time.monotonic() - started, 1)
    progress(f"Short version ready: {made['seconds']:.0f} s, {len(made['film_shots'])} of the film's shots, made in "
             f"{seconds:.0f} s")
    if again:
        return {"video_id": row["id"], "short": made["seconds"], "readings": readings, "voice": spoken["voice"]}
    plan = {**plan, "story": story,
            "short_render": {"id": uuid.uuid4().hex[:10], "of": (plan.get("render") or {}).get("id"),
                             "made_at": db.now_iso(), "seconds": made["seconds"], "render_seconds": seconds,
                             "music": made.get("music"), "cover_at": story_film.SHORT_COVER_AT,
                             "voice": _voice_record(spoken, lines),
                             "shots": [{"shot": k, "start": t["start"], "end": round(t["start"] + t["seconds"], 3)}
                                       for k, t in zip(made["film_shots"], made["times"])],
                             "lines": [{"start": t["line_at"], "end": round(t["line_at"] + t["line_seconds"], 3)}
                                       for t in made["times"] if t["line_at"] is not None]}}
    db.update_video(row["id"], plan=plan)
    return {"plan": plan, "video_id": row["id"], "short": made["seconds"], "readings": readings,
            "voice": spoken["voice"]}


# --- the thumbnail -----------------------------------------------------------------------------------------------------------

def stills(plan: dict) -> list[str]:
    """The scenes a thumbnail can be made from, in the order they appear ("plate:s1", ...)."""
    if not plan.get("story"):
        return []
    return [f"plate:{p['id']}" for p in plan["story"]["plates"] if p["id"] in (plan.get("plates") or {})]


def make_thumbnail(video_id: int, plan: dict, lead: str | None = None, punch: str | None = None,
                   background: str | None = None, text: str | None = None) -> dict:
    """The story's thumbnail (1280x720, tools/thumbnail.py's template): one of its scenes at its strongest moment (the
    storyboard's choice, or yours), him big with his marks, the words (a white lead-in and a yellow punch: Agent 3's, or
    yours) and the red arrow; returns what it was made from, and when that scene is on screen (Instagram's cover frame).
    `text`: one line of words (a story from before the storyboard): all of it the punch."""
    story, before = plan["story"], plan.get("thumbnail") or {}
    chosen = story.get("thumbnail") or {}
    if text is not None and lead is None and punch is None:
        lead, punch = "", text
    if lead is None and punch is None:
        lead = before.get("lead") if "lead" in before else chosen.get("lead")
        punch = before.get("punch") if "punch" in before else (chosen.get("punch") or before.get("text")
                                                               or chosen.get("words"))
    lead = " ".join(str(lead or "").split())[:40]
    punch = " ".join(str(punch or story.get("theme") or "").upper().split())[:40]
    choices = stills(plan)
    picked = f"plate:s{chosen['shot']}" if chosen.get("shot") else f"plate:{chosen.get('plate')}"
    background = background or before.get("background") or picked
    if background not in choices:
        background = choices[0] if choices else None
    if not background:
        raise RuntimeError("the story has no scene for a thumbnail")
    k = int(background.partition(":")[2].lstrip("s") or 1)
    times = _story_times(plan)
    if len(times) != len(story["shots"]):
        times = story_film.timeline(story)
    _, wide = thumb_paths(video_id)
    story_film.thumbnail(story, times, k, lead, punch, wide)
    first = next((s for s in (plan.get("render") or {}).get("shots") or [] if s.get("name") == background), None)
    return {"lead": lead, "punch": punch, "text": " ".join(w for w in (lead, punch) if w), "background": background,
            "at": round(first["start"] + 0.6, 2) if first else 1.2, "made_at": db.now_iso()}


# --- acting on the Reviewer's notes ------------------------------------------------------------------------------------------

def _redraw(shot: dict, kind: str) -> str:
    """A scene drawn again with the change its problem asks for; returns the change in words."""
    import silhouette_words

    if shot.get("place") and not shot.get("set"):   # (a shot of Agent 3's storyboard: changed in its own words)
        him = shot.get("him") or {}
        if kind == "too_dark":
            shot["light"] = "dusk" if shot.get("light") == "day" else "day"
            shot["weather"] = "clear"
        elif kind in ("crowded", "unsuitable"):
            shot["others"] = []
            if him.get("action") in silhouette_words.PAIRS:
                shot["him"] = {**him, "action": "standing", "with": "", "mark": None}
        elif kind == "hard_to_read":
            shot["framing"] = "medium" if him else "wide"
        shot["move"] = "hold"
        if kind in ("hard_to_read", "mismatch", "broken_picture") and shot.get("event") != "head_turn":
            shot["event"] = "none"
        shot["redraws"] = int(shot.get("redraws") or 0) + 1
        return STORY_FIXES.get(kind, "drawn again")
    if kind == "too_dark":
        lights = silhouette_words.SETS[shot["set"]][1]
        shot["light"] = "day" if "day" in lights else ("dusk" if "dusk" in lights else lights[0])
        shot["rain"] = False
    elif kind in ("crowded", "unsuitable"):
        shot["other"] = "none"
    shot["camera"] = "hold"
    if kind in ("hard_to_read", "mismatch", "broken_picture"):
        shot["event"] = "none" if shot.get("event") not in ("head_turn", "clock_flip") else shot["event"]
    shot["redraws"] = int(shot.get("redraws") or 0) + 1
    return STORY_FIXES.get(kind, "drawn again")


def improve(plan: dict, progress=log) -> tuple[dict, list[str]]:
    """Acts on the Reviewer's notes about the latest film and its short version: a scene turned down is drawn again with
    a change (at most MAX_REDRAWS times a making), sounds covering the narrator go down, a voice problem gets a new
    reading; a problem only the short version has is fixed in it (SHORT_FIXES), and when nothing else needs fixing only
    it is made again (fixes["short_only"]). Returns the plan and what was changed, in words; nothing changed means
    nothing the Animator can do would fix it."""
    review = plan.get("review") or {}
    fixes = json.loads(json.dumps(plan.get("fixes") or {}))
    story = json.loads(json.dumps(plan["story"]))
    changes, redrawn = [], set()
    for issue in review.get("issues") or []:
        fix, what = issue.get("fix"), issue.get("what") or ""
        if issue.get("severity") != "major" or not fix:
            continue
        if fix == "redraw" and what.startswith("plate:s"):
            k = int(what.partition(":")[2].lstrip("s") or 0) - 1
            if not 0 <= k < len(story["shots"]) or k in redrawn or int(story["shots"][k].get("redraws") or 0) >= MAX_REDRAWS:
                continue
            change = _redraw(story["shots"][k], issue.get("kind") or "")
            if k < len(story.get("plates") or []):
                story["plates"][k]["redraws"] = story["shots"][k]["redraws"]
                story["plates"][k]["scene"] = story_agent.scene_words(story["shots"][k])
            redrawn.add(k)
            changes.append(f"scene {k + 1} drawn again ({change})")
        elif fix == "beds" and float(fixes.get("beds") or 0) > -12 and "the sounds under him turned down" not in changes:
            fixes["beds"] = float(fixes.get("beds") or 0) - 4
            changes.append("the sounds under him turned down")
        elif fix == "reread" and "read again" not in changes:
            fixes["take"] = int(fixes.get("take") or 0) + 1
            changes.append("read again")
        elif fix == "remake" and not changes:
            changes.append("made again")
        elif fix in SHORT_FIXES and SHORT_FIXES[fix] not in changes:
            if fix == "short_beds":
                if float(fixes.get("short_beds") or 0) <= -12:
                    continue
                fixes["short_beds"] = float(fixes.get("short_beds") or 0) - 4
            elif fix == "short_reread":
                fixes["short_take"] = int(fixes.get("short_take") or 0) + 1
            elif fix == "short_rewrite":
                story["short"] = None
            elif fix == "short_remake" and any(c in SHORT_FIXES.values() for c in changes):
                continue  # (made again anyway)
            changes.append(SHORT_FIXES[fix])
    if changes:
        fixes["round"] = int(fixes.get("round") or 0) + 1
        fixes["changes"] = changes
        fixes["short_only"] = all(c in SHORT_FIXES.values() for c in changes)
        # (the film and the short version they answer: applied once, even if the making waits for his voice)
        fixes["after"] = [review.get("of"), review.get("short_of")]
    plan = {**plan, "story": story, "fixes": fixes}
    if any(c in SHORT_FIXES.values() for c in changes):
        plan.pop("short_render", None)  # (the short version is made again)
    return plan, changes


def make_again(row: dict, progress=log) -> dict:
    """A story the Reviewer turned down after the fixes, made ready to be made again by itself (nothing waits for you:
    agents/reviewer.py hold() says when). Its scenes' fixes are kept (their redraws counted afresh) and a voice problem
    gets a new reading; from the REWRITE_FROM-th time Agent 2 writes the story again (same theme and title). Returns the
    story as it is now."""
    plan = row["plan"]
    major = [i for i in (plan.get("review") or {}).get("issues") or [] if i.get("severity") == "major"]
    remakes = int(plan.get("remakes") or 0) + 1
    if remakes >= REWRITE_FROM:
        progress(f"Story #{row['id']} was turned down again: Agent 2 writes it again, then the Animator makes it")
        written = story_agent.write(plan["brief"], progress)
        plan = {**{k: v for k, v in plan.items()
                   if k not in ("fixes", "review", "plates", "teaser", "thumbnail", "short_render")},
                "story": written["story"], "script": written["script"], "metadata": written["metadata"]}
    else:
        story = json.loads(json.dumps(plan["story"]))
        turned_down = {(i.get("what") or "").partition(":")[2] for i in major if (i.get("what") or "").startswith("plate:")}
        for k, shot in enumerate(story["shots"]):
            if f"s{k + 1}" in turned_down and int(shot.get("redraws") or 0) < MAX_REDRAWS:
                kind = next((i.get("kind") for i in major if (i.get("what") or "") == f"plate:s{k + 1}"), "") or ""
                _redraw(shot, kind)
            shot["redraws"] = 0
        fixes = {k: v for k, v in (plan.get("fixes") or {}).items() if k not in ("round", "changes", "short_only")}
        if any(i.get("fix") == "reread" for i in major):
            fixes["take"] = int(fixes.get("take") or 0) + 1
        if any(i.get("fix") == "short_reread" for i in major):
            fixes["short_take"] = int(fixes.get("short_take") or 0) + 1
        if any(i.get("fix") == "short_rewrite" for i in major):
            story["short"] = None
        plan = {**{k: v for k, v in plan.items() if k != "review"}, "story": story, "fixes": fixes}
        progress(f"Story #{row['id']} was turned down after the fixes: the Animator makes it again (time {remakes})")
    plan = {k: v for k, v in plan.items() if k not in ("render", "short_render")}  # (made again, old files or not)
    db.update_video(row["id"], plan={**plan, "remakes": remakes, "remade_at": db.now_iso()})
    remove(preview_path(row["id"]))
    remove(short_path(row["id"]))
    return db.get_video(row["id"])


def run(row: dict, out: Path | None = None, progress=log, now: bool = False) -> dict:
    return act("animator", f"Make story #{row['id']}'s film", animate, row, out or preview_path(row["id"]),
               progress=progress, now=now)


def run_short(row: dict, progress=log, now: bool = False) -> dict:
    return act("animator", f"Make story #{row['id']}'s short version", make_short, row, progress=progress, now=now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--short", action="store_true", help="only its short version (its film is made already)")
    parser.add_argument("--now", action="store_true", help="ask Gemini's voice even while it rests")
    args = parser.parse_args()
    try:
        row = db.get_video(args.id)
        if not row:
            raise RuntimeError(f"there's no story #{args.id}")
        result = run_short(row, now=args.now) if args.short else run(row, now=args.now)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, indent=2))
    if not args.short:
        print(f"Wrote {preview_path(args.id)}")
    print(f"Wrote {short_path(args.id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
