"""Regression tests for the 2026-07 prediction-code audit — safe fixes.

Each test is named for the failure mode it prevents (not the feature). These
cover the non-value-changing fixes shipped from the audit; the value-changing
(Path-2) and tuning-metric findings are tracked as Notion tickets, not here.
"""

from datetime import date, timedelta
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


class TestGbmTrainingLabels:
    """THEME 2: GBM training labels + cache keys.

    A3-F1: the 1m/horizon labels spanned one transition too many (anchored
    `current` on bulletin B-1 but reached the label to B+1 → 2 transitions for a
    1-step prediction, so the model learned ~2x the movement).
    A3-F2: the label bulletin was not walk-forward-filtered (could be the very
    target being predicted).
    A3-F3: the model caches omitted action_type, so filing predictions were
    served from the final_action-trained model within one publish process.
    """

    SERIES = (Country.INDIA.value, "2nd")  # one _GBM_ELIGIBLE series

    def _monthly_bulletins(self, n: int):
        # n consecutive monthly bulletins from 2023-01-01.
        out, y, m = [], 2023, 1
        for _ in range(n):
            out.append(SimpleNamespace(publication_date=date(y, m, 1)))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return out

    def _install(self, monkeypatch, bulletins, *, step_days=30):
        """Wire data_cache so each successive bulletin's cutoff advances step_days.
        get_cutoff_at_date returns the cutoff of the latest bulletin <= as_of."""
        import models.raw_facts as raw_facts_mod
        from lib.business.vqs import data_cache, gbm_expert

        base = date(2019, 1, 1)
        cutoff_of = {
            b.publication_date: base + timedelta(days=step_days * i)
            for i, b in enumerate(bulletins)
        }

        def fake_cutoff(vc, country, action_type, as_of):
            latest = None
            for b in bulletins:
                if b.publication_date <= as_of:
                    latest = b.publication_date
            return cutoff_of.get(latest)

        monkeypatch.setattr(data_cache, "get_all_bulletins", lambda: bulletins)
        monkeypatch.setattr(data_cache, "get_cutoff_at_date", fake_cutoff)
        monkeypatch.setattr(gbm_expert, "_GBM_ELIGIBLE", [self.SERIES])
        monkeypatch.setattr(gbm_expert, "_MIN_TRAINING_SAMPLES", 1)
        monkeypatch.setattr(
            gbm_expert, "_build_features_for_series",
            lambda vc, c, at, kd, facts, mask_demand_drop=True: [0.0] * len(gbm_expert.FEATURE_NAMES),
        )
        monkeypatch.setattr(
            raw_facts_mod, "RawFactsLedger",
            SimpleNamespace(objects=SimpleNamespace(filter=lambda **k: [])),
        )

    def test_1m_label_is_single_transition(self, monkeypatch):
        from lib.business.vqs import gbm_expert

        buls = self._monthly_bulletins(8)
        self._install(monkeypatch, buls, step_days=30)
        x, y = gbm_expert._build_training_data(date(2024, 6, 1), "filing")
        # Each label = one bulletin's advance (30d), NOT two (60d).
        assert x, "expected training rows"
        assert all(val == 30.0 for val in y), y

    def test_horizon_label_is_exactly_h_transitions(self, monkeypatch):
        from lib.business.vqs import gbm_expert

        buls = self._monthly_bulletins(20)
        self._install(monkeypatch, buls, step_days=30)
        # 6-month horizon over a 30d/step ramp → interior labels are 180d (6
        # transitions). The OLD off-by-one anchored the target a month too far and
        # produced 210d (7 transitions); the max label must now be 180, never 210.
        # (Edge bulletins whose exact target month is past the last bulletin snap
        # the ±35d window to a nearer bulletin → labels < 180, which is fine.)
        x, y = gbm_expert._build_training_data_horizon(date(2025, 6, 1), 6, "filing")
        assert x, "expected training rows"
        assert max(y) == 180.0, y
        assert 180.0 in y

    def test_horizon_label_excludes_unobservable_target(self, monkeypatch):
        # A3-F2: a target bulletin at/after knowledge_date must not become a
        # training label (walk-forward leakage).
        from lib.business.vqs import gbm_expert

        buls = self._monthly_bulletins(20)
        self._install(monkeypatch, buls, step_days=30)
        # bulletins < kd = 2023-01..2023-11 (i0..i10). Valid 6m samples need B-1 to
        # exist AND B+5 to be published BEFORE kd. That is i1..i5 (targets
        # 2023-07..2023-11); i6+ target 2023-12-01 (== kd) or later and are dropped
        # by the walk-forward guard. Without the guard, i1..i10 = 10 rows leak.
        kd = date(2023, 12, 1)
        x, y = gbm_expert._build_training_data_horizon(kd, 6, "filing")
        assert len(x) == 5, len(x)

    def test_model_cache_key_discriminates_action_type(self, monkeypatch):
        # A3-F3: filing and final_action must train/cache SEPARATE models.
        import sys

        from lib.business.vqs import gbm_expert

        gbm_expert._model_cache.clear()
        trained_for = []

        def fake_training(kd, action_type="filing"):
            trained_for.append(action_type)
            return [[0.0] * len(gbm_expert.FEATURE_NAMES)], [1.0]

        monkeypatch.setattr(gbm_expert, "_build_training_data", fake_training)
        fake_lgb = SimpleNamespace(
            LGBMRegressor=lambda **k: SimpleNamespace(
                fit=lambda x, y: None, predict=lambda x: [0.0]
            )
        )
        monkeypatch.setitem(sys.modules, "lightgbm", fake_lgb)

        kd = date(2025, 6, 1)
        m_filing = gbm_expert._get_or_train_model(kd, "filing")
        m_final = gbm_expert._get_or_train_model(kd, "final_action")
        assert m_filing is not None and m_final is not None
        assert trained_for == ["filing", "final_action"]  # no cache collision
        assert m_filing is not m_final
        gbm_expert._model_cache.clear()


