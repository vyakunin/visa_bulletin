"""VQS Model Evaluation and Comparison.

Runs the current VQS model against persistence and dashboard-trend baselines,
outputs a metrics table, and generates an interactive HTML visualization
showing predictions at multiple horizons vs actuals with cumulative error.

Includes per-regime, per-FY-phase, and per-movement-magnitude stratified
metrics to reveal where each model adds value vs where it is just persistence.

Usage:
    bazel run //scripts/vqs:evaluate_model
    bazel run //scripts/vqs:evaluate_model -- --quick
    bazel run //scripts/vqs:evaluate_model -- --series "India EB-2"
    bazel run //scripts/vqs:evaluate_model -- --horizons 1,3,6,12
"""

import argparse
import datetime
import json
import logging
import os
import time
from collections import defaultdict

import django
import numpy as np

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from dateutil.relativedelta import relativedelta
from django.conf import settings

from lib.business.vqs.contextual_aggregator import ContextualTrajectoryAggregator
from lib.business.vqs.metric_config import MetricConfig
from lib.business.vqs.gbm_expert import (
    _GBM_DEFAULT_GATE_THRESHOLD,
    _GBM_DEFAULT_MOVEMENT_THRESHOLD,
    expert_gbm,
    expert_gbm_direct,
    expert_gbm_gated,
)
from lib.business.vqs.prediction_loader import (
    build_regime_switched_cache,
    build_solver_cache,
    build_solver_cache_ablated,
    get_actual_cutoffs,
    load_stored_predictions_bulk,
)
from lib.business.vqs.regime import classify_regime, get_fy_phase
from lib.business.vqs.seasonal_predictor import get_last_N_moves
from models.enums.country import Country
from models.raw_facts import RawFactsLedger
from models.visa_cutoff_date import VisaCutoffDate

logging.basicConfig(level=logging.INFO)
logging.getLogger("lib.business.vqs.solver").setLevel(logging.WARNING)
logging.getLogger("lib.business.vqs.aggregator").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

FY_BOUNDARY_MONTHS = {9, 10, 11}

# Historical EB visa supply by fiscal year (base + spillover estimates).
# Source: DOS annual reports + community estimates (arika1447, Oppenheim).
FY_EB_SUPPLY = {
    2016: 140_000,
    2017: 140_000,
    2018: 140_000,
    2019: 140_000,
    2020: 140_000,
    2021: 170_000,
    2022: 280_000,
    2023: 197_000,
    2024: 161_000,
    2025: 150_000,
    2026: 140_000,
}

SERIES = [
    (Country.INDIA.value, "2nd", "India EB-2"),
    (Country.INDIA.value, "3rd", "India EB-3"),
    (Country.CHINA.value, "2nd", "China EB-2"),
    (Country.CHINA.value, "3rd", "China EB-3"),
    (Country.CHINA.value, "1st", "China EB-1"),
    (Country.INDIA.value, "1st", "India EB-1"),
]

ACTION_TYPE = "filing"
DEFAULT_HORIZONS = [1, 3, 6]


def forecast_persistence(visa_class, country, target_date, horizon):
    """Static/persistence: predicts no change from horizon months ago."""
    knowledge_date = target_date - relativedelta(months=horizon)
    latest = (
        VisaCutoffDate.objects.filter(
            visa_class=visa_class, country=country, action_type=ACTION_TYPE,
            bulletin__publication_date__lte=knowledge_date,
        )
        .order_by("-bulletin__publication_date")
        .first()
    )
    return latest.cutoff_date if latest and latest.cutoff_date else None


def forecast_dashboard(visa_class, country, target_date, horizon):
    """Dashboard trend: 12-month moving average pace projected forward."""
    knowledge_date = target_date - relativedelta(months=horizon)
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class, country=country, action_type=ACTION_TYPE,
        bulletin__publication_date__lte=knowledge_date,
    ).order_by("bulletin__publication_date")

    cutoff_12m_ago = knowledge_date - datetime.timedelta(days=366)
    recent = [
        (h.bulletin.publication_date, h.cutoff_date)
        for h in history if h.cutoff_date and h.bulletin.publication_date > cutoff_12m_ago
    ]
    if len(recent) < 2:
        return recent[-1][1] if recent else None

    first_date, first_val = recent[0]
    last_date, last_val = recent[-1]
    months_diff = max(1, (last_date.year - first_date.year) * 12 + last_date.month - first_date.month)
    rate = (last_val - first_val).days / months_diff

    if rate <= 0:
        return last_val
    return last_val + datetime.timedelta(days=int(rate * horizon))



def build_contextual_cache(
    visa_class: str,
    country: int,
    knowledge_dates: list[datetime.date],
    horizons: list[int],
    action_type: str = "filing",
) -> dict[tuple[datetime.date, int], datetime.date]:
    cache = {}
    aggregator = ContextualTrajectoryAggregator()

    # We need to process knowledge dates chronologically
    # For each knowledge date, we first update the aggregator with any new actuals that became known
    # since the last knowledge date, then we predict.

    from lib.business.vqs.data_cache import get_all_bulletins
    all_b = sorted(get_all_bulletins(), key=lambda x: x.publication_date)

    last_kd = None
    for kd in sorted(knowledge_dates):
        # Update weights with bulletins that became known between last_kd and kd
        # Actually, just call warmup_history up to kd. It's idempotent if we just recreate or we can optimize.
        # Let's just recreate and warmup for simplicity, or we can optimize by only updating.
        # To optimize:
        new_bulletins = [b for b in all_b if (last_kd is None or b.publication_date > last_kd) and b.publication_date <= kd]
        for b in new_bulletins:
            actual_obj = VisaCutoffDate.objects.filter(
                bulletin=b,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
            ).first()
            if actual_obj and actual_obj.cutoff_date:
                for h in horizons:
                    aggregator.update_weights(
                        visa_class=visa_class,
                        country=country,
                        action_type=action_type,
                        target_date=b.publication_date,
                        horizon=h,
                        actual_date=actual_obj.cutoff_date,
                    )

        last_kd = kd

        # Now predict for all horizons
        for h in horizons:
            target_date = kd + relativedelta(months=h)
            pred, _ = aggregator.predict(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                target_date=target_date,
                horizon=h,
            )
            if pred:
                cache[(kd, h)] = pred

    return cache


_GBM_FEATURE_GROUPS: dict[str, list[int]] = {
    # Recent velocity / momentum (move_1m … move_12m_avg)
    "velocity": [2, 3, 4, 5, 6],
    # Calendar / FY seasonality (month_of_year, FY flags, months_into_fy, retro_distance)
    "seasonality": [7, 8, 9, 17, 20],
    # Macro supply/demand signals (cutoff_age, I-140 ratio, I-485 queue, utilization, demand_ratio_class, velocity_6m)
    "macro": [10, 11, 12, 16, 18, 19],
    # Demand-drop signals – ROW velocity + issuance drop (indices 22-25)
    "demand_drop": [22, 23, 24, 25],
    # Cross-series EB-1 signals + near-cutoff I-485 density
    "cross_series": [13, 14, 15, 21, 26],
}


def build_gbm_caches(
    visa_class: str,
    country: int,
    knowledge_dates: list[datetime.date],
    horizons: list[int],
    action_type: str = "filing",
    movement_threshold: int = _GBM_DEFAULT_MOVEMENT_THRESHOLD,
    gate_threshold: float = _GBM_DEFAULT_GATE_THRESHOLD,
    ablate_group: str | None = None,
) -> tuple[
    dict[tuple[datetime.date, int], datetime.date],
    dict[tuple[datetime.date, int], datetime.date],
    dict[tuple[datetime.date, int], datetime.date],
]:
    """Build GBM standalone, GBM Direct, and GBM Gated prediction caches.

    Returns (gbm_cache, gbm_direct_cache, gbm_gated_cache) where each maps
    (knowledge_date, horizon) -> predicted_cutoff_date.

    GBM standalone: 1-step model, applied h times (iterated linear).
    GBM Direct: separate model per horizon, no error compounding.
    GBM Gated: classifier decides whether to predict or defer to persistence.

    ablate_group: if set, zero out the corresponding feature indices (from
        _GBM_FEATURE_GROUPS) at inference time to measure group contribution.
        Valid values: "velocity", "seasonality", "macro", "demand_drop", "cross_series".
    """
    import lib.business.vqs.gbm_expert as _gbm_mod
    from lib.business.vqs.data_cache import get_cutoff_at_date

    _orig_build = _gbm_mod._build_features_for_series
    if ablate_group is not None:
        zero_indices = _GBM_FEATURE_GROUPS.get(ablate_group)
        if zero_indices is None:
            raise ValueError(f"Unknown ablate_group '{ablate_group}'. Valid: {list(_GBM_FEATURE_GROUPS)}")
        # Clear model caches so this run trains fresh on ablated features, ensuring
        # inference and training are consistent for the ablation study.
        _gbm_mod._model_cache.clear()
        _gbm_mod._classifier_cache.clear()
        _gbm_mod._quantile_cache.clear()
        def _ablated_build(*args, **kwargs):
            feats = _orig_build(*args, **kwargs)
            if feats is not None:
                feats = list(feats)
                for idx in zero_indices:
                    if idx < len(feats):
                        feats[idx] = 0.0
            return feats
        _gbm_mod._build_features_for_series = _ablated_build

    try:
        gbm_cache: dict[tuple, datetime.date] = {}
        gbm_direct_cache: dict[tuple, datetime.date] = {}
        gbm_gated_cache: dict[tuple, datetime.date] = {}

        for kd in sorted(knowledge_dates):
            current_cutoff = get_cutoff_at_date(visa_class, country, action_type, kd)
            pred_1m = expert_gbm(visa_class, country, action_type, kd)
            move_1m = (pred_1m - current_cutoff).days if (pred_1m and current_cutoff) else None

            for h in horizons:
                # GBM standalone: apply 1m move h times (iterated linear extrapolation)
                if current_cutoff and move_1m is not None:
                    total_move = max(-90 * h, min(365 * h, move_1m * h))
                    gbm_cache[(kd, h)] = current_cutoff + datetime.timedelta(days=total_move)

                # GBM Direct: per-horizon trained model
                pred_direct = expert_gbm_direct(visa_class, country, action_type, kd, h)
                if pred_direct:
                    gbm_direct_cache[(kd, h)] = pred_direct

                # GBM Gated: classifier + regression
                pred_gated = expert_gbm_gated(
                    visa_class, country, action_type, kd, h,
                    movement_threshold=movement_threshold,
                    gate_threshold=gate_threshold,
                )
                if pred_gated:
                    gbm_gated_cache[(kd, h)] = pred_gated
    finally:
        if ablate_group is not None:
            _gbm_mod._build_features_for_series = _orig_build

    return gbm_cache, gbm_direct_cache, gbm_gated_cache


