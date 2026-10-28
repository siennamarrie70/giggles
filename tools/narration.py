"""
The Professor's voice for a documentary case. One Gemini text-to-speech call (free tier) reads the
whole script in the voice chosen on the dashboard's Host page, in his persona (STYLE: a wise
American professor with a deep, calm voice), each line with its own direction ("low and tense",
"faster, building"). faster-whisper then hears it back on this computer and gives every word's
time, so the captions, cuts, numbers and his mouth follow the voice exactly, and a read that
doesn't match the script is caught (and read again). Pauses longer than MAX_GAP are tightened to
KEEP_GAP: Gemini's narrators leave about a second between dramatic sentences (measured 2026-10-26),
too slow for Shorts. Only quiet audio is ever cut: where whisper heard no words but the voice is
speaking (it can skip a stretch), only the real pauses in it go. "deeper" lowers the voice 1 or 2
semitones without changing its timing (ffmpeg's rubberband filter, formants kept, so it still
sounds like him).

He keeps one voice, his own: only the models that take his persona and each line's direction read
him (TTS_MODELS), the next one when one fails (each has its own free quota), and one that failed for
another reason (network, busy) is asked last for FAILED_FOR. gemini-3.1-flash-tts-preview, which can't
take them, read the plain words in a lighter, younger voice 4-5 semitones higher, slowed to his pace
by software: you discarded those Shorts, and it was dropped on 2026-10-27. There's no other voice
either (the Kokoro backup was removed the same day: it didn't sound like him).

Each of his models gives DAILY readings a day on the free tier, on Google's day (it renews at
midnight Pacific time, RENEW_TZ): every reading is counted (note voice:used), a model whose readings
are used up isn't asked again that day, and when both are, narrate() raises VoiceUnavailable with
the time they renew and the case waits for it. A used-up model doesn't say so through the
Interactions API: it never answers (both models, a one-line read, 2026-10-27), so one that hangs is
asked once through generate_content, which says so at once (429, "per day").

Every reading is then measured against the Host page's sample of his voice (tools/voiceprint.py:
pitch and timbre); one that doesn't sound like him isn't used, and the next model reads the script.

Measured 2026-10-26: gemini-3.8-flash-tts read 48 words (25 s, untightened) in 14 s; whisper
small.en (int8, CPU) heard those 25 s in 3.7 s and matched the script at 0.94; base.en was slower
there and repeated a sentence that wasn't said. PyAV 19 and faster-whisper 1.2.1 disagree on
av.open(), so the audio is decoded by our ffmpeg and handed over as samples.

  narrate()  the case's narration: the WAV, its length, and each line's start, end and words

Usage:
    python tools/narration.py --text "In 2000, one company..." --text "Fourteen years later..." --out .tmp/out/n.wav
"""

import argparse
import base64
import difflib
import io
import json
import math
import re
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import db
import voiceprint
from common import env, load_config, tmp_path

SAMPLE_RATE = 24_000
TTS_MODELS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")  # his voice: both take his persona and directions
DAILY = 10                      # readings a day each gives on the free tier ("generate_content_free_tier_requests,
                                # limit: 10", 2026-10-27)
