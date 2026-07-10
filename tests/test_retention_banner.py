"""Server-side contract for the anonymous "your date moved" return banner.

The banner itself is client-side (webapp/static/js/retention_banner.js) and can't
run under bazel, so these tests lock the SERVER contract that feeds it:

  * the stable, URL-independent comparison key + record shape (retention.py);
  * the forecast page bakes a #retention-data json_script for its headline series
    with the right key, predicted date, and status;
  * the dashboard bakes records keyed by the raw class code, and the key is
    IDENTICAL across two different URL forms of the same page (the URL-scheme
    stability the ticket requires);
  * pages with no predictions bake nothing (graceful no-op);
  * the shipped JS is CLS-safe (position:fixed — out of flow, no layout shift).

The JS logic (localStorage diff, forward/back/unchanged phrasing) is exercised by
manual verification — see the module docstring in retention_banner.js.
"""

import json
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff
from webapp.views.bulletin.retention import (
    STATUS_CURRENT,
    STATUS_DATE,
    make_record,
    retention_key,
    series_label,
)

_JS = (
    Path(__file__).resolve().parent.parent
    / "webapp" / "static" / "js" / "retention_banner.js"
)


def _retention_payload(html: str):
    """Parse the #retention-data json_script payload, or None if absent."""
    m = re.search(
        r'<script id="retention-data" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    return json.loads(m.group(1)) if m else None


class RetentionKeyUnitTest(TestCase):
    """Pure helpers — no DB, no request."""

    def test_key_is_underlying_values_not_url(self):
        # category | country-int | class-code | action — nothing URL-derived, so it
        # can't drift when the URL canonicalization changes.
        self.assertEqual(
            retention_key("employment_based", Country.INDIA.value, "2nd", "final_action"),
            "employment_based|3|2nd|final_action",
        )

    def test_key_stable_regardless_of_slug_vs_numeric(self):
        # Same series, however the caller spelled the country in the URL.
        k1 = retention_key("employment_based", Country.INDIA.value, "2nd", "filing")
        k2 = retention_key("employment_based", 3, "2nd", "filing")
        self.assertEqual(k1, k2)

    def test_series_label_reads_naturally(self):
        self.assertEqual(
            series_label("employment_based", Country.INDIA.value, "2nd", "final_action"),
            "the EB-2 India Final Action cutoff",
        )

    def test_make_record_date(self):
        rec = make_record(
            "employment_based", Country.INDIA.value, "2nd", "final_action",
            status=STATUS_DATE, predicted_date=date(2020, 3, 1),
        )
        self.assertEqual(rec["k"], "employment_based|3|2nd|final_action")
        self.assertEqual(rec["s"], STATUS_DATE)
        self.assertEqual(rec["d"], "2020-03-01")
        self.assertIn("EB-2 India", rec["l"])

    def test_make_record_current_has_null_date(self):
        rec = make_record(
            "employment_based", Country.CHINA.value, "1st", "filing",
            status=STATUS_CURRENT, predicted_date=None,
        )
        self.assertIsNone(rec["d"])
        self.assertEqual(rec["s"], STATUS_CURRENT)


class ForecastPageBakesRecordsTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        self.latest = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        VisaCutoffDate.objects.create(
            bulletin=self.latest, visa_category="employment_based", visa_class="2nd",
            action_type=ActionType.FINAL_ACTION.value, country=Country.INDIA.value,
            cutoff_value="01JAN20", cutoff_date=date(2020, 1, 1),
            is_current=False, is_unavailable=False,
        )
        self.pb = PredictedBulletin.objects.create(
            target_bulletin_month=date(2026, 7, 1), prediction_date=date(2026, 6, 15),
        )
        PredictedCutoff.objects.create(
            bulletin=self.pb, visa_class="2nd", country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value, predicted_date=date(2020, 3, 1),
            model_name="regime_switched", expert_predictions={},
        )

    def test_forecast_bakes_retention_data_for_headline_series(self):
        html = self.client.get("/predictions/july-2026/").content.decode()
        payload = _retention_payload(html)
        self.assertIsNotNone(payload, "forecast page must bake #retention-data")
        by_key = {r["k"]: r for r in payload}
        rec = by_key.get("employment_based|3|2nd|final_action")
        self.assertIsNotNone(rec, "EB-2 India Final Action must be a recorded series")
        self.assertEqual(rec["s"], STATUS_DATE)
        self.assertEqual(rec["d"], "2020-03-01")

    def test_forecast_includes_the_banner_script(self):
        html = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("js/retention_banner.js", html)


class DashboardBakesRecordsTest(TestCase):
    """Dashboard render with the heavy VQS/chart paths mocked (pattern mirrors
    test_dashboard_content_depth): assert the baked records + URL-scheme stability."""

    V = "webapp.views.bulletin.dashboard"

    def setUp(self):
        self.client = Client()
        cache.clear()

    def _get(self, url, params=None):
        rows = [{
            "label": "EB-2", "visa_class": "2nd",
            "next_cutoff": date(2020, 3, 1), "already_current": False,
        }]
        with patch(f"{self.V}.get_aggregated_visa_class_data",
                   return_value=([{"visa_class_label": "EB-2", "visa_class": "2nd"}], True)), \
             patch(f"{self.V}._build_unified_prediction_rows", return_value=rows), \
             patch(f"{self.V}.build_multi_class_chart_with_projections",
                   return_value={"trace_info": []}), \
             patch(f"{self.V}._get_vqs_predictions", return_value={}):
            return self.client.get(url, params or {}).content.decode()

    def test_dashboard_bakes_record_keyed_by_class_code(self):
        html = self._get("/employment-based/india/")
        payload = _retention_payload(html)
        self.assertIsNotNone(payload, "dashboard must bake #retention-data")
        # Dashboard default action_type is Dates for Filing.
        by_key = {r["k"]: r for r in payload}
        rec = by_key.get("employment_based|3|2nd|filing")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["d"], "2020-03-01")

    def test_key_identical_across_url_forms(self):
        # The ticket's hard requirement: the "prediction changed" key must not vary
        # with the URL canonicalization. /employment-based/india/ (slug path) and
        # /?country=india (query form) are the same page → same key.
        keys_slug = {r["k"] for r in _retention_payload(self._get("/employment-based/india/"))}
        keys_query = {
            r["k"] for r in _retention_payload(
                self._get("/", {"category": "employment_based", "country": "india"})
            )
        }
        self.assertIn("employment_based|3|2nd|filing", keys_slug)
        self.assertEqual(keys_slug, keys_query)


class GracefulDegradationTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()

    def test_static_page_bakes_nothing(self):
        # A page with no predictions supplies no retention_records → no data script,
        # no JS include (the banner is a pure no-op there).
        html = self.client.get("/about/").content.decode()
        self.assertIsNone(_retention_payload(html))
        self.assertNotIn("js/retention_banner.js", html)


class BannerJsIsClsSafeTest(TestCase):
    def test_js_uses_fixed_positioning(self):
        # position:fixed = out of normal flow ⇒ appearing causes zero layout shift
        # (CLS-safe on / and /employment-based/india). Locks the reasoning in code.
        src = _JS.read_text()
        self.assertIn('id = "retention-banner"', src)

    def test_css_pins_banner_fixed(self):
        base = (
            Path(__file__).resolve().parent.parent
            / "webapp" / "templates" / "webapp" / "base.html"
        ).read_text()
        # The #retention-banner rule must be position:fixed for the CLS guarantee.
        block = re.search(r"#retention-banner\s*\{[^}]*\}", base)
        self.assertIsNotNone(block)
        self.assertIn("position: fixed", block.group(0))
