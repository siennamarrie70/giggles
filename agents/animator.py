"""
Agent 4, Animator: makes the video and its thumbnail. The Professor reads the script
(tools/narration.py: Gemini's voice on the free tier, each line with its direction, every word timed
by faster-whisper), his mouth shapes are worked out (Rhubarb, tools/host.py), each line's visuals
become shots (real footage, archive film, photos with depth, satellite maps, charts, big numbers,
quotes: agents.writer.shot_for), a music track in the script's mood is picked, and
tools/doc_render.py draws and encodes the case, with a cover frame for the dashboard. Then the
thumbnail, in the channel's one style (tools/thumbnail.py): a still from the case, the Professor, the
case type and the Writer's few bold words, which you can change in the Studio. One voice call per
case and no other Gemini calls.

Every video goes to the Reviewer (Agent 5, agents/reviewer.py) before the Publisher may post it. A
video it fails comes back here with its notes, and improve() acts on them: a number or name that
collides with other words comes off its line, the title leaves sooner, a dark, frozen or unsuitable
shot is swapped for another picture from the research, a rushed line is read again more slowly,
pauses get longer, an over-long script loses a line, or it's simply made again. The fixes are kept on
the case (plan["fixes"]), so each new version keeps the earlier ones. Problems that keep coming back
become standing fixes from the Reviewer's lessons (agents/base.py lessons_for), applied to every video
from the start: that's how the Animator stops making the same mistake. A video still failing after the
Reviewer's rounds is made again by itself, over and over until it passes (make_again; your call on
2026-10-27: nothing waits for you to press "Make it again"): new drawings for the scenes turned down, a
new reading for a voice problem, and from the REWRITE_FROM-th time a new script from the Writer.

His reading is kept (.tmp/voices/<id>) until the Short is posted or discarded: a new version that only
changes the picture reuses it (no new voice call); one that changes the words, their directions or
the pauses has it read again.

The Professor has one voice, his own: Gemini's, from the models that take his persona, each reading
measured against the Host page's sample of it (tools/narration.py, tools/voiceprint.py). There's no
backup voice (Kokoro's was removed on 2026-10-27, and so was Gemini's legacy model: neither sounded
like him), and a kept reading that isn't his is never used again. When his voice is out, it rests (a
note in the database, so nothing retries in the meantime) and the case waits (VoiceResting): until
his models' free readings renew (midnight Pacific time) when they're used up for the day, otherwise
REST_FIRST, twice as long after each failure in a row, up to REST_MOST. The morning run tries it
again when the rest is over. A video wanted now (its slot is due, or you pressed "Make the video")
asks Gemini even while it rests (a model with no readings left today isn't asked).

In the drawn look (the script's look: agents/writer.py) the scenes are drawn first (draw_scenes:
Cloudflare's FLUX in his art, tools/draw.py, kept in .tmp/scenes/<id>/ so only what changed is drawn
again), each line plays over its drawing (a photo framed on it; a map, chart or quote over it,
darkened; a number landing on it), and the thumbnail is made from a drawing. When Cloudflare can't
draw (today's free drawing is used up, or it's out; a note in the database, until 00:00 UTC when the
day's drawing is used up), the case is made in the real-footage look instead, so the day's ten still go
up (settings look.when_out: footage, your choice on 2026-10-27): as_footage() has the Researcher find its
clips and the Writer write it again for them, before anything is read (no voice call wasted), and the
case stays in that look. With look.when_out: wait it waits for Cloudflare instead, as it does for the
voice (DrawingResting). A Short made again for its Reel never changes its look: it waits. A scene the
Reviewer turns down (letters in it, the wrong style, odd hands, too dark) is drawn again, with a word on
what to change, at most MAX_REDRAWS times.

The plan remembers the track, the voice, the drawings and every clip, photo and film on screen, so
the Publisher can add the credit lines and mark the clips used.

Usage:
    python -m agents.animator --id 12      # renders Short #12's preview into .tmp/out/short_12.mp4
"""

import argparse
import hashlib
import json
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import db
import doc_render
import draw
import host
import infographics
import narration
import short_render
import slots
import thumbnail
from agents import writer
from agents.base import act, lessons_for, log
from agents.writer import shot_for
from common import load_config, tmp_path

