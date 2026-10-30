"""Tests for the {occupation} H-1B/PERM salary landing pages.

Locks: a qualifying occupation (>= MIN_OCCUPATION_FILINGS) renders 200 with the
display name, median, percentile table, FAQPage schema + self-canonical; a thin
occupation 404s (no thin page); an alias slug 301s to the canonical page; an
unknown slug 404s; records are scoped by SOC code (a non-matching SOC code does
not count); the sitemap lists qualifying occupations + the hub only (never a
404). The qualification gate is shared with the sitemap
(lib/business/salary/occupation_stats.py).
"""

import re
from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from lib.business.i129.pay_comparison import warm_soc_pay_comparison
from lib.business.salary.occupation_stats import (
    get_occupation_stats,
    occupation_filing_count,
    occupation_page_stored,
    store_qualifying_occupation_slugs,
    warm_occupation_page,
)
from lib.business.salary.soc_occupations import get_occupation
from models.enums.visa_program import VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord

_CORPUS_TABLES = ('"salary_record"', '"i129_petition"', '"worksite_record"')


def _corpus_queries(captured) -> list[str]:
    """Captured queries that scan the filing corpus, the cost the stores exist to avoid."""
    return [
        q["sql"]
        for q in captured.captured_queries
        if any(table in q["sql"] for table in _CORPUS_TABLES)
    ]


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
    CACHES={**settings.CACHES, **{"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}}
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

    def test_counts_are_not_called_certified(self):
        # Counts include denied and withdrawn filings; only the outcome list may say certified.
        body = self.client.get("/h1b-salary/software-engineer/").content.decode()
        body = re.sub(r"\(certified,\s+denied or\s+withdrawn\)", "", body)
        self.assertNotIn("certified", body.lower())

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
    CACHES={**settings.CACHES, **{"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}}
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
        with CaptureQueriesContext(connection) as captured:
            again = get_occupation_stats(self.occ)
        self.assertEqual(_corpus_queries(captured), [])
        self.assertEqual(again.total_filings, 120)
        self.assertEqual(again.percentiles, first.percentiles)
        self.assertEqual(again.top_employers, first.top_employers)

    def test_repeat_filing_count_does_not_rescan_the_corpus(self):
        self.assertEqual(occupation_filing_count(self.occ), 120)
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(occupation_filing_count(self.occ), 120)
        self.assertEqual(_corpus_queries(captured), [])

    def test_second_page_request_issues_no_occupation_queries(self):
        # A crawler hit on an occupation the warmer has not stored renders from the
        # Redis entries the first hit filled, even though the page cache skipped the bot.
        bot = {"HTTP_USER_AGENT": "Mozilla/5.0 (compatible; Googlebot/2.1)"}
        self.assertEqual(
            self.client.get("/h1b-salary/software-engineer/", **bot).status_code, 200
        )
        with CaptureQueriesContext(connection) as captured:
            resp = self.client.get("/h1b-salary/software-engineer/", **bot)
        self.assertEqual(_corpus_queries(captured), [])
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Software Engineer H-1B", resp.content.decode())


@override_settings(
    CACHES={**settings.CACHES, **{"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}}
)
class TestStoredOccupationPage(TestCase):
    """The warmer's stored aggregates serve the page with Redis empty.

    On 2026-10-29 vb_redis evicted all 41 occupations' entries and cold renders of
    65-209s starved the workers into a 504 burst. The default cache here is a dummy,
    so anything not served from the `aggregates` store would hit salary_record.
    """

    def setUp(self):
        for idx in range(10):
            _add_records(
                _make_employer(idx), soc_code="15-1252.00", n=12,
                start_case=f"SE-{idx}", wage=120000 + idx * 3000,
            )
        _add_records(_make_employer(900), soc_code="17-2051.00", n=5, start_case="CE")
        self.occ = get_occupation("software-engineer")

    def _warm(self, occ):
        page = warm_occupation_page(occ)
        warm_soc_pay_comparison(occ)
        return page

    def test_stored_page_renders_with_no_corpus_query(self):
        self._warm(self.occ)
        bot = {"HTTP_USER_AGENT": "Mozilla/5.0 (compatible; Googlebot/2.1)"}
        with CaptureQueriesContext(connection) as captured:
            resp = self.client.get("/h1b-salary/software-engineer/", **bot)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Employer 0 Inc", resp.content.decode())
        self.assertEqual(_corpus_queries(captured), [])

    def test_thin_occupation_is_stored_without_stats_and_still_404s(self):
        page = self._warm(get_occupation("civil-engineer"))
        self.assertEqual(page.filing_count, 5)
        self.assertIsNone(page.stats)
        with CaptureQueriesContext(connection) as captured:
            status = self.client.get("/h1b-salary/civil-engineer/").status_code
        self.assertEqual(status, 404)
        self.assertEqual(_corpus_queries(captured), [])

    def test_stored_qualifying_slugs_feed_the_sitemap(self):
        store_qualifying_occupation_slugs(["software-engineer"])
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("/h1b-salary/software-engineer/", body)
        self.assertNotIn("/h1b-salary/civil-engineer/", body)


@override_settings(
    CACHES={**settings.CACHES, **{"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}}
)
class TestOccupationStoredProbe(TestCase):
    """`occupation_page_stored` reports a missing page WITHOUT computing it, and
    only the warmer's store counts: a Redis entry is gone within hours."""

    def setUp(self):
        cache.clear()
        for idx in range(10):
            _add_records(
                _make_employer(idx), soc_code="15-1252.00", n=12,
                start_case=f"SE-{idx}", wage=120000 + idx * 3000,
            )
        self.occ = get_occupation("software-engineer")

    def test_probe_reports_missing_without_storing(self):
        self.assertFalse(occupation_page_stored(self.occ.slug))
        self.assertFalse(occupation_page_stored(self.occ.slug))

    def test_a_redis_fill_is_not_a_stored_page(self):
        get_occupation_stats(self.occ)
        self.assertFalse(occupation_page_stored(self.occ.slug))

    def test_probe_reports_stored_after_the_warm(self):
        warm_occupation_page(self.occ)
        self.assertTrue(occupation_page_stored(self.occ.slug))
