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
import sys

if os.environ.get("DB_HOST") == "host.docker.internal":
    os.environ["DB_HOST"] = "localhost"

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.core.cache import cache  # noqa: E402

from django_config.logging_config import setup_logging  # noqa: E402
from lib.ingest.orchestrator import PipelineOrchestrator  # noqa: E402
from lib.ingest.plugins.visa_bulletin import VisaBulletinPlugin  # noqa: E402
from lib.ingest.registry import PluginRegistry  # noqa: E402
from lib.utils.logging_utils import ScriptLogger  # noqa: E402
from lib.utils.url_utils import (  # noqa: E402
    normalize_source_url,
    path_basename_from_url,
)
from models.ingest.data_source import DataSource  # noqa: E402
from models.ingest.enums import DataDomain, IngestStatus  # noqa: E402
from models.ingest.ingest_run import IngestRun  # noqa: E402

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


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


def get_pending_bulletin_source_ids() -> list[int]:
    """Return IDs of visa bulletin sources without a completed ingest run."""
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
    return sorted(all_ids - completed_ids)


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


def main() -> None:
    script_logger.log_call(args={}, context="Hourly visa bulletin refresh")
    logger.info("=== Visa Bulletin Refresh ===")

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
    else:
        logger.warning("No bulletins were successfully ingested.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Bulletin refresh failed")
        sys.exit(1)
