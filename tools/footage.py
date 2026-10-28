"""
Real video for the documentary cases: free stock clips from Pexels (portrait first, then landscape)
and Pixabay, and archive film of the real thing from the Internet Archive (the Prelinger Archives'
mid-century films and FedFlix, the US government's films: only items marked public domain) and
NASA's library, checked by Gemini from their frames, downloaded once into .tmp/footage.

Pexels and Pixabay allow free use on YouTube, edited and monetised, with no credit required; the
description credits each creator anyway. Stock clips are illustrative (mood, places, everyday
scenes): the Writer never presents them as the real company, person or event. Archive film is the
real thing (a 1942 battle, a 1950s Tupperware advert), so it carries specific claims; from a long
film only a few seconds are cut, around the frame Gemini liked best, without downloading the rest.
NASA's footage isn't copyrighted; its rules: credit NASA, never suggest NASA endorses anything.

Gemini looks at up to 3 frames of every candidate in one request. The hard rules are applied in
code after it answers, so a lenient answer can't let them through: never a child, nothing graphic
or sexual, no distress, nothing blurry or dark, nothing off the subject; for stock clips also no
burned-in text, watermark or brand logo as the focus, and no weapons or fighting. Archive film may
show a period battle without gore, for history cases, or a brand in its own old advert. Clips
already used by the channel are skipped.

Ported from v2's tools/footage/clips_search.py, clip_check.py, film_search.py and nasa_search.py
(tag v2-meme-bar).

  search()          stock candidates for a few searches, alternating so the mix stays varied
  search_archive()  archive films and NASA videos, with three frames each read straight off the web
  check()           the candidates with Gemini's verdict, usable ones first
  download()        a stock clip's file, at most 1920 px on its long side; cut() an archive film's seconds
  credit()          the clip's line for the description

What comes from these services is handled as untrusted (2026-10-28): an archive film's web address goes straight
to ffmpeg, which can also open files on this computer and playlists that point anywhere, so it must be https from
the Internet Archive or NASA (FILM_HOSTS) and ffmpeg may only use web protocols for it (WEB_ONLY); a file is named
after its id with nothing but letters, digits, dots, dashes and underscores (_file_name: no "../"); a download
stops at MAX_DOWNLOAD.

Usage:
    python tools/footage.py --query "old mobile phone" --query "stock market screen" [--check] [--download]
    python tools/footage.py --archive "aircraft carrier" --history [--check] [--download]
"""

import argparse
import io
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from PIL import Image

import llm
import text_clean
from common import env, tmp_path

PEXELS_SEARCH = "https://api.pexels.com/v1/videos/search"
PIXABAY_SEARCH = "https://pixabay.com/api/videos/"
ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
ARCHIVE_META = "https://archive.org/metadata/{id}"
ARCHIVE_FILE = "https://archive.org/download/{id}/{name}"
ARCHIVE_PAGE = "https://archive.org/details/{id}"
ARCHIVE_BASE = ("(collection:prelinger OR collection:FedFlix) AND mediatype:movies AND "
                "licenseurl:(*publicdomain*)")  # public domain items only
NASA_SEARCH = "https://images-api.nasa.gov/search"
NASA_ASSET = "https://images-api.nasa.gov/asset/{id}"
NASA_PAGE = "https://images.nasa.gov/details/{id}"
HEADERS = {"User-Agent": "ezzy-case-studies/1.0 (archive footage for documentary Shorts)"}
FILM_HOSTS = ("archive.org", "nasa.gov")  # where an archive film's address may point (it goes straight to ffmpeg)
WEB_ONLY = ["-protocol_whitelist", "https,tls,tcp,http"]  # ffmpeg, for a web address: no local files, no other schemes
MAX_DOWNLOAD = 400 * 1024 * 1024  # bytes: a stock clip bigger than this isn't downloaded (they're 10-80 MB)
MIN_LONG_SIDE = 960   # softer than this looks poor at 1080x1920 (stock; archive film is what it is)
MAX_LONG_SIDE = 1920  # no point downloading 4K for a 1080p Short
FRAME_SIZE = 512      # px, long side, for Gemini's check
MIN_SCORE = 6
ARCHIVE_PER_QUERY = 3
CUT_SECONDS = 9       # how much of an archive film is kept, around its best frame
# Films about young people (many were made for schools) and grim subjects are left out by their words.
ARCHIVE_SKIP = re.compile(r"\b(teen\w*|adolescen\w*|high school|junior high|schoolchild\w*|girl|girls|boy|boys|child\w*|"
                          r"kid|kids|juvenile|youth|youngster\w*|baby|babies|venereal|syphilis|surgery|autopsy|corpse\w*|"
                          r"execution\w*|atrocit\w*|concentration camp|holocaust|sex\w*|nude|nudity|drug\w*|narcotic\w*|"
                          r"cigarette\w*|tobacco|alcohol\w*|propaganda|racis\w*|negro\w*)\b", re.IGNORECASE)
