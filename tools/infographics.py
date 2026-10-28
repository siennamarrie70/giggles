"""
The case studies' visuals: what plays on the studio's wall screen or fills the frame. Photos,
charts, maps, timelines, big numbers, versus cards, quotes, short lists and title cards.

Each visual draws itself at any panel size and animates in; after that its drawing is cached, and
the card keeps zooming in slowly so it never sits still (photos pan and zoom instead). Given the
words of the line it opens on and when each is said (cues), it follows them: a big number pops in
as it's said, a timeline's years turn gold as they're said, lists and timelines fill in while the
line is spoken. Shapes and text are drawn at twice the size and shrunk, like the hosts, so edges
stay smooth. A spec is self-contained: the Animator resolves the script's references (image ids,
data series, facts) into it before rendering.

  {"kind": "photo", "path": "...", "credit": "Photo: Jane Doe, CC BY 4.0", "move": "in"}
  {"kind": "chart", "title": "...", "unit": "%", "points": [[2007, 49.4], ...], "forecast_from": 2026,
   "highlight": 2013, "source": "IMF"}                     ("style": "bar" with [["China", 145], ...])
  {"kind": "map", "countries": ["USA", "CHN"], "arrows": [["CHN", "USA"]]}
  {"kind": "timeline", "events": [{"when": "2007", "text": "The iPhone arrives"}, ...]}
  {"kind": "stat", "value": "49%", "label": "of smartphones sold in 2007 were Nokias"}
  {"kind": "versus", "left": {"title": "Nokia", "value": "49%"}, "right": {"title": "Apple", "value": "5%"}}
  {"kind": "quote", "text": "...", "who": "..."}
  {"kind": "list", "title": "...", "items": ["...", "...", "..."]}
  {"kind": "title", "kicker": "BUSINESS · CASE FILE 12", "title": "WHY NOKIA FAILED"}

Usage:
    python tools/infographics.py --spec visual.json --out .tmp/out/visual.png [--t 2] [--size 1080x920]
"""

import argparse
import json
import math
import re
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from common import ASSETS_DIR

HEAD_FONT = ASSETS_DIR / "fonts" / "ArchivoBlack-Regular.ttf"
BODY_FONT = ASSETS_DIR / "fonts" / "Arimo-Bold.ttf"
MAP_FILE = ASSETS_DIR / "maps" / "countries.json"
SHORT_NAMES = {"USA": "USA", "GBR": "UK", "COD": "DR Congo", "CAF": "C. African Rep."}
SS = 2

BG = (21, 26, 37)
GRID = (52, 60, 79)
LAND = (58, 67, 88)
TEXT = (246, 244, 238)
MUTED = (150, 158, 178)
GOLD = (255, 205, 64)
ACCENTS = {"business": (59, 130, 246), "economy": (34, 168, 110), "trending": (236, 72, 72),
           "history": (214, 150, 46), "mythology": (139, 92, 246), "dark_history": (190, 70, 46),
           "mysteries": (32, 170, 160), "technology": (56, 165, 240), "psychology": (168, 92, 222),
           "people": (232, 150, 44), "science": (92, 118, 255), "crime": (196, 70, 78)}
NUMBER = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)")
PUSH = 0.06  # how much a card zooms in while it's on screen


def accent(category: str) -> tuple:
    return ACCENTS.get(category, ACCENTS["business"])


