"""
The film of Agent 2's story (agents/story.py): its moments' shots, their bubbles over the speakers' heads (no narrator:
your choice, 2026-11-19), drawn in the silhouette look (tools/silhouette_render.py: everything in code, no AI pictures),
its short version drawn upright, the thumbnail, and a still of every scene. Agent 3 (agents/animator.py) runs it.

Timing (timeline): the bubbles lead. A shot with bubbles starts its first LEAD seconds in; each bubble stays for an average
reader (tools/silhouette_words.read_seconds: a second to find it, then 2.5 words a second, 2.5 s at least), the next one
starting where it was read, the earlier one staying (dimmed) until its reply is read: never more than two at once. The
shot lasts until TAIL after its last bubble is read. There's no title in the picture (your choice, 2026-11-20): the film
begins straight with the story, its first bubble OPENING seconds after the picture fades in; its last shot shows the
closing line after its bubbles, long enough to read it and CLOSING_HOLD more. A shot
without bubbles keeps its planned length; the film is kept inside series.minutes by stretching or shortening those.

Music (music_for): one of the full-length tracks in the music library (assets/music/full/, the dashboard's Music page;
CC BY, incompetech.com, credited in the description), chosen from the story's title: low from the first second, lifting
at his realization (tools/silhouette_render.music_spec).

The short version (make_short): the whole story told again in under a minute for YouTube Shorts and Instagram Reels.
Agent 2 picks 8-12 of the film's shots (in its order, every stage) with shorter bubbles (story["short"]); short_story()
makes that a story of its own, each shot drawn as in the film (its seed) but upright, 1080x1920, framed on him. Timed like
the film (short_timeline: inside SHORT_SECONDS, never SHORT_MOST or more), beginning straight with the story (no title
in the picture), the closing line at its end.

Usage:
    python tools/story_film.py story.json out.mp4      # a storyboarded story (agents/storyboard.py --out) made into a film
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import series
import silhouette_words as W

LEAD, TAIL = 0.5, 0.8              # seconds of a shot before its first bubble, and after its last is read
OPENING = 1.0                      # the film's first shot: its picture fades in before the first bubble (no title)
CLOSING_HOLD = 2.5                 # the closing line stays this long after it's read
LAST_BREATH = 0.3                  # a shot's last bubble stays this long after it's read
SILENT_SHORTEST, SILENT_LONGEST = 2.5, 8.0  # a shot without bubbles, when the film's length is fitted

# The short version (Shorts and Reels): under a minute, your choice (2026-11-16)
SHORT_SECONDS = (45.0, 58.0)       # what its timing aims for
SHORT_MOST = 59.5                  # never this long or more (YouTube blocks a Short over a minute that gets a claim)
SHORT_LEAD, SHORT_TAIL = 0.35, 0.5  # a Short's pace: a little less air round each shot's bubbles than the film's
SHORT_OPENING = 0.5                # its first shot: the picture fades in, then the hook's bubble (no title)
SHORT_CLOSING_HOLD = 1.6
SHORT_SILENT = (1.8, 4.5)          # one of its shots without bubbles
SHORT_EVENT_SHORTEST = 2.6         # ...one whose event (a head turn) needs the time to happen
SHORT_COVER_AT = 2.0               # the Reel's cover: a moment of its first shot, the hook's bubble in


# --- timing ------------------------------------------------------------------------------------------------------------------
def bubble_times(bubbles: list[dict], lead: float) -> tuple[list[dict], float]:
    """A shot's bubbles with their times in it (seconds from its start): each starts where the one before was read and
    stays until its reply is read (the last, LAST_BREATH after it's read). Returns them and when the last is read."""
    reads = [W.read_seconds(b.get("text") or "", b.get("picture") or "") for b in bubbles]
    starts, t = [], lead
    for r in reads:
        starts.append(t)
        t += r
    out = []
    for k, b in enumerate(bubbles):
        end = starts[k + 1] + reads[k + 1] if k + 1 < len(bubbles) else starts[k] + reads[k] + LAST_BREATH
        out.append({**b, "start": round(starts[k], 3), "end": round(end, 3)})
    return out, t


def timeline(story: dict, bounds: tuple[float, float] | None = None, lead: float = LEAD, tail: float = TAIL,
             hold: float = CLOSING_HOLD, silences: tuple[float, float] = (SILENT_SHORTEST, SILENT_LONGEST),
             event_shortest: float = 0.0, opening: float = OPENING) -> list[dict]:
    """Each shot's start and length, its bubbles' times in it ("bubbles"), when its first bubble comes ("line_at", in
    the film) and, the last shot's, when the closing line comes in it ("closing_at"). Fitted inside `bounds` (seconds;
    the film's: series.minutes) by the shots without bubbles, each kept between `silences` (and at least
    `event_shortest` when something happens in it, or its own planned "shortest")."""
    closing = story.get("closing_line") or ""
    n = len(story["shots"])
    times = []
    for k, shot in enumerate(story["shots"]):
        first, last = k == 0, k == n - 1
        bubbles = shot.get("bubbles") or []
        own_lead = lead + (opening if first else 0.0)
        timed, read = bubble_times(bubbles, own_lead) if bubbles else ([], own_lead)
        need = read + tail if bubbles else 0.0
        if first:
            need = max(need, opening + 1.0)
        closing_at = None
        if last:
            closing_at = read + LAST_BREATH if bubbles else 0.8
            need = max(need, closing_at + W.read_seconds(closing) + hold)
        own = float(shot.get("shortest") or 0.0)
        fixed = bool(bubbles) or first or last
        floor = max(need, own) if fixed else max(
            silences[0], own, event_shortest if (shot.get("event") or "none") != "none" else 0.0)
        planned = float(shot.get("seconds") or silences[0])
        seconds = floor if fixed and shot.get("stage") else max(planned, floor)   # (a storyboard shot with bubbles lasts
        times.append({"planned": planned, "need": need, "floor": floor, "seconds": seconds, "bubbles": timed,   # what they need)
                      "line_seconds": (read - own_lead) if bubbles else None, "first_at": own_lead if bubbles else None,
                      "closing_at": closing_at, "fixed": fixed})
    low, high = bounds or tuple(m * 60 for m in series.minutes())
    longest = silences[1]
    total = sum(t["seconds"] for t in times)
    free = [t for t in times if not t["fixed"]]
    if total > high and free:  # shorter silent shots, never under their floor
        spare = sum(t["seconds"] - t["floor"] for t in free)
        cut = min(spare, total - high)
        for t in free:
            t["seconds"] -= cut * (t["seconds"] - t["floor"]) / max(spare, 1e-6)
    elif total < low and free:  # longer silent shots, up to the longest
        room = sum(longest - t["seconds"] for t in free if t["seconds"] < longest)
        add = min(room, low - total)
        for t in free:
            if t["seconds"] < longest:
                t["seconds"] += add * (longest - t["seconds"]) / max(room, 1e-6)
    at = 0.0
    for t in times:
        t["seconds"] = round(t["seconds"], 3)
        t["start"] = round(at, 3)
        t["line_at"] = round(at + t.pop("first_at"), 3) if t["first_at"] is not None else None
        t.pop("first_at", None)
        t.pop("fixed", None)
        at += t["seconds"]
    return times


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
def make(story: dict, out: Path, progress=print, beds: float = 0.0) -> dict:
    """The film: drawn, its bubbles timed for reading, the place's sounds and the music. Returns its timing and
    chapters."""
    import silhouette_render

    times = timeline(story)
    story = {**story, "music": music_for(story)}
    silhouette_render.render(story, times, Path(out), progress=progress, beds_db=beds)
    return {"times": times, "seconds": round(sum(t["seconds"] for t in times), 2), "chapters": chapters(story, times),
            "music": story["music"]}


# --- the short version -------------------------------------------------------------------------------------------------------
def short_story(story: dict, short: dict | None = None) -> dict:
    """The short version as a story of its own: the film's shots Agent 2 picked (story["short"], or `short`), each drawn
    as in the film (its seed: "film_shot" says which it is) with the short version's bubbles. Its first shot fades in; a
    light switching off between two of the film's shots isn't between these two, so it's a fade."""
    picked = (short if short is not None else story.get("short") or {}).get("shots") or []
    shots = []
    for j, s in enumerate(picked):
        k = int(s["shot"]) - 1
        if not 0 <= k < len(story["shots"]):
            continue
        base = story["shots"][k]
        enter = "fade" if j == 0 or base.get("enter") == "lights_out" else (base.get("enter") or "cut")
        bubbles = [dict(b) for b in s.get("bubbles") or [] if b.get("kind") in W.BUBBLE_KINDS]
        shots.append({**base, "bubbles": bubbles, "line": "", "enter": enter, "seed": k * 101 + 7, "film_shot": k + 1,
                      "seconds": float(base.get("seconds") or SHORT_SILENT[0]) if not bubbles else 0.0,
                      "shortest": 0.0})
    for s in shots:
        s.pop("line_index", None)
    out = {"title": story.get("title") or "", "theme": story.get("theme"), "closing_line": story.get("closing_line") or "",
           "music": story.get("music"), "music_from": story.get("music_from"), "shots": shots,
           "places": story.get("places") or [], "cast": story.get("cast") or []}
    if story.get("realization") is not None:   # (the music lifts at the first of its shots from his realization on)
        out["realization"] = next((j for j, s in enumerate(shots) if s["film_shot"] - 1 >= int(story["realization"])),
                                  None)
    return out


def short_timeline(short: dict) -> list[dict]:
    """timeline() for the short version (short_story's): tighter, fitted inside SHORT_SECONDS."""
    return timeline(short, bounds=SHORT_SECONDS, lead=SHORT_LEAD, tail=SHORT_TAIL, hold=SHORT_CLOSING_HOLD,
                    silences=SHORT_SILENT, event_shortest=SHORT_EVENT_SHORTEST, opening=SHORT_OPENING)


def make_short(story: dict, out: Path, progress=print, beds: float = 0.0) -> dict:
    """The short version (1080x1920): the film's shots Agent 2 picked, drawn upright with its bubbles, each place's
    sounds and the music. Returns its timing and the film's shots it shows."""
    import silhouette_render

    short = {**short_story(story), "music": music_for(story)}
    if not short["shots"]:
        raise RuntimeError("the story has no short version to make")
    times = short_timeline(short)
    silhouette_render.render(short, times, Path(out), progress=progress, beds_db=beds, upright=True)
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
    parser.add_argument("story", help="a storyboarded story's JSON (or {\"story\": ...})")
    parser.add_argument("out")
    args = parser.parse_args()
    data = json.loads(Path(args.story).read_text(encoding="utf-8"))
    story = data.get("story") or data
    made = make(story, Path(args.out))
    print(json.dumps({k: v for k, v in made.items() if k != "times"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
