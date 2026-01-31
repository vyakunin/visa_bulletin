#!/usr/bin/env python3
"""
Update Employer aggregated statistics (total_lca_count, total_perm_count, avg_salary).

This script calculates statistics from SalaryRecords for each Employer.
These stats are then summed by cluster_existing_employers to populate EmployerCluster stats.

Usage:
    bazel run //scripts/salary:update_employer_stats
    bazel run //scripts/salary:update_employer_stats -- --dry-run
"""

import os
import logging
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

import argparse
from django.db.models import Count, Avg
from models.salary import Employer, SalaryRecord
from models.enums.visa_program import VisaProgram
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger

script_logger = ScriptLogger(__file__)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Update Employer aggregated statistics')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()
    
    script_logger.log_call(
        args={'dry_run': args.dry_run},
        context='Update Employer aggregated statistics from SalaryRecords'
    )
    
    logger.info("Updating Employer statistics...")
    logger.info("=" * 80)
    
    total_employers = Employer.objects.count()
    logger.info(f"Total employers to process: {total_employers:,}")
    
    if args.dry_run:
        logger.info("DRY RUN - Showing sample of what would be updated:")
        
        # Show LCA counts sample
        lca_counts = (
            SalaryRecord.objects
            .filter(visa_program__in=[VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3])
            .values('employer_id', 'employer__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        logger.info("Top 10 employers by LCA count:")
        for item in lca_counts:
            logger.info(f"  {item['employer__name']}: {item['count']} LCA filings")
        
        # Show PERM counts sample
        perm_counts = (
            SalaryRecord.objects
            .filter(visa_program=VisaProgram.PERM)
            .values('employer_id', 'employer__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        logger.info("Top 10 employers by PERM count:")
        for item in perm_counts:
            logger.info(f"  {item['employer__name']}: {item['count']} PERM filings")
        
        return
    
    # Update LCA counts
    logger.info("Updating LCA counts...")
    lca_counts = (
        SalaryRecord.objects
        .filter(visa_program__in=[VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3])
        .values('employer_id')
        .annotate(count=Count('id'))
    )
    
    lca_collector = BatchedUpdateCollector(
        fields=['total_lca_count'],
        batch_size=1000,
        dry_run=False,
        use_transaction=True
    )
    
    lca_updated = 0
    for item in lca_counts:
        if item['employer_id']:
            try:
                employer = Employer.objects.get(id=item['employer_id'])
                employer.total_lca_count = item['count']
                lca_collector.add(employer)
                lca_updated += 1
            except Employer.DoesNotExist:
                pass
    
    lca_collector.flush()
    logger.info(f"Updated LCA counts for {lca_updated:,} employers")
    
    # Update PERM counts
    logger.info("Updating PERM counts...")
    perm_counts = (
        SalaryRecord.objects
        .filter(visa_program=VisaProgram.PERM)
        .values('employer_id')
        .annotate(count=Count('id'))
    )
    
    perm_collector = BatchedUpdateCollector(
        fields=['total_perm_count'],
        batch_size=1000,
        dry_run=False,
        use_transaction=True
    )
    
    perm_updated = 0
    for item in perm_counts:
        if item['employer_id']:
            try:
                employer = Employer.objects.get(id=item['employer_id'])
                employer.total_perm_count = item['count']
                perm_collector.add(employer)
                perm_updated += 1
            except Employer.DoesNotExist:
                pass
    
    perm_collector.flush()
    logger.info(f"Updated PERM counts for {perm_updated:,} employers")
    
    # Update average salary
    logger.info("Updating average salaries...")
    avg_salaries = (
        SalaryRecord.objects
        .filter(wage_annual__isnull=False, wage_annual__gt=0)
        .values('employer_id')
        .annotate(avg=Avg('wage_annual'))
    )
    
    salary_collector = BatchedUpdateCollector(
        fields=['avg_salary'],
        batch_size=1000,
        dry_run=False,
        use_transaction=True
    )
    
    salary_updated = 0
    for item in avg_salaries:
        if item['employer_id']:
            try:
                employer = Employer.objects.get(id=item['employer_id'])
                employer.avg_salary = item['avg']
                salary_collector.add(employer)
                salary_updated += 1
            except Employer.DoesNotExist:
                pass
    
    salary_collector.flush()
    logger.info(f"Updated average salaries for {salary_updated:,} employers")
    
    logger.info("=" * 80)
    logger.info("Employer statistics updated successfully!")
    logger.info(f"  LCA counts: {lca_updated:,} employers")
    logger.info(f"  PERM counts: {perm_updated:,} employers")
    logger.info(f"  Avg salaries: {salary_updated:,} employers")


if __name__ == '__main__':
    main()
