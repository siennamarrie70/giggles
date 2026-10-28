"""
Agent 2, Researcher: gathers what's known about the Editor's topic from free sources and turns it
into a research pack for the Writer: checked facts and the story they tell, data, real photos and
real footage.

1. Fetch (tools/research_fetch.py): the brief's Wikipedia articles (or the best search hits), news
   articles for this week's events and the economy (news sites' feeds, GDELT and the links in
   Wikipedia's Current events), the data series the brief asks for (IMF, World Bank) and photos from
   Wikimedia Commons whose licence allows reuse.
2. Gemini reads the numbered sources, and only those, and lists facts: each a short claim, its source
   and the exact words from that source that support it; plus a timeline, big numbers, who's who and
   the story: the most surprising fact to open on, the decisions real people made, and the twist.
3. Code checks every fact: its quote must really be in that source, and every number in the claim
   must be in the quote. The rest are dropped (the dashboard shows how many), and so is any part of
   the story that rested on them. Code adds facts it calculates from the data series itself: the
   change over the years, the IMF's expected growth and how long that takes to double an economy.
4. Gemini looks at the candidate photos and keeps relevant ones without children, gore, logos or
   walls of text, with their credits; each kept photo gets its depth map (tools/depth.py), so it can
   move like a camera passing it.
5. Footage (tools/footage.py): stock clips for the brief's b-roll searches and, when the brief asks,
   archive film of the real thing (public-domain films, newsreels and adverts, or NASA's), all
   checked from their frames in one Gemini request (never a child, nothing graphic; see footage.py),
   then downloaded (archive film: only the seconds around its best frame). Clips the channel has
   used before are skipped. In the drawn look (settings look.style) there are no clips to find: every
   line plays over a drawing, so this step is skipped (minutes and 50-150 MB a case saved). While
   Cloudflare can't draw, a case is made with real footage instead (look.when_out; draw.style_now()),
   so its clips are found; the pack says which look it was researched for (pack["look"]), and
   add_footage() finds the clips of one researched for drawings that's made with footage after all.

A case fails (the Editor then picks another topic) with fewer than MIN_CHECKED facts checked against the
sources, or fewer than MIN_FACTS counting the calculated ones.

Usage:
    python -m agents.researcher --topic "Nokia's phone business" --angle "Why did Nokia lose the phone market?"
        [--category business] [--wiki Nokia "Nokia Lumia"] [--data gdp_growth --countries FIN]
"""

import argparse
import difflib
import io
import json
import math
import re
import shutil
import statistics
import sys
import unicodedata
from pathlib import Path

from PIL import Image

import db
import depth
import draw
import footage
import infographics
import llm
import research_fetch as rf
from agents.base import act, lessons_for, log, taught
from common import TMP_DIR, load_config, tmp_path

MIN_FACTS = 6
MIN_CHECKED = 4  # of them from the sources themselves, not calculated
MAX_FACTS = 30
WIKI_PAGES = 3
WIKI_CHARS, NEWS_CHARS = 9000, 4000
NEWS_FOR = {"trending", "economy", "technology"}
COMBAT_OK = {"history", "dark_history", "mythology"}  # period battles (and paintings of legendary ones), no gore
MAX_CANDIDATES, MAX_IMAGES = 12, 8
FACT_KINDS = ["background", "turning_point", "cause", "effect", "number", "forecast", "reaction", "story"]
BROLL_SEARCHES, PER_SEARCH = 8, 2   # stock candidates: per search, before the check
MAX_FOOTAGE, MAX_ARCHIVE = 10, 4    # clips kept

QUOTE_SWAPS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
SMALL = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
# "one" and "zero" aren't counted: as words they're rarely numbers ("one of the largest")
SPELLED = re.compile(r"\b(" + "|".join(list(TENS) + SMALL[2:]) + r")(?:[- ](" + "|".join(SMALL[1:10]) + r"))?\b")

