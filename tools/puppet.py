"""
The puppet rig: draws a cartoon character from its spec (character_spec.py) in a pose, with an
emotion, a mouth shape, a blink and a gaze. Flat colours, thick ink outlines, adult proportions.
Everything is a polygon pushed through one transform (the Pen), so the camera can zoom and the
head can tilt without any blur.

A character is drawn in its own units (one unit = one pixel at size 1.0 in the wide shot), with
(0, 0) in the middle of the shoulder line and y pointing down. The foreground prop (desk, counter,
sofa...) covers everything below y = +370, so nothing is drawn below the waist.

Mouth shapes are Rhubarb's (Preston Blair): A closed (M B P), B slightly open (most consonants),
C open (EH), D wide open (AA), E rounded (AO), F puckered (OO W), G teeth on lip (F V), H tongue
up (L), X at rest (its look follows the emotion).

Usage:
    python tools/puppet.py --spec cast.json --out .tmp/out/cast.png    # character cards, side by side
"""

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import character_spec as cs

INK = (29, 26, 32)
WHITE = (252, 251, 247)
MOUTH = (92, 32, 44)
TONGUE = (226, 112, 122)
GOLD = (222, 176, 64)
LINE = 5.5  # ink width in units

EMOTIONS = ("neutral", "happy", "annoyed", "surprised", "sad", "smug")
MOUTHS = ("A", "B", "C", "D", "E", "F", "G", "H", "X")
POSES = ("down", "desk", "gesture", "point", "shrug", "facepalm", "wave", "cross", "think", "cheer", "phone", "mug")
FACES = {"oval": (166, 204, 2.15, 0.22), "round": (182, 188, 2.05, 0.10), "square": (178, 196, 2.7, 0.10),
         "long": (156, 218, 2.25, 0.18)}
BODIES = {"slim": (112, 100, 44, 0.9), "average": (128, 118, 50, 1.0), "broad": (150, 134, 58, 1.12),
          "round": (134, 158, 54, 1.05)}  # shoulder and waist half-widths, neck width, arm thickness
LONG_SLEEVES = {"shirt", "shirt and tie", "hoodie", "blazer", "sweater", "cardigan", "jacket"}
NO_SLEEVES = {"tank top", "dress"}
HEIGHT_SHIFT = {"short": 30, "medium": 0, "tall": -40}  # how much higher the shoulders sit


def rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# ------------------------------------------------------------------ geometry

def ellipse(cx: float, cy: float, rx: float, ry: float, n: int = 40) -> list:
    return [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]


def bez(p0, p1, p2, p3, n: int = 12) -> list:
    """A cubic Bezier curve as n + 1 points."""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def clip_half(points: list, a: float, b: float, c: float) -> list:
    """The part of a polygon where a*x + b*y <= c (one Sutherland-Hodgman step)."""
    out = []
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        dp, dq = a * p[0] + b * p[1] - c, a * q[0] + b * q[1] - c
        if dp <= 0:
            out.append(p)
        if (dp <= 0) != (dq <= 0):
            t = dp / (dp - dq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def clip_convex(points: list, window: list) -> list:
    """The part of a polygon inside a convex window (both lists of points, window clockwise on screen)."""
    out = points
    for i, p in enumerate(window):
        q = window[(i + 1) % len(window)]
        a, b = -(q[1] - p[1]), q[0] - p[0]  # keep the side the window turns towards
        out = clip_half(out, -a, -b, -(a * p[0] + b * p[1]))
        if not out:
            break
    return out


def scale_about(points: list, cx: float, cy: float, s: float) -> list:
    return [(cx + (x - cx) * s, cy + (y - cy) * s) for x, y in points]


def lerp(p, q, t: float) -> tuple:
    return p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t


class Pen:
    """Draws on a Pillow image through an affine transform (x, y) -> (a x + b y + c, d x + e y + f)."""

    def __init__(self, draw: ImageDraw.ImageDraw, m=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)):
        self.draw, self.m = draw, m

    @property
    def unit(self) -> float:
        a, b, _, d, e, _ = self.m
        return math.sqrt(abs(a * e - b * d))

    def child(self, tx: float = 0.0, ty: float = 0.0, s: float = 1.0, angle: float = 0.0,
              pivot=(0.0, 0.0)) -> "Pen":
        """A pen for a part: rotated by `angle` degrees about `pivot`, then scaled by s and moved by (tx, ty)."""
        r = math.radians(angle)
        cos, sin = math.cos(r) * s, math.sin(r) * s
        px, py = pivot
        local = (cos, -sin, tx + px - (cos * px - sin * py), sin, cos, ty + py - (sin * px + cos * py))
        a, b, c, d, e, f = self.m
        la, lb, lc, ld, le, lf = local
        return Pen(self.draw, (a * la + b * ld, a * lb + b * le, a * lc + b * lf + c,
                               d * la + e * ld, d * lb + e * le, d * lc + e * lf + f))

    def tf(self, points: list) -> list:
        a, b, c, d, e, f = self.m
        return [(a * x + b * y + c, d * x + e * y + f) for x, y in points]

    def poly(self, points: list, fill, outline=True, width: float = LINE) -> None:
        if len(points) < 3:
            return
        pts = self.tf(points)
        self.draw.polygon(pts, fill=fill)
        if outline:
            w = max(1, round(width * self.unit))
            self.draw.line(pts + pts[:2], fill=INK if outline is True else outline, width=w, joint="curve")

    def stroke(self, points: list, color=INK, width: float = LINE) -> None:
        """A thick line with round joints and round ends."""
        if len(points) < 2:
            return
        pts = self.tf(points)
        w = max(1, round(width * self.unit))
        self.draw.line(pts, fill=color, width=w, joint="curve")
        r = w / 2
        for x, y in (pts[0], pts[-1]):
            self.draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def dot(self, x: float, y: float, r: float, fill, outline=True) -> None:
        self.poly(ellipse(x, y, r, r, 20), fill, outline)


# ------------------------------------------------------------------ the character's measurements

class Geo:
    """Where everything sits for one spec."""

    def __init__(self, spec: dict):
        self.W, self.H, self.n, self.taper = FACES[spec["face"]]
        self.S, self.waist, self.neck, self.arm = BODIES[spec["body"]]
        self.hy = -30 - self.H / 2  # head centre: the chin sits 30 units above the shoulder line
        self.eye_y = self.hy - self.H * 0.02
        self.eye_dx = self.W * 0.19
        self.erx, self.ery = self.W * 0.086, self.H * 0.085
        if spec["eyes"] == "narrow":
            self.ery *= 0.64
        self.nose_y = self.hy + self.H * 0.13
        self.mouth_y = self.hy + self.H * 0.31
        self.mouth_w = self.W * 0.31
        self.pivot = (0.0, self.hy + self.H * 0.45)  # the head tilts about the top of the neck

    def head_outline(self, s: float = 1.0, n: int = 72) -> list:
        rx, ry = self.W / 2 * s, self.H / 2 * s
        pts = []
        for i in range(n):
            t = 2 * math.pi * i / n
            c, sn = math.cos(t), math.sin(t)
            ex = 2 / self.n
            x = math.copysign(abs(c) ** ex, c)
            y = math.copysign(abs(sn) ** ex, sn)
            jaw = 1 - self.taper * max(sn, 0) ** 1.6
            pts.append((rx * jaw * x, self.hy + ry * y))
        return pts


