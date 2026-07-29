#!/usr/bin/env python3
"""Backtest the MULTI-STEP trajectory that feeds the dashboard 6m/12m cells.

``backtest_selector.py`` measures the 1-month selection decision. This harness
measures the other half: the horizon trajectory that ``predict_regime_switched``
rolls out (``solver.py`` -> ``ALL_EXPERT_TRAJECTORIES[traj_expert]``) and that
``webapp/views/bulletin/dashboard.py`` reads as ``results[5]`` / ``results[11]``.

Why it exists: on a STALLED/RETRO series the selector picks ``persistence``,
whose trajectory is ``[current] * steps`` -- flat by construction. A 12-month
horizon therefore spans an October fiscal-year reset without modelling it. This
compares candidate trajectories for the persistence regime.

VARIANTS (only the ``persistence`` trajectory differs; every other expert's
trajectory, the step-0 single-step prediction, and the demand gate are
untouched, so a series whose ``traj_expert`` is not ``persistence`` scores
identically across all variants -- by construction, not by luck):

  prod              [current] * steps.  Also = ticket shape (iii) "presentation
                    only", which makes no model change at all.
  oct_fyreset       Shape (i) LITERAL: apply ``trajectory_fy_reset``'s October
                    branch to the flat baseline. That branch is
                    ``get_median_october_retrogression``, i.e. retrogression
                    ONLY (``-move if move < 0 else 0``), so it is a no-op on a
                    series whose October historically ADVANCES.
  oct_signed        Shape (i) CORRECTED: October step = the SIGNED October
                    seasonal median (advance or retro), flat elsewhere.
  oct_signed_recov  oct_signed + fy_reset's Nov/Dec/Jan post-retro recovery.
  hazard_ev         Shape (ii) mean: per-month move probability p and median
                    conditional move m from the series' own base rate; step h =
                    current + h*p*m.  A smooth ramp.
  hazard_med        Shape (ii) median: cumulative moves ~ Binomial(h, p) scaled
                    by m; take the distribution median.  A step function.
  hazard_seasonal   Shape (ii) with month-of-year specific p and m (October has
                    a far higher move rate than March), expected value.

METRICS, per (variant, horizon h in 1..12):
  MAE      mean |pred - actual| in days.
  wMAE     magnitude-weighted (MetricConfig.magnitude_weight over the actual
           cumulative move) -- "catch the big steps, not just the no-change".
  composite  series-weighted (MetricConfig.series_weight) MAE, and the
           horizon-weighted roll-up over {1,3,6,12} (MetricConfig.horizon_weights).

SLICES (the whole trade being measured):
  moved    observations where the series ACTUALLY moved >= MOVE_MIN over the
           horizon -- where a step-aware trajectory should win.
  flat     observations where it did not -- where persistence is already
           optimal and any step-aware trajectory must not do much damage.
  oct      observations whose horizon window spans an October bulletin.

PRE-REGISTERED DECISION RULE (fixed before the first run; do not retune it to
fit the output).  A variant is a CLEAR WINNER and gets shipped only if, on the
series-weighted composite:
  (a) MAE improves vs prod at BOTH h=6 and h=12; and
  (b) the flat slice regresses by no more than 10% relative AND 15 days
      absolute at h=12 (do-no-harm on the ~79% of months that never move); and
  (c) the moved slice improves by at least 10% relative at h=12.
Anything else -> no clear winner; report the numbers and leave the model alone.

Run (working tree mounted over the staging prod-copy DB):
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_trajectory
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_trajectory --action-type filing
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_trajectory --json out.json
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.vqs.data_cache import (  # noqa: E402
    get_cutoff_at_date,
    get_cutoffs_up_to,
    is_current_at_date,
    is_unavailable_at_date,
)
from lib.business.vqs.metric_config import MetricConfig  # noqa: E402
from lib.business.vqs.seasonal_predictor import (  # noqa: E402
    get_median_october_retrogression,
    get_median_post_retro_recovery,
    get_seasonal_prediction,
)
from lib.business.vqs.solver import predict_regime_switched  # noqa: E402
from models.enums.country import Country  # noqa: E402

STEPS = 12
MOVE_MIN = 30          # horizon "moved" if |actual - current| >= this
HAZARD_MOVE_MIN = 30   # a month counts as a move for the hazard base rate
HAZARD_LOOKBACK_Y = 4  # match the single-step experts' lookback_years=4

FOCUS = [
    ("1st", Country.CHINA.value, "China EB-1"),
    ("2nd", Country.CHINA.value, "China EB-2"),
    ("3rd", Country.CHINA.value, "China EB-3"),
    ("1st", Country.INDIA.value, "India EB-1"),
    ("2nd", Country.INDIA.value, "India EB-2"),
    ("3rd", Country.INDIA.value, "India EB-3"),
]

CFG = MetricConfig.defaults()


# --------------------------------------------------------------------------
# candidate persistence trajectories
# --------------------------------------------------------------------------

def _target_month(knowledge_date: date, i: int) -> int:
    """Bulletin month of step i, matching the expert_pool convention."""
    return ((knowledge_date.month + i) % 12) + 1


def traj_prod(vc, country, at, kd, steps=STEPS, facts=None):
    cur = get_cutoff_at_date(vc, country, at, kd)
    return [cur] * steps if cur else [None] * steps


def traj_oct_fyreset(vc, country, at, kd, steps=STEPS, facts=None):
    """Shape (i) literal: fy_reset's October branch on a flat baseline."""
    cur = get_cutoff_at_date(vc, country, at, kd)
    if cur is None:
        return [None] * steps
    out, cutoff = [], cur
    for i in range(steps):
        if _target_month(kd, i) == 10:
            retro = get_median_october_retrogression(vc, country, at, kd)
            if retro > 0:
                cutoff = cutoff - timedelta(days=retro)
        out.append(cutoff)
    return out


