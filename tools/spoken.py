"""
Numbers as a narrator says them. The faceless look's scripts spell every number out ("nine thousand eight hundred
sixty", your Agent 3 prompt bans digits), while whisper usually hears digits and the research keeps them. So:

  words_for(text)      a number in digits as the words he'd say: "9,860" -> "nine thousand eight hundred sixty",
                       "1932" -> "nineteen thirty two", "2.5" -> "two point five", "%" -> "percent" (what
                       tools/narration.py matches what's heard against the script with)
  said_groups(text)    the numbers spoken in a script line, each as a set of its values: "ten billion dollars" ->
                       [{10000000000}], "nineteen thirty-two" -> [{1932}], "December tenth" -> [{10}]; "one" to "nine" with no
                       scale after them aren't numbers worth checking ("one company")
  unsupported(text, have)  those numbers that none of the values in `have` backs
  written_numbers(text) the numbers in a fact, as values, scale included: "$10 billion" -> {10, 10000000000}

Usage:
    python tools/spoken.py --text "nine thousand eight hundred sixty bullets"
"""

import argparse
import re
import sys

SMALL = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
            "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
            "fortieth": 40, "fiftieth": 50, "sixtieth": 60, "seventieth": 70, "eightieth": 80, "ninetieth": 90,
            "hundredth": 100, "thousandth": 1000}
UNIT = {w: n for n, w in enumerate(SMALL)}
NUMBER_WORDS = set(UNIT) | set(TENS) | set(SCALES) | {"hundred"} | set(ORDINALS)
WORD = re.compile(r"[a-z]+")
PHRASE = re.compile(r"[,.:;?!()]+(?:\s|$)")
DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion|bn|[kmb])\b)?", re.IGNORECASE)
SHORT_SCALE = {"k": 10 ** 3, "m": 10 ** 6, "b": 10 ** 9, "bn": 10 ** 9}
WORTH_CHECKING = 10  # spoken numbers below this with no scale after them are ordinary words ("one company")


