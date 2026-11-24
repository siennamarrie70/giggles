"""
Agent 3's renderer for the silhouette stories: a story's shots (agents/story.py) drawn in the owner's look
(prompts/look_silhouette.txt.enc) by tools/silhouette.py, in the places of tools/silhouette_sets.py and
tools/silhouette_places.py. Everything is drawn in code: no AI pictures, nothing counted against a free allowance.

A shot names its place (SETS), its light (dusk, night, dawn, day) and rain; what he does (POSES: placed on the place's
marks by SET_POSES) and how his eyes are (silhouette.MOODS); who else is there (OTHERS, placed by SET_OTHERS); one event
(EVENTS: the head turning to camera with the eyes springing wide, the clock flipping...); the small label at the top;
the camera's move (CAMERA) and how it enters (ENTER). plan() resolves it once; state() gives every frame's moment:
breathing and blinks, a walk's or a run's cycle (the camera follows outdoors), the event's motion, the camera, the
label, fades. The film begins straight with its story (no title in the picture: your choice, 2026-11-20); the last
shot carries the closing line, and the last second of the film holds completely still.

render() draws the shots in parallel processes (one piece of video each), joins them, mixes the sound
(tools/film_sound.py: the beds and single sounds, the narrator's lines, the music from the spark) and makes the film.
The short version (render(upright=True), tools/story_film.py make_short) is drawn the same way from the film's shots it
picks, upright (1080x1920, each place framed on him, not cropped), beginning straight with the story and ending on the
closing line. The thumbnail is tools/thumbnail.py's.

Subtitles (your request, 2026-11-17; tools/subtitles.py cuts and times them by his words): the narrator's words in the
look's type (Oswald, warm white): the film's in the black band under the picture, one row, never over it; the short
version's low in its picture (SUB_TALL_Y), at most two rows on a soft dark halo, clear of what YouTube and Instagram
lay over a Short's bottom. The closing line has none: it's on screen in big type.

Usage:
    python tools/silhouette_render.py story.json out.mp4          # a story (agents/story.py --out) into a film, silent
"""

import argparse
import json
import math
import subprocess
import sys
import tempfile
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import silhouette as S

FPS = S.FPS
SIZE, TALL, THUMB = (1920, 1080), (1080, 1920), (1280, 720)

# --- the vocabulary (tools/silhouette_words.py: agents/story.py gives it to Gemini and checks every shot against it) ------
from silhouette_words import CAMERA, ENTER, EVENTS, MOODS, OTHER_POSES, OTHERS, POSES, SET_OTHERS, SET_POSES, SETS  # noqa: E402

assert set(MOODS) == set(S.MOODS), "silhouette_words.MOODS and silhouette.MOODS differ"
VOCABULARY = {"sets": SETS, "poses": POSES, "set_poses": SET_POSES, "others": OTHERS, "other_poses": OTHER_POSES,
              "set_others": SET_OTHERS, "moods": MOODS, "events": EVENTS, "camera": CAMERA, "enter": ENTER}

WALK_SPEED, RUN_SPEED, BOX_SPEED = 170.0, 520.0, 130.0   # world units a second
OUTDOORS = ("street", "park", "rooftop")
TITLE_PX, CLOSING_PX = 88, 50                             # at 1080 px
SUB_PX, SUB_TALL_PX = 40, 56                              # the subtitles' type at 1080 px: the film's fits its black band
SUB_CHARS, SUB_TALL_CHARS = 52, 30                        # the most letters in a subtitle's row (longer is hard to take in)
SUB_WIDTH, SUB_TALL_WIDTH = 0.84, 0.80                    # ...and its most width, a share of the frame's
SUB_TALL_Y = 0.75                                         # the short version's: the middle of its rows, a share of the height


# --- the places ----------------------------------------------------------------------------------------------------------------
_PLACES: OrderedDict = OrderedDict()


def place(name: str, size, light: str, rain: bool, center=None, open_door=False):
    """The place, drawn for this frame size and light (kept: a process keeps its most recent one)."""
    import silhouette_places as places
    import silhouette_sets as sets

    key = (name, tuple(size), light, bool(rain), tuple(center) if center else None, open_door)
    if key in _PLACES:
        _PLACES.move_to_end(key)
        return _PLACES[key]
    if name == "desk_room":
        obj = sets.DeskRoom(size, label="", light=light, rain=rain)
    elif name == "street":
        obj = sets.RainStreet(size, light=light, rain=rain, center=center)
    elif name == "hospital":
        obj = sets.HospitalRoom(size, light=light, rain=rain, center=center)
    elif name == "hallway":
        obj = places.Hallway(size, light, rain, center, open_door=open_door)
    else:
        obj = places.PLACES[name](size, light, rain, center)
    _PLACES[key] = obj
    while len(_PLACES) > 1:
        _PLACES.popitem(last=False)
    return obj


def place_class(name: str):
    import silhouette_places as places
    import silhouette_sets as sets

    return {"desk_room": sets.DeskRoom, "street": sets.RainStreet, "hospital": sets.HospitalRoom}.get(name) \
        or places.PLACES[name]


def marks(name: str) -> dict:
    return {"desk": {"kind": "desk"}} if name == "desk_room" else dict(place_class(name).MARKS)


def place_R(name: str) -> float:
    return {"desk_room": 95.0}.get(name, float(getattr(place_class(name), "R", 64.0)))


def ground_of(name: str) -> float:
    cls = place_class(name)
    return float(getattr(cls, "FLOOR", None) or getattr(cls, "GROUND", None) or getattr(cls, "WALK_Y", 300.0))


# --- a shot's plan ---------------------------------------------------------------------------------------------------------------
def plan(shot: dict, size=SIZE) -> dict:
    """What a shot draws, resolved once: the place and its light, him and anyone else on their marks, the event, the
    camera. Raises ValueError when the place can't hold it (agents/story.py checks before)."""
    name = shot["set"]
    if name not in SETS:
        raise ValueError(f"no place called {name!r}")
    light = shot.get("light") if shot.get("light") in SETS[name][1] else SETS[name][1][0]
    ms = marks(name)
    him = shot.get("him") or "none"
    him_mark = None
    if him != "none":
        mk = SET_POSES[name].get(him)
        if not mk:
            raise ValueError(f"{name} has no place for him {him}")
        him_mark = {**ms[mk], "name": mk}
    other, other_marks = shot.get("other") or "none", []
    if other != "none":
        ways = SET_OTHERS.get(name, {}).get(other)
        if not ways:
            raise ValueError(f"{other} can't be in {name}")
        how = shot.get("other_pose") if shot.get("other_pose") in ways else next(iter(ways))
        mk = ways[how]
        spec = ms[mk]
        for k, sp in enumerate(spec if isinstance(spec, list) else [spec]):
            other_marks.append({**sp, "name": mk, "how": how, "who": other, "k": k})
    seconds = float(shot["seconds"])
    out = {"set": name, "light": light, "rain": bool(shot.get("rain")), "him": him, "mark": him_mark,
           "mood": shot.get("eyes") if shot.get("eyes") in S.MOODS else None, "other": other, "others": other_marks,
           "other_mood": shot.get("other_eyes") if shot.get("other_eyes") in S.MOODS else "open",
           "event": shot.get("event") if shot.get("event") in EVENTS else "none",
           "event_at": float(shot.get("event_at") if shot.get("event_at") is not None else 0.45) * seconds,
           "camera": shot.get("camera") if shot.get("camera") in CAMERA else "hold", "seconds": seconds,
           "label": (shot.get("label") or "").strip().upper()[:28], "clock": shot.get("clock") or "",
           "R": place_R(name), "ground": ground_of(name), "seed": int(shot.get("seed") or 0),
           "open_door": name == "hallway" and other in ("landlord", "woman", "friend")}
    out["center"] = _center(out, size)
    return out


