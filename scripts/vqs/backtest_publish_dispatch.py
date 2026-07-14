"""Backtest the PUBLISHED 6m/12m GBM dispatch (expert_gbm_gated) per serving surface.

The full-system backtest (compute_prediction_accuracy) scores the VQS ensemble via
predict_next_bulletin_and_maturity — NOT the per-series dispatch that
scripts/publish_predictions.py actually serves (RS at 1m, GBM Gated / Pace at
6m/12m). This script is the publish-path-faithful gate for changes to the GBM
hyperparameters (lib/business/vqs/gbm_expert.py _GBM_* constants): it walk-forward
evaluates the exact production call — expert_gbm_gated at horizon 6/12 on the
surfaces the dispatch table routes to GBM — and scores each
(series, horizon, action_type) surface on metrics that capture MEANINGFUL
prediction quality, not just stall-friendly MAE:

  - MAE vs the no-change (persistence) baseline
  - conditional MAE + directional hit rate on months where the cutoff actually
    moved (|actual delta| > 30d and > 90d) — the months a prediction is FOR
  - movement-detection precision/recall/F1 (predicted-move vs actual-move)
  - gate-open rate (how often the model predicts any movement at all) vs the
    actual movement base rate — catches "predict no-change everywhere"

Candidate hyperparameters are applied via --params-json (a JSON object with keys
n_estimators / max_depth / learning_rate / min_child_samples / reg_alpha /
reg_lambda / movement_threshold / gate_threshold — e.g. the `best_params` block
from scripts/vqs/tune_params.py --gbm-params, gbm_-prefixed keys accepted).
Without --params-json it evaluates the committed _GBM_* constants.

Usage (canonical — against the staging DB with working-tree code):
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_publish_dispatch \
      --action-type final_action --out /app/logs/gate_current_fa.json
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_publish_dispatch \
      --action-type final_action --params-json /app/logs/tuned.json \
      --out /app/logs/gate_tuned_fa.json

Output: JSON with per-surface metrics over the full history AND the stall-era
window (targets >= --recent-start, default 2021-10-01), plus per-month rows.
"""

import argparse
import calendar
import json
import logging
from datetime import date, timedelta

import django

django.setup()

from lib.utils.logging_utils import ScriptLogger

logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

# Movement significance thresholds (days) for conditional / detection metrics.
_MOVE_THRESHOLDS = (30, 90)


def _add_months(d: date, n: int) -> date:
    month = d.month + n
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, max_day))


def _gbm_surfaces() -> list[tuple[str, int, int]]:
    """(visa_class, country, horizon) surfaces the publish dispatch routes to GBM.

    Imported from scripts.publish_predictions so this gate can never drift from
    the real dispatch table.
    """
    from scripts.publish_predictions import _GBM_GATED_6M_SERIES, _GBM_GATED_12M_SERIES

    surfaces = [(vc, c, 6) for (c, vc) in _GBM_GATED_6M_SERIES]
    surfaces += [(vc, c, 12) for (c, vc) in _GBM_GATED_12M_SERIES]
    return surfaces


def _apply_params(params: dict) -> dict:
    """Override the gbm_expert module _GBM_* constants with candidate params.

    Mirrors what graduating the constants into gbm_expert.py would do: the
    training functions read the module globals at call time. Accepts both bare
    keys (n_estimators) and the tuner's gbm_-prefixed keys (gbm_n_estimators).
    Returns the effective (movement_threshold, gate_threshold) among the full
    applied set — expert_gbm_gated's defaults are bound at import time, so the
    caller must pass thresholds explicitly.
    """
    from lib.business.vqs import gbm_expert as g

    def _get(key, default):
        return params.get(key, params.get(f"gbm_{key}", default))

    g._model_cache.clear()
    g._classifier_cache.clear()
    g._quantile_cache.clear()
    g._GBM_N_ESTIMATORS = int(_get("n_estimators", g._GBM_N_ESTIMATORS))
    g._GBM_MAX_DEPTH = int(_get("max_depth", g._GBM_MAX_DEPTH))
    g._GBM_NUM_LEAVES = max(15, 2 ** g._GBM_MAX_DEPTH - 1)
    g._GBM_LEARNING_RATE = float(_get("learning_rate", g._GBM_LEARNING_RATE))
    g._GBM_MIN_CHILD_SAMPLES = int(_get("min_child_samples", g._GBM_MIN_CHILD_SAMPLES))
    g._GBM_REG_ALPHA = float(_get("reg_alpha", g._GBM_REG_ALPHA))
    g._GBM_REG_LAMBDA = float(_get("reg_lambda", g._GBM_REG_LAMBDA))
    g._GBM_DEFAULT_MOVEMENT_THRESHOLD = int(
        _get("movement_threshold", g._GBM_DEFAULT_MOVEMENT_THRESHOLD)
    )
    g._GBM_DEFAULT_GATE_THRESHOLD = float(
        _get("gate_threshold", g._GBM_DEFAULT_GATE_THRESHOLD)
    )
    return {
        "n_estimators": g._GBM_N_ESTIMATORS,
        "max_depth": g._GBM_MAX_DEPTH,
        "num_leaves": g._GBM_NUM_LEAVES,
        "learning_rate": g._GBM_LEARNING_RATE,
        "min_child_samples": g._GBM_MIN_CHILD_SAMPLES,
        "reg_alpha": g._GBM_REG_ALPHA,
        "reg_lambda": g._GBM_REG_LAMBDA,
        "movement_threshold": g._GBM_DEFAULT_MOVEMENT_THRESHOLD,
        "gate_threshold": g._GBM_DEFAULT_GATE_THRESHOLD,
    }


