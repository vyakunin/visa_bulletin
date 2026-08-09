#!/usr/bin/env python3
"""
Update JobTitleCluster and JobTitle with aggregated stats and representative titles.

This script does three things in a single pass with bulk SQL (no per-record scans):

1. **JobTitleCluster**: Sets total_filings, avg_salary, and canonical_title.
   - total_filings / avg_salary: from SalaryRecords per cluster (sum over JobTitles in
     that cluster, wage_annual in reasonable bounds). Each cluster gets its true count
     so directory "Popular Job Titles" and profile "Total Filings" align.
   - canonical_title: the most frequent raw title among records whose normalized title
     (JobTitle.title_normalized) equals the cluster's most frequent normalized form;
     among those, prefers no comma then shorter (so "Software Engineers, Applications"
     → cluster's mode normalized → most frequent raw with that normalized form).

2. **JobTitle**: Sets title to the most frequent raw title (SalaryRecord.job_title) among
   records pointing at this entity, so both the entity and the cluster have a meaningful
   display title.

All "most frequent" choices are computed in bulk via SQL (GROUP BY + ROW_NUMBER), then
applied with batched bulk_update. No N+1 queries and no full-table scan of unindexed
fields.

Usage:
    bazel run //scripts/salary:update_job_title_cluster_stats
    bazel run //scripts/salary:update_job_title_cluster_stats -- --dry-run
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

import argparse
import logging
from decimal import Decimal

from django.db import connection
from django.utils import timezone

from django_config.logging_config import setup_logging
from lib.utils.db_utils import bulk_update_batched
from lib.utils.logging_utils import ScriptLogger
from models.job_title import JobTitle, JobTitleCluster

setup_logging()
script_logger = ScriptLogger(__file__)
logger = logging.getLogger(__name__)

# Salary bounds for filtering — the single source of truth lives in
# job_title_stats.py; a duplicated literal here once drifted from the
# render-time floor and made the profile card disagree with the charts.
from lib.business.salary.job_title_stats import (  # noqa: E402
    MAX_REASONABLE_SALARY,
    MIN_REASONABLE_SALARY,
)

# Years for "recent" filings (autocomplete ranking); must match webapp/views/job_titles/directory.AUTOCOMPLETE_YEARS
RECENT_YEARS = 5

# Batch sizes for bulk updates (avoid loading full tables into memory)
JOB_TITLE_BATCH_SIZE = 2000
CLUSTER_BATCH_SIZE = 500


def _most_frequent_raw_title_per_job_title() -> list[tuple[int, str]]:
    """
    Return [(job_title_id, most_frequent_raw_title), ...] using one indexed query.

    Uses SalaryRecord.job_title_entity_id (indexed) and GROUP BY + ROW_NUMBER.
    """
    sql = """
    WITH ranked AS (
        SELECT
            job_title_entity_id AS id,
            job_title,
            COUNT(*) AS cnt,
            ROW_NUMBER() OVER (PARTITION BY job_title_entity_id ORDER BY COUNT(*) DESC) AS rn
        FROM salary_record
        WHERE job_title_entity_id IS NOT NULL
        GROUP BY job_title_entity_id, job_title
    )
    SELECT id, job_title FROM ranked WHERE rn = 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return [(row[0], row[1]) for row in cursor.fetchall()]


def _stats_per_job_title() -> list[tuple[int, int, Decimal | None]]:
    """
    Return [(job_title_id, total_filings, avg_salary), ...] using one indexed query.

    Per-entity COUNT + AVG(wage_annual) over the same reasonable-salary bounds
    as the cluster stats, so the Related Roles table's "Filings" and "Avg
    Salary" columns use the SAME definition as the profile's Total Filings card
    (previously JobTitle.total_filings came from backfill_job_title_links with
    no wage bounds, so the related-roles counts didn't sum to the card).
    """
    sql = """
    SELECT
        job_title_entity_id AS id,
        CAST(COUNT(*) AS INTEGER) AS total_filings,
        AVG(wage_annual) AS avg_salary
    FROM salary_record
    WHERE job_title_entity_id IS NOT NULL
      AND wage_annual IS NOT NULL
      AND wage_annual >= %s
      AND wage_annual <= %s
    GROUP BY job_title_entity_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [MIN_REASONABLE_SALARY, MAX_REASONABLE_SALARY])
        return [(row[0], row[1], row[2]) for row in cursor.fetchall()]


def _zero_orphaned_job_titles() -> int:
    """
    Zero JobTitles that hold a stale total_filings but own no qualifying record.

    Both queries that drive the JobTitle update loop read FROM salary_record, so
    a JobTitle whose records were all re-linked away during a re-cluster appears
    in neither and the loop never visits it — it keeps whichever total_filings
    it last had. `related_titles` excludes only total_filings=0, so those rows
    still render on the profile, each adding filings the Total Filings card does
    not count. Driving this from the JobTitle side is what makes the Related
    Roles column sum to the card.

    Returns the number of rows zeroed.
    """
    sql = """
    UPDATE salary_job_title AS jt
    SET total_filings = 0, avg_salary = NULL
    WHERE jt.total_filings > 0
      AND NOT EXISTS (
          SELECT 1 FROM salary_record sr
          WHERE sr.job_title_entity_id = jt.id
            AND sr.wage_annual IS NOT NULL
            AND sr.wage_annual >= %s
            AND sr.wage_annual <= %s
      )
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [MIN_REASONABLE_SALARY, MAX_REASONABLE_SALARY])
        return cursor.rowcount


