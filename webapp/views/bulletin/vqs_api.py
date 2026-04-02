"""Bulletin Forecast Model API for cutoff and maturity predictions."""

import logging
from datetime import date, datetime

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from lib.business.vqs.solver import predict_regime_switched
from models.enums.country import Country

logger = logging.getLogger(__name__)

VQS_CACHE_SECONDS = 300


@method_decorator(require_GET, name="get")
@method_decorator(cache_page(VQS_CACHE_SECONDS), name="get")
class VQSPredictView(View):
    """
    GET /api/vqs/predict/

    Query params: visa_class (2nd, 3rd), country (int or name), action_type (final_action),
    priority_date (YYYY-MM-DD), knowledge_date (YYYY-MM-DD, default today).

    Returns: next_cutoff, maturity_month, disclaimer.
    """

    def get(self, request):
        visa_class = request.GET.get("visa_class", "2nd").strip()
        country_param = request.GET.get("country", "3")
        action_type = request.GET.get("action_type", "final_action").strip()
        priority_date_str = request.GET.get("priority_date")
        knowledge_date_str = request.GET.get("knowledge_date")

        knowledge_date = date.today()
        if knowledge_date_str:
            try:
                knowledge_date = datetime.strptime(
                    knowledge_date_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid knowledge_date (use YYYY-MM-DD)"},
                    status=400,
                )

        priority_date = None
        if priority_date_str:
            try:
                priority_date = datetime.strptime(priority_date_str, "%Y-%m-%d").date()
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid priority_date (use YYYY-MM-DD)"},
                    status=400,
                )

        if country_param.isdigit():
            country = int(country_param)
        else:
            try:
                country = getattr(
                    Country, country_param.upper().replace("-", "_")
                ).value
            except (AttributeError, ValueError):
                return JsonResponse(
                    {"error": f"Unknown country: {country_param}"},
                    status=400,
                )

        try:
            outcome = predict_regime_switched(
                knowledge_date=knowledge_date,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                priority_date=priority_date,
            )
            next_cutoff = outcome.predicted_cutoff
            maturity_month = outcome.maturity_month
            results = outcome.results
            confidence = outcome.confidence
        except Exception as e:
            logger.exception("Bulletin Forecast Model predict failed")
            return JsonResponse(
                {"error": "Prediction failed", "detail": str(e)},
                status=500,
            )

        confidence_low = None
        confidence_high = None
        if results:
            first = results[0]
            if first.confidence_low:
                confidence_low = first.confidence_low.isoformat()
            if first.confidence_high:
                confidence_high = first.confidence_high.isoformat()

        return JsonResponse(
            {
                "next_cutoff": next_cutoff.isoformat() if next_cutoff else None,
                "maturity_month": maturity_month.isoformat()
                if maturity_month
                else None,
                "confidence": confidence,
                "confidence_low": confidence_low,
                "confidence_high": confidence_high,
                "disclaimer": "Estimates use public data only; policy and allocation changes can affect outcomes.",
            }
        )
