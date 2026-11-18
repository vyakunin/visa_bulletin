"""Correctness of the /salaries/ search resolvers that replace the single materialized scan.

walked_page_ids() resolves a page from a bounded prefix of the wage ordering and must
return exactly what fenced_page_ids() returns, or None so the caller falls back to it.
parallel_aggregate() must return exactly what fenced_aggregate() returns.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from lib.utils.filter_utils import (
    PAGE_WALK_MAX_ROWS,
    apply_text_search_filter,
    fenced_aggregate,
    fenced_page_ids,
    parallel_aggregate,
    walked_page_ids,
)
from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord

ORDER = ("-wage_annual", "-fiscal_year")


def _seed(employer, rows):
    for idx, (title, wage, fy, state) in enumerate(rows):
        SalaryRecord.objects.create(
            case_number=f"RES-{title[:3]}-{idx}",
            employer=employer,
            employer_name=employer.name,
            job_title=title,
            wage_annual=wage,
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=fy,
            worksite_state=state,
            is_worksite=False,
        )


def _employer(name):
    cluster = EmployerCluster.objects.create(
        canonical_name=name, slug=name.lower().replace(" ", "-")
    )
    return Employer.objects.create(
        name=name, name_normalized=name.lower(), canonical_cluster=cluster
    )


def _searched(query, **filters):
    qs = apply_text_search_filter(SalaryRecord.objects.all(), query, ["job_title", "soc_title"])
    if filters:
        qs = qs.filter(**filters)
    qs = qs.exclude(is_worksite=True).exclude(employer_name="Unknown")
    return qs.filter(wage_annual__isnull=False, wage_annual__gt=0)


class WalkedPageIdsTest(TestCase):
    def setUp(self):
        employer = _employer("Walk Co")
        # 40 ENGINEER rows at 100k-139k, alternating states and fiscal years,
        # a wage tie broken by fiscal year, one CASHIER, and 30 ACCOUNTANT rows
        # paid above every engineer (they fill the top of the wage ordering).
        rows = [
            (f"ENGINEER {i}", 100000 + i * 1000, 2024 if i % 2 else 2020, "CA" if i % 3 else "NY")
            for i in range(40)
        ]
        rows += [
            ("SENIOR ENGINEER", 250000, 2024, "CA"),
            ("SENIOR ENGINEER", 250000, 2022, "CA"),
            ("CASHIER", 35000, 2023, "CA"),
        ]
        rows += [(f"ACCOUNTANT {i}", 300000 + i * 1000, 2024, "CA") for i in range(30)]
        _seed(employer, rows)
        self.table_rows = len(rows)

    def test_page_inside_the_prefix_equals_the_fence(self):
        qs = _searched("ENGINEER")
        for offset in (0, 10, 30):
            page = walked_page_ids(
                qs, ORDER, offset, 10, match_count=2, table_rows=self.table_rows
            )
            self.assertEqual(page, fenced_page_ids(qs, ORDER, offset, 10), offset)

    def test_wage_tie_breaks_on_fiscal_year_like_the_fence(self):
        qs = _searched("SENIOR ENGINEER")
        page = walked_page_ids(qs, ORDER, 0, 2, match_count=1, table_rows=self.table_rows)
        self.assertEqual(page, fenced_page_ids(qs, ORDER, 0, 2))

    def test_extra_filters_apply_inside_the_prefix(self):
        qs = _searched("ENGINEER", worksite_state="NY")
        page = walked_page_ids(qs, ORDER, 0, 5, match_count=1, table_rows=self.table_rows)
        self.assertEqual(page, fenced_page_ids(qs, ORDER, 0, 5))

    def test_prefix_without_enough_matches_returns_none(self):
        # The match rate sizes a prefix of a few rows; the top of the ordering is all
        # accountants, so the prefix holds no engineer at all.
        qs = _searched("ENGINEER")
        page = walked_page_ids(qs, ORDER, 0, 1, match_count=40, table_rows=self.table_rows)
        self.assertIsNone(page)

    def test_short_last_page_returns_none(self):
        qs = _searched("ENGINEER")
        page = walked_page_ids(qs, ORDER, 40, 10, match_count=1, table_rows=self.table_rows)
        self.assertIsNone(page)

    def test_budget_over_the_cap_returns_none_without_a_query(self):
        with CaptureQueriesContext(connection) as ctx:
            page = walked_page_ids(
                _searched("CASHIER"), ORDER, 0, 50, match_count=1,
                table_rows=PAGE_WALK_MAX_ROWS,
            )
        self.assertIsNone(page)
        self.assertEqual(len(ctx.captured_queries), 0)

    def test_unknown_table_size_returns_none(self):
        for table_rows in (0, -1):
            self.assertIsNone(
                walked_page_ids(_searched("ENGINEER"), ORDER, 0, 5, match_count=40,
                                table_rows=table_rows)
            )

    def test_no_matches_is_an_empty_page(self):
        self.assertEqual(
            walked_page_ids(_searched("ENGINEER"), ORDER, 0, 5, match_count=0,
                            table_rows=self.table_rows),
            [],
        )

    def test_provably_empty_queryset_is_an_empty_page(self):
        page = walked_page_ids(SalaryRecord.objects.none(), ORDER, 0, 5, match_count=3,
                               table_rows=self.table_rows)
        self.assertEqual(page, [])

    def test_walks_a_bounded_prefix_not_a_fence(self):
        with CaptureQueriesContext(connection) as ctx:
            # A non-zero page offset, so the page's own OFFSET is not read as a fence.
            walked_page_ids(_searched("ENGINEER"), ORDER, 3, 5, match_count=2,
                            table_rows=self.table_rows)
        sql = ctx.captured_queries[-1]["sql"]
        self.assertNotIn("OFFSET 0", sql)
        self.assertNotIn("MATERIALIZED", sql)
        self.assertIn('ORDER BY "wage_annual" DESC, "fiscal_year" DESC LIMIT', sql)


class ParallelAggregateTest(TestCase):
    def setUp(self):
        employer = _employer("Agg Co")
        _seed(employer, [
            ("SOFTWARE ENGINEER", 150000, 2024, "CA"),
            ("DATA ENGINEER", 130000, 2023, "NY"),
            ("ENGINEER", 0, 2023, "NY"),
            ("CASHIER", 35000, 2023, "CA"),
        ])

    def test_equals_the_fenced_aggregate(self):
        for query in ("ENGINEER", "CASHIER", "NONEXISTENTZZZ"):
            qs = _searched(query)
            self.assertEqual(parallel_aggregate(qs, "wage_annual", trigram_search=True),
                             fenced_aggregate(qs, "wage_annual"), query)

    def test_provably_empty_queryset_is_zero(self):
        agg = parallel_aggregate(
            SalaryRecord.objects.none(), "wage_annual", trigram_search=False
        )
        self.assertEqual((agg.count, agg.avg, agg.min, agg.max), (0, None, None, None))

    def test_a_trigram_search_is_kept_off_the_seq_scan(self):
        for force, expected in ((True, True), (False, False)):
            with CaptureQueriesContext(connection) as ctx:
                parallel_aggregate(_searched("ENGINEER"), "wage_annual", trigram_search=force)
            statements = [q["sql"] for q in ctx.captured_queries]
            self.assertEqual("SET LOCAL enable_seqscan = off" in statements, expected)

    def test_runs_unfenced_with_jit_off(self):
        with CaptureQueriesContext(connection) as ctx:
            parallel_aggregate(_searched("ENGINEER"), "wage_annual", trigram_search=True)
        statements = [q["sql"] for q in ctx.captured_queries]
        self.assertIn("SET LOCAL jit = off", statements)
        (aggregate,) = [sql for sql in statements if "count(*)" in sql]
        self.assertNotIn("OFFSET 0", aggregate)
        self.assertGreater(statements.index(aggregate), statements.index("SET LOCAL jit = off"))


class SalarySearchViewResolverTest(TestCase):
    """A cold free-text search reads its page off the wage ordering and its stats from one
    parallel aggregate; an employer filter keeps the fenced aggregate."""

    def setUp(self):
        cache.clear()
        self.employer = _employer("View Co")
        rows = [(f"ENGINEER {i}", 100000 + i * 1000, 2024, "CA") for i in range(120)]
        rows += [(f"ACCOUNTANT {i}", 50000 + i, 2024, "CA") for i in range(20)]
        _seed(self.employer, rows)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE salary_record")

    def test_free_text_search_uses_no_fence(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("salary_search"), {"q": "engineer"})
        self.assertEqual(response.status_code, 200)
        sql = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("_fenced", sql)
        self.assertIn("SET LOCAL enable_seqscan = off", sql)
        self.assertEqual(response.context["total_results"], 120)
        top = [r.wage_annual for r in response.context["records"]]
        self.assertEqual(len(top), 50)
        self.assertEqual(int(top[0]), 219000)
        self.assertEqual(int(top[-1]), 170000)

    def test_employer_filter_keeps_the_fenced_aggregate(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                reverse("salary_search"), {"q": "engineer", "employer": "View Co"}
            )
        self.assertEqual(response.status_code, 200)
        aggregates = [q["sql"] for q in ctx.captured_queries if "count(*)" in q["sql"]]
        self.assertTrue(any("_fenced" in sql for sql in aggregates), aggregates)
        self.assertEqual(response.context["total_results"], 120)

    def test_result_rows_load_case_submitted_in_the_page_query(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("salary_search"), {"q": "engineer"})
        per_row = [q for q in ctx.captured_queries
                   if '"case_submitted" FROM "salary_record" WHERE "salary_record"."id" =' in q["sql"]]
        self.assertEqual(per_row, [])
