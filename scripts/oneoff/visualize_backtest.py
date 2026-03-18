import datetime
import os

import django
from dateutil.relativedelta import relativedelta
from django.conf import settings

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.vqs.solver import predict_next_bulletin_and_maturity
from models.enums.country import Country
from models.raw_facts import RawFactsLedger
from models.visa_cutoff_date import VisaCutoffDate

# Artifact Directory
ARTIFACT_DIR = (
    "/Users/vyakunin/.gemini/antigravity/brain/fe663a4c-c9d2-4347-b11c-7b9414a10399"
)


def get_actual_history(visa_class, country, action_type):
    """
    Get the full history of actual cutoffs.
    Returns dict: {date: cutoff_date}
    """
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class, country=country, action_type=action_type
    ).order_by("bulletin__publication_date")

    data = {}
    for h in history:
        if h.cutoff_date:
            data[h.bulletin.publication_date] = h.cutoff_date
    return data


def generate_dashboard_forecast_at_horizon(
    visa_class, country, action_type, target_date, months_prior
):
    """
    Simulate what the Dashboard model predicted for `target_date`
    when the prediction was made `months_prior` months ago.
    """
    simulation_date = target_date - relativedelta(months=months_prior)

    # Dashboard logic: 12-month moving average of progress
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        bulletin__publication_date__lte=simulation_date,
    ).order_by("bulletin__publication_date")

    recent_points = []
    # Get last 12 months history relative to simulation_date
    cutoff_12m_ago = simulation_date - datetime.timedelta(days=366)

    for h in history:
        if h.cutoff_date and h.bulletin.publication_date > cutoff_12m_ago:
            recent_points.append((h.bulletin.publication_date, h.cutoff_date))

    if len(recent_points) < 2:
        # Fallback: Naive (Last Value)
        if history.exists():
            last = history.last()
            return last.cutoff_date if last.cutoff_date else None
        return None

    first_date, first_val = recent_points[0]
    last_date, last_val = recent_points[-1]

    months_diff = (last_date.year - first_date.year) * 12 + (
        last_date.month - first_date.month
    )
    if months_diff < 1:
        months_diff = 1

    rate_days_per_month = (last_val - first_val).days / months_diff

    # If rate <= 0, Dashboard falls back to Linear Regression (24m or all history)
    # For simplicity here, let's assume Naive fallback if rate <= 0,
    # as our previous analysis showed Naive beats Linear anyway.
    # But strictly, the Dashboard uses historical regression.
    # Let's use Naive (Last Value) for rate <= 0 to represent a "Conservative Trend".
    if rate_days_per_month <= 0:
        return last_val

    # Project forward
    months_to_project = months_prior
    days_to_add = rate_days_per_month * months_to_project

    predicted_date = last_val + datetime.timedelta(days=days_to_add)
    return predicted_date


def generate_vqs_forecast_at_horizon(
    visa_class, country, action_type, target_date, months_prior
):
    """
    Run VQS Soler to predict `target_date` from `months_prior` ago.
    """
    simulation_date = target_date - relativedelta(months=months_prior)

    # VQS requires RawFactsLedger
    if not RawFactsLedger.objects.exists():
        return None

    try:
        # The VQS solver returns specific step results.
        # We need to run it starting from simulation_date until target_date
        # predict_next_bulletin_and_maturity runs a loop.

        # We need to simulate the loop for `months_prior` steps.
        # But `predict_next_bulletin_and_maturity` returns the *next* bulletin (1 month out).
        # We need the full `results` list to find the prediction for `target_date`.

        # However, `predict_next_bulletin_and_maturity` might be heavy to run for every point.
        # Let's try to run it.

        # Note: solver expects visa_class like "2nd", country int, action "filing"

        # VQS typically targets "final_action". Does it support "filing"?
        # The code checks `action_type` in `get_historical_advancement_rate`, so yes.
        # But `predict_next_bulletin_and_maturity` doesn't explicitly block it.

        # We need to capture the prediction for `target_date`.
        # The `results` list contains SolverResult(month=..., cutoff=...).
        # We want the result where result.month == target_date.

        outcome = predict_next_bulletin_and_maturity(
            knowledge_date=simulation_date,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            force_physics=False,
        )
        next_cutoff = outcome.predicted_cutoff
        results = outcome.results

        for res in results:
            # Solver results are usually the 1st of the month
            if (
                res.month.year == target_date.year
                and res.month.month == target_date.month
            ):
                return res.cutoff_date

        # If target date beyond max_months (usually 120), return last
        if results:
            return results[-1].cutoff_date

        return next_cutoff

    except Exception as e:
        print(f"VQS Error at {simulation_date}: {e}")
        return None


