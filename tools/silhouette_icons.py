"""
Small flat drawings in the silhouette look, used three ways: inside a thought bubble (a picture instead of words), on a
phone's screen seen face-on, and floating round a head (the comic marks: hearts, $, Z, ?, !). Drawn in code like
everything else: no pictures from anywhere.

  draw(p, name, x, y, s, on="cream", t=0.0)   the icon `name` centred at (x, y), s world units from its middle to its top
                                              (its half height); on: what it sits on ("cream": a bubble, "dark": the
                                              scene or a dark screen) picks its ink; t: seconds, for the few that move
  ICONS                                       every name, with what it shows (the storyboard's words for pictures)

Lust's pictures stay symbolic and censored (hearts, lips, a phone whose screen is a pink mosaic under "18+"): never a body.
"""

import math

import numpy as np

import silhouette as S
import silhouette_words as W
from silhouette import ell, hexc, rect, rr, smooth, spline, tube

INK = hexc("#141018")          # the look's black (a bubble's drawings)
CREAM = hexc("#F4F1EA")        # the eyes' white (marks over the dark)
TEAL = hexc("#2B6470")         # his hoodie
CORAL = hexc("#FF5A44")        # the rim
HEART = hexc("#FF4F7E")        # love, lust
GOLD = hexc("#F5C542")         # money, crowns, stars
GREEN = hexc("#4CC38A")        # money's notes, envy, a tick
RED = hexc("#E8453C")          # a cross, a stamp, alarms
BLUE = hexc("#8FB8FF")         # screens, water, tears
GREY = hexc("#8C86A0")         # smoke, clouds, steel
BROWN = hexc("#6A4A3A")        # wood, bread


def _pts(x, y, s, uv):
    """Icon space (u right, v down, -1..1 from the middle) to the world."""
    return np.array([(x + u * s, y + v * s) for u, v in uv], np.float64)


def _ink(on):
    return INK if on == "cream" else CREAM


def _heart_shape(x, y, s, n=48):
    t = np.linspace(0, math.tau, n, endpoint=False)
    u = 16 * np.sin(t) ** 3 / 17
    v = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)) / 17
    return np.stack([x + u * s, y + (v + 0.12) * s], 1)


def _line(p, x, y, s, uv, w, color, alpha=1.0, k=4):
    p.poly(tube([tuple(q) for q in _pts(x, y, s, uv)], w * s, k=k), color, alpha)


def _star_shape(x, y, s, points=5, inner=0.45, rot=-math.pi / 2):
    a = rot + np.arange(points * 2) * math.pi / points
    r = np.where(np.arange(points * 2) % 2 == 0, 1.0, inner)
    return np.stack([x + np.cos(a) * r * s, y + np.sin(a) * r * s], 1)


# --- marks (floating round a head) and feelings ----------------------------------------------------------------------------
def i_heart(p, x, y, s, on, t):
    p.poly(_heart_shape(x, y, s), HEART)
    p.poly(ell(x - 0.38 * s, y - 0.30 * s, 0.16 * s, 0.10 * s, 16), CREAM, 0.55)


def i_broken_heart(p, x, y, s, on, t):
    """Two halves of a heart, apart along a jagged crack."""
    zig = [(0.0, -0.62), (0.16, -0.30), (-0.12, 0.05), (0.12, 0.40), (0.0, 0.88)]   # (top dip down to the tip)
    for side, t0, t1 in ((1, 0.0, math.pi), (-1, math.pi, math.tau)):
        a = np.linspace(t0, t1, 30)
        u = 16 * np.sin(a) ** 3 / 17
        v = -(13 * np.cos(a) - 5 * np.cos(2 * a) - 2 * np.cos(3 * a) - np.cos(4 * a)) / 17 + 0.12
        curve = np.stack([u, v], 1)
        crack = np.array(zig[::-1] if side > 0 else zig, np.float64)   # (back up to the dip, or down to the tip)
        half = np.vstack([curve, crack]) + np.array([side * 0.10, 0.04 * side])
        p.poly(np.stack([x + half[:, 0] * s, y + half[:, 1] * s], 1), HEART)


def i_lips(p, x, y, s, on, t):
    up = [(-1.0, 0.05), (-0.55, -0.42), (-0.18, -0.30), (0.0, -0.18), (0.18, -0.30), (0.55, -0.42), (1.0, 0.05),
          (0.0, 0.0)]
    low = [(-1.0, 0.05), (0.0, 0.08), (1.0, 0.05), (0.55, 0.45), (0.0, 0.58), (-0.55, 0.45)]
    p.poly(spline(_pts(x, y, s, up), True, 6), HEART)
    p.poly(spline(_pts(x, y, s, low), True, 6), hexc("#E23D6A"))
    p.poly(ell(x + 0.35 * s, y + 0.30 * s, 0.18 * s, 0.07 * s, 16), CREAM, 0.45)


def i_dollar(p, x, y, s, on, t):
    col = GOLD
    s_curve = [(0.55, -0.55), (0.0, -0.72), (-0.55, -0.45), (-0.30, -0.08), (0.30, 0.08), (0.55, 0.45), (0.0, 0.72),
               (-0.55, 0.55)]
    p.poly(tube([tuple(q) for q in spline(_pts(x, y, s, s_curve), False, 8)], 0.20 * s, k=3), col)
    _line(p, x, y, s, [(0.0, -1.0), (0.0, 1.0)], 0.14, col)


def i_z(p, x, y, s, on, t):
    _line(p, x, y, s, [(-0.7, -0.8), (0.7, -0.8), (-0.7, 0.8), (0.7, 0.8)], 0.24, _ink(on), k=2)


def i_question(p, x, y, s, on, t):
    c = _ink(on)
    arc = [(-0.55, -0.40), (-0.40, -0.85), (0.15, -1.0), (0.58, -0.70), (0.45, -0.25), (0.05, 0.05), (0.0, 0.40)]
    p.poly(tube([tuple(q) for q in spline(_pts(x, y, s, arc), False, 8)], 0.24 * s, k=3), c)
    p.circle(x, y + 0.82 * s, 0.15 * s, c)


def i_exclaim(p, x, y, s, on, t):
    c = _ink(on) if on == "cream" else hexc("#FFD25A")
    p.poly(_pts(x, y, s, [(-0.20, -1.0), (0.20, -1.0), (0.10, 0.40), (-0.10, 0.40)]), c)
    p.circle(x, y + 0.80 * s, 0.17 * s, c)


def i_star(p, x, y, s, on, t):
    p.poly(_star_shape(x, y, s), GOLD)


def i_sparkle(p, x, y, s, on, t):
    p.poly(_star_shape(x, y, s, 4, 0.22, -math.pi / 2), CREAM if on != "cream" else GOLD)


def i_bolt(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(0.15, -1.0), (-0.55, 0.12), (-0.05, 0.12), (-0.25, 1.0), (0.55, -0.20), (0.05, -0.20),
                         (0.40, -1.0)]), GOLD)


def i_drop(p, x, y, s, on, t):
    a = np.linspace(-0.15 * math.pi, 1.15 * math.pi, 22)
    drop = np.vstack([np.stack([x + np.cos(a) * 0.55 * s, y + 0.35 * s + np.sin(a) * 0.62 * s], 1), [(x, y - s)]])
    p.poly(drop, BLUE)
    p.poly(ell(x - 0.18 * s, y + 0.30 * s, 0.10 * s, 0.18 * s, 12), CREAM, 0.7)


def i_puff(p, x, y, s, on, t):
    for u, v, r in ((-0.45, 0.15, 0.45), (0.05, -0.15, 0.55), (0.50, 0.12, 0.42), (0.05, 0.30, 0.45)):
        p.circle(x + u * s, y + v * s, r * s, GREY if on == "cream" else hexc("#D9D3E2"))


def i_vein(p, x, y, s, on, t):
    """The anger mark: four bulging strokes round a cross gap."""
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        c, sn = math.cos(a), math.sin(a)
        mid = (x + c * 0.55 * s, y + sn * 0.55 * s)
        bend = [(mid[0] - sn * 0.42 * s + c * 0.10 * s, mid[1] + c * 0.42 * s + sn * 0.10 * s), mid,
                (mid[0] + sn * 0.42 * s + c * 0.10 * s, mid[1] - c * 0.42 * s + sn * 0.10 * s)]
        p.poly(tube(bend, 0.20 * s, 0.20 * s, k=6), RED)


def i_cloud_rain(p, x, y, s, on, t):
    for k in range(5):   # the rain under it, falling
        u = -0.55 + k * 0.28
        v = 0.45 + ((t * 1.6 + k * 0.37) % 1.0) * 0.55
        _line(p, x, y, s, [(u, v), (u - 0.06, v + 0.22)], 0.07, BLUE, 0.85)
    for u, v, r in ((-0.50, 0.05, 0.38), (-0.05, -0.25, 0.50), (0.48, 0.0, 0.40), (0.0, 0.15, 0.42)):
        p.circle(x + u * s, y + v * s, r * s, hexc("#55506A"))


def i_fly(p, x, y, s, on, t):
    flap = 0.5 + 0.5 * math.sin(t * 40.0)
    for side in (-1, 1):
        p.poly(S.rell(x + side * 0.35 * s, y - 0.35 * s, 0.38 * s, (0.15 + 0.12 * flap) * s, side * 0.6), CREAM, 0.45)
    p.circle(x, y, 0.30 * s, INK)


def i_dot(p, x, y, s, on, t):
    """A notification's red dot."""
    p.circle(x, y, s, RED)
    _line(p, x, y, s, [(0.0, -0.45), (0.0, 0.45)], 0.22, CREAM)


