"""
The posting timetable (your plan of 2026-11-23): two Shorts a night for `series.cycle.short_days` (3) nights, at
`series.cycle.shorts_at` (21:00, then 03:00 that same night), each one also a Reel on Instagram at the same time; then a
night with one long story (3-4 minutes) at `series.cycle.long_at` (21:00), on YouTube only; then round again. On the
clock of `schedule.timezone` (config/channel.yaml). The moment a video goes public is its "slot", and every slot is for
one form of video: a Short ("short") or a long story ("long").

A posting day (a night) runs from noon to noon (DAY_STARTS), so the 03:00 Short is the same night's second one. The
rounds count from `series.cycle.start`, the first night of Shorts. Every night before it (or every night, with no start)
is a night of the plan before: one long story at long_at.

When a slot needs its video (opens): with `schedule.ahead` (on, your choice of 2026-11-19), the moment the slot
`schedule.stories_ahead` (4) before it goes public: about two days of videos are always made or on their way, so one
that gets stuck (Gemini, GitHub's late checks) has time before its slot could go empty. Made when the free quotas allow
(tools/jobs.py quota_short); the cloud looks every hour. Without `ahead`, in the morning run of its own day, from
`schedule.make_at` (07:00).

Usage:
    python tools/slots.py            # the next nine nights' slots, each with its form, in the schedule's time and UTC
"""

import argparse
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from common import load_config

ISO = "%Y-%m-%dT%H:%M:%SZ"
CLOCK = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
MIN_LEAD = timedelta(minutes=60)  # the morning run starts at least this long before a day's first video (a story takes
                                  # 15-30 minutes to make on GitHub's machine)
STORIES_AHEAD = (1, 8)            # videos kept ready ahead with `ahead`, fewest and most
STORIES_AHEAD_DEFAULT = 4         # about two days of videos (your plan of 2026-11-23: 7 videos every 4 days)
DAY_STARTS = time(12, 0)          # a posting day (a night) runs from noon to noon: the 03:00 Short is the night's second
FORMS = ("short", "long")
FORM_WORDS = {"short": "Short", "long": "long story"}
SHORT_DAYS = (1, 6)               # nights of Shorts before each long story's night, fewest and most
SHORTS_MOST = 3                   # Shorts a night at most
CYCLE_DEFAULT = {"start": "", "short_days": 3, "shorts_at": ["21:00", "03:00"], "long_at": "21:00"}


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(ISO)


def parse(text: str) -> datetime:
    return datetime.strptime(text, ISO).replace(tzinfo=timezone.utc)


def _minutes(clock_time: str) -> int:
    hour, minute = (int(x) for x in clock_time.split(":"))
    return hour * 60 + minute


def _after_noon(clock_time: str) -> int:
    """Minutes from the posting day's start (noon) to this time of that night."""
    return (_minutes(clock_time) - (DAY_STARTS.hour * 60 + DAY_STARTS.minute)) % (24 * 60)


def _clock(text, what: str) -> str:
    text = str(text or "").strip()
    if not CLOCK.fullmatch(text):
        raise ValueError(f"{what}: a time like 21:00.")
    return text


def validate_cycle(raw: dict | None) -> dict:
    """The posting plan (series.cycle) checked and normalised; ValueError says what's wrong in plain words. (A time
    alone, as before the plan: the long story's.)"""
    if isinstance(raw, str):
        raw = {"long_at": raw}
    raw = {**CYCLE_DEFAULT, **(raw or {})}
    start = str(raw.get("start") or "").strip()
    if start:
        try:
            date.fromisoformat(start)
        except ValueError:
            raise ValueError("The plan starts on: a date like 2026-11-27.")
    try:
        days = int(str(raw.get("short_days")).strip())
    except ValueError:
        days = 0
    if not SHORT_DAYS[0] <= days <= SHORT_DAYS[1]:
        raise ValueError(f"Nights of Shorts before each long story: {SHORT_DAYS[0]} to {SHORT_DAYS[1]}.")
    shorts = raw.get("shorts_at")
    if isinstance(shorts, str):
        shorts = shorts.replace(",", " ").split()
    shorts = [_clock(s, "Shorts at") for s in shorts or []]
    if not 1 <= len(shorts) <= SHORTS_MOST:
        raise ValueError(f"Shorts at: 1 to {SHORTS_MOST} times.")
    order = [_after_noon(s) for s in shorts]
    if order != sorted(set(order)):
        raise ValueError("Shorts at: the times in the order they go out, within a night from noon to noon (21:00 then "
                         "03:00: the 03:00 one after midnight, that same night).")
    return {"start": start, "short_days": days, "shorts_at": shorts, "long_at": _clock(raw.get("long_at"), "Long story at")}


