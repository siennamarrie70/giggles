"""
The character contract between the hosts' design (agents/hosts.py) and the puppet rig (puppet.py):
every part a character can be drawn with, the voices it can speak with, and validate_cast(), which
turns what Gemini wrote into specs the rig can always draw.

Everything is adult on purpose: the rig only has adult proportions, ages run 25 to 75, and the
clothes are grown-up clothes. A value the rig doesn't know is snapped to the nearest one it does
(or to the default); a missing name is an error.

Usage:
    python tools/character_spec.py --check cast.json      # prints the validated cast
    python tools/character_spec.py --parts                # lists every part and voice
"""

import argparse
import json
import re
import sys

SKIN_TONES = {"porcelain": "#f7dfcf", "fair": "#f0cdb0", "light": "#e6b994", "warm": "#d69d70",
              "tan": "#bd8253", "brown": "#97603d", "deep": "#714328", "ebony": "#4d2d1b"}
HAIR_COLORS = {"black": "#221d1f", "dark brown": "#40291f", "brown": "#6c4428", "chestnut": "#8a4a2a",
               "auburn": "#9b3e23", "ginger": "#cb6430", "blonde": "#ddb565", "platinum": "#ece2c9",
               "grey": "#a29f99", "white": "#eeebe4", "blue": "#3f6fd8", "pink": "#ec80ad",
               "purple": "#8a5cd6", "green": "#3fa06f"}
COLORS = {"navy": "#2e3e72", "royal blue": "#3466cc", "sky blue": "#82b4e6", "teal": "#269488",
          "green": "#4b9a4a", "olive": "#7a7c3c", "mustard": "#e0a526", "orange": "#ec7a32",
          "red": "#d6453d", "burgundy": "#7f2a3b", "pink": "#ee8fb3", "purple": "#7b55c7",
          "lavender": "#b9a3e3", "white": "#f4f2ec", "grey": "#8e9096", "charcoal": "#3c3e45",
          "black": "#212126", "brown": "#7b5137", "beige": "#d9c3a0", "denim": "#4f6d98"}

PARTS = {
    "face": ["oval", "round", "square", "long"],
    "eyes": ["round", "narrow", "sleepy", "lashes"],
    "nose": ["small", "round", "pointy", "big"],
    "hair": ["short", "side part", "quiff", "buzz", "curly", "afro", "bun", "ponytail", "long", "bob",
             "pixie", "receding", "bald"],
    "facial_hair": ["none", "stubble", "mustache", "beard", "goatee"],
    "glasses": ["none", "round", "square", "sunglasses"],
    "body": ["average", "slim", "broad", "round"],
    "height": ["medium", "short", "tall"],
    "outfit": ["t-shirt", "shirt", "shirt and tie", "hoodie", "blazer", "sweater", "polo", "tank top",
               "dress", "apron", "cardigan", "jacket", "scrubs"],
    "accessory": ["none", "earrings", "headphones", "cap", "beanie", "necklace", "lanyard", "scarf",
                  "headband"],
}
PALETTES = {"skin": SKIN_TONES, "hair_color": HAIR_COLORS, "outfit_color": COLORS, "accent_color": COLORS}
DEFAULTS = {"skin": "light", "hair_color": "brown", "outfit_color": "navy", "accent_color": "white"}

# Kokoro voices that sound good enough for dialogue (Kokoro's own grades C+ and up, plus a few for
# variety). Santa and the non-English voices are left out on purpose.
VOICES = {
    "af_heart": "woman, American, warm and bright",
    "af_bella": "woman, American, lively and expressive",
    "af_nicole": "woman, American, soft and breathy",
    "af_aoede": "woman, American, relaxed",
    "af_kore": "woman, American, clear and confident",
    "af_sarah": "woman, American, friendly",
    "af_nova": "woman, American, crisp",
    "bf_emma": "woman, British, polished",
    "bf_isabella": "woman, British, warm",
    "am_michael": "man, American, steady",
    "am_fenrir": "man, American, deep and bold",
    "am_puck": "man, American, playful",
    "am_echo": "man, American, light",
    "am_eric": "man, American, upbeat",
    "am_liam": "man, American, easy-going",
    "am_onyx": "man, American, low and calm",
    "bm_george": "man, British, older and dry",
    "bm_fable": "man, British, storyteller",
    "bm_lewis": "man, British, gruff",
    "bm_daniel": "man, British, calm",
}

