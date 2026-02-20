#!/usr/bin/env python3
"""
Run VQS simulation and print predicted next bulletin cutoff and maturity date.

Usage:
  bazel run //scripts/vqs:run_simulation -- --knowledge-date 2024-01-01 --visa-class 2nd --country 3 --action-type final_action
  bazel run //scripts/vqs:run_simulation -- --knowledge-date 2024-01-01 --visa-class 2nd --country 3 --priority-date 2020-06-15 --months 24

When to use:
- After ingesting stub or real I-140 data (scripts/vqs:ingest_uscis_i140)
- To get next bulletin prediction and/or maturity date for a priority date
"""

import argparse
import logging
import os
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.business.vqs.solver import predict_next_bulletin_and_maturity
from lib.utils.logging_utils import ScriptLogger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run VQS simulation: next bulletin cutoff and maturity date"
    )
    parser.add_argument(
        "--knowledge-date",
        type=str,
        required=True,
        help="Knowledge date YYYY-MM-DD (state of the world for simulation)",
    )
    parser.add_argument(
        "--visa-class",
        type=str,
        required=True,
        help="Visa class (e.g. 2nd for EB2, 3rd for EB3)",
    )
    parser.add_argument(
        "--country",
        type=int,
        required=True,
        help="Country enum value (e.g. 3 for India, 2 for China)",
    )
    parser.add_argument(
        "--action-type",
        type=str,
        default="final_action",
        help="Action type (default: final_action)",
    )
    parser.add_argument(
        "--priority-date",
        type=str,
        default=None,
        help="Priority date YYYY-MM-DD for maturity prediction",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=12,
        help="Max months to simulate (default: 12)",
    )
    parser.add_argument(
        "--monthly-supply",
        type=int,
        default=700,
        help="Constant monthly supply (default: 700)",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={
            "knowledge_date": args.knowledge_date,
            "visa_class": args.visa_class,
            "country": args.country,
            "priority_date": args.priority_date,
        },
        context="VQS: Run simulation",
    )

    knowledge_date = date.fromisoformat(args.knowledge_date)
    priority_date = (
        date.fromisoformat(args.priority_date) if args.priority_date else None
    )

    next_cutoff, maturity_month, results, confidence = (
        predict_next_bulletin_and_maturity(
            knowledge_date=knowledge_date,
            visa_class=args.visa_class,
            country=args.country,
            action_type=args.action_type,
            priority_date=priority_date,
            monthly_supply=args.monthly_supply,
        )
    )

    print("VQS Simulation Results")
    print("----------------------")
    print(f"Knowledge date:     {knowledge_date}")
    print(f"Visa class:         {args.visa_class}")
    print(f"Country:            {args.country}")
    print(f"Action type:        {args.action_type}")
    print(f"Next bulletin cutoff: {next_cutoff}")
    print(f"Confidence:          {confidence}")
    if priority_date:
        print(f"Priority date:      {priority_date}")
        print(f"Maturity month:    {maturity_month}")
    print(f"Steps (first {min(5, len(results))}):")
    for r in results[:5]:
        print(f"  {r.month}  cutoff={r.cutoff_date}  consumed={r.consumed}")
    if len(results) > 5:
        print(f"  ... ({len(results)} total)")


if __name__ == "__main__":
    main()
