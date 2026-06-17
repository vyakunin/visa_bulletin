"""Tests for blog bulletin narrator helpers (horizon selection matches publish_predictions)."""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest

from lib.business.blog.bulletin_narrator import (
    BulletinNarrator,
    horizon_months_from_knowledge,
)


class TestHorizonMonthsFromKnowledge(unittest.TestCase):
    """Matches scripts/publish_predictions horizon_m calculation."""

    def test_one_month_ahead(self):
        self.assertEqual(
            horizon_months_from_knowledge(date(2026, 5, 1), date(2026, 4, 15)),
            1,
        )

    def test_six_months_ahead(self):
        self.assertEqual(
            horizon_months_from_knowledge(date(2026, 5, 1), date(2025, 11, 20)),
            6,
        )

    def test_same_calendar_month_is_zero(self):
        self.assertEqual(
            horizon_months_from_knowledge(date(2026, 5, 1), date(2026, 5, 31)),
            0,
        )


class TestOutlookUnavailable(unittest.TestCase):
    """Future Outlook must render an Unavailable series without a stale cutoff date.

    Regression: India EB-2 went Unavailable but the model persisted its last
    pre-Unavailable cutoff, rendering "Advancing — Next predicted cutoff: 01 Sep
    2013". Unavailable series must carry predicted_date=None + an unavailable flag.
    """

    def test_unavailable_series_has_no_predicted_date(self):
        unavailable = {
            "label": "EB-2 India", "visa_class": "2nd", "country": 3,
            "predicted_date": None, "unavailable": True,
            "regime_label": "Unavailable", "regime_badge_class": "secondary",
        }
        normal = {
            "label": "EB-3 India", "visa_class": "3rd", "country": 3,
            "predicted_date": date(2014, 1, 31), "regime": "advancing",
            "regime_label": "Advancing", "regime_badge_class": "success",
        }
        outlook = BulletinNarrator()._generate_outlook_from_predictions(
            [unavailable, normal], historical_pace=[]
        )
        by_label = {o["label"]: o for o in outlook["series_outlooks"]}

        self.assertTrue(by_label["EB-2 India"]["unavailable"])
        self.assertIsNone(by_label["EB-2 India"]["predicted_date"])
        self.assertEqual(by_label["EB-2 India"]["regime_label"], "Unavailable")

        self.assertEqual(by_label["EB-3 India"]["predicted_date"], date(2014, 1, 31))
        self.assertFalse(by_label["EB-3 India"].get("unavailable", False))


class _FakeCutoff:
    def __init__(self, visa_class, country, cutoff_date=None, is_current=False, is_unavailable=False):
        self.visa_class = visa_class
        self.country = country
        self.cutoff_date = cutoff_date
        self.is_current = is_current
        self.is_unavailable = is_unavailable
        self.action_type = "final_action"


class _FakeQS:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, **kwargs):
        at = kwargs.get("action_type")
        return [r for r in self._rows if at is None or r.action_type == at]


class _FakeBulletin:
    def __init__(self, rows):
        self.cutoff_dates = _FakeQS(rows)


class TestMovementsStateTransitions(unittest.TestCase):
    """Key Movements must report Unavailable/Current transitions, not drop them.

    Regression: India EB-2 going from a real cutoff to Unavailable (July 2026) was
    silently omitted because the analyzer only reported date→date moves.
    """

    def test_date_to_unavailable_is_reported(self):
        prev = _FakeBulletin([_FakeCutoff("2nd", 3, cutoff_date=date(2013, 9, 1))])
        curr = _FakeBulletin([_FakeCutoff("2nd", 3, is_unavailable=True)])
        mv = BulletinNarrator()._analyze_movements(curr, prev)
        emp = " ".join(mv["employment"])
        self.assertIn("Unavailable", emp)
        self.assertIn("EB-2 India", emp)
        self.assertIn("01 Sep 2013", emp)

    def test_normal_advance_still_reported(self):
        prev = _FakeBulletin([_FakeCutoff("3rd", 3, cutoff_date=date(2013, 12, 15))])
        curr = _FakeBulletin([_FakeCutoff("3rd", 3, cutoff_date=date(2014, 1, 1))])
        mv = BulletinNarrator()._analyze_movements(curr, prev)
        self.assertTrue(any("advanced by 17 days" in m for m in mv["employment"]))


class TestFamilyMovements(unittest.TestCase):
    """Family-Sponsored movement must be analyzed (was hardcoded 'no movement').

    Country 1=All, 2=China, 4=Mexico. China folds into All when it matches;
    Mexico is reported separately when it diverges.
    """

    def test_family_all_areas_and_diverging_country(self):
        prev = _FakeBulletin([
            _FakeCutoff("F1", 1, cutoff_date=date(2017, 9, 1)),   # All
            _FakeCutoff("F1", 2, cutoff_date=date(2017, 9, 1)),   # China == All
            _FakeCutoff("F1", 4, cutoff_date=date(2001, 5, 1)),   # Mexico diverges
        ])
        curr = _FakeBulletin([
            _FakeCutoff("F1", 1, cutoff_date=date(2018, 2, 1)),   # All advanced
            _FakeCutoff("F1", 2, cutoff_date=date(2018, 2, 1)),   # China still == All
            _FakeCutoff("F1", 4, cutoff_date=date(2001, 6, 1)),   # Mexico advanced
        ])
        fam = " ".join(BulletinNarrator()._analyze_movements(curr, prev)["family"])
        self.assertIn("F1 (All Areas)", fam)
        self.assertIn("F1 Mexico", fam)
        self.assertNotIn("F1 China", fam)  # folded into All Areas

    def test_family_quiet_month_reports_nothing(self):
        prev = _FakeBulletin([_FakeCutoff("F2A", 1, cutoff_date=date(2025, 1, 1))])
        curr = _FakeBulletin([_FakeCutoff("F2A", 1, cutoff_date=date(2025, 1, 1))])
        self.assertEqual(BulletinNarrator()._analyze_movements(curr, prev)["family"], [])


if __name__ == "__main__":
    unittest.main()
