"""Static informational pages."""

import json
import time
from datetime import date

from django.http import HttpResponse
from django.shortcuts import render
from django.test import Client

from lib.business.bulletin.release_schedule import get_release_schedule

# Canonical author entity, reused across trust pages (E-E-A-T / GEO). A single
# named human with sameAs links is the signal Google's quality systems and
# LLM-citation pipelines look for on a YMYL (immigration) site; the site
# otherwise presents as anonymous ("built to help the community").
_AUTHOR_LD = {
    "@type": "Person",
    "name": "Vladimir Yakunin",
    "url": "https://visa-bulletin.us/about/",
    "email": "vyakunin@gmail.com",
    "sameAs": ["https://github.com/vyakunin"],
    "knowsAbout": [
        "U.S. Visa Bulletin",
        "immigration priority dates",
        "H-1B and PERM labor data",
        "data engineering",
    ],
}
_PUBLISHER_LD = {
    "@type": "Organization",
    "name": "U.S. Immigration Data (visa-bulletin.us)",
    "url": "https://visa-bulletin.us",
}

# Top-level pages the health check must fetch; each must return 200, <1s, non-empty content
HEALTH_CHECK_PATHS = ("/", "/salaries/", "/job-titles/", "/employers/")
HEALTH_MAX_SEC_PER_PAGE = 1.0
HEALTH_MIN_CONTENT_LENGTH = 500


def health_view(request):
    """
    Health check for load balancers and refresh orchestrator.

    Returns 200 only if main pages respond with status 200, load time <1s each,
    and meaningful non-empty content. Otherwise returns 503.
    """
    # Force Host=localhost so the self-probes pass DisallowedHost middleware
    # without leaking `testserver` into prod ALLOWED_HOSTS. Without this every
    # /health/ probe returns 400 → /health/ reports 503.
    client = Client(HTTP_HOST="localhost")
    for path in HEALTH_CHECK_PATHS:
        start = time.monotonic()
        try:
            response = client.get(path)
        except Exception:
            return HttpResponse(
                f"Health check failed: error fetching {path}",
                status=503,
                content_type="text/plain",
            )
        elapsed = time.monotonic() - start
        if response.status_code != 200:
            return HttpResponse(
                f"Health check failed: {path} returned {response.status_code}",
                status=503,
                content_type="text/plain",
            )
        if elapsed > HEALTH_MAX_SEC_PER_PAGE:
            return HttpResponse(
                f"Health check failed: {path} took {elapsed:.2f}s (max {HEALTH_MAX_SEC_PER_PAGE}s)",
                status=503,
                content_type="text/plain",
            )
        content = response.content
        if not content or len(content) < HEALTH_MIN_CONTENT_LENGTH:
            return HttpResponse(
                f"Health check failed: {path} content too short ({len(content) if content else 0} bytes)",
                status=503,
                content_type="text/plain",
            )
    return HttpResponse("OK", status=200)


def faq_view(request):
    """FAQ page."""
    return render(
        request,
        "webapp/faq.html",
        {
            "page_title": "Frequently Asked Questions - U.S. Immigration Data",
            "page_description": "Common questions about priority dates, PERM processing, Final Action vs Filing Dates, and how the Visa Bulletin tracker works.",
            "hreflang_en": request.build_absolute_uri("/faq/"),
            "hreflang_es": request.build_absolute_uri("/es/faq/"),
        },
    )