class TestAggregatorWeightIntegrity:
    """THEME 3: online Hedge aggregator weight-learning integrity.

    A4-F1: warmup replayed each bulletin at knowledge_date = its OWN publication
    date; get_cutoff_at_date is inclusive so persistence saw the actual cutoff and
    scored loss 0 every step → weights collapsed onto persistence.
    A4-F3/F4: the series/weight key omitted action_type, so filing and
    final_action shared one weight vector (and the 2nd action's warmup was skipped).
    A4-F8: an abstaining expert kept factor 1.0 while active experts were penalised,
    so its relative weight grew and swamped the blend when it woke up.
    """

    def test_series_key_discriminates_action_type(self):
        from lib.business.vqs.aggregator import ExpertAggregator

        agg = ExpertAggregator()
        assert agg._get_series_key("2nd", 3, "filing") != agg._get_series_key(
            "2nd", 3, "final_action"
        )

    def test_abstaining_expert_does_not_gain_relative_weight(self):
        from lib.business.vqs.aggregator import ExpertAggregator

        experts = {
            "persistence": lambda vc, c, at, kd, facts=None: date(2020, 1, 1),
            "abstainer": lambda vc, c, at, kd, facts=None: None,
        }
        agg = ExpertAggregator(experts=experts)
        kd = date(2024, 1, 1)
        agg.predict("2nd", 3, "filing", kd)
        # actual differs from persistence's pred → persistence takes a real loss.
        agg.update("2nd", 3, kd, date(2020, 3, 1), action_type="filing")
        w = agg.weights[agg._get_series_key("2nd", 3, "filing")]
        # Both experts start at 0.5. The abstainer must track the field's mean loss
        # (only persistence is active), so normalised weights stay equal — it does
        # NOT balloon to > 0.5 the way factor=1.0 would make it.
        assert abs(w["persistence"] - w["abstainer"]) < 1e-9

    def test_warmup_scores_at_day_before_publication(self, monkeypatch):
        # A4-F1: each warmup step must score at pub_date - 1 (mirroring live), not
        # at pub_date (which hands persistence the answer).
        import models.visa_cutoff_date as vcd_mod
        from lib.business.vqs import aggregator as agg_mod

        class _Chain:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, **k):
                return self

            def select_related(self, *a):
                return self

            def order_by(self, *a):
                return self

            def __iter__(self):
                return iter(self._rows)

            def __len__(self):
                return len(self._rows)

        row = SimpleNamespace(
            bulletin=SimpleNamespace(publication_date=date(2024, 2, 1)),
            cutoff_date=date(2020, 1, 1),
        )
        monkeypatch.setattr(
            vcd_mod, "VisaCutoffDate", SimpleNamespace(objects=_Chain([row]))
        )
        monkeypatch.setattr(
            "lib.business.vqs.seasonal_predictor.get_last_N_moves",
            lambda *a, **k: [],
        )

        agg = agg_mod.ExpertAggregator()
        seen_predict_kd, seen_update_kd = [], []
        monkeypatch.setattr(
            agg, "predict", lambda vc, c, at, kd, facts=None: seen_predict_kd.append(kd)
        )
        monkeypatch.setattr(
            agg, "update",
            lambda vc, c, kd, actual, **kw: seen_update_kd.append(kd),
        )
        agg.warmup_history("2nd", 3, "filing", date(2025, 1, 1))
        assert seen_predict_kd == [date(2024, 1, 31)]  # pub_date - 1, not 2024-02-01
        assert seen_update_kd == [date(2024, 1, 31)]


