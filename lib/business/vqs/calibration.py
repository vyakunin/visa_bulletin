"""Calibrated prediction intervals for VQS cutoff date forecasts.

Computes historical error distributions conditioned on (series, regime, horizon)
and uses them to produce calibrated confidence intervals: the range in which the
actual cutoff will fall with ~80% probability.

Design:
- For each (visa_class, country, horizon, regime), collect all historical prediction
  errors (signed: actual - predicted).
- Compute 10th and 90th percentile of errors → 80% coverage interval.
- Apply these historical offsets to the current point prediction.

Usage in solver / publish_predictions:
    from lib.business.vqs.calibration import compute_calibrated_interval
    low, high = compute_calibrated_interval(
        predicted_date, visa_class, country, action_type, knowledge_date, horizon
    )
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Global cache: {action_type -> {(visa_class, country, horizon, regime): signed errors}}.
# Keyed by action_type — filing and final_action have very different error
# distributions, so they must NOT share a cache entry. Rebuilt when the
# knowledge-date month advances.
_error_distribution_cache: dict[str, dict[tuple, list[int]]] = {}
_cache_knowledge_month: tuple[int, int] | None = None


def _get_regime(visa_class: str, country: int, action_type: str, knowledge_date: date) -> str:
    """Get regime string for a series at a knowledge_date."""
    from lib.business.vqs.regime import classify_regime
    from lib.business.vqs.seasonal_predictor import get_last_N_moves

    moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 6)
    if not moves:
        return "stalled"
    return classify_regime(moves).regime.value


def _build_error_distributions(knowledge_date: date, action_type: str = "filing") -> dict[tuple, list[int]]:
    """Build signed error distributions from all stored PredictedCutoff rows.

    For each (visa_class, country, horizon) pair with stored predictions,
    look up the actual cutoff and compute the signed error. Stratify by regime.
    """

    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from lib.business.vqs.regime import classify_regime
    from lib.business.vqs.seasonal_predictor import get_last_N_moves
    from models.vqs import PredictedCutoff

    distributions: dict[tuple, list[int]] = defaultdict(list)

    # Use stored predictions for horizon=1 (most reliable, matches what was actually served)
    stored = list(
        PredictedCutoff.objects.filter(
            action_type=action_type,
            actual_date__isnull=False,
            predicted_date__isnull=False,
        ).select_related("bulletin")
    )

    for row in stored:
        target_month = row.bulletin.target_bulletin_month
        knowledge = row.bulletin.prediction_date
        if not target_month or not knowledge:
            continue
        if knowledge >= knowledge_date:
            continue
        # A3-F7: the stored actual must have been OBSERVABLE at knowledge_date, not
        # merely filled in later. The actual for target_month is known once that
        # month's bulletin publishes; if the target month is on/after knowledge_date
        # it hadn't happened yet, so including its error leaks the future.
        if target_month >= knowledge_date:
            continue

        # Compute horizon (months from prediction_date to target)
        h = (target_month.year - knowledge.year) * 12 + (target_month.month - knowledge.month)
        if h < 1 or h > 12:
            continue

        regime = _get_regime(row.visa_class, row.country, action_type, knowledge)
        signed_error = (row.actual_date - row.predicted_date).days
        key = (row.visa_class, row.country, h, regime)
        distributions[key].append(signed_error)

    # Supplement with backtest-style errors using historical cutoff data
    # For each knowledge_date in history, compute what "best" model would have predicted
    # and what actually happened.
    bulletins = [b for b in get_all_bulletins() if b.publication_date < knowledge_date]

    from lib.business.vqs.expert_pool import expert_seasonal_median

    physics_eligible = [
        ("2nd", 3), ("3rd", 3), ("1st", 3),  # India
        ("2nd", 2), ("3rd", 2), ("1st", 2),  # China
    ]

    for bulletin in bulletins:
        kd = bulletin.publication_date - timedelta(days=1)
        for visa_class, country in physics_eligible:
            current = get_cutoff_at_date(visa_class, country, action_type, kd)
            if not current:
                continue
            # A3-F6: the 1-month actual is THIS bulletin's cutoff (B), not the
            # bulletin AFTER it. The old code used next_b (B+1), so signed_error
            # compared a "predict B" seasonal_median against the B+1 actual — the
            # same off-by-one transition as the GBM label (A3-F1). Because
            # bulletin.pub < knowledge_date, this actual is also always observable.
            actual = get_cutoff_at_date(visa_class, country, action_type, bulletin.publication_date)
            if not actual:
                continue

            # Use seasonal_median as the reference predictor (most stable)
            pred = expert_seasonal_median(visa_class, country, action_type, kd)
            if not pred:
                continue

            moves = get_last_N_moves(visa_class, country, action_type, kd, 6)
            regime = classify_regime(moves).regime.value if moves else "stalled"

            signed_error = (actual - pred).days
            key = (visa_class, country, 1, regime)
            distributions[key].append(signed_error)

    return dict(distributions)


def _get_error_distributions(knowledge_date: date, action_type: str = "filing") -> dict[tuple, list[int]]:
    """Return per-action_type error distributions, rebuilding when the month advances."""
    global _error_distribution_cache, _cache_knowledge_month

    month = (knowledge_date.year, knowledge_date.month)
    if _cache_knowledge_month != month:
        # Knowledge-date month advanced — drop the whole per-action cache.
        _error_distribution_cache = {}
        _cache_knowledge_month = month

    if action_type not in _error_distribution_cache:
        _error_distribution_cache[action_type] = _build_error_distributions(knowledge_date, action_type)

    return _error_distribution_cache[action_type]


def compute_calibrated_interval(
    predicted_date: date,
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    horizon: int = 1,
    coverage: float = 0.80,
) -> tuple[date, date]:
    """Compute a calibrated prediction interval for a point prediction.

    Args:
        predicted_date: The point prediction from the solver.
        visa_class, country, action_type, knowledge_date, horizon: Series context.
        coverage: Target coverage probability (default 0.80 = 80%).

    Returns:
        (lower_bound, upper_bound): Dates such that the actual cutoff falls
        within this range approximately `coverage` of the time.
    """
    regime = _get_regime(visa_class, country, action_type, knowledge_date)

    try:
        distributions = _get_error_distributions(knowledge_date, action_type)
    except Exception as e:
        logger.warning("Could not build error distributions: %s", e)
        # Fallback: symmetric ±90 days for h=1, wider for longer horizons
        spread = 90 * horizon
        return predicted_date - timedelta(days=spread), predicted_date + timedelta(days=spread)

    key = (visa_class, country, horizon, regime)
    errors = distributions.get(key, [])

    # If not enough data for this exact key, relax regime and use all regimes
    if len(errors) < 10:
        any_regime_errors = []
        for k, v in distributions.items():
            if k[0] == visa_class and k[1] == country and k[2] == horizon:
                any_regime_errors.extend(v)
        errors = any_regime_errors

    # Still not enough data → fall back to series-independent defaults
    if len(errors) < 5:
        # Default intervals: ±90d for h=1, scaling with horizon
        spread_days = max(60, 90 * horizon // 2)
        return predicted_date - timedelta(days=spread_days), predicted_date + timedelta(days=spread_days)

    errors_sorted = sorted(errors)
    n = len(errors_sorted)
    tail = (1.0 - coverage) / 2.0
    lo_idx = max(0, int(tail * n))
    hi_idx = min(n - 1, int((1.0 - tail) * n))

    lo_offset = errors_sorted[lo_idx]  # negative = actual below prediction
    hi_offset = errors_sorted[hi_idx]  # positive = actual above prediction

    lower = predicted_date + timedelta(days=lo_offset)
    upper = predicted_date + timedelta(days=hi_offset)

    # Ensure lower <= predicted_date <= upper (widen if needed)
    if lower > predicted_date:
        lower = predicted_date - timedelta(days=30)
    if upper < predicted_date:
        upper = predicted_date + timedelta(days=30)

    return lower, upper


def get_calibration_summary(
    knowledge_date: date,
    action_type: str = "filing",
) -> dict:
    """Return summary statistics for all calibration distributions.

    Useful for diagnosing how well-calibrated intervals are:
    - count: number of historical errors
    - p10, p50, p90: error percentiles (signed, days)
    - iqr: p90 - p10 (total interval width)
    """
    try:
        distributions = _get_error_distributions(knowledge_date, action_type)
    except Exception:
        return {}

    summary = {}
    for (vc, country, h, regime), errors in sorted(distributions.items()):
        if len(errors) < 5:
            continue
        es = sorted(errors)
        n = len(es)
        summary[f"{vc}/{country}/h{h}/{regime}"] = {
            "count": n,
            "p10": es[max(0, int(0.1 * n))],
            "p50": es[n // 2],
            "p90": es[min(n - 1, int(0.9 * n))],
            "iqr": es[min(n - 1, int(0.9 * n))] - es[max(0, int(0.1 * n))],
        }
    return summary
