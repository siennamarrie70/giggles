"""
Agent 2, Writer: writes the sketch for Agent 1's cast: a hook for the top of the screen, 3 to 6
beats of dialogue that end on a punchline, and the YouTube title, description and hashtags. It
reads today's trends (searches trending worldwide, popular comedy videos, holidays coming up) and
uses one only when it fits naturally. Each beat says who speaks, the line (12 words at most: it's
spoken and captioned), the speaker's emotion and action, the camera (wide or close on the speaker)
and how the others react. Everything is cleaned and checked in code before it's saved.

apply_edits() takes the owner's edits from the dashboard through the same checks.

Usage:
    python -m agents.writer         # casts an episode (Agent 1 saves its characters) and prints a sketch for it
"""

import json
import sys

import cartoon_render
import character_spec as cs
import db
import llm
import puppet
import short_render
import text_clean
from agents.base import act, advice, log
from common import load_config

MAX_BEATS = 6
LINE_CHARS = 90
HOOK_CHARS = 60
WORDS_PER_SECOND = 2.5  # Kokoro's pace at speed 1.0, measured 2026-10-25
RECENT_PREMISES = 40


def _schema(names: list[str], moods: list[str]) -> dict:
    beat = {
        "type": "object",
        "properties": {
            "speaker": {"type": "string", "enum": names},
            "line": {"type": "string", "description": "what they say, 12 words at most"},
            "emotion": {"type": "string", "enum": list(puppet.EMOTIONS)},
            "action": {"type": "string", "enum": list(cartoon_render.ACTIONS)},
            "camera": {"type": "string", "enum": ["wide", "close"]},
            "listener_emotion": {"type": "string", "enum": list(puppet.EMOTIONS),
                                 "description": "how the others react while this line is said"},
        },
        "required": ["speaker", "line", "emotion", "action", "camera", "listener_emotion"],
    }
    return {
        "type": "object",
        "properties": {
            "premise": {"type": "string", "description": "one sentence: the situation and the joke"},
            "hook": {"type": "string", "description": "the caption on top of the whole video, 60 characters at most"},
            "trend_used": {"type": "string", "description": "the trend or event it plays on; empty if evergreen"},
            "beats": {"type": "array", "items": beat, "description": "3 to 6 beats; the last one is the punchline"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "music_mood": {"type": "string", "enum": moods} if moods else {"type": "string"},
        },
        "required": ["premise", "hook", "trend_used", "beats", "title", "description", "hashtags", "tags", "music_mood"],
    }


def _where(items: list[dict], key: str) -> list[str]:
    out = []
    for item in items:
        countries = item.get("countries") or []
        out.append(item[key] + (f" ({len(countries)} countries)" if len(countries) > 1 else ""))
    return out


def clean_beats(raw: list[dict], cast: list[dict]) -> list[dict]:
    """Beats the renderer can always play: known speakers and enums, short lines, walk-ins only on a
    character's first line, a wide first shot, at least two speakers."""
    by_name = {c["name"].lower(): i for i, c in enumerate(cast)}
    beats, spoken = [], set()
    for item in raw[:MAX_BEATS]:
        line = text_clean.screen_text(str(item.get("line", "")), LINE_CHARS)
        if not line:
            continue
        speaker = by_name.get(str(item.get("speaker", "")).strip().lower())
        if speaker is None:  # unknown name: whoever didn't speak last
            speaker = (beats[-1]["speaker"] + 1) % len(cast) if beats else 0
        action = cs.snap(item.get("action"), cartoon_render.ACTIONS, default="talk")
        if action == "walk_in" and speaker in spoken:
            action = "talk"
        beats.append({"speaker": speaker, "line": line,
                      "emotion": cs.snap(item.get("emotion"), puppet.EMOTIONS, default="neutral"),
                      "action": action,
                      "camera": "close" if str(item.get("camera")).lower() == "close" else "wide",
                      "listener_emotion": cs.snap(item.get("listener_emotion"), puppet.EMOTIONS, default="neutral")})
        spoken.add(speaker)
    if len(beats) < 2 or len({b["speaker"] for b in beats}) < 2:
        raise ValueError("the sketch needs at least two lines from two different characters")
    beats[0]["camera"] = "wide"  # first, show who's there
    return beats


def estimate_seconds(beats: list[dict], cast: list[dict]) -> float:
    words = sum(len(b["line"].split()) / cast[b["speaker"]]["speed"] for b in beats)
    return words / WORDS_PER_SECOND + cartoon_render.LEAD_IN + cartoon_render.TAIL + len(beats) * cartoon_render.GAP


def metadata(raw: dict, premise: str, cfg: dict) -> dict:
    tags = text_clean.hashtags(raw.get("hashtags") or [], cfg["metadata"]["base_hashtags"])
    title = text_clean.title(raw.get("title", ""), premise)
    description = "\n\n".join(p for p in (text_clean.no_brackets(str(raw.get("description", ""))).strip()[:1500],
                                          " ".join(tags)) if p)
    return {"title": title, "description": description, "hashtags": tags, "tags": text_clean.tags(raw.get("tags") or [])}


def write(cast: list[dict], setting: str, premise_hint: str, trends: dict, progress=log) -> dict:
    cfg = load_config()
    ch, max_seconds = cfg["channel"], int(cfg["episodes"]["max_seconds"])
    names = [c["name"] for c in cast]
    moods = short_render.music_moods()
    system = f"""You write sketches for {ch['name']}, a YouTube Shorts channel of animated comedy for {ch['audience']}.
The channel's voice: {ch['voice']}

A sketch is 3 to 6 beats of dialogue between the given characters, in the given setting, about {max_seconds - 10} to
{max_seconds} seconds long when spoken. One clear, relatable situation from adult everyday life; build quickly and
end on a punchline in the last line. Lines are spoken aloud by a voice engine and shown as captions: 12 words at most,
plain words, no emoji, no hashtags, no stage directions, no sound effects. Play each character's personality.
Emotions and actions are what the cartoon can show; use them to sell the joke (a facepalm, a shrug, a smug look).
Use a close shot for the line that matters most (often the punchline); otherwise wide.
The hook is a caption over the whole video that makes people stay: a short 'When...' or 'POV:' line about this
sketch's situation, in your own words, that viewers recognise from their own life.
Use a trend only if it fits naturally and is harmless: holidays, seasons, weekday moods, widespread lighthearted
trends. Never news, politics, disasters, crime, tragedy, real people, celebrities, brands, or anything sexual.
Never aimed at children. Write in English whatever language a trend is in.
Title: at most 70 characters, honest, may include one emoji, no hashtags. Description: 1-2 short sentences;
a light question that invites comments is good. Hashtags: 3-5, lowercase. Tags: 5-10 search keywords."""
    signals = {
        "today": f"{trends['weekday']} {trends['date']}",
        "upcoming_events": trends.get("events", []),
        "season": trends.get("season"),
        "weekday_vibe": trends.get("weekday_vibe"),
        "trending_searches": _where(trends.get("google_trends", []), "term")[:20],
        "popular_comedy_videos": _where(trends.get("youtube_popular", []), "title")[:12],
    }
    recent = [v["theme"] for v in db.recent_videos(days=30) if v["theme"]][:RECENT_PREMISES]
    prompt = (f"Setting: {setting} ({cs.SETTINGS.get(setting, '')})\n"
              f"Characters:\n" + "\n".join(f"- {cs.describe(c)}. {c['personality']}" for c in cast) + "\n"
              f"Casting's hint: {premise_hint or 'none'}\n\n"
              f"Today's signals:\n{json.dumps(signals, ensure_ascii=False, indent=1)}\n\n"
              f"Recent premises to avoid repeating: {recent or 'none yet'}\n"
              f"What has worked so far: {advice(('length', 'beats', 'trend')) or 'not enough data yet'}\n\n"
              "Write the sketch.")
    progress("Writing the sketch")
    raw = llm.generate_json([prompt], _schema(names, moods), system)
    beats = clean_beats(raw.get("beats") or [], cast)
    while len(beats) > 2 and estimate_seconds(beats, cast) > max_seconds:  # too long: drop a middle beat
        beats.pop(len(beats) // 2)
    premise = " ".join(str(raw.get("premise", "")).split())[:200] or beats[0]["line"]
    script = {"premise": premise,
              "hook": text_clean.screen_text(str(raw.get("hook", "")), HOOK_CHARS),
              "trend_used": " ".join(str(raw.get("trend_used", "")).split())[:120],
              "beats": beats,
              "music_mood": cs.snap(raw.get("music_mood"), moods, default="") if moods else ""}
    progress(f"Premise: {premise}")
    return {"script": script, "metadata": metadata(raw, premise, cfg), "premise": premise,
            "trend": script["trend_used"], "lines": len(beats)}


def run(cast: list[dict], setting: str, premise_hint: str, trends: dict, progress=log) -> dict:
    return act("writer", "Write a sketch", write, cast, setting, premise_hint, trends, progress=progress)


def apply_edits(plan: dict, edits: dict) -> dict:
    """The owner's edits from the dashboard, through the same rules as generated text."""
    cfg = load_config()
    script, meta, cast = plan["script"], plan["metadata"], plan["cast"]
    if "hook" in edits:
        script["hook"] = text_clean.screen_text(str(edits["hook"]), HOOK_CHARS)
    if "beats" in edits:
        raw = [{**b, "speaker": cast[int(b["speaker"])]["name"] if str(b.get("speaker", "")).isdigit() else b.get("speaker")}
               for b in edits["beats"] if isinstance(b, dict)]
        script["beats"] = clean_beats(raw, cast)
    if "title" in edits:
        meta["title"] = text_clean.title(str(edits["title"]), meta["title"])
    if "description" in edits:
        meta["description"] = text_clean.no_brackets(str(edits["description"])).strip()[:4900]
    if estimate_seconds(script["beats"], cast) > int(cfg["episodes"]["max_seconds"]) + 15:
        raise ValueError("That's too long for a Short: shorten or remove a line.")
    return plan


def main() -> int:
    from agents import casting
    from jobs import trend_signals

    try:
        cast = casting.cast_episode()
        result = write(cast["cast"], cast["setting"], cast["premise_hint"], trend_signals(load_config()))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
