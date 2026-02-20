#!/usr/bin/env python3
"""
Unified comprehensive validation script for salary data.

This script consolidates functionality from:
- scripts/salary/validate_data.py (core validation)
- scripts/verify_import_completeness.py (import completeness checks)
- scripts/validate_data_comprehensive.py (comprehensive analysis)

Validates:
- Basic statistics (record counts, program distribution)
- Data integrity (required fields, calculations, dates)
- Data sanity (wage ranges, valid units, SOC codes, state codes)
- Import completeness (file rows vs DB records)
- Record completeness (missing fields by type)
- Ingestion analysis (latest ingestion runs)
- Input vs served comparison (file stats vs DB stats)
- Homepage query testing
- Golden set tracking and comparison
- Spot checks by groups (visa program, fiscal year, state, employer, wage range, case status)

Usage:
    # Run all validations (default)
    bazel run //scripts/salary:validate_data

    # Generate JSON report
    bazel run //scripts/salary:validate_data -- --json-report report.json

    # Skip spot checks (faster)
    bazel run //scripts/salary:validate_data -- --skip-spot-checks

    # Check import completeness only
    bazel run //scripts/salary:validate_data -- --check-import-completeness

    # Check incomplete records only
    bazel run //scripts/salary:validate_data -- --check-incomplete-records

    # Analyze ingestion logs
    bazel run //scripts/salary:validate_data -- --analyze-ingestion

    # Compare input vs served stats
    bazel run //scripts/salary:validate_data -- --compare-input-served

    # Test homepage queries only
    bazel run //scripts/salary:validate_data -- --test-homepage-queries

    # Golden set operations
    bazel run //scripts/salary:validate_data -- --golden-file data/validation/golden.json
    bazel run //scripts/salary:validate_data -- --update-golden
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Setup Django early (before any model imports)
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

# Configure logging
from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Import models and utilities
from django.db.models import Avg, Case, Count, F, IntegerField, Max, Min, Q, Sum, When
from django.db.utils import OperationalError

# Additional imports for comprehensive validation
from lib.business.bulletin.cutoff_data_aggregator import get_aggregated_visa_class_data
from lib.parsing.salary.wage_unit_correction import calculate_annual_wage
from lib.utils.data_source_utils import (
    count_file_rows,
    get_file_stats,
    get_fiscal_year_from_filename,
)
from lib.utils.import_completeness import (
    compare_counts_by_year,
    compare_file_counts,
    get_db_counts_by_year,
)
from lib.utils.location_utils import VALID_STATES
from lib.utils.logging_utils import ScriptLogger
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory
from models.enums.visa_program import CaseStatus, VisaProgram, WageUnit
from models.ingest.data_source import DataSource
from models.ingest.enums import IngestStatus, SourceType
from models.ingest.ingest_run import IngestRun
from models.job_title import JobTitle
from models.salary import Employer, SalaryRecord, WorksiteRecord
from models.visa_cutoff_date import Bulletin, VisaCutoffDate

script_logger = ScriptLogger(__file__)

# Reasonable wage ranges
MIN_REASONABLE_WAGE = Decimal("20000")  # $20K annually
MAX_REASONABLE_WAGE = Decimal("1000000")  # $1M annually


@dataclass
class ValidationResult:
    """Result of a single validation check"""

    check_name: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None
    warnings: list[str] | None = None
    errors: list[str] | None = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


@dataclass
class GoldenSet:
    """Golden set of expected data statistics"""

    timestamp: str
    salary_stats: dict[str, Any]
    bulletin_stats: dict[str, Any]
    homepage_queries: dict[str, Any]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


# ============================================================================
# File counting functions (from verify_import_completeness.py)
# Preserved for performance - scanning files is slow
# ============================================================================


def cached_file_rows(filepath: Path) -> int:
    """Get cached file row count, or count and cache if not available.

    This is a thin wrapper around count_file_rows for backwards compatibility.
    The caching is now handled by count_file_rows itself.
    """
    result = count_file_rows(filepath, logger_instance=logger)
    return result if result is not None else 0


# ============================================================================
# Import completeness validation (from verify_import_completeness.py)
# ============================================================================


def verify_import_counts() -> list[ValidationResult]:
    """Verify that file row counts match database record counts.

    Compares total rows in Excel files to total records in database.
    Uses cached file row counts for performance.
    """
    results = []

    # Use BUILD_WORKSPACE_DIRECTORY if available to find the real source root
    workspace_dir = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    data_dir = workspace_dir / "data/salary"

    if not data_dir.exists():
        results.append(
            ValidationResult(
                check_name="Import Counts Verification",
                passed=False,
                message=f"Data directory not found: {data_dir}",
                errors=[f"Data directory not found: {data_dir}"],
            )
        )
        return results

    xlsx_files = list(data_dir.glob("**/*.xlsx"))

    total_file_rows = 0
    file_counts = {}

    logger.info(f"Found {len(xlsx_files)} Excel files in {data_dir}")

    for file_path in xlsx_files:
        rows = cached_file_rows(file_path)
        file_counts[file_path.name] = rows
        total_file_rows += rows
        logger.debug(f"{file_path.name}: {rows} rows")

    logger.info(f"Total rows in input files: {total_file_rows:,}")

    # DB Counts
    try:
        salary_count = SalaryRecord.objects.count()
        worksite_count = WorksiteRecord.objects.count()
        total_db_records = salary_count + worksite_count

        logger.info(f"DB SalaryRecords: {salary_count:,}")
        logger.info(f"DB WorksiteRecords: {worksite_count:,}")
        logger.info(f"Total DB Records: {total_db_records:,}")

        diff = total_file_rows - total_db_records
        diff_pct = (diff / total_file_rows * 100) if total_file_rows > 0 else 0

        logger.info(f"Difference (File Rows - DB Records): {diff:,} ({diff_pct:.1f}%)")

        # Allow 5% deviation
        passed = abs(diff_pct) <= 5.0

        results.append(
            ValidationResult(
                check_name="Import Counts Verification",
                passed=passed,
                message=f"File rows: {total_file_rows:,}, DB records: {total_db_records:,}, Difference: {diff:,} ({diff_pct:.1f}%)",
                details={
                    "total_file_rows": total_file_rows,
                    "salary_records": salary_count,
                    "worksite_records": worksite_count,
                    "total_db_records": total_db_records,
                    "difference": diff,
                    "difference_pct": diff_pct,
                    "file_counts": file_counts,
                },
                warnings=[]
                if passed
                else [f"Significant difference in record counts: {diff_pct:.1f}%"],
                errors=[]
                if passed
                else [
                    f"Significant difference in record counts: {diff_pct:.1f}% (file rows: {total_file_rows:,}, DB records: {total_db_records:,})"
                ],
            )
        )

    except OperationalError as e:
        results.append(
            ValidationResult(
                check_name="Import Counts Verification",
                passed=False,
                message=f"Database error (tables missing?): {e}",
                errors=[f"Database error: {e}"],
            )
        )

    return results


def verify_import_counts_by_year() -> list[ValidationResult]:
    """Verify that file row counts match database record counts per fiscal year.

    Compares rows in Excel files grouped by fiscal year to DB records grouped by fiscal year.
    Shows side-by-side comparison for each year.

    Uses extracted logic from lib.utils.import_completeness for testability.
    """
    results = []

    # Use BUILD_WORKSPACE_DIRECTORY if available to find the real source root
    workspace_dir = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    data_dir = workspace_dir / "data/salary"

    if not data_dir.exists():
        results.append(
            ValidationResult(
                check_name="Import Counts by Year Verification",
                passed=False,
                message=f"Data directory not found: {data_dir}",
                errors=[f"Data directory not found: {data_dir}"],
            )
        )
        return results

    try:
        # Use extracted module for comparison logic
        db_counts_by_year = get_db_counts_by_year()
        year_comparisons = compare_counts_by_year(
            data_dir, db_counts_by_year, min_discrepancy_pct=5.0
        )

        # Build comparison table for all years (including those without discrepancies)
        # Get all years from files and DB
        xlsx_files = list(data_dir.glob("**/*.xlsx"))
        files_by_year: dict[int, list[tuple[Path, int]]] = defaultdict(list)

        for file_path in xlsx_files:
            rows = count_file_rows(file_path)
            if rows is None:
                continue
            fiscal_year = get_fiscal_year_from_filename(file_path.name)
            if fiscal_year is not None:
                files_by_year[fiscal_year].append((file_path, rows))

        all_years = sorted(
            set(list(files_by_year.keys()) + list(db_counts_by_year.keys()))
        )
        comparison_table = []
        total_file_rows_by_year = 0
        total_db_records_by_year = 0

        for year in all_years:
            file_rows = sum(rows for _, rows in files_by_year.get(year, []))
            db_records = db_counts_by_year.get(year, 0)

            total_file_rows_by_year += file_rows
            total_db_records_by_year += db_records

            diff = file_rows - db_records
            diff_pct = (diff / file_rows * 100) if file_rows > 0 else 0
            file_names = [f.name for f, _ in files_by_year.get(year, [])]

            comparison_table.append(
                {
                    "fiscal_year": year,
                    "file_rows": file_rows,
                    "db_records": db_records,
                    "difference": diff,
                    "difference_pct": diff_pct,
                    "files": file_names,
                }
            )

        # Overall check
        overall_passed = len(year_comparisons) == 0

        # Build detailed message
        message_lines = [
            f"Per-year comparison: {len(all_years)} fiscal years analyzed",
            f"Total file rows: {total_file_rows_by_year:,}, Total DB records: {total_db_records_by_year:,}",
        ]
        if year_comparisons:
            message_lines.append(
                f"Found {len(year_comparisons)} years with >5% discrepancy"
            )

        discrepancies = [
            {
                "year": comp.fiscal_year,
                "file_rows": comp.file_rows,
                "db_records": comp.db_records,
                "difference_pct": comp.difference_pct,
            }
            for comp in year_comparisons
        ]

        results.append(
            ValidationResult(
                check_name="Import Counts by Year Verification",
                passed=overall_passed,
                message="\n".join(message_lines),
                details={
                    "total_file_rows": total_file_rows_by_year,
                    "total_db_records": total_db_records_by_year,
                    "years_analyzed": len(all_years),
                    "years_with_discrepancies": len(year_comparisons),
                    "comparison_by_year": comparison_table,
                    "discrepancies": discrepancies,
                },
                warnings=[]
                if overall_passed
                else [
                    f"Found {len(year_comparisons)} fiscal years with >5% discrepancy between file rows and DB records"
                ],
                errors=[]
                if overall_passed
                else [
                    f"Significant discrepancies found in {len(year_comparisons)} fiscal years. Review comparison_by_year details."
                ],
            )
        )

        # Log detailed comparison
        logger.info("=" * 80)
        logger.info("PER-YEAR COMPARISON: Input Files vs Database")
        logger.info("=" * 80)
        logger.info(
            f"{'Fiscal Year':<12} {'File Rows':<15} {'DB Records':<15} {'Difference':<15} {'Diff %':<10} {'Status'}"
        )
        logger.info("-" * 80)
        for comp in comparison_table:
            status = "✓" if abs(comp["difference_pct"]) <= 5.0 else "✗"
            logger.info(
                f"FY {comp['fiscal_year']:<10d} "
                f"{comp['file_rows']:>14,} "
                f"{comp['db_records']:>14,} "
                f"{comp['difference']:>14,} "
                f"{comp['difference_pct']:>9.1f}% "
                f"{status}"
            )
        logger.info("=" * 80)

    except OperationalError as e:
        results.append(
            ValidationResult(
                check_name="Import Counts by Year Verification",
                passed=False,
                message=f"Database error (tables missing?): {e}",
                errors=[f"Database error: {e}"],
            )
        )

    return results


def verify_import_counts_by_file() -> list[ValidationResult]:
    """Verify that file row counts match database record counts per file.

    Compares each file's row count to its database record count.
    Reports files with significant discrepancies.

    Uses extracted logic from lib.utils.import_completeness for testability.
    """
    results = []

    # Use BUILD_WORKSPACE_DIRECTORY if available to find the real source root
    workspace_dir = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    data_dir = workspace_dir / "data/salary" / "dol_data"

    if not data_dir.exists():
        results.append(
            ValidationResult(
                check_name="Import Counts by File Verification",
                passed=False,
                message=f"Data directory not found: {data_dir}",
                errors=[f"Data directory not found: {data_dir}"],
            )
        )
        return results

    try:
        # Use extracted module for comparison logic - get ALL files for full table
        all_file_comparisons = compare_file_counts(
            data_dir,
            min_discrepancy_threshold=100,
            min_discrepancy_pct=1.0,
            return_all=True,
        )

        # Filter to only significant discrepancies for validation check
        significant_discrepancies = [
            comp
            for comp in all_file_comparisons
            if abs(comp.discrepancy) >= 100 or abs(comp.discrepancy_pct) >= 1.0
        ]

        # Build comparison details (all files)
        comparison_details = [
            {
                "file": comp.filename,
                "file_rows": comp.file_rows,
                "db_records": comp.db_records,
                "discrepancy": comp.discrepancy,
                "discrepancy_pct": comp.discrepancy_pct,
                "by_program": comp.by_program,
                "reason": comp.reason,
            }
            for comp in all_file_comparisons
        ]

        total_discrepancy = sum(abs(comp.discrepancy) for comp in all_file_comparisons)

        # Overall check (based on significant discrepancies only)
        overall_passed = len(significant_discrepancies) == 0

        # Build detailed message
        message_lines = [
            f"Per-file comparison: {len(all_file_comparisons)} files analyzed",
            f"{len(significant_discrepancies)} files with significant discrepancies (>1% or >100 records)",
            f"Total discrepancy: {total_discrepancy:,} records",
        ]

        results.append(
            ValidationResult(
                check_name="Import Counts by File Verification",
                passed=overall_passed,
                message="\n".join(message_lines),
                details={
                    "files_analyzed": len(all_file_comparisons),
                    "files_with_discrepancies": len(significant_discrepancies),
                    "total_discrepancy": total_discrepancy,
                    "comparison_by_file": comparison_details,
                },
                warnings=[]
                if overall_passed
                else [
                    f"Found {len(significant_discrepancies)} files with significant discrepancies (>1% or >100 records)"
                ],
                errors=[]
                if overall_passed
                else [
                    f"Significant discrepancies found in {len(significant_discrepancies)} files. Review comparison_by_file details."
                ],
            )
        )

        # Log full comparison table
        logger.info("=" * 120)
        logger.info("PER-FILE COMPARISON: Input Files vs Database")
        logger.info("=" * 120)
        logger.info(
            f"{'Filename':<50} {'File Rows':<15} {'DB Records':<15} {'Discrepancy':<15} {'Diff %':<10} {'Status':<8} {'Reason'}"
        )
        logger.info("-" * 120)
        for comp in all_file_comparisons:
            is_significant = (
                abs(comp.discrepancy) >= 100 or abs(comp.discrepancy_pct) >= 1.0
            )
            status = "✗" if is_significant else "✓"
            # Truncate long filenames for display
            display_name = (
                comp.filename[:47] + "..." if len(comp.filename) > 50 else comp.filename
            )
            # Show reason if available (truncate if too long)
            reason_display = (
                comp.reason[:20] + "..."
                if comp.reason and len(comp.reason) > 23
                else (comp.reason or "")
            )
            logger.info(
                f"{display_name:<50} "
                f"{comp.file_rows:>14,} "
                f"{comp.db_records:>14,} "
                f"{comp.discrepancy:>14,} "
                f"{comp.discrepancy_pct:>9.1f}% "
                f"{status:<8} "
                f"{reason_display}"
            )
        logger.info("=" * 120)

    except Exception as e:
        logger.error(f"Error during per-file comparison: {e}", exc_info=True)
        results.append(
            ValidationResult(
                check_name="Import Counts by File Verification",
                passed=False,
                message=f"Error during per-file comparison: {e}",
                errors=[f"Error: {e}"],
            )
        )

    return results


def check_record_completeness() -> list[ValidationResult]:
    """Check for incomplete records using comprehensive filter-based approach.

    This function preserves the incomplete_salary_filters/incomplete_worksite_filters
    approach for comprehensive differentiated incompleteness checks.
    """
    results = []

    logger.info("Checking for incomplete records...")

    try:
        # Check SalaryRecord completeness with comprehensive filters
        incomplete_salary_filters = [
            {
                "name": "case_number",
                "filter": Q(case_number__isnull=True) | Q(case_number=""),
            },
            {
                "name": "job_title",
                "filter": Q(job_title__isnull=True) | Q(job_title=""),
            },
            {
                "name": "wage_annual",
                "filter": Q(wage_annual__isnull=True) | Q(wage_annual=0),
            },
            {
                "name": "employer_name",
                "filter": Q(employer_name__isnull=True) | Q(employer_name=""),
            },
            {"name": "employer", "filter": Q(employer__isnull=True)},
            {"name": "fiscal_year", "filter": Q(fiscal_year__isnull=True)},
        ]

        salary_completeness_details = {}
        for filter_def in incomplete_salary_filters:
            incomplete_count = SalaryRecord.objects.filter(filter_def["filter"]).count()
            salary_completeness_details[filter_def["name"]] = incomplete_count
            if incomplete_count > 0:
                logger.warning(
                    f"Found {incomplete_count} incomplete SalaryRecords with {filter_def['name']}"
                )
            else:
                logger.debug(
                    f"No incomplete SalaryRecords with {filter_def['name']} found."
                )

        # Check WorksiteRecord completeness with comprehensive filters
        # NOTE: WorksiteRecord does NOT have employer_name or employer fields by design
        # Worksite records focus on location data, not employer data
        # Salary data (wage_annual) is optional for worksite records
        incomplete_worksite_filters = [
            {
                "name": "case_number",
                "filter": Q(case_number__isnull=True) | Q(case_number=""),
            },
            {
                "name": "job_title",
                "filter": Q(job_title__isnull=True) | Q(job_title=""),
            },
            {"name": "fiscal_year", "filter": Q(fiscal_year__isnull=True)},
            # Note: wage_annual is optional for worksite records (not checked here)
        ]

        worksite_completeness_details = {}
        for filter_def in incomplete_worksite_filters:
            incomplete_count = WorksiteRecord.objects.filter(
                filter_def["filter"]
            ).count()
            worksite_completeness_details[filter_def["name"]] = incomplete_count
            if incomplete_count > 0:
                logger.warning(
                    f"Found {incomplete_count} incomplete WorksiteRecords with {filter_def['name']}"
                )
            else:
                logger.debug(
                    f"No incomplete WorksiteRecords with {filter_def['name']} found."
                )

        # Overall completeness check
        total_salary = SalaryRecord.objects.count()
        total_worksite = WorksiteRecord.objects.count()

        # Check for any incomplete salary records (any of the critical fields)
        incomplete_salary = SalaryRecord.objects.filter(
            Q(case_number__isnull=True)
            | Q(case_number="")
            | Q(employer_name__isnull=True)
            | Q(employer_name="")
            | Q(job_title__isnull=True)
            | Q(job_title="")
        ).count()

        results.append(
            ValidationResult(
                check_name="Record Completeness",
                passed=incomplete_salary == 0,
                message=f"Incomplete SalaryRecords: {incomplete_salary}/{total_salary}, Incomplete WorksiteRecords: see details",
                details={
                    "incomplete_salary_total": incomplete_salary,
                    "total_salary": total_salary,
                    "total_worksite": total_worksite,
                    "salary_completeness_by_field": salary_completeness_details,
                    "worksite_completeness_by_field": worksite_completeness_details,
                },
                warnings=[]
                if incomplete_salary == 0
                else [f"Found {incomplete_salary} incomplete SalaryRecords"],
                errors=[]
                if incomplete_salary == 0
                else [
                    f"Found {incomplete_salary} incomplete SalaryRecords with missing critical fields"
                ],
            )
        )

    except OperationalError as e:
        results.append(
            ValidationResult(
                check_name="Record Completeness",
                passed=False,
                message=f"Skipping completeness check due to database error: {e}",
                errors=[f"Database error: {e}"],
            )
        )

    return results


# ============================================================================
# Core validation functions (from original validate_data.py)
# ============================================================================


def validate_basic_stats(
    total_records: int | None = None,
) -> tuple[list[ValidationResult], int]:
    """Validate basic statistics match expectations

    Returns:
        tuple: (results, total_records) - total_records can be reused to avoid repeated queries
    """
    results = []

    # Total record count (cache if not provided)
    if total_records is None:
        total_records = SalaryRecord.objects.count()
    results.append(
        ValidationResult(
            check_name="Total Record Count",
            passed=total_records > 0,
            message=f"Total records: {total_records:,}",
            details={"count": total_records},
        )
    )

    # Records by visa program
    program_counts = SalaryRecord.objects.values("visa_program").annotate(
        count=Count("id")
    )
    program_details = {}
    for item in program_counts:
        program = item["visa_program"]
        count = item["count"]
        program_details[program] = count
        program_label = next(
            (p.label for p in VisaProgram if p.value == program), program
        )
        results.append(
            ValidationResult(
                check_name=f"Records by Program: {program_label}",
                passed=count > 0,
                message=f"{program_label}: {count:,} records",
                details={"program": program, "count": count},
            )
        )

    # Records by fiscal year
    fiscal_year_counts = (
        SalaryRecord.objects.values("fiscal_year")
        .annotate(count=Count("id"))
        .order_by("fiscal_year")
    )
    fy_details = {}
    for item in fiscal_year_counts:
        fy = item["fiscal_year"]
        count = item["count"]
        fy_details[fy] = count
        results.append(
            ValidationResult(
                check_name=f"Records by Fiscal Year: FY {fy}",
                passed=count > 0,
                message=f"FY {fy}: {count:,} records",
                details={"fiscal_year": fy, "count": count},
            )
        )

    # Records by source file
    source_file_counts = (
        SalaryRecord.objects.values("source_file")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    source_details = {}
    for item in source_file_counts[:10]:  # Top 10 files
        source = item["source_file"] or "Unknown"
        count = item["count"]
        source_details[source] = count

    results.append(
        ValidationResult(
            check_name="Records by Source File",
            passed=len(source_details) > 0,
            message=f"{len(source_file_counts)} source files, top 10 shown",
            details={"top_files": source_details},
        )
    )

    # Employer count
    employer_count = Employer.objects.count()
    unique_employers_in_records = (
        SalaryRecord.objects.values("employer_id").distinct().count()
    )
    results.append(
        ValidationResult(
            check_name="Employer Count",
            passed=employer_count > 0,
            message=f"Total employers: {employer_count:,}, Employers with records: {unique_employers_in_records:,}",
            details={
                "total_employers": employer_count,
                "employers_with_records": unique_employers_in_records,
            },
        )
    )

    return results, total_records


def validate_data_integrity(total_records: int | None = None) -> list[ValidationResult]:
    """Validate data integrity (required fields, calculations, dates)"""
    results = []

    # Required fields check - combine into single query for better performance
    logger.info("  Checking required fields...")
    # Use conditional aggregation to count all three in one query
    required_field_counts = SalaryRecord.objects.aggregate(
        missing_case_number=Sum(
            Case(
                When(case_number__isnull=True, then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
        missing_employer_name=Sum(
            Case(
                When(employer_name__isnull=True, then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
        missing_job_title=Sum(
            Case(
                When(job_title__isnull=True, then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
    )
    missing_case_number = required_field_counts["missing_case_number"] or 0
    missing_employer_name = required_field_counts["missing_employer_name"] or 0
    missing_job_title = required_field_counts["missing_job_title"] or 0

    results.append(
        ValidationResult(
            check_name="Required Fields",
            passed=missing_case_number == 0
            and missing_employer_name == 0
            and missing_job_title == 0,
            message=f"Missing case_number: {missing_case_number}, employer_name: {missing_employer_name}, job_title: {missing_job_title}",
            details={
                "missing_case_number": missing_case_number,
                "missing_employer_name": missing_employer_name,
                "missing_job_title": missing_job_title,
            },
            errors=[]
            if (
                missing_case_number == 0
                and missing_employer_name == 0
                and missing_job_title == 0
            )
            else [
                f"Missing case_number: {missing_case_number}",
                f"Missing employer_name: {missing_employer_name}",
                f"Missing job_title: {missing_job_title}",
            ],
        )
    )

    # Wage calculation check
    # Check records where wage_annual doesn't match calculated value
    logger.info("  Checking wage calculation accuracy (sampling 1000 records)...")
    wage_calc_errors = []
    sample_size = min(1000, total_records or SalaryRecord.objects.count())
    # Use only() to fetch only needed fields (faster, less memory)
    sample_records = SalaryRecord.objects.filter(
        wage_from__isnull=False, wage_unit__isnull=False
    ).only("case_number", "wage_from", "wage_unit", "wage_annual")[:sample_size]

    calc_errors = 0
    for record in sample_records:
        calculated = calculate_annual_wage(record.wage_from, record.wage_unit)
        if calculated and record.wage_annual:
            # Allow small rounding differences (within $1)
            diff = abs(float(calculated) - float(record.wage_annual))
            if diff > 1.0:
                calc_errors += 1
                if len(wage_calc_errors) < 5:  # Store first 5 examples
                    wage_calc_errors.append(
                        {
                            "case_number": record.case_number,
                            "wage_from": float(record.wage_from),
                            "wage_unit": record.wage_unit,
                            "wage_annual_stored": float(record.wage_annual),
                            "wage_annual_calculated": float(calculated),
                            "difference": diff,
                        }
                    )

    results.append(
        ValidationResult(
            check_name="Wage Calculation Accuracy",
            passed=calc_errors == 0,
            message=f"Wage calculation errors in sample: {calc_errors}/{sample_size}",
            details={
                "sample_size": sample_size,
                "errors": calc_errors,
                "error_rate": calc_errors / sample_size if sample_size > 0 else 0,
                "examples": wage_calc_errors[:5],
            },
            errors=[]
            if calc_errors == 0
            else [f"{calc_errors} wage calculation errors found in sample"],
        )
    )

    # Date validation
    logger.info("  Checking date validity...")
    invalid_dates = SalaryRecord.objects.filter(
        Q(case_submitted__isnull=False)
        & Q(decision_date__isnull=False)
        & Q(case_submitted__gt=F("decision_date"))
    ).count()

    invalid_employment_dates = SalaryRecord.objects.filter(
        Q(employment_start__isnull=False)
        & Q(employment_end__isnull=False)
        & Q(employment_start__gt=F("employment_end"))
    ).count()

    results.append(
        ValidationResult(
            check_name="Date Validation",
            passed=invalid_dates == 0 and invalid_employment_dates == 0,
            message=f"Invalid date sequences: case_submitted > decision_date: {invalid_dates}, employment_start > employment_end: {invalid_employment_dates}",
            details={
                "invalid_case_dates": invalid_dates,
                "invalid_employment_dates": invalid_employment_dates,
            },
            errors=[]
            if (invalid_dates == 0 and invalid_employment_dates == 0)
            else [
                f"Invalid case dates: {invalid_dates}",
                f"Invalid employment dates: {invalid_employment_dates}",
            ],
        )
    )

    # Duplicate case numbers (should be none due to unique constraint, but check anyway)
    logger.info("  Checking for duplicate case numbers...")
    duplicates = (
        SalaryRecord.objects.values("case_number")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    duplicate_count = duplicates.count()
    results.append(
        ValidationResult(
            check_name="Duplicate Case Numbers",
            passed=duplicate_count == 0,
            message=f"Duplicate case numbers: {duplicate_count}",
            details={"duplicate_count": duplicate_count},
            errors=[]
            if duplicate_count == 0
            else [f"Found {duplicate_count} duplicate case numbers"],
        )
    )

    return results


def spot_check_by_group(group_type: str, sample_size: int = 10) -> list[dict]:
    """Perform spot checks on records grouped by different criteria"""
    samples = []

    if group_type == "visa_program":
        for program in [VisaProgram.H1B, VisaProgram.PERM]:
            records = SalaryRecord.objects.filter(visa_program=program)[:sample_size]
            for record in records:
                samples.append(
                    {
                        "group": f"Visa Program: {program.label}",
                        "case_number": record.case_number,
                        "employer_name": record.employer_name,
                        "job_title": record.job_title,
                        "wage_annual": float(record.wage_annual)
                        if record.wage_annual
                        else None,
                        "worksite_state": record.worksite_state,
                        "fiscal_year": record.fiscal_year,
                    }
                )

    elif group_type == "fiscal_year":
        fiscal_years = (
            SalaryRecord.objects.values("fiscal_year")
            .annotate(count=Count("id"))
            .order_by("fiscal_year")
        )
        for fy_item in fiscal_years[:5]:  # Top 5 fiscal years
            fy = fy_item["fiscal_year"]
            records = SalaryRecord.objects.filter(fiscal_year=fy)[:sample_size]
            for record in records:
                samples.append(
                    {
                        "group": f"Fiscal Year: FY {fy}",
                        "case_number": record.case_number,
                        "employer_name": record.employer_name,
                        "job_title": record.job_title,
                        "wage_annual": float(record.wage_annual)
                        if record.wage_annual
                        else None,
                        "case_submitted": record.case_submitted.isoformat()
                        if record.case_submitted
                        else None,
                        "decision_date": record.decision_date.isoformat()
                        if record.decision_date
                        else None,
                    }
                )

    elif group_type == "state":
        top_states = (
            SalaryRecord.objects.filter(worksite_state__isnull=False)
            .values("worksite_state")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )
        for state_item in top_states:
            state = state_item["worksite_state"]
            records = SalaryRecord.objects.filter(worksite_state=state)[:sample_size]
            for record in records:
                samples.append(
                    {
                        "group": f"State: {state}",
                        "case_number": record.case_number,
                        "employer_name": record.employer_name,
                        "job_title": record.job_title,
                        "worksite_city": record.worksite_city,
                        "wage_annual": float(record.wage_annual)
                        if record.wage_annual
                        else None,
                    }
                )

    elif group_type == "employer":
        top_employers = (
            SalaryRecord.objects.values("employer_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        for emp_item in top_employers:
            emp_name = emp_item["employer_name"]
            records = SalaryRecord.objects.filter(employer_name=emp_name)[:sample_size]
            for record in records:
                samples.append(
                    {
                        "group": f"Employer: {emp_name}",
                        "case_number": record.case_number,
                        "job_title": record.job_title,
                        "wage_annual": float(record.wage_annual)
                        if record.wage_annual
                        else None,
                        "worksite_state": record.worksite_state,
                    }
                )

    elif group_type == "wage_range":
        # Get percentiles
        records_with_wage = SalaryRecord.objects.filter(
            wage_annual__isnull=False, wage_annual__gt=0
        ).order_by("wage_annual")
        total = records_with_wage.count()
        if total > 0:
            percentiles = [10, 50, 90]
            for pct in percentiles:
                idx = int(total * pct / 100)
                if idx < total:
                    record = records_with_wage[idx]
                    samples.append(
                        {
                            "group": f"Wage Percentile: {pct}th",
                            "case_number": record.case_number,
                            "employer_name": record.employer_name,
                            "job_title": record.job_title,
                            "wage_annual": float(record.wage_annual),
                            "wage_from": float(record.wage_from),
                            "wage_unit": record.wage_unit,
                        }
                    )

    elif group_type == "case_status":
        for status in [CaseStatus.CERTIFIED, CaseStatus.DENIED, CaseStatus.WITHDRAWN]:
            records = SalaryRecord.objects.filter(case_status=status)[:sample_size]
            for record in records:
                samples.append(
                    {
                        "group": f"Case Status: {status.label}",
                        "case_number": record.case_number,
                        "employer_name": record.employer_name,
                        "job_title": record.job_title,
                        "wage_annual": float(record.wage_annual)
                        if record.wage_annual
                        else None,
                    }
                )

    return samples


def validate_data_sanity(total_records: int | None = None) -> list[ValidationResult]:
    """Validate data sanity (wage ranges, valid units, SOC codes, state codes)"""
    results = []

    # High-wage validation (separate check)
    logger.info("  Checking high-wage records (>$1M)...")
    high_wage_count = SalaryRecord.objects.filter(
        wage_annual__gt=MAX_REASONABLE_WAGE
    ).count()
    results.append(
        ValidationResult(
            check_name="High-Wage Validation",
            passed=high_wage_count == 0,
            message=f"Records with wages > $1M: {high_wage_count}",
            details={
                "max_reasonable": float(MAX_REASONABLE_WAGE),
                "high_wage_count": high_wage_count,
            },
            errors=[]
            if high_wage_count == 0
            else [
                f"CRITICAL: {high_wage_count} records have wages > $1M - likely parsing errors"
            ],
            warnings=[]
            if high_wage_count == 0
            else [
                f"{high_wage_count} records have extremely high wages (>$1M) - almost certainly invalid"
            ],
        )
    )

    # Low-wage validation (separate check)
    logger.info("  Checking low-wage records (<$20K)...")
    low_wage_count = SalaryRecord.objects.filter(
        wage_annual__lt=MIN_REASONABLE_WAGE, wage_annual__gt=0
    ).count()
    results.append(
        ValidationResult(
            check_name="Low-Wage Validation",
            passed=low_wage_count == 0,
            message=f"Records with wages < $20K: {low_wage_count}",
            details={
                "min_reasonable": float(MIN_REASONABLE_WAGE),
                "low_wage_count": low_wage_count,
            },
            warnings=[]
            if low_wage_count == 0
            else [
                f"{low_wage_count} records have wages < $20K - may be hourly wages stored as annual"
            ],
        )
    )

    # Combined wage range validation (for backward compatibility)
    wage_out_of_range = high_wage_count + low_wage_count
    results.append(
        ValidationResult(
            check_name="Wage Range Validation",
            passed=wage_out_of_range == 0,
            message=f"Records with wages outside reasonable range ($20K-$1M): {wage_out_of_range}",
            details={
                "min_reasonable": float(MIN_REASONABLE_WAGE),
                "max_reasonable": float(MAX_REASONABLE_WAGE),
                "out_of_range_count": wage_out_of_range,
                "high_wage_count": high_wage_count,
                "low_wage_count": low_wage_count,
            },
            warnings=[]
            if wage_out_of_range == 0
            else [
                f"{wage_out_of_range} records have wages outside reasonable range ({high_wage_count} high, {low_wage_count} low)"
            ],
        )
    )

    # Valid wage units
    logger.info("  Checking wage unit validity...")
    invalid_units = SalaryRecord.objects.exclude(
        wage_unit__in=[u.value for u in WageUnit]
    ).count()
    results.append(
        ValidationResult(
            check_name="Valid Wage Units",
            passed=invalid_units == 0,
            message=f"Records with invalid wage units: {invalid_units}",
            details={"invalid_unit_count": invalid_units},
            errors=[]
            if invalid_units == 0
            else [f"Found {invalid_units} records with invalid wage units"],
        )
    )

    # SOC code format (basic check: should be numeric with optional dash)
    logger.info("  Checking SOC code format (sampling 1000 records)...")
    import re

    soc_pattern = re.compile(r"^\d{2}-\d{4}(\.\d{2})?$")
    invalid_soc = 0
    sample_records = SalaryRecord.objects.filter(soc_code__isnull=False).exclude(
        soc_code=""
    )[:1000]
    for record in sample_records:
        if not soc_pattern.match(record.soc_code):
            invalid_soc += 1

    results.append(
        ValidationResult(
            check_name="SOC Code Format",
            passed=invalid_soc == 0,
            message=f"Records with invalid SOC code format (sample of 1000): {invalid_soc}",
            details={
                "invalid_soc_count": invalid_soc,
                "sample_size": min(1000, sample_records.count()),
            },
            warnings=[]
            if invalid_soc == 0
            else [
                f"Found {invalid_soc} records with invalid SOC code format in sample"
            ],
        )
    )

    # State code validation - reuse query results to avoid duplicate filtering
    logger.info("  Checking state code validity...")
    invalid_states_qs = (
        SalaryRecord.objects.filter(worksite_state__isnull=False)
        .exclude(worksite_state__in=VALID_STATES)
        .exclude(worksite_state="")
    )

    invalid_states = invalid_states_qs.count()

    # Get sample invalid states for reporting (reuse same queryset)
    logger.info("  Getting sample invalid states for reporting...")
    sample_invalid_states = list(
        invalid_states_qs.values("worksite_state")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    # Build examples string for warnings
    state_examples = (
        ", ".join(
            [f"{s['worksite_state']} ({s['count']})" for s in sample_invalid_states[:5]]
        )
        if invalid_states > 0
        else ""
    )

    results.append(
        ValidationResult(
            check_name="State Code Validation",
            passed=invalid_states == 0,
            message=f"Records with invalid state codes: {invalid_states}",
            details={
                "invalid_state_count": invalid_states,
                "sample_invalid_states": {
                    s["worksite_state"]: s["count"] for s in sample_invalid_states
                },
            },
            warnings=[]
            if invalid_states == 0
            else [
                f"Found {invalid_states} records with invalid state codes. Examples: {state_examples}"
            ],
        )
    )

    # Orphaned employers check
    logger.info("  Checking for orphaned employers...")
    from models.salary import Employer

    orphaned_employers = Employer.objects.filter(salary_records__isnull=True).count()
    results.append(
        ValidationResult(
            check_name="Orphaned Employers",
            passed=orphaned_employers == 0,
            message=f"Orphaned employers (no salary records): {orphaned_employers}",
            details={"orphaned_count": orphaned_employers},
            warnings=[]
            if orphaned_employers == 0
            else [f"Found {orphaned_employers} orphaned employers (no salary records)"],
        )
    )

    # Duplicate clusters check (case-insensitive canonical_name)
    logger.info("  Checking for duplicate employer clusters...")
    from collections import defaultdict

    from models.salary import EmployerCluster

    clusters_by_name = defaultdict(list)
    for cluster in EmployerCluster.objects.all():
        # Group by lowercase canonical_name to catch case variations
        normalized_name = cluster.canonical_name.lower()
        clusters_by_name[normalized_name].append(cluster.id)

    # Find duplicates (canonical_name with 2+ clusters)
    duplicate_names = {
        name: cluster_ids
        for name, cluster_ids in clusters_by_name.items()
        if len(cluster_ids) > 1
    }
    duplicate_count = sum(len(ids) - 1 for ids in duplicate_names.values())

    results.append(
        ValidationResult(
            check_name="Duplicate Employer Clusters",
            passed=len(duplicate_names) == 0,
            message=f"Duplicate clusters (same canonical_name, case-insensitive): {len(duplicate_names)} names, {duplicate_count} duplicate clusters",
            details={
                "duplicate_names_count": len(duplicate_names),
                "duplicate_clusters_count": duplicate_count,
                "sample_names": list(duplicate_names.keys())[:5]
                if duplicate_names
                else [],
            },
            errors=[]
            if len(duplicate_names) == 0
            else [
                f"Found {len(duplicate_names)} canonical names with duplicates (case-insensitive)",
                f"Total duplicate clusters: {duplicate_count}",
                "Run: bazel run //scripts/salary:merge_duplicate_clusters",
            ],
        )
    )

    # Orphaned/empty clusters check
    logger.info("  Checking for empty employer clusters...")
    empty_clusters = (
        EmployerCluster.objects.annotate(employer_count=Count("employers"))
        .filter(employer_count=0)
        .count()
    )

    results.append(
        ValidationResult(
            check_name="Empty Employer Clusters",
            passed=empty_clusters == 0,
            message=f"Empty clusters (no employers): {empty_clusters}",
            details={"empty_clusters_count": empty_clusters},
            warnings=[]
            if empty_clusters == 0
            else [
                f"Found {empty_clusters} empty employer clusters",
                "Run: bazel run //scripts/salary:merge_duplicate_clusters (merging duplicates also cleans up empty clusters)",
            ],
        )
    )

    # Null/empty critical fields
    logger.info("  Checking for empty critical fields...")
    empty_critical = SalaryRecord.objects.filter(
        Q(case_number="") | Q(employer_name="") | Q(job_title="")
    ).count()

    results.append(
        ValidationResult(
            check_name="Empty Critical Fields",
            passed=empty_critical == 0,
            message=f"Records with empty critical fields: {empty_critical}",
            details={"empty_critical_count": empty_critical},
            errors=[]
            if empty_critical == 0
            else [f"Found {empty_critical} records with empty critical fields"],
        )
    )

    # Missing salary data (completely missing - no wage_from, wage_unit, or wage_annual)
    # This catches records that show "$--" in the UI (wage_annual is null)
    # NOTE: Exclude worksite records - they are stored in WorksiteRecord model, not SalaryRecord
    # SalaryRecord.is_worksite=True records are legacy and should be migrated to WorksiteRecord
    # For SalaryRecord (is_worksite=False), salary data is REQUIRED
    logger.info(
        "  Checking for missing salary data in SalaryRecord (excluding worksite records)..."
    )

    # Reuse queryset to avoid duplicate filtering
    # Exclude worksite records - they should be in WorksiteRecord model, not SalaryRecord
    # SalaryRecord records (is_worksite=False) MUST have salary data
    null_wage_annual_qs = SalaryRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0),
        is_worksite=False,  # Worksite records should be in WorksiteRecord model - exclude from check
    )

    # Also check WorksiteRecord - salary data is REQUIRED (not optional)
    logger.info(
        "  Checking for missing salary data in WorksiteRecord (salary is REQUIRED)..."
    )
    missing_worksite_salary = WorksiteRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0)
    )
    missing_worksite_count = missing_worksite_salary.count()

    logger.info("    Counting records with null/zero wage_annual (non-worksite)...")
    null_wage_annual = null_wage_annual_qs.count()

    logger.info("    Counting records with completely missing salary data...")
    missing_salary_data = null_wage_annual_qs.filter(
        Q(wage_from__isnull=True) | Q(wage_from=0),
        Q(wage_unit__isnull=True) | Q(wage_unit=""),
    ).count()

    # Get sample records by employer to identify patterns (reuse queryset)
    logger.info("    Grouping missing salary data by employer (this may be slow)...")
    sample_missing_by_employer = list(
        null_wage_annual_qs.values("employer_name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    # Build employer examples string for warnings
    employer_examples = (
        ", ".join(
            [
                f"{s['employer_name']} ({s['count']})"
                for s in sample_missing_by_employer[:5]
            ]
        )
        if null_wage_annual > 0
        else ""
    )

    results.append(
        ValidationResult(
            check_name="Missing Salary Data",
            passed=missing_salary_data == 0
            and null_wage_annual == 0
            and missing_worksite_count == 0,
            message=f"SalaryRecord missing: {null_wage_annual} (completely missing: {missing_salary_data}), WorksiteRecord missing: {missing_worksite_count}",
            details={
                "missing_salary_data_count": missing_salary_data,
                "null_wage_annual_count": null_wage_annual,
                "missing_worksite_count": missing_worksite_count,
                "total_records": total_records,
                "percentage_missing": (null_wage_annual / total_records * 100)
                if total_records > 0
                else 0,
                "sample_by_employer": {
                    s["employer_name"]: s["count"] for s in sample_missing_by_employer
                },
            },
            errors=[]
            if (
                missing_salary_data == 0
                and null_wage_annual == 0
                and missing_worksite_count == 0
            )
            else [
                f"CRITICAL: {null_wage_annual} SalaryRecord records have missing salary data (wage_annual is null/0) - shows as '$--' in UI",
                f"CRITICAL: {missing_worksite_count} WorksiteRecord records have missing salary data (salary is REQUIRED, not optional)",
                f"Completely missing salary data (no wage_from, wage_unit, or wage_annual): {missing_salary_data} SalaryRecord records",
            ],
            warnings=[]
            if (
                missing_salary_data == 0
                and null_wage_annual == 0
                and missing_worksite_count == 0
            )
            else [
                f"{null_wage_annual} SalaryRecord records have null/zero wage_annual (displays as '$--' in search results)",
                f"{missing_worksite_count} WorksiteRecord records have missing salary data (REQUIRED, not optional)",
                f"Top employers with missing salary data: {employer_examples}",
            ],
        )
    )

    return results


def validate_job_titles() -> list[ValidationResult]:
    """Validate job title normalization quality and roman numeral preservation."""
    results = []

    # Job title normalization check (duplicate words in normalized titles)
    logger.info("  Checking job title normalization quality...")
    duplicate_word_count = 0
    sample_bad_titles = []

    for jt in JobTitle.objects.all()[:10000]:  # Check sample of 10K titles
        words = jt.title_normalized.split()
        if len(words) != len(set(words)):  # Has duplicate words
            duplicate_word_count += 1
            if len(sample_bad_titles) < 5:  # Collect first 5 examples
                sample_bad_titles.append(
                    {
                        "title": jt.title,
                        "normalized": jt.title_normalized,
                        "level": jt.experience_level or "no level",
                    }
                )

    results.append(
        ValidationResult(
            check_name="Job Title Normalization Quality",
            passed=duplicate_word_count == 0,
            message=f"Job titles with duplicate words in normalized form (sample of 10K): {duplicate_word_count}",
            details={
                "duplicate_word_count": duplicate_word_count,
                "sample_size": min(10000, JobTitle.objects.count()),
                "sample_bad_titles": sample_bad_titles,
            },
            errors=[]
            if duplicate_word_count == 0
            else [
                f"Found {duplicate_word_count} job titles with duplicate words in normalized form",
                "Run: bazel run //scripts/salary:fix_job_title_normalization",
                f"Examples: {sample_bad_titles[:3]}",
            ],
        )
    )

    # Roman numeral preservation check (ensure II, III, IV, V are kept verbatim)
    logger.info("  Checking roman numeral preservation in job titles...")
    roman_numeral_count = sum(
        [
            JobTitle.objects.filter(experience_level="ii").count(),
            JobTitle.objects.filter(experience_level="iii").count(),
            JobTitle.objects.filter(experience_level="iv").count(),
            JobTitle.objects.filter(experience_level="v").count(),
        ]
    )

    results.append(
        ValidationResult(
            check_name="Job Title Roman Numeral Preservation",
            passed=roman_numeral_count > 0,
            message=f"Job titles with roman numerals (ii, iii, iv, v): {roman_numeral_count:,}",
            details={
                "roman_numeral_titles": roman_numeral_count,
                "level_ii": JobTitle.objects.filter(experience_level="ii").count(),
                "level_iii": JobTitle.objects.filter(experience_level="iii").count(),
                "level_iv": JobTitle.objects.filter(experience_level="iv").count(),
                "level_v": JobTitle.objects.filter(experience_level="v").count(),
            },
            warnings=[]
            if roman_numeral_count > 0
            else [
                "No job titles with roman numerals found - may indicate normalization issue",
                "Expected titles like 'Software Engineer II' to preserve 'ii' as experience level",
            ],
        )
    )

    return results


# ============================================================================
# Comprehensive validation functions (from validate_data_comprehensive.py)
# ============================================================================


def analyze_latest_ingestion_logs() -> dict:
    """
    Analyze latest ingestion runs to understand what was imported.

    Returns:
        Dict with ingestion summary statistics
    """
    logger.info("Analyzing latest ingestion logs...")

    # Get recent completed runs
    recent_runs = IngestRun.objects.filter(status=IngestStatus.COMPLETED).order_by(
        "-completed_at"
    )[:50]

    summary = {
        "total_runs": recent_runs.count(),
        "runs_by_source_type": defaultdict(int),
        "runs_by_domain": defaultdict(int),
        "total_records_created": 0,
        "total_records_failed": 0,
        "recent_runs": [],
    }

    for run in recent_runs:
        summary["runs_by_source_type"][run.source.source_type] += 1
        summary["runs_by_domain"][run.source.domain] += 1
        summary["total_records_created"] += run.records_created
        summary["total_records_failed"] += run.records_failed

        summary["recent_runs"].append(
            {
                "id": run.id,
                "source_url": run.source.url,
                "source_type": run.source.source_type,
                "domain": run.source.domain,
                "records_created": run.records_created,
                "records_failed": run.records_failed,
                "completed_at": run.completed_at.isoformat()
                if run.completed_at
                else None,
                "source_file": Path(run.checkpoint.get("filepath", "")).name
                if run.checkpoint.get("filepath")
                else None,
            }
        )

    return summary


def get_input_file_stats(source: DataSource) -> dict | None:
    """
    Get statistics from input file (Excel/CSV) before import.

    Args:
        source: DataSource with local_file_path

    Returns:
        Dict with file stats or None if file not found
    """
    if not source.local_file_path:
        return None

    filepath = Path(source.local_file_path)
    return get_file_stats(filepath, logger_instance=logger)


def compare_input_vs_served_stats() -> dict:
    """
    Compare input file statistics to served data statistics.

    Returns:
        Dict with comparison results
    """
    logger.info("Comparing input file stats to served data stats...")

    comparison = {
        "sources_analyzed": 0,
        "sources_with_files": 0,
        "comparisons": [],
        "discrepancies": [],
    }

    # Get recent completed runs with their sources
    recent_runs = (
        IngestRun.objects.filter(status=IngestStatus.COMPLETED)
        .select_related("source")
        .order_by("-completed_at")[:20]
    )

    logger.debug(
        "Recent runs: "
        + "\n".join([f"{run.id}: {run.source.url}" for run in recent_runs])
    )

    for run in recent_runs:
        source = run.source
        comparison["sources_analyzed"] += 1

        # Get input file stats
        input_stats = get_input_file_stats(source)
        if not input_stats:
            continue

        logger.debug(f"Input stats: {input_stats}")

        comparison["sources_with_files"] += 1

        # Get served data stats for this source file
        source_file = (
            Path(run.checkpoint.get("filepath", "")).name
            if run.checkpoint.get("filepath")
            else None
        )
        if not source_file:
            source_file = (
                Path(source.local_file_path).name if source.local_file_path else None
            )

        if source_file:
            # Count records by various dimensions
            if source.source_type in [SourceType.LCA, SourceType.PERM]:
                served_records = SalaryRecord.objects.filter(source_file=source_file)
            elif source.source_type == SourceType.WORKSITE:
                served_records = WorksiteRecord.objects.filter(source_file=source_file)
            else:
                served_records = None

            logger.debug(f"Served records: {served_records}")

            if served_records is not None:
                served_count = served_records.count()
                input_count = input_stats.get("row_count", 0)

                comp = {
                    "source_file": source_file,
                    "source_type": source.source_type,
                    "input_rows": input_count,
                    "served_records": served_count,
                    "difference": served_count - input_count,
                    "difference_pct": ((served_count - input_count) / input_count * 100)
                    if input_count > 0
                    else 0,
                }

                # Check for significant discrepancies
                if input_count > 0:
                    # Allow 5% difference (some rows may be skipped/rejected)
                    if abs(comp["difference_pct"]) > 5:
                        comparison["discrepancies"].append(
                            {
                                "source_file": source_file,
                                "issue": f"Significant difference: {comp['difference_pct']:.1f}% ({served_count} served vs {input_count} input rows)",
                                "severity": "warning"
                                if abs(comp["difference_pct"]) < 20
                                else "error",
                            }
                        )

                comparison["comparisons"].append(comp)

    return comparison


def test_homepage_queries() -> dict:
    """
    Test queries corresponding to home page main entry points.

    Returns:
        Dict with query results and statistics
    """
    logger.info("Testing home page main entry point queries...")

    results = {
        "dashboard_queries": {},
        "salary_search_queries": {},
        "aggregations": {},
    }

    # Test dashboard queries (main entry points)
    test_cases = [
        {
            "category": VisaCategory.FAMILY_SPONSORED.value,
            "country": Country.ALL.value,
            "action_type": ActionType.FINAL_ACTION.value,
        },
        {
            "category": VisaCategory.FAMILY_SPONSORED.value,
            "country": Country.CHINA.value,
            "action_type": ActionType.FINAL_ACTION.value,
        },
        {
            "category": VisaCategory.FAMILY_SPONSORED.value,
            "country": Country.INDIA.value,
            "action_type": ActionType.FINAL_ACTION.value,
        },
        {
            "category": VisaCategory.EMPLOYMENT_BASED.value,
            "country": Country.ALL.value,
            "action_type": ActionType.FINAL_ACTION.value,
        },
        {
            "category": VisaCategory.EMPLOYMENT_BASED.value,
            "country": Country.CHINA.value,
            "action_type": ActionType.FINAL_ACTION.value,
        },
        {
            "category": VisaCategory.EMPLOYMENT_BASED.value,
            "country": Country.INDIA.value,
            "action_type": ActionType.FINAL_ACTION.value,
        },
    ]

    for test_case in test_cases:
        try:
            visa_class_data, has_data = get_aggregated_visa_class_data(
                test_case["category"],
                test_case["country"],
                test_case["action_type"],
                date.today(),
            )

            key = f"{test_case['category']}_{test_case['country']}_{test_case['action_type']}"
            results["dashboard_queries"][key] = {
                "has_data": has_data,
                "visa_classes_count": len(visa_class_data),
                "total_data_points": sum(
                    len(vc.get("dates", [])) for vc in visa_class_data
                ),
            }
        except Exception as e:
            logger.warning(f"Dashboard query failed for {test_case}: {e}")
            key = f"{test_case['category']}_{test_case['country']}_{test_case['action_type']}"
            results["dashboard_queries"][key] = {"error": str(e)}

    # Test salary search queries
    salary_queries = [
        {"program": "h1b", "year": None},
        {"program": "perm", "year": None},
        {"program": "h1b", "year": 2024},
        {"program": "perm", "year": 2024},
        {"state": "CA", "program": "h1b"},
        {"state": "NY", "program": "h1b"},
    ]

    for query in salary_queries:
        records = SalaryRecord.objects.all()

        if query.get("program") == "h1b":
            records = records.filter(visa_program=VisaProgram.H1B)
        elif query.get("program") == "perm":
            records = records.filter(visa_program=VisaProgram.PERM)

        if query.get("year"):
            records = records.filter(fiscal_year=query["year"])

        if query.get("state"):
            records = records.filter(worksite_state=query["state"])

        key = "_".join(f"{k}={v}" for k, v in query.items())
        results["salary_search_queries"][key] = {
            "count": records.count(),
            "has_wages": records.filter(wage_annual__isnull=False).count(),
        }

    # Test aggregations (used in salary search stats)
    records_with_wage = SalaryRecord.objects.filter(
        wage_annual__isnull=False, wage_annual__gt=0
    )
    if records_with_wage.count() > 0:
        results["aggregations"] = records_with_wage.aggregate(
            avg_salary=Avg("wage_annual"),
            min_salary=Min("wage_annual"),
            max_salary=Max("wage_annual"),
        )
        # Convert Decimal to float for JSON
        results["aggregations"] = {
            k: float(v) if v else None for k, v in results["aggregations"].items()
        }

    return results


def get_served_data_stats() -> dict:
    """
    Get comprehensive statistics about served data.

    Returns:
        Dict with served data statistics
    """
    logger.info("Collecting served data statistics...")

    stats = {
        "salary_records": {},
        "worksite_records": {},
        "bulletin_records": {},
    }

    # Salary records stats
    total_salary = SalaryRecord.objects.count()
    stats["salary_records"] = {
        "total": total_salary,
        "by_program": {},
        "by_fiscal_year": {},
        "by_state": {},
        "null_rates": {},
    }

    if total_salary > 0:
        # By program
        for program in [VisaProgram.H1B, VisaProgram.PERM]:
            count = SalaryRecord.objects.filter(visa_program=program).count()
            stats["salary_records"]["by_program"][program.label] = count

        # By fiscal year
        fiscal_years = (
            SalaryRecord.objects.values("fiscal_year")
            .annotate(count=Count("id"))
            .order_by("-fiscal_year")[:10]
        )
        stats["salary_records"]["by_fiscal_year"] = {
            str(fy["fiscal_year"]): fy["count"] for fy in fiscal_years
        }

        # By state (top 10)
        top_states = (
            SalaryRecord.objects.filter(worksite_state__isnull=False)
            .exclude(worksite_state="")
            .values("worksite_state")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        stats["salary_records"]["by_state"] = {
            s["worksite_state"]: s["count"] for s in top_states
        }

        # Null rates
        stats["salary_records"]["null_rates"] = {
            "wage_annual": (
                total_salary
                - SalaryRecord.objects.filter(wage_annual__isnull=False).count()
            )
            / total_salary
            * 100,
            "worksite_state": (
                total_salary
                - SalaryRecord.objects.filter(worksite_state__isnull=False)
                .exclude(worksite_state="")
                .count()
            )
            / total_salary
            * 100,
            "employer_name": (
                total_salary
                - SalaryRecord.objects.filter(employer_name__isnull=False).count()
            )
            / total_salary
            * 100,
        }

    # Worksite records stats
    total_worksite = WorksiteRecord.objects.count()
    stats["worksite_records"] = {
        "total": total_worksite,
    }

    # Bulletin records stats
    total_bulletins = Bulletin.objects.count()
    total_cutoffs = VisaCutoffDate.objects.count()
    stats["bulletin_records"] = {
        "total_bulletins": total_bulletins,
        "total_cutoff_dates": total_cutoffs,
        "by_category": {},
        "by_country": {},
    }

    if total_cutoffs > 0:
        by_category = VisaCutoffDate.objects.values("visa_category").annotate(
            count=Count("id")
        )
        stats["bulletin_records"]["by_category"] = {
            cat["visa_category"]: cat["count"] for cat in by_category
        }

        by_country = (
            VisaCutoffDate.objects.values("country")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        stats["bulletin_records"]["by_country"] = {
            str(c["country"]): c["count"] for c in by_country
        }

    return stats


def load_golden_set(golden_file: Path) -> GoldenSet | None:
    """Load golden set from file"""
    if not golden_file.exists():
        return None

    try:
        with open(golden_file) as f:
            data = json.load(f)
        return GoldenSet.from_dict(data)
    except Exception as e:
        logger.warning(f"Could not load golden set: {e}")
        return None


def save_golden_set(golden_file: Path, golden: GoldenSet):
    """Save golden set to file"""
    golden_file.parent.mkdir(parents=True, exist_ok=True)
    with open(golden_file, "w") as f:
        json.dump(golden.to_dict(), f, indent=2, default=str)
    logger.info(f"Golden set saved to: {golden_file}")


def compare_to_golden(current: dict, golden: GoldenSet) -> dict:
    """
    Compare current statistics to golden set and detect significant changes.

    Returns:
        Dict with comparison results and detected changes
    """
    if not golden:
        return {"error": "No golden set available"}

    changes = {
        "significant_changes": [],
        "warnings": [],
        "details": {},
    }

    # Compare salary stats
    if "salary_records" in current and "salary_stats" in golden.to_dict():
        current_salary = current["salary_records"]
        golden_salary = golden.salary_stats

        # Total count change
        current_total = current_salary.get("total", 0)
        golden_total = golden_salary.get("total", 0)
        if golden_total > 0:
            change_pct = (current_total - golden_total) / golden_total * 100
            if abs(change_pct) > 10:  # More than 10% change
                changes["significant_changes"].append(
                    {
                        "metric": "salary_total_count",
                        "golden": golden_total,
                        "current": current_total,
                        "change_pct": change_pct,
                        "severity": "error" if abs(change_pct) > 50 else "warning",
                    }
                )

        # Program distribution changes
        current_programs = current_salary.get("by_program", {})
        golden_programs = golden_salary.get("by_program", {})
        for program, current_count in current_programs.items():
            golden_count = golden_programs.get(program, 0)
            if golden_count > 0:
                change_pct = (current_count - golden_count) / golden_count * 100
                if abs(change_pct) > 15:  # More than 15% change in program distribution
                    changes["significant_changes"].append(
                        {
                            "metric": f"salary_program_{program}",
                            "golden": golden_count,
                            "current": current_count,
                            "change_pct": change_pct,
                            "severity": "warning",
                        }
                    )

    # Compare homepage queries
    if "homepage_queries" in current and "homepage_queries" in golden.to_dict():
        current_queries = current["homepage_queries"]
        golden_queries = golden.homepage_queries

        for query_key, current_result in current_queries.get(
            "dashboard_queries", {}
        ).items():
            golden_result = golden_queries.get("dashboard_queries", {}).get(query_key)
            if golden_result:
                current_count = current_result.get("visa_classes_count", 0)
                golden_count = golden_result.get("visa_classes_count", 0)
                if golden_count > 0 and current_count != golden_count:
                    changes["warnings"].append(
                        {
                            "query": query_key,
                            "issue": f"Visa classes count changed: {golden_count} → {current_count}",
                        }
                    )

    return changes


# ============================================================================
# Report generation
# ============================================================================


def generate_report(
    basic_stats: list[ValidationResult],
    integrity: list[ValidationResult],
    sanity: list[ValidationResult],
    import_counts: list[ValidationResult] | None = None,
    import_counts_by_year: list[ValidationResult] | None = None,
    completeness: list[ValidationResult] | None = None,
    spot_checks: dict[str, list[dict]] | None = None,
    output_file: Path | None = None,
) -> str:
    """Generate comprehensive validation report"""
    report_lines = []

    report_lines.append("=" * 80)
    report_lines.append("SALARY DATA VALIDATION REPORT")
    report_lines.append("=" * 80)
    report_lines.append("")

    # Summary
    all_results = basic_stats + integrity + sanity
    if import_counts:
        all_results.extend(import_counts)
    if completeness:
        all_results.extend(completeness)

    total_checks = len(all_results)
    passed_checks = sum(1 for r in all_results if r.passed)
    failed_checks = total_checks - passed_checks

    total_errors = sum(len(r.errors or []) for r in all_results)
    total_warnings = sum(len(r.warnings or []) for r in all_results)

    report_lines.append("SUMMARY")
    report_lines.append("-" * 80)
    report_lines.append(f"Total checks: {total_checks}")
    report_lines.append(f"Passed: {passed_checks}")
    report_lines.append(f"Failed: {failed_checks}")
    report_lines.append(f"Total errors: {total_errors}")
    report_lines.append(f"Total warnings: {total_warnings}")
    report_lines.append("")

    # Basic Statistics
    report_lines.append("BASIC STATISTICS VALIDATION")
    report_lines.append("-" * 80)
    for result in basic_stats:
        status = "✓ PASS" if result.passed else "✗ FAIL"
        report_lines.append(f"{status}: {result.check_name}")
        report_lines.append(f"  {result.message}")
        if result.details:
            for key, value in result.details.items():
                if isinstance(value, dict):
                    report_lines.append(f"    {key}:")
                    for k, v in value.items():
                        report_lines.append(
                            f"      {k}: {v:,}"
                            if isinstance(v, int)
                            else f"      {k}: {v}"
                        )
                else:
                    report_lines.append(
                        f"    {key}: {value:,}"
                        if isinstance(value, int)
                        else f"    {key}: {value}"
                    )
        if result.errors:
            for error in result.errors:
                report_lines.append(f"    ERROR: {error}")
        if result.warnings:
            for warning in result.warnings:
                report_lines.append(f"    WARNING: {warning}")
        report_lines.append("")

    # Import Counts (if included)
    if import_counts:
        report_lines.append("IMPORT COMPLETENESS VALIDATION (TOTAL)")
        report_lines.append("-" * 80)
        for result in import_counts:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            report_lines.append(f"{status}: {result.check_name}")
            report_lines.append(f"  {result.message}")
            if result.details:
                for key, value in result.details.items():
                    if isinstance(value, dict):
                        report_lines.append(f"    {key}:")
                        for k, v in value.items():
                            report_lines.append(
                                f"      {k}: {v:,}"
                                if isinstance(v, int)
                                else f"      {k}: {v}"
                            )
                    else:
                        report_lines.append(
                            f"    {key}: {value:,}"
                            if isinstance(value, int)
                            else f"    {key}: {value}"
                        )
            if result.errors:
                for error in result.errors:
                    report_lines.append(f"    ERROR: {error}")
            if result.warnings:
                for warning in result.warnings:
                    report_lines.append(f"    WARNING: {warning}")
            report_lines.append("")

    # Record Completeness (if included)
    if completeness:
        report_lines.append("RECORD COMPLETENESS VALIDATION")
        report_lines.append("-" * 80)
        for result in completeness:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            report_lines.append(f"{status}: {result.check_name}")
            report_lines.append(f"  {result.message}")
            if result.details:
                for key, value in result.details.items():
                    if isinstance(value, dict):
                        report_lines.append(f"    {key}:")
                        for k, v in value.items():
                            report_lines.append(
                                f"      {k}: {v:,}"
                                if isinstance(v, int)
                                else f"      {k}: {v}"
                            )
                    else:
                        report_lines.append(
                            f"    {key}: {value:,}"
                            if isinstance(value, int)
                            else f"    {key}: {value}"
                        )
            if result.errors:
                for error in result.errors:
                    report_lines.append(f"    ERROR: {error}")
            if result.warnings:
                for warning in result.warnings:
                    report_lines.append(f"    WARNING: {warning}")
            report_lines.append("")

    # Data Integrity
    report_lines.append("DATA INTEGRITY VALIDATION")
    report_lines.append("-" * 80)
    for result in integrity:
        status = "✓ PASS" if result.passed else "✗ FAIL"
        report_lines.append(f"{status}: {result.check_name}")
        report_lines.append(f"  {result.message}")
        if result.details:
            for key, value in result.details.items():
                report_lines.append(
                    f"    {key}: {value:,}"
                    if isinstance(value, int)
                    else f"    {key}: {value}"
                )
        if result.errors:
            for error in result.errors:
                report_lines.append(f"    ERROR: {error}")
        if result.warnings:
            for warning in result.warnings:
                report_lines.append(f"    WARNING: {warning}")
        report_lines.append("")

    # Data Sanity
    report_lines.append("DATA SANITY VALIDATION")
    report_lines.append("-" * 80)
    for result in sanity:
        status = "✓ PASS" if result.passed else "✗ FAIL"
        report_lines.append(f"{status}: {result.check_name}")
        report_lines.append(f"  {result.message}")
        if result.details:
            for key, value in result.details.items():
                if isinstance(value, dict):
                    report_lines.append(f"    {key}:")
                    for k, v in value.items():
                        report_lines.append(
                            f"      {k}: {v:,}"
                            if isinstance(v, int)
                            else f"      {k}: {v}"
                        )
                else:
                    report_lines.append(
                        f"    {key}: {value:,}"
                        if isinstance(value, int)
                        else f"    {key}: {value}"
                    )
        if result.errors:
            for error in result.errors:
                report_lines.append(f"    ERROR: {error}")
        if result.warnings:
            for warning in result.warnings:
                report_lines.append(f"    WARNING: {warning}")
        report_lines.append("")

    # Spot Checks
    if spot_checks:
        report_lines.append("SPOT CHECKS BY GROUPS")
        report_lines.append("-" * 80)
        for group_type, samples in spot_checks.items():
            report_lines.append(f"\n{group_type.upper().replace('_', ' ')}:")
            for i, sample in enumerate(samples[:5], 1):  # Show first 5 samples
                report_lines.append(f"  Sample {i}:")
                for key, value in sample.items():
                    if value is not None:
                        report_lines.append(f"    {key}: {value}")
            if len(samples) > 5:
                report_lines.append(f"  ... and {len(samples) - 5} more samples")
            report_lines.append("")

    report_text = "\n".join(report_lines)

    # Write to file if specified
    if output_file:
        output_file.write_text(report_text)
        logger.info(f"Report written to: {output_file}")

    return report_text


# ============================================================================
# Main function
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Unified comprehensive validation script for salary data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run all validations (default):
    bazel run //scripts/salary:validate_data
  
  Generate JSON report:
    bazel run //scripts/salary:validate_data -- --json-report report.json
  
  Skip spot checks (faster):
    bazel run //scripts/salary:validate_data -- --skip-spot-checks
  
  Check import completeness only:
    bazel run //scripts/salary:validate_data -- --check-import-completeness
  
  Check incomplete records only:
    bazel run //scripts/salary:validate_data -- --check-incomplete-records
  
  Analyze ingestion logs:
    bazel run //scripts/salary:validate_data -- --analyze-ingestion
  
  Compare input vs served stats:
    bazel run //scripts/salary:validate_data -- --compare-input-served
  
  Test homepage queries only:
    bazel run //scripts/salary:validate_data -- --test-homepage-queries
  
  Golden set operations:
    bazel run //scripts/salary:validate_data -- --golden-file data/validation/golden.json
    bazel run //scripts/salary:validate_data -- --update-golden
        """,
    )

    parser.add_argument(
        "--json-report", type=Path, help="Path to write JSON validation report"
    )

    parser.add_argument(
        "--text-report", type=Path, help="Path to write text validation report"
    )

    parser.add_argument(
        "--skip-spot-checks",
        action="store_true",
        help="Skip spot checks (faster validation)",
    )

    parser.add_argument(
        "--check-import-completeness",
        action="store_true",
        help="Check import completeness (file rows vs DB records)",
    )

    parser.add_argument(
        "--check-import-completeness-by-file",
        action="store_true",
        help="Check import completeness per file (reports files with discrepancies)",
    )

    parser.add_argument(
        "--check-incomplete-records",
        action="store_true",
        help="Check for incomplete records (missing fields by type)",
    )

    parser.add_argument(
        "--check-job-titles",
        action="store_true",
        help="Check job title normalization quality and roman numeral preservation",
    )

    parser.add_argument(
        "--analyze-ingestion", action="store_true", help="Analyze latest ingestion logs"
    )

    parser.add_argument(
        "--compare-input-served",
        action="store_true",
        help="Compare input file stats to served data stats",
    )

    parser.add_argument(
        "--test-homepage-queries",
        action="store_true",
        help="Test homepage queries only (faster)",
    )

    parser.add_argument(
        "--golden-file",
        type=Path,
        default=Path("data/validation/golden.json"),
        help="Path to golden set file",
    )

    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Update golden set with current statistics",
    )

    args = parser.parse_args()

    # Log script execution
    script_logger.log_call(
        args={
            "json_report": str(args.json_report) if args.json_report else None,
            "text_report": str(args.text_report) if args.text_report else None,
            "skip_spot_checks": args.skip_spot_checks,
            "check_import_completeness": args.check_import_completeness,
            "check_incomplete_records": args.check_incomplete_records,
            "check_job_titles": args.check_job_titles,
            "analyze_ingestion": args.analyze_ingestion,
            "compare_input_served": args.compare_input_served,
            "test_homepage_queries": args.test_homepage_queries,
            "golden_file": str(args.golden_file),
            "update_golden": args.update_golden,
        },
        context="Unified comprehensive data validation",
    )

    logger.info("=" * 80)
    logger.info("UNIFIED COMPREHENSIVE DATA VALIDATION")
    logger.info("=" * 80)
    logger.info("")

    # Determine which validations to run
    # If specific flags are set, run only those. Otherwise run all.
    run_all = not any(
        [
            args.check_import_completeness,
            args.check_import_completeness_by_file,
            args.check_incomplete_records,
            args.check_job_titles,
            args.analyze_ingestion,
            args.compare_input_served,
            args.test_homepage_queries,
        ]
    )

    results = {
        "timestamp": datetime.now().isoformat(),
        "basic_stats": [],
        "integrity": [],
        "sanity": [],
        "job_titles": [],
        "import_counts": [],
        "import_counts_by_year": [],
        "completeness": [],
        "ingestion_analysis": {},
        "input_vs_served": {},
        "served_stats": {},
        "homepage_queries": {},
        "golden_comparison": {},
        "spot_checks": {},
    }

    # Core validations (run unless only specific checks requested)
    if run_all or not args.test_homepage_queries:
        # Basic statistics
        logger.info("Running basic statistics validation...")
        basic_stats, total_records = validate_basic_stats()
        results["basic_stats"] = [r.to_dict() for r in basic_stats]
        logger.info("  Basic statistics validation completed")

        # Data integrity
        logger.info("Running data integrity validation...")
        integrity = validate_data_integrity(total_records=total_records)
        results["integrity"] = [r.to_dict() for r in integrity]
        logger.info("  Data integrity validation completed")

        # Data sanity
        logger.info("Running data sanity validation...")
        logger.info(
            "  This includes checks for wage ranges, units, SOC codes, state codes, and missing salary data"
        )
        sanity = validate_data_sanity(total_records=total_records)
        results["sanity"] = [r.to_dict() for r in sanity]
        logger.info("  Data sanity validation completed")

    # Job title validation
    if run_all or args.check_job_titles:
        logger.info("Running job title validation...")
        job_titles = validate_job_titles()
        results["job_titles"] = [r.to_dict() for r in job_titles]
        logger.info("  Job title validation completed")

    # Import completeness check
    if run_all or args.check_import_completeness:
        logger.info("Checking import completeness (file rows vs DB records)...")
        import_counts = verify_import_counts()
        results["import_counts"] = [r.to_dict() for r in import_counts]
        logger.info("  Import completeness check completed")

        # Also run per-year comparison
        logger.info(
            "Checking import completeness by fiscal year (per-year comparison)..."
        )
        import_counts_by_year = verify_import_counts_by_year()
        results["import_counts_by_year"] = [r.to_dict() for r in import_counts_by_year]
        logger.info("  Per-year import completeness check completed")

    # Per-file import completeness check
    if run_all or args.check_import_completeness_by_file:
        logger.info("Checking import completeness by file (per-file comparison)...")
        import_counts_by_file = verify_import_counts_by_file()
        results["import_counts_by_file"] = [r.to_dict() for r in import_counts_by_file]
        logger.info("  Per-file import completeness check completed")

    # Record completeness check
    if run_all or args.check_incomplete_records:
        logger.info("Checking record completeness...")
        completeness = check_record_completeness()
        results["completeness"] = [r.to_dict() for r in completeness]
        logger.info("  Record completeness check completed")

    # Ingestion analysis
    if run_all or args.analyze_ingestion:
        logger.info("Analyzing latest ingestion logs...")
        results["ingestion_analysis"] = analyze_latest_ingestion_logs()
        logger.info(
            f"  Found {results['ingestion_analysis']['total_runs']} recent completed runs"
        )
        logger.info(
            f"  Total records created: {results['ingestion_analysis']['total_records_created']:,}"
        )

    # Input vs served comparison
    if (run_all or args.compare_input_served) and not args.test_homepage_queries:
        logger.info("Comparing input file stats to served data stats...")
        results["input_vs_served"] = compare_input_vs_served_stats()
        logger.info(
            f"  Analyzed {results['input_vs_served']['sources_analyzed']} sources"
        )
        if results["input_vs_served"]["discrepancies"]:
            logger.warning(
                f"  Found {len(results['input_vs_served']['discrepancies'])} discrepancies"
            )

    # Served data statistics
    if run_all or args.test_homepage_queries or args.update_golden:
        logger.info("Collecting served data statistics...")
        results["served_stats"] = get_served_data_stats()
        logger.info(
            f"  Salary records: {results['served_stats']['salary_records'].get('total', 0):,}"
        )
        logger.info(
            f"  Bulletin records: {results['served_stats']['bulletin_records'].get('total_cutoff_dates', 0):,}"
        )

    # Homepage queries
    if run_all or args.test_homepage_queries:
        logger.info("Testing homepage main entry point queries...")
        results["homepage_queries"] = test_homepage_queries()
        logger.info(
            f"  Dashboard queries tested: {len(results['homepage_queries']['dashboard_queries'])}"
        )
        logger.info(
            f"  Salary search queries tested: {len(results['homepage_queries']['salary_search_queries'])}"
        )

    # Spot checks
    spot_checks = {}
    if (run_all or not args.test_homepage_queries) and not args.skip_spot_checks:
        logger.info("Performing spot checks...")
        for group_type in [
            "visa_program",
            "fiscal_year",
            "state",
            "employer",
            "wage_range",
            "case_status",
        ]:
            logger.info(f"  Spot checking by {group_type}...")
            spot_checks[group_type] = spot_check_by_group(group_type, sample_size=10)
        results["spot_checks"] = spot_checks
    else:
        logger.info(
            "Skipping spot checks (--skip-spot-checks specified or homepage-only mode)"
        )

    # Golden set operations
    golden = load_golden_set(args.golden_file)
    if golden:
        logger.info("Comparing to golden set...")
        results["golden_comparison"] = compare_to_golden(
            results["served_stats"], golden
        )
        if results["golden_comparison"].get("significant_changes"):
            logger.warning(
                f"  Found {len(results['golden_comparison']['significant_changes'])} significant changes"
            )
    elif args.update_golden:
        logger.info("Creating new golden set...")
        golden = GoldenSet(
            timestamp=datetime.now().isoformat(),
            salary_stats=results["served_stats"].get("salary_records", {}),
            bulletin_stats=results["served_stats"].get("bulletin_records", {}),
            homepage_queries=results["homepage_queries"],
        )
        save_golden_set(args.golden_file, golden)
        logger.info("  Golden set created")
    elif run_all:
        logger.info("No golden set found (use --update-golden to create one)")

    # Generate text report
    if run_all or not args.test_homepage_queries:
        logger.info("Generating validation report...")
        basic_stats = [ValidationResult(**r) for r in results["basic_stats"]]
        integrity = [ValidationResult(**r) for r in results["integrity"]]
        sanity = [ValidationResult(**r) for r in results["sanity"]]
        import_counts = (
            [ValidationResult(**r) for r in results["import_counts"]]
            if results["import_counts"]
            else None
        )
        import_counts_by_year = (
            [ValidationResult(**r) for r in results["import_counts_by_year"]]
            if results.get("import_counts_by_year")
            else None
        )
        completeness = (
            [ValidationResult(**r) for r in results["completeness"]]
            if results["completeness"]
            else None
        )
        report_text = generate_report(
            basic_stats,
            integrity,
            sanity,
            import_counts,
            import_counts_by_year,
            completeness,
            spot_checks,
            args.text_report,
        )

        # Print report to console
        print(report_text)

    # Generate JSON report if requested
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_report, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"JSON report written to: {args.json_report}")

    # Exit with error code if any checks failed
    if run_all or not args.test_homepage_queries:
        all_results = (
            [ValidationResult(**r) for r in results["basic_stats"]]
            + [ValidationResult(**r) for r in results["integrity"]]
            + [ValidationResult(**r) for r in results["sanity"]]
        )
        if results["import_counts"]:
            all_results.extend(
                [ValidationResult(**r) for r in results["import_counts"]]
            )
        if results["completeness"]:
            all_results.extend([ValidationResult(**r) for r in results["completeness"]])

        has_errors = any(not r.passed for r in all_results) or any(
            r.errors for r in all_results
        )
        if has_errors:
            logger.error("Validation completed with errors. Please review the report.")
            sys.exit(1)
        else:
            logger.info("Validation completed successfully!")
            sys.exit(0)
    else:
        logger.info("Validation completed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
