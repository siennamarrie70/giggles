"""
The Professor: the host on screen in every documentary case, the user's own character drawn from
their character sheet (tools/host_prep.py made his pieces once, in assets/host/). He floats in the
lower-left corner for the whole video, turned toward the middle: a slow bob, a slight sway and tilt,
a small nod as each line starts, a blink every few seconds, and his mouth moving with the words.

His mouth shapes come from Rhubarb Lip Sync (tools/lipsync.py), run on every line's stretch of the
narration at once, and are held two frames at a time, like hand-drawn animation. Each of his
movements repeats a whole number of times over the video, so the last frame flows into the first
when the Short loops. A soft shadow behind him keeps him readable over bright footage, and his chest
fades out above YouTube's title text.

  mouth_track(wav, lines)   how open his mouth is, when: [[start, end, 1-3], ...] (closed otherwise)
  Host(...)                 .draw(frame, t) puts him on a frame; .box is all the room he moves in

Usage:
    python tools/host.py [--text "Fourteen years later, it was gone."] [--size L]   # a test clip in .tmp/out
"""

import argparse
import bisect
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image

import lipsync
from common import ASSETS_DIR, TMP_DIR, tmp_path

HOST_DIR = ASSETS_DIR / "host"
W, H, FPS = 1080, 1920, 24
SIZES = {"S": 380, "M": 440, "L": 480}  # his width on screen, px
LEFT, BOTTOM = 6, 1592                 # his left edge, and where his chest has faded out (YouTube's text is below)
FADE = (0.80, 0.995)                   # his chest fades out over this part of his height
GLOW = 0.45                            # how dark the soft shadow behind him gets
MARGIN = 70                            # room around him for the shadow and the motion
BOB, BOB_S = 9.0, 4.2                  # the slow float: px, seconds
SWAY, SWAY_S = 4.0, 6.3
TILT, TILT_S = 0.9, 5.1                # degrees
NOD, NOD_S = 5.0, 0.5                  # as a line starts: px down, seconds
BLINK_EVERY = (2.0, 6.0)               # seconds between blinks; now and then a double blink
BLINK = ("half", "closed", "closed", "half")  # a blink, frame by frame
SHAPES = {"B": 1, "F": 1, "G": 1, "C": 2, "E": 2, "H": 2, "D": 3}  # Rhubarb's shapes -> his openings (X, A shut)
EYES = (None, "half", "closed")


def mouth_track(wav: Path | str, lines: list[dict]) -> list[list]:
    """How open his mouth is over the narration ([[start, end, 1-3], ...]; shut the rest of the time). Each line's
    stretch of the WAV goes through Rhubarb with its words, all at once."""
    with wave.open(str(wav), "rb") as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        pcm = w.readframes(w.getnframes())
    step = width * channels
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="mouth_", dir=TMP_DIR / "work"))
    pieces = []
    for k, line in enumerate(lines):
        start = max(0.0, line["start"] - 0.08)
        until = lines[k + 1]["start"] - 0.05 if k + 1 < len(lines) else line["end"] + 0.3
        path = folder / f"line_{k}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(width)
            out.setframerate(rate)
            out.writeframes(pcm[int(start * rate) * step:int((line["end"] + 0.15) * rate) * step])
        pieces.append((path, line["text"], start, until))
    try:
        found = lipsync.cues_for([(path, text) for path, text, _, _ in pieces])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    track = []
    for (_, _, start, until), cues in zip(pieces, found):
        for cue in cues:
            level = SHAPES.get(cue["value"], 0)
            a, b = start + cue["start"], min(start + cue["end"], until)
            if level and b > a:
                track.append([round(a, 3), round(b, 3), level])
    return sorted(track)


# --- his drawings -------------------------------------------------------------

def _load(name: str) -> np.ndarray:
    """An RGBA drawing as floats with the colour premultiplied by alpha (so edges never pick up stray colour)."""
    a = np.asarray(Image.open(HOST_DIR / name).convert("RGBA"), dtype=np.float32)
    a[:, :, 3] /= 255
    a[:, :, :3] *= a[:, :, 3:]
    return a


