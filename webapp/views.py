"""Views for visa bulletin dashboard"""

from datetime import date, datetime
from django.shortcuts import render

from models.visa_cutoff_date import VisaCutoffDate
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.family_preference import FamilyPreference
from models.enums.employment_preference import EmploymentPreference
from lib.projection import calculate_projection
from lib.chart_builder import build_chart_with_projection as build_chart
from lib.visa_class_utils import (
    get_all_employment_visa_classes_from_db,
    get_all_family_visa_classes_from_db,
    get_deduplicated_employment_classes,
)


def dashboard_view(request):
    """
    Main dashboard view with filters and time-series chart
    
    Query parameters:
        category: visa category (family_sponsored, employment_based)
        country: country code (all, china, india, mexico, philippines)
        visa_class: visa class (F1, F2A, EB1, EB2, etc.)
        action_type: action type (final_action, dates_for_filing)
        submission_date: application submission date (YYYY-MM-DD, default=today)
    """
    # Get filter parameters with defaults
    category = request.GET.get('category', VisaCategory.FAMILY_SPONSORED.value)
    country = request.GET.get('country', Country.ALL.value)
    visa_class = request.GET.get('visa_class', FamilyPreference.F1.value)
    action_type = request.GET.get('action_type', ActionType.FINAL_ACTION.value)
    submission_date_str = request.GET.get('submission_date', date.today().isoformat())
    
    # Parse submission date
    try:
        submission_date = datetime.strptime(submission_date_str, '%Y-%m-%d').date()
    except ValueError:
        submission_date = date.today()
    
    # Query visa cutoff data
    cutoff_data = VisaCutoffDate.objects.filter(
        visa_category=category,
        country=country,
        visa_class=visa_class,
        action_type=action_type
    ).select_related('bulletin').order_by('bulletin__publication_date')
    
    # Build chart if data exists
    chart_html = None
    projection_result = None
    
    if cutoff_data.exists():
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
        
        # Calculate projection
        projection_result = calculate_projection(dates, cutoff_dates, submission_date)
        
        # Build chart
        chart_html = build_chart(
            dates, cutoff_dates, submission_date, projection_result, visa_class, country, bulletin_urls
        )
    
    # Get available visa classes for current category
    available_classes_with_labels = get_visa_classes_for_category(category)
    available_classes = [vc[0] for vc in available_classes_with_labels]  # Just values for backward compat
    
    # Get display labels for error messages
    category_display = VisaCategory(category).label if category in [c.value for c in VisaCategory] else category
    country_display = Country(country).label if country in [c.value for c in Country] else country
    action_type_display = ActionType(action_type).label if action_type in [c.value for c in ActionType] else action_type
    
    context = {
        'category': category,
        'country': country,
        'visa_class': visa_class,
        'action_type': action_type,
        'submission_date': submission_date,
        'chart_html': chart_html,
        'projection': projection_result,
        'visa_categories': VisaCategory.choices,
        'countries': Country.choices,
        'action_types': ActionType.choices,
        'family_preferences': FamilyPreference.choices,
        'employment_preferences': EmploymentPreference.choices,
        'available_classes': available_classes,
        'available_classes_with_labels': available_classes_with_labels,
        'has_data': cutoff_data.exists(),
        'category_display': category_display,
        'country_display': country_display,
        'action_type_display': action_type_display,
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

