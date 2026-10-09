"""Tests for the per-EB-class x per-country priority-date landing pages.

Locks: valid combo renders 200 with the current cutoff + FAQPage schema +
correct canonical; unknown class/country 404s; a combo with no cutoff data 404s
(no thin page). Mirrors the slug sets in
webapp/views/bulletin/priority_date_landing.py.
"""

import re
from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from webapp.views.seo.sitemaps import build_sitemap_xml


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


def _cutoff_unavailable(bulletin, action_type, country):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class="2nd",
        action_type=action_type,
        country=country,
        cutoff_value="U",
        cutoff_date=None,
        is_current=False,
        is_unavailable=True,
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

    def test_answer_card_label_and_date_share_one_element(self):
        # Auto-ads appends a unit into a text block; a label in its own block let it land
        # between "FINAL ACTION DATE" and the date, pushing the answer below a phone screen.
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        for label, value in (("Final Action Date", "February 1, 2013"),
                             ("Dates for Filing", "July 1, 2013")):
            self.assertRegex(body, re.compile(
                r"<p[^>]*>\s*<span[^>]*>" + label + r"</span><br>\s*<span[^>]*>" + value
                + r"</span>\s*</p>"))

    def test_faqpage_schema_present(self):
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("priority date right now", body)  # an FAQ question rendered
        # FAQ questions render as real <h3> headings (featured-snippet / PAA harvest).
        self.assertIn('<h3 class="h6 fw-semibold mb-1">', body)

    def test_lead_answer_snippet_paragraph(self):
        # Featured-snippet bait: a concise direct answer in a .lead paragraph,
        # naming both the Final Action and Dates-for-Filing cutoffs.
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn('class="lead"', body)
        self.assertIn("the EB-2 Final Action Date for India is February 1, 2013", body)

    def test_canonical_is_self(self):
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn('rel="canonical" href="http://testserver/priority-date/eb2/india/"', body)

    def test_trend_direction_advanced(self):
        # Jan -> Feb 2013 is an advance; the page should say so.
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn("advanced", body)

    def test_history_chart_present(self):
        # The single priority-date-over-time graph is inlined as a Plotly payload.
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn('id="pd-history-chart"', body)
        self.assertIn('"connectgaps"', body)  # only appears in the chart JSON payload

    def test_unavailable_status_and_why_faq(self):
        # Latest bulletin: EB-2 India Final Action goes Unavailable (had a date the
        # month before). The page must say "Unavailable", explain WHY (not the old
        # vague "moved to/from Current or Unavailable" copy), and keep Filing usable.
        b3 = Bulletin.objects.create(publication_date=date(2026, 8, 1))
        _cutoff_unavailable(b3, ActionType.FINAL_ACTION.value, Country.INDIA.value)
        _cutoff(b3, ActionType.FILING.value, Country.INDIA.value, date(2015, 1, 15))
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn("Unavailable", body)
        self.assertIn("moved to Unavailable this month", body)  # new precise trend copy
        self.assertIn("annual per-country limit", body)  # the Why-Unavailable FAQ
        self.assertNotIn("moved to/from Current or Unavailable", body)  # old vague copy gone

    def test_unknown_class_404(self):
        self.assertEqual(self.client.get("/priority-date/eb9/india/").status_code, 404)

    def test_unknown_country_404(self):
        self.assertEqual(self.client.get("/priority-date/eb2/atlantis/").status_code, 404)

    def test_no_data_combo_404(self):
        # eb1/mexico has no cutoff rows in this fixture -> no thin page.
        self.assertEqual(self.client.get("/priority-date/eb1/mexico/").status_code, 404)


def _eb4_cutoff(bulletin, action_type, country, cutoff_date):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class="4th",  # EmploymentPreference.EB4 -> "EB-4: Special Immigrants"
        action_type=action_type,
        country=country,
        cutoff_value=cutoff_date.strftime("%d%b%y").upper(),
        cutoff_date=cutoff_date,
        is_current=False,
        is_unavailable=False,
    )


_EB4_COUNTRIES = {
    "india": (Country.INDIA, "India"),
    "china": (Country.CHINA, "China"),
    "philippines": (Country.PHILIPPINES, "Philippines"),
    "mexico": (Country.MEXICO, "Mexico"),
}


def _page_content(body: str) -> str:
    """The page's own content: from its H1 to the site footer, so the nav's Predictions link is out."""
    return body[body.index("<h1"):body.index("<footer")]


