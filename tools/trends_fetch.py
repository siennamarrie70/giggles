"""
Collects today's trend signals for the concept writer.

Sources (each is optional; a failing source is reported in "errors", not fatal):
  - Google Trends daily trending searches (public RSS feed, no key)
  - YouTube's most-popular Pets & Animals chart, or a search for recent animal Shorts
    as a fallback (needs the YouTube sign-in from youtube_auth.py)
  - config/calendar.yaml: upcoming pet days/holidays, the season and a weekday vibe

The region is one country code (US, GB, IN...) or ALL. ALL asks every country in WORLD and
merges the lists: a search or video trending in many countries ranks first, because the
channel's audience is worldwide. That's ~190 requests, so the planner keeps the result for a
few hours (jobs.trend_signals) instead of asking for every Short.

Usage:
    python tools/trends_fetch.py [--region ALL] [--out .tmp/trends.json]
"""

import argparse
import json
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests

import youtube_auth
from common import load_config, tmp_path

GOOGLE_TRENDS_RSS = "https://trends.google.com/trending/rss"
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
# Every country Google's trending feed answered for when checked (2026-10-24; CN, IS, LU and MT
# didn't), biggest English-speaking markets first so they're asked first.
WORLD = ("US GB CA AU NZ IE IN PK BD LK NP PH SG MY ID TH VN JP KR TW HK AE SA EG IL TR NG KE ZA GH MA DZ TN "
         "DE FR ES IT PT NL BE CH AT SE NO DK FI PL CZ HU RO GR UA RU BR MX AR CO CL PE VE EC UY BO PY CR PA DO "
         "GT HN SV NI PR JM KZ QA KW BH OM JO LB SK SI HR RS BG LT LV EE CY BY GE AZ AM UZ").split()
# The feed refuses bursts (HTTP 429 after ~100 quick requests, 2026-10-24): ask a few countries at a
# time, and stop at the first refusal instead of hammering on.
WORKERS = 4


