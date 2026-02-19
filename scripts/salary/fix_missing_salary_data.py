#!/usr/bin/env python3
"""
Fix records with missing salary data (wage_annual is null/0).

This script identifies records where wage_annual is missing but wage_from and wage_unit
are available, and recalculates wage_annual using the shared calculate_annual_wage function.

Usage:
    bazel run //scripts/salary:fix_missing_salary_data
    bazel run //scripts/salary:fix_missing_salary_data -- --fix
    bazel run //scripts/salary:fix_missing_salary_data -- --limit 1000
"""

import argparse
import logging
import os
import sys
from decimal import Decimal

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django

django.setup()

from django.db.models import Count, Q

from django_config.logging_config import setup_logging
from lib.parsing.salary.wage_unit_correction import calculate_annual_wage
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger
from lib.utils.validation_utils import get_missing_salary_data_queryset

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def analyze_missing_salary_data(limit: int | None = None) -> dict:
    """
    Analyze records with missing salary data.
    
    Returns:
        Dict with analysis results
    """
    logger.info("Analyzing records with missing salary data...")

    # Use shared queryset utility
    missing_wage_annual = get_missing_salary_data_queryset()

    total_missing = missing_wage_annual.count()
    logger.info(f"Found {total_missing:,} records with missing wage_annual")

    # Categorize records
    # 1. Records with wage_from and wage_unit (can be recalculated)
    can_recalculate = missing_wage_annual.filter(
        wage_from__isnull=False,
        wage_unit__isnull=False
    ).exclude(wage_from=0).exclude(wage_unit='')

    can_recalculate_count = can_recalculate.count()

    # 2. Records with no wage_from or wage_unit (cannot be recalculated)
    cannot_recalculate = missing_wage_annual.filter(
        Q(wage_from__isnull=True) | Q(wage_from=0) | Q(wage_unit__isnull=True) | Q(wage_unit='')
    )
    cannot_recalculate_count = cannot_recalculate.count()

    # Get sample by employer
    sample_by_employer = list(
        missing_wage_annual.values('employer_name')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    # Get sample records that can be recalculated
    sample_recalculable = list(
        can_recalculate.values('case_number', 'employer_name', 'wage_from', 'wage_unit', 'wage_annual')[:10]
    )

    # Get sample records that cannot be recalculated
    sample_non_recalculable = list(
        cannot_recalculate.values('case_number', 'employer_name', 'wage_from', 'wage_unit', 'wage_annual')[:10]
    )

    analysis = {
        'total_missing': total_missing,
        'can_recalculate': can_recalculate_count,
        'cannot_recalculate': cannot_recalculate_count,
        'sample_by_employer': sample_by_employer,
        'sample_recalculable': sample_recalculable,
        'sample_non_recalculable': sample_non_recalculable,
    }

    logger.info(f"  Can be recalculated: {can_recalculate_count:,}")
    logger.info(f"  Cannot be recalculated: {cannot_recalculate_count:,}")

    if sample_by_employer:
        logger.info("  Top employers affected:")
        for emp in sample_by_employer[:5]:
            logger.info(f"    {emp['employer_name']}: {emp['count']:,} records")

    return analysis


def fix_missing_salary_data(limit: int | None = None, dry_run: bool = True) -> dict:
    """
    Fix records with missing salary data by recalculating wage_annual.
    
    Args:
        limit: Maximum number of records to process (None = all)
        dry_run: If True, don't actually update records
    
    Returns:
        Dict with fix results
    """
    logger.info("Fixing records with missing salary data...")

    # Use shared queryset utility
    missing_wage_annual = get_missing_salary_data_queryset()

    # Find records that can be recalculated
    records_to_fix = missing_wage_annual.filter(
        wage_from__isnull=False,
        wage_unit__isnull=False
    ).exclude(wage_from=0).exclude(wage_unit='')

    if limit:
        records_to_fix = records_to_fix[:limit]

    total_to_fix = records_to_fix.count()
    logger.info(f"Found {total_to_fix:,} records that can be recalculated")

    if total_to_fix == 0:
        logger.info("No records to fix")
        return {'fixed': 0, 'errors': 0, 'skipped': 0}

    error_count = 0
    skipped_count = 0

    # Use BatchedUpdateCollector to handle batching, transactions, and counting
    collector = BatchedUpdateCollector(
        fields=['wage_annual'],
        batch_size=1000,
        dry_run=dry_run,
        use_transaction=True
    )

    def process_batch(batch):
        """Process a batch of records"""
        nonlocal error_count, skipped_count

        for record in batch:
            try:
                if not record.wage_from or not record.wage_unit:
                    skipped_count += 1
                    continue

                # Recalculate wage_annual
                new_wage_annual = calculate_annual_wage(record.wage_from, record.wage_unit)

                if new_wage_annual is None:
                    skipped_count += 1
                    continue

                record.wage_annual = new_wage_annual
                collector.add(record)

            except Exception as e:
                logger.warning(f"Error processing record {record.id}: {e}")
                error_count += 1

    # Process in batches using iterator to avoid loading all into memory
    batch_size = 1000
    batch = []
    batch_num = 0

    for record in records_to_fix.iterator(chunk_size=batch_size):
        batch.append(record)

        if len(batch) >= batch_size:
            batch_num += 1
            logger.info(f"Processing batch {batch_num} ({len(batch)} records)...")
            process_batch(batch)
            batch = []

    # Process remaining records
    if batch:
        batch_num += 1
        logger.info(f"Processing final batch {batch_num} ({len(batch)} records)...")
        process_batch(batch)

    # Flush any remaining records
    collector.flush()
    fixed_count = collector.count

    mode_str = "[DRY RUN] " if dry_run else ""
    logger.info(f"{mode_str}Fixed {fixed_count:,} records")
    if error_count > 0:
        logger.warning(f"Errors: {error_count}")
    if skipped_count > 0:
        logger.info(f"Skipped: {skipped_count}")

    return {
        'fixed': fixed_count,
        'errors': error_count,
        'skipped': skipped_count,
        'total': total_to_fix
    }


def main():
    parser = argparse.ArgumentParser(
        description='Fix records with missing salary data (wage_annual is null/0)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Analyze missing salary data:
    bazel run //scripts/salary:fix_missing_salary_data
  
  Preview fixes (dry-run):
    bazel run //scripts/salary:fix_missing_salary_data -- --limit 1000
  
  Actually fix records:
    bazel run //scripts/salary:fix_missing_salary_data -- --fix
        """
    )

    parser.add_argument(
        '--fix',
        action='store_true',
        help='Actually fix records (default is dry-run)'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of records to process (for testing)'
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={
            'fix': args.fix,
            'limit': args.limit,
        },
        context='Fixing records with missing salary data'
    )

    # Analyze first
    analysis = analyze_missing_salary_data(limit=args.limit)

    print("\n" + "=" * 80)
    print("ANALYSIS RESULTS")
    print("=" * 80)
    print(f"Total records with missing wage_annual: {analysis['total_missing']:,}")
    print(f"  Can be recalculated: {analysis['can_recalculate']:,}")
    print(f"  Cannot be recalculated: {analysis['cannot_recalculate']:,}")
    print()

    if analysis['sample_recalculable']:
        print("Sample records that CAN be recalculated:")
        for rec in analysis['sample_recalculable'][:5]:
            calculated = calculate_annual_wage(
                Decimal(str(rec['wage_from'])),
                rec['wage_unit']
            )
            print(f"  Case: {rec['case_number']}, Employer: {rec['employer_name']}")
            print(f"    wage_from: {rec['wage_from']}, wage_unit: {rec['wage_unit']}")
            print(f"    Current wage_annual: {rec['wage_annual']}")
            print(f"    Would calculate to: {calculated}")
        print()

    if analysis['sample_non_recalculable']:
        print("Sample records that CANNOT be recalculated:")
        for rec in analysis['sample_non_recalculable'][:5]:
            print(f"  Case: {rec['case_number']}, Employer: {rec['employer_name']}")
            print(f"    wage_from: {rec['wage_from']}, wage_unit: {rec['wage_unit']}, wage_annual: {rec['wage_annual']}")
        print()

    # Fix if requested
    if analysis['can_recalculate'] > 0:
        if args.fix:
            logger.info("=" * 80)
            logger.info("FIXING RECORDS")
            logger.info("=" * 80)
            results = fix_missing_salary_data(limit=args.limit, dry_run=False)

            print("\n" + "=" * 80)
            print("FIX RESULTS")
            print("=" * 80)
            print(f"Fixed: {results['fixed']:,}")
            print(f"Errors: {results['errors']}")
            print(f"Skipped: {results['skipped']}")
        else:
            logger.info("=" * 80)
            logger.info("DRY RUN - PREVIEW OF FIXES")
            logger.info("=" * 80)
            results = fix_missing_salary_data(limit=args.limit, dry_run=True)

            print("\n" + "=" * 80)
            print("DRY RUN RESULTS")
            print("=" * 80)
            print(f"[DRY RUN] Would fix: {results['fixed']:,}")
            print(f"Errors: {results['errors']}")
            print(f"Skipped: {results['skipped']}")
            print()
            print("To actually fix records, run with --fix flag")
    else:
        logger.info("No records can be recalculated - all missing records have no wage_from or wage_unit")

    sys.exit(0)


if __name__ == '__main__':
    main()
