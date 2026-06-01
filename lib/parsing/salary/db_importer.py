"""Salary data import library - reusable functions for importing DOL CSV/Excel data"""

import csv
import logging
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction

from lib.parsing.salary.wage_unit_correction import (
    calculate_annual_wage,
    correct_wage_unit,
    validate_wage_annual,
)
from lib.utils.data_source_utils import (
    get_fiscal_year_from_filename,
)
from lib.utils.excel_utils import read_excel_streaming
from lib.utils.location_utils import normalize_state_code
from models.enums.visa_program import CaseStatus, VisaProgram, WageUnit
from models.salary import Employer, SalaryRecord

logger = logging.getLogger(__name__)

# DB precision limit for wage fields (max_digits=12, decimal_places=2 => abs(value) < 1e10)
MAX_DB_WAGE_ABS = Decimal("10000000000")


# Column mappings for different DOL file formats
LCA_COLUMN_MAPPINGS = {
    "case_number": ["CASE_NUMBER", "LCA_CASE_NUMBER"],
    "case_status": ["CASE_STATUS", "STATUS"],
    "employer_name": [
        "EMPLOYER_NAME",
        "EMPLOYER_BUSINESS_NAME",
        "LCA_CASE_EMPLOYER_NAME",
    ],
    "employer_city": ["EMPLOYER_CITY", "LCA_CASE_EMPLOYER_CITY"],
    "employer_state": ["EMPLOYER_STATE", "LCA_CASE_EMPLOYER_STATE"],
    "job_title": ["JOB_TITLE", "LCA_CASE_JOB_TITLE"],
    "soc_code": ["SOC_CODE", "LCA_CASE_SOC_CODE"],
    "soc_title": ["SOC_TITLE", "LCA_CASE_SOC_NAME"],
    "worksite_city": ["WORKSITE_CITY", "LCA_CASE_WORKLOC1_CITY", "WORK_CITY"],
    "worksite_state": ["WORKSITE_STATE", "LCA_CASE_WORKLOC1_STATE", "WORK_STATE"],
    "wage_from": [
        "WAGE_RATE_OF_PAY_FROM",
        "LCA_CASE_WAGE_RATE_FROM",
        "WAGE_RATE_OF_PAY_FROM_1",
        "WAGE_RATE_OF_PAY",  # Some LCA files use singular column with ranges like "20000 -"
    ],
    "wage_to": [
        "WAGE_RATE_OF_PAY_TO",
        "LCA_CASE_WAGE_RATE_TO",
        "WAGE_RATE_OF_PAY_TO_1",
        # Note: WAGE_RATE_OF_PAY (singular) may contain ranges - handled in _parse_wage_info
    ],
    "wage_unit": ["WAGE_UNIT_OF_PAY", "LCA_CASE_WAGE_RATE_UNIT", "WAGE_UNIT_OF_PAY_1"],
    "prevailing_wage": ["PREVAILING_WAGE", "PW_WAGE_LEVEL", "PREVAILING_WAGE_1"],
    "prevailing_wage_unit": ["PW_UNIT_OF_PAY", "PW_UNIT_OF_PAY_1"],
    "case_submitted": [
        "RECEIVED_DATE",
        "LCA_CASE_SUBMIT",
        "CASE_SUBMITTED",
        "SUBMITTED_DATE",
    ],
    "decision_date": [
        "DECISION_DATE",
        "LCA_CASE_CERTIFICATION",
        "DOL_DECISION_DATE",
        "Decision_Date",
    ],
    "employment_start": [
        "BEGIN_DATE",
        "LCA_CASE_EMPLOYMENT_START_DATE",
        "EMPLOYMENT_START_DATE",
    ],
    "employment_end": [
        "END_DATE",
        "LCA_CASE_EMPLOYMENT_END_DATE",
        "EMPLOYMENT_END_DATE",
    ],
}

