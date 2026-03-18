"""Salary and worksite search views."""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Max, Min
from django.shortcuts import render
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from lib.business.salary.common_chart_builder import (
    build_filing_volume_chart,
    build_geographic_chart,
    build_geographic_median_chart,
    build_salary_trend_chart,
)
from lib.business.salary.market_overview import get_market_overview_stats
from lib.utils.filter_utils import (
    apply_filing_year_filter,
    apply_fiscal_year_filter,
    apply_text_search_filter,
    apply_visa_program_filter,
)
from lib.utils.location_utils import US_STATES
from lib.utils.pagination import (
    build_pagination_query_string,
    calculate_pagination_info,
)
from models.salary import SalaryRecord, WorksiteRecord
from webapp.forms import SalarySearchForm, WorksiteSearchForm


def _get_cached_fiscal_years() -> list[int]:
    """
    Get available fiscal years with caching.

    Fiscal years change infrequently (monthly), so we cache for 24 hours.
    Cache key invalidates when new data is imported.
    """
    cache_key = "salary_fiscal_years"
    fiscal_years = cache.get(cache_key)

    if fiscal_years is None:
        fiscal_years = list(
            SalaryRecord.objects.exclude(fiscal_year__isnull=True)
            .values_list("fiscal_year", flat=True)
            .distinct()
            .order_by("-fiscal_year")
        )
        cache.set(cache_key, fiscal_years)

    return fiscal_years


def _get_cached_filing_years() -> list[int]:
    """
    Get available filing years (from case_submitted) with caching.
    """
    cache_key = "salary_filing_years"
    filing_years = cache.get(cache_key)

    if filing_years is None:
        from django.db.models.functions import ExtractYear

        filing_years = list(
            SalaryRecord.objects.exclude(case_submitted__isnull=True)
            .annotate(year=ExtractYear("case_submitted"))
            .values_list("year", flat=True)
            .distinct()
            .order_by("-year")
        )
        cache.set(cache_key, filing_years)

    return filing_years


