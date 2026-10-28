"""
Agent 3, Writer: turns the brief and the research pack into the Professor's script, told as a
mystery: 10 to 16 short lines he narrates, each with the facts it relies on, how he says it (a
voice direction), its beat in the story and one or two visuals (real footage, archive film, photos,
maps, charts, big numbers, the source's own words); plus the on-screen case title and YouTube's
title, description and hashtags.

The shape, the user's format (2026-10-26), each line's beat: the hook (one line that frames the whole
story, e.g. a decision that turned a success into a cautionary tale), the setup (the person, company,
event or mystery), the turning point (the crucial mistake, conflict, discovery or unexpected
development, told through people's decisions), the reveal (the outcome and why it matters) and the
narrator's closing thought (one reflective line in his own words, like "and that is why..."). The
closing thought is the one place a reflection belongs; anywhere else a moral still counts as a
lecture habit.

Everything is checked in code before it's kept: the fact ids and visuals must exist, every number
spoken must be in the line's facts (or the line before), and the script must fit max_seconds at the
narrator's pace. The lecture habits of earlier scripts are caught (a line starting with a date,
more than three dates, a moral or "in conclusion" at the end, greetings, lists, more than one number
in a sentence) and sent back for one rewrite. Then two more free Gemini readings:
1. the retention editor scores the hook, the open loop, the pace, the specifics and the payoff and
   rewrites only the weak lines, keeping their facts and visuals; a rewrite bringing a number its
   facts don't support, or a lecture habit, is ignored;
2. the fact-checker reads each line against its facts' source quotes: an overstated line gets the
   checker's fix, an unsupported one is cut (framing lines that state nothing are fine), and more
   than three cuts, or the hook cut, means one rewrite. The dashboard shows each line's mark.

Visuals are named, not drawn, here: "footage:B1", "archive:A1", "photo:I2", "number:N1", "chart:D1",
"map", "map:CHN>USA" and "quote:F3". The Animator turns them into shots (shot_for). apply_edits()
takes the owner's edits from the dashboard through the same checks.

In the drawn look (settings look.style: drawn, your choice on 2026-10-27) every line plays over a
drawing in the Professor's art, and the Writer describes each one in the line's `scene` (or "same":
the drawing before stays and the camera moves on across it); the visuals are then 0 or 1 more thing
shown after it (a real photo, framed over the drawing, a map, a chart, a number or a quote). No stock
video or archive film. Scenes are checked in code (clean_scene, settle_scenes): words in quotes and
"a sign reading..." go (they'd be drawn as garbled lettering), a real person's name becomes their role
(never a likeness), a scene with anything graphic or a child stays on the drawing before, and there
are at most MAX_SCENES drawings (Cloudflare's free allocation). The script remembers its look
(script["look"]): a case is made the way it was written, whatever the setting says later. While
Cloudflare can't draw, new cases are written in the real-footage look (draw.style_now(), settings
look.when_out), and a case written for drawings that can't be drawn is written again for footage
(write(..., look="footage"), from agents/animator.py), its clips found first.

Usage:
    python -m agents.writer --pack pack.json --brief brief.json      # prints a script (nothing is saved)
"""

import argparse
import json
import re
import sys
from pathlib import Path

import db
import draw
import llm
import short_render
import text_clean
from agents.base import act, advice, lessons_for, log, taught
from agents.researcher import numbers_in
from common import load_config

MIN_LINES, MAX_LINES = 8, 18
MAX_WORDS = 22                 # the most words in a line (the prompt asks for 18)
WORDS_PER_SECOND = 2.1         # the Professor's pace on case scripts, after pauses are tightened (2026-10-26: 2.18
                               # on Tupperware, 1.98 on Western Sydney Airport; plain sample sentences 2.5)
LINE_GAP = 0.2                 # narration's pause between lines (narration.KEEP_GAP)
MIN_SECONDS = 35
MAX_CUTS = 3
MAX_DATES = 3
NUMBER_RUN = 3                 # this many lines in a row, each with a number, read like a list of facts
QUOTE_CARDS = 3
TITLE_CHARS = 32
BEATS = ["hook", "setup", "turn", "reveal", "closing"]  # turn = the turning point; closing = his closing thought
HASHTAG_FOR = {"business": "#business", "economy": "#economics", "trending": "#news", "history": "#history",
               "mythology": "#mythology", "dark_history": "#history", "mysteries": "#mystery", "technology": "#technology",
               "psychology": "#psychology", "people": "#biography", "science": "#science", "crime": "#truecrime"}
VERDICTS = ["supported", "overstated", "unsupported", "not_a_claim"]
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
DATE = re.compile(rf"\b(1[0-9]{{3}}|20[0-9]{{2}}|(?:{MONTHS})(?:\s+\d{{1,2}})?)\b", re.IGNORECASE)
STARTS_WITH_DATE = re.compile(rf"^\W*(?:(?:in|on|by|from|during|until|since|back in)\s+)?(?:the\s+)?"
                              rf"(?:1[0-9]{{3}}|20[0-9]{{2}}|{MONTHS}|the (?:19|20)\d0s)\b", re.IGNORECASE)
MORAL = re.compile(r"\b(in conclusion|this shows|that shows|which shows|proves that|proving|the lesson|the moral|"
                   r"teaches us|we can learn|we learn|remember this|the takeaway)\b", re.IGNORECASE)
CLOSING_CLICHE = re.compile(r"\b(in conclusion|to conclude|to sum up|in summary|the moral of the story|the lesson "
                            r"here)\b", re.IGNORECASE)  # the closing thought reflects, it doesn't summarise
CONTENT_WORD = re.compile(r"[a-z]{4,}")
GREETING = re.compile(r"^\W*(hi|hello|hey|welcome|today we|today,? we|let's dive|let us dive|did you know|"
                      r"have you ever wondered)\b", re.IGNORECASE)
