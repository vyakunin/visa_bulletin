"""Shared queries for the "{job title} at {employer}" H-1B salary pages.

Used by BOTH the page view (``webapp/views/salary/h1b_salary_pair.py``) and the
sitemap (``webapp/views/seo/sitemaps.py``) so the view's 404-gate and the
sitemap's emit-set use the SAME qualification criterion — the sitemap never
lists a page that will 404.

This answers the high-intent query the existing pages don't cleanly serve:
**"{role} salary at {employer}" / "does {employer} sponsor H-1B for {role}" /
"{employer} {role} H-1B salary"**. The `/employer/<slug>/` profile is
employer-wide (all roles) and `/job-title/<slug>/` is role-wide (all employers);
neither is the specific (employer × role) salary answer — so this is a new page,
not a duplicate. All queries are index-served and scoped to a single
(employer cluster, job-title cluster) pair, so the page stays cheap and cacheable.
"""

from django.core.cache import cache
from django.db.models import Avg, Count

from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord

# A pair needs enough H-1B filings for a meaningful salary distribution (p25/
# median/p75) or it is a thin page. ≈506 (employer, role) pairs clear this on the
# current corpus. Both the view 404-gate and the sitemap emit-set apply it.
MIN_PAIR_FILINGS = 10

# Cap the sitemap emit-set (ordered by pair volume). Well above the current
# qualifying count; a guard against future growth ballooning the sitemap.
SITEMAP_MAX_PAGES = 5000

# The qualifying-pair set is a two-key GROUP BY over the whole H-1B corpus — too
# heavy to run per Googlebot sitemap fetch. Cache it; the refresh pipeline's
# ``cache.clear()`` on each ingest naturally refreshes it.
_QUALIFYING_PAIRS_CACHE_KEY = "h1b_salary_pair.qualifying_pairs.v1"
_QUALIFYING_PAIRS_TTL = 60 * 60 * 24


def _h1b_pair_base(emp_cluster_id: int, jt_cluster_id: int):
    """H-1B, salaried, real-employer records for one (employer, role) pair.

    Identical filter to the sitemap aggregate's per-group rows, so the view's
    per-pair count and the sitemap's per-pair count agree exactly.
    """
    return (
        SalaryRecord.objects.filter(
            visa_program=VisaProgram.H1B,
            employer__canonical_cluster_id=emp_cluster_id,
            job_title_entity__canonical_cluster_id=jt_cluster_id,
            wage_annual__isnull=False,
            wage_annual__gt=0,
        )
        .exclude(is_worksite=True)
        .exclude(employer_name="Unknown")
    )


def pair_h1b_filings(emp_cluster_id: int, jt_cluster_id: int) -> int:
    """H-1B filing count for one (employer, role) pair — the cheap 404-gate."""
    return _h1b_pair_base(emp_cluster_id, jt_cluster_id).count()


def pair_qualifies(filings: int) -> bool:
    """Whether a pair has a substantive enough salary distribution to publish."""
    return filings >= MIN_PAIR_FILINGS


def pair_filings_by_year(emp_cluster_id: int, jt_cluster_id: int) -> list[dict]:
    """H-1B filing count per fiscal year for the pair, oldest→newest."""
    return list(
        _h1b_pair_base(emp_cluster_id, jt_cluster_id)
        .values("fiscal_year")
        .annotate(filings=Count("id"))
        .order_by("fiscal_year")
    )


def pair_top_states(emp_cluster_id: int, jt_cluster_id: int, limit: int = 5) -> list[dict]:
    """Top worksite states (by H-1B filing count) for the pair."""
    return list(
        _h1b_pair_base(emp_cluster_id, jt_cluster_id)
        .exclude(worksite_state="")
        .values("worksite_state")
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .order_by("-filings")[:limit]
    )


def qualifying_pairs() -> list[tuple[str, str]]:
    """(employer-cluster slug, job-title-cluster slug) pairs whose page qualifies.

    Cached: the underlying aggregate is a two-key GROUP BY over the full H-1B
    corpus. Ordered by filing volume, capped to the highest-demand pairs. Both
    clusters must have a non-null, non-"unknown" slug (so the URL is linkable).
    """
    cached = cache.get(_QUALIFYING_PAIRS_CACHE_KEY)
    if cached is not None:
        return cached
    rows = (
        SalaryRecord.objects.filter(
            visa_program=VisaProgram.H1B,
            wage_annual__isnull=False,
            wage_annual__gt=0,
            employer__canonical_cluster__slug__isnull=False,
            job_title_entity__canonical_cluster__slug__isnull=False,
        )
        .exclude(is_worksite=True)
        .exclude(employer_name="Unknown")
        .exclude(employer__canonical_cluster__slug="unknown")
        .values(
            "employer__canonical_cluster__slug",
            "job_title_entity__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"))
        .filter(filings__gte=MIN_PAIR_FILINGS)
        .order_by("-filings")[:SITEMAP_MAX_PAGES]
    )
    pairs = [
        (
            r["employer__canonical_cluster__slug"],
            r["job_title_entity__canonical_cluster__slug"],
        )
        for r in rows
    ]
    cache.set(_QUALIFYING_PAIRS_CACHE_KEY, pairs, _QUALIFYING_PAIRS_TTL)
    return pairs
