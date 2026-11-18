"""
The silhouette look's places (beyond the three of the style tests in tools/silhouette_sets.py), each in four lights (dusk,
night, dawn, day: LIGHTS, in the family of the owner's palette) and in rain. A place is a Room (an interior seen from the
side: a back wall with a window onto the sky and the city, a floor, furniture, a hanging lamp's cone with dust in it) or
an Outdoor (sky, far city, buildings or trees, the ground, street lamps); its own class adds what makes it that place.

Every place has MARKS: where a person stands, sits, lies, walks or runs there (agents/story.py's poses are placed on
them by tools/silhouette_render.py), and its frame(index, st) draws one moment: st["actors"] are the people in it
({"pose": silhouette.pose_*, "look", "eyes", "slot": "main" or "bed" (under a blanket)}), st["lamp"] the hanging lamp
(1 on, 0 off), st["cam"], st["label"], st["still"], st["fade"] (silhouette_sets.Stage).

The rules are the owner's look (prompts/look_silhouette.txt.enc): flat shapes with one lit edge, no outlines, light does
the mood (the low sun or the moon behind the window, the lamp's soft cone with dust, screens' cool glow), the red rim on
the people, haze and a touch of blur far away, a strong vignette, letterbox bars and fine grain. No neon tubes, no lens
flares, nothing flickering.
"""

import math

import numpy as np

import silhouette as S
from silhouette import PAL, Dynamic, Paint, ell, hexc, rect, rr, spline, tube
from silhouette_sets import Rain, Stage, falling, flat, gradient, rng

LIGHTS = {  # sky stops (0 at the top of the sky .. 1 at the horizon), the sun or the moon, the city, the room
    "dusk": {"sky": [(0, "#2F2A57"), (0.30, "#463566"), (0.48, "#7A4E7A"), (0.62, "#B3687C"), (0.78, "#EE8F67"),
                     (0.90, "#FFD7A0"), (1.0, "#FFD7A0")],
             "sun": ("#FFE9C8", 0.55), "moon": None, "far": "#C7939F", "near": "#2A1830", "lit": 0.30, "win": "#FFC383",
             "wall": ("#48304F", "#170F1D"), "floor": "#120C15", "lamp": True, "haze": ("#F4C4A6", 0.30),
             "spill": (0.55, 0.26, 0.20), "stars": 0.5, "cloud": "#C996AE", "ground": "#1A121F"},
    "night": {"sky": [(0, "#0B0918"), (0.45, "#16112A"), (0.80, "#2A1D3E"), (1.0, "#45294A")],
              "sun": None, "moon": ("#ECE6F4", 0.30), "far": "#2E2346", "near": "#150F1E", "lit": 0.55,
              "win": "#FFC383", "wall": ("#30253F", "#0E0A14"), "floor": "#0C0910", "lamp": True,
              "haze": ("#5A4570", 0.20), "spill": (0.22, 0.24, 0.40), "stars": 1.0, "cloud": "#3A2E52", "ground": "#100C15"},
    "dawn": {"sky": [(0, "#2B2A55"), (0.40, "#5E5486"), (0.62, "#B87C96"), (0.80, "#F2A98A"), (0.92, "#FFE0B5"),
                     (1.0, "#FFF0D2")],
             "sun": ("#FFF4DC", 0.50), "moon": None, "far": "#A08AAE", "near": "#2E2238", "lit": 0.06, "win": "#FFD9A0",
             "wall": ("#4E3D5E", "#1B1426"), "floor": "#141019", "lamp": False, "haze": ("#F6D2C2", 0.32),
             "spill": (0.50, 0.36, 0.30), "stars": 0.15, "cloud": "#E3A9B4", "ground": "#1D1622"},
    "day": {"sky": [(0, "#5E6FA8"), (0.45, "#8C98C6"), (0.80, "#C9BBD6"), (1.0, "#E8D6CF")],
            "sun": None, "moon": None, "far": "#9A92B6", "near": "#3B3150", "lit": 0.0, "win": "#FFE2B4",
            "wall": ("#5D4C6C", "#241B2E"), "floor": "#1A141F", "lamp": False, "haze": ("#E8DCE6", 0.30),
            "spill": (0.40, 0.38, 0.46), "stars": 0.0, "cloud": "#E9E1EE", "ground": "#211A27"},
}
RAINY = "#3A3550"   # what rain mixes into a sky


def mix(a, b, t):
    a = hexc(a) if isinstance(a, str) else np.asarray(a, np.float32)
    b = hexc(b) if isinstance(b, str) else np.asarray(b, np.float32)
    return a * (1 - t) + b * t


def sky(p: Paint, L: dict, x0, x1, top, horizon, sun_x, rain=False, seed="sky"):
    """The sky between `top` and the `horizon` (world y), in the light's colours, with its sun (dusk, dawn), its moon or
    its stars, a few thin streaks of cloud; greyed and starless in rain."""
    stops = [(top + (horizon - top) * u, c) for u, c in L["sky"]]
    if rain:
        stops = [(y, "#%02x%02x%02x" % tuple(int(v * 255) for v in mix(c, RAINY, 0.45))) for y, c in stops]
    p.poly(rect(x0, top - 600, x1 - x0, horizon - top + 1200), gradient(stops)(p))
    if L["sun"] and not rain:
        col, strength = L["sun"]
        p.glow(sun_x, horizon - 10, 120, 50, (1.0, 0.78, 0.52), strength)
        p.glow(sun_x, horizon - 10, 380, 130, (1.0, 0.60, 0.44), strength * 0.4)
        p.circle(sun_x, horizon - 12, 18, hexc(col))
    if L["moon"] and not rain:
        col, strength = L["moon"]
        my = top + (horizon - top) * 0.28
        p.glow(sun_x, my, 70, 70, (0.75, 0.75, 0.92), strength)
        p.circle(sun_x, my, 20, hexc(col))
    r = rng(seed, "clouds")
    for _ in range(4):
        cx, cy = r.uniform(x0, x1), top + (horizon - top) * r.uniform(0.25, 0.7)
        p.poly(ell(cx, cy, r.uniform(120, 300), r.uniform(3, 5), 96), hexc(L["cloud"]), 0.35 if not rain else 0.15,
               soft=2.0)
    if not rain:
        for _ in range(int(24 * L["stars"])):
            p.circle(r.uniform(x0, x1), top + (horizon - top) * r.uniform(0.02, 0.55), r.uniform(0.8, 1.4), PAL["label"],
                     float(r.uniform(0.4, 0.85)))


def city(p: Paint, base, x0, x1, tops, widths, color, seed, win=None, lit=0.0, cell=(10.0, 14.0), size=(4.0, 5.0)):
    """A skyline: blocks between tops (world y) and `base`, `lit` of their windows lit in `win`."""
    r = rng("city", seed)
    x, shapes, wins = x0, [], []
    while x < x1:
        w = r.uniform(*widths)
        top = r.uniform(*tops)
        shapes.append(rect(x, top, w + 1, base - top + 80))
        if r.random() < 0.25:
            sw = w * r.uniform(0.3, 0.6)
            shapes.append(rect(x + (w - sw) / 2, top - r.uniform(6, 16), sw, 30))
        if win and lit > 0:
            for wy in np.arange(top + 8, base - 4, cell[1]):
                for wx in np.arange(x + 5, x + w - 6, cell[0]):
                    if r.random() < lit:
                        wins.append(rect(wx, wy, *size))
        x += w
    p.poly(None, hexc(color) if isinstance(color, str) else np.asarray(color, np.float32), polys=shapes)
    for wv in wins:
        p.poly(wv, hexc(win), 0.9)


def lit_edge(p: Paint, pts_top_y, x0, x1, color="#7A6068", alpha=0.85, h=3.0):
    """A prop's one lit edge: a thin bright line along its top."""
    p.poly(rect(x0, pts_top_y, x1 - x0, h), hexc(color), alpha)


