"""
Agent 3, Writer: turns the brief and the research pack into the two hosts' script: 10 to 16 lines
of dialogue (the presenter tells the case, the co-host asks what viewers would ask), each with the
facts it relies on, the visual on screen, the shot and the hosts' emotions and actions; plus the
on-screen case title and YouTube's title, description and hashtags.

Everything is checked in code before it's kept: the speakers, the fact ids and the visuals must
exist; every number spoken must be in the facts the line cites; the script must fit max_seconds
(middle lines go) and not be too short (one rewrite). Then a fact-checker (a second Gemini call)
reads each line against its facts' source quotes: an overstated line is replaced by the checker's
fix, an unsupported one is cut, and more than three cuts means one rewrite. The dashboard shows each
line's mark.

Visuals are named, not drawn, here: "photo:I2", "chart:D1", "map", "map:CHN>USA", "timeline",
"stat:N1", "versus:N1,N2", "quote:F3", "list", "title" or "hosts". The Animator draws them from the
pack (visual_spec). apply_edits() takes the owner's edits from the dashboard through the same checks.

Usage:
    python -m agents.writer --pack pack.json --brief brief.json      # prints a script (nothing is saved)
"""

import argparse
import json
import re
import sys

import case_render
import character_spec as cs
import db
import infographics
import llm
import puppet
import short_render
import text_clean
from agents.base import act, advice, log
from agents.researcher import numbers_in
from common import load_config

MIN_LINES, MAX_LINES = 8, 16
WORDS = {0: 24, 1: 16}         # the most words per line: presenter, co-host (the prompt asks for 20 and 14)
QUOTE_CARDS, MAX_SAME = 3, 3   # quote cards on the menu; the most lines one kind of visual may have
WORDS_PER_SECOND = 2.3         # Kokoro's pace at speed 1.0 on case scripts (numbers and money take longer), 2026-10-25
MIN_SECONDS = 35
MAX_CUTS = 3
TITLE_CHARS = 32
HASHTAG_FOR = {"business": "#business", "economy": "#economics", "trending": "#news", "history": "#history",
               "mythology": "#mythology"}
VERDICTS = ["supported", "overstated", "unsupported", "not_a_claim"]


# --- visuals ------------------------------------------------------------------

def visual_menu(pack: dict, brief: dict) -> dict[str, str]:
    """The visuals a script can use for this case: name -> what it shows."""
    menu = {"hosts": "just the two hosts (the screen shows the case title)", "title": "the case title, big"}
    for image in pack.get("images") or []:
        menu[f"photo:{image['id']}"] = f"photo: {image['shows']}"
    for s in pack.get("series") or []:
        years = f"{s['points'][0][0]}-{s['points'][-1][0]}" if s["points"] else ""
        ahead = f", IMF forecasts from {s['forecast_from']}" if s.get("forecast_from") else ""
        menu[f"chart:{s['id']}"] = f"chart: {s['title']} ({s['unit']}), {s['country']}, {years}{ahead}"
    countries = brief.get("countries") or []
    if countries:
        menu["map"] = f"map with {', '.join(countries)} highlighted"
        for a in countries[:3]:
            for b in countries[:3]:
                if a != b:
                    menu[f"map:{a}>{b}"] = f"map with an arrow from {a} to {b} (trade, money, people moving)"
    if len(pack.get("timeline") or []) >= 2:
        menu["timeline"] = "timeline: " + "; ".join(f"{t['when']} {t['event']}" for t in pack["timeline"])
    stats = pack.get("stats") or []
    for s in stats:
        menu[f"stat:{s['id']}"] = f"big number: {s['value']} ({s['label']})"
    for i, a in enumerate(stats[:3]):
        for b in stats[i + 1:3]:
            menu[f"versus:{a['id']},{b['id']}"] = f"side by side: {a['value']} vs {b['value']}"
    quotable = sorted((f for f in pack.get("facts") or [] if not f.get("calculated") and len(f["quote"].split()) <= 28
                       and f["quote"].rstrip().endswith((".", "!", "?", '"', "”"))),  # whole sentences only
                      key=lambda f: (f["kind"] not in ("reaction", "number", "forecast"), len(f["quote"])))
    for f in quotable[:QUOTE_CARDS]:
        menu[f"quote:{f['id']}"] = f"the source's own words, on screen: \"{f['quote'][:90]}\""
    menu["list"] = "the 2-3 key points you write in key_points, numbered"
    return menu


