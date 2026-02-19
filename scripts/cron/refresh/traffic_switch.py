# scripts/cron/refresh/traffic_switch.py
"""Traffic switch: DNS (Namecheap) or static IP (Lightsail detach/attach)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def switch_traffic_dns(
    domain_sld: str,
    domain_tld: str,
    new_ip: str,
    api_user: str,
    api_key: str,
    client_ip: str,
) -> bool:
    """Switch DNS A records for @ and www to new_ip via Namecheap API. Returns True on success."""
    try:
        import urllib.parse
        import urllib.request
        import xml.etree.ElementTree as ET
    except ImportError:
        logger.error("Namecheap API requires urllib and xml.etree")
        return False
    base = "https://api.namecheap.com/xml.response"
    params = {
        "ApiUser": api_user,
        "ApiKey": api_key,
        "UserName": api_user,
        "Command": "namecheap.domains.dns.getHosts",
        "ClientIp": client_ip,
        "SLD": domain_sld,
        "TLD": domain_tld,
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read().decode()
    except Exception as e:
        logger.error("getHosts failed: %s", e)
        return False
    root = ET.fromstring(body)
    if root.get("Status") != "OK":
        err_el = root.find(".//{http://api.namecheap.com/xml.response}Errors/{http://api.namecheap.com/xml.response}Error")
        err_msg = err_el.get("Number", "") + ": " + (err_el.text or "") if err_el is not None else body[:500]
        logger.error("getHosts status: %s; %s", root.get("Status"), err_msg)
        return False
    hosts = []
    for h in root.findall(".//{http://api.namecheap.com/xml.response}host"):
        hostname = h.get("Name", "")
        record_type = h.get("Type", "")
        address = h.get("Address", "")
        if record_type == "A" and hostname in ("@", "www"):
            address = new_ip
        hosts.append((hostname, record_type, address, h.get("TTL", "300")))
    # setHosts
    set_params = {
        "ApiUser": api_user,
        "ApiKey": api_key,
        "UserName": api_user,
        "Command": "namecheap.domains.dns.setHosts",
        "ClientIp": client_ip,
        "SLD": domain_sld,
        "TLD": domain_tld,
    }
    for i, (name, rtype, addr, ttl) in enumerate(hosts):
        set_params[f"HostName{i + 1}"] = name
        set_params[f"RecordType{i + 1}"] = rtype
        set_params[f"Address{i + 1}"] = addr
        set_params[f"TTL{i + 1}"] = ttl
    set_url = base + "?" + urllib.parse.urlencode(set_params)
    try:
        with urllib.request.urlopen(set_url, timeout=30) as resp:
            set_body = resp.read().decode()
    except Exception as e:
        logger.error("setHosts failed: %s", e)
        return False
    set_root = ET.fromstring(set_body)
    if set_root.get("Status") != "OK":
        logger.error("setHosts status: %s", set_root.get("Status"))
        return False
    logger.info("DNS switched to %s", new_ip)
    return True


def switch_traffic_static_ip(
    static_ip_name: str,
    instance_name_to_attach: str,
    region: str | None = None,
) -> bool:
    """Detach static IP from current instance, attach to instance_name_to_attach. Returns True on success."""
    import subprocess
    reg = region or os.environ.get("REFRESH_AWS_REGION", "us-east-1")
    result = subprocess.run(
        ["aws", "lightsail", "detach-static-ip", "--static-ip-name", static_ip_name, "--region", reg],
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
        ["aws", "lightsail", "detach-static-ip", "--static-ip-name", staging_static_ip_name, "--region", reg],
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
        logger.error("attach-static-ip (staging IP to old prod) failed: %s", result.stderr)
        return False
    logger.info("Staging static IP %s attached to old prod %s", staging_static_ip_name, old_prod_instance_name)
    return True
