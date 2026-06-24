"""Tests for the interactive priority-date calculator (/priority-date-calculator/).

Locks: the page renders 200 with the H1, canonical, and FAQPage schema; the
baked cutoff matrix is correct (a real date, Current, and Unavailable all map to
the right cell shape, EB + family categories both surface, EB-5 collapses to the
Unreserved line); the dropdowns only offer categories that have data; the page is
in the sitemap. Mirrors webapp/views/bulletin/priority_date_calculator.py.
"""

import json
import re
from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate


def _cutoff(bulletin, *, category, visa_class, action_type, country,
            cutoff_date=None, is_current=False, is_unavailable=False):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category=category,
        visa_class=visa_class,
        action_type=action_type,
        country=country,
        cutoff_value=(cutoff_date.strftime("%d%b%y").upper() if cutoff_date
                      else ("C" if is_current else "U")),
        cutoff_date=cutoff_date,
        is_current=is_current,
        is_unavailable=is_unavailable,
    )


def _config(body: str) -> dict:
    m = re.search(
        r'<script id="pd-calc-config" type="application/json">(.*?)</script>',
        body, re.DOTALL,
    )
    assert m, "calc config script tag missing"
    return json.loads(m.group(1))


class TestPriorityDateCalculator(TestCase):
    def setUp(self):
        b = Bulletin.objects.create(publication_date=date(2026, 7, 1))
        fa = ActionType.FINAL_ACTION.value
        df = ActionType.FILING.value
        emp = "employment_based"
        fam = "family_sponsored"
        # EB-2 India: a real Final Action + Filing date.
        _cutoff(b, category=emp, visa_class="2nd", action_type=fa,
                country=Country.INDIA.value, cutoff_date=date(2013, 2, 1))
        _cutoff(b, category=emp, visa_class="2nd", action_type=df,
                country=Country.INDIA.value, cutoff_date=date(2013, 7, 1))
        # EB-1 China: Current.
        _cutoff(b, category=emp, visa_class="1st", action_type=fa,
                country=Country.CHINA.value, is_current=True)
        # EB-3 India: Unavailable.
        _cutoff(b, category=emp, visa_class="3rd", action_type=fa,
                country=Country.INDIA.value, is_unavailable=True)
        # EB-5 India: two sub-lines — Unreserved must win over Targeted.
        _cutoff(b, category=emp, visa_class="5th Targeted Employment Areas",
                action_type=fa, country=Country.INDIA.value, cutoff_date=date(2022, 1, 1))
        _cutoff(b, category=emp, visa_class="5th Unreserved", action_type=fa,
                country=Country.INDIA.value, cutoff_date=date(2020, 5, 1))
        # F2A All Other Countries: a date (family category surfaces too).
        _cutoff(b, category=fam, visa_class="F2A", action_type=fa,
                country=Country.ALL.value, cutoff_date=date(2024, 9, 1))

    def test_renders_with_seo_chrome(self):
        resp = self.client.get("/priority-date-calculator/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Green Card Priority Date Calculator", body)  # H1
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn(
            'rel="canonical" href="http://testserver/priority-date-calculator/"', body
        )

    def test_matrix_baked_correctly(self):
        body = self.client.get("/priority-date-calculator/").content.decode()
        matrix = _config(body)["matrix"]
        india, china, allc = (
            str(Country.INDIA.value), str(Country.CHINA.value), str(Country.ALL.value),
        )
        # EB-2 India: real dates on both action types.
        self.assertEqual(matrix["eb2"][india]["final"]["iso"], "2013-02-01")
        self.assertEqual(matrix["eb2"][india]["final"]["status"], "date")
        self.assertEqual(matrix["eb2"][india]["filing"]["iso"], "2013-07-01")
        # EB-1 China: Current.
        self.assertEqual(matrix["eb1"][china]["final"]["status"], "current")
        # EB-3 India: Unavailable.
        self.assertEqual(matrix["eb3"][india]["final"]["status"], "unavailable")
        # EB-5 India: the Unreserved line wins over Targeted.
        self.assertEqual(matrix["eb5"][india]["final"]["iso"], "2020-05-01")
        # Family category surfaces.
        self.assertEqual(matrix["f2a"][allc]["final"]["iso"], "2024-09-01")

    def test_dropdowns_only_offer_categories_with_data(self):
        body = self.client.get("/priority-date-calculator/").content.decode()
        # Categories with data are offered…
        self.assertIn("EB-2: Professionals with Advanced Degrees", body)
        self.assertIn("F2A: Spouses/Children of Permanent Residents", body)
        # …categories with NO data this month are not (EB-4 has no fixture row).
        self.assertNotIn("EB-4: Special Immigrants", body)
        # Country options present.
        self.assertIn(">India</option>", body)
        self.assertIn(">All Other Countries</option>", body)

    def test_in_sitemap(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("/priority-date-calculator/", body)