import json
import logging

# Configure logging to suppress noisy VQS DEBUG logs
logging.basicConfig(level=logging.INFO)
# VQS logger is 'lib.business.vqs.solver', set it to WARNING
logging.getLogger("lib.business.vqs.solver").setLevel(logging.WARNING)
logging.getLogger("lib.business.vqs.aggregator").setLevel(logging.WARNING)


def generate_static_forecast_at_horizon(
    visa_class, country, action_type, target_date, months_prior
):
    """
    Static (Persistence) Forecast.
    Predicts that there will be NO CHANGE from the knowledge date.
    Prediction = Cutoff at (target_date - months_prior).
    """
    knowledge_date = target_date - relativedelta(months=months_prior)

    # We need the cutoff that was active ON knowledge_date.
    # We can query the DB or just use our pre-fetched history if we passed it in,
    # but querying is safer to handle "active" logic (most recent bulletin).

    # Find the bulletin that would be active/published by knowledge_date
    # Bulletins are published ~15th of prior month, effective 1st of month.
    # If knowledge_date is 2024-01-01, we know the Jan bulletin.

    # Simple approach: Find latest tuple in history <= knowledge_date
    # Since we don't have the full history object here, let's just query.

    latest = (
        VisaCutoffDate.objects.filter(
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            bulletin__publication_date__lte=knowledge_date,
        )
        .order_by("-bulletin__publication_date")
        .first()
    )

    if latest and latest.cutoff_date:
        return latest.cutoff_date
    return None


