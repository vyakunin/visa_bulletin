"""Robots, sitemap views."""

import logging

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from models.bulletin import Bulletin
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
        "Disallow: /api/",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def _get_latest_bulletin_date() -> str | None:
    """Return ISO date string of the latest bulletin publication, or None."""
    try:
        pub = Bulletin.objects.order_by("-publication_date").values_list(
            "publication_date", flat=True
        ).first()
        return pub.isoformat() if pub else None
    except (OperationalError, ProgrammingError):
        return None


def _url_entry(loc: str, lastmod: str | None = None, changefreq: str = "monthly", priority: str = "0.8") -> list[str]:
    parts = ["  <url>", f"    <loc>{loc}</loc>"]
    if lastmod:
        parts.append(f"    <lastmod>{lastmod}</lastmod>")
    parts.extend([f"    <changefreq>{changefreq}</changefreq>", f"    <priority>{priority}</priority>", "  </url>"])
    return parts


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def sitemap_view(request):
    """Generate XML sitemap."""
    base_url = request.build_absolute_uri("/")[:-1]
    bulletin_lastmod = _get_latest_bulletin_date()

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    # Static pages — all reflect data that changes on each pipeline refresh
    for path in ("/", "/salaries/", "/employers/", "/job-titles/", "/faq/", "/about/", "/contact/"):
        xml_parts.extend(_url_entry(f"{base_url}{path}", lastmod=bulletin_lastmod))

    # Category landing pages (updated when new bulletin arrives)
    categories = [
        ("employment_based", "employment-based"),
        ("family_sponsored", "family-sponsored"),
    ]
    for _, cat_slug in categories:
        xml_parts.extend(_url_entry(f"{base_url}/{cat_slug}/", lastmod=bulletin_lastmod))
        for c in Country:
            if c.value == Country.INVALID:
                continue
            slug = Country.slug_for_value(c.value)
            if slug:
                xml_parts.extend(_url_entry(f"{base_url}/{cat_slug}/{slug}/", lastmod=bulletin_lastmod))

    # Employer profile pages (top 10,000 by filing count)
    try:
        employer_clusters = list(
            EmployerCluster.objects.filter(
                slug__isnull=False,
                total_lca_count__gte=5,
            ).order_by("-total_lca_count")[:10000]
        )
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load employer clusters for sitemap", exc_info=True)
        employer_clusters = []

    for cluster in employer_clusters:
        xml_parts.extend(_url_entry(f"{base_url}/employer/{cluster.slug}/", lastmod=bulletin_lastmod))

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
        xml_parts.extend(_url_entry(f"{base_url}/job-title/{cluster.slug}/", lastmod=bulletin_lastmod))

    xml_parts.append("</urlset>")
    return HttpResponse("\n".join(xml_parts), content_type="application/xml")
