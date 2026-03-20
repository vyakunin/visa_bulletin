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
    compose_file = root / "deployment" / "docker-compose.yml"
    override_file = root / "deployment" / "docker-compose.override.yml"
    compose_args = f"-f {shlex.quote(str(compose_file))}"
    # Include override file for stop too (compose needs same file set for service discovery)
    compose_with_override = (
        f"docker-compose {compose_args} -f {shlex.quote(str(override_file))}"
        f" stop 2>/dev/null || docker-compose {compose_args} stop 2>/dev/null || true"
    )
    stop_cmds = [
        "export DOCKER_HOST=unix:///var/run/docker.sock",
        f"cd {shlex.quote(str(root))}",
        f"({compose_with_override})",
        "(docker stop visa_bulletin_web visa_bulletin_web_blue visa_bulletin_web_green visa_bulletin_redis 2>/dev/null || true)",
        "(docker rm -f visa_bulletin_web_blue visa_bulletin_web_green 2>/dev/null || true)",
        # Stop system-level redis-server (non-Docker) so Docker Redis can bind to port 6379 later.
        "(sudo systemctl stop redis-server 2>/dev/null; sudo systemctl disable redis-server 2>/dev/null; sudo pkill redis-server 2>/dev/null) || true",
        # Use pgrep + kill excluding $$ so we don't kill the SSH-invoked shell (pkill -f matches
        # the shell's command line and would kill it, causing SSH exit 255).
        "(pgrep -f 'gunicorn.*django_config' | grep -v ^$$ | xargs -r kill 2>/dev/null) || true",
        # Kill stale pipeline processes left behind by previous runs (e.g. SSH timeout
        # kills the client but the remote binary keeps running as a zombie).
        "(pgrep -f 'backfill_job_title_links|backfill_source_file_date|cluster_job_titles"
        "|cluster_existing_employers|update_employer_stats|update_job_title_cluster_stats"
        "|populate_job_title_slugs|run_pipeline|manage_salary_indexes|warm_cache'"
        " | grep -v ^$$ | xargs -r kill 2>/dev/null) || true",
        f"(cd {shlex.quote(str(root))} && bazel shutdown 2>/dev/null) || true",
    ]
    cmd = " && ".join(stop_cmds)
    result = runner.run_shell(cmd, timeout_sec=120)
    if result.returncode != 0:
        logger.warning(
            "stop_remote_services had non-zero exit %s (stdout: %r stderr: %r)",
            result.returncode,
            result.stdout,
            result.stderr,
        )
    else:
        logger.info("Stopped remote services (Docker/Gunicorn/Bazel)")


