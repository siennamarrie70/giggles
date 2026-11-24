"""
New visuals for the code-drawn library, made from recipes (2026-11-24: Agent 3, Visuals, agents/visuals.py). When a
script needs a thing or a bubble picture the library doesn't have, Gemini designs it as a recipe: data, never code.
This module checks the recipe, draws it, and adds it to the library, for the story's film and every story after it.

Silhouettes only (your rule, 2026-11-24): a recipe can make only what the library's own things are made of.
  - A thing: solid filled shapes (box, shape, bar, circle, oval) in the silhouette tones the library's things are
    drawn in (wood, dark, ink, metal, steel, the six dark fabrics). Each tone's lit partner appears only as the thin
    lit edge along a box's top; paper or a screen's glow only for a small part. It stands on a table or shelf (small),
    on the floor by the wall (floor_small) or hangs on the wall (wall): never furniture, which would move where people
    stand.
  - A bubble picture: a solid dark pictogram in the bubbles' ink on the bubble's cream, with at most one small accent
    colour of the library's pictures.
There's no text, outline or gradient to ask for. The drawn visual must read as a silhouette too (silhouette_ok), and
agents/visuals.py has Gemini compare it with the library's own before it's used.

  validate(recipe)               the recipe made safe (numbers checked and rounded, its name a library word) or
                                 ValueError saying what's wrong
  register(recipes)              visuals into the library in this process: a thing's PROPS entry and d_<name>, a
                                 picture's ICONS and PICTURES entries (a code-drawn one of the same name is never replaced)
  for_story(story)               the story's own copies (story["visuals"]) registered: before planning or drawing its shots
  preview(recipe)                (RGB float image, mask): the visual alone on a plain card
  silhouette_ok(rgb, mask, kind) (ok, why): the drawn visual reads as a silhouette
  examples(kind, layer)          three of the library's own silhouettes of the same kind, drawn alike (for the comparison)
"""

import math
import re

import cv2
import numpy as np

import silhouette as S
import silhouette_icons as I
import silhouette_props as PR
import silhouette_words as W
from silhouette import ell, rect, rr, tube

MOST_SHAPES, MOST_POINTS = 24, 24
LAYERS = {"small": "small", "floor_small": "small", "wall": "wall"}       # a new thing's layer: its group in PROPS
SIZES = {"small": (12.0, 160.0, 6.0, 130.0), "floor_small": (20.0, 220.0, 10.0, 200.0),   # (width, height: least, most)
         "wall": (30.0, 260.0, 20.0, 240.0)}
HANG = (220.0, 640.0)    # a wall thing's bottom above the floor (the library's clock: 560; photos: 500)
THING_TONES = {"wood": (PR.WOOD, PR.WOOD_LIT), "dark": (PR.DARK, PR.DARK_LIT), "ink": (PR.INK, PR.DARK_LIT),
               "metal": (PR.METAL, PR.METAL_LIT), "steel": (PR.STEEL, PR.STEEL_LIT),
               **{f"fabric{i + 1}": (c, PR.DARK_LIT) for i, c in enumerate(PR.FABRICS)}}   # (fill, its lit edge)
THING_ACCENTS = {"paper": PR.PAPER, "glow": "#9FC8FF"}                   # a small part only (a page, a screen's light)
PICTURE_ACCENTS = {"red": I.RED, "pink": I.HEART, "gold": I.GOLD, "green": I.GREEN, "blue": I.BLUE, "grey": I.GREY,
                   "brown": I.BROWN, "teal": I.TEAL}
SHAPES = ("box", "shape", "bar", "circle", "oval")
DARK_LUM, LIGHT_LUM = 0.36, 0.50     # a silhouette tone is darker than the first; a lit edge or an accent, lighter
CARD = "#3A3242"                     # the plain card a thing is drawn on alone (a dim wall)
MADE: dict = {}                      # (kind, name): the recipe registered in this process


def name_of(words) -> str:
    """A library word for a visual: a few plain words, lower case, joined by _ ("reading_glasses")."""
    return re.sub(r"[^a-z0-9]+", "_", str(words or "").lower()).strip("_")[:28].strip("_")


