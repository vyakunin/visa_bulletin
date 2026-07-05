"""
Regression test for the Filing/Final-Action maturity ordering invariant.

Final Action and Filing (Dates for Filing) cutoffs are forecast as fully
independent VQS/linear-extrapolation runs (see dashboard.py
_get_vqs_predictions / _build_unified_prediction_rows). Because a real Filing
cutoff is never behind its Final Action counterpart, a projected "Est. Current
Date" for Filing must never land LATER than the one for Final Action on the
same priority date -- but with no cross-check, the two independent linear
fallbacks can disagree on rate and violate that ordering.

Reported live 2026-07-05 via r/USCIS (u/TryMysterious8274): EB-1 India, PD
4/29/2025 showed Final Action ~2027 vs Filing ~2029, though Filing's current
cutoff was 14 months ahead of Final Action's. See Notion 39462b8d.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest
from datetime import date

from dateutil.relativedelta import relativedelta

from webapp.views.bulletin.dashboard import (
    _build_unified_prediction_rows,
    _counterpart_action_type,
)


def _vcd(label: str, dates: list[date], cutoffs: list[date]) -> dict:
    return {
        "visa_class_label": label,
        "visa_class": label,
        "dates": dates,
        "cutoff_dates": cutoffs,
        "last_bulletin_date": dates[-1] if dates else None,
    }


class TestCounterpartActionType(unittest.TestCase):
    def test_swaps_final_and_filing(self):
        self.assertEqual(_counterpart_action_type("final_action"), "filing")
        self.assertEqual(_counterpart_action_type("filing"), "final_action")


class TestMaturityInvariant(unittest.TestCase):
    """Filing's effective maturity must never be later than Final Action's."""

    def setUp(self):
        today = date.today()
        # A priority date still behind both current cutoffs (needs both series
        # to advance further to reach it) -- mirrors the reported EB-1 India case.
        self.submission_date = today - relativedelta(years=2)

        # Final Action: further behind today (more backlogged) but with a FAST
        # historical advancement rate over the lookback window.
        self.final_dates = [today - relativedelta(months=m) for m in (24, 12, 0)]
        self.final_cutoffs = [
            today - relativedelta(years=6, months=9),
            today - relativedelta(years=5),
            today - relativedelta(years=3, months=9),
        ]

        # Filing: currently AHEAD of Final Action (less backlogged) but nearly
        # FLAT/plateaued historically -- a much slower rate.
        self.filing_dates = [today - relativedelta(months=m) for m in (24, 12, 0)]
        self.filing_cutoffs = [
            today - relativedelta(years=2, months=8),
            today - relativedelta(years=2, months=7),
            today - relativedelta(years=2, months=6),
        ]

        # Sanity: Filing's current cutoff really is ahead of Final Action's.
        self.assertGreater(self.filing_cutoffs[-1], self.final_cutoffs[-1])

    def _rows(self, dates, cutoffs, label="EB-1: Priority Workers", counterpart_maturity=None, is_filing=False):
        vcd = [_vcd(label, dates, cutoffs)]
        return _build_unified_prediction_rows(
            vcd, {}, self.submission_date,
            counterpart_maturity=counterpart_maturity,
            is_filing=is_filing,
        )

    def test_unclamped_projections_can_violate_the_invariant(self):
        """Demonstrates the bug: independent projections can put Filing later than Final Action."""
        final_rows = self._rows(self.final_dates, self.final_cutoffs)
        filing_rows = self._rows(self.filing_dates, self.filing_cutoffs)

        final_est = final_rows[0]["linear_maturity"]
        filing_est = filing_rows[0]["linear_maturity"]
        self.assertIsNotNone(final_est)
        self.assertIsNotNone(filing_est)
        # This is the reported bug shape: Filing (ahead today) still lands later.
        self.assertGreater(filing_est, final_est)

    def test_clamped_projections_respect_the_invariant(self):
        """With the counterpart bound wired in, Filing must never land after Final Action."""
        label = "EB-1: Priority Workers"

        final_rows = self._rows(self.final_dates, self.final_cutoffs)
        final_est = final_rows[0]["linear_maturity"]
        final_maturity_lookup = {label: final_est}

        filing_rows = self._rows(
            self.filing_dates, self.filing_cutoffs,
            counterpart_maturity=final_maturity_lookup,
            is_filing=True,
        )
        filing_est = filing_rows[0]["linear_maturity"]

        self.assertIsNotNone(filing_est)
        self.assertLessEqual(filing_est, final_est)

        # And the symmetric direction: Final Action can't be clamped earlier
        # than Filing's own (unclamped) estimate.
        filing_rows_unclamped = self._rows(self.filing_dates, self.filing_cutoffs)
        filing_est_unclamped = filing_rows_unclamped[0]["linear_maturity"]
        filing_maturity_lookup = {label: filing_est_unclamped}
        final_rows_clamped = self._rows(
            self.final_dates, self.final_cutoffs,
            counterpart_maturity=filing_maturity_lookup,
            is_filing=False,
        )
        final_est_clamped = final_rows_clamped[0]["linear_maturity"]
        self.assertGreaterEqual(final_est_clamped, filing_est_unclamped)


if __name__ == "__main__":
    unittest.main()
