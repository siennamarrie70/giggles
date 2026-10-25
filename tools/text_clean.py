"""
Cleaning rules for everything the Writer's text turns into: words spoken and shown on screen,
and YouTube's title, description, hashtags and tags.

  screen_text()  on-screen and spoken text: no emoji (the caption font can't draw them), no hashtags
  title()        at most 100 characters, no hashtags, no < or > (YouTube rejects them)
  hashtags()     #lowercase_words, the channel's own ones added, no duplicates
  tags()         search keywords, 450 characters in all at most (YouTube's limit is 500)

Usage:
    python tools/text_clean.py --text "Hello 👋 #shorts there"
"""

import argparse
import re
import sys

EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")
HASHTAG_WORD = re.compile(r"#\w+")


def screen_text(text: str, limit: int) -> str:
    """No emoji, no hashtags, cut at a word boundary."""
    text = " ".join(EMOJI.sub("", HASHTAG_WORD.sub("", text or "")).split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return text


def no_brackets(text: str) -> str:
    """YouTube rejects < and > in titles and descriptions; keep the heart in "<3"."""
    return text.replace("<3", "❤").replace("<", "").replace(">", "")


def title(text: str, fallback: str = "") -> str:
    text = " ".join(no_brackets(HASHTAG_WORD.sub("", text or "")).split())
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
