"""
Expert Pool for VQS Online Aggregation Framework.

Each expert is a stateless function:
    (visa_class, country, action_type, knowledge_date) -> predicted_cutoff_date | None

Experts return None if they cannot make a predictions (e.g. insufficient history).
"""

from datetime import date, timedelta
from statistics import stdev

from lib.business.vqs.data_cache import get_all_bulletins, get_cutoffs_for_series
from lib.business.vqs.seasonal_predictor import (
    get_historical_issuance_median,
    get_last_N_moves,
    get_median_october_retrogression,
    get_median_post_retro_recovery,
    get_seasonal_prediction,
    get_seasonal_prediction_filtered,
)


def expert_persistence(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts no change from the previous bulletin."""
    # Find most recent bulletin before knowledge_date
    bulletins = get_all_bulletins()
    prev_bulletin = None
    # Linear scan from end is fast for N < 500
    for i in range(len(bulletins) - 1, -1, -1):
        if bulletins[i].publication_date < knowledge_date:
            prev_bulletin = bulletins[i]
            break

    if not prev_bulletin:
        return None

    # Find cutoff for this bulletin
    cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    # Binary search or just scan? Since cutoffs are ordered by bulletin date:
    # We can just look for the one matching prev_bulletin.
    # Optimization: iterate backwards matching bulletins.
    # Actually, we can just grab the last one < knowledge_date?
    # Yes! The last cutoff in the filtered list is exactly what we want.

    # Filter valid cutoffs before knowledge_date
    # (Note: cutoffs list is already ordered by bulletin date)
    # Optimization: slice from end? No, need to check date.
    # Let's verify assumption: cutoffs are ordered.
    # So the last one with date < knowledge_date is the persistence value.

    # Binary search for index?
    # For now, linear scan backwards
    for i in range(len(cutoffs) - 1, -1, -1):
        if cutoffs[i].bulletin.publication_date < knowledge_date:
            return cutoffs[i].cutoff_date

    return None


def expert_seasonal_median(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts using historical median movement for this specific month."""
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # Determine target month (knowledge_date + 1 month roughly)
    target_month = (knowledge_date.month % 12) + 1

    move_days = get_seasonal_prediction(
        visa_class,
        country,
        action_type,
        knowledge_date=knowledge_date,
        target_month=target_month,
        min_samples=3,
    )

    if move_days is None:
        return current_cutoff  # Fallback to persistence if no seasonal data

    return current_cutoff + timedelta(days=move_days)


def expert_linear_extrap(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts using trailing 12-month average pace."""
    # Look back 1 year
    start_date = knowledge_date - timedelta(days=370)

    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)

    cutoffs = []
    # Linear scan (can be optimized but < 200 items in all_cutoffs usually)
    for c in all_cutoffs:
        d = c.bulletin.publication_date
        if start_date <= d < knowledge_date:
            cutoffs.append(c)
        elif d >= knowledge_date:
            break

    if len(cutoffs) < 2:
        return None

    first, last = cutoffs[0], cutoffs[-1]

    # Approx months elapsed
    months = (
        last.bulletin.publication_date.year - first.bulletin.publication_date.year
    ) * 12 + (
        last.bulletin.publication_date.month - first.bulletin.publication_date.month
    )

    if months < 1:
        months = 1

    pace = (last.cutoff_date - first.cutoff_date).days / months
    return last.cutoff_date + timedelta(days=int(pace))


def expert_momentum_3m(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts using trailing 3-month average pace (short-term momentum)."""
    # Look back ~4 months to get 3 intervals
    start_date = knowledge_date - timedelta(days=130)

    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)

    cutoffs = []
    for c in all_cutoffs:
        d = c.bulletin.publication_date
        if start_date <= d < knowledge_date:
            cutoffs.append(c)
        elif d >= knowledge_date:
            break

    if len(cutoffs) < 2:
        return None

    first, last = cutoffs[0], cutoffs[-1]

    months = (
        last.bulletin.publication_date.year - first.bulletin.publication_date.year
    ) * 12 + (
        last.bulletin.publication_date.month - first.bulletin.publication_date.month
    )

    if months < 1:
        months = 1

    pace = (last.cutoff_date - first.cutoff_date).days / months
    return last.cutoff_date + timedelta(days=int(pace))


def expert_october_rule(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts specific retrogressions for October bulletins."""
    # Target bulletin is for next month. If knowledge_date is in Sep, target is Oct.
    target_month = (knowledge_date.month % 12) + 1

    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    if target_month != 10:
        return current_cutoff  # No-op for non-October months

    # Hardcoded learned retrogressions (conservative estimates)
    # India EB2/EB3/EB4 often retrogress or advance huge amounts.
    # For now, let's just use persistence for Oct unless we have a specific hardcoded rule.
    # The aggregator will learn to downweight this if it's bad.

    # Example rule: India EB2 often retrogresses in Oct if it advanced in Sep?
    # For this initial version, let's make it identical to Seasonal Median but ONLY for October.
    # This expert "specializes" in October.

    return expert_seasonal_median(visa_class, country, action_type, knowledge_date)


def expert_fy_reset(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Models the systematic October retrogression + Q1 recovery cycle."""
    target_month = (knowledge_date.month % 12) + 1
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    if target_month == 10:  # Predict October retrogression
        retro_days = get_median_october_retrogression(
            visa_class, country, action_type, knowledge_date
        )
        if (
            retro_days > 0
        ):  # Correction: get_median_october_retrogression returns positive days of retrogression
            return current_cutoff - timedelta(days=retro_days)
        return current_cutoff

    elif target_month in (11, 12, 1):  # Predict Q1 Recovery
        recovery_days = get_median_post_retro_recovery(
            visa_class, country, action_type, knowledge_date, target_month
        )
        if recovery_days > 0:
            return current_cutoff + timedelta(days=recovery_days)
        return current_cutoff

    else:
        # Outside reset window, default to persistence
        return current_cutoff


def expert_seasonal_directional(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts using regime-aware seasonal median (advancing vs retrogressing)."""
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # Determine current regime
    # Look at last 2 months to determine if we are in a retrogression/advancement phase
    moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 1)
    is_retrogressing = (moves[0] < 0) if moves else False

    target_month = (knowledge_date.month % 12) + 1
    regime = "retrogressing" if is_retrogressing else "advancing"

    move_days = get_seasonal_prediction_filtered(
        visa_class,
        country,
        action_type,
        knowledge_date,
        target_month=target_month,
        regime=regime,
        min_samples=2,
    )

    if move_days is None:
        # Fallback to standard seasonal median
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date)

    return current_cutoff + timedelta(days=move_days)


def expert_vol_gated(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """In high-volatility periods, shrinks predictions towards persistence."""
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # Calculate volatility (std dev of last 6 moves)
    recent_moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 6)
    volatility = stdev(recent_moves) if len(recent_moves) >= 3 else 0.0

    # Base prediction (e.g., Seasonal Median)
    seasonal_pred = expert_seasonal_median(
        visa_class, country, action_type, knowledge_date
    )
    if not seasonal_pred:
        return current_cutoff

    # Shrinkage factor: 90 days vol -> 100% persistence
    shrinkage = min(1.0, volatility / 90.0)
    alpha = 1.0 - shrinkage

    # Blend
    delta = (seasonal_pred - current_cutoff).days * alpha
    return current_cutoff + timedelta(days=int(delta))


def expert_recency_seasonal(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Predicts using Recency-Weighted Seasonal Median (exponential decay)."""
    # For now, until we fully implement weighted median in seasonal_predictor,
    # let's just use a shorter window (last 3 samples) for the "seasonal_median" call
    # instead of the default logic.
    # Actually, the default seasonal_predictor uses all history.
    # Let's mock this by implementing a simplified version here or assuming
    # we'll upgrade seasonal_predictor later.
    # PLAN: Just alias to seasonal_median for now to unblock,
    # but with a TODO to add weighting in the helper.
    # BETTER: Use get_seasonal_prediction but rely on its median property which
    # naturally handles recent data if distribution is stable, but for regime change
    # we want RECENT samples.

    # We can't easily change the helper's weighting without changing its signature.
    # Let's fallback to expert_seasonal_median for this iteration
    # and mark it as a placeholder.
    return expert_seasonal_median(visa_class, country, action_type, knowledge_date)


from functools import lru_cache  # noqa: E402


def _physics_prediction_impl(
    visa_class: str, country: int, action_type: str, knowledge_date: date, facts: list
) -> date | None:
    """Core logic of the physics engine (uncached)."""
    # Local imports to avoid circular dependency
    # solver.py -> aggregator.py -> expert_pool.py
    from lib.business.vqs.data_cache import get_cutoff_at_date
    from lib.business.vqs.solver import (
        build_virtual_queue_snapshot,
        calibrate_queue_depth,
        get_monthly_supply,
        run_monthly_loop,
    )

    # 1. Get current cutoff (Persistence)
    current_cutoff = get_cutoff_at_date(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # 2. Build Queue (using passed facts)
    queue = build_virtual_queue_snapshot(knowledge_date, facts, visa_class, country)

    # 3. Get Supply
    # Use generic supply for now (since we haven't built the new supply module yet)
    # The existing get_monthly_supply in solver/estimators is basic but functional
    # We need a date for supply... let's use knowledge_date as proxy for "current month"
    supply = get_monthly_supply(knowledge_date, country=country, visa_class=visa_class)

    # 4. Calibrate
    calibrate_queue_depth(
        queue, current_cutoff, knowledge_date, supply, visa_class, country, action_type
    )

    # 5. Run Simulation (1 step)
    # run_monthly_loop yields SolverResult objects
    # We just need the first predicted cutoff
    cutoff_predictor = run_monthly_loop(
        queue,
        current_cutoff,
        supply,
        start_month=knowledge_date,
        max_months=12,  # restrict horizon for speed
    )

    try:
        first_result = next(cutoff_predictor)
        return first_result.cutoff_date
    except StopIteration:
        return current_cutoff


@lru_cache(maxsize=1024)
def _cached_physics_prediction(
    visa_class: str, country: int, action_type: str, knowledge_date: date
) -> date | None:
    """Cached wrapper that fetches facts."""
    from models.raw_facts import RawFactsLedger

    # Fetch facts
    facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))
    return _physics_prediction_impl(
        visa_class, country, action_type, knowledge_date, facts
    )


def expert_physics(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Wraps the physics/queue engine as a Hedge expert."""
    # If facts provided, bypass cache and fetch
    if facts is not None:
        return _physics_prediction_impl(
            visa_class, country, action_type, knowledge_date, facts
        )

    return _cached_physics_prediction(visa_class, country, action_type, knowledge_date)


def expert_supply_aware(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """Scales historical advancement rate by current supply ratio vs base."""
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # Import locally to avoid circularity (expert_pool -> supply -> allocator)
    from datetime import (  # date is already imported at module level, but good for clarity
        date,
        timedelta,
    )

    from lib.business.vqs.solver import get_historical_advancement_rate
    from lib.business.vqs.supply import SupplyAllocator

    # 1. Get Base Supply (Statutory + Seasonality) vs Total Supply (inc Cascade/Spillover)
    # We need to peek ahead one month to see supply conditions for the prediction period.
    if knowledge_date.month == 12:
        next_month = date(knowledge_date.year + 1, 1, 1)
    else:
        next_month = date(knowledge_date.year, knowledge_date.month + 1, 1)

    allocator = SupplyAllocator()
    allocation = allocator.get_supply(visa_class, country, next_month, knowledge_date)

    # Ratio: Total Available / Base Statutory
    # Base supply from allocator includes seasonality, which is correct for apples-to-apples
    # if we compare to "historical pace at this time of year".
    # BUT get_historical_advancement_rate averages over 24-36 months, so it smooths seasonality.
    # So we should compare Total Supply to Annual Averaged Base?
    # Or just monthly base?
    # If we use monthly base with seasonality, we might double-count seasonality if the pace
    # already captures "August is fast".
    # However, if supply is abnormally high (cascade), we want to boost it.
    # Let's use ratio = total / base. If total == base, ratio = 1.0 -> same as historical avg.
    # This implies historical avg is achieved when supply is "normal".
    # This is a safe assumption.

    if allocation.base_supply > 0:
        ratio = allocation.total / allocation.base_supply
    else:
        ratio = 1.0

    # 2. Get Historical Pace
    pace = get_historical_advancement_rate(
        visa_class, country, action_type, knowledge_date
    )

    if pace is not None and pace > 0:
        # 3. Predict: Advance by (Pace * Ratio * 30 days) ?
        # Pace is in "days/month".
        # If ratio is 1.5, we advance 1.5x speed.
        # Cap at 365 days? No, theoretical max is high.

        # Project forward
        # We are predicting the NEW cutoff date for next month.
        # current_cutoff is the cutoff from THIS month (persistence).
        # next_cutoff = current + days_adv

        # Round to integer days
        # pace = (cutoff_delta).days
        # So if pace=10, it means cutoff moves 10 days in 1 month.
        # We don't mult by 30 unless pace is "advancement rate per day".
        # get_historical_advancement_rate docstring: "days/month".
        # So we just multiply by ratio.

        days_to_add = int(pace * ratio)

        # Apply predicted advancement
        new_date = current_cutoff + timedelta(days=days_to_add)
        return new_date

    return (
        current_cutoff  # If pace is not available or not positive, return persistence.
    )


def expert_dos_historical(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """
    Expert that scales seasonal movement by (current_supply / historical_issuance).

    This is highly effective because it captures when a series has 'extra' supply
    (spillovers) compared to its historical norm for that month.
    """
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # 1. Target month for prediction
    target_month = (knowledge_date.month % 12) + 1

    # 2. Get historical median move (days)
    hist_move = get_seasonal_prediction(
        visa_class, country, action_type, knowledge_date, target_month
    )
    if hist_move is None:
        return current_cutoff  # Fallback to persistence

    # 3. Get historical median issuance (visas)
    hist_issuance = get_historical_issuance_median(
        visa_class, country, target_month, knowledge_date, facts
    )
    if not hist_issuance or hist_issuance <= 0:
        # If no issuance data, fallback to regular seasonal median (scaled 1.0)
        return current_cutoff + timedelta(days=hist_move)

    # 4. Get current predicted supply (visas)
    # Estimate the bulletin date
    if knowledge_date.month == 12:
        bulletin_date = date(knowledge_date.year + 1, 1, 1)
    else:
        bulletin_date = date(knowledge_date.year, knowledge_date.month + 1, 1)

    from lib.business.vqs.supply.allocator import SupplyAllocator

    allocator = SupplyAllocator()
    current_supply = allocator.get_supply(
        visa_class, country, bulletin_date, knowledge_date
    ).total

    # 5. Scale the move
    # If the current supply is higher than historical issuance, the cutoff should advance faster.
    ratio = current_supply / hist_issuance

    # Cap ratio to avoid explosive predictions from data noise (0.1x to 3x)
    ratio = min(max(ratio, 0.1), 3.0)

    scaled_move = int(hist_move * ratio)
    return current_cutoff + timedelta(days=scaled_move)


def expert_demand_signal(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> date | None:
    """
    Expert that slows down predictions if recent I-140 demand is spiking.

    This acts as a 'brake' on aggressive advancement when queue pressure is building.
    """
    current_cutoff = expert_persistence(
        visa_class, country, action_type, knowledge_date
    )
    if not current_cutoff:
        return None

    # Use a basic expert for the core prediction to be braked
    base_pred = expert_seasonal_median(visa_class, country, action_type, knowledge_date)
    if not base_pred or base_pred <= current_cutoff:
        return current_cutoff

    # 1. Fetch recent I-140 receipts (quarterly facts)
    from models.raw_facts import RawFactsLedger

    if facts is None:
        filtered_facts = list(
            RawFactsLedger.objects.filter(
                metric="i140_receipts", publication_date__lt=knowledge_date
            )
        )
    else:
        filtered_facts = facts

    country_facts = []
    for f in filtered_facts:
        if f.metric != "i140_receipts":
            continue
        if f.publication_date >= knowledge_date:
            continue
        if str(f.dimensions.get("country")) != str(country):
            continue
        country_facts.append(f)

    # Sort by period
    country_facts.sort(key=lambda x: x.reference_period_start)

    if len(country_facts) < 4:
        return current_cutoff

    recent = country_facts[-2:]
    hist_pool = country_facts[:-2]

    def get_val(f):
        if isinstance(f.value, list) and len(f.value) > 0:
            return float(f.value[0])
        return float(f.value)

    recent_avg = sum(get_val(f) for f in recent) / 2
    hist_avg = sum(get_val(f) for f in hist_pool) / len(hist_pool)

    if hist_avg <= 0:
        return current_cutoff

    demand_ratio = recent_avg / hist_avg

    # 2. Adjust: if demand spiked by >10%
    if demand_ratio > 1.1:
        # Apply 20% brake per 10% spike, capped at 50% brake
        brake = min(0.5, (demand_ratio - 1.0) * 2.0)
        delta = (base_pred - current_cutoff).days * (1.0 - brake)
        return current_cutoff + timedelta(days=int(delta))

    return base_pred


ALL_EXPERTS = {
    "persistence": expert_persistence,
    "seasonal_median": expert_seasonal_median,
    "linear_extrap": expert_linear_extrap,
    "momentum_3m": expert_momentum_3m,
    "october_rule": expert_october_rule,
    "fy_reset": expert_fy_reset,
    "seasonal_directional": expert_seasonal_directional,
    "vol_gated": expert_vol_gated,
    "recency_seasonal": expert_recency_seasonal,
    "physics": expert_physics,
    "supply_aware": expert_supply_aware,
    "dos_historical": expert_dos_historical,
    "demand_signal": expert_demand_signal,
}


# ---------------------------------------------------------------------------
# Multi-step trajectory functions
# ---------------------------------------------------------------------------
# Each returns list[date | None] of length `steps`, representing the
# expert's prediction for months 1..steps ahead of knowledge_date.

def _get_pace(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, lookback_days: int,
) -> float | None:
    """Extract monthly pace (days/month) from trailing cutoff history."""
    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    start = knowledge_date - timedelta(days=lookback_days)
    window = [c for c in all_cutoffs
              if start <= c.bulletin.publication_date < knowledge_date]
    if len(window) < 2:
        return None
    first, last = window[0], window[-1]
    months = ((last.bulletin.publication_date.year - first.bulletin.publication_date.year) * 12
              + (last.bulletin.publication_date.month - first.bulletin.publication_date.month))
    if months < 1:
        months = 1
    return (last.cutoff_date - first.cutoff_date).days / months


def _pace_trajectory(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int, lookback_days: int,
) -> list[date | None]:
    """Linear extrapolation trajectory at a fixed pace."""
    current = expert_persistence(visa_class, country, action_type, knowledge_date)
    pace = _get_pace(visa_class, country, action_type, knowledge_date, lookback_days)
    if current is None or pace is None:
        return [None] * steps
    return [current + timedelta(days=int(pace * (i + 1))) for i in range(steps)]


def _seasonal_chain_trajectory(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int,
) -> list[date | None]:
    """Chain monthly seasonal median predictions forward."""
    current = expert_persistence(visa_class, country, action_type, knowledge_date)
    if current is None:
        return [None] * steps
    trajectory: list[date | None] = []
    cutoff = current
    for i in range(steps):
        target_month = ((knowledge_date.month + i) % 12) + 1
        move = get_seasonal_prediction(
            visa_class, country, action_type,
            knowledge_date=knowledge_date,
            target_month=target_month, min_samples=3,
        )
        if move is not None:
            cutoff = cutoff + timedelta(days=move)
        trajectory.append(cutoff)
    return trajectory


def trajectory_persistence(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    current = expert_persistence(visa_class, country, action_type, knowledge_date, facts)
    return [current] * steps if current else [None] * steps


def trajectory_linear_extrap(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    return _pace_trajectory(visa_class, country, action_type, knowledge_date, steps, 370)


def trajectory_momentum_3m(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    return _pace_trajectory(visa_class, country, action_type, knowledge_date, steps, 130)


def trajectory_seasonal_median(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    return _seasonal_chain_trajectory(visa_class, country, action_type, knowledge_date, steps)


def trajectory_october_rule(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    """Persistence except at October transitions; uses seasonal there."""
    current = expert_persistence(visa_class, country, action_type, knowledge_date, facts)
    if current is None:
        return [None] * steps
    trajectory: list[date | None] = []
    cutoff = current
    for i in range(steps):
        target_month = ((knowledge_date.month + i) % 12) + 1
        if target_month == 10:
            pred = expert_seasonal_median(visa_class, country, action_type, knowledge_date, facts)
            cutoff = pred if pred else cutoff
        trajectory.append(cutoff)
    return trajectory


def trajectory_fy_reset(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    """October retrogression + Q1 recovery, persistence otherwise."""
    current = expert_persistence(visa_class, country, action_type, knowledge_date, facts)
    if current is None:
        return [None] * steps
    trajectory: list[date | None] = []
    cutoff = current
    for i in range(steps):
        target_month = ((knowledge_date.month + i) % 12) + 1
        if target_month == 10:
            retro = get_median_october_retrogression(
                visa_class, country, action_type, knowledge_date)
            if retro > 0:
                cutoff = cutoff - timedelta(days=retro)
        elif target_month in (11, 12, 1):
            recovery = get_median_post_retro_recovery(
                visa_class, country, action_type, knowledge_date, target_month)
            if recovery > 0:
                cutoff = cutoff + timedelta(days=recovery)
        trajectory.append(cutoff)
    return trajectory


def trajectory_physics(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    """Run the physics engine for N steps to get a full trajectory."""
    from lib.business.vqs.data_cache import get_cutoff_at_date
    from lib.business.vqs.solver import (
        build_virtual_queue_snapshot,
        calibrate_queue_depth,
        get_monthly_supply,
        run_monthly_loop,
    )
    if facts is None:
        from models.raw_facts import RawFactsLedger
        facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))
    current = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current:
        return [None] * steps
    queue = build_virtual_queue_snapshot(knowledge_date, facts, visa_class, country)
    supply = get_monthly_supply(knowledge_date, country=country, visa_class=visa_class)
    calibrate_queue_depth(
        queue, current, knowledge_date, supply, visa_class, country, action_type)
    results: list[date | None] = []
    for res in run_monthly_loop(queue, current, supply, start_month=knowledge_date, max_months=steps):
        results.append(res.cutoff_date)
    while len(results) < steps:
        results.append(results[-1] if results else None)
    return results


def _identity_trajectory(expert_fn):
    """Wrap a single-step expert into a trajectory by repeating step-1 for all steps."""
    def _traj(visa_class, country, action_type, knowledge_date, steps=12, facts=None):
        expert_fn(visa_class, country, action_type, knowledge_date, facts)
        return _seasonal_chain_trajectory(visa_class, country, action_type, knowledge_date, steps)
    return _traj


ALL_EXPERT_TRAJECTORIES = {
    "persistence": trajectory_persistence,
    "seasonal_median": trajectory_seasonal_median,
    "linear_extrap": trajectory_linear_extrap,
    "momentum_3m": trajectory_momentum_3m,
    "october_rule": trajectory_october_rule,
    "fy_reset": trajectory_fy_reset,
    "seasonal_directional": trajectory_seasonal_median,  # same chain logic
    "vol_gated": trajectory_seasonal_median,  # base is seasonal
    "recency_seasonal": trajectory_seasonal_median,
    "physics": trajectory_physics,
    "supply_aware": trajectory_linear_extrap,  # pace-based, supply ratio is step-1 only
    "dos_historical": trajectory_seasonal_median,
    "demand_signal": trajectory_seasonal_median,
}
