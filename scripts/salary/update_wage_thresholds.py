#!/usr/bin/env python3
"""
Update wage thresholds based on recent data distributions.

This script:
1. Loads salary records from last N fiscal years
2. Converts all wages to annual (WITHOUT unit correction first)
3. Filters out obvious errors (<$5K, >$5M)
4. Calculates statistics (mean, std, percentiles)
5. Computes 4σ range (mean ± 4×std) for unified min/max thresholds
6. Updates wage_thresholds_config.yaml

Usage:
    bazel run //scripts/salary:update_wage_thresholds
    bazel run //scripts/salary:update_wage_thresholds -- --dry-run
    bazel run //scripts/salary:update_wage_thresholds -- --fiscal-years 3
"""

import argparse
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    yaml = None

try:
    import numpy as np
except ImportError:
    np = None

# Setup Django
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django.db.models import Q
from models.salary import SalaryRecord
from models.enums.visa_program import WageUnit
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)

# Use BUILD_WORKSPACE_DIRECTORY to write to actual workspace (not Bazel sandbox)
WORKSPACE_DIR = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', Path(__file__).parent.parent.parent))
CONFIG_PATH = WORKSPACE_DIR / 'lib' / 'parsing' / 'salary' / 'wage_thresholds_config.yaml'

# Conversion factors
HOURS_PER_YEAR = 2080
WEEKS_PER_YEAR = 52
BI_WEEKS_PER_YEAR = 26
MONTHS_PER_YEAR = 12

# Filter bounds for obvious errors
MIN_FILTER = 5000
MAX_FILTER = 5000000


def convert_to_annual(wage_from: Decimal, wage_unit: str) -> float | None:
    """Convert wage_from to annual WITHOUT unit correction."""
    if not wage_from:
        return None
    
    multipliers = {
        WageUnit.YEAR: 1,
        WageUnit.MONTH: MONTHS_PER_YEAR,
        WageUnit.BI_WEEKLY: BI_WEEKS_PER_YEAR,
        WageUnit.WEEK: WEEKS_PER_YEAR,
        WageUnit.HOUR: HOURS_PER_YEAR,
    }
    
    multiplier = multipliers.get(wage_unit, 1)
    return float(wage_from) * multiplier


def get_recent_fiscal_years(num_years: int = 2) -> list[int]:
    """Get the most recent N fiscal years from the database."""
    fiscal_years = (
        SalaryRecord.objects
        .values_list('fiscal_year', flat=True)
        .distinct()
        .order_by('-fiscal_year')
    )
    return list(fiscal_years[:num_years])


def calculate_thresholds(fiscal_years=2):
    """
    Calculate unified wage thresholds from recent data using 4σ range.
    
    Strategy:
    1. Load records from recent fiscal years
    2. Convert wages to annual WITHOUT unit correction
    3. Filter out obvious errors (<$5K, >$5M)
    4. Calculate mean and std
    5. Use 4σ range (mean ± 4×std) for min/max thresholds
    
    Args:
        fiscal_years: Number of recent fiscal years to analyze
    
    Returns:
        dict with calculated thresholds
    """
    if np is None:
        raise RuntimeError("NumPy is required. Install with: pip install numpy")
    
    logger.info(f"Calculating thresholds from last {fiscal_years} fiscal years...")
    logger.info("")
    
    # Get recent fiscal years
    recent_years = get_recent_fiscal_years(fiscal_years)
    logger.info(f"Using fiscal years: {recent_years}")
    logger.info("")
    
    # Load records with non-null wage_from
    records = SalaryRecord.objects.filter(
        fiscal_year__in=recent_years,
        wage_from__isnull=False,
        wage_unit__isnull=False
    )
    
    total_records = records.count()
    logger.info(f"Total records with wage_from: {total_records:,}")
    
    if total_records < 1000:
        logger.warning(f"Only {total_records} records found - thresholds may not be reliable")
    
    # Convert all wages to annual (WITHOUT unit correction)
    logger.info("Converting wages to annual (without unit correction)...")
    annual_wages = []
    for record in records.iterator(chunk_size=10000):
        annual = convert_to_annual(record.wage_from, record.wage_unit)
        if annual is not None:
            annual_wages.append(annual)
    
    logger.info(f"Converted {len(annual_wages):,} wages to annual")
    logger.info("")
    
    # Filter out obvious errors
    logger.info(f"Filtering out wages < ${MIN_FILTER:,} or > ${MAX_FILTER:,}...")
    filtered_wages = [w for w in annual_wages if MIN_FILTER <= w <= MAX_FILTER]
    
    removed = len(annual_wages) - len(filtered_wages)
    removed_pct = (removed / len(annual_wages) * 100) if annual_wages else 0
    logger.info(f"Removed {removed:,} records ({removed_pct:.2f}%)")
    logger.info(f"Remaining: {len(filtered_wages):,} records")
    logger.info("")
    
    if not filtered_wages:
        logger.error("No valid wage data after filtering!")
        return {}
    
    # Calculate statistics
    wages_array = np.array(filtered_wages)
    mean = float(np.mean(wages_array))
    std = float(np.std(wages_array))
    median = float(np.median(wages_array))
    
    # Calculate percentiles (for reference)
    p1 = float(np.percentile(wages_array, 1))
    p5 = float(np.percentile(wages_array, 5))
    p50 = float(np.percentile(wages_array, 50))
    p95 = float(np.percentile(wages_array, 95))
    p99 = float(np.percentile(wages_array, 99))
    
    # Calculate 4σ range (captures ~99.99% of data)
    min_threshold = max(MIN_FILTER, int(mean - 4 * std))
    max_threshold = min(MAX_FILTER, int(mean + 4 * std))
    
    logger.info("STATISTICS:")
    logger.info(f"  Mean:   ${mean:,.2f}")
    logger.info(f"  Std:    ${std:,.2f}")
    logger.info(f"  Median: ${median:,.2f}")
    logger.info(f"  Count:  {len(filtered_wages):,}")
    logger.info("")
    
    logger.info("PERCENTILES (for reference):")
    logger.info(f"  p1:  ${p1:,.2f}")
    logger.info(f"  p5:  ${p5:,.2f}")
    logger.info(f"  p50: ${p50:,.2f}")
    logger.info(f"  p95: ${p95:,.2f}")
    logger.info(f"  p99: ${p99:,.2f}")
    logger.info("")
    
    logger.info("4σ RANGE (mean ± 4×std):")
    logger.info(f"  Min: ${min_threshold:,}")
    logger.info(f"  Max: ${max_threshold:,}")
    logger.info(f"  Coverage: ~99.99% of data")
    logger.info("")
    
    return {
        'min_threshold': min_threshold,
        'max_threshold': max_threshold,
        'mean': mean,
        'std': std,
        'median': median,
        'count': len(filtered_wages),
        'percentiles': {
            'p1': round(p1, 2),
            'p5': round(p5, 2),
            'p50': round(p50, 2),
            'p95': round(p95, 2),
            'p99': round(p99, 2),
        },
        'fiscal_years': recent_years,
    }


