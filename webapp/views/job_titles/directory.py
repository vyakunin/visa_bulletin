"""Job title directory and autocomplete views."""

import json

from django.conf import settings
from django.db.models import Avg, Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from lib.utils.pagination import (
    build_pagination_query_string,
    calculate_pagination_info,
)
from models.job_title import JobTitleCluster

# Years for "recent" filings; must match scripts/salary/update_job_title_cluster_stats.RECENT_YEARS
AUTOCOMPLETE_YEARS = 5


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def job_title_autocomplete_view(request):
    """
    API endpoint for job title autocomplete suggestions.

    Uses JobTitleCluster.total_filings_recent (precomputed by update_job_title_cluster_stats
    for the last AUTOCOMPLETE_YEARS years). No live JOIN to salary_record; fast lookup.
    Ranks by recent filings so stale titles don't dominate.

    Query params:
        q: Search query (partial job title)
        limit: Maximum number of results (default: 20)

    Returns JSON array of objects with title, slug, total_filings (recent count).
    """
    query = request.GET.get("q", "").strip()
    limit = int(request.GET.get("limit", 20))

    if not query or len(query) < 2:
        return HttpResponse(json.dumps([]), content_type="application/json")

    clusters = JobTitleCluster.objects.filter(
        slug__isnull=False,
        total_filings_recent__gt=0,
        canonical_title__icontains=query,
    ).order_by("-total_filings_recent", "canonical_title")[:limit]

    suggestions = [
        {
            "slug": c.slug,
            "title": c.canonical_title,
            "total_filings": c.total_filings_recent,
        }
        for c in clusters
    ]

    return HttpResponse(json.dumps(suggestions), content_type="application/json")


def _get_job_title_directory_base_queryset():
    """Return base queryset for job title directory listings."""
    return JobTitleCluster.objects.filter(slug__isnull=False, total_filings__gt=0)


def _get_job_title_directory_summary(titles):
    """Aggregate summary stats for the job title directory."""
    return titles.aggregate(
        total_titles=Count("id"),
        total_filings=Sum("total_filings"),
        avg_salary=Avg("avg_salary"),
    )


def _get_job_title_directory_featured(titles):
    """Return featured job title lists for the directory page."""
    return {
        "popular_titles": list(
            titles.order_by("-total_filings", "canonical_title")[:12]
        ),
        "top_salary_titles": list(
            titles.exclude(avg_salary__isnull=True)
            .filter(
                total_filings__gte=10
            )  # Require >= 10 filings for meaningful average
            .order_by("-avg_salary")[:6]
        ),
    }


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def job_title_directory_view(request):
    """
    Job title directory page with search and top roles.

    Query params:
        q: Search query (job title)
        page: Page number for pagination
    """
    query = request.GET.get("q", "").strip()
    try:
        page = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page = 1

    per_page = 50
    base_titles = _get_job_title_directory_base_queryset()
    summary = _get_job_title_directory_summary(base_titles)
    featured = _get_job_title_directory_featured(base_titles)

    titles = base_titles
    if query:
        titles = titles.filter(canonical_title__icontains=query)
    titles = titles.order_by("-total_filings", "canonical_title")

    total_results = titles.count()
    has_titles_without_slugs = False
    if query and total_results == 0:
        has_titles_without_slugs = JobTitleCluster.objects.filter(
            canonical_title__icontains=query,
            slug__isnull=True,
        ).exists()

    pagination = calculate_pagination_info(total_results, page, per_page)
    titles = titles[pagination["offset"] : pagination["offset"] + per_page]
    params = {
        "query": query,
        "page": page,
    }

    context = {
        "query": query,
        "titles": titles,
        "total_results": total_results,
        "summary": summary,
        "has_titles_without_slugs": has_titles_without_slugs,
        **featured,
        "page": pagination["page"],
        "total_pages": pagination["total_pages"],
        "per_page": per_page,
        "page_start": pagination["offset"] + 1 if total_results > 0 else 0,
        "page_end": min(pagination["offset"] + per_page, total_results),
        "has_pagination": pagination["total_pages"] > 1,
        "pagination_query": build_pagination_query_string(params),
        "page_range": pagination["page_range"],
        "page_title": "Job Title Directory - Salary Data by Role | U.S. Immigration Data",
        "page_description": "Explore salary and sponsorship data by job title. Browse top roles, view average salaries, and jump to detailed job title profiles.",
        "canonical_url": request.build_absolute_uri(),
        "job_title_autocomplete_url": request.build_absolute_uri(
            reverse("job_title_autocomplete")
        ),
    }

    return render(request, "webapp/job_title_directory.html", context)
