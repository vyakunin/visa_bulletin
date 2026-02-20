#!/usr/bin/env python3
"""
Verify file discovery mechanism - ensure all files are detected correctly.

This script:
1. Lists all Excel files in data/salary/dol_data
2. Tests detection logic on each file
3. Reports which files are detected as PERM, H1B, or unknown
4. Verifies that only Appendix A files remain unknown
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.utils.excel_utils import read_excel_headers
from lib.utils.http_utils import get_workspace_dir
from scripts.salary.collect_dol_golden_test_data import detect_file_type


def main():
    workspace = get_workspace_dir()
    dol_data_dir = workspace / "data" / "salary" / "dol_data"

    if not dol_data_dir.exists():
        print(f"❌ Directory not found: {dol_data_dir}")
        sys.exit(1)

    # Find all Excel files
    excel_files = sorted(dol_data_dir.glob("*.xlsx"))
    print(f"Found {len(excel_files)} Excel files\n")

    # Test detection on each file
    perm_files = []
    h1b_files = []
    unknown_files = []
    error_files = []

    for filepath in excel_files:
        try:
            headers = read_excel_headers(filepath)
            detected = detect_file_type(headers)

            if detected == "PERM":
                perm_files.append(filepath.name)
            elif detected == "H1B":
                h1b_files.append(filepath.name)
            else:
                unknown_files.append((filepath.name, "No matching indicators"))
        except Exception as e:
            error_files.append((filepath.name, str(e)))

    # Report results
    print("=" * 80)
    print("FILE DISCOVERY RESULTS")
    print("=" * 80)
    print(f"\n✅ PERM files: {len(perm_files)}")
    print(f"✅ H1B files: {len(h1b_files)}")
    print(f"⚠️  Unknown files: {len(unknown_files)}")
    print(f"❌ Error files: {len(error_files)}")
    print(f"\n📊 Total: {len(excel_files)} files")
    print(f"📊 Detected: {len(perm_files) + len(h1b_files)} files")
    print(
        f"📊 Coverage: {(len(perm_files) + len(h1b_files)) / len(excel_files) * 100:.1f}%"
    )

    # Check if unknown files are all Appendix A
    if unknown_files:
        print("\n" + "=" * 80)
        print("UNKNOWN FILES ANALYSIS")
        print("=" * 80)
        appendix_files = []
        other_unknown = []

        for filename, reason in unknown_files:
            if "Appendix" in filename or "APPX" in filename:
                appendix_files.append((filename, reason))
            else:
                other_unknown.append((filename, reason))

        print(f"\n📁 Appendix A files (expected to be unknown): {len(appendix_files)}")
        for filename, reason in appendix_files:
            print(f"   - {filename}")

        if other_unknown:
            print(
                f"\n⚠️  Other unknown files (should be investigated): {len(other_unknown)}"
            )
            for filename, reason in other_unknown:
                print(f"   - {filename}: {reason}")
        else:
            print("\n✅ All unknown files are Appendix A files (expected)")

    if error_files:
        print("\n" + "=" * 80)
        print("ERROR FILES")
        print("=" * 80)
        for filename, error in error_files:
            print(f"   - {filename}: {error}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    expected_unknown = len(appendix_files) if unknown_files else 0
    if len(unknown_files) == expected_unknown and expected_unknown == 6:
        print("✅ PASS: Only 6 Appendix A files are unknown (as expected)")
        return 0
    else:
        print(
            f"❌ FAIL: Expected 6 unknown files (Appendix A), got {len(unknown_files)}"
        )
        if other_unknown:
            print(f"   - {len(other_unknown)} non-Appendix files are unknown")
        return 1


if __name__ == "__main__":
    sys.exit(main())
