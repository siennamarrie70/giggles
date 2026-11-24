"""
Agent 2, Story: the day's story, written with your own script writer's prompt (prompts/script_writer.txt.enc: your
words, 2026-11-16, the whole system prompt, word for word), then turned into the film's moments and their bubbles.

The message is Agent 1's brief (agents/theme.py: "Write a story about LUST. Make the major incident emotionally
shocking...", "Choose a topic yourself. ...", or your own from the Themes page) with the channel's facts under it
(facts(): the main character is always the same man in the animation, everyone is an adult, the length, the film shows
it without a narrator (its people speak and think in bubbles), the recent stories so this one is new, and what the
Reviewer and the Analyst have taught). Gemini answers in your prompt's output format: Title, Central Theme, Core
Message, Full Script, Final Closing Line.

Code checks what it can (check_script): the length (WORDS; the brief asks for AIM), a title that's short and not an
earlier one, the closing line, adults only, nothing explicit, no gore or self-harm, no real brands. Problems go back to
Gemini with its draft, at most TRIES times; your prompt itself never changes.

The moments (write_moments; no narrator since 2026-11-19, your choice): a second call, with the channel's own prompt
(not yours), turns the story into MOMENTS moments across the six stages (STAGES): what we see, who is in it, and 0-2
bubbles each (say, think, shout, or a picture from the library's PICTURES), short enough to read
(silhouette_words.BUBBLE_WORDS, read_seconds). check_moments() holds them to the rules (every stage, enough bubbles, a
3-4 minute film's reading time, the speakers among its people, adults only, nothing explicit, no brands); problems go
back with the draft, at most TRIES times. The closing line is never a bubble: it stays the end quote on screen.

Agent 3 (agents/storyboard.py) then pictures the moments: the places, the people, a shot for every moment, each in its
stage of your prompt's six.

The short version (write_short; your choice, 2026-11-16): the same story told whole in under a minute for YouTube Shorts
and Instagram Reels. From the finished film Gemini picks SHORT_SHOTS of its shots (in its order, at least one from every
stage, ending on its last) and gives them shorter bubbles (SHORT_BUBBLE_WORDS words at most, SHORT_READ seconds of
reading in all). check_short() holds it to the rules and to its time (tools/story_film.py short_timeline: under a
minute). It's written the first time the Animator needs it, and kept with the story (story["short"]).

(split_lines and the narrator's lines below are a narrated story's, from before 2026-11-19: kept so going back is easy.)

Usage:
    python -m agents.story --brief "Write a story about GREED. Let the incident cost him his oldest friend."
    python -m agents.story --topic laziness --out .tmp/script.json   # Agent 1's brief about a topic, then the script
    python -m agents.story --choose                                  # Agent 1's "choose a topic yourself" brief
"""

import argparse
import difflib
import json
import re
import sys

import llm
import series
import silhouette_words as SR
from agents.base import act, advice, log, taught

TRIES = 3
WORDS = (380, 560)            # the script's words at least and at most (your prompt: about 450-550, by the pace)
AIM = (430, 490)              # what the facts ask for (a story that fills a 3-4 minute film)
TITLE_CHARS = 70
CLOSING_WORDS = (3, 30)
CLOSING_CHARS = 200           # ...and characters (it's shown big on screen at the end)
LINE_MOST, LINE_LEAST = 22, 3  # words in one of the narrator's lines, when code cuts a long sentence
LINE_GAP = 0.75                # seconds between two lines in the film, for estimates (tools/story_film.py's own)
OPEN_CLOSE = 6.0               # seconds of the title at the start and the closing line's hold at the end, for estimates
STAGES = ["hook", "incident", "collapse", "rock_bottom", "transformation", "payoff"]  # your prompt's six stages
STAGE_NAMES = {"hook": "The hook", "incident": "The major incident", "collapse": "The collapse",
               "rock_bottom": "Rock bottom", "transformation": "The transformation", "payoff": "The dream life"}

SHORT_TRIES = 3
SHORT_SHOTS = (8, 12)              # the film's shots the short version shows

_NUM = r"(?:[1-9]|1[0-7]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|" \
       r"sixteen|seventeen)"
ADULTS = re.compile(r"\b(child(?:ren)?|kids?|teen(?:s|age|ager|agers)?|toddlers?|(?:a|the|his|her|their|our) bab(?:y|ies)|"
                    r"infants?|newborns?|schoolboys?|schoolgirls?|underage|"
                    r"(?:little|young|baby|teenage) (?:sons?|daughters?|brothers?|sisters?|boys?|girls?)|"
                    r"as a (?:boy|girl|child|kid|teenager)|when (?:he|she) was (?:a )?(?:boy|girl|child|kid|teenager|little|"
                    + _NUM + r")|(?<![-\w])" + _NUM + r"[- ]years?[- ]old)\b", re.I)
EXPLICIT = re.compile(r"\b(sex|sexual intercourse|sexually explicit|naked|nude|nudity|porn\w*|erotic\w*|orgasm\w*|"
                      r"genital\w*|breasts?|lingerie|strip clubs?|strippers?|onlyfans|hook-?ups?|one-night stands?|"
                      r"masturbat\w*)\b", re.I)
GORE = re.compile(r"\b(blood(?:y|ied|stained)?(?! pressure| test| sugar| donation)|gore|gory|corpses?|dead bod(?:y|ies)|"
                  r"suicid\w*|self-harm\w*|kill(?:s|ed|ing)? (?:him|her|them)sel(?:f|ves)|overdos\w*|slit (?:his|her) "
                  r"\w+|guns?|pistols?|rifles?|stab(?:s|bed|bing|bings)?|shot (?:him|her|them|dead))\b", re.I)
BRANDS = re.compile(r"\b(nike|adidas|puma|reebok|apple|iphone|samsung|instagram|tiktok|youtube|facebook|twitter|netflix|"
                    r"google|coca-?cola|pepsi|starbucks|mcdonald\w*|red bull|playstation|xbox|nintendo|sony|rolex|uber|"
                    r"whatsapp|amazon|tesla|ferrari|lamborghini|gucci|louis vuitton|marlboro|heineken|budweiser)\b", re.I)
RULES = (("everyone in the story is an adult: no children or teenagers, not even in a memory", ADULTS),
         ("keep it clean for YouTube: nothing explicit (show desire through its signs and its cost)", EXPLICIT),
         ("no gore, weapons, self-harm or suicide", GORE),
         ("no real brands or companies", BRANDS))
ROMANCE = re.compile(r"\b(lust\w*|porn\w*|romanc\w*|dating|affairs?|cheat(?:s|ed|ing)?|seduc\w*|infatuat\w*|"
                     r"sexual\w*|flirt\w*|one-night|hook-?ups?)\b", re.I)
KIDS = re.compile(ADULTS.pattern + r"|\b(sons?|daughters?|(?:little|younger|baby) (?:brothers?|sisters?))\b", re.I)
KID_DANGER = re.compile(r"\b(hit(?:s|ting)?|punch\w*|slap\w*|beat(?:s|ing|en)?|kick\w*|fight\w*|shout\w*|scream\w*|"
                        r"yell\w*|rage|drunk\w*|drink(?:s|ing)?|alcohol\w*|beer|wine|whisk(?:e)?y|vodka|bottles?|fire|"
                        r"burn\w*|crash\w*|accident\w*|hospital\w*|blood\w*|weapons?|knife|knives|danger\w*|kidnap\w*|"
                        r"abus\w*|threat\w*|kiss\w*|sexy|lust\w*|porn\w*)\b", re.I)
KIDS_RULE = "children only in calm, safe family moments (never with violence, shouting, alcohol, danger or romance)"


def kids_allowed(story: dict) -> bool:
    """Children can be in this story (calm, safe family moments only): never in one about lust or romance."""
    return not ROMANCE.search(" ".join(str(story.get(k) or "") for k in ("topic", "instruction", "theme",
                                                                           "central_theme", "title", "core_message",
                                                                           "habit")))


