"""Actual-pay (I-129) vs LCA-posted vs prevailing-wage three-way comparison.

The I-129 petition data (USCIS, obtained by Bloomberg via FOIA; FY2021-2024,
cap-subject lottery petitions only) carries the beneficiary's ACTUAL pay
(``pay_annual``) — a figure no free H-1B salary site surfaces. Joined to our LCA
``worksite_record`` on the DOL ETA case number, it yields, per occupation (and
later per employer), a comparison of three wages for the SAME matched petitions:

    actual individual pay  vs  the LCA-posted position wage  vs  the prevailing floor

We publish AGGREGATES ONLY, with small-n suppression (re-identification safety +
the FOIA-coverage caveat). The join is I-129 ``dol_eta_case_number`` =
``worksite_record.case_number`` (see the ``i129_petition_dol_eta_idx`` index).
There is no FK between the two tables (a single LCA case covers multiple
beneficiaries), so the join is expressed in raw SQL — which is also required for
``percentile_cont`` (no ORM aggregate).

Spec: docs/department_of_labor/I129_DATA_INTEGRATION_ASSESSMENT.md.
Attribution required on any surface: "sourced from USCIS, obtained by Bloomberg."
"""

import logging
from dataclasses import dataclass

from django.core.cache import cache
from django.db import connection

from lib.business.salary.soc_occupations import Occupation

logger = logging.getLogger(__name__)

# The matched-triple aggregate drives a parallel seq scan of i129_petition
# (373k rows) with a per-row index probe into worksite_record, so it costs
# ~1.7-2.0s regardless of how selective the occupation is (measured on prod
# 2026-08-09). `/h1b-salary/<slug>/` is served by `cache_page_skip_bots`, so the
# crawler traffic that is nearly all of its hits bypasses the rendered-page cache
# and would pay that on every request — hence a result cache here.
#
# Only the SOC (occupation) variant is cached: the occupation registry is a fixed
# 41 entries, whereas keying the employer variant by cluster would put thousands
# of entries into a Redis running allkeys-lru — the very pressure
# `cache_page_skip_bots` exists to avoid.
#
# The refresh pipeline's cache.clear() on each ingest refreshes these.
_SOC_COMPARISON_CACHE_KEY = "i129_pay_comparison.soc.v1.{slug}"
_SOC_COMPARISON_TTL = 60 * 60 * 24

# Publish a comparison only for cells with at least this many matched petitions
# (statistical stability + re-identification safety, aggregates-only rule).
MIN_COMPARISON_N = 50

# I-129 coverage window — surfaced verbatim in the on-page caveat.
FY_COVERAGE = "FY2021–FY2024"

# LCA case statuses whose posted wage is meaningful: Certified (1) +
# Certified-Withdrawn (4). Denied/withdrawn-before-certification wages are noise.
_CERTIFIED_STATUSES = (1, 4)

# The matched-triple aggregate. ``%s`` params: (soc_like_array,). The
# certified-status list is inlined (trusted constant). ``pay_annual`` is the
# canonical annualized actual pay; ``wage_annual`` the LCA-posted position wage;
# ``prevailing_wage`` the prevailing-wage floor. Ratios use a ±1% band so
# rounding on either side of an exactly-matched wage isn't miscounted.
_COMPARISON_SQL = """
WITH matched AS (
    SELECT i.pay_annual AS actual,
           w.wage_annual AS lca,
           w.prevailing_wage AS prev
    FROM i129_petition i
    JOIN worksite_record w ON w.case_number = i.dol_eta_case_number
    WHERE w.soc_code LIKE ANY(%s)
      AND w.case_status IN (1, 4)
      AND i.pay_annual IS NOT NULL AND i.pay_annual > 0
      AND w.wage_annual IS NOT NULL AND w.wage_annual > 0
)
SELECT
    count(*),
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY actual)),
    round(avg(actual)),
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY lca)),
    round(avg(lca)),
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY prev) FILTER (WHERE prev > 0)),
    round(100.0 * avg((actual > lca * 1.01)::int), 1),
    round(100.0 * avg((actual BETWEEN lca * 0.99 AND lca * 1.01)::int), 1),
    round(100.0 * avg((actual < lca * 0.99)::int), 1)
FROM matched
"""


