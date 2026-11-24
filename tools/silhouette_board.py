"""
The storyboard's shots drawn (Agent 3's design: agents/storyboard.py) in the owner's look (prompts/look_silhouette.txt.enc).
A story's own places are built in code from their descriptions (tools/silhouette_scene.py); him (always the same man) and
the people around him (each made from the look's parts: silhouette.look_from) do what each shot says
(tools/silhouette_actions.py) on the places' marks; a shot is framed wide (the place), medium (from the knees up), close
(head and shoulders) or on a thing (detail), with the camera's move, the event, the label and the places' effects. A shot
in one of the 12 ready-made sets is drawn by tools/silhouette_render.py as before.

  where(marks, action, at)   the mark an action happens on: a thing's own spot for it (the bed to sleep in, its edge to
                             sit on, the desk's chair), a free spot, the window, the floor, a way in or out
  plan(story, shot, size)    what a shot draws, resolved once: the place built for its framing, the people on their marks
  frame(p, size, t, ...)     the shot's frame t seconds in (tools/silhouette_render.py draws films with it)
  still(story, k)            shot k at its strongest moment: the storyboard's stills, the Reviewer's, the thumbnail's

Usage:
    python tools/silhouette_board.py .tmp/storyboard/1_lust.json --out .tmp/storyboard/1_lust   # every still, a page
"""

import argparse
import html
import json
import math
import sys
from collections import OrderedDict
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import silhouette as S  # noqa: E402
import silhouette_actions as A  # noqa: E402
import silhouette_bubbles as BB  # noqa: E402
import silhouette_icons as I  # noqa: E402
import silhouette_marks as MK  # noqa: E402
import silhouette_words as W  # noqa: E402

FPS = S.FPS
SIZE, TALL, STILL = (1920, 1080), (1080, 1920), (960, 540)
OUTDOORS, VEHICLES = ("street", "houses", "bridge", "nature"), ("car", "bus", "train")
FRAMINGS = ("wide", "medium", "close", "detail")
FRAME_HEIGHT = {"medium": 440.0, "close": 340.0, "detail": 300.0}   # world units a frame shows (a room whole: 900)
HEAD_AT = {"medium": 0.20, "close": 0.10}   # how far above the frame's middle the head is (a share of its height)
MOVES = tuple(W.CAMERA)
EVENTS = {
    "none": "nothing happens: life, breath, a blink",
    "head_turn": "his head turns to the camera and his eyes spring wide (the look's signature moment: once or twice a "
                 "film, at a shock or the realization)",
    "look_up": "he lifts his head and looks up", "look_down": "he lowers his head",
    "eyes_open": "his eyes open (he wakes, he comes to)", "eyes_close": "his eyes close",
    "nod": "a small nod", "shake_head": "a slow shake of the head", "phone_buzz": "a phone buzzes",
    "lamp_off": "the room's lamp goes off",
}
WAYS = {"in": ("walk_in", "walk", "aisle"), "out": ("walk_out", "walk_away", "aisle"),
        "across": ("cross", "run", "aisle")}   # (a room's, outdoors', a bus's or a train's)
SPOT_WORDS = ("spot", "standing", "stand", "middle", "here", "room", "free")
SLEEPING = ("asleep", "asleep_desk")   # the eyes stay shut, whatever the storyboard says
WALKS = ("walking", "running", "carrying_box")
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Oswald[wght].ttf"


def word(v) -> str:
    """A word of the library as code writes it ("Dining table" -> "dining_table")."""
    return "_".join(str(v or "").strip().lower().replace("-", " ").replace("'", "").split())


# --- a place's marks and things (a small build of it: the layout is the same at any size) --------------------------------
_PROBES: OrderedDict = OrderedDict()


def _all_things(obj) -> list:
    out = []
    for attr in ("things", "wall_things", "small_things", "mids", "backs"):
        out += list(getattr(obj, attr, None) or [])
    return out


def probe(spec: dict, seed: str = "place") -> dict:
    """What a place built from `spec` holds: {"kind", "marks", "R", "ground", "things": [{"name", "x", "b", "layer",
    "width"}], "missing", "height", "window"} (kept: the last few)."""
    key = json.dumps([spec, str(seed)], sort_keys=True)
    if key in _PROBES:
        _PROBES.move_to_end(key)
        return _PROBES[key]
    import silhouette_scene as SC

    obj = SC.build(spec, (192, 108), "dusk", "clear", (), seed=str(seed))
    kind = (getattr(obj, "spec", None) or {}).get("kind") or word(spec.get("kind")) or "room"
    info = {"kind": kind, "marks": dict(obj.MARKS), "R": float(obj.R),
            "ground": float(getattr(obj, "FLOOR", None) or getattr(obj, "GROUND", None) or 300.0),
            "things": [{"name": t.name, "x": float(t.x), "b": float(t.b), "layer": t.layer, "width": float(t.width)}
                       for t in _all_things(obj)],
            "missing": list(getattr(obj, "missing", []) or []), "height": float(obj.HEIGHT),
            "center": tuple(float(v) for v in obj.CENTER), "window": bool(getattr(obj, "WINDOW", None)),
            "tall_ratio": float(getattr(obj, "TALL_WIDTH", 720.0)) / float(obj.HEIGHT),
            "span": tuple(float(v) for v in getattr(obj, "SPAN", (-1400.0, 1400.0)))}
    _PROBES[key] = info
    while len(_PROBES) > 48:
        _PROBES.popitem(last=False)
    return info


# --- where an action happens ------------------------------------------------------------------------------------------------
def fit(action: str, name: str, m) -> int:
    """How a mark suits an action: 2 made for it (the stove to cook at, a bed to sleep in), 1 it can be done there, 0 not."""
    if not isinstance(m, dict):   # (a crowd's walkers)
        return 0
    kind, use, reach = m.get("kind", "stand"), m.get("use") or [], bool(m.get("reach"))
    if action in use:
        return 2
    need = W.ACTIONS.get(action, ("", "any"))[1]
    own = bool(m.get("thing"))           # (a thing's own mark, not a free spot)
    if need == "stand":
        return int(kind in ("stand", "kneel"))
    if need == "fix":
        return 1 if kind == "kneel" or (kind == "stand" and not reach) else 0
    if need == "walk":
        return int(kind == "walk")
    if need == "run":
        return 2 if kind == "run" else int(kind == "walk")
    if need == "sit":
        return int(kind in ("sit", "drive"))
    if need == "desk":
        return int(kind == "sit" and reach)
    if need == "table":
        return int(reach and (kind == "sit" or (kind == "stand" and action != "eating")))
    if need == "bed":
        return int(kind == "lie")
    if need == "floor":
        return 2 if kind == "floor" else int(kind == "stand" and not own)
    if need == "window":
        return 2 if name == "window" else 0
    if need == "pushup":
        return 2 if kind == "pushup" else int(kind == "stand" and not own)
    if need == "treadmill":
        return 2 if kind == "treadmill" else 0
    if need == "drive":
        return 2 if kind == "drive" else 0
    if need == "pair":
        return 2 if kind == "pair" else int(kind == "stand" and not own)
    if need == "podium":
        return 1 if kind == "stand" and m.get("ground") is not None else 0   # (on a stage)
    if need == "mirror":
        return 2 if "mirror" in use else 0
    if need == "bench":
        return 2 if kind == "bench" else 0
    if need == "bar":
        return 2 if kind == "bar" else 0
    if need in ("door", "stove", "bag", "screen"):
        return 0
    return int(kind in ("stand", "sit", "walk", "drive", "kneel"))   # any: standing, sitting, walking, at the wheel


def _named(marks: dict, at: str) -> list[str]:
    """The marks `at` names: a thing's own (all of them: "bed" is the bed to lie in and its edge to sit on), a way in or
    out, the free floor, the floor, the window, or one mark by its name (with its thing's others: "table" and
    "table_2")."""
    if not at:
        return []
    own = [n for n, m in marks.items() if isinstance(m, dict) and m.get("thing") == at]
    if own:
        return own
    if at in WAYS:
        return [n for n in WAYS[at] if n in marks][:1]
    if at in SPOT_WORDS:   # (the most central free floor first)
        free = sorted((n for n in marks if n.startswith("spot") and isinstance(marks[n], dict)),
                      key=lambda n: abs(marks[n].get("x", 0.0)))
        return free + [n for n in ("stand", "stand_2") if n in marks]
    if at == "floor":
        return [n for n in ("floor",) if n in marks] + [n for n in marks if n.startswith("spot")]
    if at == "window":
        return ["window"] if "window" in marks else []
    if at in marks:
        thing = marks[at].get("thing") if isinstance(marks[at], dict) else None
        return [at] + [n for n, m in marks.items() if thing and n != at and isinstance(m, dict) and m.get("thing") == thing]
    return []


