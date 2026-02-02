"""Employer profile views and chart helpers."""

import logging
import time
from datetime import date, datetime

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Avg, Count, F, Max, Min, Q
from django.db.utils import OperationalError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import cache_page

from lib.business.salary.common_stats import (
    calculate_salary_histogram_with_overlays,
    calculate_salary_percentiles,
    calculate_yoy_growth,
    calculate_yoy_trends,
)
from lib.business.salary.common_chart_builder import build_salary_histogram_chart
from models.enums.visa_program import VisaProgram
from models.job_title import JobTitle
from models.salary import Employer, EmployerCluster, SalaryRecord

logger = logging.getLogger(__name__)

SIMILAR_EMPLOYERS_CACHE_TIMEOUT = 86400  # 24h
SIMILAR_EMPLOYERS_QUERY_TIMEOUT_MS = 15000  # 15s


def _get_cluster_or_404(slug: str):
    """Resolve employer cluster by slug; redirect if name match, else 404."""
    try:
        cluster = EmployerCluster.objects.get(slug=slug)
    except EmployerCluster.DoesNotExist:
        slug_normalized = slug.replace('-', ' ').lower()
        employers = Employer.objects.filter(
            name_normalized__icontains=slug_normalized
        ).select_related('canonical_cluster')
        if employers.exists():
            canonical_cluster = employers.first().canonical_cluster
            if canonical_cluster and canonical_cluster.slug:
                return redirect('employer_profile', slug=canonical_cluster.slug, permanent=True)
        raise Http404("Employer not found")
    if cluster.canonical_name == "Unknown" or cluster.slug == "unknown":
        raise Http404("Employer not found")
    return cluster


def _parse_employer_profile_params(request):
    """Parse years, program, level from request; return dict with start_year, level_choices, etc."""
    try:
        years = min(int(request.GET.get('years', 5)), 20)
    except (ValueError, TypeError):
        years = 5
    program_filter = request.GET.get('program', 'all').lower()
    level_param = request.GET.get('level', 'all').lower().strip()
    level_choices = list(JobTitle._meta.get_field('experience_level').choices)
    level_values = {value for value, _ in level_choices if value}
    if level_param == 'unspecified':
        experience_level = ''
        level_filter = 'unspecified'
    elif level_param in level_values:
        experience_level = level_param
        level_filter = level_param
    else:
        experience_level = None
        level_filter = 'all'
    current_year = datetime.now().year
    start_year = current_year - years
    return {
        'years': years,
        'program_filter': program_filter,
        'level_filter': level_filter,
        'level_choices': level_choices,
        'experience_level': experience_level,
        'start_year': start_year,
    }


def _get_employer_records_queryset(cluster, params):
    """Base SalaryRecord queryset for this employer and filters."""
    records = SalaryRecord.objects.filter(
        employer__canonical_cluster=cluster,
        fiscal_year__gte=params['start_year'],
        wage_annual__isnull=False,
        is_worksite=False,
    )
    if params['program_filter'] == 'h1b':
        records = records.filter(visa_program=VisaProgram.H1B)
    elif params['program_filter'] == 'perm':
        records = records.filter(visa_program=VisaProgram.PERM)
    return records


