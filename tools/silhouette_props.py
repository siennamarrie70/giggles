"""
The silhouette look's things: furniture, things on the walls, outdoor pieces and small things, each drawn in code in
the owner's look (prompts/look_silhouette.txt.enc): flat shapes, one lit edge along the top, no outlines, the light
doing the mood (lamps, screens and fires glow; windows light up at dusk and night).

A place (tools/silhouette_scene.py) lays them out from a storyboard's description and asks each thing for:
  d_<name>(p, x, b, c)        its shape: x its middle, b the floor or ground it stands on (a wall thing: the floor under
                              it; a small thing: the top of what it stands on), c its Ctx (the light, which way it faces,
                              its options);
  f_<name>(p, x, b, c)        parts in front of the people (a bed's blanket, a podium, a car's near side);
  g_<name>(p, x, b, c)        its light (added: a lamp, a screen, a fire's glow);
  a_<name>(p, x, b, c, tau)   parts that move (a heart monitor's trace, a candle's flame, steam, a swaying bag);
  m_<name>(x, b, c)           its marks: where people stand, sit, lie or work at it (tools/silhouette_actions.py).
Every offset is written for a thing facing right (c.s = 1); c.X() mirrors it when it faces left.

PROPS says what each one is: its group, a line for the storyboard, its width, its layer ("floor": on the floor under
everything; "back": against the wall; "mid": in the room, beside the people; "wall": hung on the wall; "small": on a
surface; "floor_small": on the floor; "fore": out of focus in front of the lens) and where it fits ("in", "out",
"both").
"""

import math

import numpy as np

import silhouette as S
import silhouette_fx as FX
import silhouette_words as W

PROPS, HANG, GROUPS = W.PROPS, W.HANG, W.PROP_GROUPS   # (the words live in tools/silhouette_words.py)
from silhouette import PAL, Paint, ell, hexc, rect, rr, spline, tube
from silhouette_sets import ecg, rng


WOOD, WOOD_LIT, DARK, DARK_LIT, INK = "#2E2130", "#7A6068", "#1C1424", "#4A3C58", "#120D16"
METAL, METAL_LIT, STEEL, STEEL_LIT = "#2C2A33", "#8A8698", "#3E4050", "#9A9CB0"
PAPER = "#E6DED2"
FABRICS = ("#4A3A50", "#3A3450", "#54425A", "#3E3048", "#2E3446", "#4A3038")


class Ctx:
    """What a thing needs to know of its place: the light (silhouette_places.LIGHTS), whether lamps and screens are on,
    the weather, which way it faces (s: 1 right, -1 left), a seed for its details, its options."""

    def __init__(self, light="dusk", s=1, weather="clear", seed="", opts=None, lit=None):
        from silhouette_places import LIGHTS

        self.light, self.L, self.s = light, LIGHTS[light], 1 if s >= 0 else -1
        self.weather = weather
        self.lit = bool(self.L["lamp"] or weather == "rain") if lit is None else bool(lit)
        self.night = light in ("night", "dusk")
        self.k = {"day": 1.16, "dawn": 1.05, "dusk": 1.0, "night": 0.86}[light]
        self.seed = seed
        self.o = opts or {}

    def col(self, h, k=1.0):
        c = hexc(h) if isinstance(h, str) else np.asarray(h, np.float32)
        return np.clip(c * self.k * k, 0, 1)

    def X(self, x, dx):
        return x + self.s * dx

    @property
    def snow(self):
        return self.weather == "snow"


# --- drawing in offsets (dx along the way the thing faces, y in the world) --------------------------------------------------
def B(p, c, x, dx0, dx1, y0, y1, col, edge=None, r=0.0, a=1.0, ea=0.8, eh=3.0, k=1.0):
    """A box from dx0 to dx1 and y0 to y1, its lit edge along the top."""
    xa, xb = sorted((c.X(x, dx0), c.X(x, dx1)))
    if xb - xa < 0.5 or y1 - y0 < 0.5:
        return
    p.poly(rr(xa, y0, xb - xa, y1 - y0, r) if r else rect(xa, y0, xb - xa, y1 - y0), c.col(col, k), a)
    if edge:
        p.poly(rect(xa + r * 0.5, y0 - 1, xb - xa - r, eh), c.col(edge, 1.1), ea)


def P(p, c, x, pts, col, a=1.0, soft=0.0, smooth=False, k=1.0):
    q = np.array([(c.X(x, dx), y) for dx, y in pts], float)
    p.poly(spline(q, True, 8) if smooth else q, c.col(col, k), a, soft=soft)


def Tb(p, c, x, pts, w, col, a=1.0, w1=None):
    p.poly(tube([(c.X(x, dx), y) for dx, y in pts], w, w1), c.col(col), a)


def Ci(p, c, x, dx, y, r, col, a=1.0):
    p.circle(c.X(x, dx), y, r, c.col(col), a)


def El(p, c, x, dx, y, rx, ry, col, a=1.0):
    p.poly(ell(c.X(x, dx), y, rx, ry, 40), c.col(col), a)


def G(p, c, x, dx, y, rx, ry, color, strength):
    p.glow(c.X(x, dx), y, rx, ry, np.asarray(hexc(color) if isinstance(color, str) else color, np.float32), strength)


def Lit(p, c, x, dx0, dx1, y, col=WOOD_LIT, a=0.85, h=3.0):
    B(p, c, x, dx0, dx1, y - 1, y - 1 + h, col, a=a, k=1.1)


def _chair(p, c, x, dx, b, f, col=DARK, edge=DARK_LIT, seat=88):
    """A chair seen from the side: its seat's middle at dx, the person on it facing f (+1: the way the thing faces)."""
    s = f
    back = dx - s * 62
    B(p, c, x, back - 6, back + 6, b - seat - 120, b, col)
    B(p, c, x, dx - 60, dx + 60, b - seat, b - seat + 11, col, edge)
    B(p, c, x, dx + s * 50 - 5, dx + s * 50 + 5, b - seat + 10, b, col)


def _books(p, c, x, dx0, shelf_y, n, seed, max_dx=None):
    r = rng("books", seed)
    cols = ["#3B2A43", "#2E3446", "#4A2E3A", "#35283E", "#283545", "#41303F", "#2F2638", "#4A3A2E"]
    d = dx0
    for k in range(n):
        w, h = r.uniform(12, 20), r.uniform(46, 74)
        if max_dx is not None and d + w > max_dx:
            break
        B(p, c, x, d, d + w, shelf_y - h, shelf_y, cols[k % len(cols)])
        B(p, c, x, d, d + w, shelf_y - h, shelf_y - h + 1.6, "#8A6A72", a=0.7)
        d += w + r.uniform(1, 3)


def _frame_pic(p, c, x, dx0, dx1, y0, y1, inner="#33263C", hill="#4B3A55"):
    B(p, c, x, dx0, dx1, y0, y1, INK, r=2)
    B(p, c, x, dx0 + 6, dx1 - 6, y0 + 6, y1 - 6, inner)
    w, h = dx1 - dx0 - 12, y1 - y0 - 12
    P(p, c, x, [(dx0 + 6, y1 - 6), (dx0 + 6 + w * 0.35, y0 + 6 + h * 0.45), (dx0 + 6 + w * 0.55, y0 + 6 + h * 0.7),
                (dx0 + 6 + w * 0.72, y0 + 6 + h * 0.5), (dx1 - 6, y1 - 6)], hill)


def mark(kind, x, c, dx, **kw):
    out = {"kind": kind, "x": c.X(x, dx)}
    for k, v in kw.items():
        out[k] = v
    return out


# === home ==================================================================================================================
def d_bed(p, x, b, c):
    B(p, c, x, -395, -361, b - 230, b, DARK, r=8)
    B(p, c, x, -395, -392, b - 228, b - 4, DARK_LIT, a=0.7)
    B(p, c, x, -373, 397, b - 102, b - 58, "#3A3450", r=10)
    B(p, c, x, -373, 397, b - 58, b - 40, "#241C30")
    for dx in (-363, 377):
        B(p, c, x, dx, dx + 14, b - 40, b, "#1A1422")
    B(p, c, x, -363, -213, b - 148, b - 96, "#77708C", r=24)


def f_bed(p, x, b, c):
    top = [(-240, b - 100), (-194, b - 140), (-94, b - 154), (26, b - 150), (166, b - 140), (286, b - 130), (366, b - 112),
           (394, b - 90)]
    pts = spline(np.array([(c.X(x, dx), y) for dx, y in top]), closed=False, k=10)
    p.poly(np.vstack([pts, [(c.X(x, 394), b - 50), (c.X(x, -240), b - 50)]]), c.col("#4B4566"))
    Tb(p, c, x, [(-240, b - 94), (-194, b - 132), (-134, b - 146)], 16.0, "#6C6688", w1=12.0)
    for a_, b_ in (((-54, b - 142), (-34, b - 64)), ((106, b - 140), (136, b - 64)), ((266, b - 124), (286, b - 64))):
        Tb(p, c, x, [a_, b_], 2.5, "#3A3552", a=0.7)


def m_bed(x, b, c):
    return {"bed": mark("lie", x, c, -286, y=b - 150, f=c.s, slot="bed", use=["asleep", "lying_awake"]),
            "bed_edge": mark("sit", x, c, 256, seat=b - 100, f=c.s)}


def d_sofa(p, x, b, c):
    col = c.o.get("color", "#4A3A50")
    B(p, c, x, -210, 210, b - 180, b - 70, col, r=18)
    B(p, c, x, -210, 210, b - 104, b - 34, S.hexc(col) * 1.12, r=14)
    Lit(p, c, x, -198, 198, b - 181, "#8A7090", 0.7)
    for dx in (-222, 188):
        B(p, c, x, dx, dx + 34, b - 150, b - 34, S.hexc(col) * 0.88, r=12)
    for dx in (-190, -160, 172):
        B(p, c, x, dx, dx + 10, b - 34, b, INK)


def m_sofa(x, b, c):
    return {"sofa": mark("sit", x, c, -110, seat=b - 86, f=c.s), "sofa_2": mark("sit", x, c, 110, seat=b - 86, f=-c.s),
            "sofa_lie": mark("lie", x, c, -168, y=b - 128, f=c.s, use=["asleep", "lying_awake"])}


def d_armchair(p, x, b, c):
    col = c.o.get("color", "#54425A")
    B(p, c, x, -100, -50, b - 220, b - 60, S.hexc(col) * 0.9, r=16)
    B(p, c, x, -95, 95, b - 104, b - 40, col, r=12)
    Lit(p, c, x, -90, 90, b - 105, "#8A7090", 0.6)
    B(p, c, x, 70, 104, b - 140, b - 40, S.hexc(col) * 0.85, r=10)
    for dx in (-90, 80):
        B(p, c, x, dx, dx + 10, b - 40, b, INK)


def m_armchair(x, b, c):
    return {"armchair": mark("sit", x, c, -10, seat=b - 92, f=c.s)}


def d_dining_table(p, x, b, c):
    _chair(p, c, x, -235, b, 1, "#2A1E26", "#7A5A60")
    _chair(p, c, x, 235, b, -1, "#2A1E26", "#7A5A60")
    B(p, c, x, -160, 160, b - 150, b - 140, WOOD, WOOD_LIT)
    for dx in (-146, 136):
        B(p, c, x, dx, dx + 10, b - 140, b, "#221828")
    if c.o.get("plates", True):
        for dx in (-95, 95):
            El(p, c, x, dx, b - 153, 34, 4, "#D8D0C6")


