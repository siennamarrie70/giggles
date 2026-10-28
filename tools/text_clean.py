"""
Cleaning rules for everything the Writer's text turns into: words spoken and shown on screen,
and YouTube's title, description, hashtags and tags.

  screen_text()  on-screen and spoken text: no emoji (the caption font can't draw them), no hashtags
  title()        at most 100 characters, no hashtags, no < or > (YouTube rejects them)
  hashtags()     #lowercase_words, the channel's own ones added, no duplicates
  tags()         search keywords, 450 characters in all at most (YouTube's limit is 500)
  no_links()     text without web addresses; linkable() whether a source's address may be linked

Only a source the Researcher read is linked in a description, and only if its address is an ordinary
page at a named site (linkable): web pages are untrusted, and a page's title, a Writer's words shaped
by it or a credit's name could otherwise put any link on the channel (2026-10-28).

Usage:
    python tools/text_clean.py --text "Hello 👋 #shorts there"
"""

import argparse
import re
import sys
from urllib.parse import urlparse

EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")
END_EMOJI = re.compile("\\s*([\U0001F000-\U0001FFFF☀-➿]\uFE0F?)\\s*([?!.])$")  # an emoji just before the last ? ! or .
HASHTAG_WORD = re.compile(r"#\w+")
LINK = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.)\S+")
SITE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z][a-z0-9-]+")
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly",
              "shorturl.at", "rb.gy", "t.ly", "tiny.cc", "s.id", "lnkd.in")


def screen_text(text: str, limit: int) -> str:
    """No emoji, no hashtags, cut at a word boundary."""
    text = " ".join(EMOJI.sub("", HASHTAG_WORD.sub("", text or "")).split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return text


def no_brackets(text: str) -> str:
    """YouTube rejects < and > in titles and descriptions; keep the heart in "<3"."""
    return text.replace("<3", "❤").replace("<", "").replace(">", "")


def no_links(text: str) -> str:
    """The text without web addresses ("https://...", "www...")."""
    return " ".join(LINK.sub("", text or "").split())


def linkable(url: str) -> bool:
    """Whether a source's address may be linked: an http(s) page at a named site, not a bare IP address, a login in
    the address, an odd port or a link shortener (which could lead anywhere)."""
    try:
        parts = urlparse(url or "")
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or parts.username or parts.password or port not in (None, 80, 443):
        return False
    if not SITE.fullmatch(host) or re.search(r"[\s<>\"]", url):
        return False
    return not any(host == s or host.endswith("." + s) for s in SHORTENERS)


def title(text: str, fallback: str = "") -> str:
    text = " ".join(no_brackets(HASHTAG_WORD.sub("", text or "")).split())
    text = END_EMOJI.sub(r"\2 \1", text)  # "empire 📱?" -> "empire? 📱"
    return re.sub(r"\s+([?!.,:;])", r"\1", text)[:100] or fallback[:100]


def hashtag(tag: str) -> str | None:
    tag = re.sub(r"[^0-9a-z_]", "", str(tag).lower().lstrip("#"))
    return f"#{tag}" if tag else None


def hashtags(raw: list[str], base: list[str], limit: int = 5) -> list[str]:
    out = []
    for tag in list(raw)[:limit] + list(base):
        tag = hashtag(tag)
        if tag and tag not in out:
            out.append(tag)
    return out


def tags(raw: list[str]) -> list[str]:
    out, length = [], 0
    for tag in raw:
        tag = " ".join(no_brackets(str(tag)).replace(",", " ").split())
        if tag and tag.lower() not in {t.lower() for t in out} and length + len(tag) + 3 <= 450:
            out.append(tag)
            length += len(tag) + 3
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    print(screen_text(args.text, 200))
    return 0


if __name__ == "__main__":
    sys.exit(main())
