"""Employer rankings/leaderboard view."""

import json
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, F, Q
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord

# Aggregation results cached for 24h independently of the page cache.
# The @cache_page_skip_bots decorator bypasses the page cache for bots, which
# means every bot request used to re-run a 5–15s aggregation. Caching at the
# function level means bots get the same pre-computed rankings; only the
# template render (fast) runs per bot hit.
_RANKINGS_CACHE_TTL = 60 * 60 * 24

# LCA (H-1B) volumes are much larger than PERM; use a lower threshold for PERM
# so that fiscal years with valid but smaller PERM data still appear in the selector.
_MIN_FY_RECORDS_DEFAULT = 10000
_MIN_FY_RECORDS_PERM = 500


def _format_count(cnt: int) -> str:
    """Format record count for display: 91971 → '92K', 1043216 → '1.0M'."""
    if cnt >= 1_000_000:
        return f"{cnt / 1_000_000:.1f}M"
    if cnt >= 1000:
        return f"{round(cnt / 1000)}K"
    return str(cnt)


def _program_q(program: str) -> Q:
    """Return Q filter for the visa program, or empty Q for 'all'."""
    if program == "h1b":
        return Q(visa_program=VisaProgram.H1B)
    if program == "perm":
        return Q(visa_program=VisaProgram.PERM)
    return Q()


def _available_fiscal_years(program: str, limit: int = 5) -> list[dict]:
    """Return recent fiscal years with substantial data (>= threshold) for the program."""
    threshold = _MIN_FY_RECORDS_PERM if program == "perm" else _MIN_FY_RECORDS_DEFAULT
    fys = list(
        SalaryRecord.objects.filter(Q(is_worksite=False) & _program_q(program))
        .values("fiscal_year")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=threshold)
        .order_by("-fiscal_year")[:limit]
    )
    return [
        {
            "year": fy["fiscal_year"],
            "count": fy["cnt"],
            "label": _format_count(fy["cnt"]),
            "period_key": f"fy_{fy['fiscal_year']}",
        }
        for fy in fys
    ]


def _resolve_period(period: str, program: str, fy_options: list[dict]) -> tuple[Q, str]:
    """Resolve period + program into (Q filter, human label).

    Returns the time-range Q filter (does NOT include program or is_worksite).
    When no fiscal years have enough data (fy_options is empty), fall back to
    all_time so the page is never blank by default.
    """
    if period == "all_time":
        return Q(), "All Years"

    if period == "last_12m" and program != "perm":
        cutoff = date(date.today().year - 1, date.today().month, 1)
        return Q(case_submitted__gte=cutoff), "Last 12 Months"

    if period.startswith("fy_"):
        try:
            year = int(period[3:])
            return Q(fiscal_year=year), str(year)
        except ValueError:
            pass

    # Default / latest_fy / fallback for PERM+last_12m
    # If no fiscal years qualified (fy_options empty), use all_time to avoid blank page.
    if not fy_options:
        return Q(), "All Years"
    latest_fy = fy_options[0]["year"]
    return Q(fiscal_year=latest_fy), str(latest_fy)


