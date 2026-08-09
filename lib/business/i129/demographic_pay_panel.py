"""View-facing assembly of the demographic actual-pay breakdown.

``demographic_pay.get_demographic_pay`` computes ONE dimension and returns every
value that clears the listing floor. This module decides what a page may show: which
dimensions are publishable at all, which rows survive to the template, and how the
site-wide figures stay off the request path.

WHICH DIMENSIONS, AND WHY NOT FIELD OF STUDY
--------------------------------------------
Measured against the FY21-24 population on 2026-08-09 (244,862 petitions with pay and
a job title):

* ``country_of_birth`` — the finding. India's raw -$2,288 barely moves (-$2,411) and
  China's raw +$17,315 falls to +$8,896: about half is job mix, but a real residual
  survives. Three values clear the adjustment floors (IND, CHN, PHL); the other 60 are
  listed by the stats layer with a raw figure only.
* ``ed_level`` — a bounded, source-defined taxonomy (5 values). A Master's is worth
  about nothing over a Bachelor's inside the same job title (-$262 vs -$1,219), while a
  doctorate keeps +$17,739 of its +$36,400 raw premium.
* ``gender`` — the control. Raw men +$1,206 / women -$2,685 adjusts to -$361 / +$469,
  reproducing the published decomposition (+4.4% raw median, -0.85% adjusted) to the
  dollar. It is here precisely because it comes out ~zero: it shows the method is not
  manufacturing the gaps the other two dimensions report.
* ``field_of_study`` — EXCLUDED, and not for the reason we expected. Its differences do
  NOT vanish under adjustment (LAW +$97,315 raw -> +$47,122 adjusted; ACCOUNTING
  -$24,464 -> -$8,199). It is unpublishable because the column is un-normalized free
  text: 40,975 distinct strings, of which 200 clear the listing floor and 21 clear the
  adjustment floors — and among those 21 the SAME degree appears seven ways
  ("COMPUTER SCIENCE", "COMP SCI", "COMPUTER SCIENCE & ENGINEERING", ...) carrying
  contradictory adjusted gaps (+$10,037 against -$4,730). Rendering that beside the
  country figures would undercut them. Publishing it needs a normalization layer that
  does not exist; adding the dimension back is a data task, not a template change.

WHY ONLY THE ADJUSTED ROWS ARE RENDERED
---------------------------------------
A value whose within-occupation figure was suppressed has no honest place in a ranked
table: its raw gap is exactly the sorting artifact our own methodology page exists to
correct, and the suppressed set swings wildly (Korea's raw +$2,309 against an
unpublishable +$24,553 on 398 petitions). So the template renders the adjusted rows and
reports the rest as a count, never as a list.

Attribution required on any surface: "sourced from USCIS, obtained by Bloomberg."
"""

import logging
from dataclasses import dataclass

from django.core.cache import cache

from lib.business.i129.demographic_pay import (
    DemographicPayBreakdown,
    DemographicPayCell,
    PayDimension,
    get_demographic_pay,
)

logger = logging.getLogger(__name__)

# The dimensions a page may show, in render order. See the module docstring for the
# measurement behind each, and for why field of study is not among them.
PUBLISHED_DIMENSIONS = (
    PayDimension.COUNTRY_OF_BIRTH,
    PayDimension.EDUCATION_LEVEL,
    PayDimension.GENDER,
)

# The site-wide breakdown is the same three numbers for every visitor and the source is
# a frozen FOIA snapshot, so it is computed once and read from cache. It is NOT computed
# on a cache miss inside a request: each dimension costs ~3s (a full pass over
# i129_petition with percentile_cont — measured 2.7-3.1s on prod), so computing all
# three would add ~9s to a page that already competes. The view reads; the warmer
# writes (scripts/i129/warm_demographic_pay.py).
SITEWIDE_CACHE_KEY = "i129_demographic_pay.sitewide.v1"
SITEWIDE_CACHE_TTL = 60 * 60 * 24 * 7

