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
from models.blog import BlogPost
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory

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


def _build_unified_prediction_rows(
    visa_class_data: list[dict],
    vqs_predictions: dict,
    submission_date: date | None,
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

        has_vqs = bool(pred)

        rows.append({
            "label": lbl,
            "last_bulletin_date": vcd.get("last_bulletin_date"),
            "current_cutoff": current_cutoffs.get(lbl),
            "next_cutoff": pred.get("next_cutoff"),
            "cutoff_6m": pred.get("cutoff_6m"),
            "cutoff_12m": pred.get("cutoff_12m"),
            "confidence": pred.get("confidence"),
            "confidence_low": pred.get("confidence_low"),
            "confidence_high": pred.get("confidence_high"),
            "maturity_month": maturity,
            "linear_maturity": linear,
            "already_current": already_current,
            "has_vqs": has_vqs,
        })
    return rows



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
        )

    latest_post = BlogPost.objects.filter(is_published=True).order_by("-published_date").first()

    # For family-sponsored, pre-select all series; for employment-based, use the default subset.
    if category == VisaCategory.FAMILY_SPONSORED.value and chart_data:
        visible_classes = frozenset(t["label"] for t in chart_data["trace_info"])
    else:
        visible_classes = DEFAULT_VISIBLE_VISA_CLASSES

    # Slug for the currently-selected country, for contextual deep-link URLs.
    country_slug = Country.slug_for_value(country) or "all"
    category_slug = category_slugs.get(category, "employment-based")

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
        "latest_post": latest_post,
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
