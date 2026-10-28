"""
Whether a reading sounds like the Professor: its pitch and its timbre, set against the sample of his
voice you chose on the Host page (tools/narration.py sample(): that voice, in his persona, as deep as
set). The same named Gemini voice doesn't sound alike from every model: gemini-3.1-flash-tts-preview
can't take his persona, and its readings came out 4-5 semitones higher than his, a younger, lighter
man; you discarded #62, #64 and #66 and deleted #42 for it (2026-10-27). Measured that day against
his sample (Alnilam, 2 deeper: 121 Hz):

  his readings (gemini-3.8-flash-tts and -lite, 8 cases)   pitch -1.7 to +1.2 semitones, timbre 0.15-0.21
  gemini-3.1-flash-tts-preview (6 cases)                    pitch +4.0 to +5.0,           timbre 0.24-0.30
  the same, his persona written into its text (2 tries)     pitch +2.5 and +3.8,          timbre 0.31 and 0.42

So a reading is his when its pitch is within PITCH of his sample's and its timbre within TIMBRE. Pitch:
the median of a YIN pitch track over the voiced 10 ms frames. Timbre: how far the reading's average
MFCCs (20 coefficients over 40 mel bands, speech frames only) are from his sample's, in units of the
sample's own spread (the root mean square of coefficients 1-19's z-scores). numpy only, about a
second for a minute of speech.

Usage:
    python tools/voiceprint.py --wav .tmp/voices/12/narration.wav --like .tmp/voices/samples/Alnilam_d2_618a0214.wav
"""

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

PITCH = (-3.0, 2.0)     # semitones a reading's pitch may be below and above his sample's
TIMBRE = 0.26           # how far its timbre may be from his sample's
FMIN, FMAX = 60, 300    # Hz: a man's speaking voice
DIP = 0.15              # YIN: a period is the first dip of the normalized difference below this
SPEECH = 0.18           # a frame at least this loud against the voice's usual level (90th percentile) is speech
N_MFCC, N_MELS, MEL_RANGE = 20, 40, (50, 8000)


