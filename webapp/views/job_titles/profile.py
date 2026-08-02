"""Job title profile views."""

from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from lib.business.salary.h1b_salary_pair import qualifying_pairs
from lib.business.salary.h1b_sponsors import role_h1b_stats, role_qualifies
from lib.business.salary.job_title_chart_builder import build_job_title_profile_charts
from lib.business.salary.job_title_stats import (
    INDEXABLE_MIN_FILINGS,
    get_job_title_statistics,
    get_related_job_titles,
)
from lib.business.salary.similar_titles import (
    find_broader_role,
    rank_similar,
    salaries_search_token,
)
from lib.business.salary.slug_redirects import resolve_job_title_slug
from models.job_title import JobTitle, JobTitleCluster

# Cache key version — bump to invalidate all similar-cluster cache entries
# without flushing the rest of the cache (e.g. after re-clustering changes
# canonical_title for many clusters). v2 = token-overlap ranking over the
# indexable universe (similar_titles.rank_similar) instead of first-word
# icontains, which recommended every big "Senior *" cluster to any
# "Senior ..." title.
_SIMILAR_CLUSTERS_CACHE_VERSION = 2
# Day-long TTL: the canonical_title universe only changes when the clustering
# pipeline runs, and a one-day staleness on a "Related Job Titles" sidebar is
# imperceptible. Bot crawls walk every /job-title/<slug>/ — the per-cluster
# cache keeps the ranking off the request path.
_SIMILAR_CLUSTERS_CACHE_TTL = 60 * 60 * 24


def _get_similar_clusters(cluster: JobTitleCluster):
    """Up to 5 indexable clusters ranked by shared content tokens, cached."""
    if not cluster.canonical_title:
        return []
    cache_key = (
        f"job_title_similar.v{_SIMILAR_CLUSTERS_CACHE_VERSION}.{cluster.id}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    similar = rank_similar(cluster.canonical_title, cluster.slug)
    cache.set(cache_key, similar, _SIMILAR_CLUSTERS_CACHE_TTL)
    return similar


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
        # 2. Stale slug (re-clustering churn): resolve to the current
        # canonical slug via the indexed ladder in slug_redirects.
        target = resolve_job_title_slug(slug)
        if target and target != slug:
            return redirect("job_title_profile", slug=target, permanent=True)

        # 3. Not found - raise 404
        raise Http404(f"Job title '{slug}' not found")

    # Get query parameters
    try:
        years = min(int(request.GET.get("years", 5)), 20)  # Max 20 years
    except (ValueError, TypeError):
        years = 5

    program_filter = request.GET.get("program", "all").lower()

    level_param = request.GET.get("level", "all").lower().strip()
    level_choices = list(JobTitle._meta.get_field("experience_level").choices)
    level_values = {value for value, _ in level_choices if value}
    if level_param == "unspecified":
        experience_level = ""
        level_filter = "unspecified"
    elif level_param in level_values:
        experience_level = level_param
        level_filter = level_param
    else:
        experience_level = None
        level_filter = "all"

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

    # Cross-mesh: link each top employer to the dedicated "{role} salary at
    # {employer}" page when that pair qualifies (shared cached gate, never a 404).
    if cluster.slug:
        qual_pairs = set(qualifying_pairs())
        for e in stats.get("top_employers", []):
            es = e.get("employer__canonical_cluster__slug")
            e["pair_url"] = (
                f"/h1b-salary/{es}/{cluster.slug}/"
                if es and (es, cluster.slug) in qual_pairs
                else None
            )

    # Build chart data
    chart_data = build_job_title_profile_charts(stats, cluster.canonical_title)

    # Get similar job titles (from other clusters with similar names) —
    # cached per-cluster; see _get_similar_clusters.
    similar_clusters = _get_similar_clusters(cluster)

    # Inbound link to the dedicated "Top H-1B sponsors for {role}" page — only
    # when that page qualifies (shared gate), so we never link to a 404.
    h1b_filings, h1b_sponsors = role_h1b_stats(cluster.id)
    h1b_sponsors_url = (
        f"/h1b-sponsors/{cluster.slug}/"
        if cluster.slug and role_qualifies(h1b_filings, h1b_sponsors)
        else None
    )

    # Build SEO metadata (use cluster.total_filings so it matches directory)
    total_filings = cluster.total_filings or 0

    # Thin-page rescue: a searcher landing on a 1-3-filing hyper-specific
    # title has nothing to do here — hand them the broader indexable role
    # (content-token subset match) as a prominent CTA, plus a salaries-search
    # fallback so there is always a relevant next step.
    broader_role = None
    salaries_q = ""
    if total_filings < INDEXABLE_MIN_FILINGS:
        broader_role = find_broader_role(cluster.canonical_title, cluster.slug)
        salaries_q = salaries_search_token(cluster.canonical_title)
    median_salary = stats["basic"].get("median_salary") or 0
    seo = {
        "title": f"{cluster.canonical_title} Salary Data & Market Analysis | Visa Bulletin",
        "description": f"{cluster.canonical_title} visa sponsorship statistics: {total_filings:,} filings, ${median_salary:,.0f} median salary. Top employers, salary trends, and geographic data.",
        "canonical_url": request.build_absolute_uri(request.path),
    }

    context = {
        "cluster": cluster,
        "stats": stats,
        "related": related,
        "chart_data": chart_data,
        "seo": seo,
        "years": years,
        "program_filter": program_filter,
        "level_filter": level_filter,
        "level_choices": level_choices,
        "start_year": start_year,
        "similar_clusters": similar_clusters,
        "broader_role": broader_role,
        "salaries_q": salaries_q,
        "h1b_sponsors_url": h1b_sponsors_url,
        "job_title_autocomplete_url": request.build_absolute_uri(
            reverse("job_title_autocomplete")
        ),
        # Base template variables for SEO
        "page_title": seo["title"],
        "page_description": seo["description"],
        "canonical_url": seo["canonical_url"],
        # Thin-page gate: hyper-specific low-filing titles stay reachable
        # (follow keeps link equity flowing) but are kept out of the index —
        # they're the scaled-content-abuse suspect on this surface.
        "meta_robots": (
            "noindex, follow" if total_filings < INDEXABLE_MIN_FILINGS else None
        ),
        # Same condition as meta_robots, exposed to the template as the seam for
        # collapsing ad slots on thin pages (AdSense judges pages that SERVE ads,
        # which noindex does not cover). No consumer yet — see employer_stats.py.
        "thin_page": total_filings < INDEXABLE_MIN_FILINGS,
    }

    return render(request, "webapp/job_title_profile.html", context)
