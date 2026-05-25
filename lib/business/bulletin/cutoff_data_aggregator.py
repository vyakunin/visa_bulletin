"""
Dashboard business logic service

Extracts data aggregation and processing logic from views to keep them thin.
"""

from dataclasses import dataclass
from datetime import date
from itertools import groupby
from operator import attrgetter

from django.core.cache import cache

from lib.business.bulletin.cutoff_projection import calculate_projection
from models.bulletin import Bulletin
from models.enums.country import Country
from models.enums.employment_preference import EmploymentPreference
from models.enums.family_preference import FamilyPreference
from models.enums.visa_category import VisaCategory
from models.visa_cutoff_date import VisaCutoffDate

_LATEST_BULLETIN_MONTH_CACHE_KEY = "seo_latest_bulletin_month_v1"
_LATEST_BULLETIN_MONTH_TTL_SECONDS = 3600  # bulletin publishes monthly; 1h is plenty


def _latest_bulletin_month() -> date | None:
    """Return the publication_date of the newest published bulletin in the DB,
    cached for an hour. Used by SEO titles so the page reflects the bulletin
    month users are actually searching for (e.g. "EB-2 China June 2026") even
    after the calendar month has rolled past it. Falls back to today() when
    the DB is empty or unreachable.
    """
    cached = cache.get(_LATEST_BULLETIN_MONTH_CACHE_KEY)
    if cached:
        return cached
    latest = Bulletin.objects.order_by("-publication_date").values_list("publication_date", flat=True).first()
    if latest:
        cache.set(_LATEST_BULLETIN_MONTH_CACHE_KEY, latest, _LATEST_BULLETIN_MONTH_TTL_SECONDS)
    return latest


@dataclass
class VisaClassData:
    """Data for a single visa class including historical cutoffs and projection"""

    visa_class: str
    visa_class_label: str
    dates: list[date]
    cutoff_dates: list[date | None]
    bulletin_urls: list[str]
    projection: dict | None = None

    def to_dict(self) -> dict:
        """Convert to dict for template context"""
        return {
            "visa_class": self.visa_class,
            "visa_class_label": self.visa_class_label,
            "dates": self.dates,
            "cutoff_dates": self.cutoff_dates,
            "bulletin_urls": self.bulletin_urls,
            "projection": self.projection,
            "last_bulletin_date": self.dates[-1] if self.dates else None,
        }


def get_visa_classes_for_category(category: str) -> list[tuple[str, str]]:
    """
    Get list of visa classes with labels for a given category

    Args:
        category: Visa category value (family_sponsored or employment_based)

    Returns:
        List of (value, label) tuples
    """
    from lib.business.bulletin.visa_class_utils import (
        get_deduplicated_employment_classes,
    )

    if category == VisaCategory.FAMILY_SPONSORED.value:
        return FamilyPreference.choices
    elif category == VisaCategory.EMPLOYMENT_BASED.value:
        return get_deduplicated_employment_classes()
    return []


def get_aggregated_visa_class_data(
    category: str,
    country: str | int,
    action_type: str,
    submission_date: date,
) -> tuple[list[dict], bool]:
    """
    Query and aggregate visa class data with normalized names

    Handles historical visa class name variations by normalizing them
    (e.g., "1st", "1 st", "EB-1" all become "EB-1: Priority Workers").

    Args:
        category: Visa category (family_sponsored, employment_based)
        country: Country code (int enum value, or string slug e.g. "all" -> Country.ALL)
        action_type: Action type (final_action, dates_for_filing)
        submission_date: User's priority date for projection calculation

    Returns:
        Tuple of (list of visa class data dicts, has_any_data bool)
    """
    # Normalize country to int (DB uses IntegerChoices); accept string slug for robustness
    if isinstance(country, str):
        if country.isdigit():
            country = int(country)
        else:
            ce = Country.from_string(country)
            country = ce.value if ce is not None else Country.ALL.value
    valid = [c.value for c in Country]
    if country not in valid:
        country = Country.ALL.value

    # Query all cutoff data in one go
    all_cutoff_data = (
        VisaCutoffDate.objects.filter(
            visa_category=category, country=country, action_type=action_type
        )
        .select_related("bulletin")
        .order_by("visa_class", "bulletin__publication_date")
    )

    if category == VisaCategory.EMPLOYMENT_BASED.value:
        visa_class_data = _aggregate_employment_data(all_cutoff_data, submission_date)
    else:
        visa_class_data = _aggregate_family_data(all_cutoff_data, submission_date)

    return visa_class_data, bool(visa_class_data)