# After failing, Gemini's voice rests REST_FIRST, twice as long after each failure in a row, up to REST_MOST.
# (A whole hour from the first failure kept videos waiting long after Gemini was back: 2026-10-26.)
REST_FIRST, REST_MOST = timedelta(minutes=10), timedelta(hours=1)
CREDITED = ("footage", "archive", "photo")
SLOWER = "slowly and clearly, unhurried"  # added to a rushed line's direction when it's read again
TITLE_STEPS = (2.2, 1.6)                  # seconds the title stays, after each fix that shortens it
GAP_STEP, MAX_GAP = 0.08, 0.4             # longer pauses: this much more each time, up to this
STILLS = ("photo", "archive", "footage")  # what a thumbnail is made from, best first
SHORT_LINE = 8                            # drawn look: a line of fewer words shows its photo, map or card instead
                                          # of its drawing (two shots would flash by)
MAX_REDRAWS = 2                           # a scene the Reviewer turns down is drawn again at most this often a making
VOICE_FIXES = ("slower", "reread", "pauses")  # a case turned down for one of these is made again with a new reading
REWRITE_FROM = 3                          # turned down this many times: the Writer writes it again before it's made
REMOVE_FOR = 120                          # seconds a file the dashboard was serving is tried again for deletion
REDRAW_HINTS = {  # what a scene drawn again adds to its description, by the Reviewer's problem (FLUX has no "no":
    "bad_anatomy": "the figures small and seen from a distance",  # naming the problem would draw it)
    "off_style": "a flat hand-painted 2D illustration with ink outlines",
    "dark": "in clearer, brighter light",
    "graphic": "a calm, quiet moment",
    "child_visible": "only grown men and women",
}


def preview_path(video_id: int) -> Path:
    return tmp_path("out", f"short_{video_id}.mp4")


def cover_path(video_id: int) -> Path:
    return tmp_path("out", f"cover_{video_id}.jpg")


def thumb_paths(video_id: int) -> tuple[Path, Path]:
    """The thumbnail: the cover (1080x1920) and the wide one (1280x720)."""
    return tmp_path("out", f"thumb_{video_id}.jpg"), tmp_path("out", f"thumb_{video_id}_wide.jpg")


def voice_dir(video_id: int) -> Path:
    return tmp_path("voices", str(video_id), "x").parent


def scenes_dir(video_id: int) -> Path:
    """Where a drawn case's drawings are kept."""
    return tmp_path("scenes", str(video_id), "x").parent


def forget(video_id: int) -> None:
    """The case's kept reading, no longer needed (it's posted or discarded)."""
    shutil.rmtree(voice_dir(video_id), ignore_errors=True)


def remove(path: Path) -> None:
    """Deletes a case's file that the dashboard may be serving right now: Windows refuses while it's open (discarding
    #62 failed so, 2026-10-27), so it's tried again in the background for REMOVE_FOR, as long as it's still the same
    file (a new render in its place is left alone)."""
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


def is_his(spoken: dict) -> bool:
    """Is a reading (or a case's voice record) his voice: Gemini's, by a model that reads him, and like his sample
    when it was measured."""
    model = (spoken.get("voice") or "").rpartition("(")[2].rstrip(") ")
    return (spoken.get("engine") == "gemini" and model in narration.TTS_MODELS
            and (spoken.get("likeness") or {}).get("his", True))


def case_number(video_id: int) -> int:
    """The case's number, its place among the cases made so far: it seeds the Professor's blinks and glances (it was
    on screen as "Case file 12" until 2026-10-27, when you asked for it to go)."""
    with db.connect() as conn:
        return conn.query("SELECT COUNT(*) AS n FROM videos WHERE format = %s AND id <= %s "
                          "AND status NOT IN ('discarded', 'skipped')", (db.FORMAT, video_id))[0]["n"]


def voice_resting() -> dict | None:
    """The note saying Gemini's voice is resting (it failed and its rest isn't over), if it is."""
    note = db.latest_note("voice:rest")
    return note if note and (note.get("until") or "") > db.now_iso() else None


def rest_until() -> str | None:
    """When Gemini's resting voice is asked again (e.g. 21:40, on the schedule's clock), or None if it isn't resting."""
    note = voice_resting()
    return _after(note) if note else None


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


