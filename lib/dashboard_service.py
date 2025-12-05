"""
Dashboard business logic service

Extracts data aggregation and processing logic from views to keep them thin.
"""

from dataclasses import dataclass
from datetime import date
from itertools import groupby
from operator import attrgetter

from models.visa_cutoff_date import VisaCutoffDate
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.family_preference import FamilyPreference
from models.enums.employment_preference import EmploymentPreference
from lib.projection import calculate_projection


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
            'visa_class': self.visa_class,
            'visa_class_label': self.visa_class_label,
            'dates': self.dates,
            'cutoff_dates': self.cutoff_dates,
            'bulletin_urls': self.bulletin_urls,
            'projection': self.projection,
        }


def get_visa_classes_for_category(category: str) -> list[tuple[str, str]]:
    """
    Get list of visa classes with labels for a given category
    
    Args:
        category: Visa category value (family_sponsored or employment_based)
        
    Returns:
        List of (value, label) tuples
    """
    from lib.visa_class_utils import get_deduplicated_employment_classes
    
    if category == VisaCategory.FAMILY_SPONSORED.value:
        return FamilyPreference.choices
    elif category == VisaCategory.EMPLOYMENT_BASED.value:
        return get_deduplicated_employment_classes()
    return []


def get_aggregated_visa_class_data(
    category: str,
    country: str,
    action_type: str,
    submission_date: date
) -> tuple[list[dict], bool]:
    """
    Query and aggregate visa class data with normalized names
    
    Handles historical visa class name variations by normalizing them
    (e.g., "1st", "1 st", "EB-1" all become "EB-1: Priority Workers").
    
    Args:
        category: Visa category (family_sponsored, employment_based)
        country: Country code
        action_type: Action type (final_action, dates_for_filing)
        submission_date: User's priority date for projection calculation
        
    Returns:
        Tuple of (list of visa class data dicts, has_any_data bool)
    """
    # Query all cutoff data in one go
    all_cutoff_data = VisaCutoffDate.objects.filter(
        visa_category=category,
        country=country,
        action_type=action_type
    ).select_related('bulletin').order_by('visa_class', 'bulletin__publication_date')
    
    if category == VisaCategory.EMPLOYMENT_BASED.value:
        visa_class_data = _aggregate_employment_data(all_cutoff_data, submission_date)
    else:
        visa_class_data = _aggregate_family_data(all_cutoff_data, submission_date)
    
    return visa_class_data, bool(visa_class_data)


def _aggregate_employment_data(
    cutoff_data,
    submission_date: date
) -> list[dict]:
    """
    Aggregate employment-based visa data with normalized class names
    
    Employment visas have many historical variations (1st, EB-1, EB1, etc.)
    that need to be normalized and aggregated.
    """
    normalized_data: dict[str, VisaClassData] = {}
    
    for visa_class, records in groupby(cutoff_data, key=attrgetter('visa_class')):
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
                bulletin_urls=[]
            )
        
        _append_records_to_data(normalized_data[display_name], records)
    
    return _finalize_aggregated_data(normalized_data, submission_date)


def _aggregate_family_data(
    cutoff_data,
    submission_date: date
) -> list[dict]:
    """
    Aggregate family-sponsored visa data with normalized class names
    
    Family visas have legacy names (1st, 2A, 3rd, 4th) that map to
    modern names (F1, F2A, F3, F4).
    """
    visa_classes_map = {vc[0]: vc[1] for vc in FamilyPreference.choices}
    normalized_data: dict[str, VisaClassData] = {}
    
    for visa_class, records in groupby(cutoff_data, key=attrgetter('visa_class')):
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
                bulletin_urls=[]
            )
        
        _append_records_to_data(normalized_data[normalized_class], records)
    
    return _finalize_aggregated_data(normalized_data, submission_date)


def _append_records_to_data(data: VisaClassData, records) -> None:
    """Append bulletin records to visa class data, avoiding duplicates"""
    for record in records:
        pub_date = record.bulletin.publication_date
        
        # Avoid duplicates (same date from different name variants)
        if pub_date in data.dates:
            continue
        
        data.dates.append(pub_date)
        data.bulletin_urls.append(record.bulletin.get_bulletin_url())
        
        if record.is_current:
            data.cutoff_dates.append(pub_date)
        elif record.is_unavailable:
            data.cutoff_dates.append(None)
        else:
            data.cutoff_dates.append(record.cutoff_date)


def _finalize_aggregated_data(
    normalized_data: dict[str, VisaClassData],
    submission_date: date
) -> list[dict]:
    """Sort data by date, calculate projections, and convert to dicts"""
    result = []
    
    for data in normalized_data.values():
        if not data.dates:
            continue
        
        # Sort all lists by date
        sorted_indices = sorted(range(len(data.dates)), key=lambda i: data.dates[i])
        data.dates = [data.dates[i] for i in sorted_indices]
        data.cutoff_dates = [data.cutoff_dates[i] for i in sorted_indices]
        data.bulletin_urls = [data.bulletin_urls[i] for i in sorted_indices]
        
        # Calculate projection
        data.projection = calculate_projection(data.dates, data.cutoff_dates, submission_date)
        result.append(data.to_dict())
    
    # Sort by label for consistent ordering
    result.sort(key=lambda x: x['visa_class_label'])
    return result


def build_seo_metadata(
    category: str,
    country: str,
    request_uri: str
) -> dict:
    """
    Build SEO metadata for the dashboard page
    
    Args:
        category: Visa category value
        country: Country value
        request_uri: Full request URI for canonical URL
        
    Returns:
        Dict with page_title, page_description, structured_data, etc.
    """
    category_display = _get_display_label(VisaCategory, category)
    country_display = _get_display_label(Country, country)
    
    current_year = date.today().year
    current_month_name = date.today().strftime("%B")
    
    # Dynamic title
    if country == Country.ALL.value and category == VisaCategory.FAMILY_SPONSORED.value:
        page_title = f"Visa Bulletin Predictions {current_year} - Priority Date Tracker"
    else:
        page_title = f"{country_display} {category_display} Visa Bulletin Predictions & Tracker - {current_month_name} {current_year}"
    
    page_description = (
        f"Track current priority dates and projections for {country_display} {category_display} visas. "
        f"View historical trends, see when dates will move, and estimate your green card wait time."
    )
    
    structured_data = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": page_title,
        "description": page_description,
        "creator": {
            "@type": "Organization",
            "name": "Visa Bulletin Dashboard",
            "url": "https://visa-bulletin.us"
        },
        "keywords": f"visa bulletin, {country_display}, {category_display}, priority date, immigration, green card",
        "dateModified": date.today().isoformat(),
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "distribution": {
            "@type": "DataDownload",
            "contentUrl": request_uri,
            "encodingFormat": "text/html"
        }
    }
    
    return {
        'page_title': page_title,
        'page_description': page_description,
        'structured_data': structured_data,
        'category_display': category_display,
        'country_display': country_display,
    }


def _get_display_label(enum_class, value: str) -> str:
    """Get display label for an enum value, or return the value if not found"""
    try:
        return enum_class(value).label
    except ValueError:
        return value
