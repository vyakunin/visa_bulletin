#!/usr/bin/env python3
"""
Benchmark parsing performance on real input files.

Measures:
- Parsing speed (rows/second)
- Time breakdown: file read, row parsing, record creation
- Memory usage during parsing
- CSV vs Excel performance comparison
"""

import argparse
import cProfile
import io
import os
import pstats
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from lib.parsing.salary.db_importer import _read_data_file, _process_row
from lib.utils.data_source_utils import get_fiscal_year_from_filename
from lib.parsing.salary.db_importer import LCA_COLUMN_MAPPINGS, PERM_COLUMN_MAPPINGS
from models.enums.visa_program import VisaProgram
from models.salary import Employer
from lib.utils.http_utils import get_workspace_dir

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Warning: psutil not available, memory profiling will be limited")


def get_memory_usage():
    """Get current memory usage in MB"""
    if HAS_PSUTIL:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    return 0


def benchmark_file_read(filepath: Path) -> dict:
    """Benchmark file reading performance"""
    print(f"Benchmarking file read: {filepath.name}")
    print(f"  File size: {filepath.stat().st_size / (1024 * 1024):.1f} MB")
    
    mem_before = get_memory_usage()
    start_time = time.time()
    
    result = _read_data_file(filepath)
    
    # Handle Excel files that return (generator, timing_info) tuple
    if isinstance(result, tuple) and len(result) == 2:
        rows_gen, timing_info = result
    else:
        rows_gen = result
    
    # Convert generator to list for benchmarking (needed for len() and iteration)
    rows = list(rows_gen)
    
    read_time = time.time() - start_time
    mem_after = get_memory_usage()
    mem_used = mem_after - mem_before
    
    print(f"  Rows read: {len(rows):,}")
    print(f"  Read time: {read_time:.2f} seconds")
    print(f"  Rows/second: {len(rows) / read_time:,.0f}")
    print(f"  Memory used: {mem_used:.1f} MB")
    print()
    
    return {
        'rows': rows,
        'read_time': read_time,
        'mem_used': mem_used,
    }


def benchmark_row_parsing(rows: list, column_mappings: dict, visa_program: str, 
                          fiscal_year: int, source_file: str) -> dict:
    """Benchmark row parsing performance"""
    print("Benchmarking row parsing...")
    
    existing_cases = set()
    employers_cache = {}
    records_created = 0
    errors = 0
    skipped = 0
    
    mem_before = get_memory_usage()
    start_time = time.time()
    
    # Profile parsing
    profiler = cProfile.Profile()
    profiler.enable()
    
    for row_num, row in enumerate(rows[:10000], start=2):  # Sample first 10k rows
        result = _process_row(
            row, row_num, column_mappings, visa_program, fiscal_year, source_file,
            existing_cases, False, employers_cache
        )
        
        if result.record:
            records_created += 1
        elif result.error:
            errors += 1
        elif result.skipped:
            skipped += 1
    
    profiler.disable()
    parse_time = time.time() - start_time
    mem_after = get_memory_usage()
    mem_used = mem_after - mem_before
    
    # Get profiling stats
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    ps.sort_stats('cumulative')
    ps.print_stats(20)  # Top 20 functions
    
    print(f"  Rows parsed: {min(10000, len(rows)):,}")
    print(f"  Parse time: {parse_time:.2f} seconds")
    print(f"  Rows/second: {min(10000, len(rows)) / parse_time:,.0f}")
    print(f"  Records created: {records_created:,}")
    print(f"  Errors: {errors:,}")
    print(f"  Skipped: {skipped:,}")
    print(f"  Memory used: {mem_used:.1f} MB")
    print()
    print("Top functions by cumulative time:")
    print(s.getvalue())
    
    return {
        'parse_time': parse_time,
        'records_created': records_created,
        'errors': errors,
        'skipped': skipped,
        'mem_used': mem_used,
    }


