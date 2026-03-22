#!/usr/bin/env python3
"""
Run VQS backtest: compare predicted vs actual cutoffs at reference dates.

For each reference date T and horizon h (1, 3, 6 months), run solver with
knowledge_date=T, get predicted cutoff for month T+h, compare to actual
cutoff at T+h. Output Bulletin MAE (days) and optional maturity metrics.

Usage:
  bazel run //scripts/vqs:run_backtest -- --reference-dates 2021-01-01 2022-01-01 --horizons 1 3 6
  bazel run //scripts/vqs:run_backtest -- --reference-dates 2024-01-01 --horizons 1 --visa-class 2nd --country 3
"""

import argparse
import json
import logging
import os
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.business.vqs.contextual_aggregator import ContextualTrajectoryAggregator
from lib.business.vqs.solver import (
    get_cutoff_at_date,
    predict_next_bulletin_and_maturity,
)
from lib.utils.logging_utils import ScriptLogger
from models.raw_facts import RawFactsLedger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def _add_months(d: date, months: int) -> date:
    """Return first day of month d + months."""
    year, month = d.year, d.month
    month += months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return date(year, month, 1)


def run_backtest(
    reference_dates: list[date],
    horizons: list[int],
    visa_class: str = "2nd",
    country: int = 3,
    action_type: str = "final_action",
    monthly_supply: int | None = None,
    use_contextual_ensemble: bool = False,
) -> list[dict]:
    """
    Run backtest and return list of metric dicts.

    Each entry: {reference_date, horizon, predicted_cutoff, actual_cutoff, mae_days, error_note}.
    """
    out: list[dict] = []
    for t in reference_dates:
        facts = list(RawFactsLedger.objects.filter(publication_date__lte=t))
        if use_contextual_ensemble:
            aggregator = ContextualTrajectoryAggregator()
            aggregator.warmup_history(visa_class, country, action_type, t, horizons)

            for h in horizons:
                target_month = _add_months(
                    date(t.year, t.month, 1) if t.day != 1 else t,
                    h,
                )
                pred_cutoff, _ = aggregator.predict(
                    visa_class=visa_class,
                    country=country,
                    action_type=action_type,
                    target_date=target_month,
                    horizon=h,
                )

                actual_cutoff = get_cutoff_at_date(
                    visa_class, country, action_type, target_month
                )
                mae_days: int | None = None
                error_note: str | None = None
                if pred_cutoff is not None and actual_cutoff is not None:
                    mae_days = abs((pred_cutoff - actual_cutoff).days)
                elif pred_cutoff is None:
                    error_note = "no_prediction"
                elif actual_cutoff is None:
                    error_note = "no_actual"
                out.append(
                    {
                        "reference_date": t.isoformat(),
                        "horizon_months": h,
                        "target_month": target_month.isoformat(),
                        "predicted_cutoff": pred_cutoff.isoformat()
                        if pred_cutoff
                        else None,
                        "actual_cutoff": actual_cutoff.isoformat()
                        if actual_cutoff
                        else None,
                        "mae_days": mae_days,
                        "error_note": error_note,
                    }
                )
            continue

        outcome = predict_next_bulletin_and_maturity(
            knowledge_date=t,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            monthly_supply=monthly_supply,
            facts=facts,
        )
        results = outcome.results
        for h in horizons:
            target_month = _add_months(
                date(t.year, t.month, 1) if t.day != 1 else t,
                h,
            )
            pred_cutoff = None
            for res in results:
                if res.month == target_month:
                    pred_cutoff = res.cutoff_date
                    break
            actual_cutoff = get_cutoff_at_date(
                visa_class, country, action_type, target_month
            )
            mae_days: int | None = None
            error_note: str | None = None
            if pred_cutoff is not None and actual_cutoff is not None:
                mae_days = abs((pred_cutoff - actual_cutoff).days)
            elif pred_cutoff is None:
                error_note = "no_prediction"
            elif actual_cutoff is None:
                error_note = "no_actual"
            out.append(
                {
                    "reference_date": t.isoformat(),
                    "horizon_months": h,
                    "target_month": target_month.isoformat(),
                    "predicted_cutoff": pred_cutoff.isoformat()
                    if pred_cutoff
                    else None,
                    "actual_cutoff": actual_cutoff.isoformat()
                    if actual_cutoff
                    else None,
                    "mae_days": mae_days,
                    "error_note": error_note,
                }
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VQS backtest: predicted vs actual cutoffs"
    )
    parser.add_argument(
        "--reference-dates",
        nargs="+",
        required=True,
        help="Reference dates YYYY-MM-DD (knowledge date T)",
    )
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 3, 6],
        help="Horizons in months (default: 1 3 6)",
    )
    parser.add_argument("--visa-class", default="2nd", help="Visa class (default: 2nd)")
    parser.add_argument(
        "--country", type=int, default=3, help="Country enum value (default: 3 = India)"
    )
    parser.add_argument(
        "--action-type",
        default="final_action",
        help="Action type (default: final_action)",
    )
    parser.add_argument(
        "--monthly-supply",
        type=int,
        default=None,
        help="Override monthly supply (default: dynamic per-country calculation)",
    )
    parser.add_argument("--output", choices=["json", "text"], default="text")
    parser.add_argument("--use-contextual-ensemble", action="store_true")
    args = parser.parse_args()

    script_logger.log_call(
        args={
            "reference_dates": args.reference_dates,
            "horizons": args.horizons,
            "visa_class": args.visa_class,
            "country": args.country,
        },
        context="VQS backtest",
    )

    ref_dates = [date.fromisoformat(d) for d in args.reference_dates]
    metrics = run_backtest(
        reference_dates=ref_dates,
        horizons=args.horizons,
        visa_class=args.visa_class,
        country=args.country,
        action_type=args.action_type,
        monthly_supply=args.monthly_supply,
        use_contextual_ensemble=args.use_contextual_ensemble,
    )

    if args.output == "json":
        print(json.dumps(metrics, indent=2))
    else:
        for m in metrics:
            mae = m.get("mae_days")
            note = m.get("error_note") or ""
            print(
                f"{m['reference_date']} h={m['horizon_months']} "
                f"pred={m['predicted_cutoff']} actual={m['actual_cutoff']} "
                f"MAE_days={mae} {note}"
            )
        valid_mae = [x["mae_days"] for x in metrics if x.get("mae_days") is not None]
        if valid_mae:
            avg = sum(valid_mae) / len(valid_mae)
            print(f"Average MAE (days): {avg:.1f} (n={len(valid_mae)})")


if __name__ == "__main__":
    main()
