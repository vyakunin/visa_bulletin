#!/usr/bin/env python3
"""
Test import performance with streaming enabled.

Shows memory usage and timing for file imports.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Warning: psutil not available, memory profiling will be limited")
    print("Install with: pip install psutil")

from lib.parsing.salary.db_importer import import_csv_file
from lib.utils.http_utils import get_workspace_dir
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord


def get_memory_usage():
    """Get current memory usage in MB"""
    if HAS_PSUTIL:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    return 0


def test_import(filepath: Path, visa_program: str, test_name: str):
    """Test import performance"""
    print("=" * 80)
    print(f"{test_name}")
    print("=" * 80)
    print(f"File: {filepath.name}")
    print("Streaming: Always enabled")
    print()
    
    # Clean up any existing test records
    SalaryRecord.objects.filter(source_file=filepath.name).delete()
    
    # Get initial memory
    mem_before = get_memory_usage()
    if HAS_PSUTIL:
        print(f"Initial memory: {mem_before:.1f} MB")
    
    # Get initial record count
    initial_count = SalaryRecord.objects.count()
    
    # Run import (streaming is always enabled)
    start_time = time.time()
    try:
        imported, skipped, errors = import_csv_file(
            filepath,
            visa_program,
            batch_size=1000,
            skip_existing=False,  # Don't skip for test
        )
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    total_time = time.time() - start_time
    
    # Get final memory
    mem_after = get_memory_usage()
    mem_used = mem_after - mem_before if HAS_PSUTIL else 0
    
    # Get final record count
    final_count = SalaryRecord.objects.count()
    actual_imported = final_count - initial_count
    
    print()
    print(f"Results:")
    print(f"  Imported: {imported:,} records")
    print(f"  Skipped: {skipped:,} records")
    print(f"  Errors: {errors:,} records")
    print(f"  Total time: {total_time:.2f} seconds")
    if imported > 0:
        print(f"  Import rate: {imported/total_time:,.0f} records/second")
    if HAS_PSUTIL:
        print(f"  Memory used: {mem_used:.1f} MB")
        print(f"  Peak memory: {mem_after:.1f} MB")
    
    return {
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'total_time': total_time,
        'mem_used': mem_used,
        'peak_mem': mem_after,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Test import performance with streaming enabled'
    )
    parser.add_argument(
        '--file', '-f',
        type=Path,
        required=True,
        help='Path to file to test'
    )
    parser.add_argument(
        '--program', '-p',
        choices=['h1b', 'perm'],
        default='h1b',
        help='Visa program type (default: h1b)'
    )
    
    args = parser.parse_args()
    
    if not args.file.exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)
    
    workspace_dir = get_workspace_dir()
    filepath = workspace_dir / args.file if not args.file.is_absolute() else args.file
    
    visa_program = VisaProgram.PERM if args.program == 'perm' else VisaProgram.H1B
    
    # Test import with streaming (always enabled)
    result = test_import(
        filepath, visa_program, test_name="Import Performance Test (Streaming Enabled)"
    )
    
    if result:
        print()
        print("Test complete!")
    else:
        print()
        print("Test failed!")
        sys.exit(1)


if __name__ == '__main__':
    main()











