"""Employment-based series keys, and the DB label each one is published under.

Two distinct identifiers exist for an employment-based preference category, and
conflating them is the defect this module removes:

* the **series key** — ``"1st"``..``"5th"``. Stable, internal, and what every
  model, prediction row (``PredictedCutoff.visa_class``) and grid row is keyed
  by. It never changes.
* the **cutoff label** — ``VisaCutoffDate.visa_class``, which stores whatever
  string the Department of State printed in that month's bulletin.

For EB-1..EB-4 the two coincide. For **EB-5 they never do in a modern bulletin**:
the State Department prints the sub-category in the row heading and has renamed
it roughly every two to three years, most recently in January 2025.

    5th                                                  ...2011-04
    5th Regional Center (I5 and R5) / Non-Regional...    2015-09..2022-04
    5th Unreserved (I5 and R5) / (C5, T5, and all others)        2022-05
    5th Unreserved (including C5, T5, I5, R5)            2022-06..2024-12
    5th Unreserved (including C5, T5, I5, R5, NU, RU)    2025-01..        (final action)
    5th Unreserved (including C5, T5, I5, R5)            2022-06..        (filing)

The label also differs **by action type** on the same bulletin: the final-action
chart carries the NU/RU set-aside carryover in its heading and the filing chart
does not, so a caller must say which chart it wants.

Hardcoding the current literal is what created the bug this module fixes, and it
fails silently: a label that matches nothing returns no row rather than raising,
so a stale key reads as "no backlog → Current" and serves a fifteen-year-old row
as today's answer. So the live label is **resolved from the data** instead —
``resolve_cutoff_label`` asks the bulletins themselves which heading was in use,
and the next rename is picked up without a code change.
"""

from __future__ import annotations

from datetime import date

# Canonical employment-based series keys, in display order. The single owner:
# every module that iterates or labels EB preferences imports these rather than
# re-typing the set (they had drifted into three shapes across three modules).
EB_CLASSES: tuple[str, ...] = ("1st", "2nd", "3rd", "4th", "5th")

# Short display label per series key.
EB_SHORT_LABELS: dict[str, str] = {
    "1st": "EB-1",
    "2nd": "EB-2",
    "3rd": "EB-3",
    "4th": "EB-4",
    "5th": "EB-5",
}

# Series whose published cutoff label is NOT the series key. The value is the
# heading prefix that identifies the chart across renames — deliberately a
# prefix, not a full label, so a rename inside the family still resolves.
#
# EB-5 maps to the *Unreserved* row: the residual category that carries the
# ordinary (non-set-aside) EB-5 queue, and the one a single "EB-5" row means.
# The Rural / High Unemployment / Infrastructure set-asides are separate charts
# and are deliberately NOT folded in here.
_LABEL_PREFIX_BY_SERIES: dict[str, str] = {"5th": "5th Unreserved"}

# (series_key, action_type, as_of) -> resolved label. See resolve_cutoff_label
# for the staleness contract.
_LABEL_CACHE: dict[tuple[str, str, date | None], str | None] = {}


def clear_label_cache() -> None:
    """Drop memoized label resolutions (tests, and after a re-ingest)."""
    _LABEL_CACHE.clear()


def is_data_resolved(series_key: str) -> bool:
    """True when this series' cutoff label must be looked up rather than assumed."""
    return series_key in _LABEL_PREFIX_BY_SERIES


def resolve_cutoff_label(
    series_key: str, action_type: str, as_of: date | None = None
) -> str | None:
    """The ``VisaCutoffDate.visa_class`` value this series was published under.

    ``as_of`` selects the bulletin month to answer for, so a historical query
    resolves to the heading that was in use *then* rather than today's. ``None``
    means "the most recent heading on record".

    Returns ``None`` only when the series has no published row at all at
    ``as_of`` — a genuine break in the data contract. Callers must treat that as
    missing data and surface nothing, never as a Current/no-backlog answer.

    Memoized per process. The cache key includes ``as_of``, so a long-lived
    worker that passes a concrete bulletin date picks up a rename on the first
    request after the new bulletin lands. The ``as_of=None`` entry is only as
    fresh as the process — matching the contract ``data_cache`` already has for
    its own series caches, and only reached from the short-lived publish and
    backtest scripts.
    """
    prefix = _LABEL_PREFIX_BY_SERIES.get(series_key)
    if prefix is None:
        # EB-1..EB-4 (and every family-sponsored class) are published under the
        # series key itself.
        return series_key

    cache_key = (series_key, action_type, as_of)
    if cache_key in _LABEL_CACHE:
        return _LABEL_CACHE[cache_key]

    from models.visa_cutoff_date import VisaCutoffDate

    qs = VisaCutoffDate.objects.filter(
        visa_class__startswith=prefix, action_type=action_type
    )
    if as_of is not None:
        qs = qs.filter(bulletin__publication_date__lte=as_of)
    # Newest bulletin first. The `-visa_class` tiebreak only bites on 2022-05,
    # the single month DOS split Unreserved across two headings; picking one
    # deterministically beats double-counting the month.
    label = (
        qs.order_by("-bulletin__publication_date", "-visa_class")
        .values_list("visa_class", flat=True)
        .first()
    )
    _LABEL_CACHE[cache_key] = label
    return label


def series_key_for_label(label: str) -> str | None:
    """The series key a published cutoff heading belongs to.

    The inverse of :func:`resolve_cutoff_label`, and pure: a row carries its own
    heading, so re-keying a set of rows onto series keys needs no bulletin date
    and no query.

    Returns ``None`` for a heading outside the five preference series. An EB-5
    *set-aside* chart (Rural, High Unemployment, Infrastructure) is its own
    category and is deliberately not folded into ``"5th"``, which means the
    residual (Unreserved) queue only.
    """
    for key, prefix in _LABEL_PREFIX_BY_SERIES.items():
        if label.startswith(prefix):
            return key
    return label if label in EB_CLASSES else None


# Why a series' published history starts when it does, for a page that shows it
# beside EB-1/2/3's much longer run. Owned here, next to the heading table above
# that is the reason.
_WINDOW_NOTE_BY_SERIES: dict[str, str] = {
    "5th": (
        "when the bulletin began publishing a separate unreserved EB-5 row; the "
        "earlier regional-center rows are a different split, not a rename"
    ),
}


def window_note(series_key: str) -> str | None:
    """Why this series' published history starts where it does, or ``None``.

    Reads as a clause after "scored from <month>", so it starts with "when".
    """
    return _WINDOW_NOTE_BY_SERIES.get(series_key)


def cutoff_label_q(series_keys):
    """A ``VisaCutoffDate`` filter matching these series under every heading.

    ``visa_class__in=("1st", ..., "5th")`` is the shape that silently drops
    EB-5: it matches the bare ``"5th"`` era that ended in April 2011 and nothing
    since. Filter with this instead, then re-key each row through
    :func:`series_key_for_label`.
    """
    from django.db.models import Q

    keys = list(series_keys)
    q = Q(visa_class__in=keys)
    for key in keys:
        prefix = _LABEL_PREFIX_BY_SERIES.get(key)
        if prefix:
            q |= Q(visa_class__startswith=prefix)
    return q
