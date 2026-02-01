#!/usr/bin/env python3
"""
Backfill slugs for existing JobTitleCluster records.

Usage:
    bazel run //scripts/salary:populate_job_title_slugs
    bazel run //scripts/salary:populate_job_title_slugs -- --dry-run
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

import argparse
from models.job_title import JobTitleCluster
from lib.utils.logging_utils import ScriptLogger

logger = ScriptLogger(__file__)


def main():
    parser = argparse.ArgumentParser(description='Backfill slugs for JobTitleCluster records')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()
    
    logger.log_call(
        args={'dry_run': args.dry_run},
        context='Backfill slugs for JobTitleCluster records'
    )
    
    # Find clusters without slugs
    clusters_without_slugs = JobTitleCluster.objects.filter(slug__isnull=True)
    total_count = clusters_without_slugs.count()
    
    print(f"Found {total_count} JobTitleCluster records without slugs")
    
    if total_count == 0:
        print("✅ All JobTitleCluster records already have slugs")
        return
    
    if args.dry_run:
        print("\n🔍 DRY RUN - Showing first 10 clusters that would be updated:")
        for cluster in clusters_without_slugs[:10]:
            slug = cluster.generate_slug()
            print(f"  - '{cluster.canonical_title}' -> '{slug}'")
        print(f"\n... and {max(0, total_count - 10)} more")
        return
    
    # Update clusters in batches
    print("\n📝 Generating and saving slugs...")
    updated_count = 0
    batch_size = 100
    
    for cluster in clusters_without_slugs.iterator(chunk_size=batch_size):
        cluster.slug = cluster.generate_slug()
        cluster.save(update_fields=['slug'])
        updated_count += 1
        
        if updated_count % batch_size == 0:
            print(f"  Updated {updated_count}/{total_count} clusters...")
    
    print(f"\n✅ Successfully updated {updated_count} JobTitleCluster records with slugs")


if __name__ == '__main__':
    main()
