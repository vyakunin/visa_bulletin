"""Robots, sitemap, llms.txt views."""

import logging
from datetime import date, datetime

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.urls import reverse

from django_config.cache_utils import cache_page_skip_bots
from lib.utils.location_utils import US_STATES
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


def _get_latest_bulletin_fetched_at() -> datetime | None:
    """Return the most-recent bulletin's real ingest time (``fetched_at``).

    This is the dashboard/static/category/state ``lastmod`` source. We use
    ``fetched_at`` (``auto_now_add`` — when the row was actually created, a
    stable real timestamp) rather than ``publication_date`` (the future
    applies-to month, e.g. the July bulletin published mid-June): capping
    ``publication_date`` to today pins lastmod to *today, every day* until the
    applies-to month arrives — daily drift Google discounts. ``fetched_at`` is
    the truthful "when did this content last change" date. Ordered by
    ``publication_date`` so we get the newest bulletin's fetch time.
    """
    try:
        fetched = Bulletin.objects.order_by("-publication_date").values_list(
            "fetched_at", flat=True
        ).first()
        return fetched or None
    except (OperationalError, ProgrammingError):
        return None


def _lastmod_capped(value: date | datetime | None, today: date) -> str | None:
    """ISO ``lastmod`` for a page, never later than ``today``.

    Sitemap ``lastmod`` must be a real, trustworthy change date: never in the
    future (Google discounts future lastmod and, seeing it across many URLs,
    stops trusting the sitemap's lastmod entirely). Accepts a date or datetime
    (e.g. ``cluster.updated_at``) and clamps to today.
    """
    if value is None:
        return None
    d = value.date() if isinstance(value, datetime) else value
    return min(d, today).isoformat()


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
    today = date.today()
    # Static / category / state pages reflect the latest bulletin + pipeline
    # refresh. Use the bulletin's real ingest time (fetched_at), not its future
    # applies-to month capped to today — the latter would re-advertise "today" on
    # every crawl until the month arrives (drift Google discounts).
    bulletin_lastmod = _lastmod_capped(_get_latest_bulletin_fetched_at(), today)

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    # Static pages — all reflect data that changes on each pipeline refresh
    for path in ("/", "/salaries/", "/employers/", "/job-titles/", "/faq/", "/when-is-the-next-visa-bulletin/", "/about/", "/contact/", "/es/"):
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

    # Priority-date landing pages: EB-1/2/3 x India/China/Philippines/Mexico.
    # Mirrors the slug sets in webapp/views/bulletin/priority_date_landing.py.
    for eb_slug in ("eb1", "eb2", "eb3"):
        for ctry_slug in ("india", "china", "philippines", "mexico"):
            xml_parts.extend(_url_entry(
                f"{base_url}/priority-date/{eb_slug}/{ctry_slug}/",
                lastmod=bulletin_lastmod,
                changefreq="weekly",
                priority="0.7",
            ))

    # Evergreen per-month FORECAST page for the upcoming bulletin (latest + 1).
    # One rolling URL — it auto-advances when a new bulletin lands (and the old
    # month's URL 301s to the accuracy archive). Targets "visa bulletin {month}
    # {year} predictions" (the cluster we rank top-3 for). Mirrors
    # webapp/views/bulletin/prediction_month_forecast.py.
    try:
        from webapp.views.bulletin.prediction_month_forecast import (
            forecast_url_for,
            upcoming_forecast_month,
        )

        upcoming = upcoming_forecast_month()
    except (OperationalError, ProgrammingError):
        upcoming = None
    if upcoming is not None:
        xml_parts.extend(_url_entry(
            f"{base_url}{forecast_url_for(upcoming)}",
            lastmod=bulletin_lastmod,
            changefreq="weekly",
            priority="0.7",
        ))

    # Per-state salary landing pages (one per US state + DC).
    # Iterate the canonical US_STATES list so new entries appear automatically.
    for code, _name in US_STATES:
        xml_parts.extend(_url_entry(
            f"{base_url}/salaries/by-state/{code.lower()}/",
            lastmod=bulletin_lastmod,
            changefreq="weekly",
            priority="0.6",
        ))

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
        # Per-page truthful lastmod = when this cluster's stats were last
        # recomputed (updated_at), capped at today. Differentiated per page,
        # never future — a real freshness signal once the ingest path bumps
        # updated_at on each refresh (see Notion: sitemap-lastmod ticket).
        xml_parts.extend(_url_entry(
            f"{base_url}/employer/{cluster.slug}/",
            lastmod=_lastmod_capped(cluster.updated_at, today),
        ))

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
        xml_parts.extend(_url_entry(
            f"{base_url}/job-title/{cluster.slug}/",
            lastmod=_lastmod_capped(cluster.updated_at, today),
        ))

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
            lastmod=_lastmod_capped(post["published_date"], today),
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
        # The latest bulletin's publication_date is next month (future); cap so
        # /predictions/<latest>/ never advertises a future lastmod.
        xml_parts.extend(_url_entry(
            f"{base_url}/predictions/{pub_date.year}-{pub_date.month}/",
            lastmod=_lastmod_capped(pub_date, today),
            changefreq="yearly",
            priority="0.5",
        ))

    xml_parts.append("</urlset>")
    return HttpResponse("\n".join(xml_parts), content_type="application/xml")
