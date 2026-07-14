"""Shared prediction loading: stored DB predictions with solver backtest fallback.

Both the predictions table (text) and spaghetti chart (visual) use this module
to answer the same question: "what would the VQS model have predicted for a
given target month?"

Priority: stored PredictedCutoff (from publish_predictions) → live solver backtest.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from lib.business.vqs.solver import (
    SolverResult,
    predict_next_bulletin_and_maturity,
    predict_regime_switched,
)
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedCutoff

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """Single series prediction for one target month."""

    predicted_date: date | None
    knowledge_date: date
    source: str  # "stored" or "backtest"
    confidence_low: date | None = None
    confidence_high: date | None = None
    explanation_markdown: str | None = None
    expert_predictions: dict | None = None
    movement_probability: float | None = None
    model_name: str = "unknown"


def compute_knowledge_date(target_month: date, horizon: int = 1) -> date:
    """Knowledge date for backtesting: day before actual publication, else target − horizon months."""
    if horizon == 1:
        b = Bulletin.objects.filter(
            publication_date__year=target_month.year,
            publication_date__month=target_month.month,
        ).first()
        if b:
            return b.publication_date - timedelta(days=1)
    return target_month - relativedelta(months=horizon)


def load_stored_predictions_bulk(
    visa_class: str, country: int, action_type: str
) -> dict[date, date]:
    """Bulk-load stored predictions for one series.

    Returns {target_bulletin_month: predicted_date}.
    Used by evaluate_model for batch evaluation.
    """
    rows = (
        PredictedCutoff.objects.filter(
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            predicted_date__isnull=False,
        )
        .select_related("bulletin")
        # Ascending prediction_date so that when several horizons target the same
        # month, the LATEST prediction (largest prediction_date = shortest horizon,
        # i.e. the 1-month line) deterministically overwrites the longer-horizon
        # ones — matching get_all_predictions_for_month / get_prediction_for_series.
        .order_by("bulletin__prediction_date")
    )
    return {row.bulletin.target_bulletin_month: row.predicted_date for row in rows}


def build_solver_cache(
    visa_class: str,
    country: int,
    knowledge_dates: list[date],
    action_type: str = "filing",
) -> dict[tuple[date, int, int], date]:
    """Run VQS solver once per unique knowledge_date, cache all step results.

    Returns {(knowledge_date, target_year, target_month): cutoff_date}.
    Avoids redundant solver calls when evaluating multiple horizons.
    """
    cache: dict[tuple[date, int, int], date] = {}
    total = len(knowledge_dates)
    for idx, kd in enumerate(knowledge_dates):
        try:
            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=kd,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                force_physics=False,
            )
            for res in outcome.results:
                if res.cutoff_date:
                    cache[(kd, res.month.year, res.month.month)] = res.cutoff_date
        except Exception as e:
            logger.debug(f"VQS Error at {kd}: {e}")
        if (idx + 1) % 20 == 0:
            logger.info(f"  VQS cache: {idx + 1}/{total} knowledge dates")
    return cache


def build_solver_cache_ablated(
    visa_class: str,
    country: int,
    knowledge_dates: list[date],
    action_type: str = "filing",
    excluded_experts: frozenset[str] | None = None,
) -> dict[tuple[date, int, int], date]:
    """Build VQS solver cache with specified experts excluded (for ablation studies).

    Example: pass excluded_experts=frozenset({"cross_series", "gbm"}) to measure
    the isolated contribution of cross-series features to prediction accuracy.
    """
    from lib.business.vqs.aggregator import ExpertAggregator
    from lib.business.vqs.expert_pool import ALL_EXPERTS

    if excluded_experts is None:
        excluded_experts = frozenset()

    ablated_experts = {k: v for k, v in ALL_EXPERTS.items() if k not in excluded_experts}
    aggregator = ExpertAggregator(experts=ablated_experts)

    cache: dict[tuple[date, int, int], date] = {}
    total = len(knowledge_dates)
    for idx, kd in enumerate(knowledge_dates):
        try:
            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=kd,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                force_physics=False,
                aggregator=aggregator,
            )
            for res in outcome.results:
                if res.cutoff_date:
                    cache[(kd, res.month.year, res.month.month)] = res.cutoff_date
        except Exception as e:
            logger.debug(f"Ablation error at {kd}: {e}")
        if (idx + 1) % 20 == 0:
            logger.info(f"  Ablation cache: {idx + 1}/{total} knowledge dates")
    return cache


def build_regime_switched_cache(
    visa_class: str,
    country: int,
    knowledge_dates: list[date],
    action_type: str = "filing",
) -> dict[tuple[date, int, int], date]:
    """Run regime-switched predictor per knowledge_date, cache step results.

    Same interface as build_solver_cache but uses the undampened
    regime-switched selector instead of the dampened ensemble.
    """
    cache: dict[tuple[date, int, int], date] = {}
    total = len(knowledge_dates)
    for idx, kd in enumerate(knowledge_dates):
        try:
            outcome = predict_regime_switched(
                knowledge_date=kd,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
            )
            for res in outcome.results:
                if res.cutoff_date:
                    cache[(kd, res.month.year, res.month.month)] = res.cutoff_date
        except Exception as e:
            logger.debug(f"Regime-switched error at {kd}: {e}")
        if (idx + 1) % 20 == 0:
            logger.info(f"  Regime-switched cache: {idx + 1}/{total} knowledge dates")
    return cache


def _extract_prediction_from_solver(
    results: list[SolverResult], target_month: date
) -> date | None:
    """Find the cutoff_date in solver results matching target_month."""
    for res in results:
        if res.month.year == target_month.year and res.month.month == target_month.month:
            return res.cutoff_date
    return None


def get_prediction_for_series(
    target_month: date,
    visa_class: str,
    country: int,
    action_type: str,
) -> PredictionResult:
    """Get prediction for one series/month. Prefers stored; falls back to solver."""
    # Order by prediction_date descending to get the most recent prediction
    # (including null ones — a newer null "Current" prediction should win).
    stored = (
        PredictedCutoff.objects.filter(
            bulletin__target_bulletin_month=target_month,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
        )
        .select_related("bulletin")
        .order_by("-bulletin__prediction_date")
        .first()
    )
    if stored:
        return PredictionResult(
            predicted_date=stored.predicted_date,
            knowledge_date=stored.bulletin.prediction_date,
            source="stored",
            confidence_low=stored.confidence_low,
            confidence_high=stored.confidence_high,
            explanation_markdown=stored.explanation_markdown or None,
            expert_predictions=stored.expert_predictions or None,
            movement_probability=stored.movement_probability,
            model_name=stored.model_name or "unknown",
        )

    kd = compute_knowledge_date(target_month)

    from lib.business.vqs.data_cache import is_current_at_date

    if is_current_at_date(visa_class, country, action_type, kd):
        return PredictionResult(predicted_date=None, knowledge_date=kd, source="backtest")

    try:
        outcome = predict_next_bulletin_and_maturity(
            knowledge_date=kd,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
        )
        pred = _extract_prediction_from_solver(outcome.results, target_month)
        return PredictionResult(predicted_date=pred, knowledge_date=kd, source="backtest")
    except Exception:
        logger.debug(
            f"Solver failed for {visa_class}/{country}/{action_type} @ {target_month}",
            exc_info=True,
        )
        return PredictionResult(predicted_date=None, knowledge_date=kd, source="backtest")


def get_all_predictions_for_month(
    target_month: date,
    classes: list[str],
    countries: list[int],
    action_types: list[str],
) -> tuple[dict[tuple[str, int, str], PredictionResult], date]:
    """Get predictions for all series in a target month.

    Returns (results_dict, knowledge_date) where results_dict is keyed by
    (visa_class, country, action_type).

    Optimised: bulk-loads stored predictions first, then runs solver only
    for missing series (batched by unique (visa_class, country, action_type)).
    """
    kd = compute_knowledge_date(target_month)
    results: dict[tuple[str, int, str], PredictionResult] = {}

    stored_by_key: dict[tuple[str, int, str], PredictedCutoff | None] = {}
    stored_qs = (
        PredictedCutoff.objects.filter(
            bulletin__target_bulletin_month=target_month,
        )
        .select_related("bulletin")
        .order_by("bulletin__prediction_date")  # ascending: latest overwrites earlier
    )
    for sc in stored_qs:
        # Include null predictions so a newer "Current" (null) prediction
        # overwrites an older stale non-null one from a longer horizon.
        stored_by_key[(sc.visa_class, sc.country, sc.action_type)] = sc

    for action_type in action_types:
        for country in countries:
            for visa_class in classes:
                key = (visa_class, country, action_type)

                stored = stored_by_key.get(key)
                if stored is not None:
                    results[key] = PredictionResult(
                        predicted_date=stored.predicted_date,
                        knowledge_date=stored.bulletin.prediction_date,
                        source="stored",
                        confidence_low=stored.confidence_low,
                        confidence_high=stored.confidence_high,
                        explanation_markdown=stored.explanation_markdown or None,
                        expert_predictions=stored.expert_predictions or None,
                        movement_probability=stored.movement_probability,
                        model_name=stored.model_name or "unknown",
                    )
                    continue

                # Skip "Current" series — solver would return a stale
                # cutoff from potentially years ago.
                from lib.business.vqs.data_cache import is_current_at_date

                if is_current_at_date(visa_class, country, action_type, kd):
                    results[key] = PredictionResult(
                        predicted_date=None, knowledge_date=kd, source="backtest"
                    )
                    continue

                try:
                    outcome = predict_next_bulletin_and_maturity(
                        knowledge_date=kd,
                        visa_class=visa_class,
                        country=country,
                        action_type=action_type,
                    )
                    pred = _extract_prediction_from_solver(outcome.results, target_month)
                    results[key] = PredictionResult(
                        predicted_date=pred, knowledge_date=kd, source="backtest"
                    )
                except Exception:
                    results[key] = PredictionResult(
                        predicted_date=None, knowledge_date=kd, source="backtest"
                    )

    return results, kd


def get_actual_cutoffs(
    visa_class: str, country: int, action_type: str = "filing"
) -> dict[date, date]:
    """Full history of actual cutoffs for one series.

    Returns {bulletin_publication_date: cutoff_date}.
    """
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class,
        country=country,
        action_type=action_type,
    ).order_by("bulletin__publication_date")
    return {h.bulletin.publication_date: h.cutoff_date for h in history if h.cutoff_date}
