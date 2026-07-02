#!/usr/bin/env python3
"""Backtest 1-month selector policies for the VQS production dispatch.

The production 1-month model is ``predict_regime_switched`` →
``_select_expert_for_regime`` (solver.py), NOT the Hedge aggregator: at the 1m
horizon publish_predictions dispatches every series to the regime-switched
selector. This harness evaluates that *selection decision* directly, at the
expert level, so alternative season/direction-conditioning policies can be
compared in seconds instead of a ~10-min full ``evaluate_model`` run.

Faithful for the physics-eligible focus series (India/China EB-1/2/3) and the
forced-persistence fallback series (EB-4, ROW/Mexico/Philippines EB-2/3), which
are exactly the cells the selector governs at 1m.

Metrics per (series, policy), stratified by FY phase (end_of_fy = Jul–Sep
target) and by actual move size:
  * MAE               — mean |pred − actual| in days.
  * wMAE              — movement-magnitude-weighted MAE (MetricConfig.magnitude_weight);
                        the ticket's "catch the big advances, not just no-change" target.
  * dir%              — of months that actually moved ≥MOVE_MIN days, fraction where the
                        prediction moved the SAME direction (persistence scores 0 here).
  * recall%           — of months that actually moved ≥MOVE_MIN days, fraction where the
                        prediction called a move ≥PRED_MIN days (caught that a move was coming).

Run in staging (prod-copy DB):
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_selector
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_selector --policies prod fy_seasonal fy_demand
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_selector --fallback   # T4 series
"""

import argparse
import os
from collections import defaultdict

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.vqs.data_cache import is_current_at_date  # noqa: E402
from lib.business.vqs.expert_pool import ALL_EXPERTS  # noqa: E402
from lib.business.vqs.metric_config import MetricConfig  # noqa: E402
from lib.business.vqs.prediction_loader import get_actual_cutoffs  # noqa: E402
from lib.business.vqs.regime import (  # noqa: E402
    FYPhase,
    Regime,
    classify_regime,
    get_fy_phase,
)
from lib.business.vqs.seasonal_predictor import get_last_N_moves  # noqa: E402
from lib.business.vqs.solver import (  # noqa: E402
    _select_expert_for_regime,
    predict_regime_switched,
)
from models.enums.country import Country  # noqa: E402

ACTION = "final_action"
MOVE_MIN = 30   # a month "moved" if |actual move| >= this
PRED_MIN = 15   # a prediction "called a move" if |pred move| >= this

FOCUS = [
    ("1st", Country.CHINA.value, "China EB-1"),
    ("2nd", Country.CHINA.value, "China EB-2"),
    ("3rd", Country.CHINA.value, "China EB-3"),
    ("1st", Country.INDIA.value, "India EB-1"),
    ("2nd", Country.INDIA.value, "India EB-2"),
    ("3rd", Country.INDIA.value, "India EB-3"),
]
# ROW ("Other Countries") is Country.ALL in the enum.
FALLBACK = [
    ("4th", Country.INDIA.value, "India EB-4"),
    ("4th", Country.CHINA.value, "China EB-4"),
    ("2nd", Country.ALL.value, "ROW EB-2"),
    ("3rd", Country.ALL.value, "ROW EB-3"),
    ("2nd", Country.MEXICO.value, "Mexico EB-2"),
    ("3rd", Country.PHILIPPINES.value, "Phil EB-3"),
    ("4th", Country.ALL.value, "ROW EB-4"),
]

SERIES_WEIGHTS = MetricConfig.defaults().series_weights


# --- selector policies: (regime_state, vc, country, target_month) -> expert name ---

def policy_prod(regime_state, vc, country, target_month):
    """Current production selector."""
    return _select_expert_for_regime(regime_state, vc, country, target_month)


def _end_of_fy(target_month):
    return get_fy_phase(target_month) == FYPhase.END_OF_FY


def policy_fy_seasonal(regime_state, vc, country, target_month):
    """END_OF_FY (Jul–Sep): if backward regime is quiet, use seasonal_median."""
    if _end_of_fy(target_month) and regime_state.regime in (
        Regime.STALLED, Regime.RETROGRESSING,
    ):
        return "seasonal_median"
    return _select_expert_for_regime(regime_state, vc, country, target_month)


def policy_fy_fyreset(regime_state, vc, country, target_month):
    """END_OF_FY: use fy_reset expert when quiet."""
    if _end_of_fy(target_month) and regime_state.regime in (
        Regime.STALLED, Regime.RETROGRESSING,
    ):
        return "fy_reset"
    return _select_expert_for_regime(regime_state, vc, country, target_month)


