"""
Publish VQS Predictions to Database.

Usage:
    bazel run //scripts:publish_predictions -- --month 2026-03
    bazel run //scripts:publish_predictions -- --backfill-start-year 2024
"""

import argparse
import logging
import sys
from datetime import date, timedelta

import django
from dateutil.relativedelta import relativedelta
from django.conf import settings

if not settings.configured:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.path.append(".")
    django.setup()

from lib.business.vqs.aggregator import ExpertAggregator
from lib.business.vqs.calibration import compute_calibrated_interval
from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.solver import predict_next_bulletin_and_maturity, predict_regime_switched
from models.bulletin import Bulletin
from models.enums.country import Country
from models.raw_facts import RawFactsLedger
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff

# EB-1 oversubscribed series: regime-switched beats VQS Ensemble at all horizons
# (from spaghetti chart: RS 130d/62.8d MAE vs VQS 135.5d/62.4d on India/China EB-1)
_HYBRID_EB1_SERIES = frozenset([
    (Country.INDIA.value, "1st"),
    (Country.CHINA.value, "1st"),
])

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
            publication_date__month=target_month.month,
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


REGIME_DESCRIPTIONS = {
    "advancing": "Cutoff dates have been moving forward consistently",
    "stalled": "Cutoff dates have shown minimal movement",
    "retrogressing": "Cutoff dates have been moving backward",
    "recovering": "Cutoff dates are recovering from a recent retrogression",
    "volatile": "Cutoff dates have been fluctuating unpredictably",
}


def generate_explanation(metadata: dict | None, confidence: str) -> str:
    """Generate a human-readable explanation from solver metadata.

    Uses regime, expert weights, pace, and confidence interval spread
    to produce a rich explanation stored in PredictedCutoff.explanation_markdown.
    """
    if not metadata or not isinstance(metadata, dict):
        return f"Physics-based prediction (Confidence: {confidence})"

    parts = []

    # Regime context
    regime = metadata.get("regime")
    if regime:
        desc = REGIME_DESCRIPTIONS.get(regime, regime)
        regime_conf = metadata.get("regime_confidence", 0)
        strength = "strongly" if regime_conf > 0.7 else "moderately" if regime_conf > 0.3 else "weakly"
        parts.append(f"**Regime: {regime.upper()}** — {desc} ({strength} classified).")

    # Historical pace
    pace = metadata.get("pace_days_per_month")
    if pace is not None:
        if pace > 0:
            parts.append(f"Historical advancement pace: {pace:.1f} days/month.")
        elif pace < 0:
            parts.append(f"Historical retrogression pace: {abs(pace):.1f} days/month backward.")
        else:
            parts.append("Historical pace: near zero (stalled).")

    # Expert consensus
    weights = metadata.get("weights")
    if weights:
        top_experts = sorted(weights.items(), key=lambda x: -x[1])[:3]
        expert_strs = [f"{k} ({v:.0%})" for k, v in top_experts if v > 0.05]
        if expert_strs:
            parts.append(f"Ensemble consensus: {', '.join(expert_strs)}.")

    # Persistence weight (how conservative the prediction is)
    pw = metadata.get("persistence_weight")
    if pw is not None and pw > 0.5:
        parts.append(
            f"High conservation factor ({pw:.0%} persistence weight) — "
            "prediction pulled toward no-change due to regime uncertainty."
        )

    # Confidence interval spread
    ci_low = metadata.get("confidence_low")
    ci_high = metadata.get("confidence_high")
    if ci_low and ci_high:
        spread = (ci_high - ci_low).days
        if spread > 90:
            parts.append(f"Wide confidence range ({spread} days) — experts disagree significantly.")
        elif spread > 30:
            parts.append(f"Moderate confidence range ({spread} days).")
        else:
            parts.append(f"Narrow confidence range ({spread} days) — high expert consensus.")

    return " ".join(parts) if parts else f"Physics-based prediction (Confidence: {confidence})"


def publish_predictions(target_months: list[date], action_types: list[str]):
    load_facts()
    aggregator = ExpertAggregator()  # Loads weights from history
    meta = VqsMetaParams.defaults()

    countries = [c.value for c in Country]
    visa_classes = ["1st", "2nd", "3rd", "4th", "5th"]

    for target_month in target_months:
        target_month = target_month.replace(day=1)
        knowledge_date = get_knowledge_date_for_target(target_month)

        logger.info(
            f"Generating predictions for {target_month.strftime('%B %Y')} (Knowledge Date: {knowledge_date})"
        )

        # Create or Update PredictedBulletin container
        pred_bulletin, created = PredictedBulletin.objects.get_or_create(
            target_bulletin_month=target_month,
            defaults={"prediction_date": knowledge_date},
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
                    # Hybrid dispatch: regime-switched for EB-1 oversubscribed, VQS for EB-2/3
                    if (country, visa_class) in _HYBRID_EB1_SERIES:
                        outcome = predict_regime_switched(
                            knowledge_date=knowledge_date,
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            facts=current_facts,
                        )
                    else:
                        outcome = predict_next_bulletin_and_maturity(
                            knowledge_date=knowledge_date,
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            facts=current_facts,
                            meta=meta,
                            aggregator=aggregator,
                        )
                    cutoff = outcome.predicted_cutoff
                    m_meta = outcome.metadata
                    confidence = outcome.confidence

                    # Extract CI and per-expert predictions
                    low = None
                    high = None
                    expert_data = {}
                    explanation = generate_explanation(m_meta, confidence)

                    if isinstance(m_meta, dict):
                        low = m_meta.get("confidence_low")
                        high = m_meta.get("confidence_high")

                    # Override with calibrated intervals when point prediction exists
                    if cutoff is not None:
                        try:
                            low, high = compute_calibrated_interval(
                                predicted_date=cutoff,
                                visa_class=visa_class,
                                country=country,
                                action_type=action,
                                knowledge_date=knowledge_date,
                                horizon=1,
                                coverage=0.80,
                            )
                        except Exception as _ci_err:
                            logger.debug("Calibrated interval failed: %s", _ci_err)

                        preds = m_meta.get("expert_preds", {})
                        weights = m_meta.get("weights", {})
                        for name, pred_date in preds.items():
                            expert_data[name] = {
                                "pred": pred_date.isoformat() if pred_date else None,
                                "weight": round(weights.get(name, 0), 4),
                            }

                    # Try to find actual if exists
                    actual_date = None
                    accuracy_score = None

                    actual_obj = VisaCutoffDate.objects.filter(
                        bulletin__publication_date__year=target_month.year,
                        bulletin__publication_date__month=target_month.month,
                        visa_class=visa_class,
                        country=country,
                        action_type=action,
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
                        expert_predictions=expert_data,
                        actual_date=actual_date,
                        accuracy_score=accuracy_score,
                    )
                    count += 1

        logger.info(f"Saved {count} predictions for {target_month}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=str, help="Target month YYYY-MM")
    parser.add_argument("--backfill-start-year", type=int, help="Backfill from year")
    args = parser.parse_args()

    targets = []
    actions = ["final_action", "filing"]  # Predict both

    if args.month:
        targets.append(date.fromisoformat(f"{args.month}-01"))
    elif args.backfill_start_year:
        start = date(args.backfill_start_year, 1, 1)
        # End is usually next month from today
        today = date.today()
        end = date(today.year, today.month, 1) + relativedelta(
            months=2
        )  # Go slightly into future

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
