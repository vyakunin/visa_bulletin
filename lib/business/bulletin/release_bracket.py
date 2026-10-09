"""The release window the ingest bridge observes, and the release date it supports.

The bridge polls the travel.state.gov index every 30 minutes. For each month it
records the last poll that did NOT list that month's bulletin and the first poll
that did; the release happened between the two. The bracket supports a release date
only when it is at most :data:`MAX_RELEASE_BRACKET` wide, and the date is read in
:data:`RELEASE_TZ`, the publisher's own clock.

Stdlib only: the minipc fetcher imports this outside Bazel and the prod image.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RELEASE_TZ = ZoneInfo("America/New_York")
MAX_RELEASE_BRACKET = timedelta(hours=24)

# Written by scripts/fetch_bulletin_via_browser.py into the HTML cache dir the bridge
# streams to prod; read there by scripts/cron/refresh_bulletin.py.
RELEASE_OBSERVATIONS_FILENAME = "release_observations.json"


def release_date_of(moment: datetime) -> date:
    """The State Department calendar date of ``moment``. A naive ``moment`` is UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(RELEASE_TZ).date()


@dataclass(frozen=True)
class ReleaseBracket:
    """Polls on either side of one month's bulletin appearing on the index."""

    last_absent_at: datetime | None = None
    first_present_at: datetime | None = None

    def release_date(self) -> date | None:
        """The release date this bracket supports, or None when it is open or too wide."""
        if self.last_absent_at is None or self.first_present_at is None:
            return None
        if self.first_present_at - self.last_absent_at > MAX_RELEASE_BRACKET:
            return None
        return release_date_of(self.first_present_at)


def observe(
    brackets: dict[date, ReleaseBracket], month: date, on_index: bool, now: datetime
) -> None:
    """Fold one poll of the index into ``brackets``. A bracket closes once and stays closed."""
    current = brackets.get(month, ReleaseBracket())
    if current.first_present_at is not None:
        return
    if on_index:
        brackets[month] = ReleaseBracket(current.last_absent_at, now)
    else:
        brackets[month] = ReleaseBracket(now, None)


def _month_key(month: date) -> str:
    return month.strftime("%Y-%m")


def _parse_month(key: str) -> date:
    return datetime.strptime(key, "%Y-%m").date()


def _parse_moment(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def dump_brackets(brackets: dict[date, ReleaseBracket], path: Path) -> None:
    payload = {
        _month_key(month): {
            "last_absent_at": b.last_absent_at.isoformat() if b.last_absent_at else None,
            "first_present_at": b.first_present_at.isoformat() if b.first_present_at else None,
        }
        for month, b in sorted(brackets.items())
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_brackets(path: Path) -> dict[date, ReleaseBracket]:
    """Brackets stored at ``path``; empty when the file does not exist yet."""
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        _parse_month(key): ReleaseBracket(
            _parse_moment(entry.get("last_absent_at")),
            _parse_moment(entry.get("first_present_at")),
        )
        for key, entry in payload.items()
    }
