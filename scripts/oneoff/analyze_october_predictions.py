"""
Analyze October prediction accuracy and model capability.

Examines:
1. Historical October patterns (actual Sep->Oct movements)
2. What each expert predicts for October transitions
3. Multi-horizon accuracy specifically for October bulletins
4. Whether the model can theoretically capture October patterns

Usage:
    bazel run //scripts/oneoff:analyze_october_predictions
"""

import logging
import os
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.business.vqs.aggregator import ExpertAggregator
from lib.business.vqs.data_cache import get_cutoff_at_date, get_cutoffs_for_series
from lib.business.vqs.expert_pool import (
    expert_fy_reset,
    expert_linear_extrap,
    expert_momentum_3m,
    expert_october_rule,
    expert_persistence,
    expert_seasonal_directional,
    expert_seasonal_median,
)
from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.metric_config import MetricConfig
from lib.business.vqs.seasonal_predictor import (
    get_median_october_retrogression,
    get_seasonal_prediction,
)
from lib.business.vqs.solver import predict_next_bulletin_and_maturity
from lib.utils.logging_utils import log_context
from models.enums.country import Country
from models.raw_facts import RawFactsLedger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
log_context("Analyzing October predictions and model capability")

PHYSICS_SERIES = [
    ("2nd", Country.INDIA.value, "India"),
    ("3rd", Country.INDIA.value, "India"),
    ("1st", Country.INDIA.value, "India"),
    ("2nd", Country.CHINA.value, "China"),
    ("3rd", Country.CHINA.value, "China"),
    ("1st", Country.CHINA.value, "China"),
]


def analyze_historical_october_patterns():
    """Show actual Sep->Oct movements across all years and series."""
    print("\n" + "=" * 80)
    print("PART 1: HISTORICAL OCTOBER PATTERNS (Actual Sep→Oct movements)")
    print("=" * 80)

    for visa_class, country, country_name in PHYSICS_SERIES:
        cutoffs = get_cutoffs_for_series(visa_class, country, "final_action")
        by_ym: dict[tuple[int, int], date] = {}
        for c in cutoffs:
            pub = c.bulletin.publication_date
            by_ym[(pub.year, pub.month)] = c.cutoff_date

        print(f"\n--- EB{visa_class} {country_name} ---")
        print(f"{'Year':>6} | {'Sep Cutoff':>12} | {'Oct Cutoff':>12} | {'Movement':>10} | {'Direction':>12}")
        print("-" * 70)

        oct_movements = []
        for y in sorted(set(yr for yr, _ in by_ym)):
            sep = by_ym.get((y, 9))
            oct = by_ym.get((y, 10))
            if sep and oct:
                move = (oct - sep).days
                oct_movements.append(move)
                direction = "RETRO" if move < 0 else ("ADVANCE" if move > 0 else "FLAT")
                print(f"{y:>6} | {sep.isoformat():>12} | {oct.isoformat():>12} | {move:>+8}d | {direction:>12}")

        if oct_movements:
            from statistics import mean, median, stdev

            print(f"\n  Summary: n={len(oct_movements)}, "
                  f"mean={mean(oct_movements):+.0f}d, median={median(oct_movements):+.0f}d, "
                  f"stdev={stdev(oct_movements) if len(oct_movements) > 1 else 0:.0f}d")
            retro_count = sum(1 for m in oct_movements if m < 0)
            print(f"  Retrogression rate: {retro_count}/{len(oct_movements)} "
                  f"({100 * retro_count / len(oct_movements):.0f}%)")