RENEW_TZ = ZoneInfo("America/Los_Angeles")  # Google's free quotas renew at midnight Pacific time
TTS_TIMEOUT_MS = 120_000
ASK_TIMEOUT_S = 60              # generate_content's one word, asked when a reading hangs
WHISPER_MODEL = "small.en"
WHISPER_REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"  # pinned (unchanged since 2023-11)
MAX_GAP, KEEP_GAP = 0.34, 0.2   # seconds: pauses longer than MAX_GAP are cut down to KEEP_GAP
LEAD, TAIL = 0.06, 0.25         # silence kept before the first word and after the last
FRAME = 0.01                    # seconds: loudness is measured in steps this long
SPEECH_DB, PAUSE_DB = 20, 40    # within 20 dB of the voice's usual level is speech; 40 dB below it, a pause
MISSED = 0.3                    # seconds of speech inside a "pause" that mean whisper missed words there
MIN_MATCH = 0.85                # how closely what's heard must match the script
FAILED_FOR = 30 * 60            # seconds a model that failed is asked last (a busy model tends to stay busy)
# A line the Reviewer found rushed is read again "slowly", but Gemini doesn't always hear it (#52 came back at 3.7
# words a second, 2026-10-27): one still faster than SLOW_LINE is slowed on its own (pitch kept), gently:
SLOW_LINE = 3.0                 # words a second (the Reviewer's limit is 3.3)
PACED_WORDS = 6                 # shorter lines aren't paced (as the Reviewer)
LEAST_TEMPO = 0.85              # never slowed more than this (a stronger stretch smears his voice)
TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|%")
STYLE = ("A wise, highly intelligent American professor in his sixties: a deep, low, resonant voice, calm and "
         "measured, never rushed; a master storyteller who draws you in.")
VOICE = "Charon"
# Gemini's male voices that suit him, the deepest-sounding first (Gemini's own one-word labels). Measured
# 2026-10-26 with STYLE: Orus 118 Hz, Charon 119, Alnilam 121, Sadaltager 123, Algenib 124, Iapetus 130.
VOICES = {"Charon": "Informative", "Alnilam": "Firm", "Orus": "Firm", "Sadaltager": "Knowledgeable",
          "Algenib": "Gravelly", "Iapetus": "Clear", "Rasalgethi": "Informative", "Schedar": "Even",
          "Algieba": "Smooth", "Enceladus": "Breathy", "Umbriel": "Easy-going"}
SAMPLE_LINES = [  # what the Host page's samples say
    {"text": "In the year 2000, one company sold almost every second phone on Earth.", "direction": "low, intrigued"},
    {"text": "Fourteen years later, it sold its phone business for a fraction of what it had once been worth.",
     "direction": "slower, heavier"},
    {"text": "So what went wrong? The answer was hiding in plain sight.", "direction": "quiet, drawing you in"},
]


class VoiceUnavailable(RuntimeError):
    """None of his voice's models could read the script in his voice now: the case waits. `until`: when they're
    back, if their free readings for today are used up (else None: a failure that passes)."""

    def __init__(self, message: str, until: str | None = None):
        super().__init__(message)
        self.until = until


class _UsedUp(Exception):
    """The model's free readings for today are used up."""


_whisper = None
_whisper_lock = threading.RLock()  # re-entrant: hear() holds it while _model() loads the model


def tokens(text: str) -> list[str]:
    """Words for matching what was said against the script: lower case, numbers and % on their own."""
    return TOKEN.findall(text.lower().replace(",", "").replace("’", "'").replace("'", ""))


# --- reading ------------------------------------------------------------------

def _health_path() -> Path:
    return tmp_path("voices", "models.json")


