"""
Agent 3's rules in code, for the faceless look: your prompt (prompts/agent3.txt.enc, word for word) writes the script, and
this makes sure it does what the prompt says, since a model can't count words reliably.

  niche(category)        which of the prompt's three niches a case type counts as (your choice, 2026-11-03)
  agent2_json(...)       the research pack in the shape the prompt reads ("INPUT (from Agent 2)")
  repair(raw, given)     what can be worked out exactly is set in code: word counts, every time, the totals, the tags
                         and pauses (where the prompt allows them), hook_text and the loop's texts
  problems(a3, given)    every rule of the prompt's FINAL CHECK that the repaired script still breaks, in words the
                         model can act on: they go back to it for another try (agents/writer.py)
  flatten(a3)            the script as the lines the rest of the system knows ({"text", "beat", "direction", "facts", ...})

Nothing here calls a service.
"""

import re

import spoken

SCHEMA_VERSION = "a3.v1"
PACE_WPS = 3.0
MIN_FACTS = 5
SECONDS = {3: 1.0, 4: 1.3, 5: 1.7, 6: 2.0, 7: 2.3, 8: 2.7, 9: 3.0, 10: 3.3, 11: 3.7, 12: 4.0}
BEATS = (  # (beat_id, beat_name, target_window, fewest words, most words, the roles it may hold)
    ("B1", "HOOK", "0:00-0:03", 8, 12, ("hook",)),
    ("B2", "PURPOSE_OPEN_LOOP_1", "0:03-0:10", 18, 24, ("stakes", "open_loop_1")),
    ("B3", "ESCALATION_CLOSE_1_OPEN_2", "0:10-0:22", 32, 38, ("escalation", "close_loop_1", "open_loop_2")),
    ("B4", "CLIMAX_CLOSE_LOOP_2", "0:22-0:42", 52, 60, ("climax", "close_loop_2")),
    ("B5", "TWIST_LOOP", "0:42-0:50", 18, 24, ("twist", "loop_bridge")),
)
ROLES = tuple(role for beat in BEATS for role in beat[5])
TONE = {"business": "punchy_analytical", "history": "cinematic_dramatic", "mythology": "epic_mysterious"}
NICHES = tuple(TONE)
# Your choice on 2026-11-03: the types your prompts don't name count as the nearest niche, so the channel keeps its variety.
# ("trending" is switched off in the settings; a case of it from before counts as business.)
NICHE_FOR = {"business": "business", "economy": "business", "technology": "business", "psychology": "business",
             "science": "business", "trending": "business", "history": "history", "dark_history": "history",
             "people": "history", "crime": "history", "mysteries": "history", "mythology": "mythology"}
FACT_TYPE = {"number": "number", "reaction": "quote", "background": "detail", "cause": "detail", "forecast": "detail",
             "turning_point": "event", "effect": "event", "story": "event"}
LESS_SURE = {"forecast", "reaction"}  # what someone expects or says, rather than what happened
# The channel's standing rules (config channel.voice), in the one input the prompt obeys for what mustn't be said:
STANDING = ["Do not give advice on money, health or law",
            "Do not take a side on politics: attribute opinions and forecasts to whoever made them",
            "Do not mock real people or any faith or culture, and do not state allegations as proven",
            "Do not mention children or teenagers",
            "Do not state a reaction, motive, cause or result that no fact states (who laughed, who refused, who was ruined, what "
            "nobody expected): the topic and the angle only ask, and only the facts say what happened"]
CHILD_WORDS = re.compile(r"\b(?:child|children|kids?|bab(?:y|ies)|boys?|girls?|teen\w*|toddlers?|infants?|schoolchildren|"
                         r"school(?:boy|girl)s?|youths?|minors?|adolescen\w*)\b", re.IGNORECASE)
BANNED = ("did you know", "have you ever", "imagine", "in this video", "let's dive in", "buckle up", "fun fact",
          "little did they know", "stay tuned", "wait till the end", "you won't believe", "like and subscribe",
          "follow for more", "today we", "hey guys", "without further ado", "game-changer", "and then", "after that")
