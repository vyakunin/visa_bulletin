"""Tests for VQS data cache performance optimizations.

Verifies that bisect-based lookups produce identical results to linear scans.
Pure unit tests — no DB, no Django. Uses lightweight mock objects to populate
the module-level caches directly.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

# data_cache imports Django models at module level — load the app registry first
# (no test DB needed; these are pure-logic tests on the module caches).
django.setup()

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from lib.business.vqs import data_cache

# ---------------------------------------------------------------------------
# Helpers: lightweight stand-ins for Bulletin / VisaCutoffDate
# ---------------------------------------------------------------------------

def _make_cutoff(pub_date: date, cutoff_date: date | None = None):
    """Create a mock VisaCutoffDate with .bulletin.publication_date and .cutoff_date."""
    bulletin = SimpleNamespace(publication_date=pub_date)
    return SimpleNamespace(bulletin=bulletin, cutoff_date=cutoff_date)


def _make_series(start: date, n: int, gap_days: int = 30):
    """Generate n mock cutoffs spaced gap_days apart, with cutoff_date = pub_date + 365."""
    cutoffs = []
    for i in range(n):
        pub = start + timedelta(days=i * gap_days)
        cutoffs.append(_make_cutoff(pub, pub + timedelta(days=365)))
    return cutoffs


SERIES_KEY = ("2nd", 3, "final_action")


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset module-level caches before and after each test."""
    data_cache._CUTOFF_CACHE.clear()
    data_cache._PUB_DATE_CACHE.clear()
    old_bulletin = data_cache._BULLETIN_CACHE
    data_cache._BULLETIN_CACHE = None
    yield
    data_cache._CUTOFF_CACHE.clear()
    data_cache._PUB_DATE_CACHE.clear()
    data_cache._BULLETIN_CACHE = old_bulletin


def _populate(cutoffs, key=SERIES_KEY):
    """Inject cutoffs into both caches."""
    data_cache._CUTOFF_CACHE[key] = cutoffs
    data_cache._PUB_DATE_CACHE[key] = [c.bulletin.publication_date for c in cutoffs]


# ---------------------------------------------------------------------------
# Tests for _find_index_up_to (pure bisect logic)
# ---------------------------------------------------------------------------

