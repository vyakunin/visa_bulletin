"""Priority-date HUB + per-EB-class ROLLUP landing pages.

Two SEO pages that sit ABOVE the per-(EB class x country) landing pages
(priority_date_landing.py) in the internal-link mesh and capture the
country-AGNOSTIC priority-date demand the per-country pages miss:

* ``/priority-date/``            — hub: every EB class x country at a glance.
* ``/priority-date/<eb_class>/`` — rollup: ONE EB class (EB-1/2/3) across all
  five chargeability areas (India, China, Mexico, Philippines, All Others).

Why they exist (GSC, 2026-06): the country-agnostic query "eb2 priority date"
pulled ~1.4k impressions/month at position ~5 onto the /salaries/ and
/employers/ list pages, which answer it terribly (0% CTR) — and nothing on the
site targeted the no-country query (only per-country pages existed). These pages
are the correct answer for it and let the list pages shed that mismatched,
never-clicked impression load.

Cheap to render (no live VQS solver): headline current cutoffs come from the
latest bulletin row via the shared helpers in priority_date_landing.py; trend
reuses the already-normalized aggregator arrays. Predictions are linked, not
embedded, to keep these pages fast and cacheable.
"""

import json

from django.http import Http404
from django.shortcuts import render

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from webapp.views.bulletin.priority_date_landing import (
    _EB_CLASSES,
    _latest_status,
    _series,
    _trend,
)

# Chargeability areas shown on a rollup, in search-interest order. India/China
# carry the real backlog demand; "All Others" (Country.ALL) is the ROW baseline.
_ROLLUP_COUNTRIES = (
    ("india", Country.INDIA),
    ("china", Country.CHINA),
    ("mexico", Country.MEXICO),
    ("philippines", Country.PHILIPPINES),
    ("all", Country.ALL),
)

# Per-country landing pages only exist for the four backlogged countries
# (see priority_date_landing._COUNTRIES); Country.ALL has none, so its row links
# to the full employment-based dashboard instead.
_HAS_LANDING = {"india", "china", "philippines", "mexico"}


def _country_label(country: Country) -> str:
    """Short display label; the ROW bucket reads "All Other Countries"."""
    if country == Country.ALL:
        return "All Other Countries"
    return Country(country.value).label.split(" (")[0]  # "China" not "China (mainland born)"


def _bulletin_month() -> str:
    latest = Bulletin.objects.order_by("-publication_date").first()
    return latest.publication_date.strftime("%B %Y") if latest else ""