def _compute_employer_stats(records, slug: str, start_year: int) -> dict:
    """Compute stats dict (basic, top_titles, state_dist, yoy_trends, etc.) for employer profile."""
    t0 = time.perf_counter()
    basic_stats = records.aggregate(
        total_filings=Count('id'),
        approved_filings=Count('id', filter=Q(case_status=1)),
        median_salary=Avg('wage_annual'),
        min_salary=Min('wage_annual'),
        max_salary=Max('wage_annual'),
    )
    logger.info("[employer_profile] basic_stats slug=%s took %.3fs", slug, time.perf_counter() - t0)
    approval_rate = (basic_stats['approved_filings'] / basic_stats['total_filings'] * 100) if basic_stats['total_filings'] else 0

    t0 = time.perf_counter()
    top_titles = list(
        records
        .filter(
            job_title_entity__isnull=False,
            job_title_entity__canonical_cluster__isnull=False,
        )
        .values(
            'job_title_entity__canonical_cluster__canonical_title',
            'job_title_entity__canonical_cluster__slug',
            'job_title_entity__canonical_cluster__id',
        )
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
            min_salary=Min('wage_annual'),
            max_salary=Max('wage_annual'),
        )
        .order_by('-count', 'job_title_entity__canonical_cluster__canonical_title')[:10]
    )
    logger.info("[employer_profile] top_titles slug=%s took %.3fs", slug, time.perf_counter() - t0)

    t0 = time.perf_counter()
    salary_percentiles = calculate_salary_percentiles(records)
    logger.info("[employer_profile] salary_percentiles slug=%s took %.3fs", slug, time.perf_counter() - t0)
    t0 = time.perf_counter()
    histogram_data, title_histograms = _build_employer_salary_histograms(
        records, top_titles, basic_stats.get('min_salary'), basic_stats.get('max_salary'),
    )
    logger.info("[employer_profile] salary_histograms slug=%s took %.3fs", slug, time.perf_counter() - t0)
    if histogram_data and title_histograms:
        histogram_data['overlays'] = _build_job_title_overlays(title_histograms, limit=6)

    t0 = time.perf_counter()
    state_dist = list(
        records.values('worksite_state')
        .annotate(count=Count('id'), median_salary=Avg('wage_annual'))
        .order_by('-count')[:15]
    )
    logger.info("[employer_profile] state_dist slug=%s took %.3fs", slug, time.perf_counter() - t0)

    t0 = time.perf_counter()
    yoy_trends = calculate_yoy_trends(records)
    logger.info("[employer_profile] yoy_trends slug=%s took %.3fs", slug, time.perf_counter() - t0)
    yoy_growth, _, _, _ = calculate_yoy_growth(yoy_trends, start_year)

    return {
        'basic': basic_stats,
        'approval_rate': approval_rate,
        'yoy_growth': yoy_growth,
        'top_titles': top_titles,
        'salary_percentiles': salary_percentiles,
        'salary_histogram': histogram_data,
        'job_title_histograms': title_histograms,
        'state_dist': state_dist,
        'yoy_trends': yoy_trends,
    }


def _build_employer_chart_data(stats: dict, cluster: EmployerCluster, slug: str) -> dict:
    """Build Plotly chart_data from stats (salary histogram, state charts, job title histograms)."""
    t0 = time.perf_counter()
    chart_data = _build_employer_profile_charts(stats, cluster.canonical_name, slug=slug)
    if stats.get('job_title_histograms'):
        t_job = time.perf_counter()
        job_title_charts = [
            {
                'id': i,
                'title': item['title'],
                'slug': item.get('slug'),
                'chart': build_salary_histogram_chart(
                    item["histogram"], f"Salary Distribution - {item['title']}", label="All Filings",
                ),
            }
            for i, item in enumerate(stats['job_title_histograms'], start=1)
        ]
        chart_data['job_title_histograms'] = job_title_charts
        logger.info("[employer_profile] build_chart job_title_histograms slug=%s count=%d took %.3fs", slug, len(job_title_charts), time.perf_counter() - t_job)
    total_bytes = sum(len(v) for v in chart_data.values() if isinstance(v, str))
    total_bytes += sum(len(item.get('chart', '')) for item in chart_data.get('job_title_histograms') or [])
    logger.info("[employer_profile] build_charts slug=%s took %.3fs chart_payload_bytes=%d", slug, time.perf_counter() - t0, total_bytes)
    return chart_data


def _get_or_compute_page_payload(cluster, records, slug: str, cache_key: str, params: dict) -> tuple:
    """
    Return (stats, chart_data, similar_employers, top_state, cache_hit).
    similar_employers is list of dicts (template-safe); uses cache.get_or_set for similar block.
    """
    page_payload = cache.get(cache_key)
    if page_payload is not None:
        return (
            page_payload["stats"],
            page_payload["chart_data"],
            page_payload["similar_employers"],
            page_payload.get("top_state"),
            True,
        )
    t_stats = time.perf_counter()
    stats = _compute_employer_stats(records, slug, params['start_year'])
    logger.info("[employer_profile] stats_compute_total slug=%s took %.3fs", slug, time.perf_counter() - t_stats)

    chart_data = _build_employer_chart_data(stats, cluster, slug)

    top_state = stats['state_dist'][0]['worksite_state'] if stats.get('state_dist') else None
    if top_state:
        similar_cache_key = f"employer_similar_v1:{cluster.id}:{top_state}"
        similar_serialized = cache.get_or_set(
            similar_cache_key,
            lambda: _compute_similar_employers_serialized(cluster.id, cluster, top_state, slug),
            timeout=SIMILAR_EMPLOYERS_CACHE_TIMEOUT,
        )
    else:
        similar_serialized = []

    payload = {
        'stats': stats,
        'chart_data': chart_data,
        'similar_employers': similar_serialized,
        'top_state': top_state,
    }
    cache.set(cache_key, payload)
    return (stats, chart_data, similar_serialized, top_state, False)