def _health() -> dict:
    """When each Gemini voice model last answered or failed ({model: {"ok", "at"}})."""
    try:
        return json.loads(_health_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _answered(model: str, ok: bool) -> None:
    health = _health()
    health[model] = {"ok": ok, "at": time.time()}
    _health_path().write_text(json.dumps(health), encoding="utf-8")


def ordered(models) -> list[str]:
    """The models to ask, in order, with any that failed in the last FAILED_FOR moved to the end."""
    health, now = _health(), time.time()
    failing = {m for m, h in health.items() if not h.get("ok") and now - float(h.get("at") or 0) < FAILED_FOR}
    return [m for m in models if m not in failing] + [m for m in models if m in failing]


def gemini_read(lines: list[dict], voice: str, style: str, model: str) -> bytes:
    """The whole script in one request: each line a turn with its own direction. Returns WAV bytes. A request
    that hasn't answered in TTS_TIMEOUT_MS is given up on (the SDK's own timeout only notices silence, and a
    busy service can keep a request open far longer: seen 2026-10-26)."""
    from google import genai
    from google.genai import types

    # attempts=1: no hidden SDK retries (a busy quota would stall for minutes); narrate() decides what's next.
    client = genai.Client(api_key=env("GEMINI_API_KEY", required=True), http_options=types.HttpOptions(
        timeout=TTS_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
    content = [{"type": "text", "text": line["text"],
                "annotations": [{"type": "speech_metadata",
                                 "style": "; ".join(s for s in (style, line.get("direction")) if s)}]}
               for line in lines]
    answer = {}

    def ask():
        try:
            answer["interaction"] = client.interactions.create(
                model=model, input=[{"type": "user_input", "content": content}], response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice}]})
        except Exception as e:
            answer["error"] = e

    # A daemon thread: a request that never answers is left behind, and doesn't keep the program from ending.
    asking = threading.Thread(target=ask, daemon=True)
    asking.start()
    asking.join(TTS_TIMEOUT_MS / 1000)
    if asking.is_alive():
        raise TimeoutError(f"{model} didn't answer in {TTS_TIMEOUT_MS // 1000} s")
    if "error" in answer:
        raise answer["error"]
    audio = answer["interaction"].output_audio
    data = base64.b64decode(audio.data)
    if data[:4] == b"RIFF":
        return data
    # Bare samples (16-bit mono, 24 kHz unless its type says otherwise; the dropped legacy model sent these): given a
    # WAV header, whisper heard such a reading word for word (2026-10-26); without one, ffmpeg couldn't read it at all.
    rate = re.search(r"rate=(\d+)", str(getattr(audio, "mime_type", None) or ""))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate.group(1)) if rate else SAMPLE_RATE)
        w.writeframes(data)
    return buf.getvalue()


# --- his readings for the day ----------------------------------------------------------

def _today() -> str:
    return datetime.now(RENEW_TZ).date().isoformat()


def renews_at() -> str:
    """When the free readings renew (the next midnight, Pacific time), in UTC (2026-10-28T07:00:00Z)."""
    midnight = datetime.combine(datetime.now(RENEW_TZ).date() + timedelta(days=1), datetime.min.time(), RENEW_TZ)
    return midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def used_today() -> dict[str, int]:
    """The readings each model has given today ({model: n}, note voice:used)."""
    note = db.latest_note("voice:used") or {}
    return {m: int(n) for m, n in (note.get("models") or {}).items()} if note.get("day") == _today() else {}


def left_today() -> dict[str, int]:
    """His models' free readings left today ({model: n})."""
    used = used_today()
    return {m: max(0, DAILY - used.get(m, 0)) for m in TTS_MODELS}


def _count(model: str, used_up: bool = False) -> None:
    """One more reading from `model` today (or all of them: it says they're used up)."""
    used = used_today()
    used[model] = DAILY if used_up else used.get(model, 0) + 1
    db.keep_note("voice:used", {"day": _today(), "models": used})


def _per_day(error: Exception) -> bool:
    said = str(error)
    return ("RESOURCE_EXHAUSTED" in said or "429" in said) and ("per day" in said.lower() or "PerDay" in said)


