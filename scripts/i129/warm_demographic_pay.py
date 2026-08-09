#!/usr/bin/env python3
"""Compute the site-wide demographic actual-pay panel and write it to the page cache.

The /job-title/ profile reads this panel from cache ONLY — it never computes it on a
request, because the three dimension queries each cost ~3s (a full pass over
i129_petition with percentile_cont) and that surface already competes on speed. So the
section stays hidden until this script has run.

RUN IT after anything that empties the cache:
  * a prod deploy (the `redis-cli -n 1 FLUSHDB` step in .claude/rules/deployment.md),
  * the refresh pipeline's cache.clear(),
  * an i129 data load or an employer re-link.

It writes one key with a 7-day TTL. The underlying data is a frozen FY2021-2024 FOIA
snapshot, so the value does not drift between runs; re-running is cheap and idempotent.

Read-only against the database. Run it INSIDE the app container, which is where the
cache the site reads actually lives:

    docker exec -w /app vb_web python3 -m scripts.i129.warm_demographic_pay
    bazel run //scripts/i129:warm_demographic_pay -- [--check]

--check reports whether the panel is currently warm, and writes nothing.
"""

import argparse
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

import logging

from django_config.logging_config import setup_logging
from lib.business.i129.demographic_pay_panel import (
    get_sitewide_demographic_pay,
    warm_sitewide_demographic_pay,
)

setup_logging(debug=False)
logger = logging.getLogger(__name__)


def _describe(panel) -> str:
    if panel is None:
        return "no dimension cleared suppression (section will render nothing)"
    parts = [f"{s.dimension_label}: {len(s.rows)} rows" for s in panel.sections]
    return f"{panel.overall_n:,} petitions; " + "; ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the panel is warm; compute and write nothing",
    )
    args = parser.parse_args()

    if args.check:
        panel = get_sitewide_demographic_pay()
        if panel is None:
            logger.warning("demographic pay panel is COLD — the section is hidden")
            return 1
        logger.info("demographic pay panel is warm — %s", _describe(panel))
        return 0

    started = time.perf_counter()
    panel = warm_sitewide_demographic_pay()
    logger.info(
        "warmed demographic pay panel in %.1fs — %s",
        time.perf_counter() - started,
        _describe(panel),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