def drawing_resting() -> dict | None:
    """The note saying Cloudflare's drawing is resting (today's free drawing is used up, or it failed), if it is."""
    return draw.resting()


def drawing_rest_until() -> str | None:
    """When Cloudflare is asked to draw again (e.g. 05:30, on the schedule's clock), or None if it isn't resting."""
    note = drawing_resting()
    return _after(note) if note else None


def resting() -> dict | None:
    """What holds the cases back now, if anything: Gemini's voice resting, or Cloudflare's drawing when cases wait for
    it (look.when_out: wait; otherwise they're made with real footage meanwhile) (the later one)."""
    notes = [note for note in (voice_resting(), None if draw.fallback() else drawing_resting()) if note]
    return max(notes, key=lambda note: note["until"]) if notes else None


def _rest_drawing(error: Exception) -> dict:
    """Cloudflare couldn't draw: it rests until its allocation renews when that's why, else like the voice."""
    failures = int((db.latest_note("draw:rest") or {}).get("failures") or 0) + 1
    until = getattr(error, "until", None) or db.now_iso(min(REST_MOST, REST_FIRST * 2 ** min(failures - 1, 8)))
    note = {"why": str(error)[:400], "at": db.now_iso(), "until": until, "failures": failures}
    db.keep_note("draw:rest", note)
    return note


def _drawn() -> None:
    """Cloudflare drew: no more resting."""
    if (db.latest_note("draw:rest") or {}).get("failures"):
        db.keep_note("draw:rest", {"at": db.now_iso(), "failures": 0})


class Resting(RuntimeError):
    """A free service the case needs is out for now (Gemini's voice, Cloudflare's drawing): the case waits for it,
    with nothing counted against it."""


class VoiceResting(Resting):
    """Gemini's voice is out for now; the case is read when it's back."""


class DrawingResting(Resting):
    """Cloudflare can't draw for now (today's free drawing is used up, or it's out); the case is drawn when it can."""


def credits(plan: dict) -> list[str]:
    """The credit line of every clip, film and photo the video shows, in order of appearance (no repeats)."""
    pack = plan.get("research") or {}
    by_id = {x["id"]: x for key in ("footage", "archive", "images") for x in pack.get(key) or []}
    lines = []
    for line in (plan.get("script") or {}).get("lines") or []:
        for name in line.get("visuals") or []:
            kind, _, ref = name.partition(":")
            item = by_id.get(ref) if kind in CREDITED else None
            if not item:
                continue
            text = item.get("credit") if kind != "photo" else f"Photo: {item['credit']}"
            if text and text not in lines:
                lines.append(text)
    return lines


def settings(plan: dict) -> dict:
    """How this case is made: the Reviewer's fixes for it on top of the standing fixes every case gets."""
    standing = lessons_for("animator")["settings"]
    fixes = plan.get("fixes") or {}
    until = [float(x) for x in (standing.get("title_until"), fixes.get("title_until")) if x]
    return {"keep_gap": max(narration.KEEP_GAP, float(standing.get("keep_gap") or 0), float(fixes.get("keep_gap") or 0)),
            "title_until": min(until) if until else None, "slower": set(fixes.get("slower") or []),
            "drops": fixes.get("drops") or [], "take": int(fixes.get("take") or 0)}