LISTING = re.compile(r"\b(firstly|secondly|thirdly|first of all|number one|number two|reason one)\b", re.IGNORECASE)
# The drawn look's scenes
SAME = "same"                  # a scene that stays on the drawing before
MAX_SCENES = 9                 # drawings in a case at most (~58 of Cloudflare's 10,000 free neurons a day each)
SCENES_AIM = "6 to 8"          # what the prompt asks for
SCENE_WORDS = 45               # a scene description is cut to this many words
QUOTED = re.compile(r"[\"“”][^\"“”]{0,80}[\"“”]")  # words in quotes would be drawn as (garbled) lettering
SPELLED = re.compile(r"\b(?:reading|that reads|saying|that says|with the words?|labell?ed|titled|captioned|spelling "
                     r"out|inscribed with)\b[^,.;]*", re.IGNORECASE)
NOT_DRAWN = re.compile(r"\b(blood\w*|gore|gory|corpses?|dead (?:body|bodies|man|woman|men|women)|bod(?:y|ies) "
                       r"(?:lying|on the floor|on the ground)|wounds?|wounded|severed|decapitat\w*|noose|hanged|stab\w*|"
                       r"guns? (?:pointed|aimed)|child|children|kids?|bab(?:y|ies)|boys?|girls?|teen\w*|toddlers?|"
                       r"infants?|schoolchildren|school(?:boy|girl)s?|youths?|lads?|minors?|adolescen\w*|pupils?)\b",
                       re.IGNORECASE)  # never drawn: graphic things, and children
YOUNG = re.compile(r"\b(?:young(?:er|est)?|youthful|boyish|girlish)\s+", re.IGNORECASE)  # "a young guard" came out a
# boy (the first drawn case, 2026-10-27): the word goes, the guard stays


# --- visuals ------------------------------------------------------------------

def visual_menu(pack: dict, brief: dict, drawn: bool = False) -> dict[str, str]:
    """The visuals a line can use for this case: name -> what it shows. The drawn look has no clips (its lines play
    over drawings) and draws its maps."""
    menu = {}
    for clip in pack.get("archive") or [] if not drawn else []:
        when = f", {clip['year']}" if clip.get("year") else ""
        menu[f"archive:{clip['id']}"] = f"archive film of the real thing (\"{clip['title']}\"{when}): {clip['shows']}"
    for image in pack.get("images") or []:
        menu[f"photo:{image['id']}"] = f"real photo{', framed over the drawing' if drawn else ''}: {image['shows']}"
    for clip in pack.get("footage") or [] if not drawn else []:
        menu[f"footage:{clip['id']}"] = f"stock video, illustrative only: {clip['shows']}"
    for s in pack.get("stats") or []:
        menu[f"number:{s['id']}"] = f"big number on screen: {s['value']} ({s['label']})"
    for s in pack.get("series") or []:
        years = f"{s['points'][0][0]}-{s['points'][-1][0]}" if s["points"] else ""
        ahead = f", IMF forecasts from {s['forecast_from']}" if s.get("forecast_from") else ""
        menu[f"chart:{s['id']}"] = f"chart: {s['title']} ({s['unit']}), {s['country']}, {years}{ahead}"
    countries = brief.get("countries") or []
    if countries:
        kind = "map" if drawn else "satellite map"
        menu["map"] = f"{kind} with {', '.join(countries)} lit up"
        for a in countries[:3]:
            for b in countries[:3]:
                if a != b:
                    menu[f"map:{a}>{b}"] = f"{kind} with an arrow from {a} to {b} (trade, money, people, fleets)"
    quotable = sorted((f for f in pack.get("facts") or [] if not f.get("calculated") and len(f["quote"].split()) <= 28
                       and f["quote"].rstrip().endswith((".", "!", "?", '"', "”"))),  # whole sentences only
                      key=lambda f: (f["kind"] not in ("reaction", "story", "number"), len(f["quote"])))
    for f in quotable[:QUOTE_CARDS]:
        menu[f"quote:{f['id']}"] = f"the source's own words, on screen: \"{f['quote'][:90]}\""
    return menu


def shot_for(name: str, plan: dict) -> dict | None:
    """What tools/doc_render.py draws for a visual's name, or None if the pack no longer has it."""
    from agents.researcher import clip_path, image_path

    pack, brief = plan.get("research") or {}, plan.get("brief") or {}
    kind, _, ref = (name or "").partition(":")
    if kind == "scene":  # a drawing of the drawn look, by the number of the line it starts on (the Animator's)
        path = (plan.get("drawings") or {}).get(ref)
        return {"kind": "scene", "path": path} if path and Path(path).exists() else None
    by_id = {x["id"]: x for key in ("images", "footage", "archive", "series", "stats", "facts") for x in pack.get(key) or []}
    sources = {s["id"]: s for s in pack.get("sources") or []}
    people = {p["name"].lower(): p for p in pack.get("people") or []}
    item = by_id.get(ref)
    if kind in ("footage", "archive") and item:
        return {"kind": "footage", "path": str(clip_path(item)), "duration": item["duration"], "framed": kind == "archive",
                "credit": item["credit"]}
    if kind == "photo" and item:
        shows = item.get("shows") or ""
        person = next((p for name_, p in people.items() if name_ and name_ in shows.lower()), None)
        return {"kind": "photo", "path": str(image_path(item)), "credit": f"Photo: {item['author']}, {item['licence']}",
                "label": f"{person['name']} · {person['role']}" if person else None}
    if kind == "number" and item:
        return {"kind": "number", "value": item["value"], "label": item["label"]}
    if kind == "chart" and item:
        import infographics

        return {"kind": "chart", "title": f"{item['title']}, {infographics.country_name(item['country'])}",
                "unit": "%" if item["unit"].startswith("%") else "", "points": item["points"][-16:],
                "forecast_from": item.get("forecast_from"), "source": item["source"]}
    if kind == "map":
        if ">" in ref:
            a, b = ref.split(">", 1)
            return {"kind": "map", "countries": [a, b], "arrows": [[a, b]]}
        return {"kind": "map", "countries": brief.get("countries") or []}
    if kind == "quote" and item:
        source = sources.get(item["source"]) or {}
        return {"kind": "quote", "text": item["quote"], "who": source.get("publisher") or source.get("title") or ""}
    return None


