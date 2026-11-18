"""
The silhouette look's sets (tools/silhouette.py draws them): the desk room at dusk, a rainy street at night and a hospital
room at night. The desk room is laid out from the owner's reference GIF (its 720 x 900 view, G() below), with its 5-second scene "the deadline": the figure typing with tired eyes,
the flip clock turning 21:59 -> 22:00, the typing stopping, the head turning to camera with wide eyes, the label, the city's
windows switching on in three clusters, a blink, and a last second held completely still.

A scene draws the same set in any frame size: the room is wider than the reference, and each frame's shape gets its own
resting framing (a 16:9 film shows more of the room; the 9:16 short version frames it as the reference does).
"""

import math

import numpy as np
import cv2
from PIL import Image, ImageDraw

import silhouette as S
from silhouette import PAL, Camera, Dynamic, Eyes, Paint, Static, ell, hexc, rect, rr, smooth, spline, tube, window


def G(x, y):
    """A point of the reference GIF (its 720 x 900 view) in world units."""
    return (330 + (x - 35) * 1.4, 120 + (y - 100) * 1.4)


def g(v):
    """A length of the reference GIF in world units."""
    return v * 1.4


def GR(x0, y0, x1, y1):
    """A rectangle of the reference GIF (corners) as world points."""
    (a, b), (c, d) = G(x0, y0), G(x1, y1)
    return rect(a, b, c - a, d - b)


def GRR(x0, y0, x1, y1, r):
    (a, b), (c, d) = G(x0, y0), G(x1, y1)
    return rr(a, b, c - a, d - b, g(r))


def gradient(stops):
    """A colour function for Paint.poly: world y -> colour, through (world y, '#hex') stops."""
    ys = np.array([s[0] for s in stops], np.float32)
    cols = np.stack([hexc(s[1]) for s in stops])

    def make(p: Paint):
        def f(px, py):
            wy = p.wy(py)
            return np.stack([np.interp(wy, ys, cols[:, c]) for c in range(3)], -1).astype(np.float32)
        return f
    return make


def rng(*seed):
    import hashlib
    return np.random.default_rng(int.from_bytes(hashlib.md5(repr(seed).encode()).digest()[:8], "little"))


# --- the desk room -----------------------------------------------------------------------------------------------------------
SKY = gradient([(G(0, 105)[1], "#2F2A57"), (G(0, 225)[1], "#463566"), (G(0, 300)[1], "#7A4E7A"), (G(0, 360)[1], "#B3687C"),
                (G(0, 412)[1], "#EE8F67"), (G(0, 452)[1], "#FFD7A0"), (G(0, 520)[1], "#FFD7A0")])
SUN = G(108, 452)
PANES = [(45, 110, 236, 286), (244, 110, 435, 286), (45, 294, 236, 525), (244, 294, 435, 525)]
WIN_OUT = (35, 100, 445, 535)
LIGHT_FROM = (-1.0, -0.35)       # the rim light's direction (towards the low sun, behind on the left)
FRAMINGS = {  # each frame shape's resting view: (world centre, how much of the room's height it shows)
    "wide": (G(430, 450), g(700)),     # 16:9: from above the window to the chair, the room's left and right walls too
    "tall": (G(352, 476), g(650)),     # 9:16: 650 of the reference's 720 across (its window to its clock), taller
}
FOCUS = G(318, 515)              # where the slow push heads (between his head and the clock)


def framing(size):
    W, H = size
    (cx, cy), tall_world = FRAMINGS["tall" if H > W else "wide"]
    z = W / tall_world if H > W else H / tall_world
    return cx, cy, z


def _city(p: Paint, base_y, x0, x1, tops, widths, color, seed, spire=None):
    r = rng("city", seed)
    x, shapes = x0, []
    while x < x1:
        w = g(r.uniform(*widths))
        top = G(0, r.uniform(*tops))[1]
        shapes.append(rect(x, top, w + 1, base_y - top + g(40)))
        if r.random() < 0.3:  # a step on the roof
            sw = w * r.uniform(0.3, 0.6)
            shapes.append(rect(x + (w - sw) / 2, top - g(r.uniform(6, 14)), sw, g(20)))
        x += w
    if spire:
        sx, top = spire
        cx = G(sx, 0)[0]
        for half, y_top in ((11, 382), (7, 352), (3.5, 330)):
            shapes.append(rect(cx - g(half), G(0, y_top)[1], g(2 * half), base_y - G(0, y_top)[1] + g(40)))
        shapes.append(rect(cx - g(0.7), G(0, top)[1], g(1.4), G(0, 330)[1] - G(0, top)[1] + 2))
    p.poly(None, color, polys=shapes)


