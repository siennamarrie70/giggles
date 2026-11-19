"""
The library's catalog: every place, thing, action, look, mood and effect of the silhouette stories drawn on contact
sheets (each in its lights), and a short film of what moves, with a page that shows them all (index.html). It's how the
owner checks the library before stories use it. Everything is drawn on this computer: nothing is uploaded, nothing
counts against a free allowance.

Usage:
    python tools/silhouette_catalog.py                      # all of it, into .tmp/library/
    python tools/silhouette_catalog.py --only things moods  # some sections (places, weather, things, actions, people,
                                                            # moods, effects, motion)
    python tools/silhouette_catalog.py --out some/folder --workers 4
"""

import argparse
import html
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import silhouette as S  # noqa: E402
import silhouette_actions as A  # noqa: E402
import silhouette_marks as MK  # noqa: E402
import silhouette_scene as SC  # noqa: E402
import silhouette_words as W  # noqa: E402
from common import ASSETS_DIR, TMP_DIR  # noqa: E402

LIGHTS = ("dawn", "day", "dusk", "night")
HIM = S.LOOKS["him"]
HER = S.look_from({"hair": "long", "extras": ["dress"], "cloth": "wine", "build": 0.86, "size": 0.95})
FONT = ASSETS_DIR / "fonts" / "Oswald[wght].ttf"

# --- what each section shows ------------------------------------------------------------------------------------------
# a place: (name, its description, the action shown, its mark, an item, a second person: (action, mark, look) or a pair)
PLACES = [
    ("bedroom", {"kind": "room", "wall": "plum", "floor": "wood", "window": "small", "view": "city", "curtains": True,
                 "things": ["bed", "nightstand", "wardrobe"], "wall_things": ["photos", "clock"], "small": ["phone"]},
     "lying_awake", "bed"),
    ("living room", {"kind": "room", "wall": "mauve", "floor": "carpet", "window": "big", "view": "trees",
                     "things": ["bookcase", "sofa", "floor_lamp", "tv"], "wall_things": ["poster"], "small": ["mess"]},
     "head_in_hands", "sofa"),
    ("kitchen", {"kind": "room", "wall": "sand", "floor": "tiles", "window": "small", "view": "houses",
                 "things": ["fridge", "stove", "counter", "dining_table"], "wall_things": ["cabinets", "calendar"],
                 "small": ["letters", "mug"]}, "cooking", "stove"),
    ("bathroom", {"kind": "room", "wall": "teal", "floor": "tiles", "window": "none", "things": ["basin", "plant"]},
     "mirror", "mirror"),
    ("study", {"kind": "room", "wall": "rose", "floor": "wood", "window": "big", "view": "city",
               "things": ["bookcase", "desk", "armchair"], "wall_things": ["certificates"], "small": ["laptop", "books"]},
     "writing", "desk"),
    ("office", {"kind": "room", "wall": "slate", "floor": "concrete", "window": "wide", "view": "city",
                "things": ["office_row", "desk", "filing_cabinet", "plant"], "wall_things": ["whiteboard"],
                "small": ["documents"]}, "typing", "desk"),
    ("meeting room", {"kind": "room", "wall": "navy", "floor": "carpet", "window": "big", "view": "city",
                      "things": ["meeting_table", "water_cooler"], "wall_things": ["screen"], "small": ["laptop"]},
     "sitting", "meeting"),
    ("shop", {"kind": "room", "wall": "olive", "floor": "tiles", "window": "big", "view": "city",
              "things": ["shop_shelves", "shop_counter"], "wall_things": ["notice_board"]}, "standing", "shop_2"),
    ("workshop", {"kind": "room", "wall": "brick", "floor": "concrete", "window": "small", "view": "houses",
                  "things": ["workbench", "shop_shelves"], "wall_things": ["tool_wall"]}, "fixing", "bench"),
    ("restaurant kitchen", {"kind": "room", "wall": "grey", "floor": "tiles", "window": "none",
                            "things": ["chef_range", "prep_counter"]}, "cooking", "range"),
    ("gym", {"kind": "room", "wall": "grey", "floor": "concrete", "window": "big", "view": "city",
             "things": ["weights", "punching_bag", "treadmill"], "wall_things": ["mirror"]}, "boxing", "bag"),
    ("hospital room", {"kind": "room", "wall": "white", "floor": "tiles", "window": "small", "view": "city",
                       "things": ["heart_monitor", "hospital_bed", "chair"]}, "slumped", "chair"),
    ("conference hall", {"kind": "hall", "wall": "navy", "floor": "wood", "things": ["stage", "podium", "audience"],
                         "effects": ["spotlight"]}, "speaking", "podium"),
    ("banquet hall", {"kind": "hall", "wall": "rose", "floor": "stone", "things": ["dining_table", "dining_table"],
                      "small": ["candles", "wine"], "effects": ["party"]}, "eating", "table"),
    ("corridor", {"kind": "corridor", "wall": "white", "floor": "tiles"}, "head_in_hands", "wait"),
    ("city street", {"kind": "street", "things": ["shopfront", "bus_stop", "bin"]}, "phone", "bus_stop"),
    ("street of houses", {"kind": "houses", "things": ["fence", "mailbox"]}, "standing", "spot"),
    ("bridge", {"kind": "bridge"}, "at_window", "spot"),
    ("sea and beach", {"kind": "nature", "nature": "sea", "things": ["rock"]}, "sitting", "rock"),
    ("mountains", {"kind": "nature", "nature": "mountains", "things": ["campfire"]}, "sitting", "campfire"),
    ("forest", {"kind": "nature", "nature": "forest"}, "walking", "walk"),
    ("field", {"kind": "nature", "nature": "field", "things": ["grave"]}, "kneeling", "grave"),
    ("lake", {"kind": "nature", "nature": "lake", "things": ["bench"]}, "sitting", "bench"),
    ("hills", {"kind": "nature", "nature": "hills", "things": ["tree"]}, "running", "run"),
    ("inside a car", {"kind": "car", "view": "city"}, "driving", "driver"),
    ("inside a bus", {"kind": "bus", "view": "city"}, "sitting", "seat_2"),
    ("inside a train", {"kind": "train", "view": "fields"}, "reading", "seat"),
]
WEATHER_SHOTS = [("city street", "rain", "night"), ("city street", "snow", "dusk"), ("city street", "fog", "dawn"),
                 ("street of houses", "rain", "dusk"), ("street of houses", "snow", "night"), ("forest", "snow", "day"),
                 ("forest", "fog", "dawn"), ("bedroom", "rain", "night"), ("bedroom", "snow", "dawn"),
                 ("sea and beach", "fog", "day"), ("mountains", "snow", "dawn"), ("inside a car", "rain", "night")]