def analyze_expert_october_predictions():
    """For each September knowledge date, show what each expert predicts for October."""
    print("\n" + "=" * 80)
    print("PART 2: EXPERT PREDICTIONS FOR OCTOBER BULLETINS")
    print("=" * 80)

    experts = {
        "persistence": expert_persistence,
        "seasonal_median": expert_seasonal_median,
        "fy_reset": expert_fy_reset,
        "october_rule": expert_october_rule,
        "seasonal_dir": expert_seasonal_directional,
        "linear": expert_linear_extrap,
        "momentum_3m": expert_momentum_3m,
    }

    for visa_class, country, country_name in PHYSICS_SERIES:
        cutoffs = get_cutoffs_for_series(visa_class, country, "final_action")
        by_ym: dict[tuple[int, int], date] = {}
        for c in cutoffs:
            pub = c.bulletin.publication_date
            by_ym[(pub.year, pub.month)] = c.cutoff_date

        print(f"\n--- EB{visa_class} {country_name} ---")
        header = f"{'Year':>6} | {'Actual Oct':>12} | {'ActMove':>8}"
        for name in experts:
            header += f" | {name[:10]:>10}"
        print(header)
        print("-" * (len(header) + 5))

        for y in sorted(set(yr for yr, _ in by_ym)):
            sep = by_ym.get((y, 9))
            oct_actual = by_ym.get((y, 10))
            if not sep or not oct_actual:
                continue

            actual_move = (oct_actual - sep).days
            # Knowledge date is end of September (just before Oct bulletin)
            knowledge_date = date(y, 9, 28)

            line = f"{y:>6} | {oct_actual.isoformat():>12} | {actual_move:>+6}d"
            for name, expert_fn in experts.items():
                pred = expert_fn(visa_class, country, "final_action", knowledge_date)
                if pred:
                    err = (pred - oct_actual).days
                    line += f" | {err:>+8}d"
                else:
                    line += f" | {'N/A':>10}"
            print(line)


def analyze_model_october_predictions():
    """Run the full model for September knowledge dates → October predictions."""
    print("\n" + "=" * 80)
    print("PART 3: FULL MODEL PREDICTIONS FOR OCTOBER BULLETINS")
    print("=" * 80)

    meta = VqsMetaParams.defaults()

    for visa_class, country, country_name in PHYSICS_SERIES:
        cutoffs = get_cutoffs_for_series(visa_class, country, "final_action")
        by_ym: dict[tuple[int, int], date] = {}
        for c in cutoffs:
            pub = c.bulletin.publication_date
            by_ym[(pub.year, pub.month)] = c.cutoff_date

        print(f"\n--- EB{visa_class} {country_name} ---")
        print(f"{'Year':>6} | {'Actual Oct':>12} | {'ActMove':>8} | {'Predicted':>12} | {'Error':>8} | {'Confidence':>10}")
        print("-" * 80)

        errors = []
        for y in sorted(set(yr for yr, _ in by_ym)):
            sep = by_ym.get((y, 9))
            oct_actual = by_ym.get((y, 10))
            if not sep or not oct_actual:
                continue

            actual_move = (oct_actual - sep).days
            knowledge_date = date(y, 9, 28)

            facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))

            aggregator = ExpertAggregator(metric_config=MetricConfig.defaults())

            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=visa_class,
                country=country,
                action_type="final_action",
                facts=facts,
                meta=meta,
                aggregator=aggregator,
            )
            pred_cutoff = outcome.predicted_cutoff
            confidence = outcome.confidence

            if pred_cutoff:
                err = (pred_cutoff - oct_actual).days
                errors.append(abs(err))
                print(f"{y:>6} | {oct_actual.isoformat():>12} | {actual_move:>+6}d | {pred_cutoff.isoformat():>12} | {err:>+6}d | {confidence:>10}")
            else:
                print(f"{y:>6} | {oct_actual.isoformat():>12} | {actual_move:>+6}d | {'N/A':>12} | {'N/A':>8} | {'N/A':>10}")

        if errors:
            from statistics import mean, median

            print(f"\n  October MAE: {mean(errors):.0f}d (median: {median(errors):.0f}d, n={len(errors)})")


