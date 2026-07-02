import calendar
import functools
import logging
import re
from datetime import date

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_page

from lib.business.vqs.prediction_loader import (
    PredictionResult,
    get_all_predictions_for_month,
)
from models.bulletin import Bulletin
from models.enums.country import Country
from models.enums.family_preference import FamilyPreference
from models.enums.visa_category import VisaCategory
from models.visa_cutoff_date import VisaCutoffDate

logger = logging.getLogger(__name__)

_REGIME_DISPLAY = {
    "ADVANCING": ("Advancing", "success"),
    "STALLED": ("Stalled", "secondary"),
    "RETROGRESSING": ("Retrogrressing", "danger"),
    "RECOVERING": ("Recovering", "info"),
    "VOLATILE": ("Volatile", "warning"),
}

_EB4_CLASSES = {"4th"}
_OVERSUBSCRIBED_EB23_COUNTRIES = {Country.INDIA.value, Country.CHINA.value}


def prediction_list(request: HttpRequest) -> HttpResponse:
    """List all bulletin months available for prediction browsing."""
    from webapp.views.bulletin.prediction_month_forecast import (
        forecast_url_for,
        upcoming_forecast_month,
    )

    months = (
        Bulletin.objects.order_by("-publication_date")
        .values_list("publication_date", flat=True)
    )
    upcoming = upcoming_forecast_month()
    context = {
        "months": list(months),
        "forecast_url": forecast_url_for(upcoming) if upcoming else None,
        "forecast_month_label": upcoming.strftime("%B %Y") if upcoming else None,
        "hreflang_en": request.build_absolute_uri("/predictions/"),
        "hreflang_es": request.build_absolute_uri("/es/predictions/"),
    }
    return render(request, "vqs/prediction_list.html", context)


def prediction_category_landing(request: HttpRequest, category: str) -> HttpResponse:
    """Redirect /predictions/<category>/ to the latest bulletin month (detail page)."""
    valid = {c.value for c in VisaCategory}
    if category not in valid:
        from django.http import Http404

        raise Http404("Unknown prediction category")

    latest = (
        Bulletin.objects.order_by("-publication_date")
        .values_list("publication_date", flat=True)
        .first()
    )
    if not latest:
        from django.http import Http404

        raise Http404("No bulletins available")

    return redirect(
        "prediction_detail_category",
        category=category,
        year=latest.year,
        month=latest.month,
    )


def _add_months(sourcedate: date, months: int) -> date:
    m = sourcedate.month - 1 + months
    y = sourcedate.year + m // 12
    mon = m % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(y, mon)[1])
    return date(y, mon, day)


def _cache_historical_predictions_only(timeout: int):
    """Cache prediction_detail ONLY for months strictly older than the latest
    published bulletin.

    A historical month's page is immutable: both its stored predictions and its
    actual cutoffs are fixed once published, so caching protects the large
    archive against crawl storms. The LATEST month is NOT immutable — the hourly
    refresh (refresh_bulletin.py) re-publishes its predictions and attaches the
    just-arrived actuals — so caching it could pin a stale/incomplete render for
    up to `timeout`. It renders fast anyway (stored predictions, no live solver),
    so we always serve it fresh. Adds one indexed bulletin lookup per request.
    """
    cached_view = None

    def decorator(view_func):
        nonlocal cached_view
        cached_view = cache_page(timeout)(view_func)

        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            target = date(int(kwargs["year"]), int(kwargs["month"]), 1)
            latest = (
                Bulletin.objects.order_by("-publication_date")
                .values_list("publication_date", flat=True)
                .first()
            )
            if latest and target < latest:
                return cached_view(request, *args, **kwargs)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


