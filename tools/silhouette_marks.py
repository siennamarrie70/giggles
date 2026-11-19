"""
Comic marks round a head in the films, moving gently and never flickering (the look's rule): steam puffing from an angry
head, a throbbing vein, sweat drops, drool, Zzz rising from a sleeper, hearts or $ floating up, a rain cloud over him,
flies, dizzy stars, a jolt, trembling lines, ? and !, sparkles, notification dots; and two glows behind a whole figure
(envy's green, rage's red). The pictures are tools/silhouette_icons.py's.

  draw(p, name, head, R, f, t, seed=0)   a mark round the head (hx, hy) of radius R of someone facing f, t seconds in
  behind(p, name, pose, t)              an aura: a glow behind the whole figure (drawn before the people, so it rims them)
  shake(pose, t)                        a trembling person's pose, shaken a little (marks "tremble")
  MARKS                                 every name, with what it shows (the storyboard's words)
"""

import math

import numpy as np

import silhouette as S
from silhouette import hexc, tube
import silhouette_icons as I
import silhouette_words as W

MARKS = W.MARKS   # (the words live in tools/silhouette_words.py)
AURAS = {"aura_green": hexc("#4CC38A"), "aura_red": hexc("#FF3A2A")}
REACH = {"raincloud": 2.45, "question": 2.15, "exclaim": 2.15, "zzz": 2.25, "hearts": 2.30, "dollars": 2.30,
         "steam": 1.95, "stars": 1.55, "jolt": 1.55, "notify": 1.65, "sparkles": 1.75, "vein": 1.15}
# (how far above a head's middle a mark reaches, in head radii: a framing keeps it in)
LIGHT = hexc("#E4DEEA")
SWEAT = hexc("#BFE4FF")


def _cycle(t, period, k=0, n=1):
    """0 -> 1 over a period, the k-th of n spread evenly through it."""
    return ((t / period) + k / n) % 1.0


def _fade(u, a=0.15, b=0.75):
    """In over [0, a], out over [b, 1]."""
    return S.smooth(u / a) * (1 - S.smooth((u - b) / (1 - b)))


