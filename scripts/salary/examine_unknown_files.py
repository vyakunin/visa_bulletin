#!/usr/bin/env python3
"""
Examine unknown file types to determine if they contain salary/worksite records.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.utils.excel_utils import read_excel_headers, read_excel_rows
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger


def examine_file(filepath: Path):
    """Examine a single file and report its characteristics."""
    print(f"\n=== {filepath.name} ===")

    try:
        # Read headers
        headers = read_excel_headers(filepath)
        print(f"Headers (first 20): {headers[:20]}")

        # Check for key indicators
        headers_upper = [str(h).upper() if h else "" for h in headers]

        has_lca = any("LCA" in h for h in headers_upper)
        has_perm = any(
            "WAGE_OFFER" in h or "JOB_OPP_WAGE" in h or "PW_JOB_TITLE" in h
            for h in headers_upper
        )
        has_employer = any("EMPLOYER" in h for h in headers_upper)
        has_worksite = any("WORKSITE" in h or "WORK_CITY" in h for h in headers_upper)
        has_wage = any("WAGE" in h for h in headers_upper)
        has_case = any("CASE" in h for h in headers_upper)
        has_salary = has_wage and has_case

        print(f"  Has LCA columns: {has_lca}")
        print(f"  Has PERM columns: {has_perm}")
        print(f"  Has employer fields: {has_employer}")
        print(f"  Has worksite fields: {has_worksite}")
        print(f"  Has wage fields: {has_wage}")
        print(f"  Has case fields: {has_case}")
        print(f"  Likely salary/worksite data: {has_salary}")

        # Get sample row
        try:
            sample_rows = read_excel_rows(
                filepath, [2, 3], read_only=True, data_only=True
            )
            if sample_rows:
                print("Sample row 2 (first 10 columns):")
                row2 = sample_rows[0]
                for i, (key, value) in enumerate(list(row2.items())[:10]):
                    print(f"    {key}: {value}")
        except Exception as e:
            print(f"  Could not read sample rows: {e}")

    except Exception as e:
        print(f"ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Examine source files and print sample rows"
    )
    parser.add_argument(
        "--files",
        nargs="*",
        help="Specific filenames to examine (default: known unknowns)",
    )
    args = parser.parse_args()

    script_logger = ScriptLogger(__file__)
    script_logger.log_call(
        args={"files": args.files}, context="Examining DOL source files for sample rows"
    )

    workspace = get_workspace_dir()
    data_dir = workspace / "data" / "salary" / "dol_data"

    # Unknown files from the log (default set)
    unknown_files = [
        "H-1B_Case_Data_FY2008.xlsx",
        "H-1B_Disclosure_Data_FY15_Q4.xlsx",
        "LCA_Disclosure_Data_FY2020_Q1.xlsx",
        "PERM_Disclosure_Data_FY2020.xlsx",
        "PERM_Disclosure_Data_FY2021.xlsx",
        "lca_361.xlsx",
        "lca_362.xlsx",
        "LCA_Appendix_A_FY2021.xlsx",
    ]
    filenames = args.files if args.files else unknown_files

    print(f"Examining {len(filenames)} file(s)...")

    for filename in filenames:
        filepath = data_dir / filename
        if filepath.exists():
            examine_file(filepath)
        else:
            print(f"\n{filename}: NOT FOUND")


if __name__ == "__main__":
    main()
