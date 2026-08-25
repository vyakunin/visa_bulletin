"""Every column this site labels "Median Salary" now shows a median.

They all used to show a mean. ``Avg("wage_annual")`` was aliased to the dict key
``median_salary`` at 18 call sites, so the label was wrong on the header stat cards
AND on every per-group table column — top employers, experience levels, metros,
company comparison, the year-over-year trend.

The visible symptom was on /job-title/senior-software-engineer/: the header card read
$141,112 and the Salary Distribution card one screen below read $135,000, over the
same rows. Measured on prod for that cluster's selected window: n=14,614, mean
141,112, p50 135,000. Wage distributions are right-skewed, so the mean sat above the
median on essentially every page and every group, not just that one.

Two mechanisms, because the two shapes have different costs:
- GROUPED annotations use the ``Median`` aggregate (percentile_cont within group).
- UNGROUPED aggregates compute no median at all; the caller assigns the p50 it already
  computes over the same queryset, so the set is sorted once rather than twice.

See Notion 3bf62b8d409f810c836cc5f970b980c1.
"""

from decimal import Decimal
from pathlib import Path

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.db.models import Avg, Count
from django.test import TestCase

from lib.business.salary.common_stats import Median
from models.enums.visa_program import VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord

_TEMPLATES = Path(__file__).resolve().parents[1] / "webapp" / "templates" / "webapp"

# (template, the context path each page's median card must read)
_CARDS = {
    "job_title_profile.html": "stats.salary_percentiles.p50",
    "employer_profile.html": "stats.salary_percentiles.p50",
    "salary_search.html": "market_stats.salary_percentiles.p50",
}


def _median_card(template_name: str) -> str:
    """The one stat_card include on this page labelled "Median Salary"."""
    text = (_TEMPLATES / template_name).read_text()
    cards = [
        line
        for line in text.splitlines()
        if "stat_card.html" in line and 'label="Median Salary"' in line
    ]
    assert len(cards) == 1, f"{template_name}: expected 1 median card, got {len(cards)}"
    return cards[0]


class TestMedianCardsReadThePercentile(TestCase):
    def test_each_card_reads_the_p50_its_page_computes(self):
        for template_name, context_path in _CARDS.items():
            with self.subTest(template=template_name):
                self.assertIn(context_path, _median_card(template_name))

    def test_job_title_card_no_longer_calls_a_median_a_national_average(self):
        self.assertNotIn("National Average", _median_card("job_title_profile.html"))


class TestNoMedianIsComputedAsAMean(TestCase):
    """The class this closed. Read through each module's own ``__file__`` so the
    check follows the sources wherever the runfiles tree puts them."""

    def _sources(self):
        from lib.business.salary import common_stats, job_title_stats, market_overview
        from webapp.views.employers import profile as employer_profile
        from webapp.views.salary import by_state

        for module in (
            common_stats,
            job_title_stats,
            market_overview,
            employer_profile,
            by_state,
        ):
            yield module.__name__, Path(module.__file__).read_text()

    def test_no_module_aliases_an_average_to_median_salary(self):
        for name, source in self._sources():
            with self.subTest(module=name):
                self.assertNotIn(
                    'median_salary=Avg(',
                    source,
                    f"{name} labels a mean 'median_salary' again — use Median() for a "
                    "grouped annotation, or assign the p50 the caller already computes.",
                )


class TestMedianAggregate(TestCase):
    """A skewed group, where the mean and the median are far apart and only one of
    them is the median. Runs against Postgres, which is what the test database is."""

    # Median 100, mean 340 — the long right tail is what wage data looks like.
    WAGES = [20_000, 60_000, 100_000, 120_000, 2_400_000]

    def setUp(self):
        cluster = EmployerCluster.objects.create(slug="acme", canonical_name="Acme Inc")
        employer = Employer.objects.create(
            name="Acme Inc",
            name_normalized="acme",
            city="San Francisco",
            state="CA",
            canonical_cluster=cluster,
        )
        for i, wage in enumerate(self.WAGES):
            SalaryRecord.objects.create(
                case_number=f"MED-{i}",
                visa_program=VisaProgram.H1B,
                employer=employer,
                employer_name=employer.name,
                job_title="Engineer",
                wage_annual=Decimal(str(wage)),
                worksite_state="CA",
                is_worksite=False,
                fiscal_year=2025,
            )

    def _grouped(self):
        return (
            SalaryRecord.objects.filter(case_number__startswith="MED-")
            .values("worksite_state")
            .annotate(
                count=Count("id"),
                median_salary=Median("wage_annual"),
                mean_salary=Avg("wage_annual"),
            )
        )

    def test_grouped_median_is_the_middle_value(self):
        row = self._grouped().get()
        self.assertEqual(row["count"], len(self.WAGES))
        self.assertEqual(float(row["median_salary"]), 100_000.0)

    def test_the_mean_would_have_been_wrong_by_an_order_of_magnitude(self):
        row = self._grouped().get()
        self.assertGreater(float(row["mean_salary"]), 500_000.0)
        self.assertLess(float(row["median_salary"]), float(row["mean_salary"]))
