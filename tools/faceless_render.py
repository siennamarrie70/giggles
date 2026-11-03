"""
Agent 4's renderer for the faceless look: plays the scene design your Agent 4 prompt writes (tools/a4.py), as a vertical
1080x1920 Short at 30 frames a second.

Every scene is one picture or stock clip (or two, split screen), moved by its camera, coloured by the preset's grade and the
scene's own, with its effects and how it enters. On top: the scene's callout, animated, and captions in the lower third
lighting up word by word. Scenes, callouts and sound effects follow his voice as actually spoken (each scene starts on its
first word), not the prompt's estimated timings: he reads slower than the 3 words a second it assumes (your choice,
2026-11-03: his calm pace stays), so scenes run longer than its 1.0-3.5 s, about 3-4 s on average. Nothing fades at either end,
and the last scene is the first's picture with the camera going back, so the last frame flows into the first when the Short
loops; a clip plays backwards to its first frame for that.

Audio: the narration, each scene's sound effects (at -10, -16 or -24 dB, landing on the word they were placed on) and music
at -20 dB (settings music.volume scales it) that dips under the voice, with no fades; loudness-normalised (-14 LUFS).

The Reviewer reads what render() returns, the same as tools/doc_render.py's: the layout audit's findings and the shots in
order ("scene:S05" for a picture, "footage:S07" for a clip or stock photo).

Case (what Agent 4 hands over):
  {"manifest": <a4.v1>, "assets": {"S01": {"kind": "picture"|"clip"|"photo", "path": ..., "duration": ...}, "S05b": <the
   split screen's bottom half>}, "narration": {"wav", "seconds", "lines": [{"start", "end", "words": [[t, "word"]]}]},
   "drops": [{"kind": "callout", "line": <scene number from 0>}]}

Usage:
    python tools/faceless_render.py --case .tmp/case.json --out .tmp/out/faceless.mp4 [--music track.mp3]
"""

import argparse
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import time
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import a4
import infographics as ig
import sfx
import short_render
from common import ASSETS_DIR, TMP_DIR
from doc_render import AUDIT_EVERY as _AUDIT_AT_24, FROZEN, SAFE_BOTTOM, SAFE_RIGHT, SAFE_RIGHT_FROM, _ease, _ease_out, _overlap, \
    _paste, caption_chunks

W, H, FPS = 1080, 1920, 30
SAMPLE_RATE = 44_100
RENDER_TIMEOUT_S = 900
LEAD_CUT = 0.08          # a new scene starts this long before its first word
END_PAD = 0.1            # the video ends this long after the sound of the last word (it loops straight back)
AUDIT_EVERY = round(_AUDIT_AT_24 * FPS / 24)
CAPTION_Y = 1420         # captions' middle: in the lower third, clear of YouTube's title text below
CAPTION_X = 510          # ...and of its buttons on the right
CAPTION_WIDTH = 840
CAPTION_SIZE = 92
TOP_Y, CENTER_Y = 430, 900  # callouts' middles: the upper third, and the middle of the frame
CALLOUT_WIDTH = 880
MUSIC_DB = -20.0
FONT_FILES = {"Anton": "Anton-Regular.ttf", "Bebas Neue": "BebasNeue-Regular.ttf", "Cinzel": "Cinzel-Variable.ttf"}
BOLD = {"Cinzel": 800}   # a variable font's weight
STAMP_RED = (214, 40, 40)
PARALLAX_FAR = 7         # px the far parts slide over a scene; near parts slide 3x that (the prompt's "3x faster")
WIGGLE_SEED = 17
GRADES = {  # (shadow tint, highlight tint, how strongly) for the preset's base grade
    "teal_amber": ((6, 62, 74), (255, 196, 112), 0.20), "warm_sepia": ((62, 40, 18), (255, 222, 170), 0.20),
    "midnight_gold": ((10, 18, 58), (255, 200, 90), 0.22),
}
SCENE_TINTS = {"color_grade_warm_gold": ((60, 36, 8), (255, 206, 96), 0.24), "color_grade_cold_blue": ((6, 22, 66), (168, 206, 255), 0.26),
               "color_grade_red_alert": ((70, 8, 8), (255, 120, 96), 0.30)}


# --- moving a picture ------------------------------------------------------------------