PERM_COLUMN_MAPPINGS = {
    # FY2026+ revised PERM (ETA-9089) disclosure files renamed columns to the
    # EMP_*/PWD_*/JOB_OPP_* scheme; older files use EMPLOYER_*/PW_*. Keep both.
    "case_number": ["CASE_NUMBER", "CASE_NO"],
    "case_status": ["CASE_STATUS", "Case_Status"],
    "employer_name": [
        "EMPLOYER_NAME",
        "Employer_Name",
        "EMPLOYER_BUSINESS_NAME",
        "EMP_BUSINESS_NAME",
    ],
    "employer_city": ["EMPLOYER_CITY", "Employer_City", "EMP_CITY"],
    "employer_state": ["EMPLOYER_STATE", "Employer_State", "EMP_STATE"],
    "job_title": [
        "JOB_TITLE",
        "PW_JOB_TITLE_9089",
        "PW_Job_Title_9089",
        "PW_JOB_TITLE",
        "JOB_INFO_JOB_TITLE",
    ],
    "soc_code": ["PW_SOC_CODE", "PW_SOC_Code", "SOC_CODE", "PWD_SOC_CODE"],
    "soc_title": ["PW_SOC_TITLE", "SOC_TITLE", "PWD_SOC_TITLE"],
    "worksite_city": [
        "WORKSITE_CITY",
        "EMPLOYER_CITY",
        "JOB_INFO_WORK_CITY",
        "Job_Info_Work_City",
    ],
    "worksite_state": [
        "WORKSITE_STATE",
        "EMPLOYER_STATE",
        "JOB_INFO_WORK_STATE",
        "Job_Info_Work_State",
    ],
    # PERM files use _9089 suffix for newer form versions (Form 9089)
    # Different PERM files use slightly different column names, so we check all variants
    # Older files (FY2011-2014) use JOB_OPP_WAGE_* format instead of WAGE_OFFER_*
    "wage_from": [
        "WAGE_OFFER_FROM_9089",  # Form 9089 variant (found in PERM_Disclosure_Data_FY16.xlsx, PERM_FY2008.xlsx)
        "WAGE_OFFERED_FROM_9089",  # Form 9089 variant (found in PERM_FY2019.xlsx)
        "JOB_OPP_WAGE_FROM",  # Older format (found in PERM_FY2011-FY2014 files)
        "WAGE_OFFER_FROM",
        "OFFERED_WAGE_FROM",
        "WAGE_OFFERED_FROM",
    ],
    "wage_to": [
        "WAGE_OFFER_TO_9089",  # Form 9089 variant
        "WAGE_OFFERED_TO_9089",  # Form 9089 variant
        "JOB_OPP_WAGE_TO",  # Older format (found in PERM_FY2011-FY2014 files)
        "WAGE_OFFER_TO",
        "OFFERED_WAGE_TO",
        "WAGE_OFFERED_TO",
    ],
    "wage_unit": [
        "WAGE_OFFER_UNIT_OF_PAY_9089",  # Form 9089 variant (found in both FY16 and FY2019)
        "JOB_OPP_WAGE_PER",  # Older format (found in PERM_FY2011-FY2014 files) - note: "PER" not "UNIT"
        "WAGE_OFFER_UNIT",
        "WAGE_OFFERED_UNIT_OF_PAY",
        "WAGE_UNIT_OF_PAY",
    ],
    "prevailing_wage": [
        "PW_AMOUNT_9089",
        "PW_AMOUNT",
        "PREVAILING_WAGE",
        "PW_WAGE_1",
        "PW_WAGE",
    ],
    "prevailing_wage_unit": ["PW_UNIT_OF_PAY_9089", "PW_UNIT_OF_PAY", "PW_WAGE_UNIT_1"],
    "case_submitted": ["CASE_RECEIVED_DATE", "RECEIVED_DATE", "Received_Date"],
    "decision_date": [
        "DECISION_DATE",
        "Decision_Date",
        "Certified_Date",
        "Denied_Date",
    ],
    "employment_start": ["EMPLOYMENT_START_DATE", "BEGIN_DATE"],
    "employment_end": ["EMPLOYMENT_END_DATE", "END_DATE"],
}


def get_column_value(row: dict, mappings: list[str]) -> str | None:
    """Get value from row using multiple possible column names"""
    for col_name in mappings:
        if col_name in row and row[col_name] is not None:
            value = row[col_name]
            # Convert to string if not already (handles Excel int/float values)
            if not isinstance(value, str):
                value = str(value)
            # Strip whitespace
            value = value.strip()
            # Return None if empty after stripping
            if not value:
                continue
            return value
    return None