PACK_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "description": "15 to 30, the most useful for the case first", "items": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "one plain sentence, at most 30 words"},
                "source": {"type": "string", "description": "the id of the source it comes from, e.g. S2"},
                "quote": {"type": "string", "description": "the exact words from that source that support the claim, "
                                                           "copied character for character: 10 to 60 words"},
                "kind": {"type": "string", "enum": FACT_KINDS},
            },
            "required": ["claim", "source", "quote", "kind"]}},
        "timeline": {"type": "array", "description": "up to 6 dated turning points, oldest first", "items": {
            "type": "object",
            "properties": {"when": {"type": "string", "description": "a year or date, as short as possible"},
                           "event": {"type": "string", "description": "at most 8 words"},
                           "fact": {"type": "integer", "description": "the number (1, 2, ...) of the fact it comes from"}},
            "required": ["when", "event", "fact"]}},
        "stats": {"type": "array", "description": "up to 4 striking numbers", "items": {
            "type": "object",
            "properties": {"value": {"type": "string", "description": "the number as shown on screen, e.g. 49% or $7.2 billion"},
                           "label": {"type": "string", "description": "what it means, at most 10 words"},
                           "fact": {"type": "integer", "description": "the number of the fact it comes from"}},
            "required": ["value", "label", "fact"]}},
        "people": {"type": "array", "items": {
            "type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
            "required": ["name", "role"]}},
        "answer": {"type": "string", "description": "2-3 sentences: what the sources say the answer to the case's "
                                                    "question is, and what they leave uncertain"},
        "story": {"type": "object", "description": "the case told as a mystery, from the facts above", "properties": {
            "paradox": {"type": "integer", "description": "the number of the most surprising fact: the case opens on it"},
            "decisions": {"type": "array", "description": "2 to 4 decisions real people made that drove the story, in "
                                                          "order", "items": {
                "type": "object",
                "properties": {"who": {"type": "string"}, "decision": {"type": "string", "description": "at most 15 words"},
                               "fact": {"type": "integer", "description": "the number of the fact it comes from"}},
                "required": ["who", "decision", "fact"]}},
            "twist": {"type": "integer", "description": "the number of the fact with the irony or twist that answers the "
                                                        "question"},
        }, "required": ["paradox", "decisions", "twist"]},
    },
    "required": ["facts", "timeline", "stats", "people", "answer", "story"],
}

IMAGES_SCHEMA = {
    "type": "object",
    "properties": {"images": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "shows": {"type": "string", "description": "what the photo shows, at most 10 words"},
            "relevant": {"type": "boolean", "description": "would it help tell this case?"},
            "children": {"type": "boolean", "description": "a child or teenager is visible"},
            "graphic": {"type": "boolean", "description": "gore, blood, injuries, dead bodies, people suffering"},
            "combat": {"type": "boolean", "description": "weapons, fighting, explosions, warships or warplanes"},
            "mostly_text_or_logo": {"type": "boolean"},
            "quality": {"type": "string", "enum": ["good", "ok", "poor"]},
        },
        "required": ["index", "shows", "relevant", "children", "graphic", "combat", "mostly_text_or_logo", "quality"]}}},
    "required": ["images"],
}


# --- checking -----------------------------------------------------------------

def normalize(text: str) -> str:
    """Lowercase words, numbers and %/$ only, without accents, so a quote and its source compare fairly
    (Karṇa and Karna are the same word)."""
    text = unicodedata.normalize("NFKD", (text or "").translate(QUOTE_SWAPS))
    text = re.sub(r"\[\d+\]", "", "".join(ch for ch in text if not unicodedata.combining(ch)).lower())
    return " ".join(re.sub(r"[^\w%$€£]+", " ", text).split())


def numbers_in(text: str, words: bool = True) -> set[str]:
    """The numbers in a text, written the same way: '1,200' and '1200' -> '1200', 'five' -> '5' (spelled
    numbers only with words=True)."""
    out = set()
    for raw in NUMBER.findall(text or ""):
        value = float(raw.replace(",", ""))
        out.add(str(int(value)) if value == int(value) else f"{value:g}")
    if not words:
        return out
    for tens_or_small, unit in SPELLED.findall((text or "").lower()):
        value = TENS.get(tens_or_small, SMALL.index(tens_or_small) if tens_or_small in SMALL else 0)
        out.add(str(value + (SMALL.index(unit) if unit else 0)))
    return out


def quote_found(quote: str, source: str) -> bool:
    """Is the quote really in the source text (both normalized)? Long quotes may differ slightly."""
    q = normalize(quote)
    if len(q) < 25:
        return False
    if q in source:
        return True
    if len(q) < 60:
        return False
    words = q.split()
    for anchor, from_end in ((" ".join(words[:3]), False), (" ".join(words[-3:]), True)):
        start = source.find(anchor)
        while start != -1:
            window = source[max(0, start + len(anchor) - len(q) - 10):start + len(anchor)] if from_end \
                else source[start:start + len(q) + 10]
            if difflib.SequenceMatcher(None, q, window).ratio() >= 0.9:
                return True
            start = source.find(anchor, start + 1)
    return False