@_cache_historical_predictions_only(60 * 60)
def prediction_detail(
    request: HttpRequest, year: int, month: int, category: str = "employment_based"
) -> HttpResponse:
    """Detailed view: backtested predictions + actual bulletin for a month."""
    target_date = date(year, month, 1)

    actual_bulletin = Bulletin.objects.filter(publication_date=target_date).first()
    if not actual_bulletin:
        from django.http import Http404

        raise Http404(f"No bulletin found for {target_date.strftime('%B %Y')}")

    # Navigation: prev/next actual bulletin
    prev_actual = (
        Bulletin.objects.filter(publication_date__lt=target_date)
        .order_by("-publication_date")
        .first()
    )
    next_actual = (
        Bulletin.objects.filter(publication_date__gt=target_date)
        .order_by("publication_date")
        .first()
    )
    nav_prev = prev_actual.publication_date if prev_actual else None
    nav_next = next_actual.publication_date if next_actual else None

    # Previous month's actuals for delta calculation
    last_actual_month = _add_months(target_date, -1)
    last_actual_bulletin = Bulletin.objects.filter(
        publication_date=last_actual_month
    ).first()
    # Track the Current/Unavailable state alongside the raw cutoff_date. A
    # Current ("C") cutoff is stored as the bulletin-month DATE (a sentinel, not
    # a real cutoff), so differencing it month-over-month fabricates a spurious
    # "↑ 1m" advance. An Unavailable ("U") cutoff is stored as NULL. Both must be
    # kept out of the numeric movement/error math below.
    last_actual_cutoffs: dict[str, date] = {}
    last_actual_flags: dict[str, tuple[bool, bool]] = {}
    if last_actual_bulletin:
        for cutoff in VisaCutoffDate.objects.filter(bulletin=last_actual_bulletin):
            key = f"{cutoff.visa_class}_{cutoff.country}_{cutoff.action_type}"
            last_actual_cutoffs[key] = cutoff.cutoff_date
            last_actual_flags[key] = (cutoff.is_current, cutoff.is_unavailable)

    # Current month's actual cutoffs
    current_actual_cutoffs: dict[str, date] = {}
    current_actual_flags: dict[str, tuple[bool, bool]] = {}
    for cutoff in VisaCutoffDate.objects.filter(bulletin=actual_bulletin):
        key = f"{cutoff.visa_class}_{cutoff.country}_{cutoff.action_type}"
        current_actual_cutoffs[key] = cutoff.cutoff_date
        current_actual_flags[key] = (cutoff.is_current, cutoff.is_unavailable)

    if category == VisaCategory.FAMILY_SPONSORED.value:
        classes = [f[0] for f in FamilyPreference.choices]
        class_display = {f[0]: f[1].split(":")[0] for f in FamilyPreference.choices}
        category_label = "Family-Sponsored"
    else:
        classes = ["1st", "2nd", "3rd", "4th", "5th"]
        class_display = {
            "1st": "EB-1",
            "2nd": "EB-2",
            "3rd": "EB-3",
            "4th": "EB-4",
            "5th": "EB-5",
        }
        category_label = "Employment-Based"

    countries = [
        Country.ALL,
        Country.CHINA,
        Country.INDIA,
        Country.MEXICO,
        Country.PHILIPPINES,
    ]
    action_types = ["final_action", "filing"]

    # Load predictions (stored DB or solver backtest)
    predictions, knowledge_date = get_all_predictions_for_month(
        target_date,
        classes,
        [c.value for c in countries],
        action_types,
    )

    # Build matrix
    matrix: dict = {}
    for vc in classes:
        matrix[vc] = {}
        for c in countries:
            matrix[vc][c.value] = {
                "final_action": {"predicted": None, "actual_date": None},
                "filing": {"predicted": None, "actual_date": None},
            }

    # Populate predictions
    for (vc, cval, atype), pred_result in predictions.items():
        if vc not in matrix or cval not in matrix.get(vc, {}):
            continue
        cell = matrix[vc][cval][atype]

        if pred_result.predicted_date:
            key = f"{vc}_{cval}_{atype}"
            last_actual_date = last_actual_cutoffs.get(key)
            last_is_current, last_is_unavailable = last_actual_flags.get(
                key, (False, False)
            )
            pred_obj = _make_prediction_display(
                pred_result,
                last_actual_date,
                visa_class=vc,
                country=cval,
                last_actual_is_current=last_is_current,
                last_actual_is_unavailable=last_is_unavailable,
            )
            cell["predicted"] = pred_obj

    # Populate actuals + compute prediction error
    for vc in classes:
        for c in countries:
            for atype in action_types:
                key = f"{vc}_{c.value}_{atype}"
                if key in current_actual_cutoffs:
                    d = current_actual_cutoffs[key]
                    cur_is_current, cur_is_unavailable = current_actual_flags.get(
                        key, (False, False)
                    )
                    cell = matrix[vc][c.value][atype]
                    cell["actual_date"] = d
                    if cur_is_current:
                        # Render "Current", never the bulletin-month sentinel date.
                        cell["formatted_actual"] = "Current"
                        cell["actual_is_current"] = True
                    elif cur_is_unavailable:
                        cell["formatted_actual"] = "Unavailable"
                        cell["actual_is_unavailable"] = True
                    else:
                        cell["formatted_actual"] = (
                            d.strftime("%d %b %Y") if d else None
                        )
                    # Compute error vs prediction and actual movement vs previous
                    last_d = last_actual_cutoffs.get(key)
                    last_is_current, last_is_unavailable = last_actual_flags.get(
                        key, (False, False)
                    )
                    pred_obj = cell.get("predicted")
                    # Only score error against a REAL actual date. A Current
                    # actual stores the bulletin-month sentinel and an Unavailable
                    # actual is NULL, so neither is a real cutoff to compare to.
                    cur_is_real = (
                        bool(d) and not cur_is_current and not cur_is_unavailable
                    )
                    last_is_real = (
                        bool(last_d)
                        and not last_is_current
                        and not last_is_unavailable
                    )
                    if cur_is_real and pred_obj and pred_obj.predicted_date:
                        err = (pred_obj.predicted_date - d).days
                        if err == 0:
                            cell["error_text"] = "exact"
                            cell["error_type"] = "success"
                        elif abs(err) <= 15:
                            cell["error_text"] = f"{'+'if err>0 else ''}{err}d"
                            cell["error_type"] = "success"
                        elif abs(err) <= 60:
                            cell["error_text"] = f"{'+'if err>0 else ''}{err}d"
                            cell["error_type"] = "warning"
                        else:
                            cell["error_text"] = f"{'+'if err>0 else ''}{err}d"
                            cell["error_type"] = "danger"
                    # Actual movement vs previous month. Difference two REAL dates
                    # only — never fabricate a numeric delta from a Current/
                    # Unavailable sentinel (the "↑ 1m" artifact). Current->Current
                    # shows NO movement; a real date becoming Current shows a
                    # non-numeric marker.
                    if cur_is_real and last_is_real:
                        actual_delta = (d - last_d).days
                        if actual_delta == 0:
                            cell["actual_move"] = "0"
                            cell["actual_move_type"] = "neutral"
                        elif actual_delta >= 30:
                            cell["actual_move"] = f"↑ {actual_delta // 30}m"
                            cell["actual_move_type"] = "positive"
                        elif actual_delta > 0:
                            cell["actual_move"] = f"↑ {actual_delta}d"
                            cell["actual_move_type"] = "positive"
                        elif actual_delta <= -30:
                            cell["actual_move"] = f"↓ {abs(actual_delta) // 30}m"
                            cell["actual_move_type"] = "negative"
                        else:
                            cell["actual_move"] = f"↓ {abs(actual_delta)}d"
                            cell["actual_move_type"] = "negative"
                    elif cur_is_current and last_is_real:
                        # Category just became Current — a genuine event, but there
                        # is no meaningful day-count, so show a plain marker.
                        cell["actual_move"] = "→ Current"
                        cell["actual_move_type"] = "neutral"

    # Convert to template rows
    table_rows = []
    for vc in classes:
        row_data = {
            "class": class_display.get(vc, vc),
            "class_full": vc,
            "countries": [],
        }
        for c in countries:
            cell = matrix[vc][c.value]
            row_data["countries"].append(
                {
                    "country": c,
                    "final_action": cell["final_action"],
                    "filing": cell["filing"],
                }
            )
        table_rows.append(row_data)

    formatted_title = (
        f"{category_label} Predictions for {target_date.strftime('%B %Y')}"
    )
    formatted_nav_prev = nav_prev.strftime("%b %Y") if nav_prev else None
    formatted_nav_next = nav_next.strftime("%b %Y") if nav_next else None

    context = {
        "knowledge_date": knowledge_date,
        "actual_bulletin": actual_bulletin,
        "target_month": target_date,
        "table_rows": table_rows,
        "classes": classes,
        "countries": list(countries),
        "nav_prev": nav_prev,
        "nav_next": nav_next,
        "formatted_title": formatted_title,
        "formatted_nav_prev": formatted_nav_prev,
        "formatted_nav_next": formatted_nav_next,
        "category": category,
        "category_label": category_label,
    }
    return render(request, "vqs/prediction_detail.html", context)


