#!/usr/bin/env python3
"""
Run comprehensive performance benchmarks and generate side-by-side comparison.

Tests:
1. Excel reading method comparison (iterrows vs to_dict)
2. Full import performance with new optimizations
3. Database timing analysis
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Setup Django early
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

import pandas as pd

from lib.parsing.salary.db_importer import import_csv_file
from lib.utils.http_utils import get_workspace_dir
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord


def benchmark_excel_methods(filepath: Path, sample_rows: int = 5000):
    """Benchmark iterrows() vs to_dict() performance"""
    print("=" * 80)
    print("EXCEL READING METHOD BENCHMARK")
    print("=" * 80)
    print(f"File: {filepath.name}")
    print(f"Sample size: {sample_rows:,} rows")
    print()

    # Read DataFrame
    print("Reading DataFrame...")
    df_start = time.time()
    df = pd.read_excel(filepath, dtype=str, na_values=["", "N/A", "NULL", "nan"])
    df_time = time.time() - df_start
    print(f"DataFrame read: {df_time:.2f}s")

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
                record[col] = ""
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
    records_new = sample_df.to_dict(orient="records")
    # Clean NaN values
    for record in records_new:
        for key, val in record.items():
            if pd.isna(val) or val is None:
                record[key] = ""
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
    print("COMPARISON")
    print("=" * 80)
    print(f"{'Method':<30} {'Time (s)':<15} {'Rate (rows/s)':<20} {'Speedup':<15}")
    print("-" * 80)
    print(
        f"{'iterrows() (OLD)':<30} {old_time:<15.3f} {old_rate:<20,.0f} {'1.0x (baseline)':<15}"
    )
    print(
        f"{'to_dict() (NEW)':<30} {new_time:<15.3f} {new_rate:<20,.0f} {f'{speedup:.1f}x':<15}"
    )
    print()
    print(f"Speedup: {speedup:.1f}x faster")
    print(f"Time saved: {old_time - new_time:.3f}s per {sample_rows:,} rows")
    print()

    return {
        "old_time": old_time,
        "new_time": new_time,
        "old_rate": old_rate,
        "new_rate": new_rate,
        "speedup": speedup,
    }


def get_baseline_metrics():
    """Get baseline metrics from log analysis"""
    return {
        "excel_read_rate": 1429,  # rows/sec from baseline
        "import_rate_avg": 1622,  # records/sec average
        "import_rate_early": 2098,  # records/sec early batches
        "import_rate_late": 877,  # records/sec late batches
        "slowdown_pct": 58.2,  # % slowdown
        "batch_time": 0.75,  # seconds per 1000 records
    }


def run_import_test(filepath: Path, visa_program: str, max_rows: int = None):
    """Run import test and collect performance metrics"""
    print("=" * 80)
    print("FULL IMPORT TEST (WITH OPTIMIZATIONS)")
    print("=" * 80)
    print(f"File: {filepath.name}")
    if max_rows:
        print(f"Limiting to {max_rows:,} rows for testing")
    print()

    # Clean up
    SalaryRecord.objects.filter(source_file=filepath.name).delete()

    initial_count = SalaryRecord.objects.count()

    # Run import
    start_time = time.time()
    imported, skipped, errors = import_csv_file(
        filepath,
        visa_program,
        batch_size=1000,
        skip_existing=False,
        stream=True,
    )
    total_time = time.time() - start_time

    final_count = SalaryRecord.objects.count()
    _actual_imported = final_count - initial_count

    print()
    print("=" * 80)
    print("IMPORT RESULTS")
    print("=" * 80)
    print(f"Imported: {imported:,} records")
    print(f"Skipped: {skipped:,} records")
    print(f"Errors: {errors:,} records")
    print(f"Total time: {total_time:.2f} seconds")

    if imported > 0:
        import_rate = imported / total_time
        print(f"Import rate: {import_rate:,.0f} records/second")

    print()
    print("Check logs for detailed performance breakdown!")
    print("Look for: 'Performance breakdown for {filepath.name}'")
    print()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_time": total_time,
        "import_rate": imported / total_time if total_time > 0 else 0,
    }


def generate_side_by_side_comparison(baseline, excel_bench, import_results=None):
    """Generate side-by-side performance comparison"""
    print("=" * 80)
    print("SIDE-BY-SIDE PERFORMANCE COMPARISON")
    print("=" * 80)
    print()

    print("EXCEL READING PERFORMANCE")
    print("-" * 80)
    print(
        f"{'Metric':<40} {'Before (iterrows)':<25} {'After (to_dict)':<25} {'Improvement':<20}"
    )
    print("-" * 110)
    to_dict_name = "to_dict(orient='records')"
    old_rate_val = excel_bench["old_rate"]
    new_rate_val = excel_bench["new_rate"]
    speedup_val = excel_bench["speedup"]
    old_time_10k = 10000 / old_rate_val
    new_time_10k = 10000 / new_rate_val
    time_speedup = old_time_10k / new_time_10k

    print(f"{'Reading method':<40} {'iterrows()':<25} {to_dict_name:<25} {'':<20}")
    print(
        f"{'Processing rate (rows/sec)':<40} {old_rate_val:,.0f}{'':<18} {new_rate_val:,.0f}{'':<18} {speedup_val:.1f}x faster{'':<8}"
    )
    print(
        f"{'Time per 10k rows (seconds)':<40} {old_time_10k:.2f}{'':<20} {new_time_10k:.2f}{'':<20} {time_speedup:.1f}x{'':<15}"
    )
    print()

    print("IMPORT PERFORMANCE (Baseline vs Optimized)")
    print("-" * 80)
    print(
        f"{'Metric':<40} {'Baseline (from logs)':<25} {'Optimized (if tested)':<25} {'Improvement':<20}"
    )
    print("-" * 110)

    if import_results:
        baseline_rate = baseline["import_rate_avg"]
        new_rate = import_results["import_rate"]
        improvement_pct = (new_rate - baseline_rate) / baseline_rate * 100
        baseline_time_618k = 618000 / baseline_rate
        new_time_618k = 618000 / new_rate
        time_improvement_pct = ((baseline_time_618k / new_time_618k) - 1) * 100
        print(
            f"{'Average import rate (rec/sec)':<40} {baseline_rate:,.0f}{'':<18} {new_rate:,.0f}{'':<18} {improvement_pct:+.1f}%{'':<13}"
        )
        print(
            f"{'Total import time (for 618k rows)':<40} {baseline_time_618k:.0f}s{'':<20} {new_time_618k:.0f}s{'':<20} {time_improvement_pct:.1f}% faster{'':<8}"
        )
    else:
        print(
            f"{'Average import rate (rec/sec)':<40} {baseline['import_rate_avg']:,.0f}{'':<18} {'(run --test-import)':<25} {'':<20}"
        )
        print(
            f"{'Early batch rate (rec/sec)':<40} {baseline['import_rate_early']:,.0f}{'':<18} {'(run --test-import)':<25} {'':<20}"
        )
        print(
            f"{'Late batch rate (rec/sec)':<40} {baseline['import_rate_late']:,.0f}{'':<18} {'(run --test-import)':<25} {'':<20}"
        )
        print(
            f"{'Slowdown as DB grows':<40} {baseline['slowdown_pct']:.1f}%{'':<20} {'(check logs)':<25} {'':<20}"
        )

    print()

    print("EXPECTED IMPROVEMENTS (Based on Excel Speedup)")
    print("-" * 80)
    print(f"{'Metric':<40} {'Before':<25} {'After (Expected)':<25} {'Improvement':<20}")
    print("-" * 110)

    # Calculate expected improvements
    excel_speedup = excel_bench["speedup"]
    baseline_excel_time = 618000 / baseline["excel_read_rate"]  # Time for 618k rows
    expected_excel_time = baseline_excel_time / excel_speedup

    # If Excel was 60% of total time, calculate overall improvement
    baseline_total = 618000 / baseline["import_rate_avg"]
    excel_portion = baseline_excel_time  # Assume Excel read was significant portion
    other_portion = baseline_total - excel_portion
    expected_total = expected_excel_time + other_portion
    overall_speedup = baseline_total / expected_total if expected_total > 0 else 1

    print(
        f"{'Excel read time (618k rows)':<40} {baseline_excel_time:.0f}s{'':<20} {expected_excel_time:.0f}s{'':<20} {excel_speedup:.1f}x faster{'':<8}"
    )
    print(
        f"{'Overall import time (618k rows)':<40} {baseline_total:.0f}s{'':<20} {expected_total:.0f}s{'':<20} {overall_speedup:.1f}x faster{'':<8}"
    )
    print()

    print("KEY FINDINGS")
    print("-" * 80)
    print(f"✓ Excel reading: {excel_speedup:.1f}x faster with to_dict()")
    print(f"✓ Expected overall import: {overall_speedup:.1f}x faster")
    if import_results:
        print(
            f"✓ Actual import rate: {import_results['import_rate']:,.0f} records/second"
        )
    print("✓ Database timing now visible (bulk vs commit)")
    print("✓ Can identify bottlenecks accurately")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Run performance benchmarks and generate side-by-side comparison"
    )
    parser.add_argument(
        "--file", "-f", type=Path, help="Path to Excel file to benchmark"
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5000,
        help="Number of rows to sample for Excel benchmark (default: 5000)",
    )
    parser.add_argument(
        "--test-import",
        action="store_true",
        help="Run full import test (requires --file)",
    )
    parser.add_argument(
        "--max-rows", type=int, help="Limit import to N rows for testing"
    )

    args = parser.parse_args()

    workspace_dir = get_workspace_dir()

    # Get baseline metrics
    baseline = get_baseline_metrics()

    excel_bench = None
    import_results = None

    if args.file:
        filepath = (
            workspace_dir / args.file if not args.file.is_absolute() else args.file
        )
        if not filepath.exists():
            print(f"Error: File not found: {filepath}")
            sys.exit(1)

        # Benchmark Excel reading methods
        excel_bench = benchmark_excel_methods(filepath, args.sample_rows)
        print()
        print()

        # Run import test if requested
        if args.test_import:
            filename_lower = filepath.name.lower()
            visa_program = (
                VisaProgram.PERM if "perm" in filename_lower else VisaProgram.H1B
            )

            import_results = run_import_test(filepath, visa_program, args.max_rows)
            print()
            print()

    # Generate side-by-side comparison
    if excel_bench:
        generate_side_by_side_comparison(baseline, excel_bench, import_results)
    else:
        print("Run with --file to benchmark Excel reading methods")
        print(
            "Example: python3 scripts/run_performance_benchmarks.py --file dol_data/file.xlsx"
        )


if __name__ == "__main__":
    main()