def compute_metrics(dates, actuals, predictions, label, error_start):
    """Compute metrics for a model's predictions.

    Includes:
    - MAE (mean absolute error, days)
    - direction_acc: % of non-zero actual moves where predicted direction matches
    - big_move_capture_rate: % of actual big moves (>90d) where model predicted a big move (>90d)
    - regime_change_detection_acc: When actual regime changed vs prior, did model predict
      movement in the correct direction?
    - cond_direction_acc: direction accuracy only when |actual_move| > 30d (Section 0 metric)
    - movement_precision: of times model predicted |move| > 30d, how often |actual| > 30d?
    - movement_recall: of times |actual| > 30d, how often did model predict |move| > 30d?
    """
    errors = []
    direction_correct = 0
    direction_total = 0
    big_move_predicted = 0
    big_move_actual = 0
    regime_change_correct = 0
    regime_change_total = 0

    # Section 0 conditional metrics
    cond_dir_correct = 0
    cond_dir_total = 0       # times |actual_move| > 30d
    move_tp = 0              # predicted > 30d AND actual > 30d (correct direction)
    move_fp = 0              # predicted > 30d but actual <= 30d (or wrong direction)
    move_fn = 0              # actual > 30d but model predicted <= 30d

    for i, d in enumerate(dates):
        if d < error_start or actuals[i] is None or predictions[i] is None:
            continue
        err = abs((predictions[i] - actuals[i]).days)
        errors.append(err)

        if i > 0 and actuals[i - 1] is not None and predictions[i] is not None:
            actual_move = (actuals[i] - actuals[i - 1]).days
            pred_move = (predictions[i] - actuals[i - 1]).days

            if actual_move != 0:
                direction_total += 1
                if (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0):
                    direction_correct += 1

            # Big-move capture: actual move >90d in either direction
            if abs(actual_move) > 90:
                big_move_actual += 1
                if abs(pred_move) > 90 and (
                    (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0)
                ):
                    big_move_predicted += 1

            # Regime change detection: actual moved after prior stall (prev move ≈0, current ≠0)
            if i >= 2 and actuals[i - 2] is not None:
                prior_move = (actuals[i - 1] - actuals[i - 2]).days
                is_regime_change = abs(prior_move) <= 5 and abs(actual_move) > 30
                if is_regime_change:
                    regime_change_total += 1
                    if (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0):
                        regime_change_correct += 1

            # Section 0: conditional direction accuracy on significant actual moves
            actual_significant = abs(actual_move) > 30
            pred_significant = abs(pred_move) > 30
            correct_dir = (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0)

            if actual_significant:
                cond_dir_total += 1
                if correct_dir:
                    cond_dir_correct += 1

            # Movement detection precision/recall (|move| > 30d as "positive" class)
            if actual_significant and pred_significant and correct_dir:
                move_tp += 1
            elif pred_significant and not (actual_significant and correct_dir):
                move_fp += 1
            elif actual_significant and not (pred_significant and correct_dir):
                move_fn += 1

    if not errors:
        return {
            "label": label, "mae": None, "cumulative": 0,
            "direction_acc": None, "count": 0,
            "big_move_capture_rate": None, "regime_change_detection_acc": None,
            "cond_direction_acc": None, "movement_precision": None, "movement_recall": None,
        }

    precision = move_tp / (move_tp + move_fp) if (move_tp + move_fp) > 0 else None
    recall = move_tp / (move_tp + move_fn) if (move_tp + move_fn) > 0 else None

    return {
        "label": label,
        "mae": round(sum(errors) / len(errors), 1),
        "cumulative": sum(errors),
        "direction_acc": round(direction_correct / direction_total * 100, 1) if direction_total > 0 else None,
        "count": len(errors),
        "big_move_capture_rate": round(big_move_predicted / big_move_actual * 100, 1) if big_move_actual > 0 else None,
        "big_move_actual_count": big_move_actual,
        "regime_change_detection_acc": round(regime_change_correct / regime_change_total * 100, 1) if regime_change_total > 0 else None,
        "cond_direction_acc": round(cond_dir_correct / cond_dir_total * 100, 1) if cond_dir_total > 0 else None,
        "movement_precision": round(precision * 100, 1) if precision is not None else None,
        "movement_recall": round(recall * 100, 1) if recall is not None else None,
    }


def forecast_pace(visa_class, country, target_date, horizon):
    """Constant-pace baseline: Charlie Oppenheim's rule of thumb.

    Applies category-specific daily pace per month based on historical
    averages. This is the "domain expert benchmark" approach.
    """
    pace_days_per_month = {
        (Country.INDIA.value, "2nd"): 7,
        (Country.INDIA.value, "3rd"): 7,
        (Country.INDIA.value, "1st"): 14,
        (Country.CHINA.value, "2nd"): 14,
        (Country.CHINA.value, "3rd"): 21,
        (Country.CHINA.value, "1st"): 21,
    }
    knowledge_date = target_date - relativedelta(months=horizon)
    latest = (
        VisaCutoffDate.objects.filter(
            visa_class=visa_class, country=country, action_type=ACTION_TYPE,
            bulletin__publication_date__lte=knowledge_date,
        )
        .order_by("-bulletin__publication_date")
        .first()
    )
    if not latest or not latest.cutoff_date:
        return None

    pace = pace_days_per_month.get((country, visa_class), 7)
    return latest.cutoff_date + datetime.timedelta(days=pace * horizon)


_I140_DEMAND_CACHE: dict[tuple, float] = {}

# Calibrated baseline queue density (applicants per priority-date-day).
# Used when I-140 data is unavailable. Derived from historical queue depth estimates.
_DEMAND_BASELINE = {
    (Country.INDIA.value, "2nd"): 25.0,
    (Country.INDIA.value, "3rd"): 15.0,
    (Country.INDIA.value, "1st"): 8.0,
    (Country.CHINA.value, "2nd"): 10.0,
    (Country.CHINA.value, "3rd"): 5.0,
    (Country.CHINA.value, "1st"): 4.0,
}


def _get_i140_demand_per_day(
    visa_class: str,
    country: int,
    knowledge_date: "datetime.date",
) -> float:
    """Estimate demand per priority-date-day using real I-140 receipts from ledger.

    Uses baseline queue density scaled by the recent I-140 trend ratio (recent
    2 quarters vs historical average).  Falls back to baseline constant when
    fewer than 4 quarterly data points are available.
    """
    cache_key = (visa_class, country, knowledge_date)
    if cache_key in _I140_DEMAND_CACHE:
        return _I140_DEMAND_CACHE[cache_key]

    baseline = _DEMAND_BASELINE.get((country, visa_class), 10.0)

    rows = list(
        RawFactsLedger.objects.filter(
            metric="i140_receipts",
            publication_date__lte=knowledge_date,
        ).order_by("reference_period_start")
    )
    country_rows = [r for r in rows if str(r.dimensions.get("country")) == str(country)]

    if len(country_rows) < 4:
        _I140_DEMAND_CACHE[cache_key] = baseline
        return baseline

    def _val(r) -> float:
        v = r.value
        if isinstance(v, (list, tuple)) and v:
            v = v[0]
        try:
            return max(0.0, float(v))
        except (TypeError, ValueError):
            return 0.0

    recent = country_rows[-2:]
    hist = country_rows[:-2]
    recent_avg = sum(_val(r) for r in recent) / max(len(recent), 1)
    hist_avg = sum(_val(r) for r in hist) / max(len(hist), 1)

    if hist_avg <= 0:
        _I140_DEMAND_CACHE[cache_key] = baseline
        return baseline

    # Scale baseline by trend: if recent filings are 20% above historical, assume 20% more demand.
    # Clamped to [0.5, 2.0] to avoid extreme swings from sparse data.
    i140_ratio = max(0.5, min(2.0, recent_avg / hist_avg))
    demand = baseline * i140_ratio

    _I140_DEMAND_CACHE[cache_key] = demand
    return demand


