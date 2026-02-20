
"""
Publish VQS Predictions to Database.

Usage:
    bazel run //scripts:publish_predictions -- --month 2026-03
    bazel run //scripts:publish_predictions -- --backfill-start-year 2024
"""
import argparse
import logging
import sys
import math
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import django
from django.conf import settings

if not settings.configured:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.path.append(".")
    import django_config.settings
    django.setup()

from lib.business.vqs.solver import predict_next_bulletin_and_maturity
from lib.business.vqs.aggregator import ExpertAggregator
from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.data_cache import get_all_bulletins
from models.vqs import PredictedBulletin, PredictedCutoff
from models.bulletin import Bulletin
from models.enums.country import Country
from models.raw_facts import RawFactsLedger
from models.visa_cutoff_date import VisaCutoffDate

logger = logging.getLogger(__name__)

# Global facts cache
FACTS = []

def load_facts():
    global FACTS
    if not FACTS:
        logger.info("Preloading facts...")
        FACTS = list(RawFactsLedger.objects.order_by("publication_date"))
        logger.info(f"Loaded {len(FACTS)} facts.")

def get_knowledge_date_for_target(target_month: date) -> date:
    """
    Determine the knowledge date (simulation date) for a target bulletin.
    
    Rules:
    1. If target is in the past, use the day BEFORE the actual publication date.
    2. If target is future (or unknown publication), use TODAY (or last day of previous month?).
       - If strict backtesting: use last day of previous month to simulate "start of month" prediction.
       - If "live": use today.
    """
    # Check if bulletin exists
    try:
        b = Bulletin.objects.filter(
            publication_date__year=target_month.year,
            publication_date__month=target_month.month
        ).first()
        if b:
            # If bulletin exists, we are simulating a past prediction "just in time"
            return b.publication_date - timedelta(days=1)
    except Exception:
        pass
    
    # If no bulletin, default to 'today' if target is next month, 
    # or last day of previous month if target is far future?
    # Better heuristic: 
    # For "March 2026", usually published mid-Feb.
    # If today is Feb 15, we use today.
    # If today is Jan 1, we use Jan 1.
    return date.today()

def generate_explanation(metadata: dict | None, confidence: str) -> str:
    """Generate a human-readable explanation from solver metadata."""
    if not metadata or not isinstance(metadata, dict):
        return f"Physics-based prediction (Confidence: {confidence})"
    
    parts = []
    if "weights" in metadata:
        weights = metadata["weights"]
        top_experts = sorted(weights.items(), key=lambda x: -x[1])[:3]
        expert_strs = [f"{k} ({v:.0%})" for k, v in top_experts if v > 0.05]
        parts.append(f"Ensemble consensus: {', '.join(expert_strs)}.")
        
    if "stickiness" in metadata:
        parts.append("Note: Prediction held steady due to recent volatility.")
        
    return " ".join(parts)

def publish_predictions(target_months: list[date], action_types: list[str]):
    load_facts()
    aggregator = ExpertAggregator() # Loads weights from history
    meta = VqsMetaParams.defaults()
    
    countries = [c.value for c in Country]
    visa_classes = ["1st", "2nd", "3rd", "4th", "5th"] 

    for target_month in target_months:
        target_month = target_month.replace(day=1)
        knowledge_date = get_knowledge_date_for_target(target_month)
        
        logger.info(f"Generating predictions for {target_month.strftime('%B %Y')} (Knowledge Date: {knowledge_date})")
        
        # Create or Update PredictedBulletin container
        pred_bulletin, created = PredictedBulletin.objects.get_or_create(
            target_bulletin_month=target_month,
            defaults={"prediction_date": knowledge_date}
        )
        if not created:
            # Update prediction date if re-running?
            pred_bulletin.prediction_date = knowledge_date
            pred_bulletin.save()
            # Clear old cutoffs
            pred_bulletin.cutoffs.all().delete()
            
        # Filter facts manually
        current_facts = [f for f in FACTS if f.publication_date <= knowledge_date]
        
        count = 0
        for action in action_types:
            for country in countries:
                for visa_class in visa_classes:
                    # Run Solver
                    cutoff, m_meta, res_list, confidence = predict_next_bulletin_and_maturity(
                        knowledge_date=knowledge_date,
                        visa_class=visa_class,
                        country=country,
                        action_type=action,
                        facts=current_facts,
                        meta=meta,
                        aggregator=aggregator
                    )
                    
                    # Extract CI
                    low = None
                    high = None
                    explanation = generate_explanation(m_meta, confidence)
                    
                    if isinstance(m_meta, dict):
                        low = m_meta.get("confidence_low")
                        high = m_meta.get("confidence_high")
                    
                    # Try to find actual if exists
                    actual_date = None
                    accuracy_score = None
                    
                    actual_obj = VisaCutoffDate.objects.filter(
                        bulletin__publication_date__year=target_month.year,
                        bulletin__publication_date__month=target_month.month,
                        visa_class=visa_class,
                        country=country,
                        action_type=action
                    ).first()
                    
                    if actual_obj:
                        actual_date = actual_obj.cutoff_date
                        if cutoff and actual_date:
                            accuracy_score = abs((cutoff - actual_date).days)
                            
                    PredictedCutoff.objects.create(
                        bulletin=pred_bulletin,
                        visa_class=visa_class,
                        country=country,
                        action_type=action,
                        predicted_date=cutoff,
                        confidence_low=low,
                        confidence_high=high,
                        explanation_markdown=explanation,
                        actual_date=actual_date,
                        accuracy_score=accuracy_score
                    )
                    count += 1
        
        logger.info(f"Saved {count} predictions for {target_month}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=str, help="Target month YYYY-MM")
    parser.add_argument("--backfill-start-year", type=int, help="Backfill from year")
    args = parser.parse_args()
    
    targets = []
    actions = ["final_action", "filing"] # Predict both
    
    if args.month:
        targets.append(date.fromisoformat(f"{args.month}-01"))
    elif args.backfill_start_year:
        start = date(args.backfill_start_year, 1, 1)
        # End is usually next month from today
        today = date.today()
        end = date(today.year, today.month, 1) + relativedelta(months=2) # Go slightly into future
        
        curr = start
        while curr <= end:
            targets.append(curr)
            curr += relativedelta(months=1)
            
    if not targets:
        # Default: Next month
        today = date.today()
        # If today is before 15th, maybe predict current month? 
        # Usually we predict the *upcoming* bulletin.
        next_month = today + relativedelta(months=1)
        targets.append(date(next_month.year, next_month.month, 1))
        
    publish_predictions(targets, actions)

if __name__ == "__main__":
    main()
