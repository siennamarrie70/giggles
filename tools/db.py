"""
Storage for the pipeline: Postgres in the cloud (Aiven since 2026-11-15), a SQLite file locally.

DATABASE_URL set -> Postgres. Not set -> .tmp/ezzy.db, for local runs only. On
Vercel a missing DATABASE_URL is an error, since /tmp doesn't survive between runs.
Tables are created automatically on first use, and new columns are added to old tables
(only ever added, so an older version of the app still works on the same database).

What the agents hand each other lives here: videos (one row a story) whose plan holds the theme and title (Agent 1),
the story and its moments with their bubbles (Agent 2), the film, its review and the upload (Agents 3, 4 and 5); stats
(Agent 6); the themes you ask for (topics); and notes (the playbook, caches, heartbeats). Only rows of FORMAT are the
stories: rows earlier versions of the channel made share the database and are left alone. (Tables only the
case-study Shorts used, before 2026-11-16, stay in an old database untouched: nothing reads them.)

A story "making" or "scheduled" holds its posting slot: a unique index lets only one
run claim each slot, even when the same run is started twice.

Usage:
    python tools/db.py recent      # latest videos and job runs
"""

import argparse
import contextvars
import base64
import json
import re
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
CREATE TABLE IF NOT EXISTS topics (
    id {pk},
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    video_id INTEGER
);
CREATE TABLE IF NOT EXISTS visuals (
    id {pk},
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    says TEXT NOT NULL,
    recipe TEXT NOT NULL,
    made_for TEXT,
    made_at TEXT NOT NULL,
    removed_at TEXT
);
CREATE TABLE IF NOT EXISTS visual_previews (
    name TEXT PRIMARY KEY,
    png TEXT NOT NULL
);

"""
FORMAT = "story"  # the stories' rows (tools/series.py STORY); other formats are earlier versions' ("doc": the case studies)
# Columns added after the first release, for databases created before them.
NEW_COLUMNS = {"slot": "TEXT", "claimed_at": "TEXT"}
CONNECT_TIMEOUT = 20  # seconds the cloud database may take to answer a new connection
SLOT_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS one_short_per_slot ON videos (slot) "
              "WHERE status IN ('making', 'scheduled')")
VIDEO_FIELDS = {"status", "youtube_id", "publish_at", "attempts", "error", "plan", "slot", "claimed_at", "theme",
                "trend", "format"}
# Lists read many times a day (the dashboard every 30 seconds, the Editor and the Writer for every topic, the Reels every
# minute of a run) take only the parts of each case's plan they use (`parts`): a whole plan is 20-50 KB, and reading
# every recent case whole sent out Neon's free 5 GB a month in under two weeks (it locked the database on 2026-11-10
# until its month renewed). A plan read in part carries LIGHT, and update_video won't save it over the whole case.
LIGHT = "_light"
LIGHT_COLUMNS = "id, created_at, status, format, theme, trend, youtube_id, publish_at, attempts, error, slot, claimed_at"

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
    """Same query() call for Postgres and SQLite; SQL is written with %s placeholders. A read whose connection the
    server dropped (2026-11-17: "server closed the connection unexpectedly" broke a dashboard page) is asked once more
    on a new connection (reopen); a change never is, since it may have been made before the answer was lost."""

    def __init__(self, conn, sqlite: bool, reopen=None):
        self.conn, self.sqlite, self.reopen = conn, sqlite, reopen

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.sqlite:
            sql = sql.replace("%s", "?")
        try:
            cur = self.conn.execute(sql, params)
        except Exception as e:
            if self.reopen is None or not _dropped(e) or not READS.match(sql):
                raise
            self.conn = self.reopen()
            cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()] if cur.description else []


READS = re.compile(r"\s*SELECT\b", re.I)


def _dropped(error: Exception) -> bool:
    """Did the cloud database's connection fail (dropped, refused, timed out) rather than the query itself?"""
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(error, psycopg.OperationalError)


