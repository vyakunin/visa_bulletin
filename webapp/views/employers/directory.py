"""Employer directory views and autocomplete."""

import json

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import cache_page
from django.db.models import Count, Exists, F, OuterRef, Q

from models.enums.visa_program import VisaProgram
from models.salary import Employer, EmployerCluster
from lib.utils.pagination import calculate_pagination_info, build_pagination_query_string
from lib.utils.location_utils import US_STATES


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
        .exclude(canonical_name="Unknown")
        .exclude(slug="unknown")
        .annotate(total_count=F('total_lca_count') + F('total_perm_count'))
        .order_by('-total_count', 'canonical_name')
        .values('canonical_name', 'total_count')
        [:limit]
    )
    
    suggestions = [
        {'name': company['canonical_name'], 'count': company['total_count']}
        for company in matching_companies
    ]
    return HttpResponse(json.dumps(suggestions), content_type='application/json')


@cache_page(60 * 60)  # Cache for 1 hour
def employer_directory_view(request):
    """
    Employer directory page showing list of top employers with search and filters.
    
    Query params:
        q: Search query (employer name)
        program: Visa program filter (h1b, perm, all)
        state: State filter (2-letter code)
        page: Page number for pagination
    """
    # Get query parameters
    query = request.GET.get('q', '').strip()
    program_filter = request.GET.get('program', 'all').lower()
    state_filter = request.GET.get('state', '').strip()
    try:
        page = int(request.GET.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    
    per_page = 50
    
    # Build base queryset - only employers with slugs (profile pages)
    employers = (
        EmployerCluster.objects
        .filter(slug__isnull=False)
        .exclude(canonical_name="Unknown")
        .exclude(slug="unknown")
    )
    
    # Apply search filter
    if query:
        # Search case-insensitively (icontains is already case-insensitive)
        # Try to match the query in canonical name
        query_clean = query.strip()
        employers = employers.filter(canonical_name__icontains=query_clean)
    
    # Apply state filter
    if state_filter:
        # Filter employers that have filings in the specified state
        # Use subquery to find clusters with employers that have salary records in this state
        employers_in_state = Employer.objects.filter(
            canonical_cluster=OuterRef('pk'),
            salary_records__worksite_state=state_filter,
        )
        
        employers = employers.filter(
            Exists(employers_in_state)
        ).distinct()
    
    # Calculate actual counts from SalaryRecord objects (more accurate than aggregated fields)
    # Count H-1B records (visa_program = 1) - count distinct SalaryRecord IDs
    employers = employers.annotate(
        actual_lca_count=Count(
            'employers__salary_records__id',
            filter=Q(employers__salary_records__visa_program=VisaProgram.H1B),
            distinct=True,
        )
    )
    # Count PERM records (visa_program = 4) - count distinct SalaryRecord IDs
    employers = employers.annotate(
        actual_perm_count=Count(
            'employers__salary_records__id',
            filter=Q(employers__salary_records__visa_program=VisaProgram.PERM),
            distinct=True,
        )
    )
    
    # Calculate total count based on program filter
    if program_filter == 'h1b':
        employers = employers.annotate(
            total_count=F('actual_lca_count')
        )
    elif program_filter == 'perm':
        employers = employers.annotate(
            total_count=F('actual_perm_count')
        )
    else:  # all
        employers = employers.annotate(
            total_count=F('actual_lca_count') + F('actual_perm_count')
        )
    
    # Order by total count
    employers = employers.order_by('-total_count')
    
    # Get total results
    total_results = employers.count()
    
    # Check if there are employers matching the query but without slugs (for helpful feedback)
    has_employers_without_slugs = False
    if query and total_results == 0:
        # Check if there are any employers matching the query that don't have slugs
        matching_without_slugs = EmployerCluster.objects.filter(
            canonical_name__icontains=query.strip(),
            slug__isnull=True,
        ).exists()
        has_employers_without_slugs = matching_without_slugs
    
    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)
    employers = employers[pagination['offset']:pagination['offset'] + per_page]
    
    # Build params dict for pagination
    params = {
        'query': query,
        'program_filter': program_filter,
        'state_filter': state_filter,
        'page': page,
    }
    
    context = {
        # Search parameters
        'query': query,
        'program_filter': program_filter,
        'state_filter': state_filter,
        
        # Filter options
        'states': US_STATES,
        
        # Autocomplete URL
        'company_autocomplete_url': request.build_absolute_uri(reverse('company_autocomplete')),
        
        # Results
        'employers': employers,
        'total_results': total_results,
        'has_employers_without_slugs': has_employers_without_slugs,
        
        # Pagination
        'page': pagination['page'],
        'total_pages': pagination['total_pages'],
        'per_page': per_page,
        'page_start': pagination['offset'] + 1 if total_results > 0 else 0,
        'page_end': min(pagination['offset'] + per_page, total_results),
        'has_pagination': pagination['total_pages'] > 1,
        'pagination_query': build_pagination_query_string(params),
        'page_range': pagination['page_range'],
        
        # SEO
        'page_title': 'Employer Directory - H-1B & PERM Sponsors | U.S. Immigration Data',
        'page_description': 'Browse top employers sponsoring H-1B and PERM visas. Search by company name, filter by state and visa program.',
    }
    
    return render(request, 'webapp/employer_directory.html', context)
