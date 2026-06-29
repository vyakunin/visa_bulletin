"""Regression: the dashboard emits query-matched, country/category-bearing H2
section headings over its data (content-depth / intent-match lever, Notion 38b62b8d).

The highest-value page (/employment-based/india) was data-dense but had only ONE
H2 ("Filter Options") and a generic "Visa Bulletin Predictions" H3 — no section
heading matched the high-intent queries it ranks page-4 for ("current eb2 priority
date india", "eb1 backlog india"). These tests lock the query-matched headings:
the data table → "Current <Country> <Category> Priority Dates"; the chart →
"<Country> <Category> Priority Date Movement & Backlog Trend".

The view's heavy paths (VQS solver, chart builder) are mocked so the unified_rows
and chart_data template blocks fire deterministically — the assertions are on the
RENDERED HTML.
"""
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase

V = "webapp.views.bulletin.dashboard"


class DashboardContentDepthTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()

    def _get_india_eb(self):
        with patch(f"{V}.get_aggregated_visa_class_data", return_value=([{"visa_class_label": "EB-2"}], True)), \
             patch(f"{V}._build_unified_prediction_rows", return_value=[{"label": "EB-2"}]), \
             patch(f"{V}.build_multi_class_chart_with_projections", return_value={"trace_info": []}), \
             patch(f"{V}._get_vqs_predictions", return_value={}):
            return self.client.get("/", {"category": "employment_based", "country": "india"}).content.decode()

    def test_data_table_has_query_matched_h2(self):
        html = self._get_india_eb()
        self.assertIn("Current India Employment-Based Priority Dates", html)
        # The old generic, non-query-matched heading must be gone.
        self.assertNotIn(">Visa Bulletin Predictions", html)

    def test_chart_has_backlog_trend_h2(self):
        html = self._get_india_eb()
        self.assertIn("India Employment-Based Priority Date Movement &amp; Backlog Trend", html)

    def test_intent_bearing_intro_sentence(self):
        html = self._get_india_eb()
        self.assertIn("Current priority date cutoffs", html)
        self.assertIn("backlog clears", html)

    def test_still_exactly_one_h1(self):
        """The added sections are H2/H3 — must not reintroduce a second H1."""
        html = self._get_india_eb()
        self.assertEqual(html.count("<h1"), 1, "dashboard must still have exactly one <h1>")
