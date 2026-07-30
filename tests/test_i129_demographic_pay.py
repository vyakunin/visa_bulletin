"""Tests for the sorting-adjusted demographic pay breakdown.

Locks the three properties that make this surface honest rather than misleading:

1. A raw demographic gap that is PURELY occupational sorting adjusts to ~0. This is
   the published gender result and the reason the module exists — if it ever stops
   holding, a page built on it starts asserting a pay gap that is really a job mix.
2. A gap that is NOT sorting survives adjustment, so the module cannot simply be
   flattening everything to zero.
3. Petitions with a BLANK job title are excluded. Pooling them fabricates a
   within-occupation gap (RIGOR_REVIEW.md:216 — it faked a +3.1% gender gap), so
   this is the specific defect the scoping guards against.

Plus the suppression rules: thin values get no row, thin overlap gets no adjusted
figure, and an employer scope restricts the population.
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.i129.demographic_pay import (
    MIN_ADJUSTED_N,
    MIN_VALUE_N,
    PayDimension,
    get_demographic_pay,
)
from models.i129 import I129Petition
from models.salary import EmployerCluster


def _petitions(country, job_title, pay, count, *, cluster=None, start=0):
    """`count` petitions sharing a country / title / pay, with unique case numbers."""
    I129Petition.objects.bulk_create(
        [
            I129Petition(
                dol_eta_case_number=f"I-200-{country}-{job_title[:4]}-{start + i:06d}",
                fiscal_year=2023,
                country_of_birth=country,
                job_title=job_title,
                pay_annual=Decimal(pay),
                employer_cluster=cluster,
            )
            for i in range(count)
        ]
    )


class DemographicPayTests(TestCase):
    def test_pure_sorting_gap_adjusts_to_zero(self):
        """Same pay within every job; one group just holds the better-paid job.

        Raw looks like a large premium; within-occupation it is nothing. A surface
        that showed only the raw number here would be asserting a pay gap that does
        not exist — the exact error the gender decomposition corrected.
        """
        # Both groups are paid identically inside each title.
        _petitions("AAA", "Engineer", 150_000, 600)
        _petitions("BBB", "Engineer", 150_000, 600, start=1000)
        _petitions("AAA", "Analyst", 80_000, 600, start=2000)
        _petitions("BBB", "Analyst", 80_000, 5_400, start=3000)
        # AAA sits half in the high-paying job, BBB mostly in the low-paying one.

        breakdown = get_demographic_pay(PayDimension.COUNTRY_OF_BIRTH)
        cells = {c.value: c for c in breakdown.cells}

        self.assertGreater(cells["AAA"].raw_gap, 20_000, "raw gap should look large")
        self.assertEqual(
            cells["AAA"].within_occupation_gap,
            0,
            "identical pay within every job must adjust to exactly zero",
        )
        self.assertAlmostEqual(cells["AAA"].sorting_share_pct, 100.0, places=1)

    def test_real_gap_survives_adjustment(self):
        """A group genuinely paid more for the SAME job keeps its gap."""
        _petitions("AAA", "Engineer", 120_000, 1_000)
        _petitions("BBB", "Engineer", 100_000, 1_000, start=1000)

        cells = {
            c.value: c
            for c in get_demographic_pay(PayDimension.COUNTRY_OF_BIRTH).cells
        }
        self.assertEqual(cells["AAA"].within_occupation_gap, 10_000)
        self.assertEqual(cells["BBB"].within_occupation_gap, -10_000)

    def test_blank_job_titles_are_excluded(self):
        """The documented pitfall: blank-title rows must not reach any figure.

        Here the blank-title rows would drag AAA's median down hard if pooled.
        """
        _petitions("AAA", "Engineer", 120_000, 1_000)
        _petitions("BBB", "Engineer", 120_000, 1_000, start=1000)
        _petitions("AAA", "", 10_000, 5_000, start=2000)

        cells = {
            c.value: c
            for c in get_demographic_pay(PayDimension.COUNTRY_OF_BIRTH).cells
        }
        self.assertEqual(cells["AAA"].n, 1_000, "blank-title rows must not be counted")
        self.assertEqual(cells["AAA"].median_pay, 120_000)
        self.assertEqual(cells["AAA"].within_occupation_gap, 0)

    def test_thin_value_gets_no_row(self):
        _petitions("AAA", "Engineer", 120_000, 1_000)
        _petitions("TIN", "Engineer", 120_000, MIN_VALUE_N - 1, start=1000)

        values = {c.value for c in get_demographic_pay(PayDimension.COUNTRY_OF_BIRTH).cells}
        self.assertIn("AAA", values)
        self.assertNotIn("TIN", values, "below MIN_VALUE_N must be suppressed entirely")

    def test_thin_overlap_gets_raw_figure_but_no_adjusted_one(self):
        """A value big enough to list, too thin to adjust, shows raw only.

        This is the TWN/KOR case on real data — enough petitions for a row, not
        enough within-occupation overlap for the adjustment to mean anything.
        """
        _petitions("AAA", "Engineer", 120_000, 5_000)
        # Just over the listing floor, but its own title is too small to be a
        # stratum, so nothing of it enters the adjustment.
        _petitions("THN", "Rare Job", 200_000, MIN_VALUE_N + 10, start=9000)

        cells = {
            c.value: c
            for c in get_demographic_pay(PayDimension.COUNTRY_OF_BIRTH).cells
        }
        self.assertIsNotNone(cells["THN"].raw_gap)
        self.assertIsNone(
            cells["THN"].within_occupation_gap,
            "no qualifying strata must mean no adjusted figure, not a zero",
        )
        self.assertIsNone(cells["THN"].sorting_share_pct)
        self.assertLess(cells["THN"].adjusted_n, MIN_ADJUSTED_N)

    def test_employer_scope_restricts_the_population(self):
        cluster = EmployerCluster.objects.create(canonical_name="Test Co")
        _petitions("AAA", "Engineer", 200_000, 600, cluster=cluster)
        _petitions("AAA", "Engineer", 100_000, 600, start=1000)

        scoped = get_demographic_pay(
            PayDimension.COUNTRY_OF_BIRTH, employer_cluster_id=cluster.id
        )
        self.assertEqual(scoped.overall_n, 600)
        self.assertEqual(scoped.cells[0].median_pay, 200_000)

    def test_invalid_dimension_returns_none(self):
        self.assertIsNone(get_demographic_pay(PayDimension.INVALID))

    def test_empty_population_returns_none(self):
        self.assertIsNone(get_demographic_pay(PayDimension.COUNTRY_OF_BIRTH))

    def test_from_str_never_raises_on_unknown(self):
        self.assertEqual(PayDimension.from_str("country"), PayDimension.COUNTRY_OF_BIRTH)
        self.assertEqual(PayDimension.from_str("nonsense"), PayDimension.INVALID)
        self.assertEqual(PayDimension.from_str(None), PayDimension.INVALID)
