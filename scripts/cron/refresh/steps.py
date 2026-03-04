# scripts/cron/refresh/steps.py
"""Pipeline step functions: each takes (config, runner, context) and uses only runner.run_*."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
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
    sources_ingested_count: int = -1  # Set by ingest_complete; -1 = not run yet
    salary_relevant_sources_ingested_count: int = (
        -1
    )  # DOL sources in this run; -1 = unknown, 0 = skip clustering
    domain: str | None = None  # Scope ingest to a single domain (e.g. "visa_bulletin")


SYNC_CODE_TIMEOUT_SEC = 600

# Build of all pipeline binaries (warm_cache, run_pipeline, etc.) can take 10–30 min on 2GB host
BUILD_PIPELINE_BINARIES_SSH_TIMEOUT_SEC = 7200


def step_sync_code(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Sync code on the target host (inactive) by pulling from the configured git branch.

    Uses REFRESH_SYNC_BRANCH (default: "staging") — runs git fetch + reset --hard on the
    target so it has the exact code from that branch.  More robust than rsync: works even
    when the orchestrator host is on a different branch, and .git history is preserved for
    rollback / inspection.

    Also creates deployment/docker-compose.override.yml on the target so the web container
    mounts the host's code directory instead of using the (potentially stale) Docker image code.
    No-op for local/mock runners.
    """
    from .runner import RemoteRunner

    if not isinstance(runner, RemoteRunner):
        return

    remote_root = str(config.project_root)
    branch = os.environ.get("REFRESH_SYNC_BRANCH", "staging")

    git_cmd = (
        f"cd {remote_root} && "
        f"git fetch origin {shlex.quote(branch)} && "
        f"git checkout -f {shlex.quote(branch)} 2>/dev/null || git checkout -b {shlex.quote(branch)} origin/{shlex.quote(branch)} && "
        f"git reset --hard origin/{shlex.quote(branch)}"
    )
    logger.info("Syncing code on %s via git (branch=%s)", runner.host, branch)
    result = runner.run_shell(git_cmd, timeout_sec=SYNC_CODE_TIMEOUT_SEC)
    if result.returncode != 0:
        raise RuntimeError(
            f"Code sync (git pull) failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout or '')[:2000]}"
        )
    logger.info("Code synced successfully (branch=%s)", branch)

    # Docker/gunicorn uses standard Python which requires __init__.py for packages.
    # Bazel handles imports via runfiles and doesn't need them, so they're not in the
    # repo. Auto-create for any Python package directory that's missing one.
    runner.run_shell(
        f"find {remote_root}/webapp {remote_root}/models {remote_root}/lib {remote_root}/extractors "
        f"-type d ! -path '*/__pycache__/*' "
        f'-exec sh -c \'test ! -f "$1/__init__.py" && touch "$1/__init__.py"\' _ {{}} \\;',
        timeout_sec=15,
    )
    logger.info("Ensured __init__.py files exist for Docker/gunicorn compatibility")

    # Ensure docker-compose.override.yml exists so the web container:
    # 1. Uses host code (volume mount) instead of stale Docker image code
    # 2. Has enough memory for query-heavy pages (512m vs default 200m)
    # 3. Has the inactive host's IP in ALLOWED_HOSTS (prevents Django 400)
    override_path = f"{remote_root}/deployment/docker-compose.override.yml"
    host_ip = runner.host
    allowed_hosts = (
        f"{host_ip},localhost,127.0.0.1,visa-bulletin.us,www.visa-bulletin.us"
    )
    override_content = (
        "version: '3.8'\n"
        "services:\n"
        "  web:\n"
        "    volumes:\n"
        "      - ../:/app\n"
        "    mem_limit: 512m\n"
        "    memswap_limit: 768m\n"
        "    environment:\n"
        "      - WEB_CONCURRENCY=1\n"
        f"      - ALLOWED_HOSTS={allowed_hosts}\n"
    )
    runner.run_shell(
        f"cat > {shlex.quote(override_path)} << 'OVERRIDE_EOF'\n{override_content}OVERRIDE_EOF",
        timeout_sec=10,
    )
    logger.info(
        "Created docker-compose.override.yml (volume mount, ALLOWED_HOSTS=%s)", host_ip
    )