def camera_at(name: str, p: float) -> tuple[float, float, float]:
    """The prompt's camera moves: (scale, x shift, y shift as shares of the frame), p from 0 to 1 over the scene."""
    if name == "ken_burns_zoom_in_slow":
        return 1 + 0.10 * p, 0.0, 0.0
    if name == "ken_burns_zoom_in_fast":
        return 1 + 0.25 * p, 0.0, 0.0
    if name == "ken_burns_zoom_out_slow":
        return 1.10 - 0.10 * p, 0.0, 0.0
    if name == "ken_burns_zoom_out_fast":
        return 1.25 - 0.25 * p, 0.0, 0.0
    if name == "slow_pan_left":
        return 1.15, 0.05 - 0.10 * p, 0.0
    if name == "slow_pan_right":
        return 1.15, -0.05 + 0.10 * p, 0.0
    if name == "slow_tilt_up":
        return 1.15, 0.0, 0.05 - 0.10 * p
    if name == "slow_tilt_down":
        return 1.15, 0.0, -0.05 + 0.10 * p
    if name == "micro_drift":
        return 1.03, -0.005 + 0.01 * p, 0.0
    return 1 + 0.06 * p, 0.0, 0.0  # 2.5d_parallax_depth: a slight push in


def _affine(sw: int, sh: int, tw: int, th: int, scale: float, dx: float, dy: float) -> np.ndarray:
    """What takes the source to a tw x th window: zoomed `scale` beyond just covering it, its centre moved by dx, dy."""
    zoom = max(tw / sw, th / sh) * scale
    room_x, room_y = max(0.0, (sw - tw / zoom) / 2), max(0.0, (sh - th / zoom) / 2)
    cx = sw / 2 + float(np.clip(dx * tw / zoom, -room_x, room_x))
    cy = sh / 2 + float(np.clip(dy * th / zoom, -room_y, room_y))
    return np.float32([[zoom, 0, tw / 2 - zoom * cx], [0, zoom, th / 2 - zoom * cy]])


