#!/usr/bin/env python3
"""Test detection on worksite files specifically."""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.utils.excel_utils import read_excel_headers
from lib.utils.http_utils import get_workspace_dir
from scripts.salary.collect_dol_golden_test_data import detect_file_type

def test_file(filename: str):
    """Test detection on a single file."""
    workspace = get_workspace_dir()
    filepath = workspace / 'data' / 'salary' / 'dol_data' / filename
    
    if not filepath.exists():
        print(f"{filename}: NOT FOUND")
        return
    
    try:
        headers = read_excel_headers(filepath)
        detected = detect_file_type(headers)
        
        print(f"\n{filename}:")
        print(f"  Detected as: {detected}")
        print(f"  Headers: {headers[:15]}")
        
        headers_upper = [h.upper() for h in headers]
        has_case = any('CASE_NUMBER' in h or 'CASE_NO' in h for h in headers_upper)
        has_wage = any('WAGE' in h for h in headers_upper)
        has_worksite = any('WORKSITE' in h or 'WORK_CITY' in h for h in headers_upper)
        has_employer = any('EMPLOYER' in h for h in headers_upper)
        
        print(f"  Has CASE: {has_case}, WAGE: {has_wage}, WORKSITE: {has_worksite}, EMPLOYER: {has_employer}")
        
        if detected is None:
            print(f"  ❌ Still unknown")
        else:
            print(f"  ✅ Detected correctly")
    except Exception as e:
        print(f"{filename}: ERROR - {e}")

def main():
    # Test worksite files
    test_files = [
        'LCA_FY2020_Worksites.xlsx',
        'LCA_Worksites_FY2023_Q4.xlsx',
        'LCA_Worksites_FY2024_Q4.xlsx',
    ]
    
    print("Testing worksite file detection...")
    for filename in test_files:
        test_file(filename)

if __name__ == '__main__':
    main()

