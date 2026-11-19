"""
Agent 3's first step, the storyboard (the 2026-11-16 plan): from the day's script (agents/story.py, your script writer's)
Gemini designs the film's pictures, for this story only, from the library of the code-drawn world
(tools/silhouette_words.py; tools/silhouette_board.py draws them):

  - its places (PLACES of them), each built from the library: a kind of place (a room, a hall, a street, nature,
    inside a car...), its look (walls, floor, the window and its view), its things, its light, weather and effects;
  - the people around him (the cast), each one's role and look from the look's parts; he is always the same man;
  - a shot for every moment of the story (agents/story.py write_moments: what we see, who's in it, their bubbles; no
    narrator), in order, and a few quiet ones: its stage of your prompt's six, its place, what he does there, where and
    with what eyes and marks, who else is there, the framing and the camera, what the picture shows (the Reviewer
    checks the drawing against it); code puts the moment's bubbles on its shot and its speakers in the picture;
  - the habit shown big (whatever this story's is: any of the library's exaggerated pieces, none tied to a topic);
  - the shot where he realizes (the music lifts there), six chapter names, the thumbnail's shot and words (white and
    yellow), the description and the tags.

It gets the moments, your look text word for word (prompts/look_silhouette.txt.enc) and the library. check() holds the
answer to them: every moment has its shot in order, every stage has shots, every place and person is real, every action
has somewhere it can happen in its place (tools/silhouette_board.where), adults only, the channel's rules. Small things
code fixes itself (a misspelt thing, a person on a taken seat, a moment's missing shot, a speaker left out of the picture,
a habit not shown big enough); problems go back to Gemini with its
storyboard, at most TRIES times. What a script needed that the library doesn't have is listed (story["missing"]): what's
added to the library next. The places differ from the recent stories' (one too like a recent one gets other colours and
its things the other way round). Every place is built from the library: the 12 ready-made sets of the first look
(silhouette_words.SETS) aren't offered any more (your call, 2026-11-17: story #6, drawn in them by Flash-Lite while the
bigger models were busy, looked like the old films), and one an answer still names is built from the library as
SET_PLACES describes it. Gemini's stronger models are waited for while they're only busy (llm.generate_json strong).

Usage:
    python -m agents.storyboard .tmp/script_test/1_lust.json --out .tmp/storyboard/1_lust.json [--recent a.json ...] [--fresh]
"""

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

import llm
import silhouette_words as W
from agents import story as story_agent
from agents.base import act, log

TRIES = 3
PLACES = (6, 14)
QUIET = (2, 8)
CAST_MOST = 8
OTHERS_MOST = 3
LABELS_MOST = 4
SHOWS_MOST = 240
THINGS_MOST = 5                  # big things in a room (more run past a wide frame's edges)
PLACE_SHARE = 0.45               # the most of a film's shots one place may hold (the prompt asks for a third)
STAGES = story_agent.STAGES
STAGE_NAMES = story_agent.STAGE_NAMES
LIGHTS = ("dawn", "day", "dusk", "night")
FRAMINGS = ("wide", "medium", "close", "detail")
BUILDS, HEIGHTS = ("slim", "average", "broad"), ("short", "average", "tall")
HERO = {"him", "he", "hero", "the_hero", "main_character", "protagonist", "narrator", "the_man"}
NEEDS = {  # where an action can happen (silhouette_words.ACTIONS' second word), in words for Gemini
    "stand": "a free spot, or a thing to stand at", "walk": "in, out or across", "run": "across (outdoors best)",
    "sit": "a seat: a chair, a sofa, a bed's edge, a bench, an armchair, a vehicle's seat", "desk": "a desk or a table",
    "bed": "a bed, a sofa or a hospital bed", "floor": "the floor", "window": "the place's window",
    "pushup": "the free floor or a gym mat", "door": "a door (indoors) or a house (its front door)",
    "stove": "a stove, a counter, a chef's range or a prep counter", "table": "a table, a desk, a counter or a workbench",
    "bag": "a punching bag", "treadmill": "a treadmill", "drive": "inside a car: driver", "pair": "a free spot",
    "fix": "a workbench, a car (its wheel), or kneeling anywhere", "podium": "a podium (on a stage)",
    "screen": "a screen or a whiteboard on the wall", "mirror": "a mirror on the wall, or a basin's",
    "any": "anywhere: standing, sitting or walking"}
GROUPS = {"home": "Home", "wall": "On the walls", "work": "Work", "health": "Health and the gym", "outdoors": "Outdoors",
          "small": "Small things"}
MOOD_WORDS = {"tired": "half-lidded", "open": "plain, awake", "wide": "shock", "closed": "shut", "sad": "sad",
              "determined": "set, focused", "soft": "tender, calm", "happy": "smiling arcs", "angry": "angry",
              "worried": "worried", "hearts": "pink hearts (lust, infatuation)", "dollars": "gold $ signs (greed)",
              "spirals": "hypnotised spirals (hooked on the phone, a craving)",
              "droopy": "heavy-lidded with bags (laziness, no sleep)", "furious": "furious, glowing red (rage)",
              "side_eye": "narrowed, looking sideways (envy, jealousy, suspicion)",
              "smug": "half-shut, looking down his nose (ego, arrogance)", "sobbing": "streaming tears (self-pity, grief)",
              "terrified": "huge with tiny pupils (fear)", "fire": "flames (obsession, fierce resolve)"}
SET_PLACES = {  # a ready-made set of the first look an answer still names -> that place built from the library
    "desk_room": {"kind": "room", "wall": "plum", "floor": "wood", "window": "big", "view": "city", "lamp": True,
                  "things": ["bookcase", "desk", "plant"], "wall_things": ["clock", "shelf"], "small": ["laptop", "mug"]},
    "bedroom": {"kind": "room", "wall": "mauve", "floor": "carpet", "window": "small", "view": "city", "curtains": True,
                "things": ["wardrobe", "bed", "nightstand"], "wall_things": ["photos"], "small": ["phone"]},
    "kitchen": {"kind": "room", "wall": "sand", "floor": "tiles", "window": "small", "view": "houses", "lamp": True,
                "things": ["fridge", "counter", "dining_table"], "wall_things": ["cabinets", "calendar"],
                "small": ["letters", "mug"]},
    "hallway": {"kind": "corridor", "wall": "grey", "floor": "wood", "things": ["door", "plant"],
                "wall_things": ["mirror"]},
    "street": {"kind": "street", "things": ["shopfront", "street_lamp", "bin"]},
    "hospital": {"kind": "room", "wall": "slate", "floor": "tiles", "window": "small", "view": "city",
                 "things": ["heart_monitor", "hospital_bed", "chair"], "wall_things": ["clock"], "small": ["flowers"]},
    "office": {"kind": "room", "wall": "navy", "floor": "carpet", "window": "wide", "view": "city",
               "things": ["office_row", "desk", "filing_cabinet"], "wall_things": ["whiteboard"], "small": ["documents"]},
    "cafe": {"kind": "room", "wall": "rose", "floor": "wood", "window": "big", "view": "city", "lamp": True,
             "things": ["shop_counter", "dining_table", "plant"], "wall_things": ["poster"], "small": ["mug"]},
    "rooftop": {"kind": "bridge", "things": ["bench"]},
    "park": {"kind": "nature", "nature": "field", "things": ["tree", "bench", "street_lamp"]},
    "bright_office": {"kind": "room", "wall": "cream", "floor": "wood", "window": "wide", "view": "city",
                      "things": ["meeting_table", "plant"], "wall_things": ["screen"], "small": ["documents"]},
    "new_flat": {"kind": "room", "wall": "green", "floor": "wood", "window": "tall", "view": "city",
                 "things": ["bookcase", "sofa", "floor_lamp", "plant"], "wall_things": ["poster"], "small": ["books"]},
}
ALIASES = {  # words Gemini may use for the library's things
    "table": "dining_table", "kitchen_table": "dining_table", "dinner_table": "dining_table", "couch": "sofa",
    "computer": "desk", "monitor": "desk", "monitors": "desk", "computer_desk": "desk", "workstation": "desk",
    "television": "tv", "tv_stand": "tv", "sink": "counter", "kitchen_counter": "counter", "kitchen": "counter",
    "cupboards": "cabinets", "cupboard": "cabinets", "lamp": "floor_lamp", "bookshelf": "bookcase",
    "bookshelves": "bookcase", "shelves": "shelf", "picture": "poster", "painting": "poster", "photo": "photos",
    "photographs": "photos", "frames": "photos", "dumbbells": "weights", "barbell": "weights", "rack": "weights",
    "notebook": "documents", "papers": "documents", "paper": "documents", "bills": "letters", "bill": "letters",
    "envelope": "letters", "envelopes": "letters", "letter": "letters", "cash": "money", "beer": "bottle",
    "glass": "bottle", "whiskey": "bottle", "coffee": "mug", "cup": "mug", "streetlight": "street_lamp",
    "street_light": "street_lamp", "lamp_post": "street_lamp", "lamppost": "street_lamp", "trash_can": "bin",
    "trees": "tree", "bed_side_table": "nightstand", "bedside_table": "nightstand", "night_stand": "nightstand",
    "alarm_clock": "nightstand", "wall_clock": "clock", "office_desk": "desk", "office_desks": "office_row",
    "cubicles": "office_row", "conference_table": "meeting_table", "boardroom_table": "meeting_table",
    "projector_screen": "screen", "tv_screen": "tv", "counter_top": "counter", "shop_shelf": "shop_shelves",
    "cash_register": "shop_counter", "till": "shop_counter", "headstone": "grave", "tombstone": "grave",
    "luggage": "suitcase", "boxes_stacked": "boxes", "moving_boxes": "boxes", "cardboard_boxes": "boxes",
    "flowerpot": "plant", "potted_plant": "plant", "plants": "plant", "window": "", "candle": "candles",
    "wine_glasses": "wine", "wine_bottle": "wine", "smartphone": "phone", "mobile": "phone", "cellphone": "phone",
    "computer_screen": "desk", "screen_monitor": "desk"}
