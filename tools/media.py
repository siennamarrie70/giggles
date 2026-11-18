"""
Media helpers the films share: a working ffmpeg, and the stories' music library.

  ffmpeg_exe()     the bundled ffmpeg (copied to /tmp on Vercel, where the bundle is read-only)
  music_tracks()   the stories' music: the full-length tracks in assets/music/full/ (the dashboard's Music page adds and
                   removes them); each story gets one, silent until the spark (tools/story_film.py music_for)
  music_credit()   the credit line a track's licence asks for, from assets/music/tracks.yaml

Kevin MacLeod's tracks are CC BY 4.0 and in YouTube's Content ID: every film that uses one must carry its credit line,
which the Publisher adds to the description at upload (agents/publisher.py). A track you add yourself has no credit
line on file: use only music you may post.

Usage:
    python tools/media.py            # the music library, with each track's credit
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from common import ASSETS_DIR

MUSIC_DIR = ASSETS_DIR / "music"
STORY_MUSIC = MUSIC_DIR / "full"  # (named in a story's plan as "full/<file>": render.music, the credits)
MUSIC_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}


def ffmpeg_exe() -> str:
    import imageio_ffmpeg  # (here, not at the top: the dashboard alone, on Vercel, doesn't install it)

    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        # On Vercel the bundled binary can lose its executable bit and the bundle is
        # read-only, so run a copy from /tmp instead.
        bundled = next((Path(imageio_ffmpeg.__file__).parent / "binaries").glob("ffmpeg-*"), None)
        if bundled is None:
            raise
        local = Path(tempfile.gettempdir()) / "ffmpeg"
        if not local.exists():
            shutil.copy(bundled, local)
            local.chmod(0o755)
        return str(local)


# --- music ----------------------------------------------------------------

def _music_notes() -> dict:
    notes_file = MUSIC_DIR / "tracks.yaml"
    if not notes_file.exists():
        return {}
    with open(notes_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def music_tracks() -> list[Path]:
    """The stories' tracks, by name."""
    if not STORY_MUSIC.exists():
        return []
    return sorted(p for p in STORY_MUSIC.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTS)


def track_name(path: Path) -> str:
    """A track as a story's plan names it ("full/Immersed.mp3")."""
    return path.relative_to(MUSIC_DIR).as_posix()


def music_credit(name: str | None) -> str | None:
    """The credit line a track's licence asks for (assets/music/tracks.yaml), or None if it needs none."""
    if not name:
        return None
    return (_music_notes().get(name) or {}).get("credit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.parse_args()
    tracks = music_tracks()
    for path in tracks:
        credit = music_credit(track_name(path))
        print(f"{track_name(path)}: {credit.splitlines()[0] if credit else 'no credit line on file'}")
    if not tracks:
        print("No tracks: the films have no music until one is added (the dashboard's Music page).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