EFFECT_SHOTS = [
    ("fire: a room", {"kind": "room", "wall": "sand", "floor": "tiles", "window": "small", "things": ["counter", "stove"]},
     ["fire"], ("standing", "spot")),
    ("fire: a house", {"kind": "houses", "things": ["fence"]}, ["fire", "smoke"], ("standing", "spot")),
    ("fire: a fireplace", {"kind": "room", "wall": "rose", "floor": "carpet", "window": "none", "lamp": "none",
                           "things": ["armchair", "fireplace", "plant"], "small": ["photo_frame"]}, [], ("sitting", "armchair")),
    ("smoke", {"kind": "street", "things": ["shopfront"]}, ["smoke"], ("standing", "spot")),
    ("emergency lights", {"kind": "street", "things": ["ambulance"]}, ["emergency"], ("phone_call", "spot")),
    ("party lights", {"kind": "hall", "wall": "rose", "floor": "stone", "things": ["dining_table"],
                      "small": ["candles", "wine"]}, ["party"], ("applauding", "spot")),
    ("spotlight", {"kind": "hall", "wall": "navy", "floor": "wood", "things": ["stage", "audience"]}, ["spotlight"],
     ("standing", "stage")),
    ("snow", {"kind": "nature", "nature": "forest"}, ["snow"], ("walking", "walk")),
    ("fog", {"kind": "nature", "nature": "field"}, ["fog"], ("standing", "spot")),
    # how the whole picture can feel (any story's: none belongs to a topic)
    ("red pulse", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["red_pulse"], ("shouting", "spot")),
    ("pink haze", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["pink_haze"], ("staring", "sofa")),
    ("green tint", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["green_tint"], ("clenching", "spot")),
    ("grey drain", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["grey_drain"], ("sulking", "sofa")),
    ("tunnel", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["tunnel"], ("doomscrolling", "sofa")),
    ("shake", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["shake", "red_pulse"], ("shaking_fists", "spot")),
    ("timelapse", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city",
                   "things": ["sofa", "tv"], "wall_things": ["clock"]}, ["timelapse"], ("watching_tv", "sofa")),
    ("notifications", {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True, "things": ["sofa", "coffee_table"]}, ["notifications"], ("doomscrolling", "sofa")),
    ("shadows", {"kind": "room", "wall": "slate", "floor": "wood", "window": "big", "view": "city",
                 "things": ["bed"]}, ["shadows"], ("hiding_bed", "bed")),
]
# a thing on its own: the place it's shown in, and what he does at it (by its first mark's kind)
OUT_PLACE = {"house": "houses", "fence": "houses", "mailbox": "houses", "tree": "nature", "pine": "nature",
             "grave": "nature", "campfire": "nature", "rock": "nature", "railing": "bridge"}
ACTION_BY_KIND = {"lie": "asleep", "sit": "sitting", "stand": "standing", "kneel": "kneeling", "pushup": "pushups",
                  "treadmill": "treadmill", "drive": "driving"}
ACTION_BY_USE = {"cooking": "cooking", "typing": "typing", "mirror": "mirror", "boxing": "boxing", "lifting": "lifting",
                 "fixing": "fixing", "speaking": "speaking", "at_door": "at_door", "wiping": "wiping", "eating": "eating",
                 "kneeling": "kneeling", "treadmill": "treadmill", "asleep": "asleep"}