def forecast_demand_supply(visa_class, country, target_date, horizon):
    """Demand-supply heuristic (PhoenixCTB approach).

    Estimates how fast the FAD should move based on the ratio of
    annual EB supply (for this country+class) to approximate backlog depth.
    Falls back to persistence when data is insufficient.

    The heuristic: monthly_advance = (annual_supply_share / backlog_months) * 30 days
    where backlog_months is a rough approximation from the gap between
    FAD and current date divided by historical pace.

    Demand is now derived from real I-140 receipt data (trend-scaled baseline),
    replacing the previously static hardcoded constants.
    """
    from lib.business.vqs.estimators import (
        DEFAULT_ANNUAL_EB_LIMIT,
        PER_CLASS_SHARE,
        PER_COUNTRY_SHARE,
    )

    knowledge_date = target_date - relativedelta(months=horizon)
    latest = (
        VisaCutoffDate.objects.filter(
            visa_class=visa_class, country=country, action_type=ACTION_TYPE,
            bulletin__publication_date__lte=knowledge_date,
        )
        .order_by("-bulletin__publication_date")
        .first()
    )
    if not latest or not latest.cutoff_date:
        return None

    current_fad = latest.cutoff_date
    fad_gap_days = (knowledge_date - current_fad).days
    if fad_gap_days <= 0:
        return current_fad + datetime.timedelta(days=horizon * 30)

    fy = target_date.year if target_date.month >= 10 else target_date.year
    annual_supply = FY_EB_SUPPLY.get(fy, DEFAULT_ANNUAL_EB_LIMIT)

    class_share = PER_CLASS_SHARE.get(visa_class, 0.286)
    country_share = PER_COUNTRY_SHARE
    monthly_visa_budget = (annual_supply * class_share * country_share) / 12.0

    demand_per_day = _get_i140_demand_per_day(visa_class, country, knowledge_date)

    if demand_per_day <= 0:
        return current_fad

    monthly_pace_days = monthly_visa_budget / demand_per_day
    total_advance = int(monthly_pace_days * horizon)

    return current_fad + datetime.timedelta(days=total_advance)


def forecast_momentum_3m(visa_class, country, target_date, horizon):
    """3-month momentum: extrapolate the average of the last 3 monthly moves forward.

    Popular community approach (Reddit, Trackitt): assumes the recent pace continues.
    Walk-forward safe.
    """
    from lib.business.vqs.data_cache import get_cutoffs_up_to
    knowledge_date = target_date - relativedelta(months=horizon)
    cutoffs = get_cutoffs_up_to(visa_class, country, ACTION_TYPE, knowledge_date)
    if len(cutoffs) < 4:
        return forecast_persistence(visa_class, country, target_date, horizon)
    recent = cutoffs[-4:]
    moves = [(recent[i].cutoff_date - recent[i - 1].cutoff_date).days for i in range(1, 4) if recent[i].cutoff_date and recent[i - 1].cutoff_date]
    if not moves:
        return forecast_persistence(visa_class, country, target_date, horizon)
    avg_move = sum(moves) / len(moves)
    last_cutoff = recent[-1].cutoff_date
    if not last_cutoff:
        return None
    return last_cutoff + datetime.timedelta(days=int(avg_move * horizon))


def forecast_seasonal_median(visa_class, country, target_date, horizon):
    """Seasonal median: predict each future month's movement using its historical median.

    Captures the strong FY seasonal pattern (October retrogression, September
    acceleration) without any trained model. Walk-forward safe.
    """
    from lib.business.vqs.seasonal_predictor import get_seasonal_prediction
    knowledge_date = target_date - relativedelta(months=horizon)
    latest = (
        VisaCutoffDate.objects.filter(
            visa_class=visa_class, country=country, action_type=ACTION_TYPE,
            bulletin__publication_date__lte=knowledge_date,
        )
        .order_by("-bulletin__publication_date")
        .first()
    )
    if not latest or not latest.cutoff_date:
        return None
    current = latest.cutoff_date
    current_kd = knowledge_date
    for _ in range(horizon):
        next_kd = current_kd + relativedelta(months=1)
        move = get_seasonal_prediction(
            visa_class, country, ACTION_TYPE, current_kd, next_kd.month
        )
        current = current + datetime.timedelta(days=move if move is not None else 0)
        current_kd = next_kd
    return current


def forecast_polynomial_trend(visa_class, country, target_date, horizon):
    """Polynomial trend (degree 2): fit a quadratic to last 12 months, extrapolate.

    Captures acceleration/deceleration that linear trend misses. Walk-forward safe.
    Falls back to persistence when fewer than 4 data points are available.
    """
    from lib.business.vqs.data_cache import get_cutoffs_up_to
    knowledge_date = target_date - relativedelta(months=horizon)
    cutoffs = get_cutoffs_up_to(visa_class, country, ACTION_TYPE, knowledge_date)
    cutoff_12m_ago = knowledge_date - datetime.timedelta(days=366)
    recent = [c for c in cutoffs if c.bulletin.publication_date > cutoff_12m_ago and c.cutoff_date]
    if len(recent) < 4:
        return forecast_persistence(visa_class, country, target_date, horizon)
    t0 = recent[0].bulletin.publication_date
    x = np.array([(c.bulletin.publication_date - t0).days for c in recent], dtype=float)
    y = np.array([(c.cutoff_date - recent[0].cutoff_date).days for c in recent], dtype=float)
    try:
        coeffs = np.polyfit(x, y, 2)
    except (np.linalg.LinAlgError, ValueError):
        return forecast_persistence(visa_class, country, target_date, horizon)
    last_cutoff = recent[-1].cutoff_date
    last_x = (recent[-1].bulletin.publication_date - t0).days
    predict_x = (target_date - t0).days
    delta = float(np.polyval(coeffs, predict_x) - np.polyval(coeffs, last_x))
    delta = max(-180.0 * horizon, min(365.0 * horizon, delta))
    return last_cutoff + datetime.timedelta(days=int(delta))


def classify_move_magnitude(move_days: int) -> str:
    """Classify movement magnitude into buckets."""
    abs_move = abs(move_days)
    if abs_move == 0:
        return "none"
    if abs_move <= 30:
        return "small"
    if abs_move <= 90:
        return "medium"
    return "big"


def classify_data_point(
    visa_class: str, country: int, target_date: datetime.date, horizon: int,
    actual: datetime.date | None, previous_actual: datetime.date | None,
) -> dict:
    """Classify a single data point by regime, FY phase, and movement magnitude."""
    knowledge_date = target_date - relativedelta(months=horizon)
    moves = get_last_N_moves(visa_class, country, ACTION_TYPE, knowledge_date, 6)
    regime_state = classify_regime(moves)
    fy_phase = get_fy_phase(target_date.month)

    actual_move_days = 0
    if actual and previous_actual:
        actual_move_days = (actual - previous_actual).days

    return {
        "regime": regime_state.regime.value,
        "fy_phase": fy_phase.value,
        "move_mag": classify_move_magnitude(actual_move_days),
        "actual_move_days": actual_move_days,
    }


def compute_stratified_metrics(
    plot_dates: list[datetime.date],
    actual_list: list[datetime.date | None],
    model_lists: dict[str, list[datetime.date | None]],
    point_meta: list[dict],
    error_start: datetime.date,
) -> dict:
    """Compute metrics broken down by regime, FY phase, and movement magnitude.

    Returns a nested dict: {dimension: {value: {model: {mae, dir_acc, count, win_rate}}}}
    """
    dimensions = {
        "regime": lambda m: m["regime"],
        "fy_phase": lambda m: m["fy_phase"],
        "move_mag": lambda m: m["move_mag"],
    }
    result = {}

    for dim_name, dim_fn in dimensions.items():
        buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

        for i, d in enumerate(plot_dates):
            if d < error_start or actual_list[i] is None:
                continue
            meta = point_meta[i]
            bucket_key = dim_fn(meta)

            for model_name, preds in model_lists.items():
                pred = preds[i]
                if pred is None:
                    continue
                err = abs((pred - actual_list[i]).days)
                persist_pred = model_lists["Persistence"][i]
                persist_err = abs((persist_pred - actual_list[i]).days) if persist_pred else None

                dir_correct = None
                if i > 0 and actual_list[i - 1] is not None:
                    actual_move = (actual_list[i] - actual_list[i - 1]).days
                    pred_move = (pred - actual_list[i - 1]).days
                    if actual_move != 0:
                        dir_correct = (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0)

                buckets[bucket_key][model_name].append({
                    "err": err,
                    "persist_err": persist_err,
                    "dir_correct": dir_correct,
                })

        dim_result = {}
        for bucket_key, model_data in sorted(buckets.items()):
            bucket_models = {}
            for model_name, entries in model_data.items():
                errors = [e["err"] for e in entries]
                mae = sum(errors) / len(errors) if errors else None
                dir_entries = [e["dir_correct"] for e in entries if e["dir_correct"] is not None]
                dir_acc = (sum(dir_entries) / len(dir_entries) * 100) if dir_entries else None

                wins = sum(1 for e in entries if e["persist_err"] is not None and e["err"] < e["persist_err"])
                losses = sum(1 for e in entries if e["persist_err"] is not None and e["err"] > e["persist_err"])
                decisions = wins + losses
                win_rate = (wins / decisions * 100) if decisions > 0 else None

                bucket_models[model_name] = {
                    "mae": round(mae, 1) if mae is not None else None,
                    "dir_acc": round(dir_acc, 1) if dir_acc is not None else None,
                    "count": len(errors),
                    "win_rate": round(win_rate, 1) if win_rate is not None else None,
                }
            dim_result[bucket_key] = bucket_models
        result[dim_name] = dim_result

    return result


