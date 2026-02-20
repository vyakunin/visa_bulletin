#!/usr/bin/env python3
"""
Clean up DataSource records with malformed URLs.

Deletes DataSource records that have incorrect URL paths (containing duplicate path segments).
These were created by buggy discovery logic and need to be removed before re-discovery.
"""

import logging
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.ingest.data_source import DataSource

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def main():
    logger.info("=" * 80)
    logger.info("Cleaning up DataSource records with malformed URLs")
    logger.info("=" * 80)

    # Find sources with malformed URLs (extra path prefix)
    bad_url_pattern = "/agencies/eta/foreign-labor/performance/sites/"

    bad_sources = DataSource.objects.filter(url__contains=bad_url_pattern)
    count = bad_sources.count()

    if count == 0:
        logger.info("✅ No malformed URLs found")
        return

    logger.info(f"Found {count} DataSource records with malformed URLs")
    logger.info(f"Pattern: URLs containing '{bad_url_pattern}'")
    logger.info("")

    # Show samples
    logger.info("Sample malformed URLs:")
    for source in bad_sources[:5]:
        logger.info(f"  ID {source.id}: {source.url}")

    if count > 5:
        logger.info(f"  ... and {count - 5} more")

    logger.info("")

    # Check if any have completed runs
    from models.ingest.ingest_run import IngestRun

    affected_runs = IngestRun.objects.filter(source__in=bad_sources)
    runs_count = affected_runs.count()

    if runs_count > 0:
        logger.warning(
            f"⚠️  These sources have {runs_count} associated IngestRun records"
        )
        logger.warning("  These runs will also be deleted (CASCADE)")

        # Show which runs will be affected
        for run in affected_runs[:5]:
            logger.warning(
                f"    Run {run.id}: status={run.status}, started={run.started_at}"
            )

    # Confirm deletion
    logger.info("")
    logger.info("This will DELETE:")
    logger.info(f"  - {count} DataSource records with malformed URLs")
    if runs_count > 0:
        logger.info(f"  - {runs_count} associated IngestRun records (CASCADE)")
    logger.info("")

    response = input("Proceed with deletion? (yes/no): ")
    if response.lower() != "yes":
        logger.info("Aborted - no changes made")
        return

    # Delete bad sources
    logger.info("Deleting malformed DataSource records...")
    deleted = bad_sources.delete()

    logger.info("")
    logger.info("=" * 80)
    logger.info("CLEANUP COMPLETE")
    logger.info("=" * 80)
    logger.info(f"✅ Deleted {deleted[0]} objects:")
    for model_name, count in deleted[1].items():
        logger.info(f"  - {model_name}: {count}")
    logger.info("")
    logger.info("Next step: Re-run discovery to create correct URLs")
    logger.info(
        "  bazel run //scripts/ingest:run_pipeline -- check-completeness --domain dol"
    )


if __name__ == "__main__":
    main()
