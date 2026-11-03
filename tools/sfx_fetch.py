"""
Finds a free sound for each sound-effect tag of your Agent 4 prompt and keeps it as assets/sfx/<tag>.mp3. Pixabay, which the prompt
names, has no sounds in its API (its documentation lists only images and videos), so these come from Openverse's search of
Creative Commons sounds, CC0 only: nothing to credit, safe in a public repository, and each is recorded in assets/sfx/sfx.yaml.
You can replace any of them: a file named after the tag in assets/sfx/ is the sound used.

Run once, by hand. It never replaces a sound that's already there unless you name its tag.

Usage:
    python tools/sfx_fetch.py                     # the tags that have no sound yet
    python tools/sfx_fetch.py gavel_bang ...      # these tags again
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

import a4
import short_render
from common import ASSETS_DIR

SEARCH = "https://api.openverse.org/v1/audio/"
SFX_DIR = ASSETS_DIR / "sfx"
RECORD = SFX_DIR / "sfx.yaml"
MAX_DOWNLOAD = 12 << 20
LONGEST = {"tension_drone": 6.0, "wind_howl": 5.0, "ocean_waves": 5.0, "crowd_murmur": 5.0, "crowd_cheer": 4.0, "fire_crackle": 5.0,
           "war_drums": 5.0, "dark_choir": 5.0, "earthquake_rumble": 4.5, "ticking_clock": 4.0, "cinematic_riser": 4.0,
           "typewriter_keys": 3.0, "keyboard_typing": 3.0, "heartbeat_thump": 3.0, "gunfire_burst": 3.0, "thunder_crack": 4.0,
           "distant_explosion": 4.0, "cinematic_boom": 4.0, "deep_sub_drop": 3.0, "magic_shimmer": 3.5, "monster_roar": 3.5}
DEFAULT_LONGEST = 2.5
SHORTEST = 0.15
BETTER_WORDS = {"deep_sub_drop": "sub drop bass", "cinematic_boom": "cinematic boom impact", "bass_hit": "bass hit impact",
                "stamp_thud": "stamp thud", "suspense_sting": "suspense sting", "tension_drone": "tension drone dark",
                "glitch_burst": "glitch digital", "pop_click": "pop click", "error_buzzer": "error buzzer", "dark_choir": "dark choir",
                "notification_ding": "notification ding", "magic_shimmer": "magic shimmer", "paper_rip": "paper tear",
                "whoosh_fast": "whoosh fast", "whoosh_soft": "soft whoosh", "gunfire_burst": "machine gun burst",
                "monster_roar": "monster roar", "earthquake_rumble": "earthquake rumble", "wind_howl": "wind howling"}


def _search(words: str) -> list[dict]:
    last = None
    for attempt in range(4):
        try:
            resp = requests.get(SEARCH, params={"q": words, "license": "cc0", "page_size": 20, "mature": "false"}, timeout=90,
                                headers={"User-Agent": "ezzy-case-studies/1.0"})
            if resp.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json().get("results") or []
        except requests.RequestException as e:
            last = e
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"Openverse didn't answer ({type(last).__name__})")


def _download(url: str, dest: Path) -> None:
    if urlparse(url).scheme != "https":
        raise ValueError("not an https address")
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "ezzy-case-studies/1.0"}) as resp:
        resp.raise_for_status()
        got = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1 << 16):
                got += len(chunk)
                if got > MAX_DOWNLOAD:
                    raise ValueError("too big")
                f.write(chunk)


def _keep(source: Path, dest: Path, longest: float) -> float:
    """The sound as a clean mono MP3: silence off its start, at most `longest` seconds, ending softly so it doesn't click. A
    file ffmpeg can't read raises. Returns its length."""
    ff = short_render.ffmpeg_exe()
    subprocess.run([ff, "-y", "-v", "error", "-i", str(source), "-vn", "-map_metadata", "-1", "-ac", "1", "-ar", "44100",
                    "-af", f"silenceremove=start_periods=1:start_threshold=-50dB,atrim=0:{longest:.2f},"
                           f"afade=t=out:st={max(longest - 0.08, 0):.2f}:d=0.08,dynaudnorm=f=500:g=31:p=0.9",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(dest)], check=True, capture_output=True, timeout=60)
    probe = subprocess.run([ff, "-hide_banner", "-i", str(dest)], capture_output=True, text=True, timeout=30).stderr
    found = [p for p in probe.split("Duration: ")[1:2]]
    if not found:
        raise ValueError("no sound in it")
    h, m, s = found[0].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def fetch(tag: str, record: dict) -> dict | None:
    """The best CC0 sound for a tag, kept; what's recorded about it, or None."""
    words = BETTER_WORDS.get(tag, tag.replace("_", " "))
    longest = LONGEST.get(tag, DEFAULT_LONGEST)
    wanted = [w for w in tag.split("_") if len(w) > 2]
    results = _search(words)
    scored = []
    for item in results:
        seconds = float(item.get("duration") or 0) / 1000
        if not SHORTEST <= seconds <= 60 or str(item.get("license")).lower() != "cc0" or not item.get("url"):
            continue
        title = str(item.get("title") or "").lower()
        if title.startswith("ll-q"):  # (Lingua Libre: someone saying the word, not the sound)
            continue
        scored.append((-sum(w in title for w in wanted), seconds > longest * 3, seconds, item))
    scored.sort(key=lambda row: row[:3])
    work = Path(tempfile.mkdtemp(prefix="sfx_"))
    try:
        for *_, item in scored[:6]:
            raw = work / "download"
            try:
                _download(item["url"], raw)
                dest = SFX_DIR / f"{tag}.mp3"
                seconds = _keep(raw, dest, longest)
            except Exception as e:
                print(f"  {tag}: skipped one ({type(e).__name__})", file=sys.stderr)
                continue
            return {"kind": tag, "creator": str(item.get("creator") or "unknown")[:80], "licence": "cc0",
                    "source": str(item.get("source") or item.get("provider") or "")[:40],
                    "title": str(item.get("title") or "")[:100], "url": str(item.get("foreign_landing_url") or item["url"])[:200],
                    "seconds": round(seconds, 2)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("tags", nargs="*")
    args = parser.parse_args()
    record = yaml.safe_load(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
    wanted = args.tags or [t for t in a4.SFX_TAGS if not any(SFX_DIR.glob(f"{t}.*"))]
    missing = []
    for tag in wanted:
        if tag not in a4.SFX_TAGS:
            print(f"{tag} isn't one of the prompt's tags", file=sys.stderr)
            continue
        try:
            found = fetch(tag, record)
        except Exception as e:
            print(f"{tag}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            found = None
        if found:
            record[f"{tag}.mp3"] = found
            print(f"{tag}: {found['title'][:50]} by {found['creator'][:30]} ({found['seconds']} s)", flush=True)
            RECORD.write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
        else:
            missing.append(tag)
            print(f"{tag}: nothing found", flush=True)
        time.sleep(1)
    print(f"{len(wanted) - len(missing)} of {len(wanted)} found" + (f"; none for {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
