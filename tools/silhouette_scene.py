"""
Places built from a storyboard's description (Agent 3, agents/animator.py): a room, a big hall, a corridor, a city
street, a quiet street of houses, a bridge, nature, inside a car, a bus or a train. Each is laid out from its things
(tools/silhouette_props.py), in any light (silhouette_places.LIGHTS) and weather (clear, rain, snow, fog), with its
effects (tools/silhouette_fx.py), in the owner's look (prompts/look_silhouette.txt.enc). The 12 ready-made sets of
tools/silhouette_places.py and tools/silhouette_sets.py stay as they are.

A description (only "kind" is needed; unknown words are skipped and listed in place.missing):
  {"kind": KINDS, "wall": WALLS, "floor": FLOORS, "window": WINDOWS, "view": VIEWS, "nature": NATURE,
   "things": [names from PROPS, left to right, or {"thing": name, "facing": "left"/"right", "open": true, ...}],
   "wall_things": [...], "small": [...], "lamp": "hanging" or "none", "curtains": true, "effects": [EFFECTS]}

build(spec, size, light, weather, effects) gives a place with frame(index, st) (as the places of
tools/silhouette_places.py), MARKS (each thing's own marks, free spots, the ways in and out: where
tools/silhouette_actions.py puts people), R, FLOOR or GROUND, missing (what the description asked for that the
library doesn't have).
"""

import math

import numpy as np

import silhouette as S
import silhouette_fx as FX
import silhouette_props as PR
from silhouette import PAL, MARGIN, Dynamic, Paint, Static, ell, hexc, rect, rr, spline, tube
from silhouette_places import LIGHTS, RAINY, Outdoor, Room, city, mix, sky
from silhouette_sets import flat, gradient, rng
from silhouette_words import EFFECTS, FLOORS, NATURE, VIEWS, WALLS, WEATHER, WINDOWS
from silhouette_words import PLACE_KINDS as KINDS

INDOORS, OUTDOORS, VEHICLES = ("room", "hall", "corridor"), ("street", "houses", "bridge", "nature"), ("car", "bus", "train")
SNOWY = "#B8B4C8"


# --- a description, made safe -------------------------------------------------------------------------------------------
def norm(spec: dict) -> tuple[dict, list]:
    """The description with its defaults, and what it asked for that the library doesn't have."""
    spec = dict(spec or {})
    missing = []

    def pick(key, allowed, default):
        v = str(spec.get(key) or default).strip().lower().replace(" ", "_")
        if v not in allowed:
            missing.append(f"{key}: {v}")
            return default
        return v
    kind = pick("kind", KINDS, "room")
    out = {"kind": kind, "wall": pick("wall", WALLS, "plum"), "floor": pick("floor", FLOORS, "wood"),
           "view": pick("view", VIEWS, "city"), "nature": pick("nature", NATURE, "hills"),
           "lamp": "hanging" if str(spec.get("lamp", "hanging" if kind == "room" else "none")).lower() == "hanging" else "none",
           "curtains": bool(spec.get("curtains")),
           "window": pick("window", WINDOWS, {"room": "big", "hall": "tall"}.get(kind, "none"))}
    where_ok = ("in", "both") if kind in INDOORS else ("out", "both")
    got = []
    for key in ("things", "wall_things", "small"):
        for item in spec.get(key) or []:
            d = {"thing": item} if isinstance(item, str) else dict(item or {})
            name = str(d.get("thing") or "").strip().lower().replace(" ", "_")
            if name not in PR.PROPS:
                missing.append(f"thing: {name}")
                continue
            if kind not in VEHICLES and PR.PROPS[name][4] not in where_ok:
                missing.append(f"thing: {name} ({'indoors' if kind in INDOORS else 'outdoors'})")
                continue
            d["thing"] = name
            got.append(d)
    out["things"] = [d for d in got if PR.PROPS[d["thing"]][3] in ("floor", "back", "mid", "fore")]
    out["wall_things"] = [d for d in got if PR.PROPS[d["thing"]][3] == "wall"]
    out["small"] = [d for d in got if PR.PROPS[d["thing"]][3] in ("small", "floor_small")]
    fx = []
    for e in spec.get("effects") or []:
        e = str(e).strip().lower()
        if e in EFFECTS:
            fx.append(e)
        else:
            missing.append(f"effect: {e}")
    out["effects"] = fx
    return out, missing


def _weather(weather, spec, effects):
    """The weather: as asked, or snow or fog when they're asked for as an effect on a clear day."""
    w = weather if weather in WEATHER else "clear"
    if w == "clear":
        for e in list(spec.get("effects") or []) + list(effects or ()):
            if e in ("snow", "fog"):
                return e
    return w


def _opts(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("thing", "facing")}


# --- the land beyond: what a window or the far layers show -------------------------------------------------------------
def hills(p: Paint, x0, x1, base, height, color, seed, bumps=5, alpha=1.0):
    r = rng("hills", seed)
    xs = np.linspace(x0, x1, bumps * 2 + 1)
    pts = [(x, base - height * (0.45 + 0.55 * r.uniform(0.3, 1.0) * (0.6 + 0.4 * math.sin(i * 1.7 + r.uniform(0, 3)))))
           for i, x in enumerate(xs)]
    top = spline(np.array(pts), closed=False, k=10)
    p.poly(np.vstack([top, [(x1, base + 900), (x0, base + 900)]]), color, alpha)


def mountains(p: Paint, x0, x1, base, height, color, seed, snow=None, peaks=7):
    r = rng("mountains", seed)
    xs = np.linspace(x0, x1, peaks * 2 + 1)
    pts, caps = [], []
    for i, x in enumerate(xs):
        x = x + r.uniform(-0.25, 0.25) * (x1 - x0) / (peaks * 2)
        h = height * (r.uniform(0.55, 1.0) if i % 2 else r.uniform(0.15, 0.45))
        pts.append((x, base - h))
        if i % 2 and snow is not None:
            caps.append((x, base - h, h))
    p.poly(np.array(pts + [(x1, base + 900), (x0, base + 900)]), color)
    for k, (x, y, h) in enumerate(caps):   # snow on the peaks: down each slope a little way
        w = h * 0.28
        p.poly(np.array([(x, y), (x + w, y + h * 0.26), (x + w * 0.4, y + h * 0.20), (x, y + h * 0.30),
                         (x - w * 0.5, y + h * 0.22), (x - w, y + h * 0.26)]), snow, 0.85)


def treeline(p: Paint, x0, x1, base, height, color, seed, size=1.0):
    r = rng("treeline", seed)
    x = x0
    while x < x1:
        rad = r.uniform(30, 60) * size
        p.circle(x, base - height * r.uniform(0.6, 1.0), rad, color)
        x += rad * r.uniform(0.9, 1.4)
    p.poly(rect(x0, base - height * 0.6, x1 - x0, 900), color)


def pines_row(p: Paint, x0, x1, base, color, seed, size=1.0):
    r = rng("pines", seed)
    x = x0
    while x < x1:
        h = r.uniform(140, 260) * size
        w = h * 0.30
        p.poly(np.array([(x - w, base), (x, base - h), (x + w, base)], float), color)
        x += w * r.uniform(0.8, 1.6)


def rooftops(p: Paint, x0, x1, base, color, seed, win=None, lit=0.0):
    r = rng("roofs", seed)
    x = x0
    while x < x1:
        w = r.uniform(90, 170)
        h = r.uniform(50, 90)
        p.poly(np.array([(x, base), (x, base - h), (x + w / 2, base - h - w * 0.32), (x + w, base - h), (x + w, base)]), color)
        if win and lit > 0 and r.random() < lit * 1.4:
            p.poly(rect(x + w * 0.35, base - h * 0.7, 12, 12), hexc(win), 0.9)
        x += w + r.uniform(0, 30)
    p.poly(rect(x0, base, x1 - x0, 900), color)


def water(p: Paint, L, x0, x1, top, bottom, sun_x, rain, seed, still=False):
    """Water from its far edge (top) to its near one: the sky's colours mirrored and darkened, a column of glints under
    the low sun or the moon, thin lines of ripples."""
    stops = L["sky"]
    far_c = mix(stops[-1][1], "#000000", 0.35)
    near_c = mix(stops[0][1], "#000000", 0.55)
    if rain:
        far_c, near_c = mix(far_c, RAINY, 0.4), mix(near_c, RAINY, 0.4)

    def f(px, py):
        u = np.clip((p.wy(py) - top) / max(bottom - top, 1), 0, 1)[..., None]
        return far_c * (1 - u) + near_c * u
    p.poly(rect(x0, top, x1 - x0, bottom - top + 900), f)
    r = rng("water", seed)
    glint = hexc(L["sun"][0]) if L["sun"] else (hexc(L["moon"][0]) if L["moon"] else hexc("#E8E0F0"))
    strength = 0.9 if L["sun"] else (0.55 if L["moon"] else 0.25)
    if rain:
        strength *= 0.3
    for k in range(60):
        v = r.uniform(0, 1) ** 0.7
        y = top + 4 + v * (bottom - top - 8)
        spread = 30 + v * 160
        x = sun_x + r.normal(0, spread * 0.5)
        w = r.uniform(8, 30) * (0.5 + v)
        p.poly(rect(x - w / 2, y, w, 1.6 + v * 1.5), glint, strength * (1 - v * 0.6) * r.uniform(0.4, 1.0))
    for k in range(14 if not still else 6):
        y = top + r.uniform(0.1, 1.0) * (bottom - top)
        x = r.uniform(x0, x1)
        p.poly(rect(x, y, r.uniform(60, 240), 1.2), mix(near_c, "#FFFFFF", 0.25), 0.35)


