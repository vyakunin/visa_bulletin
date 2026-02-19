#!/usr/bin/env python3
"""
Cluster job titles using the generic clustering framework.

This script:
1. Extracts and normalizes job titles from SalaryRecord
2. Creates JobTitle entities with experience levels
3. Clusters similar job titles using the generic clustering engine
4. Links SalaryRecords to their JobTitle entities

Usage:
    bazel run //scripts/salary:cluster_job_titles

    # With dry run mode:
    bazel run //scripts/salary:cluster_job_titles -- --dry-run

When to use:
- After importing salary data to normalize and cluster job titles
- Periodically to refresh job title clustering
- Before analyzing job title trends or salary distributions
"""

import os
import sys

import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

import logging

from django_config.logging_config import setup_logging
from lib.business import clustering_engine
from lib.business.salary.job_title_config import JobTitleClusteringConfig
from lib.utils.logging_utils import ScriptLogger
from models.job_title import JobTitle
from models.salary import SalaryRecord

# Setup logging
setup_logging(debug=False)
logger = logging.getLogger(__name__)

# Script usage logging
script_logger = ScriptLogger(__file__)


def extract_or_create_job_title(job_title_str: str) -> JobTitle:
    """
    Extract or create JobTitle entity for a given job title string.
    
    Args:
        job_title_str: Raw job title from SalaryRecord
    
    Returns: JobTitle instance
    """
    if not job_title_str:
        return None

    # Normalize and extract experience level
    normalized = JobTitle.normalize_title(job_title_str)
    experience_level = JobTitle.extract_experience_level(job_title_str)

    # Get or create JobTitle entity
    job_title, created = JobTitle.objects.get_or_create(
        title_normalized=normalized,
        experience_level=experience_level,
        defaults={
            'title': job_title_str,
            'total_filings': 0,
        }
    )

    if created:
        logger.info(f"Created new JobTitle: '{job_title_str}' -> '{normalized}' ({experience_level or 'no level'})")

    return job_title


