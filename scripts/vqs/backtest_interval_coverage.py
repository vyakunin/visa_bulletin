"""Score published 80% prediction intervals against realised actuals.

Reads stored ``PredictedCutoff`` rows — the intervals that were actually
served — and reports empirical coverage against the 80% they claimed, with the
two tails separated. A headline coverage number alone cannot distinguish a
correctly-centred interval from one that buys coverage on an over-covered tail
while under-covering the other, which is why every table prints
``low%``/``high%`` beside the nominal 10% each should hold.

This is a pure read of stored predictions: no solver run, no model reload, so
it is safe against a live database and reproduces exactly what was published.

Strata reported:
  * horizon — the published next-month forecast (h=1) is the headline
  * mode — ``forward`` (generated before the target bulletin published) versus
    ``backfilled`` (generated afterwards, so a walk-forward backtest rather
    than a pre-registered forecast). Reported separately; a backfilled row
    still respects knowledge_date inside the solver, but it was never served.
  * model / chart / series

Usage (canonical — against the staging prod-copy DB):
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_interval_coverage
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_interval_coverage --horizon 1 --forward-only
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_interval_coverage --since 2026-05-01 --by-series

Re-run it after each newly graded bulletin month and append the numbers to the
tracking ticket, so the next month compares against a recorded series instead
of re-deriving the baseline.
"""

import argparse
import os
from collections import defaultdict
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from lib.business.vqs.interval_coverage import (  # noqa: E402
    CoverageMetrics,
    FlatCallMetrics,
    GradedInterval,
    coverage_metrics,
    flat_call_metrics,
)
from models.enums.country import Country  # noqa: E402

_CNAME = {
    Country.ALL.value: "ROW",
    Country.CHINA.value: "China",
    Country.INDIA.value: "India",
    Country.MEXICO.value: "Mexico",
    Country.PHILIPPINES.value: "Phil",
}
_EBNAME = {"1st": "EB-1", "2nd": "EB-2", "3rd": "EB-3", "4th": "EB-4", "5th": "EB-5"}

# The six series with a dedicated modelled dispatch. Everything else is served
# by a conservative no-change baseline, so mixing them in reads as model
# quality when it is not.
MODELLED_SERIES = frozenset(
    (vc, c)
    for vc in ("1st", "2nd", "3rd")
    for c in (Country.CHINA.value, Country.INDIA.value)
)


def _series_label(visa_class: str, country: int, action_type: str) -> str:
    chart = "FA" if action_type == "final_action" else "FD"
    return f"{_CNAME.get(country, country)} {_EBNAME.get(visa_class, visa_class)} {chart}"


def _build_anchors() -> dict[tuple[str, int, str, date], date]:
    """Map (series, bulletin month) -> the PREVIOUS month's actual cutoff.

    The anchor a move is measured from. Built from the canonical actuals table
    rather than from stored predictions, so it is unaffected by which months
    happen to have predictions.
    """
    from models.visa_cutoff_date import VisaCutoffDate

    by_series: dict[tuple[str, int, str], list[tuple[date, date]]] = defaultdict(list)
    rows = VisaCutoffDate.objects.filter(cutoff_date__isnull=False).select_related("bulletin")
    for row in rows:
        pub = row.bulletin.publication_date
        if not pub:
            continue
        month = date(pub.year, pub.month, 1)
        by_series[(row.visa_class, row.country, row.action_type)].append((month, row.cutoff_date))

    anchors: dict[tuple[str, int, str, date], date] = {}
    for series, pairs in by_series.items():
        pairs.sort()
        for (month, _cutoff), (_prev_month, prev_cutoff) in zip(pairs[1:], pairs):
            anchors[(*series, month)] = prev_cutoff
    return anchors


def load_rows(
    *,
    horizon: int | None,
    since: date | None,
    forward_only: bool,
    modelled_only: bool,
) -> list[tuple[str, str, str, GradedInterval]]:
    """Return (mode, model_name, series_label, GradedInterval) for graded rows."""
    from models.vqs import PredictedCutoff

    anchors = _build_anchors()
    out: list[tuple[str, str, str, GradedInterval]] = []

    qs = PredictedCutoff.objects.filter(
        actual_date__isnull=False,
        predicted_date__isnull=False,
        confidence_low__isnull=False,
        confidence_high__isnull=False,
    ).select_related("bulletin")

    for row in qs:
        target = row.bulletin.target_bulletin_month
        knowledge = row.bulletin.prediction_date
        if not target or not knowledge:
            continue
        h = (target.year - knowledge.year) * 12 + (target.month - knowledge.month)
        if horizon is not None and h != horizon:
            continue
        if since is not None and target < since:
            continue
        if modelled_only and (row.visa_class, row.country) not in MODELLED_SERIES:
            continue

        generated = row.bulletin.generated_at.date() if row.bulletin.generated_at else None
        mode = "backfilled" if generated and generated > target else "forward"
        if forward_only and mode != "forward":
            continue

        out.append((
            mode,
            row.model_name or "(unset)",
            _series_label(row.visa_class, row.country, row.action_type),
            GradedInterval(
                predicted=row.predicted_date,
                actual=row.actual_date,
                ci_low=row.confidence_low,
                ci_high=row.confidence_high,
                prev_actual=anchors.get((row.visa_class, row.country, row.action_type, target)),
            ),
        ))
    return out


