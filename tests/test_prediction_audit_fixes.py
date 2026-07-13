"""Regression tests for the 2026-07 prediction-code audit — safe fixes.

Each test is named for the failure mode it prevents (not the feature). These
cover the non-value-changing fixes shipped from the audit; the value-changing
(Path-2) and tuning-metric findings are tracked as Notion tickets, not here.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.vqs.accuracy_metrics import MultiHorizonRow, compute_composite_metric
from lib.business.vqs.metric_config import MetricConfig
from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.vqs import PredictedBulletin, PredictedCutoff


class TestCompositeNoWeightSentinel:
    """A4-F13: composite_mae must NOT report 0.0 ("perfect") when no evaluated
    horizon carries a configured weight — that reads as the tuning optimum and
    would be picked as best. It must surface as the worst (inf) instead."""

    def _row(self, horizon: int, error_days: int) -> MultiHorizonRow:
        return MultiHorizonRow(
            knowledge_date=date(2025, 1, 1),
            bulletin_date=date(2025, 1 + horizon if horizon < 12 else 12, 1),
            visa_class="2nd",
            country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value,
            horizon=horizon,
            predicted_cutoff=date(2020, 1, 1),
            actual_cutoff=date(2020, 2, 1),
            error_days=error_days,
            current_cutoff=date(2020, 1, 1),
        )

    def test_no_matching_horizon_weight_is_inf_not_zero(self):
        # horizon 2 is absent from horizon_weights → total weight 0.
        cfg = MetricConfig(horizon_weights={1: 1.0, 3: 1.0, 6: 1.0, 12: 1.0})
        rows = [self._row(2, 50), self._row(2, 70)]
        result = compute_composite_metric(rows, config=cfg)
        assert result["composite_mae"] == float("inf")

    def test_matching_horizon_weight_is_finite(self):
        cfg = MetricConfig(horizon_weights={1: 1.0})
        rows = [self._row(1, 40), self._row(1, 60)]
        result = compute_composite_metric(rows, config=cfg)
        assert result["composite_mae"] < float("inf")
        assert result["composite_mae"] > 0


class TestStoredPredictionSelection(TestCase):
    """A5-F7 / A5-F11: reads over stored PredictedCutoff rows must be
    deterministic and complete."""

    def setUp(self):
        Bulletin.objects.create(publication_date=date(2026, 6, 1))
        self.target = date(2026, 7, 1)
        # Two horizons target the SAME month: a longer-horizon prediction made
        # earlier, and the 1-month prediction made latest.
        self.pb_6m = PredictedBulletin.objects.create(
            target_bulletin_month=self.target, prediction_date=date(2026, 1, 15)
        )
        self.pb_1m = PredictedBulletin.objects.create(
            target_bulletin_month=self.target, prediction_date=date(2026, 6, 15)
        )
        PredictedCutoff.objects.create(
            bulletin=self.pb_6m, visa_class="2nd", country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value, predicted_date=date(2020, 1, 1),
            model_name="gbm_gated", movement_probability=0.9, expert_predictions={},
        )
        PredictedCutoff.objects.create(
            bulletin=self.pb_1m, visa_class="2nd", country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value, predicted_date=date(2020, 5, 1),
            model_name="regime_switched", movement_probability=0.15, expert_predictions={},
        )

    def test_bulk_load_picks_latest_prediction_date_deterministically(self):
        # A5-F7: with two horizons for one month, the 1m line (latest
        # prediction_date) must win, every time — not an arbitrary DB order.
        from lib.business.vqs.prediction_loader import load_stored_predictions_bulk

        out = load_stored_predictions_bulk(
            "2nd", Country.INDIA.value, ActionType.FINAL_ACTION.value
        )
        assert out[self.target] == date(2020, 5, 1)  # the 1m prediction, not the 6m

    def test_single_series_lookup_carries_movement_probability(self):
        # A5-F11: get_prediction_for_series must not drop movement_probability
        # (it did, while the bulk path kept it).
        from lib.business.vqs.prediction_loader import get_prediction_for_series

        result = get_prediction_for_series(
            self.target, "2nd", Country.INDIA.value, ActionType.FINAL_ACTION.value
        )
        assert result.source == "stored"
        assert result.movement_probability == 0.15  # from the latest stored row
