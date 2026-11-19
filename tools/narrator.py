"""
The series' narrator: the voice that tells every story, calm and warm, like a kind mentor late at night (your choice,
2026-11-16: Algieba, picked from four warm voices in style test 2; settings series.narrator, chosen on the dashboard's
Narrator page).

Gemini's text-to-speech (free tier, tools/narration.py) reads the story's lines in the narrator's voice and persona, in
parts of at most PART_WORDS words (one reading each: a long reading takes longer to come back and drifts more), every
line with its own direction. faster-whisper hears each part back and times every word; then each line is cut out on its
own (cut_lines: where the sound really starts and stops, never inside a word), because the film puts every line over its
own shot (tools/story_film.py). Pauses inside a line are kept up to KEEP_GAP: his delivery is unhurried.

The narrator has one voice: only the models that take his persona read him (narration.TTS_MODELS),
every reading is measured against his sample (tools/voiceprint.py: SAMPLE_LINES read by the voice you chose), and when the
day's free readings are used up the story waits for them (narration.VoiceUnavailable; agents/animator.py rests). Parts
already read are kept with the story (each named by its words, directions and voice), so a story read again after a
change only reads the parts that changed.

A direction never asks for a louder, higher or projected voice (voice_direction, used by Agent 3's storyboard and the
short version's writer): Gemini then reads him off his own voice, and a line it can't read like him holds the whole
story (#7's closing line, "resonant, calm", 2026-11-17/18). A big moment is slower and firmer, not louder. A reading
that still comes out unlike him is brought down or read steadier by tools/narration.py.

Measured 2026-11-16 in this persona (gemini-3.8-flash-lite-tts, the six lines below, 51 words): Algieba 22.0 s of lines
(2.3 words a second), Umbriel 23.3, Achird 23.3, Sadaltager 24.0; every word heard back. Their readings of these lines are
their samples on the Narrator page (style test 2's), so choosing among them costs no reading.

Usage:
    python tools/narrator.py --sample                 # the chosen voice's sample (one reading if it isn't made yet)
    python tools/narrator.py --text "He woke at five." --text "Nobody saw." --out .tmp/out/narrator
"""

import argparse
import hashlib
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

import narration
import series
from common import tmp_path

SAMPLE_LINES = narration.SAMPLE_LINES  # what his samples say (the Narrator page plays them): style test 2's
VOICES = narration.VOICES  # four warm male voices, heard in style test 2 (2026-11-16)
KEEP_GAP = 0.65        # seconds: a pause inside a line is kept up to this (narration.tighten)
PART_WORDS = 90        # words in one reading at most
QUIET_DB = 38          # dB under the voice's usual level: quiet enough to cut there
LEAD, TAIL = 0.07, 0.28  # seconds kept before a line's first sound and after its last (his breath in, the word's ring)
FADE = 0.012
WORDS_PER_SECOND = 2.3   # his pace inside a line, pauses included (Algieba, 2026-11-16: 51 words in 22.0 s; for estimates)
# What in a direction pushes Gemini's voice up and off his own: louder, higher, projected, excited.
PUSHES_UP = re.compile(r"\b(?:loud\w*|shout\w*|yell\w*|scream\w*|boom\w*|resonan\w*|resound\w*|project\w*|"
                       r"high(?:er|est)?|shrill\w*|excit\w*|frantic\w*|thunder\w*|bellow\w*|roar\w*)\b", re.I)


class Unavailable(narration.VoiceUnavailable):
    pass


def voice_direction(direction: str | None) -> str:
    """A line's direction as his voice is given it: each of its parts (between commas) that asks for a louder, higher or
    projected voice left out, the rest kept as written ("resonant, calm" -> "calm"; "loud, sharp" -> "sharp")."""
    parts = [p.strip() for p in re.split(r"[,;]", direction or "")]
    return ", ".join(p for p in parts if p and not PUSHES_UP.search(p))


def voice_cfg(override: dict | None = None) -> dict:
    """The narrator's settings (series.narrator), with any of `override`'s."""
    return {**series.narrator(), **(override or {})}


def sample_path(cfg: dict | None = None) -> Path:
    cfg = voice_cfg(cfg)
    return narration.sample_path(cfg["name"], int(cfg.get("deeper") or 0), cfg["style"], SAMPLE_LINES)


def sample(cfg: dict | None = None, progress=print) -> dict:
    """The voice's sample in the narrator's persona (one free reading, kept): what you choose him by, and what every
    reading of his is measured against."""
    cfg = voice_cfg(cfg)
    return narration.sample(cfg["name"], int(cfg.get("deeper") or 0), cfg["style"], progress, lines=SAMPLE_LINES,
                            keep_gap=KEEP_GAP)


def estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_SECOND


def parts(lines: list[dict]) -> list[list[int]]:
    """The lines grouped into readings of at most PART_WORDS words, in order (a longer line is a part of its own)."""
    out, words = [], 0
    for k, line in enumerate(lines):
        n = len(line["text"].split())
        if out and words + n <= PART_WORDS:
            out[-1].append(k)
            words += n
        else:
            out.append([k])
            words = n
    return out


def part_names(lines: list[dict], take: int = 0, cfg: dict | None = None) -> list[str]:
    """Each part's reading as read() keeps it in its folder (part_<key>: .wav, .json, and .steady when it was read the
    steady way), in order: how a part already read is known (tools/jobs.py keep_videos)."""
    cfg = voice_cfg(cfg)
    return [f"part_{_key([lines[k] for k in group], cfg, take)}" for group in parts(lines)]