class DeskRoom:
    """The desk room, in one frame size and one light (dusk is the reference GIF's; night, dawn and day in the same
    palette's family; rain on the window): its layers, made once; draw(index, st) draws a moment, frame(t) the GIF's
    5-second deadline scene."""

    def __init__(self, size, label: str = "DEADLINE", seconds: float = 5.0, light: str = "dusk", rain: bool = False):
        from silhouette_places import LIGHTS

        self.size, self.label, self.seconds = size, label, seconds
        self.light, self.rain, self.L = light, bool(rain), LIGHTS[light]
        self.lamp_on = bool(self.L["lamp"] or self.rain)
        W, H = size
        self.tall = H > W
        self.cam = Camera(size, *framing(size))
        self.k = self.cam.rest[2]             # px per world unit at rest
        self.finish = S.Finish(size)
        self.windows = self._windows()
        cam = self.cam
        self.static_back = [
            Static(cam, 0.10, self._sky, blur=1.6),
            Static(cam, 0.20, self._far_city, blur=1.4),
        ]
        versions = range(4) if light == "dusk" else ([3] if light == "night" else [-1])
        self.near = {n: Static(cam, 0.30, lambda p, n=n: self._near_city(p, n), blur=0.8) for n in versions}
        self.static_mid = [
            Static(cam, 0.62, self._wall),
            Static(cam, 0.62, self._window_bloom, add=True),
            Static(cam, 0.70, self._lamp),
            Static(cam, 0.80, self._laptop),
        ]
        self.figure = Dynamic(cam, 0.80)
        self.desk = Static(cam, 0.80, self._desk)
        self.clock = Dynamic(cam, 0.80)
        self.light = ([Static(cam, 0.70, self._cone, add=True, blur=2.0)] if self.lamp_on else []) + [
            Static(cam, 0.80, self._desk_light, add=True)]
        self.wet = Dynamic(cam, 0.10, add=True) if self.rain else None
        self.dust = Dynamic(cam, 0.70, add=True)
        self.plant = Static(cam, 1.70, self._plant, blur=6.0 * self.k,
                            rim_light=(LIGHT_FROM[0] * 3 * self.k, LIGHT_FROM[1] * 3 * self.k, PAL["rim"], 4.0, 0.3,
                                       0.75 if self.tall else 0.45))
        self.pages = {}
        self.dust_seed = self._dust_seed()
        self.label_px = int(round((46 if not self.tall else 54) * (min(W, H) / 1080)))

    # --- the static layers ----------------------------------------------------------------------------------------------
    def _sky(self, p: Paint):
        if self.light != "dusk" or self.rain:
            from silhouette_places import sky
            sky(p, self.L, G(-60, 0)[0], G(560, 0)[0], G(0, 105)[1], G(0, 452)[1], SUN[0], self.rain, "desk room")
            return
        x0, y0 = G(-60, 60)
        x1, y1 = G(560, 560)
        p.poly(rect(x0, y0, x1 - x0, y1 - y0), SKY(p))
        # the low sun behind the skyline: its bloom and faint rays
        p.glow(*SUN, g(70), g(30), (1.0, 0.78, 0.52), 0.55)
        p.glow(*SUN, g(220), g(80), (1.0, 0.60, 0.44), 0.22)
        p.circle(*SUN, g(11), hexc("#FFE9C8"))
        for k, a in enumerate(np.linspace(-2.9, -0.25, 9)):
            L = g(150 + 40 * (k % 3))
            w = g(8 + 5 * (k % 3))
            tip = (SUN[0] + math.cos(a) * L, SUN[1] + math.sin(a) * L)
            nx, ny = -math.sin(a), math.cos(a)
            p.poly(np.array([SUN, (tip[0] + nx * w, tip[1] + ny * w), (tip[0] - nx * w, tip[1] - ny * w)]),
                   hexc("#FFD9B0"), 0.06, soft=g(6), add=True)
        # thin streaks of cloud, a few stars
        for cx, cy, rx, ry, a in ((235, 180, 185, 3.6, 0.55), (335, 233, 112, 3.0, 0.5), (120, 207, 75, 2.2, 0.35),
                                  (300, 140, 60, 1.6, 0.25)):
            p.poly(ell(*G(cx, cy), g(rx), g(ry), 96), hexc("#C996AE"), a, soft=g(1.4))
        r = rng("stars")
        for _ in range(16):
            x, y = r.uniform(50, 430), r.uniform(115, 300)
            p.circle(*G(x, y), g(r.uniform(0.7, 1.15)), PAL["label"], float(r.uniform(0.45, 0.9)))

    def _far_city(self, p: Paint):
        base = G(0, 475)[1]
        _city(p, base, G(-60, 0)[0], G(560, 0)[0], (420, 452), (16, 38), hexc(self.L["far"]), "far", spire=(348, 300))
        # haze over the far skyline: it melts into the horizon
        x0, y0 = G(-60, 418)
        x1, y1 = G(560, 480)
        haze, alpha = self.L["haze"]
        p.poly(rect(x0, y0, x1 - x0, y1 - y0), lambda px, py: np.broadcast_to(hexc(haze), px.shape + (3,)), alpha,
               soft=g(10))

    def _windows(self):
        """The near skyline's buildings and their windows: (lit from the start, cluster 1, 2, 3)."""
        r = rng("near")
        base = G(0, 535)[1]
        x, blocks, wins = G(-60, 0)[0], [], []
        while x < G(560, 0)[0]:
            w = g(r.uniform(28, 62))
            top = G(0, r.uniform(450, 498))[1]
            blocks.append(rect(x, top, w + 1, base - top + g(40)))
            for row in range(6):
                for col in range(max(1, int(w / g(11)))):
                    wx, wy = x + g(5) + col * g(10), top + g(7) + row * g(10)
                    if wy > base - g(4) or wx > x + w - g(6):
                        continue
                    roll = r.random()
                    state = 0 if roll < 0.20 else (1 + int((wx - G(-60, 0)[0]) / (g(620) / 3))) if roll < 0.40 else None
                    if state is not None:
                        wins.append((wx, wy, min(3, state)))
            x += w
        return blocks, wins

    def _near_city(self, p: Paint, lit: int):
        blocks, wins = self.windows
        p.poly(None, hexc(self.L["near"]), polys=blocks)
        for wx, wy, state in wins:
            if state <= lit:
                p.poly(rect(wx, wy, g(4), g(5)), hexc(self.L["win"]), 0.92)

    def _wall(self, p: Paint):
        cx, cy = G(240, 330)

        def wall(px, py):
            d = np.sqrt(((p.wx(px) - cx) / g(470)) ** 2 + ((p.wy(py) - cy) / g(430)) ** 2)
            t = np.clip(d, 0, 1)[..., None] ** 0.75
            return near * (1 - t) + far * t
        near, far = (PAL["wall_near"], PAL["wall_far"]) if self.light == "dusk" else (hexc(self.L["wall"][0]),
                                                                                      hexc(self.L["wall"][1]))
        x0, y0 = G(-900, -900)
        x1, y1 = G(1700, 870)
        p.poly(rect(x0, y0, x1 - x0, y1 - y0), wall)
        # the floor, a little darker, under a soft line
        fx0, fy0 = G(-900, 870)
        fx1, fy1 = G(1700, 1600)
        p.poly(rect(fx0, fy0, fx1 - fx0, fy1 - fy0), hexc(self.L["floor"]))
        # the window: frame, sill, mullions (the panes are cut out, so the sky shows)
        p.poly(GR(*WIN_OUT), hexc("#1A1120"))
        for pane in PANES:
            p.cut(GR(*pane))
        p.poly(GR(22, 525, 458, 531), hexc("#6A5060"))
        p.poly(GR(22, 531, 458, 541), hexc("#2A1C2C"))
        # a small picture on the wall: a frame, a mat and two mountains
        p.poly(GRR(632, 150, 703, 242, 1.5), PAL["frame"])
        p.poly(GR(638, 156, 697, 236), hexc("#33263C"))
        p.poly(np.array([G(640, 234), G(660, 200), G(675, 218), G(684, 206), G(696, 234)]), hexc("#4B3A55"))
        if not self.tall:  # the wider room: a door's edge on the left, a shelf with books and a second picture on the right
            p.poly(GR(-170, 40, -80, 870), hexc("#1E1424"))
            p.poly(GR(-82, 40, -78, 870), hexc("#5A3E52"), 0.8)
            p.poly(GRR(-55, 205, 15, 300, 2), hexc("#2A1D27"))
            for nx, ny, nw, nh, a in ((-48, 214, 26, 30, -0.05), (-16, 220, 22, 26, 0.06), (-44, 254, 20, 34, 0.04),
                                      (-14, 258, 24, 28, -0.07)):
                c = np.array(G(nx + nw / 2, ny + nh / 2))
                rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
                p.poly((GR(nx, ny, nx + nw, ny + nh) - c) @ rot.T + c, hexc("#B9A8A6"), 0.55)
                p.circle(*G(nx + nw / 2, ny + 3), g(1.6), PAL["rim"], 0.8)
            p.poly(GRR(790, 170, 858, 252, 1.5), PAL["frame"])
            p.poly(GR(796, 176, 852, 246), hexc("#3A2B40"))
            p.circle(*G(824, 205), g(9), hexc("#6C4A5E"))
            p.poly(GR(760, 372, 960, 380), hexc("#2B1D2D"))
            p.poly(GR(760, 370, 960, 372.5), hexc("#7A5C68"))
            r = rng("books")
            x = 770
            for k in range(7):
                w, h = r.uniform(9, 15), r.uniform(42, 62)
                col = hexc(["#3B2A43", "#2E3446", "#4A2E3A", "#35283E", "#283545", "#41303F", "#2F2638"][k])
                tilt = 0 if k != 5 else -0.18
                pts = GR(x, 370 - h, x + w, 370)
                if tilt:
                    c = np.array(G(x + w, 370))
                    rot = np.array([[math.cos(tilt), -math.sin(tilt)], [math.sin(tilt), math.cos(tilt)]])
                    pts = (pts - c) @ rot.T + c
                p.poly(pts, col)
                p.poly(GR(x, 370 - h, x + w, 370 - h + 1.2), hexc("#8A6A72"), 0.7)
                x += w + (1.5 if k != 4 else 12)
            p.poly(GRR(905, 340, 930, 370, 3), hexc("#2A1D2E"))
            for a in (-0.5, -0.1, 0.35):
                tip = G(917 + 26 * math.sin(a), 340 - 26 * math.cos(a))
                p.poly(tube([G(917, 342), tip], g(5), g(1.5)), hexc("#1F2A2A"))

    def _window_bloom(self, p: Paint):
        # warm light round the window, as if the low sun spilled through it (the light's own colour in other lights)
        spill = self.L["spill"]
        k = 0.5 if self.rain else 1.0
        p.glow(*G(150, 470), g(300), g(200), spill, 0.16 * k)
        p.glow(*G(240, 330), g(330), g(300), tuple(c * 0.55 for c in spill), 0.12 * k)

    def _lamp(self, p: Paint):
        cx = G(565, 0)[0]
        p.poly(rect(cx - g(1.1), G(0, -700)[1], g(2.2), G(0, 236)[1] - G(0, -700)[1]), hexc("#140D17"))
        p.poly(GR(558.5, 231, 571.5, 240), hexc("#1E1422"))
        shade = spline([G(553, 239), G(577, 239), G(612, 270), G(628, 297), G(565, 301), G(502, 297), G(518, 270)], True, 8)
        p.poly(shade, PAL["shade"])
        p.poly(spline([G(577, 241), G(612, 271), G(626, 295), G(621, 296), G(604, 272), G(573, 243)], True, 6),
               hexc("#4A3346"), 0.8)  # the shade's lit edge
        p.poly(ell(*G(565, 297.5), g(61), g(5), 80), hexc("#FFF5E1") if self.lamp_on else hexc("#4A3A44"))  # the bulb

    def _cone(self, p: Paint):
        top_y, bot_y = G(0, 299)[1], G(0, 681)[1]

        def fall(px, py):
            u = np.clip((p.wy(py) - top_y) / (bot_y - top_y), 0, 1)[..., None]
            return PAL["lamp"] * (0.30 * (1 - u) ** 1.4 + 0.07)
        p.poly(np.array([G(505, 299), G(625, 299), G(712, 681), G(446, 681)]), fall, soft=g(9), add=True)
        p.poly(np.array([G(530, 299), G(600, 299), G(650, 681), G(495, 681)]), fall, 0.35, soft=g(14), add=True)
        p.glow(*G(565, 300), g(66), g(14), PAL["lamp"], 0.30)
        p.glow(*G(565, 296), g(120), g(55), PAL["lamp"] * 0.6, 0.12)

    def _desk_light(self, p: Paint):
        if self.lamp_on:
            p.glow(*G(578, 682), g(130), g(9), PAL["lamp"], 0.35)      # the pool of light on the desk
        p.glow(*G(392, 640), g(26), g(36), PAL["screen"], 0.22)       # the laptop's cool glow
        p.glow(*G(360, 655), g(40), g(26), PAL["screen"], 0.10)

    def _laptop(self, p: Paint):
        p.poly(GR(330, 672.5, 417, 677.5), hexc("#1B1320"))
        p.poly(tube([G(397.5, 598), G(412, 676)], g(2.6)), hexc("#D5E6FF"))

    def _desk(self, p: Paint):
        x_l, x_r = (-40, 735) if self.tall else (-60, 1060)
        p.poly(GR(x_l, 676.5, x_r, 683.5), hexc("#77606A"))
        p.poly(GR(x_l, 683.5, x_r, 706), lambda px, py: np.broadcast_to(hexc("#2C1F2F"), px.shape + (3,)))
        for lx in ((708,) if self.tall else (-40, 1035)):
            p.poly(GR(lx, 706, lx + 9, 872), hexc("#1C1320"))
        if not self.tall:  # a mug on the desk, in the lamp's light
            p.poly(GRR(735, 645, 760, 677, 3), hexc("#2B1F2F"))
            p.poly(GR(736, 645, 759, 648), hexc("#9A7A80"), 0.9)
            p.poly(tube([G(760, 653), G(769, 660), G(760, 668)], g(3)), hexc("#2B1F2F"))

    def _plant(self, p: Paint):
        """The out-of-focus plant in front of the lens: long dark leaves from the bottom-left corner."""
        W, H = self.size
        v = p.v
        base = ((-0.06 * W + S.MARGIN - v.ox) / v.z + v.cx, (1.0 * H + S.MARGIN - v.oy) / v.z + v.cy)
        span = (1.0 * W if self.tall else 0.62 * H) / v.z  # (narrow pointed leaves fanning up from the corner, as in the reference)
        for ang, length, width in ((-1.55, 0.45, 0.060), (-1.30, 0.62, 0.075), (-1.05, 0.58, 0.072), (-0.80, 0.55, 0.070),
                                   (-0.55, 0.50, 0.065)):
            L = span * length
            tip = (base[0] + math.cos(ang) * L, base[1] + math.sin(ang) * L)
            mid = ((base[0] + tip[0]) / 2 + math.sin(ang) * L * 0.08, (base[1] + tip[1]) / 2 - math.cos(ang) * L * 0.04)
            spine = spline([base, mid, tip], closed=False, k=16)
            tg = np.gradient(spine, axis=0)
            tg /= np.maximum(np.hypot(tg[:, 0], tg[:, 1]), 1e-9)[:, None]
            nrm = np.stack([-tg[:, 1], tg[:, 0]], 1)
            u = np.linspace(0, 1, len(spine))[:, None]
            wdt = span * width * np.sin(np.pi * np.clip(u * 0.92 + 0.04, 0, 1)) ** 0.8
            p.poly(np.vstack([spine + nrm * wdt, (spine - nrm * wdt)[::-1]]), hexc("#0C080E"))

    # --- the moving parts ------------------------------------------------------------------------------------------------
    def _dust_seed(self):
        r = rng("dust")
        n = 70
        u = r.uniform(0, 1, n)
        return {"u": u, "v": r.uniform(0, 1, n), "vx": r.normal(0, 0.012, n), "vy": r.uniform(0.006, 0.028, n),
                "ph": r.uniform(0, math.tau, n), "size": r.uniform(0.8, 1.9, n), "a": r.uniform(0.35, 0.95, n)}

    def _draw_dust(self, p: Paint, tau: float):
        d = self.dust_seed
        top_y, bot_y = G(0, 305)[1], G(0, 670)[1]
        v = (d["v"] + d["vy"] * tau + 0.01 * np.sin(tau * 0.7 + d["ph"])) % 1.0
        y = top_y + v * (bot_y - top_y)
        lx = G(512, 0)[0] + (G(452, 0)[0] - G(512, 0)[0]) * v
        rx = G(618, 0)[0] + (G(705, 0)[0] - G(618, 0)[0]) * v
        u = (d["u"] + d["vx"] * tau + 0.02 * np.sin(tau * 0.5 + d["ph"] * 1.3)) % 1.0
        x = lx + u * (rx - lx)
        strength = (1 - v) ** 0.8 * d["a"]
        for xi, yi, si, ai in zip(x, y, d["size"], strength):
            p.circle(xi, yi, g(si * 0.75), PAL["lamp"], float(ai) * 0.9, add=True)

    def _page(self, text: str, back: bool = False) -> np.ndarray:
        """A clock page (premultiplied RGBA): cream with heavy black digits (Rubik ExtraBold), or its blank back."""
        key = (text, back)
        if key not in self.pages:
            z = self.k * 1.12
            w, h = int(round(g(92) * z)), int(round(g(124) * z))
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            col = (206, 197, 192, 255) if back else (242, 236, 226, 255)
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(g(3.5) * z), fill=col)
            if not back:
                f = S.font("Rubik[wght].ttf", int(h * 0.48), "ExtraBold")
                box = d.textbbox((0, 0), text, font=f)
                d.text(((w - (box[2] - box[0])) / 2 - box[0], (h - (box[3] - box[1])) / 2 - box[1] + h * 0.04), text,
                       font=f, fill=(20, 16, 22, 255))
            arr = np.asarray(im, np.float32) / 255.0
            arr[..., :3] *= arr[..., 3:4]
            self.pages[key] = arr
        return self.pages[key]

    def _draw_clock(self, p: Paint, t: float, flips):
        """The flip clock: its body, the stacked pages, the current values, and a page flipping (lifting, swinging up over
        the rings and dropping behind)."""
        hop = 0.0
        for f in flips:
            q = window(t, f["at"] + 0.06, f["at"] + 0.22)
            if 0 < q < 1:
                hop -= g(5) * math.sin(math.pi * q)
        p2 = Paint(p.buf, S.View(p.v.cx, p.v.cy - hop, p.v.z, p.v.ox, p.v.oy))
        p2.dirty = p.dirty
        pages = {"L": (447, 531), "R": (554, 637)}
        top, bottom = 546, 664
        ring_y = G(0, 550)[1]
        H = G(0, bottom)[1] - G(0, top)[1]
        # pages dropping behind the clock (drawn before its body, so it hides them)
        for f in flips:
            q = window(t, f["at"] + 0.20, f["at"] + 0.34)
            if 0 < q < 1:
                x0, x1 = pages[f["page"]]
                drop = (H + g(30)) * q * q
                p2.sprite(self._page("", back=True), G(x0, 0)[0], ring_y - H + drop, g(x1 - x0), H)
        p2.poly(GRR(442, 514.5, 648, 674, 11), hexc("#E58A5B"), 0.85)  # the lamp-lit edge (top and right)
        p2.poly(GRR(440, 517, 645, 676, 10), PAL["clock_body"])
        for side, (x0, x1) in pages.items():
            for k, col in enumerate(("#D9CFC6", "#BCB1AA")):          # the stacked pages peeking out underneath
                p2.poly(GRR(x0 + 1 + k, bottom + k * 2.5, x1 - 1 - k, bottom + 2.5 + k * 2.5, 1), hexc(col))
            now = None
            for f in flips:
                if f["page"] != side:
                    continue
                q = window(t, f["at"], f["at"] + 0.20)
                if t < f["at"]:
                    now = now or f["from"]
                    continue
                now = f["to"]
                if q < 1:
                    th = math.pi * S.ease_in_out(q)
                    p2.sprite(self._page(f["to"]), G(x0, 0)[0], G(0, top)[1], g(x1 - x0), H)
                    if th < math.pi / 2:  # the old page tipping towards the rings, squashed as it turns away
                        shade = 0.82 + 0.18 * math.cos(th)
                        img = self._page(f["from"]).copy()
                        img[..., :3] *= shade
                        p2.sprite(img, G(x0, 0)[0], ring_y, g(x1 - x0), (H - (ring_y - G(0, top)[1])) * math.cos(th))
                    else:                 # past the rings: its back, standing up above them
                        p2.sprite(self._page("", back=True), G(x0, 0)[0], ring_y, g(x1 - x0), -H * -math.cos(th))
                    now = None
            if now is not None:
                p2.sprite(self._page(now), G(x0, 0)[0], G(0, top)[1], g(x1 - x0), H)
            for rx in (x0 + (x1 - x0) * 0.25, x0 + (x1 - x0) * 0.77):  # the rings
                p2.circle(*G(rx, 550), g(4.8), PAL["ring"])
                p2.circle(*G(rx, 549), g(2.4), hexc("#CFC9CE"))
        for cy in (589, 618):                                          # the colon: light dots on the dark body
            p2.circle(*G(542.5, cy), g(4.6), hexc("#D9D2CC"))
        p.dirty = p2.dirty

    def _draw_figure(self, p: Paint, st: dict):
        """The chair and the figure at the desk, from the reference's own shapes (G()), moved by the state."""
        body, hood, fold = PAL["figure"], PAL["hoodie"], np.clip(PAL["hoodie"] * 0.70, 0, 1)
        chair = hexc("#140C17")
        breathe = st["breath"]
        # the chair: back post, seat, legs
        p.poly(GRR(130, 525, 148, 736, 6), chair)
        p.poly(GR(158, 734, 166, 870), chair)
        p.poly(GR(312, 734, 320, 870), chair)
        # his legs under the desk (stick legs) and his feet
        for x0, x1 in ((300, 309), (287, 296)):
            p.poly(tube([G(x0, 736), G(x1, 860)], g(6.2)), body)
            p.poly(ell(*G(x1 + 9, 862), g(12), g(4.2), 30), body)
        # the hood behind the neck, the hoodie, its folds
        lift = -g(1.4) * breathe
        p.poly(ell(*G(172, 494 + lift / 1.4), g(30), g(22), 48), hood)
        torso = spline([G(160, 503), G(205, 500), G(256, 506), G(273, 536), G(284, 592), G(285, 652), G(282, 702),
                        G(279, 723), G(150, 723), G(141, 662), G(142, 580), G(148, 530)], True, 10)
        torso[:, 1] += lift * (1 - (torso[:, 1] - torso[:, 1].min()) / max(1, np.ptp(torso[:, 1])))
        p.poly(torso, hood)
        p.poly(tube([G(257, 562), G(262, 604), G(268, 646)], g(1.5)), fold, 0.85)
        p.poly(tube([G(196, 671), G(236, 674), G(270, 672)], g(1.3)), fold, 0.6)
        p.poly(GR(148, 722, 330, 735), chair)                              # the seat, in front of the hem
        # the arm, the hand: typing (a small tap on twos) or resting on the desk; holding his head or his phone (below)
        arm = st.get("arm", "type")
        if arm in ("type", "rest"):
            tap = st["tap"] if arm == "type" else (0.0, 0.0)
            hand = G(343 + tap[0], 660 + tap[1])
            elbow = G(283, 612 + tap[1] * 0.3)
            p.poly(tube([G(250, 521), elbow, G(332 + tap[0], 655 + tap[1])], g(28), g(22)), hood)
            p.poly(tube([G(268, 590), G(276, 616)], g(1.3)), fold, 0.8)
            p.poly(ell(*hand, g(11.5), g(7.2), 32), body)
        # the neck, the drawstrings, the head and the eyes
        hx, hy = G(215 + st["head"][0], 415 + st["head"][1])
        p.poly(rect(hx - g(3.4), hy + g(58), g(6.8), max(1.0, G(0, 507)[1] - hy - g(58))), body)
        for x0, x1, y1 in ((231, 233, 548), (242, 244, 543)):
            p.poly(tube([G(x0, 507), G(x1, y1)], g(2.3)), PAL["eye"], 0.95)
        p.circle(hx, hy, g(68), body)
        if arm != "head" and st.get("eyes") is not None:
            st["eyes"].draw(p, hx, hy, g(68))
        if arm == "head":   # his head sunk into his hand, the elbow on the desk
            p.poly(tube([G(250, 521), G(322, 668), G(300, 535)], g(28), g(22)), hood)
            p.poly(tube([G(300, 640), G(312, 664)], g(1.3)), fold, 0.8)
            p.poly(ell(*G(296, 512), g(15), g(11), 32), body)
        elif arm == "phone":   # the phone held up in front of his face, its screen towards him
            p.poly(tube([G(250, 521), G(312, 642), G(334, 548)], g(28), g(22)), hood)
            p.poly(ell(*G(336, 540), g(11), g(8), 32), body)
            p.poly(GRR(328, 498, 344, 540, 2.5), hexc("#141018"))
            p.poly(GR(328, 501, 330.5, 537), PAL["screen"], 0.95)

    # --- the scene ---------------------------------------------------------------------------------------------------------
    FLIPS = [{"page": "R", "at": 0.98, "from": "59", "to": "00"}, {"page": "L", "at": 1.20, "from": "21", "to": "22"}]
    STILL_FROM = 4.0
    LABEL_AT = 2.90

    def state(self, t: float) -> dict:
        """Everything that moves, at t: the deadline scene's timing, measured from the reference (the clock flips at
        1.1-1.4 s, the head turns at 1.6-1.9 s, the eyes spring wide, the label at 2.9 s, then a blink, and the last second
        held completely still)."""
        t = min(t, self.STILL_FROM)
        typing = t < 1.55
        tap = (0.0, 0.0)
        if typing:
            k = int(t * 12)
            tap = ((k % 3 - 1) * 1.2, -2.2 if k % 2 else 0.0)
        # the head turns to camera with a small startle; the eyes slide across and spring wide, then a blink to deadpan
        turn = S.ease_out(window(t, 1.62, 1.82), 3)
        startle = -6 * math.sin(math.pi * window(t, 1.62, 1.86)) * (1 - window(t, 1.62, 1.86) * 0.3)
        wide = S.spring(window(t, 1.70, 2.35))
        blink = window(t, 3.02, 3.22)
        lid = 1 - math.sin(math.pi * blink) if 0 < blink < 1 else 1.0
        if t < 1.62:
            eyes = Eyes(look=(1.18, -0.05), open_=0.48, size=1.0, gap=0.44)
        else:
            open_ = 0.48 + (1.0 - 0.48) * wide
            size = 1.0 + 0.22 * wide
            if t >= 3.02:
                open_ = (0.62 if blink >= 0.5 else 1.0) * lid if 0 < blink < 1 else 0.62
                size = 1.16
            eyes = Eyes(look=(1.18 * (1 - turn), -0.05 + 0.02 * turn), open_=open_, size=size, gap=0.44 + 0.04 * turn)
        breath = math.sin(t * 2 * math.pi * 0.28) * (1 - window(t, 3.3, 4.0))
        windows_lit = sum(t >= a for a in (3.00, 3.13, 3.26))
        # the camera: a slow push in from the first frame, nudged in at each flip, easing to rest by 4 s
        cx0, cy0, z0 = self.cam.rest
        push = S.ease_out(window(t, 0.0, 4.0), 1.8)
        nudge = 0.006 * smooth(window(t, 1.06, 1.22)) + 0.006 * smooth(window(t, 1.28, 1.44))
        z = z0 * (1 + 0.05 * push + nudge)
        cx = cx0 + (FOCUS[0] - cx0) * 0.30 * push
        cy = cy0 + (FOCUS[1] - cy0) * 0.30 * push
        dust_tau = t if t < 3.3 else 3.3 + 0.7 * (1 - (1 - window(t, 3.3, 4.0)) ** 2) / 2 * 1.0
        return {"tap": tap, "head": (-3 * turn, startle - 2 * turn), "eyes": eyes, "breath": breath, "windows": windows_lit,
                "cam": (cx, cy, z), "dust": dust_tau, "label": t}

    def frame(self, t: float, index: int) -> np.ndarray:
        """The reference GIF's deadline scene at t."""
        st = self.state(t)
        st.update({"clock_t": min(t, self.STILL_FROM), "flips": self.FLIPS, "still": t >= self.STILL_FROM,
                   "label": (self.label, window(t, self.LABEL_AT, self.LABEL_AT + 0.28))})
        return self.draw(index, st)

    def _draw_wet(self, p: Paint, tau: float):
        """Rain on the window: drops on the panes, a few running down, faint streaks beyond."""
        r = rng("desk drops")
        n = 60
        xs, ys0, sp, rad = r.uniform(0, 1, n), r.uniform(0, 1, n), r.uniform(0.02, 0.12, n), r.uniform(1.2, 2.8, n)
        col = np.asarray(self.L["spill"], np.float32) * 0.4 + 0.45
        for k in range(n):
            pane = PANES[k % len(PANES)]
            (x0, y0), (x1, y1) = G(pane[0], pane[1]), G(pane[2], pane[3])
            p.circle(x0 + xs[k] * (x1 - x0), y0 + ((ys0[k] + sp[k] * tau) % 1.0) * (y1 - y0), g(rad[k] * 0.8), col, 0.32,
                     add=True)
        q = rng("desk streaks", int(tau * 24) % 6)
        for _ in range(30):
            pane = PANES[int(q.integers(len(PANES)))]
            (x0, y0), (x1, y1) = G(pane[0], pane[1]), G(pane[2], pane[3])
            sx, sy = q.uniform(x0, x1), q.uniform(y0, y1 - g(20))
            p.poly(tube([(sx, sy), (sx - g(3), sy + g(18))], g(0.8)), col, 0.15, add=True)

    def draw(self, index: int, st: dict) -> np.ndarray:
        """One moment from a state: "cam", "tap", "head", "eyes", "breath", "arm" (type, rest, head, phone), "windows"
        (how many clusters of the city's windows are lit), "dust", "clock_t" and "flips" (the clock), "label" (text, 0-1
        popped in, optionally 0-1 faded out), "lamp" (0 off .. 1), "still", "fade", "tau"."""
        W, H = self.size
        still = st.get("still", False)
        frame = np.zeros((H, W, 3), np.float32)
        at = st["cam"]
        lamp = float(st.get("lamp", 1.0))
        for layer in self.static_back:
            layer.composite(frame, at)
        lit = st.get("windows", 0)
        keys = sorted(self.near)
        self.near[max([k for k in keys if k <= lit] or keys[:1])].composite(frame, at)
        if self.wet is not None:
            wp = self.wet.paint(at)
            self._draw_wet(wp, st.get("tau", index / S.FPS))
            self.wet.composite(frame, wp)
        for layer in self.static_mid:
            layer.composite(frame, at)
        fp = self.figure.paint(at)
        self._draw_figure(fp, st)
        k = self.cam.view(0.8, *at).z
        self.figure.composite(frame, fp, rim_light=(LIGHT_FROM[0] * 3.6 * k, LIGHT_FROM[1] * 3.6 * k, PAL["rim"],
                                                    6.0 * k, 0.6, 1.0))
        self.desk.composite(frame, at)
        for k, layer in enumerate(self.light):
            layer.composite(frame, at, gain=lamp if (self.lamp_on and k == 0) else 1.0)
        if st.get("arm") == "phone":
            gp = self.dust.paint(at)
            gp.glow(*G(330, 520), g(40), g(40), PAL["screen"], 0.45)
            gp.glow(*G(285, 470), g(70), g(60), PAL["screen"], 0.10)
            self.dust.composite(frame, gp)
        cp = self.clock.paint(at)
        self._draw_clock(cp, st.get("clock_t", 0.0), st.get("flips") or [])
        self.clock.composite(frame, cp)
        if self.lamp_on and lamp > 0.5:
            dp = self.dust.paint(at)
            self._draw_dust(dp, st["dust"])
            self.dust.composite(frame, dp)
        self.plant.composite(frame, at)
        S.bloom(frame, 0.86, 0.30)
        # the label pops in at the top
        text, q, *gone = st.get("label") or ("", 0.0)
        alpha = 1.0 - (gone[0] if gone else 0.0)
        if text and q > 0 and alpha > 0:
            sprite = S.label_sprite(text, self.label_px)
            y = self.finish.bar + self.label_px * (1.25 if not self.tall else 1.6)
            S.paste(frame, sprite, W / 2, y, scale=0.55 + 0.45 * S.back_out(q, 2.2), opacity=smooth(q * 1.6) * smooth(alpha))
        frame = self.finish.apply(frame, index, still=still)
        fade = st.get("fade", 1.0)
        if fade < 1:
            frame *= max(0.0, fade)
        return frame


