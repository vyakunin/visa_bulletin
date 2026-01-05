#!/usr/bin/env python3
"""
Reset employer clustering - remove all clustering information.

This script:
- Removes canonical_cluster FK from all Employer records (sets to NULL)
- Deletes all EmployerCluster records
- Deletes all EmployerClusteringReview records (optional)

After running this, you can run cluster_existing_employers.py to re-cluster from scratch.

Usage:
    bazel run //scripts/salary:reset_clustering
    bazel run //scripts/salary:reset_clustering -- --force  # Skip confirmation
    bazel run //scripts/salary:reset_clustering -- --keep-reviews  # Keep review queue
"""

import argparse
import logging
import os
import sys
from django.db import transaction

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from models.salary import Employer, EmployerCluster, EmployerClusteringReview
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def reset_clustering(keep_reviews: bool = False) -> dict:
    """
    Reset all clustering information.
    
    Args:
        keep_reviews: If True, keep EmployerClusteringReview records
    
    Returns:
        Dictionary with counts of what was reset
    """
    results = {
        'employers_reset': 0,
        'clusters_deleted': 0,
        'reviews_deleted': 0,
    }
    
    # Count before reset
    clustered_employers = Employer.objects.filter(canonical_cluster__isnull=False).count()
    total_clusters = EmployerCluster.objects.count()
    total_reviews = EmployerClusteringReview.objects.count()
    
    logger.info(f"Current state:")
    logger.info(f"  Clustered employers: {clustered_employers:,}")
    logger.info(f"  Total clusters: {total_clusters:,}")
    if not keep_reviews:
        logger.info(f"  Review queue entries: {total_reviews:,}")
    
    # Reset employer cluster assignments
    logger.info("\nResetting employer cluster assignments...")
    updated = Employer.objects.filter(canonical_cluster__isnull=False).update(canonical_cluster=None)
    results['employers_reset'] = updated
    logger.info(f"  Reset {updated:,} employer cluster assignments")
    
    # Delete clusters
    logger.info("\nDeleting employer clusters...")
    deleted_clusters, _ = EmployerCluster.objects.all().delete()
    results['clusters_deleted'] = deleted_clusters
    logger.info(f"  Deleted {deleted_clusters:,} clusters")
    
    # Delete reviews (optional)
    if not keep_reviews:
        logger.info("\nDeleting review queue...")
        deleted_reviews, _ = EmployerClusteringReview.objects.all().delete()
        results['reviews_deleted'] = deleted_reviews
        logger.info(f"  Deleted {deleted_reviews:,} review queue entries")
    else:
        logger.info("\nKeeping review queue entries (--keep-reviews)")
    
    # Verify reset
    remaining_clustered = Employer.objects.filter(canonical_cluster__isnull=False).count()
    remaining_clusters = EmployerCluster.objects.count()
    
    logger.info("\n" + "="*60)
    logger.info("Reset complete!")
    logger.info("="*60)
    logger.info(f"  Employers reset: {results['employers_reset']:,}")
    logger.info(f"  Clusters deleted: {results['clusters_deleted']:,}")
    if not keep_reviews:
        logger.info(f"  Reviews deleted: {results['reviews_deleted']:,}")
    logger.info("")
    logger.info("Verification:")
    logger.info(f"  Remaining clustered employers: {remaining_clustered:,} (should be 0)")
    logger.info(f"  Remaining clusters: {remaining_clusters:,} (should be 0)")
    
    if remaining_clustered > 0 or remaining_clusters > 0:
        logger.warning("⚠️  Warning: Some clustering data remains!")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Reset employer clustering - remove all clustering information',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Reset clustering (with confirmation):
    bazel run //scripts/salary:reset_clustering
  
  Reset without confirmation:
    bazel run //scripts/salary:reset_clustering -- --force
  
  Reset but keep review queue:
    bazel run //scripts/salary:reset_clustering -- --keep-reviews

After resetting, run clustering:
    bazel run //scripts/salary:cluster_existing_employers

WARNING: This operation cannot be undone!
        """
    )
    
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Skip confirmation prompt (use with caution)'
    )
    
    parser.add_argument(
        '--keep-reviews',
        action='store_true',
        help='Keep EmployerClusteringReview records (only reset cluster assignments)'
    )
    
    args = parser.parse_args()
    
    # Log script execution
    script_logger.log_call(
        args={'force': args.force, 'keep_reviews': args.keep_reviews},
        context='Resetting employer clustering'
    )
    
    # Get counts before reset
    clustered_count = Employer.objects.filter(canonical_cluster__isnull=False).count()
    cluster_count = EmployerCluster.objects.count()
    review_count = EmployerClusteringReview.objects.count()
    
    logger.info("="*60)
    logger.info("Reset Employer Clustering")
    logger.info("="*60)
    logger.info(f"Current state:")
    logger.info(f"  Clustered employers: {clustered_count:,}")
    logger.info(f"  Total clusters: {cluster_count:,}")
    if not args.keep_reviews:
        logger.info(f"  Review queue entries: {review_count:,}")
    logger.info("")
    
    # Confirmation prompt
    if not args.force:
        warning_msg = "WARNING: This will remove ALL clustering information!"
        warning_msg += "\n  - All employer cluster assignments will be cleared"
        warning_msg += "\n  - All EmployerCluster records will be deleted"
        if not args.keep_reviews:
            warning_msg += "\n  - All EmployerClusteringReview records will be deleted"
        logger.warning(warning_msg)
        logger.warning("This operation cannot be undone.")
        response = input("Type 'yes' to continue: ")
        if response.lower() != 'yes':
            logger.info("Operation cancelled.")
            sys.exit(0)
    
    # Perform reset in transaction
    try:
        with transaction.atomic():
            results = reset_clustering(keep_reviews=args.keep_reviews)
        
        logger.info("")
        logger.info("✓ Clustering reset complete!")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  Run clustering:")
        logger.info("    bazel run //scripts/salary:cluster_existing_employers")
        
    except Exception as e:
        logger.error(f"Error during reset: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