# --- money, status ------------------------------------------------------------------------------------------------------------
def i_money(p, x, y, s, on, t):
    for k, (u, v, a) in enumerate(((-0.10, 0.18, -0.12), (0.10, -0.10, 0.10))):
        cx, cy = x + u * s, y + v * s
        c, sn = math.cos(a), math.sin(a)
        rect = [(cx + c * dx * s - sn * dy * s, cy + sn * dx * s + c * dy * s) for dx, dy in
                ((-0.95, -0.50), (0.95, -0.50), (0.95, 0.50), (-0.95, 0.50))]
        p.poly(np.array(rect), hexc("#3E8F64") if k else hexc("#2E7350"))
        p.poly(ell(cx, cy, 0.28 * s, 0.28 * s, 20), hexc("#9ED8B4"))
    i_dollar(p, x + 0.10 * s, y - 0.10 * s, 0.22 * s, on, t)


def i_moneybag(p, x, y, s, on, t):
    bag = [(-0.25, -0.62), (0.25, -0.62), (0.18, -0.48), (0.70, -0.05), (0.80, 0.55), (0.45, 0.95), (-0.45, 0.95),
           (-0.80, 0.55), (-0.70, -0.05), (-0.18, -0.48)]
    p.poly(spline(_pts(x, y, s, bag), True, 8), hexc("#B88A4A"))
    p.poly(_pts(x, y, s, [(-0.32, -0.95), (0.32, -0.95), (0.22, -0.62), (-0.22, -0.62)]), hexc("#B88A4A"))
    _line(p, x, y, s, [(-0.26, -0.58), (0.26, -0.58)], 0.10, hexc("#6A4A2A"))
    i_dollar(p, x, y + 0.25 * s, 0.42 * s, on, t)


def i_crown(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-0.95, 0.55), (-0.95, -0.45), (-0.48, 0.05), (0.0, -0.70), (0.48, 0.05), (0.95, -0.45),
                         (0.95, 0.55)]), GOLD)
    for u in (-0.95, 0.0, 0.95):
        p.circle(x + u * s, y + (-0.45 if u else -0.70) * s - 0.10 * s, 0.13 * s, GOLD)
    p.circle(x, y + 0.20 * s, 0.14 * s, RED)


def i_trophy(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-0.62, -0.90), (0.62, -0.90), (0.50, -0.25), (0.18, 0.15), (-0.18, 0.15), (-0.50, -0.25)]),
           GOLD)
    for side in (-1, 1):
        p.poly(tube([(x + side * 0.55 * s, y - 0.75 * s), (x + side * 0.95 * s, y - 0.60 * s),
                     (x + side * 0.55 * s, y - 0.25 * s)], 0.12 * s, k=6), GOLD)
    p.poly(_pts(x, y, s, [(-0.10, 0.15), (0.10, 0.15), (0.14, 0.55), (-0.14, 0.55)]), GOLD)
    p.poly(rr(x - 0.50 * s, y + 0.55 * s, 1.0 * s, 0.32 * s, 0.05 * s), hexc("#6A4A3A"))


def i_wallet_empty(p, x, y, s, on, t):
    p.poly(rr(x - 0.95 * s, y - 0.45 * s, 1.9 * s, 1.2 * s, 0.15 * s), hexc("#5A3A2E"))
    p.poly(rr(x - 0.80 * s, y - 0.70 * s, 1.6 * s, 0.40 * s, 0.10 * s), hexc("#7A5242"))
    for k in range(2):   # nothing in it but moths
        i_fly(p, x + (-0.35 + 0.7 * k) * s, y - 1.0 * s - 0.1 * s * math.sin(t * 3 + k), 0.20 * s, "dark", t)


def i_car(p, x, y, s, on, t):
    body = [(-1.0, 0.35), (-0.95, 0.0), (-0.55, -0.05), (-0.30, -0.45), (0.35, -0.45), (0.62, -0.05), (0.98, 0.05),
            (1.0, 0.35)]
    p.poly(spline(_pts(x, y, s, body), True, 4), RED if on == "cream" else hexc("#C23A3A"))
    p.poly(_pts(x, y, s, [(-0.22, -0.38), (0.10, -0.38), (0.10, -0.08), (-0.45, -0.08)]), BLUE)
    p.poly(_pts(x, y, s, [(0.18, -0.38), (0.32, -0.38), (0.50, -0.08), (0.18, -0.08)]), BLUE)
    for u in (-0.58, 0.58):
        p.circle(x + u * s, y + 0.38 * s, 0.22 * s, INK)
        p.circle(x + u * s, y + 0.38 * s, 0.09 * s, GREY)


def i_house(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-0.75, -0.05), (0.0, -0.80), (0.75, -0.05)]), CORAL)
    p.poly(rr(x - 0.62 * s, y - 0.10 * s, 1.24 * s, 0.95 * s, 0.03 * s), hexc("#D9CBB8") if on == "cream" else GREY)
    p.poly(rr(x - 0.15 * s, y + 0.30 * s, 0.30 * s, 0.55 * s, 0.03 * s), BROWN)
    p.poly(rr(x + 0.25 * s, y + 0.08 * s, 0.25 * s, 0.22 * s, 0.02 * s), hexc("#FFC383"))


def i_ring(p, x, y, s, on, t):
    p.poly(tube([tuple(q) for q in ell(x, y + 0.25 * s, 0.62 * s, 0.62 * s, 40)] + [tuple(ell(x, y + 0.25 * s, 0.62 * s,
                0.62 * s, 40)[0])], 0.16 * s, k=2), GOLD)
    p.poly(_pts(x, y, s, [(-0.30, -0.55), (0.30, -0.55), (0.42, -0.42), (0.0, -0.05), (-0.42, -0.42)]), BLUE)


# --- anger ---------------------------------------------------------------------------------------------------------------------
def i_fist(p, x, y, s, on, t):
    body = hexc("#08070B") if on == "cream" else hexc("#2A2430")
    p.poly(rr(x - 0.65 * s, y - 0.55 * s, 1.30 * s, 1.0 * s, 0.30 * s), body)
    for k in range(4):
        p.circle(x - 0.48 * s + k * 0.32 * s, y - 0.55 * s, 0.17 * s, body)
    p.poly(rr(x - 0.40 * s, y + 0.35 * s, 0.80 * s, 0.65 * s, 0.08 * s), TEAL)
    for k in range(3):
        _line(p, x, y, s, [(-0.32 + k * 0.32, -0.70), (-0.32 + k * 0.32, -0.40)], 0.06, CREAM, 0.6)
    for a in (-2.5, -1.9, -1.2, -0.6):   # the force round it
        _line(p, x, y, s, [(math.cos(a) * 1.05, math.sin(a) * 1.05 - 0.2), (math.cos(a) * 1.35, math.sin(a) * 1.35 - 0.2)],
              0.08, CORAL if on == "cream" else GOLD)


def i_bomb(p, x, y, s, on, t):
    p.circle(x - 0.10 * s, y + 0.15 * s, 0.72 * s, INK if on == "cream" else hexc("#2A2430"))
    p.poly(rr(x + 0.20 * s, y - 0.62 * s, 0.30 * s, 0.30 * s, 0.05 * s), GREY)
    p.poly(tube([(x + 0.35 * s, y - 0.60 * s), (x + 0.55 * s, y - 0.85 * s), (x + 0.80 * s, y - 0.80 * s)], 0.07 * s, k=6),
           BROWN)
    flick = 1.0 + 0.25 * math.sin(t * 18.0)
    p.poly(_star_shape(x + 0.85 * s, y - 0.85 * s, 0.25 * s * flick, 6, 0.4), GOLD)
    p.poly(ell(x - 0.38 * s, y - 0.12 * s, 0.14 * s, 0.10 * s, 14), CREAM, 0.5)


def i_volcano(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-1.0, 0.9), (-0.25, -0.35), (0.25, -0.35), (1.0, 0.9)]), hexc("#5A4038"))
    p.poly(_pts(x, y, s, [(-0.25, -0.35), (0.25, -0.35), (0.15, 0.05), (0.0, -0.05), (-0.12, 0.20)]), RED)
    for k in range(3):
        u = (t * 0.6 + k / 3) % 1.0
        p.circle(x + (k - 1) * 0.25 * s, y - (0.45 + u * 0.55) * s, (0.20 + 0.15 * u) * s, GREY, 0.9 * (1 - u))
    for a in (-2.4, -1.57, -0.7):
        p.circle(x + math.cos(a) * 0.55 * s, y - 0.35 * s + math.sin(a) * 0.55 * s, 0.08 * s, hexc("#FF8A3D"))


def i_grawlix(p, x, y, s, on, t):
    """"#@%!": swearing, never spelt out."""
    c = RED
    g = 0.38 * s
    for k, cx in enumerate((-0.72, -0.24, 0.24, 0.66)):
        X = x + cx * s
        if k == 0:   # #
            for d in (-0.35, 0.35):
                p.poly(tube([(X + d * g - 0.1 * g, y - g), (X + d * g + 0.1 * g, y + g)], 0.18 * g, k=2), c)
                p.poly(tube([(X - g, y + d * g), (X + g, y + d * g)], 0.18 * g, k=2), c)
        elif k == 1:   # @
            p.poly(tube([tuple(q) for q in S._arc(X, y, 0.95 * g, 1, -0.4, 4.9, 26)], 0.18 * g, k=2), c)
            p.circle(X + 0.05 * g, y, 0.38 * g, c)
        elif k == 2:   # %
            p.circle(X - 0.45 * g, y - 0.50 * g, 0.28 * g, c)
            p.circle(X + 0.45 * g, y + 0.50 * g, 0.28 * g, c)
            p.poly(tube([(X + 0.6 * g, y - g), (X - 0.6 * g, y + g)], 0.18 * g, k=2), c)
        else:   # !
            p.poly(np.array([(X - 0.16 * g, y - g), (X + 0.16 * g, y - g), (X + 0.08 * g, y + 0.45 * g),
                             (X - 0.08 * g, y + 0.45 * g)]), c)
            p.circle(X, y + 0.82 * g, 0.16 * g, c)