def check_facts(raw: list[dict], texts: dict[str, str]) -> tuple[list[dict], dict[int, str]]:
    """The facts whose quote is in their source and whose numbers are all in the quote, renumbered
    F1, F2...; plus a map from the model's fact numbers (1-based) to the new ids."""
    normalized = {sid: normalize(t) for sid, t in texts.items()}
    kept, ids = [], {}
    for n, fact in enumerate(raw[:MAX_FACTS], start=1):
        claim = " ".join(str(fact.get("claim", "")).split())[:240]
        quote = " ".join(str(fact.get("quote", "")).split())[:600]
        sid = str(fact.get("source", "")).strip().upper()
        if not claim or sid not in normalized or not quote_found(quote, normalized[sid]):
            continue
        if not numbers_in(claim, words=False) <= numbers_in(quote):
            continue
        fid = f"F{len(kept) + 1}"
        ids[n] = fid
        kept.append({"id": fid, "claim": claim, "source": sid, "quote": quote,
                     "kind": fact.get("kind") if fact.get("kind") in FACT_KINDS else "background"})
    return kept, ids


# --- calculated facts -----------------------------------------------------------

def _amount(v: float, unit: str) -> str:
    if unit == "$ billion":
        return f"${v:,.0f} billion" if v >= 10 else f"${v:,.1f} billion"
    if unit == "$":
        return f"${v:,.0f}"
    if unit == "people":
        return f"{v / 1e6:,.0f} million people" if v >= 1e6 else f"{v:,.0f} people"
    if unit.startswith("%"):
        return f"{v:.1f}{unit}"
    return f"{v:,.1f} {unit}"


def calculated_facts(series: list[dict], start: int) -> list[dict]:
    """Facts code works out from the data itself: change over the last decade, the IMF's expected
    growth, doubling time at that pace, and where a forecast ends up."""
    facts = []

    def add(sid, claim, kind):
        facts.append({"id": f"F{start + len(facts)}", "claim": claim, "source": sid, "quote": claim, "kind": kind,
                      "calculated": True})
    for s in series:
        name = infographics.country_name(s["country"])
        what, unit, sid = s["title"].lower(), s["unit"], s["source_id"]
        forecast = s.get("forecast_from")
        actual = [p for p in s["points"] if forecast is None or p[0] < forecast]
        ahead = [p for p in s["points"] if forecast is not None and p[0] >= forecast]
        if len(actual) >= 2:
            (y0, v0), (y1, v1) = actual[max(0, len(actual) - 11)], actual[-1]
            add(sid, f"{name}'s {what} stood at {_amount(v0, unit)} in {y0} and at {_amount(v1, unit)} in {y1}.", "number")
        if len(ahead) >= 2 and unit == "%" and "growth" in what:
            avg = statistics.mean(v for _, v in ahead)
            add(sid, f"The IMF expects {name}'s economy to grow by about {avg:.1f}% a year from {ahead[0][0]} to "
                     f"{ahead[-1][0]}.", "forecast")
            if avg >= 0.5:
                years = math.log(2) / math.log(1 + avg / 100)
                add(sid, f"At about {avg:.1f}% a year, an economy doubles in size in about {years:.0f} years.", "forecast")
        elif ahead and unit != "%":
            add(sid, f"The IMF projects {name}'s {what} at {_amount(ahead[-1][1], unit)} in {ahead[-1][0]}.", "forecast")
    return facts


# --- the steps ----------------------------------------------------------------