def plan_for(story: dict, shot: dict, size=SIZE) -> dict:
    """A story's shot resolved for drawing: Agent 3's storyboard shots (2026-11-17: a place of the story's own, built by
    tools/silhouette_board.py, or one of the sets drawn as before) and the shots of the stories before them (a set each).
    The visuals Agent 3 made for the story (story["visuals"], tools/visual_recipes.py) join the library first."""
    if story.get("visuals"):
        import visual_recipes

        visual_recipes.for_story(story)
    if shot.get("place") and not shot.get("set"):
        import silhouette_board as SB

        if SB.place_of(story, shot["place"]).get("set"):
            return plan(SB.old_shot(story, shot), size)
        return SB.plan(story, shot, size)
    return plan(shot, size)


def _subject_x(p: dict):
    m = p["mark"]
    if not m:
        return None
    if m["kind"] in ("walk", "run"):
        return (m["from"] + m["to"]) / 2
    return m.get("x")


def _center(p: dict, size):
    """An upright frame's resting centre: on him (a place's own framing is for a wide frame)."""
    W, H = size
    if H <= W or p["set"] == "desk_room":
        return None
    cls = place_class(p["set"])
    cx, cy = getattr(cls, "CENTER", (0.0, 0.0))
    x = _subject_x(p)
    if x is None and p["others"]:
        o = p["others"][0]
        x = o.get("x", (o.get("from", cx) + o.get("to", cx)) / 2)
    if x is None:
        x = -470.0 if p["set"] == "hospital" else cx
    elif p["set"] == "hospital" and p["him"] != "none":
        x = (x - 566.0) / 2   # (between him and his mother's head: the upright hospital is framed wider)
    return (float(x), float(cy))


# --- motion ----------------------------------------------------------------------------------------------------------------------
def _blink(t: float, seed: int) -> float:
    """1 open .. 0 shut: a blink every 2.8-4.4 s."""
    r = np.random.default_rng(seed + 7)
    at = float(r.uniform(0.6, 2.2))
    while at < t + 1:
        if at <= t < at + 0.16:
            return 1 - math.sin(math.pi * (t - at) / 0.16)
        at += float(r.uniform(2.8, 4.4))
    return 1.0


def _walked(m: dict, t: float, seconds: float, speed: float) -> tuple[float, float]:
    """Where a walker is (x) and how fast (0-1) at t: from `from` towards `to`, easing in, slowing to a stop at `to`."""
    length = abs(m["to"] - m["from"])
    d = speed * max(0.0, t - 0.0)
    ramp = min(0.35, seconds / 4)
    if t < ramp:
        d = speed * t * t / (2 * ramp)
        v = t / ramp
    else:
        d = speed * (t - ramp / 2)
        v = 1.0
    stop = 0.9 * speed  # (slowing over the last ~0.9 of a second's distance)
    if d > length - stop / 2:
        over = d - (length - stop / 2)
        q = min(1.0, over / stop)
        d = length - stop / 2 + stop / 2 * (1 - (1 - q) ** 2)
        v *= max(0.0, 1 - q)
        if q >= 1:
            d, v = length, 0.0
    sign = 1 if m["to"] >= m["from"] else -1
    return m["from"] + sign * min(d, length), v


def _step_len(R, run=False):
    leg = 2.84 * R * 0.985
    return 2 * leg * math.sin(0.70 if run else 0.40)


def _ev(p, t):
    """The event's progress: seconds since it (negative before)."""
    return t - p["event_at"]