def mix(a: tuple, b: tuple, t: float) -> tuple:
    t = min(1.0, max(0.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def ease_out(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


@lru_cache(maxsize=256)
def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(8, int(size)))


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=fnt) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def fit(draw: ImageDraw.ImageDraw, text: str, path: Path, max_w: float, max_lines: int, size: float,
        min_size: float) -> tuple:
    """The biggest font (from size down to min_size) that fits the text in max_lines lines, the lines
    evened out (no lonely last word)."""
    size = int(size)
    while True:
        fnt = font(path, size)
        lines = wrap(draw, text, fnt, max_w)
        if (len(lines) <= max_lines and all(draw.textlength(l, font=fnt) <= max_w for l in lines)) or size <= min_size:
            break
        size = int(size * 0.92)
    width = max_w
    while len(lines) > 1 and width > max_w * 0.5:
        trial = wrap(draw, text, fnt, width - max_w * 0.05)
        if len(trial) > len(lines):
            break
        lines, width = trial, width - max_w * 0.05
    return fnt, lines[:max_lines]


def line_height(fnt) -> float:
    top, bottom = fnt.getbbox("Hg")[1::2]
    return (bottom - top) * 1.18


def count_up(value: str, p: float) -> str:
    """The value as it counts up: '49%' at p=0.5 reads '25%' (decimals and separators kept)."""
    m = NUMBER.search(value or "")
    if not m or p >= 1:
        return value
    raw = m.group(1)
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    number = float(raw.replace(",", "")) * ease_out(p)
    shown = f"{number:,.{decimals}f}" if "," in raw else f"{number:.{decimals}f}"
    return value[:m.start()] + shown + value[m.end():]


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    first = math.floor(lo / step) * step
    return [first + i * step for i in range(int(math.ceil((hi - first) / step)) + 1)]


def as_number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def short_number(v: float) -> str:
    if v == int(v) and 1000 <= v <= 2200:  # a year
        return str(int(v))
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 or abs(v) >= 100 else f"{v:.1f}"


class Visual:
    """Something on the screen. frame() is what renderers call; subclasses implement draw().

    cues (optional) tie it to the words: {"line": seconds until the line it opens on ends, "length": seconds
    it stays on screen, "said": [[seconds, word], ...] (when each word is said)}, all from the visual's start."""

    still_after: float | None = 1.5  # seconds: from then on the drawing doesn't change (and is cached)
    push = True  # zooms in slowly while it's on screen

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        self.spec, self.accent = spec, accent_color
        self.cues = cues or {}
        self._still, self._last = {}, (None, None)

    def said_at(self, value) -> float | None:
        """When the line says this number (the first word with the same digits), if it does."""
        digits = re.sub(r"\D", "", str(value or ""))
        if not digits:
            return None
        return next((at for at, word in self.cues.get("said") or [] if re.sub(r"\D", "", word) == digits), None)

    def spread(self, n: int, first: float = 0.3, least: float = 0.4, most: float = 1.4) -> list[float]:
        """When each of n items appears: spread over most of the line the visual opens on."""
        line = self.cues.get("line") or 0
        gap = min(most, max(least, (line * 0.72 - first) / max(1, n))) if line else least
        return [first + gap * i for i in range(n)]

    def frame(self, t: float, size: tuple[int, int]) -> Image.Image:
        if not self.push:
            return self._drawn(t, size)
        big = (round(size[0] * (1 + PUSH)), round(size[1] * (1 + PUSH)))
        z = 1 + PUSH * min(1.0, max(0.0, t) / max(2.0, self.cues.get("length") or 6.0))
        w, h = big[0] / z, big[1] / z  # drawn a little bigger and shrunk less and less: always sharp
        x0, y0 = (big[0] - w) / 2, (big[1] - h) / 2
        return self._drawn(t, big).resize(size, Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))

    def _drawn(self, t: float, size: tuple[int, int]) -> Image.Image:
        if self.still_after is not None and t >= self.still_after:
            if size not in self._still:
                self._still[size] = self.draw(self.still_after, size)
            return self._still[size]
        if not self.push:
            return self.draw(max(0.0, t), size)
        t = math.floor(max(0.0, t) * 12) / 12  # a card animates on twos, like the hosts (its zoom stays smooth)
        if self._last[0] != (t, size):
            self._last = ((t, size), self.draw(t, size))
        return self._last[1]

    def draw(self, t: float, size: tuple[int, int]) -> Image.Image:
        raise NotImplementedError

    @staticmethod
    def canvas(size: tuple[int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw, float]:
        """A blank panel at twice the size, and the unit: 1 on a full-width panel at least 620 tall."""
        w, h = size[0] * SS, size[1] * SS
        img = Image.new("RGB", (w, h), BG)
        return img, ImageDraw.Draw(img), min(w / 1080, h / 620)

    @staticmethod
    def done(img: Image.Image) -> Image.Image:
        return img.reduce(SS)


class Photo(Visual):
    """A photo with a slow zoom or pan; one of a very different shape is shown whole over a blurred copy."""

    still_after = None
    push = False  # it moves by itself
    ZOOM, MAX_ZOOM = 0.02, 0.16

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        img = Image.open(spec["path"]).convert("RGB")
        if max(img.size) > 2200:  # plenty for a zoom on a 1080-wide panel
            img.thumbnail((2200, 2200), Image.LANCZOS)
        self.img = img
        self.move = spec.get("move") or "in"
        self.credit = " ".join(str(spec.get("credit") or "").split())
        self._backdrops, self._labels = {}, {}

    def _zoom(self, t: float) -> float:
        z = min(self.ZOOM * t, self.MAX_ZOOM)
        return 1 + (self.MAX_ZOOM - z if self.move == "out" else z)

    def _backdrop(self, size):
        if size not in self._backdrops:
            w, h = size
            iw, ih = self.img.size
            s = max(w / iw, h / ih) * 1.1
            big = self.img.resize((max(w, round(iw * s)), max(h, round(ih * s))), Image.BILINEAR)
            big = big.crop(((big.width - w) // 2, (big.height - h) // 2, (big.width - w) // 2 + w, (big.height - h) // 2 + h))
            dark = Image.new("RGB", size, BG)
            self._backdrops[size] = Image.blend(big.filter(ImageFilter.GaussianBlur(28)), dark, 0.45)
        return self._backdrops[size]

    def _label(self, size):
        if size not in self._labels:
            fnt = font(BODY_FONT, max(15, size[0] * 0.021))
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            text = self.credit
            while text and probe.textlength(text, font=fnt) > size[0] * 0.8:
                text = text[:-2]
            text = text if text == self.credit else text.rstrip() + "…"
            tw = probe.textlength(text, font=fnt)
            pad = fnt.size * 0.45
            label = Image.new("RGBA", (round(tw + pad * 2), round(fnt.size * 1.5)), (0, 0, 0, 0))
            d = ImageDraw.Draw(label)
            d.rounded_rectangle((0, 0, label.width - 1, label.height - 1), radius=label.height // 2, fill=(0, 0, 0, 150))
            d.text((pad, label.height / 2), text, font=fnt, fill=(235, 235, 235, 255), anchor="lm")
            self._labels[size] = label
        return self._labels[size]

    def draw(self, t, size):
        w, h = size
        iw, ih = self.img.size
        panel, photo = w / h, iw / ih
        if max(panel / photo, photo / panel) > 1.45:
            out = self._backdrop(size).copy()
            s = min(w / iw, h / ih) * 0.94 * (1 + min(0.01 * t, 0.06))
            fg = self.img.resize((max(1, round(iw * s)), max(1, round(ih * s))), Image.BILINEAR)
            out.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
        else:
            cw, ch = (iw, iw / panel) if photo < panel else (ih * panel, ih)
            z = self._zoom(t)
            cw, ch = cw / z, ch / z
            p = ease(t / 9)
            fx, fy = {"left": (1 - p, 0.45), "right": (p, 0.45), "up": (0.5, 1 - p), "down": (0.5, p)}.get(self.move, (0.5, 0.42))
            x0, y0 = (iw - cw) * fx, (ih - ch) * fy
            out = self.img.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))
        if self.credit:
            label = self._label(size)
            out.paste(label, (w - label.width - round(w * 0.015), h - label.height - round(h * 0.02)), label)
        return out


class Chart(Visual):
    """A line chart that draws itself while the line is said (forecast years dashed), or bars that grow; the
    highlighted value pops up once the line reaches it (and the words do, if they say it)."""

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        self.takes = min(3.0, max(1.25, (self.cues.get("line") or 0) * 0.5))  # seconds to draw
        self.mark_said = self.said_at(spec.get("highlight"))
        self.still_after = max(self.takes, self.mark_said or 0) + 0.6

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        title = str(self.spec.get("title") or "")
        unit = str(self.spec.get("unit") or "")
        pad = 56 * u
        top = pad
        if title:
            fnt, lines = fit(d, title, BODY_FONT, W - 2 * pad, 2, 50 * u, 30 * u)
            for line in lines:
                d.text((pad, top), line, font=fnt, fill=TEXT)
                top += line_height(fnt)
            top += 22 * u
        source = str(self.spec.get("source") or "")
        small = font(BODY_FONT, 26 * u)
        bottom = H - pad - (line_height(small) if source else 0) - 64 * u
        if source:
            d.text((pad, H - pad - line_height(small) * 0.8), f"Source: {source}", font=small, fill=MUTED)
        points = [(p[0], float(p[1])) for p in self.spec.get("points") or [] if len(p) >= 2]
        if not points:
            return self.done(img)
        bars = self.spec.get("style") == "bar" or not all(isinstance(x, (int, float)) for x, _ in points)
        values = [v for _, v in points]
        lo, hi = min(0.0, min(values)), max(values)
        ticks = nice_ticks(lo, hi * (1.12 if hi > 0 else 1))
        lo, hi = ticks[0], ticks[-1]
        left = pad + 92 * u
        right = W - pad - 24 * u

        def y_of(v):
            return bottom - (v - lo) / (hi - lo) * (bottom - top - 40 * u)

        label_font = font(BODY_FONT, 28 * u)
        for tick in ticks:
            y = y_of(tick)
            d.line((left, y, right, y), fill=GRID, width=max(1, round(2 * u)))
            d.text((left - 16 * u, y), short_number(tick) + (unit if unit in ("%",) else ""), font=label_font,
                   fill=MUTED, anchor="rm")
        value_font = font(HEAD_FONT, 40 * u)
        if bars:
            n = len(points)
            slot = (right - left) / n
            bw = slot * 0.62
            stagger = max(0.12, (self.takes - 0.9) / max(1, n - 1))
            for i, (name, v) in enumerate(points):
                p = ease_out((t - stagger * i) / 0.9)
                x = left + slot * (i + 0.5)
                y = y_of(lo + (v - lo) * p)
                color = GOLD if str(name) == str(self.spec.get("highlight")) else self.accent
                d.rounded_rectangle((x - bw / 2, min(y, y_of(lo) - 1), x + bw / 2, y_of(lo)), radius=10 * u, fill=color)
                if p > 0.05:
                    d.text((x, y - 10 * u), count_up(short_number(v) + unit, p), font=value_font, fill=TEXT, anchor="mb")
                name_font, name_lines = fit(d, str(name), BODY_FONT, slot * 0.95, 2, 30 * u, 18 * u)
                ny = bottom + 14 * u
                for line in name_lines:
                    d.text((x, ny), line, font=name_font, fill=TEXT, anchor="ma")
                    ny += line_height(name_font)
            return self.done(img)

        xs = [float(x) for x, _ in points]
        x_lo, x_hi = min(xs), max(xs)

        def x_of(x):
            return left + (x - x_lo) / ((x_hi - x_lo) or 1) * (right - left)

        progress = ease(t / self.takes)
        reach = x_lo + (x_hi - x_lo) * progress
        forecast = as_number(self.spec.get("forecast_from"))
        width = max(2, round(9 * u))
        shown = []
        for (xa, va), (xb, vb) in zip(points, points[1:]):
            xa, xb = float(xa), float(xb)
            if xa >= reach:
                break
            end_x = min(xb, reach)
            end_v = va + (vb - va) * ((end_x - xa) / ((xb - xa) or 1))
            a, b = (x_of(xa), y_of(va)), (x_of(end_x), y_of(end_v))
            if forecast is not None and xa >= forecast:
                segments = max(1, int(math.dist(a, b) / (26 * u)))
                for k in range(segments):
                    if k % 2 == 0:
                        s0, s1 = k / segments, min(1, (k + 1) / segments)
                        d.line((a[0] + (b[0] - a[0]) * s0, a[1] + (b[1] - a[1]) * s0,
                                a[0] + (b[0] - a[0]) * s1, a[1] + (b[1] - a[1]) * s1), fill=self.accent, width=width)
            else:
                d.line((a, b), fill=self.accent, width=width, joint="curve")
            shown.append((xa, va))
        if points and float(points[-1][0]) <= reach:
            shown.append((float(points[-1][0]), points[-1][1]))
        for x, v in shown:
            r = 8 * u
            d.ellipse((x_of(x) - r, y_of(v) - r, x_of(x) + r, y_of(v) + r), fill=self.accent)
        mark = as_number(self.spec.get("highlight"))
        for x in sorted({x_lo, x_hi} | ({mark} if mark is not None and x_lo <= mark <= x_hi else set())):
            d.text((x_of(x), bottom + 18 * u), short_number(x), font=label_font, fill=MUTED, anchor="ma")
        if forecast is not None and x_lo < forecast <= x_hi and progress > 0.6:
            d.text((x_of(forecast), top), "forecast", font=small, fill=MUTED, anchor="la")
        target = next(((float(x), v) for x, v in points if mark is not None and float(x) == mark), None) \
            or (float(points[-1][0]), points[-1][1])
        share = (target[0] - x_lo) / ((x_hi - x_lo) or 1)
        reached = next((s / 50 * self.takes for s in range(51) if ease(s / 50) >= share - 1e-9), self.takes)
        shown = max(reached, self.mark_said or 0)
        if t >= shown:
            pop = 1 + 0.3 * (1 - ease_out((t - shown) / 0.3))  # lands a little big, then settles
            x, y = x_of(target[0]), y_of(target[1])
            r = 15 * u * pop
            d.ellipse((x - r, y - r, x + r, y + r), fill=GOLD, outline=BG, width=max(1, round(4 * u)))
            vf = font(HEAD_FONT, 40 * u * pop)
            text = short_number(target[1]) + unit
            tw = d.textlength(text, font=vf)
            bh, padx = 62 * u * pop, 18 * u * pop
            bx = min(max(x - tw / 2 - padx, left), right - tw - 2 * padx)
            by = y - 30 * u - bh if y - 30 * u - bh > top else y + 30 * u
            d.rounded_rectangle((bx, by, bx + tw + 2 * padx, by + bh), radius=14 * u, fill=GOLD)
            d.text((bx + padx, by + bh / 2), text, font=vf, fill=BG, anchor="lm")
        return self.done(img)


@lru_cache(maxsize=1)
def countries() -> dict:
    with open(MAP_FILE, encoding="utf-8") as f:
        data = json.load(f)["countries"]
    for country in data.values():
        main = max(country["rings"], key=lambda r: abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))))
        xs, ys = [p[0] for p in main], [p[1] for p in main]
        country["box"] = (min(xs), min(ys), max(xs), max(ys))
    return data