def next_bulletin_view(request):
    """"When does the next Visa Bulletin come out?" — projected release date + countdown.

    Estimates the next release from recent live-ingested bulletins (their
    ``fetched_at`` ≈ actual State Dept release date); see
    ``lib.business.bulletin.release_schedule``.
    """
    from webapp.views.bulletin.prediction_month_forecast import (
        forecast_url_for,
        upcoming_forecast_month,
    )

    schedule = get_release_schedule(today=date.today())
    upcoming = upcoming_forecast_month()
    # Month-specific title/description so the page matches the highest-volume
    # variant of the timing query ("visa bulletin <month> <year> when will it come
    # out") — the generic homepage was consolidating that intent (GSC, 2026-06).
    # Rolls forward each month with the governing bulletin (like the forecast page).
    gov_label = schedule.next_governing_month.strftime("%B %Y") if schedule else None
    if gov_label:
        page_title = f"When Will the {gov_label} Visa Bulletin Come Out? Expected Release Date"
        page_description = (
            f"The {gov_label} U.S. Visa Bulletin is expected to be released around "
            f"{schedule.next_release_estimate.strftime('%B %-d, %Y')}. See the projected "
            f"release date, a live countdown, and the recent release-date history."
        )
    else:
        page_title = "When Does the Next Visa Bulletin Come Out? (Release Schedule)"
        page_description = (
            "The next U.S. Visa Bulletin is released in the middle of each month "
            "for the following month. See the projected next release date, a live "
            "countdown, and the recent release-date history."
        )
    return render(
        request,
        "webapp/next_bulletin.html",
        {
            "page_title": page_title,
            "page_description": page_description,
            "canonical_url": request.build_absolute_uri("/when-is-the-next-visa-bulletin/"),
            "schedule": schedule,
            "forecast_url": forecast_url_for(upcoming) if upcoming else None,
            "forecast_month_label": upcoming.strftime("%B %Y") if upcoming else None,
        },
    )


def about_view(request):
    """About page.

    Carries the named-author Person JSON-LD (E-E-A-T): the human behind a YMYL
    immigration site is a first-class trust signal, and the page already names
    Vladimir Yakunin in prose — the structured data makes it machine-readable
    for Google + LLM-citation.
    """
    return render(
        request,
        "webapp/about.html",
        {
            "page_title": "About - U.S. Immigration Data",
            "page_description": "Learn about the Visa Bulletin dashboard, data sources, projection methodology, and the team behind this community tool.",
            "canonical_url": request.build_absolute_uri("/about/"),
            "structured_data": json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "AboutPage",
                    "name": "About U.S. Immigration Data",
                    "url": request.build_absolute_uri("/about/"),
                    "publisher": _PUBLISHER_LD,
                    "mainEntity": _AUTHOR_LD,
                }
            ),
        },
    )


def methodology_view(request):
    """Prediction methodology page.

    A dedicated, canonical trust surface (vs the existing methodology *blog
    post*, which is harder to find and not linked as a policy page). States in
    plain language how the Bulletin Forecast Model works, what the 80% range
    means, the data sources + update cadence, and — deliberately — an HONEST
    accuracy posture (no single vanity "% accurate" headline; error varies by
    category and horizon). This honesty is the E-E-A-T differentiator vs
    competitors that publish unaudited accuracy marketing.
    """
    return render(
        request,
        "webapp/methodology.html",
        {
            "page_title": "Prediction Methodology - How the Visa Bulletin Forecast Works",
            "page_description": (
                "How visa-bulletin.us predicts priority-date movement: the regime-aware "
                "near-term model, the longer-horizon gradient-boosted model, what the 80% "
                "range means, data sources, and how we measure our own accuracy."
            ),
            "canonical_url": request.build_absolute_uri("/methodology/"),
            "structured_data": json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "TechArticle",
                    "headline": "How the Visa Bulletin Forecast Model Works",
                    "description": (
                        "Methodology behind visa-bulletin.us priority-date predictions: "
                        "regime classification, gradient-boosted longer-horizon forecasts, "
                        "confidence ranges, data sources, and accuracy measurement."
                    ),
                    "url": request.build_absolute_uri("/methodology/"),
                    "author": _AUTHOR_LD,
                    "publisher": _PUBLISHER_LD,
                    "about": "U.S. Visa Bulletin priority date prediction methodology",
                }
            ),
        },
    )


