"""
VQS Backtesting and Tuning Script.

Implements Two-Stage Tuning with Walk-Forward Validation:
1.  **Stage 1 (Physics)**: Tune lookback/supply to match trends.
2.  **Stage 2 (Control)**: Tune stickiness/caps/blend to dampen noise.

Usage:
    bazel run //scripts:vqs_backtest -- --stage=baseline
    bazel run //scripts:vqs_backtest -- --stage=1
    bazel run //scripts:vqs_backtest -- --stage=2
"""

import argparse
import logging
import math
import sys
from collections import defaultdict
from datetime import date
from itertools import product
from pathlib import Path
from statistics import mean, median
from typing import Any

import django
from django.conf import settings

# Setup Django before imports
if not settings.configured:
    logging.basicConfig(level=logging.INFO)
    sys.path.append(".")
    django.setup()


from lib.business.vqs.accuracy_metrics import (
    BulletinAccuracyRow,
    compute_bulletin_accuracy,
    compute_longterm_accuracy,
)
from lib.business.vqs.aggregator import ExpertAggregator
from lib.business.vqs.expert_pool import expert_linear_extrap, expert_persistence
from lib.business.vqs.meta_params import VqsMetaParams
from models.bulletin import Bulletin
from models.enums.country import Country

logger = logging.getLogger(__name__)

COUNTRY_NAMES = {
    Country.INDIA.value: "India",
    Country.CHINA.value: "China",
    Country.MEXICO.value: "Mexico",
    Country.PHILIPPINES.value: "Philippines",
}


def get_country_name(country: int) -> str:
    return COUNTRY_NAMES.get(country, f"ROW/{country}")


# Retrogressed series: where the model should add value over persistence
RETROGRESSED_SERIES = {
    ("2nd", Country.INDIA.value),
    ("3rd", Country.INDIA.value),
    ("2nd", Country.CHINA.value),
    ("3rd", Country.CHINA.value),
}


def is_retrogressed_series(visa_class: str, country: int) -> bool:
    """Return True if this is a heavily retrogressed series."""
    return (visa_class, country) in RETROGRESSED_SERIES


def compute_weighted_mae(
    rows: list[BulletinAccuracyRow], weight_large_moves: float = 2.0
) -> float:
    """
    Compute weighted MAE where errors on large actual movements are weighted more heavily.

    Args:
        rows: Accuracy rows with error_days.
        weight_large_moves: Multiplier for errors when actual movement > 30 days.

    Returns:
        Weighted mean absolute error.
    """
    if not rows:
        return 0.0

    weighted_errors = []
    for r in rows:
        if r.error_days is None:
            continue

        # Compute actual movement (difference between consecutive bulletins)
        # For simplicity, we'll use a heuristic: if error is large, likely actual moved
        # A more accurate implementation would track actual movements from data
        # For now, weight errors > 30 days more heavily
        weight = weight_large_moves if r.error_days > 30 else 1.0
        weighted_errors.append(r.error_days * weight)

    if not weighted_errors:
        return 0.0

    return sum(weighted_errors) / len(weighted_errors)


# Global cache for facts to speed up backtests
FACTS = []


def load_facts():
    """Load all facts into memory once."""
    global FACTS
    if FACTS:
        return
    from models.raw_facts import RawFactsLedger

    logger.info("Preloading facts from DB...")
    FACTS = list(RawFactsLedger.objects.order_by("publication_date"))
    logger.info(f"Loaded {len(FACTS)} facts.")


def evaluate_params_detailed(
    params: VqsMetaParams,
    bulletins: list[date],
    use_weighted: bool = False,
    horizon: int = 1,
) -> dict[str, float]:
    """Run accuracy metrics and return detailed breakdown by series type."""
    if not bulletins:
        return {"overall_mae": 0.0, "retrogressed_mae": 0.0, "other_mae": 0.0}

    # Use global facts if available
    rows = compute_bulletin_accuracy(
        bulletins=bulletins,
        meta=params,
        facts=FACTS if FACTS else None,
        horizon=horizon,
    )

    # Split by series type
    retrogressed_rows = [
        r for r in rows if is_retrogressed_series(r.visa_class, r.country)
    ]
    other_rows = [
        r for r in rows if not is_retrogressed_series(r.visa_class, r.country)
    ]

    if use_weighted:
        overall_mae = compute_weighted_mae(rows)
        retrogressed_mae = compute_weighted_mae(retrogressed_rows)
        other_mae = compute_weighted_mae(other_rows)
    else:
        errors = [r.error_days for r in rows if r.error_days is not None]
        overall_mae = mean(errors) if errors else 0.0

        retro_errors = [
            r.error_days for r in retrogressed_rows if r.error_days is not None
        ]
        retrogressed_mae = mean(retro_errors) if retro_errors else 0.0

        other_errors = [r.error_days for r in other_rows if r.error_days is not None]
        other_mae = mean(other_errors) if other_errors else 0.0

    return {
        "overall_mae": overall_mae,
        "retrogressed_mae": retrogressed_mae,
        "other_mae": other_mae,
    }


