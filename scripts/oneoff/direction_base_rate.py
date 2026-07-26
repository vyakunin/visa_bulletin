#!/usr/bin/env python3
"""Base rate of ADVANCE among months that actually moved, per series.

This is the conditional direction accuracy that an "always predict advance"
constant classifier scores — the null baseline any claimed direction accuracy
must clear before it counts as signal. Written for §26, which found the
Demand-Supply queue model's advertised 69% direction accuracy to be exactly
this base rate (the model is structurally incapable of predicting a
retrogression).

The permanent home for this measurement is the ``UpBase%`` column in
``scripts/vqs/evaluate_model.py --per-series-summary``; this script exists to
answer the same question in seconds instead of a ~1h walk-forward eval.

Run against the staging (prod-copy) DB:
    scripts/vqs/run_in_stg.sh scripts/oneoff/direction_base_rate.py
"""

import argparse
import datetime
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.utils.logging_utils import log_context  # noqa: E402
from models.enums.country import Country  # noqa: E402
from models.visa_cutoff_date import VisaCutoffDate  # noqa: E402

SERIES = [
    (Country.INDIA.value, "2nd", "India EB-2"),
    (Country.INDIA.value, "3rd", "India EB-3"),
    (Country.CHINA.value, "2nd", "China EB-2"),
    (Country.CHINA.value, "3rd", "China EB-3"),
    (Country.CHINA.value, "1st", "China EB-1"),
    (Country.INDIA.value, "1st", "India EB-1"),
]
START = datetime.date(2016, 1, 1)
# 30 matches evaluate_model.compute_metrics' cond_direction_acc filter (|move| > 30d);
# 0 matches its direction_acc filter (any non-zero move), which is what the public
# methodology page's "Dir%" column reports.
DEFAULT_MOVE_MIN = 30


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--move-min", type=int, default=DEFAULT_MOVE_MIN,
        help="A month counts as 'moved' when |move| exceeds this. 30 = CondDir filter, "
             "0 = the any-non-zero-move filter behind the public Dir%% column.",
    )
    args = parser.parse_args()
    move_min = args.move_min

    log_context("§26: direction base rate — is 'high direction accuracy' just 'advance is common'?")
    print(f"move_min = {move_min} (a month 'moved' when |move| > {move_min})")
    print(f"{'Series':<12} {'action':<13} {'movers':>9} {'advances':>9} {'UpBase%':>8} {'retros':>7}")
    print("-" * 64)
    for action in ("filing", "final_action"):
        tot_n = tot_up = 0
        for country, visa_class, label in SERIES:
            rows = (
                VisaCutoffDate.objects.filter(
                    visa_class=visa_class, country=country, action_type=action,
                    bulletin__publication_date__gte=START,
                )
                .order_by("bulletin__publication_date")
                .values_list("cutoff_date", flat=True)
            )
            cutoffs = [c for c in rows if c]
            moves = [(cutoffs[i] - cutoffs[i - 1]).days for i in range(1, len(cutoffs))]
            significant = [m for m in moves if abs(m) > move_min]
            advances = sum(1 for m in significant if m > 0)
            tot_n += len(significant)
            tot_up += advances
            pct = f"{advances / len(significant) * 100:.1f}" if significant else "n/a"
            print(f"{label:<12} {action:<13} {len(significant):>9} {advances:>9} {pct:>8} {len(significant) - advances:>7}")
        pct = f"{tot_up / tot_n * 100:.1f}" if tot_n else "n/a"
        print(f"{'ALL 6':<12} {action:<13} {tot_n:>9} {tot_up:>9} {pct:>8} {tot_n - tot_up:>7}\n")


if __name__ == "__main__":
    main()
