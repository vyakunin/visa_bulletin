#!/usr/bin/env python3
"""
Check for suspicious salary values in the database.

This script identifies records with unrealistic salaries that may be data entry errors
or miscoded values (e.g., hourly wages coded as annual).

Usage:
    bazel run //scripts/salary:check_suspicious_salaries

    # Show more details
    bazel run //scripts/salary:check_suspicious_salaries -- --verbose

    # Check specific job title
    bazel run //scripts/salary:check_suspicious_salaries -- --job-title "Software Engineer"
"""

import os
import sys

import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

import argparse

from django.db.models import Count

from lib.utils.logging_utils import ScriptLogger
from models.salary import SalaryRecord

# Script usage logging
script_logger = ScriptLogger(__file__)

# Salary validation bounds (same as job_title_stats.py)
MIN_REASONABLE_SALARY = 30000  # $30k/year minimum
MAX_REASONABLE_SALARY = 1000000  # $1M/year maximum


def check_suspicious_salaries(verbose: bool = False, job_title: str | None = None):
    """
    Check for suspicious salary values.
    
    Args:
        verbose: Show detailed records
        job_title: Filter by job title (optional)
    """
    print("=" * 80)
    print("SUSPICIOUS SALARY ANALYSIS")
    print("=" * 80)

    # Base queryset
    records = SalaryRecord.objects.filter(
        wage_annual__isnull=False,
    ).exclude(
        wage_annual=0,
    )

    if job_title:
        records = records.filter(job_title__icontains=job_title)
        print(f"\nFiltered by job title: {job_title}")

    total_records = records.count()
    print(f"\nTotal records with salary data: {total_records:,}")

    # 1. Check for extremely low salaries (< $30k annual)
    print("\n" + "=" * 80)
    print(f"1. EXTREMELY LOW SALARIES (< ${MIN_REASONABLE_SALARY:,})")
    print("=" * 80)

    low_salary_records = records.filter(wage_annual__lt=MIN_REASONABLE_SALARY)
    low_count = low_salary_records.count()
    low_percentage = (low_count / total_records * 100) if total_records > 0 else 0

    print(f"\nFound {low_count:,} records ({low_percentage:.2f}%) with suspiciously low salaries")

    if low_count > 0:
        # Group by wage_unit to see if these are miscoded hourly wages
        by_unit = low_salary_records.values('wage_unit').annotate(count=Count('id')).order_by('-count')
        print("\nBreakdown by wage unit:")
        for item in by_unit:
            print(f"  {item['wage_unit']}: {item['count']:,} records")

        if verbose and low_count <= 20:
            print("\nSample records:")
            for record in low_salary_records[:20]:
                print(f"  Case: {record.case_number}")
                print(f"    Job: {record.job_title}")
                print(f"    Employer: {record.employer_name}")
                print(f"    Salary: ${record.wage_annual:,.2f} annual (from ${record.wage_from:,.2f} {record.wage_unit})")
                print(f"    Fiscal Year: {record.fiscal_year}")
                print()

    # 2. Check for extremely high salaries (> $1M annual)
    print("\n" + "=" * 80)
    print(f"2. EXTREMELY HIGH SALARIES (> ${MAX_REASONABLE_SALARY:,})")
    print("=" * 80)

    high_salary_records = records.filter(wage_annual__gt=MAX_REASONABLE_SALARY)
    high_count = high_salary_records.count()
    high_percentage = (high_count / total_records * 100) if total_records > 0 else 0

    print(f"\nFound {high_count:,} records ({high_percentage:.2f}%) with suspiciously high salaries")

    if high_count > 0:
        # Group by wage_unit
        by_unit = high_salary_records.values('wage_unit').annotate(count=Count('id')).order_by('-count')
        print("\nBreakdown by wage unit:")
        for item in by_unit:
            print(f"  {item['wage_unit']}: {item['count']:,} records")

        # Show top job titles with high salaries
        by_job = high_salary_records.values('job_title').annotate(count=Count('id')).order_by('-count')[:10]
        print("\nTop job titles with high salaries:")
        for item in by_job:
            print(f"  {item['job_title']}: {item['count']:,} records")

        if verbose and high_count <= 20:
            print("\nSample records:")
            for record in high_salary_records.order_by('-wage_annual')[:20]:
                print(f"  Case: {record.case_number}")
                print(f"    Job: {record.job_title}")
                print(f"    Employer: {record.employer_name}")
                print(f"    Salary: ${record.wage_annual:,.2f} annual (from ${record.wage_from:,.2f} {record.wage_unit})")
                print(f"    Fiscal Year: {record.fiscal_year}")
                print()

    # 3. Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    suspicious_count = low_count + high_count
    suspicious_percentage = (suspicious_count / total_records * 100) if total_records > 0 else 0

    print(f"\nTotal records: {total_records:,}")
    print(f"Suspicious records: {suspicious_count:,} ({suspicious_percentage:.2f}%)")
    print(f"  - Too low (< ${MIN_REASONABLE_SALARY:,}): {low_count:,} ({low_percentage:.2f}%)")
    print(f"  - Too high (> ${MAX_REASONABLE_SALARY:,}): {high_count:,} ({high_percentage:.2f}%)")
    print(f"\nReasonable records: {total_records - suspicious_count:,} ({100 - suspicious_percentage:.2f}%)")

    print("\n" + "=" * 80)
    print("NOTE: These suspicious records are automatically filtered out in salary statistics")
    print("and charts to prevent skewing the data.")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Check for suspicious salary values")
    parser.add_argument('--verbose', action='store_true', help='Show detailed records')
    parser.add_argument('--job-title', type=str, help='Filter by job title')

    args = parser.parse_args()

    # Log script execution
    script_logger.log_call(
        args={'verbose': args.verbose, 'job_title': args.job_title},
        context='Checking for suspicious salary values in database'
    )

    try:
        check_suspicious_salaries(verbose=args.verbose, job_title=args.job_title)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
