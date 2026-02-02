#!/usr/bin/env python3
"""
Manage non-unique indexes for salary_record and worksite_record.

Usage:
  bazel run //scripts/salary:manage_salary_indexes -- --list
  bazel run //scripts/salary:manage_salary_indexes -- --drop --snapshot data/index_snapshots/salary_indexes.yaml
  bazel run //scripts/salary:manage_salary_indexes -- --recreate --snapshot data/index_snapshots/salary_indexes.yaml
  bazel run //scripts/salary:manage_salary_indexes -- --create-clustering-indexes

Modes:
  --list: Show current indexes
  --drop: Drop non-unique indexes (saves snapshot)
  --recreate: Recreate indexes from snapshot (requires snapshot file)
  --create-clustering-indexes: Create minimal indexes for clustering (emergency mode when snapshot missing)

Index Strategy:
  - During ingest: Drop indexes for speed (--drop)
  - Before clustering: Create clustering indexes (--create-clustering-indexes or --recreate)
  - After clustering: Recreate all indexes (--recreate)
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Setup Django early (before any model imports)
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django.db import connection
from django_config.logging_config import setup_logging
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger
from models.ingest.enums import IngestStatus
from models.ingest.ingest_run import IngestRun
import yaml

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

TARGET_TABLES = ('salary_record', 'worksite_record')


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _indexdef_with_if_not_exists(indexdef: str) -> str:
    if indexdef.startswith('CREATE UNIQUE INDEX '):
        return indexdef.replace('CREATE UNIQUE INDEX ', 'CREATE UNIQUE INDEX IF NOT EXISTS ', 1)
    if indexdef.startswith('CREATE INDEX '):
        return indexdef.replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ', 1)
    return indexdef


def _ensure_no_running_ingests() -> None:
    running = IngestRun.objects.filter(status=IngestStatus.RUNNING).exists()
    if running:
        logger.error("Refusing to modify indexes while ingest runs are active.")
        sys.exit(1)


def _fetch_index_metadata() -> list[dict]:
    query = """
        SELECT
            i.schemaname,
            i.tablename,
            i.indexname,
            i.indexdef,
            ix.indisunique,
            ix.indisprimary
        FROM pg_indexes i
        JOIN pg_class t ON t.relname = i.tablename
        JOIN pg_namespace n ON n.nspname = i.schemaname AND t.relnamespace = n.oid
        JOIN pg_class c ON c.relname = i.indexname AND c.relnamespace = n.oid
        JOIN pg_index ix ON ix.indexrelid = c.oid
        WHERE i.schemaname = 'public'
          AND i.tablename IN %s
        ORDER BY i.tablename, i.indexname;
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [TARGET_TABLES])
        rows = cursor.fetchall()
    return [
        {
            'schema': row[0],
            'table': row[1],
            'name': row[2],
            'indexdef': row[3],
            'is_unique': bool(row[4]),
            'is_primary': bool(row[5]),
        }
        for row in rows
    ]


def _log_index_summary(indexes: list[dict]) -> None:
    if not indexes:
        logger.info("No indexes found for target tables.")
        return

    logger.info("Index inventory:")
    for index in indexes:
        flags = []
        if index['is_primary']:
            flags.append('PRIMARY')
        if index['is_unique']:
            flags.append('UNIQUE')
        flag_str = f" ({', '.join(flags)})" if flags else ""
        logger.info("  %s.%s%s", index['table'], index['name'], flag_str)


def list_indexes() -> None:
    indexes = _fetch_index_metadata()
    _log_index_summary(indexes)


def _snapshot_path(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg)
    return get_workspace_dir() / 'data' / 'index_snapshots' / 'salary_indexes.yaml'


def _write_snapshot(path: Path, indexes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        'generated_at': datetime.utcnow().isoformat(),
        'tables': list(TARGET_TABLES),
        'indexes': indexes,
    }
    path.write_text(yaml.safe_dump(snapshot, sort_keys=False))
    logger.info("Wrote index snapshot to %s", path)


