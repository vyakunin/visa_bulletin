"""
Bayesian hyperparameter optimization for VQS prediction parameters.

Uses Optuna (TPE sampler) to search VqsMetaParams + MetricConfig + GBM space,
minimizing either the multi-horizon composite MAE (objective="mae") or a
user-centric conditional objective targeting Section 0 success metrics
(objective="conditional").

The conditional objective directly optimizes for what users care about:
  - conditional MAE on months with significant movement (|actual| > 30d)
  - movement detection F1 (precision × recall trade-off)
  - 6-month MAE for EB-2/3 India/China (long-horizon planning)
  - overall MAE (sanity: don't blow up on quiet months)

Usage:
    # Standard composite MAE objective (original)
    bazel run //scripts/vqs:tune_params -- --n-trials 30 --timeout 7200

    # Conditional objective (Section 0 metrics)
    bazel run //scripts/vqs:tune_params -- --n-trials 50 --objective conditional

    # Include GBM hyperparameters in search space
    bazel run //scripts/vqs:tune_params -- --n-trials 50 --gbm-params

    # Per-series persistence weights
    bazel run //scripts/vqs:tune_params -- --n-trials 30 --per-series-weights

    # Quick subsample for fast iteration
    bazel run //scripts/vqs:tune_params -- --n-trials 10 --quick
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
from lib.business.vqs.metric_config import MetricConfig, PeriodDiscount

setup_logging(debug=False)
logger = logging.getLogger(__name__)

# Key series for Section 0 conditional objective
_KEY_SERIES = {(3, "2nd"), (3, "3rd"), (2, "2nd"), (2, "3rd")}  # India/China EB-2/3


def build_trial_params(
    trial: optuna.Trial,
    gbm_params: bool = False,
    per_series_weights: bool = False,
) -> tuple[dict, MetricConfig, dict]:
    """Sample parameter space for one trial.

    Returns (agg_params, metric_cfg, extra_params) where extra_params
    contains GBM hyperparameters and per-series persistence weights.
    """
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

    extra_params: dict = {}

    if gbm_params:
        extra_params["gbm"] = {
            "n_estimators": trial.suggest_int("gbm_n_estimators", 50, 300),
            "max_depth": trial.suggest_int("gbm_max_depth", 3, 8),
            "learning_rate": trial.suggest_float("gbm_learning_rate", 0.01, 0.2, log=True),
            "min_child_samples": trial.suggest_int("gbm_min_child_samples", 3, 20),
            "reg_alpha": trial.suggest_float("gbm_reg_alpha", 0.0, 5.0),
            "reg_lambda": trial.suggest_float("gbm_reg_lambda", 0.0, 5.0),
            "movement_threshold": trial.suggest_int("gbm_movement_threshold", 15, 60),
            "gate_threshold": trial.suggest_float("gbm_gate_threshold", 0.3, 0.7),
        }

    if per_series_weights:
        extra_params["per_series_persistence_weight"] = {
            (3, "2nd"): trial.suggest_float("pw_india_eb2", 0.3, 0.9),
            (3, "3rd"): trial.suggest_float("pw_india_eb3", 0.3, 0.9),
            (2, "2nd"): trial.suggest_float("pw_china_eb2", 0.3, 0.9),
            (2, "3rd"): trial.suggest_float("pw_china_eb3", 0.3, 0.9),
        }

    return agg_params, metric_cfg, extra_params


def compute_conditional_objective(
    rows: list,
    config: MetricConfig,
    key_series: set[tuple[int, str]],
    cond_mae_weight: float = 0.3,
    movement_f1_weight: float = 0.3,
    long_horizon_mae_weight: float = 0.2,
    overall_mae_weight: float = 0.2,
) -> float:
    """Compute user-centric conditional objective for Section 0 success metrics.

    Arguments:
        rows: list of MultiHorizonRow from compute_multi_horizon_accuracy
        config: MetricConfig for overall MAE computation
        key_series: set of (country, visa_class) for EB-2/3 India/China focus
        cond_mae_weight: weight for conditional MAE (|actual| > 30d months only)
        movement_f1_weight: weight for movement detection F1
        long_horizon_mae_weight: weight for 6-month horizon MAE on key series
        overall_mae_weight: weight for overall aggregate MAE (sanity)

    Returns:
        scalar to minimize (lower = better)
    """
    all_1m_errors = []
    all_6m_key_errors = []

    # Conditional MAE (1m, |actual move| > 30d) and movement detection
    move_tp = 0
    move_fp = 0
    move_fn = 0
    cond_errors = []

    for r in rows:
        if r.error_days is None or r.actual_cutoff is None or r.current_cutoff is None:
            continue

        actual_move = (r.actual_cutoff - r.current_cutoff).days
        pred_move = 0
        if r.predicted_cutoff and r.current_cutoff:
            pred_move = (r.predicted_cutoff - r.current_cutoff).days

        series_key = (r.country, r.visa_class)
        is_key = series_key in key_series
        correct_dir = (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0)
        actual_sig = abs(actual_move) > 30
        pred_sig = abs(pred_move) > 30

        if r.horizon == 1:
            all_1m_errors.append(float(r.error_days))

            if actual_sig:
                cond_errors.append(float(r.error_days))
            if actual_sig and pred_sig and correct_dir:
                move_tp += 1
            elif pred_sig and not (actual_sig and correct_dir):
                move_fp += 1
            elif actual_sig and not (pred_sig and correct_dir):
                move_fn += 1

        if r.horizon == 6 and is_key:
            all_6m_key_errors.append(float(r.error_days))

    conditional_mae = sum(cond_errors) / len(cond_errors) if cond_errors else 999.0
    overall_mae = sum(all_1m_errors) / len(all_1m_errors) if all_1m_errors else 999.0
    long_horizon_mae = sum(all_6m_key_errors) / len(all_6m_key_errors) if all_6m_key_errors else 999.0

    precision = move_tp / (move_tp + move_fp) if (move_tp + move_fp) > 0 else 0.0
    recall = move_tp / (move_tp + move_fn) if (move_tp + move_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    # We minimize, so negate F1 contribution (higher F1 = lower objective)
    movement_f1_score = 1.0 - f1

    objective = (
        cond_mae_weight * conditional_mae
        + movement_f1_weight * (movement_f1_score * 200)  # scale to ~days range
        + long_horizon_mae_weight * long_horizon_mae
        + overall_mae_weight * overall_mae
    )

    return objective


def _apply_gbm_params(gbm_params: dict) -> None:
    """Apply GBM hyperparameters to the gbm_expert module's defaults.

    Patches all four training functions so Optuna tunes the full GBM:
    1m regression, direct multi-horizon regression, movement classifier, and
    quantile models. Without patching all four, the conditional objective
    (which evaluates classifier quality and 6m MAE) is tuned against a mix
    of tuned and un-tuned models.
    """
    from lib.business.vqs import gbm_expert as _gbm

    # Clear caches since params changed
    _gbm._model_cache.clear()
    _gbm._classifier_cache.clear()
    _gbm._quantile_cache.clear()

    n_estimators = gbm_params.get("n_estimators", 100)
    max_depth = gbm_params.get("max_depth", 4)
    num_leaves = max(15, 2 ** max_depth - 1)
    learning_rate = gbm_params.get("learning_rate", 0.05)
    min_child_samples = gbm_params.get("min_child_samples", 5)
    reg_alpha = gbm_params.get("reg_alpha", 1.0)
    reg_lambda = gbm_params.get("reg_lambda", 1.0)
    movement_threshold = gbm_params.get("movement_threshold", 30)

    def _make_regressor():
        try:
            import lightgbm as lgb
            return lgb.LGBMRegressor(
                n_estimators=n_estimators,
                max_depth=max_depth,
                num_leaves=num_leaves,
                learning_rate=learning_rate,
                min_child_samples=min_child_samples,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=reg_alpha,
                reg_lambda=reg_lambda,
                random_state=42,
                verbose=-1,
            )
        except ImportError:
            return None

    def _make_classifier():
        try:
            import lightgbm as lgb
            return lgb.LGBMClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                num_leaves=num_leaves,
                learning_rate=learning_rate,
                min_child_samples=min_child_samples,
                subsample=0.8,
                colsample_bytree=0.8,
                is_unbalance=True,
                random_state=42,
                verbose=-1,
            )
        except ImportError:
            return None

    # Patch 1: 1m regression model
    def patched_train_1m(knowledge_date, action_type="filing"):
        cache_key = ("reg1m", knowledge_date.year, knowledge_date.month)
        if cache_key in _gbm._model_cache:
            return _gbm._model_cache[cache_key]
        model = _make_regressor()
        if model is None:
            return None
        data = _gbm._build_training_data(knowledge_date, action_type)
        if data is None:
            return None
        import numpy as np
        x_arr = np.array(data[0], dtype=np.float32)
        y_arr = np.array(data[1], dtype=np.float32)
        model.fit(x_arr, y_arr)
        _gbm._model_cache[cache_key] = model
        return model

    # Patch 2: direct multi-horizon regression
    def patched_train_horizon(knowledge_date, horizon, action_type="filing"):
        cache_key = ("direct", knowledge_date.year, knowledge_date.month, horizon)
        if cache_key in _gbm._model_cache:
            return _gbm._model_cache[cache_key]
        model = _make_regressor()
        if model is None:
            return None
        data = _gbm._build_training_data_horizon(knowledge_date, horizon, action_type)
        if data is None:
            return None
        import numpy as np
        x_arr = np.array(data[0], dtype=np.float32)
        y_arr = np.array(data[1], dtype=np.float32)
        model.fit(x_arr, y_arr)
        _gbm._model_cache[cache_key] = model
        return model

    # Patch 3: movement classifier (uses trial's movement_threshold)
    def patched_train_classifier(
        knowledge_date, horizon, movement_threshold_local=None, action_type="filing"
    ):
        thr = movement_threshold_local if movement_threshold_local is not None else movement_threshold
        cache_key = ("clf", knowledge_date.year, knowledge_date.month, horizon, thr)
        if cache_key in _gbm._classifier_cache:
            return _gbm._classifier_cache[cache_key]
        clf = _make_classifier()
        if clf is None:
            return None
        data = _gbm._build_training_data_classifier(knowledge_date, horizon, thr, action_type)
        if data is None:
            return None
        import numpy as np
        x_arr = np.array(data[0], dtype=np.float32)
        y_arr = np.array(data[1], dtype=np.float32)
        n_pos = int(y_arr.sum())
        n_neg = len(y_arr) - n_pos
        if n_pos < 5 or n_neg < 5:
            return None
        clf.fit(x_arr, y_arr)
        _gbm._classifier_cache[cache_key] = clf
        return clf

    _gbm._get_or_train_model = patched_train_1m
    _gbm._get_or_train_model_horizon = patched_train_horizon
    _gbm._get_or_train_classifier = patched_train_classifier


def _add_months_local(d: date, n: int) -> date:
    """Add n months to date d (day-clamped)."""
    month = d.month + n
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, max_day))


def compute_gbm_only_objective(
    movement_threshold: int = 30,
    gate_threshold: float = 0.45,
    quick: bool = False,
    action_type: str = "filing",
) -> float:
    """Directly evaluate GBM Gated / Direct predictions for the 4 key series.

    Called instead of the VQS-ensemble objective when --gbm-params is set, so
    Optuna can actually see the effect of GBM hyperparameters.  The ensemble
    objective down-weights GBM (due to its higher 1m MAE) making GBM params
    invisible to the optimizer.

    Evaluates:
      - GBM Gated at h=1  →  conditional MAE + movement F1 (30% each)
      - GBM Direct at h=6  →  long-horizon MAE for key series (20%)
      - GBM Direct at h=1  →  overall 1m MAE sanity (20%)
    """
    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from lib.business.vqs.gbm_expert import expert_gbm_direct, expert_gbm_gated
    from models.raw_facts import RawFactsLedger

    all_b = sorted(b.publication_date for b in get_all_bulletins())
    if quick:
        all_b = all_b[::3]

    max_b = max(all_b)
    # Only keep bulletins where we can measure the 6m horizon
    eval_bulletins = [b for b in all_b if _add_months_local(b, 6) <= max_b]

    key_series_list = [
        ("2nd", 3),  # India EB-2
        ("3rd", 3),  # India EB-3
        ("2nd", 2),  # China EB-2
        ("3rd", 2),  # China EB-3
    ]

    cond_errors: list[float] = []
    all_1m_errors: list[float] = []
    all_6m_errors: list[float] = []
    move_tp = move_fp = move_fn = 0

    # Pre-load facts once; slice per knowledge_date in the loop
    all_facts = list(RawFactsLedger.objects.all().order_by("publication_date"))

    for pub_date in eval_bulletins:
        knowledge_date = pub_date - __import__("datetime").timedelta(days=1)
        current_facts = [f for f in all_facts if f.publication_date <= knowledge_date]

        for visa_class, country in key_series_list:
            current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
            if current_cutoff is None:
                continue

            # ---- 1m evaluation (GBM Gated) ----
            target_1m = _add_months_local(pub_date, 0)
            actual_1m = get_cutoff_at_date(visa_class, country, action_type, target_1m)
            pred_1m = expert_gbm_gated(
                visa_class, country, action_type, knowledge_date,
                1, movement_threshold, gate_threshold, current_facts,
            )
            if actual_1m is not None and pred_1m is not None:
                err1 = abs((pred_1m - actual_1m).days)
                all_1m_errors.append(float(err1))

                actual_move = (actual_1m - current_cutoff).days
                pred_move = (pred_1m - current_cutoff).days
                actual_sig = abs(actual_move) > 30
                pred_sig = abs(pred_move) > 30
                correct_dir = (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0)

                if actual_sig:
                    cond_errors.append(float(err1))
                if actual_sig and pred_sig and correct_dir:
                    move_tp += 1
                elif pred_sig and not (actual_sig and correct_dir):
                    move_fp += 1
                elif actual_sig and not (pred_sig and correct_dir):
                    move_fn += 1

            # ---- 6m evaluation (GBM Direct) ----
            target_6m = _add_months_local(pub_date, 5)
            actual_6m = get_cutoff_at_date(visa_class, country, action_type, target_6m)
            pred_6m = expert_gbm_direct(
                visa_class, country, action_type, knowledge_date, 6, current_facts,
            )
            if actual_6m is not None and pred_6m is not None:
                all_6m_errors.append(float(abs((pred_6m - actual_6m).days)))

    conditional_mae = sum(cond_errors) / len(cond_errors) if cond_errors else 999.0
    overall_mae = sum(all_1m_errors) / len(all_1m_errors) if all_1m_errors else 999.0
    long_horizon_mae = sum(all_6m_errors) / len(all_6m_errors) if all_6m_errors else 999.0

    precision = move_tp / (move_tp + move_fp) if (move_tp + move_fp) > 0 else 0.0
    recall = move_tp / (move_tp + move_fn) if (move_tp + move_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    movement_f1_score = 1.0 - f1

    objective_value = (
        0.3 * conditional_mae
        + 0.3 * (movement_f1_score * 200)
        + 0.2 * long_horizon_mae
        + 0.2 * overall_mae
    )
    return objective_value, {
        "cond_mae": conditional_mae,
        "overall_mae": overall_mae,
        "long_horizon_mae": long_horizon_mae,
        "f1": f1,
        "move_tp": move_tp,
        "move_fp": move_fp,
        "move_fn": move_fn,
    }


def objective(
    trial: optuna.Trial,
    horizons: list[int],
    quick: bool = False,
    action_type: str | None = None,
    objective_type: str = "mae",
    gbm_params: bool = False,
    per_series_weights: bool = False,
) -> float:
    """Evaluate one parameter configuration, returning objective value to minimize.

    Two objective types are supported:
    - "mae": minimize compute_composite_metric(rows)["composite_mae"] — a
      per-sample weighted horizon-blended MAE with series/regime/magnitude
      weights and Optuna-searched horizon weights. This is NOT the same as the
      reporting composite in evaluate_model.py print_composite_table or the blog
      comparison table (those use a simple per-horizon average with fixed
      MetricConfig default weights).
    - "conditional": minimize compute_conditional_objective — a user-centric mix
      of conditional MAE, movement-detection F1, 6m key-series MAE, and overall
      1m MAE. Preferred for most tuning runs.

    The reporting composite (evaluate_model.py) and the optimization objective
    (this function) are intentionally different: the reporting composite is
    transparent and directly comparable across methods; the optimization objective
    is tuned for user-centric quality (movement detection, long-horizon accuracy
    on key series).
    """
    agg_params, eval_cfg, extra = build_trial_params(trial, gbm_params, per_series_weights)

    # Apply GBM params if requested
    if gbm_params and "gbm" in extra:
        _apply_gbm_params(extra["gbm"])

    # When tuning GBM params with conditional objective, evaluate GBM directly —
    # NOT through the VQS ensemble, which down-weights GBM due to its higher 1m MAE,
    # making GBM hyperparameters invisible to the optimizer.
    if gbm_params and objective_type == "conditional":
        gbm_cfg = extra.get("gbm", {})
        cond_obj, metrics = compute_gbm_only_objective(
            movement_threshold=gbm_cfg.get("movement_threshold", 30),
            gate_threshold=gbm_cfg.get("gate_threshold", 0.45),
            quick=quick,
            action_type=action_type or "filing",
        )
        logger.info(
            f"Trial {trial.number}: CondObj={cond_obj:.1f} "
            f"CondMAE={metrics['cond_mae']:.0f}d F1={metrics['f1']:.2f} "
            f"6mMAE={metrics['long_horizon_mae']:.0f}d "
            f"TP={metrics['move_tp']} FP={metrics['move_fp']} FN={metrics['move_fn']}"
        )
        return cond_obj

    warmup_cfg = replace(eval_cfg, horizon_weights={1: 1.0})
    aggregator = ContextualTrajectoryAggregator(**agg_params)

    bulletins: list[date] | None = None
    if quick:
        from lib.business.vqs.data_cache import get_all_bulletins
        all_b = [b.publication_date for b in get_all_bulletins()]
        bulletins = all_b[::3]

    from lib.business.vqs.accuracy_metrics import EVALUABLE_VISA_CLASSES
    from models.enums.country import Country

    distinct_series = [
        (vc, c)
        for vc in EVALUABLE_VISA_CLASSES
        if vc != "4th"
        for c in [Country.INDIA.value, Country.CHINA.value]
    ]

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

    if objective_type == "conditional":
        result_mae = compute_composite_metric(rows, config=eval_cfg)["composite_mae"]
        cond_obj = compute_conditional_objective(
            rows=rows,
            config=eval_cfg,
            key_series=_KEY_SERIES,
        )
        logger.info(
            f"Trial {trial.number}: CondObj={cond_obj:.1f} CompMAE={result_mae:.1f} | "
            f"lr={agg_params['learning_rate']:.3f}"
        )
        return cond_obj
    else:
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
    parser.add_argument(
        "--objective", type=str, default="mae", choices=["mae", "conditional"],
        help="Optimization objective: 'mae' (original composite) or 'conditional' (Section 0 metrics)",
    )
    parser.add_argument(
        "--gbm-params", action="store_true",
        help="Include GBM hyperparameters (n_estimators, max_depth, lr, etc.) in search space",
    )
    parser.add_argument(
        "--per-series-weights", action="store_true",
        help="Include per-series persistence weights for EB-2/3 India/China",
    )
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
        f"objective={args.objective} quick={args.quick} horizons={args.horizons} "
        f"gbm_params={args.gbm_params} per_series_weights={args.per_series_weights}"
    )

    study.optimize(
        lambda trial: objective(
            trial, args.horizons, args.quick, args.action_type,
            objective_type=args.objective,
            gbm_params=args.gbm_params,
            per_series_weights=args.per_series_weights,
        ),
        n_trials=args.n_trials,
        timeout=args.timeout,
    )

    best = study.best_trial
    logger.info(f"\n{'='*60}")
    logger.info(f"Best trial #{best.number}: objective_value = {best.value:.1f}")
    logger.info("Best params:")
    for k, v in sorted(best.params.items()):
        logger.info(f"  {k}: {v}")

    results = {
        "best_value": best.value,
        "best_params": best.params,
        "best_trial": best.number,
        "objective": args.objective,
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
