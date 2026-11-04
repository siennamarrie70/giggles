"""
The Constructivist Montage look's director: turns a script (your Agent 3 prompt's, word for word) and the case's real material
(tools/archive_find.py) into the scenes tools/montage_render.py draws.

Your Agent 4 prompt designs AI pictures and stock scenes, so it can't direct this look; it stays with the faceless look, unchanged.
DIRECTOR below is this look's own prompt, written from the style's rules (you're welcome to write your own, as you did the others). Gemini
chooses, and code decides what's exact:

  repair(raw, script, pack)   every line in one scene, in order; known formats and pictures only; the opening is the title, the twist gets the
                              result and the silent beat before it; grounds and directions alternate so every cut conflicts; a number
                              on screen must come from a checked fact of its own lines or from what he says, otherwise it comes off
  fallback(script, pack)      a sound film from the script's roles alone, when Gemini's answer can't be used
  stock_share(manifest, pack) real pictures stay at least half of what's shown: stock never takes the title or the result

Manifest (montage.v1): {"schema": "montage.v1", "scenes": [{"format", "lines": [line numbers], "items": [ids], "big", "unit", "words": [...],
"ground": "paper"|"ink"|"red", "side": 1|-1, "wipe": bool}]}, with a silent beat as a scene with no lines.

Usage:
    python tools/montage.py --check plan.json     # what repair and the rules make of a saved plan's design
"""

import argparse
import json
import math
import re
import sys

import a3
import llm
import spoken
import text_clean
from archive_find import on_screen

SCHEMA_VERSION = "montage.v1"
FORMATS = ("title", "window", "stack", "grid", "strips", "freeze", "staircase", "question", "acceleration", "exposure", "tower", "result")
LEAST_ITEMS = {"title": 2, "window": 2, "stack": 1, "grid": 5, "strips": 4, "freeze": 1, "staircase": 3, "question": 1, "acceleration": 5,
               "exposure": 2, "tower": 4, "result": 2}
MOST_ITEMS = {"title": 4, "window": 6, "stack": 5, "grid": 8, "strips": 6, "freeze": 3, "staircase": 6, "question": 1, "acceleration": 10,
              "exposure": 4, "tower": 10, "result": 3}
EVERY_SECONDS = {"title": 1.0, "window": 1.25, "stack": 1.0, "freeze": 3.0, "staircase": 1.0, "exposure": 2.0}  # a new picture this often, so nothing sits still
WORDS_PER_SECOND = 2.45  # (his usual pace, 2026-11)
FIXED_GROUND = {"title": "paper", "freeze": "ink", "question": "ink", "acceleration": "ink", "exposure": "red", "tower": "paper", "result": "paper"}
FALLBACK_FOR = {"hook": "title", "stakes": "window", "open_loop_1": "question", "escalation": "grid", "close_loop_1": "freeze", "open_loop_2": "stack",
                "climax": "acceleration", "close_loop_2": "tower", "twist": "result", "loop_bridge": "window"}
ROLE_CYCLE = ("strips", "staircase", "exposure", "freeze", "window", "stack", "grid")
MAX_LINES = 3            # lines a scene may hold
MAX_WORD_LINE = 26       # characters of one line of words on screen
MAX_BIG = 16             # characters of the big word or number
MAX_UNIT = 24
MAX_WIPES = 4
TRIES = 2
CARD_WORDS = re.compile(r"\b(?:subscribe|follow|like|comment|link in bio|part \d+)\b", re.IGNORECASE)