def get_bulletins_in_range(start_year: int, end_year: int) -> list[date]:
    """Return list of bulletin publication dates in [start_year, end_year)."""
    return list(
        Bulletin.objects.filter(
            publication_date__year__gte=start_year, publication_date__year__lt=end_year
        )
        .order_by("publication_date")
        .values_list("publication_date", flat=True)
    )


def evaluate_params(
    params: VqsMetaParams,
    bulletins: list[date],
    action_type: str = "final_action",
    horizon: int = 1,
) -> float:
    """Run accuracy metrics for a given param set and return MAE (days)."""
    if not bulletins:
        return 0.0

    # Use global facts if available
    rows = compute_bulletin_accuracy(
        bulletins=bulletins,
        meta=params,
        facts=FACTS if FACTS else None,
        action_type=action_type,
        horizon=horizon,
    )

    errors = [r.error_days for r in rows if r.error_days is not None]
    if not errors:
        return 0.0

    return mean(errors)


import multiprocessing
from concurrent.futures import ProcessPoolExecutor

# Global state for worker caching
_LAST_PHYSICS_PARAMS = None


# Worker function must be top-level for pickling
def worker_evaluate_config(args):
    """
    Worker function to evaluate a single config.
    args: (config_dict, bulletins, base_params_dict)
    """
    global _LAST_PHYSICS_PARAMS
    cfg, bulletins, base_params_dict, action_type, horizon = args

    # Ensure Django is setup (for spawn processes)

    # Reconstruct base_params
    current_dict = base_params_dict.copy()
    current_dict.update(cfg)
    candidate = VqsMetaParams.from_dict(current_dict)

    # Monkey Patch in worker process
    original_defaults = VqsMetaParams.defaults
    VqsMetaParams.defaults = lambda: candidate

    # Check if physics params changed
    physics_keys = [
        "supply_scale_multiplier",
        "lookback_months_default",
        "lookback_months_eb1_india",
    ]
    current_physics = {k: getattr(candidate, k) for k in physics_keys}

    from lib.business.vqs.expert_pool import _cached_physics_prediction

    if current_physics != _LAST_PHYSICS_PARAMS:
        # Physics params changed (or first run) -> Clear cache
        _cached_physics_prediction.cache_clear()
        _LAST_PHYSICS_PARAMS = current_physics

    # Load facts (this hits DB in each worker, but it's < 1s)
    load_facts()

    try:
        # Silence verbose logs in workers
        logging.getLogger("lib.business.vqs.accuracy_metrics").setLevel(logging.WARNING)
        # We need a way to pass action_type to worker, but for tuning it's usually final_action
        # If we need tuning for filing, we should pass it in args
        mae = evaluate_params(
            candidate, bulletins, action_type=action_type, horizon=horizon
        )
        return mae
    except Exception as e:
        # Return error info as string to avoid pickling issues with exceptions
        return f"ERROR: {str(e)}"
    finally:
        VqsMetaParams.defaults = original_defaults


def tune_on_range(
    param_grid: list[dict[str, Any]],
    base_params: VqsMetaParams,
    start_year: int,
    end_year: int,
    horizon: int = 1,
) -> tuple[float, dict[str, Any]]:
    """
    Run grid search on bulletins in [start_year, end_year).
    Returns (best_mae, best_config).
    """
    bulletins = get_bulletins_in_range(start_year, end_year)
    if not bulletins:
        logger.warning(f"No bulletins found for range {start_year}-{end_year}")
        return float("inf"), {}

    logger.info(f"Tuning on {start_year}-{end_year} ({len(bulletins)} bulletins)")

    best_mae = float("inf")
    best_cfg = {}

    total_configs = len(param_grid)
    workers = max(1, multiprocessing.cpu_count() - 1)
    logger.info(f"Parallel execution with {workers} workers")

    base_params_dict = base_params.to_dict()

    # Prepare args
    tasks = [
        (cfg, bulletins, base_params_dict, "final_action", horizon)
        for cfg in param_grid
    ]

    with ProcessPoolExecutor(max_workers=workers) as executor:
        # Submit all tasks
        futures = {executor.submit(worker_evaluate_config, t): t[0] for t in tasks}

        # Process results as they complete
        completed_count = 0
        from concurrent.futures import as_completed

        for future in as_completed(futures):
            cfg = futures[future]
            completed_count += 1

            try:
                result = future.result()
                if isinstance(result, str) and result.startswith("ERROR:"):
                    logger.error(f"Config failed: {cfg} -> {result}")
                    continue

                mae = result

                if mae < best_mae:
                    best_mae = mae
                    best_cfg = cfg
                    logger.info(f"New Best: {best_mae:.2f} (Config: {best_cfg})")

            except Exception as e:
                logger.error(f"Worker failed for {cfg}: {e}")

            if completed_count % 5 == 0 or completed_count == total_configs:
                logger.info(f"Progress: {completed_count}/{total_configs} done")

    return best_mae, best_cfg


