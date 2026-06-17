#!/usr/bin/env python3
"""
Lightweight hourly visa bulletin refresh.

Discovers and ingests new visa bulletins only (no salary data, no index ops,
no instance swap). Designed to run on the serving instance via cron.

If no new bulletins are found, exits immediately (no-op).
After ingesting new data, clears the Django cache so users see fresh data.

Usage:
    bazel run //scripts/cron:refresh_bulletin
    # Or via pre-built binary:
    ./bazel-bin/scripts/cron/refresh_bulletin

Cron (hourly, uses `. .env` not `source` for /bin/sh compatibility):
    0 * * * * cd /opt/visa_bulletin && set -a && . ./.env && set +a && \
        DB_HOST=localhost ./bazel-bin/scripts/cron/refresh_bulletin \
        >> /var/log/visa-bulletin/bulletin_refresh.log 2>&1
"""

import logging
import os
import runpy
import sys
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta

if os.environ.get("DB_HOST") == "host.docker.internal":
    os.environ["DB_HOST"] = "localhost"

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.core.cache import cache  # noqa: E402

from django_config.logging_config import setup_logging  # noqa: E402
from lib.business.blog.bulletin_narrator import BulletinNarrator  # noqa: E402
from lib.ingest.orchestrator import PipelineOrchestrator  # noqa: E402
from lib.ingest.plugins.visa_bulletin import VisaBulletinPlugin  # noqa: E402
from lib.ingest.registry import PluginRegistry  # noqa: E402
from lib.utils.logging_utils import ScriptLogger  # noqa: E402
from lib.utils.url_utils import (  # noqa: E402
    normalize_source_url,
    path_basename_from_url,
)
from models.blog import BlogPost  # noqa: E402
from models.bulletin import Bulletin  # noqa: E402
from models.ingest.data_source import DataSource  # noqa: E402
from models.ingest.enums import DataDomain, IngestStatus  # noqa: E402
from models.ingest.ingest_run import IngestRun  # noqa: E402

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

_METHODOLOGY_POST_TITLE = "How My Prediction Model Works"


def _ensure_methodology_blog_post() -> None:
    """Recreate the methodology explainer if it is missing (links assume this slug exists)."""
    from django.utils.text import slugify

    slug = slugify(_METHODOLOGY_POST_TITLE)
    if BlogPost.objects.filter(slug=slug, is_published=True).exists():
        return

    script = Path(__file__).resolve().parent.parent / "oneoff" / "generate_initial_blog_posts.py"
    if not script.is_file():
        logger.error("Cannot seed methodology post: script not found at %s", script)
        return

    logger.warning(
        "Published methodology blog post missing (slug=%s); running create_methodology_post",
        slug,
    )
    mod = runpy.run_path(str(script))
    mod["create_methodology_post"]()


def discover_bulletin_sources() -> list:
    """Discover visa bulletin sources, return newly created DataSource objects."""
    plugin = VisaBulletinPlugin()
    source_infos = plugin.discover_sources()
    domain = DataDomain.VISA_BULLETIN.value
    source_type = plugin.source_type

    existing = list(
        DataSource.objects.filter(domain=domain, source_type=source_type).values("id", "url")
    )
    normalized_existing = {normalize_source_url(ds["url"]) for ds in existing}
    basename_existing = {
        (domain, source_type, path_basename_from_url(ds["url"]).lower())
        for ds in existing
    }

    discovered = []
    for info in source_infos:
        normalized = normalize_source_url(info.url)
        basename = path_basename_from_url(normalized).lower()
        if normalized in normalized_existing:
            continue
        if (domain, source_type, basename) in basename_existing:
            continue
        source, created = DataSource.objects.get_or_create(
            url=normalized,
            defaults={
                "domain": info.domain,
                "source_type": info.source_type,
                "format_version": info.format_version,
                "metadata": info.metadata or {},
            },
        )
        if created:
            discovered.append(source)
            normalized_existing.add(normalized)
            logger.info("Discovered new bulletin source: %s", source.url)

    return discovered


MAX_FAILED_RETRIES = 10


def get_pending_bulletin_source_ids() -> list[int]:
    """Return IDs of visa bulletin sources without a completed ingest run.

    Sources that have accumulated ``MAX_FAILED_RETRIES`` failed IngestRuns
    without ever completing are excluded as "permanently failed" — typically
    legacy bulletins (pre-2017) whose HTML format the current parser cannot
    decode. Without this gate the hourly cron retries them forever, producing
    thousands of redundant FAILED rows and burying real errors in the log.

    To force a retry after fixing the parser, delete the FAILED IngestRun rows
    for the affected source(s) or pass them explicitly via a one-off script.
    """
    from django.db.models import Count

    domain = DataDomain.VISA_BULLETIN.value
    all_ids = set(
        DataSource.objects.filter(domain=domain).values_list("id", flat=True)
    )
    completed_ids = set(
        IngestRun.objects.filter(
            source__domain=domain,
            status=IngestStatus.COMPLETED,
        ).values_list("source_id", flat=True)
    )
    failed_counts = (
        IngestRun.objects.filter(
            source__domain=domain,
            status=IngestStatus.FAILED,
        )
        .values("source_id")
        .annotate(n=Count("id"))
    )
    permanently_failed = {
        row["source_id"] for row in failed_counts if row["n"] >= MAX_FAILED_RETRIES
    }
    permanently_failed -= completed_ids  # any later completion overrides the gate

    if permanently_failed:
        logger.warning(
            "Skipping %d permanently-failed bulletin source(s) (>= %d failed retries, no completion). "
            "IDs: %s",
            len(permanently_failed),
            MAX_FAILED_RETRIES,
            sorted(permanently_failed),
        )

    return sorted(all_ids - completed_ids - permanently_failed)