def parse_date(date_str: str | None) -> datetime | None:
    """Parse date from various DOL formats"""
    if not date_str:
        return None

    # Ensure it's a string (handles non-string values from Excel)
    if not isinstance(date_str, str):
        date_str = str(date_str)

    date_str = date_str.strip()
    if not date_str:
        return None

    # Try common formats (DOL Excel often exports as 'YYYY-MM-DD HH:MM:SS')
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y%m%d",
        "%d-%b-%Y",
        "%d-%b-%y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None


def parse_decimal(value: str | None) -> Decimal | None:
    """Parse decimal value, handling currency formatting and null sentinels."""
    if not value:
        return None

    cleaned = value.strip()
    # Treat PostgreSQL COPY null sentinel and common null representations as None
    if cleaned in ("\\N", "\\n", "NULL", "null", ""):
        return None

    # Remove currency symbols, commas, spaces
    cleaned = cleaned.replace("$", "").replace(",", "").replace(" ", "")

    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _read_data_file(filepath: Path):
    """
    Read CSV or Excel file and return as generator (streaming, memory efficient).

    Args:
        filepath: Path to file

    Returns:
        For Excel files: tuple of (generator, timing_dict) where timing_dict will be
        populated when generator is consumed.
        For CSV files: generator that yields dictionaries with column names as keys.
    """
    read_start = time.time()

    if filepath.suffix.lower() in [".xlsx", ".xls"]:
        # Read Excel file using openpyxl streaming for memory efficiency
        logger.info(f"Reading Excel file: {filepath.name}")
        logger.debug("Using openpyxl streaming for Excel file")

        # Timing storage (will be populated when generator runs)
        timing_info = {"df_read_time": 0.0, "dict_convert_time": 0.0}

        def excel_stream_generator():
            # Measure actual read time (happens when generator is first consumed)
            read_start_time = time.time()

            # Use openpyxl streaming - true buffered reading, no upfront load
            # read_excel_streaming already converts to string and handles None
            for record in read_excel_streaming(
                filepath, read_only=True, data_only=True
            ):
                # Strip values for consistency with pandas behavior
                # (stripping empty strings is a no-op, so safe to do for all)
                for key, val in record.items():
                    record[key] = val.strip() if val else val

                # Track timing on first yield (after first row is read)
                if timing_info["df_read_time"] == 0.0:
                    timing_info["df_read_time"] = time.time() - read_start_time

                yield record

            # Track total conversion time
            timing_info["dict_convert_time"] = (
                time.time() - read_start_time - timing_info["df_read_time"]
            )

        return excel_stream_generator(), timing_info
    else:
        # Read CSV file - stream row-by-row (memory efficient)
        logger.info(f"Reading CSV file: {filepath.name}")

        def csv_row_generator():
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                yield from reader
            read_time = time.time() - read_start
            logger.debug(f"File read timing - Total: {read_time:.2f}s (streaming)")

        return csv_row_generator()


def _get_existing_cases(source_file: str) -> set[str]:
    """Get set of existing case numbers for the source file"""
    return set(
        SalaryRecord.objects.filter(source_file=source_file).values_list(
            "case_number", flat=True
        )
    )


def _get_or_create_employer(
    employer_name: str,
    employer_city: str,
    employer_state: str,
    employers_cache: dict,
    assign_to_cluster: bool = True,
) -> Employer:
    """
    Get or create employer, using cache to avoid repeated DB queries

    If assign_to_cluster is True, also assigns employer to appropriate cluster.
    """
    employer_key = (
        Employer.normalize_name(employer_name),
        employer_city,
        employer_state,
    )

    if employer_key not in employers_cache:
        employer, _ = Employer.objects.get_or_create(
            name_normalized=employer_key[0],
            city=employer_key[1],
            state=employer_key[2],
            defaults={"name": employer_name},
        )
        employers_cache[employer_key] = employer

        # Assign to cluster if enabled
        if assign_to_cluster:
            from lib.business.salary.employer_clustering import assign_to_cluster

            assign_to_cluster(employer)

    return employers_cache[employer_key]


# Wage unit correction and annual wage calculation are now in wage_unit_correction.py
# Imported at the top of the file for use in _parse_wage_info