def _signed_october(vc, country, at, kd) -> int:
    """Signed median October (Sep->Oct) move: negative retro, positive advance."""
    move = get_seasonal_prediction(
        vc, country, at, knowledge_date=kd, target_month=10,
        min_samples=2, lookback_years=None,
    )
    return move or 0


def traj_oct_signed(vc, country, at, kd, steps=STEPS, facts=None):
    """Shape (i) corrected: signed October step, flat elsewhere."""
    cur = get_cutoff_at_date(vc, country, at, kd)
    if cur is None:
        return [None] * steps
    out, cutoff = [], cur
    for i in range(steps):
        if _target_month(kd, i) == 10:
            cutoff = cutoff + timedelta(days=_signed_october(vc, country, at, kd))
        out.append(cutoff)
    return out


def traj_oct_signed_recov(vc, country, at, kd, steps=STEPS, facts=None):
    """oct_signed + fy_reset's Nov/Dec/Jan post-retro recovery branch."""
    cur = get_cutoff_at_date(vc, country, at, kd)
    if cur is None:
        return [None] * steps
    out, cutoff = [], cur
    for i in range(steps):
        tm = _target_month(kd, i)
        if tm == 10:
            cutoff = cutoff + timedelta(days=_signed_october(vc, country, at, kd))
        elif tm in (11, 12, 1):
            rec = get_median_post_retro_recovery(vc, country, at, kd, tm)
            if rec > 0:
                cutoff = cutoff + timedelta(days=rec)
        out.append(cutoff)
    return out


def _monthly_moves(vc, country, at, kd) -> list[int]:
    """Month-to-month moves within the lookback window, walk-forward safe."""
    cutoffs = get_cutoffs_up_to(vc, country, at, kd)
    if len(cutoffs) < 2:
        return []
    lb = date(kd.year - HAZARD_LOOKBACK_Y, kd.month, min(kd.day, 28))
    cutoffs = [c for c in cutoffs if c.bulletin.publication_date >= lb]
    return [
        ((cutoffs[i].cutoff_date - cutoffs[i - 1].cutoff_date).days,
         cutoffs[i].bulletin.publication_date.month)
        for i in range(1, len(cutoffs))
    ]


def _hazard_params(vc, country, at, kd) -> tuple[float, float]:
    """(p, m): per-month move probability and median conditional move size."""
    moves = _monthly_moves(vc, country, at, kd)
    if len(moves) < 6:
        return 0.0, 0.0
    movers = [d for d, _ in moves if abs(d) >= HAZARD_MOVE_MIN]
    if not movers:
        return 0.0, 0.0
    return len(movers) / len(moves), float(median(movers))


