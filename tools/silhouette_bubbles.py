"""
The characters' words and thoughts, drawn as bubbles over their heads instead of a voice: speech (a rounded bubble, its
tail to the speaker), thought (a cloud, small rounds trailing down to his head), a shout (a spiky burst; swearing as
"#@%!", never spelt out), a picture (a thought cloud with a small drawing in it: tools/silhouette_icons.py). In the look:
the warm cream of the eyes' white, the thin coral-red rim, dark plum letters in Rubik.

  read_seconds(text, picture="")      how long a bubble stays: a second to find it, then 2.5 words a second; 2.5 s at
                                      least; a picture alone 2.5 s, a picture with words a second more
  KINDS                               the bubbles' kinds, with what each is for (the storyboard's words)
  draw(frame, bubbles)                the shot's bubbles at this moment (tools/silhouette_board.state gives them, with
                                      each speaker's head on screen), popping in, fading out, an earlier one dimmed
                                      while the reply is read

Where a bubble goes: above its speaker's head on the side with room (the way he faces first, for speech), inside the
letterbox bars, off every face and every other bubble; it keeps its place by the head as the head moves.
"""

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

import silhouette as S
from silhouette import hexc
import silhouette_icons as I
import silhouette_words as W

KINDS = W.BUBBLE_KINDS   # (the words live in tools/silhouette_words.py)
FILL, RIM, INK = hexc("#F4EDE2"), S.PAL["rim"], hexc("#3A1F38")
MOST_WORDS, MOST_ROWS = W.BUBBLE_WORDS, 3
POP, FADE = 0.25, 0.30      # seconds popping in, fading out


read_seconds = W.read_seconds


def _px(size) -> float:
    """The letters' height in pixels: 42 at 1080p in the film; bigger in the upright Short (it's watched on a phone)."""
    W, H = size
    return 42.0 * H / 1080.0 if W >= H else 56.0 * W / 1080.0


def _clip(text: str) -> str:
    """At most MOST_WORDS words of at most W.WORD_CHARS letters, W.BUBBLE_CHARS in all: words from anywhere never draw
    a bubble wider than the picture (the checks upstream keep them short; this is the last guard)."""
    words = [w if len(w) <= W.WORD_CHARS else w[:W.WORD_CHARS - 1] + "…" for w in text.split()[:MOST_WORDS]]
    out = " ".join(words)
    return out if len(out) <= W.BUBBLE_CHARS else out[:W.BUBBLE_CHARS - 1].rstrip() + "…"


def _rows(text: str, font, width: float) -> list[str]:
    """The words in rows no wider than `width`, as even as can be (at most MOST_ROWS)."""
    words = text.split()
    if not words:
        return []
    best = None
    for n in range(1, MOST_ROWS + 1):
        target = sum(font.getlength(w + " ") for w in words) / n
        rows, cur = [], []
        for w in words:
            trial = " ".join(cur + [w])
            if cur and font.getlength(trial) > max(target * 1.15, font.getlength(w)) and len(rows) < n - 1:
                rows.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        rows.append(" ".join(cur))
        widest = max(font.getlength(r) for r in rows)
        if widest <= width or n == MOST_ROWS:
            score = widest + 0.0 * n
            if best is None or (widest <= width and score < best[0]) or best[0] > width:
                best = (widest, rows)
            if widest <= width:
                break
    return best[1]


