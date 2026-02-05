# scripts/cron/refresh/smoke.py
"""Smoke tests: record counts, fiscal year, clustering, slugs. Uses runner for PSQL."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import RefreshConfig
    from .runner import Runner

logger = logging.getLogger(__name__)

MIN_RECORDS = 100_000
MIN_RECENT_FY_RECORDS = 1_000
MIN_LINK_PERCENT = 30
MIN_SLUG_PERCENT = 99
MIN_CLUSTERED_EMPLOYERS = 100_000


def run_smoke_tests(runner: Runner, db_name: str, config: RefreshConfig) -> None:
    """Run smoke tests via runner.run_psql. Raises on failure."""
    record_count_s = runner.run_psql(db_name, "SELECT COUNT(*) FROM salary_record;")
    record_count = int(record_count_s.strip()) if record_count_s.strip() else 0
    logger.info("Total salary records: %s", record_count)
    if record_count < MIN_RECORDS:
        raise RuntimeError(
            f"Record count too low: {record_count} (expected >{MIN_RECORDS})"
        )

    max_fy_s = runner.run_psql(db_name, "SELECT MAX(fiscal_year) FROM salary_record;")
    max_fy_s = max_fy_s.strip()
    if not max_fy_s:
        raise RuntimeError("No fiscal year data found in database")
    max_fy = int(max_fy_s)
    logger.info("Most recent fiscal year in DB: %s", max_fy)
    recent_s = runner.run_psql(
        db_name,
        f"SELECT COUNT(*) FROM salary_record WHERE fiscal_year = {max_fy};",
    )
    recent_count = int(recent_s.strip()) if recent_s.strip() else 0
    logger.info("Records for FY %s: %s", max_fy, recent_count)
    if recent_count < MIN_RECENT_FY_RECORDS:
        logger.warning(
            "Very few records for most recent fiscal year %s: %s",
            max_fy,
            recent_count,
        )

    clustered_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_record WHERE job_title_entity_id IS NOT NULL;",
    )
    linked = int(clustered_s.strip()) if clustered_s.strip() else 0
    link_pct = (linked * 100 // record_count) if record_count else 0
    logger.info("Linked records: %s (%s%%)", linked, link_pct)
    if link_pct < MIN_LINK_PERCENT:
        logger.warning(
            "Low job title link percentage: %s%% (expected >%s%%)",
            link_pct,
            MIN_LINK_PERCENT,
        )

    emp_clustered_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer WHERE canonical_cluster_id IS NOT NULL;",
    )
    emp_clustered = int(emp_clustered_s.strip()) if emp_clustered_s.strip() else 0
    logger.info("Clustered employers: %s", emp_clustered)
    if emp_clustered < MIN_CLUSTERED_EMPLOYERS:
        logger.warning(
            "Low clustered employer count: %s (expected >%s)",
            emp_clustered,
            MIN_CLUSTERED_EMPLOYERS,
        )

    total_clusters_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer_cluster;",
    )
    with_slugs_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer_cluster WHERE slug IS NOT NULL;",
    )
    total_clusters = int(total_clusters_s.strip()) if total_clusters_s.strip() else 0
    with_slugs = int(with_slugs_s.strip()) if with_slugs_s.strip() else 0
    if total_clusters > 0:
        slug_pct = with_slugs * 100 // total_clusters
        logger.info("Employer clusters: %s total, %s with slugs (%s%%)", total_clusters, with_slugs, slug_pct)
        if slug_pct < MIN_SLUG_PERCENT:
            raise RuntimeError(
                f"Too many employer clusters without slugs: {total_clusters - with_slugs} missing"
            )
    logger.info("All smoke tests passed")