def kids_rule(story: dict, short: bool = False) -> str:
    """What the writers are told about children (the owner's rule, 2026-11-23): his son or daughter, a little brother or
    sister, himself as a boy, in calm, safe family moments only; adults only in a story of lust or romance."""
    if not kids_allowed(story):
        return ("everyone is an adult (no children or teenagers, not even in a memory)" if short else
                "Everyone in the story is an adult: no children or teenagers, not even in a memory or a flashback.")
    return (KIDS_RULE if short else
            "Children may appear only in calm, safe family moments: his son or daughter, a little brother or sister, "
            "himself as a boy in a memory. Never with violence, shouting, alcohol, danger or anything romantic. Everyone "
            "else is an adult.")


SCRIPT_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string", "description": "Title: a compelling, curiosity-driven YouTube title"},
    "central_theme": {"type": "string", "description": "Central Theme: the weakness, virtue, or problem explored"},
    "core_message": {"type": "string", "description": "Core Message: the main lesson, in one sentence"},
    "full_script": {"type": "string", "description": "Full Script: the complete, polished, narration-ready script"},
    "closing_line": {"type": "string", "description": "Final Closing Line: one powerful, memorable sentence"}},
    "required": ["title", "central_theme", "core_message", "full_script", "closing_line"]}


def _clean(text) -> str:
    return " ".join(str(text or "").replace("’", "'").replace("‘", "'").split())


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", str(text).lower()).split())


def _plain_words(text: str) -> int:
    return len(str(text).split())


def rules_broken(text: str, kids: bool = False) -> list[str]:
    """The channel's rules a text breaks, in words for Gemini (or you), with what to take out. kids (kids_allowed): this
    story can have children, and then only a child near violence, alcohol, danger or romance breaks it (sentence by
    sentence)."""
    out = []
    for name, pattern in RULES:
        if kids and pattern is ADULTS:
            near = sorted({m.group(0).lower() for sentence in re.split(r"(?<=[.!?])\s+", text) if KIDS.search(sentence)
                           for m in KID_DANGER.finditer(sentence)})
            if near:
                out.append(f"{KIDS_RULE}: take out {', '.join(near[:6])} where the children are")
            continue
        found = sorted({m.group(0).lower() for m in pattern.finditer(text)})
        if found:
            out.append(f"{name}: take out {', '.join(found[:6])}")
    return out


def _writer() -> str:
    import prompts

    return prompts.load("script_writer")


def facts(brief: dict, recent: list[dict] | None = None, form: str = "long") -> str:
    """What the channel adds under the brief: facts for this script (your prompt is never changed), at the length of
    its form (a Short: 2-3 minutes; a long story: 3-4)."""
    from agents import theme

    recent = theme.recent_stories() if recent is None else recent
    L = limits(form)
    lines = [
        "The main character is a man, an adult. (The channel's animation always draws him the same way, so don't "
        "describe his looks or his clothes.) Give him his own background, job, age, personality and relationships.",
        kids_rule(brief),
        f"Length: the full script is about {L['aim'][0]}-{L['aim'][1]} words (it fills a {L['minutes']} minute "
        f"{L['film']})." + (" It's a Short, watched upright on phones: tell the whole story with a few places and "
                            "people, every moment counting." if form == "short" else ""),
        "Our film shows the story in pictures, without a narrator: what the people say to each other and what he "
        "thinks appears in speech and thought bubbles. Write the full script as your format asks, and give the people "
        "real moments to speak to each other and to think, so it can be shown.",
        "What our film can show well, where it fits this story (never force it): his phone ringing with a call, "
        "missed calls piling up, the phone's alarm going off, the endless feed of short videos pulling him in, texts "
        "piling up unanswered (\"Where are you??\"), a video playing when he should be busy; when he changes: training "
        "(push-ups, weights, the bench press, pull-ups, a jump rope, the heavy bag, the treadmill) and growing fit and "
        "strong; the life he builds: a sports car, a luxury car, a gold watch, a sharp suit, a penthouse over the "
        "city's lights, a safe of gold, a trophy.",
        "No headings, stage labels, sound cues or directions in the full script.",
        "No real people, brands or companies. Keep it clean for YouTube: nothing explicit, no gore, no self-harm.",
    ]
    if recent:
        lines.append("Recent stories on this channel; make this one different from all of them (another kind of "
                     "incident, another life and work, other places and people):\n"
                     + "\n".join(f"  - {theme.summary(v)}" for v in recent[:8]))
    learned = taught("story")
    worked = advice(("theme", "opening"))
    text = "Facts from the channel for this script:\n- " + "\n- ".join(lines)
    if worked:
        text += f"\nWhat has worked on this channel so far:\n{worked}"
    if learned:
        text += "\n" + learned
    return text


# --- the narrator's lines ------------------------------------------------------------------------------------------------
ABBREVIATIONS = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Prof|vs|etc|e\.g|i\.e|a\.m|p\.m)\.", re.I)
DOT = "․"                     # (an abbreviation's dot while the sentences are found)
SENTENCE_END = re.compile(r"[.!?…][\"”’)\]]*$")
HEADING = re.compile(r"^\s*(#{1,6}\s|\*\*[^*]+\*\*\s*$|\[[^\]]*\]\s*$|\([^)]*\)\s*$|(stage|part|act|scene)\s*\d\b)", re.I)


def clean_script(text: str) -> tuple[str, list[str]]:
    """The script as it will be read: paragraphs kept, headings, labels and cues taken out, markdown stars dropped.
    Returns (the script, what was taken out)."""
    paragraphs, dropped = [], []
    for row in str(text or "").replace("\r\n", "\n").split("\n"):  # (a narration script's every line break is a paragraph's)
        if HEADING.match(row):
            dropped.append(row.strip()[:60])
            continue
        para = " ".join(row.replace("**", "").replace("__", "").split())
        para = re.sub(r"(?<![\w*])\*(?=\S)([^*]+?)\*(?![\w*])", r"\1", para)
        if para:
            paragraphs.append(para)
    return "\n\n".join(paragraphs), dropped


def _split_long(words: list[str]) -> list[list[str]]:
    """A sentence longer than LINE_MOST words cut where it breathes (a comma, a semicolon, a dash, else "and", "but"...)
    nearest its middle; both halves at least LINE_LEAST words."""
    if len(words) <= LINE_MOST:
        return [words]
    n, best = len(words), None
    for i in range(LINE_LEAST, n - LINE_LEAST + 1):
        tok = words[i - 1]
        if re.search(r"[,;:][\"”’)\]]*$", tok) or tok in ("—", "–", "-") or tok.endswith(("—", "–")):
            score = abs(i - n / 2)
            if best is None or score < best[0]:
                best = (score, i)
    if best is None:
        for i in range(LINE_LEAST, n - LINE_LEAST + 1):
            if words[i].lower() in ("and", "but", "so", "because", "while", "until", "when", "then", "or", "as"):
                score = abs(i - n / 2)
                if best is None or score < best[0]:
                    best = (score, i)
    i = best[1] if best else n // 2
    return _split_long(words[:i]) + _split_long(words[i:])


def split_lines(script: str, closing: str = "") -> list[dict]:
    """The narrator's lines: every sentence (a long one cut where it breathes), in order, every word as written
    ({"text", "para": the first of a paragraph, "closing": the closing line said last because the script doesn't end
    on it})."""
    out = []
    for para in [p for p in re.split(r"\n\s*\n", script) if p.strip()]:
        text = ABBREVIATIONS.sub(lambda m: m.group(0).replace(".", DOT), para)
        sentence, first = [], True
        tokens = text.split()
        for k, tok in enumerate(tokens):
            sentence.append(tok)
            if SENTENCE_END.search(tok) or k == len(tokens) - 1:
                for piece in _split_long(sentence):
                    out.append({"text": " ".join(piece).replace(DOT, "."), "para": first, "closing": False})
                    first = False
                sentence = []
    closing = _clean(closing)
    if closing and out:
        last = out[-1]["text"]
        if difflib.SequenceMatcher(None, _plain(last), _plain(closing)).ratio() < 0.9 \
                and _plain(closing) not in _plain(" ".join(x["text"] for x in out[-3:])):
            out.append({"text": closing, "para": True, "closing": True})
    return out


