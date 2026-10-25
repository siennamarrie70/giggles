"""
Agent 1, Editor: decides the next case: its type, its topic and the one question it answers.

Code picks the type first, from cases.categories in config/channel.yaml (how often each, 0 = never),
weighed by what the playbook says does well (Agent 6), never the type of the last two cases, and
never "trending" while two cases already wait for your OK. The two best types go to Gemini with
today's signals: trending searches and popular Education videos (jobs.trend_signals), Wikipedia's
Current events of the last three days and its "On this day" list, holidays coming up, your topic
requests (always first), viewers' comments, cases that did well enough for a follow-up, and the
last 90 days' topics so none repeats. It writes a brief for the Researcher: the topic, the
question, why now, which Wikipedia articles, news searches, data and photos to look for, and
whether it touches politics.

Code checks the brief: its Wikipedia articles must exist (or a search must find some) and the topic
mustn't repeat a recent one. A failed brief gets two more tries, with the failed topics to avoid.
A case about this week's news or about politics is marked to wait for your OK (cases.approval).

Usage:
    python -m agents.editor          # writes the next brief and prints it (nothing is saved)
"""

import json
import random
import re
import sys

import db
import infographics
import llm
import research_fetch as rf
from agents.base import VARIETY, act, advice, log, playbook
from common import load_config

CATEGORIES = {
    "business": "a company's rise, fall or turnaround, or how a business really makes its money",
    "economy": "an economic what-if or explainer (tariffs, growth, inflation, debt, trade), with real data",
    "trending": "something in this week's news, explained as a case: what happened, why, and what it means",
    "history": "a historic event, decision or turning point: why it happened and what it changed",
    "mythology": "a myth or legend from any culture, told as a case: what happened and what it teaches",
}
WHY_NOW = ["trend", "anniversary", "evergreen", "request", "comment", "follow_up"]
RECENT_DAYS = 90
FOLLOW_UP_EVERY = 4  # at most one case in this many is a follow-up
TRIES = 3


def _schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": categories},
            "topic": {"type": "string", "description": "the case in a few words, e.g. 'the fall of Nokia's phone business'"},
            "angle": {"type": "string", "description": "the one question the Short answers, the way a viewer would ask it"},
            "why_now": {"type": "string", "enum": WHY_NOW},
            "trend": {"type": "string", "description": "the trend, news item, anniversary, request or comment it comes "
                                                       "from; empty if evergreen"},
            "request_declined": {"type": "string", "description": "only if the owner's request breaks the rules: why "
                                                                  "(then pick another case); else empty"},
            "comment_id": {"type": "string", "description": "the id of the viewer comment it answers; empty if none"},
            "follow_up_of": {"type": "integer", "description": "the id of the case it follows up; 0 if none"},
            "wiki_titles": {"type": "array", "items": {"type": "string"},
                            "description": "1 to 4 English Wikipedia article titles that cover it"},
            "search_terms": {"type": "array", "items": {"type": "string"}, "description": "1 to 3 short news searches"},
            "countries": {"type": "array", "items": {"type": "string"},
                          "description": "ISO 3166 alpha-3 codes of the countries involved (at most 4), for maps and data"},
            "data_needs": {"type": "array", "items": {"type": "string", "enum": list(rf.DATA)},
                           "description": "0 to 2 data series that would show the story (mostly for the economy)"},
            "image_subjects": {"type": "array", "items": {"type": "string"},
                               "description": "3 to 6 things to look for photos of on Wikimedia Commons: products, places, "
                                             "buildings, artworks, public figures"},
            "political": {"type": "boolean", "description": "does it touch politics, government policy or politicians?"},
            "living_people": {"type": "array", "items": {"type": "string"}, "description": "living people it names"},
        },
        "required": ["category", "topic", "angle", "why_now", "trend", "request_declined", "comment_id", "follow_up_of",
                     "wiki_titles", "search_terms", "countries", "data_needs", "image_subjects", "political",
                     "living_people"],
    }


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if w not in rf.STOPWORDS}


def repeats(topic: str, earlier: list[str]) -> str | None:
    """The earlier topic this one repeats (most of their words shared), if any."""
    mine = _words(topic)
    for other in earlier:
        theirs = _words(other)
        if mine and theirs and len(mine & theirs) / len(mine | theirs) >= 0.5:
            return other
    return None


def recent_cases(days: int = RECENT_DAYS) -> list[dict]:
    return [v for v in db.recent_videos(days=days) if v["format"] == db.FORMAT and v["plan"].get("brief")
            and v["status"] not in ("discarded", "skipped")]


