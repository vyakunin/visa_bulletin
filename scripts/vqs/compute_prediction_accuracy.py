#!/usr/bin/env python3
"""
Compute VQS prediction accuracy metrics and optionally plot.

Metric 1 – Bulletin-by-bulletin: For each bulletin, predict every cutoff
as-of day-before-publication; compare to actual; plot average error over
bulletin date. Drill down by visa_class and country.

Metric 2 – Long-term "final ready date": For each month and (visa_class,
country), predict when next cutoff will appear; compare to first bulletin
where that cutoff was reached; plot average error over time.

Usage:
  bazel run //scripts/vqs:compute_prediction_accuracy -- --metric bulletin --plot --output-dir /tmp/vqs_accuracy
  bazel run //scripts/vqs:compute_prediction_accuracy -- --metric both --filter-visa-class 2nd --filter-country 3
"""

import argparse
import json
import logging
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django
django.setup()

from django_config.logging_config import setup_logging
from lib.business.vqs.accuracy_metrics import (
    BulletinAccuracyRow,
    LongtermAccuracyRow,
    compute_bulletin_accuracy,
    compute_longterm_accuracy,
    aggregate_bulletin_errors_by_date,
    aggregate_longterm_errors_by_month,
    aggregate_longterm_by_horizon_and_series,
)
from lib.utils.logging_utils import ScriptLogger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def _serialize_row(r: BulletinAccuracyRow | LongtermAccuracyRow) -> dict:
    d = asdict(r)
    for k, v in d.items():
        if isinstance(v, date):
            d[k] = v.isoformat()
    return d


def _build_bulletin_plot(
    rows: list[BulletinAccuracyRow],
    filter_visa_class: str | None,
    filter_country: int | None,
) -> "plotly.graph_objects.Figure":
    import plotly.graph_objects as go

    agg = aggregate_bulletin_errors_by_date(
        rows,
        filter_visa_class=filter_visa_class,
        filter_country=filter_country,
    )
    if not agg:
        fig = go.Figure()
        fig.add_annotation(text="No data (try without filters)", x=0.5, y=0.5, showarrow=False)
        return fig
    dates = [d.isoformat() for d, _, _ in agg]
    mean_errors = [e for _, e, _ in agg]
    counts = [n for _, _, n in agg]
    label = "All"
    if filter_visa_class:
        label = f"{filter_visa_class}"
    if filter_country is not None:
        label = f"{label} country={filter_country}"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=mean_errors,
            mode="lines+markers",
            name=label,
            text=[f"n={n}" for n in counts],
            hovertemplate="%{x}<br>Mean error: %{y:.0f} days<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Bulletin-by-bulletin prediction accuracy (mean error vs bulletin date)",
        xaxis_title="Bulletin publication date",
        yaxis_title="Mean absolute error (days)",
        template="plotly_white",
        height=500,
    )
    return fig


def _build_bulletin_plot_with_drilldown(rows: list[BulletinAccuracyRow]) -> "plotly.graph_objects.Figure":
    import plotly.graph_objects as go

    from models.enums.country import Country

    fig = go.Figure()
    seen = set()
    for r in rows:
        key = (r.visa_class, r.country)
        if key in seen:
            continue
        seen.add(key)
        agg = aggregate_bulletin_errors_by_date(
            rows,
            filter_visa_class=r.visa_class,
            filter_country=r.country,
        )
        if not agg:
            continue
        dates = [d.isoformat() for d, _, _ in agg]
        mean_errors = [e for _, e, _ in agg]
        try:
            country_label = Country(r.country).label if r.country else "All"
        except ValueError:
            country_label = str(r.country)
        name = f"{r.visa_class} – {country_label}"
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=mean_errors,
                mode="lines+markers",
                name=name,
                visible=True,
            )
        )
    if not fig.data:
        fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
    else:
        fig.update_layout(
            title="Bulletin accuracy by visa class and country (toggle legend to drill down)",
            xaxis_title="Bulletin publication date",
            yaxis_title="Mean absolute error (days)",
            template="plotly_white",
            height=500,
            showlegend=True,
        )
    return fig


def _build_longterm_plot(
    rows: list[LongtermAccuracyRow],
    filter_visa_class: str | None,
    filter_country: int | None,
) -> "plotly.graph_objects.Figure":
    import plotly.graph_objects as go

    agg = aggregate_longterm_errors_by_month(
        rows,
        filter_visa_class=filter_visa_class,
        filter_country=filter_country,
    )
    if not agg:
        fig = go.Figure()
        fig.add_annotation(text="No data (try without filters)", x=0.5, y=0.5, showarrow=False)
        return fig
    months = [m.isoformat() for m, _, _ in agg]
    mean_errors = [e for _, e, _ in agg]
    counts = [n for _, _, n in agg]
    label = "All"
    if filter_visa_class:
        label = f"{filter_visa_class}"
    if filter_country is not None:
        label = f"{label} country={filter_country}"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=months,
            y=mean_errors,
            mode="lines+markers",
            name=label,
            text=[f"n={n}" for n in counts],
            hovertemplate="%{x}<br>Mean error: %{y:.0f} days<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Long-term 'final ready date' prediction accuracy (mean error vs knowledge month)",
        xaxis_title="Knowledge month",
        yaxis_title="Mean absolute error (days)",
        template="plotly_white",
        height=500,
    )
    return fig


