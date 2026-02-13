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


def step_create_db(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
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


def step_drop_indexes_save_snapshot(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> str:
    """Drop indexes, save snapshot path. Returns snapshot path for context."""
    from datetime import datetime
    db = context.db_name or config.db_name
    # Clear stale RUNNING ingest runs so drop-index check passes (controlled refresh pipeline).
    runner.run_sudo_psql("UPDATE ingest_run SET status = 4 WHERE status = 2", db=db)
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
        tail = _get_stage_tail(runner, result)
        raise RuntimeError(f"Drop indexes failed: {tail[-2000:] if tail else 'no output'}")
    return str(snapshot)


def _get_stage_tail(
    runner: Runner, result: subprocess.CompletedProcess[str], n: int = 200
) -> str:
    """Get stage output tail: from stage log file (remote) or result.stdout/stderr (local)."""
    if hasattr(runner, "read_stage_log_tail"):
        return (runner.read_stage_log_tail(n) or "").strip()
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    return (out + "\n" + err).strip() if (out or err) else ""


def _log_stage_tail_text(tail_text: str, step_name: str, last_n: int = 80) -> None:
    """Log last N lines of stage output so orchestrator log has stage tail."""
    if not tail_text:
        return
    lines = tail_text.splitlines()
    tail = lines[-last_n:] if len(lines) > last_n else lines
    logger.info("[%s] stage output (last %d lines):", step_name, len(tail))
    for line in tail:
        logger.info("  %s", line)


# Ingest can take many hours (full LCA/PERM). Use 12h so SSH does not time out.
INGEST_SSH_TIMEOUT_SEC = 43200
# Employer clustering (Phase 1 + Phase 2 + _update_cluster_statistics) can exceed 4h on 2GB instances
CLUSTER_EMPLOYERS_SSH_TIMEOUT_SEC = 28800  # 8 hours


def step_run_ingest(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    """Run discover-and-ingest --all-domains."""
    result = runner.run_bin(
        "scripts/ingest/run_pipeline",
        "discover-and-ingest",
        "--all-domains",
        cwd=config.project_root,
        timeout_sec=INGEST_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "ingest_complete", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Ingest failed: {tail[-4000:] if tail else 'no output'}")


def step_backfill_job_title_links(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/backfill_job_title_links", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "backfill_links_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Backfill job title links failed: {tail[-2000:] if tail else result.stderr}")


def step_backfill_source_file_date(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/backfill_source_file_date", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "backfill_dates_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Backfill source file date failed: {tail[-2000:] if tail else result.stderr}")


def step_cluster_job_titles(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/cluster_job_titles", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "cluster_job_titles_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Cluster job titles failed: {tail[-2000:] if tail else result.stderr}")


def step_restore_indexes(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    db = context.db_name or config.db_name
    runner.run_sudo_psql("UPDATE ingest_run SET status = 4 WHERE status = 2", db=db)
    snapshot = context.index_snapshot
    if not snapshot:
        raise RuntimeError("Index snapshot path not set (index_snapshot_saved may not have run)")
    # Do not check Path(snapshot).exists() here: when using RemoteRunner the snapshot lives on
    # the remote host; this code runs on the orchestrator host, so a local exists() check is wrong.
    # If the file is missing on the remote, run_bin will fail with a clear error from manage_salary_indexes.
    result = runner.run_bin(
        "scripts/salary/manage_salary_indexes",
        "--recreate",
        "--snapshot", snapshot,
        cwd=config.project_root,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "indexes_restored", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Recreate indexes failed: {tail[-2000:] if tail else result.stderr}")


def step_update_employer_stats(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/update_employer_stats", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "employer_stats_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Update employer stats failed: {tail[-2000:] if tail else result.stderr}")


def step_cluster_employers(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin(
        "scripts/salary/cluster_existing_employers",
        cwd=config.project_root,
        timeout_sec=CLUSTER_EMPLOYERS_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "cluster_employers_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Cluster employers failed: {tail[-2000:] if tail else result.stderr}")


def step_update_job_title_cluster_stats(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/update_job_title_cluster_stats", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "job_title_stats_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Update job title cluster stats failed: {tail[-2000:] if tail else result.stderr}")


def step_populate_job_title_slugs(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/salary/populate_job_title_slugs", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "slugs_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Populate job title slugs failed: {tail[-2000:] if tail else result.stderr}")


def step_vacuum_analyze(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    db = context.db_name or config.db_name
    runner.run_psql(db, "VACUUM ANALYZE;")


def step_start_services(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    """Start Redis and Gunicorn on the target host so warm_cache HTTP page warming and smoke can reach the app."""
    from . import services
    services.start_remote_services(runner, config.project_root)


def step_warm_cache(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
    result = runner.run_bin("scripts/cache/warm_cache", cwd=config.project_root)
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "warm_cache_done", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Warm cache failed: {tail[-2000:] if tail else result.stderr}")


def step_run_smoke_tests(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
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
        tail = _get_stage_tail(runner, result)
        logger.warning("Ingest cleanup failed: %s", tail[-2000:] if tail else "no output")


def step_swap_db(config: RefreshConfig, runner: Runner, context: PipelineContext) -> None:
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
