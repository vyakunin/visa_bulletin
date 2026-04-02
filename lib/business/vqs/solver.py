"""VQS Solver: deterministic simulation engine.

Steps through future months, depleting the virtual queue against supply
to produce cutoff predictions and maturity dates. Includes queue depth
calibration from historical bulletin advancement rates and fiscal-year
retrogression handling.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta

from lib.business.vqs.data_cache import get_cutoff_at_date
from lib.business.vqs.demand import build_virtual_queue_snapshot
from lib.business.vqs.estimators import get_monthly_supply
from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.queue_snapshot import VirtualQueueSnapshot
from lib.business.vqs.regime import (
    classify_regime,
    classify_regime_fy_aware,
    fy_aware_cap_back_days,
    fy_aware_cap_forward_days,
    fy_aware_persistence_weight,
    fy_aware_stickiness_days,
    regime_persistence_weight,
    regime_stickiness_days,
)
from lib.business.vqs.seasonal_predictor import get_last_N_moves
from models.enums.country import Country

logger = logging.getLogger(__name__)

# Minimum I-140 rows for "high" confidence (same visa_class, country).
CONFIDENCE_HIGH_I140_MIN = 10


def _get(row, key, default=None):
    """Get attribute or dict key from a row (model or dict)."""
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def compute_confidence(
    facts: list,
    visa_class: str,
    country: int,
) -> str:
    """
    Compute prediction confidence from I-140 data availability.

    high: at least CONFIDENCE_HIGH_I140_MIN I-140 rows for (visa_class, country), and not EB4.
    medium: some I-140 data but sparse, or EB5.
    low: no I-140 rows (queue from calibration only) or EB4.
    """
    if visa_class == "4th":
        return "low"
    count = 0
    for row in facts:
        if _get(row, "metric") != "i140_receipts":
            continue
        dims = _get(row, "dimensions") or {}
        if dims.get("category") != visa_class:
            continue
        c = dims.get("country")
        if c is not None and c != country:
            continue
        count += 1
    if count >= CONFIDENCE_HIGH_I140_MIN:
        return "high"
    if count >= 1 or visa_class == "5th":
        return "medium"
    return "low"


@dataclass
class SolverResult:
    """Result of one solver step (one month)."""

    month: date
    cutoff_date: date | None
    consumed: int
    confidence_low: date | None = None
    confidence_high: date | None = None


@dataclass
class SolverOutcome:
    """Complete result from predict_next_bulletin_and_maturity."""

    predicted_cutoff: date | None
    metadata: dict
    maturity_month: date | None
    results: list[SolverResult]
    confidence: str


def get_historical_advancement_rate(
    visa_class: str,
    country: int,
    action_type: str,
    as_of: date,
    lookback_months: int | None = None,
    recency_weight: float = 0.0,
) -> float | None:
    """
    Compute average cutoff advancement (days/month) from recent bulletin history.

    Returns None if insufficient data. Counts all moves (forward, backward, stalls).
    EB1 India uses longer lookback (36 months) for smoother rate.

    If recency_weight > 0, blends recent (last 6 months) with full lookback:
        final_rate = recency_weight * recent_rate + (1 - recency_weight) * historical_rate
    This allows the model to detect momentum/trend changes.
    """
    from lib.business.vqs.data_cache import get_cutoffs_up_to

    # EB1 India: longer lookback for smoother historical advancement rate.
    if lookback_months is None:
        lookback_months = (
            36 if (visa_class == "1st" and country == Country.INDIA.value) else 24
        )  # pyright: ignore[reportAttributeAccessIssue]

    # O(log n) via bisect — cache already excludes null cutoff_date
    filtered = get_cutoffs_up_to(visa_class, country, action_type, as_of)

    recent = filtered[-lookback_months:]
    if len(recent) < 6:
        return None

    ordered = sorted(recent, key=lambda x: x.bulletin.publication_date)

    # Compute full historical rate
    total_adv = 0
    count = 0
    for i in range(1, len(ordered)):
        adv = (ordered[i].cutoff_date - ordered[i - 1].cutoff_date).days
        # Count ALL moves: forward, backward (retrogression), and stalls
        total_adv += adv
        count += 1

    if count == 0:
        return None

    historical_rate = total_adv / count

    # If no recency weighting, return historical rate
    if recency_weight <= 0.0 or len(ordered) < 7:
        return historical_rate

    # Compute recent rate (last 6 months)
    recent_window = ordered[-6:]
    recent_adv = 0
    recent_count = 0
    for i in range(1, len(recent_window)):
        adv = (recent_window[i].cutoff_date - recent_window[i - 1].cutoff_date).days
        recent_adv += adv
        recent_count += 1

    if recent_count == 0:
        return historical_rate

    recent_rate = recent_adv / recent_count

    # Blend: higher recency_weight = more responsive to recent trends
    blended_rate = recency_weight * recent_rate + (1 - recency_weight) * historical_rate
    return blended_rate


def calibrate_queue_depth(
    queue: VirtualQueueSnapshot,
    current_cutoff: date,
    knowledge_date: date,
    monthly_supply: int,
    visa_class: str,
    country: int,
    action_type: str,
    meta: "VqsMetaParams | None" = None,
) -> float | None:
    """
    Fill missing demand in the queue using historical cutoff advancement rate.

    Without calibration, the model's queue (from limited I-140 data) may be
    too sparse, causing unrealistically fast cutoff advancement. Historical
    bulletin data tells us how fast the cutoff actually moves, allowing us to
    estimate the real demand density and fill gaps.

    Demand density = monthly_supply / avg_advancement_days_per_month * 30
    (i.e., if supply is 234/mo and cutoff advances 22 days/mo, each month
    of priority dates has ~319 applicants waiting).
    """
    if meta is None:
        from lib.business.vqs.meta_params import VqsMetaParams

        meta = VqsMetaParams.defaults()

    lookback = meta.lookback_months_default
    if visa_class == "1st" and country == Country.INDIA.value:
        lookback = meta.lookback_months_eb1_india

    avg_adv = get_historical_advancement_rate(
        visa_class,
        country,
        action_type,
        knowledge_date,
        lookback_months=lookback,
        recency_weight=meta.advancement_rate_recency_weight,
    )

    # NEW: Fallback to Final Action history for rate estimation if Filing history is sparse
    if (avg_adv is None or avg_adv <= 0) and action_type == "filing":
        avg_adv = get_historical_advancement_rate(
            visa_class,
            country,
            "final_action",
            knowledge_date,
            lookback_months=lookback,
            recency_weight=meta.advancement_rate_recency_weight,
        )

    if avg_adv is None or avg_adv <= 0:
        return avg_adv

    # Demand per month of priority dates implied by historical rate
    # CAP: Never assume demand density lower than supply / 1 month.
    # If the cutoff jumped forward fast, we should still assume a minimum density.
    capped_adv = min(30.4, avg_adv)
    demand_per_month = int(monthly_supply * 30.4 / capped_adv)
    if demand_per_month <= 0:
        return

    # Fill gaps from current_cutoff to knowledge_date
    cursor = date(current_cutoff.year, current_cutoff.month, 1)
    end = date(knowledge_date.year, knowledge_date.month, 1)
    filled = 0
    while cursor <= end:
        existing = queue.get_bucket(cursor)
        if existing < demand_per_month:
            queue.add(cursor, demand_per_month - existing)
            filled += 1
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    if filled > 0:
        # Decrease noise: this log is too chatty for backtests
        # logger.debug(...)
        pass

    return avg_adv


def run_monthly_loop(
    queue: VirtualQueueSnapshot,
    current_cutoff: date,
    monthly_supply: int,
    start_month: date,
    max_months: int = 120,
    attrition_lambda: float = 1.0,
    supply_fn: Callable[[date], int] | None = None,
    retrogression_months: int = 0,
) -> Iterator[SolverResult]:
    """
    Run the monthly simulation loop.

    Yields SolverResult for each month.
    Optional retrogression_months: in October (new FY), move cutoff back
    by this many months to model the typical FY-start retrogression.
    """
    cutoff = current_cutoff
    current = date(start_month.year, start_month.month, 1)
    for _ in range(max_months):
        # Retrogression: at new fiscal year (October), move cutoff backward
        if retrogression_months > 0 and current.month == 10 and cutoff is not None:
            retro_month = cutoff.month - retrogression_months
            retro_year = cutoff.year
            while retro_month <= 0:
                retro_month += 12
                retro_year -= 1
            cutoff = date(retro_year, retro_month, 1)

        supply = supply_fn(current) if supply_fn else monthly_supply
        new_cutoff, consumed = queue.advance_cutoff(cutoff, supply)
        # If queue exhausted, stay at the last valid cutoff instead of jumping to current
        # This prevents confusing spikes in backtests with sparse early data.
        display_cutoff = new_cutoff if new_cutoff is not None else cutoff
        yield SolverResult(month=current, cutoff_date=display_cutoff, consumed=consumed)

        # We continue the loop but keep cutoff at current status if exhausted
        if new_cutoff is None:
            # We are "at the end" of the known queue.
            # In a backtest, this usually means data sparsity.
            # Keep cutoff at the last known point to avoid 'Current' spikes.
            pass
        else:
            cutoff = new_cutoff

        if attrition_lambda < 1.0 and attrition_lambda > 0:
            queue.scale_remaining_by(attrition_lambda)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


# Fallback retrogression months when history has fewer than 3 Sept/Oct transitions.
# IntegerChoices .value is valid at runtime; pyright infers tuple (value, label).
_RETROGRESSING_SERIES = {
    ("2nd", Country.INDIA.value): 3,  # pyright: ignore[reportAttributeAccessIssue]
    ("3rd", Country.INDIA.value): 3,  # pyright: ignore[reportAttributeAccessIssue]
    ("2nd", Country.CHINA.value): 2,  # pyright: ignore[reportAttributeAccessIssue]
    ("3rd", Country.CHINA.value): 2,  # pyright: ignore[reportAttributeAccessIssue]
    ("1st", Country.INDIA.value): 1,  # pyright: ignore[reportAttributeAccessIssue]
    ("1st", Country.CHINA.value): 1,  # pyright: ignore[reportAttributeAccessIssue]
}

MIN_RETROGRESSION_TRANSITIONS = 3


def get_retrogression_months_from_history(
    visa_class: str,
    country: int,
    action_type: str = "final_action",
) -> int | None:
    """
    Compute typical October retrogression (months) from bulletin history.

    For each year, compares cutoff in September bulletin vs October bulletin.
    If October cutoff is earlier (retrogression), computes months backward.
    Returns median of those values, or None if fewer than MIN_RETROGRESSION_TRANSITIONS.
    """
    from models.visa_cutoff_date import VisaCutoffDate

    rows = list(
        VisaCutoffDate.objects.filter(
            visa_category="employment_based",
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            bulletin__publication_date__month__in=(9, 10),
            cutoff_date__isnull=False,
        )
        .select_related("bulletin")
        .order_by("bulletin__publication_date")
    )
    # Group by (year, month) -> cutoff_date
    by_ym: dict[tuple[int, int], date] = {}
    for r in rows:
        pub = r.bulletin.publication_date
        by_ym[(pub.year, pub.month)] = r.cutoff_date

    retro_months_list: list[float] = []
    for (y, m), cutoff in by_ym.items():
        if m != 9:
            continue
        oct_cutoff = by_ym.get((y, 10))
        if oct_cutoff is None:
            continue
        sept_cutoff = cutoff
        if oct_cutoff >= sept_cutoff:
            continue
        # Retrogression: Oct is earlier. Months backward (approximate).
        months_back = (sept_cutoff.year - oct_cutoff.year) * 12 + (
            sept_cutoff.month - oct_cutoff.month
        )
        if months_back > 0:
            retro_months_list.append(months_back)

    if len(retro_months_list) < MIN_RETROGRESSION_TRANSITIONS:
        return None
    return int(round(sum(retro_months_list) / len(retro_months_list)))


def _select_expert_for_regime(
    regime_state: "RegimeState",  # noqa: F821
    visa_class: str,
    country: int,
    target_month: int,
) -> str:
    """Select the best expert based on regime, series, and target month.

    Returns the expert name from expert_pool.ALL_EXPERTS.
    Selection rules: use persistence except when regime clearly indicates
    movement. demand_signal's seasonal filter is too permissive during
    stalled periods (predicts +15d forward from historical median even
    when the series is stalled, adding consistent small errors that
    outweigh the large wins during actual advances).

    Conservative approach: only use non-persistence experts when
    regime shows actual movement. demand_signal is safer than momentum_3m
    because it returns persistence when seasonal doesn't predict forward.
    """
    from lib.business.vqs.regime import Regime

    regime = regime_state.regime

    if regime in (Regime.STALLED, Regime.RETROGRESSING, Regime.VOLATILE):
        return "persistence"

    avg = regime_state.avg_move or 0
    if regime == Regime.ADVANCING and avg >= 15:
        return "demand_signal"

    if regime == Regime.RECOVERING and avg >= 10:
        return "demand_signal"

    return "persistence"


def predict_regime_switched(
    knowledge_date: date,
    visa_class: str,
    country: int,
    action_type: str,
    priority_date: date | None = None,
    facts: list | None = None,
) -> SolverOutcome:
    """Regime-switched expert selector — no dampening stack.

    For each (series, regime), picks the best expert from expert_pool
    and returns its prediction directly. No ensemble, no stickiness,
    no caps, no persistence blending.

    Selection rules from Phase 1 backtest (scripts/vqs/backtest_experts.py).
    """
    from lib.business.vqs.expert_pool import ALL_EXPERTS
    from models.raw_facts import RawFactsLedger

    target_month = (knowledge_date.month % 12) + 1
    moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 6)
    regime_state = classify_regime(moves)

    if facts is None:
        facts = list(
            RawFactsLedger.objects.filter(publication_date__lte=knowledge_date)
        )

    # Non-eligible series (non-retrogressed ROW, Mexico, Philippines): persistence
    PHYSICS_ELIGIBLE_SERIES = {  # noqa: N806
        ("2nd", Country.INDIA.value),
        ("3rd", Country.INDIA.value),
        ("1st", Country.INDIA.value),
        ("2nd", Country.CHINA.value),
        ("3rd", Country.CHINA.value),
        ("1st", Country.CHINA.value),
    }

    current_cutoff = get_cutoff_at_date(
        visa_class, country, action_type, knowledge_date
    )

    if knowledge_date.month == 12:
        first_future = date(knowledge_date.year + 1, 1, 1)
    else:
        first_future = date(knowledge_date.year, knowledge_date.month + 1, 1)

    base_meta = {
        "regime": regime_state.regime.value,
        "regime_confidence": regime_state.confidence,
        "regime_avg_move": regime_state.avg_move,
        "regime_volatility": regime_state.volatility,
        "moves": moves,
        "persistence_weight": 0.0,
        "fy_boundary": False,
    }

    if (visa_class, country) not in PHYSICS_ELIGIBLE_SERIES or visa_class == "4th":
        result = SolverResult(month=first_future, cutoff_date=current_cutoff, consumed=0)
        meta = {**base_meta, "selected_expert": "persistence", "expert_preds": {}}
        return SolverOutcome(current_cutoff, meta, None, [result], "low")

    expert_name = _select_expert_for_regime(
        regime_state, visa_class, country, target_month
    )
    expert_fn = ALL_EXPERTS.get(expert_name)
    if expert_fn is None:
        expert_fn = ALL_EXPERTS["persistence"]
        expert_name = "persistence"

    predicted_cutoff = expert_fn(
        visa_class, country, action_type, knowledge_date, facts=facts
    )


    if predicted_cutoff is None:
        predicted_cutoff = current_cutoff

    # Run all experts for metadata / explainability
    expert_preds = {}
    for name, fn in ALL_EXPERTS.items():
        try:
            p = fn(visa_class, country, action_type, knowledge_date, facts=facts)
            expert_preds[name] = p
        except Exception:
            expert_preds[name] = None

    # Confidence intervals from expert disagreement
    valid_preds = [p for p in expert_preds.values() if p is not None]
    confidence_low = None
    confidence_high = None
    spread_days = 0
    if len(valid_preds) >= 2 and predicted_cutoff:
        min_pred = min(valid_preds)
        max_pred = max(valid_preds)
        spread_days = (max_pred - min_pred).days
        confidence_low = predicted_cutoff - timedelta(days=int(spread_days * 0.3))
        confidence_high = predicted_cutoff + timedelta(days=int(spread_days * 0.7))

    # Build multi-step results.
    # Step 0: use the single-step expert prediction (correct by construction).
    # Steps 1+: chain forward using the expert's trajectory function, but
    # override step 0 with the single-step prediction to avoid mismatch
    # (e.g. demand_signal uses trajectory_seasonal_median which lacks
    # the demand-braking/persistence-fallback logic).
    from lib.business.vqs.expert_pool import ALL_EXPERT_TRAJECTORIES

    results = []
    maturity_month = None
    max_steps = 24
    spread_days_val = spread_days

    traj_fn = ALL_EXPERT_TRAJECTORIES.get(expert_name)
    trajectory_rest: list[date | None] = []
    if traj_fn:
        full_traj = traj_fn(
            visa_class, country, action_type, knowledge_date, max_steps, facts
        )
        trajectory_rest = full_traj[1:] if len(full_traj) > 1 else []

    all_cutoffs = [predicted_cutoff] + list(trajectory_rest)
    for i, cutoff in enumerate(all_cutoffs[:max_steps]):
        if knowledge_date.month + i >= 12:
            step_year = knowledge_date.year + (knowledge_date.month + i) // 12
            step_month = (knowledge_date.month + i) % 12 + 1
        else:
            step_year = knowledge_date.year
            step_month = knowledge_date.month + i + 1
        step_date = date(step_year, step_month, 1)
        ci_low = cutoff - timedelta(days=int(spread_days_val * 0.3)) if cutoff and spread_days_val > 0 else None
        ci_high = cutoff + timedelta(days=int(spread_days_val * 0.7)) if cutoff and spread_days_val > 0 else None
        results.append(SolverResult(
            month=step_date,
            cutoff_date=cutoff,
            consumed=0,
            confidence_low=ci_low,
            confidence_high=ci_high,
        ))
        if (
            priority_date is not None
            and cutoff is not None
            and cutoff >= priority_date
            and maturity_month is None
        ):
            maturity_month = step_date
            break

    confidence = compute_confidence(facts, visa_class, country)

    pace = get_historical_advancement_rate(
        visa_class, country, action_type, knowledge_date
    )

    meta = {
        **base_meta,
        "selected_expert": expert_name,
        "expert_preds": expert_preds,
        "expert_weights": {expert_name: 1.0},
        "pace_days_per_month": pace,
        "confidence_low": confidence_low,
        "confidence_high": confidence_high,
        "fy_boundary_target_month": None,
        "fy_phase": None,
    }

    return SolverOutcome(predicted_cutoff, meta, maturity_month, results, confidence)


def predict_next_bulletin_and_maturity(
    knowledge_date: date,
    visa_class: str,
    country: int,
    action_type: str,
    priority_date: date | None = None,
    monthly_supply: int | None = None,
    facts: list | None = None,
    meta: "VqsMetaParams | None" = None,
    aggregator: "ExpertAggregator | None" = None,  # noqa: F821
    force_physics: bool = False,
    metric_config: "MetricConfig | None" = None,  # noqa: F821
    fy_boundary_aware: bool = False,
) -> SolverOutcome:
    """
    Run VQS solver and return next bulletin cutoff, maturity month, and all step results.

    Args:
        knowledge_date: State of knowledge (only facts with publication_date <= this).
        visa_class: e.g. "2nd" (EB2), "3rd" (EB3).
        country: Country enum value (e.g. Country.INDIA).
        action_type: e.g. "final_action".
        priority_date: If set, maturity is the first month where cutoff >= priority_date.
        monthly_supply: Explicit constant supply per month. If None, uses
            get_monthly_supply() with per-class allocation, seasonality, and spillover.
        facts: Raw facts (RawFactsLedger queryset or list). If None, loads from DB.
        meta: Tuning parameters. If None, uses defaults.
        aggregator: Optional ExpertAggregator instance.
        force_physics: If True, bypasses the ExpertAggregator and forces the Physics Engine.

    Returns:
        SolverOutcome with:
        predicted_cutoff: predicted cutoff for the first future month.
        metadata: dict with regime, expert weights, pace, persistence weight, CI.
        maturity_month: first month (first day) where cutoff >= priority_date, or None.
        results: list of SolverResult for each month (up to maturity or max).
        confidence: "high" | "medium" | "low" from I-140 data availability.
    """
    from lib.business.vqs.meta_params import VqsMetaParams
    from models.raw_facts import RawFactsLedger

    if meta is None:
        meta = VqsMetaParams.defaults()

    # --- REGIME-AWARE PARAMETER ADAPTATION ---
    target_month = (knowledge_date.month % 12) + 1
    moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 6)

    if fy_boundary_aware:
        regime_state = classify_regime_fy_aware(moves, target_month)
        meta = replace(
            meta,
            ensemble_persistence_weight=fy_aware_persistence_weight(regime_state),
            stickiness_days=fy_aware_stickiness_days(regime_state),
            cap_forward_days=fy_aware_cap_forward_days(regime_state, meta.cap_forward_days),
            cap_back_days=fy_aware_cap_back_days(regime_state, meta.cap_back_days),
            ensemble_stickiness_days=0 if target_month in (8, 9, 10) else meta.ensemble_stickiness_days,
        )
    else:
        regime_state = classify_regime(moves)
        meta = replace(
            meta,
            ensemble_persistence_weight=regime_persistence_weight(regime_state),
            stickiness_days=regime_stickiness_days(regime_state),
        )

    fy_boundary = fy_boundary_aware and target_month in (8, 9, 10)
    # ----------------------------------------

    if facts is None:
        facts = list(
            RawFactsLedger.objects.filter(publication_date__lte=knowledge_date)
        )

    # Use meta-param for confidence threshold
    # Note: compute_confidence logic is currently hardcoded to use CONFIDENCE_HIGH_I140_MIN
    # We should update compute_confidence to take threshold, or just use it here if logic moves.
    # For now, let's keep compute_confidence as is but pass the meta value if we refactor it.
    # actually, compute_confidence uses the constant directly. To be clean, let's just
    # re-implement the check here or pass it?
    # Better: Update compute_confidence signature or use the meta value in place.
    # Since compute_confidence is a helper, let's use the meta value to check "high".

    # Re-implementing confidence logic slightly to use meta param:
    confidence = "low"
    if visa_class != "4th":
        count = 0
        for row in facts:
            if _get(row, "metric") != "i140_receipts":
                continue
            dims = _get(row, "dimensions") or {}
            if dims.get("category") != visa_class:
                continue
            c = dims.get("country")
            if c is not None and c != country:
                continue
            count += 1

        if count >= meta.confidence_high_i140_min:
            confidence = "high"
        elif count >= 1 or visa_class == "5th":
            confidence = "medium"

    # Fix 1: Exclude EB4 from solver (persistence is better)
    if visa_class == "4th":
        current_cutoff = get_cutoff_at_date(
            visa_class, country, action_type, knowledge_date
        )
        eb4_meta = {
            "regime": regime_state.regime.value,
            "regime_confidence": regime_state.confidence,
            "regime_avg_move": regime_state.avg_move,
            "regime_volatility": regime_state.volatility,
            "pace_days_per_month": None,
            "persistence_weight": 1.0,
            "expert_weights": {"persistence": 1.0},
            "expert_preds": {},
            "confidence_low": None,
            "confidence_high": None,
            "moves": moves,
        }
        eb4_maturity = None
        if priority_date is not None and current_cutoff is not None and current_cutoff >= priority_date:
            eb4_maturity = date(knowledge_date.year, knowledge_date.month, 1)
        return SolverOutcome(current_cutoff, eb4_meta, eb4_maturity, [], "low")

    # PHASE 3 IMPROVEMENT: Confidence Gate
    # Only run physics for series where we have signal (Retrogressed).
    # Non-retrogressed series (ROW, Mexico, Philippines) have 0% beat rate with physics
    # and add massive noise. Default them to persistence.
    PHYSICS_ELIGIBLE_SERIES = {  # noqa: N806
        ("2nd", Country.INDIA.value),
        ("3rd", Country.INDIA.value),
        ("1st", Country.INDIA.value),
        ("2nd", Country.CHINA.value),
        ("3rd", Country.CHINA.value),
        ("1st", Country.CHINA.value),
    }

    if (visa_class, country) not in PHYSICS_ELIGIBLE_SERIES:
        current_cutoff = get_cutoff_at_date(
            visa_class, country, action_type, knowledge_date
        )

        if knowledge_date.month == 12:
            first_future = date(knowledge_date.year + 1, 1, 1)
        else:
            first_future = date(knowledge_date.year, knowledge_date.month + 1, 1)

        persistence_result = SolverResult(
            month=first_future,
            cutoff_date=current_cutoff,
            consumed=0,
        )

        persist_meta = {
            "regime": regime_state.regime.value,
            "regime_confidence": regime_state.confidence,
            "regime_avg_move": regime_state.avg_move,
            "regime_volatility": regime_state.volatility,
            "pace_days_per_month": None,
            "persistence_weight": 1.0,
            "expert_weights": {"persistence": 1.0},
            "expert_preds": {},
            "confidence_low": None,
            "confidence_high": None,
            "moves": moves,
        }
        persist_maturity = None
        if priority_date is not None and current_cutoff is not None and current_cutoff >= priority_date:
            persist_maturity = first_future
        return SolverOutcome(current_cutoff, persist_meta, persist_maturity, [persistence_result], "low")

    # --- TIER 2: FY TRANSITION MODEL ---
    # At FY boundaries, the conditional transition model provides a prediction
    # based on utilization rate, backlog depth, and cross-series signals.
    # This prediction is blended with the standard ensemble at weight 0.6 (Tier 2)
    # vs 0.4 (Tier 1 ensemble), giving the transition model dominant influence
    # at the specific months where it has structural insight.
    tier2_prediction = None
    tier2_diagnostics = None
    if fy_boundary:
        from lib.business.vqs.fy_transition_model import predict_fy_transition

        tier2_result = predict_fy_transition(
            visa_class, country, action_type, knowledge_date,
            target_month=target_month, facts=facts,
        )
        if tier2_result.predicted_cutoff is not None:
            tier2_prediction = tier2_result.predicted_cutoff
            tier2_diagnostics = tier2_result.diagnostics
            logger.debug(
                f"[Tier2] {visa_class}/{country} target_m={target_month}: "
                f"pred={tier2_prediction} method={tier2_result.method} "
                f"move={tier2_result.predicted_move_days}d"
            )

    # PHASE 5: Online Expert Aggregation
    # Use the ensemble of experts (Persistence, Seasonal, Linear, Momentum, etc.)
    # learned via the Hedge algorithm on historical data.
    from lib.business.vqs.aggregator import ExpertAggregator

    if aggregator is None:
        from lib.business.vqs.metric_config import MetricConfig

        aggregator = ExpertAggregator(
            metric_config=metric_config or MetricConfig.defaults()
        )

    # Warmup weights by replaying history for this series
    # (aggregator.warmup_history checks self.warmed_series internally)
    aggregator.warmup_history(
        visa_class, country, action_type, knowledge_date, facts=facts
    )

    ensemble_cutoff, metadata = aggregator.predict(
        visa_class, country, action_type, knowledge_date, facts=facts
    )

    # Blend Tier 2 prediction with ensemble when at FY boundary
    if tier2_prediction is not None:
        if metadata is None:
            metadata = {}
        metadata["tier2_prediction"] = tier2_prediction.isoformat()
        metadata["tier2_diagnostics"] = tier2_diagnostics

        if ensemble_cutoff is not None:
            anchor = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
            if anchor is not None:
                tier2_weight = 0.6
                t2_delta = (tier2_prediction - anchor).days
                t1_delta = (ensemble_cutoff - anchor).days
                blended_delta = int(t2_delta * tier2_weight + t1_delta * (1 - tier2_weight))
                ensemble_cutoff = anchor + timedelta(days=blended_delta)
                metadata["tier2_weight"] = tier2_weight
            else:
                metadata["tier2_weight"] = 0.5
        else:
            ensemble_cutoff = tier2_prediction
            metadata["tier2_weight"] = 1.0

    # Compute confidence intervals from expert disagreement
    confidence_low = None
    confidence_high = None
    if metadata and "expert_preds" in metadata:
        expert_preds = metadata["expert_preds"]
        valid_preds = [p for p in expert_preds.values() if p is not None]

        if len(valid_preds) >= 2:
            # Calculate spread (difference between max and min predictions)
            min_pred = min(valid_preds)
            max_pred = max(valid_preds)
            spread_days = (max_pred - min_pred).days

            # Use asymmetric confidence: low = -30% of spread, high = +70% of spread
            # (Overshoots are more likely than undershoots in visa retrogression)
            if ensemble_cutoff:
                confidence_low = ensemble_cutoff - timedelta(
                    days=int(spread_days * 0.3)
                )
                confidence_high = ensemble_cutoff + timedelta(
                    days=int(spread_days * 0.7)
                )
                logger.debug(
                    f"[Confidence] {visa_class}/{country}: Spread={spread_days}d, CI=[{confidence_low}, {confidence_high}]"
                )

    if metadata is None:
        metadata = {}
    metadata["confidence_low"] = confidence_low
    metadata["confidence_high"] = confidence_high

    # Fetch current cutoff (needed for fallback and post-processing)
    current_cutoff = get_cutoff_at_date(
        visa_class, country, action_type, knowledge_date
    )

    final_ensemble_cutoff = None
    if ensemble_cutoff is not None and not force_physics:
        if current_cutoff is None:
            return SolverOutcome(ensemble_cutoff, metadata, None, [], confidence)

        # Pass raw ensemble prediction through to trajectory blending.
        # Post-step shaping is applied once at the end to avoid double dampening.
        final_ensemble_cutoff = ensemble_cutoff

    # Fallback to current_cutoff (Persistence) if ensemble fails completely
    if current_cutoff is None:
        current_cutoff = get_cutoff_at_date(
            visa_class, country, action_type, knowledge_date
        )
        if current_cutoff is None:
            if action_type == "filing":
                # Use Final Action as floor if Filing is missing (early backtests)
                current_cutoff = get_cutoff_at_date(
                    visa_class, country, "final_action", knowledge_date
                )

            if current_cutoff is None:
                current_cutoff = date(knowledge_date.year - 10, 1, 1)

    # FALLBACK: Physics engine (if seasonal prediction unavailable or forced)
    queue = build_virtual_queue_snapshot(
        knowledge_date,
        facts,
        visa_class=visa_class,
        country=country,
    )

    start_month = knowledge_date
    if start_month.month == 12:
        first_future = date(start_month.year + 1, 1, 1)
    else:
        first_future = date(start_month.year, start_month.month + 1, 1)

    # Build supply function with per-class allocation, seasonality, spillover
    if monthly_supply is not None:
        effective_supply = monthly_supply
        supply_fn = None
    else:
        base_supply = get_monthly_supply(
            first_future,
            country=country,
            visa_class=visa_class,
        )
        effective_supply = int(base_supply * meta.supply_scale_multiplier)

        def _scaled_supply(m):
            s = get_monthly_supply(m, country=country, visa_class=visa_class)
            return int(s * meta.supply_scale_multiplier)

        supply_fn = _scaled_supply

    # Retrogression months from history
    retro = get_retrogression_months_from_history(visa_class, country, action_type)
    if retro is None:
        retro = _RETROGRESSING_SERIES.get((visa_class, country), 0)

    # Queue depth calibration
    avg_adv = calibrate_queue_depth(
        queue,
        current_cutoff,
        knowledge_date,
        effective_supply,
        visa_class,
        country,
        action_type,
        meta,
    )

    # Build ensemble trajectory for multi-step blending
    ensemble_traj: list[date | None] | None = None
    if final_ensemble_cutoff is not None and meta.ensemble_trajectory_blend > 0:
        ensemble_traj = aggregator.predict_trajectory(
            visa_class, country, action_type, knowledge_date,
            steps=24, facts=facts,
        )

    results: list[SolverResult] = []
    raw_next_cutoff: date | None = None
    maturity_month: date | None = None

    blend_alpha = meta.ensemble_trajectory_blend
    decay = meta.ensemble_trajectory_decay

    for i, res in enumerate(
        run_monthly_loop(
            queue,
            current_cutoff,
            effective_supply,
            first_future,
            supply_fn=supply_fn,
            retrogression_months=retro,
        )
    ):
        # Blend physics with ensemble trajectory at each step
        if ensemble_traj is not None and i < len(ensemble_traj):
            step_weight = blend_alpha * (decay ** i)
            ens_pred = ensemble_traj[i]
            phys_pred = res.cutoff_date

            if ens_pred is not None and phys_pred is not None and step_weight > 0.01:
                delta = (ens_pred - phys_pred).days
                blended = phys_pred + timedelta(days=int(delta * step_weight))
                res = replace(res, cutoff_date=blended)
            elif i == 0 and final_ensemble_cutoff is not None:
                res = replace(res, cutoff_date=final_ensemble_cutoff)

        results.append(res)
        if i == 0:
            raw_next_cutoff = res.cutoff_date

        if (
            priority_date is not None
            and res.cutoff_date is not None
            and res.cutoff_date >= priority_date
            and maturity_month is None
        ):
            maturity_month = res.month
            break

    # Regime-aware persistence blending for all predictions.
    # FY-aware mode uses phase-specific weights; standard mode uses regime-based weights.
    if fy_boundary_aware:
        persistence_w = fy_aware_persistence_weight(regime_state)
    else:
        persistence_w = regime_persistence_weight(regime_state)
    if persistence_w > 0.01 and current_cutoff is not None:
        for i, res in enumerate(results):
            if res.cutoff_date is not None:
                delta = (res.cutoff_date - current_cutoff).days
                blended_delta = int(delta * (1.0 - persistence_w))
                results[i] = replace(res, cutoff_date=current_cutoff + timedelta(days=blended_delta))

    if final_ensemble_cutoff is not None:
        ensemble_delta = (final_ensemble_cutoff - current_cutoff).days
        blended_delta = int(ensemble_delta * (1.0 - persistence_w))
        final_next_cutoff = current_cutoff + timedelta(days=blended_delta)
    else:
        final_next_cutoff = meta.apply_post_step(
            current_cutoff, raw_next_cutoff, confidence, advancement_rate=avg_adv
        )

    # Enrich metadata with regime and pace signals for explainability
    metadata["regime"] = regime_state.regime.value
    metadata["regime_confidence"] = regime_state.confidence
    metadata["regime_avg_move"] = regime_state.avg_move
    metadata["regime_volatility"] = regime_state.volatility
    metadata["pace_days_per_month"] = avg_adv
    metadata["persistence_weight"] = persistence_w
    metadata["fy_boundary"] = fy_boundary
    metadata["fy_boundary_target_month"] = target_month if fy_boundary else None
    metadata["fy_phase"] = regime_state.fy_phase.value if hasattr(regime_state, 'fy_phase') else None
    metadata["moves"] = moves

    return SolverOutcome(final_next_cutoff, metadata, maturity_month, results, confidence)