def where(marks: dict, action: str, at: str, taken=()) -> tuple[str | None, str]:
    """The mark `action` happens on when the storyboard says `at`: (its name, why it's another than asked, or ""). None
    when the place has nowhere for it."""
    at = word(at)
    asked = _named(marks, at)
    free = [n for n in asked if n not in taken]
    best = sorted(((fit(action, n, marks[n]), -i, n) for i, n in enumerate(free)), reverse=True)
    if best and best[0][0] > 0:
        return best[0][2], ""
    anywhere = sorted(((fit(action, n, m), -i, n) for i, (n, m) in enumerate(marks.items()) if n not in taken),
                      reverse=True)
    if anywhere and anywhere[0][0] > 0:
        name = anywhere[0][2]
        if not at or (isinstance(marks[name], dict) and marks[name].get("thing") == at):   # (the same thing's other place)
            return name, ""
        why = "taken" if asked and not free else ("not done there" if asked else "nothing called that here")
        return name, f"{action} at {name} ({at}: {why})"
    return None, f"nowhere here for {action}"


def _crowded(marks: dict, taken, R: float) -> set:
    """The marks too near one already taken: someone there would stand in the other's head (a screen's spot by a seat)."""
    xs = [marks[n].get("x", 0.0) for n in taken if isinstance(marks.get(n), dict)]
    return {n for n, m in marks.items() if isinstance(m, dict) and n not in taken and m.get("kind") not in ("walk", "run")
            and any(abs(m.get("x", 0.0) - x) < 2.3 * R for x in xs)}


ADAPT = {"sit": "sitting", "drive": "driving", "lie": "lying_awake", "walk": "walking", "run": "running",
         "stand": "standing", "floor": "floor", "kneel": "kneeling", "pushup": "pushups",
         "treadmill": "treadmill", "bench": "bench_press", "bar": "pullups"}   # what someone does on a mark their action
#                                                                                  can't be done on


def fallback(marks: dict, action: str, taken=()) -> str | None:
    """Somewhere to be when the action has nowhere: a free spot to stand, the wheel, a seat, anywhere."""
    for want in ("stand", "drive", "sit", "walk"):
        for n, m in marks.items():
            if n not in taken and isinstance(m, dict) and m.get("kind") == want and (want != "stand" or not m.get("thing")):
                return n
    return next((n for n, m in marks.items() if isinstance(m, dict) and n not in taken), None)


# --- looks --------------------------------------------------------------------------------------------------------------------
BUILDS = {"slim": 0.86, "average": 1.0, "broad": 1.18}
HEIGHTS = {"short": 0.92, "average": 1.0, "tall": 1.06}


def look_spec(person: dict) -> dict:
    """The storyboard's words for someone's look as silhouette.look_from takes them."""
    out = {k: person.get(k) for k in ("cloth", "hair", "hair_color", "jacket_color", "apron_color", "beard_color",
                                      "scarf_color", "backpack_color") if person.get(k)}
    out["extras"] = [e for e in person.get("extras") or [] if e in W.EXTRAS]
    b, h = person.get("build"), person.get("height")
    out["build"] = BUILDS.get(b, b if isinstance(b, (int, float)) else 1.0)
    out["size"] = HEIGHTS.get(h, h if isinstance(h, (int, float)) else 1.0)
    for k in ("child", "young_him"):   # (the library's children: W.ROLES)
        if person.get(k):
            out[k] = True
    return out


_LOOKS: dict = {}


WORKOUTS = ("pushups", "lifting", "boxing", "treadmill", "bench_press", "pullups", "jump_rope")


def _him_look(him: dict, action: str) -> dict | None:
    """His look in a shot (None: his hoodie): the gym's fitted T-shirt at a workout, his suit when the storyboard dresses
    him in it (his new life); fit from his first workout after the realization on (agents/storyboard.py marks it)."""
    outfit = "gym" if action in WORKOUTS else ("suit" if him.get("outfit") == "suit" else "")
    key = "_".join(["him"] + [w for w in (outfit, "fit" if him.get("fit") else "") if w])
    return {"him": key} if key != "him" else None


def _look(spec: dict | None) -> S.Look:
    if not spec:
        return S.LOOKS["him"]
    if "him" in spec:   # (his other looks: fit, the gym's T-shirt, the suit)
        return S.HIM_LOOKS.get(spec["him"], S.LOOKS["him"])
    key = json.dumps(spec, sort_keys=True)
    if key not in _LOOKS:
        _LOOKS[key] = S.look_from(spec)
    return _LOOKS[key]


# --- a shot's plan ------------------------------------------------------------------------------------------------------------
def place_of(story: dict, pid: str) -> dict:
    for p in story.get("places") or []:
        if p["id"] == pid:
            return p
    raise ValueError(f"the storyboard has no place {pid!r}")


def cast_of(story: dict, cid: str) -> dict | None:
    return next((c for c in story.get("cast") or [] if c["id"] == cid), None)


def seconds_of(shot: dict) -> float:
    return float(shot.get("seconds") or 4.0)


def _mark(info: dict, name: str | None) -> dict:
    m = info["marks"].get(name) if name else None
    if isinstance(m, list):
        m = m[0]
    return dict(m) if isinstance(m, dict) else {"kind": "stand", "x": 0.0, "f": 1}


def people(story: dict, shot: dict, info: dict) -> list[dict]:
    """Who's in the shot, in drawing order (the others, then him in front): {"who", "look", "action", "mark" (the mark
    itself), "mark_name", "item", "eyes", "seed", "pair" (his partner in a hug, a handshake, an argument)}."""
    marks, taken, out = info["marks"], set(), []
    seed = int(shot.get("seed") or 7)
    entries = []
    him = shot.get("him") or {}
    if him.get("action") and him["action"] != "none":
        entries.append(("him", him))
    for o in shot.get("others") or []:
        if o.get("who") and o.get("action") and o["action"] != "none" and o["who"] != (him.get("with") or ""):
            entries.append((o["who"], o))
    for k, (who, d) in enumerate(entries):
        action = d["action"] if d["action"] in W.ACTIONS else "standing"
        name = d.get("mark") if d.get("mark") in marks and d.get("mark") not in taken else None
        crowd = taken | _crowded(marks, taken, info["R"])
        if name is not None and name in crowd:   # (too near someone: another place for it, if the room has one)
            other, _ = where(marks, action, d.get("at") or "", crowd)
            name = other or name
        if name is None:
            name, _ = where(marks, action, d.get("at") or "", crowd)
            name = name or where(marks, action, d.get("at") or "", taken)[0]
            name = name or fallback(marks, action, crowd) or fallback(marks, action, taken)
        if name:
            taken.add(name)
        m = marks.get(name) if name else None
        if isinstance(m, dict) and fit(action, name, m) == 0 and m.get("kind") in ADAPT:
            action = ADAPT[m["kind"]]   # (what can really be done there: standing or a hug on a car's seat is sitting)
        cast = None if who == "him" else cast_of(story, who)
        p = {"who": who, "look": _him_look(d, action) if who == "him" else (cast or {}).get("look") or {}, "action": action,
             "mark": _mark(info, name), "mark_name": name, "item": d.get("item") or None,
             "eyes": d.get("eyes") or None, "seed": seed + 31 * k, "pair": None,
             "marks": [m for m in (d.get("marks") or []) if m in MK.MARKS][:2],
             "screen": d.get("screen") if d.get("screen") in I.SCREENS else None}
        if who == "him" and action in W.PAIRS and him.get("with"):
            partner = cast_of(story, him["with"])
            if partner is not None:
                mate = next((o for o in shot.get("others") or [] if o.get("who") == him["with"]), {})
                p["pair"] = {"who": partner["id"], "look": partner.get("look") or {}, "eyes": mate.get("eyes") or None}
        if who == "him" and action in W.PAIRS and p["pair"] is None:
            p["action"] = "standing"
        if who != "him" and action in W.PAIRS:
            p["action"] = "standing"
        out.append(p)
    _clear_walks(out, marks, info["R"])
    return out[1:] + out[:1] if out and out[0]["who"] == "him" else out   # (him last: in front)


def _clear_walks(out: list, marks: dict, R: float) -> None:
    """Someone walking in or out through a person sitting or standing on the way (their heads on top of each other for a
    moment) goes the room's other way instead, when that way is clear."""
    cross = marks.get("cross")
    if not isinstance(cross, dict) or "from" not in cross:
        return
    still = [q["mark"].get("x", 0.0) for q in out if q["mark"].get("kind") not in ("walk", "run")]

    def through(m):
        lo, hi = sorted((m["from"], m["to"]))
        return any(lo - 1.4 * R < x < hi + 1.4 * R for x in still)

    a, b = cross["from"], cross["to"]
    for q in out:
        m = q["mark"]
        if m.get("kind") != "walk" or q.get("mark_name") not in ("walk_in", "walk_out") or not through(m):
            continue
        alt = dict(m)
        if q["mark_name"] == "walk_out":
            alt["to"] = a if m["to"] == b else b
        else:
            alt["from"] = b if m["from"] == a else a
        alt["f"] = 1 if alt["to"] >= alt["from"] else -1
        if not through(alt):
            q["mark"] = alt


def _subject(p: dict) -> dict | None:
    return next((q for q in p["people"] if q["who"] == "him"), p["people"][0] if p["people"] else None)


def _head_at(p: dict, person: dict, t: float) -> tuple[float, float, int, bool, bool]:
    """Where someone's head is at t: (x, y, facing, lying, face hidden)."""
    acts = actors({**p, "people": [person], "event": "none"}, t)
    a = acts[-1]
    pose = a["pose"]
    return pose["head"][0], pose["head"][1], pose["f"], bool(pose.get("lying")), a["eyes"] is None


