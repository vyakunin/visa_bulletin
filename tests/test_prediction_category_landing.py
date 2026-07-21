"""Tests for /predictions/<category>/ redirect to latest bulletin month."""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin


class TestPredictionCategoryLanding(TestCase):
    """Landing URL redirects to prediction_detail_category for latest bulletin."""

    def setUp(self):
        Bulletin.objects.create(publication_date=date(2025, 6, 1))
        Bulletin.objects.create(publication_date=date(2025, 11, 1))

    def test_employment_based_redirects_to_latest_month(self):
        # employment_based canonicalizes to the monthname slug, so the landing
        # redirect points straight there (no employment_based/<y>-<m> hop).
        response = self.client.get("/predictions/employment_based/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "/predictions/november-2025/",
        )

    def test_family_sponsored_redirects_to_latest_month(self):
        response = self.client.get("/predictions/family_sponsored/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "/predictions/family_sponsored/2025-11/",
        )

    def test_unknown_category_404(self):
        response = self.client.get("/predictions/not_a_category/")
        self.assertEqual(response.status_code, 404)

    def test_legacy_year_month_matches_legacy_pattern_and_301s_to_slug(self):
        """predictions/2025-6/ must match the legacy numeric pattern (not
        <str:category>) and 301 to the canonical monthname slug."""
        response = self.client.get("/predictions/2025-6/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/predictions/june-2025/")


class TestPredictionCanonicalScheme(TestCase):
    """One canonical URL per prediction month — the keyword-rich monthname slug.

    Regression guard for the duplicate-content bug: the same page was served at
    /predictions/2025-11/ AND /predictions/employment_based/2025-11/ with no
    canonical tag on either. employment_based canonicalizes to the monthname slug
    (/predictions/november-2025/); the bare-numeric and alias forms both 301
    there. family_sponsored is distinct content and self-canonical under its own
    segment. Full lifecycle coverage: tests/test_stable_prediction_url.py.
    """

    def setUp(self):
        Bulletin.objects.create(publication_date=date(2025, 11, 1))

    def test_employment_based_alias_301s_to_slug(self):
        response = self.client.get("/predictions/employment_based/2025-11/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/predictions/november-2025/")

    def test_numeric_301s_to_slug(self):
        response = self.client.get("/predictions/2025-11/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/predictions/november-2025/")

    def test_slug_page_renders_with_self_canonical(self):
        response = self.client.get("/predictions/november-2025/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" href="http://testserver/predictions/november-2025/">',
            response.content,
        )
        # The employment_based alias must NOT appear as the canonical.
        self.assertNotIn(b"canonical/predictions/employment_based", response.content)

    def test_family_sponsored_does_not_redirect_and_is_self_canonical(self):
        response = self.client.get("/predictions/family_sponsored/2025-11/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" '
            b'href="http://testserver/predictions/family_sponsored/2025-11/">',
            response.content,
        )


class TestPredictionDetailSeoTitles(TestCase):
    """Post-drop archive title/meta.

    The freshest published month serves at the keyword-rich monthname slug
    (/predictions/<month>-<year>/) — the same URL the forecast ranked on — so it
    keeps that ranking exactly when actual-bulletin intent ("visa bulletin
    <month> <year>") peaks and stays high for weeks. Its title must lead with
    "<Month> <Year> Visa Bulletin" and og/meta must be set (regression: they used
    to fall back to the generic sitewide defaults). Older months lead with "Visa
    Bulletin" too but keep predictions-vs-actual framing.
    """

    def setUp(self):
        Bulletin.objects.create(publication_date=date(2025, 6, 1))
        Bulletin.objects.create(publication_date=date(2025, 11, 1))  # latest

    def test_latest_month_leads_with_visa_bulletin_and_official(self):
        body = self.client.get("/predictions/november-2025/").content.decode()
        # <title> (block override) + H1 both use the same string.
        self.assertIn("November 2025 Visa Bulletin", body)
        self.assertIn("Official Employment-Based Dates", body)
        # og:title / twitter:title / meta description are now the page's own,
        # NOT the generic sitewide fallback.
        self.assertIn(
            '<meta property="og:title" content="November 2025 Visa Bulletin', body
        )
        self.assertIn(
            'content="The official November 2025 U.S. Visa Bulletin', body
        )
        # The old generic-default meta description must not be what we ship here.
        self.assertNotIn(
            'content="Priority dates, work visas, and labor market data.', body
        )

    def test_historical_month_keeps_predictions_vs_actual_framing(self):
        # June 2025 is NOT the latest (November 2025 exists after it).
        body = self.client.get("/predictions/june-2025/").content.decode()
        self.assertIn("June 2025 Visa Bulletin", body)
        self.assertIn("Predictions vs Actual Dates", body)
        self.assertNotIn("Official Employment-Based Dates", body)
