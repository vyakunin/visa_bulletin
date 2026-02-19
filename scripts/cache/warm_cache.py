#!/usr/bin/env python3
"""
Warm up Django cache for frequently accessed pages.

This script pre-populates the cache with expensive computations to ensure
fast page loads for users. Run after data refresh or deployment.

Usage:
    bazel run //scripts/cache:warm_cache
    bazel run //scripts/cache:warm_cache -- --verbose
"""

import logging
import os
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

import argparse

from django.core.cache import cache

from lib.business.salary.market_overview import get_market_overview_stats
from models.job_title import JobTitleCluster
from models.salary import EmployerCluster, SalaryRecord

logger = logging.getLogger(__name__)


def warm_market_overview_cache(verbose: bool = False):
    """Warm the market overview stats cache."""
    logger.info("Warming market overview cache...")
    start = time.time()

    # Clear existing cache to force refresh
    cache.delete("salary_market_overview:5:all")

    # Trigger cache population
    stats = get_market_overview_stats(years=5, program_filter="all")

    elapsed = time.time() - start
    logger.info(f"  Market overview cache warmed in {elapsed:.1f}s")

    if verbose:
        logger.info(f"    Total filings: {stats['basic'].get('total_filings', 'N/A'):,}")
        logger.info(f"    Median salary: ${stats['basic'].get('median_salary', 0):,.0f}")
        logger.info(f"    Top employers: {len(stats.get('top_employers', []))}")
        logger.info(f"    Top job titles: {len(stats.get('top_job_titles', []))}")


def warm_fiscal_years_cache(verbose: bool = False):
    """Warm the fiscal years cache."""
    logger.info("Warming fiscal years cache...")
    start = time.time()

    # Clear existing cache
    cache.delete('salary_fiscal_years')

    # Populate cache
    fiscal_years = list(
        SalaryRecord.objects
        .exclude(fiscal_year__isnull=True)
        .values_list('fiscal_year', flat=True)
        .distinct()
        .order_by('-fiscal_year')
    )
    cache.set('salary_fiscal_years', fiscal_years)

    elapsed = time.time() - start
    logger.info(f"  Fiscal years cache warmed in {elapsed:.1f}s")

    if verbose:
        logger.info(f"    Years: {fiscal_years}")


def warm_count_caches(verbose: bool = False):
    """Warm the record count caches."""
    logger.info("Warming count caches...")
    start = time.time()

    # Base queryset (non-worksite, non-unknown, with salary)
    base_qs = (
        SalaryRecord.objects
        .exclude(is_worksite=True)
        .exclude(employer_name='Unknown')
        .filter(wage_annual__isnull=False, wage_annual__gt=0)
    )

    # Total non-worksite count
    cache.delete('salary_non_worksite_count')
    total_count = base_qs.count()
    cache.set('salary_non_worksite_count', total_count)
    logger.info(f"  Total non-worksite count: {total_count:,}")

    # H1B count
    from models.enums.visa_program import VisaProgram
    cache.delete('salary_h1b_non_worksite_count')
    h1b_count = base_qs.filter(
        visa_program__in=[VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3]
    ).count()
    cache.set('salary_h1b_non_worksite_count', h1b_count)
    logger.info(f"  H1B non-worksite count: {h1b_count:,}")

    # PERM count
    cache.delete('salary_perm_non_worksite_count')
    perm_count = base_qs.filter(visa_program=VisaProgram.PERM).count()
    cache.set('salary_perm_non_worksite_count', perm_count)
    logger.info(f"  PERM non-worksite count: {perm_count:,}")

    # Has data flag
    cache.delete('salary_has_data')
    has_data = SalaryRecord.objects.exists()
    cache.set('salary_has_data', not has_data)

    elapsed = time.time() - start
    logger.info(f"  Count caches warmed in {elapsed:.1f}s")


def warm_directory_caches(verbose: bool = False):
    """Warm caches for directory pages."""
    logger.info("Warming directory caches...")
    start = time.time()

    # Top employers count
    top_employers_count = (
        EmployerCluster.objects
        .exclude(canonical_name="Unknown")
        .exclude(slug="unknown")
        .count()
    )
    logger.info(f"  Total employer clusters: {top_employers_count:,}")

    # Top job titles count
    top_job_titles_count = (
        JobTitleCluster.objects
        .exclude(canonical_title="Unknown")
        .count()
    )
    logger.info(f"  Total job title clusters: {top_job_titles_count:,}")

    elapsed = time.time() - start
    logger.info(f"  Directory caches warmed in {elapsed:.1f}s")


def warm_page_caches(base_url: str = "http://localhost:8000", verbose: bool = False):
    """Warm page-level caches by making HTTP requests."""
    import urllib.error
    import urllib.request

    logger.info("Warming page caches via HTTP requests...")
    start = time.time()

    pages = [
        "/salaries/",
        "/job-titles/",
        "/employers/",
    ]

    for page in pages:
        url = f"{base_url}{page}"
        try:
            page_start = time.time()
            req = urllib.request.Request(url, headers={'User-Agent': 'CacheWarmer/1.0'})
            with urllib.request.urlopen(req, timeout=60) as response:
                _ = response.read()  # Read full response to ensure cache is populated
                elapsed = time.time() - page_start
                logger.info(f"  {page}: {response.status} in {elapsed:.1f}s")
        except urllib.error.URLError as e:
            logger.warning(f"  {page}: Failed - {e}")
        except Exception as e:
            logger.warning(f"  {page}: Error - {e}")

    elapsed = time.time() - start
    logger.info(f"  Page caches warmed in {elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(description='Warm up Django cache')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed cache contents')
    parser.add_argument('--market-only', action='store_true',
                       help='Only warm market overview cache')
    parser.add_argument('--base-url', type=str, default='http://localhost:8000',
                       help='Base URL for page cache warming (default: http://localhost:8000)')
    parser.add_argument('--skip-pages', action='store_true',
                       help='Skip page-level cache warming (HTTP requests)')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    logger.info("=" * 60)
    logger.info("Cache Warming Started")
    logger.info("=" * 60)

    total_start = time.time()

    if args.market_only:
        warm_market_overview_cache(args.verbose)
    else:
        warm_market_overview_cache(args.verbose)
        warm_fiscal_years_cache(args.verbose)
        warm_count_caches(args.verbose)
        warm_directory_caches(args.verbose)

        # Warm page caches via HTTP requests (optional)
        if not args.skip_pages:
            warm_page_caches(args.base_url, args.verbose)

    total_elapsed = time.time() - total_start
    logger.info("=" * 60)
    logger.info(f"Cache Warming Complete in {total_elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