FACE_EVENTS = ("head_turn", "look_up", "look_down", "eyes_open", "eyes_close", "nod", "shake_head")
POINTED_AT = {"screen": (190.0, 125.0), "whiteboard": (180.0, 120.0)}   # half the size of what a presenter points at
WORKS_AT = ("desk", "table", "fix", "stove")    # the needs whose hands work at a mark's reach (a laptop, a plate, a pan)
KEEP = 0.035   # a share of the visible frame kept clear round what must show


def _view_box(center, height, size, info) -> tuple:
    """The part of a framing's frame the letterbox bars leave, in world units: (x0, y0, x1, y1)."""
    W_, H_ = size
    if H_ > W_:   # upright: the place's tall width fills the frame's width
        ww = height * info.get("tall_ratio", 0.8)
        hw = ww * H_ / W_
    else:
        hw, ww = height, height * W_ / H_
    bar = S.BARS * min(W_, H_) / H_ * hw
    cx, cy = center
    return (cx - ww / 2, cy - hw / 2 + bar, cx + ww / 2, cy + hw / 2 - bar)


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _inside(box, v) -> bool:
    return box[0] >= v[0] - 0.5 and box[2] <= v[2] + 0.5 and box[1] >= v[1] - 0.5 and box[3] <= v[3] + 0.5


def _cut(box, v) -> bool:
    """A box the frame's edge (or a bar) cuts: not whole inside, not wholly out."""
    out = box[2] <= v[0] or box[0] >= v[2] or box[3] <= v[1] or box[1] >= v[3]
    return not out and not _inside(box, v)


def _shift_to(center, height, size, info, boxes, floor=None):
    """The smallest move of the centre that puts every box whole inside the bars, with a margin (and the frame's middle
    never much below the floor): None when they can't all fit at this height."""
    v = _view_box(center, height, size, info)
    mx, my = (v[2] - v[0]) * KEEP, (v[3] - v[1]) * KEEP
    b = _union(boxes)
    if b[2] - b[0] > v[2] - v[0] - 2 * mx or b[3] - b[1] > v[3] - v[1] - 2 * my:
        return None
    dx = min(0.0, b[0] - mx - v[0]) + max(0.0, b[2] + mx - v[2])
    dy = min(0.0, b[1] - my - v[1]) + max(0.0, b[3] + my - v[3])
    c = (center[0] + dx, center[1] + dy)
    if floor is not None and c[1] > floor - height / 2:
        c = (c[0], floor - height / 2)
        if not all(_inside(x, _view_box(c, height, size, info)) for x in boxes):
            return None
    return c


def _figure_xs(pose: dict) -> list[float]:
    """Across, where a person is (world units): their head, their body from the shoulders to the hips, their arms. An
    upright frame, narrow, keeps all of it in (their legs may go under its bottom)."""
    R = pose["R"]
    hx = pose["head"][0]
    xs = [hx - 1.12 * R, hx + 1.12 * R]
    T = pose.get("T")
    if T is not None:
        xs += [float(T(u, v)[0]) for u in (-1.15, 1.15) for v in (0.0, 1.3, 2.55)]
    for arm in (pose.get("near"), pose.get("far")):
        xs += [float(q[0]) for q in arm or ()]
    return xs


def sights(p: dict) -> dict:
    """What a shot's people show over its length: {who: {"head": their head's boxes (with the hair) at moments through
    the shot, "figure": the same boxes as wide as their whole figure (body and arms too), "neck": where their shoulders
    begin then, "things": what their hands work at (the screen pointed at, the
    desk's or the table's top they reach, what they hold), "walks": walking through, "R"}}."""
    s = p["seconds"]
    n = max(3, int(s * 2) + 1)
    times = [min(max(0.0, s - 0.04), s * k / (n - 1)) for k in range(n)]
    walkers = {q["who"] for q in p["people"] if q["mark"].get("kind") in ("walk", "run") or q["action"] in WALKS}
    out: dict = {}
    for t in times:
        for a in actors(p, t):
            pose, who = a["pose"], a.get("who", "?")
            R = pose["R"]
            hx, hy = pose["head"]
            up = 1.50 if a["look"].hair == "bun" else 1.14
            up = max([up] + [MK.REACH.get(m, 0.0) for m in a.get("marks") or ()])   # (and the marks over it)
            d = out.setdefault(who, {"head": [], "figure": [], "neck": [], "things": [], "walks": who in walkers,
                                     "R": R})
            d["head"].append((hx - 1.12 * R, hy - up * R, hx + 1.12 * R, hy + 1.06 * R))
            xs = _figure_xs(pose)
            d["figure"].append((min(xs) - 0.15 * R, hy - up * R, max(xs) + 0.15 * R, hy + 1.06 * R))
            d["neck"].append(float(pose["S"][1]))
            hold = pose.get("hold") or {}
            if hold.get("at") is not None:
                gx, gy = hold["at"]
                d["things"].append((gx - 0.55 * R, gy - 0.55 * R, gx + 0.55 * R, gy + 0.55 * R))
    for q in p["people"]:
        d = out.get(q["who"])
        if d is None:
            continue
        m, R = q["mark"], d["R"]
        if m.get("point") is not None and q["action"] == "presenting":
            px, py = m["point"]
            hw, hh = POINTED_AT.get((q.get("mark_name") or "").split("_")[0], (0.9 * R, 0.9 * R))
            d["things"].append((px - hw, py - hh, px + hw, py + hh))
        need = W.ACTIONS.get(q["action"], ("", ""))[1]
        if m.get("reach") is not None and (need in WORKS_AT or q["action"] in (m.get("use") or [])):
            rx, ry = m["reach"]
            d["things"].append((rx - 0.9 * R, ry - 1.35 * R, rx + 0.9 * R, ry + 0.30 * R))
    return out


def _fit(p: dict, info: dict, size, center, H: float, framing: str, sight: dict, who: str):
    """A medium or a close framing as near the asked one as it can be: his whole head (through the shot) and what his
    hands work at inside the bars; in a medium, whoever is near him whole too; anyone else either whole in the frame or
    wholly out of it (never cut by an edge). Grows the frame when it must; None when even the room's own can't."""
    me = sight.get(who)
    if me is None:
        return None
    part = "figure" if size[1] > size[0] else "head"   # (upright, narrow: whoever it shows whole across, body too)
    need = list(me[part]) + list(me["things"])
    others = {w: d for w, d in sight.items() if w != who and not d["walks"]}
    if framing == "medium":   # (whoever stands or sits by him, in the frame's middle part, shares it whole)
        v0 = _view_box(center, H, size, info)
        mid, span = (v0[0] + v0[2]) / 2, (v0[2] - v0[0]) * 0.42
        for d in others.values():
            hb = _union(d["head"])
            if abs((hb[0] + hb[2]) / 2 - mid) < span:
                need += d[part]
    floor = p["ground"] + 140.0
    top = info["height"] * 0.985
    for grow in (1.0, 1.1, 1.22, 1.36, 1.52, 1.7, 1.9, 2.15):
        h = H * grow
        if h > top:
            break
        c = _shift_to(center, h, size, info, need, floor)
        if c is None:
            continue
        v = _view_box(c, h, size, info)
        cut = [w for w, d in others.items() if any(_cut(b, v) for b in d[part])]
        if not cut:
            return c, h
        both = _shift_to(c, h, size, info, need + [b for w in cut for b in others[w][part]], floor)   # take them in
        if both is not None:
            vb = _view_box(both, h, size, info)
            if not any(_cut(b, vb) for d in others.values() for b in d[part]):
                return both, h
        for w in cut:   # or slide away from them, keeping what must show
            hb = _union(others[w][part])
            gap = (v[2] - v[0]) * 0.012
            dx = (hb[0] - gap - v[2]) if (hb[0] + hb[2]) / 2 > (v[0] + v[2]) / 2 else (hb[2] + gap - v[0])
            c3 = (c[0] + dx, c[1])
            v3 = _view_box(c3, h, size, info)
            if all(_inside(x, v3) for x in need) and not any(_cut(b, v3) for d in others.values() for b in d[part]):
                return c3, h
    return None


def _fit_detail(p: dict, info: dict, size, center, H: float, sight: dict):
    """A thing seen close (its middle kept near where asked): nobody cut at the neck. Each person by it is shown with
    their whole head, or only from the shoulders down (their hands at the thing), or not at all. None when no framing
    near it can."""
    def ok(c, h):
        v = _view_box(c, h, size, info)
        for d in sight.values():
            if d["walks"]:
                continue
            for b, neck in zip(d["head"], d["neck"]):
                if _cut(b, v):
                    return False
                body_in = b[2] > v[0] and b[0] < v[2]   # (the body under the head, in the frame's width)
                if body_in and b[3] <= v[1] and v[1] < neck + 0.30 * d["R"]:
                    return False   # (headless: the shoulders in, the head above the frame)
        return True

    cx, cy = center
    for h in (H, H * 0.82, H * 0.68):
        if ok((cx, cy), h):
            return (cx, cy), h
        v = _view_box((cx, cy), h, size, info)
        lows = [n + 0.32 * d["R"] for d in sight.values() if not d["walks"] for b, n in zip(d["head"], d["neck"])
                if b[2] > v[0] and b[0] < v[2]]
        if lows:   # down until the frame's top is under everyone's shoulders, the thing still near the middle
            dy = max(lows) - v[1]
            if 0 < dy < (v[3] - v[1]) * 0.42 and ok((cx, cy + dy), h):
                return (cx, cy + dy), h
    for h in (H * 1.35, H * 1.6):   # or wider, with their whole heads
        v = _view_box((cx, cy), h, size, info)
        heads = [b for d in sight.values() if not d["walks"] for b in d["head"] if b[2] > v[0] and b[0] < v[2]]
        c = _shift_to((cx, cy), h, size, info, heads + [(cx - 40, cy - 40, cx + 40, cy + 40)]) if heads else (cx, cy)
        if c is not None and ok(c, h):
            return c, h
    return None


