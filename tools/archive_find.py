"""
Real material for the Constructivist Montage look (your choice, 2026-11-04): archive film, photographs and documents about the case's
actual subject, with stock video only for gaps, never more than half.

  quick_check(brief)  a few free searches, no Gemini: is there enough to bother researching this topic? A topic with too little costs
                      only the Editor's one call.
  gather(brief, ...)  the material itself, in the shapes the rest of the system already reads:
                      images (photos and documents, I1...), archive (cuts of film, A1...), footage (stock, B1...).

Where it looks, and what it trusts (the style's own rules, tools/montage_render.py):
  - Wikimedia Commons: photographs and videos whose licence is public domain, CC0 or CC BY (research_fetch.licence_ok). CC BY-SA isn't used.
  - The Internet Archive: only collections known for public-domain film (footage.ARCHIVE_BASE) that also carry a public-domain mark. No
    licence, or any other collection, is refused: anyone can mark an upload "public domain".
  - NASA's own videos (footage.search_nasa).
  - Stock video (Pexels, Pixabay) only when real material runs short; it's printed in the same look and labelled STOCK on screen.

Everything from outside is untrusted: a title or an author only ever becomes words on screen or in a credit (cleaned here, and printed in
capitals by the renderer), and a file's name comes from our own numbering, never from outside. Web addresses go through
footage._film_url and research_fetch's own checks.

Gemini sees everything before it's used, twice: once to choose (from a contact sheet of each film), once on the very seconds chosen,
because a film can be fine in nine frames and show a child in the tenth. A child, gore, distress or anything off the subject is out, in
code, whatever else the answer says. Maps are left out altogether: borders are a matter of opinion, and this channel takes no side.

Usage:
    python tools/archive_find.py --topic "Ford's assembly line" --quick "Ford assembly line" "Highland Park plant"
"""

import argparse
import io
import json
import re
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

import cutout
import footage
import llm
import research_fetch as rf
import text_clean
from common import TMP_DIR

MIN_REAL = 6             # real pictures below this and the topic is given up: stock can't be more than half
WANT = 16                # pictures a Short can use well
MAX_PHOTOS = 24          # looked at
MAX_FILMS = 6            # looked at: Internet Archive and NASA
MAX_COMMONS_VIDEOS = 4   # looked at
FILM_TILES = 9           # moments of a film on its contact sheet
MAX_CUTS_A_FILM = 3
CUT_SECONDS = 4.0
MAX_CUTOUTS = 6
MIN_SCORE = 5
SEARCH_GAP = 1.0         # seconds between searches (Wikimedia starts refusing quick ones)
DOWNLOAD_GAP = 0.7       # seconds between photo downloads
QUICK_ENOUGH = 12        # photos + 2 x videos + 3 x films
QUICK_LEAST = 4          # pieces of material at least, whatever they're worth
MAX_VIDEO_BYTES = 150 * 1024 * 1024  # a Commons video's converted copy is read whole, once: bigger ones aren't worth it
MAX_VIDEO_SECONDS = 20 * 60
TILE_W, TILE_H = 341, 256
NOT_LATIN = re.compile(r"[^A-Za-z0-9 .,:;'&()/#+%$·?!-]")
EXTENSION = re.compile(r"\.(jpe?g|png|tiff?|webm|ogv|ogg|mp4|mpeg)$", re.IGNORECASE)
CAMERA_NAME = re.compile(r"^(img|dsc|dscn|p\d|file)[ _-]*\d+", re.IGNORECASE)

