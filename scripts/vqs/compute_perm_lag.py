#!/usr/bin/env python3
"""
Compute PERM lag distribution from SalaryRecord and write to raw_facts_ledger.

Lag = decision_date - case_submitted (days). Histogram by 30-day buckets per
decision quarter. Used by VQS Model A (convolution) to de-aggregate I-140 receipts.

Usage:
  bazel run //scripts/vqs:compute_perm_lag [--publication-date YYYY-MM-DD]

When to use:
- After PERM data is ingested; run periodically or before running VQS simulation.
"""

import argparse
import logging
import os
from collections import defaultdict
from datetime import date, timedelta
from fractions import Fraction

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django
django.setup()

from django.db.utils import IntegrityError

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.raw_facts import RawFactsLedger, RawFactSource
from models.salary import SalaryRecord
from models.enums.visa_program import VisaProgram
from models.enums.case_status import CaseStatus
from models.enums.country import Country

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

BUCKET_DAYS = 30


def _quarter_dates(year: int, quarter: int) -> tuple[date, date]:
    """Return (start, end) for calendar quarter (Q1=Jan-Mar, Q2=Apr-Jun, ...)."""
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    if end_month > 12:
        end = date(year, 12, 31)
    else:
        next_month = date(year, end_month, 1) + timedelta(days=32)
        end = date(next_month.year, next_month.month, 1) - timedelta(days=1)
    return start, end


def compute_and_write_perm_lag(publication_date: date | None = None) -> int:
    """Compute PERM lag histogram per decision quarter and write to ledger. Returns count written.

    If --publication-date is given, all rows use that date.
    Otherwise, each row's publication_date is set to reference_period_end + 90 days
    for correct backtesting (data wasn't available instantly after the quarter).
    """
    use_historical = publication_date is None
    qs = (
        SalaryRecord.objects.filter(
            visa_program=VisaProgram.PERM,
            case_status=CaseStatus.CERTIFIED,
            case_submitted__isnull=False,
            decision_date__isnull=False,
        )
        .values_list("decision_date", "case_submitted")
    )
    by_quarter: dict[tuple[int, int], list[int]] = defaultdict(list)
    for decision_date, case_submitted in qs.iterator(chunk_size=5000):
        if not decision_date or not case_submitted:
            continue
        lag_days = (decision_date - case_submitted).days
        if lag_days < 0:
            continue
        q = (decision_date.year, (decision_date.month - 1) // 3 + 1)
        by_quarter[q].append(lag_days)

    count = 0
    for (year, quarter), lags in by_quarter.items():
        if not lags:
            continue
        hist: dict[int, float] = {}
        for d in lags:
            bucket = (d // BUCKET_DAYS) * BUCKET_DAYS
            hist[bucket] = hist.get(bucket, 0) + 1
        total = len(lags)
        value = {k: round(v / total, 4) for k, v in sorted(hist.items())}
        start, end = _quarter_dates(year, quarter)
        pub = end + timedelta(days=90) if use_historical else publication_date
        try:
            RawFactsLedger.objects.create(
                source=RawFactSource.DOL_PERM,
                metric="perm_lag_distribution",
                dimensions={"country": Country.ALL.value},
                value=value,
                reference_period_start=start,
                reference_period_end=end,
                publication_date=pub,
            )
            count += 1
        except IntegrityError:
            logger.debug("Skip duplicate perm_lag %s Q%s", year, quarter)
    logger.info("Wrote %d perm_lag_distribution rows to raw_facts_ledger", count)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute PERM lag distribution and write to raw_facts_ledger")
    parser.add_argument("--publication-date", type=str, help="Publication date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    script_logger.log_call(args={}, context="VQS: Compute PERM lag distribution")

    pub_date = date.fromisoformat(args.publication_date) if args.publication_date else None
    compute_and_write_perm_lag(publication_date=pub_date)


if __name__ == "__main__":
    main()