def _under_thousand(n: int) -> list[str]:
    out = []
    if n >= 100:
        out += [SMALL[n // 100], "hundred"]
        n %= 100
    if n >= 20:
        out.append(next(w for w, v in TENS.items() if v == n // 10 * 10))
        n %= 10
    if n or not out:
        out.append(SMALL[n])
    return out


def whole_words(n: int) -> list[str]:
    """A whole number as words: 9860 -> nine thousand eight hundred sixty."""
    if n == 0:
        return ["zero"]
    out = []
    for name, size in sorted(SCALES.items(), key=lambda kv: -kv[1]):
        if n >= size:
            out += whole_words(n // size) + [name]
            n %= size
    return out + (_under_thousand(n) if n else [])


def year_words(n: int) -> list[str]:
    """A year as it's said: 1932 -> nineteen thirty two, 1900 -> nineteen hundred, 2008 -> two thousand eight,
    2024 -> twenty twenty four."""
    if 2000 <= n <= 2009:
        return whole_words(n)
    high, low = n // 100, n % 100
    if not low:
        return _under_thousand(high) + ["hundred"]
    return _under_thousand(high) + (["oh", SMALL[low]] if low < 10 else _under_thousand(low))


def words_for(number: str) -> list[str]:
    """Digits as the words he'd say, for matching speech with text."""
    raw = number.replace(",", "")
    whole, _, part = raw.partition(".")
    if part:
        return whole_words(int(whole)) + ["point"] + [SMALL[int(d)] for d in part]
    value = int(whole)
    return year_words(value) if "," not in number and 1100 <= value <= 2099 else whole_words(value)


def _parse_run(run: list[str]) -> list[tuple[float, bool]]:
    """Number words next to each other as values: [(value, has a scale or is big enough to matter)]."""
    if len(run) >= 2 and not set(run) & (set(SCALES) | {"hundred"}):  # a year: nineteen thirty two, twenty twelve
        first = UNIT.get(run[0]) or TENS.get(run[0]) or 0
        rest = run[1:]
        low = sum(UNIT.get(w) or TENS.get(w) or 0 for w in rest)
        if run[0] in TENS and len(run) == 2 and run[1] in UNIT and UNIT[run[1]] < 10:  # twenty five
            return [(TENS[run[0]] + UNIT[run[1]], True)]
        if 10 <= first <= 99 and 0 <= low <= 99:
            return [(first * 100 + low, True)]
    total, current, scaled = 0.0, 0.0, False
    for word in run:
        if word in UNIT:
            current += UNIT[word]
        elif word in TENS:
            current += TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
            scaled = True
        elif word in SCALES:
            total += (current or 1) * SCALES[word]
            current, scaled = 0.0, True
    value = total + current
    return [(value, scaled or value >= WORTH_CHECKING)]


def said_groups(text: str) -> list[set[float]]:
    """The numbers worth checking in a spoken line, each as a set of its values. A scale is part of the number: "fifty
    million" isn't backed by a fact's "50 km/h"."""
    out = []
    for part in PHRASE.split(text or ""):  # (numbers on either side of a comma or a colon are separate numbers)
        out += _phrase_numbers(WORD.findall(part.lower().replace("-", " ")))
    return out


def said_numbers(text: str) -> set[float]:
    """Every value the numbers in a spoken line could be written as."""
    return set().union(*said_groups(text))


def unsupported(text: str, have: set[float]) -> list[float]:
    """The numbers said in the text that none of `have` backs (each by its biggest form)."""
    return sorted(max(group) for group in said_groups(text) if not group & have)


def _phrase_numbers(tokens: list[str]) -> list[set[float]]:
    out, k = [], 0
    while k < len(tokens):
        word = tokens[k]
        if word in ORDINALS:
            if ORDINALS[word] >= WORTH_CHECKING:
                out.append({float(ORDINALS[word])})
            k += 1
            continue
        if word not in NUMBER_WORDS and not (word in ("a", "an") and k + 1 < len(tokens) and tokens[k + 1] in
                                             (set(SCALES) | {"hundred"})):
            k += 1
            continue
        run, j = [], k
        if word in ("a", "an"):
            j = k + 1
        while j < len(tokens) and (tokens[j] in UNIT or tokens[j] in TENS or tokens[j] in SCALES or tokens[j] == "hundred"
                                   or (tokens[j] == "and" and run and j + 1 < len(tokens) and tokens[j + 1] in NUMBER_WORDS)
                                   or (tokens[j] == "oh" and run and j + 1 < len(tokens) and tokens[j + 1] in UNIT)):
            if tokens[j] != "and":
                run.append(tokens[j])
            j += 1
        ordinal = 0
        if j < len(tokens) and tokens[j] in ORDINALS and ORDINALS[tokens[j]] < 100 and run and run[-1] in TENS:
            ordinal = ORDINALS[tokens[j]]  # thirty second
            j += 1
        if j < len(tokens) and tokens[j] == "point" and j + 1 < len(tokens) and tokens[j + 1] in UNIT:
            digits, m = [], j + 1
            while m < len(tokens) and tokens[m] in UNIT and UNIT[tokens[m]] < 10:
                digits.append(str(UNIT[tokens[m]]))
                m += 1
            whole = _parse_run(run)[0][0] if run else 0
            value = float(f"{int(whole)}.{''.join(digits)}")
            j = m
            if j < len(tokens) and tokens[j] in SCALES:
                value *= SCALES[tokens[j]]
                j += 1
            out.append({value})
            k = j
            continue
        for value, matters in _parse_run(run or ["one"]):
            value += ordinal
            if matters:
                out.append({float(value)})
        k = max(j, k + 1)
    return out


def written_numbers(text: str) -> set[float]:
    """The numbers in a fact's words, scale included: "$10 billion" -> {10, 10000000000}; spelled ones count as well."""
    out = set()
    for raw, scale in AMOUNT.findall(text or ""):
        value = float(raw.replace(",", ""))
        out.add(value)
        size = SCALES.get(scale.lower()) or SHORT_SCALE.get(scale.lower())
        if size:
            out.add(value * size)
    return out | said_numbers(AMOUNT.sub(" ", text or ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    print("said:", sorted(said_numbers(args.text)), "| written:", sorted(written_numbers(args.text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
