"""Visa bulletin dashboard views."""

import json
import logging
from datetime import date, datetime

from django.conf import settings
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from lib.business.bulletin.chart_builder import build_multi_class_chart_with_projections
from lib.business.bulletin.cutoff_data_aggregator import (
    build_seo_metadata,
    get_aggregated_visa_class_data,
)
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory

logger = logging.getLogger(__name__)

VQS_VISA_CLASS_MAP = {
    "EB-1: Priority Workers": "1st",
    "EB-2: Advanced Degree / Exceptional Ability": "2nd",
    "EB-3: Skilled Workers / Professionals": "3rd",
    "EB-4: Special Immigrants": "4th",
    "EB-5: Immigrant Investors": "5th",
}

DEFAULT_VISIBLE_VISA_CLASSES = frozenset({
    "EB-1: Priority Workers",
    "EB-2: Professionals with Advanced Degrees",
    "EB-3: Skilled Workers, Professionals",
})


def _get_vqs_predictions(category: str, country: int, action_type: str) -> dict:
    """Fetch VQS predictions for employment-based visa classes. Returns {visa_class_label: prediction_dict}."""
    if category != VisaCategory.EMPLOYMENT_BASED.value:
        return {}

    from lib.business.vqs.solver import predict_next_bulletin_and_maturity

    predictions = {}
    knowledge_date = date.today()

    for label, vqs_class in VQS_VISA_CLASS_MAP.items():
        try:
            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=vqs_class,
                country=country,
                action_type=action_type,
            )
            next_cutoff = outcome.predicted_cutoff
            results = outcome.results
            confidence = outcome.confidence
            pred = {
                "next_cutoff": next_cutoff,
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
    submission_date = _parse_submission_date(request.GET.get("submission_date", ""))

    # Get aggregated visa class data
    visa_class_data, has_data = get_aggregated_visa_class_data(
        category, country, action_type, submission_date
    )

    # Build chart
    chart_data = None
    if has_data:
        cat_label = (
            VisaCategory(category).label
            if category in [c.value for c in VisaCategory]
            else category
        )
        chart_data = build_multi_class_chart_with_projections(
            visa_class_data, submission_date, country, cat_label
        )

    # Build SEO metadata
    seo = build_seo_metadata(category, country, request.build_absolute_uri())
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
            vqs_predictions = _get_vqs_predictions(category, country, action_type)
        except Exception:
            logger.exception("Failed to load VQS predictions")

    context = {
        # Filter state
        "category": category,
        "country": country,
        "action_type": action_type,
        "submission_date": submission_date,
        # Data
        "chart_data": chart_data,
        "visa_class_data": visa_class_data,
        "has_data": has_data,
        "vqs_predictions": vqs_predictions,
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
        "canonical_url": request.build_absolute_uri(),
        "og_url": request.build_absolute_uri(),
        "og_type": "website",
        "category_slugs_json": json.dumps(category_slugs),
        "country_slugs_json": json.dumps(country_slugs),
        "default_visible_classes": DEFAULT_VISIBLE_VISA_CLASSES,
    }

    return render(request, "webapp/dashboard.html", context)
