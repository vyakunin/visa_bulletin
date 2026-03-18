#!/usr/bin/env python3
"""
Fix missing employer links (records with employer_name but no employer FK).

This script:
1. Identifies records with employer_name but employer FK is null
2. Attempts to find or create matching Employer records
3. Links records to employers using bulk_update

Usage:
    bazel run //scripts/salary:fix_missing_employers
    bazel run //scripts/salary:fix_missing_employers -- --fix
    bazel run //scripts/salary:fix_missing_employers -- --limit 1000
"""

import argparse
import logging
import os
import sys
from collections import defaultdict

# Setup Django early
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()


from django_config.logging_config import setup_logging
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, SalaryRecord

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def find_missing_employer_links(limit: int | None = None) -> list[SalaryRecord]:
    """Find records with employer_name but no employer FK"""
    queryset = SalaryRecord.objects.filter(
        employer__isnull=True, employer_name__isnull=False
    ).exclude(employer_name="")

    if limit:
        queryset = queryset[:limit]

    return list(queryset)


def get_or_create_employer(
    employer_name: str, city: str | None, state: str | None
) -> Employer:
    """Get or create Employer record"""
    normalized_name = Employer.normalize_name(employer_name)

    # Try to find existing employer
    employer = Employer.objects.filter(
        name_normalized=normalized_name, city=city or "", state=state or ""
    ).first()

    if employer:
        return employer

    # Create new employer
    employer = Employer.objects.create(
        name=employer_name,
        name_normalized=normalized_name,
        city=city or "",
        state=state or "",
    )

    return employer


def fix_missing_employers(dry_run: bool = True, limit: int | None = None) -> dict:
    """Fix missing employer links"""
    logger.info("Finding records with missing employer links...")

    records_without_employer = find_missing_employer_links(limit)
    total_count = len(records_without_employer)

    logger.info(f"Found {total_count:,} records with missing employer links")

    if total_count == 0:
        return {"fixed": 0, "created": 0, "errors": 0}

    # Group by employer_name, city, state for batch processing
    grouped = defaultdict(list)
    for record in records_without_employer:
        key = (record.employer_name, record.worksite_city, record.worksite_state)
        grouped[key].append(record)

    logger.info(f"Grouped into {len(grouped)} unique employer/location combinations")

    created_count = 0
    error_count = 0

    # Use BatchedUpdateCollector to handle batching, transactions, and counting
    collector = BatchedUpdateCollector(
        fields=["employer"], batch_size=1000, dry_run=dry_run, use_transaction=True
    )

    # Process each group
    for (employer_name, city, state), records in grouped.items():
        try:
            # Get or create employer
            # Check if employer was just created by checking if it exists before creation
            employer_exists = Employer.objects.filter(
                name_normalized=Employer.normalize_name(employer_name),
                city=city or "",
                state=state or "",
            ).exists()

            employer = get_or_create_employer(employer_name, city, state)

            if not employer_exists:
                created_count += 1

            # Link all records in this group to the employer
            for record in records:
                record.employer = employer
                flushed = collector.add(record)

                # Log progress when batch is flushed
                if flushed > 0:
                    logger.info(f"  Fixed {collector.count:,} records...")

        except Exception as e:
            logger.error(f"Error processing employer {employer_name}: {e}")
            error_count += len(records)

    # Flush remaining records
    collector.flush()
    fixed_count = collector.count

    mode_str = "[DRY RUN] " if dry_run else ""
    logger.info(
        f"{mode_str}Fixed {fixed_count:,} records, created {created_count} employers"
    )

    return {
        "fixed": fixed_count,
        "created": created_count,
        "errors": error_count,
        "total": total_count,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fix missing employer links in salary records",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Dry-run (analyze only):
    bazel run //scripts/salary:fix_missing_employers

  Actually fix records:
    bazel run //scripts/salary:fix_missing_employers -- --fix

  Limit for testing:
    bazel run //scripts/salary:fix_missing_employers -- --limit 1000
        """,
    )

    parser.add_argument(
        "--fix", action="store_true", help="Actually fix records (default is dry-run)"
    )

    parser.add_argument(
        "--limit", type=int, help="Limit number of records to process (for testing)"
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "fix": args.fix,
            "limit": args.limit,
        },
        context="Fixing missing employer links in salary records",
    )

    mode_str = "[DRY RUN] " if not args.fix else ""
    logger.info("=" * 80)
    logger.info(f"{mode_str}FIX MISSING EMPLOYER LINKS")
    logger.info("=" * 80)
    logger.info("")

    results = fix_missing_employers(dry_run=not args.fix, limit=args.limit)

    print(f"\n{'=' * 80}")
    print(f"{mode_str}RESULTS")
    print(f"{'=' * 80}")
    print(f"Fixed: {results['fixed']:,}")
    print(f"Created employers: {results['created']}")
    print(f"Errors: {results['errors']}")
    print(f"Total found: {results['total']:,}")

    if not args.fix:
        print("\nTo actually fix records, run with --fix flag")

    sys.exit(0)


if __name__ == "__main__":
    main()
