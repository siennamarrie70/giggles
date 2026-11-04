"""
Makes the Constructivist Montage look's scores, once, on this laptop (the cloud only ever plays the finished files in assets/music/montage):
six original machine ostinati at 120 BPM, each 100 s long, starting exactly on the beat so the cuts land on it. Sampled instruments, from the
free CC0 libraries in the Lemo-Opuscar toolbox (VSCO 2 CE and VCSL; about 700 MB, which can be deleted afterwards), played by that toolbox's
sampler. The way the parts are built follows its kino-montage style (MIT: see assets/fonts/NOTICE-montage.txt); the figures are this file's own.

Needs the toolbox's Python, not this project's:
    C:\\Users\\ayush\\lemo-opuscar\\.venv\\Scripts\\python.exe -I tools\\montage_scores.py [--only 1] [--lib C:\\Users\\ayush\\lemo-opuscar]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
BEAT = 0.5
BAR = 2.0
BARS = 50
SR_OUT = 44_100
TARGET_RMS = 0.14   # about -17 dBFS: all six sit at the same level, and the renderer sets the level under his voice
# (name, the machine figure in eighths, the step the middle goes up by, the rising figure on top)
SCORES = [
    ("ironworks", ["D3", "D3", "F3", "D3", "A2", "D3", "E3", "F3"], 5, ["D5", "D5", "F5", "E5", "D5", "A4"]),
    ("foundry", ["E3", "B2", "E3", "G3", "E3", "B2", "D3", "E3"], 3, ["E5", "G5", "G5", "F#5", "E5", "B4"]),
    ("assembly", ["C3", "G2", "C3", "Eb3", "C3", "G2", "Bb2", "C3"], 5, ["C5", "Eb5", "D5", "C5", "G4", "C5"]),
    ("girder", ["A2", "A2", "C3", "A2", "E3", "A2", "B2", "C3"], 2, ["A4", "C5", "E5", "D5", "C5", "A4"]),
    ("signal", ["G2", "D3", "G2", "Bb2", "G2", "D3", "F3", "G2"], 5, ["G4", "Bb4", "D5", "C5", "Bb4", "G4"]),
    ("furnace", ["F2", "F2", "Ab2", "F2", "C3", "F2", "G2", "Ab2"], 3, ["F4", "F4", "Ab4", "G4", "F4", "C4"]),
]


def compose(figure: list[str], step: int, top: list[str], S) -> list:
    """The score's events: a machine that starts at once, thins out and rebuilds so it never sits still, and comes home at the end."""
    events = []
    m = S.midi
    root = m(figure[0])

    def ostinato(t0, t1, tr=0, vel=0.6, bassoon=True, up=0):
        for i in range(int(round((t1 - t0) / (BEAT / 2)))):
            p = m(figure[i % 8]) + tr + 12 * up
            t = t0 + i * BEAT / 2
            events.append((t, "cellos_spic", p, 0.22, vel + 0.1 * (i % 4 == 0), -0.2))
            if bassoon and i % 2 == 0:
                events.append((t, "bassoon_stac", p + 12, 0.2, vel * 0.8, 0.25))

    def low(t0, t1, tr=0, vel=0.66):
        for k in range(int(round((t1 - t0) / BEAT))):
            t = t0 + k * BEAT
            events.append((t, "tuba_stac" if k % 2 == 0 else "trombone_stac", root - 12 + tr + (-5 if k % 4 == 2 else 0), 0.3, vel, 0.1))

    def taps(t0, t1, vel=0.3):
        for i in range(int(round((t1 - t0) / (BEAT / 4)))):
            events.append((t0 + i * BEAT / 4, "snare2", "taps" if i % 4 else "on", None, vel + 0.2 * (i % 8 == 4), 0.25))

    def pulse(t0, t1, vel=0.42):
        for k in range(int(round((t1 - t0) / BEAT))):
            events.append((t0 + k * BEAT, "contrabass_pizz", root - 12 if k % 2 == 0 else root - 5, 0.4, vel, 0.0))

    def figure_on_top(t0, tr=0, inst="trumpet_stac", vel=0.62):
        t = t0
        for p, d in zip(top, (BEAT / 2, BEAT / 2, BEAT, BEAT / 2, BEAT / 2, BEAT)):
            events.append((t, inst, m(p) + tr, d * 0.8, vel, 0.3))
            t += d

    def stab(t, tr=0, vel=0.78, inst="horn_stac"):
        for p in (root + 12, root + 15, root + 19):
            events.append((t, inst, p + tr, 0.3, vel, -0.15))

    def strike(t, vel=0.9):
        events.append((t, "gran_cassa", None, None, vel, 0))
        events.append((t, "timpani", root - 12, 1.2, vel, 0))
        events.append((t, "tuba", root - 24, 1.0, vel * 0.85, 0))

    def roll(t0, t1, tr=0):
        count = int((t1 - t0) / (BEAT / 8))
        for i in range(count):
            events.append((t0 + i * BEAT / 8, "timpani", root - 12 + tr, 0.1, 0.25 + 0.5 * i / max(1, count), 0))

    b = lambda n: n * BAR  # noqa: E731
    strike(0)
    ostinato(b(0), b(8), vel=0.55)
    low(b(1), b(8), vel=0.58)
    for k in range(8):
        events.append((b(k), "xylophone", m(top[k % len(top)]) + 12, 0.2, 0.42, 0.45))
    # 8-16: the full machine
    strike(b(8), 0.75)
    ostinato(b(8), b(16), vel=0.6)
    low(b(8), b(16))
    taps(b(8), b(16), 0.24)
    for k in range(8, 16, 2):
        stab(b(k), vel=0.72)
    # 16-24: up a step, the figure on top
    strike(b(16), 0.8)
    ostinato(b(16), b(24), tr=step, vel=0.58)
    low(b(16), b(24), tr=step)
    for k in range(16, 24, 2):
        figure_on_top(b(k), step)
    # 24-30: half the band
    ostinato(b(24), b(30), vel=0.45, bassoon=False)
    pulse(b(24), b(30))
    roll(b(29), b(30))
    # 30-40: the full machine again, an octave up in the middle
    strike(b(30), 0.85)
    ostinato(b(30), b(40), vel=0.6, up=1)
    ostinato(b(30), b(40), vel=0.52)
    low(b(30), b(40))
    taps(b(30), b(40), 0.28)
    for k in range(30, 40, 2):
        figure_on_top(b(k), 0, "horn_stac" if k % 4 else "trumpet_stac", 0.66)
    # 40-48: climbing, a step each two bars
    for n, k in enumerate(range(40, 48, 2)):
        lift = (0, 2, step, step + 2)[n]
        strike(b(k), 0.7 + 0.05 * n)
        ostinato(b(k), b(k + 2), tr=lift, vel=0.58 + 0.04 * n)
        low(b(k), b(k + 2), tr=lift, vel=0.62 + 0.03 * n)
        stab(b(k), lift, 0.8)
        taps(b(k), b(k + 2), 0.3 + 0.04 * n)
    # 48-50: home, so a Short that ran this long still lands
    strike(b(48), 0.95)
    ostinato(b(48), b(50), vel=0.6)
    low(b(48), b(50))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--lib", default=str(Path.home() / "lemo-opuscar"))
    parser.add_argument("--only", type=int)
    parser.add_argument("--ffmpeg", default=None)
    args = parser.parse_args()
    sys.path.insert(0, args.lib)
    import soundfile as sf
    import soxr
    from core.audio import sampler as S
    from core.audio.sfx import SR

    out_dir = HERE / "assets" / "music" / "montage"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = HERE / ".tmp" / "montage_scores"
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    for k, (name, figure, step, top) in enumerate(SCORES, start=1):
        if args.only and k != args.only:
            continue
        print(f"Score {k}: {name}", flush=True)
        S.seed(1930 + k)
        music = S.render(compose(figure, step, top, S), dur=BARS * BAR)
        music = S.room(music, size=0.3, mix=0.12)
        n = int(0.025 * SR)
        music[:n] *= np.linspace(0, 1, n)[:, None]
        music *= TARGET_RMS / max(1e-6, float(np.sqrt(np.mean(music ** 2))))
        music = np.clip(music, -0.98, 0.98)
        music = soxr.resample(music, SR, SR_OUT, quality="HQ")
        wav = work / f"{name}.wav"
        sf.write(wav, music, SR_OUT, subtype="PCM_16")
        dest = out_dir / f"{k:02d}_{name}.m4a"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)], check=True)
        wav.unlink()
        print(f"  {dest.name}: {dest.stat().st_size // 1024} KB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
