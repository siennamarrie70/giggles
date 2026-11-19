"""
What the people of the silhouette stories can do: every action as a pose at a moment, on a place's mark
(tools/silhouette_scene.py and tools/silhouette_places.py give the marks; tools/silhouette.py draws the poses).

pose(action, mark, t, R, ground) gives one person's pose at t seconds into a shot, and the eyes the action suggests
(their mood, where they look, a tear); pair(action, mark, t, R, R2, ground) gives two people's for the actions done
together (a hug, a handshake, an argument). Each action moves a little on its own (a stirring hand, a sob, a punch every
second), never anything fast or flickering: the look's rule.

ACTIONS is the vocabulary Agent 3's storyboard picks from (plain words; tools/silhouette_words.py repeats it for the
dashboard and Gemini).
"""

import math

import silhouette as S
from silhouette import clamp, ease_in_out, ik, smooth, spine
import silhouette_words as W
import silhouette_habits as H

ACTIONS, ITEMS, PAIRS = W.ACTIONS, W.ITEMS, W.PAIRS   # (the words live in tools/silhouette_words.py)


# the eyes an action suggests when the storyboard gives none: (mood, where they look: (forward, down))
EYES = {
    "typing": ("tired", (1.0, 0.1)), "slumped": ("sad", (1.0, 0.3)), "phone": ("tired", (1.0, 0.0)),
    "lying_awake": ("tired", (0.3, -0.8)), "asleep": ("closed", (0.0, 0.0)), "asleep_desk": ("closed", (0.0, 0.0)),
    "lying_floor": ("closed", (0.0, 0.0)), "floor": ("sad", (1.0, 0.2)), "head_in_hands": ("closed", (0.0, 0.0)),
    "pushups": ("determined", (1.0, 0.35)), "running": ("determined", (1.0, 0.0)), "cooking": ("soft", (0.8, 0.6)),
    "eating": ("soft", (1.0, 0.3)), "drinking": ("tired", (1.0, -0.1)), "reading": ("soft", (0.7, 0.55)),
    "letter": ("worried", (0.7, 0.45)), "writing": ("determined", (0.7, 0.6)), "lifting": ("determined", (1.0, 0.0)),
    "boxing": ("angry", (1.0, 0.0)), "treadmill": ("determined", (1.0, 0.0)), "driving": ("open", (1.0, 0.0)),
    "cleaning": ("soft", (0.8, 0.6)), "wiping": ("soft", (0.8, 0.6)), "fixing": ("determined", (0.8, 0.45)),
    "speaking": ("determined", (1.0, -0.1)), "presenting": ("open", (1.0, -0.3)), "hugging": ("closed", (0.0, 0.0)),
    "handshake": ("happy", (1.0, 0.0)), "arguing": ("angry", (1.0, 0.0)), "crying": ("sad", (0.6, 0.4)),
    "kneeling": ("sad", (1.0, 0.4)), "mirror": ("tired", (1.0, 0.0)), "applauding": ("happy", (1.0, 0.0)),
    "waving": ("happy", (1.0, 0.0)), "phone_call": ("worried", (1.0, 0.1)), "at_door": ("worried", (1.0, 0.0)),
    "standing": ("open", (1.0, 0.0)), "walking": ("open", (1.0, 0.0)), "sitting": ("open", (1.0, 0.1)),
    "at_window": ("soft", (1.0, -0.15)), "carrying_box": ("tired", (1.0, 0.1)), "holding": ("open", (1.0, 0.1)),
}

EYES.update(H.EYES)
WALK_SPEED, RUN_SPEED, BOX_SPEED = 170.0, 520.0, 130.0   # world units a second (tools/silhouette_render.py's)


def _uv(pose):
    T, u, v = spine(pose["S"], pose["H"], pose["f"], pose["R"])
    return T, (u, v)


def _elbow(sh, wr, R, f, out=False):
    """The elbow of an arm from the shoulder sh to the wrist wr: bending down (out=False) or forward and out."""
    l1, l2 = 1.22 * R, 1.10 * R
    k1, k2 = ik(sh, wr, l1, l2, 1), ik(sh, wr, l1, l2, -1)
    if out:
        return k1 if f * (k1[0] - k2[0]) > 0 else k2
    return k1 if k1[1] > k2[1] else k2


def _arm_to(sh, wr, R, f, out=False):
    return (sh, _elbow(sh, wr, R, f, out), wr)