def m_dining_table(x, b, c):
    return {"table": mark("sit", x, c, -235, seat=b - 88, f=c.s, reach=(c.X(x, -110), b - 154), use=["eating", "writing"]),
            "table_2": mark("sit", x, c, 235, seat=b - 88, f=-c.s, reach=(c.X(x, 110), b - 154), use=["eating", "writing"])}


def d_chair(p, x, b, c):
    _chair(p, c, x, 0, b, 1)


def m_chair(x, b, c):
    return {"chair": mark("sit", x, c, 0, seat=b - 88, f=c.s)}


def d_desk(p, x, b, c):
    _chair(p, c, x, -210, b, 1, "#1A1724", "#4A4660")
    B(p, c, x, -150, 150, b - 140, b - 130, "#2E2840", "#7A7090")
    B(p, c, x, -140, -130, b - 130, b, "#221C30")
    B(p, c, x, 60, 140, b - 130, b, "#262036")
    B(p, c, x, 70, 130, b - 100, b - 97, "#3A3450", a=0.8)
    if c.o.get("laptop"):
        B(p, c, x, -30, 70, b - 147, b - 140, "#24202E")
        P(p, c, x, [(-28, b - 147), (-18, b - 215), (-10, b - 215), (-20, b - 147)], "#24202E")
        P(p, c, x, [(-25, b - 151), (-16, b - 209), (-13, b - 209), (-22, b - 151)], PAL["screen"] * (1.0 if c.night else 0.6),
          a=0.85)
    else:
        B(p, c, x, 20, 140, b - 262, b - 170, "#141220", r=5)
        B(p, c, x, 27, 133, b - 255, b - 177, "#8FB0E8" if c.night else "#4A5A80", r=3, a=0.95)
        B(p, c, x, 75, 85, b - 170, b - 142, "#141220")
        B(p, c, x, 55, 105, b - 145, b - 140, "#141220", r=2)
        B(p, c, x, -90, 0, b - 148, b - 141, "#24202E", r=2)
    B(p, c, x, -128, -106, b - 168, b - 140, "#E6DCD0", r=4, a=0.9)


def g_desk(p, x, b, c):
    bright = 0.30 if c.night else 0.12
    if c.o.get("laptop"):
        G(p, c, x, -16, b - 180, 50, 40, PAL["screen"], bright * 0.6)
    else:
        G(p, c, x, 80, b - 215, 90, 70, PAL["screen"], bright)


def m_desk(x, b, c):
    reach = (c.X(x, -70), b - 144)
    return {"desk": mark("sit", x, c, -210, seat=b - 88, f=c.s, reach=reach,
                         use=["typing", "writing", "asleep_desk", "head_in_hands", "slumped", "sitting", "phone", "eating"])}


def d_stove(p, x, b, c):
    B(p, c, x, -115, 115, b - 160, b, "#2E2A38")
    B(p, c, x, -95, 95, b - 125, b - 22, "#24202C", r=4)
    B(p, c, x, -70, 70, b - 105, b - 62, "#14101A", r=3)
    Tb(p, c, x, [(-80, b - 134), (80, b - 134)], 5.0, METAL_LIT, a=0.8)
    for dx in (-80, -45, 45, 80):
        Ci(p, c, x, dx, b - 147, 5, "#4A4656")
    B(p, c, x, -120, 120, b - 168, b - 158, "#3A3646", STEEL_LIT)
    for dx in (-50, 50):
        El(p, c, x, dx, b - 169, 34, 4, INK)
    P(p, c, x, [(-102, b - 190), (2, b - 190), (-8, b - 170), (-92, b - 170)], METAL)       # the pan
    B(p, c, x, -102, 2, b - 192, b - 189, METAL_LIT, a=0.7)
    Tb(p, c, x, [(-100, b - 186), (-165, b - 196)], 7.0, METAL)
    B(p, c, x, 15, 85, b - 235, b - 170, "#3A3A48", r=4)                                     # the pot
    B(p, c, x, 10, 90, b - 241, b - 233, "#4A4A5A", STEEL_LIT, r=3)
    Ci(p, c, x, 50, b - 246, 6, "#4A4A5A")
    P(p, c, x, [(-130, b - 470), (130, b - 470), (110, b - 410), (-110, b - 410)], "#2A2634")   # the hood
    Lit(p, c, x, -128, 128, b - 470, STEEL_LIT, 0.6)
    B(p, c, x, -28, 28, b - 900, b - 470, "#24202E")


def g_stove(p, x, b, c):
    G(p, c, x, -50, b - 171, 34, 7, (0.45, 0.6, 1.0), 0.18)
    if c.lit:
        G(p, c, x, 0, b - 405, 120, 14, PAL["lamp"], 0.25)


def a_stove(p, x, b, c, tau):
    FX.steam(p, c.X(x, 50), b - 252, tau, seed=hash(c.seed) % 97)


def m_stove(x, b, c):
    return {"stove": mark("stand", x, c, -200, f=c.s, reach=(c.X(x, -50), b - 172), use=["cooking"])}


def d_fridge(p, x, b, c):
    B(p, c, x, -62, 62, b - 530, b, "#3A3346", r=10)
    B(p, c, x, -62, -59, b - 528, b - 4, "#7A6E86", a=0.7)
    B(p, c, x, -60, 60, b - 362, b - 359, "#221C2A")
    for y0, y1 in ((b - 500, b - 400), (b - 330, b - 200)):
        B(p, c, x, 40, 46, y0, y1, "#8A8098", r=3)
    B(p, c, x, -30, 5, b - 470, b - 432, PAPER, a=0.85)
    B(p, c, x, -40, -8, b - 420, b - 392, "#5A4A6A", a=0.9)


def d_counter(p, x, b, c):
    B(p, c, x, -200, 200, b - 160, b, "#241A2B")
    B(p, c, x, -205, 205, b - 168, b - 157, "#3A2E3E", WOOD_LIT, eh=4)
    for dx in np.arange(-195, 190, 98):
        B(p, c, x, dx + 4, dx + 92, b - 145, b - 12, "#2C2134")
        B(p, c, x, dx + 40, dx + 56, b - 132, b - 128, "#6A5A6A", r=2)
    B(p, c, x, 40, 145, b - 168, b - 160, "#14101A")                                         # the sink
    Tb(p, c, x, [(150, b - 168), (150, b - 205), (125, b - 210), (110, b - 196)], 6.0, METAL_LIT)
    B(p, c, x, -160, -70, b - 176, b - 168, "#5A4636", r=2)                                 # a cutting board
    Tb(p, c, x, [(-150, b - 180), (-100, b - 178)], 3.0, METAL_LIT, a=0.9)


def m_counter(x, b, c):
    return {"counter": mark("stand", x, c, -275, f=c.s, reach=(c.X(x, -120), b - 168), use=["wiping", "cooking"])}


def d_cabinets(p, x, b, c):
    for d0, d1 in ((-190, -3), (3, 190)):
        B(p, c, x, d0, d1, b - 640, b - 490, "#34283C")
        B(p, c, x, d0, d1, b - 492, b - 489, WOOD_LIT, a=0.6)
        B(p, c, x, d1 - 30 if d0 < 0 else d0 + 18, (d1 - 30 if d0 < 0 else d0 + 18) + 10, b - 520, b - 517, "#6A5A6A")


def d_basin(p, x, b, c):
    B(p, c, x, -24, 24, b - 150, b, "#5A5666", r=6)
    B(p, c, x, -82, 82, b - 182, b - 148, "#7A7488", r=12)
    Lit(p, c, x, -76, 76, b - 182, "#B8B2C6", 0.8)
    Tb(p, c, x, [(55, b - 182), (55, b - 210), (32, b - 214)], 6.0, METAL_LIT)
    B(p, c, x, -88, 88, b - 480, b - 258, INK, r=4)                                          # the mirror
    p.poly(rect(min(c.X(x, -78), c.X(x, 78)), b - 470, 156, 202),
           _vgrad(p, b - 470, b - 268, c.col("#4A4A62"), c.col("#262434")))
    P(p, c, x, [(-60, b - 300), (-20, b - 460), (0, b - 460), (-40, b - 300)], "#8A8AA8", a=0.10)


def m_basin(x, b, c):
    xa, xb = sorted((c.X(x, -78), c.X(x, 78)))
    return {"mirror": mark("stand", x, c, -175, f=c.s, glass=(xa, b - 470, xb, b - 268), use=["mirror"])}


def _vgrad(p, y0, y1, top, bot):
    def f(px, py):
        u = np.clip((p.wy(py) - y0) / max(y1 - y0, 1e-6), 0, 1)[..., None]
        return top * (1 - u) + bot * u
    return f


def d_wardrobe(p, x, b, c):
    B(p, c, x, -115, 115, b - 570, b, "#20172A", r=4)
    B(p, c, x, -115, -112, b - 570, b, DARK_LIT, a=0.8)
    B(p, c, x, -1, 1, b - 555, b - 15, "#120D18")
    for dx in (-14, 8):
        B(p, c, x, dx, dx + 5, b - 300, b - 266, "#6A5A6A", r=2)


def d_bookcase(p, x, b, c):
    B(p, c, x, -125, 125, b - 560, b, "#241A2C", r=3)
    B(p, c, x, -125, -122, b - 560, b, DARK_LIT, a=0.8)
    for k, y in enumerate((b - 440, b - 320, b - 200, b - 80)):
        B(p, c, x, -112, 112, y - 112, y, "#160F1C")
        B(p, c, x, -112, 112, y, y + 8, "#2E2236", WOOD_LIT, ea=0.5)
        _books(p, c, x, -108, y, 12, (c.seed, k), max_dx=108)


def d_tv(p, x, b, c):
    B(p, c, x, -160, 160, b - 110, b, "#241A2C", WOOD_LIT, r=3)
    B(p, c, x, -1, 1, b - 100, b - 10, "#120D18")
    B(p, c, x, -150, 150, b - 335, b - 140, "#0E0C12", r=4)
    on = c.o.get("on", True) and c.night
    B(p, c, x, -140, 140, b - 327, b - 148, "#3E5A86" if on else "#1C1C28", r=2)
    if on:
        P(p, c, x, [(-140, b - 200), (-60, b - 250), (20, b - 215), (140, b - 290), (140, b - 148), (-140, b - 148)],
          "#24365A", a=0.85)
        Ci(p, c, x, 60, b - 270, 18, "#8AA8D8", a=0.7)
    B(p, c, x, -8, 8, b - 140, b - 110, "#0E0C12")


def g_tv(p, x, b, c):
    if c.o.get("on", True) and c.night:
        G(p, c, x, 0, b - 240, 200, 140, PAL["screen"], 0.30)
        G(p, c, x, 0, b - 240, 420, 300, PAL["screen"], 0.08)


