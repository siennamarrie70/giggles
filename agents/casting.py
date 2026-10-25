"""
Agent 1, Casting: decides who is in each episode. It picks a setting and designs two or three
adult characters for it (name, role in the sketch, personality, look and voice) from the parts the
puppet rig can draw (tools/character_spec.py), plus a one-line hint for the Writer about the kind of
situation this cast suits. Every character is saved, so the Analyst can see which kinds of
characters do well and the dashboard's Cast page shows them all.

Usage:
    python -m agents.casting        # casts one episode, saves its characters and prints them
"""

import json
import random
import sys

import character_spec as cs
import db
import llm
from agents.base import act, advice, log
from common import load_config

RECENT_EPISODES = 8

_CHARACTER = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "a short first name"},
        "age": {"type": "integer", "description": "25 to 75"},
        "role": {"type": "string", "description": "their role in the sketch, 2-4 words, e.g. 'deadpan coworker'"},
        "personality": {"type": "string", "description": "one sentence"},
        **{part: {"type": "string", "enum": options} for part, options in cs.PARTS.items()},
        "skin": {"type": "string", "enum": list(cs.SKIN_TONES)},
        "hair_color": {"type": "string", "enum": list(cs.HAIR_COLORS)},
        "outfit_color": {"type": "string", "enum": list(cs.COLORS)},
        "accent_color": {"type": "string", "enum": list(cs.COLORS),
                         "description": "the colour of the inner layer, tie, scarf, hat or mug"},
        "voice": {"type": "string", "enum": list(cs.VOICES)},
        "speed": {"type": "number", "description": "speaking speed, 0.85 (slow) to 1.2 (fast)"},
    },
    "required": ["name", "age", "role", "personality", *cs.PARTS, "skin", "hair_color", "outfit_color",
                 "accent_color", "voice", "speed"],
}


def _schema(settings: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "setting": {"type": "string", "enum": settings},
            "premise_hint": {"type": "string", "description": "one line: the kind of situation this cast suits"},
            "characters": {"type": "array", "items": _CHARACTER, "description": "2 or 3 characters"},
        },
        "required": ["setting", "premise_hint", "characters"],
    }


def _recent() -> list[str]:
    out = []
    for v in db.recent_videos(days=21)[:RECENT_EPISODES]:
        plan = v["plan"]
        if plan.get("cast"):
            out.append(f"{plan.get('setting')}: " + ", ".join(f"{c['name']} the {c['role']}" for c in plan["cast"]))
    return out


def cast_episode(progress=log) -> dict:
    cfg = load_config()
    ch, episodes = cfg["channel"], cfg["episodes"]
    settings = [s for s in episodes["settings"] if s in cs.SETTINGS] or list(cs.SETTINGS)
    system = f"""You are the casting director of {ch['name']}, a YouTube Shorts channel of 20-45 second animated
comedy sketches for {ch['audience']}.
The channel's voice: {ch['voice']}

For each episode, choose a setting and design 2 or {episodes['max_cast']} adult characters (all 25 or older) whose
personalities clash in a funny, relatable way: an overthinker and a deadpan colleague, an over-sharer and someone who
wants to be left alone, a know-it-all and a skeptic. Make them look clearly different from each other (hair, colours,
body type, skin tone, outfit) so viewers tell them apart at a glance, and keep casts diverse from one episode to the
next. Give each a short first name, a 2-4 word role in the sketch and a one-sentence personality. Pick the voice
that fits each character from the list; no two characters share a voice. Clothes should suit the setting.
Never base a character on a real person, a celebrity or an existing cartoon or film character. Never children or
teenagers. Suggest, in one line, the kind of everyday situation this cast suits."""
    prompt = (f"Settings you may use: {json.dumps({s: cs.SETTINGS[s] for s in settings})}\n"
              f"Voices: {json.dumps(cs.VOICES)}\n"
              f"Recent episodes (use a different setting or kind of cast): {_recent() or 'none yet'}\n"
              f"What has worked so far: {advice(('setting', 'role', 'voice', 'outfit')) or 'not enough data yet'}\n\n"
              "Cast the next episode.")
    progress("Casting the next episode")
    raw = llm.generate_json([prompt], _schema(settings), system)
    cast = cs.validate_cast(raw.get("characters") or [], max_size=int(episodes["max_cast"]))
    setting = cs.snap(raw.get("setting"), settings)
    for spec in cast:
        spec["id"] = db.insert_character(spec)
    progress(f"{setting.capitalize()}: " + ", ".join(f"{c['name']} the {c['role']}" for c in cast))
    return {"setting": setting, "seed": random.randint(0, 999), "premise_hint": " ".join(str(raw.get("premise_hint", "")).split())[:200],
            "cast": cast, "names": [c["name"] for c in cast]}


def run(progress=log) -> dict:
    return act("casting", "Cast an episode", cast_episode, progress=progress)


def main() -> int:
    try:
        result = run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
