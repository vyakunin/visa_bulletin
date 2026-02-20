"""Historical Seasonal Predictor for VQS.

Computes the median monthly cutoff movement per (visa_class, country, action_type, month_of_year)
from historical bulletin data. Walk-forward safe: only uses data before knowledge_date.

This is a statistical baseline that captures seasonal patterns (October retrogression,
September acceleration) without relying on the physics engine.
"""

import logging
from datetime import date
from statistics import median
from collections import defaultdict

from models.visa_cutoff_date import VisaCutoffDate
from lib.business.vqs.data_cache import get_cutoffs_for_series

logger = logging.getLogger(__name__)


def get_seasonal_prediction(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    target_month: int,
    min_samples: int = 3,
) -> int | None:
    """
    Predict cutoff movement (days) for a given month-of-year using historical median.

    Args:
        visa_class: e.g. "2nd"
        country: Country enum value
        action_type: e.g. "final_action"
        knowledge_date: Only use bulletins published before this date (walk-forward safe).
        target_month: Month of year (1-12) of the bulletin we're predicting.
        min_samples: Minimum historical samples required. Returns None if insufficient.

    Returns:
        Predicted movement in days (positive = forward, negative = retrogression).
        None if insufficient historical data.
    """
    # Get all cutoff dates for this series from cache
    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    
    # Filter by knowledge_date (binary search could be faster but linear scan is fine for N<200)
    # Actually, we can just slice list since it is ordered
    cutoffs = []
    for c in all_cutoffs:
        if c.bulletin.publication_date < knowledge_date:
            cutoffs.append(c)
        else:
            break

    if len(cutoffs) < 2:
        return None

    # Compute month-to-month movements, grouped by target month
    movements_by_month: dict[int, list[int]] = defaultdict(list)
    for i in range(1, len(cutoffs)):
        prev = cutoffs[i - 1]
        curr = cutoffs[i]
        bulletin_month = curr.bulletin.publication_date.month
        movement_days = (curr.cutoff_date - prev.cutoff_date).days
        movements_by_month[bulletin_month].append(movement_days)

    movements = movements_by_month.get(target_month, [])
    if len(movements) < min_samples:
        return None

    med = int(median(movements))
    return med


def get_seasonal_prediction_filtered(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    target_month: int,
    regime: str = "all",  # "all", "advancing", "retrogressing"
    min_samples: int = 3,
) -> int | None:
    """Predict cutoff movement filtering by regime (advancing/retrogressing)."""
    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    
    # Filter by knowledge_date
    cutoffs = []
    for c in all_cutoffs:
        if c.bulletin.publication_date < knowledge_date:
            cutoffs.append(c)
        else:
            break

    if len(cutoffs) < 3:
        return None

    movements = []
    for i in range(2, len(cutoffs)):
        prev_prev = cutoffs[i - 2]
        prev = cutoffs[i - 1]
        curr = cutoffs[i]
        
        # Determine regime based on PREVIOUS month's movement
        # (This is the info we'd have at prediction time)
        prev_move = (prev.cutoff_date - prev_prev.cutoff_date).days
        is_retro = prev_move < 0
        
        if regime == "retrogressing" and not is_retro:
            continue
        if regime == "advancing" and is_retro:
            continue
            
        # If regime matches, record THIS month's movement
        if curr.bulletin.publication_date.month == target_month:
            movements.append((curr.cutoff_date - prev.cutoff_date).days)

    if len(movements) < min_samples:
        return None

    return int(median(movements))


def get_median_october_retrogression(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
) -> int:
    """Return median retrogression days for Oct bulletins (Sep->Oct step)."""
    # Reuse generic logic targeting month 10
    move = get_seasonal_prediction(visa_class, country, action_type, knowledge_date, 10, min_samples=2)
    return -move if move and move < 0 else 0


def get_median_post_retro_recovery(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    target_month: int,
) -> int:
    """Return median recovery days for Nov/Dec/Jan after an Oct retrogression."""
    # Logic: Only count years where Oct retrogressed?
    # For simplicity, just return seasonal median for target month, BUT
    # we could filter for years with Oct retrogression.
    # Let's use the generic seasonal median first.
    move = get_seasonal_prediction(visa_class, country, action_type, knowledge_date, target_month, min_samples=2)
    return move if move and move > 0 else 0


def get_last_N_moves(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    n: int
) -> list[int]:
    """Return list of last N monthly movements (days) before knowledge_date."""
    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    cutoffs = [c for c in all_cutoffs if c.bulletin.publication_date < knowledge_date]
    
    if len(cutoffs) < 2:
        return []
        
    moves = []
    # Iterate backwards
    for i in range(len(cutoffs) - 1, 0, -1):
        if len(moves) >= n:
            break
        curr = cutoffs[i]
        prev = cutoffs[i-1]
        moves.append((curr.cutoff_date - prev.cutoff_date).days)
        
    return moves


def get_historical_issuance_median(
    visa_class: str,
    country: int,
    target_month: int,
    knowledge_date: date,
    facts: list | None = None,
    min_samples: int = 3,
) -> float | None:
    """
    Predict monthly visa issuance using historical median.
    
    Uses RawFactsLedger data (source=DOS_ISSUANCE, metric='visa_issuance_monthly')
    published before knowledge_date.
    """
    if facts is None:
        # Avoid circular import
        from models.raw_facts import RawFactsLedger
        # Query DB if facts not provided (expensive but safer if not in backtest)
        filtered_facts = list(RawFactsLedger.objects.filter(
            metric="visa_issuance_monthly",
            publication_date__lt=knowledge_date
        ))
    else:
        filtered_facts = facts

    # Filter by dimensions and month
    # Facts in ledger have dimensions like {"country": 1, "visa_class": "1st"}
    # Value is usually [number] (json list)
    values = []
    for f in filtered_facts:
        if f.metric != "visa_issuance_monthly":
            continue
        if f.publication_date >= knowledge_date:
            continue
            
        dims = f.dimensions
        if str(dims.get("country")) != str(country):
            continue
        if str(dims.get("visa_class")) != str(visa_class):
            continue
            
        if f.reference_period_start.month != target_month:
            continue
            
        # Extract value
        val = f.value
        if isinstance(val, list) and len(val) > 0:
            values.append(float(val[0]))
        elif isinstance(val, (int, float)):
            values.append(float(val))

    if len(values) < min_samples:
        return None
        
    return float(median(values))