NASA_SKIP = re.compile(r"(©|copyright|courtesy|credit:\s*(?!nasa)|spacex|boeing|blue origin|esa/|jaxa|roscosmos|"
                       r"\b(challenger|columbia accident|memorial|tribute|died|death|crash\w*|explosion\w*)\b)", re.IGNORECASE)
# People talking (briefings, news shows, interviews) rarely have the pictures a Short needs.
NASA_TALK = re.compile(r"\b(this week|news|update|briefing\w*|conference\w*|interview\w*|podcast\w*|webinar\w*|q&a|panel|"
                       r"remarks|speech\w*|coverage|town hall|ceremony|explains?|lecture\w*|science live|"
                       r"what's up)\b", re.IGNORECASE)

CHECK_SYSTEM = """You review video clips for a YouTube channel of short documentary case studies (business, the
economy, history, mythology) for adults. Each candidate comes with 1-3 frames from the same clip: stock footage, or
archive film (old public-domain films, newsreels and adverts) or NASA footage. Judge only what you can see. Be strict
about safety flags: if you are unsure whether a child or teenager is visible, flag it.
fits is false when the clip doesn't show the wanted subject or mood. score 0-10: how well it suits the subject and how
good it looks (archive film is old: judge it as archive film, but it must be clear enough to read). stop_power 0-10:
how strongly it would stop someone scrolling. best_frame: the number (1-3) of the frame that looks best."""

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "shows": {"type": "string", "description": "what the clip shows, in a few words"},
                    "child_visible": {"type": "boolean", "description": "anyone who may be under 18"},
                    "text_or_logo": {"type": "boolean",
                                     "description": "a watermark, captions, or a brand name or logo as the focus"},
                    "distress": {"type": "boolean", "description": "people hurt, suffering, frightened or in danger"},
                    "graphic": {"type": "boolean", "description": "gore, blood, injuries, dead bodies"},
                    "combat": {"type": "boolean", "description": "weapons, fighting, explosions, warships or warplanes"},
                    "unsuitable": {"type": "boolean", "description": "nudity or suggestive, drugs, or alcohol or smoking "
                                                                     "as the focus, hateful symbols"},
                    "low_quality": {"type": "boolean", "description": "blurry, dark, shaky, or the subject is hard to see"},
                    "fits": {"type": "boolean"},
                    "score": {"type": "integer"},
                    "stop_power": {"type": "integer"},
                    "best_frame": {"type": "integer"},
                },
                "required": ["index", "shows", "child_visible", "text_or_logo", "distress", "graphic", "combat",
                             "unsuitable", "low_quality", "fits", "score", "stop_power", "best_frame"],
            },
        },
    },
    "required": ["candidates"],
}


# --- searching ------------------------------------------------------------------

