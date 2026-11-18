"""
Finds a free sound for each of the stories' sound tags (the beds under a scene and the single sounds on what's seen:
agents/story.py BEDS and SPOTS, tools/silhouette_render.py) and keeps it as assets/sfx/<tag>.mp3. They come from
Openverse's search of Creative Commons sounds, CC0 only: nothing to credit, safe in a public repository, and each is
recorded in assets/sfx/sfx.yaml. You can replace any of them: a file named after the tag in assets/sfx/ is the sound used.
(A monitor's beep and a knock on a door are made in code: tools/film_sound.py.)

Run by hand, when a new sound is added to the stories. It never replaces a sound that's already there unless you name
its tag.

Usage:
    python tools/sfx_fetch.py                     # the tags that have no sound yet
    python tools/sfx_fetch.py rain_bed ...        # these tags again
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

import media
from common import ASSETS_DIR

SEARCH = "https://api.openverse.org/v1/audio/"
SFX_DIR = ASSETS_DIR / "sfx"
RECORD = SFX_DIR / "sfx.yaml"
MAX_DOWNLOAD = 12 << 20
DEFAULT_LONGEST = 2.5
SHORTEST = 0.15
# The stories' sounds: beds that run under a whole scene, and single sounds placed on what's seen. tag: (search words,
# longest seconds kept). Beds keep their natural rise and fall (no levelling); the renderer sets every level.
BEDS = {
    "rain_bed": ("rain ambience", 30.0),
    "rain_window": ("rain on window glass", 30.0),
    "night_street": ("city street night ambience", 30.0),
    "room_quiet": ("quiet room tone night", 30.0),
    "dawn_birds": ("birds morning chorus", 30.0),
    "wind_soft": ("soft wind ambience", 30.0),
    "crickets": ("crickets night", 30.0),
    "crowd_murmur": ("cafe people talking softly", 30.0),
}
SPOTS = {
    "footstep": ("footstep concrete", 1.0),
    "footstep_wet": ("footstep puddle splash", 1.2),
    "running_steps": ("running footsteps", 6.0),
    "water_drop": ("water drop", 1.5),
    "gate_close": ("metal gate closing", 3.0),
    "door_close": ("door closing", 2.0),
    "phone_buzz": ("phone vibrating", 2.0),
    "clock_tick": ("clock ticking", 8.0),
    "alarm_clock": ("alarm clock ringing", 4.0),
    "heartbeat": ("heartbeat", 4.0),
    "thunder_far": ("distant thunder", 6.0),
    "keys_jingle": ("keys jingle", 2.0),
    "switch_click": ("light switch click", 0.8),
    "page_turn": ("page turning", 1.5),
    "page_flip": ("paper page flip", 0.6),
    "paper_rip": ("paper tear", 1.5),
    "keyboard_typing": ("keyboard typing", 3.0),
    "car_pass_wet": ("car passing wet road", 6.0),
    "train_pass": ("train passing", 10.0),
    "glass_set_down": ("glass set down on table", 1.5),
    "wind_howl": ("wind howling", 5.0),
}
FOLEY = {**BEDS, **SPOTS}


def _search(words: str) -> list[dict]:
    last = None
    for attempt in range(4):
        try:
            resp = requests.get(SEARCH, params={"q": words, "license": "cc0", "page_size": 20, "mature": "false"}, timeout=90,
                                headers={"User-Agent": "ezzy-stories/1.0"})
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
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "ezzy-stories/1.0"}) as resp:
        resp.raise_for_status()
        got = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1 << 16):
                got += len(chunk)
                if got > MAX_DOWNLOAD:
                    raise ValueError("too big")
                f.write(chunk)


def _keep(source: Path, dest: Path, longest: float, bed: bool = False) -> float:
    """The sound as a clean mono MP3: silence off its start, at most `longest` seconds, ending softly so it doesn't click. A
    file ffmpeg can't read raises. Returns its length. A bed (rain, a street) keeps its natural rise and fall and fades in and
    out over a second, so it can loop."""
    ff = media.ffmpeg_exe()
    if bed:
        chain = (f"atrim=0:{longest:.2f},afade=t=in:d=1,areverse,afade=t=in:d=1,areverse")
    else:
        chain = (f"silenceremove=start_periods=1:start_threshold=-50dB,atrim=0:{longest:.2f},"
                 f"afade=t=out:st={max(longest - 0.08, 0):.2f}:d=0.08,dynaudnorm=f=500:g=31:p=0.9")
    subprocess.run([ff, "-y", "-v", "error", "-i", str(source), "-vn", "-map_metadata", "-1", "-ac", "1", "-ar", "44100",
                    "-af", chain, "-c:a", "libmp3lame", "-b:a", "128k", str(dest)], check=True, capture_output=True, timeout=90)
    probe = subprocess.run([ff, "-hide_banner", "-i", str(dest)], capture_output=True, text=True, timeout=30).stderr
    found = [p for p in probe.split("Duration: ")[1:2]]
    if not found:
        raise ValueError("no sound in it")
    h, m, s = found[0].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def fetch(tag: str, record: dict) -> dict | None:
    """The best CC0 sound for a tag, kept; what's recorded about it, or None."""
    words, longest = FOLEY.get(tag) or (tag.replace("_", " "), DEFAULT_LONGEST)
    bed = tag in BEDS
    wanted = [w for w in words.split() if len(w) > 2]
    results = _search(words)
    scored = []
    for item in results:
        seconds = float(item.get("duration") or 0) / 1000
        if not SHORTEST <= seconds <= (600 if bed else 60) or str(item.get("license")).lower() != "cc0" or not item.get("url"):
            continue
        if bed and seconds < 12:  # (a bed has to run under a whole scene)
            continue
        title = str(item.get("title") or "").lower()
        if title.startswith("ll-q"):  # (Lingua Libre: someone saying the word, not the sound)
            continue
        too_long = seconds > longest * 3 and not bed
        scored.append((-sum(w in title for w in wanted), too_long, -seconds if bed else seconds, item))
    scored.sort(key=lambda row: row[:3])
    work = Path(tempfile.mkdtemp(prefix="sfx_"))
    try:
        for *_, item in scored[:6]:
            raw = work / "download"
            try:
                _download(item["url"], raw)
                dest = SFX_DIR / f"{tag}.mp3"
                seconds = _keep(raw, dest, longest, bed=bed)
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
    known = set(FOLEY)
    wanted = args.tags or [t for t in FOLEY if not any(SFX_DIR.glob(f"{t}.*"))]
    missing = []
    for tag in wanted:
        if tag not in known:
            print(f"{tag} isn't one of the known sound tags", file=sys.stderr)
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
