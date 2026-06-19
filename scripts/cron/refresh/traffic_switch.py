# scripts/cron/refresh/traffic_switch.py
"""Traffic switch via Lightsail static IP detach/attach."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)


def _aws_region() -> str:
    """Region for Lightsail API (align with instance.py)."""
    return (
        os.environ.get("REFRESH_AWS_REGION", "").strip()
        or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )


def _get_static_ip_attached_to(static_ip_name: str, region: str) -> str | None:
    """Return the instance name the static IP is currently attached to, or None if detached."""

    result = subprocess.run(
        ["aws", "lightsail", "get-static-ip", "--static-ip-name", static_ip_name, "--region", region],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data.get("staticIp", {}).get("attachedTo") or None
    except Exception:
        return None


def switch_traffic_static_ip(
    static_ip_name: str,
    instance_name_to_attach: str,
    region: str | None = None,
) -> bool:
    """Detach static IP from current instance, attach to instance_name_to_attach.

    Idempotent: if the IP is already on instance_name_to_attach, returns True.
    Returns True on success, False on failure.
    """

    reg = region or _aws_region()

    # Idempotency check: if already on target, nothing to do.
    current = _get_static_ip_attached_to(static_ip_name, reg)
    if current == instance_name_to_attach:
        logger.info(
            "Static IP %s already attached to %s (idempotent — skip)", static_ip_name, instance_name_to_attach
        )
        return True

    result = subprocess.run(
        ["aws", "lightsail", "detach-static-ip", "--static-ip-name", static_ip_name, "--region", reg],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        # Tolerate "not attached" errors — IP may already be detached if a previous run
        # timed out after detach but before attach.
        if "not attached" in (result.stderr or "").lower() or "IsNotAttached" in (result.stderr or ""):
            logger.warning("detach-static-ip: IP was already detached (continuing): %s", result.stderr)
        else:
            logger.error("detach-static-ip failed: %s", result.stderr)
            return False

    result = subprocess.run(
        [
            "aws", "lightsail", "attach-static-ip",
            "--static-ip-name", static_ip_name,
            "--instance-name", instance_name_to_attach,
            "--region", reg,
        ],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        # Idempotency: if already attached to the target, treat as success.
        err = result.stderr or ""
        if "already attached" in err.lower() and instance_name_to_attach in err:
            logger.info("Static IP %s already attached to %s (idempotent)", static_ip_name, instance_name_to_attach)
            return True
        logger.error("attach-static-ip failed: %s", err)
        return False
    logger.info("Static IP %s attached to %s", static_ip_name, instance_name_to_attach)
    return True


def verify_staging_ip_attached(
    staging_static_ip_name: str,
    expected_instance: str,
    region: str | None = None,
) -> bool:
    """
    Check that the staging static IP is attached to expected_instance.
    Used for post-graduation verification.
    Returns True if correctly attached, False otherwise (logs warning on mismatch).
    """

    reg = region or _aws_region()
    result = subprocess.run(
        [
            "aws",
            "lightsail",
            "get-static-ip",
            "--static-ip-name",
            staging_static_ip_name,
            "--region",
            reg,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.warning("get-static-ip failed: %s", result.stderr)
        return False
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("get-static-ip returned invalid JSON: %s", e)
        return False
    ip_info = data.get("staticIp", {})
    attached = ip_info.get("isAttached", False)
    attached_to = ip_info.get("attachedTo", "")
    if not attached or attached_to != expected_instance:
        logger.warning(
            "Staging IP %s: isAttached=%s, attachedTo=%r (expected %r)",
            staging_static_ip_name,
            attached,
            attached_to,
            expected_instance,
        )
        return False
    logger.info(
        "Staging IP %s correctly attached to %s",
        staging_static_ip_name,
        expected_instance,
    )
    return True


def attach_staging_static_ip_to_old_prod(
    staging_static_ip_name: str,
    old_prod_instance_name: str,
    region: str | None = None,
    max_attach_retries: int = 3,
) -> bool:
    """
    Re-assign the staging static IP to the old prod instance (so old prod becomes
    the inactive instance with a stable IP for the next cycle).
    Detaches the static IP from wherever it is, then attaches to old_prod_instance_name.
    Retries attach up to max_attach_retries on failure (transient AWS errors).
    Returns True on success.
    """

    reg = region or _aws_region()
    detach = subprocess.run(
        [
            "aws",
            "lightsail",
            "detach-static-ip",
            "--static-ip-name",
            staging_static_ip_name,
            "--region",
            reg,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if detach.returncode != 0 and "not attached" not in (detach.stderr or "").lower():
        logger.warning("detach-static-ip (staging IP) failed: %s", detach.stderr)

    for attempt in range(max_attach_retries):
        result = subprocess.run(
            [
                "aws",
                "lightsail",
                "attach-static-ip",
                "--static-ip-name",
                staging_static_ip_name,
                "--instance-name",
                old_prod_instance_name,
                "--region",
                reg,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info(
                "Staging static IP %s attached to old prod %s",
                staging_static_ip_name,
                old_prod_instance_name,
            )
            return True
        logger.warning(
            "attach-static-ip (staging IP to old prod) attempt %s/%s failed: %s",
            attempt + 1,
            max_attach_retries,
            result.stderr,
        )
        if attempt < max_attach_retries - 1:
            time.sleep(5)
    logger.error(
        "attach-static-ip (staging IP to old prod) failed after %s attempts: %s",
        max_attach_retries,
        result.stderr,
    )
    return False