def validate(raw: dict, cycle: dict | None = None) -> dict:
    """The schedule settings (and the posting plan, series.cycle) checked and normalised; ValueError says what's wrong
    in plain words."""
    zone = str(raw.get("timezone") or "").strip()
    try:
        ZoneInfo(zone)
    except Exception:
        raise ValueError(f"Time zone: '{zone}' isn't one. Use a name like Asia/Kolkata or America/New_York.")
    c = validate_cycle(cycle)
    make = str(raw.get("make_at") or "07:00").strip()
    if not CLOCK.fullmatch(make):
        raise ValueError("Morning run: a time like 07:00.")
    first = min(c["shorts_at"][0], c["long_at"], key=_after_noon)  # (a night's first video, on make_at's calendar day)
    first_at = _minutes(first) + (24 * 60 if _minutes(first) < DAY_STARTS.hour * 60 + DAY_STARTS.minute else 0)
    if first_at - _minutes(make) < MIN_LEAD.total_seconds() / 60:
        raise ValueError(f"Morning run: start it at least {MIN_LEAD.seconds // 60} minutes before the day's first video "
                         f"({first}).")
    ahead = raw.get("ahead", True)
    if not isinstance(ahead, bool):
        ahead = str(ahead).strip().lower() in ("true", "1", "yes", "on")
    ready = raw.get("stories_ahead", STORIES_AHEAD_DEFAULT)
    try:
        ready = int(str(ready).strip())
    except ValueError:
        raise ValueError(f"Videos ready ahead: a number, {STORIES_AHEAD[0]} to {STORIES_AHEAD[1]}.")
    if not STORIES_AHEAD[0] <= ready <= STORIES_AHEAD[1]:
        raise ValueError(f"Videos ready ahead: {STORIES_AHEAD[0]} to {STORIES_AHEAD[1]}.")
    return {"timezone": zone, "make_at": make, "ahead": ahead, "stories_ahead": ready, **c,
            "post_at": c["long_at"]}  # (post_at: the long story's time, the dashboard's name for it before the plan)


def _time(clock_time: str) -> time:
    return time(*divmod(_minutes(clock_time), 60))


def plan(cfg: dict | None = None) -> dict:
    """The schedule from channel.yaml, ready for the functions below. (A channel.yaml from before the plan, with only
    series.post_at: one long story a night at that time.)"""
    cfg = cfg or load_config()
    series_cfg = cfg.get("series") or {}
    cycle = dict(series_cfg.get("cycle") or {})
    if not cycle.get("long_at") and series_cfg.get("post_at"):
        cycle["long_at"] = series_cfg["post_at"]
    s = validate(cfg.get("schedule") or {}, cycle)
    return {"tz": ZoneInfo(s["timezone"]), "make": _time(s["make_at"]), "every": timedelta(hours=24),
            "shorts": [_time(t) for t in s["shorts_at"]], "long": _time(s["long_at"]),
            "cycle_start": date.fromisoformat(s["start"]) if s["start"] else None, **s}


def clock(slot: datetime, sched: dict) -> str:
    """A slot as the schedule's clock shows it, e.g. 21:00."""
    return slot.astimezone(sched["tz"]).strftime("%H:%M")


def day_form(day: date, sched: dict) -> str:
    """What a posting day (a night) has: "short" (its Shorts) or "long" (its long story; every night before the plan's
    start too)."""
    start = sched.get("cycle_start")
    if not start or day < start:
        return "long"
    return "short" if (day - start).days % (int(sched["short_days"]) + 1) < int(sched["short_days"]) else "long"


def cycle_day(day: date, sched: dict) -> int | None:
    """Which night of its round a posting day is (1 = the first night of Shorts; short_days + 1 = the long story's), or
    None before the plan's start."""
    start = sched.get("cycle_start")
    if not start or day < start:
        return None
    return (day - start).days % (int(sched["short_days"]) + 1) + 1