def _parse_wage_range(wage_str: str | None) -> tuple[Decimal | None, Decimal | None]:
    """
    Parse wage range from string like "20000 -" or "20000 - 30000" or "20000-30000".

    Returns:
        Tuple of (wage_from, wage_to)
    """
    if not wage_str:
        return None, None

    wage_str = str(wage_str).strip()
    if not wage_str or wage_str == "-":
        return None, None

    # Handle range formats: "20000 -", "20000 - 30000", "20000-30000", "20000 to 30000"
    import re

    # Try to match range patterns
    # Pattern 1: "20000 - 30000" or "20000-30000"
    range_match = re.match(r"^([\d,]+\.?\d*)\s*[-–—]\s*([\d,]+\.?\d*)$", wage_str)
    if range_match:
        from_val = parse_decimal(range_match.group(1))
        to_val = parse_decimal(range_match.group(2))
        return from_val, to_val

    # Pattern 2: "20000 -" or "20000-" (only from value)
    single_with_dash = re.match(r"^([\d,]+\.?\d*)\s*[-–—]\s*$", wage_str)
    if single_with_dash:
        from_val = parse_decimal(single_with_dash.group(1))
        return from_val, None

    # Pattern 3: "20000 to 30000"
    to_match = re.match(
        r"^([\d,]+\.?\d*)\s+to\s+([\d,]+\.?\d*)$", wage_str, re.IGNORECASE
    )
    if to_match:
        from_val = parse_decimal(to_match.group(1))
        to_val = parse_decimal(to_match.group(2))
        return from_val, to_val

    # Pattern 4: Single value (no range indicator)
    single_val = parse_decimal(wage_str)
    if single_val is not None:
        return single_val, None

    return None, None


def _is_db_safe_wage(value: Decimal | None) -> bool:
    """Check if a wage value fits in database precision limits."""
    return value is None or abs(value) < MAX_DB_WAGE_ABS


def _sanitize_wage_values(
    row_num: int,
    wage_from: Decimal | None,
    wage_to: Decimal | None,
    wage_unit: WageUnit | None,
    wage_annual: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, WageUnit | None, Decimal | None, bool]:
    """Ensure wage values won't overflow database precision."""
    if wage_from is not None and not isinstance(wage_from, Decimal):
        logger.error(
            "Row %s: wage_from has non-decimal value %r; skipping record.",
            row_num,
            wage_from,
        )
        return None, None, wage_unit, None, True

    if wage_to is not None and not isinstance(wage_to, Decimal):
        logger.error(
            "Row %s: wage_to has non-decimal value %r; clearing wage_to.",
            row_num,
            wage_to,
        )
        wage_to = None

    if wage_annual is not None and not isinstance(wage_annual, Decimal):
        logger.error(
            "Row %s: wage_annual has non-decimal value %r; clearing wage_annual.",
            row_num,
            wage_annual,
        )
        wage_annual = None

    if not _is_db_safe_wage(wage_from) or not _is_db_safe_wage(wage_to):
        logger.error(
            "Row %s: wage value exceeds DB precision; skipping record.",
            row_num,
        )
        return None, None, wage_unit, None, True

    if not _is_db_safe_wage(wage_annual):
        logger.error(
            "Row %s: annual wage exceeds DB precision; clearing wage_annual.",
            row_num,
        )
        wage_annual = None

    return wage_from, wage_to, wage_unit, wage_annual, False


def _parse_wage_info(
    row: dict, column_mappings: dict, row_num: int
) -> tuple[Decimal | None, Decimal | None, WageUnit | None, Decimal | None]:
    """Parse wage information from row, correcting unit if needed"""
    # First try standard FROM/TO columns
    wage_from = parse_decimal(get_column_value(row, column_mappings["wage_from"]))
    wage_to = parse_decimal(get_column_value(row, column_mappings["wage_to"]))

    # If wage_from is None, check for WAGE_RATE_OF_PAY (singular) which may contain ranges
    if wage_from is None:
        wage_rate_singular = get_column_value(row, ["WAGE_RATE_OF_PAY"])
        if wage_rate_singular:
            # Parse range from singular column
            parsed_from, parsed_to = _parse_wage_range(wage_rate_singular)
            if parsed_from is not None:
                wage_from = parsed_from
                if parsed_to is not None and wage_to is None:
                    wage_to = parsed_to

    wage_unit_raw = get_column_value(row, column_mappings["wage_unit"])
    wage_unit = WageUnit.from_dol_value(wage_unit_raw) or WageUnit.YEAR

    # Correct wage unit if value suggests it's actually annual (using shared logic)
    wage_unit = correct_wage_unit(wage_from, wage_unit, row_num=row_num)

    # Calculate annual wage (using shared logic)
    wage_annual = calculate_annual_wage(wage_from, wage_unit)

    # Sanitize wage values (keep enum, don't convert to string yet)
    wage_from, wage_to, wage_unit, wage_annual, should_skip = _sanitize_wage_values(
        row_num,
        wage_from,
        wage_to,
        wage_unit,
        wage_annual,
    )

    if should_skip:
        return None, None, None, None

    return wage_from, wage_to, wage_unit, wage_annual


