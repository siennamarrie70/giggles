"""
Agent 5, Reviewer: watches every video the Animator makes before the Publisher may post it, the way
a picture editor would. Only a video that passes goes to the Publisher. One that fails goes back to
the Animator with the review's notes (agents/animator.py, improve()): it fixes what they point at
and makes the video again, at most MAX_ROUNDS times; a video that still fails is turned down (held):
never posted as it is, and made again by itself (animator.make_again: new drawings for the scenes
turned down, a new reading for a voice problem, later a new script), at once the first time and then
after REMAKE_WAITS, over and over until it passes (your call on 2026-10-27: nothing waits for you to
press "Make it again"). Its slot goes to the next case meanwhile. You can still post one anyway, or
discard it, in the Studio.

What it checks, on the finished MP4 (what a viewer sees and hears):
  words    where every word was on screen, from the renderer's own audit (tools/doc_render.py looks
           4 times a second): words overlapping each other, covering the Professor's face, or under
           YouTube's buttons and title text
  voice    faster-whisper hears the final mix, music and all, each line's stretch on its own, and
           compares it with the script: a line it can't make out is unclear, and the whole must match
           MIN_MATCH
  his voice  that it's his: read by a model that reads him (tools/narration.py TTS_MODELS), and his
           reading measured against the Host page's sample of his voice, pitch and timbre
           (tools/voiceprint.py). You discarded #62, #64 and #66 for a lighter, younger voice that this
           review had passed (2026-10-27): one that isn't his fails, and is read again
  pace     the words per second of each line, from the Animator's own timing of his voice (over
           LINE_PACE: rushed), and of the whole video (PACE)
  sound    loudness (Shorts play at -14 LUFS), clipping, and silence where his voice should be
  picture  a shot too dark to see, a clip that ran out and held its last frame, 1080x1920, a length
           within the settings (cases.max_seconds)
  look     one free Gemini look at FRAMES frames: text cut off, a broken or watermarked picture,
           anything unsuitable (a child, gore), and smaller things (hard to read, off topic); in the
           drawn look also letters or a signature inside a drawing, a drawing that isn't in his painted
           style, and twisted hands or faces

A problem is "major" (the video fails) or "minor" (only noted). Each major one says what would fix it:
take a number, name or the title off, swap a shot, draw a scene again (the drawn look: a drawing is
never swapped), read a line slower, more pauses, read it again, cut a line, or make it again. Every review is kept (note review:history, the last HISTORY), and
problems that keep coming back in the first look at a video (RECURRING of the last LOOKBACK) become
lessons (note review:lessons, read through agents/base.py lessons_for()): standing fixes the Animator
applies from the start, and advice for the Writer and the Researcher, so the same mistake is made less.

Usage:
    python -m agents.reviewer --id 12          # reviews Short #12's preview (.tmp/out/short_12.mp4)
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
import doc_render
import llm
import narration
import notify
import short_render
import voiceprint
from agents import animator
from agents.base import act, lessons_for, log
from common import load_config

CHECKS = 2                  # what a review covers: 2 = with his voice measured (2026-10-27); an older one is looked at again
MAX_ROUNDS = 2              # times the Animator may fix a video before it's turned down and made again from the start
REMAKE_WAITS = (0, 30, 60, 120, 240)  # minutes from a turn-down to the next making, by the times it was made again
MIN_MATCH = 0.85            # how much of the script must be heard in the final mix
UNCLEAR = 0.6               # a line heard less well than this is unclear
PACE = (1.6, 2.9)           # words per second over the whole video
LINE_PACE = 3.3             # a line read faster than this (words per second) is rushed
MIN_PACED_WORDS = 6         # shorter lines aren't judged on pace (a few quick words are fine)
LONG_PAUSE = 1.5            # seconds between two lines
LOUDNESS, LOUDNESS_OK, LOUDNESS_BAD = -14.0, 2.0, 3.0  # LUFS: off by more than OK is noted, by more than BAD fails
MAX_PEAK = -0.1             # dBTP: above this it may clip
DARK = "blackdetect=d=0.4:pic_th=0.85:pix_th=0.06"  # 85% of the picture near black for 0.4 s (the Professor stays lit)
DARK_FOR = 1.0              # seconds of a shot too dark to see before it fails
SILENT = "silencedetect=n=-50dB:d=1.0"
HEAR_RATE = 16_000          # whisper's sample rate
MIN_SECONDS = 20
MIN_ISSUE = 0.3             # seconds: words overlapping for less than this (a cut passing) don't count
AUDIT_STEP = doc_render.AUDIT_EVERY / doc_render.FPS
FRAMES = 8
HISTORY = 40
LOOKBACK, RECURRING = 12, 3
SIZE = (doc_render.W, doc_render.H)
WORDS = {"caption": "the captions", "number": "the big number", "name": "the name", "title": "the title"}
LOOK_PROBLEMS = {  # what the look may find: (fails the video, in words, fixed by swapping the shot)
    "text_cut_off": (True, "words cut off at the edge", False),
    "broken_picture": (True, "a broken, glitched or blank picture", True),
    "watermark": (True, "a watermark or channel logo in the footage", True),
    "child_visible": (True, "a child may be visible", True),
    "graphic": (True, "something graphic or disturbing", True),
    "text_overlap": (False, "words on top of each other", False),
    "hard_to_read": (False, "words hard to read against the picture", False),
    "stretched": (False, "a stretched or squashed picture", True),
    "off_topic": (False, "a picture that doesn't fit what's said", True),
    "host_glitch": (False, "the Professor looks wrong", False),
    "garbled_text": (True, "letters or a signature painted into a drawing", True),  # these three: the drawn look only
    "off_style": (True, "a drawing that isn't in his painted style", True),
    "bad_anatomy": (True, "a drawn person with twisted hands, limbs or face", True),
}
DRAWN_ONLY = ("garbled_text", "off_style", "bad_anatomy")


def _look_schema(problems) -> dict:
    return {"type": "object", "properties": {
        "frames": {"type": "array", "items": {"type": "object", "properties": {
            "frame": {"type": "integer"},
            "problems": {"type": "array", "items": {"type": "string", "enum": list(problems)}},
            "note": {"type": "string", "description": "what's wrong, in a few words; empty if nothing"}},
            "required": ["frame", "problems", "note"]}},
        "overall": {"type": "integer", "description": "0-10: how good the video looks"}},
        "required": ["frames", "overall"]}


LOOK_SCHEMA = _look_schema(p for p in LOOK_PROBLEMS if p not in DRAWN_ONLY)
LOOK_SYSTEM = """You review frames of a finished YouTube Short before it's posted: a documentary case told by a drawn,
anime-style old professor (the host: he belongs in the lower-left corner) over real footage, photos, maps and charts,
with captions in the middle that light up word by word, and sometimes a big number, a person's name (top left) or the
case title (at the start). A big number counts up before it lands, so a frame may show an in-between value: that's
fine. For each frame, list the problems you can see, if any:
- text_cut_off: the video's own words running off the edge of the frame or cut in half
- text_overlap: two of the video's own words or numbers on top of each other (text that's part of the footage, like a
  sign, doesn't count)