def i_broken_phone(p, x, y, s, on, t):
    p.poly(rr(x - 0.48 * s, y - 0.95 * s, 0.96 * s, 1.9 * s, 0.16 * s), INK if on == "cream" else hexc("#2A2430"))
    p.poly(rr(x - 0.38 * s, y - 0.80 * s, 0.76 * s, 1.55 * s, 0.06 * s), hexc("#3A4660"))
    _line(p, x, y, s, [(-0.20, -0.75), (0.05, -0.30), (-0.15, 0.05), (0.20, 0.45), (0.05, 0.75)], 0.05, CREAM, 0.9, k=2)
    _line(p, x, y, s, [(0.05, -0.30), (0.33, -0.15)], 0.04, CREAM, 0.8, k=2)
    _line(p, x, y, s, [(-0.15, 0.05), (-0.36, 0.25)], 0.04, CREAM, 0.8, k=2)


# --- rest, comfort, time ------------------------------------------------------------------------------------------------------
def i_bed(p, x, y, s, on, t, zzz=True):
    p.poly(rr(x - 1.0 * s, y - 0.05 * s, 2.0 * s, 0.45 * s, 0.08 * s), hexc("#5A5078"))
    p.poly(rr(x - 1.0 * s, y - 0.55 * s, 0.18 * s, 1.30 * s, 0.05 * s), BROWN)
    p.poly(rr(x - 0.80 * s, y - 0.30 * s, 0.50 * s, 0.28 * s, 0.10 * s), CREAM if on == "cream" else hexc("#D9D3E2"))
    p.poly(rr(x - 0.25 * s, y - 0.22 * s, 1.20 * s, 0.30 * s, 0.10 * s), hexc("#7A6EA0"))
    for k, (u, v, z) in enumerate(((0.35, -0.75, 0.16), (0.62, -0.98, 0.22), (0.95, -1.25, 0.28)) if zzz else ()):
        rise = 0.06 * math.sin(t * 2.0 + k)
        i_z(p, x + u * s, y + (v + rise) * s, z * s, on, t)


def i_tv(p, x, y, s, on, t):
    p.poly(rr(x - 0.95 * s, y - 0.62 * s, 1.9 * s, 1.20 * s, 0.10 * s), INK if on == "cream" else hexc("#2A2430"))
    p.poly(rr(x - 0.82 * s, y - 0.50 * s, 1.64 * s, 0.96 * s, 0.05 * s), hexc("#6A8ACF"))
    p.poly(rr(x - 0.82 * s, y - 0.50 * s, 1.64 * s, 0.30 * s, 0.05 * s), hexc("#8FB0EF"), 0.6)
    _line(p, x, y, s, [(-0.35, 0.58), (-0.45, 0.85)], 0.08, INK)
    _line(p, x, y, s, [(0.35, 0.58), (0.45, 0.85)], 0.08, INK)


def i_pizza(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-0.85, -0.70), (0.85, -0.70), (0.0, 0.95)]), hexc("#F2B54A"))
    p.poly(rr(x - 0.92 * s, y - 0.88 * s, 1.84 * s, 0.30 * s, 0.14 * s), hexc("#C27A3A"))
    for u, v in ((-0.35, -0.35), (0.30, -0.30), (0.0, 0.10), (-0.08, 0.50)):
        p.circle(x + u * s, y + v * s, 0.13 * s, RED)


def i_clock(p, x, y, s, on, t, spin=0.0):
    p.circle(x, y, 0.95 * s, INK if on == "cream" else hexc("#2A2430"))
    p.circle(x, y, 0.82 * s, CREAM)
    for k in range(12):
        a = k * math.pi / 6
        _line(p, x, y, s, [(math.cos(a) * 0.66, math.sin(a) * 0.66), (math.cos(a) * 0.76, math.sin(a) * 0.76)], 0.05,
              INK)
    hh = -math.pi / 2 + 1.1 + spin * 0.083
    mm = -math.pi / 2 + 4.2 + spin
    _line(p, x, y, s, [(0, 0), (math.cos(hh) * 0.40, math.sin(hh) * 0.40)], 0.09, INK)
    _line(p, x, y, s, [(0, 0), (math.cos(mm) * 0.62, math.sin(mm) * 0.62)], 0.06, INK)
    p.circle(x, y, 0.07 * s, RED)


def i_clock_spin(p, x, y, s, on, t):
    """A clock whose hands race round: no sense of time."""
    i_clock(p, x, y, s, on, t, spin=t * 9.0)
    for a in (-0.6, 0.6, 2.5):   # the blur of speed round it
        p.poly(tube([tuple(q) for q in S._arc(x, y, 1.12 * s, 1, a, a + 0.8, 10)], 0.06 * s, k=2),
               CORAL if on == "cream" else GOLD, 0.8)


def i_calendar(p, x, y, s, on, t, crosses=True):
    p.poly(rr(x - 0.85 * s, y - 0.75 * s, 1.7 * s, 1.7 * s, 0.10 * s), CREAM if on != "cream" else hexc("#FFFFFF"))
    p.poly(rr(x - 0.85 * s, y - 0.75 * s, 1.7 * s, 0.40 * s, 0.10 * s), RED)
    for u in (-0.45, 0.45):
        _line(p, x, y, s, [(u, -0.95), (u, -0.62)], 0.10, INK)
    for r_ in range(3):
        for c_ in range(4):
            cx, cy = x + (-0.60 + c_ * 0.40) * s, y + (-0.10 + r_ * 0.33) * s
            if crosses and (r_ * 4 + c_) < 9:
                _line(p, cx, cy, s, [(-0.13, -0.11), (0.13, 0.11)], 0.06, RED)
                _line(p, cx, cy, s, [(0.13, -0.11), (-0.13, 0.11)], 0.06, RED)
            else:
                p.circle(cx, cy, 0.05 * s, GREY)


def i_calendar_ticks(p, x, y, s, on, t):
    """A calendar of days done: every square ticked."""
    p.poly(rr(x - 0.85 * s, y - 0.75 * s, 1.7 * s, 1.7 * s, 0.10 * s), CREAM if on != "cream" else hexc("#FFFFFF"))
    p.poly(rr(x - 0.85 * s, y - 0.75 * s, 1.7 * s, 0.40 * s, 0.10 * s), TEAL)
    for r_ in range(3):
        for c_ in range(4):
            cx, cy = x + (-0.60 + c_ * 0.40) * s, y + (-0.10 + r_ * 0.33) * s
            _line(p, cx, cy, s, [(-0.12, 0.0), (-0.03, 0.10), (0.14, -0.12)], 0.06, GREEN, k=2)


def i_alarm(p, x, y, s, on, t):
    shake = 0.06 * s * math.sin(t * 50.0)
    for side in (-1, 1):
        p.circle(x + side * 0.55 * s + shake, y - 0.78 * s, 0.25 * s, GOLD)
    i_clock(p, x + shake, y + 0.05 * s, 0.85 * s, on, t)
    for side in (-1, 1):
        for k in range(2):
            a = (-2.2 if side < 0 else -0.95) + k * 0.35 * side
            _line(p, x, y, s, [(math.cos(a) * 1.05, math.sin(a) * 1.05), (math.cos(a) * 1.35, math.sin(a) * 1.35)], 0.07,
                  RED)


def i_hourglass(p, x, y, s, on, t):
    p.poly(rr(x - 0.65 * s, y - 0.98 * s, 1.30 * s, 0.18 * s, 0.05 * s), BROWN)
    p.poly(rr(x - 0.65 * s, y + 0.80 * s, 1.30 * s, 0.18 * s, 0.05 * s), BROWN)
    p.poly(_pts(x, y, s, [(-0.50, -0.80), (0.50, -0.80), (0.08, 0.0), (0.50, 0.80), (-0.50, 0.80), (-0.08, 0.0)]),
           hexc("#C9D6EA"), 0.8)
    u = (t * 0.15) % 1.0
    p.poly(_pts(x, y, s, [(-0.40 * (1 - u), -0.70 + u * 0.6), (0.40 * (1 - u), -0.70 + u * 0.6), (0.0, -0.05)]), GOLD)
    p.poly(_pts(x, y, s, [(-0.42, 0.78), (0.42, 0.78), (0.0, 0.78 - 0.6 * u - 0.05)]), GOLD)


# --- the phone -----------------------------------------------------------------------------------------------------------------
def i_phone_adult(p, x, y, s, on, t):
    """The censored phone: a pink mosaic under "18+". Nothing on it can be made out."""
    p.poly(rr(x - 0.55 * s, y - 1.0 * s, 1.10 * s, 2.0 * s, 0.18 * s), INK if on == "cream" else hexc("#2A2430"))
    screen(p, "adult", x, y, 0.42 * s, 0.85 * s, t)


def i_notifications(p, x, y, s, on, t):
    p.poly(rr(x - 0.55 * s, y - 1.0 * s, 1.10 * s, 2.0 * s, 0.18 * s), INK if on == "cream" else hexc("#2A2430"))
    screen(p, "notifications", x, y, 0.42 * s, 0.85 * s, t)


def i_likes(p, x, y, s, on, t):
    i_heart(p, x - 0.15 * s, y + 0.10 * s, 0.85 * s, on, t)
    p.circle(x + 0.62 * s, y - 0.55 * s, 0.38 * s, RED)
    for k in range(3):   # its count, too big to read
        p.circle(x + (0.48 + 0.14 * k) * s, y - 0.55 * s, 0.05 * s, CREAM)


def i_controller(p, x, y, s, on, t):
    body = [(-0.95, 0.10), (-0.70, -0.40), (0.70, -0.40), (0.95, 0.10), (0.75, 0.60), (0.40, 0.35), (-0.40, 0.35),
            (-0.75, 0.60)]
    p.poly(spline(_pts(x, y, s, body), True, 6), INK if on == "cream" else hexc("#3A3446"))
    _line(p, x, y, s, [(-0.62, -0.05), (-0.30, -0.05)], 0.10, CREAM)
    _line(p, x, y, s, [(-0.46, -0.21), (-0.46, 0.11)], 0.10, CREAM)
    for u, v, c in ((0.42, -0.15, RED), (0.62, 0.0, GREEN), (0.42, 0.12, BLUE), (0.25, 0.0, GOLD)):
        p.circle(x + u * s, y + v * s, 0.08 * s, c)


