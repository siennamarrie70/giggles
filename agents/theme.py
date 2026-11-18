"""
Agent 1, Theme: the day's brief for your script writer (Agent 2, agents/story.py).

Your examples of how the software briefs the writer (2026-11-16), examples of the kind, never templates:
  "Write a story about LUST. Make the major incident emotionally shocking, and give the character a powerful
   transformation."
  "Write a story about LAZINESS. Make the consequences affect the character's family, career, and future."
  "Choose a topic yourself. I want a highly relatable story about a destructive habit that can ruin someone's life."

So a day's brief is one of two kinds:
  topic   "Write a story about <TOPIC>. <the direction>": the topic from series.themes, a weakness and a virtue in turn,
          never one used within series.repeat_after_days
  choose  "Choose a topic yourself. <the direction>": every CHOOSE_EVERY-th story (your third example); the writer's
          Central Theme then becomes the story's topic
The direction is the story's own angle in one or two sentences, written fresh by one Gemini call that sees the recent
briefs and stories (never the same angle twice; code checks it isn't close to a recent one). Your own brief, typed on the
Themes page, goes first and is sent word for word (a word or two, like "greed", is taken as the topic of a topic brief).
Agent 2 adds the channel's facts under the brief (the main character, adults only, the length, the recent stories).

Usage:
    python -m agents.theme                  # the next brief (nothing saved)
    python -m agents.theme --topic lust     # a brief about one topic
    python -m agents.theme --choose         # a "choose a topic yourself" brief
"""

import argparse
import difflib
import json
import re
import sys
from datetime import timedelta

import db
import llm
import series
from agents.base import act, advice, log, taught

TRIES = 3
CHOOSE_EVERY = 4                 # every 4th story's brief leaves the topic to the writer (your third example)
DIRECTION_WORDS = (6, 45)
SAME_DIRECTION = 0.72            # this close to a recent direction (difflib's ratio) is the same direction again
NAMED_TOPICS = ("procrastinat", "lazi", "lazy", "lust", "greed", "jealous", "envious", "arrogan", "pride", "addict",
                "gambl", "anger", "angry", "dishonest", "lying", "liar", "selfish", "impatien", "discipline", "courage",
                "self-respect", "ego")    # (word stems: a choose brief that says one of these has chosen the topic)
EXAMPLES = [
    "Write a story about LUST. Make the major incident emotionally shocking, and give the character a powerful "
    "transformation.",
    "Write a story about LAZINESS. Make the consequences affect the character's family, career, and future.",
    "Choose a topic yourself. I want a highly relatable story about a destructive habit that can ruin someone's life.",
]
SCHEMA = {"type": "object", "properties": {
    "topic": {"type": "string", "description": "for a topic brief: one of the topics offered, exactly as written; "
                                               "for a choose brief: empty"},
    "direction": {"type": "string", "description": "one or two sentences to the writer: this story's own angle"}},
    "required": ["topic", "direction"]}
SYSTEM = """You brief a scriptwriter. Every day the writer writes one 3-4 minute animated YouTube story about a human
weakness, destructive habit or virtue: a man's weakness leads to a major incident, his life falls apart, he reaches rock
bottom and realizes, then changes and builds the life he wanted.

Your brief names the topic (or leaves the choice to the writer) and adds one or two sentences of direction: what makes
this story its own. The channel owner's examples of briefs (examples of the kind: never copy their wording, and never
give the same direction twice):
{examples}

A good direction asks for something specific that the recent stories didn't have: the kind of major incident, which
parts of his life the consequences reach, what brings his realization, his life or work, where he lives, the tone, how the
change shows. Plain words, said to the writer ("Make...", "Let...", "I want...", "Show..."). Don't start with "Write a
story" or "Choose a topic" (that part is added). Never name a real person, brand or company; never ask for anything
sexual, gory or cruel, or for children."""


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", str(text).lower()).split())


def recent_stories(days: int = 120) -> list[dict]:
    """The series' stories of the last `days`, newest first (their briefs, titles and what they were about only:
    db.LIGHT). Stories set aside (skipped) are left out."""
    return [v for v in db.recent_videos(days=days, parts=("brief", "metadata.title", "story.title", "story.theme",
                                                          "story.core_message", "story.logline"))
            if v["format"] == series.STORY and v["plan"].get("brief") and v["status"] not in ("skipped",)]


