"""
Sound effects for the documentary cases, as 24 kHz mono samples: the three CC0 whooshes in
assets/sfx (decoded once into .tmp/sfx), plus an impact (a low hit, for a number landing) and a
riser (rising noise, before a reveal) made here in code, so there's nothing to license.

The faceless look's sounds go by the tags of your Agent 4 prompt: effect(tag) is the file named after the tag in assets/sfx (fetched by
tools/sfx_fetch.py, or one you put there, any common format), or for a few tags the sounds above; a tag with no sound is silent, and
never fails a video.

Usage:
    python tools/sfx.py --out .tmp/sfx   # writes impact.wav and riser.wav to listen to
"""

import argparse
import re
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

from common import ASSETS_DIR, tmp_path

SAMPLE_RATE = 24_000
SFX_DIR = ASSETS_DIR / "sfx"
SOUND_FILES = (".mp3", ".wav", ".ogg", ".m4a", ".flac")
IN_CODE = {"deep_sub_drop": "impact", "cinematic_boom": "impact", "bass_hit": "impact", "stamp_thud": "impact", "cinematic_riser": "riser"}
TAG = re.compile(r"[a-z0-9_]{1,40}")


@lru_cache(maxsize=1)
def whooshes() -> tuple:
    import numpy as np

    import short_render

    out = []
    for src in sorted(SFX_DIR.glob("whoosh*.mp3")):
        dest = tmp_path("sfx", src.stem + ".wav")
        if not dest.exists():
            subprocess.run([short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                            "-ac", "1", "-ar", str(SAMPLE_RATE), str(dest)], check=True, timeout=60)
        with wave.open(str(dest), "rb") as w:
            out.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768)
    return tuple(out)


@lru_cache(maxsize=1)
def impact():
    """A deep cinematic hit: a falling sine thump, a little noise for the attack, a long soft tail."""
    import numpy as np

    n = int(1.4 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 38 + 52 * np.exp(-t * 9)  # 90 Hz falling to 38 Hz
    body = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.exp(-t * 3.2)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n) * np.exp(-t * 38)
    noise = np.convolve(noise, np.ones(6) / 6, mode="same")  # take the hiss off
    sub = np.sin(2 * np.pi * 32 * t) * np.exp(-t * 2.2) * 0.5
    out = body * 0.9 + noise * 0.35 + sub
    return (out / np.abs(out).max() * 0.9).astype(np.float32)


@lru_cache(maxsize=1)
def riser():
    """Noise that swells and rises in pitch over about a second and a half, cut off at the top."""
    import numpy as np

    n = int(1.5 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    rng = np.random.default_rng(11)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    state, prev = 0.0, 0.0
    for i in range(n):  # a one-pole low-pass that opens up as it rises
        a = 0.02 + 0.5 * (t[i] / t[-1]) ** 2
        state += a * (noise[i] - state)
        out[i] = state - prev * 0.6
        prev = state
    tone = np.sin(2 * np.pi * np.cumsum(220 + 660 * (t / t[-1]) ** 2) / SAMPLE_RATE) * 0.25
    env = (t / t[-1]) ** 2.2
    out = (out / np.abs(out).max() + tone) * env
    return (out / np.abs(out).max() * 0.8).astype(np.float32)


def _decoded(path: Path, rate: int):
    import numpy as np

    import short_render

    raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le",
                          "-"], capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


@lru_cache(maxsize=64)
def effect(tag: str, rate: int = 44_100):
    """The sound for a tag of the Agent 4 prompt at its full level (the design sets how loud), or None if it has none."""
    import numpy as np

    if not TAG.fullmatch(tag or ""):
        return None
    sound = None
    found = next((p for p in sorted(SFX_DIR.glob(f"{tag}.*")) if p.suffix.lower() in SOUND_FILES), None)
    try:
        if found:
            sound = _decoded(found, rate)
        elif tag in IN_CODE:
            made = {"impact": impact, "riser": riser}[IN_CODE[tag]]()
            sound = np.interp(np.arange(int(len(made) * rate / SAMPLE_RATE)) * SAMPLE_RATE / rate, np.arange(len(made)), made)
        elif tag.startswith("whoosh") and whooshes():
            made = whooshes()[0 if tag == "whoosh_fast" else -1]
            sound = np.interp(np.arange(int(len(made) * rate / SAMPLE_RATE)) * SAMPLE_RATE / rate, np.arange(len(made)), made)
    except (OSError, subprocess.SubprocessError):
        return None
    if sound is None or not len(sound):
        return None
    peak = float(np.abs(sound).max())
    return (sound / peak * 0.95).astype(np.float32) if peak > 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--out", default=str(tmp_path("sfx", "x").parent))
    args = parser.parse_args()
    import numpy as np

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, sound in (("impact", impact()), ("riser", riser())):
        with wave.open(str(out / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes((np.clip(sound, -1, 1) * 32767).astype(np.int16).tobytes())
        print(f"Wrote {out / name}.wav ({len(sound) / SAMPLE_RATE:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
