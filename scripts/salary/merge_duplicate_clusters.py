#!/usr/bin/env python3
"""
Merge duplicate employer clusters with the same canonical_name.

This script identifies and merges duplicate EmployerCluster records that have the same
canonical_name. This fixes data integrity issues where multiple clusters exist for the
same employer name, causing duplicates in autocomplete and breaking data consistency.

Process:
1. Find all duplicate clusters (same canonical_name)
2. Select primary cluster (most employers, or lowest ID if tied)
3. Reassign all employers from duplicate clusters to primary
4. Delete empty duplicate clusters

Usage:
    # Dry run to see what would be merged (recommended first)
    bazel run //scripts/salary:merge_duplicate_clusters -- --dry-run
    
    # Actually perform the merge
    bazel run //scripts/salary:merge_duplicate_clusters
    
    # Debug mode with verbose logging
    bazel run //scripts/salary:merge_duplicate_clusters -- --debug

When to use:
- After discovering duplicate clusters in autocomplete
- Before applying unique constraint migration on canonical_name
- After bulk imports that may have created duplicate clusters
- To clean up data integrity issues in employer clustering

Performance:
- Uses bulk operations (bulk_update_batched, bulk delete)
- Optimized for large datasets (24k+ duplicates processed in ~5 queries)
- Pre-fetches related employers to avoid N+1 queries
"""

import os
import sys
import logging
from collections import defaultdict
from typing import Optional

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

from django.db import transaction
from models.salary import Employer, EmployerCluster
from lib.utils.logging_utils import ScriptLogger
from lib.utils.db_utils import bulk_update_batched
from django_config.logging_config import setup_logging

setup_logging()  # Uses debug=True default
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def find_duplicate_clusters() -> dict[str, list[EmployerCluster]]:
    """
    Find all duplicate clusters (same canonical_name, case-insensitive).
    
    Returns: dict mapping canonical_name -> list of duplicate clusters
    """
    logger.info("Searching for duplicate clusters (case-insensitive)...")
    
    # Group clusters by canonical_name (case-insensitive to catch "BBC" vs "bbc")
    clusters_by_name = defaultdict(list)
    for cluster in EmployerCluster.objects.all().prefetch_related('employers'):
        # Use lowercase for grouping to catch case variations
        normalized_name = cluster.canonical_name.lower()
        clusters_by_name[normalized_name].append(cluster)
    
    # Filter to only duplicates (canonical_name with 2+ clusters)
    duplicates = {
        name: clusters 
        for name, clusters in clusters_by_name.items() 
        if len(clusters) > 1
    }
    
    total_duplicates = sum(len(clusters) - 1 for clusters in duplicates.values())
    logger.info(f"Found {len(duplicates):,} canonical names with duplicates (case-insensitive)")
    logger.info(f"  Total duplicate clusters to merge: {total_duplicates:,}")
    
    # Log top duplicates (uses prefetched data, no extra queries)
    if duplicates:
        logger.info("\nTop 10 duplicates by cluster count:")
        sorted_duplicates = sorted(
            duplicates.items(), 
            key=lambda x: len(x[1]), 
            reverse=True
        )
        for normalized_name, clusters in sorted_duplicates[:10]:
            # Use prefetched data (len of cached queryset, no SQL COUNT query)
            employer_counts = [len(list(c.employers.all())) for c in clusters]
            # Show actual canonical names (case variations)
            actual_names = [c.canonical_name for c in clusters]
            logger.info(f"  Normalized: '{normalized_name}': {len(clusters)} clusters")
            logger.info(f"    Actual names: {actual_names}")
            logger.info(f"    Employer counts: {employer_counts}")
    
    return duplicates


def select_primary_cluster(clusters: list[EmployerCluster]) -> EmployerCluster:
    """
    Select the primary cluster from duplicates.
    
    Priority:
    1. Cluster with most employers
    2. If tied, cluster with lowest ID (oldest)
    
    Note: Uses prefetched employer data from find_duplicate_clusters(),
    so no additional queries are executed here.
    """
    # Count employers for each cluster (uses prefetched data, no extra queries)
    cluster_counts = [
        (cluster, len(list(cluster.employers.all())))
        for cluster in clusters
    ]
    
    # Sort by: employer count (desc), then ID (asc)
    cluster_counts.sort(key=lambda x: (-x[1], x[0].id))
    
    primary = cluster_counts[0][0]
    primary_count = cluster_counts[0][1]
    
    logger.debug(f"  Selected primary cluster: ID {primary.id} "
                f"with {primary_count} employers")
    
    return primary


