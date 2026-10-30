"""Aggregations for the {occupation} H-1B/PERM salary landing pages.

Shared by BOTH the page view (``webapp/views/salary/occupation.py``) and the
sitemap (``webapp/views/seo/sitemaps.py``) so the view's 404-gate and the
sitemap's emit-set apply the SAME qualification criterion — the sitemap never
lists a page that will 404.

Records are scoped by SOC code (``soc_code__startswith`` over the occupation's
SOC-6 prefixes), the clean DOL-assigned occupation classification — NOT the
messy employer-typed ``job_title``/``soc_title``. Worksite-duplicate rows and the
``Unknown`` employer placeholder are excluded so filing counts aren't inflated.

Unlike the H-1B-sponsor pages, occupation pages span BOTH H-1B and PERM (the page
answers "{occupation} visa-sponsored salary" across all sponsorship), so the base
queryset is not program-filtered; callers narrow with ``apply_program_filter``.
"""

from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache, caches
from django.db.models import Avg, Count

from lib.business.salary.common_stats import (
    calculate_program_breakdown,
    calculate_salary_percentiles,
    calculate_yoy_trends,
)
from lib.business.salary.soc_occupations import Occupation, all_occupations
from models.salary import SalaryRecord

# Lower than the job-title pages' $30k floor: occupation pages include low-wage
# PERM occupations (cook, caregiver, truck driver) whose legitimate annualized
# wages sit below $30k. $12k drops clear hourly-miscoded outliers while keeping
# real low-wage filings.
MIN_OCCUPATION_SALARY = 12000
MAX_OCCUPATION_SALARY = 1000000

# A page needs a substantive dataset or it is a thin page (SEO negative). Both the
# view's 404-gate and the sitemap emit-set apply this identically.
MIN_OCCUPATION_FILINGS = 100

RECENT_YEARS = 5
TOP_EMPLOYERS = 20
TOP_STATES = 12
TOP_TITLES = 12

# The occupation filter is `soc_code LIKE '15-1252%'`, served by the
# `sr_soc_code_pattern` index (migration 0058). Only software-engineer (28% of the
# 1.66M-row / 1.24 GB table) and systems-analyst (5.8%) are broad enough that
# PostgreSQL correctly prefers a Parallel Seq Scan; the other 39 occupations match
# under 5% and index-scan. A cold page runs nine of these aggregates and took 65-209s
# under load on 2026-10-29, long enough to starve the gunicorn workers into 504s.
#
# `/h1b-salary/` is served by `cache_page_skip_bots`, so crawler traffic never reads
# the rendered-page cache. A request therefore reads the page's aggregates from the
# `aggregates` store, which scripts.salary.warm_occupations writes daily and which
# nothing evicts. The Redis entries below serve only an occupation the store lacks
# (a stack the warmer has not run on yet), and vb_redis evicts them within hours.
_STORED_PAGE_KEY = "occupation.page.v1.{slug}"
_STORED_QUALIFYING_SLUGS_KEY = "occupation.qualifying_slugs.v1"

_QUALIFYING_SLUGS_CACHE_KEY = "occupation_salary.qualifying_slugs.v1"
_FILING_COUNT_CACHE_KEY = "occupation_salary.filing_count.v1.{slug}"
_STATS_CACHE_KEY = "occupation_salary.stats.v1.{slug}"
_OCCUPATION_CACHE_TTL = 60 * 60 * 24


@dataclass
class OccupationStats:
    """Computed salary statistics for one occupation across visa sponsorship.

    List fields hold Django ``.values()`` rows (dicts at the ORM boundary, per
    code style). Empty/None means "not enough data" — the view gates on
    ``total_filings`` before building the rest.
    """

    total_filings: int = 0
    recent_filings: int = 0
    avg_salary: float = 0.0
    percentiles: dict = field(default_factory=dict)
    program: dict = field(default_factory=dict)
    top_employers: list[dict] = field(default_factory=list)
    top_states: list[dict] = field(default_factory=list)
    top_titles: list[dict] = field(default_factory=list)
    yoy: list[dict] = field(default_factory=list)


@dataclass
class StoredOccupationPage:
    """What one occupation page reads, as the warmer stores it."""

    filing_count: int
    stats: OccupationStats | None  # None for a thin occupation, which 404s


def _stored_page(slug: str) -> StoredOccupationPage | None:
    return caches[settings.AGGREGATES_CACHE_ALIAS].get(_STORED_PAGE_KEY.format(slug=slug))


def occupation_base_qs(occ: Occupation):
    """Salaried, real-employer records for one occupation (both H-1B and PERM).

    Identical filter on the view and sitemap paths so their counts agree.
    """
    return (
        SalaryRecord.objects.filter(
            occ.soc_q(),
            wage_annual__isnull=False,
            wage_annual__gte=MIN_OCCUPATION_SALARY,
            wage_annual__lte=MAX_OCCUPATION_SALARY,
        )
        .exclude(is_worksite=True)
        .exclude(employer_name="Unknown")
    )