def _slide_upright(p: dict, info: dict, size, c, sight: dict, who: str):
    """An upright wide frame (the place's height, narrow) slid along so nobody is cut by its sides (head or body):
    whoever its edge cuts is taken in whole when they fit beside him, else left out."""
    h = info["height"]
    me = (sight.get(who) or {}).get("figure") or []
    others = [d for w, d in sight.items() if w != who and not d["walks"]]
    if me:   # (his own figure first: whole inside when it can be)
        whole = _shift_to(c, h, size, info, me)
        if whole is not None:
            c = (whole[0], c[1])
    for _ in range(3):
        v = _view_box(c, h, size, info)
        cut = [d for d in others if any(_cut(b, v) for b in d["figure"])]
        if not cut:
            return c
        d = cut[0]
        both = _shift_to(c, h, size, info, me + d["figure"])
        if both is not None:
            c = (both[0], c[1])
            continue
        hb = _union(d["figure"])
        gap = (v[2] - v[0]) * 0.012
        dx = (hb[0] - gap - v[2]) if (hb[0] + hb[2]) / 2 > (v[0] + v[2]) / 2 else (hb[2] + gap - v[0])
        moved = (c[0] + dx, c[1])
        if me and not all(_inside(b, _view_box(moved, h, size, info)) for b in me):
            return c
        c = moved
    return c


def _frame_it(p: dict, shot: dict, info: dict, size) -> None:
    """The framing's centre and height (world units): wide is the place's own; medium (from the knees up, with whoever
    is near him), close (head and shoulders) and detail (a thing) are closer. Inside a vehicle medium is its own framing.
    A medium or a close keeps his whole head and what his hands work at inside the bars (a screen he points at, the desk he
    types at) and cuts nobody by its edge; a detail cuts nobody at the neck. One that can't is framed wider."""
    framing = p["framing"]
    upright = size[1] > size[0]
    sight = None
    if framing == "detail":
        name = word(shot.get("close_on"))
        t = next((t for t in info["things"] if t["name"] == name), None)
        if t is None or p["event"] in FACE_EVENTS:   # (a face's moment can't be seen on a thing)
            framing = "close"
        else:
            H = FRAME_HEIGHT["detail"] if t["layer"] != "small" else 260.0
            if t["layer"] == "wall":
                y = t["b"] - W.HANG.get(name, 450)
            elif t["layer"] == "small":
                y = t["b"] - 40.0
            else:
                y = t["b"] - min(140.0, H * 0.25)
            sight = sights(p)
            got = _fit_detail(p, info, size, (t["x"], y), H, sight)
            if got is not None:
                p.update(center=got[0], height=got[1], framing="detail")
                return
            framing = "close"
    subj = _subject(p)
    if framing in ("medium", "close") and subj is not None:
        when = best_moment(p)
        hx, hy, f, lying, hidden = _head_at(p, subj, when)
        if hidden and framing == "close":   # (his face in his hands: a close-up would be a black ball)
            framing = "medium"
        if info["kind"] in VEHICLES and framing == "medium":
            p.update(framing="wide", focus=(hx, hy))
            return
        H = FRAME_HEIGHT[framing] if info["kind"] not in VEHICLES else info["height"] * 0.62
        width = H * (size[0] / size[1])
        heads, near = [(hx, hy)], [subj["who"]]
        if framing == "medium":   # whoever is with him, when they fit in the frame
            for q in p["people"]:
                if q is not subj:
                    x2, y2, *_ = _head_at(p, q, when)
                    if abs(x2 - hx) < width * 0.62:
                        heads.append((x2, y2))
                        near.append(q["who"])
        if lying:
            cx, cy = hx + f * 2.4 * p["R"], hy + 0.05 * H
        elif upright and info["kind"] not in VEHICLES:   # (upright, narrow: whoever it shows in its middle, whole
            sight = sight or sights(p)                   # across; room left before him would cut his back off)
            figs = [b for w in near for b in (sight.get(w) or {}).get("figure") or []]
            fig = _union(figs) if figs else (hx - 1.0, hy, hx + 1.0, hy)
            cx, cy = (fig[0] + fig[2]) / 2, min(y for _, y in heads) + H * HEAD_AT[framing]
        elif len(heads) > 1:
            xs = [x for x, _ in heads]
            cx, cy = (min(xs) + max(xs)) / 2, min(y for _, y in heads) + H * HEAD_AT[framing]
        else:
            cx = hx + f * H * (0.14 if framing == "medium" else 0.08)
            cy = hy + H * HEAD_AT[framing]
        cy = min(cy, p["ground"] + 140.0 - H / 2)    # (never much below the floor)
        if info["kind"] in VEHICLES:
            p.update(center=(cx, cy), height=H, framing=framing, focus=(hx, hy))
            return
        got = _fit(p, info, size, (cx, cy), H, framing, sight or sights(p), subj["who"])
        if got is not None:
            p.update(center=got[0], height=got[1], framing=framing, focus=(hx, hy))
            return
    p["framing"] = "wide"
    p["center"], p["height"] = None, None
    if upright and subj is not None:   # an upright frame: the place's own height, centred on him, sliding to take whoever
        # its edge would cut in whole (or to leave them out)
        hx, hy, f, lying, _ = _head_at(p, subj, best_moment(p))
        c = (hx + (f * 2.4 * p["R"] if lying else 0.0), info["center"][1])
        if info["kind"] not in VEHICLES:
            c = _slide_upright(p, info, size, c, sight or sights(p), subj["who"])
        p.update(center=c, focus=(hx, hy))
        return
    if subj is None or info["kind"] in VEHICLES:
        return
    if info["kind"] in OUTDOORS and subj["mark"].get("kind") in ("walk", "run"):
        return   # (outdoors the camera follows him walking)
    when = best_moment(p)
    xs = []   # where everyone is (a lying person by their middle): a wide room slides along to keep them in it
    for q in p["people"]:
        hx, hy, f, lying, _ = _head_at(p, q, when)
        xs.append(hx + (f * 2.4 * p["R"] if lying else 0.0))
    cx0 = info["center"][0]
    half = info["height"] * size[0] / size[1] / 2 * 0.80
    lo, hi = min(xs), max(xs)
    if lo < cx0 - half or hi > cx0 + half:
        sx = next(x for x, q in zip(xs, p["people"]) if q is subj)
        cx = (lo + hi) / 2 if hi - lo <= 2 * half else sx
        reach = info["height"] * size[0] / size[1] / 2   # (the frame stays inside what's drawn: the walls reach 400 past)
        a, b = info["span"][0] - 380.0, info["span"][1] + 380.0
        cx = max(a + reach, min(b - reach, cx)) if b - a > 2 * reach else cx0
        p["center"] = (cx, info["center"][1])


def frame_problems(p: dict, size, info: dict | None = None) -> list[str]:
    """What a planned shot's frame gets wrong, measured (nothing drawn): a head cut by the frame's edge or a bar, someone
    shown without their head, two heads on top of each other, what his hands work at out of view. [] when none. (Inside
    a vehicle the framing is the vehicle's own: not measured.)"""
    info = info or probe(p["spec"], p["seed"])
    if info["kind"] in VEHICLES or not p["people"]:
        return []
    sight = sights(p)
    center = p["center"] if p["center"] is not None else info["center"]
    h = p["height"] if p["height"] is not None else info["height"]
    v = _view_box(center, h, size, info)
    subject = (_subject(p) or {}).get("who")
    upright = size[1] > size[0] and p["framing"] in ("medium", "close")
    out = []
    for who, d in sight.items():
        if d["walks"]:
            continue
        if any(_cut(b, v) for b in d["head"]):
            out.append(f"{who}'s head is cut by the frame's edge")
        elif upright and any(_cut(b, v) for b in d["figure"]):   # (an upright Short's narrow frame: whole across)
            out.append(f"{who}'s body is cut by the frame's side")
        elif any(b[2] > v[0] and b[0] < v[2] and b[3] <= v[1] and v[1] < n + 0.30 * d["R"]
                 for b, n in zip(d["head"], d["neck"])):
            out.append(f"{who} is shown without their head")
        if who == subject and p["framing"] in ("medium", "close") and not all(_inside(b, v) for b in d["things"]):
            out.append(f"what {who}'s hands work at is out of view")
    names = [w for w, d in sight.items() if not d["walks"]]
    for i, a_ in enumerate(names):
        for b_ in names[i + 1:]:
            for x, y in zip(sight[a_]["head"], sight[b_]["head"]):
                ra, rb = (x[2] - x[0]) / 2, (y[2] - y[0]) / 2
                d = math.hypot((x[0] + x[2]) / 2 - (y[0] + y[2]) / 2, (x[1] + x[3]) / 2 - (y[1] + y[3]) / 2)
                if d < 0.62 * (ra + rb):
                    out.append(f"{a_}'s and {b_}'s heads are on top of each other")
                    break
    return out


