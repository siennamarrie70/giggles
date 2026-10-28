"""
The posting timetable: the moments ("slots") Shorts go public, from `schedule` in
config/channel.yaml: the first post of the day, then one every N hours, on one time zone's clock.

A posting day can run past midnight. With 08:00, every 2 hours, 10 a day, the last slot is
02:00 the next morning and still belongs to the day that started at 08:00.

Each posting day's Shorts are made in one run that starts at `make_at` (07:00) that morning: from
then on, every open slot of the day is due (tools/jobs.py morning).

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
EVERY_HOURS = (1, 1.5, 2, 3, 4, 6, 8, 12)
# 12 a day fits one morning run well inside GitHub's 6-hour job limit (10-15 minutes a Short).
MAX_PER_DAY = 12
MIN_LEAD = timedelta(minutes=30)  # the morning run starts at least this long before the first post


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO)


def parse(text: str) -> datetime:
    return datetime.strptime(text, ISO).replace(tzinfo=timezone.utc)


def validate(raw: dict) -> dict:
    """The schedule settings checked and normalised; ValueError says what's wrong in plain words."""
    zone = str(raw.get("timezone") or "").strip()
    try:
        ZoneInfo(zone)
    except Exception:
        raise ValueError(f"Time zone: '{zone}' isn't one. Use a name like Asia/Kolkata or America/New_York.")
    first = str(raw.get("first_post") or "").strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", first):
        raise ValueError("First post: a time like 08:00.")
    try:
        every, count = float(raw.get("every_hours")), int(raw.get("posts_per_day"))
    except (TypeError, ValueError):
        raise ValueError("Hours between posts and posts per day must be numbers.")
    if every not in EVERY_HOURS:
        raise ValueError(f"Hours between posts: one of {', '.join(f'{h:g}' for h in EVERY_HOURS)}.")
    if not 1 <= count <= MAX_PER_DAY:
        raise ValueError(f"Posts per day: 1 to {MAX_PER_DAY}.")
    if (count - 1) * every >= 24:
        raise ValueError(f"{count} posts {every:g} hours apart don't fit in one day.")
    make = str(raw.get("make_at") or "07:00").strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", make):
        raise ValueError("Morning run: a time like 07:00.")
    if _minutes(first) - _minutes(make) < MIN_LEAD.total_seconds() / 60:
        raise ValueError(f"Morning run: start it at least {MIN_LEAD.seconds // 60} minutes before the first post "
                         f"({first}).")
    return {"timezone": zone, "first_post": first, "every_hours": int(every) if every.is_integer() else every,
            "posts_per_day": count, "make_at": make}


def _minutes(clock_time: str) -> int:
    hour, minute = (int(x) for x in clock_time.split(":"))
    return hour * 60 + minute


def plan(cfg: dict | None = None) -> dict:
    """The schedule from channel.yaml, ready for the functions below."""
    s = validate((cfg or load_config())["schedule"])
    first, make = (divmod(_minutes(s[key]), 60) for key in ("first_post", "make_at"))
    return {"tz": ZoneInfo(s["timezone"]), "first": time(*first), "make": time(*make),
            "every": timedelta(hours=s["every_hours"]), "count": s["posts_per_day"], **s}


def clock(slot: datetime, sched: dict) -> str:
    """A slot as the schedule's clock shows it, e.g. 10:00."""
    return slot.astimezone(sched["tz"]).strftime("%H:%M")


def day_slots(day: date, sched: dict) -> list[datetime]:
    """The slots of the posting day that starts on `day` (a date on the schedule's clock), in UTC."""
    start = datetime.combine(day, sched["first"], tzinfo=sched["tz"])
    # Adding to an aware datetime moves the wall clock, so "every 2 hours" stays on the hour across DST.
    return [(start + k * sched["every"]).astimezone(timezone.utc) for k in range(sched["count"])]


def posting_day(slot: datetime, sched: dict) -> date:
    """The posting day a slot belongs to: 02:00 belongs to the day that started at 08:00 the morning before."""
    local = slot.astimezone(sched["tz"])
    return local.date() if local.time() >= sched["first"] else local.date() - timedelta(days=1)


def run_starts(day: date, sched: dict) -> datetime:
    """When the run that makes `day`'s Shorts starts (make_at that morning), in UTC."""
    return datetime.combine(day, sched["make"], tzinfo=sched["tz"]).astimezone(timezone.utc)


def between(start: datetime, end: datetime, sched: dict) -> list[datetime]:
    """Every slot from start to end, earliest first."""
    first_day = start.astimezone(sched["tz"]).date() - timedelta(days=1)
    found = []
    for n in range((end - start).days + 3):
        found += [s for s in day_slots(first_day + timedelta(days=n), sched) if start <= s <= end]
    return sorted(set(found))


def shown_day(now: datetime, sched: dict) -> date:
    """The posting day a dashboard shows at `now`: the one under way, or the next one once the
    last slot is an hour gone and the next day starts within five hours."""
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
        print(f"Posting day {day:%a %d %b} ({sched['timezone']}), made from {sched['make_at']}:")
        for s in day_slots(day, sched):
            local = s.astimezone(sched["tz"])
            print(f"  {local:%a %H:%M}  =  {iso(s)}{'  (past)' if s < now else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
