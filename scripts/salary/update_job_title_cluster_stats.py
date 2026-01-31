#!/usr/bin/env python3
"""
Update JobTitleCluster aggregated statistics (total_filings, avg_salary).

This script calculates statistics from linked SalaryRecords for each cluster.

Usage:
    bazel run //scripts/salary:update_job_title_cluster_stats
    bazel run //scripts/salary:update_job_title_cluster_stats -- --dry-run
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

import argparse
import logging
from django.db.models import Count, Avg
from models.job_title import JobTitleCluster, JobTitle
from models.salary import SalaryRecord
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

setup_logging()
script_logger = ScriptLogger(__file__)
logger = logging.getLogger(__name__)

# Salary bounds for filtering out absurd values (same as job_title_stats.py)
MIN_REASONABLE_SALARY = 30000  # $30k/year minimum
MAX_REASONABLE_SALARY = 1000000  # $1M/year maximum


def main():
    parser = argparse.ArgumentParser(description='Update JobTitleCluster aggregated statistics')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()
    
    script_logger.log_call(
        args={'dry_run': args.dry_run},
        context='Update JobTitleCluster aggregated statistics from SalaryRecords'
    )
    
    logger.info("Updating JobTitleCluster statistics...")
    logger.info("=" * 80)
    
    # Get all clusters
    clusters = JobTitleCluster.objects.all()
    total_clusters = clusters.count()
    
    logger.info("Total clusters to process: %s", f"{total_clusters:,}")
    
    if args.dry_run:
        logger.info("DRY RUN - Showing first 10 clusters that would be updated:")
        for cluster in clusters[:10]:
            job_titles = JobTitle.objects.filter(canonical_cluster=cluster)
            stats = SalaryRecord.objects.filter(
                job_title_entity__in=job_titles,
                wage_annual__isnull=False,
                wage_annual__gte=MIN_REASONABLE_SALARY,
                wage_annual__lte=MAX_REASONABLE_SALARY
            ).aggregate(
                total=Count('id'),
                avg_sal=Avg('wage_annual')
            )
            avg_sal_str = f"${stats['avg_sal']:,.0f}" if stats['avg_sal'] else "$0"
            logger.info("  %s: %s filings, %s avg", cluster.canonical_title, stats['total'], avg_sal_str)
        logger.info("... and %s more", max(0, total_clusters - 10))
        return
    
    # Update clusters in batches
    logger.info("Calculating and updating statistics...")
    
    collector = BatchedUpdateCollector(
        fields=['total_filings', 'avg_salary', 'canonical_title'],
        batch_size=500,
        dry_run=False,
        use_transaction=True
    )
    
    processed = 0
    updated = 0
    representative_updated = 0
    
    for cluster in clusters.iterator(chunk_size=500):
        # Get all job titles in this cluster
        job_titles = JobTitle.objects.filter(canonical_cluster=cluster)
        
        # Calculate statistics from salary records (with reasonable salary bounds)
        stats = SalaryRecord.objects.filter(
            job_title_entity__in=job_titles,
            wage_annual__isnull=False,
            wage_annual__gte=MIN_REASONABLE_SALARY,
            wage_annual__lte=MAX_REASONABLE_SALARY
        ).aggregate(
            total=Count('id'),
            avg_sal=Avg('wage_annual')
        )
        
        # Update cluster fields
        cluster.total_filings = stats['total'] or 0
        cluster.avg_salary = stats['avg_sal']
        
        # Update canonical_title to the most frequent job title in the cluster
        most_frequent = (
            job_titles
            .filter(total_filings__gt=0)
            .order_by('-total_filings')
            .values_list('title', flat=True)
            .first()
        )
        if most_frequent and most_frequent != cluster.canonical_title:
            cluster.canonical_title = most_frequent
            representative_updated += 1
        
        collector.add(cluster)
        processed += 1
        
        if stats['total'] and stats['total'] > 0:
            updated += 1
        
        if processed % 1000 == 0:
            logger.info("  Processed %s/%s clusters (%s%%)", 
                       f"{processed:,}", f"{total_clusters:,}", 
                       f"{(processed/total_clusters*100):.1f}")
    
    collector.flush()
    
    logger.info("Successfully processed %s clusters", f"{processed:,}")
    logger.info("   Updated %s clusters with non-zero filings", f"{updated:,}")
    logger.info("   %s clusters have no linked salary records", f"{processed - updated:,}")
    logger.info("   Updated %s cluster representatives to most frequent title", f"{representative_updated:,}")


if __name__ == '__main__':
    main()