# What Gemini might write instead of the rig's own word.
SYNONYMS = {
    "hair": {"shaved": "bald", "shaved head": "bald", "crew cut": "buzz", "buzz cut": "buzz", "parted": "side part",
             "side parted": "side part", "curls": "curly", "wavy": "curly", "top knot": "bun", "man bun": "bun",
             "pony tail": "ponytail", "natural": "afro", "bob cut": "bob", "pixie cut": "pixie", "thinning": "receding",
             "balding": "receding", "long straight": "long", "straight": "long", "pompadour": "quiff", "slicked": "quiff",
             "cropped": "short", "messy": "short"},
    "outfit": {"suit": "blazer", "suit jacket": "blazer", "shirt & tie": "shirt and tie", "tie": "shirt and tie",
               "tshirt": "t-shirt", "tee": "t-shirt", "t shirt": "t-shirt", "jumper": "sweater", "pullover": "sweater",
               "sweatshirt": "sweater", "hooded sweatshirt": "hoodie", "denim jacket": "jacket",
               "leather jacket": "jacket", "bomber": "jacket", "nurse": "scrubs", "doctor": "scrubs", "chef": "apron",
               "blouse": "shirt", "button-up": "shirt", "button up": "shirt", "vest": "tank top", "singlet": "tank top"},
    "facial_hair": {"moustache": "mustache", "full beard": "beard", "clean shaven": "none", "clean-shaven": "none",
                    "five o'clock shadow": "stubble"},
    "glasses": {"no": "none", "specs": "round", "rectangular": "square", "shades": "sunglasses"},
    "accessory": {"hat": "cap", "baseball cap": "cap", "woolly hat": "beanie", "earring": "earrings",
                  "chain": "necklace", "badge": "lanyard", "id badge": "lanyard", "hairband": "headband"},
    "body": {"thin": "slim", "skinny": "slim", "medium": "average", "muscular": "broad", "stocky": "broad",
             "chubby": "round", "heavy": "round", "plus-size": "round"},
    "face": {"heart": "oval", "angular": "square", "wide": "round"},
    "eyes": {"tired": "sleepy", "droopy": "sleepy", "almond": "narrow", "big": "round"},
    "nose": {"button": "small", "long": "pointy", "large": "big"},
    "colors": {"blue": "royal blue", "light blue": "sky blue", "dark blue": "navy", "gray": "grey",
               "dark grey": "charcoal", "dark gray": "charcoal", "yellow": "mustard", "gold": "mustard",
               "maroon": "burgundy", "wine": "burgundy", "violet": "purple", "khaki": "beige", "tan": "beige",
               "cream": "white", "jeans": "denim", "dark green": "olive", "lime": "green", "turquoise": "teal"},
    "hair_color": {"blond": "blonde", "red": "ginger", "gray": "grey", "silver": "grey", "salt and pepper": "grey",
                   "light brown": "brown", "dark": "black", "brunette": "dark brown"},
    "skin": {"pale": "porcelain", "medium": "warm", "olive": "tan", "dark": "deep", "very dark": "ebony"},
}


def _key(value) -> str:
    return " ".join(re.sub(r"[_\-]+", " ", str(value or "")).lower().split())