def shirt_colors(spec: dict) -> tuple[tuple, tuple, tuple]:
    return rgb(cs.COLORS[spec["outfit_color"]]), rgb(cs.COLORS[spec["accent_color"]]), rgb(cs.SKIN_TONES[spec["skin"]])


def hair_rgb(spec: dict) -> tuple:
    return rgb(cs.HAIR_COLORS[spec["hair_color"]])


def brow_rgb(spec: dict) -> tuple:
    hair = hair_rgb(spec)
    if spec["hair"] == "bald" or sum(hair) > 480:  # light hair still needs readable brows
        return mix(hair if spec["hair"] != "bald" else (90, 70, 60), INK, 0.45)
    return mix(hair, INK, 0.25)


# ------------------------------------------------------------------ arms

def _arm_layout(pose: str, side: int, toward: int, geo: Geo, raise_: float) -> dict | None:
    """Shoulder, elbow, hand and hand shape for the arm on screen side `side` (-1 left, +1 right).
    `toward` is the side the other characters are on (pointing, gesturing and waving go that way)."""
    S, W, H, hy = geo.S, geo.W, geo.H, geo.hy
    sx = side
    shoulder = (sx * (S - 16), 34 - raise_)
    main = toward if toward else 1  # the arm that acts
    down = {"elbow": (sx * (S + 12), 175), "hand": (sx * (S + 2), 300), "kind": "fist"}
    desk = {"elbow": (sx * (S + 18), 190), "hand": (sx * S * 0.62, 352), "kind": "fist"}
    if pose == "down":
        lay = down
    elif pose == "desk":
        lay = desk
    elif pose == "gesture":
        lay = {"elbow": (sx * (S + 34), 190), "hand": (sx * (S + 78), 126), "kind": "open"} if sx == main else down
    elif pose == "point":
        lay = ({"elbow": (sx * (S + 70), 92), "hand": (sx * (S + 148), 62), "kind": "point"} if sx == main
               else down)
    elif pose == "shrug":
        lay = {"elbow": (sx * (S + 46), 165), "hand": (sx * (S + 96), 90), "kind": "open"}
    elif pose == "facepalm":
        lay = ({"elbow": (sx * S * 0.55, 150), "hand": (sx * W * 0.17, geo.eye_y - 2), "kind": "palm", "face": True}
               if sx == 1 else down)
    elif pose == "wave":
        lay = {"elbow": (sx * (S + 58), 36), "hand": (sx * (S + 44), -150), "kind": "open"} if sx == main else down
    elif pose == "cross":
        lay = ({"elbow": (S + 10, 175), "hand": (-S * 0.40, 162), "kind": "fist"} if sx == 1
               else {"elbow": (-(S + 10), 190), "hand": (S * 0.40, 180), "kind": "fist"})
    elif pose == "think":
        lay = ({"elbow": (S * 0.62, 205), "hand": (W * 0.07, hy + H * 0.47), "kind": "fist", "face": True}
               if sx == 1 else {"elbow": (-(S + 6), 190), "hand": (S * 0.30, 212), "kind": "fist"})
    elif pose == "cheer":
        lay = {"elbow": (sx * (S + 40), -30), "hand": (sx * (S + 26), -176), "kind": "fist"}
    elif pose == "phone":
        lay = ({"elbow": (S + 6, 185), "hand": (S * 0.30, 118), "kind": "phone"} if sx == 1 else down)
    elif pose == "mug":
        lay = ({"elbow": (S + 10, 190), "hand": (S * 0.48, 150), "kind": "mug"} if sx == 1 else down)
    else:
        lay = down
    return {"shoulder": shoulder, **lay}


def _limb(pen: Pen, pts: list, width: float, color) -> None:
    pen.stroke(pts, INK, width + 2 * LINE)
    pen.stroke(pts, color, width)


def _hand(pen: Pen, x: float, y: float, kind: str, side: int, skin, spec: dict) -> None:
    r = 21
    if kind == "open":
        pen.poly(ellipse(x, y, r * 1.12, r * 0.92), skin)
        pen.dot(x - side * r * 0.95, y - r * 0.35, r * 0.42, skin)  # thumb
    elif kind == "palm":
        pen.poly(ellipse(x, y, r * 1.15, r * 1.25), skin)
        for k in (-1, 0, 1):  # finger lines
            pen.stroke([(x + k * r * 0.45, y - r * 0.9), (x + k * r * 0.45, y - r * 0.2)], mix(skin, INK, 0.45), 2.5)
    elif kind == "point":
        tip = (x + side * r * 1.9, y - 2)
        pen.stroke([(x, y - 2), tip], INK, 15 + 2 * LINE)
        pen.stroke([(x, y - 2), tip], skin, 15)
        pen.dot(x, y, r, skin)
    elif kind == "phone":
        pen.poly([(x - 24, y - 52), (x + 24, y - 52), (x + 24, y + 36), (x - 24, y + 36)], (40, 42, 50))
        pen.poly([(x - 17, y - 44), (x + 17, y - 44), (x + 17, y + 26), (x - 17, y + 26)], (120, 190, 235), False)
        pen.dot(x, y + 18, r * 0.95, skin)
    elif kind == "mug":
        cup = rgb(cs.COLORS[spec["accent_color"]])
        pen.poly(ellipse(x + 34, y - 10, 15, 19, 24), cup)  # handle
        pen.poly(ellipse(x + 34, y - 10, 7, 10, 24), mix(cup, INK, 0.1), False)
        pen.poly([(x - 30, y - 44), (x + 30, y - 44), (x + 26, y + 22), (x - 26, y + 22)], cup)
        pen.poly(ellipse(x, y - 44, 30, 7, 24), mix(cup, (60, 35, 25), 0.75))
        pen.dot(x - 6, y + 4, r * 0.9, skin)
    else:
        pen.dot(x, y, r, skin)


def _arm(pen: Pen, lay: dict, side: int, spec: dict, geo: Geo, colors: tuple) -> None:
    outfit, accent, skin = colors
    sleeve = accent if spec["outfit"] == "apron" else outfit
    w = 40 * geo.arm
    pts = [lay["shoulder"], lay["elbow"], lay["hand"]]
    outfit_name = spec["outfit"]
    if outfit_name in LONG_SLEEVES:
        _limb(pen, pts, w, sleeve)
        cuff = lerp(lay["elbow"], lay["hand"], 0.86)
        pen.stroke([lerp(lay["elbow"], lay["hand"], 0.80), cuff], mix(sleeve, INK, 0.25), w * 0.92)
    else:
        _limb(pen, pts, w * 0.86, skin)
        if outfit_name not in NO_SLEEVES:
            end = lerp(lay["shoulder"], lay["elbow"], 0.62)
            _limb(pen, [lay["shoulder"], end], w * 1.12, sleeve)
    _hand(pen, *lay["hand"], lay["kind"], side, skin, spec)


# ------------------------------------------------------------------ body and clothes