def _build_longterm_plot_with_drilldown(rows: list[LongtermAccuracyRow]) -> "plotly.graph_objects.Figure":
    import plotly.graph_objects as go

    from models.enums.country import Country

    fig = go.Figure()
    seen = set()
    for r in rows:
        key = (r.visa_class, r.country)
        if key in seen:
            continue
        seen.add(key)
        agg = aggregate_longterm_errors_by_month(
            rows,
            filter_visa_class=r.visa_class,
            filter_country=r.country,
        )
        if not agg:
            continue
        months = [m.isoformat() for m, _, _ in agg]
        mean_errors = [e for _, e, _ in agg]
        try:
            country_label = Country(r.country).label if r.country else "All"
        except ValueError:
            country_label = str(r.country)
        name = f"{r.visa_class} – {country_label}"
        fig.add_trace(
            go.Scatter(
                x=months,
                y=mean_errors,
                mode="lines+markers",
                name=name,
                visible=True,
            )
        )
    if not fig.data:
        fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
    else:
        fig.update_layout(
            title="Long-term accuracy by visa class and country (toggle legend to drill down)",
            xaxis_title="Knowledge month",
            yaxis_title="Mean absolute error (days)",
            template="plotly_white",
            height=500,
            showlegend=True,
        )
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute VQS prediction accuracy (bulletin and/or long-term) and optionally plot"
    )
    parser.add_argument(
        "--metric",
        choices=["bulletin", "longterm", "both"],
        default="both",
        help="Which metric to compute (default: both)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for JSON/CSV and HTML plots (default: current dir)",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate Plotly HTML plots (with drill-down by visa class and country)",
    )
    parser.add_argument(
        "--filter-visa-class",
        type=str,
        default=None,
        help="Drill down: only this visa class (e.g. 2nd, 3rd)",
    )
    parser.add_argument(
        "--filter-country",
        type=int,
        default=None,
        help="Drill down: only this country enum value (e.g. 3 for India)",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "csv"],
        default="json",
        help="Format for raw rows (default: json)",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default=None,
        help="Directory for intermediate checkpoints (enables resume on restart)",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={
            "metric": args.metric,
            "output_dir": args.output_dir,
            "plot": args.plot,
            "filter_visa_class": args.filter_visa_class,
            "filter_country": args.filter_country,
        },
        context="VQS prediction accuracy",
    )

    out_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    ckpt_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else None
    if ckpt_dir:
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Checkpointing enabled: %s", ckpt_dir)

    if args.metric in ("bulletin", "both"):
        logger.info("Computing bulletin-by-bulletin accuracy...")
        bulletin_rows = compute_bulletin_accuracy(checkpoint_dir=ckpt_dir)
        logger.info("Bulletin accuracy: %d rows", len(bulletin_rows))
        raw = [_serialize_row(r) for r in bulletin_rows]
        if args.output_format == "json":
            (out_dir / "bulletin_accuracy.json").write_text(
                json.dumps(raw, indent=2), encoding="utf-8"
            )
        else:
            import csv
            if raw:
                with open(
                    out_dir / "bulletin_accuracy.csv", "w", newline="", encoding="utf-8"
                ) as f:
                    w = csv.DictWriter(f, fieldnames=raw[0].keys())
                    w.writeheader()
                    w.writerows(raw)
        if args.plot:
            fig = _build_bulletin_plot_with_drilldown(bulletin_rows)
            fig.write_html(str(out_dir / "bulletin_accuracy_plot.html"))
            logger.info("Wrote %s", out_dir / "bulletin_accuracy_plot.html")
            if args.filter_visa_class or args.filter_country is not None:
                fig2 = _build_bulletin_plot(
                    bulletin_rows,
                    filter_visa_class=args.filter_visa_class,
                    filter_country=args.filter_country,
                )
                fig2.write_html(str(out_dir / "bulletin_accuracy_plot_filtered.html"))

    if args.metric in ("longterm", "both"):
        logger.info("Computing long-term 'final ready date' accuracy...")
        longterm_rows = compute_longterm_accuracy(checkpoint_dir=ckpt_dir)
        logger.info("Long-term accuracy: %d rows", len(longterm_rows))
        raw = [_serialize_row(r) for r in longterm_rows]
        if args.output_format == "json":
            (out_dir / "longterm_accuracy.json").write_text(
                json.dumps(raw, indent=2), encoding="utf-8"
            )
        else:
            import csv
            if raw:
                with open(
                    out_dir / "longterm_accuracy.csv", "w", newline="", encoding="utf-8"
                ) as f:
                    w = csv.DictWriter(f, fieldnames=raw[0].keys())
                    w.writeheader()
                    w.writerows(raw)
        summary = aggregate_longterm_by_horizon_and_series(longterm_rows)
        (out_dir / "longterm_accuracy_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        logger.info("Wrote %s", out_dir / "longterm_accuracy_summary.json")
        if args.plot:
            fig = _build_longterm_plot_with_drilldown(longterm_rows)
            fig.write_html(str(out_dir / "longterm_accuracy_plot.html"))
            logger.info("Wrote %s", out_dir / "longterm_accuracy_plot.html")
            if args.filter_visa_class or args.filter_country is not None:
                fig2 = _build_longterm_plot(
                    longterm_rows,
                    filter_visa_class=args.filter_visa_class,
                    filter_country=args.filter_country,
                )
                fig2.write_html(str(out_dir / "longterm_accuracy_plot_filtered.html"))

    logger.info("Done. Output dir: %s", out_dir)


if __name__ == "__main__":
    main()