def traj_hazard_ev(vc, country, at, kd, steps=STEPS, facts=None):
    """Shape (ii) mean: current + h * p * m."""
    cur = get_cutoff_at_date(vc, country, at, kd)
    if cur is None:
        return [None] * steps
    p, m = _hazard_params(vc, country, at, kd)
    return [cur + timedelta(days=int(round((i + 1) * p * m))) for i in range(steps)]


def _binomial_quantile(h: int, p: float, q: float) -> int:
    """Smallest k with P(Binom(h,p) <= k) >= q."""
    if p <= 0:
        return 0
    cum, term = 0.0, (1 - p) ** h
    for k in range(h + 1):
        cum += term
        if cum >= q:
            return k
        term *= (h - k) / (k + 1) * (p / (1 - p)) if p < 1 else 0
    return h


def traj_hazard_med(vc, country, at, kd, steps=STEPS, facts=None):
    """Shape (ii) median: m * median(Binom(h, p)) -- a step function."""
    cur = get_cutoff_at_date(vc, country, at, kd)
    if cur is None:
        return [None] * steps
    p, m = _hazard_params(vc, country, at, kd)
    return [
        cur + timedelta(days=int(round(m * _binomial_quantile(i + 1, p, 0.5))))
        for i in range(steps)
    ]


def _seasonal_hazard_params(vc, country, at, kd) -> tuple[dict, float, float]:
    """Per-month (p, m), falling back to the pooled rate when sparse."""
    moves = _monthly_moves(vc, country, at, kd)
    p_g, m_g = _hazard_params(vc, country, at, kd)
    by_month: dict[int, list[int]] = defaultdict(list)
    for d, mo in moves:
        by_month[mo].append(d)
    per: dict[int, tuple[float, float]] = {}
    for mo, ds in by_month.items():
        if len(ds) < 3:
            continue
        movers = [d for d in ds if abs(d) >= HAZARD_MOVE_MIN]
        per[mo] = (len(movers) / len(ds), float(median(movers)) if movers else 0.0)
    return per, p_g, m_g


def traj_hazard_seasonal(vc, country, at, kd, steps=STEPS, facts=None):
    """Shape (ii) with month-of-year hazard, expected value."""
    cur = get_cutoff_at_date(vc, country, at, kd)
    if cur is None:
        return [None] * steps
    per, p_g, m_g = _seasonal_hazard_params(vc, country, at, kd)
    out, acc = [], 0.0
    for i in range(steps):
        p, m = per.get(_target_month(kd, i), (p_g, m_g))
        acc += p * m
        out.append(cur + timedelta(days=int(round(acc))))
    return out


VARIANTS = {
    "prod": traj_prod,
    "oct_fyreset": traj_oct_fyreset,
    "oct_signed": traj_oct_signed,
    "oct_signed_recov": traj_oct_signed_recov,
    "hazard_ev": traj_hazard_ev,
    "hazard_med": traj_hazard_med,
    "hazard_seasonal": traj_hazard_seasonal,
}


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------

def _actuals(vc: int, country: int, action_type: str) -> dict[tuple[int, int], date]:
    """{(year, month) -> cutoff} for real, non-Current, non-Unavailable rows."""
    from models.visa_cutoff_date import VisaCutoffDate

    out = {}
    qs = VisaCutoffDate.objects.filter(
        visa_class=vc, country=country, action_type=action_type,
        cutoff_date__isnull=False,
    ).select_related("bulletin")
    for row in qs:
        # Direct attribute access, not getattr-with-default: a rename must fail
        # loudly rather than silently stop excluding Current/Unavailable rows,
        # whose sentinel cutoffs would poison every MAE below.
        if row.is_current or row.is_unavailable:
            continue
        pub = row.bulletin.publication_date
        out[(pub.year, pub.month)] = row.cutoff_date
    return out


def _step_month(kd: date, i: int) -> tuple[int, int]:
    if kd.month + i >= 12:
        return kd.year + (kd.month + i) // 12, (kd.month + i) % 12 + 1
    return kd.year, kd.month + i + 1