def _torso_outline(geo: Geo, raise_: float, neckline: str) -> list:
    S, waist, nk = geo.S, geo.waist, geo.neck / 2
    top = -2 - raise_
    right = (bez((nk, top), (S * 0.55, top - 8), (S, 6 - raise_), (S, 42 - raise_), 10)
             + bez((S, 42 - raise_), (S + 18, 200), (waist + (22 if waist > S else 0), 330), (waist, 470), 10))
    left = [(-x, y) for x, y in reversed(right)]
    if neckline == "v":
        neck = [(-nk, top), (0, top + 70), (nk, top)]
    elif neckline == "scoop":
        neck = bez((-nk - 10, top), (-nk, top + 46), (nk, top + 46), (nk + 10, top), 8)
    else:  # crew
        neck = bez((-nk, top), (-nk * 0.6, top + 16), (nk * 0.6, top + 16), (nk, top), 8)
    return neck[1:] + right + [(waist, 520), (-waist, 520)] + left


def _neck(pen: Pen, geo: Geo, skin) -> None:
    nk = geo.neck / 2
    chin = geo.hy + geo.H * 0.40
    pen.poly([(-nk, chin), (nk, chin), (nk, 20), (-nk, 20)], skin)
    pen.poly(clip_half(ellipse(0, chin + 6, nk + 4, 26), 0, -1, -(chin + 4)), mix(skin, INK, 0.18), False)


def _hood(pen: Pen, geo: Geo, outfit) -> None:
    S = geo.S
    pen.poly(bez((-S * 0.78, 30), (-S * 0.9, -40), (S * 0.9, -40), (S * 0.78, 30), 16), mix(outfit, INK, 0.18))


def _torso(pen: Pen, spec: dict, geo: Geo, colors: tuple, raise_: float) -> None:
    outfit, accent, skin = colors
    kind = spec["outfit"]
    S, nk = geo.S, geo.neck / 2
    top = -2 - raise_
    dark = mix(outfit, INK, 0.2)
    if kind in ("tank top", "dress"):
        neckline = "scoop"
        body = _torso_outline(geo, raise_, neckline)
        # bare shoulders: the garment starts below them, held up by straps
        pen.poly(_torso_outline(geo, raise_, "crew"), skin)
        garment = clip_half(body, 0, -1, -(60 - raise_)) if kind == "dress" else clip_half(body, 0, -1, -(70 - raise_))
        pen.poly(garment, outfit)
        for sx in (-1, 1):
            strap_x = sx * S * (0.45 if kind == "tank top" else 0.5)
            pen.poly([(strap_x - 11, top + 4), (strap_x + 11, top + 4), (strap_x + 9, 72 - raise_),
                      (strap_x - 9, 72 - raise_)], outfit)
        if kind == "dress":
            pen.stroke([(-geo.waist * 0.9, 300), (geo.waist * 0.9, 300)], dark, 4)
        return
    neckline = "v" if kind == "scrubs" else "crew"
    pen.poly(_torso_outline(geo, raise_, neckline), accent if kind == "apron" else outfit)

    if kind in ("shirt", "shirt and tie", "blazer"):
        shirt = accent if kind == "blazer" else outfit
        if kind == "blazer":  # the shirt shows in a V between the lapels
            pen.poly(_torso_outline(geo, raise_, neckline), outfit)
            pen.poly([(-nk - 4, top), (nk + 4, top), (0, 170)], shirt)
            for sx in (-1, 1):
                pen.poly([(sx * (nk + 4), top), (sx * (nk + 34), top + 30), (sx * 30, 150), (0, 172)], dark)
            for y in (205, 260):
                pen.dot(0, y, 6, mix(outfit, INK, 0.35))
        else:
            pen.stroke([(0, top + 30), (0, 470)], dark, 3)
            for y in (60, 130, 200, 270):
                pen.dot(0, y, 4.5, mix(shirt, WHITE, 0.4))
        for sx in (-1, 1):  # collar flaps
            pen.poly([(sx * 4, top + 26), (sx * (nk + 10), top - 4), (sx * (nk + 20), top + 34)],
                     mix(shirt, WHITE, 0.25))
        if kind == "shirt and tie":
            tie = accent
            pen.poly([(-12, top + 24), (12, top + 24), (8, top + 46), (-8, top + 46)], tie)
            pen.poly([(-8, top + 46), (8, top + 46), (18, 230), (0, 262), (-18, 230)], tie)
    elif kind == "hoodie":
        for sx in (-1, 1):
            pen.stroke([(sx * 16, top + 14), (sx * 20, 130)], mix(outfit, WHITE, 0.55), 5)
            pen.dot(sx * 20, 136, 6, mix(outfit, WHITE, 0.55))
        pen.stroke(bez((-nk - 6, top), (-nk, top + 24), (nk, top + 24), (nk + 6, top), 8), dark, 9)
    elif kind == "sweater":
        pen.stroke(bez((-nk - 4, top), (-nk * 0.6, top + 20), (nk * 0.6, top + 20), (nk + 4, top), 10), dark, 14)
        for y in (330, 345):
            pen.stroke([(-geo.waist * 0.95, y), (geo.waist * 0.95, y)], dark, 3)
    elif kind == "polo":
        for sx in (-1, 1):
            pen.poly([(sx * 2, top + 18), (sx * (nk + 8), top - 6), (sx * (nk + 26), top + 22), (sx * 10, top + 40)],
                     mix(outfit, WHITE, 0.2))
        pen.stroke([(0, top + 24), (0, 120)], dark, 3)
        for y in (60, 100):
            pen.dot(0, y, 4.5, WHITE)
    elif kind == "scrubs":
        pen.poly([(S * 0.25, 120), (S * 0.62, 120), (S * 0.60, 190), (S * 0.27, 190)], mix(outfit, INK, 0.1))
        pen.stroke([(S * 0.36, 98), (S * 0.36, 140)], (60, 60, 70), 5)
    elif kind == "apron":
        bib = outfit
        pen.poly([(-S * 0.52, 120), (S * 0.52, 120), (S * 0.56, 520), (-S * 0.56, 520)], bib)
        for sx in (-1, 1):
            pen.stroke([(sx * S * 0.46, 122), (sx * (nk + 6), top + 6)], bib, 9)
        pen.poly([(-S * 0.25, 200), (S * 0.25, 200), (S * 0.25, 270), (-S * 0.25, 270)], mix(bib, INK, 0.12))
    elif kind in ("cardigan", "jacket"):
        # Worn open: the top underneath shows down the middle.
        pen.poly([(-nk - 2, top), (nk + 2, top), (34, 520), (-34, 520)], accent)
        if kind == "jacket":
            for sx in (-1, 1):
                pen.poly([(sx * (nk + 2), top), (sx * (nk + 34), top + 6), (sx * (nk + 20), top + 52)], dark)
                pen.stroke([(sx * (nk - 4 + 36 * 0.5), 130), (sx * 33, 470)], mix(outfit, WHITE, 0.45), 3)
        else:
            for y in (170, 240, 310):
                pen.dot(-30, y, 5, WHITE)


