"""Tests for employer directory view (stored counts, keyset pagination, state filter)."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord


class EmployerDirectoryViewTest(TestCase):
    """Test employer directory view: stored counts, keyset pagination, state filter."""

    def setUp(self):
        self.client = Client()
        cache.clear()

        # Cluster with filings (stored counts set)
        self.cluster_a = EmployerCluster.objects.create(
            canonical_name="Company A LLC",
            slug="company-a-llc",
            total_lca_count=10,
            total_perm_count=5,
        )
        self.employer_a = Employer.objects.create(
            name="Company A",
            name_normalized="company a",
            city="San Francisco",
            state="CA",
            canonical_cluster=self.cluster_a,
        )
        for i in range(10):
            SalaryRecord.objects.create(
                case_number=f"CA-{i}",
                employer=self.employer_a,
                employer_name="Company A",
                job_title="Engineer",
                wage_annual=100000,
                visa_program=VisaProgram.H1B if i < 7 else VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2023,
                worksite_state="CA" if i < 6 else "NY",
                is_worksite=False,
            )

        # Second cluster
        self.cluster_b = EmployerCluster.objects.create(
            canonical_name="Company B Inc",
            slug="company-b-inc",
            total_lca_count=5,
            total_perm_count=2,
        )
        self.employer_b = Employer.objects.create(
            name="Company B",
            name_normalized="company b",
            city="Austin",
            state="TX",
            canonical_cluster=self.cluster_b,
        )
        for i in range(5):
            SalaryRecord.objects.create(
                case_number=f"CB-{i}",
                employer=self.employer_b,
                employer_name="Company B",
                job_title="Analyst",
                wage_annual=90000,
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2023,
                worksite_state="TX",
                is_worksite=False,
            )

    def test_directory_returns_200_and_uses_stored_counts(self):
        """Directory returns 200 and rows have total_lca_count/total_perm_count (no actual_*)."""
        response = self.client.get(reverse("employer_directory"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("employers", response.context)
        employers = list(response.context["employers"])
        self.assertGreaterEqual(len(employers), 2)
        for emp in employers:
            self.assertIsNotNone(getattr(emp, "total_lca_count", None))
            self.assertIsNotNone(getattr(emp, "total_perm_count", None))
        self.assertContains(response, "Company A LLC")
        self.assertContains(response, "Company B Inc")
        self.assertContains(response, "10")  # H-1B count for A
        self.assertContains(response, "5")  # PERM count for A

    def test_keyset_next_page_different_and_ordered(self):
        """Page 1 then cursor=next_cursor returns second page; no duplicates; correct order."""
        url = reverse("employer_directory")
        response1 = self.client.get(url)
        self.assertEqual(response1.status_code, 200)
        next_cursor = response1.context.get("next_cursor")
        if not next_cursor:
            self.skipTest("Only one page of results; cannot test keyset next")
        page1_ids = [e.id for e in response1.context["employers"]]
        response2 = self.client.get(f"{url}?page=2&cursor={next_cursor}&program=all")
        self.assertEqual(response2.status_code, 200)
        page2_ids = [e.id for e in response2.context["employers"]]
        for pid in page2_ids:
            self.assertNotIn(pid, page1_ids)
        if page1_ids and page2_ids:
            last_order_a = (
                response1.context["employers"][-1].total_lca_count
                + response1.context["employers"][-1].total_perm_count
            )
            first_order_b = (
                response2.context["employers"][0].total_lca_count
                + response2.context["employers"][0].total_perm_count
            )
            self.assertLessEqual(
                first_order_b,
                last_order_a,
                "Second page should be ordered after first (by total count)",
            )

    def test_state_filter_restricts_to_clusters_with_filings_in_state(self):
        """State filter shows only clusters that have at least one filing in that state."""
        response_all = self.client.get(reverse("employer_directory"))
        self.assertEqual(response_all.status_code, 200)
        total_all = response_all.context["total_results"]

        response_ca = self.client.get(reverse("employer_directory") + "?state=CA")
        self.assertEqual(response_ca.status_code, 200)
        self.assertLessEqual(
            response_ca.context["total_results"],
            total_all,
            "CA filter should not increase total",
        )
        self.assertIn("Company A LLC", response_ca.content.decode())
        for emp in response_ca.context["employers"]:
            self.assertIsNotNone(emp.slug)

    def test_program_filter_ordering(self):
        """Program filter h1b/perm changes ordering (by total_lca_count or total_perm_count)."""
        response_all = self.client.get(reverse("employer_directory") + "?program=all")
        response_h1b = self.client.get(reverse("employer_directory") + "?program=h1b")
        response_perm = self.client.get(reverse("employer_directory") + "?program=perm")
        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(response_h1b.status_code, 200)
        self.assertEqual(response_perm.status_code, 200)
        employers_all = list(response_all.context["employers"])
        employers_h1b = list(response_h1b.context["employers"])
        employers_perm = list(response_perm.context["employers"])
        if len(employers_all) >= 2:
            self.assertEqual(
                employers_h1b[0].total_lca_count,
                max(e.total_lca_count for e in employers_h1b),
                "First row for h1b should have max total_lca_count",
            )
            self.assertEqual(
                employers_perm[0].total_perm_count,
                max(e.total_perm_count for e in employers_perm),
                "First row for perm should have max total_perm_count",
            )
