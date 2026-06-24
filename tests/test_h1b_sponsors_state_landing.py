"""Tests for the per-state "Top H-1B sponsors in {state}" landing pages.

Locks: a state with a substantive H-1B leaderboard renders 200 with both the
volume-ranked and pay-ranked employer tables + FAQPage schema + self-canonical;
a thin state 404s (no thin page); a PERM-heavy state 404s (H-1B only); the
sitemap lists qualifying states only (never a 404); the highest-paying ranking
honors the minimum-filings floor (a one-filing outlier can't top it); the
by-state page links in only when the page qualifies. The qualification gate is
shared with the sitemap (lib/business/salary/h1b_sponsors.py).
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from lib.business.salary.h1b_sponsors import (
    highest_paying_in_state,
    qualifying_state_codes,
)
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


def _add_records(jt, employer, program, n, *, start_case, state, wage):
    for i in range(n):
        SalaryRecord.objects.create(
            case_number=f"{start_case}-{i}",
            visa_program=program,
            employer=employer,
            employer_name=employer.name,
            job_title_entity=jt,
            job_title=jt.title,
            wage_annual=Decimal(str(wage + i)),
            worksite_state=state,
            is_worksite=False,
            fiscal_year=2025,
        )


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class TestH1BSponsorsStateLanding(TestCase):
    def setUp(self):
        cache.clear()
        self.role = _make_role("software-engineer", "Software Engineer")

        # Qualifying state CA: 8 employers with distinct (filings, wage), so both
        # the volume ranking and the pay ranking are deterministic and differ.
        # (filings, wage): D pays most, H second; A files most.
        self.ca_specs = {
            "A": (12, 120000), "B": (11, 130000), "C": (10, 110000),
            "D": (9, 250000), "E": (8, 140000), "F": (7, 150000),
            "G": (6, 160000), "H": (5, 200000),
        }
        for idx, (label, (n, wage)) in enumerate(self.ca_specs.items()):
            emp = _make_employer(idx)
            setattr(self, f"emp_{label}", emp)
            _add_records(
                self.role, emp, VisaProgram.H1B, n,
                start_case=f"CA-{label}", state="CA", wage=wage,
            )
        # Outlier: a single very-high-wage filing — below the pay floor (5), so it
        # must NOT top the highest-paying ranking.
        self.outlier = _make_employer(99)
        _add_records(
            self.role, self.outlier, VisaProgram.H1B, 1,
            start_case="CA-OUT", state="CA", wage=999000,
        )

        # Thin state TX: 2 employers x 3 H-1B filings — below both thresholds.
        for idx in range(2):
            emp = _make_employer(200 + idx)
            _add_records(
                self.role, emp, VisaProgram.H1B, 3,
                start_case=f"TX-{idx}", state="TX", wage=100000,
            )

        # PERM-heavy state NY: many PERM, zero H-1B — must 404 (H-1B only).
        for idx in range(10):
            emp = _make_employer(300 + idx)
            _add_records(
                self.role, emp, VisaProgram.PERM, 10,
                start_case=f"NY-{idx}", state="NY", wage=100000,
            )

    def test_qualifying_state_renders(self):
        resp = self.client.get("/h1b-sponsors/in/ca/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Top H-1B Sponsors in California", body)  # H1
        self.assertIn("Highest-paying H-1B employers in California", body)  # 2nd table
        self.assertIn("Employer 0 Inc", body)  # a ranked employer (emp A)
        self.assertIn("/employer/employer-0/", body)  # employer link

    def test_faqpage_schema_and_canonical(self):
        body = self.client.get("/h1b-sponsors/in/ca/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("Which companies sponsor H-1B visas in California", body)
        self.assertIn("highest-paying h-1b employers in california", body.lower())
        self.assertIn(
            'rel="canonical" href="http://testserver/h1b-sponsors/in/ca/"', body
        )

    def test_highest_paying_honors_min_filings_floor(self):
        rows = highest_paying_in_state("CA")
        slugs = [r["employer__canonical_cluster__slug"] for r in rows]
        # emp D ($250k, 9 filings) tops the pay ranking, not the $999k outlier.
        self.assertEqual(rows[0]["employer__canonical_cluster__slug"], "employer-3")
        self.assertNotIn("employer-99", slugs)  # 1 filing < floor → excluded
        # Pay ranking differs from volume ranking (emp A files most, isn't #1 pay).
        self.assertNotEqual(slugs[0], "employer-0")

    def test_roles_block_cross_links_to_qualifying_role_page(self):
        # The CA role has 68+ H-1B filings across 8+ sponsors, so its own role
        # leaderboard qualifies → the roles block links there, not the profile.
        body = self.client.get("/h1b-sponsors/in/ca/").content.decode()
        self.assertIn("/h1b-sponsors/software-engineer/", body)

    def test_thin_state_404(self):
        self.assertEqual(self.client.get("/h1b-sponsors/in/tx/").status_code, 404)

    def test_perm_heavy_state_404_h1b_only(self):
        self.assertEqual(self.client.get("/h1b-sponsors/in/ny/").status_code, 404)

    def test_unknown_state_404(self):
        self.assertEqual(self.client.get("/h1b-sponsors/in/zz/").status_code, 404)

    def test_qualifying_state_codes_gate(self):
        codes = set(qualifying_state_codes())
        self.assertIn("CA", codes)
        self.assertNotIn("TX", codes)  # thin
        self.assertNotIn("NY", codes)  # PERM only

    def test_sitemap_lists_qualifying_states_only(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("/h1b-sponsors/in/ca/", body)
        self.assertNotIn("/h1b-sponsors/in/tx/", body)
        self.assertNotIn("/h1b-sponsors/in/ny/", body)

    def test_by_state_links_in_when_qualifying(self):
        body = self.client.get("/salaries/by-state/ca/").content.decode()
        self.assertIn("/h1b-sponsors/in/ca/", body)
        # Thin state's by-state page must NOT link to a 404 sponsor page.
        tx_body = self.client.get("/salaries/by-state/tx/").content.decode()
        self.assertNotIn("/h1b-sponsors/in/tx/", tx_body)