def view_far(p: Paint, L, view, x0, x1, base, rain, seed):
    """The far land at a horizon `base` (world y): its shapes in the light's far colour, a haze band."""
    far = mix(L["far"], RAINY, 0.3) if rain else hexc(L["far"])
    if view == "city":
        city(p, base + 30, x0, x1, (base - 150, base - 60), (22, 60), far, seed + "far")
    elif view == "houses":
        rooftops(p, x0, x1, base + 20, far, seed)
    elif view == "trees":
        treeline(p, x0, x1, base + 30, 120, far, seed, 0.8)
    elif view in ("hills", "fields"):
        hills(p, x0, x1, base + 20, 150 if view == "hills" else 60, far, seed)
    elif view == "mountains":
        mountains(p, x0, x1, base + 30, 300, far, seed, snow=mix(L["cloud"], "#FFFFFF", 0.3))
    p.poly(rect(x0, base - 90, x1 - x0, 140), flat(L["haze"][0]), L["haze"][1], soft=24)


def view_near(p: Paint, L, view, x0, x1, base, rain, seed, lit_k=1.0):
    near = hexc(L["near"])
    if view == "city":
        city(p, base + 60, x0, x1, (base - 90, base - 20), (30, 80), near, seed + "near", win=L["win"],
             lit=L["lit"] * (0.8 if rain else 1.0) * lit_k)
    elif view == "houses":
        rooftops(p, x0, x1, base + 50, near, seed + "n", win=L["win"], lit=L["lit"] * lit_k)
    elif view == "trees":
        treeline(p, x0, x1, base + 70, 150, near, seed + "n", 1.2)
    elif view == "hills":
        hills(p, x0, x1, base + 60, 90, near, seed + "n", 4)
    elif view == "fields":
        p.poly(rect(x0, base + 30, x1 - x0, 900), near)
        for k in range(int((x1 - x0) / 140)):
            p.poly(rect(x0 + k * 140, base + 10, 4, 22), mix(near, "#000000", 0.3))
        p.poly(rect(x0, base + 16, x1 - x0, 3), mix(near, "#000000", 0.3))
    elif view == "mountains":
        pines_row(p, x0, x1, base + 70, near, seed + "n", 0.7)
        p.poly(rect(x0, base + 68, x1 - x0, 900), near)
    elif view == "sea":
        water(p, L, x0, x1, base - 20, base + 120, (x0 + x1) / 2, rain, seed)


# --- laying things out along a floor -----------------------------------------------------------------------------------
PERSON = 55.0   # half a person's width with room to spare (world units at R 64)


def footprint(name, opts, s, R=64.0):
    """How far a thing and the people using it reach (lo, hi) from its x, facing s."""
    c = PR.Ctx("dusk", s=s, opts=opts)
    t = PR.Thing(name, 0.0, 300.0, c)
    lo, hi = -t.width / 2, t.width / 2
    for m in t.marks().values():
        xs = [m["x"]] if "x" in m else []
        if m["kind"] == "sit":
            xs.append(m["x"] + m.get("f", 1) * 1.8 * R)
        if m["kind"] == "lie":
            xs.append(m["x"] + m.get("f", 1) * 7.0 * R)
        for x in xs:
            lo, hi = min(lo, x - PERSON), max(hi, x + PERSON)
    return lo, hi


def facing(name, x, d: dict) -> int:
    """Which way a thing faces: as the description says, or with its users towards the middle of the place (beds with
    their heads to the nearer wall)."""
    f = str(d.get("facing") or "").lower()
    if f in ("left", "right"):
        return 1 if f == "right" else -1
    c = PR.Ctx("dusk", s=1, opts=_opts(d))
    marks = PR.Thing(name, 0.0, 300.0, c).marks()
    if name in ("bed", "hospital_bed", "sofa"):
        return 1 if x < 0 else -1
    if not marks:
        return 1 if x < 0 else -1
    mean = np.mean([m.get("x", 0.0) for m in marks.values()])
    users_left = mean < 0
    if x < 0:
        return -1 if users_left else 1
    return 1 if users_left else -1


def lay_out(items, x0, x1, gap_min=60.0):
    """Places things left to right between x0 and x1 with even gaps (wider than the room if they don't fit): returns
    their x and facing, and the gaps [(a, b)] between their footprints."""
    if not items:
        return [], [(x0, x1)]
    # each one's facing from an even guess at its place, then its footprint so facing
    n = len(items)
    guess = [x0 + (k + 0.5) * (x1 - x0) / n for k in range(n)]
    ss = [facing(d["thing"], g, d) for d, g in zip(items, guess)]
    feet = [footprint(d["thing"], _opts(d), s) for d, s in zip(items, ss)]
    widths = [hi - lo for lo, hi in feet]
    gap = max(gap_min, ((x1 - x0) - sum(widths)) / (n + 1))
    used = sum(widths) + gap * (n + 1)
    cur = (x0 + x1) / 2 - used / 2 + gap
    xs, gaps, prev = [], [], (x0 + x1) / 2 - used / 2
    for (lo, hi), w in zip(feet, widths):
        xs.append(cur - lo)
        gaps.append((prev, cur))
        prev = cur + w
        cur += w + gap
    gaps.append((prev, max(prev, (x0 + x1) / 2 + used / 2)))
    return list(zip(xs, ss)), gaps


def spots(gaps, ground, prefix="spot", center=0.0, R=64.0):
    """Free marks in the gaps between things: standing spots, a floor spot, a push-up spot, a pair's spot."""
    out = {}
    k = 0
    big = sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)
    for a, b in gaps:
        if b - a >= 150:
            k += 1
            x = (a + b) / 2
            out[f"{prefix}" if k == 1 else f"{prefix}_{k}"] = {"kind": "stand", "x": x, "f": 1 if x < center else -1}
    if not out:   # no free floor: in front of the things, at the widest gap
        x = (big[0][0] + big[0][1]) / 2 if big else center
        out[prefix] = {"kind": "stand", "x": x, "f": 1 if x < center else -1}
    if big and big[0][1] - big[0][0] >= 240:
        a, b = big[0]
        x = (a + b) / 2
        out["floor"] = {"kind": "floor", "x": x - 40 * (1 if x < center else -1), "f": 1 if x < center else -1}
    if big and big[0][1] - big[0][0] >= 330:
        a, b = big[0]
        out["pair"] = {"kind": "pair", "x": (a + b) / 2, "f": 1}
    if big and big[0][1] - big[0][0] >= 430:
        a, b = big[0]
        out["pushup"] = {"kind": "pushup", "x": (a + b) / 2 + 150, "f": 1}
    return out


def unique(marks: dict, more: dict, thing: str) -> None:
    for name, m in more.items():
        key, k = name, 1
        while key in marks:
            k += 1
            key = f"{name}_{k}"
        m = dict(m)
        m.setdefault("thing", thing)
        marks[key] = m


