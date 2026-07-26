"""Tests for VQS regime detection module.

Pure unit tests - no DB, no Django. Tests regime classification,
shift detection, parameter recommendations, and FY-phase-aware detection.
"""

from datetime import date, timedelta

from lib.business.vqs.regime import (
    DEMAND_GATE_MIN_MOVE,
    DIRECTION_GATE_MIN,
    FYPhase,
    Regime,
    RegimeState,
    apply_demand_gate,
    classify_regime,
    classify_regime_fy_aware,
    detect_regime_shift,
    direction_gate,
    fy_aware_cap_back_days,
    fy_aware_cap_forward_days,
    fy_aware_persistence_weight,
    fy_aware_stickiness_days,
    get_fy_phase,
    regime_learning_rate,
    regime_persistence_weight,
    regime_stickiness_days,
    shrink_prediction,
)


class TestClassifyRegime:
    def test_empty_moves_returns_stalled(self):
        state = classify_regime([])
        assert state.regime == Regime.STALLED
        assert state.confidence == 0.0

    def test_consistent_forward_movement(self):
        moves = [20, 25, 18, 22, 30, 15]
        state = classify_regime(moves)
        assert state.regime == Regime.ADVANCING
        assert state.confidence > 0.0
        assert state.avg_move > 0

    def test_consistent_backward_movement(self):
        moves = [-20, -15, -25, -10, -30, -18]
        state = classify_regime(moves)
        assert state.regime == Regime.RETROGRESSING
        assert state.confidence > 0.0
        assert state.avg_move < 0

    def test_near_zero_movement_is_stalled(self):
        moves = [2, -1, 3, -2, 1, 0]
        state = classify_regime(moves)
        assert state.regime == Regime.STALLED

    def test_recovery_after_retrogression(self):
        # Most recent first: recent positive, older negative
        moves = [20, 25, 15, -30, -25, -20]
        state = classify_regime(moves)
        assert state.regime == Regime.RECOVERING

    def test_volatile_high_variance(self):
        # VOLATILE needs coefficient-of-variation (vol/avg_abs) > VOLATILE_CV (2.0):
        # one large magnitude spike among small moves. Pure sign-oscillation has
        # cv≈1.0 and never reaches the VOLATILE branch. Most recent first; the
        # older half is non-negative so the RECOVERING branch is not triggered.
        moves = [200, -5, 0, 5, -3, 2]
        state = classify_regime(moves)
        assert state.regime == Regime.VOLATILE

    def test_lookback_limits_window(self):
        # First 3 are advancing, rest are retrogressing
        moves = [20, 25, 15, -30, -25, -20]
        state = classify_regime(moves, lookback=3)
        assert state.regime == Regime.ADVANCING

    def test_single_move_forward(self):
        state = classify_regime([30])
        assert state.regime == Regime.ADVANCING

    def test_single_move_backward(self):
        state = classify_regime([-30])
        assert state.regime == Regime.RETROGRESSING

    def test_stall_confidence_higher_when_truly_zero(self):
        zero = classify_regime([0, 0, 0, 0])
        small = classify_regime([3, -2, 4, -3])
        assert zero.confidence >= small.confidence


class TestDetectRegimeShift:
    def test_no_shift_when_insufficient_data(self):
        assert detect_regime_shift([10, 20, 15]) is False

    def test_detects_sign_change(self):
        # Recent: positive advancing. Prior: negative retrogressing.
        moves = [20, 25, 15, -20, -15, -25]
        assert detect_regime_shift(moves) is True

    def test_no_shift_when_consistent(self):
        moves = [20, 25, 15, 18, 22, 30]
        assert detect_regime_shift(moves) is False

    def test_detects_magnitude_change(self):
        # Same direction but 3x speed change
        moves = [60, 50, 55, 15, 10, 20]
        assert detect_regime_shift(moves) is True

    def test_no_shift_for_small_magnitude_change(self):
        moves = [20, 22, 18, 15, 17, 16]
        assert detect_regime_shift(moves) is False


