"""Salary and worksite search views."""

import hashlib
import json
from datetime import date as _date
from typing import NamedTuple

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
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
    fenced_aggregate,
    fenced_page_ids,
)
from lib.utils.location_utils import US_STATES
from lib.utils.pagination import (
    MAX_PAGE,
    build_pagination_query_string,
    calculate_pagination_info,
)
from models.salary import EmployerCluster, SalaryRecord, WorksiteRecord
from webapp.forms import SalarySearchForm, WorksiteSearchForm

_NO_STATS = {"avg_salary": None, "min_salary": None, "max_salary": None}

_PAGE_CAP_GONE_BODY = (
    "This page is beyond the listing depth cap (page=100). "
    "Use the filters at /salaries/ or /worksites/ to narrow your search."
)

_STATIC_PAGE_TITLE = (
    "H-1B & PERM Salary Database: What 1.5M+ DOL Filings Actually Pay "
    "(by Employer + Role)"
)
_STATIC_PAGE_DESCRIPTION = (
    "Look up real H-1B and PERM wages from official DOL filings — by company, "
    "job title, and city. Compare offers, negotiate, or research filing "
    "trends. Free."
)
_STATIC_PAGE_HEADING = "H-1B & Green Card Salary Database"
# SERP meta-description cap — Google currently truncates at ~155–160 chars.
_DESCRIPTION_MAX_CHARS = 165


class _SalarySEO(NamedTuple):
    """SEO/SERP fields for the salary search page, dynamic on active filters.

    page_intro is None when the page should render no intro paragraph
    (currently only on the bare /salaries/ landing). structured_data is a
    JSON-LD string (pre-escaped for <script> context) or None.
    """

    page_title: str
    page_description: str
    page_heading: str
    page_intro: str | None
    structured_data: str | None


def _program_label(program_filter: str) -> str:
    """Human-readable program label for SEO copy ('h1b' → 'H-1B')."""
    return {
        "h1b": "H-1B",
        "perm": "Green Card (PERM)",
    }.get(program_filter, "H-1B & PERM")


def _format_money(amount) -> str | None:
    """Format a numeric salary as $123,456, or None if unset/non-numeric."""
    if amount is None:
        return None
    try:
        return f"${float(amount):,.0f}"
    except (TypeError, ValueError):
        return None


def _embed_jsonld(payload: dict) -> str:
    """Serialize a JSON-LD payload safely for embedding in a <script> tag.

    Escapes the four characters that can break out of a <script> context
    (<, >, &, and the U+2028/U+2029 line terminators) per the OWASP JSON-in-
    HTML guidance. Without this, an employer name containing literal
    '</script>' would terminate the surrounding tag.
    """
    raw = json.dumps(payload, ensure_ascii=False)
    return (
        raw.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _build_dataset_jsonld(
    *,
    employer_name: str,
    canonical_url: str,
    total_results: int,
    avg_salary,
    min_salary,
    max_salary,
) -> str:
    """schema.org Dataset payload for an employer-scoped salary page."""
    avg_str = _format_money(avg_salary)
    min_str = _format_money(min_salary)
    max_str = _format_money(max_salary)
    avg_clause = f" Average {avg_str}." if avg_str else ""
    range_clause = (
        f" Range {min_str}–{max_str}." if (min_str and max_str) else ""
    )
    payload = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": f"{employer_name} H-1B & PERM Salary Records",
        "description": (
            f"{total_results:,} H-1B and PERM salary records at "
            f"{employer_name}, filed with the U.S. Department of Labor."
            f"{avg_clause}{range_clause}"
        ),
        "url": canonical_url,
        "keywords": (
            f"H-1B salary, PERM salary, green card salary, "
            f"{employer_name}, visa sponsorship"
        ),
        "creator": {
            "@type": "Organization",
            "name": "U.S. Department of Labor",
            "url": "https://www.dol.gov",
        },
        "publisher": {
            "@type": "Organization",
            "name": "U.S. Immigration Data",
            "url": "https://visa-bulletin.us",
        },
        "isAccessibleForFree": True,
        "license": "https://www.usa.gov/government-works",
        "dateModified": _date.today().isoformat(),
    }
    return _embed_jsonld(payload)