- hard_to_read: the video's words hard to read against the picture
- broken_picture: a glitched, corrupted or blank picture
- stretched: a squashed or stretched picture
- watermark: a stock site's watermark (Shutterstock, Getty, iStock, Pond5...) or a channel's logo burned into the footage
- child_visible: a child or a teenager is visible
- graphic: blood, injury, a dead body or something disturbing
- off_topic: the picture plainly clashes with what he's saying then (stock footage is illustrative: only a clash counts)
- host_glitch: the professor looks broken (cut off oddly, distorted, doubled)
Be strict about real defects and relaxed about style: most frames have no problems. overall: 0-10, how good it looks."""
DRAWN_LOOK = """- garbled_text: letters, words or a signature painted inside a drawn scene itself (not the video's own captions,
  name, number or title)
- off_style: a drawn scene that looks like a photograph or a 3D render instead of a painting in the professor's own style
- bad_anatomy: a drawn person with plainly twisted or extra limbs, hands or fingers, or a melted face
"""


def look_system(drawn: bool) -> str:
    """The look's instructions: the drawn look's videos are painted scenes in the host's style, with three more
    things to look for."""
    if not drawn:
        return LOOK_SYSTEM
    return (LOOK_SYSTEM.replace("over real footage, photos, maps and charts,",
                                "over scenes painted in his own art (real photos framed inside them, maps, charts),")
            .replace("(stock footage is illustrative: only a clash counts)",
                     "(the drawings are illustrative: only a clash counts)")
            .replace("(cut off oddly, distorted, doubled)\n", "(cut off oddly, distorted, doubled)\n" + DRAWN_LOOK))


def _swap_or_redraw(name: str) -> str:
    """How a shot the Reviewer turns down is fixed: a drawing is drawn again, anything else swapped."""
    return "redraw" if name.startswith("scene:") else "swap"
LESSONS = {  # a recurring problem -> what each agent takes from it: (agent, standing settings, advice)
    "rushed": [("animator", {"keep_gap": 0.28}, "Give him more room to breathe between sentences."),
               ("writer", {}, "Lines were read too fast in recent videos: keep each line to 14 words or fewer, one idea "
                              "per line.")],
    "fast": [("animator", {"keep_gap": 0.3}, "Leave longer pauses: whole videos ran too fast.")],
    "unclear": [("writer", {}, "The voice stumbled on some lines in recent videos: write names and numbers the way "
                               "they're said, and avoid abbreviations and tongue-twisters.")],
    "title": [("animator", {"title_until": 2.2}, "Take the case title off sooner: it kept colliding with other words.")],
    "number": [("writer", {}, "Big numbers kept colliding with the captions: give a number line few other words.")],
    "frozen": [("researcher", {"min_clip_seconds": 8}, "Clips ran out before their shot ended: prefer clips of 8 "
                                                       "seconds or more.")],
    "dark": [("researcher", {}, "Recent clips were too dark to see: skip night scenes and dim footage.")],
    "watermark": [("researcher", {}, "Footage with watermarks or logos got through: skip clips with any text burned in.")],
    "long": [("writer", {"seconds_under": 5}, "Recent scripts ran over the length limit: aim 5 seconds under the "
                                              "target.")],
}


def _issue(kind: str, severity: str, detail: str, line: int | None = None, at: float | None = None,
           fix: str | None = None, what: str | None = None) -> dict:
    return {"kind": kind, "severity": severity, "detail": detail, "line": line,
            "at": None if at is None else round(float(at), 2), "fix": fix, "what": what}


def _line_at(timing: list[dict], t: float) -> int:
    return max([k for k, line in enumerate(timing) if line["start"] - 0.15 <= t] or [0])


def _shot_at(shots: list[dict], t: float) -> dict | None:
    return next((s for s in shots if s["start"] <= t < s["end"]), shots[-1] if shots else None)


# --- what the renderer saw ----------------------------------------------------------

def words_on_screen(layout: list[dict]) -> list[dict]:
    """The layout audit's findings that lasted long enough to notice, each with its fix: a name or number comes off
    its line, the title comes off sooner; a held clip is swapped. Captions are never taken off."""
    issues = []
    for item in layout:
        span = item["end"] - item["start"] + AUDIT_STEP
        if span < MIN_ISSUE:
            continue
        line = item.get("line")
        if item["kind"] == "frozen":
            issues.append(_issue("frozen", "major", f"a clip ran out and stood still for {span:.1f} s", line,
                                 item["start"], "swap" if item["what"] and ":" in item["what"] else None, item["what"]))
            continue
        parts = str(item["what"]).split("+")
        movable = next((p for p in ("name", "number", "title") if p in parts), None)
        words = " and ".join(WORDS.get(p, p) for p in parts)
        detail = {"overlap": f"{words} overlap", "covers_host": f"{words} cover the Professor's face",
                  "unsafe": f"{words} reach under YouTube's buttons or title"}.get(item["kind"], words)
        issues.append(_issue("title" if movable == "title" else "number" if movable == "number" else item["kind"],
                             "major" if movable else "minor", f"{detail} for {span:.1f} s", line, item["start"],
                             "title" if movable == "title" else "drop" if movable else None, movable))
    return issues


# --- sound and picture ------------------------------------------------------------------

def probe(path: Path) -> dict:
    """One pass of ffmpeg over the video: its size, length and sound, its loudness and true peak, and the stretches
    that are too dark or silent."""
    err = subprocess.run([short_render.ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path), "-vf", DARK,
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


def sound_and_picture(found: dict, shots: list[dict], max_seconds: float) -> list[dict]:
    issues = []
    if found["size"] != SIZE:
        issues.append(_issue("size", "major", f"the video is {found['size']} instead of {SIZE[0]}x{SIZE[1]}",
                             fix="remake"))
    if not found["sound"]:
        issues.append(_issue("sound", "major", "the video has no sound", fix="remake"))
    if found["seconds"] > max_seconds + 1:
        issues.append(_issue("long", "major", f"{found['seconds']:.0f} s, over the {max_seconds:.0f} s limit", fix="trim"))
    elif found["seconds"] < MIN_SECONDS:
        issues.append(_issue("short", "major", f"only {found['seconds']:.0f} s long"))
    if found["loudness"] is not None and abs(found["loudness"] - LOUDNESS) > LOUDNESS_OK:
        bad = abs(found["loudness"] - LOUDNESS) > LOUDNESS_BAD
        issues.append(_issue("loudness", "major" if bad else "minor",
                             f"{found['loudness']:.1f} LUFS (Shorts play at {LOUDNESS:.0f})", fix="remake" if bad else None))
    if found["peak"] is not None and found["peak"] > MAX_PEAK:
        issues.append(_issue("peak", "minor", f"the sound peaks at {found['peak']:.1f} dB and may clip"))
    dark = []  # [shot, start, end, seconds]: one per shot (without a shot list, stretches under 0.5 s apart are one)
    for a, b in found["dark"]:
        shot = _shot_at(shots, (a + b) / 2) if shots else None
        last = dark[-1] if dark else None
        if last and (last[0] is shot if shot else a - last[2] <= 0.5):
            last[2], last[3] = b, last[3] + b - a
        else:
            dark.append([shot, a, b, b - a])
    for shot, a, _, seconds in dark:
        name, bad = (shot or {}).get("name"), seconds >= DARK_FOR
        issues.append(_issue("dark", "major" if bad else "minor", f"a shot too dark to see for {seconds:.1f} s",
                             (shot or {}).get("line"), a, _swap_or_redraw(name) if bad and name and ":" in name else None,
                             name))
    for a, b in found["silences"]:
        if b - a >= 1.0 and b < found["seconds"] - 1.0:
            issues.append(_issue("silence", "major", f"{b - a:.1f} s of silence", at=a, fix="reread"))
    return issues


# --- his voice --------------------------------------------------------------------------

def _sound(path: Path):
    """The video's sound as 16 kHz mono samples (floats from -1 to 1)."""
    import numpy as np

    raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(HEAR_RATE),
                          "-f", "s16le", "-"], capture_output=True, check=True, timeout=300).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def timing_by_ear(samples, lines: list[dict]) -> list[dict]:
    """Each line's start and end found by hearing the whole mix: only for a video made before the Animator kept its
    lines' times (on a whole mix, whisper can skip a stretch under the music, which squeezes those lines)."""
    return narration.align(lines, narration.hear_samples(samples, " ".join(line["text"] for line in lines)))[0]