class TestRegimeParameterRecommendations:
    def test_advancing_low_vol_gets_moderate_persistence(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        w = regime_persistence_weight(state)
        assert 0.3 < w < 0.5

    def test_advancing_high_vol_gets_higher_persistence(self):
        from lib.business.vqs.regime import RegimeState

        low_vol = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        high_vol = RegimeState(Regime.ADVANCING, 0.8, 20.0, 80.0)
        assert regime_persistence_weight(high_vol) > regime_persistence_weight(low_vol)

    def test_volatile_gets_high_persistence(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.VOLATILE, 0.5, 0.0, 40.0)
        w = regime_persistence_weight(state)
        assert w > 0.9

    def test_persistence_weight_capped_at_95(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.VOLATILE, 1.0, 0.0, 500.0)
        assert regime_persistence_weight(state) <= 0.95

    def test_advancing_gets_zero_stickiness(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        assert regime_stickiness_days(state) == 0

    def test_stalled_gets_high_stickiness(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0)
        assert regime_stickiness_days(state) == 90

    def test_recovering_gets_higher_learning_rate(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.RECOVERING, 0.7, 10.0, 15.0)
        lr = regime_learning_rate(state, base_lr=0.5)
        assert lr > 0.5

    def test_stalled_gets_lower_learning_rate(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0)
        lr = regime_learning_rate(state, base_lr=0.5)
        assert lr < 0.5


class TestShrinkPrediction:
    def test_zero_stays_zero(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        assert shrink_prediction(0, state) == 0

    def test_preserves_sign(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        assert shrink_prediction(50, state) > 0
        assert shrink_prediction(-50, state) < 0

    def test_small_movements_pass_through_mostly(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        result = shrink_prediction(15, state)
        assert result > 10

    def test_large_movements_shrunk_aggressively(self):
        from lib.business.vqs.regime import RegimeState

        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        result = shrink_prediction(200, state)
        assert result < 100

    def test_stalled_shrinks_more_than_advancing(self):
        from lib.business.vqs.regime import RegimeState

        adv = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        stall = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0)
        assert shrink_prediction(50, stall) < shrink_prediction(50, adv)

    def test_volatile_shrinks_most(self):
        adv = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0)
        vol = RegimeState(Regime.VOLATILE, 0.5, 0.0, 40.0)
        assert shrink_prediction(100, vol) < shrink_prediction(100, adv)


class TestFYPhaseDetection:
    def test_october_is_fy_reset(self):
        assert get_fy_phase(10) == FYPhase.FY_RESET

    def test_november_through_march_is_conservative(self):
        for m in (11, 12, 1, 2, 3):
            assert get_fy_phase(m) == FYPhase.CONSERVATIVE

    def test_april_through_june_is_acceleration(self):
        for m in (4, 5, 6):
            assert get_fy_phase(m) == FYPhase.ACCELERATION

    def test_july_through_september_is_end_of_fy(self):
        for m in (7, 8, 9):
            assert get_fy_phase(m) == FYPhase.END_OF_FY

    def test_classify_regime_fy_aware_preserves_base_regime(self):
        moves = [20, 25, 18, 22, 30, 15]
        state = classify_regime_fy_aware(moves, target_month=10)
        assert state.regime == Regime.ADVANCING
        assert state.fy_phase == FYPhase.FY_RESET

    def test_classify_regime_fy_aware_end_of_fy(self):
        moves = [20, 25, 18, 22, 30, 15]
        state = classify_regime_fy_aware(moves, target_month=9)
        assert state.regime == Regime.ADVANCING
        assert state.fy_phase == FYPhase.END_OF_FY


class TestFYAwarePersistenceWeight:
    def test_fy_reset_gets_very_low_persistence(self):
        state = RegimeState(Regime.VOLATILE, 0.8, 0.0, 50.0, FYPhase.FY_RESET)
        w = fy_aware_persistence_weight(state)
        assert w == 0.05

    def test_end_of_fy_gets_low_persistence(self):
        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0, FYPhase.END_OF_FY)
        w = fy_aware_persistence_weight(state)
        assert w == 0.15

    def test_normal_phase_uses_standard_regime_weight(self):
        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0, FYPhase.NORMAL)
        assert fy_aware_persistence_weight(state) == regime_persistence_weight(state)

    def test_conservative_phase_uses_standard_regime_weight(self):
        state = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0, FYPhase.CONSERVATIVE)
        assert fy_aware_persistence_weight(state) == regime_persistence_weight(state)


