"""
Agent 2, Story: the day's script, written with your own script writer's prompt (prompts/script_writer.txt.enc: your
words, 2026-11-16, the whole system prompt, word for word).

The message is Agent 1's brief (agents/theme.py: "Write a story about LUST. Make the major incident emotionally
shocking...", "Choose a topic yourself. ...", or your own from the Themes page) with the channel's facts under it
(facts(): the main character is always the same man in the animation, everyone is an adult, the length at the narrator's
pace, the recent stories so this one is new, and what the Reviewer and the Analyst have taught). Gemini answers in your
prompt's output format: Title, Central Theme, Core Message, Full Script, Final Closing Line.

Code checks what it can (check_script): the length (WORDS; the brief asks for AIM), a title that's short and not an
earlier one, the closing line, adults only, nothing explicit, no gore or self-harm, no real brands. Problems go back to
Gemini with its draft, at most TRIES times; your prompt itself never changes. Then split_lines() cuts the script into
the narrator's lines (at sentence ends, a long sentence at a comma near its middle) without changing a word, and the
closing line ends the film: the narrator says it last when the script doesn't already end with it.

Agent 3 (agents/animator.py) then turns the script into pictures: the places, the people, a shot for every line, each
in its stage of your prompt's six (STAGES).

The short version (write_short; your choice, 2026-11-16): the same story told whole in under a minute for YouTube Shorts
and Instagram Reels. From the finished film Gemini picks SHORT_SHOTS of its shots (in its order, at least one from every
stage, ending on its last) and writes the narrator's new lines over them: SHORT_WORDS words (never more than
SHORT_MOST_WORDS: one reading), the first line a hook while the title shows at the top, the last the closing line.
check_short() holds it to the script's rules and to its time (tools/story_film.py short_timeline: under a minute when
read). It's written the first time the Animator needs it, and kept with the story (story["short"]).

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
import narrator
import series
import silhouette_words as SR
from agents.base import act, advice, log, taught

TRIES = 3
WORDS = (380, 560)            # the script's words at least and at most (your prompt: about 450-550, by the pace)
AIM = (430, 490)              # what the facts ask for: 3-4 minutes at the narrator's pace (2.3 words a second)
TITLE_CHARS = 70
CLOSING_WORDS = (3, 30)
LINE_MOST, LINE_LEAST = 22, 3  # words in one of the narrator's lines, when code cuts a long sentence
LINE_GAP = 0.75                # seconds between two lines in the film, for estimates (tools/story_film.py's own)
OPEN_CLOSE = 6.0               # seconds of the title at the start and the closing line's hold at the end, for estimates
STAGES = ["hook", "incident", "collapse", "rock_bottom", "transformation", "payoff"]  # your prompt's six stages
STAGE_NAMES = {"hook": "The hook", "incident": "The major incident", "collapse": "The collapse",
               "rock_bottom": "Rock bottom", "transformation": "The transformation", "payoff": "The dream life"}

SHORT_TRIES = 3
SHORT_SHOTS = (8, 14)              # the film's shots the short version shows
SHORT_WORDS = (55, 80)             # words the narrator says in it
SHORT_MOST_WORDS = narrator.PART_WORDS  # (90: more would take a second reading)
SHORT_LINES = (6, 10)
SHORT_LINE = (2, 14)               # words in one of its lines
SHORT_NEED_MOST = 53.0             # seconds: the least it can run, estimated; a slower reading must still stay under a minute

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


def rules_broken(text: str) -> list[str]:
    """The channel's rules a text breaks, in words for Gemini (or you), with what to take out."""
    out = []
    for name, pattern in RULES:
        found = sorted({m.group(0).lower() for m in pattern.finditer(text)})
        if found:
            out.append(f"{name}: take out {', '.join(found[:6])}")
    return out


def _writer() -> str:
    import prompts

    return prompts.load("script_writer")


