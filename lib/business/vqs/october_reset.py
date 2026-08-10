"""October-reset / U-transition estimator.

When an employment-based category exhausts its fiscal-year annual limit it goes
**Unavailable (U)** and stays U until the October fiscal-year reset (INA §203(b)
annual numerical limits + the October 1 reset — public policy structure, so a
deterministic model is appropriate here per PREDICTIONS_ASSESSMENT §0 design
principle #2).

This module answers the two questions a user staring at an "Unavailable" cell
actually has:

1. **When does a date come back?**  → Structural, high-confidence: the category
   stays Unavailable through September and a cutoff returns on **October 1** when
   the new fiscal-year quota opens.  (No model needed — it's policy.)

2. **Roughly where will it reset to?**  → Genuinely uncertain.  History shows the
   reset can resume near the pre-Unavailable cutoff (2006 EB-2 India: flat) or
   retrogress years (2012 EB-2 India: 2007-08 → 2004-09).  We therefore anchor the
   point estimate on the last real cutoff before the category went Unavailable
   (the neutral "resumes where it left off" persistence anchor) and attach a
   **wide, empirically-calibrated CI** built from the cross-series distribution of
   historical reset moves.  We deliberately do NOT fit a conditional point model
   on the ~2-3 per-series precedents — that is exactly the failure mode of the
   §8 FY-boundary experiment (regressed India EB-2 +46.6d on an 8-point NN model).

The estimator is used by `scripts/publish_predictions.py` (Unavailable branch) and
validated by `scripts/vqs/backtest_october_reset.py` (leave-one-out, walk-forward).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from lib.business.bulletin.eb_series import EB_CLASSES as _EB_CLASSES
from lib.business.bulletin.eb_series import resolve_cutoff_label

# Months in which an active Unavailable state is an end-of-fiscal-year annual-limit
# exhaustion (→ resets in October).  U states earlier in the FY are different
# animals and are not modeled here.
_END_OF_FY_MONTHS = (5, 6, 7, 8, 9)


def _fiscal_year(d: date) -> int:
    """US federal fiscal year for a bulletin month (FY starts October 1)."""
    return d.year + 1 if d.month >= 10 else d.year


@dataclass
class ResetEvent:
    """A historical end-of-FY Unavailable spell with its realized October reset.

    Used both as a backtest label and as a precedent for the CI distribution.
    """

    visa_class: str
    country: int
    action_type: str
    spell_fy: int  # fiscal year that ended Unavailable (reset happens Oct 1 of this year)
    pre_u_cutoff: date  # last real cutoff before the category went Unavailable
    reset_cutoff: date  # first real cutoff at/after Oct 1 of the reset FY
    reset_pub_date: date  # bulletin month the reset cutoff first appeared
    knowledge_date: date  # a date during the spell when we'd be predicting (Sep 1)

    @property
    def delta_days(self) -> int:
        """Signed reset move: reset cutoff minus pre-Unavailable cutoff, in days.

        Negative = retrogressed on reset (e.g. 2012 EB-2 India), positive = advanced.
        """
        return (self.reset_cutoff - self.pre_u_cutoff).days


@dataclass
class OctoberResetEstimate:
    """Result of estimating the October reset for a currently-Unavailable series."""

    is_unavailable: bool
    reset_year: int | None = None  # calendar year of the October reset
    stays_u_through: str = "September"
    pre_u_cutoff: date | None = None
    point: date | None = None
    ci_low: date | None = None
    ci_high: date | None = None
    n_precedents: int = 0
    method: str = "none"
    # Lower bound the State Department published in a bulletin's notes section for
    # this reset, if one was recorded (models.PublishedFloor). None = no statement.
    floor: date | None = None
    floor_source_period: date | None = None
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serializable summary for storage in PredictedCutoff.expert_predictions."""
        return {
            "is_unavailable": self.is_unavailable,
            "reset_year": self.reset_year,
            "stays_u_through": self.stays_u_through,
            "pre_u_cutoff": self.pre_u_cutoff.isoformat() if self.pre_u_cutoff else None,
            "reset_reference": self.pre_u_cutoff.isoformat() if self.pre_u_cutoff else None,
            "n_precedents": self.n_precedents,
            "method": self.method,
            "floor": self.floor.isoformat() if self.floor else None,
            "floor_source_period": (
                self.floor_source_period.isoformat() if self.floor_source_period else None
            ),
            "diagnostics": self.diagnostics,
        }