def _reading(row: dict, said: list[dict], how: dict, progress) -> tuple[dict, list]:
    """The Professor's reading and his mouth track: the kept one if it's of these words, directions and pauses, in
    this voice; otherwise a new one (kept for next time). A reading that isn't his voice (the old backup voice,
    Gemini's dropped legacy model, or one measured unlike him) is never reused."""
    voice = load_config().get("voice") or {}
    key = hashlib.sha1(json.dumps([said, how["keep_gap"], how["take"],
                                   [voice.get(k) for k in ("name", "model", "style", "deeper")]],
                                  sort_keys=True).encode("utf-8")).hexdigest()[:16]
    work = voice_dir(row["id"])
    try:
        kept = json.loads((work / "reading.json").read_text(encoding="utf-8"))
        if kept["key"] == key and Path(kept["spoken"]["wav"]).exists() and is_his(kept["spoken"]):
            progress("Using the Professor's reading from before (the words haven't changed)")
            return kept["spoken"], kept["mouth"]
    except (OSError, ValueError, KeyError):
        pass
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    progress("The Professor is reading the script")
    try:
        spoken = narration.narrate(said, work / "narration.wav", progress=progress, keep_gap=how["keep_gap"])
    except narration.VoiceUnavailable as e:
        rest = _rest(str(e), e.until)
        if e.until:
            raise VoiceResting(f"His voice's free readings for today are used up; Short #{row['id']} waits and is "
                               f"read when they renew (about {_after(rest)})") from e
        raise VoiceResting(f"Gemini's voice didn't read it in his voice; Short #{row['id']} waits and is read when it "
                           f"does (tried again at about {_after(rest)})") from e
    _rested()
    timed = [{**line, **t} for line, t in zip(said, spoken["lines"])]
    progress("Working out his mouth shapes")
    mouth = host.mouth_track(spoken["wav"], timed)
    (work / "reading.json").write_text(json.dumps({"key": key, "spoken": spoken, "mouth": mouth}), encoding="utf-8")
    return spoken, mouth


def draw_scenes(row: dict, plan: dict, progress=log, now: bool = False) -> dict[str, str]:
    """The drawn look: every scene of the script drawn in his art (tools/draw.py), by the number of the line it
    starts on ({"1": path, "4": path...}). A scene Cloudflare refuses (its safety filter) leaves its line on the
    drawing before. Cloudflare out or today's free drawing used up: the case waits (DrawingResting). `now`: asked
    even while the drawing rests."""
    if not now and (rest := drawing_resting()):
        raise DrawingResting(f"Cloudflare's drawing is resting until about {_after(rest)}; Short #{row['id']} is drawn "
                             "then")
    wanted = [(k, line) for k, line in enumerate(plan["script"]["lines"])
              if (line.get("scene") or writer.SAME) != writer.SAME]
    progress(f"Drawing {len(wanted)} scenes in the Professor's art")
    drawings, refused, fresh, how = {}, [], False, draw.settings()
    for k, line in wanted:
        scene = ", ".join(x for x in (line["scene"].rstrip(". "), line.get("scene_hint")) if x)
        seed = int(line.get("seed_from") or 0) + int(line.get("redraws") or 0)  # (seed_from: make_again's)
        kept = draw.picture_path(scenes_dir(row["id"]), scene, seed, how).exists()
        try:
            drawings[str(k + 1)] = str(draw.draw(scene, scenes_dir(row["id"]), seed=seed, progress=progress))
            fresh = fresh or not kept
        except draw.DrawingUnavailable as e:
            rest = _rest_drawing(e)
            raise DrawingResting(f"Cloudflare can't draw now ({str(e)[:200]}); Short #{row['id']} waits and is drawn "
                                 f"when it can (tried again at about {_after(rest)})") from e
        except RuntimeError as e:  # this one scene refused: its line stays on the drawing before
            refused.append(k + 1)
            progress(f"Line {k + 1}'s scene couldn't be drawn ({str(e)[:160]}); it stays on the drawing before")
    if not drawings:
        raise RuntimeError(f"none of Short #{row['id']}'s scenes could be drawn (lines {refused})")
    if fresh:  # (pictures kept from before don't show that Cloudflare is back)
        _drawn()
    return drawings


def _written_again(plan: dict, progress=log, look: str | None = None) -> dict:
    """The plan with a new script from the Writer (from the same facts and photos; `look` or the one a case made now
    gets), its clips found first if it's now footage; the drawings, the fixes and the review of the old lines go."""
    pack = dict(plan.get("research") or {})
    written = writer.write(plan["brief"], pack, progress, look=look)
    return {**{k: v for k, v in plan.items() if k not in ("drawings", "fixes", "review")}, "research": pack,
            "script": written["script"], "metadata": written["metadata"]}