# --- checking -----------------------------------------------------------------

def _supported_numbers(fact_ids: list[str], pack: dict) -> set[str]:
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    out = set()
    for fid in fact_ids:
        if fid in by_id:
            out |= numbers_in(by_id[fid]["claim"]) | numbers_in(by_id[fid]["quote"])
    for s in pack.get("stats") or []:
        if s["fact"] in fact_ids:
            out |= numbers_in(s["value"])
    return out


def unsupported_numbers(line: dict, pack: dict, before: dict | None = None) -> set[str]:
    """Numbers in the line that neither its facts nor the line before it back up."""
    facts = (line.get("facts") or []) + ((before or {}).get("facts") or [])
    return numbers_in(line["text"]) - _supported_numbers(facts, pack)


def lecture_habits(lines: list[dict]) -> list[str]:
    """What still sounds like a lecture, line by line (empty: none)."""
    found = []
    for n, line in enumerate(lines, start=1):
        text = line["text"]
        if STARTS_WITH_DATE.search(text):
            found.append(f"line {n} starts with a date")
        if n == 1 and GREETING.search(text):
            found.append("line 1 is a greeting")
        if line.get("beat") == "closing":  # his closing thought is a reflection by design, just not a summary
            if CLOSING_CLICHE.search(text):
                found.append(f"line {n}, the closing thought, sums up like an essay")
        elif MORAL.search(text):
            found.append(f"line {n} states a moral or a conclusion (only the closing thought reflects)")
        if LISTING.search(text):
            found.append(f"line {n} lists points")
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if len(numbers_in(sentence, words=False)) > 1:
                found.append(f"line {n} has more than one number in a sentence")
                break
    dates = sum(len(DATE.findall(line["text"])) for line in lines)
    if dates > MAX_DATES:
        found.append(f"the script has {dates} dates (at most {MAX_DATES})")
    run = 0
    for n, line in enumerate(lines + [{"text": ""}], start=1):  # numbers one after another read like a list
        if numbers_in(line["text"], words=False):
            run += 1
            continue
        if run >= NUMBER_RUN:
            found.append(f"lines {n - run}-{n - 1} each give a number, one after another, like a list")
        run = 0
    return found


def clean_scene(text, pack: dict) -> str:
    """A scene the drawing can use: no words in quotes or "a sign reading...", a real person's name as their role
    (a figure, never a likeness), at most SCENE_WORDS words; SAME (the drawing before) when it asks for "same" or
    for anything graphic or a child."""
    text = " ".join(str(text or "").split())
    if not text or text.lower().strip(" .'\"") in (SAME, "the same", "same as before", "keep", "same scene"):
        return SAME
    text = YOUNG.sub("", SPELLED.sub("", QUOTED.sub("", text)))
    for person in pack.get("people") or []:
        name, role = person.get("name") or "", (person.get("role") or "").strip()
        figure = f"the {role[0].lower()}{role[1:]}" if role else "a figure"
        parts = [name] + [w for w in name.split()[1:] if len(w) >= 4 and w[0].isupper()]  # the full name, then surnames
        for part in parts:
            if part:
                text = re.sub(rf"\b{re.escape(part)}(['’]s)?\b", lambda m: figure + ("'s" if m.group(1) else ""), text,
                              flags=re.IGNORECASE)
    text = " ".join(re.sub(r"\s+([,.;:])", r"\1", text).split()[:SCENE_WORDS]).strip(" ,;:-")
    if not text or NOT_DRAWN.search(text):
        return SAME
    return text


def settle_scenes(lines: list[dict]) -> list[dict]:
    """The drawn look's scenes made whole: the first line has its own drawing (the first one described, if it said
    "same"), a scene that repeats the one before is SAME, and at most MAX_SCENES drawings (the shortest lines'
    drawings go first)."""
    for line in lines:
        line["scene"] = str(line.get("scene") or SAME)
    if lines and lines[0]["scene"] == SAME:
        first = next((k for k, line in enumerate(lines) if line["scene"] != SAME), None)
        if first is None:
            raise ValueError("the script describes no drawings")
        lines[0]["scene"], lines[first]["scene"] = lines[first]["scene"], SAME
    last = None
    for line in lines:
        if line["scene"] != SAME and line["scene"].lower() == (last or "").lower():
            line["scene"] = SAME
        last = line["scene"] if line["scene"] != SAME else last
    new = [k for k in range(1, len(lines)) if lines[k]["scene"] != SAME]
    while 1 + len(new) > MAX_SCENES:
        k = min(new, key=lambda k: len(lines[k]["text"].split()))
        lines[k]["scene"] = SAME
        new.remove(k)
    return lines


