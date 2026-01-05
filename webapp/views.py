"""Views for visa bulletin dashboard"""

import json
import logging
from datetime import date, datetime
from decimal import Decimal

from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from django.db.models import Avg, Min, Max, Count, F

from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord, Employer, EmployerCluster, WorksiteRecord
from lib.business.bulletin.chart_builder import build_multi_class_chart_with_projections
from lib.business.bulletin.cutoff_data_aggregator import (
    get_aggregated_visa_class_data,
    build_seo_metadata,
)
from lib.utils.pagination import calculate_pagination_info, build_pagination_query_string
from lib.utils.filter_utils import (
    apply_text_search_filter,
    apply_visa_program_filter,
    apply_fiscal_year_filter,
)
from lib.utils.location_utils import US_STATES
from webapp.forms import SalarySearchForm, WorksiteSearchForm

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




def _get_cached_fiscal_years() -> list[int]:
    """
    Get available fiscal years with caching.
    
    Fiscal years change infrequently (monthly), so we cache for 24 hours.
    Cache key invalidates when new data is imported.
    """
    cache_key = 'salary_fiscal_years'
    fiscal_years = cache.get(cache_key)
    
    if fiscal_years is None:
        fiscal_years = list(
            SalaryRecord.objects
            .exclude(fiscal_year__isnull=True)
            .values_list('fiscal_year', flat=True)
            .distinct()
            .order_by('-fiscal_year')
        )
        cache.set(cache_key, fiscal_years, 60 * 60 * 24)  # Cache for 24 hours
    
    return fiscal_years