def policy_fy_demand(regime_state, vc, country, target_month):
    """END_OF_FY: use demand_signal (seasonal w/ demand brake) when quiet."""
    if _end_of_fy(target_month) and regime_state.regime in (
        Regime.STALLED, Regime.RETROGRESSING,
    ):
        return "demand_signal"
    return _select_expert_for_regime(regime_state, vc, country, target_month)


def policy_persistence(regime_state, vc, country, target_month):
    return "persistence"


def policy_seasonal_always(regime_state, vc, country, target_month):
    return "seasonal_median"


def policy_fyreset_always(regime_state, vc, country, target_month):
    return "fy_reset"


POLICIES = {
    "prod": policy_prod,
    "persistence": policy_persistence,
    "fy_seasonal": policy_fy_seasonal,
    "fy_fyreset": policy_fy_fyreset,
    "fy_demand": policy_fy_demand,
    "seasonal_always": policy_seasonal_always,
    "fyreset_always": policy_fyreset_always,
    "solver": None,  # special-cased in eval_series: true predict_regime_switched path
}

_META = MetricConfig.defaults()


# --- T3 gated-hybrid predictors: return a DATE directly (not an expert name).
# Two-stage: a gate decides move/hold; when it fires, take an active expert's
# direction with a DAMPENED magnitude (regime.shrink_prediction) so we express
# direction without the overshoot that made raw seasonal/demand regress MAE. ---

def _gated_hybrid(vc, country, action, kd, current, target_month, regime_state,
                  gate_min=25, shrink=True, active="demand_signal"):
    from lib.business.vqs.regime import shrink_prediction
    if current is None:
        return current
    active_fn = ALL_EXPERTS.get(active, ALL_EXPERTS["persistence"])
    active_pred = active_fn(vc, country, action, kd)
    if active_pred is None:
        return current
    move = (active_pred - current).days
    # Gate: only express a move if the active expert signals a meaningful one.
    if abs(move) < gate_min:
        return current
    if shrink:
        move = shrink_prediction(move, regime_state)
    return current + __import__("datetime").timedelta(days=int(move))


PRED_POLICIES = {
    "gate_demand_shrink": lambda *a: _gated_hybrid(*a, gate_min=25, shrink=True, active="demand_signal"),
    "gate_demand_raw":    lambda *a: _gated_hybrid(*a, gate_min=25, shrink=False, active="demand_signal"),
    "gate_seasonal_shrink": lambda *a: _gated_hybrid(*a, gate_min=25, shrink=True, active="seasonal_median"),
    "gate_pace_shrink":   lambda *a: _gated_hybrid(*a, gate_min=25, shrink=True, active="momentum_3m"),
}


def move_size(move_days):
    a = abs(move_days)
    if a == 0:
        return "none"
    if a <= 30:
        return "small"
    if a <= 90:
        return "medium"
    return "big"


def _solver_prediction(vc, country, knowledge_date, curr_pub):
    """True production 1m path: predict_regime_switched -> target-month cutoff."""
    outcome = predict_regime_switched(
        knowledge_date=knowledge_date, visa_class=vc, country=country, action_type=ACTION,
    )
    for res in outcome.results:
        if res.month.year == curr_pub.year and res.month.month == curr_pub.month:
            return res.cutoff_date
    return outcome.predicted_cutoff


def eval_series(vc, country, policy_name):
    """Return list of records for one series under one policy."""
    policy_fn = POLICIES.get(policy_name)
    actuals = get_actual_cutoffs(vc, country, ACTION)  # {pub_date: cutoff}
    pubs = sorted(actuals)
    recs = []
    for i in range(1, len(pubs)):
        prev_pub, curr_pub = pubs[i - 1], pubs[i]
        # only clean consecutive-month 1m transitions
        months_gap = (curr_pub.year - prev_pub.year) * 12 + (curr_pub.month - prev_pub.month)
        if months_gap != 1:
            continue
        knowledge_date = prev_pub
        # Exclude months where the series was "Current" at knowledge time: prod
        # suppresses those predictions (they're meaningless), so scoring any
        # expert on them is an artifact. This is what production actually does.
        if is_current_at_date(vc, country, ACTION, knowledge_date):
            continue
        current = actuals[prev_pub]
        actual = actuals[curr_pub]
        target_month = curr_pub.month

        moves = get_last_N_moves(vc, country, ACTION, knowledge_date, 6)
        regime_state = classify_regime(moves)
        if policy_name == "solver":
            pred = _solver_prediction(vc, country, knowledge_date, curr_pub)
        elif policy_name in PRED_POLICIES:
            pred = PRED_POLICIES[policy_name](
                vc, country, ACTION, knowledge_date, current, target_month, regime_state
            )
        else:
            expert = policy_fn(regime_state, vc, country, target_month)
            fn = ALL_EXPERTS.get(expert, ALL_EXPERTS["persistence"])
            pred = fn(vc, country, ACTION, knowledge_date)
        if pred is None:
            pred = current

        err = (pred - actual).days
        actual_move = (actual - current).days
        pred_move = (pred - current).days
        recs.append({
            "kd": knowledge_date,
            "target_month": target_month,
            "fy_phase": get_fy_phase(target_month).value,
            "err": err,
            "actual_move": actual_move,
            "pred_move": pred_move,
            "move_mag": move_size(actual_move),
        })
    return recs


