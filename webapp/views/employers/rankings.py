"""Employer rankings/leaderboard view."""

from datetime import date

from django.conf import settings
from django.db.models import Avg, Count, F, Q
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord


def _latest_complete_fy() -> int:
    """Return the most recent fiscal year with substantial data (>10K records)."""
    from django.db.models import Count

    result = (
        SalaryRecord.objects.filter(is_worksite=False)
        .values("fiscal_year")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=10000)
        .order_by("-fiscal_year")
        .first()
    )
    return result["fiscal_year"] if result else date.today().year - 1


def _period_filter(period: str) -> Q:
    """Return a Q object filtering SalaryRecord by the given period."""
    today = date.today()
    if period == "last_12m":
        cutoff = date(today.year - 1, today.month, 1)
        return Q(case_submitted__gte=cutoff)
    if period == "all_time":
        return Q()
    # Default: latest_fy — most recent fiscal year with complete data
    latest_fy = _latest_complete_fy()
    return Q(fiscal_year=latest_fy)


def _period_label(period: str) -> str:
    labels = {
        "latest_fy": f"FY{_latest_complete_fy()}",
        "last_12m": "Last 12 Months",
        "all_time": "All Time",
    }
    return labels.get(period, period)


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def employer_rankings_view(request):
    """
    Employer rankings page showing top 100 employers by recent filing volume.

    Query params:
        program: h1b, perm, all (default: all)
        period: latest_fy, last_12m, all_time (default: latest_fy)
    """
    program = request.GET.get("program", "all").lower()
    period = request.GET.get("period", "latest_fy").lower()
    if period not in ("latest_fy", "last_12m", "all_time"):
        period = "latest_fy"
    if program not in ("h1b", "perm", "all"):
        program = "all"

    base_filter = Q(is_worksite=False) & _period_filter(period)

    if program == "h1b":
        base_filter &= Q(visa_program=VisaProgram.H1B)
    elif program == "perm":
        base_filter &= Q(visa_program=VisaProgram.PERM)

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
            avg_salary=Avg("wage_annual", filter=Q(wage_annual__gt=0)),
        )
        .filter(cluster_slug__isnull=False)
        .exclude(cluster_slug="unknown")
        .exclude(cluster_name="Unknown")
        .order_by("-total_filings")[:100]
    )

    # Add rank and PERM ratio to each row
    for i, row in enumerate(rankings, start=1):
        row["rank"] = i
        total = row["total_filings"] or 0
        perm = row["perm_count"] or 0
        row["perm_ratio"] = round(100.0 * perm / total, 1) if total > 0 else 0
        row["avg_salary_k"] = (
            round(row["avg_salary"] / 1000, 0) if row["avg_salary"] else None
        )

    period_label = _period_label(period)

    context = {
        "rankings": rankings,
        "program": program,
        "period": period,
        "period_label": period_label,
        "page_title": f"Top H-1B & PERM Sponsors ({period_label}) | U.S. Immigration Data",
        "page_description": (
            "The top 100 H-1B and PERM sponsors ranked by recent filing volume. "
            "See which companies sponsor the most visas, file green cards, "
            "and how their salaries compare."
        ),
        "canonical_url": request.build_absolute_uri(),
    }

    return render(request, "webapp/employer_rankings.html", context)
