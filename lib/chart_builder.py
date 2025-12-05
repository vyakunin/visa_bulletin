"""
Chart building logic for visa bulletin dashboard

Creates Plotly charts with historical data and projections.
"""

from datetime import date
import plotly.graph_objects as go

from models.enums.country import Country


# Color palette for multiple visa classes
VISA_CLASS_COLORS = [
    '#0d6efd',  # Blue
    '#198754',  # Green
    '#dc3545',  # Red
    '#ffc107',  # Yellow
    '#6f42c1',  # Purple
    '#fd7e14',  # Orange
    '#20c997',  # Teal
    '#e83e8c',  # Pink
]


def build_multi_class_chart_with_projections(
    visa_class_data: list[dict],
    submission_date: date,
    country: str,
    category_label: str
) -> dict:
    """
    Build Plotly chart data with multiple visa classes, each with projection
    
    Args:
        visa_class_data: List of dicts with visa_class, dates, cutoff_dates, projection, bulletin_urls
        submission_date: User's application submission date
        country: Country code (e.g., 'china', 'all')
        category_label: Category display name (e.g., 'Family-Sponsored')
        
    Returns:
        Dict with 'chart_json' and 'trace_info' for checkbox controls
    """
    fig = go.Figure()
    trace_info = []
    current_trace_idx = 0
    max_projection_date = None
    
    # Add traces for each visa class
    for idx, data in enumerate(visa_class_data):
        color = VISA_CLASS_COLORS[idx % len(VISA_CLASS_COLORS)]
        
        trace_indices, proj_date, current_trace_idx = _add_visa_class_traces(
            fig, data, color, submission_date, current_trace_idx
        )
        
        if proj_date and (max_projection_date is None or proj_date > max_projection_date):
            max_projection_date = proj_date
        
        trace_info.append({
            'visa_class': data['visa_class'],
            'label': data.get('visa_class_label', data['visa_class']),
            'color': color,
            'trace_indices': trace_indices
        })
    
    # Add priority date line
    priority_date_trace_idx = current_trace_idx
    if visa_class_data:
        _add_priority_date_line(fig, visa_class_data, submission_date, max_projection_date)
    
    # Configure layout
    _apply_chart_layout(fig, category_label, country)
    
    return {
        'chart_json': fig.to_json(),
        'trace_info': trace_info,
        'priority_date_trace_idx': priority_date_trace_idx,
        'submission_date_formatted': submission_date.strftime("%b %d, %Y")
    }


def _add_visa_class_traces(
    fig: go.Figure,
    data: dict,
    color: str,
    submission_date: date,
    current_idx: int
) -> tuple[list[int], date | None, int]:
    """
    Add historical and projection traces for a single visa class
    
    Returns:
        Tuple of (trace_indices, projection_date, next_trace_idx)
    """
    visa_class_label = data.get('visa_class_label', data['visa_class'])
    dates = data['dates']
    cutoff_dates = data['cutoff_dates']
    projection = data.get('projection')
    bulletin_urls = data.get('bulletin_urls', [])
    
    trace_indices = []
    projection_date = None
    
    # Historical data trace
    customdata = bulletin_urls if bulletin_urls else [None] * len(dates)
    fig.add_trace(go.Scatter(
        x=dates,
        y=cutoff_dates,
        mode='lines+markers',
        name=visa_class_label,
        line=dict(color=color, width=2),
        marker=dict(size=5),
        customdata=customdata,
        hovertemplate=(
            f'<b>{visa_class_label}</b><br>'
            f'<b>Bulletin:</b> %{{x|%B %Y}}<br>'
            f'<b>Priority Date:</b> %{{y|%b %d, %Y}}<br>'
            f'<i>Click to view bulletin</i><extra></extra>'
        )
    ))
    trace_indices.append(current_idx)
    current_idx += 1
    
    # Projection trace (if available)
    if projection and projection.get('estimated_date'):
        last_valid_cutoff = next((c for c in reversed(cutoff_dates) if c is not None), None)
        if last_valid_cutoff:
            projection_date = projection['estimated_date']
            fig.add_trace(go.Scatter(
                x=[dates[-1], projection_date],
                y=[last_valid_cutoff, submission_date],
                mode='lines+markers',
                name=f'{visa_class_label} (Projection)',
                line=dict(color=color, width=2, dash='dash'),
                marker=dict(size=6, symbol='star'),
                hovertemplate=f'<b>{visa_class_label}</b><br><b>Estimated:</b> %{{x|%B %Y}}<extra></extra>'
            ))
            trace_indices.append(current_idx)
            current_idx += 1
    
    return trace_indices, projection_date, current_idx