def step_build_pipeline_binaries(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Build all pipeline binaries on the target host so runfiles include all deps (e.g. redis for warm_cache)."""
    root = config.project_root
    script = root / "scripts" / "cron" / "build_all.sh"
    cmd = f"cd {root} && bash {script}"
    result = runner.run_shell(cmd, timeout_sec=BUILD_PIPELINE_BINARIES_SSH_TIMEOUT_SEC)
    if result.returncode != 0:
        raise RuntimeError(
            f"Build pipeline binaries failed (exit {result.returncode}). "
            "Ensure scripts/cron/build_all.sh runs successfully on the host."
        )


def step_create_db(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Create fresh DB, grant privileges, set DB_NAME in .env, run migrations. Drops DB if exists (full reset only)."""
    db = context.db_name or config.db_name
    runner.run_sudo_psql(f"DROP DATABASE IF EXISTS {db};")
    runner.run_sudo_psql(f"CREATE DATABASE {db};")
    runner.run_sudo_psql(f"GRANT ALL PRIVILEGES ON DATABASE {db} TO {config.db_user};")
    runner.update_env("DB_NAME", db)
    result = runner.run_migrate(config.project_root)
    if result.returncode != 0:
        logger.error("Migrations failed: %s", result.stderr)
        raise RuntimeError("Migrations failed")


def step_ensure_db(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Ensure DB exists (create only if missing), grant privileges, fix ownership, set DB_NAME, run migrations."""
    db = context.db_name or config.db_name
    check = runner.run_sudo_psql(
        f"SELECT 1 FROM pg_database WHERE datname = '{db}';",
        db=None,
    )
    out = (check.stdout or "").strip()
    exists = "1" in out or out == "1"
    if not exists:
        runner.run_sudo_psql(f"CREATE DATABASE {db};")
    runner.run_sudo_psql(f"GRANT ALL PRIVILEGES ON DATABASE {db} TO {config.db_user};")
    _fix_db_ownership(runner, db, config.db_user)
    runner.update_env("DB_NAME", db)
    result = runner.run_migrate(config.project_root)
    if result.returncode != 0:
        logger.error(
            "Migrations failed: stdout=%s stderr=%s", result.stdout, result.stderr
        )
        raise RuntimeError("Migrations failed")


def _fix_db_ownership(runner: Runner, db: str, db_user: str) -> None:
    """Reassign ownership of all tables and sequences in public schema to db_user.

    Prevents 'must be owner of table/index' errors when tables were created
    by postgres superuser (e.g. during manual setup or old blue-green deploys).
    """
    fix_tables = (
        f"DO $$ DECLARE r RECORD; BEGIN "
        f"FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP "
        f"EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename) || ' OWNER TO {db_user}'; "
        f"END LOOP; END$$;"
    )
    fix_sequences = (
        f"DO $$ DECLARE r RECORD; BEGIN "
        f"FOR r IN SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public' LOOP "
        f"EXECUTE 'ALTER SEQUENCE public.' || quote_ident(r.sequence_name) || ' OWNER TO {db_user}'; "
        f"END LOOP; END$$;"
    )
    runner.run_sudo_psql(fix_tables, db=db)
    runner.run_sudo_psql(fix_sequences, db=db)
    logger.info("Fixed DB ownership for %s (tables+sequences -> %s)", db, db_user)


def step_drop_indexes_save_snapshot(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> str:
    """Drop indexes, save snapshot path. Returns snapshot path for context."""
    from datetime import datetime

    db = context.db_name or config.db_name
    # Clear stale RUNNING ingest runs so drop-index check passes (controlled refresh pipeline).
    runner.run_sudo_psql("UPDATE ingest_run SET status = 4 WHERE status = 2", db=db)
    backup_dir = config.backup_dir
    # Create backup dir on target host (local or remote) so snapshot path exists there.
    runner.run_shell(f"mkdir -p {shlex.quote(str(backup_dir))}")
    snapshot = (
        backup_dir
        / f"salary_indexes_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.yaml"
    )
    result = runner.run_bin(
        "scripts/salary/manage_salary_indexes",
        "--drop",
        "--snapshot",
        str(snapshot),
        "--overwrite",
        cwd=config.project_root,
    )
    if result.returncode != 0:
        tail = _get_stage_tail(runner, result)
        raise RuntimeError(
            f"Drop indexes failed: {tail[-2000:] if tail else 'no output'}"
        )
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
CLUSTER_EMPLOYERS_SSH_TIMEOUT_SEC = (
    24 * 3600
)  # 24 hours (Phase 1 + Phase 2 can take 8h+ on 2GB)
# Backfill, cluster_job_titles, update_employer_stats, etc. can exceed default 4h SSH timeout
HEAVY_STEP_SSH_TIMEOUT_SEC = 8 * 3600  # 8 hours


def _parse_sources_ingested_count(tail: str) -> int:
    """Parse run_pipeline output for 'Starting pipeline for N sources'; return N or 0."""
    match = re.search(r"Starting pipeline for (\d+) sources", tail)
    return int(match.group(1)) if match else 0


def _parse_salary_relevant_count(tail: str) -> int | None:
    """Parse run_pipeline output for '(salary_relevant: N)'; return N or None if not found."""
    match = re.search(r"salary_relevant:\s*(\d+)", tail)
    return int(match.group(1)) if match else None


def step_run_ingest(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> tuple[int, int | None]:
    """Run discover-and-ingest. Uses --domain if scoped, otherwise --all-domains. Returns (sources_count, salary_relevant_count or None)."""
    domain_args: list[str] = []
    if context.domain:
        domain_args = ["--domain", context.domain]
        logger.info("Ingest scoped to domain: %s", context.domain)
    else:
        domain_args = ["--all-domains"]
    result = runner.run_bin(
        "scripts/ingest/run_pipeline",
        "discover-and-ingest",
        *domain_args,
        cwd=config.project_root,
        timeout_sec=INGEST_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "ingest_complete", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(f"Ingest failed: {tail[-4000:] if tail else 'no output'}")
    sources_count = _parse_sources_ingested_count(tail)
    salary_relevant = _parse_salary_relevant_count(tail)
    return sources_count, salary_relevant


def step_backfill_job_title_links(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/salary/backfill_job_title_links",
        cwd=config.project_root,
        timeout_sec=HEAVY_STEP_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "backfill_job_title_links", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Backfill job title links failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_backfill_source_file_date(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/salary/backfill_source_file_date",
        cwd=config.project_root,
        timeout_sec=HEAVY_STEP_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "backfill_source_file_date", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Backfill source file date failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_cluster_job_titles(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/salary/cluster_job_titles",
        cwd=config.project_root,
        timeout_sec=HEAVY_STEP_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "cluster_job_titles", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Cluster job titles failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_restore_indexes(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    db = context.db_name or config.db_name
    runner.run_sudo_psql("UPDATE ingest_run SET status = 4 WHERE status = 2", db=db)
    snapshot = context.index_snapshot
    if not snapshot:
        raise RuntimeError(
            "Index snapshot path not set (index_snapshot_saved may not have run)"
        )
    # Do not check Path(snapshot).exists() here: when using RemoteRunner the snapshot lives on
    # the remote host; this code runs on the orchestrator host, so a local exists() check is wrong.
    # If the file is missing on the remote, run_bin will fail with a clear error from manage_salary_indexes.
    result = runner.run_bin(
        "scripts/salary/manage_salary_indexes",
        "--recreate",
        "--snapshot",
        snapshot,
        cwd=config.project_root,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "indexes_restored", last_n=80)
    if result.returncode != 0:
        tail_str = tail or (result.stderr or "")
        if "Snapshot file not found" in tail_str:
            logger.warning(
                "Snapshot file not found at %s; creating clustering indexes as fallback so pipeline can continue",
                snapshot,
            )
            fallback = runner.run_bin(
                "scripts/salary/manage_salary_indexes",
                "--create-clustering-indexes",
                cwd=config.project_root,
            )
            fallback_tail = _get_stage_tail(runner, fallback)
            _log_stage_tail_text(
                fallback_tail, "indexes_restored (fallback)", last_n=40
            )
            if fallback.returncode != 0:
                raise RuntimeError(
                    f"Recreate indexes failed (snapshot missing) and create-clustering-indexes fallback failed: "
                    f"{fallback_tail[-2000:] if fallback_tail else fallback.stderr}"
                )
            return
        raise RuntimeError(
            f"Recreate indexes failed: {tail_str[-2000:] if tail_str else result.stderr}"
        )


def step_update_employer_stats(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/salary/update_employer_stats",
        cwd=config.project_root,
        timeout_sec=HEAVY_STEP_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "update_employer_stats", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Update employer stats failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_cluster_employers(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Run employer clustering. Assumes indexes were restored (runs after indexes_restored)."""
    result = runner.run_bin(
        "scripts/salary/cluster_existing_employers",
        cwd=config.project_root,
        timeout_sec=CLUSTER_EMPLOYERS_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "cluster_employers", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Cluster employers failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_update_job_title_cluster_stats(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/salary/update_job_title_cluster_stats",
        cwd=config.project_root,
        timeout_sec=HEAVY_STEP_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "update_job_title_cluster_stats", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Update job title cluster stats failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_populate_job_title_slugs(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/salary/populate_job_title_slugs",
        cwd=config.project_root,
        timeout_sec=HEAVY_STEP_SSH_TIMEOUT_SEC,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "populate_job_title_slugs", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Populate job title slugs failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_vacuum_analyze(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    db = context.db_name or config.db_name
    runner.run_psql(db, "VACUUM ANALYZE;")


def step_start_services(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Start Redis and Gunicorn on the target host so warm_cache HTTP page warming and smoke can reach the app."""
    from . import services

    services.start_remote_services(runner, config.project_root)


def step_warm_cache(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    # Pipeline runs after start_services (Docker up); Redis is exposed as 127.0.0.1:6379 so warm_cache warms the same Redis the app uses.
    env_override = {"REDIS_URL": "redis://127.0.0.1:6379/1"}
    result = runner.run_bin(
        "scripts/cache/warm_cache",
        cwd=config.project_root,
        env_override=env_override,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "warm_cache", last_n=80)
    if result.returncode != 0:
        raise RuntimeError(
            f"Warm cache failed: {tail[-2000:] if tail else result.stderr}"
        )


def step_clear_sitemap_cache(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    result = runner.run_bin(
        "scripts/clear_cache",
        "--sitemap-only",
        cwd=config.project_root,
    )
    tail = _get_stage_tail(runner, result)
    _log_stage_tail_text(tail, "clear_sitemap_cache", last_n=20)
    if result.returncode != 0:
        logger.warning("Clear sitemap cache failed (non-fatal): %s", tail[-500:] if tail else result.stderr)


_SITEMAP_PING_URLS = [
    "https://www.google.com/ping?sitemap=https://visa-bulletin.us/sitemap.xml",
    "https://www.bing.com/ping?sitemap=https://visa-bulletin.us/sitemap.xml",
]


def step_ping_search_engines(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    """Notify Google and Bing that the sitemap has been updated."""
    import urllib.request

    for url in _SITEMAP_PING_URLS:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                logger.info("Sitemap ping %s → %s", url.split("?")[0].split("//")[1].split("/")[0], resp.status)
        except Exception as e:
            logger.warning("Sitemap ping failed for %s: %s", url, e)


def step_run_smoke_tests(
    config: RefreshConfig, runner: Runner, context: PipelineContext
) -> None:
    from .smoke import run_smoke_tests

    db = context.db_name or config.db_name
    run_smoke_tests(runner, db, config)
