"""
Chart builder for job title profile pages.

Generates Plotly chart data for visualization of job title statistics.
"""

from lib.business.salary.common_chart_builder import (
    build_experience_salary_chart,
    build_filing_volume_chart,
    build_geographic_chart,
    build_geographic_median_chart,
    build_salary_histogram_chart,
    build_salary_trend_chart,
)


def build_job_title_profile_charts(stats: dict, job_title_name: str) -> dict:
    """
    Build Plotly chart data for job title profile page.
    
    Args:
        stats: Statistics dictionary from get_job_title_statistics
        job_title_name: Canonical job title name for chart titles
    
    Returns:
        Dictionary of chart data (JSON-encoded Plotly figures)
    """
    charts = {}
    
    # Chart 1: Salary Distribution Histogram with Employer Overlays
    if stats.get('salary_histogram'):
        charts["salary_histogram"] = build_salary_histogram_chart(
            stats["salary_histogram"],
            f"Salary Distribution - {job_title_name}",
            label="All Filings",
        )
    
    # Chart 3: Experience Level vs Salary
    if stats.get('experience_salary_histogram') and stats.get('experience_has_levels'):
        charts["experience_salary"] = build_experience_salary_chart(
            stats["experience_salary_histogram"],
            f"Salary Distribution by Experience Level - {job_title_name}",
        )
    
    # Chart 4: Geographic Distribution (Bar Chart)
    if stats.get('geographic_dist') and len(stats['geographic_dist']) > 0:
        charts["geographic_dist"] = build_geographic_chart(
            stats["geographic_dist"],
            f"Filing Distribution by State - {job_title_name}",
        )
    
    # Chart 4b: Median Salary by State (Bar Chart)
    if stats.get('geographic_dist_by_median') and len(stats['geographic_dist_by_median']) > 0:
        charts["geographic_dist_median"] = build_geographic_median_chart(
            stats["geographic_dist_by_median"],
            f"Median Salary by State - {job_title_name}",
        )
    
    # Chart 5: Year-over-Year Filing Volume
    yoy_trends = stats.get("yoy_trends", [])
    if yoy_trends and len(yoy_trends) > 0:
        filing_volume_chart = build_filing_volume_chart(
            yoy_trends,
            f"Filing Volume Over Time - {job_title_name}",
        )
        if filing_volume_chart:
            charts["filing_volume"] = filing_volume_chart
    
    # Chart 6: Year-over-Year Salary Trend
    if yoy_trends and len(yoy_trends) > 0:
        salary_trend_chart = build_salary_trend_chart(
            yoy_trends,
            f"Median Salary Trend - {job_title_name}",
        )
        if salary_trend_chart:
            charts["salary_trend"] = salary_trend_chart
    
    return charts
