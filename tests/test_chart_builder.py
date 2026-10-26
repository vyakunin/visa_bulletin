"""Tests for chart builder logic"""

import json
import unittest
from datetime import date

from lib.business.bulletin.chart_builder import (
    build_chart_with_projection,
    build_multi_class_chart_with_projections,
)


class TestChartBuilder(unittest.TestCase):
    """Test chart HTML generation"""

    def test_builds_html_with_valid_data(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)]
        submission = date(2021, 1, 1)
        projection = None

        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, "F1", "all"
        )

        self.assertIsInstance(html, str)
        self.assertIn("plotly", html.lower())
        self.assertIn("priority-date-chart", html)

    def test_includes_projection_when_available(self):
        # The legacy build_chart_with_projection accepts projection for backward
        # compatibility but VQS lines are only added via vqs_predictions in the
        # multi-class builder. Chart should still render without crashing.
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)]
        submission = date(2021, 1, 1)
        projection = {
            "status": "projected",
            "estimated_date": date(2025, 1, 1),
            "months_to_wait": 12,
        }

        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, "F1", "china"
        )

        self.assertIsInstance(html, str)
        self.assertIn("plotly", html.lower())
        self.assertIn("F1", html)

    def test_handles_none_cutoff_dates(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        cutoffs = [date(2020, 1, 1), None, date(2020, 3, 1)]
        submission = date(2021, 1, 1)
        projection = None

        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, "EB2", "india"
        )

        self.assertIsInstance(html, str)
        self.assertIn("plotly", html.lower())

    def test_includes_visa_class_in_title(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 1, 1)

        html = build_chart_with_projection(
            dates, cutoffs, submission, None, "EB3", "mexico"
        )

        self.assertIn("EB3", html)
        self.assertIn(
            "mexico", html.lower()
        )  # Country label in title (case-insensitive)

    def test_includes_submission_date_line(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 6, 15)

        html = build_chart_with_projection(
            dates, cutoffs, submission, None, "F2A", "all"
        )

        self.assertIn("Your Priority Date", html)

    def test_projection_without_estimated_date(self):
        dates = [date(2024, 1, 1), date(2024, 2, 1)]
        cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        submission = date(2021, 1, 1)
        projection = {
            "status": "current",
            "estimated_date": None,
        }

        html = build_chart_with_projection(
            dates, cutoffs, submission, projection, "F1", "all"
        )

        # Should not crash, projection line not added
        self.assertIsInstance(html, str)
        self.assertIn("plotly", html.lower())


