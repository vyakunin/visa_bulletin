"""Unit + property tests for the FAD↔DFF reconciliation helper.

Proves the DFF≥FAD invariant is guaranteed *by construction* (not by an ad-hoc
clamp) for any confidence weight, and that the weight endpoints reproduce the
intended per-series behaviours. See lib/business/vqs/coupling.py and
docs/fad_dff_coupling_design.md.
"""

# Settings-only Django init: this module is pure math (no ORM/DB); it needs Django
# configured solely so the Country enum imports for the per-country weight check.
# Deliberately NOT setup_django_for_tests() — that creates+migrates a test DB this
# test never touches (and stalls collection under load).
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
os.environ.setdefault("RUNNING_TESTS", "1")
django.setup()

import unittest
from datetime import date

from dateutil.relativedelta import relativedelta

from lib.business.vqs.coupling import (
    LEGACY_CLAMP_W,
    reconcile_maturity,
    reconcile_pair,
    w_fad_concedes_for_country,
)
from models.enums.country import Country


def _traj(start: date, cutoffs: list[date | None]) -> list[tuple[date, date | None]]:
    """Build a monthly-stepped (month, cutoff) trajectory starting at `start`."""
    return [(start + relativedelta(months=i), c) for i, c in enumerate(cutoffs)]


class TestReconcilePairSemantics(unittest.TestCase):
    def setUp(self):
        self.m0 = date(2026, 8, 1)
        # A single violated step: FAD cutoff (2020-06-01) is LATER than DFF
        # cutoff (2020-01-01) -> Filing behind Final Action -> impossible -> repair.
        self.fad = _traj(self.m0, [date(2020, 6, 1)])
        self.dff = _traj(self.m0, [date(2020, 1, 1)])
        self.gap_days = (date(2020, 6, 1) - date(2020, 1, 1)).days

    def test_w1_moves_fad_onto_dff_keeps_dff(self):
        """w=1: trust the smooth DFF — FAD concedes fully, DFF untouched."""
        fad2, dff2 = reconcile_pair(self.fad, self.dff, 1.0)
        self.assertEqual(dff2[0][1], date(2020, 1, 1))  # DFF unchanged
        self.assertEqual(fad2[0][1], date(2020, 1, 1))  # FAD pulled onto DFF
        self.assertGreaterEqual(dff2[0][1], fad2[0][1])  # invariant

    def test_w0_moves_dff_onto_fad_keeps_fad_legacy_clamp(self):
        """w=0 == LEGACY_CLAMP_W: Final Action is the binding upper bound."""
        self.assertEqual(LEGACY_CLAMP_W, 0.0)
        fad2, dff2 = reconcile_pair(self.fad, self.dff, LEGACY_CLAMP_W)
        self.assertEqual(fad2[0][1], date(2020, 6, 1))  # FAD unchanged
        self.assertEqual(dff2[0][1], date(2020, 6, 1))  # DFF pulled onto FAD
        self.assertGreaterEqual(dff2[0][1], fad2[0][1])

    def test_w_half_meets_in_middle(self):
        """w=0.5: symmetric — both move to the same midpoint."""
        fad2, dff2 = reconcile_pair(self.fad, self.dff, 0.5)
        self.assertEqual(fad2[0][1], dff2[0][1])  # they meet
        # midpoint ~ halfway across the gap from each side
        self.assertEqual(fad2[0][1], date(2020, 6, 1) - relativedelta(days=round(self.gap_days / 2)))

    def test_already_ordered_is_untouched(self):
        fad = _traj(self.m0, [date(2020, 1, 1)])
        dff = _traj(self.m0, [date(2021, 1, 1)])  # DFF already ahead
        for w in (0.0, 0.5, 1.0):
            fad2, dff2 = reconcile_pair(fad, dff, w)
            self.assertEqual(fad2, fad)
            self.assertEqual(dff2, dff)

    def test_none_cutoffs_pass_through(self):
        fad = _traj(self.m0, [None, date(2020, 6, 1)])
        dff = _traj(self.m0, [date(2019, 1, 1), None])
        fad2, dff2 = reconcile_pair(fad, dff, 0.5)
        self.assertEqual(fad2, fad)  # no month has both sides non-None
        self.assertEqual(dff2, dff)

    def test_month_present_in_only_one_passes_through(self):
        fad = _traj(self.m0, [date(2020, 6, 1), date(2020, 7, 1)])
        dff = _traj(self.m0, [date(2019, 1, 1)])  # only month 0
        fad2, dff2 = reconcile_pair(fad, dff, 1.0)
        # month 0 reconciled (w=1 -> FAD onto DFF), month 1 (FAD-only) untouched
        self.assertEqual(fad2[0][1], date(2019, 1, 1))
        self.assertEqual(fad2[1][1], date(2020, 7, 1))
        self.assertEqual(dff2, dff)


