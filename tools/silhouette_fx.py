"""
The silhouette look's moving light and weather beyond the rain (tools/silhouette_sets.Rain): fire, smoke, emergency
lights, snow, fog, party lights, a spotlight; and the small ones things carry (a candle's flame, a pot's steam).
Everything moves slowly and smoothly (the look's rule: nothing flickering): a fire breathes, lights pulse, flakes drift.

A place (tools/silhouette_scene.py) keeps a list of effects; each draws at its stages of the frame:
  "view"  rooms: beyond the window's glass (the wall is drawn over it, so it shows only through the panes);
  "far"   outdoors: over the far layers (fog banks, far snow);
  "back"  behind the people (flames, smoke, light on the walls; the spotlight dims the room here);
  "front" over everything but the finish (near snow, near fog, the warm or flashing wash on the air).
"""

import math

import cv2
import numpy as np

import silhouette as S
from silhouette import PAL, Dynamic, Paint, hexc, spline, tube
from silhouette_sets import rng
import silhouette_words as W

EFFECTS = W.EFFECTS   # (the words live in tools/silhouette_words.py)

DEEP, ORANGE, YELLOW, CORE = hexc("#B8322A"), hexc("#F07A36"), hexc("#FFC25A"), hexc("#FFF0C8")
FIRE_LIGHT = np.array([1.0, 0.55, 0.25], np.float32)


# --- the small ones, drawn by things (tools/silhouette_props.py) ----------------------------------------------------------
def flames(p: Paint, x, base, width, height, tau, seed=0, alpha=1.0):
    """A fire's flames rising from `base` (world y) across `width`, about `height` tall: tongues in three colours that
    breathe and sway slowly, a pale core, a few embers rising."""
    r = rng("flames", seed)
    n = max(2, int(round(width / max(height * 0.42, 1e-6))))
    slot = width / n
    xs = x - width / 2 + (np.arange(n) + 0.5) * slot + r.uniform(-0.15, 0.15, n) * slot
    ph = r.uniform(0, math.tau, (n, 3))
    tall = r.uniform(0.70, 1.0, n)
    for col, scale, wk in ((DEEP, 1.0, 1.25), (ORANGE, 0.74, 0.95), (YELLOW, 0.46, 0.70), (CORE, 0.22, 0.42)):
        for i in range(n):
            h = height * tall[i] * scale * (0.78 + 0.16 * math.sin(math.tau * 0.62 * tau + ph[i, 0])
                                             + 0.06 * math.sin(math.tau * 1.7 * tau + ph[i, 1]))
            w = slot * wk
            sway = w * 0.30 * math.sin(math.tau * 0.45 * tau + ph[i, 2])
            xi = xs[i]
            pts = [(xi - w / 2, base), (xi - w * 0.46, base - h * 0.30), (xi - w * 0.22 + sway * 0.4, base - h * 0.68),
                   (xi + sway, base - h), (xi + w * 0.24 + sway * 0.4, base - h * 0.64), (xi + w * 0.46, base - h * 0.28),
                   (xi + w / 2, base), (xi, base + h * 0.04)]
            p.poly(spline(pts, True, 8), col, alpha * 0.96)
    for k in range(int(6 + width / 40)):   # embers
        u = (tau * r.uniform(0.18, 0.32) + r.uniform(0, 1)) % 1.0
        ex = x + r.uniform(-0.5, 0.5) * width + math.sin(tau * 0.8 + k) * 8 * u
        ey = base - height * (0.4 + 1.8 * u)
        p.circle(ex, ey, r.uniform(1.0, 2.2), YELLOW, alpha * 0.9 * (1 - u) ** 1.5)


def fire_glow(p: Paint, x, base, width, height, tau, strength=1.0, seed=0):
    """The fire's light on what's round it (added): a warm breath, never a flicker."""
    b = strength * (0.85 + 0.15 * math.sin(math.tau * 0.5 * tau + seed))
    p.glow(x, base - height * 0.45, width * 0.9 + 60, height * 0.9 + 40, FIRE_LIGHT, 0.55 * b)
    p.glow(x, base - height * 0.3, width * 2.4 + 200, height * 2.0 + 160, FIRE_LIGHT * 0.6, 0.20 * b)
    p.glow(x, base, width * 1.6 + 120, 22, FIRE_LIGHT, 0.30 * b)


def steam(p: Paint, x, top, tau, seed=0, size=1.0, alpha=0.16):
    """A few thin wisps rising from a pot or a cup, curling and fading."""
    r = rng("steam", seed)
    for k in range(3):
        u0 = r.uniform(0, 1)
        pts = []
        for j in range(7):
            v = j / 6
            pts.append((x + (k - 1) * 9 * size + math.sin(tau * 1.1 + k * 2 + v * 4 + u0 * 6) * 7 * size * v,
                        top - v * 70 * size))
        a = alpha * (0.6 + 0.4 * math.sin(tau * 0.7 + k))
        p.poly(tube(pts, 5.0 * size, 1.5 * size), hexc("#D8D0E0"), max(0.0, a), soft=2.5 * size)


