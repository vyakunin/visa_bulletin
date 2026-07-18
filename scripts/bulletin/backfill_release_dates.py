#!/usr/bin/env python3
"""Backfill ``Bulletin.released_on`` — the real State Department release date.

``publication_date`` is the governing month and ``fetched_at`` only approximates
the release date for bulletins our own cron ingested live (4 of 290 rows as of
2026-07). This fills the rest from the Internet Archive: the earliest capture of
each bulletin's travel.state.gov URL.

Sources, best first:
  live     our own ``fetched_at`` (within hours of the State Dept posting)
  wayback  earliest archived capture — an UPPER bound (measured lag vs our live
           ingests: -1 to +6 days)

When both are available the EARLIER of the two wins: each is an upper bound on
the true release, so the minimum is the tightest one. A candidate whose implied
lead time falls outside 3-45 days before the governing month is REJECTED and the
row left NULL — "unknown" stays distinguishable from "known".

Coverage note: travel.state.gov moved to its current CMS in late 2017, so
bulletins governing months before ~2018 have no contemporaneous capture at these
URLs (they were all first archived 2017-12-03, which the lead filter rejects).
Recovering those needs the pre-migration numbered URLs
(``/visa/frvi/bulletin/bulletin_NNNN.html``), which are not derivable from the
publication date — out of scope here.

Prereqs:
    Network access to web.archive.org. CDX responses are cached under
    ``--cache-dir`` so re-runs are cheap and resumable.

Outputs:
    Updates ``bulletin.released_on``, ``released_on_source``,
    ``released_on_gap_days``. Prints a per-era coverage summary.
    Exit 0 on success, 1 if every lookup failed (network down).

Usage:
    bazel run //scripts/bulletin:backfill_release_dates -- --dry-run
    bazel run //scripts/bulletin:backfill_release_dates
    bazel run //scripts/bulletin:backfill_release_dates -- --since 2018-01-01 --refresh
"""

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from lib.business.bulletin.wayback import first_capture_date  # noqa: E402
from lib.utils.logging_utils import ScriptLogger  # noqa: E402
from models.bulletin import Bulletin  # noqa: E402

logger = logging.getLogger(__name__)

# Same plausibility window the serving code uses (lib/business/bulletin/release_schedule).
MIN_LEAD_DAYS = 3
MAX_LEAD_DAYS = 45

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "visa_bulletin" / "wayback_cdx"


def _lead_days(governing_month: date, released_on: date) -> int:
    return (governing_month - released_on).days


def _plausible(governing_month: date, released_on: date | None) -> bool:
    if released_on is None:
        return False
    return MIN_LEAD_DAYS <= _lead_days(governing_month, released_on) <= MAX_LEAD_DAYS


def _live_candidate(b: Bulletin) -> date | None:
    """``fetched_at`` as a release-date candidate, if it looks like a live ingest."""
    if b.fetched_at is None:
        return None
    candidate = b.fetched_at.date()
    return candidate if _plausible(b.publication_date, candidate) else None


def backfill(
    *,
    dry_run: bool,
    since: date | None,
    refresh: bool,
    cache_dir: Path,
    limit: int | None,
) -> int:
    qs = Bulletin.objects.order_by("-publication_date")
    if since is not None:
        qs = qs.filter(publication_date__gte=since)
    if not refresh:
        qs = qs.filter(released_on__isnull=True)
    if limit is not None:
        qs = qs[:limit]

    bulletins = list(qs)
    logger.info("Considering %d bulletin(s)", len(bulletins))

    resolved = 0
    rejected = 0
    lookup_failures = 0
    by_source: Counter[str] = Counter()
    by_era: Counter[int] = Counter()

    for b in bulletins:
        month = b.publication_date
        live = _live_candidate(b)

        wayback: date | None = None
        gap: int | None = None
        try:
            wayback, gap = first_capture_date(b.get_bulletin_url(), cache_dir=cache_dir)
        except Exception as exc:  # network / archive outage — keep going
            lookup_failures += 1
            logger.warning("Wayback lookup failed for %s: %s", month, exc)

        if not _plausible(month, wayback):
            if wayback is not None:
                logger.debug(
                    "Rejecting wayback %s for %s (lead %dd outside %d-%d)",
                    wayback, month, _lead_days(month, wayback), MIN_LEAD_DAYS, MAX_LEAD_DAYS,
                )
            wayback, gap = None, None

        # Both are upper bounds on the true release, so the earlier one is tighter.
        if live and wayback:
            chosen, source = (
                (wayback, Bulletin.SOURCE_WAYBACK) if wayback < live else (live, Bulletin.SOURCE_LIVE)
            )
        elif live:
            chosen, source = live, Bulletin.SOURCE_LIVE
        elif wayback:
            chosen, source = wayback, Bulletin.SOURCE_WAYBACK
        else:
            rejected += 1
            continue

        gap_days = gap if source == Bulletin.SOURCE_WAYBACK else None
        logger.info(
            "%s -> %s (%s, lead %dd)", month, chosen, source, _lead_days(month, chosen)
        )
        resolved += 1
        by_source[source] += 1
        by_era[month.year] += 1

        if not dry_run:
            b.released_on = chosen
            b.released_on_source = source
            b.released_on_gap_days = gap_days
            b.save(update_fields=["released_on", "released_on_source", "released_on_gap_days"])

    total = Bulletin.objects.count()
    known = (
        resolved
        if dry_run
        else Bulletin.objects.filter(released_on__isnull=False).count()
    )
    print("\n=== RELEASE DATE BACKFILL ===")
    print(f"{'DRY RUN — nothing written' if dry_run else 'Written to DB'}")
    print(f"Considered:       {len(bulletins)}")
    print(f"Resolved:         {resolved}  ({dict(by_source)})")
    print(f"No usable date:   {rejected}")
    if lookup_failures:
        print(f"Lookup failures:  {lookup_failures}")
    print(f"Known / total:    {known} / {total}")
    if by_era:
        print("By governing year:")
        for year in sorted(by_era):
            print(f"  {year}: {by_era[year]}")

    if lookup_failures and resolved == 0:
        logger.error("Every lookup failed — archive unreachable?")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Resolve but do not write")
    parser.add_argument("--since", type=date.fromisoformat, help="Only months >= this date")
    parser.add_argument(
        "--refresh", action="store_true", help="Re-resolve rows that already have released_on"
    )
    parser.add_argument("--limit", type=int, help="Process at most N bulletins")
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Where to cache CDX responses"
    )
    args = parser.parse_args()

    script_logger = ScriptLogger(__file__)
    script_logger.log_call(
        args={
            "dry_run": args.dry_run,
            "since": str(args.since) if args.since else None,
            "refresh": args.refresh,
            "limit": args.limit,
        },
        context="Backfill Bulletin.released_on from Wayback + live ingest",
    )

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    return backfill(
        dry_run=args.dry_run,
        since=args.since,
        refresh=args.refresh,
        cache_dir=args.cache_dir,
        limit=args.limit,
    )


if __name__ == "__main__":
    sys.exit(main())