def _spread(items: list, n: int) -> list:
    """n items spread evenly through the list (first, middle, last...)."""
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def _best_pexels_file(files: list[dict]) -> dict | None:
    mp4s = [f for f in files if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    fitting = [f for f in mp4s if MIN_LONG_SIDE <= max(f["width"], f["height"]) <= MAX_LONG_SIDE]
    return max(fitting, key=lambda f: max(f["width"], f["height"])) if fitting else None


def search_pexels(query: str, orientation: str = "portrait", per_page: int = 15) -> list[dict]:
    key = env("PEXELS_API_KEY")
    if not key:
        return []
    resp = requests.get(PEXELS_SEARCH, headers={"Authorization": key}, timeout=30, params={
        "query": query, "orientation": orientation, "size": "medium", "per_page": per_page, "locale": "en-US"})
    resp.raise_for_status()
    clips = []
    for video in resp.json().get("videos", []):
        file = _best_pexels_file(video.get("video_files", []))
        pictures = [p["picture"] for p in sorted(video.get("video_pictures", []), key=lambda p: p.get("nr", 0))
                    if p.get("picture")]
        if not file or not (pictures or video.get("image")):
            continue
        user = video.get("user") or {}
        clips.append({"key": f"pexels:{video['id']}", "source": "Pexels", "page_url": video.get("url"),
                      "credit_name": user.get("name") or "a Pexels creator", "credit_url": user.get("url") or video.get("url"),
                      "duration": float(video.get("duration") or 0), "width": file["width"], "height": file["height"],
                      "download_url": file["link"], "preview_urls": _spread(pictures, 3) or [video["image"]],
                      "query": query})
    return clips


def search_pixabay(query: str, per_page: int = 15) -> list[dict]:
    key = env("PIXABAY_API_KEY")
    if not key:
        return []
    resp = requests.get(PIXABAY_SEARCH, timeout=30, params={
        "key": key, "q": query[:100], "video_type": "film", "safesearch": "true", "order": "popular", "per_page": per_page})
    resp.raise_for_status()
    clips = []
    for hit in resp.json().get("hits", []):
        videos = hit.get("videos") or {}
        rendition = next((videos[k] for k in ("large", "medium") if (videos.get(k) or {}).get("url")
                          and MIN_LONG_SIDE <= max(videos[k].get("width", 0), videos[k].get("height", 0)) <= MAX_LONG_SIDE), None)
        if not rendition:
            continue
        clips.append({"key": f"pixabay:{hit['id']}", "source": "Pixabay", "page_url": hit.get("pageURL"),
                      "credit_name": hit.get("user") or "a Pixabay creator",
                      "credit_url": f"https://pixabay.com/users/{hit.get('user')}-{hit.get('user_id')}/",
                      "duration": float(hit.get("duration") or 0), "width": rendition["width"], "height": rendition["height"],
                      "download_url": rendition["url"],
                      "preview_urls": [rendition["thumbnail"]] if rendition.get("thumbnail") else [], "query": query})
    return clips


def search(queries: list[str], exclude: set[str] | frozenset = frozenset(), min_seconds: float = 4,
           per_query: int = 3) -> list[dict]:
    """Up to per_query unused clips for each search: portrait Pexels first (fills the frame), then landscape
    Pexels, then Pixabay, for searches that still need more."""
    if not (env("PEXELS_API_KEY") or env("PIXABAY_API_KEY")):
        raise RuntimeError("No stock footage key set. Add PEXELS_API_KEY (and optionally PIXABAY_API_KEY) to .env.")
    picked, seen = {q: [] for q in queries}, set(exclude)
    for search_fn in (lambda q: search_pexels(q, "portrait"), lambda q: search_pexels(q, "landscape", 10), search_pixabay):
        for query in queries:
            if len(picked[query]) >= per_query:
                continue
            try:
                found = search_fn(query)
            except requests.RequestException:
                continue
            for clip in found:
                if clip["key"] in seen or clip["duration"] < min_seconds or not clip["preview_urls"]:
                    continue
                seen.add(clip["key"])
                picked[query].append(clip)
                if len(picked[query]) >= per_query:
                    break
    return [clip for query in queries for clip in picked[query]]


# --- archive film -----------------------------------------------------------------

def _text(value) -> str:
    return " ".join(value) if isinstance(value, list) else str(value or "")


def _seconds(length) -> float:
    """A length as archive.org writes it: '808.71' or '13:28'."""
    try:
        parts = [float(p) for p in str(length).split(":")]
    except ValueError:
        return 0.0
    return sum(p * 60 ** k for k, p in enumerate(reversed(parts)))


def _ffmpeg() -> str:
    import short_render

    return short_render.ffmpeg_exe()


def _film_url(url: str) -> str:
    """An archive film's web address, if ffmpeg may open it: https, at the Internet Archive or NASA. ValueError if not."""
    parts = urlparse(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or not any(host == h or host.endswith("." + h) for h in FILM_HOSTS):
        raise ValueError(f"not an archive film's address: {str(url)[:120]}")
    return url


def _file_name(key: str) -> str:
    """A file name from a clip's key ("archive:some-film"): letters, digits, dots, dashes and underscores only."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", key).lstrip(".") or "clip"


def _probe(url: str) -> float:
    """A video's length in seconds, read from the web (0 if unknown)."""
    try:
        err = subprocess.run([_ffmpeg(), "-hide_banner", *WEB_ONLY, "-i", _film_url(url)], capture_output=True, text=True,
                             timeout=60).stderr
    except (subprocess.TimeoutExpired, ValueError):
        return 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _grab(url: str, at: float) -> bytes | None:
    """One frame of a video on the web at `at` seconds, as a small JPEG (ffmpeg reads only that part of it)."""
    small = f"scale='if(gt(iw,ih),{FRAME_SIZE},-2)':'if(gt(iw,ih),-2,{FRAME_SIZE})'"
    try:
        raw = subprocess.run([_ffmpeg(), "-v", "error", "-ss", f"{at:.2f}", *WEB_ONLY, "-i", _film_url(url), "-frames:v", "1",
                              "-vf", small,
                              "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"], capture_output=True, timeout=90).stdout
    except (subprocess.TimeoutExpired, ValueError):
        return None
    return raw or None


def search_films(query: str, rows: int = 8, exclude: set[str] | frozenset = frozenset()) -> list[dict]:
    """Public-domain films (Prelinger, FedFlix) for a search, most watched first, without the grim ones."""
    words = re.sub(r"[^\w\s'-]", " ", query).strip()
    if not words:
        return []
    resp = requests.get(ARCHIVE_SEARCH, headers=HEADERS, timeout=30, params={
        "q": f"{ARCHIVE_BASE} AND ({words})", "fl[]": ["identifier", "title", "year", "description", "subject"],
        "sort[]": "downloads desc", "rows": rows, "output": "json"})
    resp.raise_for_status()
    found = []
    for doc in resp.json().get("response", {}).get("docs", []):
        about = f"{_text(doc.get('title'))} {_text(doc.get('description'))} {_text(doc.get('subject'))}"
        key = f"archive:{doc['identifier']}"
        if key not in exclude and not ARCHIVE_SKIP.search(about):
            found.append({"key": key, "id": doc["identifier"], "source": "Internet Archive",
                          "title": _text(doc.get("title")).strip()[:120], "year": str(doc.get("year") or "")[:4] or None,
                          "page_url": ARCHIVE_PAGE.format(id=doc["identifier"]), "query": query})
    return found


def film_file(film_id: str) -> dict | None:
    """A film's best MP4 (H.264 if there is one; most are 640x480) and its length."""
    resp = requests.get(ARCHIVE_META.format(id=film_id), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    files = [f for f in resp.json().get("files", []) if f.get("name", "").lower().endswith(".mp4")]
    if not files:
        return None
    best = max(files, key=lambda f: (f.get("format") == "h.264", f.get("format") == "512Kb MPEG4",
                                     not f["name"].endswith("_edit.mp4")))
    return {"url": ARCHIVE_FILE.format(id=film_id, name=quote(best["name"])), "duration": _seconds(best.get("length"))}


def search_nasa(query: str, rows: int = 10, exclude: set[str] | frozenset = frozenset()) -> list[dict]:
    """NASA's own videos for a search (not ones it credits to others; no accidents, memorials or briefings)."""
    resp = requests.get(NASA_SEARCH, headers=HEADERS, timeout=30, params={"q": query, "media_type": "video",
                                                                          "page_size": rows})
    resp.raise_for_status()
    found = []
    for item in resp.json().get("collection", {}).get("items", []):
        data = (item.get("data") or [{}])[0]
        nasa_id = data.get("nasa_id")
        text = f"{data.get('title', '')} {data.get('description', '')} {data.get('secondary_creator', '')}"
        if nasa_id and f"nasa:{nasa_id}" not in exclude and not NASA_SKIP.search(text) \
                and not NASA_TALK.search(data.get("title") or ""):
            found.append({"key": f"nasa:{nasa_id}", "id": nasa_id, "source": "NASA",
                          "title": (data.get("title") or nasa_id).strip()[:120],
                          "year": (data.get("date_created") or "")[:4] or None, "page_url": NASA_PAGE.format(id=nasa_id),
                          "query": query})
    return found


def nasa_file(nasa_id: str) -> dict | None:
    resp = requests.get(NASA_ASSET.format(id=nasa_id), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    urls = [i["href"].replace("http://", "https://") for i in resp.json().get("collection", {}).get("items", [])]
    for size in ("~large.mp4", "~medium.mp4", "~orig.mp4", "~small.mp4"):
        url = next((u for u in urls if u.endswith(size)), None)
        if url:
            return {"url": url, "duration": 0.0}
    return None


def _with_frames(clip: dict, nasa: bool) -> dict | None:
    """The candidate with its file, its length and three frames (at 22%, 47% and 72%: past any opening titles)."""
    try:
        file = (nasa_file if nasa else film_file)(clip["id"])
    except requests.RequestException:
        return None
    if not file:
        return None
    duration = file["duration"] or _probe(file["url"])
    if duration < CUT_SECONDS:
        return None
    times = [round(duration * p, 1) for p in (0.22, 0.47, 0.72)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        shots = [(t, f) for t, f in zip(times, pool.map(lambda t: _grab(file["url"], t), times)) if f]
    if not shots:
        return None
    return {**clip, "archive": True, "download_url": file["url"], "duration": duration,
            "frame_times": [t for t, _ in shots], "frames": [f for _, f in shots]}


def search_archive(queries: list[str], exclude: set[str] | frozenset = frozenset(), nasa: bool = False,
                   per_query: int = ARCHIVE_PER_QUERY) -> list[dict]:
    """Archive films (or NASA videos) for each search, each with three frames read off the web, ready for check()."""
    picked, seen = [], set(exclude)
    for query in queries:
        try:
            hits = (search_nasa if nasa else search_films)(query, exclude=seen)
        except requests.RequestException:
            continue
        hits = [h for h in hits if h["key"] not in seen][:per_query + 2]
        with ThreadPoolExecutor(max_workers=5) as pool:
            ready = [c for c in pool.map(lambda c: _with_frames(c, nasa), hits) if c]
        for clip in ready[:per_query]:
            seen.add(clip["key"])
            picked.append(clip)
    return picked


def cut_start(clip: dict, seconds: float = CUT_SECONDS) -> float:
    """Where the kept seconds of an archive film start: centred on the frame Gemini liked best."""
    times = clip.get("frame_times") or [clip.get("duration", 0) / 2]
    best = int(((clip.get("check") or {}).get("best_frame") or 1)) - 1
    at = times[min(max(best, 0), len(times) - 1)]
    return round(max(0.0, min(at - seconds / 2, clip.get("duration", at + seconds) - seconds)), 2)


def cut(clip: dict, start: float | None = None, seconds: float = CUT_SECONDS) -> Path:
    """An archive film's few seconds (from `start`, else around its best frame) as a local MP4 (H.264, no sound); the
    rest of the film is never downloaded."""
    start = cut_start(clip, seconds) if start is None else start
    dest = tmp_path("footage", f"{_file_name(clip['key'])}_{int(start)}.mp4")
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    partial = dest.with_name(dest.stem + ".part.mp4")
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-ss", f"{start:.2f}", *WEB_ONLY, "-i", _film_url(clip["download_url"]),
                    "-t", f"{seconds:.2f}",
                    "-an", "-vf", "scale='trunc(min(1280,iw)/2)*2':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(partial)], check=True, capture_output=True, timeout=300)
    partial.replace(dest)
    return dest


# --- checking -------------------------------------------------------------------

def _frame(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None
    img.thumbnail((FRAME_SIZE, FRAME_SIZE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def reject_reasons(verdict: dict | None, clip: dict | None = None) -> list[str]:
    """Why a clip can't be used (none: it can). Archive film may show its subject's own brand, and a period battle
    without gore when the clip says combat_ok (history cases)."""
    if verdict is None:
        return ["not checked"]
    clip = clip or {}
    flags = {"child_visible": "a child may be visible", "distress": "distress", "graphic": "graphic",
             "unsuitable": "unsuitable", "low_quality": "poor quality"}
    if not clip.get("archive"):
        flags["text_or_logo"] = "text or a logo"
    if not (clip.get("archive") and clip.get("combat_ok")):
        flags["combat"] = "weapons or fighting"
    reasons = [why for key, why in flags.items() if verdict.get(key)]
    if not verdict.get("fits"):
        reasons.append("doesn't fit")
    if int(verdict.get("score", 0)) < MIN_SCORE:
        reasons.append(f"score {verdict.get('score')}")
    return reasons


def check(candidates: list[dict], topic: str) -> list[dict]:
    """The candidates with `check`, `ok` and `reject_reasons`, usable ones first (best score first).
    Each candidate's wanted subject is its `query` (or `subject`)."""
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = [clip.get("frames") or [f.result() for f in [pool.submit(_frame, u) for u in clip["preview_urls"][:3]]]
                  for clip in candidates]
    parts = [f"The case: {topic}. {len(candidates)} candidates, numbered from 0; each wants the subject given."]
    shown = set()
    for i, clip in enumerate(candidates):
        got = [f for f in frames[i] if f]
        if got:
            shown.add(i)
            kind = (f"archive film: \"{clip.get('title', '')}\"" + (f" ({clip['year']})" if clip.get("year") else "")
                    if clip.get("archive") else "stock footage")
            parts.append(f"Candidate {i} ({kind}), wanted subject: {clip.get('subject') or clip['query']}")
            parts.extend(("image/jpeg", f) for f in got)
    verdicts = {}
    if shown:
        answer = llm.generate_json(parts, CHECK_SCHEMA, system=CHECK_SYSTEM)
        for v in answer.get("candidates", []):
            if v.get("index") in shown:
                v["score"] = max(0, min(10, int(v.get("score", 0))))
                v["stop_power"] = max(0, min(10, int(v.get("stop_power", v["score"]))))
                verdicts[v["index"]] = v
    out = []
    for i, clip in enumerate(candidates):
        reasons = reject_reasons(verdicts.get(i), clip) if i in shown else ["no preview frames"]
        out.append({**clip, "check": verdicts.get(i), "ok": not reasons, "reject_reasons": reasons})
    return sorted(out, key=lambda c: (c["ok"], (c["check"] or {}).get("score", -1), (c["check"] or {}).get("stop_power", -1)),
                  reverse=True)


# --- files and credits ------------------------------------------------------------------

def path_for(clip: dict) -> Path:
    return tmp_path("footage", _file_name(clip["key"]) + ".mp4")


def download(clip: dict) -> Path:
    """The clip's file (downloaded once; again if .tmp was cleared)."""
    dest = path_for(clip)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    partial = dest.with_suffix(".part")
    if urlparse(clip["download_url"]).scheme != "https":
        raise ValueError(f"not a clip's web address: {clip['download_url'][:120]}")
    with requests.get(clip["download_url"], stream=True, timeout=60, headers={"User-Agent": "ezzy-case-studies/1.0"}) as resp:
        resp.raise_for_status()
        got = 0
        with open(partial, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                got += len(chunk)
                if got > MAX_DOWNLOAD:
                    break
                f.write(chunk)
    if got > MAX_DOWNLOAD:
        partial.unlink(missing_ok=True)
        raise ValueError(f"the clip is over {MAX_DOWNLOAD >> 20} MB; not downloaded")
    partial.replace(dest)
    return dest


def credit(clip: dict) -> str:
    if clip.get("source") == "NASA":
        return f"Footage: NASA - {clip['page_url']}"
    if clip.get("source") == "Internet Archive":
        year = f" ({clip['year']})" if clip.get("year") else ""
        return f"Film: \"{text_clean.no_links(clip['title'])}\"{year}, Internet Archive, public domain - {clip['page_url']}"
    return f"Video: {text_clean.no_links(clip['credit_name'])} ({clip['source']}) {clip.get('page_url') or ''}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--query", action="append", default=[], help="a stock footage search (repeat for more)")
    parser.add_argument("--archive", action="append", default=[], help="an archive film search (repeat for more)")
    parser.add_argument("--nasa", action="store_true", help="--archive searches NASA's videos instead")
    parser.add_argument("--history", action="store_true", help="a history case: archive film may show a period battle")
    parser.add_argument("--topic", default="a case study")
    parser.add_argument("--check", action="store_true", help="have Gemini check the candidates (one free call)")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not args.query and not args.archive:
        parser.error("give --query or --archive")
    try:
        clips = search(args.query) if args.query else []
        clips += [{**c, "combat_ok": args.history} for c in search_archive(args.archive, nasa=args.nasa)]
        if args.check:
            clips = check(clips, args.topic)
        for clip in clips:
            if args.download and clip.get("ok", True):
                clip["file"] = str(cut(clip) if clip.get("archive") else download(clip))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    for c in clips:
        verdict = c.get("check") or {}
        size = f"{c['width']}x{c['height']}" if c.get("width") else "archive"
        print(f"{'OK ' if c.get('ok', True) else 'NO '}{c['key'][:34]:<34} {size:>9} {c['duration']:>5.0f}s "
              f"'{c['query']}' {c.get('title', '')[:40]} | {verdict.get('shows', '')} {', '.join(c.get('reject_reasons', []))}")
    print(json.dumps([c.get("file") for c in clips if c.get("file")], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
