"""Tests for employer rankings view."""

import re
from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord
from webapp.views.employers.rankings import _format_count


def _url(**params) -> str:
    base = reverse("employer_rankings")
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"
    return base


class EmployerRankingsViewTest(TestCase):
    """Tests for the employer rankings leaderboard page."""

    def setUp(self):
        self.client = Client()
        cache.clear()

        # Cluster A: heavy PERM sponsor, some H-1B
        self.cluster_a = EmployerCluster.objects.create(
            canonical_name="Alpha Corp",
            slug="alpha-corp",
        )
        self.employer_a = Employer.objects.create(
            name="Alpha Corp",
            name_normalized="alpha corp",
            city="Seattle",
            state="WA",
            canonical_cluster=self.cluster_a,
        )

        # Cluster B: heavy H-1B sponsor, fewer PERM
        self.cluster_b = EmployerCluster.objects.create(
            canonical_name="Beta Inc",
            slug="beta-inc",
        )
        self.employer_b = Employer.objects.create(
            name="Beta Inc",
            name_normalized="beta inc",
            city="Austin",
            state="TX",
            canonical_cluster=self.cluster_b,
        )

        # Cluster C: H-1B only (no PERM), to test exclusion
        self.cluster_c = EmployerCluster.objects.create(
            canonical_name="Gamma LLC",
            slug="gamma-llc",
        )
        self.employer_c = Employer.objects.create(
            name="Gamma LLC",
            name_normalized="gamma llc",
            city="Chicago",
            state="IL",
            canonical_cluster=self.cluster_c,
        )

        def _make(employer, n, program, fy, wage, case_num_prefix):
            for i in range(n):
                SalaryRecord.objects.create(
                    case_number=f"{case_num_prefix}-{fy}-{i}",
                    employer=employer,
                    employer_name=employer.name,
                    job_title="Engineer",
                    wage_annual=wage,
                    visa_program=program,
                    case_status=CaseStatus.CERTIFIED,
                    fiscal_year=fy,
                    case_submitted=date(fy - 1, 6, 1) if program == VisaProgram.H1B else None,
                )

        # Alpha Corp FY2024: 20 PERM + 5 H-1B
        _make(self.employer_a, 20, VisaProgram.PERM, 2024, 150_000, "A-P")
        _make(self.employer_a, 5, VisaProgram.H1B, 2024, 120_000, "A-H")

        # Alpha Corp FY2023: 15 PERM + 3 H-1B
        _make(self.employer_a, 15, VisaProgram.PERM, 2023, 140_000, "A-P23")
        _make(self.employer_a, 3, VisaProgram.H1B, 2023, 110_000, "A-H23")

        # Beta Inc FY2024: 8 PERM + 30 H-1B
        _make(self.employer_b, 8, VisaProgram.PERM, 2024, 130_000, "B-P")
        _make(self.employer_b, 30, VisaProgram.H1B, 2024, 100_000, "B-H")

        # Gamma LLC FY2024: 25 H-1B, 0 PERM
        _make(self.employer_c, 25, VisaProgram.H1B, 2024, 90_000, "C-H")

    # --- Basic smoke ---

    def test_default_view_returns_200(self):
        response = self.client.get(reverse("employer_rankings"))
        self.assertEqual(response.status_code, 200)

    def test_all_programs_returns_200(self):
        response = self.client.get(_url(program="all", period="latest_fy"))
        self.assertEqual(response.status_code, 200)

    def test_perm_filter_returns_200(self):
        response = self.client.get(_url(program="perm", period="fy_2024"))
        self.assertEqual(response.status_code, 200)

    def test_h1b_filter_returns_200(self):
        response = self.client.get(_url(program="h1b", period="latest_fy"))
        self.assertEqual(response.status_code, 200)

    # --- Cross-program counts ---

    def test_perm_filter_shows_nonzero_h1b_count(self):
        """PERM filter: H-1B column must reflect employer's real H-1B filings, not 0."""
        response = self.client.get(_url(program="perm", period="fy_2024"))
        self.assertEqual(response.status_code, 200)
        rankings = response.context["rankings"]
        # Alpha Corp: 5 H-1B filings in FY2024
        alpha = next(r for r in rankings if r["cluster_name"] == "Alpha Corp")
        self.assertEqual(alpha["h1b_count"], 5)
        # Beta Inc: 30 H-1B filings in FY2024
        beta = next(r for r in rankings if r["cluster_name"] == "Beta Inc")
        self.assertEqual(beta["h1b_count"], 30)

    def test_h1b_filter_shows_nonzero_perm_count(self):
        """H-1B filter: PERM column must show real PERM filings, not 0."""
        response = self.client.get(_url(program="h1b", period="fy_2024"))
        self.assertEqual(response.status_code, 200)
        rankings = response.context["rankings"]
        beta = next(r for r in rankings if r["cluster_name"] == "Beta Inc")
        self.assertEqual(beta["perm_count"], 8)

    # --- Sort order ---

    def test_perm_filter_ranked_by_perm_count(self):
        """With PERM filter, list is ranked by perm_count descending."""
        response = self.client.get(_url(program="perm", period="fy_2024"))
        rankings = response.context["rankings"]
        perm_counts = [r["perm_count"] for r in rankings]
        self.assertEqual(perm_counts, sorted(perm_counts, reverse=True))
        # Alpha (20) before Beta (8)
        names = [r["cluster_name"] for r in rankings]
        self.assertLess(names.index("Alpha Corp"), names.index("Beta Inc"))

    def test_h1b_filter_ranked_by_h1b_count(self):
        """With H-1B filter, list is ranked by h1b_count descending."""
        response = self.client.get(_url(program="h1b", period="fy_2024"))
        rankings = response.context["rankings"]
        h1b_counts = [r["h1b_count"] for r in rankings]
        self.assertEqual(h1b_counts, sorted(h1b_counts, reverse=True))

    def test_all_program_ranked_by_total_filings(self):
        """With all-program, list is ranked by total_filings descending."""
        response = self.client.get(_url(program="all", period="fy_2024"))
        rankings = response.context["rankings"]
        totals = [r["total_filings"] for r in rankings]
        self.assertEqual(totals, sorted(totals, reverse=True))

    # --- Exclusion of zero-count employers ---

    def test_perm_filter_excludes_zero_perm_employers(self):
        """Gamma LLC has 0 PERM filings and must not appear in PERM-filtered results."""
        response = self.client.get(_url(program="perm", period="fy_2024"))
        names = [r["cluster_name"] for r in response.context["rankings"]]
        self.assertNotIn("Gamma LLC", names)

    def test_h1b_filter_excludes_zero_h1b_employers(self):
        """An employer with 0 H-1B must not appear when filtering by H-1B."""
        # Create a PERM-only employer
        cluster_perm_only = EmployerCluster.objects.create(
            canonical_name="PermOnly Co",
            slug="permonly-co",
        )
        emp = Employer.objects.create(
            name="PermOnly Co",
            name_normalized="permonly co",
            canonical_cluster=cluster_perm_only,
        )
        for i in range(5):
            SalaryRecord.objects.create(
                case_number=f"PO-{i}",
                employer=emp,
                employer_name="PermOnly Co",
                job_title="Analyst",
                wage_annual=80_000,
                visa_program=VisaProgram.PERM,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2024,
            )

        response = self.client.get(_url(program="h1b", period="fy_2024"))
        names = [r["cluster_name"] for r in response.context["rankings"]]
        self.assertNotIn("PermOnly Co", names)

    # --- PERM FY selector ---

    def test_perm_shows_fy_selector(self):
        """PERM filter must use the FY-based selector, not the standard date selector."""
        response = self.client.get(_url(program="perm", period="fy_2024"))
        self.assertTrue(response.context["use_fy_selector"])

    def test_non_perm_shows_standard_selector(self):
        """H-1B and All filters must use the standard (Latest FY / Last 12 Months) selector."""
        for program in ("h1b", "all"):
            response = self.client.get(_url(program=program, period="latest_fy"))
            self.assertFalse(response.context["use_fy_selector"])

    # --- Period fallback ---

    def test_perm_last_12m_falls_back_to_latest_fy(self):
        """PERM + last_12m has no data (filing dates predate 12m window), falls back to latest FY."""
        response = self.client.get(_url(program="perm", period="last_12m"))
        self.assertEqual(response.status_code, 200)
        # Should not be empty — fallback to latest FY
        self.assertGreater(len(response.context["rankings"]), 0)

    def test_fy_specific_period_filters_correctly(self):
        """?period=fy_2023 must include only FY2023 records."""
        response = self.client.get(_url(program="perm", period="fy_2023"))
        rankings = response.context["rankings"]
        # Alpha Corp has 15 PERM in FY2023
        alpha = next((r for r in rankings if r["cluster_name"] == "Alpha Corp"), None)
        self.assertIsNotNone(alpha)
        self.assertEqual(alpha["perm_count"], 15)
        # Beta Inc has 0 PERM in FY2023, should not appear
        names = [r["cluster_name"] for r in rankings]
        self.assertNotIn("Beta Inc", names)

    def test_all_time_shows_all_fiscal_years(self):
        """?period=all_time must include records from all fiscal years."""
        response = self.client.get(_url(program="perm", period="all_time"))
        rankings = response.context["rankings"]
        # Alpha Corp: 20 (FY2024) + 15 (FY2023) = 35 PERM total
        alpha = next(r for r in rankings if r["cluster_name"] == "Alpha Corp")
        self.assertEqual(alpha["perm_count"], 35)

    # --- Avg salary scoped to program ---

    def test_avg_salary_scoped_to_selected_program(self):
        """Avg salary must reflect the selected program's wages, not all wages."""
        # Alpha Corp PERM wage=150K, H-1B wage=120K in FY2024
        response_perm = self.client.get(_url(program="perm", period="fy_2024"))
        alpha_perm = next(
            r for r in response_perm.context["rankings"] if r["cluster_name"] == "Alpha Corp"
        )
        # avg_salary_k rounded — should be ~150 (PERM wages only)
        self.assertIsNotNone(alpha_perm["avg_salary_k"])
        self.assertAlmostEqual(alpha_perm["avg_salary_k"], 150, delta=5)

        response_h1b = self.client.get(_url(program="h1b", period="fy_2024"))
        alpha_h1b = next(
            r for r in response_h1b.context["rankings"] if r["cluster_name"] == "Alpha Corp"
        )
        # avg_salary_k rounded — should be ~120 (H-1B wages only)
        self.assertIsNotNone(alpha_h1b["avg_salary_k"])
        self.assertAlmostEqual(alpha_h1b["avg_salary_k"], 120, delta=5)

    # perm_ratio column was removed; perm_count and total_filings columns
    # remain so users can compare them directly.

    # --- Mobile column visibility ---
    # Regression: the H-1B/PERM breakdown columns were unconditionally
    # d-none d-md-table-cell, so on phones the only visible number was
    # total_filings — switching the program toggle appeared to change nothing.
    # The selected program's column must stay visible at all widths.

    @staticmethod
    def _column_classes(html: str, col: str) -> list[str]:
        """Class attributes of every th/td cell tagged col-<col>."""
        classes = re.findall(rf'class="([^"]*\bcol-{col}\b[^"]*)"', html)
        assert classes, f"no col-{col} cells found in rendered HTML"
        return classes

    def _assert_column_visibility(self, program: str, visible: str, hidden: tuple[str, ...]):
        response = self.client.get(_url(program=program, period="fy_2024"))
        html = response.content.decode()
        for cls in self._column_classes(html, visible):
            self.assertNotIn(
                "d-none", cls, f"program={program}: col-{visible} must be visible on mobile"
            )
        for col in hidden:
            for cls in self._column_classes(html, col):
                self.assertIn(
                    "d-none d-md-table-cell",
                    cls,
                    f"program={program}: col-{col} should collapse below md",
                )

    def test_perm_filter_perm_column_visible_on_mobile(self):
        self._assert_column_visibility("perm", visible="perm", hidden=("total", "h1b"))

    def test_h1b_filter_h1b_column_visible_on_mobile(self):
        self._assert_column_visibility("h1b", visible="h1b", hidden=("total", "perm"))

    def test_all_program_total_column_visible_on_mobile(self):
        self._assert_column_visibility("all", visible="total", hidden=("h1b", "perm"))


class FormatCountTest(TestCase):
    """Unit tests for the _format_count helper."""

    def test_small_numbers_returned_as_string(self):
        self.assertEqual(_format_count(0), "0")
        self.assertEqual(_format_count(999), "999")

    def test_thousands_formatted_with_k(self):
        self.assertEqual(_format_count(1000), "1K")
        self.assertEqual(_format_count(91971), "92K")
        self.assertEqual(_format_count(114109), "114K")

    def test_millions_formatted_with_m(self):
        self.assertEqual(_format_count(1_000_000), "1.0M")
        self.assertEqual(_format_count(1_500_000), "1.5M")