def collect_rows(action_type: str, movement_threshold: int, gate_threshold: float) -> list[dict]:
    """Walk-forward: one row per (surface, bulletin) with pred/actual/baseline deltas."""
    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from lib.business.vqs.gbm_expert import expert_gbm_gated
    from models.raw_facts import RawFactsLedger

    all_pub = sorted(b.publication_date for b in get_all_bulletins())
    max_pub = max(all_pub)
    all_facts = list(RawFactsLedger.objects.all().order_by("publication_date"))
    surfaces = _gbm_surfaces()

    rows: list[dict] = []
    for i, pub_date in enumerate(all_pub):
        knowledge_date = pub_date - timedelta(days=1)
        current_facts = [f for f in all_facts if f.publication_date <= knowledge_date]
        for visa_class, country, horizon in surfaces:
            target = _add_months(pub_date, horizon - 1)
            if target > max_pub:
                continue
            current = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
            actual = get_cutoff_at_date(visa_class, country, action_type, target)
            if current is None or actual is None:
                continue
            pred = expert_gbm_gated(
                visa_class, country, action_type, knowledge_date, horizon,
                movement_threshold, gate_threshold, current_facts,
            )
            if pred is None:
                continue
            rows.append({
                "series": f"{['','','China','India'][country]} EB-{['','1','2','3'][int(visa_class[0])]}",
                "horizon": horizon,
                "knowledge_date": knowledge_date.isoformat(),
                "target": target.isoformat(),
                "actual_delta": (actual - current).days,
                "pred_delta": (pred - current).days,
                "err": abs((pred - actual).days),
                "baseline_err": abs((actual - current).days),
            })
        if (i + 1) % 50 == 0:
            logger.info("processed %d/%d bulletins (%d rows)", i + 1, len(all_pub), len(rows))
    return rows


def _metrics(rows: list[dict]) -> dict:
    """Per-surface metric block for one row subset."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    out = {
        "n": n,
        "mae": round(sum(r["err"] for r in rows) / n, 1),
        "baseline_mae": round(sum(r["baseline_err"] for r in rows) / n, 1),
        "gate_open_rate": round(sum(1 for r in rows if r["pred_delta"] != 0) / n, 3),
    }
    for thr in _MOVE_THRESHOLDS:
        moved = [r for r in rows if abs(r["actual_delta"]) > thr]
        stalled = [r for r in rows if abs(r["actual_delta"]) <= thr]
        pred_sig = [r for r in rows if abs(r["pred_delta"]) > thr]
        tp = [r for r in moved if abs(r["pred_delta"]) > thr
              and r["pred_delta"] * r["actual_delta"] > 0]
        dir_hits = [r for r in moved if r["pred_delta"] * r["actual_delta"] > 0]
        block = {
            "actual_move_rate": round(len(moved) / n, 3),
            "cond_mae": round(sum(r["err"] for r in moved) / len(moved), 1) if moved else None,
            "cond_baseline_mae": (
                round(sum(r["baseline_err"] for r in moved) / len(moved), 1) if moved else None
            ),
            "dir_hit_rate": round(len(dir_hits) / len(moved), 3) if moved else None,
            "precision": round(len(tp) / len(pred_sig), 3) if pred_sig else None,
            "recall": round(len(tp) / len(moved), 3) if moved else None,
            "stall_correct_rate": (
                round(sum(1 for r in stalled if abs(r["pred_delta"]) <= thr) / len(stalled), 3)
                if stalled else None
            ),
        }
        p, r_ = block["precision"], block["recall"]
        block["f1"] = round(2 * p * r_ / (p + r_), 3) if p and r_ and (p + r_) > 0 else None
        out[f"move_gt_{thr}d"] = block
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-type", default="final_action",
                        choices=["final_action", "filing"])
    parser.add_argument("--params-json", default=None,
                        help="JSON file with candidate GBM params (tuner best_params ok)")
    parser.add_argument("--recent-start", default="2021-10-01",
                        help="Start of the stall-era window (target date, ISO)")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()
    script_logger.log_call(args=vars(args), context="Publish-dispatch GBM graduation gate")

    params_in = {}
    if args.params_json:
        with open(args.params_json) as f:
            params_in = json.load(f)
        if "best_params" in params_in:
            params_in = params_in["best_params"]
    effective = _apply_params(params_in)
    logger.info("effective GBM params: %s", effective)

    rows = collect_rows(
        args.action_type, effective["movement_threshold"], effective["gate_threshold"]
    )
    recent_start = date.fromisoformat(args.recent_start)

    surfaces = sorted({(r["series"], r["horizon"]) for r in rows})
    report = {
        "action_type": args.action_type,
        "params": effective,
        "recent_start": args.recent_start,
        "surfaces": {},
        "rows": rows,
    }
    for series, horizon in surfaces:
        sub = [r for r in rows if r["series"] == series and r["horizon"] == horizon]
        recent = [r for r in sub if date.fromisoformat(r["target"]) >= recent_start]
        key = f"{series} @{horizon}m"
        report["surfaces"][key] = {"all": _metrics(sub), "recent": _metrics(recent)}
        logger.info("%s: all=%s", key, report["surfaces"][key]["all"])

    with open(args.out, "w") as f:
        json.dump(report, f, indent=1)
    logger.info("wrote %s", args.out)


if __name__ == "__main__":
    main()