def clean_lines(raw: list[dict], pack: dict, menu: dict, drawn: bool = False) -> list[dict]:
    """Lines the Animator can always use: known beats, facts and visuals, not too long (and in the drawn look, a
    scene each: clean_scene)."""
    fact_ids = {f["id"] for f in pack.get("facts") or []}
    lines = []
    for item in raw[:MAX_LINES + 4]:
        text = text_clean.screen_text(str(item.get("text", "")), 240)
        if not text or len(text.split()) > MAX_WORDS + 4:
            continue
        visuals = [v for v in dict.fromkeys(str(v).strip() for v in item.get("visuals") or []) if v in menu][:2]
        lines.append({"text": text, "beat": item.get("beat") if item.get("beat") in BEATS else "turn",
                      "direction": " ".join(str(item.get("direction", "")).split())[:80],
                      "facts": [f for f in dict.fromkeys(str(f).strip().upper() for f in item.get("facts") or [])
                                if f in fact_ids],
                      "visuals": visuals, **({"scene": clean_scene(item.get("scene"), pack)} if drawn else {})})
    if len(lines) < MIN_LINES // 2:
        raise ValueError(f"the script has only {len(lines)} usable lines")
    lines[0]["beat"] = "hook"
    return lines


def match_visuals(lines: list[dict], pack: dict) -> list[dict]:
    """A big number or a quote card only on a line that says it: the number's (or quote's) fact must be one the line
    cites. Otherwise it goes (vary_visuals then gives the line a picture)."""
    stat_fact = {s["id"]: s["fact"] for s in pack.get("stats") or []}
    for line in lines:
        keep = []
        for name in line["visuals"]:
            kind, _, ref = name.partition(":")
            if kind == "number" and stat_fact.get(ref) not in line["facts"]:
                continue
            if kind == "quote" and ref not in line["facts"]:
                continue
            keep.append(name)
        line["visuals"] = keep
    return lines


def drop_repeats(lines: list[dict]) -> list[dict]:
    """Lines that only say again what an earlier line said (the same facts, mostly the same words) go; the closing
    thought stays, it may look back at the hook on purpose."""
    kept = []
    for line in lines:
        words = set(CONTENT_WORD.findall(line["text"].lower()))
        again = line["beat"] != "closing" and line["facts"] and any(
            set(line["facts"]) <= set(k["facts"])
            and len(words & set(CONTENT_WORD.findall(k["text"].lower()))) >= 0.3 * max(1, len(words)) for k in kept)
        if not again:
            kept.append(line)
    return kept


def vary_visuals(lines: list[dict], menu: dict, drawn: bool = False) -> list[dict]:
    """Every line shows something: a line without a usable visual gets one the script hasn't used yet (real material
    first), and no clip or photo is shown twice. In the drawn look every line has its drawing: it keeps at most one
    more visual, and no photo twice."""
    if drawn:
        used = set()
        for line in lines:
            line["visuals"] = [v for v in line["visuals"] if v.split(":")[0] in ("number", "map", "chart", "quote")
                               or v not in used][:1]
            used.update(line["visuals"])
        return lines
    used, spare = set(), [v for v in menu if v.split(":")[0] in ("archive", "photo", "footage")]
    for line in lines:
        line["visuals"] = [v for v in line["visuals"] if v.split(":")[0] in ("number", "map", "chart", "quote") or v not in used]
        used.update(line["visuals"])
        if not any(v.split(":")[0] != "number" for v in line["visuals"]):
            extra = next((v for v in spare if v not in used), None)
            if extra:
                line["visuals"] = [extra] + line["visuals"][:1]
                used.add(extra)
    return lines


def estimate_seconds(lines: list[dict]) -> float:
    words = sum(len(line["text"].split()) for line in lines)
    return words / WORDS_PER_SECOND + LINE_GAP * max(0, len(lines) - 1) + 0.6


