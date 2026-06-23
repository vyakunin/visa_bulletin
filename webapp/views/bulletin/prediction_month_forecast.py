"""Per-month evergreen forecast landing pages.

SEO landing pages targeting the recurring high-intent query
"visa bulletin {month} {year} predictions" (the predictions cluster we already
rank top-3 for). Each page is a forward-looking FORECAST for ONE upcoming
Visa Bulletin month — the model's predicted Final Action / Filing cutoffs across
every employment-based and family-sponsored category and country, the predicted
month-over-month movement, an FAQ (FAQPage schema), and links into the live
dashboards + methodology.

This is distinct from /predictions/<category>/<year>-<month>/, which is the
backtest ACCURACY ARCHIVE (predicted vs actual) and 404s for any month without a
published bulletin. The forecast page covers exactly the gap that archive can't:
the *upcoming*, not-yet-published month people search for before the drop.

Deliberately CHEAP to render — NEVER calls the live VQS solver (the 23s path that
was explicitly removed from the FS pages, commit 4524f04). It reads only STORED
PredictedCutoff rows, which the hourly refresh publishes for the upcoming month
(latest bulletin month + 1) for every series. Once a target month's actual
bulletin lands, the URL 301-redirects to the accuracy archive (no duplicate page
for the same month).
"""

import json
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from models.bulletin import Bulletin
from models.enums.country import Country
from models.enums.family_preference import FamilyPreference
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedCutoff

# EB preference visa_class -> short display label (the stored visa_class values).
_EB_CLASSES = {"1st": "EB-1", "2nd": "EB-2", "3rd": "EB-3", "4th": "EB-4", "5th": "EB-5"}

# Countries shown in the forecast grid (the per-country-limited + "All" buckets).
_COUNTRIES = [
    Country.ALL,
    Country.CHINA,
    Country.INDIA,
    Country.MEXICO,
    Country.PHILIPPINES,
]

# The oversubscribed series that drive search demand — surfaced as headline cards.
_HEADLINE_SERIES = (
    ("2nd", Country.INDIA),
    ("3rd", Country.INDIA),
    ("2nd", Country.CHINA),
    ("3rd", Country.CHINA),
)

_FINAL = "final_action"
_FILING = "filing"

_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
_MONTH_SLUG_TO_NUM = {name: i + 1 for i, name in enumerate(_MONTH_NAMES)}


@dataclass
class _Forecast:
    """Predicted cutoff for one (visa_class, country, action_type) series."""

    display: str            # "October 1, 2020" | "Current" | "Unavailable" | "—"
    predicted_date: date | None
    movement: str | None    # "+45d", "-2m", "0", or None when not comparable
    movement_type: str      # "positive" | "negative" | "neutral" | "na"
    movement_prob: int | None = None   # 0-100, oversubscribed 1m series only
    movement_prob_label: str | None = None
    movement_prob_color: str | None = None


def _fmt(d: date | None) -> str:
    return d.strftime("%B %-d, %Y") if d else "—"


def _parse_slug(slug: str) -> date | None:
    """`october-2026` -> date(2026, 10, 1). None if not a valid month-year slug."""
    try:
        month_name, year_str = slug.rsplit("-", 1)
        month = _MONTH_SLUG_TO_NUM.get(month_name.lower())
        year = int(year_str)
    except (ValueError, AttributeError):
        return None
    if month is None or not (2000 <= year <= 2100):
        return None
    return date(year, month, 1)


def _movement(predicted: date | None, current: date | None) -> tuple[str | None, str]:
    """Predicted month-over-month movement vs the current (latest) actual cutoff."""
    if predicted is None or current is None:
        return None, "na"
    delta = (predicted - current).days
    if delta == 0:
        return "no change", "neutral"
    sign = "+" if delta > 0 else "−"
    mag = abs(delta)
    label = f"{sign}{mag // 30}m" if mag >= 30 else f"{sign}{mag}d"
    return label, ("positive" if delta > 0 else "negative")


def _prob_badge(p: float | None) -> tuple[int | None, str | None, str | None]:
    if p is None:
        return None, None, None
    pct = round(p * 100)
    if p < 0.40:
        return pct, "Stable", "success"
    if p < 0.68:
        return pct, "Watch", "warning"
    return pct, "Movement likely", "danger"