ACTION_ALIASES = {"sleeping": "asleep", "lying": "lying_awake", "lying_down": "lying_awake", "sitting_down": "sitting",
                  "stand": "standing", "walk": "walking", "run": "running", "jogging": "running", "sit": "sitting",
                  "looking_at_phone": "phone", "scrolling": "phone", "texting": "phone", "calling": "phone_call",
                  "on_the_phone": "phone_call", "talking_on_phone": "phone_call", "staring": "standing",
                  "thinking": "sitting", "working": "typing", "studying": "reading", "praying": "kneeling",
                  "hug": "hugging", "shaking_hands": "handshake", "argue": "arguing", "cry": "crying", "weeping": "crying",
                  "cook": "cooking", "eat": "eating", "drink": "drinking", "read": "reading", "write": "writing",
                  "clean": "cleaning", "sweeping": "cleaning", "wipe": "wiping", "fix": "fixing", "repairing": "fixing",
                  "speech": "speaking", "giving_a_speech": "speaking", "present": "presenting", "kneel": "kneeling",
                  "clap": "applauding", "clapping": "applauding", "wave": "waving", "carrying": "carrying_box",
                  "lifting_weights": "lifting", "punching": "boxing", "knocking": "at_door", "push_ups": "pushups",
                  "push-ups": "pushups", "looking_out_the_window": "at_window", "looking_in_mirror": "mirror",
                  "head_down": "slumped", "sitting_on_floor": "floor", "lying_on_floor": "lying_floor"}


def _clean(text) -> str:
    return " ".join(str(text or "").replace("’", "'").replace("‘", "'").split())


def _word(v) -> str:
    return "_".join(str(v or "").strip().lower().replace("-", " ").replace("'", "").split())


def _id(v, fallback: str = "x") -> str:
    w = re.sub(r"[^a-z0-9_]", "", _word(v))[:24].strip("_")
    return w or fallback


def story_key(story: dict) -> str:
    return hashlib.sha1(str(story.get("title") or "").encode("utf-8")).hexdigest()[:6]


# --- what Gemini gets --------------------------------------------------------------------------------------------------------
def library() -> str:
    """The library in words: everything a storyboard can build with."""
    out = ["KINDS OF PLACE (kind):"]
    out += [f"- {k}: {v}" for k, v in W.PLACE_KINDS.items()]
    out += [f"nature (kind nature only): {', '.join(W.NATURE)}",
            f"wall (rooms, halls, corridors): {', '.join(W.WALLS)}",
            f"floor: {', '.join(W.FLOORS)}",
            f"window (rooms, halls): {', '.join(W.WINDOWS)}; view (what a window or a vehicle's windows show): "
            f"{', '.join(W.VIEWS)}",
            "lamp: true for a lamp hanging from a room's ceiling (over its table or desk); curtains: true or false",
            f"light: {', '.join(LIGHTS)}; weather: {', '.join(W.WEATHER)}",
            "effects: " + "; ".join(f"{k} ({v})" for k, v in W.EFFECTS.items()),
            "",
            "THINGS. things: the big things on the floor, left to right; wall_things: on the walls; small: small things "
            "(set on a surface, or on the floor). Indoors only unless marked [out] (outdoors only) or [in or out]:"]
    for g, name in GROUPS.items():
        out.append(f"{name}:")
        for n, d in W.PROPS.items():
            if d[0] == g:
                out.append(f"  {n}: {d[1]}" + {"out": " [out]", "both": " [in or out]"}.get(d[4], ""))
    out += ["", "ACTIONS (what a person does; at: where it can happen):"]
    out += [f"  {n}: {what} (at: {NEEDS[need]})" for n, (what, need) in W.ACTIONS.items()]
    out += [f"items (what someone holds: for holding, or with any action): {', '.join(W.ITEMS)}",
            "", "PEOPLE'S LOOKS (the cast): hair: " + ", ".join(W.HAIRS) + "; hair_color: " + ", ".join(W.HAIR_COLORS)
            + "; cloth (their clothes' colour): " + ", ".join(c for c in W.CLOTH_COLORS if c != "teal")
            + "; extras: " + ", ".join(W.EXTRAS) + f"; build: {', '.join(BUILDS)}; height: {', '.join(HEIGHTS)}",
            "EYES (their mood): " + ", ".join(f"{m} ({w})" for m, w in MOOD_WORDS.items()),
            "MARKS (round a person's head, at most 2): " + "; ".join(f"{k} ({v})" for k, v in W.MARKS.items()),
            "SCREEN (his phone's screen turned to us, when he looks at his phone: phone, lying_awake, doomscrolling): "
            + "; ".join(f"{k} ({v})" for k, v in W.SCREENS.items()),
            "", "framing: wide (the whole place: where he is, how small in it), medium (from the knees up: what he does), "
            "close (head and shoulders: the eyes), detail (a thing close up; close_on names it: a thing of that place)",
            f"move: {', '.join(W.CAMERA)} (push_in: slowly closer, for a blow landing or a realization; pull_out: slowly "
            "back, for loneliness or an ending)",
            "event: " + "; ".join(f"{k} ({v})" for k, v in _events().items()),
            "enter: cut (mostly), fade (a time jump, a new chapter), lights_out (after a light goes off)"]
    return "\n".join(out)


def _events() -> dict:
    import silhouette_board as SB

    return SB.EVENTS


def _numbered(story: dict) -> str:
    """The story's moments for Gemini: k. [stage] what we see | who is in it | its bubbles."""
    def bubble(b):
        what = f"picture: {b['picture']}" + (f", \"{b['text']}\"" if b.get("text") else "") if b["kind"] == "picture" \
            else f"\"{b['text']}\""
        return f"{b['who']} {b['kind']}s {what}"
    return "\n".join(f"{k + 1}. [{x.get('stage', '')}] {x['text']} | in it: {', '.join(x.get('who') or ['him'])}"
                     + (" | " + "; ".join(bubble(b) for b in x["bubbles"]) if x.get("bubbles") else " | (no bubble)")
                     for k, x in enumerate(story["lines"]))


def _people_text(story: dict) -> str:
    people = story.get("people") or []
    if not people:
        return "(none: only him)"
    return "; ".join(f"{p['id']} ({p['role']})" for p in people)


def _recent_text(recent: list[dict]) -> str:
    if not recent:
        return "RECENT STORIES: none yet."
    rows = []
    for r in recent[:4]:
        bits = []
        for p in r.get("places") or []:
            if p.get("set"):   # (a story from before every place was built from the library)
                bits.append(f"{p.get('id')} ({p['set'].replace('_', ' ')})")
                continue
            s = p.get("spec") or {}
            kind = s.get("kind", "room") + (f"/{s.get('nature')}" if s.get("kind") == "nature" else "")
            things = ", ".join(t if isinstance(t, str) else t.get("thing", "") for t in s.get("things") or [])
            bits.append(f"{p.get('id')} ({kind}" + (f", {s.get('wall')} walls" if s.get("kind") in ("room", "hall", "corridor")
                                                   else "") + (f": {things}" if things else "") + ")")
        rows.append(f"- \"{r.get('title')}\": " + "; ".join(bits))
    return ("RECENT STORIES' PLACES (this story's must look different: other kinds of place where the script allows; "
            "when it needs the same kind, other colours and other things):\n" + "\n".join(rows))


