#!/usr/bin/env python3
"""
Backfill SalaryRecords with JobTitle entity links.

This links existing SalaryRecords to JobTitle entities based on exact job_title match.
This can be run independently of clustering.

Usage:
    bazel run //scripts/salary:backfill_job_title_links [--dry-run]
"""

import argparse
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from django.db import transaction
from models.salary import SalaryRecord
from models.job_title import JobTitle
from lib.utils.db_utils import BatchedUpdateCollector
from django_config.logging_config import setup_logging

setup_logging(debug=False)
import logging
logger = logging.getLogger(__name__)


def backfill_job_title_links(dry_run: bool = False):
    """Link SalaryRecords to JobTitle entities."""
    logger.info("="*80)
    logger.info("Backfilling SalaryRecords with JobTitle entity links...")
    logger.info("="*80)
    
    total_records = SalaryRecord.objects.count()
    already_linked = SalaryRecord.objects.filter(job_title_entity__isnull=False).count()
    unlinked_records = SalaryRecord.objects.filter(job_title_entity__isnull=True).count()
    
    logger.info(f"Total SalaryRecords: {total_records:,}")
    logger.info(f"Already linked: {already_linked:,}")
    logger.info(f"To link: {unlinked_records:,}")
    
    if unlinked_records == 0:
        logger.info("No unlinked records found. Skipping backfill.")
        return

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be saved")
    
    # Get all JobTitle entities indexed by title
    logger.info("Loading JobTitle entities...")
    job_titles_by_name = {}
    for jt in JobTitle.objects.all():
        job_titles_by_name[jt.title] = jt
    
    logger.info(f"Loaded {len(job_titles_by_name):,} JobTitle entities")
    
    # Process in batches
    collector = BatchedUpdateCollector(
        fields=['job_title_entity'],
        batch_size=1000,
        dry_run=dry_run,
        use_transaction=True
    )
    
    linked_count = 0
    not_found_count = 0
    
    # Process unlinked records
    logger.info("Processing unlinked SalaryRecords...")
    for i, record in enumerate(SalaryRecord.objects.filter(job_title_entity__isnull=True).iterator(chunk_size=1000), 1):
        if record.job_title in job_titles_by_name:
            job_title = job_titles_by_name[record.job_title]
            record.job_title_entity = job_title
            collector.add(record)
            linked_count += 1
        else:
            not_found_count += 1
        
        if i % 10000 == 0:
            logger.info(f"Processed {i:,}/{unlinked_records:,} ({i*100.0/unlinked_records:.1f}%) - Linked: {linked_count:,}, Not found: {not_found_count:,}")
    
    # Flush remaining
    collector.flush()
    
    logger.info("\n" + "="*80)
    logger.info("SUMMARY:")
    logger.info(f"  Processed: {unlinked_records:,} unlinked records")
    logger.info(f"  Linked: {linked_count:,} ({linked_count*100.0/unlinked_records:.1f}%)")
    logger.info(f"  Not found: {not_found_count:,} ({not_found_count*100.0/unlinked_records:.1f}%)")
    if dry_run:
        logger.info("  NO CHANGES SAVED (dry run mode)")
    else:
        logger.info(f"  CHANGES SAVED: {collector.count:,} records updated")
    logger.info("="*80)
    
    # Update JobTitle statistics
    if not dry_run and linked_count > 0:
        logger.info("\nUpdating JobTitle statistics...")
        from django.db.models import Count, Avg
        from django.db import connection
        
        # Update total_filings for all affected JobTitles
        updated = 0
        for job_title in JobTitle.objects.all():
            count = SalaryRecord.objects.filter(job_title_entity=job_title).count()
            if job_title.total_filings != count:
                job_title.total_filings = count
                job_title.save(update_fields=['total_filings'])
                updated += 1
        
        logger.info(f"Updated statistics for {updated:,} JobTitle entities")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without saving')
    args = parser.parse_args()
    
    backfill_job_title_links(dry_run=args.dry_run)


if __name__ == '__main__':
    main()