def _forecast_from_row(row: PredictedCutoff | None, current: VisaCutoffDate | None) -> _Forecast:
    """Build a display forecast from a stored prediction + the current actual baseline."""
    if row is None:
        return _Forecast(display="—", predicted_date=None, movement=None, movement_type="na")
    if row.predicted_date is not None:
        cur_date = current.cutoff_date if current and not current.is_unavailable else None
        move, mtype = _movement(row.predicted_date, cur_date)
        pct, plabel, pcolor = _prob_badge(row.movement_probability)
        return _Forecast(
            display=_fmt(row.predicted_date),
            predicted_date=row.predicted_date,
            movement=move,
            movement_type=mtype,
            movement_prob=pct,
            movement_prob_label=plabel,
            movement_prob_color=pcolor,
        )
    # Null prediction: model_name distinguishes Unavailable from Current/no-backlog.
    if (row.model_name or "") == "unavailable":
        return _Forecast(display="Unavailable", predicted_date=None, movement=None, movement_type="na")
    return _Forecast(display="Current", predicted_date=None, movement=None, movement_type="na")


def _load_current_actuals(bulletin: Bulletin) -> dict[tuple[str, int, str], VisaCutoffDate]:
    rows = VisaCutoffDate.objects.filter(bulletin=bulletin)
    return {(r.visa_class, r.country, r.action_type): r for r in rows}


def _load_stored_forecast(target: date) -> tuple[dict[tuple[str, int, str], PredictedCutoff], date | None]:
    """Stored predictions for target month, keyed by series. Latest prediction wins.

    Returns (by_key, knowledge_date). Ascending prediction_date so the newest
    overwrites earlier/longer-horizon rows (mirrors get_all_predictions_for_month).
    """
    rows = (
        PredictedCutoff.objects.filter(bulletin__target_bulletin_month=target)
        .select_related("bulletin")
        .order_by("bulletin__prediction_date")
    )
    by_key: dict[tuple[str, int, str], PredictedCutoff] = {}
    knowledge_date: date | None = None
    for r in rows:
        by_key[(r.visa_class, r.country, r.action_type)] = r
        knowledge_date = r.bulletin.prediction_date
    return by_key, knowledge_date


def _build_grid(
    class_map: dict[str, str],
    stored: dict[tuple[str, int, str], PredictedCutoff],
    actuals: dict[tuple[str, int, str], VisaCutoffDate],
) -> list[dict]:
    """One row per visa class; Final Action forecast cells in _COUNTRIES order."""
    rows = []
    for vc, short in class_map.items():
        cells = [
            _forecast_from_row(stored.get((vc, c.value, _FINAL)), actuals.get((vc, c.value, _FINAL)))
            for c in _COUNTRIES
        ]
        rows.append({"label": short, "cells": cells})
    return rows


def _headline_cards(
    stored: dict[tuple[str, int, str], PredictedCutoff],
    actuals: dict[tuple[str, int, str], VisaCutoffDate],
) -> list[dict]:
    cards = []
    for vc, country in _HEADLINE_SERIES:
        fa = _forecast_from_row(stored.get((vc, country.value, _FINAL)), actuals.get((vc, country.value, _FINAL)))
        filing = _forecast_from_row(stored.get((vc, country.value, _FILING)), actuals.get((vc, country.value, _FILING)))
        cards.append(
            {
                "label": f"{_EB_CLASSES[vc]} {Country(country.value).label.split(' (')[0]}",
                "final": fa,
                "filing": filing,
            }
        )
    return cards