def d_floor_lamp(p, x, b, c):
    B(p, c, x, -3, 3, b - 430, b, "#1C1520")
    El(p, c, x, 0, b - 3, 34, 6, "#1C1520")
    P(p, c, x, [(-32, b - 478), (32, b - 478), (48, b - 424), (-48, b - 424)], "#5A4040")
    if c.lit:
        El(p, c, x, 0, b - 424, 46, 4, "#FFE9C8")


def g_floor_lamp(p, x, b, c):
    if c.lit:
        G(p, c, x, 0, b - 424, 140, 60, PAL["lamp"], 0.40)
        G(p, c, x, 0, b - 250, 260, 220, PAL["lamp"] * 0.5, 0.10)


def d_nightstand(p, x, b, c):
    B(p, c, x, -55, 55, b - 95, b, "#241A2C", WOOD_LIT, r=4)
    B(p, c, x, -45, 45, b - 52, b - 50, "#140F1A")
    B(p, c, x, -50, -4, b - 124, b - 96, "#140F18", r=5)
    for k in range(4):
        B(p, c, x, -44 + k * 9 + (3 if k > 1 else 0), -38 + k * 9 + (3 if k > 1 else 0), b - 116, b - 105, "#FF5A44", a=0.9)
    B(p, c, x, 20, 24, b - 150, b - 96, "#2A2030")
    P(p, c, x, [(4, b - 172), (40, b - 172), (48, b - 148), (-4, b - 148)], "#4A3036")
    if c.lit:
        El(p, c, x, 22, b - 148, 26, 3, "#FFE9C8")


def g_nightstand(p, x, b, c):
    G(p, c, x, -27, b - 110, 30, 14, (1.0, 0.30, 0.22), 0.30)
    if c.lit:
        G(p, c, x, 22, b - 150, 90, 40, PAL["lamp"], 0.40)
        G(p, c, x, 22, b - 95, 110, 16, PAL["lamp"], 0.20)


def d_plant(p, x, b, c):
    B(p, c, x, -34, 34, b - 70, b, "#2A1D2E", r=6)
    Lit(p, c, x, -34, 34, b - 71, "#7A5C68", 0.7)
    r = rng("pot", c.seed)
    leaf = "#1F2A2A" if c.light != "day" else "#2A3A36"
    for _ in range(8):
        a = r.uniform(-1.2, 1.2)
        L = 220 * r.uniform(0.6, 1.0)
        tip = (math.sin(a) * L, b - 70 - math.cos(a) * L)
        mid = (math.sin(a) * L * 0.5 + r.uniform(-20, 20), b - 70 - math.cos(a) * L * 0.55)
        Tb(p, c, x, [(0, b - 66), mid, tip], 18.0, leaf, w1=3.0)


def d_coffee_table(p, x, b, c):
    B(p, c, x, -120, 120, b - 84, b - 74, WOOD, WOOD_LIT)
    for dx in (-110, 100):
        B(p, c, x, dx, dx + 10, b - 74, b, "#221828")
    B(p, c, x, -90, -30, b - 89, b - 84, "#3A4A5A", a=0.9)


def d_door(p, x, b, c):
    B(p, c, x, -145, 145, b - 596, b, "#160F18")
    B(p, c, x, -145, 145, b - 596, b - 592, DARK_LIT, a=0.8)
    if c.o.get("open"):
        p.poly(rect(min(c.X(x, -125), c.X(x, 125)), b - 580, 250, 580),
               _vgrad(p, b - 580, b, c.col("#6A4A48", 1.1), c.col("#B88060", 1.1)))
        B(p, c, x, -125, -115, b - 580, b, "#3A2A30")
        B(p, c, x, 110, 132, b - 580, b, "#3A2A3A")
    else:
        B(p, c, x, -125, 125, b - 580, b, "#3A2A3A")
        for y0, y1 in ((b - 550, b - 340), (b - 290, b - 30)):
            B(p, c, x, -95, 95, y0, y1, "#33253A", "#5A4658", r=3, ea=0.7)
        Ci(p, c, x, 0, b - 410, 5, "#8A7A80")
        B(p, c, x, 87, 113, b - 280, b - 272, "#9A8A90", r=3)


def g_door(p, x, b, c):
    if c.o.get("open"):
        P(p, c, x, [(-125, b), (125, b), (185, b + 60), (-185, b + 60)], (0.9, 0.6, 0.42), a=0.25, soft=12)
        G(p, c, x, 0, b - 300, 140, 280, (0.70, 0.45, 0.30), 0.18)


def m_door(x, b, c):
    return {"door": mark("stand", x, c, -215, f=c.s, arms="knock", use=["at_door"]),
            "doorway": mark("stand", x, c, 5, f=-c.s)}


def d_rug(p, x, b, c):
    p.poly(ell(x, b + 4, 260, 14, 64), c.col(c.o.get("color", "#2A2030")), 0.85)


def d_fireplace(p, x, b, c):
    B(p, c, x, -180, 180, b - 300, b, "#2A2030")
    B(p, c, x, -200, 200, b - 314, b - 298, "#3A2C3A", WOOD_LIT, eh=4)
    B(p, c, x, -112, 112, b - 205, b - 18, "#0A070C", r=6)
    B(p, c, x, -195, 195, b - 20, b, "#241A26", "#5A4A58", ea=0.6)
    for dx, h in ((-150, 60), (120, 48)):
        B(p, c, x, dx, dx + 34, b - 314 - h, b - 314, INK, r=2)
        B(p, c, x, dx + 5, dx + 29, b - 309 - h, b - 319, "#3A2E40")
    Tb(p, c, x, [(-70, b - 30), (60, b - 42)], 16.0, "#3A2620")
    Tb(p, c, x, [(-50, b - 44), (80, b - 28)], 14.0, "#2E1E1A")


def a_fireplace(p, x, b, c, tau):
    FX.flames(p, x, b - 36, 190, 120, tau, seed=hash(c.seed) % 101)


def g_fireplace(p, x, b, c):
    G(p, c, x, 0, b - 110, 170, 110, FX.FIRE_LIGHT, 0.45)
    G(p, c, x, 0, b - 80, 520, 300, FX.FIRE_LIGHT * 0.6, 0.12)
    G(p, c, x, 0, b + 4, 320, 24, FX.FIRE_LIGHT, 0.30)


# === on the walls (b: the floor under it; HANG: how high its middle is) =====================================================
def d_photos(p, x, b, c):
    y = b - HANG["photos"]
    _frame_pic(p, c, x, -110, -10, y - 45, y + 40)
    _frame_pic(p, c, x, 20, 90, y - 30, y + 25, "#2E3446", "#3E4C60")


def d_poster(p, x, b, c):
    y = b - HANG["poster"]
    B(p, c, x, -95, 95, y - 120, y + 120, INK, r=2)
    p.poly(rect(min(c.X(x, -85), c.X(x, 85)), y - 110, 170, 220), _vgrad(p, y - 110, y + 110, c.col("#5A4A7A"), c.col("#C88A7A")))
    Ci(p, c, x, 20, y + 10, 26, "#FFD7A0", a=0.85)
    P(p, c, x, [(-85, y + 110), (-30, y + 30), (10, y + 70), (50, y + 20), (85, y + 60), (85, y + 110)], "#2E2240")


def d_clock(p, x, b, c):
    y = b - HANG["clock"]
    Ci(p, c, x, 0, y, 40, "#1A1420")
    Ci(p, c, x, 0, y, 34, "#C9BFC6")
    hh, mm = (c.o.get("time") or "10:10").split(":")
    for ang, ln, w in (((int(hh) % 12 + int(mm) / 60) / 12 * math.tau, 18, 3.5), (int(mm) / 60 * math.tau, 27, 2.5)):
        Tb(p, c, x, [(0, y), (math.sin(ang) * ln * c.s, y - math.cos(ang) * ln)], w, "#1A1420")


def d_shelf(p, x, b, c):
    y = b - HANG["shelf"]
    B(p, c, x, -120, 120, y, y + 10, "#2B1F2E", WOOD_LIT, ea=0.7)
    _books(p, c, x, -110, y, 6, c.seed, max_dx=20)
    B(p, c, x, 60, 92, y - 34, y, "#2A1D2E", r=4)
    Tb(p, c, x, [(76, y - 32), (60, y - 70)], 10.0, "#1F2A2A", w1=2.0)
    Tb(p, c, x, [(76, y - 32), (96, y - 64)], 10.0, "#1F2A2A", w1=2.0)


def d_whiteboard(p, x, b, c):
    y = b - HANG["whiteboard"]
    B(p, c, x, -175, 175, y - 115, y + 115, "#2A2632", r=3)
    B(p, c, x, -165, 165, y - 105, y + 105, "#A8A2B2")
    up = c.o.get("chart", "up") != "down"
    pts = [(-140, y + 70), (-80, y + 40 if up else y - 50), (-20, y + 50 if up else y - 20), (40, y - 10 if up else y + 30),
           (100, y - 30 if up else y + 50), (140, y - 80 if up else y + 80)]
    Tb(p, c, x, pts, 5.0, "#3A6A5A" if up else "#9A3A3A")
    for k in range(3):
        B(p, c, x, -150, -150 + 60 + k * 25, y - 90 + k * 18, y - 86 + k * 18, "#4A4658", a=0.7)
    B(p, c, x, -100, 100, y + 115, y + 122, "#3A3644")


def d_screen(p, x, b, c):
    y = b - HANG["screen"]
    B(p, c, x, -185, 185, y - 120, y + 120, "#16131E", r=4)
    B(p, c, x, -175, 175, y - 110, y + 110, "#A8B8D8" if c.lit or c.light == "day" else "#5A6A88")
    for k, h in enumerate((50, 80, 70, 120, 150)):
        B(p, c, x, -130 + k * 55, -95 + k * 55, y + 90 - h, y + 90, "#4A6A9A", a=0.8)


def m_screen(x, b, c):
    """He stands on the room's side of it, pointing at it."""
    side = 1 if x < 0 else -1
    return {"screen": {"kind": "stand", "x": x + side * 300, "f": -side, "point": (x, b - HANG["screen"]),
                       "use": ["presenting"]}}


def m_whiteboard(x, b, c):
    side = 1 if x < 0 else -1
    return {"whiteboard": {"kind": "stand", "x": x + side * 290, "f": -side, "point": (x, b - HANG["whiteboard"]),
                           "use": ["presenting"]}}


def g_screen(p, x, b, c):
    G(p, c, x, 0, b - HANG["screen"], 220, 140, PAL["screen"], 0.10)


def d_notice_board(p, x, b, c):
    y = b - HANG["notice_board"]
    B(p, c, x, -115, 115, y - 80, y + 80, "#3A2A22", r=2)
    B(p, c, x, -107, 107, y - 72, y + 72, "#6A5040")
    r = rng("notes", c.seed)
    for k in range(6):
        dx, dy = r.uniform(-95, 50), r.uniform(-62, 20)
        B(p, c, x, dx, dx + r.uniform(30, 48), y + dy, y + dy + r.uniform(36, 50), PAPER if k % 3 else "#E8D890", a=0.9)
        Ci(p, c, x, dx + 15, y + dy + 4, 3, "#B8322A")


