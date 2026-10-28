"""
The case's thumbnail, made by Agent 4 in the channel's one style, so every case looks like part of
the same series: a still from the case (a real photo, a frame of its footage, or its map or chart)
graded like the video, the Professor big in the lower-left corner with the soft shadow he has in the
videos, the case type in a coloured tab (no case number since 2026-10-27, as in the video), and 2-6 bold words (the Writer's
thumbnail text) with the key word in the case type's colour. Two sizes: the cover (1080x1920: the
Shorts grid, Instagram and the dashboard) and a wide one (1280x720, where a 16:9 picture is shown).

The words and the still are the interactive part: the Studio shows the thumbnail, and you can change
its words (*word* marks the coloured one; without a mark, the last word is) and pick another still
from the case's shots; it's made again at once.

Usage:
    python tools/thumbnail.py --image photo.jpg --text "One phone *sank* Nokia" --category business --out .tmp/out/t.jpg
"""

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import doc_render
import host
import infographics as ig
import short_render

COVER, WIDE = (1080, 1920), (1280, 720)
MARKED = re.compile(r"\*([^*]+)\*")
MAX_WORDS = 6
INK = (12, 14, 20)


def words(text: str) -> list[tuple[str, bool]]:
    """The thumbnail's words in capitals, each with whether it's the coloured one (the last word without a mark)."""
    out = []
    for n, part in enumerate(MARKED.split(" ".join(str(text or "").split()))):
        out += [(w.upper(), n % 2 == 1) for w in part.split()]
    out = out[:MAX_WORDS]
    if out and not any(marked for _, marked in out):
        out[-1] = (out[-1][0], True)
    return out


def still(spec: dict, accent: tuple) -> Image.Image:
    """The background: a photo or a drawing (the drawn look), a frame of a clip a second in, or the map, chart or quote
    as the video draws it."""
    kind = spec.get("kind")
    if kind in ("photo", "scene"):
        return Image.open(spec["path"]).convert("RGB")
    if kind == "footage":
        at = min(1.0, max(0.0, float(spec.get("duration") or 2) - 0.5))
        raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(spec["path"]),
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, check=True, timeout=60).stdout
        return Image.open(io.BytesIO(raw)).convert("RGB")
    shot = doc_render.MapShot(spec, 3.0, accent) if kind == "map" else doc_render.CardShot(spec, 3.0, accent)
    return Image.fromarray(np.ascontiguousarray(shot.frame(2.5)))