def as_footage(row: dict, plan: dict, why: str, progress=log) -> dict:
    """A case written for drawings, made in the real-footage look instead (Cloudflare can't draw): the Researcher
    finds its clips, the Writer writes it again for them from the same facts and photos, and it's saved so (the
    Reviewer's fixes for the old lines go with them). Returns the new plan."""
    plan = {**_written_again(plan, progress, "footage"), "switched": {"from": "drawn", "at": db.now_iso(), "why": why[:300]}}
    db.update_video(row["id"], plan=plan)
    return plan


def make_again(row: dict, progress=log) -> dict:
    """A case the Reviewer turned down after the fixes, made ready to be made again by itself (your call, 2026-10-27:
    nothing waits for you to press "Make it again"; agents/reviewer.py hold() says when). The review goes; the fixes
    stay, their rounds counted afresh; each scene the last review turned down gets a new drawing (a seed not used
    before), every scene's redraws are counted afresh, and a voice problem gets a new reading (a line still rushed is
    then slowed on its own: narration.slow_rushed). From the REWRITE_FROM-th time the Writer writes it again first,
    for what the Animator can't change. Returns the case as it is now."""
    plan = row["plan"]
    major = [i for i in (plan.get("review") or {}).get("issues") or [] if i.get("severity") == "major"]
    remakes = int(plan.get("remakes") or 0) + 1
    if remakes >= REWRITE_FROM:
        progress(f"Case #{row['id']} was turned down again: the Writer writes it again, then the Animator makes it")
        plan = _written_again(plan, progress)
    else:
        script = json.loads(json.dumps(plan["script"]))
        turned_down = {(i.get("what") or "").partition(":")[2] for i in major if (i.get("what") or "").startswith("scene:")}
        for k, line in enumerate(script["lines"]):
            if line.get("redraws") or str(k + 1) in turned_down:  # the same seed keeps its drawing; one more, a new one
                line["seed_from"] = (int(line.get("seed_from") or 0) + int(line.get("redraws") or 0)
                                     + (1 if str(k + 1) in turned_down else 0))
                line["redraws"] = 0
        fixes = {k: v for k, v in (plan.get("fixes") or {}).items() if k not in ("round", "changes")}
        if any(i.get("fix") in VOICE_FIXES for i in major):
            fixes["take"] = int(fixes.get("take") or 0) + 1
        plan = {**{k: v for k, v in plan.items() if k != "review"}, "script": script, "fixes": fixes}
        progress(f"Case #{row['id']} was turned down after the fixes: the Animator makes it again (time {remakes})")
    plan = {k: v for k, v in plan.items() if k != "render"}  # (made again whether or not the old file can go yet)
    db.update_video(row["id"], plan={**plan, "remakes": remakes, "remade_at": db.now_iso()})
    remove(preview_path(row["id"]))
    return db.get_video(row["id"])


def _over_drawing(visuals: list[dict], scene: dict, words: int) -> list[dict]:
    """A drawn-look line's shots: its drawing, then its other visual on it (a photo framed over it, a map, chart or
    quote over it darkened); a short line shows only the other visual (two shots would flash by). A number lands on
    the drawing."""
    extra = []
    for v in visuals:
        if v["kind"] == "photo":
            v = {**v, "kind": "framed", "backdrop": scene["path"]}
        elif v["kind"] in ("map", "chart", "quote"):
            v = {**v, "backdrop": scene["path"], "drawn": True}
        extra.append(v)
    shots = [v for v in extra if v["kind"] != "number"]
    return extra if shots and words < SHORT_LINE else [scene] + extra