# an action in a place that fits it: (place, mark, item)
ACTION_PLACE = {
    "standing": ("living room", "spot", None), "walking": ("city street", "walk", None),
    "running": ("hills", "run", None), "sitting": ("living room", "sofa", None), "slumped": ("kitchen", "table", None),
    "head_in_hands": ("bedroom", "bed_edge", None), "typing": ("office", "desk", None),
    "phone": ("city street", "bus_stop", None), "phone_call": ("street of houses", "spot", None),
    "lying_awake": ("bedroom", "bed", None), "asleep": ("bedroom", "bed", None), "asleep_desk": ("office", "desk", None),
    "lying_floor": ("living room", "spot", None), "floor": ("bedroom", "floor", None),
    "at_window": ("living room", "window", None), "pushups": ("gym mat", "mat", None),
    "carrying_box": ("corridor", "walk_out", None), "at_door": ("corridor", "door", None),
    "cooking": ("kitchen", "stove", None), "eating": ("kitchen", "table", None),
    "drinking": ("living room", "sofa_2", "bottle"), "reading": ("study", "armchair", None),
    "letter": ("kitchen", "spot", None), "writing": ("study", "desk", None), "lifting": ("gym", "weights", None),
    "boxing": ("gym", "bag", None), "treadmill": ("gym", "treadmill", None), "driving": ("inside a car", "driver", None),
    "cleaning": ("living room", "spot", None), "wiping": ("kitchen", "counter", None),
    "fixing": ("workshop", "bench", None), "speaking": ("conference hall", "podium", None),
    "presenting": ("meeting room", "screen", None), "hugging": ("lake", "pair", None),
    "handshake": ("office", "pair", None), "arguing": ("kitchen", "pair", None), "crying": ("bedroom", "bed_edge", None),
    "kneeling": ("field", "grave", "flowers"), "mirror": ("bathroom", "mirror", None),
    "applauding": ("banquet hall", "spot", None), "waving": ("street of houses", "spot", None),
    "holding": ("city street", "walk", "suitcase"),
    # a habit's exaggerated actions
    "slamming": ("kitchen", "counter", None), "throwing": ("living room", "spot", None),
    "punching_wall": ("corridor", "spot", None), "shouting": ("kitchen", "spot", None),
    "shaking_fists": ("living room", "spot", None), "hiding_phone": ("bedroom", "bed_edge", None),
    "staring": ("living room", "sofa", None), "doomscrolling": ("bedroom", "bed_edge", None),
    "sprawled": ("living room", "sofa_lie", None), "snoozing": ("bedroom", "bed", None),
    "stretching": ("bedroom", "spot", None), "snacking": ("living room", "sofa", None),
    "watching_tv": ("living room", "sofa", None), "peeking": ("corridor", "spot", None),
    "clenching": ("office", "spot", None), "arms_crossed": ("office", "spot", None),
    "admiring": ("bathroom", "mirror", None), "waving_off": ("office", "spot", None),
    "posing": ("living room", "spot", None), "curled_up": ("bedroom", "floor", None),
    "sulking": ("living room", "sofa", None), "hiding_bed": ("bedroom", "bed", None),
    "backing_away": ("corridor", "spot", None), "cowering": ("living room", "spot", None),
    "counting_money": ("office", "desk", None), "hugging_bag": ("living room", "spot", None),
    "grabbing": ("kitchen", "spot", None), "rising": ("bedroom", "bed_edge", None),
    "ticking": ("meeting room", "screen", None), "watering": ("living room", "spot", None),
    "meditating": ("bedroom", "floor", None),
}
EXTRA_PLACES = {"gym mat": {"kind": "room", "wall": "grey", "floor": "concrete", "window": "big", "view": "city",
                            "things": ["gym_mat", "weights"]}}
CAST = [("him", None), ("short hair", {"hair": "short", "cloth": "navy"}),
        ("grey hair, glasses", {"hair": "short", "hair_color": "grey", "extras": ["glasses"], "cloth": "cream"}),
        ("beard", {"hair": "short", "hair_color": "brown", "extras": ["beard"], "cloth": "forest", "build": 1.15}),
        ("grey beard", {"extras": ["beard"], "beard_color": "grey", "cloth": "brown", "build": 1.2}),
        ("helmet", {"extras": ["helmet"], "cloth": "mustard", "build": 1.2}),
        ("apron", {"hair": "short", "extras": ["apron"], "cloth": "white"}),
        ("dress", {"hair": "long", "extras": ["dress"], "cloth": "wine", "build": 0.86, "size": 0.95}),
        ("jacket", {"hair": "short", "extras": ["jacket"], "cloth": "cream", "jacket_color": "navy"}),
        ("suit", {"hair": "short", "extras": ["suit"], "cloth": "charcoal", "build": 1.1}),
        ("grey bun, dress, glasses", {"hair": "bun", "hair_color": "grey", "extras": ["dress", "glasses"], "cloth": "plum",
                                      "size": 0.93}),
        ("coat, long hair", {"hair": "long", "hair_color": "auburn", "extras": ["coat"], "cloth": "slate", "build": 0.88}),
        ("nurse", {"hair": "bun", "cloth": "blue", "extras": ["coat"], "build": 0.9}),
        ("doctor", {"hair": "short", "hair_color": "grey", "extras": ["stethoscope", "coat", "glasses"], "cloth": "white"}),
        ("cap", {"extras": ["cap"], "cloth": "brown", "build": 1.25}), ("blonde, jacket", {"hair": "long", "hair_color": "blonde",
                                                                                         "extras": ["jacket"], "cloth": "rose",
                                                                                         "jacket_color": "black",
                                                                                         "build": 0.86, "size": 0.95})]
MOTION = [("fire: a room", None, None), ("fire: a house", None, None), ("emergency lights", None, None),
          ("snow", None, None), ("fog", None, None), ("party lights", None, None), ("spotlight", None, None),
          ("inside a car", "night", "driving"), ("inside a train", "day", "reading"), ("inside a bus", "dusk", "sitting"),
          ("gym", "dawn", "boxing"), ("kitchen", "dusk", "cooking"), ("bedroom", "night", "crying"),
          ("hospital room", "night", "slumped"), ("lake", "dawn", "hugging"), ("office", "day", "handshake"),
          ("living room", "night", "cleaning"), ("street of houses", "dusk", "waving"), ("sea and beach", "dusk", "sitting"),
          ("conference hall", "night", "speaking")]


# --- drawing one moment ---------------------------------------------------------------------------------------------------
def _font(px):
    return ImageFont.truetype(str(FONT), px)


def _ground(place):
    return getattr(place, "FLOOR", None) or getattr(place, "GROUND", 300.0)