def person_at(p: dict, m: dict, pose_name: str, t: float, look_key: str, mood: str | None, is_him: bool,
              seed: int) -> dict:
    """One person's pose and eyes at t: an actor for the place ({"pose", "look", "eyes", "slot"})."""
    R0 = p["R"]
    look = S.LOOKS[look_key]
    R = R0 * look.size
    ground = p["ground"]
    f = m.get("f", 1)
    seconds = p["seconds"]
    ev, et = (p["event"], _ev(p, t)) if is_him else ("none", -1.0)
    breath = 0.03 * math.sin(math.tau * 0.24 * t + seed)
    blink = _blink(t, seed)
    lift = m.get("lift", 0.0) + breath
    eye_look = [f * 1.0, 0.0]
    kind = m["kind"]
    outdoors = p["set"] in OUTDOORS
    defaults = {"typing": "tired", "slumped": "sad", "phone": "tired", "lying_awake": "tired", "asleep": "closed",
                "floor": "sad", "head_in_hands": "closed", "pushups": "determined", "running": "determined"}
    mood = mood or defaults.get(pose_name, "open")
    slump = 0.85 if pose_name in ("slumped",) else (0.30 if pose_name == "floor" else 0.0)
    if mood == "sad" and pose_name in ("standing", "walking"):
        slump = max(slump, 0.35)
    # the event's motion
    turn = 0.0
    if ev == "head_turn" and et >= 0:
        turn = S.ease_out(S.window(et, 0.0, 0.22), 3)
        w = S.window(et, 0.0, 0.26)
        lift += -0.20 * math.sin(math.pi * w) * (1 - w * 0.3)
    if ev == "look_up" and et >= 0:
        q = S.ease_in_out(S.window(et, 0.0, 0.9))
        lift += 0.85 * q
        eye_look[1] -= 0.75 * q
    if ev == "look_down" and et >= 0:
        q = S.ease_in_out(S.window(et, 0.0, 0.9))
        lift -= 0.6 * q
        eye_look[1] += 0.6 * q
    if ev == "nod" and 0 <= et < 1.3:
        lift -= 0.28 * max(0.0, math.sin(math.tau * et / 0.62)) * (1 - et / 1.3)
    open_scale = 1.0
    if ev == "eyes_open":
        open_scale = S.smooth(S.window(et, 0.0, 0.7))
    if ev == "eyes_close":
        open_scale = 1 - S.smooth(S.window(et, 0.0, 0.9))
    slot = "main"
    # the pose
    if kind in ("walk", "run"):
        running = kind == "run" or pose_name == "running"
        box = pose_name == "carrying_box" or m.get("arms") == "box"
        speed = RUN_SPEED if running else (BOX_SPEED if box else WALK_SPEED)
        x, v = _walked(m, t, seconds, speed)
        d = abs(x - m["from"])
        phase = math.pi * d / _step_len(R, running) + seed
        arms = "box" if box else ("run" if running else ("pockets" if p["rain"] and is_him else "hang"))
        pose = S.pose_stand(x, ground, f, R, slump=slump * 0.6, lift=lift, arms=arms, walk=v if not running else 0.0,
                            phase=phase, run=v if running else 0.0, hood_up=p["rain"] and look.hood and outdoors)
    elif kind == "stand":
        arms = m.get("arms") or ("pockets" if pose_name == "at_window" else "hang")
        if pose_name == "phone":
            arms = "phone"
        if not is_him:
            arms = {"offering": "offer", "arms_crossed": "cross"}.get(m.get("how"), m.get("arms") or "hang")
        knock = et if (ev == "knock" and 0 <= et < 1.6) else 0.0
        pose = S.pose_stand(m["x"], ground, f, R, slump=slump, lift=lift, arms=arms,
                            hood_up=p["rain"] and look.hood and outdoors, knock=knock)
    elif kind == "sit":
        arms = {"typing": "type", "head_in_hands": "head", "phone": "phone"}.get(pose_name, "lap")
        if arms == "lap" and m.get("reach") and pose_name in ("sitting", "slumped"):
            arms = "desk"
        pose = S.pose_sit(m["x"], m["seat"], ground, f, R, slump=slump, lift=lift, arms=arms, reach=m.get("reach"),
                          tap=t)
    elif kind == "floor":
        pose = S.pose_floor(m["x"], ground, f, R, slump=0.25 + (0.7 if mood in ("closed",) else 0.0), lift=lift)
    elif kind == "lie":
        pose = S.pose_lie(m["x"], m["y"], f, R, arms="phone" if pose_name in ("lying_awake", "phone") else "rest")
        eye_look = [0.3 * f, -0.8]
        slot = m.get("slot", "main")
    elif kind == "pushup":
        pose = S.pose_pushup(m["x"], ground, f, R, phase=math.tau * t / 1.7 + seed)
        eye_look = [f * 1.0, 0.35]
    else:
        raise ValueError(f"no pose kind {kind!r}")
    if ev == "shake_head" and 0 <= et < 1.6:
        hx, hy = pose["head"]
        pose["head"] = (hx + f * 0.10 * R * math.sin(math.tau * et / 0.55) * (1 - et / 1.6), hy)
    # the eyes
    if pose.get("face_hidden"):
        eyes = None
    else:
        lx, ly = eye_look[0] * (1 - turn), eye_look[1] * (1 - turn)
        e = S.eyes_for(mood, (lx, ly), look.gap, blink * open_scale)
        if ev == "head_turn" and et >= 0:
            wide = S.spring(S.window(et, 0.08, 0.7))
            e.open = min(1.0, e.open + (1.0 - e.open) * wide) * blink
            e.size = 1.0 + 0.22 * wide
        eyes = e
    return {"pose": pose, "look": look, "eyes": eyes, "slot": slot}


def _walker_x(p: dict, t: float):
    m = p["mark"]
    if not m or m["kind"] not in ("walk", "run"):
        return None
    running = m["kind"] == "run" or p["him"] == "running"
    speed = RUN_SPEED if running else (BOX_SPEED if p["him"] == "carrying_box" else WALK_SPEED)
    return _walked(m, t, p["seconds"], speed)[0]


def camera_at(p: dict, obj, t: float) -> tuple:
    """The camera (cx, cy, z) at t: the shot's move from the place's resting framing, eased; outdoors it follows a
    walker or a runner."""
    cx0, cy0, z0 = obj.cam.rest
    seconds = p["seconds"]
    u = S.ease_out(S.window(t, 0.0, seconds), 1.6)
    head = None
    if p["mark"] and p["mark"]["kind"] not in ("walk", "run"):
        hx = p["mark"].get("x")
        head = (hx, p["ground"] - 6.2 * p["R"]) if hx is not None else None
    pan_limit = float(getattr(obj, "PAN", (0.0, 0.0))[0])
    move = p["camera"]
    cx, cy, z = cx0, cy0, z0
    if p["set"] == "desk_room":
        import silhouette_sets as sets
        fx, fy = sets.FOCUS
        k = {"push_in": 0.30, "hold": 0.10, "pull_out": 0.0, "pan_left": 0.10, "pan_right": 0.10}[move]
        zk = {"push_in": 0.06, "hold": 0.015, "pull_out": 0.0, "pan_left": 0.02, "pan_right": 0.02}[move]
        if move == "pull_out":
            return (cx0 + (fx - cx0) * 0.3 * (1 - u), cy0 + (fy - cy0) * 0.3 * (1 - u), z0 * (1 + 0.06 * (1 - u)))
        return (cx0 + (fx - cx0) * k * u, cy0 + (fy - cy0) * k * u, z0 * (1 + zk * u))
    if move == "push_in":
        z = z0 * (1 + 0.07 * u)
        if head:
            cx, cy = cx0 + (head[0] - cx0) * 0.35 * u, cy0 + (head[1] - cy0) * 0.25 * u
    elif move == "pull_out":
        z = z0 * (1 + 0.07 * (1 - u))
        if head:
            cx, cy = cx0 + (head[0] - cx0) * 0.35 * (1 - u), cy0 + (head[1] - cy0) * 0.25 * (1 - u)
    elif move in ("pan_left", "pan_right"):
        span = min(140.0, pan_limit * 0.9) if pan_limit else 50.0
        d = (-1 if move == "pan_left" else 1) * span
        cx = cx0 - d / 2 + d * u
        z = z0 * 1.02
    else:
        z = z0 * (1 + 0.012 * u)
    wx = _walker_x(p, t)
    if wx is not None and pan_limit > 300:  # outdoors: follow him (three quarters of his way), a little behind
        mid = (p["mark"]["from"] + p["mark"]["to"]) / 2
        shift = (wx - mid) * 0.75 / 0.70
        cx = cx0 + max(-pan_limit * 0.95, min(pan_limit * 0.95, shift))
    return (cx, cy, z)