# Note: @cache_page automatically varies by query parameters, so different searches have different cache keys
# Cache is cleared when server restarts or via: bazel run //scripts:clear_cache
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
    # Get available fiscal years (cached) - needed for form choices
    fiscal_years = _get_cached_fiscal_years()
    
    # Initialize form with dynamic fiscal year choices
    form = SalarySearchForm(request.GET)
    form.fields['year'].choices = [('', 'All Years')] + [(str(y), f'FY {y}') for y in fiscal_years]
    
    per_page = 50
    
    # Extract cleaned form data, with fallback to request.GET for robustness
    # This ensures filters work even if form validation fails
    cleaned_data = form.cleaned_data if form.is_valid() else {}
    query = cleaned_data.get('q') or request.GET.get('q', '') or ''
    employer_filter = cleaned_data.get('employer') or request.GET.get('employer', '') or ''
    state_filter = cleaned_data.get('state') or request.GET.get('state', '') or ''
    program_filter = cleaned_data.get('program') or request.GET.get('program', '') or ''
    year_filter = cleaned_data.get('year') or request.GET.get('year') or None
    try:
        page = cleaned_data.get('page') or int(request.GET.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    
    # Build params dict for compatibility with existing code
    params = {
        'query': query,
        'employer_filter': employer_filter,
        'state_filter': state_filter,
        'program_filter': program_filter,
        'year_filter': str(year_filter) if year_filter else '',
        'page': page,
    }
    
    # Check if any data exists (cache this check)
    cache_key_no_data = 'salary_has_data'
    no_data_yet = cache.get(cache_key_no_data)
    if no_data_yet is None:
        no_data_yet = SalaryRecord.objects.count() == 0
        cache.set(cache_key_no_data, no_data_yet, 60 * 60)  # Cache for 1 hour
    
    # Build and apply filters FIRST (before expensive exclude)
    # This reduces the dataset size before the expensive exclude operation
    has_filters = any([query, employer_filter, state_filter, program_filter, year_filter])
    records = SalaryRecord.objects.all()
    
    # Apply filters using generic utilities
    records = apply_text_search_filter(records, query, ['job_title', 'soc_title'])
    if employer_filter:
        # Filter by cluster canonical name ONLY (matches cluster head)
        # This ensures that searching for a company matches all records in that company's cluster
        # PERFORMANCE: Composite index on (employer, is_worksite) makes this JOIN efficient
        records = records.filter(
            employer__canonical_cluster__canonical_name__icontains=employer_filter
        )
    if state_filter:
        records = records.filter(worksite_state=state_filter)
    records = apply_visa_program_filter(records, program_filter)
    records = apply_fiscal_year_filter(records, year_filter)
    
    # Exclude worksite records AFTER applying filters (reduces dataset size)
    # Use indexed is_worksite field for fast filtering (much faster than source_file pattern matching)
    records = records.exclude(is_worksite=True)
    
    # Also exclude records with 'Unknown' employer (safety measure - worksite records should be filtered above,
    # but this catches any edge cases where is_worksite flag isn't set correctly)
    records = records.exclude(employer_name='Unknown')
    
    # Only calculate statistics when filters are applied (expensive query)
    if has_filters:
        stats = records.filter(wage_annual__isnull=False, wage_annual__gt=0).aggregate(
            avg_salary=Avg('wage_annual'),
            min_salary=Min('wage_annual'),
            max_salary=Max('wage_annual'),
        )
    else:
        # No filters - don't calculate expensive stats
        stats = {
            'avg_salary': None,
            'min_salary': None,
            'max_salary': None,
        }
    
    # Get total results - needed for pagination
    # Cache counts for common filter combinations to avoid expensive count operations
    # The exclude() on source_file causes full table scans, so caching is critical
    cache_key_count = None
    if not has_filters:
        cache_key_count = 'salary_non_worksite_count'
    elif params['program_filter'] == 'h1b' and not any([params['query'], params['employer_filter'], params['state_filter'], params['year_filter']]):
        # Common case: just program=h1b filter (no other filters)
        cache_key_count = 'salary_h1b_non_worksite_count'
    elif params['program_filter'] == 'perm' and not any([params['query'], params['employer_filter'], params['state_filter'], params['year_filter']]):
        # Common case: just program=perm filter (no other filters)
        cache_key_count = 'salary_perm_non_worksite_count'
    
    if cache_key_count:
        total_results = cache.get(cache_key_count)
        if total_results is None:
            total_results = records.count()
            cache.set(cache_key_count, total_results, 60 * 60)  # Cache for 1 hour
    else:
        # For complex filters, calculate count (but this will be slow)
        total_results = records.count()
    
    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)
    
    # Use only() to reduce data loaded - we only need these fields for the list view
    records = records.only(
        'id', 'employer_name', 'job_title', 'worksite_city', 'worksite_state',
        'wage_annual', 'wage_to', 'visa_program', 'fiscal_year'
    ).order_by('-wage_annual', '-fiscal_year')[
        pagination['offset']:pagination['offset'] + per_page
    ]
    
    context = {
        # Form for rendering
        'form': form,
        
        # Search parameters (for backward compatibility with templates)
        'query': query,
        'employer_filter': employer_filter,
        'state_filter': state_filter,
        'program_filter': program_filter,
        'year_filter': year_filter,
        
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
        'page_start': pagination['offset'] + 1 if total_results and total_results > 0 else 0,
        'page_end': min(pagination['offset'] + per_page, total_results) if total_results else 0,
        'has_pagination': pagination['total_pages'] > 1,
        'pagination_query': build_pagination_query_string(params),
        'page_range': pagination['page_range'],
        
        # SEO
        'page_title': 'H-1B & PERM Salary Database - Visa Bulletin Dashboard',
        'page_description': 'Search H-1B and PERM salary data from official DOL disclosure files. Find salaries by job title, employer, and location.',
    }
    
    return render(request, 'webapp/salary_search.html', context)


def _get_cached_worksite_fiscal_years() -> list[int]:
    """Get available fiscal years for worksite records with caching"""
    cache_key = 'worksite_fiscal_years'
    fiscal_years = cache.get(cache_key)
    
    if fiscal_years is None:
        fiscal_years = list(
            WorksiteRecord.objects
            .exclude(fiscal_year__isnull=True)
            .values_list('fiscal_year', flat=True)
            .distinct()
            .order_by('-fiscal_year')
        )
        cache.set(cache_key, fiscal_years, 60 * 60 * 24)  # Cache for 24 hours
    
    return fiscal_years


