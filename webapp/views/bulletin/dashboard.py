"""Visa bulletin dashboard views."""

import json
import logging
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from lib.business.bulletin.chart_builder import build_multi_class_chart_with_projections
from lib.business.bulletin.cutoff_data_aggregator import (
    build_seo_metadata,
    get_aggregated_visa_class_data,
)
from lib.business.vqs.coupling import (
    LEGACY_CLAMP_W,
    reconcile_maturity,
    reconcile_pair,
    w_fad_concedes_for_country,
)
from models.blog import BlogPost
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory
from webapp.views.bulletin.priority_date_landing import (
    _COUNTRIES as _PRIORITY_DATE_COUNTRY_SLUGS,
)
from webapp.views.bulletin.priority_date_landing import (
    _EB_CLASSES as _PRIORITY_DATE_EB_CLASSES,
)
from webapp.views.bulletin.retention import (
    STATUS_CURRENT,
    STATUS_DATE,
    make_record,
)

logger = logging.getLogger(__name__)

VQS_VISA_CLASS_MAP = {
    "EB-1: Priority Workers": "1st",
    "EB-2: Professionals with Advanced Degrees": "2nd",
    "EB-3: Skilled Workers, Professionals": "3rd",
    "EB-4: Special Immigrants": "4th",
    "EB-5: Immigrant Investors": "5th",
}

DEFAULT_VISIBLE_VISA_CLASSES = frozenset({
    "EB-1: Priority Workers",
    "EB-2: Professionals with Advanced Degrees",
    "EB-3: Skilled Workers, Professionals",
})

# Short, readable nav labels for the crawlable sibling-country dashboard links
# (keyed by the URL slug from models.enums.country._VALUE_TO_SLUG). Kept terse for
# the inline nav row rather than reusing the verbose enum choice labels
# (e.g. "China (mainland born)").
_DASHBOARD_COUNTRY_LABELS = {
    "india": "India",
    "china": "China",
    "mexico": "Mexico",
    "philippines": "Philippines",
    "all": "All Other Countries",
    "el_salvador_guatemala_honduras": "El Salvador, Guatemala & Honduras",
}