def visual_spec(name: str, plan: dict) -> dict:
    """What tools/infographics.py draws for a visual's name (anything unknown: the case title)."""
    pack, script, brief = plan.get("research") or {}, plan.get("script") or {}, plan.get("brief") or {}
    kind, _, ref = (name or "title").partition(":")
    title_card = {"kind": "title", "kicker": case_render.CATEGORY_NAMES.get(brief.get("category"), ""),
                  "title": script.get("case_title") or brief.get("topic", "")}
    by_id = {x["id"]: x for key in ("images", "series", "stats", "facts") for x in pack.get(key) or []}
    sources = {s["id"]: s for s in pack.get("sources") or []}
    if kind == "photo" and ref in by_id:
        from agents.researcher import image_path
        image = by_id[ref]
        return {"kind": "photo", "path": str(image_path(image)), "credit": f"Photo: {image['author']}, {image['licence']}",
                "move": ("in", "left", "out", "right")[int(re.sub(r"\D", "", ref) or 0) % 4]}
    if kind == "chart" and ref in by_id:
        s = by_id[ref]
        return {"kind": "chart", "title": f"{s['title']}, {infographics.country_name(s['country'])}",
                "unit": "%" if s["unit"].startswith("%") else "",
                "points": s["points"][-16:], "forecast_from": s.get("forecast_from"), "source": s["source"]}
    if kind == "map":
        if ">" in ref:
            a, b = ref.split(">", 1)
            return {"kind": "map", "countries": [a, b], "arrows": [[a, b]]}
        return {"kind": "map", "countries": brief.get("countries") or []}
    if kind == "timeline" and pack.get("timeline"):
        return {"kind": "timeline", "events": [{"when": t["when"], "text": t["event"]} for t in pack["timeline"]]}
    if kind == "stat" and ref in by_id:
        return {"kind": "stat", "value": by_id[ref]["value"], "label": by_id[ref]["label"]}
    if kind == "versus" and "," in ref:
        a, b = (by_id.get(r) for r in ref.split(",", 1))
        if a and b:
            return {"kind": "versus", "left": {"title": a["label"][:40], "value": a["value"]},
                    "right": {"title": b["label"][:40], "value": b["value"]}}
    if kind == "quote" and ref in by_id:
        fact = by_id[ref]
        source = sources.get(fact["source"]) or {}
        return {"kind": "quote", "text": fact["quote"], "who": source.get("publisher") or source.get("title") or ""}
    if kind == "list" and script.get("key_points"):
        return {"kind": "list", "title": "", "items": script["key_points"]}
    return title_card


# --- checking -----------------------------------------------------------------

def _supported_numbers(fact_ids: list[str], pack: dict) -> set[str]:
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    out = set()
    for fid in fact_ids:
        if fid in by_id:
            out |= numbers_in(by_id[fid]["claim"]) | numbers_in(by_id[fid]["quote"])
    for s in pack.get("stats") or []:
        if s["fact"] in fact_ids:
            out |= numbers_in(s["value"])
    return out


def unsupported_numbers(line: dict, pack: dict, before: dict | None = None) -> set[str]:
    """Numbers in the line that neither its facts nor the line before it (an echo: "Wait, 40%?") back up."""
    facts = (line.get("facts") or []) + ((before or {}).get("facts") or [])
    return numbers_in(line["text"]) - _supported_numbers(facts, pack)


def clean_lines(raw: list[dict], hosts: list[dict], pack: dict, menu: dict) -> list[dict]:
    """Lines the renderer can always play, with known speakers, facts, visuals and shots."""
    by_name = {h["name"].lower(): i for i, h in enumerate(hosts)}
    fact_ids = {f["id"] for f in pack.get("facts") or []}
    lines = []
    for item in raw[:MAX_LINES + 4]:
        speaker = by_name.get(str(item.get("speaker", "")).strip().lower())
        if speaker is None:  # unknown name: whoever didn't speak last
            speaker = 1 - lines[-1]["speaker"] if lines else 0
        text = text_clean.screen_text(str(item.get("text", "")), 220)
        if not text or len(text.split()) > WORDS[speaker] + 4:
            continue
        visual = item.get("visual") if item.get("visual") in menu else "hosts"
        shot = item.get("shot") if item.get("shot") in case_render.SHOTS else "studio"
        if shot == "screen" and visual in ("hosts", "title"):
            shot = "studio"
        if shot == "close" and lines:  # the screen is out of the shot: it keeps what it showed
            visual = lines[-1]["visual"]
        line = {"speaker": speaker, "text": text,
                "facts": [f for f in dict.fromkeys(str(f).strip().upper() for f in item.get("facts") or []) if f in fact_ids],
                "visual": visual, "shot": shot,
                "emotion": cs.snap(item.get("emotion"), puppet.EMOTIONS, default="neutral"),
                "action": cs.snap(item.get("action"), case_render.ACTIONS, default="talk"),
                "listener_emotion": cs.snap(item.get("listener_emotion"), puppet.EMOTIONS, default="neutral")}
        lines.append(line)
    if len(lines) < MIN_LINES // 2:
        raise ValueError(f"the script has only {len(lines)} usable lines")
    lines[0]["shot"] = "studio"  # the hook: both hosts, the case on the screen
    return lines


