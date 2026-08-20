"""Shape VQS accuracy metrics into the small display dicts the public
prediction pages surface: the per-month recap rollup banner and the archive
index scorecard + all-time track-record teasers.

The heavy accuracy computation lives in ``accuracy_metrics.py``; this module
only *shapes* it and keeps the request path cheap:

* the per-month recap banner is built from the recap page's already-computed
  ``matrix`` (zero extra queries, and it mirrors exactly the grid the reader
  sees below it), and
* the archive-index scorecard + all-time track record are built from STORED
  predictions (``PredictedCutoff`` — no request-time solver) and cached.

Every number here traces back to ``compute_bulletin_accuracy_summary`` /
``compare_to_no_change_baseline`` over real ``BulletinAccuracyRow`` objects —
nothing is hardcoded or estimated. Per ``docs``/methodology we never surface a
single sitewide "X% accurate": the shapes below are per-category error bands +
an explicit model-vs-no-change comparison (both means shown), so an unflattering
month or an at-baseline track record reads honestly rather than being dressed up.
"""

import logging
from collections import defaultdict
from datetime import date

from lib.business.bulletin.eb_series import (
    EB_CLASSES,
    EB_SHORT_LABELS,
    cutoff_label_q,
    series_key_for_label,
    window_note,
)
from lib.business.vqs.accuracy_metrics import (
    QUEUE_DRIVEN_CLASSES,
    BulletinAccuracyRow,
    compare_to_no_change_baseline,
    compute_bulletin_accuracy_summary,
)

logger = logging.getLogger(__name__)

# Scored EB series in display order: WHICH classes score is owned by
# accuracy_metrics (EB-4 is policy-driven, not queue-driven), the ORDER by
# eb_series, and the display label by eb_series.EB_SHORT_LABELS.
_EB_SCORED_CLASSES = [c for c in EB_CLASSES if c in QUEUE_DRIVEN_CLASSES]
_ACTION_TYPES = ("final_action", "filing")
_CACHE_TTL_S = 60 * 60 * 24


def _bands(
    rows: list[BulletinAccuracyRow], class_display: dict[str, str]
) -> list[dict]:
    """Per-category error bands, each carrying the window it was scored over.

    ``error_days`` is already absolute (see the row builders), so a plain mean is
    the MAE; countries aggregate into their class.

    A band whose window starts after the record's own first scored month carries
    ``scored_from`` and the reason, so a reader is not comparing spans that
    differ by years without being told. EB-5 needs it: it joins on a heading the
    bulletin has only printed since 2022, where EB-1/2/3 run from 2006. On a
    single-month rollup every band shares the month, so nothing is flagged.
    """
    errs_by_class: dict[str, list[int]] = defaultdict(list)
    months_by_class: dict[str, list[date]] = defaultdict(list)
    for r in rows:
        if r.error_days is None or r.visa_class not in QUEUE_DRIVEN_CLASSES:
            continue
        errs_by_class[r.visa_class].append(r.error_days)
        months_by_class[r.visa_class].append(r.bulletin_date)
    if not errs_by_class:
        return []
    record_start = min(min(months) for months in months_by_class.values())

    bands: list[dict] = []
    for vc in _EB_SCORED_CLASSES:
        errs = errs_by_class.get(vc)
        if not errs:
            continue
        first = min(months_by_class[vc])
        bands.append(
            {
                "label": class_display.get(vc, vc),
                "mae_days": round(sum(errs) / len(errs)),
                "n": len(errs),
                "first_month": first,
                "last_month": max(months_by_class[vc]),
                "scored_from": first if first > record_start else None,
                "window_note": window_note(vc),
            }
        )
    return bands


def _format_rollup(
    rows: list[BulletinAccuracyRow],
    prev_cutoff_lookup: dict,
    class_display: dict[str, str],
    month_label: str | None = None,
) -> dict | None:
    """Roll a set of accuracy rows into the display dict the banners render.

    Returns ``None`` when there is nothing scoreable (no real actual + real
    prediction pair) so the caller can omit the banner rather than print zeros.
    """
    summary = compute_bulletin_accuracy_summary(rows, exclude_eb4=True)
    overall = summary.get("overall", {})
    n = overall.get("count") or 0
    if not n:
        return None

    baseline = compare_to_no_change_baseline(
        rows, exclude_eb4=True, prev_cutoff_lookup=prev_cutoff_lookup
    )

    return {
        "month_label": month_label,
        "n_scored": n,
        "mae_days": round(overall["mean_abs_error_days"]),
        "max_days": overall["max_abs_error_days"],
        "bands": _bands(rows, class_display),
        "baseline": {
            "total": baseline["total"],
            "model_wins": baseline["model_wins"],
            "baseline_wins": baseline["baseline_wins"],
            "ties": baseline["ties"],
            "model_win_pct": baseline.get("model_win_pct"),
            "model_mean": baseline.get("model_mean_error"),
            "baseline_mean": baseline.get("baseline_mean_error"),
            "beats_baseline": baseline.get("beats_baseline"),
        },
    }