def corrections_view(request):
    """Corrections policy page.

    A visible corrections/updates policy is a standard journalistic + YMYL
    trust marker (the kind of page Google's quality raters and LLM-citation
    pipelines weight). Short, static.
    """
    return render(
        request,
        "webapp/corrections.html",
        {
            "page_title": "Corrections & Updates Policy - U.S. Immigration Data",
            "page_description": (
                "How visa-bulletin.us handles errors and updates: how to report a "
                "correction, how quickly we fix data issues, and how pages are dated."
            ),
            "canonical_url": request.build_absolute_uri("/corrections/"),
            "structured_data": json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": "Corrections & Updates Policy",
                    "url": request.build_absolute_uri("/corrections/"),
                    "publisher": _PUBLISHER_LD,
                }
            ),
        },
    )


def ai_citation_view(request):
    """AI citation & content-reuse policy (GEO).

    Explicitly welcomes AI Overviews / LLM assistants to cite the site with
    attribution — LLMs increasingly answer "visa bulletin predictions" queries,
    and being the clearly-citable source with unambiguous terms is a distribution
    channel. Also disambiguates licensing: the *code* is PolyForm Noncommercial;
    this page defines the terms for citing the site's *data and content*.
    """
    return render(
        request,
        "webapp/ai_citation.html",
        {
            "page_title": "AI Citation & Content Use Policy - U.S. Immigration Data",
            "page_description": (
                "How AI assistants and publishers may cite visa-bulletin.us: attribution "
                "terms, what may be quoted, and the distinction between our open data and "
                "the site's source-code license."
            ),
            "canonical_url": request.build_absolute_uri("/ai-citation/"),
            "structured_data": json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": "AI Citation & Content Use Policy",
                    "url": request.build_absolute_uri("/ai-citation/"),
                    "publisher": _PUBLISHER_LD,
                }
            ),
        },
    )


def contact_view(request):
    """Contact page."""
    return render(
        request,
        "webapp/contact.html",
        {
            "page_title": "Contact - U.S. Immigration Data",
            "page_description": "Get in touch with questions, feedback, or bug reports about the Visa Bulletin tracker.",
        },
    )


def privacy_view(request):
    """Privacy Policy page.

    Required by ad networks (AdSense, Mediavine) and by GDPR/CCPA — discloses the
    analytics (GoatCounter, GA4) and advertising (AdSense + DART) cookies, the
    affiliate/FTC disclosure, and the contact address.
    """
    return render(
        request,
        "webapp/privacy.html",
        {
            "page_title": "Privacy Policy - U.S. Immigration Data",
            "page_description": "How visa-bulletin.us handles your data: analytics (GoatCounter, GA4), advertising cookies (Google AdSense, DART), affiliate disclosure, and your privacy choices.",
            "canonical_url": request.build_absolute_uri("/privacy/"),
        },
    )


def spanish_landing_view(request):
    """Spanish-language landing page.

    Per GSC baseline 2026-05-16 (see [[project_gsc_seo_baseline]]), Spanish
    queries like "boletin de visas" + month variants pull ~3-5k impressions/4w
    at ~0.13% CTR with no Spanish content on the site. Full Django i18n is
    days of work; this single page + reciprocal hreflang on `/` is the quick
    win that converts the Spanish search demand. Data widgets (dashboard,
    salaries, predictions) stay English — the page links to them with a clear
    note that the live data is in English.
    """
    return render(
        request,
        "webapp/spanish_landing.html",
        {
            "page_title": "Boletín de Visas — Fechas de Prioridad, Predicciones y Análisis | visa-bulletin.us",
            "page_description": (
                "Boletín de visas mensual del Departamento de Estado de EE.UU. en español: "
                "fechas de prioridad EB-1/2/3/4/5 y F1-F4, predicciones del modelo Bulletin "
                "Forecast, y guía para solicitantes I-485 (USCIS)."
            ),
        },
    )