class _PredDisplay:
    """Lightweight container for template rendering of a prediction cell."""

    __slots__ = (
        "predicted_date",
        "formatted_date",
        "movement_delta",
        "movement_type",
        "accuracy_score",
        "confidence_low_fmt",
        "confidence_high_fmt",
        "ci_spread_days",
        "regime_label",
        "regime_color",
        "confidence_level",
        "is_experimental",
        "explanation_text",
        "top_experts",
        "movement_probability",
        "movement_prob_label",
        "movement_prob_color",
        "model_name",
        "prev_actual_fmt",
    )

    def __init__(self):
        self.predicted_date = None
        self.formatted_date = None
        self.movement_delta = None
        self.movement_type = None
        self.accuracy_score = None
        self.confidence_low_fmt = None
        self.confidence_high_fmt = None
        self.ci_spread_days = None
        self.regime_label = None
        self.regime_color = None
        self.confidence_level = None
        self.is_experimental = False
        self.explanation_text = None
        self.top_experts = None
        self.movement_probability = None
        self.movement_prob_label = None
        self.movement_prob_color = None
        self.model_name = "unknown"
        self.prev_actual_fmt = None


def _parse_regime_from_explanation(explanation: str | None) -> str | None:
    if not explanation:
        return None
    m = re.search(r"\*\*Regime: (\w+)\*\*", explanation)
    return m.group(1).upper() if m else None


