"""Direction metrics for cutoff-movement predictions, including the null baseline.

Direction accuracy on visa-bulletin movements is dominated by a lopsided class
mix: ~90% of months that move by more than a month are ADVANCES (measured
2016-2026 across the six focus series, both charts). So the headline
"conditional direction accuracy" — the share of moving months where the
predicted sign matched — is beatable by the constant rule "always say advance",
and a model scoring 69% is not showing skill; it is 21 points BEHIND that
one-line heuristic.

Two fields make this impossible to misread:

* ``cond_up_rate`` — the share of moving months that advanced, i.e. exactly the
  score the constant "always advance" classifier achieves. It is the null
  baseline ``cond_direction_acc`` must clear.
* ``bal_direction_acc`` — mean of advance recall and retrogression recall. Any
  constant classifier scores 50% on it regardless of the class mix, so this is
  the number that measures direction SKILL. It is also the metric aligned with
  what users need: a retrogression is the event that hurts, and a model that
  never predicts one has zero recall on it however good its headline looks.

Used by ``scripts/vqs/evaluate_model.py``; suitable for any harness scoring a
predicted move against an actual one.
"""

from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_MOVE_MIN = 30  # a month "moved" when |actual move| exceeds this


@dataclass(frozen=True)
class MovePair:
    """One scored month: the actual move and the predicted move, both in days.

    Both are measured from the same anchor by the caller (``evaluate_model``
    anchors on the previous month's actual cutoff).
    """

    actual_days: int
    predicted_days: int


@dataclass(frozen=True)
class DirectionMetrics:
    """Direction scoring for a set of scored months. Percentages are 0-100.

    Fields are ``None`` when the denominator is empty (e.g. ``retro_recall``
    for a series that never retrogressed in the window).
    """

    cond_n: int                          # months with |actual move| > move_min
    retro_n: int                         # of those, how many were retrogressions
    cond_direction_acc: float | None     # share of cond_n with the sign called right
    cond_up_rate: float | None           # share of cond_n that advanced = the null baseline
    advance_recall: float | None         # advances called correctly
    retro_recall: float | None           # retrogressions called correctly
    bal_direction_acc: float | None      # mean of the two recalls; constant classifier = 50%
    pred_up_share: float | None          # share of ALL scored months called an advance


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator > 0 else None


def direction_metrics(
    pairs: Sequence[MovePair], *, move_min: int = DEFAULT_MOVE_MIN
) -> DirectionMetrics:
    """Score predicted move directions against actual ones.

    A prediction is "correct" when its move has the same sign as the actual
    move; a zero predicted move is never correct (it expresses no direction),
    which is why persistence scores ~0% here by construction.
    """
    cond_n = up_n = up_ok = down_n = down_ok = cond_ok = pred_up = 0

    for pair in pairs:
        if pair.predicted_days > move_min:
            pred_up += 1
        if abs(pair.actual_days) <= move_min:
            continue

        cond_n += 1
        correct = (pair.predicted_days > 0) == (pair.actual_days > 0) and pair.predicted_days != 0
        if correct:
            cond_ok += 1
        if pair.actual_days > 0:
            up_n += 1
            up_ok += int(correct)
        else:
            down_n += 1
            down_ok += int(correct)

    balanced = None
    if up_n > 0 and down_n > 0:
        balanced = round((up_ok / up_n + down_ok / down_n) / 2 * 100, 1)

    return DirectionMetrics(
        cond_n=cond_n,
        retro_n=down_n,
        cond_direction_acc=_pct(cond_ok, cond_n),
        cond_up_rate=_pct(up_n, cond_n),
        advance_recall=_pct(up_ok, up_n),
        retro_recall=_pct(down_ok, down_n),
        bal_direction_acc=balanced,
        pred_up_share=_pct(pred_up, len(pairs)),
    )