def i_chain(p, x, y, s, on, t):
    for k in range(4):
        u = -0.75 + k * 0.5
        a = 0.0 if k % 2 == 0 else math.pi / 2
        link = S.rell(x + u * s, y + (k % 2) * 0.02 * s, 0.36 * s, 0.20 * s, a * 0.0 + (0.4 if k % 2 else -0.4))
        p.poly(tube([tuple(q) for q in link] + [tuple(link[0])], 0.10 * s, k=2), GREY if on == "cream" else hexc("#B8B2C4"))


# --- work, his life ---------------------------------------------------------------------------------------------------------------
def i_briefcase(p, x, y, s, on, t):
    p.poly(rr(x - 0.30 * s, y - 0.75 * s, 0.60 * s, 0.30 * s, 0.10 * s), INK if on == "cream" else GREY)
    p.poly(rr(x - 0.95 * s, y - 0.50 * s, 1.9 * s, 1.30 * s, 0.12 * s), BROWN)
    _line(p, x, y, s, [(-0.95, -0.02), (0.95, -0.02)], 0.06, hexc("#3A2A20"))
    p.poly(rr(x - 0.12 * s, y - 0.10 * s, 0.24 * s, 0.18 * s, 0.03 * s), GOLD)


def i_bill(p, x, y, s, on, t):
    """A bill come due: a sheet of lines with a red stamp."""
    p.poly(_pts(x, y, s, [(-0.70, -0.95), (0.45, -0.95), (0.70, -0.70), (0.70, 0.95), (-0.70, 0.95)]),
           hexc("#FFFFFF") if on == "cream" else CREAM)
    for k in range(5):
        _line(p, x, y, s, [(-0.50, -0.62 + k * 0.22), (0.45 - (0.3 if k == 4 else 0.0), -0.62 + k * 0.22)], 0.05,
              GREY)
    p.poly(tube([tuple(q) for q in S.rell(x + 0.10 * s, y + 0.55 * s, 0.48 * s, 0.24 * s, -0.25)] +
                [tuple(S.rell(x + 0.10 * s, y + 0.55 * s, 0.48 * s, 0.24 * s, -0.25)[0])], 0.08 * s, k=2), RED)
    i_exclaim(p, x + 0.10 * s, y + 0.55 * s, 0.17 * s, "cream", t)


def i_hospital(p, x, y, s, on, t):
    i_bed(p, x, y + 0.25 * s, 0.85 * s, on, t, zzz=False)
    _line(p, x, y, s, [(0.90, 0.10), (0.90, -0.95)], 0.06, GREY)
    p.poly(rr(x + 0.72 * s, y - 0.95 * s, 0.36 * s, 0.40 * s, 0.08 * s), hexc("#C9E2F2"))
    beat = [(-0.95, -0.65), (-0.45, -0.65), (-0.30, -0.95), (-0.12, -0.35), (0.02, -0.65), (0.45, -0.65)]
    _line(p, x, y, s, beat, 0.06, GREEN, k=2)


def i_parents(p, x, y, s, on, t):
    """His mother and father (grown-ups only)."""
    for u, hair in ((-0.48, "bun"), (0.48, "short")):
        cx = x + u * s
        p.poly(rr(cx - 0.42 * s, y + 0.15 * s, 0.84 * s, 0.85 * s, 0.30 * s), hexc("#7E5A68") if hair == "bun" else
               hexc("#3A4A6A"))
        p.circle(cx, y - 0.30 * s, 0.38 * s, INK)
        if hair == "bun":
            p.circle(cx - 0.30 * s, y - 0.62 * s, 0.15 * s, hexc("#B9B2BC"))
        else:
            p.poly(tube([tuple(q) for q in S._arc(cx, y - 0.30 * s, 0.39 * s, -1, -0.3, -2.9, 12)], 0.12 * s, k=2),
                   hexc("#B9B2BC"))
        for d in (-0.12, 0.12):
            p.circle(cx + d * s, y - 0.32 * s, 0.05 * s, CREAM)
    i_heart(p, x, y - 0.95 * s, 0.22 * s, on, t)


def i_her(p, x, y, s, on, t):
    """Her (someone he loves or longs for): a head with long hair, a small heart by her."""
    p.poly(tube([(x + 0.10 * s, y - 0.55 * s), (x + 0.55 * s, y + 0.10 * s), (x + 0.45 * s, y + 0.85 * s)], 0.62 * s,
                0.40 * s), hexc("#4A3328"))
    p.poly(rr(x - 0.55 * s, y + 0.35 * s, 1.0 * s, 0.70 * s, 0.30 * s), hexc("#7A4A5E"))
    p.circle(x - 0.05 * s, y - 0.15 * s, 0.55 * s, INK)
    p.poly(tube([tuple(q) for q in S._arc(x - 0.05 * s, y - 0.15 * s, 0.57 * s, -1, -0.30, -3.2, 14)], 0.16 * s, k=2),
           hexc("#4A3328"))
    for d in (-0.22, 0.02):
        p.poly(ell(x + d * s, y - 0.12 * s, 0.07 * s, 0.07 * s, 12), CREAM)
    i_heart(p, x + 0.75 * s, y - 0.75 * s, 0.25 * s, on, t)


def i_him(p, x, y, s, on, t):
    """Him: his black head and white eyes, his teal hoodie's shoulders."""
    p.poly(rr(x - 0.62 * s, y + 0.25 * s, 1.24 * s, 0.75 * s, 0.32 * s), TEAL)
    p.circle(x, y - 0.25 * s, 0.58 * s, INK)
    for d in (-0.16, 0.16):
        p.poly(ell(x + d * s, y - 0.25 * s, 0.08 * s, 0.09 * s, 12), CREAM)


def i_rival(p, x, y, s, on, t):
    """Another man doing better: him in a suit, smug, with his new car."""
    i_car(p, x + 0.25 * s, y + 0.45 * s, 0.70 * s, on, t)
    p.poly(rr(x - 0.95 * s, y - 0.10 * s, 0.70 * s, 0.75 * s, 0.25 * s), hexc("#2E3A5A"))
    p.circle(x - 0.60 * s, y - 0.52 * s, 0.40 * s, INK)
    for d in (-0.70, -0.50):   # smug: half-lidded
        p.poly(np.array([(x + d * s - 0.07 * s, y - 0.54 * s), (x + d * s + 0.07 * s, y - 0.54 * s),
                         (x + d * s, y - 0.48 * s)]), CREAM)
    for a in (-0.4, 0.3):
        i_sparkle(p, x + (0.6 + a) * s, y - (0.55 + a * 0.3) * s, 0.18 * s, "dark" if on != "cream" else "cream", t)


def i_mirror(p, x, y, s, on, t):
    p.poly(ell(x, y, 0.70 * s, 0.98 * s, 40), BROWN)
    p.poly(ell(x, y, 0.58 * s, 0.86 * s, 40), hexc("#9FB2CC"))
    p.circle(x, y + 0.05 * s, 0.30 * s, INK)
    p.poly(rr(x - 0.40 * s, y + 0.35 * s, 0.80 * s, 0.40 * s, 0.18 * s), TEAL)
    for d in (-0.09, 0.09):
        p.circle(x + d * s, y + 0.05 * s, 0.04 * s, CREAM)


# --- change, the good life ----------------------------------------------------------------------------------------------------
def i_mountain(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-1.0, 0.85), (-0.15, -0.55), (0.25, -0.05), (0.50, -0.30), (1.0, 0.85)]), hexc("#6A5A80"))
    p.poly(_pts(x, y, s, [(-0.36, -0.22), (-0.15, -0.55), (0.05, -0.27), (-0.08, -0.18)]), CREAM)
    _line(p, x, y, s, [(-0.15, -0.55), (-0.15, -1.0)], 0.05, INK)
    flap = 0.05 * math.sin(t * 4.0)
    p.poly(_pts(x, y, s, [(-0.15, -1.0), (0.32, -0.88 + flap), (-0.15, -0.74)]), CORAL)


def i_sunrise(p, x, y, s, on, t):
    for k in range(7):
        a = math.pi + (k + 0.5) * math.pi / 7
        _line(p, x, y + 0.35 * s, s, [(math.cos(a) * 0.72, math.sin(a) * 0.72), (math.cos(a) * 1.0, math.sin(a) * 1.0)],
              0.09, GOLD)
    sun = S._arc(x, y + 0.35 * s, 0.58 * s, 1, math.pi, 2 * math.pi, 24)
    p.poly(sun, hexc("#FFB65A"))
    p.poly(rr(x - 1.0 * s, y + 0.32 * s, 2.0 * s, 0.10 * s, 0.03 * s), CORAL)
    _line(p, x, y, s, [(-0.70, 0.62), (0.70, 0.62)], 0.06, CORAL, 0.6)


def i_dumbbell(p, x, y, s, on, t):
    _line(p, x, y, s, [(-0.75, 0.0), (0.75, 0.0)], 0.14, GREY)
    for side in (-1, 1):
        p.poly(rr(x + side * 0.62 * s - 0.15 * s, y - 0.45 * s, 0.30 * s, 0.90 * s, 0.06 * s),
               INK if on == "cream" else hexc("#3A3446"))
        p.poly(rr(x + side * 0.90 * s - 0.10 * s, y - 0.30 * s, 0.20 * s, 0.60 * s, 0.05 * s),
               INK if on == "cream" else hexc("#3A3446"))


def i_checklist(p, x, y, s, on, t):
    p.poly(rr(x - 0.75 * s, y - 0.95 * s, 1.5 * s, 1.9 * s, 0.10 * s), hexc("#FFFFFF") if on == "cream" else CREAM)
    p.poly(rr(x - 0.30 * s, y - 1.05 * s, 0.60 * s, 0.22 * s, 0.05 * s), BROWN)
    for k in range(3):
        cy = y + (-0.45 + k * 0.48) * s
        _line(p, x - 0.42 * s, cy, s, [(-0.13, 0.0), (-0.03, 0.12), (0.16, -0.14)], 0.07, GREEN, k=2)
        _line(p, x, cy, s, [(-0.10, 0.0), (0.55, 0.0)], 0.06, GREY)


