"""
Shared salary statistics utilities for profile and landing pages.
"""

import logging
from datetime import datetime

from django.db.models import Avg, Count, F, Max, Min, Q, StdDev
from django.db.models.functions import TruncQuarter

from models.enums.visa_program import VisaProgram

logger = logging.getLogger(__name__)

# Filing count the base year of a growth percentage must reach before that
# percentage is worth rendering as a headline.
#
# A growth figure is a ratio, so the count it divides by sets its resolution:
# at a base of N filings one filing moves the headline by 100/N percentage
# points. Measured on prod 2026-08-18 over the 29,301 employer profiles that
# have two or more qualifying years in the default 5-year window, i.e. that
# render a growth figure at all:
#
#     base-year filings │ profiles │ one filing moves it │ render >= +1000%
#     ──────────────────┼──────────┼─────────────────────┼─────────────────
#     1                 │   17,076 │           100.0 pts │              235
#     2                 │    5,219 │            50.0 pts │               31
#     3-4               │    3,305 │            33.3 pts │               21
#     5-9               │    2,032 │            20.0 pts │               14
#     10-24             │    1,107 │            10.0 pts │                6
#     25-99             │      456 │             4.0 pts │                4
#     100+              │      106 │             1.0 pts │                0
#
# 94.3% of those profiles carry a base under 10, and 235 of the 311 profiles
# rendering +1000% or more sit at a base of exactly 1 — Anthropic, PBC has one
# FY2021 filing and 52 in FY2026, rendered as "+5100.0%". At 10 the headline
# moves by at most 10 points per filing, which is the coarsest step the one
# decimal place the tile prints can honestly survive.
#
# This is NOT employer_stats.EMPLOYER_INDEXABLE_MIN_FILINGS. That gate counts a
# cluster's LIFETIME filings across both programs and decides indexing and ads;
# this one counts a single base year inside a window the reader picks with
# `?years=` / `?program=` / `?level=`, and decides one tile. Equal today by
# coincidence; they move for different reasons.
GROWTH_MIN_BASE_FILINGS = 10


def calculate_market_overview_stats(queryset) -> dict:
    """Aggregate basic market stats for a salary queryset."""
    return queryset.aggregate(
        total_filings=Count("id"),
        median_salary=Avg("wage_annual"),
        min_salary=Min("wage_annual"),
        max_salary=Max("wage_annual"),
        std_salary=StdDev("wage_annual"),
    )


def apply_program_filter(queryset, program_filter: str):
    """Apply visa program filter to a queryset."""
    if program_filter == "h1b":
        return queryset.filter(visa_program=VisaProgram.H1B)
    if program_filter == "perm":
        return queryset.filter(visa_program=VisaProgram.PERM)
    return queryset


def calculate_yoy_trends(queryset) -> list[dict]:
    """Return year-over-year trends with counts and median salaries."""
    return list(
        queryset.values("fiscal_year")
        .annotate(
            count=Count("id"),
            median_salary=Avg("wage_annual"),
            approval_rate=Count("id", filter=Q(case_status=1)) * 100.0 / Count("id"),
        )
        .order_by("fiscal_year")
    )


def filter_growth_years(
    yoy_trends: list[dict], start_year: int
) -> list[tuple[int, int]]:
    """Return fiscal year counts eligible for growth calculation."""
    return [
        (item["fiscal_year"], item["count"])
        for item in yoy_trends
        if item.get("fiscal_year") is not None and item["fiscal_year"] >= start_year
    ]


def drop_partial_latest_year(
    growth_counts: list[tuple[int, int]],
    current_year: int,
    min_ratio: float,
) -> tuple[list[tuple[int, int]], bool]:
    """
    Drop the latest year if it looks partial vs the prior year.

    Uses a conservative ratio check to avoid showing large declines driven
    by incomplete recent-year data.
    """
    if len(growth_counts) < 2:
        return growth_counts, False

    last_year, last_count = growth_counts[-1]
    prev_year, prev_count = growth_counts[-2]
    if last_year >= current_year - 1 and prev_count > 0:
        ratio = last_count / prev_count
        if ratio < min_ratio and len(growth_counts) >= 3:
            return growth_counts[:-1], True
    return growth_counts, False