def _most_frequent_raw_title_per_cluster() -> list[tuple[int, str]]:
    """
    Return [(cluster_id, display_title), ...] using one query.

    Picks the most frequent raw title among records whose normalized title
    (JobTitle.title_normalized) equals the cluster's most frequent normalized form.
    Order: (1) count DESC so the dominant raw title wins, (2) shorter length as
    tiebreaker. So "Software Engineer" (47k) wins over "Programmer" (666).
    """
    sql = """
    WITH cluster_top_normalized AS (
        SELECT
            jt.canonical_cluster_id AS id,
            jt.title_normalized,
            COUNT(*) AS cnt,
            ROW_NUMBER() OVER (
                PARTITION BY jt.canonical_cluster_id
                ORDER BY COUNT(*) DESC
            ) AS rn
        FROM salary_record sr
        JOIN salary_job_title jt ON sr.job_title_entity_id = jt.id
        WHERE jt.canonical_cluster_id IS NOT NULL
        GROUP BY jt.canonical_cluster_id, jt.title_normalized
    ),
    cluster_mode_normalized AS (
        SELECT id, title_normalized FROM cluster_top_normalized WHERE rn = 1
    ),
    ranked_raw AS (
        SELECT
            jt.canonical_cluster_id AS id,
            sr.job_title,
            ROW_NUMBER() OVER (
                PARTITION BY jt.canonical_cluster_id
                ORDER BY
                    COUNT(*) DESC,
                    LENGTH(TRIM(sr.job_title)) ASC
            ) AS rn
        FROM salary_record sr
        JOIN salary_job_title jt ON sr.job_title_entity_id = jt.id
        JOIN cluster_mode_normalized c
            ON jt.canonical_cluster_id = c.id AND jt.title_normalized = c.title_normalized
        WHERE jt.canonical_cluster_id IS NOT NULL
        GROUP BY jt.canonical_cluster_id, sr.job_title
    )
    SELECT id, job_title FROM ranked_raw WHERE rn = 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return [(row[0], row[1]) for row in cursor.fetchall()]


def _stats_by_cluster() -> list[tuple[int, int, Decimal | None]]:
    """
    Return [(cluster_id, total_filings, avg_salary), ...] using one query.

    Counts SalaryRecords for JobTitles in each cluster (wage_annual in reasonable
    bounds). Each cluster gets its true total so directory "Popular Job Titles"
    and profile "Total Filings" match.
    """
    sql = """
    SELECT
        jt.canonical_cluster_id AS cluster_id,
        CAST(COUNT(*) AS INTEGER) AS total_filings,
        AVG(sr.wage_annual) AS avg_salary
    FROM salary_record sr
    JOIN salary_job_title jt ON sr.job_title_entity_id = jt.id
    WHERE jt.canonical_cluster_id IS NOT NULL
      AND sr.wage_annual IS NOT NULL
      AND sr.wage_annual >= %s
      AND sr.wage_annual <= %s
    GROUP BY jt.canonical_cluster_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [MIN_REASONABLE_SALARY, MAX_REASONABLE_SALARY])
        return [(row[0], row[1], row[2]) for row in cursor.fetchall()]


