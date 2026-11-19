"""
Agent 4, Reviewer: watches every film the Animator makes, and its short version, before the Publisher may post them,
the way a picture editor would. Only a film that passes goes to the Publisher. One that fails goes back to the
Animator with the review's notes (agents/animator.py, improve()): it fixes what they point at and makes the film again
(or only its short version, when only that failed), at most MAX_ROUNDS times; a film that still fails is turned down
(held): never posted as it is, and made again by itself (animator.make_again: the scenes turned down drawn again with a
change, later a new story from Agent 2), at once the first time and then after
REMAKE_WAITS, over and over until it passes (your call on 2026-10-27: nothing waits for you). Its slot stays empty
meanwhile. You can still post one anyway, or discard it, in the Studio.

What it checks, on the finished film (what a viewer sees and hears):
  size and length  1920x1080, inside series.minutes
  sound            its level (a silent film, told in bubbles since 2026-11-19, plays at film_sound.LUFS_TARGET),
                   peaks, and no dead silence
  the bubbles      (bubble_checks, measured) at least BUBBLES_LEAST, each on screen its reading time
                   (silhouette_words.read_seconds), none past the end
  the look         one Gemini look at a frame of every scene (a new place or light, and every head turn) and the
                   closing line, against what the scene should show and your look description: too dark to see,
                   what happens unreadable, a broken picture, a bubble over a face or cut off, the habit not shown big
                   in his fall, or anything unsuitable sends that scene back to be drawn again with a change
and on its short version (the YouTube Short and the Reel; your choice, 2026-11-16): 1080x1920, under a minute
(SHORT_LEAST to story_film.SHORT_MOST seconds; story_film.SHORT_SECONDS is the aim), its sound, its bubbles, and 4 of
its frames in the same look (its first shot, two scenes, its closing line). A problem only it has is fixed in it
alone: the sounds under it, or a new script from Agent 2 (one too long). A review counts for the film and the short
version it saw (current()). (A narrated film, from before 2026-11-19, is listened to as before: every line heard by
faster-whisper, MIN_MATCH of it, and his own voice.)

A problem is "major" (the film fails) or "minor" (only noted). Every review is kept (note review:history, the last
HISTORY), and problems that keep coming back at first look (RECURRING of the last LOOKBACK) become lessons (note
review:lessons, read through agents/base.py lessons_for()): standing settings the Animator applies from the start, and
advice for Agent 2, so the same mistake is made less.

Usage:
    python -m agents.reviewer --id 12          # reviews story #12's film (.tmp/out/short_12.mp4)
    python -m agents.reviewer --id 12 --fix    # ...and, if it fails, the Animator's fixes (the full loop)
"""

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import db
import film_sound
import llm
import media
import narration
import notify
import prompts
import series
import story_film
from agents import animator
from agents.base import act, lessons_for, log