def _faq_schema(faq: list[dict]) -> dict:
    return {
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


def _rollup_faq(eb_short: str, rows: list[dict], bulletin_month: str) -> list[dict]:
    statuses = ", ".join(f"{r['country']}: {r['final_status']['display']}" for r in rows)
    dated = [r for r in rows if r["final_status"]["status"] == "date"]
    longest = min(dated, key=lambda r: r["final_status"]["date_iso"]) if dated else None
    return [
        {
            "q": f"What is the {eb_short} priority date right now?",
            "a": (
                f"{eb_short} priority dates differ by country of chargeability. As of the "
                f"{bulletin_month} U.S. Visa Bulletin, the {eb_short} Final Action Dates are "
                f"{statuses}. The Final Action Date determines when the green card can be issued."
            ),
        },
        {
            "q": f"Which country has the longest {eb_short} green-card backlog?",
            "a": (
                f"{longest['country']} has the most retrogressed {eb_short} Final Action Date "
                f"({longest['final_status']['display']}), meaning the longest wait."
                if longest
                else f"Backlogs vary by country; see the table above for current {eb_short} cutoffs."
            ),
        },
        {
            "q": "What is the difference between Final Action and Dates for Filing?",
            "a": (
                "Final Action Dates govern when USCIS or the consulate can approve the green "
                "card. Dates for Filing govern when you may submit the application (Form I-485 / "
                "DS-260) and are usually ahead of Final Action Dates."
            ),
        },
    ]


def _hub_faq(bulletin_month: str) -> list[dict]:
    return [
        {
            "q": "What is a priority date?",
            "a": (
                "Your priority date is your place in the green-card line — the date your I-140 "
                "petition (or PERM labor certification) was filed. You can move forward with the "
                "green card once your priority date is earlier than the cutoff in the U.S. Visa "
                "Bulletin for your category and country."
            ),
        },
        {
            "q": "How do I find my priority date?",
            "a": (
                "It is printed on your I-140 (or I-130) approval notice, Form I-797. Compare it to "
                "the Final Action and Dates-for-Filing cutoffs for your employment preference "
                "(EB-1/EB-2/EB-3) and country of chargeability."
            ),
        },
        {
            "q": "How often do priority dates change?",
            "a": (
                f"The U.S. Department of State publishes a new Visa Bulletin every month; the "
                f"current edition is {bulletin_month}. Cutoffs can advance, hold, or retrogress "
                f"month to month with demand and per-country limits."
            ),
        },
    ]


def priority_date_eb_rollup_view(request, eb_class: str):
    """ONE EB class across all chargeability areas — targets generic "ebN priority date"."""
    eb = _EB_CLASSES.get((eb_class or "").lower())
    if eb is None:
        raise Http404("Unknown priority-date rollup")
    eb_short, eb_full = eb
    slug = eb_class.lower()

    rows: list[dict] = []
    any_data = False
    for ctry_slug, country in _ROLLUP_COUNTRIES:
        final_series = _series(country.value, ActionType.FINAL_ACTION.value, eb_full)
        filing_series = _series(country.value, ActionType.FILING.value, eb_full)
        final_status = _latest_status(country.value, ActionType.FINAL_ACTION.value, eb_full)
        filing_status = _latest_status(country.value, ActionType.FILING.value, eb_full)
        trend = _trend(final_status, final_series)
        any_data = any_data or final_series is not None or filing_series is not None
        rows.append(
            {
                "country": _country_label(country),
                "final_status": final_status,
                "filing_status": filing_status,
                "trend": trend,
                "url": (
                    f"/priority-date/{slug}/{ctry_slug}/"
                    if ctry_slug in _HAS_LANDING
                    else "/employment-based/"
                ),
            }
        )
    if not any_data:
        raise Http404("No data for this EB class")

    bulletin_month = _bulletin_month()
    page_heading = f"{eb_short} Priority Date by Country"
    page_title = f"{eb_short} Priority Date by Country — Current Visa Bulletin Cutoffs"
    page_description = (
        f"Current {eb_short} Final Action and Dates-for-Filing cutoffs for India, China, Mexico, "
        f"the Philippines, and all other countries, from the {bulletin_month} U.S. Visa Bulletin. "
        f"See which countries have the longest {eb_short} green-card backlog."
    )
    canonical_url = request.build_absolute_uri(request.path)
    faq = _rollup_faq(eb_short, rows, bulletin_month)
    sibling_classes = [
        {"label": short, "url": f"/priority-date/{sl}/"}
        for sl, (short, _full) in _EB_CLASSES.items()
        if sl != slug
    ]

    context = {
        "page_title": page_title,
        "page_heading": page_heading,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "structured_data": json.dumps(_faq_schema(faq)),
        "eb_short": eb_short,
        "eb_full": eb_full,
        "bulletin_month": bulletin_month,
        "rows": rows,
        "faq": faq,
        "sibling_classes": sibling_classes,
    }
    return render(request, "webapp/priority_date_rollup.html", context)


def priority_date_hub_view(request):
    """Index of every priority-date page — targets generic "priority date" / "visa bulletin priority date"."""
    bulletin_month = _bulletin_month()
    classes = []
    for slug, (eb_short, eb_full) in _EB_CLASSES.items():
        countries = [
            {"label": _country_label(country), "url": f"/priority-date/{slug}/{ctry_slug}/"}
            for ctry_slug, country in _ROLLUP_COUNTRIES
            if ctry_slug in _HAS_LANDING
        ]
        classes.append(
            {
                "eb_short": eb_short,
                "eb_full": eb_full,
                "url": f"/priority-date/{slug}/",
                "countries": countries,
            }
        )

    page_heading = "Green Card Priority Dates"
    page_title = "Green Card Priority Dates — EB-1, EB-2, EB-3 by Country (Visa Bulletin)"
    page_description = (
        f"Look up the current EB-1, EB-2, and EB-3 priority dates by country from the "
        f"{bulletin_month} U.S. Visa Bulletin: Final Action and Dates-for-Filing cutoffs for "
        f"India, China, Mexico, the Philippines, and all other countries."
    )
    canonical_url = request.build_absolute_uri(request.path)
    faq = _hub_faq(bulletin_month)

    context = {
        "page_title": page_title,
        "page_heading": page_heading,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "hreflang_en": canonical_url,
        "hreflang_es": request.build_absolute_uri("/es/priority-date/"),
        "structured_data": json.dumps(_faq_schema(faq)),
        "bulletin_month": bulletin_month,
        "classes": classes,
        "faq": faq,
    }
    return render(request, "webapp/priority_date_hub.html", context)