def walk_forward_validation(
    param_grid: list[dict],
    base_params: VqsMetaParams,
    years: list[int] | None = None,
    horizon: int = 1,
) -> dict[str, Any]:
    """
    Simulate yearly tuning and testing.
    For each year Y in `years`:
        Train on [Y-3 .. Y]: Find best params from grid.
        Test on [Y]: Evaluate best params on Y (out of sample).

    Returns the aggregated Test MAE across all years using the rolling optimal params.
    """
    if years is None:
        years = [2021, 2022, 2023, 2024, 2025, 2026]

    total_test_errors = []

    logger.info(f"Starting Walk-Forward Validation on {years}")

    for test_year in years:
        train_start = test_year - 3
        train_end = test_year

        # Grid Search on Train
        best_mae, best_cfg = tune_on_range(
            param_grid, base_params, train_start, train_end, horizon=horizon
        )

        if best_mae == float("inf"):
            continue

        logger.info(f"=== Year {test_year} ===")
        logger.info(f"Best Train MAE: {best_mae:.2f} days | Config: {best_cfg}")

        # Evaluated on Test (Out of Sample)
        test_dates = get_bulletins_in_range(test_year, test_year + 1)
        if not test_dates:
            logger.warning(f"Skipping test year {test_year}: insufficient data")
            continue
        test_dict = base_params.to_dict()
        test_dict.update(best_cfg)
        test_params = VqsMetaParams.from_dict(test_dict)

        # We need raw errors to aggregate properly
        test_rows = compute_bulletin_accuracy(
            bulletins=test_dates, meta=test_params, horizon=horizon
        )

        test_errors = [r.error_days for r in test_rows if r.error_days is not None]
        test_mae = mean(test_errors) if test_errors else 0.0

        # Exclude EB4
        no_eb4_errors = [
            r.error_days
            for r in test_rows
            if r.error_days is not None and r.visa_class != "4th"
        ]
        mae_no_eb4 = mean(no_eb4_errors) if no_eb4_errors else 0.0

        logger.info(f"Test MAE: {test_mae:.2f} days | Excl. EB4: {mae_no_eb4:.2f} days")

        total_test_errors.extend(test_errors)

    final_mae = mean(total_test_errors) if total_test_errors else 0.0
    return {"mae": final_mae, "n_samples": len(total_test_errors)}


def run_stage_1(base_params: VqsMetaParams):
    """
    Stage 1: Physics Tuning.
    Grid: supply_scale, lookback_months.
    """
    logger.info("Starting Stage 1: Physics Tuning")

    grid = {
        "supply_scale_multiplier": [0.8, 1.0, 1.2],
        "lookback_months_default": [24, 36],
        "lookback_months_eb1_india": [24, 36],
    }

    keys, values = zip(*grid.items())
    param_grid = [dict(zip(keys, v)) for v in product(*values)]

    result = walk_forward_validation(param_grid, base_params)
    logger.info(f"Stage 1 Final Result: MAE = {result['mae']:.2f} days")


def run_stage_2(base_params: VqsMetaParams):
    """
    Stage 2: Control Tuning.
    Grid: stickiness, blend, caps.
    Assumes base_params already has optimal Stage 1 values (manually set for now).
    """
    logger.info("Starting Stage 2: Control Tuning")

    grid = {
        "stickiness_days": [60, 90],
        "stickiness_stall_days": [90, 120, 150],
        "cap_forward_days": [30, 45, 60],
        "blend_lambda": [0.5, 0.7, 1.0],
    }

    keys, values = zip(*grid.items())
    param_grid = [dict(zip(keys, v)) for v in product(*values)]

    result = walk_forward_validation(param_grid, base_params)
    logger.info(f"Stage 2 Final Result: MAE = {result['mae']:.2f} days")


def run_stage_ensemble_weight(base_params: VqsMetaParams, horizon: int = 1):
    """
    Stage 3: Ensemble Persistence Weight Tuning.
    Grid: ensemble_persistence_weight.
    """
    logger.info(
        f"Starting Stage 3: Ensemble Persistence Weight Tuning (Horizon {horizon})"
    )

    grid = {
        "ensemble_persistence_weight": [
            0.1,
            0.2,
            0.3,
            0.4,
            0.5,
            0.6,
            0.7,
            0.8,
            0.85,
            0.9,
        ],
    }

    keys, values = zip(*grid.items())
    param_grid = [dict(zip(keys, v)) for v in product(*values)]

    result = walk_forward_validation(param_grid, base_params, horizon=horizon)
    logger.info(f"Stage 3 Final Result: MAE = {result['mae']:.2f} days")


def run_find_best_physics(base_params: VqsMetaParams):
    """
    Run grid search on strictly the latest training window (e.g. 2022-2024).
    This gives the best params to use for *future* predictions (2025+).
    """
    logger.info("Finding Best Physics Params for 2022-2024")

    grid = {
        "supply_scale_multiplier": [0.8, 0.9, 1.0, 1.1, 1.2],
        "lookback_months_default": [12, 24, 36],
        "lookback_months_eb1_india": [24, 36, 48],
    }

    # Generate all combinations
    keys, values = zip(*grid.items())
    param_grid = [dict(zip(keys, v)) for v in product(*values)]

    best_mae, best_cfg = tune_on_range(param_grid, base_params, 2022, 2025)
    logger.info(f"Final Best Physics Params (MAE {best_mae:.2f}): {best_cfg}")


