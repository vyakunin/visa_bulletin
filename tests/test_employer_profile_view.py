"""Tests for employer profile view"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from models.enums.visa_program import CaseStatus, VisaProgram
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord


class EmployerProfileViewTest(TestCase):
    """Test employer profile view functionality"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()
        cache.clear()

        # Create test employer cluster with slug
        self.cluster = EmployerCluster.objects.create(
            canonical_name="Test Company LLC",
            slug="test-company-llc",
            total_lca_count=100,
            total_perm_count=50,
        )

        # Create test employer
        self.employer = Employer.objects.create(
            name="Test Company",
            name_normalized="test company",
            city="San Francisco",
            state="CA",
            canonical_cluster=self.cluster,
        )

        # Clustered job titles — the profile view's top_titles derives from
        # job_title_entity__canonical_cluster, so raw job_title strings alone
        # produce no top titles. Wire JobTitleCluster + JobTitle for each title.
        self.job_titles = {}
        for raw_title in ("Software Engineer", "Data Scientist"):
            cluster = JobTitleCluster.objects.create(canonical_title=raw_title)
            self.job_titles[raw_title] = JobTitle.objects.create(
                title=raw_title,
                title_normalized=raw_title.lower(),
                canonical_cluster=cluster,
            )

        # Create test salary records
        for i in range(10):
            raw_title = "Software Engineer" if i < 5 else "Data Scientist"
            SalaryRecord.objects.create(
                case_number=f"TEST-{i}",
                employer=self.employer,
                employer_name="Test Company",
                job_title=raw_title,
                job_title_entity=self.job_titles[raw_title],
                wage_annual=100000 + (i * 10000),
                visa_program=VisaProgram.H1B if i < 7 else VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED if i < 8 else CaseStatus.DENIED,
                fiscal_year=2023,
                worksite_state="CA" if i < 6 else "NY",
            )

    def test_basic_rendering(self):
        """Test that profile page renders successfully for valid slug"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Company LLC")
        self.assertContains(response, "Green Card Sponsorship Data")

    def test_redirect_handling(self):
        """Test that invalid slug redirects to canonical URL"""
        # Create another employer with different name in same cluster
        Employer.objects.create(
            name="Test Company Inc",
            name_normalized="test company inc",
            city="New York",
            state="NY",
            canonical_cluster=self.cluster,
        )

        # Try accessing with non-canonical slug
        url = reverse("employer_profile", kwargs={"slug": "test-company-inc"})
        response = self.client.get(url)

        # Should redirect to canonical slug
        self.assertEqual(response.status_code, 301)
        self.assertIn("/employer/test-company-llc/", response.url)

    def test_404_handling(self):
        """Test that non-existent employer returns 404"""
        url = reverse("employer_profile", kwargs={"slug": "non-existent-company"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_statistics_accuracy(self):
        """Test that approval rate and median salary computed correctly"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that stats are in context
        self.assertIn("stats", response.context)
        stats = response.context["stats"]

        # Check basic stats
        self.assertEqual(stats["basic"]["total_filings"], 10)
        self.assertEqual(stats["basic"]["approved_filings"], 8)

        # Check approval rate (8 out of 10 certified = 80%)
        self.assertAlmostEqual(stats["approval_rate"], 80.0, places=1)

        # Check median salary (should be around 145000)
        self.assertIsNotNone(stats["basic"]["median_salary"])

    def test_program_filter_h1b(self):
        """Test that program filter (H-1B) works correctly"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url, {"program": "h1b"})

        self.assertEqual(response.status_code, 200)
        stats = response.context["stats"]

        # Should only count H-1B records (7 out of 10)
        self.assertEqual(stats["basic"]["total_filings"], 7)

    def test_program_filter_perm(self):
        """Test that program filter (PERM) works correctly"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url, {"program": "perm"})

        self.assertEqual(response.status_code, 200)
        stats = response.context["stats"]

        # Should only count PERM records (3 out of 10)
        self.assertEqual(stats["basic"]["total_filings"], 3)

    def test_recent_activity_program_display_uses_enum_labels(self):
        """Recent filing activity by_program rows have program_display from VisaProgram.short_display."""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        by_program = response.context["stats"].get("recent_activity", {}).get("by_program") or []
        self.assertGreater(len(by_program), 0)
        program_labels = {row["program_display"] for row in by_program}
        self.assertIn("H-1B", program_labels)
        self.assertIn("PERM", program_labels)
        for row in by_program:
            self.assertIn(row["program_display"], ("H-1B", "H-1B1", "E-3", "PERM", "Other"))

    def test_year_range_filter(self):
        """Test that configurable year range filters data correctly"""
        # Create records for different years
        for year in [2020, 2021, 2022]:
            SalaryRecord.objects.create(
                case_number=f"TEST-{year}",
                employer=self.employer,
                employer_name="Test Company",
                job_title="Software Engineer",
                wage_annual=100000,
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=year,
                worksite_state="CA",
            )

        # Test with 3 year range
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url, {"years": 3})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["years"], 3)

    def test_empty_data_handling(self):
        """Test graceful handling when employer has no filings"""
        # Create cluster with no salary records
        empty_cluster = EmployerCluster.objects.create(
            canonical_name="Empty Company",
            slug="empty-company",
            total_lca_count=0,
            total_perm_count=0,
        )

        Employer.objects.create(
            name="Empty Company",
            name_normalized="empty company",
            canonical_cluster=empty_cluster,
        )

        url = reverse("employer_profile", kwargs={"slug": "empty-company"})
        response = self.client.get(url)

        # Should render without errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Empty Company")

    def test_top_job_titles(self):
        """Test that top job titles are displayed correctly"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        stats = response.context["stats"]

        # Should have top titles
        self.assertIn("top_titles", stats)
        self.assertGreater(len(stats["top_titles"]), 0)

        # Should be ordered by count
        if len(stats["top_titles"]) > 1:
            self.assertGreaterEqual(
                stats["top_titles"][0]["count"], stats["top_titles"][1]["count"]
            )

    def test_geographic_distribution(self):
        """Test geographic distribution data"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        stats = response.context["stats"]

        # Should have state distribution
        self.assertIn("state_dist", stats)
        self.assertGreater(len(stats["state_dist"]), 0)

        # Should contain CA and NY states
        states = [s["worksite_state"] for s in stats["state_dist"]]
        self.assertIn("CA", states)
        self.assertIn("NY", states)

    def test_cache_effectiveness(self):
        """Test that caching works correctly"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})

        # First request (cold cache)
        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)

        # Second request (should hit cache)
        response2 = self.client.get(url)
        self.assertEqual(response2.status_code, 200)

        # Content should be the same
        self.assertEqual(response1.content, response2.content)

    def test_seo_metadata(self):
        """Test that SEO metadata is present in context AND rendered in HTML"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that SEO context is present
        self.assertIn("seo", response.context)
        seo = response.context["seo"]

        # Check required SEO fields
        self.assertIn("title", seo)
        self.assertIn("description", seo)
        self.assertIn("canonical_url", seo)

        # Check that title contains company name
        self.assertIn("Test Company LLC", seo["title"])

        # Verify SEO tags are actually rendered in HTML (not silently dropped)
        content = response.content.decode()
        self.assertIn('<meta name="description"', content)
        self.assertIn('<link rel="canonical"', content)
        self.assertIn('<meta property="og:title"', content)
        self.assertIn("application/ld+json", content)

    def test_chart_data_generated(self):
        """Test that chart data is generated for Plotly"""
        url = reverse("employer_profile", kwargs={"slug": "test-company-llc"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that chart data is in context
        self.assertIn("chart_data", response.context)
        chart_data = response.context["chart_data"]

        # Should have at least some chart data
        self.assertIsInstance(chart_data, dict)
        self.assertIn("state_filings", chart_data)
        self.assertIn("state_median_salary", chart_data)
        self.assertIn("salary_histogram", chart_data)

        stats = response.context["stats"]
        self.assertIn("salary_percentiles", stats)
        self.assertIn("salary_histogram", stats)


class EmployerSlugGenerationTest(TestCase):
    """Test slug generation for employer clusters"""

    def test_slug_auto_generated_on_save(self):
        """Test that slug is auto-generated when creating new cluster"""
        cluster = EmployerCluster.objects.create(canonical_name="Google LLC")

        self.assertIsNotNone(cluster.slug)
        self.assertEqual(cluster.slug, "google-llc")

    def test_slug_uniqueness(self):
        """Test that slugs are unique with counter suffix"""
        # Create first cluster
        cluster1 = EmployerCluster.objects.create(canonical_name="Test Company")
        self.assertEqual(cluster1.slug, "test-company")

        # Create second cluster with same name
        cluster2 = EmployerCluster.objects.create(canonical_name="Test Company")
        self.assertEqual(cluster2.slug, "test-company-1")

        # Create third cluster with same name
        cluster3 = EmployerCluster.objects.create(canonical_name="Test Company")
        self.assertEqual(cluster3.slug, "test-company-2")

    def test_slug_from_special_characters(self):
        """Test that special characters are handled in slug"""
        cluster = EmployerCluster.objects.create(canonical_name="AT&T Corp.")

        # Should convert to URL-safe format
        self.assertEqual(cluster.slug, "att-corp")


class SitemapTest(TestCase):
    """Test sitemap generation"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()

        # Create test employer clusters
        for i in range(5):
            _cluster = EmployerCluster.objects.create(
                canonical_name=f"Company {i}",
                slug=f"company-{i}",
                total_lca_count=10 + i,  # All have >= 5 filings
            )

    def test_sitemap_includes_employer_profiles(self):
        """Test that sitemap includes employer profile URLs"""
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")

        # Check that employer profile URLs are included
        content = response.content.decode("utf-8")
        self.assertIn("/employer/company-0/", content)
        self.assertIn("/employer/company-4/", content)

    def test_sitemap_excludes_low_filing_employers(self):
        """Test that employers with < 5 filings are excluded"""
        # Create employer with only 2 filings
        _low_cluster = EmployerCluster.objects.create(
            canonical_name="Low Volume Company",
            slug="low-volume-company",
            total_lca_count=2,
        )

        response = self.client.get("/sitemap.xml")
        content = response.content.decode("utf-8")

        # Should not include low-volume employer
        self.assertNotIn("/employer/low-volume-company/", content)
