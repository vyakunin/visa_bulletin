"""Expert Pool for VQS Online Aggregation Framework.

Each expert is a stateless function:
    (visa_class, country, action_type, knowledge_date) -> predicted_cutoff_date | None

Experts return None if they cannot make a prediction (e.g. insufficient history).

Pool contains 11 distinct strategies:
  persistence       - no change baseline
  seasonal_median   - historical median movement for this month
  linear_extrap     - 12-month trailing pace
  momentum_3m       - 3-month trailing pace (short-term)
  fy_reset          - fiscal year Oct retrogression + Q1 recovery
  physics           - queue simulation engine
  supply_aware      - pace scaled by supply ratio
  demand_signal     - brakes seasonal when I-140 demand spikes
  i485_queue_depth  - queue depth from I-485 pending inventory (independent signal)
  cross_series      - EB-1 movement as leading indicator for EB-2/3 via spillover
  gbm               - LightGBM model trained on tabular features (requires lightgbm)
"""

from datetime import date, timedelta
from functools import lru_cache

from lib.business.vqs.data_cache import (
    get_cutoff_at_date,
    get_cutoffs_up_to,
)
from lib.business.vqs.seasonal_predictor import (
    get_last_N_moves,
    get_median_october_retrogression,
    get_median_post_retro_recovery,
    get_seasonal_prediction,
)

# ---------------------------------------------------------------------------
# Single-step expert functions
# ---------------------------------------------------------------------------

