"""Generate static HTML metric report for VQS model evaluation.

Produces a standalone dashboard showing:
- Series x regime heat map (MAE advantage vs persistence)
- FY boundary vs steady-state comparison table
- Per-series sparklines of cumulative error
- "Where does the model add value?" honest summary

Usage:
    bazel run //scripts/vqs:generate_metric_report
    bazel run //scripts/vqs:generate_metric_report -- --output /tmp/metric_report.html
"""

import argparse
import datetime
import logging
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django.conf import settings

from scripts.vqs.evaluate_model import (
    run_evaluation,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("lib.business.vqs.solver").setLevel(logging.WARNING)
logging.getLogger("lib.business.vqs.aggregator").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def build_heatmap_data(all_stratified: dict, horizon: str) -> dict:
    """Build series x regime heat map data showing MAE advantage over persistence."""
    rows = []
    for series_label in sorted(all_stratified.keys()):
        if horizon not in all_stratified[series_label]:
            continue
        regime_data = all_stratified[series_label][horizon].get("regime", {})
        row = {"series": series_label, "cells": {}}
        for regime_key, model_data in sorted(regime_data.items()):
            persist = model_data.get("Persistence", {})
            vqs = model_data.get("VQS Ensemble", {})
            rs = model_data.get("Regime-Switched", {})
            p_mae = persist.get("mae")
            v_mae = vqs.get("mae")
            r_mae = rs.get("mae")
            count = persist.get("count", 0)

            best_model = "Persistence"
            best_mae = p_mae
            advantage = 0.0
            if v_mae is not None and p_mae is not None and v_mae < p_mae:
                best_model = "VQS Ensemble"
                best_mae = v_mae
                advantage = p_mae - v_mae
            if r_mae is not None and (best_mae is None or r_mae < best_mae):
                best_model = "Regime-Switched"
                advantage = (p_mae or 0) - r_mae
                best_mae = r_mae

            row["cells"][regime_key] = {
                "p_mae": p_mae,
                "best_model": best_model,
                "best_mae": best_mae,
                "advantage": round(advantage, 1),
                "count": count,
            }
        rows.append(row)
    return {"rows": rows}


def build_fy_comparison(all_stratified: dict, horizon: str) -> list[dict]:
    """Build FY boundary vs steady-state comparison across series."""
    result = []
    for series_label in sorted(all_stratified.keys()):
        if horizon not in all_stratified[series_label]:
            continue
        fy_data = all_stratified[series_label][horizon].get("fy_phase", {})

        fy_boundary_phases = {"fy_reset", "end_of_fy"}
        steady_phases = {"conservative", "acceleration", "normal"}

        fy_errors = []
        ss_errors = []
        for phase, model_data in fy_data.items():
            persist = model_data.get("Persistence", {})
            mae = persist.get("mae")
            count = persist.get("count", 0)
            if mae is None:
                continue
            if phase in fy_boundary_phases:
                fy_errors.extend([mae] * count)
            elif phase in steady_phases:
                ss_errors.extend([mae] * count)

        fy_mae = sum(fy_errors) / len(fy_errors) if fy_errors else None
        ss_mae = sum(ss_errors) / len(ss_errors) if ss_errors else None

        fy_vqs_errors = []
        ss_vqs_errors = []
        for phase, model_data in fy_data.items():
            vqs = model_data.get("VQS Ensemble", {})
            mae = vqs.get("mae")
            count = vqs.get("count", 0)
            if mae is None:
                continue
            if phase in fy_boundary_phases:
                fy_vqs_errors.extend([mae] * count)
            elif phase in steady_phases:
                ss_vqs_errors.extend([mae] * count)

        fy_vqs_mae = sum(fy_vqs_errors) / len(fy_vqs_errors) if fy_vqs_errors else None
        ss_vqs_mae = sum(ss_vqs_errors) / len(ss_vqs_errors) if ss_vqs_errors else None

        result.append({
            "series": series_label,
            "fy_persist_mae": round(fy_mae, 1) if fy_mae else None,
            "ss_persist_mae": round(ss_mae, 1) if ss_mae else None,
            "fy_vqs_mae": round(fy_vqs_mae, 1) if fy_vqs_mae else None,
            "ss_vqs_mae": round(ss_vqs_mae, 1) if ss_vqs_mae else None,
            "fy_advantage": round((fy_mae or 0) - (fy_vqs_mae or 0), 1) if fy_mae and fy_vqs_mae else None,
            "ss_advantage": round((ss_mae or 0) - (ss_vqs_mae or 0), 1) if ss_mae and ss_vqs_mae else None,
        })

    return result


def build_value_summary(all_stratified: dict, horizon: str) -> list[str]:
    """Build honest 'where does the model add value' summary bullets."""
    findings = []
    series_with_advantage = []
    series_without = []

    for series_label in sorted(all_stratified.keys()):
        if horizon not in all_stratified[series_label]:
            continue
        regime_data = all_stratified[series_label][horizon].get("regime", {})
        total_advantage = 0.0
        total_count = 0
        for regime_key, model_data in regime_data.items():
            p = model_data.get("Persistence", {})
            v = model_data.get("VQS Ensemble", {})
            p_mae = p.get("mae")
            v_mae = v.get("mae")
            count = p.get("count", 0)
            if p_mae is not None and v_mae is not None and count > 0:
                total_advantage += (p_mae - v_mae) * count
                total_count += count

        avg_advantage = total_advantage / total_count if total_count > 0 else 0
        if avg_advantage > 1.0:
            series_with_advantage.append((series_label, round(avg_advantage, 1)))
        else:
            series_without.append(series_label)

    if series_with_advantage:
        parts = [f"{s} ({a:+.1f}d)" for s, a in sorted(series_with_advantage, key=lambda x: -x[1])]
        findings.append(f"VQS adds value for: {', '.join(parts)}")
    if series_without:
        findings.append(f"VQS is essentially persistence for: {', '.join(series_without)}")

    for series_label in sorted(all_stratified.keys()):
        if horizon not in all_stratified[series_label]:
            continue
        fy_data = all_stratified[series_label][horizon].get("fy_phase", {})
        fy_reset = fy_data.get("fy_reset", {})
        vqs_reset = fy_reset.get("VQS Ensemble", {})
        p_reset = fy_reset.get("Persistence", {})
        if vqs_reset.get("mae") and p_reset.get("mae"):
            adv = p_reset["mae"] - vqs_reset["mae"]
            if adv > 5:
                findings.append(
                    f"{series_label} FY Reset: VQS is {adv:.0f}d better "
                    f"({vqs_reset['mae']:.0f}d vs {p_reset['mae']:.0f}d persistence, N={p_reset.get('count', 0)})"
                )

    if not findings:
        findings.append("Insufficient data to determine model advantage.")

    return findings


def generate_report_html(
    chart_data: dict,
    all_stratified: dict,
    metrics: list,
    horizons: list[int],
    output_path: str,
):
    """Generate the static HTML metric report."""
    horizon = str(horizons[0])

    heatmap = build_heatmap_data(all_stratified, horizon)
    fy_comparison = build_fy_comparison(all_stratified, horizon)
    value_summary = build_value_summary(all_stratified, horizon)

    regime_order = ["advancing", "stalled", "retrogressing", "recovering", "volatile"]
    regime_labels = {
        "advancing": "Advancing", "stalled": "Stalled",
        "retrogressing": "Retrogressing", "recovering": "Recovering",
        "volatile": "Volatile",
    }

    heatmap_rows_html = ""
    for row in heatmap["rows"]:
        heatmap_rows_html += f'<tr><td class="series-label">{row["series"]}</td>'
        for rg in regime_order:
            cell = row["cells"].get(rg)
            if not cell or cell["count"] == 0:
                heatmap_rows_html += '<td class="cell empty">—</td>'
                continue
            adv = cell["advantage"]
            color_class = "win" if adv > 3 else "lose" if adv < -3 else "neutral"
            heatmap_rows_html += (
                f'<td class="cell {color_class}" title="{cell["best_model"]}: {cell["best_mae"]}d MAE (N={cell["count"]})">'
                f'{adv:+.0f}d<br><small>N={cell["count"]}</small></td>'
            )
        heatmap_rows_html += "</tr>"

    regime_headers = "".join(f"<th>{regime_labels.get(r, r)}</th>" for r in regime_order)

    fy_rows_html = ""
    for row in fy_comparison:
        fy_adv = row.get("fy_advantage")
        ss_adv = row.get("ss_advantage")
        fy_class = "win" if fy_adv and fy_adv > 3 else "lose" if fy_adv and fy_adv < -3 else "neutral"
        ss_class = "win" if ss_adv and ss_adv > 3 else "lose" if ss_adv and ss_adv < -3 else "neutral"
        fy_rows_html += (
            f'<tr><td class="series-label">{row["series"]}</td>'
            f'<td>{row.get("fy_persist_mae") or "—"}</td>'
            f'<td>{row.get("fy_vqs_mae") or "—"}</td>'
            f'<td class="{fy_class}">{f"{fy_adv:+.1f}d" if fy_adv else "—"}</td>'
            f'<td>{row.get("ss_persist_mae") or "—"}</td>'
            f'<td>{row.get("ss_vqs_mae") or "—"}</td>'
            f'<td class="{ss_class}">{f"{ss_adv:+.1f}d" if ss_adv else "—"}</td>'
            f"</tr>"
        )

    summary_items = "".join(f"<li>{s}</li>" for s in value_summary)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>VQS Prediction Metric Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px 40px; max-width: 1200px; margin: 0 auto; color: #333; }}
        h1 {{ border-bottom: 2px solid #0d6efd; padding-bottom: 10px; }}
        h2 {{ margin-top: 30px; color: #555; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 14px; }}
        th {{ background: #f0f4f8; padding: 8px 12px; text-align: center; border: 1px solid #dee2e6; font-weight: 600; }}
        td {{ padding: 8px 12px; text-align: center; border: 1px solid #dee2e6; }}
        .series-label {{ text-align: left; font-weight: 500; white-space: nowrap; }}
        .cell {{ min-width: 70px; }}
        .cell small {{ color: #888; font-size: 11px; }}
        .win {{ background: #d4edda; color: #155724; }}
        .lose {{ background: #f8d7da; color: #721c24; }}
        .neutral {{ background: #fff3cd; color: #856404; }}
        .empty {{ background: #f8f9fa; color: #aaa; }}
        .summary {{ background: #e7f1ff; border: 1px solid #b6d4fe; border-radius: 6px; padding: 15px 20px; margin: 15px 0; }}
        .summary ul {{ margin: 5px 0 0 0; padding-left: 20px; }}
        .summary li {{ margin: 5px 0; line-height: 1.5; }}
        .meta {{ color: #666; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <h1>VQS Prediction Metric Report</h1>
    <p class="meta">Generated {datetime.date.today().isoformat()} | Horizon: {horizon}-month | Series: {len(heatmap["rows"])}</p>

    <div class="summary">
        <strong>Where Does the Model Add Value?</strong>
        <ul>{summary_items}</ul>
    </div>

    <h2>Series x Regime Heat Map (VQS advantage over Persistence, days)</h2>
    <p style="font-size:13px;color:#666">Green = VQS better by &gt;3d, Red = VQS worse by &gt;3d, Yellow = within 3d. Hover for details.</p>
    <table>
        <tr><th>Series</th>{regime_headers}</tr>
        {heatmap_rows_html}
    </table>

    <h2>FY Boundary vs Steady-State</h2>
    <p style="font-size:13px;color:#666">Comparing persistence and VQS MAE during FY boundary months (Aug-Oct) vs steady-state (Nov-Jul).</p>
    <table>
        <tr>
            <th rowspan="2">Series</th>
            <th colspan="3">FY Boundary (Aug-Oct)</th>
            <th colspan="3">Steady-State (Nov-Jul)</th>
        </tr>
        <tr>
            <th>Persist</th><th>VQS</th><th>Advantage</th>
            <th>Persist</th><th>VQS</th><th>Advantage</th>
        </tr>
        {fy_rows_html}
    </table>

    <p class="meta">
        Report data: <code>{len(metrics)} metric rows across {len(set(m["series"] for m in metrics))} series x {len(horizons)} horizons</code>
    </p>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    logger.info(f"Metric report saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate VQS Metric Report")
    parser.add_argument("--start", type=str, default="2016-01-01")
    parser.add_argument("--end", type=str, default="2026-03-01")
    parser.add_argument("--series", type=str, default=None)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--horizons", type=str, default="1,3,6")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    step = 3 if args.quick else 1
    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    output_path = args.output or os.path.join(
        getattr(settings, "WORKSPACE_DIR", settings.BASE_DIR),
        "webapp",
        "templates",
        "metric_report.html",
    )

    chart_data, metrics, stratified = run_evaluation(
        start, end, horizons, series_filter=args.series, step=step,
    )
    generate_report_html(chart_data, stratified, metrics, horizons, output_path)
    logger.info("Done. View at http://localhost:8000/metric-report/")


if __name__ == "__main__":
    main()