def animate(row: dict, out: Path, progress=log, now: bool = False, again: bool = False) -> dict:
    """The voice, his mouth, the shots, music, the render and the thumbnail for one case; returns its updated plan.
    `now`: it's wanted now (its slot is due, or you asked), so Gemini is asked even while its voice rests;
    otherwise a resting voice raises VoiceResting at once and the case waits for it. `again`: a posted case made
    again as it was (for its Reel, when its video wasn't kept): its music and drawings, and nothing saved, so its
    plan still describes the video on YouTube."""
    cfg = load_config()
    plan = row["plan"]
    if row["format"] != db.FORMAT or not plan.get("script"):
        raise RuntimeError(f"Short #{row['id']} is from an earlier version of the channel: it has no case to animate")
    if not now and (rest := voice_resting()):
        raise VoiceResting(f"Gemini's voice is resting until about {_after(rest)}; Short #{row['id']} is read then")
    script = plan["script"]
    drawn = script.get("look") == "drawn"
    if drawn:  # first: three seconds a drawing, and nothing is read while Cloudflare can't draw
        try:
            plan = {**plan, "drawings": draw_scenes(row, plan, progress, now)}
        except DrawingResting as e:
            if again or not draw.fallback():
                raise
            progress(f"Cloudflare can't draw now: Short #{row['id']} is made with real footage instead")
            plan = as_footage(row, plan, str(e), progress)
            script, drawn = plan["script"], False
    how = settings(plan)
    said = [{"text": line["text"], "direction": ", ".join(d for d in (SLOWER if k in how["slower"] else "",
                                                                       line.get("direction", "")) if d),
             "slow": k in how["slower"]}  # (still rushed when read "slowly": slowed on its own, narration.slow_rushed)
            for k, line in enumerate(script["lines"])]
    spoken, mouth = _reading(row, said, how, progress)
    lines, origin = [], None
    for k, line in enumerate(script["lines"]):
        visuals = [{**s, "name": v} for v, s in ((v, shot_for(v, plan)) for v in line.get("visuals") or []) if s]
        if drawn:  # its own drawing, or the one before ("same", or a scene that couldn't be drawn)
            drawings = plan["drawings"]
            origin = str(k + 1) if str(k + 1) in drawings else origin or next(iter(drawings))
            visuals = _over_drawing(visuals, {"kind": "scene", "path": drawings[origin], "name": f"scene:{origin}"},
                                    len(line["text"].split()))
        lines.append({"text": line["text"], "beat": line.get("beat"), "visuals": visuals})
    if again:
        track = short_render.MUSIC_DIR / plan["music"] if plan.get("music") else None
        track = track if track and track.exists() else None
    else:
        track = short_render.pick_music(script.get("music_mood")) if cfg["music"]["volume"] > 0 else None
    progress("Animating" + (f" with {track.stem}" if track else " (no music)"))
    case = {"category": plan["brief"]["category"], "case_no": case_number(row["id"]),
            "case_title": script["case_title"], "narration": {**spoken, "mouth": mouth}, "lines": lines,
            "drops": how["drops"], "title_until": how["title_until"]}
    made = doc_render.render(case, out, track, cfg["music"]["volume"], cover_path=cover_path(row["id"]), progress=progress)
    if again:
        progress(f"Video made again: {made['seconds']:.0f} s, in {made['render_seconds']:.0f} s")
        return {"video_id": row["id"], "length": made["seconds"], "render_seconds": made["render_seconds"],
                "music": track.name if track else None, "voice": spoken["voice"]}
    plan = {**plan, "music": track.name if track else None,
            "voice": {"engine": spoken["engine"], "voice": spoken["voice"], "match": spoken["match"],
                      "deeper": spoken.get("deeper", 0),
                      "words_per_second": round(sum(len(l["text"].split()) for l in script["lines"])
                                                / max(spoken["seconds"], 1), 2),
                      **({"likeness": spoken["likeness"]} if spoken.get("likeness") else {})},
            "render": {"id": uuid.uuid4().hex[:10], "made_at": db.now_iso(),  # the Reviewer's verdict names the render it saw
                       "seconds": made["seconds"], "render_seconds": made["render_seconds"], "layout": made["layout"],
                       "shots": made["shots"], "title_until": how["title_until"] or doc_render.TITLE_FOR,
                       "lines": [{"start": t["start"], "end": t["end"]} for t in spoken["lines"]]},
            "credits": credits(plan)}
    try:
        plan["thumbnail"] = make_thumbnail(row["id"], plan)
    except Exception as e:  # a video without its thumbnail still goes out (YouTube picks a frame)
        progress(f"Couldn't make the thumbnail ({type(e).__name__}: {str(e)[:120]})")
    db.update_video(row["id"], plan=plan)
    progress(f"Video ready: {made['seconds']:.0f} s, made in {made['render_seconds']:.0f} s")
    return {"plan": plan, "video_id": row["id"], "length": made["seconds"], "render_seconds": made["render_seconds"],
            "music": plan["music"], "voice": plan["voice"]["voice"],
            "layout_notes": len(made["layout"])}