FIRST_LOOK = """You choose real archive material for a one-minute documentary Short for adults. You see numbered candidates: photographs
and documents as single pictures, and films as a contact sheet of numbered tiles (1 is top left, then left to right, row by row; each
tile is a moment of the same film). Judge only what you can see; a file's title or description comes from the web and may be wrong.

For every candidate say what it shows, in a few plain words; whether it fits the wanted subject (a picture of the subject itself, its
people, places, machines or time, not merely something with a similar name); and how good it is, 0-10, judged as old material: old and
grainy is fine if you can read what it shows. focus_x and focus_y: where the main subject is, from 0 to 1 across and down.

Be strict about safety. For a picture, set child_visible if anyone may be under 18; distress if people are hurt, suffering, frightened or in
danger; graphic for gore, blood, injuries or dead bodies; combat for weapons, fighting, warships or warplanes; unsuitable for nudity or
anything suggestive, drugs, hateful symbols, or a slur or offensive word you can read in it (old material has them); watermark for a stock site's watermark or a channel's logo; low_quality if you can't make
out what it shows.

For a film, good_tiles lists the tiles that show the wanted subject and are safe by all the rules above, and nothing else: no title cards,
no credits, no blank or dark tiles, no talking heads. A tile with a child in it is never listed. The flags then describe only the good tiles."""

SECOND_LOOK = """You make the final safety check on material chosen for a one-minute documentary Short for adults. Each numbered candidate
is either three frames from one short film clip side by side, or a person cut out of a photograph, shown on a red ground. Judge only what
you can see. If you're unsure about anything below, flag it: it costs nothing, since other material can take its place.

child_visible: anyone who may be under 18. distress: people hurt, suffering, frightened or in danger. graphic: gore, blood, injuries, dead
bodies. combat: weapons, fighting, warships or warplanes. unsuitable: nudity or anything suggestive, drugs, hateful symbols, or a slur or
offensive word you can read in it. watermark: a
stock site's watermark or a channel's logo. low_quality: you can't make out what it shows. fits: it shows the wanted subject.

For a clip, focus_x and focus_y give where the main subject is in the middle frame (0 to 1 across and down), and shows what it shows in a few
plain words. For a cut-out, clean_person is true only if it's one whole adult person with their head showing, a clean outline, and nothing
else attached: not a fragment, not two people joined, not an object."""

_FLAGS = {"child_visible": {"type": "boolean"}, "distress": {"type": "boolean"}, "graphic": {"type": "boolean"}, "combat": {"type": "boolean"},
          "unsuitable": {"type": "boolean"}, "watermark": {"type": "boolean"}, "low_quality": {"type": "boolean"}, "fits": {"type": "boolean"}}
FIRST_SCHEMA = {"type": "object", "properties": {"candidates": {"type": "array", "items": {"type": "object", "properties": {
    "index": {"type": "integer"}, "shows": {"type": "string"},
    "kind": {"type": "string", "enum": ["photograph", "document", "painting_or_drawing", "map", "logo_or_icon", "film"]}, **_FLAGS,
    "score": {"type": "integer"}, "focus_x": {"type": "number"}, "focus_y": {"type": "number"},
    "good_tiles": {"type": "array", "items": {"type": "integer"}}},
    "required": ["index", "shows", "kind", *_FLAGS, "score", "focus_x", "focus_y", "good_tiles"]}}}, "required": ["candidates"]}
SECOND_SCHEMA = {"type": "object", "properties": {"candidates": {"type": "array", "items": {"type": "object", "properties": {
    "index": {"type": "integer"}, "shows": {"type": "string"}, **_FLAGS, "clean_person": {"type": "boolean"},
    "focus_x": {"type": "number"}, "focus_y": {"type": "number"}},
    "required": ["index", "shows", *_FLAGS, "clean_person", "focus_x", "focus_y"]}}}, "required": ["candidates"]}


class NotEnoughMaterial(RuntimeError):
    """A topic without enough real material for this look: the Editor picks another."""


def _queries(brief: dict) -> list[str]:
    """What to search for: the Editor's archive searches, its photo subjects, then the topic. A search is short plain words."""
    wanted = [*(brief.get("archive") or []), *(brief.get("image_subjects") or []), brief.get("topic") or ""]
    out = []
    for query in wanted:
        query = " ".join(re.sub(r"[^\w\s'-]", " ", str(query)).split())[:60]
        if query and query.lower() not in (q.lower() for q in out):
            out.append(query)
    return out


