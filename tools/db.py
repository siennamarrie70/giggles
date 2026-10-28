"""
Storage for the pipeline: Postgres (Neon) in the cloud, a SQLite file locally.

DATABASE_URL set -> Postgres. Not set -> .tmp/ezzy.db, for local runs only. On
Vercel a missing DATABASE_URL is an error, since /tmp doesn't survive between runs.
Tables are created automatically on first use, and new columns are added to old tables
(only ever added, so an older version of the app still works on the same database).

What the agents hand each other lives here: videos whose plan holds the brief (Agent 1), the
research pack (Agent 2), the script (Agent 3), the render, its review and the upload (Agents 4, 5 and 6); stats
and viewers' comments (Agent 7); topics you ask for; the two hosts (characters); and notes (the
playbook, caches, heartbeats). Only rows of FORMAT are the case studies: older versions' Shorts
share the database and are left alone.

A Short "making" or "scheduled" holds its posting slot: a unique index lets only one
run claim each slot, even when Vercel delivers the same cron call twice.

Usage:
    python tools/db.py recent      # latest videos and job runs
"""

import argparse
import contextvars
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from common import ON_VERCEL, env, redact, tmp_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id {pk},
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    format TEXT,
    theme TEXT,
    trend TEXT,
    plan TEXT NOT NULL,
    youtube_id TEXT,
    publish_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    slot TEXT,
    claimed_at TEXT
);
CREATE TABLE IF NOT EXISTS used_clips (
    clip_key TEXT PRIMARY KEY,
    used_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id {pk},
    job TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS stats (
    youtube_id TEXT NOT NULL,
    taken_on TEXT NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    avg_view_pct REAL,
    avg_view_seconds REAL,
    subs_gained INTEGER,
    PRIMARY KEY (youtube_id, taken_on)
);
CREATE TABLE IF NOT EXISTS notes (
    id {pk},
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
    id {pk},
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    spec TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id {pk},
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    video_id INTEGER
);
CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    youtube_id TEXT NOT NULL,
    text TEXT NOT NULL,
    likes INTEGER,
    published_at TEXT,
    used_by INTEGER
)
"""
FORMAT = "doc"  # the documentary cases' rows (v5); "case" rows are v4's cartoon-host cases, other formats earlier versions'
# Columns added after the first release, for databases created before them.
NEW_COLUMNS = {"slot": "TEXT", "claimed_at": "TEXT"}
CONNECT_TIMEOUT = 20  # seconds the cloud database may take to answer a new connection
SLOT_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS one_short_per_slot ON videos (slot) "
              "WHERE status IN ('making', 'scheduled')")
VIDEO_FIELDS = {"status", "youtube_id", "publish_at", "attempts", "error", "plan", "slot", "claimed_at", "theme",
                "trend", "format"}

_schema_ready = False
_held: contextvars.ContextVar[dict | None] = contextvars.ContextVar("held_connection", default=None)


@contextmanager
def held():
    """Within it, the cloud database's connection is shared: the first connect() opens it, the others reuse it, and
    it closes at the end, so nothing stays open to keep Neon awake. The web app holds one per request (app.py): a
    dashboard page's ~25 reads then cost one connection instead of 25 (each ~0.6 s from India, more from the US). A
    thread started inside doesn't inherit it: a background task opens its own."""
    holder: dict = {}
    token = _held.set(holder)
    try:
        yield
    finally:
        _held.reset(token)
        if holder.get("raw") is not None:
            holder["raw"].close()


def now_iso(delta: timedelta = timedelta()) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Conn:
    """Same query() call for Postgres and SQLite; SQL is written with %s placeholders."""

    def __init__(self, conn, sqlite: bool):
        self.conn, self.sqlite = conn, sqlite

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.sqlite:
            sql = sql.replace("%s", "?")
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()] if cur.description else []


