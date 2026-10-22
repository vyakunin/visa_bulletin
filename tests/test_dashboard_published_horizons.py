"""The dashboard's 6m/12m cells read the published per-horizon forecasts.

The roll-forward of the next-bulletin model repeats "no move" month after month,
so on India and China EB-1/2/3 it showed "No step predicted" for a year on series
that move every year (D15, 2026-10-22). The per-horizon dispatch behind the
monthly prediction pages now fills those cells; series it does not cover keep the
roll-forward value.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from lib.business.vqs.prediction_loader import (
    MODEL_GBM_GATED,
    MODEL_OPPENHEIM_PACE,
    MODEL_PERSISTENCE,
    HorizonForecast,
)
from models.enums.action_type import ActionType
from models.enums.country import Country
from scripts.publish_predictions import _filing_horizon_model
from webapp.views.bulletin import dashboard
from webapp.views.bulletin.dashboard import _apply_published_horizons

EB2 = "EB-2: Professionals with Advanced Degrees"
EB4 = "EB-4: Special Immigrants"
LATEST = date(2026, 10, 1)
ROLLED = date(2015, 1, 15)
_TEMPLATE = Path(__file__).resolve().parent.parent / "webapp" / "templates" / "webapp" / "dashboard.html"


def _forecast(predicted: date) -> HorizonForecast:
    return HorizonForecast(
        predicted_date=predicted,
        confidence_low=date(predicted.year - 1, predicted.month, 1),
        confidence_high=date(predicted.year + 1, predicted.month, 1),
        model_name=MODEL_GBM_GATED,
    )


def _apply(published_by_action: dict, action_type: str) -> dict:
    preds = {
        EB2: {"cutoff_6m": ROLLED, "cutoff_12m": ROLLED},
        EB4: {"cutoff_6m": ROLLED, "cutoff_12m": ROLLED},
    }

    def fake_load(country, action, latest, horizon):
        return published_by_action.get((action, horizon), {})

    with mock.patch.object(dashboard, "load_published_horizon_forecasts", side_effect=fake_load):
        _apply_published_horizons(preds, 3, action_type, LATEST)
    return preds


class TestPublishedHorizonCells(unittest.TestCase):
    def test_published_forecast_replaces_the_roll_forward_with_its_range(self):
        fad = ActionType.FINAL_ACTION.value
        preds = _apply(
            {(fad, 6): {"2nd": _forecast(date(2013, 12, 13))},
             (fad, 12): {"2nd": _forecast(date(2014, 7, 11))}},
            fad,
        )
        self.assertEqual(preds[EB2]["cutoff_6m"], date(2013, 12, 13))
        self.assertEqual(preds[EB2]["cutoff_12m"], date(2014, 7, 11))
        self.assertEqual(preds[EB2]["cutoff_12m_low"], date(2013, 7, 1))
        self.assertEqual(preds[EB2]["cutoff_12m_high"], date(2015, 7, 1))

    def test_series_without_a_published_horizon_keeps_the_roll_forward(self):
        fad = ActionType.FINAL_ACTION.value
        preds = _apply({(fad, 6): {"2nd": _forecast(date(2013, 12, 13))}}, fad)
        self.assertEqual(preds[EB4]["cutoff_6m"], ROLLED)
        self.assertEqual(preds[EB2]["cutoff_12m"], ROLLED)
        self.assertNotIn("cutoff_12m_low", preds[EB2])

    def test_filing_cell_is_raised_to_its_final_action_counterpart(self):
        filing, fad = ActionType.FILING.value, ActionType.FINAL_ACTION.value
        preds = _apply(
            {(filing, 6): {"2nd": _forecast(date(2014, 1, 1))},
             (fad, 6): {"2nd": _forecast(date(2014, 3, 1))}},
            filing,
        )
        self.assertEqual(preds[EB2]["cutoff_6m"], date(2014, 3, 1))

    def test_filing_cell_ahead_of_final_action_is_left_alone(self):
        filing, fad = ActionType.FILING.value, ActionType.FINAL_ACTION.value
        preds = _apply(
            {(filing, 6): {"2nd": _forecast(date(2015, 6, 1))},
             (fad, 6): {"2nd": _forecast(date(2014, 3, 1))}},
            filing,
        )
        self.assertEqual(preds[EB2]["cutoff_6m"], date(2015, 6, 1))


class TestFilingHorizonDispatch(unittest.TestCase):
    """Dates for Filing at 6m/12m follows its own backtest, not the Final Action table."""

    def test_backtested_series_get_their_filing_model_by_horizon_bucket(self):
        india = Country.INDIA.value
        self.assertEqual(_filing_horizon_model(india, "1st", 6), MODEL_GBM_GATED)
        self.assertEqual(_filing_horizon_model(india, "2nd", 9), MODEL_PERSISTENCE)
        self.assertEqual(_filing_horizon_model(india, "2nd", 12), MODEL_OPPENHEIM_PACE)
        self.assertEqual(_filing_horizon_model(india, "2nd", 18), MODEL_OPPENHEIM_PACE)

    def test_short_horizons_and_unbacktested_series_fall_through(self):
        self.assertIsNone(_filing_horizon_model(Country.INDIA.value, "1st", 3))
        self.assertIsNone(_filing_horizon_model(Country.ALL.value, "2nd", 6))
        self.assertIsNone(_filing_horizon_model(Country.INDIA.value, "4th", 12))


class TestHorizonRangeInTemplate(unittest.TestCase):
    def test_a_horizon_cell_with_a_range_renders_the_range(self):
        src = _TEMPLATE.read_text()
        for h in ("6m", "12m"):
            with self.subTest(horizon=h):
                self.assertIn(f"row.cutoff_{h}_low|date:", src)
                self.assertIn(f"row.cutoff_{h}_high|date:", src)


if __name__ == "__main__":
    unittest.main()