def vary_visuals(lines: list[dict], menu: dict, pack: dict) -> list[dict]:
    """No kind of visual on more than MAX_SAME lines in a row's worth: the extra ones get a photo, the
    timeline or a big number the script hasn't used yet (or just the hosts)."""
    counts: dict[str, int] = {}
    used = {line["visual"] for line in lines}
    stat_for = {s["fact"]: f"stat:{s['id']}" for s in pack.get("stats") or []}
    spare = [v for v in menu if v.split(":")[0] in ("photo", "chart", "map", "timeline") and v not in used]
    for line in lines:
        kind = line["visual"].split(":")[0]
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("hosts", "title") or counts[kind] <= MAX_SAME:
            continue
        swap = next((stat_for[f] for f in line["facts"] if f in stat_for and stat_for[f] not in used), None)
        other = next((v for v in spare if v.split(":")[0] != kind), None)  # a different kind, not just another photo
        if not swap and other:
            swap = other
            spare.remove(other)
        line["visual"] = swap or "hosts"
        used.add(line["visual"])
        if line["visual"] == "hosts" and line["shot"] == "screen":
            line["shot"] = "studio"
    return lines


def estimate_seconds(lines: list[dict], hosts: list[dict]) -> float:
    words = sum(len(line["text"].split()) / hosts[line["speaker"]]["speed"] for line in lines)
    gaps = sum(case_render.SAME_GAP if a["speaker"] == b["speaker"] else case_render.GAP for a, b in zip(lines, lines[1:]))
    return words / WORDS_PER_SECOND + case_render.LEAD_IN + gaps + case_render.TAIL


def fit_length(lines: list[dict], hosts: list[dict], max_seconds: float) -> list[dict]:
    """Drops lines from the middle (never the hook or the ending) until the script fits."""
    while len(lines) > MIN_LINES and estimate_seconds(lines, hosts) > max_seconds:
        middle = len(lines) // 2
        # a co-host line goes first if there's one near the middle: it carries no facts
        k = next((i for i in (middle, middle + 1, middle - 1) if 0 < i < len(lines) - 1 and lines[i]["speaker"] == 1), middle)
        lines.pop(k)
    return lines


# --- writing --------------------------------------------------------------------

