"""
The film of Agent 2's story (agents/story.py): the narrator's lines laid over their shots, the film drawn in
the silhouette look (tools/silhouette_render.py: everything in code, no AI pictures), its short version drawn upright,
the thumbnail, and a still of every scene. Agent 3 (agents/animator.py) runs it.

Timing (timeline): the narrator leads. A shot with a line starts its line LEAD seconds in and lasts at least until TAIL
after the line ends (longer if planned so); a shot without one keeps its planned length. Lines never overlap. The film is
then kept inside series.minutes by stretching or shortening the silent shots. The closing line is said over the last shot
and stays on screen CLOSING_HOLD after he finishes.

Music (music_for): one of the full-length tracks in the music library (assets/music/full/, the dashboard's Music page;
CC BY, incompetech.com, credited in the description), chosen from the story's title, silent until the spark and rising
from it to the end.

The short version (make_short; your choice, 2026-11-16: it replaced the teaser): the whole story told again in under a
minute for YouTube Shorts and Instagram Reels. Agent 2 picks 8-14 of the film's shots (in its order, every part of the
story) and writes the narrator's new lines over them (story["short"]); short_story() makes that a story of its own, each
shot drawn as in the film (its seed) but upright, 1080x1920, framed on him. Timed like the film (short_timeline: tighter
gaps between lines, fitted inside SHORT_SECONDS, never SHORT_MOST or more), the title at the top for its first seconds,
the closing line at its end, its own sounds, and the music silent until its spark, then rising.

Usage:
    python tools/story_film.py story.json out.mp4      # a story (agents/story.py --out) made into a film, no narrator
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import series

LEAD, TAIL = 0.30, 0.45            # seconds of a shot before its line, and after it (agents/story.py estimates with these)
FLOW_LEAD, FLOW_TAIL = 0.06, 0.10  # ...when a sentence goes on into the next shot (its line was cut at a comma)
PARAGRAPH = 0.35                   # a new paragraph's extra breath before its first line
CLOSING_HOLD = 3.0                 # the closing line stays this long after he's said it
SILENT_SHORTEST, SILENT_LONGEST = 2.5, 8.0  # a shot without a line, when the film's length is fitted

# The short version (Shorts and Reels): under a minute, your choice (2026-11-16)
SHORT_SECONDS = (45.0, 58.0)       # what its timing aims for
SHORT_MOST = 59.5                  # never this long or more (YouTube blocks a Short over a minute that gets a claim)
SHORT_LEAD, SHORT_TAIL = 0.35, 0.5  # a Short's pace: a little less air around each line than the film's
SHORT_CLOSING_HOLD = 2.2
SHORT_SILENT = (1.8, 4.5)          # one of its shots without a line
SHORT_EVENT_SHORTEST = 2.6         # ...one whose event (a head turn, the clock's flip) needs the time to happen
SHORT_FIRST_SHORTEST = 3.6         # its first shot: the title at the top must be read
SHORT_COVER_AT = 2.0               # the Reel's cover: the title at the top, fully in


# --- timing ------------------------------------------------------------------------------------------------------------------
def timeline(story: dict, spoken: list[dict] | None = None, bounds: tuple[float, float] | None = None,
             lead: float = LEAD, tail: float = TAIL, hold: float = CLOSING_HOLD,
             silences: tuple[float, float] = (SILENT_SHORTEST, SILENT_LONGEST), event_shortest: float = 0.0) -> list[dict]:
    """Each shot's start and length, and its line's start and length (spoken: the narrator's lines in order, with their
    real lengths; without them, estimated). Fitted inside `bounds` (seconds; the film's: series.minutes) by the silent
    shots, each kept between `silences` (and at least `event_shortest` when something happens in it, or its own planned
    "shortest")."""
    import narrator

    lines = iter(spoken or [])
    times = []
    said = [k for k, s in enumerate(story["shots"]) if s.get("line")]
    flows = {a for a, b in zip(said, said[1:]) if b == a + 1 and _goes_on(story["shots"][a]["line"])}
    paras = {k for k in said[1:] if _new_paragraph(story, story["shots"][k])}
    for k, shot in enumerate(story["shots"]):
        line_s = None
        if shot.get("line"):
            got = next(lines, None)
            line_s = float(got["seconds"]) if got else narrator.estimate_seconds(shot["line"])
        last = k == len(story["shots"]) - 1
        own_lead = FLOW_LEAD if k - 1 in flows else lead + (PARAGRAPH if k in paras else 0.0)
        own_tail = FLOW_TAIL if k in flows else tail
        need = own_lead + line_s + (hold if last else own_tail) if line_s is not None else 0.0
        own = float(shot.get("shortest") or 0.0)
        floor = max(need, own) if line_s is not None else max(
            silences[0], own, event_shortest if (shot.get("event") or "none") != "none" else 0.0)
        times.append({"planned": float(shot["seconds"]), "need": need, "line_seconds": line_s, "floor": floor,
                      "seconds": floor if line_s is not None and shot.get("stage") else max(float(shot["seconds"]), floor),
                      "lead": own_lead})   # (a storyboard shot with a line lasts what its line needs: the lines flow)
    low, high = bounds or tuple(m * 60 for m in series.minutes())
    longest = silences[1]
    total = sum(t["seconds"] for t in times)
    silent = [t for t in times if t["line_seconds"] is None]
    if total > high and silent:  # shorter silences (never under their floor), then lines' shots to what they need
        spare = sum(t["seconds"] - t["floor"] for t in silent)
        cut = min(spare, total - high)
        for t in silent:
            t["seconds"] -= cut * (t["seconds"] - t["floor"]) / max(spare, 1e-6)
        total = sum(t["seconds"] for t in times)
        if total > high:
            for t in times:
                if t["line_seconds"] is not None:
                    t["seconds"] = max(t["floor"], min(t["seconds"], t["need"] + 0.2))
    elif total < low and silent:  # longer silences, up to the longest
        room = sum(longest - t["seconds"] for t in silent if t["seconds"] < longest)
        add = min(room, low - total)
        for t in silent:
            if t["seconds"] < longest:
                t["seconds"] += add * (longest - t["seconds"]) / max(room, 1e-6)
    at = 0.0
    for t in times:
        t["seconds"] = round(t["seconds"], 3)
        t["start"] = round(at, 3)
        t["line_at"] = round(at + t.pop("lead"), 3) if t["line_seconds"] is not None else None
        at += t["seconds"]
        t.pop("lead", None)
    return times


def _goes_on(line: str) -> bool:
    """Does a line go on into the next one (a sentence cut where it breathes, not at its end)?"""
    return not re.search(r"[.!?…][\"”’)\]]*$", str(line).strip())


def _new_paragraph(story: dict, shot: dict) -> bool:
    """Is a shot's line the first of a paragraph of the script (a little more breath before it)?"""
    i = shot.get("line_index")
    lines = story.get("lines") or []
    return i is not None and 0 < i < len(lines) and bool(lines[i].get("para"))


def chapters(story: dict, times: list[dict]) -> list[dict]:
    """YouTube chapters: one at each part's first shot ({"at", "name"}); the first at 0:00."""
    out = []
    for shot, t in zip(story["shots"], times):
        if not out or out[-1]["act"] != shot["act"]:
            out.append({"act": shot["act"], "at": 0.0 if not out else t["start"],
                        "name": (story.get("chapters") or {}).get(shot["act"]) or shot["act"].replace("_", " ").title()})
    merged = []  # YouTube wants every chapter at least 10 s long
    for c in out:
        if merged and c["at"] - merged[-1]["at"] < 10:
            continue
        merged.append(c)
    return merged


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def voice_cues(times: list[dict], spoken: list[dict]) -> list[dict]:
    """Where each of the narrator's lines starts in the film: [{"wav", "at", "seconds", "words", "from"}] (the last
    three time the subtitles: tools/subtitles.py)."""
    cues, lines = [], iter(spoken)
    for t in times:
        if t["line_at"] is not None:
            got = next(lines, None)
            if got:
                cues.append({"wav": got["wav"], "at": t["line_at"], "seconds": got.get("seconds"),
                             "words": got.get("words") or [], "from": got.get("from")})
    return cues


def music_for(story: dict) -> str | None:
    """The story's music (a full-length track of the library: tools/media.py), chosen from its title so a story keeps
    its track when it's made again."""
    import media

    tracks = [media.track_name(p) for p in media.music_tracks()]
    if not tracks:
        return None
    k = int(hashlib.sha1(str(story.get("title") or "").encode("utf-8")).hexdigest()[:8], 16) % len(tracks)
    return tracks[k]


# --- the film ----------------------------------------------------------------------------------------------------------------
def make(story: dict, spoken: list[dict] | None, out: Path, progress=print, beds: float = 0.0) -> dict:
    """The film: drawn, timed to the narrator's lines (`spoken`, in order), with his voice and the music from the spark.
    Returns its timing and chapters."""
    import silhouette_render

    times = timeline(story, spoken)
    story = {**story, "music": music_for(story)}
    silhouette_render.render(story, times, Path(out), voice=voice_cues(times, spoken) if spoken else None,
                             progress=progress, beds_db=beds)
    return {"times": times, "seconds": round(sum(t["seconds"] for t in times), 2), "chapters": chapters(story, times),
            "music": story["music"]}


# --- the short version -------------------------------------------------------------------------------------------------------
def short_story(story: dict, short: dict | None = None) -> dict:
    """The short version as a story of its own: the film's shots Agent 2 picked (story["short"], or `short`), each drawn
    as in the film (its seed: "film_shot" says which it is) with the short script's line over it; the last one's line is
    always the closing line. Its first shot fades in; a light switching off between two of the film's shots isn't
    between these two, so it's a fade."""
    picked = (short if short is not None else story.get("short") or {}).get("shots") or []
    shots = []
    for j, s in enumerate(picked):
        k = int(s["shot"]) - 1
        if not 0 <= k < len(story["shots"]):
            continue
        base = story["shots"][k]
        enter = "fade" if j == 0 or base.get("enter") == "lights_out" else (base.get("enter") or "cut")
        shots.append({**base, "line": s.get("line") or "", "direction": s.get("direction") or "",
                      "seconds": float(s.get("seconds") or SHORT_SILENT[0]), "enter": enter, "seed": k * 101 + 7,
                      "film_shot": k + 1, "shortest": SHORT_FIRST_SHORTEST if j == 0 else 0.0})
    if shots and story.get("closing_line"):
        shots[-1]["line"] = story["closing_line"]
        shots[-1]["direction"] = shots[-1]["direction"] or "slow, warm, final"
    for s in shots:   # (its own lines: no paragraph of the film's script)
        s.pop("line_index", None)
    out = {"title": story.get("title") or "", "theme": story.get("theme"), "closing_line": story.get("closing_line") or "",
           "music": story.get("music"), "music_from": story.get("music_from"), "shots": shots,
           "places": story.get("places") or [], "cast": story.get("cast") or []}
    if story.get("realization") is not None:   # (the music starts at the first of its shots from his realization on)
        out["realization"] = next((j for j, s in enumerate(shots) if s["film_shot"] - 1 >= int(story["realization"])),
                                  None)
    return out


def short_lines(story: dict, short: dict | None = None) -> list[dict]:
    """The short version's script for the narrator: each line with its direction and its shot (in the short)."""
    return [{"text": s["line"], "direction": s.get("direction") or "", "shot": j}
            for j, s in enumerate(short_story(story, short)["shots"]) if s.get("line")]


def short_timeline(short: dict, spoken: list[dict] | None = None) -> list[dict]:
    """timeline() for the short version (short_story's): tighter gaps, fitted inside SHORT_SECONDS."""
    return timeline(short, spoken, bounds=SHORT_SECONDS, lead=SHORT_LEAD, tail=SHORT_TAIL, hold=SHORT_CLOSING_HOLD,
                    silences=SHORT_SILENT, event_shortest=SHORT_EVENT_SHORTEST)


def short_need(times: list[dict]) -> float:
    """The least the short version can run with these lines (every shot at its floor: a line's shot as long as its line
    needs, a silent one at its shortest)."""
    return round(sum(t["floor"] for t in times), 2)


def make_short(story: dict, spoken: list[dict] | None, out: Path, progress=print, beds: float = 0.0) -> dict:
    """The short version (1080x1920): the film's shots Agent 2 picked, drawn upright and timed to the narrator's reading
    of its own lines (`spoken`, in order), with his voice, each place's sounds and the music from its spark. Returns its
    timing and the film's shots it shows."""
    import silhouette_render

    short = {**short_story(story), "music": music_for(story)}
    if not short["shots"]:
        raise RuntimeError("the story has no short version to make")
    times = short_timeline(short, spoken)
    silhouette_render.render(short, times, Path(out), voice=voice_cues(times, spoken) if spoken else None,
                             progress=progress, beds_db=beds, upright=True)
    return {"times": times, "seconds": round(sum(t["seconds"] for t in times), 2), "music": short["music"],
            "film_shots": [s["film_shot"] for s in short["shots"]]}


def thumbnail(story: dict, times: list[dict], shot: int, lead: str, punch: str, out: Path) -> Path:
    """The thumbnail (1280x720 JPEG, tools/thumbnail.py): shot `shot` (1 = the first) at its strongest moment, him big,
    the white lead-in and the yellow punch."""
    import thumbnail as T

    k = max(0, min(len(times) - 1, int(shot) - 1))
    return T.make(story, k, times[k]["seconds"], lead, punch, Path(out))


def scenes(story: dict, times: list[dict], folder: Path) -> dict[str, str]:
    """A still of every shot ({"s1": path, ...}): the dashboard's scenes, what the Reviewer is shown."""
    import silhouette_render

    got = silhouette_render.scene_stills(story, times, Path(folder))
    return {f"s{g['shot']}": g["path"] for g in got}


def cover(film: Path, at: float, out: Path) -> Path:
    """A frame of the film (the dashboard's poster for it)."""
    import media

    subprocess.run([media.ffmpeg_exe(), "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(film), "-frames:v", "1",
                    "-q:v", "3", str(out)], check=True, timeout=120)
    return out


def story_key(story: dict) -> str:
    return hashlib.sha1(json.dumps(story, sort_keys=True).encode("utf-8")).hexdigest()[:10]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("story", help="agents/story.py --out's JSON (or {\"story\": ...})")
    parser.add_argument("out")
    args = parser.parse_args()
    data = json.loads(Path(args.story).read_text(encoding="utf-8"))
    story = data.get("story") or data
    made = make(story, None, Path(args.out))
    print(json.dumps({k: v for k, v in made.items() if k != "times"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
