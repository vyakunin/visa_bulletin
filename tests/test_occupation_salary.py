"""Tests for the {occupation} H-1B/PERM salary landing pages.

Locks: a qualifying occupation (>= MIN_OCCUPATION_FILINGS) renders 200 with the
display name, median, percentile table, FAQPage schema + self-canonical; a thin
occupation 404s (no thin page); an alias slug 301s to the canonical page; an
unknown slug 404s; records are scoped by SOC code (a non-matching SOC code does
not count); the sitemap lists qualifying occupations + the hub only (never a
404). The qualification gate is shared with the sitemap
(lib/business/salary/occupation_stats.py).
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from lib.business.salary.occupation_stats import (
    get_occupation_stats,
    occupation_filing_count,
)
from lib.business.salary.soc_occupations import get_occupation
from models.enums.visa_program import VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord


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


def _add_records(employer, *, soc_code, n, start_case, program=VisaProgram.H1B, wage=130000):
    for i in range(n):
        SalaryRecord.objects.create(
            case_number=f"{start_case}-{i}",
            visa_program=program,
            employer=employer,
            employer_name=employer.name,
            job_title=f"Engineer {i}",
            soc_code=soc_code,
            wage_annual=Decimal(str(wage + i * 100)),
            worksite_state="CA" if i % 2 else "TX",
            is_worksite=False,
            fiscal_year=2025,
        )


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class TestOccupationSalary(TestCase):
    def setUp(self):
        cache.clear()
        # Qualifying: software-engineer (SOC 15-1252) — 10 employers x 12 = 120
        # filings (>= MIN_OCCUPATION_FILINGS of 100).
        for idx in range(10):
            emp = _make_employer(idx)
            _add_records(
                emp, soc_code="15-1252.00", n=12, start_case=f"SE-{idx}",
                wage=120000 + idx * 3000,
            )
        # Thin: civil-engineer (SOC 17-2051) — only 5 filings, below the gate.
        thin_emp = _make_employer(900)
        _add_records(thin_emp, soc_code="17-2051.00", n=5, start_case="CE")
        # Noise: a non-registered SOC code that no occupation matches.
        noise_emp = _make_employer(901)
        _add_records(noise_emp, soc_code="99-9999.00", n=50, start_case="NOISE")

    def test_qualifying_occupation_renders(self):
        resp = self.client.get("/h1b-salary/software-engineer/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Software Engineer H-1B", body)  # H1
        self.assertIn("Employer 0 Inc", body)  # a ranked sponsoring employer
        self.assertIn("/employer/employer-0/", body)  # employer cross-link
        self.assertIn("percentile", body.lower())

    def test_faqpage_schema_and_canonical(self):
        body = self.client.get("/h1b-salary/software-engineer/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn('"@type": "Occupation"', body)
        self.assertIn(
            'rel="canonical" href="http://testserver/h1b-salary/software-engineer/"',
            body,
        )

    def test_thin_occupation_404(self):
        # 5 filings < MIN_OCCUPATION_FILINGS → no thin page.
        self.assertEqual(
            self.client.get("/h1b-salary/civil-engineer/").status_code, 404
        )

    def test_alias_redirects_to_canonical(self):
        resp = self.client.get("/h1b-salary/swe/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp.url, "/h1b-salary/software-engineer/")

    def test_unknown_slug_404(self):
        self.assertEqual(
            self.client.get("/h1b-salary/not-an-occupation/").status_code, 404
        )

    def test_index_hub_lists_qualifying(self):
        body = self.client.get("/h1b-salary/").content.decode()
        self.assertEqual(self.client.get("/h1b-salary/").status_code, 200)
        self.assertIn("/h1b-salary/software-engineer/", body)
        # Thin occupation must not appear on the hub.
        self.assertNotIn("/h1b-salary/civil-engineer/", body)

    def test_sitemap_lists_qualifying_only(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("/h1b-salary/software-engineer/", body)
        self.assertIn("/h1b-salary/</loc>", body.replace(" ", ""))  # the hub
        self.assertNotIn("/h1b-salary/civil-engineer/", body)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class TestOccupationStatsResultCache(TestCase):
    """Every occupation aggregate is a full scan of the salary_record heap, and
    one page needs nine of them. `/h1b-salary/` is served by
    `cache_page_skip_bots`, so its crawler traffic — nearly all of its hits —
    never reads the rendered-page cache and would pay all nine every time.
    """

    def setUp(self):
        cache.clear()
        for idx in range(10):
            _add_records(
                _make_employer(idx), soc_code="15-1252.00", n=12,
                start_case=f"SE-{idx}", wage=120000 + idx * 3000,
            )
        self.occ = get_occupation("software-engineer")

    def test_repeat_stats_call_does_not_rescan_the_corpus(self):
        first = get_occupation_stats(self.occ)
        self.assertEqual(first.total_filings, 120)
        with self.assertNumQueries(0):
            again = get_occupation_stats(self.occ)
        self.assertEqual(again.total_filings, 120)
        self.assertEqual(again.percentiles, first.percentiles)
        self.assertEqual(again.top_employers, first.top_employers)

    def test_repeat_filing_count_does_not_rescan_the_corpus(self):
        self.assertEqual(occupation_filing_count(self.occ), 120)
        with self.assertNumQueries(0):
            self.assertEqual(occupation_filing_count(self.occ), 120)

    def test_second_page_request_issues_no_occupation_queries(self):
        # The end state the cache exists for: a warm crawler hit renders from
        # the cached aggregates even though the page cache skipped the bot.
        bot = {"HTTP_USER_AGENT": "Mozilla/5.0 (compatible; Googlebot/2.1)"}
        self.assertEqual(
            self.client.get("/h1b-salary/software-engineer/", **bot).status_code, 200
        )
        with self.assertNumQueries(0):
            resp = self.client.get("/h1b-salary/software-engineer/", **bot)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Software Engineer H-1B", resp.content.decode())
