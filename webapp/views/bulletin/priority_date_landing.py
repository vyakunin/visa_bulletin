"""Per-category x per-country priority-date landing pages.

SEO landing pages targeting high-intent queries like "eb2 india priority date",
"eb3 priority date china", etc. (real GSC demand — "eb2 priority date india"
pulls clicks at pos ~7-8). Each page is a focused answer for ONE employment
preference (EB-1/2/3) x ONE country (India/China/Philippines/Mexico): the
current Final Action + Dates-for-Filing cutoffs, the latest month-over-month
movement, a short recent-history table, an FAQ (FAQPage schema), and links into
the full interactive dashboard + salary data.

Deliberately CHEAP to render — no live VQS solver (the per-country dashboard's
filter-combo query cost is the heavy path; see Notion EB-dashboard latency
ticket). Headline current status comes from the latest bulletin row; trend +
history reuse the already-normalized aggregator arrays. Predictions are linked,
not embedded, to keep this page fast and cacheable.
"""

import json
from datetime import date

from django.http import Http404
from django.shortcuts import render

from lib.business.bulletin.cutoff_data_aggregator import (
    get_aggregated_visa_class_data,
)
from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.employment_preference import EmploymentPreference
from models.visa_cutoff_date import VisaCutoffDate

# slug -> (short label, full aggregated label). Restricted to EB-1/2/3, the
# preferences with real per-country priority-date search demand + non-thin data.
_EB_CLASSES = {
    "eb1": ("EB-1", "EB-1: Priority Workers"),
    "eb2": ("EB-2", "EB-2: Professionals with Advanced Degrees"),
    "eb3": ("EB-3", "EB-3: Skilled Workers, Professionals"),
}

# slug -> Country. The four countries with their own per-country backlog.
_COUNTRIES = {
    "india": Country.INDIA,
    "china": Country.CHINA,
    "philippines": Country.PHILIPPINES,
    "mexico": Country.MEXICO,
}


def _fmt_date(d: date | None) -> str | None:
    return d.strftime("%B %-d, %Y") if d else None


def _latest_status(country_value: int, action_type: str, full_label: str) -> dict:
    """Headline current cutoff for (EB class, country, action) from the latest bulletin.

    Reads the raw latest row so we can distinguish a real date from "Current"
    (C) / "Unavailable" (U) — a distinction the aggregator's date|None arrays
    lose.
    """
    latest_bulletin = Bulletin.objects.order_by("-publication_date").first()
    if latest_bulletin is None:
        return {"status": "unknown", "display": "No data", "date_iso": None}

    rows = VisaCutoffDate.objects.filter(
        bulletin=latest_bulletin,
        visa_category="employment_based",
        country=country_value,
        action_type=action_type,
    ).select_related("bulletin")

    for row in rows:
        if EmploymentPreference.normalize_for_display(row.visa_class) != full_label:
            continue
        if row.is_current:
            return {"status": "current", "display": "Current (no backlog)", "date_iso": None}
        if row.is_unavailable:
            return {"status": "unavailable", "display": "Unavailable", "date_iso": None}
        if row.cutoff_date:
            return {
                "status": "date",
                "display": _fmt_date(row.cutoff_date),
                "date_iso": row.cutoff_date.isoformat(),
            }
        return {"status": "unknown", "display": row.cutoff_value or "No data", "date_iso": None}
    return {"status": "unknown", "display": "No data", "date_iso": None}


def _series(country_value: int, action_type: str, full_label: str) -> dict | None:
    """The aggregated (sorted, normalized) series for one EB class + country."""
    data, has_data = get_aggregated_visa_class_data(
        "employment_based", country_value, action_type, date.today()
    )
    if not has_data:
        return None
    for entry in data:
        if entry["visa_class_label"] == full_label:
            return entry
    return None


def _trend(series: dict | None) -> dict:
    """Month-over-month movement of the Final Action cutoff (last two bulletins)."""
    if not series:
        return {"direction": "na", "text": "No recent data."}
    cutoffs = series["cutoff_dates"]
    if len(cutoffs) < 2:
        return {"direction": "na", "text": "Not enough history for a trend."}
    cur, prev = cutoffs[-1], cutoffs[-2]
    if cur is None or prev is None:
        return {"direction": "na", "text": "Cutoff moved to/from Current or Unavailable."}
    if cur > prev:
        days = (cur - prev).days
        return {"direction": "advanced", "text": f"advanced {days} days month-over-month"}
    if cur < prev:
        days = (prev - cur).days
        return {"direction": "retrogressed", "text": f"retrogressed {days} days month-over-month"}
    return {"direction": "unchanged", "text": "unchanged from the prior month"}