def _make_prediction_display(
    pred: PredictionResult,
    last_actual_date: date | None,
    visa_class: str = "",
    country: int = 0,
    last_actual_is_current: bool = False,
    last_actual_is_unavailable: bool = False,
) -> _PredDisplay:
    obj = _PredDisplay()
    obj.predicted_date = pred.predicted_date
    obj.formatted_date = (
        pred.predicted_date.strftime("%d %b %Y") if pred.predicted_date else None
    )
    obj.model_name = pred.model_name

    # The previous-month actual is only a real anchor to diff against when it was
    # a real date. Current stores the bulletin-month sentinel and Unavailable
    # NULL, so differencing them fabricates a spurious movement delta.
    last_is_real = (
        bool(last_actual_date)
        and not last_actual_is_current
        and not last_actual_is_unavailable
    )
    if last_actual_is_current:
        obj.prev_actual_fmt = "Current"
    elif last_is_real:
        obj.prev_actual_fmt = last_actual_date.strftime("%d %b %Y")

    if last_is_real and pred.predicted_date:
        delta = (pred.predicted_date - last_actual_date).days
        if delta == 0:
            obj.movement_delta = "0"
            obj.movement_type = "neutral"
        elif delta >= 30:
            obj.movement_delta = f"↑ {delta // 30}m"
            obj.movement_type = "positive"
        elif delta > 0:
            obj.movement_delta = f"↑ {delta}d"
            obj.movement_type = "positive"
        elif delta <= -30:
            obj.movement_delta = f"↓ {abs(delta) // 30}m"
            obj.movement_type = "negative"
        else:
            obj.movement_delta = f"↓ {abs(delta)}d"
            obj.movement_type = "negative"

    # Confidence intervals (from stored predictions only)
    if pred.confidence_low and pred.confidence_high:
        obj.confidence_low_fmt = pred.confidence_low.strftime("%b %Y")
        obj.confidence_high_fmt = pred.confidence_high.strftime("%b %Y")
        obj.ci_spread_days = (pred.confidence_high - pred.confidence_low).days

    # Regime (parsed from explanation_markdown)
    regime_raw = _parse_regime_from_explanation(pred.explanation_markdown)
    if regime_raw and regime_raw in _REGIME_DISPLAY:
        obj.regime_label, obj.regime_color = _REGIME_DISPLAY[regime_raw]

    # Explanation text (strip markdown bold for cleaner display)
    if pred.explanation_markdown:
        obj.explanation_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", pred.explanation_markdown)

    # Movement probability badge (from stored 1m predictions for oversubscribed series)
    if pred.movement_probability is not None:
        p = pred.movement_probability
        obj.movement_probability = round(p * 100)
        if p < 0.40:
            obj.movement_prob_label = "Stable"
            obj.movement_prob_color = "success"
        elif p < 0.68:
            obj.movement_prob_label = "Watch"
            obj.movement_prob_color = "warning"
        else:
            obj.movement_prob_label = "Movement Likely"
            obj.movement_prob_color = "danger"

    # Top experts from expert_predictions dict
    if pred.expert_predictions and isinstance(pred.expert_predictions, dict):
        top = sorted(
            ((k, v.get("weight", 0)) for k, v in pred.expert_predictions.items() if isinstance(v, dict)),
            key=lambda x: -x[1],
        )[:4]
        if top:
            obj.top_experts = [(k, f"{v:.0%}") for k, v in top if v >= 0.05]

    # Confidence level and EB-4 experimental flag
    if visa_class in _EB4_CLASSES:
        obj.is_experimental = True
        obj.confidence_level = "Experimental"
    elif obj.ci_spread_days is not None:
        if obj.ci_spread_days <= 30:
            obj.confidence_level = "High"
        elif obj.ci_spread_days <= 90:
            obj.confidence_level = "Moderate"
        else:
            obj.confidence_level = "Low"
    elif pred.source == "stored":
        # Stored but no CI: moderately confident
        obj.confidence_level = "Moderate" if country in _OVERSUBSCRIBED_EB23_COUNTRIES else "High"

    return obj