def gather(brief: dict, progress=log) -> tuple[list[dict], dict[str, str], list[dict], list[str]]:
    """The numbered sources with their texts, the data series, and notes on what couldn't be read."""
    sources, texts, series, notes = [], {}, [], []

    def add(kind, title, url, text, publisher="", when=""):
        sid = f"S{len(sources) + 1}"
        sources.append({"id": sid, "kind": kind, "title": title, "url": url, "publisher": publisher, "date": when})
        texts[sid] = text
        return sid

    words = f"{brief['topic']} {brief.get('angle', '')}"
    titles = list(dict.fromkeys(t for t in brief.get("wiki_titles") or [] if t))[:WIKI_PAGES]
    pages = []
    for title in titles:
        page = rf.wiki_page(title)
        if not page:
            hit = next(iter(rf.wiki_search(title, 1)), None)
            page = rf.wiki_page(hit["title"]) if hit else None
        if page and page["title"] not in {p["title"] for p in pages}:
            pages.append(page)
    if len(pages) < 2:
        for hit in rf.wiki_search(words, 3):
            page = rf.wiki_page(hit["title"])
            if page and page["title"] not in {p["title"] for p in pages} and len(pages) < WIKI_PAGES:
                pages.append(page)
    for page in pages:
        add("wikipedia", page["title"], page["url"], rf.wiki_excerpt(page, words, WIKI_CHARS), "Wikipedia")
    progress(f"Read {len(pages)} Wikipedia article{'s' if len(pages) != 1 else ''}: " + ", ".join(p["title"] for p in pages))

    if brief.get("category") in NEWS_FOR or brief.get("why_now") == "trend":
        terms = (brief.get("search_terms") or [brief["topic"]])[0]
        event_links = []
        topic_words = {w for w in re.findall(r"[a-z]{4,}", words.lower())}
        for item in rf.current_events(7):
            if len(topic_words & set(re.findall(r"[a-z]{4,}", (item["text"] + " " + " ".join(item["topics"])).lower()))) >= 2:
                event_links += [link["url"] for link in item["links"]]
        found = rf.news(terms, days=21, max_articles=4, extra_urls=event_links[:6])
        if found["error"]:
            notes.append(found["error"])
        for a in found["articles"]:
            add("news", a["title"] or a["site"], a["url"], rf.clip(a["text"], NEWS_CHARS), a["site"], a["date"])
        progress(f"Read {len(found['articles'])} news article{'s' if len(found['articles']) != 1 else ''}")

    for key in [k for k in brief.get("data_needs") or [] if k in rf.DATA][:2]:
        for s in rf.data_series(key, brief.get("countries") or [])[:3]:
            text = " | ".join(f"{y}: {v:g}" for y, v in s["points"])
            if s.get("forecast_from"):
                text += f" (values from {s['forecast_from']} on are IMF forecasts)"
            label = f"{s['title']} ({s['unit']}), {s['country']}"
            s["source_id"] = add("data", label, s["url"], text, s["source"])
            series.append(s)
    if series:
        progress(f"Fetched {len(series)} data series")
    return sources, texts, series, notes


def _thumb(path: Path) -> bytes:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((512, 512))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return buf.getvalue()


def find_images(brief: dict, pages: list[str], folder: Path, progress=log) -> list[dict]:
    """Up to MAX_IMAGES checked photos, saved in the case's folder, with their credits."""
    share_alike = bool((load_config().get("research") or {}).get("share_alike_images"))
    candidates, seen = [], set()
    for name in pages:
        image = rf.commons_file(name, share_alike) if name else None
        if image and image["title"] not in seen:
            seen.add(image["title"])
            candidates.append(image)
    for subject in (brief.get("image_subjects") or [])[:6]:
        try:
            found = rf.commons_images(subject, limit=3, share_alike=share_alike)
        except Exception as e:  # one search failing (Commons rate-limits now and then) skips that subject
            progress(f"Photo search for {subject!r} failed: {e}")
            continue
        for image in found:
            if image["title"] not in seen and len(candidates) < MAX_CANDIDATES:
                seen.add(image["title"])
                candidates.append(image)
    downloaded = []
    for n, image in enumerate(candidates, start=1):
        path = rf.download_image(image, folder / f"candidate_{n}.jpg")
        if path:
            downloaded.append((image, path))
    if not downloaded:
        return []
    parts = [f"Case: {brief['topic']}. Question: {brief.get('angle', '')}\n"
             "Look at each numbered photo and say what it shows and whether it's usable."]
    for n, (image, path) in enumerate(downloaded, start=1):
        parts += [f"Photo {n}: {image['title']} ({image['description'] or 'no description'})", ("image/jpeg", _thumb(path))]
    progress(f"Checking {len(downloaded)} photos")
    try:
        verdicts = llm.generate_json(parts, IMAGES_SCHEMA, "You check photos for a YouTube channel's case-study videos. "
                                     "Be strict: a photo with any child or teenager in it, anything graphic (gore, "
                                     "injuries, the dead, people suffering), or one that's mostly text, a logo or a chart "
                                     "is not usable. Say whether it shows combat (weapons, fighting, warships, warplanes): "
                                     "history cases may show it without gore.").get("images") or []
    except Exception as e:  # without the check, no photo is used (it might show a child)
        progress(f"Couldn't check the photos ({e}); the case will use footage and graphics")
        verdicts = []
    kept = []
    for v in verdicts:
        n = v.get("index")
        if not isinstance(n, int) or not 1 <= n <= len(downloaded) or len(kept) >= MAX_IMAGES:
            continue
        if not v.get("relevant") or v.get("children") or v.get("graphic") or v.get("mostly_text_or_logo") \
                or v.get("quality") == "poor" or (v.get("combat") and brief.get("category") not in COMBAT_OK):
            continue
        image, path = downloaded[n - 1]
        iid = f"I{len(kept) + 1}"
        final = path.with_name(f"{iid}.jpg")
        shutil.move(str(path), final)
        kept.append({"id": iid, "file": final.relative_to(TMP_DIR).as_posix(), "url": image["url"], "page": image["page"],
                     "shows": " ".join(str(v.get("shows", "")).split())[:120], "title": image["title"],
                     "author": image["author"], "licence": image["licence"], "credit": image["credit"]})
    for path in folder.glob("candidate_*.jpg"):
        path.unlink()
    return kept