def _open(url: str):
    """A new connection to the cloud database. prepare_threshold=None: Neon's pooled connections don't support prepared
    statements. connect_timeout: a database that doesn't answer fails in CONNECT_TIMEOUT seconds instead of holding a
    run (Neon wakes in ~1-5 s)."""
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                           connect_timeout=CONNECT_TIMEOUT)


@contextmanager
def connect():
    global _schema_ready
    url = env("DATABASE_URL") or env("POSTGRES_URL")
    holder = _held.get() if url else None  # (inside held(): the request's shared connection)
    if url:
        raw = holder.get("raw") if holder is not None else None
        if raw is None or raw.closed or raw.broken:
            if raw is not None:
                raw.close()
            raw = _open(url)
            if holder is not None:
                holder["raw"] = raw

        def reopen():   # (the connection dropped: a new one, the request's shared one from now on)
            try:
                conn.conn.close()
            except Exception:
                pass
            fresh = _open(url)
            if holder is not None:
                holder["raw"] = fresh
            return fresh
        conn, pk = _Conn(raw, sqlite=False, reopen=reopen), "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
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
            conn.conn.close()


def _video(row: dict | None) -> dict | None:
    if row:
        row["plan"] = json.loads(row["plan"])
    return row


def _slot_taken(error: Exception) -> bool:
    """The unique slot index refused a row: another run claimed that slot first."""
    return isinstance(error, sqlite3.IntegrityError) or type(error).__name__ == "UniqueViolation"


def _plan_part(sqlite: bool, path: str) -> str:
    """SQL for one part of a case's plan ("brief", "render.id"), as JSON text: the database sends only that part."""
    keys = path.split(".")
    if not all(re.fullmatch(r"[a-z_]+", key) for key in keys):  # (the code's own names, never outside text)
        raise ValueError(f"not a part of a plan: {path!r}")
    if sqlite:
        return "(plan -> '$." + ".".join(keys) + "')"
    return "((plan::jsonb #> '{" + ",".join(keys) + "}')::text)"


def _select(db, parts: tuple[str, ...] | None) -> str:
    """The columns a list reads: everything, or with `parts` a case's own columns and only those parts of its plan."""
    if parts is None:
        return "*"
    return ", ".join([LIGHT_COLUMNS] + [f"{_plan_part(db.sqlite, path)} AS part{k}" for k, path in enumerate(parts)])


def _read(db, rest: str, params: tuple, parts: tuple[str, ...] | None) -> list[dict]:
    """The cases of "SELECT ... FROM videos <rest>", whole or (with `parts`) in part. If the database refuses the SQL
    for the parts (a syntax or data error, SQLSTATE class 42 or 22), they're read whole, as before, rather than stop the
    run; a lost connection or a refusal of the database itself still raises."""
    if parts is not None:
        try:
            return [_case(r, parts) for r in db.query(f"SELECT {_select(db, parts)} FROM videos {rest}", params)]
        except Exception as e:
            if str(getattr(e, "sqlstate", "") or "")[:2] not in ("42", "22"):
                raise
            print(f"Reading cases in part was refused ({type(e).__name__}: {str(e)[:160]}); reading them whole")
    return [_video(r) for r in db.query(f"SELECT * FROM videos {rest}", params)]


def _case(row: dict, parts: tuple[str, ...] | None) -> dict:
    """A row as a case: its whole plan, or (with `parts`) only those parts of it, marked LIGHT."""
    if parts is None:
        return _video(row)
    plan = {LIGHT: True}
    for k, path in enumerate(parts):
        raw = row.pop(f"part{k}", None)
        if raw is None:  # (not in this plan)
            continue
        *above, last = path.split(".")
        node = plan
        for key in above:
            node = node.setdefault(key, {})
        node[last] = json.loads(raw)
    row["plan"] = plan
    return row


# --- videos ---------------------------------------------------------------