def _schema(names: list[str], menu: dict, moods: list[str]) -> dict:
    line = {
        "type": "object",
        "properties": {
            "speaker": {"type": "string", "enum": names},
            "text": {"type": "string", "description": f"what they say: {names[0]} at most 20 words, {names[1]} at most 14"},
            "facts": {"type": "array", "items": {"type": "string"},
                      "description": "ids of the facts the line uses (F1, F2...); empty for a question or a joke"},
            "visual": {"type": "string", "enum": list(menu)},
            "shot": {"type": "string", "enum": list(case_render.SHOTS)},
            "emotion": {"type": "string", "enum": list(puppet.EMOTIONS)},
            "action": {"type": "string", "enum": list(case_render.ACTIONS)},
            "listener_emotion": {"type": "string", "enum": list(puppet.EMOTIONS),
                                 "description": "how the other host reacts while this is said"},
        },
        "required": ["speaker", "text", "facts", "visual", "shot", "emotion", "action", "listener_emotion"],
    }
    return {
        "type": "object",
        "properties": {
            "case_title": {"type": "string", "description": f"the title on screen, at most {TITLE_CHARS} characters"},
            "lines": {"type": "array", "items": line, "description": "12 to 16 lines: the hook first, the takeaway or twist last"},
            "key_points": {"type": "array", "items": {"type": "string"}, "description": "2 or 3 key points, at most 6 words each"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "music_mood": {"type": "string", "enum": moods} if moods else {"type": "string"},
        },
        "required": ["case_title", "lines", "key_points", "title", "description", "hashtags", "tags", "music_mood"],
    }


def _system(cfg: dict, hosts: list[dict], target: int) -> str:
    ch = cfg["channel"]
    p, c = hosts
    words = round((target - 6) * WORDS_PER_SECOND * (p["speed"] + c["speed"]) / 2)
    return f"""You write the scripts for {ch['name']}, a YouTube Shorts channel of 60-second case studies for
{ch['audience']}, told by two cartoon hosts: {p['name']} presents ({p['personality']}); {c['name']} is the co-host
({c['personality']}).
The channel's voice: {ch['voice']}

Write 12 to 16 short lines of dialogue, about {target} seconds spoken: about {words} words in all.
The shape:
1. Hook (line 1, {p['name']}, at most 12 words): the most surprising fact, or a sharp question. No greeting.
2. Setup (1-2 lines): who, when, how big.
3. Turning points (3-5 lines): what changed, in order, with the numbers that show it.
4. The why (2-3 lines): connect the dots. This analysis is what viewers came for.
5. Takeaway or twist (the last line from {p['name']}): what the case teaches, in one sentence people remember.
{c['name']} speaks every two or three lines, at least four times: asks what a viewer would ask, reacts, or makes a light
joke, in at most 14 words, and never states a new fact.

How to say it:
- Retell the facts in your own spoken words: short, punchy, conversational sentences. Never read a fact out word for
  word. Each of {p['name']}'s lines has at most 20 words and one idea. Contrasts, then-and-now and a 'but' make lines land.
- Every fact, name, date and number comes from the research pack, and each line lists the ids of the facts it uses.
  Never add anything from memory, even if you're sure of it. Numbers exactly as the facts give them, written as digits.
- Opinions and forecasts are attributed ('economists say', 'the IMF expects'). Neutral and respectful: never mock real
  people, faiths or nations; for politics give both sides; no advice on money, health or law; myths are told as
  stories ('in the epic, ...').
- Spoken English for a voice engine: no emoji, no hashtags, no stage directions, no parentheses.

What's on screen:
- Each line gets a visual from the list that matches what's said. Change it every line or two and use at least four
  kinds: photos, charts, maps, timelines and big numbers work best. Quote cards (the source's own words) at most
  twice; 'hosts' and 'title' only for the hook, jokes and reactions.
- Shots: screen shows the visual big with both hosts at their desk under it, so most lines use it, either host's
  (photos, charts, maps, timelines, numbers); studio shows both hosts big with the visual on the wall screen behind
  them (the hook, quick back-and-forth, the ending); close is the speaker up close without the visual (short
  reactions, jokes, the twist).
- Emotions and actions fit each line: surprised at a twist, smug at a punchline, a shrug, a facepalm, pointing.

case_title: the title on screen, at most {TITLE_CHARS} characters, in a few plain words.
key_points: 2 or 3 points of at most 6 words each, for the 'list' visual.
Title: at most 70 characters, sentence case, honest, may end with one emoji. Description: 2-3 short sentences ending
on a question for the comments. Hashtags: 2-4, lowercase. Tags: 5-10 search keywords."""


def _pack_for_prompt(pack: dict, brief: dict) -> str:
    sources = {s["id"]: s.get("publisher") or s["title"] for s in pack.get("sources") or []}
    return json.dumps({
        "facts": [{"id": f["id"], "claim": f["claim"], "kind": f["kind"], "source": sources.get(f["source"], "")}
                  for f in pack.get("facts") or []],
        "timeline": pack.get("timeline") or [], "big_numbers": pack.get("stats") or [],
        "people": pack.get("people") or [], "what_the_sources_say": pack.get("answer", ""),
    }, ensure_ascii=False, indent=1)


def fact_check(lines: list[dict], pack: dict, progress=log) -> tuple[list[dict], int, bool]:
    """A second reading of every line against its facts' quotes: fixes overstated lines, cuts unsupported
    ones. Returns the lines (each marked), how many were cut and whether the hook was one of them."""
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    items = []
    for n, line in enumerate(lines, start=1):
        before = lines[n - 2] if n > 1 else None
        items.append({"line": n, "speaker": "presenter" if line["speaker"] == 0 else "co-host", "text": line["text"],
                      "facts": [{"claim": by_id[f]["claim"], "quote": by_id[f]["quote"]}
                                for f in line["facts"] + ((before or {}).get("facts") or [])],
                      "numbers_not_in_its_facts": sorted(unsupported_numbers(line, pack, before))})
    schema = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"line": {"type": "integer"}, "verdict": {"type": "string", "enum": VERDICTS},
                       "fixed": {"type": "string", "description": "for an overstated line: the same line, corrected so its "
                                                                 "facts support it; else empty"}},
        "required": ["line", "verdict", "fixed"]}}}, "required": ["verdicts"]}
    system = """You fact-check scripts for a YouTube channel of case studies. For each line, compare what it says with
the facts it cites (their claims and the source quotes behind them):
- supported: everything it states is in those facts (wording may differ; obvious context is fine)
- overstated: mostly right but goes further than the facts (a number, a date, a cause, a superlative); give the
  fixed line, as short and natural as the original
- unsupported: it states something none of its facts support
- not_a_claim: a question, a reaction or a joke that states no new fact
Numbers must match the facts exactly. Be strict about facts and relaxed about style."""
    progress("Fact-checking every line against its sources")
    verdicts = {v.get("line"): v for v in llm.generate_json([json.dumps(items, ensure_ascii=False, indent=1)], schema,
                                                            system).get("verdicts") or []}
    kept, cut, hook_cut = [], 0, False
    for n, line in enumerate(lines, start=1):
        v = verdicts.get(n) or {}
        before = lines[n - 2] if n > 1 else None
        verdict = v.get("verdict") if v.get("verdict") in VERDICTS else "supported"
        if verdict == "overstated":
            fixed = text_clean.screen_text(str(v.get("fixed", "")), 220)
            candidate = {**line, "text": fixed}
            if fixed and not unsupported_numbers(candidate, pack, before):
                kept.append({**candidate, "check": "fixed", "was": line["text"]})
                continue
            verdict = "unsupported"
        if unsupported_numbers(line, pack, before) or (verdict == "unsupported" and line["speaker"] == 0):
            cut += 1  # the co-host's questions and reactions stay unless they bring numbers of their own
            hook_cut = hook_cut or n == 1
            continue
        kept.append({**line, "check": "ok"})
    if kept:
        kept[0]["shot"] = "studio"
    return kept, cut, hook_cut