def _parse_case_info(
    row: dict, column_mappings: dict
) -> tuple[
    CaseStatus | None,
    datetime | None,
    datetime | None,
    datetime | None,
    datetime | None,
    Decimal | None,
    WageUnit | None,
]:
    """Parse case status, dates, and prevailing wage from row"""
    case_status_raw = get_column_value(row, column_mappings["case_status"])
    case_status = CaseStatus.from_dol_value(
        case_status_raw
    )  # Returns None if not found, which is fine for nullable field

    case_submitted = parse_date(
        get_column_value(row, column_mappings["case_submitted"])
    )
    decision_date = parse_date(get_column_value(row, column_mappings["decision_date"]))
    employment_start = parse_date(
        get_column_value(row, column_mappings["employment_start"])
    )
    employment_end = parse_date(
        get_column_value(row, column_mappings["employment_end"])
    )

    prevailing_wage = parse_decimal(
        get_column_value(row, column_mappings["prevailing_wage"])
    )
    if not _is_db_safe_wage(prevailing_wage):
        logger.error("Prevailing wage exceeds DB precision; clearing value.")
        prevailing_wage = None
    pw_unit_raw = get_column_value(row, column_mappings["prevailing_wage_unit"])
    prevailing_wage_unit = WageUnit.from_dol_value(pw_unit_raw) if pw_unit_raw else None

    return (
        case_status,
        case_submitted,
        decision_date,
        employment_start,
        employment_end,
        prevailing_wage,
        prevailing_wage_unit,
    )


def _create_salary_record(
    row: dict,
    column_mappings: dict,
    case_number: str,
    visa_program: VisaProgram,
    employer: Employer,
    employer_name: str,
    job_title: str,
    wage_from: Decimal | None,
    wage_to: Decimal | None,
    wage_unit: WageUnit | None,
    wage_annual: Decimal | None,
    case_status: CaseStatus | None,
    case_submitted: datetime | None,
    decision_date: datetime | None,
    employment_start: datetime | None,
    employment_end: datetime | None,
    prevailing_wage: Decimal | None,
    prevailing_wage_unit: WageUnit | None,
    fiscal_year: int,
    source_file: str,
) -> SalaryRecord:
    """Create a SalaryRecord object from parsed data"""
    # Final validation: ensure wage fields are None or numeric
    if wage_from is not None and not isinstance(wage_from, (Decimal, int, float)):
        logger.error(
            "Final validation failed for case %s: wage_from=%r (type: %s). "
            "Clearing to NULL. wage_to=%r, wage_unit=%r, wage_annual=%r",
            case_number,
            wage_from,
            type(wage_from).__name__,
            wage_to,
            wage_unit,
            wage_annual,
        )
        wage_from = None

    if wage_to is not None and not isinstance(wage_to, (Decimal, int, float)):
        logger.error(
            "Final validation failed for case %s: wage_to=%r (type: %s). "
            "Clearing to NULL. wage_from=%r, wage_unit=%r, wage_annual=%r",
            case_number,
            wage_to,
            type(wage_to).__name__,
            wage_from,
            wage_unit,
            wage_annual,
        )
        wage_to = None

    if wage_annual is not None and not isinstance(wage_annual, (Decimal, int, float)):
        logger.error(
            "Final validation failed for case %s: wage_annual=%r (type: %s). "
            "Clearing to NULL. wage_from=%r, wage_to=%r, wage_unit=%r",
            case_number,
            wage_annual,
            type(wage_annual).__name__,
            wage_from,
            wage_to,
            wage_unit,
        )
        wage_annual = None

    # Determine if this is a worksite record for efficient filtering
    # Worksite records are identified by:
    # 1. Filename contains 'worksite' or 'worksites' (worksite files)
    # 2. Case number starts with 'I-200' (worksite case prefix, per DOL format)
    is_worksite = (
        source_file.startswith("LCA_Worksites")
        or "_Worksites_" in source_file
        or "worksite" in source_file.lower()
        or (case_number and case_number.startswith("I-200"))
    )

    return SalaryRecord(
        case_number=case_number,
        visa_program=visa_program,
        case_status=case_status,
        employer=employer,
        employer_name=employer_name,
        job_title=job_title,
        soc_code=get_column_value(row, column_mappings["soc_code"]) or "",
        soc_title=get_column_value(row, column_mappings["soc_title"]) or "",
        worksite_city=get_column_value(row, column_mappings["worksite_city"]) or "",
        worksite_state=normalize_state_code(
            get_column_value(row, column_mappings["worksite_state"]) or ""
        ),
        wage_from=wage_from,  # Allow None - records without wage data should be skipped
        wage_to=wage_to,
        wage_unit=wage_unit,
        wage_annual=wage_annual,
        prevailing_wage=prevailing_wage,
        prevailing_wage_unit=prevailing_wage_unit,
        case_submitted=case_submitted,
        decision_date=decision_date,
        employment_start=employment_start,
        employment_end=employment_end,
        fiscal_year=fiscal_year,
        source_file=source_file,
        is_worksite=is_worksite,
    )


