#!/usr/bin/env python3
"""
Inspect raw source rows for records with unknown employer/job title.

Usage:
    bazel run //scripts/ingest:inspect_unknown_source_rows
    bazel run //scripts/ingest:inspect_unknown_source_rows -- --limit 5
    bazel run //scripts/ingest:inspect_unknown_source_rows -- --mode employer
    bazel run //scripts/ingest:inspect_unknown_source_rows -- --mode job
    bazel run //scripts/ingest:inspect_unknown_source_rows -- --files data/salary/dol_data/PERM_Disclosure_Data_FY2024_Q4.xlsx

Output:
    - Source file and case number for unknown records
    - Raw column values for employer/job-related fields
    - Highlights empty vs populated columns
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import django

from django_config.logging_config import setup_logging
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger


LCA_INDICATORS = [
    "LCA_CASE_NUMBER",
    "LCA_CASE_WAGE_RATE_FROM",
    "LCA_CASE_JOB_TITLE",
    "VISA_CLASS",
]
PERM_INDICATORS = [
    "WAGE_OFFER_FROM_9089",
    "WAGE_OFFERED_FROM_9089",
    "JOB_OPP_WAGE_FROM",
    "PW_JOB_TITLE_9089",
    "PW_SOC_CODE",
]

EMPLOYER_KEYWORDS = ["employer", "business", "company", "organization", "org", "corp", "inc", "llc"]
JOB_KEYWORDS = ["job", "title", "occupation", "position", "role"]

DEFAULT_SCAN_FILES = [
    "data/salary/dol_data/PERM_Disclosure_Data_FY2024_Q4.xlsx",
    "data/salary/dol_data/LCA_Disclosure_Data_FY2024_Q4.xlsx",
]


def _detect_file_type(headers: list[str]) -> str | None:
    headers_upper = [str(h).upper() for h in headers]
    if any(indicator in headers_upper for indicator in PERM_INDICATORS):
        return "PERM"
    if any(indicator in headers_upper for indicator in LCA_INDICATORS):
        return "H1B"
    return None


def _collect_unknown_records(mode: str, limit: int) -> list[dict]:
    from models.salary import SalaryRecord

    unknown_employer = SalaryRecord.objects.filter(employer_name__in=["", "Unknown"])
    unknown_job = SalaryRecord.objects.filter(job_title__in=["", "Unknown"])

    if mode == "employer":
        qs = unknown_employer
    elif mode == "job":
        qs = unknown_job
    else:
        qs = unknown_employer.union(unknown_job)

    return list(
        qs.values(
            "case_number",
            "source_file",
            "employer_name",
            "job_title",
            "fiscal_year",
        )[:limit]
    )


def _group_by_source_file(records: list[dict]) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for record in records:
        grouped[record["source_file"]].append(record)
    return grouped


def _find_row_details(
    filepath: Path,
    target_cases: set[str],
    logger: logging.Logger,
    max_matches: int,
) -> None:
    from lib.parsing.salary.db_importer import LCA_COLUMN_MAPPINGS, PERM_COLUMN_MAPPINGS, get_column_value
    from lib.utils.excel_utils import read_excel_headers, read_excel_streaming

    headers = read_excel_headers(filepath)
    file_type = _detect_file_type(headers)
    logger.info("File type detected: %s", file_type or "UNKNOWN")

    case_columns = []
    if "case_number" in LCA_COLUMN_MAPPINGS:
        case_columns.extend(LCA_COLUMN_MAPPINGS["case_number"])
    if "case_number" in PERM_COLUMN_MAPPINGS:
        case_columns.extend(PERM_COLUMN_MAPPINGS["case_number"])

    matches_found = 0
    for row in read_excel_streaming(filepath):
        case_number = get_column_value(row, case_columns)
        if not case_number or case_number not in target_cases:
            continue

        matches_found += 1
        logger.info("Matched case_number: %s", case_number)
        _log_row_inspection(row, logger)

        if matches_found >= max_matches:
            break


def _scan_file_for_missing(
    filepath: Path,
    mode: str,
    max_matches: int,
    max_rows: int,
    logger: logging.Logger,
) -> list[dict]:
    from lib.parsing.salary.db_importer import LCA_COLUMN_MAPPINGS, PERM_COLUMN_MAPPINGS, get_column_value
    from lib.utils.excel_utils import read_excel_headers, read_excel_streaming

    headers = read_excel_headers(filepath)
    file_type = _detect_file_type(headers)
    logger.info("File type detected: %s", file_type or "UNKNOWN")

    case_columns = LCA_COLUMN_MAPPINGS.get("case_number", []) + PERM_COLUMN_MAPPINGS.get("case_number", [])
    employer_columns = LCA_COLUMN_MAPPINGS.get("employer_name", []) + PERM_COLUMN_MAPPINGS.get("employer_name", [])
    job_columns = LCA_COLUMN_MAPPINGS.get("job_title", []) + PERM_COLUMN_MAPPINGS.get("job_title", [])

    matches = []
    for index, row in enumerate(read_excel_streaming(filepath), start=1):
        if index > max_rows:
            break
        case_number = get_column_value(row, case_columns)
        employer_name = get_column_value(row, employer_columns)
        job_title = get_column_value(row, job_columns)

        employer_missing = not employer_name or employer_name.strip().lower() == "unknown"
        job_missing = not job_title or job_title.strip().lower() == "unknown"

        if mode == "employer" and not employer_missing:
            continue
        if mode == "job" and not job_missing:
            continue
        if mode == "both" and not (employer_missing or job_missing):
            continue

        matches.append(
            {
                "case_number": case_number,
                "employer_name": employer_name,
                "job_title": job_title,
                "row": row,
            }
        )
        if len(matches) >= max_matches:
            break

    return matches


def _log_row_inspection(row: dict, logger: logging.Logger) -> None:
    employer_columns = _filter_columns(row, EMPLOYER_KEYWORDS)
    job_columns = _filter_columns(row, JOB_KEYWORDS)

    logger.info("  Employer-related columns:")
    _log_columns_with_values(employer_columns, row, logger)

    logger.info("  Job-related columns:")
    _log_columns_with_values(job_columns, row, logger)


def _filter_columns(row: dict, keywords: list[str]) -> list[str]:
    matches = []
    for column in row.keys():
        column_lower = str(column).lower()
        if any(keyword in column_lower for keyword in keywords):
            matches.append(column)
    return matches


def _log_columns_with_values(columns: list[str], row: dict, logger: logging.Logger) -> None:
    if not columns:
        logger.info("    (none found)")
        return
    for column in columns[:20]:
        value = row.get(column, "")
        display = value if value else "[empty]"
        logger.info("    %s: %s", column, display)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect raw rows for unknown employer/job title values",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of unknown records to inspect (default: 5)",
    )
    parser.add_argument(
        "--mode",
        choices=["employer", "job", "both"],
        default="both",
        help="Which unknowns to inspect (default: both)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Optional file paths to scan directly (bypasses DB lookup)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=50000,
        help="Max rows to scan per file when using --files (default: 50000)",
    )
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
    django.setup()
    setup_logging(debug=False)
    logger = logging.getLogger(__name__)
    ScriptLogger(__file__).log_call(
        args={
            "limit": args.limit,
            "mode": args.mode,
            "files": args.files,
            "max_rows": args.max_rows,
        },
        context="Inspecting unknown employer/job title rows",
    )

    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / "data" / "salary" / "dol_data"

    if args.files:
        filepaths = [Path(path) for path in args.files]
        for filepath in filepaths:
            if not filepath.is_absolute():
                filepath = data_dir / filepath
            if not filepath.exists():
                logger.warning("Source file not found: %s", filepath)
                continue

            logger.info("")
            logger.info("=" * 80)
            logger.info("Scanning %s", filepath.name)
            matches = _scan_file_for_missing(filepath, args.mode, args.limit, args.max_rows, logger)
            if not matches:
                logger.info("No missing fields found within scanned rows.")
                continue

            for match in matches:
                logger.info("Matched case_number: %s", match["case_number"])
                _log_row_inspection(match["row"], logger)
        return

    unknown_records = _collect_unknown_records(args.mode, args.limit)
    if not unknown_records:
        logger.info("No unknown records found. Scanning default files instead.")
        for filename in DEFAULT_SCAN_FILES:
            filepath = Path(filename)
            if not filepath.is_absolute():
                filepath = data_dir / filepath
            if not filepath.exists():
                logger.warning("Source file not found: %s", filepath)
                continue

            logger.info("")
            logger.info("=" * 80)
            logger.info("Scanning %s", filepath.name)
            matches = _scan_file_for_missing(filepath, args.mode, args.limit, args.max_rows, logger)
            if not matches:
                logger.info("No missing fields found within scanned rows.")
                continue

            for match in matches:
                logger.info("Matched case_number: %s", match["case_number"])
                _log_row_inspection(match["row"], logger)
        return

    logger.info("Found %s unknown record(s) from database.", len(unknown_records))
    for record in unknown_records:
        logger.info(
            "  case=%s source=%s employer=%s job=%s",
            record["case_number"],
            record["source_file"],
            record["employer_name"],
            record["job_title"],
        )

    grouped = _group_by_source_file(unknown_records)
    for source_file, records in grouped.items():
        if not source_file:
            logger.warning("Skipping record with empty source_file")
            continue

        filename = Path(source_file).name
        filepath = data_dir / filename
        if not filepath.exists():
            logger.warning("Source file not found: %s", source_file)
            continue

        logger.info("")
        logger.info("=" * 80)
        logger.info("Inspecting %s", filename)
        logger.info("Target cases: %s", [record["case_number"] for record in records])

        _find_row_details(filepath, {record["case_number"] for record in records}, logger, len(records))


if __name__ == "__main__":
    main()