def occupation_filing_count(occ: Occupation) -> int:
    """Total qualifying filings for the occupation — the 404-gate input."""
    stored = _stored_page(occ.slug)
    if stored is not None:
        return stored.filing_count
    key = _FILING_COUNT_CACHE_KEY.format(slug=occ.slug)
    cached = cache.get(key)
    if cached is not None:
        return cached
    count = occupation_base_qs(occ).count()
    cache.set(key, count, _OCCUPATION_CACHE_TTL)
    return count


def occupation_qualifies(filing_count: int) -> bool:
    """Whether an occupation has enough data to publish a non-thin page."""
    return filing_count >= MIN_OCCUPATION_FILINGS


def _top_employers(qs, limit: int = TOP_EMPLOYERS) -> list[dict]:
    """Top sponsoring employers (by filing count) for the occupation.

    Grouped by canonical employer cluster (with slug, for cross-link). Mean wage
    per group because PostgreSQL ``percentile_cont`` can't be a grouped annotation.
    """
    return list(
        qs.filter(employer__canonical_cluster__slug__isnull=False)
        .exclude(employer__canonical_cluster__slug="unknown")
        .values(
            "employer__canonical_cluster__canonical_name",
            "employer__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .order_by("-filings")[:limit]
    )


def _top_states(qs, limit: int = TOP_STATES) -> list[dict]:
    """Top worksite states by filing count, with mean wage."""
    return list(
        qs.exclude(worksite_state="")
        .values("worksite_state")
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .order_by("-filings")[:limit]
    )


def _top_titles(qs, limit: int = TOP_TITLES) -> list[dict]:
    """Top real job-title clusters filed under this occupation, with slug links.

    Surfaces the colloquial titles people file under the SOC code (e.g. a
    "Software Engineer" occupation page lists Senior Software Engineer, SDE II,
    Backend Engineer …), each linking to its existing /job-title/<slug>/ page.
    """
    return list(
        qs.filter(job_title_entity__canonical_cluster__slug__isnull=False)
        .values(
            "job_title_entity__canonical_cluster__canonical_title",
            "job_title_entity__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .order_by("-filings")[:limit]
    )


def get_occupation_stats(occ: Occupation) -> OccupationStats:
    """Full statistics for the occupation page. Assumes the gate already passed."""
    stored = _stored_page(occ.slug)
    if stored is not None and stored.stats is not None:
        return stored.stats
    key = _STATS_CACHE_KEY.format(slug=occ.slug)
    cached = cache.get(key)
    if cached is not None:
        return cached
    stats = _compute_occupation_stats(occ)
    cache.set(key, stats, _OCCUPATION_CACHE_TTL)
    return stats


def _compute_occupation_stats(occ: Occupation) -> OccupationStats:
    """Run every occupation aggregate against the database. Uncached."""
    from datetime import datetime

    qs = occupation_base_qs(occ)
    basic = qs.aggregate(total=Count("id"), avg=Avg("wage_annual"))
    total = basic["total"] or 0

    start_year = datetime.now().year - RECENT_YEARS
    recent_qs = qs.filter(fiscal_year__gte=start_year)

    return OccupationStats(
        total_filings=total,
        recent_filings=recent_qs.count(),
        avg_salary=float(basic["avg"] or 0),
        percentiles=calculate_salary_percentiles(qs),
        program=calculate_program_breakdown(qs),
        top_employers=_top_employers(qs),
        top_states=_top_states(qs),
        top_titles=_top_titles(qs),
        yoy=calculate_yoy_trends(qs),
    )


def qualifying_occupation_slugs() -> list[str]:
    """Occupation slugs whose page qualifies (>= MIN_OCCUPATION_FILINGS).

    Used by the sitemap so it never emits a URL that will 404.
    """
    stored = caches[settings.AGGREGATES_CACHE_ALIAS].get(_STORED_QUALIFYING_SLUGS_KEY)
    if stored is not None:
        return stored
    cached = cache.get(_QUALIFYING_SLUGS_CACHE_KEY)
    if cached is not None:
        return cached
    slugs = [
        occ.slug
        for occ in all_occupations()
        if occupation_qualifies(occupation_filing_count(occ))
    ]
    cache.set(_QUALIFYING_SLUGS_CACHE_KEY, slugs, _OCCUPATION_CACHE_TTL)
    return slugs


def occupation_page_stored(slug: str) -> bool:
    """Whether the warmer has stored this occupation's page, without computing it."""
    return _stored_page(slug) is not None


def warm_occupation_page(occ: Occupation) -> StoredOccupationPage:
    """Compute one occupation's page aggregates and store them. For warmers only."""
    filing_count = occupation_base_qs(occ).count()
    stats = _compute_occupation_stats(occ) if occupation_qualifies(filing_count) else None
    page = StoredOccupationPage(filing_count=filing_count, stats=stats)
    caches[settings.AGGREGATES_CACHE_ALIAS].set(_STORED_PAGE_KEY.format(slug=occ.slug), page)
    return page


def store_qualifying_occupation_slugs(slugs: list[str]) -> None:
    """Store the sitemap's occupation set. For warmers only."""
    caches[settings.AGGREGATES_CACHE_ALIAS].set(_STORED_QUALIFYING_SLUGS_KEY, slugs)
