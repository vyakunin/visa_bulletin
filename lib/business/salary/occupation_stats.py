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

from django.core.cache import cache
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

# Every aggregate below scans the whole salary_record heap: the occupation filter
# is `soc_code LIKE '15-1252%'` and the heaviest occupations match ~28% of the
# 1.6M-row / 1.19 GB table, so PostgreSQL correctly picks a Parallel Seq Scan and
# no index can change that. One page needs nine such scans, which is affordable
# once and not once per request — so the per-occupation results are cached, not
# just the qualifying-slug set. The occupation registry is a fixed 41 entries, so
# the key space is bounded and cannot pressure Redis's LRU the way an
# employer/job-title key space would.
#
# This matters because `/h1b-salary/` is served by `cache_page_skip_bots`: crawler
# traffic bypasses the rendered-page cache by design and would otherwise pay the
# full nine scans on every hit. Measured on prod 2026-08-09 before this cache:
# software-engineer 11.5s, data-scientist 7.9s, accountant 6.7s per request.
#
# The refresh pipeline's cache.clear() on each ingest refreshes all of them.
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
    """Total qualifying filings for the occupation — the 404-gate input.

    A full heap scan (see the cache note above), so it is cached per occupation.
    ``qualifying_occupation_slugs`` reads through the same entries, so a page
    view and the sitemap warm each other rather than each paying their own scan.
    """
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


def get_occupation_stats(occ: Occupation, years: int = RECENT_YEARS) -> OccupationStats:
    """Full statistics for the occupation page. Assumes the gate already passed.

    Cached per (occupation, years) — the eight aggregates below are eight full
    heap scans (see the cache note above), and the page's crawler traffic never
    reads the rendered-page cache.
    """
    key = f"{_STATS_CACHE_KEY.format(slug=occ.slug)}.{years}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    stats = _compute_occupation_stats(occ, years)
    cache.set(key, stats, _OCCUPATION_CACHE_TTL)
    return stats


def _compute_occupation_stats(occ: Occupation, years: int) -> OccupationStats:
    """Run every occupation aggregate against the database. Uncached."""
    from datetime import datetime

    qs = occupation_base_qs(occ)
    basic = qs.aggregate(total=Count("id"), avg=Avg("wage_annual"))
    total = basic["total"] or 0

    start_year = datetime.now().year - years
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

    Cached — the per-occupation counts are GROUP-BY aggregates over the corpus.
    Used by the sitemap so it never emits a URL that will 404.
    """
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