def _pulse(t, period, on=0.18, phase=0.0):
    """0 -> 1 -> 0 once a period: a quick move out and a slower return (a punch, a jab)."""
    u = ((t + phase) % period) / period
    if u < on * 0.4:
        return smooth(u / (on * 0.4))
    if u < on:
        return 1 - smooth((u - on * 0.4) / (on * 0.6))
    return 0.0


def _bob(pose, dy):
    """Moves the whole upper body (the torso, the head, the arms) by dy: a sob, a breath."""
    def shift(pt):
        return (pt[0], pt[1] + dy)
    pose["S"], pose["H"], pose["head"] = shift(pose["S"]), shift(pose["H"]), shift(pose["head"])
    pose["T"], _ = _uv(pose)
    for k in ("near", "far"):
        if pose.get(k):
            pose[k] = tuple(shift(q) for q in pose[k])
    return pose


# --- poses beyond silhouette.py's ------------------------------------------------------------------------------------------
def pose_kneel(x, ground, f, R, bow=0.0, lift=0.0) -> dict:
    """Kneeling on one knee: the back knee on the ground (its foot behind, on its toes), the front foot planted, its knee
    up; bow 0-1: upright .. bowed over (at a grave)."""
    H = (x, ground - 1.55 * R)
    back_knee, back_foot = (x - f * 0.30 * R, ground - 0.10 * R), (x - f * 1.55 * R, ground - 0.06 * R)
    front_knee, front_foot = (x + f * 1.38 * R, ground - 1.40 * R), (x + f * 1.30 * R, ground)
    lean = 0.05 + 0.62 * clamp(bow)
    S_ = (H[0] + f * math.sin(lean) * 2.55 * R, H[1] - math.cos(lean) * 2.55 * R)
    T, u, v = spine(S_, H, f, R)
    head = T(0.14 + 0.45 * bow - 0.08 * lift, -1.28 + 0.45 * bow - 0.06 * lift)
    sh = T(0.02, 0.24)
    near = _arm_to(sh, (front_knee[0] + f * 0.10 * R, front_knee[1] - 0.12 * R), R, f)
    return {"f": f, "R": R, "S": S_, "H": H, "T": T, "head": head, "lift": lift, "hood_up": False,
            "legs": [((H[0] - f * 0.05 * R, H[1]), back_knee, back_foot), (H, front_knee, front_foot)], "toes": [True, False],
            "near": near, "far": None, "hold": None, "hands": ["fist", "fist"], "hem_max": 2.62}


def pose_lie_floor(x, ground, f, R) -> dict:
    """Lying on the floor on his back, his head at x, his body towards f."""
    p = S.pose_lie(x, ground - 1.04 * R, f, R, arms="rest")
    p["floor"] = True
    return p


def _stance(x, ground, f, R, lift=0.0, slump=0.0):
    """Standing with the feet apart, the front one forward (a boxer's, a worker's stance)."""
    return S.pose_stand(x, ground, f, R, slump=slump, lift=lift, arms="hang", walk=0.9, phase=math.pi / 2)


# --- one person's actions --------------------------------------------------------------------------------------------------
def _walk_x(mark, t, seconds, speed):
    """Where a walker is at t (from `from` to `to`, easing in and slowing to a stop) and how fast (0-1)."""
    length = abs(mark["to"] - mark["from"])
    ramp = min(0.35, seconds / 4)
    if t < ramp:
        d, v = speed * t * t / (2 * ramp), t / ramp
    else:
        d, v = speed * (t - ramp / 2), 1.0
    stop = 0.9 * speed
    if d > length - stop / 2:
        q = min(1.0, (d - (length - stop / 2)) / stop)
        d = length - stop / 2 + stop / 2 * (1 - (1 - q) ** 2)
        v *= max(0.0, 1 - q)
        if q >= 1:
            d, v = length, 0.0
    sign = 1 if mark["to"] >= mark["from"] else -1
    return mark["from"] + sign * min(d, length), v