def state(p: dict, obj, t: float, index: int, flags: dict) -> dict:
    """Everything that moves in a shot at t (its plan p, its place obj): the place's st."""
    seconds = p["seconds"]
    still = bool(flags.get("still_from") is not None and t >= flags["still_from"])
    tt = min(t, flags["still_from"]) if still else t
    st = {"cam": camera_at(p, obj, tt), "tau": flags.get("t0", 0.0) + tt, "still": still}
    seed = p["seed"]
    actors = []
    if p["mark"] and p["set"] != "desk_room":
        actors.append(person_at(p, p["mark"], p["him"], tt, "him", p["mood"], True, seed))
    for m in p["others"]:
        if p["set"] == "hospital" and m["who"] == "mother":
            continue
        who = m["who"] if m["who"] != "crowd" else ("stranger" if m["k"] % 2 == 0 else "friend")
        pose_name = {"sitting": "sitting", "leaving": "walking", "lying": "asleep"}.get(m["how"], "standing")
        actors.append(person_at(p, m, pose_name, tt, who, p["other_mood"], False, seed + 31 * (m["k"] + 1)))
    st["actors"] = actors
    # the label: pops in at 0.4 s; in a long shot it fades out again after 4 s
    if p["label"] and not flags.get("no_label"):
        q = S.window(tt, 0.4, 0.68)
        gone = S.window(tt, 4.4, 5.0) if seconds > 6.5 else 0.0
        st["label"] = (p["label"], q, gone)
    # the lamp, the fades
    lamp = 1.0
    et = _ev(p, tt)
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
    # the places' own moving parts
    if p["set"] == "desk_room":
        _desk_state(p, st, tt, seed)
    elif p["set"] == "hospital":
        st["beat"] = st["tau"]
        mother = next((m for m in p["others"] if m["who"] == "mother"), None)
        wake = 0.0
        if mother is not None:
            wake = 1.0 if p["other_mood"] not in ("closed",) else 0.0
        her_blink = _blink(tt, seed + 11)
        st["her_eyes"] = S.Eyes(look=(1.0 * wake, -0.25 * wake), open_=0.55 * wake * her_blink, tilt=0.25, gap=0.44)
        st["her_turn"] = wake
    elif p["set"] == "street":
        st["rain"] = st["tau"]
    return st


def _desk_state(p: dict, st: dict, t: float, seed: int):
    """The desk room's moment: his GIF-drawn figure at the desk (typing, idle, slumped, his head in his hands, his phone),
    the clock, the city's windows, the dust."""
    pose = p["him"]
    mood = p["mood"] or {"typing": "tired", "slumped": "sad", "phone": "tired", "head_in_hands": "closed"}.get(pose, "open")
    arm = {"typing": "type", "head_in_hands": "head", "phone": "phone"}.get(pose, "rest")
    head = {"slumped": (7.0, 22.0), "head_in_hands": (18.0, 50.0), "phone": (4.0, 8.0)}.get(pose, (0.0, 0.0))
    tap = (0.0, 0.0)
    if arm == "type":
        k = int(t * 12)
        tap = ((k % 3 - 1) * 1.2, -2.2 if k % 2 else 0.0)
    ev, et = p["event"], _ev(p, t)
    look = [1.18, -0.05 + (0.35 if arm == "phone" else 0.0)]
    blink = _blink(t, seed)
    e = S.eyes_for(mood, tuple(look), 0.44, blink)
    if ev == "head_turn" and et >= 0:
        if arm == "type":
            tap = (0.0, 0.0)
        turn = S.ease_out(S.window(et, 0.0, 0.2), 3)
        w = S.window(et, 0.0, 0.24)
        head = (head[0] - 3 * turn, head[1] - 6 * math.sin(math.pi * w) * (1 - w * 0.3) - 2 * turn)
        wide = S.spring(S.window(et, 0.08, 0.73))
        e = S.Eyes(look=(1.18 * (1 - turn), -0.05 + 0.02 * turn), open_=min(1.0, e.open + (1.0 - e.open) * wide) * blink,
                   size=1.0 + 0.22 * wide, tilt=e.tilt * (1 - wide), gap=0.44 + 0.04 * turn)
    if ev in ("eyes_close",) and et >= 0:
        e.open *= 1 - S.smooth(S.window(et, 0.0, 0.9))
    if ev == "eyes_open":
        e.open *= S.smooth(S.window(et, 0.0, 0.7))
    if ev == "look_down" and et >= 0:
        q = S.ease_in_out(S.window(et, 0.0, 0.9))
        head = (head[0] + 6 * q, head[1] + 16 * q)
    if ev == "look_up" and et >= 0:
        q = S.ease_in_out(S.window(et, 0.0, 0.9))
        head = (head[0] - 2 * q, head[1] - 6 * q)
        e.look = (e.look[0], e.look[1] - 0.6 * q)
    st.update({"tap": tap, "head": head, "eyes": e, "arm": arm, "breath": math.sin(t * math.tau * 0.25)})
    # the clock: the shot's time ("HH:MM", or 21:59), turning a minute at the event
    hh, mm = 21, 59
    try:
        hh, mm = (int(x) for x in p["clock"].split(":"))
    except (ValueError, AttributeError):
        pass
    flips = []
    if ev == "clock_flip":
        nh, nm = (hh + (mm + 1) // 60) % 24, (mm + 1) % 60
        at = p["event_at"]
        flips.append({"page": "R", "at": at, "from": f"{mm:02d}", "to": f"{nm:02d}"})
        if nh != hh:
            flips.append({"page": "L", "at": at + 0.22, "from": f"{hh:02d}", "to": f"{nh:02d}"})
    else:
        flips.append({"page": "R", "at": 1e9, "from": f"{mm:02d}", "to": f"{mm:02d}"})
        flips.append({"page": "L", "at": 1e9, "from": f"{hh:02d}", "to": f"{hh:02d}"})
    st["flips"], st["clock_t"] = flips, t
    base = {"dusk": 0, "night": 3, "dawn": -1, "day": -1}[p["light"]]
    if ev == "lights_on" and p["light"] == "dusk":
        base = sum(t >= p["event_at"] + d for d in (0.0, 0.13, 0.26))
    st["windows"] = base
    st["dust"] = st["tau"]


# --- type: the title card, the closing line, the short version's title, the thumbnail's words ------------------------------------
@lru_cache(maxsize=32)
def type_sprite(words: str, px: int, max_width: int, spacing: float = 0.22, glow: float = 0.55) -> np.ndarray:
    """Words in the look's type (Oswald SemiBold capitals, widely spaced, warm white with a faint red glow), wrapped to
    max_width, centred (premultiplied RGBA)."""
    words = " ".join(str(words).upper().split())
    f = S.font("Oswald[wght].ttf", px, "SemiBold")
    gap = px * spacing

    def width(s):
        return sum(f.getlength(ch) for ch in s) + gap * max(0, len(s) - 1)
    lines, cur = [], ""
    for w in words.split():
        trial = (cur + " " + w).strip()
        if cur and width(trial) > max_width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) == 2 and len(words.split()) > 2:  # balance two lines
        ws = words.split()
        best = min(range(1, len(ws)), key=lambda k: abs(width(" ".join(ws[:k])) - width(" ".join(ws[k:]))))
        lines = [" ".join(ws[:best]), " ".join(ws[best:])]
    lh = int(px * 1.35)
    W = int(max(width(s) for s in lines) + px * 2)
    Hh = int(lh * len(lines) + px * 0.9)
    mask = Image.new("L", (W, Hh), 0)
    d = ImageDraw.Draw(mask)
    for k, s in enumerate(lines):
        x = (W - width(s)) / 2
        for ch in s:
            d.text((x, px * 0.25 + k * lh), ch, font=f, fill=255)
            x += f.getlength(ch) + gap
    m = np.asarray(mask, np.float32) / 255.0
    g = np.asarray(mask.filter(ImageFilter.GaussianBlur(px * 0.22)), np.float32) / 255.0 * glow
    out = np.zeros((Hh, W, 4), np.float32)
    out[..., :3] = S.PAL["rim"] * g[..., None]
    out[..., 3] = g
    out[..., :3] = out[..., :3] * (1 - m[..., None]) + S.PAL["label"] * m[..., None]
    out[..., 3] = out[..., 3] * (1 - m) + m
    return out


