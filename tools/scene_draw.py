"""
The sketches' sets: a flat background and a foreground prop for each setting, drawn with the
puppet's Pen so the camera can zoom without blur.

Each setting has a back layer (walls, windows, shelves: drawn before the characters) and a front
layer (the desk, counter, table, sofa seat, rack, wall or hedge that hides everything below the
characters' waists). World coordinates: the wide shot shows x 0-1080, y 0-1920; the front layer's
top edge is at PROP_TOP and characters stand with their shoulder line at STAND_Y. A seed picks the
colours, so the same episode always looks the same and different episodes differ.

Usage:
    python tools/scene_draw.py --setting office --out .tmp/out/office.png
"""

import argparse
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from puppet import INK, WHITE, Pen, bez, ellipse, mix, rgb

WORLD_W, WORLD_H = 1080, 1920
PROP_TOP = 1170
STAND_Y = 800
SEATED = {"flat"}  # characters sit (on the sofa) instead of standing behind something

PALETTES = {
    "office": [("#dfe7ee", "#9fb8cc", "#8a6a4f"), ("#e9e2d6", "#a7c0c9", "#6f5a48"), ("#e4ecdf", "#b2c7d6", "#5f6b78")],
    "flat": [("#f1e3d3", "#c8644b", "#d9a441"), ("#dfe9e4", "#4f7f8c", "#e6a35f"), ("#ece0ef", "#7b5aa6", "#e7b44c")],
    "kitchen": [("#f4ecdf", "#7fb3a6", "#f7f7f2"), ("#eef0ea", "#e0a160", "#ffffff"), ("#f6e8e3", "#5e86b9", "#f4f1ea")],
    "cafe": [("#c96f4e", "#3e3a36", "#d8a464"), ("#b85f45", "#2f3b38", "#c9965a"), ("#d08159", "#353047", "#dcae6e")],
    "gym": [("#3c4655", "#aab8c8", "#e35d3b"), ("#41404a", "#b8c4cf", "#f1b53d"), ("#2f4a4f", "#a9c3c4", "#e2574c")],
    "street": [("#bfe0f2", "#e0b48c", "#c75a4b"), ("#f3d3b8", "#9fb3c9", "#3f7d6e"), ("#cde6f5", "#d9a6a0", "#4f6fa8")],
    "park": [("#bfe3f5", "#6fb35a", "#4c8f45"), ("#cfe8f7", "#86bf5d", "#3f8a4f"), ("#f6e1c4", "#a3c45a", "#5f9a43")],
}


def palette(setting: str, seed: int) -> tuple:
    options = PALETTES.get(setting, PALETTES["office"])
    return tuple(rgb(c) for c in options[seed % len(options)])


def _rect(pen: Pen, x0, y0, x1, y1, fill, outline=True, width=5.5):
    pen.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, outline, width)


def _plant(pen: Pen, x: float, y: float, s: float, pot) -> None:
    leaf = (76, 150, 86)
    for k, (dx, h, lean) in enumerate(((-30, 210, -60), (0, 260, 0), (32, 220, 55), (-12, 170, -25), (18, 180, 28))):
        tip = (x + lean * s, y - h * s)
        mid = (x + dx * s * 0.5, y - h * s * 0.55)
        pen.poly(bez((x + dx * s * 0.2, y), (mid[0] - 30 * s, mid[1]), (tip[0] - 10 * s, tip[1] + 30 * s), tip, 10)
                 + bez(tip, (tip[0] + 18 * s, tip[1] + 40 * s), (mid[0] + 30 * s, mid[1]), (x + dx * s * 0.2 + 8 * s, y), 10),
                 mix(leaf, (40, 90, 50), 0.15 * (k % 2)))
    pen.poly([(x - 58 * s, y - 10 * s), (x + 58 * s, y - 10 * s), (x + 44 * s, y + 90 * s), (x - 44 * s, y + 90 * s)], pot)