@contextmanager
def connect():
    global _schema_ready
    url = env("DATABASE_URL") or env("POSTGRES_URL")
    holder = _held.get() if url else None  # (inside held(): the request's shared connection)
    if url:
        import psycopg
        from psycopg.rows import dict_row

        raw = holder.get("raw") if holder is not None else None
        if raw is None or raw.closed or raw.broken:
            if raw is not None:
                raw.close()
            # prepare_threshold=None: Neon's pooled connections don't support prepared statements. connect_timeout:
            # a database that doesn't answer fails in CONNECT_TIMEOUT seconds instead of holding a run (Neon wakes
            # in ~1-5 s).
            raw = psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                                  connect_timeout=CONNECT_TIMEOUT)
            if holder is not None:
                holder["raw"] = raw
        conn, pk = _Conn(raw, sqlite=False), "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    else:
        if ON_VERCEL:
            raise RuntimeError("DATABASE_URL is not set. Connect a Neon database to the Vercel project.")
        raw = sqlite3.connect(tmp_path("ezzy.db"))
        raw.row_factory = sqlite3.Row
        conn, pk = _Conn(raw, sqlite=True), "INTEGER PRIMARY KEY AUTOINCREMENT"
    try:
        if not _schema_ready:
            for statement in filter(str.strip, SCHEMA.format(pk=pk).split(";")):
                conn.query(statement)
            have = ({r["name"] for r in conn.query("PRAGMA table_info(videos)")} if conn.sqlite else
                    {r["column_name"] for r in conn.query("SELECT column_name FROM information_schema.columns "
                                                          "WHERE table_name = 'videos'")})
            for column, kind in NEW_COLUMNS.items():
                if column not in have:
                    conn.query(f"ALTER TABLE videos ADD COLUMN {column} {kind}")
            conn.query(SLOT_INDEX)
            _schema_ready = True
        yield conn
        if conn.sqlite:
            raw.commit()
    finally:
        if holder is None:  # (a held connection closes when held() ends)
            raw.close()


def _video(row: dict | None) -> dict | None:
    if row:
        row["plan"] = json.loads(row["plan"])
    return row


def _slot_taken(error: Exception) -> bool:
    """The unique slot index refused a row: another run claimed that slot first."""
    return isinstance(error, sqlite3.IntegrityError) or type(error).__name__ == "UniqueViolation"


# --- videos ---------------------------------------------------------------

def insert_video(status: str, fmt: str, theme: str | None, trend: str | None, plan: dict,
                 slot: str | None = None) -> int | None:
    """New row; with a slot it also claims that slot, and returns None if another run has it."""
    try:
        with connect() as db:
            return db.query("INSERT INTO videos (created_at, status, format, theme, trend, plan, slot, claimed_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            (now_iso(), status, fmt, theme, trend, json.dumps(plan), slot,
                             now_iso() if slot else None))[0]["id"]
    except Exception as e:
        if slot and _slot_taken(e):
            return None
        raise


def update_video(video_id: int, **fields) -> None:
    unknown = set(fields) - VIDEO_FIELDS
    if unknown:
        raise ValueError(f"unknown video fields: {unknown}")
    if "plan" in fields:  # (secrets never go into the database: an error kept on a case can quote a web address)
        fields["plan"] = redact(json.dumps(fields["plan"]), addresses=False)
    if fields.get("error"):
        fields["error"] = redact(fields["error"])
    with connect() as db:
        db.query(f"UPDATE videos SET {', '.join(f'{k} = %s' for k in fields)} WHERE id = %s",
                 (*fields.values(), video_id))


def claim(video_id: int, slot: str) -> bool:
    """Marks a planned Short as being made for `slot`. False if it isn't planned any more or
    another run already holds that slot."""
    try:
        with connect() as db:
            rows = db.query("UPDATE videos SET status = 'making', slot = %s, claimed_at = %s "
                            "WHERE id = %s AND status = 'planned' RETURNING id", (slot, now_iso(), video_id))
    except Exception as e:
        if _slot_taken(e):
            return False
        raise
    return bool(rows)


def release_stale(before: str) -> list[dict]:
    """Shorts stuck in "making" since before `before`: their run was cut off (Vercel stops a job
    at 300 s). With a finished plan they go back to the queue (or fail on the second time);
    without one they're skipped."""
    with connect() as db:
        return db.query("UPDATE videos SET status = CASE WHEN plan = '{}' THEN 'skipped' "
                        "WHEN attempts + 1 >= 2 THEN 'failed' ELSE 'planned' END, attempts = attempts + 1, "
                        "slot = CASE WHEN plan = '{}' THEN slot END, claimed_at = NULL, "
                        "error = 'Interrupted while it was being made' "
                        "WHERE status = 'making' AND claimed_at < %s RETURNING id, status", (before,))