def facts(brief: dict, recent: list[dict] | None = None) -> str:
    """What the channel adds under the brief: facts for this script (your prompt is never changed)."""
    from agents import theme

    recent = theme.recent_stories() if recent is None else recent
    lines = [
        "The main character is a man, an adult. (The channel's animation always draws him the same way, so don't "
        "describe his looks or his clothes.) Give him his own background, job, age, personality and relationships.",
        "Everyone in the story is an adult: no children or teenagers, not even in a memory or a flashback.",
        f"Length: the story runs 3-4 minutes read aloud by our narrator, who is calm and unhurried (about 2.3 words a "
        f"second), so the full script is about {AIM[0]}-{AIM[1]} words.",
        "The full script is read aloud exactly as written: no headings, stage labels, sound cues or directions in it.",
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
    """The film's length in seconds, roughly: his lines at his pace, a breath between them, the title and the end."""
    return sum(narrator.estimate_seconds(x["text"]) for x in lines) + LINE_GAP * len(lines) + OPEN_CLOSE


# --- the script ----------------------------------------------------------------------------------------------------------
def check_script(raw: dict, brief: dict, titles: list[str] | None = None) -> tuple[dict, list[str], list[str]]:
    """The script as code can take it (headings dropped, cut into lines), what's wrong with it (problems: it goes back)
    and what could be better (notes), in words for Gemini."""
    problems, notes = [], []
    script, dropped = clean_script(raw.get("full_script"))
    if dropped:
        notes.append("the full script is read aloud as it is: no headings or labels in it (taken out: "
                     + "; ".join(dropped[:3]) + ")")
    title = _clean(raw.get("title")).strip(" \"'")
    theme = _clean(raw.get("central_theme")).strip(" .")
    message = _clean(raw.get("core_message"))
    closing = _clean(raw.get("closing_line")).strip(" \"'")
    words = _plain_words(script)
    if not WORDS[0] <= words <= WORDS[1]:
        problems.append(f"the full script has {words} words: write about {AIM[0]}-{AIM[1]} (it's read at a calm 2.3 "
                        f"words a second and must run 3-4 minutes)")
    elif not AIM[0] - 20 <= words <= AIM[1] + 30:
        notes.append(f"the full script has {words} words: about {AIM[0]}-{AIM[1]} fits 3-4 minutes best")
    if not title or len(title) > TITLE_CHARS or len(title.split()) < 2:
        problems.append(f"the title: 2 or more words, at most {TITLE_CHARS} characters")
    if re.search(r"[#@]|https?:|[\U0001F300-\U0001FAFF]", title):
        problems.append("no hashtags, links or emoji in the title")
    if title and _plain(title) in {_plain(t) for t in titles or [] if t}:
        problems.append("that title was used before: write a new one")
    if not theme or len(theme.split()) > 6:
        problems.append("the central theme: the weakness, virtue or problem, in a few words")
    if not message or len(message.split()) > 45:
        problems.append("the core message: one sentence")
    if not CLOSING_WORDS[0] <= _plain_words(closing) <= CLOSING_WORDS[1]:
        problems.append(f"the final closing line: one sentence of {CLOSING_WORDS[0]}-{CLOSING_WORDS[1]} words")
    problems += rules_broken(" ".join([title, theme, message, script, closing]))
    lines = split_lines(script, closing)
    if lines and " ".join(x["text"] for x in lines if not x["closing"]) != " ".join(script.split()):
        problems.append("(code) the lines don't keep the script's words")  # (never expected: split_lines keeps them)
    seconds = estimate(lines)
    story = {"format": "script", "look": "silhouette", "brief": brief.get("instruction") or "",
             "mode": brief.get("mode") or "", "topic": brief.get("topic") or "", "theme": theme,
             "kind": brief.get("kind") or "", "title": title, "core_message": message, "script": script,
             "closing_line": closing, "lines": lines, "words": words, "estimate": round(seconds, 1)}
    return story, problems, notes


def _draft(raw: dict) -> str:
    return json.dumps({k: raw.get(k) for k in ("title", "central_theme", "core_message", "full_script", "closing_line")},
                      ensure_ascii=False)


def write(brief: dict, progress=log) -> dict:
    """The script for the brief (Agent 1's): {"story", "script", "metadata"}. Raises when no try keeps the rules."""
    from agents import theme

    system = _writer()
    recent = theme.recent_stories()
    titles = [(v["plan"].get("story") or {}).get("title") or (v["plan"].get("metadata") or {}).get("title")
              for v in recent]
    base = f"{brief['instruction']}\n\n{facts(brief, recent)}"
    best, complaints, raw = None, [], {}
    for attempt in range(TRIES):
        prompt = base + ("\n\nYour last draft is below, with these problems. Write it again with every one fixed, keeping "
                         "what works:\n- " + "\n- ".join(complaints) + f"\nThe draft: {_draft(raw)}" if complaints else "")
        progress("Writing the script" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        raw = llm.generate_json([prompt], SCRIPT_SCHEMA, system, careful=True, thinking="MEDIUM", timeout_ms=300_000,
                               patient=True)
        story, problems, notes = check_script(raw, brief, titles)
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
    progress(f"Script written: \"{story['title']}\" ({story['theme']}), {story['words']} words in {len(story['lines'])} "
             f"lines, about {story['estimate'] / 60:.1f} minutes")
    return {"story": story, "script": {"look": "story", "lines": lines_of(story), "seconds": story["estimate"],
                                       "case_title": story["title"]},
            "metadata": metadata(story)}


def metadata(story: dict) -> dict:
    """The video's title, description (the storyboard's, or the core message; the Publisher adds the chapters and the
    credits), tags and hashtags."""
    cfg = series.settings()
    theme = story.get("theme") or story.get("topic") or ""
    word = re.sub(r"[^a-z0-9]", "", theme.lower())
    hashtags = list(dict.fromkeys([*(cfg.get("hashtags") or []), f"#{word}" if word else ""]))
    tags = list(dict.fromkeys([theme.lower(), "motivation", "animation", "short film", "animated story",
                               "self improvement", "motivational story", *(story.get("tags") or [])]))[:15]
    return {"title": story["title"], "description": story.get("description") or story.get("core_message") or "",
            "tags": [t for t in tags if t], "hashtags": [h for h in hashtags if h],
            "thumbnail_text": " ".join(w for w in ((story.get("thumbnail") or {}).get("lead", ""),
                                                   (story.get("thumbnail") or {}).get("punch", "")) if w)
            or theme.upper()}


def lines_of(story: dict) -> list[dict]:
    """The narrator's script: each line with its direction and the shot it's over (a story Agent 3 hasn't designed yet:
    no shots)."""
    if story.get("shots"):
        return [{"text": s["line"], "direction": s.get("direction") or "", "shot": k}
                for k, s in enumerate(story["shots"]) if s.get("line")]
    return [{"text": x["text"], "direction": x.get("direction") or "", "shot": None} for x in story.get("lines") or []]


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

def _short_schema() -> dict:
    return {"type": "object", "properties": {
        "shots": {"type": "array", "items": {"type": "object", "properties": {
            "shot": {"type": "integer", "description": "the film's shot number (1 = its first)"},
            "line": {"type": "string", "description": "the narrator's words over it in the short version, or empty"},
            "direction": {"type": "string", "description": "a few words for his voice on this line, or empty"},
            "seconds": {"type": "number", "description": "how long a shot without a line stays on screen"}},
            "required": ["shot", "line", "direction", "seconds"]}}},
        "required": ["shots"]}


def _short_system(story: dict) -> str:
    import story_film

    low, high = series.minutes()
    aim_low, aim_high = story_film.SHORT_SECONDS
    quiet_low, quiet_high = story_film.SHORT_SILENT
    n = len(story["shots"])
    film = "\n".join(f"{k + 1}. [{stage_of(s)}] {scene_words(s)}" + (f'. Line: "{s["line"]}"' if s.get("line") else ". (no line)")
                     for k, s in enumerate(story["shots"]))
    return f"""You write the short version of one episode of an animated YouTube series of motivational story films: black
silhouettes with a thin red rim of light and two white eyes, the hero a man in a teal hoodie who never speaks; a calm, warm
narrator tells it. The full film runs {low:g}-{high:g} minutes. Its short version tells the same story whole, for YouTube
Shorts and Instagram Reels, in {aim_low:.0f}-{aim_high:.0f} seconds (never a minute or more), upright, with the film's own
pictures and the same narrator reading new lines.

The episode: "{story['title']}" (theme: {story.get('theme')}). Its core message: {story.get('core_message') or ''}
Its title shows at the top of the short version for its first seconds. Its closing line: "{story.get('closing_line')}"

The film's {n} shots, in order ([its stage] what it shows; the narrator's line in the film):
{film}

The short version:
- Pick {SHORT_SHOTS[0]}-{SHORT_SHOTS[1]} of these shots, in the film's order (rising numbers), that tell the whole story: at least
  one from every stage ({', '.join(STAGES)}). The last is shot {n}, the film's last. Prefer the shots where something
  happens: his weakness at work, the incident, the cost of it, his lowest moment and the realization, the change, the life
  he built.
- Write the narrator's lines for it, new ones (the film's are too long for a short): {SHORT_LINES[0]}-{SHORT_LINES[1]} lines,
  {SHORT_LINE[0]}-{SHORT_LINE[1]} words each, {SHORT_WORDS[0]}-{SHORT_WORDS[1]} words in all (count them; never more than
  {SHORT_MOST_WORDS}). He reads about 2.3 words a second.
- The first shot's line is the hook: it makes a stranger scrolling past stop and listen, while the title shows above
  it. Don't repeat the title's words.
- Each line fits the picture under it. A shot without a line stays {quiet_low:g}-{quiet_high:g} seconds ("seconds"); give it a
  reason to be there (a sound, his eyes, a door).
- The last shot's line is exactly the closing line.
- The film's voice: the way the film's lines tell it (the same person, his name if they use one), plain words, short
  sentences, concrete images. Each line gets a few words of direction for his voice: his mood and pace, never louder
  or higher (never loud, shouting, booming, resonant or excited): he's a calm, low voice, and a big moment is slower.
- Always: everyone is an adult, nothing explicit, no gore, weapons or self-harm, no real brands."""


def check_short(raw: dict, story: dict) -> tuple[dict, list[str], list[str]]:
    """The short version as code can make it right (its shots in the film's order, ending on the film's last shot with
    the closing line), what's still wrong with it (problems) and what could be better (notes), in words for Gemini."""
    import story_film

    problems, notes = [], []
    shots, n = story["shots"], len(story["shots"])
    closing = _clean(story.get("closing_line"))
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
        quiet = story_film.SHORT_SILENT
        picked.append({"shot": k, "line": _clean(s.get("line")),
                       "direction": narrator.voice_direction(_clean(s.get("direction")))[:80],
                       "seconds": round(min(max(float(s.get("seconds") or quiet[0]), quiet[0]), quiet[1]), 2)})
    if [p["shot"] for p in picked] != sorted(p["shot"] for p in picked):
        notes.append("the shots go in the film's order")
        picked.sort(key=lambda p: p["shot"])
    if picked and picked[-1]["shot"] != n:
        notes.append(f"the last shot is the film's last (shot {n}), with the closing line")
        picked.append({"shot": n, "line": "", "direction": "", "seconds": 3.0})
    for p in picked[:-1]:  # (the closing line is said once, over the last shot)
        if closing and p["line"].lower() == closing.lower():
            p["line"] = ""
    if picked:
        picked[-1]["line"] = closing
        picked[-1]["direction"] = picked[-1]["direction"] or "slow, warm, final"
    if not SHORT_SHOTS[0] <= len(picked) <= SHORT_SHOTS[1]:
        (notes if SHORT_SHOTS[0] - 2 <= len(picked) <= SHORT_SHOTS[1] + 2 else problems).append(
            f"pick {SHORT_SHOTS[0]}-{SHORT_SHOTS[1]} shots (now {len(picked)})")
    stages = [x for x in dict.fromkeys(stage_of(s) for s in shots) if x]
    missing = [a for a in stages if a not in {stage_of(shots[p["shot"] - 1]) for p in picked}]
    if missing:
        problems.append("it tells the whole story: pick at least one shot from every stage (none from "
                        + ", ".join(missing) + ")")
    lines = [p for p in picked if p["line"]]
    for p in lines:
        w = _plain_words(p["line"])
        if not SHORT_LINE[0] <= w <= SHORT_LINE[1] and p is not picked[-1]:
            (notes if w <= SHORT_LINE[1] + 4 else problems).append(
                f"the line over shot {p['shot']} has {w} words: {SHORT_LINE[0]}-{SHORT_LINE[1]} a line")
    words = sum(_plain_words(p["line"]) for p in lines)
    if words > SHORT_MOST_WORDS:
        problems.append(f"the narrator says {words} words: never more than {SHORT_MOST_WORDS} (write "
                        f"{SHORT_WORDS[0]}-{SHORT_WORDS[1]}: cut some lines)")
    elif not SHORT_WORDS[0] <= words <= SHORT_WORDS[1]:
        (notes if words >= SHORT_WORDS[0] - 12 else problems).append(
            f"the narrator says {words} words: write {SHORT_WORDS[0]}-{SHORT_WORDS[1]}")
    if not SHORT_LINES[0] <= len(lines) <= SHORT_LINES[1]:
        notes.append(f"{len(lines)} lines: write {SHORT_LINES[0]}-{SHORT_LINES[1]}")
    if picked and not picked[0]["line"]:
        notes.append("the first shot's line is the hook: give it one")
    short = {"shots": picked, "words": words, "lines": len(lines)}
    times = story_film.short_timeline(story_film.short_story(story, short))
    need, seconds = story_film.short_need(times), sum(t["seconds"] for t in times)
    if need > SHORT_NEED_MOST:
        problems.append(f"read aloud it would run at least {need:.0f} s: it must stay well under a minute (fewer words, "
                        "fewer shots)")
    elif seconds < story_film.SHORT_SECONDS[0] - 3:
        notes.append(f"it would run only about {seconds:.0f} s: aim for {story_film.SHORT_SECONDS[0]:.0f}-"
                     f"{story_film.SHORT_SECONDS[1]:.0f} (a line or a shot more)")
    problems += rules_broken(" ".join(p["line"] for p in picked))
    short["estimate"] = round(seconds, 1)
    return short, problems, notes


def write_short(story: dict, progress=log, complaint: str | None = None) -> dict:
    """The short version's script for a finished story: {"shots": [{"shot" (the film's, 1 = its first), "line",
    "direction", "seconds"}], "words", "lines", "estimate", "notes"}. `complaint`: what was wrong with the last one (it ran
    too long when read). Raises when no try keeps the rules."""
    system = _short_system(story)
    best, complaints = None, [complaint] if complaint else []
    for attempt in range(SHORT_TRIES):
        prompt = (f"Write the short version of \"{story['title']}\".\n"
                  + ("\nYour last draft had these problems. Write it again with every one fixed:\n- "
                     + "\n- ".join(complaints) + "\n" if complaints else ""))
        progress("Writing the short version" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        raw = llm.generate_json([prompt], _short_schema(), system, careful=True, thinking="MEDIUM", timeout_ms=180_000,
                               patient=True)
        short, problems, notes = check_short(raw, story)
        complaints = problems + notes
        if best is None or (len(problems), len(notes)) < (len(best[1]), len(best[2])):
            best = (short, problems, notes)
        if not problems and (not notes or attempt):  # (small notes are worth one more try, not two)
            break
        progress("Short version problems: " + "; ".join(complaints[:5]))
    short, problems, notes = best
    if problems:
        raise RuntimeError("the short version keeps breaking the rules: " + "; ".join(problems[:4]))
    short["notes"] = notes
    progress(f"Short version written: {len(short['shots'])} shots, {short['lines']} lines ({short['words']} words), "
             f"about {short['estimate']:.0f} s")
    return short


def run_short(story: dict, progress=log, complaint: str | None = None) -> dict:
    """write_short, logged as Agent 2's work."""
    def work(story, progress=log, complaint=None):
        short = write_short(story, progress, complaint)
        return {"script": short, "shots": len(short["shots"]), "words": short["words"], "seconds": short["estimate"]}

    return act("story", f"Write the short version: {story['title']}", work, story, progress=progress,
               complaint=complaint)["script"]


# --- your changes from the dashboard -----------------------------------------------------------------------------------------
EDIT_MAX_LINE = 30  # words in a line you write yourself


def apply_edits(plan: dict, edits: dict) -> dict:
    """Your changes to a story from the dashboard: its title, any narrator's line or its direction ({"lines": [{"line"
    (1 = the first), "text", "direction"}]}) and the closing line. The channel's rules hold (rules_broken). Returns the
    plan (the caller drops the old film and review)."""
    story = json.loads(json.dumps(plan["story"]))
    if not story.get("lines"):
        raise ValueError("This story was written before your script writer: it can't be edited here.")
    lines = story["lines"]
    if "title" in edits:
        title = _clean(edits["title"]).strip(" \"'")
        if len(title.split()) < 2 or len(title) > TITLE_CHARS:
            raise ValueError(f"The title: 2 words or more, {TITLE_CHARS} characters at most.")
        story["title"] = title
    for e in edits.get("lines") or []:
        k = int(e["line"]) - 1
        if not 0 <= k < len(lines):
            raise ValueError(f"There's no line {k + 1}.")
        text = _clean(e.get("text"))
        if not 1 <= len(text.split()) <= EDIT_MAX_LINE:
            raise ValueError(f"Line {k + 1}: 1 to {EDIT_MAX_LINE} words.")
        lines[k]["text"] = text
        if "direction" in e:
            lines[k]["direction"] = _clean(e.get("direction"))[:80]
    if "closing_line" in edits:
        closing = _clean(edits["closing_line"])
        if not CLOSING_WORDS[0] <= len(closing.split()) <= CLOSING_WORDS[1]:
            raise ValueError(f"The closing line: {CLOSING_WORDS[0]} to {CLOSING_WORDS[1]} words.")
        story["closing_line"] = closing
        if lines and lines[-1].get("closing"):
            lines[-1]["text"] = closing
    problems = rules_broken(" ".join([story["title"], story["closing_line"]] + [x["text"] for x in lines]))
    if problems:
        raise ValueError("The channel's rules: " + "; ".join(problems))
    for s in story.get("shots") or []:  # (the shots carry their line's words: Agent 3's design)
        if s.get("line_index") is not None and 0 <= s["line_index"] < len(lines):
            s["line"] = lines[s["line_index"]]["text"]
            s["direction"] = lines[s["line_index"]].get("direction") or s.get("direction") or ""
    story["words"] = sum(len(x["text"].split()) for x in lines if not x.get("closing"))
    story["estimate"] = round(estimate(lines), 1)
    return {**plan, "brief": plan.get("brief") or {}, "story": story, "edited_at": _now_iso(),
            "script": {**(plan.get("script") or {}), "lines": lines_of(story), "seconds": story["estimate"],
                       "case_title": story["title"]},
            "metadata": {**(plan.get("metadata") or {}), "title": story["title"]}}


def _now_iso() -> str:
    import db

    return db.now_iso()


def run(brief: dict, progress=log) -> dict:
    return act("story", f"Write the script: {brief.get('instruction', '')[:80]}", write, brief, progress=progress)


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