class RowProcessResult:
    """Result of processing a row - distinguishes between success, skipped, error, and rejected"""

    def __init__(
        self,
        record: SalaryRecord | None = None,
        skipped: bool = False,
        error: bool = False,
        rejected: bool = False,
        rejection_reason: str | None = None,
    ):
        self.record = record
        self.skipped = skipped
        self.error = error
        self.rejected = rejected
        self.rejection_reason = rejection_reason

    @classmethod
    def success(cls, record: SalaryRecord) -> "RowProcessResult":
        return cls(record=record)

    @classmethod
    def skipped(cls) -> "RowProcessResult":
        return cls(skipped=True)

    @classmethod
    def error(cls) -> "RowProcessResult":
        return cls(error=True)

    @classmethod
    def rejected(cls, reason: str) -> "RowProcessResult":
        return cls(rejected=True, rejection_reason=reason)


def _process_row(
    row: dict,
    row_num: int,
    column_mappings: dict,
    visa_program: VisaProgram,
    fiscal_year: int,
    source_file: str,
    existing_cases: set[str],
    skip_existing: bool,
    employers_cache: dict,
) -> RowProcessResult:
    """Process a single row and return RowProcessResult indicating success, skipped, or error"""
    try:
        case_number = get_column_value(row, column_mappings["case_number"])
        if not case_number:
            return RowProcessResult.error()

        if skip_existing and case_number in existing_cases:
            return RowProcessResult.skipped()

        # Parse employer info
        employer_name_raw = get_column_value(row, column_mappings["employer_name"])
        if (
            not employer_name_raw
            or employer_name_raw.strip() == ""
            or employer_name_raw.strip().lower() == "unknown"
        ):
            return RowProcessResult.rejected("Missing employer name - record skipped")
        employer_name = employer_name_raw.strip()
        employer_city = get_column_value(row, column_mappings["employer_city"]) or ""
        employer_state = normalize_state_code(
            get_column_value(row, column_mappings["employer_state"]) or ""
        )

        employer = _get_or_create_employer(
            employer_name, employer_city, employer_state, employers_cache
        )

        job_title_raw = get_column_value(row, column_mappings["job_title"])
        if (
            not job_title_raw
            or job_title_raw.strip() == ""
            or job_title_raw.strip().lower() == "unknown"
        ):
            return RowProcessResult.rejected("Missing job title - record skipped")
        job_title = job_title_raw.strip()

        # Parse wage info
        wage_from, wage_to, wage_unit, wage_annual = _parse_wage_info(
            row, column_mappings, row_num
        )

        # Skip records without wage data (wage_from is None/empty)
        # We don't want entries without wages - drop them entirely
        if wage_from is None:
            return RowProcessResult.rejected("Missing wage data - record skipped")

        # Validate annual wage
        is_valid, validation_error = validate_wage_annual(wage_annual, row_num)
        if not is_valid:
            return RowProcessResult.rejected(validation_error or "Invalid wage")

        # Parse case info
        (
            case_status,
            case_submitted,
            decision_date,
            employment_start,
            employment_end,
            prevailing_wage,
            prevailing_wage_unit,
        ) = _parse_case_info(row, column_mappings)

        # Create record
        record = _create_salary_record(
            row,
            column_mappings,
            case_number,
            visa_program,
            employer,
            employer_name,
            job_title,
            wage_from,
            wage_to,
            wage_unit,
            wage_annual,
            case_status,
            case_submitted,
            decision_date,
            employment_start,
            employment_end,
            prevailing_wage,
            prevailing_wage_unit,
            fiscal_year,
            source_file,
        )
        return RowProcessResult.success(record)
    except Exception as e:
        logger.warning(f"Error on row {row_num}: {e}")
        return RowProcessResult.error()


