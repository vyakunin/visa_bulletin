"""Regression tests for the 2026-07 prediction-code audit — safe fixes.

Each test is named for the failure mode it prevents (not the feature). These
cover the non-value-changing fixes shipped from the audit; the value-changing
(Path-2) and tuning-metric findings are tracked as Notion tickets, not here.
"""

from datetime import date
from types import SimpleNamespace

import pytest

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


class TestCurrentUnavailableGuard:
    """THEME 1: a series that has gone Current/Unavailable must NOT be treated as
    if its last real (years-old) cutoff still applies.

    Root cause: get_cutoff_at_date reads a cache filtered to non-null cutoffs, so
    during a Current/Unavailable spell it returns the STALE last-real cutoff, not
    None. Every consumer that reasoned `cutoff is None ⇒ Current` was silently
    dead. These tests inject that exact cache state (stale non-null cutoff + a
    newer Current/Unavailable full-entry) and assert the consumers now react.
    """

    KEY = ("2nd", Country.INDIA.value, "final_action")
    EB1_KEY = ("1st", Country.INDIA.value, "final_action")

    def _entry(self, pub: date, cutoff=None, is_current=False, is_unavailable=False):
        return SimpleNamespace(
            bulletin=SimpleNamespace(publication_date=pub),
            cutoff_date=cutoff,
            is_current=is_current,
            is_unavailable=is_unavailable,
        )

    def _inject(self, key, *, state: str):
        """Populate both caches for a series whose last REAL cutoff is 2020-01-01
        (published 2022) and which then went `state` (current/unavailable) in 2023."""
        from lib.business.vqs import data_cache

        real = self._entry(date(2022, 1, 1), cutoff=date(2020, 1, 1))
        spell = self._entry(
            date(2023, 1, 1),
            is_current=(state == "current"),
            is_unavailable=(state == "unavailable"),
        )
        # Non-null-cutoff cache (what get_cutoff_at_date reads) sees ONLY the real row.
        data_cache._CUTOFF_CACHE[key] = [real]
        data_cache._PUB_DATE_CACHE[key] = [real.bulletin.publication_date]
        # Full-entry cache (what is_current/is_unavailable read) sees both.
        data_cache._CURRENT_CACHE[key] = [real, spell]
        data_cache._CURRENT_PUB_DATES[key] = [
            real.bulletin.publication_date, spell.bulletin.publication_date
        ]

    @pytest.fixture(autouse=True)
    def _clear(self):
        from lib.business.vqs import data_cache

        for c in (data_cache._CUTOFF_CACHE, data_cache._PUB_DATE_CACHE,
                  data_cache._CURRENT_CACHE, data_cache._CURRENT_PUB_DATES):
            c.clear()
        yield
        for c in (data_cache._CUTOFF_CACHE, data_cache._PUB_DATE_CACHE,
                  data_cache._CURRENT_CACHE, data_cache._CURRENT_PUB_DATES):
            c.clear()

    def test_root_cause_get_cutoff_stale_while_is_current_true(self):
        # The trap itself: during a Current spell get_cutoff_at_date returns the
        # stale 2020 date (NOT None), while is_current_at_date correctly says True.
        from lib.business.vqs import data_cache

        self._inject(self.KEY, state="current")
        as_of = date(2024, 6, 1)
        assert data_cache.get_cutoff_at_date(*self.KEY, as_of=as_of) == date(2020, 1, 1)
        assert data_cache.is_current_at_date(*self.KEY, as_of=as_of) is True

    def test_backlog_depth_zero_for_current_not_phantom_years(self):
        # A5-F9: was (2024-06-01 − 2020-01-01) ≈ 1600 phantom days; must be 0.
        from lib.business.vqs.fy_utilization import compute_backlog_depth

        self._inject(self.KEY, state="current")
        assert compute_backlog_depth(*self.KEY, knowledge_date=date(2024, 6, 1)) == 0

    def test_backlog_depth_none_for_unavailable(self):
        # A5-F9: Unavailable → depth not derivable from a stale cutoff → None.
        from lib.business.vqs.fy_utilization import compute_backlog_depth

        self._inject(self.KEY, state="unavailable")
        assert compute_backlog_depth(*self.KEY, knowledge_date=date(2024, 6, 1)) is None

    def test_eb1_surplus_indicator_fires_during_current_spell(self):
        # A3-F4: EB-1 Current must set the spillover indicator to 1.0; it was
        # stuck at 0.0 because get_cutoff_at_date returned a stale non-None date.
        from lib.business.vqs.gbm_expert import _get_eb1_surplus_indicator

        self._inject(self.EB1_KEY, state="current")
        assert _get_eb1_surplus_indicator(
            Country.INDIA.value, "final_action", date(2024, 6, 1)
        ) == 1.0

    def test_cascade_bonus_fires_for_current_higher_preference(self):
        # A5-F2: EB-1 Current → surplus falls down to EB-2; bonus must be > 0.
        from lib.business.vqs.supply.cascade import CascadeModel

        self._inject(self.EB1_KEY, state="current")
        bonus = CascadeModel().estimate_cascade_bonus(
            "2nd", Country.INDIA.value, date(2024, 6, 1), date(2024, 6, 1)
        )
        assert bonus > 0


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