def candle_flame(p: Paint, x, top, tau, seed=0, size=1.0):
    """A small flame on a wick, swaying slowly."""
    sway = 1.6 * size * math.sin(math.tau * 0.5 * tau + seed)
    h = 15 * size * (0.92 + 0.08 * math.sin(math.tau * 0.8 * tau + seed * 2))
    pts = [(x - 3.6 * size, top - 2), (x - 2.6 * size, top - h * 0.5), (x + sway, top - h), (x + 2.6 * size, top - h * 0.5),
           (x + 3.6 * size, top - 2), (x, top + 1)]
    p.poly(spline(pts, True, 6), YELLOW, 0.95)
    p.poly(spline([(x - 1.6 * size, top - 2), (x + sway * 0.5, top - h * 0.62), (x + 1.6 * size, top - 2)], True, 4), CORE)


# --- a place's effects ---------------------------------------------------------------------------------------------------
class Effect:
    stages: tuple = ()

    def __init__(self, place, **kw):
        self.place = place
        self.kw = kw

    def draw(self, stage, frame, at, tau):
        pass


class Fire(Effect):
    """Flames at (x, base) `width` across, smoke above them, their warm light on the place (in front too, faintly)."""
    stages = ("back", "front")

    def __init__(self, place, x=0.0, base=300.0, width=380.0, height=260.0, depth=0.72, smoke=True, seed=0):
        super().__init__(place)
        self.x, self.base, self.width, self.height, self.seed = x, base, width, height, seed
        self.strength = {"day": 0.40, "dawn": 0.65, "dusk": 0.85, "night": 1.0}.get(getattr(place, "light", "night"), 1.0)
        self.layer = Dynamic(place.cam, depth)
        self.light = Dynamic(place.cam, depth, add=True)
        self.smoke = Smoke(place, x=x, top=base - height * 0.9, width=width, depth=depth, seed=seed) if smoke else None

    def draw(self, stage, frame, at, tau):
        if stage == "back":
            if self.smoke is not None:
                self.smoke.draw("back", frame, at, tau)
            lp = self.light.paint(at)
            fire_glow(lp, self.x, self.base, self.width, self.height, tau, strength=self.strength, seed=self.seed)
            self.light.composite(frame, lp)
            p = self.layer.paint(at)
            flames(p, self.x, self.base, self.width, self.height, tau, self.seed)
            self.layer.composite(frame, p)
        else:   # the warm breath on the air, faint
            lp = self.light.paint(at)
            b = 0.85 + 0.15 * math.sin(math.tau * 0.5 * tau + self.seed)
            lp.glow(self.x, self.base - self.height * 0.5, self.width * 3 + 400, self.height * 3 + 300, FIRE_LIGHT * 0.5,
                    0.10 * b * self.strength)
            self.light.composite(frame, lp)


class Smoke(Effect):
    """Puffs rising from a source (x, top) `width` across, growing, drifting, thinning; dark and soft."""
    stages = ("back",)

    def __init__(self, place, x=0.0, top=0.0, width=300.0, depth=0.70, color=None, rise=900.0, seed=0, n=10):
        super().__init__(place)
        light = getattr(place, "light", "night")
        color = color or {"day": "#6E6676", "dawn": "#5A5062", "dusk": "#4A4050", "night": "#3A3240"}.get(light, "#3A3240")
        self.x, self.top, self.width, self.rise, self.color = x, top, width, rise, hexc(color)
        self.layer = Dynamic(place.cam, depth)
        r = rng("smoke", seed)
        self.puffs = [(r.uniform(0, 1), r.uniform(-0.4, 0.4), r.uniform(0.8, 1.25), r.uniform(0, math.tau))
                      for _ in range(n)]

    def draw(self, stage, frame, at, tau):
        p = self.layer.paint(at)
        for u0, dx, sz, ph in self.puffs:
            u = (tau / 7.0 + u0) % 1.0
            px = self.x + dx * self.width + math.sin(tau * 0.3 + ph) * 30 * u + 160 * u
            py = self.top - self.rise * u
            rad = (self.width * 0.22 + self.width * 0.55 * u) * sz
            a = 0.58 * math.sin(math.pi * min(1.0, u * 1.4)) * (1 - u) ** 0.5
            p.circle(px, py, rad, self.color, a, soft=rad * 0.35)
        self.layer.composite(frame, p)