# --- the thumbnail -------------------------------------------------------------------

def stills(plan: dict) -> list[str]:
    """The script's shots a thumbnail can be made from: photos, archive film, then stock clips, maps and charts; in
    the drawn look, his art first (the drawings, in order), then the rest."""
    names = list(dict.fromkeys(v for line in plan["script"]["lines"] for v in line.get("visuals") or []
                               if v.split(":")[0] != "number" and not v.startswith("quote:")))
    if plan["script"].get("look") == "drawn":
        return [f"scene:{n}" for n in plan.get("drawings") or {}] + names
    return sorted(names, key=lambda v: STILLS.index(v.split(":")[0]) if v.split(":")[0] in STILLS else len(STILLS))


def make_thumbnail(video_id: int, plan: dict, text: str | None = None, background: str | None = None) -> dict:
    """Makes the case's thumbnail from its words (the Writer's, or yours) and a still (the first photo of the script,
    or the shot you picked); returns what it was made from, and when that shot is on screen (Instagram's cover
    frame)."""
    before = plan.get("thumbnail") or {}
    text = " ".join(str(text if text is not None else before.get("text") or (plan.get("metadata") or {}).get(
        "thumbnail_text") or plan["script"]["case_title"]).split())[:80]
    choices = stills(plan)
    background = background or before.get("background")
    if background not in choices:
        background = choices[0] if choices else None
    spec = shot_for(background, plan) if background else None
    if not spec:
        raise RuntimeError("the case has no picture for a thumbnail")
    category = plan["brief"]["category"]
    images = thumbnail.make(thumbnail.still(spec, infographics.accent(category)), text, category)
    thumbnail.save(images, *thumb_paths(video_id))
    shot = next((s for s in (plan.get("render") or {}).get("shots") or [] if s.get("name") == background), None)
    return {"text": text, "background": background, "at": round(shot["start"] + 0.6, 2) if shot else 1.2,
            "made_at": db.now_iso()}


# --- acting on the Reviewer's notes ------------------------------------------------------

def _replacement(plan: dict, lines: list[dict], name: str, tried: list[str]) -> str | None:
    """Another picture for a shot the Reviewer turned down: one from the research the script doesn't show yet and
    that hasn't been turned down, of the same kind if there is one (then archive film, photos, stock video)."""
    menu = writer.visual_menu(plan.get("research") or {}, plan.get("brief") or {},
                              (plan.get("script") or {}).get("look") == "drawn")
    used = {v for line in lines for v in line.get("visuals") or []}
    kind = name.split(":")[0]
    for want in dict.fromkeys([kind, "archive", "photo", "footage"]):
        found = next((v for v in menu if v.startswith(want + ":") and v not in used and v not in tried and v != name),
                     None)
        if found:
            return found
    return None