class TestMultiClassChartBuilder(unittest.TestCase):
    """Test multi-class chart generation (main dashboard feature)"""

    def test_builds_chart_with_multiple_visa_classes(self):
        """Chart should include all visa classes with their data"""
        visa_class_data = [
            {
                "visa_class": "F1",
                "visa_class_label": "F1: Unmarried Sons/Daughters",
                "dates": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
                "cutoff_dates": [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)],
                "projection": None,
                "bulletin_urls": ["url1", "url2", "url3"],
            },
            {
                "visa_class": "F2A",
                "visa_class_label": "F2A: Spouses and Children",
                "dates": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
                "cutoff_dates": [date(2021, 1, 1), date(2021, 2, 1), date(2021, 3, 1)],
                "projection": None,
                "bulletin_urls": ["url1", "url2", "url3"],
            },
        ]
        submission_date = date(2022, 1, 1)

        result = build_multi_class_chart_with_projections(
            visa_class_data, submission_date, "all", "Family-Sponsored"
        )

        # Returns dict with chart_json and trace_info
        self.assertIsInstance(result, dict)
        self.assertIn("chart_json", result)
        self.assertIn("trace_info", result)
        self.assertIn("F1", result["chart_json"])
        self.assertIn("F2A", result["chart_json"])

        # Check trace_info structure
        self.assertEqual(len(result["trace_info"]), 2)
        self.assertEqual(result["trace_info"][0]["visa_class"], "F1")
        self.assertEqual(result["trace_info"][1]["visa_class"], "F2A")

    def test_handles_empty_visa_class_data(self):
        """Chart should handle empty data gracefully"""
        result = build_multi_class_chart_with_projections(
            [], date(2022, 1, 1), "all", "Family-Sponsored"
        )

        self.assertIsInstance(result, dict)
        self.assertIn("chart_json", result)
        self.assertEqual(result["trace_info"], [])

    def test_includes_projections_when_available(self):
        """Chart should show projection lines for each visa class via vqs_predictions"""
        visa_class_data = [
            {
                "visa_class": "EB2",
                "visa_class_label": "EB-2: Advanced Degree",
                "dates": [date(2024, 1, 1), date(2024, 2, 1)],
                "cutoff_dates": [date(2018, 1, 1), date(2018, 2, 1)],
                "bulletin_urls": [],
            }
        ]
        vqs_predictions = {
            "EB-2: Advanced Degree": {
                "trajectory": [
                    (date(2024, 3, 1), date(2018, 4, 1)),
                    (date(2024, 6, 1), date(2019, 1, 1)),
                    (date(2026, 1, 1), date(2020, 1, 1)),
                ],
                "maturity_month": date(2026, 1, 1),
            }
        }

        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2020, 1, 1), "india", "Employment-Based",
            vqs_predictions=vqs_predictions,
        )

        # Check label appears in chart (not visa_class code)
        self.assertIn("EB-2: Advanced Degree", result["chart_json"])
        # Should include projection data (2026 from trajectory/maturity)
        self.assertIn("2026", result["chart_json"])
        # Should have 2+ trace indices (historical + VQS line)
        self.assertGreaterEqual(len(result["trace_info"][0]["trace_indices"]), 2)

    def test_handles_mixed_projections(self):
        """Some visa classes have projections via vqs_predictions, others don't"""
        visa_class_data = [
            {
                "visa_class": "EB2",
                "dates": [date(2024, 1, 1)],
                "cutoff_dates": [date(2018, 1, 1)],
            },
            {
                "visa_class": "EB3",
                "dates": [date(2024, 1, 1)],
                "cutoff_dates": [date(2019, 1, 1)],
            },
        ]
        # Only EB2 has a VQS prediction; EB3 does not
        vqs_predictions = {
            "EB2": {
                "trajectory": [
                    (date(2024, 2, 1), date(2018, 6, 1)),
                    (date(2025, 1, 1), date(2020, 1, 1)),
                ],
                "maturity_month": date(2025, 1, 1),
            }
        }

        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2020, 1, 1), "china", "Employment-Based",
            vqs_predictions=vqs_predictions,
        )

        self.assertIsInstance(result, dict)
        self.assertIn("EB2", result["chart_json"])
        self.assertIn("EB3", result["chart_json"])
        # EB2 has VQS prediction (historical + projection + maturity marker), EB3 doesn't (1 trace)
        self.assertGreaterEqual(len(result["trace_info"][0]["trace_indices"]), 2)
        self.assertEqual(len(result["trace_info"][1]["trace_indices"]), 1)

    def test_handles_none_cutoff_dates_in_multi_class(self):
        """None values in cutoff_dates should not break chart"""
        visa_class_data = [
            {
                "visa_class": "F1",
                "dates": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
                "cutoff_dates": [date(2020, 1, 1), None, date(2020, 3, 1)],
                "projection": None,
            }
        ]

        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2021, 1, 1), "all", "Family-Sponsored"
        )

        self.assertIsInstance(result, dict)
        self.assertIn("chart_json", result)

    def test_submission_date_line_extends_to_projections(self):
        """Submission date line should extend to furthest VQS projection"""
        visa_class_data = [
            {
                "visa_class": "EB2",
                "dates": [date(2024, 1, 1)],
                "cutoff_dates": [date(2018, 1, 1)],
            }
        ]
        vqs_predictions = {
            "EB2": {
                "trajectory": [
                    (date(2024, 2, 1), date(2018, 4, 1)),
                    (date(2030, 1, 1), date(2020, 1, 1)),  # Far future maturity
                ],
                "maturity_month": date(2030, 1, 1),
            }
        }

        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2020, 1, 1), "india", "Employment-Based",
            vqs_predictions=vqs_predictions,
        )

        self.assertIn("Your Priority Date", result["chart_json"])
        # Should reference 2030 in chart data (maturity month extends priority line)
        self.assertIn("2030", result["chart_json"])

    def test_trace_info_includes_colors(self):
        """Each trace_info entry should include color for checkbox styling"""
        visa_class_data = [
            {
                "visa_class": "F1",
                "visa_class_label": "F1: Test",
                "dates": [date(2024, 1, 1)],
                "cutoff_dates": [date(2020, 1, 1)],
                "projection": None,
            }
        ]

        result = build_multi_class_chart_with_projections(
            visa_class_data, date(2021, 1, 1), "all", "Family-Sponsored"
        )

        self.assertIn("color", result["trace_info"][0])
        self.assertTrue(result["trace_info"][0]["color"].startswith("#"))