def _accessory_body(pen: Pen, spec: dict, geo: Geo, colors: tuple, raise_: float) -> None:
    outfit, accent, skin = colors
    kind = spec["accessory"]
    nk = geo.neck / 2
    top = -2 - raise_
    if kind == "necklace":
        pts = bez((-nk - 6, top + 2), (-nk, top + 46), (nk, top + 46), (nk + 6, top + 2), 10)
        for x, y in pts[1:-1]:
            pen.dot(x, y, 4.2, GOLD, False)
    elif kind == "lanyard":
        card = (0, 200)
        for sx in (-1, 1):
            pen.stroke([(sx * (nk - 4), top + 4), (sx * 6, card[1] - 30)], accent, 6)
        pen.poly([(-26, 170), (26, 170), (26, 236), (-26, 236)], WHITE)
        pen.poly([(-16, 182), (4, 182), (4, 202), (-16, 202)], mix(accent, WHITE, 0.3), False)
    elif kind == "scarf":
        wool = accent if sum(accent) < 600 else (196, 64, 60)  # a white scarf would read as a collar
        stripe = mix(wool, WHITE, 0.45)
        pen.poly([(nk - 4, top + 10), (nk + 30, top + 14), (nk + 34, 175), (nk + 2, 175)], wool)
        pen.poly([(nk - 14, top + 14), (nk + 12, top + 16), (nk + 6, 140), (nk - 20, 138)], mix(wool, INK, 0.12))
        for y in (150, 162):
            pen.stroke([(nk + 6, y), (nk + 30, y)], stripe, 4)
        pen.poly(bez((-nk - 24, top - 20), (-nk - 34, top + 40), (nk + 34, top + 40), (nk + 24, top - 20), 14)
                 + bez((nk + 10, top - 40), (nk * 0.4, top - 18), (-nk * 0.4, top - 18), (-nk - 10, top - 40), 8), wool)
        pen.stroke(bez((-nk - 18, top + 6), (-nk * 0.5, top + 26), (nk * 0.5, top + 26), (nk + 18, top + 6), 10), stripe, 4)


# ------------------------------------------------------------------ head and face

def _clip_lid(eye: list, cx: float, y0: float, slope: float, above: bool) -> list:
    """The part of the eye above (or below) the lid line y = y0 + slope (x - cx)."""
    # a*x + b*y <= c with the line y - slope*x = y0 - slope*cx
    if above:
        return clip_half(eye, -slope, 1, y0 - slope * cx)
    return clip_half(eye, slope, -1, -(y0 - slope * cx))


EYE_LIDS = {  # upper lid cover (0-1), slope towards the nose (+ inner corner lower), lower lid cover
    "neutral": (0.14, 0.0, 0.0), "happy": (0.12, 0.0, 0.32), "annoyed": (0.50, 0.40, 0.0),
    "surprised": (0.0, 0.0, 0.0), "sad": (0.32, -0.40, 0.0), "smug": (0.46, 0.0, 0.12),
}


def _eye(pen: Pen, spec: dict, geo: Geo, side: int, emotion: str, blink: bool, gaze: tuple, skin) -> None:
    cx, cy = side * geo.eye_dx, geo.eye_y
    rx, ry = geo.erx, geo.ery
    if emotion == "surprised":
        rx, ry = rx * 1.15, ry * 1.2
    if blink:
        if emotion == "happy":
            pen.stroke(bez((cx - rx, cy + 3), (cx - rx * 0.4, cy - ry * 0.7), (cx + rx * 0.4, cy - ry * 0.7),
                           (cx + rx, cy + 3), 8), INK, 5)
        else:
            pen.stroke(bez((cx - rx, cy), (cx - rx * 0.4, cy + ry * 0.45), (cx + rx * 0.4, cy + ry * 0.45),
                           (cx + rx, cy), 8), INK, 5)
        return
    eye = ellipse(cx, cy, rx, ry, 36)
    pen.poly(eye, WHITE, outline=True, width=4.5)
    pr = rx * (0.46 if emotion == "surprised" else 0.58)
    px = cx + gaze[0] * rx * 0.36
    py = cy + gaze[1] * ry * 0.28 + (ry * 0.08 if emotion in ("annoyed", "smug") else 0)
    pupil = clip_convex(ellipse(px, py, pr, pr * 1.06, 24), eye)
    pen.poly(pupil or ellipse(px, py, pr, pr, 24), INK, False)
    pen.dot(px + pr * 0.32, py - pr * 0.38, pr * 0.28, WHITE, False)
    cover, slope_k, lower = EYE_LIDS.get(emotion, EYE_LIDS["neutral"])
    if spec["eyes"] == "sleepy":
        cover = max(cover, 0.42)
    slope = -side * slope_k  # positive slope_k lowers the inner corner
    if cover > 0:
        lid = _clip_lid(eye, cx, cy - ry + 2 * ry * cover, slope, above=True)
        if len(lid) > 2:
            pen.poly(lid, skin, outline=True, width=4.5)
    if lower > 0:
        lid = _clip_lid(eye, cx, cy + ry - 2 * ry * lower, 0, above=False)
        if len(lid) > 2:
            pen.poly(lid, skin, outline=True, width=4)
    if spec["eyes"] == "lashes":  # two short flicks at the outer corner
        for k, a in enumerate((-12, -38)):
            r = math.radians(a)
            base = (cx + side * rx * math.cos(r), cy + ry * math.sin(r) * (1 - cover))
            pen.stroke([base, (base[0] + side * (9 - k * 2), base[1] - 6 - k * 3)], INK, 3.5)


BROWS = {  # inner and outer end raise (negative = up)
    "neutral": (0, -3), "happy": (-6, -7), "annoyed": (11, -5), "surprised": (-17, -14),
    "sad": (-13, 5), "smug": (2, 0),
}


def _brow(pen: Pen, spec: dict, geo: Geo, side: int, emotion: str) -> None:
    cx = side * geo.eye_dx
    base = geo.eye_y - geo.ery - 15
    inner, outer = BROWS.get(emotion, BROWS["neutral"])
    if emotion == "smug" and side == -1:
        inner, outer = -12, -16
    rx = geo.erx
    p_in = (cx - side * rx * 0.95, base + inner)
    p_out = (cx + side * rx * 1.25, base + outer)
    mid = lerp(p_in, p_out, 0.5)
    pts = bez(p_in, (mid[0] - side * 6, mid[1] - 7), (mid[0] + side * 6, mid[1] - 7), p_out, 10)
    pen.stroke(pts, brow_rgb(spec), 9.5)


def _nose(pen: Pen, spec: dict, geo: Geo, skin) -> None:
    y = geo.nose_y
    shade = mix(skin, INK, 0.16)
    kind = spec["nose"]
    if kind == "round":
        pen.poly(ellipse(0, y + 2, 13, 11, 24), shade, outline=True, width=4)
    elif kind == "big":
        pen.poly(ellipse(0, y + 2, 18, 15, 24), shade, outline=True, width=4.5)
        for sx in (-1, 1):
            pen.dot(sx * 6, y + 9, 2.6, mix(skin, INK, 0.5), False)
    elif kind == "pointy":
        pen.poly(bez((-2, y - 24), (4, y - 10), (16, y + 2), (8, y + 8), 8) + [(-6, y + 8)], shade, outline=True, width=4)
    else:
        pen.stroke(bez((-7, y - 4), (-11, y + 8), (6, y + 10), (9, y + 3), 8), INK, 4.5)


