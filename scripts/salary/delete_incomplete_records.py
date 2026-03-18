#!/usr/bin/env python3
"""
Delete incomplete records (missing salary data) from database.

This script deletes:
- SalaryRecord records with missing wage_annual (null/0) and no wage_from/wage_unit
- WorksiteRecord records with missing wage_annual (salary is REQUIRED for worksite)

Usage:
    bazel run //scripts/salary:delete_incomplete_records -- --fix
"""

import argparse
import logging
import os
import sys

# Setup Django early
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import transaction
from django.db.models import Q

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.salary import SalaryRecord, WorksiteRecord

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def delete_incomplete_records(dry_run: bool = True) -> dict:
    """
    Delete incomplete records (missing salary data).

    Args:
        dry_run: If True, don't actually delete records

    Returns:
        Dict with deletion results
    """
    logger.info("=" * 80)
    logger.info("DELETING INCOMPLETE RECORDS")
    logger.info("=" * 80)

    # Delete SalaryRecord records without salary data
    unfixable_salary = SalaryRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0), is_worksite=False
    ).filter(
        Q(wage_from__isnull=True)
        | Q(wage_from=0)
        | Q(wage_unit__isnull=True)
        | Q(wage_unit="")
    )
    salary_drop_count = unfixable_salary.count()

    # Delete WorksiteRecord records without salary data (salary is REQUIRED)
    unfixable_worksite = WorksiteRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0)
    )
    worksite_drop_count = unfixable_worksite.count()

    logger.info(
        f"Found {salary_drop_count:,} SalaryRecord and {worksite_drop_count:,} WorksiteRecord records to delete"
    )

    if dry_run:
        logger.info(
            f"[DRY RUN] Would delete {salary_drop_count:,} SalaryRecord and {worksite_drop_count:,} WorksiteRecord records"
        )
        return {"salary_deleted": 0, "worksite_deleted": 0, "dry_run": True}
    else:
        with transaction.atomic():
            salary_deleted, _ = unfixable_salary.delete()
            worksite_deleted, _ = unfixable_worksite.delete()
            logger.info(
                f"Deleted {salary_deleted:,} SalaryRecord and {worksite_deleted:,} WorksiteRecord records"
            )
            return {
                "salary_deleted": salary_deleted,
                "worksite_deleted": worksite_deleted,
                "dry_run": False,
            }


def main():
    parser = argparse.ArgumentParser(
        description="Delete incomplete records (missing salary data) from database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Dry-run (preview what would be deleted):
    bazel run //scripts/salary:delete_incomplete_records

  Actually delete records:
    bazel run //scripts/salary:delete_incomplete_records -- --fix
        """,
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        help="Actually delete records (default is dry-run)",
    )

    args = parser.parse_args()

    script_logger.log_call(
        args=vars(args), context="Deleting incomplete records (missing salary data)"
    )

    results = delete_incomplete_records(dry_run=not args.fix)

    if results["dry_run"]:
        logger.info(
            "\n[DRY RUN] No records were deleted. Use --fix to actually delete."
        )
    else:
        logger.info(
            f"\n✅ Deletion completed: {results['salary_deleted']:,} SalaryRecord, {results['worksite_deleted']:,} WorksiteRecord"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
