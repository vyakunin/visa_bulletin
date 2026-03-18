"""Tests for VQS regime detection module.

Pure unit tests - no DB, no Django. Tests regime classification,
shift detection, parameter recommendations, and FY-phase-aware detection.
"""

from lib.business.vqs.regime import (
    FYPhase,
    Regime,
    RegimeState,
    classify_regime,
    classify_regime_fy_aware,
    detect_regime_shift,
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
        moves = [50, -40, 60, -50, 45, -35]
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