def calculate_growth_from_counts(
    growth_counts: list[tuple[int, int]],
) -> tuple[float, int | None, int | None]:
    """Calculate growth percent from the first to last year in range."""
    if len(growth_counts) < 2:
        return 0, None, None

    start_year, start_count = growth_counts[0]
    end_year, end_count = growth_counts[-1]
    if start_count <= 0:
        return 0, start_year, end_year

    growth = ((end_count - start_count) / start_count) * 100
    return growth, start_year, end_year


def growth_window(
    yoy_trends: list[dict],
    start_year: int,
    min_ratio: float = 0.6,
) -> tuple[list[tuple[int, int]], bool]:
    """The fiscal-year counts a growth percentage is computed over."""
    current_year = datetime.now().year
    growth_counts = filter_growth_years(yoy_trends, start_year)
    return drop_partial_latest_year(
        growth_counts,
        current_year,
        min_ratio=min_ratio,
    )


def calculate_yoy_growth(
    yoy_trends: list[dict],
    start_year: int,
    min_ratio: float = 0.6,
) -> tuple[float, int | None, int | None, bool]:
    """Calculate growth from a YoY trend list with partial-year handling."""
    growth_counts, used_partial_year = growth_window(
        yoy_trends, start_year, min_ratio=min_ratio
    )
    yoy_growth, growth_start_year, growth_end_year = calculate_growth_from_counts(
        growth_counts
    )
    return yoy_growth, growth_start_year, growth_end_year, used_partial_year


def growth_endpoint_counts(
    yoy_trends: list[dict],
    start_year: int,
    min_ratio: float = 0.6,
) -> tuple[int, int]:
    """Filing counts at the two years the growth percentage is derived from.

    The first is the base the percentage divides by, so it sets the figure's
    resolution: see GROWTH_MIN_BASE_FILINGS. Returns (0, 0) when fewer than two
    years qualify, i.e. when there is no growth figure.
    """
    growth_counts, _ = growth_window(yoy_trends, start_year, min_ratio=min_ratio)
    if len(growth_counts) < 2:
        return 0, 0
    return growth_counts[0][1], growth_counts[-1][1]


def growth_headline(
    yoy_trends: list[dict],
    start_year: int,
    min_ratio: float = 0.6,
) -> dict:
    """A growth percentage together with the gate and counts a tile needs.

    Every surface that renders a growth headline goes through this, so the
    `show` gate cannot be left off a new one: the percentage is not available
    without it. tests/test_growth_tile_guard.py holds that as the enumeration
    -- outside this module nothing calls calculate_yoy_growth directly.

    `show` is false whenever there is no growth figure at all (fewer than two
    qualifying years leaves base at 0), so a caller that honours it never has
    to test the years for None separately.
    """
    growth, growth_start_year, growth_end_year, used_partial_year = (
        calculate_yoy_growth(yoy_trends, start_year, min_ratio=min_ratio)
    )
    base_filings, end_filings = growth_endpoint_counts(
        yoy_trends, start_year, min_ratio=min_ratio
    )
    return {
        "yoy_growth": growth,
        "growth_start_year": growth_start_year,
        "growth_end_year": growth_end_year,
        "used_partial_year": used_partial_year,
        "growth_base_filings": base_filings,
        "growth_end_filings": end_filings,
        "show_yoy_growth": base_filings >= GROWTH_MIN_BASE_FILINGS,
    }