def country_name(code: str) -> str:
    return SHORT_NAMES.get(code) or (countries().get(code) or {}).get("name") or code


class Map(Visual):
    """The countries in question, highlighted, zoomed to; arrows (trade, money, people) draw in, then dots keep
    flowing along them."""

    still_after = None  # the dots keep moving; the land is drawn once and cached
    FLOW = 1.6  # seconds for a dot to travel an arrow

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        self._land = {}

    def draw(self, t, size):
        glow = ease(t / 0.6)
        if glow < 1 or size not in self._land:
            img, proj, u = self._draw_land(size, glow)
            if glow >= 1:
                self._land[size] = (img, proj, u)
        else:
            img, proj, u = self._land[size]
        img = img.copy()
        d = ImageDraw.Draw(img)
        world = countries()
        for i, pair in enumerate(self.spec.get("arrows") or []):
            if len(pair) != 2 or pair[0] not in world or pair[1] not in world:
                continue
            p = ease((t - 0.5 - 0.25 * i) / 0.9)
            if p <= 0:
                continue
            a, b = proj(*world[pair[0]]["label"]), proj(*world[pair[1]]["label"])
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            nx, ny = -(b[1] - a[1]), b[0] - a[0]
            norm = math.hypot(nx, ny) or 1
            bend = 0.22 * math.dist(a, b)
            ctrl = (mx + nx / norm * bend, my + ny / norm * bend)

            def at(s, a=a, b=b, ctrl=ctrl):
                return ((1 - s) ** 2 * a[0] + 2 * (1 - s) * s * ctrl[0] + s * s * b[0],
                        (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * ctrl[1] + s * s * b[1])

            curve = [at(j / 40 * p) for j in range(41)]
            d.line(curve, fill=GOLD, width=max(2, round(10 * u)), joint="curve")
            (ex, ey), (px, py) = curve[-1], curve[-3]
            ang = math.atan2(ey - py, ex - px)
            head = 30 * u
            d.polygon([(ex + math.cos(ang) * head * 0.6, ey + math.sin(ang) * head * 0.6),
                       (ex + math.cos(ang + 2.5) * head, ey + math.sin(ang + 2.5) * head),
                       (ex + math.cos(ang - 2.5) * head, ey + math.sin(ang - 2.5) * head)], fill=GOLD)
            if p >= 1:  # what moves along it
                done = 0.5 + 0.25 * i + 0.9
                for j in range(3):
                    s = ((t - done) / self.FLOW + j / 3) % 1 * 0.9
                    x, y = at(s)
                    r = 9 * u
                    d.ellipse((x - r, y - r, x + r, y + r), fill=TEXT, outline=BG, width=max(1, round(3 * u)))
        label = font(BODY_FONT, 38 * u)
        for code in [c for c in self.spec.get("countries") or [] if c in world]:
            x, y = proj(*world[code]["label"])
            if 0 < x < img.width and 0 < y < img.height:
                d.text((x, y), SHORT_NAMES.get(code, world[code]["name"]), font=label, fill=mix(BG, TEXT, glow), anchor="mm",
                       stroke_width=max(1, round(5 * u)), stroke_fill=mix(BG, (10, 12, 18), glow))
        return self.done(img)

    def _draw_land(self, size, glow):
        """The countries, the ones in question lit up; and the projection used."""
        img, d, u = self.canvas(size)
        W, H = img.size
        world = countries()
        codes = [c for c in self.spec.get("countries") or [] if c in world]
        if codes:
            boxes = [world[c]["box"] for c in codes]
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            span_x, span_y = max((x1 - x0) * 1.5, 26), max((y1 - y0) * 1.5, 16)
        else:
            cx, cy, span_x, span_y = 10, 20, 360, 150
        k = math.cos(math.radians(max(-60, min(60, cy))))
        # widen or heighten the view to the panel's shape
        if span_x * k / span_y < W / H:
            span_x = span_y * (W / H) / k
        else:
            span_y = span_x * k / (W / H)
        scale = W / (span_x * k)

        def proj(lon, lat):
            return W / 2 + (lon - cx) * k * scale, H / 2 - (lat - cy) * scale

        outline = max(1, round(2 * u))
        for code, country in world.items():
            fill = mix(LAND, self.accent, glow) if code in codes else LAND
            for ring in country["rings"]:
                pts = [proj(x, y) for x, y in ring]
                if max(p[0] for p in pts) < 0 or min(p[0] for p in pts) > W or max(p[1] for p in pts) < 0 \
                        or min(p[1] for p in pts) > H:
                    continue
                d.polygon(pts, fill=fill, outline=BG, width=outline)
        return img, proj, u


class Timeline(Visual):
    """Up to five dated events down a line, filling in while the line is said; a year turns gold as it's said
    (the last one does if none is)."""

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        self.events = [e for e in spec.get("events") or [] if e.get("text")][:5]
        said = [self.said_at(e.get("when")) for e in self.events]
        shows = self.spread(len(self.events))
        for j, at in enumerate(said):  # a year that's said is on screen by then, with the ones above it
            if at is not None:
                shows[:j + 1] = [min(s, at) for s in shows[:j + 1]]
        for i in range(1, len(shows)):
            shows[i] = max(shows[i], shows[i - 1] + 0.12)
        self.shows = shows
        self.golds = said if any(at is not None for at in said) else [None] * (len(shows) - 1) + shows[-1:]
        self.still_after = max(shows + [g for g in self.golds if g is not None] + [0.0]) + 0.6

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        n = max(1, len(self.events))
        pad = 60 * u
        x_line = pad + 30 * u
        step = (H - 2 * pad) / n
        lw = max(1, round(6 * u))
        d.line((x_line, pad, x_line, H - pad), fill=GRID, width=lw)
        shown = [ease_out((t - at) / 0.45) for at in self.shows]
        last = max((i for i, p in enumerate(shown) if p > 0), default=None)
        if last is not None:  # the line fills down to the newest event
            d.line((x_line, pad, x_line, max(pad, pad + step * (last - 0.5 + shown[last]))), fill=self.accent, width=lw)
        when_font = font(HEAD_FONT, min(48 * u, step * 0.36))
        for i, event in enumerate(self.events):
            p = shown[i]
            if p <= 0:
                continue
            cy = pad + step * (i + 0.5)
            r = 16 * u
            gold = self.golds[i]
            g = ease((t - gold) / 0.3) if gold is not None else 0.0
            color = mix(self.accent, GOLD, g)
            if gold is not None and 0 <= t - gold < 0.6:  # a ring goes out from it as it's said
                q = (t - gold) / 0.6
                rr = r * (1 + 2.2 * ease_out(q))
                d.ellipse((x_line - rr, cy - rr, x_line + rr, cy + rr), outline=mix(GOLD, BG, q), width=max(1, round(5 * u)))
            d.ellipse((x_line - r, cy - r, x_line + r, cy + r), fill=mix(BG, color, p))
            x = x_line + 46 * u + (1 - p) * 40 * u
            when = str(event.get("when") or "")
            d.text((x, cy), when, font=when_font, fill=mix(BG, color, p), anchor="lm")
            tx = x + d.textlength(when, font=when_font) + 26 * u
            body, lines = fit(d, str(event["text"]), BODY_FONT, W - tx - pad, 2, min(40 * u, step * 0.3), 20 * u)
            lh = line_height(body)
            y = cy - lh * len(lines) / 2
            for line in lines:
                d.text((tx, y), line, font=body, fill=mix(BG, TEXT, p))
                y += lh
        return self.done(img)


class Stat(Visual):
    """One big number that counts up, and lands (in gold, a little big) as it's said; under it, what it means."""

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        said = self.said_at(spec.get("value"))
        self.hit = max(0.9, said) if said is not None else 0.9
        self.still_after = self.hit + 0.5

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        value = str(self.spec.get("value") or "")
        label = str(self.spec.get("label") or "")
        big, _ = fit(d, value, HEAD_FONT, W * 0.86, 1, min(230 * u, H * 0.36), 60 * u)
        body, lines = fit(d, label, BODY_FONT, W * 0.84, 3, 50 * u, 26 * u)
        lh = line_height(body)
        block = line_height(big) + 40 * u + lh * len(lines)
        y = (H - block) / 2
        p = (t - 0.2) / (self.hit - 0.2)
        if p > 0:
            landed = t - self.hit
            pop = 1 + 0.25 * (1 - ease_out(landed / 0.35)) if landed >= 0 else 1.0
            d.text((W / 2, y + line_height(big) / 2), count_up(value, p), font=font(HEAD_FONT, big.size * pop),
                   fill=mix(TEXT, GOLD, ease(landed / 0.2)), anchor="mm")
        y += line_height(big) + 10 * u
        bar = W * 0.3 * ease_out(max(0.0, p))
        if bar > 1:
            d.rounded_rectangle((W / 2 - bar / 2, y, W / 2 + bar / 2, y + 12 * u), radius=6 * u, fill=self.accent)
        y += 30 * u
        fade = ease(t / 0.45)
        for line in lines:
            d.text((W / 2, y), line, font=body, fill=mix(BG, TEXT, fade), anchor="ma")
            y += lh
        return self.done(img)


class Versus(Visual):
    """Two sides, sliding in from the left and the right (the right one when the line says its number)."""

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        said = self.said_at((spec.get("right") or {}).get("value"))
        self.right_at = max(0.5, said) if said is not None else 0.5
        self.still_after = self.right_at + 0.9

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        gap = 40 * u
        cw, ch = (W - 3 * gap) / 2, H * 0.72
        top = (H - ch) / 2
        for side, item in ((-1, self.spec.get("left") or {}), (1, self.spec.get("right") or {})):
            p = ease_out((t if side < 0 else t - self.right_at) / 0.6)
            if p <= 0:
                continue
            x0 = gap if side < 0 else 2 * gap + cw
            x0 += side * (1 - p) * W * 0.6
            color = self.accent if side < 0 else mix(GOLD, (200, 120, 40), 0.25)
            d.rounded_rectangle((x0, top, x0 + cw, top + ch), radius=28 * u, fill=mix(BG, color, 0.22),
                                outline=color, width=max(2, round(6 * u)))
            title_font, title_lines = fit(d, str(item.get("title") or ""), HEAD_FONT, cw * 0.84, 2, 60 * u, 28 * u)
            y = top + 50 * u
            for line in title_lines:
                d.text((x0 + cw / 2, y), line, font=title_font, fill=TEXT, anchor="ma")
                y += line_height(title_font)
            value = str(item.get("value") or "")
            if value:
                value_font, _ = fit(d, value, HEAD_FONT, cw * 0.84, 1, 110 * u, 36 * u)
                d.text((x0 + cw / 2, top + ch * 0.58), value, font=value_font, fill=GOLD, anchor="mm")
            note = str(item.get("note") or "")
            if note:
                note_font, note_lines = fit(d, note, BODY_FONT, cw * 0.84, 2, 34 * u, 20 * u)
                y = top + ch - 40 * u - line_height(note_font) * len(note_lines)
                for line in note_lines:
                    d.text((x0 + cw / 2, y), line, font=note_font, fill=MUTED, anchor="ma")
                    y += line_height(note_font)
        r = 62 * u * ease_out((t - self.right_at - 0.35) / 0.4)
        if r > 1:
            d.ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), fill=TEXT, outline=BG, width=max(2, round(8 * u)))
            d.text((W / 2, H / 2), "VS", font=font(HEAD_FONT, r * 0.8), fill=BG, anchor="mm")
        return self.done(img)