def estimate(lines: list[dict]) -> float:
    """The script's length read aloud, roughly (before its moments: they set the film's own, estimate_moments)."""
    return sum(len(x["text"].split()) / 2.3 for x in lines) + LINE_GAP * len(lines) + OPEN_CLOSE


# --- the script ----------------------------------------------------------------------------------------------------------
def check_script(raw: dict, brief: dict, titles: list[str] | None = None,
                 form: str = "long") -> tuple[dict, list[str], list[str]]:
    """The script as code can take it (headings dropped, cut into lines), what's wrong with it (problems: it goes back)
    and what could be better (notes), in words for Gemini. Its length is its form's (limits)."""
    problems, notes = [], []
    L = limits(form)
    aim, most = L["aim"], L["words"]
    script, dropped = clean_script(raw.get("full_script"))
    if dropped:
        notes.append("the full script is read aloud as it is: no headings or labels in it (taken out: "
                     + "; ".join(dropped[:3]) + ")")
    title = _clean(raw.get("title")).strip(" \"'")
    theme = _clean(raw.get("central_theme")).strip(" .")
    message = _clean(raw.get("core_message"))
    closing = _clean(raw.get("closing_line")).strip(" \"'")
    words = _plain_words(script)
    if not most[0] <= words <= most[1]:
        problems.append(f"the full script has {words} words: write about {aim[0]}-{aim[1]} (it fills a "
                        f"{L['minutes']} minute {L['film']})")
    elif not aim[0] - 20 <= words <= aim[1] + 30:
        notes.append(f"the full script has {words} words: about {aim[0]}-{aim[1]} fits {L['minutes']} minutes best")
    if not title or SR.too_long(title, TITLE_CHARS) or len(title.split()) < 2:
        problems.append(f"the title: 2 or more words, at most {TITLE_CHARS} characters (no word over {SR.WORD_CHARS})")
    if re.search(r"[#@]|https?:|[\U0001F300-\U0001FAFF]", title):
        problems.append("no hashtags, links or emoji in the title")
    if title and _plain(title) in {_plain(t) for t in titles or [] if t}:
        problems.append("that title was used before: write a new one")
    if not theme or len(theme.split()) > 6:
        problems.append("the central theme: the weakness, virtue or problem, in a few words")
    if not message or len(message.split()) > 45:
        problems.append("the core message: one sentence")
    if not CLOSING_WORDS[0] <= _plain_words(closing) <= CLOSING_WORDS[1] or SR.too_long(closing, CLOSING_CHARS):
        problems.append(f"the final closing line: one sentence of {CLOSING_WORDS[0]}-{CLOSING_WORDS[1]} words, at most "
                        f"{CLOSING_CHARS} characters")
    problems += rules_broken(" ".join([title, theme, message, script, closing]),
                             kids=kids_allowed({**brief, "title": title, "theme": theme, "core_message": message}))
    lines = split_lines(script, closing)
    if lines and " ".join(x["text"] for x in lines if not x["closing"]) != " ".join(script.split()):
        problems.append("(code) the lines don't keep the script's words")  # (never expected: split_lines keeps them)
    seconds = estimate(lines)
    story = {"format": "script", "look": "silhouette", "form": form if form in ("short", "long") else "long",
             "brief": brief.get("instruction") or "",
             "mode": brief.get("mode") or "", "topic": brief.get("topic") or "", "theme": theme,
             "kind": brief.get("kind") or "", "title": title, "core_message": message, "script": script,
             "closing_line": closing, "lines": lines, "words": words, "estimate": round(seconds, 1)}
    return story, problems, notes


def _draft(raw: dict) -> str:
    return json.dumps({k: raw.get(k) for k in ("title", "central_theme", "core_message", "full_script", "closing_line")},
                      ensure_ascii=False)