def _over(dst: np.ndarray, src: np.ndarray, at: tuple[int, int]) -> None:
    x, y = at
    h, w = src.shape[:2]
    region = dst[y:y + h, x:x + w]
    region[:] = src + region * (1 - src[:, :, 3:])


class Host:
    """The Professor for one video: his twelve drawings (four mouths, three eye states) at his size, with his
    shadow, and the timing of his blinks, nods and mouth."""

    def __init__(self, total: float, lines: list[dict], track: list, seed: int = 0, size: str = "M"):
        import cv2

        rig = json.loads((HOST_DIR / "rig.json").read_text(encoding="utf-8"))
        base = _load("base.png")
        mouths = [None] + [(_load(m["file"]), tuple(m["at"])) for m in rig["mouths"]]
        lids = {state: (_load(e["file"]), tuple(e["at"])) for state, e in rig["eyes"].items()}
        bh, bw = base.shape[:2]
        width = SIZES.get(str(size).upper(), SIZES["M"])
        scale = width / bw
        sw, sh = width, round(bh * scale)
        y = np.arange(bh, dtype=np.float32)[:, None, None] / bh
        fade = np.clip((FADE[1] - y) / (FADE[1] - FADE[0]), 0, 1)
        fade = fade * fade * (3 - 2 * fade)
        cw, ch = sw + 2 * MARGIN, sh + 2 * MARGIN
        shadow = np.zeros((ch, cw), dtype=np.float32)
        cv2.ellipse(shadow, (MARGIN + round(sw * 0.52), MARGIN + round(sh * 0.46)), (round(sw * 0.56), round(sh * 0.5)),
                    0, 0, 360, GLOW, -1)
        shadow = cv2.GaussianBlur(shadow, (0, 0), 38)
        sy = (np.arange(ch, dtype=np.float32)[:, None] - MARGIN) / sh
        shadow *= np.clip((FADE[1] - sy) / (FADE[1] - FADE[0]), 0, 1)
        self.sprites = {}
        for m, mouth in enumerate(mouths):
            for eye in EYES:
                img = base.copy()
                for part in (mouth, lids.get(eye)):
                    if part:
                        _over(img, *part)
                img *= fade
                small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
                canvas = np.zeros((ch, cw, 4), dtype=np.float32)
                canvas[:, :, 3] = shadow
                _over(canvas, small, (MARGIN, MARGIN))
                self.sprites[(m, eye)] = canvas
        self.size = (cw, ch)
        self.at = (LEFT - MARGIN, BOTTOM - sh - MARGIN)  # where the canvas's corner sits on the frame
        self.pivot = (MARGIN + rig["pivot"][0] * scale, MARGIN + rig["pivot"][1] * scale)
        fx0, fy0, fx1, fy1 = rig["face"]
        top = BOTTOM - sh
        reach = BOB + 3
        self.box = (max(0, round(LEFT - SWAY)), round(top - reach), round(LEFT + sw + SWAY), BOTTOM)
        self.face = (round(LEFT + fx0 * scale - SWAY), round(top + fy0 * scale - reach),
                     round(LEFT + fx1 * scale + SWAY), round(top + fy1 * scale + reach + NOD))
        # Whole cycles over the video, so the end flows back into the start.
        cycles = lambda period: total / max(1, round(total / period))  # noqa: E731
        self.bob_s, self.sway_s, self.tilt_s = cycles(BOB_S), cycles(SWAY_S), cycles(TILT_S)
        self.nods = [line["start"] for line in lines]
        rng = random.Random(seed)
        self.blinks, at = [], rng.uniform(0.8, 2.4)
        while at < total - 0.6:
            self.blinks.append(at)
            if rng.random() < 0.15:  # a double blink; the next one is counted from its second half
                at += 0.28
                self.blinks.append(at)
            at += rng.uniform(*BLINK_EVERY)
        self.track = sorted(track)
        self._starts = [c[0] for c in self.track]

    def mouth(self, t: float) -> int:
        """His mouth's opening at t (0 shut, 3 wide), changing at most every two frames."""
        t = (int(t * FPS) // 2 * 2) / FPS
        k = bisect.bisect_right(self._starts, t) - 1
        return self.track[k][2] if k >= 0 and t < self.track[k][1] else 0

    def eyes(self, t: float):
        for at in self.blinks:
            k = int((t - at) * FPS)
            if 0 <= k < len(BLINK):
                return BLINK[k]
        return None

    def motion(self, t: float) -> tuple[float, float, float]:
        """(x, y, degrees): the float, the sway, the tilt and the nods."""
        nod = sum(math.sin(math.pi * (t - s) / NOD_S) for s in self.nods if 0 <= t - s < NOD_S)
        x = SWAY * math.sin(2 * math.pi * t / self.sway_s + 1.1)
        y = BOB * math.sin(2 * math.pi * t / self.bob_s) + 2.5 * math.sin(4 * math.pi * t / self.bob_s + 0.7) + NOD * nod
        return x, y, TILT * math.sin(2 * math.pi * t / self.tilt_s + 0.4) - 0.6 * nod

    def draw(self, frame: np.ndarray, t: float) -> np.ndarray:
        import cv2

        sprite = self.sprites[(self.mouth(t), self.eyes(t))]
        dx, dy, angle = self.motion(t)
        m = cv2.getRotationMatrix2D(self.pivot, angle, 1.0)
        m[0, 2] += dx
        m[1, 2] += dy
        cw, ch = self.size
        moved = cv2.warpAffine(sprite, m, (cw, ch), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        x, y = self.at
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + cw), min(H, y + ch)
        part = moved[y0 - y:y1 - y, x0 - x:x1 - x]
        region = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = np.clip(part[:, :, :3] + region * (1 - part[:, :, 3:]), 0, 255).astype(np.uint8)
        return frame


TEST_LINES = ["Every story has a lesson...", "if you know how to listen."]  # his own words, from the sheet


def test_clip(out: Path, lines: list[str] | None = None, size: str | None = None, progress=print) -> dict:
    """A few seconds of him saying `lines` (his line from the sheet by default) in his current voice and size, over a
    plain dark backdrop: one free Gemini voice call. For the dashboard's Host page."""
    import narration
    import short_render
    from common import load_config

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    texts = [{"text": t, "direction": "warm, unhurried"} for t in (lines or TEST_LINES)]
    spoken = narration.narrate(texts, out.with_suffix(".wav"), progress=progress)
    timed = [{**line, **t} for line, t in zip(texts, spoken["lines"])]
    total = spoken["seconds"] + 0.6
    progress("Drawing him")
    him = Host(total, timed, mouth_track(spoken["wav"], timed), size=size or (load_config().get("host") or {}).get("size", "M"))
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    backdrop = ((1 - y) * np.array([40, 52, 70], np.float32) + y * np.array([14, 18, 26], np.float32)).astype(np.uint8)
    backdrop = np.ascontiguousarray(np.broadcast_to(backdrop, (H, W, 3)))
    cmd = [short_render.ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-framerate", str(FPS), "-i", "-", "-i", spoken["wav"], "-c:v", "libx264", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-af", "apad", "-t", f"{total:.2f}", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for n in range(math.ceil(total * FPS)):
            proc.stdin.write(him.draw(backdrop.copy(), n / FPS).tobytes())
        proc.stdin.close()
        proc.wait(timeout=300)
    finally:
        out.with_suffix(".wav").unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg couldn't encode the test clip")
    return {"path": str(out), "seconds": round(total, 1), "voice": spoken["voice"], "match": spoken["match"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--text", action="append", help="a line (repeat for more); his line from the sheet if none")
    parser.add_argument("--size", choices=list(SIZES))
    parser.add_argument("--out", default=str(tmp_path("out", "host_test.mp4")))
    args = parser.parse_args()
    try:
        result = test_clip(Path(args.out), args.text, args.size)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {result['path']} ({result['voice']}, match {result['match']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
