"""Conditional FY Transition Model (Tier 2).

Predicts cutoff movements at fiscal year boundaries (Aug, Sep, Oct) using
contextual features: FY utilization rate, backlog depth, cross-series signals,
and recent momentum. Falls back to unconditional seasonal median when features
are unavailable.

This is the "Tier 2" model that replaces the generic solver at FY boundaries.
The solver's Tier 1 (physics + ensemble) handles non-boundary months.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from lib.business.vqs.data_cache import get_cutoff_at_date
from lib.business.vqs.fy_utilization import (
    FYTransition,
    collect_fy_transitions,
    compute_backlog_depth,
    compute_utilization_rate,
    get_fiscal_year,
)
from lib.business.vqs.seasonal_predictor import (
    get_last_N_moves,
    get_seasonal_prediction,
)

logger = logging.getLogger(__name__)


@dataclass
class FYTransitionPrediction:
    """Result from the FY transition model."""
    predicted_cutoff: date | None
    predicted_move_days: int
    method: str
    confidence: str
    unconditional_median: int | None
    diagnostics: dict


# Cross-series signal: which series typically transition first
_SERIES_PRIORITY_ORDER = {
    "1st": 0,
    "2nd": 1,
    "3rd": 2,
}


def _get_cross_series_signal(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
) -> dict:
    """Check if higher-preference series already showed FY transition.

    EB-1 typically moves first, then EB-2, then EB-3. If a higher-preference
    series already showed a big October jump, the current series is likely next.
    """
    current_priority = _SERIES_PRIORITY_ORDER.get(visa_class, 99)
    signals = {}

    for vc, priority in _SERIES_PRIORITY_ORDER.items():
        if priority >= current_priority:
            continue
        moves = get_last_N_moves(vc, country, action_type, knowledge_date, 2)
        if moves:
            signals[vc] = {
                "last_move": moves[0],
                "prior_move": moves[1] if len(moves) > 1 else None,
            }

    return signals


def predict_fy_transition(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    target_month: int,
    facts: list | None = None,
) -> FYTransitionPrediction:
    """Predict cutoff movement at a fiscal year boundary using conditional features.

    This is the main entry point for the Tier 2 model. It:
    1. Collects historical FY transitions for this series
    2. Computes current contextual features (utilization, backlog, cross-series)
    3. Uses weighted nearest-neighbor on historical transitions
    4. Falls back to seasonal median if insufficient data

    Args:
        visa_class: e.g. "2nd"
        country: Country enum value
        action_type: e.g. "filing"
        knowledge_date: Current date (what we know as of)
        target_month: Month we're predicting (8=Aug, 9=Sep, 10=Oct)
        facts: Raw facts for utilization computation (loaded from DB if None)

    Returns:
        FYTransitionPrediction with predicted cutoff and diagnostics.
    """
    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if current_cutoff is None:
        return FYTransitionPrediction(
            predicted_cutoff=None, predicted_move_days=0,
            method="no_current_cutoff", confidence="low",
            unconditional_median=None, diagnostics={},
        )

    # Load facts for utilization computation if not provided
    if facts is None:
        from models.raw_facts import RawFactsLedger
        facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))

    target_year = knowledge_date.year if target_month > knowledge_date.month else knowledge_date.year + 1
    fy_year = get_fiscal_year(date(target_year, target_month, 1))

    # Collect historical transitions (walk-forward: only data before knowledge_date)
    end_year = knowledge_date.year
    transitions = collect_fy_transitions(
        visa_class, country, action_type,
        start_year=2017, end_year=end_year, facts=facts,
    )

    # Compute current features
    current_backlog = compute_backlog_depth(visa_class, country, action_type, knowledge_date)

    util_rates = compute_utilization_rate(
        facts, visa_class, country, knowledge_date, as_of_month=knowledge_date.month,
    )
    current_fy = get_fiscal_year(knowledge_date)
    current_utilization = util_rates.get(current_fy)

    # Cross-series signals
    cross_signals = _get_cross_series_signal(visa_class, country, action_type, knowledge_date)

    # Recent momentum
    recent_moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 3)
    avg_recent_momentum = sum(recent_moves) / len(recent_moves) if recent_moves else None

    # Unconditional seasonal baseline
    unconditional_move = get_seasonal_prediction(
        visa_class, country, action_type, knowledge_date, target_month, min_samples=2,
    )

    # Build prediction based on target month
    if target_month == 10:
        predicted_move, diag = _predict_october(
            transitions, fy_year, current_backlog, current_utilization,
            cross_signals, avg_recent_momentum, unconditional_move,
        )
    elif target_month == 9:
        predicted_move, diag = _predict_september(
            transitions, fy_year, current_backlog, current_utilization,
            avg_recent_momentum, unconditional_move,
        )
    elif target_month == 8:
        predicted_move, diag = _predict_august(
            transitions, fy_year, current_backlog, current_utilization,
            avg_recent_momentum, unconditional_move,
        )
    else:
        predicted_move = unconditional_move or 0
        diag = {"method": "seasonal_fallback"}

    predicted_cutoff = current_cutoff + timedelta(days=predicted_move)

    # Confidence based on data availability
    n_historical = len([t for t in transitions if t.october_jump_days is not None])
    if n_historical >= 5 and current_backlog is not None:
        confidence = "high"
    elif n_historical >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return FYTransitionPrediction(
        predicted_cutoff=predicted_cutoff,
        predicted_move_days=predicted_move,
        method=diag.get("method", "unknown"),
        confidence=confidence,
        unconditional_median=unconditional_move,
        diagnostics={
            **diag,
            "current_backlog": current_backlog,
            "current_utilization": current_utilization,
            "cross_signals": cross_signals,
            "avg_recent_momentum": avg_recent_momentum,
            "n_historical_transitions": n_historical,
        },
    )


def _predict_october(
    transitions: list[FYTransition],
    target_fy: int,
    backlog: int | None,
    utilization: float | None,
    cross_signals: dict,
    momentum: float | None,
    unconditional: int | None,
) -> tuple[int, dict]:
    """October prediction: large forward jumps expected (new FY quota)."""
    train = [t for t in transitions
             if t.fiscal_year != target_fy and t.october_jump_days is not None]

    if not train:
        return unconditional or 0, {"method": "unconditional_fallback", "reason": "no_training_data"}

    jumps = [t.october_jump_days for t in train]
    uncond_med = int(median(jumps))

    # Weighted prediction using available features
    predicted = _weighted_nearest_neighbor(
        train, target_field="october_jump_days",
        current_backlog=backlog, current_utilization=utilization,
    )

    # Cross-series adjustment: if higher-preference already jumped big, scale up
    cross_boost = 0
    for vc, sig in cross_signals.items():
        if sig.get("last_move", 0) > 200:
            cross_boost = int(sig["last_move"] * 0.15)
            break

    predicted += cross_boost

    return predicted, {
        "method": "conditional_october",
        "unconditional_median": uncond_med,
        "raw_conditional": predicted - cross_boost,
        "cross_boost": cross_boost,
        "n_train": len(train),
    }


def _predict_september(
    transitions: list[FYTransition],
    target_fy: int,
    backlog: int | None,
    utilization: float | None,
    momentum: float | None,
    unconditional: int | None,
) -> tuple[int, dict]:
    """September prediction: potential retrogression at end of FY."""
    train = [t for t in transitions
             if t.fiscal_year != target_fy and t.september_move_days is not None]

    if not train:
        return unconditional or 0, {"method": "unconditional_fallback"}

    moves = [t.september_move_days for t in train]
    uncond_med = int(median(moves))

    predicted = _weighted_nearest_neighbor(
        train, target_field="september_move_days",
        current_backlog=backlog, current_utilization=utilization,
    )

    # Momentum adjustment: if recent months show deceleration, more likely to retrogress
    if momentum is not None and momentum < -10:
        predicted = int(predicted * 1.2)

    return predicted, {
        "method": "conditional_september",
        "unconditional_median": uncond_med,
        "momentum_adjusted": momentum is not None and momentum < -10,
        "n_train": len(train),
    }


def _predict_august(
    transitions: list[FYTransition],
    target_fy: int,
    backlog: int | None,
    utilization: float | None,
    momentum: float | None,
    unconditional: int | None,
) -> tuple[int, dict]:
    """August prediction: early end-of-FY pressure may start."""
    train = [t for t in transitions
             if t.fiscal_year != target_fy and t.august_move_days is not None]

    if not train:
        return unconditional or 0, {"method": "unconditional_fallback"}

    moves = [t.august_move_days for t in train]
    uncond_med = int(median(moves))

    predicted = _weighted_nearest_neighbor(
        train, target_field="august_move_days",
        current_backlog=backlog, current_utilization=utilization,
    )

    return predicted, {
        "method": "conditional_august",
        "unconditional_median": uncond_med,
        "n_train": len(train),
    }


def _weighted_nearest_neighbor(
    train: list[FYTransition],
    target_field: str,
    current_backlog: int | None = None,
    current_utilization: float | None = None,
) -> int:
    """Weighted nearest-neighbor prediction on historical transitions.

    Weights each historical transition by feature similarity to current state.
    Falls back to unweighted median if no features available.
    """
    values = [getattr(t, target_field) for t in train if getattr(t, target_field) is not None]
    if not values:
        return 0

    has_backlog = current_backlog is not None and any(t.backlog_depth_days is not None for t in train)
    has_util = current_utilization is not None and any(t.utilization_rate is not None for t in train)

    if not has_backlog and not has_util:
        return int(median(values))

    weighted_sum = 0.0
    weight_total = 0.0

    for t in train:
        val = getattr(t, target_field)
        if val is None:
            continue

        similarity = 1.0

        if has_backlog and t.backlog_depth_days is not None:
            backlog_diff = abs(current_backlog - t.backlog_depth_days) / max(1, current_backlog)
            similarity *= max(0.1, 1.0 - min(1.0, backlog_diff))

        if has_util and t.utilization_rate is not None:
            util_diff = abs(current_utilization - t.utilization_rate)
            similarity *= max(0.1, 1.0 - min(1.0, util_diff * 2.0))

        weighted_sum += val * similarity
        weight_total += similarity

    return int(weighted_sum / weight_total) if weight_total > 0 else int(median(values))