def _holding(pose, item, R, f, ground):
    """The near arm holding an item (ITEMS) the way it's carried."""
    T, uv = _uv(pose)
    sh = pose["near"][0]
    if item == "bag":
        wr = T(0.12, 2.15)
        pose["hold"] = {"kind": "bag", "at": (wr[0], wr[1] + 0.12 * R)}
    elif item == "suitcase":
        wr = T(-0.45, 2.05)
        pose["hold"] = {"kind": "suitcase", "at": (wr[0], wr[1] + 0.10 * R), "ground": ground}
    elif item == "trophy":
        wr = T(0.55, -1.75)
        pose["hold"] = {"kind": "trophy", "at": (wr[0], wr[1] - 0.10 * R)}
        pose["near"] = (sh, T(0.62, -0.55), wr)
        pose["hands"] = [pose["hands"][0], "fist"]
        return pose
    elif item == "box":
        p2 = S.pose_stand(pose["H"][0], ground, f, R, arms="box")
        pose.update({k: p2[k] for k in ("near", "far", "hold", "hands")})
        return pose
    else:   # held in front: flowers, a gift, money, a cup, a bottle, a glass, a letter, a book
        wr = T(0.95, 1.10) if item in ("flowers", "gift", "money") else T(0.90, 0.95)
        kind = {"cup": "cup", "bottle": "bottle", "glass": "glass", "letter": "letter", "book": "book"}.get(item, item)
        pose["hold"] = {"kind": kind, "at": (wr[0] + f * 0.08 * R, wr[1] - 0.08 * R)}
    pose["near"] = _arm_to(sh, wr, R, f)
    pose["hands"] = [pose["hands"][0], "fist"]
    return pose


def pose(action: str, mark: dict, t: float, R: float, ground: float, seed: int = 0, item: str | None = None,
         seconds: float = 6.0) -> tuple[dict, dict]:
    """One person's pose at t seconds into a shot, doing `action` on `mark`, and the eyes it suggests: {"mood", "look":
    (dx, dy) with dx towards where they face, "tear": 0-1 (0 none)}."""
    f = mark.get("f", 1)
    gnd = mark.get("ground", ground)
    mood, (lx, ly) = EYES.get(action, ("open", (1.0, 0.0)))
    eyes = {"mood": mood, "look": (lx, ly), "tear": 0.0}
    breath = 0.03 * math.sin(math.tau * 0.24 * t + seed)
    kind = mark.get("kind", "stand")

    if action in H.ACTIONS:   # a habit's exaggerated action (tools/silhouette_habits.py)
        got = H.pose(action, mark, t, R, ground, f, seed=seed, seconds=seconds)
        if got is not None:
            return got

    if action in ("walking", "running", "carrying_box") or kind in ("walk", "run"):
        running = action == "running" or kind == "run"
        box = action == "carrying_box" or item == "box"
        speed = RUN_SPEED if running else (BOX_SPEED if box else WALK_SPEED)
        if "from" in mark:
            x, v = _walk_x(mark, t, seconds, speed)
            d = abs(x - mark["from"])
        else:
            x, v, d = mark.get("x", 0.0), 0.0, 0.0
        step = 2 * 2.84 * R * 0.985 * math.sin(0.70 if running else 0.40)
        phase = math.pi * d / step + seed
        arms = "box" if box else ("run" if running else ("phone" if action == "phone" else "hang"))
        p = S.pose_stand(x, gnd, f, R, lift=breath, arms=arms, walk=v if not running else 0.0, phase=phase,
                         run=v if running else 0.0)
        if item and not box and not running:
            p = _holding(p, item, R, f, gnd)
        if action == "phone_call":
            p = _call(p, R, f)
        return p, eyes

    if action == "treadmill":
        phase = math.tau * t / 0.62 + seed
        return S.pose_stand(mark["x"], gnd, f, R, run=1.0, phase=phase), eyes

    if action in ("lying_awake", "asleep"):
        if "y" not in mark:   # not a bed: on the floor, there
            p = pose_lie_floor(mark.get("x", mark.get("to", 0.0)), gnd, f, R)
            if action == "lying_awake":
                q = S.pose_lie(p["head"][0], p["head"][1], f, R, arms="phone")
                p.update({k: q[k] for k in ("near", "hold")})
            return p, eyes
        return S.pose_lie(mark["x"], mark["y"], f, R, arms="phone" if action == "lying_awake" else "rest"), eyes
    if action == "lying_floor":
        return pose_lie_floor(mark["x"], gnd, f, R), eyes
    if action == "floor":
        return S.pose_floor(mark["x"], gnd, f, R, slump=0.25, lift=breath), eyes
    if action == "pushups":
        return S.pose_pushup(mark["x"], gnd, f, R, phase=math.tau * t / 1.7 + seed), eyes

    if kind == "sit" or kind == "drive":
        return _sitting(action, mark, t, R, gnd, f, breath, eyes, seed, item)
    return _standing(action, mark, t, R, gnd, f, breath, eyes, seed, item)


