#!/usr/bin/env python3
"""
Test Excel performance improvements: compare iterrows() vs to_dict() speedup.

Also analyzes database bottleneck by tracking batch times over import progress.
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


def benchmark_excel_reading_methods(filepath: Path, sample_rows: int = 10000):
    """Benchmark different Excel reading methods"""
    print("=" * 80)
    print("EXCEL READING METHOD BENCHMARK")
    print("=" * 80)
    print(f"File: {filepath.name}")
    print(f"Sample size: {sample_rows:,} rows")
    print()

    # Read DataFrame once
    print("Reading DataFrame...")
    df_start = time.time()
    df = pd.read_excel(filepath, dtype=str, na_values=["", "N/A", "NULL", "nan"])
    df_time = time.time() - df_start
    print(f"DataFrame read time: {df_time:.2f}s")
    print()

    # Sample rows for testing
    sample_df = df.head(sample_rows)

    # Method 1: iterrows() (old, slow)
    print("Method 1: iterrows() (OLD - SLOW)")
    start = time.time()
    records_iterrows = []
    for _, row in sample_df.iterrows():
        record = {}
        for col, val in row.items():
            if pd.isna(val) or val is None:
                record[col] = ""
            else:
                record[col] = str(val).strip()
        records_iterrows.append(record)
    iterrows_time = time.time() - start
    print(f"  Time: {iterrows_time:.2f}s")
    print(f"  Rate: {sample_rows / iterrows_time:,.0f} rows/second")
    print()

    # Method 2: to_dict(orient='records') (new, fast)
    print("Method 2: to_dict(orient='records') (NEW - FAST)")
    start = time.time()
    records_dict = sample_df.to_dict(orient="records")
    # Clean NaN values
    for record in records_dict:
        for key, val in record.items():
            if pd.isna(val) or val is None:
                record[key] = ""
            else:
                record[key] = str(val).strip()
    to_dict_time = time.time() - start
    print(f"  Time: {to_dict_time:.2f}s")
    print(f"  Rate: {sample_rows / to_dict_time:,.0f} rows/second")
    print()

    # Calculate speedup
    speedup = iterrows_time / to_dict_time if to_dict_time > 0 else 0
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"iterrows() time: {iterrows_time:.2f}s")
    print(f"to_dict() time: {to_dict_time:.2f}s")
    print(f"Speedup: {speedup:.1f}x faster")
    print()

    # Verify results are equivalent
    if len(records_iterrows) == len(records_dict):
        print(f"✓ Both methods processed {len(records_iterrows)} records")
        # Check a few records match
        matches = 0
        for i in range(min(10, len(records_iterrows))):
            if records_iterrows[i] == records_dict[i]:
                matches += 1
        if matches == min(10, len(records_iterrows)):
            print("✓ Results match (verified first 10 records)")
        else:
            print("⚠ Results differ (check implementation)")
    print()

    return {
        "iterrows_time": iterrows_time,
        "to_dict_time": to_dict_time,
        "speedup": speedup,
    }


def analyze_db_bottleneck_from_logs(log_file: Path):
    """Analyze database slowdown pattern from import logs"""
    print("=" * 80)
    print("DATABASE BOTTLENECK ANALYSIS")
    print("=" * 80)
    print()

    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        print("Run an import first to generate logs with batch timing")
        return

    # Parse batch insert times from logs
    batch_times = []
    import re

    with open(log_file) as f:
        for line in f:
            # Look for batch insert timing: "bulk: X.XXXs, commit: Y.YYYs"
            match = re.search(r"bulk: ([\d.]+)s, commit: ([\d.]+)s", line)
            if match:
                bulk_time = float(match.group(1))
                commit_time = float(match.group(2))
                total_time = bulk_time + commit_time

                # Extract record count if available
                record_match = re.search(r"Imported ([\d,]+) records", line)
                record_count = (
                    int(record_match.group(1).replace(",", "")) if record_match else 0
                )

                batch_times.append(
                    {
                        "records": record_count,
                        "bulk_time": bulk_time,
                        "commit_time": commit_time,
                        "total_time": total_time,
                    }
                )

    if not batch_times:
        print("No batch timing data found in logs")
        print(
            "Look for lines like: 'Imported X records... (bulk: X.XXXs, commit: Y.YYYs)'"
        )
        return

    print(f"Found {len(batch_times)} batch timing entries")
    print()

    # Analyze early vs late batches
    if len(batch_times) >= 10:
        early_batches = batch_times[: len(batch_times) // 3]
        late_batches = batch_times[-len(batch_times) // 3 :]

        early_avg_bulk = sum(b["bulk_time"] for b in early_batches) / len(early_batches)
        early_avg_commit = sum(b["commit_time"] for b in early_batches) / len(
            early_batches
        )
        early_avg_total = sum(b["total_time"] for b in early_batches) / len(
            early_batches
        )

        late_avg_bulk = sum(b["bulk_time"] for b in late_batches) / len(late_batches)
        late_avg_commit = sum(b["commit_time"] for b in late_batches) / len(
            late_batches
        )
        late_avg_total = sum(b["total_time"] for b in late_batches) / len(late_batches)

        print("Early batches (first third):")
        print(f"  Average bulk time: {early_avg_bulk:.3f}s")
        print(f"  Average commit time: {early_avg_commit:.3f}s")
        print(f"  Average total time: {early_avg_total:.3f}s")
        print()

        print("Late batches (last third):")
        print(f"  Average bulk time: {late_avg_bulk:.3f}s")
        print(f"  Average commit time: {late_avg_commit:.3f}s")
        print(f"  Average total time: {late_avg_total:.3f}s")
        print()

        bulk_slowdown = (
            ((late_avg_bulk - early_avg_bulk) / early_avg_bulk) * 100
            if early_avg_bulk > 0
            else 0
        )
        commit_slowdown = (
            ((late_avg_commit - early_avg_commit) / early_avg_commit) * 100
            if early_avg_commit > 0
            else 0
        )
        total_slowdown = (
            ((late_avg_total - early_avg_total) / early_avg_total) * 100
            if early_avg_total > 0
            else 0
        )

        print("Slowdown analysis:")
        print(f"  Bulk time slowdown: {bulk_slowdown:+.1f}%")
        print(f"  Commit time slowdown: {commit_slowdown:+.1f}%")
        print(f"  Total time slowdown: {total_slowdown:+.1f}%")
        print()

        if commit_slowdown > 20:
            print("⚠ WARNING: Significant commit time slowdown detected!")
            print("  This suggests index maintenance is the bottleneck.")
            print(
                "  Consider: disabling indexes during bulk import, then re-enabling after"
            )
        elif bulk_slowdown > 20:
            print("⚠ WARNING: Significant bulk_create slowdown detected!")
            print("  This suggests ignore_conflicts checking is getting slower.")
            print("  Consider: larger batch sizes or different conflict handling")
        else:
            print("✓ Database performance is stable (no significant slowdown)")

    # Show trend
    print("Batch time trend (first 10 and last 10):")
    print(
        f"{'Batch':<10} {'Records':<12} {'Bulk (s)':<12} {'Commit (s)':<12} {'Total (s)':<12}"
    )
    print("-" * 60)
    for i, batch in enumerate(batch_times[:10]):
        print(
            f"{i + 1:<10} {batch['records']:<12,} {batch['bulk_time']:<12.3f} {batch['commit_time']:<12.3f} {batch['total_time']:<12.3f}"
        )
    if len(batch_times) > 20:
        print("...")
        for i, batch in enumerate(batch_times[-10:], start=len(batch_times) - 9):
            print(
                f"{i + 1:<10} {batch['records']:<12,} {batch['bulk_time']:<12.3f} {batch['commit_time']:<12.3f} {batch['total_time']:<12.3f}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Test Excel performance improvements and analyze DB bottleneck"
    )
    parser.add_argument(
        "--file", "-f", type=Path, help="Path to Excel file to benchmark"
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=10000,
        help="Number of rows to sample for benchmark (default: 10000)",
    )
    parser.add_argument(
        "--analyze-logs",
        type=Path,
        help="Path to log file to analyze for DB bottleneck",
    )
    parser.add_argument(
        "--test-import",
        type=Path,
        help="Run full import test on file (tracks DB performance)",
    )

    args = parser.parse_args()

    workspace_dir = get_workspace_dir()

    if args.file:
        filepath = (
            workspace_dir / args.file if not args.file.is_absolute() else args.file
        )
        if not filepath.exists():
            print(f"Error: File not found: {filepath}")
            sys.exit(1)
        benchmark_excel_reading_methods(filepath, args.sample_rows)

    if args.analyze_logs:
        log_file = (
            workspace_dir / args.analyze_logs
            if not args.analyze_logs.is_absolute()
            else args.analyze_logs
        )
        analyze_db_bottleneck_from_logs(log_file)

    if args.test_import:
        filepath = (
            workspace_dir / args.test_import
            if not args.test_import.is_absolute()
            else args.test_import
        )
        if not filepath.exists():
            print(f"Error: File not found: {filepath}")
            sys.exit(1)

        print("=" * 80)
        print("FULL IMPORT TEST")
        print("=" * 80)
        print(f"File: {filepath.name}")
        print()
        print("This will import the file and track performance.")
        print("Check logs for detailed timing breakdown including DB commit times.")
        print()

        # Determine visa program
        filename_lower = filepath.name.lower()
        if "perm" in filename_lower:
            visa_program = VisaProgram.PERM
        else:
            visa_program = VisaProgram.H1B

        # Clean up any existing records from this file
        SalaryRecord.objects.filter(source_file=filepath.name).delete()

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

        print()
        print("=" * 80)
        print("IMPORT RESULTS")
        print("=" * 80)
        print(f"Imported: {imported:,} records")
        print(f"Skipped: {skipped:,} records")
        print(f"Errors: {errors:,} records")
        print(f"Total time: {total_time:.2f} seconds")
        if imported > 0:
            print(f"Import rate: {imported / total_time:,.0f} records/second")
        print()
        print("Check logs for detailed performance breakdown!")

    if not any([args.file, args.analyze_logs, args.test_import]):
        parser.error(
            "At least one of --file, --analyze-logs, or --test-import must be specified"
        )


if __name__ == "__main__":
    main()
