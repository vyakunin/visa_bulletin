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


def _predict(pred_bulletin, action_type, country, visa_class, predicted_date):
    PredictedCutoff.objects.create(
        bulletin=pred_bulletin,
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        predicted_date=predicted_date,
        model_name="regime_switched",
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
        _predict(self.pb, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2020, 3, 1))
        _predict(self.pb, ActionType.FILING.value, Country.INDIA.value, "2nd", date(2020, 8, 1))

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
