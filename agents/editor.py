"""
Agent 1, Editor: decides the next case: its type, its topic, the paradox it opens on and the one
question it answers. Every case is told as a mystery by the Professor, the channel's one host.

Code picks the type first, from cases.categories in config/channel.yaml (how often each, 0 = never),
weighed by what the playbook says does well (Agent 7), never the type of the last two cases, and
never "trending" while two cases already wait for your OK. The two best types go to Gemini with
today's signals: trending searches and popular Education videos (jobs.trend_signals), Wikipedia's
Current events of the last three days and its "On this day" list, holidays coming up, your topic
requests (always first), viewers' comments, cases that did well enough for a follow-up, and the
last 90 days' topics so none repeats. It writes a brief for the Researcher: the topic, the
paradox and the question, why now, which Wikipedia articles, news searches, data and photos to look
for, the stock video that would set the scene (b-roll), archive film of the real thing for older
history, old products and space, and whether it touches politics.

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
from agents.base import VARIETY, act, advice, log, playbook, taught
from common import load_config

CATEGORIES = {  # the user's list of 2026-10-26, plus the economy and plain history
    "dark_history": "dark history and untold historical events: forgotten empires, historical betrayals, lost "
                    "civilizations, strange historical events, rulers who lost everything",
    "mysteries": "mysteries and unexplained cases: strange disappearances, unsolved historical mysteries, puzzling "
                 "discoveries, unexplained incidents (what is known, what isn't, and the leading explanations)",
    "business": "business case studies and corporate failures: how companies became giants, why famous brands "
                "collapsed, the founders' crucial decisions, how business scandals unfolded",
    "technology": "AI, technology and breakthroughs: important AI developments, famous inventions, technology "
                  "rivalries, how an emerging technology works",
    "trending": "trending news explained: this week's major story (world events, the economy, technology, political "
                "decisions) and why people are talking about it",
    "psychology": "human psychology and unusual behavior: why people make irrational decisions, how persuasion works, "
                  "herd behavior, famous experiments (what research found, never health advice)",
    "mythology": "mythology, legends and ancient civilizations: Indian epics, Greek myths, legendary warriors, "
                 "folklore, the origins of ancient traditions, told as stories",
    "people": "famous people's rise, fall and comeback: entrepreneurs, inventors, leaders and athletes, the decisions "
              "and setbacks that shaped them",
    "science": "science, space and mind-blowing discoveries: black holes, space missions, breakthroughs, strange "
               "natural phenomena, big questions about the universe",
    "crime": "famous criminal cases and investigations: historical frauds, heists and courtroom cases, and how "
             "investigators found the evidence",
    "history": "a historic event, decision or turning point: why it happened and what it changed",
    "economy": "an economic what-if or explainer (tariffs, growth, inflation, debt, trade), with real data",
}
ON_THIS_DAY_FOR = {"history", "dark_history", "people", "crime", "mysteries", "science"}  # anniversaries help these
WHY_NOW = ["trend", "anniversary", "evergreen", "request", "comment", "follow_up"]
ARCHIVE_SOURCES = ["none", "film", "nasa"]
RECENT_DAYS = 90
FOLLOW_UP_EVERY = 4  # at most one case in this many is a follow-up
TRIES = 3


def _schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": categories},
            "topic": {"type": "string", "description": "the case in a few words, e.g. 'the fall of Nokia's phone business'"},
            "paradox": {"type": "string", "description": "the true, surprising fact or contradiction the case opens on, "
                                                         "at most 20 words, e.g. 'In 2000 Nokia sold almost every second "
                                                         "phone on Earth; by 2013 it sold its phone business.'"},
            "angle": {"type": "string", "description": "the mystery: the one question the paradox raises, the way a viewer "
                                                       "would ask it, with an answer that isn't obvious"},
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
            "broll": {"type": "array", "items": {"type": "string"},
                      "description": "5 to 8 searches for stock video that sets the scene: concrete things a camera can film, "
                                     "1 to 4 words each ('old mobile phone', 'stock market screen', 'Helsinki harbour', "
                                     "'office meeting at night'); never brand names or real people"},
            "archive": {"type": "array", "items": {"type": "string"},
                        "description": "0 to 3 searches for public-domain archive film of the real thing (old films, "
                                       "newsreels, adverts before about 1975; NASA footage for space), 1 to 3 words each "
                                       "('aircraft carrier', 'Tupperware', 'Apollo launch'); empty if none would exist"},
            "archive_source": {"type": "string", "enum": ARCHIVE_SOURCES,
                               "description": "film (old films and newsreels), nasa (space), or none"},
            "political": {"type": "boolean", "description": "does it touch politics, government policy or politicians?"},
            "living_people": {"type": "array", "items": {"type": "string"}, "description": "living people it names"},
        },
        "required": ["category", "topic", "paradox", "angle", "why_now", "trend", "request_declined", "comment_id",
                     "follow_up_of", "wiki_titles", "search_terms", "countries", "data_needs", "image_subjects", "broll",
                     "archive", "archive_source", "political", "living_people"],
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


def discarded_topics(days: int = RECENT_DAYS) -> list[str]:
    """The topics of the cases you discarded lately: not chosen again unless you ask for them (Nokia came back a
    third time after two discards, 2026-10-26)."""
    return [(v["plan"].get("brief") or {}).get("topic") for v in db.recent_videos(days=days)
            if v["status"] == "discarded" and (v["plan"].get("brief") or {}).get("topic")]


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
    if ON_THIS_DAY_FOR & set(category_choices):
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
    phrases = lambda items, n, chars: [" ".join(str(s).split())[:chars] for s in items or [] if str(s).strip()][:n]  # noqa: E731
    archive_source = raw.get("archive_source") if raw.get("archive_source") in ARCHIVE_SOURCES else "none"
    archive = phrases(raw.get("archive"), 3, 40) if archive_source != "none" else []
    return {
        "category": category, "topic": topic, "angle": angle, "why_now": why_now,
        "paradox": " ".join(str(raw.get("paradox", "")).split())[:200],
        "broll": phrases(raw.get("broll"), 8, 40) or [topic],
        "archive": archive, "archive_source": archive_source if archive else "none",
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
    """The next case's brief (not saved: jobs.prepare saves it with the script). ready_now: the case is made on
    the spot for a slot, so it can't wait for your OK: while news or politics need your OK (cases.approval), it
    steers clear of them. With approvals off (the Publisher approves cases itself) any type goes."""
    from agents import analyst

    cfg = load_config()
    ch, cases = cfg["channel"], cfg["cases"]
    recent = recent_cases()
    waiting = sum(1 for v in db.planned_videos() if v["plan"].get("approval") == "waiting")
    requests = db.list_topics("waiting", limit=1)
    request = requests[0] if requests else None
    enabled = [c for c, w in (cases.get("categories") or {}).items() if c in CATEGORIES and float(w or 0) > 0] \
        or list(CATEGORIES)
    approval = cases.get("approval") or {}
    types = enabled if request else choose_types(cfg, recent, 2 if ready_now and approval.get("trending", True) else waiting)
    if ready_now and approval.get("trending", True) and len(types) > 1:
        types = [t for t in types if t != "trending"] or types
    comments = [{"id": c["comment_id"], "text": c["text"][:200], "likes": c["likes"] or 0}
                for c in db.recent_comments()] if cases.get("comment_requests", True) else []
    follow_ups = []
    if cases.get("follow_ups", True) and recent and not recent[0]["plan"]["brief"].get("follow_up_of") \
            and sum(1 for v in recent[:FOLLOW_UP_EVERY] if v["plan"]["brief"].get("follow_up_of")) == 0:
        follow_ups = analyst.follow_up_candidates()
    earlier = [v["plan"]["brief"]["topic"] for v in recent] + list(avoid or []) + ([] if request else discarded_topics())

    system = f"""You are the editor of {ch['name']}, a YouTube Shorts channel of case studies a minute or so long for
{ch['audience']}. One host, the Professor, tells every case as a mystery.
The channel's voice: {ch['voice']}