def _build_rankings(period_filter: Q, program: str) -> list[dict]:
    """Query and annotate employer rankings for the given period and program.

    Always fetches both H-1B and PERM counts per employer regardless of the
    selected program, so the breakdown columns are never artificially 0.
    Sorts and filters by the selected program's count.
    """
    # Avg salary is scoped to the selected program's wages for meaningful comparison.
    if program == "perm":
        salary_q = Q(visa_program=VisaProgram.PERM)
        order_field = "perm_count"
        presence_filter = Q(perm_count__gt=0)
    elif program == "h1b":
        salary_q = Q(visa_program=VisaProgram.H1B)
        order_field = "h1b_count"
        presence_filter = Q(h1b_count__gt=0)
    else:
        salary_q = Q()
        order_field = "total_filings"
        presence_filter = Q()

    # Base queryset: no program filter — we want cross-program counts per employer.
    base_filter = Q(is_worksite=False) & period_filter

    rankings = list(
        SalaryRecord.objects.filter(base_filter)
        .values(
            cluster_id=F("employer__canonical_cluster__id"),
            cluster_name=F("employer__canonical_cluster__canonical_name"),
            cluster_slug=F("employer__canonical_cluster__slug"),
        )
        .annotate(
            total_filings=Count("id"),
            h1b_count=Count("id", filter=Q(visa_program=VisaProgram.H1B)),
            perm_count=Count("id", filter=Q(visa_program=VisaProgram.PERM)),
            avg_salary=Avg(
                "wage_annual",
                filter=Q(wage_annual__gt=0) & salary_q,
            ),
        )
        .filter(cluster_slug__isnull=False, **{})
        .exclude(cluster_slug="unknown")
        .exclude(cluster_name="Unknown")
        .filter(presence_filter)
        .order_by(f"-{order_field}")[:100]
    )

    for i, row in enumerate(rankings, start=1):
        row["rank"] = i
        row["avg_salary_k"] = (
            round(row["avg_salary"] / 1000, 0) if row["avg_salary"] else None
        )
        row["sort_field"] = order_field

    return rankings


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def employer_rankings_view(request):
    """
    Employer rankings page showing top 100 employers by recent filing volume.

    Query params:
        program: h1b, perm, all (default: all)
        period: latest_fy, last_12m, all_time, fy_YYYY (default: latest_fy)
    """
    program = request.GET.get("program", "all").lower()
    period = request.GET.get("period", "latest_fy").lower()
    valid_periods = {"latest_fy", "last_12m", "all_time"}
    if period not in valid_periods and not period.startswith("fy_"):
        period = "latest_fy"
    if program not in ("h1b", "perm", "all"):
        program = "all"

    fy_cache_key = f"rankings.fy_options.{program}"
    fy_options = cache.get(fy_cache_key)
    if fy_options is None:
        fy_options = _available_fiscal_years(program)
        cache.set(fy_cache_key, fy_options, _RANKINGS_CACHE_TTL)
    else:
        fy_options = [dict(fy) for fy in fy_options]
    use_fy_selector = program == "perm"

    period_q, period_label = _resolve_period(period, program, fy_options)

    # Mark which FY button is selected (for template)
    for fy in fy_options:
        fy["is_selected"] = (
            period == fy["period_key"]
            or (period == "latest_fy" and fy == fy_options[0])
            # PERM+last_12m falls through to latest_fy
            or (period == "last_12m" and program == "perm" and fy == fy_options[0])
        )

    rankings_cache_key = f"rankings.result.{program}.{period}"
    rankings = cache.get(rankings_cache_key)
    if rankings is None:
        rankings = _build_rankings(period_q, program)
        cache.set(rankings_cache_key, rankings, _RANKINGS_CACHE_TTL)

    program_labels = {
        "all": "H-1B & Green Card",
        "h1b": "H-1B",
        "perm": "Green Card (PERM)",
    }
    program_label = program_labels.get(program, "H-1B & Green Card")
    latest_fy_label = str(fy_options[0]["year"]) if fy_options else "Latest"

    current_year = date.today().year
    latest_available_year = fy_options[0]["year"] if fy_options else None
    show_recency_note = bool(latest_available_year and latest_available_year < current_year)

    page_title = f"Top {program_label} Sponsors ({period_label}) | U.S. Immigration Data"
    page_description = (
        f"The top 100 {program_label} sponsors ranked by recent filing volume. "
        f"Data from official DOL "
        f"{'LCA and PERM' if program == 'all' else 'PERM' if program == 'perm' else 'LCA'} "
        "disclosure files."
    )
    canonical_url = request.build_absolute_uri()

    structured_data = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": page_title,
        "description": page_description,
        "url": canonical_url,
        "creator": {
            "@type": "Organization",
            "name": "U.S. Immigration Data",
            "url": "https://visa-bulletin.us",
        },
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "keywords": (
            f"{program_label} sponsors, H-1B employers, PERM employers, "
            "top green card sponsors, LCA filings, visa sponsorship rankings"
        ),
        "dateModified": date.today().isoformat(),
        "mainEntity": {
            "@type": "ItemList",
            "itemListOrder": "https://schema.org/ItemListOrderDescending",
            "numberOfItems": len(rankings),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "item": {
                        "@type": "Organization",
                        "name": r["cluster_name"],
                        "url": request.build_absolute_uri(f"/employer/{r['cluster_slug']}/"),
                    },
                }
                for i, r in enumerate(rankings[:100])
            ],
        },
    }

    context = {
        "rankings": rankings,
        "program": program,
        "period": period,
        "period_label": period_label,
        "use_fy_selector": use_fy_selector,
        "fy_options": fy_options,
        "latest_fy_label": latest_fy_label,
        "program_label": program_label,
        "latest_available_year": latest_available_year,
        "current_year": current_year,
        "show_recency_note": show_recency_note,
        "page_title": page_title,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "structured_data": json.dumps(structured_data),
    }

    return render(request, "webapp/employer_rankings.html", context)