def build_month_rollup(
    matrix: dict,
    month_date: date,
    classes: list[str],
    country_values: list[int],
    prev_real_cutoffs: dict[tuple[str, int, str], date],
    class_display: dict[str, str],
) -> dict | None:
    """Build the recap-page rollup banner FROM the page's own ``matrix``.

    ``matrix[visa_class][country_value][action_type]`` is the dict the recap view
    already computed (with ``predicted`` = a display object carrying
    ``predicted_date``, ``actual_date``, and the Current/Unavailable flags). So
    the banner scores exactly the predicted-vs-actual pairs shown in the grid —
    it can never diverge from what the reader sees. ``prev_real_cutoffs`` is the
    previous month's REAL actual per ``(visa_class, country, action_type)`` (the
    no-change baseline), so the baseline is scored without touching the
    process-global ``data_cache``.
    """
    rows: list[BulletinAccuracyRow] = []
    prev_lookup: dict = {}
    for vc in classes:
        vc_cells = matrix.get(vc)
        if not vc_cells:
            continue
        for cval in country_values:
            cell_pair = vc_cells.get(cval)
            if not cell_pair:
                continue
            for atype in _ACTION_TYPES:
                cell = cell_pair.get(atype) or {}
                pred = cell.get("predicted")
                pred_date = getattr(pred, "predicted_date", None) if pred else None
                actual = cell.get("actual_date")
                is_real_actual = (
                    actual is not None
                    and not cell.get("actual_is_current")
                    and not cell.get("actual_is_unavailable")
                )
                error_days = (
                    abs((pred_date - actual).days)
                    if (pred_date and is_real_actual)
                    else None
                )
                rows.append(
                    BulletinAccuracyRow(
                        bulletin_date=month_date,
                        visa_class=vc,
                        country=cval,
                        action_type=atype,
                        predicted_cutoff=pred_date,
                        actual_cutoff=actual if is_real_actual else None,
                        error_days=error_days,
                    )
                )
                prev = prev_real_cutoffs.get((vc, cval, atype))
                if prev is not None:
                    prev_lookup[(vc, cval, atype, month_date)] = prev
    return _format_rollup(rows, prev_lookup, class_display, month_label=None)


def _stored_eb_rows(
    months: set[date] | None = None,
) -> tuple[list[BulletinAccuracyRow], dict]:
    """Build EB accuracy rows from STORED predictions (no solver, no data_cache).

    Scores each ``PredictedCutoff`` (shortest horizon per series+month) against
    the published actual, excluding EB-4 and Current/Unavailable actuals. Returns
    ``(rows, prev_cutoff_lookup)`` where the lookup is the previous month's real
    actual per row — everything the summary + baseline functions need, sourced
    from two bulk queries.
    """
    from models.visa_cutoff_date import VisaCutoffDate
    from models.vqs import PredictedCutoff

    # Stored predictions, shortest horizon wins (ascending prediction_date, so a
    # later/ shorter-horizon row overwrites the earlier one for the same target).
    pred_qs = (
        PredictedCutoff.objects.filter(
            visa_class__in=_EB_SCORED_CLASSES,
            predicted_date__isnull=False,
        )
        .select_related("bulletin")
        .order_by("bulletin__prediction_date")
    )
    stored: dict[tuple[str, int, str, date], date] = {}
    for p in pred_qs:
        tm = p.bulletin.target_bulletin_month
        if months is not None and tm not in months:
            continue
        stored[(p.visa_class, p.country, p.action_type, tm)] = p.predicted_date
    if not stored:
        return [], {}

    # Actuals are keyed by the heading DOS printed, predictions by the series
    # key. They differ for EB-5, so the filter spans its renames and every row
    # is re-keyed onto its series before the join (see eb_series).
    act_qs = (
        VisaCutoffDate.objects.filter(
            cutoff_label_q(_EB_SCORED_CLASSES),
            visa_category="employment_based",
        ).select_related("bulletin")
    )
    actuals: dict[tuple[str, int, str, date], tuple] = {}
    series_hist: dict[tuple[str, int, str], list[tuple[date, date]]] = defaultdict(list)
    for a in act_qs:
        vc = series_key_for_label(a.visa_class)
        if vc is None:
            continue
        pub = a.bulletin.publication_date
        actuals[(vc, a.country, a.action_type, pub)] = (
            a.cutoff_date,
            a.is_current,
            a.is_unavailable,
        )
        if a.cutoff_date is not None and not a.is_current and not a.is_unavailable:
            series_hist[(vc, a.country, a.action_type)].append((pub, a.cutoff_date))
    for key in series_hist:
        series_hist[key].sort()

    rows: list[BulletinAccuracyRow] = []
    prev_lookup: dict = {}
    for (vc, country, atype, tm), pred_date in stored.items():
        act = actuals.get((vc, country, atype, tm))
        if not act:
            continue
        cutoff, is_cur, is_unav = act
        if cutoff is None or is_cur or is_unav:
            continue  # only score a real published date
        rows.append(
            BulletinAccuracyRow(
                bulletin_date=tm,
                visa_class=vc,
                country=country,
                action_type=atype,
                predicted_cutoff=pred_date,
                actual_cutoff=cutoff,
                error_days=abs((pred_date - cutoff).days),
            )
        )
        # Previous month's real actual = latest series entry strictly before tm.
        prev = None
        for pub, cd in series_hist.get((vc, country, atype), []):
            if pub < tm:
                prev = cd
            else:
                break
        if prev is not None:
            prev_lookup[(vc, country, atype, tm)] = prev
    return rows, prev_lookup