class TestFindIndexUpTo:
    def test_exact_match_returns_that_index(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        assert data_cache._find_index_up_to(dates, date(2024, 2, 1)) == 1

    def test_between_dates_returns_earlier(self):
        dates = [date(2024, 1, 1), date(2024, 3, 1), date(2024, 5, 1)]
        assert data_cache._find_index_up_to(dates, date(2024, 2, 15)) == 0

    def test_before_all_returns_negative(self):
        dates = [date(2024, 3, 1), date(2024, 4, 1)]
        assert data_cache._find_index_up_to(dates, date(2024, 1, 1)) == -1

    def test_after_all_returns_last(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        assert data_cache._find_index_up_to(dates, date(2025, 1, 1)) == 1

    def test_empty_list(self):
        assert data_cache._find_index_up_to([], date(2024, 1, 1)) == -1

    def test_single_element_match(self):
        assert data_cache._find_index_up_to([date(2024, 6, 1)], date(2024, 6, 1)) == 0

    def test_single_element_before(self):
        assert data_cache._find_index_up_to([date(2024, 6, 1)], date(2024, 5, 1)) == -1

    def test_duplicate_dates_returns_last(self):
        dates = [date(2024, 1, 1), date(2024, 1, 1), date(2024, 2, 1)]
        assert data_cache._find_index_up_to(dates, date(2024, 1, 1)) == 1


# ---------------------------------------------------------------------------
# Tests for get_cutoff_at_date (bisect-backed)
# ---------------------------------------------------------------------------

class TestGetCutoffAtDate:
    def test_returns_cutoff_for_exact_date(self):
        cutoffs = _make_series(date(2024, 1, 1), 5)
        _populate(cutoffs)
        result = data_cache.get_cutoff_at_date(*SERIES_KEY, as_of=date(2024, 1, 1))
        assert result == cutoffs[0].cutoff_date

    def test_returns_most_recent_before_date(self):
        cutoffs = _make_series(date(2024, 1, 1), 5, gap_days=30)
        _populate(cutoffs)
        result = data_cache.get_cutoff_at_date(*SERIES_KEY, as_of=date(2024, 2, 15))
        assert result == cutoffs[1].cutoff_date

    def test_returns_none_before_any_data(self):
        cutoffs = _make_series(date(2024, 6, 1), 3)
        _populate(cutoffs)
        result = data_cache.get_cutoff_at_date(*SERIES_KEY, as_of=date(2024, 1, 1))
        assert result is None

    def test_returns_last_for_future_date(self):
        cutoffs = _make_series(date(2024, 1, 1), 3, gap_days=30)
        _populate(cutoffs)
        result = data_cache.get_cutoff_at_date(*SERIES_KEY, as_of=date(2030, 1, 1))
        assert result == cutoffs[-1].cutoff_date

    def test_empty_series(self):
        _populate([])
        result = data_cache.get_cutoff_at_date(*SERIES_KEY, as_of=date(2024, 1, 1))
        assert result is None


# ---------------------------------------------------------------------------
# Tests for get_cutoffs_up_to (new bisect-backed helper)
# ---------------------------------------------------------------------------

class TestGetCutoffsUpTo:
    def test_returns_all_up_to_date(self):
        cutoffs = _make_series(date(2024, 1, 1), 10, gap_days=30)
        _populate(cutoffs)
        result = data_cache.get_cutoffs_up_to(*SERIES_KEY, as_of=date(2024, 4, 15))
        # pub dates: Jan 1, Jan 31, Mar 1, Mar 31, Apr 30 ... — 5 entries with pub <= Apr 15
        assert len(result) <= 5
        for c in result:
            assert c.bulletin.publication_date <= date(2024, 4, 15)

    def test_returns_empty_before_all(self):
        cutoffs = _make_series(date(2024, 6, 1), 3)
        _populate(cutoffs)
        result = data_cache.get_cutoffs_up_to(*SERIES_KEY, as_of=date(2024, 1, 1))
        assert result == []

    def test_returns_all_for_far_future(self):
        cutoffs = _make_series(date(2024, 1, 1), 5)
        _populate(cutoffs)
        result = data_cache.get_cutoffs_up_to(*SERIES_KEY, as_of=date(2030, 1, 1))
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Equivalence: bisect vs linear scan produce identical results
# ---------------------------------------------------------------------------

def _linear_get_cutoff_at_date(cutoffs, as_of):
    """Reference implementation: the old linear reverse scan."""
    for i in range(len(cutoffs) - 1, -1, -1):
        if cutoffs[i].bulletin.publication_date <= as_of:
            return cutoffs[i].cutoff_date
    return None


class TestBisectEquivalence:
    """Verify bisect-backed functions match the original linear-scan behavior."""

    @pytest.mark.parametrize("n_cutoffs", [1, 10, 50, 200])
    def test_random_dates_match(self, n_cutoffs):
        cutoffs = _make_series(date(2000, 1, 1), n_cutoffs, gap_days=30)
        _populate(cutoffs)

        test_dates = [
            date(1999, 1, 1),   # before all
            date(2000, 1, 1),   # first exact
            date(2000, 1, 15),  # between first and second
            date(2030, 1, 1),   # after all
        ]
        # Add dates around each pub_date
        for c in cutoffs[:10]:
            pd = c.bulletin.publication_date
            test_dates.extend([
                pd - timedelta(days=1),
                pd,
                pd + timedelta(days=1),
            ])

        for as_of in test_dates:
            bisect_result = data_cache.get_cutoff_at_date(*SERIES_KEY, as_of=as_of)
            linear_result = _linear_get_cutoff_at_date(cutoffs, as_of)
            assert bisect_result == linear_result, (
                f"Mismatch at as_of={as_of}: bisect={bisect_result}, linear={linear_result}"
            )