DIRECTOR = """You direct a one-minute documentary Short for adults in the Constructivist Montage style: real archive film, photographs and
documents, all printed in black ink on cream paper with one red, cut hard to a machine beat, with type on diagonal bands. The argument comes from
how real pictures are cut and set. You don't write words for him to say: his script is fixed and comes to you word for word. You choose, for each
moment of the script, the shot, the pictures, and the few words on screen.

THE SHOTS (the format field):
- title: the opening. A red band lands, film runs above it, a word or number is stamped below it letter by letter. big: the opening's strongest
  word or number. words: one short line on the band, usually the place and year.
- window: a tall window of film leaning along the diagonal. big: a date or number on a red band. words: a few words turned up the side.
- stack: the words are the structure, each line the full width of the frame, slammed in from alternate sides. words: 2 to 4 lines of 1 to 3 words
  each; big: the last line, printed in red. For the line that must be read.
- grid: nine windows light up one by one and count; the middle lights last with the number. big: the number at the middle. words: a label. Use it
  when he counts or names many things. Needs at least 5 pictures.
- strips: the frame turned on the diagonal, three strips of film drifting in opposite directions, a panel changing on every beat: a machine at work,
  people at work, a system running. big or words: one short label. Needs at least 4 pictures.
- freeze: a flash, one frozen frame, a red ring drawn on what matters, and a number in a red block. big: the number. unit: what it counts. 1 to 3 pictures.
- staircase: three windows rising in steps with a counter climbing. Use it for a process or a rise over time. big: the number it climbs to. unit: what
  it counts. 3 to 6 pictures.
- question: black ground, the question's words on a tilted paper tab ringed in red, then a huge red question mark. words: the question, in 2 or 3 short
  lines. Use it where he opens a question. 1 picture.
- acceleration: cuts halving from half a second to an eighth, the ground flashing red and black, a counter jumping with every cut. big: the number it
  ends on. unit: what it counts. No other words: nobody can read them this fast. Needs at least 5 pictures. Use it where things pile up.
- exposure: two films printed through each other on a red ground, with the answer in a black block. big: the number or word. unit: a short line. 2 or 3
  pictures. Use it where he gives an answer.
- tower (the signature shot): floors of film and photographs slam in from alternate sides, one per sixteenth of a beat, with people cut out of
  photographs standing on them, while a counter climbs. big: the number it ends on. unit: what it counts. Needs at least 4 pictures; pictures marked
  "has a cut-out person" make it work. Use it once at most, for scale, for many people or for something being built.
- result: the heaviest hit of the film. A huge number, a tall slanted window, a tilted photograph, a red wedge. big: the number or word. unit: what it
  counts. Use it for the twist. 2 or 3 pictures.

RULES:
- Every line of the script belongs to exactly one scene, in order. A scene holds 1 to 3 lines. Aim for 10 to 16 scenes. Vary them: never the same
  format twice in a row, and use at least 6 different formats.
- The first scene is the title. The twist line's scene is the result.
- Use the pictures that show what he's saying at that moment. Film before photographs wherever you have both. Spread the pictures: use every one at
  least once. Don't put stock clips (kind: stock) in the title or the result, and use them only where nothing real fits.
- The words on screen are few: big at most 2 words or one number (up to 14 characters); unit at most 3 words; each line of words at most 4 words. Write
  numbers in digits on screen ("93 MINUTES", "1913", "$5 A DAY"), even though he says them in words.
- Every number on screen must be one he says in those lines, or one in those lines' facts, exactly. Never round it, never work one out, never invent
  one. If a scene has no number, big is a word from what he says, or leave big and unit empty.
- Words on screen say the same thing he says. They never add a claim. Never name a child or mention one. No hashtags, no calls to subscribe.
- A format with big and unit reads best when they're short and concrete: not "A VERY LONG TIME", but "12 HOURS".
- Anything on screen must make sense on its own to someone with the sound off, as a headline would: "REFUSED SURGERY", "THE LAST SHOW", "AGE 52". Never
  a fragment cut out of his sentence ("DID BLOW CAUSE", "STAGE DETROIT"), and never a label for its own sake. If you can't say it well in those few
  words, leave it out: a scene can run on pictures alone.
- Give each scene as many pictures as it can use, so it keeps cutting while he speaks: about one picture for every second of speech."""

SCHEMA = {"type": "object", "properties": {"scenes": {"type": "array", "items": {"type": "object", "properties": {
    "lines": {"type": "array", "items": {"type": "integer"}, "description": "the script's line numbers this scene holds, from 0"},
    "format": {"type": "string", "enum": list(FORMATS)},
    "items": {"type": "array", "items": {"type": "string"}, "description": "the ids of the pictures it shows"},
    "big": {"type": "string"}, "unit": {"type": "string"}, "words": {"type": "array", "items": {"type": "string"}}},
    "required": ["lines", "format", "items", "big", "unit", "words"]}}}, "required": ["scenes"]}