def insert_video(status: str, fmt: str, theme: str | None, trend: str | None, plan: dict,
                 slot: str | None = None) -> int | None:
    """New row; with a slot it also claims that slot, and returns None if another run has it."""
    if plan.get(LIGHT):
        raise ValueError("a case read in part (as a list reads it) can't be saved as a case")
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
        if (fields["plan"] or {}).get(LIGHT):
            raise ValueError("a case read in part (as a list reads it) can't be saved over the whole case: read it "
                             "whole with get_video first")
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


def slot_holders(start: str, end: str, parts: tuple[str, ...] | None = None) -> list[dict]:
    """Shorts being made or scheduled whose slot (or, for older rows without one, publish
    time) falls between start and end (`parts`: only those parts of their plans, LIGHT)."""
    with connect() as db:
        return _read(db, "WHERE status IN ('making', 'scheduled') AND "
                         "(slot BETWEEN %s AND %s OR (slot IS NULL AND publish_at BETWEEN %s AND %s)) ORDER BY id",
                     (start, end, start, end), parts)


def planned_videos(limit: int = 50, parts: tuple[str, ...] | None = None) -> list[dict]:
    """The queue: stories written and waiting for a slot, oldest first. Rows earlier versions made (other formats) are
    left to the dashboard. `parts`: as in slot_holders."""
    with connect() as db:
        return _read(db, "WHERE status = 'planned' AND format = %s ORDER BY id LIMIT %s", (fmt(), limit), parts)


def fmt() -> str:
    """The format of the rows the agents make: the stories'."""
    return FORMAT


def ready(video: dict) -> bool:
    """Can it go up: not held by the Reviewer (agents/reviewer.py: a film that still failed after the Animator's fixes
    is made again by itself first)."""
    return not (video["plan"].get("review") or {}).get("held")


def next_planned() -> dict | None:
    """The oldest story ready to go up."""
    return next((v for v in planned_videos() if ready(v)), None)


def get_video(video_id: int) -> dict | None:
    with connect() as db:
        rows = db.query("SELECT * FROM videos WHERE id = %s", (video_id,))
    return _video(rows[0] if rows else None)


def list_videos(limit: int = 30, parts: tuple[str, ...] | None = None) -> list[dict]:
    with connect() as db:
        return _read(db, "ORDER BY id DESC LIMIT %s", (limit,), parts)