def run_expert_diagnostics(base_params: VqsMetaParams):
    """
    Run backtest with diagnostics enabled to inspect expert weights.
    """
    logger.info("Running Expert Diagnostics...")

    # 1. Run backtest with a tracked aggregator
    aggregator = ExpertAggregator()
    # We use the latest 3 years for diagnostics
    bulletins = get_bulletins_in_range(2022, 2025)

    # Load facts if not loaded
    load_facts()

    compute_bulletin_accuracy(
        bulletins=bulletins, meta=base_params, aggregator=aggregator, facts=FACTS
    )

    # 2. Analyze Weights
    logger.info("\n=== Expert Diagnostics (Average Weights) ===")

    # Structure: series -> expert -> list of weights
    weight_samples = {}

    for (series_key, _), data in aggregator.history.items():
        if series_key not in weight_samples:
            weight_samples[series_key] = {}

        weights = data["weights"]
        for expert, w in weights.items():
            if expert not in weight_samples[series_key]:
                weight_samples[series_key][expert] = []
            weight_samples[series_key][expert].append(w)

    # Print average weights per series
    for series_key, experts in weight_samples.items():
        visa, country_val = series_key
        country_name = Country(country_val).name if country_val else "Unknown"
        logger.info(f"\nSeries: {visa} / {country_name}")

        # Sort by avg weight desc
        avg_weights = []
        for exp, samples in experts.items():
            avg = sum(samples) / len(samples)
            avg_weights.append((exp, avg))

        avg_weights.sort(key=lambda x: x[1], reverse=True)

        for exp, avg in avg_weights:
            logger.info(f"  {exp:<25}: {avg:.4f}")


def run_find_best_control(base_params: VqsMetaParams, horizon: int = 1):
    """
    Run grid search for Control params on 2022-2024, using the BEST Physics params found.
    """
    # Apply best physics params found in previous step
    physics_params = {
        "supply_scale_multiplier": 0.8,
        "lookback_months_default": 36,
        "lookback_months_eb1_india": 24,
    }
    current_dict = base_params.to_dict()
    current_dict.update(physics_params)
    base_params = VqsMetaParams.from_dict(current_dict)

    logger.info(
        f"Finding Best Control Params for 2022-2024 (using Physics: {base_params})"
    )

    grid = {
        "stickiness_days": [60, 90],
        "stickiness_stall_days": [90, 120, 150],
        "cap_forward_days": [30, 45, 60],
        "blend_lambda": [0.5, 0.7, 1.0],
    }

    keys, values = zip(*grid.items())
    param_grid = [dict(zip(keys, v)) for v in product(*values)]

    best_mae, best_cfg = tune_on_range(
        param_grid, base_params, 2022, 2025, horizon=horizon
    )
    logger.info(f"Final Best Control Params (MAE {best_mae:.2f}): {best_cfg}")

    # mae not defined here, just skip baseline log or calculate it