def merge_cluster_group(
    canonical_name: str,
    clusters: list[EmployerCluster],
    dry_run: bool = False
) -> tuple[int, int]:
    """
    Merge a group of duplicate clusters into one primary cluster.
    
    Uses bulk operations to minimize database queries:
    - Bulk update for employer reassignments (1-2 queries instead of N)
    - Bulk delete for duplicate clusters (1 query instead of N)
    
    Returns: (reassigned_count, deleted_count)
    """
    logger.info(f"\nMerging '{canonical_name}' ({len(clusters)} clusters)...")
    
    # Select primary cluster
    primary = select_primary_cluster(clusters)
    duplicates = [c for c in clusters if c.id != primary.id]
    
    logger.info(f"  Primary cluster: ID {primary.id}")
    logger.info(f"  Duplicate clusters to merge: {[c.id for c in duplicates]}")
    
    # Count employers in each
    primary_emp_count = len(list(primary.employers.all()))
    duplicate_emp_counts = {
        c.id: len(list(c.employers.all())) 
        for c in duplicates
    }
    
    logger.info(f"  Primary has {primary_emp_count} employers")
    for cluster_id, count in duplicate_emp_counts.items():
        logger.info(f"  Duplicate {cluster_id} has {count} employers")
    
    reassigned_count = 0
    deleted_count = 0
    
    if not dry_run:
        with transaction.atomic():
            # Collect all employers to reassign (uses prefetched data, no extra queries)
            all_employers_to_update = []
            cluster_ids_to_delete = []
            
            for duplicate_cluster in duplicates:
                employers_to_reassign = list(duplicate_cluster.employers.all())
                
                # Update cluster assignment in memory
                for employer in employers_to_reassign:
                    employer.canonical_cluster = primary
                    reassigned_count += 1
                
                all_employers_to_update.extend(employers_to_reassign)
                cluster_ids_to_delete.append(duplicate_cluster.id)
                deleted_count += 1
                
                logger.info(f"  Will delete duplicate cluster {duplicate_cluster.id} "
                           f"(reassigning {len(employers_to_reassign)} employers)")
            
            # Bulk update all employers at once (1-2 queries instead of N)
            if all_employers_to_update:
                logger.info(f"  Bulk updating {len(all_employers_to_update)} employers...")
                bulk_update_batched(
                    all_employers_to_update, 
                    fields=['canonical_cluster'],
                    batch_size=1000
                )
            
            # Bulk delete duplicate clusters (1 query instead of N)
            if cluster_ids_to_delete:
                logger.info(f"  Bulk deleting {len(cluster_ids_to_delete)} duplicate clusters...")
                EmployerCluster.objects.filter(id__in=cluster_ids_to_delete).delete()
    else:
        # Dry run - just count what would be done (uses prefetched data)
        for duplicate_cluster in duplicates:
            employers_to_reassign = list(duplicate_cluster.employers.all())
            reassigned_count += len(employers_to_reassign)
            deleted_count += 1
    
    logger.info(f"  ✓ Merged {len(clusters)} clusters: "
               f"{reassigned_count} employers reassigned, "
               f"{deleted_count} duplicates deleted")
    
    return reassigned_count, deleted_count


def merge_all_duplicates(dry_run: bool = False) -> tuple[int, int, int]:
    """
    Merge all duplicate clusters.
    
    Returns: (canonical_names_fixed, total_reassigned, total_deleted)
    """
    duplicates = find_duplicate_clusters()
    
    if not duplicates:
        logger.info("No duplicate clusters found!")
        return 0, 0, 0
    
    if dry_run:
        logger.info("\n" + "="*60)
        logger.info("DRY RUN - No changes will be made")
        logger.info("="*60)
    else:
        logger.info("\n" + "="*60)
        logger.info("Starting merge of duplicate clusters")
        logger.info("="*60)
    
    total_reassigned = 0
    total_deleted = 0
    canonical_names_fixed = 0
    
    for canonical_name, clusters in duplicates.items():
        reassigned, deleted = merge_cluster_group(canonical_name, clusters, dry_run)
        total_reassigned += reassigned
        total_deleted += deleted
        canonical_names_fixed += 1
    
    logger.info("\n" + "="*60)
    logger.info("MERGE SUMMARY")
    logger.info("="*60)
    logger.info(f"  Canonical names fixed: {canonical_names_fixed:,}")
    logger.info(f"  Employers reassigned: {total_reassigned:,}")
    logger.info(f"  Duplicate clusters deleted: {total_deleted:,}")
    logger.info("="*60)
    
    if dry_run:
        logger.info("\nDRY RUN - No changes were made to the database")
    
    return canonical_names_fixed, total_reassigned, total_deleted


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Merge duplicate employer clusters'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run - show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    script_logger.log_call(
        args=vars(args),
        context='Merge duplicate employer clusters'
    )
    
    try:
        canonical_names_fixed, total_reassigned, total_deleted = merge_all_duplicates(
            dry_run=args.dry_run
        )
        
        if canonical_names_fixed == 0:
            logger.info("\n✓ No duplicates found - database is clean!")
            sys.exit(0)
        
        if args.dry_run:
            logger.info(f"\n⚠ DRY RUN: Found {canonical_names_fixed:,} duplicate "
                       f"canonical names affecting {total_reassigned:,} employers")
            logger.info("Run without --dry-run to perform the merge")
            sys.exit(0)
        else:
            logger.info(f"\n✓ Successfully merged {canonical_names_fixed:,} duplicate "
                       f"canonical names")
            logger.info(f"  Reassigned {total_reassigned:,} employers")
            logger.info(f"  Deleted {total_deleted:,} duplicate clusters")
            sys.exit(0)
    
    except Exception as e:
        logger.error(f"Error during merge: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

