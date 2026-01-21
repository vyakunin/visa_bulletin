"""
Job title statistics aggregation for profile pages.

Provides comprehensive statistics for job title clusters including:
- Market overview (filings, salary, growth)
- Salary distribution (percentiles, histogram)
- Top employers
- Geographic distribution
- Experience level analysis
- Year-over-year trends
- Related job titles
"""

from datetime import datetime
from django.db.models import Q, Avg, Count, Max, Min, StdDev
from django.core.cache import cache
from models.salary import SalaryRecord
from models.job_title import JobTitle, JobTitleCluster
from lib.business.salary.common_stats import (
    apply_program_filter,
    calculate_geographic_distributions,
    calculate_salary_histogram_with_experience_overlays,
    calculate_salary_histogram_with_overlays,
    calculate_salary_percentiles,
    calculate_yoy_growth,
    calculate_yoy_trends,
)

GROWTH_PARTIAL_YEAR_MIN_RATIO = 0.6


def get_job_title_statistics(
    cluster: JobTitleCluster,
    years: int = 5,
    program_filter: str = 'all',
    experience_level: str | None = None,
    normalized_title: str | None = None,
) -> dict:
    """
    Compute comprehensive statistics for a job title cluster.
    
    Args:
        cluster: JobTitleCluster instance
        years: Number of fiscal years to include (default: 5)
        program_filter: Visa program filter ('all', 'h1b', 'perm')
        experience_level: Experience level filter (None for all, '' for unspecified)
        normalized_title: Base normalized title for aggregating across levels
    
    Returns:
        Dictionary with all statistics sections
    """
    # Build cache key
    level_cache_key = 'all'
    if experience_level == '':
        level_cache_key = 'unspecified'
    elif experience_level:
        level_cache_key = experience_level
    if normalized_title:
        base_key = f"normalized:{normalized_title}"
    else:
        base_key = f"cluster:{cluster.id}"
    cache_key = f"job_title_stats:{base_key}:{program_filter}:{years}:{level_cache_key}"
    stats = cache.get(cache_key)
    
    if stats is not None:
        return stats
    
    # Calculate start year
    current_year = datetime.now().year
    start_year = current_year - years
    
    # Build base queryset - use normalized title when aggregating across levels
    base_filters = {
        'fiscal_year__gte': start_year,
        'wage_annual__isnull': False,
        'wage_annual__gt': 0,
    }
    if normalized_title:
        base_filters['job_title_entity__title_normalized'] = normalized_title
    else:
        base_filters['job_title_entity__canonical_cluster'] = cluster
    records = SalaryRecord.objects.filter(**base_filters)
    
    # Apply program filter
    records = apply_program_filter(records, program_filter)

    if experience_level is not None:
        records = records.filter(job_title_entity__experience_level=experience_level)
    
    # A. Market Overview
    basic_stats = records.aggregate(
        total_filings=Count('id'),
        median_salary=Avg('wage_annual'),
        min_salary=Min('wage_annual'),
        max_salary=Max('wage_annual'),
        std_salary=StdDev('wage_annual'),
    )
    
    # Top 3 employers by filing count
    top_employers_brief = list(
        records
        .values('employer__canonical_cluster__canonical_name', 'employer__canonical_cluster__slug')
        .annotate(count=Count('id'))
        .order_by('-count')[:3]
    )
    
    # B. Salary Distribution (percentiles)
    salary_percentiles = calculate_salary_percentiles(records)
    
    # C. Top Employers for This Role
    top_employers = list(
        records
        .values(
            'employer__canonical_cluster__canonical_name',
            'employer__canonical_cluster__slug'
        )
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
            min_salary=Min('wage_annual'),
            max_salary=Max('wage_annual'),
            approval_rate=Count('id', filter=Q(case_status=1)) * 100.0 / Count('id'),
        )
        .order_by('-count')[:15]
    )

    # Salary histogram data (overall + top employer overlays)
    overlay_employers = [
        employer['employer__canonical_cluster__canonical_name']
        for employer in top_employers[:5]
        if employer.get('employer__canonical_cluster__canonical_name')
    ]
    salary_histogram = calculate_salary_histogram_with_overlays(
        records,
        overlay_employers,
    )
    
    # D. Experience vs Salary Analysis
    experience_analysis = list(
        records
        .values('job_title_entity__experience_level')
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
            min_salary=Min('wage_annual'),
            max_salary=Max('wage_annual'),
        )
        .order_by('job_title_entity__experience_level')
    )
    for item in experience_analysis:
        item['experience_level_display'] = JobTitle.format_experience_level(
            item.get('job_title_entity__experience_level')
        )
    experience_levels = {
        item['job_title_entity__experience_level']
        for item in experience_analysis
        if item.get('job_title_entity__experience_level')
    }
    experience_has_unspecified = any(
        not item.get('job_title_entity__experience_level')
        for item in experience_analysis
    )
    experience_order = [
        'entry',
        'junior',
        'mid',
        'senior',
        'staff',
        'principal',
        'lead',
        'manager',
        'director',
    ]
    roman_order = ['i', 'ii', 'iii', 'iv', 'v']
    experience_levels_sorted = [
        level for level in experience_order if level in experience_levels
    ]
    experience_levels_sorted.extend(
        [level for level in roman_order if level in experience_levels]
    )
    remaining_levels = sorted(experience_levels - set(experience_levels_sorted))
    experience_levels_sorted.extend(remaining_levels)
    experience_has_levels = bool(experience_levels)
    experience_salary_histogram = calculate_salary_histogram_with_experience_overlays(
        records,
        experience_levels_sorted,
        include_unspecified=experience_has_unspecified,
    )
    for overlay in experience_salary_histogram.get("overlays", []):
        overlay["employer_name"] = JobTitle.format_experience_level(
            overlay.get("employer_name")
        )
    
    # E. Geographic Distribution
    geographic_dist, geographic_dist_by_median = calculate_geographic_distributions(
        records,
        limit=20,
    )
    
    # Top metro areas (city + state combinations)
    top_metros = list(
        records
        .exclude(worksite_city='')
        .exclude(worksite_state='')
        .values('worksite_city', 'worksite_state')
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
        )
        .order_by('-count')[:10]
    )
    
    # F. Related Job Titles (other titles in same cluster)
    related_titles = list(
        JobTitle.objects
        .filter(canonical_cluster=cluster)
        .exclude(total_filings=0)
        .annotate(
            filing_count=Count('salary_records')
        )
        .order_by('-total_filings')[:20]
    )
    
    # G. Year-over-Year Trends
    yoy_trends = calculate_yoy_trends(records)

    # Growth calculation (use latest non-partial year when possible)
    (
        yoy_growth,
        growth_start_year,
        growth_end_year,
        used_partial_year,
    ) = calculate_yoy_growth(
        yoy_trends,
        start_year,
        min_ratio=GROWTH_PARTIAL_YEAR_MIN_RATIO,
    )
    
    # H. Company Comparison (top 5 employers with detailed stats)
    company_comparison = list(
        records
        .values(
            'employer__canonical_cluster__canonical_name',
            'employer__canonical_cluster__slug'
        )
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
            approval_rate=Count('id', filter=Q(case_status=1)) * 100.0 / Count('id'),
        )
        .order_by('-count')[:5]
    )
    
    # Compile all stats
    stats = {
        'basic': basic_stats,
        'top_employers_brief': top_employers_brief,
        'yoy_growth': yoy_growth,
        'growth_period': {
            'start_year': growth_start_year,
            'end_year': growth_end_year,
            'used_partial_year': used_partial_year,
        },
        'salary_percentiles': salary_percentiles,
        'salary_histogram': salary_histogram,
        'top_employers': top_employers,
        'experience_analysis': experience_analysis,
        'experience_has_levels': experience_has_levels,
        'experience_salary_histogram': experience_salary_histogram,
        'geographic_dist': geographic_dist,
        'geographic_dist_by_median': geographic_dist_by_median,
        'top_metros': top_metros,
        'related_titles': related_titles,
        'yoy_trends': yoy_trends,
        'company_comparison': company_comparison,
    }
    
    # Cache for 6 hours
    cache.set(cache_key, stats, timeout=60*60*6)
    
    return stats