BAD_OPENINGS = ("did you know", "imagine", "what if", "have you ever", "this is", "here's", "here is", "the story of")
JOINERS = ("but", "so", "therefore", "until")
CONTRAST = ("yet", "however", "still", "though", "although")
PACE_TAGS, PITCH_TAGS = ("fast pace", "slow pace"), ("drop pitch", "rise pitch")
PAUSES = (0.0, 0.2, 0.3, 0.5)
TAG = re.compile(r"\[([a-z0-9. ]+)\]", re.IGNORECASE)
DIRECTIONS = {"fast pace": "a little quicker, with energy", "slow pace": "slower, letting it land",
              "drop pitch": "his pitch falling at the end, final", "rise pitch": "his pitch rising at the end, left open"}
NOT_SPOKEN = re.compile(r"[0-9$%&/+#]")
ODD_MARKS = re.compile(r"[;()\[\]{}]")
CULTURES = re.compile(r"\b(greek|greece|roman|rome|norse|viking|japanese|japan|hindu|india|indian|egyptian|egypt|celtic|irish|"
                      r"welsh|chinese|china|aztec|maya|mayan|inca|mesopotamian|sumerian|babylonian|persian|slavic|korean|"
                      r"yoruba|african|polynesian|hawaiian|maori|arthurian|british|arabian|arab|mexican|native american|"
                      r"tibetan|buddhist|thai|vietnamese|mongol|mongolian|finnish|germanic|aboriginal|canaanite|hittite|"
                      r"zoroastrian|sanskrit|vedic)\b", re.IGNORECASE)


def niche(category: str | None) -> str:
    """The prompt's niche for a case type (anything else counts as history, the widest)."""
    return NICHE_FOR.get(category or "", "history")


def fact_id(pack_id: str) -> str:
    """A pack's fact id as the prompt writes them: F3 -> F03."""
    return f"F{int(pack_id[1:]):02d}"


def pack_fact(a3_id: str) -> str:
    """A fact id back as the pack writes them: F03 -> F3."""
    return f"F{int(a3_id[1:])}"


def agent2_json(brief: dict, pack: dict, video_id: str = "case") -> dict:
    """The research pack as the prompt's input. Every fact in the pack has passed the Researcher's checks (its quote
    is in its source, its numbers are in its quote), so it's high confidence; what someone expects or says is medium."""
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    story = pack.get("story") or {}
    # (not the Editor's paradox: it's written before the research, and what it assumes may not be so)
    conflicts = [f"{d.get('who')}: {d.get('decision')}" for d in story.get("decisions") or [] if d.get("decision")]
    twists = list(dict.fromkeys(by_id[f]["claim"] for f in (story.get("twist"), story.get("paradox")) if f in by_id))
    if pack.get("answer"):
        twists.append(pack["answer"])
    angle = brief.get("angle") or brief.get("topic") or ""
    return {"video_id": str(video_id), "niche": niche(brief.get("category")), "topic": brief.get("topic") or "",
            "angle": angle,
            "facts": [{"fact_id": fact_id(f["id"]), "fact": f["claim"], "type": FACT_TYPE.get(f.get("kind"), "detail"),
                       "confidence": "medium" if f.get("kind") in LESS_SURE else "high"} for f in pack.get("facts") or []],
            "conflicts": conflicts, "twist_candidates": twists, "do_not_claim": list(STANDING)}


def _words(text: str) -> list[str]:
    return text.split()


def seconds_for(words: int) -> float:
    """The prompt's table: how long a line of so many words takes (outside it, at the same pace)."""
    return SECONDS.get(words, round(words / PACE_WPS, 1))


def _clean_text(value) -> str:
    return " ".join(TAG.sub(" ", str(value or "")).split())


def _fact_ids(value, known: set[str]) -> list[str]:
    out = []
    for item in value or []:
        match = re.fullmatch(r"[Ff](\d{1,3})", str(item).strip())
        name = f"F{int(match[1]):02d}" if match else None
        if name in known and name not in out:
            out.append(name)
    return out


def _cite(line: dict, facts: dict[str, str]) -> None:
    """A number the line says that its cited facts don't have, but another fact does: that fact is cited too."""
    have = set()
    for name in line["fact_ids"]:
        have |= spoken.written_numbers(facts[name])
    for group in spoken.said_groups(line["text"]):
        if group & have:
            continue
        found = next((name for name, text in facts.items() if group & spoken.written_numbers(text)), None)
        if found and found not in line["fact_ids"]:
            line["fact_ids"].append(found)
            have |= spoken.written_numbers(facts[found])