def choose_types(cfg: dict, recent: list[dict], waiting: int) -> list[str]:
    """The two case types to offer Gemini: weighted by the settings and the playbook, without the last
    two cases' types (unless nothing else is on)."""
    weights = {c: float(w) for c, w in (cfg["cases"].get("categories") or {}).items() if c in CATEGORIES and float(w or 0) > 0}
    if not weights:
        weights = {c: 1.0 for c in CATEGORIES}
    book = playbook()
    lifts = (book["weights"].get("category") or {}) if book["samples"] and random.random() >= VARIETY else {}
    for c in weights:
        weights[c] *= min(2.0, max(0.5, lifts.get(c, 1.0)))
    if waiting >= 2:
        weights.pop("trending", None)
    last = [v["plan"]["brief"].get("category") for v in recent[:2]]
    fresh = {c: w for c, w in weights.items() if c not in last}
    pool = fresh or weights or {"business": 1.0}
    order = []
    while pool and len(order) < 2:
        pick = random.choices(list(pool), weights=list(pool.values()))[0]
        order.append(pick)
        pool.pop(pick)
    return order


def _signals(cfg: dict, category_choices: list[str]) -> dict:
    from jobs import trend_signals

    trends = trend_signals(cfg)
    out = {
        "today": f"{trends['weekday']} {trends['date']}",
        "trending_searches": [t["term"] for t in trends.get("google_trends", [])][:20],
        "popular_educational_videos": [v["title"] for v in trends.get("youtube_popular", [])][:10],
        "coming_up": [e["name"] for e in trends.get("events", [])],
    }
    try:
        out["in_the_news"] = [f"{e['section']}: {e['text'][:170]}" for e in rf.current_events(3)][:25]
    except Exception as e:
        log(f"Current events unavailable: {e}")
    if "history" in category_choices:
        try:
            out["on_this_day"] = [f"{e['year']}: {e['text'][:150]}" for e in rf.on_this_day()][:15]
        except Exception as e:
            log(f"On this day unavailable: {e}")
    return out


def validate(raw: dict, allowed: list[str], earlier: list[str], cfg: dict) -> dict:
    """The brief the Researcher can always use; raises ValueError if it can't be researched or repeats."""
    category = raw.get("category") if raw.get("category") in allowed else allowed[0]
    topic = " ".join(str(raw.get("topic", "")).split())[:90]
    angle = " ".join(str(raw.get("angle", "")).split())[:180]
    if not topic or not angle:
        raise ValueError("the brief has no topic or question")
    why_now = raw.get("why_now") if raw.get("why_now") in WHY_NOW else "evergreen"
    follow_up_of = int(raw.get("follow_up_of") or 0)
    if why_now != "follow_up" and (same := repeats(topic, earlier)):
        raise ValueError(f"'{topic}' repeats a recent case ('{same}')")
    titles = []
    for title in [str(t).strip() for t in raw.get("wiki_titles") or []][:4]:
        page = rf.wiki_page(title) if title else None
        if page and page["title"] not in titles:
            titles.append(page["title"])
    if not titles:
        titles = [hit["title"] for hit in rf.wiki_search(f"{topic} {angle}", 2)]
    if not titles:
        raise ValueError(f"no Wikipedia article covers '{topic}'")
    known = infographics.countries()
    countries = [c.upper() for c in raw.get("countries") or [] if str(c).upper() in known][:4]
    political = bool(raw.get("political"))
    approval = cfg["cases"].get("approval") or {}
    needs_approval = bool((category == "trending" and approval.get("trending", True))
                          or (political and approval.get("politics", True)))
    return {
        "category": category, "topic": topic, "angle": angle, "why_now": why_now,
        "trend": " ".join(str(raw.get("trend", "")).split())[:160],
        "wiki_titles": titles,
        "search_terms": [" ".join(str(t).split())[:60] for t in raw.get("search_terms") or [] if str(t).strip()][:3]
        or [topic],
        "countries": countries,
        "data_needs": [d for d in raw.get("data_needs") or [] if d in rf.DATA][:2] if countries else [],
        "image_subjects": [" ".join(str(s).split())[:60] for s in raw.get("image_subjects") or [] if str(s).strip()][:6]
        or [topic],
        "political": political, "needs_approval": needs_approval,
        "living_people": [" ".join(str(p).split())[:60] for p in raw.get("living_people") or []][:6],
        "comment_id": str(raw.get("comment_id") or "").strip() or None,
        "follow_up_of": follow_up_of or None,
    }