def _compute_similar_employers_serialized(cluster_id: int, cluster: EmployerCluster, top_state: str, slug: str) -> list:
    """
    Compute top 5 similar employers (same state); 15s timeout; returns list of dicts for cache.
    Returns [] on timeout or error.
    """
    min_fiscal_year = date.today().year - 5
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = {SIMILAR_EMPLOYERS_QUERY_TIMEOUT_MS}")
            try:
                rows = list(
                    SalaryRecord.objects.filter(
                        worksite_state=top_state,
                        fiscal_year__gte=min_fiscal_year,
                        employer__canonical_cluster__isnull=False,
                        employer__canonical_cluster__slug__isnull=False,
                    )
                    .exclude(employer__canonical_cluster_id=cluster_id)
                    .values('employer__canonical_cluster_id')
                    .annotate(
                        lca_count=Count('id', filter=Q(visa_program=VisaProgram.H1B)),
                        perm_count=Count('id', filter=Q(visa_program=VisaProgram.PERM)),
                    )
                    .annotate(total=F('lca_count') + F('perm_count'))
                    .order_by('-total')[:5]
                )
                if not rows:
                    return []
                cluster_ids_ordered = [r['employer__canonical_cluster_id'] for r in rows]
                clusters_by_id = {
                    c.id: c
                    for c in EmployerCluster.objects.filter(id__in=cluster_ids_ordered)
                }
                result = []
                for r in rows:
                    c = clusters_by_id.get(r['employer__canonical_cluster_id'])
                    if not c:
                        continue
                    result.append({
                        'slug': c.slug,
                        'canonical_name': c.canonical_name,
                        'actual_lca_count': r['lca_count'],
                        'actual_perm_count': r['perm_count'],
                        'total_lca_count': r['lca_count'],
                        'total_perm_count': r['perm_count'],
                    })
                return result
            finally:
                cursor.execute("SET statement_timeout = 0")
    except OperationalError as e:
        if "statement timeout" in str(e).lower() or "canceling statement" in str(e).lower():
            logger.warning("[employer_profile] similar_employers timeout (15s) slug=%s top_state=%s", slug, top_state)
            return []
        raise


@cache_page(settings.CACHE_TIMEOUT)
def employer_profile_view(request, slug):
    """
    Employer profile page showing sponsorship statistics and trends.

    Args:
        slug: Employer cluster slug (from URL)

    Query params:
        years: Number of fiscal years to show (default: 5, max: 20)
        program: Filter by visa program (h1b, perm, all) (default: all)
        level: Filter by experience level (entry, junior, mid, senior, staff, principal,
               lead, manager, director, unspecified, all) (default: all)
    """
    t_page_start = time.perf_counter()

    result = _get_cluster_or_404(slug)
    if hasattr(result, 'status_code'):
        return result
    cluster = result

    params = _parse_employer_profile_params(request)
    records = _get_employer_records_queryset(cluster, params)
    cache_key = f"employer_page_v5:{cluster.id}:{params['program_filter']}:{params['years']}"
    stats, chart_data, similar_employers, top_state, cache_hit = _get_or_compute_page_payload(
        cluster, records, slug, cache_key, params
    )

    # Build SEO metadata
    median_salary = stats["basic"].get("median_salary")
    if median_salary is None:
        median_salary_label = "N/A"
    else:
        median_salary_label = f"${median_salary:,.0f}"

    seo = {
        "title": f"{cluster.canonical_name} H-1B & PERM Sponsorship Data | Visa Bulletin",
        "description": (
            f"{cluster.canonical_name} visa sponsorship statistics: "
            f"{stats['basic']['total_filings']} filings, "
            f"{stats['approval_rate']:.1f}% approval rate, "
            f"{median_salary_label} median salary."
        ),
        "canonical_url": request.build_absolute_uri(),
    }
    
    context = {
        'cluster': cluster,
        'stats': stats,
        'chart_data': chart_data,
        'seo': seo,
        'years': params['years'],
        'program_filter': params['program_filter'],
        'level_filter': params['level_filter'],
        'level_choices': params['level_choices'],
        'start_year': params['start_year'],
        'similar_employers': similar_employers,
        'top_state': top_state,
        'company_autocomplete_url': request.build_absolute_uri(reverse('company_autocomplete')),
    }

    t0 = time.perf_counter()
    response = render(request, 'webapp/employer_profile.html', context)
    logger.info("[employer_profile] render slug=%s took %.3fs", slug, time.perf_counter() - t0)
    logger.info("[employer_profile] page_total slug=%s cache_hit=%s took %.3fs", slug, cache_hit, time.perf_counter() - t_page_start)
    return response