# --- an interior ------------------------------------------------------------------------------------------------------------
class Room(Stage):
    """An interior seen from the side. A subclass sets WINDOW (x0, y0, x1, y1, cols, rows), LAMP (the hanging lamp's
    shade, or None) and LAMP_TO (where its cone lands), and draws _decor (on the wall), _back (furniture against the
    wall), _mid (furniture beside the people), _front (in front of a person in bed: the blanket), _glows (screens, other
    lamps: light)."""

    WINDOW = None
    FLOOR = 300.0
    LAMP = None
    LAMP_TO = 300.0
    CENTER, HEIGHT, TALL_WIDTH = (0.0, 0.0), 900.0, 720.0
    R = 64.0
    PLANT = False
    WALL_TINT = None     # the room's own wall colour, mixed into the light's
    SPAN = (-1300.0, 1300.0)
    ALWAYS_LIT = False   # the hanging lamp is on in every light (a hall's bare bulb), not only at dusk and night
    MARKS: dict = {}

    def __init__(self, size, light="night", rain=False, center=None):
        super().__init__(size, center or self.CENTER, self.HEIGHT, self.TALL_WIDTH)
        self.light, self.L, self.rain = light, LIGHTS[light], bool(rain)
        self.lamp_on = bool(self.LAMP) and (self.L["lamp"] or self.rain or self.ALWAYS_LIT)
        self._tau = 0.0
        self.view = self._make_view() if self.WINDOW else []
        self.back = [self.static(0.60, self._wall), self.static(0.60, self._spill, add=True, blur=3.0),
                     self.static(0.66, self._back)]
        self.lamp_shape = self.static(0.70, self._lamp) if self.LAMP else None
        self.mid = self.static(0.72, self._mid)
        self.people = {"bed": Dynamic(self.cam, 0.72), "main": Dynamic(self.cam, 0.72)}
        self.front = self.static(0.72, self._front)
        self.glows = self.static(0.72, self._glows, add=True, blur=2.5)
        self.cone = self.static(0.70, self._cone, add=True, blur=2.0) if self.lamp_on else None
        self.light_fx = Dynamic(self.cam, 0.72, add=True)
        self.dust = Dynamic(self.cam, 0.70, add=True) if self.lamp_on else None
        self.wet = Dynamic(self.cam, 0.60, add=True) if self.rain and self.WINDOW else None
        self.plant = (self.static(1.7, self._plant, blur=6.0 * self.k,
                                  rim_light=(-3 * self.k, -1 * self.k, PAL["rim"], 4.0, 0.3, 0.45))
                      if self.PLANT else None)
        r = rng("dust", type(self).__name__)
        self.dust_seed = {"u": r.uniform(0, 1, 50), "v": r.uniform(0, 1, 50), "vx": r.normal(0, 0.012, 50),
                          "vy": r.uniform(0.006, 0.028, 50), "ph": r.uniform(0, math.tau, 50),
                          "size": r.uniform(0.8, 1.9, 50), "a": r.uniform(0.35, 0.95, 50)}
        r = rng("drops", type(self).__name__)
        self.drops = {"x": r.uniform(0, 1, 70), "y": r.uniform(0, 1, 70), "sp": r.uniform(0.02, 0.12, 70),
                      "r": r.uniform(1.2, 3.0, 70)}

    def _make_view(self):
        """What the window shows: the sky, the far city, the near city (tools/silhouette_scene.py's vehicles scroll it)."""
        return [self.static(0.10, self._sky, blur=1.2), self.static(0.20, self._far, blur=1.4),
                self.static(0.32, self._near, blur=0.8)]

    def fx(self, frame, at, tau, stage):
        """A place's moving parts and effects at a stage of the frame (tools/silhouette_fx.py): "view" (beyond the
        window), "back" (behind the people), "front" (over them). The places here have none."""

    # --- the wall and the window ------------------------------------------------------------------------------------------
    def window_center(self):
        if not self.WINDOW:
            return (self.CENTER[0] - 600, -200.0)
        x0, y0, x1, y1 = self.WINDOW[:4]
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    def _sky(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        sky(p, self.L, x0 - 500, x1 + 500, y0 - 60, y1 + 10, (x0 + x1) / 2 - (x1 - x0) * 0.22, self.rain,
            seed=type(self).__name__)

    def _far(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        city(p, y1 + 30, x0 - 500, x1 + 500, (y1 - 150, y1 - 60), (22, 60), self.L["far"], type(self).__name__ + "far")
        p.poly(rect(x0 - 500, y1 - 90, x1 - x0 + 1000, 140), flat(self.L["haze"][0]), self.L["haze"][1], soft=24)

    def _near(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        city(p, y1 + 60, x0 - 500, x1 + 500, (y1 - 90, y1 - 20), (30, 80), self.L["near"], type(self).__name__ + "near",
             win=self.L["win"], lit=self.L["lit"] * (0.8 if self.rain else 1.0))

    def wall_colors(self):
        near, far = self.L["wall"]
        if self.WALL_TINT:
            return mix(near, self.WALL_TINT, 0.35), mix(far, self.WALL_TINT, 0.15)
        return hexc(near), hexc(far)

    def _wall(self, p: Paint):
        near, far = self.wall_colors()
        cx, cy = self.window_center()

        def wall(px, py):
            d = np.sqrt(((p.wx(px) - cx) / 900) ** 2 + ((p.wy(py) - cy) / 620) ** 2)
            t = np.clip(d, 0, 1)[..., None] ** 0.8
            return near * (1 - t) + far * t
        p.poly(rect(self.SPAN[0] - 400, -1200, self.SPAN[1] - self.SPAN[0] + 800, self.FLOOR + 1200), wall)
        p.poly(rect(self.SPAN[0] - 400, self.FLOOR, self.SPAN[1] - self.SPAN[0] + 800, 700), hexc(self.L["floor"]))
        p.poly(rect(self.SPAN[0] - 400, self.FLOOR - 12, self.SPAN[1] - self.SPAN[0] + 800, 12), mix(far, "#000000", 0.2))
        if self.WINDOW:
            x0, y0, x1, y1, cols, rows = self.WINDOW
            p.poly(rr(x0 - 14, y0 - 14, x1 - x0 + 28, y1 - y0 + 28, 4), hexc("#16101E"))
            bar = 10.0
            pw = (x1 - x0 - bar * (cols - 1)) / cols
            ph = (y1 - y0 - bar * (rows - 1)) / rows
            for c in range(cols):
                for r_ in range(rows):
                    p.cut(rect(x0 + c * (pw + bar), y0 + r_ * (ph + bar), pw, ph))
            p.poly(rect(x0 - 26, y1 + 14, x1 - x0 + 52, 9), mix(near, "#FFFFFF", 0.12))
            p.poly(rect(x0 - 22, y1 + 23, x1 - x0 + 44, 8), mix(far, "#000000", 0.1))
        self._decor(p)

    def _spill(self, p: Paint):
        if not self.WINDOW:
            return
        cx, cy = self.window_center()
        x0, y0, x1, y1 = self.WINDOW[:4]
        s = self.L["spill"]
        p.glow(cx, cy, (x1 - x0) * 0.75, (y1 - y0) * 0.75, s, 0.16 if not self.rain else 0.08)
        p.poly(np.array([(x0, y1 + 20), (x1, y1 + 20), (x1 + 160, self.FLOOR + 40), (x0 - 160, self.FLOOR + 40)], float),
               falling(p, y1 + 20, self.FLOOR + 40, s, 0.10 if not self.rain else 0.05, 0.02), soft=26)

    def _lamp(self, p: Paint):
        x, y = self.LAMP
        p.poly(rect(x - 1.6, -1400, 3.2, y - 26 + 1400), hexc("#140D17"))
        shade = spline([(x - 12, y - 30), (x + 12, y - 30), (x + 44, y - 6), (x + 58, y + 18), (x, y + 21),
                        (x - 58, y + 18), (x - 44, y - 6)], True, 8)
        p.poly(shade, PAL["shade"])
        p.poly(spline([(x + 12, y - 28), (x + 44, y - 5), (x + 56, y + 16), (x + 52, y + 17), (x + 40, y - 3),
                       (x + 10, y - 26)], True, 6), hexc("#4A3346"), 0.8)
        p.poly(ell(x, y + 18.5, 56, 4.5, 64), hexc("#FFF5E1") if self.lamp_on else hexc("#4A3A44"))

    def _cone(self, p: Paint):
        x, y = self.LAMP
        top, bot = y + 20, self.LAMP_TO

        def fall(px, py):
            u = np.clip((p.wy(py) - top) / max(bot - top, 1), 0, 1)[..., None]
            return PAL["lamp"] * (0.28 * (1 - u) ** 1.4 + 0.06)
        spread = (bot - top) * 0.36
        p.poly(np.array([(x - 52, top), (x + 52, top), (x + 52 + spread, bot), (x - 52 - spread, bot)], float), fall,
               soft=9)
        p.glow(x, top, 60, 13, PAL["lamp"], 0.30)
        p.glow(x, bot, min(52 + spread, 130), 7, PAL["lamp"], 0.26)

    def _plant(self, p: Paint):
        W, H = self.size
        v = p.v
        base = ((-0.06 * W + p.v.ox - W / 2 - v.ox) / v.z + v.cx, (1.0 * H + p.v.oy - H / 2 - v.oy) / v.z + v.cy)
        span = (1.0 * W if self.tall else 0.62 * H) / v.z
        for ang, length, width in ((-1.55, 0.45, 0.060), (-1.30, 0.62, 0.075), (-1.05, 0.58, 0.072),
                                   (-0.80, 0.55, 0.070), (-0.55, 0.50, 0.065)):
            L = span * length
            tip = (base[0] + math.cos(ang) * L, base[1] + math.sin(ang) * L)
            mid = ((base[0] + tip[0]) / 2 + math.sin(ang) * L * 0.08, (base[1] + tip[1]) / 2 - math.cos(ang) * L * 0.04)
            sp = spline([base, mid, tip], closed=False, k=16)
            tg = np.gradient(sp, axis=0)
            tg /= np.maximum(np.hypot(tg[:, 0], tg[:, 1]), 1e-9)[:, None]
            nrm = np.stack([-tg[:, 1], tg[:, 0]], 1)
            u = np.linspace(0, 1, len(sp))[:, None]
            wdt = span * width * np.sin(np.pi * np.clip(u * 0.92 + 0.04, 0, 1)) ** 0.8
            p.poly(np.vstack([sp + nrm * wdt, (sp - nrm * wdt)[::-1]]), hexc("#0C080E"))

    # --- what a place adds --------------------------------------------------------------------------------------------------
    def _decor(self, p: Paint):
        pass

    def _back(self, p: Paint):
        pass

    def _mid(self, p: Paint):
        pass

    def _front(self, p: Paint):
        pass

    def _glows(self, p: Paint):
        pass

    # --- a moment ---------------------------------------------------------------------------------------------------------
    def rim_dir(self, x):
        cx, cy = self.window_center()
        d = -1.0 if cx < x else 1.0
        return (d, -0.40)

    def draw_people(self, frame, at, st, slot):
        acts = [a for a in st.get("actors") or [] if a.get("slot", "main") == slot]
        if not acts:
            return []
        layer = self.people[slot]
        p = layer.paint(at)
        glows = []
        for a in acts:
            got = S.draw_person(p, a["pose"], a["look"], a.get("eyes"))
            if got.get("glow"):
                glows.append((got["glow"], a["pose"]["R"], got["head"]))
        x = acts[0]["pose"]["head"][0]
        layer.composite(frame, p, rim_light=self.rim_at(0.72, at, self.rim_dir(x), strength=0.95))
        return glows

    def _draw_dust(self, p: Paint, tau: float):
        x, y = self.LAMP
        top, bot = y + 24, self.LAMP_TO - 8
        spread = (bot - top) * 0.36
        d = self.dust_seed
        v = (d["v"] + d["vy"] * tau + 0.01 * np.sin(tau * 0.7 + d["ph"])) % 1.0
        yy = top + v * (bot - top)
        half = 50 + spread * v
        u = (d["u"] + d["vx"] * tau + 0.02 * np.sin(tau * 0.5 + d["ph"] * 1.3)) % 1.0
        xx = x - half + u * 2 * half
        strength = (1 - v) ** 0.8 * d["a"]
        for xi, yi, si, ai in zip(xx, yy, d["size"], strength):
            p.circle(xi, yi, si * 1.05, PAL["lamp"], float(ai) * 0.8, add=True)

    def _draw_wet(self, p: Paint, tau: float):
        """Rain on the window: drops on the glass, a few running down, and faint streaks beyond it."""
        x0, y0, x1, y1 = self.WINDOW[:4]
        d = self.drops
        ys = y0 + ((d["y"] + d["sp"] * tau) % 1.0) * (y1 - y0)
        xs = x0 + d["x"] * (x1 - x0)
        col = mix("#C9C3E0", self.L["spill"], 0.3)
        for xi, yi, ri in zip(xs, ys, d["r"]):
            p.circle(xi, yi, ri, col, 0.35, add=True)
        r = rng("streaks", int(tau * 24) % 6)
        for _ in range(26):
            sx, sy = r.uniform(x0, x1), r.uniform(y0, y1 - 30)
            p.poly(tube([(sx, sy), (sx - 5, sy + 26)], 1.1), col, 0.16, add=True)

    def frame(self, index: int, st: dict) -> np.ndarray:
        W, H = self.size
        frame = np.zeros((H, W, 3), np.float32)
        at = st["cam"]
        tau = st.get("tau", index / S.FPS)
        lamp = float(st.get("lamp", 1.0))
        self._tau = tau
        for layer in self.view:
            layer.composite(frame, at)
        self.fx(frame, at, tau, "view")
        for layer in self.back:
            layer.composite(frame, at)
        if self.wet is not None:
            wp = self.wet.paint(at)
            self._draw_wet(wp, tau)
            self.wet.composite(frame, wp)
        if self.lamp_shape is not None:
            self.lamp_shape.composite(frame, at)
        self.mid.composite(frame, at)
        self.fx(frame, at, tau, "back")
        glows = self.draw_people(frame, at, st, "bed")
        self.front.composite(frame, at)
        glows += self.draw_people(frame, at, st, "main")
        self.glows.composite(frame, at)
        if self.cone is not None:
            self.cone.composite(frame, at, gain=lamp)
        fx = self.light_fx.paint(at)
        for (gx, gy), R, (hx, hy) in glows:
            fx.glow(gx, gy, 0.9 * R, 0.9 * R, PAL["screen"], 0.55)
            fx.glow(hx, hy, 1.0 * R, 0.9 * R, PAL["screen"], 0.12)
        self.light_fx.composite(frame, fx)
        if self.dust is not None and lamp > 0.5:
            dp = self.dust.paint(at)
            self._draw_dust(dp, st.get("dust", tau))
            self.dust.composite(frame, dp)
        self.fx(frame, at, tau, "front")
        if self.plant is not None:
            self.plant.composite(frame, at)
        return self.finish_frame(frame, index, st)


# --- outdoors ----------------------------------------------------------------------------------------------------------------
class Outdoor(Stage):
    """A place outdoors seen from the side: the sky down to HORIZON, the far city, what stands behind (_backdrop:
    buildings, trees), the ground (_ground), street lamps (LAMPS: their poles' x; lit at dusk and night), things beside
    the people (_props), and rain. Subclasses draw the rest."""

    GROUND = 300.0
    HORIZON = 150.0
    SPAN = (-1700.0, 1700.0)
    PAN = (640.0, 40.0)
    LAMPS: tuple = ()
    LAMP_Y = -262.0
    CENTER, HEIGHT, TALL_WIDTH = (0.0, 40.0), 900.0, 700.0
    R = 58.0
    MARKS: dict = {}

    def __init__(self, size, light="dusk", rain=False, center=None):
        super().__init__(size, center or self.CENTER, self.HEIGHT, self.TALL_WIDTH)
        self.light, self.L, self.rain = light, LIGHTS[light], bool(rain)
        self.lamps_on = self.L["lamp"] or self.rain
        self._tau = 0.0
        self.back = [self.static(0.06, self._sky, blur=1.2), self.static(0.18, self._far, blur=1.6)]
        self.backdrop = [self.static(0.42, self._backdrop), self.static(0.42, self._backdrop_light, add=True, blur=4.0)]
        self.ground = self.static(0.70, self._ground)
        self.ground_light = self.static(0.72, self._ground_light, add=True, blur=2.5)
        self.lamp_shapes = self.static(0.74, self._lamps)
        self.lamp_glow = self.static(0.74, self._lamp_glow, add=True) if self.lamps_on else None
        self.props = self.static(0.70, self._props)
        self.people = {"main": Dynamic(self.cam, 0.70)}
        self.glow_fx = Dynamic(self.cam, 0.70, add=True)
        self.rainfx = Rain(size, seed=type(self).__name__) if self.rain else None
        self.fore = None   # things out of focus in front of the lens (tools/silhouette_scene.py)

    def fx(self, frame, at, tau, stage):
        """A place's moving parts and effects at a stage of the frame (tools/silhouette_fx.py): "far" (over the far
        layers), "back" (behind the people), "front" (over them). The places here have none."""

    def _sky(self, p: Paint):
        sky(p, self.L, self.SPAN[0] - 600, self.SPAN[1] + 600, -900, self.HORIZON, 380.0, self.rain, type(self).__name__)

    def _far(self, p: Paint):
        city(p, self.HORIZON + 80, self.SPAN[0] - 600, self.SPAN[1] + 600, (self.HORIZON - 210, self.HORIZON - 60),
             (30, 110), mix(self.L["far"], RAINY, 0.3) if self.rain else self.L["far"], type(self).__name__ + "far",
             win=self.L["win"], lit=self.L["lit"] * 0.5, cell=(14, 18))
        p.poly(rect(self.SPAN[0] - 600, self.HORIZON - 120, self.SPAN[1] - self.SPAN[0] + 1200, 220),
               flat(self.L["haze"][0]), self.L["haze"][1], soft=30)

    def _backdrop(self, p: Paint):
        pass

    def _backdrop_light(self, p: Paint):
        pass

    def _ground(self, p: Paint):
        p.poly(rect(self.SPAN[0] - 900, self.GROUND - 120, self.SPAN[1] - self.SPAN[0] + 1800, 900),
               gradient([(self.GROUND - 120, self.L["ground"]), (self.GROUND + 80, "#0B0910")])(p))

    def _ground_light(self, p: Paint):
        if not self.lamps_on:
            return
        for L in self.LAMPS:
            hx = L - 85
            top = self.LAMP_Y + 10
            p.poly(np.array([(hx - 20, top), (hx + 20, top), (hx + 250, self.GROUND + 10), (hx - 250, self.GROUND + 10)]),
                   falling(p, top, self.GROUND, PAL["lamp"], 0.24, 0.04), soft=18)
            p.glow(hx, self.GROUND, 250, 30, PAL["lamp"], 0.38)

    def _lamps(self, p: Paint):
        dark = hexc("#0E0A12")
        for L in self.LAMPS:
            hx, y = L - 85, self.LAMP_Y
            p.poly(rect(L - 6, y - 6, 12, self.GROUND + 40 - y), dark)
            p.poly(rr(L - 15, self.GROUND - 10, 30, 40, 4), dark)
            p.poly(tube([(L, y), (L - 18, y - 34), (L - 52, y - 40), (hx + 16, y - 24)], 9.0), dark)
            p.poly(np.array([(hx - 36, y - 24), (hx + 32, y - 24), (hx + 22, y - 4), (hx - 26, y - 4)]), hexc("#120D16"))
            p.poly(ell(hx, y - 3, 25, 5, 40), hexc("#FFF1D6") if self.lamps_on else hexc("#4A3A44"))

    def _lamp_glow(self, p: Paint):
        for L in self.LAMPS:
            p.glow(L - 85, self.LAMP_Y, 60, 24, PAL["lamp"], 0.55)
            p.glow(L - 85, self.LAMP_Y + 10, 170, 90, PAL["lamp"] * 0.5, 0.16)

    def _props(self, p: Paint):
        pass

    def rim_dir(self, x):
        if self.L["sun"] and not self.rain:
            return (1.0 if x < 380 else -1.0, -0.35)
        return (0.25, -1.0)

    def frame(self, index: int, st: dict) -> np.ndarray:
        W, H = self.size
        frame = np.zeros((H, W, 3), np.float32)
        at = st["cam"]
        tau = st.get("tau", index / S.FPS)
        self._tau = tau
        for layer in self.back:
            layer.composite(frame, at)
        self.fx(frame, at, tau, "far")
        for layer in self.backdrop:
            layer.composite(frame, at)
        self.ground.composite(frame, at)
        self.ground_light.composite(frame, at)
        self.lamp_shapes.composite(frame, at)
        if self.lamp_glow is not None:
            self.lamp_glow.composite(frame, at)
        self.props.composite(frame, at)
        self.fx(frame, at, tau, "back")
        acts = st.get("actors") or []
        if acts:
            layer = self.people["main"]
            p = layer.paint(at)
            glows = []
            for a in acts:
                got = S.draw_person(p, a["pose"], a["look"], a.get("eyes"))
                if got.get("glow"):
                    glows.append((got["glow"], a["pose"]["R"], got["head"]))
            layer.composite(frame, p, rim_light=self.rim_at(0.70, at, self.rim_dir(acts[0]["pose"]["head"][0])))
            if glows:
                fx = self.glow_fx.paint(at)
                for (gx, gy), R, (hx, hy) in glows:
                    fx.glow(gx, gy, 0.9 * R, 0.9 * R, PAL["screen"], 0.55)
                    fx.glow(hx, hy, 1.0 * R, 0.9 * R, PAL["screen"], 0.12)
                self.glow_fx.composite(frame, fx)
        self.fx(frame, at, tau, "front")
        if self.fore is not None:
            self.fore.composite(frame, at)
        if self.rainfx is not None:
            v = self.cam.view(0.74, *at)
            lights = [(*v.pt(L - 85, self.LAMP_Y), 26 * v.z) for L in self.LAMPS] if self.lamps_on else []
            g = self.cam.view(0.70, *at)
            band = (g.pt(0, self.GROUND - 100)[1], min(H - self.finish.bar, g.pt(0, self.GROUND + 50)[1]))
            self.rainfx.draw(frame, tau, (at[0] - self.cam.rest[0]) * self.k, lights, band)
        return self.finish_frame(frame, index, st)


# --- furniture: flat shapes with one lit edge ----------------------------------------------------------------------------------
WOOD, WOOD_EDGE, DARK, DARK_EDGE = "#2E2130", "#7A6068", "#1C1424", "#4A3C58"


def chair(p: Paint, x, seat_y, f, floor, color=DARK, edge=DARK_EDGE):
    """A chair seen from the side, its seat's middle at x, the person on it facing f (its back behind them)."""
    bx = x - f * 62
    p.poly(rect(min(bx, bx + f * 10) - 4, seat_y - 120, 12, 120 + (floor - seat_y)), hexc(color))
    p.poly(rect(x - 60, seat_y, 120, 11), hexc(color))
    lit_edge(p, seat_y, x - 60, x + 60, edge, 0.8, 2.5)
    p.poly(rect(x + f * 50 - 5, seat_y + 10, 10, floor - seat_y - 10), hexc(color))


def table(p: Paint, x0, x1, top, floor, color=WOOD, edge=WOOD_EDGE, legs=True):
    p.poly(rect(x0, top, x1 - x0, 10), hexc(color))
    lit_edge(p, top - 1, x0, x1, edge, 0.85, 3.0)
    if legs:
        for lx in (x0 + 14, x1 - 24):
            p.poly(rect(lx, top + 10, 10, floor - top - 10), mix(color, "#000000", 0.25))


def frame_picture(p: Paint, x0, y0, x1, y1, inner="#33263C", hill="#4B3A55"):
    p.poly(rr(x0, y0, x1 - x0, y1 - y0, 2), PAL["frame"])
    p.poly(rect(x0 + 6, y0 + 6, x1 - x0 - 12, y1 - y0 - 12), hexc(inner))
    w, h = x1 - x0 - 12, y1 - y0 - 12
    p.poly(np.array([(x0 + 6, y1 - 6), (x0 + 6 + w * 0.35, y0 + 6 + h * 0.45), (x0 + 6 + w * 0.55, y0 + 6 + h * 0.7),
                     (x0 + 6 + w * 0.72, y0 + 6 + h * 0.5), (x1 - 6, y1 - 6)]), hexc(hill))


def plant_pot(p: Paint, x, floor, h=220, leaves=7, seed="pot", color="#1F2A2A"):
    p.poly(rr(x - 34, floor - 70, 68, 70, 6), hexc("#2A1D2E"))
    lit_edge(p, floor - 71, x - 34, x + 34, "#7A5C68", 0.7, 2.5)
    r = rng(seed)
    for _ in range(leaves):
        a = r.uniform(-1.2, 1.2)
        L = h * r.uniform(0.6, 1.0)
        tip = (x + math.sin(a) * L, floor - 70 - math.cos(a) * L)
        mid = (x + math.sin(a) * L * 0.5 + r.uniform(-20, 20), floor - 70 - math.cos(a) * L * 0.55)
        p.poly(tube([(x, floor - 66), mid, tip], 18.0, 3.0), hexc(color))


def books(p: Paint, x0, shelf_y, n, seed="books"):
    r = rng(seed)
    cols = ["#3B2A43", "#2E3446", "#4A2E3A", "#35283E", "#283545", "#41303F", "#2F2638"]
    x = x0
    for k in range(n):
        w, h = r.uniform(12, 20), r.uniform(56, 84)
        p.poly(rect(x, shelf_y - h, w, h), hexc(cols[k % len(cols)]))
        p.poly(rect(x, shelf_y - h, w, 1.6), hexc("#8A6A72"), 0.7)
        x += w + r.uniform(1, 3)
    return x


# --- his bedroom ---------------------------------------------------------------------------------------------------------------
class Bedroom(Room):
    """His bedroom: the bed along the left (he lies in it, the blanket over him; a phone's glow on his face at night), a
    window over the nightstand (its alarm clock's red glow, a small lamp), a wardrobe on the right."""

    WINDOW = (100.0, -330.0, 430.0, -40.0, 2, 2)
    CENTER = (-60.0, 0.0)
    MARKS = {
        "bed": {"kind": "lie", "x": -612.0, "y": 150.0, "f": 1, "slot": "bed"},
        "edge": {"kind": "sit", "x": -70.0, "seat": 200.0, "f": 1},
        "stand": {"kind": "stand", "x": 400.0, "f": -1},
        "window": {"kind": "stand", "x": 270.0, "f": -1, "lift": 0.15},
        "floor": {"kind": "floor", "x": 480.0, "f": -1},
        "pushup": {"kind": "pushup", "x": 150.0, "f": -1},
        "walk": {"kind": "walk", "from": 760.0, "to": 330.0, "f": -1},
    }

    def _decor(self, p: Paint):
        frame_picture(p, -620, -250, -520, -165)
        frame_picture(p, -480, -235, -410, -180, "#2E3446", "#3E4C60")
        x0, y0, x1, y1 = self.WINDOW[:4]
        drape = spline([(x0 - 70, y0 - 40), (x0 - 40, y0 + 60), (x0 - 60, y0 + 170), (x0 - 36, y1 + 60), (x0 - 10, y1 + 70),
                        (x0 - 18, y0 + 150), (x0 - 4, y0 + 40), (x0 - 10, y0 - 40)], True, 8)
        p.poly(drape, mix(self.wall_colors()[0], "#000000", 0.25))
        p.poly(tube([(x0 - 52, y0 - 30), (x0 - 44, y1 + 50)], 3.0), mix(self.wall_colors()[0], "#FFFFFF", 0.08), 0.6)

    def _back(self, p: Paint):
        # the wardrobe
        p.poly(rr(520, -270, 230, 570, 4), hexc("#20172A"))
        p.poly(rect(520, -270, 3, 570), hexc(DARK_EDGE), 0.8)
        p.poly(rect(634, -255, 2, 540), hexc("#120D18"))
        for x in (620, 648):
            p.poly(rr(x, 0, 5, 34, 2), hexc("#6A5A6A"))
        # the nightstand, its alarm clock and its little lamp
        p.poly(rr(90, 205, 110, 95, 4), hexc("#241A2C"))
        lit_edge(p, 203, 90, 200, WOOD_EDGE, 0.8, 3)
        p.poly(rect(100, 248, 90, 2), hexc("#140F1A"))
        p.poly(rr(104, 176, 46, 28, 5), hexc("#140F18"))
        for k in range(4):
            p.poly(rect(110 + k * 9 + (3 if k > 1 else 0), 184, 6, 11), hexc("#FF5A44"), 0.9)
        p.poly(rect(166, 150, 4, 54), hexc("#2A2030"))
        p.poly(np.array([(150, 128), (186, 128), (194, 152), (142, 152)], float), hexc("#4A3036"))
        if self.L["lamp"]:
            p.poly(ell(168, 152, 26, 3, 30), hexc("#FFE9C8"))
        # the bed: headboard, frame, mattress, pillow
        p.poly(rr(-722, 70, 34, 230, 8), hexc(DARK))
        p.poly(rect(-722, 72, 3, 226), hexc(DARK_EDGE), 0.7)
        p.poly(rr(-700, 198, 770, 44, 10), hexc("#3A3450"))
        p.poly(rect(-700, 242, 770, 18), hexc("#241C30"))
        for x in (-690, 50):
            p.poly(rect(x, 260, 14, 40), hexc("#1A1422"))
        p.poly(rr(-690, 152, 150, 52, 24), hexc("#77708C"))

    def _front(self, p: Paint):
        top = spline([(-566, 200), (-520, 160), (-420, 146), (-300, 150), (-160, 160), (-40, 170), (40, 188), (68, 210)],
                     closed=False, k=10)
        p.poly(np.vstack([top, [(68, 250), (-566, 250)]]), hexc("#4B4566"))
        p.poly(tube([(-566, 206), (-520, 168), (-460, 154)], 16.0, 12.0), hexc("#6C6688"))
        for a, b in (((-380, 158), (-360, 236)), ((-220, 160), (-190, 236)), ((-60, 176), (-40, 236))):
            p.poly(tube([a, b], 2.5), hexc("#3A3552"), 0.7)

    def _glows(self, p: Paint):
        p.glow(127, 190, 30, 14, (1.0, 0.30, 0.22), 0.30)
        if self.L["lamp"]:
            p.glow(168, 150, 90, 40, PAL["lamp"], 0.40)
            p.glow(168, 205, 110, 16, PAL["lamp"], 0.20)
            p.glow(168, 80, 160, 120, PAL["lamp"] * 0.5, 0.10)


# --- the kitchen ---------------------------------------------------------------------------------------------------------------
class Kitchen(Room):
    """The kitchen: the counter under a window on the left, the fridge, the small table under a hanging lamp with the
    bills on it (envelopes, one marked red), two chairs, the door to the hall on the right."""

    WINDOW = (-760.0, -300.0, -440.0, -40.0, 2, 1)
    LAMP = (165.0, -150.0)
    LAMP_TO = 150.0
    CENTER = (-60.0, 0.0)
    WALL_TINT = "#5A4048"
    MARKS = {
        "sit": {"kind": "sit", "x": -40.0, "seat": 212.0, "f": 1, "reach": (85.0, 146.0)},
        "sit_other": {"kind": "sit", "x": 370.0, "seat": 212.0, "f": -1, "reach": (245.0, 146.0)},
        "stand": {"kind": "stand", "x": -250.0, "f": 1},
        "stand_other": {"kind": "stand", "x": 520.0, "f": -1},
        "leave": {"kind": "walk", "from": 330.0, "to": 950.0, "f": 1},
        "walk": {"kind": "walk", "from": 700.0, "to": 180.0, "f": -1},
    }

    def _decor(self, p: Paint):
        for x0, x1 in ((-980, -800), (-420, -300)):
            p.poly(rr(x0, -310, x1 - x0, 150, 4), hexc("#2A1F30"))
            p.poly(rect(x0, -162, x1 - x0, 3), hexc(WOOD_EDGE), 0.6)
        p.circle(400, -200, 36, hexc("#1A1420"))
        p.circle(400, -200, 30, hexc("#C9BFC6"))
        p.poly(tube([(400, -200), (400, -222)], 3.0), hexc("#1A1420"))
        p.poly(tube([(400, -200), (414, -192)], 3.0), hexc("#1A1420"))

    def _back(self, p: Paint):
        p.poly(rect(-1000, 140, 700, 160), hexc("#241A2B"))
        lit_edge(p, 138, -1000, -300, WOOD_EDGE, 0.85, 4)
        for x in np.arange(-990, -310, 115):
            p.poly(rect(x + 6, 158, 100, 128), hexc("#2C2134"))
            p.poly(rr(x + 48, 170, 16, 4, 2), hexc("#6A5A6A"))
        p.poly(rr(-600, 96, 52, 44, 10), hexc("#1C1520"))                        # the kettle
        p.poly(tube([(-548, 108), (-530, 100)], 6.0), hexc("#1C1520"))
        p.poly(rect(-600, 94, 52, 3), hexc("#8A7078"), 0.7)
        p.poly(rr(-290, -230, 125, 530, 10), hexc("#3A3346"))                      # the fridge
        p.poly(rect(-290, -228, 3, 526), hexc("#7A6E86"), 0.7)
        p.poly(rect(-288, -60, 121, 3), hexc("#221C2A"))
        p.poly(rr(-185, -190, 6, 90, 3), hexc("#8A8098"))
        p.poly(rr(560, -260, 150, 560, 3), hexc("#2B1F2E"))                        # the door to the hall
        p.poly(rect(560, -260, 3, 560), hexc(DARK_EDGE), 0.8)
        p.poly(rr(578, 30, 26, 8, 3), hexc("#8A7A80"))
        p.poly(tube([(500, -160), (500, -140)], 4.0), hexc("#3A2E3C"))              # a coat on its hook
        p.poly(spline([(486, -140), (514, -140), (530, 0), (520, 70), (480, 70), (470, 0)], True, 6), hexc("#3D2F3A"))

    def _mid(self, p: Paint):
        chair(p, -40, 212, 1, self.FLOOR)
        chair(p, 370, 212, -1, self.FLOOR)
        table(p, 0, 330, 150, self.FLOOR)
        for k, (x, y, a) in enumerate(((118, 141, -0.05), (142, 138, 0.08), (170, 140, -0.02))):   # the bills
            c = np.array((x + 30, y + 4))
            rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            p.poly((rect(x, y, 60, 9) - c) @ rot.T + c, hexc("#D9D0C6" if k != 1 else "#E8DFD4"))
            if k == 1:
                p.poly((rect(x + 42, y + 1, 14, 7) - c) @ rot.T + c, hexc("#C8473A"), 0.9)
        p.poly(rr(262, 118, 26, 32, 4), hexc("#2B1F2F"))
        p.poly(rect(263, 118, 24, 3), hexc("#9A7A80"), 0.9)

    def _glows(self, p: Paint):
        if self.lamp_on:
            p.glow(165, 150, 120, 8, PAL["lamp"], 0.16)


# --- the hall and the front door ---------------------------------------------------------------------------------------------
class Hallway(Room):
    """The flat's narrow hall: the front door (open: the stairwell's warm light behind whoever stands in it), coats on
    hooks, shoes, a bare bulb overhead."""

    LAMP = (-80.0, -230.0)
    CENTER = (-40.0, 0.0)
    WALL_TINT = "#5A4048"
    MARKS = {
        "door": {"kind": "stand", "x": 70.0, "f": 1, "arms": "knock"},
        "stand": {"kind": "stand", "x": -150.0, "f": 1},
        "floor": {"kind": "floor", "x": -470.0, "f": 1},
        "walk": {"kind": "walk", "from": -720.0, "to": 250.0, "f": 1},
        "doorway": {"kind": "stand", "x": 290.0, "f": -1},
        "leave": {"kind": "walk", "from": 250.0, "to": 520.0, "f": 1},
    }

    ALWAYS_LIT = True

    def __init__(self, size, light="night", rain=False, center=None, open_door=False):
        self.open_door = open_door
        super().__init__(size, light, rain, center)

    def window_center(self):
        return (290.0, -60.0) if self.open_door else (-700.0, -200.0)

    def _decor(self, p: Paint):
        frame_picture(p, -580, -230, -480, -150)
        p.poly(rr(-392, -50, 22, 34, 3), hexc("#C9BFC6"), 0.8)
        for x in (-320, -270, -220):
            p.poly(tube([(x, -200), (x + 10, -186)], 5.0), hexc("#2A2030"))
        p.poly(spline([(-336, -186), (-300, -188), (-286, -20), (-300, 60), (-346, 60), (-352, -20)], True, 6),
               hexc("#3D2F3A"))
        p.poly(tube([(-232, -186), (-226, -60), (-238, 30)], 14.0, 10.0), hexc("#6A2A30"))   # a scarf

    def _back(self, p: Paint):
        p.poly(rect(140, -296, 290, 596), hexc("#160F18"))                          # the door's frame
        p.poly(rect(140, -296, 290, 4), hexc(DARK_EDGE), 0.8)
        if self.open_door:
            p.poly(rect(160, -280, 250, 580), gradient([(-280, "#6A4A48"), (100, "#B88060"), (300, "#7A5248")])(p))
            p.poly(rect(160, -280, 10, 580), hexc("#3A2A30"))
            p.poly(rect(395, -280, 22, 580), hexc("#3A2A3A"))                        # the door, open, edge-on
        else:
            p.poly(rect(160, -280, 250, 580), hexc("#3A2A3A"))
            for y0, y1 in ((-250, -40), (10, 270)):
                p.poly(rr(190, y0, 190, y1 - y0, 3), hexc("#33253A"))
                p.poly(rect(190, y0, 190, 2), hexc("#5A4658"), 0.7)
            p.circle(285, -110, 5, hexc("#8A7A80"))
            p.poly(rr(372, 20, 26, 8, 3), hexc("#9A8A90"))
        p.poly(rect(-230, 262, 170, 8), hexc("#2A2030"))                              # shoes on a rack
        for x in (-220, -170, -120):
            p.poly(rr(x, 240, 44, 20, 8), hexc("#140F18"))

    def _glows(self, p: Paint):
        if self.open_door:
            p.poly(np.array([(160, 300), (410, 300), (470, 360), (100, 360)], float), flat("#E0A070"), 0.25, soft=12,
                   add=True)
            p.glow(285, 0, 140, 280, (0.70, 0.45, 0.30), 0.18)


# --- the office ----------------------------------------------------------------------------------------------------------------
class Office(Room):
    """An office floor: a wall of windows onto the city, a back row of desks with their screens' glow, his desk with its
    monitor, the boss's glass door on the right."""

    WINDOW = (-920.0, -330.0, 380.0, 40.0, 6, 2)
    CENTER = (-60.0, 0.0)
    WALL_TINT = "#3E4058"
    MARKS = {
        "desk": {"kind": "sit", "x": -80.0, "seat": 212.0, "f": 1, "reach": (60.0, 156.0)},
        "stand": {"kind": "stand", "x": 300.0, "f": 1},
        "boss": {"kind": "stand", "x": 520.0, "f": -1},
        "walk": {"kind": "walk", "from": 300.0, "to": -760.0, "f": -1},
    }

    def _back(self, p: Paint):
        for x in (-760, -420):
            table(p, x, x + 260, 170, self.FLOOR, "#2A2436", "#6A6080")
            p.poly(rr(x + 150, 92, 90, 70, 4), hexc("#16131E"))
            p.poly(rr(x + 156, 98, 78, 54, 3), hexc("#6F86B8") if self.light in ("night", "dusk") else hexc("#3A4660"), 0.9)
            p.poly(rect(x + 192, 162, 8, 10), hexc("#16131E"))
        if self.light in ("day", "dusk"):
            for x in (-640, -300):   # people at the back desks, out of focus
                S.draw_person(p, S.pose_sit(x, 236, self.FLOOR, 1, 46.0, arms="type", reach=(x + 110, 170)), S.LOOKS["stranger"],
                              None)
        p.poly(rect(420, -300, 230, 600), hexc("#1C1A28"))                           # the boss's glass door
        p.poly(rect(436, -284, 198, 420), hexc("#8A8AA8"), 0.22)
        p.poly(rect(420, -300, 3, 600), hexc("#6A6A88"), 0.8)
        p.poly(rr(612, 20, 8, 60, 3), hexc("#9A9AB0"))
        plant_pot(p, 360, self.FLOOR, 200, seed="office")

    def _mid(self, p: Paint):
        chair(p, -80, 212, 1, self.FLOOR, "#1A1724", "#4A4660")
        table(p, -20, 280, 160, self.FLOOR, "#2E2840", "#7A7090")
        p.poly(rr(150, 40, 120, 92, 5), hexc("#141220"))                             # his monitor
        p.poly(rr(157, 47, 106, 76, 3), hexc("#8FB0E8") if self.light != "day" else hexc("#4A5A80"), 0.95)
        p.poly(rect(205, 132, 10, 28), hexc("#141220"))
        p.poly(rr(185, 156, 50, 5, 2), hexc("#141220"))
        p.poly(rr(40, 152, 90, 7, 2), hexc("#24202E"))                                # the keyboard

    def _glows(self, p: Paint):
        bright = 0.30 if self.light != "day" else 0.12
        p.glow(210, 85, 90, 70, PAL["screen"], bright)
        for x in (-760, -420):
            p.glow(x + 195, 125, 70, 50, PAL["screen"], bright * 0.6)


# --- the café ------------------------------------------------------------------------------------------------------------------
class Cafe(Room):
    """A small café: a big window onto the city, a round table for two under a pendant lamp, a counter at the back with
    the coffee machine and cups."""

    WINDOW = (-760.0, -320.0, 220.0, 70.0, 4, 2)
    LAMP = (0.0, -170.0)
    LAMP_TO = 150.0
    WALL_TINT = "#5A3E44"
    MARKS = {
        "sit": {"kind": "sit", "x": -170.0, "seat": 212.0, "f": 1, "reach": (-55.0, 146.0)},
        "sit_other": {"kind": "sit", "x": 170.0, "seat": 212.0, "f": -1, "reach": (55.0, 146.0)},
        "stand": {"kind": "stand", "x": -400.0, "f": 1},
        "stand_other": {"kind": "stand", "x": 360.0, "f": -1},
        "leave": {"kind": "walk", "from": 300.0, "to": 760.0, "f": 1},
        "walk": {"kind": "walk", "from": -760.0, "to": -400.0, "f": 1},
    }

    def _decor(self, p: Paint):
        for y in (-210, -120):
            p.poly(rect(430, y, 360, 8), hexc("#2B1F2E"))
            lit_edge(p, y - 1, 430, 790, WOOD_EDGE, 0.7, 2)
            for k, x in enumerate(np.arange(445, 780, 42)):
                h = 30 + 14 * ((k * 7) % 3)
                p.poly(rr(x, y - h, 26, h, 5), hexc(["#3A2A30", "#4A3A3A", "#2E2630"][k % 3]))
        p.poly(rr(300, -290, 110, 80, 3), PAL["frame"])
        p.poly(rect(306, -284, 98, 68), hexc("#1E1A22"))

    def _back(self, p: Paint):
        p.poly(rect(400, 110, 520, 190), hexc("#2A1E2A"))
        lit_edge(p, 108, 400, 920, WOOD_EDGE, 0.85, 4)
        p.poly(rr(470, 30, 110, 80, 6), hexc("#1C161E"))                             # the coffee machine
        p.poly(rect(472, 32, 106, 3), hexc("#9A8A90"), 0.7)
        for x in (610, 650, 690):
            p.poly(rr(x, 84, 26, 26, 5), hexc("#E6DCD0"), 0.85)
        plant_pot(p, -840, self.FLOOR, 240, seed="cafe")

    def _mid(self, p: Paint):
        chair(p, -170, 212, 1, self.FLOOR, "#2A1E26", "#7A5A60")
        chair(p, 170, 212, -1, self.FLOOR, "#2A1E26", "#7A5A60")
        p.poly(ell(0, 152, 100, 9, 48), hexc("#3A2A30"))
        p.poly(rect(-100, 148, 200, 3), hexc("#9A7A70"), 0.8)
        p.poly(rect(-7, 160, 14, 130), hexc("#1E161E"))
        p.poly(ell(0, 294, 50, 8, 40), hexc("#1E161E"))
        for x in (-40, 40):
            p.poly(rr(x - 11, 126, 22, 24, 4), hexc("#E6DCD0"), 0.9)

    def _glows(self, p: Paint):
        if self.lamp_on:
            p.glow(0, 150, 105, 8, PAL["lamp"], 0.18)
        p.glow(525, 60, 120, 60, PAL["lamp"] * 0.6, 0.10)


# --- the dream life: a bright office and a new flat ---------------------------------------------------------------------------
class BrightOffice(Room):
    """The life he built: a bright meeting room with a glass wall onto the city, a long table, a blank screen on the wall,
    plants."""

    WINDOW = (-960.0, -340.0, 180.0, 140.0, 5, 2)
    LAMP = (420.0, -170.0)
    LAMP_TO = 150.0
    CENTER = (-80.0, 0.0)
    WALL_TINT = "#6A5A78"
    MARKS = {
        "window": {"kind": "stand", "x": -420.0, "f": -1, "lift": 0.1},
        "desk": {"kind": "sit", "x": 90.0, "seat": 212.0, "f": 1, "reach": (215.0, 146.0)},
        "stand": {"kind": "stand", "x": -150.0, "f": 1},
        "present": {"kind": "stand", "x": 760.0, "f": -1},
        "walk": {"kind": "walk", "from": -900.0, "to": -150.0, "f": 1},
        "other": {"kind": "stand", "x": 360.0, "f": -1},
        "crowd": [{"kind": "sit", "x": 470.0, "seat": 212.0, "f": -1, "reach": (360.0, 146.0)},
                  {"kind": "sit", "x": 650.0, "seat": 212.0, "f": -1, "reach": (540.0, 146.0)}],
    }

    def _decor(self, p: Paint):
        p.poly(rr(780, -260, 260, 160, 6), hexc("#16131E"))
        p.poly(rect(780, -260, 260, 3), hexc("#6A6080"), 0.8)

    def _back(self, p: Paint):
        plant_pot(p, -1000, self.FLOOR, 260, seed="bright1")
        plant_pot(p, 1060, self.FLOOR, 220, seed="bright2")

    def _mid(self, p: Paint):
        for x, f in ((90, 1), (470, -1), (650, -1)):
            chair(p, x, 212, f, self.FLOOR, "#2A2436", "#6A6080")
        table(p, 150, 760, 150, self.FLOOR, "#3A3046", "#9A8AA0")
        p.poly(rr(220, 130, 70, 8, 2), hexc("#24202E"))                              # an open laptop
        p.poly(np.array([(222, 130), (232, 70), (240, 70), (230, 130)], float), hexc("#24202E"))
        p.poly(np.array([(225, 126), (234, 76), (237, 76), (228, 126)], float), PAL["screen"], 0.8)

    def _glows(self, p: Paint):
        p.glow(910, -180, 160, 100, PAL["screen"], 0.06)
        p.glow(232, 100, 50, 40, PAL["screen"], 0.15)


class NewFlat(Room):
    """The home he made: a tall window onto the city, a sofa, a warm floor lamp, plants, a shelf of books, pictures."""

    WINDOW = (-650.0, -350.0, 150.0, 140.0, 4, 2)
    CENTER = (-40.0, 0.0)
    WALL_TINT = "#6A4E5A"
    MARKS = {
        "window": {"kind": "stand", "x": -260.0, "f": -1, "lift": 0.1},
        "sofa": {"kind": "sit", "x": 360.0, "seat": 214.0, "f": -1},
        "stand": {"kind": "stand", "x": 160.0, "f": 1},
        "walk": {"kind": "walk", "from": -760.0, "to": 120.0, "f": 1},
        "sofa_other": {"kind": "sit", "x": 520.0, "seat": 214.0, "f": -1},
        "door": {"kind": "stand", "x": 760.0, "f": -1},
    }

    def _decor(self, p: Paint):
        frame_picture(p, 300, -250, 400, -160)
        frame_picture(p, 430, -235, 510, -170, "#3A2E40", "#5A4660")
        p.poly(rect(700, -280, 230, 10), hexc("#2B1F2E"))
        lit_edge(p, -281, 700, 930, WOOD_EDGE, 0.7, 2)
        books(p, 710, -280, 9, "flat1")
        p.poly(rect(700, -150, 230, 10), hexc("#2B1F2E"))
        books(p, 720, -150, 7, "flat2")

    def _back(self, p: Paint):
        plant_pot(p, -760, self.FLOOR, 300, leaves=9, seed="flat")
        p.poly(rect(612, -160, 6, 460), hexc("#1C1520"))                             # the floor lamp
        p.poly(np.array([(580, -200), (650, -200), (668, -150), (562, -150)], float), hexc("#5A4040"))
        if self.L["lamp"]:
            p.poly(ell(615, -150, 52, 4, 40), hexc("#FFE9C8"))
        p.poly(ell(200, 302, 420, 14, 64), hexc("#2A2030"), 0.8)                      # the rug

    def _mid(self, p: Paint):
        p.poly(rr(250, 120, 420, 110, 18), hexc("#4A3A50"))                          # the sofa
        p.poly(rr(250, 196, 420, 70, 14), hexc("#54425A"))
        lit_edge(p, 119, 262, 658, "#8A7090", 0.7, 3)
        for x in (240, 650):
            p.poly(rr(x, 150, 34, 116, 12), hexc("#40324A"))
        for x in (270, 300):
            p.poly(rect(x, 266, 10, 34), hexc("#1C1520"))
        p.poly(rect(632, 266, 10, 34), hexc("#1C1520"))

    def _glows(self, p: Paint):
        if self.L["lamp"]:
            p.glow(615, -150, 140, 60, PAL["lamp"], 0.40)
            p.glow(615, 40, 260, 200, PAL["lamp"] * 0.5, 0.10)


# --- outdoors: the rooftop, the park --------------------------------------------------------------------------------------------
class Rooftop(Outdoor):
    """A flat roof above the city: the low parapet, a water tank on legs, a vent, a crate, string lights; the whole sky
    and the skyline beyond."""

    HORIZON = 200.0
    PAN = (300.0, 30.0)
    MARKS = {
        "stand": {"kind": "stand", "x": 150.0, "f": 1, "lift": 0.1},
        "pushup": {"kind": "pushup", "x": -60.0, "f": 1},
        "sit": {"kind": "sit", "x": -380.0, "seat": 238.0, "f": 1},
        "floor": {"kind": "floor", "x": -520.0, "f": 1},
        "walk": {"kind": "walk", "from": -700.0, "to": 150.0, "f": 1},
        "run": {"kind": "run", "from": -900.0, "to": 700.0, "f": 1},
    }

    def _backdrop(self, p: Paint):
        city(p, self.HORIZON + 140, self.SPAN[0], self.SPAN[1], (self.HORIZON - 140, self.HORIZON - 20), (60, 160),
             self.L["near"], "roof near", win=self.L["win"], lit=self.L["lit"], cell=(16, 20), size=(6, 8))

    def _ground(self, p: Paint):
        p.poly(rect(self.SPAN[0] - 900, 226, self.SPAN[1] - self.SPAN[0] + 1800, 80), hexc("#1E1626"))   # the parapet
        lit_edge(p, 224, self.SPAN[0] - 900, self.SPAN[1] + 900, "#6A5068", 0.85, 4)
        p.poly(rect(self.SPAN[0] - 900, self.GROUND, self.SPAN[1] - self.SPAN[0] + 1800, 600), hexc("#140F18"))

    def _props(self, p: Paint):
        dark = hexc("#150F1A")
        p.poly(rr(-820, -170, 150, 190, 14), dark)                                      # the water tank
        p.poly(rect(-820, -170, 3, 190), hexc(DARK_EDGE), 0.8)
        for x in (-810, -700):
            p.poly(rect(x, 20, 10, 280), dark)
        p.poly(rect(-600, 140, 120, 160), hexc("#1C1522"))                              # a vent
        lit_edge(p, 138, -600, -480, "#6A5068", 0.8, 3)
        p.poly(rect(-440, 238, 120, 62), hexc("#3A2E2A"))                               # a crate
        lit_edge(p, 236, -440, -320, "#8A6A5A", 0.8, 3)
        p.poly(rect(-430, 262, 100, 2), hexc("#2A201E"))
        p.poly(rect(560, -330, 6, 560), dark)                                           # a pole for the lights
        pts = [(560 - 900 * u, -320 + 70 * math.sin(math.pi * u)) for u in np.linspace(0, 1, 40)]
        p.poly(tube(pts, 2.0, k=2), hexc("#140F18"))
        for x, y in pts[2::4]:
            p.circle(x, y + 6, 5, hexc("#FFE2B4") if self.lamps_on else hexc("#4A3A44"))

    def _backdrop_light(self, p: Paint):
        if self.lamps_on:
            pts = [(560 - 900 * u, -320 + 70 * math.sin(math.pi * u)) for u in np.linspace(0, 1, 40)][2::4]
            for x, y in pts:
                p.glow(x, y + 6, 26, 26, PAL["lamp"], 0.30)


class Park(Outdoor):
    """A city park at the edge of the skyline: big trees, a path, a bench, two lamps; where he runs at dawn."""

    HORIZON = 120.0
    LAMPS = (-420.0, 620.0)
    MARKS = {
        "run": {"kind": "run", "from": -1000.0, "to": 900.0, "f": 1},
        "walk": {"kind": "walk", "from": -900.0, "to": 500.0, "f": 1},
        "pushup": {"kind": "pushup", "x": 300.0, "f": 1},
        "sit": {"kind": "sit", "x": -280.0, "seat": 236.0, "f": 1},
        "stand": {"kind": "stand", "x": 150.0, "f": 1},
        "crowd": [{"kind": "run", "from": 1100.0, "to": -900.0, "f": -1}],
    }

    def _backdrop(self, p: Paint):
        r = rng("trees")
        dark = mix(self.L["near"], "#000000", 0.2)
        for x in np.arange(-1700, 1800, 260):
            x = x + r.uniform(-60, 60)
            trunk_top = r.uniform(-60, 40)
            p.poly(rect(x - 9, trunk_top, 18, 280 - trunk_top), dark)
            for _ in range(6):
                p.circle(x + r.uniform(-120, 120), trunk_top - r.uniform(30, 190), r.uniform(70, 130), dark)
        city(p, 260, self.SPAN[0] - 600, self.SPAN[1] + 600, (150, 230), (40, 120), mix(self.L["near"], "#000000", 0.35),
             "bushes")

    def _ground(self, p: Paint):
        p.poly(rect(self.SPAN[0] - 900, 200, self.SPAN[1] - self.SPAN[0] + 1800, 70), hexc("#1C1822"))
        p.poly(rect(self.SPAN[0] - 900, 262, self.SPAN[1] - self.SPAN[0] + 1800, 60),
               gradient([(262, "#3A2F44"), (322, "#2A2232")])(p))
        lit_edge(p, 261, self.SPAN[0] - 900, self.SPAN[1] + 900, "#6A5878", 0.5, 2)
        p.poly(rect(self.SPAN[0] - 900, 322, self.SPAN[1] - self.SPAN[0] + 1800, 600), hexc("#120E16"))

    def _props(self, p: Paint):
        dark = hexc("#150F1A")
        p.poly(rect(-400, 236, 220, 10), dark)                                           # the bench
        lit_edge(p, 234, -400, -180, "#7A6068", 0.8, 2.5)
        p.poly(rect(-400, 180, 220, 9), dark)
        for x in (-390, -200):
            p.poly(rect(x, 180, 9, 120), dark)


# --- the registry ---------------------------------------------------------------------------------------------------------------
PLACES = {"bedroom": Bedroom, "kitchen": Kitchen, "hallway": Hallway, "office": Office, "cafe": Cafe,
          "rooftop": Rooftop, "park": Park, "bright_office": BrightOffice, "new_flat": NewFlat}