def calculate_geographic_distributions(
    queryset,
    limit: int = 20,
) -> tuple[list[dict], list[dict]]:
    """Return geographic distribution lists sorted by count and median salary."""
    geographic_dist_base = list(
        queryset.exclude(worksite_state="")
        .values("worksite_state")
        .annotate(
            count=Count("id"),
            median_salary=Avg("wage_annual"),
            min_salary=Min("wage_annual"),
            max_salary=Max("wage_annual"),
        )
    )
    geographic_by_count = sorted(
        geographic_dist_base,
        key=lambda item: item.get("count", 0) or 0,
        reverse=True,
    )[:limit]
    geographic_by_median = sorted(
        geographic_dist_base,
        key=lambda item: item.get("median_salary") or 0,
        reverse=True,
    )[:limit]
    return geographic_by_count, geographic_by_median


def _percentile_from_list(data: list, p: float) -> float:
    """Return the p-th percentile (0-100) from a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return float(data[-1])
    return float(data[f]) + (float(data[c]) - float(data[f])) * (k - f)


def calculate_salary_percentiles(queryset) -> dict:
    """
    Calculate salary percentiles (10th, 25th, 50th, 75th, 90th).

    On PostgreSQL uses a raw subquery with percentile_cont() to avoid loading all
    rows into Python. Falls back to a Python sort for SQLite (tests).
    """
    from django.db import connection

    empty = {"p10": 0, "p25": 0, "p50": 0, "p75": 0, "p90": 0}

    if connection.vendor == "postgresql":
        inner_sql, params = queryset.values("wage_annual").query.sql_with_params()
        raw_sql = f"""
            SELECT
                percentile_cont(0.10) WITHIN GROUP (ORDER BY wage_annual),
                percentile_cont(0.25) WITHIN GROUP (ORDER BY wage_annual),
                percentile_cont(0.50) WITHIN GROUP (ORDER BY wage_annual),
                percentile_cont(0.75) WITHIN GROUP (ORDER BY wage_annual),
                percentile_cont(0.90) WITHIN GROUP (ORDER BY wage_annual)
            FROM ({inner_sql}) AS q
        """
        with connection.cursor() as cursor:
            cursor.execute(raw_sql, params)
            row = cursor.fetchone()
        if row is None or row[0] is None:
            return empty
        return {
            "p10": float(row[0]),
            "p25": float(row[1]),
            "p50": float(row[2]),
            "p75": float(row[3]),
            "p90": float(row[4]),
        }

    salaries = sorted(
        float(v)
        for v in queryset.values_list("wage_annual", flat=True)
        if v is not None
    )
    if not salaries:
        return empty
    return {
        "p10": _percentile_from_list(salaries, 10),
        "p25": _percentile_from_list(salaries, 25),
        "p50": _percentile_from_list(salaries, 50),
        "p75": _percentile_from_list(salaries, 75),
        "p90": _percentile_from_list(salaries, 90),
    }


# Cap histogram X-axis at this percentile so the chart focuses on where data is
# (avoids long empty tail when a few outliers extend to e.g. $750k)
HISTOGRAM_PERCENTILE_CAP = 95


def _salary_percentile_value(salaries: list[float], p: float) -> float:
    """Return the p-th percentile value (0 <= p <= 100)."""
    if not salaries:
        return 0.0
    sorted_sal = sorted(salaries)
    k = (len(sorted_sal) - 1) * (p / 100.0)
    f = int(k)
    if f < 0:
        return float(sorted_sal[0])
    if f >= len(sorted_sal) - 1:
        return float(sorted_sal[-1])
    d0 = float(sorted_sal[f])
    d1 = float(sorted_sal[f + 1])
    return d0 + (d1 - d0) * (k - f)


def calculate_salary_histogram_with_overlays(
    queryset,
    overlay_values: list[str],
    overlay_field: str = "employer__canonical_cluster__canonical_name",
    num_bins: int = 20,
) -> dict:
    """
    Calculate salary histogram data for charting.

    The X-axis range is capped at the 95th percentile so the chart adapts to the
    data and does not show a long empty tail when a few salaries extend far right.
    One extra bin [cap, cap+bin_width) holds the real count in that range; values
    above that go in the last data bin.

    Returns dict with overall bins and overlay counts for selected values.
    """
    values_list = list(queryset.values_list("wage_annual", overlay_field))
    wages = [float(w) for w, _ in values_list if w is not None]
    if not wages:
        return {}

    min_salary = min(wages)
    max_salary = max(wages)
    p98 = _salary_percentile_value(wages, HISTOGRAM_PERCENTILE_CAP)
    cap_max = max(min_salary, min(max_salary, p98))
    bin_width = (cap_max - min_salary) / num_bins
    if bin_width <= 0:
        return {}

    overall_counts = [0] * num_bins
    overlay_counts = {name: [0] * num_bins for name in overlay_values}
    right_bin_end = cap_max + bin_width
    right_bin_count = 0
    right_bin_overlay = {name: 0 for name in overlay_values}

    for wage, overlay_value in values_list:
        if wage is None:
            continue
        wage_value = float(wage)
        if wage_value >= right_bin_end:
            index = num_bins - 1
        elif wage_value >= cap_max:
            right_bin_count += 1
            if overlay_value in overlay_counts:
                right_bin_overlay[overlay_value] += 1
            continue
        else:
            index = int((wage_value - min_salary) / bin_width)
            if index >= num_bins:
                index = num_bins - 1
            elif index < 0:
                index = 0
        overall_counts[index] += 1
        if overlay_value in overlay_counts:
            overlay_counts[overlay_value][index] += 1

    bins = []
    for i in range(num_bins):
        bin_start = min_salary + (i * bin_width)
        bin_end = bin_start + bin_width if i < num_bins - 1 else cap_max
        bins.append(
            {
                "range_start": bin_start,
                "range_end": bin_end,
                "count": overall_counts[i],
                "label": f"${bin_start:,.0f} - ${bin_end:,.0f}",
            }
        )
    bins.append(
        {
            "range_start": cap_max,
            "range_end": right_bin_end,
            "count": right_bin_count,
            "label": f"${cap_max:,.0f} - ${right_bin_end:,.0f}",
        }
    )
    for name in overlay_values:
        overlay_counts[name].append(right_bin_overlay[name])
    overall_counts.append(right_bin_count)

    overlays = [
        {"employer_name": name, "counts": overlay_counts[name]}
        for name in overlay_values
    ]

    return {
        "bins": bins,
        "overlays": overlays,
    }


def calculate_salary_histogram_with_experience_overlays(
    queryset,
    experience_levels: list[str],
    include_unspecified: bool,
    num_bins: int = 20,
) -> dict:
    """
    Calculate salary histogram data with experience level overlays.

    X-axis range is capped at the 95th percentile. One extra bin [cap, cap+bin_width)
    holds the real count in that range; values above that go in the last data bin.
    """
    values_list = list(
        queryset.values_list("wage_annual", "job_title_entity__experience_level")
    )
    wages = [float(w) for w, _ in values_list if w is not None]
    if not wages:
        return {}

    min_salary = min(wages)
    max_salary = max(wages)
    p98 = _salary_percentile_value(wages, HISTOGRAM_PERCENTILE_CAP)
    cap_max = max(min_salary, min(max_salary, p98))
    bin_width = (cap_max - min_salary) / num_bins
    if bin_width <= 0:
        return {}

    overlay_levels = list(experience_levels)
    if include_unspecified and "" not in overlay_levels:
        overlay_levels.append("")

    overall_counts = [0] * num_bins
    overlay_counts = {level: [0] * num_bins for level in overlay_levels}
    right_bin_end = cap_max + bin_width
    right_bin_count = 0
    right_bin_overlay = {level: 0 for level in overlay_levels}

    for wage, level in values_list:
        if wage is None:
            continue
        wage_value = float(wage)
        level_key = level or ""
        if wage_value >= right_bin_end:
            index = num_bins - 1
        elif wage_value >= cap_max:
            right_bin_count += 1
            if level_key in overlay_counts:
                right_bin_overlay[level_key] += 1
            continue
        else:
            index = int((wage_value - min_salary) / bin_width)
            if index >= num_bins:
                index = num_bins - 1
            elif index < 0:
                index = 0
        overall_counts[index] += 1
        if level_key in overlay_counts:
            overlay_counts[level_key][index] += 1

    bins = []
    for i in range(num_bins):
        bin_start = min_salary + (i * bin_width)
        bin_end = bin_start + bin_width if i < num_bins - 1 else cap_max
        bins.append(
            {
                "range_start": bin_start,
                "range_end": bin_end,
                "count": overall_counts[i],
                "label": f"${bin_start:,.0f} - ${bin_end:,.0f}",
            }
        )
    bins.append(
        {
            "range_start": cap_max,
            "range_end": right_bin_end,
            "count": right_bin_count,
            "label": f"${cap_max:,.0f} - ${right_bin_end:,.0f}",
        }
    )
    for level in overlay_levels:
        overlay_counts[level].append(right_bin_overlay[level])
    overall_counts.append(right_bin_count)

    return {
        "bins": bins,
        "overlays": [
            {"employer_name": level, "counts": overlay_counts[level]}
            for level in overlay_levels
        ],
        "label": "All Levels",
    }


def calculate_program_breakdown(queryset) -> dict:
    """Count filings per visa program (H-1B vs PERM)."""
    rows = list(
        queryset.values("visa_program").annotate(count=Count("id")).order_by()
    )
    h1b_count = sum(
        r["count"]
        for r in rows
        if r["visa_program"]
        in (VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3)
    )
    perm_count = sum(
        r["count"] for r in rows if r["visa_program"] == VisaProgram.PERM
    )
    total = h1b_count + perm_count
    perm_ratio = (perm_count / total * 100) if total > 0 else 0
    return {
        "h1b_count": h1b_count,
        "perm_count": perm_count,
        "total": total,
        "perm_ratio": perm_ratio,
    }


def calculate_recent_filing_activity(queryset) -> dict:
    """
    Last filing dates per program type and per top job title.

    Uses case_submitted when available, falls back to fiscal_year.
    """
    has_dates = queryset.filter(case_submitted__isnull=False).exists()

    if has_dates:
        by_program = list(
            queryset.filter(case_submitted__isnull=False)
            .values("visa_program")
            .annotate(last_filing=Max("case_submitted"), count=Count("id"))
            .order_by("-last_filing")
        )
        for row in by_program:
            row["program_display"] = VisaProgram.short_display(row.get("visa_program"))
        by_title = list(
            queryset.filter(
                case_submitted__isnull=False,
                job_title_entity__isnull=False,
                job_title_entity__canonical_cluster__isnull=False,
            )
            .values(
                "job_title_entity__canonical_cluster__canonical_title",
                "job_title_entity__canonical_cluster__slug",
            )
            .annotate(last_filing=Max("case_submitted"), count=Count("id"))
            .order_by("-last_filing")[:5]
        )
    else:
        by_program = list(
            queryset.values("visa_program")
            .annotate(last_year=Max("fiscal_year"), count=Count("id"))
            .order_by("-last_year")
        )
        for row in by_program:
            row["program_display"] = VisaProgram.short_display(row.get("visa_program"))
        by_title = list(
            queryset.filter(
                job_title_entity__isnull=False,
                job_title_entity__canonical_cluster__isnull=False,
            )
            .values(
                "job_title_entity__canonical_cluster__canonical_title",
                "job_title_entity__canonical_cluster__slug",
            )
            .annotate(last_year=Max("fiscal_year"), count=Count("id"))
            .order_by("-last_year")[:5]
        )

    return {
        "by_program": by_program,
        "by_title": by_title,
        "has_exact_dates": has_dates,
    }


def calculate_filing_pace(queryset) -> list[dict]:
    """
    Quarterly filing pace using case_submitted.

    Returns empty list if case_submitted data not available.
    Split by visa_program (H-1B vs PERM).
    """
    dated_qs = queryset.filter(case_submitted__isnull=False)
    if not dated_qs.exists():
        return []

    rows = list(
        dated_qs.annotate(period=TruncQuarter("case_submitted"))
        .values("period", "visa_program")
        .annotate(count=Count("id"))
        .order_by("period", "visa_program")
    )
    return rows


def calculate_filing_pace_by_fiscal_year(queryset) -> list[dict]:
    """Fallback filing pace grouped by fiscal_year and visa_program."""
    return list(
        queryset.values("fiscal_year", "visa_program")
        .annotate(count=Count("id"))
        .order_by("fiscal_year", "visa_program")
    )


def calculate_processing_latency(queryset) -> dict | None:
    """
    Filing-to-decision processing time stats.

    Returns None if insufficient data (case_submitted or decision_date missing).
    """
    latency_qs = queryset.filter(
        case_submitted__isnull=False,
        decision_date__isnull=False,
        decision_date__gte=F("case_submitted"),
    )
    count = latency_qs.count()
    if count < 10:
        return None

    days_list = sorted(
        (r["decision_date"] - r["case_submitted"]).days
        for r in latency_qs.values("case_submitted", "decision_date").iterator(
            chunk_size=5000
        )
    )
    if not days_list:
        return None

    def _percentile(data: list[int], p: float) -> int:
        k = (len(data) - 1) * (p / 100.0)
        f = int(k)
        if f >= len(data) - 1:
            return data[-1]
        return int(data[f] + (data[f + 1] - data[f]) * (k - f))

    overall = {
        "count": count,
        "avg_days": int(sum(days_list) / len(days_list)),
        "median_days": _percentile(days_list, 50),
        "p25_days": _percentile(days_list, 25),
        "p75_days": _percentile(days_list, 75),
    }

    # Per-program breakdown
    per_program = {}
    for prog_val, prog_label in [
        (VisaProgram.H1B, "H-1B"),
        (VisaProgram.PERM, "PERM"),
    ]:
        prog_qs = latency_qs.filter(visa_program=prog_val)
        prog_days = sorted(
            (r["decision_date"] - r["case_submitted"]).days
            for r in prog_qs.values(
                "case_submitted", "decision_date"
            ).iterator(chunk_size=5000)
        )
        if len(prog_days) >= 5:
            per_program[prog_label] = {
                "count": len(prog_days),
                "avg_days": int(sum(prog_days) / len(prog_days)),
                "median_days": _percentile(prog_days, 50),
                "p25_days": _percentile(prog_days, 25),
                "p75_days": _percentile(prog_days, 75),
            }

    return {**overall, "per_program": per_program}


def calculate_latency_trend(queryset) -> list[dict]:
    """
    Quarterly median processing time trend.

    Returns empty list if insufficient data.
    """
    latency_qs = queryset.filter(
        case_submitted__isnull=False,
        decision_date__isnull=False,
        decision_date__gte=F("case_submitted"),
    )
    if not latency_qs.exists():
        return []

    rows = list(
        latency_qs.annotate(period=TruncQuarter("case_submitted"))
        .values("period")
        .annotate(count=Count("id"))
        .order_by("period")
    )

    result = []
    for row in rows:
        if row["count"] < 5:
            continue
        period_qs = latency_qs.filter(
            case_submitted__gte=row["period"],
            case_submitted__lt=row["period"].replace(month=row["period"].month + 3)
            if row["period"].month <= 9
            else row["period"].replace(year=row["period"].year + 1, month=(row["period"].month + 3 - 12)),
        )
        days = sorted(
            (r["decision_date"] - r["case_submitted"]).days
            for r in period_qs.values(
                "case_submitted", "decision_date"
            ).iterator(chunk_size=5000)
        )
        if days:
            median = days[len(days) // 2]
            result.append(
                {
                    "period": row["period"].isoformat(),
                    "period_label": f"Q{(row['period'].month - 1) // 3 + 1} {row['period'].year}",
                    "median_days": median,
                    "count": len(days),
                }
            )

    return result