def _num(v, lo: float, hi: float, what: str) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: not a number") from None
    if not math.isfinite(v):
        raise ValueError(f"{what}: not a number")
    if v < lo - 1e-6 or v > hi + 1e-6:
        raise ValueError(f"{what}: {v:g} is outside {lo:g} to {hi:g}")
    return round(min(max(v, lo), hi), 3)


def _points(pts, xr: float, y0: float, y1: float, least: int, what: str) -> list:
    if not isinstance(pts, list) or not least <= len(pts) <= MOST_POINTS:
        raise ValueError(f"{what}: {least} to {MOST_POINTS} points")
    out = []
    for q in pts:
        x, y = (q.get("x"), q.get("y")) if isinstance(q, dict) else (q if isinstance(q, (list, tuple)) and len(q) == 2
                                                                     else (None, None))
        out.append([_num(x, -xr, xr, f"{what}: a point's x"), _num(y, y0, y1, f"{what}: a point's y")])
    return out


def validate(recipe: dict) -> dict:
    """The recipe, checked: only silhouette shapes and tones, every shape inside the visual's size. Raises ValueError
    with what's wrong (Gemini is told, for its redesign)."""
    if not isinstance(recipe, dict):
        raise ValueError("a recipe is an object")
    kind = recipe.get("kind")
    if kind not in ("thing", "picture"):
        raise ValueError("kind: thing or picture")
    name = name_of(recipe.get("name"))
    if not name or not name[0].isalpha():
        raise ValueError("name: one to three plain words")
    says = " ".join(str(recipe.get("says") or "").split())[:90]
    if not says or re.search(r"https?:|www\.|[<>{}\\]", says):
        raise ValueError("says: a few plain words saying what it is")
    shapes = recipe.get("shapes")
    if not isinstance(shapes, list) or not 1 <= len(shapes) <= MOST_SHAPES:
        raise ValueError(f"shapes: 1 to {MOST_SHAPES}")
    out = {"kind": kind, "name": name, "says": says}
    if kind == "thing":
        layer = recipe.get("layer")
        if layer not in LAYERS:
            raise ValueError("layer: small (on a table or shelf), floor_small (on the floor by the wall) or wall")
        w0, w1, h0, h1 = SIZES[layer]
        out.update(layer=layer, width=_num(recipe.get("width"), w0, w1, "width"),
                   height=_num(recipe.get("height"), h0, h1, "height"))
        if layer == "wall":
            out["hang"] = _num(recipe.get("hang", 480), *HANG, "hang")
        xr, y0, y1 = out["width"] / 2, 0.0, out["height"]
        tones = set(THING_TONES) | set(THING_ACCENTS)
    else:
        accent = recipe.get("accent") or "none"
        if accent != "none" and accent not in PICTURE_ACCENTS:
            raise ValueError(f"accent: none or one of {', '.join(PICTURE_ACCENTS)}")
        out["accent"] = accent
        xr, y0, y1 = 1.0, -1.0, 1.0
        tones = {"ink", "accent"} if accent != "none" else {"ink"}
    clean = []
    for k, s in enumerate(shapes):
        what = f"shape {k + 1}"
        if not isinstance(s, dict) or s.get("shape") not in SHAPES:
            raise ValueError(f"{what}: one of {', '.join(SHAPES)}")
        if s.get("tone") not in tones:
            raise ValueError(f"{what}: its tone is one of {', '.join(sorted(tones))}")
        c = {"shape": s["shape"], "tone": s["tone"]}
        if s["shape"] == "box":
            c.update(x0=_num(s.get("x0"), -xr, xr, f"{what}: x0"), x1=_num(s.get("x1"), -xr, xr, f"{what}: x1"),
                     y0=_num(s.get("y0"), y0, y1, f"{what}: y0"), y1=_num(s.get("y1"), y0, y1, f"{what}: y1"))
            if c["x1"] - c["x0"] <= 0 or c["y1"] - c["y0"] <= 0:
                raise ValueError(f"{what}: x1 above x0 and y1 above y0")
            c["round"] = _num(s.get("round") or 0.0, 0.0, min(c["x1"] - c["x0"], c["y1"] - c["y0"]) / 2, f"{what}: round")
            c["lit"] = bool(s.get("lit")) and kind == "thing" and s["tone"] in THING_TONES
        elif s["shape"] in ("shape", "bar"):
            c["points"] = _points(s.get("points"), xr, y0, y1, 3 if s["shape"] == "shape" else 2, what)
            if s["shape"] == "bar":
                most = min(xr, (y1 - y0) / 2) if kind == "thing" else 0.45
                c["width"] = _num(s.get("width"), 0.06 if kind == "picture" else 2.0, most, f"{what}: width")
        else:
            c.update(x=_num(s.get("x"), -xr, xr, f"{what}: x"), y=_num(s.get("y"), y0, y1, f"{what}: y"))
            if s["shape"] == "circle":
                c["r"] = _num(s.get("r"), 0.02 if kind == "picture" else 1.0, xr, f"{what}: r")
                rx = ry = c["r"]
            else:
                c["rx"] = _num(s.get("rx"), 0.02 if kind == "picture" else 1.0, xr, f"{what}: rx")
                c["ry"] = _num(s.get("ry"), 0.02 if kind == "picture" else 1.0, (y1 - y0) / 2, f"{what}: ry")
                rx, ry = c["rx"], c["ry"]
            slack = 0.02 * (2 * xr)
            if c["x"] - rx < -xr - slack or c["x"] + rx > xr + slack or c["y"] - ry < y0 - slack or c["y"] + ry > y1 + slack:
                raise ValueError(f"{what}: it goes outside the visual's size")
        clean.append(c)
    out["shapes"] = clean
    return out