def start_remote_services(runner: Runner, project_root: Path) -> None:
    """
    On the target host: start Docker web+redis (compose up -d), then ensure nginx is running
    so port 80 proxies to the app (orchestrator health check uses http://ip:80/health/).
    Uses image from CI: IMAGE_TAG=<branch>-<short_sha> (e.g. staging-d696786). No volume mount.
    """
    root = project_root if isinstance(project_root, Path) else Path(project_root)
    compose_file = os.environ.get(
        "REFRESH_REMOTE_COMPOSE_FILE",
        str(root / "deployment" / "docker-compose.yml"),
    )
    override_file = str(root / "deployment" / "docker-compose.override.yml")
    compose_args = f"-f {shlex.quote(compose_file)}"
    # Kill any gunicorn that may have been started manually (e.g. during debugging)
    # after stop_remote_services() was called. This prevents port 8000 conflicts when
    # Docker tries to bind. Use pgrep+kill (not pkill -f) to avoid killing the SSH shell.
    runner.run_shell(
        "(pgrep -f 'gunicorn.*django_config' | grep -v ^$$ | xargs -r kill 2>/dev/null) || true",
        timeout_sec=10,
    )
    cleanup_cmd = (
        f"export DOCKER_HOST=unix:///var/run/docker.sock && cd {shlex.quote(str(root))} && "
        f"docker rm -f visa_bulletin_web visa_bulletin_redis 2>/dev/null; "
        f"docker-compose {compose_args} down --remove-orphans 2>/dev/null || true"
    )
    runner.run_shell(cleanup_cmd, timeout_sec=60)
    # Use image built from current branch (staging-<sha> or prod-<sha>).
    image_tag_cmd = (
        f"cd {shlex.quote(str(root))} && "
        "BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) && "
        "SHA=$(git rev-parse --short HEAD 2>/dev/null) && "
        'echo "${BRANCH}-${SHA}"'
    )
    tag_result = runner.run_shell(image_tag_cmd, timeout_sec=5)
    image_tag = (tag_result.stdout or "").strip() or "latest"
    # Guard: if the inactive host is on 'prod' branch, the image tag will be prod-<sha>
    # which doesn't exist in CI (CI builds staging-<sha> for staging deployments).
    # This happens when the host was last used as prod and wasn't switched to staging
    # before the orchestrator ran. Fail early with a clear message.
    if image_tag.startswith("prod-"):
        raise RuntimeError(
            f"Inactive host is on 'prod' branch (image tag would be {image_tag!r}). "
            "Switch it to 'staging' first: "
            "git fetch origin staging && git reset --hard origin/staging"
        )
    pull_and_up_cmd = (
        f"export DOCKER_HOST=unix:///var/run/docker.sock && "
        f"cd {shlex.quote(str(root))} && "
        "set -a && [ -f .env ] && source .env; set +a && "
        f"export IMAGE_TAG={shlex.quote(image_tag)} && "
        f"docker pull ghcr.io/vyakunin/visa_bulletin:{shlex.quote(image_tag)} && "
        f"( [ -f {shlex.quote(override_file)} ] && "
        f"  docker-compose {compose_args} -f {shlex.quote(override_file)} up -d || "
        f"  docker-compose {compose_args} up -d )"
    )
    result = runner.run_shell(pull_and_up_cmd, timeout_sec=300)
    if result.returncode != 0:
        logger.error("start_remote_services failed: %s", result.stderr)
        raise RuntimeError(f"Failed to start remote services: {result.stderr}")
    logger.info("Started remote services (Docker compose)")
    # Ensure nginx conf.d has log format and gptbot zone so any site config that uses
    # main_timed or limit_req zone=gptbot (e.g. visa-bulletin-locations.conf) works.
    nginx_confd_cmd = (
        f"sudo cp {shlex.quote(str(root))}/deployment/nginx/visa-bulletin-log-format.conf /etc/nginx/conf.d/ && "
        f"sudo cp {shlex.quote(str(root))}/deployment/nginx/gptbot-rate-limit.conf /etc/nginx/conf.d/"
    )
    runner.run_shell(nginx_confd_cmd, timeout_sec=10)
    # Ensure nginx has a default server block so the app is reachable by IP (not just
    # visa-bulletin.us). Use repo file to avoid shell-escaping of $host etc.
    default_server_src = str(root / "deployment" / "nginx" / "default-server.conf")
    nginx_cmd = (
        f"sudo cp {shlex.quote(default_server_src)} /etc/nginx/sites-enabled/default-server && "
        "sudo nginx -t 2>/dev/null "
        "&& sudo systemctl start nginx 2>/dev/null || true "
        "&& sudo systemctl reload nginx 2>/dev/null || true"
    )
    nginx_result = runner.run_shell(nginx_cmd, timeout_sec=30)
    if nginx_result.returncode != 0:
        logger.warning(
            "nginx default-server setup had non-zero exit %s (stderr: %s)",
            nginx_result.returncode,
            nginx_result.stderr,
        )
    else:
        logger.info("Nginx started/reloaded with default-server block for IP access")


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


def setup_bulletin_cron_on_remote(runner: Runner, project_root: Path) -> bool:
    """Set up the hourly visa bulletin refresh cron job on the target host.

    Builds the refresh_bulletin binary (if missing), creates the log directory,
    and runs deployment/cron/setup-ingest-cron.sh to install the cron entries.
    Returns True on success.
    """
    root = shlex.quote(str(project_root))
    cmd = (
        f"cd {root} && "
        "sudo mkdir -p /var/log/visa-bulletin && "
        "sudo chown $(whoami):$(whoami) /var/log/visa-bulletin && "
        # Always rebuild so the cron binary reflects code after the git branch switch,
        # not the potentially-stale binary built earlier in the pipeline from staging code.
        # Bazel uses its action cache so this is fast (~5s) if nothing changed.
        "bazel build //scripts/cron:refresh_bulletin && bazel shutdown && "
        "bash deployment/cron/setup-ingest-cron.sh"
    )
    result = runner.run_shell(cmd, timeout_sec=300)
    if result.returncode != 0:
        logger.warning(
            "setup_bulletin_cron_on_remote failed (rc=%s): %s",
            result.returncode,
            ((result.stderr or "") + (result.stdout or ""))[:500],
        )
        return False
    logger.info("Bulletin cron job set up on remote host")
    return True


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
        raw = os.environ.get(
            "REFRESH_HTTPS_DOMAINS", "visa-bulletin.us,www.visa-bulletin.us"
        ).strip()
        domains = [d.strip() for d in raw.split(",") if d.strip()]
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",") if d.strip()]
    if not domains:
        logger.warning("No HTTPS domains configured; skipping certbot")
        return True
    # certbot requires a separate -d flag for each domain; a single -d with multiple
    # values is rejected ("unrecognized arguments: www.visa-bulletin.us").
    domain_args = " ".join(f"-d {shlex.quote(d)}" for d in domains)
    cmd = (
        f"sudo certbot --nginx {domain_args} "
        "--non-interactive --agree-tos --register-unsafely-without-email"
    )
    result = runner.run_shell(cmd, timeout_sec=timeout_sec)
    if result.returncode != 0:
        logger.error("setup_https_on_remote failed: %s", result.stderr)
        return False
    logger.info("HTTPS set up on remote for %s", ", ".join(domains))
    return True