def pick(progress=log, avoid: list[str] | None = None, ready_now: bool = False) -> dict:
    """The next case's brief (not saved: jobs.prepare saves it with the script). ready_now: the case
    goes up without your OK (made on the spot for a slot), so no news and no politics."""
    from agents import analyst

    cfg = load_config()
    ch, cases = cfg["channel"], cfg["cases"]
    recent = recent_cases()
    waiting = sum(1 for v in db.planned_videos() if v["plan"].get("approval") == "waiting")
    requests = db.list_topics("waiting", limit=1)
    request = requests[0] if requests else None
    enabled = [c for c, w in (cases.get("categories") or {}).items() if c in CATEGORIES and float(w or 0) > 0] \
        or list(CATEGORIES)
    types = enabled if request else choose_types(cfg, recent, 2 if ready_now else waiting)
    if ready_now and len(types) > 1:
        types = [t for t in types if t != "trending"] or types
    comments = [{"id": c["comment_id"], "text": c["text"][:200], "likes": c["likes"] or 0}
                for c in db.recent_comments()] if cases.get("comment_requests", True) else []
    follow_ups = []
    if cases.get("follow_ups", True) and recent and not recent[0]["plan"]["brief"].get("follow_up_of") \
            and sum(1 for v in recent[:FOLLOW_UP_EVERY] if v["plan"]["brief"].get("follow_up_of")) == 0:
        follow_ups = analyst.follow_up_candidates()
    earlier = [v["plan"]["brief"]["topic"] for v in recent] + list(avoid or [])

    system = f"""You are the editor of {ch['name']}, a YouTube Shorts channel of 60-second case studies for
{ch['audience']}. Two cartoon hosts talk each case through.
The channel's voice: {ch['voice']}

Choose the next case: one clear question with a surprising, well-documented answer that people worldwide would want
answered in a minute. A good case has a story (a rise, a fall, a turning point, a twist) and plenty of public
sources: at least one English Wikipedia article, and recent reporting if it's news.
Rules, always:
- Real companies, people and events are fine, told neutrally as the sources tell them. No accusations of crimes or
  misconduct unless a court ruled or the person admitted it.
- Politics only as policy and economics, with both sides. Never elections, campaigns or voting.
- Never wars, attacks, disasters, crimes or deaths from the last 25 years. Older history is fine, without gore.
- Never health or medical advice, never investment advice or 'should you buy'.
- Nothing about children, nothing sexual, nothing that mocks a faith, a nation or a group.
- Myths and legends from any culture, told as stories, respectfully, never as fact.
- English, whatever language a trend is in.
- The channel owner's request comes first: make that case if it fits these rules; if it doesn't, say why in
  request_declined and choose another.
- A viewer's comment can suggest a case (set comment_id); a follow-up continues a case that did well (set
  follow_up_of) only when there's genuinely more story.
- Pick photos to look for that exist as free photos: products, places, buildings, old artworks, public figures."""
    blocked = []
    for attempt in range(TRIES):
        signals = _signals(cfg, types)
        prompt = (f"Case types you may use this time (choose the one with the best case today):\n"
                  + "\n".join(f"- {t}: {CATEGORIES[t]}" for t in types) + "\n\n"
                  f"Today's signals:\n{json.dumps(signals, ensure_ascii=False, indent=1)}\n\n"
                  f"The owner's request: {json.dumps(request['text']) if request else 'none'}\n"
                  f"Viewers' comments (id, text, likes): {json.dumps(comments, ensure_ascii=False) if comments else 'none'}\n"
                  f"Cases that did well (a follow-up is possible): {json.dumps(follow_ups, ensure_ascii=False) if follow_ups else 'none'}\n"
                  f"Recent cases (don't repeat their topics): {json.dumps(earlier[:60], ensure_ascii=False) if earlier else 'none yet'}\n"
                  + (f"Don't use these either (they couldn't be done): {json.dumps(blocked)}\n" if blocked else "")
                  + ("This case goes up without anyone checking it first: choose one that doesn't touch politics.\n"
                     if ready_now else "")
                  + f"What has worked so far: {advice(('category', 'why_now', 'hook')) or 'not enough data yet'}\n\n"
                  "Choose the next case and write its brief.")
        progress("Choosing the next case" + (f" ({', '.join(types)})" if len(types) <= 2 else ""))
        raw = llm.generate_json([prompt], _schema(types), system)
        if request and raw.get("request_declined"):
            reason = " ".join(str(raw["request_declined"]).split())[:300]
            db.set_topic(request["id"], "dropped", reason=reason)
            progress(f"Your request \"{request['text']}\" can't be made: {reason}")
            request = None
        try:
            brief = validate(raw, types, earlier + blocked, cfg)
        except ValueError as e:
            progress(f"Brief rejected: {e}")
            blocked.append(" ".join(str(raw.get("topic", "")).split())[:90])
            continue
        if request and not raw.get("request_declined"):
            brief["request_id"] = request["id"]
            brief["why_now"] = "request"
        if brief["comment_id"] and brief["comment_id"] not in {c["id"] for c in comments}:
            brief["comment_id"] = None
        if brief["follow_up_of"] and brief["follow_up_of"] not in {f["id"] for f in follow_ups}:
            brief["follow_up_of"] = None
        progress(f"Next case ({brief['category']}): {brief['angle']}"
                 + (" (waits for your OK)" if brief["needs_approval"] else ""))
        return {"brief": brief, "category": brief["category"], "topic": brief["topic"], "why_now": brief["why_now"],
                "needs_approval": brief["needs_approval"]}
    raise RuntimeError(f"no usable case after {TRIES} tries: " + "; ".join(blocked))


def run(progress=log, avoid: list[str] | None = None, ready_now: bool = False) -> dict:
    return act("editor", "Choose the next case", pick, progress=progress, avoid=avoid, ready_now=ready_now)


def main() -> int:
    try:
        result = pick()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result["brief"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