def plan(story: dict, shot: dict, size=SIZE) -> dict:
    """What a shot of the storyboard draws, resolved once: its place's description, light, weather and effects, the people
    on their marks, the framing (centre and height), the camera's move, the event and the label."""
    place = place_of(story, shot["place"])
    spec, seed = place["spec"], place.get("seed") or place["id"]
    info = probe(spec, seed)
    seconds = seconds_of(shot)
    event = shot.get("event") if shot.get("event") in EVENTS else "none"
    p = {"composed": True, "spec": spec, "seed": seed, "kind": info["kind"],
         "light": shot.get("light") or place.get("light") or "dusk",
         "weather": shot.get("weather") or place.get("weather") or "clear",
         "effects": [e for e in shot.get("effects") or [] if e in W.EFFECTS and e not in (spec.get("effects") or [])],
         "R": info["R"], "ground": info["ground"], "camera": shot.get("move") if shot.get("move") in MOVES else "hold",
         "event": event, "event_at": float(shot.get("event_at", 0.45)) * seconds, "seconds": seconds,
         "label": (shot.get("label") or "").strip().upper()[:28], "framing": shot.get("framing") or "wide",
         "center": None, "height": None, "focus": None}
    p["people"] = people(story, shot, info)
    p["bubbles"] = [{"who": b.get("who") or "him", "kind": b["kind"], "text": b.get("text") or "",
                     "picture": b.get("picture") if b.get("picture") in I.ICONS else "",
                     "start": float(b.get("start") or 0.0), "end": float(b.get("end") or seconds)}
                    for b in shot.get("bubbles") or [] if b.get("kind") in BB.KINDS]
    _frame_it(p, shot, info, size)
    if p["framing"] != "wide" and frame_problems(p, size, info):   # (a closer framing that still cuts someone: the
        p.update(framing="wide", center=None, height=None, focus=None)   # place's own)
        _frame_it(p, shot, info, size)
    return p


# --- what moves ---------------------------------------------------------------------------------------------------------------
def _blink(t: float, seed: int) -> float:
    """1 open .. 0 shut: a blink every 2.8-4.4 s (silhouette_render's)."""
    r = np.random.default_rng(seed + 7)
    at = float(r.uniform(0.6, 2.2))
    while at < t + 1:
        if at <= t < at + 0.16:
            return 1 - math.sin(math.pi * (t - at) / 0.16)
        at += float(r.uniform(2.8, 4.4))
    return 1.0


def _pose(action, m, t, R, ground, seed, item, seconds):
    if action == "presenting" and "point" not in m:   # (no screen: he points up and ahead)
        m = {**m, "point": (m.get("x", 0.0) + 300.0 * m.get("f", 1), ground - 500.0)}
    return A.pose(action, m, t, R, ground, seed=seed, item=item, seconds=seconds)


def _event(p: dict, pose: dict, e, t: float) -> None:
    """The shot's event on him at t: the head turning to the camera with the eyes springing wide, looking up or down,
    the eyes opening or closing, a nod, a shake of the head."""
    ev, et = p["event"], t - p["event_at"]
    if ev == "eyes_open" and e is not None:
        e.open *= S.smooth(S.window(et, 0.0, 0.7)) if et >= 0 else 0.0
        return
    if ev == "none" or et < 0:
        return
    R = pose["R"]
    hx, hy = pose["head"]
    if ev == "head_turn" and e is not None:
        turn = S.ease_out(S.window(et, 0.0, 0.22), 3)
        wide = S.spring(S.window(et, 0.08, 0.7))
        e.look = (e.look[0] * (1 - turn), e.look[1] * (1 - turn))
        e.open = min(1.0, e.open + (1.0 - e.open) * wide)
        e.size = max(e.size, 1.0 + 0.22 * wide)
        e.tilt *= 1 - wide
        e.smile = False
    elif ev in ("look_up", "look_down"):
        q = S.ease_in_out(S.window(et, 0.0, 0.9))
        up = ev == "look_up"
        pose["head"] = (hx, hy + (-0.10 if up else 0.10) * R * q)
        if e is not None:
            e.look = (e.look[0], e.look[1] + (-0.75 if up else 0.6) * q)
    elif ev == "nod" and et < 1.3:
        pose["head"] = (hx, hy + 0.06 * R * max(0.0, math.sin(math.tau * et / 0.62)) * (1 - et / 1.3))
    elif ev == "shake_head" and et < 1.6:
        pose["head"] = (hx + pose["f"] * 0.10 * R * math.sin(math.tau * et / 0.55) * (1 - et / 1.6), hy)
    elif ev == "eyes_close" and e is not None:
        e.open *= 1 - S.smooth(S.window(et, 0.0, 0.9))


def _dressed(pose: dict, person: dict, t: float) -> dict:
    """A pose with what the shot adds to it: the phone's screen turned to us (what he's looking at), a tremble."""
    hold = pose.get("hold")
    if person.get("screen") and hold and hold.get("kind") in ("phone", "phone_up"):
        pose = {**pose, "hold": {**hold, "screen": person["screen"], "t": t}}
    if "tremble" in (person.get("marks") or ()):
        pose = MK.shake(pose, t)
    return pose


def actors(p: dict, t: float) -> list[dict]:
    """The people at t: {"pose", "look", "eyes", "slot"} (and a mirror's glass), in drawing order."""
    out = []
    R0, gnd = p["R"], p["ground"]
    for person in p["people"]:
        look = _look(person["look"])
        m, seed = person["mark"], person["seed"]
        blink = _blink(t, seed)
        if person.get("pair"):
            mate = person["pair"]
            mlook = _look(mate["look"])
            pm = m if m.get("kind") == "pair" else {"kind": "pair", "x": m.get("x", 0.0),
                                                     "f": 1 if m.get("x", 0.0) <= 0 else -1,
                                                     **({"ground": m["ground"]} if m.get("ground") is not None else {})}
            a, ea, b, eb = A.pair(person["action"], pm, t, R0 * look.size, R0 * mlook.size, gnd, seed)
            out.append({"pose": b, "look": mlook, "slot": "main", "who": mate["who"],
                        "eyes": A.eyes_of(eb, mlook.gap, _blink(t, seed + 3), mate.get("eyes"), f=b["f"])})
            e = A.eyes_of(ea, look.gap, blink, person.get("eyes"), f=a["f"])
            if person["who"] == "him":
                _event(p, a, e, t)
            out.append({"pose": _dressed(a, person, t), "look": look, "eyes": e, "slot": "main", "who": person["who"],
                        "marks": person.get("marks") or []})
            continue
        pose, hint = _pose(person["action"], m, t, R0 * look.size, gnd, seed, person.get("item"), p["seconds"])
        mood = None if person["action"] in SLEEPING else person.get("eyes")
        e = None if pose.get("face_hidden") else A.eyes_of(hint, look.gap, blink, mood, f=pose["f"])
        if person["who"] == "him":
            _event(p, pose, e, t)
        a = {"pose": _dressed(pose, person, t), "look": look, "eyes": e, "slot": m.get("slot", "main"),
             "who": person["who"], "marks": person.get("marks") or []}
        for key in ("glass", "oval"):   # (at a mirror: the place draws the reflection)
            if m.get(key):
                a[key] = m[key]
        out.append(a)
    return out


def camera(p: dict, obj, t: float, acts: list[dict]) -> tuple:
    """The camera (cx, cy, z) at t: the shot's move from its framing, eased; outdoors a wide shot follows him walking."""
    cx0, cy0, z0 = obj.cam.rest
    u = S.ease_out(S.window(t, 0.0, p["seconds"]), 1.6)
    head = p.get("focus")
    if head is None:
        him = next((a for a, q in zip(acts, p["people"]) if q["who"] == "him"), None)
        head = him["pose"]["head"] if him else None
    k = (p.get("height") or obj.HEIGHT) / 900.0
    move, cx, cy, z = p["camera"], cx0, cy0, z0
    if move == "push_in":
        z = z0 * (1 + 0.07 * u)
        if head:
            cx, cy = cx0 + (head[0] - cx0) * 0.35 * u, cy0 + (head[1] - cy0) * 0.25 * u
    elif move == "pull_out":
        z = z0 * (1 + 0.07 * (1 - u))
        if head:
            cx, cy = cx0 + (head[0] - cx0) * 0.35 * (1 - u), cy0 + (head[1] - cy0) * 0.25 * (1 - u)
    elif move in ("pan_left", "pan_right"):
        pan = float(getattr(obj, "PAN", (0.0, 0.0))[0])
        d = (-1 if move == "pan_left" else 1) * (min(140.0, pan * 0.9) if pan else 50.0) * k
        cx, z = cx0 - d / 2 + d * u, z0 * 1.02
    else:
        z = z0 * (1 + 0.012 * u)
    if "shake" in p["effects"]:   # (rage, panic: the camera shaking, a few world units)
        cx += k * (7.0 * math.sin(t * 37.0) + 4.0 * math.sin(t * 23.0 + 1.0))
        cy += k * 5.0 * math.sin(t * 31.0 + 2.0)
    him = next((q for q in p["people"] if q["who"] == "him"), None)
    if p["framing"] == "wide" and p["kind"] in OUTDOORS and him and him["mark"].get("kind") in ("walk", "run") and acts:
        pan = float(getattr(obj, "PAN", (0.0, 0.0))[0])
        m = him["mark"]
        x = acts[-1]["pose"]["H"][0]
        shift = (x - (m.get("from", 0.0) + m.get("to", 0.0)) / 2) * 0.75 / 0.70
        cx = cx0 + max(-pan * 0.95, min(pan * 0.95, shift))
    return (cx, cy, z)


