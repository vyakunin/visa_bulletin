"""Tests for stale profile-slug 301 resolution and the job-title thin-page gate.

Regressions covered (2026-07-04, post 06-25 PERM re-cluster):
- slash-less profile URLs 404ed (no CommonMiddleware -> APPEND_SLASH never ran)
- stale re-clustered slugs (requisition-id / uniqueness suffixes) 404ed because
  the old fallback only tried a whole-slug icontains
- employer stale slugs containing generic words ("-inc") never matched
  name_normalized (the normalizer strips those words)
- hyper-specific low-filing job-title pages were indexable (thin-page /
  scaled-content-abuse suspect) and sitemap-listed at >=10 filings
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from decimal import Decimal

from django.test import Client, TestCase, override_settings

from lib.business.salary.job_title_stats import INDEXABLE_MIN_FILINGS
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster

_DUMMY_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}
}


@override_settings(CACHES=_DUMMY_CACHE)
class TestAppendSlashRedirect(TestCase):
    """Slash-less profile URLs must 301 to the canonical slashed route
    (regression: MIDDLEWARE lacked CommonMiddleware, so /job-title/lawyers
    404ed while /job-title/lawyers/ was 200)."""

    def setUp(self):
        JobTitleCluster.objects.get_or_create(
            slug="lawyers-test",
            defaults={"canonical_title": "Lawyers Test", "total_filings": 200},
        )

    def test_slashless_job_title_url_redirects(self):
        response = Client().get("/job-title/lawyers-test", follow=False)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/job-title/lawyers-test/")


@override_settings(CACHES=_DUMMY_CACHE)
class TestJobTitleStaleSlugRedirect(TestCase):
    """Stale /job-title/ slugs resolve to the current canonical slug."""

    def setUp(self):
        self.cluster, _ = JobTitleCluster.objects.get_or_create(
            slug="dairy-derivatives-trader",
            defaults={
                "canonical_title": "Dairy Derivatives Trader",
                "total_filings": 150,
            },
        )
        JobTitle.objects.get_or_create(
            title_normalized="dairy derivatives trader",
            experience_level="",
            defaults={
                "title": "Dairy Derivatives Trader",
                "canonical_cluster": self.cluster,
            },
        )

    def test_requisition_suffix_slug_redirects(self):
        """Old uniqueness/requisition suffixes strip back to the base slug."""
        response = Client().get(
            "/job-title/dairy-derivatives-trader-kbgfjg353961-1/", follow=False
        )
        self.assertEqual(response.status_code, 301)
        self.assertIn("/job-title/dairy-derivatives-trader/", response["Location"])

    def test_exact_title_match_redirects(self):
        """A slug matching an existing title_normalized redirects to its cluster."""
        stale_cluster_slug = "dairy-derivatives-trader-2"
        response = Client().get(f"/job-title/{stale_cluster_slug}/", follow=False)
        self.assertEqual(response.status_code, 301)
        self.assertIn("/job-title/dairy-derivatives-trader/", response["Location"])

    def test_seniority_prefixed_slug_redirects_via_normalizer(self):
        """normalize_title strips seniority, so sr-<title> finds the entity."""
        response = Client().get(
            "/job-title/sr-dairy-derivatives-trader/", follow=False
        )
        self.assertEqual(response.status_code, 301)
        self.assertIn("/job-title/dairy-derivatives-trader/", response["Location"])

    def test_garbage_slug_404s(self):
        response = Client().get("/job-title/zzz-nonexistent-title-xyz/", follow=False)
        self.assertEqual(response.status_code, 404)


@override_settings(CACHES=_DUMMY_CACHE)
class TestEmployerStaleSlugRedirect(TestCase):
    """Stale /employer/ slugs resolve to the current canonical slug."""

    def setUp(self):
        self.cluster, _ = EmployerCluster.objects.get_or_create(
            slug="galaxsystems-current",
            defaults={"canonical_name": "Galax Esystems Corporation"},
        )
        Employer.objects.get_or_create(
            name="Galax Esystems Corporation",
            defaults={
                # What Employer.normalize_name produces: generic words
                # ("corporation") stripped.
                "name_normalized": Employer.normalize_name(
                    "Galax Esystems Corporation"
                ),
                "city": "Austin",
                "state": "TX",
                "canonical_cluster": self.cluster,
            },
        )

    def test_generic_word_slug_redirects_via_normalizer(self):
        """A stale slug carrying stripped generic words still matches
        name_normalized once run through the same normalizer."""
        response = Client().get(
            "/employer/galax-esystems-corporation/", follow=False
        )
        self.assertEqual(response.status_code, 301)
        self.assertIn("/employer/galaxsystems-current/", response["Location"])

    def test_suffix_stripped_slug_redirects(self):
        response = Client().get(
            "/employer/galaxsystems-current-2/", follow=False
        )
        self.assertEqual(response.status_code, 301)
        self.assertIn("/employer/galaxsystems-current/", response["Location"])

    def test_garbage_slug_404s(self):
        response = Client().get("/employer/zzz-nonexistent-employer/", follow=False)
        self.assertEqual(response.status_code, 404)


@override_settings(CACHES=_DUMMY_CACHE)
class TestJobTitleThinPageGate(TestCase):
    """Profiles below INDEXABLE_MIN_FILINGS are noindexed and sitemap-excluded."""

    def setUp(self):
        self.thin, _ = JobTitleCluster.objects.get_or_create(
            slug="thin-requisition-role",
            defaults={
                "canonical_title": "Thin Requisition Role",
                "total_filings": 3,
                "avg_salary": Decimal("90000.00"),
            },
        )
        self.fat, _ = JobTitleCluster.objects.get_or_create(
            slug="fat-popular-role",
            defaults={
                "canonical_title": "Fat Popular Role",
                "total_filings": INDEXABLE_MIN_FILINGS,
                "avg_salary": Decimal("120000.00"),
            },
        )

    def test_thin_profile_is_noindexed_but_renders(self):
        response = Client().get("/job-title/thin-requisition-role/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta name="robots" content="noindex, follow">')

    def test_qualifying_profile_is_indexable(self):
        response = Client().get("/job-title/fat-popular-role/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "noindex")

    def test_sitemap_excludes_thin_includes_fat(self):
        response = Client().get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("/job-title/thin-requisition-role/", body)
        self.assertIn("/job-title/fat-popular-role/", body)
