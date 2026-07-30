"""H-1B actual pay by beneficiary demographic, adjusted for occupational sorting.

The I-129 petition data (USCIS, obtained by Bloomberg via FOIA; FY2021-2024,
cap-subject lottery petitions only) carries the beneficiary's ACTUAL pay together
with country of birth, education level, field of study and gender — a join no free
H-1B salary site has. The obvious surface, "median pay by country", is also the
dishonest one: most of a raw demographic pay gap is people being in DIFFERENT JOBS,
not being paid differently for the same job.

Our own published decomposition established this for gender — the raw ~4% H-1B gap
is +0.29% mean / -0.85% median once you compare within job title over 388 strata,
i.e. it vanishes (see /analysis/h1b-gender-pay-gap-decomposition/ and
docs/department_of_labor/i129_stories/RIGOR_REVIEW.md). So any demographic pay figure
we publish carries the within-occupation number next to the raw one. This module
computes both, and refuses to compute the adjusted one when the overlap is too thin
to mean anything.

Country of birth does NOT behave like gender, which is what makes it worth a page:
measured FY21-24, China's raw +$27,315 median premium falls to +$8,896 within job
title — about two thirds is sorting, but a real residual survives. India's small
-$2,685 raw gap is barely sorting at all (-$2,411 adjusted).

THE PITFALL THIS MODULE IS BUILT AROUND: pooling the ~125k petitions with a BLANK
job_title fabricates a within-occupation gap (RIGOR_REVIEW.md:216 — it faked a +3.1%
gender gap that does not exist). Every figure here is therefore scoped to petitions
that HAVE a job title, so the raw and adjusted numbers share one denominator and are
directly comparable. That is a deliberate narrowing, not an oversight; surfaces must
report ``n`` so the reader sees the base.

Aggregates only, with small-n suppression — the FOIA coverage caveat and the
re-identification rule both apply. Attribution required on any surface:
"sourced from USCIS, obtained by Bloomberg."
"""

import logging
from dataclasses import dataclass
from enum import IntEnum, unique

from django.db import connection

logger = logging.getLogger(__name__)

# A dimension value needs this many petitions (with pay AND a job title) before it
# gets a row at all. Matches the indexable-page floor used on /job-title/.
MIN_VALUE_N = 100

# A job title becomes a comparison stratum at this many petitions. Below it the
# stratum median is too noisy to subtract anything from.
MIN_STRATUM_N = 100

# A (dimension value x job title) cell must have this many petitions to contribute
# to the adjusted figure. Keeps one outlier salary out of a stratum's contribution.
MIN_CELL_N = 30

# The adjusted figure is published only when the qualifying cells cover at least this
# many petitions AND this share of the value's own petitions. Both matter: a large
# absolute base can still be unrepresentative, and a high share of a tiny base is
# noise. Measured FY21-24, this admits IND (91,314 / 99.9%) and CHN (16,343 / 93.8%)
# and correctly withholds TWN (471) and KOR (398), whose adjusted figures swing
# wildly against their raw ones.
MIN_ADJUSTED_N = 500
MIN_ADJUSTED_COVERAGE_PCT = 25.0

# I-129 coverage window — surfaced verbatim in the on-page caveat.
FY_COVERAGE = "FY2021–FY2024"


@unique
class PayDimension(IntEnum):
    """A beneficiary attribute we can break actual pay down by."""

    INVALID = 0
    COUNTRY_OF_BIRTH = 1
    EDUCATION_LEVEL = 2
    FIELD_OF_STUDY = 3
    GENDER = 4

    @classmethod
    def from_str(cls, raw: str | None) -> "PayDimension":
        return _DIMENSION_LOOKUP.get((raw or "").strip().lower(), cls.INVALID)

    @property
    def slug(self) -> str:
        return self.name.lower()

    @property
    def column(self) -> str:
        """The i129_petition column this dimension groups by.

        Spliced into SQL, so it must never come from user input — it is derived
        from the enum member, which is the whole reason this is an enum.
        """
        return _DIMENSION_COLUMNS[self]

    @property
    def label(self) -> str:
        return _DIMENSION_LABELS[self]