def day_slots(day: date, sched: dict) -> list[datetime]:
    """The slots of the posting day `day` (the night that begins on that date, on the schedule's clock), in UTC, in the
    order they go out: its Shorts, or its long story."""
    times = sched["shorts"] if day_form(day, sched) == "short" else [sched["long"]]
    return [datetime.combine(day if t >= DAY_STARTS else day + timedelta(days=1), t, tzinfo=sched["tz"])
            .astimezone(timezone.utc) for t in times]


def posting_day(slot: datetime, sched: dict) -> date:
    """The posting day (night) a moment belongs to: noon to noon on the schedule's clock."""
    local = slot.astimezone(sched["tz"])
    return local.date() if local.time() >= DAY_STARTS else local.date() - timedelta(days=1)


def form(slot: datetime, sched: dict) -> str:
    """A slot's form: "short" or "long" (its night's)."""
    return day_form(posting_day(slot, sched), sched)


def run_starts(day: date, sched: dict) -> datetime:
    """When the run that makes `day`'s videos starts (make_at that morning), in UTC."""
    return datetime.combine(day, sched["make"], tzinfo=sched["tz"]).astimezone(timezone.utc)


def opens(slot: datetime, sched: dict) -> datetime:
    """When a slot starts needing its video: with `ahead`, the moment the slot `stories_ahead` before it goes public
    (with 4, the one four videos before it: about two days ahead); without, its posting day's morning run (make_at)."""
    if sched.get("ahead"):
        n = max(1, int(sched.get("stories_ahead") or 1))
        earlier = between(slot - timedelta(days=n + 3), slot - timedelta(seconds=1), sched)
        return earlier[-n] if len(earlier) >= n else slot - n * sched["every"]
    return run_starts(posting_day(slot, sched), sched)


def day_word(slot: datetime, sched: dict, now: datetime | None = None) -> str:
    """A slot's day on the schedule's clock, as its date (a 03:00 Short: the morning after its night): "Today's",
    "Tomorrow's" or e.g. "Friday's"."""
    now = now or datetime.now(timezone.utc)
    when = slot.astimezone(sched["tz"]).date()
    days = (when - now.astimezone(sched["tz"]).date()).days
    return {0: "Today's", 1: "Tomorrow's"}.get(days) or f"{when:%A}'s"


def between(start: datetime, end: datetime, sched: dict) -> list[datetime]:
    """Every slot from start to end, earliest first."""
    day, last = posting_day(start, sched) - timedelta(days=1), posting_day(end, sched) + timedelta(days=1)
    found = []
    while day <= last:
        found += [s for s in day_slots(day, sched) if start <= s <= end]
        day += timedelta(days=1)
    return sorted(set(found))


def shown_day(now: datetime, sched: dict) -> date:
    """The posting day a dashboard shows at `now`: the one under way, or the next one once its last video is an hour
    public and the next one goes public within five hours."""
    day = posting_day(now, sched) - timedelta(days=1)
    while True:
        switch = max(day_slots(day, sched)[-1] + timedelta(hours=1),
                     day_slots(day + timedelta(days=1), sched)[0] - timedelta(hours=5))
        if now < switch:
            return day
        day += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--days", type=int, default=9, help="nights shown (default 9)")
    args = parser.parse_args()
    try:
        sched = plan()
    except (KeyError, ValueError) as e:
        print(f"Error: schedule in config/channel.yaml: {e}", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    today = shown_day(now, sched)
    start = sched["cycle_start"]
    print(f"The plan: {sched['short_days']} nights of Shorts at {' and '.join(sched['shorts_at'])}, then a long story at "
          f"{sched['long_at']} ({sched['timezone']}); "
          + (f"its first round starts on {start:%a %d %b %Y}." if start else "no start date: one long story a night."))
    for n in range(max(1, args.days)):
        day = today + timedelta(days=n)
        night = cycle_day(day, sched)
        label = f"night {night}" if night else "before the plan"
        for s in day_slots(day, sched):
            local = s.astimezone(sched["tz"])
            print(f"  {day:%a %d %b} ({label}): {FORM_WORDS[form(s, sched)]:<10} {local:%a %H:%M} = {iso(s)}"
                  f"{'  (past)' if s < now else ''}; made from {opens(s, sched).astimezone(sched['tz']):%a %H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