def system(story: dict, recent: list[dict]) -> str:
    """What Gemini is told: its job, your look text word for word, the story and its script, the library, the rules."""
    import prompts

    look = prompts.load("look_silhouette")
    return f"""You are the storyboard artist of a YouTube channel of animated motivational story films. There's no
narrator: the film shows the story in pictures drawn entirely in code, in the channel's own look, from a library of
places, things, people and actions (below), and what the people say and think appears in bubbles over their heads (code
draws them, from the moments below). You design this story's pictures: the places it happens in, the people around its
hero, and a shot for every moment.

THE LOOK, in the channel owner's own words (its scene is one example of the look: its rules hold for every place you
design, its room and its clock don't):
\"\"\"
{look}
\"\"\"

THE HERO is always the same man, drawn the same way in every story: a black silhouette in a teal hoodie, two white eyes.
He speaks and thinks only in his bubbles. Never describe his looks: say what he does, where, and how his eyes are.

THE STORY: "{story['title']}". Theme: {story.get('theme')}. Core message: {story.get('core_message')}
Its stages, in the script writer's words, in order: hook, incident (the major incident), collapse, rock_bottom (rock
bottom and the realization), transformation, payoff (the new life).

{_habit_text(story, recent)}

THE MOMENTS, one numbered moment per shot, in order ([stage] what we see | who is in it | their bubbles):
{_numbered(story)}

THE PEOPLE (their ids are fixed: the bubbles name them): {_people_text(story)}

WHAT YOU DESIGN
1. places ({PLACES[0]}-{PLACES[1]}): every place the story happens in, designed for this story and built from the library.
   id: a short name (flat, office, restaurant); name: what it is in a few words ("his small rented flat").
   kind and its look: wall colour, floor, window and its view, lamp, curtains (rooms); nature (outdoors in nature).
   things: the big things on the floor, left to right (at most {THINGS_MOST} in a room, 4 outdoors); wall_things (at most 3);
   small (at most 4). A home looks lived in, never a showroom; a workplace has what its work needs. Never invent a
   thing: use the library's closest, and say what was missing in wish (a few plain words, else empty): code lists it,
   and it's added to the library.
   light and weather: the light does the mood: the dark stages at night or dusk, often in rain; the turn at dawn; the new
   life by day or a warm dusk. The script's own times come first (a morning is dawn or day). A shot can change its
   place's light or weather (the same room at dawn).
   effects: fire, smoke, emergency lights, party lights, a spotlight, snow, fog: when the story has them.
   A place is one room or one spot, and the story comes back to it whenever it returns there; a home can be several
   places (his desk by the window, his kitchen, his bedroom). Places differ from each other and from the recent stories'
   places (below). No place holds more than a third of the shots: when many lines happen in one home or one night, use
   its other rooms and corners, other framings, the light changing as time passes. Every place is built from the
   library's parts: there are no ready-made places.
2. cast (0-{CAST_MOST}): the people around him, never him: the moments' people with their ids exactly (above), and anyone
   else a shot needs. role: who they are to him; their look from the library's parts: hair and its colour, cloth (never
   teal: that's his), extras, build, height. Each looks different from the others at a glance. Everyone is an adult.
3. shots: one for every moment, in order (line: its number), and {QUIET[0]}-{QUIET[1]} quiet shots without a moment
   (line: 0) where the film needs to breathe: after a blow lands, before the turn, a place before he enters it.
   - stage: the stage the line belongs to (every stage has shots, in order, never going back).
   - place: a place's id. light, weather: empty for the place's own, or this shot's.
   - action: what he does (ACTIONS), or none when he isn't in the shot; at: where (below); item: what he holds, or empty;
     eyes: his eyes; with: for hugging, handshake or arguing, the cast id of the other one (also in others).
   - others: who else is in the shot (cast ids, at most {OTHERS_MOST}), each with what they do, where, and their eyes.
   - framing, close_on (detail only), move, event (none, mostly), enter.
   - shows: what the picture shows, in one plain sentence (the reviewer checks the drawing against it).
   - Everyone in a moment ("in it") is in its shot: him (his action) and the people (others). Whoever has a bubble
     must be in the picture, with room above their head for it: frame them medium or close, or wide when the place
     matters.
   - label: rarely, a small caption at the top for a time ("3:00 AM", "SIX HOURS LEFT", "MONTHS LATER"), at most
     {LABELS_MOST} in the film; else empty.
   - seconds: how long a quiet shot stays (3-6); 0 for a moment's shot (its bubbles set it).
   How to picture a moment: show exactly what it says we see, and whoever speaks or thinks in it, with room for their
   bubble. When a bubble is a thought, show him in a moment that carries it (at the window, walking alone, his head in
   his hands, working at dawn), never a random scene. Stay in a place for the moments that happen there, framed
   differently (wide to show the place, then medium, close, a detail of what matters); move on when the story does. The
   realization is close on his eyes.
   The pictures can't show: words or text of any kind (the bubbles are code's; a phone shows only a SCREEN), faces
   (people are silhouettes with two white eyes), blood or injuries, anyone undressed. A crash, a fire, an illness are
   shown by their signs (smoke, an ambulance's lights, a hospital bed), never by harm.
4. realization: the number of the shot (counting every shot, 1 = the first) where he realizes; the music lifts
   there. In rock_bottom, or the first shot of transformation.
5. chapters: six short names (2-5 words), one for each stage in order: the film's YouTube chapters.
6. thumbnail: the shot (its number) that makes a stranger click (him in it, a strong moment) and its words: lead (white,
   1-4 words) and punch (yellow, 1-3 words): together they make a stranger need to know. This story's own words.
7. description: 2-3 sentences for YouTube: what the story is about and its stakes, not its ending; no links or hashtags.
   tags: 6-12 search words.

WHERE PEOPLE ARE (at):
- a thing of the shot's place, by its name (bed, desk, dining_table, sofa, stove, door, bench, podium...): code puts the
  person on its right spot for what they do (in the bed to sleep, on its edge to sit; the desk's chair; at the stove).
  Two people at the same thing take its two places (a table's two chairs, a sofa's two seats).
- spot (standing on the free floor), window (at the place's window), floor (on the floor), in (walking in), out (walking
  out, leaving), across (walking across).
- inside a car: driver, back_seat; a bus: seat, seat_2, seat_3, stand (holding a strap), aisle; a train: seat, seat_2,
  seat_3, aisle.
Each action says where it can happen: typing needs a desk, cooking a stove, boxing a punching bag. Put the thing in the
place first.

THE LIBRARY (nothing else exists; use these words exactly)
{library()}

{_recent_text(recent)}

ALWAYS: everyone is an adult (no children or teenagers, not even in a photo or a memory); nothing explicit; no gore,
weapons or self-harm; no real brands, people or places by name.""" + _learned()


def _learned() -> str:
    """What the Reviewer has taught the storyboard (recurring problems in the films), if anything."""
    try:
        from agents.base import taught

        text = taught("storyboard")
    except Exception:   # (the database out of reach: the storyboard is made without them)
        return ""
    return ("\n\n" + text) if text else ""


