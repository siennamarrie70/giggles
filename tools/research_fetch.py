"""
Agent 2's fetchers: what the internet says about a topic, from free sources that need no key.

  wiki_search(query)            Wikipedia article titles for a search
  wiki_page(title)              an article's plain text by section, its URL and its lead image
  wiki_excerpt(page, words)     the lead plus the sections that matter most for these words
  current_events(days)          Wikipedia's Current events portal: each item with its news links
  on_this_day(day)              Wikipedia's "On this day" events for a date (history ideas)
  news(terms, days)             recent English news articles (news sites' RSS feeds, GDELT) with their text
  article(url)                  one web page's main text (trafilatura)
  data_series(key, countries)   yearly numbers from the IMF (with its forecasts) or the World Bank
  commons_images(query)         Wikimedia Commons photos whose licence allows reuse, with credits
  download_image(image, dest)   one of those photos, checked to be a real image

Answers are cached in .tmp/research/cache (a day for news, a week for the rest), so re-runs don't
ask the same thing twice. Wikimedia asks API clients for a descriptive User-Agent. GDELT allows one
request every few seconds and often answers 429 anyway (2026-10-25), so the news sites' own RSS
feeds come first and GDELT is a best-effort extra.

A news link can point anywhere (GDELT and the feeds list whatever was published, and anyone can edit
Wikipedia's Current events portal), so article() reads only ordinary public sites (2026-10-28): each
connection is checked once it's made, before anything is sent, and one to this computer, a home or
office network or a cloud's own addresses (169.254.169.254) is dropped, even when a public name or a
redirect leads there; at most MAX_PAGE bytes are read, for at most PAGE_SECONDS. A photo is taken
only from Wikimedia's own servers (IMAGE_HOSTS), at most MAX_IMAGE bytes; a feed that declares XML
entities (which can make a small file expand without end) is skipped.

Usage:
    python tools/research_fetch.py wiki "Nokia"
    python tools/research_fetch.py search "Nokia decline smartphones"
    python tools/research_fetch.py events [--days 3]
    python tools/research_fetch.py onthisday [--date 2026-10-25]
    python tools/research_fetch.py news "tariffs" [--days 14]
    python tools/research_fetch.py data gdp_growth IND USA
    python tools/research_fetch.py images "Nokia 3310"
"""

import argparse
import hashlib
import html
import ipaddress
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError

from common import tmp_path

USER_AGENT = "ezzy-case-studies/1.0 (research for a YouTube channel of case-study Shorts)"
# The IMF's firewall refuses that one (and browser-like ones) but lets known clients through, while
# Wikimedia refuses bare library agents: so each gets its own.
IMF_AGENT = f"python-requests/{requests.__version__} ezzy-case-studies/1.0"
PAGE_AGENT = "Mozilla/5.0 (compatible; ezzy-case-studies/1.0; reading articles to cite them)"
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
IMF_API = "https://www.imf.org/external/datamapper/api/v1"
WORLDBANK_API = "https://api.worldbank.org/v2"
TIMEOUT = 20
GDELT_SPACING = 6.0  # seconds between GDELT requests
DAY, WEEK = timedelta(days=1), timedelta(days=7)

SKIP_SECTIONS = {"see also", "references", "external links", "further reading", "notes", "bibliography",
                 "sources", "gallery", "citations", "footnotes", "explanatory notes", "works cited"}
SKIP_DOMAINS = ("youtube.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "tiktok.com", "reddit.com",
                "pinterest.", "linkedin.com", "wikipedia.org")
MIN_ARTICLE = 800
MAX_PAGE = 5 * 1024 * 1024  # bytes of an article's page (they're 50 KB-2 MB)
PAGE_SECONDS = 45  # to read one page, all of it
IMAGE_HOSTS = ("upload.wikimedia.org",)
MAX_IMAGE = 40 * 1024 * 1024  # bytes (a Commons photo at 1280 px is under 1 MB; an original can be 30)
FEEDS = [  # news sites' public RSS feeds, searched for the topic's words
    "https://feeds.bbci.co.uk/news/business/rss.xml", "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml", "https://www.theguardian.com/uk/business/rss",
    "https://www.theguardian.com/world/rss", "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.npr.org/1001/rss.xml", "https://feeds.npr.org/1006/rss.xml",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html", "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "https://www.france24.com/en/rss", "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    "https://www.livemint.com/rss/news",
]
STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "what", "when", "why", "how", "does", "will", "into",
             "after", "over", "about", "its", "his", "her", "their", "are", "was", "were", "has", "have", "who"}

