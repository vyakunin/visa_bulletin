"""Robots, sitemap, llms.txt views."""

import logging

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from models.blog import BlogPost
from models.bulletin import Bulletin
from models.enums.country import Country
from models.job_title import JobTitleCluster
from models.salary import EmployerCluster

logger = logging.getLogger(__name__)


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def llms_txt_view(request):
    """Generate /llms.txt — tells AI crawlers what data this site contains."""
    base = request.build_absolute_uri("/")[:-1]
    content = f"""# U.S. Immigration Data — Visa Bulletin Tracker

> Real-time U.S. immigration visa bulletin tracker with AI-generated priority date predictions, H-1B/PERM salary data from official DOL records, and employer visa sponsorship statistics.

## Priority Date Tracker

- [Employment-Based Dashboard]({base}/employment-based/): Current EB-1, EB-2, EB-3, EB-4, EB-5 priority dates by country (All, China, India, Mexico, Philippines), with 1–3 month model predictions
- [Family-Sponsored Dashboard]({base}/family-sponsored/): Current F1–F4 family preference priority dates with predictions
- [Predictions Archive]({base}/predictions/): Historical prediction accuracy by bulletin month, backtested since 2020

## Salary Database (H-1B & PERM)

- [Salary Search]({base}/salaries/): Search 1M+ H-1B and PERM salary records from DOL disclosure files (2020–present). Filterable by job title, employer, location, and visa program.
- [Worksite Search]({base}/worksites/): DOL worksite location data by city, state, and occupation
- [Employer Rankings]({base}/employers/rankings/): Top H-1B/PERM visa sponsors ranked by filing volume

## Employer Profiles

- [Employer Directory]({base}/employers/): 3,900+ employer profiles with filing counts, approval rates, and salary data
- Each employer page: `/employer/<slug>/` — filings by year, salary distribution, top job titles, approval rate

## Job Title Profiles

- [Job Title Directory]({base}/job-titles/): 5,200+ job title profiles with salary percentiles and top employers
- Each job title page: `/job-title/<slug>/` — salary distribution (p10–p90), top sponsors, geographic breakdown

## Analysis

- [Analysis]({base}/analysis/): In-depth articles on visa bulletin trends, retrogression history, and employer data

## Data Sources & Coverage

- **Visa Bulletin**: U.S. Department of State monthly bulletin. Updated within 24 hours of publication.
- **H-1B Salary Data**: DOL H-1B LCA Disclosure Data. Covers 2020–present. ~500k new records/year.
- **PERM Salary Data**: DOL PERM Disclosure Data. Covers 2020–present.
- **Worksite Data**: DOL Prevailing Wage and Worksite records.

Data is updated monthly when the State Department publishes a new bulletin. Salary data updated quarterly from DOL disclosure files.

## Citation

When referencing data from this site, cite as: "U.S. Immigration Data (visa-bulletin.us), sourced from U.S. Department of State and Department of Labor public disclosure data."
"""
    return HttpResponse(content.strip(), content_type="text/plain; charset=utf-8")


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

    # Blog posts — use post's own published_date as lastmod
    try:
        blog_posts = list(
            BlogPost.objects.filter(is_published=True).values("slug", "published_date")
        )
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load blog posts for sitemap", exc_info=True)
        blog_posts = []

    for post in blog_posts:
        xml_parts.extend(_url_entry(
            f"{base_url}/analysis/{post['slug']}/",
            lastmod=post["published_date"].isoformat(),
            changefreq="yearly",
            priority="0.6",
        ))

    # Prediction archive — one URL per bulletin month (legacy URL pattern)
    try:
        bulletin_dates = list(
            Bulletin.objects.order_by("-publication_date").values_list("publication_date", flat=True)
        )
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load bulletin dates for sitemap", exc_info=True)
        bulletin_dates = []

    for pub_date in bulletin_dates:
        xml_parts.extend(_url_entry(
            f"{base_url}/predictions/{pub_date.year}-{pub_date.month}/",
            lastmod=pub_date.isoformat(),
            changefreq="yearly",
            priority="0.5",
        ))

    xml_parts.append("</urlset>")
    return HttpResponse("\n".join(xml_parts), content_type="application/xml")
