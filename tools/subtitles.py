"""
Subtitles: the narrator's words on screen, burned into the film and its short version (your request, 2026-11-17).

Each line of the script is cut into as few cues of whole words as fit their place (split: broken after a full stop or a
comma where it can, as evenly as can be, never a word left alone), each shown while he says it: timed by his
reading itself (tools/narration.py hears every word's time; tools/narrator.py keeps each line's, and where its own sound
was cut from the reading), or, with no reading yet, spread over the line by its letters. A line's cues stay inside its
shot: they never run over a cut.

Where they go (tools/silhouette_render.py draws them, in the look's type): the film's in the black letterbox band under
its picture, one row, so they never cover it; the short version's low in its picture, at most two rows on a soft dark
halo, above the title and the buttons YouTube and Instagram lay over the bottom of a Short. The closing line isn't
subtitled: it's on screen in big type as he says it.
"""

import re

LEAD = 0.08        # seconds a cue comes on before its first word
HOLD = 0.10        # ...and a line's last one stays after his line's sound (its cut ends just after his last word)
SHORTEST = 0.30    # seconds a cue stays at the least, when the word times crowd it
CLEAR = 0.04       # a line's cues are gone this long before its shot cuts away
BREAK = re.compile(r"[,;:.!?…—–][\"”’)\]]*$")   # a word a cue may end on (its sentence breathes there)
STOP = re.compile(r"[.!?…][\"”’)\]]*$")          # ...best of all
OPENS = {"and", "but", "or", "so", "yet", "because", "while", "when", "where", "which", "who", "that", "until", "before",
         "after", "if", "though", "although", "as", "of", "to", "in", "into", "on", "at", "for", "with", "from", "without",
         "through", "than", "like", "instead", "the", "a", "an", "his", "her", "their", "its", "my", "your", "our", "this",
         "these", "those", "every", "each", "all", "no", "some", "he", "she", "they", "we", "i", "you",
         "it"}   # words a phrase starts with: a cue may begin on one
BINDS = {"the", "a", "an", "his", "her", "their", "its", "my", "your", "our", "this", "these", "those", "of", "to", "in",
         "into", "on", "at", "for", "with", "from", "by", "and", "but", "or", "he", "she", "they", "i", "we", "you", "was",
         "were", "is", "are", "had", "has", "have", "be", "been", "could", "would", "will", "can", "not",
         "very"}             # words that hold on to the next one: a cue never ends on one if it can help it


def split(text: str, fits) -> list[str]:
    """A line's words cut into as few cues as fit (fits(text) -> bool), or one more when that breaks it better: each
    break after a full stop if it can, else a comma, as evenly as can be, never a word alone."""
    words = str(text or "").split()
    n = len(words)
    if n <= 1 or fits(" ".join(words)):
        return [" ".join(words)] if words else []
    known = {}

    def fit(i, j):
        if (i, j) not in known:
            known[(i, j)] = fits(" ".join(words[i:j]))
        return known[(i, j)]
    ends = [0]
    for w in words:
        ends.append(ends[-1] + len(w) + 1)

    def letters(i, j):
        return ends[j] - ends[i] - 1

    def after(j):   # (what a break after word j costs: nothing after a full stop, a little after a comma, more inside a
        w = words[j - 1]   # phrase, most after a word that holds on to the next: "the / seat")
        if STOP.search(w):
            return 0.0
        if BREAK.search(w):
            return 0.25
        if _bare(w) in BINDS:
            return 2.2
        return 0.6 if _bare(words[j]) in OPENS else 1.5
    fewest, i = 0, 0   # (the fewest cues: as many words in each as fit)
    while i < n:
        j = i + 1
        while j < n and fit(i, j + 1):
            j += 1
        fewest, i = fewest + 1, j
    best = None
    for m in (fewest, fewest + 1):
        even = letters(0, n) / m
        cost = [[None] * (m + 1) for _ in range(n + 1)]
        cost[0][0] = (0.0, None)
        for c in range(1, m + 1):
            for j in range(1, n + 1):
                for i in range(j - 1, -1, -1):
                    if not fit(i, j):
                        break   # (more words won't fit either)
                    if cost[i][c - 1] is None:
                        continue
                    v = (cost[i][c - 1][0] + ((letters(i, j) - even) / even) ** 2 + (after(j) if j < n else 0.0)
                         + (1.5 if j - i == 1 else 0.0))
                    if cost[j][c] is None or v < cost[j][c][0]:
                        cost[j][c] = (v, i)
        if cost[n][m] is None:
            continue
        total = cost[n][m][0] + (0.6 if m > fewest else 0.0)
        if best is None or total < best[0]:
            cuts, j = [], n
            for c in range(m, 0, -1):
                i = cost[j][c][1]
                cuts.append(" ".join(words[i:j]))
                j = i
            best = (total, cuts[::-1])
    return best[1] if best else [" ".join(words)]