# ISO3 codes carried by the FY21-24 population with enough petitions to be listed
# (every value at or above the stats layer's listing floor, measured 2026-08-09).
# Unmapped codes fall back to the code itself rather than guessing a name.
_COUNTRY_NAMES = {
    "ARE": "United Arab Emirates", "ARG": "Argentina", "AUS": "Australia",
    "BEL": "Belgium", "BGD": "Bangladesh", "BRA": "Brazil", "CAN": "Canada",
    "CHL": "Chile", "CHN": "China", "COL": "Colombia", "CRI": "Costa Rica",
    "DEU": "Germany", "ECU": "Ecuador", "EGY": "Egypt", "ESP": "Spain",
    "ETH": "Ethiopia", "FRA": "France", "GBR": "United Kingdom", "GHA": "Ghana",
    "GRC": "Greece", "HKG": "Hong Kong", "HND": "Honduras", "IDN": "Indonesia",
    "IND": "India", "IRL": "Ireland", "IRN": "Iran", "ISR": "Israel", "ITA": "Italy",
    "JAM": "Jamaica", "JOR": "Jordan", "JPN": "Japan", "KAZ": "Kazakhstan",
    "KEN": "Kenya", "KOR": "South Korea", "KWT": "Kuwait", "LBN": "Lebanon",
    "LKA": "Sri Lanka", "MAR": "Morocco", "MEX": "Mexico", "MNG": "Mongolia",
    "MYS": "Malaysia", "NGA": "Nigeria", "NLD": "Netherlands", "NPL": "Nepal",
    "NZL": "New Zealand", "PAK": "Pakistan", "PER": "Peru", "PHL": "Philippines",
    "POL": "Poland", "ROU": "Romania", "RUS": "Russia", "SAU": "Saudi Arabia",
    "SGP": "Singapore", "SLV": "El Salvador", "SWE": "Sweden", "THA": "Thailand",
    "TUR": "Turkey", "TWN": "Taiwan", "UKR": "Ukraine", "VEN": "Venezuela",
    "VNM": "Vietnam", "ZAF": "South Africa", "ZWE": "Zimbabwe",
}

_GENDER_NAMES = {"male": "Men", "female": "Women"}


def _signed_dollars(amount: int) -> str:
    """``+$17,315`` / ``-$2,288``. The sign is the point, so it is always shown."""
    return f"{'+' if amount >= 0 else '-'}${abs(amount):,}"


def _row_label(dimension: PayDimension, value: str) -> str:
    """Human label for one dimension value; never invents a name it does not have."""
    if dimension == PayDimension.COUNTRY_OF_BIRTH:
        return _COUNTRY_NAMES.get(value.upper(), value)
    if dimension == PayDimension.GENDER:
        return _GENDER_NAMES.get(value.lower(), value.capitalize())
    # ed_level ships as its own description ("MASTER'S DEGREE").
    return value.capitalize()


@dataclass(frozen=True)
class PanelRow:
    """One rendered value: its label and the cell behind it."""

    label: str
    cell: DemographicPayCell

    @property
    def sorting_share_pct(self) -> float | None:
        """Share of the raw gap explained by job mix, only where that reads sanely.

        The underlying ratio is unbounded — a gap the adjustment WIDENS gives a negative
        share, and one it overshoots past zero gives more than 100% (women's -$2,685 raw
        against +$469 adjusted scores 117.5%). Those are real and interesting, but as a
        percentage in a table they read as an error, so the template gets None and shows
        the two gap columns instead.
        """
        share = self.cell.sorting_share_pct
        if share is None or not 0.0 <= share <= 100.0:
            return None
        return share

    @property
    def raw_gap_display(self) -> str:
        """Raw gap as signed currency, e.g. ``+$17,315``."""
        return _signed_dollars(self.cell.raw_gap)

    @property
    def within_occupation_gap_display(self) -> str:
        """Within-occupation gap as signed currency. Only rendered rows have one."""
        gap = self.cell.within_occupation_gap
        return _signed_dollars(gap) if gap is not None else ""


@dataclass(frozen=True)
class PanelSection:
    """One dimension's renderable rows plus what was withheld from them."""

    dimension_label: str
    rows: tuple[PanelRow, ...]
    withheld_values: int
    withheld_petitions: int
    overall_n: int
    overall_median: int
    fy_coverage: str