def quick_check(brief: dict, progress=print) -> dict:
    """How much free material there seems to be for a brief, from searches alone (no Gemini, nothing downloaded):
    {"photos", "videos", "films", "enough", "unknown"}. If the searches themselves all fail, nobody knows: "enough" is then true and the
    real search decides later (a network blip shouldn't throw good topics away)."""
    queries = _queries(brief)
    photos, videos, films, errors, asked = set(), set(), set(), 0, 0
    nasa = brief.get("archive_source") == "nasa"
    for k, query in enumerate(queries[:4]):
        asked += 1
        try:
            photos |= {i["title"] for i in rf.commons_images(query, limit=30)}
        except Exception:
            errors += 1
        time.sleep(SEARCH_GAP)
        if k < 2:
            asked += 2
            try:
                videos |= {v["title"] for v in rf.commons_videos(query, limit=12)}
            except Exception:
                errors += 1
            time.sleep(SEARCH_GAP)
            try:
                films |= {f["key"] for f in (footage.search_nasa if nasa else footage.search_films)(query)}
            except Exception:
                errors += 1
    unknown = asked > 0 and errors == asked
    worth = len(photos) + 2 * len(videos) + 3 * len(films)
    enough = unknown or (worth >= QUICK_ENOUGH and len(photos) + len(videos) + len(films) >= QUICK_LEAST)
    progress(f"Free material for “{brief.get('topic')}”: {len(photos)} photos, {len(videos)} videos, {len(films)} archive films"
             + (" (the searches failed: the real search decides)" if unknown else ""))
    return {"photos": len(photos), "videos": len(videos), "films": len(films), "enough": enough, "unknown": unknown}


def on_screen(text: str, limit: int) -> str:
    """Outside words as they may appear on screen: Latin letters the print fonts have, no web addresses, no hashtags, capitals."""
    plain = unicodedata.normalize("NFKD", text_clean.no_links(str(text or "")).replace("·", " - ")).encode("ascii", "ignore").decode()
    plain = NOT_LATIN.sub(" ", EXTENSION.sub("", plain).replace("_", " "))
    plain = re.sub(r"\s+-\s+", " · ", plain)
    return text_clean.screen_text(plain, limit).upper().strip(" .,:;-")


def _photo_tag(image: dict, kind: str) -> str:
    title = on_screen(image.get("title"), 40)
    if CAMERA_NAME.match(title or ""):
        title = on_screen(image.get("author"), 30)
    return f"{'DOCUMENT' if kind == 'document' else 'PHOTO'} · {title}" if title else ("DOCUMENT" if kind == "document" else "PHOTO")


def _film_tag(clip: dict) -> str:
    title = on_screen(clip.get("title"), 32)
    year = f" {clip['year']}" if clip.get("year") else ""
    if clip.get("source") == "NASA":
        return f"FILM · NASA{year}"
    return f"FILM · {title}{year}" if title else f"FILM{year}"


def _film_credit(clip: dict) -> str:
    if clip.get("source") == "Wikimedia Commons":
        name = text_clean.no_links(str(clip.get("author") or "unknown author"))
        return f"Video: \"{text_clean.no_links(clip['title'])}\", {name}, {clip['licence']}, Wikimedia Commons - {clip['page_url']}"
    return footage.credit(clip)


def _sheet(frames: list[tuple[float, bytes]]) -> tuple[bytes, list[float]] | None:
    """A film's moments as one picture, three tiles a row, each numbered, so Gemini can say which it means."""
    if not frames:
        return None
    rows = (len(frames) + 2) // 3
    sheet = Image.new("RGB", (TILE_W * 3, TILE_H * rows), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    for k, (_, raw) in enumerate(frames):
        try:
            tile = Image.open(io.BytesIO(raw)).convert("RGB").resize((TILE_W - 4, TILE_H - 4), Image.BILINEAR)
        except OSError:
            continue
        x, y = k % 3 * TILE_W + 2, k // 3 * TILE_H + 2
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y, x + 34, y + 24), fill=(0, 0, 0))
        draw.text((x + 6, y + 5), str(k + 1), fill=(255, 255, 0))
    out = io.BytesIO()
    sheet.save(out, format="JPEG", quality=78)
    return out.getvalue(), [t for t, _ in frames]