# The data the Editor can ask for: key -> (source, code, what it is, unit)
DATA = {
    "gdp_growth": ("imf", "NGDP_RPCH", "Real GDP growth", "%"),
    "gdp": ("imf", "NGDPD", "GDP", "$ billion"),
    "gdp_per_person": ("imf", "NGDPDPC", "GDP per person", "$"),
    "inflation": ("imf", "PCPIPCH", "Inflation", "%"),
    "unemployment": ("imf", "LUR", "Unemployment", "%"),
    "government_debt": ("imf", "GGXWDG_NGDP", "Government debt", "% of GDP"),
    "share_of_world_economy": ("imf", "PPPSH", "Share of the world economy", "%"),
    "tariff_rate": ("worldbank", "TM.TAX.MRCH.WM.AR.ZS", "Average tariff on imports", "%"),
    "exports": ("worldbank", "NE.EXP.GNFS.ZS", "Exports", "% of GDP"),
    "imports": ("worldbank", "NE.IMP.GNFS.ZS", "Imports", "% of GDP"),
    "population": ("worldbank", "SP.POP.TOTL", "Population", "people"),
}
SOURCE_NAMES = {"imf": "IMF World Economic Outlook", "worldbank": "World Bank, World Development Indicators"}

# Licences we can reuse in a video: public domain, CC0 and CC BY. Share-alike ones (CC BY-SA, the Free
# Art Licence) arguably make the whole video share-alike, so they're only used when allowed.
FREE = re.compile(r"^(public domain|pd\b|pd-|cc0|cc[ -]by[ -]\d|cc[ -]by$|attribution$)", re.I)
SHARE_ALIKE = re.compile(r"^(cc[ -]by[ -]sa|fal\b|free art)", re.I)
NOT_FREE = re.compile(r"\b(nc|nd|non[- ]?commercial|no ?deriv|fair use|non-free)\b", re.I)
NOT_PHOTOS = re.compile(r"\b(logo|wordmark|icon|seal|coat of arms|emblem|signature|screenshot)\b", re.I)

_session = None
_pages_session = None
_gdelt_lock = threading.Lock()
_gdelt_last = 0.0


def _http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = USER_AGENT
    return _session


def is_public(address: str) -> bool:
    """Whether an IP address is on the public internet: not this computer, a home or office network, or a
    cloud's own addresses."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class _PublicOnly:
    """A connection dropped as soon as it's made (before anything is sent) unless it reached a public address."""

    def _new_conn(self):
        sock = super()._new_conn()
        if not is_public(sock.getpeername()[0]):
            sock.close()
            raise NewConnectionError(self, f"{self.host} isn't a public site")
        return sock


class _PublicHTTP(_PublicOnly, HTTPConnection):
    pass


class _PublicHTTPS(_PublicOnly, HTTPSConnection):
    pass


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTP


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPS


class _PublicAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PublicHTTPPool, "https": _PublicHTTPSPool}


def _pages() -> requests.Session:
    """The session for pages from anywhere (article): public sites only, redirects included."""
    global _pages_session
    if _pages_session is None:
        session = requests.Session()
        session.trust_env = False  # (no proxy: the address checked must be the site's own)
        session.max_redirects = 5
        session.headers["User-Agent"] = PAGE_AGENT
        session.mount("http://", _PublicAdapter())
        session.mount("https://", _PublicAdapter())
        _pages_session = session
    return _pages_session


def _body(resp: requests.Response, limit: int, seconds: float) -> bytes | None:
    """A streamed answer's bytes; None if there are more than `limit` or they take longer than `seconds`."""
    body, until = bytearray(), time.monotonic() + seconds
    for chunk in resp.iter_content(1 << 16):
        body += chunk
        if len(body) > limit or time.monotonic() > until:
            return None
    return bytes(body)


def _cached(key: str, max_age: timedelta, fetch):
    """fetch()'s answer, reused for max_age. Failures aren't cached."""
    path = tmp_path("research", "cache", hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if datetime.now(timezone.utc) - datetime.fromisoformat(saved["at"]) < max_age:
                return saved["value"]
        except (ValueError, KeyError):
            pass
    value = fetch()
    path.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "value": value}), encoding="utf-8")
    return value


