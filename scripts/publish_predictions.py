"""
Publish VQS Predictions to Database.

Usage:
    bazel run //scripts:publish_predictions -- --month 2026-03
    bazel run //scripts:publish_predictions -- --backfill-start-year 2024
    bazel run //scripts:publish_predictions -- --backfill-start-year 2018 --horizon 6
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
from lib.business.vqs.data_cache import get_cutoff_at_date, is_current_at_date
from lib.business.vqs.expert_pool import expert_oppenheim_pace
from lib.business.vqs.gbm_expert import expert_gbm_gated, expert_gbm_movement_prob
from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.solver import (
    predict_next_bulletin_and_maturity,
    predict_regime_switched,
)
from models.bulletin import Bulletin
from models.enums.country import Country
from models.raw_facts import RawFactsLedger
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff

# China EB-1: regime-switched best at 6m (155.7d); GBM Gated best at 12m (256.9d vs Pace 289.6d).
# Section 20: 6m RS=155.7d < Pace=167.1d < GBM Gated=169.0d; 12m GBM Gated=256.9d < Pace=289.6d.
_CHINA_EB1 = (Country.CHINA.value, "1st")

# India EB-1: regime-switched best at 1m/3m; GBM Gated best at 6m+ (beats RS by 35d).
# Section 20: 6m India EB-1 GBM Gated=233.3d, RS=268.5d, Persistence=289.2d.
_INDIA_EB1 = (Country.INDIA.value, "1st")

# At 6m (but < 12m), per-series dispatch based on Section 20 same-window eval.
# GBM Gated series: beat nearest competitor by ≥10d at 6m in same-window eval.
_GBM_GATED_6M_SERIES = frozenset([
    (Country.INDIA.value, "1st"),   # GBM Gated 233.3d vs RS 268.5d (−35.2d)
    (Country.CHINA.value, "3rd"),   # GBM Gated 158.5d vs Pace 193.0d (−34.5d)
])

# Pace series at 6m (but < 12m): Pace beats GBM Gated within ≥10d margin.
# India EB-2: GBM Gated 203.8d vs Pace 211.3d (−7.5d) — below 10d threshold, keep Pace.
# India EB-3: GBM Gated 261.1d vs Pace 264.3d (−3.2d) — below 10d threshold, keep Pace.
_PACE_6M_SERIES = frozenset([
    (Country.INDIA.value, "2nd"),   # Pace 211.3d vs GBM Gated 203.8d (7.5d gap, <10d threshold)
    (Country.INDIA.value, "3rd"),   # Pace 264.3d vs GBM Gated 261.1d (3.2d gap, <10d threshold)
    (Country.CHINA.value, "2nd"),   # Pace 155.4d vs GBM Gated 176.1d (−20.7d, Pace wins)
])

# At 12m+, different winners due to longer structural patterns.
# Section 20 same-window eval: GBM Gated wins 5/6, Pace wins 1/6.
_GBM_GATED_12M_SERIES = frozenset([
    (Country.CHINA.value, "1st"),   # GBM Gated 256.9d vs Pace 289.6d (−32.7d)
    (Country.CHINA.value, "2nd"),   # GBM Gated 230.7d vs Pace 246.4d (−15.7d) — switched from Pace §20
    (Country.CHINA.value, "3rd"),   # GBM Gated 224.3d vs Pace 302.0d (−77.7d)
    (Country.INDIA.value, "1st"),   # GBM Gated 369.6d vs Pace 435.0d (−65.4d)
    (Country.INDIA.value, "2nd"),   # GBM Gated 303.2d vs Pace 329.0d (−25.8d)
])

# Pace series at 12m: beats GBM Gated.
_PACE_12M_SERIES = frozenset([
    (Country.INDIA.value, "3rd"),   # Pace 490.0d vs GBM Gated 494.2d vs Persistence 523.8d (§21 eval)
])

# Persistence at 12m: reserved for structurally stalled series where Pace
# and GBM both produce extremely high MAE vs no-change baseline.
# Currently empty — India EB-3 Pace (490d) beats Persistence (524d).
# Reassign series here if future evals show model-12m MAE > persistence-12m MAE.
_PERSISTENCE_12M_SERIES: frozenset = frozenset()

# Series for which a 1m movement probability badge is computed.
# These are the oversubscribed EB-1/2/3 series where GBM CondDir signal is meaningful.
_MOVEMENT_PROB_SERIES = frozenset([
    (Country.INDIA.value, "1st"),
    (Country.INDIA.value, "2nd"),
    (Country.INDIA.value, "3rd"),
    (Country.CHINA.value, "1st"),
    (Country.CHINA.value, "2nd"),
    (Country.CHINA.value, "3rd"),
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


def get_knowledge_date_for_target(target_month: date, horizon_months: int = 1) -> date:
    """
    Determine the knowledge date (simulation date) for a target bulletin.

    For horizon_months=1: use the day before the actual publication date (1m-ahead prediction).
    For horizon_months>1: use the publication date of the bulletin that appeared
      approximately (horizon_months) before target_month.  This gives a proper
      retrospective backtest — only data available at that earlier date is used.
    """
    if horizon_months <= 1:
        # Standard: 1-month-ahead prediction made the day before publication.
        try:
            b = Bulletin.objects.filter(
                publication_date__year=target_month.year,
                publication_date__month=target_month.month,
            ).first()
            if b:
                return b.publication_date - timedelta(days=1)
        except Exception:
            pass
        return date.today()

    # Multi-horizon: find the bulletin that was published ~horizon_months before target.
    earlier = target_month - relativedelta(months=horizon_months)
    try:
        b = Bulletin.objects.filter(
            publication_date__year=earlier.year,
            publication_date__month=earlier.month,
        ).first()
        if b:
            # Use the day before that bulletin so we only have data from before it.
            return b.publication_date - timedelta(days=1)
    except Exception:
        pass
    # Fallback: last day of the month that is horizon_months before target.
    last_day = (earlier.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
    return last_day


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


def publish_predictions(target_months: list[date], action_types: list[str], horizon_months: int = 1):
    load_facts()
    aggregator = ExpertAggregator()  # Loads weights from history
    meta = VqsMetaParams.defaults()

    countries = [c.value for c in Country]
    visa_classes = ["1st", "2nd", "3rd", "4th", "5th"]

    for target_month in target_months:
        target_month = target_month.replace(day=1)
        knowledge_date = get_knowledge_date_for_target(target_month, horizon_months)

        logger.info(
            f"Generating {horizon_months}m predictions for {target_month.strftime('%B %Y')} (Knowledge Date: {knowledge_date})"
        )

        # One PredictedBulletin per (target_month, prediction_date) pair —
        # different horizon_months produce different prediction_dates.
        pred_bulletin, created = PredictedBulletin.objects.get_or_create(
            target_bulletin_month=target_month,
            prediction_date=knowledge_date,
        )
        if not created:
            # Re-running for the same (target, knowledge_date): clear and recompute.
            pred_bulletin.cutoffs.all().delete()

        # Filter facts manually
        current_facts = [f for f in FACTS if f.publication_date <= knowledge_date]

        # Compute prediction horizon in months (how far ahead is target_month from knowledge_date)
        horizon_m = (
            (target_month.year - knowledge_date.year) * 12
            + (target_month.month - knowledge_date.month)
        )

        count = 0
        for action in action_types:
            for country in countries:
                for visa_class in visa_classes:
                    # Skip "Current" series: no meaningful cutoff to predict.
                    # Without this check, persistence returns a stale date from
                    # years ago (the last month that had a real cutoff).
                    if is_current_at_date(visa_class, country, action, knowledge_date):
                        PredictedCutoff.objects.create(
                            bulletin=pred_bulletin,
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            predicted_date=None,
                            model_name="persistence",
                        )
                        count += 1
                        continue

                    # Horizon-aware hybrid dispatch (Sections 17–18, §20, §21 eval):
                    # 1m:     ALL series → Regime-Switched
                    # 3m:     China EB-1 → RS; India EB-1 → RS; all others → VQS ensemble
                    # 6m:     China EB-1 → RS; India EB-1, China EB-3 → GBM Gated;
                    #         India EB-2/3, China EB-2 → Pace
                    # 12m+:   China EB-1/2/3, India EB-1/2 → GBM Gated; India EB-3 → Pace
                    model_name = "vqs_ensemble"
                    dispatch_key = (country, visa_class)

                    if (dispatch_key == _CHINA_EB1 and horizon_m < 12) or (
                        dispatch_key == _INDIA_EB1 and horizon_m < 6
                    ) or horizon_m == 1:
                        # RS: China EB-1 at 1m/3m/6m; India EB-1 at 1m/3m; ALL series at 1m.
                        # At 1m, RS matches or beats persistence for all 6 series and is
                        # vastly better than VQS ensemble (166d avg vs 43d for RS/Persistence).
                        # VQS at 1m was predicting movement during the 2022-2026 stall that
                        # didn't materialise; RS correctly applies regime-based damping.
                        model_name = "regime_switched"
                        outcome = predict_regime_switched(
                            knowledge_date=knowledge_date,
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            facts=current_facts,
                        )
                        cutoff = outcome.predicted_cutoff
                        m_meta = outcome.metadata
                        confidence = outcome.confidence
                    elif horizon_m >= 12 and dispatch_key in _GBM_GATED_12M_SERIES:
                        # GBM Gated at 12m+: China EB-1/3, India EB-1/2
                        model_name = "gbm_gated"
                        cutoff = expert_gbm_gated(
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            knowledge_date=knowledge_date,
                            horizon=horizon_m,
                        )
                        m_meta = {"model": "gbm_gated", "horizon_months": horizon_m}
                        confidence = "medium"
                    elif horizon_m >= 12 and dispatch_key in _PACE_12M_SERIES:
                        # Pace at 12m+: India EB-3 (Pace 490d beats GBM 494d, Persistence 524d)
                        model_name = "oppenheim_pace"
                        cutoff = expert_oppenheim_pace(
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            knowledge_date=knowledge_date,
                            horizon=horizon_m,
                        )
                        m_meta = {"model": "oppenheim_pace", "horizon_months": horizon_m}
                        confidence = "medium"
                    elif horizon_m >= 12 and dispatch_key in _PERSISTENCE_12M_SERIES:
                        # Persistence at 12m+: for structurally stalled series where Pace
                        # and GBM both produce extremely high MAE vs no-change baseline.
                        # India EB-3: Pace 491d, GBM 499d — both dominated by no-change.
                        model_name = "persistence"
                        cutoff = get_cutoff_at_date(visa_class, country, action, knowledge_date)
                        m_meta = {"model": "persistence", "horizon_months": horizon_m}
                        confidence = "low"
                    elif dispatch_key in _GBM_GATED_6M_SERIES and horizon_m >= 6:
                        # GBM Gated at 6m (but < 12m): India EB-1, China EB-3
                        model_name = "gbm_gated"
                        cutoff = expert_gbm_gated(
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            knowledge_date=knowledge_date,
                            horizon=horizon_m,
                        )
                        m_meta = {"model": "gbm_gated", "horizon_months": horizon_m}
                        confidence = "medium"
                    elif dispatch_key in _PACE_6M_SERIES and horizon_m >= 6:
                        # Pace at 6m (but < 12m): India EB-2/3, China EB-2
                        model_name = "oppenheim_pace"
                        cutoff = expert_oppenheim_pace(
                            visa_class=visa_class,
                            country=country,
                            action_type=action,
                            knowledge_date=knowledge_date,
                            horizon=horizon_m,
                        )
                        m_meta = {"model": "oppenheim_pace", "horizon_months": horizon_m}
                        confidence = "medium"
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
                                horizon=max(1, horizon_months),
                                coverage=0.80,
                            )
                        except Exception as _ci_err:
                            logger.debug("Calibrated interval failed: %s", _ci_err)

                        if isinstance(m_meta, dict):
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

                    # Compute movement probability badge for 1m oversubscribed series.
                    movement_prob = None
                    if horizon_months == 1 and dispatch_key in _MOVEMENT_PROB_SERIES:
                        try:
                            movement_prob = expert_gbm_movement_prob(
                                visa_class=visa_class,
                                country=country,
                                action_type=action,
                                knowledge_date=knowledge_date,
                                horizon=1,
                            )
                        except Exception as _mp_err:
                            logger.debug("Movement prob failed: %s", _mp_err)

                    PredictedCutoff.objects.create(
                        bulletin=pred_bulletin,
                        visa_class=visa_class,
                        country=country,
                        action_type=action,
                        predicted_date=cutoff,
                        confidence_low=low,
                        confidence_high=high,
                        explanation_markdown=explanation,
                        model_name=model_name,
                        expert_predictions=expert_data,
                        actual_date=actual_date,
                        accuracy_score=accuracy_score,
                        movement_probability=movement_prob,
                    )
                    count += 1

        logger.info(f"Saved {count} predictions for {target_month}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=str, help="Target month YYYY-MM")
    parser.add_argument("--backfill-start-year", type=int, help="Backfill from year")
    parser.add_argument(
        "--horizon",
        type=int,
        default=1,
        help="Prediction horizon in months (1 = day-before-publication, 6 = made 6 months earlier). "
             "Use --horizon 6 to backfill 6m-ahead predictions. Default: 1.",
    )
    args = parser.parse_args()

    targets = []
    actions = ["final_action", "filing"]  # Predict both

    if args.month:
        targets.append(date.fromisoformat(f"{args.month}-01"))
    elif args.backfill_start_year:
        start = date(args.backfill_start_year, 1, 1)
        today = date.today()
        end = date(today.year, today.month, 1) + relativedelta(months=2)

        curr = start
        while curr <= end:
            targets.append(curr)
            curr += relativedelta(months=1)

    if not targets:
        # Default: Next month
        today = date.today()
        next_month = today + relativedelta(months=1)
        targets.append(date(next_month.year, next_month.month, 1))

    publish_predictions(targets, actions, horizon_months=args.horizon)


if __name__ == "__main__":
    main()
