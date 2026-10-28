"""
Copies the channel's database from this computer (.tmp/ezzy.db) to the cloud one (DATABASE_URL:
Neon's Postgres), once, when the morning run moves to GitHub Actions. Every row keeps its id, so
cases keep their numbers, and each table's row count is checked afterwards. It refuses to copy
into a cloud database that already has cases, so it can't run twice by mistake.

Afterwards keep DATABASE_URL in .env: the dashboard on this computer then shows the cloud's
cases and its own autopilot stays off (only the cloud posts).

Usage:
    python tools/db_copy.py          # needs DATABASE_URL in .env
"""

import argparse
import sqlite3
import sys

import db
from common import env, tmp_path

TABLES = ("videos", "used_clips", "runs", "stats", "notes", "characters", "topics", "comments")
WITH_ID = {"videos", "runs", "notes", "characters", "topics"}  # their ids are kept (Postgres would number them anew)


def copy(progress=print) -> dict:
    if not (env("DATABASE_URL") or env("POSTGRES_URL")):
        raise RuntimeError("DATABASE_URL isn't set: paste Neon's connection string into .env first")
    local = sqlite3.connect(tmp_path("ezzy.db"))
    local.row_factory = sqlite3.Row
    copied = {}
    with db.connect() as cloud:  # (makes the tables in the cloud database the first time)
        if cloud.query("SELECT COUNT(*) AS n FROM videos")[0]["n"]:
            raise RuntimeError("the cloud database has cases already: nothing was copied")
        for table in TABLES:
            rows = local.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                columns = list(rows[0].keys())
                overriding = " OVERRIDING SYSTEM VALUE" if table in WITH_ID else ""
                sql = (f"INSERT INTO {table} ({', '.join(columns)}){overriding} "
                       f"VALUES ({', '.join(['%s'] * len(columns))})")
                for row in rows:
                    cloud.query(sql, tuple(row))
                if table in WITH_ID:  # the next new row continues after the copied ones
                    cloud.query(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")
            there = cloud.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
            if there != len(rows):
                raise RuntimeError(f"{table}: {len(rows)} rows here but {there} in the cloud")
            copied[table] = there
            progress(f"{table}: {there} rows")
    return copied


def main() -> int:
    argparse.ArgumentParser(description=__doc__.strip().splitlines()[0]).parse_args()
    try:
        copied = copy()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Copied {sum(copied.values())} rows in {len(copied)} tables; the counts match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