_DIMENSION_COLUMNS = {
    PayDimension.COUNTRY_OF_BIRTH: "country_of_birth",
    PayDimension.EDUCATION_LEVEL: "ed_level",
    PayDimension.FIELD_OF_STUDY: "field_of_study",
    PayDimension.GENDER: "gender",
}

_DIMENSION_LABELS = {
    PayDimension.COUNTRY_OF_BIRTH: "Country of birth",
    PayDimension.EDUCATION_LEVEL: "Education level",
    PayDimension.FIELD_OF_STUDY: "Field of study",
    PayDimension.GENDER: "Gender",
}

_DIMENSION_LOOKUP = {
    "country_of_birth": PayDimension.COUNTRY_OF_BIRTH,
    "country": PayDimension.COUNTRY_OF_BIRTH,
    "education_level": PayDimension.EDUCATION_LEVEL,
    "education": PayDimension.EDUCATION_LEVEL,
    "field_of_study": PayDimension.FIELD_OF_STUDY,
    "field": PayDimension.FIELD_OF_STUDY,
    "gender": PayDimension.GENDER,
}


@dataclass(frozen=True)
class DemographicPayCell:
    """Actual-pay figures for one value of a demographic dimension.

    ``raw_gap`` and ``within_occupation_gap`` are whole USD/year, signed, both
    measured against the same population median. ``within_occupation_gap`` is None
    when the value has too little cross-occupation overlap to adjust honestly — a
    surface must then show the raw figure WITHOUT implying it is a like-for-like
    comparison.
    """

    value: str
    n: int
    median_pay: int
    mean_pay: int
    raw_gap: int
    within_occupation_gap: int | None
    adjusted_n: int
    strata_count: int

    @property
    def adjusted_coverage_pct(self) -> float:
        """Share of this value's petitions that entered the adjusted figure."""
        return round(100.0 * self.adjusted_n / self.n, 1) if self.n else 0.0

    @property
    def sorting_share_pct(self) -> float | None:
        """How much of the raw gap is explained by occupational sorting.

        100% means the gap vanishes once you compare within job title (the gender
        result). None when there is no adjusted figure, or when the raw gap is too
        small for the ratio to be meaningful.
        """
        if self.within_occupation_gap is None or abs(self.raw_gap) < 1000:
            return None
        explained = 1.0 - (self.within_occupation_gap / self.raw_gap)
        return round(100.0 * explained, 1)


@dataclass(frozen=True)
class DemographicPayBreakdown:
    """One dimension's full breakdown, ordered by petition count descending."""

    dimension: PayDimension
    overall_n: int
    overall_median: int
    cells: tuple[DemographicPayCell, ...]
    fy_coverage: str = FY_COVERAGE

    @property
    def adjusted_cells(self) -> tuple[DemographicPayCell, ...]:
        """Only the values whose within-occupation figure survived suppression."""
        return tuple(c for c in self.cells if c.within_occupation_gap is not None)


