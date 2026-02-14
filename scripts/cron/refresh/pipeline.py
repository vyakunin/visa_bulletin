# scripts/cron/refresh/pipeline.py
"""Single pipeline: run_pipeline(config, runner, resume) -> int."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .checkpoint import CheckpointData, OLD_STEP_NAME_TO_NEW, STEPS_ORDER, should_skip_step
from .config import RefreshConfig, get_env_value
from .discovery import check_new_sources
from . import steps

if TYPE_CHECKING:
    from .runner import Runner  # noqa: F401

logger = logging.getLogger(__name__)

STEP_FUNCS = {
    "db_created": steps.step_create_db,
    "index_snapshot_saved": steps.step_drop_indexes_save_snapshot,
    "ingest_complete": steps.step_run_ingest,
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
    "smoke_tests": steps.step_run_smoke_tests,
    "swap_db": steps.step_swap_db,
}


def _inactive_db_from_env(config: RefreshConfig) -> str:
    """Return inactive DB name for legacy two-DB host (blue <-> green). Instance rotation uses single DB per host."""
    current = get_env_value(config.env_file, "DB_NAME") or ""
    if current == "visa_bulletin_blue":
        return "visa_bulletin_green"
    if current == "visa_bulletin_green":
        return "visa_bulletin_blue"
    return current


def run_pipeline(config: RefreshConfig, runner: Runner, resume: bool) -> int:
    """Run pipeline: discovery, then steps in order; skip when should_skip_step; write checkpoint after each. Return 0 on success."""
    ctx = steps.PipelineContext()
    checkpoint_path = config.checkpoint_path
    resume_from: str | None = None
    checkpoint_data = runner.read_checkpoint(checkpoint_path)
    if checkpoint_data:
        checkpoint_data.last_step = OLD_STEP_NAME_TO_NEW.get(
            checkpoint_data.last_step, checkpoint_data.last_step
        )
    if resume and checkpoint_data:
        target_db = checkpoint_data.inactive_db or _inactive_db_from_env(config)
        if config.single_db_on_host:
            ctx.db_name = config.db_name
        else:
            ctx.db_name = target_db
            runner.update_env("DB_NAME", target_db)
        resume_from = checkpoint_data.last_step
        ctx.index_snapshot = checkpoint_data.index_snapshot or ""
        logger.info("Resuming from checkpoint: last_step=%s", resume_from)
    else:
        if config.single_db_on_host:
            ctx.db_name = config.db_name
        else:
            ctx.db_name = _inactive_db_from_env(config)
            runner.update_env("DB_NAME", ctx.db_name)
        if resume:
            logger.info("Resume requested but checkpoint missing or invalid; starting fresh")

    new_sources, discovery_out = check_new_sources(runner, str(config.project_root))
    ctx.new_sources_count = new_sources
    logger.info("Discovery: %s new sources", new_sources)
    for line in discovery_out.splitlines():
        if "Not ingested" in line or "Ingested" in line or "Broken" in line:
            logger.info("%s", line.strip())

    for step_name in STEPS_ORDER:
        if should_skip_step(resume_from, step_name):
            logger.info("Skipping step (resume): %s", step_name)
            continue
        func = STEP_FUNCS.get(step_name)
        if not func:
            raise RuntimeError(f"Unknown step: {step_name}")
        logger.info("Running step: %s", step_name)
        try:
            result = func(config, runner, ctx)
            if step_name == "index_snapshot_saved" and result is not None:
                ctx.index_snapshot = result
        except Exception as e:
            logger.exception("Step %s failed: %s", step_name, e)
            raise
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        data = CheckpointData(
            last_step=step_name,
            timestamp=ts,
            inactive_db=ctx.db_name,
            index_snapshot=ctx.index_snapshot or "",
        )
        runner.write_checkpoint(checkpoint_path, data)
        if step_name == "smoke_tests":
            if ctx.record_count:
                pass  # already set in smoke if we want
        if step_name == "swap_db":
            if not config.single_db_on_host:
                runner.read_checkpoint(checkpoint_path)  # clear not needed; we remove file after swap in bash
            break
    return 0