def actors(place, action, mark_name, t, item=None, other=None, eyes=None, signs=(), screen=None):
    """The people of a moment: him doing `action` on `mark_name` (a pair: him and her), someone else if given; his eyes
    (a mood), the marks round his head, his phone's screen when the shot gives them."""
    marks = place.MARKS
    if mark_name not in marks:
        alt = [n for n in marks if n.startswith("spot")] or \
              [n for n, m in marks.items() if isinstance(m, dict) and m.get("kind") == "stand"] or \
              [n for n, m in marks.items() if isinstance(m, dict)]
        mark_name = alt[0]
    m = dict(marks[mark_name]) if isinstance(marks[mark_name], dict) else dict(marks[mark_name][0])
    out = []
    gnd = _ground(place)
    if action in W.PAIRS:
        if m.get("kind") != "pair":
            m = {"kind": "pair", "x": m.get("x", 0.0), "f": 1}
        a, ea, b, eb = A.pair(action, m, t, place.R, place.R * HER.size, gnd)
        return [{"pose": b, "look": HER, "eyes": A.eyes_of(eb, HER.gap, f=b["f"])},
                {"pose": a, "look": HIM, "eyes": A.eyes_of(ea, HIM.gap, f=a["f"])}]
    if action == "presenting" and "point" not in m:
        m["point"] = (m.get("x", 0.0) + 300.0, -200.0)
    pose, hint = A.pose(action, m, t, place.R, gnd, item=item, seconds=6.0)
    if screen and pose.get("hold") and pose["hold"].get("kind") in ("phone", "phone_up"):
        pose = {**pose, "hold": {**pose["hold"], "screen": screen, "t": t}}
    if "tremble" in signs:
        pose = MK.shake(pose, t)
    e = None if pose.get("face_hidden") else A.eyes_of(hint, HIM.gap, mood=eyes, f=pose["f"])
    a = {"pose": pose, "look": HIM, "eyes": e, "slot": m.get("slot", "main"), "marks": list(signs)}
    for k in ("glass", "oval"):   # (at a mirror: the scene draws the reflection)
        if m.get(k):
            a[k] = m[k]
    out.append(a)
    if other:
        oa, om, olook = other
        if om in marks:
            mm = dict(marks[om])
            p2, h2 = A.pose(oa, mm, t, place.R * olook.size, gnd)
            out.insert(0, {"pose": p2, "look": olook, "eyes": A.eyes_of(h2, olook.gap, f=p2["f"]), "slot": mm.get("slot", "main")})
    return out


