"""FY Boundary A/B Backtest: compare baseline vs FY-aware solver at fiscal year transitions.

Runs the solver with and without fy_boundary_aware for every September knowledge date
(predicting October) and July/August knowledge dates (predicting Aug/Sep).
Computes per-transition MAE and aggregates for each mode.

Usage:
    bazel run //scripts/vqs:backtest_fy_boundary
    bazel run //scripts/vqs:backtest_fy_boundary -- --action-type filing
    bazel run //scripts/vqs:backtest_fy_boundary -- --start-year 2019 --end-year 2025
"""

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from lib.business.vqs.data_cache import get_cutoff_at_date
from lib.business.vqs.solver import predict_next_bulletin_and_maturity
from models.enums.country import Country
from models.raw_facts import RawFactsLedger

logging.basicConfig(level=logging.INFO)
logging.getLogger("lib.business.vqs.solver").setLevel(logging.WARNING)
logging.getLogger("lib.business.vqs.aggregator").setLevel(logging.WARNING)
logging.getLogger("lib.business.vqs.expert_pool").setLevel(logging.WARNING)
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

# FY boundary predictions: (knowledge_month, target_month, label)
FY_BOUNDARY_MONTHS = [
    (7, 8, "Aug (end FY)"),
    (8, 9, "Sep (end FY)"),
    (9, 10, "Oct (new FY)"),
]

# Non-boundary months for comparison
NON_BOUNDARY_MONTHS = [
    (11, 12, "Dec"),
    (1, 2, "Feb"),
    (3, 4, "Apr"),
    (5, 6, "Jun"),
]


@dataclass
class BacktestResult:
    series: str
    year: int
    knowledge_month: int
    target_month: int
    month_label: str
    baseline_pred: date | None
    patched_pred: date | None
    actual: date | None
    baseline_error_days: int | None
    patched_error_days: int | None
    baseline_persistence_w: float
    patched_persistence_w: float


def run_single_prediction(
    knowledge_date: date,
    visa_class: str,
    country: int,
    action_type: str,
    fy_boundary_aware: bool,
    facts: list,
) -> tuple[date | None, float]:
    """Run solver and return (predicted_cutoff, persistence_weight)."""
    outcome = predict_next_bulletin_and_maturity(
        knowledge_date=knowledge_date,
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        facts=facts,
        fy_boundary_aware=fy_boundary_aware,
    )
    pw = outcome.metadata.get("persistence_weight", 0.0)
    return outcome.predicted_cutoff, pw


def run_backtest(
    start_year: int,
    end_year: int,
    action_type: str,
    include_non_boundary: bool = True,
) -> list[BacktestResult]:
    results: list[BacktestResult] = []

    all_months = FY_BOUNDARY_MONTHS[:]
    if include_non_boundary:
        all_months.extend(NON_BOUNDARY_MONTHS)

    for country, visa_class, series_label in SERIES:
        logger.info(f"Processing {series_label}...")

        for year in range(start_year, end_year + 1):
            for kd_month, tgt_month, month_label in all_months:
                kd_year = year if kd_month <= 12 else year + 1
                tgt_year = year if tgt_month > kd_month else year + 1
                if tgt_month < kd_month:
                    tgt_year = year + 1

                knowledge_date = date(kd_year, kd_month, 15)
                facts = list(
                    RawFactsLedger.objects.filter(publication_date__lte=knowledge_date)
                )

                actual = get_cutoff_at_date(
                    visa_class, country, action_type,
                    date(tgt_year, tgt_month, 1),
                )

                baseline_pred, baseline_pw = run_single_prediction(
                    knowledge_date, visa_class, country, action_type,
                    fy_boundary_aware=False, facts=facts,
                )
                patched_pred, patched_pw = run_single_prediction(
                    knowledge_date, visa_class, country, action_type,
                    fy_boundary_aware=True, facts=facts,
                )

                baseline_err = (
                    abs((baseline_pred - actual).days)
                    if baseline_pred and actual else None
                )
                patched_err = (
                    abs((patched_pred - actual).days)
                    if patched_pred and actual else None
                )

                results.append(BacktestResult(
                    series=series_label,
                    year=year,
                    knowledge_month=kd_month,
                    target_month=tgt_month,
                    month_label=month_label,
                    baseline_pred=baseline_pred,
                    patched_pred=patched_pred,
                    actual=actual,
                    baseline_error_days=baseline_err,
                    patched_error_days=patched_err,
                    baseline_persistence_w=baseline_pw,
                    patched_persistence_w=patched_pw,
                ))

    return results


