"""
Data Cache for VQS Online Simulation.

Loads Bulletin and VisaCutoffDate objects into memory once to avoid N+1 queries
during high-frequency expert evaluation loops.

Performance: all lookups by date use bisect (O(log n)) instead of linear scans.
A parallel _PUB_DATE_CACHE stores extracted publication dates for each series
so bisect_right can operate on a flat list of dates.
"""

import bisect
from datetime import date

# Cache for Bulletins: ordered list by publication_date
_BULLETIN_CACHE: list | None = None

# Cache for Cutoffs: (visa_class, country, action_type) -> ordered list of VisaCutoffDate
_CUTOFF_CACHE: dict[tuple[str, int, str], list] = {}

# Parallel cache: same key -> sorted list of publication_date values for O(log n) bisect
_PUB_DATE_CACHE: dict[tuple[str, int, str], list[date]] = {}

# Cache for is_current checks: includes ALL entries (even null cutoff_date)
_CURRENT_CACHE: dict[tuple[str, int, str], list] = {}
_CURRENT_PUB_DATES: dict[tuple[str, int, str], list[date]] = {}


def _find_index_up_to(pub_dates: list[date], as_of: date) -> int:
    """Return index of the last entry with publication_date <= as_of, or -1 if none.

    O(log n) via bisect on the sorted pub_dates list.
    """
    idx = bisect.bisect_right(pub_dates, as_of)
    return idx - 1


def get_all_bulletins() -> list:
    """Return all bulletins ordered by publication_date (cached)."""
    from models.bulletin import Bulletin

    global _BULLETIN_CACHE
    if _BULLETIN_CACHE is None:
        _BULLETIN_CACHE = list(Bulletin.objects.order_by("publication_date"))
    return _BULLETIN_CACHE


def get_cutoffs_for_series(
    visa_class: str, country: int, action_type: str
) -> list:
    """
    Get all historical cutoffs for a specific series, ordered by bulletin date.
    Cached in memory. Also populates _PUB_DATE_CACHE for bisect lookups.
    """
    from models.visa_cutoff_date import VisaCutoffDate

    key = (visa_class, country, action_type)
    if key not in _CUTOFF_CACHE:
        qs = (
            VisaCutoffDate.objects.filter(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                cutoff_date__isnull=False,
            )
            .select_related("bulletin")
            .order_by("bulletin__publication_date")
        )
        cutoffs = list(qs)
        _CUTOFF_CACHE[key] = cutoffs
        _PUB_DATE_CACHE[key] = [c.bulletin.publication_date for c in cutoffs]
    return _CUTOFF_CACHE[key]


def _get_pub_dates(visa_class: str, country: int, action_type: str) -> list[date]:
    """Return sorted publication dates for the series (populates cache if needed)."""
    key = (visa_class, country, action_type)
    if key not in _PUB_DATE_CACHE:
        get_cutoffs_for_series(visa_class, country, action_type)
    return _PUB_DATE_CACHE[key]


def get_cutoff_at_date(
    visa_class: str,
    country: int,
    action_type: str,
    as_of: date,
) -> date | None:
    """
    Return the actual Visa Bulletin cutoff date at as_of for the given series.

    Finds the latest bulletin with publication_date <= as_of via O(log n) bisect,
    then returns cutoff_date for (visa_class, country, action_type). Returns None if no data.
    """
    cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    pub_dates = _get_pub_dates(visa_class, country, action_type)
    idx = _find_index_up_to(pub_dates, as_of)
    if idx < 0:
        return None
    return cutoffs[idx].cutoff_date


def is_current_at_date(
    visa_class: str,
    country: int,
    action_type: str,
    as_of: date,
) -> bool:
    """Return True if the series was 'Current' (no meaningful cutoff) at as_of.

    Checks the latest VisaCutoffDate row (including null cutoff_date entries)
    with publication_date <= as_of. If that row has is_current=True, the series
    had no backlog and predictions are meaningless.

    Uses a separate cache (_CURRENT_CACHE) to avoid modifying the non-null
    cutoff cache used by the rest of the solver.
    """
    from models.visa_cutoff_date import VisaCutoffDate

    key = (visa_class, country, action_type)
    if key not in _CURRENT_CACHE:
        # Load ALL entries (including null cutoff_date) for this series
        qs = (
            VisaCutoffDate.objects.filter(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
            )
            .select_related("bulletin")
            .order_by("bulletin__publication_date")
        )
        entries = list(qs)
        _CURRENT_CACHE[key] = entries
        _CURRENT_PUB_DATES[key] = [e.bulletin.publication_date for e in entries]

    pub_dates = _CURRENT_PUB_DATES.get(key, [])
    entries = _CURRENT_CACHE.get(key, [])
    idx = _find_index_up_to(pub_dates, as_of)
    if idx < 0:
        return False
    return entries[idx].is_current


def get_cutoffs_up_to(
    visa_class: str,
    country: int,
    action_type: str,
    as_of: date,
) -> list:
    """Return all cutoffs with publication_date <= as_of. O(log n) via bisect."""
    cutoffs = get_cutoffs_for_series(visa_class, country, action_type)
    pub_dates = _get_pub_dates(visa_class, country, action_type)
    idx = _find_index_up_to(pub_dates, as_of)
    if idx < 0:
        return []
    return cutoffs[: idx + 1]