CHECKS = 2                  # what a review covers: 2 = with his voice measured (2026-10-27); an older one is looked at again
MAX_ROUNDS = 2              # times the Animator may fix a film before it's turned down and made again from the start
REMAKE_WAITS = (0, 30, 60, 120, 240)  # minutes from a turn-down to the next making, by the times it was made again
MIN_MATCH = 0.85            # how much of the narration must be heard in the final mix
UNCLEAR = 0.6               # a line heard less well than this is unclear
MAX_PEAK = -0.1             # dBTP: above this it may clip
DARK = "blackdetect=d=0.4:pic_th=0.95:pix_th=0.06"  # 95% of the picture near black for 0.4 s
SILENT = "silencedetect=n=-50dB:d=1.0"
HEAR_RATE = 16_000          # whisper's sample rate
HISTORY = 40
LOOKBACK, RECURRING = 12, 3
FILM_SIZE, SHORT_SIZE = (1920, 1080), (1080, 1920)
SHORT_LEAST = 40.0          # seconds: a short version shorter than this fails (story_film.SHORT_MOST and over, too)
LOUDNESS_FILM_OK, LOUDNESS_FILM_BAD = 2.0, 4.0  # LU from film_sound.LUFS_VOICE: a note, then a failure
MAX_STORY_FRAMES = 24      # frames a film's look takes: a frame of (nearly) every scene
STORY_PROBLEMS = {  # (fails the film, in words, sent back to Agent 3 to draw that scene again)
    "too_dark": (True, "the people can't be made out: too dark", True),
    "hard_to_read": (True, "what happens can't be read (people overlapping, cut off, hidden)", True),
    "mismatch": (False, "the picture doesn't show what the shot should", True),
    "broken_picture": (True, "a broken, glitched or blank picture", True),
    "unsuitable": (True, "something unsuitable for the channel", True),
    "off_look": (False, "something outside the look (a detailed face, thick outlines, a lens flare, neon)", True),
    "text_unreadable": (False, "a label, a bubble or the closing line hard to read", False),
    "bubble_wrong": (False, "a bubble over a face, cut off, or pointing at the wrong person", False),
    "habit_not_shown": (False, "the habit isn't shown big: no exaggerated eyes, marks or actions where the story needs them",
                        False),
}
STORY_LOOK = """You review frames of a finished animated short film before it goes on YouTube: a 3-4 minute motivational
story drawn in code in one look, the owner's own description of which is below. The people are black silhouettes with a
thin red rim of light and two white eyes (no faces: that is the look); the hero wears a teal hoodie. There's no title in
the picture: the film begins straight with its story. The last frame shows its closing line in widely spaced capitals:
those are the film's own words, and so is the
small label at the top of some frames, and so are the bubbles over people's heads (there's no narrator: what they say
and think appears in cream speech bubbles, thought clouds, spiky shouts, or a cloud with a small picture, each with a thin
coral-red rim and a tail to the one who says or thinks it). The habit the story is about is shown big, like a cartoon:
exaggerated eyes (hearts, $, spirals, furious, droopy...), marks round a head (steam, sweat, Zzz, hearts...), glows,
exaggerated actions: that is the look too. The frames marked "short version" come after: they're from the film's upright short version (9:16) for YouTube Shorts and Reels, the same scenes
framed upright; its last shows the closing line. Each frame comes with what its scene
should show. For each frame list the problems you can see, if any:
- too_dark: the people or what they do can't be made out (too dark to see).
- hard_to_read: what happens can't be read: people overlapping each other confusingly, cut off by the frame's edge, or
  hidden behind something.
- mismatch: the picture clearly doesn't show what it should (another place, nobody where he should be, the wrong action).
- broken_picture: a glitched, blank or corrupted frame.
- unsuitable: anything sexual, gory or bloody, or a child. (A fire, an ambulance's lights, a hospital bed, a bottle or
  a glass of wine are fine when the story has them; so are desire's symbols: hearts, lips, heart eyes, a phone screen of
  pink squares under "18+": they show nothing.)
- off_look: something outside the look: a detailed face, thick outlines, realistic 3D shading, a lens flare, neon tubes.
- text_unreadable: the label, a bubble's words or the closing line is cut off, misspelt or hard to read.
- bubble_wrong: a bubble covers a face, is cut by the frame's edge, or its tail points at someone who isn't speaking.
- habit_not_shown: (only in a frame of his fall: the hook, the incident, the collapse, rock bottom) the habit the story
  is about isn't shown big at all where it plainly should be.
Judge only what you see. Most frames have no problems: then list none.

The look, in the owner's own words:
"""
LESSONS = {  # a recurring problem -> what each agent takes from it: (agent, standing settings, advice)
    "too_dark": [("storyboard", {}, "Recent films had scenes too dark to read: prefer dusk, dawn or day, or a lamp-lit "
                                     "room, over night outdoors, and keep rain at night for the moments that need it.")],
    "hard_to_read": [("storyboard", {}, "Recent films had scenes that couldn't be read: one or two people in a shot, "
                                        "each doing one clear thing; close and medium shots for what matters.")],
    "mismatch": [("storyboard", {}, "Some scenes didn't show what their shot asked for: keep each shot to one action "
                                    "its place can hold, and put in the place the things the action needs.")],
    "unclear": [("animator", {"beds": -4}, "The narrator was hard to hear over the sounds: the sounds under him go down "
                                           "in every film."),
                ("story", {}, "The narrator was hard to hear: short plain sentences, and fewer single sounds under his "
                              "lines.")],
    "length": [("story", {}, "Recent films ran outside the length: keep to the word count.")],
}


def _look_schema(problems) -> dict:
    return {"type": "object", "properties": {
        "frames": {"type": "array", "items": {"type": "object", "properties": {
            "frame": {"type": "integer"},
            "problems": {"type": "array", "items": {"type": "string", "enum": list(problems)}},
            "note": {"type": "string", "description": "what's wrong, in a few words; empty if nothing"}},
            "required": ["frame", "problems", "note"]}},
        "overall": {"type": "integer", "description": "0-10: how good the film looks"}},
        "required": ["frames", "overall"]}


def _issue(kind: str, severity: str, detail: str, line: int | None = None, at: float | None = None,
           fix: str | None = None, what: str | None = None) -> dict:
    return {"kind": kind, "severity": severity, "detail": detail, "line": line,
            "at": None if at is None else round(float(at), 2), "fix": fix, "what": what}


# --- sound and picture ------------------------------------------------------------------

