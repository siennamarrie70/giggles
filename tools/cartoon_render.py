"""
Agent 3's renderer: turns an episode (a setting, the cast, and beats with their voice lines and
mouth shapes) into a vertical 1080x1920 cartoon Short.

The lines play one after another with short pauses (a longer one before the punchline), then a
moment of silence for the reaction. Frames are drawn 12 times a second ("on twos", like hand-drawn
cartoons) and encoded at 24 fps; each is drawn at twice the size and shrunk, which smooths the
edges. Shots: "wide" shows everyone, "close" frames the speaker's face, and the reaction after the
punchline is always wide. The speaker's mouth follows Rhubarb's shapes; everyone blinks now and
then, listeners look at the speaker, bodies breathe and bounce while talking.
Captions: the hook stays on top; the spoken line appears below in short chunks.
Audio: the dialogue, plus a music track that dips under the voices, loudness-normalised.

Episode JSON (what Agent 3 hands over):
  {"setting": "office", "seed": 3, "hook": "...", "cast": [spec, ...],
   "beats": [{"speaker": 0, "line": "...", "emotion": "annoyed", "action": "talk", "camera": "wide",
              "listener_emotion": "neutral", "wav": "path", "seconds": 2.4, "cues": [{start, end, value}]}]}

Usage:
    python tools/cartoon_render.py --episode .tmp/episode.json --out .tmp/out/cartoon.mp4 [--music none]
"""

import argparse
import json
import math
import random
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from PIL import Image, ImageDraw

import puppet
import scene_draw
import short_render
from common import TMP_DIR, load_config

W, H = 1080, 1920
FPS, OUT_FPS = 12, 24  # drawings per second; frames per second in the file
SS = 2                 # drawn at twice the size, then shrunk
LEAD_IN, GAP, PUNCH_GAP, TAIL = 0.35, 0.28, 0.6, 1.5
SAMPLE_RATE = 24_000
RENDER_TIMEOUT_S = 600

ACTIONS = ("talk", "gesture", "shrug", "facepalm", "cross_arms", "think", "wave", "cheer", "phone", "mug", "walk_in")
ACTION_POSE = {"gesture": "point", "shrug": "shrug", "facepalm": "facepalm", "cross_arms": "cross", "think": "think",
               "wave": "wave", "cheer": "cheer", "phone": "phone", "mug": "mug"}
REST_POSE = {"office": "desk", "kitchen": "desk", "cafe": "desk"}  # elsewhere: arms down
OPEN_MOUTHS = {"C", "D", "E", "H"}
CLOSE_SCALE = 1.9


def _ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def chunks(line: str, max_words: int = 4, max_chars: int = 26) -> list[str]:
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
    if len(out) > 1 and len(out[-1].split()) == 1 and len(out[-2].split()) < max_words + 1:  # no lonely last word
        out[-2:] = [f"{out[-2]} {out[-1]}"]
    return out


