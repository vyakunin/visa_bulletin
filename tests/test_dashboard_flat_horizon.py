"""
Regression test: a horizon cell whose forecast equals the CURRENT cutoff must be
marked flat, so the dashboard can say "no step predicted" instead of restating
today's date as if it were a forecast.

Dates-for-Filing series are step functions, not trends: EB-1 India DoF moved on 7
of 34 month-transitions since Oct 2023 and sat frozen for 12 straight bulletins
through FY2025. The VQS trajectory reproduces the ~80%/month no-move base rate
correctly, but it cannot call step TIMING, so it returns the current value at
every horizon -- and the 6m/12m cells rendered that as a hard date. A reader
(u/Funny-Avocato, r/USCIS thread 1v6w1hx, 2026-07-29) read the 12-month cell as
"the model expects no movement for a year" and asked why, given the same page
forecasts +2m of Final Action movement for Oct 2026. That reading is the natural
one and the cell does not support it: six of the last eight Octobers moved that
series (+2m Oct 2024, +12m Oct 2025), so a flat line spanning the Oct 2026 FY
reset contradicts the series' own base rate.

The fix is presentational -- the model is unchanged; the cell stops claiming
precision it does not have. See Notion 3ac62b8d409f81e79703eec823090a92.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import re
import unittest
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta

from webapp.views.bulletin.dashboard import _build_unified_prediction_rows

_DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "webapp"
    / "templates"
    / "webapp"
    / "dashboard.html"
)


def _vcd(label: str, dates: list[date], cutoffs: list[date]) -> dict:
    return {
        "visa_class_label": label,
        "visa_class": label,
        "dates": dates,
        "cutoff_dates": cutoffs,
        "last_bulletin_date": dates[-1] if dates else None,
    }


def _row(pred: dict, current_cutoff: date) -> dict:
    """Build the single unified row for a series whose latest actual cutoff is
    ``current_cutoff`` and whose VQS prediction is ``pred``."""
    today = date.today()
    dates = [today - relativedelta(months=n) for n in (2, 1, 0)]
    vcd = _vcd("1st", dates, [current_cutoff] * 3)
    rows = _build_unified_prediction_rows([vcd], {"1st": pred}, None)
    assert len(rows) == 1
    return rows[0]


class TestFlatHorizonCells(unittest.TestCase):
    """A horizon forecast equal to the current cutoff is flagged, not shown bare."""

    def test_frozen_series_marks_both_horizons_flat(self):
        """The EB-1 India Dates-for-Filing shape: nothing moves for 12 months."""
        frozen = date(2023, 12, 1)
        row = _row(
            {
                "next_cutoff": frozen,
                "cutoff_6m": frozen,
                "cutoff_12m": frozen,
                "confidence": "low",
            },
            current_cutoff=frozen,
        )
        self.assertTrue(row["cutoff_6m_flat"])
        self.assertTrue(row["cutoff_12m_flat"])
        # The held date is still carried, so the template can show what it holds at.
        self.assertEqual(row["cutoff_6m"], frozen)
        self.assertEqual(row["cutoff_12m"], frozen)

    def test_advancing_series_is_not_flat(self):
        current = date(2022, 4, 15)
        row = _row(
            {
                "next_cutoff": date(2022, 5, 1),
                "cutoff_6m": date(2022, 10, 1),
                "cutoff_12m": date(2023, 4, 15),
                "confidence": "medium",
            },
            current_cutoff=current,
        )
        self.assertFalse(row["cutoff_6m_flat"])
        self.assertFalse(row["cutoff_12m_flat"])

    def test_retrogression_is_a_real_forecast_not_flat(self):
        """A cell BEHIND the current cutoff is a prediction; it keeps its date."""
        current = date(2023, 4, 1)
        row = _row(
            {
                "next_cutoff": date(2022, 12, 15),
                "cutoff_6m": date(2022, 10, 15),
                "cutoff_12m": date(2022, 10, 15),
                "confidence": "low",
            },
            current_cutoff=current,
        )
        self.assertFalse(row["cutoff_6m_flat"])
        self.assertFalse(row["cutoff_12m_flat"])

    def test_partial_flat_only_marks_the_flat_horizon(self):
        """6m moves, 12m gives it all back to exactly today's cutoff."""
        current = date(2023, 12, 1)
        row = _row(
            {
                "next_cutoff": date(2024, 1, 1),
                "cutoff_6m": date(2024, 3, 1),
                "cutoff_12m": current,
                "confidence": "low",
            },
            current_cutoff=current,
        )
        self.assertFalse(row["cutoff_6m_flat"])
        self.assertTrue(row["cutoff_12m_flat"])

    def test_missing_horizon_forecast_is_not_flat(self):
        """No forecast at all renders as an em dash, which is not a flat claim."""
        current = date(2023, 12, 1)
        row = _row(
            {
                "next_cutoff": current,
                "cutoff_6m": None,
                "cutoff_12m": None,
                "confidence": "low",
            },
            current_cutoff=current,
        )
        self.assertFalse(row["cutoff_6m_flat"])
        self.assertFalse(row["cutoff_12m_flat"])

    def test_current_series_has_no_cutoff_to_compare(self):
        """A Current series carries no cutoff date; nothing can be flat against it."""
        today = date.today()
        dates = [today - relativedelta(months=n) for n in (2, 1, 0)]
        vcd = _vcd("1st", dates, [None, None, None])
        rows = _build_unified_prediction_rows(
            [vcd],
            {"1st": {"next_cutoff": None, "cutoff_6m": None, "cutoff_12m": None}},
            None,
        )
        self.assertFalse(rows[0]["cutoff_6m_flat"])
        self.assertFalse(rows[0]["cutoff_12m_flat"])


