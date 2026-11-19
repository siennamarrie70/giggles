"""
The channel: one 3-4 minute motivation story a day (your idea since 2026-11-15), drawn in code in your silhouette look
(an ordinary man's habit ruins his life, something wakes him, he works on himself, reaches the life he wanted and calmly
turns down what turned him down), told without a narrator (since 2026-11-19: its people talk and think in bubbles),
and its short version: the same story in under a minute for YouTube Shorts and Instagram Reels (your choice,
2026-11-16: it replaced the teaser). Six agents make it:

  1 theme       the day's theme (a vice or a virtue, alternating) and the brief for your script writer (agents/theme.py)
  2 story       the story (your script writer's prompt), its moments with their bubbles, and the short version's
                (agents/story.py)
  3 animator    storyboards it, times every shot to its bubbles' reading and draws the film in code with the music, the
                thumbnail, then the short version upright (agents/storyboard.py, tools/story_film.py,
                tools/silhouette_render.py)
  4 reviewer    watches the film and its short version; a failure is fixed or made again by itself
                (agents/reviewer.py)
  5 publisher   uploads the film into its slot and its short version as a Short a few hours later, and the short version
                as a Reel (agents/publisher.py)
  6 analyst     reads the numbers, watch time first, and teaches the others (agents/analyst.py)

Its settings are `series:` in config/channel.yaml (the dashboard's Settings page). The documentary case-study Shorts that
came before were removed on 2026-11-16 (your choice); they're kept only in git (tags v5-before-motivation and
v6-motivation-series). A row in the database is a story when its format is STORY (db.FORMAT).
"""

from common import CONFIG_DIR, load_config

STORY = "story"  # the stories' rows (videos.format)
LOOK = "silhouette"  # the look a film is drawn in now (plan["render"]["look"]): a film drawn in an earlier look is never
                     # uploaded as it is (agents/publisher.py choose(), agents/reviewer.py reviewed())
DEFAULTS = {
    "post_at": "17:30", "short_after_hours": 3, "minutes": [3, 4], "repeat_after_days": 30,
    "themes": {"vices": ["laziness", "procrastination", "comfort"], "virtues": ["discipline", "focus", "patience"]},
    "category_id": "1", "language": "en", "hashtags": ["#motivation", "#animation", "#shortfilm"],
    "narrator": {"name": "Algieba", "model": "gemini-3.8-flash-lite-tts", "deeper": 0,
                 "style": ("A calm, warm man in his fifties, like a kind mentor telling a story late at night: unhurried, "
                           "gentle and hopeful, with soft natural pauses. Never dramatic, never theatrical, never cheerful.")},
}
_cache: dict = {"mtime": None, "series": {}}


def settings() -> dict:
    """The stories' settings (defaults filled in), read again only when channel.yaml has changed."""
    try:
        mtime = (CONFIG_DIR / "channel.yaml").stat().st_mtime_ns
    except OSError:
        mtime = None
    if mtime is None or _cache["mtime"] != mtime:
        _cache.update(mtime=mtime, series=dict(load_config().get("series") or {}))
    raw = dict(_cache["series"])
    if "short_after_hours" not in raw and "teaser_after_hours" in raw:  # (its name until 2026-11-16)
        raw["short_after_hours"] = raw["teaser_after_hours"]
    raw.pop("teaser_after_hours", None)
    return {**DEFAULTS, **raw, "themes": {**DEFAULTS["themes"], **(raw.get("themes") or {})},
            "narrator": {**DEFAULTS["narrator"], **(raw.get("narrator") or {})}}


def short_after_hours() -> float:
    """How long after the film its short version goes public (hours)."""
    try:
        return max(0.0, float(settings().get("short_after_hours")))
    except (TypeError, ValueError):
        return float(DEFAULTS["short_after_hours"])


def is_story(row: dict | None) -> bool:
    """Is this database row one of the stories (not a row an earlier version of the channel made)?"""
    return bool(row) and row.get("format") == STORY


def current(row: dict | None) -> bool:
    """Is this a story the agents can make and post now: a story whose shots are drawn in the look (Agent 3's storyboard:
    each in its place and stage; or, before 2026-11-17, each in a ready-made set and a part), and, if its film is made,
    drawn in the look of now? An older row is never uploaded as it is."""
    if not is_story(row):
        return False
    plan = row.get("plan") or {}
    shots = (plan.get("story") or {}).get("shots") or []
    if not shots or not all(s.get("act") and (s.get("set") or s.get("place")) for s in shots):
        return False
    made = plan.get("render") or {}
    return not made.get("id") or made.get("look") == LOOK


def narrator() -> dict:
    """The narrator's voice settings, as tools/narration.py takes them (name, model, style, deeper)."""
    return dict(settings()["narrator"])


def themes() -> dict[str, list[str]]:
    """The themes Agent 1 picks from: {"vices": [...], "virtues": [...]} (lower case, no repeats, none empty)."""
    out = {}
    for kind in ("vices", "virtues"):
        seen = []
        for t in settings()["themes"].get(kind) or []:
            t = " ".join(str(t).split()).strip().lower()
            if t and t not in seen:
                seen.append(t)
        out[kind] = seen
    return out


def minutes() -> tuple[float, float]:
    low, high = (list(settings().get("minutes") or [3, 4]) + [4])[:2]
    low, high = float(low), float(high)
    return (min(low, high), max(low, high))