def _window(pen: Pen, x0, y0, x1, y1, sky, frame, inside) -> None:
    _rect(pen, x0 - 18, y0 - 18, x1 + 18, y1 + 18, frame)
    _rect(pen, x0, y0, x1, y1, sky)
    inside(pen)
    pen.stroke([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], INK, 6)
    mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
    pen.stroke([(mid_x, y0), (mid_x, y1)], frame, 14)
    pen.stroke([(x0, mid_y), (x1, mid_y)], frame, 14)
    pen.stroke([(x0, y1 + 18), (x1, y1 + 18)], INK, 5)


def _skyline(pen: Pen, x0, x1, base, color, rng: random.Random) -> None:
    x = x0
    while x < x1:
        w = rng.randint(60, 130)
        h = rng.randint(120, 360)
        _rect(pen, x, base - h, min(x + w, x1), base, color, False)
        for wy in range(int(base - h + 20), int(base - 20), 34):
            for wx in range(int(x + 12), int(min(x + w, x1) - 16), 26):
                _rect(pen, wx, wy, wx + 12, wy + 16, mix(color, WHITE, 0.35), False)
        x += w + rng.randint(4, 18)


# ------------------------------------------------------------------ settings

def office_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, glass, wood = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, wall, False)
    _rect(pen, -200, 1060, WORLD_W + 200, 1100, mix(wall, INK, 0.08), False)  # dado line behind the desks

    def city(p):
        _rect(p, 150, 200, 930, 760, mix(glass, WHITE, 0.45), False)
        _skyline(p, 150, 930, 760, mix(glass, INK, 0.12), rng)
    _window(pen, 150, 200, 930, 760, glass, mix(wall, INK, 0.25), city)
    pen.poly(ellipse(110, 130, 46, 46, 32), WHITE)  # clock
    pen.stroke([(110, 130), (110, 100)], INK, 5)
    pen.stroke([(110, 130), (132, 140)], INK, 5)
    for k, color in enumerate(((255, 214, 92), (255, 160, 170), (150, 210, 255))):  # sticky notes
        _rect(pen, 960 + (k % 2) * 46, 300 + k * 60, 1004 + (k % 2) * 46, 344 + k * 60, color, True, 3)
    _plant(pen, 70, 1080, 1.0, wood)


def office_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, glass, wood = pal
    top = mix(wood, WHITE, 0.25)
    _rect(pen, -200, PROP_TOP, WORLD_W + 200, PROP_TOP + 46, top)
    _rect(pen, -200, PROP_TOP + 46, WORLD_W + 200, WORLD_H + 200, wood)
    pen.stroke([(-200, PROP_TOP + 120), (WORLD_W + 200, PROP_TOP + 120)], mix(wood, INK, 0.25), 4)
    # a laptop (seen from behind) between the characters, a mug and some papers
    pen.poly([(450, PROP_TOP + 4), (630, PROP_TOP + 4), (612, PROP_TOP - 128), (468, PROP_TOP - 128)], (196, 199, 207))
    pen.dot(540, PROP_TOP - 66, 13, (232, 234, 238))
    handle = bez((112, PROP_TOP - 54), (146, PROP_TOP - 56), (146, PROP_TOP - 14), (112, PROP_TOP - 16), 8)
    pen.stroke(handle, INK, 18)
    pen.stroke(handle, (233, 110, 90), 7)
    pen.poly([(60, PROP_TOP - 70), (118, PROP_TOP - 70), (114, PROP_TOP + 6), (64, PROP_TOP + 6)], (233, 110, 90))
    for k in range(3):
        _rect(pen, 900 - k * 6, PROP_TOP - 14 - k * 9, 1040 - k * 6, PROP_TOP - 2 - k * 9, WHITE, True, 3)