class Episode:
    """Everything needed to draw any moment of the episode."""

    def __init__(self, ep: dict):
        self.setting = ep["setting"]
        self.seed = int(ep.get("seed", 0))
        self.cast = ep["cast"]
        self.beats = [dict(b) for b in ep["beats"]]
        n = len(self.cast)
        self.size = 1.0 if n == 2 else 0.86
        self.xs = [320, 760] if n == 2 else [205, 540, 875]
        seated = 80 if self.setting in scene_draw.SEATED else 0
        self.ys = [scene_draw.STAND_Y + puppet.HEIGHT_SHIFT[s["height"]] * self.size + seated for s in self.cast]
        self.rest = REST_POSE.get(self.setting, "down")

        t = LEAD_IN
        for i, beat in enumerate(self.beats):
            if i and i == len(self.beats) - 1:
                t += PUNCH_GAP - GAP
            beat["start"], beat["end"] = round(t, 3), round(t + beat["seconds"], 3)
            t = beat["end"] + GAP
        self.total = round(self.beats[-1]["end"] + TAIL, 2)

        # When each character enters (walk_in on their first line) and when they blink
        self.enter = {}
        for b in self.beats:
            if b.get("action") == "walk_in" and b["speaker"] not in self.enter:
                self.enter[b["speaker"]] = b["start"]
        self.blinks = []
        for i in range(n):
            rng, times, at = random.Random(self.seed * 31 + i), [], 0.0
            at = rng.uniform(0.5, 2.0)
            while at < self.total:
                times.append(at)
                at += rng.uniform(2.2, 4.8)
            self.blinks.append(times)

        self.hook = self._caption(ep.get("hook") or "", "top")
        self.subtitles = []  # (start, end, caption)
        for k, beat in enumerate(self.beats):
            parts = chunks(beat["line"])
            letters = sum(len(p) for p in parts) or 1
            done = 0
            next_start = self.beats[k + 1]["start"] if k + 1 < len(self.beats) else self.total
            for j, part in enumerate(parts):
                start = beat["start"] + beat["seconds"] * done / letters
                done += len(part)
                end = (beat["start"] + beat["seconds"] * done / letters if j + 1 < len(parts)
                       else min(beat["end"] + 0.3, next_start))
                self.subtitles.append((start, end, self._caption(part, "bottom")))
        self._backs = {}

    # -- captions -----------------------------------------------------------------------------

    @staticmethod
    def _caption(text: str, position: str):
        if not short_render.clean_text(text):
            return None
        img = short_render.caption_image(text, position)
        box = img.getbbox()
        return (img.crop(box), box[:2]) if box else None

    # -- the camera ---------------------------------------------------------------------------

    def wide(self) -> tuple:
        scale = 1.25 if len(self.cast) == 2 else 1.15
        return scale, 540 - 540 / scale, scene_draw.STAND_Y - 920 / scale

    def close(self, i: int) -> tuple:
        geo = puppet.Geo(self.cast[i])
        head_y = self.ys[i] + geo.hy * self.size
        x0 = self.xs[i] - 540 / CLOSE_SCALE
        x0 = min(max(x0, -150), scene_draw.WORLD_W + 150 - W / CLOSE_SCALE)
        return CLOSE_SCALE, x0, head_y - 820 / CLOSE_SCALE

    def cover_time(self) -> float:
        """The moment for the cover: the middle of the first wide shot with the whole cast in it."""
        everyone_in = max(self.enter.values(), default=0.0) + 0.8
        for beat in self.beats:
            if beat["start"] >= everyone_in - 0.8 and beat.get("camera") != "close":
                return max(everyone_in, (beat["start"] + beat["end"]) / 2)
        return max(everyone_in, self.beats[-1]["end"] + 0.5)  # the wide reaction shot at the end

    def beat_at(self, t: float) -> int:
        k = 0
        for i, b in enumerate(self.beats):
            if b["start"] <= t:
                k = i
        return k

    def camera_at(self, t: float, k: int) -> tuple:
        beat = self.beats[k]
        if t >= self.beats[-1]["end"] or beat.get("camera") != "close":
            return self.wide()
        return self.close(beat["speaker"])

    # -- the characters -----------------------------------------------------------------------

    def _mouth(self, beat: dict, t: float) -> str:
        at = t - beat["start"]
        for cue in beat.get("cues") or []:
            if cue["start"] <= at < cue["end"]:
                return cue["value"] if cue["value"] in puppet.MOUTHS else "B"
        return "X"

    def _target(self, i: int, k: int) -> int:
        """Who character i looks at: the speaker, or (when speaking) the one they're answering."""
        speaker = self.beats[k]["speaker"]
        if i != speaker:
            return speaker
        others = [b["speaker"] for b in self.beats[:k][::-1] + self.beats[k + 1:] if b["speaker"] != i]
        if others:
            return others[0]
        return min((j for j in range(len(self.cast)) if j != i), key=lambda j: abs(self.xs[j] - self.xs[i]))

    def state(self, i: int, t: float, k: int) -> tuple[dict | None, float, float]:
        """The rig state for character i at time t, and how far it's moved (dx, dy) from its spot."""
        beat = self.beats[k]
        dx = dy = 0.0
        entered = self.enter.get(i)
        if entered is not None and t < entered:
            return None, 0, 0
        speaking_beat = beat["speaker"] == i and t >= beat["start"]
        talking = speaking_beat and t < beat["end"]
        emotion = beat.get("emotion", "neutral") if beat["speaker"] == i else beat.get("listener_emotion", "neutral")
        mouth = self._mouth(beat, t) if talking else "X"
        action = beat.get("action", "talk") if speaking_beat else None
        if action == "talk" or action == "walk_in":
            pose = "gesture" if talking and int((t - beat["start"]) / 1.4) % 2 == 0 else self.rest
        elif action in ACTION_POSE:
            pose = ACTION_POSE[action]
        else:
            pose = "cross" if emotion == "annoyed" else self.rest
        target = self._target(i, k)
        toward = 1 if self.xs[target] > self.xs[i] else -1
        blink = any(b <= t < b + 0.14 for b in self.blinks[i])
        phase = i * 1.7
        dy += 2.5 * math.sin(2 * math.pi * t / 3.0 + phase)
        if talking and mouth in OPEN_MOUTHS:
            dy -= 3
        tilt = 2.2 * math.sin(2 * math.pi * 0.7 * t + phase) if talking else (3.0 if emotion == "smug" else 0.0)
        if entered is not None and t < entered + 0.7:  # walking in from the nearer edge
            p = (t - entered) / 0.7
            side = -1 if self.xs[i] < scene_draw.WORLD_W / 2 else 1
            dx += side * (1 - _ease(p)) * 620
            dy -= abs(math.sin(p * math.pi * 3)) * 14
        if action == "cheer" and t < beat["start"] + 0.45:
            dy -= math.sin(math.pi * (t - beat["start"]) / 0.45) * 40
        state = {"pose": pose, "emotion": emotion, "mouth": mouth, "blink": blink, "gaze": (toward * 0.85, 0.05),
                 "tilt": tilt, "toward": toward}
        return state, dx, dy

    # -- drawing ------------------------------------------------------------------------------

    def _back(self, cam: tuple) -> Image.Image:
        if cam not in self._backs:
            img = Image.new("RGB", (W * SS, H * SS), "white")
            scene_draw.draw_back(self._pen(ImageDraw.Draw(img), cam), self.setting, self.seed)
            self._backs[cam] = img
        return self._backs[cam]

    @staticmethod
    def _pen(draw: ImageDraw.ImageDraw, cam: tuple) -> puppet.Pen:
        scale, x0, y0 = cam
        s = SS * scale
        return puppet.Pen(draw, (s, 0, -s * x0, 0, s, -s * y0))

    def frame(self, t: float) -> Image.Image:
        k = self.beat_at(t)
        cam = self.camera_at(t, k)
        img = self._back(cam).copy()
        pen = self._pen(ImageDraw.Draw(img), cam)
        speaker = self.beats[k]["speaker"]
        for i in sorted(range(len(self.cast)), key=lambda j: j == speaker):  # the speaker in front
            state, dx, dy = self.state(i, t, k)
            if state:
                puppet.draw(pen.child(self.xs[i] + dx * self.size, self.ys[i] + dy * self.size, self.size), self.cast[i], state)
        scene_draw.draw_front(pen, self.setting, self.seed)
        out = img.reduce(SS)
        if self.hook:
            out.paste(self.hook[0], self.hook[1], self.hook[0])
        for start, end, caption in self.subtitles:
            if caption and start <= t < end:
                out.paste(caption[0], caption[1], caption[0])
        return out


