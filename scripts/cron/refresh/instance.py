# scripts/cron/refresh/instance.py
"""Resolve active/inactive instance; start/stop/state via Lightsail API."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


@dataclass
class InstanceInfo:
    """Active or inactive instance: name, IP, state."""

    name: str
    ip: str
    state: str  # running, stopped, pending, etc.


def resolve_active_inactive_from_env() -> tuple[
    InstanceInfo | None, InstanceInfo | None
]:
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


def is_this_host_active(
    my_identifier: str, active_instance: InstanceInfo | None
) -> bool:
    """True if my_identifier matches the active instance (name or IP)."""
    if not active_instance:
        return True  # If not configured, assume active (local-only mode)
    return my_identifier.strip() in (active_instance.name, active_instance.ip)


def get_instance_state(instance_name: str) -> str:
    """Get Lightsail instance state via AWS CLI. Returns 'running', 'stopped', 'pending', or '' on error."""
    import subprocess

    result = subprocess.run(
        [
            "aws", "lightsail", "get-instance-state",
            "--instance-name", instance_name,
            "--region", AWS_REGION,
        ],
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
        [
            "aws", "lightsail", "start-instance",
            "--instance-name", instance_name,
            "--region", AWS_REGION,
        ],
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
        [
            "aws", "lightsail", "stop-instance",
            "--instance-name", instance_name,
            "--region", AWS_REGION,
        ],
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


def validate_env_against_aws(
    active_info: InstanceInfo,
    inactive_info: InstanceInfo,
) -> bool:
    """Verify that REFRESH_ACTIVE_INSTANCE_IP is actually attached to REFRESH_ACTIVE_INSTANCE_NAME.

    Queries AWS Lightsail to confirm the static IP attachment matches .env.
    Returns True if consistent, False (with logged errors) if not.
    A mismatch means .env was corrupted (e.g. from a partial orchestrator run or manual edit)
    and the orchestrator would operate on the wrong instance.
    """
    import json
    import subprocess

    try:
        result = subprocess.run(
            [
                "aws", "lightsail", "get-static-ips",
                "--region", AWS_REGION,
                "--output", "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        logger.warning("AWS validation skipped (aws CLI unavailable or timed out): %s", e)
        return True  # Non-fatal: if AWS CLI is not configured, don't block the run

    if result.returncode != 0:
        logger.warning(
            "AWS validation skipped (get-static-ips failed: %s)", result.stderr[:300]
        )
        return True  # Non-fatal: treat as unverifiable

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("AWS validation skipped (invalid JSON from get-static-ips): %s", e)
        return True

    # Build ip -> attached_instance_name map
    ip_to_instance: dict[str, str] = {}
    for ip_info in data.get("staticIps", []):
        ip_addr = ip_info.get("ipAddress", "")
        attached_to = ip_info.get("attachedTo", "")
        if ip_addr:
            ip_to_instance[ip_addr] = attached_to

    ok = True
    # Check active IP is on the active instance
    actual_active = ip_to_instance.get(active_info.ip)
    if actual_active is None:
        logger.warning(
            "AWS validation: active IP %s not found in Lightsail static IPs "
            "(may be a dynamic IP — skipping check for this IP)",
            active_info.ip,
        )
    elif actual_active != active_info.name:
        logger.error(
            "AWS/env mismatch: REFRESH_ACTIVE_INSTANCE_IP=%s is attached to %r in AWS, "
            "but .env says REFRESH_ACTIVE_INSTANCE_NAME=%r. "
            ".env is corrupted (likely from a partial graduation). "
            "Fix: set REFRESH_ACTIVE_INSTANCE_NAME to %r and REFRESH_INACTIVE_INSTANCE_NAME to %r in .env, "
            "then verify IPs match with: aws lightsail get-static-ips --region %s",
            active_info.ip, actual_active, active_info.name, actual_active,
            active_info.name, AWS_REGION,
        )
        ok = False

    # Check inactive IP is on the inactive instance (if it's a known static IP)
    actual_inactive = ip_to_instance.get(inactive_info.ip)
    if actual_inactive is None:
        logger.debug(
            "AWS validation: inactive IP %s not found in static IPs (may be dynamic — skipping)",
            inactive_info.ip,
        )
    elif actual_inactive != inactive_info.name:
        logger.error(
            "AWS/env mismatch: REFRESH_INACTIVE_INSTANCE_IP=%s is attached to %r in AWS, "
            "but .env says REFRESH_INACTIVE_INSTANCE_NAME=%r. "
            ".env is corrupted (likely from a partial graduation). "
            "Fix: set REFRESH_INACTIVE_INSTANCE_NAME to %r in .env.",
            inactive_info.ip, actual_inactive, inactive_info.name, actual_inactive,
        )
        ok = False

    if ok:
        logger.info(
            "AWS/env validation passed: active=%s (%s), inactive=%s (%s)",
            active_info.name, active_info.ip, inactive_info.name, inactive_info.ip,
        )
    return ok


def wait_instance_healthy(
    ip: str,
    port: int = 80,
    path: str = "/health/",
    timeout_sec: int = 600,
    poll_interval_sec: int = 10,
    host_header: str | None = None,
) -> bool:
    """Wait until HTTP GET to http://ip:port/path returns 200. Returns True if healthy within timeout.
    Uses /health/ by default. With nginx listen 80 default_server, requests by IP hit the app."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_sec
    url = f"http://{ip}:{port}{path}"
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url)
            if host_header:
                req.add_header("Host", host_header)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError) as e:
            logger.debug("Health check %s: %s", url, e)
        time.sleep(poll_interval_sec)
    return False
