#!/usr/bin/env python3
"""
Run SQL queries for debugging and maintenance (SELECT and mutations).

Usage:
    # SELECT
    bazel run //scripts:run_sql -- --query "SELECT COUNT(*) FROM salary_record"

    # UPDATE (prompts unless --yes)
    bazel run //scripts:run_sql -- --query "UPDATE salary_record SET job_title_entity_id = NULL"

    # Dry-run for mutations
    bazel run //scripts:run_sql -- --query "DELETE FROM salary_job_title" --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os


def is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container."""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r") as handle:
            return "docker" in handle.read()
    except (FileNotFoundError, PermissionError):
        return False


_OVERRIDE_DB_HOST = False
if not is_running_in_docker():
    current_host = os.environ.get("DB_HOST", "")
    if current_host == "host.docker.internal":
        os.environ["DB_HOST"] = "localhost"
        _OVERRIDE_DB_HOST = True


if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import connection  # noqa: E402
from django_config.logging_config import setup_logging  # noqa: E402
from lib.utils.logging_utils import ScriptLogger  # noqa: E402
from models.bulletin import Bulletin  # noqa: F401,E402
from models.salary import SalaryRecord  # noqa: F401,E402

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)

if _OVERRIDE_DB_HOST:
    logger.info("Overriding DB_HOST to localhost (not running in Docker)")


def _is_mutation(query: str) -> bool:
    query_upper = query.strip().upper()
    return query_upper.startswith(("UPDATE", "DELETE", "INSERT", "TRUNCATE"))


def run_query(query: str, *, dry_run: bool, auto_confirm: bool) -> None:
    """Execute a SQL query and log results."""
    is_mutation = _is_mutation(query)
    if is_mutation:
        if dry_run:
            logger.info("[DRY RUN] Would execute: %s", query[:200])
            return
        if not auto_confirm:
            logger.warning("This query will modify data.")
            logger.info("Query: %s", query[:500])
            confirm = input("Type 'yes' to confirm: ").strip().lower()
            if confirm != "yes":
                logger.info("Aborted.")
                return

    with connection.cursor() as cursor:
        cursor.execute(query)
        if is_mutation:
            logger.info("Rows affected: %s", cursor.rowcount)
            return

        columns = [col[0] for col in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        if columns:
            header = " | ".join(columns)
            logger.info(header)
            logger.info("-" * len(header))
            for row in rows:
                logger.info(" | ".join(str(val) for val in row))
        else:
            for row in rows:
                logger.info(row[0] if len(row) == 1 else row)
        logger.info("(%s row(s))", len(rows))


def show_table(table_name: str, limit: int = 10) -> None:
    """Show table structure and sample data."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
            """,
            [table_name],
        )
        columns = cursor.fetchall()
        logger.info("Table: %s", table_name)
        logger.info("Columns:")
        for column_name, data_type in columns:
            logger.info("  %s (%s)", column_name, data_type)

        cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
        rows = cursor.fetchall()
        if rows:
            col_names = [col[0] for col in columns]
            logger.info(" | ".join(col_names))
            logger.info("-" * 80)
            for row in rows:
                logger.info(" | ".join(str(val)[:30] for val in row))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SQL queries (SELECT or mutation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Count records:
    bazel run //:run_sql -- --query "SELECT COUNT(*) FROM salary_record"

  Update records (with confirmation):
    bazel run //:run_sql -- --query "UPDATE salary_record SET job_title_entity_id = NULL"

  Dry-run a mutation:
    bazel run //:run_sql -- --query "DELETE FROM salary_job_title" --dry-run
        """,
    )
    parser.add_argument("--query", "-q", help="SQL query to execute")
    parser.add_argument("--table", "-t", help="Table name to explore")
    parser.add_argument("--limit", type=int, default=10, help="Limit for table exploration")
    parser.add_argument("--dry-run", action="store_true", help="Log mutation without executing")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation for mutations")
    args = parser.parse_args()

    script_logger.log_call(
        args={
            "query": args.query,
            "table": args.table,
            "limit": args.limit,
            "dry_run": args.dry_run,
            "yes": args.yes,
        },
        context="Run SQL query",
    )

    if args.query:
        run_query(args.query, dry_run=args.dry_run, auto_confirm=args.yes)
    elif args.table:
        show_table(args.table, args.limit)
    else:
        parser.error("Either --query or --table must be specified")


if __name__ == "__main__":
    main()