def _scope_clause(
    *,
    employer_label: str,
    query_label: str,
    state_label: str,
    fiscal_year_filter,
    filing_year_filter,
) -> str:
    """Compose the scope half of the meta description ('at X for "y" in CA')."""
    bits: list[str] = []
    if employer_label:
        bits.append(f"at {employer_label}")
    if query_label:
        bits.append(f'for "{query_label}"')
    if state_label:
        bits.append(f"in {state_label}")
    if fiscal_year_filter:
        bits.append(f"in fiscal year {fiscal_year_filter}")
    elif filing_year_filter:
        bits.append(f"filed in {filing_year_filter}")
    return " ".join(bits)


def _build_dynamic_title(
    *,
    employer_label: str,
    query_label: str,
    state_label: str,
    program_filter: str,
    fiscal_year_filter,
    filing_year_filter,
) -> str:
    """Pick a SERP-friendly title shape from the active filter combination."""
    if employer_label and query_label:
        return f"{query_label} at {employer_label} — H-1B & PERM Salaries"
    if employer_label:
        return f"{employer_label} — H-1B & PERM Salary Records"
    if query_label and state_label:
        return f"{query_label} Salaries in {state_label} — H-1B & PERM"
    if state_label:
        return f"{state_label} H-1B & PERM Salary Data"
    if query_label:
        return f"{query_label} Salaries — H-1B & PERM Database"
    if fiscal_year_filter:
        return f"FY{fiscal_year_filter} H-1B & PERM Salary Data"
    if filing_year_filter:
        return f"{filing_year_filter} H-1B & PERM Salary Filings"
    if program_filter:
        return f"{_program_label(program_filter)} Salary Data | U.S. Immigration Data"
    return _STATIC_PAGE_TITLE


def _build_dynamic_heading(
    *,
    employer_label: str,
    query_label: str,
    state_label: str,
) -> str:
    """Pick an H1 heading that mirrors the title but reads as a page header."""
    if employer_label and query_label:
        return f"{query_label} salaries at {employer_label}"
    if employer_label:
        return f"{employer_label} salary records"
    if query_label and state_label:
        return f"{query_label} salaries in {state_label}"
    if state_label:
        return f"{state_label} H-1B & PERM salaries"
    if query_label:
        return f"{query_label} salaries"
    return "Search results"


def _build_salary_seo(
    *,
    has_filters: bool,
    query: str,
    employer_filter: str,
    matched_cluster,
    state_filter: str,
    program_filter: str,
    fiscal_year_filter,
    filing_year_filter,
    total_results: int,
    avg_salary,
    min_salary,
    max_salary,
    canonical_url: str,
    page_url: str,
    state_name_map: dict[str, str],
) -> _SalarySEO:
    """Compute dynamic SEO fields so the SERP snippet and landed page both
    echo the searcher's exact query when filters are active. Bare /salaries/
    keeps the static copy so the high-impression landing page is unchanged.
    """
    if not has_filters:
        return _SalarySEO(
            page_title=_STATIC_PAGE_TITLE,
            page_description=_STATIC_PAGE_DESCRIPTION,
            page_heading=_STATIC_PAGE_HEADING,
            page_intro=None,
            structured_data=None,
        )

    employer_label = (
        matched_cluster.canonical_name
        if matched_cluster is not None
        else employer_filter.strip()
    )
    query_label = query.strip()
    state_label = state_name_map.get(state_filter.upper(), "") if state_filter else ""
    program_label = _program_label(program_filter)

    page_title = _build_dynamic_title(
        employer_label=employer_label,
        query_label=query_label,
        state_label=state_label,
        program_filter=program_filter,
        fiscal_year_filter=fiscal_year_filter,
        filing_year_filter=filing_year_filter,
    )
    page_heading = _build_dynamic_heading(
        employer_label=employer_label,
        query_label=query_label,
        state_label=state_label,
    )
    scope = _scope_clause(
        employer_label=employer_label,
        query_label=query_label,
        state_label=state_label,
        fiscal_year_filter=fiscal_year_filter,
        filing_year_filter=filing_year_filter,
    )
    count_label = f"{total_results:,}" if total_results else "No"
    avg_str = _format_money(avg_salary)
    min_str = _format_money(min_salary)
    max_str = _format_money(max_salary)

    base_clause = (
        f"{count_label} {program_label} salary records {scope}".rstrip()
    )
    avg_clause = f" Average {avg_str}." if avg_str else ""
    range_clause = (
        f" Range {min_str}–{max_str}." if (min_str and max_str) else ""
    )
    source_clause = " From official U.S. Department of Labor disclosure data."

    page_description = (
        f"{base_clause}.{avg_clause}{range_clause}{source_clause}"
    )
    if len(page_description) > _DESCRIPTION_MAX_CHARS:
        # Drop the source clause first; keep the data-bearing parts.
        page_description = (
            f"{base_clause}.{avg_clause}{range_clause}".strip()
        )

    page_intro = (
        f"{count_label} {program_label} records {scope}, sourced from "
        f"U.S. Department of Labor disclosures."
    ).strip()

    # Dataset JSON-LD only fires when an employer scope is present — that's
    # the page Google may surface as a structured "Dataset" rich result.
    structured_data = None
    if employer_label:
        structured_data = _build_dataset_jsonld(
            employer_name=employer_label,
            canonical_url=page_url,
            total_results=total_results,
            avg_salary=avg_salary,
            min_salary=min_salary,
            max_salary=max_salary,
        )

    return _SalarySEO(
        page_title=page_title,
        page_description=page_description,
        page_heading=page_heading,
        page_intro=page_intro,
        structured_data=structured_data,
    )


