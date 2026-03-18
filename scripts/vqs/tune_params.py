"""
Bayesian hyperparameter optimization for VQS prediction parameters.

Uses Optuna (TPE sampler) to search VqsMetaParams + MetricConfig space,
minimizing the multi-horizon composite MAE. Each trial runs the full
evaluation pipeline (~6 min on local machine).

Usage:
    bazel run //scripts/vqs:tune_params -- --n-trials 30 --timeout 7200
    bazel run //scripts/vqs:tune_params -- --n-trials 10 --quick  # subsample bulletins
"""
import argparse
import json
import logging
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

import optuna
from optuna.samplers import TPESampler

from django_config.logging_config import setup_logging
from lib.business.vqs.accuracy_metrics import (
    compute_composite_metric,
    compute_multi_horizon_accuracy,
)
from lib.business.vqs.contextual_aggregator import ContextualTrajectoryAggregator
from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.metric_config import MetricConfig, PeriodDiscount

setup_logging(debug=False)
logger = logging.getLogger(__name__)


def build_trial_params(trial: optuna.Trial) -> tuple[dict, MetricConfig]:
    """Sample parameter space for one trial."""
    
    # Contextual Aggregator Params
    agg_params = {
        "learning_rate": trial.suggest_float("learning_rate", 0.1, 10.0, log=True),
        "blend_temperature": trial.suggest_float("blend_temperature", 0.01, 2.0, log=True),
        "use_regime_context": trial.suggest_categorical("use_regime_context", [True, False]),
    }

    hw = {
        1: trial.suggest_float("hw_1", 0.05, 0.4),
        3: trial.suggest_float("hw_3", 0.1, 0.4),
        6: trial.suggest_float("hw_6", 0.1, 0.4),
        12: trial.suggest_float("hw_12", 0.1, 0.5),
    }
    metric_cfg = MetricConfig(
        horizon_weights=hw,
        period_discounts=[PeriodDiscount(date(2023, 1, 1), date(2023, 12, 31), 0.2)],
        use_huber_loss=trial.suggest_categorical("use_huber_loss", [True, False]),
        trend_weight=trial.suggest_float("trend_weight", 0.0, 0.15),
        fy_boundary_weight=trial.suggest_float("fy_boundary_weight", 0.3, 2.0),
        steady_state_weight=trial.suggest_float("steady_state_weight", 0.5, 2.0),
        move_magnitude_weight=trial.suggest_float("move_magnitude_weight", 0.0, 1.0),
    )

    return agg_params, metric_cfg


def objective(
    trial: optuna.Trial,
    horizons: list[int],
    quick: bool = False,
    action_type: str | None = None,
) -> float:
    """Evaluate one parameter configuration, returning composite MAE."""
    agg_params, eval_cfg = build_trial_params(trial)

    warmup_cfg = replace(eval_cfg, horizon_weights={1: 1.0})

    aggregator = ContextualTrajectoryAggregator(**agg_params)

    bulletins: list[date] | None = None
    if quick:
        from lib.business.vqs.data_cache import get_all_bulletins
        all_b = [b.publication_date for b in get_all_bulletins()]
        bulletins = all_b[::3]

    # Warmup the aggregator
    from lib.business.vqs.accuracy_metrics import EVALUABLE_VISA_CLASSES
    from models.enums.country import Country
    
    distinct_series = [
        (vc, c)
        for vc in EVALUABLE_VISA_CLASSES
        if vc != "4th"
        for c in [Country.INDIA.value, Country.CHINA.value]
    ]
    
    # We need to warmup up to the first evaluation date
    if bulletins:
        first_date = min(bulletins)
        for vc, c in distinct_series:
            aggregator.warmup_history(vc, c, action_type or "filing", first_date, horizons)

    rows = compute_multi_horizon_accuracy(
        bulletins=bulletins,
        horizons=horizons,
        exclude_eb4=True,
        action_type=action_type,
        metric_config=warmup_cfg,
        aggregator=aggregator,
        use_contextual_ensemble=True,
    )

    result = compute_composite_metric(rows, config=eval_cfg)
    mae = result["composite_mae"]
    logger.info(
        f"Trial {trial.number}: MAE={mae:.1f} | "
        f"lr={agg_params['learning_rate']:.3f} temp={agg_params['blend_temperature']:.3f} "
        f"regime={agg_params['use_regime_context']}"
    )
    return mae


def main():
    parser = argparse.ArgumentParser(description="Optuna VQS parameter tuning")
    parser.add_argument("--n-trials", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=None, help="Max seconds")
    parser.add_argument("--quick", action="store_true", help="Subsample bulletins (3x faster)")
    parser.add_argument("--action-type", type=str, default=None, choices=["final_action", "filing"])
    parser.add_argument("--horizons", type=int, nargs="+", default=[1, 3, 6, 12])
    parser.add_argument("--output-dir", type=str, default="/tmp/vqs_optuna")
    parser.add_argument("--study-name", type=str, default="vqs_tune")
    parser.add_argument("--db", type=str, default=None, help="Optuna storage URL (e.g. sqlite:///optuna.db)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    storage = args.db or f"sqlite:///{output_dir / 'optuna.db'}"
    study = optuna.create_study(
        study_name=args.study_name,
        storage=storage,
        direction="minimize",
        sampler=TPESampler(seed=42),
        load_if_exists=True,
    )

    logger.info(
        f"Starting Optuna study: {args.n_trials} trials, "
        f"quick={args.quick}, horizons={args.horizons}"
    )

    study.optimize(
        lambda trial: objective(trial, args.horizons, args.quick, args.action_type),
        n_trials=args.n_trials,
        timeout=args.timeout,
    )

    best = study.best_trial
    logger.info(f"\n{'='*60}")
    logger.info(f"Best trial #{best.number}: composite_mae = {best.value:.1f}")
    logger.info("Best params:")
    for k, v in sorted(best.params.items()):
        logger.info(f"  {k}: {v}")

    results = {
        "best_value": best.value,
        "best_params": best.params,
        "best_trial": best.number,
        "n_trials": len(study.trials),
        "all_trials": [
            {"number": t.number, "value": t.value, "params": t.params}
            for t in study.trials
            if t.value is not None
        ],
    }
    out_path = output_dir / "optuna_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