def run_comparative_audit(
    base_params: VqsMetaParams, years: list[int], action_type: str = "final_action"
):
    """
    Run a multi-year audit comparing Ensemble vs trivial baselines.
    """
    from lib.business.vqs.aggregator import ExpertAggregator

    logger.info(f"\n==== VQS Comparative Audit ({min(years)}-{max(years)}) ====")
    logger.info(f"Action Type: {action_type}")

    # 1. Prepare expert-locked aggregators (using learning_rate=0 to freeze weights)
    ensemble_agg = ExpertAggregator()  # Uses all weighted experts (dynamic)

    from lib.business.vqs.expert_pool import ALL_EXPERTS

    # Persistence Aggregator (locked to 100% persistence)
    persistence_agg = ExpertAggregator(learning_rate=0.0)

    # Extrap Aggregator (locked to 100% linear_extrap)
    extrap_agg = ExpertAggregator(learning_rate=0.0)

    # Pre-initialize weights for baselines to avoid dynamic learning
    visa_classes = ["1st", "2nd", "3rd", "4th", "5th", "other"]
    countries = [c.value for c in Country]

    for v_class, c_val in product(visa_classes, countries):
        key = (v_class, c_val)
        persistence_agg.weights[key] = {
            name: (1.0 if name == "persistence" else 0.0) for name in ALL_EXPERTS
        }
        extrap_agg.weights[key] = {
            name: (1.0 if name == "linear_extrap" else 0.0) for name in ALL_EXPERTS
        }

    results = []  # list of (year, ensemble_mae, persistence_mae, extrap_mae)

    for year in sorted(years):
        bulletins = get_bulletins_in_range(year, year + 1)
        if not bulletins:
            continue

        # Ensemble
        ens_rows = compute_bulletin_accuracy(
            bulletins=bulletins,
            meta=base_params,
            aggregator=ensemble_agg,
            facts=FACTS,
            action_type=action_type,
        )
        ens_errs = [
            r.error_days
            for r in ens_rows
            if r.error_days is not None and r.visa_class != "4th"
        ]
        ens_mae = mean(ens_errs) if ens_errs else 0.0

        # Persistence
        per_rows = compute_bulletin_accuracy(
            bulletins=bulletins,
            meta=base_params,
            aggregator=persistence_agg,
            facts=FACTS,
            action_type=action_type,
        )
        per_errs = [
            r.error_days
            for r in per_rows
            if r.error_days is not None and r.visa_class != "4th"
        ]
        per_mae = mean(per_errs) if per_errs else 0.0

        # Extrapolation
        ext_rows = compute_bulletin_accuracy(
            bulletins=bulletins,
            meta=base_params,
            aggregator=extrap_agg,
            facts=FACTS,
            action_type=action_type,
        )
        ext_errs = [
            r.error_days
            for r in ext_rows
            if r.error_days is not None and r.visa_class != "4th"
        ]
        ext_mae = mean(ext_errs) if ext_errs else 0.0

        results.append(
            {
                "year": year,
                "ensemble": ens_mae,
                "persistence": per_mae,
                "extrap": ext_mae,
                "count": len(ens_errs),
            }
        )
        logger.info(f"Year {year} processed ({len(ens_errs)} samples)")

    # Final Report
    logger.info("\n" + "=" * 80)
    logger.info(
        f"{'Year':<6} | {'Ensemble':<12} | {'Persistence':<12} | {'Extrap':<12} | {'Alpha vs Best Baseline'}"
    )
    logger.info("-" * 80)

    total_ens = []
    total_per = []
    total_ext = []

    for r in results:
        best_base = min(r["persistence"], r["extrap"])
        alpha = best_base - r["ensemble"]
        logger.info(
            f"{r['year']:<6} | {r['ensemble']:>8.2f} days | {r['persistence']:>8.2f} days | {r['extrap']:>8.2f} days | {alpha:>+8.2f} days"
        )
        total_ens.append(r["ensemble"])
        total_per.append(r["persistence"])
        total_ext.append(r["extrap"])

    logger.info("-" * 80)
    avg_ens = mean(total_ens) if total_ens else 0
    avg_per = mean(total_per) if total_per else 0
    avg_ext = mean(total_ext) if total_ext else 0
    logger.info(
        f"{'AVG':<6} | {avg_ens:>8.2f} days | {avg_per:>8.2f} days | {avg_ext:>8.2f} days | {min(avg_per, avg_ext) - avg_ens:>+8.2f} days"
    )
    logger.info("=" * 80)
    logger.info(
        "* Note: Metrics exclude EB4 noise and are averaged per-year across all horizons."
    )