# --- what the other sets share ------------------------------------------------------------------------------------------------
class Stage:
    """A set's shared parts: the camera's resting framing for the frame's shape (`height` world units fill a 16:9 frame's
    height, `tall_width` a 9:16 frame's width), the finish, the label and the fade. A set's frame(index, st) draws one
    moment from a state st: "cam" (cx, cy, z), "label" (text, 0-1 how far it has popped in, and optionally 0-1 how far it
    has faded out again), "still", "fade" (1 = none)
    and the set's own parts."""

    PAN = (0.0, 0.0)  # how far (world units) the camera may pan at most: static layers are drawn that much wider

    def __init__(self, size, center, height, tall_width):
        W, H = size
        self.size, self.tall = size, H > W
        z = W / tall_width if self.tall else H / height
        self.cam = Camera(size, center[0], center[1], z)
        self.k = z
        self.finish = S.Finish(size)
        self.label_px = int(round((46 if not self.tall else 54) * (min(W, H) / 1080)))

    def static(self, depth, draw, **kw):
        m = (S.MARGIN + int(self.PAN[0] * depth * self.k), S.MARGIN + int(self.PAN[1] * depth * self.k))
        return Static(self.cam, depth, draw, margin=m, **kw)

    def rim_at(self, depth, at, light, px=3.6, glow=6.0, strength=1.0):
        k = self.cam.view(depth, *at).z
        return (light[0] * px * k, light[1] * px * k, PAL["rim"], glow * k, 0.6, strength)

    def finish_frame(self, frame, index, st):
        S.bloom(frame, 0.86, 0.30)
        text, q, *gone = st.get("label") or ("", 0.0)
        alpha = 1.0 - (gone[0] if gone else 0.0)   # (a label can fade out again: its third value, 0-1)
        if text and q > 0 and alpha > 0:
            W, H = self.size
            sprite = S.label_sprite(text, self.label_px)
            y = self.finish.bar + self.label_px * (1.25 if not self.tall else 1.6)
            S.paste(frame, sprite, W / 2, y, scale=0.55 + 0.45 * S.back_out(q, 2.2), opacity=smooth(q * 1.6) * smooth(alpha))
        frame = self.finish.apply(frame, index, still=st.get("still", False))
        fade = st.get("fade", 1.0)
        if fade < 1:
            frame *= max(0.0, fade)
        return frame