def _dialogue_wav(ep: Episode, dest: Path) -> None:
    import numpy as np

    track = np.zeros(int(ep.total * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.int32)
    for beat in ep.beats:
        with wave.open(str(beat["wav"]), "rb") as w:
            if w.getframerate() != SAMPLE_RATE:
                raise RuntimeError(f"{beat['wav']}: expected {SAMPLE_RATE} Hz")
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.int32)
        at = int(beat["start"] * SAMPLE_RATE)
        track[at:at + len(pcm)] += pcm[:max(0, len(track) - at)]
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.clip(track, -32768, 32767).astype(np.int16).tobytes())


def render(episode: dict, out_path: Path | str, music: Path | None = None, volume: float = 1.0,
           cover_path: Path | str | None = None, progress=print) -> dict:
    """Draws and encodes the episode; returns its length, frame count and how long it took."""
    started = time.monotonic()
    ep = Episode(episode)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cartoon_", dir=TMP_DIR / "work"))
    dialogue = work / "dialogue.wav"
    _dialogue_wav(ep, dialogue)

    total = ep.total
    cmd = [short_render.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
           "-i", str(dialogue)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
    gain = 0.22 * volume
    audio = (f"[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={total:.2f}[d];"
             f"[d]asplit=2[d1][d2];"
             f"[2:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
             f"volume={gain:.3f},afade=t=in:st=0:d=0.8,afade=t=out:st={max(total - 1.2, 0):.2f}:d=1.2[m];"
             f"[m][d1]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=400[md];"
             f"[md][d2]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", audio, "-map", "0:v", "-map", "[aout]",
            "-r", str(OUT_FPS), "-c:v", "libx264", "-preset", "superfast", "-tune", "animation", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart", "-t", f"{total:.2f}", str(out)]

    frames = math.ceil(total * FPS)
    errors = work / "ffmpeg.log"
    cover_at = ep.cover_time()
    with open(errors, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        try:
            for n in range(frames):
                t = n / FPS
                img = ep.frame(t)
                if cover_path and abs(t - cover_at) < 0.5 / FPS:
                    img.resize((540, 960), Image.LANCZOS).save(cover_path, quality=88)
                proc.stdin.write(img.tobytes())
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
    parser.add_argument("--episode", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--music", default="auto", help="Track path, 'auto' (random from assets/music) or 'none'")
    args = parser.parse_args()
    try:
        with open(args.episode, encoding="utf-8") as f:
            episode = json.load(f)
        music = None if args.music == "none" else short_render.pick_music() if args.music == "auto" else Path(args.music)
        result = render(episode, args.out, music, load_config()["music"]["volume"])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
