#!/usr/bin/env python3
"""
Fix job title normalization by re-normalizing all existing JobTitle records.

This script updates all JobTitle records to use the improved normalization logic
that deduplicates words.

Usage:
    bazel run //scripts/salary:fix_job_title_normalization [--dry-run]
"""

import argparse
import os

import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from django_config.logging_config import setup_logging
from models.job_title import JobTitle

setup_logging(debug=False)
import logging

logger = logging.getLogger(__name__)


def renormalize_job_titles(dry_run: bool = False):
    """
    Re-normalize all job titles using updated logic.
    
    Strategy: Delete all JobTitle records and recreate them from SalaryRecords.
    This automatically handles merging duplicates.
    """
    logger.info("="*80)
    logger.info("Re-normalizing all job titles with improved logic...")
    logger.info("="*80)

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be saved")
        logger.info("Would clear SalaryRecord.job_title_entity and recreate JobTitle records")

        # Show examples of what would change
        sample_count = 0
        for job_title in JobTitle.objects.all()[:50]:
            old_normalized = job_title.title_normalized
            new_normalized = JobTitle.normalize_title(job_title.title)
            if old_normalized != new_normalized and sample_count < 20:
                sample_count += 1
                logger.info("\nExample change:")
                logger.info(f"  Title: '{job_title.title}'")
                logger.info(f"  Old: '{old_normalized}'")
                logger.info(f"  New: '{new_normalized}'")

        logger.info(f"\nTotal JobTitle records: {JobTitle.objects.count():,}")
        logger.info("DRY RUN - No changes made")
        return

    # Clear references to allow JobTitle deletion
    from models.salary import SalaryRecord

    logger.info("Clearing SalaryRecord.job_title_entity references...")
    SalaryRecord.objects.update(job_title_entity=None)
    logger.info("✓ Cleared SalaryRecord.job_title_entity references")

    # Delete all JobTitle records
    old_count = JobTitle.objects.count()
    logger.info(f"Deleting {old_count:,} old JobTitle records...")
    JobTitle.objects.all().delete()
    logger.info("✓ Deleted all JobTitle records")

    # Get unique (title, experience_level) pairs from SalaryRecords
    logger.info("Finding unique job titles from SalaryRecords...")
    from django.db.models import Count

    # Get distinct job titles
    unique_titles = (
        SalaryRecord.objects
        .values('job_title')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    logger.info(f"Found {len(unique_titles):,} unique job titles")

    # Create new JobTitle records with improved normalization
    logger.info("Creating JobTitle records with improved normalization...")
    new_titles = []
    seen = set()  # Track (normalized, level) to avoid duplicates

    for i, title_data in enumerate(unique_titles, 1):
        title = title_data['job_title']
        if not title:
            continue

        normalized = JobTitle.normalize_title(title)
        level = JobTitle.extract_experience_level(title)

        key = (normalized, level or '')
        if key not in seen:
            seen.add(key)
            new_titles.append(JobTitle(
                title=title,
                title_normalized=normalized,
                experience_level=level or ''
            ))

        if i % 10000 == 0:
            logger.info(f"Processed {i:,}/{len(unique_titles):,} ({i*100.0/len(unique_titles):.1f}%)")

    logger.info(f"Creating {len(new_titles):,} new JobTitle records...")
    JobTitle.objects.bulk_create(new_titles, batch_size=1000)

    new_count = JobTitle.objects.count()

    logger.info("\n" + "="*80)
    logger.info("SUMMARY:")
    logger.info(f"  Old JobTitle count: {old_count:,}")
    logger.info(f"  New JobTitle count: {new_count:,}")
    logger.info(f"  Difference: {new_count - old_count:+,} ({(new_count - old_count)*100.0/old_count:+.1f}%)")
    logger.info("  ✓ Re-normalization complete!")
    logger.info("="*80)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without saving')
    args = parser.parse_args()

    renormalize_job_titles(dry_run=args.dry_run)

    if not args.dry_run:
        logger.info("\n✅ Re-normalization complete! Run analysis script to verify:")
        logger.info("   bazel run //scripts/salary:analyze_job_title_normalization")


if __name__ == '__main__':
    main()

