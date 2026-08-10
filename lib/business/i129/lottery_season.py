"""H-1B cap ("lottery") season: the calendar, the published selection odds, and
the later-round filing waves visible in the I-129 microdata.

Three separable things live here because one page cluster renders all three:

* ``USCIS_SELECTION_HISTORY`` — eligible registrations and selections per cap
  fiscal year, from USCIS's published H-1B Electronic Registration statistics.
  These are NOT computable from our database: ``i129_petition`` holds only
  petitions that were selected AND filed (``status_type = SELECTED`` on
  essentially every row), so the denominator — the registration pool — is not in
  it. Every figure here was vetted in
  ``docs/department_of_labor/i129_stories/RIGOR_REVIEW.md`` and is already
  published with attribution at ``/analysis/h1b-lottery-odds-by-year/``.

* ``filing_waves()`` — derived from OUR data: when cap-selected petitions were
  actually received by USCIS, split into the initial filing window and the later
  window. A cap season in which USCIS ran additional selection rounds shows a
  second mass of receipts months after the initial window closes, so this is a
  direct, observed measure of how much of a season came from later rounds. It is
  a measure of receipts, not an announcement of rounds.

* ``current_cap_season()`` — which phase of the annual cycle today falls in. The
  April 1 filing start and the October 1 employment start are fixed points of the
  program; the later-round window is where the receipts in ``filing_waves()``
  land, not a date USCIS publishes in advance.
"""

from dataclasses import dataclass
from datetime import date
from enum import IntEnum, unique

from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import TruncMonth

from models.i129 import I129Petition

# 65,000 regular cap + 20,000 U.S. master's-degree exemption.
H1B_ANNUAL_CAP = 85_000

# When SELECTION_HISTORY below was last revised. This is the pages' real content
# change date and therefore their sitemap lastmod: the rendered phase banner
# moves daily, and advertising "changed today" every day is drift Google
# discounts (see webapp/views/seo/sitemaps.py::_lastmod_capped). Bump this when a
# season is added or a figure corrected.
SELECTION_HISTORY_UPDATED = date(2026, 8, 10)

# USCIS's published registration statistics report a page that is Akamai-blocked
# to non-browser clients, so the citation a reader can follow is the process page
# itself plus the FY2025 rulemaking that changed how selection is counted.
USCIS_REGISTRATION_URL = (
    "https://www.uscis.gov/working-in-the-united-states/temporary-workers/"
    "h-1b-specialty-occupations/h-1b-electronic-registration-process"
)
BENEFICIARY_CENTRIC_RULE_URL = (
    "https://www.federalregister.gov/documents/2024/02/02/2024-01770/"
    "improving-the-h-1b-registration-selection-process-and-program-integrity"
)


@unique
class SelectionBasis(IntEnum):
    """What USCIS drew from when it ran the lottery."""

    INVALID = 0
    PER_REGISTRATION = 1
    PER_BENEFICIARY = 2

    @property
    def slug(self) -> str:
        return self.name.lower()

    @property
    def label(self) -> str:
        return {
            SelectionBasis.PER_REGISTRATION: "Per registration",
            SelectionBasis.PER_BENEFICIARY: "Per beneficiary",
        }.get(self, "Unknown")


@dataclass(frozen=True)
class SelectionSeason:
    """One cap season's published registration and selection totals."""

    cap_fy: int
    eligible_registrations: int
    selected_registrations: int
    basis: SelectionBasis
    note: str = ""

    @property
    def selection_rate_pct(self) -> float:
        if not self.eligible_registrations:
            return 0.0
        return round(
            100.0 * self.selected_registrations / self.eligible_registrations, 1
        )

    @property
    def over_selection_multiple(self) -> float:
        """Selections across all rounds, as a multiple of the 85,000 cap.

        USCIS selects more registrations than the cap because not every selected
        registrant files a petition and not every petition is approved. A season
        that needed a larger multiple is one where more selections were required
        to fill the same 85,000 slots.
        """
        return round(self.selected_registrations / H1B_ANNUAL_CAP, 2)