class TestFYAwareStickiness:
    def test_fy_reset_has_zero_stickiness(self):
        state = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0, FYPhase.FY_RESET)
        assert fy_aware_stickiness_days(state) == 0

    def test_end_of_fy_has_zero_stickiness(self):
        state = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0, FYPhase.END_OF_FY)
        assert fy_aware_stickiness_days(state) == 0

    def test_normal_phase_uses_standard_stickiness(self):
        state = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0, FYPhase.NORMAL)
        assert fy_aware_stickiness_days(state) == regime_stickiness_days(state)


class TestFYAwareCaps:
    def test_fy_reset_forward_cap_is_1500(self):
        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0, FYPhase.FY_RESET)
        assert fy_aware_cap_forward_days(state) == 1500

    def test_end_of_fy_back_cap_is_500(self):
        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0, FYPhase.END_OF_FY)
        assert fy_aware_cap_back_days(state) == 500

    def test_normal_phase_uses_base_cap(self):
        state = RegimeState(Regime.ADVANCING, 0.8, 20.0, 5.0, FYPhase.NORMAL)
        assert fy_aware_cap_forward_days(state, base_cap=45) == 45
        assert fy_aware_cap_back_days(state, base_cap=60) == 60


class TestApplyDemandGate:
    """T3 demand gate (solver.predict_regime_switched). Pure logic — the gate
    turns a persistence fallback into a DAMPENED directional move when the
    demand_signal expert implies one, without ever suppressing a move.
    Locks the shipped behaviour + the §8/T2 lesson (dampen, don't swap raw)."""

    STALLED = RegimeState(Regime.STALLED, 0.8, 1.0, 2.0, FYPhase.NORMAL)
    CUR = date(2015, 6, 1)

    def _persist(self):
        # persistence prediction == current cutoff (no move)
        return self.CUR

    def test_fires_forward_dampens_and_relabels(self):
        # demand implies a big +180d move; gate expresses a SHRUNK forward move.
        demand_pred = self.CUR + timedelta(days=180)
        pred, expert, traj = apply_demand_gate(
            "persistence", self._persist(), self.CUR, demand_pred, self.STALLED
        )
        assert expert == "demand_gate"
        assert traj == "persistence"  # keep persistence trajectory for steps 1+
        move = (pred - self.CUR).days
        assert move > 0                      # correct direction
        assert move < 180                    # dampened (never raw)
        assert pred != self._persist()       # it ADDED a move (not a no-op)

    def test_fires_backward_preserves_direction(self):
        demand_pred = self.CUR - timedelta(days=120)
        pred, expert, traj = apply_demand_gate(
            "persistence", self._persist(), self.CUR, demand_pred, self.STALLED
        )
        assert expert == "demand_gate"
        move = (pred - self.CUR).days
        assert move < 0 and move > -120      # retro direction, dampened

    def test_noop_when_expert_not_persistence(self):
        # selector already picked an active expert (ADVANCING → demand_signal);
        # the gate must not touch it.
        demand_pred = self.CUR + timedelta(days=180)
        active_pred = self.CUR + timedelta(days=90)
        pred, expert, traj = apply_demand_gate(
            "demand_signal", active_pred, self.CUR, demand_pred, self.STALLED
        )
        assert (pred, expert, traj) == (active_pred, "demand_signal", "demand_signal")

    def test_noop_below_gate_threshold(self):
        # demand move under the gate minimum → stays flat persistence.
        demand_pred = self.CUR + timedelta(days=DEMAND_GATE_MIN_MOVE - 1)
        pred, expert, traj = apply_demand_gate(
            "persistence", self._persist(), self.CUR, demand_pred, self.STALLED
        )
        assert (pred, expert, traj) == (self._persist(), "persistence", "persistence")

    def test_noop_when_demand_none(self):
        pred, expert, traj = apply_demand_gate(
            "persistence", self._persist(), self.CUR, None, self.STALLED
        )
        assert (pred, expert, traj) == (self._persist(), "persistence", "persistence")

    def test_noop_when_current_none(self):
        pred, expert, traj = apply_demand_gate(
            "persistence", None, None, self.CUR + timedelta(days=180), self.STALLED
        )
        assert expert == "persistence" and traj == "persistence"

    def test_advancing_regime_dampens_less_than_stalled(self):
        # shrink_prediction is regime-modulated: ADVANCING keeps more of the move.
        advancing = RegimeState(Regime.ADVANCING, 0.9, 40.0, 5.0, FYPhase.NORMAL)
        demand_pred = self.CUR + timedelta(days=180)
        pred_stall, _, _ = apply_demand_gate(
            "persistence", self._persist(), self.CUR, demand_pred, self.STALLED
        )
        pred_adv, _, _ = apply_demand_gate(
            "persistence", self._persist(), self.CUR, demand_pred, advancing
        )
        assert (pred_adv - self.CUR).days > (pred_stall - self.CUR).days