def _latest_bulletin_month() -> date | None:
    from models.bulletin import Bulletin

    return (
        Bulletin.objects.order_by("-publication_date")
        .values_list("publication_date", flat=True)
        .first()
    )


def latest_month_scorecard() -> dict | None:
    """Rollup for the most-recent published EB bulletin month (stored preds).

    Adds ``month`` + ``recap_url`` so the archive index can link the scorecard to
    that month's recap page. ``None`` when the latest month has no scoreable
    stored predictions yet.
    """
    latest = _latest_bulletin_month()
    if latest is None:
        return None
    rows, prev_lookup = _stored_eb_rows(months={latest})
    roll = _format_rollup(
        rows, prev_lookup, EB_SHORT_LABELS, month_label=latest.strftime("%B %Y")
    )
    if roll is None:
        return None
    roll["month"] = latest
    # Canonical bare-numeric employment_based recap URL (see
    # prediction_canonical_path) — non-zero-padded month, matching the canonical.
    roll["recap_url"] = f"/predictions/{latest.year}-{latest.month}/"
    return roll


def all_time_track_record() -> dict | None:
    """Model-vs-no-change track record across every month with STORED EB
    predictions. Honest: both the model mean error and the no-change baseline
    mean are returned, plus how often the model actually won — never a lone
    flattering %. ``None`` when nothing is scoreable."""
    rows, prev_lookup = _stored_eb_rows()
    summary = compute_bulletin_accuracy_summary(rows, exclude_eb4=True)
    overall = summary.get("overall", {})
    if not overall.get("count"):
        return None
    baseline = compare_to_no_change_baseline(
        rows, exclude_eb4=True, prev_cutoff_lookup=prev_lookup
    )
    months = sorted({r.bulletin_date for r in rows if r.error_days is not None})
    return {
        "n_scored": overall["count"],
        "bands": _bands(rows, EB_SHORT_LABELS),
        "months_covered": len(months),
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "mae_days": round(overall["mean_abs_error_days"]),
        "model_mean": baseline.get("model_mean_error"),
        "baseline_mean": baseline.get("baseline_mean_error"),
        "model_wins": baseline["model_wins"],
        "baseline_total": baseline["total"],
        "model_win_pct": baseline.get("model_win_pct"),
        "beats_baseline": baseline.get("beats_baseline"),
    }


def archive_index_accuracy() -> dict:
    """Cached {scorecard, all_time} for the /predictions/ archive index.

    Keyed on the latest bulletin month so it refreshes each time a new bulletin
    lands. Fails soft — any error yields empty teasers rather than a 500, since
    this is a decorative surface on top of the plain month list.
    """
    from django.core.cache import cache

    latest = _latest_bulletin_month()
    cache_key = f"vqs_archive_index_accuracy:{latest}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit["v"]
    try:
        result = {
            "scorecard": latest_month_scorecard(),
            "all_time": all_time_track_record(),
        }
    except Exception:
        logger.exception("archive_index_accuracy failed; degrading to empty teasers")
        result = {"scorecard": None, "all_time": None}
    cache.set(cache_key, {"v": result}, _CACHE_TTL_S)
    return result
