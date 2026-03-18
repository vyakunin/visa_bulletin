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
    aggregate_bulletin_errors_by_date,
    aggregate_longterm_by_horizon_and_series,
    aggregate_longterm_errors_by_month,
    compare_to_no_change_baseline,
    compute_bulletin_accuracy,
    compute_composite_metric,
    compute_longterm_accuracy,
    compute_multi_horizon_accuracy,
)
from lib.business.vqs.metric_config import MetricConfig, PeriodDiscount
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
) -> "plotly.graph_objects.Figure":  # noqa: F821
    import plotly.graph_objects as go

    agg = aggregate_bulletin_errors_by_date(
        rows,
        filter_visa_class=filter_visa_class,
        filter_country=filter_country,
    )
    if not agg:
        fig = go.Figure()
        fig.add_annotation(
            text="No data (try without filters)", x=0.5, y=0.5, showarrow=False
        )
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


def _build_bulletin_plot_with_drilldown(
    rows: list[BulletinAccuracyRow],
) -> "plotly.graph_objects.Figure":  # noqa: F821
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
) -> "plotly.graph_objects.Figure":  # noqa: F821
    import plotly.graph_objects as go

    agg = aggregate_longterm_errors_by_month(
        rows,
        filter_visa_class=filter_visa_class,
        filter_country=filter_country,
    )
    if not agg:
        fig = go.Figure()
        fig.add_annotation(
            text="No data (try without filters)", x=0.5, y=0.5, showarrow=False
        )
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