def flat_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, sofa, art = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, wall, False)
    for x in range(-200, WORLD_W + 200, 90):  # wallpaper stripes
        _rect(pen, x, -200, x + 30, 1500, mix(wall, WHITE, 0.35), False)
    _rect(pen, 300, 190, 780, 560, (250, 247, 240))  # a framed print
    _rect(pen, 330, 220, 750, 530, mix(art, WHITE, 0.55), False)
    pen.poly(ellipse(470, 380, 90, 90, 32), art, False)
    pen.poly([(560, 520), (700, 300), (750, 520)], mix(sofa, WHITE, 0.2), False)
    pen.stroke([(-200, 1080), (WORLD_W + 200, 1080)], mix(wall, INK, 0.15), 5)
    pen.stroke([(70, 1080), (70, 340)], (70, 70, 76), 8)  # floor lamp
    pen.poly([(10, 340), (130, 340), (105, 250), (35, 250)], (250, 236, 200))
    # the sofa's back, behind the characters
    pen.poly(bez((20, 1240), (20, 930), (60, 900), (200, 900), 10) + [(880, 900)]
             + bez((880, 900), (1020, 900), (1060, 930), (1060, 1240), 10), sofa)
    for x in (360, 720):
        pen.stroke([(x, 930), (x, 1180)], mix(sofa, INK, 0.25), 4)


def flat_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, sofa, art = pal
    seat = mix(sofa, WHITE, 0.12)
    pen.poly(bez((-20, PROP_TOP + 30), (-10, PROP_TOP - 10), (40, PROP_TOP - 14), (120, PROP_TOP - 14), 8) + [(960, PROP_TOP - 14)]
             + bez((960, PROP_TOP - 14), (1040, PROP_TOP - 14), (1090, PROP_TOP - 10), (1100, PROP_TOP + 30), 8)
             + [(1100, PROP_TOP + 190), (-20, PROP_TOP + 190)], seat)
    for x in (360, 720):
        pen.stroke([(x, PROP_TOP - 8), (x, PROP_TOP + 180)], mix(sofa, INK, 0.25), 4)
    _rect(pen, -40, PROP_TOP + 190, WORLD_W + 40, PROP_TOP + 300, mix(sofa, INK, 0.2))
    _rect(pen, -200, PROP_TOP + 300, WORLD_W + 200, WORLD_H + 200, (176, 132, 96), False)  # floor
    pen.poly(ellipse(540, PROP_TOP + 470, 520, 90, 40), mix(art, WHITE, 0.3), False)  # rug
    for sx, x in ((-1, 30), (1, 1050)):  # armrests
        pen.poly(bez((x - 70, PROP_TOP + 300), (x - 80, PROP_TOP - 40), (x - 40, PROP_TOP - 90), (x, PROP_TOP - 90), 8)
                 + bez((x, PROP_TOP - 90), (x + 40, PROP_TOP - 90), (x + 80, PROP_TOP - 40), (x + 70, PROP_TOP + 300), 8), sofa)


def kitchen_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, cabinet, tile = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, wall, False)
    for row, y in enumerate(range(700, PROP_TOP + 40, 52)):  # subway tiles
        for x in range(-220 + (row % 2) * 55, WORLD_W + 200, 110):
            _rect(pen, x, y, x + 106, y + 48, tile, True, 2.5)

    def outside(p):
        _rect(p, 380, 200, 700, 600, (190, 226, 245), False)
        p.poly(ellipse(470, 520, 160, 70, 32), (150, 200, 120), False)
    _window(pen, 380, 200, 700, 600, (190, 226, 245), WHITE, outside)
    for sx in (-1, 1):  # curtains
        x = 380 if sx < 0 else 700
        pen.poly([(x - sx * 30, 170), (x + sx * 50, 170), (x + sx * 30, 640), (x - sx * 50, 640)], mix(cabinet, WHITE, 0.4))
    for x0, x1 in ((-60, 330), (750, 1140)):  # upper cabinets
        _rect(pen, x0, 110, x1, 560, cabinet)
        mid = (x0 + x1) / 2
        pen.stroke([(mid, 110), (mid, 560)], INK, 4)
        for hx in (mid - 30, mid + 30):
            pen.stroke([(hx, 470), (hx, 530)], (210, 210, 214), 8)


