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
from django.db.models import Count, Avg
from models.job_title import JobTitleCluster, JobTitle
from models.salary import SalaryRecord
from lib.utils.db_utils import BatchedUpdateCollector
from lib.utils.logging_utils import ScriptLogger

logger = ScriptLogger(__file__)

# Salary bounds for filtering out absurd values (same as job_title_stats.py)
MIN_REASONABLE_SALARY = 30000  # $30k/year minimum
MAX_REASONABLE_SALARY = 1000000  # $1M/year maximum


def main():
    parser = argparse.ArgumentParser(description='Update JobTitleCluster aggregated statistics')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()
    
    logger.log_call(
        args={'dry_run': args.dry_run},
        context='Update JobTitleCluster aggregated statistics from SalaryRecords'
    )
    
    print("Updating JobTitleCluster statistics...")
    print("=" * 80)
    
    # Get all clusters
    clusters = JobTitleCluster.objects.all()
    total_clusters = clusters.count()
    
    print(f"Total clusters to process: {total_clusters:,}")
    
    if args.dry_run:
        print("\n🔍 DRY RUN - Showing first 10 clusters that would be updated:")
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
            print(f"  {cluster.canonical_title}: {stats['total']} filings, {avg_sal_str} avg")
        print(f"\n... and {max(0, total_clusters - 10)} more")
        return
    
    # Update clusters in batches
    print("\n📝 Calculating and updating statistics...")
    
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
            print(f"  Processed {processed:,}/{total_clusters:,} clusters...")
    
    collector.flush()
    
    print(f"\n✅ Successfully processed {processed:,} clusters")
    print(f"   Updated {updated:,} clusters with non-zero filings")
    print(f"   {processed - updated:,} clusters have no linked salary records")
    print(f"   Updated {representative_updated:,} cluster representatives to most frequent title")


if __name__ == '__main__':
    main()