def _key(lines: list[dict], cfg: dict, take: int) -> str:
    said = [[line["text"], line.get("direction", "")] for line in lines]
    return hashlib.sha1(json.dumps([said, [cfg.get(k) for k in ("name", "model", "style", "deeper")], take, KEEP_GAP,
                                    narration.CUT_RULES], sort_keys=True).encode("utf-8")).hexdigest()[:14]


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).copy(), w.getframerate()


def _write_wav(path: Path, pcm: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype(np.int16).tobytes())


def _levels(pcm: np.ndarray, rate: int, frame: float = 0.01) -> np.ndarray:
    step = int(frame * rate)
    n = len(pcm) // step
    if not n:
        return np.zeros(0)
    x = pcm[:n * step].astype(np.float32).reshape(n, step)
    level = 20 * np.log10(np.sqrt((x ** 2).mean(axis=1)) + 1.0)
    return level - np.percentile(level, 90)


def cut_lines(wav: Path, timed: list[dict], folder: Path, names: list[str]) -> list[dict]:
    """Each line of a reading cut out into its own WAV: from just before its first sound to just after its last, found
    in the sound itself (whisper's times only say where to look: its word ends come early). Between two lines the cut is
    at the quietest point of the gap. Returns [{"wav", "seconds", "from"}] in order (from: the second of the reading the
    line's own sound starts at: its words' times, less this, are their times in its own sound, for the subtitles)."""
    pcm, rate = _read_wav(wav)
    level = _levels(pcm, rate)
    loud = level > -QUIET_DB
    frames = len(level)

    def frame(t):
        return max(0, min(frames, int(round(t / 0.01))))

    bounds = []  # where each line may start and end (the quietest points between neighbours)
    for k, t in enumerate(timed):
        if k == 0:
            a = 0
        else:
            x, y = sorted((frame(timed[k - 1]["end"]), frame(t["start"])))
            y = max(y, x + 1)
            a = x + int(np.argmin(level[x:y])) if y <= frames and y > x else x
        bounds.append(a)
    bounds.append(frames)
    out = []
    for k, t in enumerate(timed):
        lo, hi = bounds[k], bounds[k + 1]
        sound = np.nonzero(loud[lo:hi])[0]
        if len(sound):
            first, last = lo + sound[0], lo + sound[-1] + 1
        else:
            first, last = frame(t["start"]), frame(t["end"])
        a = max(lo * 0.01, first * 0.01 - LEAD)
        b = min(hi * 0.01, last * 0.01 + TAIL)
        piece = pcm[int(a * rate):int(b * rate)].astype(np.float32)
        f = min(len(piece) // 4, int(FADE * rate))
        if f:
            piece[:f] *= np.linspace(0, 1, f)
            piece[-f:] *= np.linspace(1, 0, f)
        path = folder / f"{names[k]}.wav"
        _write_wav(path, np.clip(piece, -32768, 32767), rate)
        out.append({"wav": str(path), "seconds": round(len(piece) / rate, 3), "from": round(int(a * rate) / rate, 4)})
    return out


def read(lines: list[dict], folder: Path, cfg: dict | None = None, take: int = 0, progress=print) -> dict:
    """The story's lines ([{text, direction}]) read by the narrator, part by part, each line cut out on its own into
    `folder`. Returns {"voice", "engine", "match", "likeness", "deeper", "readings", "lines": [{"wav", "seconds"}]}.
    Raises narration.VoiceUnavailable when none of his models can read now (`until`: their free readings renew)."""
    cfg = voice_cfg(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    timed_lines: list[dict | None] = [None] * len(lines)
    matches, likeness, voice, readings = [], [], None, 0
    for group in parts(lines):
        part = [lines[k] for k in group]
        key = _key(part, cfg, take)
        kept = folder / f"part_{key}.json"
        try:
            spoken = json.loads(kept.read_text(encoding="utf-8"))
            if not Path(spoken["wav"]).exists():
                raise OSError
        except (OSError, ValueError, KeyError):
            spoken = narration.narrate(part, folder / f"part_{key}.wav", cfg, progress, keep_gap=KEEP_GAP,
                                       sample_lines=SAMPLE_LINES)
            kept.write_text(json.dumps(spoken), encoding="utf-8")
            readings += 1
        voice = spoken["voice"]
        matches.append(spoken["match"])
        if spoken.get("likeness"):
            likeness.append(spoken["likeness"])
        cut = cut_lines(Path(spoken["wav"]), spoken["lines"], folder, [f"line_{key}_{j}" for j in range(len(group))])
        for j, k in enumerate(group):
            timed_lines[k] = {**cut[j], "words": spoken["lines"][j].get("words") or []}
    keep = {Path(t["wav"]).name for t in timed_lines if t} | {f"part_{_key([lines[k] for k in g], cfg, take)}{x}"
                                                               for g in parts(lines) for x in (".wav", ".json")}
    for old in folder.glob("*"):  # (parts and lines of earlier versions of the script)
        if old.name not in keep:
            old.unlink(missing_ok=True)
    worst = max(likeness, key=lambda m: m.get("timbre") or 0) if likeness else None  # (the least like him)
    return {"voice": voice, "engine": "gemini", "match": round(min(matches), 3) if matches else 0.0,
            "likeness": worst, "his": all(m.get("his", True) for m in likeness), "deeper": int(cfg.get("deeper") or 0),
            "readings": readings, "lines": timed_lines,
            "seconds": round(sum(t["seconds"] for t in timed_lines), 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--sample", action="store_true", help="the chosen voice's sample")
    parser.add_argument("--text", action="append", default=[])
    parser.add_argument("--out", default=str(tmp_path("out", "narrator", "x").parent))
    args = parser.parse_args()
    try:
        if args.sample:
            print(json.dumps(sample(), indent=2))
            return 0
        result = read([{"text": t, "direction": ""} for t in args.text], Path(args.out))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
