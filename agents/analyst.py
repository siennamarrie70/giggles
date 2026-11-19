"""
Agent 6, Analyst: reads the numbers and writes the playbook the other agents follow, and what each of them should learn
from it.

Every day it pulls YouTube's numbers for each published film (views, likes and comments, plus the average % viewed and
subscribers gained from YouTube Analytics, which lags about two days) and marks films deleted in YouTube Studio as vetoed.
Once a week (or when asked), with at least MIN_SAMPLES films that are two days old or more, it works out what does better
than usual. Long films live by watch time, so each film's score is its views times the share watched (watch time), set
against the channel's median, grouped by theme, vice or virtue, the title's shape, the story's motif, length, the
narrator's voice (or none: the films are told in bubbles since 2026-11-19), whether the Reviewer passed it at first look,
and posting hour. A group needs MIN_SAMPLES films before
it counts. Gemini then writes a few plain lessons from the same table, and lessons for each agent (LEARNERS), with the
Reviewer's recurring problems beside them; it sees public counts only, never the private analytics (the privacy page
promises that).

Agent 1 reads the theme and title weights, Agent 2 the theme, opening and motif ones, each leaving them out a quarter of
the time (agents/base.py) so early noise doesn't lock the channel in; every agent reads its own lessons every time
(agents/base.py lessons_for), and the Publisher drops hashtags that clearly do worse.

Usage:
    python -m agents.analyst [--learn]      # pull today's numbers; --learn also rewrites the playbook
"""

import argparse
import json
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

import db
import llm
import notify
import slots
import stats_pull
from agents.base import act, log, playbook
from common import load_config

MIN_SAMPLES = 5
MIN_AGE = timedelta(days=2)
LEARN_EVERY = timedelta(days=7)
LEARNERS = {  # each agent, and what its lessons may be about
    "theme": "which themes (vices or virtues) and which kinds of title to choose",
    "story": "how the stories open, their parts and pace, the moments and their bubbles, the places and lights, the "
             "closing line",
    "animator": "the film's look, the camera, how long the bubbles stay, the music and the sounds",
    "reviewer": "what to be stricter or more relaxed about when checking a film",
    "publisher": "posting: the hour, titles and descriptions as they appear, hashtags, the short version",
}
LESSONS_SCHEMA = {
    "type": "object",
    "properties": {
        "lessons": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "for_agents": {"type": "object", "properties": {k: {"type": "array", "items": {"type": "string"}}
                                                        for k in LEARNERS},
                       "required": list(LEARNERS)},
    },
    "required": ["lessons", "summary", "for_agents"],
}


def _minutes(seconds: float | None) -> str:
    if not seconds:
        return "unknown"
    return "under 3 min" if seconds < 180 else "3-3.5 min" if seconds < 210 else "3.5-4 min" if seconds < 240 else "4 min+"


def title_pattern(title: str) -> str:
    """The shape of a story's title: "X is Y.", "X Built Him.", "The Price of X." and so on."""
    words = re.sub(r"[^a-z ]", "", str(title).lower()).split()
    if len(words) >= 3 and words[1] in ("is", "was", "are"):
        return "X is Y"
    if words[:1] == ["the"]:
        return "The ... of X" if "of" in words else "The X"
    if any(w in ("him", "his", "he") for w in words):
        return "X did it to him"
    return f"{min(len(words), 6)} words"


def traits(video: dict, sched: dict) -> dict[str, list[str]]:
    """What a story was made of, in groups the playbook compares."""
    plan = video["plan"]
    brief = plan.get("brief") or {}
    at = video["slot"] or video["publish_at"]
    review = plan.get("review") or {}
    return {
        "theme": [brief.get("theme") or "unknown"], "kind": [brief.get("kind") or "unknown"],
        "title_pattern": [title_pattern((plan.get("metadata") or {}).get("title") or "")],
        "motif": [(plan.get("story") or {}).get("motif") or "none"],
        "length": [_minutes((plan.get("render") or {}).get("seconds"))],
        "voice": [SILENT if (plan.get("render") or {}).get("silent")
                  else (plan.get("voice") or {}).get("voice", "unknown").split(" (")[0]],
        "hashtag": sorted({t.lower() for t in (plan.get("metadata") or {}).get("hashtags") or []}),
        "review": ["passed at first look" if not review.get("history") else "fixed by the Animator"] if review else [],
        "hour": [slots.clock(slots.parse(at), sched)] if at else [],
    }


# The parts of a story its traits are read from (db.LIGHT: not the screenplay or the render's shots).
TRAIT_PARTS = ("brief", "metadata", "voice", "render.seconds", "render.silent", "review", "story.motif")
SILENT = "none: told in bubbles"   # a silent film's "voice" (since 2026-11-19)


def rows(min_age: timedelta = MIN_AGE, with_traits: bool = True) -> list[dict]:
    """Published films old enough to judge, with their latest numbers, their watch-time score and (with_traits) their
    traits."""
    sched = slots.plan()
    cutoff = datetime.now(timezone.utc) - min_age
    published = [v for v in db.published_videos(days=90, parts=TRAIT_PARTS if with_traits else ("metadata.title",))
                 if v["format"] == db.fmt() and slots.parse(v["publish_at"]) <= cutoff]
    numbers = db.latest_stats([v["youtube_id"] for v in published])
    out = []
    for v in published:
        n = numbers.get(v["youtube_id"])
        if not n:
            continue
        out.append({"id": v["id"], "title": v["plan"].get("metadata", {}).get("title") or v["theme"],
                    "publish_at": v["publish_at"], "youtube_id": v["youtube_id"],
                    "views": n["views"] or 0, "likes": n["likes"] or 0, "comments": n["comments"] or 0,
                    "avg_view_pct": n["avg_view_pct"], "subs_gained": n["subs_gained"],
                    "traits": traits(v, sched) if with_traits else {}})
    pcts = [r["avg_view_pct"] for r in out if r["avg_view_pct"]]
    usual = statistics.median(pcts) if pcts else 50.0
    for r in out:  # long films are judged by how much is watched: views times the share watched (watch time)
        r["score"] = round(r["views"] * float(r["avg_view_pct"] or usual) / 100, 1)
    return out


