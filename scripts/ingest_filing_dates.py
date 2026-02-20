#!/usr/bin/env python3
"""
Quick script to populate filing_date cutoffs from existing bulletin HTML files.

The parser infrastructure already supports filing dates, but they weren't ingested
in the initial run. This script re-parses the existing HTML files and inserts only
the filing_date cutoffs that are missing.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

import logging

from django.db import transaction

from lib.parsing.bulletin.parser import extract_tables
from lib.parsing.bulletin.table_to_cutoff_data import TableToCutoffData
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ingest_filing_dates_from_file(filepath: Path, bulletin: Bulletin) -> int:
    """Extract and insert filing_date cutoffs from a bulletin HTML file."""

    logger.info(
        f"Processing {filepath.name} (bulletin from {bulletin.publication_date})"
    )

    # Read HTML
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Parse tables
    tables = extract_tables(content)

    # Extract cutoff data
    extractor = TableToCutoffData(
        bulletin.publication_date, bulletin.url or str(filepath)
    )

    filing_count = 0
    for table in tables:
        cutoff_data_list = extractor.extract_from_table(table)
        for cutoff_data in cutoff_data_list:
            # Only process filing dates
            if cutoff_data["action_type"] != "filing":
                continue

            # Check if already exists
            exists = VisaCutoffDate.objects.filter(
                bulletin=bulletin,
                visa_category=cutoff_data["visa_category"],
                visa_class=cutoff_data["visa_class"],
                action_type=cutoff_data["action_type"],
                country=cutoff_data["country"],
            ).exists()

            if not exists:
                VisaCutoffDate.objects.create(
                    bulletin=bulletin,
                    visa_category=cutoff_data["visa_category"],
                    visa_class=cutoff_data["visa_class"],
                    action_type=cutoff_data["action_type"],
                    country=cutoff_data["country"],
                    cutoff_value=cutoff_data["cutoff_value"],
                    cutoff_date=cutoff_data["cutoff_date"],
                    is_current=cutoff_data["is_current"],
                    is_unavailable=cutoff_data["is_unavailable"],
                )
                filing_count += 1

    return filing_count


def main():
    data_dir = Path("data/bulletin/saved_pages")

    if not data_dir.exists():
        logger.error(f"Directory not found: {data_dir}")
        sys.exit(1)

    html_files = list(data_dir.glob("*.html"))
    logger.info(f"Found {len(html_files)} bulletin HTML files")

    total_created = 0
    processed = 0

    with transaction.atomic():
        for filepath in sorted(html_files):
            # Match to bulletin by filename pattern
            # visa-bulletin-for-MONTH-YEAR.html
            from datetime import datetime

            filename = filepath.stem  # Without .html
            try:
                date_str = filename.replace("visa-bulletin-for-", "")
                pub_date = datetime.strptime(date_str, "%B-%Y").date()
            except ValueError:
                logger.warning(f"Could not parse date from filename: {filename}")
                continue

            # Find bulletin
            try:
                bulletin = Bulletin.objects.get(publication_date=pub_date)
            except Bulletin.DoesNotExist:
                logger.warning(f"No bulletin found for {pub_date}, skipping")
                continue

            # Ingest filing dates
            created = ingest_filing_dates_from_file(filepath, bulletin)
            total_created += created
            processed += 1

            if created > 0:
                logger.info(f"  Created {created} filing_date cutoffs")

    logger.info("\n✅ Complete!")
    logger.info(f"Processed {processed} bulletins")
    logger.info(f"Created {total_created} filing_date cutoffs")

    # Verify
    filing_count = VisaCutoffDate.objects.filter(action_type="filing").count()
    final_action_count = VisaCutoffDate.objects.filter(
        action_type="final_action"
    ).count()
    logger.info("\nDatabase totals:")
    logger.info(f"  Final Action cutoffs: {final_action_count}")
    logger.info(f"  Filing Date cutoffs:  {filing_count}")


if __name__ == "__main__":
    main()