def timed(cues: list[str], start: float, end: float, words: list[float] | None = None) -> list[tuple[float, float]]:
    """Each cue's (on, off) in a line said from `start` to `end` (seconds): on just before its first word (words: every
    word's second, in the line's order; else spread by the cues' letters), off when the next comes on, the last at end."""
    counts = [len(c.split()) for c in cues]
    if words and len(words) == sum(counts):
        ons, k = [], 0
        for n in counts:
            ons.append(words[k] - LEAD)
            k += n
        ons[0] = start
    else:
        letters = [max(1, len(c)) for c in cues]
        ons = [start + (end - start) * sum(letters[:i]) / sum(letters) for i in range(len(cues))]
    for i in range(1, len(ons)):   # (in order, each on screen a moment at least, the last before the end)
        ons[i] = max(ons[i], ons[i - 1] + SHORTEST)
    for i in range(len(ons) - 1, 0, -1):
        ons[i] = min(ons[i], (ons[i + 1] if i + 1 < len(ons) else end) - SHORTEST)
    if any(b <= a for a, b in zip(ons, ons[1:] + [end])):   # (a line too short for its cues: shared evenly)
        ons = [start + (end - start) * i / len(cues) for i in range(len(cues))]
    return [(ons[i], ons[i + 1] if i + 1 < len(ons) else end) for i in range(len(ons))]


def _bare(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower().replace("’", "'"))


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", str(text or "").lower().replace("’", "'")).split())


def word_seconds(voice: dict | None, at: float, count: int) -> list[float] | None:
    """Every word's second in the film from the narrator's line as placed in it (voice: {"words": [[second in his
    reading, word], ...], "from": the second of his reading its own sound was cut from}; at: where it starts)."""
    if not voice or voice.get("from") is None or len(voice.get("words") or []) != count:
        return None
    return [at + float(w[0]) - float(voice["from"]) for w in voice["words"]]


def cues(shots: list[dict], times: list[dict], voice: list[dict] | None, fits, closing: str = "") -> list[dict]:
    """The subtitles of a film or its short version: [{"shot": k, "on", "off", "text", "first", "last"}] in its seconds
    (first/last: the line's first and last cue). times: tools/story_film.timeline's. voice: the narrator's lines as
    placed in it ({"at", "seconds", "words", "from"}: story_film.voice_cues), or None (no reading yet: estimated)."""
    placed = {round(float(v["at"]), 2): v for v in voice or []}
    out = []
    for k, (shot, t) in enumerate(zip(shots, times)):
        text = " ".join(str(shot.get("line") or "").split())
        if t.get("line_at") is None or not text:
            continue
        if k == len(shots) - 1 and closing and _plain(text) == _plain(closing):
            continue   # (the closing line: on screen in big type as he says it)
        start = float(t["line_at"])
        v = placed.get(round(start, 2))
        said = float((v or {}).get("seconds") or t.get("line_seconds") or 0.0)
        end = max(start + SHORTEST, min(start + said + HOLD, float(t["start"]) + float(t["seconds"]) - CLEAR))
        parts = split(text, fits)
        spans = timed(parts, start, end, word_seconds(v, start, len(text.split())))
        for i, (cue, (on, off)) in enumerate(zip(parts, spans)):
            out.append({"shot": k, "on": round(on, 3), "off": round(off, 3), "text": cue, "first": i == 0,
                        "last": i == len(parts) - 1})
    return out