def status_counts() -> dict[str, int]:
    with connect() as db:
        return {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")}


def get_run(run_id: int) -> dict | None:
    with connect() as db:
        rows = db.query("SELECT * FROM runs WHERE id = %s", (run_id,))
    return rows[0] if rows else None


def recent_runs(limit: int = 30) -> list[dict]:
    with connect() as db:
        return db.query("SELECT * FROM runs ORDER BY id DESC LIMIT %s", (limit,))


def upload_times(since: str) -> list[str]:
    """When each Short went up to YouTube since `since`, oldest first (the Publisher's finished uploads in the runs, those
    deleted later included: YouTube's daily upload limit counts them too)."""
    with connect() as db:
        rows = db.query("SELECT finished_at, detail FROM runs WHERE job = 'publisher' AND ok = 1 AND finished_at >= %s "
                        "AND detail LIKE %s ORDER BY finished_at", (since, '%"youtube_id"%'))
    return [r["finished_at"] for r in rows if (json.loads(r["detail"] or "{}") or {}).get("youtube_id")]


def count_videos(status: str | None = None) -> int:
    with connect() as db:
        if status:
            return db.query("SELECT COUNT(*) AS n FROM videos WHERE status = %s", (status,))[0]["n"]
        return db.query("SELECT COUNT(*) AS n FROM videos WHERE status <> 'skipped'")[0]["n"]


def recent_videos(days: int = 21, parts: tuple[str, ...] | None = None) -> list[dict]:
    with connect() as db:
        return _read(db, "WHERE created_at >= %s ORDER BY id DESC", (now_iso(-timedelta(days=days)),), parts)


def published_videos(days: int = 60, parts: tuple[str, ...] | None = None) -> list[dict]:
    """Stories whose publish time has passed (they're public unless you vetoed them)."""
    with connect() as db:
        return _read(db, "WHERE status = 'scheduled' AND youtube_id IS NOT NULL AND publish_at <= %s AND publish_at >= %s "
                         "ORDER BY publish_at", (now_iso(), now_iso(-timedelta(days=days))), parts)


def posted_history(limit: int = 200, parts: tuple[str, ...] | None = None) -> list[dict]:
    """Every story that went up to YouTube and whose time has come (public, unless it was taken off in YouTube Studio),
    and those you stopped or deleted: the Schedule page's "Posted", newest first (`limit` at most)."""
    with connect() as db:
        return _read(db, "WHERE youtube_id IS NOT NULL AND ((status = 'scheduled' AND publish_at <= %s) "
                         "OR status IN ('stopped', 'deleted')) ORDER BY id DESC LIMIT %s", (now_iso(), limit), parts)


def scheduled_videos(days: int = 3, parts: tuple[str, ...] | None = None) -> list[dict]:
    """Stories on YouTube whose publish time is still to come, or passed at most `days` ago."""
    with connect() as db:
        return _read(db, "WHERE status = 'scheduled' AND youtube_id IS NOT NULL AND publish_at >= %s ORDER BY publish_at",
                     (now_iso(-timedelta(days=days)),), parts)


# --- stats, notes, runs ---------------------------------------------------

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


def add_visual(recipe: dict, made_for: str = "") -> None:
    """A visual Agent 3 made (agents/visuals.py, its recipe: tools/visual_recipes.py) into the library."""
    with connect() as db:
        db.query("INSERT INTO visuals (name, kind, says, recipe, made_for, made_at) VALUES (%s, %s, %s, %s, %s, %s)",
                 (recipe["name"], recipe["kind"], recipe["says"], json.dumps(recipe), (made_for or "")[:160], now_iso()))


def visuals(removed: bool = False) -> list[dict]:
    """The visuals Agent 3 made, oldest first: each its recipe with "made_for", "made_at" and "removed_at" (a removed
    one only when `removed`; the latest of a name wins)."""
    with connect() as db:
        rows = db.query("SELECT name, kind, says, recipe, made_for, made_at, removed_at FROM visuals ORDER BY id")
    out = {}
    for r in rows:
        try:
            rec = json.loads(r["recipe"])
        except (TypeError, ValueError):
            continue
        out[(r["kind"], r["name"])] = {**rec, "made_for": r["made_for"] or "", "made_at": r["made_at"],
                                       "removed_at": r["removed_at"]}
    return [v for v in out.values() if removed or not v["removed_at"]]


def remove_visual(name: str) -> bool:
    """A made visual taken out of the library (the Studio's Remove): no later story uses it; the stories made with it
    keep their own copies."""
    with connect() as db:
        return bool(db.query("UPDATE visuals SET removed_at = %s WHERE name = %s AND removed_at IS NULL RETURNING id",
                             (now_iso(), name)))


def set_visual_preview(name: str, png: bytes) -> None:
    """A made visual's picture (PNG), kept with it: the dashboard shows it where nothing is drawn (online)."""
    data = base64.b64encode(png).decode("ascii")
    with connect() as db:
        if not db.query("UPDATE visual_previews SET png = %s WHERE name = %s RETURNING name", (data, name)):
            db.query("INSERT INTO visual_previews (name, png) VALUES (%s, %s)", (name, data))


def visual_preview(name: str) -> bytes | None:
    """The picture kept with a made visual (set_visual_preview), or None."""
    with connect() as db:
        rows = db.query("SELECT png FROM visual_previews WHERE name = %s", (name,))
    return base64.b64decode(rows[0]["png"]) if rows else None


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


# --- themes you ask for (the Themes page; Agent 1 takes them first) ---------

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
