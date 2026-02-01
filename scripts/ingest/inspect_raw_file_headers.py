#!/usr/bin/env python3
"""
Inspect raw file headers to check for missing fields.

Checks:
1. Worksite files - are there any employer-related columns we're not parsing?
2. PERM files with missing job titles - are there alternative job title columns?
"""

import argparse
import sys
from pathlib import Path
from collections import Counter

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import django
django.setup()

from models.salary import WorksiteRecord, SalaryRecord
from lib.utils.http_utils import get_workspace_dir
from lib.utils.excel_utils import read_excel_headers
import csv


def inspect_worksite_file(filepath: Path):
    """Inspect a worksite file for employer-related columns"""
    print(f"\n📁 Inspecting worksite file: {filepath.name}")
    
    if filepath.suffix.lower() == '.xlsx':
        headers = read_excel_headers(filepath)
    else:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            headers = next(reader)
    
    print(f"   Total columns: {len(headers)}")
    
    # Check for employer-related columns
    employer_keywords = ['employer', 'business', 'company', 'organization', 'corp', 'inc', 'llc']
    employer_columns = []
    for header in headers:
        header_lower = str(header).lower()
        if any(keyword in header_lower for keyword in employer_keywords):
            employer_columns.append(header)
    
    if employer_columns:
        print(f"   ⚠️  Found employer-related columns:")
        for col in employer_columns:
            print(f"      - {col}")
    else:
        print(f"   ✅ No employer-related columns found (as expected)")
    
    # Show all column names
    print(f"\n   All columns ({len(headers)}):")
    for i, header in enumerate(headers[:30], 1):  # Show first 30
        print(f"      {i}. {header}")
    if len(headers) > 30:
        print(f"      ... and {len(headers) - 30} more")


def inspect_perm_file_without_job_title(filepath: Path):
    """Inspect a PERM file that has records without job titles"""
    print(f"\n📁 Inspecting PERM file: {filepath.name}")
    
    if filepath.suffix.lower() == '.xlsx':
        headers = read_excel_headers(filepath)
    else:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            headers = next(reader)
    
    print(f"   Total columns: {len(headers)}")
    
    # Check for job title columns
    job_keywords = ['job', 'title', 'occupation', 'position', 'role', 'pw_job', 'job_info']
    job_columns = []
    for header in headers:
        header_lower = str(header).lower()
        if any(keyword in header_lower for keyword in job_keywords):
            job_columns.append(header)
    
    if job_columns:
        print(f"   Found job title-related columns:")
        for col in job_columns:
            print(f"      - {col}")
    else:
        print(f"   ⚠️  No job title-related columns found!")
    
    # Show all column names
    print(f"\n   All columns ({len(headers)}):")
    for i, header in enumerate(headers[:30], 1):  # Show first 30
        print(f"      {i}. {header}")
    if len(headers) > 30:
        print(f"      ... and {len(headers) - 30} more")


def main():
    """Main inspection function"""
    print("🔍 Inspecting raw file headers...")
    
    # Find sample worksite files
    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / 'data' / 'salary' / 'dol_data'
    if not data_dir.exists():
        print(f"❌ Data directory not found: {data_dir}")
        return
    
    # Find worksite files
    worksite_files = list(data_dir.glob('*Worksites*.xlsx')) + list(data_dir.glob('*worksites*.xlsx'))
    if worksite_files:
        print(f"\n📊 Found {len(worksite_files)} worksite files")
        # Inspect first few
        for filepath in worksite_files[:3]:
            inspect_worksite_file(filepath)
    else:
        print("\n⚠️  No worksite files found")
    
    # Find PERM files with missing job titles
    perm_files = list(data_dir.glob('PERM*.xlsx'))
    if perm_files:
        print(f"\n📊 Found {len(perm_files)} PERM files")
        # Check which PERM files have records without job titles
        perm_without_job_title = SalaryRecord.objects.filter(
            source_file__startswith='PERM',
            job_title__in=['', 'Unknown']
        ).values_list('source_file', flat=True).distinct()
        
        if perm_without_job_title:
            print(f"\n   PERM files with missing job titles: {list(perm_without_job_title)[:5]}")
            # Inspect first PERM file
            for source_file in list(perm_without_job_title)[:1]:
                filepath = data_dir / source_file
                if filepath.exists():
                    inspect_perm_file_without_job_title(filepath)
                else:
                    # Try with just filename if source_file includes path
                    filename = Path(source_file).name
                    filepath = data_dir / filename
                    if filepath.exists():
                        inspect_perm_file_without_job_title(filepath)
                    else:
                        print(f"   ⚠️  File not found: {source_file} or {filename}")
        else:
            print("\n   ✅ No PERM files with missing job titles found")
    else:
        print("\n⚠️  No PERM files found")


if __name__ == '__main__':
    main()

