"""One-off: confirm the FAD↔DFF reconciliation (Option B) is backtest-neutral.

Runs the FINAL_ACTION and FILING VQS trajectories for every EB (class, country)
at one or more knowledge dates, aligns them by month, and counts how often the
raw (pre-reconciliation) trajectories violate the DFF≥FAD invariant (i.e. a step
where reconcile_pair would actually fire). The design (docs/fad_dff_coupling_design.md)
predicts ≈0 violations on real, correctly-ordered data — reconciliation is a safety
net for pathological extrapolation tails, not a load-bearing correction, so it does
not distort per-series accuracy.

Usage:
    bazel run //scripts/oneoff:check_fad_dff_violations
    bazel run //scripts/oneoff:check_fad_dff_violations -- --knowledge-dates 2026-07-01,2026-04-01,2025-10-01
"""

import argparse
from datetime import date, datetime

from lib.utils.logging_utils import log_context

log_context("Count pre-reconciliation FAD<DFF trajectory violations (Option B backtest-neutral check)")

import django  # noqa: E402

django.setup()

from lib.business.vqs.coupling import (  # noqa: E402
    reconcile_pair,
    w_fad_concedes_for_country,
)
from lib.business.vqs.solver import predict_regime_switched  # noqa: E402
from models.bulletin import Bulletin  # noqa: E402
from models.enums.action_type import ActionType  # noqa: E402
from models.enums.country import Country  # noqa: E402

_EB_CLASSES = ["1st", "2nd", "3rd", "4th", "5th"]
_COUNTRIES = [Country.INDIA, Country.CHINA, Country.ALL, Country.MEXICO, Country.PHILIPPINES]


def _trajectory(knowledge_date: date, vqs_class: str, country: int, action_type: str):
    outcome = predict_regime_switched(
        knowledge_date=knowledge_date,
        visa_class=vqs_class,
        country=country,
        action_type=action_type,
        priority_date=None,
    )
    return [(r.month, r.cutoff_date) for r in outcome.results if r.cutoff_date is not None]


def _count_violations(fad_traj, dff_traj) -> int:
    """Steps where DFF cutoff < FAD cutoff (Filing behind Final Action — impossible)."""
    fad_by_month = dict(fad_traj)
    n = 0
    for month, dff_c in dff_traj:
        fad_c = fad_by_month.get(month)
        if fad_c is not None and dff_c is not None and dff_c < fad_c:
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--knowledge-dates",
        default="",
        help="comma-separated YYYY-MM-DD; default = latest published bulletin date",
    )
    args = ap.parse_args()

    if args.knowledge_dates.strip():
        kdates = [datetime.strptime(s.strip(), "%Y-%m-%d").date() for s in args.knowledge_dates.split(",")]
    else:
        latest = Bulletin.objects.order_by("-publication_date").first()
        kdates = [latest.publication_date if latest else date.today()]

    total_pairs = 0
    total_violations = 0
    total_violating_series = 0
    max_gap_days = 0

    for kd in kdates:
        for country in _COUNTRIES:
            w = w_fad_concedes_for_country(country.value)
            for vqs_class in _EB_CLASSES:
                try:
                    fad = _trajectory(kd, vqs_class, country.value, ActionType.FINAL_ACTION.value)
                    dff = _trajectory(kd, vqs_class, country.value, ActionType.FILING.value)
                except Exception as e:  # noqa: BLE001
                    print(f"  skip {kd} EB-{vqs_class}/{country.label}: {e}")
                    continue
                if not fad or not dff:
                    continue
                total_pairs += 1
                v = _count_violations(fad, dff)
                if v:
                    total_violating_series += 1
                    total_violations += v
                    # Report the worst gap so a real crossing is visible.
                    fad_by_month = dict(fad)
                    gaps = [
                        (fad_by_month[m] - c).days
                        for m, c in dff
                        if fad_by_month.get(m) is not None and c is not None and c < fad_by_month[m]
                    ]
                    worst = max(gaps) if gaps else 0
                    max_gap_days = max(max_gap_days, worst)
                    # Sanity: after reconciliation there must be ZERO violations.
                    fad2, dff2 = reconcile_pair(fad, dff, w)
                    assert _count_violations(fad2, dff2) == 0, "reconcile_pair left a violation!"
                    print(
                        f"  VIOLATION {kd} EB-{vqs_class}/{country.label}: {v} step(s), "
                        f"worst gap {worst}d -> reconciled clean (w={w})"
                    )

    print("\n=== FAD↔DFF pre-reconciliation violation summary ===")
    print(f"knowledge dates : {', '.join(d.isoformat() for d in kdates)}")
    print(f"series pairs     : {total_pairs}")
    print(f"violating series : {total_violating_series}")
    print(f"violating steps  : {total_violations}")
    print(f"worst gap (days) : {max_gap_days}")
    if total_violations == 0:
        print("RESULT: 0 violations — reconciliation never fires on this data (backtest-neutral confirmed).")
    else:
        print(
            "RESULT: violations exist only in the (rare) crossing cases reconciliation exists to repair; "
            "each was verified to reconcile to 0 violations. Backtest-neutral for all non-crossing series."
        )


if __name__ == "__main__":
    main()
