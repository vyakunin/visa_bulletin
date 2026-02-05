# scripts/cron/refresh/orchestrate.py
"""Orchestrator: resolve active/inactive, start inactive, run pipeline on inactive, smoke, (optional) traffic switch, stop old."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from . import instance
from . import traffic_switch
from .config import RefreshConfig, load_config
from .pipeline import run_pipeline
from .runner import RemoteRunner

if TYPE_CHECKING:
    from .runner import Runner

logger = logging.getLogger(__name__)


def run_orchestrate(
    config: RefreshConfig,
    safety_interval_sec: int = 1800,
    no_traffic_switch: bool = False,
    resume: bool = False,
) -> int:
    """
    Full cycle: resolve active/inactive -> start inactive -> wait healthy
    -> run pipeline with RemoteRunner(inactive) -> smoke -> (optional) traffic switch
    -> safety interval -> stop old -> (optional) cron on new active.
    If no_traffic_switch is True, skip traffic switch, safety, stop old, and cron (first validation).
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

    if not instance.wait_instance_healthy(inactive_info.ip, port=80, timeout_sec=600):
        logger.error("Instance %s (%s) not healthy", inactive_info.name, inactive_info.ip)
        return 1
    logger.info("Inactive instance healthy at %s", inactive_info.ip)

    ssh_user = os.environ.get("REFRESH_SSH_USER", "ubuntu")
    ssh_key = os.environ.get("REFRESH_SSH_KEY_PATH", "")
    project_root = os.environ.get("REFRESH_REMOTE_PROJECT_ROOT", "/opt/visa_bulletin")
    remote = RemoteRunner(
        host=inactive_info.ip,
        project_root=project_root,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key if ssh_key else None,
    )
    remote_root = Path(project_root)
    remote_config = load_config(None)
    remote_config.project_root = remote_root
    remote_config.env_file = remote_root / ".env"
    remote_config.backup_dir = remote_root / "backups"
    remote_config.single_db_on_host = True
    remote_config.db_name = os.environ.get("REFRESH_REMOTE_DB_NAME", "visa_bulletin")
    logger.info("Running pipeline on inactive host %s", inactive_info.ip)
    run_pipeline(remote_config, remote, resume=resume)
    logger.info("Pipeline complete on inactive; smoke already run in pipeline")

    if no_traffic_switch:
        logger.info("--no-traffic-switch: skipping traffic switch, safety interval, stop old, cron")
        return 0

    switch_mode = os.environ.get("REFRESH_TRAFFIC_SWITCH", "dns").strip().lower()
    if switch_mode == "dns":
        sld = os.environ.get("REFRESH_DOMAIN_SLD", "visa-bulletin")
        tld = os.environ.get("REFRESH_DOMAIN_TLD", "us")
        api_user = os.environ.get("NAMECHEAP_API_USER", "")
        api_key = os.environ.get("NAMECHEAP_API_KEY", "")
        client_ip = os.environ.get("REFRESH_CLIENT_IP", active_info.ip)
        if not traffic_switch.switch_traffic_dns(sld, tld, inactive_info.ip, api_user, api_key, client_ip):
            logger.error("DNS switch failed")
            return 1
    elif switch_mode == "static_ip":
        static_ip_name = os.environ.get("REFRESH_STATIC_IP_NAME", "")
        if not traffic_switch.switch_traffic_static_ip(static_ip_name, inactive_info.name):
            logger.error("Static IP switch failed")
            return 1
    else:
        logger.error("Unknown REFRESH_TRAFFIC_SWITCH: %s", switch_mode)
        return 1

    import time
    logger.info("Safety interval: %s sec", safety_interval_sec)
    time.sleep(safety_interval_sec)

    logger.info("Stopping old instance %s", active_info.name)
    if not instance.stop_instance(active_info.name):
        logger.warning("Failed to stop %s (non-fatal)", active_info.name)

    logger.info("Orchestrate complete")
    return 0
