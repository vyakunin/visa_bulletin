"""Analyze FY transition patterns: utilization rate vs jump/retrogression magnitude.

Computes FY utilization from DOS issuance data, collects historical transitions,
runs leave-one-year-out cross-validation on the conditional predictor, and
reports correlation statistics.

Usage:
    bazel run //scripts/vqs:analyze_fy_transitions
    bazel run //scripts/vqs:analyze_fy_transitions -- --action-type final_action
"""

import argparse
import logging
import os
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from lib.business.vqs.fy_utilization import (
    collect_fy_transitions,
    compute_backlog_depth,
    compute_utilization_rate,
    predict_october_jump_conditional,
    predict_september_retrogression_conditional,
)
from models.enums.country import Country
from models.raw_facts import RawFactsLedger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERIES = [
    (Country.INDIA.value, "1st", "India EB-1"),
    (Country.INDIA.value, "2nd", "India EB-2"),
    (Country.INDIA.value, "3rd", "India EB-3"),
    (Country.CHINA.value, "1st", "China EB-1"),
    (Country.CHINA.value, "2nd", "China EB-2"),
    (Country.CHINA.value, "3rd", "China EB-3"),
    (Country.ALL.value, "3rd", "ROW EB-3"),
]


def analyze_transitions(action_type: str, start_year: int, end_year: int):
    facts = list(RawFactsLedger.objects.all())
    logger.info(f"Loaded {len(facts)} raw facts")

    all_transitions = []

    for country, visa_class, label in SERIES:
        transitions = collect_fy_transitions(
            visa_class, country, action_type,
            start_year=start_year, end_year=end_year, facts=facts,
        )
        all_transitions.extend(transitions)

        print(f"\n{'=' * 90}")
        print(f"  {label} ({action_type})")
        print(f"{'=' * 90}")
        print(f"{'FY':<8} {'Oct Jump':<12} {'Sep Move':<12} {'Aug Move':<12} "
              f"{'Util Rate':<12} {'Backlog':<12} {'Pace':<10}")
        print("-" * 90)

        for t in transitions:
            oct_j = f"{t.october_jump_days:+d}d" if t.october_jump_days is not None else "N/A"
            sep_m = f"{t.september_move_days:+d}d" if t.september_move_days is not None else "N/A"
            aug_m = f"{t.august_move_days:+d}d" if t.august_move_days is not None else "N/A"
            util = f"{t.utilization_rate:.2f}" if t.utilization_rate is not None else "N/A"
            bl = f"{t.backlog_depth_days}d" if t.backlog_depth_days is not None else "N/A"
            pace = f"{t.prior_fy_avg_pace:.1f}" if t.prior_fy_avg_pace is not None else "N/A"
            print(f"{t.fiscal_year:<8} {oct_j:<12} {sep_m:<12} {aug_m:<12} "
                  f"{util:<12} {bl:<12} {pace:<10}")

    # Leave-one-year-out cross-validation
    print("\n\n" + "=" * 100)
    print("LEAVE-ONE-YEAR-OUT CROSS-VALIDATION: OCTOBER JUMP PREDICTION")
    print("=" * 100)

    for country, visa_class, label in SERIES:
        transitions = collect_fy_transitions(
            visa_class, country, action_type,
            start_year=start_year, end_year=end_year, facts=facts,
        )
        valid = [t for t in transitions if t.october_jump_days is not None]
        if len(valid) < 3:
            continue

        print(f"\n  {label}:")
        print(f"  {'FY':<8} {'Actual':<12} {'Unconditional':<16} {'Conditional':<16} "
              f"{'Uncond Err':<14} {'Cond Err':<14}")
        print("  " + "-" * 85)

        uncond_errors = []
        cond_errors = []

        for t in valid:
            # Unconditional: median of all other years' jumps
            others = [x.october_jump_days for x in valid if x.fiscal_year != t.fiscal_year]
            from statistics import median
            uncond_pred = int(median(others)) if others else 0

            # Conditional: use backlog and utilization
            cond_pred, diag = predict_october_jump_conditional(
                transitions, t.fiscal_year,
                current_backlog=t.backlog_depth_days,
                current_utilization=t.utilization_rate,
            )

            uncond_err = abs(t.october_jump_days - uncond_pred)
            cond_err = abs(t.october_jump_days - cond_pred)
            uncond_errors.append(uncond_err)
            cond_errors.append(cond_err)

            print(f"  {t.fiscal_year:<8} {t.october_jump_days:+6d}d    {uncond_pred:+6d}d          "
                  f"{cond_pred:+6d}d          {uncond_err:5d}d         {cond_err:5d}d")

        if uncond_errors:
            uncond_mae = sum(uncond_errors) / len(uncond_errors)
            cond_mae = sum(cond_errors) / len(cond_errors)
            improvement = ((uncond_mae - cond_mae) / uncond_mae * 100) if uncond_mae > 0 else 0
            print(f"  {'MAE:':<8} {'':>18} {'':>16} {uncond_mae:10.1f}d      {cond_mae:8.1f}d   ({improvement:+.1f}%)")

    # Same for September
    print("\n\n" + "=" * 100)
    print("LEAVE-ONE-YEAR-OUT CROSS-VALIDATION: SEPTEMBER RETROGRESSION")
    print("=" * 100)

    for country, visa_class, label in SERIES:
        transitions = collect_fy_transitions(
            visa_class, country, action_type,
            start_year=start_year, end_year=end_year, facts=facts,
        )
        valid = [t for t in transitions if t.september_move_days is not None]
        if len(valid) < 3:
            continue

        print(f"\n  {label}:")
        print(f"  {'FY':<8} {'Actual':<12} {'Unconditional':<16} {'Conditional':<16} "
              f"{'Uncond Err':<14} {'Cond Err':<14}")
        print("  " + "-" * 85)

        uncond_errors = []
        cond_errors = []

        for t in valid:
            others = [x.september_move_days for x in valid if x.fiscal_year != t.fiscal_year]
            from statistics import median
            uncond_pred = int(median(others)) if others else 0

            cond_pred, diag = predict_september_retrogression_conditional(
                transitions, t.fiscal_year,
                current_backlog=t.backlog_depth_days,
                current_utilization=t.utilization_rate,
            )

            uncond_err = abs(t.september_move_days - uncond_pred)
            cond_err = abs(t.september_move_days - cond_pred)
            uncond_errors.append(uncond_err)
            cond_errors.append(cond_err)

            print(f"  {t.fiscal_year:<8} {t.september_move_days:+6d}d    {uncond_pred:+6d}d          "
                  f"{cond_pred:+6d}d          {uncond_err:5d}d         {cond_err:5d}d")

        if uncond_errors:
            uncond_mae = sum(uncond_errors) / len(uncond_errors)
            cond_mae = sum(cond_errors) / len(cond_errors)
            improvement = ((uncond_mae - cond_mae) / uncond_mae * 100) if uncond_mae > 0 else 0
            print(f"  {'MAE:':<8} {'':>18} {'':>16} {uncond_mae:10.1f}d      {cond_mae:8.1f}d   ({improvement:+.1f}%)")

    # Cross-series pooled analysis
    print("\n\n" + "=" * 100)
    print("CROSS-SERIES POOLED STATISTICS")
    print("=" * 100)

    oct_with_util = [t for t in all_transitions
                     if t.october_jump_days is not None and t.utilization_rate is not None]
    oct_with_backlog = [t for t in all_transitions
                        if t.october_jump_days is not None and t.backlog_depth_days is not None]

    if oct_with_util:
        print(f"\n  October jump vs utilization rate (n={len(oct_with_util)}):")
        # Simple correlation
        jumps = [t.october_jump_days for t in oct_with_util]
        utils = [t.utilization_rate for t in oct_with_util]
        mean_j = sum(jumps) / len(jumps)
        mean_u = sum(utils) / len(utils)
        cov = sum((j - mean_j) * (u - mean_u) for j, u in zip(jumps, utils)) / len(jumps)
        std_j = (sum((j - mean_j) ** 2 for j in jumps) / len(jumps)) ** 0.5
        std_u = (sum((u - mean_u) ** 2 for u in utils) / len(utils)) ** 0.5
        r = cov / (std_j * std_u) if std_j > 0 and std_u > 0 else 0
        print(f"    Pearson r = {r:.3f}  (positive = higher utilization → bigger jump)")

    if oct_with_backlog:
        print(f"\n  October jump vs backlog depth (n={len(oct_with_backlog)}):")
        jumps = [t.october_jump_days for t in oct_with_backlog]
        backlogs = [t.backlog_depth_days for t in oct_with_backlog]
        mean_j = sum(jumps) / len(jumps)
        mean_b = sum(backlogs) / len(backlogs)
        cov = sum((j - mean_j) * (b - mean_b) for j, b in zip(jumps, backlogs)) / len(jumps)
        std_j = (sum((j - mean_j) ** 2 for j in jumps) / len(jumps)) ** 0.5
        std_b = (sum((b - mean_b) ** 2 for b in backlogs) / len(backlogs)) ** 0.5
        r = cov / (std_j * std_b) if std_j > 0 and std_b > 0 else 0
        print(f"    Pearson r = {r:.3f}  (positive = deeper backlog → bigger jump)")

    sep_with_util = [t for t in all_transitions
                     if t.september_move_days is not None and t.utilization_rate is not None]
    if sep_with_util:
        print(f"\n  September move vs utilization rate (n={len(sep_with_util)}):")
        moves = [t.september_move_days for t in sep_with_util]
        utils = [t.utilization_rate for t in sep_with_util]
        mean_m = sum(moves) / len(moves)
        mean_u = sum(utils) / len(utils)
        cov = sum((m - mean_m) * (u - mean_u) for m, u in zip(moves, utils)) / len(moves)
        std_m = (sum((m - mean_m) ** 2 for m in moves) / len(moves)) ** 0.5
        std_u = (sum((u - mean_u) ** 2 for u in utils) / len(utils)) ** 0.5
        r = cov / (std_m * std_u) if std_m > 0 and std_u > 0 else 0
        print(f"    Pearson r = {r:.3f}  (negative = higher utilization → more retrogression)")


def main():
    parser = argparse.ArgumentParser(description="Analyze FY Transitions")
    parser.add_argument("--action-type", default="filing")
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    analyze_transitions(args.action_type, args.start_year, args.end_year)


if __name__ == "__main__":
    main()