# Cap seasons FY2021-FY2026. Sources: USCIS H-1B Electronic Registration
# statistics for the totals; the FY2025 beneficiary-centric rule for the change
# of basis. Figures cross-checked in RIGOR_REVIEW.md against the same published
# aggregates used by the /analysis/h1b-lottery-odds-by-year/ story.
USCIS_SELECTION_HISTORY: tuple[SelectionSeason, ...] = (
    SelectionSeason(
        cap_fy=2021,
        eligible_registrations=269_424,
        selected_registrations=124_415,
        basis=SelectionBasis.PER_REGISTRATION,
        note="Total across multiple selection rounds — USCIS selected again when "
        "too few selectees filed, so this rate overstates a single round's odds.",
    ),
    SelectionSeason(
        cap_fy=2022,
        eligible_registrations=301_447,
        selected_registrations=131_924,
        basis=SelectionBasis.PER_REGISTRATION,
        note="Total across multiple selection rounds — USCIS selected again when "
        "too few selectees filed, so this rate overstates a single round's odds.",
    ),
    SelectionSeason(
        cap_fy=2023,
        eligible_registrations=474_421,
        selected_registrations=127_600,
        basis=SelectionBasis.PER_REGISTRATION,
    ),
    SelectionSeason(
        cap_fy=2024,
        eligible_registrations=758_994,
        selected_registrations=188_400,
        basis=SelectionBasis.PER_REGISTRATION,
        note="The largest registration pool on record. Over half of these "
        "registrations were for beneficiaries entered by more than one employer.",
    ),
    SelectionSeason(
        cap_fy=2025,
        eligible_registrations=470_342,
        selected_registrations=135_137,
        basis=SelectionBasis.PER_BENEFICIARY,
        note="First season under the beneficiary-centric rule: one entry per "
        "person however many employers register them. 127,624 distinct "
        "beneficiaries were selected, a 28.9% per-beneficiary rate.",
    ),
    SelectionSeason(
        cap_fy=2026,
        eligible_registrations=343_981,
        selected_registrations=120_141,
        basis=SelectionBasis.PER_BENEFICIARY,
        note="The registration fee rose from $10 to $215 for this season, "
        "alongside a cooler hiring market — both cut registrations independently "
        "of the counting rule.",
    ),
)


def latest_published_season() -> SelectionSeason:
    """The most recent cap season we hold published USCIS figures for."""
    return max(USCIS_SELECTION_HISTORY, key=lambda s: s.cap_fy)


# --- The cap-season calendar --------------------------------------------------