@dataclass(frozen=True)
class PayComparison:
    """Aggregate actual-vs-posted-vs-prevailing wages for one matched cell.

    All wage figures are whole USD/year. ``n`` is the number of matched
    (I-129 ↔ certified LCA) petitions the aggregate is computed over.
    """

    n: int
    median_actual: int
    mean_actual: int
    median_lca: int
    mean_lca: int
    median_prevailing: int | None
    pct_above_lca: float  # actual > posted by >1%
    pct_at_lca: float  # actual within ±1% of posted
    pct_below_lca: float  # actual < posted by >1%
    fy_coverage: str = FY_COVERAGE

    @property
    def median_actual_vs_lca_pct(self) -> float:
        """Median actual as a signed % of the median LCA-posted wage."""
        if not self.median_lca:
            return 0.0
        return round((self.median_actual / self.median_lca - 1) * 100, 1)

    @property
    def mean_actual_vs_lca_pct(self) -> float:
        """Mean actual as a signed % of the mean LCA-posted wage (upper-tail gap)."""
        if not self.mean_lca:
            return 0.0
        return round((self.mean_actual / self.mean_lca - 1) * 100, 1)

    @property
    def median_actual_vs_prevailing_pct(self) -> float | None:
        """Median actual as a signed % above the prevailing-wage floor."""
        if not self.median_prevailing:
            return None
        return round((self.median_actual / self.median_prevailing - 1) * 100, 1)


def _run_comparison(where_sql: str, params: list) -> PayComparison | None:
    """Execute the matched-triple aggregate; return None if suppressed/empty.

    ``where_sql`` is spliced into the CTE's WHERE in place of the SOC clause by
    the public helpers, so callers never build SQL themselves.
    """
    sql = _COMPARISON_SQL.replace("w.soc_code LIKE ANY(%s)", where_sql)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    if not row or not row[0] or row[0] < MIN_COMPARISON_N:
        return None
    (n, med_actual, mean_actual, med_lca, mean_lca, med_prev, above, at, below) = row
    return PayComparison(
        n=int(n),
        median_actual=int(med_actual),
        mean_actual=int(mean_actual),
        median_lca=int(med_lca),
        mean_lca=int(mean_lca),
        median_prevailing=int(med_prev) if med_prev is not None else None,
        pct_above_lca=float(above),
        pct_at_lca=float(at),
        pct_below_lca=float(below),
    )


def get_soc_pay_comparison(occ: Occupation) -> PayComparison | None:
    """Three-way pay comparison for one occupation (matched over its SOC-6 set).

    Returns None when fewer than ``MIN_COMPARISON_N`` petitions match (thin cell
    suppressed) — the view then hides the section entirely. Cached per occupation
    (see the cache note above; the query costs ~1.7-2.0s whatever the occupation).

    The cached value is wrapped in a 1-tuple so a **suppressed** result — a
    legitimate ``None``, and the common case, since most occupations fall under
    ``MIN_COMPARISON_N`` — is distinguishable from a cache miss. Storing a bare
    ``None`` would leave exactly those occupations recomputing the most expensive
    query on the page on every single request.
    """
    like_params = [prefix + "%" for prefix in occ.soc6]
    if not like_params:
        return None
    key = _SOC_COMPARISON_CACHE_KEY.format(slug=occ.slug)
    cached = cache.get(key)
    if cached is not None:
        return cached[0]
    comparison = _run_comparison("w.soc_code LIKE ANY(%s)", [like_params])
    cache.set(key, (comparison,), _SOC_COMPARISON_TTL)
    return comparison


def soc_pay_comparison_cached(slug: str) -> bool:
    """Whether this occupation's SOC comparison is cached, without computing it.

    A suppressed result is a cached ``(None,)``, so this reports warm for it too —
    which is correct: the page renders without the section and pays no query.
    """
    return cache.get(_SOC_COMPARISON_CACHE_KEY.format(slug=slug)) is not None


def get_employer_pay_comparison(cluster) -> PayComparison | None:
    """Three-way pay comparison for one employer cluster.

    Scopes the matched-triple to petitions whose ``employer_cluster_id`` resolves to
    ``cluster`` (populated by lib/business/i129/employer_linker.py), joined to their
    certified LCA for the posted + prevailing wages. ``cluster`` is any object with an
    ``id`` (an ``EmployerCluster``). Returns None when fewer than ``MIN_COMPARISON_N``
    petitions match (thin cell suppressed → the view hides the section). Uses the
    ``employer_cluster_id`` index (migration 0053), so it's cheap inside the
    already-page-cached employer view.
    """
    cluster_id = getattr(cluster, "id", None)
    if cluster_id is None:
        return None
    return _run_comparison("i.employer_cluster_id = %s", [cluster_id])