# --- drawing ---------------------------------------------------------------------------------------------------------------
def _thing_tone(tone):
    return THING_TONES[tone][0] if tone in THING_TONES else THING_ACCENTS[tone]


def thing_drawer(rec: dict):
    """d_<name> for silhouette_props.Thing: draws at (x, b) facing the place's way (c: its silhouette_props.Ctx)."""
    shapes, hang = rec["shapes"], rec.get("hang", 0.0) if rec["layer"] == "wall" else 0.0

    def draw(p, x, b, c):
        base = b - hang
        for s in shapes:
            col = _thing_tone(s["tone"])
            if s["shape"] == "box":
                edge = THING_TONES[s["tone"]][1] if s.get("lit") else None
                PR.B(p, c, x, s["x0"], s["x1"], base - s["y1"], base - s["y0"], col, edge=edge, r=s.get("round") or 0.0)
            elif s["shape"] == "shape":
                PR.P(p, c, x, [(px, base - py) for px, py in s["points"]], col)
            elif s["shape"] == "bar":
                PR.Tb(p, c, x, [(px, base - py) for px, py in s["points"]], s["width"], col)
            elif s["shape"] == "circle":
                PR.Ci(p, c, x, s["x"], base - s["y"], s["r"], col)
            else:
                PR.El(p, c, x, s["x"], base - s["y"], s["rx"], s["ry"], col)
    return draw


def picture_drawer(rec: dict):
    """A bubble picture for silhouette_icons.ICONS: centred at (x, y), s from its middle to its top (u right, y up)."""
    shapes, accent = rec["shapes"], PICTURE_ACCENTS.get(rec.get("accent"))

    def draw(p, x, y, s, on, t):
        ink = I._ink(on)
        for sh in shapes:
            col = ink if sh["tone"] == "ink" else accent
            if sh["shape"] == "box":
                x0, y0, w, h = x + sh["x0"] * s, y - sh["y1"] * s, (sh["x1"] - sh["x0"]) * s, (sh["y1"] - sh["y0"]) * s
                p.poly(rr(x0, y0, w, h, sh["round"] * s) if sh.get("round") else rect(x0, y0, w, h), col)
            elif sh["shape"] == "shape":
                p.poly(np.array([(x + u * s, y - v * s) for u, v in sh["points"]], np.float64), col)
            elif sh["shape"] == "bar":
                p.poly(tube([(x + u * s, y - v * s) for u, v in sh["points"]], sh["width"] * s), col)
            elif sh["shape"] == "circle":
                p.circle(x + sh["x"] * s, y - sh["y"] * s, sh["r"] * s, col)
            else:
                p.poly(ell(x + sh["x"] * s, y - sh["y"] * s, sh["rx"] * s, sh["ry"] * s, 40), col)
    return draw


