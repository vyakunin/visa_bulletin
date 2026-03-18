#!/usr/bin/env python3
"""
Investigate records with missing salary data.

This script performs comprehensive analysis to understand why records have
missing salary data (wage_annual is null/0).

Investigation steps:
1. Check if missing records are worksite records
2. Analyze by source file
3. Check by visa program
4. Sample records for manual inspection

Usage:
    bazel run //scripts/salary:investigate_missing_salary
    bazel run //scripts/salary:investigate_missing_salary -- --sample-size 50
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

from django.db.models import Case, Count, IntegerField, Q, Sum, When

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def step1_check_worksite_status() -> dict:
    """Step 1: Check if missing records are worksite records"""
    logger.info("=" * 80)
    logger.info("STEP 1: Checking if missing records are worksite records")
    logger.info("=" * 80)

    # Count missing salary records by worksite status
    missing_salary = SalaryRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0)
    )

    total_missing = missing_salary.count()

    # Count by worksite status
    worksite_breakdown = missing_salary.aggregate(
        is_worksite_true=Sum(
            Case(When(is_worksite=True, then=1), default=0, output_field=IntegerField())
        ),
        is_worksite_false=Sum(
            Case(
                When(is_worksite=False, then=1), default=0, output_field=IntegerField()
            )
        ),
        is_worksite_null=Sum(
            Case(
                When(is_worksite__isnull=True, then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
    )

    worksite_true = worksite_breakdown["is_worksite_true"] or 0
    worksite_false = worksite_breakdown["is_worksite_false"] or 0
    worksite_null = worksite_breakdown["is_worksite_null"] or 0

    results = {
        "total_missing": total_missing,
        "is_worksite_true": worksite_true,
        "is_worksite_false": worksite_false,
        "is_worksite_null": worksite_null,
        "worksite_true_pct": (worksite_true / total_missing * 100)
        if total_missing > 0
        else 0,
        "worksite_false_pct": (worksite_false / total_missing * 100)
        if total_missing > 0
        else 0,
    }

    print(f"\nTotal records with missing salary data: {total_missing:,}")
    print(
        f"  is_worksite=True:  {worksite_true:,} ({results['worksite_true_pct']:.1f}%)"
    )
    print(
        f"  is_worksite=False: {worksite_false:,} ({results['worksite_false_pct']:.1f}%)"
    )
    print(f"  is_worksite=NULL:  {worksite_null:,}")

    if worksite_true > worksite_false:
        print(
            "\n✅ Most missing records are worksite records (expected - worksite records don't have salary data)"
        )
    elif worksite_false > worksite_true:
        print("\n⚠️  Most missing records are NOT worksite records (data quality issue)")
    else:
        print("\n⚠️  Mixed - need further investigation")

    return results


def step2_analyze_by_source_file(limit: int = 20) -> list[dict]:
    """Step 2: Analyze missing salary data by source file"""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Analyzing missing salary data by source file")
    logger.info("=" * 80)

    # Get source files with missing salary data (excluding worksite records)
    source_file_stats = (
        SalaryRecord.objects.filter(
            Q(wage_annual__isnull=True) | Q(wage_annual=0), is_worksite=False
        )
        .values("source_file")
        .annotate(
            missing_count=Count("id"),
            total_count=Count(
                "id"
            ),  # This will be the count of missing records per file
        )
        .order_by("-missing_count")[:limit]
    )

    # For each source file, get total records to calculate percentage
    results = []
    for stat in source_file_stats:
        source_file = stat["source_file"] or "NULL"
        missing_count = stat["missing_count"]

        # Get total records for this source file (non-worksite)
        total_in_file = SalaryRecord.objects.filter(
            source_file=stat["source_file"], is_worksite=False
        ).count()

        missing_pct = (missing_count / total_in_file * 100) if total_in_file > 0 else 0

        results.append(
            {
                "source_file": source_file,
                "missing_count": missing_count,
                "total_in_file": total_in_file,
                "missing_pct": missing_pct,
            }
        )

    print(
        f"\nTop {limit} source files with missing salary data (excluding worksite records):"
    )
    print(f"{'Source File':<60} {'Missing':<12} {'Total':<12} {'% Missing':<12}")
    print("-" * 100)

    for result in results:
        source_file_display = (
            result["source_file"][:58]
            if len(result["source_file"]) > 58
            else result["source_file"]
        )
        print(
            f"{source_file_display:<60} {result['missing_count']:>11,} {result['total_in_file']:>11,} {result['missing_pct']:>11.1f}%"
        )

    return results


def step3_check_by_visa_program() -> dict:
    """Step 3: Check missing salary data by visa program"""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Checking missing salary data by visa program")
    logger.info("=" * 80)

    # Get missing salary data by visa program (excluding worksite)
    program_stats = (
        SalaryRecord.objects.filter(
            Q(wage_annual__isnull=True) | Q(wage_annual=0), is_worksite=False
        )
        .values("visa_program")
        .annotate(missing_count=Count("id"))
        .order_by("-missing_count")
    )

    # Get total records by program for comparison
    total_by_program = (
        SalaryRecord.objects.filter(is_worksite=False)
        .values("visa_program")
        .annotate(total_count=Count("id"))
    )

    total_by_program_dict = {
        item["visa_program"]: item["total_count"] for item in total_by_program
    }

    results = {}
    print("\nMissing salary data by visa program (excluding worksite records):")
    print(f"{'Program':<30} {'Missing':<12} {'Total':<12} {'% Missing':<12}")
    print("-" * 70)

    for stat in program_stats:
        program_value = stat["visa_program"]
        program_label = next(
            (p.label for p in VisaProgram if p.value == program_value),
            f"Unknown ({program_value})",
        )
        missing_count = stat["missing_count"]
        total_count = total_by_program_dict.get(program_value, 0)
        missing_pct = (missing_count / total_count * 100) if total_count > 0 else 0

        results[program_value] = {
            "program_label": program_label,
            "missing_count": missing_count,
            "total_count": total_count,
            "missing_pct": missing_pct,
        }

        print(
            f"{program_label:<30} {missing_count:>11,} {total_count:>11,} {missing_pct:>11.1f}%"
        )

    return results


def step4_sample_records(sample_size: int = 20) -> list[dict]:
    """Step 4: Sample records for manual inspection"""
    logger.info("\n" + "=" * 80)
    logger.info(f"STEP 4: Sampling {sample_size} records for manual inspection")
    logger.info("=" * 80)

    # Get sample records (excluding worksite, prioritizing different employers)
    sample_records = list(
        SalaryRecord.objects.filter(
            Q(wage_annual__isnull=True) | Q(wage_annual=0), is_worksite=False
        )
        .values(
            "case_number",
            "employer_name",
            "job_title",
            "visa_program",
            "wage_from",
            "wage_unit",
            "wage_annual",
            "source_file",
            "fiscal_year",
            "is_worksite",
        )
        .order_by("employer_name", "case_number")[:sample_size]
    )

    print("\nSample records with missing salary data (excluding worksite):")
    print("-" * 100)

    for i, record in enumerate(sample_records, 1):
        program_label = next(
            (p.label for p in VisaProgram if p.value == record["visa_program"]),
            f"Unknown ({record['visa_program']})",
        )
        source_file = record["source_file"] or "NULL"

        print(f"\n{i}. Case: {record['case_number']}")
        print(f"   Employer: {record['employer_name']}")
        print(f"   Job Title: {record['job_title']}")
        print(f"   Program: {program_label}")
        print(f"   Fiscal Year: {record['fiscal_year']}")
        print(f"   Source File: {source_file[:80]}")
        print(
            f"   wage_from: {record['wage_from']}, wage_unit: {record['wage_unit']}, wage_annual: {record['wage_annual']}"
        )
        print(f"   is_worksite: {record['is_worksite']}")

    return sample_records


def generate_summary(
    step1_results: dict, step2_results: list, step3_results: dict, step4_results: list
) -> str:
    """Generate summary report"""
    summary_lines = []
    summary_lines.append("\n" + "=" * 80)
    summary_lines.append("INVESTIGATION SUMMARY")
    summary_lines.append("=" * 80)

    # Step 1 summary
    summary_lines.append("\nStep 1: Worksite Status")
    summary_lines.append(f"  Total missing: {step1_results['total_missing']:,}")
    summary_lines.append(
        f"  Worksite records: {step1_results['is_worksite_true']:,} ({step1_results['worksite_true_pct']:.1f}%)"
    )
    summary_lines.append(
        f"  Non-worksite records: {step1_results['is_worksite_false']:,} ({step1_results['worksite_false_pct']:.1f}%)"
    )

    if step1_results["is_worksite_false"] > step1_results["is_worksite_true"]:
        summary_lines.append(
            "  ⚠️  RECOMMENDATION: Most missing records are NOT worksite - investigate source files"
        )
    else:
        summary_lines.append("  ✅ Most missing records are worksite (expected)")

    # Step 2 summary
    summary_lines.append("\nStep 2: Source File Analysis")
    if step2_results:
        top_file = step2_results[0]
        summary_lines.append(f"  Top source file: {top_file['source_file'][:60]}")
        summary_lines.append(
            f"    Missing: {top_file['missing_count']:,} ({top_file['missing_pct']:.1f}% of file)"
        )
        if top_file["missing_pct"] > 50:
            summary_lines.append(
                "  ⚠️  RECOMMENDATION: High percentage - investigate this source file"
            )

    # Step 3 summary
    summary_lines.append("\nStep 3: Visa Program Analysis")
    for program_value, stats in step3_results.items():
        summary_lines.append(
            f"  {stats['program_label']}: {stats['missing_count']:,} missing ({stats['missing_pct']:.1f}%)"
        )
        if stats["missing_pct"] > 20:
            summary_lines.append(f"    ⚠️  High percentage for {stats['program_label']}")

    # Step 4 summary
    summary_lines.append("\nStep 4: Sample Records")
    summary_lines.append(
        f"  Sampled {len(step4_results)} records for manual inspection"
    )
    summary_lines.append("  Review sample records above to identify patterns")

    # Overall recommendation
    summary_lines.append("\n" + "=" * 80)
    summary_lines.append("NEXT ACTIONS")
    summary_lines.append("=" * 80)

    if step1_results["is_worksite_false"] > step1_results["is_worksite_true"]:
        summary_lines.append("1. Investigate source files with high missing rates")
        summary_lines.append(
            "2. Manually inspect sample source files to check if salary data exists"
        )
        summary_lines.append(
            "3. Consider re-parsing affected source files if parsing issue found"
        )
        summary_lines.append(
            "4. Mark non-worksite records without salary as invalid if source data missing"
        )
    else:
        summary_lines.append("1. Most missing records are worksite (expected)")
        summary_lines.append(
            "2. Update validation to exclude worksite records from missing salary check"
        )
        summary_lines.append(
            "3. For non-worksite records with missing salary, investigate source files"
        )

    return "\n".join(summary_lines)


def main():
    parser = argparse.ArgumentParser(
        description="Investigate records with missing salary data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run full investigation:
    bazel run //scripts/salary:investigate_missing_salary

  Sample more records:
    bazel run //scripts/salary:investigate_missing_salary -- --sample-size 50
        """,
    )

    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Number of sample records to show (default: 20)",
    )

    parser.add_argument(
        "--source-file-limit",
        type=int,
        default=20,
        help="Number of source files to analyze (default: 20)",
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "sample_size": args.sample_size,
            "source_file_limit": args.source_file_limit,
        },
        context="Investigating records with missing salary data",
    )

    logger.info("=" * 80)
    logger.info("MISSING SALARY DATA INVESTIGATION")
    logger.info("=" * 80)
    logger.info("")
    logger.info("This investigation will:")
    logger.info("  1. Check if missing records are worksite records")
    logger.info("  2. Analyze missing data by source file")
    logger.info("  3. Check missing data by visa program")
    logger.info("  4. Sample records for manual inspection")
    logger.info("")

    # Run all investigation steps
    step1_results = step1_check_worksite_status()
    step2_results = step2_analyze_by_source_file(limit=args.source_file_limit)
    step3_results = step3_check_by_visa_program()
    step4_results = step4_sample_records(sample_size=args.sample_size)

    # Generate and print summary
    summary = generate_summary(
        step1_results, step2_results, step3_results, step4_results
    )
    print(summary)

    logger.info("\nInvestigation complete!")

    sys.exit(0)


if __name__ == "__main__":
    main()