def summary(v: dict) -> str:
    """A recent story in one line: its title, topic and what happened (for the briefs and the writer)."""
    plan, story = v["plan"], v["plan"].get("story") or {}
    title = story.get("title") or (plan.get("metadata") or {}).get("title") or ""
    theme = story.get("theme") or (plan.get("brief") or {}).get("theme") or ""
    what = story.get("logline") or story.get("core_message") or ""
    return f"\"{title}\" ({theme})" + (f": {what}" if what else "")


def candidates(recent: list[dict], avoid: list[str] | None = None) -> tuple[str, list[str]]:
    """The kind due (vice or virtue: the other one from the last story's) and the themes of it not used lately."""
    themes = series.themes()
    last_kind = next(((v["plan"].get("brief") or {}).get("kind") for v in recent
                      if (v["plan"].get("brief") or {}).get("kind") in ("vice", "virtue")), None)
    kind = "virtue" if last_kind == "vice" else "vice"
    days = int(series.settings().get("repeat_after_days") or 30)
    cutoff = db.now_iso(-timedelta(days=days))
    used = {_plain((v["plan"].get("brief") or {}).get("theme") or "") for v in recent if v["created_at"] >= cutoff}
    avoid = {_plain(a) for a in avoid or []}
    for k in (kind, "virtue" if kind == "vice" else "vice"):
        pool = [t for t in themes[f"{k}s"] if _plain(t) not in used and _plain(t) not in avoid]
        if pool:
            return k, pool
    # every theme used within the window: the least recently used of the kind due
    order = [_plain((v["plan"].get("brief") or {}).get("theme") or "") for v in recent]
    pool = sorted(themes[f"{kind}s"], key=lambda t: -(order.index(_plain(t)) if _plain(t) in order else 10_000))
    return kind, pool[:3] or ["discipline"]


def kind_of(topic: str) -> str:
    """vice or virtue, by the settings' lists (a topic on neither is taken as a weakness: the stories are about one)."""
    themes = series.themes()
    return "virtue" if _plain(topic) in {_plain(t) for t in themes["virtues"]} else "vice"


def choose_due(recent: list[dict]) -> bool:
    """Every CHOOSE_EVERY-th story leaves the topic to the writer: due when the last CHOOSE_EVERY - 1 briefs (of this
    kind of brief) all named one."""
    modes = [(v["plan"].get("brief") or {}).get("mode") for v in recent]
    modes = [m for m in modes if m in ("topic", "choose", "request")][:CHOOSE_EVERY - 1]
    return len(modes) == CHOOSE_EVERY - 1 and "choose" not in modes


def _request() -> dict | None:
    """Your oldest waiting brief from the Themes page, if any."""
    waiting = db.list_topics("waiting", limit=10)
    return waiting[0] if waiting else None


def _instruction(mode: str, topic: str, direction: str) -> str:
    direction = direction.strip()
    if mode == "choose":
        return f"Choose a topic yourself. {direction}"
    return f"Write a story about {topic.upper()}. {direction}"


def _recent_directions(recent: list[dict]) -> list[str]:
    return [d for d in ((v["plan"].get("brief") or {}).get("direction") for v in recent[:12]) if d]