def hearing(samples, lines: list[dict], timing: list[dict]) -> tuple[list[float], float]:
    """How clearly each line comes through in the final mix, music and all (0-1), and the share of the script heard.
    Each line's stretch is heard on its own and without the script as a hint, so a drowned line can't be "heard" from
    the hint. (Heard whole, #29 once came out at 60% with four lines missing: whisper had skipped 15 s under the
    music, though every line was clear. 2026-10-26.) A line that seems unclear alone is heard again with the lines
    on either side: alone, whisper heard "King Midas once welcomed a lost satyr" as "King Meat is once welcome to
    Lost Satter" (40%); with its neighbours, word for word (#35, 2026-10-26). Then what counts is how many of its own
    words are heard."""
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


def voice(lines: list[dict], timing: list[dict], clarity: list[float], match: float, seconds: float) -> list[dict]:
    issues = []
    if match < MIN_MATCH:
        issues.append(_issue("unclear", "major", f"only {match:.0%} of the script can be made out", fix="reread"))
    for k, (line, t, heard) in enumerate(zip(lines, timing, clarity)):
        if heard < UNCLEAR:
            issues.append(_issue("unclear", "major" if match >= MIN_MATCH else "minor",
                                 f"line {k + 1} is hard to make out ({heard:.0%} heard)", k, t["start"], "reread"))
        words, spoken = len(line["text"].split()), t["end"] - t["start"]
        if words >= MIN_PACED_WORDS and spoken > 0 and words / spoken > LINE_PACE:
            issues.append(_issue("rushed", "major", f"line {k + 1} is rushed ({words / spoken:.1f} words a second)", k,
                                 t["start"], "slower"))
    for k in range(1, len(timing)):
        gap = timing[k]["start"] - timing[k - 1]["end"]
        if gap > LONG_PAUSE:
            issues.append(_issue("pause", "minor", f"a {gap:.1f} s pause before line {k + 1}", k, timing[k - 1]["end"]))
    pace = sum(len(line["text"].split()) for line in lines) / max(seconds, 1)
    if pace > PACE[1]:
        issues.append(_issue("fast", "major", f"{pace:.1f} words a second over the video", fix="pauses"))
    elif pace < PACE[0]:
        issues.append(_issue("slow", "minor", f"only {pace:.1f} words a second over the video"))
    return issues