def i_plant(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-0.50, 0.30), (0.50, 0.30), (0.38, 0.95), (-0.38, 0.95)]), hexc("#B8664A"))
    _line(p, x, y, s, [(0.0, 0.30), (0.0, -0.45)], 0.08, GREEN)
    for side, v in ((-1, -0.10), (1, -0.40), (-1, -0.65)):
        leaf = S.rell(x + side * 0.30 * s, y + v * s, 0.32 * s, 0.14 * s, -side * 0.5)
        p.poly(leaf, GREEN)


def i_lightbulb(p, x, y, s, on, t):
    p.circle(x, y - 0.20 * s, 0.58 * s, hexc("#FFE27A"))
    p.poly(rr(x - 0.26 * s, y + 0.30 * s, 0.52 * s, 0.42 * s, 0.06 * s), GREY)
    for k in range(5):
        a = math.pi + 0.35 + k * (math.pi - 0.7) / 4
        _line(p, x, y - 0.20 * s, s, [(math.cos(a) * 0.78, math.sin(a) * 0.78), (math.cos(a) * 1.0, math.sin(a) * 1.0)],
              0.08, GOLD)


def i_book(p, x, y, s, on, t):
    for side in (-1, 1):
        page = [(0.0, -0.55), (side * 0.95, -0.70), (side * 0.95, 0.60), (0.0, 0.75)]
        p.poly(_pts(x, y, s, page), hexc("#FFFFFF") if on == "cream" else CREAM)
        for k in range(4):
            _line(p, x, y, s, [(side * 0.15, -0.40 + k * 0.28), (side * 0.80, -0.50 + k * 0.28)], 0.04, GREY)
    _line(p, x, y, s, [(0.0, -0.55), (0.0, 0.75)], 0.05, BROWN)


def i_door(p, x, y, s, on, t):
    p.poly(rr(x - 0.55 * s, y - 1.0 * s, 1.1 * s, 2.0 * s, 0.05 * s), BROWN)
    p.poly(rr(x - 0.42 * s, y - 0.85 * s, 0.84 * s, 0.70 * s, 0.03 * s), hexc("#5A3A2E"))
    p.poly(rr(x - 0.42 * s, y + 0.05 * s, 0.84 * s, 0.75 * s, 0.03 * s), hexc("#5A3A2E"))
    p.circle(x + 0.32 * s, y + 0.0 * s, 0.07 * s, GOLD)


def i_road(p, x, y, s, on, t):
    p.poly(_pts(x, y, s, [(-1.0, 0.95), (-0.12, -0.75), (0.12, -0.75), (1.0, 0.95)]), hexc("#4A4458"))
    for k in range(4):
        v0 = -0.55 + k * 0.38
        _line(p, x, y, s, [(0.0, v0), (0.0, v0 + 0.18 + k * 0.03)], 0.04 + 0.025 * k, GOLD)
    i_sunrise(p, x, y - 0.95 * s, 0.35 * s, on, t)


def i_tick(p, x, y, s, on, t):
    _line(p, x, y, s, [(-0.75, 0.0), (-0.20, 0.60), (0.80, -0.65)], 0.24, GREEN, k=2)


def i_cross(p, x, y, s, on, t):
    _line(p, x, y, s, [(-0.70, -0.70), (0.70, 0.70)], 0.24, RED, k=2)
    _line(p, x, y, s, [(0.70, -0.70), (-0.70, 0.70)], 0.24, RED, k=2)


def i_eye(p, x, y, s, on, t, color=None):
    p.poly(np.array([(x - 1.0 * s, y)] + [(x + math.cos(a) * s, y - math.sin(a) * 0.55 * s)
                                          for a in np.linspace(math.pi, 0, 16)] +
                    [(x + math.cos(a) * s, y + math.sin(a) * 0.55 * s) for a in np.linspace(0, math.pi, 16)]),
           hexc("#FFFFFF") if on == "cream" else CREAM)
    p.circle(x, y, 0.42 * s, color if color is not None else TEAL)
    p.circle(x, y, 0.20 * s, INK)


def i_green_eye(p, x, y, s, on, t):
    """Envy: a narrowed green eye."""
    i_eye(p, x, y, s, on, t, color=GREEN)
    p.poly(np.array([(x - 1.05 * s, y - 0.62 * s), (x + 1.05 * s, y - 0.62 * s), (x + 1.05 * s, y - 0.18 * s),
                     (x - 1.05 * s, y - 0.02 * s)]), INK if on == "cream" else hexc("#2A2430"))


def i_bottle(p, x, y, s, on, t):
    p.poly(rr(x - 0.12 * s, y - 1.0 * s, 0.24 * s, 0.45 * s, 0.05 * s), hexc("#2E5A3A"))
    p.poly(rr(x - 0.38 * s, y - 0.55 * s, 0.76 * s, 1.50 * s, 0.18 * s), hexc("#2E5A3A"))
    p.poly(rr(x - 0.30 * s, y - 0.10 * s, 0.60 * s, 0.50 * s, 0.05 * s), hexc("#E8D8B0"))


def i_coffee(p, x, y, s, on, t):
    cup = TEAL if on == "cream" else CREAM
    p.poly(rr(x - 0.55 * s, y - 0.25 * s, 1.0 * s, 1.0 * s, 0.12 * s), cup)
    p.poly(tube([(x + 0.45 * s, y - 0.05 * s), (x + 0.80 * s, y + 0.20 * s), (x + 0.45 * s, y + 0.50 * s)], 0.12 * s,
                k=6), cup)
    for k in range(2):
        u = (t * 0.7 + k * 0.5) % 1.0
        _line(p, x, y, s, [(-0.20 + 0.3 * k, -0.40 - u * 0.4), (-0.10 + 0.3 * k, -0.60 - u * 0.4),
                           (-0.20 + 0.3 * k, -0.80 - u * 0.4)], 0.06, GREY, 1 - u, k=4)


def i_diploma(p, x, y, s, on, t):
    """A certificate: a sheet of lines with a red seal and its ribbons."""
    p.poly(rr(x - 0.95 * s, y - 0.72 * s, 1.9 * s, 1.40 * s, 0.06 * s), hexc("#FFFFFF") if on == "cream" else CREAM)
    p.poly(rr(x - 0.82 * s, y - 0.60 * s, 1.64 * s, 1.16 * s, 0.04 * s), GOLD, 0.25)
    for k in range(3):
        _line(p, x, y, s, [(-0.60, -0.35 + k * 0.25), (0.40 - 0.25 * (k == 2), -0.35 + k * 0.25)], 0.06, GREY)
    for side in (-1, 1):
        p.poly(_pts(x, y, s, [(0.45 + side * 0.06, 0.40), (0.45 + side * 0.24, 0.98), (0.45 + side * 0.10, 0.88),
                             (0.45, 0.98)]), RED)
    p.circle(x + 0.45 * s, y + 0.38 * s, 0.26 * s, RED)
    p.poly(_star_shape(x + 0.45 * s, y + 0.38 * s, 0.15 * s, 8, 0.6), GOLD)


def i_shadow(p, x, y, s, on, t):
    """Fear: a dark shape with white eyes, reaching."""
    sway = 0.06 * math.sin(t * 1.5)
    body = [(-0.85, 1.0), (-0.75, -0.15), (-0.45, -0.75), (0.0, -0.95), (0.45, -0.75), (0.75, -0.15), (0.85, 1.0)]
    p.poly(spline(_pts(x + sway * s, y, s, body), True, 8), hexc("#1E1828") if on == "cream" else hexc("#000000"), 0.95)
    for d in (-0.25, 0.25):
        p.poly(S.rell(x + (d + sway) * s, y - 0.40 * s, 0.13 * s, 0.07 * s, -d), RED if on != "cream" else CREAM)
    for side in (-1, 1):
        p.poly(tube([(x + side * 0.70 * s, y + 0.10 * s), (x + side * 1.0 * s, y - 0.10 * s),
                     (x + side * 1.10 * s, y - 0.35 * s)], 0.14 * s, 0.05 * s), hexc("#1E1828"))


def i_laughing(p, x, y, s, on, t):
    """People laughing at him (his fear of being judged): three heads, eyes shut in laughter."""
    for k, u in enumerate((-0.62, 0.0, 0.62)):
        bob = 0.05 * math.sin(t * 10.0 + k)
        cx, cy = x + u * s, y + (bob - 0.05) * s
        p.circle(cx, cy, 0.36 * s, INK)
        for d in (-0.12, 0.12):
            arc = S._arc(cx + d * s, cy - 0.02 * s, 0.07 * s, 1, math.pi, 2 * math.pi, 8)
            p.poly(tube([tuple(q) for q in arc], 0.035 * s, k=2), CREAM)
        _line(p, cx, cy, s, [(0.42, -0.42), (0.56, -0.58)], 0.05, CORAL)


def i_target(p, x, y, s, on, t):
    for r_, c in ((0.95, RED), (0.70, CREAM if on != "cream" else hexc("#FFFFFF")), (0.45, RED), (0.20,
                  CREAM if on != "cream" else hexc("#FFFFFF"))):
        p.circle(x, y, r_ * s, c)
    _line(p, x, y, s, [(0.0, 0.0), (0.85, -0.85)], 0.07, INK)
    p.poly(_pts(x, y, s, [(0.85, -0.85), (1.0, -0.62), (0.62, -1.0)]), GOLD)


def i_shield(p, x, y, s, on, t):
    p.poly(spline(_pts(x, y, s, [(-0.80, -0.75), (0.0, -0.95), (0.80, -0.75), (0.70, 0.20), (0.0, 0.95),
                                 (-0.70, 0.20)]), True, 6), TEAL)
    _line(p, x, y, s, [(-0.35, 0.0), (-0.08, 0.30), (0.40, -0.30)], 0.12, CREAM, k=2)


