"""
Shared salary statistics utilities for profile and landing pages.
"""

import logging
from datetime import datetime

from django.db.models import Avg, Count, Max, Min, Q, StdDev

from models.enums.visa_program import VisaProgram

logger = logging.getLogger(__name__)


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


def filter_growth_years(yoy_trends: list[dict], start_year: int) -> list[tuple[int, int]]:
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


def calculate_yoy_growth(
    yoy_trends: list[dict],
    start_year: int,
    min_ratio: float = 0.6,
) -> tuple[float, int | None, int | None, bool]:
    """Calculate growth from a YoY trend list with partial-year handling."""
    current_year = datetime.now().year
    growth_counts = filter_growth_years(yoy_trends, start_year)
    growth_counts, used_partial_year = drop_partial_latest_year(
        growth_counts,
        current_year,
        min_ratio=min_ratio,
    )
    yoy_growth, growth_start_year, growth_end_year = calculate_growth_from_counts(
        growth_counts
    )
    return yoy_growth, growth_start_year, growth_end_year, used_partial_year


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


def calculate_salary_percentiles(queryset) -> dict:
    """
    Calculate salary percentiles (10th, 25th, 50th, 75th, 90th).

    Uses a simple list-based percentile calculation.
    """
    import time

    t0 = time.perf_counter()
    salaries = list(queryset.values_list("wage_annual", flat=True).order_by("wage_annual"))
    query_sec = time.perf_counter() - t0

    if not salaries:
        return {
            "p10": 0,
            "p25": 0,
            "p50": 0,
            "p75": 0,
            "p90": 0,
        }

    def percentile(data, p):
        if not data:
            return 0
        k = (len(data) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c >= len(data):
            return float(data[-1])
        d0 = float(data[f])
        d1 = float(data[c])
        return d0 + (d1 - d0) * (k - f)

    t1 = time.perf_counter()
    result = {
        "p10": percentile(salaries, 10),
        "p25": percentile(salaries, 25),
        "p50": percentile(salaries, 50),
        "p75": percentile(salaries, 75),
        "p90": percentile(salaries, 90),
    }
    python_sec = time.perf_counter() - t1
    logger.info(
        "[salary_percentiles] rows=%d query_sec=%.3f python_sec=%.3f",
        len(salaries),
        query_sec,
        python_sec,
    )
    return result


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
        {"employer_name": name, "counts": overlay_counts[name]} for name in overlay_values
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