def kitchen_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, cabinet, tile = pal
    _rect(pen, -200, PROP_TOP, WORLD_W + 200, PROP_TOP + 44, (236, 234, 228))
    _rect(pen, -200, PROP_TOP + 44, WORLD_W + 200, WORLD_H + 200, cabinet)
    for x in range(-60, WORLD_W + 100, 270):
        _rect(pen, x + 14, PROP_TOP + 80, x + 256, PROP_TOP + 560, mix(cabinet, WHITE, 0.12), True, 4)
        pen.stroke([(x + 110, PROP_TOP + 120), (x + 160, PROP_TOP + 120)], (210, 210, 214), 8)
    # a kettle and a fruit bowl at the ends of the counter
    pen.poly(bez((40, PROP_TOP + 2), (30, PROP_TOP - 120), (150, PROP_TOP - 120), (140, PROP_TOP + 2), 12), (228, 90, 80))
    pen.stroke([(56, PROP_TOP - 96), (124, PROP_TOP - 96)], INK, 7)
    pen.poly(bez((880, PROP_TOP - 40), (900, PROP_TOP + 6), (1020, PROP_TOP + 6), (1040, PROP_TOP - 40), 10), (250, 240, 220))
    for k, (x, color) in enumerate(((915, (240, 170, 60)), (960, (220, 70, 60)), (1003, (120, 190, 80)))):
        pen.dot(x, PROP_TOP - 52 - (k % 2) * 10, 24, color)


def cafe_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    brick, board, lamp = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, brick, False)
    for row, y in enumerate(range(-20, 1300, 40)):  # bricks
        for x in range(-220 + (row % 2) * 45, WORLD_W + 200, 90):
            _rect(pen, x, y, x + 86, y + 36, mix(brick, (90, 40, 30) if (x + row) % 3 else WHITE, 0.08), False)
    _rect(pen, 300, 180, 780, 560, board)  # menu board
    for k, y in enumerate(range(240, 520, 46)):
        w = 260 - (k * 37) % 120
        pen.stroke([(350, y), (350 + w, y)], (235, 232, 222), 5)
        pen.stroke([(690, y), (730, y)], (235, 232, 222), 5)
    for x in (130, 950):  # pendant lamps
        pen.stroke([(x, -200), (x, 150)], INK, 4)
        pen.poly(ellipse(x, 220, 120, 60, 32), mix(lamp, WHITE, 0.6), False)
        pen.poly([(x - 70, 150), (x + 70, 150), (x + 40, 100), (x - 40, 100)], lamp)
    _rect(pen, -200, 760, 230, 790, (120, 84, 60))  # shelf with cups
    for k in range(3):
        pen.poly([(30 + k * 64, 760), (80 + k * 64, 760), (74 + k * 64, 712), (36 + k * 64, 712)], WHITE)


def cafe_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    brick, board, lamp = pal
    wood = (150, 102, 66)
    _rect(pen, -200, PROP_TOP, WORLD_W + 200, PROP_TOP + 40, mix(wood, WHITE, 0.15))
    _rect(pen, -200, PROP_TOP + 40, WORLD_W + 200, WORLD_H + 200, wood)
    for x in range(-200, WORLD_W + 200, 120):
        pen.stroke([(x, PROP_TOP + 40), (x, WORLD_H + 200)], mix(wood, INK, 0.2), 4)
    for x in (200, 860):  # coffee cups on saucers
        pen.poly(ellipse(x, PROP_TOP - 4, 70, 12, 28), WHITE)
        pen.poly([(x - 44, PROP_TOP - 90), (x + 44, PROP_TOP - 90), (x + 34, PROP_TOP - 8), (x - 34, PROP_TOP - 8)], WHITE)
        pen.poly(ellipse(x, PROP_TOP - 90, 44, 9, 24), (110, 70, 40))
        pen.poly(ellipse(x + 54, PROP_TOP - 52, 16, 20, 20), WHITE)
    pen.poly([(510, PROP_TOP), (570, PROP_TOP), (560, PROP_TOP - 70), (520, PROP_TOP - 70)], (190, 220, 235))  # a vase
    pen.poly(ellipse(540, PROP_TOP - 104, 26, 36, 20), lamp)


