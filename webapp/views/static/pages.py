"""Static informational pages."""

import time
from datetime import date

from django.http import HttpResponse
from django.shortcuts import render
from django.test import Client

from lib.business.bulletin.release_schedule import get_release_schedule

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
    """About page."""
    return render(
        request,
        "webapp/about.html",
        {
            "page_title": "About - U.S. Immigration Data",
            "page_description": "Learn about the Visa Bulletin dashboard, data sources, projection methodology, and the team behind this community tool.",
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
