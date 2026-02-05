# scripts/cron/refresh/pipeline.py
"""Single pipeline: run_pipeline(config, runner, resume) -> int."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .checkpoint import CheckpointData, STEPS_ORDER, should_skip_step
from .config import RefreshConfig, get_env_value
from .discovery import check_new_sources
from . import steps

if TYPE_CHECKING:
    from .runner import Runner  # noqa: F401

logger = logging.getLogger(__name__)

STEP_FUNCS = {
    "db_created": steps.step_db_created,
    "indexes_dropped": steps.step_indexes_dropped,
    "ingest_complete": steps.step_ingest_complete,
    "backfill_links_done": steps.step_backfill_links_done,
    "backfill_dates_done": steps.step_backfill_dates_done,
    "cluster_job_titles_done": steps.step_cluster_job_titles_done,
    "indexes_recreated": steps.step_indexes_recreated,
    "employer_stats_done": steps.step_employer_stats_done,
    "cluster_employers_done": steps.step_cluster_employers_done,
    "job_title_stats_done": steps.step_job_title_stats_done,
    "slugs_done": steps.step_slugs_done,
    "vacuum_done": steps.step_vacuum_done,
    "warm_cache_done": steps.step_warm_cache_done,
    "smoke_done": steps.step_smoke_done,
    "swap_done": steps.step_swap_done,
}


def _inactive_db_from_env(config: RefreshConfig) -> str:
    """Return inactive DB name for two-DB host (blue <-> green)."""
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
            if step_name == "indexes_dropped" and result is not None:
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
        if step_name == "smoke_done":
            if ctx.record_count:
                pass  # already set in smoke if we want
        if step_name == "swap_done":
            if not config.single_db_on_host:
                runner.read_checkpoint(checkpoint_path)  # clear not needed; we remove file after swap in bash
            break
    return 0
