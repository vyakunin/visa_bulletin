"""Backtest the October-reset / U-transition estimator (leave-one-out, walk-forward).

For every historical end-of-FY Unavailable spell (across EB-1..5 × ROW/China/
India/Mexico/Philippines), compare candidate reset estimators against the realized
October reset cutoff:

  * persist_u   — the trivial "it stays Unavailable" baseline (no numeric reset;
                  scored as the worst-case error = |reset - pre_u_cutoff| only for
                  reference, since a U-persister emits no date).
  * anchor      — reset = pre-Unavailable cutoff (neutral persistence anchor).
  * anchor+med  — anchor shifted by the leave-one-out median historical delta.

Reports MAE (days) per estimator and empirical 80% CI coverage for the anchor
model. Adopt the reset estimate in production only if the anchor is at least
competitive with the naive baseline (per the ticket acceptance gate).

Usage (via the staging runner):
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_october_reset
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_october_reset --action-type filing
"""

import argparse
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()


from lib.business.vqs.october_reset import (
    ResetEvent,
    estimate_from_precedents,
    find_reset_events,
)
from models.enums.country import Country

_CNAME = {
    Country.ALL.value: "ROW",
    Country.CHINA.value: "China",
    Country.INDIA.value: "India",
    Country.MEXICO.value: "Mexico",
    Country.PHILIPPINES.value: "Phil",
}
_EBNAME = {"1st": "EB-1", "2nd": "EB-2", "3rd": "EB-3", "4th": "EB-4", "5th": "EB-5"}


def _label(e: ResetEvent) -> str:
    return f"{_CNAME.get(e.country, e.country)} {_EBNAME.get(e.visa_class, e.visa_class)} FY{e.spell_fy}"


def run(action_type: str, exclude_2007: bool) -> None:
    events = find_reset_events(action_type)
    if exclude_2007:
        events = [e for e in events if e.spell_fy != 2007]
    events.sort(key=lambda e: (e.reset_pub_date, e.country, e.visa_class))

    print(f"\n{'=' * 96}")
    print(f"  OCTOBER-RESET BACKTEST — action_type={action_type}"
          f"{'  (excl FY2007 mass-U)' if exclude_2007 else ''}")
    print(f"  {len(events)} historical end-of-FY U->reset events")
    print(f"{'=' * 96}")
    header = (f"{'Event':<22} {'pre-U cutoff':<13} {'actual reset':<13} "
              f"{'delta':>7} {'anchorErr':>9} {'a+medErr':>9} {'in80CI':>7}")
    print(header)
    print("-" * len(header))

    err_anchor: list[int] = []
    err_shift: list[int] = []
    err_persist: list[int] = []  # |reset - pre_u| == anchorErr, kept for parity note
    covered = 0
    scored = 0

    for e in events:
        # Leave-one-out, walk-forward: precedents = other events whose reset was
        # published strictly before THIS event's knowledge date.
        precedents = [
            p
            for p in events
            if p is not e
            and p.reset_pub_date < e.knowledge_date
        ]
        est_anchor = estimate_from_precedents(
            e.pre_u_cutoff, e.spell_fy, precedents, apply_median_shift=False
        )
        est_shift = estimate_from_precedents(
            e.pre_u_cutoff, e.spell_fy, precedents, apply_median_shift=True
        )
        a_err = abs((est_anchor.point - e.reset_cutoff).days)
        s_err = abs((est_shift.point - e.reset_cutoff).days)
        err_anchor.append(a_err)
        err_shift.append(s_err)
        err_persist.append(a_err)

        in_ci = ""
        if est_anchor.ci_low and est_anchor.ci_high:
            scored += 1
            if est_anchor.ci_low <= e.reset_cutoff <= est_anchor.ci_high:
                covered += 1
                in_ci = "yes"
            else:
                in_ci = "NO"

        print(f"{_label(e):<22} {str(e.pre_u_cutoff):<13} {str(e.reset_cutoff):<13} "
              f"{e.delta_days:>6}d {a_err:>8}d {s_err:>8}d {in_ci:>7}")

    def mae(xs: list[int]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    print("-" * len(header))
    print(f"\n  MAE anchor (reset=pre-U cutoff):        {mae(err_anchor):8.1f}d")
    print(f"  MAE anchor + LOO-median-delta shift:    {mae(err_shift):8.1f}d")
    if scored:
        print(f"  80% CI coverage (anchor):               {covered}/{scored} "
              f"= {100.0 * covered / scored:.0f}%  (target 75-85%)")
    print(f"\n  n={len(events)}  "
          f"(events with >=1 walk-forward precedent get a CI; earliest events have none)")
    # Median absolute delta = a size sense of the reset move.
    deltas = sorted(abs(e.delta_days) for e in events)
    if deltas:
        print(f"  median |reset move| across events:      {deltas[len(deltas) // 2]:.0f}d")


def main() -> None:
    ap = argparse.ArgumentParser(description="October-reset estimator backtest")
    ap.add_argument("--action-type", default="final_action")
    ap.add_argument("--exclude-2007", action="store_true",
                    help="Drop the FY2007 mass-Unavailable outlier regime")
    args = ap.parse_args()
    run(args.action_type, exclude_2007=False)
    if not args.exclude_2007:
        run(args.action_type, exclude_2007=True)


if __name__ == "__main__":
    main()
