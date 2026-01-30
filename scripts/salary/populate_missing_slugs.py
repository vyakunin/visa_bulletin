#!/usr/bin/env python3
"""
Populate missing slugs for EmployerCluster and JobTitleCluster records.

This script is needed because bulk operations bypass the save() method
which auto-generates slugs. When clusters are created via clustering scripts
using bulk_create, they don't get slugs assigned.

Usage:
    bazel run //scripts/salary:populate_missing_slugs
    bazel run //scripts/salary:populate_missing_slugs -- --dry-run
"""

import django
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

import argparse
from django.db import transaction
from django.utils.text import slugify

from models.salary import EmployerCluster, JobTitleCluster
from lib.utils.logging_utils import ScriptLogger

# Initialize script logger
logger = ScriptLogger(__file__)


def populate_employer_slugs(dry_run: bool = False) -> int:
    """
    Populate missing slugs for EmployerCluster records.
    
    Returns number of clusters updated.
    """
    print("\n=== Populating EmployerCluster Slugs ===")
    
    # Get clusters without slugs
    missing_slugs = EmployerCluster.objects.filter(slug__isnull=True)
    total_count = missing_slugs.count()
    
    if total_count == 0:
        print("✅ All EmployerCluster records already have slugs")
        return 0
    
    print(f"Found {total_count:,} clusters without slugs")
    
    if dry_run:
        print("🔍 DRY RUN - Would populate slugs for these clusters")
        # Show sample
        sample = missing_slugs.values('canonical_name')[:10]
        for cluster in sample:
            print(f"  - {cluster['canonical_name']}")
        if total_count > 10:
            print(f"  ... and {total_count - 10:,} more")
        return 0
    
    # Process in batches using transaction for atomicity
    batch_size = 1000
    updated_count = 0
    
    # Track used slugs to ensure uniqueness
    used_slugs = set(
        EmployerCluster.objects
        .filter(slug__isnull=False)
        .values_list('slug', flat=True)
    )
    
    # Process all clusters without slugs
    clusters_to_update = []
    
    for cluster in missing_slugs.iterator(chunk_size=batch_size):
        if cluster.canonical_name:
            # Generate unique slug
            base_slug = slugify(cluster.canonical_name)
            slug = base_slug
            counter = 1
            
            while slug in used_slugs:
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            cluster.slug = slug
            used_slugs.add(slug)
            clusters_to_update.append(cluster)
            
            # Bulk update when batch is full
            if len(clusters_to_update) >= batch_size:
                with transaction.atomic():
                    EmployerCluster.objects.bulk_update(
                        clusters_to_update,
                        ['slug'],
                        batch_size=batch_size
                    )
                updated_count += len(clusters_to_update)
                print(f"  Updated {updated_count:,} / {total_count:,} clusters...")
                clusters_to_update = []
    
    # Update remaining clusters
    if clusters_to_update:
        with transaction.atomic():
            EmployerCluster.objects.bulk_update(
                clusters_to_update,
                ['slug'],
                batch_size=batch_size
            )
        updated_count += len(clusters_to_update)
    
    print(f"✅ Updated {updated_count:,} EmployerCluster records with slugs")
    return updated_count


def populate_job_title_slugs(dry_run: bool = False) -> int:
    """
    Populate missing slugs for JobTitleCluster records.
    
    Returns number of clusters updated.
    """
    print("\n=== Populating JobTitleCluster Slugs ===")
    
    # Get clusters without slugs
    missing_slugs = JobTitleCluster.objects.filter(slug__isnull=True)
    total_count = missing_slugs.count()
    
    if total_count == 0:
        print("✅ All JobTitleCluster records already have slugs")
        return 0
    
    print(f"Found {total_count:,} clusters without slugs")
    
    if dry_run:
        print("🔍 DRY RUN - Would populate slugs for these clusters")
        # Show sample
        sample = missing_slugs.values('canonical_name')[:10]
        for cluster in sample:
            print(f"  - {cluster['canonical_name']}")
        if total_count > 10:
            print(f"  ... and {total_count - 10:,} more")
        return 0
    
    # Process in batches
    batch_size = 1000
    updated_count = 0
    
    # Track used slugs
    used_slugs = set(
        JobTitleCluster.objects
        .filter(slug__isnull=False)
        .values_list('slug', flat=True)
    )
    
    clusters_to_update = []
    
    for cluster in missing_slugs.iterator(chunk_size=batch_size):
        if cluster.canonical_name:
            # Generate unique slug
            base_slug = slugify(cluster.canonical_name)
            slug = base_slug
            counter = 1
            
            while slug in used_slugs:
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            cluster.slug = slug
            used_slugs.add(slug)
            clusters_to_update.append(cluster)
            
            # Bulk update when batch is full
            if len(clusters_to_update) >= batch_size:
                with transaction.atomic():
                    JobTitleCluster.objects.bulk_update(
                        clusters_to_update,
                        ['slug'],
                        batch_size=batch_size
                    )
                updated_count += len(clusters_to_update)
                print(f"  Updated {updated_count:,} / {total_count:,} clusters...")
                clusters_to_update = []
    
    # Update remaining
    if clusters_to_update:
        with transaction.atomic():
            JobTitleCluster.objects.bulk_update(
                clusters_to_update,
                ['slug'],
                batch_size=batch_size
            )
        updated_count += len(clusters_to_update)
    
    print(f"✅ Updated {updated_count:,} JobTitleCluster records with slugs")
    return updated_count


def main():
    parser = argparse.ArgumentParser(
        description="Populate missing slugs for cluster records"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--employers-only',
        action='store_true',
        help='Only process employer clusters'
    )
    parser.add_argument(
        '--job-titles-only',
        action='store_true',
        help='Only process job title clusters'
    )
    args = parser.parse_args()
    
    # Log script invocation
    logger.log_call(
        args=vars(args),
        context="Populate missing slugs for clusters created via bulk operations"
    )
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made\n")
    
    # Process employers unless job-titles-only
    employer_count = 0
    if not args.job_titles_only:
        employer_count = populate_employer_slugs(dry_run=args.dry_run)
    
    # Process job titles unless employers-only
    job_title_count = 0
    if not args.employers_only:
        job_title_count = populate_job_title_slugs(dry_run=args.dry_run)
    
    # Summary
    print("\n=== Summary ===")
    if not args.job_titles_only:
        print(f"Employer clusters updated: {employer_count:,}")
    if not args.employers_only:
        print(f"Job title clusters updated: {job_title_count:,}")
    
    if args.dry_run:
        print("\n🔍 DRY RUN - No changes were made")
        print("Run without --dry-run to apply changes")


if __name__ == '__main__':
    main()
