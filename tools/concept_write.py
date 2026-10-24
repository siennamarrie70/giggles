"""
The creative step: plans each Short, writes its text, and turns it into an edit.

  plan_concept()    trend signals + format -> theme, joke angle, stock search queries
  write_metadata()  concept + what the chosen clips show -> on-screen text, title,
                    description, hashtags (cleaned and length-checked in code)
  build_edit()      metadata + clips -> timed segments and caption overlays for short_render.py
  write_learnings() recent performance -> a few lessons fed back into plan_concept()

Usage:
    python tools/concept_write.py concept --trends .tmp/trends.json --format punchline [--out .tmp/concept.json]
    python tools/concept_write.py metadata --concept .tmp/concept.json --clips .tmp/checked.json [--out .tmp/plan.json]
"""

import argparse
import json
import re
import sys

import llm
from common import load_config, tmp_path

FORMATS = {
    "punchline": {"clips": 1, "seconds": (6.0, 14.0),
                  "brief": "One clip. A hook line on top sets up a relatable situation; "
                           "a punchline appears halfway through and lands the joke."},
    "pov": {"clips": 1, "seconds": (6.0, 14.0),
            "brief": "One clip. A single 'POV: ...' caption on top frames the clip as a relatable moment."},
    "top3": {"clips": 3, "seconds": (4.0, 7.0),
             "brief": "Three short clips counting down 3-2-1 on one theme, e.g. '3 pets who refuse to Monday'. "
                      "A hook on top and a short numbered caption for each clip."},
}
FORMAT_TEXT_RULES = {
    "punchline": "hook: sets up the situation (max 8 words). punchline: lands the joke (max 8 words). captions: [].",
    "pov": "hook: one line starting with 'POV:' (max 12 words). punchline: ''. captions: [].",
    "top3": "hook: names the countdown, e.g. '3 cats who refuse to Monday' (max 8 words). punchline: ''. "
            "captions: exactly 3 lines (max 6 words each), one per clip in the order shown; the first clip "
            "shown is #3 and the last is #1. Don't include the numbers.",
}
TEXT_LIMITS = {"hook": 70, "punchline": 55, "caption": 40}
EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")
HASHTAG_WORD = re.compile(r"#\w+")

CONCEPT_SCHEMA = {
    "type": "object",
    "properties": {
        "theme": {"type": "string", "description": "the idea in a few words, e.g. 'cats vs Monday mornings'"},
        "angle": {"type": "string", "description": "one sentence: the joke or feeling the Short delivers"},
        "trend_used": {"type": "string", "description": "the event, trend or vibe this plays on; empty if evergreen"},
        "animal": {"type": "string", "description": "main animal to search for, e.g. 'kitten'"},
        "search_queries": {"type": "array", "items": {"type": "string"},
                           "description": "2-4 stock video searches, 2-4 words each"},
    },
    "required": ["theme", "angle", "trend_used", "animal", "search_queries"],
}
META_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "punchline": {"type": "string"},
        "captions": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "punchline", "captions", "title", "description", "hashtags", "tags"],
}
LEARNINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "learnings": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["learnings", "summary"],
}


def _channel_brief(cfg: dict) -> str:
    ch = cfg["channel"]
    return f"Channel: {ch['name']}, cute and funny animal Shorts for {ch['audience']}.\nVoice: {ch['voice']}"


def _where(items: list[dict], text_key: str) -> list[str]:
    """Trend texts with where they trend, when they come from several countries: 'Halloween (14 countries)'."""
    out = []
    for item in items:
        countries = item.get("countries") or []
        where = f" ({len(countries)} countries)" if len(countries) > 1 else f" ({countries[0]})" if countries else ""
        out.append(item[text_key] + where)
    return out