def items_of(pack: dict) -> list[dict]:
    """The case's pictures, film first."""
    return [*(pack.get("archive") or []), *(pack.get("images") or []), *(pack.get("footage") or [])]


def kinds(pack: dict) -> dict[str, str]:
    return {i["id"]: i.get("kind") or "photo" for i in items_of(pack)}


def _allowed_numbers(lines: list[dict], pack: dict) -> set[float]:
    """The numbers that may go on screen for these lines: what he says in them and what their checked facts say."""
    facts = {f["id"]: f for f in pack.get("facts") or []}
    have: set[float] = set()
    for line in lines:
        have |= spoken.said_numbers(line.get("text") or "")
        for fid in line.get("facts") or []:
            have |= spoken.written_numbers((facts.get(fid) or {}).get("claim") or "")
    return have


def _numbers_shown(text: str) -> set[float]:
    """The numbers in words on screen, each as a value: a number's scale counts ("$5 A DAY" is 5; "15M" is 15 or 15 million)."""
    found = set()
    for raw, scale in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*([KMB])?\b", text):
        found.add((float(raw.replace(",", "")), scale))
    return found


def number_ok(text: str, allowed: set[float]) -> bool:
    """Is every number on screen one he says or his facts say? A year written in figures counts too."""
    size = {"K": 1e3, "M": 1e6, "B": 1e9}
    for value, scale in _numbers_shown(text):
        wanted = value * size.get(scale, 1)
        if not any(abs(wanted - a) < 1e-6 * max(1.0, abs(a)) or abs(value - a) < 1e-9 for a in allowed):
            return False
    return True


def _clean_words(value, limit: int) -> str:
    text = on_screen(value, limit)
    return "" if (a3.CHILD_WORDS.search(text) or CARD_WORDS.search(text)) else text


def _text(scene: dict, lines: list[dict], pack: dict) -> dict:
    """A scene's words, cleaned; a number nobody said comes off."""
    allowed = _allowed_numbers(lines, pack)
    keep = lambda t: t if number_ok(t, allowed) else ""  # noqa: E731
    big, unit = keep(_clean_words(scene.get("big"), MAX_BIG)), keep(_clean_words(scene.get("unit"), MAX_UNIT))
    words = [t for t in (keep(_clean_words(w, MAX_WORD_LINE)) for w in (scene.get("words") or [])[:4]) if t]
    words = [w for w in dict.fromkeys(words) if w not in (big, unit)]  # (no line twice)
    if scene.get("format") == "question":  # the question on screen is the one he asks, in his own words
        asked = next((line["text"] for line in lines if "?" in line["text"]), lines[0]["text"] if lines else "")
        words = _wrapped(_clean_words(asked, 60))
        big, unit = "", ""
    return {"big": big, "unit": unit, "words": words}


def _wrapped(text: str, width: int = 18, most: int = 3) -> list[str]:
    """A sentence as a few short lines."""
    lines, row = [], ""
    for word in text.split():
        if row and len(row) + 1 + len(word) > width and len(lines) < most - 1:
            lines.append(row)
            row = word
        else:
            row = f"{row} {word}".strip()
    return lines + [row] if row else lines


def _covered(raw_scenes: list[dict], count: int) -> list[dict]:
    """The scenes with every line in exactly one, in order: a line left out joins the scene before it, a scene too long is split, a scene
    with nothing left of its own goes."""
    seen, out = set(), []
    for scene in raw_scenes:
        mine = sorted({int(k) for k in scene.get("lines") or [] if isinstance(k, (int, float)) and 0 <= int(k) < count} - seen)
        if not mine:
            continue
        seen |= set(mine)
        out.append({**scene, "lines": mine})
    # holes: each scene runs from its first line up to the next scene's first line
    out.sort(key=lambda s: s["lines"][0])
    firsts = [s["lines"][0] for s in out]
    if not out:
        return [{"format": "window", "lines": list(range(count)), "items": [], "big": "", "unit": "", "words": []}]
    firsts[0] = 0
    made = []
    for k, scene in enumerate(out):
        end = firsts[k + 1] if k + 1 < len(firsts) else count
        span = list(range(firsts[k], end))
        for i in range(0, len(span), MAX_LINES):
            part = span[i:i + MAX_LINES]
            made.append({**scene, "lines": part} if not i else {"format": "window", "lines": part, "items": [], "big": "", "unit": "", "words": []})
    return made