class TestInvariantProperty(unittest.TestCase):
    """DFF_t >= FAD_t at every aligned non-None step, for any weight, over a grid."""

    def test_invariant_holds_over_grid(self):
        m0 = date(2026, 1, 1)
        # A deliberately crossing pair (FAD racing ahead of DFF) — the pathological
        # extrapolation shape reconciliation exists to repair.
        fad = _traj(m0, [date(2018, 1, 1) + relativedelta(months=3 * i) for i in range(24)])
        dff = _traj(m0, [date(2019, 1, 1) + relativedelta(months=1 * i) for i in range(24)])
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            fad2, dff2 = reconcile_pair(fad, dff, w)
            fad_by_m = dict(fad2)
            for month, dff_c in dff2:
                fad_c = fad_by_m[month]
                self.assertGreaterEqual(
                    dff_c, fad_c,
                    f"invariant DFF>=FAD violated at {month} for w={w}: dff={dff_c} fad={fad_c}",
                )

    def test_out_of_range_weight_is_clamped_not_crashed(self):
        m0 = date(2026, 1, 1)
        fad = _traj(m0, [date(2020, 6, 1)])
        dff = _traj(m0, [date(2020, 1, 1)])
        # w=2 clamps to 1 (FAD onto DFF); w=-1 clamps to 0 (DFF onto FAD)
        self.assertEqual(reconcile_pair(fad, dff, 2.0)[0][0][1], date(2020, 1, 1))
        self.assertEqual(reconcile_pair(fad, dff, -1.0)[1][0][1], date(2020, 6, 1))


class TestReconcileMaturity(unittest.TestCase):
    """Maturity mirror: DFF maturity <= FAD maturity (Filing matures no later)."""

    def test_violation_w1_moves_fad_keeps_dff(self):
        fad_m = date(2027, 3, 1)
        dff_m = date(2029, 3, 1)  # Filing maturing LATER than Final Action -> violation
        fad2, dff2 = reconcile_maturity(fad_m, dff_m, 1.0)
        self.assertEqual(dff2, dff_m)  # DFF kept
        self.assertEqual(fad2, dff_m)  # FAD pushed out onto DFF
        self.assertLessEqual(dff2, fad2)

    def test_violation_w0_moves_dff_keeps_fad_legacy(self):
        fad_m = date(2027, 3, 1)
        dff_m = date(2029, 3, 1)
        fad2, dff2 = reconcile_maturity(fad_m, dff_m, 0.0)
        self.assertEqual(fad2, fad_m)  # FAD (binding) kept
        self.assertEqual(dff2, fad_m)  # DFF pulled down onto FAD
        self.assertLessEqual(dff2, fad2)

    def test_already_ordered_untouched(self):
        fad_m = date(2029, 1, 1)
        dff_m = date(2027, 1, 1)  # Filing already matures earlier -> ok
        self.assertEqual(reconcile_maturity(fad_m, dff_m, 0.5), (fad_m, dff_m))

    def test_none_passthrough(self):
        d = date(2027, 1, 1)
        self.assertEqual(reconcile_maturity(None, d, 0.5), (None, d))
        self.assertEqual(reconcile_maturity(d, None, 0.5), (d, None))
        self.assertEqual(reconcile_maturity(None, None, 0.5), (None, None))


class TestPerCountryWeight(unittest.TestCase):
    def test_india_trusts_dff(self):
        self.assertEqual(w_fad_concedes_for_country(Country.INDIA.value), 1.0)

    def test_china_symmetric(self):
        self.assertEqual(w_fad_concedes_for_country(Country.CHINA.value), 0.5)

    def test_other_defaults_symmetric(self):
        self.assertEqual(w_fad_concedes_for_country(Country.ALL.value), 0.5)
        self.assertEqual(w_fad_concedes_for_country(Country.MEXICO.value), 0.5)


if __name__ == "__main__":
    unittest.main()