def flat(color):
    c = hexc(color) if isinstance(color, str) else np.asarray(color, np.float32)
    return lambda px, py: np.broadcast_to(c, px.shape + (3,))


def falling(p: Paint, y0, y1, color, a0, a1=0.0, power=1.3):
    """A colour function: `color` fading from a0 at world y0 to a1 at y1 (light that thins as it falls)."""
    c = hexc(color) if isinstance(color, str) else np.asarray(color, np.float32)

    def f(px, py):
        u = np.clip((p.wy(py) - y0) / (y1 - y0), 0, 1)[..., None]
        return c * (a1 + (a0 - a1) * (1 - u) ** power)
    return f


class Rain:
    """Rain in screen space: thin slanted streaks at two depths (far: fine and dim; near: longer and soft), brighter where a
    lamp's light catches them, and small splashes on the wet ground."""

    def __init__(self, size, seed="rain", far=460, near=70, splashes=150):
        W, H = size
        r = rng(seed)
        self.size = size
        self.layers = []
        for n, length, thick, speed, base, depth, blur in ((far, 0.030, 1, 1.7, 0.30, 0.45, 0.0),
                                                           (near, 0.080, 2, 2.8, 0.30, 1.5, 2.0)):
            self.layers.append({"x": r.uniform(0, 1, n), "y": r.uniform(0, 1, n), "sp": r.uniform(0.8, 1.2, n) * speed,
                                "len": length * H * r.uniform(0.7, 1.3, n), "thick": thick,
                                "base": base * r.uniform(0.5, 1.2, n), "depth": depth, "blur": blur * H / 1080})
        self.sp = {"x": r.uniform(0, 1, splashes), "y": r.uniform(0, 1, splashes), "ph": r.uniform(0, 1, splashes),
                   "rate": r.uniform(1.6, 3.2, splashes), "size": r.uniform(0.6, 1.4, splashes)}
        self.slant = 0.16

    @staticmethod
    def _lit(x, y, lights):
        b = np.zeros_like(x)
        for sx, sy, spread in lights:
            below = np.clip(y - sy, 0, None)
            d = np.abs(x - sx) / (spread + below * 0.42)
            b += 1.6 * np.exp(-d * d * 2.2) * (y > sy - spread * 0.5) * np.exp(-below / 900.0)
        return b

    def draw(self, frame, tau, pan_px, lights, band, color="#C4BDE0"):
        """pan_px: how far the camera has panned (px, at depth 1); lights: [(x, y, spread)] lamp heads on screen (px);
        band: (y0, y1) px where splashes land."""
        W, H = self.size
        col = hexc(color)
        total = np.zeros((H, W), np.float32)
        for L in self.layers:
            canvas = np.zeros((H, W), np.uint8)
            n = len(L["x"])
            y_end = ((L["y"] + L["sp"] * tau) % 1.0) * (H + L["len"])
            y_start = y_end - L["len"]
            span = W * 1.25
            x_end = (L["x"] * span - pan_px * L["depth"] + self.slant * y_end) % span - W * 0.12
            x_start = x_end - self.slant * L["len"]
            val = np.clip((L["base"] + self._lit(x_end, y_end, lights) * L["base"]) * 255, 0, 255)
            for i in range(n):
                cv2.line(canvas, (int(x_start[i] * 16), int(y_start[i] * 16)), (int(x_end[i] * 16), int(y_end[i] * 16)),
                         int(val[i]), L["thick"], cv2.LINE_AA, 4)
            c = canvas.astype(np.float32) / 255.0
            if L["blur"]:
                c = cv2.GaussianBlur(c, (0, 0), L["blur"])
            total += c
        # splashes: little crowns opening on the wet ground
        sp, (y0, y1) = self.sp, band
        canvas = np.zeros((H, W), np.uint8)
        span = W * 1.3
        xs = (sp["x"] * span - pan_px * 0.70) % span - W * 0.15
        ys = y0 + sp["y"] * (y1 - y0)
        ph = (sp["ph"] + sp["rate"] * tau) % 1.0
        lit = 0.25 + self._lit(xs, ys, lights) * 0.6
        for i in range(len(xs)):
            r = (2 + 9 * ph[i]) * sp["size"][i] * H / 1080
            v = int(np.clip((1 - ph[i]) ** 1.5 * lit[i] * 255, 0, 255))
            if v > 6:
                cv2.ellipse(canvas, (int(xs[i] * 16), int(ys[i] * 16)), (int(r * 16), int(r * 0.32 * 16)), 0, 180, 360, v,
                            1, cv2.LINE_AA, 4)
        total += canvas.astype(np.float32) / 255.0
        frame += total[..., None] * col


