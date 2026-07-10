"""FAD↔DFF reconciliation (Option B — constrained, confidence-weighted).

The Visa Bulletin publishes two cutoffs per (category, country): the Final
Action Date (FAD) and the Dates-for-Filing (DFF). By construction the Filing
cutoff is at-or-ahead of the Final Action cutoff — i.e. ``DFF cutoff ≥ FAD
cutoff`` at every bulletin (419/419 paired historical observations since
2020-10 show zero violations). Equivalently a priority date matures for Filing
no later than for Final Action (``DFF maturity ≤ FAD maturity``).

VQS forecasts FAD and DFF as two fully independent runs, so nothing enforces the
invariant. In pathological extrapolation tails the two independent trajectories
can cross (the DFF cutoff falling below FAD's), producing the user-visible
ordering bug reported via r/USCIS (2026-07-05: EB-1 India, PD 2025-04-29, Final
Action ~2027 vs Filing ~2029). This module is the **single source of truth** for
repairing such crossings, imported by every display/consumer surface so no site
is missed. See ``docs/fad_dff_coupling_design.md``.

Reconciliation projects any violating pair onto the feasible region, splitting
the correction by each series' relative reliability (a confidence weight ``w``)::

    if DFF_t < FAD_t:                      # cutoff-space violation
        gap    = FAD_t - DFF_t
        FAD_t' = FAD_t - w*gap             # FAD concedes a w share (moves earlier)
        DFF_t' = DFF_t + (1-w)*gap         # DFF concedes a (1-w) share (moves later)
        # they meet at FAD_t - w*gap, so DFF_t' == FAD_t' -> invariant holds (equal)

``w`` is ``w_fad_concedes`` ∈ [0, 1] — the share of the gap the FAD series gives up:

* ``w = 1``  → FAD moves fully onto DFF; DFF untouched  (**trust the DFF series**)
* ``w = 0``  → DFF moves fully onto FAD; FAD untouched  (**trust the FAD series** —
  this is the direction of the legacy scalar maturity clamp this generalizes)
* ``w = 0.5`` → meet in the middle (symmetric; neither series trusted over the other)

Per-series ``w`` is empirically motivated (docs table): India's DFF is the smooth
series and FAD is the jumpy one (mean |ΔFAD| ≫ |ΔDFF|), so India trusts DFF
(``w → 1``); China's two series co-move at similar magnitudes, so China is
symmetric (``w = 0.5``). Because ``DFF ≥ FAD`` holds across ALL real history,
reconciliation NEVER fires on correctly-ordered forecasts — it is a safety net
for extrapolation artifacts, so the per-series ``w`` choice is immaterial to
backtest accuracy and only shapes the rare pathological tail. Every choice of
``w`` guarantees the invariant by construction.

This module is a pure function of its inputs (no Django/ORM); the only import is
the ``Country`` enum for the per-country ``w`` lookup.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# ---------------------------------------------------------------------------
# Per-country confidence weight
# ---------------------------------------------------------------------------
# ``w_fad_concedes`` = share of a violation the FAD (Final Action) series concedes.
# India: DFF is smooth, FAD is jumpy -> trust DFF, concede FAD -> 1.0.
# China: the two co-move -> symmetric -> 0.5.
# Everyone else: symmetric default. The invariant holds for any value in [0, 1];
# this table only shapes which series absorbs a (rare) pathological crossing.
_DEFAULT_W_FAD_CONCEDES = 0.5

# The value that reproduces the legacy scalar maturity clamp's direction
# (Final Action is the binding upper bound; Filing is pulled onto it).
LEGACY_CLAMP_W = 0.0

# A trajectory is a list of (month, cutoff) pairs. ``cutoff`` may be None
# ("unavailable" / not yet projected) and is passed through untouched.
Trajectory = list[tuple[date, date | None]]


@lru_cache(maxsize=1)
def _w_table() -> dict[int, float]:
    # Imported lazily so the pure reconcile helpers are usable without Django
    # configured (and so the module is import-safe outside a Django context).
    from models.enums.country import Country

    return {
        Country.INDIA.value: 1.0,
        Country.CHINA.value: 0.5,
    }


def w_fad_concedes_for_country(country: int) -> float:
    """Confidence weight for a country: share of a FAD↔DFF gap the FAD side concedes."""
    return _w_table().get(int(country), _DEFAULT_W_FAD_CONCEDES)


def _split(fad: date, dff: date, w_fad_concedes: float) -> tuple[date, date]:
    """Reconcile one aligned cutoff pair so ``dff >= fad``. No-op if already ordered.

    Uses exact integer-day arithmetic: the two sides meet at a single day, so the
    result is ``dff' == fad'`` on a violation (no rounding drift can leave a residual
    violation). ``w`` is clamped to [0, 1] defensively.
    """
    if dff >= fad:
        return fad, dff
    w = 0.0 if w_fad_concedes < 0.0 else 1.0 if w_fad_concedes > 1.0 else w_fad_concedes
    gap = (fad - dff).days  # > 0
    fad_shift = round(w * gap)  # FAD moves earlier by this many days
    fad2 = fad - timedelta(days=fad_shift)
    dff2 = dff + timedelta(days=gap - fad_shift)  # meets fad2 exactly
    return fad2, dff2


def reconcile_pair(
    fad_traj: Trajectory,
    dff_traj: Trajectory,
    w_fad_concedes: float,
) -> tuple[Trajectory, Trajectory]:
    """Reconcile two month-aligned cutoff trajectories so ``DFF ≥ FAD`` at every step.

    Trajectories are ``[(month, cutoff), ...]``; alignment is by ``month``. A month
    present in only one trajectory, or whose cutoff is None on either side, passes
    through untouched. Input order is preserved in each returned trajectory.

    Returns ``(fad', dff')``. On any violated month the two sides meet exactly, so
    ``dff'_t >= fad'_t`` holds for every month present in both with non-None cutoffs.
    """
    fad_by_month = dict(fad_traj)
    dff_by_month = dict(dff_traj)
    fad_out = dict(fad_by_month)
    dff_out = dict(dff_by_month)

    for month, fad_c in fad_by_month.items():
        dff_c = dff_by_month.get(month)
        if fad_c is None or dff_c is None:
            continue
        fad_out[month], dff_out[month] = _split(fad_c, dff_c, w_fad_concedes)

    return (
        [(m, fad_out[m]) for m, _ in fad_traj],
        [(m, dff_out[m]) for m, _ in dff_traj],
    )


def reconcile_maturity(
    fad_maturity: date | None,
    dff_maturity: date | None,
    w_fad_concedes: float,
) -> tuple[date | None, date | None]:
    """Reconcile a scalar maturity pair so ``DFF maturity ≤ FAD maturity``.

    The maturity-space mirror of :func:`reconcile_pair` — a priority date matures
    for Filing no later than for Final Action. Used for the linear-extrapolation
    tails, whose maturity is projected *beyond* the trajectory horizon and so is not
    covered by trajectory reconciliation. ``None`` (unknown maturity) passes through.

    ``w`` is again ``w_fad_concedes``: ``w = 1`` moves FAD (concede FAD, keep the
    smooth DFF); ``w = 0`` moves DFF onto FAD (the legacy clamp direction).
    """
    if fad_maturity is None or dff_maturity is None:
        return fad_maturity, dff_maturity
    if dff_maturity <= fad_maturity:
        return fad_maturity, dff_maturity
    w = 0.0 if w_fad_concedes < 0.0 else 1.0 if w_fad_concedes > 1.0 else w_fad_concedes
    gap = (dff_maturity - fad_maturity).days  # > 0 (Filing maturing later == violation)
    fad_shift = round(w * gap)  # FAD maturity moves LATER by this
    fad2 = fad_maturity + timedelta(days=fad_shift)
    dff2 = dff_maturity - timedelta(days=gap - fad_shift)  # meets fad2 exactly
    return fad2, dff2
