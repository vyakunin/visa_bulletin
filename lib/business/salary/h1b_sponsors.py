"""Shared queries for the "Top H-1B sponsors for {job title}" landing pages.

Used by BOTH the page view (``webapp/views/salary/h1b_sponsors.py``) and the
sitemap (``webapp/views/seo/sitemaps.py``) so the view's 404-gate and the
sitemap's emit-set use the SAME qualification criterion — the sitemap never
lists a page that will 404.

All queries are index-served (``visa_program``, ``wage_annual``,
``job_title_entity``/``employer`` FKs) and scoped to a single role cluster on
the page path, so the page stays cheap and cacheable. The site already exposes
``/job-title/<slug>/`` (salary stats) and ``/salaries/by-state/<code>/``; this
page answers the distinct high-intent query those don't — "top H-1B sponsors
for {role}" / "which companies sponsor H-1B for {role}" — as a dedicated ranked
leaderboard.
"""

from django.core.cache import cache
from django.db.models import Avg, Count

from models.enums.visa_program import VisaProgram
from models.salary import SalaryRecord

# A page needs a substantive leaderboard or it is a thin/duplicate page (SEO
# negative): require at least this many H-1B filings AND this many distinct
# sponsoring employer clusters for the role/state. Both the view's 404-gate and
# the sitemap emit-set apply these identically.
MIN_H1B_FILINGS = 50
MIN_SPONSORS = 8

# How many employers to rank on the page.
TOP_SPONSORS = 25

# "Highest-paying" ranking: an employer must have at least this many H-1B
# filings in the state to be ranked by mean wage, so a single high outlier
# filing can't top the chart.
MIN_EMPLOYER_FILINGS_FOR_PAY = 5

# Cap the sitemap emit-set to the highest-volume roles (where the query has real
# search demand) and to keep the sitemap from ballooning.
SITEMAP_MAX_PAGES = 5000

# The qualifying-slug aggregate is a GROUP BY over the whole H-1B corpus — too
# heavy to run per Googlebot sitemap fetch (bots bypass the rendered-page
# cache). Cache the slug list so it is recomputed at most once per TTL; the
# refresh pipeline's ``cache.clear()`` on each ingest naturally refreshes it.
_QUALIFYING_SLUGS_CACHE_KEY = "h1b_sponsors.qualifying_slugs.v1"
_QUALIFYING_SLUGS_TTL = 60 * 60 * 24

# Same idea for the per-state variant ("Top H-1B sponsors in {state}"): cache the
# qualifying worksite-state set so the per-Googlebot sitemap fetch never reruns
# the full GROUP-BY-state aggregate.
_QUALIFYING_STATES_CACHE_KEY = "h1b_sponsors.qualifying_states.v1"


def _h1b_role_base(cluster_id: int | None):
    """H-1B, salaried, real-employer, slug-linkable records for the leaderboard.

    Identical filter on both paths so the view's per-cluster counts and the
    sitemap's per-cluster counts agree exactly. When ``cluster_id`` is None the
    queryset spans all roles (the sitemap aggregate); otherwise it is scoped to
    one job-title cluster.
    """
    qs = (
        SalaryRecord.objects.filter(
            visa_program=VisaProgram.H1B,
            employer__canonical_cluster__slug__isnull=False,
            wage_annual__isnull=False,
            wage_annual__gt=0,
        )
        .exclude(is_worksite=True)
        .exclude(employer_name="Unknown")
        .exclude(employer__canonical_cluster__slug="unknown")
    )
    if cluster_id is not None:
        qs = qs.filter(job_title_entity__canonical_cluster_id=cluster_id)
    return qs


def role_h1b_stats(cluster_id: int) -> tuple[int, int]:
    """(total H-1B filings, distinct sponsoring employer clusters) for a role.

    The cheap 404-gate the view applies before rendering — one indexed
    aggregate scoped to the cluster.
    """
    agg = _h1b_role_base(cluster_id).aggregate(
        filings=Count("id"),
        sponsors=Count("employer__canonical_cluster", distinct=True),
    )
    return agg["filings"] or 0, agg["sponsors"] or 0


def role_qualifies(filings: int, sponsors: int) -> bool:
    """Whether a role has a substantive enough H-1B leaderboard to publish."""
    return filings >= MIN_H1B_FILINGS and sponsors >= MIN_SPONSORS


