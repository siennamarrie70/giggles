"""
Sound for the series' films: beds under each shot (several may be layered) that cross-fade at the cuts, single sounds at
their moments, and the narrator's lines over them (your choice, 2026-11-15: a heavy, dark narrator tells each story; before,
the films were wordless). Small real sounds from assets/sfx (CC0, fetched by tools/sfx_fetch.py and listed in
assets/sfx/sfx.yaml), a few made here (_made: a monitor's beep, a knock); music only from the story's spark on (your
choice, 2026-11-15: silent until the turning point, then rising; music_track).

The narrator (voice=[{"wav", "at"}]: each line's reading and the second of the film it starts at) is warmed (VOICE_EQ: a
little more chest, less mud, a little presence), brought to VOICE_RMS as a whole (his lines keep their own light and
shade), evened out at known levels (VOICE_DYNAMICS: a compressor, then a peak limiter at VOICE_CEILING), and set in a dark
room: a short reverb (REVERB_*) made here from decaying noise, so nothing is downloaded. Without the limiter his voice
peaked 18 dB over its level, and the film's last limiter flattened a quarter of his syllables (and cost 1.5 LU) to
reach LUFS_VOICE (story #1, 2026-11-15). While he speaks the beds dip DUCK_BEDS and the single sounds DUCK_SPOTS, so every word stays clear
over rain; they come back up slowly after him (DUCK_RELEASE). A narrated film is set to LUFS_VOICE, a wordless one to
LUFS_TARGET.

Every sound is first brought to a standard level (a bed of over 5 s to BED_RMS, a single sound's loudest tenth of a second
to SPOT_RMS, its sharpest peaks rounded off), so a gain means the same for all of them. The finished mix is set to
LUFS_TARGET in one gain and limited so true peaks stay under TRUE_PEAK (a straight loudnorm pass let a splash reach +7.6 dB
on 2026-11-15).

A shot's sound:
  bed, bed_gain     one bed (a tag) and its gain in dB, or
  beds              [{"tag", "gain"}] several layered
  sounds            [{"tag", "at" (s into the shot), "gain" dB, "from" (s into the recording, optional),
                      "dur" (s, optional: loop the sound or cut it to this length, with a short fade)}]
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from common import ASSETS_DIR

SAMPLE_RATE = 48_000
LUFS_TARGET = -17.0  # a calm, wordless film: a little quieter than a talking video (-14 to -16)
TRUE_PEAK = -1.5
LEVEL = "acompressor=threshold=0.25:ratio=1.5:attack=8:release=250"  # barely there: the sounds tell the story
MAX_BOOST = 10.0  # dB at most: a scene of only room tone stays quiet instead of being pushed up into hiss
MAX_BOOST_VOICE = 16.0  # a narrated film: his voice carries it (the first one needed 11.5 dB to reach -15: 2026-11-15)
BED_RMS = 10 ** (-24 / 20)       # a bed at gain 0 dB: -24 dBFS RMS
SPOT_RMS = 10 ** (-16 / 20)      # a single sound at gain 0 dB: its loudest tenth of a second at -16 dBFS RMS
SPOT_PEAK_MAX = 10 ** (-3 / 20)  # ... but never peaking over -3 dBFS
SPOT_CLIP = 10 ** (-7 / 20)      # its peaks rounded off toward -7 dBFS (a soft clip)
SFX_DIR = ASSETS_DIR / "sfx"
XFADE = 0.6                   # beds cross-fade over this at a cut (s)
LUFS_VOICE = -16.0            # a narrated film: his voice keeps ~16 dB between its peaks and its loudness even evened out
                              # (story #1, 2026-11-15), so -15 cost 1.3 LU and flattened his peaks in the last limiter
VOICE_RMS = 10 ** (-18 / 20)  # the narrator's speech (its loud tenths of a second) at gain 0, before the mix's one gain
VOICE_EQ = ("highpass=f=60,equalizer=f=115:t=q:w=0.9:g=3,equalizer=f=320:t=q:w=1.2:g=-2.5,"
            "equalizer=f=3300:t=q:w=1.3:g=1.5")
VOICE_CEILING = 10 ** (-11 / 20)  # his peaks after the limiter: -11 dBFS, so the film's last limiter leaves his voice alone
VOICE_DYNAMICS = (f"acompressor=threshold={10 ** (-17 / 20):.4f}:ratio=3:attack=5:release=140:makeup=1,"
                  f"alimiter=limit={VOICE_CEILING:.4f}:attack=2:release=50:level=false")
DUCK_BEDS, DUCK_SPOTS = -10.0, -4.0  # dB the beds and the single sounds dip while he speaks
DUCK_ATTACK, DUCK_RELEASE = 0.10, 0.70  # s: how fast they dip, and come back after him
MUSIC_DIR = ASSETS_DIR / "music"
MUSIC_RMS = 10 ** (-23 / 20)  # a track at gain 0 dB: its loud passages at -23 dBFS RMS (under his voice at -18)
DUCK_MUSIC = -6.0             # dB the music dips while he speaks
REVERB_SECONDS, REVERB_PREDELAY, REVERB_WET = 1.7, 0.026, -16.0  # the room: decay (RT60), the gap before it, its level (dB)


def ffmpeg_exe() -> str:
    import media

    return media.ffmpeg_exe()


def _rng(*seed) -> np.random.Generator:
    return np.random.default_rng(int.from_bytes(hashlib.md5(repr(seed).encode("utf-8")).digest()[:8], "little"))


def _made(tag: str) -> np.ndarray | None:
    """A few sounds made here rather than fetched (nothing to download or credit): a hospital monitor's beep, a knock
    on a door. At the standard level of a single sound."""
    sr = SAMPLE_RATE
    if tag == "monitor_beep":
        t = np.arange(int(0.12 * sr)) / sr
        env = np.minimum(1, t / 0.004) * np.exp(-np.maximum(0, t - 0.07) / 0.02)
        x = (np.sin(2 * np.pi * 960 * t) + 0.25 * np.sin(2 * np.pi * 1920 * t)) * env
    elif tag == "bubble_pop":   # a soft, round pop: a bubble coming (never a click)
        t = np.arange(int(0.09 * sr)) / sr
        f = 520 + 380 * np.minimum(1, t / 0.03)
        env = np.minimum(1, t / 0.006) * np.exp(-t / 0.028)
        x = np.sin(2 * np.pi * np.cumsum(f) / sr) * env
    elif tag == "door_knock":
        t = np.arange(int(0.16 * sr)) / sr
        r = _rng("knock")
        thump = np.sin(2 * np.pi * 95 * t) * np.exp(-t / 0.030) + 0.6 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.018)
        click = r.normal(0, 1, t.size) * np.exp(-t / 0.004) * 0.35
        x = thump + click
    else:
        return None
    x = x / max(float(np.abs(x).max()), 1e-9) * SPOT_RMS * 1.3
    return x.astype(np.float32)


@lru_cache(maxsize=64)
def sound(tag: str) -> np.ndarray:
    """A sound from assets/sfx by tag (or made here: _made), as 48 kHz mono float32 at the standard level (silence if
    there's none)."""
    made = _made(tag)
    if made is not None:
        return made
    files = [p for p in SFX_DIR.glob(f"{tag}.*") if p.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac")]
    if not files:
        print(f"  (no sound for {tag!r}; silent)", file=sys.stderr)
        return np.zeros(1, np.float32)
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(files[0]), "-f", "f32le", "-ac", "1", "-ar",
                          str(SAMPLE_RATE), "-"], capture_output=True, check=True, timeout=120).stdout
    s = np.frombuffer(raw, np.float32).copy()
    if s.size > 5 * SAMPLE_RATE:
        rms = float(np.sqrt(np.mean(s ** 2)))
        if rms > 1e-6:
            s *= BED_RMS / rms
    else:
        # a single sound by its loudest tenth of a second, not its peak: a click or a jingle peaks high but is 15 dB
        # quieter than an alarm of the same peak (2026-11-15: the slap and the keys vanished under the rain)
        w = SAMPLE_RATE // 10
        padded = np.concatenate([s, np.zeros(-s.size % w, np.float32)]) if s.size >= w else np.pad(s, (0, w - s.size))
        loudest = float(np.sqrt(np.mean(padded.reshape(-1, w) ** 2, axis=1)).max())
        peak = float(np.abs(s).max())
        if loudest > 1e-6:
            s *= min(SPOT_RMS / loudest, SPOT_PEAK_MAX / max(peak, 1e-9))
        # and its sharpest peaks rounded off (a soft clip ~9 dB over its loudness): a bell or a click can then sit loud in
        # the mix without the final limiter flattening it
        s = (SPOT_CLIP * np.tanh(s / SPOT_CLIP)).astype(np.float32)
    return s