def update_config(thresholds, fiscal_years):
    """Update the config file with new thresholds."""
    if yaml is None:
        logger.error("PyYAML not installed. Install with: pip install pyyaml")
        raise RuntimeError("PyYAML is required for updating wage thresholds config")
    
    # Prepare config data (new unified format)
    config_data = {
        '_last_updated': datetime.now().strftime('%Y-%m-%d'),
        '_source': f'Calculated from salary data distributions (without unit correction, filtered <{MIN_FILTER}, >{MAX_FILTER})',
        'annual_wage_range': {
            'min': thresholds['min_threshold'],
            'max': thresholds['max_threshold'],
        },
        'percentiles': thresholds['percentiles'],
        'calculation_method': {
            'min_threshold': 'max(MIN_FILTER, mean - 4*std)',
            'max_threshold': 'min(MAX_FILTER, mean + 4*std)',
            'coverage': '~99.99% (4σ)',
        },
        'statistics': {
            'mean': round(thresholds['mean'], 2),
            'std': round(thresholds['std'], 2),
            'median': round(thresholds['median'], 2),
            'count': thresholds['count'],
            'fiscal_years': thresholds['fiscal_years'],
        },
    }
    
    # Write config file
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
    
    logger.info(f"✅ Updated config file: {CONFIG_PATH}")
    logger.info(f"  Min threshold: ${config_data['annual_wage_range']['min']:,}")
    logger.info(f"  Max threshold: ${config_data['annual_wage_range']['max']:,}")


def main():
    parser = argparse.ArgumentParser(
        description='Update wage thresholds from recent data distributions (unified 4σ approach)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Update using last 2 fiscal years (default):
    bazel run //scripts/salary:update_wage_thresholds
  
  Dry-run to see what would be calculated:
    bazel run //scripts/salary:update_wage_thresholds -- --dry-run
  
  Use last 3 fiscal years:
    bazel run //scripts/salary:update_wage_thresholds -- --fiscal-years 3
        """
    )
    
    parser.add_argument(
        '--fiscal-years',
        type=int,
        default=2,
        help='Number of recent fiscal years to analyze (default: 2)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Calculate thresholds but do not update config file'
    )
    
    args = parser.parse_args()
    
    script_logger.log_call(
        args={
            'fiscal_years': args.fiscal_years,
            'dry_run': args.dry_run,
        },
        context='Updating wage thresholds using unified 4σ approach'
    )
    
    logger.info("=" * 80)
    logger.info("UPDATING WAGE THRESHOLDS (UNIFIED 4σ APPROACH)")
    logger.info("=" * 80)
    logger.info("")
    
    thresholds = calculate_thresholds(fiscal_years=args.fiscal_years)
    
    if not thresholds:
        logger.error("Failed to calculate thresholds")
        return
    
    logger.info("")
    if args.dry_run:
        logger.info("DRY-RUN: Config file would be updated with:")
        logger.info(yaml.dump({
            'annual_wage_range': {
                'min': thresholds['min_threshold'],
                'max': thresholds['max_threshold'],
            },
        }, default_flow_style=False))
    else:
        update_config(thresholds, args.fiscal_years)
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Review the updated thresholds")
        logger.info("  2. Run tests to verify: bazel test //tests:...")
        logger.info("  3. Commit the updated config file")


if __name__ == '__main__':
    main()