def _get_json(url: str, params: dict | None = None) -> dict | list:
    headers = {"User-Agent": IMF_AGENT} if url.startswith(IMF_API) else None
    for attempt in range(3):
        try:
            resp = _http().get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.ConnectionError:  # a dropped connection (Wikimedia, 2026-10-26): try again shortly
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code != 429 or attempt == 2:
            break
        wait = resp.headers.get("Retry-After", "")  # rate-limited: wait as asked (briefly), then try again
        time.sleep(min(float(wait) if wait.isdigit() else 3 * (attempt + 1), 10))
    resp.raise_for_status()
    return resp.json()


def strip_markup(text: str) -> str:
    """Plain text from a bit of HTML."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


# --- Wikipedia --------------------------------------------------------------

def wiki_search(query: str, limit: int = 5) -> list[dict]:
    def fetch():
        data = _get_json(WIKI_API, {"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                                    "srprop": "snippet", "format": "json", "formatversion": 2})
        return [{"title": r["title"], "snippet": strip_markup(r.get("snippet", ""))}
                for r in data.get("query", {}).get("search", [])]
    return _cached(f"wiki_search:{query}:{limit}", WEEK, fetch)


def wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))


def wiki_page(title: str) -> dict | None:
    """The article's sections as [(heading, text)], with its final title (after redirects), URL and lead
    image file; None if there's no such article."""
    def fetch():
        data = _get_json(WIKI_API, {"action": "query", "prop": "extracts|pageimages", "explaintext": 1,
                                    "exsectionformat": "wiki", "piprop": "name", "redirects": 1, "titles": title,
                                    "format": "json", "formatversion": 2})
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or not pages[0].get("extract"):
            return None
        page = pages[0]
        sections, heading, buf = [], "", []
        for line in page["extract"].splitlines():
            m = re.match(r"^(=+)\s*(.+?)\s*\1\s*$", line)
            if m:
                sections.append((heading, "\n".join(buf).strip()))
                heading, buf = m.group(2), []
            elif line.strip():
                buf.append(line.strip())
        sections.append((heading, "\n".join(buf).strip()))
        return {"title": page["title"], "url": wiki_url(page["title"]), "image": page.get("pageimage"),
                "sections": [s for s in sections if s[1]]}
    return _cached(f"wiki_page:{title}", WEEK, fetch)


def wiki_excerpt(page: dict, words: str, limit: int = 12000) -> str:
    """The lead and the sections that share the most words with `words`, in article order, up to limit."""
    keys = {w for w in re.findall(r"[a-z]{4,}", words.lower())}
    sections = [(h, t) for h, t in page["sections"] if h.lower() not in SKIP_SECTIONS]
    if not sections:
        return ""
    lead, rest = sections[0], sections[1:]
    scored = sorted(range(len(rest)), key=lambda i: -sum(rest[i][1].lower().count(k) + 3 * rest[i][0].lower().count(k)
                                                         for k in keys))
    chosen, size = set(), len(lead[1])
    for i in scored:
        if size + len(rest[i][1]) > limit:
            continue
        chosen.add(i)
        size += len(rest[i][1])
    parts = [lead[1]] + [f"{rest[i][0]}: {rest[i][1]}" for i in sorted(chosen)]
    return clip("\n\n".join(parts), limit)


def clip(text: str, limit: int) -> str:
    """At most limit characters, ending on a whole sentence (so nothing quoted from it stops mid-word)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(mark) for mark in (". ", ".\n", "! ", "? ", '." '))
    return cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0]


def _wikitext_plain(text: str) -> str:
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)      # [[a|b]] -> b
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", "", text)           # external links (kept separately)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"'{2,}", "", text)
    return " ".join(text.replace("()", "").split()).strip(" ;,")


def current_events(days: int = 3, today: date | None = None) -> list[dict]:
    """News items from Wikipedia's Current events portal for the last `days` days: date, section,
    the topics above the item, its text and its sources' links."""
    today = today or datetime.now(timezone.utc).date()
    items = []
    for back in range(days):
        day = today - timedelta(days=back)
        page = f"Portal:Current events/{day.year} {day:%B} {day.day}"

        def fetch(page=page):
            data = _get_json(WIKI_API, {"action": "parse", "page": page, "prop": "wikitext", "format": "json",
                                        "formatversion": 2})
            return (data.get("parse") or {}).get("wikitext") or ""
        try:
            wikitext = _cached(f"events:{page}", DAY / 4 if back == 0 else DAY, fetch)
        except requests.RequestException:
            continue
        section, parents = "", []
        for line in wikitext.splitlines():
            line = line.rstrip()
            m = re.match(r"^(?:'''|;)\s*(.+?)\s*(?:''')?$", line)
            if m and not line.startswith("*"):
                section = _wikitext_plain(m.group(1))
                parents = []
                continue
            m = re.match(r"^(\*+)\s*(.*)$", line)
            if not m:
                continue
            depth, body = len(m.group(1)), m.group(2)
            parents = parents[:depth - 1] + [_wikitext_plain(body)]
            links = [{"url": u, "outlet": _wikitext_plain(o).strip("() ")}
                     for u, o in re.findall(r"\[(https?://\S+)\s+([^\]]+)\]", body)]
            if links:
                items.append({"date": day.isoformat(), "section": section, "topics": [p for p in parents[:-1] if p],
                              "text": _wikitext_plain(body), "links": links})
    return items


