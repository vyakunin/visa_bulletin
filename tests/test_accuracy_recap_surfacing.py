"""Integration tests for surfacing prediction-accuracy content (2026 SEO pass).

The accuracy data existed but leaked: the archive index was out of the sitemap
and carried no canonical/structured data, the per-month recap buried the headline
accuracy under a dense grid, dashboard "See backtest" links 301'd to only the
latest month, and the /spaghetti/ + /metric-report/ track-record pages were
orphaned. These lock the surfacing:

* the sitemap now emits /predictions/, /spaghetti/, /metric-report/;
* the /predictions/ archive index renders a canonical, a BreadcrumbList JSON-LD,
  a latest-month scorecard, and links to the track-record pages;
* the per-month recap renders a headline accuracy rollup banner whose real
  numbers come from compute_bulletin_accuracy_summary / compare_to_no_change_baseline;
* the archive teasers (scorecard + all-time) are computed from STORED predictions.
"""

import json
import re
from datetime import date
from unittest.mock import patch

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache  # noqa: E402
from django.test import Client, TestCase  # noqa: E402

from lib.business.vqs.accuracy_surfacing import (  # noqa: E402
    all_time_track_record,
    latest_month_scorecard,
)
from lib.business.vqs.prediction_loader import PredictionResult  # noqa: E402
from models.bulletin import Bulletin  # noqa: E402
from models.enums.action_type import ActionType  # noqa: E402
from models.enums.country import Country  # noqa: E402
from models.visa_cutoff_date import VisaCutoffDate  # noqa: E402
from models.vqs import PredictedBulletin, PredictedCutoff  # noqa: E402

_FA = ActionType.FINAL_ACTION.value
_INDIA = Country.INDIA.value
_PREV = date(2026, 7, 1)
_TARGET = date(2026, 8, 1)


def _actual(bulletin, visa_class, cutoff):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class=visa_class,
        action_type=_FA,
        country=_INDIA,
        cutoff_value=cutoff.strftime("%d%b%y").upper(),
        cutoff_date=cutoff,
        is_current=False,
        is_unavailable=False,
    )


def _seed_actuals():
    prev = Bulletin.objects.create(publication_date=_PREV)
    _actual(prev, "2nd", date(2019, 11, 15))
    _actual(prev, "3rd", date(2013, 1, 1))
    target = Bulletin.objects.create(publication_date=_TARGET)
    _actual(target, "2nd", date(2019, 12, 1))  # EB-2 India advanced +16d
    _actual(target, "3rd", date(2013, 2, 1))  # EB-3 India advanced
    return prev, target


def _seed_stored_predictions():
    pb = PredictedBulletin.objects.create(
        target_bulletin_month=_TARGET, prediction_date=date(2026, 7, 15)
    )
    PredictedCutoff.objects.create(
        bulletin=pb, visa_class="2nd", country=_INDIA, action_type=_FA,
        predicted_date=date(2019, 12, 10), model_name="ensemble", expert_predictions={},
    )  # 9d miss
    PredictedCutoff.objects.create(
        bulletin=pb, visa_class="3rd", country=_INDIA, action_type=_FA,
        predicted_date=date(2013, 1, 19), model_name="ensemble", expert_predictions={},
    )  # 13d miss


def _jsonld_blocks(html: str) -> list:
    return [
        json.loads(b)
        for b in re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL
        )
    ]


class StoredScorecardTest(TestCase):
    def setUp(self):
        cache.clear()
        _seed_actuals()
        _seed_stored_predictions()

    def test_latest_month_scorecard_real_numbers(self):
        sc = latest_month_scorecard()
        self.assertIsNotNone(sc)
        self.assertEqual(sc["month_label"], "August 2026")
        self.assertEqual(sc["recap_url"], "/predictions/2026-8/")
        self.assertEqual(sc["n_scored"], 2)
        self.assertEqual(sc["mae_days"], 11)  # round(mean(9, 13))
        bands = {b["label"]: b["mae_days"] for b in sc["bands"]}
        self.assertEqual(bands, {"EB-2": 9, "EB-3": 13})
        # No-change baseline: prev 15Nov->1Dec = 16d, prev 1Jan->1Feb = 31d.
        base = sc["baseline"]
        self.assertEqual(base["total"], 2)
        self.assertEqual(base["model_wins"], 2)
        self.assertEqual(base["baseline_mean"], 23.5)
        self.assertTrue(base["beats_baseline"])

    def test_all_time_track_record_real_numbers(self):
        at = all_time_track_record()
        self.assertIsNotNone(at)
        self.assertEqual(at["n_scored"], 2)
        self.assertEqual(at["months_covered"], 1)
        self.assertEqual(at["model_mean"], 11.0)
        self.assertEqual(at["baseline_mean"], 23.5)
        self.assertEqual(at["model_wins"], 2)
        self.assertEqual(at["baseline_total"], 2)
        self.assertTrue(at["beats_baseline"])

    def test_all_time_none_without_stored_predictions(self):
        PredictedCutoff.objects.all().delete()
        self.assertIsNone(all_time_track_record())
        self.assertIsNone(latest_month_scorecard())