def _mouth_poly(hw: float, top: float, bottom: float) -> list:
    corner = top + (bottom - top) * 0.32
    return (bez((-hw, corner), (-hw * 0.5, top), (hw * 0.5, top), (hw, corner), 10)[:-1]
            + bez((hw, corner), (hw * 0.62, bottom), (-hw * 0.62, bottom), (-hw, corner), 10)[:-1])


def _mouth(pen: Pen, spec: dict, geo: Geo, shape: str, emotion: str, skin) -> None:
    w = geo.mouth_w
    m = pen.child(0, geo.mouth_y)
    smile = {"happy": -4, "sad": 4}.get(emotion, 0)

    def open_mouth(hw, top, bottom, teeth=0.0, tongue=0.0, tongue_up=False):
        poly = _mouth_poly(hw, top, bottom)
        poly = [(x, y + smile * (abs(x) / hw) ** 2) for x, y in poly]
        m.poly(poly, MOUTH, outline=False)
        if tongue:
            ty = top + (bottom - top) * (0.15 if tongue_up else 0.62)
            t = clip_convex(ellipse(0, ty + (bottom - top) * 0.25, hw * 0.62, (bottom - top) * tongue, 24), poly)
            if len(t) > 2:
                m.poly(t, TONGUE, False)
        if teeth:
            band = clip_half(poly, 0, 1, top + (bottom - top) * teeth)
            if len(band) > 2:
                m.poly(band, WHITE, False)
        m.stroke(poly + poly[:2], INK, 4.5)

    if shape == "X":
        if emotion == "happy":
            open_mouth(w * 0.55, -4, w * 0.42, teeth=0.35, tongue=0.35)
        elif emotion == "surprised":
            m.poly(ellipse(0, 6, w * 0.18, w * 0.24, 24), MOUTH, outline=True, width=4.5)
        elif emotion == "sad":
            m.stroke(bez((-w * 0.45, 8), (-w * 0.2, -5), (w * 0.2, -5), (w * 0.45, 8), 10), INK, 5)
        elif emotion == "annoyed":
            m.stroke(bez((-w * 0.42, 4), (-w * 0.1, 0), (w * 0.1, 0), (w * 0.42, 5), 10), INK, 5)
        elif emotion == "smug":
            m.stroke(bez((-w * 0.38, 3), (-w * 0.08, 6), (w * 0.22, 3), (w * 0.48, -9), 10), INK, 5)
        else:
            m.stroke(bez((-w * 0.46, -1), (-w * 0.22, 8), (w * 0.22, 8), (w * 0.46, -1), 10), INK, 5)
    elif shape == "A":
        m.stroke(bez((-w * 0.42, 0), (-w * 0.15, 4 - smile), (w * 0.15, 4 - smile), (w * 0.42, 0), 10), INK, 5.5)
    elif shape == "B":
        open_mouth(w * 0.42, -w * 0.06, w * 0.17, teeth=0.55)
    elif shape == "C":
        open_mouth(w * 0.42, -w * 0.10, w * 0.34, teeth=0.25, tongue=0.3)
    elif shape == "D":
        open_mouth(w * 0.46, -w * 0.12, w * 0.56, teeth=0.18, tongue=0.4)
    elif shape == "E":
        mouth = ellipse(0, w * 0.12, w * 0.27, w * 0.24, 28)
        m.poly(mouth, MOUTH, outline=False)
        t = clip_convex(ellipse(0, w * 0.28, w * 0.18, w * 0.1, 20), mouth)
        if len(t) > 2:
            m.poly(t, TONGUE, False)
        m.stroke(mouth + mouth[:2], INK, 4.5)
    elif shape == "F":
        lip = mix(skin, (190, 70, 80), 0.3)
        m.poly(ellipse(0, w * 0.06, w * 0.2, w * 0.22, 24), lip, outline=True, width=4.5)
        m.poly(ellipse(0, w * 0.06, w * 0.09, w * 0.11, 20), MOUTH, False)
    elif shape == "G":
        open_mouth(w * 0.36, -w * 0.05, w * 0.18, teeth=0.7)
        m.stroke(bez((-w * 0.3, w * 0.14), (-w * 0.1, w * 0.2), (w * 0.1, w * 0.2), (w * 0.3, w * 0.14), 8), INK, 4)
    elif shape == "H":
        open_mouth(w * 0.38, -w * 0.09, w * 0.32, teeth=0.2, tongue=0.32, tongue_up=True)
    else:
        m.stroke([(-w * 0.4, 0), (w * 0.4, 0)], INK, 5)


def _facial_hair(pen: Pen, spec: dict, geo: Geo, skin, layer: str) -> None:
    kind = spec["facial_hair"]
    if kind == "none":
        return
    hair = hair_rgb(spec)
    if layer == "under":  # drawn before the mouth
        if kind == "stubble":
            area = clip_half(geo.head_outline(0.995), 0, -1, -(geo.nose_y + 8))
            pen.poly(area, mix(skin, hair, 0.24), False)
        elif kind == "beard":
            jaw = [p for p in geo.head_outline(1.07) if p[1] > geo.hy + geo.H * 0.04]
            jaw.sort(key=lambda p: math.atan2(p[1] - geo.hy, p[0]))
            top = bez((-geo.W * 0.44, geo.hy + geo.H * 0.08), (-geo.W * 0.3, geo.nose_y + 30),
                      (geo.W * 0.3, geo.nose_y + 30), (geo.W * 0.44, geo.hy + geo.H * 0.08), 12)
            jaw_r = sorted(jaw, key=lambda p: -p[0])
            pen.poly(jaw_r + top, hair)
            pen.poly(ellipse(0, geo.mouth_y + 4, geo.mouth_w * 0.62, geo.mouth_w * 0.36, 28), mix(skin, hair, 0.35), False)
        elif kind == "goatee":
            pen.poly(ellipse(0, geo.mouth_y + geo.H * 0.1, geo.mouth_w * 0.36, geo.H * 0.075, 28), hair)
    else:  # over the mouth
        if kind in ("mustache", "beard", "goatee"):
            y = geo.mouth_y - 12
            wide = geo.mouth_w * (0.62 if kind != "goatee" else 0.48)
            pen.poly(bez((0, y - 6), (-wide * 0.4, y - 14), (-wide, y - 6), (-wide * 1.05, y + 8), 10)
                     + bez((-wide * 1.05, y + 8), (-wide * 0.6, y + 6), (-wide * 0.2, y + 6), (0, y + 2), 8)
                     + bez((0, y + 2), (wide * 0.2, y + 6), (wide * 0.6, y + 6), (wide * 1.05, y + 8), 8)
                     + bez((wide * 1.05, y + 8), (wide, y - 6), (wide * 0.4, y - 14), (0, y - 6), 10), hair)


