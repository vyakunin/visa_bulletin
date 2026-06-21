"""Estimate when the next Visa Bulletin will be released.

The State Department publishes each month's Visa Bulletin roughly two weeks
before the month it governs (the "July" bulletin posts in mid-June). Our
``Bulletin.publication_date`` is normalised to the 1st of the *governing* month,
so the real release date is not stored there. ``Bulletin.fetched_at``
(``auto_now_add``) ≈ when our hourly cron first ingested the bulletin, which is
within hours of the State Department posting it — so for *live-ingested*
bulletins it is a faithful proxy for the actual release date.

This module derives the typical release day-of-month from recent live-ingested
bulletins and projects the next expected release.
"""

from dataclasses import dataclass
from datetime import date
from statistics import median

from dateutil.relativedelta import relativedelta

from models.bulletin import Bulletin

# A live ingest lands a few days to a few weeks BEFORE the governing month's 1st.
# Bulk-backfilled rows share one synthetic fetched_at far from their governing
# month (huge lead), so this window cleanly excludes them.
_MIN_LEAD_DAYS = 3
_MAX_LEAD_DAYS = 45


@dataclass(frozen=True)
class ReleaseRecord:
    """One observed release: which month it governs, when it actually posted."""

    governing_month: date  # 1st of the governing month
    released_on: date  # fetched_at date ≈ real State Dept release date

    @property
    def lead_days(self) -> int:
        return (self.governing_month - self.released_on).days


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


def recent_live_releases(limit: int = 12) -> list[ReleaseRecord]:
    """Most-recent live-ingested bulletins (newest first), backfill rows excluded."""
    out: list[ReleaseRecord] = []
    # Over-fetch then filter: ordering by publication_date keeps the newest
    # governing months; the lead-window filter drops synthetic backfill rows.
    for b in Bulletin.objects.order_by("-publication_date").iterator():
        if b.fetched_at is None:
            continue
        rec = ReleaseRecord(governing_month=b.publication_date, released_on=b.fetched_at.date())
        if _MIN_LEAD_DAYS <= rec.lead_days <= _MAX_LEAD_DAYS:
            out.append(rec)
        if len(out) >= limit:
            break
    return out


def get_release_schedule(today: date | None = None) -> ReleaseSchedule | None:
    """Project the next Visa Bulletin release from recent release history.

    Returns None when there is not yet enough live-ingested history to estimate.
    """
    history = recent_live_releases()
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


def _clamp_dom(month_first: date, day: int) -> date:
    """A date in ``month_first``'s month on ``day``, clamped to the month length."""
    nxt = month_first + relativedelta(months=1)
    last_dom = (nxt - relativedelta(days=1)).day
    return month_first.replace(day=min(max(day, 1), last_dom))