# Note: @cache_page automatically varies by query parameters, so different searches have different cache keys
# Cache is cleared when server restarts or via: bazel run //scripts:clear_cache
@cache_page_skip_bots(settings.CACHE_TIMEOUT)
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
    filing_years = _get_cached_filing_years()

    # Initialize form with dynamic fiscal year choices
    form = SalarySearchForm(request.GET)
    form.fields["year"].choices = [("", "All Years")] + [
        (str(y), f"FY {y}") for y in fiscal_years
    ]
    form.fields["filing_year"].choices = [("", "All Years")] + [
        (str(y), str(y)) for y in filing_years
    ]

    per_page = 50

    # Extract cleaned form data, with fallback to request.GET for robustness
    # This ensures filters work even if form validation fails
    cleaned_data = form.cleaned_data if form.is_valid() else {}
    query = cleaned_data.get("q") or request.GET.get("q", "") or ""
    employer_filter = (
        cleaned_data.get("employer") or request.GET.get("employer", "") or ""
    )
    state_filter = cleaned_data.get("state") or request.GET.get("state", "") or ""
    program_filter = cleaned_data.get("program") or request.GET.get("program", "") or ""
    # 'year' parameter now refers to fiscal year (unchanged)
    fiscal_year_filter = cleaned_data.get("year") or request.GET.get("year") or None
    filing_year_filter = (
        cleaned_data.get("filing_year") or request.GET.get("filing_year") or None
    )
    try:
        page = cleaned_data.get("page") or int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page = 1

    # Build params dict for compatibility with existing code
    params = {
        "query": query,
        "employer_filter": employer_filter,
        "state_filter": state_filter,
        "program_filter": program_filter,
        "year_filter": str(fiscal_year_filter) if fiscal_year_filter else "",
        "filing_year_filter": str(filing_year_filter) if filing_year_filter else "",
        "page": page,
    }

    # Check if any data exists (cache this check)
    cache_key_no_data = "salary_has_data"
    no_data_yet = cache.get(cache_key_no_data)
    if no_data_yet is None:
        no_data_yet = SalaryRecord.objects.count() == 0
        cache.set(cache_key_no_data, no_data_yet)

    # Build and apply filters FIRST (before expensive exclude)
    # This reduces the dataset size before the expensive exclude operation
    has_filters = any(
        [
            query,
            employer_filter,
            state_filter,
            program_filter,
            fiscal_year_filter,
            filing_year_filter,
        ]
    )
    records = SalaryRecord.objects.all()

    # Apply filters using generic utilities
    records = apply_text_search_filter(records, query, ["job_title", "soc_title"])
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
    records = apply_fiscal_year_filter(records, fiscal_year_filter)
    records = apply_filing_year_filter(records, filing_year_filter)

    # Exclude worksite records AFTER applying filters (reduces dataset size)
    # Use indexed is_worksite field for fast filtering (much faster than source_file pattern matching)
    records = records.exclude(is_worksite=True)

    # Also exclude records with 'Unknown' employer (safety measure - worksite records should be filtered above,
    # but this catches any edge cases where is_worksite flag isn't set correctly)
    records = records.exclude(employer_name="Unknown")

    # Exclude records without a usable annual salary to avoid null/zero bands in the UI
    records = records.filter(wage_annual__isnull=False, wage_annual__gt=0)

    # Only calculate statistics when filters are applied (expensive query)
    if has_filters:
        stats = records.filter(wage_annual__isnull=False, wage_annual__gt=0).aggregate(
            avg_salary=Avg("wage_annual"),
            min_salary=Min("wage_annual"),
            max_salary=Max("wage_annual"),
        )
    else:
        # No filters - don't calculate expensive stats
        stats = {
            "avg_salary": None,
            "min_salary": None,
            "max_salary": None,
        }

    market_stats = None
    market_chart_data = {}
    if not has_filters and not no_data_yet:
        market_stats = get_market_overview_stats()
        geographic_dist = market_stats.get("geographic_dist", [])
        geographic_dist_by_median = market_stats.get("geographic_dist_by_median", [])
        yoy_trends = market_stats.get("yoy_trends", [])

        if geographic_dist:
            market_chart_data["state_filings"] = build_geographic_chart(
                geographic_dist,
                "Filings by State",
            )
        if geographic_dist_by_median:
            market_chart_data["state_median_salary"] = build_geographic_median_chart(
                geographic_dist_by_median,
                "Median Salary by State",
            )
        if yoy_trends:
            filing_volume_chart = build_filing_volume_chart(
                yoy_trends,
                "Filing Volume Over Time",
            )
            if filing_volume_chart:
                market_chart_data["filing_volume"] = filing_volume_chart

            salary_trend_chart = build_salary_trend_chart(
                yoy_trends,
                "Median Salary Trend",
            )
            if salary_trend_chart:
                market_chart_data["salary_trend"] = salary_trend_chart

    # Get total results - needed for pagination
    # Cache counts for common filter combinations to avoid expensive count operations
    # The exclude() on source_file causes full table scans, so caching is critical
    cache_key_count = None
    if not has_filters:
        cache_key_count = "salary_non_worksite_count"
    elif params["program_filter"] == "h1b" and not any(
        [
            params["query"],
            params["employer_filter"],
            params["state_filter"],
            params["year_filter"],
            params["filing_year_filter"],
        ]
    ):
        # Common case: just program=h1b filter (no other filters)
        cache_key_count = "salary_h1b_non_worksite_count"
    elif params["program_filter"] == "perm" and not any(
        [
            params["query"],
            params["employer_filter"],
            params["state_filter"],
            params["year_filter"],
            params["filing_year_filter"],
        ]
    ):
        # Common case: just program=perm filter (no other filters)
        cache_key_count = "salary_perm_non_worksite_count"

    if cache_key_count:
        total_results = cache.get(cache_key_count)
        if total_results is None:
            total_results = records.count()
            cache.set(cache_key_count, total_results)
    else:
        # For complex filters, calculate count (but this will be slow)
        total_results = records.count()

    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)

    # Use select_related for employer and job title cluster slugs (profile links)
    # Use only() to reduce data loaded - we only need these fields for the list view
    records = (
        records.select_related(
            "employer__canonical_cluster",
            "job_title_entity__canonical_cluster",
        )
        .only(
            "id",
            "employer_name",
            "job_title",
            "job_title_entity_id",
            "worksite_city",
            "worksite_state",
            "wage_annual",
            "wage_to",
            "visa_program",
            "fiscal_year",
            "employer__canonical_cluster__slug",
        )
        .order_by("-wage_annual", "-fiscal_year")[
            pagination["offset"] : pagination["offset"] + per_page
        ]
    )

    context = {
        # Form for rendering
        "form": form,
        # Search parameters (for backward compatibility with templates)
        "query": query,
        "employer_filter": employer_filter,
        "state_filter": state_filter,
        "program_filter": program_filter,
        "year_filter": str(fiscal_year_filter) if fiscal_year_filter else "",
        "filing_year_filter": str(filing_year_filter) if filing_year_filter else "",
        # Filter options
        "states": US_STATES,
        "fiscal_years": fiscal_years,
        "filing_years": filing_years,
        # Results
        "records": records,
        "has_data": has_filters or not no_data_yet,
        "has_filters": has_filters,
        "no_data_yet": no_data_yet,
        # Statistics
        "total_results": total_results,
        "avg_salary": stats["avg_salary"],
        "min_salary": stats["min_salary"],
        "max_salary": stats["max_salary"],
        "market_stats": market_stats,
        "market_chart_data": market_chart_data,
        # Pagination
        "page": pagination["page"],
        "total_pages": pagination["total_pages"],
        "per_page": per_page,
        "page_start": pagination["offset"] + 1
        if total_results and total_results > 0
        else 0,
        "page_end": min(pagination["offset"] + per_page, total_results)
        if total_results
        else 0,
        "has_pagination": pagination["total_pages"] > 1,
        "pagination_query": build_pagination_query_string(params),
        "page_range": pagination["page_range"],
        # SEO
        "page_title": "H-1B & PERM Salary Database | U.S. Immigration Data",
        "page_description": "Search H-1B and PERM salary data from official DOL disclosure files. Find salaries by role, employer, and location.",
        # Autocomplete URLs (shared component used for both Job Title and Employer)
        "company_autocomplete_url": request.build_absolute_uri(
            reverse("company_autocomplete")
        ),
        "job_title_autocomplete_url": request.build_absolute_uri(
            reverse("job_title_autocomplete")
        ),
    }

    return render(request, "webapp/salary_search.html", context)