def run_detailed_error_analysis(
    base_params: VqsMetaParams, years: list[int], action_type: str = "final_action"
):
    """Run full error analysis decomposing errors by series, year, direction, and regime."""
    from lib.business.vqs.aggregator import ExpertAggregator

    start_year = min(years)
    end_year = max(years)
    bulletins = get_bulletins_in_range(start_year, end_year + 1)

    print(f"\\n{'=' * 80}")
    print(
        f"VQS DETAILED ERROR ANALYSIS: {len(bulletins)} bulletins ({start_year}-{end_year})"
    )
    print(f"Action Type: {action_type}")
    print(f"{'=' * 80}\\n")

    if not bulletins:
        print("No bulletins found for this period.")
        return

    # Instantiate Online Aggregator
    aggregator = ExpertAggregator()

    # Pass aggregator to compute_metrics. Weights will be updated online.
    rows = compute_bulletin_accuracy(
        bulletins=bulletins,
        meta=base_params,
        aggregator=aggregator,
        facts=FACTS,
        action_type=action_type,
    )

    # ---- Enrich rows with persistence error and actual movement ----
    enriched = []
    for r in rows:
        if r.error_days is None:
            continue

        # 1. Persistence Baseline
        persist_pred = expert_persistence(
            r.visa_class, r.country, r.action_type, r.bulletin_date
        )
        persist_error = (
            abs((persist_pred - r.actual_cutoff).days) if persist_pred else None
        )

        # 2. Linear Extrapolation Baseline
        linear_pred = expert_linear_extrap(
            r.visa_class, r.country, r.action_type, r.bulletin_date
        )
        linear_error = (
            abs((linear_pred - r.actual_cutoff).days) if linear_pred else None
        )

        actual_movement = None
        if persist_pred:
            actual_movement = (r.actual_cutoff - persist_pred).days

        pred_movement = None
        if r.predicted_cutoff and persist_pred:
            pred_movement = (r.predicted_cutoff - persist_pred).days

        enriched.append(
            {
                "row": r,
                "persist_error": persist_error,
                "linear_error": linear_error,
                "actual_movement": actual_movement,
                "pred_movement": pred_movement,
                "beat_persistence": (r.error_days < persist_error)
                if persist_error is not None
                else None,
                "series": f"{r.visa_class}/{get_country_name(r.country)}",
                "year": r.bulletin_date.year,
                "is_retrogressed": (r.visa_class, r.country) in RETROGRESSED_SERIES,
            }
        )

    valid_comparison = [
        e
        for e in enriched
        if e["persist_error"] is not None and e["row"].error_days is not None
    ]

    if not valid_comparison:
        print("NO VALID ROWS FOR COMPARISON")
        return

    # ---- 0. EB4 IMPACT ANALYSIS ----
    print("0. EB4 IMPACT ANALYSIS")

    eb4_rows = [e for e in valid_comparison if e["row"].visa_class == "4th"]
    non_eb4_rows = [e for e in valid_comparison if e["row"].visa_class != "4th"]

    all_mae = mean([e["row"].error_days for e in valid_comparison])
    eb4_mae = mean([e["row"].error_days for e in eb4_rows]) if eb4_rows else 0.0
    non_eb4_mae = (
        mean([e["row"].error_days for e in non_eb4_rows]) if non_eb4_rows else 0.0
    )

    print(f"   Overall MAE:      {all_mae:.2f} days (n={len(valid_comparison)})")
    print(f"   EB4 Only MAE:     {eb4_mae:.2f} days (n={len(eb4_rows)})")
    print(f"   Excluding EB4:    {non_eb4_mae:.2f} days (n={len(non_eb4_rows)})")
    print(f"   Impact of EB4:    {all_mae - non_eb4_mae:+.2f} days")
    print()

    # ---- 0.1 IMPACT BY YEAR ----
    print("0.1. EB4 IMPACT BY YEAR")
    years_list = sorted(list(set(e["year"] for e in valid_comparison)))
    for yr in years_list:
        yr_rows = [e for e in valid_comparison if e["year"] == yr]
        yr_eb4 = [e for e in yr_rows if e["row"].visa_class == "4th"]
        yr_non_eb4 = [e for e in yr_rows if e["row"].visa_class != "4th"]

        y_all = mean([e["row"].error_days for e in yr_rows])
        y_no4 = mean([e["row"].error_days for e in yr_non_eb4]) if yr_non_eb4 else 0
        y_4 = mean([e["row"].error_days for e in yr_eb4]) if yr_eb4 else 0

        impact = y_all - y_no4
        print(
            f"   {yr}: Overall={y_all:5.1f} | Excl.EB4={y_no4:5.1f} | EB4={y_4:6.1f} | Impact={impact:+5.1f}"
        )
    print()

    def compute_metrics(errors: list[float]) -> dict[str, float]:
        """Compute MAE, RMSE, MedianAE."""
        if not errors:
            return {"MAE": 0.0, "RMSE": 0.0, "MedAE": 0.0}

        abs_errors = [abs(e) for e in errors]
        squared_errors = [e**2 for e in errors]

        return {
            "MAE": mean(abs_errors),
            "RMSE": math.sqrt(mean(squared_errors)),
            "MedAE": median(abs_errors),
        }

    # ---- 1. OVERALL SUMMARY ----
    linear_comparison = [e for e in enriched if e["linear_error"] is not None]
    excluded_count = len(enriched) - len(valid_comparison)

    all_vqs = [e["row"].error_days for e in valid_comparison]
    all_persist = [e["persist_error"] for e in valid_comparison]
    all_linear = [e["linear_error"] for e in linear_comparison]

    vqs_metrics = compute_metrics(all_vqs)
    persist_metrics = compute_metrics(all_persist)
    linear_metrics = compute_metrics(all_linear)

    print("1. OVERALL SUMMARY")
    print(
        f"   Evaluated:       {len(valid_comparison)} rows (Excluded {excluded_count} due to missing history)"
    )

    print(
        f"   VQS:         MAE={vqs_metrics['MAE']:.2f} | RMSE={vqs_metrics['RMSE']:.2f} | MedAE={vqs_metrics['MedAE']:.2f}"
    )
    print(
        f"   Persistence: MAE={persist_metrics['MAE']:.2f} | RMSE={persist_metrics['RMSE']:.2f} | MedAE={persist_metrics['MedAE']:.2f}"
    )
    if linear_metrics["MAE"] > 0:
        print(
            f"   Lin. Extrap: MAE={linear_metrics['MAE']:.2f} | RMSE={linear_metrics['RMSE']:.2f} | MedAE={linear_metrics['MedAE']:.2f}"
        )

    print(
        f"   Improvement (MAE): {persist_metrics['MAE'] - vqs_metrics['MAE']:.2f} days"
    )

    beats = [e for e in valid_comparison if e["beat_persistence"] is True]
    losses = [e for e in valid_comparison if e["beat_persistence"] is False]
    ties = [e for e in valid_comparison if e["row"].error_days == e["persist_error"]]

    print(
        f"   Beat Rate:       {len(beats)}/{len(valid_comparison)} = {100 * len(beats) / len(valid_comparison):.1f}%"
    )
    print(
        f"   Loss Rate:       {len(losses)}/{len(valid_comparison)} = {100 * len(losses) / len(valid_comparison):.1f}%"
    )
    print(
        f"   Tie Rate:        {len(ties)}/{len(valid_comparison)} = {100 * len(ties) / len(valid_comparison):.1f}%"
    )
    print()

    # ---- 2. MAE BY VISA CLASS ----
    print("2. MAE BY VISA CLASS")
    by_class = defaultdict(list)
    for e in valid_comparison:
        by_class[e["row"].visa_class].append(e["row"].error_days)

    for vc in sorted(by_class.keys()):
        mae = mean(by_class[vc])
        n = len(by_class[vc])
        print(f"   {vc:5s}: MAE={mae:6.1f} (n={n})")
    print()

    # ---- 3. BY SERIES ----
    print("3. MAE BY SERIES (top 15 by sample count, Fair Comparison)")
    by_series = defaultdict(lambda: {"vqs": [], "persist": [], "beats": 0, "n": 0})
    for e in valid_comparison:
        s = e["series"]
        by_series[s]["vqs"].append(e["row"].error_days)
        by_series[s]["persist"].append(e["persist_error"])
        if e["beat_persistence"]:
            by_series[s]["beats"] += 1
        by_series[s]["n"] += 1

    sorted_series = sorted(by_series.items(), key=lambda x: -x[1]["n"])[:15]
    for s, data in sorted_series:
        vqs = mean(data["vqs"])
        p = mean(data["persist"]) if data["persist"] else 0
        delta = p - vqs
        beat_pct = 100 * data["beats"] / data["n"] if data["n"] else 0
        marker = "✅" if delta > 0 else "❌"
        print(
            f"   {s:20s}: VQS={vqs:6.1f} | Persist={p:6.1f} | Δ={delta:+6.1f} {marker} | BeatRate={beat_pct:4.1f}% (n={data['n']})"
        )
    print()

    # ---- 4. WORST PREDICTIONS (top 20 by VQS error) ----
    print("4. WORST PREDICTIONS (top 20 by VQS error, Fair Comparison)")
    worst = sorted(valid_comparison, key=lambda e: -e["row"].error_days)[:20]
    for e in worst:
        r = e["row"]
        persist_err = e["persist_error"] or 0
        actual_move = e["actual_movement"] or 0
        pred_move = e["pred_movement"] or 0
        print(
            f"   {r.bulletin_date} {e['series']:20s} | "
            f"Error={r.error_days:4d}d | PersistErr={persist_err:4d}d | "
            f"ActualMove={actual_move:+5d}d | PredMove={pred_move:+5d}d"
        )
    print()

    # ---- 8. MONTH-OF-YEAR ANALYSIS ----
    print("8. MONTH-OF-YEAR ANALYSIS")
    by_month = defaultdict(list)
    for e in valid_comparison:
        m = e["row"].bulletin_date.month
        by_month[m].append(e["row"].error_days)

    for m in sorted(by_month.keys()):
        mae = mean(by_month[m])
        n = len(by_month[m])
        bar = "█" * int(mae / 5)
        print(f"   Month {m:2d}: MAE={mae:6.1f} (n={n:3d}) {bar}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=[
            "baseline",
            "1",
            "2",
            "3",
            "ensemble",
            "diagnostics",
            "analysis",
            "find_best_physics",
            "find_best_control",
            "persistence",
            "longterm",
            "coverage",
            "audit",
        ],
        required=True,
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Specific years to validate (e.g. 2023 2024)",
        default=[2021, 2022, 2023, 2024, 2025, 2026],
    )
    parser.add_argument(
        "--action-type",
        choices=["final_action", "filing"],
        default="final_action",
        help="Which cutoff type to evaluate",
    )
    parser.add_argument(
        "--horizon", type=int, default=1, help="Evaluation horizon (months)"
    )
    args = parser.parse_args()

    base_params = VqsMetaParams.defaults()
    horizon = args.horizon

    # Preload facts
    load_facts()

    if args.stage == "baseline":
        logger.info(f"Running Baseline (Default Params) on {args.years}")

        # Get all test bulletins
        all_bulletins = []
        for year in args.years:
            all_bulletins.extend(get_bulletins_in_range(year, year + 1))

        # Compute overall accuracy
        rows = compute_bulletin_accuracy(
            bulletins=all_bulletins,
            meta=base_params,
            facts=FACTS if FACTS else None,
            action_type=args.action_type,
            horizon=horizon,
        )
        errors = [r.error_days for r in rows if r.error_days is not None]
        no_eb1_india_errors = [
            r.error_days
            for r in rows
            if r.error_days is not None
            and not (r.visa_class == "1st" and r.country == "3")
        ]
        overall_mae = mean(errors) if errors else 0.0
        mae_no_eb1_india = mean(no_eb1_india_errors) if no_eb1_india_errors else 0.0

        # Compute excluding EB4
        no_eb4_errors = [
            r.error_days
            for r in rows
            if r.error_days is not None and r.visa_class != "4th"
        ]
        mae_no_eb4 = mean(no_eb4_errors) if no_eb4_errors else 0.0

        logger.info("\nBaseline Results:")
        logger.info(f"  Overall MAE:      {overall_mae:.2f} days (n={len(errors)})")
        logger.info(
            f"  Excl. EB-1 India: {mae_no_eb1_india:.2f} days (n={len(no_eb1_india_errors)})"
        )
        logger.info(
            f"  Excluding EB4:    {mae_no_eb4:.2f} days (n={len(no_eb4_errors)})"
        )
        logger.info(f"  Impact of EB4:    {overall_mae - mae_no_eb4:+.2f} days")

        if horizon > 1:
            logger.info("\nTop 10 Worst Offenders:")
            valid_rows = [r for r in rows if r.error_days is not None]
            valid_rows.sort(key=lambda x: x.error_days, reverse=True)
            for r in valid_rows[:10]:
                logger.info(
                    f"  {r.visa_class}/{r.country} {r.bulletin_date}: Pred={r.predicted_cutoff}, Actual={r.actual_cutoff}, Error={r.error_days} days"
                )

    elif args.stage == "coverage":
        logger.info(
            f"Running Coverage Evaluation (Confidence Intervals) on {args.years}"
        )

        # Get all test bulletins
        all_bulletins = []
        for year in args.years:
            all_bulletins.extend(get_bulletins_in_range(year, year + 1))

        # Compute accuracy with confidence intervals
        rows = compute_bulletin_accuracy(
            bulletins=all_bulletins,
            meta=base_params,
            facts=FACTS if FACTS else None,
            action_type=args.action_type,
            horizon=horizon,
        )

        # Filter rows where we have both a prediction and confidence intervals
        eligible_rows = [
            r
            for r in rows
            if r.predicted_cutoff and r.confidence_low and r.confidence_high
        ]

        covered_count = 0
        total_eligible = len(eligible_rows)

        for r in eligible_rows:
            if r.confidence_low <= r.actual_cutoff <= r.confidence_high:
                covered_count += 1

        coverage_rate = (
            (covered_count / total_eligible * 100) if total_eligible > 0 else 0
        )

        logger.info("\nCoverage Results:")
        logger.info(f"  Total Eligible: {total_eligible}")
        logger.info(f"  Covered:        {covered_count}")
        logger.info(f"  Coverage Rate:  {coverage_rate:.1f}%")

        if total_eligible > 10:
            logger.info("\nSample Intervals:")
            for r in eligible_rows[:10]:
                status = (
                    "✅"
                    if r.confidence_low <= r.actual_cutoff <= r.confidence_high
                    else "❌"
                )
                logger.info(
                    f"  {r.visa_class}/{r.country} {r.bulletin_date}: Actual={r.actual_cutoff} CI=[{r.confidence_low}, {r.confidence_high}] {status}"
                )

    elif args.stage == "1":
        run_stage_1(
            base_params
        )  # Note: stages still need updating or just pass horizon inside

    elif args.stage == "2":
        logger.info("Running Stage 2 (on top of defaults)")
        run_stage_2(base_params)

    elif args.stage in ["3", "ensemble"]:
        run_stage_ensemble_weight(base_params, horizon=horizon)

    elif args.stage == "diagnostics":
        run_expert_diagnostics(base_params)

    elif args.stage == "find_best_physics":
        run_find_best_physics(base_params)
    elif args.stage == "longterm":
        logger.info(f"Running Long-Term Maturity Validation on {args.years}...")
        # Evaluate how well we predicted "When will I be current?"

        test_months = []
        for year in sorted(args.years):
            curr = date(year, 1, 1)
            end_of_year = date(year, 12, 31)
            while curr <= end_of_year:
                test_months.append(curr)
                curr = date(curr.year + (curr.month // 12), ((curr.month % 12) + 1), 1)

        logger.info(f"Evaluating {len(test_months)} months")

        # Load facts
        load_facts()

        results = compute_longterm_accuracy(
            months=test_months,
            visa_category="employment_based",
            action_type=args.action_type,
            checkpoint_dir=Path("."),
            force_recompute=True,
        )

        # Analyze results
        # error_days is populated in LongtermAccuracyRow
        errors_months = [
            r.error_days / 30.44 for r in results if r.error_days is not None
        ]

        if errors_months:
            mae = mean([abs(e) for e in errors_months])
            med_ae = median([abs(e) for e in errors_months])
            rmse = math.sqrt(mean([e**2 for e in errors_months]))

            logger.info(f"\nLong-Term Maturity Accuracy (n={len(errors_months)}):")
            logger.info(f"MAE: {mae:.2f} months")
            logger.info(f"MedAE: {med_ae:.2f} months")
            logger.info(f"RMSE: {rmse:.2f} months")

            # Bucket analysis
            under_3mo = len([e for e in errors_months if abs(e) <= 3])
            under_6mo = len([e for e in errors_months if abs(e) <= 6])
            under_12mo = len([e for e in errors_months if abs(e) <= 12])
            n = len(errors_months)

            logger.info(
                f"Within 3 months: {under_3mo}/{n} ({100 * under_3mo / n:.1f}%)"
            )
            logger.info(
                f"Within 6 months: {under_6mo}/{n} ({100 * under_6mo / n:.1f}%)"
            )
            logger.info(
                f"Within 12 months: {under_12mo}/{n} ({100 * under_12mo / n:.1f}%)"
            )
        else:
            logger.warning("No evaluable longterm predictions found.")

    elif args.stage == "find_best_control":
        run_find_best_control(base_params, horizon=horizon)

    elif args.stage == "persistence":
        run_persistence_baseline(base_params)

    elif args.stage == "audit":
        run_comparative_audit(base_params, args.years, action_type=args.action_type)

    elif args.stage == "analysis":
        run_detailed_error_analysis(
            base_params, args.years, action_type=args.action_type
        )


if __name__ == "__main__":
    main()
