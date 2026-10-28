"""
Agent 4's renderer for the documentary cases: the narrator's voice over real footage, real photos
moving like a camera passing them, satellite maps, charts and numbers, with captions that light
up word by word. A vertical 1080x1920 Short.

Shots (each line has one or two, so the picture changes every few seconds):
  footage  a stock or archive clip, cropped to fill the frame, slowly pushing in
  photo    a real photo given depth (tools/depth.py): near parts slide more than far ones as the
           camera drifts in. Tall photos fill the frame; wide ones sit full-width over a blurred,
           darkened copy of themselves (sharp, and nothing important is cropped away)
  scene    a drawing in the Professor's art (the drawn look, tools/draw.py): a square seen through the
           9:16 frame as a window that travels across it, with depth like a photo
  framed   a real photo inside the drawn world: a print with a paper border, slightly turned, over
           the line's drawing (darker and softened), drifting gently
  map      the countries on NASA's Blue Marble, lit up, the view easing in (drawn map if missing)
  chart    a chart (tools/infographics.py) on a dark panel
  quote    the source's own words, line by line, with who said them
In the drawn look a chart, quote or map sits on the line's drawing, softened and darkened (its spec's
"backdrop"), and maps are drawn (the navy-and-gold map: no satellite photo in a painted world).
On top: the Professor, the host (tools/host.py), floating in the lower-left corner and talking
with the narration; a number that counts up and lands in gold (with an impact) the moment it's
said; a name for a person's photo (top left); the case title over the opening; captions of 2-4
words in the middle, above the Professor, with the word being said lit up. Charts, wide photos and
maps keep what matters in the upper part of the frame, clear of him. Every shot gets the same look
(a gentle grade in the case type's colour, a vignette, fine grain), so clips from different sources
feel like one film; the Professor is drawn on top of it, crisp. The video ends half a second after
the last word: no end card, so it loops cleanly back to the opening line.

Audio: the narration, a whoosh at each new beat, an impact under each number, a riser into the
reveal, and music in the script's mood that dips under the voice; loudness-normalised (-14 LUFS).

Case JSON (what Agent 4 hands over):
  {"category": "business", "case_no": 12, "case_title": "The fall of Nokia",
   "narration": {"wav": "path", "seconds": 57.2, "lines": [{"start", "end", "words": [[t, "word"]]}]},
   "lines": [{"text": "...", "beat": "hook", "visuals": [{see SHOT_KINDS}, {...}]}],
   "credits": [...]}

Usage:
    python tools/doc_render.py --case .tmp/case.json --out .tmp/out/doc.mp4 [--music none]
"""

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import host
import infographics as ig
import sfx
import short_render
from common import ASSETS_DIR, TMP_DIR, load_config

W, H, FPS = 1080, 1920, 24
SAMPLE_RATE = 24_000
RENDER_TIMEOUT_S = 900
LEAD_CUT = 0.12          # a new shot starts this long before its first word
END_PAD = 0.5            # the video ends this long after the last word
PUSH = 0.08              # footage and photos drift in this much over a shot
PARALLAX = 26            # px: how far near things slide relative to far ones over a shot
CAPTION_Y = 1330         # captions' middle without the host (clear of the Shorts buttons and text below)
CAPTION_GAP = 85         # with the host: captions' middle sits this far above the room he moves in
CAPTION_SIZE = 76
NUMBER_Y = 620           # where a number lands
NAME_Y = 236             # a person's name, top left (under the Shorts header)
FOCUS = 0.40             # maps put their countries this far down the frame (clear of the host)
WIDE = 100               # degrees of longitude: countries spread wider than this are framed by their closest group
AUDIT_EVERY = 6          # frames: how often the layout check looks at where the words are (4 times a second)
SAFE_RIGHT, SAFE_RIGHT_FROM = 960, 1100  # YouTube's like/comment/share column: right of x 960, below y 1100
SAFE_BOTTOM = 1580       # YouTube's channel name and title text start about here
TITLE_FOR = 3.0          # seconds the case title stays over the opening
FROZEN = 0.75            # seconds a clip may hold its last frame (after running out) before the audit notes it
BLUE_MARBLE = ASSETS_DIR / "maps" / "bluemarble.jpg"
SHOT_KINDS = ("footage", "photo", "scene", "framed", "map", "chart", "quote")
KICKERS = {"business": "Business", "economy": "Economy", "trending": "In the news", "history": "History",
           "mythology": "Mythology", "dark_history": "Dark history", "mysteries": "Mysteries", "technology": "Technology",
           "psychology": "Psychology", "people": "Rise and fall", "science": "Science", "crime": "Crime"}
NUMBERISH = re.compile(r"\d")
TINTS = {  # (shadow tint, highlight tint) mixed in gently: one look per case type
    "business": ((14, 34, 52), (255, 236, 214)), "economy": ((12, 40, 34), (240, 250, 228)),
    "trending": ((40, 18, 22), (255, 238, 226)), "history": ((40, 28, 12), (255, 232, 196)),
    "mythology": ((30, 16, 44), (255, 230, 200)), "dark_history": ((40, 16, 12), (255, 226, 190)),
    "mysteries": ((10, 32, 40), (226, 240, 255)), "technology": ((8, 24, 48), (220, 240, 255)),
    "psychology": ((34, 18, 46), (250, 236, 255)), "people": ((36, 26, 14), (255, 236, 208)),
    "science": ((6, 14, 40), (225, 235, 255)), "crime": ((16, 20, 28), (236, 240, 246)),
}