def analyze_seasonal_predictor_accuracy():
    """Check what the seasonal predictor thinks October movement should be, vs reality."""
    print("\n" + "=" * 80)
    print("PART 4: SEASONAL PREDICTOR INTERNAL STATE FOR OCTOBER")
    print("=" * 80)

    for visa_class, country, country_name in PHYSICS_SERIES:
        print(f"\n--- EB{visa_class} {country_name} ---")

        cutoffs = get_cutoffs_for_series(visa_class, country, "final_action")
        by_ym: dict[tuple[int, int], date] = {}
        for c in cutoffs:
            pub = c.bulletin.publication_date
            by_ym[(pub.year, pub.month)] = c.cutoff_date

        for y in sorted(set(yr for yr, _ in by_ym)):
            oct_actual = by_ym.get((y, 10))
            sep_actual = by_ym.get((y, 9))
            if not oct_actual or not sep_actual:
                continue

            knowledge_date = date(y, 9, 28)
            actual_move = (oct_actual - sep_actual).days

            seasonal_pred = get_seasonal_prediction(
                visa_class, country, "final_action", knowledge_date,
                target_month=10, min_samples=2,
            )
            retro_days = get_median_october_retrogression(
                visa_class, country, "final_action", knowledge_date,
            )

            seasonal_str = f"{seasonal_pred:+d}d" if seasonal_pred is not None else "N/A"
            print(f"  {y}: actual={actual_move:+d}d | seasonal_pred={seasonal_str} | "
                  f"median_retro={retro_days}d")


def analyze_multi_horizon_october():
    """Check h=3, h=6 predictions that TARGET October as the evaluation month."""
    print("\n" + "=" * 80)
    print("PART 5: MULTI-HORIZON PREDICTIONS TARGETING OCTOBER")
    print("(e.g., h=3 from July, h=6 from April, h=12 from October prior year)")
    print("=" * 80)

    meta = VqsMetaParams.defaults()

    for visa_class, country, country_name in PHYSICS_SERIES:
        cutoffs = get_cutoffs_for_series(visa_class, country, "final_action")
        by_ym: dict[tuple[int, int], date] = {}
        for c in cutoffs:
            pub = c.bulletin.publication_date
            by_ym[(pub.year, pub.month)] = c.cutoff_date

        print(f"\n--- EB{visa_class} {country_name} ---")

        for y in sorted(set(yr for yr, _ in by_ym)):
            oct_actual = by_ym.get((y, 10))
            if not oct_actual:
                continue

            print(f"\n  October {y} (actual: {oct_actual.isoformat()}):")

            for h, source_month in [(1, 9), (3, 7), (6, 4), (12, 10)]:
                source_year = y if source_month <= 9 else y - 1
                knowledge_date = date(source_year, source_month, 28)

                source_cutoff = get_cutoff_at_date(
                    visa_class, country, "final_action", knowledge_date
                )
                if not source_cutoff:
                    continue

                facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))
                aggregator = ExpertAggregator(metric_config=MetricConfig.defaults())

                outcome = predict_next_bulletin_and_maturity(
                    knowledge_date=knowledge_date,
                    visa_class=visa_class,
                    country=country,
                    action_type="final_action",
                    facts=facts,
                    meta=meta,
                    aggregator=aggregator,
                )
                results = outcome.results

                idx = h - 1
                if idx < len(results):
                    pred = results[idx].cutoff_date
                    if pred:
                        err = (pred - oct_actual).days
                        print(f"    h={h:>2} (from {knowledge_date.isoformat()}): "
                              f"pred={pred.isoformat()} err={err:+d}d")
                    else:
                        print(f"    h={h:>2} (from {knowledge_date.isoformat()}): pred=None")
                else:
                    print(f"    h={h:>2} (from {knowledge_date.isoformat()}): no result at idx {idx}")


def main():
    analyze_historical_october_patterns()
    analyze_expert_october_predictions()
    analyze_seasonal_predictor_accuracy()
    analyze_model_october_predictions()
    analyze_multi_horizon_october()

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