def _db(gain: float) -> float:
    return 10 ** (float(gain) / 20)


def _bed_piece(bed: np.ndarray, length: int, seed) -> np.ndarray:
    """`length` samples of a bed: one stretch from a fixed random point if it's long enough, else overlapped copies (the
    beds fade in and out over a second, so the overlaps cross-fade)."""
    overlap = SAMPLE_RATE
    if bed.size >= length + 2 * overlap:
        start = int(_rng("bed", seed).integers(overlap, bed.size - length - overlap + 1))
        return bed[start:start + length].copy()
    out = np.zeros(length + bed.size, np.float32)
    pos = 0
    while pos < length:
        out[pos:pos + bed.size] += bed
        pos += max(1, bed.size - overlap)
    return out[:length]


def _fit(s: np.ndarray, dur: float) -> np.ndarray:
    """The sound looped (10 ms cross-fades) or cut to `dur` seconds, ending with a 15 ms fade."""
    n = max(1, int(dur * SAMPLE_RATE))
    if s.size >= n:
        out = s[:n].copy()
    else:
        xf = min(int(0.01 * SAMPLE_RATE), s.size // 4)
        out = np.zeros(n + s.size, np.float32)
        ramp_in = np.linspace(0, 1, xf, dtype=np.float32) if xf else None
        pos = 0
        while pos < n:
            piece = s.copy()
            if xf and pos:
                piece[:xf] *= ramp_in
                out[pos:pos + xf] *= ramp_in[::-1]
            out[pos:pos + piece.size] += piece
            pos += max(1, s.size - xf)
        out = out[:n]
    fade = min(out.size, int(0.015 * SAMPLE_RATE))
    out[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return out


def _impulse() -> np.ndarray:
    """A dark room's reverb: a few early reflections, then noise decaying to -60 dB over REVERB_SECONDS, its highs fading
    faster than its lows (a one-pole low-pass that closes as it decays). Fixed seed: the same room in every film."""
    rate = SAMPLE_RATE
    n = int((REVERB_SECONDS + REVERB_PREDELAY) * rate)
    r = _rng("room")
    t = np.arange(n, dtype=np.float32) / rate
    tail = r.normal(0, 1, n).astype(np.float32) * np.exp(-6.91 * t / REVERB_SECONDS).astype(np.float32)
    out = np.zeros(n, np.float32)
    y = 0.0
    for i in range(n):  # (n ~ 83,000: a fraction of a second)
        a = 0.35 + 0.6 * min(1.0, t[i] / REVERB_SECONDS)  # more smoothing later on: the tail darkens
        y = a * y + (1 - a) * tail[i]
        out[i] = y
    pre = int(REVERB_PREDELAY * rate)
    out[:pre] = 0
    for delay, gain in ((0.011, 0.5), (0.019, 0.35), (0.027, 0.3), (0.041, 0.22)):  # early reflections
        out[int(delay * rate)] += gain
    return (out / np.sqrt(np.sum(out ** 2))).astype(np.float32)


def _convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    size = 1 << int(np.ceil(np.log2(x.size + h.size)))
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)[:x.size + h.size - 1].astype(np.float32)


def _voice_line(path: str) -> np.ndarray:
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(path), "-af", VOICE_EQ, "-f", "f32le", "-ac", "1",
                          "-ar", str(SAMPLE_RATE), "-"], capture_output=True, check=True, timeout=120).stdout
    return np.frombuffer(raw, np.float32).copy()