def print_stratified_table(all_stratified: dict[str, dict], horizons: list[int]):
    """Print stratified metrics tables per series and horizon."""
    # Detect ablation model from data
    has_ablation = any(
        "VQS No Cross-Series" in bucket_models
        for horizon_data in all_stratified.values()
        for strat in horizon_data.values()
        for dim_data in strat.values()
        for bucket_models in dim_data.values()
    )
    has_gbm = any(
        "GBM" in bucket_models
        for horizon_data in all_stratified.values()
        for strat in horizon_data.values()
        for dim_data in strat.values()
        for bucket_models in dim_data.values()
    )
    if has_gbm:
        models = MODELS_GBM
    elif has_ablation:
        models = MODELS_ABLATE
    else:
        models = MODELS

    for series_label, horizon_data in sorted(all_stratified.items()):
        for h, strat in sorted(horizon_data.items(), key=lambda x: int(x[0])):
            print(f"\n{'='*100}")
            print(f"  {series_label} — {h}-month horizon — STRATIFIED BREAKDOWN")
            print(f"{'='*100}")

            for dim_name in ["regime", "fy_phase", "move_mag"]:
                if dim_name not in strat:
                    continue
                dim_data = strat[dim_name]
                dim_label = {"regime": "REGIME", "fy_phase": "FY PHASE", "move_mag": "MOVE SIZE"}[dim_name]
                print(f"\n  --- By {dim_label} ---")
                print(f"  {'Bucket':<16} {'Model':<18} {'MAE':>8} {'DirAcc':>8} {'WinRate':>8} {'N':>6}")
                print(f"  {'-'*70}")

                for bucket_key, bucket_models in sorted(dim_data.items()):
                    for model in models:
                        m = bucket_models.get(model)
                        if not m or m["count"] == 0:
                            continue
                        mae_s = f"{m['mae']:.1f}" if m["mae"] is not None else "N/A"
                        da_s = f"{m['dir_acc']:.1f}%" if m["dir_acc"] is not None else "N/A"
                        wr_s = f"{m['win_rate']:.1f}%" if m["win_rate"] is not None else "—"
                        print(f"  {bucket_key:<16} {model:<18} {mae_s:>8} {da_s:>8} {wr_s:>8} {m['count']:>6}")
                    print()


_CROSS_SERIES_EXPERTS = frozenset({"cross_series", "gbm"})