def _call(p, R, f):
    """The near hand holding the phone to his ear."""
    T, _ = _uv(p)
    hx, hy = p["head"]
    wr = (hx + f * 0.02 * R, hy + 0.62 * R)
    p["near"] = (p["near"][0], T(0.78, 0.92), wr)
    p["hold"] = {"kind": "phone_ear", "at": (hx - f * 0.12 * R, hy + 0.30 * R)}
    p["hands"] = [p["hands"][0], "fist"]
    return p


def _sitting(action, mark, t, R, gnd, f, breath, eyes, seed, item):
    reach = mark.get("reach")
    slump = 0.85 if action == "slumped" else 0.0
    arms = {"typing": "type", "head_in_hands": "head", "phone": "phone"}.get(action, "lap")
    if arms == "lap" and reach and action in ("sitting", "slumped"):
        arms = "desk"
    if action == "asleep_desk" and reach:
        p = S.pose_sit(mark["x"], mark["seat"], gnd, f, R, slump=1.0, arms="desk", reach=reach)
        T, uv = _uv(p)
        rx, ry = reach
        p["head"] = (rx - f * 0.15 * R, ry - 0.95 * R + 0.02 * R * math.sin(math.tau * 0.2 * t))
        p["near"] = _arm_to(p["near"][0], (rx + f * 0.25 * R, ry - 0.10 * R), R, f, out=True)
        p["hands"] = ["fist", "hidden"]
        return p, eyes
    p = S.pose_sit(mark["x"], mark["seat"], gnd, f, R, slump=slump, lift=breath, arms=arms, reach=reach, tap=t)
    T, uv = _uv(p)
    sh = p["near"][0]
    hx, hy = p["head"]
    if action == "driving" and reach:
        wx, wy = reach
        turn = 0.06 * R * math.sin(math.tau * t / 5.0 + seed)
        p["near"] = _arm_to(sh, (wx + f * 0.05 * R, wy + 0.10 * R + turn), R, f)
        far_sh = T(-0.06, 0.26)
        p["far"] = _arm_to(far_sh, (wx - f * 0.05 * R, wy - 0.30 * R - turn), R, f)
        p["hands"] = ["fist", "fist"]
    elif action == "eating" and reach:
        mouth = (hx + f * 0.80 * R, hy + 0.55 * R)
        plate = (reach[0], reach[1] - 0.12 * R)
        u = (t + seed * 0.37) % 3.4
        q = 0.0 if u < 1.2 else (smooth((u - 1.2) / 0.7) if u < 1.9 else (1.0 if u < 2.5 else 1 - smooth((u - 2.5) / 0.9)))
        wr = (plate[0] + (mouth[0] - f * 0.35 * R - plate[0]) * q, plate[1] + (mouth[1] + 0.25 * R - plate[1]) * q)
        p["near"] = _arm_to(sh, wr, R, f)
        p["hold"] = {"kind": "spoon", "at": wr, "to": mouth if q > 0.3 else (wr[0] + f * 0.5 * R, wr[1] + 0.1 * R)}
        p["hands"] = ["fist", "fist"]
        p["lift"] = -0.15 + 0.15 * q
    elif action in ("writing",) and reach:
        jig = (0.05 * R * math.sin(math.tau * t * 1.7), 0.03 * R * math.sin(math.tau * t * 3.3))
        wr = (reach[0] + f * 0.05 * R + jig[0], reach[1] - 0.06 * R + jig[1])
        p["near"] = _arm_to(sh, wr, R, f)
        p["hold"] = {"kind": "pen", "at": wr, "paper": (reach[0] + f * 0.25 * R, reach[1] + 0.02 * R)}
        p["lift"] = -0.45
    elif action in ("reading", "letter"):
        book = T(1.15, 0.80)
        p["near"] = _arm_to(sh, (book[0] - f * 0.08 * R, book[1] + 0.12 * R), R, f)
        p["far"] = _arm_to(T(-0.06, 0.26), (book[0] - f * 0.20 * R, book[1] + 0.05 * R), R, f)
        p["hold"] = {"kind": "book" if action == "reading" else "letter", "at": book}
        p["hands"] = ["fist", "fist"]
        p["lift"] = -0.35
    elif action == "wiping" and reach:
        a = math.tau * t / 1.3
        wr = (reach[0] + f * 0.25 * R + 0.30 * R * math.cos(a), reach[1] - 0.05 * R + 0.05 * R * math.sin(a))
        p["near"] = _arm_to(sh, wr, R, f)
        p["hold"] = {"kind": "rag", "at": (wr[0], wr[1] + 0.05 * R)}
        p["hands"] = ["fist", "open"]
    elif action == "phone_call":
        p = _call(p, R, f)
    elif action in ("drinking",):
        p = _drink(p, t, R, f, seed, item or "glass")
    elif action == "crying":
        p = _cry(p, t, R, f, seed)
        eyes["tear"] = ((t + seed * 0.29) % 2.6) / 2.6
    elif action == "applauding":
        p = _clap(p, t, R, f)
    elif action == "holding" and item:
        p = _holding(p, item, R, f, gnd)
    return p, eyes