def _get_cached_worksite_fiscal_years() -> list[int]:
    """Get available fiscal years for worksite records with caching."""
    cache_key = "worksite_fiscal_years"
    fiscal_years = cache.get(cache_key)

    if fiscal_years is None:
        fiscal_years = list(
            WorksiteRecord.objects.exclude(fiscal_year__isnull=True)
            .values_list("fiscal_year", flat=True)
            .distinct()
            .order_by("-fiscal_year")
        )
        cache.set(cache_key, fiscal_years)

    return fiscal_years


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
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
    form.fields["year"].choices = [("", "All Years")] + [
        (str(y), f"FY {y}") for y in fiscal_years
    ]

    per_page = 50

    # Extract cleaned form data
    cleaned_data = form.cleaned_data if form.is_valid() else {}
    query = cleaned_data.get("q", "") or ""
    state_filter = cleaned_data.get("state", "") or ""
    city_filter = cleaned_data.get("city", "") or ""
    program_filter = cleaned_data.get("program", "") or ""
    year_filter = cleaned_data.get("year")
    page = cleaned_data.get("page", 1) or 1

    # Build params dict for compatibility with existing code
    params = {
        "query": query,
        "state_filter": state_filter,
        "city_filter": city_filter,
        "program_filter": program_filter,
        "year_filter": str(year_filter) if year_filter else "",
        "page": page,
    }

    # Check if any data exists (cache this check)
    cache_key_no_data = "worksite_has_data"
    no_data_yet = cache.get(cache_key_no_data)
    if no_data_yet is None:
        no_data_yet = WorksiteRecord.objects.count() == 0
        cache.set(cache_key_no_data, no_data_yet)

    # Build and apply filters
    records = WorksiteRecord.objects.all()
    has_filters = any([query, state_filter, city_filter, program_filter, year_filter])

    # Apply filters using generic utilities
    records = apply_text_search_filter(
        records, query, ["job_title", "soc_title", "worksite_city"]
    )
    if state_filter:
        records = records.filter(worksite_state=state_filter)
    if city_filter:
        records = records.filter(worksite_city__icontains=city_filter)
    records = apply_visa_program_filter(records, program_filter)
    records = apply_fiscal_year_filter(records, year_filter)

    # Only calculate statistics when filters are applied (expensive query)
    if has_filters:
        stats = records.filter(wage_annual__isnull=False, wage_annual__gt=0).aggregate(
            avg_salary=Avg("wage_annual"),
            min_salary=Min("wage_annual"),
            max_salary=Max("wage_annual"),
        )
    else:
        # No filters - don't calculate expensive stats
        stats = {
            "avg_salary": None,
            "min_salary": None,
            "max_salary": None,
        }

    # Get total results - needed for pagination
    total_results = records.count()

    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)
    records = records.order_by("-wage_annual", "-fiscal_year")[
        pagination["offset"] : pagination["offset"] + per_page
    ]

    context = {
        # Form for rendering
        "form": form,
        # Search parameters (for backward compatibility with templates)
        "query": query,
        "state_filter": state_filter,
        "city_filter": city_filter,
        "program_filter": program_filter,
        "year_filter": year_filter,
        # Filter options
        "states": US_STATES,
        "fiscal_years": fiscal_years,
        # Results
        "records": records,
        "has_data": has_filters or not no_data_yet,
        "no_data_yet": no_data_yet,
        # Statistics
        "total_results": total_results,
        "avg_salary": stats["avg_salary"],
        "min_salary": stats["min_salary"],
        "max_salary": stats["max_salary"],
        # Pagination
        "page": pagination["page"],
        "total_pages": pagination["total_pages"],
        "per_page": per_page,
        "page_start": pagination["offset"] + 1
        if total_results and total_results > 0
        else 0,
        "page_end": min(pagination["offset"] + per_page, total_results)
        if total_results
        else 0,
        "has_pagination": pagination["total_pages"] > 1,
        "pagination_query": build_pagination_query_string(params),
        "page_range": pagination["page_range"],
        # SEO
        "page_title": "Worksite Location Data | U.S. Immigration Data",
        "page_description": "Search worksite location data from DOL Worksites disclosure files. Find job locations by city, state, and role.",
    }

    return render(request, "webapp/worksite_search.html", context)
