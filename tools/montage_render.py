"""
The Constructivist Montage look's renderer (your choice, 2026-11-04): real archive film, photographs and documents, all printed in
ink on paper with one red, cut hard to a machine beat, as a vertical 1080x1920 Short at 24 frames a second. Python, like the
faceless renderer, so the cloud run needs no browser.

The look's rules come from the Lemo-Opuscar toolbox's kino-montage style (MIT, commit bebbbe1; see assets/fonts/NOTICE-montage.txt):
its print grade, palette, axis, slams, wipes and shot formats, redrawn here for an upright frame. It's a set of reusable shots
that Gemini directs (tools/montage.py), so it has less craft than that style's hand-made demo film.

  Print grade    every picture goes luminance -> percentile stretch -> S curve -> ink..paper, with one set of percentiles per clip so
                 it never pumps. Pictures are kept as grey arrays and coloured by one table as they're drawn.
  The grid       120 BPM. Every scene starts on a half beat, and every cut, slam and count inside one lands on a beat, half beat or
                 sixteenth. Each scene is drawn from nothing for any moment in time: draw(t) has no memory, so stills, the audit and
                 the wipes all see what the video shows.
  Type           Oswald and Space Mono (open licence, in assets/fonts), on the -18 degree axis or as blocks, never floating.
  Loop           the last frame is the first frame: a red wipe in the last quarter second reveals the opening.

Case (what agents/animator.py hands over):
  {"manifest": <montage.v1, tools/montage.py>, "assets": {"a1": {"kind": "film"|"stock"|"photo"|"document", "path", "tag",
   "focus": [x, y], "cutout": <png or None>}}, "narration": {"wav", "seconds", "lines": [{"start", "end", "words"}], "voice_end"},
   "drops": [{"kind": "type", "line": <scene number>}]}

The Reviewer reads what render() returns, as with the other renderers: the layout audit's findings and the shots in order
("archive:a3"). Nothing from outside reaches a command line except a file path this system chose.

Usage:
    python tools/montage_render.py --case .tmp/case.json --out .tmp/out/montage.mp4 [--music score.m4a]
    python tools/montage_render.py --case .tmp/case.json --still 3.5 --out .tmp/out/frame.jpg
"""

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import sfx
import short_render
from common import ASSETS_DIR, TMP_DIR, tmp_path
from doc_render import AUDIT_EVERY, SAFE_BOTTOM, SAFE_RIGHT, SAFE_RIGHT_FROM, _overlap, caption_chunks

W, H, FPS = 1080, 1920, 24
SAMPLE_RATE = 44_100
RENDER_TIMEOUT_S = 900
BPM = 120
BEAT = 60 / BPM          # 0.5 s; a bar is 2 s
BAR = BEAT * 4
HALF = BEAT / 2          # scenes start on these
SIXTEENTH = BEAT / 4     # the shortest cut: 3 frames at 24 fps
END_PAD = 0.1            # the video ends about this long after the sound of the last word (it loops straight back)
SILENCE = BEAT           # the look's one silent beat
WIPE = 0.25              # seconds a red wipe takes
INK = (20, 18, 16)
PAPER = (237, 228, 208)
RED = (213, 43, 30)
AXIS = math.radians(-18)
WIPE_ANGLE = math.radians(72)
WIPE_BAND = 260          # px across
OSWALD = ASSETS_DIR / "fonts" / "Oswald[wght].ttf"
MONO = ASSETS_DIR / "fonts" / "SpaceMono-Bold.ttf"
TOP = 170                # type stays below the Shorts player's top bar
LEFT, RIGHT = 40, 1040
SUB_TOP = 1400           # subtitles start here; key type stays above it while he's speaking
FLOOR_Y = 1560           # the middle of the dark wedge's top edge
SUB_SIZE = 74
FILM_WIDTH = 960         # px a 640-wide film is prepared at (1.5x, lanczos); windows then take it to at most 2.5x overall
STOCK_WIDTH = 1000
PHOTO_LONG = 2000
FLICKER = 6              # film's flicker, in grey levels (+/- 2.5%)
SETTLE = 0.5             # seconds a layout problem has to last to count
FOLEY = {   # a printed action's sound: (sound effect in assets/sfx, gain, semitones up)
    "slam": [("bass_hit", 0.55, 0), ("metal_clank", 0.35, 0)], "stamp": [("gavel_bang", 0.5, 0)], "cut": [("pop_click", 0.22, 0)],
    "wipe": [("whoosh_fast", 0.45, 0)], "paper": [("page_flip", 0.45, 0)], "marker": [("paper_rip", 0.25, 0)],
    "freeze": [("camera_shutter", 0.5, 0)], "final": [("cinematic_boom", 0.8, 0), ("metal_clank", 0.4, 0)],
    "rivet": [("pop_click", 0.4, 0), ("metal_clank", 0.2, 0)], "type": [("typewriter_keys", 0.2, 0)],
}
PRINT_TONE = 0.32        # how strong the S curve is (documents: 0.18, they keep their paper)
GRADE = {"film": (0.7, 99.5, PRINT_TONE), "stock": (0.7, 99.5, PRINT_TONE), "photo": (0.8, 99.4, PRINT_TONE),
         "document": (0.5, 99.0, 0.18)}


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def seg(t: float, a: float, b: float) -> float:
    return clamp((t - a) / (b - a))


def eo(p: float) -> float:
    return 1 - (1 - clamp(p)) ** 3


def eio(p: float) -> float:
    p = clamp(p)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def back(p: float, s: float = 1.8) -> float:
    p = clamp(p) - 1
    return 1 + p * p * ((s + 1) * p + s)


def slam(lt: float, t0: float = 0.0, d: float = 0.12) -> float:
    """1 before t0, easing out to a hard stop at 0: how much of its travel an element still has to come."""
    return 1 - eo(seg(lt, t0, t0 + d))


def noise(n: float) -> float:
    n = math.sin(n * 127.1 + 311.7) * 43758.5453
    return n - math.floor(n)


# --- the print grade --------------------------------------------------------------------

def tone(x: np.ndarray, s: float = PRINT_TONE) -> np.ndarray:
    """x 0..1 -> the S curve (contrast up, like a halftone print of a press photo)."""
    return np.clip(x + s * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 2, 0, 1)


def grade_table(lo: float, hi: float, s: float = PRINT_TONE) -> np.ndarray:
    """256 -> 256: what a picture's grey value becomes once it's printed, for its own low and high percentiles."""
    x = np.arange(256, dtype=np.float32)
    return (tone(np.clip((x - lo) / max(1.0, hi - lo), 0, 1), s) * 255).round().astype(np.uint8)


def ink_table() -> np.ndarray:
    """256 x 1 x 3: a printed grey value as colour, ink to paper."""
    g = np.arange(256, dtype=np.float32)[:, None] / 255
    return (np.float32(INK) + (np.float32(PAPER) - np.float32(INK)) * g).round().astype(np.uint8)[:, None, :]


PRINT = ink_table()


def printed(g: np.ndarray) -> np.ndarray:
    """Printed grey values as colour."""
    import cv2

    return cv2.LUT(cv2.merge([g, g, g]), PRINT)


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _trim_plain(g: np.ndarray, tolerance: float = 7.0, most: float = 0.14) -> tuple[int, int, int, int]:
    """(top, bottom, left, right) of a picture without the plain borders old prints and film transfers have round them
    (a row or column with hardly any detail, at most `most` of a side)."""
    h, w = g.shape[:2]
    rows, cols = g.std(axis=1), g.std(axis=0)
    top = 0
    while top < h * most and rows[top] < tolerance:
        top += 1
    bottom = h
    while h - bottom < h * most and rows[bottom - 1] < tolerance:
        bottom -= 1
    left = 0
    while left < w * most and cols[left] < tolerance:
        left += 1
    right = w
    while w - right < w * most and cols[right - 1] < tolerance:
        right -= 1
    return top, bottom, left, right


