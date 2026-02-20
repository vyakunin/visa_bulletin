#!/usr/bin/env python3
"""
Fix salary records with invalid wages - both too high and too low.

This script identifies and fixes records with wage_annual outside valid range
(configured in wage_thresholds_config.yaml). Uses same logic as ingest to ensure
consistent validation and correction.

Invalid wages can be caused by:
- **Incorrect wage units**: Hourly/monthly/weekly wages stored as annual (or vice versa)
- **Data entry errors**: Unrealistic values (e.g., $21.3M for Marketing Manager, or $500 annual)
- **Parsing errors**: Decimal point errors, extra zeros, missing conversion

This script categorizes invalid wages and applies appropriate fixes:
- **Parsing errors** (wrong unit): Recalculates wage_annual using corrected unit
- **Data errors** (unrealistic even with correct unit): Marks as invalid (NULL)
- **Edge cases** (possibly legitimate): Flags for manual review

All logic shared with ingest via `lib.parsing.salary.wage_unit_correction` module.

Only needed for cleaning legacy data or one-off fixes. Ingest already rejects out-of-range
wages at import; no need to run this after a normal ingest.

Does not drop or recreate indexes; only filtered SELECT and batched UPDATEs. Safe on production.

After running: Re-compute stats that depend on wage_annual (see scripts/README.md):
  update_employer_stats, update_job_title_cluster_stats, then clear_cache.

Usage:
    # Fix all invalid wages (both high and low)
    bazel run //scripts/salary:fix_invalid_wages

    # Dry-run to see what would be fixed
    bazel run //scripts/salary:fix_invalid_wages -- --dry-run

    # Fix only parsing errors (wrong units)
    bazel run //scripts/salary:fix_invalid_wages -- --category parsing

    # Fix only data errors (mark as invalid)
    bazel run //scripts/salary:fix_invalid_wages -- --category data

    # Limit to first 100 records (for testing)
    bazel run //scripts/salary:fix_invalid_wages -- --limit 100
"""

import argparse
import logging
import os
from decimal import Decimal

# Setup Django
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()


from django_config.logging_config import setup_logging
from lib.parsing.salary.wage_unit_correction import (
    MAX_ANNUAL,
    MIN_ANNUAL,
    calculate_annual_wage,
    should_correct_wage_unit,
)
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger
from models.enums.visa_program import WageUnit
from models.salary import SalaryRecord

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)

MIN_ANNUAL_DECIMAL = Decimal(str(MIN_ANNUAL))
MAX_ANNUAL_DECIMAL = Decimal(str(MAX_ANNUAL))


def categorize_invalid_wage_records(records):
    """
    Categorize invalid wage records (both high and low) into fixable categories.

    Uses shared `should_correct_wage_unit()` logic from wage_unit_correction module
    to ensure consistent categorization with ingest.

    Returns:
        dict with categories: 'parsing_errors', 'data_errors', 'edge_cases', 'unknown'
        - parsing_errors: Wrong wage unit, can be automatically corrected
        - data_errors: Unrealistic values even with correct unit, mark as invalid
        - edge_cases: Possibly legitimate (very high executive salaries), need review
        - unknown: Can't determine category
    """
    categories = {
        "parsing_errors": [],  # Can be automatically fixed (wrong unit)
        "data_errors": [],  # Mark as invalid (unrealistic even with correct unit)
        "edge_cases": [],  # Possibly legitimate, need review
        "unknown": [],  # Can't determine category
    }

    for record in records:
        wage_annual_float = float(record.wage_annual) if record.wage_annual else None

        # Check if this is a parsing error (wrong unit)
        # Use shared logic from wage_unit_correction module
        if record.wage_from and record.wage_unit != WageUnit.YEAR:
            if should_correct_wage_unit(record.wage_from, record.wage_unit):
                categories["parsing_errors"].append(record)
                continue

        # If wage is extremely high or low and unit is YEAR, check if it's a data error
        if record.wage_unit == WageUnit.YEAR and wage_annual_float:
            if wage_annual_float > MAX_ANNUAL or wage_annual_float < MIN_ANNUAL:
                # Check if it's possibly legitimate (edge case)
                if _is_possibly_legitimate(record):
                    categories["edge_cases"].append(record)
                else:
                    categories["data_errors"].append(record)
                continue

        # If we get here, couldn't categorize
        categories["unknown"].append(record)

    return categories


