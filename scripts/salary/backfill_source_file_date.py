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
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import log_context
from models.salary import SalaryRecord

log_context("Backfilling source_file_date for existing SalaryRecord records")


def backfill_source_file_date(dry_run: bool = False, limit: int | None = None):
    """
    Backfill source_file_date for existing SalaryRecord records.
    
    Args:
        dry_run: If True, don't actually update records
        limit: Maximum number of records to process (None = all)
    """
    # Query records without source_file_date
    queryset = SalaryRecord.objects.filter(source_file_date__isnull=True)

    total_count = queryset.count()
    if limit:
        queryset = queryset[:limit]
        print(f"Processing {limit:,} of {total_count:,} records without source_file_date")
    else:
        print(f"Processing {total_count:,} records without source_file_date")

    if dry_run:
        print("DRY RUN MODE - No records will be updated")

    # Use BatchedUpdateCollector for efficient updates
    collector = BatchedUpdateCollector(
        fields=['source_file_date'],
        batch_size=1000,
        dry_run=dry_run,
        use_transaction=True
    )

    updated_count = 0
    skipped_count = 0

    for record in queryset.iterator(chunk_size=1000):
        # Try to get source_file_date from ingest_version.run.started_at
        source_file_date = None
        if record.ingest_version and record.ingest_version.run:
            source_file_date = record.ingest_version.run.started_at
        elif record.source_file:
            # Try to get from DataSource
            from models.ingest.data_source import DataSource
            try:
                # Try to find DataSource by URL pattern or local_file_path
                # This is a best-effort approach
                data_source = DataSource.objects.filter(
                    local_file_path__icontains=record.source_file
                ).first()
                if data_source and data_source.downloaded_at:
                    source_file_date = data_source.downloaded_at
            except Exception:
                pass

        # Fallback to created_at if nothing else available
        if not source_file_date:
            source_file_date = record.created_at

        # Update record
        record.source_file_date = source_file_date
        collector.add(record)
        updated_count += 1

        if updated_count % 10000 == 0:
            print(f"Processed {updated_count:,} records...")

    # Flush remaining records
    collector.flush()

    print("\nBackfill complete:")
    print(f"  Updated: {updated_count:,} records")
    print(f"  Skipped: {skipped_count:,} records")

    if dry_run:
        print("\nDRY RUN - No records were actually updated")


def main():
    parser = argparse.ArgumentParser(
        description='Backfill source_file_date for existing SalaryRecord records'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - do not update records'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of records to process (default: all)'
    )

    args = parser.parse_args()

    backfill_source_file_date(dry_run=args.dry_run, limit=args.limit)


if __name__ == '__main__':
    main()