def gym_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, mirror, stripe = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, wall, False)
    _rect(pen, -200, 940, WORLD_W + 200, 990, stripe, False)
    _rect(pen, 60, 140, 1020, 900, mirror)  # the mirror wall
    for x0 in (180, 520, 820):
        pen.poly([(x0, 140), (x0 + 90, 140), (x0 - 60, 900), (x0 - 150, 900)], mix(mirror, WHITE, 0.35), False)
    pen.stroke([(60, 140), (1020, 140), (1020, 900), (60, 900), (60, 140)], INK, 6)
    pen.poly([(510, 40), (580, 40), (540, 100), (590, 100), (500, 190), (525, 120), (480, 120)], stripe)  # a bolt sign


def gym_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    wall, mirror, stripe = pal
    frame = (70, 74, 86)
    _rect(pen, -200, PROP_TOP + 40, WORLD_W + 200, WORLD_H + 200, (44, 46, 54))  # the rack's body
    _rect(pen, -200, PROP_TOP + 26, WORLD_W + 200, PROP_TOP + 52, frame)
    _rect(pen, -200, PROP_TOP + 150, WORLD_W + 200, PROP_TOP + 166, stripe, False)
    # dumbbells lying on the top shelf: a handle between two hexagonal weights, seen from the front
    for k, x in enumerate(range(-20, WORLD_W + 60, 150)):
        weight = (52, 54, 62) if k % 2 else mix(stripe, INK, 0.25)
        pen.stroke([(x - 40, PROP_TOP - 6), (x + 40, PROP_TOP - 6)], INK, 18)
        pen.stroke([(x - 40, PROP_TOP - 6), (x + 40, PROP_TOP - 6)], (190, 192, 198), 9)
        for sx in (-1, 1):
            cx = x + sx * 52
            pen.poly([(cx - 18, PROP_TOP - 44), (cx + 18, PROP_TOP - 44), (cx + 26, PROP_TOP - 6),
                      (cx + 18, PROP_TOP + 30), (cx - 18, PROP_TOP + 30), (cx - 26, PROP_TOP - 6)], weight)


def street_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    sky, facade, awning = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, sky, False)
    pen.poly(ellipse(200, 220, 110, 50, 32), WHITE, False)
    pen.poly(ellipse(290, 200, 90, 60, 32), WHITE, False)
    for x0, x1, top, color in ((-60, 420, 240, facade), (420, 760, 120, mix(facade, (120, 140, 170), 0.35)),
                               (760, 1140, 300, mix(facade, (190, 90, 80), 0.25))):
        _rect(pen, x0, top, x1, 1400, color)
        for wy in range(top + 50, 820, 120):
            for wx in range(x0 + 40, x1 - 60, 110):
                _rect(pen, wx, wy, wx + 60, wy + 80, (205, 228, 240), True, 4)
    _rect(pen, 470, 860, 720, 1400, (90, 70, 60))  # a shop door
    for k in range(6):  # striped awning
        x = 420 + k * 57
        pen.poly([(x, 780), (x + 57, 780), (x + 57, 850), (x, 850)], awning if k % 2 else WHITE)
    pen.stroke([(420, 780), (762, 780), (762, 850), (420, 850), (420, 780)], INK, 5)
    pen.stroke([(980, 1400), (980, 520)], (60, 66, 74), 12)  # street lamp
    pen.poly(ellipse(980, 500, 40, 26, 24), (255, 230, 150))