def _least_used(pool: list[str], used: dict[str, int], avoid: set[str], want_real: bool, kind_of: dict[str, str]) -> str | None:
    order = [p for p in pool if p not in avoid]
    if want_real:
        real = [p for p in order if kind_of.get(p) != "stock"]
        order = real or order
    return min(order, key=lambda p: (used.get(p, 0), kind_of.get(p) == "stock", pool.index(p)), default=None)


def _settle_items(scenes: list[dict], pack: dict, texts: list[str] | None = None) -> None:
    """Known pictures only, enough of them for each format to keep cutting for as long as its lines will run, and no more; every picture
    shown somewhere; stock kept out of the title and the result, and at most half of what's shown."""
    texts = texts or []
    kind_of = kinds(pack)
    pool = list(kind_of)
    used: dict[str, int] = {}
    for scene in scenes:
        fmt = scene["format"]
        want_real = fmt in ("title", "result", "freeze")
        mine = []
        for item in scene.get("items") or []:
            item = str(item)
            if item in kind_of and item not in mine and not (want_real and kind_of[item] == "stock"):
                mine.append(item)
        mine = mine[:MOST_ITEMS.get(fmt, 4)]
        words = sum(len(texts[n].split()) for n in scene.get("lines") or [] if n < len(texts))
        wanted = math.ceil(words / WORDS_PER_SECOND / EVERY_SECONDS[fmt]) if fmt in EVERY_SECONDS else 0
        need = min(max(LEAST_ITEMS.get(fmt, 1), min(wanted, MOST_ITEMS.get(fmt, 4))), len(pool))
        while len(mine) < need:
            extra = _least_used(pool, used, set(mine), want_real, kind_of)
            if extra is None:
                break
            mine.append(extra)
        scene["items"] = mine
        for item in mine:
            used[item] = used.get(item, 0) + 1
    # anything never shown takes a place in a scene that has room
    for item in [p for p in pool if not used.get(p) and kind_of[p] != "stock"]:
        roomy = max((s for s in scenes if s["format"] not in ("silence", "freeze", "question", "stack") and len(s["items"]) < MOST_ITEMS.get(s["format"], 4)),
                    key=lambda s: MOST_ITEMS.get(s["format"], 4) - len(s["items"]), default=None)
        if roomy:
            roomy["items"].append(item)
            used[item] = 1
    stock_share(scenes, pack)


def stock_share(scenes: list[dict], pack: dict) -> None:
    """Real pictures at least half of what's shown: a stock clip over the share gives way to a real picture."""
    kind_of = kinds(pack)
    real = [p for p, k in kind_of.items() if k != "stock"]
    if not real:
        return
    shown = [(s, i) for s in scenes for i in range(len(s.get("items") or []))]
    count = lambda: sum(1 for s, i in shown if kind_of.get(s["items"][i]) == "stock")  # noqa: E731
    while count() * 2 > len(shown):
        s, i = next((s, i) for s, i in reversed(shown) if kind_of.get(s["items"][i]) == "stock")
        replacement = next((r for r in real if r not in s["items"]), real[0])
        s["items"][i] = replacement


def _alternate(scenes: list[dict]) -> None:
    """Every cut conflicts: never the same format twice running, grounds alternating where a format lets them, sides swapping."""
    last_ground, side = None, 1
    for k, scene in enumerate(scenes):
        if k and scene["format"] == scenes[k - 1]["format"] and scene["format"] != "silence":
            scene["format"] = next(f for f in ROLE_CYCLE if f != scene["format"])
        fixed = FIXED_GROUND.get(scene["format"])
        ground = fixed or ("ink" if last_ground == "paper" else "paper")
        scene["ground"] = ground
        scene["side"] = side
        side = -side
        last_ground = ground


def _has_people(pack: dict) -> set[str]:
    return {i["id"] for i in items_of(pack) if i.get("cutout")}