def _is_possibly_legitimate(record):
    """Check if record might be legitimate (very high-paying executive role)."""
    # Very few roles legitimately pay >$1M
    # These would typically be C-level executives at major companies
    high_paying_keywords = ["ceo", "chief executive", "president", "chief", "executive"]
    job_lower = (record.job_title or "").lower()

    # Check if job title suggests executive role
    if any(keyword in job_lower for keyword in high_paying_keywords):
        # Still suspicious if >$5M
        if record.wage_annual and float(record.wage_annual) > 50000000:
            return False
        return True

    return False


def fix_parsing_error_record(record, dry_run=False):
    """
    Fix a record where wage_unit is wrong (parsing error).

    Strategy: If wage_from is reasonable for the unit, treat it as correct and recalculate annual.
    Otherwise, mark as invalid.
    """
    if not record.wage_from:
        return False, "No wage_from value"

    wage_from_float = float(record.wage_from)

    # Check if wage_from is reasonable for the unit
    if record.wage_unit == WageUnit.HOUR:
        if wage_from_float > 500:  # Unrealistic hourly rate
            return False, f"Unrealistic hourly rate ${wage_from_float:,.2f}/hour"
        # Recalculate annual wage correctly
        new_annual = calculate_annual_wage(record.wage_from, record.wage_unit)

    elif record.wage_unit == WageUnit.MONTH:
        if wage_from_float > 50000:  # Unrealistic monthly rate
            return False, f"Unrealistic monthly rate ${wage_from_float:,.2f}/month"
        new_annual = calculate_annual_wage(record.wage_from, record.wage_unit)

    elif record.wage_unit == WageUnit.WEEK:
        if wage_from_float > 20000:  # Unrealistic weekly rate
            return False, f"Unrealistic weekly rate ${wage_from_float:,.2f}/week"
        new_annual = calculate_annual_wage(record.wage_from, record.wage_unit)

    elif record.wage_unit == WageUnit.BI_WEEKLY:
        if wage_from_float > 20000:  # Unrealistic bi-weekly rate
            return (
                False,
                f"Unrealistic bi-weekly rate ${wage_from_float:,.2f}/bi-weekly",
            )
        new_annual = calculate_annual_wage(record.wage_from, record.wage_unit)

    else:
        return False, f"Unexpected unit: {record.wage_unit}"

    if not dry_run:
        record.wage_annual = new_annual
        # Note: save() will be done in bulk_update_batched() - return record for batching

    return True, f"Recalculated annual wage to ${float(new_annual):,.2f}"


def fix_data_error_record(record, dry_run=False):
    """
    Fix a record with data entry error (YEAR unit but unrealistic value).

    Strategy: Mark as invalid (set wage_annual to NULL or 0) since we can't determine correct value.
    """
    if not dry_run:
        # Set to NULL to exclude from queries
        record.wage_annual = None
        record.wage_from = None
        # Note: save() will be done in bulk_update_batched() - return record for batching

    return True, "Marked as invalid (unrealistic value)"