def _recent_filings_by_cluster() -> list[tuple[int, int]]:
    """
    Return [(cluster_id, total_filings_recent), ...] using one query.

    Counts SalaryRecords in each cluster with fiscal_year >= (current_year - RECENT_YEARS).
    Used for autocomplete ranking so recent titles rank higher.
    """
    from datetime import datetime

    start_year = datetime.now().year - RECENT_YEARS
    sql = """
    SELECT
        jt.canonical_cluster_id AS cluster_id,
        CAST(COUNT(*) AS INTEGER) AS total_filings_recent
    FROM salary_record sr
    JOIN salary_job_title jt ON sr.job_title_entity_id = jt.id
    WHERE jt.canonical_cluster_id IS NOT NULL
      AND sr.fiscal_year >= %s
    GROUP BY jt.canonical_cluster_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [start_year])
        return [(row[0], row[1]) for row in cursor.fetchall()]


def main():
    parser = argparse.ArgumentParser(
        description="Update JobTitleCluster and JobTitle stats and representative titles"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without making changes",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={"dry_run": args.dry_run},
        context="Update JobTitleCluster and JobTitle stats and representative titles from SalaryRecords",
    )

    logger.info("Updating JobTitleCluster and JobTitle statistics...")
    logger.info("=" * 80)

    if args.dry_run:
        logger.info(
            "DRY RUN: would run 5 bulk SQL queries then batch-update JobTitle and JobTitleCluster"
        )
        n_jt = _most_frequent_raw_title_per_job_title()
        n_avg = _stats_per_job_title()
        n_cl = _most_frequent_raw_title_per_cluster()
        n_st = _stats_by_cluster()
        n_recent = _recent_filings_by_cluster()
        logger.info("  JobTitle representative titles: %s rows", f"{len(n_jt):,}")
        logger.info("  JobTitle avg_salary: %s rows", f"{len(n_avg):,}")
        logger.info(
            "  JobTitleCluster representative titles: %s rows", f"{len(n_cl):,}"
        )
        logger.info("  Stats by cluster: %s rows", f"{len(n_st):,}")
        logger.info(
            "  Recent filings by cluster (last %s years): %s rows",
            RECENT_YEARS,
            f"{len(n_recent):,}",
        )
        if n_jt:
            logger.info(
                "  Sample JobTitle update: id=%s -> %s", n_jt[0][0], n_jt[0][1][:50]
            )
        if n_cl:
            logger.info(
                "  Sample cluster canonical_title: id=%s -> %s",
                n_cl[0][0],
                n_cl[0][1][:50],
            )
        return

    # 1) Bulk SQL: most frequent raw title per JobTitle
    logger.info("Query 1/5: Most frequent raw title per JobTitle...")
    job_title_updates = _most_frequent_raw_title_per_job_title()
    logger.info(
        "  Got %s JobTitle representative titles", f"{len(job_title_updates):,}"
    )

    # 2) Bulk SQL: total_filings + avg_salary per JobTitle (Related Roles columns)
    logger.info("Query 2/5: Filings + avg salary per JobTitle...")
    stats_by_job_title = {
        row[0]: (row[1], row[2]) for row in _stats_per_job_title()
    }
    logger.info(
        "  Got filings/avg_salary for %s JobTitles", f"{len(stats_by_job_title):,}"
    )

    # 3) Bulk SQL: most frequent raw title per cluster
    logger.info("Query 3/5: Most frequent raw title per cluster...")
    cluster_canonical = dict(_most_frequent_raw_title_per_cluster())
    logger.info("  Got %s cluster representative titles", f"{len(cluster_canonical):,}")

    # 4) Bulk SQL: stats by cluster (total_filings, avg_salary)
    # Each cluster gets its true total so directory and profile counts match.
    logger.info("Query 4/5: Stats by cluster (total_filings, avg_salary)...")
    stats_by_cluster_list = _stats_by_cluster()
    stats_by_cluster = {row[0]: (row[1], row[2]) for row in stats_by_cluster_list}
    logger.info("  Got stats for %s clusters", f"{len(stats_by_cluster):,}")

    # 5) Bulk SQL: recent filings by cluster (last RECENT_YEARS years, for autocomplete)
    logger.info("Query 5/5: Recent filings by cluster (last %s years)...", RECENT_YEARS)
    recent_by_cluster_list = _recent_filings_by_cluster()
    recent_by_cluster = {row[0]: row[1] for row in recent_by_cluster_list}
    logger.info("  Got recent filings for %s clusters", f"{len(recent_by_cluster):,}")

    # Batch-update JobTitle.title + total_filings + avg_salary (only mark changed
    # where different; bulk_update sends the full batch either way).
    logger.info("Updating JobTitle.title + total_filings + avg_salary...")
    title_updated_count = 0
    avg_updated_count = 0
    filings_updated_count = 0
    for i in range(0, len(job_title_updates), JOB_TITLE_BATCH_SIZE):
        batch = job_title_updates[i : i + JOB_TITLE_BATCH_SIZE]
        ids = [b[0] for b in batch]
        titles_by_id = {b[0]: b[1] for b in batch}
        job_titles = list(JobTitle.objects.filter(id__in=ids))
        for jt in job_titles:
            new_title = titles_by_id.get(jt.id)
            if new_title is not None and new_title != jt.title:
                jt.title = new_title
                title_updated_count += 1
            new_count, new_avg = stats_by_job_title.get(jt.id, (0, None))
            if jt.total_filings != new_count:
                jt.total_filings = new_count
                filings_updated_count += 1
            if new_avg is not None and jt.avg_salary != new_avg:
                jt.avg_salary = new_avg
                avg_updated_count += 1
        if job_titles:
            bulk_update_batched(
                job_titles,
                batch_size=JOB_TITLE_BATCH_SIZE,
                fields=["title", "total_filings", "avg_salary"],
            )
        if (
            i + JOB_TITLE_BATCH_SIZE
        ) % 10000 < JOB_TITLE_BATCH_SIZE or i + JOB_TITLE_BATCH_SIZE >= len(
            job_title_updates
        ):
            logger.info(
                "  Processed %s/%s JobTitle batches",
                f"{(i + JOB_TITLE_BATCH_SIZE):,}",
                f"{len(job_title_updates):,}",
            )
    logger.info(
        "  Updated %s JobTitle titles + %s avg_salary values",
        f"{title_updated_count:,}",
        f"{avg_updated_count:,}",
    )

    # The loop above only visits JobTitles that own a record, so orphans left by
    # a re-cluster never reach it. Zero them from the JobTitle side.
    logger.info("Zeroing orphaned JobTitles (stale total_filings, no records)...")
    orphaned_zeroed = _zero_orphaned_job_titles()
    logger.info("  Zeroed %s orphaned JobTitles", f"{orphaned_zeroed:,}")

    # 5) Batch-update JobTitleCluster (total_filings, avg_salary, canonical_title, total_filings_recent)
    # total_filings/avg_salary from stats_by_cluster; total_filings_recent for autocomplete ranking.
    logger.info(
        "Updating JobTitleCluster (total_filings, avg_salary, canonical_title, total_filings_recent)..."
    )
    all_cluster_ids = list(
        JobTitleCluster.objects.order_by("id").values_list("id", flat=True)
    )
    canonical_updated = 0
    freshness_bumped = 0
    processed = 0
    now_ts = timezone.now()
    for i in range(0, len(all_cluster_ids), CLUSTER_BATCH_SIZE):
        batch_ids = all_cluster_ids[i : i + CLUSTER_BATCH_SIZE]
        clusters = list(JobTitleCluster.objects.filter(id__in=batch_ids))
        # Clusters whose page content actually changed this run get a fresh
        # `updated_at` (bulk_update bypasses auto_now). Trigger on the integer
        # filing counts or canonical_title — a truthful sitemap `lastmod`
        # freshness signal, never a cosmetic bump (Notion: sitemap-lastmod
        # ticket Part 2). avg_salary is excluded from the trigger to avoid
        # decimal-rounding false positives; it moves only when counts move.
        changed = []
        for c in clusters:
            total, avg_sal = stats_by_cluster.get(c.id, (0, None))
            recent = recent_by_cluster.get(c.id, 0)
            counts_changed = (
                c.total_filings != total or c.total_filings_recent != recent
            )
            c.total_filings = total
            c.avg_salary = avg_sal
            c.total_filings_recent = recent
            canonical_changed = False
            new_canonical = cluster_canonical.get(c.id)
            if new_canonical and new_canonical != c.canonical_title:
                c.canonical_title = new_canonical
                c.slug = None
                canonical_updated += 1
                canonical_changed = True
            if counts_changed or canonical_changed:
                c.updated_at = now_ts
                changed.append(c)
        if clusters:
            bulk_update_batched(
                clusters,
                batch_size=CLUSTER_BATCH_SIZE,
                fields=[
                    "total_filings",
                    "avg_salary",
                    "canonical_title",
                    "total_filings_recent",
                    "slug",
                ],
            )
        if changed:
            bulk_update_batched(
                changed, batch_size=CLUSTER_BATCH_SIZE, fields=["updated_at"]
            )
            freshness_bumped += len(changed)
        processed += len(clusters)
        if processed % 5000 == 0 or processed == len(all_cluster_ids):
            logger.info(
                "  Processed %s/%s clusters (%s%%)",
                f"{processed:,}",
                f"{len(all_cluster_ids):,}",
                f"{(processed / len(all_cluster_ids) * 100):.1f}",
            )

    logger.info("=" * 80)
    logger.info(
        "Done. Updated %s cluster canonical_titles (slugs nulled for re-generation by populate_job_title_slugs)",
        f"{canonical_updated:,}",
    )
    logger.info(
        "Bumped updated_at (sitemap freshness) on %s clusters whose filings/title changed",
        f"{freshness_bumped:,}",
    )


if __name__ == "__main__":
    main()