def run(action_types: list[str], start: date, verbose: bool):
    # obs[(variant, h)] -> list of dicts(err, w_mag, w_series, moved, oct_span)
    obs: dict[tuple[str, int], list[dict]] = defaultdict(list)
    traj_expert_counts: dict[str, int] = defaultdict(int)
    n_kdates = 0

    for action_type in action_types:
        for vc, country, label in FOCUS:
            actuals = _actuals(vc, country, action_type)
            if not actuals:
                continue
            kdates = sorted({date(y, m, 1) for (y, m) in actuals})
            kdates = [k for k in kdates if k >= start]
            s_w = CFG.series_weight(vc, country)

            for kd in kdates:
                if is_current_at_date(vc, country, action_type, kd) or \
                        is_unavailable_at_date(vc, country, action_type, kd):
                    continue
                cur = get_cutoff_at_date(vc, country, action_type, kd)
                if cur is None:
                    continue
                # Which targets do we actually have truth for?
                truths = {}
                for i in range(STEPS):
                    y, m = _step_month(kd, i)
                    a = actuals.get((y, m))
                    if a is not None:
                        truths[i] = a
                if not truths:
                    continue

                # One faithful production call: gives step-0 (incl. the demand
                # gate) and the traj_expert actually in force.
                outcome = predict_regime_switched(
                    knowledge_date=kd, visa_class=vc, country=country,
                    action_type=action_type, priority_date=None,
                )
                sel = outcome.metadata.get("selected_expert")
                traj_expert = "persistence" if sel == "demand_gate" else sel
                traj_expert_counts[str(traj_expert)] += 1
                n_kdates += 1
                step0 = outcome.predicted_cutoff
                prod_traj = [r.cutoff_date for r in outcome.results][:STEPS]

                for vname, vfn in VARIANTS.items():
                    if traj_expert != "persistence":
                        # By construction the variant cannot differ.
                        traj = prod_traj
                    else:
                        raw = vfn(vc, country, action_type, kd, STEPS, None)
                        # Mirror solver.py: step 0 is the single-step
                        # prediction, steps 1+ come from the trajectory.
                        traj = [step0] + list(raw[1:])
                    for i, actual in truths.items():
                        if i >= len(traj) or traj[i] is None:
                            continue
                        err = abs((traj[i] - actual).days)
                        move = (actual - cur).days
                        span_months = [_step_month(kd, j)[1] for j in range(i + 1)]
                        obs[(vname, i + 1)].append({
                            "err": err,
                            "w": s_w * CFG.magnitude_weight(move),
                            "sw": s_w,
                            "moved": abs(move) >= MOVE_MIN,
                            "oct": 10 in span_months,
                            "series": f"{label} {action_type}",
                        })
        if verbose:
            print(f"  ... {action_type} done", flush=True)

    return obs, traj_expert_counts, n_kdates


def _agg(rows, key_w="sw", pred=None):
    rows = [r for r in rows if pred is None or pred(r)]
    if not rows:
        return None, 0
    tot_w = sum(r[key_w] for r in rows)
    return sum(r["err"] * r[key_w] for r in rows) / tot_w, len(rows)