Choose the next case: a mystery people worldwide would want solved in a minute. It opens on a paradox, a true and
surprising fact or contradiction ('the biggest phone maker on Earth sold its phone business'), which raises one
question whose answer isn't obvious and is well documented. A good case has real people making decisions, turning
points and a twist, and plenty of public sources: at least one English Wikipedia article, and recent reporting if
it's news. The video is real footage: stock video that sets the scene (b-roll: filmable things, never brand names or
real people, since stock clips can't show the real company), real photos, maps and charts, and archive film of the
real thing for older history, old products and adverts, and space.
Rules, always:
- Real companies, people and events are fine, told neutrally as the sources tell them. No accusations of crimes or
  misconduct unless a court ruled or the person admitted it.
- Politics only as policy and economics, with both sides. Never elections, campaigns or voting.
- Never wars, attacks, disasters, crimes or deaths from the last 25 years. Older history is fine, without gore.
- Never health or medical advice, never investment advice or 'should you buy'.
- Nothing about children, nothing sexual, nothing that mocks a faith, a nation or a group.
- Myths and legends from any culture, told as stories, respectfully, never as fact.
- Criminal cases only when settled (a court ruled, or the person admitted it) and more than 25 years old: frauds,
  heists and investigations rather than violence, victims treated with respect, proven facts kept apart from
  allegations. Unsolved mysteries: what is known and what isn't, the leading explanations named as explanations,
  never speculation as fact. Psychology: what research found, never health advice or diagnoses.
- English, whatever language a trend is in.
- The channel owner's request comes first: make that case if it fits these rules; if it doesn't, say why in
  request_declined and choose another.
- A viewer's comment can suggest a case (set comment_id); a follow-up continues a case that did well (set
  follow_up_of) only when there's genuinely more story.
- Pick photos to look for that exist as free photos: products, places, buildings, old artworks, public figures."""
    blocked = []
    for attempt in range(TRIES):
        signals = _signals(cfg, types)
        prompt = ("Case types you may use this time (choose the one with the best case today):\n"
                  + "\n".join(f"- {t}: {CATEGORIES[t]}" for t in types) + "\n\n"
                  f"Today's signals:\n{json.dumps(signals, ensure_ascii=False, indent=1)}\n\n"
                  f"The owner's request: {json.dumps(request['text']) if request else 'none'}\n"
                  f"Viewers' comments (id, text, likes): {json.dumps(comments, ensure_ascii=False) if comments else 'none'}\n"
                  f"Cases that did well (a follow-up is possible): {json.dumps(follow_ups, ensure_ascii=False) if follow_ups else 'none'}\n"
                  f"Recent cases (don't repeat their topics): {json.dumps(earlier[:60], ensure_ascii=False) if earlier else 'none yet'}\n"
                  + (f"Don't use these either (they couldn't be done): {json.dumps(blocked)}\n" if blocked else "")
                  + ("This case goes up without anyone checking it first: choose one that doesn't touch politics.\n"
                     if ready_now and approval.get("politics", True) else "")
                  + f"What has worked so far: {advice(('category', 'why_now', 'hook')) or 'not enough data yet'}\n"
                  + taught("editor") + "\nChoose the next case and write its brief.")
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
