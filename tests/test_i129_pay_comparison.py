"""Tests for the I-129 actual-pay vs LCA-posted vs prevailing comparison.

Locks: the join (i129.dol_eta_case_number = worksite_record.case_number) scoped
by an occupation's SOC-6 set produces correct medians/means and above/at/below
distribution; small-n cells are suppressed (None); non-matching SOC, denied
LCAs, and null-pay petitions are excluded from the aggregate.
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from lib.business.i129.pay_comparison import (
    MIN_COMPARISON_N,
    get_employer_pay_comparison,
    get_soc_pay_comparison,
)

# The SQL-correctness tests below all query the SAME occupation slug against
# different fixtures, so the result cache in get_soc_pay_comparison would serve
# the first test's answer to the rest. They are about the query, not the cache.
_NO_CACHE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
_LOCMEM_CACHE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
from lib.business.salary.soc_occupations import Occupation
from models.enums.case_status import CaseStatus
from models.enums.visa_program import VisaProgram
from models.i129 import I129Petition
from models.salary import EmployerCluster, WorksiteRecord

_OCC = Occupation(slug="test-dev", display="Test Developer", soc6=("15-1252",))


def _pair(
    case: str,
    *,
    soc="15-1252.00",
    actual,
    lca,
    prevailing=90000,
    case_status=CaseStatus.CERTIFIED,
    pay_null=False,
    employer_cluster=None,
):
    """One matched worksite (LCA) + i129 (petition) row sharing a case number."""
    WorksiteRecord.objects.create(
        case_number=case,
        visa_program=VisaProgram.H1B,
        case_status=case_status,
        soc_code=soc,
        job_title="Software Developer",
        wage_annual=Decimal(str(lca)),
        prevailing_wage=Decimal(str(prevailing)),
        worksite_state="CA",
        fiscal_year=2024,
    )
    I129Petition.objects.create(
        dol_eta_case_number=case,
        fiscal_year=2024,
        job_title="Software Developer",
        pay_annual=None if pay_null else Decimal(str(actual)),
        employer_cluster=employer_cluster,
    )


@_NO_CACHE
class TestI129PayComparison(TestCase):
    def test_matched_cell_computes_three_way(self):
        # 60 matched pairs, all paid 10% above the posted LCA wage.
        for i in range(60):
            _pair(f"CASE-{i}", actual=110000, lca=100000, prevailing=90000)

        cmp = get_soc_pay_comparison(_OCC)
        assert cmp is not None
        assert cmp.n == 60
        assert cmp.median_actual == 110000
        assert cmp.median_lca == 100000
        assert cmp.median_prevailing == 90000
        assert cmp.median_actual_vs_lca_pct == 10.0
        assert cmp.median_actual_vs_prevailing_pct == round((110000 / 90000 - 1) * 100, 1)
        # Every worker is >1% above posted.
        assert cmp.pct_above_lca == 100.0
        assert cmp.pct_at_lca == 0.0
        assert cmp.pct_below_lca == 0.0

    def test_above_at_below_distribution(self):
        # 25 above, 25 at (exactly equal), 10 below → 60 total.
        for i in range(25):
            _pair(f"A-{i}", actual=120000, lca=100000)
        for i in range(25):
            _pair(f"E-{i}", actual=100000, lca=100000)
        for i in range(10):
            _pair(f"B-{i}", actual=80000, lca=100000)

        cmp = get_soc_pay_comparison(_OCC)
        assert cmp is not None and cmp.n == 60
        assert cmp.pct_above_lca == round(100 * 25 / 60, 1)
        assert cmp.pct_at_lca == round(100 * 25 / 60, 1)
        assert cmp.pct_below_lca == round(100 * 10 / 60, 1)

    def test_small_n_suppressed(self):
        for i in range(MIN_COMPARISON_N - 1):
            _pair(f"THIN-{i}", actual=110000, lca=100000)
        assert get_soc_pay_comparison(_OCC) is None

    def test_excludes_nonmatching_soc_denied_and_null_pay(self):
        # 55 valid matched pairs for the target SOC.
        for i in range(55):
            _pair(f"OK-{i}", actual=110000, lca=100000)
        # Noise that must NOT be counted:
        for i in range(20):  # different SOC
            _pair(f"OTHER-{i}", soc="15-2031.00", actual=200000, lca=100000)
        for i in range(20):  # denied LCA
            _pair(f"DENIED-{i}", actual=200000, lca=100000, case_status=CaseStatus.DENIED)
        for i in range(20):  # null actual pay
            _pair(f"NULLPAY-{i}", actual=0, lca=100000, pay_null=True)

        cmp = get_soc_pay_comparison(_OCC)
        assert cmp is not None
        assert cmp.n == 55  # only the clean matched-target-SOC pairs
        assert cmp.median_actual == 110000


@_NO_CACHE
class TestI129EmployerPayComparison(TestCase):
    def test_scopes_to_the_employer_cluster(self):
        cluster_a = EmployerCluster.objects.create(canonical_name="Acme", slug="acme")
        cluster_b = EmployerCluster.objects.create(canonical_name="Other", slug="other")
        # 55 matched pairs for cluster A, all paid 20% above posted.
        for i in range(55):
            _pair(f"A-{i}", actual=120000, lca=100000, employer_cluster=cluster_a)
        # Noise: another cluster + unlinked petitions must NOT be counted for A.
        for i in range(30):
            _pair(f"B-{i}", actual=200000, lca=100000, employer_cluster=cluster_b)
        for i in range(30):
            _pair(f"U-{i}", actual=200000, lca=100000, employer_cluster=None)

        cmp = get_employer_pay_comparison(cluster_a)
        assert cmp is not None
        assert cmp.n == 55
        assert cmp.median_actual == 120000
        assert cmp.median_actual_vs_lca_pct == 20.0

    def test_thin_employer_suppressed(self):
        cluster = EmployerCluster.objects.create(canonical_name="Tiny", slug="tiny")
        for i in range(MIN_COMPARISON_N - 1):
            _pair(f"T-{i}", actual=110000, lca=100000, employer_cluster=cluster)
        assert get_employer_pay_comparison(cluster) is None

    def test_none_cluster_returns_none(self):
        assert get_employer_pay_comparison(None) is None


@_LOCMEM_CACHE
class TestSocComparisonResultCache(TestCase):
    """The matched-triple aggregate costs ~1.7-2.0s whatever the occupation, and
    `/h1b-salary/` serves crawlers straight past the rendered-page cache — so a
    repeat request must not re-run it.
    """

    def setUp(self):
        cache.clear()

    def test_repeat_call_does_not_rerun_the_aggregate(self):
        for i in range(60):
            _pair(f"CASE-{i}", actual=110000, lca=100000)

        first = get_soc_pay_comparison(_OCC)
        assert first is not None and first.n == 60
        with self.assertNumQueries(0):
            again = get_soc_pay_comparison(_OCC)
        assert again == first

    def test_suppressed_result_is_cached_not_recomputed(self):
        # A suppressed cell returns None, which is also what a cache miss looks
        # like. Most occupations fall under MIN_COMPARISON_N, so storing a bare
        # None would leave exactly them re-running the page's most expensive
        # query on every request.
        for i in range(MIN_COMPARISON_N - 1):
            _pair(f"THIN-{i}", actual=110000, lca=100000)

        assert get_soc_pay_comparison(_OCC) is None
        with self.assertNumQueries(0):
            assert get_soc_pay_comparison(_OCC) is None


@_NO_CACHE
class SocScopeIsIndexableTests(TestCase):
    """The SOC scope must stay a shape the planner can turn into an index scan.

    ``worksite_record`` carries a varchar_pattern_ops index on ``soc_code``, and
    PostgreSQL uses it for ``soc_code LIKE 'prefix%'`` — but NOT for
    ``soc_code LIKE ANY(array)``, where the pattern is an opaque array element. The
    two forms return identical rows, so every correctness test above passes either
    way; the only difference is the plan. Measured on prod 2026-08-18 for
    operations-manager: 1828ms with ANY, 171ms without.

    That makes this a silent 10x regression nothing else would catch, hence a test
    on the emitted SQL rather than on the result.
    """

    def test_soc_scope_emits_one_plain_like_per_prefix(self):
        multi = Occupation(
            slug="test-multi",
            display="Test Multi",
            soc6=("15-1252", "15-1132", "15-1133"),
        )
        with CaptureQueriesContext(connection) as captured:
            get_soc_pay_comparison(multi)

        comparisons = [q["sql"] for q in captured.captured_queries if "matched" in q["sql"]]
        assert len(comparisons) == 1, comparisons
        sql = comparisons[0]

        assert "LIKE ANY" not in sql.upper(), (
            "the SOC scope regressed to LIKE ANY(array), which cannot use "
            f"worksite_record's soc_code pattern index: {sql}"
        )
        assert sql.upper().count("SOC_CODE LIKE") == len(multi.soc6), (
            "expected one plain LIKE per SOC-6 prefix so each is independently "
            f"index-searchable: {sql}"
        )

    def test_marker_is_always_replaced(self):
        # __SCOPE__ is deliberately invalid SQL so an unscoped template cannot run:
        # a query reaching the database with it still in place would aggregate over
        # every petition rather than one occupation's.
        with CaptureQueriesContext(connection) as captured:
            get_soc_pay_comparison(_OCC)
        for query in captured.captured_queries:
            assert "__SCOPE__" not in query["sql"], query["sql"]
