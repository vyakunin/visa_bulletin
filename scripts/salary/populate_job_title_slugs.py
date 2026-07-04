#!/usr/bin/env python3
"""
Backfill slugs for existing JobTitleCluster records.

Usage:
    bazel run //scripts/salary:populate_job_title_slugs
    bazel run //scripts/salary:populate_job_title_slugs -- --dry-run
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

import argparse

from lib.utils.logging_utils import ScriptLogger
from models.job_title import JobTitleCluster

logger = ScriptLogger(__file__)


def _derive_slug(canonical_title: str) -> str:
    """Derive the expected slug from a canonical_title."""
    from django.utils.text import slugify

    return slugify(canonical_title) if canonical_title else ""


def _find_stale_slugs(min_filings: int = 0):
    """Find clusters whose slug doesn't match their current canonical_title.

    Returned biggest-first so high-traffic clusters claim clean slugs before
    smaller ones contend for them.
    """
    qs = JobTitleCluster.objects.exclude(canonical_title="")
    if min_filings:
        qs = qs.filter(total_filings__gte=min_filings)
    stale = []
    for cluster in qs.order_by("-total_filings").iterator(chunk_size=5000):
        expected = _derive_slug(cluster.canonical_title)
        if cluster.slug != expected:
            stale.append(cluster)
    return stale


def main():
    parser = argparse.ArgumentParser(
        description="Backfill slugs for JobTitleCluster records"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--refresh-all",
        action="store_true",
        help="Regenerate slugs for all clusters whose slug does not match canonical_title",
    )
    parser.add_argument(
        "--min-filings",
        type=int,
        default=0,
        help="With --refresh-all: only refresh clusters with total_filings >= N "
        "(e.g. 100 = the indexable set; renaming noindexed thin pages is pure churn)",
    )
    parser.add_argument(
        "--skip-collisions",
        action="store_true",
        help="With --refresh-all: never rename INTO a counter-suffixed slug — if the "
        "derived slug is held by another cluster, keep the current slug instead",
    )
    args = parser.parse_args()

    logger.log_call(
        args={
            "dry_run": args.dry_run,
            "refresh_all": args.refresh_all,
            "min_filings": args.min_filings,
            "skip_collisions": args.skip_collisions,
        },
        context="Backfill slugs for JobTitleCluster records",
    )

    if args.refresh_all:
        _refresh_stale_slugs(
            args.dry_run,
            min_filings=args.min_filings,
            skip_collisions=args.skip_collisions,
        )
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
        cluster.save(update_fields=["slug"])
        updated_count += 1

        if updated_count % batch_size == 0:
            print(f"  Updated {updated_count}/{total_count} clusters...")

    print(f"\nSuccessfully updated {updated_count} JobTitleCluster records with slugs")


def _refresh_stale_slugs(
    dry_run: bool, min_filings: int = 0, skip_collisions: bool = False
) -> None:
    """Regenerate slugs for clusters where slug doesn't match canonical_title.

    With skip_collisions, a cluster whose derived slug is held by ANOTHER cluster
    keeps its current slug (renaming 'senior-technical-lead' to 'technical-lead-1'
    would be a downgrade). Runs extra passes so slugs freed by an earlier rename
    get claimed in the same invocation.
    """
    max_passes = 5 if skip_collisions else 1
    total_updated = 0
    for pass_no in range(1, max_passes + 1):
        stale = _find_stale_slugs(min_filings)
        print(f"Pass {pass_no}: {len(stale)} clusters with stale slugs")

        if not stale:
            print("All slugs are up-to-date")
            break

        if dry_run:
            print("\nDRY RUN - Showing first 20 stale slugs:")
            for cluster in stale[:20]:
                expected = _derive_slug(cluster.canonical_title)
                taken = (
                    JobTitleCluster.objects.filter(slug=expected)
                    .exclude(pk=cluster.pk)
                    .exists()
                )
                verdict = "SKIP (collision)" if (skip_collisions and taken) else "rename"
                print(
                    f"  [{verdict}] '{cluster.slug}' -> '{expected}' "
                    f"(title: '{cluster.canonical_title}', filings: {cluster.total_filings})"
                )
            if len(stale) > 20:
                print(f"\n... and {len(stale) - 20} more")
            return

        updated = 0
        skipped = 0
        for cluster in stale:
            expected = _derive_slug(cluster.canonical_title)
            if skip_collisions:
                taken = (
                    JobTitleCluster.objects.filter(slug=expected)
                    .exclude(pk=cluster.pk)
                    .exists()
                )
                if taken:
                    skipped += 1
                    continue
                cluster.slug = expected
            else:
                cluster.slug = None
                cluster.slug = cluster.generate_slug()
            cluster.save(update_fields=["slug"])
            updated += 1
            if updated % 1000 == 0:
                print(f"  Updated {updated}/{len(stale)} clusters...")

        total_updated += updated
        print(f"Pass {pass_no}: refreshed {updated}, skipped {skipped} (collisions)")
        if updated == 0:
            break

    print(f"\nSuccessfully refreshed {total_updated} cluster slugs")


if __name__ == "__main__":
    main()
