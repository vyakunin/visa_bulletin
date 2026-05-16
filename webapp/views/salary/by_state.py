"""Per-state salary landing page view.

Renders an SEO-focused per-state page at /salaries/by-state/<state>/ with
aggregate stats, top employers, top job titles, and a visa-program breakdown
limited to filings whose worksite_state matches the requested state.
"""

from django.conf import settings
from django.db.models import Avg, Count, Max, Min
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from lib.business.salary.common_stats import (
    calculate_program_breakdown,
    calculate_salary_percentiles,
)
from lib.utils.location_utils import US_STATES
from models.salary import SalaryRecord

# Map of lowercase 2-letter state code -> (canonical uppercase code, display name).
# Built once at import time from the canonical US_STATES list so adding a new
# state in lib/utils/location_utils.py is picked up automatically (per the
# "iterate the enum, never restate its members" rule).
_STATE_LOOKUP: dict[str, tuple[str, str]] = {
    code.lower(): (code, name) for code, name in US_STATES
}


def _resolve_state(state_slug: str) -> tuple[str, str]:
    """Return (canonical 2-letter code, display name) or raise Http404."""
    if not state_slug:
        raise Http404("State not specified")
    normalized = state_slug.strip().lower()
    if normalized not in _STATE_LOOKUP:
        raise Http404(f"Unknown state: {state_slug}")
    return _STATE_LOOKUP[normalized]


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def salary_by_state_view(request, state: str):
    """Per-state aggregate salary landing page."""
    state_code, state_name = _resolve_state(state)
    state_slug = state_code.lower()

    # Base queryset: searchable, non-worksite, salaried filings in this state.
    base_qs = (
        SalaryRecord.objects.filter(worksite_state=state_code)
        .exclude(is_worksite=True)
        .exclude(employer_name="Unknown")
        .filter(wage_annual__isnull=False, wage_annual__gt=0)
    )

    # Aggregate stats: count + mean + min/max in a single query.
    agg = base_qs.aggregate(
        total_filings=Count("id"),
        avg_salary=Avg("wage_annual"),
        min_salary=Min("wage_annual"),
        max_salary=Max("wage_annual"),
    )
    total_filings = agg["total_filings"] or 0

    # Percentile band (p10/p25/p50/p75/p90) via shared helper (PG percentile_cont).
    percentiles = (
        calculate_salary_percentiles(base_qs) if total_filings > 0 else {}
    )

    # Visa-program breakdown (H-1B vs PERM vs other).
    program_breakdown = (
        calculate_program_breakdown(base_qs) if total_filings > 0 else {}
    )

    # Top 25 employers in this state, by filing count.
    top_employers = list(
        base_qs.filter(employer__canonical_cluster__slug__isnull=False)
        .exclude(employer__canonical_cluster__canonical_name="Unknown")
        .exclude(employer__canonical_cluster__slug="unknown")
        .values(
            "employer__canonical_cluster__canonical_name",
            "employer__canonical_cluster__slug",
        )
        .annotate(count=Count("id"), median_salary=Avg("wage_annual"))
        .order_by("-count")[:25]
    )

    # Top 25 job titles in this state, by filing count.
    top_job_titles = list(
        base_qs.filter(job_title_entity__canonical_cluster__isnull=False)
        .values(
            "job_title_entity__canonical_cluster__canonical_title",
            "job_title_entity__canonical_cluster__slug",
        )
        .annotate(count=Count("id"), median_salary=Avg("wage_annual"))
        .order_by("-count")[:25]
    )

    canonical_url = request.build_absolute_uri(
        reverse("salary_by_state", kwargs={"state": state_slug})
    )

    median_salary = percentiles.get("p50") if percentiles else None
    # Fall back to mean when median isn't available (no rows).
    median_or_avg = median_salary if median_salary else agg["avg_salary"]

    if median_or_avg:
        page_description = (
            f"{state_name} H-1B and PERM salary data: median "
            f"${median_or_avg:,.0f} across {total_filings:,} filings, "
            f"top employers and roles."
        )
    else:
        page_description = (
            f"{state_name} H-1B and PERM salary data: filings, "
            f"top employers and roles."
        )

    context = {
        "state_code": state_code,
        "state_slug": state_slug,
        "state_name": state_name,
        "total_filings": total_filings,
        "avg_salary": agg["avg_salary"],
        "min_salary": agg["min_salary"],
        "max_salary": agg["max_salary"],
        "percentiles": percentiles,
        "median_salary": median_or_avg,
        "program_breakdown": program_breakdown,
        "top_employers": top_employers,
        "top_job_titles": top_job_titles,
        # SEO
        "page_title": (
            f"Salaries in {state_name} — H-1B & PERM filings | "
            "visa-bulletin.us"
        ),
        "page_description": page_description,
        "canonical_url": canonical_url,
    }
    return render(request, "webapp/salary_by_state.html", context)
