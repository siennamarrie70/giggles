"""
Agent 5, Analyst: reads the numbers and writes the playbook the other agents follow.

Every day it pulls YouTube's numbers for each published Short (views, likes and comments, plus the
average % viewed and subscribers gained from YouTube Analytics, which lags about two days) and marks
Shorts deleted in YouTube Studio as vetoed. Once a week (or when asked), with at least MIN_SAMPLES
Shorts that are two days old or more, it works out what does better than usual: each Short's views
against the channel's median, grouped by setting, character role, voice and outfit, sketch length,
number of lines, whether it used a trend, and posting hour. A group needs MIN_SAMPLES Shorts before it
counts. Gemini then writes a few plain lessons from the same table; it sees public counts only, never
the private analytics (the privacy page promises that).

Casting reads the setting/role/voice/outfit weights, the Writer the length/lines/trend ones, each
leaving them out a quarter of the time (agents/base.py) so early noise doesn't lock the channel in.

Usage:
    python -m agents.analyst [--learn]      # pull today's numbers; --learn also rewrites the playbook
"""

import argparse
import json
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

LESSONS_SCHEMA = {
    "type": "object",
    "properties": {
        "lessons": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["lessons", "summary"],
}


def _length(seconds: float | None) -> str:
    if not seconds:
        return "unknown"
    return "under 20 s" if seconds < 20 else "20-30 s" if seconds < 30 else "30-40 s" if seconds < 40 else "40 s+"


def traits(video: dict, sched: dict) -> dict[str, list[str]]:
    """What a Short was made of, in groups the playbook compares."""
    plan = video["plan"]
    cast = plan.get("cast") or []
    script = plan.get("script") or {}
    at = video["slot"] or video["publish_at"]
    return {
        "setting": [plan.get("setting") or "unknown"],
        "role": sorted({c["role"].lower() for c in cast}),
        "voice": sorted({c["voice"] for c in cast}),
        "outfit": sorted({c["outfit"] for c in cast}),
        "length": [_length((plan.get("render") or {}).get("seconds"))],
        "beats": [f"{len(script.get('beats') or [])} lines"],
        "trend": ["trend" if script.get("trend_used") else "evergreen"],
        "hour": [slots.clock(slots.parse(at), sched)] if at else [],
    }


def rows(min_age: timedelta = MIN_AGE) -> list[dict]:
    """Published Shorts old enough to judge, with their latest numbers and traits."""
    sched = slots.plan()
    cutoff = datetime.now(timezone.utc) - min_age
    published = [v for v in db.published_videos(days=90)
                 if v["format"] == "sketch" and slots.parse(v["publish_at"]) <= cutoff]  # cartoons only
    numbers = db.latest_stats([v["youtube_id"] for v in published])
    out = []
    for v in published:
        n = numbers.get(v["youtube_id"])
        if not n:
            continue
        out.append({"id": v["id"], "title": v["plan"].get("metadata", {}).get("title") or v["theme"],
                    "publish_at": v["publish_at"], "youtube_id": v["youtube_id"],
                    "views": n["views"] or 0, "likes": n["likes"] or 0, "comments": n["comments"] or 0,
                    "avg_view_pct": n["avg_view_pct"], "subs_gained": n["subs_gained"], "traits": traits(v, sched)})
    return out


def lifts(table: list[dict]) -> dict[str, dict[str, float]]:
    """For each group with enough Shorts: its median views over the channel's median."""
    if len(table) < MIN_SAMPLES:
        return {}
    overall = statistics.median(r["views"] for r in table) or 1
    groups: dict[str, dict[str, list[int]]] = {}
    for r in table:
        for kind, values in r["traits"].items():
            for value in values:
                groups.setdefault(kind, {}).setdefault(value, []).append(r["views"])
    return {kind: {value: round(statistics.median(views) / overall, 2)
                   for value, views in by_value.items() if len(views) >= MIN_SAMPLES}
            for kind, by_value in groups.items()}


def pull(progress=log) -> dict:
    """Today's numbers for every Short published in the last 60 days."""
    published = db.published_videos(days=60)
    if not published:
        return {"skipped": "no published Shorts yet"}
    progress(f"Fetching numbers for {len(published)} published Shorts")
    result = stats_pull.run([v["youtube_id"] for v in published])
    found = {s["youtube_id"] for s in result["videos"]}
    vetoed = [v for v in published if v["youtube_id"] not in found]  # deleted in YouTube Studio
    for v in vetoed:
        db.update_video(v["id"], status="vetoed")
    db.save_stats(result["videos"], datetime.now(timezone.utc).date().isoformat())
    return {"updated": len(result["videos"]), "vetoed": len(vetoed), "analytics_error": result["analytics_error"]}


def learn(progress=log) -> dict:
    """Rewrites the playbook from the Shorts old enough to judge."""
    table = rows()
    if len(table) < MIN_SAMPLES:
        return {"skipped": f"the playbook needs {MIN_SAMPLES} Shorts that are 2 days old; there are {len(table)}"}
    weights = lifts(table)
    cfg = load_config()
    # Only public counts go to Gemini (free-tier prompts may be used by Google): private analytics such
    # as average % viewed stay in the database and the dashboard (see /privacy).
    public = [{"title": r["title"], **{k: v for k, v in r["traits"].items()},
               "views": r["views"], "likes": r["likes"], "comments": r["comments"]} for r in table]
    system = f"""You analyse results for {cfg['channel']['name']}, a YouTube Shorts channel of animated comedy sketches.
Give 3-6 concrete, testable lessons about which settings, kinds of characters, voices, lengths and hooks do better or
worse. Small samples are noisy: say 'early signal' when the evidence is thin.
Summary: 2-3 plain sentences for the channel owner."""
    progress("Writing this week's lessons")
    written = llm.generate_json(["Recent Shorts with their public numbers:\n" + json.dumps(public, ensure_ascii=False, indent=1)],
                                LESSONS_SCHEMA, system)
    book = {"weights": weights, "lessons": [" ".join(str(l).split())[:240] for l in written.get("lessons", [])][:6],
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