def on_this_day(day: date | None = None, limit: int = 25, min_age: int = 30) -> list[dict]:
    """Events on this date at least min_age years ago (recent ones are too raw for a history case)."""
    day = day or datetime.now(timezone.utc).date()

    def fetch():
        data = _get_json(f"{WIKI_REST}/feed/onthisday/events/{day.month:02d}/{day.day:02d}")
        return [{"year": e.get("year"), "text": e.get("text", ""),
                 "pages": [p.get("normalizedtitle") or p.get("title") for p in e.get("pages", [])][:3]}
                for e in data.get("events", [])]
    events = _cached(f"onthisday:{day.month}-{day.day}", WEEK, fetch)
    return [e for e in events if isinstance(e["year"], int) and e["year"] <= day.year - min_age][:limit]


# --- news -------------------------------------------------------------------

def _gdelt(params: dict) -> dict:
    global _gdelt_last
    with _gdelt_lock:
        for attempt in range(2):
            wait = GDELT_SPACING - (time.monotonic() - _gdelt_last)
            if wait > 0:
                time.sleep(wait)
            _gdelt_last = time.monotonic()
            resp = _http().get(GDELT_API, params=params, timeout=TIMEOUT)
            if resp.status_code == 429 and attempt == 0:
                time.sleep(GDELT_SPACING * 2)
                continue
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:  # GDELT answers plain text for a query it doesn't like
                raise RuntimeError(f"GDELT: {resp.text[:200]}")
    raise RuntimeError("GDELT is rate-limiting; try again in a minute")


def _feed(url: str) -> list[dict]:
    def fetch():
        resp = _http().get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        if b"<!ENTITY" in resp.content[:3_000_000]:
            raise ValueError("the feed declares XML entities")
        root = ElementTree.fromstring(resp.content[:3_000_000])
        items = []
        for item in root.iter("item"):
            when = item.findtext("pubDate") or ""
            try:
                when = parsedate_to_datetime(when).astimezone(timezone.utc).isoformat() if when else ""
            except (TypeError, ValueError):
                when = ""
            items.append({"title": strip_markup(item.findtext("title") or ""), "url": (item.findtext("link") or "").strip(),
                          "summary": strip_markup(item.findtext("description") or "")[:400], "date": when})
        return items
    try:
        return _cached(f"feed:{url}", DAY / 12, fetch)
    except Exception:  # a feed that's down or moved is skipped
        return []


def feed_news(terms: str, days: int = 14, limit: int = 12) -> list[dict]:
    """Recent items from the news sites' feeds whose title or summary has most of the terms' words."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", terms.lower()) if w not in STOPWORDS}
    if not words:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = [i for feed in pool.map(_feed, FEEDS) for i in feed]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    need = max(1, round(len(words) * 0.5))
    scored, seen = [], set()
    for item in items:
        if item["url"] in seen:  # the same story in two of a site's feeds
            continue
        seen.add(item["url"])
        text = f"{item['title']} {item['summary']}".lower()
        score = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", text))
        fresh = not item["date"] or datetime.fromisoformat(item["date"]) >= since
        if score >= need and fresh and item["url"]:
            scored.append((score, item["date"], item))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)  # most matching words, then newest
    return [item for _, _, item in scored][:limit]


def _skip(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return not host or any(d in host for d in SKIP_DOMAINS)


def article(url: str) -> dict | None:
    """A page's main text, title, site and date; None if it can't be read, is too short or isn't on a public site."""
    import trafilatura

    def fetch():
        try:
            parts = urlparse(url)
            if parts.scheme not in ("http", "https") or parts.username or parts.password \
                    or parts.port not in (None, 80, 443):
                return None
            with _pages().get(url, timeout=TIMEOUT, stream=True) as resp:
                if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
                    return None
                page = _body(resp, MAX_PAGE, PAGE_SECONDS)
        except (requests.RequestException, ValueError):  # (ValueError: a malformed address)
            return None
        if not page:
            return None
        doc = trafilatura.bare_extraction(page, url=url, with_metadata=True, as_dict=True, include_comments=False,
                                          include_tables=False, favor_precision=True)
        text = (doc or {}).get("text") or ""
        if len(text) < MIN_ARTICLE:
            return None
        return {"url": url, "title": doc.get("title") or "", "site": doc.get("sitename") or urlparse(url).netloc,
                "date": doc.get("date") or "", "text": text}
    return _cached(f"article:{url}", WEEK, fetch)


