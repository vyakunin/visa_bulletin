#!/usr/bin/env python3
"""
Ingest USCIS I-485 Inventory Data into RawFactsLedger.

Reads CSV files from data/sources/uscis_inventory/
Expected Columns:
- Country: "India", "China", "Philippines", "Mexico", "All Chargeability"
- Visa Class: "1st", "2nd", "3rd", "Other Workers"
- Priority Date: Date string (YYYY-MM-DD or MM/DD/YYYY)
- Count: Integer

Metric: 'i485_pending_inventory'
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

DATA_DIR = Path("data/sources/uscis_inventory")


def parse_date_str(d_str: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return None


def normalize_country(c_str: str) -> int:
    c_upper = c_upper = c_str.strip().upper()
    if "INDIA" in c_upper:
        return Country.INDIA
    if "CHINA" in c_upper:
        return Country.CHINA
    if "PHILIPPINES" in c_upper:
        return Country.PHILIPPINES
    if "MEXICO" in c_upper:
        return Country.MEXICO
    if "SALVADOR" in c_upper or "GUATEMALA" in c_upper:
        return Country.EL_SALVADOR_GUATEMALA_HONDURAS
    return Country.ALL


def normalize_visa_class(v_str: str) -> str:
    v_upper = v_str.strip().upper()
    if "1ST" in v_upper or "EB-1" in v_upper:
        return "1st"
    if "2ND" in v_upper or "EB-2" in v_upper:
        return "2nd"
    if "3RD" in v_upper or "EB-3" in v_upper:
        return "3rd"
    if "OTHER" in v_upper or "EW" in v_upper:
        return "3rd"  # treat EW as 3rd for now or separate? VQS uses "3rd" generic usually but expects specific if needed.
    # VQS solver uses '3rd' for skilled and 'Other Workers' implies 'unskilled'?
    # Solver logic often groups them unless specified. Let's map to '3rd' or '4th' etc.
    # Actually VQS enums usually string based: "1st", "2nd", "3rd".
    # Let's map "Other Workers" to "3rd" for now as they share the quota mostly (EW limit).
    return "3rd"


def process_file(filepath: Path, publication_date: date):
    logger.info(f"Processing {filepath} (Pub Date: {publication_date})")

    facts_created = 0
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = normalize_country(row.get("Country", ""))
            visa_class = normalize_visa_class(row.get("Visa Class", ""))
            pd_str = row.get("Priority Date", "")
            count_str = row.get("Count", "0").replace(",", "")

            pd = parse_date_str(pd_str)
            if not pd:
                continue

            try:
                count = int(float(count_str))
            except ValueError:
                continue

            if count <= 0:
                continue

            # Fact Dimensions
            dimensions = {
                "country": country,
                "visa_class": visa_class,
                "priority_date": pd.isoformat(),
            }

            # Fact period: The inventory is a snapshot AT a specific time.
            # But specific row refers to people with PD = X.
            # RawFactsLedger structure:
            # Metric: i485_pending_inventory
            # Reference Period: The month of the priority date?
            # NO. The fact is "As of <PublicationDate>, there are N people with <PriorityDate>".
            # This is a distribution.
            # We should probably store the WHOLE distribution as one JSON fact?
            # Or one row per PD month?
            # One row per PD month is better for querying specific demand blocks.
            # Reference Period Start/End: The month of the Priority Date data.
            # i.e. "Demand for Jan 2015".

            ref_start = date(pd.year, pd.month, 1)
            # End of month
            if pd.month == 12:
                ref_end = date(pd.year + 1, 1, 1)
            else:
                ref_end = date(pd.year, pd.month + 1, 1)  # Exclusive or inclusive?
                # DateField usually inclusive. Let's use last day of month.
            import calendar

            last_day = calendar.monthrange(pd.year, pd.month)[1]
            ref_end = date(pd.year, pd.month, last_day)

            # Creating individual small facts might be too many rows (thousands of days).
            # Aggregate by Month-Year-Country-Class?
            # The input might be daily specific or monthly.
            # If input has specific PDs, we aggregate them?
            # Let's aggregate in memory first.
            pass

    # Re-impl with aggregation
    inventory = {}  # (country, visa_class, pd_month_year) -> count

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = normalize_country(row.get("Country", ""))
            visa_class = normalize_visa_class(row.get("Visa Class", ""))
            pd_str = row.get("Priority Date", "")
            count_str = row.get("Count", "0").replace(",", "")

            pd = parse_date_str(pd_str)
            if not pd:
                continue
            try:
                count = int(float(count_str))
            except ValueError:
                continue

            key = (country, visa_class, pd.year, pd.month)
            inventory[key] = inventory.get(key, 0) + count

    # Bulk Create
    to_create = []
    import calendar

    for (country, visa_class, year, month), total_count in inventory.items():
        ref_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        ref_end = date(year, month, last_day)

        dims = {
            "country": country,
            "visa_class": visa_class,
        }

        # Check uniqueness?
        # Using get_or_create logic or just ignore conflicts (append only ledger)
        # We want to avoid duplicates if run multiple times.
        # But RawFactsLedger is append-only.
        # We should check if this fact exists for this source/pub_date.

        # Actually, for VQS, we assume "New file = New knowledge".
        # If we re-run same file, we should probably check if it was already ingested.
        # Simple check: delete previous facts for this source+pub_date?
        # Or construct a deterministic ID/constraint.

        fact = RawFactsLedger(
            source=RawFactSource.USCIS_I485_INVENTORY,
            metric="i485_pending_inventory_monthly",
            dimensions=dims,
            value=total_count,  # raw integer
            reference_period_start=ref_start,
            reference_period_end=ref_end,
            publication_date=publication_date,
        )
        to_create.append(fact)

    with transaction.atomic():
        # Clean up existing for this pub date (optional, but good for idempotency during dev)
        RawFactsLedger.objects.filter(
            source=RawFactSource.USCIS_I485_INVENTORY, publication_date=publication_date
        ).delete()

        RawFactsLedger.objects.bulk_create(to_create, batch_size=1000)

    logger.info(f"Ingested {len(to_create)} facts from {filepath.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Specific file to ingest")
    parser.add_argument(
        "--pub-date", help="Publication date (YYYY-MM-DD)", required=True
    )
    args = parser.parse_args()

    pub_date = parse_date_str(args.pub_date)
    if not pub_date:
        logger.error("Invalid publication date")
        sys.exit(1)

    if args.file:
        process_file(Path(args.file), pub_date)
    else:
        # Scan directory?
        logger.info(f"Scanning {DATA_DIR}...")
        if not DATA_DIR.exists():
            logger.warning(f"{DATA_DIR} does not exist. Creating...")
            DATA_DIR.mkdir(parents=True, exist_ok=True)

        for f in DATA_DIR.glob("*.csv"):
            # heuristic to guess pub date if not provided?
            # For now require explicit execution per file or use args.
            if args.file is None:
                logger.warning("Auto-scan not implemented yet. Please specify --file")
                break


if __name__ == "__main__":
    main()
