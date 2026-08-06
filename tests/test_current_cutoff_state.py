"""
A "Current" cutoff is a STATE, not a date — it must never be substituted with the
bulletin's own publication date.

The aggregator used to collapse an ``is_current`` cell to ``record.bulletin.publication_date``,
which reads back as a real cutoff everywhere downstream. Three visible consequences:

1. The dashboard's "Current Cutoff" column printed "Aug 01, 2026" for F2A in the
   August 2026 bulletin, matching neither the Final Action actual (22 Jul 2026) nor
   the Filing actual (Current).
2. The chart plotted the Current months as a cutoff line marching in lockstep with
   the bulletin month — five consecutive fake "advances" for F2A Filing, Apr–Aug 2026 —
   and the per-country distinction vanished, since every column renders the same
   substituted date.
3. ``webapp/views/bulletin/priority_date_landing.py`` documents the opposite contract
   ("the aggregated series collapses both Current and Unavailable to None") and reads
   the series directly, so a long-standing Current spell reported "became Current this
   month" every month.

The contract these tests pin: ``cutoff_dates`` carries ``None`` for both Current and
Unavailable, and the parallel ``cutoff_states`` list says which of the two it is.

See Notion 3b062b8d409f81ff8486d29d8118e642.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from lib.business.bulletin.cutoff_data_aggregator import (
    VisaClassData,
    _append_records_to_data,
)
from webapp.views.bulletin.dashboard import _build_unified_prediction_rows

_DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "webapp"
    / "templates"
    / "webapp"
    / "dashboard.html"
)

_BULLETINS = [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]


def _record(publication_date: date, cutoff_date=None, *, current=False, unavailable=False):
    return SimpleNamespace(
        bulletin=SimpleNamespace(publication_date=publication_date),
        cutoff_date=cutoff_date,
        is_current=current,
        is_unavailable=unavailable,
    )


def _aggregate(records) -> VisaClassData:
    data = VisaClassData(
        visa_class="2A",
        visa_class_label="F2A: Spouses/Children of Permanent Residents",
        dates=[],
        cutoff_dates=[],
        bulletin_urls=[],
    )
    _append_records_to_data(data, records, "family_sponsored")
    return data


def _vcd(states: list[str], cutoffs: list[date | None]) -> dict:
    return {
        "visa_class_label": "F2A",
        "visa_class": "2A",
        "dates": list(_BULLETINS),
        "cutoff_dates": cutoffs,
        "cutoff_states": states,
        "last_bulletin_date": _BULLETINS[-1],
    }


class TestAggregatorCurrentState(unittest.TestCase):
    def test_current_cell_is_not_substituted_with_the_bulletin_month(self):
        """The exact defect: a Current cell must not come back as publication_date."""
        data = _aggregate([_record(_BULLETINS[-1], current=True)])

        self.assertEqual(data.cutoff_dates, [None])
        self.assertNotIn(_BULLETINS[-1], data.cutoff_dates)
        self.assertEqual(data.cutoff_states, ["current"])

    def test_unavailable_is_distinguishable_from_current(self):
        data = _aggregate([_record(_BULLETINS[-1], unavailable=True)])

        self.assertEqual(data.cutoff_dates, [None])
        self.assertEqual(data.cutoff_states, ["unavailable"])

    def test_ordinary_cutoff_passes_through_unchanged(self):
        data = _aggregate([_record(_BULLETINS[-1], cutoff_date=date(2026, 7, 22))])

        self.assertEqual(data.cutoff_dates, [date(2026, 7, 22)])
        self.assertEqual(data.cutoff_states, ["date"])

    def test_a_current_spell_does_not_read_as_a_marching_cutoff(self):
        """Three consecutive Current bulletins produced three fake monthly advances."""
        data = _aggregate([_record(b, current=True) for b in _BULLETINS])

        self.assertEqual(data.cutoff_dates, [None, None, None])
        self.assertEqual(data.cutoff_states, ["current"] * 3)

    def test_states_stay_aligned_with_dates_after_sorting(self):
        """_finalize_aggregated_data reorders by bulletin date; states must follow."""
        from lib.business.bulletin.cutoff_data_aggregator import (
            _finalize_aggregated_data,
        )

        data = _aggregate(
            [
                _record(_BULLETINS[2], current=True),
                _record(_BULLETINS[0], cutoff_date=date(2025, 1, 1)),
                _record(_BULLETINS[1], unavailable=True),
            ]
        )
        finalized = _finalize_aggregated_data({"F2A": data}, date(2024, 1, 1))[0]

        self.assertEqual(finalized["dates"], _BULLETINS)
        self.assertEqual(finalized["cutoff_states"], ["date", "unavailable", "current"])
        self.assertEqual(finalized["cutoff_dates"], [date(2025, 1, 1), None, None])


class TestUnifiedRowCurrentState(unittest.TestCase):
    def test_latest_current_renders_as_current_not_a_date(self):
        rows = _build_unified_prediction_rows(
            [_vcd(["date", "current", "current"], [date(2025, 1, 1), None, None])],
            {},
            date(2026, 1, 1),
        )

        self.assertIsNone(rows[0]["current_cutoff"])
        self.assertTrue(rows[0]["cutoff_is_current"])
        self.assertFalse(rows[0]["cutoff_is_unavailable"])

    def test_a_current_class_is_current_for_every_priority_date(self):
        """No backlog means no wait — including for a priority date filed yesterday."""
        rows = _build_unified_prediction_rows(
            [_vcd(["current"] * 3, [None] * 3)],
            {},
            date(2026, 8, 5),
        )

        self.assertTrue(rows[0]["already_current"])

    def test_latest_unavailable_does_not_fall_back_to_a_stale_date(self):
        rows = _build_unified_prediction_rows(
            [_vcd(["date", "date", "unavailable"], [date(2025, 1, 1), date(2025, 2, 1), None])],
            {},
            date(2026, 1, 1),
        )

        self.assertIsNone(rows[0]["current_cutoff"])
        self.assertTrue(rows[0]["cutoff_is_unavailable"])
        self.assertFalse(rows[0]["cutoff_is_current"])

    def test_ordinary_series_keeps_its_latest_cutoff(self):
        rows = _build_unified_prediction_rows(
            [_vcd(["date"] * 3, [date(2025, 1, 1), date(2025, 2, 1), date(2026, 7, 22)])],
            {},
            date(2026, 1, 1),
        )

        self.assertEqual(rows[0]["current_cutoff"], date(2026, 7, 22))
        self.assertFalse(rows[0]["cutoff_is_current"])

    def test_missing_states_key_does_not_break_the_row(self):
        """Callers that pre-date cutoff_states (fixtures, cached payloads) still render."""
        rows = _build_unified_prediction_rows(
            [
                {
                    "visa_class_label": "F2A",
                    "visa_class": "2A",
                    "dates": list(_BULLETINS),
                    "cutoff_dates": [date(2025, 1, 1)] * 3,
                    "last_bulletin_date": _BULLETINS[-1],
                }
            ],
            {},
            date(2026, 1, 1),
        )

        self.assertEqual(rows[0]["current_cutoff"], date(2025, 1, 1))
        self.assertFalse(rows[0]["cutoff_is_current"])


class TestDashboardTemplateCutoffCell(unittest.TestCase):
    """The template's fallback branch labelled EVERY dateless row "Current" — so an
    Unavailable class, and a class with no data at all, both claimed no backlog."""

    def setUp(self):
        self.template = _DASHBOARD_TEMPLATE.read_text()
        start = self.template.index('<th scope="col">Current Cutoff</th>')
        body = self.template.index("{% for row in unified_rows %}", start)
        self.cell = self.template[body : body + 900]

    def test_current_label_is_gated_on_the_current_state(self):
        self.assertIn("row.cutoff_is_current", self.cell)

    def test_unavailable_is_labelled_unavailable(self):
        self.assertIn("row.cutoff_is_unavailable", self.cell)
        self.assertIn("Unavailable", self.cell)


if __name__ == "__main__":
    unittest.main()
