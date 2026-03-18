#!/usr/bin/env python3
"""
Inspect PERM and LCA file column headers to identify actual column names.

This script helps identify why files have missing salary data
by examining the actual column headers in source files.

Supports both PERM and LCA files (including worksite files).

Usage:
    bazel run //scripts/salary:inspect_perm_columns -- --file PERM_FY2019.xlsx
    bazel run //scripts/salary:inspect_perm_columns -- --file lca_368.xlsx
    bazel run //scripts/salary:inspect_perm_columns -- --list-files
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

from lib.utils.excel_utils import read_excel_headers, read_excel_row


# Get workspace directory (from environment or current file location)
def get_workspace_dir() -> Path:
    """Get workspace directory"""
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        return Path(workspace)
    # Fallback: assume we're in project root
    return Path(__file__).parent.parent.parent


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def list_perm_files() -> list[Path]:
    """List all PERM files in data directory"""
    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / "data" / "salary" / "dol_data"

    if not data_dir.exists():
        logger.warning(f"Data directory not found: {data_dir}")
        return []

    perm_files = []
    for pattern in ["PERM*.xlsx", "PERM*.xls", "PERM*.csv"]:
        perm_files.extend(data_dir.glob(pattern))

    return sorted(perm_files)


def list_lca_files() -> list[Path]:
    """List all LCA files in data directory"""
    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / "data" / "salary" / "dol_data"

    if not data_dir.exists():
        logger.warning(f"Data directory not found: {data_dir}")
        return []

    lca_files = []
    for pattern in [
        "lca_*.xlsx",
        "lca_*.xls",
        "LCA_*.xlsx",
        "LCA_*.xls",
        "H-1B*.xlsx",
        "H-1B*.xls",
    ]:
        lca_files.extend(data_dir.glob(pattern))

    return sorted(lca_files)


def inspect_excel_columns(filepath: Path) -> dict:
    """Inspect column headers in Excel file"""
    logger.info(f"Inspecting Excel file: {filepath.name}")

    try:
        headers = read_excel_headers(filepath)
        headers = [h.strip() for h in headers]  # Strip whitespace

        # Look for wage-related columns
        wage_related = [
            h
            for h in headers
            if any(term in h.upper() for term in ["WAGE", "SALARY", "PAY", "OFFER"])
        ]

        # Look for job title columns
        job_related = [
            h
            for h in headers
            if any(term in h.upper() for term in ["JOB", "TITLE", "OCCUPATION"])
        ]

        # Sample first data row
        sample_row = read_excel_row(filepath, row_number=2) or {}

        return {
            "filepath": str(filepath),
            "filename": filepath.name,
            "total_columns": len(headers),
            "headers": headers,
            "wage_related_columns": wage_related,
            "job_related_columns": job_related,
            "sample_row": sample_row,
        }
    except Exception as e:
        logger.error(f"Error inspecting {filepath.name}: {e}")
        return {"error": str(e)}


def inspect_csv_columns(filepath: Path) -> dict:
    """Inspect column headers in CSV file"""
    logger.info(f"Inspecting CSV file: {filepath.name}")

    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []

            # Get first data row
            sample_row = next(reader, {})

            # Look for wage-related columns
            wage_related = [
                h
                for h in headers
                if h
                and any(
                    term in h.upper() for term in ["WAGE", "SALARY", "PAY", "OFFER"]
                )
            ]

            # Look for job title columns
            job_related = [
                h
                for h in headers
                if h
                and any(term in h.upper() for term in ["JOB", "TITLE", "OCCUPATION"])
            ]

            return {
                "filepath": str(filepath),
                "filename": filepath.name,
                "total_columns": len(headers),
                "headers": list(headers) if headers else [],
                "wage_related_columns": wage_related,
                "job_related_columns": job_related,
                "sample_row": dict(sample_row) if sample_row else {},
            }
    except Exception as e:
        logger.error(f"Error inspecting {filepath.name}: {e}")
        return {"error": str(e)}


def inspect_file(filepath: Path) -> dict:
    """Inspect file columns based on file type"""
    if filepath.suffix.lower() in [".xlsx", ".xls"]:
        return inspect_excel_columns(filepath)
    elif filepath.suffix.lower() == ".csv":
        return inspect_csv_columns(filepath)
    else:
        return {"error": f"Unsupported file type: {filepath.suffix}"}


def main():
    parser = argparse.ArgumentParser(
        description="Inspect PERM and LCA file column headers to identify actual column names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Inspect PERM file:
    bazel run //scripts/salary:inspect_perm_columns -- --file PERM_FY2019.xlsx

  Inspect LCA file:
    bazel run //scripts/salary:inspect_perm_columns -- --file lca_368.xlsx

  List all PERM files:
    bazel run //scripts/salary:inspect_perm_columns -- --list-files --type perm

  List all LCA files:
    bazel run //scripts/salary:inspect_perm_columns -- --list-files --type lca
        """,
    )

    parser.add_argument(
        "--file",
        type=str,
        help="Specific file to inspect (filename only, will search in data directory). Supports both PERM and LCA files.",
    )

    parser.add_argument(
        "--list-files", action="store_true", help="List all available files"
    )

    parser.add_argument(
        "--type",
        choices=["perm", "lca", "all"],
        default="all",
        help="File type to list (default: all)",
    )

    parser.add_argument(
        "--top-missing",
        type=int,
        default=5,
        help="Inspect top N files with missing salary data (default: 5)",
    )

    args = parser.parse_args()

    # Log execution (simple logging without ScriptLogger)
    logger.info(
        f"Inspecting PERM columns: file={args.file}, list_files={args.list_files}, top_missing={args.top_missing}"
    )

    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / "data" / "salary" / "dol_data"

    if args.list_files:
        if args.type in ["perm", "all"]:
            perm_files = list_perm_files()
            print(f"\nFound {len(perm_files)} PERM files:")
            for f in perm_files:
                print(f"  {f.name}")

        if args.type in ["lca", "all"]:
            lca_files = list_lca_files()
            print(f"\nFound {len(lca_files)} LCA files:")
            for f in lca_files:
                print(f"  {f.name}")
        return

    if args.file:
        # Find file
        filepath = data_dir / args.file
        if not filepath.exists():
            # Try to find by partial name
            matching = list(data_dir.glob(f"*{args.file}*"))
            if matching:
                filepath = matching[0]
                logger.info(f"Found file: {filepath.name}")
            else:
                logger.error(f"File not found: {args.file}")
                sys.exit(1)

        result = inspect_file(filepath)

        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)

        print(f"\n{'=' * 80}")
        print(f"FILE: {result['filename']}")
        print(f"{'=' * 80}")
        print(f"Total columns: {result['total_columns']}")
        print(f"\nAll column headers ({len(result['headers'])}):")
        for i, header in enumerate(result["headers"], 1):
            print(f"  {i:3d}. {header}")

        print(f"\n{'=' * 80}")
        print("WAGE-RELATED COLUMNS:")
        print(f"{'=' * 80}")
        if result["wage_related_columns"]:
            for col in result["wage_related_columns"]:
                sample_value = result["sample_row"].get(col, "N/A")
                print(f"  {col}: '{sample_value}'")
        else:
            print("  ⚠️  NO WAGE-RELATED COLUMNS FOUND!")
            print("  This explains why salary data is missing!")

        print(f"\n{'=' * 80}")
        print("JOB TITLE-RELATED COLUMNS:")
        print(f"{'=' * 80}")
        if result["job_related_columns"]:
            for col in result["job_related_columns"]:
                sample_value = result["sample_row"].get(col, "N/A")
                print(f"  {col}: '{sample_value}'")
        else:
            print("  ⚠️  NO JOB TITLE COLUMNS FOUND!")

        # Detect file type
        is_perm = "PERM" in result["filename"].upper()
        is_lca = any(
            term in result["filename"].upper() for term in ["LCA", "H-1B", "H1B"]
        )

        print(f"\n{'=' * 80}")
        if is_perm:
            print("EXPECTED COLUMN NAMES (from PERM_COLUMN_MAPPINGS):")
            print(f"{'=' * 80}")
            print(
                "  wage_from: ['WAGE_OFFER_FROM_9089', 'WAGE_OFFERED_FROM_9089', 'JOB_OPP_WAGE_FROM']"
            )
            print(
                "  wage_to: ['WAGE_OFFER_TO_9089', 'WAGE_OFFERED_TO_9089', 'JOB_OPP_WAGE_TO']"
            )
            print(
                "  wage_unit: ['WAGE_OFFER_UNIT_OF_PAY_9089', 'JOB_OPP_WAGE_PER', 'WAGE_UNIT_OF_PAY']"
            )
            print("  job_title: ['JOB_TITLE', 'PW_JOB_TITLE_9089', 'PW_JOB_TITLE']")

            # Check if expected columns exist
            expected_wage = [
                "WAGE_OFFER_FROM_9089",
                "WAGE_OFFERED_FROM_9089",
                "JOB_OPP_WAGE_FROM",
                "WAGE_OFFER_FROM",
            ]
            found_wage = any(
                col.upper() in [h.upper() for h in result["headers"]]
                for col in expected_wage
            )
        elif is_lca:
            print("EXPECTED COLUMN NAMES (from LCA_COLUMN_MAPPINGS):")
            print(f"{'=' * 80}")
            print(
                "  wage_from: ['WAGE_RATE_OF_PAY_FROM', 'LCA_CASE_WAGE_RATE_FROM', 'WAGE_RATE_OF_PAY_FROM_1']"
            )
            print(
                "  wage_to: ['WAGE_RATE_OF_PAY_TO', 'LCA_CASE_WAGE_RATE_TO', 'WAGE_RATE_OF_PAY_TO_1']"
            )
            print(
                "  wage_unit: ['WAGE_UNIT_OF_PAY', 'LCA_CASE_WAGE_RATE_UNIT', 'WAGE_UNIT_OF_PAY_1']"
            )
            print(
                "  Note: Some LCA files use 'WAGE_RATE_OF_PAY' (singular, may contain range like '20000 -')"
            )
            print("  job_title: ['JOB_TITLE', 'LCA_CASE_JOB_TITLE']")

            # Check if expected columns exist
            expected_wage = [
                "WAGE_RATE_OF_PAY_FROM",
                "LCA_CASE_WAGE_RATE_FROM",
                "WAGE_RATE_OF_PAY_FROM_1",
                "WAGE_RATE_OF_PAY",
            ]
            found_wage = any(
                col.upper() in [h.upper() for h in result["headers"]]
                for col in expected_wage
            )
        else:
            print("EXPECTED COLUMN NAMES:")
            print(f"{'=' * 80}")
            print("  (File type unclear - check filename)")
            found_wage = False

        print(f"\n{'=' * 80}")
        print("ANALYSIS:")
        print(f"{'=' * 80}")
        if not found_wage:
            print("  ❌ Expected wage columns NOT FOUND in file!")
            print("  This is why salary data is missing!")
            print("\n  RECOMMENDATION:")
            print("  1. Check actual column names in wage_related_columns above")
            if is_perm:
                print(
                    "  2. Update PERM_COLUMN_MAPPINGS in lib/parsing/salary/db_importer.py"
                )
            elif is_lca:
                print(
                    "  2. Update LCA_COLUMN_MAPPINGS in lib/parsing/salary/db_importer.py"
                )
                print(
                    "  3. Check if WAGE_RATE_OF_PAY (singular) needs special parsing (may contain ranges)"
                )
            print("  3. Re-import affected files")
        else:
            print("  ✅ Expected wage columns found")
            print("  Issue may be in parsing logic, not column names")

            # For LCA files, check if WAGE_RATE_OF_PAY (singular) is used instead of FROM/TO
            if (
                is_lca
                and "WAGE_RATE_OF_PAY" in result["headers"]
                and "WAGE_RATE_OF_PAY_FROM" not in result["headers"]
            ):
                sample = result["sample_row"].get("WAGE_RATE_OF_PAY", "")
                print(
                    "\n  ⚠️  NOTE: File uses 'WAGE_RATE_OF_PAY' (singular) instead of FROM/TO"
                )
                print(f"  Sample value: '{sample}'")
                print("  This may contain a range (e.g., '20000 -') that needs parsing")

    else:
        # Inspect top files with missing data
        print("Inspecting top PERM files with missing salary data...")
        print("(Run with --file <filename> to inspect specific file)")

        top_files = [
            "PERM_Disclosure_Data_FY16.xlsx",
            "PERM_Disclosure_Data_FY2018_EOY.xlsx",
            "PERM_FY2019.xlsx",
            "PERM_Disclosure_Data_FY2025_Q3.xlsx",
            "PERM_Disclosure_Data_FY17.xlsx",
        ]

        for filename in top_files[: args.top_missing]:
            filepath = data_dir / filename
            if filepath.exists():
                print(f"\n{'=' * 80}")
                result = inspect_file(filepath)
                if "error" not in result:
                    print(f"File: {result['filename']}")
                    print(
                        f"Wage-related columns: {len(result['wage_related_columns'])}"
                    )
                    if result["wage_related_columns"]:
                        print(f"  Found: {', '.join(result['wage_related_columns'])}")
                    else:
                        print("  ⚠️  NO WAGE COLUMNS FOUND!")
            else:
                print(f"File not found: {filename}")

    sys.exit(0)


if __name__ == "__main__":
    main()
