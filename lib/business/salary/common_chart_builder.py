"""
Shared Plotly chart builders for salary pages.
"""

import json

import plotly.graph_objs as go
import plotly.utils


def build_salary_histogram_chart(histogram_data: dict, title: str, label: str | None = None) -> str:
    """Build salary distribution histogram with overlays."""
    bins = histogram_data.get("bins", [])
    overlays = histogram_data.get("overlays", [])
    default_label = histogram_data.get("label", "All Filings")
    label = label or default_label
    labels = [bin_data["label"] for bin_data in bins]
    counts = [bin_data["count"] for bin_data in bins]

    if not bins:
        fig = go.Figure()
        fig.update_layout(
            title=title,
            xaxis_title="Salary Range",
            yaxis_title="Number of Filings",
            height=400,
            template="plotly_white",
            showlegend=False,
        )
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    max_count = max(counts) if counts else 0
    y_max = max_count * 1.2 if max_count else 1

    data = [
        go.Bar(
            x=labels,
            y=counts,
            name=label,
            opacity=0.35,
            marker_color="rgba(100, 100, 100, 0.45)",
            hovertemplate=f"<b>%{{x}}</b><br>{label}: %{{y:,}}<extra></extra>",
        )
    ]

    for overlay in overlays:
        overlay_counts = overlay.get("counts", [])
        if not overlay_counts:
            continue
        data.append(
            go.Scatter(
                x=labels,
                y=overlay_counts,
                mode="lines+markers",
                name=overlay.get("employer_name", "Overlay"),
                hovertemplate="<b>%{x}</b><br>%{fullData.name}: %{y:,}<extra></extra>",
            )
        )

    fig = go.Figure(data=data)
    fig.update_layout(
        title=title,
        xaxis_title="Salary Range",
        yaxis_title="Number of Filings",
        height=450,
        template="plotly_white",
        showlegend=True,
        xaxis={"tickangle": -45},
        yaxis={"range": [0, y_max]},
        margin=dict(t=60, b=90, l=60, r=20),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_experience_salary_chart(histogram_data: dict, title: str) -> str:
    """Build salary distribution chart with experience level overlays."""
    bins = histogram_data.get("bins", [])
    overlays = histogram_data.get("overlays", [])
    label = histogram_data.get("label", "All Levels")
    labels = [bin_data["label"] for bin_data in bins]
    counts = [bin_data["count"] for bin_data in bins]

    if not bins:
        fig = go.Figure()
        fig.update_layout(
            title=title,
            xaxis_title="Salary Range",
            yaxis_title="Number of Filings",
            height=400,
            template="plotly_white",
            showlegend=False,
        )
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    max_count = max(counts) if counts else 0
    y_max = max_count * 1.2 if max_count else 1

    data = [
        go.Bar(
            x=labels,
            y=counts,
            name=label,
            opacity=0.35,
            marker_color="rgba(100, 100, 100, 0.45)",
            hovertemplate=f"<b>%{{x}}</b><br>{label}: %{{y:,}}<extra></extra>",
        )
    ]

    for overlay in overlays:
        overlay_counts = overlay.get("counts", [])
        if not overlay_counts:
            continue
        data.append(
            go.Scatter(
                x=labels,
                y=overlay_counts,
                mode="lines+markers",
                name=overlay.get("employer_name", "Experience Level"),
                hovertemplate="<b>%{x}</b><br>%{fullData.name}: %{y:,}<extra></extra>",
            )
        )

    fig = go.Figure(data=data)
    fig.update_layout(
        title=title,
        xaxis_title="Salary Range",
        yaxis_title="Number of Filings",
        height=450,
        template="plotly_white",
        showlegend=True,
        xaxis={"tickangle": -45},
        yaxis={"range": [0, y_max]},
        margin=dict(t=60, b=90, l=60, r=20),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_geographic_chart(geographic_data: list[dict], title: str) -> str:
    """Build geographic distribution chart."""
    if not geographic_data:
        fig = go.Figure()
        fig.add_annotation(
            text="No geographic data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="gray"),
        )
        fig.update_layout(
            title=title,
            xaxis_title="State",
            yaxis_title="Number of Filings",
            height=400,
            template="plotly_white",
            showlegend=False,
            margin=dict(t=60, b=60, l=60, r=20),
        )
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    geographic_data = geographic_data[:15]
    states = [g["worksite_state"] for g in geographic_data]
    counts = [g["count"] for g in geographic_data]
    medians = [
        float(g["median_salary"]) if g.get("median_salary") else 0 for g in geographic_data
    ]
    max_count = max(counts) if counts else 0
    y_max = max_count * 1.15

    fig = go.Figure(
        data=[
            go.Bar(
                x=states,
                y=counts,
                text=[f"{c:,}" for c in counts],
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>Filings: %{y:,}<br>Median Salary: $%{customdata[0]:,.0f}<extra></extra>",
                customdata=[[m] for m in medians],
                marker_color="rgb(55, 83, 109)",
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_title="State",
        yaxis_title="Number of Filings",
        height=400,
        template="plotly_white",
        showlegend=False,
        yaxis={"range": [0, y_max]},
        margin=dict(t=60, b=60, l=60, r=20),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_geographic_median_chart(geographic_data: list[dict], title: str) -> str:
    """Build median salary by state chart."""
    if not geographic_data:
        fig = go.Figure()
        fig.add_annotation(
            text="No geographic data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="gray"),
        )
        fig.update_layout(
            title=title,
            xaxis_title="State",
            yaxis_title="Median Salary ($)",
            height=400,
            template="plotly_white",
            showlegend=False,
            margin=dict(t=60, b=60, l=60, r=20),
        )
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    geographic_data = geographic_data[:15]
    states = [g["worksite_state"] for g in geographic_data]
    medians = [
        float(g["median_salary"]) if g.get("median_salary") else 0 for g in geographic_data
    ]
    counts = [g["count"] for g in geographic_data]
    max_median = max(medians) if medians else 0
    y_max = max_median * 1.15 if max_median else 1

    fig = go.Figure(
        data=[
            go.Bar(
                x=states,
                y=medians,
                text=[f"${m:,.0f}" for m in medians],
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>Median Salary: $%{y:,.0f}<br>Filings: %{customdata[0]:,}<extra></extra>",
                customdata=[[c] for c in counts],
                marker_color="rgb(55, 83, 109)",
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_title="State",
        yaxis_title="Median Salary ($)",
        height=400,
        template="plotly_white",
        showlegend=False,
        yaxis={"range": [0, y_max]},
        margin=dict(t=60, b=60, l=60, r=20),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_filing_volume_chart(yoy_trends: list[dict], title: str) -> str | None:
    """Build year-over-year filing volume chart."""
    if not yoy_trends or len(yoy_trends) < 2:
        return None

    years = [t["fiscal_year"] for t in yoy_trends]
    counts = [t["count"] for t in yoy_trends]
    fig = go.Figure(
        data=[
            go.Scatter(
                x=years,
                y=counts,
                mode="lines+markers",
                line=dict(color="rgb(55, 83, 109)", width=3),
                marker=dict(size=8),
                hovertemplate="<b>FY %{x}</b><br>Filings: %{y:,}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_title="Fiscal Year",
        yaxis_title="Number of Filings",
        height=350,
        template="plotly_white",
        showlegend=False,
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_salary_trend_chart(yoy_trends: list[dict], title: str) -> str | None:
    """Build year-over-year salary trend chart."""
    if not yoy_trends or len(yoy_trends) < 2:
        return None

    years = [t["fiscal_year"] for t in yoy_trends]
    salaries = [float(t["median_salary"]) if t.get("median_salary") else 0 for t in yoy_trends]
    fig = go.Figure(
        data=[
            go.Scatter(
                x=years,
                y=salaries,
                mode="lines+markers",
                line=dict(color="rgb(26, 118, 255)", width=3),
                marker=dict(size=8),
                hovertemplate="<b>FY %{x}</b><br>Median Salary: $%{y:,.0f}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_title="Fiscal Year",
        yaxis_title="Median Salary ($)",
        height=350,
        template="plotly_white",
        showlegend=False,
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
