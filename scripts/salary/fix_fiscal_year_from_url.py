#!/usr/bin/env python3
"""
Fix fiscal year for records from files with artificial filenames (e.g., lca_xxx.xlsx).

When files are downloaded with artificial names like "lca_367.xlsx", the fiscal year
cannot be extracted from the filename. This script:
1. Finds records from files with artificial names (lca_xxx, perm_xxx)
2. Looks up the DataSource URL to get the original filename
3. Extracts fiscal year from the original URL
4. Updates records with the correct fiscal year

Usage:
    bazel run //scripts/salary:fix_fiscal_year_from_url -- --dry-run
    bazel run //scripts/salary:fix_fiscal_year_from_url
"""

import argparse
import os
import re

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

import logging

from django.db.models import Count, Q

from django_config.logging_config import setup_logging
from lib.utils.data_source_utils import (
    get_fiscal_year_from_datasource,
)
from lib.utils.db_utils import BatchedUpdateCollector
from models.ingest.data_source import DataSource
from models.salary import SalaryRecord, WorksiteRecord

logger = logging.getLogger(__name__)


def is_artificial_filename(filename: str) -> bool:
    """Check if filename is artificial (e.g., lca_xxx.xlsx, perm_xxx.xlsx)"""
    # Pattern: prefix_number.ext (e.g., lca_367.xlsx, perm_123.xlsx)
    pattern = r"^(lca|perm|h1b|icert)_\d+\.(xlsx|csv|XLSX|CSV)$"
    return bool(re.match(pattern, filename, re.IGNORECASE))


def get_fiscal_year_from_datasource_url(source_file: str) -> int | None:
    """
    Get fiscal year from DataSource URL for a given source_file.

    This is a wrapper that finds the DataSource and then uses the shared
    get_fiscal_year_from_datasource function.

    Args:
        source_file: Source filename (e.g., 'lca_367.xlsx')

    Returns:
        Fiscal year if found, None otherwise
    """
    # Find DataSource by local_file_path or URL containing the filename
    # Try to find by local_file_path first (more reliable)
    data_source = DataSource.objects.filter(
        Q(local_file_path__endswith=source_file) | Q(url__contains=source_file)
    ).first()

    if not data_source:
        logger.debug(f"  No DataSource found for {source_file}")
        return None

    logger.debug(
        f"  Found DataSource {data_source.id}: URL={data_source.url}, local_file_path={data_source.local_file_path}"
    )

    # Use shared function that handles all sophisticated strategies
    return get_fiscal_year_from_datasource(
        source_file, data_source, logger_instance=logger
    )


