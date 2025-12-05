"""Views for visa bulletin dashboard"""

import json
import logging
from datetime import date, datetime

from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_page

from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from lib.chart_builder import build_multi_class_chart_with_projections
from lib.dashboard_service import (
    get_aggregated_visa_class_data,
    build_seo_metadata,
)

logger = logging.getLogger(__name__)


def _parse_submission_date(date_str: str) -> date:
    """Parse submission date from request, supports MM/DD/YYYY and YYYY-MM-DD"""
    if not date_str:
        return date.today()
    
    # Try MM/DD/YYYY format first
    try:
        return datetime.strptime(date_str, '%m/%d/%Y').date()
    except ValueError:
        pass
    
    # Try YYYY-MM-DD format (backward compatibility)
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        logger.warning(f"Invalid submission_date format: {date_str}, using today")
        return date.today()


@cache_page(60 * 60 * 3)  # Cache for 3 hours (bulletins update monthly)
def dashboard_view(request, category=None, country=None):
    """
    Main dashboard view with filters and time-series chart
    
    URL kwargs or query params:
        category: visa category (family_sponsored, employment_based)
        country: country code (all, china, india, mexico, philippines)
        action_type: action type (final_action, dates_for_filing)
        submission_date: priority date (MM/DD/YYYY or YYYY-MM-DD)
    """
    # Parse request parameters
    category = category or request.GET.get('category', VisaCategory.FAMILY_SPONSORED.value)
    country = country or request.GET.get('country', Country.ALL.value)
    action_type = request.GET.get('action_type', ActionType.FINAL_ACTION.value)
    submission_date = _parse_submission_date(request.GET.get('submission_date', ''))
    
    # Get aggregated visa class data
    visa_class_data, has_data = get_aggregated_visa_class_data(
        category, country, action_type, submission_date
    )
    
    # Build chart
    chart_data = None
    if has_data:
        cat_label = VisaCategory(category).label if category in [c.value for c in VisaCategory] else category
        chart_data = build_multi_class_chart_with_projections(
            visa_class_data, submission_date, country, cat_label
        )
    
    # Build SEO metadata
    seo = build_seo_metadata(category, country, request.build_absolute_uri())
    action_type_display = ActionType(action_type).label if action_type in [c.value for c in ActionType] else action_type
    
    context = {
        # Filter state
        'category': category,
        'country': country,
        'action_type': action_type,
        'submission_date': submission_date,
        
        # Data
        'chart_data': chart_data,
        'visa_class_data': visa_class_data,
        'has_data': has_data,
        
        # Filter options
        'visa_categories': VisaCategory.choices,
        'countries': Country.choices,
        'action_types': ActionType.choices,
        
        # Display labels
        'category_display': seo['category_display'],
        'country_display': seo['country_display'],
        'action_type_display': action_type_display,
        
        # SEO
        'page_title': seo['page_title'],
        'page_description': seo['page_description'],
        'structured_data': json.dumps(seo['structured_data']),
        'canonical_url': request.build_absolute_uri(),
        'og_url': request.build_absolute_uri(),
        'og_type': 'website',
    }
    
    return render(request, 'webapp/dashboard.html', context)


@cache_page(60 * 60 * 24)
def robots_view(request):
    """Generate robots.txt"""
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}"
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@cache_page(60 * 60 * 24)
def sitemap_view(request):
    """Generate XML sitemap"""
    base_url = request.build_absolute_uri('/')[:-1]
    
    urls = [
        f"{base_url}/",
        f"{base_url}/faq/",
        f"{base_url}/about/",
        f"{base_url}/contact/",
    ]
    
    # Category landing pages
    categories = [
        ('employment_based', 'employment-based'),
        ('family_sponsored', 'family-sponsored')
    ]
    
    for _, cat_slug in categories:
        urls.append(f"{base_url}/{cat_slug}/")
        for c in Country:
            if c.value != Country.ALL.value:
                urls.append(f"{base_url}/{cat_slug}/{c.value}/")
    
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    for url in urls:
        xml_parts.extend([
            '  <url>',
            f'    <loc>{url}</loc>',
            '    <changefreq>monthly</changefreq>',
            '    <priority>0.8</priority>',
            '  </url>'
        ])
    
    xml_parts.append('</urlset>')
    return HttpResponse("\n".join(xml_parts), content_type="application/xml")


def faq_view(request):
    """FAQ page"""
    return render(request, 'webapp/faq.html', {
        'page_title': 'Frequently Asked Questions - Visa Bulletin Dashboard',
        'page_description': 'Common questions about priority dates, PERM processing, Final Action vs Filing Dates, and how the Visa Bulletin tracker works.',
    })


def about_view(request):
    """About page"""
    return render(request, 'webapp/about.html', {
        'page_title': 'About - Visa Bulletin Dashboard',
        'page_description': 'Learn about the Visa Bulletin dashboard, data sources, projection methodology, and the team behind this community tool.',
    })


def contact_view(request):
    """Contact page"""
    return render(request, 'webapp/contact.html', {
        'page_title': 'Contact - Visa Bulletin Dashboard',
        'page_description': 'Get in touch with questions, feedback, or bug reports about the Visa Bulletin tracker.',
    })
