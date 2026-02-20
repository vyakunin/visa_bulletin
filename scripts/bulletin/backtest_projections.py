#!/usr/bin/env python3
"""
Backtest the current visa bulletin projection system against historical data.

Measures how accurately the 12-month rolling average projection predicts
future visa cutoff dates at various horizons (1, 3, 6, 12 months ahead).

Usage:
    bazel run //scripts/bulletin:backtest_projections
    bazel run //scripts/bulletin:backtest_projections -- --horizons 1 3 6 --min-eval-year 2018
    bazel run //scripts/bulletin:backtest_projections -- --category employment_based --country 3

Output:
    Per-series and aggregate MAE (mean absolute error) in days,
    broken down by visa_class, country, action_type, and horizon.
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
django.setup()

from lib.business.bulletin.cutoff_projection import calculate_projection
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.employment_preference import EmploymentPreference
from models.enums.visa_category import VisaCategory
from models.visa_cutoff_date import VisaCutoffDate

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """Single backtesting prediction result"""

    visa_class: str
    country: int
    action_type: str
    eval_month: date
    horizon: int
    actual_date: date
    predicted_date: date | None
    status: str
    error_days: int | None


@dataclass
class SeriesStats:
    """Aggregated stats for one (visa_class, country, action_type) series"""

    visa_class: str
    country_label: str
    action_type: str
    horizon: int
    n_predictions: int = 0
    n_successful: int = 0
    n_no_movement: int = 0
    n_failed: int = 0
    errors: list[int] = field(default_factory=list)

    @property
    def mae(self) -> float | None:
        if not self.errors:
            return None
        return sum(abs(e) for e in self.errors) / len(self.errors)

    @property
    def median_ae(self) -> float | None:
        if not self.errors:
            return None
        sorted_errors = sorted(abs(e) for e in self.errors)
        n = len(sorted_errors)
        if n % 2 == 0:
            return (sorted_errors[n // 2 - 1] + sorted_errors[n // 2]) / 2
        return sorted_errors[n // 2]

    @property
    def mean_error(self) -> float | None:
        """Signed mean error: positive = pessimistic, negative = optimistic"""
        if not self.errors:
            return None
        return sum(self.errors) / len(self.errors)

    @property
    def pct_within_90d(self) -> float | None:
        if not self.errors:
            return None
        return sum(1 for e in self.errors if abs(e) <= 90) / len(self.errors) * 100

    @property
    def pct_within_180d(self) -> float | None:
        if not self.errors:
            return None
        return sum(1 for e in self.errors if abs(e) <= 180) / len(self.errors) * 100


def load_cutoff_series() -> dict[tuple[str, int, str], list[tuple[date, date | None]]]:
    """
    Load all VisaCutoffDate data grouped by (visa_class_normalized, country, action_type).
    Returns a dict mapping series key to sorted list of (publication_date, cutoff_date) tuples.
    """
    all_data = (
        VisaCutoffDate.objects.select_related("bulletin")
        .order_by("visa_class", "bulletin__publication_date")
        .values_list(
            "visa_class",
            "bulletin__publication_date",
            "country",
            "action_type",
            "cutoff_date",
            "is_current",
            "is_unavailable",
            "visa_category",
        )
    )

    series: dict[tuple[str, int, str], list[tuple[date, date | None]]] = defaultdict(
        list
    )

    for (
        visa_class,
        pub_date,
        country,
        action_type,
        cutoff_date,
        is_current,
        is_unavailable,
        visa_category,
    ) in all_data:
        if visa_category == VisaCategory.EMPLOYMENT_BASED.value:
            display = EmploymentPreference.normalize_for_display(visa_class)
            if not display or display == visa_class:
                continue
            key_class = display
        else:
            key_class = visa_class

        effective_cutoff: date | None
        if is_current:
            effective_cutoff = pub_date
        elif is_unavailable:
            effective_cutoff = None
        else:
            effective_cutoff = cutoff_date

        key = (key_class, country, action_type)
        series[key].append((pub_date, effective_cutoff))

    # Sort each series by publication date and deduplicate
    for key in series:
        seen_dates: set[date] = set()
        deduped: list[tuple[date, date | None]] = []
        for pub_date, cutoff in sorted(series[key], key=lambda x: x[0]):
            if pub_date not in seen_dates:
                seen_dates.add(pub_date)
                deduped.append((pub_date, cutoff))
        series[key] = deduped

    return dict(series)


def backtest_series(
    pub_dates: list[date],
    cutoff_dates: list[date | None],
    horizons: list[int],
    min_eval_year: int,
    min_training_months: int = 12,
) -> list[PredictionResult]:
    """
    Run backtest on a single time series.

    For each evaluation month M (with enough prior data), and each horizon H:
    1. Use data up to M to build the projection
    2. Find the actual cutoff at M+H
    3. Call calculate_projection with submission_date = actual cutoff at M+H
    4. Record the error between predicted date and actual date M+H
    """
    results: list[PredictionResult] = []
    n = len(pub_dates)

    for eval_idx in range(min_training_months, n):
        eval_pub = pub_dates[eval_idx]
        if eval_pub.year < min_eval_year:
            continue

        for horizon in horizons:
            target_idx = eval_idx + horizon
            if target_idx >= n:
                continue

            target_pub = pub_dates[target_idx]
            target_cutoff = cutoff_dates[target_idx]

            if target_cutoff is None:
                continue

            train_dates = pub_dates[:eval_idx]
            train_cutoffs = cutoff_dates[:eval_idx]

            projection = calculate_projection(train_dates, train_cutoffs, target_cutoff)

            if projection is None:
                results.append(
                    PredictionResult(
                        visa_class="",
                        country=0,
                        action_type="",
                        eval_month=eval_pub,
                        horizon=horizon,
                        actual_date=target_pub,
                        predicted_date=None,
                        status="insufficient_data",
                        error_days=None,
                    )
                )
                continue

            status = projection["status"]
            estimated = projection.get("estimated_date")

            error_days: int | None = None
            if status in ("projected", "projected_historical") and estimated:
                error_days = (estimated - target_pub).days
            elif status == "current":
                error_days = 0

            results.append(
                PredictionResult(
                    visa_class="",
                    country=0,
                    action_type="",
                    eval_month=eval_pub,
                    horizon=horizon,
                    actual_date=target_pub,
                    predicted_date=estimated,
                    status=status,
                    error_days=error_days,
                )
            )

    return results


def aggregate_results(
    all_results: dict[tuple[str, int, str], list[PredictionResult]],
    horizons: list[int],
) -> tuple[dict[tuple[str, int, str, int], SeriesStats], dict[int, SeriesStats]]:
    """
    Aggregate prediction results into per-series and overall stats.
    Returns (per_series_stats, overall_stats_by_horizon).
    """
    per_series: dict[tuple[str, int, str, int], SeriesStats] = {}
    overall: dict[int, SeriesStats] = {
        h: SeriesStats(
            visa_class="ALL",
            country_label="ALL",
            action_type="ALL",
            horizon=h,
        )
        for h in horizons
    }

    for (visa_class, country, action_type), results in all_results.items():
        country_label = _country_label(country)

        for h in horizons:
            h_results = [r for r in results if r.horizon == h]
            if not h_results:
                continue

            stats = SeriesStats(
                visa_class=visa_class,
                country_label=country_label,
                action_type=action_type,
                horizon=h,
            )

            for r in h_results:
                stats.n_predictions += 1
                overall[h].n_predictions += 1

                if r.error_days is not None:
                    stats.n_successful += 1
                    stats.errors.append(r.error_days)
                    overall[h].n_successful += 1
                    overall[h].errors.append(r.error_days)
                elif r.status == "no_movement":
                    stats.n_no_movement += 1
                    overall[h].n_no_movement += 1
                else:
                    stats.n_failed += 1
                    overall[h].n_failed += 1

            per_series[(visa_class, country, action_type, h)] = stats

    return per_series, overall


def _country_label(country_val: int) -> str:
    try:
        return Country(country_val).label
    except ValueError:
        return str(country_val)


def print_report(
    per_series: dict[tuple[str, int, str, int], SeriesStats],
    overall: dict[int, SeriesStats],
    horizons: list[int],
    output_json: str | None = None,
) -> None:
    """Print human-readable report and optionally save JSON."""

    print("\n" + "=" * 90)
    print("VISA BULLETIN PROJECTION BACKTEST RESULTS")
    print("=" * 90)

    print("\n--- OVERALL (all series) ---\n")
    print(
        f"{'Horizon':>8} {'N':>6} {'OK':>6} {'NoMov':>6} {'Fail':>6} "
        f"{'MAE(d)':>8} {'MedAE':>8} {'MeanE':>8} {'<90d':>6} {'<180d':>7}"
    )
    print("-" * 90)

    for h in horizons:
        s = overall[h]
        mae_str = f"{s.mae:.0f}" if s.mae is not None else "—"
        med_str = f"{s.median_ae:.0f}" if s.median_ae is not None else "—"
        me_str = f"{s.mean_error:+.0f}" if s.mean_error is not None else "—"
        p90_str = f"{s.pct_within_90d:.0f}%" if s.pct_within_90d is not None else "—"
        p180_str = f"{s.pct_within_180d:.0f}%" if s.pct_within_180d is not None else "—"
        print(
            f"{h:>5}mo  {s.n_predictions:>6} {s.n_successful:>6} {s.n_no_movement:>6} "
            f"{s.n_failed:>6} {mae_str:>8} {med_str:>8} {me_str:>8} {p90_str:>6} {p180_str:>7}"
        )

    # Per-series breakdown (only for series with enough data)
    for h in horizons:
        series_for_h = sorted(
            (
                (k, v)
                for k, v in per_series.items()
                if k[3] == h and v.n_successful >= 5
            ),
            key=lambda x: x[1].mae or 0,
        )
        if not series_for_h:
            continue

        print(
            f"\n--- HORIZON {h} MONTHS: Per-Series (sorted by MAE, min 5 predictions) ---\n"
        )
        print(
            f"{'Visa Class':<42} {'Country':<20} {'Type':<8} {'N':>4} "
            f"{'MAE':>7} {'MedAE':>7} {'MeanE':>8} {'<90d':>5} {'<180d':>6}"
        )
        print("-" * 120)

        for _key, s in series_for_h:
            mae_str = f"{s.mae:.0f}" if s.mae is not None else "—"
            med_str = f"{s.median_ae:.0f}" if s.median_ae is not None else "—"
            me_str = f"{s.mean_error:+.0f}" if s.mean_error is not None else "—"
            p90_str = (
                f"{s.pct_within_90d:.0f}%" if s.pct_within_90d is not None else "—"
            )
            p180_str = (
                f"{s.pct_within_180d:.0f}%" if s.pct_within_180d is not None else "—"
            )
            at_short = "FA" if s.action_type == ActionType.FINAL_ACTION.value else "DF"
            print(
                f"{s.visa_class:<42} {s.country_label:<20} {at_short:<8} {s.n_successful:>4} "
                f"{mae_str:>7} {med_str:>7} {me_str:>8} {p90_str:>5} {p180_str:>6}"
            )

    if output_json:
        _save_json(per_series, overall, horizons, output_json)


def _save_json(
    per_series: dict,
    overall: dict,
    horizons: list[int],
    path: str,
) -> None:
    """Save results as JSON for later analysis."""
    data = {
        "overall": {
            str(h): {
                "n_predictions": s.n_predictions,
                "n_successful": s.n_successful,
                "n_no_movement": s.n_no_movement,
                "n_failed": s.n_failed,
                "mae_days": round(s.mae, 1) if s.mae is not None else None,
                "median_ae_days": round(s.median_ae, 1)
                if s.median_ae is not None
                else None,
                "mean_error_days": round(s.mean_error, 1)
                if s.mean_error is not None
                else None,
                "pct_within_90d": round(s.pct_within_90d, 1)
                if s.pct_within_90d is not None
                else None,
                "pct_within_180d": round(s.pct_within_180d, 1)
                if s.pct_within_180d is not None
                else None,
            }
            for h, s in overall.items()
        },
        "per_series": [
            {
                "visa_class": s.visa_class,
                "country": s.country_label,
                "action_type": s.action_type,
                "horizon": s.horizon,
                "n_successful": s.n_successful,
                "mae_days": round(s.mae, 1) if s.mae is not None else None,
                "median_ae_days": round(s.median_ae, 1)
                if s.median_ae is not None
                else None,
                "mean_error_days": round(s.mean_error, 1)
                if s.mean_error is not None
                else None,
            }
            for s in per_series.values()
            if s.n_successful >= 5
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nJSON results saved to: {path}")


def main():
    parser = argparse.ArgumentParser(description="Backtest visa bulletin projections")
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 3, 6, 12],
        help="Prediction horizons in months (default: 1 3 6 12)",
    )
    parser.add_argument(
        "--min-eval-year",
        type=int,
        default=2016,
        help="Earliest evaluation year (default: 2016)",
    )
    parser.add_argument(
        "--category",
        choices=["employment_based", "family_sponsored"],
        help="Filter to a specific visa category",
    )
    parser.add_argument(
        "--country",
        type=int,
        help="Filter to a specific country code (e.g., 3 for India)",
    )
    parser.add_argument(
        "--action-type",
        choices=["final_action", "filing"],
        help="Filter to a specific action type",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Save results as JSON to this path",
    )
    parser.add_argument(
        "--min-training-months",
        type=int,
        default=12,
        help="Minimum months of training data before first evaluation (default: 12)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    logger.info("Loading cutoff data from database...")
    all_series = load_cutoff_series()
    logger.info(
        f"Loaded {len(all_series)} unique (visa_class, country, action_type) series"
    )

    # Apply filters
    filtered_series = {}
    for (visa_class, country, action_type), data in all_series.items():
        if args.country is not None and country != args.country:
            continue
        if args.action_type and action_type != args.action_type:
            continue
        if args.category:
            is_eb = any(visa_class.startswith(f"EB-{i}") for i in range(1, 6))
            if args.category == "employment_based" and not is_eb:
                continue
            if args.category == "family_sponsored" and is_eb:
                continue
        filtered_series[(visa_class, country, action_type)] = data

    logger.info(f"After filters: {len(filtered_series)} series")

    all_results: dict[tuple[str, int, str], list[PredictionResult]] = {}
    total_predictions = 0

    for (visa_class, country, action_type), data in filtered_series.items():
        pub_dates = [d[0] for d in data]
        cutoff_dates = [d[1] for d in data]

        results = backtest_series(
            pub_dates,
            cutoff_dates,
            horizons=args.horizons,
            min_eval_year=args.min_eval_year,
            min_training_months=args.min_training_months,
        )

        for r in results:
            r.visa_class = visa_class
            r.country = country
            r.action_type = action_type

        all_results[(visa_class, country, action_type)] = results
        total_predictions += len(results)

    logger.info(f"Total predictions evaluated: {total_predictions}")

    per_series, overall = aggregate_results(all_results, args.horizons)
    print_report(per_series, overall, args.horizons, args.output_json)


if __name__ == "__main__":
    main()
