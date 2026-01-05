#!/usr/bin/env python3
"""
Benchmark database serving/query performance.

Tests common query patterns from webapp:
- Salary search with filters (job_title, employer, state, year)
- Aggregations (avg, min, max salary)
- Pagination queries
- Index effectiveness with EXPLAIN ANALYZE
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

from django.db import connection
from django.db.models import Avg, Min, Max, Count, Q
from models.salary import SalaryRecord
from models.enums.visa_program import VisaProgram


def explain_query(queryset):
    """Get EXPLAIN ANALYZE output for a query"""
    sql, params = queryset.query.get_compiler(queryset.db).as_sql()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN ANALYZE {sql}", params)
        return '\n'.join(row[0] for row in cursor.fetchall())


def benchmark_query(name: str, queryset, show_explain: bool = False):
    """Benchmark a query and return timing"""
    print(f"Query: {name}")
    
    # Warm up
    list(queryset[:10])
    
    # Time the query
    start_time = time.time()
    results = list(queryset)
    query_time = time.time() - start_time
    
    print(f"  Results: {len(results):,}")
    print(f"  Time: {query_time:.3f} seconds")
    if len(results) > 0:
        print(f"  Time per result: {query_time / len(results) * 1000:.3f} ms")
    
    if show_explain:
        print("  EXPLAIN ANALYZE:")
        explain = explain_query(queryset)
        for line in explain.split('\n')[:10]:  # First 10 lines
            print(f"    {line}")
    
    print()
    return query_time


def benchmark_job_title_search():
    """Benchmark job title search queries"""
    print("=" * 80)
    print("JOB TITLE SEARCH BENCHMARKS")
    print("=" * 80)
    print()
    
    # Test different search terms
    search_terms = ['engineer', 'software', 'developer', 'manager', 'analyst']
    
    results = {}
    for term in search_terms:
        queryset = SalaryRecord.objects.filter(job_title__icontains=term)
        time_taken = benchmark_query(f"job_title__icontains='{term}'", queryset, show_explain=(term == 'engineer'))
        results[term] = time_taken
    
    return results


def benchmark_employer_search():
    """Benchmark employer name search queries"""
    print("=" * 80)
    print("EMPLOYER SEARCH BENCHMARKS")
    print("=" * 80)
    print()
    
    # Test different employer searches
    employers = ['Google', 'Microsoft', 'Amazon', 'Apple', 'Meta']
    
    results = {}
    for employer in employers:
        queryset = SalaryRecord.objects.filter(employer_name__icontains=employer)
        time_taken = benchmark_query(f"employer_name__icontains='{employer}'", queryset, show_explain=(employer == 'Google'))
        results[employer] = time_taken
    
    return results


def benchmark_state_filter():
    """Benchmark state filtering"""
    print("=" * 80)
    print("STATE FILTER BENCHMARKS")
    print("=" * 80)
    print()
    
    # Test different states
    states = ['CA', 'NY', 'TX', 'WA', 'FL']
    
    results = {}
    for state in states:
        queryset = SalaryRecord.objects.filter(worksite_state=state)
        time_taken = benchmark_query(f"worksite_state='{state}'", queryset, show_explain=(state == 'CA'))
        results[state] = time_taken
    
    return results


def benchmark_aggregations():
    """Benchmark aggregation queries"""
    print("=" * 80)
    print("AGGREGATION BENCHMARKS")
    print("=" * 80)
    print()
    
    # Overall aggregations
    queryset = SalaryRecord.objects.filter(wage_annual__isnull=False, wage_annual__gt=0)
    stats = queryset.aggregate(
        avg=Avg('wage_annual'),
        min=Min('wage_annual'),
        max=Max('wage_annual'),
        count=Count('id')
    )
    
    start_time = time.time()
    stats = queryset.aggregate(
        avg=Avg('wage_annual'),
        min=Min('wage_annual'),
        max=Max('wage_annual'),
        count=Count('id')
    )
    query_time = time.time() - start_time
    
    print("Overall salary statistics:")
    print(f"  Count: {stats['count']:,}")
    print(f"  Avg: ${stats['avg']:,.0f}")
    print(f"  Min: ${stats['min']:,.0f}")
    print(f"  Max: ${stats['max']:,.0f}")
    print(f"  Query time: {query_time:.3f} seconds")
    print()
    
    # Aggregations with filters
    print("Aggregations with filters:")
    
    # By state
    queryset = SalaryRecord.objects.filter(worksite_state='CA', wage_annual__isnull=False, wage_annual__gt=0)
    start_time = time.time()
    stats = queryset.aggregate(avg=Avg('wage_annual'), count=Count('id'))
    query_time = time.time() - start_time
    print(f"  CA average: ${stats['avg']:,.0f} (count: {stats['count']:,}, time: {query_time:.3f}s)")
    
    # By visa program
    queryset = SalaryRecord.objects.filter(visa_program=VisaProgram.H1B, wage_annual__isnull=False, wage_annual__gt=0)
    start_time = time.time()
    stats = queryset.aggregate(avg=Avg('wage_annual'), count=Count('id'))
    query_time = time.time() - start_time
    print(f"  H-1B average: ${stats['avg']:,.0f} (count: {stats['count']:,}, time: {query_time:.3f}s)")
    
    print()
    return query_time


def benchmark_pagination():
    """Benchmark pagination queries"""
    print("=" * 80)
    print("PAGINATION BENCHMARKS")
    print("=" * 80)
    print()
    
    per_page = 50
    
    # Test different pages
    for page in [1, 10, 100, 1000]:
        offset = (page - 1) * per_page
        queryset = SalaryRecord.objects.order_by('-wage_annual', '-fiscal_year')[offset:offset + per_page]
        
        start_time = time.time()
        results = list(queryset)
        query_time = time.time() - start_time
        
        print(f"Page {page} (offset {offset}):")
        print(f"  Results: {len(results)}")
        print(f"  Time: {query_time:.3f} seconds")
        if page == 1:
            explain = explain_query(SalaryRecord.objects.order_by('-wage_annual', '-fiscal_year')[:per_page])
            print("  EXPLAIN ANALYZE (first page):")
            for line in explain.split('\n')[:10]:
                print(f"    {line}")
        print()


def benchmark_complex_filters():
    """Benchmark complex multi-filter queries"""
    print("=" * 80)
    print("COMPLEX FILTER BENCHMARKS")
    print("=" * 80)
    print()
    
    # Multiple filters combined
    queryset = SalaryRecord.objects.filter(
        job_title__icontains='engineer',
        worksite_state='CA',
        visa_program=VisaProgram.H1B,
        fiscal_year=2024,
        wage_annual__gte=100000
    )
    
    time_taken = benchmark_query(
        "job_title='engineer' AND state='CA' AND program='H1B' AND year=2024 AND wage>=100k",
        queryset,
        show_explain=True
    )
    
    return time_taken


def benchmark_index_usage():
    """Check which indexes are being used"""
    print("=" * 80)
    print("INDEX USAGE ANALYSIS")
    print("=" * 80)
    print()
    
    queries = [
        ("job_title search", SalaryRecord.objects.filter(job_title__icontains='engineer')),
        ("employer search", SalaryRecord.objects.filter(employer_name__icontains='Google')),
        ("state filter", SalaryRecord.objects.filter(worksite_state='CA')),
        ("visa program + year", SalaryRecord.objects.filter(visa_program=VisaProgram.H1B, fiscal_year=2024)),
        ("wage range", SalaryRecord.objects.filter(wage_annual__gte=100000, wage_annual__lte=200000)),
    ]
    
    for name, queryset in queries:
        print(f"Query: {name}")
        explain = explain_query(queryset)
        # Look for index usage in explain output
        if 'Index' in explain or 'index' in explain.lower():
            print("  ✓ Index used")
            for line in explain.split('\n')[:5]:
                if 'Index' in line or 'index' in line.lower():
                    print(f"    {line.strip()}")
        else:
            print("  ✗ No index usage detected")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark database serving/query performance'
    )
    parser.add_argument(
        '--test-all',
        action='store_true',
        help='Run all benchmark tests'
    )
    parser.add_argument(
        '--test-job-title',
        action='store_true',
        help='Test job title searches'
    )
    parser.add_argument(
        '--test-employer',
        action='store_true',
        help='Test employer searches'
    )
    parser.add_argument(
        '--test-state',
        action='store_true',
        help='Test state filters'
    )
    parser.add_argument(
        '--test-aggregations',
        action='store_true',
        help='Test aggregation queries'
    )
    parser.add_argument(
        '--test-pagination',
        action='store_true',
        help='Test pagination'
    )
    parser.add_argument(
        '--test-complex',
        action='store_true',
        help='Test complex multi-filter queries'
    )
    parser.add_argument(
        '--test-indexes',
        action='store_true',
        help='Test index usage'
    )
    
    args = parser.parse_args()
    
    # Check database state
    total_records = SalaryRecord.objects.count()
    print(f"Database state: {total_records:,} records")
    print()
    
    if total_records == 0:
        print("Warning: Database is empty. Benchmarks may not be representative.")
        print()
    
    if args.test_all or args.test_job_title:
        benchmark_job_title_search()
    
    if args.test_all or args.test_employer:
        benchmark_employer_search()
    
    if args.test_all or args.test_state:
        benchmark_state_filter()
    
    if args.test_all or args.test_aggregations:
        benchmark_aggregations()
    
    if args.test_all or args.test_pagination:
        benchmark_pagination()
    
    if args.test_all or args.test_complex:
        benchmark_complex_filters()
    
    if args.test_all or args.test_indexes:
        benchmark_index_usage()
    
    print("Benchmark complete.")


if __name__ == '__main__':
    main()
