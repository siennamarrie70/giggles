"""
Agent 4's renderer: turns a case (its two hosts and its lines, each with a voice recording, mouth
shapes, a shot and a visual) into a vertical 1080x1920 Short.

Shots:
  studio  both hosts big at the desk, the line's visual on the wall screen above them
  screen  the visual big under the band, both hosts at their desk below it (a light behind whoever
          is talking; the other one glances up at each new visual and nods at the numbers)
  close   the speaking host, close up (jokes, reactions, the twist); the visual stays as it was
The band on top always shows the case type and number and the case title. The spoken line appears
in short caption chunks that pop in as they're said, numbers in gold. A new visual pushes the old
one out with a whoosh, keeps zooming in slowly, and follows the words: numbers pop in as they're
said, lists and timelines fill in while the line is spoken (tools/infographics.py). When each word
is said comes from the line's length and the pauses in its mouth shapes. After the last line the
end card plays on the wall screen while the hosts wave.

The hosts move "on twos" (12 drawings a second, like hand-drawn cartoons); the visuals move at the
full 24 frames a second. Audio: the dialogue and the whooshes, plus a music track that dips under
the voices, loudness-normalised.

Case JSON (what Agent 4 hands over):
  {"category": "business", "case_no": 12, "case_title": "Why Nokia failed", "end_text": "...",
   "hosts": [presenter spec, co-host spec],
   "lines": [{"speaker": 0, "text": "...", "shot": "studio", "visual": {see tools/infographics.py},
              "emotion": "happy", "action": "talk", "listener_emotion": "neutral",
              "wav": "path", "seconds": 2.4, "cues": [{start, end, value}]}]}

Usage:
    python tools/case_render.py --case .tmp/case.json --out .tmp/out/case.mp4 [--music none]
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
from pathlib import Path

from PIL import Image, ImageDraw

import infographics
import puppet
import scene_draw
import short_render
from common import ASSETS_DIR, TMP_DIR, load_config, tmp_path

W, H = 1080, 1920
FPS, HOST_FPS = 24, 12
SS = 2
LEAD_IN, GAP, SAME_GAP, TAIL = 0.3, 0.22, 0.12, 2.2
SLIDE = 0.3            # a new visual slides in over this long
SAMPLE_RATE = 24_000
RENDER_TIMEOUT_S = 900
BAND_H = 330
PANEL_SIZE = (W, 760)  # the visual in the screen shot, under the band
PANEL_BOTTOM = BAND_H + PANEL_SIZE[1]
DESK_SCALE = 0.78      # the screen shot's desk, under the visual: the studio at this scale,
DESK_SHOULDER_Y = 1500  # a medium-height host's shoulders this far down the frame,
DESK_HOST_X = (270, 810)  # and the hosts this far across
SPOT_R = 230           # the light behind whoever is talking (studio units)
CLOSE_SCALE = 1.9
SFX_DIR = ASSETS_DIR / "sfx"
WHOOSH_GAIN, WHOOSH_SPACING = 0.45, 1.5

ACTIONS = ("talk", "point", "shrug", "facepalm", "cross_arms", "think", "wave", "cheer")
ACTION_POSE = {"point": "point", "shrug": "shrug", "facepalm": "facepalm", "cross_arms": "cross", "think": "think",
               "wave": "wave", "cheer": "cheer"}
SHOTS = ("studio", "screen", "close")
REST_POSE = "desk"
OPEN_MOUTHS = {"C", "D", "E", "H"}
CATEGORY_NAMES = {"business": "Business", "economy": "Economy", "trending": "In the news", "history": "History",
                  "mythology": "Mythology"}
# where captions sit: centre x, widest line, bottom edge (clear of the Shorts buttons), highest top edge
CAPTION_LAYOUT = {"studio": (540, 900, 1395, 1060), "close": (540, 900, 1395, 1060),
                  "screen": (540, 960, 1240, PANEL_BOTTOM + 16)}
CAPTION_SIZE = 74
CAPTION_POP = 0.12     # a caption lands this much bigger and settles over this long
NUMBERISH = re.compile(r"\d")
PAUSE = {",": 3, ";": 4, ":": 4, ".": 5, "?": 5, "!": 5}  # room for the pause after these, in letters
QUIET = 0.12           # a stretch of resting mouth this long is a pause between phrases


def _ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def _letters(word: str) -> int:
    """About how many letters it takes to say the word: numbers are said in words ("33%", thirty-three percent)."""
    plain = re.sub(r"\W", "", word)
    digits = sum(ch.isdigit() for ch in plain)
    return len(plain) + 3 * digits + (7 if digits and re.search(r"[%$€£₹¥]", word) else 0)


def word_times(text: str, seconds: float, cues: list | None = None) -> list[float]:
    """When each word of a spoken line starts, in seconds into the line. Words take time by their length; where
    the mouth shapes show as many pauses as the line has commas and full stops, each phrase fits between them."""
    words = text.split()
    if not words:
        return []
    weight = [_letters(w) + 1 for w in words]
    breaks = [i for i, w in enumerate(words[:-1]) if w[-1] in PAUSE]  # a phrase ends with these words
    quiet = [(c["start"], c["end"]) for c in cues or [] if c.get("value") == "X"
             and c["end"] - c["start"] >= QUIET and c["start"] > 0.05 and c["end"] < seconds - 0.05]
    if breaks and len(quiet) == len(breaks):
        bounds = [0.0] + [x for gap in quiet for x in gap] + [seconds]
        firsts = [0] + [b + 1 for b in breaks] + [len(words)]
        out = []
        for n in range(len(firsts) - 1):
            a, b = bounds[2 * n], bounds[2 * n + 1]
            phrase = range(firsts[n], firsts[n + 1])
            total = sum(weight[i] for i in phrase)
            at = a
            for i in phrase:
                out.append(at)
                at += (b - a) * weight[i] / total
        return out
    weight = [wt + (PAUSE.get(w[-1], 0) if i < len(words) - 1 else 0) for i, (wt, w) in enumerate(zip(weight, words))]
    total, at, out = sum(weight), 0.0, []
    for wt in weight:
        out.append(at)
        at += seconds * wt / total
    return out


def chunks(line: str, max_words: int = 3, max_chars: int = 20) -> list[str]:
    """A line split into short caption chunks, the way Shorts captions read."""
    out, current = [], []
    for word in line.split():
        trial = " ".join(current + [word])
        if current and (len(current) >= max_words or len(trial) > max_chars):
            out.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        out.append(" ".join(current))
    if (len(out) > 1 and len(out[-1].split()) == 1 and len(out[-2].split()) < max_words + 1
            and len(out[-2]) + len(out[-1]) < max_chars + 6):  # no lonely last word, if it still fits one line
        out[-2:] = [f"{out[-2]} {out[-1]}"]
    return out


def caption_image(text: str, layout: str) -> tuple[Image.Image, tuple[int, int]] | None:
    """A caption chunk: white with a black outline, words with numbers in gold; cropped, with its position."""
    text = short_render.clean_text(text)
    if not text:
        return None
    cx, max_w, bottom, top = CAPTION_LAYOUT[layout]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    size = CAPTION_SIZE
    while size > CAPTION_SIZE - 14 and probe.textlength(text, font=infographics.font(infographics.HEAD_FONT, size)) > max_w:
        size -= 4  # one line if it fits a little smaller,
    if probe.textlength(text, font=infographics.font(infographics.HEAD_FONT, size)) > max_w:
        size = CAPTION_SIZE  # else two lines, as big as fit between the top and bottom edges
    while True:
        fnt = infographics.font(infographics.HEAD_FONT, size)
        lines = infographics.wrap(probe, text, fnt, max_w)
        lh = infographics.line_height(fnt) * 1.02
        if (len(lines) <= 2 and bottom - lh * len(lines) - size // 9 >= top) or size <= 44:
            break
        size -= 4
    stroke = max(5, size // 9)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    space = d.textlength(" ", font=fnt)
    y = bottom - lh * len(lines)
    for line in lines:
        words = line.split()
        x = cx - d.textlength(line, font=fnt) / 2
        for word in words:
            fill = infographics.GOLD if NUMBERISH.search(word) else (255, 255, 255)
            d.text((x, y), word, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
            x += d.textlength(word, font=fnt) + space
        y += lh
    box = img.getbbox()
    return (img.crop(box), box[:2]) if box else None


class Case:
    """Everything needed to draw any moment of the case."""

    def __init__(self, case: dict):
        self.category = case.get("category") or "business"
        self.colors = scene_draw.colors(self.category)
        self.accent = self.colors["accent"]
        self.hosts = case["hosts"]
        self.title = str(case.get("case_title") or "")
        self.lines = [dict(line) for line in case["lines"]]
        if not self.lines:
            raise ValueError("a case needs at least one line")
        self.xs = list(scene_draw.HOST_X)
        self.ys = [scene_draw.SHOULDER_Y + puppet.HEIGHT_SHIFT[h["height"]] * scene_draw.HOST_SIZE for h in self.hosts]

        x0 = W / 2 - W / 2 / DESK_SCALE  # the screen shot's desk: a camera on the studio, drawn under the visual
        y0 = scene_draw.SHOULDER_Y - DESK_SHOULDER_Y / DESK_SCALE
        self.desk_cam = (DESK_SCALE, x0, y0 + PANEL_BOTTOM / DESK_SCALE)
        self.desk_xs = [x / DESK_SCALE + x0 for x in DESK_HOST_X]

        t = LEAD_IN
        for i, line in enumerate(self.lines):
            if i:
                t += SAME_GAP if line["speaker"] == self.lines[i - 1]["speaker"] else GAP
            line["start"], line["end"] = round(t, 3), round(t + line["seconds"], 3)
            t = line["end"]
            line["words"] = [(line["start"] + at, word) for at, word in
                             zip(word_times(line["text"], line["seconds"], line.get("cues")), line["text"].split())]
        self.outro = round(t + 0.3, 3)
        self.total = round(t + TAIL, 2)
        self.numbers = [at for line in self.lines for at, word in line["words"] if NUMBERISH.search(word)]

        # Visual segments: lines in a row with the same visual share one, so its animation runs on. A close-up
        # doesn't show the screen, so the visual stays as it was.
        title_card = {"kind": "title", "kicker": CATEGORY_NAMES.get(self.category, ""), "title": self.title}
        runs, last = [], None  # [start, end, spec, first line]
        for i, line in enumerate(self.lines):
            if line.get("shot") == "close" and runs:
                continue
            spec = line.get("visual") or title_card
            key = json.dumps(spec, sort_keys=True)
            if key != last:
                start = 0.0 if i == 0 else max(0.0, line["start"] - 0.08)
                if runs:
                    runs[-1][1] = start
                runs.append([start, None, spec, i])
                last = key
        runs[-1][1] = self.outro
        self.segments = []
        for start, end, spec, i in runs:
            cues = {"line": self.lines[i]["end"] - start, "length": end - start,
                    "said": [[at - start, word] for line in self.lines for at, word in line["words"] if start <= at < end]}
            self.segments.append([start, end, infographics.make(spec, self.accent, cues)])
        end_card = {"kind": "title", "kicker": CATEGORY_NAMES.get(self.category, ""),
                    "title": case.get("end_text") or "A new case every day"}
        self.segments.append([self.outro, self.total + 1,
                              infographics.make(end_card, self.accent, {"length": self.total - self.outro})])
        self.cover_card = infographics.make({**title_card, "kicker": self._kicker(case)}, self.accent)
        self.whooshes = []
        for start, _, _ in self.segments[1:]:
            if not self.whooshes or start - self.whooshes[-1] >= WHOOSH_SPACING:
                self.whooshes.append(start)

        self.blinks = []
        for i in range(len(self.hosts)):
            rng, times = random.Random(31 * (i + 1) + len(self.lines)), []
            at = rng.uniform(0.5, 2.0)
            while at < self.total:
                times.append(at)
                at += rng.uniform(2.2, 4.8)
            self.blinks.append(times)

        self.band = self._band(case)
        self.captions = []  # (start, end, text)
        for k, line in enumerate(self.lines):
            parts = chunks(line["text"])
            next_start = self.lines[k + 1]["start"] if k + 1 < len(self.lines) else self.outro
            n = 0
            for j, part in enumerate(parts):
                start = line["words"][n][0]
                n += len(part.split())
                end = line["words"][n][0] if j + 1 < len(parts) else min(line["end"] + 0.25, next_start)
                self.captions.append((start, end, part))
        self._caption_cache, self._backs, self._desk_drawn, self._shot_drawn = {}, {}, (None, None), (None, None)

    # -- the band on top ----------------------------------------------------------------------

    def _kicker(self, case: dict) -> str:
        name = CATEGORY_NAMES.get(self.category, self.category.title())
        return f"{name} · Case file {case['case_no']}" if case.get("case_no") else name

    def _band(self, case: dict) -> Image.Image:
        img = Image.new("RGBA", (W, BAND_H), (*puppet.WHITE, 255))
        d = ImageDraw.Draw(img)
        kicker = self._kicker(case).upper()
        chip = infographics.font(infographics.BODY_FONT, 30)
        tw = d.textlength(kicker, font=chip)
        d.rounded_rectangle((W / 2 - tw / 2 - 22, 104, W / 2 + tw / 2 + 22, 152), radius=24, fill=self.accent)
        d.text((W / 2, 128), kicker, font=chip, fill=(255, 255, 255), anchor="mm")
        head, lines = infographics.fit(d, self.title.upper(), infographics.HEAD_FONT, 980, 2, 70, 40)
        lh = infographics.line_height(head)
        y = 170 + (2 - len(lines)) * lh / 2 * 0.6
        for line in lines:
            d.text((W / 2, y), line, font=head, fill=puppet.INK, anchor="ma")
            y += lh
        d.rectangle((0, BAND_H - 8, W, BAND_H), fill=self.accent)
        return img

    # -- timing -------------------------------------------------------------------------------

    def line_at(self, t: float) -> int:
        k = 0
        for i, line in enumerate(self.lines):
            if line["start"] <= t:
                k = i
        return k

    def shot_at(self, t: float, k: int) -> str:
        if t >= self.outro:
            return "studio"
        shot = self.lines[k].get("shot")
        return shot if shot in SHOTS else "studio"

    def visual_frame(self, t: float, size: tuple[int, int]) -> Image.Image:
        n = next((i for i, (start, end, _) in enumerate(self.segments) if start <= t < end), len(self.segments) - 1)
        start, _, visual = self.segments[n]
        img = visual.frame(t - start, size)
        if n and t - start < SLIDE:  # the new visual pushes the old one out
            old_start, _, old = self.segments[n - 1]
            x = round(size[0] * (1 - _ease((t - start) / SLIDE)))
            if x > 0:
                both = Image.new("RGB", size)
                both.paste(old.frame(t - old_start, size).crop((size[0] - x, 0, size[0], size[1])), (0, 0))
                both.paste(img.crop((0, 0, size[0] - x, size[1])), (x, 0))
                return both
        return img

    # -- the hosts ----------------------------------------------------------------------------

    def _mouth(self, line: dict, t: float) -> str:
        at = t - line["start"]
        for cue in line.get("cues") or []:
            if cue["start"] <= at < cue["end"]:
                return cue["value"] if cue["value"] in puppet.MOUTHS else "B"
        return "X"

    def state(self, i: int, t: float, k: int) -> tuple[dict, float, float]:
        """Host i's rig state at time t, and how far they've moved (dx, dy) from their spot."""
        line = self.lines[k]
        speaker = line["speaker"]
        outro = t >= self.outro
        speaking_line = speaker == i and t >= line["start"] and not outro
        talking = speaking_line and t < line["end"]
        emotion = "happy" if outro else (line.get("emotion") if speaker == i else line.get("listener_emotion"))
        emotion = emotion if emotion in puppet.EMOTIONS else "neutral"
        mouth = self._mouth(line, t) if talking else "X"
        action = line.get("action", "talk") if speaking_line else None
        if outro:
            pose = "wave"
        elif action == "talk":
            pose = "gesture" if talking and int((t - line["start"]) / 1.4) % 2 == 0 else REST_POSE
        elif action in ACTION_POSE:
            pose = ACTION_POSE[action]
        else:
            pose = "cross" if emotion == "annoyed" else REST_POSE
        toward = 1 if self.xs[1 - i] > self.xs[i] else -1  # where the other host stands
        if speaker == i or outro:
            gaze = (0.0, 0.05)  # the speaker talks to the viewer
        else:
            segment_start = next((s for s, e, _ in self.segments if s <= t < e), 0.0)
            new_visual = t - segment_start < 1.2 and line.get("shot") in ("studio", "screen")
            gaze = (toward * 0.3, -0.9) if new_visual else (toward * 0.85, 0.05)  # a glance up at the screen
        blink = any(b <= t < b + 0.14 for b in self.blinks[i])
        phase = i * 1.7
        dy = 2.5 * math.sin(2 * math.pi * t / 3.0 + phase)
        if talking and mouth in OPEN_MOUTHS:
            dy -= 3
        if speaker != i and not outro:  # the listener nods at the numbers
            dy += sum(7 * math.sin(math.pi * (t - at) / 0.4) for at in self.numbers if at <= t < at + 0.4)
        tilt = 2.2 * math.sin(2 * math.pi * 0.7 * t + phase) if talking else (3.0 if emotion == "smug" else 0.0)
        if action == "cheer" and t < line["start"] + 0.45:
            dy -= math.sin(math.pi * (t - line["start"]) / 0.45) * 40
        state = {"pose": pose, "emotion": emotion, "mouth": mouth, "blink": blink, "gaze": gaze, "tilt": tilt,
                 "toward": toward}
        return state, 0.0, dy

    # -- drawing ------------------------------------------------------------------------------

    def close_cam(self, i: int) -> tuple:
        geo = puppet.Geo(self.hosts[i])
        head_y = self.ys[i] + geo.hy * scene_draw.HOST_SIZE
        x0 = self.xs[i] - 540 / CLOSE_SCALE
        x0 = min(max(x0, -150), scene_draw.WORLD_W + 150 - W / CLOSE_SCALE)
        return CLOSE_SCALE, x0, head_y - 900 / CLOSE_SCALE

    @staticmethod
    def _pen(draw: ImageDraw.ImageDraw, cam: tuple) -> puppet.Pen:
        scale, x0, y0 = cam
        s = SS * scale
        return puppet.Pen(draw, (s, 0, -s * x0, 0, s, -s * y0))

    def _back(self, cam: tuple, size: tuple[int, int] = (W, H), screen: bool = True) -> Image.Image:
        key = (cam, size, screen)
        if key not in self._backs:
            img = Image.new("RGB", (size[0] * SS, size[1] * SS), "white")
            scene_draw.draw_back(self._pen(ImageDraw.Draw(img), cam), self.category, screen=screen)
            self._backs[key] = img
        return self._backs[key]

    def _hosts(self, pen: puppet.Pen, t: float, k: int, xs: list[float]) -> None:
        """Both hosts, the speaker in front; whoever starts a line bobs up a little."""
        line = self.lines[k]
        speaker = line["speaker"]
        for i in sorted(range(len(self.hosts)), key=lambda j: j == speaker):
            state, dx, dy = self.state(i, t, k)
            size = scene_draw.HOST_SIZE
            if i == speaker and line["start"] <= t < line["start"] + 0.3 and t < self.outro:
                size *= 1 + 0.05 * math.sin(math.pi * (t - line["start"]) / 0.3)
            puppet.draw(pen.child(xs[i] + dx, self.ys[i] + dy * scene_draw.HOST_SIZE, size), self.hosts[i], state)

    def _set(self, t: float, k: int, cam: tuple, screen: Image.Image | None) -> Image.Image:
        """The studio through a camera: the wall (with the screen's picture), the hosts, the desk."""
        img = self._back(cam).copy()
        if screen is not None:
            x0, y0, x1, y1 = scene_draw.SCREEN
            img.paste(screen.resize(((x1 - x0) * SS, (y1 - y0) * SS), Image.NEAREST), (x0 * SS, y0 * SS))
        pen = self._pen(ImageDraw.Draw(img), cam)
        self._hosts(pen, t, k, self.xs)
        scene_draw.draw_front(pen, self.category)
        return img.reduce(SS)

    def _shot(self, t: float, k: int, shot: str) -> Image.Image:
        """The studio (its screen left dark) or a close-up, drawn once per drawing of the hosts: the visual is
        pasted onto the screen afterwards, every frame (the hosts never reach up to it)."""
        if self._shot_drawn[0] != (t, k, shot):
            cam = self.close_cam(self.lines[k]["speaker"]) if shot == "close" else (1.0, 0.0, 0.0)
            self._shot_drawn = ((t, k, shot), self._set(t, k, cam, None))
        return self._shot_drawn[1]

    def _desk(self, t: float, k: int) -> Image.Image:
        """The screen shot's lower part: both hosts at their desk, a light behind whoever is talking."""
        if self._desk_drawn[0] != (t, k):
            size = (W, H - PANEL_BOTTOM)
            img = self._back(self.desk_cam, size, screen=False).copy()
            pen = self._pen(ImageDraw.Draw(img), self.desk_cam)
            i = self.lines[k]["speaker"]
            if t < self.outro:
                pen.poly(puppet.ellipse(self.desk_xs[i], self.ys[i] - 110, SPOT_R, SPOT_R, 72), self.colors["spot"], False)
            self._hosts(pen, t, k, self.desk_xs)
            scene_draw.draw_front(pen, self.category)
            self._desk_drawn = ((t, k), img.reduce(SS))
        return self._desk_drawn[1]

    def _caption(self, text: str, layout: str):
        key = (text, layout)
        if key not in self._caption_cache:
            self._caption_cache[key] = caption_image(text, layout)
        return self._caption_cache[key]

    def frame(self, t: float) -> Image.Image:
        k = self.line_at(t)
        shot = self.shot_at(t, k)
        th = math.floor(t * HOST_FPS) / HOST_FPS  # the hosts move on twos
        if shot == "screen":
            out = Image.new("RGB", (W, H), infographics.BG)
            out.paste(self.visual_frame(t, PANEL_SIZE), (0, BAND_H))
            out.paste(self._desk(th, k), (0, PANEL_BOTTOM))
            ImageDraw.Draw(out).rectangle((0, PANEL_BOTTOM - 4, W, PANEL_BOTTOM + 4), fill=self.accent)
        elif shot == "close":
            out = self._shot(th, k, "close").copy()
        else:
            x0, y0, x1, y1 = scene_draw.SCREEN
            out = self._shot(th, k, "studio").copy()
            out.paste(self.visual_frame(t, (x1 - x0, y1 - y0)), (x0, y0))
        out.paste(self.band, (0, 0), self.band)
        for start, end, text in self.captions:
            if start <= t < end:
                cap = self._caption(text, shot)
                if cap:
                    img, (x, y) = cap
                    if t - start < CAPTION_POP:  # it lands a little big
                        s = 1 + 0.16 * (1 - (t - start) / CAPTION_POP)
                        big = img.resize((round(img.width * s), round(img.height * s)), Image.BILINEAR)
                        x, y, img = x - (big.width - img.width) // 2, y - (big.height - img.height) // 2, big
                    out.paste(img, (x, y), img)
                break
        return out

    def cover(self) -> Image.Image:
        """The cover: the studio with the case title on the screen, both hosts smiling."""
        x0, y0, x1, y1 = scene_draw.SCREEN
        saved = self.lines
        self.lines = [{**saved[0], "start": -10, "end": -9, "emotion": "happy", "listener_emotion": "happy",
                       "action": "talk", "shot": "studio"}]
        try:
            img = self._set(0.0, 0, (1.0, 0.0, 0.0), self.cover_card.frame(5.0, (x1 - x0, y1 - y0)))
        finally:
            self.lines = saved
        img.paste(self.band, (0, 0), self.band)
        return img


def _whoosh_pcm() -> list:
    """The whoosh sounds as 24 kHz mono samples (decoded once into .tmp/sfx)."""
    import numpy as np

    out = []
    for src in sorted(SFX_DIR.glob("whoosh*.mp3")):
        dest = tmp_path("sfx", src.stem + ".wav")
        if not dest.exists():
            subprocess.run([short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                            "-ac", "1", "-ar", str(SAMPLE_RATE), str(dest)], check=True, timeout=60)
        with wave.open(str(dest), "rb") as w:
            out.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.int32))
    return out


