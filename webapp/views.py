"""Views for visa bulletin dashboard"""

from datetime import date, datetime
from django.shortcuts import render
from django.views.decorators.cache import cache_page

from models.visa_cutoff_date import VisaCutoffDate
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.family_preference import FamilyPreference
from models.enums.employment_preference import EmploymentPreference
from lib.projection import calculate_projection
from lib.chart_builder import build_multi_class_chart_with_projections
from lib.visa_class_utils import (
    get_all_employment_visa_classes_from_db,
    get_all_family_visa_classes_from_db,
    get_deduplicated_employment_classes,
)


@cache_page(60 * 60 * 3)  # Cache for 3 hours (bulletins update monthly)
def dashboard_view(request):
    """
    Main dashboard view with filters and time-series chart showing all visa classes
    
    Query parameters:
        category: visa category (family_sponsored, employment_based)
        country: country code (all, china, india, mexico, philippines)
        action_type: action type (final_action, dates_for_filing)
        submission_date: application submission date (YYYY-MM-DD, default=today)
    """
    # Get filter parameters with defaults
    category = request.GET.get('category', VisaCategory.FAMILY_SPONSORED.value)
    country = request.GET.get('country', Country.ALL.value)
    action_type = request.GET.get('action_type', ActionType.FINAL_ACTION.value)
    submission_date_str = request.GET.get('submission_date', date.today().isoformat())
    
    # Parse submission date
    try:
        submission_date = datetime.strptime(submission_date_str, '%Y-%m-%d').date()
    except ValueError:
        submission_date = date.today()
    
    # Get all visa classes for the selected category
    available_classes_with_labels = get_visa_classes_for_category(category)
    visa_classes_map = {vc[0]: vc[1] for vc in available_classes_with_labels}  # value -> label mapping
    
    # Query data for all visa classes
    visa_class_data = []
    has_any_data = False
    
    for visa_class, visa_class_label in available_classes_with_labels:
        cutoff_data = VisaCutoffDate.objects.filter(
            visa_category=category,
            country=country,
            visa_class=visa_class,
            action_type=action_type
        ).select_related('bulletin').order_by('bulletin__publication_date')
        
        if cutoff_data.exists():
            has_any_data = True
            
            # Extract data from queryset
            dates = []
            cutoff_dates = []
            bulletin_urls = []
            
            for record in cutoff_data:
                pub_date = record.bulletin.publication_date
                dates.append(pub_date)
                bulletin_urls.append(record.bulletin.get_bulletin_url())
                
                if record.is_current:
                    cutoff_dates.append(pub_date)  # Current = publication date
                elif record.is_unavailable:
                    cutoff_dates.append(None)
                else:
                    cutoff_dates.append(record.cutoff_date)
            
            # Calculate projection for this visa class
            projection_result = calculate_projection(dates, cutoff_dates, submission_date)
            
            # Add to data list with full label
            visa_class_data.append({
                'visa_class': visa_class,
                'visa_class_label': visa_class_label,
                'dates': dates,
                'cutoff_dates': cutoff_dates,
                'projection': projection_result,
                'bulletin_urls': bulletin_urls
            })
    
    # Build chart if data exists
    chart_html = None
    if has_any_data:
        category_display = VisaCategory(category).label if category in [c.value for c in VisaCategory] else category
        chart_html = build_multi_class_chart_with_projections(
            visa_class_data, submission_date, country, category_display
        )
    
    # Get display labels for error messages
    category_display = VisaCategory(category).label if category in [c.value for c in VisaCategory] else category
    country_display = Country(country).label if country in [c.value for c in Country] else country
    action_type_display = ActionType(action_type).label if action_type in [c.value for c in ActionType] else action_type
    
    context = {
        'category': category,
        'country': country,
        'action_type': action_type,
        'submission_date': submission_date,
        'chart_html': chart_html,
        'visa_categories': VisaCategory.choices,
        'countries': Country.choices,
        'action_types': ActionType.choices,
        'has_data': has_any_data,
        'category_display': category_display,
        'country_display': country_display,
        'action_type_display': action_type_display,
        'visa_class_data': visa_class_data,  # For displaying individual projections
    }
    
    return render(request, 'webapp/dashboard.html', context)


def get_visa_classes_for_category(category: str) -> list[tuple[str, str]]:
    """
    Get list of visa classes with labels for a given category
    
    Args:
        category: Visa category value (family_sponsored or employment_based)
        
    Returns:
        List of (value, label) tuples from database
        
    Example:
        >>> get_visa_classes_for_category('family_sponsored')
        [('F1', 'F1: Unmarried Sons/Daughters...'), ...]
    """
    if category == VisaCategory.FAMILY_SPONSORED.value:
        # Use enum for family-sponsored (stable naming)
        return FamilyPreference.choices
    elif category == VisaCategory.EMPLOYMENT_BASED.value:
        # Use database values for employment-based (many historical variations)
        # Returns deduplicated list: (raw_db_value, normalized_display_name)
        return get_deduplicated_employment_classes()
    return []

