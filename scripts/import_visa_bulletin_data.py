#!/usr/bin/env python3
"""
Import visa bulletin data from CSV files exported from another instance.

The main path for bulletin data is the Visa Bulletin ingest (VisaBulletinPlugin):
run_pipeline discovers HTML from the State Dept index and parses it. This script
is for importing pre-exported CSV data (e.g. from production to development, or
from historical dumps).

CSV format: direct psql \\COPY export from bulletin and visa_cutoff_date tables.
Country values can be integers (enum values from DB) or strings (enum labels).

Usage:
    bazel run //scripts:import_visa_bulletin_data
    bazel run //scripts:import_visa_bulletin_data -- --bulletin /path/to/bulletin.csv --cutoff /path/to/cutoff.csv
    (Defaults to /tmp/bulletin.csv and /tmp/visa_cutoff_date.csv)
"""

import argparse
import csv
import logging
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django.db import transaction

from django_config.logging_config import setup_logging
from models.bulletin import Bulletin
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate

setup_logging(debug=False)
logger = logging.getLogger(__name__)


def _parse_country(value: str) -> Country | None:
    """Parse country from CSV value (integer enum value or string label)."""
    if not value or value.strip() == "":
        return None
    stripped = value.strip()
    # Try integer enum value first (from psql COPY export)
    try:
        int_val = int(stripped)
        return Country(int_val)
    except (ValueError, KeyError):
        pass
    # Fall back to string label
    return Country.from_string(stripped)


def _parse_bool(value: str) -> bool:
    """Parse boolean from CSV (handles 't'/'f', '1'/'0', 'True'/'False')."""
    return value.strip().lower() in ("t", "true", "1", "yes")


def import_visa_bulletin_data(bulletin_csv: str, cutoff_csv: str) -> None:
    """Import visa bulletin data from CSV files."""
    logger.info("Importing visa bulletin data...")
    logger.info("Bulletin CSV: %s", bulletin_csv)
    logger.info("Cutoff CSV: %s", cutoff_csv)

    with transaction.atomic():
        # Build ID mapping: prod bulletin_id -> local bulletin_id (may differ)
        # Use publication_date as the natural key for bulletins
        logger.info("1. Importing bulletins...")
        created_count = 0
        updated_count = 0
        prod_to_local_bulletin_id: dict[int, int] = {}
        with open(bulletin_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                prod_id = int(row["id"])
                pub_date = row["publication_date"]
                bulletin, created = Bulletin.objects.update_or_create(
                    publication_date=pub_date,
                    defaults={
                        "fetched_at": row["fetched_at"],
                        "url": row["url"] if row["url"] else None,
                    },
                )
                prod_to_local_bulletin_id[prod_id] = bulletin.id
                if created:
                    created_count += 1
                else:
                    updated_count += 1
        logger.info("Bulletins: %d created, %d updated", created_count, updated_count)

        logger.info("2. Importing visa cutoff dates...")
        created_count = 0
        skipped_count = 0
        warn_count = 0
        with open(cutoff_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                country = _parse_country(row["country"])
                if country is None:
                    warn_count += 1
                    if warn_count <= 5:
                        logger.warning(
                            "Unknown country '%s', skipping row %s",
                            row["country"],
                            row["id"],
                        )
                    continue

                prod_bulletin_id = int(row["bulletin_id"])
                local_bulletin_id = prod_to_local_bulletin_id.get(prod_bulletin_id)
                if local_bulletin_id is None:
                    warn_count += 1
                    if warn_count <= 5:
                        logger.warning(
                            "Bulletin ID %d not found in mapping, skipping",
                            prod_bulletin_id,
                        )
                    continue

                cutoff_date_val = row["cutoff_date"] if row["cutoff_date"] else None
                _, created = VisaCutoffDate.objects.get_or_create(
                    bulletin_id=local_bulletin_id,
                    visa_category=row["visa_category"],
                    visa_class=row["visa_class"],
                    action_type=row["action_type"],
                    country=country,
                    defaults={
                        "cutoff_value": row["cutoff_value"],
                        "cutoff_date": cutoff_date_val,
                        "is_current": _parse_bool(row["is_current"]),
                        "is_unavailable": _parse_bool(row["is_unavailable"]),
                    },
                )
                if created:
                    created_count += 1
                else:
                    skipped_count += 1
        logger.info(
            "Cutoff dates: %d created, %d already existed, %d warnings",
            created_count,
            skipped_count,
            warn_count,
        )

    logger.info(
        "Import completed. Totals: %d bulletins, %d cutoff dates",
        Bulletin.objects.count(),
        VisaCutoffDate.objects.count(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import visa bulletin data from CSV")
    parser.add_argument(
        "--bulletin", default="/tmp/bulletin.csv", help="Path to bulletin CSV"
    )
    parser.add_argument(
        "--cutoff",
        default="/tmp/visa_cutoff_date.csv",
        help="Path to visa_cutoff_date CSV",
    )
    args = parser.parse_args()

    if not os.path.exists(args.bulletin):
        logger.error("Bulletin CSV not found: %s", args.bulletin)
        sys.exit(1)
    if not os.path.exists(args.cutoff):
        logger.error("Cutoff CSV not found: %s", args.cutoff)
        sys.exit(1)

    import_visa_bulletin_data(args.bulletin, args.cutoff)


if __name__ == "__main__":
    main()
