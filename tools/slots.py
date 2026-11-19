"""
The posting timetable: one story a day, public at `series.post_at` (17:30) on the clock of `schedule.timezone`
(config/channel.yaml), its short version as a Short series.short_after_hours later. The moment a story goes public is
its "slot".

When a slot needs its story (opens): with `schedule.ahead` (on, your choice of 2026-11-19), `schedule.stories_ahead` slots
before it goes public: with 2 (your choice of 2026-11-19, the default), the moment the story two before it goes public,
so tomorrow's story is always made and the next one on its way: one that gets stuck (his voice, Gemini, GitHub's late
checks) has a spare day before its slot could go empty; with 1, the moment the story before it goes public. Made when
the free quotas allow (tools/jobs.py quota_short); the cloud looks every hour. Without `ahead`, in the morning run of
its own day, from `schedule.make_at` (07:00).

Usage:
    python tools/slots.py            # today's and tomorrow's slots, in the schedule's time and UTC
"""

import argparse
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from common import load_config

ISO = "%Y-%m-%dT%H:%M:%SZ"
CLOCK = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
MIN_LEAD = timedelta(minutes=60)  # the morning run starts at least this long before the story goes public (a story takes
                                  # 15-30 minutes to make on GitHub's machine)
STORIES_AHEAD = (1, 3)            # stories kept ready ahead with `ahead`, fewest and most
STORIES_AHEAD_DEFAULT = 2         # tomorrow's made, the next on its way: a spare day (your choice of 2026-11-19)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO)


def parse(text: str) -> datetime:
    return datetime.strptime(text, ISO).replace(tzinfo=timezone.utc)


def _minutes(clock_time: str) -> int:
    hour, minute = (int(x) for x in clock_time.split(":"))
    return hour * 60 + minute


def validate(raw: dict, post_at: str) -> dict:
    """The schedule settings checked and normalised; ValueError says what's wrong in plain words."""
    zone = str(raw.get("timezone") or "").strip()
    try:
        ZoneInfo(zone)
    except Exception:
        raise ValueError(f"Time zone: '{zone}' isn't one. Use a name like Asia/Kolkata or America/New_York.")
    post_at = str(post_at or "").strip()
    if not CLOCK.fullmatch(post_at):
        raise ValueError("Goes public at: a time like 17:30.")
    make = str(raw.get("make_at") or "07:00").strip()
    if not CLOCK.fullmatch(make):
        raise ValueError("Morning run: a time like 07:00.")
    if _minutes(post_at) - _minutes(make) < MIN_LEAD.total_seconds() / 60:
        raise ValueError(f"Morning run: start it at least {MIN_LEAD.seconds // 60} minutes before the story goes "
                         f"public ({post_at}).")
    ahead = raw.get("ahead", True)
    if not isinstance(ahead, bool):
        ahead = str(ahead).strip().lower() in ("true", "1", "yes", "on")
    ready = raw.get("stories_ahead", STORIES_AHEAD_DEFAULT)
    try:
        ready = int(str(ready).strip())
    except ValueError:
        raise ValueError(f"Stories ready ahead: a number, {STORIES_AHEAD[0]} to {STORIES_AHEAD[1]}.")
    if not STORIES_AHEAD[0] <= ready <= STORIES_AHEAD[1]:
        raise ValueError(f"Stories ready ahead: {STORIES_AHEAD[0]} to {STORIES_AHEAD[1]}.")
    return {"timezone": zone, "post_at": post_at, "make_at": make, "ahead": ahead, "stories_ahead": ready}


def plan(cfg: dict | None = None) -> dict:
    """The schedule from channel.yaml, ready for the functions below: one slot a day at series.post_at."""
    cfg = cfg or load_config()
    s = validate(cfg.get("schedule") or {}, (cfg.get("series") or {}).get("post_at") or "17:30")
    first, make = (divmod(_minutes(s[key]), 60) for key in ("post_at", "make_at"))
    return {"tz": ZoneInfo(s["timezone"]), "first": time(*first), "make": time(*make),
            "every": timedelta(hours=24), "count": 1, **s}


def clock(slot: datetime, sched: dict) -> str:
    """A slot as the schedule's clock shows it, e.g. 17:30."""
    return slot.astimezone(sched["tz"]).strftime("%H:%M")


def day_slots(day: date, sched: dict) -> list[datetime]:
    """The slots of the posting day `day` (a date on the schedule's clock), in UTC: one, the story's."""
    start = datetime.combine(day, sched["first"], tzinfo=sched["tz"])
    return [(start + k * sched["every"]).astimezone(timezone.utc) for k in range(sched["count"])]


def posting_day(slot: datetime, sched: dict) -> date:
    """The posting day a slot belongs to."""
    local = slot.astimezone(sched["tz"])
    return local.date() if local.time() >= sched["first"] else local.date() - timedelta(days=1)


def run_starts(day: date, sched: dict) -> datetime:
    """When the run that makes `day`'s story starts (make_at that morning), in UTC."""
    return datetime.combine(day, sched["make"], tzinfo=sched["tz"]).astimezone(timezone.utc)


def opens(slot: datetime, sched: dict) -> datetime:
    """When a slot starts needing its story: with `ahead`, the moment the slot `stories_ahead` before it comes (that story
    goes public: with 2, the one two before it); without, its posting day's morning run (make_at)."""
    if sched.get("ahead"):
        return slot - int(sched.get("stories_ahead") or 1) * sched["every"]
    return run_starts(posting_day(slot, sched), sched)


def day_word(slot: datetime, sched: dict, now: datetime | None = None) -> str:
    """Whose story a slot holds, by its posting day on the schedule's clock: "Today's", "Tomorrow's" or e.g. "Friday's"."""
    now = now or datetime.now(timezone.utc)
    days = (posting_day(slot, sched) - now.astimezone(sched["tz"]).date()).days
    return {0: "Today's", 1: "Tomorrow's"}.get(days) or f"{posting_day(slot, sched):%A}'s"


def between(start: datetime, end: datetime, sched: dict) -> list[datetime]:
    """Every slot from start to end, earliest first."""
    first_day = start.astimezone(sched["tz"]).date() - timedelta(days=1)
    found = []
    for n in range((end - start).days + 3):
        found += [s for s in day_slots(first_day + timedelta(days=n), sched) if start <= s <= end]
    return sorted(set(found))


def shown_day(now: datetime, sched: dict) -> date:
    """The posting day a dashboard shows at `now`: the one under way, or the next one once its story is an hour public
    and the next one goes public within five hours."""
    day = now.astimezone(sched["tz"]).date() - timedelta(days=1)
    while True:
        switch = max(day_slots(day, sched)[-1] + timedelta(hours=1),
                     day_slots(day + timedelta(days=1), sched)[0] - timedelta(hours=5))
        if now < switch:
            return day
        day += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.parse_args()
    try:
        sched = plan()
    except (KeyError, ValueError) as e:
        print(f"Error: schedule in config/channel.yaml: {e}", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    today = shown_day(now, sched)
    for day in (today, today + timedelta(days=1)):
        for s in day_slots(day, sched):
            print(f"{day:%a %d %b}: the story at {s.astimezone(sched['tz']):%H:%M} ({sched['timezone']}) = {iso(s)}"
                  f"{'  (past)' if s < now else ''}; made from {sched['make_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