def _sub_font(px: int):
    return S.font("Oswald[wght].ttf", px, "Regular")


def sub_rows(text: str, px: int, max_width: int, tall: bool) -> list[str] | None:
    """A subtitle's rows: one (the film's band holds one), or in the short version two balanced ones when one is too
    long; None when it doesn't fit (tools/subtitles.split cuts a line into cues that do)."""
    f = _sub_font(px)
    most = SUB_TALL_CHARS if tall else SUB_CHARS
    if len(text) <= most and f.getlength(text) <= max_width:
        return [text]
    ws = text.split()
    if not tall or len(ws) < 2:
        return None
    k = min(range(1, len(ws)), key=lambda k: max(f.getlength(" ".join(ws[:k])), f.getlength(" ".join(ws[k:]))))
    rows = [" ".join(ws[:k]), " ".join(ws[k:])]
    return rows if all(len(r) <= most and f.getlength(r) <= max_width for r in rows) else None


def _sub_box(size) -> tuple[int, int, bool]:
    """The subtitles' type size, most width and whether it's the short version's, for a frame size."""
    W, H = size
    tall = H > W
    return (int(round((SUB_TALL_PX if tall else SUB_PX) * min(W, H) / 1080)),
            int(W * (SUB_TALL_WIDTH if tall else SUB_WIDTH)), tall)


@lru_cache(maxsize=96)
def sub_sprite(text: str, px: int, max_width: int, tall: bool) -> np.ndarray:
    """A subtitle in the look's type (Oswald, warm white), centred on its capitals' middle; the short version's on a
    soft dark halo, as it lies over the picture (premultiplied RGBA)."""
    f = _sub_font(px)
    rows = sub_rows(text, px, max_width, tall) or [text]
    cap = -f.getbbox("H", anchor="ls")[1]           # the capitals' height over the baseline
    gap = int(round(px * 0.62))                      # between two rows (the descenders' room)
    pad_x, pad_y = int(px * (1.0 if tall else 0.4)), int(px * (1.0 if tall else 0.45))
    W = int(max(f.getlength(r) for r in rows)) + 2 * pad_x
    H = 2 * pad_y + cap * len(rows) + gap * (len(rows) - 1)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    for i, r in enumerate(rows):
        d.text((W / 2, pad_y + cap + i * (cap + gap)), r, font=f, fill=255, anchor="ms")
    m = np.asarray(mask, np.float32) / 255.0
    out = np.zeros((H, W, 4), np.float32)
    if tall:
        halo = np.asarray(mask.filter(ImageFilter.GaussianBlur(px * 0.55)), np.float32) / 255.0
        out[..., 3] = np.clip(halo * 2.6, 0, 1) * 0.70
    out[..., :3] = S.PAL["label"] * m[..., None]
    out[..., 3] = out[..., 3] * (1 - m) + m
    return out


def subtitle_cues(story: dict, times: list[dict], voice: list[dict] | None, size) -> list[dict]:
    """The story's subtitles for a frame size (tools/subtitles.cues, fitted to its type and band)."""
    import subtitles

    px, max_width, tall = _sub_box(size)
    return subtitles.cues(story["shots"], times, voice, lambda s: sub_rows(s, px, max_width, tall) is not None,
                          story.get("closing_line") or "")


def _subtitle(frame, size, t, subs):
    cue = next((c for c in subs if c[0] <= t < c[1]), None)
    if not cue:
        return
    on, off, text, first, last = cue
    q = (S.smooth((t - on) / 0.12) if first else 1.0) * (S.smooth((off - t) / 0.15) if last else 1.0)
    W, H = size
    px, max_width, tall = _sub_box(size)
    y = H * SUB_TALL_Y if tall else H - round(min(W, H) * S.BARS) / 2
    S.paste(frame, sub_sprite(text, px, max_width, tall), W / 2, y, opacity=q)


def _dim(frame, a):
    if a > 0:
        frame *= 1 - a


def closing_place(p: dict, obj, size, flags: dict) -> dict:
    """An upright frame's closing line, off everyone in its shot when it can be (2026-11-24: always 72% down, it lay over
    him): {"closing_y": its middle (px), "closing_dim": a soft dark band behind it, when it can't be}. {}: its usual
    place (a wide frame; a shot without the closing line)."""
    W, H = size
    if not flags.get("closing") or W >= H or not p.get("composed"):
        return {}
    import silhouette_board as SB

    st = SB.state(p, obj, float(flags.get("closing_at") or 0.0) + 0.6, {"t0": 0.0, **flags, "no_bubbles": True})
    people = SB.screen_boxes(obj, st)
    spr = type_sprite(flags["closing"], int(CLOSING_PX * min(W, H) / 1080), int(W * 0.82), 0.30)
    h, w = spr.shape[:2]
    bar = S.BARS * min(W, H)
    lo, hi = bar + 0.035 * H + h / 2, H - bar - 0.10 * H - h / 2   # (off the bars; above YouTube's words at the bottom)
    best = None
    for rank, share in enumerate((0.72, 0.17, 0.62, 0.28, 0.80)):
        y = min(max(share * H, lo), hi)
        box = (W / 2 - w / 2, y - h / 2, W / 2 + w / 2, y + h / 2)
        hit = sum(max(0.0, min(box[2], b[2]) - max(box[0], b[0])) * max(0.0, min(box[3], b[3]) - max(box[1], b[1]))
                  for b in people) / float(w * h)
        if best is None or hit + 0.004 * rank < best[0]:
            best = (hit + 0.004 * rank, y, hit)
    return {"closing_y": best[1], "closing_dim": best[2] > 0.03}


def _band(frame, y, h, a):
    """A soft dark band across the frame round y (words over someone, still readable)."""
    H = frame.shape[0]
    d = np.abs(np.arange(H, dtype=np.float32) - y) / (h * 0.5 + 0.05 * H)
    frame *= (1.0 - a * np.clip(1.0 - d, 0.0, 1.0) ** 0.6)[:, None, None]


