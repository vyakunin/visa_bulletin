"""Regression tests for the single-scan page+aggregate resolver.

fenced_page_and_aggregate() replaced the fenced_aggregate() + fenced_page_ids()
pair on COLD /salaries/ searches. The pair materialized the full filtered match
set twice per request (the trigram Bitmap Heap Scan over salary_record — the
``?q=`` double-scan residual from the 2026-06-21 504 swarm); the combined query
materializes it once (``WITH _fenced AS MATERIALIZED``) and derives both the
top-N page and count/avg/min/max from that tuplestore.

These tests pin its CORRECTNESS — it must return exactly the page
fenced_page_ids() returns and exactly the aggregate fenced_aggregate() returns
— plus the SQL shape (single MATERIALIZED fence), so a perf tweak can't
silently change the numbers or reintroduce the double scan.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.utils.filter_utils import (
    apply_text_search_filter,
    fenced_aggregate,
    fenced_page_and_aggregate,
    fenced_page_ids,
)
from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord

_ORDER = ("-wage_annual", "-fiscal_year")


class FencedPageAndAggregateTest(TestCase):
    def setUp(self):
        cluster = EmployerCluster.objects.create(
            canonical_name="Combined Co", slug="combined-co"
        )
        self.employer = Employer.objects.create(
            name="Combined Co",
            name_normalized="combined co",
            canonical_cluster=cluster,
        )
        # 7 ENGINEER rows with distinct wages (ordering is deterministic) plus
        # rows the filter must exclude (other title, zero wage, worksite).
        wages = [200000, 180000, 160000, 150000, 140000, 130000, 120000]
        for idx, wage in enumerate(wages):
            SalaryRecord.objects.create(
                case_number=f"CMB-{idx}",
                employer=self.employer,
                employer_name=self.employer.name,
                job_title=f"Software Engineer {idx}",
                wage_annual=wage,
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2020 + idx,
                worksite_state="CA",
                is_worksite=False,
            )
        SalaryRecord.objects.create(
            case_number="CMB-OTHER",
            employer=self.employer,
            employer_name=self.employer.name,
            job_title="Accountant",
            wage_annual=999999,
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
            worksite_state="CA",
            is_worksite=False,
        )

    def _engineers(self):
        qs = SalaryRecord.objects.all()
        qs = apply_text_search_filter(qs, "Engineer", ["job_title", "soc_title"])
        qs = qs.exclude(is_worksite=True).filter(
            wage_annual__isnull=False, wage_annual__gt=0
        )
        return qs

    def _assert_matches_pair(self, qs, offset: int, limit: int):
        """The combined call must equal the (page_ids, aggregate) pair it replaced."""
        page_ids, agg = fenced_page_and_aggregate(
            qs, _ORDER, offset, limit, "wage_annual"
        )
        expected_ids = fenced_page_ids(qs, _ORDER, offset, limit)
        expected_agg = fenced_aggregate(qs, "wage_annual")
        self.assertEqual(page_ids, expected_ids)
        self.assertEqual(agg.count, expected_agg.count)
        self.assertEqual(agg.min, expected_agg.min)
        self.assertEqual(agg.max, expected_agg.max)
        if expected_agg.avg is None:
            self.assertIsNone(agg.avg)
        else:
            self.assertAlmostEqual(float(agg.avg), float(expected_agg.avg), places=2)

    def test_first_page_matches_pair(self):
        self._assert_matches_pair(self._engineers(), offset=0, limit=3)

    def test_middle_page_matches_pair(self):
        self._assert_matches_pair(self._engineers(), offset=3, limit=3)

    def test_partial_last_page_matches_pair(self):
        # 7 matches, offset 6 limit 3 → 1-row page; aggregate still full-set.
        self._assert_matches_pair(self._engineers(), offset=6, limit=3)

    def test_offset_beyond_end_returns_empty_page_with_correct_aggregate(self):
        # The beyond-last-page shape (bot page=99999): empty page, but the
        # aggregate must still describe the full match set so the view can
        # clamp pagination and cache the count.
        page_ids, agg = fenced_page_and_aggregate(
            self._engineers(), _ORDER, 500, 50, "wage_annual"
        )
        self.assertEqual(page_ids, [])
        self.assertEqual(agg.count, 7)
        self.assertEqual(float(agg.max), 200000.0)

    def test_no_match_is_empty_and_zero(self):
        qs = SalaryRecord.objects.all()
        qs = apply_text_search_filter(qs, "NONEXISTENTZZZ", ["job_title", "soc_title"])
        page_ids, agg = fenced_page_and_aggregate(qs, _ORDER, 0, 50, "wage_annual")
        self.assertEqual(page_ids, [])
        self.assertEqual(agg.count, 0)
        self.assertIsNone(agg.avg)
        self.assertIsNone(agg.min)
        self.assertIsNone(agg.max)

    def test_provably_empty_queryset_returns_empty_not_raises(self):
        # The employer free-text ``records.none()`` path raises EmptyResultSet
        # from as_sql(); the combined resolver must swallow it like both of the
        # functions it replaced do.
        for qs in (
            SalaryRecord.objects.none(),
            SalaryRecord.objects.filter(pk__in=[]),
            SalaryRecord.objects.filter(employer__canonical_cluster_id__in=[]),
        ):
            page_ids, agg = fenced_page_and_aggregate(
                qs, _ORDER, 0, 50, "wage_annual"
            )
            self.assertEqual(page_ids, [])
            self.assertEqual(agg.count, 0)
            self.assertIsNone(agg.avg)

    def test_emits_single_materialized_fence(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Non-zero page offset so the page's own "OFFSET 3" can't be confused
        # with the "OFFSET 0" optimization fence in the assertions below.
        with CaptureQueriesContext(connection) as ctx:
            fenced_page_and_aggregate(
                self._engineers(), _ORDER, 3, 3, "wage_annual"
            )
        sql = ctx.captured_queries[-1]["sql"]
        self.assertIn("AS MATERIALIZED", sql)
        self.assertIn("OFFSET 0", sql)
        # ONE materialized fence feeding both consumers — the point of the fix.
        self.assertEqual(sql.count("AS MATERIALIZED"), 2)  # _fenced + _page
        self.assertEqual(sql.count("OFFSET 0"), 1)
        self.assertIn("count(*)", sql)