def _faq(month_label: str, cards: list[dict]) -> list[dict]:
    india_eb2 = next((c for c in cards if c["label"] == "EB-2 India"), None)
    faq = [
        {
            "q": f"When does the {month_label} Visa Bulletin come out?",
            "a": (
                f"The U.S. Department of State publishes each Visa Bulletin in the middle "
                f"of the prior month — so the {month_label} bulletin is typically released "
                f"in the second or third week of the preceding month. This page is updated "
                f"with our model's forecast until the official numbers are published."
            ),
        },
    ]
    if india_eb2 and india_eb2["final"].predicted_date is not None:
        faq.append(
            {
                "q": f"Will EB-2 India advance in the {month_label} Visa Bulletin?",
                "a": (
                    f"Our model forecasts the EB-2 India Final Action Date for the "
                    f"{month_label} bulletin at {india_eb2['final'].display}"
                    + (
                        f" ({india_eb2['final'].movement} vs the current bulletin)."
                        if india_eb2["final"].movement
                        else "."
                    )
                    + " Oversubscribed categories move slowly and can retrogress; treat "
                    "this as a data-driven projection, not a guarantee."
                ),
            }
        )
    faq.extend(
        [
            {
                "q": "How accurate are these Visa Bulletin predictions?",
                "a": (
                    "The model is backtested against every published bulletin since 2020. "
                    "Accuracy varies by category — stable, advancing series are the most "
                    "predictable, while demand- and policy-driven movements (and "
                    "retrogressions) are inherently hard to call. See the methodology and "
                    "the historical accuracy archive for the track record."
                ),
            },
            {
                "q": "What is the difference between Final Action Dates and Dates for Filing?",
                "a": (
                    "Final Action Dates govern when USCIS or the consulate can approve the "
                    "green card. Dates for Filing govern when you may submit the application "
                    "(Form I-485 / DS-260), and are usually ahead of Final Action Dates."
                ),
            },
        ]
    )
    return faq


def upcoming_forecast_month() -> date | None:
    """The month the forecast page targets: latest published bulletin month + 1.

    Single source of truth for both the sitemap emitter and inbound links so the
    URL rolls forward automatically when a new bulletin lands.
    """
    from dateutil.relativedelta import relativedelta

    latest = (
        Bulletin.objects.order_by("-publication_date")
        .values_list("publication_date", flat=True)
        .first()
    )
    if latest is None:
        return None
    return latest.replace(day=1) + relativedelta(months=1)


def forecast_url_for(target: date) -> str:
    return f"/predictions/{_MONTH_NAMES[target.month - 1]}-{target.year}/"


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def prediction_month_forecast_view(request, slug: str) -> HttpResponse:
    """Render the evergreen forecast landing page for one upcoming bulletin month."""
    target = _parse_slug(slug)
    if target is None:
        raise Http404("Unknown forecast month")

    # Once the actual bulletin for this month exists, the forecast is history —
    # send the URL to the accuracy archive so there's no duplicate page.
    if Bulletin.objects.filter(publication_date=target).exists():
        return HttpResponsePermanentRedirect(
            f"/predictions/employment_based/{target.year}-{target.month}/"
        )

    latest = Bulletin.objects.order_by("-publication_date").first()
    if latest is None:
        raise Http404("No bulletins available")

    stored, knowledge_date = _load_stored_forecast(target)
    if not stored:
        # No stored forecast for this future month — never invoke the live solver
        # here, and never ship a thin page. Only the upcoming month is published.
        raise Http404(f"No forecast available for {target.strftime('%B %Y')}")

    actuals = _load_current_actuals(latest)
    month_label = target.strftime("%B %Y")
    current_label = latest.publication_date.strftime("%B %Y")

    fs_class_map = {f.value: f.label.split(":")[0] for f in FamilyPreference}
    country_headers = [Country(c.value).label.split(" (")[0] for c in _COUNTRIES]
    cards = _headline_cards(stored, actuals)
    eb_grid = _build_grid(_EB_CLASSES, stored, actuals)
    fs_grid = _build_grid(fs_class_map, stored, actuals)
    faq = _faq(month_label, cards)

    canonical_url = request.build_absolute_uri(request.path)
    page_title = f"{month_label} Visa Bulletin Predictions — Forecast"
    page_heading = f"{month_label} Visa Bulletin Predictions"
    page_description = (
        f"Our model's forecast for the {month_label} U.S. Visa Bulletin: predicted "
        f"EB-1/2/3 and family-sponsored Final Action & Filing dates for India, China, "
        f"Mexico, the Philippines, and all other countries."
    )

    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": i["q"], "acceptedAnswer": {"@type": "Answer", "text": i["a"]}}
                for i in faq
            ],
        }
    )

    context = {
        "page_title": page_title,
        "page_heading": page_heading,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "structured_data": structured_data,
        "month_label": month_label,
        "current_label": current_label,
        "knowledge_date": knowledge_date,
        "cards": cards,
        "eb_grid": eb_grid,
        "fs_grid": fs_grid,
        "country_headers": country_headers,
        "faq": faq,
    }
    return render(request, "webapp/prediction_month_forecast.html", context)
