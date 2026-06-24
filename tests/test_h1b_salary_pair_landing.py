"""Tests for the per-(employer × role) H-1B salary pages.

Locks: a pair with a substantive salary distribution renders 200 with the
percentile band + market-comparison + FAQPage + self-canonical + outbound mesh;
a thin pair / sub-threshold pair / PERM-heavy pair / unknown slug all 404 (no
thin page); the sitemap lists qualifying pairs only (never a 404); the
qualifying-pair gate is shared (lib/business/salary/h1b_salary_pair.py); and the
h1b-sponsors role page links a qualifying employer's wage cell to the pair page
(gated cross-mesh).
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from lib.business.salary.h1b_salary_pair import qualifying_pairs
from models.enums.visa_program import VisaProgram
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord


def _make_role(slug: str, title: str) -> JobTitle:
    cluster = JobTitleCluster.objects.create(
        slug=slug, canonical_title=title, total_filings=0
    )
    return JobTitle.objects.create(
        title=title, title_normalized=title.lower(), canonical_cluster=cluster
    )


def _make_employer(slug: str, name: str) -> Employer:
    ec = EmployerCluster.objects.create(slug=slug, canonical_name=name)
    return Employer.objects.create(
        name=name, name_normalized=name.lower(), city="San Francisco",
        state="CA", canonical_cluster=ec,
    )


def _add(jt, employer, program, n, *, start_case, state="CA", wage=120000):
    for i in range(n):
        SalaryRecord.objects.create(
            case_number=f"{start_case}-{i}",
            visa_program=program,
            employer=employer,
            employer_name=employer.name,
            job_title_entity=jt,
            job_title=jt.title,
            wage_annual=Decimal(str(wage + i * 1000)),
            worksite_state=state,
            is_worksite=False,
            fiscal_year=2024 + (i % 2),
        )


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class TestH1BSalaryPairLanding(TestCase):
    def setUp(self):
        cache.clear()
        self.role = _make_role("software-engineer", "Software Engineer")

        # Google × SWE: 12 H-1B filings → QUALIFIES as a pair (>= 10).
        self.google = _make_employer("google-llc", "Google LLC")
        _add(self.role, self.google, VisaProgram.H1B, 12,
             start_case="GOOG-SWE", wage=150000)

        # 7 more employers × 6 H-1B filings on SWE → each pair is sub-threshold
        # (< 10) but together the ROLE clears the h1b-sponsors gate (>=50 filings,
        # >=8 sponsors): 12 + 7*6 = 54 filings, 8 sponsors.
        self.others = []
        for idx in range(7):
            emp = _make_employer(f"employer-{idx}", f"Employer {idx} Inc")
            self.others.append(emp)
            _add(self.role, emp, VisaProgram.H1B, 6,
                 start_case=f"OTH{idx}-SWE", wage=110000 + idx * 2000)

        # Thin pair: Google × Data Clerk, 3 H-1B filings → 404.
        self.clerk = _make_role("data-clerk", "Data Clerk")
        _add(self.clerk, self.google, VisaProgram.H1B, 3, start_case="GOOG-CLK")

        # PERM-heavy pair: 10 PERM, 0 H-1B → 404 (H-1B only).
        self.perm_role = _make_role("perm-role", "Perm Role")
        self.permco = _make_employer("perm-co", "Perm Co")
        _add(self.perm_role, self.permco, VisaProgram.PERM, 10, start_case="PERMCO")

    def test_qualifying_pair_renders(self):
        resp = self.client.get("/h1b-salary/google-llc/software-engineer/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Software Engineer Salary at Google LLC", body)  # H1
        self.assertIn("Salary distribution", body)  # percentile band
        self.assertIn("/employer/google-llc/", body)  # outbound mesh
        self.assertIn("/job-title/software-engineer/", body)
        self.assertIn("/h1b-sponsors/software-engineer/", body)

    def test_faqpage_schema_and_canonical(self):
        body = self.client.get(
            "/h1b-salary/google-llc/software-engineer/"
        ).content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("Does Google LLC sponsor H-1B", body)
        self.assertIn(
            'rel="canonical" '
            'href="http://testserver/h1b-salary/google-llc/software-engineer/"',
            body,
        )

    def test_thin_pair_404(self):
        self.assertEqual(
            self.client.get("/h1b-salary/google-llc/data-clerk/").status_code, 404
        )

    def test_subthreshold_pair_404(self):
        # employer-0 × SWE has 6 H-1B filings (< 10).
        self.assertEqual(
            self.client.get("/h1b-salary/employer-0/software-engineer/").status_code,
            404,
        )

    def test_perm_heavy_pair_404_h1b_only(self):
        self.assertEqual(
            self.client.get("/h1b-salary/perm-co/perm-role/").status_code, 404
        )

    def test_unknown_slugs_404(self):
        self.assertEqual(
            self.client.get("/h1b-salary/no-such-emp/software-engineer/").status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/h1b-salary/google-llc/no-such-role/").status_code, 404
        )

    def test_qualifying_pairs_gate(self):
        pairs = set(qualifying_pairs())
        self.assertIn(("google-llc", "software-engineer"), pairs)
        self.assertNotIn(("employer-0", "software-engineer"), pairs)  # sub-threshold
        self.assertNotIn(("google-llc", "data-clerk"), pairs)  # thin
        self.assertNotIn(("perm-co", "perm-role"), pairs)  # PERM only

    def test_sitemap_lists_qualifying_pairs_only(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("/h1b-salary/google-llc/software-engineer/", body)
        self.assertNotIn("/h1b-salary/employer-0/software-engineer/", body)
        self.assertNotIn("/h1b-salary/google-llc/data-clerk/", body)

    def test_sponsors_role_page_links_qualifying_pair(self):
        # The role qualifies as an h1b-sponsors page; Google's wage cell links to
        # the pair page, while sub-threshold employers' do not.
        body = self.client.get("/h1b-sponsors/software-engineer/").content.decode()
        self.assertEqual(
            self.client.get("/h1b-sponsors/software-engineer/").status_code, 200
        )
        self.assertIn("/h1b-salary/google-llc/software-engineer/", body)
        self.assertNotIn("/h1b-salary/employer-0/software-engineer/", body)