def run_evaluation(start_date, end_date, horizons, series_filter=None, step=1, diagnostic=False, ablate=False, gbm=False, gate_threshold: float = _GBM_DEFAULT_GATE_THRESHOLD, ablate_group: str | None = None):
    """Run evaluation across all series and horizons, return chart data and metrics."""
    chart_data = {}
    all_metrics = []
    all_stratified = {}

    vqs_start = None
    if RawFactsLedger.objects.exists():
        vqs_start = RawFactsLedger.objects.order_by("publication_date").first().publication_date

    max_horizon = max(horizons)
    error_start = start_date + relativedelta(months=max_horizon + 12)

    for country, visa_class, label in SERIES:
        if series_filter and label != series_filter:
            continue
        logger.info(f"Processing {label}...")
        t0 = time.time()

        true_data = get_actual_cutoffs(visa_class, country, ACTION_TYPE)
        sorted_dates = sorted(true_data.keys())
        plot_dates = [d for d in sorted_dates if start_date <= d <= end_date][::step]

        stored_vqs = load_stored_predictions_bulk(visa_class, country, ACTION_TYPE)
        stored_count = sum(1 for d in plot_dates if d in stored_vqs)
        logger.info(f"  Stored VQS predictions available: {stored_count}/{len(plot_dates)}")

        all_knowledge_dates = set()
        for h in horizons:
            for d in plot_dates:
                if h == 1 and d in stored_vqs:
                    continue
                all_knowledge_dates.add(d - relativedelta(months=h))
        vqs_cache = build_solver_cache(visa_class, country, sorted(all_knowledge_dates), ACTION_TYPE)
        logger.info(f"  VQS cache built: {len(vqs_cache)} entries from {len(all_knowledge_dates)} knowledge dates")

        # Build regime-switched cache (undampened selector)
        all_kd_for_rs = set()
        for h in horizons:
            for d in plot_dates:
                all_kd_for_rs.add(d - relativedelta(months=h))
        rs_cache = build_regime_switched_cache(visa_class, country, sorted(all_kd_for_rs), ACTION_TYPE)
        ctx_cache = build_contextual_cache(visa_class, country, sorted(all_kd_for_rs), horizons, ACTION_TYPE)
        logger.info(f"  Contextual cache built: {len(ctx_cache)} entries")
        logger.info(f"  Regime-switched cache built: {len(rs_cache)} entries")

        ablation_cache = {}
        if ablate:
            ablation_cache = build_solver_cache_ablated(
                visa_class, country, sorted(all_knowledge_dates), ACTION_TYPE,
                excluded_experts=_CROSS_SERIES_EXPERTS,
            )
            logger.info(f"  Ablation cache built: {len(ablation_cache)} entries (no cross-series/GBM)")

        gbm_cache: dict = {}
        gbm_direct_cache: dict = {}
        gbm_gated_cache: dict = {}
        if gbm:
            gbm_cache, gbm_direct_cache, gbm_gated_cache = build_gbm_caches(
                visa_class, country, sorted(all_kd_for_rs), horizons, ACTION_TYPE,
                gate_threshold=gate_threshold,
                ablate_group=ablate_group,
            )
            logger.info(
                f"  GBM caches built: standalone={len(gbm_cache)} direct={len(gbm_direct_cache)}"
                f" gated={len(gbm_gated_cache)}"
            )

        dates_str = [d.strftime("%Y-%m-%d") for d in plot_dates]
        actual_vals = [
            true_data.get(d).strftime("%Y-%m-%d") if true_data.get(d) else None
            for d in plot_dates
        ]
        actual_list = [true_data.get(d) for d in plot_dates]

        per_horizon = {}
        stratified_by_horizon = {}
        for h in horizons:
            persist_vals = []
            dash_vals = []
            vqs_vals = []
            rs_vals = []
            pace_vals = []
            dsupply_vals = []
            ctx_vals = []
            hybrid_vals = []
            dispatch_vals = []
            ablation_vals = []
            gbm_vals = []
            gbm_direct_vals = []
            gbm_gated_vals = []
            persist_list = []
            dash_list = []
            vqs_list = []
            rs_list = []
            pace_list = []
            dsupply_list = []
            ctx_list = []
            hybrid_list = []
            dispatch_list = []
            ablation_list = []
            gbm_list = []
            gbm_direct_list = []
            gbm_gated_list = []
            momentum3m_vals = []
            seasonal_med_vals = []
            poly_trend_vals = []
            momentum3m_list = []
            seasonal_med_list = []
            poly_trend_list = []

            for d in plot_dates:
                persist = forecast_persistence(visa_class, country, d, h)
                dash = forecast_dashboard(visa_class, country, d, h)
                kd = d - relativedelta(months=h)

                if h == 1 and d in stored_vqs:
                    vqs = stored_vqs[d]
                else:
                    vqs = vqs_cache.get((kd, d.year, d.month))

                rs = rs_cache.get((kd, d.year, d.month))
                pace = forecast_pace(visa_class, country, d, h)
                dsupply = forecast_demand_supply(visa_class, country, d, h)
                ctx = ctx_cache.get((kd, h))

                # Hybrid: RS for EB-1, VQS for EB-2/3 at 1m/3m, Pace for EB-2/3 at 6m+
                if label in _EB1_LABELS:
                    hybrid = rs
                elif h >= 6:
                    hybrid = pace
                else:
                    hybrid = vqs

                abl = ablation_cache.get((kd, d.year, d.month)) if ablate else None

                gbm_pred = gbm_cache.get((kd, h)) if gbm else None
                gbm_direct_pred = gbm_direct_cache.get((kd, h)) if gbm else None
                gbm_gated_pred = gbm_gated_cache.get((kd, h)) if gbm else None

                # Dispatch: mirrors publish_predictions.py production logic exactly.
                # NOTE: Dispatch is only fully accurate when --gbm is used (GBM Gated
                # is required for India EB-1/China EB-3 at 6m+ and 5 series at 12m).
                # Without --gbm, gbm_gated_pred is None and those series fall through to pace.
                _dispatch_key = (country, visa_class)
                if (_dispatch_key == _DISP_CHINA_EB1 and h < 12) or (
                    _dispatch_key == _DISP_INDIA_EB1 and h < 6
                ) or h == 1:
                    dispatch = rs
                elif h >= 12 and _dispatch_key in _DISP_GBM_GATED_12M:
                    dispatch = gbm_gated_pred
                elif h >= 12 and _dispatch_key in _DISP_PACE_12M:
                    dispatch = pace
                elif h >= 12 and _dispatch_key in _DISP_PERSISTENCE_12M:
                    dispatch = persist
                elif _dispatch_key in _DISP_GBM_GATED_6M and h >= 6:
                    dispatch = gbm_gated_pred
                elif _dispatch_key in _DISP_PACE_6M and h >= 6:
                    dispatch = pace
                else:
                    dispatch = vqs
                mom3m = forecast_momentum_3m(visa_class, country, d, h)
                seas_med = forecast_seasonal_median(visa_class, country, d, h)
                poly_trend = forecast_polynomial_trend(visa_class, country, d, h)

                persist_vals.append(persist.strftime("%Y-%m-%d") if persist else None)
                dash_vals.append(dash.strftime("%Y-%m-%d") if dash else None)
                vqs_vals.append(vqs.strftime("%Y-%m-%d") if vqs else None)
                rs_vals.append(rs.strftime("%Y-%m-%d") if rs else None)
                pace_vals.append(pace.strftime("%Y-%m-%d") if pace else None)
                dsupply_vals.append(dsupply.strftime("%Y-%m-%d") if dsupply else None)
                ctx_vals.append(ctx.strftime("%Y-%m-%d") if ctx else None)
                hybrid_vals.append(hybrid.strftime("%Y-%m-%d") if hybrid else None)
                dispatch_vals.append(dispatch.strftime("%Y-%m-%d") if dispatch else None)
                ablation_vals.append(abl.strftime("%Y-%m-%d") if abl else None)
                gbm_vals.append(gbm_pred.strftime("%Y-%m-%d") if gbm_pred else None)
                gbm_direct_vals.append(gbm_direct_pred.strftime("%Y-%m-%d") if gbm_direct_pred else None)
                gbm_gated_vals.append(gbm_gated_pred.strftime("%Y-%m-%d") if gbm_gated_pred else None)
                momentum3m_vals.append(mom3m.strftime("%Y-%m-%d") if mom3m else None)
                seasonal_med_vals.append(seas_med.strftime("%Y-%m-%d") if seas_med else None)
                poly_trend_vals.append(poly_trend.strftime("%Y-%m-%d") if poly_trend else None)

                persist_list.append(persist)
                dash_list.append(dash)
                vqs_list.append(vqs)
                rs_list.append(rs)
                pace_list.append(pace)
                dsupply_list.append(dsupply)
                ctx_list.append(ctx)
                hybrid_list.append(hybrid)
                dispatch_list.append(dispatch)
                ablation_list.append(abl)
                gbm_list.append(gbm_pred)
                gbm_direct_list.append(gbm_direct_pred)
                gbm_gated_list.append(gbm_gated_pred)
                momentum3m_list.append(mom3m)
                seasonal_med_list.append(seas_med)
                poly_trend_list.append(poly_trend)

            # Classify each data point by regime, FY phase, movement magnitude
            point_meta = []
            regime_labels = []
            fy_phase_labels = []
            for i, d in enumerate(plot_dates):
                prev_actual = actual_list[i - 1] if i > 0 else None
                meta = classify_data_point(
                    visa_class, country, d, h, actual_list[i], prev_actual,
                )
                point_meta.append(meta)
                regime_labels.append(meta["regime"])
                fy_phase_labels.append(meta["fy_phase"])

            h_data = {
                "persist": persist_vals,
                "dash": dash_vals,
                "vqs": vqs_vals,
                "rs": rs_vals,
                "pace": pace_vals,
                "dsupply": dsupply_vals,
                "ctx": ctx_vals,
                "hybrid": hybrid_vals,
                "dispatch": dispatch_vals,
                "momentum3m": momentum3m_vals,
                "seasonal_med": seasonal_med_vals,
                "poly_trend": poly_trend_vals,
                "regime": regime_labels,
                "fy_phase": fy_phase_labels,
            }
            if ablate:
                h_data["ablation"] = ablation_vals
            if gbm:
                h_data["gbm"] = gbm_vals
                h_data["gbm_direct"] = gbm_direct_vals
                h_data["gbm_gated"] = gbm_gated_vals
            per_horizon[str(h)] = h_data

            # Compute stratified metrics for this horizon
            model_lists = {
                "Persistence": persist_list,
                "Dashboard": dash_list,
                "VQS Ensemble": vqs_list,
                "Regime-Switched": rs_list,
                "Pace": pace_list,
                "Demand-Supply": dsupply_list,
                "Contextual Ensemble": ctx_list,
                "Hybrid": hybrid_list,
                "Dispatch": dispatch_list,
                "3m Momentum": momentum3m_list,
                "Seasonal Median": seasonal_med_list,
                "Poly Trend": poly_trend_list,
            }
            if ablate:
                model_lists["VQS No Cross-Series"] = ablation_list
            if gbm:
                model_lists["GBM"] = gbm_list
                model_lists["GBM Direct"] = gbm_direct_list
                model_lists["GBM Gated"] = gbm_gated_list
            stratified_by_horizon[str(h)] = compute_stratified_metrics(
                plot_dates, actual_list, model_lists, point_meta, error_start,
            )

            # --- diagnostic: show where RS diverges from persistence ---
            if h == 1 and diagnostic:
                rs_better = 0
                rs_worse = 0
                rs_same = 0
                for i, d in enumerate(plot_dates):
                    actual = actual_list[i]
                    p = persist_list[i]
                    r = rs_list[i]
                    if actual and p and r and r != p:
                        p_err = abs((actual - p).days)
                        r_err = abs((actual - r).days)
                        delta = r_err - p_err
                        tag = "WORSE" if delta > 0 else "BETTER"
                        if delta > 0:
                            rs_worse += 1
                        else:
                            rs_better += 1
                        print(
                            f"  {d.strftime('%Y-%m')} actual={actual} "
                            f"persist={p} rs={r} "
                            f"p_err={p_err}d r_err={r_err}d Δ={delta:+d}d {tag}"
                        )
                    elif actual and p and r:
                        rs_same += 1
                total_div = rs_better + rs_worse
                print(
                    f"  --- RS diverges: {total_div}/{rs_same + total_div} months | "
                    f"better={rs_better} worse={rs_worse} same={rs_same}"
                )
            # --- end diagnostic ---

            model_eval_pairs = [
                (persist_list, "Persistence"),
                (dash_list, "Dashboard"),
                (vqs_list, "VQS Ensemble"),
                (rs_list, "Regime-Switched"),
                (pace_list, "Pace"),
                (dsupply_list, "Demand-Supply"),
                (ctx_list, "Contextual Ensemble"),
                (hybrid_list, "Hybrid"),
                (dispatch_list, "Dispatch"),
                (momentum3m_list, "3m Momentum"),
                (seasonal_med_list, "Seasonal Median"),
                (poly_trend_list, "Poly Trend"),
            ]
            if ablate:
                model_eval_pairs.append((ablation_list, "VQS No Cross-Series"))
            if gbm:
                model_eval_pairs.append((gbm_list, "GBM"))
                model_eval_pairs.append((gbm_direct_list, "GBM Direct"))
                model_eval_pairs.append((gbm_gated_list, "GBM Gated"))
            for model_list, model_label in model_eval_pairs:
                m = compute_metrics(plot_dates, actual_list, model_list, model_label, error_start)
                m["series"] = label
                m["horizon"] = h
                all_metrics.append(m)

        all_stratified[label] = stratified_by_horizon

        chart_data[label] = {
            "dates": dates_str,
            "actual": actual_vals,
            "horizons": per_horizon,
            "vqs_start": vqs_start.strftime("%Y-%m-%d") if vqs_start else "N/A",
            "stratified": stratified_by_horizon,
        }

        logger.info(f"  {label} done in {time.time() - t0:.1f}s ({len(plot_dates)} points x {len(horizons)} horizons)")

    return chart_data, all_metrics, all_stratified


MODELS = ["Persistence", "Dashboard", "VQS Ensemble", "Regime-Switched", "Pace", "Demand-Supply", "Contextual Ensemble", "Hybrid", "3m Momentum", "Seasonal Median", "Poly Trend"]
MODELS_ABLATE = MODELS + ["VQS No Cross-Series"]
MODELS_GBM = MODELS + ["GBM", "GBM Direct", "GBM Gated", "Dispatch"]

# EB-1 series where Regime-Switched beats VQS Ensemble
_EB1_LABELS = {"India EB-1", "China EB-1"}

# Dispatch constants — mirror publish_predictions.py exactly.
_DISP_CHINA_EB1 = (Country.CHINA.value, "1st")
_DISP_INDIA_EB1 = (Country.INDIA.value, "1st")
_DISP_GBM_GATED_6M = frozenset([
    (Country.INDIA.value, "1st"),
    (Country.CHINA.value, "3rd"),
])
_DISP_PACE_6M = frozenset([
    (Country.INDIA.value, "2nd"),
    (Country.INDIA.value, "3rd"),
    (Country.CHINA.value, "2nd"),
])
_DISP_GBM_GATED_12M = frozenset([
    (Country.CHINA.value, "1st"),
    (Country.CHINA.value, "2nd"),
    (Country.CHINA.value, "3rd"),
    (Country.INDIA.value, "1st"),
    (Country.INDIA.value, "2nd"),
])
_DISP_PACE_12M = frozenset([(Country.INDIA.value, "3rd")])
# Persistence at 12m: reserved for structurally stalled series where Pace
# and GBM both lose to no-change. Currently empty — India EB-3 Pace (490d)
# beats Persistence (524d) per §21 same-window eval.
_DISP_PERSISTENCE_12M: frozenset = frozenset()


