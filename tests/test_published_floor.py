"""Tests for PublishedFloor and its effect on the October-reset estimate.

A bulletin's notes section can state a lower bound on a FUTURE month's cutoff
("in October the final action date will advance to at least the final action date
announced in the May 2026 Visa Bulletin"). The reset estimator is an empirical
distribution over past October resets and cannot see prose, so without a floor it
happily publishes a forecast the State Department has already contradicted.

The shape under test is the live one: EB-2 India went Unavailable in July 2026
with a pre-U anchor of 2013-09-01, while the July bulletin published a floor of
2014-07-15 — a date the pooled precedent distribution puts in its top decile.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.vqs import data_cache
from lib.business.vqs.october_reset import describe_reset, estimate_october_reset
from models.bulletin import Bulletin
from models.enums.country import Country
from models.published_floor import PublishedFloor
from models.visa_cutoff_date import VisaCutoffDate

FLOOR = date(2014, 7, 15)  # May 2026 bulletin's EB-2 India final action date
ANCHOR = date(2013, 9, 1)  # June 2026 EB-2 India final action, the last pre-U value

# Verbatim July 2026 Visa Bulletin, section F.
QUOTE = (
    "It is likely that in October the final action date will advance to at least "
    "the final action date announced in the May 2026 Visa Bulletin; however, the "
    "date is dependent on the demand for EB-2 numbers by Indian applicants and the "
    "FY 2027 annual limit on employment-based preference visas."
)


def _row(bulletin, country, visa_class, cutoff_date, *, unavailable=False):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class=visa_class,
        action_type="final_action",
        country=country,
        cutoff_value=(
            cutoff_date.strftime("%d%b%y").upper() if cutoff_date else ("U" if unavailable else "C")
        ),
        cutoff_date=cutoff_date,
        is_unavailable=unavailable,
    )


def _clear_caches():
    data_cache._BULLETIN_CACHE = None
    for d in (
        data_cache._CUTOFF_CACHE,
        data_cache._PUB_DATE_CACHE,
        data_cache._CURRENT_CACHE,
        data_cache._CURRENT_PUB_DATES,
    ):
        d.clear()


class TestPublishedFloorReset(TestCase):
    def setUp(self):
        _clear_caches()
        self.india = Country.INDIA.value
        self.china = Country.CHINA.value
        self.bulletins: dict[tuple[int, int], Bulletin] = {}

        # --- Precedents: past resets that all landed BELOW the floor, so the
        # pooled distribution alone would contradict the published statement.
        _row(self.bul(2018, 5), self.china, "3rd", date(2010, 1, 1))
        for m in (7, 8, 9):
            _row(self.bul(2018, m), self.china, "3rd", None, unavailable=True)
        _row(self.bul(2018, 11), self.china, "3rd", date(2007, 1, 1))  # −3y retrogression

        _row(self.bul(2019, 5), self.china, "2nd", date(2012, 1, 1))
        for m in (7, 8, 9):
            _row(self.bul(2019, m), self.china, "2nd", None, unavailable=True)
        _row(self.bul(2019, 11), self.china, "2nd", date(2011, 6, 1))

        # --- Subject: EB-2 India, anchored at 2013-09-01, Unavailable from July.
        _row(self.bul(2026, 6), self.india, "2nd", ANCHOR)
        _row(self.bul(2026, 7), self.india, "2nd", None, unavailable=True)

    def bul(self, y, m):
        key = (y, m)
        if key not in self.bulletins:
            self.bulletins[key] = Bulletin.objects.create(publication_date=date(y, m, 1))
        return self.bulletins[key]

    def record_floor(self, source=(2026, 7), floor_date=FLOOR, target=date(2026, 10, 1)):
        return PublishedFloor.objects.create(
            source_bulletin=self.bul(*source),
            target_period=target,
            visa_category="employment_based",
            visa_class="2nd",
            action_type="final_action",
            country=self.india,
            floor_date=floor_date,
            source_quote=QUOTE,
            source_section="F",
        )

    def estimate(self, knowledge_date=date(2026, 7, 31)):
        return estimate_october_reset("2nd", self.india, "final_action", knowledge_date)

    # ---- the defect this ticket is about -------------------------------------

    def test_without_a_floor_the_estimate_sits_below_the_published_bound(self):
        """Baseline: the pooled precedent model puts the whole forecast under the floor."""
        est = self.estimate()
        self.assertTrue(est.is_unavailable)
        self.assertEqual(est.pre_u_cutoff, ANCHOR)
        self.assertLess(est.point, FLOOR)
        self.assertLess(est.ci_high, FLOOR)  # the floor is beyond our best case

    def test_recorded_floor_clamps_the_point_estimate(self):
        self.record_floor()
        est = self.estimate()
        self.assertGreaterEqual(est.point, FLOOR)

    def test_recorded_floor_clamps_the_interval(self):
        """The published range must not put mass below a bound DOS published."""
        self.record_floor()
        est = self.estimate()
        self.assertGreaterEqual(est.ci_low, FLOOR)
        self.assertGreaterEqual(est.ci_high, est.ci_low)
        self.assertGreaterEqual(est.ci_high, FLOOR)

    def test_floor_is_reported_in_diagnostics(self):
        self.record_floor()
        est = self.estimate()
        self.assertEqual(est.diagnostics.get("floor_date"), FLOOR.isoformat())
        self.assertEqual(est.diagnostics.get("floor_source_period"), "2026-07-01")
        # Every precedent landed below the floor; that is worth surfacing, not hiding.
        self.assertEqual(est.diagnostics.get("n_precedents_below_floor"), est.n_precedents)
        self.assertEqual(est.method, "anchor_floored")

    # ---- walk-forward safety -------------------------------------------------

    def test_floor_published_after_the_knowledge_date_is_invisible(self):
        """A backtest replaying an earlier date must not see a later statement."""
        self.record_floor(source=(2026, 7))
        est = self.estimate(knowledge_date=date(2026, 6, 15))
        # June knowledge: the series is not Unavailable yet, so no reset estimate.
        self.assertFalse(est.is_unavailable)

        # And with the source bulletin itself in the future, the floor cannot apply.
        floor = PublishedFloor.objects.floor_for(
            "2nd", self.india, "final_action", date(2026, 10, 1), date(2026, 6, 15)
        )
        self.assertIsNone(floor)

    def test_latest_source_bulletin_supersedes_an_earlier_statement(self):
        self.record_floor(source=(2026, 6), floor_date=date(2013, 1, 1))
        self.record_floor(source=(2026, 7), floor_date=FLOOR)
        floor = PublishedFloor.objects.floor_for(
            "2nd", self.india, "final_action", date(2026, 10, 1), date(2026, 7, 31)
        )
        self.assertEqual(floor.floor_date, FLOOR)
        self.assertEqual(floor.source_bulletin.publication_date, date(2026, 7, 1))

    def test_floor_for_another_series_does_not_leak(self):
        self.record_floor()
        floor = PublishedFloor.objects.floor_for(
            "1st", self.india, "final_action", date(2026, 10, 1), date(2026, 7, 31)
        )
        self.assertIsNone(floor)

    # ---- the public sentence -------------------------------------------------

    def test_explainer_cites_the_floor_and_drops_the_2012_precedent(self):
        self.record_floor()
        text = describe_reset(self.estimate(), "EB-2 India")
        self.assertIn("July 15, 2014", text)
        self.assertIn("at least", text)
        # The 2012-retrogression framing is what the pooled distribution justified.
        # With a published floor above it, citing it contradicts the same paragraph.
        self.assertNotIn("2012", text)

    def test_explainer_without_a_floor_is_unchanged(self):
        text = describe_reset(self.estimate(), "EB-2 India")
        self.assertIn("rough guess", text)
        self.assertNotIn("at least", text)