def fit_length(lines: list[dict], max_seconds: float) -> list[dict]:
    """Drops turning-point lines from the middle, then extra setup lines (never the hook, the first setup line, the
    reveal or the closing thought) until the script fits."""
    while len(lines) > MIN_LINES and estimate_seconds(lines) > max_seconds:
        first_setup = next((k for k, line in enumerate(lines) if line["beat"] == "setup"), None)
        turns = [k for k, line in enumerate(lines) if line["beat"] == "turn" and 0 < k < len(lines) - 2]
        setups = [k for k, line in enumerate(lines) if line["beat"] == "setup" and k != first_setup]
        spare = turns or setups
        if not spare:
            break
        lines.pop(spare[len(spare) // 2])
    return lines


# --- writing --------------------------------------------------------------------

def _schema(menu: dict, moods: list[str], drawn: bool = False) -> dict:
    line = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "what he says: at most 18 words"},
            "beat": {"type": "string", "enum": BEATS},
            "direction": {"type": "string", "description": "how he says it, in a few words: 'low, intrigued'"},
            "facts": {"type": "array", "items": {"type": "string"},
                      "description": "ids of the facts the line uses (F1, F2...); empty for a question or a pure transition"},
            "visuals": {"type": "array", "items": {"type": "string", "enum": list(menu)},
                        "description": "0 or 1 more thing, shown after the drawing" if drawn
                        else "1 or 2 visuals, in the order they appear"},
        },
        "required": ["text", "beat", "direction", "facts", "visuals"],
    }
    if drawn:
        line["properties"]["scene"] = {"type": "string", "description": "the drawing behind the line, at most 40 words "
                                                                        "(one main subject, where, period, framing, light), "
                                                                        "or 'same'"}
        line["required"].insert(3, "scene")
    return {
        "type": "object",
        "properties": {
            "case_title": {"type": "string", "description": f"the title on screen, at most {TITLE_CHARS} characters"},
            "lines": {"type": "array", "items": line, "description": "10 to 16 lines: the hook, the setup, the turning "
                                                                     "point, the reveal, the closing thought"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "music_mood": {"type": "string", "enum": moods} if moods else {"type": "string"},
            "thumbnail_text": {"type": "string", "description": "2 to 5 words for the thumbnail, the key word in "
                                                                "*asterisks*"},
        },
        "required": ["case_title", "lines", "title", "description", "hashtags", "tags", "music_mood", "thumbnail_text"],
    }


def _system(cfg: dict, target: int, max_seconds: int, drawn: bool = False) -> str:
    ch = cfg["channel"]
    words, most = round((target - 1) * WORDS_PER_SECOND), round((max_seconds - 2) * WORDS_PER_SECOND)
    return f"""You write the scripts for {ch['name']}, a YouTube Shorts channel of case studies told as stories with a
mystery at their heart, for {ch['audience']}. One narrator tells every case: the Professor, a wise and highly
intelligent old professor with a deep voice: a deep thinker, a great storyteller, calm, observant. He speaks to the
viewer directly, unhurried and sure, like someone sharing what he has worked out. He never introduces himself, never
greets anyone and never names the channel.
The channel's voice: {ch['voice']}

Write 10 to 16 short lines he narrates, about {target} seconds spoken: about {words} words in all, never more than
{most}. Every script has the same five parts, in this order (each line's beat):
1. hook (line 1): one line that frames the whole story and makes the viewer stay: the single decision, mistake,
   discovery or contradiction at its heart and how big its consequence was, concrete (who or what), at most 14 words,
   never vague ('trouble brewed', 'everything changed'). For example, the way one decision can turn a successful
   company into a cautionary tale; write this case's own hook, never that one. No greeting.
2. setup (2 or 3 lines): introduce the person, company, event or mystery: who, where, when, how big, and the question
   it leaves the viewer wanting answered.
3. turn (3 to 6 lines): the turning point: the crucial mistake, conflict, discovery or unexpected development, told
   through real people's decisions: what they chose, what they didn't know, what it cost. End each line on a pull
   forward ('It almost worked.').
4. reveal (2 or 3 lines): the outcome and why it matters, with the evidence: the twist, the consequence, the answer.
5. closing (the last line): the narrator's closing thought: one reflective sentence in his own voice, as a storyteller
   wraps up a tale ('And that is why...', 'Which is why...', 'Perhaps that is...'), turning this case into something
   larger, in words specific to this case. Never 'in conclusion', a summary, or advice.

Never:
- a line that starts with a date or a year; more than {MAX_DATES} dates in the whole script; more than one number in a
  sentence;
- lists of facts, 'firstly' and 'secondly', or a lecture's tone; never {NUMBER_RUN} lines in a row that each give a
  number: put a person, a choice or a consequence between them;
- 'in conclusion', 'this shows', 'proves that', 'the lesson', or a moral anywhere but the closing thought;
- greetings, 'let's dive in', 'did you know', 'today we';
- anything from memory: every fact, name, date and number comes from the research pack, and each line lists the ids of
  the facts it uses (questions and pure transitions use none). Numbers exactly as the facts give them, as digits.
Do:
- short sentences of different lengths; concrete people, choices and stakes; irony; 'you' now and then.
- attribute opinions and forecasts ('analysts said'); neutral on politics (both sides); respectful of every faith and
  culture; myths told as stories ('in the epic, ...'); no advice on money, health or law.
- spoken English for a voice engine: no emoji, hashtags, stage directions or parentheses.

Each line's direction says how he says it, in a few words: 'low, intrigued', 'slower, heavier', 'quiet, drawing you
in', 'quicker, building', 'a beat, then firm'. Calm authority throughout; tension builds through the turning point;
slow and clear for the reveal; warm and unhurried for the closing thought.

{_DRAWN_SCREEN if drawn else _FOOTAGE_SCREEN}

case_title: at most {TITLE_CHARS} characters, a few plain words.
thumbnail_text: 2 to 5 bold words for the thumbnail that make the mystery plain without giving away the answer (the
paradox, the stakes or the question), with the one key word in *asterisks*: 'One phone *sank* Nokia'. Never a lie, a
shock word the video doesn't earn, or the case_title again.
Title: at most 70 characters, sentence case, honest and intriguing (the question or the paradox), may end with one
emoji. Description: 2-3 short sentences ending on a question for the comments. Hashtags: 2-4, lowercase. Tags: 5-10
search keywords."""


_FOOTAGE_SCREEN = """What's on screen, each line 1 or 2 visuals from the list (2 for longer lines; the first shows as the
line starts):
- Real material carries the specific claims: photos of the real people, products and places, archive film of the
  real thing, maps, charts and big numbers from the research.
- Stock video is illustrative only: mood and setting, never presented as the real company, person or event.
- A new picture every line or two, at least four kinds over the script, each clip and photo once. A big number only
  for the number that line says. Quote cards at most twice."""
_DRAWN_SCREEN = f"""What's on screen: every line plays over a drawing in the Professor's own painted style, which you
describe in its scene:
- scene: what to draw behind the line, in one sentence of at most 40 words: one main subject (a person, a place or a
  thing), what is happening, where, the period's details (clothes, cars, buildings and objects of the time), the
  framing (a wide view, from behind, from above, a close view of hands or an object) and the light and mood. Or 'same'
  to stay on the drawing before (the camera moves on across it). About {SCENES_AIM} different drawings in the whole
  script: a new one when the story moves to a new moment or place, 'same' when a line goes on in the same moment.
- One main subject per drawing and at most two people, never a crowd of faces up close: the drawing leaves out
  whatever doesn't fit, so put the one thing that matters first.
- Never writing in the picture: no signs, headlines, labels, book titles or screens with text, never words in quotes.
  A newspaper, a letter or a sign can be there, unreadable.
- Real people are drawn as figures of their time and role ('a woman novelist in a 1920s cloche hat'), never by name
  and never as a likeness: their real photo shows their face.
- Nothing graphic (no blood, wounds, bodies, or weapons aimed at anyone) and never a child or a teenager: everyone
  drawn is a grown adult (never 'young'). Tension comes from light, shadow and what is left unseen.
- visuals: 0 or 1 more thing, shown after the drawing (on a short line, instead of it): a real photo, framed over the
  drawing, where the real face, place or document matters (each photo once; the real people at least once when there
  is a photo of them), a map, a chart, a big number (only for the number that line says) or the source's own words (at
  most twice)."""


def _pack_for_prompt(pack: dict) -> str:
    sources = {s["id"]: s.get("publisher") or s["title"] for s in pack.get("sources") or []}
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    story = pack.get("story") or {}
    return json.dumps({
        "facts": [{"id": f["id"], "claim": f["claim"], "kind": f["kind"], "source": sources.get(f["source"], "")}
                  for f in pack.get("facts") or []],
        "timeline": pack.get("timeline") or [], "big_numbers": pack.get("stats") or [],
        "people": pack.get("people") or [], "what_the_sources_say": pack.get("answer", ""),
        "story": {"most_surprising_fact": story.get("paradox"), "decisions": story.get("decisions") or [],
                  "twist": story.get("twist"),
                  "facts": {fid: by_id[fid]["claim"] for fid in [story.get("paradox"), story.get("twist")] if fid in by_id}},
    }, ensure_ascii=False, indent=1)


RETENTION_SCHEMA = {"type": "object", "properties": {
    "scores": {"type": "object", "properties": {k: {"type": "integer"} for k in
                                                ("hook", "open_loop", "pace", "specificity", "payoff")},
               "required": ["hook", "open_loop", "pace", "specificity", "payoff"]},
    "rewrites": {"type": "array", "items": {"type": "object", "properties": {
        "line": {"type": "integer"}, "text": {"type": "string"}, "direction": {"type": "string"}},
        "required": ["line", "text", "direction"]}},
}, "required": ["scores", "rewrites"]}


def retention_edit(lines: list[dict], pack: dict, brief: dict, progress=log) -> tuple[list[dict], dict]:
    """A second Gemini reading as a Shorts retention editor: scores the script and rewrites only its weak lines, which
    keep their facts and visuals. Rewrites that bring unsupported numbers or lecture habits are ignored."""
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    items = [{"line": n, "beat": line["beat"], "text": line["text"], "direction": line["direction"],
              "facts": [by_id[f]["claim"] for f in line["facts"] if f in by_id]} for n, line in enumerate(lines, start=1)]
    system = """You are the retention editor of a YouTube Shorts channel of case studies told as stories by one narrator,
a wise old professor with a deep, calm voice. Every script has five parts: the hook, the setup, the turning point,
the reveal and his closing thought. Viewers swipe away in the first 2 seconds unless the hook stops them, and leave
mid-way unless a question keeps them. Score the script 0-10 on: hook (does line 1 stop the scroll?), open_loop (does
the setup leave a question the viewer needs answered, held back until the reveal?), pace (short, varied sentences, no
lecture, no wasted words), specificity (real people, numbers and choices rather than vague summary), payoff (does the
reveal give the outcome and why it matters, and does the closing thought land as one memorable reflection specific
to this story?).
Then rewrite the weak lines, at most 5: every area you score below 7 needs at least one rewrite (line 1 whenever the
hook is below 7: concrete, the contradiction plain; the turning point when pace or specificity is below 7: people and
their choices, not a list of numbers; the last line when the closing thought is generic). Same facts (never a fact,
name or number the line's facts don't have), at most 18 words, no line starting with a date or year, no greeting, no
moral except in the closing thought, at most one number in a sentence. Give each rewritten line's voice direction
too. If every score is 7 or more, rewrite nothing."""
    prompt = (f"The case's question: {brief.get('angle', '')}\n\nThe script, line by line, with the facts each line may "
              f"use:\n{json.dumps(items, ensure_ascii=False, indent=1)}\n\nScore it and rewrite the weak lines.")
    progress("The retention editor is reading the script")
    try:
        raw = llm.generate_json([prompt], RETENTION_SCHEMA, system)
    except Exception as e:  # the script stands without this pass
        progress(f"Retention editor unavailable ({type(e).__name__}); keeping the script as written")
        return lines, {}
    scores = {k: max(0, min(10, int(v))) for k, v in (raw.get("scores") or {}).items() if isinstance(v, (int, float))}
    changed, rejected = 0, []
    for edit in (raw.get("rewrites") or [])[:5]:
        n = edit.get("line")
        if not isinstance(n, int) or not 1 <= n <= len(lines):
            continue
        text = text_clean.screen_text(str(edit.get("text", "")), 240)
        line = lines[n - 1]
        candidate = {**line, "text": text}
        why = ("empty" if not text else "too long" if len(text.split()) > MAX_WORDS
               else "a number its facts don't have" if unsupported_numbers(candidate, pack, lines[n - 2] if n > 1 else None)
               else "; ".join(lecture_habits([candidate])))
        if why:  # kept for the dashboard, so a weak score with nothing rewritten can be explained
            rejected.append({"line": n, "text": text[:160], "why": why})
            continue
        lines[n - 1] = {**candidate, "direction": " ".join(str(edit.get("direction") or line["direction"]).split())[:80],
                        "was": line["text"]}
        changed += 1
    progress(f"Retention editor: {', '.join(f'{k} {v}' for k, v in scores.items())}; {changed} line(s) rewritten"
             + (f", {len(rejected)} rewrite(s) refused" if rejected else ""))
    return lines, {"scores": scores, "rewritten": changed, "rejected": rejected}


def fact_check(lines: list[dict], pack: dict, progress=log) -> tuple[list[dict], int, bool]:
    """A reading of every line against its facts' quotes: fixes overstated lines, cuts unsupported ones. Returns the
    lines (each marked), how many were cut and whether the hook was one of them."""
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    items = []
    for n, line in enumerate(lines, start=1):
        before = lines[n - 2] if n > 1 else None
        items.append({"line": n, "beat": line["beat"], "text": line["text"],
                      "facts": [{"claim": by_id[f]["claim"], "quote": by_id[f]["quote"]}
                                for f in line["facts"] + ((before or {}).get("facts") or [])],
                      "numbers_not_in_its_facts": sorted(unsupported_numbers(line, pack, before))})
    schema = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"line": {"type": "integer"}, "verdict": {"type": "string", "enum": VERDICTS},
                       "fixed": {"type": "string", "description": "for an overstated line: the same line, corrected so its "
                                                                 "facts support it; else empty"}},
        "required": ["line", "verdict", "fixed"]}}}, "required": ["verdicts"]}
    system = """You fact-check scripts for a YouTube channel of case studies told as mysteries. For each line, compare
what it says with the facts it cites (their claims and the source quotes behind them):
- supported: everything it states is in those facts (wording may differ; obvious context is fine)
- overstated: mostly right but goes further than the facts (a number, a date, a cause, a superlative); give the fixed
  line, as short and natural as the original
- unsupported: it states something none of its facts support
- not_a_claim: a question, a moment of tension or a transition that states no new fact ('So what went wrong?', 'And
  that's when it broke.'), and the narrator's closing thought (beat 'closing'): a reflection on what the story means,
  unless it slips in a new specific fact, name or number
Numbers must match the facts exactly. Be strict about facts and relaxed about style."""
    progress("Fact-checking every line against its sources")
    verdicts = {v.get("line"): v for v in llm.generate_json([json.dumps(items, ensure_ascii=False, indent=1)], schema,
                                                            system).get("verdicts") or []}
    kept, cut, hook_cut = [], 0, False
    for n, line in enumerate(lines, start=1):
        v = verdicts.get(n) or {}
        before = lines[n - 2] if n > 1 else None
        verdict = v.get("verdict") if v.get("verdict") in VERDICTS else "supported"
        if verdict == "overstated":
            fixed = text_clean.screen_text(str(v.get("fixed", "")), 240)
            candidate = {**line, "text": fixed}
            if fixed and not unsupported_numbers(candidate, pack, before):
                kept.append({**candidate, "check": "fixed", "was": line.get("was") or line["text"]})
                continue
            verdict = "unsupported"
        if verdict == "unsupported" and line["beat"] == "closing" and not numbers_in(line["text"], words=False):
            verdict = "not_a_claim"  # his closing thought reflects; the format needs it (numbers are still checked)
        if unsupported_numbers(line, pack, before) or verdict == "unsupported":
            cut += 1
            hook_cut = hook_cut or n == 1
            continue
        kept.append({**line, "check": "ok" if verdict != "not_a_claim" else "framing"})
    return kept, cut, hook_cut