def expert_persistence(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Predicts no change from the previous bulletin."""
    return get_cutoff_at_date(visa_class, country, action_type, knowledge_date)


def expert_seasonal_median(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Predicts using historical median movement for this specific month."""
    current_cutoff = expert_persistence(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    target_month = (knowledge_date.month % 12) + 1
    move_days = get_seasonal_prediction(
        visa_class, country, action_type,
        knowledge_date=knowledge_date, target_month=target_month, min_samples=3,
    )


    if move_days is None:
        return current_cutoff
    return current_cutoff + timedelta(days=move_days)


def expert_linear_extrap(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Predicts using trailing 12-month average pace."""
    return _pace_prediction(visa_class, country, action_type, knowledge_date, 370)


def expert_momentum_3m(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Predicts using trailing 3-month average pace (short-term momentum)."""
    return _pace_prediction(visa_class, country, action_type, knowledge_date, 130)


def expert_fy_reset(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Models FY cycle: Oct retrogression, Q1 recovery, Q2-Q4 seasonal pace."""
    target_month = (knowledge_date.month % 12) + 1
    current_cutoff = expert_persistence(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    if target_month == 10:
        retro_days = get_median_october_retrogression(
            visa_class, country, action_type, knowledge_date
        )
        if retro_days > 0:
            return current_cutoff - timedelta(days=retro_days)
        return current_cutoff
    elif target_month in (11, 12, 1):
        recovery_days = get_median_post_retro_recovery(
            visa_class, country, action_type, knowledge_date, target_month
        )
        if recovery_days > 0:
            return current_cutoff + timedelta(days=recovery_days)
        return current_cutoff
    else:
        move_days = get_seasonal_prediction(
            visa_class, country, action_type,
            knowledge_date=knowledge_date, target_month=target_month, min_samples=3,
        )
        if move_days is not None:
            return current_cutoff + timedelta(days=move_days)
        return current_cutoff


def _physics_prediction_impl(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list,
) -> date | None:
    """Core logic of the physics engine (uncached)."""
    from lib.business.vqs.data_cache import get_cutoff_at_date
    from lib.business.vqs.solver import (
        build_virtual_queue_snapshot,
        calibrate_queue_depth,
        get_monthly_supply,
        run_monthly_loop,
    )

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    queue = build_virtual_queue_snapshot(knowledge_date, facts, visa_class, country)
    supply = get_monthly_supply(knowledge_date, country=country, visa_class=visa_class)
    calibrate_queue_depth(
        queue, current_cutoff, knowledge_date, supply,
        visa_class, country, action_type,
    )

    try:
        first_result = next(
            run_monthly_loop(queue, current_cutoff, supply, start_month=knowledge_date, max_months=12)
        )
        return first_result.cutoff_date
    except StopIteration:
        return current_cutoff


@lru_cache(maxsize=1024)
def _cached_physics_prediction(
    visa_class: str, country: int, action_type: str, knowledge_date: date,
) -> date | None:
    """Cached wrapper that fetches facts."""
    from models.raw_facts import RawFactsLedger

    facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))
    return _physics_prediction_impl(visa_class, country, action_type, knowledge_date, facts)


def expert_physics(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Wraps the physics/queue engine as a Hedge expert."""
    if facts is not None:
        return _physics_prediction_impl(visa_class, country, action_type, knowledge_date, facts)
    return _cached_physics_prediction(visa_class, country, action_type, knowledge_date)


def expert_supply_aware(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Scales historical advancement rate by current supply ratio vs base."""
    current_cutoff = expert_persistence(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    from lib.business.vqs.solver import get_historical_advancement_rate
    from lib.business.vqs.supply import SupplyAllocator

    if knowledge_date.month == 12:
        next_month = date(knowledge_date.year + 1, 1, 1)
    else:
        next_month = date(knowledge_date.year, knowledge_date.month + 1, 1)

    allocator = SupplyAllocator()
    allocation = allocator.get_supply(visa_class, country, next_month, knowledge_date)

    ratio = allocation.total / allocation.base_supply if allocation.base_supply > 0 else 1.0

    pace = get_historical_advancement_rate(visa_class, country, action_type, knowledge_date)
    if pace is not None and pace > 0:
        days_to_add = int(pace * ratio)
        return current_cutoff + timedelta(days=days_to_add)
    return current_cutoff


def expert_demand_signal(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Slows down predictions if recent I-140 demand is spiking."""
    current_cutoff = expert_persistence(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    base_pred = expert_seasonal_median(visa_class, country, action_type, knowledge_date)

    if not base_pred or base_pred <= current_cutoff:
        return current_cutoff

    from models.raw_facts import RawFactsLedger

    if facts is None:
        filtered_facts = list(
            RawFactsLedger.objects.filter(metric="i140_receipts", publication_date__lt=knowledge_date)
        )
    else:
        filtered_facts = facts

    country_facts = [
        f for f in filtered_facts
        if f.metric == "i140_receipts"
        and f.publication_date < knowledge_date
        and str(f.dimensions.get("country")) == str(country)
    ]
    country_facts.sort(key=lambda x: x.reference_period_start)

    if len(country_facts) < 4:
        return current_cutoff

    def get_val(f):
        if isinstance(f.value, list) and len(f.value) > 0:
            return float(f.value[0])
        return float(f.value)

    recent = country_facts[-2:]
    hist_pool = country_facts[:-2]

    recent_avg = sum(get_val(f) for f in recent) / 2
    hist_avg = sum(get_val(f) for f in hist_pool) / len(hist_pool)

    if hist_avg <= 0:
        return current_cutoff

    demand_ratio = recent_avg / hist_avg
    if demand_ratio > 1.1:
        brake = min(0.5, (demand_ratio - 1.0) * 2.0)
        delta = (base_pred - current_cutoff).days * (1.0 - brake)
        return current_cutoff + timedelta(days=int(delta))

    return base_pred


def expert_i485_queue_depth(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Estimates advancement from I-485 pending inventory queue depth.

    Uses the pending count of I-485 applications near the current cutoff
    (within a 3-year priority date window ahead of it) to estimate how
    quickly the cutoff can advance. Thin queue → faster advance; dense
    queue → slower advance.

    Formula:
        estimated_monthly_advance = monthly_supply / queue_density_per_day

    where queue_density_per_day = pending_near_cutoff / window_days.

    Falls back to seasonal_median if insufficient I-485 data.
    """
    current_cutoff = expert_persistence(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    from lib.business.vqs.estimators import get_monthly_supply
    from models.raw_facts import RawFactsLedger

    if facts is None:
        i485_facts = list(
            RawFactsLedger.objects.filter(
                metric="i485_pending_inventory",
                publication_date__lte=knowledge_date,
            ).order_by("-publication_date")
        )
    else:
        i485_facts = [
            f for f in facts
            if f.metric == "i485_pending_inventory"
            and f.publication_date <= knowledge_date
        ]
        i485_facts.sort(key=lambda x: x.publication_date, reverse=True)

    if not i485_facts:
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date)

    # Use most recent inventory snapshot
    # Count pending applications within 3 years ahead of current cutoff
    window_days = 3 * 365
    window_end = current_cutoff + timedelta(days=window_days)

    pending_in_window = 0
    most_recent_date = i485_facts[0].publication_date

    for f in i485_facts:
        if f.publication_date < most_recent_date - timedelta(days=120):
            break
        dims = f.dimensions if isinstance(f.dimensions, dict) else {}
        f_country = dims.get("country")
        f_class = dims.get("visa_class")
        f_pd_str = dims.get("priority_date")

        if f_country is not None and str(f_country) != str(country):
            continue
        if f_class is not None and f_class != visa_class:
            continue
        if not f_pd_str:
            continue

        try:
            from datetime import datetime
            for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                try:
                    f_pd = datetime.strptime(f_pd_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                continue
        except Exception:
            continue

        if current_cutoff <= f_pd <= window_end:
            val = f.value
            if isinstance(val, (list, tuple)) and val:
                val = val[0]
            try:
                pending_in_window += float(val)
            except (TypeError, ValueError):
                pass

    if pending_in_window <= 0:
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date)

    # Estimate queue density: pending applications per day of priority date range
    queue_density_per_day = pending_in_window / window_days

    # Get monthly supply allocation for this series
    monthly_supply = get_monthly_supply(knowledge_date, country=country, visa_class=visa_class)

    # Estimated days of priority date cleared per month = supply / queue_density
    if queue_density_per_day > 0:
        estimated_advance = int(monthly_supply / queue_density_per_day)
    else:
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date)

    # Sanity bounds: cap between -60 and +365 days advance
    estimated_advance = max(-60, min(365, estimated_advance))

    return current_cutoff + timedelta(days=estimated_advance)


# ---------------------------------------------------------------------------
# Expert registry
# ---------------------------------------------------------------------------

def expert_cross_series(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Predicts using EB-1 movement as a leading indicator for EB-2/3.

    Rationale: Unused EB-1 visas spill to EB-2, then to EB-3. When EB-1
    advances, the spillover budget for EB-2/3 often follows within 1-2 months.
    Conversely, EB-1 retrogression signals tightening supply.

    Only applies to EB-2 and EB-3 for India and China (physics-eligible).
    For EB-1 or non-oversubscribed series: falls back to seasonal_median.

    Signal: if EB-1 (same country) moved by X days last month, scale the
    seasonal_median prediction up or down by a fraction of X.
    """
    from models.enums.country import Country as CountryEnum

    oversubscribed_eb23 = frozenset([
        (CountryEnum.INDIA.value, "2nd"), (CountryEnum.INDIA.value, "3rd"),
        (CountryEnum.CHINA.value, "2nd"), (CountryEnum.CHINA.value, "3rd"),
    ])

    if (country, visa_class) not in oversubscribed_eb23:
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date, facts)

    # EB-1 same country last month move
    eb1_moves = get_last_N_moves("1st", country, action_type, knowledge_date, 3)
    if not eb1_moves:
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date, facts)

    eb1_recent_avg = sum(eb1_moves[:3]) / len(eb1_moves[:3])

    # Base prediction from seasonal median
    base_pred = expert_seasonal_median(visa_class, country, action_type, knowledge_date, facts)
    current_cutoff = expert_persistence(visa_class, country, action_type, knowledge_date, facts)

    if not base_pred or not current_cutoff:
        return base_pred

    base_move = (base_pred - current_cutoff).days

    # Cross-series adjustment: blend 20% of EB-1 signal into prediction
    cross_series_weight = 0.20
    adjusted_move = int(base_move * (1.0 - cross_series_weight) + eb1_recent_avg * cross_series_weight)

    return current_cutoff + timedelta(days=adjusted_move)


def _expert_gbm_wrapper(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Lazy import wrapper for GBM expert to keep dependency optional."""
    try:
        from lib.business.vqs.gbm_expert import expert_gbm
        return expert_gbm(visa_class, country, action_type, knowledge_date, facts)
    except ImportError:
        return expert_seasonal_median(visa_class, country, action_type, knowledge_date, facts)


ALL_EXPERTS = {
    "persistence": expert_persistence,
    "seasonal_median": expert_seasonal_median,
    "linear_extrap": expert_linear_extrap,
    "momentum_3m": expert_momentum_3m,
    "fy_reset": expert_fy_reset,
    "physics": expert_physics,
    "supply_aware": expert_supply_aware,
    "demand_signal": expert_demand_signal,
    "i485_queue_depth": expert_i485_queue_depth,
    "cross_series": expert_cross_series,
    "gbm": _expert_gbm_wrapper,
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_pace(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, lookback_days: int,
) -> float | None:
    """Extract monthly pace (days/month) from trailing cutoff history."""
    start = knowledge_date - timedelta(days=lookback_days)
    all_up_to = get_cutoffs_up_to(visa_class, country, action_type, knowledge_date - timedelta(days=1))
    window = [c for c in all_up_to if c.bulletin.publication_date >= start]
    if len(window) < 2:
        return None
    first, last = window[0], window[-1]
    months = (
        (last.bulletin.publication_date.year - first.bulletin.publication_date.year) * 12
        + (last.bulletin.publication_date.month - first.bulletin.publication_date.month)
    )
    if months < 1:
        months = 1
    return (last.cutoff_date - first.cutoff_date).days / months


def _pace_prediction(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, lookback_days: int,
) -> date | None:
    """Single-step prediction using linear pace extrapolation."""
    current = expert_persistence(visa_class, country, action_type, knowledge_date)
    pace = _get_pace(visa_class, country, action_type, knowledge_date, lookback_days)
    if current is None or pace is None:
        return None
    return current + timedelta(days=int(pace))


# ---------------------------------------------------------------------------
# Multi-step trajectory functions
# ---------------------------------------------------------------------------

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
            knowledge_date=knowledge_date, target_month=target_month, min_samples=3,
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


def trajectory_cross_series(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    """Multi-step trajectory blending 20% EB-1 movement signal into seasonal median.

    Uses historical EB-1 average as a fixed cross-series signal for all forward steps
    (we don't project EB-1 forward separately for multi-step, so the same recent EB-1
    average modulates each step). Falls back to seasonal_median for EB-1 or non-
    oversubscribed series.
    """
    from models.enums.country import Country as CountryEnum

    oversubscribed_eb23 = frozenset([
        (CountryEnum.INDIA.value, "2nd"), (CountryEnum.INDIA.value, "3rd"),
        (CountryEnum.CHINA.value, "2nd"), (CountryEnum.CHINA.value, "3rd"),
    ])

    if (country, visa_class) not in oversubscribed_eb23:
        return _seasonal_chain_trajectory(visa_class, country, action_type, knowledge_date, steps)

    eb1_moves = get_last_N_moves("1st", country, action_type, knowledge_date, 3)
    if not eb1_moves:
        return _seasonal_chain_trajectory(visa_class, country, action_type, knowledge_date, steps)

    eb1_recent_avg = sum(eb1_moves[:3]) / len(eb1_moves[:3])

    current = expert_persistence(visa_class, country, action_type, knowledge_date)
    if current is None:
        return [None] * steps

    cross_series_weight = 0.20
    trajectory: list[date | None] = []
    cutoff = current

    for i in range(steps):
        target_month = ((knowledge_date.month + i) % 12) + 1
        move = get_seasonal_prediction(
            visa_class, country, action_type,
            knowledge_date=knowledge_date, target_month=target_month, min_samples=3,
        )
        base_move = move if move is not None else 0
        adjusted_move = int(base_move * (1.0 - cross_series_weight) + eb1_recent_avg * cross_series_weight)
        cutoff = cutoff + timedelta(days=adjusted_move)
        trajectory.append(cutoff)

    return trajectory


def trajectory_fy_reset(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, steps: int = 12, facts: list | None = None,
) -> list[date | None]:
    """Full FY cycle: Oct retrogression, Q1 recovery, Q2-Q4 seasonal pace."""
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
        else:
            move = get_seasonal_prediction(
                visa_class, country, action_type,
                knowledge_date=knowledge_date, target_month=target_month, min_samples=3,
            )
            if move is not None:
                cutoff = cutoff + timedelta(days=move)
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
    calibrate_queue_depth(queue, current, knowledge_date, supply, visa_class, country, action_type)
    results: list[date | None] = []
    for res in run_monthly_loop(queue, current, supply, start_month=knowledge_date, max_months=steps):
        results.append(res.cutoff_date)
    while len(results) < steps:
        results.append(results[-1] if results else None)
    return results


ALL_EXPERT_TRAJECTORIES = {
    "persistence": trajectory_persistence,
    "seasonal_median": trajectory_seasonal_median,
    "linear_extrap": trajectory_linear_extrap,
    "momentum_3m": trajectory_momentum_3m,
    "fy_reset": trajectory_fy_reset,
    "physics": trajectory_physics,
    "supply_aware": trajectory_linear_extrap,
    "demand_signal": trajectory_seasonal_median,
    # single-step experts: use best available multi-step fallback
    "i485_queue_depth": trajectory_seasonal_median,
    "cross_series": trajectory_cross_series,
    "gbm": trajectory_seasonal_median,
}
