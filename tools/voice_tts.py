"""
Gives each host a voice: Kokoro (open-source, Apache 2.0 licence) turns a line into speech
on this computer's CPU, so nothing is sent anywhere and nothing costs money.

The model (~120 MB) is downloaded once into .tmp/models/kokoro the first time it's needed.
Measured 2026-10-25 on this PC: ~3x faster than real time (a 3 s line in ~1 s), plus ~1.5 s to
load the model once. Silence at the start and end of each line is trimmed, so the timing of the
dialogue comes from the renderer's pauses, not from the model. Money is read the way people say it
("$5.4 billion" as "5.4 billion dollars").

Usage:
    python tools/voice_tts.py --voice af_heart --text "Hello there" --out .tmp/out/hello.wav
"""

import argparse
import re
import sys
import threading
import wave
from pathlib import Path

import requests

import character_spec
from common import tmp_path

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")  # int8: the small, CPU-friendly model
SAMPLE_RATE = 24_000
TRIM_MARGIN = 0.04  # seconds of silence kept before and after the words

_engine = None
_lock = threading.Lock()


def model_dir() -> Path:
    return tmp_path("models", "kokoro", "x").parent


def ready() -> bool:
    """Whether the model is on this computer already (it downloads itself on first use otherwise)."""
    return all((model_dir() / name).exists() for name in MODEL_FILES)


def ensure_model(progress=print) -> Path:
    """Downloads the model files if they're missing (once; ~120 MB)."""
    folder = model_dir()
    for name in MODEL_FILES:
        path = folder / name
        if path.exists():
            continue
        progress(f"Downloading the voice model ({name}), once")
        partial = path.with_suffix(".part")
        with requests.get(MODEL_URL + name, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    f.write(chunk)
        partial.replace(path)
    return folder


def _kokoro():
    global _engine
    with _lock:
        if _engine is None:
            from kokoro_onnx import Kokoro  # imported here: the cloud app never needs it

            folder = ensure_model()
            _engine = Kokoro(str(folder / MODEL_FILES[0]), str(folder / MODEL_FILES[1]))
    return _engine


CURRENCY = {"$": "dollars", "€": "euros", "£": "pounds", "₹": "rupees", "¥": "yen"}
MONEY = re.compile(r"(US|A|C|HK)?([$€£₹¥])\s?(\d[\d,]*(?:\.\d+)?)(\s?(?:thousand|million|billion|trillion|bn|m)\b)?")


def _money(m: re.Match) -> str:
    """"$5.4 billion" -> "5.4 billion dollars", "US$7.8bn" -> "7.8 billion US dollars"."""
    scale = {"bn": " billion", "m": " million"}.get((m.group(4) or "").strip(), m.group(4) or "")
    country = {"US": "US ", "A": "Australian ", "C": "Canadian ", "HK": "Hong Kong "}.get(m.group(1) or "", "")
    return f"{m.group(3)}{scale} {country}{CURRENCY[m.group(2)]}"


def _spoken(text: str) -> str:
    """What the model reads aloud: money and symbols as words, no emoji."""
    text = MONEY.sub(_money, text)
    text = text.replace("&", " and ").replace("%", " percent").replace("@", " at ")
    text = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️‍]", "", text)
    return " ".join(text.split())


def speak(text: str, voice: str, speed: float, out: Path) -> float:
    """Says `text` in `voice` and writes a 16-bit mono WAV; returns its length in seconds."""
    import numpy as np

    engine = _kokoro()
    with _lock:  # one line at a time: the model already uses every core
        samples, rate = engine.create(_spoken(text), voice=voice, speed=speed, lang=character_spec.voice_lang(voice))
    samples = np.asarray(samples, dtype=np.float32)
    loud = np.flatnonzero(np.abs(samples) > max(0.02, float(np.abs(samples).max()) * 0.04))
    if loud.size:
        margin = int(TRIM_MARGIN * rate)
        samples = samples[max(0, loud[0] - margin): loud[-1] + margin]
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return len(samples) / rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--voice", default="af_heart", choices=list(character_spec.VOICES))
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", default=str(tmp_path("out", "voice.wav")))
    args = parser.parse_args()
    try:
        seconds = speak(args.text, args.voice, args.speed, Path(args.out))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out} ({seconds:.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