def probe(path: Path) -> dict:
    """One pass of ffmpeg over the video: its size, length and sound, its loudness and true peak, and the stretches
    that are too dark or silent."""
    err = subprocess.run([media.ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path), "-vf", DARK,
                          "-af", f"ebur128=peak=true,{SILENT}", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600).stderr
    size = re.search(r"Video: .*?, (\d{3,4})x(\d{3,4})", err)
    length = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    loud = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    peak = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    seconds = int(length[1]) * 3600 + int(length[2]) * 60 + float(length[3]) if length else 0.0
    silences, start = [], None
    for kind, value in re.findall(r"silence_(start|end): (-?[\d.]+)", err):
        if kind == "start":
            start = float(value)
        elif start is not None:
            silences.append((start, float(value)))
            start = None
    if start is not None:
        silences.append((start, seconds))
    return {"size": (int(size[1]), int(size[2])) if size else None, "seconds": round(seconds, 2),
            "sound": bool(re.search(r"Stream #\d+:\d+.*Audio:", err)),
            "loudness": float(loud[-1]) if loud else None,
            "peak": None if not peak or peak[-1] == "-inf" else float(peak[-1]),
            "dark": [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)],
            "silences": silences}


# --- his voice --------------------------------------------------------------------------

def _sound(path: Path):
    """The video's sound as 16 kHz mono samples (floats from -1 to 1)."""
    import numpy as np

    raw = subprocess.run([media.ffmpeg_exe(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(HEAR_RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True, timeout=300).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def timing_by_ear(samples, lines: list[dict]) -> list[dict]:
    """Each line's start and end found by hearing the whole mix: only for a film made before the Animator kept its
    lines' times (on a whole mix, whisper can skip a stretch under the music, which squeezes those lines)."""
    return narration.align(lines, narration.hear_samples(samples, " ".join(line["text"] for line in lines)))[0]


def hearing(samples, lines: list[dict], timing: list[dict]) -> tuple[list[float], float]:
    """How clearly each line comes through in the final mix, music and all (0-1), and the share of the script heard.
    Each line's stretch is heard on its own and without the script as a hint, so a drowned line can't be "heard" from
    the hint. (Heard whole, whisper once skipped 15 s under the music, though every line was clear. 2026-10-26.) A line
    that seems unclear alone is heard again with the lines on either side (alone, whisper mishears names it gets right
    with their neighbours); then what counts is how many of its own words are heard."""
    clarity, weights = [], []
    for k, (line, t) in enumerate(zip(lines, timing)):
        want = narration.tokens(line["text"])
        a, b = max(0.0, t["start"] - 0.25), t["end"] + 0.35
        heard = narration.hear_samples(samples[int(a * HEAR_RATE):int(b * HEAR_RATE)]) if want else []
        got = [tok for _, _, word in heard for tok in narration.tokens(word)]
        clear = round(difflib.SequenceMatcher(a=want, b=got, autojunk=False).ratio(), 2) if want else 1.0
        if clear < UNCLEAR:
            a = max(0.0, timing[max(k - 1, 0)]["start"] - 0.25)
            b = timing[min(k + 1, len(timing) - 1)]["end"] + 0.35
            got = [tok for _, _, word in narration.hear_samples(samples[int(a * HEAR_RATE):int(b * HEAR_RATE)])
                   for tok in narration.tokens(word)]
            found = difflib.SequenceMatcher(a=want, b=got, autojunk=False).get_matching_blocks()
            clear = max(clear, round(sum(block.size for block in found) / len(want), 2))
        clarity.append(clear)
        weights.append(len(want))
    return clarity, sum(c * w for c, w in zip(clarity, weights)) / max(1, sum(weights))


# --- the look -----------------------------------------------------------------------------

def _grab(path: Path, at: float) -> bytes | None:
    try:
        return subprocess.run([media.ffmpeg_exe(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
                               "-frames:v", "1", "-vf", "scale=540:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4",
                               "-"], capture_output=True, check=True, timeout=60).stdout or None
    except (subprocess.SubprocessError, OSError):
        return None


def _story_frames(plan: dict, seconds: float) -> list[tuple[float, str | None, str]]:
    """The frames the look takes: the first shot of every scene (a new place or light) and every shot whose event is
    the head turning to the camera (at most MAX_STORY_FRAMES); the closing line: (second, the scene's shot "sK" or None,
    what it should show). (No title in the picture since 2026-11-20: the first frame is the first scene's.)"""
    story, shots = plan["story"], (plan.get("render") or {}).get("shots") or []
    scenes = {p["id"]: p["scene"] for p in story.get("plates") or []}
    out = []
    last = None
    picked = []
    for k, (shot, made) in enumerate(zip(story["shots"], shots)):
        where = (shot.get("set") or shot.get("place"), shot.get("light"), shot.get("rain") or shot.get("weather"))
        if where != last or shot.get("event") == "head_turn":
            picked.append((k, made))
        last = where
    for k, made in picked[:MAX_STORY_FRAMES + 1]:
        pid = f"s{k + 1}"
        t = made["start"] + min(2.4 if k == 0 else 1.6, (made["end"] - made["start"]) / 2)   # (the first: its bubble in)
        if story["shots"][k].get("event") == "head_turn":
            t = min(made["end"] - 0.2, made["start"] + (made["end"] - made["start"]) * 0.45 + 0.9)
        if all(abs(t - x[0]) > 0.8 for x in out):
            out.append((round(t, 2), pid, scenes.get(pid) or ""))
    if shots:
        end = shots[-1]
        t = min(seconds - 1.6, max(end["start"] + 0.5, end["end"] - 2.2))
        out.append((round(t, 2), None, f"the last scene, with the closing line: \"{story['closing_line']}\""))
    return out


def _short_frames(plan: dict) -> list[tuple[float, str | None, str]]:
    """The short version's frames the look takes: its first shot (its hook), his lowest moment and his new life (a story
    from before the storyboard: its spark and its turn-down), and its closing line: (second in it, the film's shot "sK"
    or None, what it should show)."""
    story, shots = plan["story"], (plan.get("short_render") or {}).get("shots") or []
    if not shots:
        return []
    scenes = {p["id"]: p["scene"] for p in story.get("plates") or []}
    first = shots[0]
    out = [(story_film.SHORT_COVER_AT, f"s{first['shot']}", scenes.get(f"s{first['shot']}") or "the first scene")]
    for part in ("rock_bottom", "payoff") if story.get("realization") is not None else ("spark", "turn_down"):
        got = next((s for s in shots[1:-1] if story["shots"][s["shot"] - 1].get("act") == part), None)
        if got:
            t = got["start"] + min(1.6, (got["end"] - got["start"]) / 2)
            out.append((round(t, 2), f"s{got['shot']}", scenes.get(f"s{got['shot']}") or ""))
    end = shots[-1]
    out.append((round(max(end["start"] + 0.5, end["end"] - 2.0), 2), None,
                f"the last scene, with the closing line: \"{story['closing_line']}\""))
    return out


def look(path: Path, plan: dict, seconds: float, progress=log, short: Path | None = None) -> tuple[list[dict], int | None]:
    """One Gemini look at a frame of every scene (and 4 of the short version's, `short`), against what it should show and
    your look; its findings and score."""
    frames = [(t, pid, should, path, "") for t, pid, should in _story_frames(plan, seconds)]
    if short is not None and short.exists():
        frames += [(t, pid, should, short, " of the short version") for t, pid, should in _short_frames(plan)]
    parts = [f"The film: \"{plan['story']['title']}\". {len(frames)} frames, in order:"]
    shown = {}
    for i, (t, pid, should, src, which) in enumerate(frames):
        jpg = _grab(src, t)
        if jpg:
            shown[i] = (t, pid, which)
            parts += [f"Frame {i}{which} at {t:.0f} s. It should show: {should}", ("image/jpeg", jpg)]
    if not shown:
        return [_issue("look", "minor", "no frames could be taken for the look")], None
    progress(f"Looking at {len(shown)} frames")
    advice = lessons_for("reviewer")["advice"]
    try:
        described = prompts.load("look_silhouette")
    except Exception:  # (without the key the frames are still looked at, without the owner's words)
        described = "(not available)"
    answer = llm.generate_json(parts, _look_schema(STORY_PROBLEMS), STORY_LOOK + described
                               + ("\nLearned so far:\n- " + "\n- ".join(advice) if advice else ""), patient=True)
    shots = plan["story"]["shots"]
    issues = []
    for item in answer.get("frames") or []:
        if item.get("frame") not in shown:
            continue
        t, pid, which = shown[item["frame"]]
        note = " ".join(str(item.get("note") or "").split())[:160]
        k = int(pid[1:]) - 1 if pid else None
        for problem in dict.fromkeys(item.get("problems") or []):
            if problem not in STORY_PROBLEMS:
                continue
            fails, words, redraw = STORY_PROBLEMS[problem]
            can = redraw and k is not None and int(shots[k].get("redraws") or 0) < animator.MAX_REDRAWS
            issues.append(_issue(problem, "major" if fails and can else "minor",
                                 f"{words} at {t:.0f} s{which}" + (f" (scene {k + 1})" if k is not None else "")
                                 + (f": {note}" if note else ""),
                                 None, t, "redraw" if can else None, f"plate:{pid}" if pid else None))
    score = answer.get("overall")
    return issues, max(0, min(10, int(score))) if isinstance(score, (int, float)) else None


# --- the review -----------------------------------------------------------------------------

def current(plan: dict) -> dict | None:
    """The story's review if it's of the film and the short version as they are now (the makings it names are the
    latest) and covers what a review checks now (CHECKS), else None. Your "Post it anyway" counts for the film as it is."""
    review, made, short = plan.get("review"), plan.get("render") or {}, plan.get("short_render") or {}
    if not review or not made.get("id") or review.get("of") != made["id"]:
        return None
    if review.get("override"):
        return review
    if int(review.get("checks") or 1) < CHECKS or not short.get("id") or review.get("short_of") != short["id"]:
        return None
    return review


def _short_checks(row: dict, plan: dict, progress=log) -> tuple[list[dict], dict]:
    """The short version, watched and listened to like the film: its size and length (under a minute), its sound, every
    one of its lines heard, his voice. Its problems name the fixes made in it alone (animator.SHORT_FIXES)."""
    path, short = animator.short_path(row["id"]), plan.get("short_render") or {}
    if not path.exists() or not short.get("id"):
        return [_issue("short", "major", "the short version wasn't made", fix="short_remake")], {}
    found = probe(path)
    issues = []
    aim_low, aim_high = story_film.SHORT_SECONDS
    if found["size"] != SHORT_SIZE:
        issues.append(_issue("short", "major", f"the short version is {found['size']} instead of 1080x1920",
                             fix="short_remake"))
    if not found["sound"]:
        issues.append(_issue("short", "major", "the short version has no sound", fix="short_remake"))
    if not SHORT_LEAST <= found["seconds"] < story_film.SHORT_MOST:
        issues.append(_issue("short_length", "major", f"the short version runs {found['seconds']:.0f} s (under a minute: "
                             f"{aim_low:.0f}-{aim_high:.0f} s)", fix="short_rewrite"))
    elif not aim_low - 1 <= found["seconds"] <= aim_high + 1:
        issues.append(_issue("short_length", "minor", f"the short version runs {found['seconds']:.0f} s "
                             f"({aim_low:.0f}-{aim_high:.0f} s is the aim)"))
    silent = bool(short.get("silent"))
    aim = film_sound.LUFS_TARGET if silent else film_sound.LUFS_VOICE
    if found["loudness"] is not None:
        off = abs(found["loudness"] - aim)
        if off > LOUDNESS_FILM_OK:
            issues.append(_issue("short", "major" if off > LOUDNESS_FILM_BAD else "minor",
                                 f"the short version is at {found['loudness']:.1f} LUFS (the aim is {aim:.0f})",
                                 fix="short_remake" if off > LOUDNESS_FILM_BAD else None))
    for a, b in found["silences"]:
        if b - a >= 1.0 and b < found["seconds"] - 1.5:
            issues.append(_issue("short", "major", f"{b - a:.1f} s of dead silence in the short version", at=a,
                                 fix="short_remake"))
    if silent:
        issues += [{**i, "kind": "short_" + i["kind"], "fix": "short_remake" if i.get("fix") else None}
                   for i in bubble_checks(short.get("bubbles") or [], found["seconds"], least=4)]
        return issues, {"seconds": found["seconds"], "loudness": found["loudness"], "match": None, "clarity": []}
    progress("Listening to the narrator in the short version")
    samples = _sound(path)
    picked = (plan["story"].get("short") or {}).get("shots") or []   # (a narrated short version's lines, before 2026-11-19)
    lines = [{"text": x.get("line") or (plan["story"].get("closing_line") if j == len(picked) - 1 else ""),
              "direction": x.get("direction") or "", "shot": j} for j, x in enumerate(picked)]
    lines = [x for x in lines if x["text"]]
    timing = short.get("lines") or []
    if len(timing) != len(lines):
        timing = timing_by_ear(samples, lines)
    clarity, match = hearing(samples, lines, timing)
    fix = "short_beds" if float((plan.get("fixes") or {}).get("short_beds") or 0) > -12 else "short_reread"
    if match < MIN_MATCH:
        issues.append(_issue("short_unclear", "major", f"only {match:.0%} of the short version's narration can be made "
                             "out", fix=fix))
    for k, (line, t, heard) in enumerate(zip(lines, timing, clarity)):
        if heard < UNCLEAR:
            issues.append(_issue("short_unclear", "major" if match >= MIN_MATCH else "minor",
                                 f"the short version's line {k + 1} is hard to make out ({heard:.0%} heard)", k,
                                 t["start"], fix))
    spoken = short.get("voice") or {}
    if not animator.is_his({k: v for k, v in spoken.items() if k != "likeness"}) or spoken.get("his") is False:
        why = (spoken.get("likeness") or {}).get("why") or "another voice"
        issues.append(_issue("short_voice", "major", f"the short version doesn't sound like the narrator ({why})",
                             fix="short_reread"))
    return issues, {"seconds": found["seconds"], "loudness": found["loudness"], "match": round(match, 3),
                    "clarity": clarity}


BUBBLES_LEAST = 12   # a silent film has at least this many bubbles (its people talk and think)


def bubble_checks(bubbles: list[dict], seconds: float, least: int = BUBBLES_LEAST) -> list[dict]:
    """A silent film's bubbles, measured: enough of them, each on screen long enough to read
    (silhouette_words.read_seconds), none past the film's end."""
    import silhouette_words as W

    issues = []
    if len(bubbles) < least:
        issues.append(_issue("bubbles", "major", f"only {len(bubbles)} bubbles: the people hardly talk or think",
                             fix="remake"))
    for k, b in enumerate(bubbles):
        need = W.read_seconds(b.get("text") or "", b.get("picture") or "")
        if b["end"] - b["start"] < need - 0.05:
            issues.append(_issue("bubble_short", "major", f"bubble {k + 1} (\"{(b.get('text') or b.get('picture') or '')[:30]}\") "
                                 f"stays {b['end'] - b['start']:.1f} s: it needs {need:.1f} s to be read", at=b["start"],
                                 fix="remake"))
        if b["end"] > seconds + 0.1:
            issues.append(_issue("bubbles", "major", f"bubble {k + 1} runs past the film's end", at=b["start"],
                                 fix="remake"))
    return issues


def review(row: dict, path: Path | None = None, progress=log) -> dict:
    """Watches and listens to a story's film and its short version; saves the verdict on the story (earlier rounds kept
    in its history) and returns it."""
    plan = row["plan"]
    path = path or animator.preview_path(row["id"])
    if not path.exists():
        raise RuntimeError(f"Story #{row['id']} has no film to review")
    made, short = plan.get("render") or {}, plan.get("short_render") or {}
    lines = plan["script"]["lines"]
    progress("The Reviewer is watching the film")
    found = probe(path)
    issues = []
    low, high = series.minutes()
    if found["size"] != FILM_SIZE:
        issues.append(_issue("size", "major", f"the film is {found['size']} instead of 1920x1080", fix="remake"))
    if not found["sound"]:
        issues.append(_issue("sound", "major", "the film has no sound", fix="remake"))
    if not low * 60 - 45 <= found["seconds"] <= high * 60 + 45:
        issues.append(_issue("length", "major", f"{found['seconds'] / 60:.1f} minutes, outside {low:g}-{high:g}", fix="remake"))
    elif not low * 60 - 15 <= found["seconds"] <= high * 60 + 20:
        issues.append(_issue("length", "minor", f"{found['seconds'] / 60:.1f} minutes ({low:g}-{high:g} is the aim)"))
    silent = bool(made.get("silent"))   # (told in bubbles: nothing to listen to, a wordless film's loudness)
    aim = film_sound.LUFS_TARGET if silent else film_sound.LUFS_VOICE
    if found["loudness"] is not None:
        off = abs(found["loudness"] - aim)
        if off > LOUDNESS_FILM_OK:
            issues.append(_issue("loudness", "major" if off > LOUDNESS_FILM_BAD else "minor",
                                 f"{found['loudness']:.1f} LUFS (the aim is {aim:.0f})",
                                 fix="remake" if off > LOUDNESS_FILM_BAD else None))
    if found["peak"] is not None and found["peak"] > MAX_PEAK:
        issues.append(_issue("peak", "minor", f"the sound peaks at {found['peak']:.1f} dB and may clip"))
    for a, b in found["silences"]:
        if b - a >= 1.0 and b < found["seconds"] - 1.5:
            issues.append(_issue("silence", "major", f"{b - a:.1f} s of dead silence", at=a, fix="remake"))
    for a, b in found["dark"]:
        if b - a >= 2.0 and a > 1.0:
            issues.append(_issue("dark", "minor", f"a very dark stretch of {b - a:.1f} s", at=a))
    if silent:
        issues += bubble_checks(made.get("bubbles") or [], found["seconds"])
        clarity, match = [], None   # (nothing to hear)
    else:
        progress("Listening to the narrator")
        samples = _sound(path)
        timing = made.get("lines") or []
        if len(timing) != len(lines):
            timing = timing_by_ear(samples, lines)
        clarity, match = hearing(samples, lines, timing)
        beds = float((plan.get("fixes") or {}).get("beds") or 0)
        fix = "beds" if beds > -12 else "reread"  # (drowned out: the sounds under him go down first, then he reads again)
        if match < MIN_MATCH:
            issues.append(_issue("unclear", "major", f"only {match:.0%} of the narration can be made out", fix=fix))
        for k, (line, t, heard) in enumerate(zip(lines, timing, clarity)):
            if heard < UNCLEAR:
                issues.append(_issue("unclear", "major" if match >= MIN_MATCH else "minor",
                                     f"line {k + 1} is hard to make out ({heard:.0%} heard)", k, t["start"], fix))
        spoken = plan.get("voice") or {}
        if not animator.is_his({k: v for k, v in spoken.items() if k != "likeness"}) or spoken.get("his") is False:
            why = (spoken.get("likeness") or {}).get("why") or "another voice"
            issues.append(_issue("not_narrator", "major", f"it doesn't sound like the narrator ({why})", fix="reread"))
    progress("The Reviewer is watching the short version")
    heard_short, short_found = _short_checks(row, plan, progress)
    issues += heard_short
    try:
        seen, score = look(path, plan, found["seconds"], progress, short=animator.short_path(row["id"]))
        issues += seen
    except Exception as e:  # Gemini out: the rest of the review stands
        issues.append(_issue("look", "minor", f"the frames couldn't be looked at ({type(e).__name__})"))
        score = None
    major = [i for i in issues if i["severity"] == "major"]
    earlier = plan.get("review") or {}
    history = list(earlier.get("history") or [])
    if earlier.get("issues") is not None and (earlier.get("of"), earlier.get("short_of")) != (made.get("id"), short.get("id")):
        history.append({k: earlier.get(k) for k in ("round", "passed", "at", "issues", "changes")})  # (an earlier version)
    words = (sum(len((b.get("text") or "").split()) for b in made.get("bubbles") or []) if silent
             else sum(len(line["text"].split()) for line in lines))
    verdict = {"passed": not major, "round": (plan.get("fixes") or {}).get("round", 0), "of": made.get("id"),
               "short_of": short.get("id"), "checks": CHECKS, "at": db.now_iso(), "issues": issues,
               "changes": (plan.get("fixes") or {}).get("changes") or [], "history": history[-MAX_ROUNDS - 1:],
               "seconds": found["seconds"], "loudness": found["loudness"], "peak": found["peak"],
               "match": round(match, 3) if match is not None else None,
               "clarity": clarity, "look": score, "words_per_second": round(words / max(found["seconds"], 1), 2),
               "short": short_found, "held": False}
    db.update_video(row["id"], plan={**plan, "review": verdict})
    remember(row["id"], verdict)
    if major:
        progress(f"Review, round {verdict['round'] + 1}: failed ({len(major)} problem(s): "
                 + "; ".join(i["detail"] for i in major[:4]) + ")")
    else:
        progress(f"Review, round {verdict['round'] + 1}: passed" + (f" ({len(issues)} small note(s))" if issues else ""))
    return verdict


def remember(video_id: int, verdict: dict) -> None:
    """Adds the review to the history, and rewrites the lessons from the recurring problems in first looks."""
    history = list(db.latest_note("review:history") or [])
    history.append({"video_id": video_id, "round": verdict["round"], "passed": verdict["passed"], "at": verdict["at"],
                    "kinds": sorted({i["kind"] for i in verdict["issues"] if i["severity"] == "major"})})
    history = history[-HISTORY:]
    db.keep_note("review:history", history)
    first = [h for h in history if h["round"] == 0][-LOOKBACK:]
    counts = Counter(kind for h in first for kind in h["kinds"])
    found = {}
    for kind, count in counts.items():
        if count < RECURRING:
            continue
        for agent, settings, advice in LESSONS.get(kind, []):
            mine = found.setdefault(agent, {"settings": {}, "advice": []})
            mine["settings"].update(settings)
            mine["advice"].append(f"{advice} ({count} of the last {len(first)} films)")
    db.keep_note("review:lessons", {"reviews": len(first), "counts": dict(counts), "for": found, "updated_at": db.now_iso()})


def hold(video_id: int, why: str, progress=log) -> None:
    """The film still fails after the Animator's fixes: it's never posted as it is, and the Animator makes it again by
    itself (the loop: tools/jobs.py unmade(), animator.make_again) from `remake_at`: at once the first time, then after
    REMAKE_WAITS, until it passes. Nothing waits for you (your call, 2026-10-27)."""
    row = db.get_video(video_id)
    remakes = int(row["plan"].get("remakes") or 0)
    wait = REMAKE_WAITS[min(remakes, len(REMAKE_WAITS) - 1)]
    db.update_video(video_id, plan={**row["plan"], "review": {**(row["plan"].get("review") or {}), "held": True,
                                                               "held_because": why,
                                                               "remake_at": db.now_iso(timedelta(minutes=wait))}})
    title = (row["plan"].get("metadata") or {}).get("title") or row["theme"]
    progress(f"The Reviewer turned story #{video_id} down: {why}. The Animator makes it again by itself"
             + (f" in {wait} minutes" if wait else ""))
    if not remakes:  # (once a story: what follows needs nothing from you)
        notify.run(f"\U0001F50D The Reviewer turned a story down after the Animator's fixes:\n{title}\n{why}\n"
                   "The Animator makes it again by itself until it passes.")


def reviewed(row: dict, progress=log, now: bool = False) -> dict:
    """Agent 3 makes the story's film and its short version (unless they're made, in the look of now; a film made
    without its short version gets only that) and Agent 4 reviews them (unless they're reviewed). A film that fails goes
    back to Agent 3 with the notes (only its short version is made again when only that failed), at most MAX_ROUNDS
    times; one that still fails is held. `now`: it's wanted now (its slot is due, or you asked), so Gemini's voice is
    asked even while it rests. Returns the story as it stands: its plan's review says whether it passed."""
    video_id = row["id"]

    def alive():  # a story being made for its slot: keep its claim fresh (a stale claim means a run was cut off)
        if row["status"] == "making":
            db.update_video(video_id, claimed_at=db.now_iso())

    made = row["plan"].get("render") or {}
    if not animator.preview_path(video_id).exists() or not made.get("id") or made.get("look") != series.LOOK:
        animator.run(row, progress=progress, now=now)  # (none yet, or drawn in an earlier look: drawn again now)
        alive()
        row = db.get_video(video_id)
    if not animator.short_made(row) and not (current(row["plan"]) or {}).get("override"):
        animator.run_short(row, progress=progress, now=now)  # (a film made before short versions, or its short one
        alive()                                              # had to wait for his voice)
        row = db.get_video(video_id)
    if not current(row["plan"]):
        run(row, progress=progress)
        row = db.get_video(video_id)
    while True:
        verdict = row["plan"]["review"]
        if verdict["passed"] or verdict.get("held") or verdict.get("override"):
            return row
        if verdict["round"] >= MAX_ROUNDS:
            hold(video_id, f"still failing after {MAX_ROUNDS} fixes: " + "; ".join(
                i["detail"] for i in verdict["issues"] if i["severity"] == "major")[:400], progress)
            return db.get_video(video_id)
        fixes = row["plan"].get("fixes") or {}
        if verdict.get("of") and fixes.get("after") == [verdict["of"], verdict.get("short_of")] and fixes.get("changes"):
            plan, changes = row["plan"], fixes["changes"]  # (this review's fixes are in: it waited for his voice)
        else:
            plan, changes = animator.improve(row["plan"])
        if not changes:
            hold(video_id, "nothing the Animator can change would fix: " + "; ".join(
                i["detail"] for i in verdict["issues"] if i["severity"] == "major")[:400], progress)
            return db.get_video(video_id)
        db.update_video(video_id, plan=plan)
        progress("Back to the Animator: " + "; ".join(changes))
        if (plan.get("fixes") or {}).get("short_only"):
            animator.run_short(db.get_video(video_id), progress=progress, now=now)
        else:
            animator.run(db.get_video(video_id), progress=progress, now=now)
        alive()
        run(db.get_video(video_id), progress=progress)
        alive()
        row = db.get_video(video_id)


def passed(plan: dict) -> bool:
    """May the Publisher post it: reviewed and passed (or you said post it anyway), for the film as it is now."""
    verdict = current(plan) or {}
    return bool(verdict.get("passed") or verdict.get("override"))


def run(row: dict, progress=log) -> dict:
    def work(row, progress=log):
        verdict = review(row, progress=progress)
        major = [i for i in verdict["issues"] if i["severity"] == "major"]
        return {"video_id": row["id"], "passed": verdict["passed"], "round": verdict["round"] + 1,
                "problems": [i["detail"] for i in major][:6], "notes": len(verdict["issues"]) - len(major),
                "look": verdict["look"], "match": verdict["match"]}

    return act("reviewer", f"Review story #{row['id']}", work, row, progress=progress)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--fix", action="store_true", help="if it fails, let the Animator fix it (the full loop)")
    args = parser.parse_args()
    try:
        row = db.get_video(args.id)
        if not row:
            raise RuntimeError(f"there's no story #{args.id}")
        if args.fix:
            row = reviewed(row)
            verdict = row["plan"]["review"]
        else:
            run(row)
            verdict = db.get_video(args.id)["plan"]["review"]
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in verdict.items() if k not in ("history", "clarity")}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
