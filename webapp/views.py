"""Views for visa bulletin dashboard"""

import json
import logging
from datetime import date, datetime
from decimal import Decimal

from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_page
from django.db.models import Q, Avg, Min, Max, Count

from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord, Employer
from lib.business.bulletin.chart_builder import build_multi_class_chart_with_projections
from lib.business.bulletin.cutoff_data_aggregator import (
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


# US States for dropdown
US_STATES = [
    ('AL', 'Alabama'), ('AK', 'Alaska'), ('AZ', 'Arizona'), ('AR', 'Arkansas'),
    ('CA', 'California'), ('CO', 'Colorado'), ('CT', 'Connecticut'), ('DE', 'Delaware'),
    ('DC', 'District of Columbia'), ('FL', 'Florida'), ('GA', 'Georgia'), ('HI', 'Hawaii'),
    ('ID', 'Idaho'), ('IL', 'Illinois'), ('IN', 'Indiana'), ('IA', 'Iowa'),
    ('KS', 'Kansas'), ('KY', 'Kentucky'), ('LA', 'Louisiana'), ('ME', 'Maine'),
    ('MD', 'Maryland'), ('MA', 'Massachusetts'), ('MI', 'Michigan'), ('MN', 'Minnesota'),
    ('MS', 'Mississippi'), ('MO', 'Missouri'), ('MT', 'Montana'), ('NE', 'Nebraska'),
    ('NV', 'Nevada'), ('NH', 'New Hampshire'), ('NJ', 'New Jersey'), ('NM', 'New Mexico'),
    ('NY', 'New York'), ('NC', 'North Carolina'), ('ND', 'North Dakota'), ('OH', 'Ohio'),
    ('OK', 'Oklahoma'), ('OR', 'Oregon'), ('PA', 'Pennsylvania'), ('RI', 'Rhode Island'),
    ('SC', 'South Carolina'), ('SD', 'South Dakota'), ('TN', 'Tennessee'), ('TX', 'Texas'),
    ('UT', 'Utah'), ('VT', 'Vermont'), ('VA', 'Virginia'), ('WA', 'Washington'),
    ('WV', 'West Virginia'), ('WI', 'Wisconsin'), ('WY', 'Wyoming'),
]


def _parse_salary_search_params(request) -> dict:
    """Parse query parameters from salary search request"""
    return {
        'query': request.GET.get('q', '').strip(),
        'employer_filter': request.GET.get('employer', '').strip(),
        'state_filter': request.GET.get('state', '').strip().upper(),
        'program_filter': request.GET.get('program', '').strip().lower(),
        'year_filter': request.GET.get('year', '').strip(),
        'page': int(request.GET.get('page', 1)),
    }


def _apply_salary_filters(records, params: dict):
    """Apply filters to salary records query"""
    if params['query']:
        records = records.filter(
            Q(job_title__icontains=params['query']) |
            Q(soc_title__icontains=params['query'])
        )
    
    if params['employer_filter']:
        records = records.filter(employer_name__icontains=params['employer_filter'])
    
    if params['state_filter']:
        records = records.filter(worksite_state=params['state_filter'])
    
    if params['program_filter']:
        if params['program_filter'] == 'h1b':
            records = records.filter(visa_program__in=[
                VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3
            ])
        elif params['program_filter'] == 'perm':
            records = records.filter(visa_program=VisaProgram.PERM)
    
    if params['year_filter']:
        try:
            records = records.filter(fiscal_year=int(params['year_filter']))
        except ValueError:
            pass
    
    return records


def _calculate_pagination_info(total_results: int, page: int, per_page: int) -> dict:
    """Calculate pagination metadata"""
    total_pages = (total_results + per_page - 1) // per_page
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    offset = (page - 1) * per_page
    
    # Calculate page range for pagination display
    if total_pages <= 7:
        page_range = list(range(1, total_pages + 1))
    elif page <= 4:
        page_range = list(range(1, 6)) + ['...', total_pages]
    elif page >= total_pages - 3:
        page_range = [1, '...'] + list(range(total_pages - 4, total_pages + 1))
    else:
        page_range = [1, '...'] + list(range(page - 1, page + 2)) + ['...', total_pages]
    
    return {
        'page': page,
        'total_pages': total_pages,
        'offset': offset,
        'page_range': [p for p in page_range if p != '...'],
    }


def _build_pagination_query_string(params: dict) -> str:
    """Build query string for pagination links (without page param)"""
    pagination_parts = []
    if params['query']:
        pagination_parts.append(f'q={params["query"]}')
    if params['employer_filter']:
        pagination_parts.append(f'employer={params["employer_filter"]}')
    if params['state_filter']:
        pagination_parts.append(f'state={params["state_filter"]}')
    if params['program_filter']:
        pagination_parts.append(f'program={params["program_filter"]}')
    if params['year_filter']:
        pagination_parts.append(f'year={params["year_filter"]}')
    return '&'.join(pagination_parts)


# Note: @cache_page automatically varies by query parameters, so different searches have different cache keys
# Cache is cleared when server restarts or via: bazel run //:clear_cache
@cache_page(60 * 60)  # Cache for 1 hour
def salary_search_view(request):
    """
    Search H-1B and PERM salary data from DOL disclosure files.
    
    Query params:
        q: Job title / keyword search
        employer: Employer name filter
        state: Worksite state filter (2-letter code)
        program: Visa program filter (h1b, perm)
        year: Fiscal year filter
        page: Page number for pagination
    """
    params = _parse_salary_search_params(request)
    per_page = 50
    
    # Check if any data exists
    no_data_yet = SalaryRecord.objects.count() == 0
    
    # Get available fiscal years
    fiscal_years = list(
        SalaryRecord.objects
        .values_list('fiscal_year', flat=True)
        .distinct()
        .order_by('-fiscal_year')
    )
    
    # Build and apply filters
    records = SalaryRecord.objects.all()
    has_filters = any([params['query'], params['employer_filter'], params['state_filter'], 
                       params['program_filter'], params['year_filter']])
    records = _apply_salary_filters(records, params)
    
    # Calculate statistics before pagination
    stats = records.filter(wage_annual__isnull=False, wage_annual__gt=0).aggregate(
        avg_salary=Avg('wage_annual'),
        min_salary=Min('wage_annual'),
        max_salary=Max('wage_annual'),
    )
    
    total_results = records.count()
    
    # Pagination
    pagination = _calculate_pagination_info(total_results, params['page'], per_page)
    records = records.order_by('-wage_annual', '-fiscal_year')[
        pagination['offset']:pagination['offset'] + per_page
    ]
    
    context = {
        # Search parameters
        'query': params['query'],
        'employer_filter': params['employer_filter'],
        'state_filter': params['state_filter'],
        'program_filter': params['program_filter'],
        'year_filter': int(params['year_filter']) if params['year_filter'].isdigit() else None,
        
        # Filter options
        'states': US_STATES,
        'fiscal_years': fiscal_years,
        
        # Results
        'records': records,
        'has_data': has_filters or not no_data_yet,
        'no_data_yet': no_data_yet,
        
        # Statistics
        'total_results': total_results,
        'avg_salary': stats['avg_salary'],
        'min_salary': stats['min_salary'],
        'max_salary': stats['max_salary'],
        
        # Pagination
        'page': pagination['page'],
        'total_pages': pagination['total_pages'],
        'per_page': per_page,
        'page_start': pagination['offset'] + 1 if total_results > 0 else 0,
        'page_end': min(pagination['offset'] + per_page, total_results),
        'has_pagination': pagination['total_pages'] > 1,
        'pagination_query': _build_pagination_query_string(params),
        'page_range': pagination['page_range'],
        
        # SEO
        'page_title': 'H-1B & PERM Salary Database - Visa Bulletin Dashboard',
        'page_description': 'Search H-1B and PERM salary data from official DOL disclosure files. Find salaries by job title, employer, and location.',
    }
    
    return render(request, 'webapp/salary_search.html', context)


@cache_page(60 * 60)  # Cache for 1 hour
def company_autocomplete_view(request):
    """
    API endpoint for company name autocomplete suggestions.
    
    Query params:
        q: Search query (partial company name)
        limit: Maximum number of results (default: 20)
    
    Returns JSON array of company names matching the query.
    """
    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 20))
    
    if not query or len(query) < 2:
        return HttpResponse(json.dumps([]), content_type='application/json')
    
    # Get distinct employer names that match the query
    # Order by frequency (most common first) for better UX
    matching_companies = (
        SalaryRecord.objects
        .filter(employer_name__icontains=query)
        .values('employer_name')
        .annotate(count=Count('id'))
        .order_by('-count', 'employer_name')
        .values_list('employer_name', flat=True)
        [:limit]
    )
    
    # Convert to list and return as JSON
    suggestions = list(matching_companies)
    return HttpResponse(json.dumps(suggestions), content_type='application/json')