def top_sponsors_for_cluster(cluster_id: int, limit: int = TOP_SPONSORS) -> list[dict]:
    """Top employers (by H-1B filing count) sponsoring this role, ranked.

    Each row: employer cluster name + slug, H-1B filing count, mean wage. Mean
    (not true median) per-group because PostgreSQL ``percentile_cont`` can't be
    a grouped annotation; the headline median for the whole role is computed
    separately via ``calculate_salary_percentiles``.
    """
    return list(
        _h1b_role_base(cluster_id)
        .values(
            "employer__canonical_cluster__canonical_name",
            "employer__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .order_by("-filings")[:limit]
    )


def top_states_for_cluster(cluster_id: int, limit: int = 5) -> list[dict]:
    """Top worksite states (by H-1B filing count) for this role."""
    return list(
        _h1b_role_base(cluster_id)
        .exclude(worksite_state="")
        .values("worksite_state")
        .annotate(filings=Count("id"))
        .order_by("-filings")[:limit]
    )


def qualifying_slugs() -> list[str]:
    """Job-title-cluster slugs whose H-1B sponsor page qualifies (for sitemap).

    Cached: the underlying aggregate is a GROUP BY over the full H-1B corpus.
    Ordered by filing volume, capped to the highest-demand roles.
    """
    cached = cache.get(_QUALIFYING_SLUGS_CACHE_KEY)
    if cached is not None:
        return cached
    rows = (
        _h1b_role_base(None)
        .filter(job_title_entity__canonical_cluster__slug__isnull=False)
        .values("job_title_entity__canonical_cluster__slug")
        .annotate(
            filings=Count("id"),
            sponsors=Count("employer__canonical_cluster", distinct=True),
        )
        .filter(filings__gte=MIN_H1B_FILINGS, sponsors__gte=MIN_SPONSORS)
        .order_by("-filings")[:SITEMAP_MAX_PAGES]
    )
    slugs = [r["job_title_entity__canonical_cluster__slug"] for r in rows]
    cache.set(_QUALIFYING_SLUGS_CACHE_KEY, slugs, _QUALIFYING_SLUGS_TTL)
    return slugs


# ---------------------------------------------------------------------------
# Per-state variant: "Top H-1B sponsors in {state}".
#
# A dedicated leaderboard for the distinct query "which companies sponsor H-1B
# in {state}" / "highest-paying H-1B employers in {state}" — a NEW page, not a
# re-angle of the existing /salaries/by-state/<code>/ page (that one ranks
# employers by filing volume across H-1B AND PERM with a state-overview intent;
# changing its angle would risk de-ranking a working page). Same shared 404-gate
# / sitemap-emit discipline as the per-role page above.
# ---------------------------------------------------------------------------


def _h1b_state_base(state_code: str | None):
    """H-1B, salaried, real-employer, slug-linkable records scoped to a state.

    Mirrors ``_h1b_role_base`` so the view's per-state counts and the sitemap's
    per-state counts agree exactly. ``None`` spans all states (the sitemap
    aggregate); a 2-letter uppercase code scopes to one worksite state.
    """
    qs = (
        SalaryRecord.objects.filter(
            visa_program=VisaProgram.H1B,
            employer__canonical_cluster__slug__isnull=False,
            wage_annual__isnull=False,
            wage_annual__gt=0,
        )
        .exclude(is_worksite=True)
        .exclude(employer_name="Unknown")
        .exclude(employer__canonical_cluster__slug="unknown")
    )
    if state_code is not None:
        qs = qs.filter(worksite_state=state_code)
    return qs


def state_h1b_stats(state_code: str) -> tuple[int, int]:
    """(total H-1B filings, distinct sponsoring employer clusters) for a state.

    The cheap 404-gate the state view applies before rendering. Qualification
    reuses ``role_qualifies`` (same MIN_H1B_FILINGS / MIN_SPONSORS thresholds).
    """
    agg = _h1b_state_base(state_code).aggregate(
        filings=Count("id"),
        sponsors=Count("employer__canonical_cluster", distinct=True),
    )
    return agg["filings"] or 0, agg["sponsors"] or 0


def top_sponsors_in_state(state_code: str, limit: int = TOP_SPONSORS) -> list[dict]:
    """Top employers by H-1B filing volume in this state, ranked."""
    return list(
        _h1b_state_base(state_code)
        .values(
            "employer__canonical_cluster__canonical_name",
            "employer__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .order_by("-filings")[:limit]
    )


def highest_paying_in_state(
    state_code: str,
    limit: int = 15,
    min_filings: int = MIN_EMPLOYER_FILINGS_FOR_PAY,
) -> list[dict]:
    """Highest-paying H-1B employers in this state, ranked by mean wage.

    ``min_filings`` (HAVING count) keeps a single outlier filing from topping
    the chart, so this is a stable answer to "highest-paying H-1B employers in
    {state}" rather than noise.
    """
    return list(
        _h1b_state_base(state_code)
        .values(
            "employer__canonical_cluster__canonical_name",
            "employer__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"), avg_salary=Avg("wage_annual"))
        .filter(filings__gte=min_filings)
        .order_by("-avg_salary")[:limit]
    )


def top_roles_in_state(state_code: str, limit: int = 10) -> list[dict]:
    """Top H-1B job-title clusters (by filing count) in this state."""
    return list(
        _h1b_state_base(state_code)
        .filter(job_title_entity__canonical_cluster__slug__isnull=False)
        .values(
            "job_title_entity__canonical_cluster__canonical_title",
            "job_title_entity__canonical_cluster__slug",
        )
        .annotate(filings=Count("id"))
        .order_by("-filings")[:limit]
    )


def qualifying_state_codes() -> list[str]:
    """Worksite-state codes whose H-1B sponsor page qualifies (for sitemap).

    Cached (the aggregate is a GROUP BY over the full H-1B corpus). Callers
    intersect with the canonical US_STATES list, so a non-standard
    ``worksite_state`` value here can never produce an emitted URL.
    """
    cached = cache.get(_QUALIFYING_STATES_CACHE_KEY)
    if cached is not None:
        return cached
    rows = (
        _h1b_state_base(None)
        .exclude(worksite_state="")
        .values("worksite_state")
        .annotate(
            filings=Count("id"),
            sponsors=Count("employer__canonical_cluster", distinct=True),
        )
        .filter(filings__gte=MIN_H1B_FILINGS, sponsors__gte=MIN_SPONSORS)
    )
    codes = [r["worksite_state"] for r in rows]
    cache.set(_QUALIFYING_STATES_CACHE_KEY, codes, _QUALIFYING_SLUGS_TTL)
    return codes