def draw(spec, size, light, weather="clear", effects=(), action=None, mark=None, item=None, t=1.4, label="", note=True,
         seed="catalog", other=None, place=None, close=None, eyes=None, marks=(), screen=None, zoom=None):
    """One moment of a place, labelled: an RGB image. close: (thing name, height) frames that thing close."""
    if close and place is None:
        name, height = close
        probe = SC.build(spec, (160, 90), light, weather, effects, seed=seed)
        t_ = next(t_ for t_ in probe.things + probe.wall_things + probe.small_things if t_.name == name)
        y = (t_.b - SC.PR.HANG[name]) if t_.layer == "wall" else (t_.b - min(140.0, height * 0.25))
        place = SC.build(spec, size, light, weather, effects, seed=seed, center=(t_.x, y), height=height)
    place = place or SC.build(spec, size, light, weather, effects, seed=seed)
    acts = actors(place, action, mark, t, item, other, eyes, marks, screen) if action else []
    cam = place.cam.rest
    if zoom and acts:   # (closer on him, for his eyes and the marks round his head)
        hx, hy = acts[-1]["pose"]["head"]
        cam = (hx, hy + 120.0, cam[2] * zoom)
    f = place.frame(int(t * S.FPS), {"cam": cam, "actors": acts, "tau": t})
    im = Image.fromarray(np.frombuffer(S.to_bytes(f), np.uint8).reshape(size[1], size[0], 3))
    if label:
        d = ImageDraw.Draw(im)
        px = max(12, size[1] // 22)
        y = int(size[1] * 0.075) + 4
        d.text((10, y), label, font=_font(px), fill=(255, 240, 220))
        miss = getattr(place, "missing", [])
        if note and miss:
            d.text((10, y + px + 4), "missing: " + ", ".join(miss), font=_font(int(px * 0.8)), fill=(255, 150, 130))
    return im


def _place_spec(name):
    for n, spec, *_ in PLACES:
        if n == name:
            return spec
    return EXTRA_PLACES[name]


def _place_demo(name):
    for n, spec, action, mark in PLACES:
        if n == name:
            return spec, action, mark
    raise KeyError(name)


# --- one row of a sheet (a worker draws it) -------------------------------------------------------------------------------
def row_place(args):
    name, size = args
    spec, action, mark = _place_demo(name)
    other = None
    if name == "hospital room":
        other = ("asleep", "hospital_bed", S.look_from({"hair": "bun", "hair_color": "grey", "size": 0.93}))
    return [draw(spec, size, light, action=action, mark=mark, label=f"{name} · {light}", seed=name, other=other)
            for light in LIGHTS]


def row_weather(args):
    (name, weather, light), size = args
    spec, action, mark = _place_demo(name)
    return [draw(spec, size, light, weather, action=action, mark=mark, label=f"{name} · {weather} · {light}", seed=name)]


def thing_demo(name):
    """A thing on its own: its place's description, and what he does at it (action, mark, item)."""
    group, about, width, layer, where, tall, surface = W.PROPS[name]
    if layer == "small":
        return {"kind": "room", "wall": "plum", "window": "small", "lamp": "none", "things": ["coffee_table"],
                "small": [name]}, ("standing", "spot", None)
    if layer == "floor_small":
        return {"kind": "room", "wall": "plum", "window": "small", "lamp": "none", "small": [name]}, ("standing", "spot", None)
    if layer == "wall":
        spec = {"kind": "room", "wall": "plum", "window": "small", "lamp": "none", "wall_things": [name]}
        return spec, (("mirror", "mirror", None) if name == "mirror" else ("standing", "spot", None))
    if where == "out":
        kind = OUT_PLACE.get(name, "street")
        spec = {"kind": kind, "things": [name]}
        if kind == "nature":
            spec["nature"] = "field"
    else:
        spec = {"kind": "room", "wall": "plum", "window": "small", "lamp": "none", "things": [name]}
        if name in ("audience",):
            spec = {"kind": "hall", "things": ["stage", name]}
    from silhouette_props import Ctx, Thing
    marks = Thing(name, 0.0, 300.0, Ctx()).marks()
    if not marks:
        return spec, ("standing", "spot", None)
    mname, m = next(iter(marks.items()))
    use = [u for u in m.get("use", []) if u in ACTION_BY_USE]
    action = ACTION_BY_USE[use[0]] if use else ACTION_BY_KIND.get(m["kind"], "standing")
    return spec, (action, mname, None)


def row_thing(args):
    name, size = args
    spec, (action, mark, item) = thing_demo(name)
    layer = W.PROPS[name][3]
    close = {"small": (name, 330.0), "floor_small": (name, 420.0), "wall": (name, 560.0)}.get(layer)
    if close and name == "mirror":
        close = (name, 700.0)
    return [draw(spec, size, light, action=action if not close or name == "mirror" else None, mark=mark, item=item,
                 label=f"{name} · {light}", seed=name, close=close) for light in LIGHTS]


def row_action(args):
    name, size = args
    pname, mark, item = ACTION_PLACE[name]
    spec = _place_spec(pname)
    light = {"inside a car": "night", "conference hall": "night", "bedroom": "night"}.get(pname, "dusk")
    return [draw(spec, size, light, action=name, mark=mark, item=item, t=t, label=f"{name} ({pname})" if t == 1.4 else "",
                 seed=pname, note=False) for t in (1.4, 2.6)]


TOPIC_PLACE = {"slamming": ("kitchen", "counter"), "throwing": ("living room", "spot"),
               "punching_wall": ("corridor", "spot"), "lying_awake": ("bedroom", "bed"), "asleep": ("bedroom", "bed"),
               "phone": ("living room", "sofa")}


def row_topic(args):
    """Ideas for a topic of the owner's list (tools/silhouette_words.IDEAS): its actions, each with big eyes and marks
    (and the phone's screen), its effects on him, its things, its pictures for thought bubbles."""
    kit, size = args
    k = W.IDEAS[kit]
    tiles = []
    eyes = (k["eyes"] or [None])
    marks = k["marks"]
    for n, action in enumerate(k["actions"][:6]):
        pname, mark, item = ACTION_PLACE.get(action, ("living room", "spot", None))
        pname, mark = TOPIC_PLACE.get(action, (pname, mark))
        screen = k["screens"][0] if k["screens"] and action in ("phone", "lying_awake", "doomscrolling") else None
        mk = [marks[n % len(marks)]] if marks else []
        light = "night" if n % 2 == 0 else "dusk"
        tiles.append(draw(_place_spec(pname), size, light, action=action, mark=mark, item=item, t=1.6,
                          label=f"{action} · eyes {eyes[n % len(eyes)]}" + (f" · {', '.join(mk)}" if mk else ""),
                          seed=pname, note=False, eyes=eyes[n % len(eyes)], marks=mk, screen=screen, zoom=1.6))
    for n, mood in enumerate(k["eyes"]):   # close on him: the eyes, with every mark of the kit
        tiles.append(draw({"kind": "room", "wall": "slate", "window": "none", "lamp": "none"}, size, "night",
                          action="standing", mark="spot", t=1.2 + n, label=f"eyes {mood}" +
                          (f" · {', '.join(marks[n * 2:n * 2 + 2] or marks[:2])}" if marks else ""), seed="eyes",
                          note=False, eyes=mood, marks=(marks[n * 2:n * 2 + 2] or marks[:2]), zoom=2.6))
    for screen in k["screens"]:
        if any(a in ("phone", "lying_awake", "doomscrolling") for a in k["actions"][:6]) and screen == k["screens"][0]:
            continue
        tiles.append(draw(_place_spec("living room"), size, "night", action="phone", mark="sofa", t=1.4,
                          label=f"his phone: {screen}", seed="screen", note=False, eyes=eyes[0], screen=screen, zoom=2.2))
    for fx in k["effects"]:
        action = k["actions"][0] if k["actions"] else "standing"
        pname, mark, item = ACTION_PLACE.get(action, ("living room", "spot", None))
        pname, mark = TOPIC_PLACE.get(action, (pname, mark))
        tiles.append(draw(_place_spec(pname), size, "night", effects=(fx,), action=action, mark=mark, item=item, t=1.8,
                          label=f"effect {fx}", seed=pname, note=False, eyes=eyes[0], marks=marks[:1]))
    for thing in k["things"]:
        spec, (action, mark, item) = thing_demo(thing)
        close = {"small": (thing, 330.0), "floor_small": (thing, 420.0), "wall": (thing, 560.0)}.get(W.PROPS[thing][3])
        tiles.append(draw(spec, size, "dusk", action=None if close else action, mark=mark, item=item,
                          label=f"in his place: {thing}", seed=thing, close=close, note=False))
    tiles.append(_pictures_tile(k["pictures"], size, f"{kit}: pictures for his thought bubbles"))
    return tiles


def tiles_marks(size):
    """Every mark round a head (tools/silhouette_marks.py), close on him."""
    room = {"kind": "room", "wall": "slate", "window": "none", "lamp": "none"}
    return [draw(room, size, "night", action="standing", mark="spot", t=1.3 + 0.37 * k, label=f"mark: {m}",
                 seed="marks", note=False, eyes={"steam": "furious", "vein": "furious", "aura_red": "furious",
                                                  "hearts": "hearts", "dollars": "dollars", "zzz": "closed",
                                                  "raincloud": "sobbing", "tremble": "terrified", "aura_green": "side_eye",
                                                  "sparkles": "smug", "notify": "spirals", "stars": "tired",
                                                  "exclaim": "wide", "question": "worried", "drool": "droopy",
                                                  "flies": "droopy", "jolt": "wide", "sweat": "worried"}.get(m),
                 marks=[m], zoom=1.9) for k, m in enumerate(W.MARKS)]


def tiles_screens(size):
    """His phone's screens, turned to us."""
    return [draw(_place_spec("living room"), size, "night", action="phone", mark="sofa", t=1.4, label=f"his phone: {sc}",
                 seed="screens", note=False, screen=sc, zoom=2.3) for sc in W.SCREENS]


def tiles_pictures(size):
    """Every picture a thought bubble can show, a dozen to a tile."""
    names = list(W.PICTURES)
    return [_pictures_tile(names[k:k + 12], size, "Pictures for thought bubbles · " + str(k // 12 + 1), cols=4)
            for k in range(0, len(names), 12)]


def _pictures_tile(names, size, label, cols=3):
    """Pictures for thought bubbles, each on a cream round as a bubble would show it."""
    import silhouette_icons as I
    W_, H_ = size
    buf = S.blank(size)
    paint = S.Paint(buf, S.View(0, 0, 1.0, 0, 0))
    frame = np.zeros((H_, W_, 3), np.float32)
    frame[:] = S.hexc("#1E1826")
    cols = min(cols, len(names)) or 1
    rows = (len(names) + cols - 1) // cols
    cw, ch = W_ / cols, (H_ - 40) / max(rows, 1)
    r = min(cw, ch) * 0.42
    for n, name in enumerate(names):
        cx, cy = cw * (n % cols) + cw / 2, 40 + ch * (n // cols) + ch / 2
        paint.poly(S.ell(cx, cy, r * 1.25, r, 48), S.hexc("#F4F1EA"))
        paint.poly(S.tube([tuple(q) for q in S.ell(cx, cy, r * 1.25, r, 48)] + [tuple(S.ell(cx, cy, r * 1.25, r, 48)[0])],
                          3.0, k=2), S.PAL["rim"], 0.9)
        I.draw(paint, name, cx, cy, r * 0.62, "cream", 0.8)
    S.over(frame, buf)
    im = Image.fromarray(np.frombuffer(S.to_bytes(frame), np.uint8).reshape(H_, W_, 3))
    ImageDraw.Draw(im).text((10, 8), label, font=_font(max(12, H_ // 22)), fill=(255, 240, 220))
    return im


def row_effect(args):
    (name, spec, effects, (action, mark)), size = args
    return [draw(spec, size, light, effects=effects, action=action, mark=mark, label=f"{name} · {light}", seed=name)
            for light in ("day", "night")]


def tiles_people(size):
    """The cast (each look standing, both ways) and the eyes' moods on him and on someone with glasses."""
    out = []
    room_spec = {"kind": "room", "wall": "plum", "window": "none", "lamp": "none"}
    for label, spec in CAST:
        look = HIM if spec is None else S.look_from(spec)
        place = SC.build(room_spec, size, "dusk", seed="cast")
        acts = []
        for k, x in enumerate((-170.0, 170.0)):
            f = 1 if k == 0 else -1
            pose = S.pose_stand(x, 300.0, f, place.R * look.size, arms="hang")
            acts.append({"pose": pose, "look": look, "eyes": S.eyes_for("open", (f * 1.0, 0.0), look.gap)})
        fr = place.frame(30, {"cam": place.cam.rest, "actors": acts, "tau": 1.2})
        im = Image.fromarray(np.frombuffer(S.to_bytes(fr), np.uint8).reshape(size[1], size[0], 3))
        ImageDraw.Draw(im).text((10, int(size[1] * 0.075) + 4), label, font=_font(max(12, size[1] // 22)), fill=(255, 240, 220))
        out.append(im)
    return out


def tiles_moods(size):
    out = []
    other = S.look_from({"hair": "short", "extras": ["glasses"], "cloth": "navy"})
    for mood in W.MOODS:
        place = SC.build({"kind": "room", "wall": "slate", "window": "none", "lamp": "none"}, size, "night", seed="moods")
        acts = []
        for k, (x, look) in enumerate(((-150.0, HIM), (150.0, other))):
            f = 1 if k == 0 else -1
            pose = S.pose_stand(x, 300.0, f, place.R * look.size, arms="hang")
            acts.append({"pose": pose, "look": look, "eyes": S.eyes_for(mood, (f * 1.0, 0.0), look.gap,
                                                                    tear=0.5 if mood == "sad" else 0.0)})
        cx, cy, z = place.cam.rest
        fr = place.frame(30, {"cam": (0.0, -60.0, z * 2.2), "actors": acts, "tau": 1.2})
        im = Image.fromarray(np.frombuffer(S.to_bytes(fr), np.uint8).reshape(size[1], size[0], 3))
        ImageDraw.Draw(im).text((10, int(size[1] * 0.075) + 4), mood, font=_font(max(12, size[1] // 22)), fill=(255, 240, 220))
        out.append(im)
    return out


# --- sheets -------------------------------------------------------------------------------------------------------------
def sheet(rows, cols, size, title, out: Path):
    """Tiles in a grid under a title; saved as a JPEG."""
    tiles = [t for r in rows for t in r]
    W_, H_ = size
    head = max(40, H_ // 5)
    n_rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (W_ * cols, head + H_ * n_rows), (12, 9, 16))
    ImageDraw.Draw(img).text((14, head // 5), title, font=_font(int(head * 0.55)), fill=(255, 226, 180))
    for k, t in enumerate(tiles):
        img.paste(t, ((k % cols) * W_, head + (k // cols) * H_))
    img.save(out, quality=86)
    return out


def _map(fn, jobs, workers):
    if workers <= 1:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, jobs))


def make(out: Path, only=None, workers=4, progress=print) -> list[dict]:
    """Draws the catalog's sheets (and the motion film) into `out`; returns what it made for the page."""
    out.mkdir(parents=True, exist_ok=True)
    made = []
    want = set(only or ("places", "weather", "things", "actions", "people", "moods", "effects", "marks", "topics",
                        "motion"))
    t0 = time.time()
    if "places" in want:
        size = (640, 360)
        rows = _map(row_place, [(n, size) for n, *_ in PLACES], workers)
        for k in range(0, len(rows), 9):
            part = k // 9 + 1
            p = sheet(rows[k:k + 9], 4, size, f"Places, each in its four lights (dawn, day, dusk, night) · {part}",
                      out / f"places_{part}.jpg")
            made.append({"section": "places", "file": p.name})
        progress(f"places: {time.time() - t0:.0f}s")
    if "weather" in want:
        size = (640, 360)
        rows = _map(row_weather, [(w, size) for w in WEATHER_SHOTS], workers)
        made.append({"section": "weather", "file": sheet(rows, 4, size, "Weather: rain, snow, fog", out / "weather.jpg").name})
        progress(f"weather: {time.time() - t0:.0f}s")
    if "things" in want:
        size = (480, 270)
        for group in W.PROP_GROUPS:
            names = [n for n, v in W.PROPS.items() if v[0] == group]
            rows = _map(row_thing, [(n, size) for n in names], workers)
            title = {"home": "Home", "wall": "On the walls", "work": "Work", "health": "Health and the gym",
                     "outdoors": "Outdoors", "small": "Small things"}[group]
            for k in range(0, len(rows), 12):
                part = k // 12 + 1
                p = sheet(rows[k:k + 12], 4, size, f"{title}, each in four lights (dawn, day, dusk, night) · {part}",
                          out / f"things_{group}_{part}.jpg")
                made.append({"section": "things", "file": p.name, "group": title})
            progress(f"things {group}: {time.time() - t0:.0f}s")
    if "actions" in want:
        size = (640, 360)
        names = list(W.ACTIONS)
        rows = _map(row_action, [(n, size) for n in names], workers)
        for k in range(0, len(rows), 16):
            part = k // 16 + 1
            p = sheet(rows[k:k + 16], 4, size, f"What people do (each twice, a moment apart) · {part}", out / f"actions_{part}.jpg")
            made.append({"section": "actions", "file": p.name})
        progress(f"actions: {time.time() - t0:.0f}s")
    if "people" in want:
        size = (480, 270)
        made.append({"section": "people", "file": sheet([tiles_people(size)], 4, size, "The cast: looks made from parts",
                                                        out / "people.jpg").name})
    if "moods" in want:
        size = (480, 270)
        made.append({"section": "moods", "file": sheet([tiles_moods(size)], 5, size, "The eyes' moods", out / "moods.jpg").name})
        progress(f"people: {time.time() - t0:.0f}s")
    if "effects" in want:
        size = (640, 360)
        rows = _map(row_effect, [(e, size) for e in EFFECT_SHOTS], workers)
        made.append({"section": "effects", "file": sheet(rows, 4, size, "Effects, by day and by night", out / "effects.jpg").name})
        progress(f"effects: {time.time() - t0:.0f}s")
    if "marks" in want:
        size = (480, 270)
        made.append({"section": "marks", "file": sheet([tiles_marks(size)], 4, size, "Marks round a head (any story's)",
                                                       out / "marks.jpg").name})
        made.append({"section": "marks", "file": sheet([tiles_screens(size)], 4, size, "His phone's screens, turned to us",
                                                       out / "marks_screens.jpg").name})
        made.append({"section": "marks", "file": sheet([tiles_pictures((640, 360))], 3, (640, 360),
                                                       "Pictures for his thought bubbles", out / "marks_pictures.jpg").name})
        progress(f"marks: {time.time() - t0:.0f}s")
    if "topics" in want:   # a few ideas for the topics of the owner's list (offered, never required)
        size = (640, 360)
        names = list(W.IDEAS)
        rows = _map(row_topic, [(n, size) for n in names], workers)
        for kit, row in zip(names, rows):
            k = W.IDEAS[kit]
            title = (f"Ideas for {kit} (any piece serves any story)" if k["kind"] == "weakness" else
                     f"Ideas for {kit} (before his turn, its weakness: {k['before']})")
            p = sheet([row], 4, size, title, out / f"topic_{kit.replace(' ', '_')}.jpg")
            made.append({"section": "topics", "file": p.name, "group": kit})
        progress(f"topics: {time.time() - t0:.0f}s")
    if "motion" in want:
        p = motion_film(out / "motion.mp4", workers=workers, progress=progress)
        made.append({"section": "motion", "file": p.name})
        progress(f"motion: {time.time() - t0:.0f}s")
    return made


# --- the film of what moves -----------------------------------------------------------------------------------------------
CLIP_SECONDS = 3.0


def _clip(args):
    """One clip's frames (raw RGB bytes), drawn by a worker."""
    (name, light, action), size = args
    effect = next((e for e in EFFECT_SHOTS if e[0] == name), None)
    if effect is not None:
        _, spec, effects, (act, mark) = effect
        light = "night" if name != "snow" else "dusk"
        item = None
    else:
        spec, demo_action, mark = _place_demo(name)
        effects, act, item = [], action or demo_action, None
        if act in W.PAIRS:
            mark = "pair"
        if act == "cleaning":
            mark = "spot"
    place = SC.build(spec, size, light, "clear", effects, seed=name)
    frames = []
    n = int(CLIP_SECONDS * S.FPS)
    font = _font(max(14, size[1] // 24))
    for i in range(n):
        t = 0.5 + i / S.FPS
        acts = actors(place, act, mark, t, item)
        f = place.frame(i, {"cam": place.cam.rest, "actors": acts, "tau": t})
        if i < 8:
            f = f * (i / 8)
        if i >= n - 8:
            f = f * ((n - 1 - i) / 8)
        im = Image.fromarray(np.frombuffer(S.to_bytes(f), np.uint8).reshape(size[1], size[0], 3))
        ImageDraw.Draw(im).text((14, int(size[1] * 0.075) + 6), f"{name} · {light}" + (f" · {act}" if action else ""),
                                font=font, fill=(255, 240, 220))
        frames.append(im.tobytes())
    return frames


def motion_film(path: Path, size=(960, 540), workers=4, progress=print) -> Path:
    import subprocess
    import media

    clips = _map(_clip, [(m, size) for m in MOTION], workers)
    W_, H_ = size
    enc = subprocess.Popen([media.ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                            f"{W_}x{H_}", "-r", str(S.FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for frames in clips:
        for fr in frames:
            enc.stdin.write(fr)
    enc.stdin.close()
    enc.wait()
    return path


# --- the page -------------------------------------------------------------------------------------------------------------
INTRO = {
    "places": "Each place is built in code from a description: its kind, walls, floor, window and view, and the things "
              "in it. Shown in the four lights a story can use, with him in it.",
    "weather": "The same places in rain, snow and fog.",
    "things": "Every piece of furniture and every object, each in four lights. Where a thing has a use (a bed, a stove, "
              "a punching bag), he is shown using it.",
    "actions": "Everything people can do, each in a place that fits it, twice a moment apart (every action moves a little: "
               "a stirring hand, a sob, a punch).",
    "people": "The people around him are made from parts: hair (short, long, a bun; black, brown, grey, white...), a "
              "beard, glasses, a cap or a helmet, an apron, a dress, a jacket or a suit, a coat. He is always the "
              "teal-hoodie man.",
    "moods": "The eyes' moods: the ten everyday ones, and ten a habit shows big (hearts, dollars, spirals, droopy, "
             "furious, side-eye, smug, sobbing, terrified, fire).",
    "marks": "What shows a habit big on anyone, in any story (none belongs to a topic): the marks round a head (steam, "
             "a vein, sweat, drool, Zzz, hearts, $, a rain cloud, flies, stars, a jolt, trembling, ?, !, sparkles, "
             "notifications, a green or a red glow), his phone's screen turned to us, and the pictures his thought "
             "bubbles can show.",
    "topics": "A habit shown big: every story shows its own habit or struggle exaggerated, with whichever of these "
              "pieces fit it (none belongs to a topic; a topic outside your list works the same). These sheets are only "
              "ideas for the topics in your Settings list: the storyboard is offered them, never made to use them. "
              "Each: actions with big eyes and the marks round his head, his phone's screen, effects, things, and "
              "pictures for his thought bubbles. Lust stays symbolic: hearts, sweat, a censored pink screen under 18+, "
              "never a body.",
    "effects": "Fire, smoke, emergency lights, party lights, a spotlight, snow and fog; and how a whole picture can feel "
               "(a red pulse, a pink haze, a green tint, the colour drained, tunnel vision, a shaking camera, a time-lapse, "
               "notifications popping up, creeping shadows): by day and by night.",
    "motion": "What moves: the effects, the world sliding past a car, a train and a bus, and some of the actions.",
}


def page(out: Path, made: list[dict]) -> Path:
    titles = {"places": "Places", "weather": "Weather", "things": "Things", "actions": "What people do",
              "people": "The cast", "moods": "Eyes", "effects": "Effects", "marks": "Marks, screens, pictures",
              "topics": "Ideas for your topics",
              "motion": "What moves"}
    parts = []
    for section in ("places", "weather", "things", "actions", "people", "moods", "effects", "marks", "topics",
                    "motion"):
        items = [m for m in made if m["section"] == section]
        if not items:
            continue
        parts.append(f'<section id="{section}"><h2>{titles[section]}</h2><p>{html.escape(INTRO[section])}</p>')
        for m in items:
            if m["file"].endswith(".mp4"):
                parts.append(f'<video src="{m["file"]}" controls loop muted playsinline></video>')
            else:
                parts.append(f'<a href="{m["file"]}" target="_blank"><img src="{m["file"]}" loading="lazy" '
                             f'alt="{html.escape(m.get("group", section))}"></a>')
        parts.append("</section>")
    nav = " · ".join(f'<a href="#{s}">{titles[s]}</a>' for s in titles if any(m["section"] == s for m in made))
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Story library</title><style>
:root {{ --bg: #0e0b12; --ink: #f2e8dc; --dim: #b9a9b8; --accent: #ffc383; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }}
header {{ padding: 28px 16px 8px; max-width: 1200px; margin: 0 auto; }}
h1 {{ margin: 0 0 6px; font-size: 28px; color: var(--accent); }}
nav {{ color: var(--dim); }} nav a {{ color: var(--ink); }}
section {{ max-width: 1200px; margin: 0 auto; padding: 18px 16px 30px; }}
h2 {{ color: var(--accent); margin: 10px 0 4px; }} p {{ color: var(--dim); max-width: 760px; }}
img, video {{ width: 100%; height: auto; display: block; margin: 12px 0; border-radius: 6px; background: #000; }}
</style></head><body><header><h1>The story library</h1>
<p>Everything the stories can now be drawn with: {len(W.PLACE_KINDS)} kinds of place, {len(W.PROPS)} things,
{len(W.ACTIONS)} actions, {len(W.MOODS)} moods, {len(W.EFFECTS)} effects. Click a sheet to see it full size.</p>
<nav>{nav}</nav></header>{''.join(parts)}</body></html>"""
    p = out / "index.html"
    p.write_text(doc, encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(TMP_DIR / "library"))
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=min(6, max(1, (os.cpu_count() or 2) - 2)))
    a = ap.parse_args()
    out = Path(a.out)
    made = make(out, a.only, a.workers)
    if a.only:   # keep what's there from a full run on the page
        old = sorted(p.name for p in out.glob("*.jpg") if not p.name.startswith("check_") and not p.name.startswith("zoom_"))
        names = {m["file"] for m in made}
        for name in old:
            if name not in names:
                section = name.split("_")[0].split(".")[0]
                section = {"topic": "topics"}.get(section, section)  # (marks_*.jpg: "marks")
                made.append({"section": section if section in INTRO else "things", "file": name})
        if (out / "motion.mp4").exists() and "motion.mp4" not in names:
            made.append({"section": "motion", "file": "motion.mp4"})
    print(page(out, made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
