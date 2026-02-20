#!/usr/bin/env python3
"""
Backfill SalaryRecords with JobTitle entity links.

This links existing SalaryRecords to JobTitle entities by normalizing each record's
job_title (same logic as cluster_job_titles) and matching on (title_normalized,
experience_level). Using exact raw-string match would miss most records because
JobTitle rows are keyed by normalized form and only store one representative
raw title per row.

Usage:
    bazel run //scripts/salary:backfill_job_title_links [--dry-run]
"""

import argparse
import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django_config.logging_config import setup_logging
from lib.utils.db_utils import BatchedUpdateCollector
from models.job_title import JobTitle
from models.salary import SalaryRecord

setup_logging(debug=False)
import logging

logger = logging.getLogger(__name__)


def backfill_job_title_links(dry_run: bool = False):
    """Link SalaryRecords to JobTitle entities."""
    logger.info("=" * 80)
    logger.info("Backfilling SalaryRecords with JobTitle entity links...")
    logger.info("=" * 80)

    total_records = SalaryRecord.objects.count()
    already_linked = SalaryRecord.objects.filter(job_title_entity__isnull=False).count()
    unlinked_records = SalaryRecord.objects.filter(
        job_title_entity__isnull=True
    ).count()

    logger.info(f"Total SalaryRecords: {total_records:,}")
    logger.info(f"Already linked: {already_linked:,}")
    logger.info(f"To link: {unlinked_records:,}")

    if unlinked_records == 0:
        logger.info("No unlinked records found. Skipping backfill.")
        return

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be saved")

    # Index JobTitle by (title_normalized, experience_level) so we match the same
    # way cluster_job_titles does — raw title variants map to one JobTitle row.
    logger.info("Loading JobTitle entities (by normalized + experience_level)...")
    job_titles_by_key = {}
    for jt in JobTitle.objects.all():
        key = (jt.title_normalized or "", jt.experience_level or "")
        job_titles_by_key[key] = jt

    logger.info(f"Loaded {len(job_titles_by_key):,} JobTitle entities")

    # Process in batches
    collector = BatchedUpdateCollector(
        fields=["job_title_entity"],
        batch_size=1000,
        dry_run=dry_run,
        use_transaction=True,
    )

    linked_count = 0
    not_found_count = 0

    # Process unlinked records — resolve each raw job_title via same normalization
    # as cluster_job_titles so all variants link to the same JobTitle row.
    logger.info("Processing unlinked SalaryRecords...")
    for i, record in enumerate(
        SalaryRecord.objects.filter(job_title_entity__isnull=True).iterator(
            chunk_size=1000
        ),
        1,
    ):
        if not record.job_title:
            not_found_count += 1
            continue
        normalized = JobTitle.normalize_title(record.job_title)
        experience_level = JobTitle.extract_experience_level(record.job_title) or ""
        key = (normalized, experience_level)
        if key in job_titles_by_key:
            job_title = job_titles_by_key[key]
            record.job_title_entity = job_title
            collector.add(record)
            linked_count += 1
        else:
            not_found_count += 1

        if i % 10000 == 0:
            logger.info(
                f"Processed {i:,}/{unlinked_records:,} ({i * 100.0 / unlinked_records:.1f}%) - Linked: {linked_count:,}, Not found: {not_found_count:,}"
            )

    # Flush remaining
    collector.flush()

    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY:")
    logger.info(f"  Processed: {unlinked_records:,} unlinked records")
    logger.info(
        f"  Linked: {linked_count:,} ({linked_count * 100.0 / unlinked_records:.1f}%)"
    )
    logger.info(
        f"  Not found: {not_found_count:,} ({not_found_count * 100.0 / unlinked_records:.1f}%)"
    )
    if dry_run:
        logger.info("  NO CHANGES SAVED (dry run mode)")
    else:
        logger.info(f"  CHANGES SAVED: {collector.count:,} records updated")
    logger.info("=" * 80)

    if not dry_run and linked_count > 0:
        logger.info("\nUpdating JobTitle statistics via bulk aggregation...")
        from django.db.models import Count

        counts_by_id = dict(
            SalaryRecord.objects.filter(job_title_entity__isnull=False)
            .values_list("job_title_entity_id")
            .annotate(cnt=Count("id"))
            .values_list("job_title_entity_id", "cnt")
        )

        to_update: list[JobTitle] = []
        for jt in JobTitle.objects.only("id", "total_filings").iterator(
            chunk_size=5000
        ):
            new_count = counts_by_id.get(jt.id, 0)
            if jt.total_filings != new_count:
                jt.total_filings = new_count
                to_update.append(jt)

        if to_update:
            from lib.utils.db_utils import bulk_update_batched

            bulk_update_batched(to_update, fields=["total_filings"], batch_size=1000)
        logger.info(f"Updated statistics for {len(to_update):,} JobTitle entities")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without saving",
    )
    args = parser.parse_args()

    backfill_job_title_links(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