def i_handshake(p, x, y, s, on, t):
    p.poly(tube([(x - 1.0 * s, y + 0.25 * s), (x - 0.20 * s, y + 0.05 * s)], 0.40 * s), TEAL)
    p.poly(tube([(x + 1.0 * s, y + 0.25 * s), (x + 0.20 * s, y + 0.05 * s)], 0.40 * s), hexc("#2E3A5A"))
    p.poly(rr(x - 0.40 * s, y - 0.22 * s, 0.80 * s, 0.50 * s, 0.22 * s), INK if on == "cream" else hexc("#2A2430"))


# --- the phone's new screens as pictures, and the new life's things ------------------------------------------------------------
def _phone_icon(p, x, y, s, on, kind, t, buzz=False):
    """His phone face-on showing `kind` (a screen), buzzing at its sides when it rings."""
    if buzz:
        for side in (-1, 1):
            for k in range(2):
                _line(p, x + side * (0.78 + 0.16 * k) * s, y, s, [(0.0, -0.30 + 0.05 * k), (0.0, 0.30 - 0.05 * k)], 0.06,
                      _ink(on), 0.8)
    p.poly(rr(x - 0.55 * s, y - 1.0 * s, 1.10 * s, 2.0 * s, 0.18 * s), INK if on == "cream" else hexc("#2A2430"))
    screen(p, kind, x, y, 0.42 * s, 0.85 * s, t)


def i_call(p, x, y, s, on, t):
    _phone_icon(p, x, y, s, on, "call", t, buzz=True)


def i_missed_calls(p, x, y, s, on, t):
    _phone_icon(p, x, y, s, on, "missed", t)


def i_phone_alarm(p, x, y, s, on, t):
    _phone_icon(p, x, y, s, on, "alarm", t, buzz=True)


def i_feed(p, x, y, s, on, t):
    _phone_icon(p, x, y, s, on, "feed", t)


def i_texts(p, x, y, s, on, t):
    _phone_icon(p, x, y, s, on, "texts", t)


def i_watch(p, x, y, s, on, t):
    """A gold wristwatch face-on: its strap, the case, the hour marks and hands, a glint."""
    p.poly(rr(x - 0.30 * s, y - 1.0 * s, 0.60 * s, 2.0 * s, 0.12 * s), hexc("#3A2E2A"))
    p.circle(x, y, 0.64 * s, GOLD)
    p.circle(x, y, 0.52 * s, hexc("#141018"))
    for k in range(12):
        a = k * math.tau / 12
        p.circle(x + math.cos(a) * 0.43 * s, y + math.sin(a) * 0.43 * s, (0.05 if k % 3 == 0 else 0.03) * s, GOLD)
    _line(p, x, y, s, [(0.0, 0.0), (0.0, -0.34)], 0.07, GOLD)
    _line(p, x, y, s, [(0.0, 0.0), (0.24, 0.10)], 0.07, GOLD)
    p.circle(x + 0.68 * s, y, 0.09 * s, GOLD)
    i_sparkle(p, x + 0.48 * s, y - 0.52 * s, 0.32 * s, "dark", t)


def i_sports_car(p, x, y, s, on, t):
    """A sleek red sports car: low, a long bonnet, gold rims, its headlight lit, a shine along its side."""
    body = [(-1.0, 0.30), (-0.98, 0.04), (-0.72, -0.06), (-0.34, -0.40), (0.14, -0.42), (0.52, -0.12), (1.0, 0.0),
            (1.03, 0.30)]
    p.poly(spline(_pts(x, y, s, body), True, 4), RED)
    p.poly(_pts(x, y, s, [(-0.30, -0.33), (0.10, -0.35), (0.40, -0.12), (-0.55, -0.10)]), hexc("#1A1824"))
    _line(p, x, y, s, [(-0.80, 0.02), (0.80, 0.04)], 0.035, hexc("#FFB0A0"), 0.8)
    for u in (-0.62, 0.64):
        p.circle(x + u * s, y + 0.32 * s, 0.25 * s, INK)
        p.circle(x + u * s, y + 0.32 * s, 0.14 * s, GOLD)
        p.circle(x + u * s, y + 0.32 * s, 0.05 * s, INK)
    p.poly(_pts(x, y, s, [(0.84, 0.02), (1.0, 0.05), (0.99, 0.12), (0.83, 0.09)]), hexc("#FFF4D8"))
    i_sparkle(p, x + 0.10 * s, y - 0.62 * s, 0.22 * s, "dark", t)


def i_flex(p, x, y, s, on, t):
    """A flexed arm: the biceps bulging, the fist up, his teal sleeve; strength lines round it."""
    ink = INK if on == "cream" else hexc("#2A2430")
    p.poly(tube([(x - 0.95 * s, y + 0.45 * s), (x + 0.15 * s, y + 0.42 * s)], 0.62 * s, 0.52 * s), ink)
    p.poly(ell(x - 0.38 * s, y + 0.16 * s, 0.44 * s, 0.34 * s, 32), ink)
    p.poly(tube([(x + 0.15 * s, y + 0.42 * s), (x + 0.30 * s, y - 0.50 * s)], 0.50 * s, 0.42 * s), ink)
    p.circle(x + 0.32 * s, y - 0.70 * s, 0.27 * s, ink)
    p.poly(tube([(x - 1.0 * s, y + 0.45 * s), (x - 0.66 * s, y + 0.44 * s)], 0.74 * s), TEAL)
    for k in range(3):
        a = -2.3 + k * 0.45
        _line(p, x - 0.38 * s, y + 0.16 * s, s, [(math.cos(a) * 0.62, math.sin(a) * 0.62),
                                                 (math.cos(a) * 0.86, math.sin(a) * 0.86)], 0.07, GOLD)


def i_safe(p, x, y, s, on, t):
    """A heavy safe standing open: gold bars and money inside, its door swung out with the dial."""
    p.poly(rr(x - 0.85 * s, y - 0.85 * s, 1.60 * s, 1.75 * s, 0.10 * s), hexc("#4A4E5A"))
    p.poly(rr(x - 0.70 * s, y - 0.70 * s, 1.30 * s, 1.45 * s, 0.05 * s), hexc("#1A1820"))
    p.poly(rr(x - 0.70 * s, y - 0.02 * s, 1.30 * s, 0.06 * s, 0.02 * s), hexc("#2E3240"))
    for k in range(3):
        u = -0.55 + 0.38 * k
        p.poly(_pts(x, y, s, [(u, 0.66), (u + 0.32, 0.66), (u + 0.26, 0.42), (u + 0.06, 0.42)]), GOLD)
    for k in range(2):
        p.poly(rr(x + (-0.58 + 0.62 * k) * s, y - 0.34 * s, 0.52 * s, 0.30 * s, 0.03 * s), hexc("#3E8F64"))
        p.poly(rr(x + (-0.36 + 0.62 * k) * s, y - 0.34 * s, 0.08 * s, 0.30 * s, 0.01 * s), hexc("#E8D8A8"))
    p.poly(_pts(x, y, s, [(0.75, -0.85), (1.05, -0.72), (1.05, 0.78), (0.75, 0.90)]), hexc("#5A5E6A"))
    p.circle(x + 0.90 * s, y, 0.13 * s, GREY)
    p.circle(x + 0.90 * s, y, 0.05 * s, INK)


def i_skyline(p, x, y, s, on, t):
    """A city's towers at night against a deep sky, their windows lit, a moon."""
    p.poly(rr(x - s, y - s, 2 * s, 2 * s, 0.12 * s), hexc("#16163A"))
    p.circle(x + 0.55 * s, y - 0.55 * s, 0.16 * s, CREAM)
    for k, (u, w, h) in enumerate(((-0.92, 0.30, 0.95), (-0.58, 0.26, 1.40), (-0.28, 0.34, 1.10), (0.10, 0.24, 1.65),
                                   (0.38, 0.30, 1.20), (0.70, 0.28, 0.80))):
        p.poly(rect(x + u * s, y + (1.0 - h) * s, w * s, h * s), hexc("#0A0A16"))
        for j in range(int(h * 5)):
            for i in range(2):
                if (j * 3 + i + k) % 4:
                    p.poly(rect(x + (u + 0.06 + 0.11 * i) * s, y + (1.0 - h + 0.10 + 0.18 * j) * s, 0.05 * s, 0.07 * s),
                           GOLD, 0.85)