class TestDirectionCorrectSymmetry:
    """A4-F5: trend-direction scoring must be symmetric. A held month
    (actual didn't move) counts a predicted move as WRONG, not as an excluded
    None — the old logic only ever returned True/None on held months, inflating
    trend accuracy on the common no-movement case."""

    def test_direction_correct_matrix(self):
        from lib.business.vqs.accuracy_metrics import _direction_correct

        assert _direction_correct(0, 0) is True       # held, predicted held → right
        assert _direction_correct(30, 0) is False      # held, predicted move → WRONG (was None)
        assert _direction_correct(-30, 0) is False     # held, predicted retro → WRONG
        assert _direction_correct(30, 30) is True       # advanced, predicted advance
        assert _direction_correct(-30, -30) is True     # retro, predicted retro
        assert _direction_correct(-30, 30) is False     # advanced, predicted retro
        assert _direction_correct(30, -30) is False     # retro, predicted advance
        assert _direction_correct(0, 30) is False       # advanced, predicted held


class TestMultiHorizonKnowledgeDate(TestCase):
    """A2-F1: get_knowledge_date_for_target(target, N) must yield a knowledge date
    that is EXACTLY N bulletins before target. The old code subtracted N months and
    then a day; because bulletins publish on the 1st, `1st - 1 day` crosses into the
    prior month, so the computed horizon came out as N+1 and mis-dispatched at the
    6/12-month predictor boundaries."""

    def _gap_months(self, target: date, kd: date) -> int:
        return (target.year - kd.year) * 12 + (target.month - kd.month)

    def test_computed_horizon_matches_requested_primary_path(self):
        from scripts.publish_predictions import get_knowledge_date_for_target

        for m in range(1, 13):
            Bulletin.objects.create(publication_date=date(2024, m, 1))
        target = date(2024, 8, 1)
        for n in (1, 2, 3, 6):
            kd = get_knowledge_date_for_target(target, n)
            assert self._gap_months(target, kd) == n, (n, kd)

    def test_computed_horizon_matches_requested_fallback_path(self):
        # No bulletins created → the fallback branch runs; it must still yield a
        # gap of exactly N.
        from scripts.publish_predictions import get_knowledge_date_for_target

        target = date(2024, 8, 1)
        for n in (2, 3, 6):
            kd = get_knowledge_date_for_target(target, n)
            assert self._gap_months(target, kd) == n, (n, kd)


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
