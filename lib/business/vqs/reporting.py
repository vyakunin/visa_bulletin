"""VQS Automated Reporting Module.

Provides post-ingest evaluation logic for Visa Bulletins.
"""

import logging
from datetime import date

from lib.business.vqs.accuracy_metrics import (
    compute_bulletin_accuracy,
    compute_bulletin_accuracy_summary,
    compute_ci_coverage,
)

logger = logging.getLogger(__name__)


def run_post_ingest_evaluation(bulletin_date: date):
    """Trigger accuracy and coverage evaluation for a newly ingested bulletin."""
    logger.info(f"Triggering VQS evaluation for bulletin: {bulletin_date}")

    try:
        rows = compute_bulletin_accuracy(bulletins=[bulletin_date], exclude_eb4=True)

        if not rows:
            logger.warning(f"No accuracy rows generated for {bulletin_date}")
            return

        ci_result = compute_ci_coverage(rows)
        summary = compute_bulletin_accuracy_summary(rows)
        overall = summary.get("overall", {})
        mae = overall.get("mean_abs_error_days")
        bias = overall.get("mean_error_days")

        logger.info("VQS Automated Report:")
        logger.info(f"  Bulletin: {bulletin_date}")
        if mae is None:
            logger.info(
                f"  MAE (EB1-3,5): n/a — no scoreable predictions "
                f"({len(rows)} row(s), all Current/Unavailable or unpredicted)"
            )
        else:
            logger.info(
                f"  MAE (EB1-3,5): {mae:.1f} days "
                f"(bias {bias:+.1f}, n={overall.get('count')})"
            )
        logger.info(
            f"  CI Coverage:   {ci_result.coverage_rate * 100:.1f}% "
            f"({ci_result.hits}/{ci_result.total_with_ci})"
        )

    except Exception as e:
        logger.error(f"Failed to run VQS evaluation: {e}")