def agg(recs):
    """Aggregate metrics over a list of records."""
    if not recs:
        return None
    n = len(recs)
    mae = sum(abs(r["err"]) for r in recs) / n
    wsum = sum(_META.magnitude_weight(r["actual_move"]) for r in recs)
    wmae = sum(_META.magnitude_weight(r["actual_move"]) * abs(r["err"]) for r in recs) / wsum
    moved = [r for r in recs if abs(r["actual_move"]) >= MOVE_MIN]
    if moved:
        dir_ok = sum(
            1 for r in moved
            if (r["pred_move"] > 0) == (r["actual_move"] > 0) and abs(r["pred_move"]) >= PRED_MIN
        )
        recall = sum(1 for r in moved if abs(r["pred_move"]) >= PRED_MIN)
        dir_pct = 100.0 * dir_ok / len(moved)
        recall_pct = 100.0 * recall / len(moved)
    else:
        dir_pct = recall_pct = float("nan")
    return {
        "n": n, "mae": mae, "wmae": wmae,
        "dir": dir_pct, "recall": recall_pct, "n_moved": len(moved),
    }


def fmt(m):
    if m is None:
        return "     —"
    d = f"{m['dir']:.0f}%" if m["dir"] == m["dir"] else "  —"
    r = f"{m['recall']:.0f}%" if m["recall"] == m["recall"] else "  —"
    return f"{m['mae']:6.1f} {m['wmae']:6.1f} {d:>5} {r:>5} {m['n']:4d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policies", nargs="+", default=["prod", "fy_seasonal", "fy_fyreset", "fy_demand"])
    ap.add_argument("--fallback", action="store_true", help="Evaluate the T4 fallback series instead of the 6 focus series")
    ap.add_argument("--phase", default="end_of_fy", help="FY phase slice to headline (default end_of_fy)")
    args = ap.parse_args()

    series = FALLBACK if args.fallback else FOCUS
    policies = [p for p in args.policies if p in POLICIES or p in PRED_POLICIES]

    # cache records per (series, policy)
    print(f"\n{'='*92}\n1-MONTH SELECTOR BACKTEST  (action={ACTION}, move_min={MOVE_MIN}d, pred_min={PRED_MIN}d)")
    print("cols: MAE  wMAE  dir%  recall%  N   |  wMAE=magnitude-weighted, dir/recall over months that moved >=30d")
    print("=" * 92)

    all_recs = defaultdict(dict)  # policy -> series_label -> recs
    for vc, country, label in series:
        for pol in policies:
            all_recs[pol][label] = eval_series(vc, country, pol)

    # Per-series headline slice (end_of_fy) + overall
    for slice_name in (args.phase, "ALL"):
        print(f"\n--- slice: {slice_name} ---")
        header = f"{'Series':13} {'Policy':16} {'MAE':>6} {'wMAE':>6} {'dir':>5} {'rec':>5} {'N':>4}"
        print(header)
        for vc, country, label in series:
            for pol in policies:
                recs = all_recs[pol][label]
                if slice_name != "ALL":
                    recs = [r for r in recs if r["fy_phase"] == slice_name]
                m = agg(recs)
                print(f"{label:13} {pol:16} {fmt(m)}")
            print()

    # Series-weighted composite across all series (protects against
    # winning only on FY jumps): wMAE weighted by MetricConfig series weight.
    print(f"\n{'='*92}\nCOMPOSITE (series-weighted mean of per-series wMAE)  — guardrail: must not rise vs prod")
    print(f"{'slice':16} " + " ".join(f"{p:>14}" for p in policies))
    for slice_name in ("ALL", args.phase):
        row = [f"{slice_name:16}"]
        for pol in policies:
            num = den = 0.0
            for vc, country, label in series:
                recs = all_recs[pol][label]
                if slice_name != "ALL":
                    recs = [r for r in recs if r["fy_phase"] == slice_name]
                m = agg(recs)
                if m is None:
                    continue
                w = SERIES_WEIGHTS.get((vc, country), 1.0)
                num += w * m["wmae"]
                den += w
            comp = num / den if den else float("nan")
            row.append(f"{comp:14.1f}")
        print(" ".join(row))
    print("=" * 92)


if __name__ == "__main__":
    main()