def _dynamics(x: np.ndarray) -> np.ndarray:
    """His voice through VOICE_DYNAMICS (the compressor, then the limiter), the same length."""
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
                          "-af", VOICE_DYNAMICS, "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
                         input=x.astype(np.float32).tobytes(), capture_output=True, check=True, timeout=300).stdout
    y = np.frombuffer(raw, np.float32)
    return np.pad(y, (0, max(0, x.size - y.size)))[:x.size].copy()


def voice_track(voice: list[dict], n: int) -> tuple[np.ndarray, np.ndarray]:
    """The narrator's lines placed at their seconds (dry, and the room's reverb of them), n samples long."""
    lines = [(float(v["at"]), _voice_line(v["wav"])) for v in voice]
    w = SAMPLE_RATE // 10
    loud = []  # each line's loud tenths of a second: his level, whole lines' quiet gaps left out
    for _, x in lines:
        if x.size >= w:
            rms = np.sqrt(np.mean(x[:x.size // w * w].reshape(-1, w) ** 2, axis=1))
            loud += list(rms[rms > rms.max() * 0.3])
    level = float(np.sqrt(np.mean(np.square(loud)))) if loud else 0.0
    gain = VOICE_RMS / level if level > 1e-6 else 1.0
    dry, wet = np.zeros(n, np.float32), np.zeros(n, np.float32)
    spans = []
    for at, x in lines:
        i = int(at * SAMPLE_RATE)
        if i >= n:
            continue
        dry[i:i + x.size] += (x * gain)[:n - i]
        spans.append((i, min(n, i + x.size)))
    dry = _dynamics(dry)
    room = _impulse() * _db(REVERB_WET)
    for i, j in spans:  # (each line's room from the evened-out voice)
        y = _convolve(dry[i:j], room)
        wet[i:i + y.size] += y[:n - i]
    return dry, wet


def _ducking(dry: np.ndarray, depth_db: float) -> np.ndarray:
    """A gain for the sounds under his voice: depth_db while he speaks, eased in over DUCK_ATTACK and out over
    DUCK_RELEASE (computed on 10 ms frames, then spread over the samples)."""
    step = SAMPLE_RATE // 100
    frames = dry.size // step + 1
    x = np.pad(dry, (0, frames * step - dry.size))
    rms = np.sqrt(np.mean(x.reshape(frames, step) ** 2, axis=1))
    speaking = (rms > VOICE_RMS * 0.06).astype(np.float32)
    env = np.zeros(frames, np.float32)
    up, down = 1 - np.exp(-0.01 / DUCK_ATTACK), 1 - np.exp(-0.01 / DUCK_RELEASE)
    level = 0.0
    for k in range(frames):  # (a pass over ~24,000 frames)
        level += (speaking[k] - level) * (up if speaking[k] > level else down)
        env[k] = level
    gain_db = np.repeat(env, step)[:dry.size] * depth_db
    return (10 ** (gain_db / 20)).astype(np.float32)


@lru_cache(maxsize=4)
def _track(file: str) -> np.ndarray:
    """A music track (assets/music) as 48 kHz mono float32, its loud passages brought to MUSIC_RMS."""
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(MUSIC_DIR / file), "-f", "f32le", "-ac", "1", "-ar",
                          str(SAMPLE_RATE), "-"], capture_output=True, check=True, timeout=180).stdout
    x = np.frombuffer(raw, np.float32).copy()
    w = SAMPLE_RATE // 10
    rms = np.sqrt(np.mean(x[:x.size // w * w].reshape(-1, w) ** 2, axis=1)) if x.size >= w else np.zeros(1)
    loud = rms[rms >= np.percentile(rms, 50)] if rms.size else rms
    level = float(np.sqrt(np.mean(loud ** 2))) if loud.size else 0.0
    return x * (MUSIC_RMS / level) if level > 1e-6 else x


def music_track(spec: dict, n: int) -> np.ndarray:
    """The music, silent until spec["at"] (s), then the track (from spec["from"] s into it) fading in over spec["rise"] s
    and still swelling spec["swell"] dB over the next spec["swell_s"] s, at spec["gain"] dB; n samples long."""
    out = np.zeros(n, np.float32)
    i = int(float(spec.get("at", 0)) * SAMPLE_RATE)
    if i >= n:
        return out
    x = _track(spec["file"])[int(float(spec.get("from", 0)) * SAMPLE_RATE):]
    need = n - i
    if 0 < x.size < need:  # a track shorter than the stretch: it plays again, cross-fading over 3 s
        fade = min(3 * SAMPLE_RATE, x.size // 3)
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        out_x = x.copy()
        while out_x.size < need:
            joined = out_x[-fade:] * (1 - ramp) + x[:fade] * ramp
            out_x = np.concatenate([out_x[:-fade], joined, x[fade:]])
        x = out_x
    m = min(x.size, need)
    t = np.arange(m, dtype=np.float32) / SAMPLE_RATE
    rise = max(0.05, float(spec.get("rise", 4.0)))
    env = np.clip(t / rise, 0, 1) ** 2
    if spec.get("lift_at") is not None:   # low until the lift, then up to full, then the swell
        ta = t + i / SAMPLE_RATE
        u = np.clip((ta - float(spec["lift_at"])) / max(0.1, float(spec.get("lift", 6.0))), 0, 1)
        level = float(spec.get("low", 0.0)) * (1 - u * u * (3 - 2 * u))
        after = np.clip((ta - float(spec["lift_at"]) - float(spec.get("lift", 6.0))) / max(0.1, float(spec.get("swell_s", 10.0))),
                        0, 1)
        swell = level + float(spec.get("swell", 0.0)) * after
    else:
        swell = float(spec.get("swell", 0.0)) * np.clip((t - rise) / max(0.1, float(spec.get("swell_s", 10.0))), 0, 1)
    out[i:i + m] = x[:m] * env * (10 ** ((swell + float(spec.get("gain", 0.0))) / 20))
    return out


def mix(shots: list[dict], dest: Path, voice: list[dict] | None = None, music: dict | None = None) -> Path:
    """The film's sound track (AAC) for the shots, in order, and the narrator's lines (voice) over them. music: a track
    that comes in at a moment and rises (music_track), dipped under his voice."""
    total = sum(float(s["seconds"]) for s in shots)
    n = int((total + 1) * SAMPLE_RATE)
    track = np.zeros(n, np.float32)  # the beds
    spots = np.zeros(n, np.float32)  # the single sounds
    start = 0.0
    for k, shot in enumerate(shots):
        seconds = float(shot["seconds"])
        beds = list(shot.get("beds") or [])
        if shot.get("bed"):
            beds.append({"tag": shot["bed"], "gain": shot.get("bed_gain", -14)})
        for j, b in enumerate(beds):
            bed = sound(b["tag"])
            if bed.size <= SAMPLE_RATE:
                continue
            a = max(0.0, start - XFADE / 2)
            e = min(total, start + seconds + XFADE / 2)
            length = int((e - a) * SAMPLE_RATE)
            piece = _bed_piece(bed, length, (b["tag"], k, j)) * _db(b.get("gain", -14))
            ramp = min(length // 2, int(XFADE * SAMPLE_RATE))
            if ramp > 0:
                piece[:ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)
                piece[-ramp:] *= np.linspace(1, 0, ramp, dtype=np.float32)
            i = int(a * SAMPLE_RATE)
            track[i:i + length] += piece[:max(0, min(length, n - i))]
        for ev in shot.get("sounds") or []:
            s = sound(ev["tag"])
            skip = int(float(ev.get("from", 0)) * SAMPLE_RATE)
            if skip:
                s = s[skip:].copy()
                ramp = min(s.size, int(0.01 * SAMPLE_RATE))
                s[:ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)
            if ev.get("dur"):
                s = _fit(s, float(ev["dur"]))
            i = int((start + float(ev.get("at", 0))) * SAMPLE_RATE)
            if i >= n or s.size <= 1:
                continue
            part = s[:n - i] * _db(ev.get("gain", -8))
            spots[i:i + part.size] += part
        start += seconds
    tune = music_track(music, n) if music else np.zeros(n, np.float32)
    if voice:
        dry, wet = voice_track(voice, n)
        track = (track * _ducking(dry, DUCK_BEDS) + spots * _ducking(dry, DUCK_SPOTS) + tune * _ducking(dry, DUCK_MUSIC)
                 + dry + wet)
    else:
        track = track + spots + tune
    fade = int(1.2 * SAMPLE_RATE)  # the film ends softly
    end = int(total * SAMPLE_RATE)
    track[max(0, end - fade):end] *= np.linspace(1, 0, min(fade, end), dtype=np.float32)
    track[end:] = 0
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "mix.f32"
        track[:end].tofile(raw)
        ff = ffmpeg_exe()
        src = ["-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", str(raw)]
        probe = subprocess.run([ff, "-hide_banner", *src, "-af", f"{LEVEL},loudnorm=print_format=json", "-f", "null", "-"],
                               capture_output=True, text=True, timeout=300).stderr
        js = json.loads(probe[probe.rfind("{"):probe.rfind("}") + 1])
        measured = float(js["input_i"]) if js.get("input_i") not in (None, "-inf") else LUFS_TARGET
        # one gain to the target; the limiter then trims the rain's sharp drips (inaudibly: they last a few ms). Single
        # sounds can't be flattened by it: their peaks were rounded off at the source (sound()), which an alarm ringing
        # over quiet beds needed (2026-11-15: it came out no louder than the room). Measure a mix at full bandwidth: a bell
        # is mostly above 4 kHz, so an 8 kHz check hides it.
        gain = max(-20.0, min(MAX_BOOST_VOICE if voice else MAX_BOOST, (LUFS_VOICE if voice else LUFS_TARGET) - measured))
        limit = 10 ** ((TRUE_PEAK - (0.5 if voice else 1.5)) / 20)  # AAC adds up to ~1 dB between samples on sharp drips
        chain = f"{LEVEL},volume={gain:.2f}dB,alimiter=limit={limit:.3f}:attack=5:release=80:level=false"
        subprocess.run([ff, "-y", "-v", "error", *src, "-af", chain, "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(dest)],
                       check=True, timeout=300)
    return dest