def print_metrics_table(metrics, horizons):
    """Print a comparison table of model metrics per horizon."""
    series_set = sorted(set(m["series"] for m in metrics))
    # Include ablation model if present in metrics
    if any(m["label"] == "GBM" for m in metrics):
        models = MODELS_GBM
    elif any(m["label"] == "VQS No Cross-Series" for m in metrics):
        models = MODELS_ABLATE
    else:
        models = MODELS

    for h in horizons:
        print("\n" + "=" * 110)
        print(f"Model Comparison ({h}-month horizon, {ACTION_TYPE})")
        print("=" * 110)
        print(f"\n{'Series':<20} {'Model':<22} {'MAE (days)':<12} {'Dir Acc %':<12} {'CondDir%':<10} {'MovPrec%':<10} {'MovRec%':<9} {'BigMove%':<10} {'RegiChg%':<10}")
        print("-" * 115)

        for series in series_set:
            for model in models:
                m = next((x for x in metrics if x["series"] == series and x["label"] == model and x["horizon"] == h), None)
                if m:
                    mae = f"{m['mae']}" if m["mae"] is not None else "N/A"
                    da = f"{m['direction_acc']}" if m["direction_acc"] is not None else "N/A"
                    cda = f"{m.get('cond_direction_acc', 'N/A')}" if m.get("cond_direction_acc") is not None else "N/A"
                    mp = f"{m.get('movement_precision', 'N/A')}" if m.get("movement_precision") is not None else "N/A"
                    mr = f"{m.get('movement_recall', 'N/A')}" if m.get("movement_recall") is not None else "N/A"
                    bm = f"{m.get('big_move_capture_rate', 'N/A')}" if m.get("big_move_capture_rate") is not None else "N/A"
                    rc = f"{m.get('regime_change_detection_acc', 'N/A')}" if m.get("regime_change_detection_acc") is not None else "N/A"
                    print(f"{series:<20} {model:<22} {mae:<12} {da:<12} {cda:<10} {mp:<10} {mr:<9} {bm:<10} {rc:<10}")
            print()

        print("--- AGGREGATE ---")
        for model in models:
            model_metrics = [m for m in metrics if m["label"] == model and m["horizon"] == h and m["mae"] is not None]
            if model_metrics:
                avg_mae = sum(m["mae"] for m in model_metrics) / len(model_metrics)
                total_cumul = sum(m["cumulative"] for m in model_metrics)
                dir_accs = [m["direction_acc"] for m in model_metrics if m["direction_acc"] is not None]
                avg_dir = sum(dir_accs) / len(dir_accs) if dir_accs else None
                bm_rates = [m.get("big_move_capture_rate") for m in model_metrics if m.get("big_move_capture_rate") is not None]
                avg_bm = sum(bm_rates) / len(bm_rates) if bm_rates else None
                print(
                    f"{'ALL':<20} {model:<22} {avg_mae:<12.1f} "
                    f"{f'{avg_dir:.1f}' if avg_dir else 'N/A':<12} "
                    f"{f'{avg_bm:.1f}%' if avg_bm is not None else 'N/A':<10} "
                    f"{total_cumul:,}"
                )

        for model_name in ["VQS Ensemble", "Regime-Switched", "Pace", "Demand-Supply", "Contextual Ensemble", "Hybrid", "Dispatch"]:
            m_wins = 0
            p_wins = 0
            for series in series_set:
                v = next((x for x in metrics if x["series"] == series and x["label"] == model_name and x["horizon"] == h), None)
                p = next((x for x in metrics if x["series"] == series and x["label"] == "Persistence" and x["horizon"] == h), None)
                if v and p and v["mae"] is not None and p["mae"] is not None:
                    if v["mae"] < p["mae"]:
                        m_wins += 1
                    elif p["mae"] < v["mae"]:
                        p_wins += 1
            total = m_wins + p_wins
            if total > 0:
                print(f"{model_name} beats persistence: {m_wins}/{total} series ({100*m_wins/total:.0f}%)")


# Key series for Section 0 success criteria
_KEY_SERIES = {"India EB-2", "India EB-3", "China EB-2", "China EB-3"}


def print_per_series_summary(metrics, horizons):
    """Print Section 0 conditional metrics per key series (EB-2/3 India/China).

    Shows the metrics that matter for beating persistence: conditional direction
    accuracy (when actual moves > 30d), movement detection precision/recall.
    """
    print("\n" + "=" * 110)
    print("SECTION 0 SUMMARY: Conditional Metrics (EB-2/3 India/China focus)")
    print("Targets: CondDir >= 65%, MovPrec >= 50%, MovRec >= 40%, 6m MAE <= 190d")
    print("=" * 110)

    all_series = sorted(set(m["series"] for m in metrics))

    all_models = MODELS_GBM if any(m["label"] == "GBM" for m in metrics) else MODELS

    for h in horizons:
        print(f"\n--- {h}-month horizon ---")
        print(f"{'Series':<20} {'Model':<22} {'MAE':<8} {'CondDir%':<10} {'MovPrec%':<10} {'MovRec%':<9} {'MovF1%':<8} {'Beat Persist?'}")
        print("-" * 105)

        for series in all_series:
            is_key = series in _KEY_SERIES
            persistence_m = next((x for x in metrics if x["series"] == series and x["label"] == "Persistence" and x["horizon"] == h), None)
            persist_mae = persistence_m["mae"] if persistence_m else None

            for model in all_models:
                m = next((x for x in metrics if x["series"] == series and x["label"] == model and x["horizon"] == h), None)
                if not m or m["mae"] is None:
                    continue

                mae_s = f"{m['mae']:.1f}"
                cda = m.get("cond_direction_acc")
                mp = m.get("movement_precision")
                mr = m.get("movement_recall")
                cda_s = f"{cda:.1f}%" if cda is not None else "N/A"
                mp_s = f"{mp:.1f}%" if mp is not None else "N/A"
                mr_s = f"{mr:.1f}%" if mr is not None else "N/A"

                f1 = None
                if mp is not None and mr is not None and (mp + mr) > 0:
                    f1 = 2 * mp * mr / (mp + mr)
                f1_s = f"{f1:.1f}%" if f1 is not None else "N/A"

                beats = ""
                if persist_mae is not None and m["mae"] is not None:
                    if m["mae"] < persist_mae:
                        beats = f"YES ({persist_mae - m['mae']:.1f}d)"
                    elif model == "Persistence":
                        beats = "(baseline)"
                    else:
                        beats = f"no ({m['mae'] - persist_mae:.1f}d worse)"

                prefix = "* " if is_key and model != "Persistence" else "  "
                print(f"{prefix}{series:<18} {model:<22} {mae_s:<8} {cda_s:<10} {mp_s:<10} {mr_s:<9} {f1_s:<8} {beats}")
            print()


def print_composite_table(metrics: list[dict], horizons: list[int]) -> None:
    """Print a composite score table across all models.

    Computes composite = (sum_h hw_h * avg_MAE_h) / (sum_h hw_h) using
    MetricConfig default horizon weights. This is the same formula shown in
    the blog comparison table, making the numbers reproducible and not
    reliant on hand-transcription.

    Only horizons present in MetricConfig.horizon_weights are included; if
    a model has no predictions for a given horizon (all None), that horizon
    is excluded from its composite (with a note).
    """
    cfg = MetricConfig.defaults()
    hw = cfg.horizon_weights

    # Collect aggregate (cross-series average) MAE per model per horizon
    # using the same arithmetic average as print_metrics_table AGGREGATE rows.
    model_set: list[str]
    if any(m["label"] == "GBM" for m in metrics):
        model_set = MODELS_GBM
    elif any(m["label"] == "VQS No Cross-Series" for m in metrics):
        model_set = MODELS_ABLATE
    else:
        model_set = MODELS

    # horizon_mae[model][h] = average MAE across series for that horizon
    horizon_mae: dict[str, dict[int, float]] = {}
    for model in model_set:
        horizon_mae[model] = {}
        for h in horizons:
            h_rows = [m for m in metrics if m["label"] == model and m["horizon"] == h and m["mae"] is not None]
            if h_rows:
                horizon_mae[model][h] = sum(m["mae"] for m in h_rows) / len(h_rows)

    print("\n" + "=" * 100)
    print(f"COMPOSITE SCORE TABLE  (weights: {', '.join(f'{h}m×{hw.get(h, 0):.3f}' for h in sorted(hw))})")
    print(f"Composite = weighted avg of per-horizon MAE  |  lower is better  |  horizons evaluated: {horizons}")
    print("=" * 100)
    print(f"{'Model':<24} {'Composite':>10}  {'vs Persist':>10}  " + "  ".join(f"{'MAE '+str(h)+'m':>8}" for h in horizons))
    print("-" * 100)

    # Compute persistence composite first for delta column
    persist_composite: float | None = None
    if "Persistence" in horizon_mae:
        p_maes = horizon_mae["Persistence"]
        numerator = sum(hw.get(h, 0) * p_maes[h] for h in p_maes if hw.get(h, 0) > 0)
        denominator = sum(hw.get(h, 0) for h in p_maes if hw.get(h, 0) > 0)
        if denominator > 0:
            persist_composite = numerator / denominator

    for model in model_set:
        maes = horizon_mae[model]
        weighted_horizons = [h for h in maes if hw.get(h, 0) > 0]
        if not weighted_horizons:
            continue
        numerator = sum(hw[h] * maes[h] for h in weighted_horizons)
        denominator = sum(hw[h] for h in weighted_horizons)
        composite = numerator / denominator if denominator > 0 else None

        missing = [h for h in horizons if h in hw and h not in maes]
        note = f" (missing: {missing})" if missing else ""

        vs_str = ""
        if composite is not None and persist_composite is not None and model != "Persistence":
            diff = composite - persist_composite
            vs_str = f"{diff:+.1f}d"

        per_h = "  ".join(
            f"{maes[h]:>8.1f}" if h in maes else f"{'N/A':>8}"
            for h in horizons
        )

        composite_str = f"{composite:.1f}d" if composite is not None else "N/A"
        print(f"{model + note:<24} {composite_str:>10}  {vs_str:>10}  {per_h}")

    print()