def state(p: dict, obj, t: float, flags: dict | None = None) -> dict:
    """Everything that moves in the shot at t (the place's st): the people, the camera, the label, the lamp, the fades
    (flags as silhouette_render.jobs_for gives them)."""
    flags = flags or {}
    seconds = p["seconds"]
    still = bool(flags.get("still_from") is not None and t >= flags["still_from"])
    tt = min(t, flags["still_from"]) if still else t
    acts = actors(p, tt)
    st = {"cam": camera(p, obj, tt, acts), "tau": flags.get("t0", 0.0) + tt, "still": still, "actors": acts}
    if p["label"] and not flags.get("no_label"):
        q = S.window(tt, 0.4, 0.68) if not flags.get("label_in") else 1.0
        gone = S.window(tt, 4.4, 5.0) if seconds > 6.5 and not flags.get("label_in") else 0.0
        st["label"] = (p["label"], q, gone)
    if p.get("bubbles") and not flags.get("no_bubbles"):
        st["bubbles"] = _bubbles_at(p, obj, tt, acts, st["cam"], _label_box(obj, st.get("label")))
    lamp, et = 1.0, tt - p["event_at"]
    if p["event"] == "lamp_off" and et >= 0:
        lamp = 1 - S.smooth(S.window(et, 0.0, 0.12))
    if flags.get("lights_out_at") is not None and t >= flags["lights_out_at"]:
        lamp = 0.0
    st["lamp"] = lamp
    fade = 1.0
    if flags.get("fade_in"):
        fade *= S.smooth(S.window(t, 0.0, flags["fade_in"]))
    if flags.get("fade_out"):
        fade *= 1 - S.smooth(S.window(t, seconds - flags["fade_out"], seconds))
    if flags.get("lights_out_at") is not None:
        fade *= 1 - 0.85 * S.smooth(S.window(t, flags["lights_out_at"], flags["lights_out_at"] + 0.08))
    st["fade"] = fade
    return st


def _label_box(obj, label) -> tuple | None:
    """Where the shot's label is on the screen while it shows (px): the bubbles keep off it."""
    text, q, *gone = label or ("", 0.0)
    if not text or q <= 0 or (gone and gone[0] >= 1):
        return None
    W, H = obj.size
    px = getattr(obj, "label_px", 54)
    spr = S.label_sprite(text, px)
    y = obj.finish.bar + px * (1.6 if H > W else 1.25)
    return (W / 2 - spr.shape[1] / 2, y - spr.shape[0] / 2, W / 2 + spr.shape[1] / 2, y + spr.shape[0] / 2)


def _bubbles_at(p: dict, obj, t: float, acts: list[dict], cam, label_box=None) -> list[dict]:
    """The shot's bubbles showing at t, each by its speaker's head on screen (tools/silhouette_bubbles.draw places them,
    off every face, and they keep that place beside the head); an earlier one dimmed while a later one is read."""
    layer = obj.people.get("main") if isinstance(getattr(obj, "people", None), dict) else None
    view = obj.cam.view(getattr(layer, "depth", 0.72), *cam)
    heads = {}
    for a in acts:
        heads.setdefault(a.get("who"), a)
    faces = []
    for a in acts:
        hx, hy = view.pt(*a["pose"]["head"])
        r = a["pose"]["R"] * view.z * 1.15
        faces.append((hx - r, hy - r, hx + r, hy + r))
    keep = p.setdefault("_bubble_keep", {})
    showing = [b for b in p["bubbles"] if b["start"] <= t < b["end"]]
    out = []
    for i, b in enumerate(p["bubbles"]):
        if b not in showing:
            continue
        a = heads.get(b["who"]) or heads.get("him")
        if a is None:
            continue
        sx, sy = view.pt(*a["pose"]["head"])
        key = (i, tuple(obj.size))
        item = {"kind": b["kind"], "text": b["text"], "picture": b["picture"], "head": (sx, sy),
                "r": a["pose"]["R"] * view.z, "f": a["pose"]["f"], "age": t - b["start"], "left": b["end"] - t,
                "dim": 1.0 if any(o is not b and o["start"] > b["start"] for o in showing) else 0.0,
                "avoid": faces + ([label_box] if label_box else []), "keep": keep, "key": key}
        if key in keep:
            item["at"] = (sx + keep[key][0], sy + keep[key][1])
        out.append(item)
    return out


def screen_boxes(obj, st: dict) -> list[tuple]:
    """Where each person in the frame is on the screen at a moment (st: state()'s), head and body: [(x0, y0, x1, y1)]
    px (the closing line of an upright frame keeps off them)."""
    layer = obj.people.get("main") if isinstance(getattr(obj, "people", None), dict) else None
    view = obj.cam.view(getattr(layer, "depth", 0.72), *st["cam"])
    out = []
    for a in st.get("actors") or []:
        pose = a["pose"]
        pts = [pose["head"], pose["S"], pose["H"]] + [q for leg in pose.get("legs") or () for q in leg]
        pts += [q for arm in (pose.get("near"), pose.get("far")) for q in arm or ()]
        on = [view.pt(*q) for q in pts]
        hx, hy = view.pt(*pose["head"])
        r = pose["R"] * view.z
        xs, ys = [x for x, _ in on] + [hx - 1.2 * r, hx + 1.2 * r], [y for _, y in on] + [hy - 1.3 * r]
        out.append((min(xs) - 0.3 * r, min(ys), max(xs) + 0.3 * r, max(ys) + 0.2 * r))
    return out


_PLACES: OrderedDict = OrderedDict()


def place_for(p: dict, size):
    """The shot's place built for its frame, light, weather, effects and framing (a process keeps its most recent one)."""
    import silhouette_scene as SC

    key = json.dumps([p["spec"], list(size), p["light"], p["weather"], p["effects"], p["center"], p["height"],
                      p["seed"]], sort_keys=True)
    if key in _PLACES:
        _PLACES.move_to_end(key)
        return _PLACES[key]
    obj = SC.build(p["spec"], tuple(size), p["light"], p["weather"], tuple(p["effects"]), center=p["center"],
                   seed=p["seed"], height=p["height"])
    _PLACES[key] = obj
    while len(_PLACES) > 1:
        _PLACES.popitem(last=False)
    return obj


def frame(p: dict, size, t: float, index: int, flags: dict | None = None) -> np.ndarray:
    """The shot's frame t seconds in (float RGB)."""
    obj = place_for(p, size)
    return obj.frame(index, state(p, obj, t, flags))


def best_moment(p: dict) -> float:
    """The shot's strongest second: just after its event, him arrived (walking in) or setting off (walking out), else a
    little after its middle."""
    s = p["seconds"]
    if p["event"] in ("head_turn", "look_up", "look_down", "eyes_open", "eyes_close"):
        return max(0.0, min(s - 0.2, p["event_at"] + 0.9))
    him = next((q for q in p["people"] if q["who"] == "him"), None)
    if him and him["mark"].get("kind") in ("walk", "run"):
        name = him.get("mark_name") or ""
        if name in ("walk_out", "walk_away"):
            return min(s * 0.3, 1.6)
        if name in ("cross", "run"):
            return s * 0.5
        return s * 0.85
    return s * 0.6


# --- the 12 ready-made sets -----------------------------------------------------------------------------------------------------
OLD_POSE = {  # the storyboard's actions as the sets' poses (silhouette_words.POSES)
    "writing": "typing", "asleep_desk": "slumped", "phone_call": "phone", "lying_floor": "floor", "crying": "head_in_hands",
    "reading": "sitting", "letter": "sitting", "drinking": "sitting", "eating": "sitting", "holding": "standing",
    "waving": "standing", "applauding": "standing", "kneeling": "floor", "mirror": "standing", "cleaning": "standing",
    "wiping": "standing", "cooking": "standing", "lifting": "standing", "boxing": "standing", "treadmill": "running",
    "driving": "sitting", "fixing": "standing", "speaking": "standing", "presenting": "standing", "hugging": "standing",
    "handshake": "standing", "arguing": "standing"}