def write(brief: dict, progress=log, form: str = "long") -> dict:
    """The script for the brief (Agent 1's) at its form's length (a Short: 2-3 minutes; a long story: 3-4): {"story",
    "script", "metadata"}. Raises when no try keeps the rules."""
    from agents import theme

    system = _writer()
    recent = theme.recent_stories()
    titles = [(v["plan"].get("story") or {}).get("title") or (v["plan"].get("metadata") or {}).get("title")
              for v in recent]
    base = f"{brief['instruction']}\n\n{facts(brief, recent, form)}"
    best, complaints, raw = None, [], {}
    for attempt in range(TRIES):
        prompt = base + ("\n\nYour last draft is below, with these problems. Write it again with every one fixed, keeping "
                         "what works:\n- " + "\n- ".join(complaints) + f"\nThe draft: {_draft(raw)}" if complaints else "")
        progress("Writing the script" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        raw = llm.generate_json([prompt], SCRIPT_SCHEMA, system, careful=True, thinking="MEDIUM", timeout_ms=300_000,
                               patient=True)
        story, problems, notes = check_script(raw, brief, titles, form)
        complaints = problems + notes
        if best is None or (len(problems), len(notes)) < (len(best[1]), len(best[2])):
            best = (story, problems, notes)
        if not problems and (not notes or attempt):  # (small notes are worth one more try, not two)
            break
        progress("Script problems: " + "; ".join(complaints[:5]))
    story, problems, notes = best
    if problems:
        raise RuntimeError("the script keeps breaking the rules: " + "; ".join(problems[:4]))
    if notes:
        progress("Kept with small notes: " + "; ".join(notes[:6]))
    story["notes"] = notes
    if not story["kind"]:
        story["kind"] = theme.kind_of(story["theme"])
    progress(f"Script written: \"{story['title']}\" ({story['theme']}), {story['words']} words")
    story = write_moments(story, progress)   # (shown, not read: its moments and their bubbles)
    return {"story": story, "script": {"look": "story", "lines": lines_of(story), "seconds": story["estimate"],
                                       "case_title": story["title"]},
            "metadata": metadata(story)}


# --- the moments: the story shown in pictures, its words in bubbles (no narrator; your choice, 2026-11-19) -----------------
MOMENTS = (28, 45)              # the film's moments (a shot each; the storyboard adds a few quiet ones)
MOMENT_STAGE_LEAST = 2          # moments in every stage at least
BUBBLES_LEAST = 18              # bubbles in the whole film at least
READ_SECONDS = (95.0, 195.0)    # all its bubbles' reading time (silhouette_words.read_seconds): with the pictures, 3-4 min
SHORT_WORDS = (230, 400)        # a Short's script (2-3 minutes, your plan of 2026-11-23): its words at least and at most
SHORT_AIM = (280, 340)          # ...what the facts ask for
SHORT_MOMENTS = (18, 28)        # ...its moments
SHORT_BUBBLES_LEAST = 12        # ...its bubbles at least
SHORT_READ_SECONDS = (70.0, 115.0)  # ...their reading time: with the pictures, 2-3 minutes (never 3:00: YouTube's Shorts)


def limits(form: str | None) -> dict:
    """The lengths a story of this form is written to: a Short ("short": 2-3 minutes, upright) or a long story (3-4)."""
    if form == "short":
        return {"words": SHORT_WORDS, "aim": SHORT_AIM, "moments": SHORT_MOMENTS, "bubbles": SHORT_BUBBLES_LEAST,
                "read": SHORT_READ_SECONDS, "minutes": "2-3", "film": "short film"}
    return {"words": WORDS, "aim": AIM, "moments": MOMENTS, "bubbles": BUBBLES_LEAST, "read": READ_SECONDS,
            "minutes": "3-4", "film": "film"}
PEOPLE_MOST = 8
PICTURE_WORDS_MOST = 4          # the words a picture bubble may carry under its picture
MOMENT_LEAD, MOMENT_TAIL = 0.5, 0.8   # a moment's shot before its first bubble and after its last (tools/story_film.py)
QUIET_MOMENT = 3.2              # a moment without a bubble, for estimates
HERO_WORDS = {"him", "he", "hero", "the_hero", "main_character", "protagonist", "the_man", "me", "i"}
SYMBOLS = re.compile(r"^[#@%!$&*?]+$")   # (swearing, never spelt out)


def _pid(text) -> str:
    return re.sub(r"[^a-z0-9_]", "", re.sub(r"\s+", "_", str(text or "").strip().lower()))[:24]


def bubbles_span(bubbles: list[dict]) -> float:
    """How long a moment's bubbles take, one after another (each from where the one before was read)."""
    return sum(SR.read_seconds(b.get("text") or "", b.get("picture") or "") for b in bubbles)


def estimate_moments(moments: list[dict], closing: str = "") -> float:
    """The film's length in seconds, roughly: each moment's bubbles read, a breath round them, the quiet ones, the title
    and the closing line read and held."""
    t = sum(MOMENT_LEAD + bubbles_span(m["bubbles"]) + MOMENT_TAIL if m["bubbles"] else QUIET_MOMENT for m in moments)
    return t + 3.5 + SR.read_seconds(closing) + 2.5


def _moments_schema() -> dict:
    bubble = {"type": "object", "properties": {
        "who": {"type": "string", "description": "him, or the id of a person in the moment"},
        "kind": {"type": "string", "enum": list(SR.BUBBLE_KINDS)},
        "text": {"type": "string", "description": f"the words: at most {SR.BUBBLE_WORDS} (a picture bubble: up to "
                                                  f"{PICTURE_WORDS_MOST}, or empty)"},
        "picture": {"type": "string", "enum": [""] + list(SR.PICTURES)},
        "wish": {"type": "string", "description": "a picture bubble whose picture isn't in PICTURES: the closest in "
                                                  "picture, and here what it should show (2-4 plain words); else empty"}},
        "required": ["who", "kind", "text", "picture"]}
    moment = {"type": "object", "properties": {
        "stage": {"type": "string", "enum": STAGES},
        "shows": {"type": "string", "description": "what we see, in one plain sentence"},
        "who": {"type": "array", "items": {"type": "string"}, "description": "everyone in the picture: him, people's ids"},
        "bubbles": {"type": "array", "items": bubble, "description": "0-2, in the order they appear"}},
        "required": ["stage", "shows", "who", "bubbles"]}
    person = {"type": "object", "properties": {"id": {"type": "string"}, "role": {"type": "string"}},
              "required": ["id", "role"]}
    return {"type": "object", "properties": {"people": {"type": "array", "items": person},
                                             "moments": {"type": "array", "items": moment}},
            "required": ["people", "moments"]}


def _moments_system(story: dict) -> str:
    L = limits(story.get("form"))
    pictures = "; ".join(f"{k} ({v})" for k, v in SR.PICTURES.items())
    kinds = "; ".join(f"{k}: {v}" for k, v in SR.BUBBLE_KINDS.items())
    return f"""You turn a short story into the moments of a silent animated film. The film has no narrator and no
subtitles: we watch the story happen, and what the people say to each other and what they think appears in bubbles over
their heads (speech bubbles, thought clouds, a shout's spiky burst, a thought showing a picture). Everyone is drawn as a
black silhouette with two white eyes; the hero is always the same man in a teal hoodie: never describe his looks.

THE STORY: "{story['title']}". Theme: {story.get('theme')}. Core message: {story.get('core_message')}
\"\"\"
{story['script']}
\"\"\"
Its closing line ("{story.get('closing_line')}") ends the film on screen by itself: it is never a bubble.

WHAT YOU WRITE
1. people: everyone besides him who appears (id: a short name like wife, boss, mother, friend; role: who they are to
   him, a few words). {kids_rule(story)} At most {PEOPLE_MOST}.
2. moments: the story told in {L['moments'][0]}-{L['moments'][1]} moments, in order, through its six stages (hook, incident, collapse,
   rock_bottom, transformation, payoff), every stage at least {MOMENT_STAGE_LEAST + 1} moments. Each moment is one picture:
   - stage;
   - shows: what we see, in one plain sentence (where he is, what he does, who is with him, the time if it matters);
   - who: everyone in the picture (him, people's ids);
   - bubbles: 0-2, what is said or thought in that moment, in order, each: who (him or someone in the moment), kind,
     text, picture.
   Bubble kinds: {kinds}.
3. How to tell it:
   - Tell the story through what the people say to each other and what he thinks. Plain spoken English, the way people
     really talk: short, concrete, alive. At most {SR.BUBBLE_WORDS} words in a bubble (most 4-9).
   - Never narrate: no captions, no "He felt...", no "Months later he...": only words someone says or thinks. A thought
     is in his own voice ("I can't keep doing this."); speech is said to someone in the same moment.
   - Some moments are silent (no bubble): where the picture says it (a look, a blow landing, a door closing, time
     passing). The film needs them to breathe.
   - Use a picture bubble where a picture says it faster than words: what he craves, fears, misses, wants, dreams of.
     A picture bubble carries up to {PICTURE_WORDS_MOST} words under its picture, or none.
   - The habit or struggle is shown big, like a cartoon, in the pictures and the bubbles: what it does to him, plainly.
   - The bubbles together take {L['read'][0]:.0f}-{L['read'][1]:.0f} seconds to read (each: one second to find it,
     then 2.5 words a second), so that with the pictures the film runs {L['minutes']} minutes. At least {L['bubbles']}
     bubbles.
   - Swearing appears only as #@%! in a shout, never spelt out.
4. PICTURES (for picture bubbles; use these words exactly): {pictures}
   When none of them shows what the moment needs, pick the closest and write in wish what it should show (2-4 plain
   words): it's drawn new for the film.

ALWAYS: {kids_rule(story, short=True)}; nothing explicit (desire shown only by its
symbols: hearts, lips, a censored phone screen); no gore, weapons or self-harm; no real brands, people or places."""


def check_moments(raw: dict, story: dict) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """The moments as code can take them ({"text": what we see, "stage", "who", "bubbles"}), the people ({"id",
    "role"}), what's wrong (problems: it goes back) and what could be better (notes), in words for Gemini."""
    problems, notes = [], []
    people, ids = [], {"him"}
    for p in raw.get("people") or []:
        pid = _pid(p.get("id") or p.get("role"))
        if not pid or pid in HERO_WORDS or pid in ids:
            continue
        ids.add(pid)
        people.append({"id": pid, "role": _clean(p.get("role"))[:80] or pid})
    if len(people) > PEOPLE_MOST:
        notes.append(f"{len(people)} people: at most {PEOPLE_MOST}")
    moments, last = [], 0
    reading, count = 0.0, 0
    closing = _plain(story.get("closing_line") or "")
    for k, m in enumerate(raw.get("moments") or []):
        where = f"moment {k + 1}"
        stage = m.get("stage") if m.get("stage") in STAGES else STAGES[last]
        if STAGES.index(stage) < last:
            problems.append(f"{where}: the stages go in order ({stage} after {STAGES[last]})")
            stage = STAGES[last]
        last = max(last, STAGES.index(stage))
        shows = _clean(m.get("shows"))[:240]
        if not shows:
            problems.append(f"{where}: say what we see (shows)")
        who = []
        for w in m.get("who") or []:
            w = "him" if _pid(w) in HERO_WORDS else _pid(w)
            if w in ids and w not in who:
                who.append(w)
        bubbles = []
        for b in m.get("bubbles") or []:
            speaker = "him" if _pid(b.get("who")) in HERO_WORDS or not _pid(b.get("who")) else _pid(b.get("who"))
            if speaker not in ids:
                problems.append(f"{where}: \"{speaker}\" isn't one of the people: add them to people, or give the words "
                                "to someone who is")
                continue
            kind = b.get("kind") if b.get("kind") in SR.BUBBLE_KINDS else "say"
            text = _clean(b.get("text")).strip(" \"'")
            picture = b.get("picture") if b.get("picture") in SR.PICTURES else ""
            n = len(text.split())
            if kind == "picture" and not picture:
                problems.append(f"{where}: a picture bubble shows one of PICTURES")
                kind = "think"
            if kind != "picture" and not text:
                notes.append(f"{where}: an empty bubble (left out)")
                continue
            if kind == "picture" and n > PICTURE_WORDS_MOST:
                problems.append(f"{where}: a picture bubble carries {PICTURE_WORDS_MOST} words at most (\"{text}\")")
            elif n > SR.BUBBLE_WORDS:
                problems.append(f"{where}: \"{text[:50]}...\" has {n} words: {SR.BUBBLE_WORDS} at most in a bubble")
            elif SR.too_long(text):
                problems.append(f"{where}: \"{text[:50]}...\" is too long to read in a bubble: {SR.BUBBLE_CHARS} "
                                f"letters at most, no word over {SR.WORD_CHARS}")
            if SYMBOLS.match(text.replace(" ", "")) and kind != "picture":
                kind = "shout"
            if kind == "say" and not [w for w in who if w != speaker]:
                notes.append(f"{where}: {speaker} speaks to no one in the picture: a thought")
                kind = "think"
            if closing and _plain(text) == closing:
                problems.append(f"{where}: the closing line is never a bubble (it ends the film on screen by itself)")
            if speaker not in who:
                who.append(speaker)
            bubble = {"who": speaker, "kind": kind, "text": text, "picture": picture if kind == "picture" else ""}
            wish = " ".join(_clean(b.get("wish") or "").split()[:5]).strip(" .\"'")[:40]
            if kind == "picture" and wish and not re.search(r"[#@<>{}]|https?:", wish):   # (no picture fits: Agent 3,
                bubble["wish"] = wish                                                       # Visuals, draws it new)
            bubbles.append(bubble)
        if len(bubbles) > 2:
            notes.append(f"{where}: at most 2 bubbles in a moment (the rest left out)")
            bubbles = bubbles[:2]
        reading += bubbles_span(bubbles)
        count += len(bubbles)
        moments.append({"text": shows, "stage": stage, "who": who or ["him"], "bubbles": bubbles})
    n = len(moments)
    L = limits(story.get("form"))
    least, most = L["moments"]
    if not least <= n <= most:
        (problems if n < least - 4 or n > most + (3 if story.get("form") == "short" else 6) else notes).append(
            f"{n} moments: tell it in {least}-{most}")
    for stage in STAGES:
        got = sum(1 for m in moments if m["stage"] == stage)
        if got < MOMENT_STAGE_LEAST:
            problems.append(f"the {STAGE_NAMES[stage].lower()} has {got} moments: at least {MOMENT_STAGE_LEAST + 1}")
    if count < L["bubbles"]:
        problems.append(f"{count} bubbles: the people talk and think more (at least {L['bubbles']})")
    if not L["read"][0] <= reading <= L["read"][1]:
        problems.append(f"the bubbles take {reading:.0f} s to read: aim for {L['read'][0]:.0f}-{L['read'][1]:.0f} s "
                        + ("(more of them, or fuller)" if reading < L["read"][0] else "(fewer, or shorter)"))
    problems += rules_broken(" ".join([p["role"] for p in people] + [m["text"] for m in moments]
                                      + [b["text"] for m in moments for b in m["bubbles"]]), kids=kids_allowed(story))
    return moments, people, problems, notes


def write_moments(story: dict, progress=log) -> dict:
    """The story's moments and people (Gemini, my prompt: your writer's stays as it is): the story with "lines" (the
    moments: one shot each, their bubbles), "people", "reading" (the bubbles' seconds) and "estimate". Raises when no
    try keeps the rules."""
    system = _moments_system(story)
    best, complaints, raw = None, [], {}
    for attempt in range(TRIES):
        prompt = "Turn this story into its film's moments."
        if complaints:
            prompt += ("\n\nYour last answer is below, with these problems. Write it again with every one fixed, keeping "
                       "what works:\n- " + "\n- ".join(complaints[:24]) + "\nThe answer: "
                       + json.dumps(raw, ensure_ascii=False)[:24000])
        progress("Writing the moments and their bubbles" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        raw = llm.generate_json([prompt], _moments_schema(), system, careful=True, thinking="MEDIUM", timeout_ms=300_000,
                               patient=True, strong=True, progress=progress)
        moments, people, problems, notes = check_moments(raw, story)
        complaints = problems + notes
        if best is None or (len(problems), len(notes)) < (len(best[2]), len(best[3])):
            best = (moments, people, problems, notes)
        if not problems and (not notes or attempt):
            break
        progress("Moments' problems: " + "; ".join(complaints[:5]))
    moments, people, problems, notes = best
    hard = [p for p in problems if any(w in p for w in ("adult", "children only", "explicit", "gore", "brand", "real "))]
    if hard or not moments:
        raise RuntimeError("the moments keep breaking the rules: " + "; ".join((hard or problems)[:4]))
    if problems:
        progress("Moments kept with problems: " + "; ".join(problems[:4]))
    reading = sum(bubbles_span(m["bubbles"]) for m in moments)
    story = {**story, "lines": moments, "people": people, "reading": round(reading, 1),
             "estimate": round(estimate_moments(moments, story.get("closing_line") or ""), 1),
             "moment_notes": problems + notes}
    progress(f"Moments: {len(moments)} ({sum(1 for m in moments if m['bubbles'])} with bubbles, "
             f"{sum(len(m['bubbles']) for m in moments)} bubbles, {reading:.0f} s of reading), {len(people)} people; "
             f"the film about {story['estimate'] / 60:.1f} minutes")
    return story


LONG_TITLE_END = " | An animated short film"  # a long story's title on YouTube: its topic in capitals, then this (your
#   format, 2026-11-24: "PROCRASTINATION | An animated short film"); a Short keeps its own title (your script writer's)
HEADLINE_WORDS, HEADLINE_CHARS = 5, 34          # the topic part of a long story's title, at most


def headline(story: dict) -> str:
    """A long story's topic for its YouTube title, in capitals: the one you set on the dashboard (story["headline"]),
    else the brief's topic ("the phone": "THE PHONE"), else, when the brief left the topic to your script writer, the
    first part of the central theme it named ("Harsh Gossip and Kindness": "HARSH GOSSIP")."""
    words = story.get("headline") or story.get("topic") or re.split(
        r"\s+(?:and|&|vs\.?|versus|or)\s+|[,;:(/]", story.get("theme") or "")[0]
    return " ".join(str(words).split()[:HEADLINE_WORDS]).strip(" .-|").upper()


def youtube_title(story: dict) -> str:
    """The video's title on YouTube: a long story's is its topic in capitals and LONG_TITLE_END; a Short's is its own."""
    top = headline(story) if story.get("form") != "short" else ""
    return f"{top}{LONG_TITLE_END}" if top else story["title"]


def metadata(story: dict) -> dict:
    """The video's title, description (the storyboard's, or the core message; the Publisher adds the chapters and the
    credits), tags and hashtags."""
    cfg = series.settings()
    theme = story.get("theme") or story.get("topic") or ""
    word = re.sub(r"[^a-z0-9]", "", theme.lower())
    hashtags = list(dict.fromkeys([*(cfg.get("hashtags") or []), f"#{word}" if word else ""]))
    tags = list(dict.fromkeys([theme.lower(), "motivation", "animation", "short film", "animated story",
                               "self improvement", "motivational story", *(story.get("tags") or [])]))[:15]
    return {"title": youtube_title(story), "description": story.get("description") or story.get("core_message") or "",
            "tags": [t for t in tags if t], "hashtags": [h for h in hashtags if h],
            "thumbnail_text": " ".join(w for w in ((story.get("thumbnail") or {}).get("lead", ""),
                                                   (story.get("thumbnail") or {}).get("punch", "")) if w)
            or theme.upper()}


def lines_of(story: dict) -> list[dict]:
    """The film's moments: what each shows, its bubbles and its shot (a story Agent 3 hasn't designed yet: no shots)."""
    if story.get("shots"):
        return [{"text": s.get("shows") or "", "bubbles": s.get("bubbles") or [], "shot": k}
                for k, s in enumerate(story["shots"])]
    return [{"text": x["text"], "bubbles": x.get("bubbles") or [], "shot": None} for x in story.get("lines") or []]


def scene_words(shot: dict) -> str:
    """A shot in plain words (the dashboard's scenes, the Reviewer's "it should show"): what Agent 3 said it shows, or
    (a story made before 2026-11-16) its place, light, him and what happens."""
    if shot.get("shows"):
        return shot["shows"]
    if shot.get("set") not in SR.SETS:
        return ""
    place = SR.SETS[shot["set"]][0].split(":")[0]
    bits = [f"{place}, {shot['light']}" + (", rain" if shot.get("rain") else "")]
    if shot.get("him", "none") != "none":
        bits.append(f"him {SR.POSES.get(shot['him'], shot['him'])} ({shot.get('eyes')} eyes)")
    else:
        bits.append("no one")
    if shot.get("other", "none") != "none":
        bits.append(f"with {SR.OTHERS.get(shot['other'], shot['other']).split(',')[0]} ({shot.get('other_pose') or 'standing'})")
    if shot.get("event", "none") != "none":
        bits.append(SR.EVENTS.get(shot["event"], shot["event"]).split(" (")[0])
    if shot.get("label"):
        bits.append(f'label "{shot["label"]}"')
    return "; ".join(bits)


def stage_of(shot: dict) -> str:
    return shot.get("stage") or shot.get("act") or ""


# --- the short version ------------------------------------------------------------------------------------------------------
SHORT_BUBBLE_WORDS = 9          # words in one of its bubbles at most (read on a phone)
SHORT_LABELS = 2                # time captions ("MONTHS LATER") it may add where it jumps in time
LABEL_WORDS = 3                 # ...each at most this many words
STRANGER_REWRITES = 2           # times the stranger's read may send it back to be made clearer (2026-11-23)
SHORT_READ = (20.0, 38.0)       # its bubbles' reading time in all: with the title, the pictures and the closing line, 45-58 s


def _bubble_words(bubbles: list[dict]) -> str:
    return "; ".join(f"{b['who']} ({b['kind']}{': ' + b['picture'] if b.get('picture') else ''}): \"{b['text']}\""
                     for b in bubbles) or "(no bubble)"


def _short_schema() -> dict:
    bubble = _moments_schema()["properties"]["moments"]["items"]["properties"]["bubbles"]["items"]
    return {"type": "object", "properties": {
        "shots": {"type": "array", "items": {"type": "object", "properties": {
            "shot": {"type": "integer", "description": "the film's shot number (1 = its first)"},
            "bubbles": {"type": "array", "items": bubble, "description": "0-2: its bubbles in the short version"},
            "label": {"type": "string", "description": "only where time jumps before this shot: a small time caption "
                                                       "(\"MONTHS LATER\", \"3:00 AM\"), at most 3 words; else empty"}},
            "required": ["shot", "bubbles"]}}},
        "required": ["shots"]}


def _short_system(story: dict) -> str:
    import story_film

    low, high = series.minutes()
    aim_low, aim_high = story_film.SHORT_SECONDS
    n = len(story["shots"])
    film = "\n".join(f"{k + 1}. [{stage_of(s)}] {scene_words(s)} | {_bubble_words(s.get('bubbles') or [])}"
                     for k, s in enumerate(story["shots"]))
    return f"""You make the short version of one episode of an animated YouTube series of silent motivational story films:
black silhouettes with a thin red rim of light and two white eyes, the hero a man in a teal hoodie. There's no narrator:
what the people say and think appears in bubbles over their heads. The full film runs {low:g}-{high:g} minutes. Its short
version tells the same story whole, for YouTube Shorts and Instagram Reels, in {aim_low:.0f}-{aim_high:.0f} seconds (never a
minute or more), upright, with the film's own pictures and shorter bubbles.

The episode: "{story['title']}" (theme: {story.get('theme')}). Its core message: {story.get('core_message') or ''}
There's no title in the picture: the short version begins straight with the story, so its first shot's bubble is the
hook. Its closing line ends it on screen by itself:
"{story.get('closing_line')}"

The film's {n} shots, in order ([its stage] what it shows | its bubbles: who (kind): "words"):
{film}

The short version:
- Pick {SHORT_SHOTS[0]}-{SHORT_SHOTS[1]} of these shots, in the film's order (rising numbers), that tell the whole story: at least
  one from every stage ({', '.join(STAGES)}). The last is shot {n}, the film's last. Prefer the shots where something
  happens: the habit at work, the incident, its cost, his lowest moment and the realization, the change, the life he built.
- Give each its bubbles: the film's own, made shorter (at most {SHORT_BUBBLE_WORDS} words each, at most 2 a shot), or none
  where the picture says it. Only someone in that shot can speak or think in it. The first shot's bubble is the hook: it
  makes a stranger scrolling past stop.
- It must make sense to a stranger scrolling past who never saw the film: who each person is, what happens, and why
  he changes, from the short version alone (it's what most people will ever see of the story). So:
  - keep a cause with its effect: the incident before what it costs him, his realization with what brings it on;
  - a reply only with the line it answers (in the same shot or the one just before it);
  - a person who matters is placed the first time we see them, by how they're spoken to ("Mom, ...", "Sir, ...",
    "Babe, ...") or by what the picture shows;
  - no bubble about something the short version doesn't show, and none that suggests what the story doesn't mean (a
    line that, out of the film, reads as something else);
  - where time jumps between two of your shots, give the later one a label: a small time caption ("MONTHS LATER",
    "3:00 AM", "A YEAR LATER"), at most 3 words; at most {SHORT_LABELS} labels in the short version.
- A bubble may be reworded, not only shortened, to carry what the skipped shots told, in that person's own voice (a
  line they would say or think there; never a narrator's caption).
- The bubbles together take {SHORT_READ[0]:.0f}-{SHORT_READ[1]:.0f} seconds to read (one second to find each, then 2.5 words a
  second).
- Swearing only as #@%! in a shout. Always: {kids_rule(story, short=True)}; nothing explicit, no gore, weapons or self-harm, no
  real brands."""


def check_short(raw: dict, story: dict) -> tuple[dict, list[str], list[str]]:
    """The short version as code can make it right (its shots in the film's order, ending on the film's last), what's
    still wrong with it (problems) and what could be better (notes), in words for Gemini."""
    import story_film

    problems, notes = [], []
    shots, n = story["shots"], len(story["shots"])
    picked, seen = [], set()
    for s in raw.get("shots") or []:
        try:
            k = int(s.get("shot"))
        except (TypeError, ValueError):
            continue
        if not 1 <= k <= n:
            problems.append(f"there's no shot {k}: the film's shots are 1-{n}")
            continue
        if k in seen:
            notes.append(f"shot {k} was picked twice (once is kept)")
            continue
        seen.add(k)
        base = shots[k - 1]
        here = {"him"} if base.get("him") else set()
        here |= {o["who"] for o in base.get("others") or []}
        bubbles = []
        for b in (s.get("bubbles") or [])[:2]:
            who = "him" if _pid(b.get("who")) in HERO_WORDS or not _pid(b.get("who")) else _pid(b.get("who"))
            if who not in here:
                problems.append(f"shot {k}: {who} isn't in that shot (only {', '.join(sorted(here)) or 'no one'})")
                continue
            kind = b.get("kind") if b.get("kind") in SR.BUBBLE_KINDS else "think"
            text = _clean(b.get("text")).strip(" \"'")
            picture = b.get("picture") if b.get("picture") in SR.PICTURES else ""
            if kind == "picture" and not picture:
                kind = "think"
            if kind != "picture" and not text:
                continue
            words = len(text.split())
            if words > (PICTURE_WORDS_MOST if kind == "picture" else SHORT_BUBBLE_WORDS):
                problems.append(f"shot {k}: \"{text[:40]}\" has {words} words: at most {SHORT_BUBBLE_WORDS} in the short")
            elif SR.too_long(text):
                problems.append(f"shot {k}: \"{text[:40]}\" is too long to read in a bubble: {SR.BUBBLE_CHARS} letters at "
                                f"most, no word over {SR.WORD_CHARS}")
            if kind == "say" and not here - {who}:
                kind = "think"
            bubbles.append({"who": who, "kind": kind, "text": text, "picture": picture if kind == "picture" else ""})
        label = _clean(s.get("label") or "").strip(" \"'.").upper()
        if label and (len(label.split()) > LABEL_WORDS or SR.too_long(label, 28)):
            problems.append(f"shot {k}: the label \"{label[:30]}\" is a small time caption: {LABEL_WORDS} words at most")
            label = ""
        picked.append({"shot": k, "bubbles": bubbles, **({"label": label} if label else {})})
    if [p["shot"] for p in picked] != sorted(p["shot"] for p in picked):
        notes.append("the shots go in the film's order")
        picked.sort(key=lambda p: p["shot"])
    if picked and picked[-1]["shot"] != n:
        notes.append(f"the last shot is the film's last (shot {n})")
        picked.append({"shot": n, "bubbles": []})
    if not SHORT_SHOTS[0] <= len(picked) <= SHORT_SHOTS[1]:
        (notes if SHORT_SHOTS[0] - 2 <= len(picked) <= SHORT_SHOTS[1] + 2 else problems).append(
            f"pick {SHORT_SHOTS[0]}-{SHORT_SHOTS[1]} shots (now {len(picked)})")
    stages = [x for x in dict.fromkeys(stage_of(s) for s in shots) if x]
    missing = [a for a in stages if a not in {stage_of(shots[p["shot"] - 1]) for p in picked}]
    if missing:
        problems.append("it tells the whole story: pick at least one shot from every stage (none from "
                        + ", ".join(missing) + ")")
    reading = sum(bubbles_span(p["bubbles"]) for p in picked)
    count = sum(len(p["bubbles"]) for p in picked)
    if not SHORT_READ[0] <= reading <= SHORT_READ[1]:
        (notes if SHORT_READ[0] - 6 <= reading <= SHORT_READ[1] + 4 else problems).append(
            f"its bubbles take {reading:.0f} s to read: aim for {SHORT_READ[0]:.0f}-{SHORT_READ[1]:.0f} s")
    if picked and not picked[0]["bubbles"]:
        notes.append("the first shot's bubble is the hook: give it one")
    short = {"shots": picked, "bubbles": count, "reading": round(reading, 1)}
    times = story_film.short_timeline(story_film.short_story(story, short))
    seconds = sum(t["seconds"] for t in times)
    if seconds >= story_film.SHORT_MOST - 1.0:
        problems.append(f"it would run {seconds:.0f} s: it must stay under a minute (fewer shots, shorter bubbles)")
    elif seconds < story_film.SHORT_SECONDS[0] - 3:
        notes.append(f"it would run only about {seconds:.0f} s: aim for {story_film.SHORT_SECONDS[0]:.0f}-"
                     f"{story_film.SHORT_SECONDS[1]:.0f} (a bubble or a shot more)")
    labelled = [p for p in picked if p.get("label")]
    if len(labelled) > SHORT_LABELS:
        notes.append(f"at most {SHORT_LABELS} labels (time captions): only where time jumps (the first {SHORT_LABELS} kept)")
        for p in labelled[SHORT_LABELS:]:
            p.pop("label")
    problems += rules_broken(" ".join([b["text"] for p in picked for b in p["bubbles"]]
                                      + [p["label"] for p in picked if p.get("label")]), kids=kids_allowed(story))
    short["estimate"] = round(seconds, 1)
    return short, problems, notes


STRANGER = """You scroll YouTube Shorts. This one is a silent animated short: black silhouettes, the hero a man in a teal
hoodie, no narrator (what people say or think shows in bubbles over their heads). You've never seen the story it comes
from. Below is everything it shows, shot by shot: what each shot shows, a time caption at the top if there is one, and
its bubbles (who (say, think, shout or picture): "words").

Read it as that first-time viewer. Retell the story you understood, in two sentences. Then list only what would really
confuse or mislead you: a person you can't place, a line that answers something you didn't see, a jump you can't
follow, a reason you can't find, a bubble that reads as something the story can't mean. Not matters of taste. An empty
list if it's clear."""
READ_SCHEMA = {"type": "object", "properties": {
    "retold": {"type": "string", "description": "the story as you understood it, in two sentences"},
    "problems": {"type": "array", "items": {"type": "object", "properties": {
        "shot": {"type": "integer", "description": "the shot's number above (1 = the first)"},
        "what": {"type": "string", "description": "what confuses or misleads you there, and why"}},
        "required": ["shot", "what"]}}},
    "required": ["retold", "problems"]}


def short_words(story: dict, short: dict) -> str:
    """The short version as a stranger meets it: each of its shots in order (what it shows, its time caption, its
    bubbles) and the closing line."""
    out = []
    for j, p in enumerate(short["shots"]):
        base = story["shots"][int(p["shot"]) - 1]
        label = p.get("label") or (base.get("label") or "").upper()
        out.append(f"{j + 1}. {f'[caption: {label}] ' if label else ''}{scene_words(base)} | {_bubble_words(p['bubbles'])}")
    return "\n".join(out) + f"\nAt the end, on screen by itself: \"{story.get('closing_line') or ''}\""


def read_short(story: dict, short: dict) -> dict:
    """The stranger's read (2026-11-23: short versions were misleading out of the film): one quick Gemini call reads the
    short version alone, as someone who never saw the film: {"retold", "problems": [{"shot" (the short's, 1 = its
    first), "what"}]}. A read that fails finds nothing: it never stops a short version."""
    try:
        raw = llm.generate_json([short_words(story, short)], READ_SCHEMA, STRANGER, patient=True)
    except Exception as e:
        return {"retold": "", "problems": [], "error": str(e)[:200]}
    problems = [{"shot": p["shot"] if isinstance(p.get("shot"), int) else None, "what": _clean(p.get("what"))[:240]}
                for p in raw.get("problems") or [] if _clean(p.get("what"))]
    return {"retold": _clean(raw.get("retold"))[:400], "problems": problems[:6]}


def _confusions(short: dict, read: dict) -> list[str]:
    """The stranger's confusions, as problems for the writer (in the film's shot numbers too)."""
    out = []
    for p in read["problems"]:
        j = p["shot"]
        where = (f"your shot {j} (the film's shot {short['shots'][j - 1]['shot']})"
                 if j and 1 <= j <= len(short["shots"]) else "your short version")
        out.append(f"a stranger who never saw the film was confused at {where}: {p['what']}")
    return out


def write_short(story: dict, progress=log, complaint: str | None = None) -> dict:
    """The short version of a finished story: {"shots": [{"shot" (the film's, 1 = its first), "bubbles", "label"
    (a time caption, where it jumps)}], "bubbles", "reading", "estimate", "notes", "read" (the stranger's)}. Each one
    that keeps the rules is read by a stranger (read_short); what confuses goes back to be made clearer, at most
    STRANGER_REWRITES times, and the clearest is kept. `complaint`: what was wrong with the last one. Raises when no try
    keeps the rules."""
    system = _short_system(story)
    best, score, complaints, rewrites = None, None, [complaint] if complaint else [], 0
    for attempt in range(SHORT_TRIES + STRANGER_REWRITES):
        prompt = (f"Make the short version of \"{story['title']}\".\n"
                  + ("\nYour last answer had these problems. Make it again with every one fixed:\n- "
                     + "\n- ".join(complaints) + "\n" if complaints else ""))
        progress("Making the short version" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        raw = llm.generate_json([prompt], _short_schema(), system, careful=True, thinking="MEDIUM", timeout_ms=180_000,
                               patient=True)
        short, problems, notes = check_short(raw, story)
        unclear = []
        if not problems:   # (it keeps the rules: does it make sense on its own?)
            short["read"] = read_short(story, short)
            unclear = _confusions(short, short["read"])
            progress(f"A stranger's read: \"{short['read']['retold'][:160]}\""
                     + (f" (confused by {len(unclear)})" if unclear else " (clear)"))
        if best is None or (len(problems), len(unclear), len(notes)) < score:
            best, score = (short, problems, notes), (len(problems), len(unclear), len(notes))
        if not problems and not unclear and (not notes or attempt):  # (small notes are worth one more try, not two)
            break
        if not problems and unclear:
            if rewrites >= STRANGER_REWRITES:
                break   # (still unclear after the rewrites: the clearest one is kept)
            rewrites += 1
        complaints = problems + unclear + notes
        progress("Short version problems: " + "; ".join(complaints[:5]))
    short, problems, notes = best
    if problems:
        raise RuntimeError("the short version keeps breaking the rules: " + "; ".join(problems[:4]))
    short["notes"] = notes
    progress(f"Short version: {len(short['shots'])} shots, {short['bubbles']} bubbles ({short['reading']:.0f} s of "
             f"reading), about {short['estimate']:.0f} s")
    return short


def run_short(story: dict, progress=log, complaint: str | None = None) -> dict:
    """write_short, logged as Agent 2's work."""
    def work(story, progress=log, complaint=None):
        short = write_short(story, progress, complaint)
        return {"script": short, "shots": len(short["shots"]), "bubbles": short["bubbles"], "seconds": short["estimate"]}

    return act("story", f"Make the short version: {story['title']}", work, story, progress=progress,
               complaint=complaint)["script"]


# --- your changes from the dashboard -----------------------------------------------------------------------------------------
def apply_edits(plan: dict, edits: dict) -> dict:
    """Your changes to a story from the dashboard: its title, a bubble's words ({"bubbles": [{"shot" (1 = the first),
    "bubble" (1 = its first), "text"}]}) and the closing line. The channel's rules hold (rules_broken). Returns the plan
    (the caller drops the old film and review)."""
    story = json.loads(json.dumps(plan["story"]))
    if not story.get("shots"):
        raise ValueError("This story has no storyboard yet: its bubbles come with it.")
    if "title" in edits and story.get("form") != "short":  # (a long story: you set its topic, LONG_TITLE_END follows)
        top = re.sub(r"\|\s*an animated short film\s*$", "", _clean(edits["title"]), flags=re.I).strip(" \"'|")
        if not top or len(top.split()) > HEADLINE_WORDS or SR.too_long(top, HEADLINE_CHARS):
            raise ValueError(f"The title: its topic, 1 to {HEADLINE_WORDS} words and {HEADLINE_CHARS} characters at most "
                             f"(“{LONG_TITLE_END.strip(' |')}” follows it by itself).")
        story["headline"] = top.upper()
    elif "title" in edits:
        title = _clean(edits["title"]).strip(" \"'")
        if len(title.split()) < 2 or SR.too_long(title, TITLE_CHARS):
            raise ValueError(f"The title: 2 words or more, {TITLE_CHARS} characters at most (no word over "
                             f"{SR.WORD_CHARS}).")
        story["title"] = title
    for e in edits.get("bubbles") or []:
        k, i = int(e["shot"]) - 1, int(e["bubble"]) - 1
        shots = story["shots"]
        if not 0 <= k < len(shots) or not 0 <= i < len(shots[k].get("bubbles") or []):
            raise ValueError(f"There's no bubble {i + 1} in shot {k + 1}.")
        b = shots[k]["bubbles"][i]
        text = _clean(e.get("text")).strip(" \"'")
        most = PICTURE_WORDS_MOST if b["kind"] == "picture" else SR.BUBBLE_WORDS
        if (not text and b["kind"] != "picture") or len(text.split()) > most or SR.too_long(text):
            raise ValueError(f"Shot {k + 1}, bubble {i + 1}: 1 to {most} words, {SR.BUBBLE_CHARS} characters at most "
                             f"(no word over {SR.WORD_CHARS}).")
        b["text"] = text
        m = shots[k].get("line_index")
        lines = story.get("lines") or []
        if m is not None and 0 <= m < len(lines) and i < len(lines[m].get("bubbles") or []):
            lines[m]["bubbles"][i]["text"] = text
    if "closing_line" in edits:
        closing = _clean(edits["closing_line"])
        if not CLOSING_WORDS[0] <= len(closing.split()) <= CLOSING_WORDS[1] or SR.too_long(closing, CLOSING_CHARS):
            raise ValueError(f"The closing line: {CLOSING_WORDS[0]} to {CLOSING_WORDS[1]} words, {CLOSING_CHARS} "
                             f"characters at most (no word over {SR.WORD_CHARS}).")
        story["closing_line"] = closing
    problems = rules_broken(" ".join([story["title"], story.get("headline") or "", story["closing_line"]]
                                     + [b["text"] for s in story["shots"] for b in s.get("bubbles") or []]))
    if problems:
        raise ValueError("The channel's rules: " + "; ".join(problems))
    story["estimate"] = round(estimate_moments(story.get("lines") or [], story.get("closing_line") or ""), 1)
    return {**plan, "brief": plan.get("brief") or {}, "story": story, "edited_at": _now_iso(),
            "script": {**(plan.get("script") or {}), "lines": lines_of(story), "seconds": story["estimate"],
                       "case_title": story["title"]},
            "metadata": {**(plan.get("metadata") or {}), "title": youtube_title(story)}}


def _now_iso() -> str:
    import db

    return db.now_iso()


def run(brief: dict, progress=log, form: str = "long") -> dict:
    what = "a Short's script" if form == "short" else "the script"
    return act("story", f"Write {what}: {brief.get('instruction', '')[:80]}", write, brief, progress=progress, form=form)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--brief", help="the brief, word for word (\"Write a story about ...\")")
    parser.add_argument("--topic", help="Agent 1 writes a brief about this topic first")
    parser.add_argument("--choose", action="store_true", help="Agent 1 writes a \"choose a topic yourself\" brief first")
    parser.add_argument("--out", help="save the story as JSON here")
    args = parser.parse_args()
    try:
        if args.brief:
            brief = {"mode": "request", "instruction": " ".join(args.brief.split()), "topic": "", "theme": "", "kind": ""}
        else:
            from agents import theme

            brief = theme.pick(topic=args.topic, choose=args.choose)["brief"]
        written = write(brief)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    text = json.dumps({"brief": brief, **written}, indent=1, ensure_ascii=False)
    if args.out:
        from pathlib import Path

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
