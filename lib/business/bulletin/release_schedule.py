"""Estimate when the next Visa Bulletin will be released, from observed history.

The State Department publishes each month's Visa Bulletin roughly two weeks
before the month it governs (the "July" bulletin posts in mid-June).
``Bulletin.publication_date`` is normalised to the 1st of the *governing* month,
so the real release date is not stored there.

``Bulletin.released_on`` carries the release date itself, backfilled by
``scripts/bulletin/backfill_release_dates.py`` from two sources:

* ``live`` — our own cron's ``fetched_at``, within hours of the State Department
  posting (only the handful of bulletins we ingested live).
* ``wayback`` — the earliest Internet Archive capture of the bulletin's
  travel.state.gov URL. An **upper bound**: the crawler sees the page some time
  after State posts it (measured lag vs our live ingests: -1 to +6 days).

Rows whose implied lead time is implausible are left NULL rather than guessed,
so "we don't know" stays distinguishable from "we know". For rows not yet
backfilled this module falls back to the original ``fetched_at`` heuristic, so
it keeps working on a database that predates the backfill.
"""

from dataclasses import dataclass
from datetime import date
from statistics import median

from dateutil.relativedelta import relativedelta

from models.bulletin import Bulletin

# A release lands a few days to a few weeks BEFORE the governing month's 1st.
# Bulk-backfilled rows share one synthetic fetched_at far from their governing
# month, and a sparsely-crawled URL's first capture can land after the governing
# month starts (e.g. May 2020, first archived on 2020-05-01). This window
# excludes both: outside it we record nothing rather than a wrong date.
_MIN_LEAD_DAYS = 3
_MAX_LEAD_DAYS = 45

# Release-timing practice drifts, and archive coverage thins out the further
# back you go, so the public-facing stats default to the recent era.
DEFAULT_LOOKBACK_YEARS = 10


@dataclass(frozen=True)
class ReleaseRecord:
    """One observed release: which month it governs, when it actually posted."""

    governing_month: date  # 1st of the governing month
    released_on: date
    source: str = ""  # Bulletin.SOURCE_LIVE | SOURCE_WAYBACK | "" (fetched_at fallback)

    @property
    def lead_days(self) -> int:
        """Days between the release and the 1st of the month it governs."""
        return (self.governing_month - self.released_on).days

    @property
    def is_upper_bound(self) -> bool:
        """True when the true release may be slightly earlier than ``released_on``."""
        return self.source != Bulletin.SOURCE_LIVE


@dataclass(frozen=True)
class ReleaseSchedule:
    """Projected next release + the recent history it was derived from."""

    latest_governing_month: date
    latest_released_on: date
    next_governing_month: date
    next_release_estimate: date
    next_release_window: tuple[date, date]  # (earliest, latest) plausible day
    typical_release_dom: int  # median release day-of-month
    recent_history: list[ReleaseRecord]


@dataclass(frozen=True)
class ReleaseOdds:
    """How often the bulletin for this calendar month was already out by now.

    Answers "X% of August bulletins were published by the 18th" — the honest
    framing for a page whose visitors are refreshing it waiting for a drop.
    """

    month_name: str          # "August"
    as_of: date
    n_total: int             # historical bulletins for this calendar month
    n_released_by_now: int
    years_covered: tuple[int, int]  # (earliest, latest) governing year in the sample

    @property
    def pct_released_by_now(self) -> int:
        if not self.n_total:
            return 0
        return round(100 * self.n_released_by_now / self.n_total)

    @property
    def is_late(self) -> bool:
        """True once most historical releases for this month had already landed."""
        return self.pct_released_by_now >= 50