def schema() -> dict:
    s = {"type": "string"}

    def one_of(values, about=""):
        return {"type": "string", "enum": list(values), **({"description": about} if about else {})}
    person = {"type": "object", "properties": {
        "who": {"type": "string", "description": "a cast id"},
        "action": {"type": "string", "description": "an action of the library"},
        "at": {"type": "string", "description": "where: a thing of the place, or spot, window, floor, in, out, across"},
        "item": {"type": "string", "description": "something they hold, or empty"},
        "eyes": one_of(W.MOODS), "marks": {"type": "array", "items": one_of(W.MARKS), "description": "at most 2"}},
        "required": ["who", "action", "at", "item", "eyes", "marks"]}
    place = {"type": "object", "properties": {
        "id": s, "name": s, "kind": one_of(W.PLACE_KINDS), "nature": {"type": "string", "description": "for kind nature, else empty"},
        "wall": one_of(W.WALLS), "floor": one_of(W.FLOORS), "window": one_of(W.WINDOWS), "view": one_of(W.VIEWS),
        "lamp": {"type": "boolean"}, "curtains": {"type": "boolean"},
        "things": {"type": "array", "items": s}, "wall_things": {"type": "array", "items": s},
        "small": {"type": "array", "items": s}, "effects": {"type": "array", "items": one_of(W.EFFECTS)},
        "light": one_of(LIGHTS), "weather": one_of(W.WEATHER),
        "wish": {"type": "string", "description": "what it needs that the library lacks, or empty"}},
        "required": ["id", "name", "kind", "nature", "wall", "floor", "window", "view", "lamp", "curtains", "things",
                     "wall_things", "small", "effects", "light", "weather", "wish"]}
    cast = {"type": "object", "properties": {
        "id": s, "role": s, "hair": one_of(W.HAIRS), "hair_color": one_of(W.HAIR_COLORS),
        "cloth": one_of([c for c in W.CLOTH_COLORS if c != "teal"]), "extras": {"type": "array", "items": one_of(W.EXTRAS)},
        "build": one_of(BUILDS), "height": one_of(HEIGHTS)},
        "required": ["id", "role", "hair", "hair_color", "cloth", "extras", "build", "height"]}
    shot = {"type": "object", "properties": {
        "line": {"type": "integer", "description": "the line's number, or 0 for a quiet shot"},
        "stage": one_of(STAGES), "place": {"type": "string", "description": "a place's id"},
        "light": {"type": "string", "description": "empty, or this shot's light"},
        "weather": {"type": "string", "description": "empty, or this shot's weather"},
        "action": {"type": "string", "description": "what he does (an action), or none"}, "at": s, "item": s,
        "eyes": one_of(W.MOODS), "with": {"type": "string", "description": "hugging, handshake, arguing: the other's id"},
        "marks": {"type": "array", "items": one_of(W.MARKS), "description": "round his head: at most 2"},
        "screen": one_of([""] + list(W.SCREENS), "his phone's screen turned to us, or empty"),
        "others": {"type": "array", "items": person},
        "framing": one_of(FRAMINGS), "close_on": {"type": "string", "description": "detail: the thing; else empty"},
        "move": one_of(W.CAMERA), "event": one_of(_events()), "enter": one_of(W.ENTER),
        "effects": {"type": "array", "items": one_of(W.EFFECTS)}, "label": s, "seconds": {"type": "number"},
        "shows": s},
        "required": ["line", "stage", "place", "light", "weather", "action", "at", "item", "eyes", "with", "marks",
                     "screen", "others",
                     "framing", "close_on", "move", "event", "enter", "effects", "label", "seconds", "shows"]}
    return {"type": "object", "properties": {
        "places": {"type": "array", "items": place}, "cast": {"type": "array", "items": cast},
        "shots": {"type": "array", "items": shot}, "realization": {"type": "integer"},
        "chapters": {"type": "array", "items": s},
        "thumbnail": {"type": "object", "properties": {"shot": {"type": "integer"}, "lead": s, "punch": s},
                      "required": ["shot", "lead", "punch"]},
        "description": s, "tags": {"type": "array", "items": s},
        "habit": {"type": "string", "description": "this story's habit or struggle, shown big: a few words"}},
        "required": ["places", "cast", "shots", "realization", "chapters", "thumbnail", "description", "tags", "habit"]}


# --- the habit, shown big: exaggerated like a cartoon, whatever the story's habit is ---------------------------------------
# (any of the library's exaggerated pieces can serve any story: none belongs to a topic. tools/silhouette_words.IDEAS only
# offers a few ideas for the topics of the owner's list; nothing is drawn from it by force)
HABIT_LEAST = {"fall": 6, "before": 4, "after": 2}   # shots that must show it big
FALL = ("hook", "incident", "collapse", "rock_bottom")    # where the habit grips him
RISE = ("transformation", "payoff")                      # where a virtue story shows the virtue
BIG_EYES = ("hearts", "dollars", "spirals", "droopy", "furious", "side_eye", "smug", "sobbing", "terrified", "fire")
BIGGER = {"sad": ("sobbing", "raincloud"), "angry": ("furious", "steam"), "tired": ("droopy", "zzz"),
          "worried": ("terrified", "sweat"), "wide": ("terrified", "exclaim")}   # a shot's own eyes, made bigger


def _ideas(story: dict) -> dict:
    """A few ideas for the story's topic when it's one of the owner's list (else none)."""
    text = " ".join(str(story.get(k) or "") for k in ("theme", "title", "core_message"))
    name = W.ideas_for(story.get("topic") or "", text)
    return W.IDEAS.get(name) or {}


def _habit_text(story: dict, recent: list[dict]) -> str:
    """The habit shown big, for Gemini: the story's own, with any of the library's exaggerated pieces."""
    virtue = story.get("kind") == "virtue"
    rule = (f"at least {HABIT_LEAST['before']} shots of hook, incident, collapse and rock_bottom show the weakness he "
            f"overcomes big, and at least {HABIT_LEAST['after']} of transformation and payoff the virtue itself"
            if virtue else
            f"at least {HABIT_LEAST['fall']} shots of hook, incident, collapse and rock_bottom show it big, growing as it "
            "grips him")
    ideas = _ideas(story)
    idea = ""
    if ideas:
        bits = [f"{k}: {', '.join(v)}" for k, v in ideas.items() if isinstance(v, list) and v and k != "words"]
        idea = (f"\nA few ideas for {story.get('topic') or 'this topic'} (a starting point, not a rule: use what fits this "
                "story, and anything else): " + "; ".join(bits))
    last = sorted({p for r in recent[:1] for p in r.get("habit_used") or []})
    return ("THE HABIT, SHOWN BIG. Whatever this story's habit or struggle is, the film shows it exaggerated, like a "
            "cartoon, so a stranger sees it at once without a word. Name it in a few words, this story's own (habit), "
            "and show it with the library's exaggerated pieces: any of them, whichever fit this story (none belongs to a "
            "topic): the big eyes (" + ", ".join(BIG_EYES) + "), the marks round a head (" + ", ".join(W.MARKS) + "), "
            "the habit actions (" + ", ".join(W.HABIT_ACTIONS) + "), his phone's screen (" + ", ".join(W.SCREENS) +
            "), the things a habit leaves in his places (" + ", ".join(W.HABIT_PROPS) + "), the effects (" +
            ", ".join(W.HABIT_EFFECTS) + "). " + rule[0].upper() + rule[1:] + ". Vary them: never the same piece in "
            "every shot." + idea + (f"\nThe last story used: {', '.join(last)}: choose others where they fit."
                                    if last else ""))


def _pieces(shot: dict) -> set:
    """The exaggerated pieces a shot shows: his big eyes, the marks round his head, a habit's action, his phone's
    screen, a habit's effect."""
    him = shot.get("him") or {}
    used = set()
    if him.get("eyes") in BIG_EYES:
        used.add(f"eyes:{him['eyes']}")
    used |= {f"mark:{m}" for m in him.get("marks") or [] if m in W.MARKS}
    if him.get("action") in W.HABIT_ACTIONS:
        used.add(f"action:{him['action']}")
    if him.get("screen") in W.SCREENS:
        used.add(f"screen:{him['screen']}")
    used |= {f"effect:{e}" for e in shot.get("effects") or [] if e in W.HABIT_EFFECTS}
    return used


def _show_big(shots: list[dict], stages, least: int, story: dict, last: set, problems: list, notes: list,
              what: str) -> None:
    """At least `least` shots of `stages` showing it big. Short, it goes back to Gemini (a problem), and code shows it
    itself on the shots that can carry it: the pieces this storyboard already chose first (its own habit), then the
    shot's own eyes made bigger (sad: streaming tears and a rain cloud; angry: furious eyes and steam), then the ideas
    for the story's topic when it has some."""
    showing = [s for s in shots if s["stage"] in stages and _pieces(s)]
    short = least - len(showing)
    if short <= 0:
        return
    problems.append(f"the habit shown big ({what}): {len(showing)} shots show it, at least {least} must")
    own = {}
    for s in shots:
        for p in _pieces(s):
            own[p] = own.get(p, 0) + (0.5 if p in last else 1)
    eyes = [p.split(":")[1] for p in sorted(own, key=lambda p: -own[p]) if p.startswith("eyes:")]
    marks = [p.split(":")[1] for p in sorted(own, key=lambda p: -own[p]) if p.startswith("mark:")]
    screens = [p.split(":")[1] for p in sorted(own, key=lambda p: -own[p]) if p.startswith("screen:")]
    ideas = _ideas(story)
    cands = [s for s in shots if s["stage"] in stages and s.get("him") and not _pieces(s)
             and s["him"]["action"] not in ("asleep", "asleep_desk", "none")]
    cands.sort(key=lambda s: (s["him"].get("eyes") not in BIGGER, shots.index(s)))   # (emotional ones first)
    done = 0
    for i, s in enumerate(cands):
        if done >= short:
            break
        him = s["him"]
        mood = him.get("eyes") or ""
        big_eyes = eyes[i % len(eyes)] if eyes else (BIGGER.get(mood, (None, None))[0] or
                                                     (ideas.get("eyes") or [None])[0])
        mark = marks[i % len(marks)] if marks else (BIGGER.get(mood, (None, None))[1] or
                                                    (ideas.get("marks") or [None])[0])
        if stages == RISE:   # (the virtue: fierce resolve in his eyes, no marks)
            big_eyes, mark = ("fire" if mood in ("determined", "open", "") else None), None
        if big_eyes and mood not in ("closed", "happy"):
            him["eyes"] = big_eyes
        if mark and len(him.get("marks") or []) < 2:
            him["marks"] = (him.get("marks") or []) + [mark]
        if him["action"] in ("phone", "lying_awake", "doomscrolling") and not him.get("screen"):
            pick = screens or ideas.get("screens") or []
            him["screen"] = pick[0] if pick else ""
        if _pieces(s):
            done += 1
    if done:
        notes.append(f"code showed it big in {done} more shots ({what})")


