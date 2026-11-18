"""
The silhouette look's drawing engine (the owner's own look description, 2026-11-15: prompts/look_silhouette.txt.enc, word for
word; reference GIF .tmp/reference/style_reference.gif, never in git). Everything is drawn in code: no AI pictures, so the
cloud needs no GPU and nothing is counted against a free allowance.

  - World and camera: a set is drawn in world units. A Camera puts a world point at the middle of the frame, zoomed; each
    layer has a depth (0 = the sky, far away; 1 = the desk; >1 = in front of the lens), and the camera's push and pan move
    a layer in proportion to it, so the front leaves slide fastest and the sky barely moves.
  - Layers: premultiplied RGBA in float (0-1). A static layer is drawn once at the camera's resting view (with a margin) and
    warped each frame; a dynamic one (the figure, the clock, the dust) is drawn every frame. Light layers are added on top
    (the lamp's cone, the sun's bloom, the laptop's glow), never painted over.
  - Shapes: anti-aliased polygons (OpenCV's fillPoly at 1/16 px), filled flat, with a gradient, or soft-edged (a blurred
    mask). No outlines anywhere (the look's rule): shapes stay flat, light does the mood.
  - The figure: a big round black head, a thin stick neck, stick legs, a hoodie in one flat colour with a few thin fold
    lines and white drawstrings; no face, only two white eyes (open, half-lidded, wide, closed, sad, determined). Its rim
    light is a red copy of its silhouette nudged towards the light, with a soft glow: a thin crescent on the lit side.
  - The finish: haze and a slight blur on far layers, a strong vignette, black letterbox bars and fine film grain. A frame
    can be "still" (the last second of a scene): then the grain and the dust hold too, so nothing flickers.

The palette is the owner's: a dusky plum room (#48304F near the window to #170F1D in the corners), a sunset sky (#2F2A57,
#B3687C, #EE8F67, #FFD7A0), mauve and plum skylines with warm windows (#FFC383), the figure #08070B in a teal hoodie
(#2B6470), the rim #FF5A44, the lamp's light #FFE2B4.
"""

import math
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from common import ASSETS_DIR
import silhouette_words as W

HAIRS, HAIR_COLORS, CLOTH_COLORS, EXTRAS = W.HAIRS, W.HAIR_COLORS, W.CLOTH_COLORS, W.EXTRAS

FPS = 24
FONTS = ASSETS_DIR / "fonts"
SUB = 16          # fillPoly's sub-pixel steps (shift 4)


def hexc(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255.0


PAL = {name: hexc(v) for name, v in {
    "wall_near": "#48304F", "wall_far": "#170F1D", "sky_top": "#2F2A57", "sky_rose": "#B3687C", "sky_orange": "#EE8F67",
    "sky_peach": "#FFD7A0", "far_city": "#B98597", "near_city": "#2A1830", "city_window": "#FFC383", "figure": "#08070B",
    "hoodie": "#2B6470", "rim": "#FF5A44", "lamp": "#FFE2B4", "eye": "#F4F1EA", "screen": "#9FC8FF", "label": "#FFF4E6",
    "page": "#F2ECE2", "ring": "#9A949C", "digit": "#141016", "clock_body": "#2A1C2C", "wood": "#2E2130",
    "wood_edge": "#7A6068", "frame": "#120C16", "floor": "#120C15", "shade": "#231826",
}.items()}


# --- easing --------------------------------------------------------------------------------------------------------------------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(p):
    p = clamp(p)
    return p * p * (3 - 2 * p)


def ease_out(p, k=3.0):
    p = clamp(p)
    return 1 - (1 - p) ** k


def ease_in_out(p):
    p = clamp(p)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def back_out(p, s=1.6):
    p = clamp(p) - 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def spring(p, bounce=0.35, freq=2.2):
    """0 -> 1 with a springy overshoot that settles (eyes popping open)."""
    p = clamp(p)
    return 1 - math.exp(-6 * p) * math.cos(freq * math.pi * p) * (1 - p) ** 0.5 if p < 1 else 1.0


def window(t, a, b):
    """Progress 0-1 of t through [a, b]."""
    return clamp((t - a) / max(b - a, 1e-6))


def lerp(a, b, t):
    return a + (b - a) * t


# --- shapes (world coordinates) -----------------------------------------------------------------------------------------------
def ell(cx, cy, rx, ry, n=64, a0=0.0):
    a = a0 + np.arange(n) / n * math.tau
    return np.stack([cx + np.cos(a) * rx, cy + np.sin(a) * ry], 1)


def rect(x, y, w, h):
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float64)


def rr(x, y, w, h, r, n=6):
    r = max(0.0, min(r, w / 2, h / 2))
    parts = []
    for cx, cy, a in ((x + w - r, y + r, -math.pi / 2), (x + w - r, y + h - r, 0.0), (x + r, y + h - r, math.pi / 2),
                      (x + r, y + r, math.pi)):
        b = a + np.arange(n + 1) / n * (math.pi / 2)
        parts.append(np.stack([cx + np.cos(b) * r, cy + np.sin(b) * r], 1))
    return np.vstack(parts)


def spline(c, closed=True, k=8):
    """A Catmull-Rom curve through the points c."""
    c = np.asarray(c, np.float64)
    n = len(c)
    idx = np.arange(n if closed else n - 1)

    def P(i):
        return c[i % n] if closed else c[np.clip(i, 0, n - 1)]

    p0, p1, p2, p3 = (P(idx + d)[:, None, :] for d in (-1, 0, 1, 2))
    t = (np.arange(k) / k)[None, :, None]
    out = 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
    out = out.reshape(-1, 2)
    return out if closed else np.vstack([out, c[-1:]])


def tube(pts, w0, w1=None, k=10):
    """A limb or a stick along the points: one smooth tube tapering w0 -> w1, round at both ends."""
    w1 = w0 if w1 is None else w1
    mid = spline(pts, closed=False, k=k)
    keep = np.concatenate([[True], np.hypot(*np.diff(mid, axis=0).T) > 1e-6])
    mid = mid[keep]
    if len(mid) < 2:
        return ell(pts[0][0], pts[0][1], w0 / 2, w0 / 2, 16)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(mid, axis=0).T))])
    u = cum / max(cum[-1], 1e-9)
    i = np.arange(len(mid))
    tg = mid[np.minimum(i + 1, len(mid) - 1)] - mid[np.maximum(i - 1, 0)]
    tg /= np.maximum(np.hypot(tg[:, 0], tg[:, 1]), 1e-9)[:, None]
    side = np.stack([-tg[:, 1], tg[:, 0]], 1) * ((w0 + (w1 - w0) * u)[:, None] / 2)
    ea, ba = math.atan2(tg[-1, 1], tg[-1, 0]), math.atan2(tg[0, 1], tg[0, 0])
    a = np.linspace(ea + math.pi / 2, ea - math.pi / 2, 9)
    cap_b = np.stack([mid[-1, 0] + np.cos(a) * w1 / 2, mid[-1, 1] + np.sin(a) * w1 / 2], 1)
    a = np.linspace(ba - math.pi / 2, ba - math.pi * 1.5, 9)
    cap_a = np.stack([mid[0, 0] + np.cos(a) * w0 / 2, mid[0, 1] + np.sin(a) * w0 / 2], 1)
    return np.vstack([mid + side, cap_b, (mid - side)[::-1], cap_a])


def ik(h, a, l1, l2, bend=1):
    """The middle joint (knee or elbow) of a two-bone limb from h to a."""
    dx, dy = a[0] - h[0], a[1] - h[1]
    d = clamp(math.hypot(dx, dy), 1e-3, l1 + l2 - 1e-3)
    ang = math.acos(clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1))
    k = math.atan2(dy, dx) - bend * ang
    return h[0] + math.cos(k) * l1, h[1] + math.sin(k) * l1


# --- the camera and a layer's view ------------------------------------------------------------------------------------------------
class View:
    """World -> pixels for one layer at one moment: p' = (p - c) * z + o."""

    def __init__(self, cx, cy, z, ox, oy):
        self.cx, self.cy, self.z, self.ox, self.oy = float(cx), float(cy), float(z), float(ox), float(oy)

    def __call__(self, pts):
        p = np.asarray(pts, np.float64)
        return np.stack([(p[..., 0] - self.cx) * self.z + self.ox, (p[..., 1] - self.cy) * self.z + self.oy], -1)

    def pt(self, x, y):
        return (x - self.cx) * self.z + self.ox, (y - self.cy) * self.z + self.oy

    def matrix_to(self, other: "View") -> np.ndarray:
        """The 2x3 matrix taking this view's pixels to `other`'s."""
        s = other.z / self.z
        return np.float32([[s, 0, other.ox - self.ox * s + (self.cx - other.cx) * other.z],
                           [0, s, other.oy - self.oy * s + (self.cy - other.cy) * other.z]])


class Camera:
    """Where the camera looks (world centre cx, cy and zoom z) at a moment, relative to its resting framing."""

    def __init__(self, size, cx, cy, z):
        self.size = size
        self.rest = (float(cx), float(cy), float(z))

    def view(self, depth, cx=None, cy=None, z=None, margin=0):
        """The view of a layer at `depth` when the camera is at (cx, cy, z) (default: at rest). The push and the pan reach a
        layer in proportion to its depth (a layer in front of the lens, depth > 1, moves more than the camera). margin: px
        round the frame (or (x, y))."""
        W, H = self.size
        mx, my = margin if isinstance(margin, tuple) else (margin, margin)
        c0x, c0y, z0 = self.rest
        cx = c0x if cx is None else cx
        cy = c0y if cy is None else cy
        z = z0 if z is None else z
        zl = z0 * (1 + (z / z0 - 1) * depth)
        lx, ly = c0x + (cx - c0x) * depth, c0y + (cy - c0y) * depth
        return View(lx, ly, zl, W / 2 + mx, H / 2 + my)