def cluster_job_titles(dry_run: bool = False):
    """
    Cluster all job titles using the generic clustering framework.
    
    Args:
        dry_run: If True, don't commit changes to database
    """
    config = JobTitleClusteringConfig()

    logger.info("=" * 80)
    logger.info("JOB TITLE CLUSTERING")
    logger.info("=" * 80)

    # Phase 1: Extract and normalize job titles from SalaryRecords
    logger.info("\n" + "=" * 80)
    logger.info("Phase 1: Extract and normalize job titles from SalaryRecords")
    logger.info("=" * 80)

    # Get all unique job titles from salary records
    unique_job_titles = SalaryRecord.objects.values_list('job_title', flat=True).distinct()
    total_unique = unique_job_titles.count()

    logger.info(f"Found {total_unique:,} unique job title strings")

    # Create JobTitle entities
    job_titles_created = 0
    job_titles_existing = 0

    for i, job_title_str in enumerate(unique_job_titles, 1):
        if i % 1000 == 0:
            logger.info(f"Processed {i:,}/{total_unique:,} job titles ({i/total_unique*100:.1f}%)")

        job_title = extract_or_create_job_title(job_title_str)
        if job_title:
            # Check if it was newly created
            if job_title.pk and JobTitle.objects.filter(pk=job_title.pk).exists():
                if job_title.total_filings == 0:
                    job_titles_created += 1
                else:
                    job_titles_existing += 1

    logger.info("\nPhase 1 complete:")
    logger.info(f"  - Created: {job_titles_created:,} new JobTitle entities")
    logger.info(f"  - Existing: {job_titles_existing:,} JobTitle entities")

    # Phase 2: Cluster job titles using generic framework
    logger.info("\n" + "=" * 80)
    logger.info("Phase 2: Cluster job titles")
    logger.info("=" * 80)

    all_job_titles = list(JobTitle.objects.select_related('canonical_cluster'))
    logger.info(f"Processing {len(all_job_titles):,} job titles...")

    bucket_index, normalized_cache, bucket_cache = clustering_engine.build_bucket_index(
        all_job_titles,
        config
    )

    auto_clustered = 0
    queued_for_review = 0
    new_clusters = 0

    for i, job_title in enumerate(all_job_titles, 1):
        if i % 100 == 0:
            logger.info(f"Processed {i:,}/{len(all_job_titles):,} job titles")

        if job_title.canonical_cluster:
            continue  # Already clustered

        # Use generic framework to assign to cluster
        cluster = clustering_engine.assign_to_cluster(
            job_title,
            config,
            auto_approve_threshold=0.95,
            bucket_index=bucket_index,
            normalized_cache=normalized_cache,
            bucket_cache=bucket_cache
        )

        if cluster:
            # Check if this was a new cluster
            if cluster.total_filings == 0:
                new_clusters += 1
            auto_clustered += 1

    logger.info("\nPhase 2 complete:")
    logger.info(f"  - Auto-clustered: {auto_clustered:,} job titles")
    logger.info(f"  - New clusters: {new_clusters:,}")

    # Phase 3: Link SalaryRecords to JobTitle entities
    logger.info("\n" + "=" * 80)
    logger.info("Phase 3: Link SalaryRecords to JobTitle entities")
    logger.info("=" * 80)

    if dry_run:
        logger.info("DRY RUN MODE: Skipping SalaryRecord linking")
    else:
        # Get total for progress logging
        total_job_titles = JobTitle.objects.count()
        logger.info(f"Total JobTitle entities to process: {total_job_titles:,}")

        linked_count = 0

        # Build a lightweight mapping of (normalized_title, experience_level) -> JobTitle ID
        # Using .values() to avoid loading full model objects into memory
        logger.info("Building JobTitle lookup index...")
        job_title_lookup = {}
        for jt_data in JobTitle.objects.values('id', 'title_normalized', 'experience_level'):
            key = (jt_data['title_normalized'], jt_data['experience_level'])
            job_title_lookup[key] = jt_data['id']

        logger.info(f"Built index with {len(job_title_lookup):,} JobTitle entities")

        # Process unlinked salary records in batches
        total_unlinked = SalaryRecord.objects.filter(job_title_entity__isnull=True).count()
        logger.info(f"Processing {total_unlinked:,} unlinked salary records...")

        processed_count = 0
        batch = []
        batch_size = 10000

        for record in SalaryRecord.objects.filter(job_title_entity__isnull=True).iterator(chunk_size=10000):
            # Normalize and extract experience level for this record
            normalized = JobTitle.normalize_title(record.job_title)
            experience_level = JobTitle.extract_experience_level(record.job_title)

            # Look up matching JobTitle entity ID
            key = (normalized, experience_level)
            if key in job_title_lookup:
                record.job_title_entity_id = job_title_lookup[key]  # Set ID directly, not full object
                batch.append(record)

                if len(batch) >= batch_size:
                    # Bulk update - use _id field name since we set the ID directly
                    SalaryRecord.objects.bulk_update(batch, ['job_title_entity_id'], batch_size=batch_size)
                    linked_count += len(batch)
                    processed_count += len(batch)

                    logger.info(f"  Processed {processed_count:,}/{total_unlinked:,} salary records ({processed_count/total_unlinked*100:.1f}%) - Linked: {linked_count:,}")

                    batch = []

        # Final batch
        if batch:
            SalaryRecord.objects.bulk_update(batch, ['job_title_entity_id'], batch_size=batch_size)
            linked_count += len(batch)
            processed_count += len(batch)

        logger.info(f"Processing complete: Processed {processed_count:,} records - Linked: {linked_count:,}")

        logger.info(f"Linked {linked_count:,} SalaryRecords to JobTitle entities")
        logger.info("Note: Run update_job_title_cluster_stats to update statistics (don't do it here - too slow)")

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("CLUSTERING SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Job titles processed: {len(all_job_titles):,}")
    logger.info(f"Auto-clustered: {auto_clustered:,}")
    logger.info(f"New clusters created: {new_clusters:,}")
    if not dry_run:
        logger.info(f"SalaryRecords linked: {linked_count:,}")
    logger.info("=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Cluster job titles using the generic clustering framework")
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (don\'t commit changes)')

    args = parser.parse_args()

    # Log script execution
    script_logger.log_call(
        args={'dry_run': args.dry_run},
        context='Clustering job titles using generic clustering framework'
    )

    try:
        cluster_job_titles(dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"Clustering failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