def street_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    sky, facade, awning = pal
    brick = (172, 92, 70)
    _rect(pen, -200, PROP_TOP, WORLD_W + 200, PROP_TOP + 50, (190, 186, 178))  # capstones
    _rect(pen, -200, PROP_TOP + 50, WORLD_W + 200, WORLD_H + 200, brick)
    for row, y in enumerate(range(PROP_TOP + 50, PROP_TOP + 700, 46)):
        for x in range(-220 + (row % 2) * 50, WORLD_W + 200, 100):
            _rect(pen, x, y, x + 96, y + 42, mix(brick, (110, 50, 40) if (x + row) % 3 else WHITE, 0.1), True, 2.5)


def park_back(pen: Pen, pal: tuple, rng: random.Random) -> None:
    sky, grass, tree = pal
    _rect(pen, -200, -200, WORLD_W + 200, WORLD_H + 200, sky, False)
    for x, y, r in ((180, 260, 70), (260, 240, 90), (350, 270, 60), (760, 180, 60), (830, 160, 80)):
        pen.poly(ellipse(x, y, r * 1.3, r * 0.8, 28), WHITE, False)
    pen.poly(bez((-200, 980), (200, 820), (600, 900), (1280, 860), 20) + [(1280, 1600), (-200, 1600)], mix(grass, WHITE, 0.25), False)
    pen.poly(bez((-200, 1080), (300, 960), (700, 1040), (1280, 980), 20) + [(1280, 1600), (-200, 1600)], grass, False)
    for x, s in ((100, 1.0), (980, 1.15), (640, 0.6)):  # trees
        pen.poly([(x - 18 * s, 1100), (x + 18 * s, 1100), (x + 14 * s, 700), (x - 14 * s, 700)], (120, 84, 56))
        for dx, dy, r in ((0, -40, 150), (-90, 30, 110), (90, 30, 110), (0, 60, 120)):
            pen.poly(ellipse(x + dx * s, 640 + dy * s, r * s, r * 0.85 * s, 32), tree)


def park_front(pen: Pen, pal: tuple, rng: random.Random) -> None:
    sky, grass, tree = pal
    hedge = mix(tree, (30, 80, 40), 0.25)
    bumps = [(x, PROP_TOP + 10 + (x * 37) % 23, 62) for x in range(-160, WORLD_W + 200, 86)]
    for x, y, r in bumps:
        pen.dot(x, y, r, hedge)
    _rect(pen, -200, PROP_TOP + 10, WORLD_W + 200, WORLD_H + 200, hedge, False)
    for x, y, r in bumps:
        pen.poly(ellipse(x, y, r - 6, r - 6, 20), hedge, False)
    rng2 = random.Random(7)
    for _ in range(60):  # leaf texture
        x, y = rng2.uniform(-100, WORLD_W + 100), rng2.uniform(PROP_TOP + 30, PROP_TOP + 600)
        pen.poly(ellipse(x, y, 14, 8, 12), mix(hedge, WHITE, 0.15), False)


SETS = {
    "office": (office_back, office_front), "flat": (flat_back, flat_front), "kitchen": (kitchen_back, kitchen_front),
    "cafe": (cafe_back, cafe_front), "gym": (gym_back, gym_front), "street": (street_back, street_front),
    "park": (park_back, park_front),
}


def draw_back(pen: Pen, setting: str, seed: int) -> None:
    SETS.get(setting, SETS["office"])[0](pen, palette(setting, seed), random.Random(seed))


def draw_front(pen: Pen, setting: str, seed: int) -> None:
    SETS.get(setting, SETS["office"])[1](pen, palette(setting, seed), random.Random(seed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--setting", choices=list(SETS), default="office")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    img = Image.new("RGB", (WORLD_W, WORLD_H), "white")
    pen = Pen(ImageDraw.Draw(img))
    draw_back(pen, args.setting, args.seed)
    draw_front(pen, args.setting, args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