def ingest_sources(source_ids: list[int]) -> int:
    """Ingest specific visa bulletin sources. Returns count of successfully ingested."""
    PluginRegistry.register(VisaBulletinPlugin())
    orchestrator = PipelineOrchestrator(batch_size=1000)
    succeeded = 0

    for source_id in source_ids:
        try:
            source = DataSource.objects.get(id=source_id)
            logger.info("Ingesting bulletin source %d: %s", source_id, source.url)
            run = orchestrator.run(source)
            if run.status == IngestStatus.COMPLETED:
                succeeded += 1
            else:
                logger.warning("Source %d finished with status %s", source_id, run.status)
        except Exception:
            logger.exception("Failed to ingest source %d", source_id)

    return succeeded


def _publish_predictions_for_latest_bulletin(n_bulletins: int) -> None:
    """Publish VQS predictions for the N most recently ingested bulletins.

    Publishes two target months per bulletin:
    - The bulletin's month (for surprise / accuracy vs actual in the blog).
    - The following calendar month (``BulletinNarrator`` Future Outlook reads
      ``PredictedBulletin`` for ``bulletin_date + 1 month``).
    """
    # Call the publisher in-process. The prod image has no Bazel build, so the
    # old bazel-bin/scripts/publish_predictions binary never existed there and
    # every homeserver ingest silently skipped prediction publishing — leaving
    # the blog Future Outlook empty. Importing + calling the function directly
    # works in both the Docker container and a Bazel dev environment.
    from scripts.publish_predictions import publish_predictions as _run_publish

    bulletins = list(
        Bulletin.objects.order_by("-publication_date").values_list("publication_date", flat=True)[:n_bulletins]
    )
    target_months: list[date] = []
    seen: set[tuple[int, int]] = set()
    for pub_date in bulletins:
        first_of = pub_date.replace(day=1)
        following = first_of + relativedelta(months=1)
        for m in (first_of, following):
            key = (m.year, m.month)
            if key not in seen:
                seen.add(key)
                target_months.append(m)

    for target in target_months:
        month_str = target.strftime("%Y-%m")
        logger.info("Publishing predictions for target month %s", month_str)
        try:
            _run_publish([target], ["final_action", "filing"], horizon_months=1)
            logger.info("Predictions published for %s", month_str)
        except Exception:
            logger.exception("Failed to publish predictions for %s", month_str)


def _generate_blog_posts_for_latest_bulletins(n_bulletins: int) -> None:
    """Generate analysis blog posts for the N most recently ingested bulletins."""
    narrator = BulletinNarrator()
    bulletins = list(Bulletin.objects.order_by("-publication_date")[:n_bulletins])
    for bulletin in bulletins:
        try:
            post = narrator.generate_post_for_bulletin(bulletin)
            logger.info("Generated blog post '%s' for bulletin %s", post.title, bulletin.publication_date)
        except Exception:
            logger.exception("Blog generation failed for bulletin %s", bulletin.publication_date)


def main() -> None:
    script_logger.log_call(args={}, context="Hourly visa bulletin refresh")
    logger.info("=== Visa Bulletin Refresh ===")

    _ensure_methodology_blog_post()

    new_sources = discover_bulletin_sources()
    logger.info("Discovered %d new bulletin source(s)", len(new_sources))

    pending_ids = get_pending_bulletin_source_ids()
    if not pending_ids:
        logger.info("No pending bulletins to ingest. Done.")
        return

    logger.info("Ingesting %d pending bulletin source(s)...", len(pending_ids))
    ingested = ingest_sources(pending_ids)

    if ingested > 0:
        logger.info("Ingested %d bulletin(s). Clearing caches...", ingested)
        try:
            cache.clear()
            logger.info("Django cache cleared. New bulletin data is live.")
        except Exception:
            logger.warning("Cache clear failed (non-fatal, Redis may be unavailable)", exc_info=True)

        _publish_predictions_for_latest_bulletin(ingested)
        _generate_blog_posts_for_latest_bulletins(ingested)
    else:
        logger.warning("No bulletins were successfully ingested.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Bulletin refresh failed")
        sys.exit(1)