OLD_NEXT = {"typing": ("sitting", "slumped"), "sitting": ("slumped", "standing"), "slumped": ("sitting", "head_in_hands"),
            "head_in_hands": ("slumped", "sitting"), "phone": ("standing", "sitting"), "lying_awake": ("asleep", "sitting"),
            "asleep": ("lying_awake", "slumped"), "standing": ("at_window", "sitting", "walking"),
            "walking": ("standing",), "running": ("walking", "standing"), "floor": ("sitting", "slumped"),
            "at_window": ("standing",), "pushups": ("standing",), "carrying_box": ("walking", "standing"),
            "at_door": ("standing",)}
OLD_ROLES = (("mother", ("mother", "mom", "mum", "mama")),
             ("woman", ("wife", "girlfriend", "fiancee", "partner", "ex", "woman", "lover", "date", "her")),
             ("boss", ("boss", "manager", "director", "client", "developer", "investor", "employer", "ceo", "supervisor")),
             ("landlord", ("landlord", "landlady", "owner")),
             ("doctor", ("doctor", "nurse", "surgeon", "therapist", "counselor", "counsellor", "psychologist")))
OLD_OTHER_POSE = {"sitting": "sitting", "slumped": "sitting", "walking": "leaving", "asleep": "lying",
                  "lying_awake": "lying", "holding": "offering"}


def _old_role(role: str) -> str:
    words = set(word(role).split("_"))
    return next((name for name, keys in OLD_ROLES if words & set(keys)), "friend")


def old_shot(story: dict, shot: dict) -> dict:
    """A storyboard shot in a ready-made set, as tools/silhouette_render.plan draws it (the set's own people: the cast
    member nearest each by role)."""
    place = place_of(story, shot["place"])
    name = place["set"]
    poses = W.SET_POSES[name]
    him = shot.get("him") or {}
    pose = "none"
    if him.get("action") not in (None, "none"):
        pose = OLD_POSE.get(him["action"], him["action"])
        if pose not in poses:
            pose = next((q for q in OLD_NEXT.get(pose, ()) if q in poses), next(iter(poses)))
    other, other_pose, other_eyes = "none", None, None
    allowed = W.SET_OTHERS.get(name) or {}
    for o in shot.get("others") or []:
        role = _old_role((cast_of(story, o["who"]) or {}).get("role") or o["who"])
        if role in allowed:
            want = OLD_OTHER_POSE.get(o.get("action"), "standing")
            other, other_eyes = role, o.get("eyes") or None
            other_pose = want if want in allowed[role] else next(iter(allowed[role]))
            break
    light = shot.get("light") or place.get("light")
    if light not in W.SETS[name][1]:
        light = W.SETS[name][1][0]
    label = shot.get("label") or ""
    return {"set": name, "light": light, "rain": (shot.get("weather") or place.get("weather")) == "rain", "him": pose,
            "eyes": him.get("eyes") or None, "other": other, "other_pose": other_pose, "other_eyes": other_eyes,
            "event": shot.get("event") if shot.get("event") in W.EVENTS else "none", "camera": shot.get("move") or "hold",
            "label": label, "clock": clock_of(label), "seconds": seconds_of(shot), "seed": shot.get("seed", 7),
            "line": shot.get("line") or "", "enter": shot.get("enter") or "cut"}


def clock_of(label: str) -> str:
    """A label that's a time ("2:00 AM", "23:59") as the desk room's flip clock shows it ("02:00"), else ""."""
    import re

    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*([AaPp])?\.?\s*[Mm]?\.?\s*$", label or "")
    if not m:
        return ""
    h, mm, half = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if half == "p" and h < 12:
        h += 12
    if half == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mm:02d}" if h < 24 and mm < 60 else ""


# --- stills ---------------------------------------------------------------------------------------------------------------------
def _old_still(shot: dict, size, label: bool) -> np.ndarray:
    import silhouette_render as RENDER

    seconds = seconds_of(shot)
    mini = {"shots": [{**shot, "seconds": seconds}]}
    at = RENDER.best_moment(mini, 0, seconds)
    if label and shot.get("label"):   # (a set's label fades after 4 s: a still shows it)
        at = min(at, 3.6)
    return RENDER.moment(mini, 0, at, tuple(size), {"no_label": not label}, seconds)


def still(story: dict, k: int, size=STILL, at: float | None = None, label: bool = True) -> np.ndarray:
    """Shot k at its strongest moment (or `at` seconds in): float RGB."""
    shot = {**story["shots"][k], "seed": story["shots"][k].get("seed", k * 101 + 7)}
    if shot.get("set"):   # (a story from before the storyboard: its shots in the sets)
        return _old_still(shot, size, label)
    if place_of(story, shot["place"]).get("set"):
        return _old_still(old_shot(story, shot), size, label)
    p = plan(story, shot, size)
    t = best_moment(p) if at is None else float(at)
    obj = place_for(p, size)
    return obj.frame(int(t * FPS), state(p, obj, t, {"no_label": not label, "label_in": True}))


def to_image(frame: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8))


def place_still(story: dict, pid: str, size=STILL) -> np.ndarray:
    """A place of the storyboard, empty, in its own light and weather."""
    place = place_of(story, pid)
    if place.get("set"):
        shot = {"set": place["set"], "light": place.get("light") or "dusk", "rain": place.get("weather") == "rain",
                "him": "none", "other": "none", "seconds": 4.0}
        return _old_still(shot, size, False)
    import silhouette_scene as SC

    obj = SC.build(place["spec"], tuple(size), place.get("light") or "dusk", place.get("weather") or "clear", (),
                   seed=place.get("seed") or pid)
    return obj.frame(30, {"cam": obj.cam.rest, "tau": 1.0, "actors": [], "lamp": 1.0, "fade": 1.0})


def cast_still(story: dict, size=STILL) -> np.ndarray:
    """Him and the people around him side by side, each in their own look."""
    import silhouette_scene as SC

    cast = story.get("cast") or []
    room = {"kind": "room", "wall": "grey", "floor": "wood", "window": "none", "lamp": "none", "things": []}
    n = len(cast) + 1
    height = 900.0 if n <= 6 else 900.0 * n / 6
    obj = SC.build(room, tuple(size), "dusk", "clear", (), seed="cast", height=height)
    span = height * 16 / 9 * 0.84
    xs = [-span / 2 + span * (i + 0.5) / n for i in range(n)]
    acts = []
    for i, (x, person) in enumerate(zip(xs, [None] + cast)):
        look = _look(None if person is None else person.get("look") or {})
        f = 1 if i % 2 == 0 else -1
        pose, hint = A.pose("standing", {"kind": "stand", "x": x, "f": f}, 1.0, obj.R * look.size, obj.FLOOR)
        acts.append({"pose": pose, "look": look, "eyes": A.eyes_of(hint, look.gap, 1.0, "open", f=f), "slot": "main"})
    return obj.frame(30, {"cam": obj.cam.rest, "tau": 1.0, "actors": acts, "lamp": 1.0, "fade": 1.0})


def _font(px):
    return ImageFont.truetype(str(FONT), px)