def overlays(frame, size, t, flags):
    """The closing line (the last shot) and a narrated film's subtitles. (The title card and the short version's title at
    the top are drawn only when a shot's flags ask for them: none does since 2026-11-20.)"""
    W, H = size
    k = min(W, H) / 1080
    if flags.get("title"):
        a, b = flags["title_span"]
        q = S.smooth(S.window(t, a, a + 0.8)) * (1 - S.smooth(S.window(t, b - 0.7, b)))
        if q > 0:
            _dim(frame, 0.35 * q)
            spr = type_sprite(flags["title"], int(TITLE_PX * k), int(W * 0.80), 0.20)
            S.paste(frame, spr, W / 2, H * (0.30 if W > H else 0.24), scale=0.96 + 0.04 * q, opacity=q)
    if flags.get("closing"):
        a = flags["closing_at"]
        q = S.smooth(S.window(t, a, a + 0.9))
        if q > 0:
            spr = type_sprite(flags["closing"], int(CLOSING_PX * k), int(W * 0.82), 0.30)
            y = flags.get("closing_y") or H * (0.80 if W > H else 0.72)   # (upright: off everyone, closing_place)
            if flags.get("closing_dim"):
                _band(frame, y, spr.shape[0], 0.45 * q)
            S.paste(frame, spr, W / 2, y, opacity=q)
    if flags.get("top_title"):  # (the short version's: at the top while its first line hooks, gone before its shot ends)
        end = min(4.2, float(flags.get("top_title_until") or 4.2))
        q = S.smooth(S.window(t, 0.2, 0.8)) * (1 - S.smooth(S.window(t, end - 0.6, end)))
        if q > 0:
            spr = type_sprite(flags["top_title"], int(78 * k), int(W * 0.86), 0.18)
            S.paste(frame, spr, W / 2, H * 0.17, opacity=q)
    if flags.get("subs"):
        _subtitle(frame, size, t, flags["subs"])


# --- drawing a shot ------------------------------------------------------------------------------------------------------------
def frames(job: dict):
    """Yields a shot's frames (float RGB), from job: {"plan", "flags", "size", "n", "index0"}."""
    p, flags, size = job["plan"], job["flags"], tuple(job["size"])
    if job.get("visuals"):   # (a drawing process of its own: the story's made visuals join its library first)
        import visual_recipes

        visual_recipes.register(job["visuals"])
    if p.get("composed"):   # (a place of the story's own: tools/silhouette_board.py)
        import silhouette_board as SB

        obj = SB.place_for(p, size)
        flags = {**flags, **closing_place(p, obj, size, flags)}
        for i in range(job["n"]):
            t = i / FPS
            frame = obj.frame(job["index0"] + i, SB.state(p, obj, t, flags))
            overlays(frame, size, t, flags)
            yield frame
        return
    obj = place(p["set"], size, p["light"], p["rain"], p.get("center"), p.get("open_door", False))
    for i in range(job["n"]):
        t = i / FPS
        st = state(p, obj, t, job["index0"] + i, flags)
        if p["set"] == "desk_room":
            frame = obj.draw(job["index0"] + i, st)
        else:
            frame = obj.frame(job["index0"] + i, st)
        overlays(frame, size, t, flags)
        yield frame