def print_results(results: list[BacktestResult]) -> None:
    # Per-transition detail
    print("\n" + "=" * 120)
    print("DETAILED FY BOUNDARY RESULTS")
    print("=" * 120)
    print(f"{'Series':<16} {'Year':<6} {'Month':<16} {'Baseline MAE':<14} {'Patched MAE':<14} "
          f"{'Improvement':<14} {'Base PW':<10} {'Patch PW':<10}")
    print("-" * 120)

    for r in sorted(results, key=lambda x: (x.series, x.year, x.target_month)):
        if r.target_month not in (8, 9, 10):
            continue
        b_err = f"{r.baseline_error_days}d" if r.baseline_error_days is not None else "N/A"
        p_err = f"{r.patched_error_days}d" if r.patched_error_days is not None else "N/A"
        if r.baseline_error_days is not None and r.patched_error_days is not None:
            diff = r.baseline_error_days - r.patched_error_days
            imp = f"{diff:+d}d" if diff != 0 else "same"
        else:
            imp = "N/A"
        print(f"{r.series:<16} {r.year:<6} {r.month_label:<16} {b_err:<14} {p_err:<14} "
              f"{imp:<14} {r.baseline_persistence_w:<10.2f} {r.patched_persistence_w:<10.2f}")

    # Aggregate by month type
    print("\n" + "=" * 100)
    print("AGGREGATE COMPARISON")
    print("=" * 100)

    for label, month_set in [("FY Boundary (Aug/Sep/Oct)", {8, 9, 10}),
                              ("Non-Boundary", {2, 4, 6, 12}),
                              ("October only", {10}),
                              ("Aug/Sep only", {8, 9})]:
        boundary_results = [r for r in results
                           if r.target_month in month_set
                           and r.baseline_error_days is not None
                           and r.patched_error_days is not None]
        if not boundary_results:
            continue

        baseline_mae = sum(r.baseline_error_days for r in boundary_results) / len(boundary_results)
        patched_mae = sum(r.patched_error_days for r in boundary_results) / len(boundary_results)
        improvement_pct = ((baseline_mae - patched_mae) / baseline_mae * 100) if baseline_mae > 0 else 0

        wins = sum(1 for r in boundary_results if r.patched_error_days < r.baseline_error_days)
        losses = sum(1 for r in boundary_results if r.patched_error_days > r.baseline_error_days)
        ties = len(boundary_results) - wins - losses

        print(f"\n  {label} (n={len(boundary_results)}):")
        print(f"    Baseline MAE:  {baseline_mae:8.1f} days")
        print(f"    Patched MAE:   {patched_mae:8.1f} days")
        print(f"    Improvement:   {improvement_pct:+.1f}%")
        print(f"    Win/Loss/Tie:  {wins}/{losses}/{ties}")

    # Per-series aggregate
    print("\n" + "=" * 100)
    print("PER-SERIES FY BOUNDARY (Aug/Sep/Oct)")
    print("=" * 100)
    print(f"{'Series':<20} {'N':<6} {'Baseline MAE':<14} {'Patched MAE':<14} {'Change %':<12} {'Wins':<8}")
    print("-" * 80)

    series_names = sorted(set(r.series for r in results))
    for series in series_names:
        sr = [r for r in results
              if r.series == series and r.target_month in (8, 9, 10)
              and r.baseline_error_days is not None and r.patched_error_days is not None]
        if not sr:
            continue
        b_mae = sum(r.baseline_error_days for r in sr) / len(sr)
        p_mae = sum(r.patched_error_days for r in sr) / len(sr)
        pct = ((b_mae - p_mae) / b_mae * 100) if b_mae > 0 else 0
        wins = sum(1 for r in sr if r.patched_error_days < r.baseline_error_days)
        print(f"{series:<20} {len(sr):<6} {b_mae:<14.1f} {p_mae:<14.1f} {pct:+.1f}%{'':>5} {wins}/{len(sr)}")


def main():
    parser = argparse.ArgumentParser(description="FY Boundary A/B Backtest")
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--action-type", default="filing")
    parser.add_argument("--no-non-boundary", action="store_true",
                        help="Skip non-boundary months (faster)")
    args = parser.parse_args()

    results = run_backtest(
        start_year=args.start_year,
        end_year=args.end_year,
        action_type=args.action_type,
        include_non_boundary=not args.no_non_boundary,
    )
    print_results(results)


if __name__ == "__main__":
    main()