class TestFlatHorizonTemplateWiring(unittest.TestCase):
    """The flags must actually gate the rendered cells, or the row work is inert.

    Guards the template source (the repo's convention for dashboard.html — see
    tests/test_dashboard_integration.py), since a full DB render harness does not
    exist here. The live rendering is verified on staging before promotion.
    """

    def setUp(self):
        self.src = _DASHBOARD_TEMPLATE.read_text()

    def test_each_horizon_cell_checks_flat_before_falling_back_to_the_date(self):
        for flag, value in (
            ("row.cutoff_6m_flat", "row.cutoff_6m"),
            ("row.cutoff_12m_flat", "row.cutoff_12m"),
        ):
            with self.subTest(flag=flag):
                flat_at = self.src.find("{% if " + flag + " %}")
                self.assertNotEqual(
                    flat_at, -1, f"{flag} is never branched on in the template"
                )
                # The date branch must be the ELIF, i.e. only reached when not flat.
                elif_at = self.src.find("{% elif " + value + " %}", flat_at)
                self.assertNotEqual(
                    elif_at, -1, f"{value} must render only as the non-flat branch"
                )
                # ...and it must be the very next tag, so nothing slips between them.
                between = self.src[flat_at:elif_at]
                self.assertNotIn(
                    "{% if ", between[len("{% if " + flag + " %}"):],
                    f"an unexpected branch sits between {flag} and its date fallback",
                )

    def test_flat_cell_still_shows_the_held_date(self):
        """"No step predicted" alone would hide information the reader wants."""
        for flag, value in (
            ("row.cutoff_6m_flat", "row.cutoff_6m"),
            ("row.cutoff_12m_flat", "row.cutoff_12m"),
        ):
            with self.subTest(flag=flag):
                flat_at = self.src.find("{% if " + flag + " %}")
                elif_at = self.src.find("{% elif " + value + " %}", flat_at)
                branch = self.src[flat_at:elif_at]
                self.assertIn("No step predicted", branch)
                self.assertRegex(branch, re.escape("{{ " + value + "|date:"))

    def test_horizon_tooltips_explain_the_flat_label(self):
        """A reader hovering the column header should find out what it means."""
        for header in ("6-Month", "12-Month"):
            with self.subTest(header=header):
                at = self.src.find(header)
                self.assertNotEqual(at, -1)
                popover = self.src[at:at + 900]
                self.assertIn("No step predicted", popover)


if __name__ == "__main__":
    unittest.main()