def _read_snapshot(path: Path) -> list[dict]:
    if not path.exists():
        logger.error("Snapshot file not found: %s", path)
        sys.exit(1)
    snapshot = yaml.safe_load(path.read_text()) or {}
    indexes = snapshot.get('indexes', [])
    if not indexes:
        logger.error("Snapshot file has no indexes to recreate: %s", path)
        sys.exit(1)
    return indexes


def drop_indexes(snapshot_path: Path, overwrite: bool) -> None:
    _ensure_no_running_ingests()
    indexes = _fetch_index_metadata()
    droppable = [
        index for index in indexes
        if not index['is_unique'] and not index['is_primary']
    ]

    if not droppable:
        logger.info("No non-unique indexes to drop.")
        return

    if snapshot_path.exists() and not overwrite:
        logger.error(
            "Snapshot already exists at %s. Use --overwrite to replace it.",
            snapshot_path,
        )
        sys.exit(1)

    _write_snapshot(snapshot_path, droppable)

    with connection.cursor() as cursor:
        for index in droppable:
            schema = _quote_ident(index['schema'])
            name = _quote_ident(index['name'])
            logger.info("Dropping index: %s.%s", index['schema'], index['name'])
            cursor.execute(f"DROP INDEX IF EXISTS {schema}.{name};")

    logger.info("Dropped %d non-unique indexes.", len(droppable))


def recreate_indexes(snapshot_path: Path) -> None:
    _ensure_no_running_ingests()
    indexes = _read_snapshot(snapshot_path)

    with connection.cursor() as cursor:
        for index in indexes:
            indexdef = _indexdef_with_if_not_exists(index['indexdef'])
            logger.info("Recreating index: %s.%s", index['table'], index['name'])
            cursor.execute(indexdef)

    logger.info("Recreated %d indexes.", len(indexes))


def create_clustering_indexes() -> None:
    """Create minimal indexes required for clustering and employer profile performance."""
    _ensure_no_running_ingests()
    
    clustering_indexes = [
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_job_title_idx ON salary_record(job_title)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_employer_name_idx ON salary_record(employer_name)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_visa_program_idx ON salary_record(visa_program)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_employer_job_title_idx ON salary_record(employer_name, job_title)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_job_title_state_idx ON salary_record(job_title, worksite_state)",
        # Covering index for employer profile percentiles/histogram (index-only scan, no heap fetches)
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS sr_emp_wk_fy_inc_wage ON salary_record(employer_id, is_worksite, fiscal_year) INCLUDE (wage_annual)",
    ]
    
    logger.info("Creating %d clustering indexes...", len(clustering_indexes))
    
    with connection.cursor() as cursor:
        for indexdef in clustering_indexes:
            # Extract index name from SQL
            index_name = indexdef.split('EXISTS ')[1].split(' ON ')[0]
            logger.info("Creating index: %s", index_name)
            cursor.execute(indexdef)
    
    logger.info("Created clustering indexes successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Manage non-unique indexes on salary_record/worksite_record',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument('--list', action='store_true', help='List indexes for target tables')
    action_group.add_argument('--drop', action='store_true', help='Drop non-unique indexes')
    action_group.add_argument('--recreate', action='store_true', help='Recreate dropped indexes from snapshot')
    action_group.add_argument('--create-clustering-indexes', action='store_true', 
                              help='Create minimal indexes required for clustering (job_title, employer_name)')
    parser.add_argument(
        '--snapshot',
        help='Path to snapshot YAML (default: data/index_snapshots/salary_indexes.yaml)',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing snapshot when dropping indexes',
    )

    args = parser.parse_args()
    snapshot_path = _snapshot_path(args.snapshot)

    script_logger.log_call(
        args={'list': args.list, 'drop': args.drop, 'recreate': args.recreate, 
              'create_clustering_indexes': args.create_clustering_indexes,
              'snapshot': str(snapshot_path), 'overwrite': args.overwrite},
        context='Manage salary/worksite indexes for bulk ingest',
    )

    if args.list:
        list_indexes()
        return
    if args.drop:
        drop_indexes(snapshot_path, args.overwrite)
        return
    if args.recreate:
        recreate_indexes(snapshot_path)
        return
    if args.create_clustering_indexes:
        create_clustering_indexes()
        return


if __name__ == '__main__':
    main()