def _whole_video(clip: dict, dest: Path) -> Path | None:
    """A Commons video's converted copy, read once in one go: Wikimedia refuses a script's many small reads after a handful (429 for ten
    minutes, 2026-11-04), so frames can't be read straight off its servers as they can off the Internet Archive's."""
    if dest.exists() and dest.stat().st_size:
        return dest
    if float(clip.get("duration") or 0) > MAX_VIDEO_SECONDS:
        return None
    part = dest.with_suffix(".part")
    try:
        got = 0
        with requests.get(footage._film_url(clip["url"]), stream=True, timeout=60, headers=footage.HEADERS) as resp:
            resp.raise_for_status()
            with open(part, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    got += len(chunk)
                    if got > MAX_VIDEO_BYTES:
                        raise ValueError("too big")
                    f.write(chunk)
    except (requests.RequestException, ValueError, OSError):
        part.unlink(missing_ok=True)
        return None
    part.replace(dest)
    return dest


def _local_frame(path: Path, at: float) -> bytes | None:
    """A frame of a video on this computer, as a small JPEG."""
    small = f"scale='if(gt(iw,ih),{footage.FRAME_SIZE},-2)':'if(gt(iw,ih),-2,{footage.FRAME_SIZE})',format=yuvj420p"
    try:
        raw = subprocess.run([footage._ffmpeg(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1", "-vf", small,
                              "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"], capture_output=True, timeout=60).stdout
    except subprocess.TimeoutExpired:
        return None
    return raw or None


def _film_moments(clip: dict, folder: Path | None = None) -> dict | None:
    """A candidate film with its address, its length and its contact sheet. Internet Archive and NASA films are read straight off the web
    (nothing else of them is downloaded); a Commons video is read whole, once."""
    local = None
    try:
        if clip.get("source") == "Wikimedia Commons":
            url, duration = clip["url"], float(clip["duration"])
            local = _whole_video(clip, (folder or Path(".")) / f"commons_{footage._file_name(clip['key'])[:60]}.webm") if folder else None
            if not local:
                return None
        else:
            found = (footage.nasa_file if clip.get("source") == "NASA" else footage.film_file)(clip["id"])
            if not found:
                return None
            url, duration = found["url"], float(found["duration"] or 0) or footage._probe(found["url"])
        footage._film_url(url)
    except Exception:
        return None
    if duration < CUT_SECONDS * 2:
        return None
    count = FILM_TILES if duration >= 40 else 3
    times = [duration * (0.06 + 0.88 * k / max(1, count - 1)) for k in range(count)]
    reader = (lambda at: _local_frame(local, at)) if local else (lambda at: footage._grab(url, at))
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = [(t, raw) for t, raw in zip(times, pool.map(reader, times)) if raw]
    made = _sheet(frames)
    if not made:
        return None
    return {**clip, "download_url": url, "duration": duration, "sheet": made[0], "tile_times": made[1], "local": str(local) if local else None}


def _find_moving(brief: dict, folder: Path, progress) -> list[dict]:
    """Candidate films: trusted archive film and NASA first, then Commons videos, each with its contact sheet."""
    queries = _queries(brief)
    nasa = brief.get("archive_source") == "nasa"
    films, seen = [], set()
    for query in queries[:3]:
        try:
            found = (footage.search_nasa if nasa else footage.search_films)(query, 6)
        except Exception as e:
            progress(f"Film search for {query!r} failed ({type(e).__name__})")
            continue
        for film in found:
            if film["key"] not in seen and len(films) < MAX_FILMS:
                seen.add(film["key"])
                films.append(film)
    commons = []
    for query in queries[:3]:
        try:
            found = rf.commons_videos(query, 6)
        except Exception as e:
            progress(f"Video search for {query!r} failed ({type(e).__name__})")
            found = []
        time.sleep(SEARCH_GAP)
        for video in found:
            key = f"commons:{video['title']}"
            if key not in seen and len(commons) < MAX_COMMONS_VIDEOS:
                seen.add(key)
                commons.append({**video, "key": key, "source": "Wikimedia Commons", "page_url": video["page"], "query": query, "year": None})
    candidates = films + commons
    if not candidates:
        return []
    progress(f"Reading frames from {len(candidates)} films")
    with ThreadPoolExecutor(max_workers=3) as pool:
        ready = [c for c in pool.map(lambda c: _film_moments(c, folder) if c.get("source") != "Wikimedia Commons" else None, candidates) if c]
    for video in commons:  # (one at a time, with a pause: it refuses scripts that hurry)
        made = _film_moments(video, folder)
        if made:
            ready.append(made)
        time.sleep(SEARCH_GAP)
    return ready


def _find_photos(brief: dict, folder: Path, progress) -> list[tuple[dict, Path]]:
    """Candidate photographs and documents, downloaded to look at."""
    seen, images = set(), []
    for query in _queries(brief)[:6]:
        try:
            found = rf.commons_images(query, limit=12)
        except Exception as e:
            progress(f"Photo search for {query!r} failed ({type(e).__name__})")
            found = []
        time.sleep(SEARCH_GAP)
        for image in found:
            if image["title"] not in seen and len(images) < MAX_PHOTOS:
                seen.add(image["title"])
                images.append(image)
    got = []
    for n, image in enumerate(images, start=1):
        path = rf.download_image(image, folder / f"candidate_{n}.jpg")
        if path:
            got.append((image, path))
        time.sleep(DOWNLOAD_GAP)
    return got


def _small(path: Path, side: int = 512) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=80)
    return out.getvalue()


def _bad(verdict: dict, combat_ok: bool) -> bool:
    """The hard rules, in code, whatever else the answer says."""
    if any(verdict.get(flag) for flag in ("child_visible", "distress", "graphic", "unsuitable", "watermark", "low_quality")):
        return True
    return bool(verdict.get("combat")) and not combat_ok


def _first_look(photos: list[tuple[dict, Path]], films: list[dict], brief: dict, progress) -> dict[int, dict]:
    """One Gemini look at every candidate: {its number: its verdict}. Photographs are numbered first, then films."""
    subject = f"{brief['topic']}: {brief.get('angle', '')}"
    parts = [f"The case: {subject}\nWanted subject: {subject}\n{len(photos) + len(films)} candidates, numbered from 0."]
    for n, (image, path) in enumerate(photos):
        parts += [f"Candidate {n} (picture). Its file's title: {image['title'][:90]}", ("image/jpeg", _small(path))]
    for k, film in enumerate(films):
        parts += [f"Candidate {len(photos) + k} (film, contact sheet of {len(film['tile_times'])} tiles). Its title: {str(film.get('title'))[:90]}",
                  ("image/jpeg", film["sheet"])]
    progress(f"Looking at {len(photos)} pictures and {len(films)} films")
    answer = llm.generate_json(parts, FIRST_SCHEMA, FIRST_LOOK)
    return {v["index"]: v for v in answer.get("candidates") or [] if isinstance(v.get("index"), int)}


def _film_frames(path: Path) -> list[np.ndarray]:
    """Three frames of a cut: near its start, its middle and near its end."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    for at in (0.06, 0.5, 0.94):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(count * at))
        ok, frame = cap.read()
        if ok:
            out.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    return out


def _strip(frames: list[np.ndarray]) -> bytes:
    """Frames side by side, as one picture."""
    tiles = [Image.fromarray(f).resize((TILE_W, TILE_H), Image.BILINEAR) for f in frames]
    strip = Image.new("RGB", (TILE_W * len(tiles), TILE_H))
    for k, tile in enumerate(tiles):
        strip.paste(tile, (k * TILE_W, 0))
    out = io.BytesIO()
    strip.save(out, format="JPEG", quality=80)
    return out.getvalue()


def _on_red(path: Path) -> bytes:
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
    ground = Image.new("RGBA", rgba.size, (213, 43, 30, 255))
    ground.alpha_composite(rgba)
    ground = ground.convert("RGB")
    ground.thumbnail((512, 512), Image.LANCZOS)
    out = io.BytesIO()
    ground.save(out, format="JPEG", quality=80)
    return out.getvalue()


def _second_look(cuts: list[dict], people: list[dict], brief: dict, progress) -> dict[int, dict]:
    """The final check of the very seconds and cut-outs chosen: {number: verdict}; cuts are numbered first, then the cut-outs."""
    subject = f"{brief['topic']}: {brief.get('angle', '')}"
    parts = [f"The case: {subject}\n{len(cuts) + len(people)} candidates, numbered from 0."]
    for n, cut in enumerate(cuts):
        parts += [f"Candidate {n} (three frames of one clip). Wanted subject: {subject}", ("image/jpeg", _strip(cut["frames"]))]
    for k, person in enumerate(people):
        parts += [f"Candidate {len(cuts) + k} (a person cut out of a photograph)", ("image/jpeg", _on_red(person["path"]))]
    progress(f"Final check of {len(cuts)} film clips and {len(people)} cut-outs")
    answer = llm.generate_json(parts, SECOND_SCHEMA, SECOND_LOOK)
    return {v["index"]: v for v in answer.get("candidates") or [] if isinstance(v.get("index"), int)}


def _focus(verdict: dict) -> list[float]:
    def one(key, default):
        try:
            return round(max(0.0, min(1.0, float(verdict.get(key)))), 3)
        except (TypeError, ValueError):
            return default
    return [one("focus_x", 0.5), one("focus_y", 0.45)]


def _good_times(film: dict, verdict: dict) -> list[float]:
    """The moments of a film to cut, from the tiles Gemini liked: spread out, at most MAX_CUTS_A_FILM."""
    times = film["tile_times"]
    tiles = sorted({int(t) for t in verdict.get("good_tiles") or [] if isinstance(t, (int, float)) and 1 <= int(t) <= len(times)})
    if len(tiles) > MAX_CUTS_A_FILM:
        step = (len(tiles) - 1) / (MAX_CUTS_A_FILM - 1)
        tiles = [tiles[round(k * step)] for k in range(MAX_CUTS_A_FILM)]
    return [times[t - 1] for t in tiles]


def _local_cut(film: dict, start: float) -> Path:
    """Seconds of a video already on this computer, as footage.cut makes them from the web."""
    from common import tmp_path

    dest = tmp_path("footage", f"{footage._file_name(film['key'])[:80]}_{int(start)}.mp4")
    if dest.exists() and dest.stat().st_size:
        return dest
    partial = dest.with_name(dest.stem + ".part.mp4")
    subprocess.run([footage._ffmpeg(), "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(film["local"]), "-t", f"{CUT_SECONDS:.2f}", "-an",
                    "-vf", "scale='trunc(min(1280,iw)/2)*2':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(partial)], check=True, capture_output=True, timeout=300)
    partial.replace(dest)
    return dest


def _try_cutout(source: Path, dest: Path) -> Path | None:
    try:
        return cutout.cut(source, dest)
    except Exception:  # no model, or a picture it can't read: this look works without cut-outs too
        return None


def _stock(brief: dict, want: int, progress) -> list[dict]:
    """Stock clips for the gaps: found, checked by Gemini like everything else, downloaded, and labelled."""
    import db

    if want <= 0:
        return []
    try:
        found = footage.search((brief.get("broll") or [brief["topic"]])[:4], exclude=db.used_clip_keys(), per_query=2, min_seconds=4)
    except RuntimeError as e:
        progress(f"No stock footage: {e}")
        return []
    if not found:
        return []
    progress(f"Real material is short: checking {len(found)} stock clips")
    try:
        checked = footage.check(found, f"{brief['topic']}: {brief.get('angle', '')}")
    except Exception as e:  # without the check, no clip is used (it might show a child)
        progress(f"Couldn't check the stock clips ({type(e).__name__})")
        return []
    clips = []
    for clip in checked:
        if not clip["ok"] or len(clips) >= want:
            continue
        try:
            path = footage.download(clip)
        except Exception as e:
            progress(f"Couldn't download {clip['key']} ({type(e).__name__})")
            continue
        clips.append({"id": f"B{len(clips) + 1}", "file": path.relative_to(TMP_DIR).as_posix(), "key": clip["key"], "source": clip["source"],
                      "query": clip["query"], "shows": clip["check"]["shows"][:120], "duration": clip["duration"],
                      "stop_power": clip["check"].get("stop_power", 0), "credit": footage.credit(clip), "page_url": clip["page_url"],
                      "download_url": clip["download_url"], "kind": "stock", "tag": f"STOCK · {str(clip['source']).upper()}", "focus": [0.5, 0.45]})
    return clips


def gather(brief: dict, folder: Path, combat_ok: bool = False, progress=print) -> dict:
    """The material for a case: {"images": [...], "archive": [...], "footage": [...]}. Raises NotEnoughMaterial if there's too little real
    material, so the Editor can pick another topic."""
    work = folder / "montage"
    work.mkdir(parents=True, exist_ok=True)
    photos = _find_photos(brief, work, progress)
    films = _find_moving(brief, work, progress)
    if not photos and not films:
        raise NotEnoughMaterial(f"no free photos or films of {brief['topic']}")
    verdicts = _first_look(photos, films, brief, progress)

    images, chosen_photos = [], []
    for n, (image, path) in enumerate(photos):
        v = verdicts.get(n)
        if not v or not v.get("fits") or _bad(v, combat_ok) or int(v.get("score") or 0) < MIN_SCORE or v.get("kind") in ("map", "logo_or_icon"):
            continue
        chosen_photos.append((int(v.get("score") or 0), image, path, v))
    chosen_photos.sort(key=lambda x: -x[0])
    for rank, (_, image, path, v) in enumerate(chosen_photos[:WANT], start=1):
        iid = f"I{rank}"
        final = path.with_name(f"{iid}.jpg")
        path.replace(final)
        kind = "document" if v.get("kind") == "document" else "photo"
        images.append({"id": iid, "file": final.relative_to(TMP_DIR).as_posix(), "url": image["url"], "page": image["page"],
                       "shows": " ".join(str(v.get("shows", "")).split())[:120], "title": image["title"], "author": image["author"],
                       "licence": image["licence"], "credit": image["credit"], "kind": kind, "tag": _photo_tag(image, kind),
                       "focus": _focus(v), "score": int(v.get("score") or 0)})
    for path in work.glob("candidate_*.jpg"):
        path.unlink(missing_ok=True)

    cuts = []
    for k, film in enumerate(films):
        v = verdicts.get(len(photos) + k)
        if not v or not v.get("fits") or int(v.get("score") or 0) < MIN_SCORE or v.get("kind") in ("map", "logo_or_icon"):
            continue
        if _bad(v, combat_ok):  # (the flags describe its good tiles)
            continue
        for at in _good_times(film, v):
            cuts.append({"film": film, "start": round(max(0.0, min(at - CUT_SECONDS / 2, film["duration"] - CUT_SECONDS)), 2),
                         "score": int(v.get("score") or 0), "shows": v.get("shows") or ""})
    cuts.sort(key=lambda c: -c["score"])

    def made(cut: dict) -> dict | None:
        try:
            path = _local_cut(cut["film"], cut["start"]) if cut["film"].get("local") else footage.cut(cut["film"], cut["start"], CUT_SECONDS)
            frames = _film_frames(path)
        except Exception as e:
            progress(f"Couldn't cut a film ({type(e).__name__})")
            return None
        return {**cut, "path": path, "frames": frames} if len(frames) >= 2 else None

    if cuts:
        progress(f"Cutting {len(cuts)} moments of film")
    with ThreadPoolExecutor(max_workers=3) as pool:
        cuts = [c for c in pool.map(made, cuts[:WANT]) if c]

    people = []
    for item in images:
        if len(people) >= MAX_CUTOUTS * 2:
            break
        dest = work / f"{item['id']}_cut.png"
        if item["kind"] == "photo" and _try_cutout(TMP_DIR / item["file"], dest):
            people.append({"owner": item, "path": dest})
    if len(people) < MAX_CUTOUTS:  # old film makes rough cut-outs, but they stand small in the tower
        for n, cut in enumerate(cuts):
            if len(people) >= MAX_CUTOUTS * 2 or len(cut["frames"]) < 2:
                continue
            still = work / f"film_{n}.png"
            Image.fromarray(cut["frames"][1]).save(still)
            dest = work / f"film_{n}_cut.png"
            if _try_cutout(still, dest):
                people.append({"owner": cut, "path": dest})
            still.unlink(missing_ok=True)

    archive = []
    if cuts or people:
        try:
            second = _second_look(cuts, people, brief, progress)
        except Exception as e:  # without the check, no film and no cut-out is used (they might show a child)
            progress(f"Couldn't make the final check ({type(e).__name__}): only checked photographs are used")
            second, cuts, people = {}, [], []
    else:
        second = {}
    kept = []
    for n, cut in enumerate(cuts):
        v = second.get(n)
        if not v or not v.get("fits") or _bad(v, combat_ok):
            continue
        cut["verdict"] = v
        kept.append(cut)
    for k, cut in enumerate(kept, start=1):
        film = cut["film"]
        item = {"id": f"A{k}", "file": cut["path"].relative_to(TMP_DIR).as_posix(), "key": film["key"], "source": film["source"],
                "title": film.get("title") or "", "year": film.get("year"), "shows": " ".join(str(cut["verdict"].get("shows") or cut["shows"]).split())[:120],
                "duration": CUT_SECONDS, "query": film.get("query"), "credit": _film_credit(film), "page_url": film.get("page_url"),
                "download_url": film["download_url"], "start": cut["start"], "seconds": CUT_SECONDS, "kind": "film", "tag": _film_tag(film),
                "focus": _focus(cut["verdict"]), "licence": film.get("licence") or "public domain"}
        cut["item"] = item
        archive.append(item)
    for path in work.glob("commons_*"):
        path.unlink(missing_ok=True)
    usable_people = 0
    for k, person in enumerate(people):
        v = second.get(len(cuts) + k)
        owner = person["owner"]
        owner = owner.get("item") if "film" in owner else owner
        if owner and v and v.get("clean_person") and not _bad(v, False) and usable_people < MAX_CUTOUTS and not owner.get("cutout"):
            owner["cutout"] = person["path"].relative_to(TMP_DIR).as_posix()
            usable_people += 1
        else:
            person["path"].unlink(missing_ok=True)
    real = len(images) + len(archive)
    if real < MIN_REAL:
        raise NotEnoughMaterial(f"only {real} real pictures of {brief['topic']} passed the checks (need {MIN_REAL})")
    clips = _stock(brief, min(real, WANT - real), progress)
    progress(f"Material: {len(archive)} moments of film, {len(images)} photos, {usable_people} cut-outs" + (f", {len(clips)} stock clips" if clips else ""))
    return {"images": images, "archive": archive, "footage": clips, "real": real, "stock": len(clips), "cutouts": usable_people}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--topic", required=True)
    parser.add_argument("--quick", nargs="*", default=[])
    args = parser.parse_args()
    brief = {"topic": args.topic, "image_subjects": args.quick, "archive": [], "archive_source": "film"}
    try:
        print(json.dumps(quick_check(brief)))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
