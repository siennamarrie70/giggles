"""
Finds free, licensed stock clips for a concept: Pexels first, Pixabay as a backup.

Both licenses allow free use on YouTube, including edited clips, with no credit
required (the description credits the creator anyway). Clips listed in `exclude`
(already used) are skipped so the channel never repeats footage.

Usage:
    python tools/clips_search.py --query "kitten yawning" --query "sleepy cat" [--out .tmp/candidates.json]
"""

import argparse
import json
import sys

import requests

from common import env, tmp_path

PEXELS_SEARCH = "https://api.pexels.com/v1/videos/search"
PIXABAY_SEARCH = "https://pixabay.com/api/videos/"
MIN_LONG_SIDE = 960      # skip footage smaller than this; it looks soft at 1080x1920
MAX_LONG_SIDE = 1920     # no point downloading 4K for a 1080p Short


def _spread(items: list, n: int) -> list:
    """Pick n items spread evenly through the list (first, middle, last...)."""
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def _best_pexels_file(files: list[dict]) -> dict | None:
    mp4s = [f for f in files if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    long_side = lambda f: max(f["width"], f["height"])
    fitting = [f for f in mp4s if MIN_LONG_SIDE <= long_side(f) <= MAX_LONG_SIDE]
    return max(fitting, key=long_side) if fitting else None


def search_pexels(query: str, orientation: str = "portrait", per_page: int = 40) -> list[dict]:
    key = env("PEXELS_API_KEY")
    if not key:
        return []
    resp = requests.get(PEXELS_SEARCH, headers={"Authorization": key}, timeout=30, params={
        "query": query, "orientation": orientation, "size": "medium", "per_page": per_page, "locale": "en-US",
    })
    resp.raise_for_status()
    clips = []
    for video in resp.json().get("videos", []):
        file = _best_pexels_file(video.get("video_files", []))
        pictures = [p["picture"] for p in sorted(video.get("video_pictures", []), key=lambda p: p.get("nr", 0)) if p.get("picture")]
        if not file or not (pictures or video.get("image")):
            continue
        user = video.get("user") or {}
        clips.append({
            "key": f"pexels:{video['id']}", "source": "pexels", "id": str(video["id"]),
            "page_url": video.get("url"),
            "credit_name": user.get("name") or "a Pexels creator",
            "credit_url": user.get("url") or video.get("url"),
            "duration": float(video.get("duration") or 0),
            "width": file["width"], "height": file["height"],
            "download_url": file["link"],
            "preview_urls": _spread(pictures, 3) or [video["image"]],
            "query": query,
        })
    return clips


def search_pixabay(query: str, per_page: int = 20) -> list[dict]:
    key = env("PIXABAY_API_KEY")
    if not key:
        return []
    resp = requests.get(PIXABAY_SEARCH, timeout=30, params={
        "key": key, "q": query[:100], "video_type": "film", "safesearch": "true",
        "order": "popular", "per_page": per_page,
    })
    resp.raise_for_status()
    clips = []
    for hit in resp.json().get("hits", []):
        rendition = (hit.get("videos") or {}).get("medium") or {}
        if not rendition.get("url") or max(rendition.get("width", 0), rendition.get("height", 0)) < MIN_LONG_SIDE:
            continue
        clips.append({
            "key": f"pixabay:{hit['id']}", "source": "pixabay", "id": str(hit["id"]),
            "page_url": hit.get("pageURL"),
            "credit_name": hit.get("user") or "a Pixabay creator",
            "credit_url": f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/",
            "duration": float(hit.get("duration") or 0),
            "width": rendition["width"], "height": rendition["height"],
            "download_url": rendition["url"],
            "preview_urls": [rendition["thumbnail"]] if rendition.get("thumbnail") else [],
            "query": query,
        })
    return clips


def run(queries: list[str], exclude: set[str] | frozenset = frozenset(), min_seconds: float = 4,
        limit: int = 8) -> list[dict]:
    """Up to `limit` unused clips, alternating between queries so the mix stays varied."""
    if not (env("PEXELS_API_KEY") or env("PIXABAY_API_KEY")):
        raise RuntimeError("No stock footage key set. Add PEXELS_API_KEY (and optionally PIXABAY_API_KEY).")

    usable = lambda c: c["key"] not in exclude and c["duration"] >= min_seconds and c["preview_urls"]
    # Portrait first (fills the frame); landscape and Pixabay only if that runs short. Portrait
    # asks for 40 results so popular searches still have unused clips after weeks of 10 Shorts a day.
    searches = [lambda q: search_pexels(q, "portrait"), lambda q: search_pexels(q, "landscape", 15), search_pixabay]

    picked, seen = [], set()
    for search in searches:
        per_query = [[c for c in search(q) if usable(c)] for q in queries]
        while any(per_query) and len(picked) < limit:
            for results in per_query:
                while results:
                    clip = results.pop(0)
                    if clip["key"] not in seen:
                        seen.add(clip["key"])
                        picked.append(clip)
                        break
                if len(picked) >= limit:
                    break
        if len(picked) >= limit:
            break
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--query", action="append", required=True, help="Search phrase (repeatable)")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--out", default=str(tmp_path("candidates.json")))
    args = parser.parse_args()

    try:
        clips = run(args.query, limit=args.limit)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(clips, f, indent=2)
    for c in clips:
        print(f"{c['key']:<18} {c['width']}x{c['height']} {c['duration']:>4.0f}s  '{c['query']}'  by {c['credit_name']}")
    print(f"Wrote {len(clips)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