def _habits(shots: list[dict], story: dict, recent: list[dict], problems: list, notes: list) -> list[str]:
    """The story's habit shown big in as many shots as HABIT_LEAST asks; returns the pieces the storyboard used."""
    if not shots:
        return []
    last = {p for r in recent[:1] for p in r.get("habit_used") or []}
    if story.get("kind") == "virtue":
        _show_big(shots, FALL, HABIT_LEAST["before"], story, last, problems, notes, "the weakness, before his turn")
        _show_big(shots, RISE, HABIT_LEAST["after"], story, last, problems, notes, "the virtue, after it")
    else:
        _show_big(shots, FALL, HABIT_LEAST["fall"], story, last, problems, notes, "his fall")
    return sorted(set().union(*[_pieces(s) for s in shots]))


# --- what code checks -------------------------------------------------------------------------------------------------------
def _names(items, known: dict, pid: str, notes: list, missing: list) -> list[str]:
    """A place's things as the library names them: aliases and near misspellings fixed; the rest listed as missing."""
    out = []
    for item in items or []:
        w = _word(item.get("thing") if isinstance(item, dict) else item)
        if not w:
            continue
        if w in known:
            out.append(w)
            continue
        alias = ALIASES.get(w)
        close = difflib.get_close_matches(w, list(known), 1, 0.82)
        if alias == "":
            continue
        if alias or close:
            out.append(alias or close[0])
            notes.append(f"{pid}: \"{w.replace('_', ' ')}\" is drawn as {alias or close[0]}")
        else:
            missing.append(f"{w.replace('_', ' ')} (wanted in {pid})")
    return out


def _place(d: dict, pid: str, key: str, notes: list, missing: list, problems: list) -> dict:
    """A place of the storyboard, made safe: a description the library can build (a ready-made set an answer still
    names is built from SET_PLACES' description of it)."""
    import silhouette_scene as SC

    name = _clean(d.get("name"))[:80] or pid.replace("_", " ")
    light = d.get("light") if d.get("light") in LIGHTS else "dusk"
    weather = d.get("weather") if d.get("weather") in W.WEATHER else "clear"
    set_name = _word(d.get("set"))
    if set_name in SET_PLACES:
        notes.append(f"{pid}: the ready-made {set_name.replace('_', ' ')} isn't used any more: built from the library")
        d = {**d, **SET_PLACES[set_name], "wish": ""}
    wish = re.sub(r"^(a|an|the|some)\s+", "", _clean(d.get("wish")).strip(" ."), flags=re.I)
    if wish and wish.lower() not in ("none", "nothing", "n/a", "-", "empty"):
        missing.append(f"{wish} (wanted in {pid})")
    kind = _word(d.get("kind")) or "room"
    spec = {"kind": kind, "wall": _word(d.get("wall")) or "plum", "floor": _word(d.get("floor")) or "wood",
            "window": _word(d.get("window")) or ("big" if kind == "room" else "none"), "view": _word(d.get("view")) or "city",
            "nature": _word(d.get("nature")) or "hills", "lamp": "hanging" if d.get("lamp") else "none",
            "curtains": bool(d.get("curtains")),
            "things": _names(d.get("things"), W.PROPS, pid, notes, missing),
            "wall_things": _names(d.get("wall_things"), W.PROPS, pid, notes, missing),
            "small": _names(d.get("small"), W.PROPS, pid, notes, missing),
            "effects": [e for e in (_word(x) for x in d.get("effects") or []) if e in W.EFFECTS]}
    clean, miss = SC.norm(spec)
    for m in miss:
        missing.append(f"{m.replace('thing: ', '').replace('_', ' ')} (in {pid})")
    out = {"kind": clean["kind"], "wall": clean["wall"], "floor": clean["floor"], "window": clean["window"],
           "view": clean["view"], "nature": clean["nature"], "lamp": clean["lamp"], "curtains": clean["curtains"],
           "things": [t["thing"] for t in clean["things"]], "wall_things": [t["thing"] for t in clean["wall_things"]],
           "small": [t["thing"] for t in clean["small"]], "effects": clean["effects"]}
    big = [t for t in out["things"] if W.PROPS[t][3] in ("back", "mid")]
    if out["kind"] == "room" and len(big) > THINGS_MOST + 1:
        notes.append(f"{pid}: {len(big)} big things is too many for a room (at most {THINGS_MOST}): it runs past the "
                     "frame")
    return {"id": pid, "name": name, "spec": out, "light": light, "weather": weather, "seed": f"{key}/{pid}"}


def _person(c: dict, cid: str, notes: list, problems: list) -> dict:
    role = _clean(c.get("role"))[:80] or cid.replace("_", " ")
    if story_agent.ADULTS.search(role):
        problems.append(f"{cid} ({role}): everyone in the story is an adult")
    words = {"hair": c.get("hair") if c.get("hair") in W.HAIRS else "short",
             "hair_color": c.get("hair_color") if c.get("hair_color") in W.HAIR_COLORS else "black",
             "cloth": c.get("cloth") if c.get("cloth") in W.CLOTH_COLORS else "slate",
             "extras": [e for e in dict.fromkeys(_word(x) for x in c.get("extras") or []) if e in W.EXTRAS],
             "build": c.get("build") if c.get("build") in BUILDS else "average",
             "height": c.get("height") if c.get("height") in HEIGHTS else "average"}
    if words["cloth"] == "teal":   # (his colour)
        words["cloth"] = "navy"
        notes.append(f"{cid}: teal is his colour: {cid} wears navy")
    if "suit" in words["extras"] and "jacket" in words["extras"]:
        words["extras"].remove("jacket")
    import silhouette_board as SB

    return {"id": cid, "role": role, "words": words, "look": SB.look_spec(words)}


def _action(v, notes: list, missing: list, where: str) -> str:
    a = _word(v)
    if a in ("", "none", "nobody", "no_one", "empty", "absent", "null"):
        return "none"
    if a in W.ACTIONS:
        return a
    alias = ACTION_ALIASES.get(a)
    close = difflib.get_close_matches(a, list(W.ACTIONS), 1, 0.8)
    if alias or close:
        notes.append(f"{where}: \"{a.replace('_', ' ')}\" is drawn as {alias or close[0]}")
        return alias or close[0]
    missing.append(f"{a.replace('_', ' ')} (an action, {where})")
    return "standing"


def _at(v) -> str:
    """Where someone is, in the library's words (a thing's other name is its own: "couch" is the sofa)."""
    w = _word(v)
    return ALIASES.get(w) or w


def _item(v) -> str:
    w = _word(v)
    if w in W.ITEMS:
        return w
    return {"phone": "", "cup_of_coffee": "cup", "mug": "cup", "coffee": "cup", "suitcase": "suitcase", "bags": "bag",
            "letters": "letter", "envelope": "letter", "bill": "letter", "bills": "letter", "cash": "money",
            "wine": "glass", "beer": "bottle", "bouquet": "flowers", "present": "gift", "award": "trophy",
            "books": "book", "notebook": "book", "cardboard_box": "box", "boxes": "box"}.get(w, "")


def _order(shots: list[dict]) -> list[dict]:
    """The shots in the script's order: each line's shot, with the quiet shots that followed it kept after it."""
    groups, cur = [], [-1, []]
    for s in shots:
        if s["line_index"] is not None:
            groups.append(cur)
            cur = [s["line_index"], [s]]
        else:
            cur[1].append(s)
    groups.append(cur)
    groups.sort(key=lambda g: g[0])
    return [s for _, ss in groups for s in ss]