def image_path(image: dict) -> Path:
    """Where a pack's photo is on disk (downloaded again if .tmp was cleared)."""
    path = TMP_DIR / image["file"]
    if not path.exists():
        rf.download_image(image, path)
    return path


def add_depth(images: list[dict], progress=log) -> None:
    """Each photo's depth map, made now (cached next to the photo) so the render doesn't wait for it."""
    for image in images:
        try:
            depth.depth_map(image_path(image))
            image["depth"] = True
        except Exception as e:  # without depth the photo just glides in
            progress(f"No depth for {image['id']} ({type(e).__name__})")
            image["depth"] = False


def find_footage(brief: dict, progress=log) -> tuple[list[dict], list[dict]]:
    """Checked stock clips (B1, B2...) for the brief's b-roll searches, and archive film (A1, A2...) when it asks for
    it: one Gemini check for all of them, then the files (archive film: just the seconds around its best frame)."""
    used = db.used_clip_keys()
    searches = (brief.get("broll") or [brief["topic"]])[:BROLL_SEARCHES]
    try:
        stock = footage.search(searches, exclude=used, per_query=PER_SEARCH,  # longer clips once short ones kept running out
                               min_seconds=float(lessons_for("researcher")["settings"].get("min_clip_seconds") or 4))
    except RuntimeError as e:  # no stock footage key
        progress(f"No stock footage: {e}")
        stock = []
    archive = []
    if brief.get("archive") and brief.get("archive_source") in ("film", "nasa"):
        progress(f"Looking for archive film: {', '.join(brief['archive'])}")
        archive = [{**c, "combat_ok": brief.get("category") in COMBAT_OK}
                   for c in footage.search_archive(brief["archive"], exclude=used, nasa=brief["archive_source"] == "nasa",
                                                   per_query=footage.ARCHIVE_PER_QUERY)]
    if not stock and not archive:
        return [], []
    progress(f"Checking {len(stock)} stock clips" + (f" and {len(archive)} archive films" if archive else ""))
    try:
        checked = footage.check(stock + archive, f"{brief['topic']}: {brief.get('angle', '')}")
    except Exception as e:  # without the check, no clip is used (it might show a child)
        progress(f"Couldn't check the footage ({e}); the case will use photos and graphics")
        return [], []
    clips, films, per_search = [], [], {}
    for clip in checked:
        if not clip["ok"]:
            continue
        if clip.get("archive"):
            if len(films) >= MAX_ARCHIVE:
                continue
            start = footage.cut_start(clip)
            try:
                path = footage.cut(clip, start)
            except Exception as e:
                progress(f"Couldn't cut {clip['key']} ({type(e).__name__})")
                continue
            films.append({"id": f"A{len(films) + 1}", "file": path.relative_to(TMP_DIR).as_posix(), "key": clip["key"],
                          "source": clip["source"], "title": clip["title"], "year": clip.get("year"),
                          "shows": clip["check"]["shows"][:120], "duration": footage.CUT_SECONDS, "query": clip["query"],
                          "credit": footage.credit(clip), "page_url": clip["page_url"],
                          "download_url": clip["download_url"], "start": start})
            continue
        if len(clips) >= MAX_FOOTAGE or per_search.get(clip["query"], 0) >= PER_SEARCH:
            continue
        try:
            path = footage.download(clip)
        except Exception as e:
            progress(f"Couldn't download {clip['key']} ({type(e).__name__})")
            continue
        per_search[clip["query"]] = per_search.get(clip["query"], 0) + 1
        clips.append({"id": f"B{len(clips) + 1}", "file": path.relative_to(TMP_DIR).as_posix(), "key": clip["key"],
                      "source": clip["source"], "query": clip["query"], "shows": clip["check"]["shows"][:120],
                      "duration": clip["duration"], "stop_power": clip["check"].get("stop_power", 0),
                      "credit": footage.credit(clip), "page_url": clip["page_url"], "download_url": clip["download_url"]})
    return clips, films


