"""VQS Solver: deterministic simulation engine.

Steps through future months, depleting the virtual queue against supply
to produce cutoff predictions and maturity dates. Includes queue depth
calibration from historical bulletin advancement rates and fiscal-year
retrogression handling.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterator

from lib.business.vqs.demand import build_virtual_queue_snapshot
from lib.business.vqs.estimators import get_monthly_supply
from lib.business.vqs.queue_snapshot import VirtualQueueSnapshot
from lib.business.vqs.data_cache import get_cutoff_at_date
from lib.business.vqs.seasonal_predictor import get_last_N_moves
from lib.business.vqs.meta_params import VqsMetaParams
from dataclasses import replace
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
    from lib.business.vqs.data_cache import get_cutoffs_for_series

    # EB1 India: longer lookback for smoother historical advancement rate.
    if lookback_months is None:
        lookback_months = 36 if (visa_class == "1st" and country == Country.INDIA.value) else 24  # pyright: ignore[reportAttributeAccessIssue]

    # Use cache to avoid DB hit in tight loops
    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    
    # Filter for dates <= as_of. Since array is sorted by date:
    # (could use bisect, but linear scan is fine for N<500)
    filtered = []
    for c in all_cutoffs:
        if c.bulletin.publication_date <= as_of and c.cutoff_date is not None:
             filtered.append(c)
        elif c.bulletin.publication_date > as_of:
             break
             
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
        visa_class, country, action_type, knowledge_date,
        lookback_months=lookback,
        recency_weight=meta.advancement_rate_recency_weight,
    )
    
    # NEW: Fallback to Final Action history for rate estimation if Filing history is sparse
    if (avg_adv is None or avg_adv <= 0) and action_type == "filing":
        avg_adv = get_historical_advancement_rate(
            visa_class, country, "final_action", knowledge_date,
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
        months_back = (
            (sept_cutoff.year - oct_cutoff.year) * 12
            + (sept_cutoff.month - oct_cutoff.month)
        )
        if months_back > 0:
            retro_months_list.append(months_back)

    if len(retro_months_list) < MIN_RETROGRESSION_TRANSITIONS:
        return None
    return int(round(sum(retro_months_list) / len(retro_months_list)))


def predict_next_bulletin_and_maturity(
    knowledge_date: date,
    visa_class: str,
    country: int,
    action_type: str,
    priority_date: date | None = None,
    monthly_supply: int | None = None,
    facts: list | None = None,
    meta: "VqsMetaParams | None" = None,
    aggregator: "ExpertAggregator | None" = None,
    force_physics: bool = False,
) -> tuple[date | None, date | None, list[SolverResult], str]:
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
        (next_cutoff_date, maturity_month, results, confidence).
        next_cutoff_date: predicted cutoff for the first future month.
        maturity_month: first month (first day) where cutoff >= priority_date, or None.
        results: list of SolverResult for each month (up to maturity or max).
        confidence: "high" | "medium" | "low" from I-140 data availability.
    """
    from lib.business.vqs.meta_params import VqsMetaParams
    from models.raw_facts import RawFactsLedger

    if meta is None:
        meta = VqsMetaParams.defaults()

    # ... (Regime Shock Override logic omitted for brevity in diff, but preserved in file via context) ...

    # --- REGIME SHOCK OVERRIDE (Phase 8A) ---
    # If a significant retrogression (>30 days) occurred recently, we force the model 
    # into "lockdown" mode by maximizing persistence weight.
    # Iteration 3: Removed Q4 exemption. A significant shock resets expectations regardless of season.
    moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 3)
    if moves:
        min_move = min(moves)
        if min_move <= -30:
            # target_month = (knowledge_date.month % 12) + 1
            # logger.info(f"Regime Shock ({min_move} days) in {visa_class}/{country} @ {knowledge_date}. Forcing Persistence.")
            meta = replace(meta, 
                ensemble_persistence_weight=0.98,
                stickiness_days=180
            )
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
        # Return current setup with low confidence
        current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
        # If current_cutoff is None, return None (no prediction) instead of fallback
        return (current_cutoff, None, [], "low")

    # PHASE 3 IMPROVEMENT: Confidence Gate
    # Only run physics for series where we have signal (Retrogressed).
    # Non-retrogressed series (ROW, Mexico, Philippines) have 0% beat rate with physics
    # and add massive noise. Default them to persistence.
    PHYSICS_ELIGIBLE_SERIES = {
        ("2nd", Country.INDIA.value),
        ("3rd", Country.INDIA.value),
        ("1st", Country.INDIA.value),
        ("2nd", Country.CHINA.value),
        ("3rd", Country.CHINA.value),
        ("1st", Country.CHINA.value),
    }

    if (visa_class, country) not in PHYSICS_ELIGIBLE_SERIES:
        # Use persistence-only prediction but still populate results
        current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
        
        # Create a simple persistence-based result for maturity validation
        # This ensures all series return at least one result, enabling longterm validation
        # Calculate first day of month after knowledge_date
        if knowledge_date.month == 12:
            first_future = date(knowledge_date.year + 1, 1, 1)
        else:
            first_future = date(knowledge_date.year, knowledge_date.month + 1, 1)
        
        persistence_result = SolverResult(
            month=first_future,
            cutoff_date=current_cutoff,
            consumed=0,
        )
        
        # Return persistence prediction with populated results
        return (current_cutoff, None, [persistence_result], "low")

    # PHASE 5: Online Expert Aggregation
    # Use the ensemble of experts (Persistence, Seasonal, Linear, Momentum, etc.)
    # learned via the Hedge algorithm on historical data.
    from lib.business.vqs.aggregator import ExpertAggregator
    
    if aggregator is None:
        aggregator = ExpertAggregator()
    
    # Warmup weights by replaying history for this series
    # (aggregator.warmup_history checks self.warmed_series internally)
    aggregator.warmup_history(
        visa_class, country, action_type, knowledge_date, facts=facts
    )
    
    ensemble_cutoff, metadata = aggregator.predict(
        visa_class, country, action_type, knowledge_date, facts=facts
    )
    
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
                confidence_low = ensemble_cutoff - timedelta(days=int(spread_days * 0.3))
                confidence_high = ensemble_cutoff + timedelta(days=int(spread_days * 0.7))
                logger.debug(f"[Confidence] {visa_class}/{country}: Spread={spread_days}d, CI=[{confidence_low}, {confidence_high}]")
    
    if metadata is None:
        metadata = {}
    metadata["confidence_low"] = confidence_low
    metadata["confidence_high"] = confidence_high
    
    # Fetch current cutoff (needed for fallback and post-processing)
    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    
    final_ensemble_cutoff = None
    if ensemble_cutoff is not None and not force_physics:
        if current_cutoff is None:
             # If no history, just return the prediction raw
             return (ensemble_cutoff, None, [], confidence)

        # Apply post-step logic (Stickiness, Caps, Blend) from Meta Params
        # This allows Stage 2 (Control) tuning to effective on the ensemble output
        if meta:
            # Calculate advancement rate for regime-based stickiness
            adv_rate = get_historical_advancement_rate(
                visa_class, country, action_type, knowledge_date,
                lookback_months=meta.lookback_months_default,
                recency_weight=meta.advancement_rate_recency_weight
            )
            
            final_ensemble_cutoff = meta.apply_post_step(
                current_cutoff=current_cutoff,
                raw_next_cutoff=ensemble_cutoff,
                confidence=confidence,
                advancement_rate=adv_rate
            )
        else:
            final_ensemble_cutoff = ensemble_cutoff

    # Fallback to current_cutoff (Persistence) if ensemble fails completely
    if current_cutoff is None:
        current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
        if current_cutoff is None:
             if action_type == "filing":
                 # Use Final Action as floor if Filing is missing (early backtests)
                 current_cutoff = get_cutoff_at_date(visa_class, country, "final_action", knowledge_date)
             
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
            first_future, country=country, visa_class=visa_class,
        )
        effective_supply = int(base_supply * meta.supply_scale_multiplier)
        
        def _scaled_supply(m):
            s = get_monthly_supply(m, country=country, visa_class=visa_class)
            return int(s * meta.supply_scale_multiplier)
            
        supply_fn = _scaled_supply

    # Retrogression months from history
    retro = get_retrogression_months_from_history(
        visa_class, country, action_type
    )
    if retro is None:
        retro = _RETROGRESSING_SERIES.get((visa_class, country), 0)

    # Queue depth calibration
    avg_adv = calibrate_queue_depth(
        queue, current_cutoff, knowledge_date, effective_supply,
        visa_class, country, action_type, meta
    )

    results: list[SolverResult] = []
    raw_next_cutoff: date | None = None
    maturity_month: date | None = None
    
    # Run the monthly simulation loop
    for i, res in enumerate(run_monthly_loop(
        queue, current_cutoff, effective_supply, first_future,
        supply_fn=supply_fn, retrogression_months=retro,
    )):
        # If we have a high-stability ensemble prediction for month 1, override the physics month 1
        if i == 0 and final_ensemble_cutoff is not None:
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

    # Apply Post-Step Shaping to the immediate next bulletin prediction
    final_next_cutoff = meta.apply_post_step(
        current_cutoff, raw_next_cutoff, confidence, advancement_rate=avg_adv
    )
    
    return (final_next_cutoff, maturity_month, results, confidence)