def _used_up(model: str, voice: str, error: Exception) -> bool:
    """Did `model` fail because its free readings for today are used up? A refusal says so ("per day"); a reading
    that hung may mean it too (the Interactions API never answers then), so generate_content is asked for one word,
    which says so at once (2026-10-27). If it reads the word instead, that's one more reading, and the hang passes."""
    if _per_day(error) or not isinstance(error, TimeoutError):
        return _per_day(error)
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=env("GEMINI_API_KEY", required=True), http_options=types.HttpOptions(
        timeout=ASK_TIMEOUT_S * 1000, retry_options=types.HttpRetryOptions(attempts=1)))
    answer = {}

    def ask():
        try:
            client.models.generate_content(model=model, contents="Say: yes.", config=types.GenerateContentConfig(
                response_modalities=["AUDIO"], speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
            answer["ok"] = True
        except Exception as e:
            answer["error"] = e

    asking = threading.Thread(target=ask, daemon=True)
    asking.start()
    asking.join(ASK_TIMEOUT_S + 5)
    if answer.get("ok"):
        _count(model)
    return "error" in answer and _per_day(answer["error"])


def _ask(lines: list[dict], voice: str, style: str, model: str) -> bytes:
    """One reading from `model`, counted against its day. Raises _UsedUp when its free readings for today are used."""
    if not left_today().get(model):
        raise _UsedUp(model)
    try:
        audio = gemini_read(lines, voice, style, model)
    except Exception as e:
        _answered(model, False)
        if _used_up(model, voice, e):
            _count(model, used_up=True)
            raise _UsedUp(model) from e
        raise
    _answered(model, True)
    _count(model)
    return audio


def his_models(voice_cfg: dict | None = None) -> list[str]:
    """The models that read him, the one in the settings (voice.model) first if it's one of them."""
    chosen = (voice_cfg or {}).get("model")
    return list(dict.fromkeys(([chosen] if chosen in TTS_MODELS else []) + list(TTS_MODELS)))


def his_voice(voice_cfg: dict | None = None, progress=print, make: bool = True) -> dict | None:
    """His voice's measure (tools/voiceprint.py), from the Host page's sample of it in these settings: the voice you
    chose, in his persona, as deep as set. Made now if there's none and `make` (one reading); else None."""
    voice_cfg = voice_cfg or load_config().get("voice") or {}
    name, style = voice_cfg.get("name") or VOICE, voice_cfg.get("style") or STYLE
    path = sample_path(name, int(voice_cfg.get("deeper") or 0), style)
    if not path.exists():
        if not make:
            return None
        try:
            sample(name, int(voice_cfg.get("deeper") or 0), style, progress)
        except Exception:  # (none left today: the reading is checked against it later, by the Reviewer)
            return None
    return voiceprint.measure(path)


def _pcm(wav_bytes: bytes):
    """16-bit mono samples at SAMPLE_RATE from WAV bytes (resampled by ffmpeg if needed)."""
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if rate == SAMPLE_RATE and channels == 1:
        return pcm
    return np.frombuffer(_ffmpeg_pcm(wav_bytes, SAMPLE_RATE), dtype=np.int16)


def _ffmpeg_pcm(wav_bytes: bytes, rate: int) -> bytes:
    import short_render

    return subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-i", "-", "-ac", "1", "-ar", str(rate),
                           "-f", "s16le", "-"], input=wav_bytes, capture_output=True, check=True, timeout=120).stdout


def _wav_bytes(pcm) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.astype("int16").tobytes())
    return buf.getvalue()


# --- hearing ------------------------------------------------------------------

def _model():
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel

            folder = str(tmp_path("models", "whisper", "x").parent)
            try:  # already downloaded: no need to ask Hugging Face (works offline too)
                _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=folder,
                                        local_files_only=True, revision=WHISPER_REVISION)
            except Exception:
                _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", download_root=folder,
                                        revision=WHISPER_REVISION)
    return _whisper


def hear(wav_bytes: bytes) -> list[tuple[float, float, str]]:
    """Every word heard, with its start and end (seconds). No hint from the script: given the script, whisper
    can skip whole stretches of speech it takes as already said (25 s of a 39-s reading, 2026-10-26)."""
    import numpy as np

    samples = np.frombuffer(_ffmpeg_pcm(wav_bytes, 16_000), dtype=np.int16).astype(np.float32) / 32768.0
    return hear_samples(samples)