def fix_fiscal_years_for_artificial_files(dry_run: bool = True) -> dict:
    """
    Fix fiscal years for records from files with artificial filenames.

    Args:
        dry_run: If True, only report what would be changed

    Returns:
        Dict with statistics about fixes
    """
    stats = {
        "salary_files_found": 0,
        "worksite_files_found": 0,
        "salary_records_fixed": 0,
        "worksite_records_fixed": 0,
        "salary_files_no_datasource": [],
        "worksite_files_no_datasource": [],
        "salary_files_no_fiscal_year": [],
        "worksite_files_no_fiscal_year": [],
    }

    # Find all unique source files that are artificial
    # Use Q objects with regex pattern for artificial filenames
    artificial_pattern = r"^(lca|perm|h1b|icert)_\d+\.(xlsx|csv|XLSX|CSV)$"

    salary_files = (
        SalaryRecord.objects.values("source_file")
        .annotate(count=Count("id"))
        .filter(source_file__regex=artificial_pattern)
    )

    worksite_files = (
        WorksiteRecord.objects.values("source_file")
        .annotate(count=Count("id"))
        .filter(source_file__regex=artificial_pattern)
    )

    logger.info(f"Found {len(salary_files)} artificial SalaryRecord files")
    logger.info(f"Found {len(worksite_files)} artificial WorksiteRecord files")

    # Process SalaryRecord files
    for file_info in salary_files:
        source_file = file_info["source_file"]
        record_count = file_info["count"]
        stats["salary_files_found"] += 1

        logger.info(
            f"\nProcessing SalaryRecord file: {source_file} ({record_count:,} records)"
        )

        # Get fiscal year from DataSource URL
        fiscal_year = get_fiscal_year_from_datasource_url(source_file)

        if fiscal_year is None:
            logger.warning(f"  ⚠️  Could not determine fiscal year for {source_file}")
            stats["salary_files_no_fiscal_year"].append(source_file)
            continue

        # Check current fiscal year distribution
        current_years = (
            SalaryRecord.objects.filter(source_file=source_file)
            .values("fiscal_year")
            .annotate(count=Count("id"))
        )

        logger.info("  Current fiscal year distribution:")
        for year_info in current_years:
            logger.info(
                f"    FY {year_info['fiscal_year']}: {year_info['count']:,} records"
            )

        # Find records that need fixing (wrong fiscal year or null)
        # CRITICAL: Must use Q objects because .exclude() doesn't capture NULL values
        # In SQL, NULL != value evaluates to NULL (not TRUE), so exclude() misses NULL records
        records_to_fix = SalaryRecord.objects.filter(source_file=source_file).filter(
            Q(fiscal_year__isnull=True) | ~Q(fiscal_year=fiscal_year)
        )

        fix_count = records_to_fix.count()

        if fix_count == 0:
            logger.info(
                f"  ✓ All records already have correct fiscal year ({fiscal_year})"
            )
            continue

        logger.info(
            f"  Found {fix_count:,} records to fix (should be FY {fiscal_year})"
        )

        if dry_run:
            logger.info(
                f"  [DRY RUN] Would update {fix_count:,} records to fiscal_year={fiscal_year}"
            )
        else:
            # Use BatchedUpdateCollector for efficient updates
            collector = BatchedUpdateCollector(
                fields=["fiscal_year"],
                batch_size=1000,
                dry_run=False,
                use_transaction=True,
            )

            for record in records_to_fix.iterator(chunk_size=1000):
                record.fiscal_year = fiscal_year
                collector.add(record)

            collector.flush()
            stats["salary_records_fixed"] += collector.count
            logger.info(
                f"  ✓ Updated {collector.count:,} records to fiscal_year={fiscal_year}"
            )

    # Process WorksiteRecord files
    for file_info in worksite_files:
        source_file = file_info["source_file"]
        record_count = file_info["count"]
        stats["worksite_files_found"] += 1

        logger.info(
            f"\nProcessing WorksiteRecord file: {source_file} ({record_count:,} records)"
        )

        # Get fiscal year from DataSource URL
        fiscal_year = get_fiscal_year_from_datasource_url(source_file)

        if fiscal_year is None:
            logger.warning(f"  ⚠️  Could not determine fiscal year for {source_file}")
            stats["worksite_files_no_fiscal_year"].append(source_file)
            continue

        # Check current fiscal year distribution
        current_years = (
            WorksiteRecord.objects.filter(source_file=source_file)
            .values("fiscal_year")
            .annotate(count=Count("id"))
        )

        logger.info("  Current fiscal year distribution:")
        for year_info in current_years:
            logger.info(
                f"    FY {year_info['fiscal_year']}: {year_info['count']:,} records"
            )

        # Find records that need fixing (wrong fiscal year or null)
        # CRITICAL: Must use Q objects because .exclude() doesn't capture NULL values
        # In SQL, NULL != value evaluates to NULL (not TRUE), so exclude() misses NULL records
        records_to_fix = WorksiteRecord.objects.filter(source_file=source_file).filter(
            Q(fiscal_year__isnull=True) | ~Q(fiscal_year=fiscal_year)
        )

        fix_count = records_to_fix.count()

        if fix_count == 0:
            logger.info(
                f"  ✓ All records already have correct fiscal year ({fiscal_year})"
            )
            continue

        logger.info(
            f"  Found {fix_count:,} records to fix (should be FY {fiscal_year})"
        )

        if dry_run:
            logger.info(
                f"  [DRY RUN] Would update {fix_count:,} records to fiscal_year={fiscal_year}"
            )
        else:
            # Use BatchedUpdateCollector for efficient updates
            collector = BatchedUpdateCollector(
                fields=["fiscal_year"],
                batch_size=1000,
                dry_run=False,
                use_transaction=True,
            )

            for record in records_to_fix.iterator(chunk_size=1000):
                record.fiscal_year = fiscal_year
                collector.add(record)

            collector.flush()
            stats["worksite_records_fixed"] += collector.count
            logger.info(
                f"  ✓ Updated {collector.count:,} records to fiscal_year={fiscal_year}"
            )

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Fix fiscal year for records from files with artificial filenames"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be changed, do not update records",
    )

    args = parser.parse_args()

    setup_logging()

    logger.info("=" * 80)
    logger.info("FIX FISCAL YEAR FROM URL")
    logger.info("=" * 80)
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE UPDATE'}")
    logger.info("")

    stats = fix_fiscal_years_for_artificial_files(dry_run=args.dry_run)

    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"SalaryRecord files processed: {stats['salary_files_found']}")
    logger.info(f"WorksiteRecord files processed: {stats['worksite_files_found']}")
    logger.info(f"SalaryRecord records fixed: {stats['salary_records_fixed']:,}")
    logger.info(f"WorksiteRecord records fixed: {stats['worksite_records_fixed']:,}")

    if stats["salary_files_no_fiscal_year"]:
        logger.warning(
            "\nSalaryRecord files where fiscal year could not be determined:"
        )
        for filename in stats["salary_files_no_fiscal_year"]:
            logger.warning(f"  - {filename}")

    if stats["worksite_files_no_fiscal_year"]:
        logger.warning(
            "\nWorksiteRecord files where fiscal year could not be determined:"
        )
        for filename in stats["worksite_files_no_fiscal_year"]:
            logger.warning(f"  - {filename}")

    if args.dry_run:
        logger.info(
            "\n[DRY RUN] No records were actually updated. Run without --dry-run to apply changes."
        )


if __name__ == "__main__":
    main()
