#!/usr/bin/env python3
"""One-off: record the release dates of the editions the bridge ingested before it
recorded release windows itself (Aug, Sep and Oct 2026).

Each date comes from the bridge's own log (``logs/sync_bulletin_to_prod.log`` on the
minipc): the last 30-minute poll whose index did not list the edition, and the first
that did. The date is read in Eastern time through the same ``ReleaseBracket`` the
ingest path uses. Only a NULL ``released_on`` is written; a row carrying a different
value is reported and left alone. Safe to re-run.

Usage
  docker exec -w /app vb_web python3 -m scripts.oneoff.correct_bridge_release_dates --dry-run
  docker exec -w /app vb_web python3 -m scripts.oneoff.correct_bridge_release_dates
"""

import argparse
import os
from datetime import UTC, date, datetime

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.bulletin.release_bracket import ReleaseBracket  # noqa: E402
from lib.utils.logging_utils import log_context  # noqa: E402
from models.bulletin import Bulletin  # noqa: E402


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# Index link count 291 -> 292 (Aug), 292 -> 293 (Sep), 293 -> 294 (Oct) between the polls.
OBSERVED_BRACKETS: dict[date, ReleaseBracket] = {
    date(2026, 8, 1): ReleaseBracket(_utc(2026, 7, 20, 16, 0, 20), _utc(2026, 7, 20, 16, 30, 10)),
    date(2026, 9, 1): ReleaseBracket(_utc(2026, 8, 22, 2, 0, 10), _utc(2026, 8, 22, 2, 30, 10)),
    date(2026, 10, 1): ReleaseBracket(_utc(2026, 9, 29, 10, 30, 10), _utc(2026, 9, 29, 11, 0, 10)),
}


def correct(*, dry_run: bool) -> None:
    for month, bracket in OBSERVED_BRACKETS.items():
        released = bracket.release_date()
        bulletin = Bulletin.objects.filter(publication_date=month).first()
        if bulletin is None:
            print(f"{month:%b %Y}: no bulletin row — skipped")
            continue
        if bulletin.released_on == released and bulletin.released_on_source == Bulletin.SOURCE_LIVE:
            print(f"{month:%b %Y}: already {released} (live) — nothing to do")
            continue
        if bulletin.released_on is not None:
            print(
                f"{month:%b %Y}: carries {bulletin.released_on} ({bulletin.released_on_source}), "
                f"evidence says {released} — left alone"
            )
            continue
        print(f"{month:%b %Y}: NULL -> {released:%a %Y-%m-%d} (live){' [dry run]' if dry_run else ''}")
        if not dry_run:
            Bulletin.objects.filter(pk=bulletin.pk, released_on__isnull=True).update(
                released_on=released,
                released_on_source=Bulletin.SOURCE_LIVE,
                released_on_gap_days=None,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report, write nothing")
    args = parser.parse_args()
    log_context("Record bridge-observed release dates for the Aug/Sep/Oct 2026 bulletins")
    correct(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
