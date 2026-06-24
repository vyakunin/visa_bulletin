"""Tests for the priority-date HUB + per-EB-class ROLLUP pages.

Locks: the hub renders 200 with FAQPage schema + the three EB-class links; a
rollup renders 200 with the per-country table + correct canonical + FAQPage;
unknown EB class 404s; an EB class with no cutoff data 404s (no thin page);
route precedence holds (hub vs rollup vs the per-country landing page). Mirrors
the slug sets in webapp/views/bulletin/priority_date_rollup.py.
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


class TestPriorityDateRollup(TestCase):
    def setUp(self):
        # Two bulletins so the month-over-month trend is computable.
        b1 = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        b2 = Bulletin.objects.create(publication_date=date(2026, 7, 1))
        # EB-2 Final Action for India (retrogressed deep), China, and All Others.
        _cutoff(b1, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 1, 1))
        _cutoff(b2, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 2, 1))
        _cutoff(b1, ActionType.FINAL_ACTION.value, Country.CHINA.value, date(2020, 1, 1))
        _cutoff(b2, ActionType.FINAL_ACTION.value, Country.CHINA.value, date(2020, 3, 1))
        _cutoff(b1, ActionType.FINAL_ACTION.value, Country.ALL.value, date(2023, 1, 1))
        _cutoff(b2, ActionType.FINAL_ACTION.value, Country.ALL.value, date(2023, 2, 1))
        _cutoff(b2, ActionType.FILING.value, Country.INDIA.value, date(2013, 7, 1))

    def test_hub_renders(self):
        resp = self.client.get("/priority-date/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Green Card Priority Dates", body)
        # Links to all three EB-class rollups.
        self.assertIn('href="/priority-date/eb1/"', body)
        self.assertIn('href="/priority-date/eb2/"', body)
        self.assertIn('href="/priority-date/eb3/"', body)
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn('rel="canonical" href="http://testserver/priority-date/"', body)
        # Featured-snippet harvest: definitional lead paragraph + FAQ questions as
        # real <h3> headings (snippet/PAA bait for "green card priority date").
        self.assertIn('class="lead"', body)
        self.assertIn("A green card priority date is your place in line", body)
        self.assertIn('<h3 class="h6 fw-semibold mb-1">', body)

    def test_rollup_renders_with_country_table(self):
        resp = self.client.get("/priority-date/eb2/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("EB-2 Priority Date by Country", body)  # heading targets "eb2 priority date"
        self.assertIn("February 1, 2013", body)  # India current Final Action
        self.assertIn("India", body)
        self.assertIn("China", body)
        self.assertIn("All Other Countries", body)  # the ROW row
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn('rel="canonical" href="http://testserver/priority-date/eb2/"', body)
        # Internal mesh: links to per-country landing pages + sibling rollups.
        self.assertIn('href="/priority-date/eb2/india/"', body)
        self.assertIn('href="/priority-date/eb1/"', body)
        # Featured-snippet harvest: lead paragraph directly answers "eb2 priority date".
        self.assertIn('class="lead"', body)
        self.assertIn("The EB-2 priority date is the U.S. Visa Bulletin cutoff", body)
        self.assertIn('<h3 class="h6 fw-semibold mb-1">', body)

    def test_unknown_eb_class_404(self):
        self.assertEqual(self.client.get("/priority-date/notaclass/").status_code, 404)

    def test_eb_class_without_data_404(self):
        # EB-1 has no cutoff rows in this fixture -> no thin page.
        self.assertEqual(self.client.get("/priority-date/eb1/").status_code, 404)

    def test_route_precedence(self):
        # Hub (0 seg), rollup (1 seg), and per-country landing (2 seg) stay distinct.
        self.assertEqual(self.client.get("/priority-date/").status_code, 200)
        self.assertEqual(self.client.get("/priority-date/eb2/").status_code, 200)
        self.assertEqual(self.client.get("/priority-date/eb2/india/").status_code, 200)
