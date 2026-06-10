"""Regression tests for the OFFSET-0 fenced page resolution.

fenced_page_ids() replaced the slow ``.order_by('-wage_annual','-fiscal_year')[slice]``
row-fetch on the salary / worksite list views (prod: ENGINEERS p4 5959→1614ms,
ARCHITECT 2444→479ms, CASHIER 39→6ms). These tests pin its CORRECTNESS — it must
return exactly the same pks, in the same order, as the naive sliced query it
replaced — so a future perf tweak can't silently change which rows a page shows.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.utils.filter_utils import apply_text_search_filter, fenced_page_ids
from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord

ORDER = ("-wage_annual", "-fiscal_year")


def _naive_ids(qs, offset, limit):
    """The exact query fenced_page_ids replaced."""
    return list(
        qs.order_by(*ORDER).values_list("id", flat=True)[offset : offset + limit]
    )


class FencedPageIdsTest(TestCase):
    def setUp(self):
        cluster = EmployerCluster.objects.create(
            canonical_name="Fence Co", slug="fence-co"
        )
        self.employer = Employer.objects.create(
            name="Fence Co", name_normalized="fence co", canonical_cluster=cluster
        )
        # Mix of titles so we can exercise rare (CASHIER x1), common (ENGINEER xN),
        # tied wages (same wage, different fiscal_year → fiscal_year tiebreak),
        # and rows that the cheap filters must exclude.
        rows = []
        for i in range(40):
            rows.append(
                (f"ENGINEER {i}", 100000 + i * 1000, 2024 if i % 2 else 2020, False)
            )
        rows += [
            ("CASHIER", 35000, 2023, False),
            ("SENIOR ENGINEER", 250000, 2024, False),
            ("SENIOR ENGINEER", 250000, 2022, False),  # wage tie → fy tiebreak
            ("ENGINEER worksite", 999999, 2024, True),  # excluded: is_worksite
        ]
        for idx, (title, wage, fy, ws) in enumerate(rows):
            SalaryRecord.objects.create(
                case_number=f"FENCE-{idx}",
                employer=self.employer,
                employer_name="Fence Co",
                job_title=title,
                wage_annual=wage,
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=fy,
                worksite_state="CA",
                is_worksite=ws,
            )

    def _filtered(self, query):
        qs = SalaryRecord.objects.all()
        qs = apply_text_search_filter(qs, query, ["job_title", "soc_title"])
        qs = qs.exclude(is_worksite=True).exclude(employer_name="Unknown")
        return qs.filter(wage_annual__isnull=False, wage_annual__gt=0)

    def _assert_matches_naive(self, query, offset, limit):
        qs = self._filtered(query)
        fenced = fenced_page_ids(qs, ORDER, offset, limit)
        naive = _naive_ids(qs, offset, limit)
        self.assertEqual(
            fenced,
            naive,
            f"q={query!r} offset={offset} limit={limit}: fenced {fenced} != naive {naive}",
        )

    def test_no_query_first_page(self):
        self._assert_matches_naive("", 0, 10)

    def test_no_query_deep_page(self):
        self._assert_matches_naive("", 30, 10)

    def test_common_term(self):
        # ENGINEER matches many; ordering by wage desc then fy desc must hold,
        # including the SENIOR ENGINEER wage-tie broken by fiscal_year.
        self._assert_matches_naive("ENGINEER", 0, 10)

    def test_common_term_deep_page(self):
        self._assert_matches_naive("ENGINEER", 20, 10)

    def test_rare_term(self):
        self._assert_matches_naive("CASHIER", 0, 10)

    def test_offset_past_end_is_empty(self):
        self.assertEqual(fenced_page_ids(self._filtered("CASHIER"), ORDER, 50, 10), [])

    def test_no_match_is_empty(self):
        self.assertEqual(
            fenced_page_ids(self._filtered("NONEXISTENTZZZ"), ORDER, 0, 10), []
        )

    def test_worksite_rows_excluded(self):
        # The 999999-wage row is is_worksite=True; it must never be page 1 row 0.
        ids = fenced_page_ids(self._filtered("ENGINEER"), ORDER, 0, 5)
        wages = [
            SalaryRecord.objects.get(pk=i).wage_annual for i in ids
        ]
        self.assertNotIn(999999, [int(w) for w in wages])

    def test_provably_empty_queryset_returns_empty_not_raises(self):
        # Regression sibling of the fenced_aggregate fix: a provably-empty
        # queryset (the employer free-text ``records.none()`` path) makes
        # Django's compiler raise EmptyResultSet from as_sql(). fenced_page_ids
        # must swallow it and return [], not 500.
        for qs in (
            SalaryRecord.objects.none(),
            SalaryRecord.objects.filter(pk__in=[]),
            SalaryRecord.objects.filter(employer__canonical_cluster_id__in=[]),
        ):
            self.assertEqual(fenced_page_ids(qs, ORDER, 0, 10), [])

    def test_emits_offset_zero_fence(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            fenced_page_ids(self._filtered("ENGINEER"), ORDER, 0, 5)
        sql = ctx.captured_queries[-1]["sql"]
        self.assertIn("OFFSET 0", sql)
        self.assertIn("LIKE", sql)
        self.assertIn("_fenced", sql)
