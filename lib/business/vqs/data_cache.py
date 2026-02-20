"""
Data Cache for VQS Online Simulation.

Loads Bulletin and VisaCutoffDate objects into memory once to avoid N+1 queries
during high-frequency expert evaluation loops.
"""
from typing import List, Dict, Tuple
from datetime import date
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate

# Cache for Bulletins: ordered list by publication_date
_BULLETIN_CACHE: List[Bulletin] | None = None

# Cache for Cutoffs: (visa_class, country, action_type) -> ordered list of VisaCutoffDate
_CUTOFF_CACHE: Dict[Tuple[str, int, str], List[VisaCutoffDate]] = {}


def get_all_bulletins() -> List[Bulletin]:
    """Return all bulletins ordered by publication_date (cached)."""
    global _BULLETIN_CACHE
    if _BULLETIN_CACHE is None:
        _BULLETIN_CACHE = list(Bulletin.objects.order_by("publication_date"))
    return _BULLETIN_CACHE


def get_cutoffs_for_series(visa_class: str, country: int, action_type: str) -> list[VisaCutoffDate]:
    """
    Get all historical cutoffs for a specific series, ordered by bulletin date.
    Cached in memory.
    """
    key = (visa_class, country, action_type)
    if key not in _CUTOFF_CACHE:
        # Populate cache
        qs = VisaCutoffDate.objects.filter(
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            cutoff_date__isnull=False
        ).select_related("bulletin").order_by("bulletin__publication_date")
        _CUTOFF_CACHE[key] = list(qs)
    return _CUTOFF_CACHE[key]


def get_cutoff_at_date(
    visa_class: str,
    country: int,
    action_type: str,
    as_of: date,
) -> date | None:
    """
    Return the actual Visa Bulletin cutoff date at as_of for the given series.

    Uses Bulletin and VisaCutoffDate: finds the latest bulletin with publication_date <= as_of,
    then returns cutoff_date for (visa_class, country, action_type). Returns None if no data.
    """
    # Optimized: use the cache instead of hitting DB every time
    cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    
    # Linear scan backwards to find latest bulletin <= as_of
    for i in range(len(cutoffs) - 1, -1, -1):
        if cutoffs[i].bulletin.publication_date <= as_of:
            return cutoffs[i].cutoff_date
            
    return None
