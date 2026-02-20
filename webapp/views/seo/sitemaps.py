"""Robots and sitemap views."""

import logging

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from models.enums.country import Country
from models.job_title import JobTitleCluster
from models.salary import EmployerCluster

logger = logging.getLogger(__name__)


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def robots_view(request):
    """Generate robots.txt."""
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def sitemap_view(request):
    """Generate XML sitemap."""
    base_url = request.build_absolute_uri("/")[:-1]

    urls = [
        f"{base_url}/",
        f"{base_url}/salaries/",
        f"{base_url}/employers/",
        f"{base_url}/job-titles/",
        f"{base_url}/faq/",
        f"{base_url}/about/",
        f"{base_url}/contact/",
    ]

    # Category landing pages
    categories = [
        ("employment_based", "employment-based"),
        ("family_sponsored", "family-sponsored"),
    ]

    for _, cat_slug in categories:
        urls.append(f"{base_url}/{cat_slug}/")
        for c in Country:
            if c.value == Country.INVALID:
                continue
            slug = Country.slug_for_value(c.value)
            if slug:
                urls.append(f"{base_url}/{cat_slug}/{slug}/")

    # Employer profile pages (only include employers with 5+ filings)
    try:
        employer_clusters = list(
            EmployerCluster.objects.filter(
                slug__isnull=False,
                total_lca_count__gte=5,
            ).order_by("-total_lca_count")[:10000]  # Limit to top 10,000 employers
        )
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load employer clusters for sitemap", exc_info=True)
        employer_clusters = []

    for cluster in employer_clusters:
        urls.append(f"{base_url}/employer/{cluster.slug}/")

    # Job title profile pages (top 10,000 by filing count)
    try:
        job_title_clusters = list(
            JobTitleCluster.objects.filter(
                slug__isnull=False,
                total_filings__gte=10,
            ).order_by("-total_filings")[:10000]
        )
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load job title clusters for sitemap", exc_info=True)
        job_title_clusters = []

    for cluster in job_title_clusters:
        urls.append(f"{base_url}/job-title/{cluster.slug}/")

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for url in urls:
        xml_parts.extend(
            [
                "  <url>",
                f"    <loc>{url}</loc>",
                "    <changefreq>monthly</changefreq>",
                "    <priority>0.8</priority>",
                "  </url>",
            ]
        )

    xml_parts.append("</urlset>")
    return HttpResponse("\n".join(xml_parts), content_type="application/xml")