def his_voice(plan: dict, video_id: int) -> list[dict]:
    """Is it his voice: read by a model that reads him, and his reading (kept apart from the music) measured like the
    Host page's sample of his voice. One that isn't his fails, and is read again."""
    spoken = plan.get("voice") or {}
    if not animator.is_his({k: v for k, v in spoken.items() if k != "likeness"}):
        who = (spoken.get("voice") or "").rpartition("(")[2].rstrip(") ") or spoken.get("voice") or "another voice"
        return [_issue("not_his_voice", "major", f"read by {who}, which doesn't sound like him", fix="reread")]
    reading, his = animator.voice_dir(video_id) / "narration.wav", narration.his_voice(make=False)
    if not reading.exists() or not his:
        return []
    like = voiceprint.compare(voiceprint.measure(reading), his)
    return [] if like["his"] else [_issue("not_his_voice", "major", f"it doesn't sound like him: {like['why']}",
                                          fix="reread")]


# --- the look -----------------------------------------------------------------------------

def _grab(path: Path, at: float) -> bytes | None:
    try:
        return subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
                               "-frames:v", "1", "-vf", "scale=540:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4",
                               "-"], capture_output=True, check=True, timeout=60).stdout or None
    except (subprocess.SubprocessError, OSError):
        return None


