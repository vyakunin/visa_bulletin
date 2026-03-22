#!/usr/bin/env python3
"""
Ingest DOL PERM Disclosure data into raw_facts_ledger as 'perm_applications'.

Reads all PERM disclosure XLSX files from data/vqs/dol_perm/, aggregates
case counts by (country_of_citizenship, visa_class, year, month, status),
and writes to RawFactsLedger. Used as a leading-indicator feature for VQS
GBM predictions (Hypothesis #7: PERM volume predicts EB-2/3 pressure).

Usage:
  # Ingest all PERM files from default directory
  bazel run //scripts/vqs:ingest_perm_supply

  # Ingest from a specific directory
  bazel run //scripts/vqs:ingest_perm_supply -- --data-dir /path/to/perm_files

  # Dry run (aggregate and report without writing to DB)
  bazel run //scripts/vqs:ingest_perm_supply -- --dry-run

  # Clear existing rows and re-ingest
  bazel run //scripts/vqs:ingest_perm_supply -- --clear

Notes:
- Only rows with a parseable CASE_RECEIVED_DATE are included
- visa_class is inferred from education field: Master's/Doctorate->EB-2, else->EB-3
- country is matched against Country enum (India, China, Mexico, Philippines; others->ALL)
- Each XLSX file may have 100k-300k rows; aggregation happens in-memory per file
"""

import argparse
import calendar
import logging
import os
from collections import defaultdict
from datetime import date
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.business.vqs.ingest_utils import normalize_country, normalize_visa_class_perm
from lib.parsing.salary.db_importer import PERM_COLUMN_MAPPINGS, get_column_value
from lib.utils.logging_utils import ScriptLogger
from models.enums.country import Country
from models.raw_facts import RawFactSource, RawFactsLedger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

# For pre-FY2015 files, CASE_RECEIVED_DATE doesn't exist; DECISION_DATE is a reasonable proxy
# (lags submission by ~1-2 years but is consistent across years, preserving YoY ratio signal).
CASE_DATE_COLUMNS = [
    "CASE_RECEIVED_DATE",
    "RECEIVED_DATE",
    "Received_Date",
    "DECISION_DATE",
    "Decision_Date",
]

EXTRA_MAPPINGS = {
    "country": [
        "COUNTRY_OF_CITIZENSHIP",
        "Country_of_Citizenship",
        "FW_INFO_CTRY_OF_CIT",
        "COUNTRY_OF_CITZENSHIP",  # typo in FY2008 file
    ],
    "education": [
        "FOREIGN_WORKER_INFO_EDUCATION",
        "Foreign_Worker_Info_Education",
        "MINIMUM_EDUCATION",
    ],
    "experience_months": [
        "JOB_INFO_EXPERIENCE_NUM_MONTHS",
        "Job_Info_Experience_Num_Months",
        "REQUIRED_EXPERIENCE_MONTHS",
    ],
}


def parse_date_flexible(s) -> date | None:
    """Parse date from string, datetime, or date objects."""
    from datetime import datetime as dt_type

    if s is None:
        return None
    if isinstance(s, date) and not isinstance(s, dt_type):
        return s
    if isinstance(s, dt_type):
        return s.date()
    s = str(s).strip()
    if not s or s in ("None", "nan", ""):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt_type.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def aggregate_perm_file_xlsx(filepath: Path) -> dict:
    """Aggregate a PERM xlsx file in memory. Returns {(country, visa_class, year, month, status): count}."""
    import openpyxl

    logger.info(f"Processing {filepath.name}...")
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    rows = ws.iter_rows(values_only=True)
    header_row = next(rows, None)
    if header_row is None:
        logger.warning(f"Empty file: {filepath.name}")
        wb.close()
        return {}

    headers = [str(h).strip() if h is not None else "" for h in header_row]
    agg = defaultdict(int)
    row_count = 0
    skipped = 0

    for row_values in rows:
        row = dict(zip(headers, row_values))
        row_count += 1

        status_raw = get_column_value(row, PERM_COLUMN_MAPPINGS["case_status"])
        if not status_raw:
            skipped += 1
            continue
        status = str(status_raw).strip().upper()

        pd_raw = get_column_value(row, CASE_DATE_COLUMNS)
        pd = parse_date_flexible(pd_raw)
        if pd is None:
            skipped += 1
            continue

        c_raw = get_column_value(row, EXTRA_MAPPINGS["country"])
        country = normalize_country(str(c_raw) if c_raw else "")

        visa_class = normalize_visa_class_perm(row, EXTRA_MAPPINGS)

        key = (country, visa_class, pd.year, pd.month, status)
        agg[key] += 1

        if row_count % 50000 == 0:
            logger.info(f"  ...{row_count:,} rows processed")

    wb.close()
    logger.info(f"  Done: {row_count:,} rows, {skipped:,} skipped, {len(agg):,} buckets")
    return dict(agg)