def slot_holders(start: str, end: str) -> list[dict]:
    """Shorts being made or scheduled whose slot (or, for older rows without one, publish
    time) falls between start and end."""
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE status IN ('making', 'scheduled') AND "
                        "(slot BETWEEN %s AND %s OR (slot IS NULL AND publish_at BETWEEN %s AND %s)) ORDER BY id",
                        (start, end, start, end))
    return [_video(r) for r in rows]


def planned_videos(limit: int = 50) -> list[dict]:
    """The queue: cases written and waiting for a slot, oldest first (including those waiting for your
    OK). Shorts planned by earlier versions (other formats) are left to the dashboard."""
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE status = 'planned' AND format = %s ORDER BY id LIMIT %s",
                        (FORMAT, limit))
    return [_video(r) for r in rows]


def ready(video: dict) -> bool:
    """Can it go up without anyone's OK: approved (or it never needed approval), and not held by the Reviewer
    (agents/reviewer.py: a video that still failed after the Animator's fixes is made again by itself first)."""
    plan = video["plan"]
    return plan.get("approval") in (None, "approved") and not (plan.get("review") or {}).get("held")


def next_planned() -> dict | None:
    """The oldest case ready to go up."""
    return next((v for v in planned_videos() if ready(v)), None)


def get_video(video_id: int) -> dict | None:
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE id = %s", (video_id,))
    return _video(rows[0] if rows else None)


def list_videos(limit: int = 30) -> list[dict]:
    with connect() as db:
        rows = db.query("SELECT * FROM videos ORDER BY id DESC LIMIT %s", (limit,))
    return [_video(r) for r in rows]


def status_counts() -> dict[str, int]:
    with connect() as db:
        return {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")}


def recent_runs(limit: int = 30) -> list[dict]:
    with connect() as db:
        return db.query("SELECT * FROM runs ORDER BY id DESC LIMIT %s", (limit,))


def count_videos(status: str | None = None) -> int:
    with connect() as db:
        if status:
            return db.query("SELECT COUNT(*) AS n FROM videos WHERE status = %s", (status,))[0]["n"]
        return db.query("SELECT COUNT(*) AS n FROM videos WHERE status <> 'skipped'")[0]["n"]


def recent_videos(days: int = 21) -> list[dict]:
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE created_at >= %s ORDER BY id DESC", (now_iso(-timedelta(days=days)),))
    return [_video(r) for r in rows]


def published_videos(days: int = 60) -> list[dict]:
    """Shorts whose publish time has passed (they're public unless you vetoed them)."""
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE status = 'scheduled' AND youtube_id IS NOT NULL "
                        "AND publish_at <= %s AND publish_at >= %s ORDER BY publish_at",
                        (now_iso(), now_iso(-timedelta(days=days))))
    return [_video(r) for r in rows]


def scheduled_videos(days: int = 3) -> list[dict]:
    """Shorts on YouTube whose publish time is still to come, or passed at most `days` ago."""
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE status = 'scheduled' AND youtube_id IS NOT NULL "
                        "AND publish_at >= %s ORDER BY publish_at", (now_iso(-timedelta(days=days)),))
    return [_video(r) for r in rows]


# --- clips, stats, notes, runs --------------------------------------------

def used_clip_keys() -> set[str]:
    with connect() as db:
        return {r["clip_key"] for r in db.query("SELECT clip_key FROM used_clips")}


def mark_clips_used(keys: list[str]) -> None:
    with connect() as db:
        for key in keys:
            db.query("INSERT INTO used_clips (clip_key, used_at) VALUES (%s, %s) ON CONFLICT (clip_key) DO NOTHING",
                     (key, now_iso()))


