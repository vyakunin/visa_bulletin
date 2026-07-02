#!/usr/bin/env python3
"""Backfill i129_petition.employer_cluster_id from employer_name.

Thin CLI wrapper over lib.business.i129.employer_linker.link_i129_employers. Maps
each petition's raw USCIS employer_name to an LCA EmployerCluster by NORMALIZED name
(exact match yields ~0 rows — the USCIS and LCA spellings differ), so the employer
profile page can scope the actual-pay comparison to that employer.

Heavyweight write on the full petition table (~373k rows): run OFF-PROD on staging
and graduate the data (branching.md / employer_clustering.md — clustering is a
derived layer; touching its inputs obligates a re-link). Re-run after every i129
data refresh (new petitions land with NULL employer_cluster_id; the linker only
touches rows whose cluster changed).

Usage:
    bazel run //scripts/i129:backfill_employer_links -- [--dry-run]
"""

import argparse
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django_config.logging_config import setup_logging
from lib.business.i129.employer_linker import link_i129_employers

setup_logging(debug=False)
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + report match rates without writing.",
    )
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("I-129 employer_name → cluster backfill%s", " [DRY RUN]" if args.dry_run else "")
    logger.info("=" * 80)

    stats = link_i129_employers(dry_run=args.dry_run)

    logger.info(
        "Result: %d/%d distinct names matched (%.1f%%); %d/%d petition rows (%.1f%%).",
        stats.matched_names,
        stats.distinct_names,
        stats.name_match_pct,
        stats.matched_rows,
        stats.total_rows,
        stats.row_match_pct,
    )
    if args.dry_run:
        logger.info("DRY RUN — no rows written.")


if __name__ == "__main__":
    main()
