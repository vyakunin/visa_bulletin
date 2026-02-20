#!/usr/bin/env python3
"""
Backfill source_file_date for existing SalaryRecord records.

This script populates the source_file_date field for existing records based on:
1. IngestVersion.run.started_at (if available)
2. DataSource.downloaded_at (if available)
3. SalaryRecord.created_at (fallback)

Usage:
    bazel run //scripts/salary:backfill_source_file_date
    bazel run //scripts/salary:backfill_source_file_date -- --dry-run
    bazel run //scripts/salary:backfill_source_file_date -- --limit 10000
"""

import argparse
import logging
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger
from models.ingest.data_source import DataSource
from models.salary import SalaryRecord

setup_logging(debug=False)
logger = logging.getLogger(__name__)

script_logger = ScriptLogger(__file__)


def _build_data_source_lookup() -> dict[str, object]:
    """Pre-load DataSource downloaded_at indexed by local_file_path fragment."""
    lookup: dict[str, object] = {}
    for ds in DataSource.objects.filter(downloaded_at__isnull=False).values(
        "local_file_path", "downloaded_at"
    ):
        path = ds["local_file_path"]
        if path:
            lookup[path] = ds["downloaded_at"]
    logger.info("Loaded %s DataSource entries with downloaded_at", f"{len(lookup):,}")
    return lookup


def backfill_source_file_date(dry_run: bool = False, limit: int | None = None):
    """Backfill source_file_date for existing SalaryRecord records."""
    queryset = SalaryRecord.objects.filter(
        source_file_date__isnull=True
    ).select_related("ingest_version__run")

    total_count = queryset.count()
    if limit:
        queryset = queryset[:limit]
        logger.info(
            "Processing %s of %s records without source_file_date",
            f"{limit:,}",
            f"{total_count:,}",
        )
    else:
        logger.info(
            "Processing %s records without source_file_date", f"{total_count:,}"
        )

    if total_count == 0:
        logger.info("No records to backfill")
        return

    if dry_run:
        logger.info("DRY RUN MODE - No records will be updated")

    ds_lookup = _build_data_source_lookup()

    collector = BatchedUpdateCollector(
        fields=["source_file_date"],
        batch_size=1000,
        dry_run=dry_run,
        use_transaction=True,
    )

    updated_count = 0
    skipped_count = 0

    for record in queryset.iterator(chunk_size=1000):
        source_file_date = None

        if record.ingest_version and record.ingest_version.run:
            source_file_date = record.ingest_version.run.started_at
        elif record.source_file:
            for ds_path, ds_date in ds_lookup.items():
                if record.source_file in ds_path or ds_path in record.source_file:
                    source_file_date = ds_date
                    break

        if not source_file_date:
            if record.created_at:
                source_file_date = record.created_at
            else:
                skipped_count += 1
                continue

        record.source_file_date = source_file_date
        collector.add(record)
        updated_count += 1

        if updated_count % 10000 == 0:
            logger.info("Processed %s records...", f"{updated_count:,}")

    collector.flush()

    logger.info("Backfill complete:")
    logger.info("  Updated: %s records", f"{updated_count:,}")
    logger.info(
        "  Skipped: %s records (no date source available)", f"{skipped_count:,}"
    )

    if dry_run:
        logger.info("DRY RUN - No records were actually updated")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill source_file_date for existing SalaryRecord records"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Dry run mode - do not update records"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to process (default: all)",
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={"dry_run": args.dry_run, "limit": args.limit},
        context="Backfilling source_file_date for SalaryRecord records",
    )

    try:
        backfill_source_file_date(dry_run=args.dry_run, limit=args.limit)
    except Exception as e:
        logger.error("Backfill failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