def _glasses(pen: Pen, spec: dict, geo: Geo) -> None:
    kind = spec["glasses"]
    if kind == "none":
        return
    r = max(geo.erx, geo.ery) * 1.5
    frame = INK
    for sx in (-1, 1):
        cx, cy = sx * geo.eye_dx, geo.eye_y
        if kind == "round":
            lens = ellipse(cx, cy, r, r * 0.95, 36)
        else:
            lens = [(cx + (r * 1.15) * math.copysign(abs(math.cos(t)) ** 0.45, math.cos(t)),
                     cy + (r * 0.85) * math.copysign(abs(math.sin(t)) ** 0.45, math.sin(t)))
                    for t in (2 * math.pi * i / 40 for i in range(40))]
        if kind == "sunglasses":
            pen.poly(lens, (38, 40, 52), outline=True, width=5)
            pen.stroke([(cx - r * 0.5, cy - r * 0.3), (cx - r * 0.1, cy - r * 0.55)], (120, 130, 160), 4)
        else:
            pen.stroke(lens + lens[:2], frame, 4.5)
        edge = sx * geo.W * 0.48
        pen.stroke([(cx + sx * r * (1.15 if kind != "round" else 1.0), cy - 2), (edge, cy - 6)], frame, 4.5)
    pen.stroke(bez((-geo.eye_dx + r * 0.95, geo.eye_y - 4), (-6, geo.eye_y - 12), (6, geo.eye_y - 12),
                   (geo.eye_dx - r * 0.95, geo.eye_y - 4), 8), frame, 4.5)


def _cloud(center: tuple, rx: float, ry: float, bumps: int, bump_r: float, a0: float = 0, a1: float = 2 * math.pi) -> list:
    """Circles along an ellipse: curly hair, afro."""
    out = []
    for i in range(bumps):
        t = a0 + (a1 - a0) * (i + 0.5) / bumps
        out.append((center[0] + rx * math.cos(t), center[1] + ry * math.sin(t), bump_r))
    return out


def _hair_back(pen: Pen, spec: dict, geo: Geo) -> None:
    kind, hair = spec["hair"], hair_rgb(spec)
    W, H, hy = geo.W, geo.H, geo.hy
    if kind == "long":
        pen.poly(bez((-W * 0.56, hy - H * 0.2), (-W * 0.66, hy + H * 0.5), (-W * 0.7, hy + H * 0.9), (-W * 0.52, hy + H * 1.05), 12)
                 + bez((-W * 0.52, hy + H * 1.05), (-W * 0.2, hy + H * 1.12), (W * 0.2, hy + H * 1.12), (W * 0.52, hy + H * 1.05), 10)
                 + bez((W * 0.52, hy + H * 1.05), (W * 0.7, hy + H * 0.9), (W * 0.66, hy + H * 0.5), (W * 0.56, hy - H * 0.2), 12)
                 + bez((W * 0.56, hy - H * 0.2), (W * 0.4, hy - H * 0.6), (-W * 0.4, hy - H * 0.6), (-W * 0.56, hy - H * 0.2), 12),
                 hair)
    elif kind == "bob":
        pen.poly(bez((-W * 0.6, hy - H * 0.1), (-W * 0.66, hy + H * 0.28), (-W * 0.6, hy + H * 0.44), (-W * 0.44, hy + H * 0.46), 10)
                 + [(W * 0.44, hy + H * 0.46)]
                 + bez((W * 0.44, hy + H * 0.46), (W * 0.6, hy + H * 0.44), (W * 0.66, hy + H * 0.28), (W * 0.6, hy - H * 0.1), 10)
                 + bez((W * 0.6, hy - H * 0.1), (W * 0.45, hy - H * 0.66), (-W * 0.45, hy - H * 0.66), (-W * 0.6, hy - H * 0.1), 12),
                 hair)
    elif kind == "afro":
        bumps = _cloud((0, hy - H * 0.12), W * 0.62, H * 0.5, 16, W * 0.17)
        for x, y, r in bumps:
            pen.dot(x, y, r, hair)
        pen.poly(ellipse(0, hy - H * 0.12, W * 0.64, H * 0.52, 40), hair, False)
    elif kind == "ponytail":
        pen.poly(bez((W * 0.3, hy - H * 0.3), (W * 0.8, hy - H * 0.2), (W * 0.82, hy + H * 0.4), (W * 0.6, hy + H * 0.7), 12)
                 + bez((W * 0.6, hy + H * 0.7), (W * 0.62, hy + H * 0.3), (W * 0.5, hy), (W * 0.3, hy - H * 0.1), 10), hair)
    elif kind == "receding":  # hair left above and behind the ears; the head covers the inner part
        for sx in (-1, 1):
            pen.poly(bez((sx * W * 0.36, hy - H * 0.3), (sx * W * 0.62, hy - H * 0.28), (sx * W * 0.6, hy + H * 0.05),
                         (sx * W * 0.46, hy + H * 0.12), 12) + [(sx * W * 0.3, hy)], hair)


def _cap(geo: Geo, s: float, hairline: float) -> list:
    """A hat covering the head above y = hairline, slightly bigger than the head."""
    return clip_half(geo.head_outline(s), 0, 1, hairline)


def _shell(geo: Geo, s: float, side_y: float) -> list:
    """The top of the head, slightly bigger than it, from the left side at height side_y over the top to
    the right side at the same height: the upper edge of every hairstyle."""
    rx, ry = geo.W / 2 * s, geo.H / 2 * s
    ex = 2 / geo.n
    # where the outline reaches side_y on each side
    k = max(-0.999, min(0.999, (side_y - geo.hy) / ry))
    t_side = math.asin(math.copysign(abs(k) ** (geo.n / 2), k))
    pts = []
    for i in range(41):
        t = math.pi - t_side + (math.pi + 2 * t_side) * i / 40  # left side -> top -> right side
        c, sn = math.cos(t), math.sin(t)
        x = math.copysign(abs(c) ** ex, c)
        y = math.copysign(abs(sn) ** ex, sn)
        jaw = 1 - geo.taper * max(sn, 0) ** 1.6
        pts.append((rx * jaw * x, geo.hy + ry * y))
    return pts