ICONS = {  # name: (draw, what it shows: the storyboard's words for a picture)
    "heart": (i_heart, "a heart: love, desire"),
    "broken_heart": (i_broken_heart, "a broken heart: a love lost"),
    "lips": (i_lips, "red lips: a kiss, desire"),
    "phone_adult": (i_phone_adult, "his phone's censored screen, a pink mosaic under 18+: what he watches in secret"),
    "notifications": (i_notifications, "a phone full of notifications"),
    "likes": (i_likes, "a heart with a counter: likes, being seen online"),
    "her": (i_her, "her: a woman he loves, misses or wants"),
    "him": (i_him, "himself"),
    "parents": (i_parents, "his mother and father"),
    "rival": (i_rival, "another man doing better: smug, with a new car"),
    "money": (i_money, "banknotes"),
    "moneybag": (i_moneybag, "a bag of money"),
    "dollar": (i_dollar, "a dollar sign"),
    "wallet_empty": (i_wallet_empty, "an empty wallet, moths flying out"),
    "crown": (i_crown, "a crown: being the best, pride"),
    "trophy": (i_trophy, "a trophy: winning"),
    "car": (i_car, "a car"),
    "house": (i_house, "a house: home"),
    "ring": (i_ring, "a ring: marriage, a promise"),
    "fist": (i_fist, "a clenched fist: anger, a fight"),
    "bomb": (i_bomb, "a bomb with a lit fuse: about to explode"),
    "volcano": (i_volcano, "an erupting volcano: rage"),
    "grawlix": (i_grawlix, "#@%!: swearing, shouting"),
    "bolt": (i_bolt, "a lightning bolt: shock, a sudden idea, rage"),
    "broken_phone": (i_broken_phone, "a cracked phone"),
    "bed": (i_bed, "a bed with Zzz: sleep, laziness"),
    "tv": (i_tv, "a TV: comfort, hours wasted"),
    "pizza": (i_pizza, "a slice of pizza: junk food"),
    "controller": (i_controller, "a game controller: games instead of work"),
    "clock": (i_clock, "a clock: time"),
    "clock_spin": (i_clock_spin, "a clock racing round: time slipping away"),
    "hourglass": (i_hourglass, "an hourglass: time running out, patience"),
    "calendar": (i_calendar, "a calendar of crossed-out days: days wasted, a deadline"),
    "calendar_ticks": (i_calendar_ticks, "a calendar of ticked days: days kept, discipline"),
    "alarm": (i_alarm, "a ringing alarm clock"),
    "chain": (i_chain, "a chain: being trapped, addiction"),
    "briefcase": (i_briefcase, "a briefcase: his job, work"),
    "bill": (i_bill, "a bill come due: rent, debt"),
    "hospital": (i_hospital, "a hospital bed: illness, someone he loves in hospital"),
    "mirror": (i_mirror, "a mirror with him in it: facing himself"),
    "mountain": (i_mountain, "a mountain with a flag on top: a goal, the climb"),
    "sunrise": (i_sunrise, "the sun rising: a new start"),
    "road": (i_road, "a road to the horizon: the way ahead"),
    "dumbbell": (i_dumbbell, "a dumbbell: training, strength"),
    "checklist": (i_checklist, "a ticked checklist: getting it done"),
    "plant": (i_plant, "a growing plant: slow growth, patience"),
    "lightbulb": (i_lightbulb, "a light bulb: an idea, understanding"),
    "book": (i_book, "an open book: learning"),
    "diploma": (i_diploma, "a diploma: a qualification earned"),
    "door": (i_door, "a door: leaving, a way out, a new chance"),
    "tick": (i_tick, "a tick: yes, done"),
    "cross": (i_cross, "a cross: no, wrong, failed"),
    "question": (i_question, "a question mark: confusion, not knowing"),
    "exclaim": (i_exclaim, "an exclamation mark: surprise, alarm"),
    "eye": (i_eye, "an eye: watching, being watched"),
    "green_eye": (i_green_eye, "a narrowed green eye: envy"),
    "bottle": (i_bottle, "a bottle: drinking"),
    "coffee": (i_coffee, "a cup of coffee: a morning, a pause"),
    "shadow": (i_shadow, "a dark shape with red eyes: fear"),
    "laughing": (i_laughing, "people laughing: being judged, mocked"),
    "target": (i_target, "a target hit: focus, a goal reached"),
    "shield": (i_shield, "a shield: courage, protection"),
    "star": (i_star, "a star: success, fame"),
    "drop": (i_drop, "a drop: a tear, sweat"),
    "puff": (i_puff, "a puff of smoke"),
    "cloud_rain": (i_cloud_rain, "a rain cloud: sadness"),
    "call": (i_call, W.PICTURES["call"]), "missed_calls": (i_missed_calls, W.PICTURES["missed_calls"]),
    "phone_alarm": (i_phone_alarm, W.PICTURES["phone_alarm"]), "feed": (i_feed, W.PICTURES["feed"]),
    "texts": (i_texts, W.PICTURES["texts"]), "watch": (i_watch, W.PICTURES["watch"]),
    "sports_car": (i_sports_car, W.PICTURES["sports_car"]), "flex": (i_flex, W.PICTURES["flex"]),
    "safe": (i_safe, W.PICTURES["safe"]), "skyline": (i_skyline, W.PICTURES["skyline"]),
    # (marks only: too small to be a bubble's picture)
    "z": (i_z, ""), "sparkle": (i_sparkle, ""), "vein": (i_vein, ""), "fly": (i_fly, ""), "dot": (i_dot, ""),
}
PICTURES = W.PICTURES   # what a bubble can show (the words live in tools/silhouette_words.py)


def draw(p, name: str, x: float, y: float, s: float, on: str = "cream", t: float = 0.0) -> None:
    """The icon `name` centred at (x, y), s world units from its middle to its top."""
    ICONS[name][0](p, x, y, s, on, t)


# --- a phone's screen seen face-on ---------------------------------------------------------------------------------------------
SCREENS = W.SCREENS   # what each shows (the words live in tools/silhouette_words.py)
SCREEN_LIGHT = {"adult": "#FF5A9A", "notifications": "#9FC8FF", "likes": "#FF7A9A", "messages": "#9FC8FF",
                "bank": "#FF6A5A", "rival": "#FFD27A", "game": "#8AF0B0", "chart_up": "#8AF0B0",
                "call": "#8FD8A8", "missed": "#FF6A5A", "alarm": "#FFB07A", "feed": "#FF8AB8", "texts": "#9FC8FF",
                "video": "#9FC8FF"}   # the light each casts


FEED = (("#FF4F7E", "#FFE0EA"), ("#2E9A8A", "#E8FFF4"), ("#5A6AFF", "#FFD27A"), ("#F5A142", "#3A1E10"),
        ("#9A4AE8", "#F4E8FF"))   # the feed's videos: (background, who's in it)
SEG = {"a": ((0, 0), (1, 0)), "b": ((1, 0), (1, 1)), "c": ((1, 1), (1, 2)), "d": ((0, 2), (1, 2)), "e": ((0, 1), (0, 2)),
       "f": ((0, 0), (0, 1)), "g": ((0, 1), (1, 1))}
DIGIT_SEGS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc",
              "8": "abcdefg", "9": "abcdfg"}


def _digits(p, text, x, y, h, color):
    """A clock's digits (seven segments each) centred at (x, y), h tall: an alarm's time."""
    w, gap = 0.5 * h, 0.22 * h
    widths = [0.25 * h if ch == ":" else w for ch in text]
    cx = x - (sum(widths) + gap * (len(text) - 1)) / 2
    for ch, cw in zip(text, widths):
        if ch == ":":
            for v in (0.32, 0.68):
                p.circle(cx + cw / 2, y - h / 2 + v * h, 0.07 * h, color)
        for seg in DIGIT_SEGS.get(ch, ""):
            (u0, v0), (u1, v1) = SEG[seg]
            p.poly(tube([(cx + u0 * cw, y - h / 2 + v0 * h / 2), (cx + u1 * cw, y - h / 2 + v1 * h / 2)], 0.12 * h, k=2),
                   color)
        cx += cw + gap


def _handset(p, x, y, s, color, down=False):
    """A phone's handset, a call's sign (down: hung up)."""
    k = -1 if down else 1
    pts = [(x - s, y + k * 0.35 * s), (x - 0.5 * s, y - k * 0.30 * s), (x + 0.5 * s, y - k * 0.30 * s),
           (x + s, y + k * 0.35 * s)]
    p.poly(tube(pts, 0.34 * s, k=4), color)
    for u in (-1, 1):
        p.circle(x + u * s, y + k * 0.35 * s, 0.30 * s, color)