def hear_samples(samples, prompt: str | None = None) -> list[tuple[float, float, str]]:
    """hear() for 16 kHz mono samples (floats from -1 to 1), with an optional hint for the spelling."""
    with _whisper_lock:  # one at a time: the model already uses every core
        segments, _ = _model().transcribe(samples, language="en", word_timestamps=True, beam_size=5,
                                          initial_prompt=prompt[-800:] if prompt else None,
                                          condition_on_previous_text=False)
        return [(float(w.start), float(w.end), w.word.strip()) for seg in segments for w in seg.words]


def align(lines: list[dict], heard: list[tuple[float, float, str]]) -> tuple[list[dict], float]:
    """Each script word's time, from the heard word it matches (in between: spread evenly), and how well the
    whole matches (0-1). Returns [{"start", "end", "words": [[seconds, word], ...]}] per line, and the match."""
    script_words = [(k, word) for k, line in enumerate(lines) for word in line["text"].split()]
    s_tok, s_owner = [], []  # script tokens and the script word each belongs to
    for n, (_, word) in enumerate(script_words):
        for tok in tokens(word) or ["_"]:
            s_tok.append(tok)
            s_owner.append(n)
    h_tok, h_time = [], []  # heard tokens and their (start, end)
    for start, end, word in heard:
        for tok in tokens(word):
            h_tok.append(tok)
            h_time.append((start, end))
    matcher = difflib.SequenceMatcher(a=s_tok, b=h_tok, autojunk=False)
    starts, ends = [None] * len(script_words), [None] * len(script_words)
    for a, b, size in matcher.get_matching_blocks():
        for i in range(size):
            n = s_owner[a + i]
            t0, t1 = h_time[b + i]
            starts[n] = t0 if starts[n] is None else min(starts[n], t0)
            ends[n] = t1 if ends[n] is None else max(ends[n], t1)
    total = heard[-1][1] if heard else 0.0
    _fill(starts, 0.0, total)
    _fill(ends, 0.0, total)
    out = []
    for k, line in enumerate(lines):
        idx = [n for n, (owner, _) in enumerate(script_words) if owner == k]
        words = [[round(starts[n], 3), script_words[n][1]] for n in idx]
        out.append({"start": round(starts[idx[0]], 3) if idx else 0.0, "end": round(max(ends[n] for n in idx), 3) if idx else 0.0,
                    "words": words})
    return out, matcher.ratio() if s_tok and h_tok else 0.0


def _fill(values: list, lo: float, hi: float) -> None:
    """Missing times (words not heard as written) spread evenly between their known neighbours."""
    n = len(values)
    i = 0
    while i < n:
        if values[i] is not None:
            i += 1
            continue
        j = i
        while j < n and values[j] is None:
            j += 1
        left = values[i - 1] if i > 0 else lo
        right = values[j] if j < n else hi
        for m in range(i, j):
            values[m] = left + (right - left) * (m - i + 1) / (j - i + 1)
        i = j


# --- pacing -------------------------------------------------------------------

def _levels(pcm):
    """The loudness of each FRAME, in dB against the voice's usual level (its 90th percentile)."""
    import numpy as np

    step = int(FRAME * SAMPLE_RATE)
    n = len(pcm) // step
    if not n:
        return np.zeros(0)
    frames = pcm[:n * step].astype(np.float32).reshape(n, step)
    level = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1.0)
    return level - np.percentile(level, 90)


def _spoken(level, a: float, b: float) -> bool:
    """Is someone speaking between a and b (seconds): a stretch of MISSED or longer at speech level?"""
    run = 0
    for k in range(int(a / FRAME), min(len(level), int(b / FRAME))):
        run = run + 1 if level[k] > -SPEECH_DB else 0
        if run * FRAME >= MISSED:
            return True
    return False


def _pauses(level, a: float, b: float, total: float) -> list[tuple[float, float]]:
    """The quiet stretches between a and b (seconds); one that reaches the last frame ends at `total`."""
    out, start = [], None
    end = min(len(level), int(math.ceil(b / FRAME)))
    for k in range(int(a / FRAME), end + 1):
        quiet = k < end and level[k] < -PAUSE_DB
        if quiet and start is None:
            start = k
        elif not quiet and start is not None:
            out.append((max(a, start * FRAME), total if k == len(level) else min(b, k * FRAME)))
            start = None
    return out