def analyze_and_fix(dry_run=False, category=None, limit=None):
    """Analyze invalid wage records (both high and low) and fix them."""
    logger.info("=" * 80)
    logger.info(
        f"FIXING INVALID WAGE RECORDS (outside ${MIN_ANNUAL:,}-${MAX_ANNUAL:,} range)"
    )
    logger.info("=" * 80)
    if dry_run:
        logger.info("DRY-RUN MODE - No changes will be made")
    logger.info("")

    # Find all invalid wage records (both high AND low)
    from django.db.models import Q

    invalid_wage_records = SalaryRecord.objects.filter(
        Q(wage_annual__gt=MAX_ANNUAL_DECIMAL) | Q(wage_annual__lt=MIN_ANNUAL_DECIMAL)
    ).order_by("-wage_annual")

    if limit:
        invalid_wage_records = invalid_wage_records[:limit]

    total_count = invalid_wage_records.count()
    high_count = SalaryRecord.objects.filter(wage_annual__gt=MAX_ANNUAL_DECIMAL).count()
    low_count = SalaryRecord.objects.filter(
        wage_annual__lt=MIN_ANNUAL_DECIMAL, wage_annual__gt=0
    ).count()

    logger.info(f"Found {total_count} records with invalid wages:")
    logger.info(f"  Too high (>${MAX_ANNUAL:,}): {high_count:,}")
    logger.info(f"  Too low (<${MIN_ANNUAL:,}): {low_count:,}")
    logger.info("")

    # Categorize records
    logger.info("Categorizing records...")
    categories = categorize_invalid_wage_records(invalid_wage_records)

    logger.info(f"  Parsing errors (can auto-fix): {len(categories['parsing_errors'])}")
    logger.info(f"  Data errors (mark as invalid): {len(categories['data_errors'])}")
    logger.info(f"  Edge cases (need review): {len(categories['edge_cases'])}")
    logger.info(f"  Unknown: {len(categories['unknown'])}")
    logger.info("")

    # Filter by category if specified
    if category:
        if category == "parsing":
            records_to_fix = categories["parsing_errors"]
        elif category == "data":
            records_to_fix = categories["data_errors"]
        elif category == "edge":
            records_to_fix = categories["edge_cases"]
        else:
            logger.error(f"Unknown category: {category}")
            return
        logger.info(
            f"Filtering to category '{category}': {len(records_to_fix)} records"
        )
    else:
        # Fix parsing errors and data errors, skip edge cases
        records_to_fix = categories["parsing_errors"] + categories["data_errors"]
        logger.info(
            f"Fixing parsing errors and data errors: {len(records_to_fix)} records"
        )

    logger.info("")

    # Determine fields to update based on what might be changed
    fields_to_update = ["wage_annual"]
    if any(r in categories["data_errors"] for r in records_to_fix):
        fields_to_update.append("wage_from")

    # Use BatchedUpdateCollector to handle batching, transactions, and counting
    collector = BatchedUpdateCollector(
        fields=fields_to_update, batch_size=1000, dry_run=dry_run, use_transaction=True
    )

    # Fix records
    failed_count = 0
    skipped_count = 0

    logger.info("Fixing records...")
    logger.info("-" * 80)

    for i, record in enumerate(records_to_fix, 1):
        logger.info(f"\n[{i}/{len(records_to_fix)}] Case: {record.case_number}")
        logger.info(f"  Employer: {record.employer_name[:60]}")
        logger.info(f"  Job: {record.job_title[:60]}")
        logger.info(
            f"  Current: wage_from=${record.wage_from:,.2f}, unit={record.wage_unit}, annual=${record.wage_annual:,.2f}"
        )

        # Determine fix strategy based on category
        if record in categories["parsing_errors"]:
            success, message = fix_parsing_error_record(record, dry_run)
            if success:
                collector.add(record)
        elif record in categories["data_errors"]:
            success, message = fix_data_error_record(record, dry_run)
            if success:
                collector.add(record)
        else:
            success, message = False, "Skipped (edge case or unknown)"
            skipped_count += 1

        if success:
            logger.info(f"  ✅ Fixed: {message}")
        else:
            logger.warning(f"  ❌ Failed: {message}")
            failed_count += 1

    # Flush remaining records
    collector.flush()
    fixed_count = collector.count

    if fixed_count > 0 and not dry_run:
        logger.info(f"\nBulk updated {fixed_count} records...")

    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total records processed: {len(records_to_fix)}")
    logger.info(f"  Fixed: {fixed_count}")
    logger.info(f"  Failed: {failed_count}")
    logger.info(f"  Skipped: {skipped_count}")
    if dry_run:
        logger.info(
            "\nDRY-RUN: No changes were made. Run without --dry-run to apply fixes."
        )
    else:
        logger.info(f"\n✅ Fixed {fixed_count} records")


def main():
    parser = argparse.ArgumentParser(
        description="Fix records with invalid wages (both too high and too low)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Fix all invalid wages (both high and low):
    bazel run //scripts/salary:fix_invalid_wages
  
  Dry-run to see what would be fixed:
    bazel run //scripts/salary:fix_invalid_wages -- --dry-run
  
  Fix only parsing errors (wrong units):
    bazel run //scripts/salary:fix_invalid_wages -- --category parsing
  
  Fix only data errors (mark as invalid):
    bazel run //scripts/salary:fix_invalid_wages -- --category data
  
  Limit to first 100 records (for testing):
    bazel run //scripts/salary:fix_invalid_wages -- --limit 100
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes",
    )

    parser.add_argument(
        "--category",
        choices=["parsing", "data", "edge"],
        help="Only fix records in this category",
    )

    parser.add_argument("--limit", type=int, help="Limit number of records to process")

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "dry_run": args.dry_run,
            "category": args.category,
            "limit": args.limit,
        },
        context="Fixing high-wage records (>$1M)",
    )

    analyze_and_fix(dry_run=args.dry_run, category=args.category, limit=args.limit)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    main()