def _caption(im: Image.Image, words: list[str], top: bool = True) -> Image.Image:
    d = ImageDraw.Draw(im)
    px = max(14, im.size[1] // 24)
    y = int(im.size[1] * 0.085) + 4 if top else im.size[1] - int(im.size[1] * 0.085) - px - 6
    for w in words:
        d.text((12, y), w, font=_font(px), fill=(255, 240, 220))
        y += px + 4
    return im


def _cast_labels(im: Image.Image, story: dict) -> Image.Image:
    cast = story.get("cast") or []
    n = len(cast) + 1
    d = ImageDraw.Draw(im)
    px = max(12, im.size[1] // 34)
    for i, person in enumerate([None] + cast):
        x = im.size[0] * (0.08 + 0.84 * (i + 0.5) / n)
        name = "him" if person is None else person["id"]
        w = _font(px).getlength(name)
        d.text((x - w / 2, im.size[1] * 0.80), name, font=_font(px), fill=(255, 240, 220))
    return im


# --- the storyboard's sheet: every shot's still and a page --------------------------------------------------------------------
def _job(args):
    kind, story, key, size, path = args
    import cv2

    cv2.setNumThreads(1)
    if kind == "shot":
        im = to_image(still(story, key, size))
    elif kind == "place":
        place = place_of(story, key)
        im = _caption(to_image(place_still(story, key, size)), [f"{key} · {place.get('light')}"
                                                                + (f" · {place.get('weather')}"
                                                                   if place.get("weather") not in (None, "clear") else "")])
    else:
        im = _cast_labels(to_image(cast_still(story, size)), story)
    im.save(path, "JPEG", quality=86)
    return str(path)


def draw_board(story: dict, folder: Path, size=STILL, workers: int = 0, progress=print) -> dict:
    """Every shot's still, every place empty and the cast side by side, into `folder`: {"shots": [...], "places": {...},
    "cast": path}."""
    import os
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [("shot", story, k, size, folder / f"shot_{k + 1:02d}.jpg") for k in range(len(story["shots"]))]
    jobs += [("place", story, p["id"], size, folder / f"place_{p['id']}.jpg") for p in story.get("places") or []]
    jobs.append(("cast", story, None, size, folder / "cast.jpg"))
    n = workers or max(1, min(6, os.cpu_count() or 2))
    done = 0
    with ProcessPoolExecutor(max_workers=n, mp_context=multiprocessing.get_context("spawn")) as pool:
        for _ in pool.map(_job, jobs):
            done += 1
            if done % 10 == 0 or done == len(jobs):
                progress(f"  {done} of {len(jobs)} pictures drawn")
    return {"shots": [str(j[4]) for j in jobs if j[0] == "shot"],
            "places": {j[2]: str(j[4]) for j in jobs if j[0] == "place"}, "cast": str(folder / "cast.jpg")}


STAGE_NAMES = {"hook": "The hook", "incident": "The major incident", "collapse": "The collapse",
               "rock_bottom": "Rock bottom", "transformation": "The transformation", "payoff": "The dream life"}


def _e(v) -> str:
    return html.escape(str(v or ""))


def _place_words(place: dict) -> str:
    if place.get("set"):
        return f"the ready-made set “{place['set']}”"
    s = place["spec"]
    kind = s["kind"] if s["kind"] != "nature" else s.get("nature") or "nature"
    bits = [kind]
    if s["kind"] in ("room", "hall", "corridor"):
        bits.append(f"{s.get('wall')} walls, {s.get('floor')} floor" + (f", {s.get('window')} window onto {s.get('view')}"
                                                                         if s.get("window") not in (None, "none") else ""))
    things = [*(s.get("things") or []), *(s.get("wall_things") or []), *(s.get("small") or [])]
    names = [t if isinstance(t, str) else t.get("thing") for t in things]
    if names:
        bits.append(", ".join(n.replace("_", " ") for n in names))
    if s.get("effects"):
        bits.append("effects: " + ", ".join(s["effects"]))
    return " · ".join(bits)


def _person_words(c: dict) -> str:
    lk = c.get("look") or {}
    bits = []
    if lk.get("hair") and lk["hair"] != "none":
        bits.append(f"{lk.get('hair_color', '')} {lk['hair']} hair".strip())
    if lk.get("cloth"):
        bits.append(f"{lk['cloth']} clothes")
    bits += [e for e in lk.get("extras") or []]
    return ", ".join(bits)


def story_section(story: dict, name: str, pics: dict, rel) -> str:
    """One story's part of the page: what it is, its places and people, then every shot under its stage."""
    out = [f'<section id="{_e(name)}"><h2>{_e(story["title"])}</h2>',
           f'<p class="brief"><b>The brief:</b> {_e(story.get("brief"))}</p>',
           f'<p><b>Theme:</b> {_e(story.get("theme"))} · <b>Core message:</b> {_e(story.get("core_message"))}</p>']
    thumb = story.get("thumbnail") or {}
    if thumb:
        out.append(f'<p><b>Thumbnail:</b> shot {thumb.get("shot")}, words <span class="lead">{_e(thumb.get("lead"))}</span> '
                   f'<span class="punch">{_e(thumb.get("punch"))}</span></p>')
    out.append(f'<p><b>Music starts:</b> shot {int(story.get("realization", 0)) + 1} (his realization)</p>')
    out.append('<h3>The places</h3><div class="grid places">')
    for place in story.get("places") or []:
        src = pics["places"].get(place["id"])
        out.append(f'<figure><a href="{rel(src)}" target="_blank"><img src="{rel(src)}" loading="lazy" alt=""></a>'
                   f'<figcaption><span><b>{_e(place["id"])}</b>: {_e(place.get("name"))}</span><span class="dim">'
                   f'{_e(_place_words(place))}</span></figcaption></figure>')
    out.append('</div><h3>The people</h3>')
    out.append(f'<a href="{rel(pics["cast"])}" target="_blank"><img class="wide" src="{rel(pics["cast"])}" alt=""></a><ul>'
               '<li><b>him</b>: always the same man, the teal hoodie</li>')
    for c in story.get("cast") or []:
        out.append(f'<li><b>{_e(c["id"])}</b>: {_e(c.get("role"))} <span class="dim">({_e(_person_words(c))})</span></li>')
    out.append("</ul>")
    stage = None
    chapters = story.get("chapters") or {}
    for k, shot in enumerate(story["shots"]):
        if shot.get("stage") != stage:
            if stage is not None:
                out.append("</div>")
            stage = shot.get("stage")
            out.append(f'<h3>{_e(STAGE_NAMES.get(stage, stage))}: <span class="chapter">“{_e(chapters.get(stage, ""))}”</span>'
                       f'</h3><div class="grid shots">')
        src = pics["shots"][k]
        line = shot.get("line") or ""
        num = (f"line {shot['line_index'] + 1}" if shot.get("line_index") is not None else "quiet")
        who = shot.get("him") or {}
        bits = [shot.get("place", "") if not shot.get("set") else f"set {shot['set']}", shot.get("framing", ""),
                shot.get("move", "") if shot.get("move") not in (None, "hold") else "",
                f"event {shot['event']}" if shot.get("event") not in (None, "none") else "",
                f"him {who.get('action')} at {who.get('mark') or who.get('at')}" if who.get("action") not in (None, "none")
                else "him not in it"]
        mark = " ★ music starts" if k == story.get("realization") else ""
        mark += " ★ thumbnail" if thumb and k + 1 == thumb.get("shot") else ""
        out.append(f'<figure class="shot"><a href="{rel(src)}" target="_blank"><img src="{rel(src)}" loading="lazy" alt="">'
                   f'</a><figcaption><span><span class="num">{k + 1}</span> <span class="dim">{_e(num)}{_e(mark)}</span></span>'
                   + (f'<q>{_e(line)}</q>' if line else '<q class="dim">(no words)</q>')
                   + f'<span class="shows">Shows: {_e(shot.get("shows"))}</span>'
                   f'<span class="dim small">{_e(" · ".join(b for b in bits if b))}</span></figcaption></figure>')
    if stage is not None:
        out.append("</div>")
    notes, missing = story.get("board_notes") or [], story.get("missing") or []
    if missing:
        out.append("<h3>Missing pieces (the library's next additions)</h3><ul>"
                   + "".join(f"<li>{_e(m)}</li>" for m in missing) + "</ul>")
    if notes:
        out.append('<details><summary>What code changed in the storyboard</summary><ul>'
                   + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul></details>")
    out.append("</section>")
    return "\n".join(out)


PAGE_STYLE = """
:root { --bg: #0e0b12; --card: #18131d; --ink: #f2e8dc; --dim: #b9a9b8; --accent: #ffc383; --punch: #ffd84a; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }
header, section { max-width: 1280px; margin: 0 auto; padding: 18px 16px; }
h1 { margin: 10px 0 6px; font-size: 28px; color: var(--accent); }
h2 { color: var(--accent); margin: 28px 0 6px; font-size: 26px; border-top: 1px solid #2c2433; padding-top: 22px; }
h3 { margin: 26px 0 10px; color: var(--ink); } .chapter { color: var(--accent); font-weight: normal; }
p { max-width: 900px; margin: 6px 0; } nav a { color: var(--ink); margin-right: 14px; }
.dim { color: var(--dim); } .small { font-size: 13px; } .lead { font-weight: 700; } .punch { color: var(--punch); font-weight: 700; }
.grid { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); }
figure { margin: 0; background: var(--card); border-radius: 8px; overflow: hidden; }
figure img, img.wide { width: 100%; height: auto; display: block; background: #000; }
img.wide { border-radius: 8px; max-width: 760px; }
figcaption { padding: 8px 10px 10px; font-size: 14px; display: flex; flex-direction: column; gap: 4px; }
.num { display: inline-block; min-width: 26px; padding: 0 6px; border-radius: 4px; background: #3a2b40; color: var(--accent);
  font-weight: 700; text-align: center; margin-right: 6px; }
q { font-size: 15px; } .shows { color: #e2d3c8; }
details { margin: 14px 0; } summary { cursor: pointer; color: var(--dim); }
"""


def write_page(entries: list[tuple[str, dict, dict]], out: Path, title: str = "Storyboards") -> Path:
    """The page: each story (name, story, its pictures) one after the other."""
    out = Path(out)

    def rel(path):
        return Path(path).resolve().relative_to(out.parent.resolve()).as_posix()
    nav = " ".join(f'<a href="#{_e(n)}">{_e(s["title"])}</a>' for n, s, _ in entries)
    body = "\n".join(story_section(s, n, pics, rel) for n, s, pics in entries)
    out.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
                   f'content="width=device-width,initial-scale=1"><title>{_e(title)}</title><style>{PAGE_STYLE}</style>'
                   f'</head><body><header><h1>{_e(title)}</h1><p class="dim">Each story\'s storyboard as Agent 3 designed '
                   f'it from the script: its places and people, then a still of every shot with the narrator\'s line '
                   f'under it. Click a picture to see it full size.</p><nav>{nav}</nav></header>{body}</body></html>',
                   encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("stories", nargs="+", help="storyboarded stories (JSON: the story, or {\"story\": ...})")
    parser.add_argument("--out", required=True, help="the folder for the pictures and index.html")
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()
    out = Path(args.out)
    entries = []
    for path in args.stories:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        story = data.get("story") or data
        name = Path(path).stem
        print(f"Drawing {name}: {len(story['shots'])} shots")
        entries.append((name, story, draw_board(story, out / name, workers=args.workers)))
    print(write_page(entries, out / "index.html"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