def _get_vqs_predictions(category: str, country: int, action_type: str, submission_date: date | None = None) -> dict:
    """Fetch VQS predictions for employment-based visa classes. Returns {visa_class_label: prediction_dict}.

    When submission_date is provided, also computes maturity_month (first month the cutoff
    is projected to reach the priority date) and trajectory (step-by-step cutoff path).

    The expensive predict_regime_switched() call is cached by (knowledge_date, visa_class,
    country, action_type) — independent of submission_date — because the trajectory is
    the same for every user; only the per-user maturity_month derivation differs.
    """
    if category != VisaCategory.EMPLOYMENT_BASED.value:
        return {}

    from django.core.cache import cache

    from lib.business.vqs.solver import predict_regime_switched
    from models.bulletin import Bulletin

    predictions = {}
    # Use the latest bulletin's publication date as knowledge_date so the solver
    # sees the same data as the "Current Cutoff" column. date.today() can miss
    # a bulletin whose publication_date is tomorrow (common when the State Dept
    # publishes the April bulletin on April 1 while today is still March 31).
    latest_bulletin = Bulletin.objects.order_by("-publication_date").first()
    knowledge_date = latest_bulletin.publication_date if latest_bulletin else date.today()

    # TTL: until the next bulletin publishes (knowledge_date + ~1 month). A user
    # request after the next publish will see a new knowledge_date → new cache key,
    # so stale entries naturally fall out; still cap entries at ~31 days for safety.
    next_publish = knowledge_date + relativedelta(months=1)
    ttl_seconds = max(
        60,
        int((datetime.combine(next_publish, datetime.min.time()) - datetime.now()).total_seconds()),
    )
    ttl_seconds = min(ttl_seconds, 31 * 24 * 3600)

    for label, vqs_class in VQS_VISA_CLASS_MAP.items():
        try:
            cache_key = f"vqs_outcome.v1.{knowledge_date.isoformat()}.{vqs_class}.{country}.{action_type}"
            outcome = cache.get(cache_key)
            if outcome is None:
                # Pass priority_date=None so the trajectory loop runs the full 24 steps
                # (otherwise it breaks early once cutoff >= priority_date, and the cached
                # outcome would be truncated for the first user's PD).
                outcome = predict_regime_switched(
                    knowledge_date=knowledge_date,
                    visa_class=vqs_class,
                    country=country,
                    action_type=action_type,
                    priority_date=None,
                )
                cache.set(cache_key, outcome, ttl_seconds)

            results = outcome.results
            # Derive per-user maturity_month from the (cached) trajectory.
            maturity_month = None
            if submission_date is not None:
                for r in results:
                    if r.cutoff_date is not None and r.cutoff_date >= submission_date:
                        maturity_month = r.month
                        break

            next_cutoff = outcome.predicted_cutoff
            confidence = outcome.confidence
            cutoff_6m = results[5].cutoff_date if len(results) > 5 else None
            cutoff_12m = results[11].cutoff_date if len(results) > 11 else None
            pred = {
                "next_cutoff": next_cutoff,
                "cutoff_6m": cutoff_6m,
                "cutoff_12m": cutoff_12m,
                "maturity_month": maturity_month,
                "trajectory": [
                    (r.month, r.cutoff_date)
                    for r in results
                    if r.cutoff_date is not None
                ],
                "confidence": confidence,
                "confidence_low": None,
                "confidence_high": None,
                # Horizon anchor months, so the 1m/6m/12m cutoff cells can be
                # re-derived by month after FAD↔DFF trajectory reconciliation
                # (see _apply_reconciled_trajectory / coupling.reconcile_pair).
                "next_cutoff_month": results[0].month if results else None,
                "cutoff_6m_month": results[5].month if len(results) > 5 else None,
                "cutoff_12m_month": results[11].month if len(results) > 11 else None,
            }
            if results:
                first = results[0]
                pred["confidence_low"] = first.confidence_low
                pred["confidence_high"] = first.confidence_high
            predictions[label] = pred
        except Exception:
            logger.exception("VQS prediction failed for %s/%s", vqs_class, country)
    return predictions


def _parse_submission_date(date_str: str) -> date:
    """Parse submission date from request, supports MM/DD/YYYY and YYYY-MM-DD."""
    if not date_str:
        return date.today()

    # Try MM/DD/YYYY format first
    try:
        return datetime.strptime(date_str, "%m/%d/%Y").date()
    except ValueError:
        pass

    # Try YYYY-MM-DD format (backward compatibility)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        logger.warning(f"Invalid submission_date format: {date_str}, using today")
        return date.today()


def _linear_maturity_fallback(
    submission_date: date,
    trajectory: list[tuple[date, date]],
) -> date | None:
    """
    Linearly extrapolate beyond the VQS trajectory horizon to estimate maturity.

    Uses the average advancement rate across the full trajectory to project how
    many additional months are needed after the last trajectory point.
    Returns None when the rate is zero (permanently stalled) or data is insufficient.
    """
    if not trajectory or not submission_date:
        return None

    valid = [(m, c) for m, c in trajectory if c is not None]
    if len(valid) < 2:
        return None

    first_month, first_cutoff = valid[0]
    last_month, last_cutoff = valid[-1]

    if last_cutoff >= submission_date:
        return None  # Already reached within trajectory

    total_months = max(1, (last_month.year - first_month.year) * 12 + (last_month.month - first_month.month))
    total_days_advanced = (last_cutoff - first_cutoff).days
    if total_days_advanced <= 0:
        return None  # Stalled — no meaningful estimate

    days_per_month = total_days_advanced / total_months
    remaining_days = (submission_date - last_cutoff).days
    months_remaining = remaining_days / days_per_month

    estimated = last_month + relativedelta(months=round(months_remaining))

    # Cap at 75 years — beyond that the estimate has no planning value
    if (estimated - date.today()).days > 75 * 365:
        return None

    return estimated