def news(terms: str, days: int = 14, max_articles: int = 5, extra_urls: list[str] | None = None) -> dict:
    """Recent English articles about the terms, read in full: {"articles": [...], "error": str|None}.
    extra_urls (e.g. the Current events links) are read first."""
    found, error = [i["url"] for i in feed_news(terms, days)], None
    try:
        data = _cached(f"gdelt:{terms}:{days}", DAY / 4, lambda: _gdelt(
            {"query": f"{terms} sourcelang:english", "mode": "artlist", "maxrecords": 40, "format": "json",
             "timespan": f"{days}d", "sort": "hybridrel"}))
        found += [a.get("url") for a in data.get("articles", []) if a.get("url")]
    except Exception as e:  # GDELT is a best-effort extra
        error = f"GDELT: {e}"
    candidates, sites = [], set()
    for url in dict.fromkeys((extra_urls or []) + found):  # one article per site, in order
        site = urlparse(url).netloc.lower().removeprefix("www.")
        if not _skip(url) and site not in sites:
            candidates.append(url)
            sites.add(site)
    with ThreadPoolExecutor(max_workers=8) as pool:  # many sites are slow or refuse: ask several at once
        read = list(pool.map(article, candidates[:max_articles * 3]))
    return {"articles": [a for a in read if a][:max_articles], "error": error}


# --- data -------------------------------------------------------------------

def data_series(key: str, countries: list[str], first_year: int = 1995) -> list[dict]:
    """One series per country: {"key", "country", "title", "unit", "points": [[year, value]], "source",
    "url", "forecast_from"} (IMF series include the IMF's forecasts from this year on)."""
    source, code, what, unit = DATA[key]
    countries = [c.upper() for c in countries if re.fullmatch(r"[A-Za-z]{3}", c or "")][:4]
    if not countries:
        return []
    this_year = datetime.now(timezone.utc).year
    if source == "imf":
        def fetch():
            return _get_json(f"{IMF_API}/{code}/{'/'.join(countries)}")
        values = (_cached(f"imf:{code}:{','.join(countries)}", WEEK, fetch).get("values") or {}).get(code) or {}
        out = []
        for c in countries:
            points = sorted([int(y), round(float(v), 2)] for y, v in (values.get(c) or {}).items()
                            if v is not None and int(y) >= first_year)
            if points:
                out.append({"key": key, "country": c, "title": what, "unit": unit, "points": points,
                            "source": SOURCE_NAMES["imf"], "url": f"https://www.imf.org/external/datamapper/{code}",
                            "forecast_from": this_year})
        return out

    def fetch():
        return _get_json(f"{WORLDBANK_API}/country/{';'.join(countries)}/indicator/{code}",
                         {"format": "json", "date": f"{first_year}:{this_year}", "per_page": 2000})
    data = _cached(f"wb:{code}:{','.join(countries)}:{first_year}", WEEK, fetch)
    rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
    out = []
    for c in countries:
        points = sorted([int(r["date"]), round(float(r["value"]), 2)] for r in rows
                        if r.get("countryiso3code") == c and r.get("value") is not None)
        if points:
            out.append({"key": key, "country": c, "title": what, "unit": unit, "points": points,
                        "source": SOURCE_NAMES["worldbank"], "url": f"https://data.worldbank.org/indicator/{code}",
                        "forecast_from": None})
    return out


# --- photos -----------------------------------------------------------------

def licence_ok(name: str, share_alike: bool = False) -> bool:
    name = " ".join((name or "").split())
    if not name or NOT_FREE.search(name):
        return False
    return bool(FREE.match(name) or (share_alike and SHARE_ALIKE.match(name)))


