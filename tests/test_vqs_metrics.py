"""Tests for VQS MetricConfig improvements.

Pure unit tests - no DB, no Django.
"""

from datetime import date

from lib.business.vqs.metric_config import MetricConfig, PeriodDiscount


class TestAsymmetricLoss:
    def test_symmetric_when_penalty_is_one(self):
        cfg = MetricConfig(optimistic_penalty=1.0)
        assert cfg.expert_loss(30) == cfg.expert_loss(-30)

    def test_optimistic_penalized_more(self):
        cfg = MetricConfig(optimistic_penalty=1.5)
        optimistic_loss = cfg.expert_loss(30)
        pessimistic_loss = cfg.expert_loss(-30)
        assert optimistic_loss > pessimistic_loss
        assert optimistic_loss / pessimistic_loss == 1.5

    def test_zero_error_is_zero_loss(self):
        cfg = MetricConfig(optimistic_penalty=2.0)
        assert cfg.expert_loss(0) == 0.0

    def test_huber_loss_also_asymmetric(self):
        cfg = MetricConfig(use_huber_loss=True, optimistic_penalty=1.5)
        optimistic = cfg.expert_loss(100)
        pessimistic = cfg.expert_loss(-100)
        assert optimistic > pessimistic


class TestWarmupDecay:
    def test_no_decay_when_one(self):
        cfg = MetricConfig(warmup_decay=1.0)
        assert cfg.warmup_weight(0) == 1.0
        assert cfg.warmup_weight(12) == 1.0
        assert cfg.warmup_weight(120) == 1.0

    def test_recent_weighted_more(self):
        cfg = MetricConfig(warmup_decay=0.95)
        assert cfg.warmup_weight(0) > cfg.warmup_weight(6)
        assert cfg.warmup_weight(6) > cfg.warmup_weight(12)

    def test_decay_formula(self):
        cfg = MetricConfig(warmup_decay=0.9)
        assert abs(cfg.warmup_weight(1) - 0.9) < 1e-9
        assert abs(cfg.warmup_weight(2) - 0.81) < 1e-9

    def test_distant_past_gets_small_weight(self):
        cfg = MetricConfig(warmup_decay=0.95)
        assert cfg.warmup_weight(60) < 0.1


class TestPeriodDiscount:
    def test_discount_in_range(self):
        cfg = MetricConfig(
            period_discounts=[
                PeriodDiscount(date(2023, 1, 1), date(2023, 12, 31), 0.2)
            ]
        )
        assert cfg.period_weight(date(2023, 6, 15)) == 0.2

    def test_no_discount_outside_range(self):
        cfg = MetricConfig(
            period_discounts=[
                PeriodDiscount(date(2023, 1, 1), date(2023, 12, 31), 0.2)
            ]
        )
        assert cfg.period_weight(date(2024, 6, 15)) == 1.0

    def test_overlapping_discounts_use_minimum(self):
        cfg = MetricConfig(
            period_discounts=[
                PeriodDiscount(date(2023, 1, 1), date(2023, 12, 31), 0.5),
                PeriodDiscount(date(2023, 6, 1), date(2024, 6, 30), 0.2),
            ]
        )
        assert cfg.period_weight(date(2023, 8, 1)) == 0.2


class TestVolatilityWeight:
    def test_low_volatility_near_one(self):
        cfg = MetricConfig()
        w = cfg.volatility_weight([10.0, 12.0, 11.0, 10.0, 13.0, 11.0])
        assert w > 0.9

    def test_high_volatility_reduces_weight(self):
        cfg = MetricConfig()
        w = cfg.volatility_weight([100.0, -80.0, 120.0, -90.0, 110.0])
        assert w < 0.5

    def test_insufficient_data_returns_one(self):
        cfg = MetricConfig()
        assert cfg.volatility_weight([10.0, 20.0]) == 1.0


class TestSeriesWeight:
    def test_known_series_gets_configured_weight(self):
        cfg = MetricConfig()
        assert cfg.series_weight("2nd", 3) == 1.5  # India EB-2

    def test_unknown_series_gets_default(self):
        cfg = MetricConfig()
        assert cfg.series_weight("5th", 1) == 1.0

    def test_custom_series_weights(self):
        cfg = MetricConfig(series_weights={("2nd", 3): 2.0})
        assert cfg.series_weight("2nd", 3) == 2.0
        assert cfg.series_weight("1st", 2) == 1.0


class TestRegimeWeight:
    def test_fy_boundary_month(self):
        cfg = MetricConfig(fy_boundary_weight=0.5, steady_state_weight=1.0)
        assert cfg.regime_weight(10) == 0.5  # October
        assert cfg.regime_weight(9) == 0.5   # September
        assert cfg.regime_weight(8) == 0.5   # August

    def test_steady_state_month(self):
        cfg = MetricConfig(fy_boundary_weight=0.5, steady_state_weight=1.5)
        assert cfg.regime_weight(3) == 1.5
        assert cfg.regime_weight(6) == 1.5

    def test_default_weights_are_one(self):
        cfg = MetricConfig()
        assert cfg.regime_weight(10) == 1.0
        assert cfg.regime_weight(3) == 1.0


class TestMagnitudeWeight:
    def test_zero_weight_always_one(self):
        cfg = MetricConfig(move_magnitude_weight=0.0)
        assert cfg.magnitude_weight(0) == 1.0
        assert cfg.magnitude_weight(500) == 1.0

    def test_large_move_weighted_more(self):
        cfg = MetricConfig(move_magnitude_weight=1.0)
        w_large = cfg.magnitude_weight(300)
        w_small = cfg.magnitude_weight(30)
        assert w_large > w_small

    def test_floor_prevents_zero_weight(self):
        cfg = MetricConfig(move_magnitude_weight=1.0)
        w = cfg.magnitude_weight(0)
        assert w == 1.0

    def test_proportional_at_full_weight(self):
        cfg = MetricConfig(move_magnitude_weight=1.0)
        w_90 = cfg.magnitude_weight(90)
        w_30 = cfg.magnitude_weight(30)
        assert w_90 / w_30 == 3.0


class TestCompositeWeight:
    def test_combines_all_dimensions(self):
        cfg = MetricConfig(
            period_discounts=[],
            series_weights={("2nd", 3): 2.0},
            fy_boundary_weight=0.5,
            steady_state_weight=1.0,
            move_magnitude_weight=0.0,
        )
        w = cfg.composite_weight(
            d=date(2024, 6, 15),
            visa_class="2nd", country=3,
            target_month=10,
            actual_move_days=100,
        )
        assert w == 2.0 * 0.5  # series * fy_boundary

    def test_none_dimensions_ignored(self):
        cfg = MetricConfig(period_discounts=[])
        w = cfg.composite_weight(d=date(2024, 1, 1))
        assert w == 1.0