def write(brief: dict, pack: dict, hosts: list[dict], progress=log) -> dict:
    cfg = load_config()
    cases = cfg["cases"]
    target, max_seconds = int(cases.get("target_seconds", 58)), int(cases.get("max_seconds", 65))
    names = [h["name"] for h in hosts]
    moods = short_render.music_moods()
    menu = visual_menu(pack, brief)
    system = _system(cfg, hosts, target)
    follow = ""
    if brief.get("follow_up_of"):
        earlier = db.get_video(brief["follow_up_of"])
        if earlier:
            follow = (f"This is a follow-up (part 2) to an earlier case: "
                      f"{earlier['plan'].get('metadata', {}).get('title') or earlier['theme']}. Mention it briefly.\n")
    recent = [v["plan"]["metadata"]["title"] for v in db.recent_videos(days=30)
              if v["format"] == db.FORMAT and v["plan"].get("metadata")][:30]
    base_prompt = (f"Case type: {brief['category']}\nTopic: {brief['topic']}\nThe case's question: {brief['angle']}\n"
                   + (f"Why now: {brief['trend']}\n" if brief.get("trend") else "") + follow
                   + f"\nResearch pack:\n{_pack_for_prompt(pack, brief)}\n\n"
                   f"Visuals you can use:\n" + "\n".join(f"- {k}: {v}" for k, v in menu.items()) + "\n\n"
                   f"Recent titles (don't repeat them): {recent or 'none yet'}\n"
                   f"What has worked so far: {advice(('hook', 'length', 'visuals', 'lines')) or 'not enough data yet'}\n\n")
    feedback = ""
    for attempt in range(2):
        progress("Writing the script" if not attempt else "Rewriting the script")
        raw = llm.generate_json([base_prompt + feedback + "Write the script."], _schema(names, menu, moods), system,
                                careful=True)
        lines = vary_visuals(clean_lines(raw.get("lines") or [], hosts, pack, menu), menu, pack)
        lines = fit_length(lines, hosts, max_seconds)
        if estimate_seconds(lines, hosts) < MIN_SECONDS and not attempt:
            feedback = f"Your last script was too short (about {estimate_seconds(lines, hosts):.0f} seconds). Write a fuller one.\n"
            continue
        checked, cut, hook_cut = fact_check(lines, pack, progress)
        if (cut > MAX_CUTS or hook_cut) and not attempt:
            feedback = (f"The fact-checker cut {cut} line(s) of your last script{', the hook among them,' if hook_cut else ''} "
                        "because the facts didn't support them. Stick to what the facts say, and cite every fact a "
                        "line uses.\n")
            continue
        lines = checked
        break
    if len(lines) < MIN_LINES // 2:
        raise RuntimeError("too few lines survived the fact-check")
    case_title = text_clean.screen_text(str(raw.get("case_title", "")), TITLE_CHARS) or brief["topic"][:TITLE_CHARS]
    script = {"case_title": case_title, "lines": lines,
              "key_points": [text_clean.screen_text(str(p), 48) for p in raw.get("key_points") or [] if str(p).strip()][:3],
              "music_mood": cs.snap(raw.get("music_mood"), moods, default="") if moods else "",
              "seconds": round(estimate_seconds(lines, hosts), 1), "cut": cut}
    progress(f"Script: {len(lines)} lines, about {script['seconds']:.0f} s ({cut} cut by the fact-check)")
    return {"script": script, "metadata": metadata(raw, brief, cfg), "lines": len(lines), "cut": cut,
            "estimate": script["seconds"]}


