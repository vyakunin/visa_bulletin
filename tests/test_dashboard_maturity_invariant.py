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
    _apply_reconciled_trajectory,
    _build_unified_prediction_rows,
    _counterpart_action_type,
    _reconcile_prediction_pair,
    _reconcile_projection_estimate,
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

    def test_clamped_filing_never_lands_after_final_action(self):
        """With the Final Action bound wired in, Filing is pulled DOWN to <= Final Action."""
        label = "EB-1: Priority Workers"

        final_rows = self._rows(self.final_dates, self.final_cutoffs)
        final_est = final_rows[0]["linear_maturity"]
        final_maturity_lookup = {label: final_est}

        # Baseline: unclamped Filing violates the invariant (lands after Final Action).
        filing_est_unclamped = self._rows(self.filing_dates, self.filing_cutoffs)[0]["linear_maturity"]
        self.assertGreater(filing_est_unclamped, final_est)

        filing_rows = self._rows(
            self.filing_dates, self.filing_cutoffs,
            counterpart_maturity=final_maturity_lookup,
            is_filing=True,
        )
        filing_est = filing_rows[0]["linear_maturity"]

        self.assertIsNotNone(filing_est)
        self.assertLessEqual(filing_est, final_est)
        # Clamped exactly to the Final Action date, not to some third value.
        self.assertEqual(filing_est, final_est)

    def test_final_action_estimate_is_never_pushed_later_by_filing(self):
        """
        The clamp is one-directional. Rendering the Final Action page must NOT drag
        its estimate later to match a slower/plateaued Filing projection — Final
        Action's own (here earlier, faster) projection is the binding upper bound.
        This is the quality guard on the reported EB-1 India shape: FAD ~2027 must
        stay ~2027, not get pushed to Filing's bogus ~2029.
        """
        label = "EB-1: Priority Workers"

        final_rows_unclamped = self._rows(self.final_dates, self.final_cutoffs)
        final_est_unclamped = final_rows_unclamped[0]["linear_maturity"]

        # Filing's own (unclamped) estimate is LATER than Final Action's.
        filing_est_unclamped = self._rows(self.filing_dates, self.filing_cutoffs)[0]["linear_maturity"]
        self.assertGreater(filing_est_unclamped, final_est_unclamped)

        # Render the Final Action page with Filing supplied as the counterpart.
        # is_filing=False → no clamp applies; Final Action is preserved.
        final_rows_clamped = self._rows(
            self.final_dates, self.final_cutoffs,
            counterpart_maturity={label: filing_est_unclamped},
            is_filing=False,
        )
        final_est_clamped = final_rows_clamped[0]["linear_maturity"]

        self.assertEqual(final_est_clamped, final_est_unclamped)
        self.assertLess(final_est_clamped, filing_est_unclamped)


def _pred(start: date, cutoffs: list[date | None], submission_date: date) -> dict:
    """A minimal VQS `pred` dict (as _get_vqs_predictions emits) for a monthly
    trajectory: cells anchored to the 1m/6m/12m months, maturity from the path."""
    traj = [(start + relativedelta(months=i), c) for i, c in enumerate(cutoffs)]
    maturity = None
    for month, cutoff in traj:
        if cutoff is not None and cutoff >= submission_date:
            maturity = month
            break
    return {
        "next_cutoff": cutoffs[0],
        "cutoff_6m": cutoffs[6] if len(cutoffs) > 6 else None,
        "cutoff_12m": cutoffs[12] if len(cutoffs) > 12 else None,
        "maturity_month": maturity,
        "trajectory": [(m, c) for m, c in traj if c is not None],
        "next_cutoff_month": traj[0][0],
        "cutoff_6m_month": traj[6][0] if len(traj) > 6 else None,
        "cutoff_12m_month": traj[12][0] if len(traj) > 12 else None,
    }


