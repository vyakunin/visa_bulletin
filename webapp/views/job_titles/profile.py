"""Job title profile views."""

from datetime import datetime

from django.http import Http404
from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django_config.cache_utils import cache_page_skip_bots
from django.db.models import F

from lib.business.salary.job_title_stats import get_job_title_statistics, get_related_job_titles
from lib.business.salary.job_title_chart_builder import build_job_title_profile_charts
from models.job_title import JobTitle, JobTitleCluster


def _cache_profile_view(timeout_seconds: int):
    """Cache profile pages unless running tests (test DB name starts with test_)."""
    db_name = settings.DATABASES.get("default", {}).get("NAME") or ""
    if db_name.startswith("test_"):
        def _decorator(view_func):
            return view_func
        return _decorator
    return cache_page_skip_bots(timeout_seconds)


@_cache_profile_view(settings.CACHE_TIMEOUT)
def job_title_profile_view(request, slug: str):
    """
    Job title profile page - comprehensive market analysis for a specific job title.
    
    URL Pattern: /job-title/{slug}/
    
    Sections:
    A. Market Overview (total filings, median salary, top employers, growth)
    B. Salary Distribution (histogram, percentiles)
    C. Top Employers for This Role
    D. Experience vs Salary Analysis
    E. Geographic Salary Distribution
    F. Related Job Titles
    G. Year-over-Year Trends
    H. Company Comparison for This Role
    
    Query params:
        years: Number of fiscal years to show (default: 5, max: 20)
        program: Filter by visa program (h1b, perm, all) (default: all)
    """
    # 1. Try to find cluster by slug
    try:
        cluster = JobTitleCluster.objects.get(slug=slug)
    except JobTitleCluster.DoesNotExist:
        # 2. Try to find by title variation and redirect
        slug_normalized = slug.replace('-', ' ').lower()
        job_titles = JobTitle.objects.filter(
            title_normalized__icontains=slug_normalized
        ).select_related('canonical_cluster')
        
        if job_titles.exists():
            canonical_cluster = job_titles.first().canonical_cluster
            if canonical_cluster and canonical_cluster.slug:
                return redirect('job_title_profile', slug=canonical_cluster.slug, permanent=True)
        
        # 3. Not found - raise 404
        raise Http404(f"Job title '{slug}' not found")
    
    # Get query parameters
    try:
        years = min(int(request.GET.get('years', 5)), 20)  # Max 20 years
    except (ValueError, TypeError):
        years = 5
    
    program_filter = request.GET.get('program', 'all').lower()

    level_param = request.GET.get('level', 'all').lower().strip()
    level_choices = list(JobTitle._meta.get_field('experience_level').choices)
    level_values = {value for value, _ in level_choices if value}
    if level_param == 'unspecified':
        experience_level = ''
        level_filter = 'unspecified'
    elif level_param in level_values:
        experience_level = level_param
        level_filter = level_param
    else:
        experience_level = None
        level_filter = 'all'
    
    # Calculate start year
    current_year = datetime.now().year
    start_year = current_year - years

    # Use cluster-level stats (normalized_title=None) so total_filings matches
    # JobTitleCluster.total_filings and directory "Popular Job Titles".
    stats = get_job_title_statistics(
        cluster,
        years,
        program_filter,
        experience_level=experience_level,
        normalized_title=None,
    )

    # Related job titles for this cluster (all titles in cluster)
    related = get_related_job_titles(
        cluster,
        limit=20,
        normalized_title=None,
    )
    
    # Build chart data
    chart_data = build_job_title_profile_charts(stats, cluster.canonical_title)
    
    # Get similar job titles (from other clusters with similar names)
    similar_clusters = []
    if cluster.canonical_title:
        # Find clusters with similar canonical titles
        similar_clusters = list(
            JobTitleCluster.objects
            .filter(slug__isnull=False)
            .exclude(id=cluster.id)
            .filter(canonical_title__icontains=cluster.canonical_title.split()[0])  # Match first word
            .annotate(total_count=F('total_filings'))
            .order_by('-total_count')[:5]
        )

    # Build SEO metadata (use cluster.total_filings so it matches directory)
    total_filings = cluster.total_filings or 0
    median_salary = stats['basic'].get('median_salary') or 0
    seo = {
        'title': f"{cluster.canonical_title} Salary Data & Market Analysis | Visa Bulletin",
        'description': f"{cluster.canonical_title} visa sponsorship statistics: {total_filings:,} filings, ${median_salary:,.0f} median salary. Top employers, salary trends, and geographic data.",
        'canonical_url': request.build_absolute_uri(),
    }
    
    context = {
        'cluster': cluster,
        'stats': stats,
        'related': related,
        'chart_data': chart_data,
        'seo': seo,
        'years': years,
        'program_filter': program_filter,
        'level_filter': level_filter,
        'level_choices': level_choices,
        'start_year': start_year,
        'similar_clusters': similar_clusters,
        'job_title_autocomplete_url': request.build_absolute_uri(reverse('job_title_autocomplete')),
        # Base template variables for SEO
        'page_title': seo['title'],
        'page_description': seo['description'],
        'canonical_url': seo['canonical_url'],
    }
    
    return render(request, 'webapp/job_title_profile.html', context)
