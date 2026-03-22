"""Employer directory views and autocomplete."""

import json

from django.conf import settings
from django.db.models import Exists, F, OuterRef, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from lib.utils.location_utils import US_STATES
from lib.utils.pagination import (
    build_pagination_query_string,
    calculate_pagination_info,
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from models.salary import Employer, EmployerCluster


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def company_autocomplete_view(request):
    """
    API endpoint for company name autocomplete suggestions.

    Query params:
        q: Search query (partial company name)
        limit: Maximum number of results (default: 20)

    Returns JSON array of canonical cluster names matching the query.
    """
    query = request.GET.get("q", "").strip()
    limit = int(request.GET.get("limit", 20))

    if not query or len(query) < 2:
        return HttpResponse(json.dumps([]), content_type="application/json")

    # Get cluster canonical names and slugs that match the query
    # Order by total record count (LCA + PERM) for relevance
    matching_companies = (
        EmployerCluster.objects.filter(canonical_name__icontains=query)
        .exclude(canonical_name="Unknown")
        .exclude(slug__isnull=True)
        .exclude(slug="unknown")
        .annotate(total_count=F("total_lca_count") + F("total_perm_count"))
        .order_by("-total_count", "canonical_name")
        .values("canonical_name", "slug", "total_count")[:limit]
    )

    suggestions = [
        {
            "name": company["canonical_name"],
            "slug": company["slug"],
            "count": company["total_count"],
        }
        for company in matching_companies
    ]
    return HttpResponse(json.dumps(suggestions), content_type="application/json")


def _employer_directory_base_queryset(query: str, state_filter: str):
    """
    Base queryset for employer directory: clusters with slug, not Unknown,
    and at least one filing. Uses stored total_lca_count/total_perm_count for
    "has filings" when no state filter; state filter uses Exists on SalaryRecord.
    """
    # Clusters with slug and at least one filing (stored counts)
    base = (
        EmployerCluster.objects.filter(slug__isnull=False)
        .exclude(canonical_name="Unknown")
        .exclude(slug="unknown")
        .filter(Q(total_lca_count__gt=0) | Q(total_perm_count__gt=0))
    )
    if query:
        query_clean = query.strip()
        base = base.filter(canonical_name__icontains=query_clean)
    if state_filter:
        employers_in_state = Employer.objects.filter(
            canonical_cluster=OuterRef("pk"),
            salary_records__worksite_state=state_filter,
        )
        base = base.filter(Exists(employers_in_state)).distinct()
    return base


def _order_value_for_row(employer, program_filter: str):
    """Order value used for keyset cursor (same as sort key)."""
    if program_filter == "h1b":
        return employer.total_lca_count
    if program_filter == "perm":
        return employer.total_perm_count
    return employer.total_lca_count + employer.total_perm_count


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def employer_directory_view(request):
    """
    Employer directory page showing list of top employers with search and filters.

    Uses stored total_lca_count and total_perm_count (maintained by update_employer_stats)
    for filtering, ordering, and display. Keyset pagination (cursor) for fast deep pages;
    offset (page) supported when no cursor is present.

    Query params:
        q: Search query (employer name)
        program: Visa program filter (h1b, perm, all)
        state: State filter (2-letter code)
        page: Page number for display / offset when no cursor
        cursor: Opaque keyset cursor for next/prev page
    """
    query = request.GET.get("q", "").strip()
    program_filter = request.GET.get("program", "all").lower()
    state_filter = request.GET.get("state", "").strip()
    cursor_param = request.GET.get("cursor", "").strip()
    try:
        page = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page = 1

    per_page = 50

    base = _employer_directory_base_queryset(query, state_filter)
    total_results = base.count()

    # Order by stored fields; annotate total for program=all
    if program_filter == "h1b":
        employers_ordered = base.order_by("-total_lca_count", "id")
    elif program_filter == "perm":
        employers_ordered = base.order_by("-total_perm_count", "id")
    else:
        employers_ordered = base.annotate(
            total=F("total_lca_count") + F("total_perm_count")
        ).order_by("-total", "id")

    # Keyset pagination: if valid cursor, fetch that page instead of offset
    decoded = decode_keyset_cursor(cursor_param) if cursor_param else None
    use_keyset = decoded is not None
    if use_keyset:
        direction, order_value, pk = decoded
        if program_filter == "all":
            qs = base.annotate(total=F("total_lca_count") + F("total_perm_count"))
            if direction == "next":
                qs = qs.filter(
                    Q(total__lt=order_value) | (Q(total=order_value) & Q(id__lt=pk))
                ).order_by("-total", "id")[: per_page + 1]
            else:
                qs = qs.filter(
                    Q(total__gt=order_value) | (Q(total=order_value) & Q(id__gt=pk))
                ).order_by("total", "id")[: per_page + 1]
        elif program_filter == "h1b":
            if direction == "next":
                qs = employers_ordered.filter(
                    Q(total_lca_count__lt=order_value)
                    | (Q(total_lca_count=order_value) & Q(id__lt=pk))
                )[: per_page + 1]
            else:
                qs = base.filter(
                    Q(total_lca_count__gt=order_value)
                    | (Q(total_lca_count=order_value) & Q(id__gt=pk))
                ).order_by("total_lca_count", "id")[: per_page + 1]
        else:
            if direction == "next":
                qs = employers_ordered.filter(
                    Q(total_perm_count__lt=order_value)
                    | (Q(total_perm_count=order_value) & Q(id__lt=pk))
                )[: per_page + 1]
            else:
                qs = base.filter(
                    Q(total_perm_count__gt=order_value)
                    | (Q(total_perm_count=order_value) & Q(id__gt=pk))
                ).order_by("total_perm_count", "id")[: per_page + 1]
        rows = list(qs)
        if direction == "prev":
            rows.reverse()
        employers = rows[:per_page]
        if direction == "next":
            has_next_keyset = len(rows) > per_page
            has_prev_keyset = page > 1
        else:
            has_next_keyset = True
            has_prev_keyset = len(rows) > per_page
    else:
        pagination = calculate_pagination_info(total_results, page, per_page)
        offset = pagination["offset"]
        employers = list(employers_ordered[offset : offset + per_page])
        has_next_keyset = (offset + per_page) < total_results
        has_prev_keyset = page > 1

    # Pagination metadata (page for display; total_pages from count)
    pagination = calculate_pagination_info(total_results, page, per_page)

    # Build next_cursor and prev_cursor from current page rows
    next_cursor = None
    prev_cursor = None
    if employers:
        first_row = employers[0]
        last_row = employers[-1]
        order_next = _order_value_for_row(last_row, program_filter)
        order_prev = _order_value_for_row(first_row, program_filter)
        next_cursor = encode_keyset_cursor(order_next, last_row.id, "next")
        prev_cursor = encode_keyset_cursor(order_prev, first_row.id, "prev")

    has_next = len(employers) == per_page and has_next_keyset
    has_prev = has_prev_keyset

    # Check if there are employers matching the query but without slugs (for helpful feedback)
    has_employers_without_slugs = False
    if query and total_results == 0:
        has_employers_without_slugs = EmployerCluster.objects.filter(
            canonical_name__icontains=query.strip(),
            slug__isnull=True,
        ).exists()

    params = {
        "query": query,
        "program_filter": program_filter,
        "state_filter": state_filter,
        "page": page,
    }

    context = {
        "query": query,
        "program_filter": program_filter,
        "state_filter": state_filter,
        "states": US_STATES,
        "company_autocomplete_url": request.build_absolute_uri(
            reverse("company_autocomplete")
        ),
        "employers": employers,
        "total_results": total_results,
        "has_employers_without_slugs": has_employers_without_slugs,
        "page": pagination["page"],
        "total_pages": pagination["total_pages"],
        "per_page": per_page,
        "page_start": (pagination["page"] - 1) * per_page + 1
        if total_results > 0
        else 0,
        "page_end": min(
            (pagination["page"] - 1) * per_page + len(employers), total_results
        ),
        "has_pagination": pagination["total_pages"] > 1,
        "pagination_query": build_pagination_query_string(params),
        "page_range": pagination["page_range"],
        "next_cursor": next_cursor,
        "prev_cursor": prev_cursor,
        "has_next": has_next,
        "has_prev": has_prev,
        "page_title": "H-1B & Green Card Sponsor Database: Search 221K+ Employers | U.S. Immigration Data",
        "page_description": "Which companies sponsor H-1B visas and green cards? Search 221K+ employers with salary data, filing history, and sponsorship breakdown.",
        "canonical_url": request.build_absolute_uri(),
    }

    return render(request, "webapp/employer_directory.html", context)