def screen(p, kind: str, x: float, y: float, hw: float, hh: float, t: float = 0.0) -> None:
    """A phone's screen (half its width hw, half its height hh, world units) centred at (x, y), showing `kind`."""
    if kind == "adult":   # a censored mosaic: rose and pink squares, no shape in them; a white 18+ over it
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#E83E7C"))
        n = 5
        cell = 2 * hw / n
        r = np.random.default_rng(int(t * 2) % 3 + 11)
        for i in range(n):
            for j in range(int(2 * hh / cell)):
                c = ("#FF7AA8", "#F25C92", "#FFA0C0", "#D9387A", "#FF8FB0")[int(r.integers(5))]
                p.poly(rr(x - hw + i * cell + 0.6, y - hh + j * cell + 0.6, cell - 1.2, cell - 1.2, 0.5), hexc(c), 0.9)
        p.circle(x, y, 0.62 * hw, hexc("#FFFFFF"))
        k = 0.36 * hw
        _line(p, x - 0.30 * k * 2.2, y, k, [(0.0, -0.6), (0.0, 0.6)], 0.22, RED, k=2)   # 1
        for v in (-0.30, 0.30):   # 8
            p.poly(tube([tuple(q) for q in ell(x - 0.05 * hw, y + v * k, 0.20 * k * 1.3, 0.28 * k, 16)] +
                        [tuple(ell(x - 0.05 * hw, y + v * k, 0.20 * k * 1.3, 0.28 * k, 16)[0])], 0.12 * k, k=2), RED)
        _line(p, x + 0.38 * hw, y, k, [(-0.35, 0.0), (0.35, 0.0)], 0.22, RED, k=2)   # +
        _line(p, x + 0.38 * hw, y, k, [(0.0, -0.35), (0.0, 0.35)], 0.22, RED, k=2)
        return
    if kind == "notifications":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#1E2A40"))
        for k in range(5):
            u = (t * 0.8 + k * 0.2) % 1.0
            cy = y - hh + 0.25 * hh + k * 0.36 * hh
            p.poly(rr(x - 0.85 * hw, cy, 1.70 * hw, 0.28 * hh, 0.06 * hw), hexc("#E8EEF8"), 0.92)
            p.circle(x - 0.62 * hw, cy + 0.14 * hh, 0.12 * hw, RED)
            _line(p, x, cy + 0.10 * hh, hw, [(-0.35, 0.0), (0.60 - 0.2 * (k % 2), 0.0)], 0.05, GREY)
        return
    if kind == "likes":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#2A1E30"))
        pulse = 1.0 + 0.08 * math.sin(t * 6.0)
        i_heart(p, x, y - 0.10 * hh, 0.55 * hw * pulse, "dark", t)
        p.circle(x + 0.45 * hw, y - 0.45 * hh, 0.25 * hw, RED)
        return
    if kind == "messages":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#1E2433"))
        for k in range(4):
            side = -1 if k % 2 == 0 else 1
            cy = y - hh + 0.30 * hh + k * 0.42 * hh
            p.poly(rr(x + (side * 0.1 - 0.75) * hw + (0.25 * hw if side > 0 else 0.0), cy, 1.20 * hw, 0.26 * hh,
                      0.10 * hw), TEAL if side > 0 else hexc("#4A4A5E"))
        return
    if kind == "bank":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#1A1A24"))
        pts = [(x - 0.80 * hw, y - 0.55 * hh), (x - 0.35 * hw, y - 0.30 * hh), (x - 0.05 * hw, y - 0.42 * hh),
               (x + 0.30 * hw, y + 0.10 * hh), (x + 0.75 * hw, y + 0.55 * hh)]
        p.poly(tube(pts, 0.12 * hw, k=2), RED)
        p.poly(np.array([(x + 0.85 * hw, y + 0.70 * hh), (x + 0.45 * hw, y + 0.62 * hh), (x + 0.78 * hw, y + 0.32 * hh)]),
               RED)
        _line(p, x - 0.45 * hw, y + 0.72 * hh, hw, [(-0.35, 0.0), (0.0, 0.0)], 0.16, RED, k=2)   # a minus
        return
    if kind == "rival":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#F4E6D0"))
        i_rival(p, x, y + 0.05 * hh, 0.80 * hw, "cream", t)
        i_heart(p, x - 0.62 * hw, y + 0.78 * hh, 0.16 * hw, "cream", t)
        return
    if kind == "game":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#1A1430"))
        for k in range(6):
            u = (t * 1.5 + k * 0.17) % 1.0
            p.poly(_star_shape(x + (-0.6 + 0.24 * k) * hw, y - hh + u * 2 * hh, 0.18 * hw, 4, 0.4),
                   (GOLD, GREEN, BLUE, HEART)[k % 4])
        return
    if kind == "chart_up":
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#14241C"))
        pts = [(x - 0.80 * hw, y + 0.55 * hh), (x - 0.35 * hw, y + 0.20 * hh), (x, y + 0.30 * hh), (x + 0.35 * hw,
               y - 0.15 * hh), (x + 0.75 * hw, y - 0.60 * hh)]
        p.poly(tube(pts, 0.12 * hw, k=2), GREEN)
        return
    if kind == "call":   # an incoming call: the caller's photo in rings, a name, decline and answer (it bobs)
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#16202E"))
        cy = y - 0.30 * hh
        for k in range(3):
            u = (t * 0.9 + k / 3) % 1.0
            p.circle(x, cy, (0.42 + 0.50 * u) * hw, hexc("#8FB8FF"), 0.30 * (1 - u))
        p.circle(x, cy, 0.42 * hw, hexc("#3D5A80"))
        p.circle(x, cy - 0.10 * hw, 0.16 * hw, CREAM)
        p.poly(ell(x, cy + 0.26 * hw, 0.27 * hw, 0.13 * hw, 24), CREAM)
        p.poly(rr(x - 0.55 * hw, cy + 0.62 * hw, 1.10 * hw, 0.13 * hw, 0.06 * hw), hexc("#E8EEF8"), 0.9)
        bob = 0.05 * hh * abs(math.sin(t * 7.0))
        for side, col in ((-1, RED), (1, GREEN)):
            bx, by = x + side * 0.50 * hw, y + 0.62 * hh - (bob if side > 0 else 0.0)
            p.circle(bx, by, 0.27 * hw, col)
            _handset(p, bx, by, 0.15 * hw, CREAM, down=side < 0)
        return
    if kind == "missed":   # missed calls stacking up: red handsets, names, a red count
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#1E1A24"))
        for k in range(3 + int(t * 0.8) % 3):
            cy = y - hh + 0.42 * hh + k * 0.34 * hh
            p.poly(rr(x - 0.88 * hw, cy - 0.12 * hh, 1.76 * hw, 0.25 * hh, 0.06 * hw), hexc("#2C2632"))
            _handset(p, x - 0.62 * hw, cy, 0.13 * hw, RED, down=True)
            _line(p, x, cy, hw, [(-0.35, 0.0), (0.45 - 0.15 * (k % 2), 0.0)], 0.06, hexc("#E8A0A0"))
        p.circle(x + 0.70 * hw, y - hh + 0.14 * hh, 0.22 * hw, RED)
        i_exclaim(p, x + 0.70 * hw, y - hh + 0.14 * hh, 0.15 * hw, "dark", t)
        return
    if kind == "alarm":   # the alarm going off: the time big, snooze and stop; the phone buzzing
        buzz = 0.04 * hw * math.sin(t * 60.0)
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#120E1C"))
        p.glow(x, y - 0.30 * hh, 1.1 * hw, 0.5 * hh, np.asarray(hexc("#FF9A5A"), np.float32),
               0.30 + 0.25 * abs(math.sin(t * 6.0)))
        _digits(p, "6:00", x + buzz, y - 0.30 * hh, 0.60 * hw, CREAM)
        p.poly(rr(x - 0.80 * hw + buzz, y + 0.22 * hh, 1.60 * hw, 0.24 * hh, 0.12 * hh), hexc("#4A4458"))
        p.poly(rr(x - 0.80 * hw + buzz, y + 0.56 * hh, 1.60 * hw, 0.24 * hh, 0.12 * hh), hexc("#FF7A3A"))
        for side in (-1, 1):
            for k in range(2):
                _line(p, x + side * (1.18 + 0.16 * k) * hw, y, hh, [(0.0, -0.22), (0.0, 0.22)], 0.04, CREAM, 0.8)
        return
    if kind == "feed":   # the endless feed: one short video after another swiping up; like, comment, share
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#0E0C14"))
        n, u = divmod(t / 1.3, 1.0)
        slide = smooth(min(1.0, max(0.0, (u - 0.72) / 0.28)))   # (each one swiped away at its end)
        for j in (0, 1):
            k = int(n) + j
            top = y - hh + (j - slide) * 2 * hh
            y0, y1 = max(top, y - hh), min(top + 2 * hh, y + hh)
            if y1 - y0 < 1.0:
                continue
            bg, fg = FEED[k % len(FEED)]
            p.poly(rect(x - hw, y0, 2 * hw, y1 - y0), hexc(bg))
            cy = top + 1.05 * hh + 0.08 * hh * math.sin(t * 9.0 + k)   # (someone dancing in it)
            if y - hh + 0.55 * hh < cy < y + hh - 0.50 * hh:
                p.circle(x - 0.12 * hw, cy - 0.42 * hh, 0.24 * hw, hexc(fg))
                p.poly(ell(x - 0.12 * hw, cy + 0.02 * hh, 0.30 * hw, 0.30 * hh, 24), hexc(fg))
                for side in (-1, 1):
                    a = 0.9 * math.sin(t * 9.0 + k + side)
                    _line(p, x - 0.12 * hw, cy - 0.15 * hh, hw, [(side * 0.25, 0.0), (side * 0.62, -0.30 + 0.25 * a)],
                          0.10, hexc(fg))
        for k, v in enumerate((-0.10, 0.20, 0.48)):   # the buttons down its side
            bx, by = x + 0.72 * hw, y + v * hh
            if k == 0:
                i_heart(p, bx, by, 0.17 * hw, "dark", t)
            elif k == 1:
                p.circle(bx, by, 0.13 * hw, CREAM, 0.9)
            else:
                p.poly(np.array([(bx - 0.12 * hw, by + 0.11 * hw), (bx + 0.15 * hw, by), (bx - 0.12 * hw, by - 0.11 * hw)]),
                       CREAM, 0.9)
        p.poly(rect(x - hw, y + hh - 0.05 * hh, 2 * hw * u, 0.025 * hh), CREAM, 0.8)
        return
    if kind == "texts":   # texts piling up unanswered: grey bubbles of "??", a red count
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#1E2433"))
        n = 2 + int(t * 1.2) % 4
        for k in range(n):
            cy = y + 0.70 * hh - (n - 1 - k) * 0.36 * hh
            p.poly(rr(x - 0.88 * hw, cy - 0.13 * hh, 1.30 * hw, 0.26 * hh, 0.10 * hw), hexc("#4A4A5E"))
            for q in range(2):
                i_question(p, x - 0.55 * hw + q * 0.26 * hw, cy, 0.10 * hh, "dark", t)
        p.circle(x + 0.70 * hw, y - hh + 0.14 * hh, 0.22 * hw, RED)
        i_exclaim(p, x + 0.70 * hw, y - hh + 0.14 * hh, 0.15 * hw, "dark", t)
        return
    if kind == "video":   # a video playing: a film in its frame, the red bar creeping on, its comments
        p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), hexc("#0E0C14"))
        vy, vh = y - 0.35 * hh, 0.36 * hh
        p.poly(rect(x - hw, vy - vh, 2 * hw, 2 * vh), hexc("#2E4A6A"))
        p.circle(x - 0.6 * hw + 1.2 * hw * ((t * 0.12) % 1.0), vy - 0.30 * vh, 0.22 * vh, GOLD)
        p.poly(np.array([(x - hw, vy + vh), (x - 0.4 * hw, vy + 0.10 * vh), (x + 0.2 * hw, vy + 0.60 * vh), (x + 0.7 * hw, vy),
                         (x + hw, vy + 0.40 * vh), (x + hw, vy + vh)]), hexc("#1E3A2E"))
        u = (t * 0.05) % 1.0
        p.poly(rect(x - hw, vy + vh + 0.02 * hh, 2 * hw, 0.03 * hh), GREY)
        p.poly(rect(x - hw, vy + vh + 0.02 * hh, 2 * hw * u, 0.03 * hh), RED)
        for k in range(3):
            _line(p, x, y + (0.25 + 0.22 * k) * hh, hw, [(-0.8, 0.0), (0.5 - 0.3 * (k % 2), 0.0)], 0.06, GREY)
        return
    p.poly(rr(x - hw, y - hh, 2 * hw, 2 * hh, 0.10 * hw), S.PAL["screen"])


def screen_light(kind: str | None):
    """The colour a screen showing `kind` casts on what's round it (the phone's usual cold blue when nothing)."""
    return hexc(SCREEN_LIGHT[kind]) if kind in SCREEN_LIGHT else S.PAL["screen"]
