"""Tests for published-interval coverage scoring (§28).

Pure unit tests - no DB, no Django.

The point these pin: a single headline coverage number cannot tell a
correctly-centred 80% interval from one that over-covers a tail it rarely
needs. The tests below encode the discriminating case measured on the real
stored predictions — a one-sided interval whose floor sits on the point
estimate scores ABOVE its nominal coverage while missing almost exclusively on
the high side.
"""

from datetime import date, timedelta

from lib.business.vqs.interval_coverage import (
    GradedInterval,
    coverage_metrics,
    flat_call_metrics,
)

BASE = date(2026, 1, 1)


def _row(pred_off: int, actual_off: int, lo_off: int, hi_off: int, prev_off: int | None = None):
    """Build a row from day offsets against a shared base date."""
    return GradedInterval(
        predicted=BASE + timedelta(days=pred_off),
        actual=BASE + timedelta(days=actual_off),
        ci_low=BASE + timedelta(days=lo_off),
        ci_high=BASE + timedelta(days=hi_off),
        prev_actual=None if prev_off is None else BASE + timedelta(days=prev_off),
    )


class TestTailsAreReportedSeparately:
    """The failure this metric exists to expose: coverage passes, centring does not."""

    # Floor sits ON the point estimate; ceiling 100d above. Nine actuals land
    # inside, one overshoots the ceiling: coverage 90% (above the nominal 80%)
    # while the low tail holds 0% of the 10% it should.
    ONE_SIDED = [_row(0, 50, 0, 100) for _ in range(9)] + [_row(0, 150, 0, 100)]

    def test_headline_coverage_can_exceed_nominal_while_a_tail_is_empty(self):
        m = coverage_metrics(self.ONE_SIDED)
        assert m.coverage_pct == 90.0  # comfortably above the claimed 80%
        assert m.miss_low_pct == 0.0  # ...but this tail should hold ~10%
        assert m.miss_high_pct == 10.0
        assert m.nominal_tail_pct == 10.0

    def test_tail_imbalance_names_the_direction_of_the_miscentring(self):
        m = coverage_metrics(self.ONE_SIDED)
        assert m.tail_imbalance_pts == 10.0  # positive -> point estimate sits too low

    def test_degenerate_floor_is_counted_as_interval_shape(self):
        m = coverage_metrics(self.ONE_SIDED)
        assert m.degenerate_floor_pct == 100.0
        assert m.mean_below_days == 0.0
        assert m.mean_above_days == 100.0

    def test_a_centred_interval_reports_no_imbalance(self):
        rows = [_row(0, 0, -50, 50) for _ in range(8)] + [_row(0, -80, -50, 50), _row(0, 80, -50, 50)]
        m = coverage_metrics(rows)
        assert m.coverage_pct == 80.0
        assert m.miss_low_pct == m.miss_high_pct == 10.0
        assert m.tail_imbalance_pts == 0.0
        assert m.degenerate_floor_pct == 0.0


class TestNoChangeExpressibility:
    """Whether the interval can represent 'the series does not move'."""

    def test_no_change_outside_interval_when_model_calls_an_advance(self):
        # Predicted +30d from the anchor, floor only 14d below the point: the
        # no-change outcome (the anchor itself) sits below the floor. This is
        # the Aug-2026 EB-3 India shape.
        m = coverage_metrics([_row(30, 0, 16, 153, prev_off=0)])
        assert m.nochange_excluded_pct == 100.0
        assert m.miss_low_pct == 100.0

    def test_no_change_inside_interval_when_model_calls_flat(self):
        # Flat call: the point IS the anchor, so no-change is inside even with
        # a degenerate floor.
        m = coverage_metrics([_row(0, 0, 0, 120, prev_off=0)])
        assert m.nochange_excluded_pct == 0.0
        assert m.coverage_pct == 100.0

    def test_rows_without_an_anchor_are_excluded_from_the_no_change_stat(self):
        m = coverage_metrics([_row(0, 10, -30, 30)])
        assert m.n == 1
        assert m.n_with_anchor == 0
        assert m.nochange_excluded_pct is None


class TestSignedErrorConvention:
    def test_positive_signed_error_means_the_actual_advanced_past_the_call(self):
        m = coverage_metrics([_row(0, 40, -30, 90), _row(0, 20, -30, 90)])
        assert m.mean_signed_error_days == 30.0
        assert m.median_signed_error_days == 30.0


class TestFlatCallScoring:
    def test_a_permanent_flat_call_is_split_into_right_and_wrong(self):
        # Model always calls the anchor. Half the months genuinely stay flat,
        # half advance 60d.
        rows = [_row(0, 0, 0, 100, prev_off=0) for _ in range(5)]
        rows += [_row(0, 60, 0, 100, prev_off=0) for _ in range(5)]
        m = flat_call_metrics(rows)
        assert m.called_flat_pct == 100.0
        assert m.actual_flat_pct == 50.0
        assert m.called_flat_actual_advanced_pct == 50.0
        assert m.called_flat_actual_retrogressed_pct == 0.0
        assert m.mean_predicted_move_days == 0.0
        assert m.mean_actual_move_days == 30.0

    def test_small_moves_inside_the_tolerance_count_as_flat(self):
        m = flat_call_metrics([_row(3, 5, -30, 30, prev_off=0)])
        assert m.called_flat_pct == 100.0
        assert m.actual_flat_pct == 100.0
        assert m.called_flat_actual_advanced_pct == 0.0

    def test_retrogression_under_a_flat_call_is_reported_separately(self):
        m = flat_call_metrics([_row(0, -60, -90, 90, prev_off=0)])
        assert m.called_flat_actual_retrogressed_pct == 100.0
        assert m.called_flat_actual_advanced_pct == 0.0

    def test_unanchored_rows_yield_an_empty_result(self):
        m = flat_call_metrics([_row(0, 10, -30, 30)])
        assert m.n == 0
        assert m.called_flat_pct is None


class TestEmptyInput:
    def test_coverage_metrics_on_no_rows(self):
        m = coverage_metrics([])
        assert m.n == 0
        assert m.coverage_pct is None
        assert m.tail_imbalance_pts is None
        assert m.nominal_tail_pct == 10.0