def _full_series(
    visa_class: str, country: int, action_type: str, as_of: date | None = None
) -> list:
    """All VisaCutoffDate rows for a series (incl. U/C null-cutoff rows), ordered.

    Not cached in data_cache's non-null cache; queried directly (called at
    publish/backtest time, not in the hot solver loop).

    ``visa_class`` is a series key; ``as_of`` picks which published heading it
    resolves to for the keys that have had several (EB-5). The series therefore
    covers one heading's era, so an EB-5 spell that straddles a rename is not
    seen as one run — enumerating the full EB-5 lineage is the open question in
    the EB-4/EB-5 coverage work, not something to infer here.
    """
    from models.visa_cutoff_date import VisaCutoffDate

    label = resolve_cutoff_label(visa_class, action_type, as_of)
    if label is None:
        return []

    return list(
        VisaCutoffDate.objects.filter(
            visa_class=label, country=country, action_type=action_type
        )
        .select_related("bulletin")
        .order_by("bulletin__publication_date")
    )


def _reset_cutoff_after(rows: list, spell_end_idx: int, reset_year: int):
    """First real (non-null) cutoff at/after Oct 1 of ``reset_year``.

    Searches forward from ``spell_end_idx`` up to the following January so a
    missing October bulletin (common pre-2013) falls through to Nov/Dec/Jan.
    Returns (cutoff_date, pub_date) or (None, None).
    """
    horizon_end = date(reset_year + 1, 1, 31)
    for row in rows[spell_end_idx + 1 :]:
        pub = row.bulletin.publication_date
        if pub < date(reset_year, 10, 1):
            continue
        if pub > horizon_end:
            break
        if row.cutoff_date is not None:
            return row.cutoff_date, pub
    return None, None


def find_reset_events(action_type: str = "final_action") -> list[ResetEvent]:
    """Enumerate all historical end-of-FY U→October-reset events across EB series.

    An event requires: a maximal run of Unavailable months reaching into
    July/Aug/Sep of a fiscal year, a real cutoff immediately before the run, and a
    realized real cutoff in the following fiscal year (Oct-Jan). The current
    (unresolved) Unavailable spell has no reset_cutoff yet and is skipped.
    """
    from models.enums.country import Country

    events: list[ResetEvent] = []
    countries = [
        Country.ALL.value,
        Country.CHINA.value,
        Country.INDIA.value,
        Country.MEXICO.value,
        Country.PHILIPPINES.value,
    ]
    for visa_class in _EB_CLASSES:
        for country in countries:
            rows = _full_series(visa_class, country, action_type)
            if not rows:
                continue
            i = 0
            n = len(rows)
            while i < n:
                if not rows[i].is_unavailable:
                    i += 1
                    continue
                # Start of a U run at index i; walk to its end.
                j = i
                while j + 1 < n and rows[j + 1].is_unavailable:
                    j += 1
                run = rows[i : j + 1]
                run_months = {r.bulletin.publication_date.month for r in run}
                touches_fy_end = bool(run_months & {7, 8, 9})
                # Pre-U real cutoff: scan backward from i for a non-null cutoff.
                pre_u = None
                for k in range(i - 1, -1, -1):
                    if rows[k].cutoff_date is not None:
                        pre_u = rows[k].cutoff_date
                        break
                if touches_fy_end and pre_u is not None:
                    # A3-F9: derive the exhausted FY from a fiscal-year-END month
                    # (Jul/Aug/Sep) the spell touches, NOT run[-1]. A U-spell that
                    # extends past September into October has its last month in the
                    # NEXT fiscal year, which pushed the reset search a year forward
                    # and mislabeled the reset event.
                    fy_end_pub = max(
                        r.bulletin.publication_date for r in run
                        if r.bulletin.publication_date.month in (7, 8, 9)
                    )
                    spell_fy = _fiscal_year(fy_end_pub)
                    reset_cut, reset_pub = _reset_cutoff_after(rows, j, spell_fy)
                    if reset_cut is not None:
                        events.append(
                            ResetEvent(
                                visa_class=visa_class,
                                country=country,
                                action_type=action_type,
                                spell_fy=spell_fy,
                                pre_u_cutoff=pre_u,
                                reset_cutoff=reset_cut,
                                reset_pub_date=reset_pub,
                                knowledge_date=date(spell_fy, 9, 1),
                            )
                        )
                i = j + 1
    return events


