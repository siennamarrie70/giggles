"""
Storage for the pipeline: Postgres (Neon) in the cloud, a SQLite file locally.

DATABASE_URL set -> Postgres. Not set -> .tmp/ezzy.db, for local runs only. On
Vercel a missing DATABASE_URL is an error, since /tmp doesn't survive between runs.
Tables are created automatically on first use, and new columns are added to old tables.

A Short "making" or "scheduled" holds its posting slot: a unique index lets only one
run claim each slot, even when Vercel delivers the same cron call twice.

Usage:
    python tools/db.py recent      # latest videos and job runs
"""

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from common import ON_VERCEL, env, tmp_path

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
)
"""
# Columns added after the first release, for databases created before them.
NEW_COLUMNS = {"slot": "TEXT", "claimed_at": "TEXT"}
SLOT_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS one_short_per_slot ON videos (slot) "
              "WHERE status IN ('making', 'scheduled')")
VIDEO_FIELDS = {"status", "youtube_id", "publish_at", "attempts", "error", "plan", "slot", "claimed_at", "theme",
                "trend", "format"}

_schema_ready = False


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
    if url:
        import psycopg
        from psycopg.rows import dict_row

        # prepare_threshold=None: Neon's pooled connections don't support prepared statements.
        raw = psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None)
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
    if "plan" in fields:
        fields["plan"] = json.dumps(fields["plan"])
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


def next_planned() -> dict | None:
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE status = 'planned' ORDER BY id LIMIT 1")
    return _video(rows[0] if rows else None)


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
                 (kind, json.dumps(body), now_iso()))


def latest_note(kind: str):
    with connect() as db:
        rows = db.query("SELECT body FROM notes WHERE kind = %s ORDER BY id DESC LIMIT 1", (kind,))
    return json.loads(rows[0]["body"]) if rows else None


def keep_note(kind: str, body: dict | list | str) -> None:
    """Like add_note, for notes where only the latest matters: one row, replaced each time."""
    with connect() as db:
        if not db.query("UPDATE notes SET body = %s, created_at = %s WHERE kind = %s RETURNING id",
                        (json.dumps(body), now_iso(), kind)):
            db.query("INSERT INTO notes (kind, body, created_at) VALUES (%s, %s, %s)", (kind, json.dumps(body), now_iso()))


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


def start_run(job: str) -> int:
    with connect() as db:
        return db.query("INSERT INTO runs (job, started_at) VALUES (%s, %s) RETURNING id", (job, now_iso()))[0]["id"]


def finish_run(run_id: int, ok: bool, detail: dict) -> None:
    with connect() as db:
        db.query("UPDATE runs SET finished_at = %s, ok = %s, detail = %s WHERE id = %s",
                 (now_iso(), int(ok), json.dumps(detail, default=str)[:4000], run_id))


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