def plan_concept(trends: dict, fmt: str, recent_themes: list[str], learnings: list[str] | None, cfg: dict) -> dict:
    system = f"""You plan one YouTube Short at a time. {_channel_brief(cfg)}
Footage comes from free stock video sites, so search queries must describe simple, common, filmable animal
moments (e.g. 'kitten yawning', 'puppy running snow', 'cat looking out window'): 2-4 words, animals only, no people.
Animals that work well: {', '.join(cfg['content']['animals'])}.
The 'animal' must be easy to find in stock footage. For top3 (three different clips) use a plain common
animal such as 'cat', 'dog' or 'kitten', with no colour or breed, or there won't be three matching clips.
Use a trend only if it fits cute animals naturally: holidays, pet days, seasons, weather, weekday moods.
Never use news, politics, disasters, crime, celebrities, sports teams, brands or anything sad.
Trends may come from many countries, with how many they trend in: the audience is worldwide, so prefer
the widespread ones. Whatever the trend's language, write everything in English.
If nothing fits, pick an evergreen everyday theme. Don't repeat recent themes."""
    signals = {
        "today": f"{trends['weekday']} {trends['date']}",
        "upcoming_events": trends.get("events", []),
        "season": trends.get("season"),
        "weekday_vibe": trends.get("weekday_vibe"),
        "google_trending_searches": _where(trends.get("google_trends", []), "term")[:20],
        "popular_youtube_animal_videos": _where(trends.get("youtube_popular", []), "title")[:15],
    }
    prompt = (f"Format: {fmt}. {FORMATS[fmt]['brief']}\n\n"
              f"Today's signals:\n{json.dumps(signals, ensure_ascii=False, indent=1)}\n\n"
              f"Recent themes to avoid: {recent_themes or 'none yet'}\n"
              f"Lessons from past results: {learnings or 'none yet'}\n\nPlan the Short.")
    concept = llm.generate_json([prompt], CONCEPT_SCHEMA, system)
    queries = [q.strip() for q in concept["search_queries"] if q.strip()][:4]
    concept["search_queries"] = queries or [f"cute {concept['animal']}"]
    concept["format"] = fmt
    return concept


