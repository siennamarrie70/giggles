"""
The habits' exaggerated actions: what a weakness or a virtue looks like when a story shows it big, so the film says it
without words (anger slams the table and throws the phone; lust stares transfixed, hides the phone; laziness sprawls on
the sofa and slaps the snooze button; envy peeks from behind a doorway and crushes a paper; ego crosses its arms, chin up;
fear hides under the blanket and backs away; greed counts money and hugs the bag; discipline gets up, ticks the list,
waters the plant...). Each moves a little on its own, smoothly (the look's rule), like tools/silhouette_actions.py's.

  ACTIONS                                    name: (what it shows, the mark it needs): the storyboard's words
  EYES                                       the eyes each suggests when the storyboard gives none
  pose(action, mark, t, R, ground, f, ...)   one person's pose at t seconds into a shot, and the eyes it suggests

Imported by tools/silhouette_actions.py (it hands these actions over); the things they hold are drawn here too (added to
tools/silhouette.py's HOLDS).
"""

import math

import numpy as np

import silhouette as S
from silhouette import clamp, hexc, ik, rr, smooth, spine, tube
import silhouette_icons as I
import silhouette_words as W

ACTIONS = W.HABIT_ACTIONS   # (the words live in tools/silhouette_words.py)

EYES = {
    "slamming": ("furious", (1.0, 0.3)), "throwing": ("furious", (1.0, 0.0)), "punching_wall": ("furious", (1.0, 0.0)),
    "shouting": ("furious", (1.0, 0.0)), "shaking_fists": ("furious", (1.0, 0.0)), "hiding_phone": ("wide", (-1.0, 0.0)),
    "staring": ("hearts", (1.0, 0.1)), "doomscrolling": ("spirals", (1.0, 0.5)), "sprawled": ("droopy", (0.6, -0.4)),
    "snoozing": ("closed", (0.0, 0.0)), "stretching": ("closed", (0.0, 0.0)), "snacking": ("droopy", (1.0, 0.0)),
    "watching_tv": ("droopy", (1.0, -0.1)), "peeking": ("side_eye", (1.0, 0.0)), "clenching": ("side_eye", (1.0, 0.2)),
    "arms_crossed": ("smug", (1.0, 0.0)), "admiring": ("smug", (1.0, 0.0)), "waving_off": ("smug", (-1.0, 0.0)),
    "posing": ("smug", (1.0, -0.2)), "curled_up": ("closed", (0.0, 0.0)), "sulking": ("sad", (1.0, 0.3)),
    "hiding_bed": ("terrified", (1.0, 0.0)), "backing_away": ("terrified", (1.0, 0.0)), "cowering": ("terrified", (0.6, 0.3)),
    "counting_money": ("dollars", (1.0, 0.5)), "hugging_bag": ("dollars", (1.0, 0.0)), "grabbing": ("dollars", (1.0, 0.0)),
    "rising": ("determined", (1.0, 0.0)), "ticking": ("determined", (0.8, -0.2)), "watering": ("soft", (0.8, 0.5)),
    "meditating": ("closed", (0.0, 0.0)),
}

PAPER, CAN, WATER = hexc("#EDE6DA"), hexc("#3E7A86"), hexc("#9FD0FF")


def _T(pose):
    return spine(pose["S"], pose["H"], pose["f"], pose["R"])[0]


def _elbow(sh, wr, R, f, out=False):
    """The elbow of an arm from the shoulder sh to the wrist wr, facing f. out=False: it bends the way a real arm does
    (the forearm folds forward), on the same side whatever the hand does, so it never jumps across the arm from one frame
    to the next (it used to take the lower of the two places, which swapped as the hand passed under the shoulder).
    out=True: raised and out (a hug's, a guard's) while the hand is below the shoulder, a real arm's above it: for a hand
    that stays on one side of the shoulder's height (one that crosses it: out=False). Near full reach it straightens
    softly, never snapping straight."""
    l1, l2 = 1.22 * R, 1.10 * R
    wr = _soft_reach(sh, wr, l1 + l2)
    if not out:
        return ik(sh, wr, l1, l2, -f)
    k1, k2 = ik(sh, wr, l1, l2, 1), ik(sh, wr, l1, l2, -1)
    return k1 if f * (k1[0] - k2[0]) > 0 else k2


def _soft_reach(sh, wr, L, start=0.90, most=0.995):
    """The hand the elbow is worked out for: eased in towards full reach (an elbow's angle changes ever faster as the arm
    straightens; without this it snaps straight in the last frames). The hand itself stays where it was asked to be."""
    dx, dy = wr[0] - sh[0], wr[1] - sh[1]
    d = math.hypot(dx, dy)
    a, b = start * L, most * L
    if d <= a:
        return wr
    d2 = a + (b - a) * (1 - math.exp(-(d - a) / (b - a)))
    return (sh[0] + dx * d2 / d, sh[1] + dy * d2 / d)


