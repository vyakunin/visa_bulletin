# scripts/cron/refresh/pipeline.py
"""Single pipeline: run_pipeline(config, runner, resume) -> int."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from . import steps
from .checkpoint import (
    OLD_STEP_NAME_TO_NEW,
    STEPS_ORDER,
    CheckpointData,
    should_skip_step,
)
from .config import RefreshConfig
from .discovery import check_new_sources

# When ingest processes 0 sources (data already in DB), skip heavy post-processing.
# Exception: if DB has 0 clustered employers but enough salary records (e.g. after reset or restore),
# run post-processing so clustering is populated (self-heal).
STEPS_SKIP_WHEN_ZERO_INGESTED = frozenset(
    {
        "backfill_job_title_links",
        "backfill_source_file_date",
        "cluster_job_titles",
        "update_employer_stats",
        "cluster_employers",
        "update_job_title_cluster_stats",
        "populate_job_title_slugs",
        "vacuum_analyze",
    }
)
MIN_RECORDS_FOR_CLUSTER_SELF_HEAL = 100_000  # Same as smoke.MIN_RECORDS

if TYPE_CHECKING:
    from .runner import Runner  # noqa: F401

logger = logging.getLogger(__name__)

STEP_FUNCS = {
    "sync_code": steps.step_sync_code,
    "build_pipeline_binaries": steps.step_build_pipeline_binaries,
    "ensure_db": steps.step_ensure_db,
    "index_snapshot_saved": steps.step_drop_indexes_save_snapshot,
    "ingest_complete": steps.step_run_ingest,
    "populate_case_submitted": steps.step_populate_case_submitted,
    "backfill_job_title_links": steps.step_backfill_job_title_links,
    "backfill_source_file_date": steps.step_backfill_source_file_date,
    "cluster_job_titles": steps.step_cluster_job_titles,
    "indexes_restored": steps.step_restore_indexes,
    "update_employer_stats": steps.step_update_employer_stats,
    "cluster_employers": steps.step_cluster_employers,
    "update_job_title_cluster_stats": steps.step_update_job_title_cluster_stats,
    "populate_job_title_slugs": steps.step_populate_job_title_slugs,
    "vacuum_analyze": steps.step_vacuum_analyze,
    "start_services": steps.step_start_services,
    "warm_cache": steps.step_warm_cache,
    "clear_sitemap_cache": steps.step_clear_sitemap_cache,
    "ping_search_engines": steps.step_ping_search_engines,
    "smoke_tests": steps.step_run_smoke_tests,
}


def run_pipeline(
    config: RefreshConfig,
    runner: Runner,
    resume: bool,
    domain: str | None = None,
) -> int:
    """Run pipeline: discovery, then steps in order; skip when should_skip_step; write checkpoint after each. Return 0 on success."""
    ctx = steps.PipelineContext()
    ctx.domain = domain
    checkpoint_path = config.checkpoint_path
    resume_from: str | None = None
    ctx.db_name = config.db_name
    runner.update_env("DB_NAME", config.db_name)

    checkpoint_data = runner.read_checkpoint(checkpoint_path)
    if checkpoint_data:
        checkpoint_data.last_step = OLD_STEP_NAME_TO_NEW.get(
            checkpoint_data.last_step, checkpoint_data.last_step
        )
    if resume and checkpoint_data:
        resume_from = checkpoint_data.last_step
        ctx.index_snapshot = checkpoint_data.index_snapshot or ""
        logger.info("Resuming from checkpoint: last_step=%s", resume_from)
    elif resume:
        logger.info(
            "Resume requested but checkpoint missing or invalid; starting fresh"
        )

    new_sources, discovery_out = check_new_sources(
        runner, str(config.project_root), domain=domain
    )
    ctx.new_sources_count = new_sources
    logger.info("Discovery: %s new sources", new_sources)
    for line in discovery_out.splitlines():
        stripped = line.strip()
        if "Discovered new source:" in stripped:
            logger.info("  [new] %s", stripped)
        elif (
            "Not ingested" in stripped or "Ingested" in stripped or "Broken" in stripped
        ):
            logger.info("%s", stripped)

    pipeline_start = time.time()
    for step_name in STEPS_ORDER:
        if should_skip_step(resume_from, step_name):
            logger.info("Skipping step (resume): %s", step_name)
            continue
        skip_reason = None
        if step_name in STEPS_SKIP_WHEN_ZERO_INGESTED:
            if getattr(ctx, "sources_ingested_count", -1) == 0:
                skip_reason = "0 sources ingested, data already in DB"
            elif getattr(ctx, "salary_relevant_sources_ingested_count", -1) == 0:
                skip_reason = "0 salary-relevant (DOL) sources ingested, no employers/job titles to cluster"
        # Self-heal: if we would skip post-processing due to 0 ingested but DB has data and 0 clusters,
        # run this step (and subsequent ones) so clustering is populated (e.g. after restore from backup,
        # restore from backup, or resume from a checkpoint past backfill_job_title_links).
        # Applied at every skip decision for post-processing steps, not only at backfill_job_title_links,
        # so resume-from-later-step still triggers re-clustering when DB has 0 clustered and enough records.
        if skip_reason:
            db = ctx.db_name or config.db_name
            if db:
                try:
                    emp_s = runner.run_psql(
                        db,
                        "SELECT COUNT(*) FROM salary_employer WHERE canonical_cluster_id IS NOT NULL;",
                    )
                    rec_s = runner.run_psql(db, "SELECT COUNT(*) FROM salary_record;")
                    emp_clustered = int(emp_s.strip() or 0)
                    record_count = int(rec_s.strip() or 0)
                    if (
                        emp_clustered == 0
                        and record_count >= MIN_RECORDS_FOR_CLUSTER_SELF_HEAL
                    ):
                        skip_reason = None
                        logger.info(
                            "Not skipping post-processing: 0 clustered employers but %s records (re-running clustering)",
                            record_count,
                        )
                except (ValueError, TypeError) as e:
                    logger.warning("Could not check cluster self-heal: %s", e)
        if skip_reason:
            logger.info("Skipping step (%s): %s", skip_reason, step_name)
            ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            data = CheckpointData(
                last_step=step_name,
                timestamp=ts,
                inactive_db=ctx.db_name,
                index_snapshot=ctx.index_snapshot or "",
            )
            runner.write_checkpoint(checkpoint_path, data)
            continue
        func = STEP_FUNCS.get(step_name)
        if not func:
            raise RuntimeError(f"Unknown step: {step_name}")
        step_start = time.time()
        logger.info("Running step: %s", step_name)
        try:
            result = func(config, runner, ctx)
            if step_name == "index_snapshot_saved" and result is not None:
                ctx.index_snapshot = result
            if step_name == "ingest_complete":
                if isinstance(result, tuple):
                    ctx.sources_ingested_count = result[0]
                    ctx.salary_relevant_sources_ingested_count = (
                        result[1] if result[1] is not None else result[0]
                    )
                else:
                    ctx.sources_ingested_count = (
                        result if isinstance(result, int) else 0
                    )
                    ctx.salary_relevant_sources_ingested_count = -1
        except Exception as e:
            logger.exception("Step %s failed: %s", step_name, e)
            raise
        step_elapsed = time.time() - step_start
        logger.info(
            "Step %s completed in %.1f s (%.1f min)",
            step_name,
            step_elapsed,
            step_elapsed / 60,
        )
        ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        data = CheckpointData(
            last_step=step_name,
            timestamp=ts,
            inactive_db=ctx.db_name,
            index_snapshot=ctx.index_snapshot or "",
        )
        runner.write_checkpoint(checkpoint_path, data)
    total_elapsed = time.time() - pipeline_start
    logger.info(
        "Pipeline complete: all steps finished in %.1f s (%.1f min)",
        total_elapsed,
        total_elapsed / 60,
    )
    return 0
