"""
The studio the two hosts present from, drawn with the puppet's Pen so the camera can zoom without
blur: a wall in the case type's colour with a big screen (the visuals play on it), and the desk
the hosts stand behind.

World coordinates are the frame's in the studio shot (1080x1920). The screen's picture area is
SCREEN; the hosts stand at HOST_X with their shoulder line at SHOULDER_Y, drawn at HOST_SIZE; the
desk's top edge is DESK_TOP, where the rig's "desk" pose rests the hands (the rig draws nothing
below the waist, which the desk hides).

Usage:
    python tools/scene_draw.py --category business --out .tmp/out/studio.png
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import infographics
from puppet import INK, WHITE, Pen, mix

WORLD_W, WORLD_H = 1080, 1920
SCREEN = (60, 350, 1020, 860)
SHOULDER_Y = 1235
HOST_X = (290, 790)
HOST_SIZE = 0.95
DESK_TOP = round(SHOULDER_Y + 370 * HOST_SIZE)
BEZEL = 16


def _rect(pen: Pen, x0, y0, x1, y1, fill, outline=True, width=5.5):
    pen.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, outline, width)


def _plant(pen: Pen, x: float, y: float, s: float, pot) -> None:
    leaf = (76, 150, 86)
    for k, (dx, h, lean) in enumerate(((-30, 210, -60), (0, 260, 0), (32, 220, 55), (-12, 170, -25), (18, 180, 28))):
        tip = (x + lean * s, y - h * s)
        pen.poly([(x + dx * s * 0.2 - 9 * s, y), (x + dx * s * 0.5 - 26 * s, y - h * s * 0.55), tip,
                  (x + dx * s * 0.5 + 26 * s, y - h * s * 0.55), (x + dx * s * 0.2 + 9 * s, y)],
                 mix(leaf, (40, 90, 50), 0.15 * (k % 2)))
    pen.poly([(x - 58 * s, y - 10 * s), (x + 58 * s, y - 10 * s), (x + 44 * s, y + 90 * s), (x - 44 * s, y + 90 * s)], pot)


def colors(category: str) -> dict:
    accent = infographics.accent(category)
    return {"accent": accent, "wall": mix(accent, WHITE, 0.84), "slat": mix(accent, WHITE, 0.74),
            "stripe": mix(accent, WHITE, 0.35), "desk": mix(accent, INK, 0.55), "top": (236, 236, 232),
            "spot": mix(accent, WHITE, 0.6)}


def draw_back(pen: Pen, category: str, screen: bool = True) -> None:
    """The wall, its lights and the screen's frame (the picture is pasted in by the renderer); without the
    screen and the plant when the visual is shown full width above the desk instead."""
    c = colors(category)
    _rect(pen, -400, -400, WORLD_W + 400, WORLD_H + 400, c["wall"], False)
    for x in range(-380, WORLD_W + 400, 120):  # wall slats
        _rect(pen, x, -400, x + 54, WORLD_H + 400, c["slat"], False)
    _rect(pen, -400, 1060, WORLD_W + 400, 1104, c["stripe"], False)  # the accent band behind the hosts
    if not screen:
        return
    x0, y0, x1, y1 = SCREEN
    _rect(pen, x0 - BEZEL, y0 - BEZEL, x1 + BEZEL, y1 + BEZEL, (36, 38, 46))
    _rect(pen, x0, y0, x1, y1, infographics.BG, False)
    _plant(pen, 20, DESK_TOP - 60, 1.15, c["desk"])


def draw_front(pen: Pen, category: str) -> None:
    """The desk: a light top and a front in the case type's colour."""
    c = colors(category)
    _rect(pen, -400, DESK_TOP, WORLD_W + 400, DESK_TOP + 44, c["top"])
    _rect(pen, -400, DESK_TOP + 44, WORLD_W + 400, WORLD_H + 400, c["desk"])
    _rect(pen, -400, DESK_TOP + 100, WORLD_W + 400, DESK_TOP + 112, c["accent"], False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--category", choices=list(infographics.ACCENTS), default="business")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    img = Image.new("RGB", (WORLD_W, WORLD_H), "white")
    pen = Pen(ImageDraw.Draw(img))
    draw_back(pen, args.category)
    draw_front(pen, args.category)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
