"""
What every agent shares: logging each piece of work as a run of that agent (the dashboard's
agent cards and Activity page read these), and the playbook the Analyst writes for the others.
"""

import random
import sys
import time

import db

DEFAULT_PLAYBOOK = {"weights": {}, "lessons": [], "summary": "", "samples": 0, "updated_at": None}
VARIETY = 0.25  # how often the playbook is left out, so early lessons don't lock the channel in


def log(message: str) -> None:
    print(f"  {message}", file=sys.stderr, flush=True)


def act(agent: str, what: str, work, *args, progress=log, **kwargs) -> dict:
    """Runs one piece of an agent's work, logged as a run of that agent: what it did, how long it
    took, and the error if it failed (which is raised again for the caller)."""
    run_id = db.start_run(agent)
    started = time.monotonic()
    try:
        result = work(*args, progress=progress, **kwargs)
    except Exception as e:
        db.finish_run(run_id, False, {"what": what, "error": str(e)})
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