@cache_page(60 * 60)  # Cache for 1 hour
def worksite_search_view(request):
    """
    Search worksite location data from DOL Worksites disclosure files.
    
    Query params:
        q: Job title / keyword search
        state: Worksite state filter (2-letter code)
        city: Worksite city filter
        program: Visa program filter (h1b, perm)
        year: Fiscal year filter
        page: Page number for pagination
    """
    # Get available fiscal years (cached) - needed for form choices
    fiscal_years = _get_cached_worksite_fiscal_years()
    
    # Initialize form with dynamic fiscal year choices
    form = WorksiteSearchForm(request.GET)
    form.fields['year'].choices = [('', 'All Years')] + [(str(y), f'FY {y}') for y in fiscal_years]
    
    per_page = 50
    
    # Extract cleaned form data
    cleaned_data = form.cleaned_data if form.is_valid() else {}
    query = cleaned_data.get('q', '') or ''
    state_filter = cleaned_data.get('state', '') or ''
    city_filter = cleaned_data.get('city', '') or ''
    program_filter = cleaned_data.get('program', '') or ''
    year_filter = cleaned_data.get('year')
    page = cleaned_data.get('page', 1) or 1
    
    # Build params dict for compatibility with existing code
    params = {
        'query': query,
        'state_filter': state_filter,
        'city_filter': city_filter,
        'program_filter': program_filter,
        'year_filter': str(year_filter) if year_filter else '',
        'page': page,
    }
    
    # Check if any data exists (cache this check)
    cache_key_no_data = 'worksite_has_data'
    no_data_yet = cache.get(cache_key_no_data)
    if no_data_yet is None:
        no_data_yet = WorksiteRecord.objects.count() == 0
        cache.set(cache_key_no_data, no_data_yet, 60 * 60)  # Cache for 1 hour
    
    # Build and apply filters
    records = WorksiteRecord.objects.all()
    has_filters = any([query, state_filter, city_filter, program_filter, year_filter])
    
    # Apply filters using generic utilities
    records = apply_text_search_filter(records, query, ['job_title', 'soc_title', 'worksite_city'])
    if state_filter:
        records = records.filter(worksite_state=state_filter)
    if city_filter:
        records = records.filter(worksite_city__icontains=city_filter)
    records = apply_visa_program_filter(records, program_filter)
    records = apply_fiscal_year_filter(records, year_filter)
    
    # Only calculate statistics when filters are applied (expensive query)
    if has_filters:
        stats = records.filter(wage_annual__isnull=False, wage_annual__gt=0).aggregate(
            avg_salary=Avg('wage_annual'),
            min_salary=Min('wage_annual'),
            max_salary=Max('wage_annual'),
        )
    else:
        # No filters - don't calculate expensive stats
        stats = {
            'avg_salary': None,
            'min_salary': None,
            'max_salary': None,
        }
    
    # Get total results - needed for pagination
    total_results = records.count()
    
    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)
    records = records.order_by('-wage_annual', '-fiscal_year')[
        pagination['offset']:pagination['offset'] + per_page
    ]
    
    context = {
        # Form for rendering
        'form': form,
        
        # Search parameters (for backward compatibility with templates)
        'query': query,
        'state_filter': state_filter,
        'city_filter': city_filter,
        'program_filter': program_filter,
        'year_filter': year_filter,
        
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
        'page_start': pagination['offset'] + 1 if total_results and total_results > 0 else 0,
        'page_end': min(pagination['offset'] + per_page, total_results) if total_results else 0,
        'has_pagination': pagination['total_pages'] > 1,
        'pagination_query': build_pagination_query_string(params),
        'page_range': pagination['page_range'],
        
        # SEO
        'page_title': 'Worksite Location Data - Visa Bulletin Dashboard',
        'page_description': 'Search worksite location data from DOL Worksites disclosure files. Find job locations by city, state, and job title.',
    }
    
    return render(request, 'webapp/worksite_search.html', context)


@cache_page(60 * 60)  # Cache for 1 hour
def company_autocomplete_view(request):
    """
    API endpoint for company name autocomplete suggestions.
    
    Query params:
        q: Search query (partial company name)
        limit: Maximum number of results (default: 20)
    
    Returns JSON array of canonical cluster names matching the query.
    """
    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 20))
    
    if not query or len(query) < 2:
        return HttpResponse(json.dumps([]), content_type='application/json')
    
    # Get cluster canonical names that match the query
    # Order by total record count (LCA + PERM) for relevance
    matching_companies = (
        EmployerCluster.objects
        .filter(canonical_name__icontains=query)
        .annotate(total_count=F('total_lca_count') + F('total_perm_count'))
        .order_by('-total_count', 'canonical_name')
        .values_list('canonical_name', flat=True)
        [:limit]
    )
    
    # Convert to list and return as JSON
    suggestions = list(matching_companies)
    return HttpResponse(json.dumps(suggestions), content_type='application/json')