def _cover(shots: list[dict], story: dict, problems: list, notes: list) -> list[dict]:
    """Every line its one shot, in the script's order (code's repair: a second shot of a line loses the line, a line
    without one gets a copy of the shot before it)."""
    n = len(story["lines"])
    seen = set()
    for s in shots:
        i = s["line_index"]
        if i is not None and i in seen:
            problems.append(f"line {i + 1} has two shots: one line, one shot (a quiet shot has line 0)")
            s["line_index"] = None
        elif i is not None:
            seen.add(i)
    nums = [s["line_index"] for s in shots if s["line_index"] is not None]
    if nums != sorted(nums):
        wrong = next(b + 1 for a, b in zip(nums, nums[1:]) if b < a)
        problems.append(f"the shots go in the script's order (line {wrong} comes too late or too early)")
        shots = _order(shots)
    lost = [i for i in range(n) if i not in seen]
    if lost:
        problems.append("these lines have no shot: " + ", ".join(str(i + 1) for i in lost[:20])
                        + " (every line gets its own shot)")
        for i in lost:
            before = [k for k, s in enumerate(shots) if s["line_index"] is not None and s["line_index"] < i]
            k = before[-1] if before else -1
            base = shots[k] if k >= 0 else next((s for s in shots if s["line_index"] is not None), shots[0] if shots else None)
            if base is None:
                continue
            copy = json.loads(json.dumps(base))
            copy.update(line_index=i, shows=base.get("shows", ""), label="", enter="cut")
            shots.insert(k + 1, copy)
            notes.append(f"line {i + 1} had no shot: it's over a copy of the shot before it")
    for s in shots:   # (a moment's shot carries its bubbles: code draws them over the speakers' heads)
        i = s["line_index"]
        s["line"] = ""
        s["bubbles"] = json.loads(json.dumps(story["lines"][i].get("bubbles") or [])) if i is not None else []
    return shots


def _speakers_in(shot: dict, cast: dict, where: str, problems: list, notes: list) -> None:
    """Whoever has a bubble in a shot is in its picture: him (standing, when the shot left him out) or the person (code
    puts them in when the shot didn't)."""
    for b in shot.get("bubbles") or []:
        who = b["who"]
        if who == "him":
            if not shot.get("him"):
                notes.append(f"{where}: he has a bubble, so he's in the shot (standing)")
                shot["him"] = {"action": "standing", "at": "spot", "item": "", "eyes": "", "with": "", "marks": [],
                               "screen": ""}
            continue
        if any(o["who"] == who for o in shot.get("others") or []):
            continue
        if who not in cast:
            problems.append(f"{where}: {who} has a bubble but isn't in the cast: add {who} to the cast")
            continue
        notes.append(f"{where}: {who} has a bubble, so they're in the shot (standing)")
        shot.setdefault("others", []).append({"who": who, "action": "standing", "at": "spot", "item": "", "eyes": "",
                                              "marks": []})


def _people_in_cast(cast: dict, story: dict, problems: list, notes: list) -> None:
    """The moments' people are all in the cast, by their ids (the bubbles name them): one missing is a problem, and
    code gives them a plain look meanwhile."""
    for k, person in enumerate(story.get("people") or []):
        if person["id"] in cast:
            continue
        problems.append(f"the cast leaves out {person['id']} ({person['role']}): give them a look")
        hair = ("short", "long", "bun", "short")[k % 4]
        cast[person["id"]] = _person({"id": person["id"], "role": person["role"], "hair": hair,
                                      "hair_color": ("brown", "black", "grey", "auburn")[k % 4],
                                      "cloth": ("navy", "wine", "olive", "grey", "plum", "mustard")[k % 6], "extras": [],
                                      "build": "average", "height": "average"}, person["id"], notes, problems)


def plates_of(story: dict) -> list[dict]:
    """The story's scenes as the Animator, the Reviewer and the Studio keep them: one per shot ("s1", ...), with what it
    shows."""
    places = {p["id"]: p for p in story.get("places") or []}
    return [{"id": s["plate"], "scene": s.get("shows") or "", "him": (s.get("him") or {}).get("action") or "none",
             "light": s.get("light") or (places.get(s.get("place")) or {}).get("light"), "place": s.get("place"),
             "redraws": int(s.get("redraws") or 0)} for s in story["shots"]]


def seat(shot: dict, marks: dict, where: str, problems: list, notes: list) -> None:
    """Puts the shot's people on their marks, him first (tools/silhouette_board.where: a thing's right spot for what
    they do); an action with nowhere to happen in the place is a problem (they stand somewhere meanwhile)."""
    import silhouette_board as SB

    him, taken = shot.get("him"), set()
    for person in ([him] if him else []) + list(shot.get("others") or []):
        if him and person is not him and person["who"] == him.get("with"):
            continue   # (drawn with him: a hug, a handshake, an argument)
        action = person["action"]
        name, why = SB.where(marks, action, person.get("at") or "", taken)
        if name is None:
            need = NEEDS[W.ACTIONS[action][1]]
            problems.append(f"{where}: {action.replace('_', ' ')} needs {need}, and {shot['place']} has none: put one in "
                            "the place or change the action")
            name = SB.fallback(marks, action, taken)
        elif why:
            notes.append(f"{where}: {why}")
        person["mark"] = name
        if name:
            taken.add(name)


def reseat(story: dict) -> list[str]:
    """A storyboarded story's people put on their marks again (after the library or where() changed): what moved."""
    import silhouette_board as SB

    notes, problems = [], []
    for k, s in enumerate(story.get("shots") or []):
        place = SB.place_of(story, s["place"])
        if place.get("set"):
            continue
        before = [(p or {}).get("mark") for p in [s.get("him")] + list(s.get("others") or [])]
        seat(s, SB.probe(place["spec"], place.get("seed") or place["id"])["marks"], f"shot {k + 1}", problems, notes)
        after = [(p or {}).get("mark") for p in [s.get("him")] + list(s.get("others") or [])]
        if before != after:
            notes.append(f"shot {k + 1}: {before} -> {after}")
    return problems + notes