def tighten(pcm, heard: list[tuple[float, float, str]], keep_gap: float = KEEP_GAP):
    """Cuts long pauses down to keep_gap (and the silence before the first and after the last word); returns the
    new samples and a function mapping old times to new ones. A pause is where whisper heard no words, unless
    someone is speaking there (whisper missed those words): then only its quiet stretches go, so no speech is
    ever cut."""
    import numpy as np

    if not heard:
        return pcm, lambda t: t
    total = len(pcm) / SAMPLE_RATE
    longest = max(MAX_GAP, keep_gap)
    first, last = heard[0][0], heard[-1][1]
    # (from, to, silence kept at its start, at its end): before the first word, the long gaps, after the last
    spans = [(0.0, first, 0.0, LEAD)]
    spans += [(end, start, keep_gap / 2, keep_gap / 2)
              for (_, end, _), (start, _, _) in zip(heard, heard[1:]) if start - end > longest]
    spans.append((last, total, TAIL, 0.0))
    level = _levels(pcm)
    cuts = []  # (from, to) in seconds, removed
    for a, b, keep_a, keep_b in spans:
        if not _spoken(level, a, b):
            if b - a > keep_a + keep_b:
                cuts.append((a + keep_a, b - keep_b))
            continue
        for x, y in _pauses(level, a, b, total):
            keep = (0.0, LEAD) if x <= 0 else (TAIL, 0.0) if y >= total else (keep_gap / 2, keep_gap / 2)
            if y - x > (sum(keep) if x <= 0 or y >= total else longest):
                cuts.append((x + keep[0], y - keep[1]))
    fade = int(0.006 * SAMPLE_RATE)
    kept, at = [], 0
    for a, b in cuts:
        a_i, b_i = int(a * SAMPLE_RATE), int(b * SAMPLE_RATE)
        piece = pcm[at:a_i].astype(np.float32)
        if len(piece) > 2 * fade:  # tiny fades so the joins don't click
            piece[-fade:] *= np.linspace(1, 0, fade)
            piece[:fade] *= np.linspace(0, 1, fade) if at else 1
        kept.append(piece)
        at = b_i
    tail = pcm[at:].astype(np.float32)
    if len(tail) > fade and cuts:
        tail[:fade] *= np.linspace(0, 1, fade)
    kept.append(tail)
    out = np.clip(np.concatenate(kept), -32768, 32767).astype(np.int16)

    def moved(t: float) -> float:
        shift = 0.0
        for a, b in cuts:
            if t >= b:
                shift += b - a
            elif t > a:
                shift += t - a
        return max(0.0, t - shift)

    return out, moved


# --- the whole narration ---------------------------------------------------------