class Material:
    """One film clip or picture, printed, and ready to be drawn at any moment. Films are decoded once into a file of grey frames
    in the work folder (read as they're needed, so memory stays low); one set of percentiles per clip."""

    def __init__(self, name: str, spec: dict, work: Path):
        self.name, self.spec, self.work = name, spec, work
        self.kind = spec.get("kind") or "photo"
        self.moving = self.kind in ("film", "stock")
        self.tag = spec.get("tag") or ""
        focus = spec.get("focus") or [0.5, 0.45]
        self.fx, self.fy = clamp(float(focus[0])), clamp(float(focus[1]))
        self._frames, self._cutout, self._sharp = None, None, None

    def close(self) -> None:
        """Lets go of its file (Windows can't delete one still mapped)."""
        self._frames = None

    def sharpest(self) -> float:
        """How many seconds into the clip its sharpest frame is (a freeze holds on it: old film is soft, and some frames softer)."""
        if self._sharp is None:
            import cv2

            frames = self.frames
            step = max(1, len(frames) // 24)
            scores = [(float(cv2.Laplacian(np.asarray(frames[i][::2, ::2]), cv2.CV_32F).var()), i) for i in range(0, len(frames), step)]
            self._sharp = max(scores)[1] / FPS
        return self._sharp

    def _prepared(self) -> np.ndarray:
        import cv2

        path = Path(self.spec["path"])
        key = hashlib.sha1(f"{path.resolve()}|{path.stat().st_size}|{self.kind}|3".encode()).hexdigest()[:16]
        dest = self.work / f"{key}.npy"
        if dest.exists():
            return np.load(dest, mmap_mode="r")
        part = dest.with_suffix(".part.npy")
        lo, hi, s = GRADE[self.kind]
        if not self.moving:
            with Image.open(path) as im:
                im = im.convert("L")
                im.thumbnail((PHOTO_LONG, PHOTO_LONG), Image.LANCZOS)
                g = np.asarray(im)
            top, bottom, left, right = _trim_plain(g)
            g = g[top:bottom, left:right]
            p = np.percentile(g, [lo, hi])
            np.save(part, cv2.LUT(g, grade_table(p[0], p[1], s))[None, ...])
        else:
            cap = cv2.VideoCapture(str(path))
            sw, sh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if sw < 16 or sh < 16:
                raise RuntimeError(f"can't read the video {path.name}")
            wide = min(int(sw * 1.5), FILM_WIDTH) if self.kind == "film" else min(sw, STOCK_WIDTH)
            tall = _even(wide * sh / sw)
            wide = _even(wide)
            clean = "hqdn3d=2:2:4:4," if self.kind == "film" else ""
            raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-i", str(path), "-an", "-vf",
                                  f"{clean}scale={wide}:{tall}:flags=lanczos,unsharp=5:5:0.45:5:5:0,fps={FPS},format=gray",
                                  "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, timeout=300, check=True).stdout
            frames = np.frombuffer(raw, dtype=np.uint8)
            count = len(frames) // (wide * tall)
            if not count:
                raise RuntimeError(f"no frames in the video {path.name}")
            frames = frames[:count * wide * tall].reshape(count, tall, wide)
            mean = frames[:: max(1, count // 12)].mean(axis=0)
            top, bottom, left, right = _trim_plain(mean)
            gate = 6 if self.kind == "film" else 0  # (a transfer's gate edge)
            frames = frames[:, top + gate:bottom - gate, left + gate:right - gate]
            p = np.percentile(frames[:: max(1, count // 24), ::5, ::5], [lo, hi])
            np.save(part, cv2.LUT(frames, grade_table(p[0], p[1], s)))
        part.replace(dest)
        return np.load(dest, mmap_mode="r")

    @property
    def frames(self) -> np.ndarray:
        if self._frames is None:
            self._frames = self._prepared()
        return self._frames

    def size(self) -> tuple[int, int]:
        return self.frames.shape[2], self.frames.shape[1]

    def at(self, lt: float, speed: float = 1.0, mode: str = "ping") -> np.ndarray:
        """Its printed grey frame, lt seconds in. A clip goes back and forth when it runs out, so it never stops on a frame."""
        frames = self.frames
        n = len(frames)
        if n == 1:
            return frames[0]
        i = int(max(lt, 0.0) * speed * FPS + 1e-6)
        if mode == "ping":
            period = max(1, 2 * n - 2)
            i %= period
            if i >= n:
                i = period - i
        return frames[min(i, n - 1)]

    def cutout(self) -> tuple[np.ndarray, np.ndarray] | None:
        """The person cut out of it, (printed grey, alpha), or None."""
        if self._cutout is None:
            self._cutout = False
            path = self.spec.get("cutout")
            if path and Path(path).exists():
                import cv2

                with Image.open(path) as im:
                    rgba = np.asarray(im.convert("LA"))
                    g, a = rgba[..., 0], rgba[..., 1]
                lo, hi, tone_s = GRADE["photo"]
                inside = g[a > 200]
                if inside.size:  # (printed by the same grade as everything else; its border is pure white, so it stays paper)
                    low, high = np.percentile(inside[inside < 250] if (inside < 250).any() else inside, [lo, hi])
                    g = cv2.LUT(g, grade_table(low, high, tone_s))
                self._cutout = (g, a)
        return self._cutout or None


# --- type -------------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _font(family: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    if family == "mono":
        return ImageFont.truetype(str(MONO), max(6, int(size)))
    font = ImageFont.truetype(str(OSWALD), max(6, int(size)))
    font.set_variation_by_axes([int(weight)])
    return font


def measure(text: str, size: float, family: str = "osw", weight: int = 700, spacing: float = 0.0) -> float:
    font = _font(family, int(size), weight)
    return font.getlength(text) + spacing * max(0, len(text) - 1)


def fitted(text: str, width: float, size: float, smallest: float = 24, family: str = "osw", weight: int = 700, spacing: float = 0.0) -> int:
    """The largest size at most `size` that fits the width."""
    size = int(size)
    while size > smallest and measure(text, size, family, weight, spacing) > width:
        size = max(int(smallest), int(size * 0.96))
    return size


def trimmed(text: str, width: float, smallest: float, weight: int = 700) -> str:
    """Words that will fit the width at their smallest size: anything longer loses its last words, rather than run off the frame."""
    words = text.split()
    while len(words) > 1 and measure(" ".join(words), smallest, weight=weight) > width:
        words.pop()
    return " ".join(words)


@lru_cache(maxsize=1024)
def _type_layer(text: str, size: int, family: str, weight: int, spacing: float, angle: float) -> tuple[np.ndarray, float, float]:
    """A line of type's coverage, rotated, and where its start on the baseline falls in it. Drawn at twice the size, for clean
    diagonals."""
    import cv2

    scale = 2
    font = _font(family, size * scale, weight)
    pad = 6 * scale
    ascent, descent = font.getmetrics()
    width = int(font.getlength(text) + spacing * scale * max(0, len(text) - 1)) + 2 * pad + scale
    height = ascent + descent + 2 * pad
    img = Image.new("L", (max(1, width), height), 0)
    draw = ImageDraw.Draw(img)
    x = float(pad)
    if spacing:
        for k, ch in enumerate(text):
            draw.text((x, pad), ch, font=font, fill=255)
            x += font.getlength(text[k:k + 2]) - font.getlength(text[k + 1:k + 2]) + spacing * scale
    else:
        draw.text((x, pad), text, font=font, fill=255)
    cover = np.asarray(img)
    ox, oy = float(pad), float(pad + ascent)
    if angle:
        ca, sa = math.cos(angle), math.sin(angle)
        corners = [(x0 - ox, y0 - oy) for x0, y0 in ((0, 0), (width, 0), (width, height), (0, height))]
        xs = [u * ca - v * sa for u, v in corners]
        ys = [u * sa + v * ca for u, v in corners]
        bx, by = min(xs), min(ys)
        out_w, out_h = int(math.ceil(max(xs) - bx)) + 2, int(math.ceil(max(ys) - by)) + 2
        matrix = np.float32([[ca, -sa, -ca * ox + sa * oy - bx], [sa, ca, -sa * ox - ca * oy - by]])
        cover = cv2.warpAffine(cover, matrix, (out_w, out_h), flags=cv2.INTER_LINEAR)
        ox, oy = -bx, -by
    small = cv2.resize(cover, (max(1, cover.shape[1] // scale), max(1, cover.shape[0] // scale)), interpolation=cv2.INTER_AREA)
    return small, ox / scale, oy / scale


# --- drawing ----------------------------------------------------------------------------

def _rotated(cx: float, cy: float, w: float, h: float, angle: float) -> list[tuple[float, float]]:
    ca, sa = math.cos(angle), math.sin(angle)
    return [(cx + u * ca - v * sa, cy + u * sa + v * ca) for u, v in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def _cover(sw: int, sh: int, x: float, y: float, w: float, h: float, fx: float, fy: float, zoom: float) -> np.ndarray:
    """What fits a source into a rectangle, filling it, with its focus as central as the source allows."""
    s = max(w / sw, h / sh) * zoom
    dw, dh = sw * s, sh * s
    ox = clamp(x + w / 2 - fx * dw, x + w - dw, x)
    oy = clamp(y + h / 2 - fy * dh, y + h - dh, y)
    return np.float32([[s, 0, ox], [0, s, oy]])


class Canvas:
    """One frame being drawn."""

    def __init__(self, recording: bool = False):
        self.a = np.empty((H, W, 3), dtype=np.uint8)
        self.recording = recording
        self.boxes, self.showing = [], []

    def ground(self, color: tuple) -> None:
        self.a[:] = color

    def rect(self, x: float, y: float, w: float, h: float, color: tuple, alpha: float = 1.0) -> None:
        x0, y0, x1, y1 = max(0, int(x)), max(0, int(y)), min(W, int(x + w)), min(H, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        if alpha >= 1:
            self.a[y0:y1, x0:x1] = color
        else:
            roi = self.a[y0:y1, x0:x1]
            roi[:] = (roi * (1 - alpha) + np.float32(color) * alpha).astype(np.uint8)

    def poly(self, pts: list, color: tuple) -> None:
        import cv2

        cv2.fillPoly(self.a, [np.int32(np.round(np.float32(pts) * 16))], color, lineType=cv2.LINE_AA, shift=4)

    def band(self, cx: float, cy: float, length: float, thick: float, angle: float, color: tuple) -> None:
        self.poly(_rotated(cx, cy, length, thick, angle), color)

    def line(self, x0: float, y0: float, x1: float, y1: float, color: tuple, width: int) -> None:
        import cv2

        cv2.line(self.a, (int(x0), int(y0)), (int(x1), int(y1)), color, width, cv2.LINE_AA)

    def ring(self, cx: float, cy: float, rx: float, ry: float, progress: float, color: tuple = RED, width: int = 12) -> None:
        """A marker's ring, drawn round as progress goes from 0 to 1."""
        import cv2

        if progress <= 0:
            return
        cv2.ellipse(self.a, (int(cx), int(cy)), (int(rx), int(ry)), 0, -110, -110 + 378 * clamp(progress), color, width, cv2.LINE_AA)

    def _blend(self, x0: int, y0: int, patch: np.ndarray, mask: np.ndarray) -> None:
        import cv2

        roi = self.a[y0:y0 + patch.shape[0], x0:x0 + patch.shape[1]]
        w1 = mask.astype(np.float32) / 255
        roi[:] = cv2.blendLinear(patch, roi, w1, 1 - w1)

    def image(self, g: np.ndarray, matrix: np.ndarray, pts: list, flicker: int = 0) -> None:
        """A printed grey picture through `matrix` (picture to frame), showing only inside the polygon `pts`."""
        import cv2

        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, y0 = max(0, int(math.floor(min(xs)))), max(0, int(math.floor(min(ys))))
        x1, y1 = min(W, int(math.ceil(max(xs))) + 1), min(H, int(math.ceil(max(ys))) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        shift = matrix.copy()
        shift[0, 2] -= x0
        shift[1, 2] -= y0
        patch = cv2.warpAffine(np.asarray(g), shift, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if flicker:
            patch = cv2.add(patch, flicker) if flicker > 0 else cv2.subtract(patch, -flicker)
        rgb = printed(patch)
        upright = (len(pts) == 4 and min(xs) == x0 and min(ys) == y0 and max(xs) == x1 and max(ys) == y1
                   and all(p[0] in (x0, x1) and p[1] in (y0, y1) for p in pts))
        if upright:
            self.a[y0:y1, x0:x1] = rgb
            return
        mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        cv2.fillPoly(mask, [np.int32(np.round((np.float32(pts) - (x0, y0)) * 16))], 255, lineType=cv2.LINE_AA, shift=4)
        self._blend(x0, y0, rgb, mask)

    def window(self, m: Material, x: float, y: float, w: float, h: float, lt: float = 0.0, zoom: float = 1.0, clip: list | None = None,
               speed: float = 1.0, frame_no: int = 0, fx: float | None = None, fy: float | None = None) -> tuple[float, float]:
        """A picture filling a rectangle (clip: the polygon it really shows in). Film flickers; photographs don't. Returns where
        the picture's focus landed."""
        g = m.at(lt, speed)
        sh, sw = g.shape[:2]
        matrix = _cover(sw, sh, x, y, w, h, m.fx if fx is None else fx, m.fy if fy is None else fy, zoom)
        pts = clip or [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        flick = int(round((noise(frame_no * 3.1) - 0.5) * 2 * FLICKER)) if m.kind == "film" else 0
        self.image(g, matrix, pts, flick)
        if self.recording:
            self.showing.append(m.name)
        return (float(matrix[0, 0] * m.fx * sw + matrix[0, 2]), float(matrix[1, 1] * m.fy * sh + matrix[1, 2]))

    def tilted(self, m: Material, cx: float, cy: float, w: float, h: float, angle: float, lt: float = 0.0, zoom: float = 1.0,
               speed: float = 1.0, frame_no: int = 0) -> None:
        """A picture in a rectangle turned by `angle`, turned with it."""
        g = m.at(lt, speed)
        sh, sw = g.shape[:2]
        local = _cover(sw, sh, -w / 2, -h / 2, w, h, m.fx, m.fy, zoom)
        ca, sa = math.cos(angle), math.sin(angle)
        turn = np.float32([[ca, -sa], [sa, ca]])
        matrix = np.zeros((2, 3), dtype=np.float32)
        matrix[:, :2] = turn @ local[:, :2]
        matrix[:, 2] = turn @ local[:, 2] + np.float32([cx, cy])
        flick = int(round((noise(frame_no * 3.1) - 0.5) * 2 * FLICKER)) if m.kind == "film" else 0
        self.image(g, matrix, _rotated(cx, cy, w, h, angle), flick)
        if self.recording:
            self.showing.append(m.name)

    def flash(self, x: float, y: float, w: float, h: float, alpha: float = 0.6) -> None:
        """The look's flash cut: one frame of paper over a window."""
        self.rect(x, y, w, h, PAPER, alpha)

    def cutout(self, m: Material, x: float, y: float, height: float, flip: bool = False, multiply: bool = False) -> None:
        """The person cut out of a picture, standing with their top left at x, y."""
        import cv2

        found = m.cutout()
        if not found:
            return
        g, a = found
        s = height / g.shape[0]
        w = max(2, int(g.shape[1] * s))
        h = max(2, int(height))
        gs = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        ms = cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if flip:
            gs, ms = gs[:, ::-1], ms[:, ::-1]
        ix, iy = int(x), int(y)
        x0, y0, x1, y1 = max(0, ix), max(0, iy), min(W, ix + w), min(H, iy + h)
        if x1 <= x0 or y1 <= y0:
            return
        gs = gs[y0 - iy:y1 - iy, x0 - ix:x1 - ix]
        ms = ms[y0 - iy:y1 - iy, x0 - ix:x1 - ix]
        rgb = printed(np.ascontiguousarray(gs))
        if multiply:
            roi = self.a[y0:y1, x0:x1]
            rgb = (rgb.astype(np.uint16) * roi.astype(np.uint16) // 255).astype(np.uint8)
        self._blend(x0, y0, rgb, np.ascontiguousarray(ms))
        if self.recording:
            self.showing.append(m.name)

    def text(self, text: str, x: float, y: float, size: float, fill: tuple = INK, family: str = "osw", weight: int = 700, spacing: float = 0.0,
             angle: float = 0.0, align: str = "left", bg: tuple | None = None, pad: float = 0, record: str | None = "type") -> tuple[float, float, float, float]:
        """A line of type with its start on the baseline at x, y (`align` moves that point along the line). Returns the box it
        covers; `record` names it for the layout audit."""
        size = int(size)
        width = measure(text, size, family, weight, spacing)
        shift = -width if align == "right" else -width / 2 if align == "center" else 0.0
        ca, sa = math.cos(angle), math.sin(angle)
        px, py = x + shift * ca, y + shift * sa
        ascent, descent = (size * 0.86, size * 0.05) if family == "osw" else (size * 0.8, size * 0.18)
        corners = [(u, v) for u, v in ((-pad, -ascent - pad), (width + pad, -ascent - pad), (width + pad, descent + pad), (-pad, descent + pad))]
        pts = [(px + u * ca - v * sa, py + u * sa + v * ca) for u, v in corners]
        if bg is not None:
            self.poly(pts, bg)
        layer, ox, oy = _type_layer(text, size, family, weight, float(spacing), float(angle))
        ix, iy = int(round(px - ox)), int(round(py - oy))
        lh, lw = layer.shape[:2]
        x0, y0, x1, y1 = max(0, ix), max(0, iy), min(W, ix + lw), min(H, iy + lh)
        if x1 > x0 and y1 > y0:
            cover = layer[y0 - iy:y1 - iy, x0 - ix:x1 - ix]
            patch = np.empty(cover.shape + (3,), dtype=np.uint8)
            patch[:] = fill
            self._blend(x0, y0, patch, cover)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = (min(xs), min(ys), max(xs), max(ys))
        if record and self.recording:
            self.boxes.append((record, box, text, pts))
        return box

    def tag(self, text: str, x: float, y: float, align: str = "left", color: tuple = INK) -> None:
        """A source tag: Space Mono on an ink or red tab."""
        room = (x - 20 if align == "right" else W - x - 20) - 14
        self.text(text, x, y, fitted(text, room, 24, 14, "mono", spacing=0.5), PAPER, "mono", spacing=0.5, align=align, bg=color, pad=7, record="tag")


def on(ground: tuple) -> tuple:
    """Type's colour on a ground."""
    return INK if ground == PAPER else PAPER


def not_red(color: tuple, ground: tuple) -> tuple:
    """The look's rule: red is never laid on red."""
    return INK if color == RED and ground == RED else color


def stamped(c: Canvas, text: str, x: float, y: float, size: int, fill: tuple, lt: float, t0: float, step: float = SIXTEENTH, weight: int = 700) -> float:
    """Type stamped down one character at a time. Returns how far it reaches."""
    at = 0.0
    for k, ch in enumerate(text):
        begin = t0 + k * step
        wide = measure(text[:k + 1], size, weight=weight) - at
        if lt >= begin and ch != " ":
            o = slam(lt, begin, 0.08)
            c.text(ch, x + at, y - o * 900, size, fill, weight=weight, record=None)
        at += wide
    if lt >= t0 + (len(text) - 1) * step + 0.08 and c.recording:
        ascent = size * 0.86
        c.boxes.append(("type", (x, y - ascent, x + at, y + size * 0.05), text, None))
    return x + at


def on_band(cx: float, cy: float, along: float, across: float = 0.0, angle: float = AXIS) -> tuple[float, float]:
    """A point on a band: `along` its length from the point cx, cy, and `across` towards its lower side."""
    return (cx + along * math.cos(angle) - across * math.sin(angle), cy + along * math.sin(angle) + across * math.cos(angle))


def floor(c: Canvas) -> None:
    """An ink wedge along the axis across the bottom of a light frame: it grounds the sheet, and YouTube's white title text and buttons,
    laid over this part of the frame, stay readable."""
    k = math.tan(AXIS)
    c.poly([(0, FLOOR_Y - k * W / 2), (W, FLOOR_Y + k * W / 2), (W, H), (0, H)], INK)


# --- the scenes -------------------------------------------------------------------------

class Scene:
    """One of the Short's scenes: its format, when it runs, its pictures and its words. Formats take their settings from here."""

    def __init__(self, spec: dict, start: float, end: float, items: list[Material], index: int):
        self.spec, self.start, self.end, self.items, self.index = spec, start, end, items, index
        self.kind = spec.get("format") or "window"
        self.dur = max(end - start, 0.25)
        self.big = spec.get("big") or ""
        self.unit = spec.get("unit") or ""
        self.words = [str(w) for w in spec.get("words") or [] if str(w).strip()]
        self.side = 1 if spec.get("side", 1 if index % 2 == 0 else -1) >= 0 else -1
        ground = spec.get("ground")
        self.ground = {"paper": PAPER, "ink": INK, "red": RED}.get(ground, PAPER)
        self.cuts = []     # local times of the cuts inside it
        self.hits = []     # (local time, how hard: px of shake)
        self.sounds = []   # (local time, foley)
        self.ends_loop = False
        self.cuts_count = 0
        planner = PLANS.get(self.kind)
        if planner:
            planner(self)

    def pick(self, lt: float, step: float) -> tuple[Material | None, float, int]:
        """What's showing when the pictures change every `step` seconds: (picture, seconds it's been on, which cut this is)."""
        n = max(0, int(lt / step + 1e-6))
        if not self.items:
            return None, lt, n
        return self.items[n % len(self.items)], lt - n * step, n

    def every(self, step: float, hit: float = 0.0, sound: str | None = "cut", start: float = 0.0) -> None:
        """Cuts every `step` seconds, on the grid."""
        at = start + step
        while at < self.dur - 0.01:
            self.cuts.append(at)
            if hit:
                self.hits.append((at, hit))
            if sound:
                self.sounds.append((at, sound))
            at += step


def _cut_step(s: Scene, longest: float = 1.5) -> float:
    """How long each picture stays so a scene's pictures all show: 0.5 to `longest` s, on the beat."""
    count = max(1, len(s.items))
    return max(BEAT, min(longest, math.ceil(s.dur / count / BEAT) * BEAT))


def cuts_in(s: Scene) -> int:
    """How many cuts a scene has (the renderer's count of shots)."""
    return 1 + len({round(x, 3) for x in s.cuts})


def _film_offset(s: Scene, n: int, m: Material | None) -> float:
    """Different moments of a film each time the same clip comes back."""
    return 0.0 if m is None or not m.moving else (s.index * 0.37 + n * 0.61) % 2.0


CROPS = ((1.0, 0.0, 0.0), (1.28, 0.0, -0.08), (1.14, 0.1, 0.04), (1.38, -0.08, 0.06))  # zoom, and how far off the focus


def _crop(m: Material | None, n: int) -> tuple[float, float, float]:
    """The n-th cut's framing of a picture: a picture that comes back is never framed the same (a jump in, as the style's freeze does).
    Old film stays near its ceiling of 2.5 times its pixels, so it only moves its window."""
    if m is None:
        return 1.0, 0.5, 0.45
    zoom, dx, dy = CROPS[n % len(CROPS)]
    return (1.0 if m.moving else zoom), clamp(m.fx + dx), clamp(m.fy + dy)


def _push(m: Material | None, ml: float) -> float:
    """A still pushes in steadily; film barely needs it."""
    return 1 + max(ml, 0.0) * (0.055 if m is not None and not m.moving else 0.015)


def _flash_on_cut(c: Canvas, ml: float, n: int, x: float, y: float, w: float, h: float, alpha: float = 0.55) -> None:
    if n > 0 and 0 <= ml < 1 / FPS - 1e-6:
        c.flash(x, y, w, h, alpha)


# Title: a red band landed on the very first frame, a window cut to the band's edge running film above it, and the headline stamped
# one character per sixteenth below it. The opening frame comes back as the last frame (the loop).

def plan_title(s: Scene) -> None:
    s.hits += [(0.0, 16.0)]
    s.sounds += [(0.0, "final")]
    text = _title_text(s)
    for k in range(len(text)):
        if text[k] != " ":
            s.hits.append((BEAT + k * SIXTEENTH, 5.0))
            s.sounds.append((BEAT + k * SIXTEENTH, "stamp"))
    s.every(_cut_step(s, 1.0), 0.0, "cut")


def _title_text(s: Scene) -> str:
    return trimmed((s.big or " ".join(s.words[:1]) or "").upper(), SAFE_RIGHT - LEFT, 60)


def draw_title(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(PAPER)
    floor(c)
    bar_y, thick = 800.0, 210.0
    k = math.tan(AXIS)
    edge = lambda x: bar_y + k * (x - W / 2) - thick / 2 / math.cos(AXIS)
    m, ml, n = s.pick(max(lt, 0.0), _cut_step(s, 1.0))
    if m:
        zoom, fx, fy = _crop(m, n)
        c.window(m, 0, 0, W, edge(0), ml + _film_offset(s, n, m), zoom=zoom * _push(m, ml), clip=[(0, 0), (W, 0), (W, edge(W)), (0, edge(0))], frame_no=frame_no,
                 fx=fx, fy=fy)
        _flash_on_cut(c, ml, n, 0, 0, W, edge(0), 0.5)
    c.band(W / 2, bar_y, 2400, thick, AXIS, RED)
    c.band(W / 2 + 40, bar_y + thick / 2 + 44, 2400, 24, AXIS, INK)
    line = (s.words[0] if s.big and s.words else " ".join(s.words[1:]) if s.words else "").upper()
    if line:
        line = trimmed(line, 960, 44)
        size = fitted(line, 960, 112, 44)
        px, py = on_band(W / 2, bar_y, 0, size * 0.36)
        c.text(line, px, py, size, PAPER, align="center", angle=AXIS)
    text = _title_text(s)
    width = SAFE_RIGHT - LEFT
    if text:
        size = fitted(text, width, 290, 60)
        stamped(c, text, LEFT, 1352, size, INK, lt, BEAT)
    if s.unit and lt >= BEAT:
        reach = LEFT + measure(text, fitted(text, width, 290, 60))
        o = slam(lt, BEAT + len(text) * SIXTEENTH, 0.1) * 600
        unit = s.unit.upper()
        c.text(unit, reach + 18 + o, 1352, fitted(unit, SAFE_RIGHT - reach - 18, 90, 36), RED, record=None)
    if m:
        c.tag(m.tag, LEFT, TOP + 12)


# Window: a tall window leaning along the axis, running film; the words turned up its open side; the date or number on a red band
# crossing it.

def plan_window(s: Scene) -> None:
    s.hits += [(0.0, 8.0), (0.375, 9.0)]
    s.sounds += [(0.0, "slam"), (0.375, "slam")]
    s.every(_cut_step(s), 0.0, "cut")


def draw_window(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(s.ground)
    if s.ground != INK:
        floor(c)
    side = s.side
    mir = (lambda x: x) if side > 0 else (lambda x: W - x)
    tall = 1200
    pts = [(mir(0), 0), (mir(880), 0), (mir(760), tall), (mir(0), tall)]
    x0 = min(p[0] for p in pts)
    w = 880
    m, ml, n = s.pick(max(lt, 0.0), _cut_step(s))
    o = slam(lt, 0.0, 0.16) * 1100
    shifted = [(p[0] - side * o, p[1]) for p in pts]
    if m:
        zoom, fx, fy = _crop(m, n + s.index)
        c.window(m, x0 - side * o, 0, w, tall, ml + _film_offset(s, n, m), zoom=zoom * _push(m, ml), clip=shifted, frame_no=frame_no, fx=fx, fy=fy)
        _flash_on_cut(c, ml, n, x0, 0, w, tall)
        if lt < 1 / FPS:
            c.flash(x0, 0, w, tall, 0.6)
    ink = on(s.ground)
    if s.words:
        # the words stacked up the open side, one line for each word given, turned to read upward
        length = SAFE_RIGHT_FROM - 20 - TOP if side > 0 else 1320 - TOP
        joined = trimmed(" ".join(s.words[:3]).upper(), length, 60)
        size = fitted(joined, length, 176, 60)
        ox = 1030 if side > 0 else 50 + size * 0.86
        c.text(joined, ox + side * slam(lt, 0.25, 0.12) * 500, TOP + length, size, ink, angle=-math.pi / 2)
    if s.big:
        bo = slam(lt, 0.375, 0.16) * 2200
        # the band comes in from the window's side of the frame and stops at the window's edge, cut square
        length = 1500
        reach = 830 if side > 0 else W - 830
        bx = reach - side * length / 2 * math.cos(AXIS)
        by = 980 - side * length / 2 * math.sin(AXIS)
        cx, cy = bx - side * bo * math.cos(AXIS), by - side * bo * math.sin(AXIS)
        c.band(cx, cy, length, 190, AXIS, not_red(RED, s.ground))
        size = fitted(s.big.upper(), 620, 150, 60)
        px, py = on_band(cx, cy, side * (length / 2 - 390), size * 0.36)
        c.text(s.big.upper(), px, py, size, PAPER, align="center", angle=AXIS)
    if s.unit:
        o2 = slam(lt, 0.625, 0.12) * 700
        c.text(s.unit.upper(), LEFT - o2, 1300, fitted(s.unit.upper(), 620, 64, 34), PAPER, bg=INK, pad=12)
    if m:
        c.tag(m.tag, mir(LEFT) if side > 0 else W - LEFT, TOP + 12, "left" if side > 0 else "right")


# Stacked type: the words themselves are the structure, each one the frame's full width, slammed in from alternate sides; the last in
# red; film running in a strip under them.

def plan_stack(s: Scene) -> None:
    for k in range(len(_stack_lines(s))):
        s.hits.append((k * HALF, 7.0))
        s.sounds.append((k * HALF, "slam" if k == 0 else "stamp"))
    s.every(_cut_step(s), 0.0, None)


def _stack_lines(s: Scene) -> list[str]:
    lines = [w.upper() for w in s.words[:4]]
    if s.big:
        lines.append(s.big.upper())
    return [trimmed(line, SAFE_RIGHT - LEFT, 56) for line in lines[:5]]


def draw_stack(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(s.ground)
    if s.ground != INK:
        floor(c)
    ink = on(s.ground)
    lines = _stack_lines(s)
    if not lines:
        return
    width = RIGHT - LEFT
    sizes = [fitted(line, width, 460, 56) for line in lines]
    gap = 22
    limit = 1370 - TOP
    at = TOP
    for k, line in enumerate(lines):  # (a line that ends up beside YouTube's buttons is kept clear of them)
        at += sizes[k] * 0.86 + gap
        if at > SAFE_RIGHT_FROM:
            sizes[k] = fitted(line, SAFE_RIGHT - LEFT, sizes[k], 56)
    heights = [sz * 0.86 + gap for sz in sizes]
    used = sum(heights)
    room = limit - used
    strip = bool(s.items) and room >= 180
    if room < 0:
        shrink = limit / used
        sizes = [int(sz * shrink) for sz in sizes]
        heights = [sz * 0.86 + gap for sz in sizes]
    y = TOP
    if strip:
        m, ml, n = s.pick(max(lt, 0.0), _cut_step(s, 1.0))
        o = slam(lt, 0.0, 0.14) * 900
        h = min(room - 30, 640)
        sy = 1370 - h
        zoom, fx, fy = _crop(m, n)
        c.window(m, LEFT - s.side * o, sy, width, h, ml + _film_offset(s, n, m), zoom=zoom * _push(m, ml), frame_no=frame_no, fx=fx, fy=fy)
        c.rect(LEFT - s.side * o, sy - 12, width, 12, RED if s.ground != RED else INK)
        _flash_on_cut(c, ml, n, LEFT, sy, width, h)
        c.tag(m.tag, LEFT, sy + 34)
    for k, (line, size) in enumerate(zip(lines, sizes)):
        y += size * 0.86
        fill = not_red(RED, s.ground) if k == len(lines) - 1 else ink
        o = slam(lt, k * HALF, 0.1) * 1300 * (1 if k % 2 else -1)
        if lt >= k * HALF:
            c.text(line, LEFT + o, y, size, fill)
        y += gap


# Grid: nine windows light one per sixteenth in a spiral; the middle counts and lights last, in red, with the number.

GRID_ORDER = (0, 1, 2, 5, 8, 7, 6, 3, 4)


def _grid_step(s: Scene) -> float:
    return SIXTEENTH if s.dur < 3.5 else HALF


def plan_grid(s: Scene) -> None:
    step = _grid_step(s)
    for k in range(9):
        s.hits.append((k * step, 2.5))
        s.sounds.append((k * step, "rivet"))
    s.cuts += [k * step for k in range(1, 9)]
    s.every(BEAT, 0.0, "cut", 9 * step - BEAT + (0 if step == HALF else BEAT))


def draw_grid(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(s.ground)
    if s.ground != INK:
        floor(c)
    cw, ch, gap = 336, 336, 12
    x0, y0 = (W - 3 * cw - 2 * gap) / 2, TOP + 26
    step = _grid_step(s)
    lit = 0
    items = s.items or []
    block = not_red(RED, s.ground)
    for order, cell in enumerate(GRID_ORDER):
        at = order * step
        if lt < at:
            continue
        lit += 1
        x, y = x0 + (cell % 3) * (cw + gap), y0 + (cell // 3) * (ch + gap)
        grow = back(seg(lt, at, at + 0.12), 1.6)
        w, h = cw * grow, ch * grow
        rx, ry = x + (cw - w) / 2, y + (ch - h) / 2
        if cell == 4:
            c.rect(rx, ry, w, h, block)
        elif items:
            # full: one cell changes on every beat, round the spiral
            changed = 0
            beats_after = int((lt - 9 * step) / BEAT + 1e-6) if lt >= 9 * step else -1
            if beats_after >= 0:
                changed = (beats_after + 8 - order) // 8 if order < 8 else 0
            m = items[(order + changed * 3) % len(items)]
            zoom, fx, fy = _crop(m, order + changed)
            ml = (lt - at) if not changed else (lt - 9 * step) % BEAT
            c.window(m, rx, ry, w, h, lt - at + order * 0.2, zoom=zoom, speed=1.5, frame_no=frame_no + order * 7, fx=fx, fy=fy)
            if ml < 1 / FPS - 1e-6:
                c.flash(rx, ry, w, h, 0.5)
    cx, cy = x0 + cw + gap + cw / 2, y0 + ch + gap + ch / 2
    if lit:
        text = s.big if s.big and lit >= 9 else str(lit)
        size = fitted(text, cw - 24, 300, 70)
        # the count shows on the dark until the middle lights
        c.text(text, cx, cy + size * 0.40, size, PAPER if lit >= 9 else block, align="center")
    words = trimmed(" ".join(s.words[:3]).upper() or s.unit.upper(), SAFE_RIGHT - LEFT - 40, 40)
    if words and lit >= 9:
        o = slam(lt, 9 * step, 0.12) * 900
        c.text(words, LEFT - o, 1354, fitted(words, SAFE_RIGHT - LEFT - 40, 92, 40), PAPER, bg=block, pad=16)
    if items:
        c.tag(items[0].tag, x0, y0 - 12)


# Split strips: the frame turned to the axis, three strips of two panels each; one panel changes on every beat; strips drift in opposite
# directions, with a red seam on the middle one.

def plan_strips(s: Scene) -> None:
    s.hits += [(0.0, 8.0)]
    s.sounds += [(0.0, "slam")]
    s.every(BEAT, 0.0, "cut")


def draw_strips(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(s.ground)
    if s.ground != INK:
        floor(c)
    if not s.items:
        return
    strip, gap = 400, 24
    total = 3 * strip + 2 * gap
    panel = 1160
    beat = int(max(lt, 0.0) / BEAT + 1e-6)
    centre = np.float32([W / 2, 760])
    ca, sa = math.cos(AXIS), math.sin(AXIS)
    for i in range(3):
        y = -total / 2 + i * (strip + gap) + strip / 2
        direction = -1 if i % 2 else 1
        change = (beat + (3 - i)) // 3
        enter = slam(lt, i * SIXTEENTH, 0.14) * 2600 * direction
        drift = direction * (max(lt, 0.0) * 90 - 60)
        for j in range(2):
            m = s.items[(i * 2 + j + change * (j + 1)) % len(s.items)]
            x = -panel - 12 + j * (panel + 24) + drift + enter + panel / 2
            cx, cy = centre[0] + x * ca - y * sa, centre[1] + x * sa + y * ca
            c.tilted(m, cx, cy, panel, strip, AXIS, max(lt, 0.0) + i * 0.3 + j * 0.5, speed=1.5, frame_no=frame_no + i + j)
        if i == 1:
            rx, ry = centre[0] - (y - strip / 2 - gap / 2) * sa, centre[1] + (y - strip / 2 - gap / 2) * ca
            c.band(rx, ry, 3000, gap, AXIS, not_red(RED, s.ground))
    if s.big or s.words:
        text = trimmed((s.big or " ".join(s.words[:3])).upper(), 860, 44)
        o = slam(lt, 0.25, 0.12) * 900
        c.text(text, LEFT - o, 1330, fitted(text, 860, 150, 44), PAPER, bg=not_red(RED, s.ground), pad=16)
    c.tag(s.items[0].tag, LEFT, TOP + 12)


# Freeze: flash, a frozen frame pushing in, a red ring drawn on what matters, a leader to a red block with the number; a jump-in; the film
# keeps running in a small red-framed inset.

FREEZE_FOR = 3.0         # seconds one freeze holds


def _freezes(s: Scene) -> tuple[float, int]:
    """How long each freeze holds, and how many there are: a long scene freezes again on another picture."""
    count = max(1, min(len(s.items) or 1, round(s.dur / FREEZE_FOR)))
    return round(s.dur / count / BEAT) * BEAT or s.dur, count


def plan_freeze(s: Scene) -> None:
    hold, count = _freezes(s)
    s.hits += [(SIXTEENTH, 6.0)]
    for k in range(count):
        at = k * hold
        s.hits.append((at, 10.0))
        s.sounds += [(at, "freeze"), (at + HALF, "marker")]
        if at:
            s.cuts.append(at)
        if hold > 1.75:
            s.hits.append((at + 1.25, 6.0))
            s.sounds.append((at + 1.25, "freeze"))
            s.cuts.append(at + 1.25)


def draw_freeze(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(INK)
    x, y, w, h = LEFT, TOP, RIGHT - LEFT, 880
    hold, count = _freezes(s)
    k = min(count - 1, max(0, int(lt / hold + 1e-6)))
    m = s.items[k % len(s.items)] if s.items else None
    local = lt - k * hold
    jumped = local >= 1.25 and hold > 1.75
    jump = 1.2 if jumped else 1.0
    zoom = (1 + eo(seg(local, 0, 0.45)) * 0.08 + max(local, 0) * 0.012) * jump
    rx, ry = x + w / 2, y + h * 0.45
    if m:
        rx, ry = c.window(m, x, y, w, h, m.sharpest(), zoom=zoom, frame_no=0)
        rx, ry = clamp(rx, x + 200, x + w - 200), clamp(ry, y + 240, y + h - 240)
    if local < 1 / FPS - 1e-6 or (jumped and local < 1.25 + 1 / FPS - 1e-6):
        c.flash(x, y, w, h, 0.8 if not jumped else 0.4)
    # the ring on what matters, drawn round, with a leader to the block
    if local >= HALF and m:
        c.ring(rx, ry, 170 * jump, 200 * jump, eo(seg(local, HALF, HALF + 0.25)))
    text = (s.big or "").upper()
    unit = s.unit.upper()
    if text:
        size = fitted(text, 500, 250, 70)
        bw = measure(text, size) + 64
        bh = size + 40
        by = y + h - bh + 70
        o = slam(lt, SIXTEENTH, 0.12) * 800
        if local >= 0.5:
            p = eo(seg(local, 0.5, 0.625))
            sx, sy = rx - 110 * jump, ry + 150 * jump
            c.line(sx, sy, sx + (LEFT + bw * 0.6 - sx) * p, sy + (by - sy) * p, RED, 8)
        c.rect(LEFT - o, by, bw, bh, RED)
        c.text(text, LEFT + 32 - o, by + 20 + size * 0.88, size, PAPER)
        if unit:
            c.text(unit, LEFT + 10 - o, by + bh + 66, fitted(unit, 700, 58, 30, weight=600), PAPER, weight=600, bg=None)
    if m and m.moving and local >= 0.5:
        o = slam(local, 0.5, 0.12) * 600
        pw, ph = 350, 262
        px, py = 960 - pw + o, 1092
        c.rect(px - 8, py - 8, pw + 16, ph + 16, RED)
        c.window(m, px, py, pw, ph, 1.1 + (local - 0.5), frame_no=frame_no)
    if m:
        c.tag(m.tag, LEFT + 10, TOP + 42)


# Staircase: three windows rising along a diagonal, with red triangles between them, and a counter climbing to the claim.

STAIRS = ((30, 950), (240, 555), (440, 160))
STAIR_W, STAIR_H = 610, 360


def plan_staircase(s: Scene) -> None:
    for k in range(3):
        s.hits.append((k * 0.75, 5.0))
        s.sounds.append((k * 0.75, "slam"))
    s.cuts += [0.75, 1.5]
    s.every(BEAT, 0.0, "cut", 1.5 + BEAT)


def draw_staircase(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(s.ground)
    if s.ground != INK:
        floor(c)
    w, h = STAIR_W, STAIR_H
    tri = not_red(RED, s.ground)
    for k, (x, y) in enumerate(STAIRS):
        at = k * 0.75
        if lt < at:
            continue
        o = slam(lt, at, 0.14) * 700
        if s.items:
            beats = int((lt - 2.0) / BEAT + 1e-6) + 1 if lt >= 2.0 else 0
            changed = (beats + 2 - k) // 3 if beats else 0
            m = s.items[(k + changed * 3) % len(s.items)]
            zoom, fx, fy = _crop(m, k + changed)
            c.window(m, x, y + o, w, h, lt - at + k * 0.3, zoom=zoom * _push(m, lt - at), frame_no=frame_no + k, fx=fx, fy=fy)
            if lt - at < 1 / FPS - 1e-6 or (changed and (beats - 1) % 3 == k and (lt - 2.0) % BEAT < 1 / FPS - 1e-6):
                c.flash(x, y, w, h, 0.6)
        if k < 2 and lt >= (k + 1) * 0.75 - 0.1:  # a ramp up to the next window
            right = x + w + 20
            top = STAIRS[k + 1][1] + h + 10
            c.poly([(right, y + h), (W + 20, y + h), (W + 20, top)], tri)
    if s.big:
        text = s.big.upper()
        value = _count_up(text, eo(seg(lt, 0.1, min(2.3, s.dur - 0.2))))
        size = fitted(text, 380, 270, 70)
        c.text(value, LEFT, TOP + size * 0.86 + 10, size, tri, record=None)
        if c.recording:
            c.boxes.append(("type", (LEFT, TOP + 10, LEFT + measure(text, size), TOP + 10 + size * 0.9), text, None))
    label = trimmed((s.unit or " ".join(s.words[:3])).upper(), 262, 24)
    if label and lt >= 0.25:
        o = slam(lt, 0.25, 0.12) * 900
        size = fitted(label, 262, 70, 24)
        c.text(label, 670 + o, 1290, size, PAPER, bg=INK if s.ground != INK else RED, pad=12)
    if s.items:
        c.tag(s.items[0].tag, 30, 1352)


def _count_up(text: str, p: float) -> str:
    """A number on its way to its end value, in place in its line (only the first number moves; its commas are kept). The end value is
    the fact; the way there is a graphic."""
    import re

    found = re.search(r"\d[\d,]*", text)
    if not found or p >= 1:
        return text
    digits = found[0].replace(",", "")
    value = int(int(digits) * p)
    shown = f"{value:,}" if "," in found[0] else str(value)
    return text[:found.start()] + shown + text[found.end():]


# The question: ink ground, the question's words on a paper tab tilted along the axis, ringed in red; then a huge red question mark.

def _question_at(s: Scene) -> float:
    return min(1.0, round(s.dur * 0.5 / BEAT) * BEAT or BEAT)


def plan_question(s: Scene) -> None:
    q_at = _question_at(s)
    s.hits += [(0.0, 9.0), (q_at, 10.0)]
    s.sounds += [(0.0, "slam"), (HALF, "marker"), (q_at, "slam")]
    at = q_at + BAR
    while at < s.dur - 0.25:
        s.hits.append((at, 7.0))
        s.sounds.append((at, "stamp"))
        at += BAR


def draw_question(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(INK)
    q_at = _question_at(s)
    if lt >= q_at:
        again = (lt - q_at) % BAR if lt >= q_at + BAR else 1.0
        grow = back(seg(lt, q_at, q_at + 0.15), 2.0) * (1 + 0.06 * (1 - eo(again / 0.2)))
        size = int(980 * grow)
        if size > 8:
            c.text("?", 790, 1350, size, RED, align="center", record=None)
    if s.items:
        m = s.items[0]
        o = slam(lt, 0.0, 0.14) * 900
        c.tilted(m, 360 - o, 1110, 620, 430, math.radians(5), lt, zoom=1.03 + max(lt, 0) * 0.05, frame_no=frame_no)
        c.tag(m.tag, LEFT, 1370)
    lines = [trimmed(w.upper(), 860, 44) for w in s.words[:3]]
    if lines:
        o = slam(lt, 0.0, 0.16) * 1200
        y = 300.0
        ang = math.radians(-4)
        size = min(fitted(line, 860, 150, 44) for line in lines)
        w = max(measure(line, size) for line in lines) + 90
        h = len(lines) * size * 1.08 + 70
        cx, cy = LEFT + w / 2 - o, y + h / 2
        c.poly(_rotated(cx, cy, w, h, ang), PAPER)
        for k, line in enumerate(lines):
            lx, ly = on_band(cx, cy, -w / 2 + 45, -h / 2 + 35 + (k + 1) * size * 1.0, ang)
            c.text(line, lx, ly, size, INK, angle=ang)
        if lt >= 0.5:
            c.ring(cx, cy, w / 2 + 40, h / 2 + 60, eo(seg(lt, 0.5, 0.9)))


# Acceleration: a window nearly filling the frame, tilted, the ground turning red and ink with every cut, cuts halving down to a
# sixteenth; a counter jumping with them to its end value, then held.

ACCEL_RUN = (BEAT, BEAT, HALF, HALF, HALF, HALF, SIXTEENTH, SIXTEENTH, SIXTEENTH, SIXTEENTH)  # a run of shots, each shorter


def _accel_cuts(s: Scene) -> list[float]:
    """Cut times: a run of shots halving down to a sixteenth, starting over if the scene is longer than one run, and a last shot held for the
    number. The eighth-second cuts stay few: a long strobe is hard on people sensitive to flashes (more than three flashes a second is the
    usual limit), so the ground only changes on the quarter-second ones and those get no paper flash."""
    times, at, k = [0.0], 0.0, 0
    while True:
        step = ACCEL_RUN[k % len(ACCEL_RUN)]
        if at + step >= s.dur - 0.5:
            break
        at += step
        times.append(at)
        k += 1
    return times


def plan_acceleration(s: Scene) -> None:
    times = _accel_cuts(s)
    s.accel = times
    for at in times:
        s.hits.append((at, 6.0 if at else 8.0))
        s.sounds.append((at, "rivet"))
    s.cuts += times[1:]
    ground, grounds = 0, []
    for k, at in enumerate(times):
        length = (times[k + 1] - at) if k + 1 < len(times) else 1.0
        if length >= HALF:
            ground = 1 - ground
        grounds.append(ground)
    s.accel_grounds = grounds


def draw_acceleration(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    times = getattr(s, "accel", [0.0])
    k = max(0, next((i for i in range(len(times) - 1, -1, -1) if lt >= times[i]), 0))
    held = k == len(times) - 1 and lt > times[-1] + 0.25
    length = (times[k + 1] - times[k]) if k + 1 < len(times) else 1.0
    ground = RED if getattr(s, "accel_grounds", [0])[min(k, len(getattr(s, "accel_grounds", [0])) - 1)] else INK
    c.ground(ground)
    if ground == RED:
        floor(c)
    if s.items:
        m = s.items[k % len(s.items)]
        tilt = math.radians((-5 if k % 2 else 5) + (k % 3 - 1))
        ml = lt - times[k]
        c.tilted(m, W / 2, 750, 1000, 1160, tilt, ml + k * 0.31, zoom=1.02 + ml * 0.18, frame_no=frame_no)
        if ml < 1 / FPS - 1e-6 and length >= BEAT:
            c.flash(0, 0, W, H, 0.3)
        c.tag(m.tag, LEFT, TOP + 12)
    if s.big:
        text = s.big.upper()
        p = (k + 1) / len(times) if not held else 1.0
        value = text if held or k == len(times) - 1 else _count_up(text, p ** 2)
        size = fitted(text, 640, 240, 70)
        block = INK if ground == RED else RED
        bw = measure(text, size) + 60
        c.rect(LEFT, 1370 - size - 30, bw, size + 30, block)
        c.text(value, LEFT + 30, 1370 - 30, size, PAPER, record=None)
        if c.recording:
            c.boxes.append(("type", (LEFT, 1370 - size - 30, LEFT + bw, 1370), text, None))
        if s.unit:  # (beside the number if it fits there, clear of YouTube's buttons; otherwise above it)
            room = SAFE_RIGHT - LEFT - bw - 40
            unit = trimmed(s.unit.upper(), SAFE_RIGHT - LEFT - 40, 30, 600)
            if measure(unit, 44, weight=600) <= room:
                c.text(unit, LEFT + bw + 18, 1370 - 30, fitted(unit, room, 72, 44, weight=600), PAPER, weight=600, bg=INK, pad=10)
            else:
                c.text(unit, LEFT + 12, 1370 - size - 56, fitted(unit, SAFE_RIGHT - LEFT - 40, 64, 30, weight=600), PAPER, weight=600, bg=INK, pad=10)
    elif held and s.words:
        text = trimmed(" ".join(s.words[:3]).upper(), SAFE_RIGHT - LEFT - 40, 40)
        c.text(text, LEFT, 1340, fitted(text, SAFE_RIGHT - LEFT - 40, 120, 40), PAPER, bg=INK if ground == RED else RED, pad=16)


# Multiple exposure: a film with a second picture printed through it, people printed over both, on a red ground; the answer in an ink block
# (red would vanish on red).

def plan_exposure(s: Scene) -> None:
    s.hits += [(0.0, 10.0)]
    s.sounds += [(0.0, "slam")]
    if s.big and s.dur > 1:
        s.sounds.append((BEAT, "type"))
    s.every(BAR, 6.0, "cut")


def draw_exposure(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    import cv2

    c.ground(RED)
    floor(c)
    x, y, w, h = 60, TOP - 60, 960, 1190
    if s.items:
        turn = max(0, int(lt / BAR + 1e-6))
        a = s.items[turn % len(s.items)]
        b = s.items[(turn + 1) % len(s.items)]
        ga = a.at(max(lt, 0.0), 0.8)
        gb = b.at(max(lt, 0.0) + 0.7, 0.9)
        ma = _cover(ga.shape[1], ga.shape[0], 0, 0, w, h, a.fx, a.fy, 1.0 + (lt - turn * BAR) * (0.04 if not a.moving else 0.006))
        mb = _cover(gb.shape[1], gb.shape[0], 0, 0, w, h, b.fx, b.fy, 1.0)
        pa = cv2.warpAffine(np.asarray(ga), ma, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        pb = cv2.warpAffine(np.asarray(gb), mb, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        # "screen" at 45%: the second picture lightens the first
        mix = 255 - ((255 - pa.astype(np.uint16)) * (255 - (pb.astype(np.uint16) * 45 // 100)) // 255)
        c.a[y:y + h, x:x + w] = printed(mix.astype(np.uint8))
        if c.recording:
            c.showing += [a.name, b.name]
        people = [m for m in s.items if m.cutout()]
        for k, person in enumerate(people[:2]):
            o = slam(lt, k * 0.25, 0.14) * 900
            found = person.cutout()
            ch = min(760 if k == 0 else 620, int(found[0].shape[0] * 460 / found[0].shape[1]))
            cw = found[0].shape[1] * ch / found[0].shape[0]
            px = x + w - cw - 10 if k == 0 else x + 10
            c.cutout(person, px + o, y + h - ch, ch, flip=bool(k))
        c.tag(a.tag, 80, y + 44)
    text = trimmed(s.big.upper() if s.big else " ".join(s.words[:2]).upper(), 800, 70)
    if text:
        size = fitted(text, 800, 270, 70)
        o = slam(lt, 0.0, 0.1) * 900
        bw = measure(text, size) + 70
        by = 780
        c.rect(LEFT - o, by, bw, size + 40, INK)
        c.text(text, LEFT + 35 - o, by + 20 + size * 0.88, size, RED if s.ground != RED else PAPER)
        under = trimmed((s.unit or (" ".join(s.words[:3]) if s.big else "")).upper(), 880, 32, 600)
        if under:
            o2 = slam(lt, BEAT, 0.12) * 1000
            c.text(under, LEFT - o2, by + size + 110, fitted(under, 880, 76, 32, weight=600), INK, weight=600, bg=PAPER, pad=12)


# Photomontage tower (the signature): floors of film and photographs slam in from alternate sides every sixteenth, an ink beam under each,
# a person cut out of a photograph landing on every other; the camera climbs; a counter runs to its end value in a block.

FLOOR = 190
MOST_FLOORS = 18


def _tower_step(s: Scene) -> float:
    """Seconds between floors: a sixteenth if the scene is short, slower on the grid if it's long, so it's still building at its end."""
    for step in (SIXTEENTH, HALF, BEAT):
        if step * MOST_FLOORS >= s.dur - 0.5:
            return step
    return BEAT


def _tower_floors(s: Scene) -> int:
    return max(4, min(int((s.dur - 0.5) / _tower_step(s)), MOST_FLOORS))


def plan_tower(s: Scene) -> None:
    floors, step = _tower_floors(s), _tower_step(s)
    s.floors, s.floor_step = floors, step
    for k in range(floors):
        s.hits.append((k * step, 3.0))
        s.sounds.append((k * step, "rivet"))
    s.cuts += [k * step for k in range(1, floors)]
    s.hits.append((floors * step, 8.0))
    s.sounds.append((floors * step, "slam"))


def draw_tower(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(PAPER)
    floors, step = getattr(s, "floors", 8), getattr(s, "floor_step", SIXTEENTH)
    if s.items:
        g = s.items[0].at(max(lt, 0.0), 0.6)
        matrix = _cover(g.shape[1], g.shape[0], 0, 0, W, H, 0.5, 0.5, 1.0)
        faint = cv2_warp(np.asarray(g), matrix, (W, H))
        c.a[:] = printed((255 - (255 - faint.astype(np.uint16)) * 16 // 100).astype(np.uint8))
    c.poly([(0, H), (W * 0.62, -40), (W * 0.92, -40), (W * 0.3, H)], RED)
    built = sum(eio(seg(lt, k * step, k * step + 0.25)) for k in range(floors))
    cam = max(0.0, (built + 1.0) * FLOOR - 1000) + eo(seg(lt, floors * step, floors * step + 0.5)) * 120
    base = 1500
    people = [m for m in s.items if m.cutout()]
    standing = []
    for k in range(floors):
        at = k * step
        if lt < at:
            continue
        direction = 1 if k % 2 else -1
        fw = max(420, 860 - k * 22)
        o = slam(lt, at, 0.1) * 1400 * direction
        fx = W / 2 - fw / 2 + (k % 3 - 1) * 26 + o
        fy = base - (k + 1) * FLOOR + cam
        if people and k % 2 == 0:
            standing.append((k, at, fx, fw, fy))
        if fy > H or fy + FLOOR < 0:
            continue
        c.rect(fx - 14, fy + FLOOR - 16, fw + 28, 16, INK)
        if s.items:
            m = s.items[k % len(s.items)]
            c.window(m, fx, fy, fw, FLOOR - 16, lt - at, fy=0.25 + 0.5 * noise(k * 7.7), frame_no=frame_no + k)
    for k, at, fx, fw, fy in standing:  # (after all the floors: they stand in front of the one above)
        person = people[(k // 2) % len(people)]
        found = person.cutout()
        ch = 330
        cw = found[0].shape[1] * ch / found[0].shape[0]
        land = eo(seg(lt, at + 0.05, at + 0.2))
        px = fx + (fw - cw * 0.7 if k % 4 < 2 else -cw * 0.3)
        c.cutout(person, px, fy - ch + FLOOR - 16 - (1 - land) * 300, ch, flip=k % 4 >= 2)
    if s.big:
        text = s.big.upper()
        p = seg(built, 0, floors)
        value = _count_up(text, p) if p < 1 else text
        size = fitted(text, 720, 250, 70)
        bw = measure(text, size) + 56
        c.rect(LEFT, TOP - 10, bw, size + 26, INK)
        c.text(value, LEFT + 28, TOP + size * 0.92, size, RED if p >= 1 else PAPER, record=None)
        if c.recording:
            c.boxes.append(("type", (LEFT, TOP - 10, LEFT + bw, TOP + size + 16), text, None))
        if s.unit:
            c.text(s.unit.upper(), LEFT, TOP + size + 92, fitted(s.unit.upper(), 700, 62, 30, weight=600), PAPER, weight=600, bg=INK, pad=10)
    if s.items:
        c.tag("PHOTOMONTAGE · ARCHIVE FILM AND PHOTOS", LEFT, TOP - 22)


def cv2_warp(g: np.ndarray, matrix: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    import cv2

    return cv2.warpAffine(g, matrix, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# The one silent beat: an ink frame, one red rivet. The score and the sound effects stop for it.

def draw_silence(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    import cv2

    c.ground(INK)
    cv2.circle(c.a, (W // 2, 760), 18, RED, -1, cv2.LINE_AA)


# Result: huge numbers top left, a tall slanted window with the subject, a tilted photograph, a red wedge; the heaviest hit of the Short; the
# key number restamped on red.

def plan_result(s: Scene) -> None:
    s.hits += [(0.0, 18.0), (BEAT / 2, 10.0)]
    s.sounds += [(0.0, "final"), (BEAT / 2, "slam")]
    if s.dur > 2.5:
        again = round((s.dur - 1.0) / BEAT) * BEAT
        s.hits.append((again, 7.0))
        s.sounds.append((again, "stamp"))
    s.every(max(1.0, min(BAR, round(s.dur / 2 / BEAT) * BEAT)), 0.0, "cut")


def draw_result(c: Canvas, s: Scene, lt: float, frame_no: int) -> None:
    c.ground(PAPER)
    floor(c)
    o = slam(lt, 0.0, 0.16) * 1200
    win = [(560, -20 - o), (1090, -20 - o), (1010, 1220 - o), (480, 1220 - o)]
    c.poly([(x + (14 if k in (1, 2) else -14), y + (-14 if k < 2 else 14)) for k, (x, y) in enumerate(win)], INK)
    step = max(1.0, min(BAR, round(s.dur / 2 / BEAT) * BEAT))
    m, ml, n = s.pick(max(lt, 0.0), step)
    if m:
        c.window(m, 480, -20 - o, 610, 1240, ml + _film_offset(s, n, m), zoom=_push(m, ml) * (1.0 if m.moving else 1.12), clip=win, speed=0.6, frame_no=frame_no,
                 fy=clamp(0.85 - 0.73 * seg(lt, 0, s.dur)))
        _flash_on_cut(c, ml, n, 480, 0, 610, 1220, 0.4)
    photo = next((i for i in s.items[1:] if not i.moving), None) or (s.items[-1] if s.items else None)
    if photo:
        o2 = slam(lt, HALF, 0.16) * 900
        px, py = 310 + o2 - max(lt, 0) * 6, 960 + max(lt, 0) * 3
        ang = math.radians(6 - max(lt, 0) * 0.3)
        c.poly(_rotated(px, py, 560, 420, ang), INK)
        c.tilted(photo, px, py, 536, 396, ang, 0.0, zoom=1.05 + max(lt, 0) * 0.006, frame_no=frame_no)
    wo = slam(lt, 0.0, 0.2)
    c.poly([(-60, 1560 + wo * 600), (1010 - wo * 1200, 1120 + wo * 600), (1060 - wo * 1200, 1240 + wo * 600), (-60, 1800 + wo * 600)], RED)
    text = trimmed((s.big or " ".join(s.words[:1])).upper(), 420, 36)
    size = 0
    if text:
        size = fitted(text, 420, 300, 36)
        again = round((s.dur - 1.0) / BEAT) * BEAT if s.dur > 2.5 else 99.0
        stamp = eo(seg(lt, again, again + 0.12))
        if stamp > 0:
            c.rect(LEFT - 20, TOP - 6, (measure(text, size) + 50) * stamp, size + 22, RED)
        c.text(text, LEFT - slam(lt, 0.0, 0.1) * 1000, TOP + size * 0.92, size, PAPER if stamp >= 1 else INK)
    unit = s.unit.upper()
    below = TOP + size + 30
    if unit:
        usize = fitted(unit, 420, 130, 40)
        below += usize * 0.86
        c.text(unit, LEFT - slam(lt, HALF, 0.1) * 1000, below, usize, RED)
        below += 16
    second = trimmed(" ".join(w for w in s.words[(1 if s.big else 1):3] if w).upper(), 400, 30)
    if second:
        c.text(second, LEFT - slam(lt, BEAT, 0.12) * 900, below + 72, fitted(second, 400, 60, 30), PAPER, bg=INK, pad=12)
    if m:
        c.tag(m.tag, 500, 1380)


PLANS = {"title": plan_title, "window": plan_window, "stack": plan_stack, "grid": plan_grid, "strips": plan_strips, "freeze": plan_freeze,
         "staircase": plan_staircase, "question": plan_question, "acceleration": plan_acceleration, "exposure": plan_exposure,
         "tower": plan_tower, "result": plan_result}
DRAWS = {"title": draw_title, "window": draw_window, "stack": draw_stack, "grid": draw_grid, "strips": draw_strips, "freeze": draw_freeze,
         "staircase": draw_staircase, "question": draw_question, "acceleration": draw_acceleration, "exposure": draw_exposure,
         "tower": draw_tower, "silence": draw_silence, "result": draw_result}
FORMATS = tuple(DRAWS)


# --- the whole Short --------------------------------------------------------------------

def on_grid(t: float, step: float = HALF) -> float:
    return round(round(t / step) * step, 4)


def _fibre() -> np.ndarray:
    """The paper's fibre, multiplied over everything at half strength (one seeded texture, drawn once)."""
    rng = np.random.default_rng(1930)
    v = 235 + rng.random((H, W), dtype=np.float32) * 20
    v[rng.random((H, W), dtype=np.float32) < 0.002] -= 60
    out = np.dstack([v, v * 0.985, v * 0.96])
    return np.clip((0.5 + 0.5 * out / 255) * 255, 0, 255).astype(np.uint8)


def timeline(manifest: dict, narration: dict) -> tuple[list[dict], float]:
    """Each scene's time by his real voice: it starts on the half beat nearest its first word, picture slightly ahead of sound.
    [{"spec", "start", "end", "words"}] and the Short's length."""
    lines = narration["lines"]
    last = max([line["end"] for line in lines] + [narration.get("voice_end") or 0.0])
    total = math.ceil((last + END_PAD) / SIXTEENTH - 1e-6) * SIXTEENTH
    out = []
    for spec in manifest["scenes"]:
        wanted = spec.get("lines") or []
        if wanted and 0 <= wanted[0] < len(lines):
            first = lines[wanted[0]]["start"]
            out.append({"spec": spec, "start": max(0.0, math.floor(first / HALF + 0.4) * HALF), "lines": wanted})
        else:
            out.append({"spec": spec, "start": None, "lines": []})
    out[0]["start"] = 0.0
    for k, item in enumerate(out):  # a scene with no line of its own (the silent beat) sits just before the next
        if item["start"] is None:
            after = next((x["start"] for x in out[k + 1:] if x["start"] is not None), total)
            item["start"] = on_grid(after - SILENCE)
    for a, b in zip(out, out[1:]):
        if b["start"] <= a["start"]:
            b["start"] = a["start"] + HALF
    for a, b in zip(out, out[1:]):
        a["end"] = b["start"]
    out[-1]["end"] = total
    return out, total


class Montage:
    """Everything needed to draw the Short, for any moment."""

    def __init__(self, case: dict, work: Path | None = None):
        manifest = case["manifest"]
        self.narration = case["narration"]
        self.work = Path(work) if work else tmp_path("montage_prep", "shared")
        self.work.mkdir(parents=True, exist_ok=True)
        self.assets = {name: Material(name, spec, self.work) for name, spec in (case.get("assets") or {}).items()}
        timed, self.total = timeline(manifest, self.narration)
        drops = {(d.get("kind"), d.get("line")) for d in case.get("drops") or []}  # (by a scene's first line)
        self.scenes = []
        for k, item in enumerate(timed):
            spec = dict(item["spec"])
            if ("type", (item["lines"] or [None])[0]) in drops:
                spec.update({"big": "", "unit": "", "words": []})
            items = [self.assets[a] for a in spec.get("items") or [] if a in self.assets]
            scene = Scene(spec, item["start"], item["end"], items, k)
            scene.lines = item["lines"]
            self.scenes.append(scene)
        self.hits = sorted((s.start + at, amp) for s in self.scenes for at, amp in s.hits)
        self.wipes = [s.start for s in self.scenes[1:] if s.spec.get("wipe")]
        self.silences = [(s.start, s.end) for s in self.scenes if s.kind == "silence"]
        self.fibre = _fibre()
        self.layout, self.runs = [], {}
        self.captions = []
        for k, line in enumerate(self.narration["lines"]):
            for chunk in caption_chunks(line["words"], 4, 22):
                self.captions.append([chunk[0][0], None, chunk, k])
        for a, b in zip(self.captions, self.captions[1:]):
            a[1] = b[0]
        if self.captions:
            self.captions[-1][1] = max(self.captions[-1][0] + 0.2, self.total - 0.08)
        self.frames = int(math.ceil(self.total * FPS - 1e-6))

    def _scene_at(self, t: float) -> Scene:
        return next((s for s in self.scenes if s.start <= t < s.end), self.scenes[-1])

    def _shake(self, t: float) -> tuple[float, float]:
        x, y = 0.0, 0.0
        for at, amp in self.hits:
            d = t - at
            if d < 0:
                break
            if d > 0.35:
                continue
            e = math.exp(-d * 14) * amp
            x += math.sin(d * 90) * e
            y += math.cos(d * 77) * e * 0.7
        return x, y

    def _draw(self, c: Canvas, scene: Scene, t: float, n: int) -> None:
        DRAWS.get(scene.kind, draw_window)(c, scene, t - scene.start, n)

    def _wipe(self, c: Canvas, t: float, n: int) -> bool:
        """The red wipe: a steep band sweeps from right to left, the next scene revealed behind it. Returns whether one is on."""
        import cv2

        target, progress = None, 0.0
        for at in self.wipes:
            if at - WIPE <= t < at:
                target, progress = self._scene_at(at), (t - (at - WIPE)) / WIPE
                break
        loop_from = self.total - WIPE - 1 / FPS
        if target is None and t >= loop_from:
            target, progress = self.scenes[0], (t - loop_from) / WIPE
        if target is None:
            return False
        current = self._scene_at(t)
        if self.scenes.index(target) == 0 and target is not current:
            target_time = target.start + 0.0
        else:
            target_time = t
        self._draw(c, current, t, n)
        other = Canvas(c.recording)
        self._draw(other, target, target_time, n if target_time == t else 0)
        slope = math.cos(WIPE_ANGLE) / math.sin(WIPE_ANGLE)
        dx = slope * H / 2
        start, finish = W + dx + WIPE_BAND, -dx - WIPE_BAND
        front = start + (finish - start) * eio(progress)
        if progress >= 1 - 1e-6:
            c.a[:] = other.a
            return True
        pts = np.float32([[front + dx, 0], [W + 2000, 0], [W + 2000, H], [front - dx, H]])
        mask = np.zeros((H, W), dtype=np.uint8)
        cv2.fillPoly(mask, [np.int32(np.round(pts * 16))], 255, lineType=cv2.LINE_AA, shift=4)
        c._blend(0, 0, other.a, mask)
        c.band(front - WIPE_BAND / 2, H / 2, WIPE_BAND, 3400, WIPE_ANGLE - math.pi / 2, RED)
        c.boxes += other.boxes
        return True

    def _subtitle(self, c: Canvas, t: float) -> None:
        """Bottom left: an ink bar with a red tick, his words, and the word he's saying on a red tab."""
        for start, end, chunk, line in self.captions:
            if start <= t < end:
                words = [short_render.clean_text(w) for _, w in chunk]
                text = " ".join(words)
                size = fitted(text, SAFE_RIGHT - LEFT - 62, SUB_SIZE, 36, weight=500)
                width = measure(text, size, weight=500) + 56
                height = size + 42
                y = SUB_TOP + (124 - height) / 2
                c.rect(LEFT, y, width, height, INK, 0.9)
                c.rect(LEFT, y, 10, height, RED)
                now = max((k for k, (at, _) in enumerate(chunk) if at <= t), default=0)
                x = LEFT + 32.0
                base = y + height / 2 + size * 0.37
                space = measure(" ", size, weight=500)
                for k, word in enumerate(words):
                    wide = measure(word, size, weight=500)
                    if k == now:
                        c.rect(x - 6, y + 8, wide + 12, height - 16, RED)
                    c.text(word, x, base, size, PAPER, weight=500, record=None)
                    x += wide + space
                if c.recording:
                    c.boxes.append(("subtitle", (LEFT, y, LEFT + width, y + height), text, None))
                return

    def _shift(self, c: Canvas, sx: float, sy: float) -> None:
        import cv2

        if abs(sx) < 0.5 and abs(sy) < 0.5:
            return
        c.a = cv2.warpAffine(c.a, np.float32([[1, 0, round(sx)], [0, 1, round(sy)]]), (W, H), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)

    def frame(self, n: int, auditing: bool = True) -> np.ndarray:
        import cv2

        last = n == self.frames - 1
        t = n / FPS
        audit = auditing and n % AUDIT_EVERY == 0
        c = Canvas(audit or auditing)
        if last:  # the very last frame is the very first one, so the loop has no seam
            self._draw(c, self.scenes[0], 0.0, 0)
            sx, sy = self._shake(0.0)
        else:
            if not self._wipe(c, t, n):
                self._draw(c, self._scene_at(t), t, n)
            sx, sy = self._shake(t)
        self._shift(c, sx, sy)
        self._subtitle(c, 0.0 if last else t)
        out = cv2.multiply(c.a, self.fibre, scale=1 / 255)
        if auditing:
            k = self.scenes.index(self._scene_at(t))
            for name in set(c.showing):
                runs = self.runs.setdefault((k, name), [])
                if runs and t - runs[-1][1] <= 1.5 / FPS:
                    runs[-1][1] = t
                else:
                    runs.append([t, t])
        if audit:
            self._audit(t, c.boxes)
        return out

    def _audit(self, t: float, boxes: list) -> None:
        """Words on top of each other, under YouTube's buttons and title text, or cut off by the frame. In the same form as the other
        renderers', for the Reviewer. A source tag is small and sits on its own window, so it only counts for the frame's edges."""
        import cv2

        scene = self._scene_at(t)
        k = scene.lines[0] if scene.lines else None
        found = []
        shapes = []
        for kind, box, text, pts in boxes:
            if kind != "tag":
                x0, y0, x1, y1 = box
                shapes.append((kind, np.float32(pts if pts else [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]), text))
        for i, (a, pa, ta) in enumerate(shapes):
            for b, pb, tb in shapes[i + 1:]:
                area = cv2.intersectConvexConvex(pa, pb)[0]
                if area > 0.04 * min(cv2.contourArea(pa), cv2.contourArea(pb)):
                    found.append(("overlap", f"{a}+{b}", k, f"{ta}|{tb}"))
        for kind, box, text, _ in boxes:
            x0, y0, x1, y1 = box
            if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:  # (waiting off-screen for its moment)
                continue
            if kind != "tag" and ((x1 > SAFE_RIGHT and y1 > SAFE_RIGHT_FROM) or y1 > SAFE_BOTTOM):
                found.append(("unsafe", kind, k, text))
            if x0 < -1 or y0 < -1 or x1 > W + 1:
                found.append(("cut off", kind, k, text))
        for kind, what, line, text in found:  # (by the words themselves: type slamming in one line after another isn't one long problem)
            prior = next((x for x in reversed(self.layout) if (x["kind"], x["what"], x["line"], x["words"]) == (kind, what, line, text)), None)
            if prior and t - prior["end"] <= AUDIT_EVERY / FPS + 0.01:
                prior["end"] = round(t, 2)
            else:
                self.layout.append({"kind": kind, "what": what, "line": line, "words": text, "start": round(t, 2), "end": round(t, 2)})

    def findings(self) -> list[dict]:
        """What the audit found that stayed long enough to read: type is often off the frame or crossing other type for a moment on its
        way in."""
        return [x for x in self.layout if x["end"] - x["start"] >= SETTLE]

    def shots(self) -> list[dict]:
        """What was on screen, in order, in the form the Reviewer reads: one entry for each stretch a picture stayed up."""
        out = []
        for (k, name), runs in self.runs.items():
            scene = self.scenes[k]
            asset = self.assets.get(name)
            kind = asset.kind if asset else "film"
            prefix = "footage" if kind == "stock" else "photo" if kind in ("photo", "document") else "archive"
            for start, end in runs:
                out.append({"start": round(start, 2), "end": round(end + 1 / FPS, 2), "kind": kind, "name": f"{prefix}:{name}",
                            "line": scene.lines[0] if scene.lines else None, "format": scene.kind})
        return sorted(out, key=lambda x: (x["start"], x["name"]))


def _pitched(sound: np.ndarray, semitones: float) -> np.ndarray:
    if not semitones:
        return sound
    rate = 2 ** (semitones / 12)
    return np.interp(np.arange(0, len(sound) / rate) * rate, np.arange(len(sound)), sound).astype(np.float32)


def _speaking(narration: dict, total: float) -> np.ndarray:
    """1 for each 10 ms he's speaking in."""
    steps = np.zeros(int(total * 100) + 2, dtype=np.float32)
    for line in narration["lines"]:
        steps[int(line["start"] * 100):int(line["end"] * 100) + 1] = 1
    return steps


def foley_wav(short: Montage, dest: Path) -> list[dict]:
    """Every printed action's sound as one track, on the times the scenes planned them, 35% lower under his voice and stopped for the
    silent beat. Returns what was placed."""
    track = np.zeros(int((short.total + 2) * SAMPLE_RATE), dtype=np.float32)
    speech = _speaking(short.narration, short.total)
    placed = []
    events = []
    for s in short.scenes:
        events += [(s.start + at, name) for at, name in s.sounds if at < s.dur]
    events += [(at - WIPE, "wipe") for at in short.wipes]
    events.append((short.total - WIPE - 1 / FPS, "wipe"))
    for at, name in sorted(events):
        if any(a <= at < b for a, b in short.silences):
            continue
        for tag, gain, semitones in FOLEY.get(name, []):
            samples = sfx.effect(tag, SAMPLE_RATE)
            if samples is None or not len(samples):
                continue
            under = speech[min(int(at * 100), len(speech) - 1)] > 0
            piece = _pitched(samples, semitones)[:int(1.2 * SAMPLE_RATE)] * gain * (0.65 if under else 1.0)
            i = max(0, int(at * SAMPLE_RATE))
            piece = piece[:max(0, len(track) - i)]
            track[i:i + len(piece)] += piece
        placed.append({"tag": name, "at": round(at, 3)})
    for a, b in short.silences:
        track[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)] = 0
    track *= 10 ** (EFFECTS_DB / 20)
    fade = int(0.025 * SAMPLE_RATE)
    track[:fade] *= np.linspace(0, 1, fade)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())
    return placed


def score_wav(short: Montage, music: Path, dest: Path, volume: float) -> None:
    """The score, looped to the Short's length from its first beat (so its beat is the cuts' beat), with the silent beat cut out of it."""
    raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-stream_loop", "-1", "-ss", f"{SCORE_LEAD:.3f}", "-i", str(music), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE),
                          "-t", f"{short.total + 0.5:.2f}", "-f", "s16le", "-"], capture_output=True, check=True, timeout=120).stdout
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    pcm = pcm.reshape(-1, 2).copy()
    pcm *= 10 ** (MUSIC_DB / 20) * volume
    ramp = int(0.01 * SAMPLE_RATE)
    for a, b in short.silences:
        i, j = int(a * SAMPLE_RATE), int(b * SAMPLE_RATE)
        pcm[i:j] = 0
        pcm[max(0, i - ramp):i] *= np.linspace(1, 0, min(ramp, i))[:, None]
    fade = int(0.025 * SAMPLE_RATE)
    pcm[:fade] *= np.linspace(0, 1, fade)[:, None]
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


# Under his voice, measured on a real reading of his with every score (2026-11-04). At -3 dB and 0 dB he was 9 dB above the score and only 6 dB above the score
# and the effects together, the user found the music too loud on their first real Short, and between his words the sound was nearly as loud as his words. At these
# levels he's 17 dB above the score and 14 dB above both. They come down together, so they keep their balance. Lower still loses the beat, half of the look.
MUSIC_DB = -11.0
EFFECTS_DB = -8.0
DUCK = "threshold=0.04:ratio=4:attack=15:release=250"  # how far the score dips while he speaks
SCORE_LEAD = 0.06        # seconds its sampled notes take to rise: it starts this far in, so what you hear lands with the cut


def render(case: dict, out_path: Path | str, music: Path | None = None, volume: float = 1.0, cover_path: Path | str | None = None,
           progress=print) -> dict:
    """Draws and encodes the Short; returns its length, frame count and how long it took, what the layout audit found and the shots in
    order (for the Reviewer), in the same form as tools/faceless_render.py's render()."""
    started = time.monotonic()
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="montage_", dir=TMP_DIR / "work"))
    short = Montage(case, work)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f"{out.stem}.part{out.suffix}")  # (renamed when whole: see doc_render.render)
    effects = work / "effects.wav"
    placed = foley_wav(short, effects)
    total = short.total
    score = None
    if music:
        score = work / "score.wav"
        score_wav(short, music, score, volume)
    voice = case["narration"]["wav"]
    cmd = [short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
           "-i", str(voice), "-i", str(effects)]
    if score:
        cmd += ["-i", str(score)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    audio = (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[d];"
             f"[d]asplit=2[d1][d2];"
             f"[2:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[fx];"
             f"[3:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[m];"
             f"[m][d1]sidechaincompress={DUCK}[md];"
             f"[md][d2][fx]amix=inputs=3:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", audio, "-map", "0:v", "-map", "[aout]", "-vf", "noise=alls=4:allf=t",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", "-t", f"{total:.3f}",
            str(part)]
    errors = work / "ffmpeg.log"
    cover = None
    try:
        with open(errors, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
            try:
                for n in range(short.frames):
                    frame = short.frame(n)
                    if cover_path and n == int(1.75 * FPS):
                        cover = frame.copy()
                    proc.stdin.write(frame.tobytes())
                    if n and n % (FPS * 10) == 0:
                        progress(f"Drawn {n // FPS} of {total:.0f} seconds")
                proc.stdin.close()
                proc.wait(timeout=RENDER_TIMEOUT_S)
            except BaseException:
                proc.kill()
                proc.wait(timeout=30)
                raise
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {errors.read_text(encoding='utf-8', errors='replace')[-1500:]}")
    except BaseException:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        for material in short.assets.values():
            material.close()
    part.replace(out)
    if cover_path and cover is not None:
        Image.fromarray(cover).resize((540, 960), Image.LANCZOS).save(cover_path, quality=88)
    result = {"seconds": total, "frames": short.frames, "render_seconds": round(time.monotonic() - started, 1), "layout": short.findings(),
              "shots": short.shots(), "sounds": placed}
    _clear(work)
    return result


def _clear(work: Path) -> None:
    for item in work.iterdir():
        try:
            item.unlink()
        except OSError:
            pass  # (a file still mapped on Windows goes with the next clear-out of .tmp)
    try:
        work.rmdir()
    except OSError:
        pass


def posters(picture: Image.Image, words: list[tuple[str, bool]]) -> tuple[Image.Image, Image.Image]:
    """The case's covers in the look, (upright 1080x1920, wide 1280x720): the picture printed in ink on paper, a red band along the axis and the
    words on a dark wedge, the marked word in red."""
    return _poster(picture, words, (1080, 1920)), _poster(picture, words, (1280, 720))


def _poster(picture: Image.Image, words: list[tuple[str, bool]], size: tuple[int, int]) -> Image.Image:
    import cv2

    w, h = size
    g = np.asarray(picture.convert("L"))
    low, high = np.percentile(g, GRADE["photo"][:2])
    g = cv2.LUT(g, grade_table(low, high, PRINT_TONE))
    matrix = _cover(g.shape[1], g.shape[0], 0, 0, w, h, 0.5, 0.42, 1.0)
    out = printed(cv2.warpAffine(g, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE))
    k = math.tan(AXIS)
    edge = lambda y, x: y + k * (x - w / 2)  # noqa: E731
    tall = h > w
    wedge_y = h * (0.60 if tall else 0.50)
    thick = h * 0.05
    wedge = [(0, edge(wedge_y, 0)), (w, edge(wedge_y, w)), (w, h), (0, h)]
    band = [(0, edge(wedge_y - thick, 0)), (w, edge(wedge_y - thick, w)), (w, edge(wedge_y, w)), (0, edge(wedge_y, 0))]
    cv2.fillPoly(out, [np.int32(np.round(np.float32(wedge) * 16))], INK, lineType=cv2.LINE_AA, shift=4)
    cv2.fillPoly(out, [np.int32(np.round(np.float32(band) * 16))], RED, lineType=cv2.LINE_AA, shift=4)
    img = Image.fromarray(out)
    draw = ImageDraw.Draw(img)
    # the words where the wedge has room for them: below the band at their left end, clear of YouTube's title text on the tall one
    x0 = w * (0.05 if tall else 0.40)
    width = w * (0.86 if tall else 0.56)
    top = edge(wedge_y, x0) + h * 0.03
    bottom = h * (0.84 if tall else 0.95)
    room = max(40.0, bottom - top)
    lines, row = [], []
    for item in words:
        trial = " ".join(x[0] for x in row + [item])
        if row and measure(trial, room / 2 / 1.05) > width and len(lines) < 2:
            lines.append(row)
            row = []
        row.append(item)
    if row:
        lines.append(row)
    size_px = int(min(room / max(1, len(lines)) / 1.05, *(fitted(" ".join(x[0] for x in line), width, 300, 30) for line in lines))) if lines else 30
    y = top + (room - len(lines) * size_px * 1.05) / 2
    font = _font("osw", size_px, 700)
    space = font.getlength(" ")
    for line in lines:
        x = x0
        for word, marked in line:
            draw.text((x, y), word, font=font, fill=RED if marked else PAPER)
            x += font.getlength(word) + space
        y += size_px * 1.05
    return img


def still(case: dict, t: float, work: Path | None = None) -> np.ndarray:
    """One moment of the Short, drawn as the video would show it."""
    short = Montage(case, work)
    return short.frame(min(int(t * FPS), short.frames - 1), auditing=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--music")
    parser.add_argument("--still", type=float)
    args = parser.parse_args()
    try:
        with open(args.case, encoding="utf-8") as f:
            case = json.load(f)
        if args.still is not None:
            Image.fromarray(still(case, args.still)).save(args.out, quality=92)
            print(args.out)
            return 0
        result = render(case, args.out, Path(args.music) if args.music else None)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