def save_stats(rows: list[dict], taken_on: str) -> None:
    with connect() as db:
        for r in rows:
            db.query("INSERT INTO stats (youtube_id, taken_on, views, likes, comments, avg_view_pct, "
                     "avg_view_seconds, subs_gained) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT (youtube_id, taken_on) DO UPDATE SET views = excluded.views, "
                     "likes = excluded.likes, comments = excluded.comments, avg_view_pct = excluded.avg_view_pct, "
                     "avg_view_seconds = excluded.avg_view_seconds, subs_gained = excluded.subs_gained",
                     (r["youtube_id"], taken_on, r["views"], r["likes"], r["comments"], r["avg_view_pct"],
                      r["avg_view_seconds"], r["subs_gained"]))


def add_note(kind: str, body: dict | list | str) -> None:
    with connect() as db:
        db.query("INSERT INTO notes (kind, body, created_at) VALUES (%s, %s, %s)",
                 (kind, redact(json.dumps(body), addresses=False), now_iso()))


def latest_note(kind: str):
    with connect() as db:
        rows = db.query("SELECT body FROM notes WHERE kind = %s ORDER BY id DESC LIMIT 1", (kind,))
    return json.loads(rows[0]["body"]) if rows else None


def keep_note(kind: str, body: dict | list | str) -> None:
    """Like add_note, for notes where only the latest matters: one row, replaced each time."""
    body = redact(json.dumps(body), addresses=False)
    with connect() as db:
        if not db.query("UPDATE notes SET body = %s, created_at = %s WHERE kind = %s RETURNING id",
                        (body, now_iso(), kind)):
            db.query("INSERT INTO notes (kind, body, created_at) VALUES (%s, %s, %s)", (kind, body, now_iso()))


def paused() -> bool:
    """The dashboard's pause switch, kept here so it also stops the morning run in the cloud."""
    return bool((latest_note("paused") or {}).get("on"))


def set_paused(on: bool) -> None:
    keep_note("paused", {"on": bool(on), "at": now_iso()})


def fresh_note(kind: str, max_age: timedelta):
    """The latest note of this kind if it's younger than max_age, else None."""
    with connect() as db:
        rows = db.query("SELECT body FROM notes WHERE kind = %s AND created_at >= %s ORDER BY id DESC LIMIT 1",
                        (kind, now_iso(-max_age)))
    return json.loads(rows[0]["body"]) if rows else None


def beat(name: str) -> None:
    """Records that `name` (the autopilot) just checked in."""
    keep_note(f"beat:{name}", {})


def last_beat(name: str) -> str | None:
    with connect() as db:
        rows = db.query("SELECT created_at FROM notes WHERE kind = %s", (f"beat:{name}",))
    return rows[0]["created_at"] if rows else None


def latest_stats(youtube_ids: list[str]) -> dict[str, dict]:
    """The newest numbers for each video, with the day they were taken."""
    if not youtube_ids:
        return {}
    marks = ", ".join(["%s"] * len(youtube_ids))
    with connect() as db:
        rows = db.query(f"SELECT * FROM stats WHERE youtube_id IN ({marks}) ORDER BY taken_on", tuple(youtube_ids))
    return {r["youtube_id"]: r for r in rows}  # later days overwrite earlier ones


def last_run(job: str, ok: bool | None = True) -> dict | None:
    """The latest run of a job or agent (only successful ones by default)."""
    with connect() as db:
        if ok is None:
            rows = db.query("SELECT * FROM runs WHERE job = %s ORDER BY id DESC LIMIT 1", (job,))
        else:
            rows = db.query("SELECT * FROM runs WHERE job = %s AND ok = %s ORDER BY id DESC LIMIT 1", (job, int(ok)))
    return rows[0] if rows else None


# --- topics you ask for, viewers' comments ----------------------------------

def add_topic(text: str) -> int:
    with connect() as db:
        return db.query("INSERT INTO topics (created_at, text, status) VALUES (%s, %s, 'waiting') RETURNING id",
                        (now_iso(), text))[0]["id"]


def list_topics(status: str | None = None, limit: int = 50) -> list[dict]:
    with connect() as db:
        if status:
            return db.query("SELECT * FROM topics WHERE status = %s ORDER BY id LIMIT %s", (status, limit))
        return db.query("SELECT * FROM topics ORDER BY id DESC LIMIT %s", (limit,))


def set_topic(topic_id: int, status: str, reason: str | None = None, video_id: int | None = None) -> None:
    with connect() as db:
        db.query("UPDATE topics SET status = %s, reason = %s, video_id = %s WHERE id = %s",
                 (status, reason, video_id, topic_id))


