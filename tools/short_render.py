"""
Media helpers every video shares: the captions (Pillow draws them in the Sniglet font, white with
a black outline, inside the Shorts safe areas), the music library, and a working ffmpeg.

  caption_image()  a caption on a transparent 1080x1920 frame, at the top or bottom safe area
  pick_music()     a track from assets/music/ (its mood first, if asked), or None if there are none
  music_credit()   the credit line a track's licence asks for in the description
  ffmpeg_exe()     the bundled ffmpeg (copied to /tmp on Vercel, where the bundle is read-only)

Kevin MacLeod's tracks are CC BY 4.0 and in YouTube's Content ID: every Short that uses one must carry
its credit line, which the Publisher adds at upload (agents/publisher.py).

Usage:
    python tools/short_render.py --caption "When it's Monday again" --out .tmp/out/caption.png
    python tools/short_render.py --music [--mood funny]          # which track would be picked
"""

import argparse
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
import yaml
from PIL import Image, ImageDraw, ImageFont

from common import ASSETS_DIR, tmp_path

W, H = 1080, 1920
FONT_PATH = ASSETS_DIR / "fonts" / "Sniglet-ExtraBold.ttf"
MUSIC_DIR = ASSETS_DIR / "music"
MUSIC_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
# The Shorts player covers the top bar, the buttons on the right and the bottom quarter.
TEXT_MAX_WIDTH = {"top": 920, "bottom": 840}  # bottom stays clear of the like/comment buttons
FONT_SIZE = {"top": 80, "bottom": 72}
TOP_TEXT_Y = 250
BOTTOM_TEXT_BOTTOM = 1380
ASCII_SWAPS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                             "–": "-", "—": "-", "…": "..."})
EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")


def ffmpeg_exe() -> str:
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
    return sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in MUSIC_EXTS) if MUSIC_DIR.exists() else []


def music_moods() -> list[str]:
    """The moods the library's tracks are tagged with (assets/music/tracks.yaml)."""
    notes = _music_notes()
    return sorted({(notes.get(p.name) or {}).get("mood") for p in music_tracks()} - {None})


def pick_music(mood: str | None = None) -> Path | None:
    """A random track, from the given mood if the library has one."""
    tracks = music_tracks()
    notes = _music_notes()
    matching = [p for p in tracks if mood and (notes.get(p.name) or {}).get("mood") == mood]
    pool = matching or tracks
    return random.choice(pool) if pool else None


def music_credit(name: str | None) -> str | None:
    """The credit line a track's licence asks for (assets/music/tracks.yaml), or None if it needs none."""
    if not name:
        return None
    return (_music_notes().get(name) or {}).get("credit")


# --- captions -------------------------------------------------------------

def clean_text(text: str) -> str:
    return " ".join(EMOJI.sub("", text.translate(ASCII_SWAPS)).split())


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=font) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def _balanced_wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Same number of lines as a greedy wrap, but evened out (no lonely last word)."""
    best = _wrap(draw, text, font, max_width)
    for width in range(max_width - 20, max_width // 3, -20):
        trial = _wrap(draw, text, font, width)
        if len(trial) > len(best):
            break
        best = trial
    return best


def caption_png(text: str, position: str, dest: Path) -> Path:
    """Full-frame transparent PNG with the caption drawn at the top or bottom safe area."""
    caption_image(text, position).save(dest)
    return dest


def caption_image(text: str, position: str) -> Image.Image:
    """The caption on a transparent full frame, at the top or bottom safe area."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = clean_text(text)
    max_width, size = TEXT_MAX_WIDTH[position], FONT_SIZE[position]
    while True:
        font = ImageFont.truetype(str(FONT_PATH), size)
        lines = _balanced_wrap(draw, text, font, max_width)
        fits = len(lines) <= 3 and all(draw.textlength(l, font=font) <= max_width for l in lines)
        if fits or size <= 44:
            break
        size -= 6
    block = "\n".join(lines)
    stroke, spacing = max(5, size // 9), size // 5
    left, top, right, bottom = draw.multiline_textbbox((0, 0), block, font=font, stroke_width=stroke,
                                                       spacing=spacing, align="center")
    x = (W - (right - left)) / 2 - left
    y = TOP_TEXT_Y - top if position == "top" else BOTTOM_TEXT_BOTTOM - (bottom - top) - top
    draw.multiline_text((x, y), block, font=font, fill="white", stroke_width=stroke, stroke_fill="black",
                        spacing=spacing, align="center")
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--caption", help="Draw this caption")
    parser.add_argument("--position", choices=["top", "bottom"], default="bottom")
    parser.add_argument("--out", default=str(tmp_path("out", "caption.png")))
    parser.add_argument("--music", action="store_true", help="Show which track would be picked")
    parser.add_argument("--mood")
    args = parser.parse_args()
    if args.music:
        track = pick_music(args.mood)
        print(f"{track.name if track else 'No tracks in assets/music/'} (moods: {', '.join(music_moods()) or 'none'})")
        return 0
    if not args.caption:
        parser.error("give --caption or --music")
    print(f"Wrote {caption_png(args.caption, args.position, Path(args.out))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