class Quote(Visual):
    """Someone's words (short, from a source), line by line while the line is said, with who said them."""

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        self.gap = min(0.5, max(0.22, (self.cues.get("line") or 0) * 0.45 / 4))  # between lines of the quote
        self.still_after = 0.15 + 6 * self.gap + 0.5

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        p = ease(t / 0.6)
        pad = 80 * u
        d.text((pad - 10 * u, pad - 60 * u), "“", font=font(HEAD_FONT, 260 * u), fill=mix(BG, self.accent, p))
        body, lines = fit(d, str(self.spec.get("text") or ""), BODY_FONT, W - 2 * pad, 6, 78 * u, 30 * u)
        lh = line_height(body)
        who = str(self.spec.get("who") or "")
        small = font(BODY_FONT, 34 * u)
        y = (H - lh * len(lines) - (line_height(small) + 30 * u if who else 0)) / 2 + 30 * u
        for j, line in enumerate(lines):
            q = ease((t - 0.15 - self.gap * j) / 0.35)
            d.text((pad + (1 - q) * 24 * u, y), line, font=body, fill=mix(BG, TEXT, q))
            y += lh
        if who:
            q = ease((t - 0.15 - self.gap * len(lines)) / 0.35)
            d.text((pad, y + 30 * u), f"— {who}", font=small, fill=mix(BG, GOLD, q))
        return self.done(img)