def google_trends(region: str, limit: int = 20) -> list[dict]:
    resp = requests.get(GOOGLE_TRENDS_RSS, params={"geo": region}, timeout=20,
                        headers={"User-Agent": "Mozilla/5.0 (trend reader)"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    terms = []
    for item in root.iter("item"):
        term = (item.findtext("title") or "").strip()
        if term:
            terms.append({"term": term, "traffic": (item.findtext("{*}approx_traffic") or "").strip()})
    return terms[:limit]


def _video(item: dict) -> dict:
    vid = item["id"]["videoId"] if isinstance(item["id"], dict) else item["id"]  # search vs chart results
    return {"id": vid, "title": item["snippet"]["title"],
            "views": int((item.get("statistics") or {}).get("viewCount", 0) or 0)}


def youtube_chart(region: str, limit: int = 25) -> list[dict]:
    """The most-popular Pets & Animals videos in one country (1 quota unit)."""
    items = youtube_auth.yt_get("videos", {
        "part": "snippet,statistics", "chart": "mostPopular", "regionCode": region,
        "videoCategoryId": "15", "maxResults": limit,
    }).get("items", [])
    return [_video(it) for it in items]


def youtube_popular(region: str, limit: int = 25) -> list[dict]:
    try:
        videos = youtube_chart(region, limit)
    except RuntimeError:
        videos = []  # the chart isn't offered for this category/region; fall back to search
    if videos:
        return videos
    since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = youtube_auth.yt_get("search", {  # 100 quota units, so only for a single country
        "part": "snippet", "type": "video", "videoDuration": "short", "order": "viewCount",
        "publishedAfter": since, "regionCode": region, "relevanceLanguage": "en",
        "q": "cute animals", "maxResults": limit,
    }).get("items", [])
    return [_video(it) for it in items]


def ask_each(fetch, countries: list[str]) -> tuple[dict, list[str]]:
    """fetch(country) for each country, a few at a time. The ones that fail get one more try after a
    pause, unless a country was refused (HTTP 429): then the rest are left out."""
    found, refused = {}, threading.Event()

    def one(country: str) -> None:
        if refused.is_set():
            return
        try:
            found[country] = fetch(country)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                refused.set()
        except Exception:
            pass

    for attempt in range(2):
        todo = [c for c in countries if c not in found]
        if not todo or refused.is_set():
            break
        if attempt:
            time.sleep(3)
        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(one, todo))
    return found, [c for c in countries if c not in found]


def _in_world_order(countries: list[str]) -> list[str]:
    return sorted(countries, key=lambda c: WORLD.index(c) if c in WORLD else len(WORLD))


def merge_searches(by_country: dict[str, list[dict]], limit: int = 30) -> list[dict]:
    """One list of searches from many countries': trending in the most countries first, then by traffic."""
    merged = {}
    for country, terms in by_country.items():
        for t in terms:
            m = merged.setdefault(" ".join(t["term"].casefold().split()), {"term": t["term"], "countries": [], "volume": 0})
            m["countries"].append(country)
            m["volume"] += int(re.sub(r"\D", "", t["traffic"]) or 0)  # "1,000+" -> 1000
    ranked = sorted(merged.values(), key=lambda m: (-len(m["countries"]), -m["volume"]))[:limit]
    return [{"term": m["term"], "traffic": f"{m['volume']:,}+" if m["volume"] else "",
             "countries": _in_world_order(m["countries"])} for m in ranked]


def merge_videos(by_country: dict[str, list[dict]], limit: int = 25) -> list[dict]:
    """One list of videos from many countries' charts: popular in the most countries first, then by views."""
    merged = {}
    for country, videos in by_country.items():
        for v in videos:
            merged.setdefault(v["id"], {**v, "countries": []})["countries"].append(country)
    ranked = sorted(merged.values(), key=lambda m: (-len(m["countries"]), -m["views"]))[:limit]
    return [{**m, "countries": _in_world_order(m["countries"])} for m in ranked]


def _missing(source: str, missed: list[str]) -> str:
    shown = " ".join(missed[:8]) + (" …" if len(missed) > 8 else "")
    return f"{source}: no answer from {len(missed)} of {len(WORLD)} countries ({shown})"


def online(region: str = "US") -> dict:
    """The internet part of the signals, for one country or ALL."""
    region = region.upper()
    out = {"region": region, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "google_trends": [], "youtube_popular": [], "errors": []}
    if region == "ALL":
        terms, missed = ask_each(google_trends, WORLD)
        out["google_trends"], out["countries"] = merge_searches(terms), len(terms)
        if missed:
            out["errors"].append(_missing("google_trends", missed))
    else:
        try:
            out["google_trends"] = google_trends(region)
        except Exception as e:
            out["errors"].append(f"google_trends: {e}")

    if not youtube_auth.is_configured():
        out["errors"].append("youtube_popular: skipped, YouTube sign-in not set up")
    elif region == "ALL":
        try:
            youtube_auth.get_access_token()  # sign in once; the parallel calls share the token
            charts, missed = ask_each(youtube_chart, WORLD)
            out["youtube_popular"] = merge_videos(charts)
            if missed:
                out["errors"].append(_missing("youtube_popular", missed))
        except Exception as e:
            out["errors"].append(f"youtube_popular: {e}")
    else:
        try:
            out["youtube_popular"] = youtube_popular(region)
        except Exception as e:
            out["errors"].append(f"youtube_popular: {e}")
    return out


def event_date(event: dict, year: int) -> date:
    if "date" in event:
        month, day = (int(x) for x in event["date"].split("-"))
        return date(year, month, day)
    nth, weekday, month = event["rule"].split()
    first = date(year, int(month), 1)
    offset = (WEEKDAYS[weekday.lower()[:3]] - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (int(nth) - 1))


def calendar_signals(today: date, days_ahead: int) -> dict:
    cal = load_config("calendar")
    events = []
    for event in cal.get("events", []):
        for year in (today.year, today.year + 1):
            when = event_date(event, year)
            if 0 <= (when - today).days <= days_ahead:
                events.append({"name": event["name"], "date": when.isoformat(), "in_days": (when - today).days})
    season = next((name for name, months in cal.get("seasons", {}).items() if today.month in months), None)
    return {
        "events": sorted(events, key=lambda e: e["in_days"]),
        "season": season,
        "weekday_vibe": (cal.get("weekday_vibes") or {}).get(today.weekday()),
    }


def run(region: str = "US", days_ahead: int = 3, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    return {"date": today.isoformat(), "weekday": today.strftime("%A"), **calendar_signals(today, days_ahead),
            **online(region)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--region", default=load_config()["trends"]["region"], help="a country code, or ALL")
    parser.add_argument("--out", default=str(tmp_path("trends.json")))
    args = parser.parse_args()

    try:
        signals = run(args.region, load_config()["trends"]["calendar_days_ahead"])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(signals, f, indent=2, ensure_ascii=False)
    print(f"Events: {[e['name'] for e in signals['events']]}  season: {signals['season']}  vibe: {signals['weekday_vibe']}")
    print(f"Google Trends: {len(signals['google_trends'])} terms  YouTube: {len(signals['youtube_popular'])} titles"
          + (f"  ({signals['countries']} countries answered)" if "countries" in signals else ""))
    for err in signals["errors"]:
        print(f"  note: {err}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