def _fill(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cropped to fill `size`, a little above the middle (faces are usually in the upper part of a picture)."""
    w, h = size
    scale = max(w / img.width, h / img.height) * 1.04
    big = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x, y = (big.width - w) // 2, int((big.height - h) * 0.35)
    return big.crop((x, y, x + w, y + h))


def _shade(size: tuple[int, int], top: float, bottom: float, start: float) -> Image.Image:
    """Black, darkest at the edges: `top` opacity at the top fading to none by 30% down, and none at `start` growing
    to `bottom` at the foot."""
    w, h = size
    y = np.linspace(0, 1, h, dtype=np.float32)
    a = np.maximum(top * np.clip(1 - y / 0.3, 0, 1), bottom * np.clip((y - start) / (1 - start), 0, 1) ** 1.3)
    alpha = Image.fromarray((np.repeat(a[:, None], w, axis=1) * 255).astype(np.uint8), "L")
    layer = Image.new("RGBA", size, INK + (0,))
    layer.putalpha(alpha)
    return layer


def _professor(height: int) -> Image.Image:
    """His drawing at `height` px, with the soft shadow behind him."""
    base = Image.open(host.HOST_DIR / "base.png").convert("RGBA")
    him = base.resize((round(base.width * height / base.height), height), Image.LANCZOS)
    pad = height // 6
    out = Image.new("RGBA", (him.width + 2 * pad, him.height + pad), (0, 0, 0, 0))
    glow = Image.new("RGBA", out.size, INK + (0,))
    alpha = Image.new("L", out.size, 0)
    alpha.paste(him.getchannel("A").point(lambda a: int(a * host.GLOW * 1.3)), (pad, pad))
    glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(height // 18)))
    out.alpha_composite(glow)
    out.alpha_composite(him, (pad, pad))
    return out


def _tab(draw: ImageDraw.ImageDraw, xy: tuple[int, int], kicker: str, case_no, accent: tuple, size: int) -> int:
    """The case type in a coloured tab, its case number after it; returns the tab's height."""
    x, y = xy
    fnt = ig.font(ig.BODY_FONT, size)
    pad_x, pad_y = int(size * 0.55), int(size * 0.32)
    text_w = draw.textlength(kicker, font=fnt)
    height = int(size * 1.2) + 2 * pad_y
    draw.rounded_rectangle((x, y, x + text_w + 2 * pad_x, y + height), radius=height // 4, fill=accent)
    draw.text((x + pad_x, y + height / 2), kicker, font=fnt, fill=INK, anchor="lm")
    if case_no:
        draw.text((x + text_w + 2 * pad_x + int(size * 0.5), y + height / 2), f"CASE FILE {case_no}", font=fnt,
                  fill=(236, 232, 222), anchor="lm", stroke_width=max(2, size // 14), stroke_fill=INK)
    return height


def _words(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], accent: tuple, sizes: tuple[int, int],
           align: str = "center") -> None:
    """The words, as big as fit `box` (x, y, width, height) in up to 3 lines, the marked one in the accent colour."""
    marked = words(text)
    if not marked:
        return
    x, y, w, h = box
    plain = " ".join(word for word, _ in marked)
    fnt, lines = ig.fit(draw, plain, ig.HEAD_FONT, w, 3, sizes[0], sizes[1])
    step = fnt.size * 1.08
    while len(lines) * step > h and fnt.size > sizes[1]:
        fnt = ig.font(ig.HEAD_FONT, fnt.size - 6)
        lines = ig.wrap(draw, plain, fnt, w)
        step = fnt.size * 1.08
    top = y + (h - len(lines) * step) / 2
    n = 0
    space = draw.textlength(" ", font=fnt)
    stroke = max(3, fnt.size // 14)
    for k, line in enumerate(lines):
        width = draw.textlength(line, font=fnt)
        cx = x + (w - width) / 2 if align == "center" else x
        for word in line.split():
            colour = accent if marked[n][1] else (250, 248, 242)
            draw.text((cx + 5, top + k * step + 7), word, font=fnt, fill=INK)  # a hard shadow
            draw.text((cx, top + k * step), word, font=fnt, fill=colour, stroke_width=stroke, stroke_fill=INK)
            cx += draw.textlength(word, font=fnt) + space
            n += 1


def make(background: Image.Image, text: str, category: str, case_no=None, look: "doc_render.Look | None" = None
         ) -> tuple[Image.Image, Image.Image]:
    """The cover (1080x1920) and the wide thumbnail (1280x720) for a case."""
    import cv2

    accent = ig.accent(category)
    look = look or doc_render.Look(category)
    kicker = doc_render.KICKERS.get(category, category.replace("_", " ").title()).upper()
    out = []
    for size in (COVER, WIDE):
        w, h = size
        img = Image.fromarray(cv2.LUT(np.asarray(_fill(background, size)), look.lut)).convert("RGBA")
        wide = size == WIDE
        img.alpha_composite(_shade(size, 0.55, 0.88 if not wide else 0.7, 0.45 if not wide else 0.35))
        if wide:  # the words sit on the right: darken it a little more
            right = Image.linear_gradient("L").rotate(90).resize(size)  # 0 on the left to 255 on the right
            layer = Image.new("RGBA", size, INK + (0,))
            layer.putalpha(right.point(lambda a: int(a * 0.55)))
            img.alpha_composite(layer)
        him = _professor(round(h * (0.47 if not wide else 0.92)))
        img.alpha_composite(him, (-him.width // 9, h - him.height + him.height // 14))
        draw = ImageDraw.Draw(img)
        if wide:
            tab = _tab(draw, (int(w * 0.43), 46), kicker, case_no, accent, 30)
            _words(draw, text, (int(w * 0.43), 46 + tab + 20, int(w * 0.54), h - tab - 110), accent, (118, 54), "left")
        else:
            tab = _tab(draw, (64, 250), kicker, case_no, accent, 40)
            _words(draw, text, (60, 250 + tab + 40, w - 120, 620), accent, (172, 84))
        out.append(img.convert("RGB"))
    return out[0], out[1]


def save(images: tuple[Image.Image, Image.Image], cover: Path, wide: Path) -> None:
    cover.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(cover, quality=90)
    images[1].save(wide, quality=90)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--image", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--category", default="business")
    parser.add_argument("--case-no", type=int)
    parser.add_argument("--out", required=True, help="the cover's path; the wide one gets _wide added")
    args = parser.parse_args()
    try:
        out = Path(args.out)
        images = make(Image.open(args.image).convert("RGB"), args.text, args.category, args.case_no)
        save(images, out, out.with_name(out.stem + "_wide" + out.suffix))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
