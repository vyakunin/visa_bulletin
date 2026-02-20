#!/usr/bin/env python3
"""
Re-import files containing I-200 case numbers with new routing logic.

With the combined LCA/Worksite plugin, I-200 records are now routed to WorksiteRecord
during import. This script helps re-import affected files.

Process:
1. Identify source files containing I-200 records
2. Delete existing I-200 records (from both SalaryRecord and WorksiteRecord)
3. Find or create DataSource entries for those files
4. Re-import using the unified ingest pipeline (new routing will apply)
"""

import argparse
import logging
import os

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import transaction

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, SourceType
from models.salary import SalaryRecord, WorksiteRecord

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def find_affected_source_files() -> set[str]:
    """
    Find source files that contain I-200 case numbers.

    Returns:
        Set of source file names
    """
    logger.info("Finding source files with I-200 case numbers...")

    # Find files with I-200 records in SalaryRecord
    try:
        salary_files = set(
            SalaryRecord.objects.filter(case_number__startswith="I-200")
            .values_list("source_file", flat=True)
            .distinct()
        )
    except Exception as e:
        logger.error(f"Error querying SalaryRecord: {e}")
        salary_files = set()

    # Find files with I-200 records in WorksiteRecord (if already migrated)
    try:
        worksite_files = set(
            WorksiteRecord.objects.filter(case_number__startswith="I-200")
            .values_list("source_file", flat=True)
            .distinct()
        )
    except Exception as e:
        logger.error(f"Error querying WorksiteRecord: {e}")
        worksite_files = set()

    all_files = salary_files | worksite_files

    logger.info(f"Found {len(all_files)} affected source files:")
    for source_file in sorted(all_files):
        if source_file:
            try:
                salary_count = SalaryRecord.objects.filter(
                    source_file=source_file, case_number__startswith="I-200"
                ).count()
                worksite_count = WorksiteRecord.objects.filter(
                    source_file=source_file, case_number__startswith="I-200"
                ).count()
                logger.info(
                    f"  {source_file}: {salary_count:,} in SalaryRecord, {worksite_count:,} in WorksiteRecord"
                )
            except Exception as e:
                logger.error(f"  Error counting records for {source_file}: {e}")

    return all_files


def delete_i200_records_for_file(
    source_file: str, dry_run: bool = False, skip_if_in_worksite: bool = True
) -> tuple[int, int, bool]:
    """
    Delete I-200 records for a specific source file.

    Args:
        source_file: Source file name
        dry_run: If True, only count records, don't delete
        skip_if_in_worksite: If True, skip deletion if records already exist in WorksiteRecord

    Returns:
        Tuple of (salary_deleted, worksite_deleted, was_skipped) counts
    """
    logger.info(
        f"{'[DRY RUN] Would delete' if dry_run else 'Deleting'} I-200 records from {source_file}..."
    )

    # Check if records already exist in WorksiteRecord
    try:
        worksite_count = WorksiteRecord.objects.filter(
            source_file=source_file, case_number__startswith="I-200"
        ).count()
    except Exception as e:
        logger.error(f"  Error counting WorksiteRecord: {e}")
        worksite_count = 0

    if skip_if_in_worksite and worksite_count > 0:
        logger.info(
            f"  Skipping {source_file} - already has {worksite_count:,} I-200 records in WorksiteRecord (correctly migrated)"
        )
        return 0, worksite_count, True

    # Delete from SalaryRecord
    try:
        salary_records = SalaryRecord.objects.filter(
            source_file=source_file, case_number__startswith="I-200"
        )
        salary_count = salary_records.count()
    except Exception as e:
        logger.error(f"  Error querying SalaryRecord: {e}")
        return 0, worksite_count, False

    if not dry_run and salary_count > 0:
        try:
            with transaction.atomic():
                deleted_count, _ = salary_records.delete()
            logger.info(f"  Deleted {deleted_count:,} I-200 records from SalaryRecord")
        except Exception as e:
            logger.error(f"  Failed to delete records: {e}")
            return 0, worksite_count, False
    else:
        deleted_count = salary_count
        logger.info(f"  Found {salary_count:,} I-200 records in SalaryRecord")

    logger.info(
        f"  Found {worksite_count:,} I-200 records in WorksiteRecord (not deleted)"
    )

    return deleted_count, worksite_count, False