def check(raw: dict, story: dict, recent: list[dict] | None = None) -> tuple[dict, list[str], list[str]]:
    """The storyboard as code can take it ({"places", "cast", "shots", "realization", "chapters", "thumbnail",
    "description", "tags", "missing", "hard"}), what's wrong with it (problems: it goes back) and what code changed or
    could be better (notes)."""
    import silhouette_board as SB

    problems, notes, missing = [], [], []
    key = story_key(story)
    recent = recent or []
    # the places
    places, by_id = [], {}
    for k, d in enumerate(raw.get("places") or []):
        pid = _id(d.get("id") or d.get("name"), f"place_{k + 1}")
        while pid in by_id:
            pid += "_2"
        place = _place(d, pid, key, notes, missing, problems)
        places.append(place)
        by_id[pid] = place
    if not places:
        problems.append("there are no places")
        places = [{"id": "room", "name": "a room", "spec": {"kind": "room"}, "light": "dusk", "weather": "clear",
                   "seed": f"{key}/room"}]
        by_id = {"room": places[0]}
    info = {pid: SB.probe(p["spec"], p["seed"]) for pid, p in by_id.items()}
    for pid, i in info.items():
        for m in i["missing"]:
            missing.append(f"{m} (in {pid})")
    # the cast
    cast = {}
    for k, c in enumerate(raw.get("cast") or []):
        cid = _id(c.get("id") or c.get("role"), f"person_{k + 1}")
        if cid in HERO or _word(c.get("role")) in HERO:
            notes.append(f"the cast is the people around him: {cid} (him) left out")
            continue
        while cid in cast:
            cid += "_2"
        cast[cid] = _person(c, cid, notes, problems)
    _people_in_cast(cast, story, problems, notes)
    if len(cast) > CAST_MOST:
        notes.append(f"{len(cast)} people: at most {CAST_MOST}")
    # the shots
    shots, n, prev = [], len(story["lines"]), {"stage": "hook", "place": places[0]["id"]}
    raw_shots = raw.get("shots") or []
    if not raw_shots:
        problems.append("there are no shots")
    for j, s in enumerate(raw_shots):
        where = f"shot {j + 1}"
        try:
            num = int(s.get("line") or 0)
        except (TypeError, ValueError):
            num = 0
        if not 0 <= num <= n:
            problems.append(f"{where}: there's no line {num} (the script has {n})")
            num = 0
        if num:
            where = f"line {num}"
        stage = s.get("stage") if s.get("stage") in STAGES else prev["stage"]
        pid = _id(s.get("place"), "")
        if pid not in by_id:
            close = difflib.get_close_matches(pid, list(by_id), 1, 0.7)
            if close:
                notes.append(f"{where}: the place \"{pid}\" is {close[0]}")
                pid = close[0]
            else:
                problems.append(f"{where}: there's no place \"{pid}\" (the places are {', '.join(by_id)})")
                pid = prev["place"]
        action = _action(s.get("action"), notes, missing, where)
        him = None
        if action != "none":
            him = {"action": action, "at": _at(s.get("at")), "item": _item(s.get("item")),
                   "eyes": s.get("eyes") if s.get("eyes") in W.MOODS else "", "with": _id(s.get("with"), ""),
                   "marks": [x for x in dict.fromkeys(_word(m) for m in s.get("marks") or []) if x in W.MARKS][:2],
                   "screen": s.get("screen") if s.get("screen") in W.SCREENS else ""}
        others = []
        for o in s.get("others") or []:
            who = _id(o.get("who"), "")
            if who in HERO or not who:
                continue
            if who not in cast:
                close = difflib.get_close_matches(who, list(cast), 1, 0.75)
                if close:
                    who = close[0]
                else:
                    problems.append(f"{where}: \"{who}\" isn't in the cast: add them to the cast, or leave them out")
                    continue
            if any(x["who"] == who for x in others):
                continue
            oa = _action(o.get("action"), notes, missing, where)
            others.append({"who": who, "action": "standing" if oa == "none" else oa, "at": _at(o.get("at")),
                           "item": _item(o.get("item")), "eyes": o.get("eyes") if o.get("eyes") in W.MOODS else "",
                           "marks": [x for x in dict.fromkeys(_word(m) for m in o.get("marks") or [])
                                     if x in W.MARKS][:2]})
        if len(others) > OTHERS_MOST:
            notes.append(f"{where}: at most {OTHERS_MOST} others in a shot")
            others = others[:OTHERS_MOST]
        if him and him["action"] in W.PAIRS:
            mate = him["with"] if him["with"] in cast else (others[0]["who"] if len(others) == 1 else "")
            if not mate:
                problems.append(f"{where}: {him['action']} needs with: the other one's id (and them in the cast)")
                him["action"] = "standing"
            else:
                him["with"] = mate
                if not any(o["who"] == mate for o in others):
                    others.append({"who": mate, "action": "standing", "at": him["at"], "item": "", "eyes": ""})
        elif him:
            him["with"] = ""
        framing = s.get("framing") if s.get("framing") in FRAMINGS else "wide"
        close_on = _word(s.get("close_on"))
        close_on = ALIASES.get(close_on, close_on)
        effects = [e for e in (_word(x) for x in s.get("effects") or []) if e in W.EFFECTS]
        label = _clean(s.get("label")).upper()[:28]
        shows = _clean(s.get("shows"))
        if not shows:
            problems.append(f"{where}: say what the picture shows (shows)")
        try:
            seconds = float(s.get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        shot = {"line_index": num - 1 if num else None, "line": "", "bubbles": [],
                "stage": stage, "place": pid, "light": s.get("light") if s.get("light") in LIGHTS else "",
                "weather": s.get("weather") if s.get("weather") in W.WEATHER else "", "him": him, "others": others,
                "framing": framing, "close_on": close_on if framing == "detail" else "",
                "move": s.get("move") if s.get("move") in W.CAMERA else "hold",
                "event": s.get("event") if s.get("event") in _events() else "none",
                "enter": s.get("enter") if s.get("enter") in W.ENTER else "cut", "effects": effects, "label": label,
                "seconds": seconds, "shows": shows[:SHOWS_MOST]}
        shots.append(shot)
        prev = {"stage": stage, "place": pid}
    if not shots:
        return ({"places": places, "cast": list(cast.values()), "shots": [], "realization": 0, "chapters": {},
                 "thumbnail": {}, "description": "", "tags": [], "missing": missing, "hard": []},
                problems or ["there are no shots"], notes)
    picked = {}   # (the shots Gemini named, before code moves any)
    for name in ("realization",):
        try:
            picked[name] = shots[int(raw.get(name)) - 1] if 1 <= int(raw.get(name)) <= len(shots) else None
        except (TypeError, ValueError):
            picked[name] = None
    try:
        tk = int((raw.get("thumbnail") or {}).get("shot") or 0)
        picked["thumbnail"] = shots[tk - 1] if 1 <= tk <= len(shots) else None
    except (TypeError, ValueError):
        picked["thumbnail"] = None
    shots = _cover(shots, story, problems, notes) if shots else shots
    # the stages, in order, all six
    last = 0
    for s in shots:
        k = STAGES.index(s["stage"])
        if k < last:
            problems.append(f"line {s['line_index'] + 1 if s['line_index'] is not None else '(quiet)'}: the stages go "
                            f"in order ({s['stage']} after {STAGES[last]})")
            s["stage"] = STAGES[last]
        last = max(last, k)
    lacking = [STAGE_NAMES[x] for x in STAGES if x not in {s["stage"] for s in shots}]
    if lacking and shots:
        problems.append("every stage has its shots: none for " + ", ".join(lacking))
    # the habit shown big in enough shots (code shows it itself when the answer falls short)
    habit_used = _habits(shots, story, recent, problems, notes)
    habit = _clean(raw.get("habit"))[:80]
    # each shot's people on their marks, its framing, its seconds
    quiet, labels = 0, 0
    for k, s in enumerate(shots):
        where = f"line {s['line_index'] + 1}" if s["line_index"] is not None else f"shot {k + 1} (quiet)"
        _speakers_in(s, cast, where, problems, notes)
        if s["line_index"] is None or not s["bubbles"]:   # (a quiet shot, or a moment told by its picture alone)
            quiet += s["line_index"] is None
            s["seconds"] = round(min(6.5, max(2.5, s["seconds"] or story_agent.QUIET_MOMENT)), 2)
        else:
            s["seconds"] = round(story_agent.bubbles_span(s["bubbles"]) + story_agent.MOMENT_LEAD
                                 + story_agent.MOMENT_TAIL, 2)
        if s["label"]:
            labels += 1
            if labels > LABELS_MOST:
                s["label"] = ""
        pinfo = info[s["place"]]
        seat(s, pinfo["marks"], where, problems, notes)
        if s["framing"] == "detail" and s["close_on"] not in {t["name"] for t in pinfo["things"]}:
            notes.append(f"{where}: a detail of \"{s['close_on']}\", which isn't in {s['place']}: close on him instead")
            s["framing"], s["close_on"] = ("close" if s["him"] else "wide"), ""
        if s["framing"] in ("medium", "close") and not s["him"] and not s["others"]:
            s["framing"] = "wide"
    if labels > LABELS_MOST:
        notes.append(f"{labels} labels: at most {LABELS_MOST} (the rest dropped)")
    if not QUIET[0] <= quiet <= QUIET[1]:
        notes.append(f"{quiet} quiet shots: {QUIET[0]}-{QUIET[1]} give the film room to breathe")
    for k, s in enumerate(shots):
        s["plate"] = f"s{k + 1}"
        s["act"] = s["stage"]
    plates = plates_of({"places": places, "shots": shots})
    # places and people no shot uses; how many places
    used = {s["place"] for s in shots}
    for p in [p for p in places if p["id"] not in used]:
        notes.append(f"{p['id']} has no shot: left out")
    places = [p for p in places if p["id"] in used]
    in_shots = {o["who"] for s in shots for o in s["others"]} | {s["him"]["with"] for s in shots if s["him"]}
    for cid in [c for c in cast if c not in in_shots]:
        notes.append(f"{cid} is in no shot: left out")
    cast = {c: v for c, v in cast.items() if c in in_shots}
    if not PLACES[0] <= len(places) <= PLACES[1]:
        (problems if len(places) < PLACES[0] - 1 else notes).append(
            f"{len(places)} places: design {PLACES[0]}-{PLACES[1]} (a home can be several: his desk, his kitchen, his "
            "bedroom; where the incident happens, where he hits bottom, where he changes, his new life)")
    for pid in used:
        share = sum(1 for s in shots if s["place"] == pid) / len(shots)
        if share > PLACE_SHARE:
            problems.append(f"{pid} has {share:.0%} of the shots: at most a third in one place (its other rooms and "
                            "corners, other places of the story)")
    # different from the recent stories
    _vary(places, recent, notes)
    # the realization, the chapters, the thumbnail, the words for YouTube
    rk = shots.index(picked["realization"]) if picked.get("realization") in shots else -1
    if rk < 0 or shots[rk]["stage"] not in ("rock_bottom", "transformation"):
        later = [k for k, s in enumerate(shots) if s["stage"] == "rock_bottom"]
        rk = later[-1] if later else next((k for k, s in enumerate(shots) if s["stage"] == "transformation"),
                                          len(shots) // 2)
        notes.append(f"the realization is shot {rk + 1} (in rock bottom or the first of the transformation)")
    chapters = [_clean(c).strip(" .\"'")[:40] for c in raw.get("chapters") or []]
    if len(chapters) != 6 or not all(1 <= len(c.split()) <= 6 for c in chapters):
        notes.append("chapters: six short names, one for each stage")
    chapters = {stage: (chapters[k] if k < len(chapters) and 1 <= len(chapters[k].split()) <= 6 else STAGE_NAMES[stage])
                for k, stage in enumerate(STAGES)}
    thumb = raw.get("thumbnail") or {}
    lead, punch = _clean(thumb.get("lead")).strip(" .\"'"), _clean(thumb.get("punch")).strip(" .\"'")
    if not 1 <= len(lead.split()) <= 4 or not 1 <= len(punch.split()) <= 3 or re.search(r"[#@]|[\U0001F300-\U0001FAFF]",
                                                                                         lead + punch):
        problems.append("the thumbnail's words: lead 1-4 words (white), punch 1-3 words (yellow), no hashtags or emoji")
    tk = shots.index(picked["thumbnail"]) if picked.get("thumbnail") in shots else -1
    if tk < 0:
        problems.append("the thumbnail's shot: a shot's number (1 = the first)")
        tk = rk
    elif not shots[tk]["him"]:
        notes.append(f"the thumbnail's shot {tk + 1} doesn't have him in it")
    description = re.sub(r"https?://\S+|#\w+", "", _clean(raw.get("description"))).strip()[:700]
    if len(description.split()) < 8:
        problems.append("the description: 2-3 sentences for YouTube")
    tags = list(dict.fromkeys(_clean(t).lower().strip("#")[:30] for t in raw.get("tags") or [] if _clean(t)))[:15]
    if len(tags) < 5:
        notes.append("tags: 6-12 search words")
    texts = [s["shows"] for s in shots] + [c["role"] for c in cast.values()] + list(chapters.values()) + [
        lead, punch, description, *tags] + [b["text"] for s in shots for b in s.get("bubbles") or []]
    hard = story_agent.rules_broken(" ".join(texts))
    hard += [p for p in problems if "everyone in the story is an adult" in p]
    problems += [h for h in hard if h not in problems]
    board = {"places": places, "cast": list(cast.values()), "shots": shots, "plates": plates, "realization": rk,
             "chapters": chapters,
             "thumbnail": {"shot": tk + 1, "lead": lead, "punch": punch}, "description": description, "tags": tags,
             "missing": list(dict.fromkeys(missing)), "hard": hard, "habit": habit, "habit_used": habit_used}
    return board, problems, notes


def _vary(places: list[dict], recent: list[dict], notes: list) -> None:
    """A place too like one of the recent stories' (the same kind, and its walls or most of its things) gets other
    colours and its things the other way round."""
    seen = []
    for r in recent[:3]:
        for p in r.get("places") or []:
            if p.get("spec"):
                s = p["spec"]
                seen.append((s.get("kind"), s.get("nature"), s.get("wall"), set(s.get("things") or []), r.get("title")))
    used_walls = {w for _, _, w, _, _ in seen}
    for p in places:
        s = p.get("spec")
        if not s:
            continue
        mine = set(s["things"])
        for kind, nature, wall, things, title in seen:
            if kind != s["kind"] or (kind == "nature" and nature != s["nature"]) or not mine:
                continue
            overlap = len(things & mine) / max(1, len(things | mine))
            indoors = kind in ("room", "hall", "corridor")
            if overlap >= 0.5 or (indoors and wall == s["wall"] and overlap >= 0.25):
                free = [w for w in W.WALLS if w not in used_walls and w != s["wall"]]
                if kind in ("room", "hall", "corridor") and free:
                    s["wall"] = free[int(hashlib.sha1(p["id"].encode()).hexdigest(), 16) % len(free)]
                s["things"] = list(reversed(s["things"]))
                notes.append(f"{p['id']} looked like a place of \"{title}\": its colours and layout changed")
                break


# --- the storyboard -----------------------------------------------------------------------------------------------------------
def recent_boards(days: int = 60, leave_out: str = "") -> list[dict]:
    """The recent stories' places, newest first (the stories set aside left out)."""
    import db
    import series

    out = []
    for v in db.recent_videos(days=days, parts=("brief", "story.title", "story.places", "story.habit_used")):
        st = v["plan"].get("story") or {}
        if v["format"] != series.STORY or v["status"] == "skipped" or not v["plan"].get("brief"):
            continue
        if leave_out and st.get("title") == leave_out:
            continue
        out.append({"title": st.get("title") or "", "places": st.get("places") or [],
                    "habit_used": st.get("habit_used") or []})
    return out[:6]


def design(story: dict, progress=log, recent: list[dict] | None = None, keep_raw: bool = False) -> dict:
    """The story with its storyboard: places, cast, shots, realization, chapters, thumbnail, description, tags, missing
    (what the library lacked), board_notes (what code changed) and board_model (Gemini's model that drew it up).
    Raises when no try keeps the channel's rules. keep_raw: Gemini's answer kept too ("_raw": for tests)."""
    recent = recent_boards(leave_out=story.get("title") or "") if recent is None else recent
    text = system(story, recent)
    best, complaints, raw = None, [], {}
    for attempt in range(TRIES):
        prompt = f"Storyboard \"{story['title']}\": every moment its shot, in order."
        if complaints:
            prompt += ("\n\nYour last storyboard is below, with these problems. Make it again with every one fixed, "
                       "keeping what works:\n- " + "\n- ".join(complaints[:30])
                       + "\nThe storyboard: " + json.dumps(raw, ensure_ascii=False))
        progress("Designing the storyboard" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        answered = dict(llm.calls)
        raw = llm.generate_json([prompt], schema(), text, careful=True, thinking="MEDIUM", timeout_ms=300_000,
                               patient=True, strong=True, progress=progress)
        model = next((m for m, n in llm.calls.items() if n > answered.get(m, 0)), "")
        if llm.passed_over:
            progress(f"Answered by {model}; passed over: " + " | ".join(f[:160] for f in llm.passed_over))
        board, problems, notes = check(raw, story, recent)
        board["board_model"] = model
        if keep_raw:
            board["_raw"] = raw
        if best is None or (len(problems), len(notes)) < (len(best[1]), len(best[2])):
            best = (board, problems, notes)
        if not problems:
            break
        complaints = problems + notes[:10]
        progress("Storyboard problems: " + "; ".join(problems[:5]))
    board, problems, notes = best
    hard = board.pop("hard")
    if hard:
        raise RuntimeError("the storyboard keeps breaking the rules: " + "; ".join(hard[:4]))
    if problems:
        progress("Kept with code's repairs: " + "; ".join(problems[:5]))
    shots = board["shots"]
    progress(f"Storyboard: {len(board['places'])} places, {len(board['cast'])} people, {len(shots)} shots "
             f"({sum(1 for s in shots if s['line_index'] is None)} quiet)"
             + (f"; missing from the library: {', '.join(board['missing'][:6])}" if board["missing"] else ""))
    return {**story, **board, "board_notes": problems + notes}


def run(story: dict, progress=log) -> dict:
    """design(), logged as Agent 3's work."""
    def work(story, progress=log):
        done = design(story, progress)
        return {"story": done, "places": len(done["places"]), "shots": len(done["shots"]), "missing": done["missing"]}

    return act("animator", f"Storyboard: {story.get('title', '')}", work, story, progress=progress)["story"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("script", help="a story from agents/story.py --out (JSON)")
    parser.add_argument("--out", required=True, help="where the storyboarded story goes (JSON)")
    parser.add_argument("--recent", nargs="*", default=None, help="storyboarded stories to differ from (else the "
                        "channel's recent stories)")
    parser.add_argument("--fresh", action="store_true", help="no recent stories to differ from")
    args = parser.parse_args()
    data = json.loads(Path(args.script).read_text(encoding="utf-8"))
    story = data.get("story") or data
    recent = [] if args.fresh else None
    if args.recent:
        recent = []
        for path in args.recent:
            other = json.loads(Path(path).read_text(encoding="utf-8"))
            other = other.get("story") or other
            recent.append({"title": other.get("title"), "places": other.get("places") or []})
    try:
        done = design(story, recent=recent, keep_raw=True)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    raw = done.pop("_raw", None)
    Path(args.out).write_text(json.dumps({**data, "story": done} if "story" in data else done, indent=1,
                                         ensure_ascii=False), encoding="utf-8")
    Path(args.out).with_suffix(".gemini.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{args.out}: {len(done['shots'])} shots, Gemini calls: {dict(llm.calls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
