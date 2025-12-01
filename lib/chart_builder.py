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
) -> str:
    """
    Build Plotly chart HTML with multiple visa classes, each with projection
    
    Args:
        visa_class_data: List of dicts, each containing:
            - visa_class: str (e.g., 'F1', 'EB2')
            - visa_class_label: str (e.g., 'F1: Unmarried Sons/Daughters...') [optional]
            - dates: list[date] (bulletin publication dates)
            - cutoff_dates: list[date | None] (priority date cutoffs)
            - projection: dict | None (projection result)
            - bulletin_urls: list[str] | None (optional URLs)
        submission_date: User's application submission date
        country: Country code (e.g., 'china', 'all')
        category_label: Category display name (e.g., 'Family-Sponsored')
        
    Returns:
        HTML string containing Plotly chart with clickable points
    """
    # Create figure
    fig = go.Figure()
    
    # Track maximum projection date for submission line
    max_projection_date = None
    
    # Add a trace for each visa class
    for idx, data in enumerate(visa_class_data):
        visa_class = data['visa_class']
        visa_class_label = data.get('visa_class_label', visa_class)  # Full label or fallback to code
        dates = data['dates']
        cutoff_dates = data['cutoff_dates']
        projection = data.get('projection')
        bulletin_urls = data.get('bulletin_urls', [])
        
        color = VISA_CLASS_COLORS[idx % len(VISA_CLASS_COLORS)]
        
        # Historical data line with clickable points
        customdata = bulletin_urls if bulletin_urls else [None] * len(dates)
        
        fig.add_trace(go.Scatter(
            x=dates,
            y=cutoff_dates,
            mode='lines+markers',
            name=visa_class_label,
            line=dict(color=color, width=2),
            marker=dict(size=5),
            customdata=customdata,
            legendgroup=visa_class,  # Group with projection line
            hovertemplate=f'<b>{visa_class_label}</b><br><b>Bulletin:</b> %{{x|%B %Y}}<br><b>Priority Date:</b> %{{y|%b %d, %Y}}<br><i>Click to view bulletin</i><extra></extra>'
        ))
        
        # Add projection if available
        if projection and projection.get('estimated_date'):
            last_valid_cutoff = next((c for c in reversed(cutoff_dates) if c is not None), None)
            if last_valid_cutoff:
                proj_x = [dates[-1], projection['estimated_date']]
                proj_y = [last_valid_cutoff, submission_date]
                
                fig.add_trace(go.Scatter(
                    x=proj_x,
                    y=proj_y,
                    mode='lines+markers',
                    name=f'{visa_class_label} (Projection)',
                    line=dict(color=color, width=2, dash='dash'),
                    marker=dict(size=6, symbol='star'),
                    legendgroup=visa_class,  # Same group as main line
                    hovertemplate=f'<b>{visa_class_label}</b><br><b>Estimated:</b> %{{x|%B %Y}}<extra></extra>',
                    showlegend=False  # Don't clutter legend with projection lines
                ))
                
                # Track max projection date
                if max_projection_date is None or projection['estimated_date'] > max_projection_date:
                    max_projection_date = projection['estimated_date']
    
    # Submission date horizontal line (extends to furthest projection)
    if visa_class_data:
        first_dates = visa_class_data[0]['dates']
        submission_line_end = max_projection_date if max_projection_date else first_dates[-1]
        
        fig.add_trace(go.Scatter(
            x=[first_dates[0], submission_line_end],
            y=[submission_date, submission_date],
            mode='lines',
            name=f'Your Priority Date: {submission_date.strftime("%b %d, %Y")}',
            line=dict(color='red', width=3, dash='dash'),
            hovertemplate=f'<b>Your Priority Date:</b> {submission_date.strftime("%b %d, %Y")}<extra></extra>'
        ))
    
    # Layout with mobile optimizations
    country_label = Country(country).label if country in [c.value for c in Country] else country
    fig.update_layout(
        title=dict(
            text=f'Priority Date Progress: {category_label} - {country_label}',
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
    
    Args:
        dates: List of bulletin publication dates
        cutoff_dates: List of priority date cutoffs (may contain None)
        submission_date: User's application submission date
        projection: Projection result from calculate_projection()
        visa_class: Visa class (e.g., 'F1', 'EB2')
        country: Country code (e.g., 'china', 'all')
        bulletin_urls: List of URLs to official bulletins (optional)
        
    Returns:
        HTML string containing Plotly chart
    """
    # Convert to new multi-class format
    visa_class_data = [{
        'visa_class': visa_class,
        'visa_class_label': visa_class,  # Legacy mode: just use code
        'dates': dates,
        'cutoff_dates': cutoff_dates,
        'projection': projection,
        'bulletin_urls': bulletin_urls
    }]
    
    return build_multi_class_chart_with_projections(
        visa_class_data, 
        submission_date, 
        country,
        visa_class
    )