def look(path: Path, plan: dict, timing: list[dict], seconds: float, progress=log) -> tuple[list[dict], int | None]:
    """One Gemini look at FRAMES frames (the opening, then evenly through the video); its findings and its score."""
    lines = plan["script"]["lines"]
    drawn = plan["script"].get("look") == "drawn"
    problems = {k: v for k, v in LOOK_PROBLEMS.items() if drawn or k not in DRAWN_ONLY}
    shots = (plan.get("render") or {}).get("shots") or []
    title_until = float((plan.get("render") or {}).get("title_until") or doc_render.TITLE_FOR)
    times = [1.0] + [round(seconds * (i + 0.5) / (FRAMES - 1), 2) for i in range(FRAMES - 1)]
    parts = [f"The case: {plan['script'].get('case_title', '')}. {len(times)} frames of the finished Short, in order:"]
    shown = {}
    for i, t in enumerate(times):
        jpg = _grab(path, t)
        if jpg:
            k = _line_at(timing, t)
            shown[i] = (t, k)
            parts += [f"Frame {i} at {t:.1f} s, while he says: \"{lines[k]['text']}\"", ("image/jpeg", jpg)]
    if not shown:
        return [_issue("look", "minor", "no frames could be taken for the look")], None
    advice = lessons_for("reviewer")["advice"]
    progress(f"Looking at {len(shown)} frames")
    answer = llm.generate_json(parts, _look_schema(problems), look_system(drawn)
                               + ("\nLearned so far:\n- " + "\n- ".join(advice) if advice else ""))
    issues = []
    for item in answer.get("frames") or []:
        if item.get("frame") not in shown:
            continue
        t, k = shown[item["frame"]]
        shot = _shot_at(shots, t) or {}
        for problem in dict.fromkeys(item.get("problems") or []):
            if problem not in problems:
                continue
            fails, words, swap = problems[problem]
            fix, what = None, None
            if swap and shot.get("name") and ":" in shot["name"]:
                fix, what = _swap_or_redraw(shot["name"]), shot["name"]
            elif problem == "text_cut_off":
                fix, what = ("title", "title") if t < title_until else (None, None)
            note = " ".join(str(item.get("note") or "").split())[:160]
            issues.append(_issue(problem, "major" if fails and fix else "minor",
                                 f"{words} at {t:.0f} s" + (f": {note}" if note else ""), k, t, fix, what))
    score = answer.get("overall")
    return issues, max(0, min(10, int(score))) if isinstance(score, (int, float)) else None