def _first(text: str) -> str:
    return (text.split()[:1] or [""])[0].lower().strip(",.:;")


def _but(text: str, facts: str = "") -> str:
    """The line starting with "But": a word of contrast is swapped for it, otherwise it's put in front (its first word
    in lower case, unless the facts only ever write it with a capital: a name)."""
    head, _, rest = text.partition(" ")
    if head.lower().strip(",") in CONTRAST and rest:
        return f"But {rest}"
    word = head.strip(",.:;")
    lower = word[:1].lower() + word[1:]
    name = word == "I" or (word in facts and not re.search(rf"\b{re.escape(lower)}\b", facts))
    return f"But {head if name else lower + head[len(word):]} {rest}".strip()


def _no_but(text: str) -> str:
    """The line without the "But" it starts with."""
    rest = text.partition(" ")[2]
    return rest[:1].upper() + rest[1:]


def _settle_buts(beats: list[dict], facts: str = "") -> None:
    """The prompt's rules about "But" pull against each other: open_loop_2 starts with it, so does an escalation line,
    and no two lines in a row start with the same word. The model kept swapping one broken rule for another here (5 tries
    in a row, 2026-11-03), and what's needed is exact, so it's done here: a line that has to start with "But" gets it (a
    word of contrast is swapped for it; a line with room gets it in front), and a line that doesn't have to loses it
    when it stands next to one that does."""
    lines = [line for beat in beats for line in beat.get("lines") or [] if isinstance(line, dict)]
    for line in lines:
        line["text"] = _clean_text(line.get("text"))
    roomy = lambda line: len(line["text"].split()) < 12  # noqa: E731
    second = next((line for line in lines if line.get("role") == "open_loop_2"), None)
    if second and second["text"] and _first(second["text"]) != "but" and (roomy(second) or _first(second["text"]) in CONTRAST):
        second["text"] = _but(second["text"], facts)
    escalation = [line for line in lines if line.get("role") == "escalation" and line["text"]]
    must = {id(second)} if second else set()

    def beside_second(line) -> bool:
        k = next(i for i, x in enumerate(lines) if x is line)
        return any(0 <= i < len(lines) and lines[i] is second for i in (k - 1, k + 1))

    if escalation and not any(_first(line["text"]) == "but" for line in escalation):
        ways = [line for line in escalation if _first(line["text"]) in CONTRAST] + [line for line in escalation if roomy(line)]
        clear = [line for line in ways if not beside_second(line)]
        if clear:
            clear[0]["text"] = _but(clear[0]["text"], facts)
    buts = [line for line in escalation if _first(line["text"]) == "but"]
    keep = next((line for line in buts if not beside_second(line)), buts[0] if buts else None)
    if keep:
        must.add(id(keep))
    for a, b in zip(lines, lines[1:]):
        if _first(a["text"]) == "but" == _first(b["text"]):
            spare = next((x for x in (a, b) if id(x) not in must and len(x["text"].split()) > 3), None)
            if spare:
                spare["text"] = _no_but(spare["text"])