def _recent_history(series: dict | None, n: int = 6) -> list[dict]:
    """Last n (bulletin month, cutoff) points, newest first."""
    if not series:
        return []
    pairs = list(zip(series["dates"], series["cutoff_dates"]))[-n:]
    rows = []
    for bulletin_month, cutoff in reversed(pairs):
        rows.append(
            {
                "month": bulletin_month.strftime("%b %Y"),
                "cutoff": _fmt_date(cutoff) or "Current/Unavailable",
            }
        )
    return rows


def _faq(eb_short: str, country_display: str, final_status: dict, trend: dict) -> list[dict]:
    cur = final_status["display"]
    return [
        {
            "q": f"What is the {eb_short} {country_display} priority date right now?",
            "a": (
                f"As of the latest U.S. Visa Bulletin, the {eb_short} Final Action "
                f"Date for {country_display} is {cur}. Final Action Dates determine "
                f"when a green card can actually be issued."
            ),
        },
        {
            "q": f"Did the {eb_short} {country_display} cutoff move this month?",
            "a": (
                f"The {eb_short} {country_display} Final Action Date "
                f"{trend['text']}. Movement varies month to month with demand and "
                f"per-country limits."
            ),
        },
        {
            "q": "What is the difference between Final Action and Dates for Filing?",
            "a": (
                "Final Action Dates govern when USCIS or the consulate can approve "
                "the green card. Dates for Filing govern when you may submit the "
                "application (Form I-485 / DS-260). Filing dates are usually ahead "
                "of Final Action dates."
            ),
        },
    ]


def priority_date_landing_view(request, eb_class: str, country: str):
    """Render the per-EB-class x per-country priority-date landing page."""
    eb = _EB_CLASSES.get((eb_class or "").lower())
    ctry = _COUNTRIES.get((country or "").lower())
    if eb is None or ctry is None:
        raise Http404("Unknown priority-date landing page")

    eb_short, eb_full = eb
    country_display = Country(ctry.value).label.split(" (")[0]  # "China" not "China (mainland born)"

    final_series = _series(ctry.value, ActionType.FINAL_ACTION.value, eb_full)
    filing_series = _series(ctry.value, ActionType.FILING.value, eb_full)
    if final_series is None and filing_series is None:
        raise Http404("No data for this category/country")

    final_status = _latest_status(ctry.value, ActionType.FINAL_ACTION.value, eb_full)
    filing_status = _latest_status(ctry.value, ActionType.FILING.value, eb_full)
    trend = _trend(final_series)
    history = _recent_history(final_series)

    latest_bulletin = Bulletin.objects.order_by("-publication_date").first()
    bulletin_month = latest_bulletin.publication_date.strftime("%B %Y") if latest_bulletin else ""

    page_title = f"{eb_short} {country_display} Priority Date — Current Cutoff & Trend"
    page_heading = f"{eb_short} {country_display} Priority Date"
    page_description = (
        f"Current {eb_short} Final Action Date for {country_display}: "
        f"{final_status['display']} ({bulletin_month} Visa Bulletin). "
        f"See Dates for Filing, the latest month-over-month movement, and recent history."
    )
    canonical_url = request.build_absolute_uri(request.path)
    faq = _faq(eb_short, country_display, final_status, trend)

    structured_data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faq
        ],
    }

    # Internal-link mesh: sibling EB classes (same country) + same class (other countries).
    sibling_classes = [
        {"label": short, "url": f"/priority-date/{slug}/{country.lower()}/"}
        for slug, (short, _full) in _EB_CLASSES.items()
        if slug != eb_class.lower()
    ]
    sibling_countries = [
        {"label": Country(c.value).label.split(" (")[0], "url": f"/priority-date/{eb_class.lower()}/{slug}/"}
        for slug, c in _COUNTRIES.items()
        if slug != country.lower()
    ]

    context = {
        "page_title": page_title,
        "page_heading": page_heading,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "structured_data": json.dumps(structured_data),
        "eb_short": eb_short,
        "eb_full": eb_full,
        "country_display": country_display,
        "country_slug": country.lower(),
        "bulletin_month": bulletin_month,
        "final_status": final_status,
        "filing_status": filing_status,
        "trend": trend,
        "history": history,
        "faq": faq,
        "dashboard_url": f"/employment-based/{country.lower()}/",
        "sibling_classes": sibling_classes,
        "sibling_countries": sibling_countries,
    }
    return render(request, "webapp/priority_date_landing.html", context)