def metadata(raw: dict, brief: dict, cfg: dict) -> dict:
    base = list(cfg["metadata"]["base_hashtags"]) + [HASHTAG_FOR.get(brief.get("category"), "")]
    tags = text_clean.hashtags(raw.get("hashtags") or [], [t for t in base if t])
    title = text_clean.title(str(raw.get("title", "")), brief["topic"])[:100]
    summary = text_clean.no_brackets(" ".join(str(raw.get("description", "")).split()))[:1200]
    return {"title": title, "description": summary, "hashtags": tags,
            "tags": text_clean.tags((raw.get("tags") or []) + [brief["topic"]])}


def run(brief: dict, pack: dict, hosts: list[dict], progress=log) -> dict:
    return act("writer", f"Script: {brief['topic']}", write, brief, pack, hosts, progress=progress)


def apply_edits(plan: dict, edits: dict) -> dict:
    """The owner's edits from the dashboard, through the same rules as written text. A line you change
    is marked "edited"; if it has a number its facts don't support, "edited-unsourced"."""
    cfg = load_config()
    script, meta, pack, brief = plan["script"], plan["metadata"], plan["research"], plan["brief"]
    hosts = plan["hosts"]
    if "lines" in edits:
        menu = visual_menu(pack, brief)
        old = {line["text"]: line for line in script["lines"]}
        raw = [{**line, "speaker": hosts[int(line["speaker"])]["name"] if str(line.get("speaker", "")).isdigit()
                else line.get("speaker")} for line in edits["lines"] if isinstance(line, dict)]
        lines = clean_lines(raw, hosts, pack, menu)
        for k, line in enumerate(lines):
            same = old.get(line["text"])
            if same and same.get("facts") == line["facts"]:
                line["check"] = same.get("check", "ok")
            else:
                line["check"] = ("edited-unsourced" if unsupported_numbers(line, pack, lines[k - 1] if k else None)
                                 else "edited")
        if estimate_seconds(lines, hosts) > int(cfg["cases"].get("max_seconds", 65)) + 15:
            raise ValueError("That's too long for a Short: shorten or remove a line.")
        script["lines"] = lines
        script["seconds"] = round(estimate_seconds(lines, hosts), 1)
    if "case_title" in edits:
        script["case_title"] = text_clean.screen_text(str(edits["case_title"]), TITLE_CHARS) or script["case_title"]
    if "key_points" in edits:
        script["key_points"] = [text_clean.screen_text(str(p), 48) for p in edits["key_points"] if str(p).strip()][:3]
    if "title" in edits:
        meta["title"] = text_clean.title(str(edits["title"]), meta["title"])
    if "description" in edits:
        meta["description"] = text_clean.no_brackets(str(edits["description"])).strip()[:3000]
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--pack", required=True)
    parser.add_argument("--brief", required=True)
    args = parser.parse_args()
    from agents import hosts as hosts_agent

    try:
        with open(args.pack, encoding="utf-8") as f:
            pack = json.load(f)
        with open(args.brief, encoding="utf-8") as f:
            brief = json.load(f)
        result = write(brief, pack, hosts_agent.current())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
