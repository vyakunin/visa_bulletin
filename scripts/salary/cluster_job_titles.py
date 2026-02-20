#!/usr/bin/env python3
"""
Cluster job titles using the generic clustering framework.

This script:
1. Extracts and normalizes job titles from SalaryRecord
2. Creates JobTitle entities with experience levels
3. Clusters similar job titles using the generic clustering engine
4. Links SalaryRecords to their JobTitle entities

Usage:
    bazel run //scripts/salary:cluster_job_titles

    # With dry run mode:
    bazel run //scripts/salary:cluster_job_titles -- --dry-run

When to use:
- After importing salary data to normalize and cluster job titles
- Periodically to refresh job title clustering
- Before analyzing job title trends or salary distributions
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

import logging

from django_config.logging_config import setup_logging
from lib.business import clustering_engine
from lib.business.salary.job_title_config import JobTitleClusteringConfig
from lib.utils.db_utils import bulk_create_batched, bulk_update_batched
from lib.utils.logging_utils import ScriptLogger
from models.job_title import JobTitle
from models.salary import SalaryRecord

setup_logging(debug=False)
logger = logging.getLogger(__name__)

script_logger = ScriptLogger(__file__)

PHASE1_CHUNK_SIZE = 5000
PHASE2_CHUNK_SIZE = 5000
PHASE2_FLUSH_SIZE = 1000


def _phase1_create_job_titles():
    """Chunked bulk creation of JobTitle entities from unique SalaryRecord.job_title values.

    Returns (created_count, existing_count).
    """
    unique_titles_qs = (
        SalaryRecord.objects.order_by("job_title")
        .values_list("job_title", flat=True)
        .distinct()
    )
    total_unique = unique_titles_qs.count()
    logger.info("Found %s unique job title strings", f"{total_unique:,}")

    created_total = 0
    existing_total = 0
    chunk: list[str] = []

    for job_title_str in unique_titles_qs.iterator(chunk_size=PHASE1_CHUNK_SIZE):
        if not job_title_str:
            continue
        chunk.append(job_title_str)
        if len(chunk) < PHASE1_CHUNK_SIZE:
            continue

        c, e = _process_phase1_chunk(chunk)
        created_total += c
        existing_total += e
        logger.info(
            "Phase 1 progress: %s created, %s existing so far",
            f"{created_total:,}",
            f"{existing_total:,}",
        )
        chunk = []

    if chunk:
        c, e = _process_phase1_chunk(chunk)
        created_total += c
        existing_total += e

    return created_total, existing_total


def _process_phase1_chunk(raw_titles: list[str]) -> tuple[int, int]:
    """Process a chunk of raw job titles: normalize, diff against DB, bulk_create missing."""
    normalized_map: dict[tuple[str, str], str] = {}
    for raw in raw_titles:
        norm = JobTitle.normalize_title(raw)
        exp = JobTitle.extract_experience_level(raw)
        key = (norm, exp)
        if key not in normalized_map:
            normalized_map[key] = raw

    norm_values = [k[0] for k in normalized_map]
    existing_keys: set[tuple[str, str]] = set()
    for row in JobTitle.objects.filter(title_normalized__in=norm_values).values_list(
        "title_normalized", "experience_level"
    ):
        existing_keys.add((row[0], row[1]))

    to_create = []
    for key, raw_title in normalized_map.items():
        if key not in existing_keys:
            to_create.append(
                JobTitle(
                    title=raw_title,
                    title_normalized=key[0],
                    experience_level=key[1],
                    total_filings=0,
                )
            )

    if to_create:
        bulk_create_batched(to_create, batch_size=1000, ignore_conflicts=True)

    return len(to_create), len(normalized_map) - len(to_create)


def _phase2_cluster(config: JobTitleClusteringConfig):
    """Cluster job titles using bucket index + deferred flush.

    Builds the bucket index from lightweight .values() data, then processes
    unclustered titles in chunks with batched bulk_update.

    Returns (auto_clustered, new_clusters).
    """
    # Build bucket index from all JobTitles (needs full objects for clustering engine)
    all_job_titles = list(JobTitle.objects.select_related("canonical_cluster"))
    logger.info(
        "Building bucket index for %s job titles...", f"{len(all_job_titles):,}"
    )

    bucket_index, normalized_cache, bucket_cache = clustering_engine.build_bucket_index(
        all_job_titles, config
    )

    auto_clustered = 0
    new_clusters = 0
    flush_batch: list[JobTitle] = []

    for i, job_title in enumerate(all_job_titles, 1):
        if i % 5000 == 0:
            logger.info(
                "Phase 2 progress: %s/%s job titles",
                f"{i:,}",
                f"{len(all_job_titles):,}",
            )

        if job_title.canonical_cluster:
            continue

        old_cluster = job_title.canonical_cluster
        cluster = clustering_engine.assign_to_cluster(
            job_title,
            config,
            auto_approve_threshold=0.95,
            bucket_index=bucket_index,
            normalized_cache=normalized_cache,
            bucket_cache=bucket_cache,
            save=False,
        )

        if cluster:
            if cluster.total_filings == 0:
                new_clusters += 1
            auto_clustered += 1

            flush_batch.append(job_title)
            if len(flush_batch) >= PHASE2_FLUSH_SIZE:
                bulk_update_batched(
                    flush_batch,
                    fields=["canonical_cluster"],
                    batch_size=PHASE2_FLUSH_SIZE,
                )
                flush_batch = []

    if flush_batch:
        bulk_update_batched(
            flush_batch, fields=["canonical_cluster"], batch_size=PHASE2_FLUSH_SIZE
        )

    return auto_clustered, new_clusters


def _phase3_link_records():
    """Link SalaryRecords to JobTitle entities. Already uses bulk_update.

    Returns linked_count.
    """
    logger.info("Building JobTitle lookup index...")
    job_title_lookup: dict[tuple[str, str], int] = {}
    for jt_data in JobTitle.objects.values(
        "id", "title_normalized", "experience_level"
    ):
        key = (jt_data["title_normalized"], jt_data["experience_level"])
        job_title_lookup[key] = jt_data["id"]
    logger.info("Built index with %s JobTitle entities", f"{len(job_title_lookup):,}")

    total_unlinked = SalaryRecord.objects.filter(job_title_entity__isnull=True).count()
    logger.info("Processing %s unlinked salary records...", f"{total_unlinked:,}")

    linked_count = 0
    batch: list[SalaryRecord] = []
    batch_size = 10000

    for record in SalaryRecord.objects.filter(job_title_entity__isnull=True).iterator(
        chunk_size=10000
    ):
        normalized = JobTitle.normalize_title(record.job_title)
        experience_level = JobTitle.extract_experience_level(record.job_title)
        key = (normalized, experience_level)

        if key in job_title_lookup:
            record.job_title_entity_id = job_title_lookup[key]
            batch.append(record)

            if len(batch) >= batch_size:
                SalaryRecord.objects.bulk_update(
                    batch, ["job_title_entity_id"], batch_size=batch_size
                )
                linked_count += len(batch)
                if total_unlinked > 0:
                    logger.info(
                        "  Linked %s/%s records (%.1f%%)",
                        f"{linked_count:,}",
                        f"{total_unlinked:,}",
                        linked_count / total_unlinked * 100,
                    )
                batch = []

    if batch:
        SalaryRecord.objects.bulk_update(
            batch, ["job_title_entity_id"], batch_size=batch_size
        )
        linked_count += len(batch)

    return linked_count


def cluster_job_titles(dry_run: bool = False):
    """Cluster all job titles using the generic clustering framework."""
    config = JobTitleClusteringConfig()

    logger.info("=" * 80)
    logger.info("JOB TITLE CLUSTERING")
    logger.info("=" * 80)

    # Phase 1
    logger.info("\n" + "=" * 80)
    logger.info("Phase 1: Extract and normalize job titles from SalaryRecords")
    logger.info("=" * 80)

    created, existing = _phase1_create_job_titles()

    logger.info("Phase 1 complete:")
    logger.info("  - Created: %s new JobTitle entities", f"{created:,}")
    logger.info("  - Existing: %s JobTitle entities", f"{existing:,}")

    # Phase 2
    logger.info("\n" + "=" * 80)
    logger.info("Phase 2: Cluster job titles")
    logger.info("=" * 80)

    auto_clustered, new_clusters = _phase2_cluster(config)

    logger.info("Phase 2 complete:")
    logger.info("  - Auto-clustered: %s job titles", f"{auto_clustered:,}")
    logger.info("  - New clusters: %s", f"{new_clusters:,}")

    # Phase 3
    logger.info("\n" + "=" * 80)
    logger.info("Phase 3: Link SalaryRecords to JobTitle entities")
    logger.info("=" * 80)

    linked_count = 0
    if dry_run:
        logger.info("DRY RUN MODE: Skipping SalaryRecord linking")
    else:
        linked_count = _phase3_link_records()
        logger.info("Linked %s SalaryRecords to JobTitle entities", f"{linked_count:,}")
        logger.info("Note: Run update_job_title_cluster_stats to update statistics")

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("CLUSTERING SUMMARY")
    logger.info("=" * 80)
    total_jt = JobTitle.objects.count()
    logger.info("Job titles processed: %s", f"{total_jt:,}")
    logger.info("Auto-clustered: %s", f"{auto_clustered:,}")
    logger.info("New clusters created: %s", f"{new_clusters:,}")
    if not dry_run:
        logger.info("SalaryRecords linked: %s", f"{linked_count:,}")
    logger.info("=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Cluster job titles using the generic clustering framework"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Dry run mode (don't commit changes)"
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={"dry_run": args.dry_run},
        context="Clustering job titles using generic clustering framework",
    )

    try:
        cluster_job_titles(dry_run=args.dry_run)
    except Exception as e:
        logger.error("Clustering failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