class TestTrajectoryReconciliation(unittest.TestCase):
    """The FULL-trajectory generalization (Option B): after reconciliation the
    DFF≥FAD invariant holds at every cutoff CELL, not just the scalar maturity.
    Exercises the dashboard glue (_reconcile_prediction_pair / _apply_reconciled_
    trajectory) over a crossing pair — the pathological shape reconciliation repairs.
    """

    def setUp(self):
        self.k = date(2026, 1, 1)
        self.sub = date(2025, 6, 1)
        # FAD races ahead of DFF (a crossing: Filing cutoff BELOW Final Action —
        # impossible in reality). 24 monthly steps.
        self.fad = _pred(self.k, [date(2024, 1, 1) + relativedelta(months=3 * i) for i in range(24)], self.sub)
        self.dff = _pred(self.k, [date(2024, 6, 1) + relativedelta(months=1 * i) for i in range(24)], self.sub)

    def test_raw_pair_violates_at_cells(self):
        # Precondition: unreconciled, the 12m cell already violates DFF>=FAD.
        self.assertLess(self.dff["cutoff_12m"], self.fad["cutoff_12m"])

    def test_reconciled_trajectory_holds_invariant_at_every_step(self):
        for w in (0.0, 0.5, 1.0):
            fad2, dff2 = _reconcile_prediction_pair(self.fad, self.dff, w, self.sub)
            fad_by_m = dict(fad2["trajectory"])
            for month, dff_c in dff2["trajectory"]:
                self.assertGreaterEqual(
                    dff_c, fad_by_m[month],
                    f"cell invariant DFF>=FAD violated at {month} for w={w}",
                )

    def test_reconciled_cells_and_maturity_ordered(self):
        # Symmetric split (China-style): every displayed cell + maturity is ordered.
        fad2, dff2 = _reconcile_prediction_pair(self.fad, self.dff, 0.5, self.sub)
        for cell in ("next_cutoff", "cutoff_6m", "cutoff_12m"):
            if dff2[cell] is not None and fad2[cell] is not None:
                self.assertGreaterEqual(dff2[cell], fad2[cell], f"{cell} not ordered")
        if dff2["maturity_month"] and fad2["maturity_month"]:
            # Filing matures no later than Final Action.
            self.assertLessEqual(dff2["maturity_month"], fad2["maturity_month"])

    def test_w1_keeps_dff_moves_fad_cells(self):
        # India-style: trust the smooth DFF — DFF cells unchanged, FAD pulled onto it.
        fad2, dff2 = _reconcile_prediction_pair(self.fad, self.dff, 1.0, self.sub)
        self.assertEqual(dff2["trajectory"], self.dff["trajectory"])  # DFF untouched
        self.assertEqual(dff2["cutoff_12m"], self.dff["cutoff_12m"])
        # FAD's violating 12m cell was pulled down onto DFF's value.
        self.assertEqual(fad2["cutoff_12m"], self.dff["cutoff_12m"])

    def test_already_ordered_pair_passes_through(self):
        # DFF genuinely ahead of FAD (the normal, correctly-ordered case): no change.
        fad = _pred(self.k, [date(2020, 1, 1) + relativedelta(months=i) for i in range(24)], self.sub)
        dff = _pred(self.k, [date(2022, 1, 1) + relativedelta(months=i) for i in range(24)], self.sub)
        fad2, dff2 = _reconcile_prediction_pair(fad, dff, 0.5, self.sub)
        self.assertEqual(fad2["trajectory"], fad["trajectory"])
        self.assertEqual(dff2["trajectory"], dff["trajectory"])
        self.assertEqual(fad2["cutoff_12m"], fad["cutoff_12m"])
        self.assertEqual(dff2["cutoff_12m"], dff["cutoff_12m"])

    def test_apply_reconciled_trajectory_absent_month_yields_none_cell(self):
        # A 6m cell whose month drops out of the reconciled trajectory -> None,
        # matching the original None-cutoff semantics.
        pred = _pred(self.k, [date(2024, 1, 1) + relativedelta(months=i) for i in range(24)], self.sub)
        # Reconciled trajectory omits the 6m anchor month.
        anchor6 = pred["cutoff_6m_month"]
        reduced = [(m, c) for m, c in pred["trajectory"] if m != anchor6]
        out = _apply_reconciled_trajectory(pred, reduced, self.sub)
        self.assertIsNone(out["cutoff_6m"])


class TestProjectionEstimateReconciliation(unittest.TestCase):
    """The 4th surface: the chart forecast-diamond (calculate_projection.estimated_date)
    is pulled onto Final Action when a Filing estimate lands later, in place."""

    def test_filing_estimate_pulled_down_and_fields_recomputed(self):
        fad_est = date(2027, 3, 1)
        proj = {"status": "projected", "estimated_date": date(2029, 3, 1),
                "months_to_wait": 40, "message": "Estimated processing in 40 months"}
        _reconcile_projection_estimate(proj, fad_est)
        self.assertEqual(proj["estimated_date"], fad_est)  # pulled DOWN onto FAD
        # months_to_wait + message recomputed to stay consistent with the new date
        self.assertIn("Estimated processing in", proj["message"])
        self.assertIsInstance(proj["months_to_wait"], int)
        self.assertGreaterEqual(proj["months_to_wait"], 0)

    def test_ordered_estimate_untouched(self):
        proj = {"status": "projected", "estimated_date": date(2026, 1, 1),
                "months_to_wait": 6, "message": "Estimated processing in 6 months"}
        _reconcile_projection_estimate(proj, date(2028, 1, 1))  # FAD later -> Filing already ok
        self.assertEqual(proj["estimated_date"], date(2026, 1, 1))
        self.assertEqual(proj["message"], "Estimated processing in 6 months")

    def test_none_cases_noop(self):
        _reconcile_projection_estimate(None, date(2027, 1, 1))  # no projection
        proj = {"status": "current", "estimated_date": None, "months_to_wait": 0}
        _reconcile_projection_estimate(proj, date(2027, 1, 1))  # no estimate
        self.assertIsNone(proj["estimated_date"])
        proj2 = {"estimated_date": date(2029, 1, 1)}
        _reconcile_projection_estimate(proj2, None)  # no counterpart
        self.assertEqual(proj2["estimated_date"], date(2029, 1, 1))


if __name__ == "__main__":
    unittest.main()
