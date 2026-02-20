"""Static informational pages."""

import time

from django.http import HttpResponse
from django.shortcuts import render
from django.test import Client

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
    client = Client()
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
    return render(request, 'webapp/faq.html', {
        'page_title': 'Frequently Asked Questions - U.S. Immigration Data',
        'page_description': 'Common questions about priority dates, PERM processing, Final Action vs Filing Dates, and how the Visa Bulletin tracker works.',
    })


def about_view(request):
    """About page."""
    return render(request, 'webapp/about.html', {
        'page_title': 'About - U.S. Immigration Data',
        'page_description': 'Learn about the Visa Bulletin dashboard, data sources, projection methodology, and the team behind this community tool.',
    })


def contact_view(request):
    """Contact page."""
    return render(request, 'webapp/contact.html', {
        'page_title': 'Contact - U.S. Immigration Data',
        'page_description': 'Get in touch with questions, feedback, or bug reports about the Visa Bulletin tracker.',
    })
