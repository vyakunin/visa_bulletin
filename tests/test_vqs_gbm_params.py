"""Tests for the GBM candidate-hyperparameter override (`gbm_expert.apply_params`).

The override is what lets a backtest score a parameter set the module does not
currently carry — `evaluate_model --params-json` and
`backtest_publish_dispatch --params-json` both route through it, so a set that
fails to apply silently scores the committed constants and reports a null result
as a real one.
"""

import json

import pytest

from lib.business.vqs import gbm_expert
from lib.business.vqs.gbm_expert import apply_params, load_params_file

# The constants in force before the §25 graduation (d12a94f). The attribution
# re-run scores this set, so a drift in how it applies invalidates that number.
PRE_S25_PARAMS = {
    "n_estimators": 258,
    "max_depth": 8,
    "learning_rate": 0.103,
    "min_child_samples": 15,
    "reg_alpha": 2.34,
    "reg_lambda": 4.11,
    "movement_threshold": 50,
    "gate_threshold": 0.68,
}

_CONSTANTS = (
    "_GBM_N_ESTIMATORS",
    "_GBM_MAX_DEPTH",
    "_GBM_NUM_LEAVES",
    "_GBM_LEARNING_RATE",
    "_GBM_MIN_CHILD_SAMPLES",
    "_GBM_REG_ALPHA",
    "_GBM_REG_LAMBDA",
    "_GBM_DEFAULT_MOVEMENT_THRESHOLD",
    "_GBM_DEFAULT_GATE_THRESHOLD",
)


@pytest.fixture(autouse=True)
def restore_constants():
    """Put the committed constants back — these are module globals other tests read."""
    saved = {name: getattr(gbm_expert, name) for name in _CONSTANTS}
    yield
    for name, value in saved.items():
        setattr(gbm_expert, name, value)


class TestApplyParams:
    def test_empty_params_leave_every_constant_untouched(self):
        before = {name: getattr(gbm_expert, name) for name in _CONSTANTS}
        effective = apply_params({})
        assert {name: getattr(gbm_expert, name) for name in _CONSTANTS} == before
        assert effective["n_estimators"] == before["_GBM_N_ESTIMATORS"]
        assert effective["gate_threshold"] == before["_GBM_DEFAULT_GATE_THRESHOLD"]

    def test_pre_s25_set_round_trips_into_the_module(self):
        effective = apply_params(PRE_S25_PARAMS)

        assert gbm_expert._GBM_N_ESTIMATORS == 258
        assert gbm_expert._GBM_LEARNING_RATE == 0.103
        assert gbm_expert._GBM_MIN_CHILD_SAMPLES == 15
        assert gbm_expert._GBM_REG_ALPHA == 2.34
        assert gbm_expert._GBM_REG_LAMBDA == 4.11
        assert gbm_expert._GBM_DEFAULT_MOVEMENT_THRESHOLD == 50
        assert gbm_expert._GBM_DEFAULT_GATE_THRESHOLD == 0.68
        # The returned set is what callers pass on to expert_gbm_gated, whose own
        # defaults are bound at definition and so never see the mutation.
        assert effective["movement_threshold"] == 50
        assert effective["gate_threshold"] == 0.68

    def test_tuner_prefixed_keys_are_accepted(self):
        apply_params({"gbm_n_estimators": 111, "gbm_learning_rate": 0.5})
        assert gbm_expert._GBM_N_ESTIMATORS == 111
        assert gbm_expert._GBM_LEARNING_RATE == 0.5

    def test_absent_key_keeps_the_committed_value(self):
        committed_depth = gbm_expert._GBM_MAX_DEPTH
        apply_params({"n_estimators": 7})
        assert gbm_expert._GBM_N_ESTIMATORS == 7
        assert gbm_expert._GBM_MAX_DEPTH == committed_depth

    def test_num_leaves_is_derived_from_max_depth(self):
        effective = apply_params({"max_depth": 5})
        assert gbm_expert._GBM_NUM_LEAVES == 31
        assert effective["num_leaves"] == 31

    def test_num_leaves_has_a_floor(self):
        apply_params({"max_depth": 2})
        assert gbm_expert._GBM_NUM_LEAVES == 15

    def test_caches_are_cleared_so_stale_models_are_not_reused(self):
        gbm_expert._model_cache[("stale",)] = object()
        gbm_expert._classifier_cache[("stale",)] = object()
        gbm_expert._quantile_cache[("stale",)] = object()

        apply_params({"n_estimators": 42})

        assert gbm_expert._model_cache == {}
        assert gbm_expert._classifier_cache == {}
        assert gbm_expert._quantile_cache == {}

    def test_values_are_coerced_to_their_declared_types(self):
        apply_params({"n_estimators": "64", "learning_rate": "0.25", "movement_threshold": "30"})
        assert gbm_expert._GBM_N_ESTIMATORS == 64
        assert isinstance(gbm_expert._GBM_N_ESTIMATORS, int)
        assert gbm_expert._GBM_LEARNING_RATE == 0.25
        assert isinstance(gbm_expert._GBM_LEARNING_RATE, float)
        assert gbm_expert._GBM_DEFAULT_MOVEMENT_THRESHOLD == 30


class TestLoadParamsFile:
    def test_bare_mapping_is_returned_as_is(self, tmp_path):
        path = tmp_path / "params.json"
        path.write_text(json.dumps(PRE_S25_PARAMS))
        assert load_params_file(str(path)) == PRE_S25_PARAMS

    def test_tuner_best_params_block_is_unwrapped(self, tmp_path):
        path = tmp_path / "tuned.json"
        path.write_text(json.dumps({"objective": 262.9, "best_params": {"n_estimators": 68}}))
        assert load_params_file(str(path)) == {"n_estimators": 68}