def _hair_front(pen: Pen, spec: dict, geo: Geo, skin) -> None:
    kind, hair = spec["hair"], hair_rgb(spec)
    W, H, hy = geo.W, geo.H, geo.hy
    top = hy - H / 2
    shade = mix(hair, INK, 0.35)
    if kind == "bald":
        pen.poly(ellipse(-W * 0.16, top + H * 0.12, W * 0.12, H * 0.05, 20), mix(skin, WHITE, 0.4), False)
        return
    if kind == "receding":  # the side hair is drawn behind the head (_hair_back); a few strands on top
        pen.stroke(bez((-W * 0.2, top + 16), (-W * 0.05, top + 6), (W * 0.1, top + 8), (W * 0.22, top + 18), 8),
                   mix(hair, skin, 0.3), 3)
        return
    if kind == "buzz":
        shell = _shell(geo, 1.015, hy - H * 0.16)
        edge = bez(shell[-1], (W * 0.3, hy - H * 0.3), (-W * 0.3, hy - H * 0.3), shell[0], 12)
        pen.poly(shell + edge[1:-1], mix(hair, skin, 0.3), outline=True, width=4)
        return
    if kind == "afro":
        shell = _shell(geo, 1.0, hy - H * 0.14)
        edge = bez(shell[-1], (W * 0.3, hy - H * 0.32), (-W * 0.3, hy - H * 0.32), shell[0], 12)
        pen.poly(shell + edge[1:-1], hair, outline=True, width=4)
        return
    if kind == "curly":
        shell = _shell(geo, 1.04, hy - H * 0.05)
        edge = bez(shell[-1], (W * 0.3, hy - H * 0.26), (-W * 0.3, hy - H * 0.26), shell[0], 12)
        pen.poly(shell + edge[1:-1], hair, False)
        bumps = _cloud((0, hy - H * 0.08), W * 0.5, H * 0.45, 12, W * 0.13, math.pi * 0.98, math.pi * 2.02)
        for x, y, r in bumps:
            pen.dot(x, y, r, hair)
        for x, y, r in bumps:
            pen.poly(ellipse(x, y, r - 5.5, r - 5.5, 20), hair, False)
        pen.poly(shell + edge[1:-1], hair, False)
        for x, y, r in bumps[2:-2:2]:  # a few curls drawn in
            pen.stroke(bez((x - r * 0.4, y), (x - r * 0.2, y - r * 0.5), (x + r * 0.3, y - r * 0.3), (x + r * 0.2, y + r * 0.2), 6),
                       shade, 3)
        return
    if kind == "long":  # parted in the middle, falling past the cheeks (the rest is behind the head)
        shell = _shell(geo, 1.05, hy + H * 0.18)
        right = bez(shell[-1], (W * 0.42, hy - H * 0.05), (W * 0.24, hy - H * 0.36), (0, top + H * 0.13), 12)
        left = bez((0, top + H * 0.13), (-W * 0.24, hy - H * 0.36), (-W * 0.42, hy - H * 0.05), shell[0], 12)
        pen.poly(shell + right[1:] + left[1:-1], hair)
        pen.stroke([(0, top + H * 0.02), (0, top + H * 0.13)], shade, 3)
        return
    if kind == "bob":  # straight fringe
        shell = _shell(geo, 1.05, hy + H * 0.12)
        fringe_y = hy - H * 0.15
        pen.poly(shell + [(W * 0.44, hy + H * 0.12), (W * 0.40, fringe_y), (-W * 0.40, fringe_y), (-W * 0.44, hy + H * 0.12)], hair)
        for k in (-2, -1, 1, 2):
            pen.stroke([(k * W * 0.12, fringe_y - 30), (k * W * 0.12 + 4, fringe_y - 2)], shade, 2.5)
        return
    if kind == "bun":
        pen.dot(0, top - H * 0.07, W * 0.19, hair)
        pen.stroke([(-W * 0.13, top + H * 0.05), (W * 0.13, top + H * 0.05)], shade, 5)
    if kind in ("bun", "ponytail"):  # pulled back: a high, smooth hairline
        shell = _shell(geo, 1.04, hy - H * 0.06)
        edge = bez(shell[-1], (W * 0.32, hy - H * 0.38), (-W * 0.32, hy - H * 0.38), shell[0], 14)
        pen.poly(shell + edge[1:-1], hair)
        pen.stroke(bez((-W * 0.3, top + 18), (-W * 0.1, top + 10), (W * 0.1, top + 10), (W * 0.3, top + 18), 8), shade, 2.5)
        return
    # short styles: hair to just above the ears, with sideburns, then the style's own shape
    shell = _shell(geo, 1.05, hy + H * 0.02)
    if kind == "side part":  # swept from a part on the left across to the right
        edge = (bez(shell[-1], (W * 0.44, hy - H * 0.2), (W * 0.2, hy - H * 0.3), (-W * 0.05, hy - H * 0.33), 10)
                + bez((-W * 0.05, hy - H * 0.33), (-W * 0.25, hy - H * 0.34), (-W * 0.42, hy - H * 0.3), (-W * 0.44, hy - H * 0.12), 8)[1:])
        pen.poly(shell + edge[1:] + [(-W * 0.47, hy + H * 0.02)], hair)
        pen.stroke(bez((-W * 0.22, top + 6), (-W * 0.16, top + 30), (W * 0.1, hy - H * 0.32), (W * 0.3, hy - H * 0.26), 10), shade, 3)
    elif kind == "pixie":  # a fringe swept to one side
        edge = bez(shell[-1], (W * 0.38, hy - H * 0.05), (W * 0.1, hy - H * 0.2), (-W * 0.42, hy - H * 0.3), 12)
        pen.poly(shell + edge[1:] + [(-W * 0.47, hy + H * 0.02)], hair)
        pen.stroke(bez((W * 0.3, top + 20), (W * 0.1, hy - H * 0.32), (-W * 0.1, hy - H * 0.3), (-W * 0.3, hy - H * 0.28), 10), shade, 2.5)
    else:  # short, quiff
        edge = (bez(shell[-1], (W * 0.46, hy - H * 0.12), (W * 0.36, hy - H * 0.22), (W * 0.2, hy - H * 0.24), 8)
                + bez((W * 0.2, hy - H * 0.24), (W * 0.08, hy - H * 0.2), (-W * 0.08, hy - H * 0.2), (-W * 0.2, hy - H * 0.24), 8)[1:]
                + bez((-W * 0.2, hy - H * 0.24), (-W * 0.36, hy - H * 0.22), (-W * 0.46, hy - H * 0.12), shell[0], 8)[1:])
        pen.poly(shell + edge[1:-1], hair)
        if kind == "quiff":
            pen.poly(bez((-W * 0.34, hy - H * 0.28), (-W * 0.32, top - H * 0.2), (W * 0.12, top - H * 0.3), (W * 0.38, top - H * 0.06), 14)
                     + bez((W * 0.38, top - H * 0.06), (W * 0.44, top + H * 0.06), (W * 0.3, hy - H * 0.3), (W * 0.06, hy - H * 0.3), 10),
                     hair)
            pen.stroke(bez((-W * 0.2, top - H * 0.04), (-W * 0.05, top - H * 0.16), (W * 0.15, top - H * 0.16), (W * 0.3, top - H * 0.04), 8),
                       shade, 3)
        else:
            for k in (-1, 1):
                pen.stroke(bez((k * W * 0.1, top + 12), (k * W * 0.14, top + 30), (k * W * 0.2, top + 40), (k * W * 0.26, top + 44), 6),
                           shade, 2.5)


