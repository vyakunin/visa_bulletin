"""Tests that forced-persistence predictions don't carry a misleading regime label."""

# solver imports Django models at module level, and one test queries the DB
# (visa_cutoff_date) — create + migrate the test DB before importing solver.
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from unittest.mock import patch

from lib.business.vqs.regime import Regime, RegimeState
from lib.business.vqs.solver import _select_expert_for_regime


class TestSelectExpertForRegime:
    """_select_expert_for_regime should use demand_signal for any advancing regime."""

    def test_advancing_high_avg_uses_demand_signal(self):
        state = RegimeState(Regime.ADVANCING, 0.8, 30.0, 5.0)
        assert _select_expert_for_regime(state, "2nd", 213, 4) == "demand_signal"

    def test_advancing_low_avg_uses_demand_signal(self):
        """Previously fell back to persistence when avg < 15; now should use demand_signal."""
        state = RegimeState(Regime.ADVANCING, 0.5, 8.0, 3.0)
        assert _select_expert_for_regime(state, "2nd", 213, 4) == "demand_signal"

    def test_stalled_uses_persistence(self):
        state = RegimeState(Regime.STALLED, 0.9, 1.0, 0.5)
        assert _select_expert_for_regime(state, "2nd", 213, 4) == "persistence"

    def test_recovering_high_avg_uses_demand_signal(self):
        state = RegimeState(Regime.RECOVERING, 0.6, 15.0, 4.0)
        assert _select_expert_for_regime(state, "2nd", 213, 4) == "demand_signal"


class TestNonEligibleSeriesNoRegime:
    """predict_regime_switched should not embed regime in metadata for non-eligible series."""

    @patch("lib.business.vqs.solver.get_cutoff_at_date")
    @patch("lib.business.vqs.solver.get_last_N_moves")
    @patch("lib.business.vqs.solver.classify_regime")
    def test_non_eligible_series_has_no_regime_in_metadata(
        self, mock_classify, mock_moves, mock_cutoff
    ):
        from datetime import date

        from lib.business.vqs.solver import predict_regime_switched
        from models.enums.country import Country

        mock_moves.return_value = [20, 25, 18, 22, 15, 19]
        mock_classify.return_value = RegimeState(Regime.ADVANCING, 0.8, 20.0, 3.0)
        mock_cutoff.return_value = date(2024, 1, 1)

        # Mexico EB-2 is NOT in PHYSICS_ELIGIBLE_SERIES
        outcome = predict_regime_switched(
            knowledge_date=date(2026, 3, 15),
            visa_class="2nd",
            country=Country.MEXICO.value,
            action_type="filing",
            facts=[],
        )

        assert "regime" not in outcome.metadata
        assert outcome.metadata["selected_expert"] == "persistence"

    @patch("lib.business.vqs.solver.get_cutoff_at_date")
    @patch("lib.business.vqs.solver.get_last_N_moves")
    @patch("lib.business.vqs.solver.classify_regime")
    def test_eligible_series_has_regime_in_metadata(
        self, mock_classify, mock_moves, mock_cutoff
    ):
        from datetime import date

        from lib.business.vqs.solver import predict_regime_switched
        from models.enums.country import Country

        mock_moves.return_value = [20, 25, 18, 22, 15, 19]
        mock_classify.return_value = RegimeState(Regime.ADVANCING, 0.8, 20.0, 3.0)
        mock_cutoff.return_value = date(2024, 1, 1)

        # India EB-2 IS in PHYSICS_ELIGIBLE_SERIES
        with patch("lib.business.vqs.solver.compute_confidence", return_value="medium"):
            with patch("lib.business.vqs.solver.get_historical_advancement_rate", return_value=15.0):
                with patch("lib.business.vqs.expert_pool.ALL_EXPERTS", {
                    "demand_signal": lambda *a, **kw: date(2024, 2, 15),
                    "persistence": lambda *a, **kw: date(2024, 1, 1),
                    "momentum_3m": lambda *a, **kw: date(2024, 2, 10),
                }):
                    with patch("lib.business.vqs.expert_pool.ALL_EXPERT_TRAJECTORIES", {}):
                        outcome = predict_regime_switched(
                            knowledge_date=date(2026, 3, 15),
                            visa_class="2nd",
                            country=Country.INDIA.value,
                            action_type="filing",
                            facts=[],
                        )

        assert outcome.metadata.get("regime") == "advancing"
        assert outcome.metadata["selected_expert"] == "demand_signal"