def _arm(sh, wr, R, f, out=False):
    return (sh, _elbow(sh, wr, R, f, out), wr)


def _lean(pose, angle, head=(0.14, -1.28)):
    """The upper body tipped forward (angle > 0) or back from the hips, the head where `head` puts it (torso frame)."""
    R, f, H = pose["R"], pose["f"], pose["H"]
    pose = dict(pose)
    pose["S"] = (H[0] + f * math.sin(angle) * 2.55 * R, H[1] - math.cos(angle) * 2.55 * R)
    pose["T"] = _T(pose)
    pose["head"] = pose["T"](*head)
    return pose


def _lerp(a, b, u):
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def _swing(sh, a, b, s, over=True):
    """A hand on its way (s 0-1) from a to b round the shoulder sh, never through it (an arm folded flat there whips
    its elbow round): up and over (straight up on the way), or over=False the shorter way round; its distance from the
    shoulder eased from a's to b's."""
    a0, a1 = math.atan2(a[1] - sh[1], a[0] - sh[0]), math.atan2(b[1] - sh[1], b[0] - sh[0])
    d = (a1 - a0) % math.tau
    if ((-math.pi / 2 - a0) % math.tau > d) if over else d > math.pi:   # (the other way round)
        d -= math.tau
    r0, r1 = math.hypot(a[0] - sh[0], a[1] - sh[1]), math.hypot(b[0] - sh[0], b[1] - sh[1])
    ang, r = a0 + d * s, r0 + (r1 - r0) * s
    return (sh[0] + r * math.cos(ang), sh[1] + r * math.sin(ang))


def _pulse(t, period, on=0.18, phase=0.0):
    u = ((t + phase) % period) / period
    if u < on * 0.4:
        return smooth(u / (on * 0.4))
    if u < on:
        return 1 - smooth((u - on * 0.4) / (on * 0.6))
    return 0.0


def _seat_or_stand(mark, gnd, f, R, slump=0.0, lift=0.0):
    if mark.get("kind") in ("sit", "drive") and mark.get("seat") is not None:
        return S.pose_sit(mark["x"], mark["seat"], gnd, f, R, slump=slump, lift=lift)
    return S.pose_stand(mark.get("x", 0.0), gnd, f, R, slump=slump, lift=lift)