# --- the rainy street at night ------------------------------------------------------------------------------------------------
class RainStreet(Stage):
    """A wet street at night in the rain, seen from the side: facades with warm windows and a lit shop, a low roof where the
    far city shows, street lamps at the curb throwing cones of light, the wet pavement reflecting them (and him), and the
    rain; in other lights (silhouette_places.LIGHTS) and dry. st: "actors" (people: silhouette_places), "rain" (seconds
    of rain); or the style test's "x" and "pose" (Figure.draw_standing)."""

    PAN = (640.0, 40.0)
    MARKS = {
        "walk": {"kind": "walk", "from": -640.0, "to": 245.0, "f": 1},
        "stand": {"kind": "stand", "x": 245.0, "f": 1},
        "run": {"kind": "run", "from": -900.0, "to": 900.0, "f": 1},
        "stand_other": {"kind": "stand", "x": 520.0, "f": -1},
        "walk_away": {"kind": "walk", "from": 420.0, "to": 1100.0, "f": 1},
        "crowd": [{"kind": "walk", "from": 1200.0, "to": -900.0, "f": -1}, {"kind": "walk", "from": -1100.0, "to": 900.0,
                                                                            "f": 1}],
    }
    R = 58.0
    LAMPS = (-560.0, 330.0, 1220.0)   # the poles, at the curb; each lamp's head hangs HEAD_DX to their left
    HEAD_DX, HEAD_Y = -85.0, -262.0
    WALK_Y, CURB, BASE = 290.0, 350.0, 190.0
    LIGHT_FROM = (0.30, -1.0)         # his rim: the lamps above

    def __init__(self, size, light="night", rain=True, center=None):
        from silhouette_places import LIGHTS

        super().__init__(size, center=center or (0.0, 40.0), height=900.0, tall_width=700.0)
        self.light, self.L, self.wet = light, LIGHTS[light], bool(rain)
        self.lamps_on = bool(self.L["lamp"] or self.wet)
        self.hero = S.Figure(R=58.0)
        self.facades = self._facades()
        self.back = [self.static(0.08, self._sky, blur=1.2), self.static(0.22, self._far, blur=1.6),
                     self.static(0.50, self._buildings), self.static(0.50, self._window_glow, add=True, blur=4.0)]
        self.street = self.static(0.70, self._street)
        self.street_light = self.static(0.72, self._street_light, add=True, blur=2.5)
        self.lamps = self.static(0.74, self._lamps)
        self.lamp_glow = self.static(0.74, self._lamp_glow, add=True) if self.lamps_on else None
        self.figure = Dynamic(self.cam, 0.70)
        self.front = Dynamic(self.cam, 1.9)
        self.rain = Rain(size) if self.wet else None

    def _sky(self, p: Paint):
        if self.light != "night":
            from silhouette_places import sky
            sky(p, self.L, -1700, 1700, -700, 150, 300.0, self.wet, "street")
            return
        p.poly(rect(-1600, -900, 3200, 1300), gradient([(-700, "#0A0816"), (-320, "#141029"), (-80, "#281C3B"),
                                                         (150, "#4A2B4C")])(p))
        p.glow(0, 120, 1100, 170, (0.32, 0.16, 0.22), 0.35)

    def _far(self, p: Paint):
        r = rng("far street")
        x, shapes, wins = -1700.0, [], []
        while x < 1700:
            w = r.uniform(40, 120)
            top = r.uniform(-170, 30)
            shapes.append(rect(x, top, w + 1, self.BASE + 80 - top))
            for _ in range(int(w / 25)):
                if r.random() < 0.35:
                    wins.append(rect(x + r.uniform(4, w - 10), r.uniform(top + 8, self.BASE - 10), 5, 7))
            x += w
        p.poly(None, hexc("#4A3858") if self.light == "night" else hexc(self.L["far"]), polys=shapes)
        if self.L["lit"] > 0.2:
            for wv in wins:
                p.poly(wv, hexc("#E7A877"), 0.6)
        p.poly(rect(-1700, -70, 3400, 280), flat("#7A5677" if self.light == "night" else self.L["haze"][0]), 0.20, soft=30)

    def _facades(self):
        """The near buildings: (x0, x1, top, colour) and their windows (rect, lit colour or None)."""
        blds = [(-1700, -650, -760, "#1C1428"), (-650, -170, -430, "#221830"), (-170, 250, 70, "#191223"),
                (250, 840, -540, "#1F162B"), (840, 1800, -700, "#1A1326")]
        r = rng("windows street")
        wins = []
        lit_cols = ["#FFC383", "#F2A86E", "#FFD9A0", "#E9B07A"]
        for x0, x1, top, _ in blds:
            if top > -100:
                continue
            for wy in np.arange(top + 60, -40, 100):
                for wx in np.arange(x0 + 45, x1 - 80, 115):
                    lit = lit_cols[int(r.integers(len(lit_cols)))] if r.random() < 0.32 else None
                    wins.append((rect(wx, wy, 44, 60), lit))
        return blds, wins

    def _buildings(self, p: Paint):
        blds, wins = self.facades
        for x0, x1, top, col in blds:
            p.poly(rect(x0, top, x1 - x0, self.BASE + 70 - top), hexc(col))
            p.poly(rect(x0, top, 3, self.BASE + 70 - top), hexc("#3B2B48"), 0.8)   # the lit edge
            p.poly(rect(x0, top, x1 - x0, 6), hexc("#2E2338"))                       # the cornice
        shown = {"night": 1.0, "dusk": 0.6, "dawn": 0.15, "day": 0.0}[self.light]
        wins = [(w, lit if lit and rng("lit", w[0][0], w[0][1]).random() < shown else None) for w, lit in wins]
        for w, lit in wins:
            p.poly(w, hexc(lit) if lit else hexc("#120D19"), 0.9 if lit else 1.0)
            if lit:  # a blind part way down
                x, y = w[0]
                p.poly(rect(x, y, 44, 60 * float(rng("blind", x, y).uniform(0.15, 0.5))), hexc("#8A5A4A"), 0.55)
        # the shop: its lit window under an awning, shelves in silhouette
        p.poly(rect(-600, 20, 360, 160), gradient([(20, "#B8784E"), (180, "#E2A56E")])(p))
        for y in (70, 120):
            p.poly(rect(-590, y, 340, 5), hexc("#5A3A30"), 0.8)
        for x, h in ((-560, 30), (-520, 22), (-470, 34), (-420, 26), (-330, 30), (-290, 20)):
            p.poly(rect(x, 70 - h, 26, h), hexc("#6A4434"), 0.75)
        p.poly(np.array([(-620, -10), (-220, -10), (-200, 22), (-640, 22)], float), hexc("#120C17"))
        # a door with a lit fanlight, a drainpipe, the low roof's water tank
        p.poly(rect(560, 40, 80, 150), hexc("#0F0B14"))
        p.poly(rect(564, 18, 72, 20), hexc("#E8A070"), 0.8)
        p.poly(rect(830, -540, 10, 740), hexc("#120D18"))
        p.poly(rr(40, -30, 90, 70, 8), hexc("#140F1C"))
        for lx in (50, 115):
            p.poly(rect(lx, 38, 6, 34), hexc("#140F1C"))

    def _window_glow(self, p: Paint):
        _, wins = self.facades
        shown = {"night": 1.0, "dusk": 0.6, "dawn": 0.15, "day": 0.0}[self.light]
        for w, lit in wins:
            if lit and rng("lit", w[0][0], w[0][1]).random() < shown:
                (x, y) = w[0]
                p.glow(x + 22, y + 30, 50, 55, hexc(lit) * 0.5, 0.30)
        p.glow(-420, 100, 260, 120, hexc("#FFC383") * 0.6, 0.22)
        p.glow(600, 28, 60, 30, hexc("#E8A070") * 0.6, 0.3)

    def _street(self, p: Paint):
        p.poly(rect(-2300, 170, 4800, 185), gradient([(170, "#181220"), (350, "#2A2133")])(p))
        for y in (214, 258, 312):
            p.poly(rect(-2300, y, 4800, 2), hexc("#3A2F45"), 0.30)
        for x in np.arange(-2300, 2500, 190):
            p.poly(tube([(x, 172), (x - 34, 348)], 2.0), hexc("#3A2F45"), 0.25)
        for cx, cy, rx, ry in ((-320, 300, 120, 14), (420, 330, 150, 12), (1020, 280, 90, 10), (-980, 320, 130, 12)):
            p.poly(ell(cx, cy, rx, ry, 48), hexc("#100C16"), 0.9)                      # puddles
        p.poly(rect(-2300, 348, 4800, 4), hexc("#5C4A66"), 0.8)
        p.poly(rect(-2300, 352, 4800, 14), hexc("#2E2438"))
        p.poly(rect(-2300, 366, 4800, 600), hexc("#0B0910"))

    def _street_light(self, p: Paint):
        warm = PAL["lamp"]
        for L in (self.LAMPS if self.lamps_on else ()):
            hx = L + self.HEAD_DX
            top = self.HEAD_Y + 10
            p.poly(np.array([(hx - 20, top), (hx + 20, top), (hx + 250, self.WALK_Y + 10), (hx - 250, self.WALK_Y + 10)]),
                   falling(p, top, self.WALK_Y, warm, 0.26, 0.04), soft=18)
            p.glow(hx, self.WALK_Y, 250, 34, warm, 0.40)
            p.glow(hx, self.WALK_Y + 10, 430, 70, warm, 0.12)
            p.poly(rect(hx - 22, 368, 44, 420), falling(p, 368, 760, warm, 0.50, 0.0, 1.6), soft=9)  # its reflection
            p.poly(rect(hx - 6, 368, 12, 360), falling(p, 368, 700, warm, 0.45, 0.0, 1.4), soft=3)
            for cx, cy, rx in ((-320, 300, 120), (420, 330, 150)):                           # the puddles catch it
                if abs(cx - hx) < 320:
                    p.glow(cx, cy, rx * 0.8, 9, warm, 0.25)
        p.poly(rect(-600, 176, 360, 170), falling(p, 176, 345, "#FFC383", 0.13, 0.0), soft=12)  # the shop on the wet pavement
        p.poly(rect(-560, 368, 280, 260), falling(p, 368, 620, "#FFC383", 0.10, 0.0), soft=12)

    def _lamps(self, p: Paint):
        dark = hexc("#0E0A12")
        for L in self.LAMPS:
            hx = L + self.HEAD_DX
            p.poly(rect(L - 6, self.HEAD_Y - 6, 12, self.CURB + 14 - self.HEAD_Y), dark)
            p.poly(rr(L - 15, self.CURB - 30, 30, 44, 4), dark)
            p.poly(tube([(L, self.HEAD_Y), (L - 18, self.HEAD_Y - 34), (L - 52, self.HEAD_Y - 40),
                         (hx + 16, self.HEAD_Y - 24)], 9.0), dark)
            p.poly(np.array([(hx - 36, self.HEAD_Y - 24), (hx + 32, self.HEAD_Y - 24), (hx + 22, self.HEAD_Y - 4),
                             (hx - 26, self.HEAD_Y - 4)]), hexc("#120D16"))
            p.poly(ell(hx, self.HEAD_Y - 3, 25, 5, 40), hexc("#FFF1D6") if self.lamps_on else hexc("#4A3A44"))

    def _lamp_glow(self, p: Paint):
        for L in self.LAMPS:
            hx = L + self.HEAD_DX
            p.glow(hx, self.HEAD_Y, 60, 24, PAL["lamp"], 0.55)
            p.glow(hx, self.HEAD_Y + 10, 170, 90, PAL["lamp"] * 0.5, 0.16)

    def _reflect(self, frame, fp: Paint, at):
        """His reflection on the wet pavement: the figure's layer flipped at his feet, faint, fading, a little blurred."""
        if fp.dirty is None:
            return
        x0, y0, x1, y1 = fp.dirty
        v = self.cam.view(0.70, *at)
        gy = int(round(v.pt(0, self.WALK_Y)[1])) + 1
        curb = int(round(v.pt(0, self.CURB)[1]))
        n = min(gy - y0, curb - gy, frame.shape[0] - gy)
        if n <= 2:
            return
        src = self.figure.buf[gy - n:gy, x0:x1][::-1].copy()
        src = cv2.GaussianBlur(src, (0, 0), 2.0)
        src *= np.linspace(0.26, 0.0, n, dtype=np.float32)[:, None, None]
        S.over(frame[gy:gy + n, x0:x1], src)

    def frame(self, index: int, st: dict) -> np.ndarray:
        W, H = self.size
        frame = np.zeros((H, W, 3), np.float32)
        at = st["cam"]
        for layer in self.back:
            layer.composite(frame, at)
        self.street.composite(frame, at)
        self.street_light.composite(frame, at)
        self.lamps.composite(frame, at)
        if self.lamp_glow is not None:
            self.lamp_glow.composite(frame, at)
        fp = self.figure.paint(at)
        glows = []
        if "actors" in st:
            for a in st["actors"]:
                got = S.draw_person(fp, a["pose"], a["look"], a.get("eyes"))
                if got.get("glow"):
                    glows.append((got["glow"], a["pose"]["R"], got["head"]))
        else:
            self.hero.draw_standing(fp, st["x"], self.WALK_Y, st["pose"])
        if self.wet or self.light == "night":
            self._reflect(frame, fp, at)
        self.figure.composite(frame, fp, rim_light=self.rim_at(0.70, at, self.LIGHT_FROM, strength=0.9))
        if glows:
            gp = self.front.paint(at)
            for (gx, gy), R_, (hx, hy) in glows:
                gp.glow(gx, gy, 0.9 * R_, 0.9 * R_, PAL["screen"], 0.55)
                gp.glow(hx, hy, R_, 0.9 * R_, PAL["screen"], 0.12)
            self.front.add = True
            self.front.composite(frame, gp)
            self.front.add = False
        v = self.cam.view(0.74, *at)
        lights = [(*v.pt(L + self.HEAD_DX, self.HEAD_Y), 26 * v.z) for L in self.LAMPS] if self.lamps_on else []
        g = self.cam.view(0.70, *at)
        band = (g.pt(0, 200)[1], min(H - self.finish.bar, g.pt(0, 345)[1]))
        if self.rain is not None:
            self.rain.draw(frame, st.get("rain", st.get("tau", index / S.FPS)), (at[0] - self.cam.rest[0]) * self.k,
                           lights, band)
        fr = self.front.paint(at)
        fr.poly(rect(40, -900, 30, 1900), hexc("#07060A"), soft=6)
        fr.poly(rr(-10, -420, 130, 80, 6), hexc("#0A080D"), soft=6)   # a sign on it, out of focus
        self.front.composite(frame, fr)
        return self.finish_frame(frame, index, st)