@dataclass(frozen=True)
class DemographicPayPanel:
    """Every publishable dimension for one scope (the whole site, or one employer)."""

    sections: tuple[PanelSection, ...]

    @property
    def overall_n(self) -> int:
        """Petitions the breakdown is drawn from (identical across sections)."""
        return self.sections[0].overall_n if self.sections else 0

    @property
    def fy_coverage(self) -> str:
        return self.sections[0].fy_coverage if self.sections else ""


def _build_section(breakdown: DemographicPayBreakdown) -> PanelSection | None:
    """Renderable section for one breakdown, or None when nothing survives suppression.

    A dimension with a single adjusted row is dropped: one row is a number with nothing
    to compare it against, and the table's whole claim is a comparison.
    """
    adjusted = breakdown.adjusted_cells
    if len(adjusted) < 2:
        return None
    withheld = [c for c in breakdown.cells if c.within_occupation_gap is None]
    return PanelSection(
        dimension_label=breakdown.dimension.label,
        rows=tuple(
            PanelRow(label=_row_label(breakdown.dimension, c.value), cell=c)
            for c in adjusted
        ),
        withheld_values=len(withheld),
        withheld_petitions=sum(c.n for c in withheld),
        overall_n=breakdown.overall_n,
        overall_median=breakdown.overall_median,
        fy_coverage=breakdown.fy_coverage,
    )


def build_demographic_pay_panel(
    employer_cluster_id: int | None = None,
) -> DemographicPayPanel | None:
    """Compute the panel for a scope. Returns None when no dimension survives.

    This RUNS the queries — one full pass over ``i129_petition`` per dimension when
    unscoped. Call it from the warmer or from an employer-scoped view (where the
    ``employer_cluster_id`` index reduces it to a scan of that employer's petitions),
    never unscoped on a request path.
    """
    sections = []
    for dimension in PUBLISHED_DIMENSIONS:
        breakdown = get_demographic_pay(
            dimension, employer_cluster_id=employer_cluster_id
        )
        if breakdown is None:
            continue
        section = _build_section(breakdown)
        if section is not None:
            sections.append(section)
    return DemographicPayPanel(sections=tuple(sections)) if sections else None


def get_sitewide_demographic_pay() -> DemographicPayPanel | None:
    """The site-wide panel, READ FROM CACHE ONLY — never computed on a request.

    Returns None on a cache miss, which the template renders as nothing. That is the
    deliberate trade: the section is dark until the warmer has run, in exchange for the
    guarantee that it can never add ~9s to a page render. Run
    ``scripts/i129/warm_demographic_pay.py`` after any deploy or cache flush.
    """
    cached = cache.get(SITEWIDE_CACHE_KEY)
    if cached is None:
        logger.info("[i129_demographic_pay] sitewide panel not warmed; section hidden")
        return None
    # Stored as a 1-tuple so a warmed-but-empty result (a legitimate None) is
    # distinguishable from a cold cache, and does not re-warm forever.
    return cached[0]


def warm_sitewide_demographic_pay() -> DemographicPayPanel | None:
    """Compute the site-wide panel and write it to cache. For the warmer only."""
    panel = build_demographic_pay_panel()
    cache.set(SITEWIDE_CACHE_KEY, (panel,), SITEWIDE_CACHE_TTL)
    return panel


def get_employer_demographic_pay(cluster) -> DemographicPayPanel | None:
    """The panel scoped to one employer cluster, computed inline.

    ``cluster`` is any object with an ``id`` (an ``EmployerCluster``). Scoping hits the
    ``employer_cluster_id`` index (migration 0053), so the cost tracks that employer's
    petition count rather than the whole table — the same posture as
    ``pay_comparison.get_employer_pay_comparison``, which is called from the same view.

    Returns None for almost every employer: a cluster needs enough linked petitions for
    two dimension values to clear the adjustment floors, which takes thousands.
    """
    cluster_id = getattr(cluster, "id", None)
    if cluster_id is None:
        return None
    return build_demographic_pay_panel(employer_cluster_id=cluster_id)
