#!/usr/bin/env python3
"""
Ingest DOS Monthly Issuance Data into RawFactsLedger.

Reads CSV files from data/sources/dos_issuance/
Expected Columns:
- Fiscal Year: Integer (e.g. 2024)
- Month: String (e.g. "October")
- Visa Class: "E1", "E2", "E3", "EW" etc.
- Chargeability Area: Country name
- Issuance Count: Integer

Metric: 'visa_issuance_monthly'
"""

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import django
from django.conf import settings
from django.db import transaction

# Setup Django
if not settings.configured:
    logging.basicConfig(level=logging.INFO)
    sys.path.append(".")
    django.setup()

from models.enums.country import Country
from models.raw_facts import RawFactsLedger, RawFactSource

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/sources/dos_issuance")


def normalize_country(c_str: str) -> int:
    return Country.from_header(c_str) or Country.ALL


def normalize_month(m_str: str) -> int:
    try:
        return datetime.strptime(m_str.strip(), "%B").month
    except ValueError:
        return 0


def process_file(filepath: Path, publication_date: date):
    logger.info(f"Processing {filepath} (Pub Date: {publication_date})")

    to_create = []

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            fy_str = row.get("Fiscal Year", "")
            month_str = row.get("Month", "")
            visa_code = row.get("Visa Class", "").strip()
            country_str = row.get("Chargeability Area", "")
            count_str = row.get("Issuance Count", "0").replace(",", "")

            try:
                fy = int(fy_str)
                count = int(float(count_str))
                month = normalize_month(month_str)
            except ValueError:
                continue

            if month == 0 or count <= 0:
                continue

            country = normalize_country(country_str)

            # Map Visa Code to VQS Class
            # DOS reports are granulated: E11, E12, E31, E34 etc.
            # We map to "1st", "2nd", "3rd", "4th" (Religious), "5th"
            # Actually simplest is to store the raw visa_code too?
            # Metric: "visa_issuance_monthly"
            # Dimensions: {"country": ..., "visa_class": "1st", "raw_code": "E11"}

            v_cat = "Unknown"
            v_upper = visa_code.upper()
            if v_upper.startswith("E1"):
                v_cat = "1st"
            elif v_upper.startswith("E2"):
                v_cat = "2nd"
            elif v_upper.startswith("E3"):
                v_cat = "3rd"
            elif v_upper.startswith("EW"):
                v_cat = "3rd"  # Unskilled
            elif v_upper.startswith("SR"):
                v_cat = "4th"
            elif v_upper.startswith("R"):
                v_cat = "4th"
            elif (
                v_upper.startswith("C5")
                or v_upper.startswith("T5")
                or v_upper.startswith("I5")
                or v_upper.startswith("R5")
            ):
                v_cat = "5th"

            # Construct reference period
            # Input is Fiscal Year + Month.
            # FY2024 Oct = Oct 2023.
            # If Month >= 10, calendar year = FY - 1.
            # If Month < 10, calendar year = FY.

            if month >= 10:
                cal_year = fy - 1
            else:
                cal_year = fy

            import calendar

            last_day = calendar.monthrange(cal_year, month)[1]
            ref_start = date(cal_year, month, 1)
            ref_end = date(cal_year, month, last_day)

            dims = {
                "country": country,
                "visa_class": v_cat,
                "raw_code": visa_code,
            }

            fact = RawFactsLedger(
                source=RawFactSource.DOS_ISSUANCE,
                metric="visa_issuance_monthly",
                dimensions=dims,
                value=count,
                reference_period_start=ref_start,
                reference_period_end=ref_end,
                publication_date=publication_date,
            )
            to_create.append(fact)

    with transaction.atomic():
        # Remove old data for this pub date?
        # DOS issuance builds up over time.
        # Idempotency: filter by dimensions + ref period + source + metric?
        # Bulk create for efficiency.
        RawFactsLedger.objects.filter(
            source=RawFactSource.DOS_ISSUANCE, publication_date=publication_date
        ).delete()
        RawFactsLedger.objects.bulk_create(to_create, batch_size=1000)

    logger.info(f"Ingested {len(to_create)} issuance records from {filepath.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Specific file to ingest")
    parser.add_argument(
        "--pub-date", help="Publication date (YYYY-MM-DD)", required=True
    )
    args = parser.parse_args()

    pub_date = None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            pub_date = datetime.strptime(args.pub_date, fmt).date()
            break
        except ValueError:
            pass

    if not pub_date:
        logger.error("Invalid publication date")
        sys.exit(1)

    if args.file:
        process_file(Path(args.file), pub_date)
    else:
        pass


if __name__ == "__main__":
    main()