def _published_floor(
    visa_class: str,
    country: int,
    action_type: str,
    target_period: date,
    knowledge_date: date,
):
    """The published lower bound for this reset, or None.

    Local import so the module keeps loading before Django's app registry is
    ready, matching ``_full_series``. Walk-forward safety lives in the manager:
    a floor is invisible until its source bulletin has published.
    """
    from models.published_floor import PublishedFloor

    return PublishedFloor.objects.floor_for(
        visa_class, country, action_type, target_period, knowledge_date
    )


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]) on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def estimate_from_precedents(
    pre_u_cutoff: date,
    reset_year: int,
    precedents: list[ResetEvent],
    *,
    coverage: float = 0.80,
    apply_median_shift: bool = False,
    floor: date | None = None,
    floor_source_period: date | None = None,
) -> OctoberResetEstimate:
    """Build a reset estimate from a pre-U cutoff + a pool of precedent deltas.

    Point estimate anchors on ``pre_u_cutoff`` (neutral persistence anchor). The
    CI comes from the empirical distribution of precedent reset moves
    (reset_cutoff - pre_u_cutoff). ``apply_median_shift`` optionally nudges the
    point by the median historical delta (evaluated in the backtest; off in prod
    unless it demonstrably beats the pure anchor).

    ``floor`` is a lower bound the State Department published in a bulletin's
    notes section (models.PublishedFloor). The precedent pool is empirical and
    cross-series, so on its own it can — and for October 2026 EB-2 India does —
    put the outcome DOS called likely outside its own 80% band. A floor is applied
    by **truncating the distribution**: every precedent outcome below it is moved
    up to it, and the point estimate cannot sit below it either. Truncation rather
    than a shift, because the statement bounds the outcome from below and says
    nothing about the upside — so the spread above the floor stays whatever the
    precedents supported, and a floor that does not bind changes nothing at all.

    Everything is computed in delta space, so ``floor=None`` is exactly the
    pre-floor arithmetic.
    """
    from datetime import timedelta

    deltas = sorted(float(e.delta_days) for e in precedents)

    floor_delta: float | None = None
    n_below_floor = 0
    if floor is not None:
        floor_delta = float((floor - pre_u_cutoff).days)
        n_below_floor = sum(1 for d in deltas if d < floor_delta)
        deltas = sorted(max(d, floor_delta) for d in deltas)

    def _floor_diagnostics() -> dict:
        if floor is None:
            return {}
        return {
            "floor_date": floor.isoformat(),
            "floor_source_period": (
                floor_source_period.isoformat() if floor_source_period else None
            ),
            "floor_delta_days": round(floor_delta),
            "n_precedents_below_floor": n_below_floor,
        }

    n = len(deltas)
    if n == 0:
        # No precedents: structural statement only, point = anchor, no CI.
        point = pre_u_cutoff
        if floor is not None and floor > point:
            point = floor
        return OctoberResetEstimate(
            is_unavailable=True,
            reset_year=reset_year,
            pre_u_cutoff=pre_u_cutoff,
            point=point,
            n_precedents=0,
            method="anchor_no_ci_floored" if floor is not None else "anchor_no_ci",
            floor=floor,
            floor_source_period=floor_source_period,
            diagnostics=_floor_diagnostics(),
        )

    median_delta = statistics.median(deltas)
    shift = median_delta if apply_median_shift else 0.0
    if floor_delta is not None:
        shift = max(shift, floor_delta)
    point = pre_u_cutoff + timedelta(days=round(shift))

    tail = (1.0 - coverage) / 2.0
    lo_delta = _percentile(deltas, tail)
    hi_delta = _percentile(deltas, 1.0 - tail)
    ci_low = pre_u_cutoff + timedelta(days=round(lo_delta))
    ci_high = pre_u_cutoff + timedelta(days=round(hi_delta))

    if floor is not None:
        method = "anchor_floored"
    elif apply_median_shift:
        method = "anchor_median_shift"
    else:
        method = "anchor"

    return OctoberResetEstimate(
        is_unavailable=True,
        reset_year=reset_year,
        pre_u_cutoff=pre_u_cutoff,
        point=point,
        ci_low=ci_low,
        ci_high=ci_high,
        n_precedents=n,
        method=method,
        floor=floor,
        floor_source_period=floor_source_period,
        diagnostics={
            "median_delta_days": round(median_delta),
            "lo_delta_days": round(lo_delta),
            "hi_delta_days": round(hi_delta),
            "min_delta_days": round(deltas[0]),
            "max_delta_days": round(deltas[-1]),
            # p10/p90 describe the historical spread of resets for user-facing copy;
            # they are NOT a calibrated prediction interval (backtest coverage of an
            # 80% band is only ~25-37% — the reset is regime-dependent). See
            # scripts/vqs/backtest_october_reset.py.
            "p10_delta_days": round(lo_delta),
            "p90_delta_days": round(hi_delta),
            **_floor_diagnostics(),
        },
    )


