"""Employer rankings/leaderboard view."""

from datetime import date

from django.conf import settings
from django.db.models import Avg, Count, F, Q
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord

_MIN_FY_RECORDS = 10000


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
    fys = list(
        SalaryRecord.objects.filter(Q(is_worksite=False) & _program_q(program))
        .values("fiscal_year")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=_MIN_FY_RECORDS)
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
    """
    if period == "all_time":
        return Q(), "All Time"

    if period == "last_12m" and program != "perm":
        cutoff = date(date.today().year - 1, date.today().month, 1)
        return Q(case_submitted__gte=cutoff), "Last 12 Months"

    if period.startswith("fy_"):
        try:
            year = int(period[3:])
            return Q(fiscal_year=year), f"FY {year}"
        except ValueError:
            pass

    # Default / latest_fy / fallback for PERM+last_12m
    latest_fy = fy_options[0]["year"] if fy_options else date.today().year - 1
    return Q(fiscal_year=latest_fy), f"FY {latest_fy}"


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
        total = row["total_filings"] or 0
        perm = row["perm_count"] or 0
        row["perm_ratio"] = round(100.0 * perm / total, 1) if total > 0 else 0
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

    fy_options = _available_fiscal_years(program)
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

    rankings = _build_rankings(period_q, program)

    program_labels = {"all": "H-1B & PERM", "h1b": "H-1B", "perm": "PERM"}
    program_label = program_labels.get(program, "H-1B & PERM")
    latest_fy_label = f"FY {fy_options[0]['year']}" if fy_options else "Latest FY"

    context = {
        "rankings": rankings,
        "program": program,
        "period": period,
        "period_label": period_label,
        "use_fy_selector": use_fy_selector,
        "fy_options": fy_options,
        "latest_fy_label": latest_fy_label,
        "program_label": program_label,
        "page_title": f"Top {program_label} Sponsors ({period_label}) | U.S. Immigration Data",
        "page_description": (
            f"The top 100 {program_label} sponsors ranked by recent filing volume. "
            f"Data from official DOL {'LCA and PERM' if program == 'all' else 'PERM' if program == 'perm' else 'LCA'} "
            "disclosure files."
        ),
        "canonical_url": request.build_absolute_uri(),
    }

    return render(request, "webapp/employer_rankings.html", context)