def _build_employer_profile_charts(stats, employer_name, slug=None):
    """Build Plotly chart data for employer profile page."""
    from decimal import Decimal
    import plotly.graph_objs as go

    def _scale_axis_max(value, scale=1.2):
        if not value:
            return 1
        if isinstance(value, Decimal):
            return value * Decimal(str(scale))
        return value * scale

    charts = {}
    log_slug = slug or ""

    # Chart 1: Salary Distribution Histogram
    if stats.get('salary_histogram'):
        t0 = time.perf_counter()
        charts['salary_histogram'] = build_salary_histogram_chart(
            stats['salary_histogram'],
            f"Salary Distribution - {employer_name}",
            label="All Filings",
        )
        if log_slug:
            logger.info("[employer_profile] build_chart salary_histogram slug=%s took %.3fs size=%d", log_slug, time.perf_counter() - t0, len(charts['salary_histogram']))

    # Chart 2: Filings by State (Bar Chart)
    if stats['state_dist']:
        t0 = time.perf_counter()
        state_by_filings = sorted(
            stats['state_dist'],
            key=lambda item: item['count'],
            reverse=True,
        )
        states = [s['worksite_state'] for s in state_by_filings]
        counts = [s['count'] for s in state_by_filings]
        medians = [s['median_salary'] for s in state_by_filings]
        max_count = max(counts) if counts else 0
        y_max = _scale_axis_max(max_count)

        fig = go.Figure(data=[
            go.Bar(
                x=states,
                y=counts,
                text=[f"{c:,}" for c in counts],
                textposition='auto',
                cliponaxis=False,
                hovertemplate='<b>%{x}</b><br>Filings: %{y:,}<br>Median Salary: $%{customdata[0]:,.0f}<extra></extra>',
                customdata=[[m] for m in medians],
                marker_color='rgb(55, 83, 109)',
            )
        ])

        fig.update_layout(
            title="Filings by State",
            xaxis_title="State",
            yaxis_title="Number of Filings",
            height=400,
            template='plotly_white',
            showlegend=False,
            yaxis={'range': [0, y_max]},
            margin=dict(t=60, b=60, l=60, r=20),
        )

        charts['state_filings'] = fig.to_json()
        if log_slug:
            logger.info("[employer_profile] build_chart state_filings slug=%s took %.3fs size=%d", log_slug, time.perf_counter() - t0, len(charts['state_filings']))

        t0 = time.perf_counter()
        state_by_median = sorted(
            stats['state_dist'],
            key=lambda item: item['median_salary'] or 0,
            reverse=True,
        )
        states = [s['worksite_state'] for s in state_by_median]
        counts = [s['count'] for s in state_by_median]
        medians = [s['median_salary'] for s in state_by_median]
        max_median = max(medians) if medians else 0
        y_max = _scale_axis_max(max_median)
        
        fig = go.Figure(data=[
            go.Bar(
                x=states,
                y=medians,
                text=[f"${m:,.0f}" for m in medians],
                textposition='auto',
                cliponaxis=False,
                hovertemplate='<b>%{x}</b><br>Median Salary: $%{y:,.0f}<br>Filings: %{customdata[0]:,}<extra></extra>',
                customdata=[[c] for c in counts],
                marker_color='rgb(26, 118, 255)',
            )
        ])
        
        fig.update_layout(
            title="Median Salary by State",
            xaxis_title="State",
            yaxis_title="Median Salary ($)",
            height=400,
            template='plotly_white',
            showlegend=False,
            yaxis={'range': [0, y_max]},
            margin=dict(t=60, b=60, l=60, r=20),
        )

        charts['state_median_salary'] = fig.to_json()
        if log_slug:
            logger.info("[employer_profile] build_chart state_median_salary slug=%s took %.3fs size=%d", log_slug, time.perf_counter() - t0, len(charts['state_median_salary']))

    # Chart 3: Year-over-Year Filing Volume (Line Chart)
    if stats['yoy_trends'] and len(stats['yoy_trends']) > 1:
        t0 = time.perf_counter()
        years = [t['fiscal_year'] for t in stats['yoy_trends']]
        counts = [t['count'] for t in stats['yoy_trends']]
        
        fig = go.Figure(data=[
            go.Scatter(
                x=years,
                y=counts,
                mode='lines+markers',
                line=dict(color='rgb(55, 83, 109)', width=3),
                marker=dict(size=8),
                hovertemplate='<b>FY %{x}</b><br>Filings: %{y:,}<extra></extra>',
            )
        ])
        
        fig.update_layout(
            title="Filing Volume Over Time",
            xaxis_title="Fiscal Year",
            yaxis_title="Number of Filings",
            height=350,
            template='plotly_white',
            showlegend=False,
        )

        charts['filing_volume'] = fig.to_json()
        if log_slug:
            logger.info("[employer_profile] build_chart filing_volume slug=%s took %.3fs size=%d", log_slug, time.perf_counter() - t0, len(charts['filing_volume']))

    # Chart 4: Year-over-Year Salary Trends (Line Chart)
    if stats['yoy_trends'] and len(stats['yoy_trends']) > 1:
        t0 = time.perf_counter()
        years = [t['fiscal_year'] for t in stats['yoy_trends']]
        salaries = [t['median_salary'] for t in stats['yoy_trends']]
        
        fig = go.Figure(data=[
            go.Scatter(
                x=years,
                y=salaries,
                mode='lines+markers',
                line=dict(color='rgb(26, 118, 255)', width=3),
                marker=dict(size=8),
                hovertemplate='<b>FY %{x}</b><br>Median Salary: $%{y:,.0f}<extra></extra>',
            )
        ])
        
        fig.update_layout(
            title="Median Salary Trend",
            xaxis_title="Fiscal Year",
            yaxis_title="Median Salary ($)",
            height=350,
            template='plotly_white',
            showlegend=False,
        )

        charts['salary_trend'] = fig.to_json()
        if log_slug:
            logger.info("[employer_profile] build_chart salary_trend slug=%s took %.3fs size=%d", log_slug, time.perf_counter() - t0, len(charts['salary_trend']))

    total_charts_size = sum(len(v) for v in charts.values() if isinstance(v, str))
    if log_slug:
        logger.info("[employer_profile] build_charts_total slug=%s charts_bytes=%d chart_keys=%s", log_slug, total_charts_size, list(charts.keys()))
    return charts