def _drink(p, t, R, f, seed, item):
    T, uv = _uv(p)
    sh = p["near"][0]
    hx, hy = p["head"]
    u = (t + seed * 0.31) % 4.0
    q = 0.0 if u < 1.6 else (smooth((u - 1.6) / 0.6) if u < 2.2 else (1.0 if u < 3.0 else 1 - smooth((u - 3.0) / 0.8)))
    rest = T(1.00, 1.05)
    mouth = (hx + f * 0.95 * R, hy + 0.55 * R)
    wr = (rest[0] + (mouth[0] - rest[0]) * q, rest[1] + (mouth[1] + 0.20 * R - rest[1]) * q)
    p["near"] = _arm_to(sh, wr, R, f)
    p["hold"] = {"kind": item if item in ("glass", "bottle", "cup") else "glass",
                 "at": (wr[0] + f * 0.06 * R, wr[1] - 0.06 * R), "tilt": -f * 0.9 * q}
    p["hands"] = [p["hands"][0], "fist"]
    p["lift"] = p.get("lift", 0.0) + 0.25 * q
    return p


def _cry(p, t, R, f, seed):
    """Head bowed, shoulders shaking a little, the near hand wiping under the eye now and then."""
    sob = 0.035 * R * max(0.0, math.sin(math.tau * 2.1 * t + seed)) * (0.6 + 0.4 * math.sin(math.tau * 0.3 * t))
    p = _bob(p, sob)
    p["lift"] = p.get("lift", 0.0) - 0.45
    T, uv = _uv(p)
    hx, hy = p["head"]
    u = (t + seed * 0.43) % 3.2
    q = smooth(u / 0.5) if u < 0.5 else (1.0 if u < 1.6 else (1 - smooth((u - 1.6) / 0.6) if u < 2.2 else 0.0))
    rest = T(0.60, 1.55) if not p.get("sitting") else T(0.70, 1.30)
    cheek = (hx + f * 0.55 * R, hy + 0.55 * R)
    wr = (rest[0] + (cheek[0] - rest[0]) * q, rest[1] + (cheek[1] - rest[1]) * q)
    p["near"] = _arm_to(p["near"][0], wr, R, f)
    p["hands"] = [p["hands"][0], "fist"]
    return p


def _clap(p, t, R, f):
    T, uv = _uv(p)
    gap = 0.20 * R * abs(math.sin(math.pi * 2.4 * t))
    c = T(1.05, 0.70)
    p["near"] = _arm_to(p["near"][0], (c[0] + f * gap, c[1]), R, f)
    p["far"] = _arm_to(T(-0.06, 0.26), (c[0] - f * 0.10 * R, c[1] - 0.04 * R), R, f)
    p["hands"] = ["open", "open"]
    p["lift"] = p.get("lift", 0.0) + 0.1
    return p