def benchmark_full_processing(filepath: Path, visa_program: str, sample_size: int = None) -> dict:
    """Benchmark full processing pipeline"""
    print("=" * 80)
    print(f"FULL PROCESSING BENCHMARK")
    print("=" * 80)
    print()
    
    fiscal_year = get_fiscal_year_from_filename(filepath.name)
    if fiscal_year is None:
        fiscal_year = datetime.now().year
        print(f"Warning: Could not extract fiscal year from filename, using current year: {fiscal_year}")
    source_file = filepath.name
    
    if visa_program == VisaProgram.PERM:
        column_mappings = PERM_COLUMN_MAPPINGS
    else:
        column_mappings = LCA_COLUMN_MAPPINGS
    
    total_start = time.time()
    
    # Benchmark file read
    read_result = benchmark_file_read(filepath)
    rows = read_result['rows']
    
    # Limit rows if sample_size specified
    if sample_size and len(rows) > sample_size:
        print(f"Limiting to {sample_size:,} rows for benchmark")
        rows = rows[:sample_size]
    
    # Benchmark parsing (without DB inserts for this benchmark)
    parse_result = benchmark_row_parsing(
        rows, column_mappings, visa_program, fiscal_year, source_file
    )
    
    # Calculate totals
    total_time = time.time() - total_start
    total_mem = read_result['mem_used'] + parse_result['mem_used']
    
    # Time breakdown
    read_time = read_result['read_time']
    parse_time = parse_result['parse_time']
    # Note: DB insert time not included in this benchmark (see benchmark_db_ingest.py)
    
    print("=" * 80)
    print("TIME BREAKDOWN SUMMARY")
    print("=" * 80)
    print(f"File: {filepath.name}")
    print(f"Total rows: {len(rows):,}")
    print(f"Total time: {total_time:.2f} seconds")
    print(f"  File reading: {read_time:.2f} seconds ({read_time/total_time*100:.1f}%)")
    print(f"  Row processing: {parse_time:.2f} seconds ({parse_time/total_time*100:.1f}%)")
    print(f"  (Database inserts: see benchmark_db_ingest.py)")
    print(f"Overall rate: {len(rows) / total_time:,.0f} rows/second")
    print(f"Total memory: {total_mem:.1f} MB")
    print()
    
    return {
        'file': filepath.name,
        'rows': len(rows),
        'read_time': read_time,
        'parse_time': parse_time,
        'total_time': total_time,
        'rows_per_sec': len(rows) / total_time,
        'total_mem': total_mem,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark parsing performance on real input files'
    )
    parser.add_argument(
        '--file', '-f',
        type=Path,
        help='Path to file to benchmark'
    )
    parser.add_argument(
        '--program', '-p',
        choices=['h1b', 'perm'],
        default='h1b',
        help='Visa program type (default: h1b)'
    )
    parser.add_argument(
        '--sample-size',
        type=int,
        help='Limit to N rows for faster benchmarking'
    )
    parser.add_argument(
        '--all-large',
        action='store_true',
        help='Benchmark all large files in dol_data/'
    )
    
    args = parser.parse_args()
    
    workspace_dir = get_workspace_dir()
    dol_data_dir = workspace_dir / 'dol_data'
    
    if args.all_large:
        # Find large files
        all_files = []
        for pattern in ['*.csv', '*.xlsx', '*.xls']:
            all_files.extend(dol_data_dir.glob(pattern))
        
        # Filter out non-data files
        excluded_keywords = ['appendix', 'worksites', 'worksite']
        data_files = [
            f for f in all_files
            if not any(kw in f.name.lower() for kw in excluded_keywords)
        ]
        
        # Sort by size (largest first)
        data_files.sort(key=lambda f: f.stat().st_size, reverse=True)
        
        print(f"Found {len(data_files)} data files")
        print(f"Benchmarking top 5 largest files...")
        print()
        
        results = []
        for filepath in data_files[:5]:
            visa_program = VisaProgram.PERM if 'perm' in filepath.name.lower() else VisaProgram.H1B
            result = benchmark_full_processing(filepath, visa_program, sample_size=10000)
            results.append(result)
            print()
        
        # Summary comparison
        print("=" * 80)
        print("COMPARISON SUMMARY")
        print("=" * 80)
        print(f"{'File':<50} {'Rows':<12} {'Time (s)':<12} {'Rows/sec':<12} {'Mem (MB)':<10}")
        print("-" * 100)
        for result in results:
            print(f"{result['file']:<50} "
                  f"{result['rows']:>11,} "
                  f"{result['total_time']:>11.2f} "
                  f"{result['rows_per_sec']:>11,.0f} "
                  f"{result['total_mem']:>9.1f}")
    
    elif args.file:
        if not args.file.exists():
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
        
        visa_program = VisaProgram.PERM if args.program == 'perm' else VisaProgram.H1B
        benchmark_full_processing(args.file, visa_program, sample_size=args.sample_size)
    
    else:
        parser.error('Either --file or --all-large must be specified')


if __name__ == '__main__':
    main()