def spaghetti_view(request):
    """View for spaghetti backtest visualization (static HTML generated by evaluate_model)."""
    import os

    from django.conf import settings

    file_path = os.path.join(settings.BASE_DIR, "webapp", "templates", "spaghetti.html")
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    return HttpResponse(content, content_type="text/html")


def metric_report_view(request):
    """View for static metric report (generated by generate_metric_report)."""
    import os

    from django.conf import settings

    try:
        # Prefer WORKSPACE_DIR (source tree) so we find the file written by generate_metric_report;
        # fall back to BASE_DIR for runserver/runfiles.
        base = getattr(settings, "WORKSPACE_DIR", None) or getattr(settings, "BASE_DIR", None)
        if base is None:
            return HttpResponse(
                "<h1>Configuration error</h1><p>BASE_DIR not set.</p>",
                content_type="text/html",
                status=500,
            )
        file_path = os.path.join(os.fspath(base), "webapp", "templates", "metric_report.html")
        if not os.path.isfile(file_path):
            return HttpResponse(
                "<h1>Metric report not generated yet</h1>"
                "<p>Run: <code>bazel run //scripts/vqs:generate_metric_report</code></p>",
                content_type="text/html",
                status=404,
            )
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        return HttpResponse(content, content_type="text/html")
    except OSError as e:
        logger.exception("Error serving metric report: %s", e)
        return HttpResponse(
            "<h1>Error loading metric report</h1><p>Could not read file.</p>",
            content_type="text/html",
            status=500,
        )
    except Exception as e:
        logger.exception("Unexpected error in metric_report_view: %s", e)
        return HttpResponse(
            "<h1>Error loading metric report</h1><p>An unexpected error occurred. Check server logs.</p>",
            content_type="text/html",
            status=500,
        )