def save_comments(rows: list[dict]) -> int:
    """New top-level comments (text and likes only, never who wrote them); returns how many were new."""
    added = 0
    with connect() as db:
        for r in rows:
            if db.query("SELECT 1 FROM comments WHERE comment_id = %s", (r["comment_id"],)):
                db.query("UPDATE comments SET likes = %s WHERE comment_id = %s", (r["likes"], r["comment_id"]))
                continue
            db.query("INSERT INTO comments (comment_id, youtube_id, text, likes, published_at) VALUES (%s, %s, %s, %s, %s)",
                     (r["comment_id"], r["youtube_id"], r["text"], r["likes"], r["published_at"]))
            added += 1
    return added


def recent_comments(days: int = 30, limit: int = 30, unused: bool = True) -> list[dict]:
    with connect() as db:
        return db.query("SELECT * FROM comments WHERE published_at >= %s" + (" AND used_by IS NULL" if unused else "")
                        + " ORDER BY likes DESC, published_at DESC LIMIT %s", (now_iso(-timedelta(days=days)), limit))


def use_comment(comment_id: str, video_id: int) -> None:
    with connect() as db:
        db.query("UPDATE comments SET used_by = %s WHERE comment_id = %s", (video_id, comment_id))


# --- characters (the hosts) -------------------------------------------------

def insert_character(spec: dict) -> int:
    with connect() as db:
        return db.query("INSERT INTO characters (created_at, name, spec) VALUES (%s, %s, %s) RETURNING id",
                        (now_iso(), spec["name"], json.dumps(spec)))[0]["id"]


def _character(row: dict) -> dict:
    return {**json.loads(row["spec"]), "id": row["id"], "created_at": row["created_at"]}


def get_characters(ids: list[int]) -> list[dict]:
    """Characters in the order asked for."""
    if not ids:
        return []
    marks = ", ".join(["%s"] * len(ids))
    with connect() as db:
        rows = {r["id"]: r for r in db.query(f"SELECT * FROM characters WHERE id IN ({marks})", tuple(ids))}
    return [_character(rows[i]) for i in ids if i in rows]


def list_characters(limit: int = 60) -> list[dict]:
    with connect() as db:
        rows = db.query("SELECT * FROM characters ORDER BY id DESC LIMIT %s", (limit,))
    return [_character(r) for r in rows]


def start_run(job: str) -> int:
    with connect() as db:
        return db.query("INSERT INTO runs (job, started_at) VALUES (%s, %s) RETURNING id", (job, now_iso()))[0]["id"]


def finish_run(run_id: int, ok: bool, detail: dict) -> None:
    with connect() as db:
        db.query("UPDATE runs SET finished_at = %s, ok = %s, detail = %s WHERE id = %s",
                 (now_iso(), int(ok), redact(json.dumps(detail, default=str))[:4000], run_id))


def abandon_runs() -> int:
    """Runs still open when the program starts were cut off when it stopped: they're marked as failed."""
    with connect() as db:
        return len(db.query("UPDATE runs SET finished_at = %s, ok = 0, detail = %s WHERE finished_at IS NULL RETURNING id",
                            (now_iso(), json.dumps({"error": "Interrupted: the program stopped while this was running"}))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("command", choices=["recent"])
    parser.parse_args()

    try:
        with connect() as db:
            videos = db.query("SELECT id, created_at, status, format, theme, youtube_id, publish_at, error "
                              "FROM videos ORDER BY id DESC LIMIT 10")
            runs = db.query("SELECT job, started_at, ok, detail FROM runs ORDER BY id DESC LIMIT 10")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("Videos:")
    for v in videos:
        print(f"  #{v['id']} {v['status']:<9} {v['format'] or '':<9} {v['theme'] or ''}"
              f"  {v['youtube_id'] or ''} {v['publish_at'] or ''} {v['error'] or ''}")
    print("Runs:")
    for r in runs:
        print(f"  {r['started_at']} {r['job']:<8} {'ok' if r['ok'] else 'FAILED' if r['ok'] == 0 else 'running'}"
              f"  {(r['detail'] or '')[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
