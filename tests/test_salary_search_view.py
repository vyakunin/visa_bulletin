"""Tests for salary search landing page behavior."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from models.enums.visa_program import CaseStatus, VisaProgram
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord


class SalarySearchLandingViewTest(TestCase):
    """Test salary search landing page overview behavior."""

    def setUp(self):
        self.client = Client()
        cache.clear()

        employer_cluster = EmployerCluster.objects.create(
            canonical_name="Landing Test Co",
            slug="landing-test-co",
        )
        employer = Employer.objects.create(
            name="Landing Test Co",
            name_normalized="landing test co",
            canonical_cluster=employer_cluster,
        )
        job_cluster = JobTitleCluster.objects.create(
            canonical_title="Landing Engineer",
            slug="landing-engineer",
        )
        job_title = JobTitle.objects.create(
            title="Landing Engineer",
            title_normalized="landing engineer",
            canonical_cluster=job_cluster,
        )

        SalaryRecord.objects.create(
            case_number="LANDING-TEST-1",
            employer=employer,
            employer_name="Landing Test Co",
            job_title="Landing Engineer",
            job_title_entity=job_title,
            wage_annual=120000,
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2023,
            worksite_state="CA",
            is_worksite=False,
        )
        SalaryRecord.objects.create(
            case_number="LANDING-TEST-2",
            employer=employer,
            employer_name="Landing Test Co",
            job_title="Landing Engineer",
            job_title_entity=job_title,
            wage_annual=135000,
            visa_program=VisaProgram.PERM,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
            worksite_state="NY",
            is_worksite=False,
        )

    def test_landing_shows_market_overview(self):
        response = self.client.get(reverse("salary_search"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("market_stats", response.context)
        self.assertIsNotNone(response.context["market_stats"])
        self.assertIn("salary_percentiles", response.context["market_stats"])
        self.assertIn("market_chart_data", response.context)
        market_chart_data = response.context["market_chart_data"]
        self.assertIn("state_filings", market_chart_data)
        self.assertIn("filing_volume", market_chart_data)

    def test_filtered_view_hides_market_overview(self):
        response = self.client.get(reverse("salary_search"), {"q": "Landing"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_filters"])
        self.assertIsNone(response.context["market_stats"])
        self.assertEqual(response.context["market_chart_data"], {})