def get_related_job_titles(
    cluster: JobTitleCluster,
    limit: int = 20,
    normalized_title: str | None = None,
) -> list[dict]:
    """
    Get related job titles from the same cluster with career progression paths.
    
    Returns titles grouped by experience level for career path visualization.
    """
    if normalized_title:
        base_key = f"normalized:{normalized_title}"
    else:
        base_key = f"cluster:{cluster.id}"
    cache_key = f"job_title_related:{base_key}:{limit}"
    related = cache.get(cache_key)
    
    if related is not None:
        return related
    
    # Get all job titles in cluster with statistics
    title_query = JobTitle.objects.exclude(total_filings=0)
    if normalized_title:
        title_query = title_query.filter(title_normalized=normalized_title)
    else:
        title_query = title_query.filter(canonical_cluster=cluster)
    titles = list(
        title_query
        .values(
            'title',
            'title_normalized',
            'experience_level',
            'total_filings',
            'avg_salary'
        )
        .order_by('-total_filings')[:limit]
    )
    
    # Group by experience level for career path visualization
    experience_groups = {
        'entry': [],
        'junior': [],
        'mid': [],
        'senior': [],
        'staff': [],
        'principal': [],
        'lead': [],
        'manager': [],
        'director': [],
        '': [],  # Unspecified
    }
    
    for title in titles:
        level = title['experience_level'] or ''
        if level in experience_groups:
            experience_groups[level].append(title)
    
    related = {
        'all_titles': titles,
        'by_experience': experience_groups,
    }
    
    # Cache for 6 hours
    cache.set(cache_key, related, timeout=60*60*6)
    
    return related