class TestHorizonForecastMarkers(unittest.TestCase):
    """The chart plots the table's 6- and 12-month cells, so the two show one forecast."""

    LABEL = "EB-1: Priority Workers"

    def _chart(self, pred, cutoff_states=None):
        data = {
            "visa_class": "EB1",
            "visa_class_label": self.LABEL,
            "dates": [date(2026, 9, 1), date(2026, 10, 1)],
            "cutoff_dates": [date(2024, 7, 1), date(2024, 7, 1)],
            "bulletin_urls": [],
        }
        if cutoff_states is not None:
            data["cutoff_states"] = cutoff_states
        result = build_multi_class_chart_with_projections(
            [data], date(2026, 6, 1), "india", "Employment-Based",
            vqs_predictions={self.LABEL: pred},
        )
        traces = json.loads(result["chart_json"])["data"]
        return [t for t in traces if t.get("name", "").endswith("(6/12-Month Forecast)")], result

    def _pred(self, **overrides):
        # A flat roll-forward line, with per-horizon cells that move: the India EB-1
        # Filing shape that made the chart contradict the table.
        pred = {
            "trajectory": [(date(2026, 11, 1), date(2024, 7, 1)), (date(2027, 10, 1), date(2024, 7, 1))],
            "maturity_month": None,
            "cutoff_6m": date(2024, 10, 25),
            "cutoff_6m_month": date(2027, 4, 1),
            "cutoff_6m_low": date(2024, 8, 1),
            "cutoff_6m_high": date(2025, 2, 1),
            "cutoff_12m": date(2026, 1, 14),
            "cutoff_12m_month": date(2027, 10, 1),
            "cutoff_12m_low": date(2025, 6, 1),
            "cutoff_12m_high": date(2026, 9, 1),
        }
        pred.update(overrides)
        return pred

    def test_markers_sit_on_the_table_cells_not_the_flat_line(self):
        markers, _ = self._chart(self._pred())
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["x"], ["2027-04-01", "2027-10-01"])
        self.assertEqual(markers[0]["y"], ["2024-10-25", "2026-01-14"])

    def _ranges(self, result):
        traces = json.loads(result["chart_json"])["data"]
        return [t for t in traces if t.get("name", "").endswith("(6/12-Month Range)")]

    def test_published_range_is_drawn_at_each_horizon_month(self):
        _, result = self._chart(self._pred())
        (rng,) = self._ranges(result)
        self.assertEqual(rng["x"], ["2027-04-01", "2027-04-01", None, "2027-10-01", "2027-10-01", None])
        self.assertEqual(rng["y"], ["2024-08-01", "2025-02-01", None, "2025-06-01", "2026-09-01", None])

    def test_cell_raised_above_its_range_stretches_the_bar_to_the_cell(self):
        # A Filing cell raised to its Final Action floor can sit above its own range.
        _, result = self._chart(self._pred(cutoff_6m=date(2025, 5, 1)))
        (rng,) = self._ranges(result)
        self.assertEqual(rng["y"][:2], ["2024-08-01", "2025-05-01"])

    def test_cell_holding_todays_cutoff_draws_no_range_like_the_table(self):
        # The table renders such a cell as "No step predicted" with no range.
        _, result = self._chart(self._pred(cutoff_6m=date(2024, 7, 1)))
        (rng,) = self._ranges(result)
        self.assertEqual(rng["x"], ["2027-10-01", "2027-10-01", None])

    def test_cell_moving_off_todays_cutoff_keeps_its_range(self):
        # Neighbour of the flat case: one day past today's cutoff is a forecast step.
        _, result = self._chart(self._pred(cutoff_6m=date(2024, 7, 2)))
        (rng,) = self._ranges(result)
        self.assertEqual(rng["x"][:2], ["2027-04-01", "2027-04-01"])

    def test_roll_forward_cells_without_a_range_draw_bare_markers(self):
        markers, result = self._chart(
            self._pred(cutoff_6m_low=None, cutoff_6m_high=None, cutoff_12m_low=None, cutoff_12m_high=None)
        )
        self.assertEqual(len(markers[0]["x"]), 2)
        self.assertEqual(self._ranges(result), [])

    def test_dotted_line_is_kept_beside_the_markers(self):
        _, result = self._chart(self._pred())
        names = [t["name"] for t in json.loads(result["chart_json"])["data"]]
        self.assertIn(f"{self.LABEL} (Queue Model)", names)

    def test_marker_trace_toggles_with_its_class(self):
        _, result = self._chart(self._pred())
        traces = json.loads(result["chart_json"])["data"]
        for suffix in ("(6/12-Month Forecast)", "(6/12-Month Range)"):
            idx = next(i for i, t in enumerate(traces) if t["name"].endswith(suffix))
            self.assertIn(idx, result["trace_info"][0]["trace_indices"])

    def test_marker_carries_no_customdata_a_click_would_open(self):
        markers, _ = self._chart(self._pred())
        self.assertNotIn("customdata", markers[0])

    def test_class_at_current_gets_no_markers(self):
        markers, _ = self._chart(self._pred(), cutoff_states=["date", "current"])
        self.assertEqual(markers, [])

    def test_no_horizon_cells_no_markers(self):
        markers, _ = self._chart(self._pred(cutoff_6m=None, cutoff_12m=None))
        self.assertEqual(markers, [])


if __name__ == "__main__":
    unittest.main()