# --- the hospital room at night -----------------------------------------------------------------------------------------------
def ecg(u):
    """One heartbeat's trace (0-1 through the beat): a small bump, the sharp spike, the slow wave after."""
    return (0.12 * np.exp(-((u - 0.12) / 0.035) ** 2) - 0.15 * np.exp(-((u - 0.24) / 0.010) ** 2)
            + 1.0 * np.exp(-((u - 0.27) / 0.012) ** 2) - 0.28 * np.exp(-((u - 0.30) / 0.012) ** 2)
            + 0.22 * np.exp(-((u - 0.52) / 0.05) ** 2))


class HospitalRoom(Stage):
    """A hospital room at night, seen from the side: the window with the moon and the far city, his mother asleep in the
    bed (grey hair, eyes only), the heart monitor's moving trace, the drip stand, a small warm lamp on the bedside table, a
    curtain at the edge, and him standing beside her. st: "her_eyes" (Eyes), "her_turn" (0-1: her head turned to him),
    "x" and "pose" (him: Figure.draw_standing) or "actors" (silhouette_places), "beat" (seconds: the monitor's sweep).
    In other lights (silhouette_places.LIGHTS): the moon and its beam only at night, the lamp lit at dusk and night."""

    PAN = (80.0, 30.0)
    MARKS = {
        "stand": {"kind": "stand", "x": 300.0, "f": -1},
        "chair": {"kind": "sit", "x": 330.0, "seat": 212.0, "f": -1},
        "doctor": {"kind": "stand", "x": -40.0, "f": 1, "arms": "clipboard"},
        "bed": {"kind": "lie", "x": -566.0, "y": 50.0, "f": 1, "slot": "bed"},   # (his mother: the room draws her)
    }
    R = 64.0
    FLOOR = 296.0
    LIGHT_FROM = (-0.80, -0.55)          # the moon behind, up on the left
    HEAD, HER_R = (-566.0, 50.0), 44.0   # her head on the pillow
    PERIOD, SWEEP = 0.95, 2.4            # a heartbeat; the trace's sweep across the screen (s)
    SCREEN = (-866.0, -729.0, -190.0, 30.0)  # the trace's x0, x1, baseline, height

    def __init__(self, size, light="night", rain=False, center=None):
        from silhouette_places import LIGHTS

        super().__init__(size, center=center or (-120.0, 0.0), height=900.0, tall_width=1150.0)
        self.light, self.L, self.wet = light, LIGHTS[light], bool(rain)
        self.lamp_on = bool(self.L["lamp"] or self.wet)
        self.hero = S.Figure(R=64.0)
        self.back = [self.static(0.12, self._sky, blur=1.2), self.static(0.22, self._far, blur=1.4),
                     self.static(0.55, self._wall), self.static(0.55, self._wall_light, add=True, blur=3.0),
                     self.static(0.64, self._drip), self.static(0.66, self._monitor)]
        self.bed_back = self.static(0.70, self._bed_back)
        self.her = Dynamic(self.cam, 0.70)
        self.bed_front = self.static(0.70, self._bed_front)
        self.table = self.static(0.72, self._table)
        self.light = [self.static(0.66, self._moonbeam, add=True, blur=4.0),
                      self.static(0.72, self._table_light, add=True, blur=2.0)]
        self.trace = Dynamic(self.cam, 0.66, add=True)
        self.figure = Dynamic(self.cam, 0.70)
        self.curtain = self.static(0.82, self._curtain)

    @classmethod
    def beeps(cls, start, end):
        """The seconds (from the scene's start) the monitor beeps: when its sweep draws each spike."""
        k0 = int(math.floor(start / cls.PERIOD)) - 1
        out = []
        for k in range(k0, int(end / cls.PERIOD) + 2):
            t = (k + 0.27) * cls.PERIOD
            if start <= t < end:
                out.append(t)
        return out

    def _sky(self, p: Paint):
        if self.light != "night" or self.wet:
            from silhouette_places import sky
            sky(p, self.L, -460, 460, -400, -10, 130.0, self.wet, "hospital")
            return
        p.poly(rect(-420, -460, 840, 480), gradient([(-400, "#0F0D24"), (-160, "#1E1838"), (-20, "#3A2A4E")])(p))
        p.glow(130, -255, 70, 70, (0.75, 0.75, 0.92), 0.30)
        p.circle(130, -255, 20, hexc("#ECE6F4"))
        r = rng("hospital stars")
        for _ in range(12):
            p.circle(r.uniform(-250, 250), r.uniform(-330, -140), r.uniform(0.9, 1.5), PAL["label"], float(r.uniform(0.4, 0.8)))

    def _far(self, p: Paint):
        r = rng("hospital city")
        x, shapes, wins = -460.0, [], []
        while x < 460:
            w = r.uniform(30, 80)
            top = r.uniform(-150, -70)
            shapes.append(rect(x, top, w + 1, 160))
            for _ in range(int(w / 18)):
                if r.random() < 0.4:
                    wins.append(rect(x + r.uniform(3, w - 7), r.uniform(top + 6, -30), 4, 6))
            x += w
        p.poly(None, hexc("#2A2140") if self.light == "night" else hexc(self.L["far"]), polys=shapes)
        if self.L["lit"] > 0.2:
            for wv in wins:
                p.poly(wv, hexc("#E7A877"), 0.6)
        p.poly(rect(-460, -110, 920, 110), flat("#5A4570" if self.light == "night" else self.L["haze"][0]), 0.25, soft=20)

    def _wall(self, p: Paint):
        cx, cy = 0.0, -180.0

        def wall(px, py):
            d = np.sqrt(((p.wx(px) - cx) / 900) ** 2 + ((p.wy(py) - cy) / 600) ** 2)
            t = np.clip(d, 0, 1)[..., None] ** 0.8
            return near * (1 - t) + far * t
        if self.light == "night":
            near, far = hexc("#2B2340"), hexc("#0F0B15")
        else:
            near, far = hexc(self.L["wall"][0]) * 0.7 + hexc("#3C4A66") * 0.3, hexc(self.L["wall"][1])
        p.poly(rect(-1500, -900, 2700, 1200), wall)
        p.poly(rect(-1500, self.FLOOR, 2700, 600), hexc("#0C0A11"))
        p.poly(rect(-1500, self.FLOOR - 12, 2700, 12), hexc("#1A1522"))
        p.poly(rr(-275, -345, 550, 330, 4), hexc("#16101E"))                  # the window
        for pane in ((-255, -325, 245, 145), (10, -325, 245, 145), (-255, -170, 245, 140), (10, -170, 245, 140)):
            p.cut(rect(*pane))
        p.poly(rect(-295, -15, 590, 10), hexc("#3A2E44"))
        p.poly(rect(-290, -5, 580, 8), hexc("#1C1624"))
        p.poly(rr(-730, -128, 270, 34, 5), hexc("#1E1828"))                   # the panel over the bed
        for x in (-700, -660, -620):
            p.circle(x, -111, 6, hexc("#3A3046"))
        p.poly(tube([(-520, -94), (-512, -20), (-520, 40)], 2.5), hexc("#2A2236"))  # the call button's cord

    def _wall_light(self, p: Paint):
        p.glow(0, -180, 420, 260, (0.30, 0.33, 0.50) if self.light == "night" else self.L["spill"], 0.16)
        p.glow(-797, -195, 170, 120, (0.20, 0.55, 0.42), 0.16)

    def _drip(self, p: Paint):
        pole = hexc("#2A2434")
        p.poly(rect(-406, -300, 6, 596), pole)
        for dx in (-55, 52):
            p.poly(tube([(-403, 286), (-403 + dx, 296)], 5.0), pole)
        p.poly(tube([(-403, -298), (-428, -312)], 3.0), pole)
        p.poly(tube([(-403, -298), (-378, -312)], 3.0), pole)
        p.poly(rr(-440, -292, 62, 92, 14), hexc("#B8C6DA"), 0.40)
        p.poly(rr(-434, -252, 50, 48, 10), hexc("#C9D6E8"), 0.32)
        p.poly(tube([(-409, -200), (-410, -60), (-435, 40), (-454, 99)], 2.2), hexc("#A9B5C8"), 0.55)

    def _monitor(self, p: Paint):
        dark = hexc("#1A1522")
        p.poly(rect(-801, -132, 10, 428), dark)
        for dx in (-45, 45):
            p.poly(tube([(-796, 286), (-796 + dx, 296)], 6.0), dark)
        p.poly(rr(-885, -255, 175, 125, 10), hexc("#17121D"))
        p.poly(rect(-880, -254, 165, 3), hexc("#3A3046"), 0.9)
        p.poly(rr(-872, -243, 149, 92, 4), hexc("#06100E"))
        for y in (-222, -190, -160):
            p.poly(rect(-870, y, 145, 1.2), hexc("#123A2E"), 0.6)
        for x in (-860, -845, -830):
            p.circle(x, -141, 3.2, hexc("#3E5A50"))

    def _bed_back(self, p: Paint):
        p.poly(ell(-320, 300, 430, 14, 64), hexc("#06050A"), 0.6, soft=10)
        p.poly(rr(-712, -120, 36, 420, 10), hexc("#1C1624"))
        p.poly(rect(-712, -118, 3, 414), hexc("#4A3C58"), 0.7)
        p.poly(rr(-690, 100, 745, 62, 14), hexc("#3A3450"))
        p.poly(rr(-668, 38, 215, 72, 30), hexc("#77708C"))
        p.poly(tube([(-650, 96), (-560, 102), (-470, 96)], 2.5), hexc("#5E5874"), 0.7)
        p.poly(rect(-700, 160, 770, 22), hexc("#2A2336"))
        p.poly(rect(-700, 160, 770, 3), hexc("#4A4058"), 0.8)
        for x in (-680, 30):
            p.poly(rect(x, 182, 14, 96), hexc("#2A2336"))
            p.circle(x + 7, 284, 13, hexc("#120E17"))
        p.poly(ell(-516, 99, 34, 16, 40), hexc("#64718A"))                    # her gown at the shoulder

    def _bed_front(self, p: Paint):
        top = spline([(-520, 100), (-430, 82), (-330, 74), (-220, 76), (-110, 66), (-30, 60), (25, 74), (52, 110)],
                      closed=False, k=10)
        p.poly(np.vstack([top, [(52, 168), (-520, 168)]]), hexc("#4B4566"))
        p.poly(tube([(-518, 106), (-450, 92), (-380, 86)], 16.0, 12.0), hexc("#6C6688"))   # the sheet turned down
        for a, b in (((-400, 100), (-382, 150)), ((-250, 90), (-205, 150)), ((-90, 80), (-60, 150))):
            p.poly(tube([a, b], 2.5), hexc("#3A3552"), 0.7)
        p.poly(tube([(-500, 101), (-466, 104)], 19.0, 16.0), hexc("#64718A"))  # her arm on the blanket, her hand
        p.poly(ell(-452, 103, 13, 8, 30), PAL["figure"])
        p.poly(rr(36, 30, 30, 270, 8), hexc("#1C1624"))                        # the footboard
        p.poly(rect(36, 32, 30, 3), hexc("#4A3C58"), 0.8)

    def _table(self, p: Paint):
        p.poly(rr(95, 170, 120, 128, 6), hexc("#1D1726"))
        p.poly(rect(93, 166, 124, 6), hexc("#5A4A5A"))
        p.poly(rect(105, 205, 100, 2), hexc("#120D17"))
        p.circle(155, 222, 3, hexc("#4A3C50"))
        p.poly(ell(155, 166, 18, 4, 30), hexc("#2A2030"))
        p.poly(rect(153, 120, 4, 46), hexc("#2A2030"))
        p.poly(np.array([(132, 92), (178, 92), (192, 124), (118, 124)], float), hexc("#4A3036"))
        p.poly(ell(155, 124, 37, 4, 40), hexc("#FFE9C8") if self.lamp_on else hexc("#4A3A44"))
        p.poly(rr(190, 146, 16, 20, 3), hexc("#2E2436"))
        p.poly(rect(392 - 4, 92, 12, 204), hexc("#1C1624"))                     # a visitor's chair
        p.poly(rect(270, 212, 120, 11), hexc("#1C1624"))
        p.poly(rect(270, 210, 120, 2.5), hexc("#4A3C58"), 0.8)
        p.poly(rect(275, 222, 10, 74), hexc("#1C1624"))

    def _table_light(self, p: Paint):
        if not self.lamp_on:
            return
        p.glow(155, 128, 90, 40, PAL["lamp"], 0.45)
        p.glow(155, 166, 95, 14, PAL["lamp"], 0.22)
        p.glow(155, 70, 170, 120, PAL["lamp"] * 0.5, 0.10)
        p.glow(-520, 60, 150, 70, PAL["lamp"] * 0.4, 0.05)

    def _moonbeam(self, p: Paint):
        col = "#8FA4DE" if self.light == "night" else "#%02x%02x%02x" % tuple(int(min(1, c * 1.6) * 255)
                                                                               for c in self.L["spill"])
        p.poly(np.array([(-255, -35), (255, -35), (60, 300), (-470, 300)], float),
               falling(p, -35, 300, col, 0.09 if not self.wet else 0.04, 0.02), soft=30)

    def _curtain(self, p: Paint):
        p.poly(rect(470, -372, 600, 7), hexc("#2A2236"))
        edge = spline([(520, -365), (512, -250), (524, -120), (508, 20), (520, 160), (506, 296)], closed=False, k=8)
        p.poly(np.vstack([edge, [(1100, 296), (1100, -365)]]), hexc("#2A2740"))
        for x in (565, 650, 740, 840):
            p.poly(rect(x, -360, 26, 650), hexc("#1C1A2E"), 0.7, soft=12)
        for x in (605, 695, 790):
            p.poly(rect(x, -360, 18, 650), hexc("#3A3552"), 0.5, soft=10)
        p.poly(tube(edge[::4], 3.0), hexc("#6A4A50"), 0.45)

    def _draw_her(self, p: Paint, eyes, turn):
        R = self.HER_R
        hx, hy = self.HEAD[0] + 4 * turn, self.HEAD[1] - 2 * turn
        hair = hexc("#B9B2BC")                                              # silver: she's older
        p.circle(hx - 1.02 * R, hy - 0.22 * R, 0.42 * R, hair)
        p.poly(ell(hx - 0.30 * R, hy - 0.24 * R, 1.06 * R, 1.02 * R, 56), hair)
        p.circle(hx, hy, R, PAL["figure"])
        eyes.draw(p, hx, hy, R, turn=0.0)

    def _draw_trace(self, p: Paint, beat):
        x0, x1, base, amp = self.SCREEN
        n = 360
        us = np.linspace(0, 1, n)
        head = (beat / self.SWEEP) % 1.0
        ages = ((head - us) % 1.0) * self.SWEEP
        ys = base - amp * ecg(((beat - ages) % self.PERIOD) / self.PERIOD)
        xs = x0 + us * (x1 - x0)
        green = hexc("#6BE3A6")
        step = 12
        for a in range(0, n - 1, step):
            b = min(n, a + step + 1)
            age = float(ages[a:b].max())
            if age > self.SWEEP * 0.9:   # the gap just ahead of the sweep
                continue
            pts = np.stack([xs[a:b], ys[a:b]], 1)
            fade = 1 - age / self.SWEEP
            p.poly(tube(pts, 2.0, k=1), green, 0.9 * fade, add=True)
            p.poly(tube(pts, 7.0, k=1), green, 0.18 * fade, soft=2.0, add=True)
        hy = ys[int(head * (n - 1))]
        p.glow(x0 + head * (x1 - x0), hy, 6, 6, green, 0.8)

    def frame(self, index: int, st: dict) -> np.ndarray:
        W, H = self.size
        frame = np.zeros((H, W, 3), np.float32)
        at = st["cam"]
        for layer in self.back:
            layer.composite(frame, at)
        self.bed_back.composite(frame, at)
        hp = self.her.paint(at)
        self._draw_her(hp, st.get("her_eyes") or Eyes(open_=0.0), st.get("her_turn", 0.0))
        self.her.composite(frame, hp, rim_light=self.rim_at(0.70, at, self.LIGHT_FROM, px=2.6, glow=4.0, strength=0.55))
        self.bed_front.composite(frame, at)
        self.table.composite(frame, at)
        for layer in self.light:
            layer.composite(frame, at)
        tp = self.trace.paint(at)
        self._draw_trace(tp, st["beat"])
        self.trace.composite(frame, tp)
        fp = self.figure.paint(at)
        if "actors" in st:
            for a in st["actors"]:
                S.draw_person(fp, a["pose"], a["look"], a.get("eyes"))
        else:
            self.hero.draw_standing(fp, st["x"], self.FLOOR, st["pose"])
        self.figure.composite(frame, fp, rim_light=self.rim_at(0.70, at, self.LIGHT_FROM))
        self.curtain.composite(frame, at)
        return self.finish_frame(frame, index, st)