# Cap on how many cluster ids we resolve from a free-text employer search
# before handing them to the salary_record filter. With the trigram GIN, a
# typical multi-character substring matches 100–500 clusters; bots typing
# very short strings (`%A%`, `%I%`) can trigger tens of thousands of matches
# and the resulting `IN (...)` clause becomes the bottleneck instead of the
# downstream join. 2000 is well above any meaningful real search but keeps
# the planner's job bounded.
_MAX_CLUSTER_IDS = 2000


def _cached_count_and_stats(records, cache_scope: str, filter_parts: list[str]):
    """Cache (count, stats) for a filtered queryset.

    Combined into a single .aggregate() so it's one DB roundtrip instead of
    two (count + avg/min/max with the same WHERE clause). Cached under a
    fingerprint of the filter parts so identical searches don't re-aggregate.
    """
    fingerprint = hashlib.md5("|".join(filter_parts).encode()).hexdigest()
    key = f"{cache_scope}.{fingerprint}"
    cached = cache.get(key)
    if cached is not None:
        return cached["count"], cached["stats"]
    # Aggregate behind an OFFSET-0 fence (see fenced_aggregate). A plain
    # .aggregate() over a trigram + employer-FK + state filter compiles to a
    # Nested Loop Semi Join that re-scans the whole trigram match set and times
    # out (>120s → 504) for combos like q=Financial Analyst + Goldman + NY.
    agg = fenced_aggregate(records, "wage_annual")
    count = agg.count
    stats = {
        "avg_salary": agg.avg,
        "min_salary": agg.min,
        "max_salary": agg.max,
    }
    cache.set(key, {"count": count, "stats": stats})
    return count, stats


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
        (str(y), str(y)) for y in fiscal_years
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
    employer_slug_filter = (
        cleaned_data.get("employer_slug")
        or request.GET.get("employer_slug", "")
        or ""
    ).strip()
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

    if page > MAX_PAGE:
        return HttpResponse(_PAGE_CAP_GONE_BODY, status=410, content_type="text/plain")

    # Resolve the employer slug to a real cluster up front. If the slug doesn't
    # match anything (stale link, edited URL), drop it and fall back to the
    # text path so the user still gets results.
    matched_cluster = None
    if employer_slug_filter:
        matched_cluster = (
            EmployerCluster.objects.filter(slug=employer_slug_filter)
            .only(
                "id",
                "slug",
                "canonical_name",
                "search_record_count",
                "search_avg_salary",
                "search_min_salary",
                "search_max_salary",
            )
            .first()
        )
        if matched_cluster is None:
            employer_slug_filter = ""

    # Build params dict for compatibility with existing code
    params = {
        "query": query,
        "employer_filter": employer_filter,
        "employer_slug_filter": employer_slug_filter,
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
            employer_slug_filter,
            state_filter,
            program_filter,
            fiscal_year_filter,
            filing_year_filter,
        ]
    )
    records = SalaryRecord.objects.all()

    # Apply filters using generic utilities
    records = apply_text_search_filter(records, query, ["job_title", "soc_title"])
    if matched_cluster is not None:
        # Fast path: user picked a company from autocomplete, so we know the
        # exact cluster id. Filter on the indexed FK + slug (B-tree, ms) rather
        # than dragging every record through the trigram heap-scan that
        # __icontains on canonical_name compiles to.
        records = records.filter(
            employer__canonical_cluster_id=matched_cluster.id
        )
    elif employer_filter:
        # Free-text path: user typed a name and submitted without picking a
        # suggestion. Done in two queries so the planner can't trick itself
        # into a "scan wage_annual DESC, filter join" plan that ends up
        # touching half the table for common substrings like "STANDARD" —
        # see docs/PERFORMANCE_IMPROVEMENTS.md §A. The first query hits the
        # trigram index on canonical_name, the second is a plain FK lookup.
        cluster_ids = list(
            EmployerCluster.objects.filter(
                canonical_name__icontains=employer_filter
            ).values_list("id", flat=True)[:_MAX_CLUSTER_IDS]
        )
        if cluster_ids:
            records = records.filter(
                employer__canonical_cluster_id__in=cluster_ids
            )
        else:
            records = records.none()
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

    market_stats = None
    market_chart_data = {}
    state_links = []
    if not has_filters and not no_data_yet:
        market_stats = get_market_overview_stats()
        geographic_dist = market_stats.get("geographic_dist", [])
        geographic_dist_by_median = market_stats.get("geographic_dist_by_median", [])
        yoy_trends = market_stats.get("yoy_trends", [])

        # Build a name + slug-augmented list of per-state entries so the
        # template can render crawler-readable links (charts above are pixels;
        # crawlers need <a href> text).
        state_name_map = {code: name for code, name in US_STATES}
        for entry in geographic_dist:
            code = (entry.get("worksite_state") or "").upper()
            name = state_name_map.get(code)
            if not name:
                continue
            state_links.append({
                "code": code,
                "slug": code.lower(),
                "name": name,
                "median_salary": entry.get("median_salary"),
                "count": entry.get("count") or 0,
            })

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

    # Fast path: when the only filter is a resolved cluster slug, the count and
    # avg/min/max are exactly the precomputed aggregates on the cluster row
    # (refreshed nightly by cluster_existing_employers --stats-only). Skip the
    # 24s aggregate query entirely.
    only_slug_filter = (
        matched_cluster is not None
        and not query
        and not state_filter
        and not program_filter
        and not fiscal_year_filter
        and not filing_year_filter
    )
    if only_slug_filter:
        total_results = matched_cluster.search_record_count
        stats = {
            "avg_salary": matched_cluster.search_avg_salary,
            "min_salary": matched_cluster.search_min_salary,
            "max_salary": matched_cluster.search_max_salary,
        }
    elif has_filters:
        total_results, stats = _cached_count_and_stats(
            records,
            "salary_search",
            [
                query,
                # Use slug when present so a slug-based search and a free-text
                # search that resolves to the same name don't share a cache
                # entry (different SQL paths, different perf profile).
                f"slug:{employer_slug_filter}" if employer_slug_filter else employer_filter,
                state_filter,
                program_filter,
                str(fiscal_year_filter or ""),
                str(filing_year_filter or ""),
            ],
        )
    else:
        stats = _NO_STATS
        total_results = cache.get("salary_non_worksite_count")
        if total_results is None:
            total_results = records.count()
            cache.set("salary_non_worksite_count", total_results)

    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)

    # Dynamic SEO — title / description / H1 echo the active filter set so the
    # SERP snippet and landed page both reflect the searcher's exact query.
    # See _build_salary_seo for the per-filter copy shapes.
    canonical_url = request.build_absolute_uri(reverse("salary_search"))
    seo = _build_salary_seo(
        has_filters=has_filters,
        query=query,
        employer_filter=employer_filter,
        matched_cluster=matched_cluster,
        state_filter=state_filter,
        program_filter=program_filter,
        fiscal_year_filter=fiscal_year_filter,
        filing_year_filter=filing_year_filter,
        total_results=total_results or 0,
        avg_salary=stats["avg_salary"],
        min_salary=stats["min_salary"],
        max_salary=stats["max_salary"],
        canonical_url=canonical_url,
        page_url=request.build_absolute_uri(),
        state_name_map={code: name for code, name in US_STATES},
    )

    # Resolve the ordered page of ids behind an OFFSET-0 fence (avoids
    # LIMIT-pessimization on rare terms and the full dimension-table hash-joins
    # on common terms — see fenced_page_ids), then fetch only those rows with
    # the profile-link joins (nested-loop by pkey, sub-ms).
    page_ids = fenced_page_ids(
        records, ("-wage_annual", "-fiscal_year"), pagination["offset"], per_page
    )
    row_by_id = {
        row.id: row
        for row in SalaryRecord.objects.filter(pk__in=page_ids)
        .select_related(
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
    }
    records = [row_by_id[pk] for pk in page_ids if pk in row_by_id]

    context = {
        # Form for rendering
        "form": form,
        # Search parameters (for backward compatibility with templates)
        "query": query,
        "employer_filter": employer_filter,
        "employer_slug_filter": employer_slug_filter,
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
        "state_links": state_links,
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
        # SEO (dynamic — see _build_salary_seo)
        "page_title": seo.page_title,
        "page_description": seo.page_description,
        "page_heading": seo.page_heading,
        "page_intro": seo.page_intro,
        "structured_data": seo.structured_data,
        "canonical_url": canonical_url,
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
        (str(y), str(y)) for y in fiscal_years
    ]

    per_page = 50

    # Extract cleaned form data
    cleaned_data = form.cleaned_data if form.is_valid() else {}
    query = cleaned_data.get("q", "") or ""
    state_filter = cleaned_data.get("state", "") or ""
    city_filter = cleaned_data.get("city", "") or ""
    program_filter = cleaned_data.get("program", "") or ""
    year_filter = cleaned_data.get("year")
    try:
        page = cleaned_data.get("page") or int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page = 1

    if page > MAX_PAGE:
        return HttpResponse(_PAGE_CAP_GONE_BODY, status=410, content_type="text/plain")

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

    if has_filters:
        filter_parts = [
            query,
            state_filter,
            city_filter,
            program_filter,
            str(year_filter or ""),
        ]
        _, stats = _cached_count_and_stats(
            records.filter(wage_annual__isnull=False, wage_annual__gt=0),
            "worksite_search_stats",
            filter_parts,
        )
        count_fingerprint = hashlib.md5("|".join(filter_parts).encode()).hexdigest()
        count_key = f"worksite_search_count.{count_fingerprint}"
        total_results = cache.get(count_key)
        if total_results is None:
            total_results = records.count()
            cache.set(count_key, total_results)
    else:
        stats = _NO_STATS
        total_results = cache.get("worksite_total_count")
        if total_results is None:
            total_results = records.count()
            cache.set("worksite_total_count", total_results)

    # Pagination
    pagination = calculate_pagination_info(total_results, page, per_page)
    # OFFSET-0 fenced page resolution (see fenced_page_ids), then fetch the rows.
    page_ids = fenced_page_ids(
        records, ("-wage_annual", "-fiscal_year"), pagination["offset"], per_page
    )
    row_by_id = {
        row.id: row for row in WorksiteRecord.objects.filter(pk__in=page_ids)
    }
    records = [row_by_id[pk] for pk in page_ids if pk in row_by_id]

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
        "canonical_url": request.build_absolute_uri(reverse("worksite_search")),
    }

    return render(request, "webapp/worksite_search.html", context)
