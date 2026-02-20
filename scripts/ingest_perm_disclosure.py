#!/usr/bin/env python3
"""
Ingest DOL PERM Disclosure Data into RawFactsLedger.

Reads CSV files from data/sources/dol_perm/
Expected Columns (varies by year, using standard mappings):
- CASE_NUMBER
- CASE_STATUS (Certified, Denied, Withdrawn)
- CASE_RECEIVED_DATE (Priority Date)
- EMPLOYER_NAME
- COUNTRY_OF_CITIZENSHIP
- CLASS_OF_ADMISSION (Visa Category inference)
- PW_SOC_CODE (Job Category inference)

Metric: 'perm_applications'
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

from lib.parsing.salary.db_importer import PERM_COLUMN_MAPPINGS, get_column_value
from models.enums.country import Country
from models.raw_facts import RawFactsLedger, RawFactSource

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/sources/dol_perm")


def parse_date_str(d_str: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return None


def normalize_country(c_str: str) -> int:
    return Country.from_header(c_str) or Country.ALL


def normalize_visa_class(row: dict, extra_mappings: dict) -> str:
    # Heuristic based on Class of Admission or Job Title?
    # PERM doesn't explicitly state "EB2" or "EB3".
    # Usually inferred from:
    # - Class of Admission (H-1B, L-1, etc.) -> Not useful for EB pref.
    # - Job Requirements (Education/Experience) -> Determines EB2 vs EB3.
    # - "MINIMUM_EDUCATION": Master's -> EB2. Bachelor's + 5yr -> EB2. Bachelor's -> EB3. None -> EW.

    # Simple heuristic for now:
    # If explicitly "EB-2" in some internal column? Rare.
    # Let's check Education.

    # Mappings for 2023+ (modern):
    # 'MINIMUM_EDUCATION': "Master's", "Bachelor's", "None", "Doctorate", "Other"

    edu = get_column_value(row, extra_mappings["education"]) or ""
    if not edu:
        # Fallback to checking other columns or default to 3rd?
        # Let's check Job Title for 'Senior', 'Manager'? Weak.
        return "3rd"

    edu_upper = str(edu).upper()
    if "MASTER" in edu_upper or "DOCTORATE" in edu_upper or "PROFESSIONAL" in edu_upper:
        return "2nd"
    if "BACHELOR" in edu_upper:
        # Check experience?
        # Requires 5 years?
        # 'REQUIRED_EXPERIENCE_MONTHS' >= 60?
        try:
            exp_months = int(
                float(get_column_value(row, extra_mappings["experience_months"]) or 0)
            )
            if exp_months >= 60:
                return "2nd"
        except:
            pass
        return "3rd"

    if "NONE" in edu_upper or "HIGH SCHOOL" in edu_upper:
        return "3rd"  # Or "Other Workers" (EW) if unskilled?

    return "3rd"


def process_file(filepath: Path, publication_date: date):
    logger.info(f"Processing {filepath} (Pub Date: {publication_date})")

    # Local mappings for fields not in db_importer (which focuses on Salary)
    EXTRA_MAPPINGS = {
        "country": [
            "COUNTRY_OF_CITIZENSHIP",
            "Country_of_Citizenship",
            "FW_INFO_CTRY_OF_CIT",
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

    # Aggregate counts by (Country, Visa Class, PD Month, Status)
    agg = {}

    # Using low-level CSV reading to avoid memory issues with huge files
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = get_column_value(row, PERM_COLUMN_MAPPINGS["case_status"])
            if not status:
                continue
            status = status.upper()

            # Fix key: case_submitted, not case_received_date
            pd_val = get_column_value(row, PERM_COLUMN_MAPPINGS["case_submitted"])
            pd = parse_date_str(str(pd_val))
            if not pd:
                continue

            c_val = get_column_value(row, EXTRA_MAPPINGS["country"])
            country = normalize_country(str(c_val))

            # Pass EXTRA_MAPPINGS to normalize_visa_class or use it here
            visa_class = normalize_visa_class(row, EXTRA_MAPPINGS)

            key = (country, visa_class, pd.year, pd.month, status)
            agg[key] = agg.get(key, 0) + 1

    # Create Facts
    to_create = []
    import calendar

    for (country, visa_class, year, month, status), count in agg.items():
        ref_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        ref_end = date(year, month, last_day)

        dims = {"country": country, "visa_class": visa_class, "status": status}

        fact = RawFactsLedger(
            source=RawFactSource.DOL_PERM_DISCLOSURE,
            metric="perm_applications",
            dimensions=dims,
            value=count,
            reference_period_start=ref_start,
            reference_period_end=ref_end,
            publication_date=publication_date,
        )
        to_create.append(fact)

    with transaction.atomic():
        RawFactsLedger.objects.filter(
            source=RawFactSource.DOL_PERM_DISCLOSURE, publication_date=publication_date
        ).delete()
        RawFactsLedger.objects.bulk_create(to_create, batch_size=1000)

    logger.info(f"Ingested {len(to_create)} PERM facts from {filepath.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Specific file to ingest")
    parser.add_argument(
        "--pub-date", help="Publication date (YYYY-MM-DD)", required=True
    )
    args = parser.parse_args()

    pub_date = None
    if args.pub_date:
        pub_date = parse_date_str(args.pub_date)

    if not pub_date:
        logger.error("Invalid publication date")
        sys.exit(1)

    if args.file:
        process_file(Path(args.file), pub_date)
    else:
        # Scan directory?
        logger.info(f"Scanning {DATA_DIR}...")
        pass


if __name__ == "__main__":
    main()