def _encoder(path: Path, size) -> subprocess.Popen:
    import media

    W, H = size
    return subprocess.Popen([media.ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                             f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                             "-threads", "2", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)


def _shot_video(job: dict) -> str:
    import cv2

    cv2.setNumThreads(1)   # (the processes share the cores: one thread each, or they fight over them)
    out = Path(job["out"])
    enc = _encoder(out, job["size"])
    for frame in frames(job):
        enc.stdin.write(S.to_bytes(frame))
    enc.stdin.close()
    if enc.wait():
        raise RuntimeError(f"encoding shot {job['k']} failed")
    return str(out)


def workers() -> int:
    """Drawing processes: one a core, at most 6 (each holds one place's layers, a few hundred MB)."""
    import os

    return max(1, min(6, os.cpu_count() or 2))


def jobs_for(story: dict, times: list[dict], size, folder: Path, short: bool = False, subs: list[dict] | None = None):
    """Every shot's drawing job: its plan, its fades and texts, its frames. The film and its short version (short:
    story_film.short_story's) begin straight with the story (no title in the picture) and end on the closing line, the
    last second still. A shot keeps its seed when it has one (the short version's: drawn as in the film). subs: the subtitles
    (subtitle_cues), each shot given its own, in its own seconds."""
    all_shots = story["shots"]
    n = len(all_shots)
    out, index0 = [], 0
    for k in range(n):
        t = times[k]
        shot = {**all_shots[k], "seed": all_shots[k].get("seed", k * 101 + 7), "seconds": t["seconds"],
                "bubbles": t.get("bubbles") or []}   # (its bubbles timed for reading: tools/story_film.timeline)
        frames_n = max(1, round(t["seconds"] * FPS))
        p = plan_for(story, shot, size)
        flags = {"t0": t["start"]}
        mine = [(c["on"] - t["start"], c["off"] - t["start"], c["text"], c["first"], c["last"])
                for c in subs or [] if c["shot"] == k]
        if mine:
            flags["subs"] = mine
        nxt = all_shots[k + 1] if k + 1 < n else None
        if k == 0 or all_shots[k].get("enter") in ("fade", "lights_out"):
            flags["fade_in"] = (0.3 if short else 0.6) if k == 0 else 0.45
        if nxt is not None and nxt.get("enter") == "fade":
            flags["fade_out"] = 0.45
        if nxt is not None and nxt.get("enter") == "lights_out":
            flags["lights_out_at"] = max(0.0, t["seconds"] - 0.55)
        if k == n - 1:
            flags["closing"] = story.get("closing_line") or ""
            flags["closing_at"] = t["closing_at"] if t.get("closing_at") is not None else 0.8
            flags["still_from"] = max(0.0, t["seconds"] - 1.0)
            flags["fade_out"] = 0.9
        out.append({"k": k, "plan": p, "flags": flags, "size": list(size), "n": frames_n, "index0": index0,
                    "out": str(folder / f"shot_{k:03d}.mp4"), "visuals": story.get("visuals") or []})
        index0 += frames_n
    return out


def draw_video(jobs: list[dict], out: Path, progress=print) -> Path:
    """The jobs drawn in parallel, joined without re-encoding (silent)."""
    import multiprocessing  # (spawn: on Linux a forked worker can freeze on a lock another thread held; 2026-11-21 #10)
    from concurrent.futures import ProcessPoolExecutor

    import media

    done = 0
    with ProcessPoolExecutor(max_workers=max(1, min(workers(), len(jobs))),
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        for _ in pool.map(_shot_video, jobs):
            done += 1
            if done % 4 == 0 or done == len(jobs):
                progress(f"{done} of {len(jobs)} shots drawn")
    listing = out.parent / (out.stem + "_shots.txt")
    listing.write_text("".join(f"file '{Path(j['out']).as_posix()}'\n" for j in jobs), encoding="utf-8")
    subprocess.run([media.ffmpeg_exe(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c",
                    "copy", str(out)], check=True, timeout=600)
    listing.unlink(missing_ok=True)
    return out


# --- the sound ------------------------------------------------------------------------------------------------------------------
BEDS = {"desk_room": "room_quiet", "bedroom": "room_quiet", "kitchen": "room_quiet", "hallway": "room_quiet",
        "street": "night_street", "hospital": "room_quiet", "office": "room_quiet", "cafe": "crowd_murmur",
        "rooftop": "wind_soft", "park": "dawn_birds", "bright_office": "room_quiet", "new_flat": "room_quiet"}
BED_GAIN = {"rain_bed": -4, "rain_window": -6, "night_street": -8, "room_quiet": -8, "dawn_birds": -6, "wind_soft": -7,
            "crickets": -9, "crowd_murmur": -16}
SOUND = {  # each single sound's level (dB, film_sound's standard), and how it plays
    "alarm_clock": {"gain": -3, "from": 3.25, "dur": 2.2}, "clock_tick": {"gain": -10, "loop": True},
    "keyboard_typing": {"gain": -12, "loop": True}, "running_steps": {"gain": -8, "loop": True},
    "heartbeat": {"gain": -2}, "thunder_far": {"gain": -5}, "car_pass_wet": {"gain": -6}, "train_pass": {"gain": -7},
    "footstep": {"gain": -8}, "footstep_wet": {"gain": -8}, "water_drop": {"gain": -6}, "door_close": {"gain": -5},
    "gate_close": {"gain": -5}, "phone_buzz": {"gain": -5}, "keys_jingle": {"gain": -4}, "switch_click": {"gain": -6},
    "page_turn": {"gain": -6}, "page_flip": {"gain": -12, "dur": 0.35}, "glass_set_down": {"gain": -6},
    "paper_rip": {"gain": -5}, "wind_howl": {"gain": -6}, "monitor_beep": {"gain": -15}, "door_knock": {"gain": -6},
    "bubble_pop": {"gain": -15},
}


def _sound(tag, at, seconds):
    how = SOUND.get(tag, {"gain": -6})
    at = min(float(at), max(0.0, seconds - 0.3))
    out = {"tag": tag, "at": round(at, 2), "gain": how["gain"]}
    if how.get("from"):
        out["from"] = how["from"]
    if how.get("dur"):
        out["dur"] = how["dur"]
    elif how.get("loop"):
        out["dur"] = round(max(0.5, seconds - at), 2)
    return out


KIND_BEDS = {"room": "room_quiet", "hall": "room_quiet", "corridor": "room_quiet", "street": "night_street",
             "houses": "wind_soft", "bridge": "wind_soft", "nature": "wind_soft", "car": "night_street",
             "bus": "night_street", "train": "wind_soft"}


def _composed_sound(story_shot: dict, p: dict, seconds: float, beds_db: float) -> dict:
    """A storyboard shot's sound: its place's bed (birds by day in nature and the houses' streets, crickets at dusk and
    night, a crowd in a hall with an audience or a party), rain, the story's single sounds, and what the people do
    (steps, typing, running, knocking, a page, the lamp's switch, the phone, a heart monitor's beeps)."""
    import silhouette_actions as A

    kind, spec, light = p["kind"], p["spec"], p["light"]
    things = set(spec.get("things") or [])
    bed = story_shot.get("bed") or KIND_BEDS.get(kind, "room_quiet")
    if kind in ("nature", "houses") and light in ("dusk", "night"):
        bed = "crickets"
    elif kind in ("nature", "houses") and spec.get("nature") not in ("sea", "mountains"):
        bed = "dawn_birds"
    if kind == "hall" and ("audience" in things or "party" in (spec.get("effects") or [])):
        bed = "crowd_murmur"
    beds = [{"tag": bed, "gain": BED_GAIN.get(bed, -8) + beds_db}]
    if p["weather"] == "rain":
        rain = "rain_bed" if kind in ("street", "houses", "bridge", "nature") else "rain_window"
        if rain != bed:
            beds.append({"tag": rain, "gain": BED_GAIN[rain] + beds_db})
    sounds = [_sound(ev["tag"], ev.get("at", 0), seconds) for ev in story_shot.get("sounds") or []]
    for q in p["people"]:
        m, action = q["mark"], q["action"]
        if m.get("kind") in ("walk", "run") and "from" in m:
            running = action == "running" or m.get("kind") == "run"
            if running:
                sounds.append(_sound("running_steps", 0.0, seconds))
                continue
            speed = BOX_SPEED if action == "carrying_box" else WALK_SPEED
            step, k = _step_len(p["R"]), 1
            for i in range(1, int(seconds * 50)):
                x, _ = A._walk_x(m, i / 50, seconds, speed)
                if abs(x - m["from"]) >= k * step:
                    sounds.append(_sound("footstep_wet" if p["weather"] == "rain" else "footstep", i / 50, seconds))
                    k += 1
        elif q["who"] == "him":
            if action in ("typing",):
                sounds.append(_sound("keyboard_typing", 0.2, seconds))
            elif action in ("running", "treadmill"):
                sounds.append(_sound("running_steps", 0.0, seconds))
            elif action == "at_door":
                sounds += [_sound("door_knock", 0.3 + d, seconds) for d in (0.0, 0.38, 0.76)]
            elif action in ("reading", "letter"):
                sounds.append(_sound("page_turn", min(1.2, seconds * 0.3), seconds))
    for b in p.get("bubbles") or []:   # (a soft pop as each bubble comes)
        if b.get("start", 0.0) < seconds - 0.2:
            sounds.append(_sound("bubble_pop", b["start"] + 0.02, seconds))
    ev, at = p["event"], p["event_at"]
    if ev == "lamp_off":
        sounds.append(_sound("switch_click", at, seconds))
    if ev == "phone_buzz":
        sounds.append(_sound("phone_buzz", at, seconds))
    if "heart_monitor" in things:
        import silhouette_sets as sets
        sounds += [_sound("monitor_beep", b, seconds) for b in sets.HospitalRoom.beeps(0.0, seconds)]
    return {"seconds": seconds, "beds": beds, "sounds": sounds}


def shot_sound(story_shot: dict, p: dict, seconds: float, beds_db: float = 0.0) -> dict:
    """A shot's sound: its bed (the story's choice, or the place's), rain, the story's single sounds, and what the
    picture makes happen (steps, the clock's pages, the lamp's switch, the monitor's beeps, knocks)."""
    if p.get("composed"):
        return _composed_sound(story_shot, p, seconds, beds_db)
    bed = story_shot.get("bed") or BEDS.get(p["set"], "room_quiet")
    if p["set"] == "park" and p["light"] in ("night", "dusk"):
        bed = "crickets"
    beds = [{"tag": bed, "gain": BED_GAIN.get(bed, -8) + beds_db}]
    if p["rain"]:
        rain = "rain_bed" if p["set"] in ("street", "park", "rooftop") else "rain_window"
        if rain != bed:
            beds.append({"tag": rain, "gain": BED_GAIN[rain] + beds_db})
    sounds = [_sound(ev["tag"], ev.get("at", 0), seconds) for ev in story_shot.get("sounds") or []]
    m, ev, at = p["mark"], p["event"], p["event_at"]
    if m and m["kind"] in ("walk", "run"):
        running = m["kind"] == "run" or p["him"] == "running"
        if running:
            sounds.append(_sound("running_steps", 0.0, seconds))
        else:
            speed = BOX_SPEED if p["him"] == "carrying_box" else WALK_SPEED
            step = _step_len(p["R"], False)
            k = 1
            for i in range(1, int(seconds * 50)):
                tt = i / 50
                x, _ = _walked(m, tt, seconds, speed)
                if abs(x - m["from"]) >= k * step:
                    sounds.append(_sound("footstep_wet" if p["rain"] else "footstep", tt, seconds))
                    k += 1
    if p["him"] == "typing":
        sounds.append(_sound("keyboard_typing", 0.2, seconds))
    if ev == "clock_flip":
        sounds += [_sound("page_flip", at, seconds), _sound("page_flip", at + 0.22, seconds)]
    if ev == "lamp_off":
        sounds.append(_sound("switch_click", at, seconds))
    if ev == "phone_buzz":
        sounds.append(_sound("phone_buzz", at, seconds))
    if ev == "knock":
        sounds += [_sound("door_knock", at + d, seconds) for d in (0.0, 0.38, 0.76)]
    if p["set"] == "hospital":
        import silhouette_sets as sets
        sounds += [_sound("monitor_beep", b, seconds) for b in sets.HospitalRoom.beeps(0.0, seconds)]
    return {"seconds": seconds, "beds": beds, "sounds": sounds}


def music_spec(story: dict, times: list[dict]) -> dict | None:
    """The music: low from the first second (no voice to leave room for: the pictures and the bubbles need its mood),
    lifting at his realization (the storyboard's shot) and swelling to the end."""
    if not story.get("music"):
        return None
    k = story.get("realization")
    if k is None or not 0 <= int(k) < len(times):
        k = next((i for i, s in enumerate(story["shots"]) if s.get("act") in ("spark", "transformation")), None)
    lift_at = times[int(k)]["start"] + 0.4 if k is not None else None
    return {"file": story["music"], "at": 0.0, "from": float(story.get("music_from") or 0.0), "rise": 3.0,
            "low": -9.0 if lift_at is not None else 0.0, "lift_at": lift_at, "lift": 6.0, "swell": 3.0,
            "swell_s": 20.0, "gain": 2.0}


# --- the film, the short version, the thumbnail ---------------------------------------------------------------------------------
def render(story: dict, times: list[dict], out: Path, voice: list[dict] | None = None, progress=print,
           beds_db: float = 0.0, upright: bool = False, subtitles: bool = False) -> Path:
    """The film (1920x1080, H.264 + AAC): the story's shots drawn with their bubbles, timed by `times`
    (tools/story_film.timeline), each place's sounds, a soft pop as each bubble comes, and the music low from the start,
    lifting at his realization. `upright`: the short version (1080x1920, tools/story_film.short_story and
    short_timeline). (voice and subtitles: a narrated film's, from before 2026-11-19.)"""
    import film_sound

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    seconds = sum(t["seconds"] for t in times)
    size = TALL if upright else SIZE
    subs = subtitle_cues(story, times, voice, size) if subtitles else None
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        jobs = jobs_for(story, times, size, tmp, short=upright, subs=subs)
        progress(f"Drawing {'the Short' if story.get('form') == 'short' else 'the short version'} upright: {len(jobs)} shots, {seconds:.0f} s" if upright
                 else f"Drawing the film: {len(jobs)} shots, {seconds / 60:.1f} minutes")
        video = draw_video(jobs, tmp / "video.mp4", progress)
        progress(("Mixing the Short's sound" if story.get("form") == "short" else "Mixing the short version's sound") if upright else "Mixing the sound")
        sound = [shot_sound(story["shots"][j["k"]], j["plan"], times[j["k"]]["seconds"], beds_db) for j in jobs]
        audio = tmp / "sound.m4a"
        film_sound.mix(sound, audio, voice=voice, music=music_spec(story, times))
        _mux(video, audio, out)
    return out


def _mux(video: Path, audio: Path, out: Path):
    import media

    subprocess.run([media.ffmpeg_exe(), "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-map", "0:v",
                    "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                    str(out)], check=True, timeout=600)


def _moment(story: dict, k: int, at: float | None, size, flags: dict | None = None, seconds: float | None = None):
    """Shot k at `at` seconds in (None: its strongest moment): (frame, plan, place, state)."""
    shot = {**story["shots"][k], "seed": story["shots"][k].get("seed", k * 101 + 7)}
    if seconds:
        shot["seconds"] = seconds
    p = plan_for(story, shot, size)
    if p.get("composed"):
        import silhouette_board as SB

        at = SB.best_moment(p) if at is None else at
        obj = SB.place_for(p, size)
        st = SB.state(p, obj, at, {"t0": 0.0, **(flags or {})})
        frame = obj.frame(int(at * FPS), st)
        flags = {**(flags or {}), **closing_place(p, obj, size, flags or {})}
    else:
        at = best_moment(story, k, p["seconds"]) if at is None else at
        obj = place(p["set"], size, p["light"], p["rain"], p.get("center"), p.get("open_door", False))
        st = state(p, obj, at, int(at * FPS), {"t0": 0.0, **(flags or {})})
        frame = obj.draw(int(at * FPS), st) if p["set"] == "desk_room" else obj.frame(int(at * FPS), st)
    overlays(frame, size, at, flags or {})
    return frame, p, obj, st


def moment(story: dict, k: int, at: float | None, size, flags: dict | None = None,
           seconds: float | None = None) -> np.ndarray:
    """One frame of shot k at `at` seconds into it (None: its strongest moment): a scene's still for the Reviewer, the
    dashboard, the thumbnail."""
    return _moment(story, k, at, size, flags, seconds)[0]


def best_moment(story: dict, k: int, seconds: float) -> float:
    """The strongest second of a shot: just after its event (the eyes wide), or a little after its middle (a shot of
    the storyboard: tools/silhouette_board.best_moment, him arrived when he walks in)."""
    shot = story["shots"][k]
    if shot.get("place") and not shot.get("set"):
        p = plan_for(story, {**shot, "seconds": seconds}, THUMB)
        if p.get("composed"):
            import silhouette_board as SB

            return SB.best_moment(p)
    if shot.get("event") in ("head_turn", "look_up", "eyes_open"):
        return min(seconds - 0.2, float(shot.get("event_at", 0.45)) * seconds + 0.9)
    return seconds * 0.6


def scene_stills(story: dict, times: list[dict], folder: Path, size=(960, 540)) -> list[dict]:
    """A still of every shot (the Reviewer's scene check, the dashboard's scenes grid): [{"shot", "path"}]."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for k, t in enumerate(times):
        path = folder / f"scene_{k + 1:02d}.jpg"
        frame = moment(story, k, best_moment(story, k, t["seconds"]), size, {"no_label": False}, t["seconds"])
        Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8)).save(path, "JPEG", quality=85)
        out.append({"shot": k + 1, "path": str(path)})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("story", help="agents/story.py --out's JSON (or {\"story\": ...})")
    parser.add_argument("out")
    args = parser.parse_args()
    import story_film

    data = json.loads(Path(args.story).read_text(encoding="utf-8"))
    story = data.get("story") or data
    times = story_film.timeline(story)
    render(story, times, Path(args.out))
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