class Emergency(Effect):
    """An ambulance's or a police car's lights: the place washed slowly red, then blue (1.6 s a cycle), from (x, y)."""
    stages = ("back", "front")

    def __init__(self, place, x=600.0, y=0.0, period=1.6, strength=1.0):
        super().__init__(place)
        self.x, self.y, self.period, self.strength = x, y, period, strength
        self.layer = Dynamic(place.cam, 0.70, add=True)

    def draw(self, stage, frame, at, tau):
        q = 0.5 + 0.5 * math.sin(math.tau * tau / self.period)
        red, blue = np.array([1.0, 0.16, 0.14], np.float32), np.array([0.20, 0.36, 1.0], np.float32)
        p = self.layer.paint(at)
        k = self.strength * (0.34 if stage == "back" else 0.09)
        p.glow(self.x, self.y, 700, 420, red, k * q ** 1.5)
        p.glow(self.x + 60, self.y, 700, 420, blue, k * (1 - q) ** 1.5)
        self.layer.composite(frame, p)


class Snow(Effect):
    """Flakes falling slowly and drifting, at two depths (screen space, like the rain): far and fine, near and soft.
    In a room it falls beyond the window ("view": the wall covers it but for the panes)."""

    def __init__(self, place, room=False, far=260, near=70, seed="snow"):
        super().__init__(place)
        self.stages = ("view",) if room else ("far", "front")
        W, H = place.size
        r = rng(seed)
        self.layers = {}
        for name, n, size, speed, blur, a in (("far", far, (1.0, 2.2), 0.06, 0.0, 0.75), ("near", near, (2.6, 5.0), 0.12, 1.6, 0.85)):
            self.layers[name] = {"x": r.uniform(0, 1, n), "y": r.uniform(0, 1, n), "sp": r.uniform(0.7, 1.3, n) * speed,
                                 "r": r.uniform(*size, n) * H / 1080, "ph": r.uniform(0, math.tau, n), "blur": blur * H / 1080,
                                 "a": a}
        self.room = room

    def _flakes(self, frame, L, tau, pan_px):
        W, H = self.place.size
        canvas = np.zeros((H, W), np.float32)
        ys = ((L["y"] + L["sp"] * tau) % 1.0) * (H + 20) - 10
        xs = (L["x"] * W * 1.1 + 18 * np.sin(tau * 0.8 + L["ph"]) * H / 1080 - pan_px) % (W * 1.1) - W * 0.05
        for x, y, rad in zip(xs, ys, L["r"]):
            cv2.circle(canvas, (int(x * 16), int(y * 16)), max(1, int(rad * 16)), 1.0, -1, cv2.LINE_AA, 4)
        if L["blur"]:
            canvas = cv2.GaussianBlur(canvas, (0, 0), L["blur"])
        frame += canvas[..., None] * hexc("#E8E4F2") * L["a"] - frame * canvas[..., None] * L["a"] * 0.6

    def draw(self, stage, frame, at, tau):
        pan = (at[0] - self.place.cam.rest[0]) * self.place.k
        if stage == "view":
            self._flakes(frame, self.layers["far"], tau, pan * 0.3)
            self._flakes(frame, self.layers["near"], tau * 0.8, pan * 0.3)
        elif stage == "far":
            self._flakes(frame, self.layers["far"], tau, pan * 0.4)
        else:
            self._flakes(frame, self.layers["near"], tau, pan * 1.2)


class Fog(Effect):
    """Soft banks of fog drifting slowly across: over the far layers, low near the ground, beyond a window."""

    def __init__(self, place, room=False, ground=300.0, color=None, seed="fog"):
        super().__init__(place)
        self.stages = ("view",) if room else ("far", "front")
        L = place.L
        self.color = hexc(color) if color else (hexc(L["haze"][0]) * 0.75 + 0.06)
        self.ground = ground
        self.far = Dynamic(place.cam, 0.20)
        self.near = Dynamic(place.cam, 0.80)
        r = rng(seed)
        self.banks = [(r.uniform(-1, 1), r.uniform(0, 1), r.uniform(0.7, 1.3)) for _ in range(7)]

    def draw(self, stage, frame, at, tau):
        layer = self.far if stage in ("far", "view") else self.near
        p = layer.paint(at)
        x0, x1 = self.place.SPAN if hasattr(self.place, "SPAN") else (-1700.0, 1700.0)
        span = (x1 - x0) + 1600
        for k, (u, v, s) in enumerate(self.banks):
            x = x0 - 800 + ((u * 0.5 + 0.5) * span + tau * 18 * s) % span
            if stage in ("far", "view"):
                y = self.ground - 260 - 300 * v
                p.poly(S.ell(x, y, 520 * s, 90 * s, 48), self.color, 0.30, soft=70)
            else:
                y = self.ground - 40 - 120 * v
                p.poly(S.ell(x, y, 640 * s, 70 * s, 48), self.color, 0.16, soft=60)
        layer.composite(frame, p)