def report(obs, traj_counts, n_kdates, out_json=None):
    variants = list(VARIANTS)
    print(f"\nknowledge_dates evaluated: {n_kdates}")
    print("traj_expert in force: " + ", ".join(
        f"{k}={v}" for k, v in sorted(traj_counts.items(), key=lambda x: -x[1])))

    def table(title, pred, key_w):
        print(f"\n=== {title} ===")
        hs = [1, 3, 6, 12]
        print(f"{'variant':<18}" + "".join(f"{'h='+str(h):>12}" for h in hs) + f"{'N(h=12)':>10}")
        base = {}
        for h in hs:
            base[h], _ = _agg(obs[("prod", h)], key_w, pred)
        for v in variants:
            cells = []
            n12 = 0
            for h in hs:
                val, n = _agg(obs[(v, h)], key_w, pred)
                if h == 12:
                    n12 = n
                if val is None:
                    cells.append(f"{'-':>12}")
                elif v == "prod":
                    cells.append(f"{val:>12.1f}")
                else:
                    d = val - base[h] if base[h] is not None else 0
                    cells.append(f"{val:>7.1f}{d:>+5.0f}")
            print(f"{v:<18}" + "".join(cells) + f"{n12:>10}")

    # per-series, h=12
    series = sorted({r["series"] for rows in obs.values() for r in rows})
    print("\n=== MAE by series (h=6 / h=12, unweighted) ===")
    print(f"{'variant':<18}" + "".join(f"{s.replace(' final_action','/FA').replace(' filing','/DoF'):>18}"
                                       for s in series))
    for v in variants:
        cells = []
        for s in series:
            m6, _ = _agg(obs[(v, 6)], "sw", lambda r, s=s: r["series"] == s)
            m12, _ = _agg(obs[(v, 12)], "sw", lambda r, s=s: r["series"] == s)
            cells.append(f"{(m6 or 0):>8.0f}/{(m12 or 0):<9.0f}")
        print(f"{v:<18}" + "".join(cells))

    table("MAE (series-weighted, days) — ALL", None, "sw")
    table("MAE — MOVED slice (|actual move| >= 30d)", lambda r: r["moved"], "sw")
    table("MAE — FLAT slice (series did not move)", lambda r: not r["moved"], "sw")
    table("MAE — horizon spans an October", lambda r: r["oct"], "sw")
    table("wMAE (magnitude-weighted) — ALL", None, "w")

    # pre-registered gate
    print("\n=== PRE-REGISTERED DECISION GATE ===")
    b6, _ = _agg(obs[("prod", 6)], "sw")
    b12, _ = _agg(obs[("prod", 12)], "sw")
    bflat, _ = _agg(obs[("prod", 12)], "sw", lambda r: not r["moved"])
    bmoved, _ = _agg(obs[("prod", 12)], "sw", lambda r: r["moved"])
    # A narrower --start can empty a slice (e.g. no 12-month-out no-move
    # window). The gate cannot be evaluated then; say so rather than crash.
    missing = [n for n, val in
               (("all 6m", b6), ("all 12m", b12),
                ("12m flat", bflat), ("12m moved", bmoved)) if val is None]
    if missing:
        print(f"NOT EVALUABLE — no observations for: {', '.join(missing)}. "
              f"Widen --start (the 12m horizon needs 12 months of actuals "
              f"after each knowledge date).")
        return

    verdicts = {}
    for v in variants:
        if v == "prod":
            continue
        v6, _ = _agg(obs[(v, 6)], "sw")
        v12, _ = _agg(obs[(v, 12)], "sw")
        vflat, _ = _agg(obs[(v, 12)], "sw", lambda r: not r["moved"])
        vmoved, _ = _agg(obs[(v, 12)], "sw", lambda r: r["moved"])
        if None in (v6, v12, vflat, vmoved):
            print(f"{v:<18} NOT EVALUABLE (empty slice)")
            continue
        a = v6 < b6 and v12 < b12
        b = (vflat - bflat) <= min(0.10 * bflat, 15.0)
        c = vmoved <= bmoved * 0.90
        verdicts[v] = {
            "a_both_horizons_improve": a, "b_flat_do_no_harm": b,
            "c_moved_improves_10pct": c, "win": a and b and c,
            "mae6": v6, "mae12": v12, "flat12": vflat, "moved12": vmoved,
        }
        print(f"{v:<18} (a) {str(a):<5} (b) {str(b):<5} (c) {str(c):<5} "
              f"-> {'WIN' if (a and b and c) else 'no'}")
    print(f"\n(prod baseline: 6m {b6:.1f}d, 12m {b12:.1f}d, "
          f"12m flat {bflat:.1f}d, 12m moved {bmoved:.1f}d)")

    if out_json:
        with open(out_json, "w") as f:
            json.dump({"verdicts": verdicts, "traj_experts": dict(traj_counts)}, f,
                      indent=2, default=str)
        print(f"\nwrote {out_json}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action-type", default="both",
                    choices=["filing", "final_action", "both"])
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--json", dest="out_json", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    ats = ["filing", "final_action"] if args.action_type == "both" else [args.action_type]
    start = date.fromisoformat(args.start)
    print(f"trajectory backtest: action_types={ats} start={start} steps={STEPS}")
    obs, tc, n = run(ats, start, args.verbose)
    report(obs, tc, n, args.out_json)


if __name__ == "__main__":
    main()