def _add_priority_date_line(
    fig: go.Figure,
    visa_class_data: list[dict],
    submission_date: date,
    max_projection_date: date | None
) -> None:
    """Add horizontal line showing user's priority date"""
    first_dates = visa_class_data[0]['dates']
    line_end = max_projection_date if max_projection_date else first_dates[-1]
    
    fig.add_trace(go.Scatter(
        x=[first_dates[0], line_end],
        y=[submission_date, submission_date],
        mode='lines',
        name=f'Your Priority Date: {submission_date.strftime("%b %d, %Y")}',
        line=dict(color='red', width=3, dash='dash'),
        hovertemplate=f'<b>Your Priority Date:</b> {submission_date.strftime("%b %d, %Y")}<extra></extra>'
    ))


def _apply_chart_layout(fig: go.Figure, category_label: str, country: str) -> None:
    """Apply mobile-optimized layout to chart"""
    country_label = _get_country_label(country)
    # Title on left to avoid modebar overlap
    title_text = f'{category_label} ({country_label})'
    
    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=13),
            x=0,
            xanchor='left',
            y=0.99,
            yanchor='top'
        ),
        xaxis=dict(
            title=dict(text='Bulletin Date', font=dict(size=11)),
            tickfont=dict(size=9),
            automargin=True
        ),
        yaxis=dict(
            title=dict(text='Cutoff Date', font=dict(size=11)),
            tickfont=dict(size=9),
            automargin=True
        ),
        hovermode='closest',
        template='plotly_white',
        height=400,
        showlegend=False,
        margin=dict(t=30, r=10, b=35, l=45),
        autosize=True
    )


def _get_country_label(country: str) -> str:
    """Get display label for country code"""
    try:
        return Country(country).label
    except ValueError:
        return country


def build_chart_with_projection(
    dates: list[date],
    cutoff_dates: list[date | None],
    submission_date: date,
    projection: dict[str, any] | None,
    visa_class: str,
    country: str,
    bulletin_urls: list[str] | None = None
) -> str:
    """
    Legacy single-class chart builder (kept for backward compatibility)
    
    Returns:
        HTML string containing self-contained Plotly chart
    """
    visa_class_data = [{
        'visa_class': visa_class,
        'visa_class_label': visa_class,
        'dates': dates,
        'cutoff_dates': cutoff_dates,
        'projection': projection,
        'bulletin_urls': bulletin_urls
    }]
    
    chart_data = build_multi_class_chart_with_projections(
        visa_class_data, submission_date, country, visa_class
    )
    
    return _wrap_chart_as_html(chart_data['chart_json'])


def _wrap_chart_as_html(chart_json: str) -> str:
    """Wrap chart JSON in self-contained HTML with initialization script"""
    return f"""
    <div id="priority-date-chart" class="plotly-graph-div" style="height:500px; width:100%;"></div>
    <script type="text/javascript">
    document.addEventListener('DOMContentLoaded', function() {{
        var initChart = function() {{
            if (typeof Plotly === 'undefined') {{
                setTimeout(initChart, 50);
                return;
            }}
            var chartData = {chart_json};
            var config = {{
                'displayModeBar': true,
                'displaylogo': false,
                'responsive': true,
                'modeBarButtonsToRemove': ['pan2d', 'select2d', 'lasso2d']
            }};
            Plotly.newPlot('priority-date-chart', chartData.data, chartData.layout, config).then(function(gd) {{
                gd.on('plotly_click', function(data){{
                    var point = data.points[0];
                    if (point.customdata) {{
                        window.open(point.customdata, '_blank');
                    }}
                }});
            }});
        }};
        initChart();
    }});
    </script>
    """