class TestDirectionGate:
    """Two-stage direction-first hybrid (§26). Stage 1 votes on direction,
    stage 2 supplies magnitude; only CONFLICTS are rewritten, so the gate can
    never inject a move stage 2 did not forecast (the §8/§23-T2 guard)."""

    CUR = date(2015, 6, 1)

    def _d(self, days):
        return self.CUR + timedelta(days=days)

    def test_agreement_passes_through_untouched(self):
        # both say advance -> magnitude survives verbatim
        assert direction_gate(self._d(120), self._d(60), self.CUR) == self._d(120)
        # both say retrogress
        assert direction_gate(self._d(-120), self._d(-60), self.CUR) == self._d(-120)

    def test_stage1_below_gate_min_has_no_opinion(self):
        weak = self._d(DIRECTION_GATE_MIN - 1)
        assert direction_gate(self._d(-90), weak, self.CUR) == self._d(-90)

    def test_conflict_hold_drops_to_no_change(self):
        # stage 1 says advance, stage 2 says retrogress -> no-change
        assert direction_gate(self._d(-90), self._d(60), self.CUR) == self.CUR

    def test_conflict_flip_keeps_magnitude_takes_stage1_sign(self):
        assert direction_gate(self._d(-90), self._d(60), self.CUR, policy="flip") == self._d(90)
        assert direction_gate(self._d(90), self._d(-60), self.CUR, policy="flip") == self._d(-90)

    def test_conflict_shrink_halves_but_keeps_stage2_sign(self):
        assert direction_gate(self._d(-90), self._d(60), self.CUR, policy="shrink") == self._d(-45)

    def test_gate_never_injects_a_move_stage2_did_not_make(self):
        # stage 2 predicts no change; stage 1 shouts advance. Gate must stay flat.
        assert direction_gate(self.CUR, self._d(300), self.CUR) == self.CUR
        assert direction_gate(self.CUR, self._d(300), self.CUR, policy="flip") == self.CUR

    def test_none_inputs_pass_the_magnitude_through(self):
        assert direction_gate(None, self._d(60), self.CUR) is None
        assert direction_gate(self._d(90), None, self.CUR) == self._d(90)
        assert direction_gate(self._d(90), self._d(60), None) == self._d(90)

    def test_unknown_policy_raises(self):
        import pytest
        with pytest.raises(ValueError):
            direction_gate(self._d(-90), self._d(60), self.CUR, policy="nonsense")