class BandWindowTest(TestCase):
    """A band names the window it covers when that window is short.

    Categories enter the record at different months, so two bands side by side
    can span histories that differ by years and still read as comparable. The
    band that starts after the record does says from when; the ones that cover
    the whole record stay silent, and a single-month rollup flags nothing at all
    (every band there shares the one month).
    """

    def setUp(self):
        cache.clear()
        first = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        _actual(first, "2nd", date(2019, 10, 1))
        target = Bulletin.objects.create(publication_date=_TARGET)
        _actual(target, "2nd", date(2019, 12, 1))
        _actual(target, "3rd", date(2013, 2, 1))

        # EB-2 is predicted from the first month; EB-3 only enters in the last.
        for month, preds in (
            (date(2026, 6, 1), {"2nd": date(2019, 10, 6)}),
            (_TARGET, {"2nd": date(2019, 12, 6), "3rd": date(2013, 2, 6)}),
        ):
            pb = PredictedBulletin.objects.create(
                target_bulletin_month=month, prediction_date=month
            )
            for vc, pd in preds.items():
                PredictedCutoff.objects.create(
                    bulletin=pb, visa_class=vc, country=_INDIA, action_type=_FA,
                    predicted_date=pd, model_name="ensemble",
                )

    def _bands(self):
        return {b["label"]: b for b in all_time_track_record()["bands"]}

    def test_the_late_entrant_names_the_month_it_is_scored_from(self):
        self.assertEqual(self._bands()["EB-3"]["scored_from"], _TARGET)

    def test_a_band_spanning_the_whole_record_names_no_window(self):
        # Saying "scored from June 2026" under every band would be noise, and it
        # would stop the one short window standing out.
        self.assertIsNone(self._bands()["EB-2"]["scored_from"])

    def test_each_band_carries_its_own_span_and_count(self):
        eb2 = self._bands()["EB-2"]
        self.assertEqual((eb2["first_month"], eb2["last_month"]), (date(2026, 6, 1), _TARGET))
        self.assertEqual((eb2["n"], self._bands()["EB-3"]["n"]), (2, 1))

    def test_a_single_month_rollup_flags_no_window(self):
        # The scorecard scores one month, so every band covers it. A window note
        # there would be true and useless.
        bands = latest_month_scorecard()["bands"]
        self.assertEqual([b["label"] for b in bands], ["EB-2", "EB-3"])
        self.assertEqual([b["scored_from"] for b in bands], [None, None])

    def test_a_series_the_bulletin_does_not_rename_carries_no_note(self):
        self.assertIsNone(self._bands()["EB-3"]["window_note"])


class ArchiveIndexTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        _seed_actuals()
        _seed_stored_predictions()

    def _html(self):
        return self.client.get("/predictions/").content.decode()

    def test_canonical_present(self):
        html = self._html()
        self.assertIn('<link rel="canonical" href="http://testserver/predictions/">', html)

    def test_breadcrumb_jsonld(self):
        graph = None
        for block in _jsonld_blocks(self._html()):
            if isinstance(block, dict) and "@graph" in block:
                graph = block["@graph"]
        self.assertIsNotNone(graph, "archive index must emit a JSON-LD @graph")
        crumb = next(n for n in graph if n.get("@type") == "BreadcrumbList")
        names = [i["name"] for i in crumb["itemListElement"]]
        self.assertEqual(names, ["Home", "Prediction accuracy archive"])

    def test_scorecard_teaser_renders(self):
        html = self._html()
        self.assertIn("Latest scorecard", html)
        self.assertIn("August 2026", html)
        self.assertIn("11 days", html)  # headline MAE
        self.assertIn("/predictions/2026-8/", html)  # link to that month's recap

    def test_track_record_links_present(self):
        html = self._html()
        self.assertIn("Model track record", html)
        self.assertIn('href="/spaghetti/"', html)
        self.assertIn('href="/metric-report/"', html)


