"""Structured data + post-drop FAQ on the month accuracy-archive page.

Locks the SEO hardening of the canonical /predictions/<year>-<month>/ page (the
one that inherits "visa bulletin <month> <year>" intent after a drop): a valid
JSON-LD @graph carrying FAQPage + BreadcrumbList + a page-scoped Dataset, plus a
VISIBLE FAQ whose answers mirror the FAQPage text and are generated from the
month's ACTUAL published cutoffs (never hardcoded). A regression — schema block
dropped, invalid JSON, the FAQ answer no longer citing the real published date,
or the visible FAQ diverging from the JSON-LD — fails here.
"""

import json
import re
from datetime import date
from unittest.mock import patch

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate

_LOADER = "webapp.views.prediction_views.get_all_predictions_for_month"


def _actual(bulletin, action_type, country, visa_class, cutoff_date):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class=visa_class,
        action_type=action_type,
        country=country,
        cutoff_value=cutoff_date.strftime("%d%b%y").upper(),
        cutoff_date=cutoff_date,
        is_current=False,
        is_unavailable=False,
    )


def _jsonld_blocks(html: str) -> list:
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL
    )
    # Django autoescape leaves the |safe blob intact; json.loads validates it.
    return [json.loads(b) for b in blocks]


class PredictionDetailStructuredDataTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        # Prior month (July 2026) actuals — the movement baseline.
        self.prev = Bulletin.objects.create(publication_date=date(2026, 7, 1))
        _actual(self.prev, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2019, 11, 15))
        _actual(self.prev, ActionType.FINAL_ACTION.value, Country.INDIA.value, "3rd", date(2013, 1, 1))

        # Target month (August 2026) — the LATEST published bulletin (no later
        # one), so it is the freshest-published page.
        self.target = Bulletin.objects.create(publication_date=date(2026, 8, 1))
        # EB-2 India advances +16 days; EB-3 India advances too.
        _actual(self.target, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2019, 12, 1))
        _actual(self.target, ActionType.FINAL_ACTION.value, Country.INDIA.value, "3rd", date(2013, 2, 1))

    def _get(self):
        # Patch the loader so the archive page renders actuals without invoking
        # the backtest solver for unstored series (fast + deterministic).
        with patch(_LOADER, return_value=({}, date(2026, 7, 15))):
            return self.client.get("/predictions/2026-8/")

    def _graph(self, html: str) -> list:
        for block in _jsonld_blocks(html):
            if isinstance(block, dict) and "@graph" in block:
                return block["@graph"]
        raise AssertionError("no @graph JSON-LD block found on the page")

    def test_page_renders_and_jsonld_is_valid(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        # Every ld+json block on the page parses (json.loads raises otherwise).
        blocks = _jsonld_blocks(resp.content.decode())
        self.assertTrue(blocks)

    def test_graph_carries_faqpage_breadcrumb_and_dataset(self):
        graph = self._graph(self._get().content.decode())
        types = {node.get("@type") for node in graph}
        self.assertIn("FAQPage", types)
        self.assertIn("BreadcrumbList", types)
        self.assertIn("Dataset", types)

    def test_breadcrumb_mirrors_visible_trail(self):
        graph = self._graph(self._get().content.decode())
        crumb = next(n for n in graph if n.get("@type") == "BreadcrumbList")
        names = [i["name"] for i in crumb["itemListElement"]]
        self.assertEqual(names[-2], "Prediction accuracy archive")
        self.assertIn("Employment-Based: August 2026", names[-1])
        # positions are contiguous 1..N
        self.assertEqual(
            [i["position"] for i in crumb["itemListElement"]],
            list(range(1, len(crumb["itemListElement"]) + 1)),
        )

    def test_faq_answers_cite_the_real_published_date(self):
        graph = self._graph(self._get().content.decode())
        faq = next(n for n in graph if n.get("@type") == "FAQPage")
        answers = " ".join(
            q["acceptedAnswer"]["text"] for q in faq["mainEntity"]
        )
        # The ACTUAL EB-2 India Final Action Date rendered by the table, and the
        # movement, must appear in the generated answers — proving the FAQ is
        # wired to real data, not hardcoded.
        self.assertIn("01 Dec 2019", answers)
        self.assertIn("advance", answers.lower())
        # A date NOT in the DB must not appear (no fabrication).
        self.assertNotIn("01 Jan 2099", answers)

    def test_next_bulletin_question_present_on_latest_month(self):
        graph = self._graph(self._get().content.decode())
        faq = next(n for n in graph if n.get("@type") == "FAQPage")
        questions = " ".join(q["name"] for q in faq["mainEntity"])
        self.assertIn("When is the September 2026 Visa Bulletin expected?", questions)

    def test_visible_faq_mirrors_jsonld(self):
        html = self._get().content.decode()
        graph = self._graph(html)
        faq = next(n for n in graph if n.get("@type") == "FAQPage")
        # Every JSON-LD question + answer is present in the visible DOM.
        self.assertIn("Frequently Asked Questions", html)
        for q in faq["mainEntity"]:
            self.assertIn(q["name"], html)
            self.assertIn(q["acceptedAnswer"]["text"], html)

    def test_table_has_caption(self):
        html = self._get().content.decode()
        self.assertIn("<caption", html)
        self.assertIn("Official August 2026 Visa Bulletin", html)

    def test_title_leads_with_official_dates(self):
        html = self._get().content.decode()
        self.assertIn(
            "August 2026 Visa Bulletin — Official Employment-Based Dates", html
        )
