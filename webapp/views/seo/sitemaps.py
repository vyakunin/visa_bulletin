"""Robots, sitemap, llms.txt views."""

import logging
from datetime import date, datetime

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.urls import reverse

from django_config.cache_utils import cache_page_all_agents
from lib.business.salary.h1b_salary_pair import qualifying_pairs
from lib.business.salary.h1b_sponsors import (
    qualifying_slugs,
    qualifying_state_codes,
)
from lib.business.salary.job_title_stats import INDEXABLE_MIN_FILINGS
from lib.business.salary.occupation_stats import qualifying_occupation_slugs
from lib.utils.location_utils import US_STATES
from models.blog import BlogPost
from models.bulletin import Bulletin
from models.enums.country import Country
from models.job_title import JobTitleCluster
from models.salary import EmployerCluster

logger = logging.getLogger(__name__)


@cache_page_all_agents(settings.CACHE_TIMEOUT)
def llms_txt_view(request):
    """Generate /llms.txt — tells AI crawlers what data this site contains."""
    base = request.build_absolute_uri("/")[:-1]
    content = f"""# U.S. Immigration Data — Visa Bulletin Tracker

> Real-time U.S. immigration visa bulletin tracker with AI-generated priority date predictions, H-1B/PERM salary data from official DOL records, and employer visa sponsorship statistics.

## Priority Date Tracker

- [Employment-Based Dashboard]({base}/employment-based/): Current EB-1, EB-2, EB-3, EB-4, EB-5 priority dates by country (All, China, India, Mexico, Philippines), with 1–3 month model predictions
- [Family-Sponsored Dashboard]({base}/family-sponsored/): Current F1–F4 family preference priority dates with predictions
- [Predictions Archive]({base}/predictions/): Historical prediction accuracy by bulletin month, backtested since 2016

## Salary Database (H-1B & PERM)

- [Salary Search]({base}/salaries/): Search 1M+ H-1B and PERM salary records from DOL disclosure files (2020–present). Filterable by job title, employer, location, and visa program.
- [Salary by Occupation]({base}/h1b-salary/): Median H-1B/PERM salary by occupation (Software Engineer, Data Scientist, Financial Analyst, …), keyed off the DOL SOC code, with percentiles, top sponsors, and states.
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


@cache_page_all_agents(settings.CACHE_TIMEOUT)
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


def build_sitemap_xml(base_url: str) -> str:
    """Render the full sitemap XML for ``base_url`` (no trailing slash).

    Split out of ``sitemap_view`` so the pre-rendered static file
    (``scripts/seo/render_sitemap.py``) and the Django fallback view are the
    same code — a divergence here would ship a sitemap that disagrees with the
    site's own 404-gates.

    This is the site's most expensive render, and the cost is NOT the 6.9k URL
    strings: it is the four whole-corpus aggregates below (``qualifying_pairs``,
    ``qualifying_slugs``, ``qualifying_state_codes``,
    ``qualifying_occupation_slugs``). Each is individually Redis-cached with a
    24h TTL, which was the original defense — but prod's Redis runs
    ``allkeys-lru`` at its 512 MB cap and evicts ~4k keys/hour, so those four
    keys disappear unpredictably and independently. Measured 2026-07-19: three
    of the four present, ``h1b_sponsors.qualifying_slugs.v1`` already evicted.
    A miss on any one of them puts a whole-corpus GROUP BY on the request path,
    which is where the ~21.7s crawler renders came from.

    So this function is meant to run on a SCHEDULE, not per request. Prefer the
    pre-rendered file; see the module docstring of the render script.
    """
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

    # Static pages — all reflect data that changes on each pipeline refresh.
    # /predictions/ is the prediction-accuracy archive INDEX (the per-month
    # /predictions/<y>-<m>/ pages are emitted separately below); it previously
    # had only its /es/ sibling listed, so the English index was orphaned.
    for path in ("/", "/salaries/", "/employers/", "/job-titles/", "/faq/", "/when-is-the-next-visa-bulletin/", "/about/", "/methodology/", "/corrections/", "/ai-citation/", "/contact/", "/predictions/", "/es/", "/es/faq/", "/es/predictions/", "/es/priority-date/"):
        xml_parts.extend(_url_entry(f"{base_url}{path}", lastmod=bulletin_lastmod))

    # Track-record pages (backtest visualisations) — reachable from the archive
    # index's "Model track record" section but previously in neither nav nor
    # sitemap. Low priority + yearly: they change only when the model is
    # re-backtested, not on each bulletin.
    for path in ("/spaghetti/", "/metric-report/"):
        xml_parts.extend(_url_entry(
            f"{base_url}{path}",
            lastmod=bulletin_lastmod,
            changefreq="yearly",
            priority="0.3",
        ))

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
            # Spanish sibling (/es/...) — same slug sets, mirrors
            # spanish_priority_date_landing_view's 404 gate.
            xml_parts.extend(_url_entry(
                f"{base_url}/es/priority-date/{eb_slug}/{ctry_slug}/",
                lastmod=bulletin_lastmod,
                changefreq="weekly",
                priority="0.6",
            ))

    # Priority-date HUB + per-EB-class rollups — country-agnostic "ebN priority
    # date" demand the per-country pages miss. Mirrors the slug sets in
    # webapp/views/bulletin/priority_date_rollup.py.
    xml_parts.extend(_url_entry(
        f"{base_url}/priority-date/",
        lastmod=bulletin_lastmod,
        changefreq="weekly",
        priority="0.7",
    ))
    # Interactive priority-date calculator (evergreen tool page). Mirrors the
    # route in webapp/urls.py / webapp/views/bulletin/priority_date_calculator.py.
    xml_parts.extend(_url_entry(
        f"{base_url}/priority-date-calculator/",
        lastmod=bulletin_lastmod,
        changefreq="weekly",
        priority="0.7",
    ))
    for eb_slug in ("eb1", "eb2", "eb3"):
        xml_parts.extend(_url_entry(
            f"{base_url}/priority-date/{eb_slug}/",
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

    # Job title profile pages — only above the thin-page gate (the view
    # noindexes anything below it, so the sitemap must not advertise those).
    try:
        job_title_clusters = list(
            JobTitleCluster.objects.filter(
                slug__isnull=False,
                total_filings__gte=INDEXABLE_MIN_FILINGS,
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

    # Top-H-1B-sponsors-per-role pages. Cached qualifying-slug set (shared with
    # the view's 404-gate) so we never list a page that 404s. lastmod = latest
    # ingest (the underlying DOL data's real change date).
    try:
        sponsor_slugs = qualifying_slugs()
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load H-1B sponsor slugs for sitemap", exc_info=True)
        sponsor_slugs = []

    for sponsor_slug in sponsor_slugs:
        xml_parts.extend(_url_entry(
            f"{base_url}/h1b-sponsors/{sponsor_slug}/",
            lastmod=bulletin_lastmod,
            changefreq="monthly",
            priority="0.6",
        ))

    # Top-H-1B-sponsors-per-STATE pages. Cached qualifying-state set (shared with
    # the view's 404-gate) intersected with the canonical US_STATES list so we
    # only ever emit valid, qualifying URLs (never a 404).
    try:
        qual_states = set(qualifying_state_codes())
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load H-1B sponsor states for sitemap", exc_info=True)
        qual_states = set()

    for code, _name in US_STATES:
        if code in qual_states:
            xml_parts.extend(_url_entry(
                f"{base_url}/h1b-sponsors/in/{code.lower()}/",
                lastmod=bulletin_lastmod,
                changefreq="monthly",
                priority="0.6",
            ))

    # Per-(employer × role) H-1B salary pages. Cached qualifying-pair set (shared
    # with the view's 404-gate) so we never list a page that 404s. lastmod =
    # latest ingest (the underlying DOL data's real change date).
    try:
        sponsor_pairs = qualifying_pairs()
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load H-1B salary pairs for sitemap", exc_info=True)
        sponsor_pairs = []

    for emp_slug, role_slug in sponsor_pairs:
        xml_parts.extend(_url_entry(
            f"{base_url}/h1b-salary/{emp_slug}/{role_slug}/",
            lastmod=bulletin_lastmod,
            changefreq="monthly",
            priority="0.5",
        ))

    # {occupation} salary pages (hub + per-occupation). Cached qualifying-slug set
    # (shared with the view's 404-gate) so we never list a thin page that 404s.
    xml_parts.extend(_url_entry(
        f"{base_url}/h1b-salary/",
        lastmod=bulletin_lastmod,
        changefreq="weekly",
        priority="0.6",
    ))
    try:
        occupation_slugs = qualifying_occupation_slugs()
    except (OperationalError, ProgrammingError):
        logger.error("Failed to load occupation slugs for sitemap", exc_info=True)
        occupation_slugs = []

    for occ_slug in occupation_slugs:
        xml_parts.extend(_url_entry(
            f"{base_url}/h1b-salary/{occ_slug}/",
            lastmod=bulletin_lastmod,
            changefreq="monthly",
            priority="0.6",
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

    from webapp.views.prediction_views import prediction_canonical_path

    for pub_date in bulletin_dates:
        # The latest bulletin's publication_date is next month (future); cap so
        # the archive URL never advertises a future lastmod. The canonical
        # employment_based archive is the keyword-rich monthname slug (see
        # prediction_canonical_path) — the SAME URL the forecast ranked on before
        # the drop — so the sitemap lists the slug (sitemap == canonical). The
        # bare-numeric and employment_based/<y>-<m>/ forms 301 here, never listed.
        xml_parts.extend(_url_entry(
            f"{base_url}{prediction_canonical_path('employment_based', pub_date.year, pub_date.month)}",
            lastmod=_lastmod_capped(pub_date, today),
            changefreq="yearly",
            priority="0.5",
        ))

    # Family-sponsored prediction archive — distinct content, self-canonical,
    # and previously orphaned from the sitemap. One URL per bulletin month.
    for pub_date in bulletin_dates:
        xml_parts.extend(_url_entry(
            f"{base_url}/predictions/family_sponsored/{pub_date.year}-{pub_date.month}/",
            lastmod=_lastmod_capped(pub_date, today),
            changefreq="yearly",
            priority="0.4",
        ))

    xml_parts.append("</urlset>")
    return "\n".join(xml_parts)


@cache_page_all_agents(settings.CACHE_TIMEOUT)
def sitemap_view(request):
    """Serve the XML sitemap — the FALLBACK path.

    In prod nginx serves a pre-rendered ``staticfiles/sitemap.xml`` off disk and
    only falls through here when that file is absent (a fresh stack that has not
    run the renderer yet). Keeping the view means a missing file degrades to a
    slow-but-correct sitemap rather than a 404 that would drop 6.9k URLs out of
    Google's index.
    """
    return HttpResponse(
        build_sitemap_xml(request.build_absolute_uri("/")[:-1]),
        content_type="application/xml",
    )