def add_footage(brief: dict, pack: dict, progress=log) -> None:
    """The clips of a case researched for drawings (none were looked for) that's made with real footage after all
    (Cloudflare can't draw): found now, into its pack."""
    if pack.get("look") == "footage" or pack.get("footage") or pack.get("archive"):
        return  # (its clips were looked for: researched for footage, or before packs said which)
    clips, films = find_footage(brief, progress)
    progress(f"{len(clips)} stock clips" + (f" and {len(films)} archive films" if films else "") + " to use instead")
    pack.update(footage=clips, archive=films, look="footage")


def clip_path(item: dict) -> Path:
    """Where a pack's clip is on disk (fetched again if .tmp was cleared)."""
    path = TMP_DIR / item["file"]
    if not path.exists():
        if item.get("start") is not None:
            return footage.cut(item, item["start"])
        return footage.download(item)
    return path


def research(brief: dict, folder: Path, progress=log) -> dict:
    """The research pack for a brief; raises if the sources don't support enough facts."""
    folder.mkdir(parents=True, exist_ok=True)
    sources, texts, series, notes = gather(brief, progress)
    if not sources:
        raise RuntimeError(f"found nothing to read about {brief['topic']}")
    numbered = "\n\n---\n\n".join(f"{s['id']} ({s['kind']}: {s['title']}{', ' + s['publisher'] if s['publisher'] else ''}"
                                  f"{', ' + s['date'] if s['date'] else ''})\n{texts[s['id']]}" for s in sources)
    system = """You are the researcher for a YouTube channel of short case studies told as mysteries. You read the numbered
sources and list 15 to 30 facts from them that help answer the case's question, from every source that has
something useful (not just the first). Use only these sources: never add anything
from memory, even if you know it. Every fact quotes, character for character, the words in its source that support it
(10 to 60 words, one or two sentences). Every number in a claim must appear in its quote exactly as the source writes
it; never round, convert or combine numbers. Prefer surprising facts, turning points, the decisions people made and
why, causes, effects, ironies and striking numbers over background. Keep each claim neutral and attributed when it's
an opinion or a forecast ('analysts say', 'the IMF expects'). For myths and legends, say it's what the story tells
('in the Mahabharata, ...'). Then the story, from those facts only: the most surprising fact to open on, the decisions
real people made that drove it, and the twist that answers the question."""
    prompt = (f"Case type: {brief.get('category', '')}\nTopic: {brief['topic']}\n"
              + (f"The paradox it opens on (the Editor's guess; use the facts): {brief['paradox']}\n" if brief.get("paradox") else "")
              + f"The case's question: {brief.get('angle', '')}\n\n"
              f"Sources:\n\n{numbered}\n\n" + taught("researcher")
              + "List the facts, the timeline, the striking numbers, the people and the story.")
    progress("Reading the sources and listing the facts")
    raw = llm.generate_json([prompt], PACK_SCHEMA, system)
    facts, ids = check_facts(raw.get("facts") or [], texts)
    dropped = len((raw.get("facts") or [])[:MAX_FACTS]) - len(facts)
    by_id = {f["id"]: f for f in facts}
    timeline = []
    for item in (raw.get("timeline") or [])[:6]:
        fid = ids.get(item.get("fact"))
        when = " ".join(str(item.get("when", "")).split())[:20]
        if fid and when and numbers_in(when, words=False) <= numbers_in(by_id[fid]["quote"]):
            timeline.append({"when": when, "event": " ".join(str(item.get("event", "")).split())[:70], "fact": fid})
    stats = []
    for item in (raw.get("stats") or [])[:4]:
        fid = ids.get(item.get("fact"))
        value = " ".join(str(item.get("value", "")).split())[:16]
        if fid and value and numbers_in(value, words=False) and numbers_in(value, words=False) <= numbers_in(by_id[fid]["quote"]):
            stats.append({"id": f"N{len(stats) + 1}", "value": value,
                          "label": " ".join(str(item.get("label", "")).split())[:80], "fact": fid})
    raw_story = raw.get("story") or {}
    story = {"paradox": ids.get(raw_story.get("paradox")), "twist": ids.get(raw_story.get("twist")),
             "decisions": [{"who": " ".join(str(d.get("who", "")).split())[:60],
                            "decision": " ".join(str(d.get("decision", "")).split())[:120], "fact": ids[d.get("fact")]}
                           for d in (raw_story.get("decisions") or [])[:4] if ids.get(d.get("fact")) and d.get("who")]}
    checked = len(facts)
    facts += calculated_facts(series, len(facts) + 1)
    if checked < MIN_CHECKED or len(facts) < MIN_FACTS:
        raise RuntimeError(f"only {checked} facts about {brief['topic']} could be checked against the sources "
                           f"(need {MIN_CHECKED}, and {MIN_FACTS} with the data)")
    progress(f"{len(facts)} facts checked against the sources ({dropped} dropped)")
    lead_images = [(rf.wiki_page(s["title"]) or {}).get("image") for s in sources if s["kind"] == "wikipedia"]
    images = find_images(brief, lead_images, folder, progress)
    add_depth(images, progress)
    progress(f"{len(images)} photos to use")
    look = draw.style_now()
    if look == "drawn":  # every line plays over a drawing: no clips to find
        clips, films = [], []
        progress("The drawn look: no stock or archive clips needed")
    else:
        if draw.style() == "drawn":
            progress("Cloudflare can't draw now: this case is made with real footage")
        clips, films = find_footage(brief, progress)
        progress(f"{len(clips)} stock clips" + (f" and {len(films)} archive films" if films else "") + " to use")
    pack = {
        "look": look,
        "folder": folder.relative_to(TMP_DIR).as_posix(),
        "sources": sources, "facts": facts, "timeline": timeline, "stats": stats,
        "series": [{"id": f"D{n}", **{k: s[k] for k in ("key", "country", "title", "unit", "points", "source", "url",
                                                        "forecast_from", "source_id")}}
                   for n, s in enumerate(series, start=1)],
        "images": images, "footage": clips, "archive": films,
        "people": [{"name": " ".join(str(p.get("name", "")).split())[:60], "role": " ".join(str(p.get("role", "")).split())[:80]}
                   for p in (raw.get("people") or [])[:8] if p.get("name")],
        "answer": " ".join(str(raw.get("answer", "")).split())[:600],
        "story": story,
        "dropped": dropped, "notes": notes,
    }
    return {"pack": pack, "facts": len(facts), "dropped": dropped, "sources": len(sources), "images": len(images),
            "footage": len(clips), "archive": len(films)}