class ListCard(Visual):
    """A heading and up to three points, numbered, appearing one by one while the line is said."""

    def __init__(self, spec: dict, accent_color: tuple, cues: dict | None = None):
        super().__init__(spec, accent_color, cues)
        self.items = [str(i) for i in spec.get("items") or [] if str(i).strip()][:3]
        self.shows = self.spread(len(self.items), first=0.45, most=1.8)
        self.still_after = (self.shows[-1] if self.shows else 0) + 0.5

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        pad = 64 * u
        y = pad
        title = str(self.spec.get("title") or "")
        if title:
            head, lines = fit(d, title, HEAD_FONT, W - 2 * pad, 2, 58 * u, 30 * u)
            for line in lines:
                d.text((pad, y), line, font=head, fill=TEXT)
                y += line_height(head)
            y += 24 * u
        step = (H - y - pad) / max(1, len(self.items))
        for i, item in enumerate(self.items):
            p = ease_out((t - self.shows[i]) / 0.4)
            if p <= 0:
                continue
            cy = y + step * (i + 0.5)
            r = min(40 * u, step * 0.3)
            x = pad + (1 - p) * 50 * u
            d.ellipse((x, cy - r, x + 2 * r, cy + r), fill=mix(BG, self.accent, p))
            d.text((x + r, cy), str(i + 1), font=font(HEAD_FONT, r * 1.1), fill=mix(BG, TEXT, p), anchor="mm")
            body, lines = fit(d, item, BODY_FONT, W - x - 2 * r - 30 * u - pad, 2, min(48 * u, step * 0.32), 24 * u)
            lh = line_height(body)
            ty = cy - lh * len(lines) / 2
            for line in lines:
                d.text((x + 2 * r + 30 * u, ty), line, font=body, fill=mix(BG, TEXT, p))
                ty += lh
        return self.done(img)


