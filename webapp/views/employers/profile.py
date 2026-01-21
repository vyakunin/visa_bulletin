"""Employer profile views and chart helpers."""

from datetime import datetime

from django.core.cache import cache
from django.db.models import Avg, Count, Exists, F, Max, Min, OuterRef, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_page

from lib.business.salary.common_stats import (
    calculate_salary_percentiles,
    calculate_yoy_growth,
    calculate_yoy_trends,
)
from lib.business.salary.common_chart_builder import build_salary_histogram_chart
from models.enums.visa_program import VisaProgram
from models.job_title import JobTitle
from models.salary import Employer, EmployerCluster, SalaryRecord


@cache_page(60 * 60 * 6)  # Cache for 6 hours
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
        level: Filter by experience level (entry, junior, mid, senior, staff, principal,
               lead, manager, director, unspecified, all) (default: all)
        level: Filter by experience level (entry, junior, mid, senior, staff, principal,
               lead, manager, director, unspecified, all) (default: all)
    """
    # 1. Try to find cluster by slug
    try:
        cluster = EmployerCluster.objects.get(slug=slug)
    except EmployerCluster.DoesNotExist:
        # 2. Try to find by name variation and redirect
        # Search for employers with similar normalized names
        slug_normalized = slug.replace('-', ' ').lower()
        employers = Employer.objects.filter(
            name_normalized__icontains=slug_normalized
        ).select_related('canonical_cluster')
        
        if employers.exists():
            # Get the first employer's cluster and redirect to canonical URL
            canonical_cluster = employers.first().canonical_cluster
            if canonical_cluster and canonical_cluster.slug:
                return redirect('employer_profile', slug=canonical_cluster.slug, permanent=True)
        
        # 3. Not found - raise 404
        raise Http404("Employer not found")

    if cluster.canonical_name == "Unknown" or cluster.slug == "unknown":
        raise Http404("Employer not found")
    
    # Get query parameters
    try:
        years = min(int(request.GET.get('years', 5)), 20)  # Max 20 years
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
    
    # Calculate start year
    current_year = datetime.now().year
    start_year = current_year - years
    
    # Build base queryset for employer cluster records
    records = SalaryRecord.objects.filter(
        employer__canonical_cluster=cluster,
        fiscal_year__gte=start_year,
        wage_annual__isnull=False,  # Only records with valid salary data
        is_worksite=False,
    )
    
    # Apply program filter
    if program_filter == 'h1b':
        records = records.filter(visa_program=VisaProgram.H1B)
    elif program_filter == 'perm':
        records = records.filter(visa_program=VisaProgram.PERM)
    
    # Build cache key (include version to invalidate old cached data without slugs)
    cache_key = f"employer_stats_v5:{cluster.id}:{program_filter}:{years}"
    stats = cache.get(cache_key)
    
    if stats is None:
        # Compute basic statistics
        basic_stats = records.aggregate(
            total_filings=Count('id'),
            approved_filings=Count('id', filter=Q(case_status=1)),  # CaseStatus.CERTIFIED = 1
            median_salary=Avg('wage_annual'),
            min_salary=Min('wage_annual'),
            max_salary=Max('wage_annual'),
        )
        
        # Calculate approval rate
        approval_rate = 0
        if basic_stats['total_filings'] > 0:
            approval_rate = (basic_stats['approved_filings'] / basic_stats['total_filings']) * 100
        
        # Top job titles with salary stats (include cluster slug for linking)
        # Group by canonical cluster to avoid per-variation counts
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
            .order_by(
                '-count',
                'job_title_entity__canonical_cluster__canonical_title',
            )[:10]
        )
        
        salary_percentiles = calculate_salary_percentiles(records)
        histogram_data, title_histograms = _build_employer_salary_histograms(
            records,
            basic_stats.get('min_salary'),
            basic_stats.get('max_salary'),
        )
        if histogram_data and title_histograms:
            histogram_data['overlays'] = _build_job_title_overlays(title_histograms, limit=6)
        
        # Geographic distribution
        state_dist = list(
            records
            .values('worksite_state')
            .annotate(
                count=Count('id'),
                median_salary=Avg('wage_annual'),
            )
            .order_by('-count')[:15]
        )
        
        # Year-over-year trends
        yoy_trends = calculate_yoy_trends(records)
        yoy_growth, _, _, _ = calculate_yoy_growth(yoy_trends, start_year)
        
        stats = {
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
        
        # Cache for 6 hours
        cache.set(cache_key, stats, timeout=60*60*6)
    
    # Build chart data (Plotly format)
    chart_data = _build_employer_profile_charts(stats, cluster.canonical_name)
    if stats.get('job_title_histograms'):
        job_title_charts = []
        for index, item in enumerate(stats['job_title_histograms'], start=1):
            chart_json = build_salary_histogram_chart(
                item["histogram"],
                f"Salary Distribution - {item['title']}",
                label="All Filings",
            )
            job_title_charts.append({
                'id': index,
                'title': item['title'],
                'slug': item.get('slug'),
                'chart': chart_json,
            })
        chart_data['job_title_histograms'] = job_title_charts
    
    # Get similar employers (top employers in same state)
    # Find most common state for this employer
    top_state = None
    if stats['state_dist']:
        top_state = stats['state_dist'][0]['worksite_state']
    
    similar_employers = []
    if top_state:
        # Get top 5 employers in same state (excluding current employer)
        # Use subquery to find clusters with employers that have salary records in this state
        # Subquery: find employers in clusters that have salary records in top_state
        employers_in_state = Employer.objects.filter(
            canonical_cluster=OuterRef('pk'),
            salary_records__worksite_state=top_state,
        )
        
        # Calculate actual counts from SalaryRecord objects
        similar_employers = list(
            EmployerCluster.objects
            .filter(slug__isnull=False)
            .exclude(id=cluster.id)
            .filter(Exists(employers_in_state))
            .annotate(
                actual_lca_count=Count(
                    'employers__salary_records__id',
                    filter=Q(employers__salary_records__visa_program=VisaProgram.H1B),
                    distinct=True,
                ),
                actual_perm_count=Count(
                    'employers__salary_records__id',
                    filter=Q(employers__salary_records__visa_program=VisaProgram.PERM),
                    distinct=True,
                ),
            )
            .annotate(total_count=F('actual_lca_count') + F('actual_perm_count'))
            .order_by('-total_count')[:5]
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
        'years': years,
        'program_filter': program_filter,
        'level_filter': level_filter,
        'level_choices': level_choices,
        'level_filter': level_filter,
        'level_choices': level_choices,
        'level_filter': level_filter,
        'level_choices': level_choices,
        'start_year': start_year,
        'similar_employers': similar_employers,
        'top_state': top_state,
    }
    
    return render(request, 'webapp/employer_profile.html', context)


def _build_employer_profile_charts(stats, employer_name):
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
    
    # Chart 1: Salary Distribution Histogram
    if stats.get('salary_histogram'):
        charts['salary_histogram'] = _build_salary_histogram(
            stats['salary_histogram'],
            employer_name,
        )
    
    # Chart 2: Filings by State (Bar Chart)
    if stats['state_dist']:
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
    
    # Chart 3: Year-over-Year Filing Volume (Line Chart)
    if stats['yoy_trends'] and len(stats['yoy_trends']) > 1:
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
    
    # Chart 4: Year-over-Year Salary Trends (Line Chart)
    if stats['yoy_trends'] and len(stats['yoy_trends']) > 1:
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
    
    return charts


def _build_employer_salary_histograms(records, min_salary, max_salary, num_bins=20):
    """Build salary histogram data for employer and per job title."""
    bins, bin_width = _build_histogram_bins(min_salary, max_salary, num_bins)
    if not bins or not bin_width:
        return {}, []

    overall_counts, title_counts = _count_histogram_bins(records, bins, bin_width)
    histogram_data = _build_histogram_payload(bins, overall_counts, label='All Filings')
    title_histograms = _build_title_histograms(bins, title_counts)
    return histogram_data, title_histograms


def _build_histogram_bins(min_salary, max_salary, num_bins):
    if min_salary is None or max_salary is None:
        return [], 0
    min_value = float(min_salary)
    max_value = float(max_salary)
    if min_value == max_value:
        return [], 0
    bin_width = (max_value - min_value) / num_bins
    if bin_width == 0:
        return [], 0
    bins = []
    for i in range(num_bins):
        bin_start = min_value + (i * bin_width)
        bin_end = bin_start + bin_width
        bins.append({
            'range_start': bin_start,
            'range_end': bin_end,
            'label': f'${bin_start:,.0f} - ${bin_end:,.0f}',
        })
    return bins, bin_width


def _count_histogram_bins(records, bins, bin_width):
    num_bins = len(bins)
    min_value = bins[0]['range_start']
    overall_counts = [0] * num_bins
    title_counts = {}
    values = records.values_list(
        'wage_annual',
        'job_title_entity__canonical_cluster__canonical_title',
        'job_title_entity__canonical_cluster__slug',
    )
    for wage, title, slug in values:
        if wage is None:
            continue
        index = _get_histogram_index(float(wage), min_value, bin_width, num_bins)
        overall_counts[index] += 1
        title_label = title or "Unspecified"
        key = (title_label, slug or "")
        if key not in title_counts:
            title_counts[key] = [0] * num_bins
        title_counts[key][index] += 1
    return overall_counts, title_counts


def _get_histogram_index(wage_value, min_value, bin_width, num_bins):
    index = int((wage_value - min_value) / bin_width)
    if index >= num_bins:
        return num_bins - 1
    if index < 0:
        return 0
    return index


def _build_histogram_payload(bins, counts, label):
    filled_bins = []
    for i, bin_data in enumerate(bins):
        filled_bins.append({
            **bin_data,
            'count': counts[i],
        })
    return {
        'bins': filled_bins,
        'overlays': [],
        'label': label,
    }


def _build_title_histograms(bins, title_counts):
    title_histograms = []
    for (title_label, slug), counts in title_counts.items():
        total = sum(counts)
        if total == 0:
            continue
        title_histograms.append({
            'title': title_label,
            'slug': slug or None,
            'total': total,
            'histogram': _build_histogram_payload(bins, counts, label='All Filings'),
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