@unique
class CapSeasonPhase(IntEnum):
    """Where the annual cycle stands for the cap season now in play."""

    INVALID = 0
    BEFORE_REGISTRATION = 1
    REGISTRATION = 2
    INITIAL_FILING = 3
    LATER_ROUNDS = 4
    EMPLOYMENT_STARTED = 5

    @property
    def slug(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class PhaseWindow:
    """One phase of a cap season, with the window it occupies."""

    phase: CapSeasonPhase
    label: str
    window: str
    detail: str
    is_current: bool = False


@dataclass(frozen=True)
class CapSeason:
    """The cap season now in play, and where in it today falls."""

    cap_fy: int
    registration_year: int
    today: date
    phase: CapSeasonPhase
    phases: tuple[PhaseWindow, ...]

    @property
    def employment_start(self) -> date:
        """First day H-1B employment under this cap can begin."""
        return date(self.registration_year, 10, 1)

    @property
    def current_phase(self) -> PhaseWindow | None:
        return next((p for p in self.phases if p.is_current), None)


def _phase_for(today: date) -> CapSeasonPhase:
    month = today.month
    if month <= 2:
        return CapSeasonPhase.BEFORE_REGISTRATION
    if month == 3:
        return CapSeasonPhase.REGISTRATION
    if month <= 7:
        return CapSeasonPhase.INITIAL_FILING
    if month <= 9:
        return CapSeasonPhase.LATER_ROUNDS
    return CapSeasonPhase.EMPLOYMENT_STARTED


def current_cap_season(today: date | None = None) -> CapSeason:
    """The cap season now in play and today's phase within it.

    The cycle is keyed to the calendar year the registration happens in: a
    registration run in March of year ``r`` fills the cap for fiscal year
    ``r + 1``, whose employment starts on October 1 of year ``r``. So the season
    in play is always ``today.year + 1``, whatever the month.
    """
    today = today or date.today()
    reg_year = today.year
    cap_fy = reg_year + 1
    phase = _phase_for(today)

    specs = (
        (
            CapSeasonPhase.BEFORE_REGISTRATION,
            "Registration announced",
            f"January-February {reg_year}",
            "USCIS announces the dates of the electronic registration period and "
            "the fee before it opens.",
        ),
        (
            CapSeasonPhase.REGISTRATION,
            "Registration period",
            f"March {reg_year}",
            "Employers register each beneficiary electronically. Recent cap "
            "seasons have registered in March; USCIS publishes the exact dates "
            "each year. Selection follows immediately, before filing opens.",
        ),
        (
            CapSeasonPhase.INITIAL_FILING,
            "Initial filing window",
            f"April 1 - late June {reg_year}",
            "Selected registrants file the I-129 petition. In the four cap "
            "seasons in our petition data, receipts from the initial selection "
            "cluster in April, May and June, and thin out through July.",
        ),
        (
            CapSeasonPhase.LATER_ROUNDS,
            "Additional selection rounds, if needed",
            f"August-September {reg_year}",
            "If the filed petitions will not fill 85,000 slots, USCIS selects "
            "again from the registrations already submitted. Seasons that ran "
            "additional rounds show a second wave of receipts in this window; "
            "seasons that did not show almost none.",
        ),
        (
            CapSeasonPhase.EMPLOYMENT_STARTED,
            f"FY{cap_fy} employment begins",
            f"October 1, {reg_year}",
            f"Approved cap-subject workers can start on October 1, {reg_year}. "
            f"The next registration period follows in March {reg_year + 1}.",
        ),
    )

    phases = tuple(
        PhaseWindow(
            phase=p, label=label, window=window, detail=detail, is_current=(p == phase)
        )
        for p, label, window, detail in specs
    )
    return CapSeason(
        cap_fy=cap_fy,
        registration_year=reg_year,
        today=today,
        phase=phase,
        phases=phases,
    )


# --- Observed filing waves, from the I-129 microdata --------------------------

# Receipts are bucketed by calendar month, which is all the resolution the
# boundaries need: filing opens April 1, and July is the trough between the
# initial window and any later-round wave in every season we hold.
_LATER_ROUND_FIRST_MONTH = 8

_FILING_WAVES_CACHE_KEY = "i129.lottery_filing_waves.v1"
_FILING_WAVES_TTL = 60 * 60 * 24


@dataclass(frozen=True)
class SeasonFilingWaves:
    """When one cap season's selected petitions were actually received."""

    cap_fy: int
    initial_window: int
    later_window: int
    out_of_season: int

    @property
    def in_season(self) -> int:
        return self.initial_window + self.later_window

    @property
    def later_share_pct(self) -> float:
        if not self.in_season:
            return 0.0
        return round(100.0 * self.later_window / self.in_season, 1)

    @property
    def had_later_wave(self) -> bool:
        """Whether receipts after the initial window are a real wave.

        One in twenty is far above the trickle of late transfers and corrected
        filings seen in seasons with no additional round (0.3% in FY2023) and far
        below the seasons that ran one (13%-37%).
        """
        return self.later_share_pct >= 5.0


def filing_waves(use_cache: bool = True) -> tuple[SeasonFilingWaves, ...]:
    """Per cap season, when its selected-and-filed petitions were received.

    A single grouped query over ``i129_petition`` (a frozen FOIA snapshot, so the
    result only changes when the dataset is re-ingested), cached because it is a
    whole-table aggregate and these pages are crawled.
    """
    if use_cache:
        cached = cache.get(_FILING_WAVES_CACHE_KEY)
        if cached is not None:
            return tuple(SeasonFilingWaves(**row) for row in cached)

    rows = (
        I129Petition.objects.filter(received_date__isnull=False)
        .annotate(month=TruncMonth("received_date"))
        .values("fiscal_year", "month")
        .annotate(n=Count("id"))
        .order_by()
    )

    buckets: dict[int, list[int]] = {}
    for row in rows:
        cap_fy = row["fiscal_year"]
        month = row["month"]
        if cap_fy is None or month is None:
            continue
        reg_year = cap_fy - 1
        counts = buckets.setdefault(cap_fy, [0, 0, 0])
        if month.year == reg_year and 4 <= month.month <= 7:
            counts[0] += row["n"]
        elif (month.year == reg_year and month.month >= _LATER_ROUND_FIRST_MONTH) or (
            month.year == cap_fy and month.month <= 9
        ):
            counts[1] += row["n"]
        else:
            counts[2] += row["n"]

    waves = tuple(
        SeasonFilingWaves(
            cap_fy=cap_fy,
            initial_window=counts[0],
            later_window=counts[1],
            out_of_season=counts[2],
        )
        for cap_fy, counts in sorted(buckets.items())
    )
    if use_cache:
        cache.set(
            _FILING_WAVES_CACHE_KEY,
            [
                {
                    "cap_fy": w.cap_fy,
                    "initial_window": w.initial_window,
                    "later_window": w.later_window,
                    "out_of_season": w.out_of_season,
                }
                for w in waves
            ],
            _FILING_WAVES_TTL,
        )
    return waves