def repair(raw: dict, given: dict) -> dict:
    """The script with everything that can be worked out exactly worked out. `given` is what the prompt was given."""
    facts = {f["fact_id"]: f["fact"] for f in given.get("facts") or []}
    raw = {**raw, "beats": [dict(b, lines=[dict(l) for l in b.get("lines") or [] if isinstance(l, dict)])
                            for b in raw.get("beats") or [] if isinstance(b, dict)]}
    _settle_buts(raw["beats"], " ".join(facts.values()))
    context = raw.get("visual_context") if isinstance(raw.get("visual_context"), dict) else {}
    a3 = {"schema_version": SCHEMA_VERSION, "status": "ok", "error": None, "video_id": given["video_id"],
          "niche": given["niche"], "tone_profile": TONE.get(given["niche"]), "pace_wps": PACE_WPS,
          "hook_text": "", "loop_bridge_text": "", "loop_readthrough": "",
          "visual_context": {"era": " ".join(str(context.get("era") or "").split()),
                             "setting": " ".join(str(context.get("setting") or "").split()),
                             "key_subjects": [" ".join(str(s).split()) for s in context.get("key_subjects") or [] if str(s).strip()],
                             "real_people": [" ".join(str(s).split()) for s in context.get("real_people") or [] if str(s).strip()]},
          "beats": [], "total_word_count": 0, "total_pause_sec": 0.0, "est_total_duration_sec": 0.0,
          "warnings": [" ".join(str(w).split())[:200] for w in raw.get("warnings") or []][:10]}
    number, clock = 0, 0.0
    beats = [b for b in raw.get("beats") or [] if isinstance(b, dict)]
    for spec, beat in zip(BEATS, beats):
        made = {"beat_id": spec[0], "beat_name": spec[1], "target_window": spec[2], "word_count": 0, "lines": []}
        lines = [l for l in beat.get("lines") or [] if isinstance(l, dict)]
        for k, item in enumerate(lines):
            number += 1
            role = str(item.get("role") or "").strip()
            text = _clean_text(item.get("text"))
            if role == "loop_bridge":
                text = text.rstrip(" .,!?:;")
            tags = [t.lower().strip() for t in TAG.findall(str(item.get("tagged_text") or ""))]
            last_of_role = (role == "hook" and k == len(lines) - 1) or (role == "twist" and k + 1 < len(lines)
                                                                        and lines[k + 1].get("role") == "loop_bridge")
            pause = 0.0
            if role in ("open_loop_1", "open_loop_2", "close_loop_2") or last_of_role:
                try:
                    pause = min(PAUSES, key=lambda p: abs(p - float(item.get("pause_after_sec") or 0)))
                except (TypeError, ValueError):
                    pause = 0.0
            pace = next((t for t in tags if t in PACE_TAGS), None)
            pitch = next((t for t in tags if t in PITCH_TAGS), None) if role != "loop_bridge" else None
            parts = [f"[{pace}]" if pace else "", f"[{pitch}]" if pitch else "", text, f"[pause {pause:g}s]" if pause else ""]
            words = len(_words(text))
            hint = " ".join(str(item.get("visual_hint") or "").split())
            emphasis = [] if role == "loop_bridge" else [e for e in dict.fromkeys(" ".join(str(x).split())
                                                                                  for x in item.get("emphasis_words") or [])
                                                         if e and e in text and len(e.split()) <= 5][:2]
            line = {"line_id": f"L{number:02d}", "role": role, "text": text, "tagged_text": " ".join(p for p in parts if p),
                    "word_count": words, "pause_after_sec": pause, "est_start_sec": round(clock, 1),
                    "est_end_sec": round(clock + seconds_for(words) + pause, 1), "emphasis_words": emphasis,
                    "visual_hint": "same shot as L01" if role == "loop_bridge" else hint,
                    "fact_ids": _fact_ids(item.get("fact_ids"), set(facts))}
            _cite(line, facts)
            clock = line["est_end_sec"]
            made["word_count"] += words
            a3["total_pause_sec"] = round(a3["total_pause_sec"] + pause, 1)
            made["lines"].append(line)
        a3["beats"].append(made)
        a3["total_word_count"] += made["word_count"]
    every = [line for beat in a3["beats"] for line in beat["lines"]]
    a3["hook_text"] = " ".join(line["text"] for line in every if line["role"] == "hook")
    a3["loop_bridge_text"] = next((line["text"] for line in reversed(every) if line["role"] == "loop_bridge"), "")
    a3["loop_readthrough"] = f"{a3['loop_bridge_text']} {a3['hook_text']}".strip()
    a3["est_total_duration_sec"] = every[-1]["est_end_sec"] if every else 0.0
    return a3


def lines_of(a3: dict) -> list[dict]:
    return [line for beat in a3.get("beats") or [] for line in beat.get("lines") or []]