def _ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def _ease_out(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


# --- the look ------------------------------------------------------------------

class Look:
    """The grade (a contrast curve and a tint), the vignette and the grain every shot gets."""

    def __init__(self, category: str):
        import cv2

        shadow, high = TINTS.get(category, TINTS["business"])
        x = np.arange(256, dtype=np.float32) / 255
        curve = x + 0.18 * np.sin(2 * np.pi * x) * (1 - x) * 0.9  # a soft S: richer contrast, gentle ends
        curve = np.clip(curve, 0, 1)
        lut = np.zeros((256, 1, 3), dtype=np.uint8)
        for c in range(3):  # RGB order
            lo, hi = shadow[c] / 255, high[c] / 255
            graded = curve * (1 - 0.10 * (1 - curve)) + 0.10 * (1 - curve) * lo  # tint the shadows
            graded = graded * (1 - 0.06 * curve) + 0.06 * curve * hi              # and the highlights
            lut[:, 0, c] = np.clip(graded * 255, 0, 255).astype(np.uint8)
        self.lut = lut
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.6)) ** 2)
        vig = np.clip(1 - 0.42 * np.clip(r - 0.35, 0, None) ** 1.6, 0.45, 1)
        self.vignette = cv2.merge([(vig * 255).astype(np.uint8)] * 3)
        rng = np.random.default_rng(5)
        self.grain = []
        for _ in range(6):  # a few frames of fine grain, cycled
            g = cv2.resize(rng.normal(0, 5.5, (H // 2, W // 2)).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
            g3 = cv2.merge([g] * 3)
            self.grain.append((np.clip(g3, 0, 255).astype(np.uint8), np.clip(-g3, 0, 255).astype(np.uint8)))

    def apply(self, frame: np.ndarray, n: int) -> np.ndarray:
        import cv2

        out = cv2.LUT(frame, self.lut)
        out = cv2.multiply(out, self.vignette, scale=1 / 255)
        plus, minus = self.grain[(n // 2) % len(self.grain)]
        return cv2.subtract(cv2.add(out, plus), minus)


# --- shots -------------------------------------------------------------------------

class Footage:
    """A clip, cropped to fill the frame, pushing in slowly. Decoded by ffmpeg as the shot plays; a clip
    shorter than its shot plays slower (down to 0.6x), then holds its last frame. Archive film ("framed":
    old 4:3 film is too small to crop) is shown whole, full width and high in the frame, over a blurred,
    darkened copy of itself."""

    def __init__(self, spec: dict, length: float):
        self.path, self.length = spec["path"], length
        self.offset = float(spec.get("offset") or 0)
        self.duration = float(spec.get("duration") or 0)
        self.proc, self.got, self.last = None, 0, None
        self.ran_out = None  # when (seconds into the shot) the clip ran out and its last frame began to hold
        self.framed = bool(spec.get("framed"))
        if self.framed:
            import cv2

            video = cv2.VideoCapture(str(self.path))
            vw, vh = video.get(cv2.CAP_PROP_FRAME_WIDTH) or 4, video.get(cv2.CAP_PROP_FRAME_HEIGHT) or 3
            video.release()
            self.framed = vw / vh >= 1.15  # only wide film is framed; a tall clip fills the frame like any other
        if self.framed:
            self.fw, self.fh = W, round(W * vh / vw) // 2 * 2
            self.y = max(240, (H - self.fh) // 2 - 330)
            self.big = (round(self.fw * (1 + PUSH)) // 2 * 2, round(self.fh * (1 + PUSH)) // 2 * 2)
        else:
            self.big = (round(W * (1 + PUSH)) // 2 * 2, round(H * (1 + PUSH)) // 2 * 2)

    def _start(self):
        frames = math.ceil(self.length * FPS) + 2
        available = max(0.5, self.duration - self.offset) if self.duration else self.length
        slow = min(1 / 0.6, max(1.0, self.length / available))
        bw, bh = self.big
        vf = (f"setpts={slow:.4f}*PTS,fps={FPS},scale={bw}:{bh}:force_original_aspect_ratio=increase:flags=bicubic,"
              f"crop={bw}:{bh}")
        cmd = [short_render.ffmpeg_exe(), "-v", "error", "-ss", f"{self.offset:.2f}", "-i", str(self.path), "-an",
               "-vf", vf, "-frames:v", str(frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def frame(self, t: float) -> np.ndarray:
        import cv2

        if self.proc is None:
            self._start()
        want = min(int(t * FPS), math.ceil(self.length * FPS))
        bw, bh = self.big
        size = bw * bh * 3
        while self.got <= want:
            raw = self.proc.stdout.read(size)
            if len(raw) < size:  # the clip ran out: hold the last frame
                if self.ran_out is None and self.last is not None:
                    self.ran_out = t
                break
            self.last = np.frombuffer(raw, dtype=np.uint8).reshape(bh, bw, 3)
            self.got += 1
        if self.last is None:
            return np.zeros((H, W, 3), dtype=np.uint8)
        z = 1 + PUSH * _ease(t / max(self.length, 0.5) * 0.9 + 0.05)
        cw, ch = bw / z, bh / z
        x0, y0 = (bw - cw) / 2, (bh - ch) / 2
        crop = self.last[int(y0):int(y0 + ch), int(x0):int(x0 + cw)]
        if not self.framed:
            return cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)
        back = cv2.GaussianBlur(cv2.resize(crop, (W // 8, H // 8), interpolation=cv2.INTER_AREA), (0, 0), 3)
        out = (cv2.resize(back, (W, H), interpolation=cv2.INTER_LINEAR) * 0.38).astype(np.uint8)
        out[self.y:self.y + self.fh] = cv2.resize(crop, (self.fw, self.fh), interpolation=cv2.INTER_CUBIC)
        return out

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc = None


class Photo:
    """A real photo with depth: the camera drifts in and sideways, near parts sliding more than far ones."""

    PAN = 0.12  # how much of the spare width the view travels across over a shot

    def __init__(self, spec: dict, length: float, index: int, fill: bool = False):
        import cv2

        import depth

        self.length = length
        img = Image.open(spec["path"]).convert("RGB")
        try:
            dep = depth.depth_map(Path(spec["path"]))
        except Exception:
            dep = np.full((img.height, img.width), 0.5, dtype=np.float32)  # no depth: a plain slow push
        iw, ih = img.size
        self.direction = -1 if index % 2 else 1
        aspect = iw / ih
        self.framed = not fill and aspect > 1.05 and ih < 1500  # wide and not big enough to fill the height sharply
        if self.framed:  # full width, over a blurred copy of itself
            fw = W
            fh = round(W / aspect)
            self.box = (0, max(240, (H - fh) // 2 - 330), fw, fh)  # high in the frame: the host is below
            back = img.resize((round(H * aspect), H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(26))
            bx = (back.width - W) // 2
            back = np.asarray(back.crop((bx, 0, bx + W, H)), dtype=np.float32) * 0.42
            self.backdrop = back.astype(np.uint8)
            margin = 1 + PUSH + 0.04
            tw, th = round(fw * margin), round(fh * margin)
        else:  # fill the frame
            self.box = (0, 0, W, H)
            self.backdrop = None
            scale = max(W / iw, H / ih) * (1 + PUSH + 0.04)
            tw, th = round(iw * scale), round(ih * scale)
        self.src = cv2.resize(np.asarray(img), (tw, th), interpolation=cv2.INTER_AREA if tw < iw else cv2.INTER_CUBIC)
        self.depth = cv2.resize(dep, (tw, th), interpolation=cv2.INTER_LINEAR)
        bw, bh = self.box[2], self.box[3]
        self.gx, self.gy = np.meshgrid(np.arange(bw, dtype=np.float32), np.arange(bh, dtype=np.float32))
        self.label = spec.get("label")

    def frame(self, t: float) -> np.ndarray:
        import cv2

        p = _ease(t / max(self.length, 0.5) * 0.92 + 0.04)
        x, y, bw, bh = self.box
        th, tw = self.src.shape[:2]
        z = 1 + PUSH * p  # zooming in
        cx, cy = tw / 2 + self.direction * (tw - bw / z) * self.PAN * (p - 0.5), th / 2 - (th - bh / z) * 0.08 * (p - 0.5)
        u0 = (self.gx - bw / 2) / z + cx
        v0 = (self.gy - bh / 2) / z + cy
        d = cv2.remap(self.depth, u0, v0, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        shift = PARALLAX * (p - 0.5) * 2
        u = u0 - (d - 0.5) * shift * self.direction
        v = v0 - (d - 0.5) * shift * 0.35
        moved = cv2.remap(self.src, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if self.backdrop is None:
            return moved
        out = self.backdrop.copy()
        out[y:y + bh, x:x + bw] = moved
        return out


class Scene(Photo):
    """A drawing in the Professor's art (the drawn look, tools/draw.py): a square, shown through the 9:16 frame as a
    window that travels across it, near things sliding more than far ones."""

    PAN = 0.34

    def __init__(self, spec: dict, length: float, index: int):
        super().__init__(spec, length, index, fill=True)


class FramedPhoto:
    """A real photo inside the drawn world (the drawn look): a print with a paper border, slightly turned, high in the
    frame over the line's drawing (darker and softened, so the photo leads), drifting gently. It stays flat, as a
    print would; a person's name still shows top left (Doc's name overlay)."""

    BOX = (800, 520)            # the photo fits inside this, before its border
    CENTER = (W // 2 + 30, 600)  # between the name (top left) and the captions, above the Professor
    BORDER = 20
    PAPER = (246, 240, 228)
    DRIFT, RISE, STEPS = 0.035, 14, 12  # it grows 3.5% and rises 14 px over the shot (12 sizes, made once)

    def __init__(self, spec: dict, length: float, index: int):
        self.length = length
        self.direction = -1 if index % 2 else 1
        self.backdrop = None
        if spec.get("backdrop"):  # the drawing behind, kept small, soft and darker: it only slides slowly sideways
            art = Image.open(spec["backdrop"]).convert("RGB")
            scale = max(W / art.width, H / art.height) * 1.15 / 4
            small = art.resize((round(art.width * scale), round(art.height * scale)), Image.BILINEAR)
            self.backdrop = (np.asarray(small.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32) * 0.55).astype(np.uint8)
        photo = Image.open(spec["path"]).convert("RGB")
        scale = min(self.BOX[0] / photo.width, self.BOX[1] / photo.height)
        photo = photo.resize((max(1, round(photo.width * scale)), max(1, round(photo.height * scale))), Image.LANCZOS)
        card = Image.new("RGB", (photo.width + 2 * self.BORDER, photo.height + 2 * self.BORDER), self.PAPER)
        card.paste(photo, (self.BORDER, self.BORDER))
        card = card.convert("RGBA").rotate(-2.2 if index % 2 else 2.2, resample=Image.BICUBIC, expand=True)
        pad = 60
        out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
        shadow = Image.new("RGBA", card.size, (0, 0, 0, 255))
        shadow.putalpha(card.getchannel("A").point(lambda a: a * 150 // 255))
        out.alpha_composite(shadow, (pad + 12, pad + 20))
        out = out.filter(ImageFilter.GaussianBlur(16))
        out.alpha_composite(card, (pad, pad))
        self.prints = [out.resize((round(out.width * z), round(out.height * z)), Image.BILINEAR)
                       for z in np.linspace(1, 1 + self.DRIFT, self.STEPS)]

    def frame(self, t: float) -> np.ndarray:
        import cv2

        p = _ease(t / max(self.length, 0.5))
        if self.backdrop is not None:
            bh, bw = self.backdrop.shape[:2]
            x0 = (bw - W / 4) / 2 + self.direction * (bw - W / 4) * 0.3 * (p - 0.5)
            y0 = (bh - H / 4) / 2
            move = np.float32([[4, 0, -4 * x0], [0, 4, -4 * y0]])  # a quarter-size picture, brought up to the frame
            base = cv2.warpAffine(self.backdrop, move, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        else:
            base = np.full((H, W, 3), (34, 30, 28), dtype=np.uint8)
        img = self.prints[min(self.STEPS - 1, int(p * self.STEPS))]
        x = self.CENTER[0] - img.width // 2
        y = self.CENTER[1] - img.height // 2 - round(self.RISE * p)
        return _paste(base, img, (x, y))


def soft_backdrop(path: str, shade: float = 0.45) -> np.ndarray:
    """A drawing filling the frame, softened and darkened: what a card or a map sits on in the drawn look."""
    art = Image.open(path).convert("RGB")
    scale = max(W / art.width, H / art.height)
    art = art.resize((max(W, round(art.width * scale)), max(H, round(art.height * scale))), Image.BILINEAR)
    x, y = (art.width - W) // 2, (art.height - H) // 2
    art = art.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(8))
    return (np.asarray(art, dtype=np.float32) * shade).astype(np.uint8)


class MapShot:
    """The countries on NASA's Blue Marble, lit up and labelled, the view easing in (a drawn map without it, and in the
    drawn look, over the line's drawing)."""

    def __init__(self, spec: dict, length: float, accent: tuple):
        self.length, self.accent = length, accent
        self.codes = [c for c in spec.get("countries") or [] if c in ig.countries()]
        self.arrows = spec.get("arrows") or []
        self.back = soft_backdrop(spec["backdrop"]) if spec.get("backdrop") else None
        self.drawn = ig.make({"kind": "map", "countries": self.codes, "arrows": self.arrows}, accent) \
            if spec.get("drawn") or not BLUE_MARBLE.exists() else None
        if self.drawn is None:
            self.base = Image.open(BLUE_MARBLE).convert("RGB")
            world = ig.countries()
            if self.codes:
                boxes = [world[c]["box"] for c in self.framed(world)]
                x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
                x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
                self.center = ((x0 + x1) / 2, (y0 + y1) / 2)
                self.span = max((x1 - x0) * 2.2, (y1 - y0) * 2.2 * W / H, 14)
            else:
                self.center, self.span = (10, 20), 200
            self._cache = {}

    def framed(self, world: dict) -> list[str]:
        """The countries the view is built around: all of them, or, when they're spread over more than WIDE degrees of
        longitude (the USA, Japan and the Philippines would centre the view on Africa), the biggest group that sits
        close together. Every country is lit up either way."""
        def width(group):
            return max(world[c]["box"][2] for c in group) - min(world[c]["box"][0] for c in group)
        if width(self.codes) <= WIDE:
            return self.codes
        best = []
        for seed in self.codes:
            group = [seed]
            for code in self.codes:
                if code not in group and width(group + [code]) <= WIDE:
                    group.append(code)
            if len(group) > len(best):
                best = group
        return best

    def _view(self, z: float):
        """The map at zoom z: (image W x H, function lon/lat -> pixel)."""
        bw, bh = self.base.size
        # The frame is tall: a wide country (the USA, Russia) would need more than the globe's height, so the view is
        # capped at it, and kept inside the picture at every edge.
        span_lat = min(self.span / z * H / W, 170.0)
        span_lon = span_lat * W / H
        lon0 = min(max(self.center[0] - span_lon / 2, -180.0), 180.0 - span_lon)
        lat0 = max(min(self.center[1] + span_lat * FOCUS, 90.0), -90.0 + span_lat)
        px = lambda lon: (lon + 180) / 360 * bw  # noqa: E731
        py = lambda lat: (90 - lat) / 180 * bh  # noqa: E731
        box = (px(lon0), py(lat0), px(lon0 + span_lon), py(lat0 - span_lat))
        img = self.base.resize((W, H), Image.BICUBIC, box=box)
        proj = lambda lon, lat: ((lon - lon0) / span_lon * W, (lat0 - lat) / span_lat * H)  # noqa: E731
        return img, proj

    def frame(self, t: float) -> np.ndarray:
        if self.drawn is not None:
            if self.back is not None:  # a card on the drawing, its edges showing
                out = Image.fromarray(self.back)
                out.paste(self.drawn.frame(t, (1000, 860)), (40, 300))
                return np.asarray(out)
            panel = self.drawn.frame(t, (W, 900))
            out = Image.new("RGB", (W, H), ig.BG)
            out.paste(panel, (0, 300))
            return np.asarray(out)
        z = 1 + 0.35 * _ease(t / max(self.length, 0.5))
        img, proj = self._view(z)
        img = Image.blend(img, Image.new("RGB", img.size, (8, 12, 22)), 0.18)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        world = ig.countries()
        glow = _ease(t / 0.8)
        for code in self.codes:
            for ring in world[code]["rings"]:
                pts = [proj(x, y) for x, y in ring]
                d.polygon(pts, fill=(*self.accent, int(70 * glow)), outline=(*ig.GOLD, int(255 * glow)), width=4)
        for i, pair in enumerate(self.arrows):
            if len(pair) == 2 and pair[0] in world and pair[1] in world:
                (alon, alat), (blon, blat) = world[pair[0]]["label"], world[pair[1]]["label"]
                if abs(alon - blon) > 180:  # the short way round: America to the Philippines comes across the Pacific
                    alon += 360 if alon < blon else -360
                a, b = proj(alon, alat), proj(blon, blat)
                p = _ease((t - 0.6 - 0.3 * i) / 1.0)
                if p > 0:
                    mid = ((a[0] + b[0]) / 2 - (b[1] - a[1]) * 0.2, (a[1] + b[1]) / 2 + (b[0] - a[0]) * 0.2)
                    pts = [((1 - s) ** 2 * a[0] + 2 * (1 - s) * s * mid[0] + s * s * b[0],
                            (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * mid[1] + s * s * b[1]) for s in [j / 30 * p for j in range(31)]]
                    d.line(pts, fill=(*ig.GOLD, 255), width=9, joint="curve")
        label = ig.font(ig.HEAD_FONT, 54)
        for code in self.codes:
            x, y = proj(*world[code]["label"])
            if 0 < x < W and 0 < y < H:
                d.text((x, y), ig.country_name(code).upper(), font=label, fill=(255, 255, 255, int(255 * glow)), anchor="mm",
                       stroke_width=6, stroke_fill=(0, 0, 0, int(200 * glow)))
        img = img.convert("RGBA")
        img.alpha_composite(layer)
        return np.asarray(img.convert("RGB"))


# --- overlays ---------------------------------------------------------------------

def _overlap(a: tuple, b: tuple) -> float:
    """How much two boxes overlap, as a share of the smaller one (0-1)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return w * h / smaller


def _paste(frame: np.ndarray, layer: Image.Image, xy: tuple[int, int]) -> np.ndarray:
    """Alpha-blends an RGBA image onto the frame at xy (only over its own box)."""
    x, y = xy
    lw, lh = layer.size
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + lw), min(H, y + lh)
    if x1 <= x0 or y1 <= y0:
        return frame
    part = np.asarray(layer.crop((x0 - x, y0 - y, x1 - x, y1 - y)), dtype=np.uint16)
    alpha = part[:, :, 3:4]
    region = frame[y0:y1, x0:x1].astype(np.uint16)
    frame[y0:y1, x0:x1] = ((part[:, :, :3] * alpha + region * (255 - alpha)) // 255).astype(np.uint8)
    return frame


_SHADE = {}


def _shade(size: tuple[int, int]) -> Image.Image:
    """A soft dark pool behind a number, so it reads over any footage (made once)."""
    if size not in _SHADE:
        w, h = size
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).ellipse((-200, 40, w + 200, h - 20), fill=150)
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        img.putalpha(mask.filter(ImageFilter.GaussianBlur(70)))
        _SHADE[size] = img
    return _SHADE[size]


def number_layer(value: str, label: str, t: float, hit: float) -> tuple[Image.Image, tuple[int, int]]:
    """The big number: counting up from the shot's start, landing (gold, a little big) when it's said."""
    img = _shade((W, 560)).copy()
    d = ImageDraw.Draw(img)
    p = (t - 0.15) / max(hit - 0.15, 0.4)
    if p > 0:
        landed = t - hit
        pop = 1 + 0.22 * (1 - _ease_out(landed / 0.3)) if landed >= 0 else 1.0
        big, _ = ig.fit(d, value, ig.HEAD_FONT, W * 0.88, 1, 250, 90)
        fnt = ig.font(ig.HEAD_FONT, big.size * pop)
        color = ig.mix((255, 255, 255), ig.GOLD, _ease(landed / 0.18))
        d.text((W / 2, 230), ig.count_up(value, p), font=fnt, fill=(*color, 255), anchor="mm", stroke_width=4,
               stroke_fill=(0, 0, 0, 160))
    if label:
        body, lines = ig.fit(d, label, ig.BODY_FONT, W * 0.8, 2, 50, 34)
        y = 380
        for line in lines:
            d.text((W / 2, y), line, font=body, fill=(255, 255, 255, int(255 * _ease(t / 0.4))), anchor="ma",
                   stroke_width=3, stroke_fill=(0, 0, 0, 180))
            y += ig.line_height(body)
    return img, (0, NUMBER_Y - 230)


def name_layer(label: str, t: float) -> tuple[Image.Image, tuple[int, int]]:
    """A person's or thing's name, lower left, sliding in: "STEVE JOBS · Apple's chief, 2007"."""
    name, _, role = label.partition("·")
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    room = W - 160  # it never runs off the frame: long names shrink, long roles wrap onto a second line
    head, names = ig.fit(probe, name.strip().upper(), ig.HEAD_FONT, room, 1, 46, 30)
    body, roles = ig.fit(probe, role.strip(), ig.BODY_FONT, room, 2, 34, 26) if role.strip() else (None, [])
    widths = [probe.textlength(n, font=head) for n in names] + [probe.textlength(r, font=body) for r in roles]
    step = int(ig.line_height(body)) if roles else 0
    img = Image.new("RGBA", (int(max(widths)) + 70, 96 + step * len(roles)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    p = _ease_out((t - 0.3) / 0.45)
    d.rectangle((0, 10, 12, img.height - 10), fill=(*ig.GOLD, int(255 * p)))
    d.text((36, 22), names[0] if names else "", font=head, fill=(255, 255, 255, int(255 * p)), stroke_width=3,
           stroke_fill=(0, 0, 0, int(170 * p)))
    for k, line in enumerate(roles):
        d.text((36, 84 + k * step), line, font=body, fill=(235, 235, 235, int(255 * p)), stroke_width=2,
               stroke_fill=(0, 0, 0, int(170 * p)))
    return img, (int(48 - 40 * (1 - p)), NAME_Y)


def title_layer(kicker: str, title: str, t: float, length: float = TITLE_FOR) -> tuple[Image.Image, tuple[int, int]]:
    """The case's title over the opening shot, fading out by `length` seconds."""
    img = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
    a = _ease(t / 0.35) * (1 - _ease((t - length + 0.5) / 0.5))
    if a <= 0:
        return img, (0, 170)
    d = ImageDraw.Draw(img)
    chip = ig.font(ig.BODY_FONT, 30)
    tw = d.textlength(kicker, font=chip)
    d.rounded_rectangle((W / 2 - tw / 2 - 22, 20, W / 2 + tw / 2 + 22, 68), radius=24, fill=(*ig.GOLD, int(235 * a)))
    d.text((W / 2, 44), kicker, font=chip, fill=(20, 20, 24, int(255 * a)), anchor="mm")
    head, lines = ig.fit(d, title.upper(), ig.HEAD_FONT, W * 0.88, 2, 92, 54)
    y = 100
    for line in lines:
        d.text((W / 2, y), line, font=head, fill=(255, 255, 255, int(255 * a)), anchor="ma", stroke_width=6,
               stroke_fill=(0, 0, 0, int(190 * a)))
        y += ig.line_height(head)
    return img, (0, 170)


def caption_chunks(words: list[list], max_words: int = 3, max_chars: int = 18) -> list[list]:
    """A line's words grouped as captions: [[(t, word), ...], ...], breaking after punctuation."""
    out, cur = [], []
    for item in words:
        trial = " ".join(w for _, w in cur + [item])
        if cur and (len(cur) >= max_words or len(trial) > max_chars):
            out.append(cur)
            cur = []
        cur.append(item)
        if item[1][-1:] in ",.?!;:":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def caption_layer(chunk: list, t: float, start: float, y: int = CAPTION_Y) -> tuple[Image.Image, tuple[int, int]]:
    """A caption chunk; the word being said in gold-yellow, numbers always gold; landing a little big."""
    words = [short_render.clean_text(w) for _, w in chunk]
    fnt = ig.font(ig.HEAD_FONT, CAPTION_SIZE)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    space = probe.textlength(" ", font=fnt)
    widths = [probe.textlength(w, font=fnt) for w in words]
    total = sum(widths) + space * (len(words) - 1)
    size = CAPTION_SIZE
    if total > W * 0.9:
        size = int(CAPTION_SIZE * W * 0.9 / total)
        fnt = ig.font(ig.HEAD_FONT, size)
        widths = [probe.textlength(w, font=fnt) for w in words]
        space = probe.textlength(" ", font=fnt)
        total = sum(widths) + space * (len(words) - 1)
    lh = int(ig.line_height(fnt) * 1.3)
    img = Image.new("RGBA", (W, lh + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = (W - total) / 2
    now = max((k for k, (at, _) in enumerate(chunk) if at <= t), default=0)
    for k, (word, width) in enumerate(zip(words, widths)):
        lit = k == now
        fill = ig.GOLD if NUMBERISH.search(word) else ((255, 226, 92) if lit else (255, 255, 255))
        d.text((x, 10), word, font=fnt, fill=(*fill, 255), stroke_width=max(6, size // 10), stroke_fill=(0, 0, 0, 255))
        x += width + space
    age = t - start
    if age < 0.1:  # lands a little big
        s = 1 + 0.12 * (1 - age / 0.1)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.BILINEAR)
    return img, ((W - img.width) // 2, y - img.height // 2)


# --- the case -------------------------------------------------------------------

class Doc:
    """Everything needed to draw the case, frame by frame (in order: footage is decoded as it plays)."""

    def __init__(self, case: dict):
        self.category = case.get("category") or "business"
        self.accent = ig.accent(self.category)
        self.look = Look(self.category)
        self.title = str(case.get("case_title") or "")
        # the case type over the title (no "Case file 12" after it: your call, 2026-10-27)
        self.kicker = KICKERS.get(self.category, self.category.replace("_", " ").title()).upper()
        narration = case["narration"]
        self.wav = narration["wav"]
        timed = narration["lines"]
        self.lines = [{**line, **timed[k]} for k, line in enumerate(case["lines"])]
        last_word = max(line["end"] for line in self.lines)
        self.total = round(max(last_word, float(narration.get("seconds") or 0) - 0.25) + END_PAD, 2)
        self.shots, self.overlays, self.events, self.layout = [], [], [], []
        # Agent 4's fixes after a review: overlays to leave out ({"kind": "number"|"name", "line": k}) and an
        # earlier end for the title.
        self.drops = {(d.get("kind"), d.get("line")) for d in case.get("drops") or []}
        self.title_until = min(TITLE_FOR, float(case.get("title_until") or TITLE_FOR))
        self._plan()
        self.captions = []  # [start, end, words, line]
        for k, line in enumerate(self.lines):
            for chunk in caption_chunks(line["words"]):
                self.captions.append([chunk[0][0], None, chunk, k])
        for a, b in zip(self.captions, self.captions[1:]):
            a[1] = b[0]
        if self.captions:
            self.captions[-1][1] = self.total
        self.live = {}
        self.host = None
        setup = load_config().get("host") or {}
        if setup.get("enabled", True) and (host.HOST_DIR / "rig.json").exists():
            track = narration.get("mouth")
            if track is None:  # the Animator normally works this out; a sample render may not have
                track = host.mouth_track(self.wav, self.lines)
            self.host = host.Host(self.total, self.lines, track, seed=int(case.get("case_no") or 0),
                                  size=setup.get("size", "M"))
        self.caption_y = min(CAPTION_Y, self.host.box[1] - CAPTION_GAP) if self.host else CAPTION_Y

    def _plan(self):
        """Shots, overlays and sound cues from the lines: each line's visuals share its time, the second one
        starting at the phrase break nearest the middle."""
        previous = None
        for k, line in enumerate(self.lines):
            start = 0.0 if k == 0 else max(0.0, line["start"] - LEAD_CUT)
            end = self.lines[k + 1]["start"] - LEAD_CUT if k + 1 < len(self.lines) else self.total
            visuals = [v for v in line.get("visuals") or [] if v]
            shots = [v for v in visuals if v.get("kind") in SHOT_KINDS]
            numbers = [v for v in visuals if v.get("kind") == "number"]
            if not shots:
                shots = [previous] if previous else []
            cut = start
            if len(shots) > 1:
                words = line["words"]
                middle = (line["start"] + line["end"]) / 2
                breaks = [words[i + 1][0] for i in range(len(words) - 1) if words[i][1][-1:] in ",.;:?!"] or \
                         [words[i][0] for i in range(1, len(words))]
                cut = min(breaks, key=lambda b: abs(b - middle)) - 0.05 if breaks else middle
            for n, shot in enumerate(shots[:2]):
                s0 = start if n == 0 else cut
                s1 = cut if n == 0 and len(shots) > 1 else end
                if s1 - s0 > 0.2:
                    self.shots.append({"start": s0, "end": s1, "spec": shot, "index": len(self.shots)})
            previous = shots[-1] if shots else previous
            for number in numbers if ("number", k) not in self.drops else []:
                digits = re.sub(r"\D", "", str(number.get("value")))
                hit = next((at for at, w in line["words"] if digits and re.sub(r"\D", "", w) == digits), line["start"] + 0.6)
                self.overlays.append({"kind": "number", "start": start, "end": end, "hit": hit, **number, "line": k})
                self.events.append(("impact", hit))
            for shot in shots[:1]:
                named = max(start, self.title_until)  # names share the top of the frame with the title: after it
                if shot.get("label") and end - named > 1.0 and ("name", k) not in self.drops:
                    self.overlays.append({"kind": "name", "start": named, "end": min(end, named + 3.5), "label": shot["label"],
                                          "line": k})
            beat = line.get("beat")
            if k and beat in ("setup", "turn", "context", "question"):  # (context and question: v5's first scripts)
                self.events.append(("whoosh", start))
            if beat == "reveal" and self.lines[k - 1].get("beat") != "reveal":  # into the reveal, once
                self.events.append(("riser", max(0.0, start - 1.4)))
                self.events.append(("flash", start + LEAD_CUT))
        self.overlays.append({"kind": "title", "start": 0.0, "end": self.title_until, "line": 0})

    def _shot(self, n: int):
        shot = self.shots[n]
        if n not in self.live:
            spec, length = shot["spec"], shot["end"] - shot["start"]
            kind = spec.get("kind")
            if kind == "footage":
                self.live[n] = Footage(spec, length)
            elif kind == "photo":
                self.live[n] = Photo(spec, length, shot["index"])
            elif kind == "scene":
                self.live[n] = Scene(spec, length, shot["index"])
            elif kind == "framed":
                self.live[n] = FramedPhoto(spec, length, shot["index"])
            elif kind == "map":
                self.live[n] = MapShot(spec, length, self.accent)
            else:
                self.live[n] = CardShot(spec, length, self.accent)
            for old in [k for k in self.live if k < n - 1]:  # done with: free their decoders
                closer = getattr(self.live[old], "close", None)
                if closer:
                    closer()
                del self.live[old]
        return self.live[n]

    def frame(self, n: int) -> np.ndarray:
        t = n / FPS
        k = next((i for i, s in enumerate(self.shots) if s["start"] <= t < s["end"]), len(self.shots) - 1)
        if k < 0:
            frame = np.zeros((H, W, 3), dtype=np.uint8)
        else:
            frame = np.ascontiguousarray(self._shot(k).frame(t - self.shots[k]["start"]))
        frame = self.look.apply(frame, n)
        for kind, at in self.events:
            if kind == "flash" and at <= t < at + 0.12:
                frame = np.clip(frame.astype(np.int16) + int(180 * (1 - (t - at) / 0.12)), 0, 255).astype(np.uint8)
        frame = frame.copy() if not frame.flags.writeable else frame
        if self.host:
            frame = self.host.draw(frame, t)
        texts = []  # (kind, box) of what's written on this frame, for the layout check
        for o in self.overlays:
            if not o["start"] <= t < o["end"]:
                continue
            local = t - o["start"]
            if o["kind"] == "number":
                layer, xy = number_layer(str(o.get("value")), str(o.get("label") or ""), local, o["hit"] - o["start"])
            elif o["kind"] == "name":
                layer, xy = name_layer(o["label"], local)
            else:
                layer, xy = title_layer(self.kicker, self.title, local, self.title_until)
            frame = _paste(frame, layer, xy)
            texts.append((o["kind"], layer, xy, o["line"]))
        for start, end, chunk, line in self.captions:
            if start <= t < end:
                layer, xy = caption_layer(chunk, t, start, self.caption_y)
                frame = _paste(frame, layer, xy)
                texts.append(("caption", layer, xy, line))
                break
        if n % AUDIT_EVERY == 0:
            self._audit(t, texts, k)
        return frame

    def _audit(self, t: float, texts: list, k: int) -> None:
        """Where the words on screen are (only their solid pixels, not the soft shade behind a number), and any that
        overlap each other, cover the Professor's face, or reach under YouTube's buttons or title text; and a clip
        that ran out and has held its last frame for over FROZEN seconds (shot k is on screen)."""
        boxes = []
        for kind, layer, (x, y), line in texts:
            box = layer.getchannel("A").point(lambda a: 255 if a > 180 else 0).getbbox()
            if box:
                boxes.append((kind, (x + box[0], y + box[1], x + box[2], y + box[3]), line))
        found = []  # (kind, what, line): the line is that of the words that could come off (captions never do)
        for i, (a, ba, la) in enumerate(boxes):
            for b, bb, lb in boxes[i + 1:]:
                if _overlap(ba, bb) > 0.04:
                    found.append(("overlap", f"{a}+{b}", lb if a == "caption" else la))
            if self.host and _overlap(ba, self.host.face) > 0.04:
                found.append(("covers_host", a, la))
            x0, y0, x1, y1 = ba
            if (x1 > SAFE_RIGHT and y1 > SAFE_RIGHT_FROM) or y1 > SAFE_BOTTOM:
                found.append(("unsafe", a, la))
        held = getattr(self.live.get(k), "ran_out", None) if k >= 0 else None
        if held is not None and t - self.shots[k]["start"] - held > FROZEN:
            found.append(("frozen", self.shots[k]["spec"].get("name") or "footage", _line_at(self, self.shots[k]["start"])))
        for kind, what, line in found:
            last = next((x for x in reversed(self.layout) if (x["kind"], x["what"], x["line"]) == (kind, what, line)), None)
            if last and t - last["end"] <= AUDIT_EVERY / FPS + 0.01:
                last["end"] = round(t, 2)
            else:
                self.layout.append({"kind": kind, "what": what, "line": line, "start": round(t, 2), "end": round(t, 2)})

    def close(self):
        for shot in self.live.values():
            closer = getattr(shot, "close", None)
            if closer:
                closer()


class CardShot:
    """A chart or a quote (tools/infographics.py) on a dark panel, high in the frame (in the drawn look, over the
    line's drawing)."""

    def __init__(self, spec: dict, length: float, accent: tuple):
        self.visual = ig.make(spec, accent, {"line": length, "length": length})
        self.back = soft_backdrop(spec["backdrop"]) if spec.get("backdrop") else None

    def frame(self, t: float) -> np.ndarray:
        panel = self.visual.frame(t, (1000, 660))
        out = Image.fromarray(self.back) if self.back is not None else Image.new("RGB", (W, H), (10, 13, 20))
        out.paste(panel, (40, 280))  # high in the frame: the captions and the host are below
        return np.asarray(out)


# --- audio and encoding ---------------------------------------------------------------------

def _effects_wav(doc: Doc, dest: Path) -> None:
    """The narration with the sound cues mixed in, as one 24 kHz mono track."""
    with wave.open(str(doc.wav), "rb") as w:
        voice = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    track = np.zeros(int((doc.total + 2) * SAMPLE_RATE), dtype=np.float32)
    track[:len(voice)] += voice[:len(track)]
    whooshes = sfx.whooshes()
    for n, (kind, at) in enumerate(doc.events):
        sound = {"impact": sfx.impact(), "riser": sfx.riser()}.get(kind) if kind != "whoosh" else (
            whooshes[n % len(whooshes)] if whooshes else None)
        if sound is None:
            continue
        gain = {"impact": 0.5, "riser": 0.28, "whoosh": 0.32}[kind]
        i = max(0, int((at - (0.05 if kind == "whoosh" else 0)) * SAMPLE_RATE))
        piece = sound[:max(0, len(track) - i)] * gain
        track[i:i + len(piece)] += piece
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())


def render(case: dict, out_path: Path | str, music: Path | None = None, volume: float = 1.0,
           cover_path: Path | str | None = None, progress=print) -> dict:
    """Draws and encodes the case; returns its length, frame count and how long it took, what the layout audit found
    ({"kind": "overlap"|"covers_host"|"unsafe"|"frozen", "what", "start", "end"}) and the shots in order (for the
    Reviewer, agents/reviewer.py)."""
    started = time.monotonic()
    doc = Doc(case)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="doc_", dir=TMP_DIR / "work"))
    voice = work / "voice.wav"
    _effects_wav(doc, voice)
    total = doc.total
    cmd = [short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-", "-i", str(voice)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    gain = 0.2 * volume
    audio = (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={total:.2f}[d];"
             f"[d]asplit=2[d1][d2];"
             f"[2:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
             f"volume={gain:.3f},afade=t=in:st=0:d=0.6,afade=t=out:st={max(total - 1.0, 0):.2f}:d=1.0[m];"
             f"[m][d1]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=400[md];"
             f"[md][d2]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", audio, "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", "-t", f"{total:.2f}",
            str(out)]
    frames = math.ceil(total * FPS)
    errors = work / "ffmpeg.log"
    cover = None
    try:
        with open(errors, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
            try:
                for n in range(frames):
                    frame = doc.frame(n)
                    if cover_path and n == int(1.2 * FPS):
                        cover = frame.copy()
                    proc.stdin.write(frame.tobytes())
                    if n and n % (FPS * 10) == 0:
                        progress(f"Drawn {n // FPS} of {total:.0f} seconds")
                proc.stdin.close()
                proc.wait(timeout=RENDER_TIMEOUT_S)
            except Exception:
                proc.kill()
                raise
    finally:
        doc.close()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {errors.read_text(encoding='utf-8', errors='replace')[-1500:]}")
    if cover_path and cover is not None:
        Image.fromarray(cover).resize((540, 960), Image.LANCZOS).save(cover_path, quality=88)
    for item in work.iterdir():
        item.unlink()
    work.rmdir()
    return {"seconds": total, "frames": frames, "render_seconds": round(time.monotonic() - started, 1),
            "layout": doc.layout, "shots": [{"start": round(s["start"], 2), "end": round(s["end"], 2),
                                             "kind": s["spec"].get("kind"), "name": s["spec"].get("name"),
                                             "line": _line_at(doc, s["start"])} for s in doc.shots]}


def _line_at(doc: Doc, t: float) -> int:
    """The number (0-based) of the line being said at t."""
    return max([k for k, line in enumerate(doc.lines) if line["start"] - LEAD_CUT - 0.01 <= t] or [0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--music", default="auto", help="track path, 'auto' or 'none'")
    parser.add_argument("--cover")
    args = parser.parse_args()
    try:
        with open(args.case, encoding="utf-8") as f:
            case = json.load(f)
        music = None if args.music == "none" else short_render.pick_music(case.get("music_mood")) if args.music == "auto" \
            else Path(args.music)
        result = render(case, args.out, music, load_config()["music"]["volume"], cover_path=args.cover)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
