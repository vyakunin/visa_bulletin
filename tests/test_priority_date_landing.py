"""Tests for the per-EB-class x per-country priority-date landing pages.

Locks: valid combo renders 200 with the current cutoff + FAQPage schema +
correct canonical; unknown class/country 404s; a combo with no cutoff data 404s
(no thin page). Mirrors the slug sets in
webapp/views/bulletin/priority_date_landing.py.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate


def _cutoff(bulletin, action_type, country, cutoff_date):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class="2nd",  # EmploymentPreference.EB2 -> "EB-2: ..."
        action_type=action_type,
        country=country,
        cutoff_value=cutoff_date.strftime("%d%b%y").upper(),
        cutoff_date=cutoff_date,
        is_current=False,
        is_unavailable=False,
    )


class TestPriorityDateLanding(TestCase):
    def setUp(self):
        # Two bulletins so the trend (last two Final Action cutoffs) is computable.
        b1 = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        b2 = Bulletin.objects.create(publication_date=date(2026, 7, 1))
        # EB-2 India Final Action advanced Jan->Feb 2013 month-over-month.
        _cutoff(b1, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 1, 1))
        _cutoff(b2, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 2, 1))
        _cutoff(b1, ActionType.FILING.value, Country.INDIA.value, date(2013, 6, 1))
        _cutoff(b2, ActionType.FILING.value, Country.INDIA.value, date(2013, 7, 1))

    def test_valid_combo_renders(self):
        resp = self.client.get("/priority-date/eb2/india/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("EB-2 India Priority Date", body)  # H1 / heading
        self.assertIn("February 1, 2013", body)  # current Final Action cutoff
        self.assertIn("July 1, 2013", body)  # current Dates for Filing cutoff

    def test_faqpage_schema_present(self):
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("priority date right now", body)  # an FAQ question rendered

    def test_canonical_is_self(self):
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn('rel="canonical" href="http://testserver/priority-date/eb2/india/"', body)

    def test_trend_direction_advanced(self):
        # Jan -> Feb 2013 is an advance; the page should say so.
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn("advanced", body)

    def test_unknown_class_404(self):
        self.assertEqual(self.client.get("/priority-date/eb9/india/").status_code, 404)

    def test_unknown_country_404(self):
        self.assertEqual(self.client.get("/priority-date/eb2/atlantis/").status_code, 404)

    def test_no_data_combo_404(self):
        # eb1/mexico has no cutoff rows in this fixture -> no thin page.
        self.assertEqual(self.client.get("/priority-date/eb1/mexico/").status_code, 404)