def _historical_linear_maturity(
    submission_date: date,
    dates: list[date],
    cutoff_dates: list[date | None],
    lookback_months: int = 36,
) -> date | None:
    """
    Estimate maturity from the actual historical advancement rate.

    Uses the most recent `lookback_months` of real bulletin cutoff data.
    This is more reliable than the VQS trajectory for series where
    regime-persistence blending has flattened the model trajectory.
    Returns None when the series is stalled or data is insufficient.
    """
    if not submission_date or not dates or not cutoff_dates:
        return None

    cutoff_limit = date.today() - relativedelta(months=lookback_months)
    valid = [
        (d, c)
        for d, c in zip(dates, cutoff_dates)
        if c is not None and d >= cutoff_limit
    ]

    if len(valid) < 2:
        return None

    first_d, first_c = valid[0]
    last_d, last_c = valid[-1]

    if last_c >= submission_date:
        return None  # Already current

    total_months = max(1, (last_d.year - first_d.year) * 12 + (last_d.month - first_d.month))
    total_days_advanced = (last_c - first_c).days
    if total_days_advanced <= 0:
        return None  # Not advancing in recent history

    days_per_month = total_days_advanced / total_months
    remaining_days = (submission_date - last_c).days
    months_remaining = remaining_days / days_per_month

    estimated = last_d + relativedelta(months=round(months_remaining))

    if (estimated - date.today()).days > 75 * 365:
        return None

    return estimated


def _counterpart_action_type(action_type: str) -> str:
    """The "other" action type — Filing <-> Final Action."""
    return (
        ActionType.FILING.value
        if action_type == ActionType.FINAL_ACTION.value
        else ActionType.FINAL_ACTION.value
    )


def _apply_reconciled_trajectory(
    pred: dict,
    reconciled_traj: list[tuple[date, date | None]],
    submission_date: date | None,
) -> dict:
    """Return a copy of ``pred`` with its cutoff cells + maturity re-derived from a
    reconciled cutoff trajectory.

    ``next_cutoff``/``cutoff_6m``/``cutoff_12m`` are looked up by their anchor month
    (recorded in ``_get_vqs_predictions``); a month absent from the reconciled
    trajectory (its cutoff was None) yields None, matching the original semantics.
    ``maturity_month`` becomes the first reconciled month whose cutoff reaches the
    submission date. All values inherit the DFF≥FAD invariant by construction.
    """
    by_month = {m: c for m, c in reconciled_traj}
    new = dict(pred)
    new["trajectory"] = reconciled_traj

    nm = pred.get("next_cutoff_month")
    if nm is not None and by_month.get(nm) is not None:
        new["next_cutoff"] = by_month[nm]
    c6 = pred.get("cutoff_6m_month")
    if c6 is not None:
        new["cutoff_6m"] = by_month.get(c6)
    c12 = pred.get("cutoff_12m_month")
    if c12 is not None:
        new["cutoff_12m"] = by_month.get(c12)

    if submission_date is not None:
        matured = None
        for month, cutoff in reconciled_traj:
            if cutoff is not None and cutoff >= submission_date:
                matured = month
                break
        new["maturity_month"] = matured
    return new


def _reconcile_prediction_pair(
    fad_pred: dict,
    dff_pred: dict,
    w_fad_concedes: float,
    submission_date: date | None,
) -> tuple[dict, dict]:
    """Reconcile a (Final Action, Filing) prediction pair so the smooth VQS
    trajectory satisfies DFF≥FAD at every step, then re-derive both preds' cutoff
    cells + maturity from the repaired trajectories. See lib.business.vqs.coupling.
    """
    fad_traj2, dff_traj2 = reconcile_pair(
        fad_pred.get("trajectory") or [],
        dff_pred.get("trajectory") or [],
        w_fad_concedes,
    )
    return (
        _apply_reconciled_trajectory(fad_pred, fad_traj2, submission_date),
        _apply_reconciled_trajectory(dff_pred, dff_traj2, submission_date),
    )


