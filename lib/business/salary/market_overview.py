"""
Market overview statistics for salary landing pages.
"""

from datetime import datetime

from django.core.cache import cache
from django.db.models import Count, Max, Min

from lib.business.salary.common_stats import (
    Median,
    apply_program_filter,
    calculate_geographic_distributions,
    calculate_market_overview_stats,
    calculate_salary_percentiles,
    calculate_yoy_trends,
    growth_headline,
)
from lib.business.salary.employer_stats import (
    employer_lifetime_filings,
    indexable_employer_clusters,
)
from models.enums.visa_program import VisaProgram
from models.job_title import JobTitleCluster
from models.salary import EmployerCluster, SalaryRecord


def get_market_overview_stats(years: int = 5, program_filter: str = "all") -> dict:
    """Return market-wide salary statistics for the landing page."""
    cache_key = f"salary_market_overview:{years}:{program_filter}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    current_year = datetime.now().year
    start_year = current_year - years

    records = SalaryRecord.objects.filter(
        fiscal_year__gte=start_year,
        wage_annual__isnull=False,
        wage_annual__gt=0,
        is_worksite=False,
    ).exclude(employer_name="Unknown")
    records = apply_program_filter(records, program_filter)

    basic_stats = calculate_market_overview_stats(records)
    salary_percentiles = calculate_salary_percentiles(records)
    basic_stats["median_salary"] = salary_percentiles["p50"]
    yoy_trends = calculate_yoy_trends(records)
    growth = growth_headline(yoy_trends, start_year)
    geographic_dist, geographic_dist_by_median = calculate_geographic_distributions(
        records,
        limit=20,
    )

    top_employers = list(
        records.filter(
            employer__canonical_cluster__slug__isnull=False,
        )
        .exclude(employer__canonical_cluster__canonical_name="Unknown")
        .exclude(employer__canonical_cluster__slug="unknown")
        .values(
            "employer__canonical_cluster__canonical_name",
            "employer__canonical_cluster__slug",
        )
        .annotate(count=Count("id"), median_salary=Median("wage_annual"))
        .order_by("-count")[:25]
    )

    top_job_titles = list(
        records.filter(job_title_entity__canonical_cluster__isnull=False)
        .values(
            "job_title_entity__canonical_cluster__canonical_title",
            "job_title_entity__canonical_cluster__slug",
        )
        .annotate(count=Count("id"), median_salary=Median("wage_annual"))
        .order_by("-count")[:25]
    )

    stats = {
        "basic": basic_stats,
        "salary_percentiles": salary_percentiles,
        "yoy_trends": yoy_trends,
        **growth,
        "geographic_dist": geographic_dist,
        "geographic_dist_by_median": geographic_dist_by_median,
        "top_employers": top_employers,
        "top_job_titles": top_job_titles,
        "start_year": start_year,
    }

    cache.set(cache_key, stats)
    return stats


def get_salary_explore_links(
    job_titles_limit: int = 12, employers_limit: int = 8
) -> dict:
    """Onward-navigation link sets for the /salaries/ "explore more" rail.

    Queried straight off the cluster tables (precomputed counts, indexed
    order-by) so it is cheap to render on EVERY salary search render —
    including filtered result pages, which carry no market_overview. This
    breaks the dead-end: result pages otherwise end at pagination with no
    onward path. Cached so it costs one query per cache cycle, not per request.
    """
    cache_key = f"salary_explore_links:{job_titles_limit}:{employers_limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    top_job_titles = list(
        JobTitleCluster.objects.exclude(slug__isnull=True)
        .exclude(slug="")
        .filter(total_filings__gt=0)
        .order_by("-total_filings")
        .values("slug", "canonical_title", "total_filings")[:job_titles_limit]
    )
    top_employers = list(
        EmployerCluster.objects.exclude(slug__isnull=True)
        .exclude(slug="")
        .exclude(slug="unknown")
        .exclude(canonical_name="Unknown")
        .filter(search_record_count__gt=0)
        .order_by("-search_record_count")
        .values("slug", "canonical_name", "search_record_count")[:employers_limit]
    )

    links = {"top_job_titles": top_job_titles, "top_employers": top_employers}
    cache.set(cache_key, links)
    return links


# Program values whose wage comes from an H-1B-family LCA; PERM is the other.
_LCA_PROGRAMS = (VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3)


def get_salary_database_summary() -> dict:
    """Coverage of the /salaries/ database: what a search can return.

    Counts the same rows the search page lists (non-worksite, a named employer,
    a positive annual wage), split into LCA (H-1B, H-1B1, E-3) and PERM.
    """
    cache_key = "salary_database_summary"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    searchable = SalaryRecord.objects.filter(
        is_worksite=False, wage_annual__isnull=False, wage_annual__gt=0
    ).exclude(employer_name="Unknown")
    by_program = dict(
        searchable.order_by()
        .values("visa_program")
        .annotate(n=Count("id"))
        .values_list("visa_program", "n")
    )
    span = searchable.aggregate(
        first_fiscal_year=Min("fiscal_year"),
        last_fiscal_year=Max("fiscal_year"),
        decided_through=Max("decision_date"),
    )
    summary = {
        "total_records": sum(by_program.values()),
        "lca_records": sum(by_program.get(p, 0) for p in _LCA_PROGRAMS),
        "perm_records": by_program.get(VisaProgram.PERM, 0),
        "employer_count": EmployerCluster.objects.filter(search_record_count__gt=0)
        .exclude(slug__isnull=True)
        .exclude(slug="unknown")
        .count(),
        **span,
    }
    cache.set(cache_key, summary)
    return summary


def get_salary_landing_employer_pages(limit: int = 60) -> list[dict]:
    """The largest indexable employer profiles, for the landing's link list."""
    cache_key = f"salary_landing_employer_pages:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # The gate's queryset arrives sliced, so the placeholder cluster (whose
    # profile 404s) is dropped here rather than filtered out.
    pages = [
        {
            "slug": c.slug,
            "canonical_name": c.canonical_name,
            "lifetime_filings": employer_lifetime_filings(c),
            "search_avg_salary": c.search_avg_salary,
        }
        for c in indexable_employer_clusters(limit=limit + 1)
        if c.slug != "unknown" and c.canonical_name != "Unknown"
    ][:limit]
    cache.set(cache_key, pages)
    return pages
