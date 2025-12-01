"""Views for visa bulletin dashboard"""

import json
from datetime import date, datetime
from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse
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
def dashboard_view(request, category=None, country=None):
    """
    Main dashboard view with filters and time-series chart showing all visa classes
    
    Query parameters (or URL kwargs):
        category: visa category (family_sponsored, employment_based)
        country: country code (all, china, india, mexico, philippines)
        action_type: action type (final_action, dates_for_filing)
        submission_date: application submission date (YYYY-MM-DD, default=today)
    """
    # Get filter parameters (URL kwargs take precedence over GET params for SEO URLs)
    if category is None:
        category = request.GET.get('category', VisaCategory.FAMILY_SPONSORED.value)
    
    if country is None:
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
        # Use label for display in chart title
        cat_label_for_chart = VisaCategory(category).label if category in [c.value for c in VisaCategory] else category
        chart_html = build_multi_class_chart_with_projections(
            visa_class_data, submission_date, country, cat_label_for_chart
        )
    
    # Get display labels for UI and SEO
    category_display = VisaCategory(category).label if category in [c.value for c in VisaCategory] else category
    country_display = Country(country).label if country in [c.value for c in Country] else country
    action_type_display = ActionType(action_type).label if action_type in [c.value for c in ActionType] else action_type
    
    # SEO Metadata Construction
    current_year = date.today().year
    current_month_name = date.today().strftime("%B")
    
    # Construct dynamic title
    # E.g. "India Employment-Based Visa Bulletin Predictions & Tracker - Dec 2025"
    page_title = f"{country_display} {category_display} Visa Bulletin Predictions & Tracker - {current_month_name} {current_year}"
    if country == Country.ALL.value and category == VisaCategory.FAMILY_SPONSORED.value:
        # Fallback for default/home view to be more generic but keyword rich
        page_title = f"Visa Bulletin Predictions {current_year} - Priority Date Tracker"

    # Construct dynamic description
    page_description = (
        f"Track current priority dates and projections for {country_display} {category_display} visas. "
        f"View historical trends, see when dates will move, and estimate your green card wait time."
    )

    # JSON-LD Structured Data
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
            "contentUrl": request.build_absolute_uri(),
            "encodingFormat": "text/html"
        }
    }
    
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
        
        # SEO Context
        'page_title': page_title,
        'page_description': page_description,
        'structured_data': json.dumps(structured_data),
        'canonical_url': request.build_absolute_uri(),
        'og_url': request.build_absolute_uri(),
        'og_type': 'website',
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


@cache_page(60 * 60 * 24)  # Cache sitemap/robots for 24 hours
def robots_view(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}"
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@cache_page(60 * 60 * 24)
def sitemap_view(request):
    urls = []
    # Build base URL dynamically or hardcode if behind proxy (often safer to use build_absolute_uri)
    # Note: Behind load balancers/proxies, ensure USE_X_FORWARDED_HOST is set in Django if needed
    base_url = request.build_absolute_uri('/')[:-1]  # Remove trailing slash
    
    # Home
    urls.append(f"{base_url}/")
    
    # Landing pages
    categories = [
        ('employment_based', 'employment-based'),
        ('family_sponsored', 'family-sponsored')
    ]
    
    for cat_val, cat_slug in categories:
        # Category root
        urls.append(f"{base_url}/{cat_slug}/")
        
        # Category + Country
        for country in Country:
             if country.value == Country.ALL.value: continue
             urls.append(f"{base_url}/{cat_slug}/{country.value}/")
    
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    for url in urls:
        xml.append('  <url>')
        xml.append(f'    <loc>{url}</loc>')
        xml.append('    <changefreq>monthly</changefreq>')
        xml.append('    <priority>0.8</priority>')
        xml.append('  </url>')
        
    xml.append('</urlset>')
    
    return HttpResponse("\n".join(xml), content_type="application/xml")
