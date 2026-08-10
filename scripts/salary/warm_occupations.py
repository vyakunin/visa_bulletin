#!/usr/bin/env python3
"""Fill the per-occupation caches the /h1b-salary/<occupation>/ pages read.

Each occupation page runs nine full scans of salary_record plus the I-129 matched-triple
aggregate. `occupation_stats` caches the results per occupation, but it fills them ON THE
FIRST MISS — so the first request for each of the 41 occupations still pays the whole
cost. That request is almost always a crawler: the view is `cache_page_skip_bots`, so bot
traffic bypasses the rendered-page cache by design and can never be warmed by it.

The entries carry a 24h TTL, which means the cold fills RECUR daily rather than only
after a deploy. Measured on prod 2026-08-10, immediately after the fix shipped: 36 of 41
occupations took 5.9-9.2s on their first hit and 0.13s on every hit after. So without a
recurring warm the slow tail comes back every day, on Googlebot.

RUN IT:
  * after anything that empties the cache — a deploy's `redis-cli -n 1 FLUSHDB`
    (.claude/rules/deployment.md), the refresh pipeline's cache.clear(), a data load;
  * daily, ahead of the crawl window, so the TTL never expires into a crawler.

Read-only against the database. Run it INSIDE the app container, which is where the
cache the site reads actually lives:

    docker exec -w /app vb_web python3 -m scripts.salary.warm_occupations
    bazel run //scripts/salary:warm_occupations -- [--check]

--check reports how many occupations are currently warm and writes nothing.
"""

import argparse
import logging
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django_config.logging_config import setup_logging  # noqa: E402
from lib.business.i129.pay_comparison import (  # noqa: E402
    get_soc_pay_comparison,
    soc_pay_comparison_cached,
)
from lib.business.salary.occupation_stats import (  # noqa: E402
    get_occupation_stats,
    occupation_filing_count,
    occupation_qualifies,
    occupation_stats_cached,
    qualifying_occupation_slugs,
)
from lib.business.salary.soc_occupations import OCCUPATIONS  # noqa: E402

setup_logging(debug=False)
logger = logging.getLogger(__name__)


def _is_warm(slug: str) -> bool:
    """Whether the two per-occupation entries a page render needs are both present.

    The filing count alone is not enough — it is the cheap 404 gate, while the stats and
    the SOC comparison are what cost seconds.
    """
    return occupation_stats_cached(slug) and soc_pay_comparison_cached(slug)


def _warm_one(occ) -> float:
    """Fill every cached value one occupation page reads. Returns seconds taken."""
    started = time.perf_counter()
    filing_count = occupation_filing_count(occ)
    if occupation_qualifies(filing_count):
        # A thin occupation 404s, so its stats are never rendered and warming them
        # would pay nine scans for a page nobody can reach.
        get_occupation_stats(occ)
        get_soc_pay_comparison(occ)
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report how many occupations are warm; compute and write nothing",
    )
    args = parser.parse_args()

    if args.check:
        warm = [o.slug for o in OCCUPATIONS if _is_warm(o.slug)]
        cold = [o.slug for o in OCCUPATIONS if o.slug not in warm]
        if cold:
            logger.warning(
                "%d/%d occupations COLD — first crawler hit pays the full render: %s",
                len(cold),
                len(OCCUPATIONS),
                ", ".join(cold),
            )
            return 1
        logger.info("all %d occupations warm", len(OCCUPATIONS))
        return 0

    started = time.perf_counter()
    # Fill the qualifying-slug set first: it reads through the same per-occupation
    # filing-count entries, so the sitemap and the pages warm each other.
    qualifying_occupation_slugs()

    slow: list[tuple[str, float]] = []
    for occ in OCCUPATIONS:
        took = _warm_one(occ)
        if took > 3.0:
            slow.append((occ.slug, took))

    logger.info(
        "warmed %d occupations in %.1fs — %d were cold fills (>3s)",
        len(OCCUPATIONS),
        time.perf_counter() - started,
        len(slow),
    )
    for slug, took in slow:
        logger.info("  cold fill %-30s %.2fs", slug, took)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
