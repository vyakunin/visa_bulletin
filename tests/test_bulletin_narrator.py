"""Tests for blog bulletin narrator helpers (horizon selection matches publish_predictions)."""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest

from lib.business.blog.bulletin_narrator import horizon_months_from_knowledge


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
