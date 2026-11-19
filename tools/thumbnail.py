"""
The stories' thumbnail (1280x720), in the template of the 2026-11-16 style test the owner saw (from their reference
picture): him big on the left in the story's chosen moment (outlined like a sticker, the coral rim, lit from the left),
the story's own place dimmed and softened behind him, comic marks for his mood, the words on the right (a white lead-in,
the punch big in yellow, a dry-brush underline) and a red arrow from the words to him. The words and the moment are
Agent 3's (the storyboard's "thumbnail": shot, lead, punch), or yours from the Studio.

Usage:
    python tools/thumbnail.py story.json 11 "ONE TEXT" "DESTROYED EVERYTHING" out.jpg    # shot 11 (1 = the first)
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent)]

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import silhouette as S  # noqa: E402
import silhouette_render as SR  # noqa: E402

W, H = SR.THUMB
YELLOW, WHITE, RED = S.hexc("#FFD21E"), S.hexc("#FFFFFF"), S.hexc("#E8221F")
INK = S.hexc("#09080C")
SITTING = ("typing", "sitting", "slumped", "head_in_hands", "phone", "lying_awake", "asleep")


# --- small helpers ------------------------------------------------------------------------------------------------------------
def layer(size=(W, H)):
    return np.zeros((size[1], size[0], 4), np.float32)


def flat_view():
    return S.View(0, 0, 1.0, 0, 0)


def comp(frame, lay):
    S.over(frame, lay)


def dilate(a, px):
    if px <= 0:
        return a
    k = int(math.ceil(px)) * 2 + 1
    return cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


def outlined(lay, px, color=INK, soft=0.8):
    """A premultiplied layer with a solid outline `px` wide round its shape (a sticker's edge)."""
    a = lay[..., 3]
    o = cv2.GaussianBlur(dilate((a > 0.02).astype(np.float32), px), (0, 0), soft)
    out = np.zeros_like(lay)
    out[..., :3] = np.asarray(color, np.float32) * o[..., None]
    out[..., 3] = o
    S.over(out[..., :3], lay)
    out[..., 3] = out[..., 3] * (1 - a) + a
    return out


def shifted(a, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(a, M, (a.shape[1], a.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def shadow(lay, dx, dy, blur, alpha):
    out = np.zeros_like(lay)
    out[..., 3] = shifted(cv2.GaussianBlur(lay[..., 3], (0, 0), blur) * alpha, dx, dy)
    return out


def noise(shape, sigma, seed):
    n = cv2.GaussianBlur(np.random.default_rng(seed).normal(0, 1, shape).astype(np.float32), (0, 0), sigma)
    return n / max(1e-6, float(n.std()))


# --- the place behind him ------------------------------------------------------------------------------------------------------
def _old_place(p, size):
    import silhouette_places as places
    import silhouette_sets as sets

    name = p["set"]
    if name == "desk_room":
        return sets.DeskRoom(size, label="", light=p["light"], rain=p["rain"])
    if name == "street":
        return sets.RainStreet(size, light=p["light"], rain=p["rain"], center=p.get("center"))
    if name == "hospital":
        return sets.HospitalRoom(size, light=p["light"], rain=p["rain"], center=p.get("center"))
    if name == "hallway":
        return places.Hallway(size, p["light"], p["rain"], p.get("center"), open_door=p.get("open_door", False))
    return places.PLACES[name](size, p["light"], p["rain"], p.get("center"))


def backdrop(story, shot, at, dim=0.50, blur=1.8, sat=0.70):
    """The shot's place, wide, without him (anyone else stays), full-bleed, dimmed, a little desaturated and softened."""
    idx = int(at * S.FPS)
    p = SR.plan_for(story, {**shot, "framing": "wide"}, (W, H))
    if p.get("composed"):
        import silhouette_board as SB
        import silhouette_scene as SC

        obj = SC.build(p["spec"], (W, H), p["light"], p["weather"], tuple(p["effects"]), center=p["center"],
                       seed=p["seed"], height=p["height"])
        obj.finish.bar = 0
        st = SB.state(p, obj, at, {"t0": 0.0, "no_label": True, "no_bubbles": True})   # (never a bubble on a thumbnail)
        if p["people"] and p["people"][-1]["who"] == "him":
            st["actors"] = st["actors"][:-1]
        frame = obj.frame(idx, st)
    else:
        obj = _old_place(p, (W, H))
        obj.finish.bar = 0
        st = SR.state(p, obj, at, idx, {"t0": 0.0, "no_label": True})
        if p["set"] == "desk_room":
            obj._draw_figure = lambda paint, st_: None
            frame = obj.draw(idx, st)
        else:
            st["actors"] = [a for a in st["actors"][1:]] if p["him"] != "none" else st["actors"]
            frame = obj.frame(idx, st)
    frame = cv2.GaussianBlur(frame, (0, 0), blur)
    lum = frame.mean(axis=2, keepdims=True)
    return (lum + (frame - lum) * sat) * dim


# --- him ---------------------------------------------------------------------------------------------------------------------------
def his_shot(story, shot) -> dict:
    """What he does in the chosen shot, in the rig's words: {"pose" (silhouette_words.POSES), "desk" (a desk before him),
    "mood", "event", "event_at", "seed"}."""
    import silhouette_actions as A
    import silhouette_board as SB

    seconds = float(shot.get("seconds") or 4.0)
    if shot.get("place") and not shot.get("set") and not SB.place_of(story, shot["place"]).get("set"):
        him = shot.get("him") or {}
        action = him.get("action") or "standing"
        pose = SB.OLD_POSE.get(action, action)
        if pose not in SR.POSES or pose == "none":
            pose = "standing"
        place = SB.place_of(story, shot["place"])
        mark = SB.probe(place["spec"], place.get("seed") or place["id"])["marks"].get(him.get("mark") or "")
        desk = bool(isinstance(mark, dict) and mark.get("reach") and mark.get("kind") == "sit")
        laptop = desk and mark.get("thing") == "desk"
        mood = him.get("eyes") or A.EYES.get(action, ("open",))[0]
    else:
        old = SB.old_shot(story, shot) if shot.get("place") and not shot.get("set") else shot
        pose = old.get("him") or "none"
        if pose == "none":
            pose = "standing"
        desk = laptop = old.get("set") in ("desk_room", "office", "bright_office") and pose in SITTING
        mood = old.get("eyes")
    event = shot.get("event") or "none"
    if event == "head_turn":
        mood = "wide"
    return {"pose": pose, "desk": desk, "laptop": laptop, "mood": mood, "event": event if event in SR.EVENTS else "none",
            "event_at": float(shot.get("event_at", 0.45)) * seconds, "seconds": seconds, "seed": int(shot.get("seed") or 7)}


def his_moment(h, at, R, head_at, f=-1):
    """His pose and eyes at `at`, drawn R big with his head at head_at, facing f; plus what's round him (a desk in front,
    a chair behind)."""
    pose_name = h["pose"]
    kind = "sit" if pose_name in SITTING else "stand"
    if pose_name in ("lying_awake",):
        pose_name = "phone"
    bowed = pose_name in ("asleep", "head_in_hands", "slumped")
    if bowed:
        pose_name = "sitting"
    if pose_name in ("running", "pushups", "walking", "floor"):
        pose_name, kind = "standing", "stand"
    m = {"kind": kind, "x": 0.0, "seat": 0.0, "f": f, "lift": -0.45 if bowed else 0.0}
    if kind == "sit" and h["desk"]:
        m["reach"] = (f * 1.45 * R, -1.15 * R)
    if pose_name == "carrying_box":
        m["arms"] = "box"
    pp = {"R": R, "ground": 1.375 * R if kind == "sit" else 0.0, "rain": False, "seconds": h["seconds"],
          "event": h["event"], "event_at": h["event_at"], "set": "thumbnail"}
    actor = SR.person_at(pp, m, pose_name, at, "him", h["mood"] if h["mood"] in S.MOODS else None, True, h["seed"])
    pose = actor["pose"]
    if not pose.get("face_hidden"):   # (big, the head sits down in the hood: no stick of a neck under it)
        pose["head"] = (pose["head"][0], pose["head"][1] + 0.30 * R)
    dx, dy = head_at[0] - pose["head"][0], head_at[1] - pose["head"][1]
    pose = shift_pose(pose, dx, dy)
    reach = (m["reach"][0] + dx, m["reach"][1] + dy) if m.get("reach") else None
    eyes = actor["eyes"]
    if eyes is not None:
        eyes.size *= 1.25
    return {"pose": pose, "eyes": eyes, "desk": reach, "kind": kind, "hip": pose["H"], "R": R, "f": f}


def shift_pose(pose, dx, dy):
    def sh(q):
        return (q[0] + dx, q[1] + dy)
    out = dict(pose)
    T0 = pose["T"]
    out["T"] = lambda u, v: sh(T0(u, v))
    for key in ("S", "H", "head"):
        out[key] = sh(pose[key])
    out["legs"] = [tuple(sh(q) for q in leg) for leg in pose["legs"]]
    for key in ("near", "far"):
        if pose.get(key):
            out[key] = tuple(sh(q) for q in pose[key])
    if pose.get("hold"):
        out["hold"] = {**pose["hold"], "at": sh(pose["hold"]["at"])}
    return out


def draw_him(frame, him, rim=True, outline=6.0, light_from=(-1.0, -0.3)):
    """Him as a sticker: the dark outline round him, the coral rim on the lit side, his hoodie lit from the left."""
    R = him["R"]
    base, lit = layer(), layer()
    S.draw_person(S.Paint(base, flat_view()), him["pose"], S.Look("#2B6470", hood=True, strings=True, build=1.12),
                  him["eyes"])
    S.draw_person(S.Paint(lit, flat_view()), him["pose"], S.Look("#357D8A", hood=True, strings=True, build=1.12),
                  him["eyes"])
    xs = np.arange(W, dtype=np.float32)
    hx = him["pose"]["head"][0]
    ramp = np.clip(0.5 - (xs - (hx - 0.10 * R)) / (0.35 * R), 0, 1)
    ramp = (ramp * ramp * (3 - 2 * ramp))[None, :, None]
    fig = base * (1 - ramp) + lit * ramp
    if rim:
        fig = S.rim(fig, light_from[0] * 0.040 * R, light_from[1] * 0.040 * R, glow_px=0.06 * R, glow_a=0.30)
    fig = outlined(fig, outline)
    comp(frame, shadow(fig, 10, 12, 14, 0.55))
    comp(frame, fig)


def draw_chair(frame, him):
    R, f = him["R"], him["f"]
    lay = layer()
    p = S.Paint(lay, flat_view())
    x = him["hip"][0] - f * 0.95 * R
    top = him["pose"]["S"][1] + 0.15 * R
    p.poly(S.rr(x - 0.30 * R, top, 0.60 * R, H - top + 40, 0.25 * R), S.hexc("#241C2B"))
    p.poly(S.rr(x - 0.30 * R + 0.07 * R, top + 0.08 * R, 0.10 * R, 2.2 * R, 0.05 * R), S.hexc("#4A4252"), 0.9)
    comp(frame, outlined(lay, 5.0))


def desk_geometry(him):
    R, f = him["R"], him["f"]
    rx, ry = him["desk"]
    top = ry + 0.10 * R
    bx1 = rx + f * 0.10 * R
    return top, bx1 + f * 1.30 * R, bx1


def screen_light(frame, him, light=1.0):
    """The laptop's cold light on the wall and the air round it (drawn before him: his black head stays black)."""
    R, f = him["R"], him["f"]
    top, bx0, _ = desk_geometry(him)
    cx, cy = bx0 - f * 0.25 * R, top - 0.75 * R
    glow = layer()
    gp = S.Paint(glow, flat_view())
    gp.glow(cx, cy, 1.0 * R, 1.6 * R, S.PAL["screen"], 0.75 * light)
    gp.glow(cx - f * 1.4 * R, cy - 0.5 * R, 3.4 * R, 3.0 * R, S.PAL["screen"], 0.20 * light)
    frame += glow[..., :3]


def draw_desk(frame, him, light, laptop=True):
    """The desk (or the table) in front of him (to the left: he faces left), the laptop on it, its screen turned to him;
    returns where the screen glows (None: a table, no laptop)."""
    R, f = him["R"], him["f"]
    rx, ry = him["desk"]
    top, bx0, bx1 = desk_geometry(him)
    edge = rx - f * 0.55 * R
    glow, lay = layer(), layer()
    gp, p = S.Paint(glow, flat_view()), S.Paint(lay, flat_view())
    x0, x1 = (-40, edge) if f < 0 else (edge, W + 40)
    p.poly(S.rect(x0, top, x1 - x0, 0.09 * R), S.hexc("#8A6F78"))
    p.poly(S.rect(x0, top + 0.09 * R, x1 - x0, H - top), S.hexc("#2C1F2F"))
    if not laptop:
        comp(frame, outlined(lay, 4.0))
        return None
    p.poly(S.rect(min(bx0, bx1), top - 0.07 * R, abs(bx1 - bx0), 0.07 * R), S.hexc("#1B1320"))
    b0, b1 = (bx0, top - 0.05 * R), (bx0 - f * 0.30 * R, top - 0.08 * R)
    t0, t1 = (bx0 + f * 0.24 * R, top - 1.55 * R), (bx0 + f * 0.02 * R, top - 1.62 * R)
    p.poly(np.array([(b0[0] + f * 0.08 * R, b0[1]), b0, t0, (t0[0] + f * 0.08 * R, t0[1] + 0.02 * R)]), S.hexc("#141018"))
    face = np.array([b0, b1, t1, t0])
    ys0, ys1 = t0[1], b0[1]

    def screen(px, py):
        u = np.clip((py - ys0) / (ys1 - ys0), 0, 1)[..., None]
        return S.hexc("#F2F8FF")[None, None, :] * (1 - u) + S.hexc("#8FB8F0")[None, None, :] * u
    p.poly(face, screen)
    cx, cy = (b1[0] + t1[0]) / 2, (b1[1] + t1[1]) / 2
    gp.glow(cx, cy, 0.35 * R, 0.9 * R, S.PAL["screen"], 0.55 * light)
    comp(frame, outlined(lay, 4.0))
    frame += glow[..., :3]
    return (cx - f * 0.15 * R, cy)


# --- the comic marks ---------------------------------------------------------------------------------------------------------
MARKS = {"tired": ("swirl", "ticks"), "closed": ("swirl",), "sad": ("gloom", "drop"), "wide": ("burst",),
         "open": ("ticks",), "determined": ("ticks", "spark"), "soft": ("spark",), "happy": ("spark", "spark2"),
         "angry": ("burst", "ticks"), "worried": ("ticks", "drop")}


def stroke(p, pts, w0, w1, color, out=3.0):
    p.poly(S.tube(pts, w0 + 2 * out, w1 + 2 * out, k=6), INK)
    p.poly(S.tube(pts, w0, w1, k=6), color)


def draw_marks(frame, him, mood):
    R, f = him["R"], him["f"]
    hx, hy = him["pose"]["head"]
    lay = layer()
    p = S.Paint(lay, flat_view())
    kinds = MARKS.get(mood or "open", ("ticks",))
    if "ticks" in kinds:
        for ang, L in ((-2.05, 0.42), (-2.45, 0.34)) if f < 0 else ((-1.09, 0.42), (-0.69, 0.34)):
            r0 = 1.22 * R
            a = (hx + math.cos(ang) * r0, hy + math.sin(ang) * r0)
            b = (hx + math.cos(ang) * (r0 + L * R), hy + math.sin(ang) * (r0 + L * R))
            stroke(p, [a, b], 0.10 * R, 0.07 * R, WHITE)
    if "burst" in kinds:
        for ang in (-2.6, -2.15, -1.7, -1.25, -0.8):
            r0 = 1.20 * R
            a = (hx + math.cos(ang) * r0, hy + math.sin(ang) * r0)
            b = (hx + math.cos(ang) * (r0 + 0.36 * R), hy + math.sin(ang) * (r0 + 0.36 * R))
            stroke(p, [a, b], 0.10 * R, 0.07 * R, WHITE)
    if "swirl" in kinds:
        cx, cy = hx - f * 0.62 * R, hy - 1.95 * R
        t = np.linspace(0, 1, 320)
        rr_ = 0.40 * R * (1 - 0.72 * t)
        xs = cx + rr_ * np.cos(t * 4.0 * math.tau) + 0.06 * R * t
        ys = cy + 0.70 * R * t + 0.22 * rr_ * np.sin(t * 4.0 * math.tau)
        pts = list(zip(xs, ys))
        p.poly(S.tube(pts, 0.085 * R, 0.07 * R, k=2), S.hexc("#26232A"))
        p.poly(S.tube(pts, 0.050 * R, 0.040 * R, k=2), S.hexc("#B5B2B8"))
    if "gloom" in kinds:
        for k, dx in enumerate((-0.55, 0.0, 0.55)):
            x = hx + dx * R
            ys = np.linspace(hy - 2.05 * R, hy - 1.30 * R, 30)
            xs = x + 0.07 * R * np.sin(np.linspace(0, 3 * math.pi, 30) + k)
            stroke(p, list(zip(xs, ys)), 0.07 * R, 0.07 * R, S.hexc("#8C86A8"), out=2.5)
    if "drop" in kinds:
        dx, dy = hx + f * 1.05 * R, hy - 0.55 * R
        drop = np.array([(dx, dy - 0.32 * R)] + [(dx + 0.16 * R * math.cos(a), dy + 0.16 * R * math.sin(a))
                                                  for a in np.linspace(-0.25, math.pi + 0.25, 20)])
        p.poly(S.tube(list(drop) + [drop[0]], 0.06 * R, k=2), INK)
        p.poly(drop, S.hexc("#BFE4FF"))
    if "spark" in kinds or "spark2" in kinds:
        spots = [(-f * 0.95, -1.35, 0.30), (f * 1.30, -0.95, 0.20), (-f * 0.20, -1.70, 0.16)]
        for sx, sy, s in spots[:3 if "spark2" in kinds else 2]:
            cx, cy = hx + sx * R, hy + sy * R
            star = [(cx + math.cos(k * math.pi / 4 - math.pi / 2) * (s * R if k % 2 == 0 else s * R * 0.30),
                     cy + math.sin(k * math.pi / 4 - math.pi / 2) * (s * R if k % 2 == 0 else s * R * 0.30))
                    for k in range(8)]
            p.poly(S.tube(star + [star[0]], 0.05 * R, k=2), INK)
            p.poly(np.array(star), YELLOW)
    comp(frame, lay)


def draw_glow_ticks(frame, at, R, f):
    lay = layer()
    p = S.Paint(lay, flat_view())
    x, y = at
    for (a, b) in (((x - f * 0.45 * R, y - 0.25 * R), (x - f * 0.75 * R, y - 0.40 * R)),
                   ((x - f * 0.50 * R, y + 0.05 * R), (x - f * 0.82 * R, y + 0.02 * R))):
        stroke(p, [a, b], 0.06 * R, 0.05 * R, WHITE, out=2.0)
    comp(frame, lay)


# --- the words -----------------------------------------------------------------------------------------------------------------
def word_mask(text, px, font="Rubik[wght].ttf", weight="Black", ss=2):
    f = S.font(font, px * ss, weight)
    l, t, r, b = f.getbbox(text)
    img = Image.new("L", (r - l + 8 * ss, b - t + 8 * ss), 0)
    ImageDraw.Draw(img).text((4 * ss - l, 4 * ss - t), text, font=f, fill=255)
    return np.asarray(img, np.float32) / 255.0, f


def rough(m, ss, amount, seed):
    """Dry-brush edges: the letter's edge pushed in and out by a fine noise."""
    e = cv2.GaussianBlur(m, (0, 0), 1.2 * ss)
    return np.clip((e - 0.5 + amount * noise(m.shape, 1.6 * ss, seed)) * 5.0 + 0.5, 0, 1)


def line_sprite(text, px, color, seed, shear=0.19, ss=2, roughness=0.06, condense=0.90):
    m, _ = word_mask(text, px, ss=ss)
    m = cv2.resize(m, (max(1, int(m.shape[1] * condense)), m.shape[0]), interpolation=cv2.INTER_AREA)
    m = rough(m, ss, roughness, seed)
    h, w = m.shape
    pad = int(h * shear) + 4
    m = cv2.warpAffine(m, np.float32([[1, -shear, pad + shear * h], [0, 1, 0]]), (w + 2 * pad, h),
                       flags=cv2.INTER_LINEAR)
    m = cv2.resize(m, (m.shape[1] // ss, m.shape[0] // ss), interpolation=cv2.INTER_AREA)
    tone = 1.0 - 0.02 * np.clip(noise(m.shape, 6.0, seed + 5), -1.5, 1.5)[..., None]
    out = np.zeros(m.shape + (4,), np.float32)
    out[..., :3] = np.asarray(color, np.float32) * tone * m[..., None]
    out[..., 3] = m
    ys, xs = np.nonzero(m > 0.02)
    return out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def balance(words):
    ws = words.split()
    if len(ws) < 2:
        return [words]
    best = min(range(1, len(ws)), key=lambda k: abs(len(" ".join(ws[:k])) - len(" ".join(ws[k:]))))
    return [" ".join(ws[:best]), " ".join(ws[best:])]


def words_block(lead, punch, box_w, box_h, seed=3):
    """The words as one sprite: the lead-in (white) over the punch (yellow, about 1.6 times as big), each line as wide as
    it can be within box_w, the whole block within box_h. Returns (sprite RGBA, each line's box)."""
    lead, punch = " ".join(lead.upper().split()), " ".join(punch.upper().split())
    best = None
    for p_lines in ([punch], balance(punch)) if len(punch.split()) > 1 else ([punch],):
        lines = ([(lead, WHITE, 1.0)] if lead else []) + [(t, YELLOW, 1.62) for t in p_lines]
        scaled = []
        for k, (t, col, rel) in enumerate(lines):
            s = line_sprite(t, int(150 * rel), col, seed + k)
            scaled.append((s, min(1.0, box_w / s.shape[1]), rel))
        total = sum(s.shape[0] * k for s, k, _ in scaled) * 1.10
        q = min(1.0, box_h / total)
        score = sum(s.shape[0] * k * q for s, k, rel in scaled if rel > 1.2)
        if best is None or score > best[0]:
            best = (score, scaled, q)
    _, scaled, q = best
    parts = [cv2.resize(s, (max(1, int(s.shape[1] * k * q)), max(1, int(s.shape[0] * k * q))),
                        interpolation=cv2.INTER_AREA) for s, k, rel in scaled]
    gap_px = int(0.10 * np.mean([pp.shape[0] for pp in parts]))
    bw = max(pp.shape[1] for pp in parts)
    bh = sum(pp.shape[0] for pp in parts) + gap_px * (len(parts) - 1)
    pad = 40
    out = np.zeros((bh + 2 * pad, bw + 2 * pad, 4), np.float32)
    y, boxes = pad, []
    for pp in parts:
        x = pad + (bw - pp.shape[1]) // 2
        region = out[y:y + pp.shape[0], x:x + pp.shape[1]]
        S.over(region[..., :3], pp)
        region[..., 3] = region[..., 3] * (1 - pp[..., 3]) + pp[..., 3]
        boxes.append((x, y, pp.shape[1], pp.shape[0]))
        y += pp.shape[0] + gap_px
    return out, boxes


def brush_underline(w, thick, seed):
    """A dry-brush stroke w px long: thin at its start, full quickly, tapering to its end, a little curved up."""
    hgt = int(thick * 3)
    xs = np.arange(w, dtype=np.float32)
    u = xs / max(1, w - 1)
    width = thick * np.clip(np.minimum(u / 0.08, 1.0) * (1 - 0.65 * u ** 1.6), 0.15, 1.0)
    mid = hgt * 0.62 - u * thick * 0.55 - np.sin(u * math.pi) * thick * 0.25
    yy = np.arange(hgt, dtype=np.float32)[:, None]
    m = np.clip((width[None, :] / 2 - np.abs(yy - mid[None, :])) / 1.2 + 0.5, 0, 1)
    streak = cv2.GaussianBlur(np.random.default_rng(seed).normal(0, 1, (hgt, w)).astype(np.float32), (0, 0),
                              sigmaX=9.0, sigmaY=0.7)
    streak /= max(1e-6, streak.std())
    edge = np.clip(np.abs(yy - mid[None, :]) / np.maximum(width[None, :] / 2, 1e-3), 0, 1)
    m *= np.clip(1.0 - np.clip(streak - 1.1, 0, None) * edge * 1.2 - np.clip(u - 0.80, 0, None) * 3.0 *
                 np.clip(streak + 0.2, 0, None), 0, 1)
    return m


def paste_rgba(frame, spr, x0, y0):
    h, w = spr.shape[:2]
    Hh, Ww = frame.shape[:2]
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(Ww, x0 + w), min(Hh, y0 + h)
    if fx1 > fx0 and fy1 > fy0:
        S.over(frame[fy0:fy1, fx0:fx1], spr[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0])


def rotate_rgba(spr, deg):
    h, w = spr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(spr, M, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT), M


def draw_words(frame, lead, punch, area, tilt=3.0, seed=3):
    """The words in `area` (x0, y0, x1, y1): returns where the arrow should start (the block's left, at the punch)."""
    x0, y0, x1, y1 = area
    spr, boxes = words_block(lead, punch, x1 - x0, (y1 - y0) * 0.88, seed)
    bx, by, bw, bh = boxes[-1]
    uw = int(bw * 0.92)
    ul = brush_underline(uw, max(16, int(bh * 0.21)), seed + 9)
    uy = by + bh + int(bh * 0.02)
    ux = bx + (bw - uw) // 2 + int(bw * 0.04)
    hh = ul.shape[0]
    if uy + hh > spr.shape[0]:
        spr = np.concatenate([spr, np.zeros((uy + hh - spr.shape[0] + 4, spr.shape[1], 4), np.float32)], 0)
    under = np.zeros((hh, uw, 4), np.float32)
    under[..., :3] = YELLOW * ul[..., None]
    under[..., 3] = ul
    region = spr[uy:uy + hh, ux:ux + uw]
    S.over(region[..., :3], under)
    region[..., 3] = region[..., 3] * (1 - ul) + ul
    spr = outlined(spr, 3.5, soft=0.6)
    spr, M = rotate_rgba(spr, tilt)
    sh = np.zeros_like(spr)
    sh[..., 3] = shifted(cv2.GaussianBlur(spr[..., 3], (0, 0), 7), 8, 10) * 0.75
    h, w = spr.shape[:2]
    px, py = int((x0 + x1) / 2 - w / 2), int((y0 + y1) / 2 - h / 2)
    paste_rgba(frame, sh, px, py)
    paste_rgba(frame, spr, px, py)
    first = boxes[1] if lead else boxes[0]
    q = M @ np.array([first[0] - 10, first[1] + first[3] * 0.85, 1.0])
    return (px + q[0], py + q[1])


def draw_arrow(frame, start, end, width=26.0, bend=0.35):
    """The red arrow: a curved shaft from start to end (bowed up), a big head at the end, a dark outline and a shadow."""
    (x0, y0), (x1, y1) = start, end
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / L, dx / L
    if ny > 0:
        nx, ny = -nx, -ny
    c = (mx + nx * L * bend, my + ny * L * bend)
    t = np.linspace(0, 1, 40)[:, None]
    P = (1 - t) ** 2 * np.array([x0, y0]) + 2 * (1 - t) * t * np.array(c) + t ** 2 * np.array([x1, y1])
    tip = P[-1]
    d = P[-1] - P[-4]
    d /= np.linalg.norm(d)
    head_len, head_w = width * 2.5, width * 2.6
    base = tip - d * head_len
    keep = np.linalg.norm(P - tip, axis=1) > head_len * 0.92
    shaft = [tuple(q) for q in P[keep]] + [tuple(base + d * width * 0.3)]
    n = np.array([-d[1], d[0]])
    head = np.array([tip, base + n * head_w / 2, base + d * width * 0.25, base - n * head_w / 2])
    lay = layer()
    p = S.Paint(lay, flat_view())
    p.poly(S.tube(shaft, width * 0.80, width), RED)
    p.poly(head, RED)
    lay = outlined(lay, 4.0)
    sh = np.zeros_like(lay)
    sh[..., 3] = shifted(cv2.GaussianBlur(lay[..., 3], (0, 0), 6), 6, 8) * 0.6
    comp(frame, sh)
    comp(frame, lay)


# --- the thumbnail ------------------------------------------------------------------------------------------------------------
def make(story: dict, k: int, seconds: float, lead: str, punch: str, out: Path, rim=True, place_dim=0.50,
         tilt=3.0) -> Path:
    """The thumbnail of shot k (0 = the first) at its strongest moment: the place behind, him big, the words, the arrow."""
    shot = {**story["shots"][k], "seed": story["shots"][k].get("seed", k * 101 + 7), "seconds": seconds}
    at = SR.best_moment(story, k, seconds)
    frame = backdrop(story, shot, at, dim=place_dim)
    xs = np.arange(W, dtype=np.float32)     # (a darker side for the words, a lighter one for him)
    frame *= (1 - 0.50 * np.clip((xs - 0.48 * W) / (0.30 * W), 0, 1))[None, :, None]
    R = 0.168 * H
    h = his_shot(story, shot)
    him = his_moment(h, at, R, (0.30 * W, 0.415 * H), f=-1)
    screen = him["desk"] is not None and h["laptop"]
    if screen:
        screen_light(frame, him)
    if him["kind"] == "sit":
        draw_chair(frame, him)
    if not screen:   # (no screen: the light from the left, the place's own)
        g = layer()
        S.Paint(g, flat_view()).glow(-0.1 * W, 0.35 * H, 0.45 * W, 0.55 * H, S.hexc("#FFC9A0"), 0.20)
        frame += g[..., :3]
    draw_him(frame, him, rim=rim)
    if him["desk"] is not None:
        glows = draw_desk(frame, him, 1.0, laptop=screen)
        if glows is not None:
            draw_glow_ticks(frame, glows, R, him["f"])
    draw_marks(frame, him, h["mood"])
    frame = S.Finish((W, H), bars=0.0, vignette=0.55, grain=0.016).apply(frame, 0, still=True)
    lead, punch = (lead or "").strip(), (punch or "").strip()
    if not punch:   # (one line of words: all of it the punch)
        lead, punch = "", lead
    start = draw_words(frame, lead, punch, (0.575 * W, 0.07 * H, 0.965 * W, 0.93 * H), tilt=tilt)
    sh_x, sh_y = him["pose"]["T"](-0.75, 0.55)
    draw_arrow(frame, start, (sh_x + 0.30 * R, sh_y))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8)).save(out, "JPEG", quality=92)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("story", help="a storyboarded story (JSON: the story, or {\"story\": ...})")
    parser.add_argument("shot", type=int, help="the shot (1 = the first)")
    parser.add_argument("lead")
    parser.add_argument("punch")
    parser.add_argument("out")
    args = parser.parse_args()
    data = json.loads(Path(args.story).read_text(encoding="utf-8"))
    story = data.get("story") or data
    k = max(0, min(len(story["shots"]) - 1, args.shot - 1))
    print(make(story, k, float(story["shots"][k].get("seconds") or 4.0), args.lead, args.punch, Path(args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