def narrate(lines: list[dict], out: Path, voice_cfg: dict | None = None, progress=print,
            keep_gap: float = KEEP_GAP) -> dict:
    """The narration of a case's lines ([{text, direction}]) into `out` (WAV, 24 kHz mono), its long pauses cut
    to keep_gap, in his voice: read by one of his models and measured like his sample. Returns {"wav", "seconds",
    "engine", "voice", "match", "deeper", "likeness", "lines": [{start, end, words}]}. Raises VoiceUnavailable when
    none of his models can read it now (with `until` when their free readings for today are used up)."""
    voice_cfg = voice_cfg or load_config().get("voice") or {}
    name, style = voice_cfg.get("name") or VOICE, voice_cfg.get("style") or STYLE
    deeper = int(voice_cfg.get("deeper") or 0)
    models = his_models(voice_cfg)
    his = his_voice(voice_cfg, progress, make=any(left_today().values()))
    attempts, used_up = [], set()
    for model in ordered(models):  # each has its own free quota
        try:
            if not left_today().get(model):
                raise _UsedUp(model)
            progress(f"Reading the script in {name}'s voice (Gemini)")
            started = time.monotonic()
            audio = _ask(lines, name, style, model)
            heard = hear(audio)
            timed, match = align(lines, heard)
            attempts.append(f"{model}: match {match:.2f} ({time.monotonic() - started:.0f} s)")
            if match < MIN_MATCH:
                progress(f"The read didn't match the script ({match:.2f}); trying again")
                continue
            spoken = _finish(audio, heard, lines, out, "gemini", f"{name} ({model})", match, deeper, keep_gap)
            if his:
                spoken["likeness"] = voiceprint.compare(voiceprint.measure(out), his)
                if not spoken["likeness"]["his"]:
                    attempts.append(f"{model}: not his voice ({spoken['likeness']['why']})")
                    progress(f"That reading doesn't sound like him ({spoken['likeness']['why']}); trying again")
                    continue
            return spoken
        except _UsedUp:
            used_up.add(model)
            attempts.append(f"{model}: today's {DAILY} free readings are used")
            progress(f"{model}'s free readings for today are used up")
        except Exception as e:  # network, a busy model, one that's gone: the next one
            attempts.append(f"{model}: {type(e).__name__}: {str(e)[:160]}")
            progress(f"Gemini's voice failed ({type(e).__name__}); trying the next way")
    raise VoiceUnavailable("; ".join(attempts), renews_at() if used_up >= set(models) else None)


def lower(pcm, semitones: int):
    """The voice `semitones` lower, same length and timing (rubberband, formants kept)."""
    import numpy as np

    import short_render

    if not semitones:
        return pcm
    raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
                          "-i", "-", "-af", f"rubberband=pitch={2 ** (-semitones / 12):.5f}:formant=preserved",
                          "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-"],
                         input=pcm.astype(np.int16).tobytes(), capture_output=True, check=True, timeout=120).stdout
    shifted = np.frombuffer(raw, dtype=np.int16)
    return np.pad(shifted, (0, max(0, len(pcm) - len(shifted))))[:len(pcm)]


def stretch(pcm, tempo: float):
    """The reading played `tempo` times as fast (below 1: slower), pitch kept (rubberband; "smooth" transients: the
    default "crisp" lowered a steady 150 Hz tone to 146, and whisper heard the smooth one best: 0.94, 2026-10-26)."""
    import numpy as np

    import short_render

    if tempo >= 0.995:
        return pcm
    raw = subprocess.run([short_render.ffmpeg_exe(), "-v", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
                          "-i", "-", "-af", f"rubberband=tempo={tempo:.4f}:transients=smooth",
                          "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-"],
                         input=pcm.astype(np.int16).tobytes(), capture_output=True, check=True, timeout=180).stdout
    return np.frombuffer(raw, dtype=np.int16)


def slow_rushed(pcm, heard: list, lines: list[dict], timed: list[dict]):
    """Each line marked "slow" (the Reviewer found it rushed) that's still faster than SLOW_LINE, slowed on its own to
    it (pitch kept; at most to LEAST_TEMPO): Gemini doesn't always hear "slowly" (#52 came back at 3.7 words a
    second, 2026-10-27). The words after it move along. Returns the reading, the heard words and how many lines."""
    import numpy as np

    slowed = 0
    for line, t in reversed(list(zip(lines, timed))):
        n, length = len(line["text"].split()), t["end"] - t["start"]
        if not line.get("slow") or n < PACED_WORDS or length <= 0:
            continue
        tempo = max(LEAST_TEMPO, SLOW_LINE / (n / length))
        if tempo >= 0.995:
            continue
        a, b = int(t["start"] * SAMPLE_RATE), int(t["end"] * SAMPLE_RATE)
        part = stretch(pcm[a:b], tempo).astype(pcm.dtype)
        pcm = np.concatenate([pcm[:a], part, pcm[b:]])
        start, end, grow = a / SAMPLE_RATE, b / SAMPLE_RATE, (len(part) - (b - a)) / SAMPLE_RATE
        heard = [tuple(x + grow if x >= end else start + (x - start) / tempo if x > start else x for x in (p, q)) + (w,)
                 for p, q, w in heard]
        slowed += 1
    return pcm, heard, slowed


