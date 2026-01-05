#!/usr/bin/env python3
"""
Clean up orphaned employers (employers with no salary records).

This script identifies employers that have no associated salary records and provides
options to either delete them or mark them for review.

Usage:
    bazel run //scripts/salary:cleanup_orphaned_employers -- --dry-run
    bazel run //scripts/salary:cleanup_orphaned_employers -- --delete
    bazel run //scripts/salary:cleanup_orphaned_employers -- --mark-inactive
"""

import argparse
import logging
import os
import sys

# Setup Django
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django.db.models import Count
from django.db import transaction

from models.salary import Employer, SalaryRecord
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)


def find_orphaned_employers():
    """Find employers with no salary records."""
    # Get all employers
    all_employers = Employer.objects.all()
    
    # Get employers that have salary records
    employers_with_records = (
        SalaryRecord.objects
        .values('employer_id')
        .distinct()
        .exclude(employer_id__isnull=True)
    )
    employer_ids_with_records = {e['employer_id'] for e in employers_with_records}
    
    # Find orphaned employers
    orphaned = all_employers.exclude(id__in=employer_ids_with_records)
    
    return orphaned


def analyze_orphaned_employers():
    """Analyze orphaned employers."""
    logger.info("Analyzing orphaned employers...")
    
    orphaned = find_orphaned_employers()
    total_orphaned = orphaned.count()
    total_employers = Employer.objects.count()
    
    logger.info(f"Total employers: {total_employers:,}")
    logger.info(f"Orphaned employers (no salary records): {total_orphaned:,}")
    logger.info(f"Percentage: {(total_orphaned / total_employers * 100) if total_employers > 0 else 0:.1f}%")
    logger.info("")
    
    if total_orphaned == 0:
        logger.info("No orphaned employers found")
        return {'total': 0, 'sample': []}
    
    # Show sample
    logger.info("Sample orphaned employers (first 20):")
    logger.info("-" * 80)
    sample = list(orphaned[:20])
    for i, employer in enumerate(sample, 1):
        logger.info(f"{i}. ID: {employer.id}, Name: {employer.name[:60]}")
        logger.info(f"   City: {employer.city}, State: {employer.state}")
    
    logger.info("")
    
    return {
        'total': total_orphaned,
        'total_employers': total_employers,
        'sample': sample,
    }


def cleanup_orphaned_employers(dry_run=False, delete=False, mark_inactive=False):
    """Clean up orphaned employers."""
    logger.info("=" * 80)
    logger.info("CLEANING UP ORPHANED EMPLOYERS")
    logger.info("=" * 80)
    if dry_run:
        logger.info("DRY-RUN MODE - No changes will be made")
    logger.info("")
    
    analysis = analyze_orphaned_employers()
    
    if analysis['total'] == 0:
        logger.info("No orphaned employers to clean up")
        return 0
    
    orphaned = find_orphaned_employers()
    
    if not delete and not mark_inactive:
        logger.info("No action specified. Use --delete or --mark-inactive to clean up.")
        logger.info("Or use --dry-run to see what would be cleaned up.")
        return 0
    
    if delete:
        logger.info(f"{'Would delete' if dry_run else 'Deleting'} {analysis['total']:,} orphaned employers...")
        logger.info("")
        
        if not dry_run:
            deleted_count = 0
            # Delete in batches to avoid memory issues
            batch_size = 1000
            for i in range(0, analysis['total'], batch_size):
                batch = orphaned[i:i+batch_size]
                with transaction.atomic():
                    count = batch.count()
                    batch.delete()
                    deleted_count += count
                    logger.info(f"  Deleted batch: {deleted_count:,} / {analysis['total']:,}")
            
            logger.info("")
            logger.info(f"✅ Deleted {deleted_count:,} orphaned employers")
            return deleted_count
        else:
            logger.info(f"[DRY-RUN] Would delete {analysis['total']:,} orphaned employers")
            return analysis['total']
    
    elif mark_inactive:
        # Check if Employer model has an 'active' or 'is_active' field
        # If not, we can't mark as inactive
        if not hasattr(Employer, 'active') and not hasattr(Employer, 'is_active'):
            logger.warning("Employer model doesn't have an 'active' or 'is_active' field")
            logger.warning("Cannot mark as inactive. Use --delete to remove instead.")
            return 0
        
        active_field = 'is_active' if hasattr(Employer, 'is_active') else 'active'
        logger.info(f"{'Would mark as inactive' if dry_run else 'Marking as inactive'} {analysis['total']:,} orphaned employers...")
        logger.info("")
        
        if not dry_run:
            updated_count = 0
            batch_size = 1000
            for i in range(0, analysis['total'], batch_size):
                batch = orphaned[i:i+batch_size]
                with transaction.atomic():
                    count = batch.update(**{active_field: False})
                    updated_count += count
                    logger.info(f"  Updated batch: {updated_count:,} / {analysis['total']:,}")
            
            logger.info("")
            logger.info(f"✅ Marked {updated_count:,} orphaned employers as inactive")
            return updated_count
        else:
            logger.info(f"[DRY-RUN] Would mark {analysis['total']:,} orphaned employers as inactive")
            return analysis['total']
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Clean up orphaned employers (no salary records)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Analyze orphaned employers:
    bazel run //scripts/salary:cleanup_orphaned_employers -- --dry-run
  
  Delete orphaned employers:
    bazel run //scripts/salary:cleanup_orphaned_employers -- --delete
  
  Mark orphaned employers as inactive (if model supports it):
    bazel run //scripts/salary:cleanup_orphaned_employers -- --mark-inactive
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be cleaned up without making changes'
    )
    
    parser.add_argument(
        '--delete',
        action='store_true',
        help='Delete orphaned employers (destructive - use with caution)'
    )
    
    parser.add_argument(
        '--mark-inactive',
        action='store_true',
        help='Mark orphaned employers as inactive (if model supports it)'
    )
    
    args = parser.parse_args()
    
    script_logger.log_call(
        args={
            'dry_run': args.dry_run,
            'delete': args.delete,
            'mark_inactive': args.mark_inactive,
        },
        context='Cleaning up orphaned employers'
    )
    
    cleanup_orphaned_employers(
        dry_run=args.dry_run,
        delete=args.delete,
        mark_inactive=args.mark_inactive
    )


if __name__ == '__main__':
    main()
