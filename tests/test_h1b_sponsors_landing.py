"""Tests for the per-role "Top H-1B sponsors" landing pages.

Locks: a role with a substantive H-1B leaderboard renders 200 with the ranked
employers + FAQPage schema + self-canonical; a thin role 404s (no thin page);
the sitemap lists qualifying roles only (never a 404); only H-1B filings count
toward qualification (a PERM-heavy role 404s). The qualification gate is shared
with the sitemap (lib/business/salary/h1b_sponsors.py).
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from models.enums.visa_program import VisaProgram
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord


def _make_role(slug: str, title: str) -> tuple[JobTitleCluster, JobTitle]:
    cluster = JobTitleCluster.objects.create(
        slug=slug, canonical_title=title, total_filings=0
    )
    jt = JobTitle.objects.create(
        title=title,
        title_normalized=title.lower(),
        canonical_cluster=cluster,
    )
    return cluster, jt


def _make_employer(idx: int) -> Employer:
    ec = EmployerCluster.objects.create(
        slug=f"employer-{idx}", canonical_name=f"Employer {idx} Inc"
    )
    return Employer.objects.create(
        name=f"Employer {idx} Inc",
        name_normalized=f"employer {idx}",
        city="San Francisco",
        state="CA",
        canonical_cluster=ec,
    )


def _add_records(jt, employer, program, n, *, start_case, state="CA", wage=150000):
    for i in range(n):
        SalaryRecord.objects.create(
            case_number=f"{start_case}-{i}",
            visa_program=program,
            employer=employer,
            employer_name=employer.name,
            job_title_entity=jt,
            job_title=jt.title,
            wage_annual=Decimal(str(wage + i * 10)),
            worksite_state=state,
            is_worksite=False,
            fiscal_year=2025,
        )


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class TestH1BSponsorsLanding(TestCase):
    def setUp(self):
        cache.clear()
        # Qualifying role: 8 employers x 7 H-1B filings = 56 filings (>= 50, >= 8).
        self.cluster, jt = _make_role("software-engineer-h1b", "Software Engineer")
        for idx in range(8):
            emp = _make_employer(idx)
            _add_records(
                jt, emp, VisaProgram.H1B, 7,
                start_case=f"H1B-{idx}", state="CA" if idx % 2 else "TX",
                wage=120000 + idx * 5000,
            )

        # Thin role: only 2 employers x 3 H-1B filings — below both thresholds.
        self.thin_cluster, thin_jt = _make_role("data-clerk-h1b", "Data Clerk")
        for idx in range(2):
            emp = _make_employer(100 + idx)
            _add_records(thin_jt, emp, VisaProgram.H1B, 3, start_case=f"THIN-{idx}")

        # PERM-heavy role: many PERM filings but few H-1B — must 404 (H-1B only).
        self.perm_cluster, perm_jt = _make_role("perm-role-h1b", "Perm Role")
        for idx in range(10):
            emp = _make_employer(200 + idx)
            _add_records(perm_jt, emp, VisaProgram.PERM, 10, start_case=f"PERM-{idx}")

    def test_qualifying_role_renders(self):
        resp = self.client.get("/h1b-sponsors/software-engineer-h1b/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Top H-1B Sponsors for Software Engineer", body)  # H1
        self.assertIn("Employer 0 Inc", body)  # a ranked employer
        self.assertIn("/employer/employer-0/", body)  # employer link

    def test_faqpage_schema_and_canonical(self):
        body = self.client.get("/h1b-sponsors/software-engineer-h1b/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("Which companies sponsor H-1B", body)
        self.assertIn(
            'rel="canonical" href="http://testserver/h1b-sponsors/software-engineer-h1b/"',
            body,
        )

    def test_thin_role_404(self):
        self.assertEqual(
            self.client.get("/h1b-sponsors/data-clerk-h1b/").status_code, 404
        )

    def test_perm_heavy_role_404_h1b_only(self):
        # 100 PERM filings but zero H-1B → not a "top H-1B sponsors" page.
        self.assertEqual(
            self.client.get("/h1b-sponsors/perm-role-h1b/").status_code, 404
        )

    def test_unknown_slug_404(self):
        self.assertEqual(
            self.client.get("/h1b-sponsors/no-such-role/").status_code, 404
        )

    def test_sitemap_lists_qualifying_only(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("/h1b-sponsors/software-engineer-h1b/", body)
        self.assertNotIn("/h1b-sponsors/data-clerk-h1b/", body)
        self.assertNotIn("/h1b-sponsors/perm-role-h1b/", body)