class Still:
    """A picture moved by the scene's camera (with depth for 2.5d_parallax_depth: near parts slide 3x as far as far ones)."""

    def __init__(self, spec: dict, size: tuple[int, int], camera: str, length: float, punch: bool = False):
        import cv2

        self.size, self.camera, self.length, self.punch = size, camera, max(length, 0.2), punch
        picture = Image.open(spec["path"]).convert("RGB")
        self.src = np.asarray(picture)
        self.depth = None
        if camera == "2.5d_parallax_depth":
            import depth

            try:
                self.depth = cv2.resize(depth.depth_map(Path(spec["path"])), picture.size, interpolation=cv2.INTER_LINEAR)
            except Exception:  # no depth: the push alone
                self.depth = None
        tw, th = size
        self.gx, self.gy = (np.meshgrid(np.arange(tw, dtype=np.float32), np.arange(th, dtype=np.float32))
                            if self.depth is not None else (None, None))
        self.direction = 1 if (spec.get("index") or 0) % 2 else -1
        self.ran_out = None

    def frame(self, t: float, shake: tuple[int, int] = (0, 0)) -> np.ndarray:
        import cv2

        p = min(1.0, max(0.0, t / self.length))
        scale, dx, dy = camera_at(self.camera, p)
        if self.punch and t < 0.2:
            scale *= 1 + 0.08 * math.sin(math.pi * t / 0.2)
        sh, sw = self.src.shape[:2]
        tw, th = self.size
        matrix = _affine(sw, sh, tw, th, scale, dx, dy)
        matrix[0, 2] += shake[0]
        matrix[1, 2] += shake[1]
        if self.depth is None:
            return cv2.warpAffine(self.src, matrix, (tw, th), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        zoom = matrix[0, 0]
        u0 = (self.gx - matrix[0, 2]) / zoom
        v0 = (self.gy - matrix[1, 2]) / zoom
        d = cv2.remap(self.depth, u0, v0, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        far = PARALLAX_FAR * (p - 0.5) * 2
        slide = (far + 2 * far * d) * self.direction / zoom  # far parts move `far`, near parts 3x that
        return cv2.remap(self.src, u0 - slide, v0 - slide * 0.25, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def close(self):
        pass


class Moving:
    """A stock clip, cropped to fill, moved by the scene's camera. Decoded by ffmpeg as it plays; one shorter than its scene
    plays slower (down to 0.6x), then holds its last frame. `slow`: the prompt's slow_motion_50. `backwards`: plays to its
    first frame (the loop's last scene)."""

    def __init__(self, spec: dict, size: tuple[int, int], camera: str, length: float, slow: bool = False, backwards: bool = False,
                 punch: bool = False):
        self.spec, self.size, self.camera, self.length, self.punch = spec, size, camera, max(length, 0.2), punch
        self.slow, self.backwards = slow, backwards
        self.proc, self.got, self.last, self.ran_out = None, 0, None, None
        self.cw, self.ch = (size[0] + 1) // 2 * 2, (size[1] + 1) // 2 * 2

    def _start(self):
        duration = float(self.spec.get("duration") or 0)
        rate = 2.0 if self.slow else 1.0
        need = self.length / rate
        if duration and duration < need:  # short clip: slower still, down to 0.6x
            rate *= min(1 / 0.6, need / duration)
        frames = math.ceil(self.length * FPS) + 2
        part = f"setpts={rate:.4f}*PTS,fps={FPS},scale={self.cw}:{self.ch}:force_original_aspect_ratio=increase:flags=bicubic," \
               f"crop={self.cw}:{self.ch}"
        cmd = [short_render.ffmpeg_exe(), "-v", "error"]
        if self.backwards:  # just the seconds it needs, then turned round: its last frame is the clip's first
            cmd += ["-t", f"{self.length / rate:.3f}", "-i", str(self.spec["path"]), "-an", "-vf", part + ",reverse"]
        else:
            cmd += ["-i", str(self.spec["path"]), "-an", "-vf", part]
        cmd += ["-frames:v", str(frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def frame(self, t: float, shake: tuple[int, int] = (0, 0)) -> np.ndarray:
        import cv2

        if self.proc is None:
            self._start()
        want = min(int(t * FPS), math.ceil(self.length * FPS))
        size = self.cw * self.ch * 3
        while self.got <= want:
            raw = self.proc.stdout.read(size)
            if len(raw) < size:
                if self.ran_out is None and self.last is not None:
                    self.ran_out = t
                break
            self.last = np.frombuffer(raw, dtype=np.uint8).reshape(self.ch, self.cw, 3)
            self.got += 1
        tw, th = self.size
        if self.last is None:
            return np.zeros((th, tw, 3), dtype=np.uint8)
        p = min(1.0, max(0.0, t / self.length))
        scale, dx, dy = camera_at(self.camera, p)
        if self.punch and t < 0.2:
            scale *= 1 + 0.08 * math.sin(math.pi * t / 0.2)
        matrix = _affine(self.cw, self.ch, tw, th, scale, dx, dy)
        matrix[0, 2] += shake[0]
        matrix[1, 2] += shake[1]
        return cv2.warpAffine(self.last, matrix, (tw, th), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def close(self):
        if self.proc:
            self.proc.kill()
            try:
                self.proc.stdout.close()
                self.proc.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
            self.proc = None


def _visual(asset: dict, size: tuple[int, int], camera: str, length: float, index: int, slow: bool = False,
            backwards: bool = False, punch: bool = False):
    if asset["kind"] == "clip":
        return Moving(asset, size, camera, length, slow, backwards, punch)
    return Still({**asset, "index": index}, size, camera, length, punch)


# --- colour and effects ------------------------------------------------------------------

def _tint_lut(shadow: tuple, high: tuple, amount: float) -> np.ndarray:
    """A soft S curve with its shadows and highlights tinted (RGB order)."""
    x = np.arange(256, dtype=np.float32) / 255
    curve = np.clip(x + 0.16 * np.sin(2 * np.pi * x) * (1 - x), 0, 1)
    lut = np.zeros((256, 1, 3), dtype=np.uint8)
    for c in range(3):
        lo, hi = shadow[c] / 255, high[c] / 255
        out = curve * (1 - amount * (1 - curve)) + amount * (1 - curve) * lo
        out = out * (1 - amount * curve) + amount * curve * hi
        lut[:, 0, c] = np.clip(out * 255, 0, 255).astype(np.uint8)
    return lut


@lru_cache(maxsize=16)
def _grade(base: str, scene: str) -> tuple:
    """(colour matrix or None, LUT) for the preset's base grade and the scene's own."""
    shadow, high, amount = GRADES.get(base, GRADES["warm_sepia"])
    lut = _tint_lut(shadow, high, amount)
    if scene in SCENE_TINTS:
        import cv2

        lut = cv2.LUT(lut, _tint_lut(*SCENE_TINTS[scene]))
    grey = np.float32([0.299, 0.587, 0.114])
    if scene == "color_grade_desaturate":
        keep = 0.4  # saturation -60%
        return np.float32([grey * (1 - keep) + np.eye(3, dtype=np.float32)[i] * keep for i in range(3)]), lut
    if scene == "color_grade_bw_high_contrast":
        x = np.arange(256, dtype=np.float32) / 255
        hard = np.clip((x - 0.5) * 1.45 + 0.5, 0, 1)
        return np.float32([grey, grey, grey]), np.repeat((hard * 255).astype(np.uint8)[:, None, None], 3, axis=2)
    return None, lut


class Effects:
    """What the prompt's film_grain, vignette_dark and light_leak put over a scene (made once)."""

    def __init__(self):
        self._grain, self._vignette, self._leak = None, None, None

    def grain(self, frame: np.ndarray, n: int) -> np.ndarray:
        import cv2

        if self._grain is None:
            rng = np.random.default_rng(5)
            self._grain = []
            for _ in range(6):
                g = cv2.resize(rng.normal(0, 8.0, (H // 2, W // 2)).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
                g3 = cv2.merge([g] * 3)
                self._grain.append((np.clip(g3, 0, 255).astype(np.uint8), np.clip(-g3, 0, 255).astype(np.uint8)))
        plus, minus = self._grain[(n // 2) % 6]
        return cv2.subtract(cv2.add(frame, plus), minus)

    def vignette(self, frame: np.ndarray) -> np.ndarray:
        import cv2

        if self._vignette is None:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            r = np.sqrt(((xx - W / 2) / (W * 0.58)) ** 2 + ((yy - H / 2) / (H * 0.56)) ** 2)
            dark = np.clip(1 - 0.9 * np.clip(r - 0.42, 0, None) ** 1.5, 0.12, 1)
            self._vignette = cv2.merge([(dark * 255).astype(np.uint8)] * 3)
        return cv2.multiply(frame, self._vignette, scale=1 / 255)

    def leak(self, frame: np.ndarray, p: float) -> np.ndarray:
        import cv2

        if self._leak is None:
            yy, xx = np.mgrid[0:H // 4, 0:W // 2].astype(np.float32)
            glow = np.exp(-(((xx - W / 2) / (W * 0.30)) ** 2 + ((yy - H / 8) / (H * 0.22)) ** 2))
            self._leak = np.dstack([glow * 255, glow * 150, glow * 60]).astype(np.uint8)
        shift = int((p - 0.5) * W * 0.25)
        glow = cv2.resize(np.roll(self._leak, shift // 2, axis=1), (W, H), interpolation=cv2.INTER_LINEAR)
        return cv2.add(frame, (glow * (0.45 + 0.2 * math.sin(p * math.pi))).astype(np.uint8))


def glitch(frame: np.ndarray, amount: float, n: int) -> np.ndarray:
    """An RGB split with a few torn slices (the prompt's rgb_glitch and glitch_cut)."""
    rng = random.Random(WIGGLE_SEED + n)
    shift = max(1, int(26 * amount))
    out = frame.copy()
    out[:, :, 0] = np.roll(frame[:, :, 0], shift, axis=1)
    out[:, :, 2] = np.roll(frame[:, :, 2], -shift, axis=1)
    for _ in range(7):
        y, h = rng.randrange(0, H - 60), rng.randrange(14, 90)
        out[y:y + h] = np.roll(out[y:y + h], rng.randrange(-int(70 * amount) - 1, int(70 * amount) + 2), axis=1)
    return out


def enter(move: str, new: np.ndarray, old: np.ndarray | None, t: float, n: int) -> np.ndarray:
    """A scene coming in, t seconds after it starts (old: the scene before's last frame). Past its time it's just the scene."""
    import cv2

    if old is None or move == "hard_cut":
        return new
    if move == "flash_white":
        return new if t >= 0.1 else np.clip(new.astype(np.int16) + int(255 * (1 - t / 0.1)), 0, 255).astype(np.uint8)
    if move == "crossfade_fast":
        return new if t >= 0.2 else cv2.addWeighted(new, t / 0.2, old, 1 - t / 0.2, 0)
    if move == "glitch_cut":
        return new if t >= 0.15 else glitch(old if t < 0.05 else new, 1 - t / 0.15, n)
    if move == "whip_pan":
        if t >= 0.25:
            return new
        p = _ease(t / 0.25)
        x = int(W * p)
        out = np.empty_like(new)
        out[:, :W - x] = old[:, x:]
        out[:, W - x:] = new[:, :x]
        k = max(3, int(120 * math.sin(math.pi * p))) | 1
        return cv2.blur(out, (k, 1))
    if move == "zoom_through":
        if t >= 0.3:
            return new
        p = t / 0.3
        source, z = (old, 1 + 0.5 * (p / 0.5) ** 2) if p < 0.5 else (new, 1 + 0.5 * ((1 - p) / 0.5) ** 2)
        blur = np.zeros_like(source, dtype=np.float32)
        for k in range(4):
            zk = z * (1 + 0.025 * k)
            matrix = np.float32([[zk, 0, W / 2 * (1 - zk)], [0, zk, H / 2 * (1 - zk)]])
            blur += cv2.warpAffine(source, matrix, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return (blur / 4).astype(np.uint8)
    return new


# --- words on screen ------------------------------------------------------------------

@lru_cache(maxsize=64)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = ASSETS_DIR / "fonts" / FONT_FILES.get(name, "Anton-Regular.ttf")
    if not path.exists():
        return ig.font(ig.HEAD_FONT, size)
    font = ImageFont.truetype(str(path), max(8, int(size)))
    if name in BOLD:
        try:
            font.set_variation_by_axes([BOLD[name]])
        except (OSError, AttributeError):
            pass
    return font


def _hex(value: str, default: tuple = (255, 255, 255)) -> tuple:
    found = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value or ""))
    return tuple(int(found[1][i:i + 2], 16) for i in (0, 2, 4)) if found else default


def _fitted(probe: ImageDraw.ImageDraw, text: str, name: str, width: int, size: int, smallest: int) -> ImageFont.FreeTypeFont:
    while size > smallest and probe.textlength(text, font=_font(name, size)) > width:
        size = int(size * 0.94)
    return _font(name, size)


def _text_box(text: str, font, fill: tuple, stroke: int, pad: int = 24) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    img = Image.new("RGBA", (max(1, right - left + 2 * pad), max(1, bottom - top + 2 * pad)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - left, pad - top), text, font=font, fill=(*fill, 255), stroke_width=stroke,
                             stroke_fill=(0, 0, 0, 255))
    return img


def _scaled(img: Image.Image, s: float) -> Image.Image:
    if abs(s - 1) < 0.01:
        return img
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.BILINEAR)


def callout_layer(spec: dict, style: dict, t: float, length: float) -> tuple[Image.Image, tuple[int, int]]:
    """The prompt's five callout animations: t seconds into a scene of `length` seconds."""
    text, animation = spec["text"], spec["animation"]
    y = CENTER_Y if spec["position"] == "center" else TOP_Y
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    font = _fitted(probe, text, style["font"], CALLOUT_WIDTH, 170 if len(text) < 11 else 150, 64)
    accent, plain = _hex(style.get("accent_color_hex")), _hex(style.get("text_color_hex"))
    stroke = max(5, font.size // 13)
    dx, dy, scale, shown = 0, 0, 1.0, text
    if animation == "count_up":
        head, _, rest = text.partition(" ")
        p = _ease_out(t / max(min(length * 0.7, 1.4), 0.3))
        shown = f"{ig.count_up(head, p)} {rest}".strip() if p < 1 else text
        img = _text_box(shown, font, accent, stroke)
    elif animation == "typewriter":
        letters = math.ceil(len(text) * min(1.0, t / max(min(length * 0.6, 1.2), 0.2)))
        whole = _text_box(text, font, plain, stroke)  # (the whole line's box: letters appear without it shifting)
        img = Image.new("RGBA", whole.size, (0, 0, 0, 0))
        if letters:
            part = _text_box(text[:letters], font, plain, stroke)
            img.alpha_composite(part, (0, 0))
    elif animation == "stamp":
        scale = 1 + 0.7 * (1 - _ease_out(t / 0.12))
        base = _text_box(text, font, STAMP_RED, 0, pad=34)
        d = ImageDraw.Draw(base)
        d.rounded_rectangle((8, 8, base.width - 9, base.height - 9), radius=20, outline=(*STAMP_RED, 255), width=max(9, font.size // 12))
        img = base.rotate(-7, resample=Image.BICUBIC, expand=True)
        if t < 0.3:
            dx, dy = int(8 * (1 - t / 0.3) * math.sin(t * 90)), int(8 * (1 - t / 0.3) * math.cos(t * 80))
    elif animation == "slam_impact":
        scale = 1 + 2.0 * (1 - _ease_out(t / 0.16))
        img = _text_box(text, font, accent, stroke)
        if t < 0.35:
            dx, dy = int(9 * (1 - t / 0.35) * math.sin(t * 95)), int(9 * (1 - t / 0.35) * math.cos(t * 85))
    else:  # pop_in: 0 -> 110% -> 100% in 0.2 s
        scale = max(0.02, 1.1 * _ease_out(t / 0.13)) if t < 0.13 else 1.1 - 0.1 * _ease((t - 0.13) / 0.07)
        img = _text_box(text, font, plain, stroke)
    img = _scaled(img, scale)
    return img, (W // 2 - img.width // 2 + dx, y - img.height // 2 + dy)


def caption_layer(chunk: list, t: float, start: float, style: dict) -> tuple[Image.Image, tuple[int, int]]:
    """A caption chunk in the preset's font; the word being said in its accent colour; landing a little big."""
    words = [short_render.clean_text(w).upper() for _, w in chunk]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    line = " ".join(words)
    font = _fitted(probe, line, style["font"], CAPTION_WIDTH, CAPTION_SIZE, 52)
    space = probe.textlength(" ", font=font)
    widths = [probe.textlength(w, font=font) for w in words]
    total = sum(widths) + space * (len(words) - 1)
    stroke = max(5, font.size // 12)
    height = int(font.size * 1.5) + 2 * stroke
    img = Image.new("RGBA", (int(total) + 2 * stroke + 8, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent, plain = _hex(style.get("accent_color_hex")), _hex(style.get("text_color_hex"))
    now = max((k for k, (at, _) in enumerate(chunk) if at <= t), default=0)
    x = stroke + 4
    for k, (word, width) in enumerate(zip(words, widths)):
        d.text((x, stroke + 2), word, font=font, fill=(*(accent if k == now else plain), 255), stroke_width=stroke,
               stroke_fill=(0, 0, 0, 255))
        x += width + space
    age = t - start
    if age < 0.1:
        img = _scaled(img, 1 + 0.06 * (1 - age / 0.1))
    return img, (CAPTION_X - img.width // 2, CAPTION_Y - img.height // 2)


# --- the video ------------------------------------------------------------------

def timed(manifest: dict, narration: dict) -> list[dict]:
    """Each scene's time by his real voice: it starts on its first word (LEAD_CUT before it), and its words' times go
    with it. [{"start", "end", "words": [[t, word]], "scene", "index"}]"""
    words = [w for line in narration["lines"] for w in line["words"]]
    counts = a4.scene_words(manifest)
    if sum(counts) != len(words):
        raise ValueError(f"the scenes cover {sum(counts)} words, the voice said {len(words)}")
    out, at = [], 0
    last = max([line["end"] for line in narration["lines"]] + [narration.get("voice_end") or 0.0])
    total = round(last + END_PAD, 2)
    for k, (scene, count) in enumerate(zip(manifest["scenes"], counts)):
        mine = words[at:at + count]
        out.append({"start": 0.0 if not k else max(0.0, mine[0][0] - LEAD_CUT), "end": total, "words": mine, "scene": scene, "index": k})
        at += count
    for a, b in zip(out, out[1:]):
        a["end"] = b["start"]
    return out


def _line_of(narration: dict, t: float) -> int:
    lines = narration["lines"]
    return max([k for k, line in enumerate(lines) if line["start"] - LEAD_CUT - 0.01 <= t] or [0])


class Short:
    """Everything needed to draw the Short, frame by frame, in order (clips are decoded as they play)."""

    def __init__(self, case: dict):
        self.manifest, self.assets, self.narration = case["manifest"], case["assets"], case["narration"]
        self.style = self.manifest["style_bible"]
        self.scenes = timed(self.manifest, self.narration)
        self.total = self.scenes[-1]["end"]
        self.drops = {(d.get("kind"), d.get("line")) for d in case.get("drops") or []}
        self.layout, self.live, self.effects = [], {}, Effects()
        self.previous, self.showing = None, None
        self.captions = []
        for k, line in enumerate(self.narration["lines"]):
            for chunk in caption_chunks(line["words"], 3, 20):
                self.captions.append([chunk[0][0], None, chunk, k])
        for a, b in zip(self.captions, self.captions[1:]):
            a[1] = b[0]
        if self.captions:
            self.captions[-1][1] = self.total
            self.captions[0][0] = 0.0

    def _asset(self, name: str) -> dict:
        found = self.assets.get(name)
        if not found:
            raise RuntimeError(f"scene {name} has no picture or clip")
        return found

    def _made(self, k: int) -> list:
        """The scene's visuals, made when it comes on screen; the ones before it let go."""
        if k not in self.live:
            info = self.scenes[k]
            scene = info["scene"]
            length = info["end"] - info["start"] + 0.04
            name = scene["scene_id"]
            backwards = scene.get("reuse_asset_from") == "S01"
            asset = self._asset("S01" if backwards else name)
            fx = scene["fx"]
            punch = "zoom_punch" in fx
            slow = "slow_motion_50" in fx
            if scene["layout"] == "split_screen_comparison" and scene.get("secondary_visual"):
                half = (W, H // 2)
                self.live[k] = [_visual(asset, half, scene["camera"], length, k, slow, False, punch),
                                _visual(self._asset(name + "b"), half, "ken_burns_zoom_in_slow", length, k + 50, False, False, punch)]
            else:
                self.live[k] = [_visual(asset, (W, H), scene["camera"], length, k, slow, backwards, punch)]
            for old in [i for i in self.live if i < k]:
                for visual in self.live[old]:
                    visual.close()
                del self.live[old]
        return self.live[k]

    def frame(self, n: int) -> np.ndarray:
        import cv2

        t = n / FPS
        k = next((i for i, s in enumerate(self.scenes) if s["start"] <= t < s["end"]), len(self.scenes) - 1)
        info = self.scenes[k]
        scene = info["scene"]
        local = t - info["start"]
        length = max(info["end"] - info["start"], 0.2)
        fx = scene["fx"]
        shake = (0, 0)
        if "screen_shake_impact" in fx and local < 0.25:  # 12 px at the start, dying away
            left = 1 - local / 0.25
            shake = (int(12 * left * math.sin(local * FPS * 2.4)), int(12 * left * math.sin(local * FPS * 3.1)))
        visuals = self._made(k)
        if len(visuals) == 2:
            top = visuals[0].frame(local, shake)
            bottom = visuals[1].frame(local, shake)
            frame = np.concatenate([top, bottom], axis=0)
            frame[H // 2 - 3:H // 2 + 3] = _hex(self.style.get("accent_color_hex"))
        else:
            frame = visuals[0].frame(local, shake)
        frame = np.ascontiguousarray(frame)
        matrix, lut = _grade(self.style.get("base_color_grade"), scene.get("color_grade") or "base")
        if matrix is not None:
            frame = cv2.transform(frame, matrix)
        frame = cv2.LUT(frame, lut)
        if "vignette_dark" in fx:
            frame = self.effects.vignette(frame)
        if "light_leak" in fx:
            frame = self.effects.leak(frame, local / length)
        if "film_grain" in fx:
            frame = self.effects.grain(frame, n)
        if "rgb_glitch" in fx and local < 0.2:
            frame = glitch(frame, 1 - local / 0.2, n)
        if k != self.showing:  # the scene before's last frame is what this one comes in over
            self.previous, self.showing = getattr(self, "_last_frame", None), k
        frame = enter(scene.get("transition_in") or "hard_cut", frame, self.previous, local, n)
        self._last_frame = frame.copy()
        if not frame.flags.writeable:
            frame = frame.copy()
        texts = []
        callout = scene.get("on_screen_text")
        if callout and ("callout", k) not in self.drops:
            layer, xy = callout_layer(callout, self.style, local, length)
            frame = _paste(frame, layer, xy)
            texts.append(("callout", layer, xy, k))
        for start, end, chunk, line in self.captions:
            if start <= t < end:
                layer, xy = caption_layer(chunk, t, start, self.style)
                frame = _paste(frame, layer, xy)
                texts.append(("caption", layer, xy, line))
                break
        if n % AUDIT_EVERY == 0:
            self._audit(t, texts, k)
        return frame

    def _audit(self, t: float, texts: list, k: int) -> None:
        """Words on top of each other or under YouTube's buttons and title text, and a clip that ran out and has held its
        last frame for over FROZEN seconds (scene k is on screen). In the same form as tools/doc_render.py's, for the Reviewer."""
        boxes = []
        for kind, layer, (x, y), line in texts:
            box = layer.getchannel("A").point(lambda a: 255 if a > 180 else 0).getbbox()
            if box:
                boxes.append((kind, (x + box[0], y + box[1], x + box[2], y + box[3]), line))
        found = []
        for i, (a, ba, la) in enumerate(boxes):
            for b, bb, lb in boxes[i + 1:]:
                if _overlap(ba, bb) > 0.04:
                    found.append(("overlap", f"{a}+{b}", la if a == "callout" else lb))
            x0, y0, x1, y1 = ba
            if (x1 > SAFE_RIGHT and y1 > SAFE_RIGHT_FROM) or y1 > SAFE_BOTTOM:
                found.append(("unsafe", a, la))
        for visual in self.live.get(k) or []:
            held = getattr(visual, "ran_out", None)
            if held is not None and t - self.scenes[k]["start"] - held > FROZEN:
                found.append(("frozen", f"footage:{self.scenes[k]['scene']['scene_id']}", _line_of(self.narration, self.scenes[k]["start"])))
        for kind, what, line in found:
            last = next((x for x in reversed(self.layout) if (x["kind"], x["what"], x["line"]) == (kind, what, line)), None)
            if last and t - last["end"] <= AUDIT_EVERY / FPS + 0.01:
                last["end"] = round(t, 2)
            else:
                self.layout.append({"kind": kind, "what": what, "line": line, "start": round(t, 2), "end": round(t, 2)})

    def shots(self) -> list[dict]:
        out = []
        for info in self.scenes:
            scene = info["scene"]
            name = "S01" if scene.get("reuse_asset_from") == "S01" else scene["scene_id"]
            kind = self.assets.get(name, {}).get("kind", "picture")
            out.append({"start": round(info["start"], 2), "end": round(info["end"], 2), "kind": kind,
                        "name": f"{'scene' if kind == 'picture' else 'footage'}:{name}",
                        "line": _line_of(self.narration, info["start"])})
        return out

    def close(self):
        for visuals in self.live.values():
            for visual in visuals:
                visual.close()


# --- audio and encoding ---------------------------------------------------------------------

def _effects_wav(short: Short, dest: Path) -> list[dict]:
    """The scenes' sound effects as one 44.1 kHz mono track, each landing on the word the design placed it on (its offset is
    in the prompt's 3 words a second, so offset x 3 is how many words in). Returns what was placed."""
    track = np.zeros(int((short.total + 2) * SAMPLE_RATE), dtype=np.float32)
    placed = []
    for info in short.scenes:
        for sound in info["scene"].get("sfx") or []:
            tag = sound.get("tag")
            samples = sfx.effect(tag, SAMPLE_RATE) if tag in a4.SFX_TAGS else None
            if samples is None or not len(samples):
                continue
            words = info["words"]
            nth = round(float(sound.get("offset_sec") or 0) * a4_words_per_second)
            at = words[nth][0] if float(sound.get("offset_sec") or 0) and nth < len(words) else info["start"]
            gain = 10 ** (a4.VOLUMES.get(sound.get("volume"), -16.0) / 20)
            i = max(0, int(at * SAMPLE_RATE))
            piece = samples[:max(0, len(track) - i)] * gain
            track[i:i + len(piece)] += piece
            placed.append({"tag": tag, "at": round(at, 2)})
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())
    return placed


a4_words_per_second = 3  # the prompt: offset_sec = (position of the word - 1) / 3


def render(case: dict, out_path: Path | str, music: Path | None = None, volume: float = 1.0, cover_path: Path | str | None = None,
           progress=print) -> dict:
    """Draws and encodes the Short; returns its length, frame count and how long it took, what the layout audit found and
    the shots in order (for the Reviewer), in the same form as tools/doc_render.py's render()."""
    started = time.monotonic()
    short = Short(case)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f"{out.stem}.part{out.suffix}")  # (renamed when whole: see doc_render.render)
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="short_", dir=TMP_DIR / "work"))
    effects = work / "effects.wav"
    placed = _effects_wav(short, effects)
    total = short.total
    voice = case["narration"]["wav"]
    cmd = [short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
           "-i", str(voice), "-i", str(effects)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    gain = 10 ** (MUSIC_DB / 20) * volume
    audio = (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={total:.2f}[d];"
             f"[d]asplit=2[d1][d2];"
             f"[2:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS[fx];"
             f"[3:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,volume={gain:.3f}[m];"
             f"[m][d1]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=400[md];"
             f"[md][d2][fx]amix=inputs=3:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", audio, "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", "-t", f"{total:.2f}",
            str(part)]
    frames = math.ceil(total * FPS)
    errors = work / "ffmpeg.log"
    cover = None
    try:
        with open(errors, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
            try:
                for n in range(frames):
                    frame = short.frame(n)
                    if cover_path and n == int(1.5 * FPS):
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
        short.close()
    part.replace(out)
    if cover_path and cover is not None:
        Image.fromarray(cover).resize((540, 960), Image.LANCZOS).save(cover_path, quality=88)
    for item in work.iterdir():
        item.unlink()
    work.rmdir()
    return {"seconds": total, "frames": frames, "render_seconds": round(time.monotonic() - started, 1), "layout": short.layout,
            "shots": short.shots(), "sounds": placed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--music")
    args = parser.parse_args()
    try:
        with open(args.case, encoding="utf-8") as f:
            case = json.load(f)
        result = render(case, args.out, Path(args.music) if args.music else None)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