def repair(raw: dict, script: dict, pack: dict) -> dict:
    """What Gemini chose, made exact. Always returns something the renderer can draw."""
    lines = script["lines"]
    scenes = _covered([s for s in raw.get("scenes") or [] if isinstance(s, dict)], len(lines))
    role_of = [line.get("role") for line in lines]
    twist = next((k for k, r in enumerate(role_of) if r == "twist"), None)
    used_tower = False
    for k, scene in enumerate(scenes):
        fmt = scene.get("format") if scene.get("format") in FORMATS else "window"
        if fmt == "tower":
            if used_tower or len(_has_people(pack)) < 1 and len(items_of(pack)) < 4:
                fmt = "strips"
            used_tower = True
        scene["format"] = fmt
        scene.update(_text(scene, [lines[n] for n in scene["lines"]], pack))
    scenes[0]["format"] = "title"
    if not scenes[0]["big"] and not scenes[0]["words"]:
        scenes[0]["words"] = [_clean_words(lines[0]["text"], MAX_WORD_LINE)]
    if twist is not None:
        holder = next((s for s in scenes if twist in s["lines"]), None)
        if holder is not None and holder is not scenes[0]:
            if holder["lines"][0] != twist:  # the twist starts its own scene, so the result lands on it
                at = holder["lines"].index(twist)
                after = {**holder, "lines": holder["lines"][at:], "items": list(holder.get("items") or [])}
                holder["lines"] = holder["lines"][:at]
                scenes.insert(scenes.index(holder) + 1, after)
                holder = after
            holder["format"] = "result"
            holder.update(_text(holder, [lines[n] for n in holder["lines"]], pack))
    holder = next((s for s in scenes if twist in s["lines"]), None) if twist is not None else None
    for scene in scenes:  # (the heaviest hit comes once)
        if scene["format"] == "result" and holder is not None and scene is not holder:
            scene["format"] = "exposure"
    _alternate(scenes)
    if holder is not None and holder is not scenes[0]:  # (_alternate may have changed a result that followed something: the twist keeps it)
        holder["format"], holder["ground"] = "result", "paper"
    _settle_items(scenes, pack, [line["text"] for line in lines])
    beats = [line.get("beat") for line in lines]
    wipes = 0
    for k, scene in enumerate(scenes):
        first = scene["lines"][0]
        scene["wipe"] = bool(k and first and beats[first] != beats[first - 1] and wipes < MAX_WIPES and scene["format"] != "result")
        wipes += scene["wipe"]
    if twist is not None:  # the look's one silent beat, just before the heaviest hit
        at = next((k for k, s in enumerate(scenes) if twist in s["lines"]), None)
        if at:
            scenes.insert(at, {"format": "silence", "lines": [], "items": [], "big": "", "unit": "", "words": [], "ground": "ink", "side": 1, "wipe": False})
    return {"schema": SCHEMA_VERSION, "scenes": [{key: s.get(key) for key in ("format", "lines", "items", "big", "unit", "words", "ground", "side", "wipe")} for s in scenes]}


def fallback(script: dict, pack: dict) -> dict:
    """A sound film from the script's roles alone: the shot each role naturally takes, one scene to a line or two."""
    raw, cycle, k = [], 0, 0
    lines = script["lines"]
    while k < len(lines):
        role = lines[k].get("role")
        fmt = FALLBACK_FOR.get(role, "window")
        span = [k]
        if k + 1 < len(lines) and lines[k + 1].get("role") == role and len(lines[k]["text"].split()) < 7:
            span.append(k + 1)
        if raw and raw[-1]["format"] == fmt:
            fmt = ROLE_CYCLE[cycle % len(ROLE_CYCLE)]
            cycle += 1
        allowed = _allowed_numbers([lines[n] for n in span], pack)
        big = next((f"{int(a):,}" if a == int(a) else str(a) for a in sorted(allowed, reverse=True) if a >= 10), "")
        raw.append({"format": fmt, "lines": span, "items": [], "big": big, "unit": "", "words": []})
        k = span[-1] + 1
    return repair({"scenes": raw}, script, pack)


def _menu(pack: dict) -> str:
    people = _has_people(pack)
    rows = []
    for item in items_of(pack):
        rows.append({"id": item["id"], "kind": item.get("kind") or "photo", "shows": item.get("shows") or "",
                     **({"note": "has a cut-out person"} if item["id"] in people else {})})
    return json.dumps(rows, ensure_ascii=False)


