"""Job title directory and autocomplete views."""

import json

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_page
from django.db.models import Avg, Case, Count, F, IntegerField, OuterRef, Subquery, Sum, Value, When

from lib.utils.pagination import calculate_pagination_info, build_pagination_query_string
from models.job_title import JobTitle, JobTitleCluster


@cache_page(60 * 60)  # Cache for 1 hour
def job_title_autocomplete_view(request):
    """
    API endpoint for job title autocomplete suggestions.
    
    Query params:
        q: Search query (partial job title)
        limit: Maximum number of results (default: 20)
    
    Returns JSON array of objects with title and slug.
    """
    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 20))
    
    if not query or len(query) < 2:
        return HttpResponse(json.dumps([]), content_type='application/json')
    
    normalized_query = JobTitle.normalize_title(query)
    if not normalized_query:
        return HttpResponse(json.dumps([]), content_type='application/json')

    title_candidates = (
        JobTitle.objects
        .filter(
            title_normalized=OuterRef('title_normalized'),
            canonical_cluster__slug__isnull=False,
        )
        .annotate(
            has_level=Case(
                When(experience_level='', then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by('has_level', '-total_filings', 'title')
    )

    matches = (
        JobTitle.objects
        .filter(title_normalized__icontains=normalized_query)
        .exclude(total_filings=0)
        .values('title_normalized')
        .annotate(
            total_filings=Sum('total_filings'),
            slug=Subquery(title_candidates.values('canonical_cluster__slug')[:1]),
            display_title=Subquery(title_candidates.values('title')[:1]),
        )
        .filter(slug__isnull=False)
        .order_by('-total_filings', 'title_normalized')[:limit]
    )

    suggestions = []
    for match in matches:
        title = match['display_title'] or match['title_normalized'].title()
        suggestions.append({
            'slug': match['slug'],
            'title': title,
            'total_filings': match['total_filings'],
        })
    return HttpResponse(json.dumps(suggestions), content_type='application/json')


def _get_job_title_directory_base_queryset():
    """Return base queryset for job title directory listings."""
    return JobTitleCluster.objects.filter(slug__isnull=False, total_filings__gt=0)


def _get_job_title_directory_summary(titles):
    """Aggregate summary stats for the job title directory."""
    return titles.aggregate(
        total_titles=Count('id'),
        total_filings=Sum('total_filings'),
        avg_salary=Avg('avg_salary'),
    )


def _get_job_title_directory_featured(titles):
    """Return featured job title lists for the directory page."""
    return {
        'popular_titles': list(
            titles.order_by('-total_filings', 'canonical_title')[:12]
        ),
        'top_salary_titles': list(
            titles.exclude(avg_salary__isnull=True).order_by('-avg_salary')[:6]
        ),
    }


@cache_page(60 * 60)  # Cache for 1 hour
def job_title_directory_view(request):
    """
    Job title directory page with search and top roles.
    
    Query params:
        q: Search query (job title)
        page: Page number for pagination
    """
    query = request.GET.get('q', '').strip()
    try:
        page = int(request.GET.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    
    per_page = 50
    base_titles = _get_job_title_directory_base_queryset()
    summary = _get_job_title_directory_summary(base_titles)
    featured = _get_job_title_directory_featured(base_titles)
    
    titles = base_titles
    if query:
        titles = titles.filter(canonical_title__icontains=query)
    titles = titles.order_by('-total_filings', 'canonical_title')
    
    total_results = titles.count()
    has_titles_without_slugs = False
    if query and total_results == 0:
        has_titles_without_slugs = JobTitleCluster.objects.filter(
            canonical_title__icontains=query,
            slug__isnull=True,
        ).exists()
    
    pagination = calculate_pagination_info(total_results, page, per_page)
    titles = titles[pagination['offset']:pagination['offset'] + per_page]
    params = {
        'query': query,
        'page': page,
    }
    
    context = {
        'query': query,
        'titles': titles,
        'total_results': total_results,
        'summary': summary,
        'has_titles_without_slugs': has_titles_without_slugs,
        **featured,
        'page': pagination['page'],
        'total_pages': pagination['total_pages'],
        'per_page': per_page,
        'page_start': pagination['offset'] + 1 if total_results > 0 else 0,
        'page_end': min(pagination['offset'] + per_page, total_results),
        'has_pagination': pagination['total_pages'] > 1,
        'pagination_query': build_pagination_query_string(params),
        'page_range': pagination['page_range'],
        'page_title': 'Job Title Directory - Salary Data by Role | Visa Bulletin Dashboard',
        'page_description': 'Explore salary and sponsorship data by job title. Browse top roles, view average salaries, and jump to detailed job title profiles.',
    }
    
    return render(request, 'webapp/job_title_directory.html', context)
