"""Shared validation logic for salary data plugins"""

import logging
from decimal import Decimal
from pathlib import Path

from django.db import models

from lib.ingest.base import ValidationResult
from lib.parsing.salary.wage_unit_correction import MAX_ANNUAL, MIN_ANNUAL
from lib.utils.location_utils import VALID_STATES
from models.enums.visa_program import VisaProgram
from models.ingest.ingest_run import IngestRun
from models.salary import SalaryRecord

logger = logging.getLogger(__name__)

# Import thresholds from config (single source of truth)
MIN_REASONABLE_WAGE = Decimal(str(MIN_ANNUAL))
MAX_REASONABLE_WAGE = Decimal(str(MAX_ANNUAL))
# Threshold for flagging too many high wages for manual review
HIGH_WAGE_REVIEW_THRESHOLD_PCT = (
    1.0  # Flag if >1% of records have wages outside valid range
)


def _get_records_for_run(
    run: IngestRun, visa_program: VisaProgram, model_class
) -> tuple[models.QuerySet, str | None]:
    """Get records created in this run."""
    source_file = (
        Path(run.checkpoint.get("filepath", "")).name
        if run.checkpoint.get("filepath")
        else None
    )

    if source_file:
        records = model_class.objects.filter(
            source_file=source_file, visa_program=visa_program
        )
    else:
        records = model_class.objects.filter(visa_program=visa_program).order_by("-id")
        if run.records_created:
            records = records[: run.records_created]

    return records, source_file


def _validate_required_fields(
    records: models.QuerySet, model_class, errors: list[str]
) -> None:
    """Validate that required fields are present."""
    missing_case = records.filter(case_number__isnull=True).count()
    missing_job_title = records.filter(job_title__isnull=True).count()

    if missing_case > 0:
        errors.append(f"{missing_case} records missing case_number (required field)")
    if missing_job_title > 0:
        errors.append(f"{missing_job_title} records missing job_title (required field)")

    if hasattr(model_class, "employer_name"):
        missing_employer = records.filter(employer_name__isnull=True).count()
        if missing_employer > 0:
            errors.append(
                f"{missing_employer} records missing employer_name (required field)"
            )


def _validate_wage_ranges(records: models.QuerySet, warnings: list[str]) -> None:
    """Validate wage ranges and flag records for manual review."""
    records_with_wage = records.filter(wage_annual__isnull=False)
    wage_count = records_with_wage.count()

    if wage_count == 0:
        return

    # Check for wages outside valid range (too high or too low)
    extremely_high = records_with_wage.filter(wage_annual__gt=MAX_REASONABLE_WAGE)
    extremely_high_count = extremely_high.count()

    if extremely_high_count > 0:
        pct = (extremely_high_count / wage_count * 100) if wage_count > 0 else 0
        examples = list(
            extremely_high.values_list(
                "case_number", "wage_annual", "wage_unit", "job_title"
            )[:5]
        )
        example_str = ", ".join(
            [f"{c}: ${float(w):,.0f} ({u})" for c, w, u, j in examples]
        )

        if pct > HIGH_WAGE_REVIEW_THRESHOLD_PCT:
            warnings.append(
                f"CRITICAL: {extremely_high_count} records ({pct:.1f}%) have wages > ${MAX_REASONABLE_WAGE:,} - high percentage, flagging for manual review. "
                f"Examples: {example_str}"
            )
        else:
            warnings.append(
                f"CRITICAL: {extremely_high_count} records ({pct:.1f}%) have wages > ${MAX_REASONABLE_WAGE:,} - flagging for manual review. "
                f"Examples: {example_str}"
            )

    # Check for wages below minimum (may be incorrect unit or data error)
    extremely_low = records_with_wage.filter(
        wage_annual__lt=MIN_REASONABLE_WAGE, wage_annual__gt=0
    )
    extremely_low_count = extremely_low.count()
    if extremely_low_count > 0:
        pct = (extremely_low_count / wage_count * 100) if wage_count > 0 else 0
        examples = list(
            extremely_low.values_list(
                "case_number", "wage_annual", "wage_unit", "job_title"
            )[:5]
        )
        example_str = ", ".join(
            [f"{c}: ${float(w):,.0f} ({u})" for c, w, u, j in examples]
        )

        if pct > 5:
            warnings.append(
                f"{extremely_low_count} records ({pct:.1f}%) have wages < ${MIN_REASONABLE_WAGE:,} - may be incorrect unit or data error. "
                f"Examples: {example_str}"
            )
        else:
            warnings.append(
                f"{extremely_low_count} records ({pct:.1f}%) have wages < ${MIN_REASONABLE_WAGE:,} - may be incorrect unit or data error. "
                f"Examples: {example_str}"
            )

    # Note: Unrealistic hourly rates are now caught by the unified wage correction logic
    # during import, so we don't need a separate check here