def problems(a3: dict, given: dict) -> list[str]:
    """Every rule of the prompt's FINAL CHECK the script breaks (empty: none), in words the model can act on."""
    found = []
    every = lines_of(a3)
    if [b["beat_id"] for b in a3.get("beats") or []] != [b[0] for b in BEATS]:
        return ["The script must have the 5 beats B1 to B5, in order, with their lines inside them."]
    for spec, beat in zip(BEATS, a3["beats"]):
        if not spec[3] <= beat["word_count"] <= spec[4]:
            count = beat["word_count"]
            change = f"add at least {spec[3] - count}" if count < spec[3] else f"take out at least {count - spec[4]}"
            found.append(f"{spec[0]} has {count} words; it must have {spec[3]}-{spec[4]} ({change}).")
        for line in beat["lines"]:
            if line["role"] not in spec[5]:
                found.append(f"{line['line_id']} has role '{line['role']}', which can't be in {spec[0]} "
                             f"(allowed: {', '.join(spec[5])}).")
    if not 135 <= a3["total_word_count"] <= 150:
        found.append(f"The script has {a3['total_word_count']} words in all; it must have 135-150.")
    if not 16 <= len(every) <= 22:
        found.append(f"The script has {len(every)} lines; it must have 16-22.")
    count = lambda role: sum(1 for line in every if line["role"] == role)  # noqa: E731
    for role in ("open_loop_1", "close_loop_1", "open_loop_2", "close_loop_2", "loop_bridge"):
        if count(role) != 1:
            found.append(f"The script must have exactly one line with role {role} (it has {count(role)}).")
    for beat_id, role in (("B2", "open_loop_1"), ("B3", "open_loop_2"), ("B5", "loop_bridge")):
        beat = next(b for b in a3["beats"] if b["beat_id"] == beat_id)
        if beat["lines"] and beat["lines"][-1]["role"] != role:
            found.append(f"The last line of {beat_id} must have role {role}.")
    for beat_id, role, least, most in (("B2", "stakes", 1, 3), ("B3", "escalation", 1, 3), ("B4", "climax", 2, 5),
                                       ("B5", "twist", 1, 3), ("B1", "hook", 1, 2)):
        beat = next(b for b in a3["beats"] if b["beat_id"] == beat_id)
        n = sum(1 for line in beat["lines"] if line["role"] == role)
        if not least <= n <= most:
            found.append(f"{beat_id} must have {least}-{most} '{role}' lines (it has {n}).")
    escalation = [line for line in every if line["role"] == "escalation"]
    if escalation and not any(line["text"].lower().startswith("but ") for line in escalation):
        found.append("At least one escalation line in B3 must start with 'But'.")
    second = next((line for line in every if line["role"] == "open_loop_2"), None)
    if second and not second["text"].lower().startswith("but "):
        found.append(f"{second['line_id']} (open_loop_2) must start with 'But'.")
    for k, line in enumerate(every):
        text, name = line["text"], line["line_id"]
        if not 3 <= line["word_count"] <= 12:
            found.append(f"{name} has {line['word_count']} words; every line needs 3-12 words.")
        sentences = [s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
        if len(sentences) > 2:
            found.append(f"{name} has {len(sentences)} sentences; at most 2.")
        for sentence in sentences:
            if len(sentence.split()) > 12:
                found.append(f"{name} has a sentence over 12 words.")
        if NOT_SPOKEN.search(text):
            found.append(f"{name} has a digit or symbol ('{NOT_SPOKEN.search(text)[0]}'): write it as spoken words.")
        if ODD_MARKS.search(text):
            found.append(f"{name} has a semicolon, parenthesis or bracket.")
        young = CHILD_WORDS.search(text)
        if young:
            found.append(f"{name} says '{young[0]}': never mention children or teenagers. Say who it was another way, or leave them out.")
        lower = text.lower()
        hit = next((b for b in BANNED if b in lower), None)
        if hit:
            found.append(f"{name} uses the banned phrase '{hit}'.")
        if lower.startswith("next "):
            found.append(f"{name} starts with 'Next', which is banned.")
        if k and text.split()[:1] and every[k - 1]["text"].split()[:1] \
                and text.split()[0].lower().strip(",.:") == every[k - 1]["text"].split()[0].lower().strip(",.:"):
            found.append(f"{every[k - 1]['line_id']} and {name} both start with '{text.split()[0]}': reword one of them so "
                         "it starts with a different word, with the same number of words.")
        if line["role"] != "loop_bridge" and not 4 <= len(line["visual_hint"].split()) <= 12:
            found.append(f"{name}'s visual_hint must be 4-12 words.")
        have = set()
        for fid in line["fact_ids"]:
            have |= spoken.written_numbers(next((f["fact"] for f in given.get("facts") or [] if f["fact_id"] == fid), ""))
        for number in spoken.unsupported(text, have):
            found.append(f"{name} says the number {number:g}, which isn't in any fact. Use only numbers from the facts.")
    joined = sum(1 for line in every if line["text"].split()[:1]
                 and line["text"].split()[0].lower().strip(",.:") in JOINERS)
    if joined < 3:
        found.append(f"Only {joined} lines start with But, So, Therefore or Until; at least 3 must.")
    hook = a3["hook_text"].lower()
    opening = next((o for o in BAD_OPENINGS if hook.startswith(o)), None)
    if opening:
        found.append(f"The hook must not start with '{opening}'.")
    if re.split(r"(?<=[.?!])\s+", a3["hook_text"])[0].endswith("?"):
        found.append("The hook must not start with a question.")
    bridge = a3["loop_bridge_text"]
    if bridge and not 4 <= len(bridge.split()) <= 8:
        found.append(f"The loop_bridge has {len(bridge.split())} words; it must have 4-8.")
    if not 1.0 <= a3["total_pause_sec"] <= 2.0:
        found.append(f"The pauses add up to {a3['total_pause_sec']:g} s; they must add up to 1.0-2.0 s. Pauses go only after "
                     "the last hook line, open_loop_1, open_loop_2, close_loop_2 and the last twist line.")
    if not 46 <= a3["est_total_duration_sec"] <= 52:
        found.append(f"The script comes to {a3['est_total_duration_sec']:g} s by the table; it must be 46-52 s.")
    climax = next(b for b in a3["beats"] if b["beat_id"] == "B4")
    climax_text = " ".join(line["text"] for line in climax["lines"])
    if a3["niche"] in ("business", "history"):
        known = set()
        for fact in given.get("facts") or []:
            known |= spoken.written_numbers(fact["fact"])
        if len(known) >= 2 and len(spoken.said_groups(climax_text)) < 2:
            found.append("B4 must use at least 2 concrete numbers or dates from the facts.")
    if a3["niche"] == "mythology":
        if not re.search(r"\b(legend|legends|myth|myths)\b", " ".join(line["text"] for line in every), re.IGNORECASE):
            found.append("Frame claims as legend at least once ('legend says', 'the myth says').")
        setup = next(b for b in a3["beats"] if b["beat_id"] == "B2")
        if not CULTURES.search(" ".join(line["text"] for line in setup["lines"])):
            found.append("Name the culture of origin in B2 (Greek, Norse, Japanese, Hindu, Egyptian...).")
    for label, value, least, most in (("key_subjects", len(a3["visual_context"]["key_subjects"]), 3, 6),):
        if not least <= value <= most:
            found.append(f"visual_context.{label} must have {least}-{most} items.")
    if not a3["visual_context"]["setting"]:
        found.append("visual_context.setting is missing.")
    return found


BEAT_FOR = {"hook": "hook", "stakes": "setup", "open_loop_1": "setup", "escalation": "turn", "close_loop_1": "turn",
            "open_loop_2": "turn", "climax": "reveal", "close_loop_2": "reveal", "twist": "reveal", "loop_bridge": "closing"}


def direction(tagged_text: str) -> str:
    """How a line is read, from its voice tags (Gemini's documented way: a direction for each line, so the tags are
    never read aloud). Its pause is set in code (tools/narration.py)."""
    return ", ".join(DIRECTIONS[t] for t in (t.lower().strip() for t in TAG.findall(tagged_text or "")) if t in DIRECTIONS)


def flatten(a3: dict) -> list[dict]:
    """The script as the lines the rest of the system reads (the Reviewer, the Publisher's credits, the dashboard)."""
    return [{"text": line["text"], "beat": BEAT_FOR.get(line["role"], "turn"), "direction": direction(line["tagged_text"]),
             "facts": [pack_fact(f) for f in line["fact_ids"]], "visuals": [], "line_id": line["line_id"],
             "role": line["role"], "pause": line["pause_after_sec"], "emphasis": line["emphasis_words"]}
            for line in lines_of(a3)]


def retext(a3: dict, line_id: str, text: str) -> None:
    """A line's words replaced (the fact-checker's correction); repair() then works out what follows from them."""
    for line in lines_of(a3):
        if line["line_id"] == line_id:
            line["tagged_text"] = line["tagged_text"].replace(line["text"], text)
            line["text"] = text