def _finish(audio: bytes, heard: list, lines: list[dict], out: Path, engine: str, voice: str, match: float,
            deeper: int = 0, keep_gap: float = KEEP_GAP) -> dict:
    """The reading's pauses tightened, a line the Reviewer found rushed slowed on its own if it still is, made
    deeper, and saved; every word's time follows."""
    pcm, moved = tighten(_pcm(audio), heard, keep_gap)
    heard = [(moved(a), moved(b), w) for a, b, w in heard]
    timed, match = align(lines, heard)
    pcm, heard, slowed = slow_rushed(pcm, heard, lines, timed)
    if slowed:
        timed, match = align(lines, heard)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_wav_bytes(lower(pcm, deeper)))
    return {"wav": str(out), "seconds": round(len(pcm) / SAMPLE_RATE, 3), "engine": engine, "voice": voice,
            "match": round(match, 3), "deeper": deeper, "lines": timed}


# --- samples for the Host page -----------------------------------------------------

def sample_path(voice: str, deeper: int = 0, style: str = STYLE) -> Path:
    """Where a voice's sample is kept, for these settings (a new style or depth makes a new sample)."""
    import hashlib

    tag = hashlib.sha1((style or STYLE).encode("utf-8")).hexdigest()[:8]
    return tmp_path("voices", "samples", f"{voice}_d{int(deeper)}_{tag}.wav")


def sample(voice: str, deeper: int = 0, style: str = STYLE, progress=print) -> dict:
    """A short sample of a voice in his persona (one free Gemini reading, kept for next time): what you choose his
    voice by on the Host page, and what every reading is measured against (his_voice)."""
    path = sample_path(voice, deeper, style)
    if not path.exists():
        progress(f"Recording a sample of {voice}'s voice")
        last = None
        for model in ordered(TTS_MODELS):
            try:
                audio = _ask(SAMPLE_LINES, voice, style or STYLE, model)
                break
            except Exception as e:  # used up for today, or a busy service: the next model
                last = e
        else:
            if isinstance(last, _UsedUp) and not any(left_today().values()):
                raise RuntimeError("Gemini's free readings for today are used up; a sample can be made after "
                                   f"{renews_at()[11:16]} UTC")
            raise RuntimeError(f"Gemini's voice is unavailable right now ({type(last).__name__}); try again later")
        heard = hear(audio)
        pcm, _ = tighten(_pcm(audio), heard)
        path.write_bytes(_wav_bytes(lower(pcm, int(deeper))))
    with wave.open(str(path), "rb") as w:
        return {"voice": voice, "deeper": int(deeper), "path": str(path), "seconds": round(w.getnframes() / w.getframerate(), 1)}


def measured() -> dict:
    """The voices' measured pitch and pace (scratch measurements saved next to the samples), if any."""
    path = tmp_path("voices", "samples", "measured.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--text", action="append", required=True, help="a line (repeat for more)")
    parser.add_argument("--direction", action="append", default=[], help="a voice direction per line, in order")
    parser.add_argument("--out", default=str(tmp_path("out", "narration.wav")))
    args = parser.parse_args()
    lines = [{"text": t, "direction": args.direction[k] if k < len(args.direction) else ""} for k, t in enumerate(args.text)]
    try:
        result = narrate(lines, Path(args.out))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "lines"}, indent=2))
    for line, timed in zip(lines, result["lines"]):
        print(f"{timed['start']:6.2f}-{timed['end']:6.2f}  {line['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