def improve(plan: dict, progress=log) -> tuple[dict, list[str]]:
    """Acts on the Reviewer's notes about the latest version: the fixes go into plan["fixes"] (and a swapped shot or
    a cut line into the script itself). Returns the plan and what was changed, in words; nothing changed means
    nothing the Animator can do would fix it."""
    review = plan.get("review") or {}
    fixes = json.loads(json.dumps(plan.get("fixes") or {}))
    fixes.setdefault("drops", [])
    fixes.setdefault("slower", [])
    fixes.setdefault("swapped", [])
    script = json.loads(json.dumps(plan["script"]))
    lines = script["lines"]
    changes, redrawn = [], set()
    for issue in review.get("issues") or []:
        fix, k, what = issue.get("fix"), issue.get("line"), issue.get("what")
        if issue.get("severity") != "major" or not fix:
            continue
        if fix == "swap" and (what or "").startswith("scene:"):  # a drawing isn't swapped: it's drawn again
            fix = "redraw"
        if fix == "drop" and k is not None and what in ("number", "name"):
            drop = {"kind": what, "line": k}
            if drop not in fixes["drops"]:
                fixes["drops"].append(drop)
                changes.append(f"took the {'big number' if what == 'number' else 'name'} off line {k + 1}")
        elif fix == "title":
            now = float(fixes.get("title_until") or doc_render.TITLE_FOR)
            shorter = next((s for s in TITLE_STEPS if s < now - 0.01), None)
            if shorter:
                fixes["title_until"] = shorter
                changes.append(f"the title now leaves after {shorter:g} s")
        elif fix == "swap" and what and what not in fixes["swapped"]:
            new = _replacement(plan, lines, what, fixes["swapped"])
            holders = [line for line in lines if what in (line.get("visuals") or [])]
            if not holders or not new and all(len(line["visuals"]) < 2 for line in holders):
                continue  # nothing to swap it for, and it's the line's only picture
            fixes["swapped"].append(what)
            for line in holders:
                if new:
                    line["visuals"] = [new if v == what else v for v in line["visuals"]]
                elif len(line["visuals"]) > 1:
                    line["visuals"] = [v for v in line["visuals"] if v != what]
            changes.append(f"swapped {what} for {new}" if new else f"took {what} out")
        elif fix == "redraw" and (what or "").startswith("scene:"):
            n = what.partition(":")[2]
            at = int(n) - 1 if n.isdigit() else -1
            if (not 0 <= at < len(lines) or at in redrawn or (lines[at].get("scene") or writer.SAME) == writer.SAME
                    or int(lines[at].get("redraws") or 0) >= MAX_REDRAWS):
                continue
            line = lines[at]
            redrawn.add(at)
            line["redraws"] = int(line.get("redraws") or 0) + 1  # a new seed: a new picture
            hint = REDRAW_HINTS.get(issue.get("kind"))
            if hint and hint not in (line.get("scene_hint") or ""):
                line["scene_hint"] = ", ".join(x for x in (line.get("scene_hint"), hint) if x)
            changes.append(f"line {at + 1}'s scene drawn again" + (f" ({hint})" if hint else ""))
        elif fix == "slower" and k is not None and k not in fixes["slower"]:
            fixes["slower"].append(k)
            changes.append(f"line {k + 1} is read again, slower")
        elif fix == "pauses":
            gap = round(min(MAX_GAP, max(narration.KEEP_GAP, float(fixes.get("keep_gap") or 0)) + GAP_STEP), 2)
            if gap > float(fixes.get("keep_gap") or narration.KEEP_GAP):
                fixes["keep_gap"] = gap
                changes.append(f"longer pauses ({gap:g} s)")
        elif fix == "reread" and "read again" not in changes:
            fixes["take"] = int(fixes.get("take") or 0) + 1
            changes.append("read again")
        elif fix == "trim":
            limit = float(load_config()["cases"].get("max_seconds", 90))
            ratio = float(review.get("seconds") or 0) / max(writer.estimate_seconds(lines), 1)
            before = len(lines)
            lines = writer.fit_length(lines, (limit - 3) / max(ratio, 0.5))
            if len(lines) < before:
                script["lines"] = lines
                script["seconds"] = round(writer.estimate_seconds(lines), 1)
                fixes["drops"], fixes["slower"] = [], []  # the lines moved: those notes are found again if needed
                changes.append(f"cut {before - len(lines)} line(s) to fit {limit:.0f} s")
        elif fix == "remake" and not changes:
            changes.append("made again")
    if changes:
        fixes["round"] = int(fixes.get("round") or 0) + 1
        fixes["changes"] = changes
        fixes["after"] = review.get("of")  # (the render they answer: applied once, even if the making waits)
    return {**plan, "script": script, "fixes": fixes}, changes


def _after(note: dict) -> str:
    """When a resting voice is tried again, on the posting schedule's clock (e.g. 21:40)."""
    try:
        return slots.clock(datetime.fromisoformat(note["until"].replace("Z", "+00:00")), slots.plan())
    except (KeyError, AttributeError, ValueError):
        return "a few minutes from now"


def run(row: dict, out: Path | None = None, progress=log, now: bool = False) -> dict:
    return act("animator", f"Animate Short #{row['id']}", animate, row, out or preview_path(row["id"]), progress=progress,
               now=now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--now", action="store_true", help="ask Gemini's voice even while it rests")
    args = parser.parse_args()
    try:
        row = db.get_video(args.id)
        if not row:
            raise RuntimeError(f"there's no Short #{args.id}")
        result = run(row, now=args.now)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, indent=2))
    print(f"Wrote {preview_path(args.id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