def _dialogue_wav(case: Case, dest: Path) -> None:
    """The voices at their start times, and a whoosh under each new visual."""
    import numpy as np

    track = np.zeros(int(case.total * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.int32)
    for line in case.lines:
        with wave.open(str(line["wav"]), "rb") as w:
            if w.getframerate() != SAMPLE_RATE:
                raise RuntimeError(f"{line['wav']}: expected {SAMPLE_RATE} Hz")
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.int32)
        at = int(line["start"] * SAMPLE_RATE)
        track[at:at + len(pcm)] += pcm[:max(0, len(track) - at)]
    sounds = _whoosh_pcm()
    for n, when in enumerate(case.whooshes):
        if not sounds:
            break
        pcm = (sounds[n % len(sounds)] * WHOOSH_GAIN).astype(np.int32)
        at = max(0, int((when - 0.05) * SAMPLE_RATE))
        track[at:at + len(pcm)] += pcm[:max(0, len(track) - at)]
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.clip(track, -32768, 32767).astype(np.int16).tobytes())


def render(case: dict, out_path: Path | str, music: Path | None = None, volume: float = 1.0,
           cover_path: Path | str | None = None, progress=print) -> dict:
    """Draws and encodes the case; returns its length, frame count and how long it took."""
    started = time.monotonic()
    c = Case(case)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="case_", dir=TMP_DIR / "work"))
    dialogue = work / "dialogue.wav"
    _dialogue_wav(c, dialogue)
    if cover_path:
        c.cover().resize((540, 960), Image.LANCZOS).save(cover_path, quality=88)

    total = c.total
    cmd = [short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
           "-i", str(dialogue)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    gain = 0.2 * volume
    audio = (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={total:.2f}[d];"
             f"[d]asplit=2[d1][d2];"
             f"[2:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
             f"volume={gain:.3f},afade=t=in:st=0:d=0.8,afade=t=out:st={max(total - 1.2, 0):.2f}:d=1.2[m];"
             f"[m][d1]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=400[md];"
             f"[md][d2]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", audio, "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "superfast", "-tune", "animation", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart", "-t", f"{total:.2f}", str(out)]

    frames = math.ceil(total * FPS)
    errors = work / "ffmpeg.log"
    with open(errors, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        try:
            for n in range(frames):
                proc.stdin.write(c.frame(n / FPS).tobytes())
                if n and n % (FPS * 10) == 0:
                    progress(f"Drawn {n // FPS} of {total:.0f} seconds")
            proc.stdin.close()
            proc.wait(timeout=RENDER_TIMEOUT_S)
        except Exception:
            proc.kill()
            raise
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {errors.read_text(encoding='utf-8', errors='replace')[-1500:]}")
    for item in work.iterdir():
        item.unlink()
    work.rmdir()
    return {"seconds": total, "frames": frames, "render_seconds": round(time.monotonic() - started, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--music", default="auto", help="Track path, 'auto' (random from assets/music) or 'none'")
    parser.add_argument("--cover", help="also save the cover image here")
    args = parser.parse_args()
    try:
        with open(args.case, encoding="utf-8") as f:
            case = json.load(f)
        music = None if args.music == "none" else short_render.pick_music() if args.music == "auto" else Path(args.music)
        result = render(case, args.out, music, load_config()["music"]["volume"], cover_path=args.cover)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
