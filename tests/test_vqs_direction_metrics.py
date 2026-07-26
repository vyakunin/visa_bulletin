"""Tests for base-rate-proof direction metrics (§26).

Pure unit tests - no DB, no Django.

The point these pin: on visa-bulletin data ~90% of moves are advances, so
``cond_direction_acc`` is largely a restatement of that class mix. The tests
below encode the discriminating case — a skill-free constant classifier that
scores a healthy-looking CondDir while ``bal_direction_acc`` correctly reports
50% (no skill) and ``cond_up_rate`` exposes the CondDir as the base rate.
"""

import pytest

from lib.business.vqs.direction_metrics import MovePair, direction_metrics


def _always_advance(actual_moves, advance_days=60):
    return [MovePair(actual_days=a, predicted_days=advance_days) for a in actual_moves]


class TestConstantClassifierIsUnmasked:
    """The failure mode §26 found: 'high direction accuracy' that is only the base rate."""

    # 3 advances, 1 retrogression -> a lopsided mix like the real data
    LOPSIDED = [60, 90, 120, -75]

    def test_conddir_of_always_advance_equals_the_up_base_rate(self):
        m = direction_metrics(_always_advance(self.LOPSIDED))
        assert m.cond_direction_acc == 75.0
        assert m.cond_up_rate == 75.0  # identical -> the score IS the base rate

    def test_balanced_accuracy_reports_no_skill_for_the_constant_classifier(self):
        m = direction_metrics(_always_advance(self.LOPSIDED))
        assert m.advance_recall == 100.0
        assert m.retro_recall == 0.0
        assert m.bal_direction_acc == 50.0  # constant classifier -> 50%, whatever the mix

    def test_pred_up_share_identifies_it_as_constant(self):
        m = direction_metrics(_always_advance(self.LOPSIDED))
        assert m.pred_up_share == 100.0

    def test_more_lopsided_data_inflates_conddir_but_not_balanced(self):
        # 9 advances, 1 retrogression: CondDir climbs to 90%, skill unchanged at 50%.
        m = direction_metrics(_always_advance([60] * 9 + [-75]))
        assert m.cond_direction_acc == 90.0
        assert m.cond_up_rate == 90.0
        assert m.bal_direction_acc == 50.0


class TestSkillIsRewarded:
    def test_perfect_direction_scores_100_on_both(self):
        pairs = [
            MovePair(actual_days=60, predicted_days=40),
            MovePair(actual_days=90, predicted_days=200),
            MovePair(actual_days=-75, predicted_days=-10),
        ]
        m = direction_metrics(pairs)
        assert m.cond_direction_acc == 100.0
        assert m.bal_direction_acc == 100.0
        assert m.retro_recall == 100.0

    def test_catching_the_retrogression_beats_the_constant_baseline(self):
        # Same actuals as the lopsided case, but the retrogression is called.
        pairs = _always_advance(TestConstantClassifierIsUnmasked.LOPSIDED)[:3]
        pairs.append(MovePair(actual_days=-75, predicted_days=-30))
        m = direction_metrics(pairs)
        assert m.cond_direction_acc == 100.0
        assert m.bal_direction_acc == 100.0


class TestCountingRules:
    def test_moves_at_or_below_threshold_are_not_scored(self):
        m = direction_metrics([
            MovePair(actual_days=30, predicted_days=60),    # exactly at move_min -> excluded
            MovePair(actual_days=-30, predicted_days=-60),  # excluded
            MovePair(actual_days=31, predicted_days=60),    # scored
        ])
        assert m.cond_n == 1
        assert m.retro_n == 0

    def test_move_min_is_configurable(self):
        pairs = [MovePair(actual_days=45, predicted_days=60)]
        assert direction_metrics(pairs, move_min=30).cond_n == 1
        assert direction_metrics(pairs, move_min=90).cond_n == 0

    def test_flat_prediction_is_never_a_correct_direction(self):
        # Persistence predicts no move; it must not be credited on moving months.
        m = direction_metrics([
            MovePair(actual_days=60, predicted_days=0),
            MovePair(actual_days=-60, predicted_days=0),
        ])
        assert m.cond_direction_acc == 0.0
        assert m.bal_direction_acc == 0.0
        assert m.pred_up_share == 0.0

    def test_pred_up_share_is_over_all_scored_months_not_just_movers(self):
        # 1 mover + 3 quiet months, all predicted as advances.
        m = direction_metrics([
            MovePair(actual_days=60, predicted_days=60),
            MovePair(actual_days=0, predicted_days=60),
            MovePair(actual_days=5, predicted_days=60),
            MovePair(actual_days=-2, predicted_days=60),
        ])
        assert m.cond_n == 1
        assert m.pred_up_share == 100.0

    @pytest.mark.parametrize("actuals,expect_balanced", [
        ([60, 90], None),      # no retrogressions -> balanced undefined
        ([-60, -90], None),    # no advances -> balanced undefined
        ([60, -90], 50.0),     # both present
    ])
    def test_balanced_needs_both_classes(self, actuals, expect_balanced):
        m = direction_metrics(_always_advance(actuals))
        assert m.bal_direction_acc == expect_balanced

    def test_empty_input_is_all_none(self):
        m = direction_metrics([])
        assert m.cond_n == 0
        assert m.cond_direction_acc is None
        assert m.bal_direction_acc is None
        assert m.pred_up_share is None
