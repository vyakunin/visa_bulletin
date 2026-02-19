#!/usr/bin/env python3
"""
Standalone Excel reading benchmark (no Django required).

Compares iterrows() vs to_dict() performance.
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Error: pandas not installed. Install with: pip install pandas openpyxl")
    sys.exit(1)


def benchmark_methods(filepath: Path, sample_rows: int = 5000):
    """Benchmark iterrows() vs to_dict()"""
    print("=" * 80)
    print("EXCEL READING METHOD BENCHMARK")
    print("=" * 80)
    print(f"File: {filepath.name}")
    print(f"Sample size: {sample_rows:,} rows")
    print()

    # Read DataFrame
    print("Reading DataFrame...")
    df_start = time.time()
    df = pd.read_excel(filepath, dtype=str, na_values=['', 'N/A', 'NULL', 'nan'])
    df_time = time.time() - df_start
    print(f"DataFrame read: {df_time:.2f}s ({len(df):,} total rows)")

    sample_df = df.head(sample_rows)
    print()

    # Method 1: iterrows() (OLD)
    print("Method 1: iterrows() (OLD - SLOW)")
    start = time.time()
    records_old = []
    for _, row in sample_df.iterrows():
        record = {}
        for col, val in row.items():
            if pd.isna(val) or val is None:
                record[col] = ''
            else:
                record[col] = str(val).strip()
        records_old.append(record)
    old_time = time.time() - start
    old_rate = sample_rows / old_time if old_time > 0 else 0
    print(f"  Time: {old_time:.3f}s")
    print(f"  Rate: {old_rate:,.0f} rows/second")
    print()

    # Method 2: to_dict() (NEW)
    print("Method 2: to_dict(orient='records') (NEW - FAST)")
    start = time.time()
    records_new = sample_df.to_dict(orient='records')
    # Clean NaN values
    for record in records_new:
        for key, val in record.items():
            if pd.isna(val) or val is None:
                record[key] = ''
            else:
                record[key] = str(val).strip()
    new_time = time.time() - start
    new_rate = sample_rows / new_time if new_time > 0 else 0
    print(f"  Time: {new_time:.3f}s")
    print(f"  Rate: {new_rate:,.0f} rows/second")
    print()

    # Calculate speedup
    speedup = old_time / new_time if new_time > 0 else 0

    print("=" * 80)
    print("SIDE-BY-SIDE COMPARISON")
    print("=" * 80)
    print()
    print(f"{'Metric':<40} {'iterrows() (OLD)':<25} {'to_dict() (NEW)':<25} {'Improvement':<20}")
    print("-" * 110)
    print(f"{'Processing rate (rows/sec)':<40} {old_rate:>23,.0f} {new_rate:>23,.0f} {speedup:>18.1f}x faster")
    print(f"{'Time per 10k rows (seconds)':<40} {10000/old_rate:>23.2f} {10000/new_rate:>23.2f} {speedup:>18.1f}x faster")
    print(f"{'Time for 618k rows (seconds)':<40} {618000/old_rate:>23.0f} {618000/new_rate:>23.0f} {speedup:>18.1f}x faster")
    print()
    print(f"Speedup: {speedup:.1f}x faster")
    print(f"Time saved per 10k rows: {10000/old_rate - 10000/new_rate:.2f} seconds")
    print()

    # Verify results match
    if len(records_old) == len(records_new):
        matches = sum(1 for i in range(min(10, len(records_old)))
                     if records_old[i] == records_new[i])
        if matches == min(10, len(records_old)):
            print("✓ Results verified: Both methods produce identical output")
        else:
            print("⚠ Results differ: Check implementation")
    print()

    return {
        'old_time': old_time,
        'new_time': new_time,
        'old_rate': old_rate,
        'new_rate': new_rate,
        'speedup': speedup,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark Excel reading methods (standalone, no Django)'
    )
    parser.add_argument(
        '--file', '-f',
        type=Path,
        required=True,
        help='Path to Excel file to benchmark'
    )
    parser.add_argument(
        '--sample-rows',
        type=int,
        default=5000,
        help='Number of rows to sample (default: 5000)'
    )

    args = parser.parse_args()

    if not args.file.exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    benchmark_methods(args.file, args.sample_rows)


if __name__ == '__main__':
    main()