# Per-value raw figures plus a stratum-weighted within-occupation gap, in one pass.
#
# `scoped` is the shared population: petitions with pay AND a job title (see the
# module docstring on the blank-title pitfall). `strata` are the job titles big
# enough to compare within. `cells` are the (value x title) intersections big enough
# to contribute. `adj` weights each cell's distance from its own stratum median by
# the cell size, so a value is compared against the same job mix it actually works in.
#
# `{col}` is substituted from PayDimension.column — an enum-derived constant, never
# user input. Every other value is a bound parameter.
_BREAKDOWN_SQL = """
WITH scoped AS (
    SELECT {col} AS val, job_title, pay_annual
    FROM i129_petition
    WHERE pay_annual IS NOT NULL AND pay_annual > 0
      AND {col} <> '' AND job_title <> ''
      {extra_where}
),
overall AS (
    SELECT count(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY pay_annual) AS med
    FROM scoped
),
strata AS (
    SELECT job_title,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY pay_annual) AS med
    FROM scoped GROUP BY job_title HAVING count(*) >= %s
),
raw AS (
    SELECT val, count(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY pay_annual) AS med,
           avg(pay_annual) AS mean
    FROM scoped GROUP BY val HAVING count(*) >= %s
),
cells AS (
    SELECT s.val, s.job_title, count(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY s.pay_annual) AS med
    FROM scoped s JOIN strata t ON t.job_title = s.job_title
    GROUP BY s.val, s.job_title HAVING count(*) >= %s
),
adj AS (
    SELECT c.val,
           sum(c.n) AS n,
           count(*) AS strata_count,
           sum(c.n * (c.med - t.med)) / sum(c.n) AS gap
    FROM cells c JOIN strata t ON t.job_title = c.job_title
    GROUP BY c.val
)
SELECT raw.val,
       raw.n,
       round(raw.med),
       round(raw.mean),
       round(raw.med - (SELECT med FROM overall)),
       round(adj.gap),
       coalesce(adj.n, 0),
       coalesce(adj.strata_count, 0),
       (SELECT n FROM overall),
       round((SELECT med FROM overall))
FROM raw LEFT JOIN adj ON adj.val = raw.val
ORDER BY raw.n DESC
"""


def _build_cell(row: tuple) -> DemographicPayCell:
    """Turn one result row into a cell, applying adjusted-figure suppression."""
    (val, n, med, mean, raw_gap, adj_gap, adj_n, strata_count, _, _) = row
    n, adj_n = int(n), int(adj_n)
    coverage_ok = n and (100.0 * adj_n / n) >= MIN_ADJUSTED_COVERAGE_PCT
    publishable = adj_gap is not None and adj_n >= MIN_ADJUSTED_N and coverage_ok
    return DemographicPayCell(
        value=str(val),
        n=n,
        median_pay=int(med),
        mean_pay=int(mean),
        raw_gap=int(raw_gap),
        within_occupation_gap=int(adj_gap) if publishable else None,
        adjusted_n=adj_n,
        strata_count=int(strata_count),
    )


def get_demographic_pay(
    dimension: PayDimension,
    employer_cluster_id: int | None = None,
) -> DemographicPayBreakdown | None:
    """Actual-pay breakdown for one demographic dimension, sorting-adjusted.

    Pass ``employer_cluster_id`` to scope the whole breakdown to one employer (for
    an employer-profile component); omit it for the site-wide figures. Returns None
    for an invalid dimension or when no value clears ``MIN_VALUE_N`` — the caller
    then hides the section rather than rendering an empty table.

    Every cell carries both the raw gap and, where honest, the within-occupation
    gap. A surface that shows only the raw one contradicts our own published
    methodology, so don't.
    """
    if dimension == PayDimension.INVALID:
        return None

    # Parameters bind in order of appearance in the SQL text, and `extra_where`
    # sits in the FIRST CTE — so the cluster id leads, ahead of the three floors.
    extra_where = ""
    scope_params: list = []
    if employer_cluster_id is not None:
        extra_where = "AND employer_cluster_id = %s"
        scope_params.append(employer_cluster_id)
    params = [*scope_params, MIN_STRATUM_N, MIN_VALUE_N, MIN_CELL_N]

    sql = _BREAKDOWN_SQL.format(col=dimension.column, extra_where=extra_where)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    if not rows:
        return None

    return DemographicPayBreakdown(
        dimension=dimension,
        overall_n=int(rows[0][8]),
        overall_median=int(rows[0][9]),
        cells=tuple(_build_cell(r) for r in rows),
    )
