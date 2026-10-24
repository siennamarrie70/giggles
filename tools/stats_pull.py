"""
Pulls performance numbers for the channel's uploaded Shorts.

Views, likes and comments come from the YouTube Data API (up to date). Average
percent viewed, average view duration and subscribers gained come from the YouTube
Analytics API, which lags about two days; if that call fails the rest still works.

Usage:
    python tools/stats_pull.py --id VIDEO_ID [--id VIDEO_ID ...] [--out .tmp/stats.json]
"""

import argparse
import json
import sys
from datetime import date, timedelta

import youtube_auth
from common import tmp_path

ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def run(video_ids: list[str], days: int = 90) -> dict:
    stats = {}
    for chunk in _chunks(video_ids, 50):
        for item in youtube_auth.yt_get("videos", {"part": "statistics", "id": ",".join(chunk)}).get("items", []):
            s = item.get("statistics", {})
            stats[item["id"]] = {
                "youtube_id": item["id"], "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
                "avg_view_pct": None, "avg_view_seconds": None, "subs_gained": None,
            }

    analytics_error = None
    try:
        end = date.today()
        for chunk in _chunks(list(stats), 50):
            report = youtube_auth.yt_get(ANALYTICS_URL, {
                "ids": "channel==MINE", "startDate": (end - timedelta(days=days)).isoformat(),
                "endDate": end.isoformat(), "dimensions": "video", "filters": "video==" + ",".join(chunk),
                "metrics": "views,averageViewPercentage,averageViewDuration,subscribersGained",
                "sort": "-views", "maxResults": 50,
            })
            columns = [c["name"] for c in report.get("columnHeaders", [])]
            for row in report.get("rows") or []:
                r = dict(zip(columns, row))
                if r["video"] in stats:
                    stats[r["video"]].update(avg_view_pct=r["averageViewPercentage"],
                                             avg_view_seconds=r["averageViewDuration"],
                                             subs_gained=r["subscribersGained"])
    except Exception as e:
        analytics_error = str(e)

    return {"videos": list(stats.values()), "analytics_error": analytics_error}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--id", action="append", required=True, help="YouTube video ID (repeatable)")
    parser.add_argument("--out", default=str(tmp_path("stats.json")))
    args = parser.parse_args()

    try:
        result = run(args.id)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    for v in result["videos"]:
        print(f"{v['youtube_id']}  views {v['views']:>7}  likes {v['likes']:>5}  avg viewed {v['avg_view_pct']}%")
    if result["analytics_error"]:
        print(f"  note: analytics unavailable: {result['analytics_error']}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