def pose(action: str, mark: dict, t: float, R: float, ground: float, f: int, seed: int = 0, seconds: float = 6.0):
    """One person's pose doing a habit's action at t, and the eyes it suggests ({"mood", "look", "tear"})."""
    gnd = mark.get("ground", ground)
    x = mark.get("x", mark.get("to", 0.0))
    mood, look = EYES.get(action, ("open", (1.0, 0.0)))
    eyes = {"mood": mood, "look": look, "tear": 0.0}
    breath = 0.03 * math.sin(math.tau * 0.24 * t + seed)
    reach = mark.get("reach")

    if action == "slamming":   # the fists rise slowly, come down hard, rest; the body jolts as they land
        p = S.pose_stand(x, gnd, f, R, lift=-0.25)
        u = ((t + seed * 0.13) % 1.1) / 1.1
        up = smooth(u / 0.62) if u < 0.62 else (1 - smooth((u - 0.62) / 0.08) if u < 0.70 else 0.0)
        p = _lean(p, 0.22 + 0.06 * (1 - up), (0.30, -1.22))
        T = _T(p)
        top = reach if reach else T(1.35, 1.50)
        low, high = (top[0], top[1] - 0.12 * R), (top[0] - f * 0.10 * R, top[1] - 1.20 * R)
        wr = _lerp(low, high, up)
        p["near"] = _arm(T(0.02, 0.24), wr, R, f)
        p["far"] = _arm(T(-0.06, 0.26), (wr[0] - f * 0.30 * R, wr[1] + 0.05 * R), R, f)
        p["hands"] = ["fist", "fist"]
        if 0.70 <= u < 0.84:   # the jolt (in and out: not a jump)
            p["head"] = (p["head"][0], p["head"][1] + 0.06 * R * math.sin(math.pi * (u - 0.70) / 0.14))
        return p, eyes

    if action == "throwing":   # wind up, hurl, follow through; the phone flies on and shatters against the wall
        p = S.pose_stand(x, gnd, f, R, lift=0.1, walk=0.6, phase=math.pi / 2)
        T = _T(p)
        cyc = 2.6
        u = ((t + seed * 0.21) % cyc) / cyc
        back, front, low, sh0 = T(-0.95, -0.55), T(1.45, 0.45), T(0.70, 1.20), T(0.02, 0.24)
        if u < 0.30:   # (drawn down, back and up behind his head: round the shoulder, not through it)
            wr = _swing(sh0, low, back, smooth(u / 0.30), over=False)
        elif u < 0.41:   # (over the shoulder, the elbow leading)
            wr = _swing(sh0, back, front, smooth((u - 0.30) / 0.11))
        elif u < 0.70:
            wr = front
        else:
            wr = _lerp(front, low, smooth((u - 0.70) / 0.30))
        lunge = smooth((u - 0.26) / 0.10) * (1 - smooth((u - 0.66) / 0.20)) if 0.26 < u < 0.86 else 0.0
        p = _lean(p, 0.05 + 0.25 * lunge, (0.22, -1.25))   # (into the throw and back: never in one frame)
        T = _T(p)
        p["near"] = _arm(T(0.02, 0.24), wr, R, f)
        p["hands"] = ["fist", "fist"]
        if u < 0.40:   # (let go as the hand comes through, not halfway)
            p["hold"] = {"kind": "phone", "at": wr}
        else:   # in flight, then the crash
            q = clamp((u - 0.40) / 0.12)
            start = T(1.45, 0.40)
            end = (start[0] + f * 3.6 * R, start[1] - 0.20 * R)
            at = (start[0] + (end[0] - start[0]) * q, start[1] + (end[1] - start[1]) * q - math.sin(math.pi * q) * 0.8 * R)
            p["hold"] = {"kind": "flying", "at": at if q < 1 else end, "spin": q * 9.0 * f,
                         "burst": clamp((u - 0.52) / 0.40) if u >= 0.52 else 0.0}
        return p, eyes

    if action == "punching_wall":   # a punch every second and a half; the wall cracks where it lands
        p = S.pose_stand(x, gnd, f, R, lift=0.0, walk=0.9, phase=math.pi / 2)
        q = _pulse(t + seed * 0.11, 1.5, on=0.40)
        p = _lean(p, 0.08 + 0.10 * q, (0.18, -1.26))
        T = _T(p)
        wr = T(0.75 + 1.05 * q, 0.62 - 0.10 * q)
        p["near"] = _arm(T(0.02, 0.24), wr, R, f, out=True)
        p["far"] = _arm(T(-0.06, 0.26), T(0.62, 0.70), R, f, out=True)
        p["hands"] = ["fist", "fist"]
        hit = T(1.95, 0.52)
        p["hold"] = {"kind": "crack", "at": (hit[0] + f * 0.20 * R, hit[1]), "q": q, "f": f, "t": t}
        return p, eyes

    if action == "shouting":   # leaning in, the head thrust forward with every shout, the arms back
        p = S.pose_stand(x, gnd, f, R, walk=0.8, phase=math.pi / 2)
        q = _pulse(t + seed * 0.17, 1.2, on=0.55)
        p = _lean(p, 0.18 + 0.08 * q, (0.38 + 0.10 * q, -1.18))
        T = _T(p)
        p["near"] = _arm(T(0.02, 0.24), T(-0.55, 1.55), R, f)
        p["far"] = _arm(T(-0.06, 0.26), T(-0.70, 1.45), R, f)
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "shaking_fists":   # both fists up before him, trembling
        p = S.pose_stand(x, gnd, f, R, lift=0.15)
        T = _T(p)
        j = 0.05 * R * math.sin(t * 38.0)
        p["near"] = _arm(T(0.02, 0.24), (T(1.10, 0.25)[0] + j, T(1.10, 0.25)[1]), R, f)
        p["far"] = _arm(T(-0.06, 0.26), (T(0.90, 0.35)[0] - j, T(0.90, 0.35)[1]), R, f)
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "hiding_phone":   # caught: the phone whipped behind his back, a start
        p = _seat_or_stand(mark, gnd, f, R, lift=0.2)
        jump = 0.10 * R * math.exp(-max(0.0, t) * 4.0)
        p["head"] = (p["head"][0] - f * jump, p["head"][1] - jump)
        T = _T(p)
        behind = T(-0.95, 1.40)
        p["far"] = _arm(T(-0.06, 0.26), behind, R, f)
        p["far_hold"] = {"kind": "phone", "at": behind}
        p["near"] = _arm(T(0.02, 0.24), T(0.85, 1.00), R, f)
        p["hands"] = ["fist", "open"]
        return p, eyes

    if action == "staring":   # leaning in, the head pushed forward, transfixed
        p = _seat_or_stand(mark, gnd, f, R)
        p = _lean(p, (0.30 if p.get("sitting") else 0.20) + 0.02 * math.sin(t * 0.9), (0.42, -1.18))
        T = _T(p)
        p["near"] = _arm(T(0.02, 0.24), T(0.55, 1.60) if not p.get("sitting") else T(0.90, 1.70), R, f)
        p["far"] = None
        return p, eyes

    if action == "doomscrolling":   # hunched, the head down over the phone, the thumb flicking
        p = _seat_or_stand(mark, gnd, f, R, slump=0.7)
        p = _lean(p, 0.30 if p.get("sitting") else 0.22, (0.40, -1.05))
        T = _T(p)
        flick = 0.04 * R * max(0.0, math.sin(t * math.tau * 1.4))
        ph = T(0.95, 0.70)
        p["near"] = _arm(T(0.02, 0.24), (ph[0], ph[1] - flick), R, f)
        p["hold"] = {"kind": "phone", "at": (ph[0] + f * 0.05 * R, ph[1] - 0.15 * R - flick)}
        p["lift"] = -0.6
        return p, eyes

    if action == "sprawled":   # lying limp, an arm hanging off the edge
        y = mark.get("y", gnd - 1.04 * R)
        p = S.pose_lie(x, y, f, R, arms="rest")
        hx, hy = p["head"]
        sh = p["near"][0]
        swing = 0.05 * R * math.sin(t * 0.8)
        p["near"] = (sh, (sh[0] + f * 0.15 * R, sh[1] + 1.05 * R), (sh[0] + f * 0.10 * R + swing, sh[1] + 1.95 * R))
        p["hands"] = [p["hands"][0], "open"]
        return p, eyes

    if action == "snoozing":   # the alarm rings; a hand slaps it quiet; it rings again
        y = mark.get("y", gnd - 1.04 * R)
        p = S.pose_lie(x, y, f, R, arms="rest")
        hx, hy = p["head"]
        cyc = 3.2
        u = ((t + seed * 0.07) % cyc) / cyc
        clock = (hx - f * 1.55 * R, hy + 0.35 * R)
        slap = smooth((u - 0.36) / 0.22) * (1 - smooth((u - 0.62) / 0.24)) if 0.36 <= u < 0.86 else 0.0
        sh = p["near"][0]
        rest = (sh[0] + f * 0.6 * R, sh[1] + 0.4 * R)
        p["near"] = _arm(sh, _swing(sh, rest, (clock[0], clock[1] - 0.25 * R), slap), R, f)   # (up and over his head)
        p["hold"] = {"kind": "alarm", "at": clock, "ringing": u < 0.57 or u > 0.9, "t": t}
        p["hands"] = [p["hands"][0], "open"]
        return p, eyes

    if action == "stretching":   # arms up and out, the body lifting, slowly
        p = _seat_or_stand(mark, gnd, f, R, lift=0.5)
        T = _T(p)
        q = 0.5 + 0.5 * math.sin(t * math.tau / 3.0)
        # (up and out beside the head: straight up, the big head hides them)
        p["near"] = _arm(T(0.02, 0.24), T(1.30 + 0.15 * q, -1.45 - 0.25 * q), R, f, out=True)
        p["far"] = _arm(T(-0.06, 0.26), T(-1.15 - 0.15 * q, -1.50 - 0.25 * q), R, f, out=True)
        p["hands"] = ["open", "open"]
        return p, eyes

    if action == "snacking":   # slumped, a bag on his lap, hand to mouth and back
        p = _seat_or_stand(mark, gnd, f, R, slump=0.6)
        T = _T(p)
        hx, hy = p["head"]
        bag = T(1.05, 1.55)
        u = ((t + seed * 0.19) % 2.2) / 2.2
        q = smooth(u / 0.32) if u < 0.32 else (1.0 if u < 0.48 else (1 - smooth((u - 0.48) / 0.34) if u < 0.82 else 0.0))
        wr = _lerp((bag[0], bag[1] - 0.30 * R), (hx + f * 0.85 * R, hy + 0.55 * R), q)
        p["near"] = _arm(T(0.02, 0.24), wr, R, f)
        p["far"] = _arm(T(-0.06, 0.26), (bag[0] - f * 0.25 * R, bag[1] + 0.05 * R), R, f)
        p["hold"] = {"kind": "chips", "at": bag}
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "watching_tv":   # sunk deep, the remote pointed lazily
        p = _seat_or_stand(mark, gnd, f, R, slump=0.95, lift=0.1)
        T = _T(p)
        rm = T(1.25, 1.05)
        p["near"] = _arm(T(0.02, 0.24), rm, R, f)
        p["hold"] = {"kind": "remote", "at": rm, "f": f}
        return p, eyes

    if action == "peeking":   # behind a doorway's edge: only his head and a hand round it
        p = S.pose_stand(x, gnd, f, R)
        p = _lean(p, 0.30, (0.30, -1.22))
        T = _T(p)
        hx, hy = p["head"]
        edge = hx - f * 0.15 * R
        top = hy - 3.2 * R
        x0, x1 = (edge - 4.0 * R, edge) if f > 0 else (edge, edge + 4.0 * R)
        p["front_slab"] = (x0, top, x1, gnd + 4.0)
        p["grip"] = (edge + f * 0.05 * R, hy + 0.85 * R)
        p["near"] = _arm(T(0.02, 0.24), T(0.80, 1.00), R, f)
        p["far"] = None
        return p, eyes

    if action == "clenching":   # a paper crushed in both fists, trembling
        p = _seat_or_stand(mark, gnd, f, R, lift=-0.1)
        T = _T(p)
        j = 0.03 * R * math.sin(t * 40.0)
        ball = (T(1.10, 0.85)[0] + j, T(1.10, 0.85)[1])
        p["near"] = _arm(T(0.02, 0.24), (ball[0] + f * 0.12 * R, ball[1]), R, f)
        p["far"] = _arm(T(-0.06, 0.26), (ball[0] - f * 0.12 * R, ball[1] + 0.05 * R), R, f)
        p["hold"] = {"kind": "paper_ball", "at": ball}
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "arms_crossed":
        return S.pose_stand(x, gnd, f, R, lift=0.50 + breath, arms="cross"), eyes

    if action == "admiring":   # at the mirror, chin up, a hand on the chin, turning a little to see himself
        p = S.pose_stand(x, gnd, f, R, lift=0.35 + 0.05 * math.sin(t * 1.2))
        T = _T(p)
        hx, hy = p["head"]
        p["near"] = _arm(T(0.02, 0.24), (hx + f * 0.55 * R, hy + 0.95 * R), R, f)
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "waving_off":   # a flick of the hand: not worth his time
        p = S.pose_stand(x, gnd, f, R, lift=0.40)
        T = _T(p)
        q = _pulse(t + seed * 0.09, 1.8, on=0.45)
        p["near"] = _arm(T(0.02, 0.24), _lerp(T(0.60, 0.95), T(1.30, 0.20), q), R, f)
        p["hands"] = ["fist", "open"]
        return p, eyes

    if action == "posing":   # fists on the hips, chest out, chin up
        p = S.pose_stand(x, gnd, f, R, lift=0.45 + breath, walk=0.5, phase=math.pi / 2)
        T = _T(p)
        p["near"] = (T(0.02, 0.24), T(0.85, 1.25), T(0.30, 2.10))
        p["far"] = (T(-0.06, 0.26), T(-0.85, 1.25), T(-0.30, 2.10))
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "curled_up":
        return S.pose_floor(x, gnd, f, R, slump=1.0, lift=breath), eyes

    if action == "sulking":
        p = _seat_or_stand(mark, gnd, f, R, slump=0.55, lift=-0.25)
        T = _T(p)
        p["near"] = (T(0.02, 0.24), T(0.16, 1.18), T(0.62, 1.02))
        p["far"] = None
        p["hands"] = ["hidden", "hidden"]
        return p, eyes

    if action == "hiding_bed":   # the blanket pulled up to his eyes, shaking a little
        y = mark.get("y", gnd - 1.04 * R)
        p = S.pose_lie(x, y, f, R, arms="rest")
        hx, hy = p["head"]
        j = 0.02 * R * math.sin(t * 30.0)
        p["head"] = (hx + j, hy)
        p["blanket"] = [(hx - f * 1.10 * R + j, hy + 0.22 * R), (hx + f * 0.40 * R + j, hy + 0.18 * R),
                        (hx + f * 1.30 * R, hy - 0.35 * R), (hx + f * 3.90 * R, hy - 0.45 * R),
                        (hx + f * 6.90 * R, hy - 0.05 * R), (hx + f * 7.10 * R, hy + 1.00 * R),
                        (hx - f * 1.15 * R, hy + 1.00 * R)]
        return p, eyes

    if action == "backing_away":   # stepping backwards, hands up before him
        dist = 1.1 * R * smooth(t / max(seconds, 0.5))
        u = 0.8 * (0.6 + 0.4 * math.sin(t * 2.0))
        p = S.pose_stand(x - f * dist, gnd, f, R, walk=u, phase=-t * 3.2, lift=-0.1)
        p = _lean(p, -0.10, (0.05, -1.28))
        T = _T(p)
        p["near"] = _arm(T(0.02, 0.24), T(1.20, 0.30), R, f, out=True)
        p["far"] = _arm(T(-0.06, 0.26), T(1.05, 0.40), R, f, out=True)
        p["hands"] = ["open", "open"]
        return p, eyes

    if action == "cowering":   # down on a knee, arms wrapped over his head
        from silhouette_actions import pose_kneel
        p = pose_kneel(x, gnd, f, R, bow=0.75)
        T = _T(p)
        hx, hy = p["head"]
        p["near"] = _arm(T(0.02, 0.24), (hx + f * 0.30 * R, hy - 0.85 * R), R, f, out=True)
        p["far"] = _arm(T(-0.06, 0.26), (hx - f * 0.35 * R, hy - 0.80 * R), R, f, out=True)
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "counting_money":   # at the table, flicking notes from one pile to the other
        if mark.get("kind") == "sit" and mark.get("seat") is not None:
            p = S.pose_sit(x, mark["seat"], gnd, f, R, slump=0.3, arms="desk", reach=reach)
        else:
            p = S.pose_stand(x, gnd, f, R, slump=0.3)
        T = _T(p)
        top = reach if reach else T(1.30, 1.40)
        u = ((t + seed * 0.05) % 1.1) / 1.1
        go = smooth(u / 0.55) if u < 0.55 else 1 - smooth((u - 0.55) / 0.45)   # (across with a note, back for the next)
        flick = math.sin(math.pi * min(1.0, u / 0.55))
        p["near"] = _arm(T(0.02, 0.24), (top[0] + f * (0.05 + 0.35 * go) * R, top[1] - (0.10 + 0.25 * flick) * R), R, f)
        p["far"] = _arm(T(-0.06, 0.26), (top[0] - f * 0.25 * R, top[1] - 0.12 * R), R, f)
        p["hold"] = {"kind": "money_piles", "at": (top[0], top[1] - 0.02 * R), "f": f}
        p["hands"] = ["fist", "open"]
        p["lift"] = -0.5
        return p, eyes

    if action == "hugging_bag":   # a fat bag of money clutched to his chest
        p = _seat_or_stand(mark, gnd, f, R, slump=0.2)
        T = _T(p)
        bag = T(1.05, 1.05)
        p["hold"] = {"kind": "moneybag", "at": bag, "R": R}
        p["near"] = _arm(T(0.02, 0.24), T(1.35, 1.00), R, f, out=True)
        p["far"] = _arm(T(-0.06, 0.26), T(1.15, 1.20), R, f, out=True)
        p["hands"] = ["fist", "fist"]
        return p, eyes

    if action == "grabbing":   # a lunge of the hand, open, closing on it, pulled back
        p = S.pose_stand(x, gnd, f, R, walk=0.7, phase=math.pi / 2)
        q = _pulse(t + seed * 0.15, 1.6, on=0.55)
        p = _lean(p, 0.10 + 0.20 * q, (0.25 + 0.15 * q, -1.24))
        T = _T(p)
        p["near"] = _arm(T(0.02, 0.24), T(0.80 + 1.10 * q, 0.80), R, f, out=True)
        p["hands"] = ["fist", "open" if q > 0.2 else "fist"]
        return p, eyes

    if action == "rising":   # up off the bed's edge in one go, then standing tall
        sit = S.pose_sit(x, mark.get("seat", gnd - 1.8 * R), gnd, f, R) if mark.get("seat") is not None else None
        stand = S.pose_stand(x + f * 0.9 * R, gnd, f, R, lift=0.25)
        u = smooth(clamp((t - 0.4) / 1.1))
        if sit is None or u >= 1.0:
            p = stand
        else:
            p = _blend(sit, stand, u)
        return p, eyes

    if action == "ticking":   # at the board, a tick, a pause, another
        p = S.pose_stand(x, gnd, f, R, lift=0.2)
        T = _T(p)
        pt = mark.get("point") or T(1.60, -0.30)
        u = ((t + seed * 0.1) % 1.6) / 1.6
        row = int(((t + seed * 0.1) // 1.6) % 3)
        base = (pt[0] - f * 0.40 * R, pt[1] - 0.55 * R + row * 0.45 * R)
        if u < 0.25:
            pen = _lerp(base, (base[0] + f * 0.12 * R, base[1] + 0.15 * R), smooth(u / 0.25))
        elif u < 0.5:
            pen = _lerp((base[0] + f * 0.12 * R, base[1] + 0.15 * R), (base[0] + f * 0.42 * R, base[1] - 0.25 * R),
                        smooth((u - 0.25) / 0.25))
        elif u < 0.7:
            pen = (base[0] + f * 0.42 * R, base[1] - 0.25 * R)
        else:   # (on to the next row's start: never a jump there)
            nxt = (pt[0] - f * 0.40 * R, pt[1] - 0.55 * R + ((row + 1) % 3) * 0.45 * R)
            pen = _lerp((base[0] + f * 0.42 * R, base[1] - 0.25 * R), nxt, smooth((u - 0.7) / 0.3))
        p["near"] = _arm(T(0.02, 0.24), pen, R, f)
        p["hold"] = {"kind": "pen", "at": pen}
        return p, eyes

    if action == "watering":   # the can tipped over the plant, water falling
        p = S.pose_stand(x, gnd, f, R, lift=-0.3)
        T = _T(p)
        can = T(1.25, 1.20)
        p["near"] = _arm(T(0.02, 0.24), can, R, f)
        p["hold"] = {"kind": "can", "at": can, "f": f, "t": t}
        return p, eyes

    if action == "meditating":   # cross-legged on the floor, upright, hands on the knees
        hip = (x, gnd - 0.30 * R)
        p = {"f": f, "R": R, "H": hip, "S": (hip[0], hip[1] - 2.55 * R), "lift": 0.05 + breath,
             "hood_up": False, "sitting": True, "hem_max": 2.62}
        p["T"] = _T(p)
        T = p["T"]
        p["head"] = T(0.10, -1.28 + 0.02 * math.sin(t * 1.1))
        knee_n, knee_f = (hip[0] + f * 1.45 * R, gnd - 0.25 * R), (hip[0] - f * 0.95 * R, gnd - 0.20 * R)
        p["legs"] = [(hip, knee_f, (hip[0] + f * 0.40 * R, gnd - 0.05 * R)),
                     (hip, knee_n, (hip[0] - f * 0.20 * R, gnd - 0.08 * R))]
        p["near"] = _arm(T(0.02, 0.24), (knee_n[0] - f * 0.15 * R, knee_n[1] - 0.20 * R), R, f)
        p["far"] = None
        p["hold"] = None
        p["hands"] = ["fist", "open"]
        return p, eyes
    return None


def _blend(a: dict, b: dict, u: float) -> dict:
    """Between two poses of the same person (getting up): every joint part of the way from a to b."""
    out = dict(b if u >= 0.5 else a)
    for k in ("S", "H", "head"):
        out[k] = _lerp(a[k], b[k], u)
    out["legs"] = [tuple(_lerp(p, q, u) for p, q in zip(la, lb)) for la, lb in zip(a["legs"], b["legs"])]
    for k in ("near", "far"):
        if a.get(k) and b.get(k):
            out[k] = tuple(_lerp(p, q, u) for p, q in zip(a[k], b[k]))
    out["T"] = _T(out)
    out["sitting"] = u < 0.5
    return out


# --- what these hands hold (added to tools/silhouette.py's HOLDS) ----------------------------------------------------------
def _h_flying(p, h, R, f, pose):
    """His phone flying, spinning; then smashing against the wall: shards bursting out and falling."""
    x, y = h["at"]
    burst = h.get("burst", 0.0)
    if burst <= 0:
        a = h.get("spin", 0.0)
        c, s = math.cos(a), math.sin(a)
        pts = [(x + c * dx - s * dy, y + s * dx + c * dy) for dx, dy in
               ((-0.12 * R, -0.22 * R), (0.12 * R, -0.22 * R), (0.12 * R, 0.22 * R), (-0.12 * R, 0.22 * R))]
        p.poly(np.array(pts), hexc("#141018"))
        p.poly(tube([(x - c * 0.06 * R, y - s * 0.06 * R), (x + c * 0.06 * R, y + s * 0.06 * R)], 0.05 * R), S.PAL["screen"], 0.8)
        return None
    r = np.random.default_rng(7)
    for k in range(9):
        ang = -math.pi / 2 + r.uniform(-1.4, 1.4)
        sp = r.uniform(0.8, 1.6) * R
        dx = -f * abs(math.cos(ang)) * sp * burst + r.uniform(-0.2, 0.2) * R * burst
        dy = math.sin(ang) * sp * burst + 2.4 * R * burst * burst
        size = r.uniform(0.04, 0.09) * R
        sx, sy = x + dx, y + dy
        p.poly(np.array([(sx, sy - size), (sx + size, sy + size * 0.6), (sx - size * 0.8, sy + size)]),
               S.PAL["screen"] if k % 3 == 0 else hexc("#2A2430"), 1.0 - 0.6 * burst)
    if burst < 0.35:   # the flash where it hit
        p.glow(x, y, 0.6 * R, 0.6 * R, hexc("#FFFFFF"), 0.8 * (1 - burst / 0.35))
    return None


def _h_crack(p, h, R, f, pose):
    """Where the punches land: a burst of lines on the hit, the wall's cracks spreading as the punches go on."""
    x, y = h["at"]
    q = h.get("q", 0.0)
    for k, ang in enumerate((-1.2, -0.5, 0.3, 1.0, 1.9, 2.6)):
        L = (0.35 + 0.12 * (k % 3)) * R
        pts = [(x, y)]
        for j in range(3):
            pts.append((pts[-1][0] - f * math.cos(ang) * L / 3 + (0.05 * R if j % 2 else -0.05 * R),
                        pts[-1][1] + math.sin(ang) * L / 3))
        p.poly(tube(pts, 0.035 * R, 0.01 * R, k=2), hexc("#D8D0E0"), 0.75)
    if q > 0.75:
        I.draw(p, "sparkle", x, y, 0.45 * R * q, "dark", 0.0)


def _h_chips(p, h, R, f, pose):
    x, y = h["at"]
    p.poly(rr(x - 0.32 * R, y - 0.42 * R, 0.64 * R, 0.80 * R, 0.10 * R), hexc("#E04A3A"))
    p.poly(rr(x - 0.32 * R, y - 0.42 * R, 0.64 * R, 0.12 * R, 0.04 * R), hexc("#F2C94C"))
    p.circle(x, y - 0.02 * R, 0.16 * R, hexc("#F2C94C"))


def _h_remote(p, h, R, f, pose):
    x, y = h["at"]
    ff = h.get("f", f)
    p.poly(S.rell(x + ff * 0.12 * R, y - 0.04 * R, 0.26 * R, 0.07 * R, -0.25 * ff), hexc("#1E1A24"))
    p.circle(x + ff * 0.30 * R, y - 0.08 * R, 0.035 * R, hexc("#E8453C"))


def _h_paper_ball(p, h, R, f, pose):
    x, y = h["at"]
    r = np.random.default_rng(3)
    pts = [(x + math.cos(a) * 0.24 * R * r.uniform(0.75, 1.15), y + math.sin(a) * 0.22 * R * r.uniform(0.75, 1.15))
           for a in np.linspace(0, math.tau, 11, endpoint=False)]
    p.poly(np.array(pts), PAPER)
    for k in range(3):
        a = k * 2.1
        p.poly(tube([(x, y), (x + math.cos(a) * 0.16 * R, y + math.sin(a) * 0.14 * R)], 0.02 * R), hexc("#A8A0B0"), 0.8)


def _h_moneybag(p, h, R, f, pose):
    x, y = h["at"]
    I.draw(p, "moneybag", x, y, 0.62 * R, "cream", 0.0)


def _h_money_piles(p, h, R, f, pose):
    x, y = h["at"]
    ff = h.get("f", f)
    for k, (dx, n) in enumerate(((-0.35, 5), (0.35, 3))):
        cx = x + ff * dx * R
        for j in range(n):
            p.poly(rr(cx - 0.28 * R, y - (0.07 + 0.07 * j) * R, 0.56 * R, 0.07 * R, 0.02 * R),
                   hexc("#3E8F64") if j % 2 else hexc("#2E7350"))


def _h_alarm(p, h, R, f, pose):
    x, y = h["at"]
    I.draw(p, "alarm" if h.get("ringing") else "clock", x, y, 0.32 * R, "dark", h.get("t", 0.0))


def _h_can(p, h, R, f, pose):
    """A watering can tipped forward, water falling from its spout."""
    x, y = h["at"]
    ff = h.get("f", f)
    p.poly(rr(x - 0.30 * R, y - 0.25 * R, 0.60 * R, 0.45 * R, 0.08 * R), CAN)
    p.poly(tube([(x + ff * 0.25 * R, y - 0.05 * R), (x + ff * 0.75 * R, y - 0.30 * R)], 0.07 * R, 0.05 * R), CAN)
    t = h.get("t", 0.0)
    for k in range(6):
        u = ((t * 1.8 + k / 6) % 1.0)
        p.circle(x + ff * (0.78 + 0.10 * u) * R, y - 0.28 * R + u * 1.1 * R, 0.04 * R, WATER, 0.9 * (1 - u))


HOLDS = {"flying": (_h_flying, False), "crack": (_h_crack, False), "chips": (_h_chips, False),
         "remote": (_h_remote, False), "paper_ball": (_h_paper_ball, False), "moneybag": (_h_moneybag, False),
         "money_piles": (_h_money_piles, True), "alarm": (_h_alarm, True), "can": (_h_can, False)}
S.HOLDS.update(HOLDS)