# --- drawing onto a layer ---------------------------------------------------------------------------------------------------------
class Paint:
    """Draws world shapes onto a premultiplied RGBA float layer through a view. It keeps the box it has drawn in
    (`dirty`), so a layer drawn every frame is only cleared and composited there."""

    def __init__(self, buf: np.ndarray, view: View):
        self.buf, self.v = buf, view
        self.dirty = None

    @property
    def z(self):
        return self.v.z

    def wy(self, ys):
        """Pixel rows -> world y (for gradients)."""
        return (ys - self.v.oy) / self.v.z + self.v.cy

    def wx(self, xs):
        return (xs - self.v.ox) / self.v.z + self.v.cx

    def _touch(self, x0, y0, x1, y1):
        d = self.dirty
        self.dirty = (x0, y0, x1, y1) if d is None else (min(d[0], x0), min(d[1], y0), max(d[2], x1), max(d[3], y1))

    def _mask(self, pts, pad=0):
        s = self.v(pts)
        h, w = self.buf.shape[:2]
        x0 = max(0, int(math.floor(s[:, 0].min())) - pad)
        y0 = max(0, int(math.floor(s[:, 1].min())) - pad)
        x1 = min(w, int(math.ceil(s[:, 0].max())) + 1 + pad)
        y1 = min(h, int(math.ceil(s[:, 1].max())) + 1 + pad)
        if x1 <= x0 or y1 <= y0:
            return None
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        q = np.round((s - (x0, y0)) * SUB).astype(np.int32)
        cv2.fillPoly(m, [q], 255, cv2.LINE_AA, 4)
        self._touch(x0, y0, x1, y1)
        return m, x0, y0

    def cut(self, pts):
        """Makes the shape transparent (a window's panes cut out of the wall)."""
        got = self._mask(pts)
        if got is None:
            return
        m, x0, y0 = got
        keep = 1 - m.astype(np.float32)[..., None] / 255.0
        h, w = m.shape
        self.buf[y0:y0 + h, x0:x0 + w] *= keep

    def sprite(self, img: np.ndarray, x, y, w, h, opacity: float = 1.0):
        """A premultiplied RGBA picture laid onto the world rectangle (x, y, w, h) (h may be negative: drawn upwards)."""
        (sx0, sy0), (sx1, sy1) = self.v.pt(x, y), self.v.pt(x + w, y + h)
        if abs(sx1 - sx0) < 0.5 or abs(sy1 - sy0) < 0.5:
            return
        ih, iw = img.shape[:2]
        kx, ky = (sx1 - sx0) / iw, (sy1 - sy0) / ih
        H_, W_ = self.buf.shape[:2]
        bx0, bx1 = max(0, int(math.floor(min(sx0, sx1)))), min(W_, int(math.ceil(max(sx0, sx1))) + 1)
        by0, by1 = max(0, int(math.floor(min(sy0, sy1)))), min(H_, int(math.ceil(max(sy0, sy1))) + 1)
        if bx1 <= bx0 or by1 <= by0:
            return
        M = np.float32([[kx, 0, sx0 - bx0], [0, ky, sy0 - by0]])
        part = cv2.warpAffine(img, M, (bx1 - bx0, by1 - by0), flags=cv2.INTER_AREA if abs(kx) < 1 else cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        if opacity < 1:
            part *= opacity
        region = self.buf[by0:by1, bx0:bx1]
        over(region[..., :3], part)
        region[..., 3] = region[..., 3] * (1 - part[..., 3]) + part[..., 3]
        self._touch(bx0, by0, bx1, by1)

    def poly(self, pts, color, alpha=1.0, soft=0.0, add=False, polys=None):
        """A filled shape (several, if `polys`: drawn as one, so overlaps don't double up). color: an RGB (0-1) or a function
        (xs, ys) of pixel coordinates -> an H x W x 3 array (a gradient). soft: blur its edge (world units). add: light,
        added rather than painted over."""
        shapes = polys if polys is not None else [pts]
        pad = int(math.ceil(soft * self.z * 2.5)) + 2 if soft else 0
        allp = np.vstack(shapes)
        got = self._mask(allp, pad)
        if got is None:
            return
        m, x0, y0 = got
        if len(shapes) > 1:
            m[:] = 0
            for p in shapes:
                q = np.round((self.v(p) - (x0, y0)) * SUB).astype(np.int32)
                cv2.fillPoly(m, [q], 255, cv2.LINE_AA, 4)
        a = m.astype(np.float32) * (alpha / 255.0)
        if soft:
            sig = soft * self.z
            a = cv2.GaussianBlur(a, (0, 0), sig)
        h, w = a.shape
        region = self.buf[y0:y0 + h, x0:x0 + w]
        col = color(*np.meshgrid(np.arange(x0, x0 + w, dtype=np.float32), np.arange(y0, y0 + h, dtype=np.float32))) \
            if callable(color) else np.asarray(color, np.float32)
        a3 = a[..., None]
        if add:
            region[..., :3] += col * a3
        else:
            region[..., :3] = region[..., :3] * (1 - a3) + col * a3
            region[..., 3] = region[..., 3] * (1 - a) + a

    def circle(self, x, y, r, color, alpha=1.0, soft=0.0, add=False):
        n = int(clamp(r * self.z * 0.6, 16, 160))
        self.poly(ell(x, y, r, r, n), color, alpha, soft, add)

    def glow(self, x, y, rx, ry, color, strength=1.0, falloff=2.0):
        """Light: a radial glow added at (x, y), rx by ry world units across its half-width."""
        sx, sy = self.v.pt(x, y)
        h, w = self.buf.shape[:2]
        Rx, Ry = rx * self.z * 2.2, ry * self.z * 2.2
        x0, x1 = max(0, int(sx - Rx)), min(w, int(sx + Rx) + 1)
        y0, y1 = max(0, int(sy - Ry)), min(h, int(sy + Ry) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        xs, ys = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
        d2 = ((xs - sx) / (rx * self.z)) ** 2 + ((ys - sy) / (ry * self.z)) ** 2
        g = np.exp(-d2 / falloff) * strength
        self.buf[y0:y1, x0:x1, :3] += np.asarray(color, np.float32) * g[..., None]
        self._touch(x0, y0, x1, y1)


def blank(size, margin=0) -> np.ndarray:
    W, H = size
    mx, my = margin if isinstance(margin, tuple) else (margin, margin)
    return np.zeros((H + 2 * my, W + 2 * mx, 4), np.float32)


MARGIN = 72  # px round a static layer, so the camera's moves never show its edge


class Static:
    """A layer drawn once, at the camera's resting view (with a margin), then moved with the camera each frame by its
    depth. Only the part with something in it is kept and warped. add: light (added to the frame, not painted over).
    margin: px round the frame drawn too (or (x, y)): more than MARGIN for a layer the camera pans across."""

    def __init__(self, cam: Camera, depth: float, draw, blur: float = 0.0, add: bool = False, rim_light=None,
                 margin=MARGIN):
        self.cam, self.depth, self.add = cam, depth, add
        self.rest = cam.view(depth, margin=margin)
        buf = blank(cam.size, margin)
        draw(Paint(buf, self.rest))
        if rim_light:
            buf = rim(buf, *rim_light)
        if blur:
            buf = cv2.GaussianBlur(buf, (0, 0), blur)
        a = buf[..., :3].max(axis=2) if add else buf[..., 3]
        ys, xs = np.nonzero(a > 1 / 512)
        self.empty = not len(ys)
        if self.empty:
            return
        self.x0, self.y0 = int(xs.min()), int(ys.min())
        self.buf = np.ascontiguousarray(buf[self.y0:int(ys.max()) + 1, self.x0:int(xs.max()) + 1])

    def composite(self, frame: np.ndarray, at: tuple, gain: float = 1.0) -> None:
        """Draws the layer onto the frame (RGB float) with the camera at `at` = (cx, cy, z). gain: a light layer's
        strength (0 = off: a lamp switched off)."""
        if self.empty or gain <= 0.0:
            return
        view = self.cam.view(self.depth, *at)
        M = self.rest.matrix_to(view).astype(np.float64)
        M[:, 2] += M[:, :2] @ np.array([self.x0, self.y0], np.float64)
        h, w = self.buf.shape[:2]
        corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], np.float64) @ M.T
        H, W = frame.shape[:2]
        dx0, dy0 = max(0, int(math.floor(corners[:, 0].min()))), max(0, int(math.floor(corners[:, 1].min())))
        dx1, dy1 = min(W, int(math.ceil(corners[:, 0].max())) + 1), min(H, int(math.ceil(corners[:, 1].max())) + 1)
        if dx1 <= dx0 or dy1 <= dy0:
            return
        M[:, 2] -= (dx0, dy0)
        part = cv2.warpAffine(self.buf, M.astype(np.float32), (dx1 - dx0, dy1 - dy0), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        region = frame[dy0:dy1, dx0:dx1]
        if self.add:
            region += part[..., :3] * gain if gain != 1.0 else part[..., :3]
        else:
            over(region, part)


class Dynamic:
    """A layer drawn every frame (a figure, the clock, the dust) onto a buffer the size of the frame, cleared and
    composited only where something was drawn."""

    def __init__(self, cam: Camera, depth: float, add: bool = False):
        self.cam, self.depth, self.add = cam, depth, add
        W, H = cam.size
        self.buf = np.zeros((H, W, 4), np.float32)

    def paint(self, at: tuple) -> Paint:
        return Paint(self.buf, self.cam.view(self.depth, *at))

    def composite(self, frame: np.ndarray, p: Paint, rim_light=None) -> None:
        if p.dirty is None:
            return
        x0, y0, x1, y1 = p.dirty
        pad = 24 if rim_light else 0
        H, W = frame.shape[:2]
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
        sub = self.buf[y0:y1, x0:x1]
        if rim_light:
            sub = rim(sub, *rim_light)
        region = frame[y0:y1, x0:x1]
        if self.add:
            region += sub[..., :3]
        else:
            over(region, sub)
        self.buf[y0:y1, x0:x1] = 0


def over(dst_rgb: np.ndarray, layer: np.ndarray) -> None:
    """Composites a premultiplied RGBA layer over an RGB frame, in place."""
    a = layer[..., 3:4]
    dst_rgb *= (1 - a)
    dst_rgb += layer[..., :3]


def warp(buf: np.ndarray, M: np.ndarray, size) -> np.ndarray:
    W, H = size
    return cv2.warpAffine(buf, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def shifted(a: np.ndarray, dx: float, dy: float) -> np.ndarray:
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(a, M, (a.shape[1], a.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def rim(layer: np.ndarray, dx: float, dy: float, color=PAL["rim"], glow_px: float = 6.0, glow_a: float = 0.55,
        strength: float = 1.0) -> np.ndarray:
    """The rim light: a red copy of the layer's silhouette nudged (dx, dy) px towards the light, with a soft glow, drawn
    behind it, so it shows as a thin crescent on the lit side. Returns the layer with its rim."""
    a = layer[..., 3]
    ys, xs = np.nonzero(a > 0.004)
    if not len(ys):
        return layer
    pad = int(abs(dx) + abs(dy) + glow_px * 3) + 2
    h, w = a.shape
    y0, y1, x0, x1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1), max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    sub = layer[y0:y1, x0:x1]
    sa = shifted(sub[..., 3], dx, dy)
    g = cv2.GaussianBlur(sa, (0, 0), glow_px) * glow_a * strength
    col = np.asarray(color, np.float32)
    back = np.zeros_like(sub)
    back[..., :3] = col * g[..., None]
    back[..., 3] = g
    edge = np.zeros_like(sub)
    edge[..., :3] = col * (sa * strength)[..., None]
    edge[..., 3] = sa * strength
    out = layer.copy()
    region = out[y0:y1, x0:x1]
    comp = back.copy()
    over(comp[..., :3], edge)
    comp[..., 3] = comp[..., 3] * (1 - edge[..., 3]) + edge[..., 3]
    over(comp[..., :3], sub)
    comp[..., 3] = comp[..., 3] * (1 - sub[..., 3]) + sub[..., 3]
    region[...] = comp
    return out


# --- type -----------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=32)
def font(name: str, size: int, variation: str | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size)
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:
            pass
    return f


@lru_cache(maxsize=64)
def label_sprite(words: str, px: int, spacing: float = 0.42, glow: float = 0.55) -> np.ndarray:
    """The small label: widely spaced capitals in Oswald SemiBold, warm white with a faint red glow (premultiplied RGBA)."""
    words = words.upper()
    f = font("Oswald[wght].ttf", px, "SemiBold")
    gap = px * spacing
    widths = [f.getlength(ch) for ch in words]
    w = int(sum(widths) + gap * (len(words) - 1)) + px * 2
    h = int(px * 1.9)
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    x = px
    for ch, cw in zip(words, widths):
        d.text((x, px * 0.25), ch, font=f, fill=255)
        x += cw + gap
    m = np.asarray(mask, np.float32) / 255.0
    g = np.asarray(mask.filter(ImageFilter.GaussianBlur(px * 0.22)), np.float32) / 255.0 * glow
    out = np.zeros((h, w, 4), np.float32)
    rimc, white = PAL["rim"], PAL["label"]
    out[..., :3] = rimc * g[..., None]
    out[..., 3] = g
    out[..., :3] = out[..., :3] * (1 - m[..., None]) + white * m[..., None]
    out[..., 3] = out[..., 3] * (1 - m) + m
    return out


def paste(frame_rgb: np.ndarray, sprite: np.ndarray, cx: float, cy: float, scale: float = 1.0, opacity: float = 1.0):
    if opacity <= 0.003 or scale <= 0.02:
        return
    s = sprite
    if abs(scale - 1) > 1e-3:
        s = cv2.resize(sprite, (max(1, int(sprite.shape[1] * scale)), max(1, int(sprite.shape[0] * scale))),
                       interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    h, w = s.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    H, W = frame_rgb.shape[:2]
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sub = s[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0] * opacity
    over(frame_rgb[fy0:fy1, fx0:fx1], sub)


# --- the finish -------------------------------------------------------------------------------------------------------------------
BARS = 0.075  # each letterbox bar's height, a share of the frame's short side (the film's subtitles sit in the lower one)


class Finish:
    """Vignette, letterbox bars and fine film grain for one frame size (made once)."""

    def __init__(self, size, bars: float = BARS, vignette: float = 0.62, grain: float = 0.022):
        W, H = size
        self.size = size
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xs - W / 2) / (W * 0.62)) ** 2 + ((ys - H / 2) / (H * 0.62)) ** 2)
        self.vig = (1 - vignette * np.clip(d - 0.42, 0, None) ** 1.5).clip(0.18, 1)[..., None].astype(np.float32)
        self.bar = int(round(min(W, H) * bars))
        r = np.random.default_rng(11)
        self.grain = [cv2.resize(r.normal(0, grain, (H // 2, W // 2)).astype(np.float32), (W, H),
                                 interpolation=cv2.INTER_LINEAR)[..., None] for _ in range(6)]

    def apply(self, frame: np.ndarray, index: int, still: bool = False) -> np.ndarray:
        frame *= self.vig
        frame += self.grain[0 if still else index % len(self.grain)] * (0.6 + 0.4 * frame.mean(axis=2, keepdims=True))
        if self.bar:
            frame[:self.bar] = 0
            frame[-self.bar:] = 0
        return frame


def bloom(frame: np.ndarray, threshold: float = 0.72, strength: float = 0.5, sigma_frac: float = 0.018) -> None:
    """Warm bloom round the brightest parts (the low sun, the lamp's bulb), in place."""
    lum = frame.max(axis=2)
    hot = np.clip(lum - threshold, 0, None)[..., None] * frame
    small = cv2.resize(hot, (frame.shape[1] // 4, frame.shape[0] // 4), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(1.0, frame.shape[0] * sigma_frac / 4))
    frame += cv2.resize(small, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR) * strength


def to_bytes(frame: np.ndarray) -> bytes:
    return cv2.convertScaleAbs(np.clip(frame, 0, 1), alpha=255.0).tobytes()


# --- the people ---------------------------------------------------------------------------------------------------------------
class Eyes:
    """Two white eyes on the head: where they look (dx, dy as a share of the head's radius), how open (0 closed, 0.5
    half-lidded, 1 open), how big (1, more when wide), the lids' tilt (+ sad or worried, - determined or angry), smile
    (closed in two happy arcs) and tear (0 none; 0-1 a tear's way down the cheek, under the eye nearer the way he looks)."""

    def __init__(self, look=(0.0, 0.0), open_=1.0, size=1.0, tilt=0.0, gap=0.46, smile=False, tear=0.0):
        self.look, self.open, self.size, self.tilt, self.gap, self.smile = look, open_, size, tilt, gap, smile
        self.tear = tear

    def draw(self, p: Paint, hx, hy, R, turn=0.0):
        """turn: -1..1, the head turned away to a side: the eyes squeeze together on that side. Returns the eyes'
        centres and radius [(x, y, r)] (glasses are drawn round them)."""
        lx, ly = self.look
        r = R * 0.135 * self.size
        gap = R * self.gap * (1 - 0.35 * abs(turn))
        cx = hx + lx * R * 0.55 + turn * R * 0.30
        cy = hy + ly * R * 0.4 - R * 0.05
        out = []
        for side in (-1, 1):
            ex = cx + side * gap / 2
            out.append((ex, cy, r))
            if self.smile:  # closed and curved up: content, happy
                a = np.linspace(math.pi * 1.08, math.pi * 1.92, 14)
                p.poly(tube(np.stack([ex + np.cos(a) * r, cy + r * 0.35 + np.sin(a) * r * 0.75], 1), r * 0.42, k=3),
                       PAL["eye"], 0.95)
                continue
            pts = ell(ex, cy, r, r * 1.05, 40)
            lid = cy - r * 1.05 + (1 - clamp(self.open)) * 2 * r * 1.05
            tilt = self.tilt * side * r * 0.9  # sad: the inner ends of the lids high; determined: low
            ys = lid + tilt * (pts[:, 0] - ex) / max(r, 1e-6)
            pts[:, 1] = np.maximum(pts[:, 1], ys)
            if self.open < 0.06:  # closed: a thin curved line
                line = ell(ex, cy + r * 0.25, r, r * 0.18, 30)
                p.poly(line, PAL["eye"], 0.9)
                continue
            p.poly(pts, PAL["eye"])
        if self.tear > 0:  # a tear sliding down from under the front eye, fading at the end of its way
            side = 1 if lx >= 0 else -1
            ex, ey, _ = out[1 if side > 0 else 0]
            u = clamp(self.tear)
            ty = ey + r * 1.35 + u * R * 0.62
            tx = ex + side * r * 0.15 + u * side * R * 0.05
            a = 0.9 * (1 - smooth(window(u, 0.75, 1.0)))
            b = np.linspace(-0.2 * math.pi, 1.2 * math.pi, 18)   # the round lower part (y grows downwards), then the tip
            drop = np.vstack([np.stack([tx + np.cos(b) * r * 0.36, ty + np.sin(b) * r * 0.40], 1), [(tx, ty - r * 0.95)]])
            p.poly(drop, hexc("#CFE2F6"), a)
        return out


MOODS = {  # the eyes' moods (agents/story.py's vocabulary): open, size, tilt, smile
    "tired": (0.45, 1.0, 0.0, False), "open": (0.85, 1.0, 0.0, False), "wide": (1.0, 1.22, 0.0, False),
    "closed": (0.0, 1.0, 0.0, False), "sad": (0.40, 1.0, 0.6, False), "determined": (0.75, 1.0, -0.38, False),
    "soft": (0.55, 1.0, 0.18, False), "happy": (0.0, 1.0, 0.0, True),
    "angry": (0.62, 0.98, -0.80, False), "worried": (0.92, 1.06, 0.48, False),
}


def eyes_for(mood: str, look=(1.0, 0.0), gap=0.42, blink: float = 1.0, tear: float = 0.0) -> Eyes:
    """Eyes in a mood (MOODS), looking `look`, `blink` 0-1 (1 open as the mood has it, 0 shut), a tear's way down."""
    open_, size, tilt, smile = MOODS.get(mood, MOODS["open"])
    return Eyes(look=look, open_=open_ * clamp(blink), size=size, tilt=tilt, gap=gap, smile=smile and blink > 0.3,
                tear=tear)


class Look:
    """How a person is drawn: the hero (his teal hoodie, white drawstrings, the hood) or someone else in the same build in
    other colours and outlines. hair: None (the bare round head), "short", "long", "bun" (in hair_color: grey reads as
    grey hair); beard (its colour); glasses; a cap or a helmet (their colours); a suit's collar and tie; a doctor's coat
    and stethoscope; an apron (its colour, over the clothes); a dress (the top flares into a skirt to the knee); a
    jacket (its colour: an open jacket over a shirt in `cloth`). size: their head and body against his (1)."""

    def __init__(self, cloth="#2B6470", hood=False, strings=False, hair=None, hair_color="#1E141B", build=1.0, hem=2.85,
                 collar=None, tie=None, cap=None, stethoscope=False, size=1.0, gap=0.42, beard=None, glasses=False,
                 helmet=None, apron=None, dress=False, jacket=None):
        self.cloth = hexc(cloth)
        self.body = PAL["figure"]
        self.hood, self.strings, self.hair, self.hair_color = hood, strings, hair, hexc(hair_color)
        self.build, self.hem, self.size, self.gap = build, hem, size, gap
        self.collar = hexc(collar) if collar else None
        self.tie = hexc(tie) if tie else None
        self.cap = hexc(cap) if cap else None
        self.stethoscope = stethoscope
        self.beard = hexc(beard) if beard else None
        self.glasses = bool(glasses)
        self.helmet = hexc(helmet) if helmet else None
        self.apron = hexc(apron) if apron else None
        self.dress = bool(dress)
        self.jacket = hexc(jacket) if jacket else None
        if self.dress and hem <= 2.85:
            self.hem = 3.9

    @property
    def coat(self):
        """The torso's and the sleeves' colour: the jacket's when there is one."""
        return self.jacket if self.jacket is not None else self.cloth

    def fold(self):
        return np.clip(self.coat * 0.72, 0, 1)


LOOKS = {
    "him": Look("#2B6470", hood=True, strings=True),
    "mother": Look("#7E5A68", hair="bun", hair_color="#B9B2BC", build=0.96, size=0.93),
    "woman": Look("#7A4A5E", hair="long", hair_color="#1E141B", build=0.86, hem=3.45, size=0.95),
    "boss": Look("#30323E", collar="#E9E4EC", tie="#7A2E36", build=1.12, size=1.04),
    "landlord": Look("#5A4636", cap="#2E2622", build=1.28),
    "doctor": Look("#C9CBD6", collar="#EEEAF2", stethoscope=True, hem=3.4),
    "friend": Look("#6B5A3A", build=1.05),
    "stranger": Look("#4A4058"),
}



def look_from(spec: dict) -> Look:
    """A person's look from a storyboard's description: {"cloth": a CLOTH_COLORS name, "hair": HAIRS, "hair_color":
    HAIR_COLORS, "build": 0.8-1.3, "size": 0.85-1.1, "extras": EXTRAS, "jacket_color", "apron_color", "beard_color"}.
    Unknown words fall back quietly (the storyboard's checks name them)."""
    def col(name, table, default):
        v = (spec.get(name) or "").strip().lower()
        return table.get(v, v if v.startswith("#") and len(v) == 7 else default)
    extras = {str(e).strip().lower() for e in spec.get("extras") or []}
    hair = (spec.get("hair") or "none").strip().lower()
    hair_c = col("hair_color", HAIR_COLORS, HAIR_COLORS["black"])
    cloth = col("cloth", CLOTH_COLORS, CLOTH_COLORS["slate"])
    kw = {"cloth": cloth, "hair": hair if hair in HAIRS and hair != "none" else None, "hair_color": hair_c,
          "build": clamp(float(spec.get("build") or 1.0), 0.8, 1.3), "size": clamp(float(spec.get("size") or 1.0), 0.85, 1.1)}
    if "beard" in extras:
        kw["beard"] = col("beard_color", HAIR_COLORS, hair_c if hair != "none" else HAIR_COLORS["black"])
    if "glasses" in extras:
        kw["glasses"] = True
    if "cap" in extras:
        kw["cap"] = "#2E2622"
    if "helmet" in extras:
        kw["helmet"] = "#C99A3E"
    if "apron" in extras:
        kw["apron"] = col("apron_color", CLOTH_COLORS, "#D9D2C8")
    if "dress" in extras:
        kw["dress"] = True
    if "suit" in extras:   # the suit in their colour, a white shirt and a tie
        kw["jacket"] = col("jacket_color", CLOTH_COLORS, cloth if spec.get("cloth") else CLOTH_COLORS["charcoal"])
        kw.update(cloth="#E9E4EC", collar="#E9E4EC", tie="#7A2E36")
    elif "jacket" in extras:
        kw["jacket"] = col("jacket_color", CLOTH_COLORS, CLOTH_COLORS["charcoal"])
    if "coat" in extras:
        kw["hem"] = 3.45
    if "stethoscope" in extras:
        kw.update(stethoscope=True, collar="#EEEAF2")
    return Look(**kw)


def spine(S, H, f, R):
    """A torso's own frame: T(u, v) -> world, u forward (towards f's front), v down the spine in R (v = 2.55 at the hip,
    whatever the torso's real length)."""
    vx, vy = H[0] - S[0], H[1] - S[1]
    L = max(math.hypot(vx, vy), 1e-6)
    vx, vy = vx / L, vy / L
    ux, uy = f * vy, -f * vx
    k = L / (2.55 * R)

    def T(u, v):
        return (S[0] + u * R * ux + v * R * k * vx, S[1] + u * R * uy + v * R * k * vy)
    return T, (ux, uy), (vx, vy)


def _leg_walk(hip, ground, f, R, walk, phase, run):
    """Both legs (far first) of a walk or a run: the stance foot on the ground, the swinging one lifted, knees forward."""
    l1 = l2 = 1.42 * R
    leg = (l1 + l2) * 0.985
    amp = 0.40 * walk * (1 - run) + 0.70 * run
    legs = []
    for i in (1, 0):
        psi = phase + i * math.pi
        th = amp * math.sin(psi)
        swing = max(0.0, math.cos(psi))
        lift = (0.32 * walk * (1 - run) + 1.05 * run) * R * swing ** 1.5
        fx = hip[0] + f * math.sin(th) * leg
        fy = min(ground, hip[1] + math.cos(th) * leg - lift)
        k1, k2 = ik(hip, (fx, fy), l1, l2, 1), ik(hip, (fx, fy), l1, l2, -1)
        knee = k1 if f * (k1[0] - k2[0]) > 0 else k2
        legs.append(((hip[0] + (i - 0.5) * 0.10 * R * f, hip[1]), knee, (fx, fy)))
    return legs


def _hip_height(ground, R, walk, phase, run):
    leg = 2.84 * R * 0.985
    amp = 0.40 * walk * (1 - run) + 0.70 * run
    stance = [amp * math.sin(phase + i * math.pi) for i in (1, 0) if math.cos(phase + i * math.pi) <= 0]
    th = stance[0] if stance else amp * math.sin(phase)
    return ground - math.cos(th) * leg - (0.25 * R * run * abs(math.sin(phase * 1.0)))


def _arm(sh, a_upper, a_fore, uv, R, l1=1.22, l2=1.10):
    """An arm from the shoulder: the upper arm at angle a_upper from straight down the spine (towards the front +), the
    forearm at a_fore."""
    (ux, uy), (vx, vy) = uv
    el = (sh[0] + R * l1 * (math.sin(a_upper) * ux + math.cos(a_upper) * vx),
          sh[1] + R * l1 * (math.sin(a_upper) * uy + math.cos(a_upper) * vy))
    wr = (el[0] + R * l2 * (math.sin(a_fore) * ux + math.cos(a_fore) * vx),
          el[1] + R * l2 * (math.sin(a_fore) * uy + math.cos(a_fore) * vy))
    return el, wr


def _reach(sh, target, R, f, down=True):
    """An arm reaching a point: the elbow bending down and back."""
    l1, l2 = 1.22 * R, 1.10 * R
    k1, k2 = ik(sh, target, l1, l2, 1), ik(sh, target, l1, l2, -1)
    if down:
        el = k1 if k1[1] > k2[1] else k2
    else:
        el = k1 if f * (k1[0] - k2[0]) < 0 else k2
    return el, target


ARM_POSES = ("hang", "pockets", "phone", "box", "knock", "offer", "cross", "clipboard", "run")


def _arms_standing(T, uv, R, f, arms, walk, phase, run, knock):
    sh = T(0.02, 0.24)
    far_sh = T(-0.06, 0.26)
    hold = None
    hands = ["fist", "fist"]
    if run > 0.5 or arms == "run":
        sw = 0.85 * math.sin(phase)
        far = _arm(far_sh, sw, sw + 1.5, uv, R)
        near = _arm(sh, -sw, -sw + 1.5, uv, R)
    elif arms == "pockets":
        near = (T(-0.20, 1.25), T(0.40, 1.88))
        far, hands = None, ["hidden", "hidden"]
    elif arms == "phone":
        near = (T(-0.08, 1.15), T(0.58, 0.95))
        far = None
        hold = {"kind": "phone", "at": T(0.66, 0.80)}
    elif arms == "box":
        near = (T(0.32, 1.25), T(0.80, 1.38))
        far = (T(0.22, 1.28), T(0.72, 1.40))
        hold = {"kind": "box", "at": T(1.05, 1.22)}
        hands = ["hidden", "fist"]
    elif arms == "knock":
        tap = 0.07 * math.sin(knock * math.tau * 2.6) if knock > 0 else 0.0
        near = (T(0.58, 0.62), T(0.86 + tap, 0.06))
        far = None
    elif arms == "offer":
        near = (T(0.36, 0.98), T(0.98, 1.06))
        far = None
        hands = ["fist", "open"]
    elif arms == "cross":
        near = (T(0.16, 1.18), T(0.62, 1.02))
        far, hands = None, ["hidden", "hidden"]
    elif arms == "clipboard":
        near = (T(0.06, 1.15), T(0.52, 1.06))
        far = None
        hold = {"kind": "clipboard", "at": T(0.74, 0.92)}
    else:  # hang (swinging when he walks)
        sw = 0.32 * walk * math.sin(phase)
        near = _arm(sh, -sw, -sw + 0.18 * walk + 0.05, uv, R)
        far = _arm(far_sh, sw, sw + 0.18 * walk + 0.05, uv, R)
    return {"near": (sh, *near), "far": (far_sh, *far) if far else None, "hold": hold, "hands": hands}


def pose_stand(x, ground, f, R, slump=0.0, lift=0.0, arms="hang", walk=0.0, phase=0.0, run=0.0, hood_up=False,
               knock=0.0) -> dict:
    """Standing, walking (walk 0-1, phase: the cycle, one step per pi) or running (run 0-1), seen from the side, facing f
    (+1 right, -1 left), his feet on `ground` at x. slump 0-1: shoulders rounded, head sunk; lift -1..1: head bowed ..
    looking up. arms: ARM_POSES."""
    sl = clamp(slump)
    hip_y = _hip_height(ground, R, walk, phase, run)
    H = (x, hip_y)
    lean = 0.06 * walk * (1 - run) + 0.24 * run + 0.20 * sl
    S = (H[0] + f * math.sin(lean) * 2.55 * R, H[1] - math.cos(lean) * 2.55 * R)
    T, u, v = spine(S, H, f, R)
    legs = _leg_walk(H, ground, f, R, walk, phase, run)
    if arms == "phone":
        lift = min(lift, -0.45)
    head = T(0.14 + 0.24 * sl - 0.08 * lift, -1.28 + 0.40 * sl - 0.06 * lift)
    out = {"f": f, "R": R, "S": S, "H": H, "T": T, "head": head, "lift": lift, "legs": legs, "hood_up": hood_up}
    out.update(_arms_standing(T, (u, v), R, f, arms, walk, phase, run, knock))
    return out


SIT_ARMS = ("lap", "desk", "type", "head", "knees", "phone", "cup")


def pose_sit(x, seat_y, ground, f, R, slump=0.0, lift=0.0, arms="lap", reach=None, tap=0.0, hood_up=False) -> dict:
    """Sitting on a chair, a bench, a bed's edge (the seat's top at seat_y; his hips at x), facing f. arms: SIT_ARMS;
    reach: where the hands rest for "desk"/"type"/"cup" (a desk's or a table's top)."""
    sl = clamp(slump)
    H = (x, seat_y - 0.12 * R)
    lean = 0.08 + 0.42 * sl + (0.62 if arms == "head" else 0.0) + (0.12 if arms in ("knees", "phone") else 0.0)
    S = (H[0] + f * math.sin(lean) * 2.55 * R, H[1] - math.cos(lean) * 2.55 * R)
    T, u, v = spine(S, H, f, R)
    knee = (H[0] + f * 1.66 * R, H[1] + 0.04 * R)
    foot = (knee[0] + f * 0.14 * R, ground)
    legs = [((H[0] - f * 0.06 * R, H[1]), (knee[0] - f * 0.14 * R, knee[1] + 0.03 * R), (foot[0] - f * 0.22 * R, ground)),
            (H, knee, foot)]
    sh = T(0.02, 0.24)
    hold, hands, far = None, ["fist", "fist"], None
    if arms == "head":  # head in his hands: elbows on his knees, the head sunk into the hands
        head = (knee[0] - f * 0.50 * R, knee[1] - 1.95 * R)
        wr = (head[0] + f * 0.58 * R, head[1] + 0.50 * R)
        el = (knee[0] - f * 0.10 * R, knee[1] - 0.14 * R)
        near = (el, wr)
        hands = ["fist", "open"]
    else:
        if arms == "phone":
            lift = min(lift, -0.5)
        head = T(0.14 + 0.24 * sl - 0.08 * lift, -1.28 + 0.40 * sl - 0.06 * lift)
        if arms in ("desk", "type", "cup") and reach is not None:
            target = (reach[0] + (f * 0.06 * R * math.sin(tap * math.tau * 3.1) if arms == "type" else 0.0),
                      reach[1] - (0.05 * R * max(0.0, math.sin(tap * math.tau * 6.3)) if arms == "type" else 0.0))
            near = _reach(sh, target, R, f)
            if arms == "cup":
                hold = {"kind": "cup", "at": (target[0] + f * 0.10 * R, target[1] - 0.12 * R)}
        elif arms == "knees":
            near = ((knee[0] - f * 0.35 * R, knee[1] - 0.20 * R), (knee[0] + f * 0.30 * R, knee[1] + 0.45 * R))
        elif arms == "phone":
            near = (T(0.10, 1.05), T(0.70, 0.78))
            hold = {"kind": "phone", "at": T(0.78, 0.62)}
        else:  # hands in the lap
            near = (T(0.05, 1.30), (knee[0] - f * 0.45 * R, knee[1] - 0.18 * R))
    out = {"f": f, "R": R, "S": S, "H": H, "T": T, "head": head, "lift": lift, "legs": legs, "hood_up": hood_up,
           "near": (sh, *near), "far": far, "hold": hold, "hands": hands, "sitting": True, "hem_max": 2.62}
    if arms == "head":
        out["face_hidden"] = True
    return out


def pose_floor(x, ground, f, R, slump=0.0, lift=0.0, hood_up=False) -> dict:
    """Sitting on the floor with his back to a wall, knees drawn up, arms round them; slump 1: his head down on his
    knees."""
    sl = clamp(slump)
    H = (x, ground - 0.32 * R)
    lean = -0.10 + 0.55 * sl
    S = (H[0] + f * math.sin(lean) * 2.55 * R, H[1] - math.cos(lean) * 2.55 * R)
    T, u, v = spine(S, H, f, R)
    knee = (H[0] + f * 1.02 * R, H[1] - 1.12 * R)
    foot = (H[0] + f * 1.90 * R, ground)
    legs = [((H[0] - f * 0.05 * R, H[1]), (knee[0] - f * 0.10 * R, knee[1] + 0.06 * R), (foot[0] - f * 0.18 * R, ground)),
            (H, knee, foot)]
    head = T(0.14 + 0.55 * sl - 0.08 * lift, -1.28 + 0.55 * sl - 0.06 * lift)
    sh = T(0.02, 0.24)
    wr = (knee[0] + f * 0.20 * R, knee[1] + 0.62 * R)
    near = _reach(sh, wr, R, f)
    return {"f": f, "R": R, "S": S, "H": H, "T": T, "head": head, "lift": lift, "legs": legs, "hood_up": hood_up,
            "near": (sh, *near), "far": None, "hold": None, "hands": ["fist", "fist"], "sitting": True, "hem_max": 2.62}


def pose_lie(xh, yh, f, R, arms="rest") -> dict:
    """Lying on his back (in bed: the bed's blanket covers him), his head on the pillow at (xh, yh), his body towards f.
    arms: "rest" (along him) or "phone" (held up over his face)."""
    S = (xh + f * 1.30 * R, yh + 0.30 * R)
    H = (S[0] + f * 2.55 * R, S[1] + 0.05 * R)
    T, u, v = spine(S, H, f, R)
    knee = (H[0] + f * 1.42 * R, H[1] - 0.02 * R)
    foot = (knee[0] + f * 1.40 * R, H[1] + 0.06 * R)
    legs = [(H, knee, foot), (H, knee, foot)]
    sh = (S[0] + f * 0.15 * R, S[1] - 0.10 * R)
    hold = None
    if arms == "phone":
        wr = (xh + f * 0.55 * R, yh - 1.50 * R)
        el = (sh[0] + f * 0.95 * R, sh[1] - 0.85 * R)
        hold = {"kind": "phone_up", "at": (wr[0] - f * 0.05 * R, wr[1] - 0.18 * R)}
    else:
        el = (S[0] + f * 1.10 * R, S[1] + 0.20 * R)
        wr = (S[0] + f * 2.10 * R, S[1] + 0.12 * R)
    return {"f": f, "R": R, "S": S, "H": H, "T": T, "head": (xh, yh), "lift": 0.0, "legs": legs, "hood_up": False,
            "near": (sh, el, wr), "far": None, "hold": hold, "hands": ["fist", "fist"], "lying": True}


def pose_pushup(x, ground, f, R, phase=0.0) -> dict:
    """A push-up, facing f: his hands on the floor at x, his body a straight line back to his feet; phase: the cycle (down
    at pi)."""
    down = 0.5 - 0.5 * math.cos(phase)
    S = (x - f * 0.12 * R, ground - (2.15 - 1.05 * down) * R)
    foot = (x - f * 4.7 * R, ground - 0.06 * R)
    H = (S[0] + (foot[0] - S[0]) * 0.46, S[1] + (foot[1] - S[1]) * 0.46)
    knee = (S[0] + (foot[0] - S[0]) * 0.73, S[1] + (foot[1] - S[1]) * 0.73)
    T, u, v = spine(S, H, f, R)
    head = (S[0] + f * 1.18 * R, S[1] - 0.28 * R)
    sh = (S[0], S[1] + 0.05 * R)
    wr = (x, ground - 0.10 * R)
    l1, l2 = 1.22 * R, 1.10 * R
    k1, k2 = ik(sh, wr, l1, l2, 1), ik(sh, wr, l1, l2, -1)
    el = k1 if f * (k1[0] - k2[0]) < 0 else k2   # the elbows bend back
    return {"f": f, "R": R, "S": S, "H": H, "T": T, "head": head, "lift": 0.3, "legs": [(H, knee, foot), (H, knee, foot)],
            "hood_up": False, "near": (sh, el, wr), "far": None, "hold": None, "hands": ["fist", "open"], "plank": True}


def rell(cx, cy, rx, ry, ang, n=28):
    pts = ell(0, 0, rx, ry, n)
    c, s = math.cos(ang), math.sin(ang)
    return np.stack([cx + pts[:, 0] * c - pts[:, 1] * s, cy + pts[:, 0] * s + pts[:, 1] * c], 1)


def _arc(cx, cy, rad, f, a0, a1, n=24):
    """Points on a circle round (cx, cy), angles measured from the face's side (0 = straight ahead, -pi/2 = the top,
    pi/2 = the chin, pi = the back of the head) for someone facing f."""
    a = np.linspace(a0, a1, n)
    return np.stack([cx + f * np.cos(a) * rad, cy + np.sin(a) * rad], 1)


def _slab(cx, cy, length, thick, ang):
    """A thin flat thing (a book, a sheet, a blade) centred at (cx, cy), along the angle ang."""
    c, s = math.cos(ang), math.sin(ang)
    hl, ht = length / 2, thick / 2
    return np.array([(cx + c * x - s * y, cy + s * x + c * y) for x, y in ((-hl, -ht), (hl, -ht), (hl, ht), (-hl, ht))])


# --- what people hold: drawn under the near arm (its hand covers them) or over it -------------------------------------------
METAL, METAL_LIT, PAPER = hexc("#2C2A33"), hexc("#8A8698"), hexc("#E6DED2")


def _h_box(p, h, R, f, pose):
    bx, by = h["at"]
    p.poly(rr(bx - 0.70 * R, by - 0.55 * R, 1.40 * R, 1.10 * R, 0.05 * R), hexc("#7A5C48"))
    p.poly(rect(bx - 0.70 * R, by - 0.55 * R, 1.40 * R, 0.06 * R), hexc("#B08A6A"), 0.9)
    p.poly(rect(bx - 0.08 * R, by - 0.55 * R, 0.16 * R, 1.10 * R), hexc("#9A7A62"), 0.6)


def _h_clipboard(p, h, R, f, pose):
    bx, by = h["at"]
    p.poly(rr(bx - 0.10 * R, by - 0.42 * R, 0.20 * R, 0.84 * R, 0.03 * R), hexc("#4A3C32"))
    p.poly(rect(bx - 0.06 * R * f - 0.02 * R, by - 0.36 * R, 0.08 * R, 0.70 * R), hexc("#E9E2D8"), 0.9)


def _h_phone(p, h, R, f, pose):
    px_, py_ = h["at"]
    up = h["kind"] == "phone_up"
    ear = h["kind"] == "phone_ear"
    ang = 0.0 if up else (-1.35 * f if ear else -0.5 * f)
    p.poly(rell(px_, py_, 0.17 * R, 0.09 * R, ang + (math.pi / 2 if up else 0.0)), hexc("#141018"))
    if ear:   # held to the ear: only its edge's faint glow shows, nothing lights his face
        p.poly(rell(px_ + f * 0.05 * R, py_, 0.12 * R, 0.025 * R, ang), PAL["screen"], 0.45)
        return None
    sx_, sy_ = (px_, py_ + 0.06 * R) if up else (px_ - f * 0.05 * R, py_ - 0.03 * R)
    p.poly(rell(sx_, sy_, 0.13 * R, 0.035 * R, ang), PAL["screen"], 0.95)
    return (sx_, sy_)


def _h_cup(p, h, R, f, pose):
    bx, by = h["at"]
    p.poly(rr(bx - 0.13 * R, by - 0.20 * R, 0.26 * R, 0.30 * R, 0.04 * R), hexc("#E6DCD0"))


def _toward_face(h, pose, R):
    hx, hy = pose["head"]
    bx, by = h["at"]
    return math.atan2(hy + 0.2 * R - by, hx - bx)


def _h_book(p, h, R, f, pose):
    bx, by = h["at"]
    ang = _toward_face(h, pose, R) + math.pi / 2
    n = (math.cos(ang - math.pi / 2), math.sin(ang - math.pi / 2))   # the side facing the reader
    cover = h.get("color", "#6A2E3A")
    p.poly(_slab(bx, by, 1.05 * R, 0.16 * R, ang), hexc(cover))
    p.poly(_slab(bx + n[0] * 0.06 * R, by + n[1] * 0.06 * R, 0.96 * R, 0.06 * R, ang), PAPER, 0.95)
    p.poly(tube([(bx + n[0] * 0.02 * R, by + n[1] * 0.02 * R), (bx + n[0] * 0.10 * R, by + n[1] * 0.10 * R)],
                0.03 * R), hexc(cover))   # the spine's fold between the pages


def _h_letter(p, h, R, f, pose):
    bx, by = h["at"]
    ang = _toward_face(h, pose, R) + math.pi / 2
    p.poly(_slab(bx, by, 0.95 * R, 0.035 * R, ang), PAPER)


def _h_pen(p, h, R, f, pose):
    bx, by = h["at"]
    if h.get("paper"):   # the sheet on the desk under his hand
        px_, py_ = h["paper"]
        p.poly(rect(px_ - 0.55 * R, py_ - 0.03 * R, 1.10 * R, 0.04 * R), PAPER)
    p.poly(tube([(bx - f * 0.05 * R, by - 0.30 * R), (bx + f * 0.18 * R, by + 0.12 * R)], 0.045 * R), hexc("#1A1620"))


def _h_spoon(p, h, R, f, pose):
    bx, by = h["at"]
    tx, ty = h.get("to", (bx + f * 0.4 * R, by - 0.3 * R))
    d = max(math.hypot(tx - bx, ty - by), 1e-6)
    ex, ey = bx + (tx - bx) / d * 0.42 * R, by + (ty - by) / d * 0.42 * R
    p.poly(tube([(bx, by), (ex, ey)], 0.035 * R), METAL_LIT)
    p.poly(rell(ex, ey, 0.09 * R, 0.05 * R, math.atan2(ty - by, tx - bx)), METAL_LIT)


def _h_spatula(p, h, R, f, pose):
    bx, by = h["at"]
    tx, ty = h.get("to", (bx + f * 0.5 * R, by + 0.6 * R))
    p.poly(tube([(bx, by), (tx, ty)], 0.05 * R), hexc("#3A2A26"))
    p.poly(rell(tx, ty, 0.13 * R, 0.035 * R, 0.25 * f), METAL_LIT)


def _h_dumbbell(p, h, R, f, pose):
    """Seen end on (its bar points at the camera): the near plate's round face with a lit rim, the hub."""
    for key in ("at", "at2"):
        if h.get(key):
            bx, by = h[key]
            p.circle(bx, by, 0.27 * R, METAL_LIT)
            p.circle(bx + 0.02 * R, by + 0.03 * R, 0.23 * R, METAL)
            p.circle(bx, by, 0.07 * R, hexc("#55525E"))


def _h_broom(p, h, R, f, pose):
    (ax, ay), (fx, fy) = h["at"], h["floor"]
    d = max(math.hypot(fx - ax, fy - ay), 1e-6)
    ux, uy = (fx - ax) / d, (fy - ay) / d
    top = (ax - ux * 0.75 * R, ay - uy * 0.75 * R)
    p.poly(tube([top, (fx - ux * 0.40 * R, fy - uy * 0.40 * R)], 0.08 * R), hexc("#5A4232"))
    p.poly(np.array([(fx - 0.16 * R, fy - 0.46 * R), (fx + 0.16 * R, fy - 0.46 * R), (fx + 0.58 * R, fy),
                     (fx - 0.58 * R, fy)]), hexc("#9A7A48"))
    p.poly(rect(fx - 0.18 * R, fy - 0.50 * R, 0.36 * R, 0.08 * R), hexc("#2A1E1A"))


def _h_rag(p, h, R, f, pose):
    bx, by = h["at"]
    p.poly(spline([(bx - 0.26 * R, by + 0.06 * R), (bx - 0.05 * R, by - 0.08 * R), (bx + 0.24 * R, by + 0.02 * R),
                   (bx + 0.20 * R, by + 0.10 * R), (bx - 0.20 * R, by + 0.12 * R)], True, 6), hexc("#7FA0B8"))


def _h_wrench(p, h, R, f, pose):
    bx, by = h["at"]
    tx, ty = h.get("to", (bx + f * 0.55 * R, by + 0.20 * R))
    p.poly(tube([(bx, by), (tx, ty)], 0.07 * R), METAL_LIT)
    ang = math.atan2(ty - by, tx - bx)
    p.poly(rell(tx, ty, 0.12 * R, 0.10 * R, ang), METAL_LIT)
    p.circle(tx + math.cos(ang) * 0.06 * R, ty + math.sin(ang) * 0.06 * R, 0.05 * R, PAL["figure"])


def _h_hammer(p, h, R, f, pose):
    bx, by = h["at"]
    tx, ty = h.get("to", (bx + f * 0.5 * R, by - 0.3 * R))
    p.poly(tube([(bx, by), (tx, ty)], 0.07 * R), hexc("#4A3628"))
    ang = math.atan2(ty - by, tx - bx) + math.pi / 2
    p.poly(_slab(tx, ty, 0.42 * R, 0.16 * R, ang), METAL)


def _h_mic(p, h, R, f, pose):
    bx, by = h["at"]
    tx, ty = h.get("to", (bx + f * 0.2 * R, by - 0.35 * R))
    p.poly(tube([(bx, by), (tx, ty)], 0.08 * R, 0.10 * R), METAL)
    p.circle(tx, ty, 0.11 * R, hexc("#4A4656"))


def _h_glass(p, h, R, f, pose):
    bx, by = h["at"]
    tilt = h.get("tilt", 0.0)
    p.poly(_slab(bx, by - 0.12 * R, 0.30 * R, 0.24 * R, math.pi / 2 + tilt), hexc("#C9C0D6"), 0.40)
    p.poly(_slab(bx, by - 0.05 * R, 0.16 * R, 0.21 * R, math.pi / 2 + tilt), hexc("#C9853A"), 0.75)


def _h_bottle(p, h, R, f, pose):
    bx, by = h["at"]
    tilt = h.get("tilt", 0.0)
    c, s = math.cos(tilt), math.sin(tilt)
    def T_(x, y):
        return (bx + c * x - s * y, by + s * x + c * y)
    body = [T_(-0.10 * R, 0.25 * R), T_(0.10 * R, 0.25 * R), T_(0.10 * R, -0.25 * R), T_(0.04 * R, -0.36 * R),
            T_(0.04 * R, -0.55 * R), T_(-0.04 * R, -0.55 * R), T_(-0.04 * R, -0.36 * R), T_(-0.10 * R, -0.25 * R)]
    p.poly(np.array(body), hexc("#2E4A36"), 0.92)
    p.poly(tube([T_(0.05 * R, -0.18 * R), T_(0.05 * R, 0.18 * R)], 0.025 * R), hexc("#9AC0A0"), 0.5)


def _h_flowers(p, h, R, f, pose):
    bx, by = h["at"]
    for k, (dx, ln) in enumerate(((-0.10, 0.62), (0.05, 0.72), (0.16, 0.58), (-0.02, 0.50))):
        tip = (bx + f * dx * R + f * 0.10 * R, by - ln * R)
        p.poly(tube([(bx, by + 0.15 * R), tip], 0.025 * R), hexc("#3E5A3A"))
        p.circle(tip[0], tip[1], 0.12 * R, hexc(("#C8566A", "#E59A7A", "#D9C2B0", "#B84A5E")[k]))
    p.poly(np.array([(bx - 0.14 * R, by - 0.10 * R), (bx + 0.14 * R, by - 0.10 * R), (bx + 0.05 * R, by + 0.22 * R),
                     (bx - 0.05 * R, by + 0.22 * R)]), hexc("#D9CBB8"))


def _h_bag(p, h, R, f, pose):
    bx, by = h["at"]
    p.poly(tube([(bx - 0.12 * R, by + 0.42 * R), (bx, by), (bx + 0.12 * R, by + 0.42 * R)], 0.03 * R), hexc("#2A2026"))
    p.poly(rr(bx - 0.32 * R, by + 0.38 * R, 0.64 * R, 0.80 * R, 0.04 * R), hexc(h.get("color", "#B89A78")))
    p.poly(rect(bx - 0.32 * R, by + 0.38 * R, 0.64 * R, 0.04 * R), hexc("#E0C8A8"), 0.7)


def _h_suitcase(p, h, R, f, pose):
    bx, by = h["at"]
    gy = h.get("ground", by + 1.6 * R)
    cx = bx - f * 0.55 * R   # rolled along behind him
    p.poly(tube([(bx, by), (cx, gy - 1.25 * R)], 0.05 * R), METAL_LIT)
    p.poly(rr(cx - 0.40 * R, gy - 1.30 * R, 0.80 * R, 1.18 * R, 0.10 * R), hexc("#3A3446"))
    p.poly(rect(cx - 0.40 * R, gy - 1.30 * R, 0.80 * R, 0.04 * R), hexc("#7A7090"), 0.8)
    for wx in (cx - 0.26 * R, cx + 0.26 * R):
        p.circle(wx, gy - 0.07 * R, 0.07 * R, METAL)


def _h_trophy(p, h, R, f, pose):
    bx, by = h["at"]
    gold = hexc("#C9A24A")
    p.poly(np.array([(bx - 0.28 * R, by - 0.62 * R), (bx + 0.28 * R, by - 0.62 * R), (bx + 0.16 * R, by - 0.25 * R),
                     (bx - 0.16 * R, by - 0.25 * R)]), gold)
    p.poly(rect(bx - 0.04 * R, by - 0.26 * R, 0.08 * R, 0.20 * R), gold)
    p.poly(rect(bx - 0.18 * R, by - 0.08 * R, 0.36 * R, 0.10 * R), hexc("#3A2E26"))
    p.poly(rect(bx - 0.28 * R, by - 0.64 * R, 0.56 * R, 0.04 * R), hexc("#FFE0A0"), 0.8)


def _h_gift(p, h, R, f, pose):
    bx, by = h["at"]
    p.poly(rect(bx - 0.26 * R, by - 0.40 * R, 0.52 * R, 0.42 * R), hexc("#8A3A4E"))
    p.poly(rect(bx - 0.04 * R, by - 0.40 * R, 0.08 * R, 0.42 * R), hexc("#E8D8C0"))
    p.poly(rect(bx - 0.28 * R, by - 0.44 * R, 0.56 * R, 0.07 * R), hexc("#A84A5E"))
    for s in (-1, 1):
        p.poly(rell(bx + s * 0.10 * R, by - 0.48 * R, 0.10 * R, 0.05 * R, s * 0.5), hexc("#E8D8C0"))


def _h_money(p, h, R, f, pose):
    bx, by = h["at"]
    for k, a in enumerate((-0.35, -0.12, 0.12)):
        ang = -math.pi / 2 + a * f
        c, s = math.cos(ang), math.sin(ang)
        cx, cy = bx + c * 0.22 * R, by + s * 0.22 * R
        p.poly(_slab(cx, cy, 0.50 * R, 0.24 * R, ang), hexc(("#6E8A6A", "#7E9A78", "#8AA884")[k]))


HOLDS = {  # kind: (draw, under the near arm?)
    "box": (_h_box, True), "clipboard": (_h_clipboard, True), "phone": (_h_phone, False), "phone_up": (_h_phone, False),
    "phone_ear": (_h_phone, False), "cup": (_h_cup, False), "book": (_h_book, False), "letter": (_h_letter, False),
    "pen": (_h_pen, True), "spoon": (_h_spoon, False), "spatula": (_h_spatula, True), "dumbbell": (_h_dumbbell, False),
    "broom": (_h_broom, True), "rag": (_h_rag, True), "wrench": (_h_wrench, True), "hammer": (_h_hammer, True),
    "mic": (_h_mic, False), "glass": (_h_glass, False), "bottle": (_h_bottle, False), "flowers": (_h_flowers, False),
    "bag": (_h_bag, True), "suitcase": (_h_suitcase, True), "trophy": (_h_trophy, False), "gift": (_h_gift, False),
    "money": (_h_money, False),
}


def _hand(p, el, wr, kind, R, body):
    if kind == "hidden":
        return
    dx, dy = wr[0] - el[0], wr[1] - el[1]
    d = max(math.hypot(dx, dy), 1e-6)
    cx, cy = wr[0] + dx / d * 0.10 * R, wr[1] + dy / d * 0.10 * R
    p.poly(rell(cx, cy, 0.16 * R if kind == "open" else 0.14 * R, 0.11 * R, math.atan2(dy, dx)), body)


def draw_person(p: Paint, pose: dict, look: Look, eyes: Eyes | None) -> dict:
    """A person in a pose (pose_*, tools/silhouette_actions.py), in a look, with eyes (None: hidden). Drawn without the
    rim (the layer gets it). Returns where the head is and where a phone's screen glows (for the light layers)."""
    R, f, T = pose["R"], pose["f"], pose["T"]
    body, cloth, coat, fold = look.body, look.cloth, look.coat, look.fold()
    hx, hy = pose["head"]
    lying = pose.get("lying")
    hood_up = pose.get("hood_up") and look.hood
    out = {"head": (hx, hy), "glow": None}
    # long hair falls behind the torso
    if look.hair == "long" and not lying:
        p.poly(tube([(hx - f * 0.30 * R, hy - 0.55 * R), (hx - f * 0.78 * R, hy + 0.45 * R),
                     (hx - f * 0.62 * R, hy + 1.70 * R)], 1.00 * R, 0.62 * R), look.hair_color)
    # the far arm (with what its hand holds) and the legs (behind the torso: its hem covers their tops)
    if pose.get("far"):
        sh, el, wr = pose["far"]
        p.poly(tube([sh, el, wr], R * 0.38, R * 0.30), fold)
        if pose["hands"][0] == "fist":
            p.poly(ell(wr[0], wr[1] + 0.08 * R, 0.13 * R, 0.15 * R, 24), body)
        elif pose["hands"][0] == "open":
            _hand(p, el, wr, "open", R, body)
    if pose.get("far_hold"):
        HOLDS[pose["far_hold"]["kind"]][0](p, pose["far_hold"], R, f, pose)
    for k, (hip, knee, foot) in enumerate(pose["legs"]):
        p.poly(tube([hip, knee, foot], R * 0.105, R * 0.095), body)
        if pose.get("plank"):
            p.poly(rell(foot[0], foot[1] + 0.02 * R, 0.10 * R, 0.24 * R, 0.0), body)
        elif lying:
            p.poly(rell(foot[0] + f * 0.05 * R, foot[1] - 0.06 * R, 0.09 * R, 0.18 * R, 0.0), body)
        elif pose.get("toes") and pose["toes"][k]:   # a kneeling leg: the foot on its toes behind
            p.poly(rell(foot[0] - f * 0.10 * R, foot[1] - 0.06 * R, 0.20 * R, 0.07 * R, 0.5 * f), body)
        else:
            p.poly(ell(foot[0] + f * 0.13 * R, foot[1] - 0.045 * R, 0.25 * R, 0.085 * R, 28), body)
    # the hood lying behind his neck
    if look.hood and not hood_up:
        hx_, hy_ = T(-0.40, 0.02)
        p.poly(ell(hx_, hy_, 0.50 * R, 0.32 * R, 40), cloth)
    # the torso: the hoodie (or coat, jacket, dress), its folds, the hem's rib
    b = look.build
    hem = min(look.hem, pose.get("hem_max", 9.0))
    if look.dress and hem > 3.0:   # fitted to the waist, then a skirt flaring to the knee
        prof = [(-0.56, 0.12), (-0.16, -0.08), (0.34, -0.03), (0.60, 0.50), (0.62, 1.30), (0.50, 2.05),
                (0.92, hem), (-0.90, hem), (-0.58, 2.05), (-0.68, 1.30), (-0.66, 0.50)]
    else:
        prof = [(-0.60, 0.12), (-0.18, -0.08), (0.36, -0.03), (0.64, 0.50), (0.70, 1.50), (0.66, 2.55), (0.60, hem),
                (-0.62, hem), (-0.70, min(2.40, hem - 0.4)), (-0.74, 1.30), (-0.70, 0.50)]
        if hem > 3.0:  # a long coat flares a little
            prof[5], prof[6], prof[7] = (0.72, 2.6), (0.74, hem), (-0.70, hem)
    torso = spline([T(u * b, v) for u, v in prof], True, 10)
    p.poly(torso, coat)
    if look.jacket is not None:   # the open jacket: the shirt between its fronts, a lapel
        p.poly(spline([T(0.34 * b, -0.02), T(0.62 * b, 0.40), T(0.66 * b, 1.40), T(0.62 * b, 2.30), T(0.48 * b, 2.30),
                       T(0.40 * b, 1.30)], True, 6), cloth)
        p.poly(tube([T(0.30 * b, 0.02), T(0.46 * b, 0.70), T(0.42 * b, 1.30)], R * 0.05), fold, 0.8)
    p.poly(tube([T(0.14 * b, 0.78), T(0.24 * b, 1.18)], R * 0.022), fold, 0.85)
    if look.hood:
        p.poly(tube([T(-0.32 * b, 2.02), T(0.10 * b, 2.06), T(0.50 * b, 1.96)], R * 0.02), fold, 0.6)
        p.poly(tube([T(-0.58 * b, 2.66), T(0.58 * b, 2.66)], R * 0.02), fold, 0.5)
    elif look.dress:
        p.poly(tube([T(-0.56 * b, 2.05), T(0.50 * b, 2.05)], R * 0.03), fold, 0.6)   # the waist's seam
    elif look.jacket is None:
        p.poly(tube([T(0.20 * b, 0.20), T(0.42 * b, min(2.6, hem - 0.3))], R * 0.02), fold, 0.55)  # the front edge
    if look.apron is not None:   # over the clothes: a bib from the chest, ties at the waist, down past the hem
        low = min(hem + 0.9, pose.get("hem_max", 9.0) + 0.4)
        p.poly(np.array([T(0.22 * b, 0.55), T(0.68 * b, 0.55), T(0.76 * b, 1.70), T(0.86 * b, low), T(0.10 * b, low),
                         T(0.16 * b, 1.70)]), look.apron)
        p.poly(tube([T(0.26 * b, 0.56), T(0.10, 0.05)], R * 0.03), look.apron)
        p.poly(tube([T(-0.66 * b, 1.70), T(0.20 * b, 1.70)], R * 0.035), np.clip(look.apron * 0.8, 0, 1))
    if look.collar is not None:
        p.poly(np.array([T(0.10 * b, -0.02), T(0.52 * b, 0.04), T(0.40 * b, 0.70)]), look.collar)
    if look.tie is not None:
        p.poly(tube([T(0.44 * b, 0.10), T(0.50 * b, 1.30)], R * 0.07, R * 0.10), look.tie)
    if look.stethoscope:
        p.poly(tube([T(-0.05, 0.02), T(0.30 * b, 0.55), T(0.52 * b, 1.05)], R * 0.03), hexc("#2A2A34"), 0.9)
        p.circle(*T(0.54 * b, 1.10), R * 0.07, hexc("#5A5A68"))
    # the neck
    nx, ny = T(0.08, 0.02)
    p.poly(tube([(hx + (nx - hx) * 0.25, hy + (ny - hy) * 0.25), (nx, ny)], R * 0.10), body)
    if look.strings and not pose.get("plank"):
        for du, dl in ((0.30, 0.58), (0.18, 0.50)):
            top = T(du * b, 0.02)
            bot = T(du * b + 0.03, 0.02 + dl)
            p.poly(tube([top, bot], R * 0.034), PAL["eye"], 0.95)
    # what the near hand holds, under the arm (a box, a broom...); the near arm (a soft darker edge so it reads against
    # the body), the hand; what it holds over the hand (a phone, a cup, a book...)
    hold = pose.get("hold")
    draw_hold = HOLDS.get(hold["kind"]) if hold else None
    if draw_hold and draw_hold[1]:
        draw_hold[0](p, hold, R, f, pose)
    sh, el, wr = pose["near"]
    p.poly(tube([sh, el, wr], R * 0.46, R * 0.39), fold, 0.55, soft=R * 0.02)
    p.poly(tube([sh, el, wr], R * 0.40, R * 0.31), coat)
    p.poly(tube([(el[0] * 0.25 + wr[0] * 0.75, el[1] * 0.25 + wr[1] * 0.75), wr], R * 0.31), fold, 0.35)
    _hand(p, el, wr, pose["hands"][1], R, body)
    if draw_hold and not draw_hold[1]:
        got = draw_hold[0](p, hold, R, f, pose)
        if hold["kind"] in ("phone", "phone_up", "phone_ear"):
            out["glow"] = got
    # the head: hair behind it, the hood when it's up, the face, the eyes
    if look.hair == "bun" and not lying:
        p.circle(hx - f * 1.02 * R, hy - 0.30 * R, 0.40 * R, look.hair_color)
        p.poly(ell(hx - f * 0.28 * R, hy - 0.22 * R, 1.06 * R, 1.03 * R, 56), look.hair_color)
    if look.hair == "long" and not lying:
        p.poly(ell(hx - f * 0.16 * R, hy - 0.12 * R, 1.10 * R, 1.08 * R, 56), look.hair_color)
    if hood_up:
        p.poly(tube([(hx - f * 0.55 * R, hy + 0.55 * R), T(-0.35, 0.15)], R * 0.85, R * 0.75), cloth)
        p.poly(ell(hx - f * 0.15 * R, hy - 0.03 * R, 1.16 * R, 1.13 * R, 64), cloth)
        p.poly(tube([(hx - f * 0.40 * R, hy - 0.90 * R), (hx - f * 0.95 * R, hy - 0.10 * R),
                     (hx - f * 0.60 * R, hy + 0.80 * R)], R * 0.022), fold, 0.6)
        p.circle(hx + f * 0.06 * R, hy + 0.05 * R, 0.90 * R, body)
    else:
        p.circle(hx, hy, R, body)
    if look.hair == "short" and not hood_up:   # over the top and the back, down to a hairline at the forehead and ear
        outer = _arc(hx - f * 0.05 * R, hy - 0.04 * R, 1.06 * R, f, -0.55, -math.pi - 0.70, 30)
        line = [(hx - f * 0.62 * R, hy + 0.52 * R), (hx - f * 0.30 * R, hy + 0.06 * R), (hx - f * 0.04 * R, hy - 0.32 * R),
                (hx + f * 0.42 * R, hy - 0.56 * R)]
        p.poly(np.vstack([outer, line]), look.hair_color)
    if look.beard is not None and not lying:   # the jaw and the chin, a sideburn, a moustache: never round the back
        outer = _arc(hx, hy + 0.02 * R, 1.05 * R, f, 0.38, math.pi / 2 + 0.50, 22)
        line = [(hx - f * 0.40 * R, hy + 0.55 * R), (hx - f * 0.30 * R, hy + 0.10 * R), (hx - f * 0.18 * R, hy + 0.12 * R),
                (hx + f * 0.10 * R, hy + 0.48 * R), (hx + f * 0.60 * R, hy + 0.40 * R)]
        p.poly(np.vstack([outer, line]), look.beard)
    if look.cap is not None:
        top = ell(hx - f * 0.04 * R, hy - 0.52 * R, 1.02 * R, 0.52 * R, 48)
        p.poly(top[top[:, 1] <= hy - 0.40 * R], look.cap)
        p.poly(rr(min(hx + f * 0.45 * R, hx + f * 1.30 * R), hy - 0.52 * R, 0.85 * R, 0.13 * R, 0.06 * R), look.cap)
    if look.helmet is not None:   # a hard hat: the dome, its ridge, the brim
        dome = _arc(hx - f * 0.02 * R, hy - 0.30 * R, 1.10 * R, f, -0.05, -math.pi + 0.05, 36)
        p.poly(dome, look.helmet)
        p.poly(rr(hx - (1.25 * R if f > 0 else 1.45 * R), hy - 0.40 * R, 2.70 * R, 0.15 * R, 0.07 * R), look.helmet)
        p.poly(tube(_arc(hx - f * 0.02 * R, hy - 0.30 * R, 1.06 * R, f, -0.9, -2.3, 12), R * 0.05),
               np.clip(look.helmet * 1.35, 0, 1), 0.7)
    if eyes is not None and not pose.get("face_hidden"):
        lift = pose.get("lift", 0.0)
        ex, ey = (hx + f * 0.06 * R, hy + 0.04 * R) if hood_up else (hx, hy)
        spots = eyes.draw(p, ex, ey - 0.10 * R * lift, R * (0.92 if hood_up else 1.0))
        if look.glasses and spots and not eyes.smile:
            rim_c = hexc("#9C96A8")
            for sx, sy, r in spots:
                p.poly(tube(ell(sx, sy, r * 1.45, r * 1.35, 24)[list(range(24)) + [0]], R * 0.035, k=2), rim_c, 0.85)
            (ax, ay, ar), (bx2, by2, br) = spots
            p.poly(tube([(ax + ar * 1.45, ay - ar * 0.2), (bx2 - br * 1.45, by2 - br * 0.2)], R * 0.03), rim_c, 0.85)
            back = spots[0] if f > 0 else spots[1]
            p.poly(tube([(back[0] - f * back[2] * 1.45, back[1] - back[2] * 0.3), (hx - f * 0.70 * R, hy - 0.10 * R)],
                        R * 0.03), rim_c, 0.7)
    if pose.get("face_hidden"):  # his hand over his face: the near hand drawn again on top
        p.poly(rell(wr[0], wr[1], 0.19 * R, 0.14 * R, 0.6 * f), body)
    return out


class Figure:
    """The earlier interface (style test 2's sets): a person of head radius R in a look, drawn standing or walking."""

    def __init__(self, R=95.0, look: Look | None = None):
        self.R, self.look = R, look or LOOKS["him"]

    def draw_standing(self, p: Paint, x: float, ground: float, pose: dict):
        j = pose_stand(x, ground, pose.get("facing", 1), self.R, slump=pose.get("slump", 0.0), lift=pose.get("lift", 0.0),
                       arms=pose.get("arms", "pockets"), walk=pose.get("walk", 0.0), phase=pose.get("phase", 0.0),
                       hood_up=bool(pose.get("hood_up")))
        return draw_person(p, j, self.look, pose.get("eyes"))