def _batch_insert_records(
    records: list[SalaryRecord], imported: int, batch_size: int, batch_num: int = 0
) -> tuple[int, float, float]:
    """
    Insert records in batch and return updated imported count and timing info.

    Returns:
        (imported_count, bulk_time, commit_time)
    """
    if not records:
        return imported, 0.0, 0.0

    bulk_start = time.time()
    with transaction.atomic():
        SalaryRecord.objects.bulk_create(records, ignore_conflicts=True)
    commit_start = time.time()
    # Transaction commit happens here (index updates occur during commit)
    bulk_time = commit_start - bulk_start
    commit_time = time.time() - commit_start
    total_insert_time = bulk_time + commit_time

    imported += len(records)
    if imported % (batch_size * 10) == 0:  # Log every 10 batches
        logger.info(
            f"  Imported {imported} records... (bulk: {bulk_time:.3f}s, commit: {commit_time:.3f}s, total: {total_insert_time:.3f}s)"
        )

    # Log slow batches to identify degradation
    if total_insert_time > 1.0:  # Slow batch threshold
        logger.warning(
            f"  Slow batch {batch_num} at {imported:,} records: bulk={bulk_time:.3f}s, commit={commit_time:.3f}s"
        )

    return imported, bulk_time, commit_time


def import_csv_file(
    filepath: Path,
    visa_program: VisaProgram,
    batch_size: int = 1000,
    skip_existing: bool = True,
) -> tuple[int, int, int]:
    """
    Import a single CSV or Excel file into the database.

    Supports both .csv and .xlsx/.xls formats.

    Returns: (imported_count, skipped_count, error_count)
    """
    total_start = time.time()

    if visa_program == VisaProgram.PERM:
        column_mappings = PERM_COLUMN_MAPPINGS
    else:
        column_mappings = LCA_COLUMN_MAPPINGS

    fiscal_year = get_fiscal_year_from_filename(filepath.name)
    # Default to current year if fiscal year cannot be extracted from filename
    if fiscal_year is None:
        fiscal_year = datetime.now().year
        logger.warning(
            f"Could not extract fiscal year from filename '{filepath.name}', using current year: {fiscal_year}"
        )
    source_file = filepath.name

    imported = 0
    skipped = 0
    errors = 0
    rejected = 0

    # Get existing case numbers if skipping duplicates
    existing_cases_start = time.time()
    existing_cases = _get_existing_cases(source_file) if skip_existing else set()
    existing_cases_time = time.time() - existing_cases_start

    records_to_create = []
    employers_cache = {}

    # Read data file (CSV or Excel) - always returns generator
    # For Excel files, returns (generator, timing_info)
    read_start = time.time()
    excel_timing_info = None
    try:
        result = _read_data_file(filepath)
        # Handle Excel files that return (generator, timing_info)
        if isinstance(result, tuple) and len(result) == 2:
            rows, excel_timing_info = result
        else:
            rows = result
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        return (0, 0, 1)

    # For Excel files, read_time is just generator creation (fast)
    # Actual read time is tracked in excel_timing_info
    read_time = time.time() - read_start

    # Count rows and process (works with both list and generator)
    row_count = 0
    process_start = time.time()
    db_insert_time = 0.0
    db_commit_time = 0.0

    for row_num, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
        row_count += 1
        result = _process_row(
            row,
            row_num,
            column_mappings,
            visa_program,
            fiscal_year,
            source_file,
            existing_cases,
            skip_existing,
            employers_cache,
        )

        if result.skipped:
            skipped += 1
            continue

        if result.error:
            errors += 1
            continue

        if result.rejected:
            rejected += 1
            if result.rejection_reason:
                logger.debug(f"Row {row_num}: Rejected - {result.rejection_reason}")
            continue

        if result.record:
            records_to_create.append(result.record)

        # Batch insert when threshold reached
        if len(records_to_create) >= batch_size:
            batch_num = (imported // batch_size) + 1
            imported, bulk_time, commit_time = _batch_insert_records(
                records_to_create, imported, batch_size, batch_num
            )
            db_insert_time += bulk_time
            db_commit_time += commit_time
            records_to_create = []

    process_time = time.time() - process_start

    # Insert remaining records
    if records_to_create:
        batch_num = (imported // batch_size) + 1
        imported, bulk_time, commit_time = _batch_insert_records(
            records_to_create, imported, batch_size, batch_num
        )
        db_insert_time += bulk_time
        db_commit_time += commit_time

    total_time = time.time() - total_start

    # Extract Excel-specific timing if available
    excel_df_read_time = 0.0
    excel_dict_convert_time = 0.0
    if excel_timing_info:
        excel_df_read_time = excel_timing_info.get("df_read_time", 0.0)
        excel_dict_convert_time = excel_timing_info.get("dict_convert_time", 0.0)
        # Adjust process_time to exclude dict conversion (it's part of file reading)
        process_time -= excel_dict_convert_time

    # Log performance breakdown
    logger.info(f"Performance breakdown for {filepath.name}:")
    logger.info(f"  Total time: {total_time:.2f}s")

    if excel_timing_info:
        # Detailed breakdown for Excel files
        logger.info(
            f"  Excel DataFrame read: {excel_df_read_time:.2f}s ({excel_df_read_time / total_time * 100:.1f}%)"
        )
        logger.info(
            f"  Dict conversion: {excel_dict_convert_time:.2f}s ({excel_dict_convert_time / total_time * 100:.1f}%)"
        )
        logger.info(
            f"  Row processing: {process_time:.2f}s ({process_time / total_time * 100:.1f}%)"
        )
    else:
        # Standard breakdown for CSV files
        logger.info(
            f"  File reading: {read_time:.2f}s ({read_time / total_time * 100:.1f}%)"
        )
        logger.info(
            f"  Row processing: {process_time:.2f}s ({process_time / total_time * 100:.1f}%)"
        )

    logger.info(
        f"  Database inserts: {db_insert_time:.2f}s ({db_insert_time / total_time * 100:.1f}%)"
    )
    if db_commit_time > 0:
        logger.info(
            f"  Transaction commits: {db_commit_time:.2f}s ({db_commit_time / total_time * 100:.1f}%)"
        )
    logger.info(
        f"  Existing cases lookup: {existing_cases_time:.2f}s ({existing_cases_time / total_time * 100:.1f}%)"
    )
    if row_count > 0:
        logger.info(f"  Throughput: {row_count / total_time:,.0f} rows/second")
        if imported > 0:
            logger.info(f"  Import rate: {imported / total_time:,.0f} records/second")
    logger.info("  (Streaming mode enabled - reduced memory usage)")

    return imported, skipped, errors


def update_employer_stats():
    """Update aggregated statistics for employers"""
    logger.info("Updating employer statistics...")
    from django.db.models import Avg, Count

    # Update LCA counts
    lca_counts = (
        SalaryRecord.objects.filter(
            visa_program__in=[VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3]
        )
        .values("employer_id")
        .annotate(count=Count("id"))
    )

    for item in lca_counts:
        if item["employer_id"]:
            Employer.objects.filter(id=item["employer_id"]).update(
                total_lca_count=item["count"]
            )

    # Update PERM counts
    perm_counts = (
        SalaryRecord.objects.filter(visa_program=VisaProgram.PERM)
        .values("employer_id")
        .annotate(count=Count("id"))
    )

    for item in perm_counts:
        if item["employer_id"]:
            Employer.objects.filter(id=item["employer_id"]).update(
                total_perm_count=item["count"]
            )

    # Update average salary
    avg_salaries = (
        SalaryRecord.objects.filter(wage_annual__isnull=False, wage_annual__gt=0)
        .values("employer_id")
        .annotate(avg=Avg("wage_annual"))
    )

    for item in avg_salaries:
        if item["employer_id"]:
            Employer.objects.filter(id=item["employer_id"]).update(
                avg_salary=item["avg"]
            )

    logger.info("Employer statistics updated.")