def _script_for_prompt(script: dict, pack: dict) -> str:
    facts = {f["id"]: f["claim"] for f in pack.get("facts") or []}
    rows = [{"line": k, "says": line["text"], "role": line.get("role"), "facts": [facts[f] for f in line.get("facts") or [] if f in facts]}
            for k, line in enumerate(script["lines"])]
    return json.dumps(rows, ensure_ascii=False)


def direct(plan: dict, progress=print) -> dict:
    """The scenes for a case: Gemini directs, code makes it exact. If Gemini can't answer, the script's roles direct it instead."""
    script, pack = plan["script"], plan.get("research") or {}
    prompt = (f"The case: {text_clean.screen_text(plan.get('brief', {}).get('topic') or '', 120)}\n\nThe script, line by line, with each line's facts:\n"
              f"{_script_for_prompt(script, pack)}\n\nThe pictures you have:\n{_menu(pack)}\n\nDirect the film.")
    best, note = None, ""
    for attempt in range(TRIES):
        progress("Directing the montage" if not attempt else "Directing it again")
        try:
            raw = llm.generate_json([prompt + note], SCHEMA, DIRECTOR, careful=True)
        except Exception as e:
            if "API key" in str(e) or "All Gemini models failed" in str(e):
                raise
            progress(f"The director's answer failed ({type(e).__name__})")
            break
        made = repair(raw, script, pack)
        found = problems(made, script)
        if best is None or len(found) < best[0]:
            best = (len(found), made)
        if not found:
            break
        note = ("\n\nYour last answer, once checked, had these problems. Direct it again and fix them:\n- " + "\n- ".join(found))
    made = best[1] if best else fallback(script, pack)
    shown = sum(len(s["items"]) for s in made["scenes"])
    progress(f"{sum(1 for s in made['scenes'] if s['lines'])} scenes in {len({s['format'] for s in made['scenes']})} formats, {shown} pictures placed")
    return made


def problems(manifest: dict, script: dict) -> list[str]:
    """What a repaired design still gets wrong that only the director can fix."""
    scenes = [s for s in manifest["scenes"] if s["lines"]]
    found = []
    formats = {s["format"] for s in scenes}
    if len(scenes) < 6:
        found.append(f"only {len(scenes)} scenes: split the lines into at least 8 scenes")
    if len(formats) < 5:
        found.append(f"only {len(formats)} different formats: use at least 6")
    if sum(1 for s in scenes if s.get("big") or s.get("words")) < len(scenes) // 2:
        found.append("most scenes have no words on screen: give at least every other scene a big word or number")
    return found


def assets(plan: dict) -> dict:
    """What the renderer needs for each picture, with its file on disk (fetched again if it's gone); a picture that can't be fetched is left
    out, and the scenes are made without it."""
    from agents.researcher import clip_path, image_path

    from common import TMP_DIR

    pack = plan.get("research") or {}
    out = {}
    for item in items_of(pack):
        try:
            path = image_path(item) if item in (pack.get("images") or []) else clip_path(item)
        except Exception:
            continue
        if not path or not path.exists():
            continue
        cut = item.get("cutout")
        out[item["id"]] = {"kind": item.get("kind") or "photo", "path": str(path), "tag": item.get("tag") or "", "focus": item.get("focus"),
                           "cutout": str(TMP_DIR / cut) if cut and (TMP_DIR / cut).exists() else None}
    return out


def without(manifest: dict, gone: set[str], pack: dict) -> dict:
    """The design with pictures taken out (turned down, or lost), others put in their places."""
    scenes = json.loads(json.dumps(manifest["scenes"]))
    for scene in scenes:
        scene["items"] = [i for i in scene.get("items") or [] if i not in gone]
    reduced = {**pack, "archive": [i for i in pack.get("archive") or [] if i["id"] not in gone],
               "images": [i for i in pack.get("images") or [] if i["id"] not in gone],
               "footage": [i for i in pack.get("footage") or [] if i["id"] not in gone]}
    _settle_items([s for s in scenes if s["format"] != "silence"], reduced)
    return {**manifest, "scenes": scenes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check", required=True)
    args = parser.parse_args()
    try:
        with open(args.check, encoding="utf-8") as f:
            plan = json.load(f)
        made = fallback(plan["script"], plan.get("research") or {})
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(made, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