def _standing(action, mark, t, R, gnd, f, breath, eyes, seed, item):
    x = mark.get("x", 0.0)
    reach = mark.get("reach")
    if action == "kneeling" or mark.get("kind") == "kneel" and action not in ("fixing",):
        bow = 0.7 if mark.get("bow") or eyes["mood"] == "sad" else 0.15
        p = pose_kneel(x, gnd, f, R, bow=bow, lift=breath)
        if item:
            p = _holding(p, item, R, f, gnd)
        return p, eyes
    if action == "fixing":
        if reach:   # at a workbench: hammering
            p = S.pose_stand(x, gnd, f, R, lift=-0.4 + breath)
            T, uv = _uv(p)
            q = _pulse(t + seed * 0.21, 0.75, on=0.55)
            wr = (reach[0] - f * 0.20 * R, reach[1] - 0.25 * R - 0.75 * R * (1 - q))
            p["near"] = _arm_to(p["near"][0], wr, R, f)
            p["hold"] = {"kind": "hammer", "at": wr, "to": (wr[0] + f * 0.45 * R, wr[1] + 0.05 * R - 0.25 * R * (1 - q))}
            p["far"] = _arm_to(T(-0.06, 0.26), (reach[0] - f * 0.55 * R, reach[1] - 0.08 * R), R, f)
            p["hands"] = ["fist", "fist"]
            return p, eyes
        p = pose_kneel(x, gnd, f, R, bow=0.35)
        T, uv = _uv(p)
        a = math.tau * t / 0.9 + seed
        wr = (x + f * (1.95 * R + 0.08 * R * math.cos(a)), gnd - 1.55 * R + 0.08 * R * math.sin(a))
        p["near"] = _arm_to(p["near"][0], wr, R, f, out=True)
        p["hold"] = {"kind": "wrench", "at": wr, "to": (wr[0] + f * 0.50 * R, wr[1] - 0.10 * R)}
        return p, eyes
    if action == "boxing":
        bag = mark.get("target", (x + f * 2.3 * R, gnd - 4.9 * R))
        p = _stance(x, gnd, f, R, lift=0.05 + breath)
        T, uv = _uv(p)
        q = _pulse(t + seed * 0.17, 1.05, on=0.30)
        guard = T(0.95, -0.25)
        hit = (bag[0] - f * 0.55 * R, bag[1])
        wr = (guard[0] + (hit[0] - guard[0]) * q, guard[1] + (hit[1] - guard[1]) * q)
        p["near"] = _arm_to(p["near"][0], wr, R, f, out=q > 0.5)
        p["far"] = _arm_to(T(-0.06, 0.26), T(0.80, -0.10), R, f)
        p["hands"] = ["fist", "fist"]
        return p, eyes
    if action == "lifting":
        p = S.pose_stand(x, gnd, f, R, lift=0.05 + breath)
        T, uv = _uv(p)
        u = (t + seed * 0.13) % 2.0
        q = ease_in_out(u / 0.9) if u < 0.9 else (1.0 if u < 1.1 else 1 - ease_in_out((u - 1.1) / 0.9))
        fore = 0.15 + 2.45 * q
        el, wr = S._arm(p["near"][0], 0.10, fore, uv, R)
        el2, wr2 = S._arm(T(-0.06, 0.26), 0.10, fore, uv, R)
        p["near"], p["far"] = (p["near"][0], el, wr), (T(-0.06, 0.26), el2, wr2)
        p["hold"] = {"kind": "dumbbell", "at": wr}
        p["far_hold"] = {"kind": "dumbbell", "at": wr2}
        p["hands"] = ["fist", "fist"]
        return p, eyes
    if action == "cooking" and reach:
        p = S.pose_stand(x, gnd, f, R, lift=-0.35 + breath)
        T, uv = _uv(p)
        a = math.tau * t / 1.4 + seed
        pan = (reach[0] + 0.10 * R * math.cos(a), reach[1])
        wr = (pan[0] - f * 0.30 * R, pan[1] - 0.70 * R + 0.06 * R * math.sin(a))
        p["near"] = _arm_to(p["near"][0], wr, R, f)
        p["hold"] = {"kind": "spatula", "at": wr, "to": (pan[0] + f * 0.15 * R, pan[1] - 0.08 * R)}
        p["far"] = _arm_to(T(-0.06, 0.26), (reach[0] - f * 0.95 * R, reach[1] - 0.12 * R), R, f)
        return p, eyes
    if action == "wiping" and reach:
        p = S.pose_stand(x, gnd, f, R, lift=-0.4 + breath, slump=0.2)
        a = math.tau * t / 1.3
        wr = (reach[0] + 0.30 * R * math.cos(a), reach[1] - 0.06 * R + 0.04 * R * math.sin(a))
        p["near"] = _arm_to(p["near"][0], wr, R, f)
        p["hold"] = {"kind": "rag", "at": (wr[0], wr[1] + 0.05 * R)}
        p["hands"] = ["fist", "open"]
        return p, eyes
    if action == "cleaning":
        p = S.pose_stand(x, gnd, f, R, lift=-0.5 + breath, slump=0.15)
        T, uv = _uv(p)
        s = math.sin(math.tau * t / 1.6 + seed)
        floor_pt = (x + f * (1.75 * R + 0.55 * R * s), gnd)
        top = T(0.55, 0.95)
        top = (top[0] + f * 0.15 * R * s, top[1])
        p["near"] = _arm_to(p["near"][0], top, R, f)
        mid = (top[0] + (floor_pt[0] - top[0]) * 0.38, top[1] + (floor_pt[1] - top[1]) * 0.38)
        p["far"] = _arm_to(T(-0.06, 0.26), mid, R, f)
        p["hold"] = {"kind": "broom", "at": top, "floor": floor_pt}
        p["hands"] = ["fist", "fist"]
        return p, eyes
    if action == "speaking":
        p = S.pose_stand(x, gnd, f, R, lift=0.12 + breath)
        T, uv = _uv(p)
        g = math.sin(math.tau * t / 2.6 + seed)
        el = T(0.80, 1.05)
        wr = T(1.25 + 0.15 * g, 0.15 - 0.20 * g)
        p["near"] = (p["near"][0], el, wr)
        if reach:
            p["far"] = _arm_to(T(-0.06, 0.26), (reach[0] - f * 0.25 * R, reach[1] - 0.05 * R), R, f)
        p["hands"] = ["fist", "open"]
        return p, eyes
    if action == "presenting":
        p = S.pose_stand(x, gnd, f, R, lift=0.25 + breath)
        T, uv = _uv(p)
        target = mark.get("point", T(2.6, -1.6))
        sh = p["near"][0]
        d = math.hypot(target[0] - sh[0], target[1] - sh[1])
        k = min(1.0, 2.1 * R / max(d, 1e-6))
        wr = (sh[0] + (target[0] - sh[0]) * k, sh[1] + (target[1] - sh[1]) * k)
        p["near"] = _arm_to(sh, wr, R, f, out=True)
        p["hands"] = ["fist", "open"]
        return p, eyes
    if action == "waving":
        p = S.pose_stand(x, gnd, f, R, lift=0.1 + breath)
        T, uv = _uv(p)
        w = 0.30 + 0.32 * math.sin(math.tau * 1.6 * t)
        el = T(1.20, 0.30)
        wr = (el[0] + f * math.sin(w) * 1.05 * R, el[1] - math.cos(w) * 1.05 * R)
        p["near"] = (p["near"][0], el, wr)
        p["hands"] = ["fist", "open"]
        return p, eyes
    if action == "at_door":
        knock = t if t < 1.6 else 0.0
        return S.pose_stand(x, gnd, f, R, lift=breath, arms="knock", knock=knock), eyes
    # standing, with what the action does to the arms
    arms = "pockets" if action == "at_window" else "hang"
    if action == "phone":
        arms = "phone"
    if mark.get("arms") and action == "standing":
        arms = mark["arms"]
    lift = breath + (mark.get("lift", 0.0) if action in ("standing", "at_window") else 0.0)
    p = S.pose_stand(x, gnd, f, R, lift=lift, arms=arms)
    if action == "phone_call":
        p = _call(p, R, f)
    elif action == "drinking":
        p = _drink(p, t, R, f, seed, item or "glass")
    elif action == "crying":
        p = _cry(p, t, R, f, seed)
        eyes["tear"] = ((t + seed * 0.29) % 2.6) / 2.6
    elif action == "applauding":
        p = _clap(p, t, R, f)
    elif action in ("reading", "letter"):
        T, uv = _uv(p)
        book = T(1.10, 0.85)
        p["near"] = _arm_to(p["near"][0], (book[0] - f * 0.08 * R, book[1] + 0.12 * R), R, f)
        p["far"] = _arm_to(T(-0.06, 0.26), (book[0] - f * 0.20 * R, book[1] + 0.05 * R), R, f)
        p["hold"] = {"kind": "book" if action == "reading" else "letter", "at": book}
        p["hands"] = ["fist", "fist"]
        p["lift"] = -0.35
    elif action == "holding" and item:
        p = _holding(p, item, R, f, gnd)
    return p, eyes


