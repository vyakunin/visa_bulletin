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
        # employment_based canonicalizes to the bare numeric URL, so the landing
        # redirect points straight there (no employment_based/<y>-<m> hop).
        response = self.client.get("/predictions/employment_based/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "/predictions/2025-11/",
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

    def test_legacy_year_month_still_works_before_category_route(self):
        """predictions/2025-6/ must match legacy pattern, not <str:category>."""
        response = self.client.get("/predictions/2025-6/")
        self.assertEqual(response.status_code, 200)


class TestPredictionCanonicalScheme(TestCase):
    """One canonical URL per prediction month.

    Regression guard for the duplicate-content bug: the same page was served at
    /predictions/2025-11/ AND /predictions/employment_based/2025-11/ with no
    canonical tag on either. employment_based canonicalizes to the bare numeric
    form (301 the alias, self-canonical on the numeric); family_sponsored is
    distinct content and self-canonical under its own segment.
    """

    def setUp(self):
        Bulletin.objects.create(publication_date=date(2025, 11, 1))

    def test_employment_based_alias_301s_to_numeric(self):
        response = self.client.get("/predictions/employment_based/2025-11/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/predictions/2025-11/")

    def test_numeric_page_renders_with_self_canonical(self):
        response = self.client.get("/predictions/2025-11/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" href="http://testserver/predictions/2025-11/">',
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