def snap(value, allowed, synonyms: dict | None = None, default=None):
    """The allowed value closest to `value`: itself, a known synonym, or one containing the other."""
    allowed = list(allowed)
    key = _key(value)
    by_key = {_key(a): a for a in allowed}
    if key in by_key:
        return by_key[key]
    if synonyms and key in synonyms:
        return synonyms[key]
    for k, a in by_key.items():
        if k and key and (k in key or key in k):
            return a
    return default if default is not None else allowed[0]


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def validate_character(raw: dict, taken_voices: set[str]) -> dict:
    name = re.sub(r"[^A-Za-z' -]", "", _text(raw.get("name"), 24)).strip()
    if not name:
        raise ValueError("every character needs a name")
    spec = {"name": name, "role": _text(raw.get("role"), 48) or "friend",
            "personality": _text(raw.get("personality"), 180)}
    try:
        spec["age"] = min(75, max(25, int(raw.get("age"))))
    except (TypeError, ValueError):
        spec["age"] = 32
    for part, allowed in PARTS.items():
        spec[part] = snap(raw.get(part), allowed, SYNONYMS.get(part))
    for field, palette in PALETTES.items():
        synonyms = SYNONYMS["colors"] if field in ("outfit_color", "accent_color") else SYNONYMS.get(field)
        spec[field] = snap(raw.get(field), palette, synonyms, DEFAULTS[field])
    if spec["accent_color"] == spec["outfit_color"]:  # the inner layer must show against the outer one
        spec["accent_color"] = "white" if spec["outfit_color"] != "white" else "charcoal"
    if spec["hair"] == "bald" and spec["accessory"] in ("headband",):
        spec["accessory"] = "none"

    voice = snap(raw.get("voice"), VOICES, default="")
    if not voice or voice in taken_voices:
        # Same kind of voice (af, am, bf, bm) that nobody in this episode has yet, else any free one.
        kind = (voice or str(raw.get("voice") or "am"))[:2]
        voice = next((v for v in VOICES if v[:2] == kind and v not in taken_voices),
                     next(v for v in VOICES if v not in taken_voices))
    spec["voice"] = voice
    try:
        spec["speed"] = round(min(1.2, max(0.85, float(raw.get("speed")))), 2)
    except (TypeError, ValueError):
        spec["speed"] = 1.0
    return spec


def validate_cast(raw: list[dict], max_size: int = 3) -> list[dict]:
    """2 to max_size characters with different names and different voices."""
    cast, names, voices = [], set(), set()
    for item in raw[:max_size]:
        spec = validate_character(item, voices)
        if spec["name"].lower() in names:
            continue
        names.add(spec["name"].lower())
        voices.add(spec["voice"])
        cast.append(spec)
    if len(cast) < 2:
        raise ValueError("at least two characters are needed")
    return cast


def voice_lang(voice: str) -> str:
    return "en-gb" if voice.startswith("b") else "en-us"


def describe(spec: dict) -> str:
    """One line for prompts and the dashboard: who this is and what they look like."""
    look = [spec["body"], f"{spec['skin']} skin", f"{spec['hair_color']} {spec['hair']} hair"
            if spec["hair"] != "bald" else "bald", spec["facial_hair"] if spec["facial_hair"] != "none" else "",
            f"{spec['glasses']} glasses" if spec["glasses"] != "none" else "",
            f"{spec['outfit_color']} {spec['outfit']}", spec["accessory"] if spec["accessory"] != "none" else ""]
    return f"{spec['name']} ({spec['age']}, {spec['role']}): " + ", ".join(p for p in look if p)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check", help="JSON file with a list of characters")
    parser.add_argument("--parts", action="store_true")
    args = parser.parse_args()
    if args.parts:
        print(json.dumps({**PARTS, "skin": list(SKIN_TONES), "hair_color": list(HAIR_COLORS),
                          "colors": list(COLORS), "voices": VOICES}, indent=1))
        return 0
    if not args.check:
        parser.error("give --check or --parts")
    try:
        with open(args.check, encoding="utf-8") as f:
            cast = validate_cast(json.load(f))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(cast, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