class BaselineVerdictTest(TestCase):
    """A model that loses to the no-change baseline is said to be losing.

    `beats_baseline` is strict (model mean < baseline mean), so its false branch
    covers both "level with" and "far worse" — and the copy called both of them
    matching. That reads as honest while the page is at parity and becomes a
    false claim the moment the mean moves, which is exactly when a reader is
    relying on it.
    """

    def setUp(self):
        self.client = Client()
        cache.clear()
        prev = Bulletin.objects.create(publication_date=_PREV)
        _actual(prev, "2nd", date(2019, 11, 15))
        target = Bulletin.objects.create(publication_date=_TARGET)
        _actual(target, "2nd", date(2019, 12, 1))  # a 16-day no-change error
        pb = PredictedBulletin.objects.create(
            target_bulletin_month=_TARGET, prediction_date=date(2026, 7, 15)
        )
        PredictedCutoff.objects.create(
            bulletin=pb, visa_class="2nd", country=_INDIA, action_type=_FA,
            predicted_date=date(2020, 6, 1), model_name="ensemble",
        )  # 183 days out — an order worse than doing nothing

    def test_the_model_is_reported_as_losing_not_matching(self):
        self.assertFalse(all_time_track_record()["beats_baseline"])
        html = self.client.get("/predictions/").content.decode()
        self.assertIn("falling behind", html)
        self.assertIn("behind the naive no-change guess", html)
        self.assertNotIn("roughly matching", html)
        self.assertNotIn("matching the naive no-change guess", html)


class RecapBannerTest(TestCase):
    """The per-month recap renders the accuracy rollup banner. Loader is patched
    (as in test_prediction_detail_structured_data) so the page renders the two
    controlled series without invoking the backtest solver for the rest."""

    _LOADER = "webapp.views.prediction_views.get_all_predictions_for_month"

    def setUp(self):
        self.client = Client()
        cache.clear()
        _seed_actuals()

    def _get(self):
        kd = date(2026, 7, 15)
        preds = {
            ("2nd", _INDIA, _FA): PredictionResult(
                predicted_date=date(2019, 12, 10), knowledge_date=kd, source="stored",
                model_name="ensemble",
            ),
            ("3rd", _INDIA, _FA): PredictionResult(
                predicted_date=date(2013, 1, 19), knowledge_date=kd, source="stored",
                model_name="ensemble",
            ),
        }
        with patch(self._LOADER, return_value=(preds, kd)):
            # Canonical archive URL is the monthname slug; the bare-numeric form
            # 301s to it. The recap banner is asserted on the canonical page.
            return self.client.get("/predictions/august-2026/").content.decode()

    def test_banner_renders_with_real_numbers(self):
        html = self._get()
        self.assertIn("How our August 2026 forecast scored", html)
        self.assertIn("11 days", html)  # overall MAE band
        self.assertIn("2 scored dates", html)
        # Per-category bands.
        self.assertIn("EB-2:", html)
        self.assertIn("9d", html)
        self.assertIn("EB-3:", html)
        self.assertIn("13d", html)
        # Honest model-vs-no-change line (model beat baseline this month).
        self.assertIn("beating the no-change baseline", html)
        self.assertIn("2 of 2 scored dates", html)

    def test_banner_links_forward_to_the_upcoming_forecast(self):
        """The recap's forward link names the next month and goes to ITS page.

        It used to read "the next bulletin" and point at the dashboard, which
        left the upcoming-month forecast page with no inbound internal link —
        Google never discovered it before the drop. See
        tests/test_stable_prediction_url.py::TestUpcomingForecastInboundLinks.
        """
        html = self._get()
        self.assertIn("See the live forecast for the September 2026 bulletin", html)
        self.assertIn('href="/predictions/september-2026/"', html)


class SitemapContainsAccuracyPagesTest(TestCase):
    def setUp(self):
        cache.clear()
        Bulletin.objects.create(publication_date=_TARGET)

    def test_predictions_index_and_track_record_pages_listed(self):
        from webapp.views.seo.sitemaps import build_sitemap_xml

        xml = build_sitemap_xml("https://visa-bulletin.us")
        self.assertIn("<loc>https://visa-bulletin.us/predictions/</loc>", xml)
        self.assertIn("<loc>https://visa-bulletin.us/spaghetti/</loc>", xml)
        self.assertIn("<loc>https://visa-bulletin.us/metric-report/</loc>", xml)


class DashboardDeepLinkTest(TestCase):
    """The dashboard 'See backtest' links deep-link to the specific latest month's
    recap (not the category landing that 301s to it). Heavy VQS/chart paths mocked
    (pattern from test_retention_banner.DashboardBakesRecordsTest)."""

    V = "webapp.views.bulletin.dashboard"

    def setUp(self):
        self.client = Client()
        cache.clear()
        Bulletin.objects.create(publication_date=_TARGET)

    def _html(self, url):
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
            return self.client.get(url).content.decode()

    def test_eb_backtest_link_deep_links_latest_month(self):
        html = self._html("/employment-based/india/")
        # Bare-numeric canonical recap URL for the latest confirmed month.
        self.assertIn('href="/predictions/2026-8/"', html)
        # And no longer the category landing that 301s to latest.
        self.assertNotIn('href="/predictions/employment_based/"', html)