def _build_longterm_plot_with_drilldown(
    rows: list[LongtermAccuracyRow],
) -> "plotly.graph_objects.Figure":  # noqa: F821
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
        choices=["bulletin", "longterm", "composite", "both", "all"],
        default="both",
        help="Which metric to compute. 'composite' adds multi-horizon evaluation. "
        "'all' runs bulletin + longterm + composite. (default: both = bulletin + longterm)",
    )
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 3, 6, 12],
        help="Prediction horizons in months for composite metric (default: 1 3 6 12)",
    )
    parser.add_argument(
        "--discount-2023",
        type=float,
        default=0.2,
        help="Period weight for 2023 in composite metric (0.0=exclude, 1.0=full; default: 0.2)",
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
    parser.add_argument(
        "--warmup-single-horizon",
        action="store_true",
        help="Force aggregator warmup to use h=1 only (for comparison with multi-horizon warmup)",
    )
    parser.add_argument(
        "--use-huber-loss",
        action="store_true",
        help="Use Huber loss instead of squared error in aggregator weight updates",
    )
    parser.add_argument(
        "--trend-weight",
        type=float,
        default=0.0,
        help="Blend direction accuracy into composite metric (0=pure MAE, 1=pure direction; default: 0.0)",
    )
    parser.add_argument(
        "--use-predictability-weight",
        action="store_true",
        help="Weight data points by I-140 coverage and volatility (focus metric on predictable series)",
    )
    parser.add_argument(
        "--dump-weights",
        action="store_true",
        help="Dump expert weights per series after evaluation (for comparing warmup strategies)",
    )
    parser.add_argument(
        "--action-type",
        type=str,
        default=None,
        choices=["final_action", "filing"],
        help="Only evaluate this action type (default: all)",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=0.5,
        help="Hedge algorithm learning rate for expert weight updates (default: 0.5)",
    )
    parser.add_argument(
        "--ensemble-trajectory-blend", type=float, default=None,
        help="Weight of ensemble vs physics at each step (0=pure physics, 1=full ensemble)",
    )
    parser.add_argument(
        "--ensemble-trajectory-decay", type=float, default=None,
        help="Decay factor for ensemble influence at later horizons",
    )
    parser.add_argument(
        "--ensemble-stickiness-days", type=int, default=None,
        help="Stickiness threshold for ensemble-mode post-step shaping",
    )
    parser.add_argument(
        "--ensemble-cap-forward-days", type=int, default=None,
        help="Forward cap for ensemble-mode post-step shaping",
    )
    parser.add_argument(
        "--stickiness-days", type=int, default=None,
        help="Override VqsMetaParams.stickiness_days",
    )
    parser.add_argument(
        "--cap-forward-days", type=int, default=None,
        help="Override VqsMetaParams.cap_forward_days",
    )
    parser.add_argument(
        "--blend-lambda", type=float, default=None,
        help="Override VqsMetaParams.blend_lambda",
    )
    parser.add_argument(
        "--ensemble-persistence-weight", type=float, default=None,
        help="Override VqsMetaParams.ensemble_persistence_weight",
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

        # Baseline comparison
        baseline_all = compare_to_no_change_baseline(bulletin_rows, exclude_eb4=True, recent_only=False)
        baseline_recent = compare_to_no_change_baseline(bulletin_rows, exclude_eb4=True, recent_only=True)
        logger.info(
            "Baseline comparison (all excl EB4): model=%.1fd vs baseline=%.1fd | wins=%d/%d (%.1f%%) | beats=%s",
            baseline_all.get("model_mean_error") or 0, baseline_all.get("baseline_mean_error") or 0,
            baseline_all["model_wins"], baseline_all["total"], baseline_all.get("model_win_pct") or 0,
            baseline_all["beats_baseline"],
        )
        logger.info(
            "Baseline comparison (recent excl EB4): model=%.1fd vs baseline=%.1fd | wins=%d/%d (%.1f%%) | beats=%s",
            baseline_recent.get("model_mean_error") or 0, baseline_recent.get("baseline_mean_error") or 0,
            baseline_recent["model_wins"], baseline_recent["total"], baseline_recent.get("model_win_pct") or 0,
            baseline_recent["beats_baseline"],
        )
        (out_dir / "baseline_comparison.json").write_text(
            json.dumps({"all_excl_eb4": baseline_all, "recent_excl_eb4": baseline_recent}, indent=2),
            encoding="utf-8",
        )

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

    if args.metric in ("composite", "all"):
        logger.info("Computing multi-horizon composite accuracy (horizons=%s)...", args.horizons)

        period_discounts = []
        if args.discount_2023 < 1.0:
            period_discounts.append(
                PeriodDiscount(date(2023, 1, 1), date(2023, 12, 31), args.discount_2023)
            )

        eval_horizon_weights = {
            h: w for h, w in zip(args.horizons, _default_horizon_weights(args.horizons))
        }

        if args.warmup_single_horizon:
            warmup_horizon_weights = {1: 1.0}
            logger.info("Warmup: single-horizon (h=1 only)")
        else:
            warmup_horizon_weights = eval_horizon_weights
            logger.info("Warmup: multi-horizon %s", warmup_horizon_weights)

        warmup_cfg = MetricConfig(
            horizon_weights=warmup_horizon_weights,
            period_discounts=period_discounts,
            use_huber_loss=args.use_huber_loss,
            trend_weight=args.trend_weight,
        )

        eval_cfg = MetricConfig(
            horizon_weights=eval_horizon_weights,
            period_discounts=period_discounts,
            use_huber_loss=args.use_huber_loss,
            trend_weight=args.trend_weight,
        )

        # Build VqsMetaParams with any CLI overrides
        from dataclasses import replace as dc_replace

        from lib.business.vqs.meta_params import VqsMetaParams

        meta = VqsMetaParams.defaults()
        meta_overrides = {}
        if args.ensemble_trajectory_blend is not None:
            meta_overrides["ensemble_trajectory_blend"] = args.ensemble_trajectory_blend
        if args.ensemble_trajectory_decay is not None:
            meta_overrides["ensemble_trajectory_decay"] = args.ensemble_trajectory_decay
        if args.ensemble_stickiness_days is not None:
            meta_overrides["ensemble_stickiness_days"] = args.ensemble_stickiness_days
        if args.ensemble_cap_forward_days is not None:
            meta_overrides["ensemble_cap_forward_days"] = args.ensemble_cap_forward_days
        if args.stickiness_days is not None:
            meta_overrides["stickiness_days"] = args.stickiness_days
        if args.cap_forward_days is not None:
            meta_overrides["cap_forward_days"] = args.cap_forward_days
        if args.blend_lambda is not None:
            meta_overrides["blend_lambda"] = args.blend_lambda
        if args.ensemble_persistence_weight is not None:
            meta_overrides["ensemble_persistence_weight"] = args.ensemble_persistence_weight
        if meta_overrides:
            meta = dc_replace(meta, **meta_overrides)
            logger.info("VqsMetaParams overrides: %s", meta_overrides)

        from lib.business.vqs.aggregator import ExpertAggregator

        shared_aggregator = ExpertAggregator(
            metric_config=warmup_cfg,
            learning_rate=args.learning_rate,
        )

        mh_rows = compute_multi_horizon_accuracy(
            horizons=args.horizons,
            exclude_eb4=True,
            action_type=args.action_type,
            metric_config=warmup_cfg,
            aggregator=shared_aggregator,
            meta=meta,
        )
        logger.info("Multi-horizon rows: %d", len(mh_rows))

        composite = compute_composite_metric(
            mh_rows, config=eval_cfg,
            use_predictability_weight=args.use_predictability_weight,
        )
        logger.info(
            "Composite MAE: %.1f days | Trend accuracy: %.1f%% | Blended: %.1f",
            composite["composite_mae"],
            composite["overall_trend_accuracy"] * 100,
            composite["blended_metric"],
        )
        for h, stats in composite["per_horizon"].items():
            trend_info = composite["trend_by_horizon"].get(h, {})
            dir_acc = trend_info.get("direction_accuracy", 0) * 100
            logger.info(
                "  h=%d: MAE=%.1f days (n=%d) | direction=%.1f%%",
                h, stats["mae"], stats["count"], dir_acc,
            )

        (out_dir / "composite_metric.json").write_text(
            json.dumps(composite, indent=2, default=str), encoding="utf-8"
        )
        logger.info("Wrote %s", out_dir / "composite_metric.json")

        raw_mh = [_serialize_row(r) for r in mh_rows]
        (out_dir / "multi_horizon_rows.json").write_text(
            json.dumps(raw_mh, indent=2), encoding="utf-8"
        )

        if args.dump_weights:
            weight_dump = {}
            for series_key, weights in shared_aggregator.weights.items():
                label = f"{series_key[0]}/{series_key[1]}"
                weight_dump[label] = {
                    k: round(v, 4) for k, v in sorted(weights.items(), key=lambda x: -x[1])
                }
            (out_dir / "expert_weights.json").write_text(
                json.dumps(weight_dump, indent=2), encoding="utf-8"
            )
            logger.info("Expert weights dumped to %s", out_dir / "expert_weights.json")
            for label, ws in sorted(weight_dump.items()):
                top3 = list(ws.items())[:3]
                logger.info("  %s: %s", label, " | ".join(f"{n}={w:.3f}" for n, w in top3))

    logger.info("Done. Output dir: %s", out_dir)


def _default_horizon_weights(horizons: list[int]) -> list[float]:
    """Generate horizon weights proportional to horizon value (longer = higher weight)."""
    total = sum(horizons)
    return [h / total for h in horizons]


if __name__ == "__main__":
    main()
