#!/usr/bin/env python3
"""
Download USCIS I-140 quarterly receipt data and ingest into raw_facts_ledger.

Attempts to download I-140 receipt files for FY2020-FY2025 from known USCIS
URL patterns, then ingests each successfully downloaded file.

Usage:
  # Download all available quarterly files and ingest
  bazel run //scripts/vqs:download_uscis_i140 -- --output-dir /tmp/i140_data

  # Download only, don't ingest
  bazel run //scripts/vqs:download_uscis_i140 -- --output-dir /tmp/i140_data --download-only

  # List URLs without downloading
  bazel run //scripts/vqs:download_uscis_i140 -- --list-urls
"""

import argparse
import logging
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

# USCIS publishes I-140 data in various URL patterns. We try multiple
# naming conventions since they've changed over the years.
USCIS_BASE = "https://www.uscis.gov/sites/default/files/document/data"

# Known URL patterns for I-140 receipts by class and country
# Format: (url_template, description)
# {fy} = fiscal year (e.g. 2024), {q} = quarter (1-4), {fy_short} = short year (e.g. 24)
URL_TEMPLATES = [
    f"{USCIS_BASE}/i140_rec_by_class_country_fy{{fy}}_q{{q}}.xlsx",
    f"{USCIS_BASE}/I140_rec_by_class_country_FY{{fy}}_Q{{q}}.xlsx",
    f"{USCIS_BASE}/i140_rec_by_class_country_FY{{fy}}_Q{{q}}.xlsx",
    f"{USCIS_BASE}/i140_receipts_by_class_country_fy{{fy}}_q{{q}}.xlsx",
    # Cumulative patterns (e.g. Q1-Q3)
    f"{USCIS_BASE}/i140_rec_by_class_country_fy{{fy}}_q1_q2_q3.xlsx",
    f"{USCIS_BASE}/I140_rec_by_class_country_FY{{fy}}_Q1_Q2_Q3.xlsx",
    # Annual patterns
    f"{USCIS_BASE}/i140_rec_by_class_country_fy{{fy}}.xlsx",
    f"{USCIS_BASE}/I140_rec_by_class_country_FY{{fy}}.xlsx",
]

# Fiscal years to attempt (FY starts in October of prior calendar year)
TARGET_FISCAL_YEARS = range(2020, 2026)
TARGET_QUARTERS = [1, 2, 3, 4]


def _generate_urls() -> list[tuple[str, str]]:
    """Generate (url, description) pairs for all FY/Q combinations."""
    urls = []
    seen = set()
    for fy in TARGET_FISCAL_YEARS:
        for template in URL_TEMPLATES:
            if "{q}" in template:
                for q in TARGET_QUARTERS:
                    url = template.format(fy=fy, q=q, fy_short=str(fy)[-2:])
                    if url not in seen:
                        seen.add(url)
                        urls.append((url, f"FY{fy} Q{q}"))
            else:
                url = template.format(fy=fy, fy_short=str(fy)[-2:])
                if url not in seen:
                    seen.add(url)
                    urls.append((url, f"FY{fy}"))
    return urls


def _download_file(url: str, output_dir: Path) -> Path | None:
    """Download a file from URL. Returns local path or None on failure."""
    import requests

    filename = url.split("/")[-1]
    local_path = output_dir / filename

    if local_path.exists():
        logger.info("Already downloaded: %s", filename)
        return local_path

    try:
        resp = requests.get(url, timeout=30, allow_redirects=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type.lower():
                logger.debug("Got HTML instead of XLSX for %s (likely 404 page)", url)
                return None
            local_path.write_bytes(resp.content)
            logger.info("Downloaded: %s (%d bytes)", filename, len(resp.content))
            return local_path
        else:
            logger.debug("HTTP %d for %s", resp.status_code, url)
            return None
    except Exception as e:
        logger.debug("Failed to download %s: %s", url, e)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and ingest USCIS I-140 quarterly data"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/uscis_i140_data"),
        help="Directory to save downloaded files (default: /tmp/uscis_i140_data)",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download files but don't ingest into database",
    )
    parser.add_argument(
        "--list-urls",
        action="store_true",
        help="List all URLs that will be tried (don't download)",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={"output_dir": str(args.output_dir), "download_only": args.download_only},
        context="VQS: Download USCIS I-140 data",
    )

    urls = _generate_urls()

    if args.list_urls:
        for url, desc in urls:
            print(f"{desc}: {url}")
        print(f"\nTotal URLs to try: {len(urls)}")
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for url, desc in urls:
        path = _download_file(url, args.output_dir)
        if path:
            downloaded.append((path, desc))

    logger.info("Downloaded %d files out of %d URLs tried", len(downloaded), len(urls))

    if not downloaded:
        logger.warning(
            "No files downloaded. USCIS may have changed URL patterns. "
            "Check https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data "
            "and download manually, then use: "
            "bazel run //scripts/vqs:ingest_uscis_i140 -- --file <path>"
        )
        return

    if args.download_only:
        logger.info("Download-only mode. Files saved to: %s", args.output_dir)
        for path, desc in downloaded:
            logger.info("  %s: %s", desc, path)
        return

    from scripts.vqs.ingest_uscis_i140 import ingest_file

    total_rows = 0
    for path, desc in downloaded:
        logger.info("Ingesting %s (%s)...", desc, path.name)
        try:
            count = ingest_file(path, publication_date=None)
            total_rows += count
            logger.info("  Ingested %d rows from %s", count, desc)
        except Exception as e:
            logger.error("  Failed to ingest %s: %s", desc, e)

    logger.info("Total: ingested %d rows from %d files", total_rows, len(downloaded))

    # Report current ledger state
    from models.raw_facts import RawFactsLedger, RawFactSource

    i140_count = RawFactsLedger.objects.filter(
        source=RawFactSource.USCIS_I140,
        metric="i140_receipts",
    ).count()
    logger.info("Raw facts ledger now has %d I-140 receipt rows total", i140_count)

    earliest = (
        RawFactsLedger.objects.filter(
            source=RawFactSource.USCIS_I140,
        )
        .order_by("reference_period_start")
        .values_list("reference_period_start", flat=True)
        .first()
    )
    latest = (
        RawFactsLedger.objects.filter(
            source=RawFactSource.USCIS_I140,
        )
        .order_by("-reference_period_end")
        .values_list("reference_period_end", flat=True)
        .first()
    )
    if earliest and latest:
        logger.info("I-140 data coverage: %s to %s", earliest, latest)


if __name__ == "__main__":
    main()