def lifts(table: list[dict]) -> dict[str, dict[str, float]]:
    """For each group with enough films: its median watch-time score over the channel's median."""
    if len(table) < MIN_SAMPLES:
        return {}
    overall = statistics.median(r["score"] for r in table) or 1
    groups: dict[str, dict[str, list[float]]] = {}
    for r in table:
        for kind, values in r["traits"].items():
            for value in values:
                groups.setdefault(kind, {}).setdefault(value, []).append(r["score"])
    return {kind: {value: round(statistics.median(scores) / overall, 2)
                   for value, scores in by_value.items() if len(scores) >= MIN_SAMPLES}
            for kind, by_value in groups.items()}


def pull(progress=log) -> dict:
    """Today's numbers for every film published in the last 60 days (their short versions aren't counted)."""
    published = db.published_videos(days=60, parts=())
    if not published:
        return {"skipped": "no published films yet"}
    progress(f"Fetching numbers for {len(published)} published films")
    result = stats_pull.run([v["youtube_id"] for v in published])
    found = {s["youtube_id"] for s in result["videos"]}
    vetoed = [v for v in published if v["youtube_id"] not in found]  # deleted in YouTube Studio
    for v in vetoed:
        db.update_video(v["id"], status="vetoed")
    db.save_stats(result["videos"], datetime.now(timezone.utc).date().isoformat())
    return {"updated": len(result["videos"]), "vetoed": len(vetoed), "analytics_error": result["analytics_error"]}


def learn(progress=log) -> dict:
    """Rewrites the playbook from the films old enough to judge."""
    table = rows()
    if len(table) < MIN_SAMPLES:
        return {"skipped": f"the playbook needs {MIN_SAMPLES} films that are 2 days old; there are {len(table)}"}
    weights = lifts(table)
    name = load_config()["channel"]["name"]
    # Only public counts go to Gemini (free-tier prompts may be used by Google): private analytics such
    # as average % viewed stay in the database and the dashboard (see /privacy).
    public = [{"title": r["title"], **{k: v for k, v in r["traits"].items()},
               "views": r["views"], "likes": r["likes"], "comments": r["comments"]} for r in table]
    system = f"""You analyse results for {name}, a YouTube channel of 3-4 minute motivational short films, one a day,
each with a short version of under a minute (a YouTube Short and an Instagram Reel). Each film is an animated story
drawn in one look (black silhouettes with a thin red rim of
light and two white eyes, film light, letterbox bars) about an ordinary man whose habit ruins his life, until something
wakes him, he works on himself, reaches the life he wanted and calmly turns down what once turned him down. Since
2026-11-19 there's no narrator: the people talk and think in speech and thought bubbles (earlier films had a calm, warm
narrator: their "voice" is his name; a silent film's is "none: told in bubbles"). Six agents make each film: Theme picks
the day's vice or virtue and names it, Story writes the screenplay and its moments with their bubbles, an Animator draws
the film, a Reviewer checks it, a Publisher posts it, and you read the results. Long films live by watch time, so lessons about holding viewers matter most.
Give 3-6 concrete, testable lessons about which themes, titles, openings, motifs, lengths and posting times do better or
worse. Then, for each agent, 0-3 short lessons it can act on next time, only about its own work:
""" + "\n".join(f"- {k}: {v}" for k, v in LEARNERS.items()) + """
Each lesson one sentence, specific ('Titles that name the habit beat titles that name the man: early signal'), never
vague advice. Small samples are noisy: say 'early signal' when the evidence is thin, and give none rather than guess.
Summary: 2-3 plain sentences for the channel owner."""
    reviews = (db.latest_note("review:lessons") or {}).get("counts") or {}
    progress("Writing this week's lessons")
    written = llm.generate_json(["Recent films with their public numbers:\n" + json.dumps(public, ensure_ascii=False, indent=1)
                                 + "\n\nProblems the Reviewer found most often at first look (kind: count): "
                                 + (json.dumps(reviews) if reviews else "none yet")],
                                LESSONS_SCHEMA, system)
    given = written.get("for_agents") or {}
    book = {"weights": weights, "lessons": [" ".join(str(l).split())[:240] for l in written.get("lessons", [])][:6],
            "lessons_for": {k: [" ".join(str(l).split())[:240] for l in given.get(k) or [] if str(l).strip()][:3]
                            for k in LEARNERS},
            "summary": " ".join(str(written.get("summary", "")).split())[:600], "samples": len(table),
            "updated_at": db.now_iso()}
    db.keep_note("playbook", book)
    notify.run("\U0001F4CA Weekly check-in: " + book["summary"] + "\n- " + "\n- ".join(book["lessons"]))
    return {"samples": len(table), "lessons": book["lessons"]}


def daily(progress=log, learn_now: bool = False) -> dict:
    result = pull(progress)
    updated = playbook().get("updated_at")
    stale = not updated or datetime.now(timezone.utc) - slots.parse(updated) >= LEARN_EVERY
    if learn_now or stale:
        result["learn"] = learn(progress)
    return result


def run(progress=log, learn_now: bool = False) -> dict:
    return act("analyst", "Read the numbers", daily, progress=progress, learn_now=learn_now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--learn", action="store_true", help="rewrite the playbook now")
    args = parser.parse_args()
    try:
        result = run(learn_now=args.learn)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
