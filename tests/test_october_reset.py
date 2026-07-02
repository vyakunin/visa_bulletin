"""Tests for the October-reset / U-transition estimator.

Locks the design decisions made from the backtest (scripts/vqs/backtest_october_reset.py):
the estimate is a *structural* statement (stays Unavailable through September,
resets October 1) anchored on the pre-Unavailable cutoff — NOT a fitted point
model (which regressed in §8) and NOT a false-precise date. Walk-forward safety:
only precedents whose reset already published are pooled.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.vqs import data_cache
from lib.business.vqs.october_reset import (
    describe_reset,
    estimate_from_precedents,
    estimate_october_reset,
    find_reset_events,
)
from models.bulletin import Bulletin
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate


def _row(bulletin, country, visa_class, cutoff_date, *, unavailable=False, current=False):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class=visa_class,
        action_type="final_action",
        country=country,
        cutoff_value=(cutoff_date.strftime("%d%b%y").upper() if cutoff_date else ("U" if unavailable else "C")),
        cutoff_date=cutoff_date,
        is_current=current,
        is_unavailable=unavailable,
    )


def _clear_caches():
    # data_cache holds module-global caches keyed by series; a prior test's rows
    # would otherwise mask this test's series.
    data_cache._BULLETIN_CACHE = None
    for d in (
        data_cache._CUTOFF_CACHE,
        data_cache._PUB_DATE_CACHE,
        data_cache._CURRENT_CACHE,
        data_cache._CURRENT_PUB_DATES,
    ):
        d.clear()


class TestOctoberReset(TestCase):
    def setUp(self):
        _clear_caches()
        self.india = Country.INDIA.value
        self.china = Country.CHINA.value

        def bul(y, m):
            return Bulletin.objects.create(publication_date=date(y, m, 1))

        # --- Precedent event: EB-3 China FY2018 (resolves before FY2020) ---
        _row(bul(2018, 5), self.china, "3rd", date(2010, 1, 1))          # pre-U
        for m in (7, 8, 9):
            _row(bul(2018, m), self.china, "3rd", None, unavailable=True)  # end-of-FY U
        _row(bul(2018, 11), self.china, "3rd", date(2009, 6, 1))         # reset (retrogressed)

        # --- Subject event: EB-2 India FY2020 (the case under test) ---
        _row(bul(2020, 5), self.india, "2nd", date(2015, 1, 1))          # pre-U
        for m in (6, 7, 8, 9):
            _row(bul(2020, m), self.india, "2nd", None, unavailable=True)  # end-of-FY U
        _row(bul(2020, 11), self.india, "2nd", date(2013, 1, 1))         # reset (retrogressed)

    def test_find_reset_events_labels_pre_u_and_reset(self):
        events = find_reset_events("final_action")
        by_key = {(e.visa_class, e.country, e.spell_fy): e for e in events}
        eb2in = by_key[("2nd", self.india, 2020)]
        self.assertEqual(eb2in.pre_u_cutoff, date(2015, 1, 1))
        self.assertEqual(eb2in.reset_cutoff, date(2013, 1, 1))
        self.assertEqual(eb2in.reset_pub_date, date(2020, 11, 1))
        self.assertLess(eb2in.delta_days, 0)  # retrogressed on reset
        eb3cn = by_key[("3rd", self.china, 2018)]
        self.assertEqual(eb3cn.pre_u_cutoff, date(2010, 1, 1))
        self.assertEqual(eb3cn.reset_cutoff, date(2009, 6, 1))

    def test_estimate_is_structural_and_anchored(self):
        est = estimate_october_reset("2nd", self.india, "final_action", date(2020, 8, 1))
        self.assertTrue(est.is_unavailable)
        self.assertEqual(est.reset_year, 2020)          # Oct 1, 2020 opens new FY
        self.assertEqual(est.pre_u_cutoff, date(2015, 1, 1))
        self.assertEqual(est.point, date(2015, 1, 1))   # pure anchor, no fitted shift
        self.assertEqual(est.method, "anchor")

    def test_walk_forward_excludes_future_precedents(self):
        # As of Aug 2020, only the EB-3 China FY2018 reset (Nov 2018) has published.
        est = estimate_october_reset("2nd", self.india, "final_action", date(2020, 8, 1))
        self.assertEqual(est.n_precedents, 1)

    def test_not_unavailable_returns_false(self):
        # Before the series ever went Unavailable, the estimator declines.
        est = estimate_october_reset("2nd", self.india, "final_action", date(2019, 8, 1))
        self.assertFalse(est.is_unavailable)

    def test_median_shift_off_by_default_but_changes_point_when_on(self):
        events = find_reset_events("final_action")
        precedents = [e for e in events if e.reset_pub_date < date(2020, 8, 1)]
        anchor = estimate_from_precedents(date(2015, 1, 1), 2020, precedents, apply_median_shift=False)
        shifted = estimate_from_precedents(date(2015, 1, 1), 2020, precedents, apply_median_shift=True)
        self.assertEqual(anchor.point, date(2015, 1, 1))
        # The single precedent retrogressed, so the shift moves the point earlier.
        self.assertLess(shifted.point, date(2015, 1, 1))

    def test_describe_reset_is_honest(self):
        est = estimate_october_reset("2nd", self.india, "final_action", date(2020, 8, 1))
        text = describe_reset(est, "EB-2 India")
        self.assertIn("Unavailable", text)
        self.assertIn("September 2020", text)
        self.assertIn("October 1, 2020", text)
        self.assertIn("rough guess", text)          # honest uncertainty
        self.assertIn("January 1, 2015", text)       # pre-U reference date