def generate_html(chart_data, horizons, output_path):
    """Generate interactive Plotly HTML visualization with stratified metrics panel."""
    json_data = json.dumps(chart_data)
    default_series = list(chart_data.keys())[0] if chart_data else ""
    default_horizon = str(horizons[0])
    horizon_options = "".join(
        f'<option value="{h}"{" selected" if h == horizons[0] else ""}>{h} month{"s" if h != 1 else ""}</option>'
        for h in horizons
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>VQS Model Evaluation</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; max-width: 1400px; margin: 0 auto; }}
        .controls {{ margin-bottom: 20px; display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }}
        select {{ padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; }}
        .stats {{
            margin-top: 10px; padding: 10px;
            background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px;
            display: flex; gap: 20px; font-weight: bold; flex-wrap: wrap;
        }}
        .strat-panel {{
            margin-top: 20px; padding: 15px;
            background: #fff; border: 1px solid #dee2e6; border-radius: 6px;
        }}
        .strat-panel h3 {{ margin: 0 0 12px 0; font-size: 16px; color: #333; }}
        .strat-tabs {{ display: flex; gap: 8px; margin-bottom: 12px; }}
        .strat-tabs button {{
            padding: 6px 14px; border: 1px solid #ccc; border-radius: 4px;
            background: #f8f9fa; cursor: pointer; font-size: 13px;
        }}
        .strat-tabs button.active {{ background: #0d6efd; color: #fff; border-color: #0d6efd; }}
        table.strat {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
        table.strat th, table.strat td {{ padding: 6px 10px; text-align: right; border-bottom: 1px solid #eee; }}
        table.strat th {{ background: #f8f9fa; font-weight: 600; text-align: left; }}
        table.strat td:first-child {{ text-align: left; font-weight: 500; }}
        table.strat tr.bucket-header td {{ background: #f0f4f8; font-weight: 600; text-align: left; border-top: 2px solid #dee2e6; }}
        .win {{ color: #198754; }}
        .lose {{ color: #dc3545; }}
        .neutral {{ color: #6c757d; }}
    </style>
</head>
<body>
    <h1>VQS Model Evaluation</h1>
    <div class="controls">
        <div>
            <label for="sel">Series:</label>
            <select id="sel" onchange="updateAll()">
                {"".join(f'<option value="{k}">{k}</option>' for k in chart_data.keys())}
            </select>
        </div>
        <div>
            <label for="horizon">Horizon:</label>
            <select id="horizon" onchange="updateAll()">
                {horizon_options}
            </select>
        </div>
    </div>
    <div id="note" style="color:#666;margin-top:5px"></div>
    <div id="stats" class="stats"></div>
    <div id="chart" style="width:100%;height:900px;"></div>
    <div class="strat-panel">
        <h3>Stratified Accuracy Breakdown</h3>
        <div class="strat-tabs">
            <button class="active" onclick="switchTab(this,'regime')">By Regime</button>
            <button onclick="switchTab(this,'fy_phase')">By FY Phase</button>
            <button onclick="switchTab(this,'move_mag')">By Move Size</button>
        </div>
        <div id="stratTable"></div>
    </div>
    <script>
        const D = {json_data};
        const ERR_START = new Date("2017-07-01");
        let currentDim = 'regime';

        function cumErr(dates, actuals, preds) {{
            let c = [], s = 0;
            for (let i = 0; i < dates.length; i++) {{
                let d = new Date(dates[i]);
                if (d >= ERR_START && actuals[i] && preds[i]) {{
                    s += Math.abs(Math.ceil((new Date(preds[i]) - new Date(actuals[i])) / 86400000));
                }}
                c.push(s);
            }}
            return c;
        }}

        function switchTab(btn, dim) {{
            currentDim = dim;
            document.querySelectorAll('.strat-tabs button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateStratTable();
        }}

        function updateStratTable() {{
            const s = document.getElementById('sel').value;
            const h = document.getElementById('horizon').value;
            const d = D[s];
            if (!d.stratified || !d.stratified[h] || !d.stratified[h][currentDim]) {{
                document.getElementById('stratTable').innerHTML = '<p style="color:#666">No stratified data available</p>';
                return;
            }}

            const dimData = d.stratified[h][currentDim];
            const hasGbm = Object.values(dimData).some(bm => 'GBM' in bm);
            const models = hasGbm
                ? ['Persistence', 'VQS Ensemble', 'Regime-Switched', 'Pace', 'Demand-Supply', 'Contextual Ensemble', 'Hybrid', '3m Momentum', 'Seasonal Median', 'Poly Trend', 'GBM', 'GBM Direct', 'GBM Gated']
                : ['Persistence', 'VQS Ensemble', 'Regime-Switched', 'Pace', 'Demand-Supply', 'Contextual Ensemble', 'Hybrid', '3m Momentum', 'Seasonal Median', 'Poly Trend'];
            const dimLabels = {{
                'regime': {{'advancing':'Advancing','stalled':'Stalled','retrogressing':'Retrogressing','recovering':'Recovering','volatile':'Volatile'}},
                'fy_phase': {{'fy_reset':'FY Reset (Oct)','conservative':'Conservative (Nov-Mar)','acceleration':'Acceleration (Apr-Jun)','end_of_fy':'End of FY (Jul-Sep)','normal':'Normal'}},
                'move_mag': {{'big':'Big (>90d)','medium':'Medium (30-90d)','small':'Small (1-30d)','none':'No Change (0d)'}},
            }};
            const labels = dimLabels[currentDim] || {{}};

            let html = '<table class="strat"><tr><th>Bucket</th><th>Model</th><th>MAE (d)</th><th>Dir Acc</th><th>vs Persist</th><th>N</th></tr>';

            const buckets = Object.keys(dimData).sort();
            for (const bk of buckets) {{
                const bm = dimData[bk];
                const displayLabel = labels[bk] || bk;
                html += `<tr class="bucket-header"><td colspan="6">${{displayLabel}}</td></tr>`;
                for (const model of models) {{
                    const m = bm[model];
                    if (!m || m.count === 0) continue;
                    const mae = m.mae !== null ? m.mae.toFixed(1) : '—';
                    const da = m.dir_acc !== null ? m.dir_acc.toFixed(1) + '%' : '—';
                    let wr = '—';
                    let wrClass = 'neutral';
                    if (model !== 'Persistence' && m.win_rate !== null) {{
                        wr = m.win_rate.toFixed(1) + '%';
                        wrClass = m.win_rate > 50 ? 'win' : m.win_rate < 50 ? 'lose' : 'neutral';
                    }}
                    html += `<tr><td>${{model === 'Persistence' ? '' : ''}}</td><td style="text-align:left">${{model}}</td><td>${{mae}}</td><td>${{da}}</td><td class="${{wrClass}}">${{wr}}</td><td>${{m.count}}</td></tr>`;
                }}
            }}
            html += '</table>';
            document.getElementById('stratTable').innerHTML = html;
        }}

        function updateChart() {{
            const s = document.getElementById('sel').value;
            const h = document.getElementById('horizon').value;
            const d = D[s];
            const hd = d.horizons[h];
            document.getElementById('note').innerText = "VQS data from: " + d.vqs_start + " | Horizon: " + h + " month(s) ahead";

            const eP = cumErr(d.dates, d.actual, hd.persist);
            const eD = cumErr(d.dates, d.actual, hd.dash);
            const eV = cumErr(d.dates, d.actual, hd.vqs);
            const eR = cumErr(d.dates, d.actual, hd.rs);
            const eC = cumErr(d.dates, d.actual, hd.ctx);
            const ePace = cumErr(d.dates, d.actual, hd.pace);
            const eDS = cumErr(d.dates, d.actual, hd.dsupply);
            const eH = hd.hybrid ? cumErr(d.dates, d.actual, hd.hybrid) : [];
            const eMom = hd.momentum3m ? cumErr(d.dates, d.actual, hd.momentum3m) : [];
            const eSeas = hd.seasonal_med ? cumErr(d.dates, d.actual, hd.seasonal_med) : [];
            const ePoly = hd.poly_trend ? cumErr(d.dates, d.actual, hd.poly_trend) : [];

            document.getElementById('stats').innerHTML = [
                '<span style="color:green">Persistence: ' + (eP[eP.length-1]||0).toLocaleString() + 'd</span>',
                '<span style="color:blue">Dashboard: ' + (eD[eD.length-1]||0).toLocaleString() + 'd</span>',
                '<span style="color:purple">VQS: ' + (eV[eV.length-1]||0).toLocaleString() + 'd</span>',
                '<span style="color:red">Regime-SW: ' + (eR[eR.length-1]||0).toLocaleString() + 'd</span>',
                '<span style="color:orange">Pace: ' + (ePace[ePace.length-1]||0).toLocaleString() + 'd</span>',
                '<span style="color:teal">D-S: ' + (eDS[eDS.length-1]||0).toLocaleString() + 'd</span>',
                eH.length ? '<span style="color:#c0392b;font-weight:bold">Hybrid: ' + (eH[eH.length-1]||0).toLocaleString() + 'd</span>' : '',
                eMom.length ? '<span style="color:#8b5cf6">3m Mom: ' + (eMom[eMom.length-1]||0).toLocaleString() + 'd</span>' : '',
                eSeas.length ? '<span style="color:#0ea5e9">SeasonalMed: ' + (eSeas[eSeas.length-1]||0).toLocaleString() + 'd</span>' : '',
                ePoly.length ? '<span style="color:#f59e0b">PolyTrend: ' + (ePoly[ePoly.length-1]||0).toLocaleString() + 'd</span>' : '',
            ].filter(Boolean).join('');

            const traces = [
                {{x:d.dates, y:d.actual, mode:'lines+markers', name:'Actual', line:{{color:'black',width:3}}, marker:{{size:4}}, legendgroup:'a'}},
                {{x:d.dates, y:hd.persist, mode:'lines', name:'Persistence ('+h+'m)', line:{{color:'green',width:1,dash:'dot'}}, legendgroup:'p'}},
                {{x:d.dates, y:hd.dash, mode:'lines', name:'Dashboard ('+h+'m)', line:{{color:'blue',width:2,dash:'dash'}}, legendgroup:'d'}},
                {{x:d.dates, y:hd.vqs, mode:'lines', name:'VQS Ensemble ('+h+'m)', line:{{color:'purple',width:3}}, legendgroup:'v'}},
                {{x:d.dates, y:hd.rs, mode:'lines', name:'Regime-Switched ('+h+'m)', line:{{color:'red',width:3}}, legendgroup:'r'}},
                {{x:d.dates, y:hd.pace, mode:'lines', name:'Pace ('+h+'m)', line:{{color:'orange',width:2,dash:'dashdot'}}, legendgroup:'pc'}},
                {{x:d.dates, y:hd.dsupply, mode:'lines', name:'Demand-Supply ('+h+'m)', line:{{color:'teal',width:2,dash:'longdash'}}, legendgroup:'ds'}},
                ...(hd.hybrid ? [{{x:d.dates, y:hd.hybrid, mode:'lines', name:'Hybrid ('+h+'m)', line:{{color:'#c0392b',width:3,dash:'solid'}}, legendgroup:'hy'}}] : []),
                ...(hd.momentum3m ? [{{x:d.dates, y:hd.momentum3m, mode:'lines', name:'3m Momentum ('+h+'m)', line:{{color:'#8b5cf6',width:1.5,dash:'dash'}}, legendgroup:'mom', visible:'legendonly'}}] : []),
                ...(hd.seasonal_med ? [{{x:d.dates, y:hd.seasonal_med, mode:'lines', name:'Seasonal Med ('+h+'m)', line:{{color:'#0ea5e9',width:1.5,dash:'dot'}}, legendgroup:'seas', visible:'legendonly'}}] : []),
                ...(hd.poly_trend ? [{{x:d.dates, y:hd.poly_trend, mode:'lines', name:'Poly Trend ('+h+'m)', line:{{color:'#f59e0b',width:1.5,dash:'dashdot'}}, legendgroup:'poly', visible:'legendonly'}}] : []),
                {{x:d.dates, y:eP, mode:'lines', name:'Err: Persist', line:{{color:'green',width:1,dash:'dot'}}, xaxis:'x', yaxis:'y2', legendgroup:'p', showlegend:false}},
                {{x:d.dates, y:eD, mode:'lines', name:'Err: Dashboard', line:{{color:'blue',width:2,dash:'dash'}}, xaxis:'x', yaxis:'y2', legendgroup:'d', showlegend:false}},
                {{x:d.dates, y:eV, mode:'lines', name:'Err: VQS', line:{{color:'purple',width:2}}, xaxis:'x', yaxis:'y2', legendgroup:'v', showlegend:false}},
                {{x:d.dates, y:eR, mode:'lines', name:'Err: Regime-SW', line:{{color:'red',width:2}}, xaxis:'x', yaxis:'y2', legendgroup:'r', showlegend:false}},
                {{x:d.dates, y:ePace, mode:'lines', name:'Err: Pace', line:{{color:'orange',width:1,dash:'dashdot'}}, xaxis:'x', yaxis:'y2', legendgroup:'pc', showlegend:false}},
                {{x:d.dates, y:eDS, mode:'lines', name:'Err: D-S', line:{{color:'teal',width:1,dash:'longdash'}}, xaxis:'x', yaxis:'y2', legendgroup:'ds', showlegend:false}},
                ...(eH.length ? [{{x:d.dates, y:eH, mode:'lines', name:'Err: Hybrid', line:{{color:'#c0392b',width:2}}, xaxis:'x', yaxis:'y2', legendgroup:'hy', showlegend:false}}] : []),
                ...(eMom.length ? [{{x:d.dates, y:eMom, mode:'lines', name:'Err: 3m Mom', line:{{color:'#8b5cf6',width:1}}, xaxis:'x', yaxis:'y2', legendgroup:'mom', showlegend:false}}] : []),
                ...(eSeas.length ? [{{x:d.dates, y:eSeas, mode:'lines', name:'Err: SeasonalMed', line:{{color:'#0ea5e9',width:1}}, xaxis:'x', yaxis:'y2', legendgroup:'seas', showlegend:false}}] : []),
                ...(ePoly.length ? [{{x:d.dates, y:ePoly, mode:'lines', name:'Err: PolyTrend', line:{{color:'#f59e0b',width:1}}, xaxis:'x', yaxis:'y2', legendgroup:'poly', showlegend:false}}] : []),
            ];

            Plotly.newPlot('chart', traces, {{
                title: s + ' \\u2014 ' + h + '-Month Forecast Accuracy',
                grid: {{rows:2, columns:1, pattern:'independent', roworder:'top to bottom'}},
                xaxis: {{title:'Bulletin Date'}},
                yaxis: {{title:'Cutoff Date', domain:[0.55,1]}},
                yaxis2: {{title:'Cumulative Error (Days)', domain:[0,0.45]}},
                template: 'plotly_white',
                hovermode: 'x unified',
                height: 900,
                legend: {{tracegroupgap:0}},
            }});
        }}

        function updateAll() {{
            updateChart();
            updateStratTable();
        }}

        document.getElementById('sel').value = "{default_series}";
        document.getElementById('horizon').value = "{default_horizon}";
        updateAll();
    </script>
</body>
</html>"""
    with open(output_path, "w") as f:
        f.write(html)
    logger.info(f"Visualization saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="VQS Model Evaluation")
    parser.add_argument("--start", type=str, default="2016-01-01")
    parser.add_argument("--end", type=str, default="2026-03-01")
    parser.add_argument("--series", type=str, default=None, help="Filter to one series label")
    parser.add_argument("--quick", action="store_true", help="Evaluate every 3rd bulletin")
    parser.add_argument("--horizons", type=str, default="1,3,6", help="Comma-separated months ahead (e.g. 1,3,6,12)")
    parser.add_argument("--output", type=str, default=None, help="HTML output path")
    parser.add_argument("--diagnostic", action="store_true", help="Print per-month RS vs persistence divergences")
    parser.add_argument("--ablate", action="store_true", help="Compare VQS with vs without cross-series/GBM experts")
    parser.add_argument("--per-series-summary", action="store_true", help="Print Section 0 conditional metrics per key series")
    parser.add_argument("--gbm", action="store_true", help="Include GBM standalone, GBM Direct, and GBM Gated models (slower)")
    parser.add_argument("--gate-threshold", type=float, default=_GBM_DEFAULT_GATE_THRESHOLD,
                        help=f"GBM Gated gate threshold (default: {_GBM_DEFAULT_GATE_THRESHOLD}). "
                             "Used for gate sweep experiments.")
    parser.add_argument(
        "--ablate-group", type=str, default=None,
        choices=list(_GBM_FEATURE_GROUPS),
        help="Zero out a named feature group at GBM inference (and retrain) to measure "
             "its contribution. Valid groups: velocity, seasonality, macro, demand_drop, cross_series. "
             "Requires --gbm.",
    )
    args = parser.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    step = 3 if args.quick else 1
    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    output_path = args.output or os.path.join(
        settings.BASE_DIR, "webapp", "templates", "spaghetti.html"
    )

    chart_data, metrics, stratified = run_evaluation(
        start, end, horizons,
        series_filter=args.series, step=step,
        diagnostic=args.diagnostic, ablate=args.ablate,
        gbm=args.gbm,
        gate_threshold=args.gate_threshold,
        ablate_group=args.ablate_group,
    )
    print_metrics_table(metrics, horizons)
    print_composite_table(metrics, horizons)
    print_stratified_table(stratified, horizons)
    if args.per_series_summary:
        print_per_series_summary(metrics, horizons)
    generate_html(chart_data, horizons, output_path)
    logger.info("View at http://localhost:8000/spaghetti/")


if __name__ == "__main__":
    main()