def _samples(wav: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{Path(wav).name}: a 16-bit WAV is needed")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return (x.reshape(-1, channels).mean(axis=1) if channels > 1 else x), rate


def _frames(x: np.ndarray, size: int, hop: int) -> np.ndarray:
    count = 1 + max(0, (len(x) - size) // hop)
    return x[np.arange(size)[None, :] + hop * np.arange(count)[:, None]]


def _speech(frames: np.ndarray) -> np.ndarray:
    rms = np.sqrt((frames ** 2).mean(axis=1))
    return rms > np.percentile(rms, 90) * SPEECH


def pitch(x: np.ndarray, rate: int) -> float:
    """The median pitch (Hz) of the voiced 40 ms frames, 10 ms apart (YIN); 0 if none is voiced."""
    size, hop = int(0.04 * rate), int(0.01 * rate)
    frames = _frames(x, size, hop)
    frames = frames[_speech(frames)]
    frames = frames - frames.mean(axis=1, keepdims=True)
    lo, hi = int(rate / FMAX), min(int(rate / FMIN), size - 1)
    spectrum = np.fft.rfft(frames, 2 * size, axis=1)
    lag = np.fft.irfft(spectrum * np.conj(spectrum), axis=1)[:, :hi + 1]  # autocorrelation
    power = np.cumsum(frames ** 2, axis=1)
    total = power[:, -1:]
    head = power[:, ::-1][:, :hi + 1]                                       # sum of x[j]^2, j < size - tau
    tail = total - np.concatenate([np.zeros_like(total), power[:, :hi]], axis=1)  # sum of x[j]^2, j >= tau
    diff = head + tail - 2 * lag                                            # YIN's difference function
    norm = diff[:, 1:] * np.arange(1, hi + 1) / np.maximum(np.cumsum(diff[:, 1:], axis=1), 1e-12)
    found = []
    for row in norm:  # (row[t - 1] is lag t)
        under = np.nonzero(row[lo - 1:] < DIP)[0]
        if len(under):
            t = under[0] + lo - 1
            while t + 1 < len(row) and row[t + 1] < row[t]:  # down to the bottom of the dip
                t += 1
            found.append(rate / (t + 1))
    return float(np.median(found)) if found else 0.0


def _mel_bank(rate: int, size: int) -> np.ndarray:
    def mel(hz):
        return 2595 * np.log10(1 + hz / 700)

    edges = 700 * (10 ** (np.linspace(mel(MEL_RANGE[0]), mel(min(MEL_RANGE[1], rate / 2)), N_MELS + 2) / 2595) - 1)
    bins = np.floor((size + 1) * edges / rate).astype(int)
    bank = np.zeros((N_MELS, size // 2 + 1))
    for m in range(N_MELS):
        a, b, c = bins[m], bins[m + 1], bins[m + 2]
        bank[m, a:b] = (np.arange(a, b) - a) / max(1, b - a)
        bank[m, b:c] = (c - np.arange(b, c)) / max(1, c - b)
    return bank


def timbre(x: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """The mean and spread of the MFCCs of the speech frames (about 21 ms, 10 ms apart)."""
    size = 1 << int(round(np.log2(0.0213 * rate)))
    frames = _frames(x, size, int(0.01 * rate))
    frames = frames[_speech(frames)] * np.hanning(size)
    bands = np.log(np.abs(np.fft.rfft(frames, size, axis=1)) ** 2 @ _mel_bank(rate, size).T + 1e-10)
    k = np.arange(N_MELS)
    coefficients = bands @ np.cos(np.pi / N_MELS * (k[:, None] + 0.5) * np.arange(N_MFCC)[None, :])
    return coefficients.mean(axis=0), coefficients.std(axis=0)


def measure(wav: Path | str) -> dict:
    """A reading's pitch (Hz) and timbre (its MFCCs' mean and spread)."""
    x, rate = _samples(Path(wav))
    mean, spread = timbre(x, rate)
    return {"pitch": round(pitch(x, rate), 1), "mfcc": mean.round(4).tolist(), "spread": spread.round(4).tolist(),
            "seconds": round(len(x) / rate, 1)}


def compare(reading: dict, his: dict) -> dict:
    """How a reading's measure differs from his sample's: semitones (+ higher), the timbre distance, whether it's his
    voice, and if not, why (in words)."""
    if not reading["pitch"] or not his["pitch"]:
        return {"pitch": None, "timbre": None, "his": False, "why": "no voice could be heard in it"}
    semitones = 12 * float(np.log2(reading["pitch"] / his["pitch"]))
    z = (np.array(reading["mfcc"][1:]) - np.array(his["mfcc"][1:])) / np.maximum(np.array(his["spread"][1:]), 1e-6)
    distance = float(np.sqrt((z ** 2).mean()))
    why = []
    if not PITCH[0] <= semitones <= PITCH[1]:
        why.append(f"{abs(semitones):.1f} semitones {'higher' if semitones > 0 else 'lower'} than his voice")
    if distance > TIMBRE:
        why.append(f"a different timbre ({distance:.2f}, his own stay under {TIMBRE:g})")
    return {"pitch": round(semitones, 2), "timbre": round(distance, 3), "his": not why, "why": "; ".join(why) or None}


def likeness(wav: Path | str, like: Path | str) -> dict:
    """compare() for a reading's WAV and his sample's WAV."""
    return compare(measure(wav), measure(like))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--wav", required=True, help="the reading")
    parser.add_argument("--like", help="his sample (without it: the reading's measure alone)")
    args = parser.parse_args()
    try:
        result = likeness(args.wav, args.like) if args.like else {k: v for k, v in measure(args.wav).items()
                                                                   if k not in ("mfcc", "spread")}
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