def estimate_october_reset(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    *,
    coverage: float = 0.80,
    apply_median_shift: bool = False,
    all_events: list[ResetEvent] | None = None,
) -> OctoberResetEstimate:
    """Estimate the October reset for a series that is Unavailable at knowledge_date.

    Walk-forward safe: only precedent events whose reset was already published
    strictly before ``knowledge_date`` are pooled into the CI distribution.
    Returns ``is_unavailable=False`` if the series is not an end-of-FY U at
    ``knowledge_date`` (caller should then fall through to its normal path).
    """
    from lib.business.vqs.data_cache import _latest_full_entry_at_date

    if visa_class not in _EB_CLASSES:
        return OctoberResetEstimate(is_unavailable=False)

    entry = _latest_full_entry_at_date(visa_class, country, action_type, knowledge_date)
    if not entry or not entry.is_unavailable:
        return OctoberResetEstimate(is_unavailable=False)
    if knowledge_date.month not in _END_OF_FY_MONTHS:
        # Unavailable but not an end-of-FY exhaustion — not our case.
        return OctoberResetEstimate(is_unavailable=False)

    reset_year = _fiscal_year(knowledge_date)  # Oct 1 of this year opens the new FY

    # Pre-U cutoff: last real cutoff strictly before the current U spell. Resolve
    # the heading as of the knowledge date so a backtest reads the series the way
    # it was published then, matching the entry checked just above.
    rows = _full_series(visa_class, country, action_type, as_of=knowledge_date)
    pre_u_cutoff = None
    in_current_u = False
    for row in reversed(rows):
        if row.bulletin.publication_date > knowledge_date:
            continue
        if row.is_unavailable:
            in_current_u = True
            continue
        if in_current_u and row.cutoff_date is not None:
            pre_u_cutoff = row.cutoff_date
            break
    if pre_u_cutoff is None:
        return OctoberResetEstimate(
            is_unavailable=True, reset_year=reset_year, method="no_anchor"
        )

    if all_events is None:
        all_events = find_reset_events(action_type)
    precedents = [
        e
        for e in all_events
        if e.reset_pub_date < knowledge_date
        and not (
            e.visa_class == visa_class
            and e.country == country
            and e.spell_fy == reset_year
        )
    ]

    floor_row = _published_floor(
        visa_class, country, action_type, date(reset_year, 10, 1), knowledge_date
    )

    return estimate_from_precedents(
        pre_u_cutoff,
        reset_year,
        precedents,
        coverage=coverage,
        apply_median_shift=apply_median_shift,
        floor=floor_row.floor_date if floor_row else None,
        floor_source_period=(
            floor_row.source_bulletin.publication_date if floor_row else None
        ),
    )


def _fmt_month(d: date) -> str:
    return d.strftime("%B %-d, %Y")


def describe_reset(est: OctoberResetEstimate, series_label: str) -> str:
    """Honest markdown explainer for a currently-Unavailable EB series.

    Leads with the structural certainty (stays U through September, resets
    October 1 — policy) and gives the pre-Unavailable cutoff as a labelled
    *reference point*, not a prediction, with a plain-language note that the
    reset magnitude is genuinely uncertain (history: near-flat to multi-year
    retrogression). Deliberately does NOT assert a precise reset date or a
    calibrated CI — the backtest shows neither is reliable.

    Where the State Department has published a floor for this reset, the floor
    leads and the historical-spread caveat is dropped: quoting a precedent that
    retrogressed below a bound State has already announced contradicts the rest
    of the same paragraph.
    """
    reset_year = est.reset_year
    parts: list[str] = []
    parts.append(
        f"**{series_label} is Unavailable** — it reached its fiscal-year annual "
        f"limit (INA §203(b) numerical caps)."
    )
    if reset_year:
        parts.append(
            f"It is expected to stay Unavailable through **September {reset_year}**; "
            f"a cutoff date returns on **October 1, {reset_year}**, when the new "
            f"fiscal year's visa quota opens."
        )
    if est.floor:
        source = ""
        if est.floor_source_period:
            source = f" the {est.floor_source_period.strftime('%B %Y')} bulletin's notes say"
        parts.append(
            f"The State Department has published a floor for this reset:{source} "
            f"the date is expected to advance to **at least "
            f"{_fmt_month(est.floor)}**. The forecast below is bounded by that "
            f"statement, which is a lower bound rather than a guarantee — State "
            f"ties it to demand and to the new fiscal year's limits."
        )
        return " ".join(parts)
    if est.pre_u_cutoff:
        ref = _fmt_month(est.pre_u_cutoff)
        note = (
            f"Where it resets to is uncertain. For reference, the last cutoff before "
            f"it went Unavailable was **{ref}**."
        )
        # If precedents show meaningful downside, name the historical range honestly.
        p10 = est.diagnostics.get("p10_delta_days")
        if p10 is not None and p10 < -120:
            note += (
                " Historically the October reset for an exhausted category has ranged "
                "from near that date to a retrogression of a year or more (EB-2 India "
                "reset about three years earlier in 2012), so treat any specific "
                "October date as a rough guess."
            )
        else:
            note += (
                " Historically the October reset has landed anywhere from near that "
                "date to a retrogression of a year or more, so treat any specific "
                "October date as a rough guess."
            )
        parts.append(note)
    return " ".join(parts)