# --- two people's actions --------------------------------------------------------------------------------------------------
GAPS = {"hugging": 1.30, "handshake": 2.95, "arguing": 3.50}   # between their hips, in his head's radii


def pair(action: str, mark: dict, t: float, R: float, R2: float, ground: float, seed: int = 0) -> tuple:
    """Two people doing something together at a pair mark ({"x": between them, "f": the way HE faces}): returns (his
    pose, his eyes, their pose, their eyes). Draw them first, then him (his near arm goes over them)."""
    f = mark.get("f", 1)
    gnd = mark.get("ground", ground)
    gap = GAPS[action] * R
    x1, x2 = mark["x"] - f * gap / 2, mark["x"] + f * gap / 2
    breath = 0.03 * math.sin(math.tau * 0.24 * t + seed)
    if action == "handshake":
        a = S.pose_stand(x1, gnd, f, R, lift=breath)
        b = S.pose_stand(x2, gnd, -f, R2, lift=breath)
        meet = (mark["x"], gnd - 3.35 * R + 0.07 * R * math.sin(math.tau * t / 0.45) * (1 - smooth(t / 1.6)))
        for p_, r_, ff in ((a, R, f), (b, R2, -f)):
            p_["near"] = _arm_to(p_["near"][0], (meet[0] - ff * 0.12 * r_, meet[1]), r_, ff)
            p_["hands"] = ["fist", "open"]
        return a, {"mood": "happy", "look": (1.0, 0.0), "tear": 0.0}, b, {"mood": "happy", "look": (1.0, 0.0), "tear": 0.0}
    if action == "arguing":
        a = S.pose_stand(x1, gnd, f, R, lift=0.08 + breath)
        b = S.pose_stand(x2, gnd, -f, R2, lift=0.05 + breath, arms="cross" if seed % 2 else "hang")
        Ta, _ = _uv(a)
        q = _pulse(t + seed * 0.11, 1.15, on=0.45)
        sh = a["near"][0]
        wr = Ta(1.30 + 0.45 * q, 0.55 - 0.25 * q)
        a["near"] = _arm_to(sh, wr, R, f, out=True)
        a["hands"] = ["fist", "open"]
        if not seed % 2:
            Tb, _ = _uv(b)
            g = math.sin(math.tau * t / 1.9 + 1.0)
            b["near"] = (b["near"][0], Tb(0.75, 1.10), Tb(1.20 + 0.10 * g, 0.40 - 0.15 * g))
            b["hands"] = ["fist", "open"]
        return (a, {"mood": "angry", "look": (1.0, 0.0), "tear": 0.0},
                b, {"mood": "angry" if seed % 3 else "sad", "look": (1.0, 0.0), "tear": 0.0})
    # hugging: pressed together, his near arm round their back, each head beside the other's: cheek to cheek, never one
    # over the other (two black heads on top of each other read as one blob)
    a = S.pose_stand(x1, gnd, f, R, lift=-0.1 + breath)
    b = S.pose_stand(x2, gnd, -f, R2, lift=-0.1 + breath)
    a["head"] = (mark["x"] - f * 0.82 * R, a["head"][1] - 0.04 * R)
    b["head"] = (mark["x"] + f * 0.82 * R2, b["head"][1] + 0.18 * R2)
    Tb, _ = _uv(b)
    a["near"] = _arm_to(a["near"][0], Tb(-0.55, 0.70), R, f, out=True)
    a["hands"] = ["fist", "open"]
    Ta, _ = _uv(a)
    b["near"] = _arm_to(b["near"][0], Ta(-0.45, 0.65), R2, -f, out=True)
    b["hands"] = ["fist", "open"]
    eyes = {"mood": "closed", "look": (1.0, 0.0), "tear": 0.0}
    return a, eyes, b, dict(eyes)


def eyes_of(hint: dict, look_gap: float, blink: float = 1.0, mood: str | None = None, f: int = 1) -> S.Eyes:
    """The Eyes for a pose's eye hint (pose()'s second value), in the storyboard's mood if it gives one."""
    lx, ly = hint["look"]
    return S.eyes_for(mood or hint["mood"], (lx * f, ly), look_gap, blink, hint.get("tear", 0.0))