# --- a room, a hall, a corridor -------------------------------------------------------------------------------------------
class ComposedRoom(Room):
    """A room, a hall or a corridor laid out from a description."""

    R = 64.0

    def __init__(self, spec: dict, size, light="dusk", weather="clear", effects=(), center=None, seed="place",
                 height=None):
        self.spec, self.missing = norm(spec)
        self.kind, self.weather, self.seed = self.spec["kind"], _weather(weather, self.spec, effects), str(seed)
        k = self.kind
        self.FLOOR = 300.0
        self.CENTER = (0.0, 0.0 if k != "hall" else -100.0)
        self.HEIGHT = {"hall": 1150.0}.get(k, 900.0)
        self.TALL_WIDTH = {"hall": 900.0}.get(k, 720.0)
        half = self.HEIGHT * 16 / 9 / 2   # (the layout always uses the whole room, however close the framing)
        self.ZOOM = 1.0   # how much closer than the room's own wide framing (the window's view softens with it)
        if height:
            self.ZOOM = max(1.0, self.HEIGHT / float(height))
            self.TALL_WIDTH *= float(height) / self.HEIGHT
            self.HEIGHT = float(height)
        self.SPAN = (-half - 600, half + 600)
        self.PAN = (300.0, 30.0)
        self.WALL_TINT = WALLS[self.spec["wall"]]
        lit = bool(LIGHTS[light]["lamp"] or self.weather == "rain")
        self.ctx_args = dict(light=light, weather=self.weather, lit=lit)
        # the things on the floor, left to right; then the window, the lamps, the wall things, the small things
        items = list(self.spec["things"])
        if k == "corridor" and not items:
            items = [{"thing": "door"}, {"thing": "waiting_chairs"}, {"thing": "door", "open": True}, {"thing": "plant"}]
        row = [d for d in items if PR.PROPS[d["thing"]][3] in ("back", "mid")]
        x0, x1 = -half + 50, half - 50
        placed, gaps = lay_out(row, x0, x1)
        self.things = []
        for d, (x, s) in zip(row, placed):
            self.things.append(PR.Thing(d["thing"], x, self.FLOOR, self._ctx(s, d, len(self.things))))
        stage = next((t for t in self.things if t.name == "stage"), None)
        for t in self.things:   # a podium stands on the stage, its speaker on the stage's floor
            if t.name == "podium" and stage is not None:
                t.x, t.b = stage.x + 240, stage.b - 70
        for d in items:   # rugs and mats under the things, the audience in front of the lens
            if PR.PROPS[d["thing"]][3] == "floor":
                x = self._floor_spot(d["thing"], gaps)
                self.things.append(PR.Thing(d["thing"], x, self.FLOOR, self._ctx(1, d, len(self.things))))
            elif PR.PROPS[d["thing"]][3] == "fore":
                self.things.append(PR.Thing(d["thing"], 0.0, self.FLOOR, self._ctx(1, d, len(self.things))))
        self.windows = self._windows(x0, x1)
        if self.windows:
            xs = [w[0] for w in self.windows] + [w[2] for w in self.windows]
            ys = [w[1] for w in self.windows] + [w[3] for w in self.windows]
            self.WINDOW = (min(xs), min(ys), max(xs), max(ys), 1, 1)
        else:
            self.WINDOW = None
        self.lamps = self._lamps()
        self.LAMP = self.lamps[0][:2] if self.lamps else None
        self.LAMP_TO = self.lamps[0][2] if self.lamps else self.FLOOR
        self.ALWAYS_LIT = k in ("hall", "corridor")
        self.wall_things = self._wall_things(x0, x1)
        self.small_things = self._small_things(gaps)
        # where people can be
        marks = {}
        for t in self.things + self.wall_things:
            unique(marks, t.marks(), t.name)
        marks.update(spots(gaps, self.FLOOR, center=0.0))
        for w in self.windows[:1]:
            wx = (w[0] + w[2]) / 2
            marks["window"] = {"kind": "stand", "x": wx + (w[2] - w[0]) * 0.22, "f": -1, "lift": 0.15, "arms": "pockets",
                               "use": ["at_window"]}
        a = min(x0, min((t.x - t.width / 2 for t in self.things), default=x0)) - 260
        b = max(x1, max((t.x + t.width / 2 for t in self.things), default=x1)) + 260
        first = next((m for n, m in marks.items() if n.startswith("spot")), None)
        marks["walk_in"] = {"kind": "walk", "from": a, "to": first["x"] if first else 0.0, "f": 1}
        marks["walk_out"] = {"kind": "walk", "from": first["x"] if first else 0.0, "to": b, "f": 1}
        marks["cross"] = {"kind": "walk", "from": a, "to": b, "f": 1}
        self.MARKS = marks
        self.fx_names = list(self.spec["effects"]) + list(effects or ())
        super().__init__(size, light, rain=self.weather == "rain", center=center)
        # what moves, what's out of focus in front, the effects
        self.anim = Dynamic(self.cam, 0.72) if any(t.moves for t in self.things + self.small_things) else None
        self.mirror_layer = Dynamic(self.cam, 0.72)
        self.mask_layer = Dynamic(self.cam, 0.72)
        fore = [t for t in self.things if t.layer == "fore"]
        if fore:
            self.plant = Static(self.cam, 1.30, lambda p: [t.draw(p) for t in fore], blur=3.0 * self.k,
                                margin=(MARGIN + 200, MARGIN + 200))
        self.effects = self._effects(self.fx_names)

    # --- building ---------------------------------------------------------------------------------------------------------
    def _ctx(self, s, d, k):
        return PR.Ctx(s=s, seed=f"{self.seed}/{d['thing']}/{k}", opts=_opts(d), **self.ctx_args)

    def _floor_spot(self, name, gaps):
        if name == "gym_mat":
            a, b = max(gaps, key=lambda g: g[1] - g[0])
            return (a + b) / 2
        under = next((t for t in self.things if t.name in ("sofa", "coffee_table", "dining_table", "bed", "armchair")), None)
        return under.x if under else 0.0

    def _tall(self):
        return [(t.x - t.width / 2 - 20, t.x + t.width / 2 + 20) for t in self.things if t.tall and t.layer != "fore"]

    def _windows(self, x0, x1):
        size = self.spec["window"]
        if size == "none" or self.kind == "corridor" and size not in ("small",):
            return []
        busy = sorted(self._tall())
        free, cur = [], x0
        for a, b in busy:
            if a > cur:
                free.append((cur, a))
            cur = max(cur, b)
        if cur < x1:
            free.append((cur, x1))
        if not free:
            return []
        a, b = max(free, key=lambda g: g[1] - g[0])
        need = sum(PR.PROPS[d["thing"]][2] + 110 for d in self.spec["wall_things"]) + 60
        others = sum(g[1] - g[0] for g in free) - (b - a)
        if need > others:   # the wall things need some of this stretch: the window keeps to one end of it
            room = max(220.0, (b - a) - (need - max(0.0, others)))
            if a + room / 2 < 0:
                a, b = a, a + room
            else:
                a, b = b - room, b
        if size == "tall":   # a hall's row of tall windows across its free wall
            out = []
            n = max(1, int((b - a) // 420))
            step = (b - a) / n
            for k in range(n):
                cx = a + step * (k + 0.5)
                out.append((cx - 115, -720.0, cx + 115, 60.0, 2, 4))
            return out
        want = {"small": 330.0, "big": 560.0, "wide": 1200.0}[size]
        w = min(want, (b - a) - 60)
        if w < 180:
            return []
        cx = (a + b) / 2
        y0, y1 = {"small": (-330.0, -40.0), "big": (-350.0, 60.0), "wide": (-340.0, 50.0)}[size]
        cols = max(1, int(round(w / 170)))
        return [(cx - w / 2, y0, cx + w / 2, y1, cols, 2 if size != "small" else 2)]

    def _lamps(self):
        """(x, y, where its light lands): a hanging lamp over the table or the desk; a hall's row of pendants; a
        corridor's ceiling lamps."""
        if self.kind == "hall":
            return [(x, -460.0, self.FLOOR) for x in np.arange(-900, 901, 450)]
        if self.kind == "corridor":
            return [(x, -420.0, self.FLOOR) for x in np.arange(-760, 761, 380)]
        if self.spec["lamp"] != "hanging":
            return []
        over = next((t for t in self.things if t.name in ("dining_table", "meeting_table", "coffee_table", "workbench",
                                                           "shop_counter", "prep_counter", "desk")), None)
        if over is not None:
            surf = over.surface()
            x = (surf[0] + surf[1]) / 2 if surf else over.x
            return [(x, -255.0, surf[2] if surf else self.FLOOR)]   # (above a standing head: lower, it lay across faces)
        return [(0.0, -255.0, self.FLOOR)]

    def _wall_things(self, x0, x1):
        busy = sorted(self._tall() + [(w[0] - 40, w[2] + 40) for w in self.windows])
        out = []
        for d in self.spec["wall_things"]:
            w = PR.PROPS[d["thing"]][2]
            spot, cur = None, x0 + 20
            for a, b in busy + [(x1 - 20, x1 + 1e9)]:
                if a - cur >= w + 30:
                    spot = cur + 20 + w / 2
                    break
                cur = max(cur, b)
            if spot is None:
                self.missing.append(f"room on the wall for: {d['thing']}")
                continue
            busy.append((spot - w / 2 - 20, spot + w / 2 + 20))
            busy.sort()
            out.append(PR.Thing(d["thing"], spot, self.FLOOR, self._ctx(1, d, 100 + len(out))))   # (never mirrored)
        return out

    def _small_things(self, gaps):
        out = []
        surfaces = []
        for t in self.things + self.wall_things:
            s_ = t.surface()
            if s_:
                surfaces.append([t, s_[0] + 8, s_[1], s_[2]])
        surfaces.sort(key=lambda s_: s_[0].name in ("bed", "hospital_bed", "sofa"))   # (a table before a bed)
        floor_gaps = sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)
        for d in self.spec["small"]:
            name = d["thing"]
            w = PR.PROPS[name][2]
            if PR.PROPS[name][3] == "small":
                desk = next((t for t in self.things if t.name == "desk"), None)
                if name == "laptop" and desk is not None and not desk.c.o.get("laptop"):
                    desk.c.o["laptop"] = True
                    continue
                spot = next((s_ for s_ in surfaces if s_[2] - s_[1] >= w), None)
                if spot is None and floor_gaps:   # (no room on any surface: on the floor, by the wall)
                    a, b = floor_gaps[0]
                    x = a + 30 + w / 2 if (a + b) / 2 < 0 else b - 30 - w / 2
                    t = PR.Thing(name, x, self.FLOOR, self._ctx(1, d, 200 + len(out)))
                    t.on = None
                    out.append(t)
                    continue
                if spot is None:
                    self.missing.append(f"a surface for: {name}")
                    continue
                x = spot[1] + w / 2
                spot[1] += w + 10
                t = PR.Thing(name, x, spot[3], self._ctx(spot[0].c.s, d, 200 + len(out)))
                t.on = spot[0]
            else:
                if not floor_gaps:
                    continue
                a, b = floor_gaps[0]
                x = a + 30 + w / 2 if (a + b) / 2 < 0 else b - 30 - w / 2
                t = PR.Thing(name, x, self.FLOOR, self._ctx(1, d, 200 + len(out)))
                t.on = None
            out.append(t)
        return out

    def _effects(self, names):
        out = []
        for name in dict.fromkeys(names):
            kw = {}
            if name == "fire":
                at = next((t for t in self.things if t.name in ("stove", "counter", "chef_range", "sofa", "bed")), None)
                if at is not None:
                    kw = {"x": at.x, "base": at.b - (160 if at.name in ("stove", "counter", "chef_range") else 90),
                          "width": min(at.width, 380), "height": 240}
                else:
                    kw = {"x": 380.0, "base": self.FLOOR, "width": 420.0, "height": 300.0}
            elif name == "smoke":
                kw = {"x": 0.0, "top": -300.0, "width": 900.0, "rise": 300.0}
            elif name == "emergency":
                kw = {"x": (self.WINDOW[0] + self.WINDOW[2]) / 2 if self.WINDOW else 900.0, "y": -150.0, "strength": 0.8}
            elif name == "snow":
                kw = {"room": True}
            elif name == "fog":
                kw = {"room": True, "ground": self.WINDOW[3] if self.WINDOW else 0.0}
            elif name == "party":
                kw = {"x0": self.SPAN[0] + 500, "x1": self.SPAN[1] - 500, "y": -360.0 if self.kind != "hall" else -560.0}
            elif name == "spotlight":
                pod = next((t for t in self.things if t.name == "podium"), None)
                stage = next((t for t in self.things if t.name == "stage"), None)
                if pod is not None:
                    m = next(iter(pod.marks().values()))
                    kw = {"x": m["x"], "floor": pod.b, "top": -900.0}
                else:
                    kw = {"x": stage.x if stage else 0.0, "floor": stage.b - 70 if stage else self.FLOOR, "top": -900.0}
            if name in ("snow", "fog") and not self.WINDOW:
                continue
            out.append(FX.make(name, self, **kw))
        if self.weather in ("snow", "fog") and self.WINDOW and self.weather not in names:
            out.append(FX.make(self.weather, self, room=True, **({"ground": self.WINDOW[3]} if self.weather == "fog" else {})))
        return out

    # --- drawing -----------------------------------------------------------------------------------------------------------
    def _sky(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        sky(p, self.L, x0 - 500, x1 + 500, y0 - 60, y1 + 10, (x0 + x1) / 2 - (x1 - x0) * 0.22,
            self.rain or self.weather in ("snow", "fog"), seed=self.seed)

    def _far(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        view_far(p, self.L, self.spec["view"], x0 - 500, x1 + 500, y1 - 40, self.rain, self.seed)

    def _near(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        view_near(p, self.L, self.spec["view"], x0 - 500, x1 + 500, y1 - 40, self.rain, self.seed)

    def _wall(self, p: Paint):
        near, far = self.wall_colors()
        cx, cy = self.window_center()
        F = self.FLOOR

        def wall(px, py):
            d = np.sqrt(((p.wx(px) - cx) / 900) ** 2 + ((p.wy(py) - cy) / 620) ** 2)
            t = np.clip(d, 0, 1)[..., None] ** 0.8
            return near * (1 - t) + far * t
        p.poly(rect(self.SPAN[0] - 400, -1600, self.SPAN[1] - self.SPAN[0] + 800, F + 1600), wall)
        floor_c = mix(self.L["floor"], FLOORS[self.spec["floor"]], 0.45)
        p.poly(rect(self.SPAN[0] - 400, F, self.SPAN[1] - self.SPAN[0] + 800, 700), floor_c)
        self._floor_pattern(p, floor_c)
        p.poly(rect(self.SPAN[0] - 400, F - 12, self.SPAN[1] - self.SPAN[0] + 800, 12), mix(far, "#000000", 0.2))
        if self.kind == "hall":   # pillars between the windows, a cornice
            p.poly(rect(self.SPAN[0] - 400, -800, self.SPAN[1] - self.SPAN[0] + 800, 22), mix(near, "#000000", 0.25))
            xs = sorted({w[0] - 70 for w in self.windows} | {w[2] + 70 for w in self.windows})
            for x in xs:
                p.poly(rect(x - 26, -800, 52, F + 800), mix(far, near, 0.4))
                p.poly(rect(x - 26, -800, 3, F + 800), mix(near, "#FFFFFF", 0.10), 0.7)
        for x0, y0, x1, y1, cols, rows in self.windows:
            p.poly(rr(x0 - 14, y0 - 14, x1 - x0 + 28, y1 - y0 + 28, 4), hexc("#16101E"))
            bar = 10.0
            pw = (x1 - x0 - bar * (cols - 1)) / cols
            ph = (y1 - y0 - bar * (rows - 1)) / rows
            for c in range(cols):
                for r_ in range(rows):
                    p.cut(rect(x0 + c * (pw + bar), y0 + r_ * (ph + bar), pw, ph))
            p.poly(rect(x0 - 26, y1 + 14, x1 - x0 + 52, 9), mix(near, "#FFFFFF", 0.12))
            p.poly(rect(x0 - 22, y1 + 23, x1 - x0 + 44, 8), mix(far, "#000000", 0.1))
            if self.spec["curtains"]:
                for side, xe in ((-1, x0), (1, x1)):
                    drape = [(xe + side * 70, y0 - 40), (xe + side * 40, y0 + 60), (xe + side * 60, y0 + 170),
                             (xe + side * 36, y1 + 60), (xe + side * 10, y1 + 70), (xe + side * 18, y0 + 150),
                             (xe + side * 4, y0 + 40), (xe + side * 10, y0 - 40)]
                    p.poly(spline(drape, True, 8), mix(near, "#000000", 0.25))
        self._decor(p)

    def _floor_pattern(self, p: Paint, base):
        F, x0, x1 = self.FLOOR, self.SPAN[0] - 400, self.SPAN[1] + 400
        line = mix(base, "#000000", 0.35)
        kind = self.spec["floor"]
        if kind in ("wood", "tiles", "stone"):
            gaps = (14, 34, 62, 100, 150)
            for k, dy in enumerate(gaps):
                p.poly(rect(x0, F + dy, x1 - x0, 1.6), line, 0.35)
                if kind != "wood" or k % 2 == 0:
                    step = {"wood": 260, "tiles": 90, "stone": 200}[kind] * (1 + dy / 150)
                    nxt = F + (gaps[k + 1] if k + 1 < len(gaps) else dy + 60)
                    for x in np.arange(x0 + (k * 57) % step, x1, step):
                        p.poly(tube([(x, F + dy), (x * 1.04, nxt)], 1.4), line, 0.25)
        elif kind == "concrete":
            r = rng("cracks", self.seed)
            for _ in range(4):
                x = r.uniform(-700, 700)
                p.poly(tube([(x, F + 10), (x + 30, F + 40), (x + 10, F + 80)], 1.4), line, 0.3)
        if self.kind in ("hall", "corridor"):   # a polished floor: the lamps' pools mirrored faintly
            for x, y, _ in self.lamps:
                p.glow(x, F + 40, 160, 16, PAL["lamp"] * 0.5, 0.18)

    def _decor(self, p: Paint):
        for t in self.wall_things:
            t.draw(p)
        for t in self.small_things:
            if getattr(t, "on", None) is not None and t.on.layer == "wall":
                t.draw(p)

    def _back(self, p: Paint):
        for t in self.things:
            if t.layer == "floor":
                t.draw(p)
        for t in self.things:
            if t.layer == "back":
                t.draw(p)
        for t in self.small_things:
            if getattr(t, "on", None) is not None and t.on.layer == "back":
                t.draw(p)

    def _mid(self, p: Paint):
        for t in self.things:
            if t.layer == "mid":
                t.draw(p)
        for t in self.small_things:
            if getattr(t, "on", None) is None or t.on.layer == "mid":
                t.draw(p)

    def _front(self, p: Paint):
        for t in self.things:
            t.front(p)

    def _glows(self, p: Paint):
        for t in self.things + self.wall_things + self.small_things:
            t.glow(p)
        if self.kind == "corridor":
            for x, y, _ in self.lamps:
                p.glow(x, self.FLOOR, 200, 18, PAL["lamp"], 0.22)

    def _lamp(self, p: Paint):
        if "spotlight" in self.fx_names:   # under a spotlight the room's own lamps are off
            self.lamp_on = False
        for x, y, _ in self.lamps:
            if self.kind == "corridor":   # flush round ceiling lamps
                p.poly(rect(x - 1.6, -1400, 3.2, y - 6 + 1400), hexc("#140D17"))
                p.poly(ell(x, y, 46, 12, 40), PAL["shade"])
                p.poly(ell(x, y + 8, 40, 5, 40), hexc("#FFF5E1") if self.lamp_on else hexc("#4A3A44"))
                continue
            big = 1.5 if self.kind == "hall" else 1.0
            p.poly(rect(x - 1.6, -1400, 3.2, y - 26 * big + 1400), hexc("#140D17"))
            shade = spline([(x - 12 * big, y - 30 * big), (x + 12 * big, y - 30 * big), (x + 44 * big, y - 6 * big),
                            (x + 58 * big, y + 18 * big), (x, y + 21 * big), (x - 58 * big, y + 18 * big),
                            (x - 44 * big, y - 6 * big)], True, 8)
            p.poly(shade, PAL["shade"])
            p.poly(ell(x, y + 18.5 * big, 56 * big, 4.5 * big, 64), hexc("#FFF5E1") if self.lamp_on else hexc("#4A3A44"))

    def _cone(self, p: Paint):
        for x, y, to in self.lamps:
            big = 1.5 if self.kind == "hall" else 1.0
            top, bot = y + 20 * big, to

            def fall(px, py, top=top, bot=bot):
                u = np.clip((p.wy(py) - top) / max(bot - top, 1), 0, 1)[..., None]
                return PAL["lamp"] * ({"corridor": 0.16, "hall": 0.17}.get(self.kind, 0.28) * (1 - u) ** 1.4 + 0.05)
            spread = (bot - top) * 0.36
            p.poly(np.array([(x - 52 * big, top), (x + 52 * big, top), (x + 52 * big + spread, bot),
                             (x - 52 * big - spread, bot)], float), fall, soft=9)
            p.glow(x, top, 60 * big, 13, PAL["lamp"], 0.30)
            p.glow(x, bot, min(52 * big + spread, 160), 7, PAL["lamp"], 0.26)

    def fx(self, frame, at, tau, stage):
        if stage == "back" and self.anim is not None:
            ap = self.anim.paint(at)
            for t in self.things + self.small_things:
                if t.moves:
                    t.animate(ap, tau)
            self.anim.composite(frame, ap)
        for e in self.effects:
            if stage in e.stages:
                e.draw(stage, frame, at, tau)

    def put_people(self, frame, at, st, slot, p):
        super().put_people(frame, at, st, slot, p)
        if slot == "main":
            for a in st.get("actors") or []:
                if a.get("glass"):
                    self._reflect(frame, at, a)

    def _reflect(self, frame, at, actor):
        """Someone at a mirror: their reflection in the glass, facing them, dimmer and cooler."""
        gx0, gy0, gx1, gy1 = actor["glass"]
        gx = (gx0 + gx1) / 2
        side = 1 if actor["pose"]["head"][0] > gx else -1
        pose = mirror_pose(actor["pose"], gx, 0.70, shift=-side * (gx1 - gx0) * 0.12)
        mp = self.mirror_layer.paint(at)
        S.draw_person(mp, pose, actor["look"], S.eyes_for("tired", (pose["f"] * 1.0, 0.0), actor["look"].gap)
                      if actor.get("eyes") is None else _mirror_eyes(actor["eyes"]))
        kp = self.mask_layer.paint(at)
        kp.poly(ell(gx, (gy0 + gy1) / 2, (gx1 - gx0) / 2, (gy1 - gy0) / 2, 64) if actor.get("oval")
                else rect(gx0, gy0, gx1 - gx0, gy1 - gy0), (1.0, 1.0, 1.0))
        if mp.dirty is not None and kp.dirty is not None:
            mask = self.mask_layer.buf[..., 3:4]
            self.mirror_layer.buf *= mask
            self.mirror_layer.buf[..., :3] *= np.array([0.80, 0.85, 1.0], np.float32) * 0.85
        self.mirror_layer.composite(frame, mp)
        if kp.dirty is not None:
            x0, y0, x1, y1 = kp.dirty
            self.mask_layer.buf[y0:y1, x0:x1] = 0


def _mirror_eyes(e: S.Eyes) -> S.Eyes:
    return S.Eyes(look=(-e.look[0], e.look[1]), open_=e.open, size=e.size, tilt=e.tilt, gap=e.gap, smile=e.smile)


def mirror_pose(pose: dict, gx: float, k: float = 0.7, shift: float = 0.0) -> dict:
    """A pose seen in a mirror at x = gx: turned round to face back, smaller by k about the head's height, its body's
    middle at gx + shift."""
    hx, hy = pose["head"]
    mid = pose["S"][0]

    def m(pt):
        return (gx + shift - (pt[0] - mid) * k, hy + (pt[1] - hy) * k)
    out = {}
    for key, v in pose.items():
        if key in ("S", "H", "head"):
            out[key] = m(v)
        elif key in ("near", "far") and v:
            out[key] = tuple(m(q) for q in v)
        elif key == "legs":
            out[key] = [tuple(m(q) for q in leg) for leg in v]
        elif key in ("hold", "far_hold") and v:
            out[key] = {kk: (m(vv) if isinstance(vv, tuple) and len(vv) == 2 else vv) for kk, vv in v.items()}
        else:
            out[key] = v
    out["f"] = -pose["f"]
    out["R"] = pose["R"] * k
    out["T"], _, _ = S.spine(out["S"], out["H"], out["f"], out["R"])
    return out


# --- outdoors: a street, houses, a bridge, nature ------------------------------------------------------------------------
class ComposedOutdoor(Outdoor):
    """A street, a quiet street of houses, a bridge or a piece of nature, laid out from a description."""

    R = 58.0

    def __init__(self, spec: dict, size, light="dusk", weather="clear", effects=(), center=None, seed="place",
                 height=None):
        self.spec, self.missing = norm(spec)
        self.kind, self.weather, self.seed = self.spec["kind"], _weather(weather, self.spec, effects), str(seed)
        self.nat = self.spec["nature"] if self.kind == "nature" else None
        if height:
            self.TALL_WIDTH = self.TALL_WIDTH * float(height) / self.HEIGHT
            self.HEIGHT = float(height)
        self.GROUND = 300.0
        self.HORIZON = {"sea": 110.0, "lake": 90.0, "field": 170.0, "mountains": 140.0}.get(self.nat, 150.0)
        if self.kind == "bridge":
            self.HORIZON = 30.0
        self.SPAN = (-1700.0, 1700.0)
        self.PAN = (640.0, 40.0)
        L = LIGHTS[light]
        lit = bool(L["lamp"] or self.weather == "rain")
        self.ctx_args = dict(light=light, weather=self.weather, lit=lit)
        back = [d for d in self.spec["things"] if PR.PROPS[d["thing"]][3] == "back"]
        mid = [d for d in self.spec["things"] if PR.PROPS[d["thing"]][3] in ("mid", "floor")]
        if self.kind == "houses" and not any(d["thing"] == "house" for d in back):
            back = [{"thing": "tree"}, {"thing": "house"}, {"thing": "house", "color": "#2E2430"}, {"thing": "tree"}] + back
        if self.kind == "nature" and self.nat == "forest" and not back:
            back = [{"thing": "tree"}, {"thing": "pine"}, {"thing": "tree"}, {"thing": "pine"}, {"thing": "tree"}]
        if self.kind == "nature" and self.nat == "field" and not back:
            back = [{"thing": "tree"}]
        placed, _ = lay_out(back, -1500, 1500, gap_min=40)
        if len(back) == 1:   # one tree, one house: off to the side, not behind whoever stands in the middle
            placed = [(560.0, placed[0][1])]
        lift = {"street": 40, "houses": 68, "bridge": 22}.get(self.kind, 30)
        self.backs = [PR.Thing(d["thing"], x, self.GROUND - lift, self._ctx(s, d, k))
                      for k, (d, (x, s)) in enumerate(zip(back, placed))]
        placed, gaps = lay_out(mid, -760, 760)
        self.mids = [PR.Thing(d["thing"], x, self.GROUND, self._ctx(s, d, 50 + k)) for k, (d, (x, s)) in enumerate(zip(mid, placed))]
        lamps = [t.x for t in self.mids if t.name == "street_lamp"]
        if not lamps and self.kind in ("street", "bridge", "houses"):
            lamps = [-560.0, 330.0, 1220.0] if self.kind != "houses" else [-300.0, 900.0]
        self.LAMPS = tuple(lamps)
        self.small_things = []
        marks = {}
        for t in self.mids:
            unique(marks, t.marks(), t.name)
        for t in self.backs:
            unique(marks, t.marks(), t.name)
        marks.update(spots(gaps, self.GROUND, center=0.0))
        marks["walk"] = {"kind": "walk", "from": -900.0, "to": 200.0, "f": 1}
        marks["walk_away"] = {"kind": "walk", "from": 200.0, "to": 1300.0, "f": 1}
        marks["run"] = {"kind": "run", "from": -1100.0, "to": 1100.0, "f": 1}
        marks["crowd"] = [{"kind": "walk", "from": 1300.0, "to": -1000.0, "f": -1},
                          {"kind": "walk", "from": -1200.0, "to": 900.0, "f": 1}]
        self.MARKS = marks
        super().__init__(size, light, rain=self.weather == "rain", center=center)
        self.lamps_on = self.L["lamp"] or self.rain
        moving = [t for t in self.mids + self.backs if t.moves]
        self.anim = Dynamic(self.cam, 0.70) if moving else None
        fore = self._fore_kind()
        if fore:
            self.fore = Static(self.cam, 1.35, fore, blur=3.0 * self.k, margin=(MARGIN + 300, MARGIN + 200))
        self.water_fx = Dynamic(self.cam, 0.50, add=True) if self.nat in ("sea", "lake") or self.kind == "bridge" else None
        self.effects = self._effects(list(self.spec["effects"]) + list(effects or ()))

    def _ctx(self, s, d, k):
        return PR.Ctx(s=s, seed=f"{self.seed}/{d['thing']}/{k}", opts=_opts(d), **self.ctx_args)

    def _effects(self, names):
        out = []
        for name in dict.fromkeys(names + ([self.weather] if self.weather in ("snow", "fog") else [])):
            kw = {}
            if name == "fire":
                at = next((t for t in self.backs + self.mids if t.name in ("house", "shopfront", "car", "campfire")), None)
                if at is not None and at.name == "campfire":
                    continue
                if at is not None:
                    top = {"house": 380, "shopfront": 300, "car": 200}[at.name]
                    kw = {"x": at.x, "base": at.b - top + 40, "width": at.width * 0.75, "height": 260.0,
                          "depth": 0.42 if at in self.backs else 0.70}
                else:
                    kw = {"x": 520.0, "base": self.GROUND - 40, "width": 420.0, "height": 320.0, "depth": 0.42}
            elif name == "smoke":
                kw = {"x": 300.0, "top": self.GROUND - 400, "width": 500.0, "rise": 900.0, "depth": 0.42}
            elif name == "emergency":
                amb = next((t for t in self.mids if t.name == "ambulance"), None)
                kw = {"x": amb.x if amb else 1000.0, "y": self.GROUND - 400}
            elif name == "snow":
                kw = {}
            elif name == "fog":
                kw = {"ground": self.GROUND}
            elif name == "party":
                kw = {"x0": -900.0, "x1": 900.0, "y": -260.0}
            elif name == "spotlight":
                kw = {"x": 0.0, "floor": self.GROUND, "top": -900.0}
            out.append(FX.make(name, self, **kw))
        return out

    # --- the land ------------------------------------------------------------------------------------------------------
    def _sky(self, p: Paint):
        sky(p, self.L, self.SPAN[0] - 600, self.SPAN[1] + 600, -900, self.HORIZON, 380.0,
            self.rain or self.weather in ("snow", "fog"), self.seed)

    def _far(self, p: Paint):
        L, x0, x1, H = self.L, self.SPAN[0] - 600, self.SPAN[1] + 600, self.HORIZON
        grey = self.rain or self.weather in ("snow", "fog")
        far = mix(L["far"], RAINY, 0.3) if grey else hexc(L["far"])
        snowcap = mix(L["cloud"], "#FFFFFF", 0.35)
        if self.kind in ("street", "bridge"):
            city(p, H + 80, x0, x1, (H - 210, H - 60), (30, 110), far, self.seed + "far", win=L["win"], lit=L["lit"] * 0.5,
                 cell=(14, 18))
        elif self.kind == "houses":
            hills(p, x0, x1, H + 40, 70, far, self.seed)
            rooftops(p, x0, x1, H + 70, mix(far, L["near"], 0.4), self.seed, win=L["win"], lit=L["lit"] * 0.6)
        elif self.nat == "hills":
            hills(p, x0, x1, H + 30, 220, far, self.seed, 4)
            hills(p, x0, x1, H + 90, 150, mix(far, L["near"], 0.45), self.seed + "2", 5)
        elif self.nat == "mountains":
            mountains(p, x0, x1, H + 40, 520, far, self.seed, snow=snowcap, peaks=6)
            mountains(p, x0, x1, H + 90, 280, mix(far, L["near"], 0.5), self.seed + "2", snow=None, peaks=9)
        elif self.nat == "field":
            hills(p, x0, x1, H + 10, 50, far, self.seed, 3)
            treeline(p, x0, x1, H + 20, 40, mix(far, L["near"], 0.4), self.seed, 0.5)
        elif self.nat == "forest":
            treeline(p, x0, x1, H + 40, 160, far, self.seed, 1.0)
            treeline(p, x0, x1, H + 120, 200, mix(far, L["near"], 0.5), self.seed + "2", 1.3)
        elif self.nat == "lake":
            hills(p, x0, x1, H + 10, 140, far, self.seed, 3)
            treeline(p, x0, x1, H + 20, 60, mix(far, L["near"], 0.45), self.seed, 0.6)
        haze = self.L["haze"]
        p.poly(rect(x0, H - 120, x1 - x0, 220), flat(haze[0]), haze[1] * (1.6 if self.weather == "fog" else 1.0), soft=30)
        if self.nat == "sea":
            water(p, L, x0, x1, H, self.GROUND - 70, 380.0, grey, self.seed)
        elif self.nat == "lake":
            water(p, L, x0, x1, H + 40, self.GROUND - 60, 380.0, grey, self.seed, still=True)
        elif self.kind == "bridge":
            p.poly(rect(x0, H + 60, x1 - x0, 30), mix(far, "#000000", 0.3))   # the far bank's embankment
            water(p, L, x0, x1, H + 90, self.GROUND - 30, 380.0, grey, self.seed)
            if L["lit"] > 0.2:   # the far bank's lights trailing in the river
                r = rng("trails", self.seed)
                for _ in range(40):
                    x = r.uniform(x0, x1)
                    p.poly(rect(x, H + 92, 3, r.uniform(40, 140)), hexc(L["win"]), 0.30)

    def _backdrop(self, p: Paint):
        L = self.L
        if self.kind == "street":
            self._facades(p)
        if self.nat == "hills":
            hills(p, self.SPAN[0] - 600, self.SPAN[1] + 600, self.GROUND - 30, 70, hexc(L["near"]), self.seed + "n", 6)
        if self.nat == "mountains":
            pines_row(p, self.SPAN[0] - 600, self.SPAN[1] + 600, self.GROUND - 40, hexc(L["near"]) * 0.9, self.seed)
        if self.nat == "forest":   # trees further off, paler in the air: a soft band behind the park's own trees, the
            # sky open above (full-height trunks every few steps read as a glass wall's bars, their crowns as a ceiling)
            haze = mix(L["near"], L["far"], 0.45)
            treeline(p, self.SPAN[0] - 600, self.SPAN[1] + 600, self.GROUND - 40, 300, haze, self.seed + "forest", 1.8)
            if self.weather == "snow":
                p.poly(rect(self.SPAN[0] - 600, self.GROUND - 300, self.SPAN[1] - self.SPAN[0] + 1200, 60), hexc(SNOWY),
                       0.18, soft=30)
        if self.kind == "bridge":
            PR.Thing("railing", 0.0, self.GROUND - 22, PR.Ctx(s=1, **self.ctx_args)).draw(p)
            PR.Thing("railing", 1600.0, self.GROUND - 22, PR.Ctx(s=1, **self.ctx_args)).draw(p)
            PR.Thing("railing", -1600.0, self.GROUND - 22, PR.Ctx(s=1, **self.ctx_args)).draw(p)
        for t in self.backs:
            t.draw(p)

    def _facades(self, p: Paint):
        """The street's buildings: a row of facades with windows (lit at night), behind its own things."""
        r = rng("facades", self.seed)
        base = self.GROUND - 40
        x = self.SPAN[0] - 400
        shown = {"night": 1.0, "dusk": 0.6, "dawn": 0.15, "day": 0.0}[self.light]
        lit_cols = ["#FFC383", "#F2A86E", "#FFD9A0", "#E9B07A"]
        while x < self.SPAN[1] + 400:
            w = r.uniform(300, 560)
            top = base - (r.uniform(480, 900) if r.random() < 0.6 else r.uniform(230, 380))
            col = ["#1C1428", "#221830", "#191223", "#1F162B", "#1A1326"][int(r.integers(5))]
            p.poly(rect(x, top, w + 1, base - top + 40), mix(col, self.L["near"], 0.25))
            p.poly(rect(x, top, 3, base - top), hexc("#3B2B48"), 0.8)
            p.poly(rect(x, top, w, 6), hexc("#2E2338"))
            for wy in np.arange(top + 60, base - 140, 100):
                for wx in np.arange(x + 40, x + w - 70, 110):
                    on = r.random() < 0.32 * shown
                    p.poly(rect(wx, wy, 44, 60), hexc(lit_cols[int(r.integers(4))]) if on else hexc("#120D19"),
                           0.9 if on else 1.0)
            x += w

    def _backdrop_light(self, p: Paint):
        for t in self.backs:
            t.glow(p)

    def _ground(self, p: Paint):
        G_, x0, x1 = self.GROUND, self.SPAN[0] - 900, self.SPAN[1] + 900
        L = self.L
        snow = self.weather == "snow"
        if self.kind in ("street", "bridge", "houses"):
            pave = mix(L["ground"], "#2A2133", 0.4)
            top = G_ - 50 if self.kind != "bridge" else G_ - 22
            p.poly(rect(x0, top, x1 - x0, G_ + 50 - top), gradient([(top, "#181220"), (G_ + 50, "#2A2133")])(p))
            for y in (G_ - 30, G_ + 10):
                p.poly(rect(x0, y, x1 - x0, 2), hexc("#3A2F45"), 0.30)
            p.poly(rect(x0, G_ + 48, x1 - x0, 4), hexc("#5C4A66"), 0.8)
            p.poly(rect(x0, G_ + 52, x1 - x0, 14), hexc("#2E2438"))
            road = "#0B0910" if self.kind != "houses" else "#141018"
            p.poly(rect(x0, G_ + 66, x1 - x0, 600), hexc(road))
            if self.kind == "houses":
                p.poly(rect(x0, top - 18, x1 - x0, 20), mix(pave, "#1E2A22", 0.6))
            if snow:
                p.poly(rect(x0, top - 2, x1 - x0, 50), mix(SNOWY, L["ground"], 0.35), 0.85)
            return
        grass = {"sea": "#5A4A40", "mountains": "#2A2632"}.get(self.nat, "#1E2A22")
        ground = mix(L["ground"], grass, 0.45)
        if snow:
            ground = mix(ground, SNOWY, 0.6)
        top = G_ - (60 if self.nat == "sea" else 40)
        p.poly(rect(x0, top, x1 - x0, 900), lambda px, py: np.broadcast_to(ground, px.shape + (3,)) *
               np.clip(1 - (p.wy(py) - top)[..., None] / 600, 0.45, 1))
        p.poly(rect(x0, top - 1, x1 - x0, 3), mix(ground, "#FFFFFF", 0.18), 0.6)
        if self.nat in ("hills", "field") and not snow:   # a path
            p.poly(rect(x0, G_ - 8, x1 - x0, 26), mix(ground, "#6A5A60", 0.35), 0.7)
        if self.nat == "sea":   # the wet sand at the water's edge
            p.poly(rect(x0, top, x1 - x0, 14), mix(ground, "#000000", 0.3), 0.8)

    def _ground_light(self, p: Paint):
        super()._ground_light(p)
        for t in self.mids:
            t.glow(p)

    def _props(self, p: Paint):
        for t in self.mids:
            t.draw(p)
            t.front(p)

    def _fore_kind(self):
        if self.nat == "field":
            def f(p):
                r = rng("grass", self.seed)
                col = mix(self.L["near"], "#000000", 0.4)
                for x in np.arange(self.SPAN[0], self.SPAN[1], 18):
                    h = r.uniform(60, 170)
                    p.poly(tube([(x, self.GROUND + 160), (x + r.uniform(-20, 20), self.GROUND + 160 - h)], 7.0, 1.0), col)
            return f
        if self.nat == "lake":
            def f(p):
                r = rng("reeds", self.seed)
                col = mix(self.L["near"], "#000000", 0.4)
                for x in list(np.arange(self.SPAN[0], -500, 26)) + list(np.arange(700, self.SPAN[1], 26)):
                    h = r.uniform(160, 300)
                    tip = (x + r.uniform(-25, 25), self.GROUND + 170 - h)
                    p.poly(tube([(x, self.GROUND + 170), tip], 6.0, 1.0), col)
                    if r.random() < 0.3:
                        p.poly(ell(tip[0], tip[1] + 30, 6, 22, 16), col)
            return f
        if self.kind == "bridge":
            def f(p):
                col = hexc("#0C0910")
                p.poly(rect(self.SPAN[0] - 600, self.GROUND + 150, self.SPAN[1] - self.SPAN[0] + 1200, 30), col)
                for x in np.arange(self.SPAN[0] - 600, self.SPAN[1] + 600, 60):
                    p.poly(rect(x, self.GROUND + 180, 16, 200), col)
            return f
        return None

    def fx(self, frame, at, tau, stage):
        if stage == "far" and self.water_fx is not None:   # the water's glints drifting, the shore's foam
            wp = self.water_fx.paint(at)
            r = rng("shimmer", self.seed)
            top = self.HORIZON + (40 if self.nat == "lake" else (90 if self.kind == "bridge" else 0))
            bot = self.GROUND - 60
            glint = hexc(self.L["sun"][0]) if self.L["sun"] else hexc("#C8C0E0")
            for k in range(24):
                v = r.uniform(0, 1)
                y = top + 6 + v * (bot - top - 12)
                x = 380 + r.normal(0, 60 + 120 * v) + 30 * math.sin(tau * 0.6 + k)
                a = 0.25 * (0.5 + 0.5 * math.sin(tau * 1.3 + k * 1.7)) * (1 - v * 0.5)
                wp.poly(rect(x, y, r.uniform(10, 30), 1.6), glint, a)
            if self.nat == "sea":
                w = math.sin(tau * 0.5) * 6
                wp.poly(rect(self.SPAN[0] - 600, bot + 4 + w, self.SPAN[1] - self.SPAN[0] + 1200, 3), hexc("#E8E0F0"), 0.35,
                        soft=2)
            self.water_fx.composite(frame, wp)
        if stage == "back" and self.anim is not None:
            ap = self.anim.paint(at)
            for t in self.backs + self.mids:
                if t.moves:
                    t.animate(ap, tau)
            self.anim.composite(frame, ap)
        for e in self.effects:
            if stage in e.stages:
                e.draw(stage, frame, at, tau)


# --- inside a car, a bus, a train: the world sliding past ----------------------------------------------------------------
class Scroll:
    """A layer of the world outside a moving vehicle: drawn once (repeating every `period` world units) and slid past
    at `speed` (world units a second, at its depth) as the shot goes on."""

    def __init__(self, place, depth, draw, period, speed, blur=0.0, add=False):
        self.place, self.depth, self.period, self.speed = place, depth, float(period), float(speed)
        m = (MARGIN + int(period * place.k * 0.55) + 16, MARGIN)

        def tiled(p):
            for k in range(-3, 4):
                draw(p, k * self.period)
        self.layer = Static(place.cam, depth, tiled, blur=blur, add=add, margin=m)

    def composite(self, frame, at):
        off = (self.place._tau * self.speed) % self.period - self.period / 2
        cx, cy, z = at
        self.layer.composite(frame, (cx + off / max(self.depth, 1e-6), cy, z))


class Vehicle(Room):
    """Inside something moving: its windows show the world sliding past (Scroll layers), the road's small bounce."""

    VIEW = "city"
    SPEED = 1.0
    R = 64.0

    def __init__(self, spec, size, light="night", weather="clear", effects=(), center=None, seed="vehicle", height=None):
        if height:
            self.TALL_WIDTH = self.TALL_WIDTH * float(height) / self.HEIGHT
            self.HEIGHT = float(height)
        self.spec, self.missing = norm(spec)
        self.weather, self.seed = weather if weather in WEATHER else "clear", str(seed)
        self.view_kind = self.spec["view"] if spec and spec.get("view") else self.VIEW
        color = str((spec or {}).get("color") or "")
        self.color = color if color.startswith("#") and len(color) == 7 else "#2A2838"
        self.things, self.small_things, self.wall_things = [], [], []
        super().__init__(size, light, rain=self.weather == "rain", center=center)
        self.effects = [FX.make(self.weather, self, room=True)] if self.weather in ("snow", "fog") else []

    def _make_view(self):
        L, seed, v = self.L, self.seed, self.view_kind
        x0, y0, x1, y1 = self.WINDOW[:4]
        grey = self.rain or self.weather in ("snow", "fog")
        horizon = y1 - 60

        def far(p, off):
            view_far(p, L, v if v != "sea" else "hills", x0 - 900 + off, x0 + 900 + off, horizon, grey, seed)

        def near(p, off):
            if v == "city":
                city(p, horizon + 120, x0 - 900 + off, x0 - 900 + off + 1800, (horizon - 160, horizon - 40), (60, 140),
                     hexc(L["near"]), seed + "n", win=L["win"], lit=L["lit"], cell=(16, 20), size=(6, 8))
            elif v == "sea":
                water(p, L, x0 - 900 + off, x0 - 900 + off + 1800, horizon - 10, horizon + 160, (x0 + x1) / 2, grey, seed)
            else:
                view_near(p, L, v, x0 - 900 + off, x0 - 900 + off + 1800, horizon, grey, seed)

        def posts(p, off):   # lamp posts, poles or trees flashing by close to the glass
            dark = hexc("#0E0A12")
            for k in range(3):
                x = x0 - 900 + off + k * 600
                if v == "city" or v == "houses":
                    p.poly(rect(x - 8, y0 - 400, 16, 1200), dark)
                    p.poly(ell(x - 40, horizon - 200, 30, 8, 24), hexc("#FFF1D6") if L["lamp"] else hexc("#4A3A44"))
                elif v in ("trees", "hills", "fields", "mountains"):
                    p.poly(rect(x - 7, y0 - 400, 14, 1200), dark)
                    p.poly(rect(x - 60, y0 + 30, 120, 9), dark)
                    for dy in (0, 26):
                        p.poly(tube([(x - 600 + 60, y0 + 40 + dy + 30), (x - 300, y0 + 70 + dy + 30),
                                     (x - 60, y0 + 40 + dy)], 2.0, k=4), dark, 0.8)

        def lights(p, off):
            if L["lamp"]:
                for k in range(3):
                    p.glow(x0 - 900 + off + k * 600 - 40, horizon - 200, 120, 80, PAL["lamp"], 0.35)
        s = self.SPEED
        out = [self.static(0.08, self._sky, blur=1.2),
               Scroll(self, 0.20, far, 1800.0, 30.0 * s, blur=1.4),
               Scroll(self, 0.40, near, 1800.0, 160.0 * s, blur=1.0 * s),
               Scroll(self, 0.55, posts, 1800.0, 900.0 * s, blur=3.0 * s),
               Scroll(self, 0.55, lights, 1800.0, 900.0 * s, blur=3.0 * s, add=True)]
        return out

    @property
    def inside_lit(self):
        return bool(self.L["lamp"] or self.rain)

    def _sky(self, p: Paint):
        x0, y0, x1, y1 = self.WINDOW[:4]
        sky(p, self.L, x0 - 900, x1 + 900, y0 - 200, y1 - 30, (x0 + x1) / 2, self.rain or self.weather in ("snow", "fog"),
            seed=self.seed)

    def fx(self, frame, at, tau, stage):
        for e in getattr(self, "effects", ()):
            if stage in e.stages:
                e.draw(stage, frame, at, tau)
        if stage == "front" and self.L["lamp"]:   # street lamps' light sweeping through, now and then
            u = (tau / 2.2) % 1.0
            p = self.sweep.paint(at)
            x = 900 - 1800 * u
            p.glow(x, -60, 260, 300, PAL["lamp"], 0.10 * math.sin(math.pi * u))
            self.sweep.composite(frame, p)

    def frame(self, index, st):
        tau = st.get("tau", index / S.FPS)
        cx, cy, z = st["cam"]
        st = dict(st, cam=(cx, cy + 1.6 * math.sin(tau * 9.0) + 0.8 * math.sin(tau * 23.0), z))
        return super().frame(index, st)


class CarInside(Vehicle):
    """Inside a car at the driver's side, seen through its near window: him at the wheel, the dashboard's glow, the far
    window and the windscreen showing the world sliding past; a back seat behind the pillar."""

    WINDOW = (-760.0, -150.0, 520.0, 140.0, 1, 1)
    CENTER = (-40.0, 10.0)
    HEIGHT, TALL_WIDTH = 700.0, 560.0
    FLOOR = 300.0
    MARKS = {"driver": {"kind": "drive", "x": -50.0, "seat": 238.0, "f": 1, "reach": (150.0, 100.0), "slot": "bed",
                        "ground": 330.0, "use": ["driving"]},
             "back_seat": {"kind": "sit", "x": -470.0, "seat": 238.0, "f": 1, "slot": "bed", "ground": 330.0}}

    def __init__(self, spec, size, light="night", weather="clear", effects=(), center=None, seed="car", height=None):
        super().__init__(spec, size, light, weather, effects, center, seed, height)
        self.sweep = Dynamic(self.cam, 0.72, add=True)

    def _wall(self, p: Paint):
        """The car's far side and roof inside: dark, the far windows and the windscreen cut out."""
        inner = mix("#1A1622", self.L["wall"][1], 0.3)
        p.poly(rect(-1600, -1200, 3200, 2400), inner)
        for pts in ([(-720, -120), (-420, -120), (-420, 120), (-720, 120)],
                    [(-380, -130), (200, -130), (230, 110), (-380, 110)],
                    [(250, -150), (420, -150), (560, 120), (300, 120)]):
            p.cut(np.array(pts, float))
        p.poly(rect(-1600, -170, 3200, 30), hexc("#24202C"))
        p.poly(rect(-1600, 116, 3200, 8), mix(inner, "#FFFFFF", 0.06))

    def _back(self, p: Paint):
        seat = hexc("#2A2632")
        for sx in (-120, -545):   # the seats' backs behind the driver and the back seat
            p.poly(rr(sx - 30, -40, 62, 290, 20), seat)
            p.poly(rr(sx - 22, -100, 48, 64, 14), seat)
            p.poly(rr(sx - 20, 225, 200, 40, 12), seat)
        p.poly(np.array([(170, 80), (560, 60), (600, 330), (170, 330)], float), hexc("#1E1A26"))   # the dashboard
        p.poly(rect(172, 78, 390, 4), hexc("#5A5068"), 0.7)

    def _mid(self, p: Paint):
        p.poly(tube([(205, 30), (232, 74), (250, 100)], 9.0), hexc("#141018"))      # the wheel's column
        p.poly(tube([(140, 150), (168, 98), (190, 30)], 14.0), hexc("#141018"))     # the wheel, edge on
        p.poly(tube([(146, 146), (172, 98), (194, 34)], 3.0), hexc("#5A5068"), 0.8)

    def _front(self, p: Paint):
        """The car's near side: the door below the window, the roof above, the pillars; all in front of him."""
        body = hexc(self.color)
        p.poly(rect(-1600, 150, 3200, 900), body)
        p.poly(rect(-1600, 148, 3200, 4), mix(body, "#FFFFFF", 0.25), 0.8)
        p.poly(rect(-1600, -1200, 3200, 1020), body)
        p.poly(rect(-1600, -184, 3200, 4), mix(body, "#FFFFFF", 0.18), 0.7)
        p.poly(np.array([(-350, -185), (-300, -185), (-300, 152), (-350, 152)], float), body)        # the middle pillar
        p.poly(np.array([(330, -185), (420, -185), (620, 152), (520, 152)], float), body)          # the front pillar
        p.poly(rr(-40, 230, 70, 14, 6), mix(body, "#FFFFFF", 0.15))                                 # the door's handle
        p.poly(tube([(-300, 150), (526, 150)], 3.0), mix(body, "#FFFFFF", 0.35), 0.7)               # the sill's edge
        p.poly(rr(470, 30, 110, 70, 14), body)                                                       # the mirror
        p.poly(rr(478, 38, 94, 54, 10), hexc("#3A3446"))

    def _glows(self, p: Paint):
        on = self.L["lamp"] or self.rain
        p.glow(240, 92, 80, 30, (0.35, 0.75, 0.85) if on else (0.5, 0.5, 0.6), 0.30 if on else 0.08)
        p.glow(330, 92, 40, 20, (1.0, 0.6, 0.3), 0.20 if on else 0.05)

    def rim_dir(self, x):
        return (1.0, -0.4)


class BusInside(Vehicle):
    """Inside a city bus, looking across it: a row of seats facing the way it goes, windows above with the city passing,
    grab poles, straps on a rail, the ceiling's lights."""

    WINDOW = (-1100.0, -260.0, 1100.0, 30.0, 1, 1)
    CENTER = (0.0, 0.0)
    FLOOR = 300.0
    MARKS = {"seat": {"kind": "sit", "x": -330.0, "seat": 212.0, "f": 1}, "seat_2": {"kind": "sit", "x": 70.0, "seat": 212.0,
                                                                                   "f": 1},
             "seat_3": {"kind": "sit", "x": 470.0, "seat": 212.0, "f": 1},
             "stand": {"kind": "stand", "x": -620.0, "f": 1, "strap": (-560.0, -300.0)},
             "stand_2": {"kind": "stand", "x": 700.0, "f": -1, "strap": (640.0, -300.0)},
             "aisle": {"kind": "walk", "from": -900.0, "to": -150.0, "f": 1}}

    def __init__(self, spec, size, light="dusk", weather="clear", effects=(), center=None, seed="bus", height=None):
        super().__init__(spec, size, light, weather, effects, center, seed, height)
        self.sweep = Dynamic(self.cam, 0.72, add=True)

    def _wall(self, p: Paint):
        wall = mix(WALLS.get(self.spec["wall"], "#3E4058"), self.L["wall"][1], 0.45)
        p.poly(rect(-2000, -1400, 4000, 1700), wall)
        p.poly(rect(-2000, 300, 4000, 600), mix(self.L["floor"], "#2A2830", 0.5))
        x0, y0, x1, y1 = self.WINDOW[:4]
        for x in np.arange(x0, x1, 400):
            p.cut(rr(x + 20, y0, 360, y1 - y0, 14))
        p.poly(rect(-2000, y0 - 90, 4000, 70), mix(wall, "#000000", 0.25))
        for k, x in enumerate(np.arange(x0 + 60, x1, 400)):
            p.poly(rr(x, y0 - 82, 160, 52, 4), hexc(["#4A3A5A", "#3A4A5A", "#5A4A3A"][k % 3]), 0.8)
        p.poly(rect(-2000, -520, 4000, 150), mix(wall, "#000000", 0.4))
        p.poly(rect(-2000, -390, 4000, 10), hexc("#FFF0D8") if self.inside_lit else hexc("#4A4250"), 0.9)

    def _back(self, p: Paint):
        seat = hexc("#2E3A5A")
        for x in (-330, 70, 470):
            p.poly(rr(x - 92, 40, 40, 220, 14), seat)
            p.poly(rr(x - 92, 200, 190, 30, 10), seat)
            p.poly(rect(x - 70, 230, 12, 70), hexc("#1A1622"))
        for x in (-760, -130, 270, 870):
            p.poly(rect(x - 6, -520, 12, 820), hexc("#B8A050"), 0.85)
        p.poly(rect(-2000, -312, 4000, 9), hexc("#8A8698"))
        for x in np.arange(-940, 1000, 160):
            p.poly(tube([(x, -306), (x, -270)], 3.0), hexc("#2A2632"))
            p.poly(tube(ell(x, -258, 13, 15, 20)[list(range(20)) + [0]], 3.5, k=2), hexc("#2A2632"))

    def _glows(self, p: Paint):
        if self.inside_lit:
            p.glow(0, -385, 1400, 40, PAL["lamp"], 0.25)


class TrainInside(Vehicle):
    """Inside a train: big windows, a luggage rack above, seats facing each other over little tables, the land rushing
    past (telegraph poles flashing by)."""

    WINDOW = (-1100.0, -280.0, 1100.0, 70.0, 1, 1)
    CENTER = (0.0, 0.0)
    FLOOR = 300.0
    VIEW = "fields"
    SPEED = 1.8
    MARKS = {"seat": {"kind": "sit", "x": -330.0, "seat": 212.0, "f": 1, "reach": (-190.0, 150.0)},
             "seat_2": {"kind": "sit", "x": 50.0, "seat": 212.0, "f": -1, "reach": (-90.0, 150.0)},
             "seat_3": {"kind": "sit", "x": 470.0, "seat": 212.0, "f": 1, "reach": (610.0, 150.0)},
             "aisle": {"kind": "walk", "from": -900.0, "to": -560.0, "f": 1}}

    def __init__(self, spec, size, light="day", weather="clear", effects=(), center=None, seed="train", height=None):
        super().__init__(spec, size, light, weather, effects, center, seed, height)
        self.sweep = Dynamic(self.cam, 0.72, add=True)

    def _wall(self, p: Paint):
        wall = mix(WALLS.get(self.spec["wall"], "#4A4650"), self.L["wall"][1], 0.4)
        p.poly(rect(-2000, -1400, 4000, 1700), wall)
        p.poly(rect(-2000, 300, 4000, 600), mix(self.L["floor"], "#2C2830", 0.5))
        x0, y0, x1, y1 = self.WINDOW[:4]
        for x in np.arange(x0, x1, 560):
            p.cut(rr(x + 30, y0, 500, y1 - y0, 22))
        p.poly(rect(-2000, y0 - 130, 4000, 12), hexc("#5A5666"))                    # the luggage rack
        for x in np.arange(-1000, 1000, 40):
            p.poly(rect(x, y0 - 120, 3, 40), hexc("#4A4656"))
        for x, w, h in ((-700, 160, 60), (-180, 120, 46), (300, 180, 70)):
            p.poly(rr(x, y0 - 130 - h, w, h, 6), hexc("#3A3446"))
        p.poly(rect(-2000, -560, 4000, 140), mix(wall, "#000000", 0.4))
        p.poly(rect(-2000, -432, 4000, 8), hexc("#FFF0D8") if self.inside_lit else hexc("#4A4250"), 0.9)

    def _back(self, p: Paint):
        seat = hexc("#3A2E4A")
        for x, f in ((-330, 1), (50, -1), (470, 1)):
            bx = x - f * 92
            p.poly(rr(min(bx, bx + f * 40), -20, 40, 280, 16), seat)
            p.poly(rr(min(x - f * 92, x + f * 98), 200, 190, 30, 10), seat)
        for tx in (-120, 680):
            p.poly(rect(tx - 90, 140, 180, 10), hexc("#2E2130"))
            p.poly(rect(tx - 90, 139, 180, 3), hexc("#7A6068"), 0.8)
            p.poly(rect(tx - 6, 150, 12, 150), hexc("#1E1622"))

    def _glows(self, p: Paint):
        if self.inside_lit:
            p.glow(0, -425, 1400, 40, PAL["lamp"], 0.22)


# --- making one -----------------------------------------------------------------------------------------------------------
def build(spec: dict, size, light: str = "dusk", weather: str = "clear", effects=(), center=None, seed: str = "place",
          height=None):
    """A place from its description, drawn for this frame size, light and weather (tools/silhouette_render.py keeps the
    most recent one per process). center and height frame it closer: the world point in the middle of the frame and how
    many world units of height the frame shows (a room shows 900; a close-up of a table 350)."""
    kind = str((spec or {}).get("kind") or "room").lower()
    light = light if light in LIGHTS else "dusk"
    if kind == "car":
        return CarInside(spec, size, light, weather, effects, center, seed, height)
    if kind == "bus":
        return BusInside(spec, size, light, weather, effects, center, seed, height)
    if kind == "train":
        return TrainInside(spec, size, light, weather, effects, center, seed, height)
    if kind in OUTDOORS:
        return ComposedOutdoor(spec, size, light, weather, effects, center, seed, height)
    return ComposedRoom(spec, size, light, weather, effects, center, seed, height)
