"""
What every agent shares: logging each piece of work as a run of that agent (the dashboard's
agent cards and Activity page read these), the playbook the Analyst writes for the others, and
what each agent has been taught (lessons_for): the Reviewer's standing fixes for problems that keep
coming back, and the Analyst's lessons for that agent from the channel's numbers.
"""

import random
import sys
import time

import db
from common import redact

DEFAULT_PLAYBOOK = {"weights": {}, "lessons": [], "lessons_for": {}, "summary": "", "samples": 0, "updated_at": None}
VARIETY = 0.25  # how often the playbook is left out, so early lessons don't lock the channel in


def log(message: str) -> None:
    print(f"  {redact(message)}", file=sys.stderr, flush=True)


def act(agent: str, what: str, work, *args, progress=log, **kwargs) -> dict:
    """Runs one piece of an agent's work, logged as a run of that agent: what it did, how long it
    took, and the error if it failed (which is raised again for the caller)."""
    run_id = db.start_run(agent)
    started = time.monotonic()
    try:
        result = work(*args, progress=progress, **kwargs)
    except Exception as e:
        db.finish_run(run_id, False, {"what": what, "error": redact(e)})
        raise
    logged = {k: v for k, v in (result or {}).items() if k not in ("brief", "pack", "hosts", "script", "plan", "metadata")}
    db.finish_run(run_id, True, {**logged, "what": what, "seconds": round(time.monotonic() - started, 1)})
    return result


def playbook() -> dict:
    return {**DEFAULT_PLAYBOOK, **(db.latest_note("playbook") or {})}


def advice(kinds: tuple[str, ...]) -> str:
    """What the playbook says about these kinds of choices, for a prompt; empty a quarter of the time
    (and before there's enough data), so the agents keep trying new things."""
    book = playbook()
    if not book["samples"] or random.random() < VARIETY:
        return ""
    lines = []
    for kind in kinds:
        weights = book["weights"].get(kind) or {}
        ranked = sorted(weights.items(), key=lambda kv: -kv[1])
        good = [f"{k} ({v:.1f}x)" for k, v in ranked if v >= 1.15][:3]
        weak = [f"{k} ({v:.1f}x)" for k, v in ranked[::-1] if v <= 0.85][:2]
        if good or weak:
            lines.append(f"{kind}: " + (f"works well: {', '.join(good)}" if good else "")
                         + ("; " if good and weak else "") + (f"weaker: {', '.join(weak)}" if weak else ""))
    lessons = book.get("lessons") or []
    if lessons:
        lines.append("Lessons: " + " | ".join(lessons[:4]))
    return "\n".join(lines)


def lessons_for(agent: str) -> dict:
    """What `agent` has been taught: standing settings and advice from the Reviewer's recurring problems (note
    review:lessons, agents/reviewer.py) and the Analyst's lessons for it from the numbers (the playbook's
    lessons_for). Unlike advice(), never left out: these correct mistakes rather than guess at taste."""
    review = ((db.latest_note("review:lessons") or {}).get("for") or {}).get(agent) or {}
    analyst = (playbook().get("lessons_for") or {}).get(agent) or []
    return {"settings": dict(review.get("settings") or {}),
            "advice": [str(a) for a in review.get("advice") or []] + [str(a) for a in analyst]}


def taught(agent: str) -> str:
    """lessons_for(agent)'s advice for a prompt, or nothing."""
    advice = lessons_for(agent)["advice"]
    return "What you've been taught (the Reviewer's checks and the Analyst's numbers):\n- " + "\n- ".join(advice) + "\n" \
        if advice else ""