def register(recipes) -> list[str]:
    """The visuals into the library in this process (idempotent): a thing's PROPS entry (and HANG for a wall thing) and
    its d_<name>; a picture's ICONS and PICTURES entries. A broken recipe is skipped; a code-drawn visual of the same
    name is never replaced. Returns the names registered."""
    done = []
    for rec in recipes or []:
        try:
            rec = validate(rec)
        except (ValueError, TypeError):
            continue
        name, key = rec["name"], (rec["kind"], rec["name"])
        if rec["kind"] == "thing":
            if name in W.PROPS and key not in MADE:
                continue
            W.PROPS[name] = (LAYERS[rec["layer"]], rec["says"], rec["width"], rec["layer"], "both", False, None)
            if rec["layer"] == "wall":
                W.HANG[name] = rec["hang"]
            setattr(PR, "d_" + name, thing_drawer(rec))
        else:
            if name in I.ICONS and key not in MADE:
                continue
            I.ICONS[name] = (picture_drawer(rec), rec["says"])
            W.PICTURES[name] = rec["says"]
        MADE[key] = rec
        done.append(name)
    return done


def forget(names) -> None:
    """Made visuals out of the library in this process (removed in the Studio): no later storyboard picks them. A story
    made with one still draws it from its own copy (for_story registers it again)."""
    for name in names or []:
        for kind in ("thing", "picture"):
            if MADE.pop((kind, name), None) is None:
                continue
            if kind == "thing":
                W.PROPS.pop(name, None)
                W.HANG.pop(name, None)
                if hasattr(PR, "d_" + name):
                    delattr(PR, "d_" + name)
            else:
                I.ICONS.pop(name, None)
                W.PICTURES.pop(name, None)


def for_story(story: dict | None) -> list[str]:
    """The story's own copies of the visuals made for it (story["visuals"]): registered before its shots are planned
    or drawn, so its film always draws them as they were when it was made."""
    return register((story or {}).get("visuals") or [])


# --- seeing one alone ------------------------------------------------------------------------------------------------------
def _layer(w: int, h: int) -> tuple:
    lay = np.zeros((h, w, 4), np.float32)
    return lay, S.Paint(lay, S.View(0, 0, 1.0, 0, 0))


def _flat(lay, bg) -> np.ndarray:
    return lay[..., :3] + np.asarray(S.hexc(bg) if isinstance(bg, str) else bg, np.float32) * (1 - lay[..., 3:4])


def preview(recipe: dict) -> tuple[np.ndarray, np.ndarray]:
    """(RGB float image, mask): a thing drawn alone at its size on a dim card (its base 30 px above the card's foot),
    a picture on a bubble's cream (200 px)."""
    rec = validate(recipe)
    if rec["kind"] == "thing":
        w, h = int(max(160, rec["width"] + 60)), int(max(140, rec["height"] + 60))
        lay, p = _layer(w, h)
        thing_drawer(rec)(p, w / 2, h - 30 + (rec.get("hang", 0.0) if rec["layer"] == "wall" else 0.0),
                          PR.Ctx("dusk", 1, "clear", "preview"))
        return _flat(lay, CARD), lay[..., 3] > 0.5
    lay, p = _layer(200, 200)
    picture_drawer(rec)(p, 100.0, 100.0, 80.0, "cream", 0.0)
    return _flat(lay, I.CREAM), lay[..., 3] > 0.5


