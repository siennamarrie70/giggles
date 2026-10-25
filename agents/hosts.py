"""
The two hosts who present every case: the presenter tells it, the co-host asks what viewers would
ask. They're designed once (one Gemini call; tools/character_spec.py snaps every part to what the
rig can draw and keeps their voices apart), saved as characters and named in config/channel.yaml
(hosts: presenter, cohost). The dashboard's Hosts page shows them with their voices, lets you change
any part, or has them designed afresh. A change saves a new character, so cases already written
keep the hosts they were written for (each plan keeps a copy).

Usage:
    python -m agents.hosts              # shows the hosts (designs them first if there are none)
    python -m agents.hosts --redesign
"""

import argparse
import json
import sys

import character_spec as cs
import db
import llm
from agents.base import act, log
from common import load_config, update_config

ROLES = ("presenter", "cohost")
ROLE_NAMES = {"presenter": "presenter", "cohost": "co-host"}

_HOST = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "a short first name"},
        "age": {"type": "integer", "description": "25 to 60"},
        "personality": {"type": "string", "description": "one sentence"},
        **{part: {"type": "string", "enum": options} for part, options in cs.PARTS.items()},
        "skin": {"type": "string", "enum": list(cs.SKIN_TONES)},
        "hair_color": {"type": "string", "enum": list(cs.HAIR_COLORS)},
        "outfit_color": {"type": "string", "enum": list(cs.COLORS)},
        "accent_color": {"type": "string", "enum": list(cs.COLORS),
                         "description": "the colour of the inner layer, tie or scarf"},
        "voice": {"type": "string", "enum": list(cs.VOICES)},
        "speed": {"type": "number", "description": "speaking speed, 1.0 to 1.12"},
    },
    "required": ["name", "age", "personality", *cs.PARTS, "skin", "hair_color", "outfit_color", "accent_color",
                 "voice", "speed"],
}
SCHEMA = {"type": "object", "properties": {"presenter": _HOST, "cohost": _HOST}, "required": ["presenter", "cohost"]}


def _save(specs: list[dict]) -> list[dict]:
    """Saves the hosts as new characters and points the config at them."""
    for spec in specs:
        spec["id"] = db.insert_character(spec)

    def change(data):
        data["hosts"] = data.get("hosts") or {}
        for role, spec in zip(ROLES, specs):
            data["hosts"][role] = spec["id"]
    update_config(change)
    return specs


def design(progress=log) -> dict:
    """Designs both hosts afresh."""
    ch = load_config()["channel"]
    system = f"""You design the two hosts of {ch['name']}, a YouTube Shorts channel of 60-second case studies for
{ch['audience']}. They present every case together from a studio desk, so viewers get to know them.
- The presenter tells each case: clear, confident, warm and a little witty.
- The co-host asks what viewers would ask, reacts and adds the odd joke: curious, quick and likeable.
Both are adults (25 or older) who look clearly different from each other at a glance (hair, colours, body type, skin
tone, outfit), dressed smart-casual for a studio. Give each a short first name, a one-sentence personality and the
voice that fits from the list: clear and easy to follow, two different voices (one woman and one man, or two
different accents). Speaking speed 1.0 to 1.12. Never based on a real person, a celebrity or an existing character."""
    prompt = f"Voices: {json.dumps(cs.VOICES)}\n\nDesign the presenter and the co-host."
    progress("Designing the two hosts")
    raw = llm.generate_json([prompt], SCHEMA, system)
    specs = cs.validate_cast([{**(raw.get(role) or {}), "role": ROLE_NAMES[role]} for role in ROLES], max_size=2)
    for spec in specs:
        spec["speed"] = round(min(1.12, max(1.0, spec["speed"])), 2)
    _save(specs)
    progress("Hosts: " + " and ".join(f"{s['name']} the {s['role']}" for s in specs))
    return {"hosts": specs, "names": [s["name"] for s in specs]}


def current(progress=log) -> list[dict]:
    """The presenter and the co-host (designed first if the config names none)."""
    ids = load_config().get("hosts") or {}
    specs = db.get_characters([ids[r] for r in ROLES if ids.get(r)])
    if len(specs) == 2:
        return specs
    return act("hosts", "Design the hosts", design, progress=progress)["hosts"]


def update(role: str, changes: dict) -> dict:
    """One host with some parts changed (checked like a new design); saved as a new character."""
    if role not in ROLES:
        raise ValueError(f"unknown host {role!r}")
    hosts = current()
    index = ROLES.index(role)
    other = hosts[1 - index]
    spec = cs.validate_character({**hosts[index], **changes, "role": ROLE_NAMES[role]}, {other["voice"]})
    spec["speed"] = round(min(1.2, max(0.9, spec["speed"])), 2)
    if spec["name"].lower() == other["name"].lower():
        raise ValueError("the two hosts need different names")
    spec["id"] = db.insert_character(spec)

    def change(data):
        data["hosts"][role] = spec["id"]
    update_config(change)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--redesign", action="store_true")
    args = parser.parse_args()
    try:
        hosts = act("hosts", "Design the hosts", design)["hosts"] if args.redesign else current()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    for spec in hosts:
        print(cs.describe(spec), f"| voice {spec['voice']} at {spec['speed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