def _image(info: dict, title: str, share_alike: bool) -> dict | None:
    meta = info.get("extmetadata") or {}
    licence = strip_markup((meta.get("LicenseShortName") or {}).get("value", ""))
    restrictions = (meta.get("Restrictions") or {}).get("value", "")
    if not licence_ok(licence, share_alike) or "trademark" in restrictions.lower():
        return None
    if info.get("mime") not in ("image/jpeg", "image/png") or max(info.get("width", 0), info.get("height", 0)) < 800:
        return None
    if NOT_PHOTOS.search(title):
        return None
    author = strip_markup((meta.get("Artist") or {}).get("value", "")) or "unknown author"
    author = re.sub(r"\s*\(talk\)\s*$", "", author)[:80]
    return {"title": title.removeprefix("File:"), "url": info.get("thumburl") or info.get("url"),
            "page": info.get("descriptionurl"), "width": info.get("width"), "height": info.get("height"),
            "licence": licence, "author": author,
            "description": strip_markup((meta.get("ImageDescription") or {}).get("value", ""))[:200],
            "credit": f"{author}, {licence}, via Wikimedia Commons"}


def commons_images(query: str, limit: int = 6, share_alike: bool = False) -> list[dict]:
    """Photos on Commons for a search whose licence we can reuse, best matches first."""
    def fetch():
        data = _get_json(COMMONS_API, {"action": "query", "generator": "search", "gsrnamespace": 6,
                                       "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 30,
                                       "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280,
                                       "format": "json", "formatversion": 2})
        pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
        return [{"title": p["title"], "info": (p.get("imageinfo") or [{}])[0]} for p in pages]
    found = []
    for item in _cached(f"commons:{query}", WEEK, fetch):
        image = _image(item["info"], item["title"], share_alike)
        if image:
            found.append(image)
        if len(found) >= limit:
            break
    return found


def commons_file(name: str, share_alike: bool = False) -> dict | None:
    """One Commons file by name (e.g. a Wikipedia article's lead image), if its licence allows reuse."""
    title = name if name.startswith("File:") else f"File:{name}"

    def fetch():
        data = _get_json(COMMONS_API, {"action": "query", "titles": title, "prop": "imageinfo",
                                       "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280, "format": "json",
                                       "formatversion": 2})
        pages = data.get("query", {}).get("pages", [])
        return {"title": pages[0]["title"], "info": pages[0]["imageinfo"][0]} if pages and pages[0].get("imageinfo") else None
    item = _cached(f"commons_file:{title}", WEEK, fetch)
    return _image(item["info"], item["title"], share_alike) if item else None


def download_image(image: dict, dest: Path) -> Path | None:
    """Saves a Commons photo as JPEG; None if it isn't a readable image, isn't on Wikimedia's servers or is huge."""
    try:
        parts = urlparse(image["url"])
        if parts.scheme != "https" or parts.hostname not in IMAGE_HOSTS:
            return None
        with _http().get(image["url"], timeout=TIMEOUT, stream=True) as resp:
            resp.raise_for_status()
            photo = _body(resp, MAX_IMAGE, 120)
        if not photo:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = dest.with_suffix(".download")
        raw.write_bytes(photo)
        with Image.open(raw) as img:
            img.convert("RGB").save(dest, "JPEG", quality=90)
        raw.unlink()
        return dest
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("what", choices=["wiki", "search", "events", "onthisday", "news", "data", "images"])
    parser.add_argument("args", nargs="*")
    parser.add_argument("--days", type=int)
    parser.add_argument("--date")
    args = parser.parse_args()
    try:
        if args.what == "wiki":
            page = wiki_page(" ".join(args.args))
            result = page and {**page, "sections": [(h, t[:200] + "...") for h, t in page["sections"]]}
        elif args.what == "search":
            result = wiki_search(" ".join(args.args))
        elif args.what == "events":
            result = current_events(args.days or 3)
        elif args.what == "onthisday":
            result = on_this_day(date.fromisoformat(args.date) if args.date else None)
        elif args.what == "news":
            got = news(" ".join(args.args), args.days or 14)
            result = {**got, "articles": [{**a, "text": a["text"][:300] + "..."} for a in got["articles"]]}
        elif args.what == "data":
            result = data_series(args.args[0], args.args[1:])
        else:
            result = commons_images(" ".join(args.args))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