# --- the review -----------------------------------------------------------------------------

def current(plan: dict) -> dict | None:
    """The case's review if it's of the video as it is now (the render it names is the latest) and covers what a
    review checks now (CHECKS), else None."""
    review, made = plan.get("review"), plan.get("render") or {}
    if (review and made.get("id") and review.get("of") == made["id"]
            and (int(review.get("checks") or 1) >= CHECKS or review.get("override"))):
        return review
    return None


def review(row: dict, path: Path | None = None, progress=log) -> dict:
    """Watches the case's video; saves the verdict on the case (earlier rounds kept in its history) and returns it."""
    plan = row["plan"]
    path = path or animator.preview_path(row["id"])
    if not path.exists():
        raise RuntimeError(f"Short #{row['id']} has no video to review")
    lines = plan["script"]["lines"]
    made = plan.get("render") or {}
    max_seconds = float(load_config()["cases"].get("max_seconds", 90))
    progress("The Reviewer is watching the video")
    found = probe(path)
    shots = made.get("shots") or []
    issues = words_on_screen(made.get("layout") or []) + sound_and_picture(found, shots, max_seconds)
    progress("Listening to the Professor")
    samples = _sound(path)
    timing = made.get("lines")  # the Animator's times for each line: whisper's on his voice alone, exact
    if not timing or len(timing) != len(lines):
        timing = timing_by_ear(samples, lines)
    clarity, match = hearing(samples, lines, timing)
    issues += voice(lines, timing, clarity, match, found["seconds"]) + his_voice(plan, row["id"])
    try:
        seen, score = look(path, plan, timing, found["seconds"], progress)
        issues += seen
    except Exception as e:  # Gemini out: the rest of the review stands
        issues.append(_issue("look", "minor", f"the frames couldn't be looked at ({type(e).__name__})"))
        score = None
    major = [i for i in issues if i["severity"] == "major"]
    earlier = plan.get("review") or {}
    history = list(earlier.get("history") or [])
    if earlier.get("issues") is not None and earlier.get("of") != made.get("id"):  # a look at an earlier version
        history.append({k: earlier.get(k) for k in ("round", "passed", "at", "issues", "changes")})
    verdict = {"passed": not major, "round": (plan.get("fixes") or {}).get("round", 0), "of": made.get("id"),
               "checks": CHECKS, "at": db.now_iso(),
               "issues": issues, "changes": (plan.get("fixes") or {}).get("changes") or [], "history": history[-MAX_ROUNDS - 1:],
               "seconds": found["seconds"], "loudness": found["loudness"], "peak": found["peak"], "match": round(match, 3),
               "clarity": clarity, "look": score,
               "words_per_second": round(sum(len(line["text"].split()) for line in lines) / max(found["seconds"], 1), 2),
               "held": False}
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
            mine["advice"].append(f"{advice} ({count} of the last {len(first)} videos)")
    db.keep_note("review:lessons", {"reviews": len(first), "counts": dict(counts), "for": found, "updated_at": db.now_iso()})