def write(brief: dict, pack: dict, progress=log, look: str | None = None) -> dict:
    """The script in `look` ("drawn" or "footage"; by default the one a case made now gets). A pack researched for
    drawings that's written for footage gets its clips first (into the pack)."""
    cfg = load_config()
    cases = cfg["cases"]
    target, max_seconds = int(cases.get("target_seconds", 60)), int(cases.get("max_seconds", 75))
    target -= int(lessons_for("writer")["settings"].get("seconds_under") or 0)  # scripts kept running long
    moods = short_render.music_moods()
    drawn = (look or draw.style_now()) == "drawn"
    if not drawn:
        from agents.researcher import add_footage
        add_footage(brief, pack, progress)
    menu = visual_menu(pack, brief, drawn)
    system = _system(cfg, target, max_seconds, drawn)
    follow = ""
    if brief.get("follow_up_of"):
        earlier = db.get_video(brief["follow_up_of"])
        if earlier:
            follow = (f"This is a follow-up (part 2) to an earlier case: "
                      f"{earlier['plan'].get('metadata', {}).get('title') or earlier['theme']}. Mention it briefly.\n")
    recent = [v["plan"]["metadata"]["title"] for v in db.recent_videos(days=30)
              if v["format"] == db.FORMAT and v["plan"].get("metadata")][:30]
    base_prompt = (f"Case type: {brief['category']}\nTopic: {brief['topic']}\n"
                   + (f"The paradox (the Editor's guess; open on what the facts support): {brief['paradox']}\n"
                      if brief.get("paradox") else "")
                   + f"The mystery to solve: {brief['angle']}\n"
                   + (f"Why now: {brief['trend']}\n" if brief.get("trend") else "") + follow
                   + f"\nResearch pack:\n{_pack_for_prompt(pack)}\n\n"
                   f"Visuals you can use:\n" + "\n".join(f"- {k}: {v}" for k, v in menu.items()) + "\n\n"
                   f"Recent titles (don't repeat them): {recent or 'none yet'}\n"
                   f"What has worked so far: {advice(('hook', 'length', 'visuals', 'lines', 'hashtag')) or 'not enough data yet'}\n"
                   + taught("writer") + "\n")
    feedback, retention = "", {}
    for attempt in range(2):
        progress("Writing the script" if not attempt else "Rewriting the script")
        raw = llm.generate_json([base_prompt + feedback + "Write the script."], _schema(menu, moods, drawn), system,
                                careful=True)
        lines = drop_repeats(clean_lines(raw.get("lines") or [], pack, menu, drawn))
        lines = fit_length(vary_visuals(match_visuals(lines, pack), menu, drawn), max_seconds)
        habits = lecture_habits(lines)
        if not attempt and drawn and all(line["scene"] == SAME for line in lines):
            feedback = "Your last script described no drawings: give every new moment its scene.\n"
            continue
        if not attempt and (estimate_seconds(lines) < MIN_SECONDS or len(habits) >= 2):
            feedback = ((f"Your last script was too short (about {estimate_seconds(lines):.0f} seconds). Write a fuller "
                         f"one.\n" if estimate_seconds(lines) < MIN_SECONDS else "")
                        + (f"Your last script still sounded like a lecture: {'; '.join(habits)}. Tell it as a story.\n"
                           if len(habits) >= 2 else ""))
            continue
        lines, retention = retention_edit(lines, pack, brief, progress)
        checked, cut, hook_cut = fact_check(lines, pack, progress)
        if (cut > MAX_CUTS or hook_cut) and not attempt:
            feedback = (f"The fact-checker cut {cut} line(s) of your last script{', the hook among them,' if hook_cut else ''} "
                        "because the facts didn't support them. Stick to what the facts say, and cite every fact a "
                        "line uses.\n")
            continue
        lines = checked
        break
    if len(lines) < MIN_LINES // 2:
        raise RuntimeError("too few lines survived the fact-check")
    lines[0]["beat"] = "hook"  # if the fact-check cut the hook on the last try, the line that now opens is the hook
    if drawn:  # (cut lines may have taken the first drawing with them)
        settle_scenes(lines)
    case_title = text_clean.screen_text(str(raw.get("case_title", "")), TITLE_CHARS) or brief["topic"][:TITLE_CHARS]
    script = {"case_title": case_title, "lines": lines, "music_mood": _mood(raw.get("music_mood"), moods),
              "seconds": round(estimate_seconds(lines), 1), "cut": cut, "retention": retention,
              "habits": lecture_habits(lines), "look": "drawn" if drawn else "footage"}
    progress(f"Script: {len(lines)} lines, about {script['seconds']:.0f} s ({cut} cut by the fact-check)"
             + (f", {sum(1 for line in lines if line['scene'] != SAME)} drawings" if drawn else ""))
    return {"script": script, "metadata": metadata(raw, brief, cfg), "lines": len(lines), "cut": cut,
            "estimate": script["seconds"]}