def _hat(pen: Pen, spec: dict, geo: Geo, colors: tuple) -> None:
    kind = spec["accessory"]
    outfit, accent, skin = colors
    W, H, hy = geo.W, geo.H, geo.hy
    top = hy - H / 2
    if kind == "cap":
        pen.poly(_cap(geo, 1.08, hy - H * 0.2), accent)
        pen.poly(ellipse(0, hy - H * 0.2, W * 0.56, H * 0.065, 32), mix(accent, INK, 0.2))
        pen.dot(0, top - 4, 7, mix(accent, INK, 0.25))
    elif kind == "beanie":
        pen.poly(_cap(geo, 1.1, hy - H * 0.16), accent)
        band = [(-W * 0.56, hy - H * 0.28), (W * 0.56, hy - H * 0.28), (W * 0.56, hy - H * 0.15), (-W * 0.56, hy - H * 0.15)]
        pen.poly(band, mix(accent, INK, 0.15))
        for k in range(-5, 6):
            pen.stroke([(k * W * 0.09, hy - H * 0.27), (k * W * 0.09, hy - H * 0.16)], mix(accent, INK, 0.3), 2.5)
    elif kind == "headband":
        pen.stroke(bez((-W * 0.5, hy - H * 0.2), (-W * 0.3, hy - H * 0.32), (W * 0.3, hy - H * 0.32), (W * 0.5, hy - H * 0.2), 12),
                   INK, 22)
        pen.stroke(bez((-W * 0.5, hy - H * 0.2), (-W * 0.3, hy - H * 0.32), (W * 0.3, hy - H * 0.32), (W * 0.5, hy - H * 0.2), 12),
                   accent, 14)
    elif kind == "headphones":
        band = bez((-W * 0.54, hy - H * 0.05), (-W * 0.56, top - H * 0.22), (W * 0.56, top - H * 0.22), (W * 0.54, hy - H * 0.05), 16)
        pen.stroke(band, INK, 22)
        pen.stroke(band, (60, 62, 72), 12)
        for sx in (-1, 1):
            pen.poly(ellipse(sx * W * 0.53, hy + H * 0.03, 20, 36, 28), (60, 62, 72))
            pen.poly(ellipse(sx * W * 0.53, hy + H * 0.03, 11, 24, 24), accent if sum(accent) < 600 else (210, 70, 70), False)
    elif kind == "earrings":
        for sx in (-1, 1):
            pen.dot(sx * W * 0.5, hy + H * 0.17, 6, GOLD)


def _head(pen: Pen, spec: dict, geo: Geo, state: dict, colors: tuple) -> None:
    outfit, accent, skin = colors
    emotion = state.get("emotion", "neutral")
    gaze = state.get("gaze", (0.0, 0.0))
    for sx in (-1, 1):  # ears
        ex = sx * geo.W * 0.48
        pen.poly(ellipse(ex, geo.hy + geo.H * 0.04, 15, 23, 24), skin)
        pen.stroke(bez((ex - sx * 2, geo.hy - 4), (ex + sx * 8, geo.hy + 2), (ex + sx * 6, geo.hy + 18),
                       (ex - sx * 2, geo.hy + 22), 6), mix(skin, INK, 0.35), 3)
    pen.poly(geo.head_outline(), skin)
    _facial_hair(pen, spec, geo, skin, "under")
    blush = mix(skin, (236, 110, 110), 0.16 if sum(skin) > 420 else 0.08)
    for sx in (-1, 1):
        pen.poly(ellipse(sx * geo.W * 0.27, geo.nose_y + 10, 17, 10, 20), blush, False)
    if spec["age"] >= 45:  # a few lines for older characters
        line = mix(skin, INK, 0.3)
        for k, dy in enumerate((0.31, 0.36)):
            y = geo.hy - geo.H * dy
            pen.stroke(bez((-geo.W * 0.16, y), (-geo.W * 0.05, y - 3), (geo.W * 0.05, y - 3), (geo.W * 0.16, y), 8), line, 2.5)
        for sx in (-1, 1):
            x = sx * (geo.eye_dx + geo.erx + 6)
            pen.stroke([(x, geo.eye_y - 2), (x + sx * 8, geo.eye_y - 6)], line, 2.5)
            pen.stroke([(x, geo.eye_y + 4), (x + sx * 8, geo.eye_y + 7)], line, 2.5)
    if spec["glasses"] != "sunglasses":
        for sx in (-1, 1):
            _eye(pen, spec, geo, sx, emotion, state.get("blink", False), gaze, skin)
    for sx in (-1, 1):
        _brow(pen, spec, geo, sx, emotion)
    _nose(pen, spec, geo, skin)
    _mouth(pen, spec, geo, state.get("mouth", "X"), emotion, skin)
    _facial_hair(pen, spec, geo, skin, "over")
    _glasses(pen, spec, geo)
    if spec["accessory"] not in ("cap", "beanie"):
        _hair_front(pen, spec, geo, skin)
    elif spec["hair"] in ("long", "bob", "curly", "afro"):
        _hair_front(pen, {**spec, "hair": "short" if spec["hair"] in ("curly", "afro") else spec["hair"]}, geo, skin)
    _hat(pen, spec, geo, colors)


# ------------------------------------------------------------------ the whole character

def draw(pen: Pen, spec: dict, state: dict | None = None) -> None:
    """Draws the character with its shoulder-line centre at the pen's origin.

    state: pose (POSES), emotion (EMOTIONS), mouth (MOUTHS), blink, gaze (x, y in -1..1),
    tilt (degrees), shrug (0-1, raises the shoulders) and toward (-1 or +1: the side the others are on)."""
    state = state or {}
    geo = Geo(spec)
    colors = shirt_colors(spec)
    outfit, accent, skin = colors
    pose = state.get("pose", "down")
    raise_ = 14 * state.get("shrug", 1.0 if pose == "shrug" else 0.0)
    toward = state.get("toward", 1) or 1

    _hair_back(pen, spec, geo)
    if spec["outfit"] == "hoodie":
        _hood(pen, geo, outfit)
    _neck(pen, geo, skin)
    _torso(pen, spec, geo, colors, raise_)
    _accessory_body(pen, spec, geo, colors, raise_)

    layouts = {side: _arm_layout(pose, side, toward, geo, raise_) for side in (-1, 1)}
    face_arms = [s for s, lay in layouts.items() if lay.get("face")]
    for side in (-1, 1):
        if side not in face_arms:
            _arm(pen, layouts[side], side, spec, geo, colors)

    head = pen.child(angle=state.get("tilt", 0.0), pivot=geo.pivot)
    _head(head, spec, geo, state, colors)
    for side in face_arms:
        _arm(pen, layouts[side], side, spec, geo, colors)


def card(spec: dict, size: tuple[int, int] = (520, 640), background=(236, 233, 224), state: dict | None = None,
         supersample: int = 3) -> Image.Image:
    """A portrait of the character for the dashboard: head and shoulders on a plain backdrop."""
    w, h = size
    img = Image.new("RGB", (w * supersample, h * supersample), background)
    draw_ = ImageDraw.Draw(img)
    s = supersample * w / 520 * 1.25
    pen = Pen(draw_, (s, 0, w * supersample / 2, 0, s, h * supersample * 0.62))
    draw(pen, spec, {"pose": "down", "emotion": "happy", **(state or {})})
    return img.resize((w, h), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--spec", required=True, help="JSON file: one character or a list (validated first)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        with open(args.spec, encoding="utf-8") as f:
            raw = json.load(f)
        cast = cs.validate_cast(raw if isinstance(raw, list) else [raw, {**raw, "name": raw.get("name", "") + " Two"}])
        cards = [card(spec) for spec in cast]
        sheet = Image.new("RGB", (sum(c.width for c in cards), cards[0].height), (255, 255, 255))
        x = 0
        for c in cards:
            sheet.paste(c, (x, 0))
            x += c.width
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