def hold(video_id: int, why: str, progress=log) -> None:
    """The video still fails after the Animator's fixes: it's never posted as it is, and the Animator makes it again
    by itself (the loop: tools/jobs.py unmade(), animator.make_again) from `remake_at`: at once the first time, then
    after REMAKE_WAITS, until it passes. Nothing waits for you (your call, 2026-10-27)."""
    row = db.get_video(video_id)
    remakes = int(row["plan"].get("remakes") or 0)
    wait = REMAKE_WAITS[min(remakes, len(REMAKE_WAITS) - 1)]
    db.update_video(video_id, plan={**row["plan"], "review": {**(row["plan"].get("review") or {}), "held": True,
                                                               "held_because": why,
                                                               "remake_at": db.now_iso(timedelta(minutes=wait))}})
    title = (row["plan"].get("metadata") or {}).get("title") or row["theme"]
    progress(f"The Reviewer turned case #{video_id} down: {why}. The Animator makes it again by itself"
             + (f" in {wait} minutes" if wait else ""))
    if not remakes:  # (once a case: what follows needs nothing from you)
        notify.run(f"\U0001F50D The Reviewer turned a case down after the Animator's fixes:\n{title}\n{why}\n"
                   "The Animator makes it again by itself until it passes.")


def reviewed(row: dict, progress=log, now: bool = False) -> dict:
    """Agent 4 makes the case's video (unless it's made) and Agent 5 reviews it (unless it's reviewed). A video that
    fails goes back to Agent 4 with the notes, at most MAX_ROUNDS times; one that still fails is held. A video read
    by the old backup voice (removed 2026-10-27) is made again in his own voice. `now`: it's wanted now (its slot is
    due, or you asked), so Gemini's voice is asked even while it rests. Returns the case as it stands: its plan's
    review says whether it passed."""
    video_id = row["id"]

    def alive():  # a Short being made for its slot: keep its claim fresh (a stale claim means a run was cut off)
        if row["status"] == "making":
            db.update_video(video_id, claimed_at=db.now_iso())

    if (not animator.preview_path(video_id).exists() or not (row["plan"].get("render") or {}).get("id")
            or (row["plan"].get("voice") or {}).get("backup")):  # (from before reviews, or the old backup voice)
        animator.run(row, progress=progress, now=now)
        alive()
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
        if verdict.get("of") and fixes.get("after") == verdict["of"] and fixes.get("changes"):  # this review's fixes
            plan, changes = row["plan"], fixes["changes"]  # are in: it waited (for his voice), and is made now
        else:
            plan, changes = animator.improve(row["plan"])
        if not changes:
            hold(video_id, "nothing the Animator can change would fix: " + "; ".join(
                i["detail"] for i in verdict["issues"] if i["severity"] == "major")[:400], progress)
            return db.get_video(video_id)
        db.update_video(video_id, plan=plan)
        progress("Back to the Animator: " + "; ".join(changes))
        animator.run(db.get_video(video_id), progress=progress, now=now)
        alive()
        run(db.get_video(video_id), progress=progress)
        alive()
        row = db.get_video(video_id)


def passed(plan: dict) -> bool:
    """May the Publisher post it: reviewed and passed (or you said post it anyway), for the video as it is now."""
    verdict = current(plan) or {}
    return bool(verdict.get("passed") or verdict.get("override"))


def run(row: dict, progress=log) -> dict:
    def work(row, progress=log):
        verdict = review(row, progress=progress)
        major = [i for i in verdict["issues"] if i["severity"] == "major"]
        return {"video_id": row["id"], "passed": verdict["passed"], "round": verdict["round"] + 1,
                "problems": [i["detail"] for i in major][:6], "notes": len(verdict["issues"]) - len(major),
                "look": verdict["look"], "match": verdict["match"]}

    return act("reviewer", f"Review Short #{row['id']}", work, row, progress=progress)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--fix", action="store_true", help="if it fails, let the Animator fix it (the full loop)")
    args = parser.parse_args()
    try:
        row = db.get_video(args.id)
        if not row:
            raise RuntimeError(f"there's no Short #{args.id}")
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