def aggregate_perm_file_csv(filepath: Path) -> dict:
    """Aggregate a PERM CSV file in memory."""
    import csv

    logger.info(f"Processing CSV {filepath.name}...")
    agg = defaultdict(int)
    row_count = 0
    skipped = 0

    with open(filepath, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_count += 1

            status_raw = get_column_value(row, PERM_COLUMN_MAPPINGS["case_status"])
            if not status_raw:
                skipped += 1
                continue
            status = str(status_raw).strip().upper()

            pd_raw = get_column_value(row, CASE_DATE_COLUMNS)
            pd = parse_date_flexible(pd_raw)
            if pd is None:
                skipped += 1
                continue

            c_raw = get_column_value(row, EXTRA_MAPPINGS["country"])
            country = normalize_country(str(c_raw) if c_raw else "")
            visa_class = normalize_visa_class_perm(row, EXTRA_MAPPINGS)

            key = (country, visa_class, pd.year, pd.month, status)
            agg[key] += 1

    logger.info(f"  Done: {row_count:,} rows, {skipped:,} skipped, {len(agg):,} buckets")
    return dict(agg)


def write_to_db(agg: dict, dry_run: bool = False) -> int:
    """Write aggregated counts to RawFactsLedger. Returns rows written."""
    records = []
    for (country, visa_class, year, month, status), count in agg.items():
        ref_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        ref_end = date(year, month, last_day)
        dims = {"country": country, "visa_class": visa_class, "status": status}

        records.append(
            RawFactsLedger(
                source=RawFactSource.DOL_PERM_DISCLOSURE,
                metric="perm_applications",
                dimensions=dims,
                value=count,
                reference_period_start=ref_start,
                reference_period_end=ref_end,
                publication_date=date.today(),
            )
        )

    if dry_run:
        logger.info(f"[dry-run] Would write {len(records):,} RawFactsLedger rows")
        return len(records)

    # Use update_or_create semantics via bulk approach: delete matching keys then bulk_create
    # Since RawFactsLedger has no unique constraint on (source, metric, dimensions, ref_start),
    # just bulk_create with ignore_conflicts=False
    batch_size = 1000
    written = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        created = RawFactsLedger.objects.bulk_create(batch, ignore_conflicts=True)
        written += len(created)
        logger.info(f"  Written {written:,}/{len(records):,} rows")

    return written


def main():
    parser = argparse.ArgumentParser(description="Ingest PERM Disclosure data into RawFactsLedger")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/vqs/dol_perm"),
        help="Directory containing PERM disclosure XLSX files (default: data/vqs/dol_perm)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Aggregate and report without writing to DB",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete existing perm_applications rows before ingestion",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={"data_dir": str(args.data_dir), "dry_run": args.dry_run, "clear": args.clear},
        context="Ingest PERM supply data for VQS Hypothesis #7",
    )

    data_dir = args.data_dir
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return

    # Find all PERM files
    files = sorted(
        list(data_dir.glob("PERM*.xlsx"))
        + list(data_dir.glob("PERM*.csv"))
        + list(data_dir.glob("perm*.xlsx"))
        + list(data_dir.glob("perm*.csv"))
    )
    logger.info(f"Found {len(files)} PERM files in {data_dir}")

    if not files:
        logger.error("No PERM files found. Check --data-dir.")
        return

    if args.clear and not args.dry_run:
        deleted, _ = RawFactsLedger.objects.filter(metric="perm_applications").delete()
        logger.info(f"Deleted {deleted:,} existing perm_applications rows")

    # Check existing rows to avoid duplicates (source+metric+dims+ref_start)
    existing_before = RawFactsLedger.objects.filter(metric="perm_applications").count()
    logger.info(f"Existing perm_applications rows: {existing_before:,}")

    total_written = 0
    global_agg: dict = {}

    for filepath in files:
        try:
            if filepath.suffix.lower() in (".xlsx", ".xls"):
                file_agg = aggregate_perm_file_xlsx(filepath)
            else:
                file_agg = aggregate_perm_file_csv(filepath)

            # Merge into global aggregate
            for key, count in file_agg.items():
                global_agg[key] = global_agg.get(key, 0) + count

        except Exception as e:
            logger.error(f"Failed to process {filepath.name}: {e}", exc_info=True)

    logger.info(f"\nTotal aggregated buckets across all files: {len(global_agg):,}")

    # Report breakdown by country and visa_class
    by_country: dict = defaultdict(int)
    by_class: dict = defaultdict(int)
    for (country, visa_class, _year, _month, status), count in global_agg.items():
        if status == "CERTIFIED":
            by_country[country] += count
            by_class[visa_class] += count

    logger.info("CERTIFIED counts by country:")
    for country, cnt in sorted(by_country.items(), key=lambda x: -x[1]):
        c_name = Country(country).label if country in [c.value for c in Country] else str(country)
        logger.info(f"  {c_name}: {cnt:,}")

    logger.info("CERTIFIED counts by visa_class:")
    for vc, cnt in sorted(by_class.items(), key=lambda x: -x[1]):
        logger.info(f"  EB-{vc}: {cnt:,}")

    # Write to DB
    total_written = write_to_db(global_agg, dry_run=args.dry_run)

    if not args.dry_run:
        existing_after = RawFactsLedger.objects.filter(metric="perm_applications").count()
        logger.info(f"perm_applications rows after ingest: {existing_after:,} (+{existing_after - existing_before:,})")

    logger.info(f"Done. {total_written:,} rows {'would be ' if args.dry_run else ''}written.")


if __name__ == "__main__":
    main()