def _print_coverage_table(title: str, groups: dict[str, list[GradedInterval]]) -> None:
    print(f"\n{title}")
    print(f"{'group':<22} {'n':>6} {'cover%':>7} {'low%':>6} {'high%':>6} "
          f"{'width':>6} {'below':>6} {'above':>6} {'flat-floor%':>12} {'medErr':>7}")
    print("-" * 100)
    for name, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        m: CoverageMetrics = coverage_metrics(rows)
        print(f"{name:<22} {m.n:>6} {_f(m.coverage_pct):>7} {_f(m.miss_low_pct):>6} "
              f"{_f(m.miss_high_pct):>6} {_f(m.mean_width_days):>6} {_f(m.mean_below_days):>6} "
              f"{_f(m.mean_above_days):>6} {_f(m.degenerate_floor_pct):>12} "
              f"{_f(m.median_signed_error_days):>7}")


def _print_flat_table(title: str, groups: dict[str, list[GradedInterval]]) -> None:
    print(f"\n{title}")
    print(f"{'group':<22} {'n':>6} {'calledFlat%':>12} {'actualFlat%':>12} "
          f"{'flat->adv%':>11} {'flat->retro%':>13} {'predMove':>9} {'actMove':>8}")
    print("-" * 100)
    for name, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        m: FlatCallMetrics = flat_call_metrics(rows)
        print(f"{name:<22} {m.n:>6} {_f(m.called_flat_pct):>12} {_f(m.actual_flat_pct):>12} "
              f"{_f(m.called_flat_actual_advanced_pct):>11} "
              f"{_f(m.called_flat_actual_retrogressed_pct):>13} "
              f"{_f(m.mean_predicted_move_days):>9} {_f(m.mean_actual_move_days):>8}")


def _f(value: float | None) -> str:
    return "-" if value is None else f"{value}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--horizon", type=int, default=1,
                        help="Prediction horizon in months (default 1; 0 = all horizons)")
    parser.add_argument("--since", type=str, default=None,
                        help="Only target bulletin months on/after YYYY-MM-DD")
    parser.add_argument("--forward-only", action="store_true",
                        help="Only rows generated before their target bulletin published")
    parser.add_argument("--modelled-only", action="store_true",
                        help="Only the six China/India EB-1/2/3 series with a modelled dispatch")
    parser.add_argument("--by-series", action="store_true", help="Break down per series")
    args = parser.parse_args()

    horizon = None if args.horizon == 0 else args.horizon
    since = date.fromisoformat(args.since) if args.since else None

    rows = load_rows(
        horizon=horizon,
        since=since,
        forward_only=args.forward_only,
        modelled_only=args.modelled_only,
    )
    if not rows:
        print("No graded rows with intervals matched the filters.")
        return

    scope = [f"horizon={'all' if horizon is None else horizon}"]
    if since:
        scope.append(f"since={since}")
    if args.forward_only:
        scope.append("forward-only")
    if args.modelled_only:
        scope.append("modelled-only")

    overall = [gi for _, _, _, gi in rows]
    m = coverage_metrics(overall)
    print(f"\n{'=' * 100}")
    print(f"  PUBLISHED-INTERVAL COVERAGE — {', '.join(scope)}")
    print(f"{'=' * 100}")
    print(f"  n={m.n}   claimed coverage {m.nominal_coverage_pct}%   "
          f"each tail should hold {m.nominal_tail_pct}%")
    print(f"  empirical coverage {_f(m.coverage_pct)}%   "
          f"miss low {_f(m.miss_low_pct)}%   miss high {_f(m.miss_high_pct)}%   "
          f"tail imbalance {_f(m.tail_imbalance_pts)} pts")
    print(f"  interval shape: mean width {_f(m.mean_width_days)}d "
          f"({_f(m.mean_below_days)}d below the point, {_f(m.mean_above_days)}d above); "
          f"floor == point on {_f(m.degenerate_floor_pct)}% of rows")
    print(f"  no-change outcome outside the interval on {_f(m.nochange_excluded_pct)}% "
          f"of {m.n_with_anchor} anchored rows")
    print(f"  signed error (actual - predicted): mean {_f(m.mean_signed_error_days)}d, "
          f"median {_f(m.median_signed_error_days)}d")

    by_mode: dict[str, list[GradedInterval]] = defaultdict(list)
    by_model: dict[str, list[GradedInterval]] = defaultdict(list)
    by_series: dict[str, list[GradedInterval]] = defaultdict(list)
    for mode, model, series, gi in rows:
        by_mode[mode].append(gi)
        by_model[model].append(gi)
        by_series[series].append(gi)

    _print_coverage_table("COVERAGE BY MODE (forward = pre-registered, backfilled = backtest)", by_mode)
    _print_coverage_table("COVERAGE BY MODEL", by_model)
    if args.by_series:
        _print_coverage_table("COVERAGE BY SERIES", by_series)

    _print_flat_table("FLAT-CALL SCORING BY MODEL", by_model)
    if args.by_series:
        _print_flat_table("FLAT-CALL SCORING BY SERIES", by_series)
    print()


if __name__ == "__main__":
    main()
