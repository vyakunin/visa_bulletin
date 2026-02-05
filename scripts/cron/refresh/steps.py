# scripts/cron/refresh/steps.py
"""Pipeline step functions: each takes (config, runner, context) and uses only runner.run_*."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import RefreshConfig
    from .runner import Runner

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Mutable context for pipeline steps: target db, index_snapshot path, etc."""

    db_name: str = ""
    index_snapshot: str = ""
    record_count: str = ""
    new_sources_count: int = 0


def step_db_created(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    """Create fresh DB, grant privileges, set DB_NAME in .env, run migrations."""
    db = context.db_name or config.db_name
    runner.run_sudo_psql(f"DROP DATABASE IF EXISTS {db};")
    runner.run_sudo_psql(f"CREATE DATABASE {db};")
    runner.run_sudo_psql(f"GRANT ALL PRIVILEGES ON DATABASE {db} TO {config.db_user};")
    runner.update_env("DB_NAME", db)
    result = runner.run_migrate(config.project_root)
    if result.returncode != 0:
        logger.error("Migrations failed: %s", result.stderr)
        raise RuntimeError("Migrations failed")


def step_indexes_dropped(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> str:
    """Drop indexes, save snapshot path. Returns snapshot path for context."""
    from datetime import datetime
    backup_dir = config.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    snapshot = backup_dir / f"salary_indexes_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.yaml"
    result = runner.run_bin(
        "scripts/salary/manage_salary_indexes",
        "--drop",
        "--snapshot", str(snapshot),
        "--overwrite",
        cwd=config.project_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Drop indexes failed: {result.stderr}")
    return str(snapshot)


def step_ingest_complete(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    """Run discover-and-ingest --all-domains."""
    result = runner.run_bin(
        "scripts/ingest/run_pipeline",
        "discover-and-ingest",
        "--all-domains",
        cwd=config.project_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ingest failed: {result.stderr}")


def step_backfill_links_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/backfill_job_title_links", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Backfill job title links failed: {result.stderr}")


def step_backfill_dates_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/backfill_source_file_date", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Backfill source file date failed: {result.stderr}")


def step_cluster_job_titles_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/cluster_job_titles", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Cluster job titles failed: {result.stderr}")


def step_indexes_recreated(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    snapshot = context.index_snapshot
    if not snapshot or not Path(snapshot).exists():
        raise RuntimeError(f"Index snapshot missing: {snapshot}")
    result = runner.run_bin(
        "scripts/salary/manage_salary_indexes",
        "--recreate",
        "--snapshot", snapshot,
        cwd=config.project_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Recreate indexes failed: {result.stderr}")


def step_employer_stats_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/update_employer_stats", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Update employer stats failed: {result.stderr}")


def step_cluster_employers_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/cluster_existing_employers", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Cluster employers failed: {result.stderr}")


def step_job_title_stats_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/update_job_title_cluster_stats", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Update job title cluster stats failed: {result.stderr}")


def step_slugs_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/populate_job_title_slugs", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Populate job title slugs failed: {result.stderr}")


def step_vacuum_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    db = context.db_name or config.db_name
    runner.run_psql(db, "VACUUM ANALYZE;")


def step_warm_cache_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/cache/warm_cache", cwd=config.project_root)
    if result.returncode != 0:
        raise RuntimeError(f"Warm cache failed: {result.stderr}")


def step_smoke_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    from .smoke import run_smoke_tests
    db = context.db_name or config.db_name
    run_smoke_tests(runner, db, config)
    # Cleanup ingest metadata (not checkpointed)
    result = runner.run_bin(
        "scripts/ingest/run_pipeline",
        "cleanup",
        "--days", "30",
        cwd=config.project_root,
    )
    if result.returncode != 0:
        logger.warning("Ingest cleanup failed: %s", result.stderr)


def step_swap_done(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    """DB swap (two-DB host) or no-op (single-DB host)."""
    if config.single_db_on_host:
        return
    from datetime import datetime
    from .config import get_env_value
    current_db = get_env_value(config.env_file, "DB_NAME") or ""
    if current_db == context.db_name:
        return
    backup_dir = config.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"visa_bulletin_archive_{current_db}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sql.gz"
    archive_path = backup_dir / archive_name
    env = dict(os.environ)
    env.setdefault("PGPASSWORD", "")
    proc = subprocess.run(
        ["pg_dump", "-h", config.db_host, "-U", config.db_user, current_db],
        env=env,
        capture_output=True,
        cwd=str(config.project_root),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {proc.stderr.decode()}")
    gz = subprocess.run(["gzip", "-c"], input=proc.stdout, capture_output=True)
    archive_path.write_bytes(gz.stdout)
    archives = sorted(
        backup_dir.glob("visa_bulletin_archive_*.sql.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in archives[config.max_backups:]:
        old.unlink()
    runner.update_env("DB_NAME", context.db_name)
    active_env = runner.detect_active_env()
    compose = config.project_root / "deployment" / f"docker-compose.{active_env}.yml"
    result = subprocess.run(
        ["docker-compose", "-f", str(compose), "restart", f"web-{active_env}"],
        cwd=str(config.project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        runner.update_env("DB_NAME", current_db)
        raise RuntimeError(f"Restart failed: {result.stderr}")
    time.sleep(5)
    new_active = get_env_value(config.env_file, "DB_NAME")
    if new_active != context.db_name:
        runner.update_env("DB_NAME", current_db)
        subprocess.run(
            ["docker-compose", "-f", str(compose), "restart", f"web-{active_env}"],
            cwd=str(config.project_root),
            capture_output=True,
        )
        raise RuntimeError(f"Swap verification failed: expected {context.db_name}, got {new_active}")