def _check_null_rates(
    records: models.QuerySet, model_class, record_count: int, warnings: list[str]
) -> dict:
    """Check for high null rates in important fields."""
    null_rates = {}
    fields_to_check = ["wage_annual", "worksite_state", "soc_code"]

    if hasattr(model_class, "employer_name"):
        fields_to_check.append("employer_name")

    for field in fields_to_check:
        if hasattr(model_class, field):
            if field == "worksite_state":
                non_null_count = (
                    records.filter(**{f"{field}__isnull": False})
                    .exclude(**{field: ""})
                    .count()
                )
            else:
                non_null_count = records.filter(**{f"{field}__isnull": False}).count()

            null_pct = (
                (record_count - non_null_count) / record_count * 100
                if record_count > 0
                else 0
            )
            null_rates[field] = null_pct

            if null_pct > 50:
                warnings.append(f"High null rate for {field}: {null_pct:.1f}%")

    return null_rates


def _check_fiscal_year_distribution(
    records: models.QuerySet, warnings: list[str]
) -> list:
    """Check fiscal year distribution in records."""
    fiscal_years = records.values_list("fiscal_year", flat=True).distinct()
    fiscal_years_list = list(fiscal_years)

    if len(fiscal_years_list) == 0:
        warnings.append("No fiscal years found in records")
    elif len(fiscal_years_list) > 5:
        warnings.append(
            f"Unusual number of fiscal years in single file: {len(fiscal_years_list)}"
        )

    return fiscal_years_list


def _validate_state_codes(
    records: models.QuerySet, model_class, warnings: list[str]
) -> None:
    """Validate state codes if worksite_state field exists."""
    if not hasattr(model_class, "worksite_state"):
        return

    invalid_states = (
        records.filter(worksite_state__isnull=False)
        .exclude(worksite_state__in=VALID_STATES)
        .exclude(worksite_state="")
        .count()
    )

    if invalid_states > 0:
        warnings.append(f"{invalid_states} records have invalid state codes")


def validate_salary_records_post_ingest(
    run: IngestRun,
    visa_program: VisaProgram,
    program_name: str,
    model_class=SalaryRecord,
) -> ValidationResult:
    """
    Shared validation logic for salary record plugins (PERM, H-1B LCA, Worksite).

    Args:
        run: IngestRun instance
        visa_program: VisaProgram enum value
        program_name: Human-readable program name (e.g., "PERM", "H-1B LCA")
        model_class: Model class to validate (SalaryRecord or WorksiteRecord)

    Returns:
        ValidationResult with errors and warnings
    """
    errors = []
    warnings = []
    details = {}

    records, source_file = _get_records_for_run(run, visa_program, model_class)
    record_count = records.count()

    details["records_created"] = record_count
    details["run_records_created"] = run.records_created
    details["source_file"] = source_file

    if record_count == 0:
        errors.append(
            f"No {program_name} records created from source file '{source_file}' - expected data but got none"
        )
        return ValidationResult(
            passed=False, errors=errors, warnings=warnings, details=details
        )

    _validate_required_fields(records, model_class, errors)
    _validate_wage_ranges(records, warnings)
    details["null_rates"] = _check_null_rates(
        records, model_class, record_count, warnings
    )
    details["fiscal_years"] = _check_fiscal_year_distribution(records, warnings)
    _validate_state_codes(records, model_class, warnings)

    return ValidationResult(
        passed=len(errors) == 0, errors=errors, warnings=warnings, details=details
    )
