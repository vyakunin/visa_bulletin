# scripts/cron/refresh/orchestrate.py
"""Orchestrator: resolve active/inactive, start inactive, run pipeline on inactive, smoke, (optional) traffic switch, stop old."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from . import instance
from . import services
from . import traffic_switch
from .config import RefreshConfig, load_config
from .pipeline import run_pipeline
from .runner import RemoteRunner

if TYPE_CHECKING:
    from .runner import Runner

logger = logging.getLogger(__name__)


def _wait_app_healthy_via_ssh(
    runner: Runner,
    timeout_sec: int = 300,
    poll_interval_sec: int = 10,
) -> bool:
    """Check app health by SSHing into the host and curling localhost:8000.

    More reliable than external HTTP: avoids nginx server_name mismatches,
    HTTP→HTTPS redirects, and security group restrictions on port 8000.
    """
    import time
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        result = runner.run_shell(
            "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/",
            timeout_sec=15,
        )
        code = (result.stdout or "").strip()
        if code == "200":
            logger.info("App healthy (HTTP 200 on localhost:8000)")
            return True
        logger.debug("Health check: HTTP %s", code or "(no response)")
        time.sleep(poll_interval_sec)
    return False


def run_orchestrate(
    config: RefreshConfig,
    safety_interval_sec: int = 1800,
    no_traffic_switch: bool = False,
    resume: bool = False,
    from_step: str | None = None,
) -> int:
    """
    Full cycle: resolve active/inactive -> start inactive -> wait healthy
    -> run pipeline with RemoteRunner(inactive) -> smoke -> (optional) traffic switch
    -> update new prod .env -> safety interval -> stop old.
    If no_traffic_switch is True, skip traffic switch and following steps (first validation).
    If from_step=="traffic_switch", skip instance start, pipeline, and pre-switch setup;
    assume inactive is up and pipeline done; ensure services, then do traffic switch and rest.
    Returns 0 on success.
    """
    active_info, inactive_info = instance.resolve_active_inactive_from_env()
    if not active_info or not inactive_info:
        logger.error("Orchestrator requires REFRESH_ACTIVE_* and REFRESH_INACTIVE_* env vars")
        return 1

    my_id = os.environ.get("REFRESH_MY_INSTANCE_NAME", "").strip() or os.environ.get("REFRESH_MY_INSTANCE_IP", "").strip()
    if my_id and not instance.is_this_host_active(my_id, active_info):
        logger.info("This host is inactive; no-op (orchestrator should run on active)")
        return 0

    logger.info("Active: %s (%s), Inactive: %s (%s)", active_info.name, active_info.ip, inactive_info.name, inactive_info.ip)

    project_root = os.environ.get("REFRESH_REMOTE_PROJECT_ROOT", "/opt/visa_bulletin")
    ssh_user = os.environ.get("REFRESH_SSH_USER", "ubuntu")
    ssh_key = os.environ.get("REFRESH_SSH_KEY_PATH", "")
    ssh_timeout_raw = os.environ.get("REFRESH_SSH_TIMEOUT", "14400").strip()
    ssh_timeout_sec = int(ssh_timeout_raw) if ssh_timeout_raw.isdigit() else 14400
    remote = RemoteRunner(
        host=inactive_info.ip,
        project_root=project_root,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key if ssh_key else None,
        ssh_timeout_sec=ssh_timeout_sec,
    )
    remote_root = Path(project_root)
    db_name = os.environ.get("REFRESH_REMOTE_DB_NAME", "visa_bulletin")

    skip_to_traffic_switch = from_step == "traffic_switch"
    if skip_to_traffic_switch:
        logger.info("--from-step traffic_switch: skipping instance start, pipeline; ensuring SSH and services, then switch")
        if not services.wait_ssh_and_db_ready(remote, db_name, timeout_sec=120):
            logger.error("Instance %s (%s): SSH or DB not ready", inactive_info.name, inactive_info.ip)
            return 1
        logger.info("Starting Redis and Gunicorn on inactive host for traffic switch")
        services.start_remote_services(remote, remote_root)
        if not _wait_app_healthy_via_ssh(remote, timeout_sec=300):
            logger.warning("Instance %s (%s) HTTP not healthy (non-fatal)", inactive_info.name, inactive_info.ip)
    else:
        assume_running = os.environ.get("REFRESH_ASSUME_INACTIVE_RUNNING", "").strip().lower() in ("1", "true", "yes")
        if assume_running:
            logger.info("REFRESH_ASSUME_INACTIVE_RUNNING: skipping instance state/start (assume inactive already running)")
        else:
            state = instance.get_instance_state(inactive_info.name)
            if state != "running":
                logger.info("Starting inactive instance %s", inactive_info.name)
                if not instance.start_instance(inactive_info.name):
                    logger.error("Failed to start %s", inactive_info.name)
                    return 1
                if not instance.wait_instance_running(inactive_info.name, timeout_sec=600):
                    logger.error("Instance %s did not reach running state", inactive_info.name)
                    return 1
            else:
                logger.info("Inactive instance %s already running", inactive_info.name)

        if not services.wait_ssh_and_db_ready(remote, db_name, timeout_sec=600):
            logger.error("Instance %s (%s): SSH or DB not ready", inactive_info.name, inactive_info.ip)
            return 1
        logger.info("Inactive instance SSH and DB ready at %s", inactive_info.ip)

        logger.info("Stopping Redis, Gunicorn, Bazel on inactive host to free memory")
        services.stop_remote_services(remote, remote_root)
        services.ensure_postgres_connections_clean(remote, db_name)

        logger.info("Running pipeline on inactive host %s", inactive_info.ip)
        remote_config = load_config(None)
        remote_config.project_root = remote_root
        remote_config.env_file = remote_root / ".env"
        remote_config.backup_dir = remote_root / "backups"
        remote_config.db_name = db_name
        run_pipeline(remote_config, remote, resume=resume)
        logger.info("Pipeline complete on inactive; smoke already run in pipeline")

        logger.info("Starting Redis and Gunicorn on inactive host for traffic switch")
        services.start_remote_services(remote, remote_root)
        if not _wait_app_healthy_via_ssh(remote, timeout_sec=300):
            logger.warning("Instance %s (%s) HTTP not healthy after start_services (non-fatal)", inactive_info.name, inactive_info.ip)

    if no_traffic_switch:
        logger.info("--no-traffic-switch: skipping traffic switch, safety interval, stop old, cron")
        return 0

    static_ip_name = os.environ.get("REFRESH_STATIC_IP_NAME", "")
    if not static_ip_name:
        logger.error("REFRESH_STATIC_IP_NAME not set; cannot switch traffic")
        return 1
    if not traffic_switch.switch_traffic_static_ip(static_ip_name, inactive_info.name):
        logger.error("Static IP switch failed")
        return 1

    logger.info("Updating new prod .env (swap REFRESH_ACTIVE_* / REFRESH_INACTIVE_* / REFRESH_MY_INSTANCE_NAME)")
    remote.update_env("REFRESH_ACTIVE_INSTANCE_NAME", inactive_info.name)
    remote.update_env("REFRESH_ACTIVE_INSTANCE_IP", inactive_info.ip)
    remote.update_env("REFRESH_INACTIVE_INSTANCE_NAME", active_info.name)
    remote.update_env("REFRESH_INACTIVE_INSTANCE_IP", active_info.ip)
    remote.update_env("REFRESH_MY_INSTANCE_NAME", inactive_info.name)

    setup_https = os.environ.get("REFRESH_SKIP_HTTPS_SETUP", "").strip().lower() not in ("1", "true", "yes")
    if setup_https:
        logger.info("Setting up HTTPS on new prod (certbot --nginx)")
        if not services.setup_https_on_remote(remote, timeout_sec=120):
            logger.warning("HTTPS setup failed (non-fatal); run certbot manually on new prod")
    else:
        logger.info("REFRESH_SKIP_HTTPS_SETUP: skipping HTTPS setup on new prod")

    reassign_staging_ip = os.environ.get("REFRESH_SKIP_STAGING_IP_REASSIGN", "").strip().lower() not in ("1", "true", "yes")
    if reassign_staging_ip:
        staging_static_ip = os.environ.get("REFRESH_STAGING_STATIC_IP_NAME", "").strip()
        if not staging_static_ip:
            logger.warning("REFRESH_STAGING_STATIC_IP_NAME not set; skipping staging IP reassign")
        else:
            logger.info("Re-assigning staging static IP %s to old prod %s", staging_static_ip, active_info.name)
            if not traffic_switch.attach_staging_static_ip_to_old_prod(staging_static_ip, active_info.name):
                logger.warning("Staging IP reassign failed (non-fatal)")
    else:
        logger.info("REFRESH_SKIP_STAGING_IP_REASSIGN: skipping staging IP reassign")

    import time
    logger.info("Safety interval: %s sec", safety_interval_sec)
    time.sleep(safety_interval_sec)

    logger.info("Stopping old instance %s", active_info.name)
    if not instance.stop_instance(active_info.name):
        logger.warning("Failed to stop %s (non-fatal)", active_info.name)

    logger.info("Orchestrate complete")
    return 0
