"""Queue engine: the deterministic core of the VQS solver.

Steps a virtual queue against monthly supply to produce cutoff dates, and
calibrates the queue's depth from historical bulletin advancement.

Split out of solver.py so it can be a LEAF. expert_pool's physics experts need
exactly this surface, and solver imports expert_pool to run the expert ensemble
— a cycle Bazel cannot express as deps in either direction, which failed at
CALL time with ModuleNotFoundError for any target whose closure had expert_pool
but not solver (reachable through predictors.py).

solver re-exports every name here, so `from lib.business.vqs.solver import
run_monthly_loop` keeps working and keeps returning THIS object.
"""

import calendar
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date

from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.queue_snapshot import VirtualQueueSnapshot
from models.enums.country import Country

# data_cache is imported lazily inside the function that uses it, exactly as it
# was in solver. Left alone so the moved body stays byte-identical to the
# original — the equivalence argument for this split is that the code did not
# change, only where it lives.


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
            # A1-F8: preserve the day-of-month. Clamping to day 1 dropped up to ~30
            # days of the original cutoff, deepening the retrogression by nearly a
            # month every simulated October. Clamp only when the target month is
            # shorter than the source day.
            max_day = calendar.monthrange(retro_year, retro_month)[1]
            cutoff = date(retro_year, retro_month, min(cutoff.day, max_day))

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