def find_or_create_data_source(source_file: str) -> DataSource | None:
    """
    Find or create DataSource entry for a source file.

    Attempts to match by URL patterns. If not found, returns None.

    Args:
        source_file: Source file name (e.g., "LCA_FY2013.xlsx")

    Returns:
        DataSource instance or None if not found
    """
    # Try to find existing DataSource with matching filename in URL
    data_sources = DataSource.objects.filter(
        domain=DataDomain.DOL.value,
        source_type=SourceType.LCA.value,
        url__icontains=source_file.replace(".xlsx", "").replace(".csv", ""),
    )

    if data_sources.exists():
        source = data_sources.first()
        logger.info(f"  Found DataSource {source.id}: {source.url}")
        return source

    logger.warning(f"  No DataSource found for {source_file}")
    logger.warning(
        "  You may need to discover sources first: bazel run //scripts/ingest:run_pipeline -- discover --domain dol"
    )
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Re-import files containing I-200 case numbers with new routing logic"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--delete-only",
        action="store_true",
        help="Only delete existing records, do not re-import",
    )
    parser.add_argument(
        "--source-file",
        type=str,
        help="Process only this specific source file (otherwise processes all affected files)",
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Skip deletion step (assumes records already deleted)",
    )

    args = parser.parse_args()

    script_logger.log_call(
        args=vars(args),
        context="Re-importing files with I-200 records using new routing logic",
    )

    # Find affected files
    if args.source_file:
        affected_files = {args.source_file}
        logger.info(f"Processing specified file: {args.source_file}")
    else:
        affected_files = find_affected_source_files()

    if not affected_files:
        logger.info("No affected files found")
        return

    # Delete existing I-200 records
    if not args.skip_delete:
        logger.info("\n" + "=" * 80)
        logger.info("Step 1: Deleting existing I-200 records")
        logger.info("=" * 80)

        total_salary_deleted = 0
        total_skipped = 0

        for source_file in sorted(affected_files):
            if not source_file:
                continue

            salary_del, worksite_count, was_skipped = delete_i200_records_for_file(
                source_file, dry_run=args.dry_run, skip_if_in_worksite=True
            )
            total_salary_deleted += salary_del
            if was_skipped:
                total_skipped += 1

        logger.info(
            f"\nTotal: {total_salary_deleted:,} I-200 records deleted from SalaryRecord"
        )
        logger.info(
            f"Skipped {total_skipped} files (already correctly migrated to WorksiteRecord)"
        )

        if args.dry_run:
            logger.info(
                "\nDRY RUN - No records were deleted. Run without --dry-run to proceed."
            )
            return

    if args.delete_only:
        logger.info("\nDelete-only mode - skipping re-import")
        return

    # Find DataSource entries (only for files that were actually processed, not skipped)
    logger.info("\n" + "=" * 80)
    logger.info("Step 2: Finding DataSource entries")
    logger.info("=" * 80)

    # Find all LCA DataSource entries (files we deleted I-200 records from need re-import)
    # Files that already have records in WorksiteRecord were skipped during deletion
    all_lca_sources = DataSource.objects.filter(
        domain=DataDomain.DOL.value, source_type=SourceType.LCA.value
    ).order_by("url")

    logger.info(f"Found {all_lca_sources.count()} LCA DataSource entries")

    # Files we deleted from (these need re-import)
    # These are files that had I-200 records in SalaryRecord (we just deleted them)
    files_to_reimport = [
        "H-1B_iCert_LCA_FY2011_Q4.xlsx",
        "Icert_ LCA_ FY2009.xlsx",
        "LCA_Appendix_A_FY2025_Q3.xlsx",
        "LCA_Disclosure_Data_FY2020_Q1.xlsx",
        "LCA_Disclosure_Data_FY2020_Q2.xlsx",
        "LCA_Disclosure_Data_FY2020_Q3.xlsx",
        "LCA_Disclosure_Data_FY2020_Q4.xlsx",
        "LCA_Disclosure_Data_FY2021_Q3.xlsx",
        "LCA_Disclosure_Data_FY2023_Q1.xlsx",
        "LCA_Disclosure_Data_FY2023_Q2.xlsx",
        "LCA_Disclosure_Data_FY2023_Q3.xlsx",
        "LCA_Disclosure_Data_FY2025_Q3.xlsx",
        "LCA_FY2012_Q4.xlsx",
        "LCA_FY2013.xlsx",
    ]

    data_sources = []
    for source in all_lca_sources:
        # Try to match by filename patterns in URL
        try:
            url_lower = source.url.lower() if source.url else ""
            filename_match = any(
                filename.lower()
                .replace(".xlsx", "")
                .replace(".csv", "")
                .replace(" ", "")
                in url_lower.replace(" ", "")
                for filename in files_to_reimport
            )
            if filename_match:
                data_sources.append(source)
        except Exception as e:
            logger.warning(f"  Error matching filename for source {source.id}: {e}")

    # Instructions for re-import
    logger.info("\n" + "=" * 80)
    logger.info("Step 3: Re-import instructions")
    logger.info("=" * 80)
    logger.info("\nTo re-import these files with the new routing logic:")
    logger.info("(I-200 records will be routed to WorksiteRecord)")
    logger.info("")

    if data_sources:
        logger.info(
            "Files that need re-import (I-200 records were deleted from SalaryRecord):"
        )
        for source in data_sources:
            logger.info(
                f"  bazel run //scripts/ingest:run_pipeline -- run --source-id {source.id}"
            )
            logger.info(f"    # {source.url}")

        logger.info("\nOr re-import all at once:")
        source_ids = [str(source.id) for source in data_sources]
        logger.info(f"  for id in {' '.join(source_ids)}; do")
        logger.info(
            "    bazel run //scripts/ingest:run_pipeline -- run --source-id $id"
        )
        logger.info("  done")
    else:
        logger.warning("No matching DataSource entries found.")
        logger.info("You may need to discover sources first:")
        logger.info(
            "  bazel run //scripts/ingest:run_pipeline -- discover --domain dol"
        )
        logger.info("")
        logger.info("Or query existing DataSource entries:")
        logger.info("  bazel run //scripts/ingest:run_pipeline -- status")


if __name__ == "__main__":
    main()