def d_certificates(p, x, b, c):
    y = b - HANG["certificates"]
    for dx in (-95, 10):
        B(p, c, x, dx, dx + 85, y - 55, y + 55, INK, r=2)
        B(p, c, x, dx + 7, dx + 78, y - 48, y + 48, "#D8CFC0")
        for k in range(3):
            B(p, c, x, dx + 18, dx + 66, y - 28 + k * 14, y - 26 + k * 14, "#6A6070", a=0.7)
        Ci(p, c, x, dx + 60, y + 30, 8, "#A84A3A")


def d_calendar(p, x, b, c):
    y = b - HANG["calendar"]
    B(p, c, x, -55, 55, y - 75, y + 75, "#E2DACE")
    B(p, c, x, -55, 55, y - 75, y - 50, "#8A3A44")
    n = int(c.o.get("crossed", 12))
    for k in range(28):
        cx, cy = -42 + (k % 7) * 14, y - 36 + (k // 7) * 22
        if k < n:
            Tb(p, c, x, [(cx - 5, cy - 6), (cx + 5, cy + 6)], 2.0, "#B8322A")
            Tb(p, c, x, [(cx + 5, cy - 6), (cx - 5, cy + 6)], 2.0, "#B8322A")
        else:
            B(p, c, x, cx - 3, cx + 3, cy - 2, cy + 2, "#7A7080", a=0.7)


def d_tool_wall(p, x, b, c):
    y = b - HANG["tool_wall"]
    B(p, c, x, -170, 170, y - 110, y + 110, "#3A3036", r=2)
    for dx in np.arange(-155, 160, 22):
        for dy in np.arange(-95, 100, 22):
            Ci(p, c, x, dx, y + dy, 1.6, "#241C22")
    Tb(p, c, x, [(-130, y - 70), (-130, y + 40)], 8.0, "#5A4232")                          # a hammer
    B(p, c, x, -150, -110, y - 82, y - 62, METAL)
    P(p, c, x, [(-80, y - 80), (-20, y - 80), (-20, y + 60), (-80, y + 20)], STEEL)         # a saw
    for k, dx in enumerate((20, 55, 90, 125)):
        Tb(p, c, x, [(dx, y - 70), (dx, y - 70 + 60 + k * 18)], 7.0, METAL_LIT)
        Ci(p, c, x, dx, y - 74, 9, METAL_LIT)


def d_mirror(p, x, b, c):
    y = b - HANG["mirror"]
    El(p, c, x, 0, y, 70, 105, INK)
    p.poly(ell(x, y, 62, 97, 64), _vgrad(p, y - 97, y + 97, c.col("#4A4A62"), c.col("#262434")))
    P(p, c, x, [(-36, y + 50), (-6, y - 80), (8, y - 80), (-22, y + 50)], "#8A8AA8", a=0.10)


def m_mirror(x, b, c):
    """He stands on the room's side of the mirror, facing it."""
    y = b - HANG["mirror"]
    side = 1 if x < 0 else -1
    return {"mirror": {"kind": "stand", "x": x + side * 170, "f": -side, "glass": (x - 62, y - 97, x + 62, y + 97),
                       "oval": True, "use": ["mirror"]}}


# === work ==================================================================================================================
def d_office_row(p, x, b, c):
    for d0 in (-290, 20):
        B(p, c, x, d0, d0 + 260, b - 130, b - 120, "#2A2436", "#6A6080")
        for dx in (d0 + 14, d0 + 236):
            B(p, c, x, dx, dx + 10, b - 120, b, "#1E1A28")
        B(p, c, x, d0 + 150, d0 + 240, b - 208, b - 138, "#16131E", r=4)
        B(p, c, x, d0 + 156, d0 + 234, b - 202, b - 146, "#6F86B8" if c.night else "#3A4660", r=3, a=0.9)
        B(p, c, x, d0 + 192, d0 + 200, b - 138, b - 128, "#16131E")
    if c.light in ("day", "dusk") and c.o.get("people", True):
        for d0 in (-290, 20):
            px = c.X(x, d0 + 40)
            S.draw_person(p, S.pose_sit(px, b - 64, b, c.s, 46.0, arms="type", reach=(c.X(x, d0 + 150), b - 130)),
                          S.LOOKS["stranger"], None)


def g_office_row(p, x, b, c):
    for d0 in (-290, 20):
        G(p, c, x, d0 + 195, b - 175, 70, 50, PAL["screen"], 0.18 if c.night else 0.07)


def d_meeting_table(p, x, b, c):
    _chair(p, c, x, -330, b, 1, "#2A2436", "#6A6080")
    _chair(p, c, x, 330, b, -1, "#2A2436", "#6A6080")
    B(p, c, x, -260, 260, b - 150, b - 140, "#3A3046", "#9A8AA0")
    for dx in (-200, 190):
        B(p, c, x, dx, dx + 12, b - 140, b, "#221C2C")
    B(p, c, x, -60, 60, b - 140, b - 125, "#2A2436")
    for dx in (-200, 150):
        B(p, c, x, dx, dx + 50, b - 154, b - 150, PAPER, a=0.85)


def m_meeting_table(x, b, c):
    return {"meeting": mark("sit", x, c, -330, seat=b - 88, f=c.s, reach=(c.X(x, -200), b - 154), use=["writing"]),
            "meeting_2": mark("sit", x, c, 330, seat=b - 88, f=-c.s, reach=(c.X(x, 200), b - 154), use=["writing"])}


def d_shop_counter(p, x, b, c):
    B(p, c, x, -175, 175, b - 170, b, "#2A1E2A")
    B(p, c, x, -180, 180, b - 178, b - 168, "#3A2C36", WOOD_LIT, eh=4)
    B(p, c, x, -165, 165, b - 120, b - 112, "#4A3640", a=0.8)
    B(p, c, x, 90, 165, b - 230, b - 178, "#1E1A24", r=4)
    B(p, c, x, 100, 150, b - 222, b - 196, "#5AA8A0" if c.lit else "#2A4A48", r=2)
    for k, dx in enumerate((-140, -110, -80)):
        B(p, c, x, dx, dx + 24, b - 178 - 30 - k * 6, b - 178, ("#6A4A3A", "#3A5A6A", "#7A6A3A")[k], r=2)


def g_shop_counter(p, x, b, c):
    G(p, c, x, 125, b - 209, 50, 30, (0.35, 0.75, 0.70), 0.14)


def m_shop_counter(x, b, c):
    return {"shop": mark("stand", x, c, -255, f=c.s, reach=(c.X(x, -150), b - 180)),
            "shop_2": mark("stand", x, c, 255, f=-c.s, reach=(c.X(x, 150), b - 180))}


def d_shop_shelves(p, x, b, c):
    B(p, c, x, -195, 195, b - 520, b, "#1E1626", r=2)
    r = rng("goods", c.seed)
    cols = ["#7A4A3A", "#3A5A6A", "#8A7A3A", "#5A3A5A", "#3A6A4A", "#8A5A4A", "#C8B8A0"]
    for k, y in enumerate((b - 400, b - 280, b - 160, b - 40)):
        B(p, c, x, -185, 185, y, y + 8, "#3A2E3E", WOOD_LIT, ea=0.6)
        dx = -178
        while dx < 170:
            w = r.uniform(20, 42)
            h = r.uniform(30, 90)
            kind = r.integers(3)
            col = cols[int(r.integers(len(cols)))]
            if kind == 0:
                B(p, c, x, dx, min(dx + w, 178), y - h, y, col, r=2)
            elif kind == 1:
                B(p, c, x, dx, min(dx + w * 0.7, 178), y - h * 0.7, y, col, r=6)
            else:
                B(p, c, x, dx + w * 0.2, min(dx + w * 0.5, 178), y - h, y - h * 0.6, col)
                B(p, c, x, dx, min(dx + w * 0.7, 178), y - h * 0.6, y, col, r=4)
            dx += w + r.uniform(2, 6)


def d_workbench(p, x, b, c):
    B(p, c, x, -190, 190, b - 178, b - 162, WOOD, WOOD_LIT, eh=4)
    for dx in (-180, 168):
        B(p, c, x, dx, dx + 12, b - 162, b, "#221828")
    B(p, c, x, -180, 180, b - 60, b - 52, "#2A1E2A")
    for dx in (-150, -60, 40):
        B(p, c, x, dx, dx + 70, b - 52 - 50, b - 52, "#5A4636", r=2)
    B(p, c, x, 150, 200, b - 205, b - 178, METAL)                                           # the vice
    B(p, c, x, 140, 210, b - 214, b - 205, METAL_LIT)
    B(p, c, x, -120, 20, b - 188, b - 178, "#6A5040", r=2)                                  # a plank
    Tb(p, c, x, [(60, b - 182), (130, b - 182)], 4.0, METAL_LIT)


def m_workbench(x, b, c):
    return {"bench": mark("stand", x, c, -265, f=c.s, reach=(c.X(x, -140), b - 182), use=["fixing", "wiping"])}


def d_chef_range(p, x, b, c):
    B(p, c, x, -220, 220, b - 170, b, STEEL)
    B(p, c, x, -225, 225, b - 178, b - 168, "#4A4C5C", STEEL_LIT)
    for d0 in (-200, 10):
        B(p, c, x, d0, d0 + 190, b - 150, b - 30, "#34364A", r=3)
        Tb(p, c, x, [(d0 + 20, b - 136), (d0 + 170, b - 136)], 5.0, STEEL_LIT, a=0.8)
    for d0, w, h in ((-180, 90, 90), (70, 110, 120)):
        B(p, c, x, d0, d0 + w, b - 178 - h, b - 178, "#4A4C5C", r=4)
        B(p, c, x, d0 - 6, d0 + w + 6, b - 184 - h, b - 176 - h, "#5A5C6C", STEEL_LIT, r=3)
    P(p, c, x, [(-60, b - 196), (30, b - 196), (22, b - 180), (-52, b - 180)], METAL)
    Tb(p, c, x, [(-60, b - 192), (-120, b - 200)], 7.0, METAL)
    P(p, c, x, [(-240, b - 520), (240, b - 520), (210, b - 440), (-210, b - 440)], "#3A3C4A")
    Lit(p, c, x, -238, 238, b - 520, STEEL_LIT, 0.6)
    B(p, c, x, -40, 40, b - 900, b - 520, "#2E3040")
    for k, dx in enumerate((-180, -120, -60, 60, 120)):
        Tb(p, c, x, [(dx, b - 440), (dx, b - 410)], 3.0, METAL_LIT)
        El(p, c, x, dx, b - 388 + (k % 2) * 6, 22 + (k % 3) * 4, 22 + (k % 3) * 4, METAL)


def a_chef_range(p, x, b, c, tau):
    FX.steam(p, c.X(x, -135), b - 270, tau, seed=hash(c.seed) % 89)
    FX.steam(p, c.X(x, 125), b - 300, tau + 1.3, seed=hash(c.seed) % 83 + 1)


def g_chef_range(p, x, b, c):
    G(p, c, x, -15, b - 182, 60, 8, (0.45, 0.6, 1.0), 0.18)
    G(p, c, x, 0, b - 430, 240, 20, PAL["lamp"], 0.22)


def m_chef_range(x, b, c):
    return {"range": mark("stand", x, c, -290, f=c.s, reach=(c.X(x, -20), b - 182), use=["cooking"])}


def d_prep_counter(p, x, b, c):
    B(p, c, x, -180, 180, b - 172, b - 160, "#4A4C5C", STEEL_LIT)
    for dx in (-170, 160):
        B(p, c, x, dx, dx + 10, b - 160, b, STEEL)
    B(p, c, x, -170, 170, b - 50, b - 42, STEEL)
    B(p, c, x, -130, -20, b - 180, b - 172, "#6A5040", r=2)
    for k, dx in enumerate((-110, -85, -60)):
        Ci(p, c, x, dx, b - 188, 10, ("#C8643A", "#5A8A4A", "#B8322A")[k])
    Tb(p, c, x, [(-40, b - 184), (20, b - 186)], 4.0, METAL_LIT)


def m_prep_counter(x, b, c):
    return {"prep": mark("stand", x, c, -250, f=c.s, reach=(c.X(x, -100), b - 176), use=["cooking", "wiping"])}


def d_podium(p, x, b, c):
    pass   # (all of it is in front of the speaker: f_podium)


def f_podium(p, x, b, c):
    P(p, c, x, [(-78, b - 350), (78, b - 330), (62, b), (-62, b)], "#2A1E2A")
    P(p, c, x, [(-80, b - 352), (80, b - 332), (80, b - 324), (-80, b - 344)], WOOD_LIT, a=0.85)
    B(p, c, x, -62, 62, b - 12, b, INK)
    Tb(p, c, x, [(-40, b - 348), (-62, b - 400), (-88, b - 418)], 4.0, METAL)
    El(p, c, x, -92, b - 420, 10, 7, METAL_LIT)


def m_podium(x, b, c):
    return {"podium": mark("stand", x, c, -70, f=c.s, slot="bed", reach=(c.X(x, -30), b - 345), use=["speaking"])}


def d_stage(p, x, b, c):
    h = 70
    p.poly(rect(min(c.X(x, -560), c.X(x, 560)), b - 760, 1120, 760 - h),
           _vgrad(p, b - 760, b - h, c.col("#3A1620"), c.col("#5A2230")))
    for dx in np.arange(-540, 560, 60):
        Tb(p, c, x, [(dx, b - 760), (dx + 6, b - h)], 10.0, "#2A0E16", a=0.6)
    B(p, c, x, -560, 560, b - 760, b - 700, "#2A0E16")
    B(p, c, x, -550, 550, b - h, b, "#2A1E2A")
    Lit(p, c, x, -550, 550, b - h, "#9A7A80", 0.9, 4)
    for k in range(3):
        B(p, c, x, 550 + k * 30, 580 + k * 30, b - h + k * (h / 3), b, "#241A26")


def m_stage(x, b, c):
    g = b - 70
    return {"stage": mark("stand", x, c, 0, f=c.s, ground=g), "stage_2": mark("stand", x, c, 260, f=-c.s, ground=g),
            "stage_3": mark("stand", x, c, -260, f=c.s, ground=g)}


def d_audience(p, x, b, c):
    """(drawn in the foreground: b is the floor; the heads stand up into the bottom of the frame)."""
    r = rng("audience", c.seed)
    for row, (y, sp, sc) in enumerate(((b + 110, 170, 1.15), (b + 220, 200, 1.45))):
        for dx in np.arange(-500, 520, sp):
            dx = dx + r.uniform(-25, 25) + (sp / 2 if row else 0)
            R = 52 * sc * r.uniform(0.92, 1.08)
            Ci(p, c, x, dx, y - R * 2.2, R, "#07060A")
            P(p, c, x, [(dx - R * 1.4, y + 200), (dx - R * 1.1, y - R * 0.9), (dx + R * 1.1, y - R * 0.9), (dx + R * 1.4, y + 200)],
              "#0A080D", smooth=False)


def d_filing_cabinet(p, x, b, c):
    B(p, c, x, -55, 55, b - 300, b, "#3A3846", r=3)
    B(p, c, x, -55, -52, b - 300, b, "#7A788A", a=0.6)
    for k in range(3):
        y = b - 290 + k * 96
        B(p, c, x, -48, 48, y, y + 88, "#34323F", r=2)
        B(p, c, x, -15, 15, y + 16, y + 22, "#8A8698", r=2)


def d_water_cooler(p, x, b, c):
    B(p, c, x, -36, 36, b - 200, b, "#7E7A8C", r=4)
    B(p, c, x, -28, 28, b - 330, b - 200, "#5A8AB8", r=14, a=0.55)
    B(p, c, x, -26, -18, b - 160, b - 150, "#3A3644")


# === health and the gym =================================================================================================
def d_hospital_bed(p, x, b, c):
    B(p, c, x, -360, 360, b - 120, b - 100, "#4A4656")
    for dx in (-330, 320):
        B(p, c, x, dx, dx + 12, b - 100, b - 22, "#3A3646")
        Ci(p, c, x, dx + 6, b - 14, 13, INK)
    B(p, c, x, -380, -360, b - 300, b - 100, "#5A5666", r=6)
    B(p, c, x, 360, 380, b - 230, b - 100, "#5A5666", r=6)
    P(p, c, x, [(-350, b - 230), (-170, b - 160), (-170, b - 120), (-350, b - 120)], "#B8B4C4", k=0.85)
    B(p, c, x, -170, 350, b - 160, b - 120, "#B8B4C4", r=6, k=0.85)
    B(p, c, x, -340, -230, b - 262, b - 208, "#D8D4E0", r=22, k=0.85)
    Tb(p, c, x, [(-200, b - 175), (300, b - 175)], 5.0, METAL_LIT, a=0.7)
    B(p, c, x, -440, -434, b - 600, b, "#5A5666")                                          # the drip
    El(p, c, x, -437, b - 8, 40, 7, "#3A3646")
    B(p, c, x, -470, -404, b - 600, b - 594, "#5A5666")
    B(p, c, x, -470, -430, b - 590, b - 520, "#D8E4F0", r=8, a=0.45)
    Tb(p, c, x, [(-450, b - 520), (-430, b - 420), (-330, b - 300), (-280, b - 230)], 2.0, "#D8E4F0", a=0.5)


def f_hospital_bed(p, x, b, c):
    top = [(-170, b - 165), (-80, b - 182), (60, b - 186), (200, b - 180), (330, b - 172), (360, b - 150)]
    pts = spline(np.array([(c.X(x, dx), y) for dx, y in top]), closed=False, k=10)
    p.poly(np.vstack([pts, [(c.X(x, 360), b - 112), (c.X(x, -170), b - 112)]]), c.col("#8A9AB0", 0.9))
    Tb(p, c, x, [(-170, b - 160), (-120, b - 176)], 10.0, "#A8B4C8", a=0.8)


def m_hospital_bed(x, b, c):
    return {"hospital_bed": mark("lie", x, c, -270, y=b - 222, f=c.s, slot="bed", use=["asleep", "lying_awake"]),
            "bedside": mark("stand", x, c, 440, f=-c.s)}


def d_heart_monitor(p, x, b, c):
    B(p, c, x, -4, 4, b - 440, b, "#3A3646")
    El(p, c, x, 0, b - 8, 46, 8, "#2A2636")
    B(p, c, x, -72, 72, b - 570, b - 440, "#1A1820", r=6)
    B(p, c, x, -62, 62, b - 560, b - 450, "#0C1214", r=3)


def a_heart_monitor(p, x, b, c, tau):
    """The trace sweeping across the screen, a heartbeat every 0.95 s."""
    x0, x1 = sorted((c.X(x, -58), c.X(x, 58)))
    base, h = b - 495, 40
    sweep = (tau % 2.4) / 2.4
    us = np.linspace(0, 1, 140)
    ys = base - ecg(np.mod(us * (2.4 / 0.95), 1.0)) * h
    xs = x0 + us * (x1 - x0)
    keep = us <= sweep
    if keep.sum() > 2:
        p.poly(tube(np.stack([xs[keep], ys[keep]], 1), 2.6, k=1), np.array([0.45, 0.95, 0.75], np.float32), 0.95)


def g_heart_monitor(p, x, b, c):
    G(p, c, x, 0, b - 505, 90, 70, (0.35, 0.85, 0.65), 0.16)


def d_waiting_chairs(p, x, b, c):
    B(p, c, x, -220, 220, b - 62, b - 52, "#2A2636")
    for dx in (-190, 180):
        B(p, c, x, dx, dx + 10, b - 52, b, "#2A2636")
    for dx in (-150, 0, 150):
        B(p, c, x, dx - 58, dx + 58, b - 92, b - 80, "#3A4A62", "#7A8AA8", r=3)
        B(p, c, x, dx - 66, dx - 54, b - 200, b - 88, "#3A4A62", r=4)
        B(p, c, x, dx - 6, dx + 6, b - 80, b - 62, "#2A2636")


def m_waiting_chairs(x, b, c):
    return {"wait": mark("sit", x, c, -150, seat=b - 92, f=c.s), "wait_2": mark("sit", x, c, 0, seat=b - 92, f=c.s),
            "wait_3": mark("sit", x, c, 150, seat=b - 92, f=c.s)}


def d_weights(p, x, b, c):
    for y in (b - 230, b - 120):
        B(p, c, x, -160, 160, y, y + 12, "#2A2832", STEEL_LIT, ea=0.6)
    for dx in (-150, 140):
        B(p, c, x, dx, dx + 10, b - 230, b, "#2A2832")
    for k, dx in enumerate(np.linspace(-120, 120, 6)):
        for y, rad in ((b - 230, 22 + k * 2), (b - 120, 26 + k * 2.4)):
            Ci(p, c, x, dx, y - rad, rad, METAL_LIT)
            Ci(p, c, x, dx + 2, y - rad + 2, rad - 4, METAL)


def m_weights(x, b, c):
    return {"weights": mark("stand", x, c, 270, f=c.s, use=["lifting"])}


def d_punching_bag(p, x, b, c):
    pass


def a_punching_bag(p, x, b, c, tau):
    sway = 0.035 * math.sin(math.tau * tau / 2.3)
    top = (x, b - 900)
    hook = (x + math.sin(sway) * 400, b - 900 + 400)
    Tb(p, c, x, [(0, top[1]), (c.s * (hook[0] - x), hook[1])], 4.0, METAL)
    pts = []
    for dx, y in ((-55, b - 500), (55, b - 500), (58, b - 180), (40, b - 152), (-40, b - 152), (-58, b - 180)):
        ang = sway
        rx, ry = dx * c.s, y - hook[1]
        pts.append((hook[0] + rx * math.cos(ang) - ry * math.sin(ang), hook[1] + rx * math.sin(ang) + ry * math.cos(ang)))
    p.poly(spline(np.array(pts), True, 6), c.col("#4A2226"))
    p.poly(tube([pts[0], pts[5]], 4.0), c.col("#9A5A5A"), 0.6)
    for y in (b - 470, b - 330, b - 190):
        ry = y - hook[1]
        cx_ = hook[0] - ry * math.sin(sway)
        cy_ = hook[1] + ry * math.cos(sway)
        p.poly(tube([(cx_ - 56, cy_), (cx_ + 56, cy_)], 6.0), c.col("#3A1A1E"), 0.9)


def m_punching_bag(x, b, c):
    return {"bag": mark("stand", x, c, -215, f=c.s, target=(c.X(x, 0), b - 330), use=["boxing"])}


def d_treadmill(p, x, b, c):
    B(p, c, x, -160, 140, b - 46, b - 14, "#1E1C26", r=8)
    B(p, c, x, -150, 130, b - 50, b - 44, "#3A3846", "#7A788A")
    for dx in (-150, 120):
        Ci(p, c, x, dx, b - 30, 13, "#2A2832")
    Tb(p, c, x, [(120, b - 40), (150, b - 330)], 9.0, "#2A2832")
    Tb(p, c, x, [(150, b - 330), (60, b - 250)], 7.0, "#2A2832")
    P(p, c, x, [(110, b - 360), (190, b - 340), (180, b - 300), (100, b - 318)], "#1E1C26")
    P(p, c, x, [(120, b - 350), (176, b - 336), (170, b - 318), (116, b - 330)], "#5AA8A0" if c.night else "#2A4A48")


def m_treadmill(x, b, c):
    return {"treadmill": mark("treadmill", x, c, -30, f=c.s, ground=b - 50, use=["treadmill"])}


def d_gym_mat(p, x, b, c):
    B(p, c, x, -160, 160, b - 7, b + 2, "#3A4A5A", r=3)
    Lit(p, c, x, -156, 156, b - 7, "#6A7A8A", 0.6, 2)


def m_gym_mat(x, b, c):
    return {"mat": mark("pushup", x, c, 140, f=c.s)}


# === outdoors =============================================================================================================
def _leafy(c):
    base = c.L["near"]
    return S.hexc(base) * 0.8 if isinstance(base, str) else base


def d_tree(p, x, b, c):
    r = rng("tree", c.seed)
    dark = np.clip(_leafy(c) * 1.0, 0, 1)
    trunk_top = b - 300 - r.uniform(0, 60)
    p.poly(rect(x - 12, trunk_top, 24, b - trunk_top), dark)
    Tb(p, c, x, [(0, trunk_top + 60), (60, trunk_top - 20)], 10.0, dark)
    blobs = [(r.uniform(-130, 130), trunk_top - r.uniform(20, 200), r.uniform(70, 120)) for _ in range(8)]
    for dx, y, rad in blobs:
        p.circle(c.X(x, dx), y, rad, dark)
    if c.snow:
        for dx, y, rad in blobs:
            p.poly(ell(c.X(x, dx), y - rad * 0.72, rad * 0.62, rad * 0.16, 32), c.col("#D8D4E4"), 0.40)


def d_pine(p, x, b, c):
    dark = np.clip(_leafy(c) * 0.9, 0, 1)
    p.poly(rect(x - 9, b - 90, 18, 90), dark)
    for k, (w, y0, y1) in enumerate(((120, b - 90, b - 270), (100, b - 210, b - 380), (78, b - 320, b - 480), (54, b - 420,
                                                                                                             b - 570))):
        p.poly(np.array([(x - w, y0), (x + w, y0), (x, y1)], float), dark)
        if c.snow:
            p.poly(np.array([(x - w * 0.35, y1 + (y0 - y1) * 0.35), (x + w * 0.35, y1 + (y0 - y1) * 0.35), (x, y1)], float),
                   c.col("#D8D4E4"), 0.8)


def d_house(p, x, b, c):
    wall = c.o.get("color", "#2A2036")
    B(p, c, x, -230, 230, b - 380, b, wall)
    P(p, c, x, [(-262, b - 376), (0, b - 560), (262, b - 376)], "#1C1426")
    Tb(p, c, x, [(-262, b - 378), (0, b - 562)], 4.0, "#5A4868", a=0.8)
    B(p, c, x, 110, 160, b - 560, b - 470, "#1C1426")
    if c.snow:
        P(p, c, x, [(-262, b - 376), (0, b - 560), (262, b - 376), (230, b - 384), (0, b - 540), (-230, b - 384)], "#D8D4E4",
          a=0.85)
    on = c.lit and c.night
    for d0 in (-170, 80):
        B(p, c, x, d0, d0 + 90, b - 310, b - 200, "#FFC383" if on else "#141019", a=0.92)
        B(p, c, x, d0 + 43, d0 + 47, b - 310, b - 200, INK)
        B(p, c, x, d0 - 6, d0 + 96, b - 200, b - 192, "#3A2E44")
    B(p, c, x, -40, 30, b - 220, b, "#16101C")
    B(p, c, x, -55, 45, b - 12, b, "#2A2232")


def g_house(p, x, b, c):
    if c.lit and c.night:
        for d0 in (-170, 80):
            G(p, c, x, d0 + 45, b - 255, 80, 70, hexc("#FFC383") * 0.6, 0.30)
        G(p, c, x, 45, b - 240, 30, 20, PAL["lamp"], 0.5)


def m_house(x, b, c):
    return {"house_door": mark("stand", x, c, -110, f=c.s, use=["at_door"])}


def d_shopfront(p, x, b, c):
    B(p, c, x, -260, 260, b - 560, b, "#241A30")
    B(p, c, x, -260, -256, b - 560, b, "#3B2B48", a=0.8)
    on = c.lit and c.night
    p.poly(rect(min(c.X(x, -220), c.X(x, 80)), b - 300, 300, 240),
           _vgrad(p, b - 300, b - 60, c.col("#B8784E" if on else "#3A3446"), c.col("#E2A56E" if on else "#2A2634")))
    for y in (b - 230, b - 160):
        B(p, c, x, -210, 70, y, y + 5, "#5A3A30" if on else "#1E1A26", a=0.8)
    r = rng("shopgoods", c.seed)
    for k in range(8):
        dx = -200 + k * 34
        h = r.uniform(18, 34)
        B(p, c, x, dx, dx + 22, b - 230 - h, b - 230, "#6A4434" if on else "#1A1622", a=0.75)
    for k in range(7):
        col = "#7A3A44" if k % 2 == 0 else "#C8B8A0"
        P(p, c, x, [(-240 + k * 46, b - 340), (-194 + k * 46, b - 340), (-186 + k * 50, b - 300), (-236 + k * 50, b - 300)],
          col, k=0.8)
    B(p, c, x, 120, 200, b - 260, b, "#0F0B14")
    B(p, c, x, 124, 196, b - 282, b - 262, "#E8A070" if on else "#3A2E3A", a=0.8)
    B(p, c, x, -200, 60, b - 430, b - 370, "#16101C", r=3)
    for k in range(4):
        B(p, c, x, -180 + k * 60, -140 + k * 60, b - 408, b - 392, "#C8A070" if on else "#4A3A3A", r=4, a=0.8)


def g_shopfront(p, x, b, c):
    if c.lit and c.night:
        G(p, c, x, -70, b - 180, 220, 130, hexc("#FFC383") * 0.6, 0.25)
        P(p, c, x, [(-220, b), (80, b), (140, b + 60), (-280, b + 60)], hexc("#FFC383") * 0.5, a=0.25, soft=14)


def m_shopfront(x, b, c):
    return {"shop_window": mark("stand", x, c, -300, f=c.s), "shop_door": mark("stand", x, c, 60, f=c.s)}


def d_car(p, x, b, c):
    col = c.o.get("color", "#3A3550")
    P(p, c, x, [(-420, b - 70), (-424, b - 160), (-392, b - 205), (-300, b - 212), (260, b - 214), (380, b - 196),
                (430, b - 160), (432, b - 80), (410, b - 64), (-400, b - 62)], col, smooth=True)
    P(p, c, x, [(-300, b - 206), (-210, b - 318), (150, b - 318), (262, b - 206)], col, smooth=False)
    Tb(p, c, x, [(-290, b - 212), (-205, b - 320), (148, b - 320), (255, b - 212)], 4.0, S.hexc(col) * 2.0, a=0.6)
    glass = "#1A1824" if not c.night else "#14121C"
    P(p, c, x, [(-272, b - 212), (-196, b - 304), (-34, b - 304), (-34, b - 212)], glass)
    P(p, c, x, [(-18, b - 212), (-18, b - 304), (140, b - 304), (232, b - 212)], glass)
    P(p, c, x, [(-120, b - 300), (-90, b - 300), (-140, b - 214), (-170, b - 214)], "#8A8AA8", a=0.08)
    Tb(p, c, x, [(-26, b - 205), (-26, b - 80)], 2.0, INK, a=0.6)
    Tb(p, c, x, [(230, b - 205), (240, b - 90)], 2.0, INK, a=0.5)
    for dx in (-260, 270):
        El(p, c, x, dx, b - 70, 78, 64, INK)
        Ci(p, c, x, dx, b - 62, 60, "#141018")
        Ci(p, c, x, dx, b - 62, 30, "#5A5666")
        Ci(p, c, x, dx, b - 62, 10, "#2A2632")
    El(p, c, x, 418, b - 168, 12, 18, "#FFE9C8" if c.lit else "#6A6070")
    B(p, c, x, -428, -418, b - 190, b - 150, "#C8322A", a=0.9)


def g_car(p, x, b, c):
    if c.lit:
        G(p, c, x, 470, b - 160, 180, 50, PAL["lamp"], 0.35)
        P(p, c, x, [(425, b - 185), (900, b - 230), (900, b - 30), (425, b - 150)], PAL["lamp"] * 0.5, a=0.25, soft=20)
        G(p, c, x, -430, b - 170, 60, 30, (1.0, 0.2, 0.15), 0.35)


def m_car(x, b, c):
    return {"car": mark("stand", x, c, -120, f=c.s), "car_wheel": mark("kneel", x, c, 130, f=c.s, use=["fixing"]),
            "car_back": mark("stand", x, c, -560, f=c.s)}


def d_ambulance(p, x, b, c):
    body = "#A8A2B4"
    B(p, c, x, -470, 300, b - 400, b - 60, body, r=10, k=0.85)
    P(p, c, x, [(300, b - 400), (380, b - 400), (460, b - 250), (470, b - 70), (300, b - 60)], body, k=0.85)
    P(p, c, x, [(310, b - 380), (370, b - 380), (440, b - 255), (310, b - 255)], "#1A1824")
    B(p, c, x, -470, 470, b - 200, b - 170, "#A8323A", k=0.9)
    Tb(p, c, x, [(-300, b - 290), (-250, b - 290), (-230, b - 330), (-205, b - 245), (-185, b - 300), (-170, b - 290),
                 (-110, b - 290)], 7.0, "#A8323A")   # a heartbeat line: the medical sign, no protected emblem
    B(p, c, x, 160, 240, b - 380, b - 230, "#1A1824")
    for dx in (-330, 330):
        El(p, c, x, dx, b - 70, 74, 62, INK)
        Ci(p, c, x, dx, b - 62, 58, "#141018")
        Ci(p, c, x, dx, b - 62, 28, "#5A5666")
    B(p, c, x, 160, 300, b - 424, b - 400, "#2A2632", r=4)


def a_ambulance(p, x, b, c, tau):
    q = 0.5 + 0.5 * math.sin(math.tau * tau / 1.6)
    for dx, col, a in ((190, (1.0, 0.2, 0.15), q), (270, (0.25, 0.4, 1.0), 1 - q)):
        p.poly(rr(c.X(x, dx) - 22, b - 434, 44, 14, 5), np.clip(np.array(col) * (0.5 + 0.5 * a), 0, 1))
        p.glow(c.X(x, dx), b - 428, 120, 60, np.array(col, np.float32), 0.45 * a ** 1.5, )


def m_ambulance(x, b, c):
    return {"ambulance": mark("stand", x, c, -580, f=c.s)}


def d_bus_stop(p, x, b, c):
    B(p, c, x, -200, 200, b - 446, b - 424, "#1E1A26", "#6A6080")
    for dx in (-196, 190):
        B(p, c, x, dx, dx + 8, b - 424, b, "#1E1A26")
    B(p, c, x, -188, 188, b - 420, b - 60, "#8A8AA8", a=0.13)
    B(p, c, x, -188, 188, b - 64, b - 58, "#2A2632")
    B(p, c, x, -150, 150, b - 104, b - 94, "#2A2632", "#6A6080")
    for dx in (-140, 130):
        B(p, c, x, dx, dx + 8, b - 94, b, "#1E1A26")
    B(p, c, x, 236, 242, b - 420, b, "#1E1A26")
    Ci(p, c, x, 239, b - 430, 26, "#2E3A5A")
    B(p, c, x, -170, -60, b - 380, b - 200, "#C8A070" if c.lit and c.night else "#3A3446", a=0.85)


def g_bus_stop(p, x, b, c):
    if c.lit and c.night:
        G(p, c, x, -115, b - 290, 90, 100, hexc("#FFC383") * 0.6, 0.28)
        G(p, c, x, 0, b - 420, 200, 30, PAL["lamp"], 0.25)


def m_bus_stop(x, b, c):
    return {"bus_stop": mark("sit", x, c, -60, seat=b - 104, f=c.s), "bus_stop_2": mark("stand", x, c, 110, f=c.s)}


def d_bench(p, x, b, c):
    dark = "#150F1A"
    B(p, c, x, -120, 120, b - 64, b - 54, dark, "#7A6068")
    B(p, c, x, -120, 120, b - 120, b - 111, dark)
    for dx in (-110, 100):
        B(p, c, x, dx, dx + 9, b - 120, b, dark)
    if c.snow:
        B(p, c, x, -118, 118, b - 70, b - 62, "#D8D4E4", a=0.8)


def m_bench(x, b, c):
    return {"bench": mark("sit", x, c, -95, seat=b - 64, f=c.s), "bench_2": mark("sit", x, c, 95, seat=b - 64, f=-c.s)}


def d_fence(p, x, b, c):
    col = "#2A2230"
    for dx in np.arange(-210, 215, 30):
        P(p, c, x, [(dx - 9, b), (dx - 9, b - 112), (dx, b - 126), (dx + 9, b - 112), (dx + 9, b)], col)
    for y in (b - 92, b - 40):
        B(p, c, x, -220, 220, y, y + 9, col)
    Lit(p, c, x, -220, 220, b - 93, "#5A4A60", 0.6, 2)
    if c.snow:
        B(p, c, x, -220, 220, b - 97, b - 92, "#D8D4E4", a=0.8)


def d_street_lamp(p, x, b, c):
    pass   # (the place draws its lamps: tools/silhouette_places.Outdoor's LAMPS)


def m_street_lamp(x, b, c):
    return {"lamp": mark("stand", x, c, -85, f=c.s)}


def d_bin(p, x, b, c):
    B(p, c, x, -36, 36, b - 110, b, "#1E1A24", r=6)
    B(p, c, x, -40, 40, b - 118, b - 106, "#2A2632", "#6A6080", r=4)
    for dx in (-18, 0, 18):
        B(p, c, x, dx - 2, dx + 2, b - 96, b - 14, "#16121C")


def d_mailbox(p, x, b, c):
    B(p, c, x, -6, 6, b - 40, b, "#1E1A24")
    B(p, c, x, -34, 34, b - 160, b - 36, "#7A2A30", r=14)
    B(p, c, x, -20, 20, b - 120, b - 114, INK)


def d_grave(p, x, b, c):
    p.poly(ell(c.X(x, -10), b + 2, 130, 20, 48), c.col("#1E2A22" if not c.snow else "#B8B4C8"))
    stone = "#5A5664"
    B(p, c, x, -62, 62, b - 170, b - 8, stone)
    top = ell(x, b - 170, 62, 50, 48)
    p.poly(np.vstack([top[24:], top[:1]]), c.col(stone))   # the rounded top (y grows downwards: the upper half)
    Tb(p, c, x, [(-60, b - 172), (-40, b - 205), (0, b - 220), (40, b - 205), (60, b - 172)], 3.0, "#9A96A8", a=0.7)
    for k in range(3):
        B(p, c, x, -34, 34 - k * 12, b - 150 + k * 22, b - 146 + k * 22, "#3A3644", a=0.8)
    for k, dx in enumerate((-30, -10, 12)):
        Tb(p, c, x, [(dx - 40, b - 2), (dx - 50, b - 40)], 2.0, "#3E5A3A")
        Ci(p, c, x, dx - 50, b - 44, 8, ("#C8566A", "#E59A7A", "#D9C2B0")[k])


def m_grave(x, b, c):
    return {"grave": mark("kneel", x, c, -200, f=c.s, bow=True, use=["kneeling"]),
            "grave_2": mark("stand", x, c, -260, f=c.s)}


def d_campfire(p, x, b, c):
    for dx in (-230, 230):
        B(p, c, x, dx - 70, dx + 70, b - 52, b - 6, "#3A2620", r=20)
        El(p, c, x, dx + 70, b - 29, 8, 22, "#6A4A38")
    r = rng("stones", c.seed)
    for k in range(9):
        dx = -80 + k * 20
        El(p, c, x, dx, b - 8, r.uniform(10, 16), r.uniform(7, 11), "#3A3446")
    Tb(p, c, x, [(-60, b - 10), (50, b - 34)], 13.0, "#2E1E1A")
    Tb(p, c, x, [(-50, b - 34), (60, b - 10)], 13.0, "#3A2620")


def a_campfire(p, x, b, c, tau):
    FX.flames(p, x, b - 16, 120, 140, tau, seed=hash(c.seed) % 103)


def g_campfire(p, x, b, c):
    G(p, c, x, 0, b - 70, 160, 120, FX.FIRE_LIGHT, 0.55)
    G(p, c, x, 0, b - 40, 600, 300, FX.FIRE_LIGHT * 0.6, 0.15)
    G(p, c, x, 0, b, 420, 26, FX.FIRE_LIGHT, 0.35)


def m_campfire(x, b, c):
    return {"campfire": mark("sit", x, c, -230, seat=b - 52, f=c.s), "campfire_2": mark("sit", x, c, 230, seat=b - 52, f=-c.s)}


def d_rock(p, x, b, c):
    P(p, c, x, [(-120, b), (-112, b - 60), (-70, b - 104), (10, b - 116), (80, b - 96), (118, b - 50), (124, b)], "#3A3446",
      smooth=True)
    Tb(p, c, x, [(-90, b - 82), (-50, b - 108), (10, b - 117), (70, b - 100)], 3.0, "#7A7090", a=0.6)
    if c.snow:
        P(p, c, x, [(-80, b - 96), (-40, b - 112), (10, b - 120), (70, b - 102), (40, b - 98), (-40, b - 100)], "#D8D4E4",
          a=0.8, smooth=True)


def m_rock(x, b, c):
    return {"rock": mark("sit", x, c, -10, seat=b - 108, f=c.s)}


def d_railing(p, x, b, c):
    col = "#1C1624"
    B(p, c, x, -800, 800, b - 150, b - 136, col, "#6A5878")
    B(p, c, x, -800, 800, b - 24, b - 12, col)
    for dx in np.arange(-790, 800, 52):
        Tb(p, c, x, [(dx, b - 136), (dx, b - 24)], 5.0, col)
    for dx in np.arange(-800, 801, 400):
        B(p, c, x, dx - 14, dx + 14, b - 170, b, "#16101C")
    if c.snow:
        B(p, c, x, -800, 800, b - 156, b - 150, "#D8D4E4", a=0.8)


def d_scaffold(p, x, b, c):
    col = "#3A3442"
    for dx in (-210, -60, 90, 220):
        B(p, c, x, dx - 4, dx + 4, b - 640, b, col)
    for y in (b - 220, b - 430, b - 640):
        B(p, c, x, -220, 230, y, y + 7, col)
        B(p, c, x, -215, 225, y - 12, y, "#6A5040", "#9A7A60", ea=0.6)
    for (d0, y0), (d1, y1) in (((-210, b), (-60, b - 220)), ((-60, b - 220), (90, b - 430)), ((90, b - 430), (220, b - 640))):
        Tb(p, c, x, [(d0, y0), (d1, y1)], 4.0, col, a=0.9)
    for y in np.arange(b - 20, b - 220, -32):
        B(p, c, x, 150, 190, y - 3, y + 3, col)
    for dx in (150, 190):
        B(p, c, x, dx - 3, dx + 3, b - 230, b, col)


def d_cement_mixer(p, x, b, c):
    B(p, c, x, -90, 90, b - 90, b - 70, "#2A2632")
    for dx in (-70, 70):
        Ci(p, c, x, dx, b - 30, 30, INK)
        Ci(p, c, x, dx, b - 30, 12, "#4A4656")
    Tb(p, c, x, [(0, b - 90), (-10, b - 150)], 12.0, "#2A2632")
    P(p, c, x, [(-80, b - 160), (40, b - 250), (100, b - 210), (90, b - 150), (-10, b - 110), (-70, b - 120)], "#B0643A",
      smooth=True, k=0.85)
    El(p, c, x, 74, b - 236, 24, 34, INK)


def d_cones(p, x, b, c):
    for dx, h in ((-55, 90), (10, 78), (65, 90)):
        P(p, c, x, [(dx - 30, b - 6), (dx - 8, b - h), (dx + 8, b - h), (dx + 30, b - 6)], "#C8643A", k=0.85)
        B(p, c, x, dx - 18, dx + 18, b - h * 0.62, b - h * 0.48, "#E8E0D8", a=0.85)
        B(p, c, x, dx - 36, dx + 36, b - 8, b, "#2A2232")


def d_bricks(p, x, b, c):
    B(p, c, x, -105, 105, b - 20, b, "#5A4636")
    for row in range(4):
        for k in range(5):
            dx = -100 + k * 40 + (20 if row % 2 else 0)
            if dx + 38 > 105:
                continue
            B(p, c, x, dx, dx + 38, b - 20 - (row + 1) * 25, b - 20 - row * 25 - 3, "#7A3E30", k=0.9)


# === small things (b: the top of what they stand on) =======================================================================
def d_phone(p, x, b, c):
    B(p, c, x, -22, 22, b - 6, b, "#141018", r=2)
    if c.lit:
        B(p, c, x, -18, 18, b - 7, b - 5, PAL["screen"], a=0.9)


def g_phone(p, x, b, c):
    if c.lit:
        G(p, c, x, 0, b - 6, 40, 16, PAL["screen"], 0.25)


def d_letters(p, x, b, c):
    for k, (dx, a) in enumerate(((-28, -0.05), (-4, 0.08), (22, -0.02))):
        cx, cy = c.X(x, dx), b - 5 - k * 3
        ang = a * c.s
        p.poly(S._slab(cx, cy, 60, 9, ang), c.col("#D9D0C6" if k != 1 else "#E8DFD4"))
        if k == 1:
            p.poly(S._slab(cx + math.cos(ang) * 19 * c.s, cy + math.sin(ang) * 19 * c.s - 1, 14, 6, ang), c.col("#C8473A"), 0.9)


def d_money(p, x, b, c):
    for k, dx in enumerate((-30, 6)):
        for j in range(4 - k):
            B(p, c, x, dx, dx + 34, b - 6 - j * 6, b - j * 6, ("#6E8A6A", "#7E9A78")[(j + k) % 2])
        B(p, c, x, dx + 13, dx + 21, b - 6 * (4 - k), b, "#C8B890", a=0.8)


def d_bottle(p, x, b, c):
    B(p, c, x, -20, 4, b - 70, b, "#2E4A36", r=6, a=0.9)
    B(p, c, x, -13, -3, b - 96, b - 66, "#2E4A36", a=0.9)
    Tb(p, c, x, [(-6, b - 60), (-6, b - 12)], 2.5, "#9AC0A0", a=0.5)
    B(p, c, x, 14, 36, b - 34, b, "#C9C0D6", a=0.40)
    B(p, c, x, 16, 34, b - 18, b - 2, "#C9853A", a=0.70)


def _glass(p, c, x, dx, b, wine="#7A1E2E"):
    P(p, c, x, [(dx - 13, b - 70), (dx + 13, b - 70), (dx + 9, b - 44), (dx - 9, b - 44)], "#C9C0D6", a=0.4)
    P(p, c, x, [(dx - 11, b - 60), (dx + 11, b - 60), (dx + 8, b - 46), (dx - 8, b - 46)], wine, a=0.8)
    B(p, c, x, dx - 1.5, dx + 1.5, b - 44, b - 4, "#C9C0D6", a=0.5)
    El(p, c, x, dx, b - 3, 10, 3, "#C9C0D6", a=0.5)


def d_wine(p, x, b, c):
    B(p, c, x, -12, 12, b - 80, b, "#2A0E16", r=5, a=0.95)
    B(p, c, x, -5, 5, b - 110, b - 76, "#2A0E16")
    B(p, c, x, -12, 12, b - 50, b - 30, "#C8B8A0", a=0.7)
    _glass(p, c, x, -40, b)
    _glass(p, c, x, 40, b)


def d_candles(p, x, b, c):
    for dx, h in ((-15, 60), (15, 46)):
        B(p, c, x, dx - 6, dx + 6, b - h, b, "#E8DFD0", r=2)
        B(p, c, x, dx - 0.8, dx + 0.8, b - h - 6, b - h, INK)
    El(p, c, x, 0, b - 2, 30, 4, "#8A7A60")


def a_candles(p, x, b, c, tau):
    for dx, h in ((-15, 60), (15, 46)):
        FX.candle_flame(p, c.X(x, dx), b - h - 4, tau, seed=dx)


def g_candles(p, x, b, c):
    for dx, h in ((-15, 60), (15, 46)):
        G(p, c, x, dx, b - h - 10, 30, 28, PAL["lamp"], 0.28)
    G(p, c, x, 0, b - 60, 200, 140, FX.FIRE_LIGHT * 0.6, 0.07)


def d_flowers(p, x, b, c):
    B(p, c, x, -14, 14, b - 44, b, "#4A5A7A", r=6, a=0.8)
    for k, (dx, h) in enumerate(((-16, 92), (2, 104), (18, 88), (-4, 80))):
        Tb(p, c, x, [(0, b - 40), (dx, b - h)], 2.0, "#3E5A3A")
        Ci(p, c, x, dx, b - h, 9, ("#C8566A", "#E59A7A", "#D9C2B0", "#B84A5E")[k])


def d_laptop(p, x, b, c):
    B(p, c, x, -45, 45, b - 6, b, "#24202E", r=2)
    P(p, c, x, [(-44, b - 6), (-30, b - 70), (-22, b - 70), (-36, b - 6)], "#24202E")
    P(p, c, x, [(-40, b - 9), (-28, b - 65), (-25, b - 65), (-37, b - 9)], PAL["screen"] * (1.0 if c.night else 0.6), a=0.85)


def g_laptop(p, x, b, c):
    G(p, c, x, -20, b - 40, 60, 50, PAL["screen"], 0.25 if c.night else 0.10)


def d_books(p, x, b, c):
    for k, (w, col) in enumerate(((70, "#3B2A43"), (64, "#2E3446"), (68, "#4A2E3A"), (58, "#35283E"))):
        dx = -w / 2 + (k % 2) * 4
        B(p, c, x, dx, dx + w, b - 14 * (k + 1), b - 14 * k, col)
        B(p, c, x, dx, dx + w, b - 14 * (k + 1), b - 14 * (k + 1) + 1.5, "#8A6A72", a=0.7)


def d_mug(p, x, b, c):
    B(p, c, x, -13, 13, b - 30, b, "#E6DCD0", r=4, a=0.9)
    Tb(p, c, x, [(13, b - 24), (21, b - 18), (13, b - 10)], 3.0, "#E6DCD0", a=0.9)


def d_documents(p, x, b, c):
    for k in range(5):
        B(p, c, x, -40 + (k % 2) * 3, 40 + (k % 2) * 3, b - 4 - k * 4, b - k * 4, PAPER if k % 2 else "#D8D0C4")
    B(p, c, x, -10, 10, b - 24, b - 18, METAL_LIT)


def d_gift(p, x, b, c):
    B(p, c, x, -26, 26, b - 42, b, "#8A3A4E")
    B(p, c, x, -4, 4, b - 42, b, "#E8D8C0")
    B(p, c, x, -28, 28, b - 46, b - 39, "#A84A5E")
    for s in (-1, 1):
        p.poly(S.rell(c.X(x, s * 10), b - 50, 10, 5, s * 0.5), c.col("#E8D8C0"))


def d_plate(p, x, b, c):
    El(p, c, x, 0, b - 3, 34, 5, "#D8D0C6")
    El(p, c, x, -4, b - 9, 18, 7, "#7A4A30")
    Ci(p, c, x, 12, b - 10, 5, "#4A7A3A")


def d_photo_frame(p, x, b, c):
    P(p, c, x, [(-20, b), (-16, b - 52), (20, b - 52), (20, b)], INK)
    B(p, c, x, -14, 15, b - 47, b - 5, "#5A4A6A")
    Ci(p, c, x, -4, b - 32, 6, "#2A2030")
    Ci(p, c, x, 7, b - 30, 6, "#2A2030")


def d_trophy(p, x, b, c):
    gold = "#C9A24A"
    P(p, c, x, [(-22, b - 76), (22, b - 76), (12, b - 46), (-12, b - 46)], gold)
    B(p, c, x, -3, 3, b - 46, b - 24, gold)
    B(p, c, x, -16, 16, b - 24, b, "#3A2E26")
    B(p, c, x, -22, 22, b - 79, b - 75, "#FFE0A0", a=0.8)


def d_suitcase(p, x, b, c):
    B(p, c, x, -42, 42, b - 120, b - 8, "#3A3446", r=8)
    B(p, c, x, -42, 42, b - 121, b - 117, "#7A7090", a=0.8)
    Tb(p, c, x, [(-14, b - 120), (-14, b - 150), (14, b - 150), (14, b - 120)], 4.0, METAL_LIT)
    for dx in (-28, 28):
        Ci(p, c, x, dx, b - 5, 6, METAL)


def d_bags(p, x, b, c):
    for dx, col, h in ((-28, "#B89A78", 80), (28, "#D8D0C6", 66)):
        B(p, c, x, dx - 26, dx + 26, b - h, b, col, r=3, k=0.85)
        Tb(p, c, x, [(dx - 12, b - h), (dx, b - h - 22), (dx + 12, b - h)], 2.5, "#2A2026")


def d_boxes(p, x, b, c):
    for dx, y0, w, h in ((-80, b, 90, 80), (12, b, 76, 70), (-60, b - 80, 80, 64)):
        B(p, c, x, dx, dx + w, y0 - h, y0, "#7A5C48", r=2, k=0.9)
        B(p, c, x, dx, dx + w, y0 - h, y0 - h + 4, "#B08A6A", a=0.8)
        B(p, c, x, dx + w / 2 - 6, dx + w / 2 + 6, y0 - h, y0, "#9A7A62", a=0.5)


def d_guitar(p, x, b, c):
    pts = [(-30, b - 10), (-34, b - 50), (-20, b - 80), (-28, b - 108), (-14, b - 140), (14, b - 136), (22, b - 106),
           (16, b - 76), (30, b - 48), (26, b - 10)]
    P(p, c, x, pts, "#6A3A28", smooth=True)
    Ci(p, c, x, -2, b - 84, 9, INK)
    Tb(p, c, x, [(0, b - 136), (14, b - 290)], 9.0, "#2A1A16")
    B(p, c, x, 6, 26, b - 320, b - 286, "#2A1A16", r=3)


def d_mess(p, x, b, c):
    r = rng("mess", c.seed)
    P(p, c, x, [(-130, b), (-110, b - 30), (-60, b - 44), (-10, b - 30), (10, b)], "#3A3450", smooth=True)
    Tb(p, c, x, [(30, b - 10), (90, b - 18)], 13.0, "#2E4A36", w1=7.0)
    for k in range(6):
        dx = r.uniform(-120, 120)
        Ci(p, c, x, dx, b - 7, r.uniform(7, 11), PAPER if k % 2 else "#C8C0B4")


# --- the registry's access --------------------------------------------------------------------------------------------------
class Thing:
    """One thing in a place: what it is (PROPS), where (x, b), which way it faces, its options."""

    def __init__(self, name: str, x: float, b: float, ctx: Ctx):
        if name not in PROPS:
            raise ValueError(f"no thing called {name!r}")
        self.name, self.x, self.b, self.c = name, float(x), float(b), ctx
        group, about, width, layer, where, tall, surface = PROPS[name]
        self.group, self.about, self.width, self.layer, self.where, self.tall, self.surface_spec = \
            group, about, width, layer, where, tall, surface
        g = globals()
        self._d, self._f, self._g = g.get("d_" + name), g.get("f_" + name), g.get("g_" + name)
        self._a, self._m = g.get("a_" + name), g.get("m_" + name)

    def draw(self, p: Paint):
        if self._d:
            self._d(p, self.x, self.b, self.c)

    def front(self, p: Paint):
        if self._f:
            self._f(p, self.x, self.b, self.c)

    def glow(self, p: Paint):
        if self._g:
            self._g(p, self.x, self.b, self.c)

    @property
    def moves(self) -> bool:
        return self._a is not None

    def animate(self, p: Paint, tau: float):
        if self._a:
            self._a(p, self.x, self.b, self.c, tau)

    def marks(self) -> dict:
        return self._m(self.x, self.b, self.c) if self._m else {}

    def surface(self):
        """Where small things can stand on it: (x0, x1, y) in the world, or None."""
        if not self.surface_spec:
            return None
        d0, d1, h = self.surface_spec
        xa, xb = sorted((self.c.X(self.x, d0), self.c.X(self.x, d1)))
        y = self.b - HANG.get(self.name, 0) if self.layer == "wall" else self.b - h
        return (xa, xb, y)
