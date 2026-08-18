#!/usr/bin/env python3
"""Report — and optionally repair — indexes the models declare but the database lacks.

Migrations do not re-check state that changed out of band, and the bulk-load
drop/restore in scripts/salary/manage_salary_indexes.py replays a snapshot of what
existed, so an index lost once is lost for good. This reads the model layer as the
source of truth and compares it against pg_indexes.

Usage
  bazel run //scripts/db:audit_indexes                          # audit every table, exit 1 on divergence
  bazel run //scripts/db:audit_indexes -- --table salary_record
  bazel run //scripts/db:audit_indexes -- --sql                 # print the repair DDL, touch nothing
  bazel run //scripts/db:audit_indexes -- --create-missing      # build the missing ones, CONCURRENTLY
  bazel run //scripts/db:audit_indexes -- --json                # machine-readable, for daily_checkup

Exit codes: 0 nothing missing, 1 declared indexes are absent, 2 the run itself failed.
--create-missing exits 0 once the repair leaves nothing missing.
"""

import argparse
import json
import logging
import os
import sys

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import connection  # noqa: E402

from django_config.logging_config import setup_logging  # noqa: E402
from lib.utils.index_audit import audit, coverage_for  # noqa: E402
from lib.utils.logging_utils import ScriptLogger  # noqa: E402

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

EXIT_OK = 0
EXIT_DIVERGED = 1
EXIT_ERROR = 2


def _report(audits, show_undeclared: bool) -> int:
    missing_total = 0
    for entry in audits:
        missing = entry.missing
        if not missing and not (show_undeclared and entry.undeclared):
            continue
        logger.info(
            "%s: %d declared, %d present, %d MISSING",
            entry.table,
            len(entry.declared),
            len(entry.actual),
            len(missing),
        )
        for index in missing:
            covering = coverage_for(index, entry.actual)
            suffix = f"  [leading keys also in: {', '.join(covering)}]" if covering else ""
            logger.info("  MISSING %s%s", index.name, suffix)
            logger.info("          %s", index.sql)
        missing_total += len(missing)
        if show_undeclared and entry.undeclared:
            logger.info("  undeclared (in DB, no model declares it):")
            for name in entry.undeclared:
                logger.info("    %s", name)
    if missing_total:
        logger.error("%d declared index(es) are absent from the database", missing_total)
        return EXIT_DIVERGED
    logger.info("Every model-declared index is present (%d tables audited)", len(audits))
    return EXIT_OK


def _create_missing(audits) -> int:
    statements = [i for entry in audits for i in entry.missing]
    if not statements:
        logger.info("Nothing missing; created nothing.")
        return EXIT_OK
    # CONCURRENTLY cannot run inside a transaction block.
    previous = connection.get_autocommit()
    connection.set_autocommit(True)
    try:
        for index in statements:
            logger.info("Creating %s on %s", index.name, index.table)
            with connection.cursor() as cursor:
                cursor.execute(index.concurrent_sql())
    finally:
        connection.set_autocommit(previous)
    logger.info("Created %d index(es).", len(statements))
    return EXIT_OK


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", help="Audit only this table (default: all)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--create-missing",
        action="store_true",
        help="Build every missing index with CREATE INDEX CONCURRENTLY IF NOT EXISTS",
    )
    mode.add_argument(
        "--sql", action="store_true", help="Print the repair DDL and exit without running it"
    )
    mode.add_argument("--json", action="store_true", help="Emit the audit as JSON")
    parser.add_argument(
        "--show-undeclared",
        action="store_true",
        help="Also list indexes the database holds that no model declares",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={
            "table": args.table,
            "create_missing": args.create_missing,
            "sql": args.sql,
            "json": args.json,
        },
        context="Reconcile model-declared indexes against the database",
    )

    audits = audit(args.table)
    if args.table and not audits:
        logger.error("No managed model uses table %r", args.table)
        return EXIT_ERROR

    if args.json:
        payload = [
            {
                "table": e.table,
                "declared": len(e.declared),
                "present": len(e.actual),
                "missing": [
                    {
                        "name": i.name,
                        "sql": i.sql,
                        "covering": coverage_for(i, e.actual),
                    }
                    for i in e.missing
                ],
                **({"undeclared": e.undeclared} if args.show_undeclared else {}),
            }
            for e in audits
        ]
        print(json.dumps(payload, indent=2))
        return EXIT_DIVERGED if any(p["missing"] for p in payload) else EXIT_OK

    if args.sql:
        printed = False
        for entry in audits:
            for index in entry.missing:
                print(index.concurrent_sql() + ";")
                printed = True
        return EXIT_DIVERGED if printed else EXIT_OK

    if args.create_missing:
        rc = _create_missing(audits)
        if rc != EXIT_OK:
            return rc
        return _report(audit(args.table), args.show_undeclared)

    return _report(audits, args.show_undeclared)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logger.exception("Index audit failed")
        sys.exit(EXIT_ERROR)