@lru_cache(maxsize=256)
def body(kind: str, text: str, picture: str, px: int, tall: bool):
    """A bubble's body with its words or picture, without its tail: (premultiplied RGBA float sprite, its width, its
    height in px). Drawn at twice the size and scaled down, so its edges are smooth."""
    k = 2
    f = S.font("Rubik[wght].ttf", int(px * k), "Bold" if kind == "shout" else "Medium")
    max_w = (0.70 if tall else 0.30) * (1080 if tall else 1920) * px / (56.0 if tall else 42.0) * k
    rows = _rows(_clip(text), f, max_w) if text else []
    line_h = px * k * 1.22
    tw = max([f.getlength(r) for r in rows] or [0.0])
    th = line_h * len(rows)
    pic = px * k * (3.4 if not rows else 2.4) if picture else 0.0
    pad_x, pad_y = px * k * (0.95 if kind != "say" else 0.80), px * k * (0.70 if kind != "say" else 0.55)
    inner_w = max(tw, pic)
    inner_h = th + pic + (px * k * 0.25 if rows and pic else 0.0)
    w, h = inner_w + 2 * pad_x, inner_h + 2 * pad_y
    if kind in ("think", "picture"):   # (a cloud's puffs bite into its edge: more room round the words)
        w, h = w * 1.30 + px * k * 0.4, h * 1.32
    if kind == "shout":
        w, h = w * 1.30, h * 1.45
    W_, H_ = int(w + 16 * k), int(h + 16 * k)
    buf = S.blank((W_, H_))
    p = S.Paint(buf, S.View(0, 0, 1.0, 0, 0))
    cx, cy = W_ / 2, H_ / 2
    shape = _shape(kind, cx, cy, w / 2, h / 2)
    p.poly(shape, RIM)
    p.poly(_shrink(shape, cx, cy, 3.2 * k), FILL)
    if picture:
        py = cy - inner_h / 2 + pic / 2
        I.draw(p, picture, cx, py, pic * 0.48, "cream", 0.8)
    if rows:   # the words, dark plum, centred under the picture (or in the middle)
        mask = Image.new("L", (W_, H_), 0)
        d = ImageDraw.Draw(mask)
        y = cy - inner_h / 2 + (pic + px * k * 0.25 if pic else 0.0)
        for r in rows:
            d.text((cx - f.getlength(r) / 2, y + px * k * 0.05), r, font=f, fill=255)
            y += line_h
        m = np.asarray(mask, np.float32)[..., None] / 255.0
        buf[..., :3] = buf[..., :3] * (1 - m) + INK * m
        buf[..., 3:] = np.maximum(buf[..., 3:], m)
    small = np.ascontiguousarray(
        np.asarray(Image.fromarray((np.clip(buf, 0, 1) * 255).astype(np.uint8)).resize((W_ // k, H_ // k), Image.LANCZOS),
                   np.float32) / 255.0)
    return small, w / k, h / k


def _shape(kind, cx, cy, rx, ry):
    """The bubble's outline round its middle: a rounded box (speech), a cloud (a thought, a picture), a burst (a shout)."""
    if kind == "say":
        r = min(ry * 0.95, rx * 0.5)
        return S.rr(cx - rx, cy - ry, 2 * rx, 2 * ry, r, 10)
    if kind == "shout":
        n = 16
        a = np.arange(2 * n) * math.pi / n
        rad = np.where(np.arange(2 * n) % 2 == 0, 1.0, 0.80)
        jag = 1.0 + 0.06 * np.sin(np.arange(2 * n) * 2.7)
        return np.stack([cx + np.cos(a) * rx * rad * jag, cy + np.sin(a) * ry * rad * jag], 1)
    a = np.linspace(0, math.tau, 240, endpoint=False)   # a cloud: an oval's edge scalloped by its puffs
    puffs = 9 if rx < 3 * ry else 11
    bump = np.abs(np.sin(a * puffs / 2)) ** 0.6
    return np.stack([cx + np.cos(a) * rx * (0.88 + 0.12 * bump), cy + np.sin(a) * ry * (0.86 + 0.14 * bump)], 1)


def _shrink(shape, cx, cy, d):
    """An outline drawn in by d pixels towards its middle (the fill inside the rim)."""
    v = shape - np.array([cx, cy])
    n = np.maximum(np.hypot(v[:, 0], v[:, 1]), 1e-6)[:, None]
    return np.array([cx, cy]) + v * np.maximum(n - d, 0) / n


def place(head, r, size, bw, bh, f, avoid, kind, bar):
    """Where a bubble of bw x bh px goes for a head at `head` (radius r px) of someone facing f: (its middle x, y). Above
    the head on the side with room (the way he faces first for speech), inside the bars, off `avoid` (boxes: faces,
    bubbles)."""
    W, H = size
    hx, hy = head
    margin = 0.02 * min(W, H)
    lo_y, hi_y = bar + margin, H - bar - margin
    side = 1 if f >= 0 else -1
    cands = [(hx + side * (r * 0.55 + bw / 2), hy - r * 1.35 - bh / 2, 0.0),
             (hx - side * (r * 0.55 + bw / 2), hy - r * 1.35 - bh / 2, 0.15 if kind == "say" else 0.0),
             (hx, hy - r * 1.55 - bh / 2, 0.05),
             (hx + side * (r * 1.45 + bw / 2), hy - r * 0.55, 0.25),
             (hx - side * (r * 1.45 + bw / 2), hy - r * 0.55, 0.35)]
    best = None
    for x, y, pref in cands:
        cx = min(max(x, margin + bw / 2), W - margin - bw / 2)
        cy = min(max(y, lo_y + bh / 2), hi_y - bh / 2)
        moved = math.hypot(cx - x, cy - y) / max(bw, bh)
        box = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
        hit = sum(_overlap(box, a) for a in avoid) / (bw * bh)
        face = _overlap(box, (hx - r * 1.05, hy - r * 1.05, hx + r * 1.05, hy + r * 1.05)) / (bw * bh)
        score = pref + 1.2 * moved + 6.0 * hit + 9.0 * face
        if best is None or score < best[0]:
            best = (score, cx, cy)
    return best[1], best[2]


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _tail(frame, kind, box, head, r, alpha):
    """The tail from the bubble to its speaker: a tapering point (speech, a shout) or small rounds getting smaller
    (a thought, a picture). Drawn on a small layer round it."""
    x0, y0, x1, y1 = box
    hx, hy = head
    bx = min(max(hx, x0 + (x1 - x0) * 0.2), x1 - (x1 - x0) * 0.2)
    by = y1 - (y1 - y0) * 0.08 if hy > y1 else (y0 + (y1 - y0) * 0.08 if hy < y0 else (y0 + y1) / 2)
    tip = (hx + (bx - hx) * 0.42, hy - r * 0.95 + (by - (hy - r * 0.95)) * 0.25)
    w = (x1 - x0) * 0.07 + 6
    H, W = frame.shape[:2]
    ox, oy = int(max(0, min(bx, tip[0]) - w - 30)), int(max(0, min(by, tip[1]) - w - 30))
    ex, ey = int(min(W, max(bx, tip[0]) + w + 30)), int(min(H, max(by, tip[1]) + w + 30))
    if ex <= ox or ey <= oy:
        return
    layer = S.blank((ex - ox, ey - oy))
    p = S.Paint(layer, S.View(ox, oy, 1.0, 0, 0))
    if kind in ("say", "shout"):
        dx, dy = tip[0] - bx, tip[1] - by
        n = max(math.hypot(dx, dy), 1e-6)
        nx, ny = -dy / n, dx / n
        tri = np.array([(bx + nx * w, by + ny * w), (bx - nx * w, by - ny * w), tip])
        p.poly(tri, RIM)
        p.poly(_shrink(tri, *np.mean(tri, axis=0), 3.0), FILL)
    else:
        for k, u in enumerate((0.30, 0.60, 0.85)):
            cx, cy = bx + (tip[0] - bx) * u * 1.15, by + (tip[1] - by) * u * 1.15
            rad = (x1 - x0) * (0.045 - 0.012 * k) + 3
            p.circle(cx, cy, rad, RIM)
            p.circle(cx, cy, rad - 2.8, FILL)
    S.over(frame[oy:ey, ox:ex], layer * alpha)


def draw(frame: np.ndarray, bubbles: list[dict]) -> None:
    """The shot's bubbles at this moment, over the frame (float RGB): each {"kind", "text", "picture", "head" (px),
    "r" (the head's radius, px), "f" (the way the speaker faces), "age" (seconds since it began), "left" (seconds until
    it ends), "dim" (0-1: an earlier one, waiting while the reply is read), "avoid" (boxes: faces), "at" (its middle, once
    placed: kept)}."""
    H, W = frame.shape[:2]
    tall = H > W
    px = int(round(_px((W, H))))
    bar = S.BARS * min(W, H)
    placed = []
    for b in bubbles:
        sprite, bw, bh = body(b["kind"], b.get("text") or "", b.get("picture") or "", px, tall)
        if b.get("at") is None:
            b["at"] = place(b["head"], b["r"], (W, H), bw, bh, b.get("f", 1), list(b.get("avoid") or []) + placed,
                            b["kind"], bar)
            if b.get("keep") is not None:   # (its place beside the head, kept: it follows the head from now on)
                b["keep"][b["key"]] = (b["at"][0] - b["head"][0], b["at"][1] - b["head"][1])
        cx, cy = b["at"]
        placed.append((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))
        age, left = b.get("age", 1.0), b.get("left", 1.0)
        pop = S.back_out(min(1.0, age / POP), 1.6) if age < POP else 1.0
        alpha = min(1.0, age / (POP * 0.6)) * min(1.0, max(0.0, left) / FADE)
        if alpha <= 0.01:
            continue
        scale = 0.82 + 0.18 * pop
        if b.get("dim"):   # (an earlier one, while the reply is read: a little darker, still solid)
            sprite = sprite.copy()
            sprite[..., :3] *= 1.0 - 0.28 * b["dim"]
        _tail(frame, b["kind"], (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), b["head"], b["r"], alpha)
        S.paste(frame, sprite, cx, cy, scale=scale, opacity=alpha)