class TestEb4PriorityDateLanding(TestCase):
    """EB-4 has history-only pages: no forecast model covers it, so nothing may present or imply one."""

    def setUp(self):
        b1 = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        b2 = Bulletin.objects.create(publication_date=date(2026, 7, 1))
        for country, _label in _EB4_COUNTRIES.values():
            _eb4_cutoff(b1, ActionType.FINAL_ACTION.value, country.value, date(2022, 8, 1))
            _eb4_cutoff(b2, ActionType.FINAL_ACTION.value, country.value, date(2022, 9, 15))
            _eb4_cutoff(b2, ActionType.FILING.value, country.value, date(2023, 1, 1))
        _eb4_cutoff(b2, ActionType.FINAL_ACTION.value, Country.ALL.value, date(2022, 9, 15))
        # EB-2 India, so a forecast-backed sibling page renders alongside.
        _cutoff(b1, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 1, 1))
        _cutoff(b2, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 2, 1))

    def test_every_eb4_country_page_renders(self):
        for slug, (_country, label) in _EB4_COUNTRIES.items():
            with self.subTest(country=slug):
                resp = self.client.get(f"/priority-date/eb4/{slug}/")
                self.assertEqual(resp.status_code, 200)
                body = resp.content.decode()
                self.assertIn(f"EB-4 {label} Priority Date", body)
                self.assertIn("September 15, 2022", body)  # current Final Action
                self.assertIn("January 1, 2023", body)  # current Dates for Filing

    def test_eb4_page_carries_history_and_faq_schema(self):
        body = self.client.get("/priority-date/eb4/india/").content.decode()
        self.assertIn("Recent EB-4 India Final Action history", body)
        self.assertIn("August 1, 2022", body)  # prior month in the history table
        self.assertIn('id="pd-history-chart"', body)
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn('rel="canonical" href="http://testserver/priority-date/eb4/india/"', body)

    def test_eb4_page_presents_no_forecast(self):
        for path in ("/priority-date/eb4/india/", "/es/priority-date/eb4/india/", "/priority-date/eb4/"):
            with self.subTest(path=path):
                content = _page_content(self.client.get(path).content.decode())
                self.assertNotRegex(content, r"(?i)predict|forecast|predicci|pronóstico")

    def test_eb4_page_has_no_h1b_salary_link(self):
        content = _page_content(self.client.get("/priority-date/eb4/india/").content.decode())
        self.assertNotIn('href="/salaries/"', content)

    def test_forecast_backed_class_keeps_its_predictions_link(self):
        content = _page_content(self.client.get("/priority-date/eb2/india/").content.decode())
        self.assertIn("India dashboard + predictions", content)

    def test_eb4_linked_from_sibling_class_pages(self):
        content = _page_content(self.client.get("/priority-date/eb2/india/").content.decode())
        self.assertIn('href="/priority-date/eb4/india/"', content)

    def test_eb4_unknown_country_404(self):
        self.assertEqual(self.client.get("/priority-date/eb4/atlantis/").status_code, 404)
        # "All other countries" has data but no per-country page; the EB-4 rollup covers it.
        self.assertEqual(self.client.get("/priority-date/eb4/all/").status_code, 404)

    def test_spanish_eb4_page_renders(self):
        resp = self.client.get("/es/priority-date/eb4/india/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Fecha de Prioridad EB-4 India", body)
        self.assertIn('hreflang="en" href="http://testserver/priority-date/eb4/india/"', body)

    def test_sitemap_lists_eb4_pages(self):
        xml = build_sitemap_xml("https://visa-bulletin.us")
        self.assertIn("<loc>https://visa-bulletin.us/priority-date/eb4/</loc>", xml)
        for slug in _EB4_COUNTRIES:
            with self.subTest(country=slug):
                self.assertIn(f"<loc>https://visa-bulletin.us/priority-date/eb4/{slug}/</loc>", xml)
                self.assertIn(f"<loc>https://visa-bulletin.us/es/priority-date/eb4/{slug}/</loc>", xml)
        entry = xml[xml.index("/priority-date/eb4/india/</loc>"):]
        self.assertIn("<lastmod>", entry[:entry.index("</url>")])


class TestEb4WithoutData(TestCase):
    def test_eb4_without_cutoff_rows_404(self):
        Bulletin.objects.create(publication_date=date(2026, 7, 1))
        self.assertEqual(self.client.get("/priority-date/eb4/india/").status_code, 404)
        self.assertEqual(self.client.get("/priority-date/eb4/").status_code, 404)