def write_direction(mode: str, pool: list[str], kind: str, recent: list[dict], progress=log) -> tuple[str, str]:
    """(topic, direction) for a brief: one Gemini call, its answer checked (a topic offered, a direction of the right
    length that isn't a recent one), at most TRIES times."""
    directions = _recent_directions(recent)
    stories = [summary(v) for v in recent[:8]]
    system = SYSTEM.format(examples="\n".join(f"- {e}" for e in EXAMPLES))
    complaints = []
    for attempt in range(TRIES):
        ask = (f"Today's brief: a topic brief. Choose one topic from these (a {kind}): {json.dumps(pool)}\n" if mode == "topic"
               else "Today's brief leaves the topic to the writer (a choose brief): leave the topic empty, and make the "
                    "direction say what kind of story you want, like the third example.\n")
        prompt = (ask
                  + f"Recent directions (never repeat one or its idea): {json.dumps(directions) if directions else 'none yet'}\n"
                  + f"Recent stories (ask for something they didn't have): {json.dumps(stories) if stories else 'none yet'}\n"
                  + f"What has worked so far: {advice(('theme',)) or 'not enough data yet'}\n"
                  + taught("theme")
                  + (f"Your last answer had these problems, fix them: {'; '.join(complaints)}\n" if complaints else "")
                  + "Write today's brief.")
        progress("Writing today's brief for the writer" + (f" (again: {len(complaints)} problems)" if complaints else ""))
        raw = llm.generate_json([prompt], SCHEMA, system)
        topic = next((t for t in pool if _plain(t) == _plain(raw.get("topic", ""))), None) if mode == "topic" else ""
        direction = " ".join(str(raw.get("direction") or "").split()).strip(" \"'")
        complaints = []
        if mode == "topic" and not topic:
            complaints.append(f"the topic must be one of {pool}")
        n = len(direction.split())
        if not DIRECTION_WORDS[0] <= n <= DIRECTION_WORDS[1]:
            complaints.append(f"the direction is one or two sentences, {DIRECTION_WORDS[0]}-{DIRECTION_WORDS[1]} words "
                              f"(now {n})")
        if re.match(r"(write a story|choose a topic)", direction, re.I):
            complaints.append("don't start the direction with \"Write a story\" or \"Choose a topic\": that's added")
        if mode == "choose":
            named = [t for t in series.themes()["vices"] + series.themes()["virtues"] + list(NAMED_TOPICS)
                     if t != "focus" and re.search(rf"\b{re.escape(_plain(t))}", _plain(direction))]  # ("focus on...")
            if named:
                complaints.append(f"in a choose brief the writer picks the topic: don't name it (you named "
                                  f"{', '.join(named[:3])}); say only what kind of story you want")
        close = [d for d in directions + EXAMPLES
                 if difflib.SequenceMatcher(None, _plain(direction),
                                            _plain(re.sub(r"^.*?\.\s*", "", d, count=1) if d in EXAMPLES else d)).ratio()
                 >= SAME_DIRECTION]
        if close:
            complaints.append(f"that direction is too close to an earlier one ({close[0][:80]}): ask for something new")
        if not complaints:
            return topic, direction
        progress("Brief rejected: " + "; ".join(complaints))
    raise RuntimeError(f"no usable brief after {TRIES} tries: " + "; ".join(complaints))


def pick(progress=log, avoid: list[str] | None = None, ready_now: bool = False, topic: str | None = None,
         choose: bool = False) -> dict:
    """The next story's brief (not saved: tools/jobs.py saves it with the story). `topic`/`choose`: a brief of that
    kind instead of the one due (the command line, tests)."""
    recent = recent_stories()
    request = None if (topic or choose) else _request()
    if request:
        text = " ".join(str(request["text"]).split())
        if len(text.split()) > 3:  # your brief, word for word
            found = next((t for t in series.themes()["vices"] + series.themes()["virtues"]
                          if re.search(rf"\b{re.escape(_plain(t))}\b", _plain(text))), "")
            brief = {"mode": "request", "instruction": text, "topic": found, "theme": found,
                     "kind": kind_of(found) if found else "", "direction": "", "why_now": "request",
                     "request_id": request["id"]}
            progress(f"Today's brief is yours: {text[:120]}")
            return {"brief": brief, "topic": found, "kind": brief["kind"], "why_now": "request"}
        topic = text  # (a word or two: the topic of a topic brief)
    if topic:
        mode, kind, pool = "topic", kind_of(topic), [topic]
    elif choose or choose_due(recent):
        mode, kind, pool = "choose", "", []
    else:
        mode = "topic"
        kind, pool = candidates(recent, avoid)
    chosen, direction = write_direction(mode, pool, kind or "vice", recent, progress)
    brief = {"mode": mode, "instruction": _instruction(mode, chosen, direction), "topic": chosen, "theme": chosen,
             "kind": kind, "direction": direction, "why_now": "request" if request else "rotation",
             "request_id": request["id"] if request else None}
    progress(f"Today's brief: {brief['instruction']}")
    return {"brief": brief, "topic": chosen, "kind": kind, "why_now": brief["why_now"]}


def run(progress=log, avoid: list[str] | None = None, ready_now: bool = False) -> dict:
    return act("theme", "Write today's brief", pick, progress=progress, avoid=avoid, ready_now=ready_now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--topic", help="a brief about this topic")
    parser.add_argument("--choose", action="store_true", help="a brief that leaves the topic to the writer")
    args = parser.parse_args()
    try:
        result = pick(topic=args.topic, choose=args.choose)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result["brief"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