def _mood(value, moods: list[str]) -> str:
    value = str(value or "").strip().lower()
    return value if value in moods else (moods[0] if moods else "")


def metadata(raw: dict, brief: dict, cfg: dict) -> dict:
    base = list(cfg["metadata"]["base_hashtags"]) + [HASHTAG_FOR.get(brief.get("category"), "")]
    tags = text_clean.hashtags(raw.get("hashtags") or [], [t for t in base if t])
    title = text_clean.title(text_clean.no_links(str(raw.get("title", ""))), brief["topic"])[:100]
    summary = text_clean.no_brackets(text_clean.no_links(str(raw.get("description", ""))))[:1200]
    thumb = text_clean.screen_text(str(raw.get("thumbnail_text") or ""), 60)
    return {"title": title, "description": summary, "hashtags": tags,
            "tags": text_clean.tags((raw.get("tags") or []) + [brief["topic"]]),
            "thumbnail_text": thumb if 2 <= len(thumb.replace("*", " ").split()) <= 6 else ""}


def run(brief: dict, pack: dict, progress=log) -> dict:
    return act("writer", f"Script: {brief['topic']}", write, brief, pack, progress=progress)


def apply_edits(plan: dict, edits: dict) -> dict:
    """The owner's edits from the dashboard, through the same rules as written text. A line you change is marked
    "edited"; if it has a number its facts don't support, "edited-unsourced"."""
    cfg = load_config()
    script, meta, pack, brief = plan["script"], plan["metadata"], plan["research"], plan["brief"]
    if "lines" in edits:
        drawn = script.get("look") == "drawn"
        menu = visual_menu(pack, brief, drawn)
        old = {line["text"]: line for line in script["lines"]}
        lines = clean_lines([line for line in edits["lines"] if isinstance(line, dict)], pack, menu, drawn)
        for k, line in enumerate(lines):
            same = old.get(line["text"])
            if same and same.get("facts") == line["facts"]:
                line["check"] = same.get("check", "ok")
            else:
                line["check"] = ("edited-unsourced" if unsupported_numbers(line, pack, lines[k - 1] if k else None)
                                 else "edited")
            if drawn:
                line["visuals"] = line["visuals"][:1]
                if same and same.get("scene") == line["scene"]:  # the same drawing: the Reviewer's redraws stay
                    line.update({key: same[key] for key in ("redraws", "scene_hint", "seed_from") if key in same})
        if drawn:
            try:
                settle_scenes(lines)
            except ValueError:
                raise ValueError("Describe at least one drawing (a line's Drawing can't all be “same”).")
        if estimate_seconds(lines) > int(cfg["cases"].get("max_seconds", 75)) + 15:
            raise ValueError("That's too long for a Short: shorten or remove a line.")
        script["lines"] = lines
        script["seconds"] = round(estimate_seconds(lines), 1)
        script["habits"] = lecture_habits(lines)
    if "case_title" in edits:
        script["case_title"] = text_clean.screen_text(str(edits["case_title"]), TITLE_CHARS) or script["case_title"]
    if "title" in edits:
        meta["title"] = text_clean.title(str(edits["title"]), meta["title"])
    if "description" in edits:
        meta["description"] = text_clean.no_brackets(str(edits["description"])).strip()[:3000]
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--pack", required=True)
    parser.add_argument("--brief", required=True)
    args = parser.parse_args()
    try:
        with open(args.pack, encoding="utf-8") as f:
            pack = json.load(f)
        with open(args.brief, encoding="utf-8") as f:
            brief = json.load(f)
        result = write(brief, pack)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