def library_preview(kind: str, name: str) -> tuple[np.ndarray, np.ndarray] | None:
    """One of the library's own visuals drawn alone like preview()."""
    if kind == "thing":
        if name not in W.PROPS:
            return None
        group, about, width, layer, where, tall, surface = W.PROPS[name]
        w, h = int(max(160, width + 60)), 300 if layer != "wall" else 360
        lay, p = _layer(w, h)
        PR.Thing(name, w / 2, h - 30 + (W.HANG.get(name, 0) if layer == "wall" else 0), PR.Ctx("dusk", 1)).draw(p)
        ys, xs = np.nonzero(lay[..., 3] > 0.02)
        if not len(ys):
            return None
        lay = lay[max(0, ys.min() - 20):ys.max() + 20, max(0, xs.min() - 20):xs.max() + 20]
        return _flat(lay, CARD), lay[..., 3] > 0.5
    if name not in I.ICONS:
        return None
    lay, p = _layer(200, 200)
    I.draw(p, name, 100.0, 100.0, 80.0, "cream", 0.0)
    return _flat(lay, I.CREAM), lay[..., 3] > 0.5


def silhouette_ok(rgb: np.ndarray, mask: np.ndarray, kind: str) -> tuple[bool, str]:
    """Whether a drawn visual reads as a silhouette: mostly solid dark fill (a thing: the silhouette tones; a picture:
    the bubbles' ink), one filled shape rather than a line drawing, light parts (lit edges, accents) a small share.
    (ok, why not: for the redesign)."""
    n = int(mask.sum())
    if n < 60:
        return False, "it's barely there: draw it bigger and solid"
    lum = rgb[mask] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    dark, light = float((lum < DARK_LUM).mean()), float((lum > LIGHT_LUM).mean())
    m8 = mask.astype(np.uint8)
    hull = cv2.convexHull(cv2.findNonZero(m8))
    solid = n / max(1.0, float(cv2.contourArea(hull)))
    ys, xs = np.nonzero(m8)
    k = max(5, int(round(0.06 * max(np.ptp(xs) + 1, np.ptp(ys) + 1)))) | 1   # (shrunk a little: a solid shape keeps
    core = int(cv2.erode(m8, np.ones((k, k), np.uint8)).sum()) / n          # its middle, a line drawing vanishes)
    least_dark, most_light = (0.75, 0.18) if kind == "thing" else (0.55, 0.40)
    if dark < least_dark:
        return False, (f"only {dark:.0%} of it is dark: a silhouette is mostly its dark tones "
                       f"({'wood, dark, ink, metal, steel, the fabrics' if kind == 'thing' else 'the ink'})")
    if light > most_light:
        return False, f"{light:.0%} of it is light: lit edges and accents only for a small part"
    if solid < 0.30 or core < 0.12:
        return False, "it reads as a line drawing: make it solid filled shapes that touch"
    return True, ""


EXAMPLES = {"small": ("mug", "books", "bottle", "phone", "plate", "candles"),
            "floor_small": ("bag", "boxes", "plant", "bin", "shoes", "guitar"),
            "wall": ("clock", "shelf", "photos", "poster", "mirror", "calendar"),
            "picture": ("phone", "money", "broken_heart", "clock", "trophy", "dumbbell")}


def examples(kind: str, layer: str = "small", n: int = 3) -> list[tuple[str, np.ndarray]]:
    """Up to n of the library's own silhouettes of the same kind, drawn alone (for Gemini's comparison): the usual
    ones first, then any of that layer that reads as a silhouette."""
    key = "picture" if kind == "picture" else layer
    if kind == "picture":
        names = [x for x in EXAMPLES["picture"] if x in I.ICONS] + [x for x in I.ICONS if ("picture", x) not in MADE]
    else:
        names = [x for x in EXAMPLES.get(key, ()) if x in W.PROPS] + \
                [x for x, v in W.PROPS.items() if v[3] == layer and ("thing", x) not in MADE]
    out, seen = [], set()
    for name in names:
        if name in seen or len(out) >= n:
            continue
        seen.add(name)
        got = library_preview("picture" if kind == "picture" else "thing", name)
        if got is not None and silhouette_ok(got[0], got[1], kind)[0]:
            out.append((name, got[0]))
    if kind == "picture" and len(out) < 2:   # (the library's pictures are mostly coloured icons: the style to match is
        return examples("thing", "small", n)  # its silhouettes')
    return out
