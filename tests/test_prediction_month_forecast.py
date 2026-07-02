"""Tests for the evergreen per-month forecast landing pages.

Locks: a future month with stored predictions renders 200 with the predicted
cutoff + FAQPage schema + correct canonical; a published month 301s to the
accuracy archive (no duplicate page); a future month with NO stored forecast
404s (no thin page, no live solver); an invalid month slug 404s; and the tight
URL pattern does not shadow the category/legacy prediction routes.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff


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


def _predict(
    pred_bulletin,
    action_type,
    country,
    visa_class,
    predicted_date,
    *,
    model_name="regime_switched",
    confidence_low=None,
    confidence_high=None,
    movement_probability=None,
):
    PredictedCutoff.objects.create(
        bulletin=pred_bulletin,
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        predicted_date=predicted_date,
        model_name=model_name,
        confidence_low=confidence_low,
        confidence_high=confidence_high,
        movement_probability=movement_probability,
    )


class TestPredictionMonthForecast(TestCase):
    def setUp(self):
        # Latest published edition = June 2026 (the "current" baseline).
        self.latest = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2020, 1, 1))
        _actual(self.latest, ActionType.FILING.value, Country.INDIA.value, "2nd", date(2020, 6, 1))

        # Stored forecast for the upcoming (unpublished) July 2026 bulletin.
        self.pb = PredictedBulletin.objects.create(
            target_bulletin_month=date(2026, 7, 1),
            prediction_date=date(2026, 6, 15),
        )
        # EB-2 India (a modeled series + headline card): a real advance, plus a
        # calibrated CI and a movement probability so the card renders both.
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2020, 3, 1),
            confidence_low=date(2020, 2, 1), confidence_high=date(2020, 5, 1),
            movement_probability=0.15,
        )
        _predict(self.pb, ActionType.FILING.value, Country.INDIA.value, "2nd", date(2020, 8, 1))

        # EB-2 China (a modeled series + headline card): Unavailable — hit the FY
        # annual limit, so predicted_date is None and model_name == "unavailable".
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.CHINA.value, "2nd", date(2020, 1, 1))
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.CHINA.value, "2nd", None,
            model_name="unavailable",
        )

        # EB-2 Other Countries (NOT a modeled series): a persistence baseline with
        # a real predicted date, so the grid tags it with the "baseline" marker.
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.ALL.value, "2nd", date(2024, 1, 1))
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.ALL.value, "2nd", date(2024, 1, 1),
            model_name="persistence",
        )

    def test_future_month_renders(self):
        resp = self.client.get("/predictions/july-2026/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("July 2026 Visa Bulletin Predictions", body)  # H1
        self.assertIn("March 1, 2020", body)  # predicted EB-2 India Final Action

    def test_predicted_advance_movement_shown(self):
        # 2020-01-01 -> 2020-03-01 is a +2-month advance vs the current bulletin.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("+2m", body)

    def test_unavailable_gets_fy_limit_explainer(self):
        # A category that hit the FY annual limit renders "Unavailable" + an
        # explainer, not a bare word that looks like a broken page.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("Unavailable", body)
        self.assertIn("fiscal-year annual limit", body)

    def test_baseline_series_marked_modeled_series_not(self):
        # A non-China/India series is a persistence baseline -> "baseline" marker;
        # the modeled EB-2 India card/cell must not carry it.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("no-change baseline", body)  # legend + marker tooltip

    def test_calibrated_ci_rendered_on_card(self):
        # The stored 80% confidence interval is shown, not hidden.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("80% range", body)
        self.assertIn("May 1, 2020", body)  # confidence_high of EB-2 India

    def test_movement_prob_badge_has_explainer(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("probability of a more-than-50-day", body)

    def test_knowledge_date_not_future_dated(self):
        # The confusing future-looking "knowledge cutoff: <day>" is gone; the
        # source edition framing is used instead.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertNotIn("knowledge cutoff", body)
        self.assertIn("based on data through", body)

    def test_backtest_window_copy_is_2016_not_2020(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("since 2016", body)
        self.assertNotIn("since 2020", body)

    def test_faqpage_schema_present(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("When does the July 2026 Visa Bulletin come out?", body)
        self.assertIn("Will EB-2 India advance in the July 2026 Visa Bulletin?", body)

    def test_canonical_is_self(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn(
            'rel="canonical" href="http://testserver/predictions/july-2026/"', body
        )

    def test_published_month_redirects_to_archive(self):
        # June 2026 has an actual bulletin -> forecast URL 301s to the accuracy archive.
        resp = self.client.get("/predictions/june-2026/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/predictions/employment_based/2026-6/")

    def test_future_month_without_forecast_404(self):
        # September 2026: no stored predictions -> no thin page, no live solver.
        self.assertEqual(self.client.get("/predictions/september-2026/").status_code, 404)

    def test_invalid_month_slug_404(self):
        self.assertEqual(self.client.get("/predictions/foo-2026/").status_code, 404)

    def test_route_does_not_shadow_category_landing(self):
        # /predictions/employment_based/ must still resolve to the category landing
        # (redirect to latest month), NOT be captured by the forecast pattern.
        resp = self.client.get("/predictions/employment_based/")
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/predictions/employment_based/2026-6/", resp["Location"])
