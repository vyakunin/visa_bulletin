"""Coverage scoring for published 80% prediction intervals.

A stated 80% interval makes two claims, and a single headline coverage number
only checks the first:

1. **Width** — the actual falls inside roughly 80% of the time.
2. **Centring** — the 20% that fall outside split evenly, ~10% below the floor
   and ~10% above the ceiling.

An interval can pass (1) while failing (2) badly, and the failure is invisible
in the headline: over-covering one tail buys coverage that hides an
under-covered opposite tail. So every metric here reports the two tails
separately alongside ``nominal_tail_pct``, the share each tail should hold.

Two further fields describe interval SHAPE rather than outcome, because a
quantile interval built from a zero-inflated error distribution degenerates in
a way that outcome counts alone do not reveal:

* ``degenerate_floor_pct`` — the share of intervals whose floor equals the point
  estimate. Such an interval expresses no downside at all: any move below the
  point estimate is outside it, whatever the stated coverage.
* ``nochange_excluded_pct`` — the share whose interval excludes the no-change
  outcome (the previous actual). This is the concrete "can the interval even
  express 'the series does not move'?" question, and it is only meaningful on
  rows where the caller supplied ``prev_actual``.

Sign convention matches the rest of VQS: a signed error is ``actual -
predicted`` in days, so **positive means the actual came in later than
predicted**, i.e. the series advanced more than the model called.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import mean, median

DEFAULT_COVERAGE = 0.80
FLAT_TOLERANCE_DAYS = 7  # |move| at or under this counts as "no movement"


@dataclass(frozen=True)
class GradedInterval:
    """One graded prediction: the point, its interval, and what happened.

    ``prev_actual`` is the previous month's actual cutoff — the no-change
    outcome, and the anchor a move is measured from. It is optional because the
    first observation of a series has no predecessor; rows without it are
    excluded from the no-change and move statistics but still scored for
    coverage.
    """

    predicted: date
    actual: date
    ci_low: date
    ci_high: date
    prev_actual: date | None = None

    @property
    def signed_error_days(self) -> int:
        return (self.actual - self.predicted).days

    @property
    def covered(self) -> bool:
        return self.ci_low <= self.actual <= self.ci_high

    @property
    def missed_low(self) -> bool:
        return self.actual < self.ci_low

    @property
    def missed_high(self) -> bool:
        return self.actual > self.ci_high


@dataclass(frozen=True)
class CoverageMetrics:
    """Interval scoring for a set of graded predictions. Percentages are 0-100.

    Fields are ``None`` when their denominator is empty.
    """

    n: int
    nominal_coverage_pct: float          # what was claimed, e.g. 80.0
    nominal_tail_pct: float              # what EACH tail should hold, e.g. 10.0
    coverage_pct: float | None
    miss_low_pct: float | None
    miss_high_pct: float | None
    mean_width_days: float | None
    mean_below_days: float | None        # point - floor: room to retrogress
    mean_above_days: float | None        # ceiling - point: room to advance
    degenerate_floor_pct: float | None   # floor == point: no downside expressible
    n_with_anchor: int
    nochange_excluded_pct: float | None
    mean_signed_error_days: float | None
    median_signed_error_days: float | None

    @property
    def tail_imbalance_pts(self) -> float | None:
        """Percentage points by which the high tail exceeds the low tail.

        Zero for a correctly centred interval, whatever its width. Positive
        means the actual overshoots the ceiling more often than it undershoots
        the floor — the point estimate sits too low.
        """
        if self.miss_low_pct is None or self.miss_high_pct is None:
            return None
        return round(self.miss_high_pct - self.miss_low_pct, 1)


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator > 0 else None


def coverage_metrics(
    rows: Sequence[GradedInterval],
    *,
    nominal_coverage: float = DEFAULT_COVERAGE,
) -> CoverageMetrics:
    """Score published intervals against realised actuals.

    ``nominal_coverage`` is the coverage the intervals CLAIMED (0.80 for the
    published 80% band); it sets the reference the tails are judged against and
    is never inferred from the data.
    """
    n = len(rows)
    nominal_pct = round(nominal_coverage * 100, 1)
    tail_pct = round((1.0 - nominal_coverage) / 2.0 * 100, 1)

    if n == 0:
        return CoverageMetrics(
            n=0,
            nominal_coverage_pct=nominal_pct,
            nominal_tail_pct=tail_pct,
            coverage_pct=None,
            miss_low_pct=None,
            miss_high_pct=None,
            mean_width_days=None,
            mean_below_days=None,
            mean_above_days=None,
            degenerate_floor_pct=None,
            n_with_anchor=0,
            nochange_excluded_pct=None,
            mean_signed_error_days=None,
            median_signed_error_days=None,
        )

    covered = sum(r.covered for r in rows)
    low = sum(r.missed_low for r in rows)
    high = sum(r.missed_high for r in rows)
    degenerate = sum(r.ci_low == r.predicted for r in rows)

    anchored = [r for r in rows if r.prev_actual is not None]
    excluded = sum(
        not (r.ci_low <= r.prev_actual <= r.ci_high) for r in anchored
    )

    errors = [r.signed_error_days for r in rows]

    return CoverageMetrics(
        n=n,
        nominal_coverage_pct=nominal_pct,
        nominal_tail_pct=tail_pct,
        coverage_pct=_pct(covered, n),
        miss_low_pct=_pct(low, n),
        miss_high_pct=_pct(high, n),
        mean_width_days=round(mean((r.ci_high - r.ci_low).days for r in rows), 1),
        mean_below_days=round(mean((r.predicted - r.ci_low).days for r in rows), 1),
        mean_above_days=round(mean((r.ci_high - r.predicted).days for r in rows), 1),
        degenerate_floor_pct=_pct(degenerate, n),
        n_with_anchor=len(anchored),
        nochange_excluded_pct=_pct(excluded, len(anchored)),
        mean_signed_error_days=round(mean(errors), 1),
        median_signed_error_days=round(median(errors), 1),
    )


@dataclass(frozen=True)
class FlatCallMetrics:
    """How often the model called "no movement" versus how often that happened.

    Separates the two ways a flat call can be wrong from the one way it can be
    right, because on this data the base rate of genuinely flat months is high
    enough that a permanent flat call scores well on accuracy while carrying no
    information (the same base-rate trap ``direction_metrics`` documents).
    """

    n: int
    called_flat_pct: float | None
    actual_flat_pct: float | None
    called_flat_actual_advanced_pct: float | None
    called_flat_actual_retrogressed_pct: float | None
    called_move_actual_flat_pct: float | None
    mean_predicted_move_days: float | None
    mean_actual_move_days: float | None


def flat_call_metrics(
    rows: Sequence[GradedInterval],
    *,
    flat_tolerance_days: int = FLAT_TOLERANCE_DAYS,
) -> FlatCallMetrics:
    """Score flat-versus-move calls. Only rows carrying ``prev_actual`` count.

    Both moves are measured from the same anchor — the previous actual cutoff —
    so a predicted move and an actual move are directly comparable.
    """
    anchored = [r for r in rows if r.prev_actual is not None]
    n = len(anchored)
    if n == 0:
        return FlatCallMetrics(0, None, None, None, None, None, None, None)

    pred_moves = [(r.predicted - r.prev_actual).days for r in anchored]
    act_moves = [(r.actual - r.prev_actual).days for r in anchored]

    called_flat = [abs(p) <= flat_tolerance_days for p in pred_moves]
    actual_flat = [abs(a) <= flat_tolerance_days for a in act_moves]

    return FlatCallMetrics(
        n=n,
        called_flat_pct=_pct(sum(called_flat), n),
        actual_flat_pct=_pct(sum(actual_flat), n),
        called_flat_actual_advanced_pct=_pct(
            sum(cf and a > flat_tolerance_days for cf, a in zip(called_flat, act_moves)), n
        ),
        called_flat_actual_retrogressed_pct=_pct(
            sum(cf and a < -flat_tolerance_days for cf, a in zip(called_flat, act_moves)), n
        ),
        called_move_actual_flat_pct=_pct(
            sum((not cf) and af for cf, af in zip(called_flat, actual_flat)), n
        ),
        mean_predicted_move_days=round(mean(pred_moves), 1),
        mean_actual_move_days=round(mean(act_moves), 1),
    )
