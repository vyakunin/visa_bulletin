# scripts/cron/refresh/traffic_switch.py
"""Traffic switch via Lightsail static IP detach/attach."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def switch_traffic_static_ip(
    static_ip_name: str,
    instance_name_to_attach: str,
    region: str | None = None,
) -> bool:
    """Detach static IP from current instance, attach to instance_name_to_attach. Returns True on success."""
    import subprocess

    reg = region or os.environ.get("REFRESH_AWS_REGION", "us-east-1")
    result = subprocess.run(
        [
            "aws",
            "lightsail",
            "detach-static-ip",
            "--static-ip-name",
            static_ip_name,
            "--region",
            reg,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.error("detach-static-ip failed: %s", result.stderr)
        return False
    result = subprocess.run(
        [
            "aws",
            "lightsail",
            "attach-static-ip",
            "--static-ip-name",
            static_ip_name,
            "--instance-name",
            instance_name_to_attach,
            "--region",
            reg,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.error("attach-static-ip failed: %s", result.stderr)
        return False
    logger.info("Static IP %s attached to %s", static_ip_name, instance_name_to_attach)
    return True


def attach_staging_static_ip_to_old_prod(
    staging_static_ip_name: str,
    old_prod_instance_name: str,
    region: str | None = None,
) -> bool:
    """
    Re-assign the staging static IP to the old prod instance (so old prod becomes
    the inactive instance with a stable IP for the next cycle).
    Detaches the static IP from wherever it is, then attaches to old_prod_instance_name.
    Returns True on success.
    """
    import subprocess

    reg = region or os.environ.get("REFRESH_AWS_REGION", "us-east-1")
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
        timeout=30,
    )
    if detach.returncode != 0 and "not attached" not in (detach.stderr or "").lower():
        logger.warning("detach-static-ip (staging IP) failed: %s", detach.stderr)
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
        timeout=30,
    )
    if result.returncode != 0:
        logger.error(
            "attach-static-ip (staging IP to old prod) failed: %s", result.stderr
        )
        return False
    logger.info(
        "Staging static IP %s attached to old prod %s",
        staging_static_ip_name,
        old_prod_instance_name,
    )
    return True
