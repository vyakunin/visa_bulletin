"""Regression tests for the OFFSET-0 fenced aggregate.

fenced_aggregate() replaced the plain ``.aggregate(Count/Avg/Min/Max)`` in the
salary search count/stats path. Without the fence, a queryset combining a
trigram text filter + an employer-FK filter + a worksite_state filter (e.g.
q=Financial Analyst + Goldman Sachs + NY) compiles to a Nested Loop Semi Join
that re-scans the full ~30k-row trigram match set and times out (>120s → 504 on
/salaries/). These tests pin its CORRECTNESS — it must return the same count and
avg/min/max as the naive .aggregate() it replaced — so a future perf tweak can't
silently change the numbers shown, and the OFFSET-0 fence isn't accidentally
dropped (which would reintroduce the timeout).
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.db.models import Avg, Count, Max, Min
from django.test import TestCase

from lib.utils.filter_utils import apply_text_search_filter, fenced_aggregate
from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord


def _naive(qs):
    """The exact aggregate fenced_aggregate replaced."""
    agg = qs.aggregate(
        count=Count("id"),
        avg=Avg("wage_annual"),
        min=Min("wage_annual"),
        max=Max("wage_annual"),
    )
    return agg["count"] or 0, agg["avg"], agg["min"], agg["max"]


class FencedAggregateTest(TestCase):
    def setUp(self):
        self.cluster = EmployerCluster.objects.create(
            canonical_name="Goldman Test", slug="goldman-test"
        )
        other = EmployerCluster.objects.create(
            canonical_name="Other Co", slug="other-co"
        )
        self.employer = Employer.objects.create(
            name="Goldman Test",
            name_normalized="goldman test",
            canonical_cluster=self.cluster,
        )
        other_emp = Employer.objects.create(
            name="Other Co", name_normalized="other co", canonical_cluster=other
        )
        # Goldman + NY + "Financial Analyst" → the target combo (3 matches),
        # plus rows the filters must exclude: wrong employer, wrong state,
        # wrong title, worksite row, null/zero wage.
        rows = [
            (self.employer, "Financial Analyst", "NY", 120000, 2024, False),
            (self.employer, "Senior Financial Analyst", "NY", 180000, 2023, False),
            (self.employer, "FINANCIAL ANALYST II", "NY", 150000, 2022, False),
            (self.employer, "Financial Analyst", "CA", 130000, 2024, False),  # state
            (self.employer, "Software Engineer", "NY", 200000, 2024, False),  # title
            (other_emp, "Financial Analyst", "NY", 999999, 2024, False),  # employer
            (self.employer, "Financial Analyst", "NY", 999999, 2024, True),  # worksite
            (self.employer, "Financial Analyst", "NY", 0, 2024, False),  # zero wage
        ]
        for idx, (emp, title, state, wage, fy, ws) in enumerate(rows):
            SalaryRecord.objects.create(
                case_number=f"AGG-{idx}",
                employer=emp,
                employer_name=emp.name,
                job_title=title,
                wage_annual=wage,
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=fy,
                worksite_state=state,
                is_worksite=ws,
            )

    def _goldman_ny_analyst(self):
        qs = SalaryRecord.objects.all()
        qs = apply_text_search_filter(qs, "Financial Analyst", ["job_title", "soc_title"])
        qs = qs.filter(employer__canonical_cluster_id=self.cluster.id)
        qs = qs.filter(worksite_state="NY")
        qs = qs.exclude(is_worksite=True).exclude(employer_name="Unknown")
        return qs.filter(wage_annual__isnull=False, wage_annual__gt=0)

    def _assert_matches_naive(self, qs):
        count, avg, min_, max_ = fenced_aggregate(qs, "wage_annual")
        n_count, n_avg, n_min, n_max = _naive(qs)
        self.assertEqual(count, n_count)
        self.assertEqual(min_, n_min)
        self.assertEqual(max_, n_max)
        # Avg can differ in Decimal scale between the two SQL shapes; compare value.
        if n_avg is None:
            self.assertIsNone(avg)
        else:
            self.assertAlmostEqual(float(avg), float(n_avg), places=2)

    def test_target_combo_matches_naive(self):
        # The exact shape that timed out in prod: trigram + FK cluster + state.
        qs = self._goldman_ny_analyst()
        self.assertEqual(qs.count(), 3)  # excludes state/title/employer/worksite/zero
        self._assert_matches_naive(qs)

    def test_text_only_matches_naive(self):
        qs = SalaryRecord.objects.all()
        qs = apply_text_search_filter(qs, "Financial Analyst", ["job_title", "soc_title"])
        qs = qs.exclude(is_worksite=True).filter(wage_annual__gt=0)
        self._assert_matches_naive(qs)

    def test_no_match_is_zero_and_nulls(self):
        qs = SalaryRecord.objects.all()
        qs = apply_text_search_filter(qs, "NONEXISTENTZZZ", ["job_title", "soc_title"])
        count, avg, min_, max_ = fenced_aggregate(qs, "wage_annual")
        self.assertEqual(count, 0)
        self.assertIsNone(avg)
        self.assertIsNone(min_)
        self.assertIsNone(max_)

    def test_emits_offset_zero_fence(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            fenced_aggregate(self._goldman_ny_analyst(), "wage_annual")
        sql = ctx.captured_queries[-1]["sql"]
        self.assertIn("OFFSET 0", sql)
        self.assertIn("_fenced", sql)
        self.assertIn("count(*)", sql)