def run_lagged_chart_multi_series():
    print("--- Generating Multi-Series Lagged Forecast Chart (Plotly) ---")

    # ... (VQS check skipped for brevity in diff, assume unchanged) ...
    # Check VQS Data Availability
    earliest_fact = None
    if RawFactsLedger.objects.exists():
        earliest_fact = (
            RawFactsLedger.objects.order_by("publication_date").first().publication_date
        )
        print(f"VQS Data available from: {earliest_fact}")
    else:
        print(
            "WARNING: No RawFactsLedger data found. VQS will yield flat lines (persistence)."
        )

    SERIES_TO_ANALYZE = [  # noqa: N806
        (Country.INDIA.value, "2nd", "India EB-2 (Filing)"),
        (Country.INDIA.value, "3rd", "India EB-3 (Filing)"),
        (Country.CHINA.value, "2nd", "China EB-2 (Filing)"),
        (Country.CHINA.value, "3rd", "China EB-3 (Filing)"),
        (Country.CHINA.value, "1st", "China EB-1 (Filing)"),
        (Country.INDIA.value, "1st", "India EB-1 (Filing)"),
    ]

    action_type = "filing"

    START_PLOT = datetime.date(2016, 1, 1)  # noqa: N806
    END_PLOT = datetime.date(2025, 2, 1)  # noqa: N806

    # Master data structure for JSON
    chart_data = {}

    for country, visa_class, label in SERIES_TO_ANALYZE:
        print(f"Processing {label}...")

        # 1. Get Truth
        true_data = get_actual_history(visa_class, country, action_type)
        sorted_dates = sorted(true_data.keys())

        # Filter dates
        plot_dates = [d for d in sorted_dates if START_PLOT <= d <= END_PLOT]

        # Lists for this series
        dates_str = [d.strftime("%Y-%m-%d") for d in plot_dates]
        actual_vals = []
        dash6_vals = []
        vqs6_vals = []
        static6_vals = []  # Replaced Linear with Static

        for d in plot_dates:
            # Actual
            actual = true_data.get(d)
            actual_vals.append(actual.strftime("%Y-%m-%d") if actual else None)

            # Dashboard
            p = generate_dashboard_forecast_at_horizon(
                visa_class, country, action_type, d, 6
            )
            dash6_vals.append(p.strftime("%Y-%m-%d") if p else None)

            # VQS
            p = generate_vqs_forecast_at_horizon(visa_class, country, action_type, d, 6)
            vqs6_vals.append(p.strftime("%Y-%m-%d") if p else None)

            # Static (Persistence)
            p = generate_static_forecast_at_horizon(
                visa_class, country, action_type, d, 6
            )
            static6_vals.append(p.strftime("%Y-%m-%d") if p else None)

        chart_data[label] = {
            "dates": dates_str,
            "actual": actual_vals,
            "dash6": dash6_vals,
            "vqs6": vqs6_vals,
            "static6": static6_vals,
            "vqs_start": earliest_fact.strftime("%Y-%m-%d") if earliest_fact else "N/A",
        }

    # 2. Construction of Client-Side Chart (HTML with JS)
    json_data = json.dumps(chart_data)
    default_series = "India EB-2 (Filing)"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Visa Bulletin Backtest</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{ font-family: sans-serif; padding: 20px; }}
            .controls {{ margin-bottom: 20px; }}
            select {{ padding: 8px; font-size: 16px; }}
            .note {{ color: #666; font-style: italic; margin-top: 10px; }}
            .stats {{
                margin-top: 15px;
                padding: 10px;
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                display: flex;
                gap: 20px;
                font-weight: bold;
            }}
            .stat-item {{ color: #333; }}
        </style>
    </head>
    <body>
        <div class="controls">
            <label for="seriesSelect">Select Visa Category:</label>
            <select id="seriesSelect" onchange="updateChart()">
                {"".join([f'<option value="{k}">{k}</option>' for k in chart_data.keys()])}
            </select>
            <div class="note" id="dataNote"></div>
            <div id="statsBox" class="stats"></div>
        </div>

        <div id="chart" style="width:100%;height:900px;"></div>

        <script>
            const chartData = {json_data};
            // 18 months after Jan 2016 = July 2017
            const ERROR_START_DATE = new Date("2017-07-01");

            function calculateCumulativeError(dates, actuals, preds) {{
                let cumulative = [];
                let sum = 0;
                for (let i = 0; i < dates.length; i++) {{
                    let dDate = new Date(dates[i]);

                    // Only start accumulating error after start date
                    if (dDate >= ERROR_START_DATE && actuals[i] && preds[i]) {{
                        let d1 = new Date(actuals[i]);
                        let d2 = new Date(preds[i]);
                        let diffTime = Math.abs(d2 - d1);
                        let diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
                        sum += diffDays;
                    }}
                    cumulative.push(sum);
                }}
                return cumulative;
            }}

            function updateChart() {{
                const selected = document.getElementById('seriesSelect').value;
                const data = chartData[selected];

                document.getElementById('dataNote').innerText =
                    "VQS Data Available From: " + data.vqs_start + ". Accumulating error from July 2017 (18m after start).";

                // Calculate Errors
                const errDash = calculateCumulativeError(data.dates, data.actual, data.dash6);
                const errVqs = calculateCumulativeError(data.dates, data.actual, data.vqs6);
                const errStatic = calculateCumulativeError(data.dates, data.actual, data.static6);

                // Update Stats Box
                const totalDash = errDash[errDash.length - 1] || 0;
                const totalVqs = errVqs[errVqs.length - 1] || 0;
                const totalStatic = errStatic[errStatic.length - 1] || 0;

                document.getElementById('statsBox').innerHTML = `
                    <span class="stat-item" style="color: blue">Dashboard Error: ${{totalDash.toLocaleString()}} days</span>
                    <span class="stat-item" style="color: purple">VQS Error: ${{totalVqs.toLocaleString()}} days</span>
                    <span class="stat-item" style="color: green">Static Error: ${{totalStatic.toLocaleString()}} days</span>
                `;

                // --- Top Chart: Forecasts ---
                const traceActual = {{
                    x: data.dates,
                    y: data.actual,
                    mode: 'lines+markers',
                    name: 'Actual History',
                    line: {{color: 'black', width: 4}},
                    marker: {{size: 6, color: 'black'}},
                    legendgroup: 'actual'
                }};

                const traceDash6 = {{
                    x: data.dates,
                    y: data.dash6,
                    mode: 'lines',
                    name: 'Dashboard Trend (6m)',
                    line: {{color: 'blue', width: 2, dash: 'dash'}},
                    legendgroup: 'dashboard'
                }};

                const traceVqs6 = {{
                    x: data.dates,
                    y: data.vqs6,
                    mode: 'lines',
                    name: 'VQS Model (6m)',
                    line: {{color: 'purple', width: 3}},
                    legendgroup: 'vqs'
                }};

                const traceStatic6 = {{
                    x: data.dates,
                    y: data.static6,
                    mode: 'lines',
                    name: 'Static Model (6m)',
                    line: {{color: 'green', width: 1, dash: 'dot'}},
                    legendgroup: 'static'
                }};

                // --- Bottom Chart: Cumulative Error ---
                // Linked via legendgroup, but showlegend=false to avoid duplication
                const traceErrDash = {{
                    x: data.dates,
                    y: errDash,
                    mode: 'lines',
                    name: 'Cumul. Error: Trend',
                    line: {{color: 'blue', width: 2, dash: 'dash'}},
                    xaxis: 'x',
                    yaxis: 'y2',
                    legendgroup: 'dashboard',
                    showlegend: false
                }};

                const traceErrVqs = {{
                    x: data.dates,
                    y: errVqs,
                    mode: 'lines',
                    name: 'Cumul. Error: VQS',
                    line: {{color: 'purple', width: 2}},
                    xaxis: 'x',
                    yaxis: 'y2',
                    legendgroup: 'vqs',
                    showlegend: false
                }};

                const traceErrStatic = {{
                    x: data.dates,
                    y: errStatic,
                    mode: 'lines',
                    name: 'Cumul. Error: Static',
                    line: {{color: 'green', width: 1, dash: 'dot'}},
                    xaxis: 'x',
                    yaxis: 'y2',
                    legendgroup: 'static',
                    showlegend: false
                }};

                const layout = {{
                    title: 'Forecast Accuracy & Cost of Optimism: ' + selected,
                    grid: {{rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom'}},
                    xaxis: {{title: 'Target Bulletin Date'}},
                    yaxis: {{title: 'Cutoff Date', domain: [0.55, 1]}},
                    yaxis2: {{title: 'Cumulative Error (Days) [Since July 2017]', domain: [0, 0.45]}},
                    template: 'plotly_white',
                    hovermode: 'x unified',
                    height: 900,
                    legend: {{tracegroupgap: 0}}
                }};

                Plotly.newPlot('chart', [
                    traceActual, traceDash6, traceVqs6, traceStatic6,
                    traceErrDash, traceErrVqs, traceErrStatic
                ], layout);
            }}

            // Initial Load
            document.getElementById('seriesSelect').value = "{default_series}";
            updateChart();
        </script>
    </body>
    </html>
    """

    # Save to Webapp Template
    webapp_template_path = os.path.join(
        settings.BASE_DIR, "webapp", "templates", "spaghetti.html"
    )
    with open(webapp_template_path, "w") as f:
        f.write(html_content)
    print(f"Chart saved to webapp: {webapp_template_path}")

    # Also save to artifact
    if os.path.exists(ARTIFACT_DIR):
        artifact_path = os.path.join(ARTIFACT_DIR, "spaghetti_backtest.html")
        with open(artifact_path, "w") as f:
            f.write(html_content)


if __name__ == "__main__":
    run_lagged_chart_multi_series()