def _aggregate_employment_data(cutoff_data, submission_date: date) -> list[dict]:
    """
    Aggregate employment-based visa data with normalized class names

    Employment visas have many historical variations (1st, EB-1, EB1, etc.)
    that need to be normalized and aggregated.
    """
    normalized_data: dict[str, VisaClassData] = {}

    for visa_class, records in groupby(cutoff_data, key=attrgetter("visa_class")):
        # Normalize to display name (e.g., "1st" → "EB-1: Priority Workers")
        display_name = EmploymentPreference.normalize_for_display(visa_class)

        # Skip unrecognized classes (normalization returns same as input)
        if not display_name or display_name == visa_class:
            list(records)  # Consume iterator
            continue

        # Initialize or get existing data for this normalized class
        if display_name not in normalized_data:
            normalized_data[display_name] = VisaClassData(
                visa_class=visa_class,
                visa_class_label=display_name,
                dates=[],
                cutoff_dates=[],
                bulletin_urls=[],
            )

        _append_records_to_data(
            normalized_data[display_name], records, VisaCategory.EMPLOYMENT_BASED.value
        )

    return _finalize_aggregated_data(normalized_data, submission_date)


def _aggregate_family_data(cutoff_data, submission_date: date) -> list[dict]:
    """
    Aggregate family-sponsored visa data with normalized class names

    Family visas have legacy names (1st, 2A, 3rd, 4th) that map to
    modern names (F1, F2A, F3, F4).
    """
    visa_classes_map = {vc[0]: vc[1] for vc in FamilyPreference.choices}
    normalized_data: dict[str, VisaClassData] = {}

    for visa_class, records in groupby(cutoff_data, key=attrgetter("visa_class")):
        # Normalize legacy name (e.g., "1st" → "F1", "2A" → "F2A")
        normalized_class = FamilyPreference.normalize_legacy_name(visa_class)

        # Skip unrecognized classes
        if normalized_class not in visa_classes_map:
            list(records)  # Consume iterator
            continue

        visa_class_label = visa_classes_map[normalized_class]

        if normalized_class not in normalized_data:
            normalized_data[normalized_class] = VisaClassData(
                visa_class=normalized_class,
                visa_class_label=visa_class_label,
                dates=[],
                cutoff_dates=[],
                bulletin_urls=[],
            )

        _append_records_to_data(
            normalized_data[normalized_class],
            records,
            VisaCategory.FAMILY_SPONSORED.value,
        )

    return _finalize_aggregated_data(normalized_data, submission_date)


def _append_records_to_data(data: VisaClassData, records, category: str) -> None:
    """Append bulletin records to visa class data, avoiding duplicates"""
    for record in records:
        pub_date = record.bulletin.publication_date

        # Avoid duplicates (same date from different name variants)
        if pub_date in data.dates:
            continue

        data.dates.append(pub_date)
        # Internal link to prediction detail page (category-aware)
        internal_url = f"/predictions/{category}/{pub_date.year}-{pub_date.month}/"
        data.bulletin_urls.append(internal_url)

        if record.is_current:
            data.cutoff_dates.append(pub_date)
        elif record.is_unavailable:
            data.cutoff_dates.append(None)
        else:
            data.cutoff_dates.append(record.cutoff_date)


# Minimum bulletin date to show a visa class (only show classes with updates after 2012)
_MIN_BULLETIN_DATE = date(2013, 1, 1)


def _finalize_aggregated_data(
    normalized_data: dict[str, VisaClassData], submission_date: date
) -> list[dict]:
    """Sort data by date, calculate projections, and convert to dicts. Only includes visa classes with at least one bulletin date on or after 2013-01-01."""
    result = []

    for data in normalized_data.values():
        if not data.dates:
            continue
        if max(data.dates) < _MIN_BULLETIN_DATE:
            continue

        # Sort all lists by date
        sorted_indices = sorted(range(len(data.dates)), key=lambda i: data.dates[i])
        data.dates = [data.dates[i] for i in sorted_indices]
        data.cutoff_dates = [data.cutoff_dates[i] for i in sorted_indices]
        data.bulletin_urls = [data.bulletin_urls[i] for i in sorted_indices]

        # Calculate projection
        data.projection = calculate_projection(
            data.dates, data.cutoff_dates, submission_date
        )
        result.append(data.to_dict())

    # Sort by label for consistent ordering
    result.sort(key=lambda x: x["visa_class_label"])
    return result


