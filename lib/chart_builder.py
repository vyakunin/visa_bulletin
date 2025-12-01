"""
Chart building logic for visa bulletin dashboard

Creates Plotly charts with historical data and projections.
"""

from datetime import date
import plotly.graph_objects as go

from models.enums.country import Country


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
    Build Plotly chart HTML with historical data and projection
    
    Args:
        dates: List of bulletin publication dates
        cutoff_dates: List of priority date cutoffs (may contain None)
        submission_date: User's application submission date
        projection: Projection result from calculate_projection()
        visa_class: Visa class (e.g., 'F1', 'EB2')
        country: Country code (e.g., 'china', 'all')
        bulletin_urls: List of URLs to official bulletins (optional)
        
    Returns:
        HTML string containing Plotly chart with clickable points
        
    Example:
        >>> dates = [date(2024, 1, 1), date(2024, 2, 1)]
        >>> cutoffs = [date(2020, 1, 1), date(2020, 2, 1)]
        >>> submission = date(2021, 1, 1)
        >>> projection = {'status': 'projected', 'estimated_date': date(2025, 1, 1)}
        >>> urls = ['https://travel.state.gov/...', ...]
        >>> html = build_chart_with_projection(dates, cutoffs, submission, projection, 'F1', 'china', urls)
        >>> 'plotly' in html
        True
    """
    # Create figure
    fig = go.Figure()
    
    # Historical data line with clickable points
    customdata = bulletin_urls if bulletin_urls else [None] * len(dates)
    
    fig.add_trace(go.Scatter(
        x=dates,
        y=cutoff_dates,
        mode='lines+markers',
        name='Historical Priority Dates',
        line=dict(color='#0d6efd', width=2),
        marker=dict(size=6),
        customdata=customdata,
        hovertemplate='<b>Bulletin:</b> %{x|%B %Y}<br><b>Priority Date:</b> %{y|%b %d, %Y}<br><i>Click to view official bulletin</i><extra></extra>'
    ))
    
    # Determine end date for submission line (extend to projection if available)
    submission_line_end = dates[-1]
    if projection and projection['estimated_date']:
        submission_line_end = projection['estimated_date']
    
    # Submission date horizontal line (extends to projection endpoint)
    fig.add_trace(go.Scatter(
        x=[dates[0], submission_line_end],
        y=[submission_date, submission_date],
        mode='lines',
        name=f'Your Submission Date: {submission_date.strftime("%b %d, %Y")}',
        line=dict(color='red', width=2, dash='dash'),
        hovertemplate=f'<b>Your Submission Date:</b> {submission_date.strftime("%b %d, %Y")}<extra></extra>'
    ))
    
    # Add projection if available
    if projection and projection['estimated_date']:
        # Projection line from last known point to estimated date
        last_valid_cutoff = next((c for c in reversed(cutoff_dates) if c is not None), None)
        if last_valid_cutoff:
            proj_x = [dates[-1], projection['estimated_date']]
            proj_y = [last_valid_cutoff, submission_date]
            
            fig.add_trace(go.Scatter(
                x=proj_x,
                y=proj_y,
                mode='lines+markers',
                name='Projection',
                line=dict(color='orange', width=2, dash='dash'),
                marker=dict(size=8, symbol='star'),
                hovertemplate='<b>Estimated Processing:</b> %{x|%B %Y}<extra></extra>'
            ))
    
    # Layout with mobile optimizations
    country_label = Country(country).label if country in [c.value for c in Country] else country
    fig.update_layout(
        title=dict(
            text=f'Priority Date Progress: {visa_class} - {country_label}',
            font=dict(size=16)
        ),
        xaxis=dict(
            title=dict(text='Bulletin Publication Date', font=dict(size=12)),
            tickfont=dict(size=10)
        ),
        yaxis=dict(
            title=dict(text='Priority Date Cutoff', font=dict(size=12)),
            tickfont=dict(size=10)
        ),
        hovermode='closest',
        template='plotly_white',
        height=500,  # Reduced for mobile
        showlegend=True,
        legend=dict(
            orientation="v",  # Vertical legend works better on mobile
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='#ddd',
            borderwidth=1,
            font=dict(size=10)
        ),
        margin=dict(t=60, r=20, b=60, l=60)  # Tighter margins
    )
    
    # Convert to HTML with mobile-friendly config
    chart_html = fig.to_html(
        include_plotlyjs='cdn',
        div_id='priority-date-chart',
        config={
            'displayModeBar': True,
            'displaylogo': False,
            'responsive': True,
            'modeBarButtonsToRemove': ['pan2d', 'select2d', 'lasso2d'],
            'toImageButtonOptions': {
                'format': 'png',
                'filename': 'visa_bulletin_chart',
                'height': 800,
                'width': 1200,
                'scale': 2
            }
        }
    )
    
    # Add JavaScript for click handling to open bulletin URLs
    if bulletin_urls:
        click_script = """
        <script>
        document.getElementById('priority-date-chart').on('plotly_click', function(data){
            var point = data.points[0];
            if (point.customdata) {
                window.open(point.customdata, '_blank');
            }
        });
        </script>
        """
        chart_html += click_script
    
    return chart_html

