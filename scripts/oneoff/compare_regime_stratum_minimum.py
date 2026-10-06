"""Counterfactual 80%-interval coverage for MIN_ERRORS_FOR_REGIME_STRATUM.

Re-derives the h=1 calibrated interval for every graded stored prediction since
--since under each minimum and reports coverage, tail misses and width. Read-only.

Usage:
  scripts/vqs/run_in_stg.sh -m scripts.oneoff.compare_regime_stratum_minimum --since 2025-01-01
"""

import argparse
import os
import statistics

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from datetime import date  # noqa: E402

from lib.business.vqs import calibration as cal  # noqa: E402
from lib.utils.logging_utils import log_context  # noqa: E402
from models.vqs import PredictedCutoff  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--minimums", type=int, nargs="+", default=[10, 20])
    ap.add_argument("--action", default="final_action")
    args = ap.parse_args()
    log_context(f"Counterfactual CI coverage for regime-stratum minimum {args.minimums}")

    rows = [
        r
        for r in PredictedCutoff.objects.filter(
            action_type=args.action,
            actual_date__isnull=False,
            predicted_date__isnull=False,
            bulletin__prediction_date__gte=date.fromisoformat(args.since),
        ).select_related("bulletin")
        if (r.bulletin.target_bulletin_month.year - r.bulletin.prediction_date.year) * 12
        + (r.bulletin.target_bulletin_month.month - r.bulletin.prediction_date.month)
        == 1
    ]
    rows.sort(key=lambda r: r.bulletin.prediction_date)
    print(f"{len(rows)} graded h=1 rows since {args.since}")

    for minimum in args.minimums:
        cal.MIN_ERRORS_FOR_REGIME_STRATUM = minimum
        hits = below = above = 0
        widths = []
        for r in rows:
            lo, hi = cal.compute_calibrated_interval(
                r.predicted_date, r.visa_class, r.country, args.action, r.bulletin.prediction_date, 1
            )
            widths.append((hi - lo).days)
            if r.actual_date < lo:
                below += 1
            elif r.actual_date > hi:
                above += 1
            else:
                hits += 1
        n = len(rows)
        print(
            f"min={minimum}: coverage {hits}/{n} = {hits / n:.1%}  below {below / n:.1%}  above {above / n:.1%}  "
            f"width median {statistics.median(widths)}d  p90 {sorted(widths)[int(0.9 * n)]}d  max {max(widths)}d"
        )


if __name__ == "__main__":
    main()