def _reconcile_projection_estimate(
    projection: dict | None,
    counterpart_estimate: date | None,
) -> None:
    """In-place: pull a Filing series' historical-linear ``projection.estimated_date``
    DOWN onto the Final Action estimate when it violates DFF≤FAD.

    This closes the 4th independent invariant surface —
    ``cutoff_projection.calculate_projection`` — which drives the chart's forecast
    diamond and is computed independently of both the VQS trajectory and the
    unified-row maturity. ``months_to_wait`` + ``message`` are recomputed so the dict
    stays internally consistent. No-op when either estimate is absent or already
    ordered. See lib.business.vqs.coupling.reconcile_maturity (LEGACY_CLAMP_W: the
    Final Action projection is the binding upper bound and is never moved).
    """
    if not projection or counterpart_estimate is None:
        return
    est = projection.get("estimated_date")
    if est is None:
        return
    _fad, new_est = reconcile_maturity(counterpart_estimate, est, LEGACY_CLAMP_W)
    if new_est == est:
        return
    projection["estimated_date"] = new_est
    today = date.today()
    months = max(0, (new_est.year - today.year) * 12 + (new_est.month - today.month))
    projection["months_to_wait"] = months
    projection["message"] = f"Estimated processing in {months} months"


def _build_unified_prediction_rows(
    visa_class_data: list[dict],
    vqs_predictions: dict,
    submission_date: date | None,
    counterpart_maturity: dict[str, date | None] | None = None,
    is_filing: bool = False,
) -> list[dict]:
    """
    Merge visa_class_data and vqs_predictions into unified rows for the combined table.

    Each row contains:
      - label: display label
      - last_bulletin_date: date of the most recent bulletin
      - current_cutoff: most recent cutoff date (None = current / no backlog)
      - next_cutoff, confidence, confidence_low, confidence_high: 1m-ahead prediction
      - maturity_month: first month cutoff ≥ submission_date (None = beyond VQS horizon)
      - linear_maturity: linear-extrapolation fallback (None = stalled / no estimate)

    counterpart_maturity/is_filing (optional): the Final Action effective maturity
    per label (maturity_month or linear_maturity), used when is_filing=True to
    enforce the invariant that a Dates-for-Filing cutoff is never behind its Final
    Action counterpart — a priority date therefore becomes current for Filing no
    LATER than for Final Action. This is the FAD↔DFF reconciliation's LINEAR-TAIL
    surface: the smooth VQS trajectory (and the cutoff cells + maturity derived from
    it) is already reconciled upstream in dashboard_view; here we repair only the
    beyond-horizon linear extrapolation, whose independent rate can put Filing later
    than Final Action — impossible in reality. Filing's estimate is pulled DOWN onto
    Final Action via lib.business.vqs.coupling.reconcile_maturity at LEGACY_CLAMP_W
    (the overshooting extrapolation is the unreliable side; Final Action is the
    binding upper bound and is never moved). See Notion 39462b8d +
    docs/fad_dff_coupling_design.md, reported via r/USCIS 2026-07-05 (EB-1 India
    PD 4/29/2025: FAD ~2027 vs Filing ~2029).
    """
    # Build lookup: label → current cutoff (last non-None cutoff date)
    current_cutoffs: dict[str, date | None] = {}
    for vcd in visa_class_data:
        lbl = vcd.get("visa_class_label") or vcd.get("visa_class") or ""
        cutoffs = vcd.get("cutoff_dates") or []
        valid = [c for c in cutoffs if c is not None]
        current_cutoffs[lbl] = valid[-1] if valid else None

    rows = []
    for vcd in visa_class_data:
        lbl = vcd.get("visa_class_label") or vcd.get("visa_class") or ""
        pred = vqs_predictions.get(lbl) or {}
        maturity = pred.get("maturity_month")
        linear = None
        already_current = False

        if submission_date and current_cutoffs.get(lbl) is not None:
            already_current = current_cutoffs[lbl] >= submission_date

        if not already_current and maturity is None and submission_date:
            # Primary: use actual historical bulletin data (more reliable than the
            # VQS trajectory, which gets squashed by regime-persistence blending).
            linear = _historical_linear_maturity(
                submission_date,
                vcd.get("dates") or [],
                vcd.get("cutoff_dates") or [],
            )
            # Fallback: VQS trajectory (for series with no recent actual data)
            if linear is None and pred.get("trajectory"):
                linear = _linear_maturity_fallback(submission_date, pred["trajectory"])

        # Linear-tail reconciliation: the trajectory-derived maturities are already
        # reconciled upstream (dashboard_view). This closes the remaining surface —
        # the beyond-horizon LINEAR extrapolation — through the shared helper. At
        # LEGACY_CLAMP_W the overshooting Filing extrapolation is pulled DOWN onto the
        # Final Action date (the binding upper bound), reproducing the prior scalar
        # clamp exactly; Final Action is never moved. See
        # lib.business.vqs.coupling.reconcile_maturity.
        if not already_current and is_filing and counterpart_maturity:
            other = counterpart_maturity.get(lbl)  # Final Action effective maturity
            effective = maturity if maturity is not None else linear
            if effective is not None and other is not None:
                _fad, new_eff = reconcile_maturity(other, effective, LEGACY_CLAMP_W)
                if new_eff != effective:
                    if maturity is not None:
                        maturity = new_eff
                    else:
                        linear = new_eff

        has_vqs = bool(pred)

        # A horizon forecast equal to today's cutoff is the model predicting no net
        # movement out to that horizon — not a dated forecast. Step-function series
        # (Dates for Filing especially) sit frozen most months and jump at the FY
        # reset; the trajectory reproduces the ~80%/month no-move base rate but
        # cannot call step TIMING, so it returns the current value at every horizon.
        # Rendering that as a hard date reads as "the model expects this exact date
        # 12 months out", which is a claim it does not make. Flag it so the template
        # can say so instead. See Notion 3ac62b8d.
        current = current_cutoffs.get(lbl)
        cutoff_6m_flat = current is not None and pred.get("cutoff_6m") == current
        cutoff_12m_flat = current is not None and pred.get("cutoff_12m") == current

        rows.append({
            "label": lbl,
            # Raw normalized class code ("1st".."5th" / "F1".."F4") — the stable,
            # URL-independent identifier the retention banner keys off (matches the
            # forecast page's PredictedCutoff.visa_class), distinct from the display
            # label above.
            "visa_class": vcd.get("visa_class") or "",
            "last_bulletin_date": vcd.get("last_bulletin_date"),
            "current_cutoff": current_cutoffs.get(lbl),
            "next_cutoff": pred.get("next_cutoff"),
            "cutoff_6m": pred.get("cutoff_6m"),
            "cutoff_12m": pred.get("cutoff_12m"),
            "cutoff_6m_flat": cutoff_6m_flat,
            "cutoff_12m_flat": cutoff_12m_flat,
            "confidence": pred.get("confidence"),
            "confidence_low": pred.get("confidence_low"),
            "confidence_high": pred.get("confidence_high"),
            "maturity_month": maturity,
            "linear_maturity": linear,
            "already_current": already_current,
            "has_vqs": has_vqs,
        })
    return rows