class TitleCard(Visual):
    """The case's title (or the end card): a coloured kicker over big words."""

    still_after = 0.6

    def draw(self, t, size):
        img, d, u = self.canvas(size)
        W, H = img.size
        p = ease_out(t / 0.5)
        title = str(self.spec.get("title") or "").upper()
        kicker = str(self.spec.get("kicker") or "").upper()
        head, lines = fit(d, title, HEAD_FONT, W * 0.86, 3, min(120 * u, H * 0.2), 40 * u)
        lh = line_height(head)
        chip = font(BODY_FONT, 36 * u)
        chip_h = 64 * u if kicker else 0
        y = (H - lh * len(lines) - chip_h - 30 * u) / 2 + (1 - p) * 30 * u
        if kicker:
            tw = d.textlength(kicker, font=chip)
            d.rounded_rectangle((W / 2 - tw / 2 - 24 * u, y, W / 2 + tw / 2 + 24 * u, y + chip_h), radius=chip_h / 2,
                                fill=mix(BG, self.accent, p))
            d.text((W / 2, y + chip_h / 2), kicker, font=chip, fill=mix(BG, TEXT, p), anchor="mm")
            y += chip_h + 30 * u
        for line in lines:
            d.text((W / 2, y), line, font=head, fill=mix(BG, TEXT, p), anchor="ma")
            y += lh
        return self.done(img)


KINDS = {"photo": Photo, "chart": Chart, "map": Map, "timeline": Timeline, "stat": Stat, "versus": Versus,
         "quote": Quote, "list": ListCard, "title": TitleCard}


def make(spec: dict, accent_color: tuple, cues: dict | None = None) -> Visual:
    """The visual for a spec (following the words, given cues); anything unknown becomes a title card."""
    return KINDS.get(spec.get("kind"), TitleCard)(spec, accent_color, cues)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--spec", required=True, help="JSON file with one visual spec")
    parser.add_argument("--out", required=True)
    parser.add_argument("--t", type=float, default=3.0, help="seconds into the visual")
    parser.add_argument("--size", default="1080x920")
    parser.add_argument("--category", default="business", choices=list(ACCENTS))
    args = parser.parse_args()
    try:
        with open(args.spec, encoding="utf-8") as f:
            spec = json.load(f)
        w, h = (int(v) for v in args.size.lower().split("x"))
        img = make(spec, accent(args.category)).frame(args.t, (w, h))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        img.save(args.out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
