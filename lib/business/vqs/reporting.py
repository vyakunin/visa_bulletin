"""VQS Automated Reporting Module.

Provides post-ingest evaluation logic for Visa Bulletins.
"""

import logging
from datetime import date

from lib.business.vqs.accuracy_metrics import (
    compute_bulletin_accuracy,
    compute_bulletin_accuracy_summary,
)

logger = logging.getLogger(__name__)


def run_post_ingest_evaluation(bulletin_date: date):
    """
    Trigger accuracy and coverage evaluation for a newly ingested bulletin.
    """
    logger.info(f"Triggering VQS evaluation for bulletin: {bulletin_date}")

    try:
        # 1. Run evaluation for this specific bulletin (walk-forward safe)
        # We use a 1-bulletin range to get the latest hit/miss report.
        rows = compute_bulletin_accuracy(bulletins=[bulletin_date], exclude_eb4=True)

        if not rows:
            logger.warning(f"No accuracy rows generated for {bulletin_date}")
            return

        # 2. Calculate Coverage (Confidence Interval Hit Rate)
        hits = 0
        total = 0
        for r in rows:
            if r.predicted_cutoff and r.confidence_low and r.confidence_high:
                total += 1
                if r.confidence_low <= r.actual_cutoff <= r.confidence_high:
                    hits += 1

        coverage = (hits / total * 100) if total > 0 else 0

        # 3. Calculate MAE for this bulletin
        summary = compute_bulletin_accuracy_summary(rows)
        mae = summary.get("overall", {}).get("mean_error_days")

        # 4. Success Log
        logger.info("VQS Automated Report:")
        logger.info(f"  Bulletin: {bulletin_date}")
        logger.info(f"  MAE (EB1-3,5): {mae:.1f} days")
        logger.info(f"  CI Coverage:   {coverage:.1f}% ({hits}/{total})")

    except Exception as e:
        logger.error(f"Failed to run VQS evaluation: {e}")
