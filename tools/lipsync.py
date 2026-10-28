"""
Turns a spoken line into mouth shapes over time, with Rhubarb Lip Sync (MIT licence, runs on this
computer): A to H and X, Preston Blair's set. The Professor (tools/host.py) opens his mouth by them:
shut for X and A, then a little, more and wide.

Rhubarb is downloaded once into .tmp/models/rhubarb (~87 MB), and unpacked only if it's exactly the
published release (SHA256, measured 2026-10-28). Given the line's text it recognises
English well; if it's missing or fails, the mouth shapes come from the loudness of the audio
instead (rougher, but the mouth still moves with the words).
Measured 2026-10-25 on this PC: ~0.75 s per second of speech, so lines run in parallel.

Usage:
    python tools/lipsync.py --wav line.wav --text "Hello there"
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import wave
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from common import tmp_path

VERSION = "1.14.0"
RELEASE = f"https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v{VERSION}/"
PACKAGES = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}
SHA256 = {  # of each package's zip in the release: a download that differs is never unpacked or run
    "Windows": "62fa416a8d5e382a3828ee4bef358ce520d0b4cabdeaea75a7ac266d098d1fe3",
    "Linux": "a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667",
    "macOS": "f991deacac6c973a14a4431a16a58b842f436531e120cfaea142c87c0d3ab4c5",
}
TIMEOUT_S = 120


def _folder() -> Path:
    return tmp_path("models", "rhubarb", "x").parent


def ready() -> bool:
    """Whether Rhubarb is on this computer already (it downloads itself on first use otherwise)."""
    return any(_folder().glob("Rhubarb-Lip-Sync-*/rhubarb*"))


def ensure_rhubarb(progress=print) -> Path | None:
    """The rhubarb executable, downloaded and unpacked the first time. None if there's no build for
    this system or the download fails (the loudness fallback is used then)."""
    package = PACKAGES.get(platform.system())
    if not package:
        return None
    name = f"Rhubarb-Lip-Sync-{VERSION}-{package}"
    exe = _folder() / name / ("rhubarb.exe" if package == "Windows" else "rhubarb")
    if exe.exists():
        return exe
    try:
        progress("Downloading Rhubarb Lip Sync, once")
        archive, digest = _folder() / f"{name}.zip", hashlib.sha256()
        with requests.get(RELEASE + f"{name}.zip", stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(archive, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    digest.update(chunk)
                    f.write(chunk)
        if digest.hexdigest() != SHA256[package]:
            archive.unlink()
            raise RuntimeError("the download isn't the published release")
        with zipfile.ZipFile(archive) as z:
            z.extractall(_folder())
        archive.unlink()
        if package != "Windows":
            exe.chmod(0o755)
    except Exception as e:
        progress(f"Rhubarb isn't available ({e}); mouths will follow the loudness instead")
        return None
    return exe if exe.exists() else None


def loudness_cues(wav_path: Path, step: float = 1 / 24) -> list[dict]:
    """Mouth shapes from how loud each moment is: quiet X, then B, C and D as it gets louder."""
    import numpy as np

    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    hop = max(1, int(rate * step))
    levels = [float(np.sqrt(np.mean(samples[i:i + hop] ** 2))) for i in range(0, len(samples), hop)]
    peak = max(levels) if levels else 0.0
    cues = []
    for k, level in enumerate(levels):
        ratio = level / peak if peak else 0
        shape = "X" if ratio < 0.12 else "B" if ratio < 0.35 else "C" if ratio < 0.65 else "D"
        if cues and cues[-1]["value"] == shape:
            cues[-1]["end"] = round((k + 1) * step, 3)
        else:
            cues.append({"start": round(k * step, 3), "end": round((k + 1) * step, 3), "value": shape})
    return cues


def cues(wav_path: Path, text: str) -> list[dict]:
    """[{start, end, value}] in seconds from the start of the line."""
    exe = ensure_rhubarb()
    if exe:
        dialog = wav_path.with_suffix(".txt")
        dialog.write_text(text, encoding="utf-8")
        out = wav_path.with_suffix(".cues.json")
        result = subprocess.run([str(exe.resolve()), "-q", "-r", "pocketSphinx", "-f", "json", "-d", str(dialog.resolve()),
                                 str(wav_path.resolve()), "-o", str(out.resolve())],
                                capture_output=True, text=True, timeout=TIMEOUT_S)
        if result.returncode == 0 and out.exists():
            found = json.loads(out.read_text(encoding="utf-8")).get("mouthCues") or []
            if found:
                return [{"start": c["start"], "end": c["end"], "value": c["value"]} for c in found]
    return loudness_cues(wav_path)


def cues_for(lines: list[tuple[Path, str]]) -> list[list[dict]]:
    """Mouth shapes for several lines at once (each Rhubarb run uses one core)."""
    ensure_rhubarb()
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(lines)))) as pool:
        return list(pool.map(lambda item: cues(*item), lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--wav", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    try:
        found = cues(Path(args.wav), args.text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