def _screen_text(text: str, limit: int) -> str:
    """On-screen text: no emoji (the font can't draw them), no hashtags, cut at a word boundary."""
    text = " ".join(EMOJI.sub("", HASHTAG_WORD.sub("", text or "")).split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return text


def _no_brackets(text: str) -> str:
    """YouTube rejects < and > in titles and descriptions; keep the heart in "<3"."""
    return text.replace("<3", "❤").replace("<", "").replace(">", "")


def _hashtag(tag: str) -> str | None:
    tag = re.sub(r"[^0-9a-z_]", "", tag.lower().lstrip("#"))
    return f"#{tag}" if tag else None


def _credits(clips: list[dict]) -> str:
    sites = {"pexels": "Pexels", "pixabay": "Pixabay"}
    return "\n".join(f"Video: {c['credit_name']} on {sites.get(c['source'], c['source'])} - {c['page_url']}" for c in clips)


def _clean_metadata(raw: dict, fmt: str, concept: dict, clips: list[dict], cfg: dict) -> dict:
    meta = {
        "hook": _screen_text(raw["hook"], TEXT_LIMITS["hook"]),
        "punchline": _screen_text(raw["punchline"], TEXT_LIMITS["punchline"]) if fmt == "punchline" else "",
        "captions": [_screen_text(c, TEXT_LIMITS["caption"]) for c in raw["captions"]][:3] if fmt == "top3" else [],
    }
    if not meta["hook"]:
        raise ValueError("the writer returned no hook")
    if fmt == "punchline" and not meta["punchline"]:
        raise ValueError("the writer returned no punchline")
    if fmt == "pov" and not meta["hook"].lower().startswith("pov"):
        meta["hook"] = f"POV: {meta['hook']}"
    if fmt == "top3":
        meta["captions"] += [""] * (3 - len(meta["captions"]))

    hashtags = []
    for tag in raw["hashtags"][:5] + cfg["metadata"]["base_hashtags"]:
        tag = _hashtag(tag)
        if tag and tag not in hashtags:
            hashtags.append(tag)

    title = " ".join(_no_brackets(HASHTAG_WORD.sub("", raw["title"])).split())[:100]
    description = "\n\n".join(p for p in (raw["description"].strip(), _credits(clips), " ".join(hashtags)) if p)

    tags, length = [], 0
    for tag in raw["tags"]:
        tag = " ".join(_no_brackets(tag).replace(",", " ").split())
        if tag and tag.lower() not in {t.lower() for t in tags} and length + len(tag) + 3 <= 450:
            tags.append(tag)
            length += len(tag) + 3

    meta.update(title=title or concept["theme"].capitalize(), description=_no_brackets(description),
                hashtags=hashtags, tags=tags)
    return meta


def write_metadata(concept: dict, clips: list[dict], cfg: dict) -> dict:
    fmt = concept["format"]
    system = f"""You write the on-screen text and YouTube metadata for one Short. {_channel_brief(cfg)}
On-screen text is read in under two seconds: short, punchy, plain words, no emoji, no hashtags.
The text must fit what the clips actually show: the setting (indoors/outdoors), time of day and action.
If the planned angle doesn't fit the footage, adapt the joke to the footage.
The clips are stock footage: relatable jokes and 'POV' framing are great, but never claim the animal is
yours or present an invented backstory as true.
Title: max 70 characters, may include one emoji, honest (no clickbait promises), no hashtags.
Description: 1-2 short friendly sentences; ending with a light question that invites comments is good.
Hashtags: 3-5, relevant to what's shown, lowercase, no spaces. Tags: 5-10 search keywords."""
    shown = [{"clip": i + 1, "animal": (c.get("check") or {}).get("animal"),
              "what_happens": (c.get("check") or {}).get("what_happens")} for i, c in enumerate(clips)]
    prompt = (f"Theme: {concept['theme']}\nAngle: {concept['angle']}\n"
              f"Trend: {concept.get('trend_used') or 'evergreen'}\n"
              f"Format: {fmt}. {FORMATS[fmt]['brief']}\nText rules for this format: {FORMAT_TEXT_RULES[fmt]}\n"
              f"What the clips show, in order:\n{json.dumps(shown, ensure_ascii=False, indent=1)}")
    raw = llm.generate_json([prompt], META_SCHEMA, system)
    return _clean_metadata(raw, fmt, concept, clips, cfg)


def build_edit(fmt: str, meta: dict, clips: list[dict], cfg: dict) -> dict:
    """Segments (trimmed clips in order) plus timed caption overlays for short_render.py."""
    low, high = FORMATS[fmt]["seconds"]
    segments = []
    for clip in clips:
        available = max(clip["duration"] - 0.5, 0.0)  # stay clear of the clip's last frames
        duration = min(high, max(low, available)) if available >= low else available
        start = 0.3 if available - duration >= 0.3 else 0.0  # skip a possible fade-in
        segments.append({"key": clip["key"], "url": clip["download_url"], "start": start,
                         "duration": round(duration, 2), "width": clip["width"], "height": clip["height"]})

    total = sum(s["duration"] for s in segments)
    max_total = cfg["content"]["max_short_seconds"]
    if total > max_total:
        for s in segments:
            s["duration"] = round(s["duration"] * max_total / total, 2)
        total = sum(s["duration"] for s in segments)
    total = round(total, 2)

    overlays = [{"text": meta["hook"], "start": 0.0, "end": total, "position": "top"}]
    if fmt == "punchline":
        overlays.append({"text": meta["punchline"], "start": round(max(2.0, total * 0.45), 2),
                         "end": total, "position": "bottom"})
    elif fmt == "top3":
        t = 0.0
        for i, (segment, caption) in enumerate(zip(segments, meta["captions"])):
            number = len(segments) - i
            overlays.append({"text": f"{number}. {caption}" if caption else f"#{number}",
                             "start": round(t, 2), "end": round(t + segment["duration"], 2), "position": "bottom"})
            t += segment["duration"]
    return {"format": fmt, "duration": total, "segments": segments, "overlays": overlays}


def apply_edits(plan: dict, edits: dict, cfg: dict) -> dict:
    """The owner's edits from the dashboard: same cleanup rules as generated text, then a fresh edit."""
    fmt, meta = plan["concept"]["format"], plan["metadata"]
    if "hook" in edits:
        meta["hook"] = _screen_text(str(edits["hook"]), TEXT_LIMITS["hook"])
    if "punchline" in edits and fmt == "punchline":
        meta["punchline"] = _screen_text(str(edits["punchline"]), TEXT_LIMITS["punchline"])
    if "captions" in edits and fmt == "top3":
        meta["captions"] = ([_screen_text(str(c), TEXT_LIMITS["caption"]) for c in edits["captions"]] + [""] * 3)[:3]
    if "title" in edits:
        meta["title"] = " ".join(_no_brackets(HASHTAG_WORD.sub("", str(edits["title"]))).split())[:100] or meta["title"]
    if "description" in edits:
        meta["description"] = _no_brackets(str(edits["description"])).strip()[:4900]
    if not meta["hook"]:
        raise ValueError("The top caption can't be empty.")
    if fmt == "punchline" and not meta["punchline"]:
        raise ValueError("The punchline can't be empty.")
    plan["edit"] = build_edit(fmt, meta, plan["clips"], cfg)
    return plan


def write_learnings(rows: list[dict], cfg: dict) -> dict:
    system = f"""You analyse recent results for a YouTube Shorts channel. {_channel_brief(cfg)}
Give 3-6 concrete, testable lessons about which formats, themes, animals and hook styles do better or worse.
Small samples are noisy: say 'early signal' when the evidence is thin.
Summary: 2-3 plain sentences for the channel owner."""
    prompt = ("Recent Shorts with their public numbers (views, likes, comments):\n"
              + json.dumps(rows, ensure_ascii=False, indent=1))
    return llm.generate_json([prompt], LEARNINGS_SCHEMA, system)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    concept_cmd = sub.add_parser("concept", help="Plan a concept from trend signals")
    concept_cmd.add_argument("--trends", required=True, help="JSON file from trends_fetch.py")
    concept_cmd.add_argument("--format", choices=list(FORMATS), default="punchline")
    concept_cmd.add_argument("--out", default=str(tmp_path("concept.json")))
    meta_cmd = sub.add_parser("metadata", help="Write text + edit for the best checked clips")
    meta_cmd.add_argument("--concept", required=True, help="JSON file from the concept command")
    meta_cmd.add_argument("--clips", required=True, help="JSON file from clip_check.py")
    meta_cmd.add_argument("--out", default=str(tmp_path("plan.json")))
    args = parser.parse_args()

    cfg = load_config()
    try:
        if args.command == "concept":
            with open(args.trends, encoding="utf-8") as f:
                result = plan_concept(json.load(f), args.format, [], None, cfg)
        else:
            with open(args.concept, encoding="utf-8") as f:
                concept = json.load(f)
            with open(args.clips, encoding="utf-8") as f:
                ok_clips = [c for c in json.load(f) if c.get("ok")]
            needed = FORMATS[concept["format"]]["clips"]
            if len(ok_clips) < needed:
                raise RuntimeError(f"{concept['format']} needs {needed} approved clip(s), found {len(ok_clips)}")
            chosen = ok_clips[:needed]
            meta = write_metadata(concept, chosen, cfg)
            result = {"concept": concept, "clips": chosen, "metadata": meta,
                      "edit": build_edit(concept["format"], meta, chosen, cfg)}
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps(result.get("metadata", result), indent=2, ensure_ascii=False))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