def run(brief: dict, folder: Path, progress=log) -> dict:
    return act("researcher", f"Research: {brief['topic']}", research, brief, folder, progress=progress)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--topic", required=True)
    parser.add_argument("--angle", default="")
    parser.add_argument("--category", default="business")
    parser.add_argument("--wiki", nargs="*", default=[])
    parser.add_argument("--search", nargs="*", default=[])
    parser.add_argument("--images", nargs="*", default=[])
    parser.add_argument("--data", nargs="*", default=[])
    parser.add_argument("--countries", nargs="*", default=[])
    parser.add_argument("--broll", nargs="*", default=[], help="stock footage searches")
    parser.add_argument("--archive", nargs="*", default=[], help="archive film searches")
    parser.add_argument("--nasa", action="store_true", help="--archive searches NASA's videos")
    args = parser.parse_args()
    brief = {"topic": args.topic, "angle": args.angle, "category": args.category, "wiki_titles": args.wiki,
             "search_terms": args.search, "image_subjects": args.images or [args.topic], "data_needs": args.data,
             "countries": args.countries, "broll": args.broll or [args.topic], "archive": args.archive,
             "archive_source": ("nasa" if args.nasa else "film") if args.archive else "none"}
    folder = tmp_path("research", "manual", "x").parent
    try:
        result = run(brief, folder)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result["pack"], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