def _build_page_title(
    category_display: str, country_display: str, category: str, country: str,
    is_root: bool = False,
) -> str:
    """Build dynamic page title based on category and country.

    When ``is_root`` is True (i.e. request landed on bare `/` with no filter
    query string), use an evergreen generic title. Per GSC baseline 2026-05-16
    (see [[project_gsc_seo_baseline]]), the query "visa bulletin" alone has
    254k impressions/4w at CTR 0.17% because the country-specific title
    ("India Employment-Based…") mismatches the generic search intent. Generic
    visitors landing on `/` still get the India dashboard underneath — the
    filter UI is right at the top — but the title now matches what they
    searched for, which should lift CTR materially.
    """
    # Anchor SEO month/year on the latest *published bulletin*, not today's
    # calendar date. Users searching "EB-2 China June 2026" want the page to
    # match the bulletin month they're tracking; using today() would still
    # say "May 2026" for two weeks after the June bulletin lands.
    bulletin_month = _latest_bulletin_month() or date.today()
    bulletin_year = bulletin_month.year
    bulletin_month_name = bulletin_month.strftime("%B")

    if is_root:
        return "U.S. Visa Bulletin — Priority Dates, Predictions & Tracker"
    if country == Country.ALL.value and category == VisaCategory.FAMILY_SPONSORED.value:
        return f"Visa Bulletin Predictions {bulletin_year} - Priority Date Tracker"
    # Country-specific: lead with the high-intent fragment users type into
    # Google ("EB-2 China Priority Date — June 2026") so the SERP snippet
    # matches the query verbatim. Brand suffix kept for recognition.
    return (
        f"{country_display} {category_display} Priority Date — "
        f"{bulletin_month_name} {bulletin_year} Visa Bulletin & Predictions"
    )


def _build_page_description(category_display: str, country_display: str, is_root: bool = False) -> str:
    """Build page description for SEO."""
    if is_root:
        return (
            "Live U.S. visa bulletin priority dates, predictions, and historical trends. "
            "Covers all employment-based (EB-1/2/3/4/5) and family-sponsored (F1–F4) categories "
            "for every country, with month-by-month projections based on the Bulletin Forecast Model."
        )
    bulletin_month = _latest_bulletin_month() or date.today()
    bulletin_label = bulletin_month.strftime("%B %Y")
    return (
        f"{bulletin_label} visa bulletin priority dates for {country_display} {category_display}. "
        f"Current cutoffs, month-over-month movement, and next-bulletin predictions from our forecast model."
    )


def _build_structured_data(
    page_title: str,
    page_description: str,
    category_display: str,
    country_display: str,
    request_uri: str,
) -> dict:
    """Build JSON-LD structured data for SEO"""
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": page_title,
        "description": page_description,
        "creator": {
            "@type": "Organization",
            "name": "Visa Bulletin Dashboard",
            "url": "https://visa-bulletin.us",
        },
        "keywords": f"visa bulletin, {country_display}, {category_display}, priority date, immigration, green card",
        "dateModified": date.today().isoformat(),
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "distribution": {
            "@type": "DataDownload",
            "contentUrl": request_uri,
            "encodingFormat": "text/html",
        },
    }


def build_seo_metadata(category: str, country: str, request_uri: str, is_root: bool = False) -> dict:
    """
    Build SEO metadata for the dashboard page.

    Args:
        category: Visa category value
        country: Country value
        request_uri: Full request URI for canonical URL
        is_root: True when serving the bare `/` URL with no filter query
                 string — switches title + description to evergreen generic
                 wording that matches "visa bulletin" search intent.

    Returns:
        Dict with page_title, page_description, structured_data, etc.
    """
    category_display = _get_display_label(VisaCategory, category)
    country_display = _get_display_label(Country, country)

    page_title = _build_page_title(category_display, country_display, category, country, is_root=is_root)
    page_description = _build_page_description(category_display, country_display, is_root=is_root)
    structured_data = _build_structured_data(
        page_title, page_description, category_display, country_display, request_uri
    )

    return {
        "page_title": page_title,
        "page_description": page_description,
        "structured_data": structured_data,
        "category_display": category_display,
        "country_display": country_display,
    }


def _get_display_label(enum_class, value: str) -> str:
    """Get display label for an enum value, or return the value if not found"""
    try:
        return enum_class(value).label
    except ValueError:
        return value