def _record_from_bulletin(b: Bulletin) -> ReleaseRecord | None:
    """Best available release record for one bulletin, or None when unknown.

    Prefers the backfilled ``released_on``; falls back to the ``fetched_at``
    heuristic so this keeps working before/without the backfill.
    """
    if b.released_on is not None:
        rec = ReleaseRecord(
            governing_month=b.publication_date,
            released_on=b.released_on,
            source=b.released_on_source or "",
        )
    elif b.fetched_at is not None:
        rec = ReleaseRecord(
            governing_month=b.publication_date,
            released_on=b.fetched_at.date(),
            source="",
        )
    else:
        return None
    return rec if _MIN_LEAD_DAYS <= rec.lead_days <= _MAX_LEAD_DAYS else None


def observed_releases(
    limit: int | None = None,
    *,
    since: date | None = None,
    calendar_month: int | None = None,
) -> list[ReleaseRecord]:
    """Observed releases, newest governing month first.

    Args:
        limit: stop after this many records (None = all).
        since: only bulletins governing this month or later.
        calendar_month: only bulletins governing this calendar month (1-12).
    """
    qs = Bulletin.objects.order_by("-publication_date")
    if since is not None:
        qs = qs.filter(publication_date__gte=since)
    if calendar_month is not None:
        qs = qs.filter(publication_date__month=calendar_month)

    out: list[ReleaseRecord] = []
    for b in qs.iterator():
        rec = _record_from_bulletin(b)
        if rec is None:
            continue
        out.append(rec)
        if limit is not None and len(out) >= limit:
            break
    return out


def recent_live_releases(limit: int = 12) -> list[ReleaseRecord]:
    """Back-compat alias for the most recent observed releases."""
    return observed_releases(limit=limit)


def get_release_schedule(today: date | None = None) -> ReleaseSchedule | None:
    """Project the next Visa Bulletin release from recent release history.

    Returns None when there is not yet enough observed history to estimate.
    """
    history = observed_releases(limit=12)
    if not history:
        return None

    latest = history[0]
    next_governing = latest.governing_month + relativedelta(months=1)
    # The next bulletin posts in the month BEFORE the month it governs.
    release_month_first = next_governing - relativedelta(months=1)

    doms = sorted(r.released_on.day for r in history)
    typical_dom = int(round(median(doms)))
    lo_dom, hi_dom = doms[0], doms[-1]

    estimate = _clamp_dom(release_month_first, typical_dom)
    window = (_clamp_dom(release_month_first, lo_dom), _clamp_dom(release_month_first, hi_dom))
    return ReleaseSchedule(
        latest_governing_month=latest.governing_month,
        latest_released_on=latest.released_on,
        next_governing_month=next_governing,
        next_release_estimate=estimate,
        next_release_window=window,
        typical_release_dom=typical_dom,
        recent_history=history,
    )


def release_odds(
    governing_month: date,
    as_of: date,
    *,
    lookback_years: int = DEFAULT_LOOKBACK_YEARS,
) -> ReleaseOdds | None:
    """How many past bulletins for this calendar month were out by this point.

    Comparison happens in "days before the governing month" space rather than by
    day-of-month, so month lengths and the release always landing in the prior
    month are handled without special cases.

    Returns None when there is no usable history for that calendar month.
    """
    since = date(governing_month.year - lookback_years, governing_month.month, 1)
    history = [
        r
        for r in observed_releases(since=since, calendar_month=governing_month.month)
        if r.governing_month < governing_month  # past bulletins only
    ]
    if not history:
        return None

    # Days still to go before the target month starts, as of today.
    current_lead = (governing_month - as_of).days
    # A past bulletin was "already out by this point" if it had at least as many
    # days of runway left when it posted.
    n_released = sum(1 for r in history if r.lead_days >= current_lead)

    years = [r.governing_month.year for r in history]
    return ReleaseOdds(
        month_name=governing_month.strftime("%B"),
        as_of=as_of,
        n_total=len(history),
        n_released_by_now=n_released,
        years_covered=(min(years), max(years)),
    )


def _clamp_dom(month_first: date, day: int) -> date:
    """A date in ``month_first``'s month on ``day``, clamped to the month length."""
    nxt = month_first + relativedelta(months=1)
    last_dom = (nxt - relativedelta(days=1)).day
    return month_first.replace(day=min(max(day, 1), last_dom))
