# scripts/cron/refresh/instance.py
"""Resolve active/inactive instance; start/stop/state via Lightsail API."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class InstanceInfo:
    """Active or inactive instance: name, IP, state."""

    name: str
    ip: str
    state: str  # running, stopped, pending, etc.


def resolve_active_inactive_from_env() -> tuple[InstanceInfo | None, InstanceInfo | None]:
    """Resolve active and inactive instances from env (REFRESH_ACTIVE_*, REFRESH_INACTIVE_*)."""
    active_name = os.environ.get("REFRESH_ACTIVE_INSTANCE_NAME", "").strip()
    active_ip = os.environ.get("REFRESH_ACTIVE_INSTANCE_IP", "").strip()
    inactive_name = os.environ.get("REFRESH_INACTIVE_INSTANCE_NAME", "").strip()
    inactive_ip = os.environ.get("REFRESH_INACTIVE_INSTANCE_IP", "").strip()
    if not active_name or not active_ip or not inactive_name or not inactive_ip:
        return None, None
    return (
        InstanceInfo(name=active_name, ip=active_ip, state=""),
        InstanceInfo(name=inactive_name, ip=inactive_ip, state=""),
    )


def is_this_host_active(my_identifier: str, active_instance: InstanceInfo | None) -> bool:
    """True if my_identifier matches the active instance (name or IP)."""
    if not active_instance:
        return True  # If not configured, assume active (local-only mode)
    return my_identifier.strip() in (active_instance.name, active_instance.ip)


def get_instance_state(instance_name: str) -> str:
    """Get Lightsail instance state via AWS CLI. Returns 'running', 'stopped', 'pending', or '' on error."""
    import subprocess
    result = subprocess.run(
        ["aws", "lightsail", "get-instance-state", "--instance-name", instance_name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.warning("get-instance-state failed: %s", result.stderr)
        return ""
    import json
    try:
        data = json.loads(result.stdout)
        return data.get("state", {}).get("name", "")
    except (json.JSONDecodeError, KeyError):
        return ""


def start_instance(instance_name: str) -> bool:
    """Start Lightsail instance. Returns True on success."""
    import subprocess
    result = subprocess.run(
        ["aws", "lightsail", "start-instance", "--instance-name", instance_name],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        logger.error("start-instance failed: %s", result.stderr)
        return False
    return True


def stop_instance(instance_name: str) -> bool:
    """Stop Lightsail instance. Returns True on success."""
    import subprocess
    result = subprocess.run(
        ["aws", "lightsail", "stop-instance", "--instance-name", instance_name],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        logger.error("stop-instance failed: %s", result.stderr)
        return False
    return True


def wait_instance_running(
    instance_name: str,
    timeout_sec: int = 600,
    poll_interval_sec: int = 15,
) -> bool:
    """Wait until instance state is 'running'. Returns True if running within timeout."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        state = get_instance_state(instance_name)
        if state == "running":
            return True
        if state == "stopped":
            logger.warning("Instance %s is stopped", instance_name)
        time.sleep(poll_interval_sec)
    return False


def wait_instance_healthy(
    ip: str,
    port: int = 80,
    path: str = "/",
    timeout_sec: int = 600,
    poll_interval_sec: int = 10,
) -> bool:
    """Wait until HTTP GET to http://ip:port/path returns 200. Returns True if healthy within timeout."""
    import urllib.request
    import urllib.error
    deadline = time.monotonic() + timeout_sec
    url = f"http://{ip}:{port}{path}"
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError) as e:
            logger.debug("Health check %s: %s", url, e)
        time.sleep(poll_interval_sec)
    return False
