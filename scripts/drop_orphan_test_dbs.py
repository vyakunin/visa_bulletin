#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg2-binary"]
# ///
"""Drop orphaned ``test_postgres_<pid>`` databases on the shared postgres server.

Backstop for the leak fixed in ``tests/django_setup.py``: the non-pytest-django
test regime creates a per-pid ``test_<base>_<pid>`` DB and now drops it via an
``atexit`` hook on clean exit. A bazel target killed by a timeout/OOM never runs
that hook, so it orphans its DB. By 2026-07-07 that had accumulated **2065 DBs
(21 GB)** on the minipc. This sweep reclaims them safely.

Safety — a DB is dropped ONLY when BOTH hold, so a live run is never touched:
  1. no active connection to it (``pg_stat_activity``), AND
  2. the ``<pid>`` embedded in its name is no longer a running process
     (``/proc/<pid>`` absent) — i.e. the creator is genuinely dead.

Auth: connects to ``postgres`` over the unix socket via peer auth as the current
OS user (the same ``vyakunin`` role the tests create the DBs as, so it owns them
and can drop them). Override with ``--host/--port/--user/--password`` for TCP.

Usage:
    uv run scripts/drop_orphan_test_dbs.py            # sweep
    uv run scripts/drop_orphan_test_dbs.py --dry-run  # show what would drop
Cron (minipc): hourly via the user crontab — see scripts/README.md.
"""
import argparse
import os
import re
import sys

import psycopg2

_PID_RE = re.compile(r"_(\d+)$")


def _pid_alive(name: str) -> bool:
    """True if the ``_<pid>`` suffix of *name* is a live process (so: keep it)."""
    m = _PID_RE.search(name)
    if not m:
        return True  # no pid suffix -> can't prove it's an orphan; keep it
    return os.path.exists(f"/proc/{m.group(1)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host")
    ap.add_argument("--port", default="5432")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--dbname", default="postgres")
    ap.add_argument("--pattern", default="test_postgres_%")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    kw = {"dbname": a.dbname, "connect_timeout": 5}
    for k in ("host", "port", "user", "password"):
        if getattr(a, k):
            kw[k] = getattr(a, k)

    conn = psycopg2.connect(**kw)
    conn.autocommit = True
    cur = conn.cursor()
    # candidates: matching name pattern with no active connection
    cur.execute(
        "SELECT d.datname FROM pg_database d "
        "WHERE d.datname LIKE %s "
        "AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname)",
        (a.pattern,),
    )
    candidates = [r[0] for r in cur.fetchall()]
    orphans = [n for n in candidates if not _pid_alive(n)]
    skipped = len(candidates) - len(orphans)

    if not orphans:
        print(f"no orphan test DBs to drop ({skipped} live/kept)")
        return 0

    if a.dry_run:
        print(f"DRY-RUN: would drop {len(orphans)} orphan test DBs ({skipped} kept)")
        for n in orphans[:20]:
            print(f"  {n}")
        return 0

    dropped = 0
    for n in orphans:
        try:
            cur.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')
            dropped += 1
        except Exception as e:  # a DB that just got a connection / was already gone
            print(f"  skip {n}: {e}", file=sys.stderr)
    print(f"dropped {dropped}/{len(orphans)} orphan test DBs ({skipped} live/kept)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
