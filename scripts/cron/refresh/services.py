# scripts/cron/refresh/services.py
"""Remote host services: stop/start Redis, Gunicorn, Bazel; wait SSH+DB; clean Postgres connections."""

from __future__ import annotations

import logging
import os
import shlex
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import Runner

logger = logging.getLogger(__name__)


def wait_ssh_and_db_ready(
    runner: Runner,
    db_name: str,
    timeout_sec: int = 600,
    poll_interval_sec: int = 10,
) -> bool:
    """Wait until SSH works and DB is reachable (run_psql SELECT 1). Returns True when ready."""
    deadline = time.monotonic() + timeout_sec
    last_out: str | None = None
    while time.monotonic() < deadline:
        out = runner.run_psql(db_name, "SELECT 1")
        last_out = out
        if out and out.strip() == "1":
            logger.info("SSH and DB ready (db=%s)", db_name)
            return True
        logger.debug("DB not ready yet: %s", out or "(empty)")
        time.sleep(poll_interval_sec)
    logger.warning(
        "SSH/DB not ready after %ss (db=%s); last run_psql output: %r",
        timeout_sec,
        db_name,
        last_out if last_out is not None else "(none)",
    )
    return False


def stop_remote_services(runner: Runner, project_root: Path) -> None:
    """
    On the target host: stop Docker web+redis, any Gunicorn, and Bazel.
    Frees memory for the pipeline. Uses run_shell; safe to no-op if not present.
    """
    root = project_root if isinstance(project_root, Path) else Path(project_root)
    compose_blue = root / "deployment" / "docker-compose.blue.yml"
    compose_green = root / "deployment" / "docker-compose.green.yml"
    # Stop Docker stacks (ignore errors if not using Docker). DOCKER_HOST for remote consistency.
    stop_cmds = [
        "export DOCKER_HOST=unix:///var/run/docker.sock",
        f"cd {shlex.quote(str(root))}",
        f"(docker-compose -f {shlex.quote(str(compose_blue))} stop 2>/dev/null || true)",
        f"(docker-compose -f {shlex.quote(str(compose_green))} stop 2>/dev/null || true)",
        "(docker stop visa_bulletin_web_blue visa_bulletin_web_green visa_bulletin_redis 2>/dev/null || true)",
        "pkill -f 'gunicorn.*django_config' || true",
        f"(cd {shlex.quote(str(root))} && bazel shutdown 2>/dev/null) || true",
    ]
    cmd = " && ".join(stop_cmds)
    result = runner.run_shell(cmd, timeout_sec=120)
    if result.returncode != 0:
        logger.warning("stop_remote_services had non-zero exit %s (stderr: %s)", result.returncode, result.stderr)
    else:
        logger.info("Stopped remote services (Docker/Gunicorn/Bazel)")


def start_remote_services(runner: Runner, project_root: Path) -> None:
    """
    On the target host: start Docker web+redis (compose up -d).
    Uses REFRESH_REMOTE_COMPOSE_FILE or defaults to docker-compose.blue.yml.
    """
    root = project_root if isinstance(project_root, Path) else Path(project_root)
    compose_file = os.environ.get(
        "REFRESH_REMOTE_COMPOSE_FILE",
        str(root / "deployment" / "docker-compose.blue.yml"),
    )
    # Use docker-compose (standalone) and explicit DOCKER_HOST so remote host (e.g. staging)
    # talks to local daemon; avoids "Not supported URL scheme http+docker" from docker-compose v1.
    cmd = f"export DOCKER_HOST=unix:///var/run/docker.sock && cd {shlex.quote(str(root))} && docker-compose -f {shlex.quote(compose_file)} up -d"
    result = runner.run_shell(cmd, timeout_sec=180)
    if result.returncode != 0:
        logger.error("start_remote_services failed: %s", result.stderr)
        raise RuntimeError(f"Failed to start remote services: {result.stderr}")
    logger.info("Started remote services (Docker compose)")


def ensure_postgres_connections_clean(runner: Runner, db_name: str) -> None:
    """
    Terminate idle connections to the target DB so the pipeline uses a clean connection set.
    Only terminates idle backends; does not kill active queries.
    """
    # Terminate idle connections in the target database (current user's or all idle)
    sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid() AND state = 'idle'"
    )
    out = runner.run_psql(db_name, sql)
    if out and out.strip():
        logger.info("Terminated idle Postgres connections (db=%s)", db_name)
    else:
        logger.debug("No idle connections to terminate (db=%s)", db_name)


def setup_https_on_remote(
    runner: Runner,
    domains: str | list[str] | None = None,
    timeout_sec: int = 120,
) -> bool:
    """
    On the target host: run certbot --nginx to obtain/renew SSL and enable HTTPS.
    Domains from REFRESH_HTTPS_DOMAINS (comma-separated) or default visa-bulletin.us, www.visa-bulletin.us.
    Returns True on success.
    """
    if domains is None:
        raw = os.environ.get("REFRESH_HTTPS_DOMAINS", "visa-bulletin.us,www.visa-bulletin.us").strip()
        domains = [d.strip() for d in raw.split(",") if d.strip()]
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",") if d.strip()]
    if not domains:
        logger.warning("No HTTPS domains configured; skipping certbot")
        return True
    domain_args = " ".join(shlex.quote(d) for d in domains)
    cmd = (
        f"sudo certbot --nginx -d {domain_args} "
        "--non-interactive --agree-tos --register-unsafely-without-email"
    )
    result = runner.run_shell(cmd, timeout_sec=timeout_sec)
    if result.returncode != 0:
        logger.error("setup_https_on_remote failed: %s", result.stderr)
        return False
    logger.info("HTTPS set up on remote for %s", ", ".join(domains))
    return True