class PartyLights(Effect):
    """Strings of warm coloured bulbs across the top of a room, each pulsing slowly out of step, and soft coloured light
    drifting over the back wall."""
    stages = ("back",)
    COLORS = [hexc(c) for c in ("#FFC25A", "#FF7A8A", "#7AD0C8", "#FFE2B4", "#C890F0", "#FF9A4A")]

    def __init__(self, place, x0=-900.0, x1=900.0, y=-330.0, sag=70.0, seed="party"):
        super().__init__(place)
        self.x0, self.x1, self.y, self.sag = x0, x1, y, sag
        self.shape = Dynamic(place.cam, 0.66)
        self.light = Dynamic(place.cam, 0.66, add=True)
        r = rng(seed)
        self.ph = r.uniform(0, math.tau, 64)

    def _bulbs(self):
        out = []
        spans = 3
        w = (self.x1 - self.x0) / spans
        for s in range(spans):
            a = self.x0 + s * w
            for u in np.linspace(0.06, 0.94, 7):
                out.append((a + u * w, self.y + self.sag * math.sin(math.pi * u)))
        return out

    def draw(self, stage, frame, at, tau):
        p = self.shape.paint(at)
        spans = 3
        w = (self.x1 - self.x0) / spans
        for s in range(spans):
            a = self.x0 + s * w
            pts = [(a + u * w, self.y - 6 + self.sag * math.sin(math.pi * u)) for u in np.linspace(0, 1, 24)]
            p.poly(tube(pts, 2.0, k=2), hexc("#120D16"))
        bulbs = self._bulbs()
        lp = self.light.paint(at)
        for k, (bx, by) in enumerate(bulbs):
            col = self.COLORS[k % len(self.COLORS)]
            q = 0.65 + 0.35 * math.sin(math.tau * tau / 3.2 + self.ph[k])
            p.circle(bx, by, 6.5, np.clip(col * (0.7 + 0.3 * q), 0, 1))
            lp.glow(bx, by, 26, 26, col, 0.32 * q)
        for k in range(3):   # soft colour moving on the wall
            col = self.COLORS[(k * 2 + 1) % len(self.COLORS)]
            gx = (self.x0 + self.x1) / 2 + math.sin(tau * 0.17 + k * 2.1) * (self.x1 - self.x0) * 0.35
            gy = self.y + 200 + math.cos(tau * 0.13 + k) * 90
            lp.glow(gx, gy, 260, 180, col, 0.07)
        self.shape.composite(frame, p)
        self.light.composite(frame, lp)


class Spotlight(Effect):
    """A spotlight from above onto (x, floor): the room dimmed round it, a soft cone, a pool of light, dust in the beam."""
    stages = ("back",)

    def __init__(self, place, x=0.0, floor=300.0, top=-700.0, width=170.0, dim=0.50, seed="spot"):
        super().__init__(place)
        self.x, self.floor, self.top, self.width, self.dim = x, floor, top, width, dim
        self.light = Dynamic(place.cam, 0.70, add=True)
        r = rng(seed)
        self.dust = (r.uniform(0, 1, 40), r.uniform(0, 1, 40), r.uniform(0, math.tau, 40))

    def draw(self, stage, frame, at, tau):
        frame *= self.dim
        p = self.light.paint(at)
        x, top, bot, w = self.x, self.top, self.floor, self.width
        warm = PAL["lamp"]

        def fall(px, py):
            u = np.clip((p.wy(py) - top) / max(bot - top, 1), 0, 1)[..., None]
            return warm * (0.10 + 0.20 * u)
        p.poly(np.array([(x - 30, top), (x + 30, top), (x + w, bot), (x - w, bot)], float), fall, soft=14)
        p.glow(x, bot, w * 1.25, 26, warm, 0.55)
        us, vs, ph = self.dust
        for u, v, a in zip(us, vs, ph):
            yy = top + ((v + tau * 0.02) % 1.0) * (bot - top)
            half = 30 + (w - 30) * (yy - top) / (bot - top)
            xx = x + (u * 2 - 1) * half * 0.9 + math.sin(tau * 0.4 + a) * 6
            p.circle(xx, yy, 1.3, warm, 0.6, add=True)
        self.light.composite(frame, p)


def make(name: str, place, **kw) -> Effect:
    """An effect by its storyboard name (EFFECTS), placed by the place (tools/silhouette_scene.py gives kw)."""
    cls = {"fire": Fire, "smoke": Smoke, "emergency": Emergency, "snow": Snow, "fog": Fog, "party": PartyLights,
           "spotlight": Spotlight}[name]
    return cls(place, **kw)