def _build_employer_salary_histograms(records, top_titles, min_salary, max_salary, num_bins=20):
    """
    Build salary histogram data for employer and per job title.

    Uses the same 95th-percentile cap as job title profile (common_stats) so the
    chart does not show a long empty tail when a few salaries extend far right.
    """
    overlay_values = [
        t['job_title_entity__canonical_cluster__canonical_title']
        for t in top_titles
        if t.get('job_title_entity__canonical_cluster__canonical_title')
    ]
    result = calculate_salary_histogram_with_overlays(
        records,
        overlay_values,
        overlay_field='job_title_entity__canonical_cluster__canonical_title',
        num_bins=num_bins,
    )
    if not result or not result.get('bins'):
        return {}, []

    histogram_data = {
        'bins': result['bins'],
        'overlays': [],
        'label': 'All Filings',
    }
    title_histograms = _build_title_histograms_from_overlays(
        result['bins'],
        result['overlays'],
        top_titles,
    )
    return histogram_data, title_histograms


def _build_title_histograms_from_overlays(bins, overlays, top_titles):
    """Build per-title histogram list from shared overlay result (same bins, per-title counts)."""
    top_titles_with_title = [
        t for t in top_titles
        if t.get('job_title_entity__canonical_cluster__canonical_title')
    ]
    title_histograms = []
    for overlay, top_title in zip(overlays, top_titles_with_title):
        title_label = overlay.get('employer_name') or top_title.get('job_title_entity__canonical_cluster__canonical_title') or 'Unspecified'
        counts = overlay.get('counts', [])
        total = sum(counts)
        if total == 0:
            continue
        filled_bins = [
            {**{k: v for k, v in bin_data.items() if k != 'count'}, 'count': counts[i]}
            for i, bin_data in enumerate(bins)
        ]
        title_histograms.append({
            'title': title_label,
            'slug': top_title.get('job_title_entity__canonical_cluster__slug') or None,
            'total': total,
            'histogram': {
                'bins': filled_bins,
                'overlays': [],
                'label': 'All Filings',
            },
        })
    title_histograms.sort(key=lambda item: (-item['total'], item['title']))
    return title_histograms


def _build_job_title_overlays(title_histograms, limit=6):
    overlays = []
    for item in title_histograms[:limit]:
        histogram = item.get('histogram', {})
        bins = histogram.get('bins', [])
        if not bins:
            continue
        overlays.append({
            'employer_name': item['title'],
            'counts': [bin_data['count'] for bin_data in bins],
        })
    return overlays
