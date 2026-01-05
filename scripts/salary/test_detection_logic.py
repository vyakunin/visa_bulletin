#!/usr/bin/env python3
"""Test the updated file type detection logic on previously unknown files."""
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
        print(f"  Headers (first 10): {headers[:10]}")
        
        if detected is None:
            print(f"  ❌ Still unknown - needs more detection logic")
        else:
            print(f"  ✅ Now detected correctly")
    except Exception as e:
        print(f"{filename}: ERROR - {e}")

def main():
    # Test on a few previously unknown files
    test_files = [
        'H-1B_Disclosure_Data_FY15_Q4.xlsx',  # Has CASE_NUMBER, VISA_CLASS
        'LCA_Disclosure_Data_FY2020_Q1.xlsx',  # Has CASE_NUMBER, EMPLOYER_NAME
        'PERM_Disclosure_Data_FY2020.xlsx',   # Has CASE_NUMBER, EMPLOYER_NAME (PERM)
        'H-1B_Case_Data_FY2008.xlsx',         # Has CASE_NO, WAGE_RATE_1
        'lca_361.xlsx',                        # Has CASE_NUMBER, VISA_CLASS
    ]
    
    print("Testing updated detection logic on previously unknown files...")
    for filename in test_files:
        test_file(filename)

if __name__ == '__main__':
    main()

