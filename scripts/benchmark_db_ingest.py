#!/usr/bin/env python3
"""
Benchmark database ingest performance.

Tests:
- bulk_create performance with different batch sizes
- Impact of indexes on insert speed
- Performance with real-world database size
- ignore_conflicts=True vs False comparison
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

from django.db import transaction, connection
from models.salary import SalaryRecord, Employer
from models.enums.visa_program import VisaProgram, CaseStatus
from models.ingest import IngestVersion  # Import to ensure Django can resolve ForeignKey
from lib.parsing.salary.db_importer import _create_salary_record, LCA_COLUMN_MAPPINGS
from lib.parsing.salary.wage_unit_correction import correct_wage_unit, calculate_annual_wage
from decimal import Decimal

# Force Django to resolve all model relationships
from django.apps import apps
apps.get_app_config('models').ready()


def get_current_db_size():
    """Get current database record count"""
    return SalaryRecord.objects.count()


def create_test_records(count: int, visa_program: int = VisaProgram.H1B) -> list:
    """Create test SalaryRecord objects (not saved)"""
    # Get or create a test employer
    employer, _ = Employer.objects.get_or_create(
        name_normalized='TEST_EMPLOYER',
        city='Test City',
        state='CA',
        defaults={'name': 'Test Employer'}
    )
    
    records = []
    for i in range(count):
        record = SalaryRecord(
            case_number=f'TEST-{visa_program}-{i}-{int(time.time())}',
            visa_program=visa_program,
            case_status=CaseStatus.CERTIFIED,
            employer=employer,
            employer_name='Test Employer',
            job_title=f'Test Job {i % 100}',
            soc_code='15-1132',
            soc_title='Software Developers, Applications',
            worksite_city='San Francisco',
            worksite_state='CA',
            wage_from=Decimal('100000') + Decimal(i % 50000),
            wage_unit='YEAR',
            wage_annual=Decimal('100000') + Decimal(i % 50000),
            fiscal_year=2024,
            source_file='test_benchmark.csv',
            ingest_version=None,  # Explicitly set to None for benchmark
        )
        records.append(record)
    
    return records


def benchmark_batch_size(batch_sizes: list[int], num_records: int = 10000, 
                         ignore_conflicts: bool = True) -> dict:
    """Benchmark different batch sizes"""
    print("=" * 80)
    print(f"BATCH SIZE BENCHMARK")
    print("=" * 80)
    print(f"Total records: {num_records:,}")
    print(f"ignore_conflicts: {ignore_conflicts}")
    print()
    
    results = []
    
    for batch_size in batch_sizes:
        print(f"Testing batch size: {batch_size}")
        
        # Clean up any test records from previous runs
        SalaryRecord.objects.filter(source_file='test_benchmark.csv').delete()
        
        # Create test records (track creation time)
        create_start = time.time()
        records = create_test_records(num_records)
        create_time = time.time() - create_start
        
        # Benchmark bulk_create
        insert_start = time.time()
        
        batches = 0
        total_insert_time = 0.0
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            batch_start = time.time()
            with transaction.atomic():
                SalaryRecord.objects.bulk_create(batch, ignore_conflicts=ignore_conflicts)
            total_insert_time += time.time() - batch_start
            batches += 1
        
        insert_time = time.time() - insert_start
        total_time = create_time + insert_time
        
        # Calculate metrics
        records_per_sec = num_records / insert_time
        time_per_batch = insert_time / batches
        time_per_record = insert_time / num_records
        
        print(f"  Batches: {batches}")
        print(f"  Time breakdown:")
        print(f"    Record creation: {create_time:.3f}s ({create_time/total_time*100:.1f}%)")
        print(f"    Database inserts: {insert_time:.3f}s ({insert_time/total_time*100:.1f}%)")
        print(f"    Total: {total_time:.2f} seconds")
        print(f"  Time per batch: {time_per_batch:.3f} seconds")
        print(f"  Records/second: {records_per_sec:,.0f}")
        print(f"  Time per record: {time_per_record*1000:.3f} ms")
        print()
        
        results.append({
            'batch_size': batch_size,
            'batches': batches,
            'create_time': create_time,
            'insert_time': insert_time,
            'total_time': total_time,
            'time_per_batch': time_per_batch,
            'records_per_sec': records_per_sec,
            'time_per_record': time_per_record,
        })
        
        # Clean up
        SalaryRecord.objects.filter(source_file='test_benchmark.csv').delete()
    
    return results


def benchmark_with_db_size(num_records: int = 10000, batch_size: int = 1000) -> dict:
    """Benchmark insert performance at different database sizes"""
    print("=" * 80)
    print(f"DATABASE SIZE IMPACT BENCHMARK")
    print("=" * 80)
    print()
    
    initial_size = get_current_db_size()
    print(f"Initial database size: {initial_size:,} records")
    print()
    
    # Test at current size
    print("Testing at current database size...")
    records = create_test_records(num_records)
    
    start_time = time.time()
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        with transaction.atomic():
            SalaryRecord.objects.bulk_create(batch, ignore_conflicts=True)
    time_at_current = time.time() - start_time
    
    # Clean up
    SalaryRecord.objects.filter(source_file='test_benchmark.csv').delete()
    
    current_rate = num_records / time_at_current
    print(f"  Time: {time_at_current:.2f} seconds")
    print(f"  Rate: {current_rate:,.0f} records/second")
    print()
    
    return {
        'initial_size': initial_size,
        'time_at_current': time_at_current,
        'rate_at_current': current_rate,
    }


def benchmark_ignore_conflicts(num_records: int = 5000, batch_size: int = 1000) -> dict:
    """Compare ignore_conflicts=True vs False"""
    print("=" * 80)
    print(f"IGNORE_CONFLICTS COMPARISON")
    print("=" * 80)
    print()
    
    results = {}
    
    for ignore_conflicts in [True, False]:
        print(f"Testing ignore_conflicts={ignore_conflicts}...")
        
        # Clean up
        SalaryRecord.objects.filter(source_file='test_benchmark.csv').delete()
        
        # Create and insert records first time
        records = create_test_records(num_records)
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            with transaction.atomic():
                SalaryRecord.objects.bulk_create(batch, ignore_conflicts=True)
        
        # Now test inserting same records again
        records = create_test_records(num_records)  # Same case numbers
        start_time = time.time()
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            with transaction.atomic():
                SalaryRecord.objects.bulk_create(batch, ignore_conflicts=ignore_conflicts)
        
        total_time = time.time() - start_time
        
        print(f"  Time: {total_time:.2f} seconds")
        print(f"  Rate: {num_records / total_time:,.0f} records/second")
        print()
        
        results[ignore_conflicts] = {
            'time': total_time,
            'rate': num_records / total_time,
        }
        
        # Clean up
        SalaryRecord.objects.filter(source_file='test_benchmark.csv').delete()
    
    if results[True]['time'] > 0 and results[False]['time'] > 0:
        speedup = results[False]['time'] / results[True]['time']
        print(f"ignore_conflicts=True is {speedup:.2f}x faster for duplicate handling")
        print()
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark database ingest performance'
    )
    parser.add_argument(
        '--batch-sizes',
        nargs='+',
        type=int,
        default=[500, 1000, 2000, 5000],
        help='Batch sizes to test (default: 500 1000 2000 5000)'
    )
    parser.add_argument(
        '--num-records',
        type=int,
        default=10000,
        help='Number of records to use for benchmark (default: 10000)'
    )
    parser.add_argument(
        '--test-all',
        action='store_true',
        help='Run all benchmark tests'
    )
    parser.add_argument(
        '--test-batch-sizes',
        action='store_true',
        help='Test different batch sizes'
    )
    parser.add_argument(
        '--test-db-size',
        action='store_true',
        help='Test impact of database size'
    )
    parser.add_argument(
        '--test-conflicts',
        action='store_true',
        help='Test ignore_conflicts performance'
    )
    
    args = parser.parse_args()
    
    # Check current database state
    current_size = get_current_db_size()
    print(f"Current database size: {current_size:,} records")
    print()
    
    if args.test_all or args.test_batch_sizes:
        results = benchmark_batch_size(args.batch_sizes, args.num_records)
        
        print("=" * 80)
        print("BATCH SIZE SUMMARY")
        print("=" * 80)
        print(f"{'Batch Size':<12} {'Batches':<10} {'Time (s)':<12} {'Records/sec':<15} {'Time/Batch (ms)':<15}")
        print("-" * 80)
        for r in results:
            print(f"{r['batch_size']:<12} "
                  f"{r['batches']:<10} "
                  f"{r['total_time']:<12.2f} "
                  f"{r['records_per_sec']:<15,.0f} "
                  f"{r['time_per_batch']*1000:<15.2f}")
        print()
    
    if args.test_all or args.test_db_size:
        benchmark_with_db_size(args.num_records)
    
    if args.test_all or args.test_conflicts:
        benchmark_ignore_conflicts(args.num_records // 2)
    
    # Final cleanup
    SalaryRecord.objects.filter(source_file='test_benchmark.csv').delete()
    print("Benchmark complete. Test records cleaned up.")


if __name__ == '__main__':
    main()

