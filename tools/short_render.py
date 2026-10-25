"""
Renders a vertical 1080x1920 Short from an edit spec using ffmpeg and Pillow.

Portrait clips are cropped to fill the frame; landscape or square clips sit over a
blurred, zoomed copy of themselves. Pillow draws each caption as a transparent PNG
(white text, black outline) that ffmpeg overlays at its time. The audio is a random
track from assets/music/ (silence if the folder is empty), loudness-normalised; music_credit()
gives the credit line its licence asks for in the description.

CPU is the scarce thing on Vercel's free plan (4 CPU-hours a month, and the autopilot
renders up to 10 Shorts a day), so the encoder runs at "superfast" and the background is
blurred at quarter size. On one core (2026-10-24): a 14 s portrait Short took 10 s of CPU,
a 21 s Top 3 took 19 s; "veryfast" cost a third more and the full-size blur twice as much.

Edit spec (what concept_write.build_edit() produces):
  {"segments": [{"url" or "path": ..., "start": 0.3, "duration": 9, "width": 1080, "height": 1920}],
   "overlays": [{"text": "When it's Monday again", "start": 0, "end": 9, "position": "top"}]}

Usage:
    python tools/short_render.py --edit .tmp/plan.json --out .tmp/out/short.mp4 [--music track.mp3]
"""

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
import requests
import yaml
from PIL import Image, ImageDraw, ImageFont

from common import ASSETS_DIR, TMP_DIR, load_config, tmp_path

W, H, FPS = 1080, 1920, 30
FONT_PATH = ASSETS_DIR / "fonts" / "Sniglet-ExtraBold.ttf"
MUSIC_DIR = ASSETS_DIR / "music"
MUSIC_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
# The Shorts player covers the top bar, the buttons on the right and the bottom quarter.
TEXT_MAX_WIDTH = {"top": 920, "bottom": 840}  # bottom stays clear of the like/comment buttons
FONT_SIZE = {"top": 80, "bottom": 72}
TOP_TEXT_Y = 250
BOTTOM_TEXT_BOTTOM = 1380
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
RENDER_TIMEOUT_S = 240
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


def pick_music() -> Path | None:
    tracks = [p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in MUSIC_EXTS] if MUSIC_DIR.exists() else []
    return random.choice(tracks) if tracks else None


def music_credit(name: str | None) -> str | None:
    """The credit line a track's licence asks for (assets/music/tracks.yaml), or None if it needs none.
    Kevin MacLeod's tracks are CC BY 4.0 and in YouTube's Content ID, so their line must be in the
    description of every Short that uses them."""
    notes_file = MUSIC_DIR / "tracks.yaml"
    if not name or not notes_file.exists():
        return None
    with open(notes_file, encoding="utf-8") as f:
        notes = yaml.safe_load(f) or {}
    return (notes.get(name) or {}).get("credit")


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    partial = dest.with_suffix(".part")
    size = 0
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(partial, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError(f"clip larger than {MAX_DOWNLOAD_BYTES >> 20} MB: {url}")
                f.write(chunk)
    partial.replace(dest)
    return dest


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
    img.save(dest)
    return dest


def _video_chain(i: int, seg: dict) -> str:
    finish = f"setsar=1,fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
    if seg["width"] / seg["height"] <= 0.65:  # portrait: crop to fill
        return f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{finish}"
    return (f"[{i}:v]split[bg{i}][fg{i}];"  # blurring a quarter-size copy looks the same and costs far less
            f"[bg{i}]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
            f"gblur=sigma=10,scale={W}:{H}[bgb{i}];"
            f"[fg{i}]scale={W}:-2[fgs{i}];"
            f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,{finish}")


def build_command(ffmpeg: str, segments: list[dict], overlays: list[dict], pngs: list[Path],
                  music: Path | None, volume: float, out: Path) -> list[str]:
    total = sum(s["duration"] for s in segments)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for s in segments:
        cmd += ["-ss", f"{s['start']:.2f}", "-t", f"{s['duration']:.2f}", "-i", str(s["path"])]
    for png in pngs:
        cmd += ["-i", str(png)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    audio_input = len(segments) + len(pngs)

    chains = [_video_chain(i, s) for i, s in enumerate(segments)]
    chains.append("".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[base]")
    last = "base"
    for k, ov in enumerate(overlays):
        chains.append(f"[{last}][{len(segments) + k}:v]overlay=0:0:"
                      f"enable='between(t,{ov['start']:.2f},{ov['end']:.2f})'[o{k}]")
        last = f"o{k}"
    chains.append(f"[{audio_input}:a]atrim=0:{total:.2f},asetpts=PTS-STARTPTS,volume={volume},"
                  f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(total - 1, 0):.2f}:d=1,"
                  f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    return cmd + ["-filter_complex", ";".join(chains), "-map", f"[{last}]", "-map", "[aout]",
                  "-c:v", "libx264", "-preset", "superfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
                  "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
                  "-t", f"{total:.2f}", str(out)]


def run(edit: dict, out_path: Path | str, music: Path | str | None = "auto", volume: float = 0.8) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="render_", dir=TMP_DIR / "work"))
    try:
        segments = []
        for i, seg in enumerate(edit["segments"]):
            path = seg.get("path")
            if not path or not Path(path).exists():
                name = (seg.get("key") or f"clip{i}").replace(":", "_") + ".mp4"
                path = download(seg["url"], tmp_path("clips", name))
            segments.append({**seg, "path": str(path)})
        overlays = [ov for ov in edit.get("overlays", []) if clean_text(ov["text"])]
        pngs = [caption_png(ov["text"], ov["position"], work / f"caption_{k}.png") for k, ov in enumerate(overlays)]
        track = pick_music() if music == "auto" else (Path(music) if music else None)

        cmd = build_command(ffmpeg_exe(), segments, overlays, pngs, track, volume, out)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=RENDER_TIMEOUT_S)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-1500:]}")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--edit", required=True, help="JSON edit spec, or plan.json containing an 'edit' key")
    parser.add_argument("--out", default=str(tmp_path("out", "short.mp4")))
    parser.add_argument("--music", default="auto", help="Track path, 'auto' (random from assets/music) or 'none'")
    args = parser.parse_args()

    try:
        with open(args.edit, encoding="utf-8") as f:
            spec = json.load(f)
        music = None if args.music == "none" else args.music
        out = run(spec.get("edit", spec), args.out, music, load_config()["music"]["volume"])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