def _dashboard_retention_records(
    category: str,
    country: int,
    action_type: str,
    unified_rows: list[dict],
) -> list[dict]:
    """localStorage-comparable records for the retention "your date moved" banner.

    One record per visa class on this (category, country, action_type) page that
    carries a concrete predicted next-month cutoff (or is already Current). Keyed
    by the raw class code so it's stable across the URL scheme and lines up with
    the forecast page. See webapp/views/bulletin/retention.py.
    """
    records = []
    for row in unified_rows:
        vc = row.get("visa_class") or ""
        if not vc:
            continue
        if row.get("already_current"):
            status, predicted = STATUS_CURRENT, None
        elif isinstance(row.get("next_cutoff"), date):
            status, predicted = STATUS_DATE, row["next_cutoff"]
        else:
            continue  # no concrete prediction to remember
        records.append(
            make_record(
                category, country, vc, action_type,
                status=status, predicted_date=predicted,
            )
        )
    return records


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def dashboard_view(request, category=None, country=None):
    """
    Main dashboard view with filters and time-series chart.

    URL kwargs or query params:
        category: visa category (family_sponsored, employment_based)
        country: country code (all, china, india, mexico, philippines)
        action_type: action type (final_action, dates_for_filing)
        submission_date: priority date (MM/DD/YYYY or YYYY-MM-DD)
    """
    # Parse request parameters
    category = category or request.GET.get(
        "category", VisaCategory.EMPLOYMENT_BASED.value
    )
    country_raw = country or request.GET.get("country", Country.INDIA.value)
    # Normalize country to int so template selected option matches
    # URL path can be slug (philippines, india) or numeric; GET params are strings
    if isinstance(country_raw, str) and country_raw.isdigit():
        country = int(country_raw)
    elif isinstance(country_raw, str):
        # Readable URL slug (e.g. /family-sponsored/philippines/)
        country_enum = Country.from_string(country_raw)
        country = country_enum.value if country_enum else Country.ALL.value
    else:
        country = country_raw
    valid_country_values = [c.value for c in Country]
    if country not in valid_country_values:
        country = Country.ALL.value
    action_type = request.GET.get("action_type", ActionType.FILING.value)
    submission_date_raw = request.GET.get("submission_date", "").strip()
    submission_date = _parse_submission_date(submission_date_raw) if submission_date_raw else None
    # Use today as fallback only for chart/non-maturity purposes
    submission_date_for_chart = submission_date or date.today()

    # Get aggregated visa class data
    visa_class_data, has_data = get_aggregated_visa_class_data(
        category, country, action_type, submission_date_for_chart
    )

    # Build chart (VQS predictions computed below — two-pass: fetch VQS first, then chart)
    chart_data = None

    # Build SEO metadata
    # Treat bare `/` as "root landing" — but only filter params should defeat
    # the evergreen SEO title. utm/stg/_gl/fbclid/etc. trackers + cache-busters
    # are irrelevant to SEO intent. Filter params are the ones this view reads:
    # category, country, action_type, submission_date.
    filter_params = ("category", "country", "action_type", "submission_date")
    has_filter_param = any(p in request.GET for p in filter_params)
    is_root_landing = request.path == "/" and not has_filter_param
    seo = build_seo_metadata(category, country, request.build_absolute_uri(), is_root=is_root_landing)
    action_type_display = (
        ActionType(action_type).label
        if action_type in [c.value for c in ActionType]
        else action_type
    )

    # URL slug mappings for readable dashboard URLs (JS builds path when user changes filters)
    category_slugs = {
        VisaCategory.FAMILY_SPONSORED.value: "family-sponsored",
        VisaCategory.EMPLOYMENT_BASED.value: "employment-based",
    }
    country_slugs = {
        str(c.value): Country.slug_for_value(c.value)
        for c in Country
        if c.value != Country.INVALID and Country.slug_for_value(c.value)
    }

    # Fetch VQS predictions for employment-based categories
    vqs_predictions = {}
    if category == VisaCategory.EMPLOYMENT_BASED.value and has_data:
        try:
            vqs_predictions = _get_vqs_predictions(category, country, action_type, submission_date)
        except Exception:
            logger.exception("Failed to load VQS predictions")

    # Enforce the DFF≥FAD invariant everywhere by reconciling this page's VQS
    # trajectories against the counterpart action_type's (Option B — confidence-
    # weighted reconciliation; see lib.business.vqs.coupling +
    # docs/fad_dff_coupling_design.md). Because reconciliation happens on the
    # trajectory BEFORE the chart + unified rows are built, the plotted chart, the
    # 1m/6m/12m cutoff cells AND the trajectory-derived maturity all inherit the
    # repaired (never-crossing) path — replacing the former scalar-only maturity
    # clamp that fixed just one of the ~4 surfaces the invariant can break.
    #
    # w = per-country confidence weight for the SMOOTH trajectory (India → trust the
    # smooth DFF; China → symmetric). The beyond-horizon LINEAR extrapolation tail is
    # reconciled separately inside _build_unified_prediction_rows with LEGACY_CLAMP_W
    # (Final Action is the binding upper bound there — the overshooting linear
    # extrapolation, not the smooth series, is the unreliable side).
    counterpart_maturity: dict[str, date | None] = {}
    if category == VisaCategory.EMPLOYMENT_BASED.value and has_data and vqs_predictions:
        try:
            w = w_fad_concedes_for_country(country)
            is_filing = action_type == ActionType.FILING.value
            counterpart_action_type = _counterpart_action_type(action_type)
            counterpart_vqs_predictions = _get_vqs_predictions(
                category, country, counterpart_action_type, submission_date
            )
            counterpart_reconciled: dict[str, dict] = {}
            for label, this_pred in list(vqs_predictions.items()):
                other_pred = counterpart_vqs_predictions.get(label)
                if not other_pred:
                    continue
                if is_filing:
                    fad2, dff2 = _reconcile_prediction_pair(other_pred, this_pred, w, submission_date)
                    vqs_predictions[label] = dff2
                    counterpart_reconciled[label] = fad2
                else:
                    fad2, dff2 = _reconcile_prediction_pair(this_pred, other_pred, w, submission_date)
                    vqs_predictions[label] = fad2
                    counterpart_reconciled[label] = dff2

            # Filing page only: also derive the Final Action effective maturity
            # (trajectory-or-linear) so the unified rows can reconcile Filing's
            # beyond-horizon linear tail against it. The Final Action page needs no
            # such counterpart — at LEGACY_CLAMP_W the linear-tail reconciliation
            # never moves Final Action (it is the binding upper bound), so it would
            # be a no-op; skip its extra aggregation.
            if is_filing and submission_date:
                counterpart_visa_class_data, counterpart_has_data = get_aggregated_visa_class_data(
                    category, country, counterpart_action_type, submission_date_for_chart
                )
                if counterpart_has_data:
                    counterpart_rows = _build_unified_prediction_rows(
                        counterpart_visa_class_data, counterpart_reconciled, submission_date,
                    )
                    counterpart_maturity = {
                        r["label"]: (r["maturity_month"] or r["linear_maturity"])
                        for r in counterpart_rows
                        if not r["already_current"]
                    }
                    # 4th surface: reconcile this page's chart forecast-diamond
                    # (calculate_projection.estimated_date) against Final Action's,
                    # in place, before the chart is built below.
                    counterpart_estimate = {
                        (d.get("visa_class_label") or d.get("visa_class")): (d.get("projection") or {}).get("estimated_date")
                        for d in counterpart_visa_class_data
                    }
                    for d in visa_class_data:
                        lbl = d.get("visa_class_label") or d.get("visa_class")
                        _reconcile_projection_estimate(d.get("projection"), counterpart_estimate.get(lbl))
        except Exception:
            logger.exception("Failed to reconcile FAD/DFF VQS predictions")

    # Build chart after VQS predictions so trajectory data can be included
    if has_data:
        cat_label = (
            VisaCategory(category).label
            if category in [c.value for c in VisaCategory]
            else category
        )
        chart_data = build_multi_class_chart_with_projections(
            visa_class_data, submission_date_for_chart, country, cat_label, vqs_predictions=vqs_predictions
        )

    # Build unified prediction rows for the combined table (all categories)
    unified_rows = []
    if has_data:
        unified_rows = _build_unified_prediction_rows(
            visa_class_data,
            vqs_predictions,
            submission_date,
            counterpart_maturity=counterpart_maturity,
            is_filing=(action_type == ActionType.FILING.value),
        )

    latest_post = BlogPost.objects.filter(is_published=True).order_by("-published_date").first()

    # Latest bulletin edition — a visible, head-term-relevant freshness signal near
    # the H1 ("Latest edition: <Month Year> Visa Bulletin"). publication_date is the
    # edition month (e.g. the July bulletin published mid-June), which is exactly the
    # "current" framing users expect — not a today-capped "last updated" timestamp.
    from models.bulletin import Bulletin

    latest_bulletin = Bulletin.objects.order_by("-publication_date").first()
    current_bulletin_date = latest_bulletin.publication_date if latest_bulletin else None

    # Homepage link to the upcoming-month forecast. The homepage is the most
    # frequently crawled page on the site, so this is the fastest path for Google
    # to discover the forecast page while the pre-drop anticipation wave builds.
    from webapp.views.bulletin.prediction_month_forecast import (
        forecast_url_for,
        upcoming_forecast_month,
    )

    upcoming_forecast = upcoming_forecast_month()
    upcoming_forecast_url = (
        forecast_url_for(upcoming_forecast) if upcoming_forecast else None
    )
    upcoming_forecast_label = (
        upcoming_forecast.strftime("%B %Y") if upcoming_forecast else None
    )

    # For family-sponsored, pre-select all series; for employment-based, use the default subset.
    if category == VisaCategory.FAMILY_SPONSORED.value and chart_data:
        visible_classes = frozenset(t["label"] for t in chart_data["trace_info"])
    else:
        visible_classes = DEFAULT_VISIBLE_VISA_CLASSES

    # Slug for the currently-selected country, for contextual deep-link URLs.
    country_slug = Country.slug_for_value(country) or "all"
    category_slug = category_slugs.get(category, "employment-based")

    # Inbound links to the per-EB-class priority-date landing pages for this
    # country (SEO internal-link mesh; reuses the landing view's canonical slug
    # sets so it tracks any added EB class / country automatically). Only the EB
    # categories + the four countries that have landing pages.
    priority_date_links = []
    if category == VisaCategory.EMPLOYMENT_BASED.value and country_slug in _PRIORITY_DATE_COUNTRY_SLUGS:
        priority_date_links = [
            {"label": short, "url": f"/priority-date/{eb_slug}/{country_slug}/"}
            for eb_slug, (short, _full) in _PRIORITY_DATE_EB_CLASSES.items()
        ]

    # Crawlable internal links to the sibling per-country dashboards for this
    # category. The high-intent country pages (e.g. /employment-based/india/)
    # were previously reachable only through the JS country <select>, which
    # search engines don't follow — leaving the core-audience pages internally
    # under-linked (India EB ranked GSC pos ~36). These <a> links flow link
    # equity from every (high-traffic) dashboard render and give a data-dense
    # page a clear next-step nav, cutting bounce. Notion 38b62b8d.
    country_dashboard_links = []
    if category in (
        VisaCategory.EMPLOYMENT_BASED.value,
        VisaCategory.FAMILY_SPONSORED.value,
    ):
        nav_slugs = ["india", "china", "mexico", "philippines", "all"]
        if category == VisaCategory.FAMILY_SPONSORED.value:
            nav_slugs.append("el_salvador_guatemala_honduras")
        country_dashboard_links = [
            {
                "label": _DASHBOARD_COUNTRY_LABELS[slug],
                "url": f"/{category_slug}/{slug}/",
                "active": slug == country_slug,
            }
            for slug in nav_slugs
        ]

    context = {
        # Filter state
        "category": category,
        "country": country,
        "country_slug": country_slug,
        "category_slug": category_slug,
        "action_type": action_type,
        "submission_date": submission_date,
        "chart_data": chart_data,
        "visa_class_data": visa_class_data,
        "has_data": has_data,
        "vqs_predictions": vqs_predictions,
        "unified_rows": unified_rows,
        "show_vqs_column": category == VisaCategory.EMPLOYMENT_BASED.value,
        "priority_date_links": priority_date_links,
        "country_dashboard_links": country_dashboard_links,
        "retention_records": _dashboard_retention_records(
            category, country, action_type, unified_rows
        ),
        "latest_post": latest_post,
        "current_bulletin_date": current_bulletin_date,
        "upcoming_forecast_url": upcoming_forecast_url,
        "upcoming_forecast_label": upcoming_forecast_label,
        # Filter options
        "visa_categories": VisaCategory.choices,
        "countries": Country.choices,
        "action_types": ActionType.choices,
        # Display labels
        "category_display": seo["category_display"],
        "country_display": seo["country_display"],
        "action_type_display": action_type_display,
        # SEO
        "page_title": seo["page_title"],
        "page_heading": seo["page_heading"],
        "page_description": seo["page_description"],
        "structured_data": json.dumps(seo["structured_data"]),
        "canonical_url": request.build_absolute_uri(request.path),
        "og_url": request.build_absolute_uri(request.path),
        "og_type": "website",
        "category_slugs_json": json.dumps(category_slugs),
        "country_slugs_json": json.dumps(country_slugs),
        "default_visible_classes": visible_classes,
    }

    return render(request, "webapp/dashboard.html", context)