def draw(p, name: str, head, R: float, f: int, t: float, seed: int = 0) -> None:
    hx, hy = head
    t = t + (seed % 97) * 0.13   # (two people's marks never move in step)
    if name == "steam":
        for k in range(4):
            u = _cycle(t, 1.3, k, 4)
            side = -1 if k % 2 else 1
            x = hx + side * (0.70 + 0.35 * u) * R
            y = hy - (0.80 + 0.85 * u) * R
            r = (0.20 + 0.25 * u) * R
            for dx, dy, q in ((-0.4, 0.1, 0.8), (0.0, -0.2, 1.0), (0.4, 0.05, 0.75)):
                p.circle(x + dx * r, y + dy * r, r * q, LIGHT, 0.85 * _fade(u))
    elif name == "vein":
        beat = 1.0 + 0.18 * abs(math.sin(t * math.pi * 1.6))
        I.draw(p, "vein", hx + f * 0.42 * R, hy - 0.78 * R, 0.30 * R * beat, "dark", t)
    elif name == "sweat":
        for k in range(2):
            u = _cycle(t, 1.6, k, 2)
            x = hx + (-f * 0.98 + (0.25 * k) * -f) * R
            y = hy + (-0.45 + 0.75 * u) * R
            a = _fade(u, 0.12, 0.7)
            b = np.linspace(-0.15 * math.pi, 1.15 * math.pi, 16)
            drop = np.vstack([np.stack([x + np.cos(b) * 0.11 * R, y + 0.07 * R + np.sin(b) * 0.13 * R], 1),
                              [(x, y - 0.20 * R)]])
            p.poly(drop, SWEAT, 0.95 * a)
    elif name == "drool":
        u = _cycle(t, 2.6)
        mx, my = hx + f * 0.78 * R, hy + 0.62 * R
        stretch = (0.10 + 0.55 * S.smooth(u / 0.75)) * R
        fall = max(0.0, (u - 0.75) / 0.25)
        if fall <= 0:
            p.poly(tube([(mx, my), (mx + f * 0.02 * R, my + stretch)], 0.07 * R, 0.13 * R, k=2), SWEAT, 0.9)
            p.circle(mx + f * 0.02 * R, my + stretch, 0.10 * R, SWEAT, 0.9)
        else:
            p.circle(mx + f * 0.02 * R, my + stretch + fall * 0.8 * R, 0.09 * R, SWEAT, 0.9 * (1 - fall))
            p.poly(tube([(mx, my), (mx, my + 0.10 * R)], 0.06 * R, k=2), SWEAT, 0.9)
    elif name == "zzz":
        for k in range(3):
            u = _cycle(t, 2.6, k, 3)
            x = hx + f * (0.55 + 0.75 * u) * R + 0.10 * R * math.sin(t * 1.7 + k)
            y = hy - (0.95 + 1.10 * u) * R
            s = (0.12 + 0.18 * u) * R
            I._line(p, x, y, s, [(-0.7, -0.8), (0.7, -0.8), (-0.7, 0.8), (0.7, 0.8)], 0.24, I.CREAM, _fade(u), k=2)
    elif name in ("hearts", "dollars"):
        for k in range(3):
            u = _cycle(t, 2.2, k, 3)
            x = hx + (k - 1) * 0.55 * R + 0.15 * R * math.sin(t * 2.6 + k * 2)
            y = hy - (1.05 + 1.05 * u) * R
            s = (0.16 + 0.12 * u) * R * _fade(u, 0.2, 0.8) ** 0.5
            if s > 0.02 * R:
                I.draw(p, "heart" if name == "hearts" else "dollar", x, y, s, "dark", t)
    elif name == "raincloud":
        I.draw(p, "cloud_rain", hx, hy - 1.75 * R + 0.05 * R * math.sin(t * 1.3), 0.62 * R, "dark", t)
    elif name == "flies":
        for k in range(3):
            a = t * (2.1 + 0.4 * k) + k * 2.1
            x = hx + 1.35 * R * math.cos(a) + 0.15 * R * math.sin(a * 3.1)
            y = hy - 0.25 * R + 0.65 * R * math.sin(a * 1.4 + k)
            I.draw(p, "fly", x, y, 0.24 * R, "dark", t * 3 + k)
    elif name == "stars":
        for k in range(4):
            a = t * 2.2 + k * math.pi / 2
            x, y = hx + 0.95 * R * math.cos(a), hy - 1.18 * R + 0.25 * R * math.sin(a)
            I.draw(p, "star", x, y, (0.15 + 0.03 * math.sin(a)) * R, "dark", t)
    elif name == "jolt":
        u = _cycle(t, 1.8)
        s = 0.32 * R * (1.0 + 0.25 * S.spring(min(1.0, u * 3)))
        I.draw(p, "bolt", hx - f * 0.95 * R, hy - 0.95 * R, s, "dark", t)
        I.draw(p, "bolt", hx + f * 1.05 * R, hy - 1.15 * R, s * 0.7, "dark", t)
    elif name == "tremble":
        jit = 0.04 * R * math.sin(t * 41.0)
        for side in (-1, 1):
            for k in range(2):
                x = hx + side * (1.22 + 0.18 * k) * R + jit
                p.poly(tube([(x, hy - (0.25 - 0.15 * k) * R), (x, hy + (0.20 + 0.10 * k) * R)], 0.07 * R, k=2), LIGHT,
                       0.85)
    elif name == "question":
        I.draw(p, "question", hx + f * 0.30 * R, hy - 1.65 * R + 0.05 * R * math.sin(t * 2.0), 0.38 * R, "dark", t)
    elif name == "exclaim":
        pop = S.spring(min(1.0, t / 0.45)) if t < 0.45 else 1.0
        I.draw(p, "exclaim", hx + f * 0.20 * R, hy - 1.65 * R, 0.42 * R * max(0.2, pop), "dark", t)
    elif name == "sparkles":
        for k, (u, v) in enumerate(((-1.15, -0.85), (1.20, -0.55), (0.30, -1.45), (-0.55, -1.40))):
            tw = 0.55 + 0.45 * math.sin(t * 3.2 + k * 1.7) ** 2
            I.draw(p, "sparkle", hx + u * R, hy + v * R, 0.20 * R * tw, "dark", t)
    elif name == "notify":
        for k in range(4):
            u = _cycle(t, 1.9, k, 4)
            a = -2.6 + k * 0.75
            x, y = hx + math.cos(a) * 1.45 * R, hy + math.sin(a) * 1.25 * R - 0.15 * R
            s = 0.17 * R * S.spring(min(1.0, u * 4)) * (1 - S.smooth((u - 0.8) / 0.2))
            if s > 0.02 * R:
                I.draw(p, "dot", x, y, s, "dark", t)


def behind(p, name: str, pose: dict, t: float) -> None:
    """An aura's glow behind someone (drawn on an additive light layer before the people)."""
    if name not in AURAS:
        return
    hx, hy = pose["head"]
    R = pose["R"]
    hipx, hipy = pose["H"]
    pulse = 0.30 + 0.10 * math.sin(t * math.tau / 1.6)
    p.glow((hx + hipx) / 2, (hy + hipy) / 2, 2.4 * R, 3.6 * R, AURAS[name], pulse)
    p.glow(hx, hy, 1.8 * R, 1.8 * R, AURAS[name], pulse * 0.8)


def shake(pose: dict, t: float) -> dict:
    """Someone trembling: their whole body shaken a little, fast (fear, rage held in)."""
    dx = 0.035 * pose["R"] * math.sin(t * 41.0)

    def mv(pt):
        return (pt[0] + dx, pt[1])
    out = dict(pose)
    for k in ("S", "H", "head"):
        out[k] = mv(pose[k])
    for k in ("near", "far"):
        if pose.get(k):
            out[k] = tuple(mv(q) for q in pose[k])
    if pose.get("legs"):
        out["legs"] = [tuple(mv(q) if i == 0 else q for i, q in enumerate(leg)) for leg in pose["legs"]]
    out["T"] = S.spine(out["S"], out["H"], out["f"], out["R"])[0]
    if pose.get("hold") and pose["hold"].get("at") is not None:
        out["hold"] = {**pose["hold"], "at": mv(pose["hold"]["at"])}
    return out
