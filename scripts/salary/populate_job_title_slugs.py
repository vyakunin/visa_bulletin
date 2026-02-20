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


def _derive_slug(canonical_title: str) -> str:
    """Derive the expected slug from a canonical_title."""
    from django.utils.text import slugify
    return slugify(canonical_title) if canonical_title else ""


def _find_stale_slugs():
    """Find clusters whose slug doesn't match their current canonical_title."""
    stale = []
    for cluster in JobTitleCluster.objects.exclude(canonical_title="").iterator(chunk_size=5000):
        expected = _derive_slug(cluster.canonical_title)
        if cluster.slug != expected:
            stale.append(cluster)
    return stale


def main():
    parser = argparse.ArgumentParser(description='Backfill slugs for JobTitleCluster records')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument(
        '--refresh-all', action='store_true',
        help='Regenerate slugs for all clusters whose slug does not match canonical_title',
    )
    args = parser.parse_args()

    logger.log_call(
        args={'dry_run': args.dry_run, 'refresh_all': args.refresh_all},
        context='Backfill slugs for JobTitleCluster records',
    )

    if args.refresh_all:
        _refresh_stale_slugs(args.dry_run)
        return

    clusters_without_slugs = JobTitleCluster.objects.filter(slug__isnull=True)
    total_count = clusters_without_slugs.count()

    print(f"Found {total_count} JobTitleCluster records without slugs")

    if total_count == 0:
        print("All JobTitleCluster records already have slugs")
        return

    if args.dry_run:
        print("\nDRY RUN - Showing first 10 clusters that would be updated:")
        for cluster in clusters_without_slugs[:10]:
            slug = cluster.generate_slug()
            print(f"  - '{cluster.canonical_title}' -> '{slug}'")
        print(f"\n... and {max(0, total_count - 10)} more")
        return

    print("\nGenerating and saving slugs...")
    updated_count = 0
    batch_size = 100

    for cluster in clusters_without_slugs.iterator(chunk_size=batch_size):
        cluster.slug = cluster.generate_slug()
        cluster.save(update_fields=['slug'])
        updated_count += 1

        if updated_count % batch_size == 0:
            print(f"  Updated {updated_count}/{total_count} clusters...")

    print(f"\nSuccessfully updated {updated_count} JobTitleCluster records with slugs")


def _refresh_stale_slugs(dry_run: bool) -> None:
    """Regenerate slugs for clusters where slug doesn't match canonical_title."""
    stale = _find_stale_slugs()
    print(f"Found {len(stale)} clusters with stale slugs")

    if not stale:
        print("All slugs are up-to-date")
        return

    if dry_run:
        print("\nDRY RUN - Showing first 20 stale slugs:")
        for cluster in stale[:20]:
            expected = _derive_slug(cluster.canonical_title)
            print(f"  '{cluster.slug}' -> '{expected}' (title: '{cluster.canonical_title}')")
        if len(stale) > 20:
            print(f"\n... and {len(stale) - 20} more")
        return

    print("\nRegenerating slugs...")
    updated = 0
    for cluster in stale:
        cluster.slug = None
        cluster.slug = cluster.generate_slug()
        cluster.save(update_fields=['slug'])
        updated += 1
        if updated % 1000 == 0:
            print(f"  Updated {updated}/{len(stale)} clusters...")

    print(f"\nSuccessfully refreshed {updated} cluster slugs")


if __name__ == '__main__':
    main()
