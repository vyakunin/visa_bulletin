#!/usr/bin/env python3
"""Automate the Cloudflare setup described in docs/deployment/cloudflare.md.

Usage (run from the project root; token read from $CLOUDFLARE_API_TOKEN
or ~/tokens/cloudflare_api_token):

    python3 deployment/scripts/cloudflare_setup.py bootstrap
    #   --> you change registrar NS records, wait for "active" status
    python3 deployment/scripts/cloudflare_setup.py wait-active
    python3 deployment/scripts/cloudflare_setup.py dns
    python3 deployment/scripts/cloudflare_setup.py configure
    python3 deployment/scripts/cloudflare_setup.py origin-cert
    python3 deployment/scripts/cloudflare_setup.py nginx-realip
    python3 deployment/scripts/cloudflare_setup.py verify
    #   --> wait 24-48h, watch analytics
    python3 deployment/scripts/cloudflare_setup.py lockdown

Phases are independent and idempotent. State (zone_id) is cached in
~/.cloudflare_setup_state.json.

API token permissions required:
    Account  - Origin CA:Edit, Account Settings:Read
    Zone     - Zone:Edit, DNS:Edit, SSL:Edit, Zone Settings:Edit,
               Cache Rules:Edit, Zone WAF:Edit
    Include:all zones (or at least visa-bulletin.us)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CF_API = "https://api.cloudflare.com/client/v4"
DOMAIN = "visa-bulletin.us"
SSH_ALIAS = "prod_2Gb_vm"
LIGHTSAIL_INSTANCE = "VisaBulletin2GB"
AWS_REGION = "us-east-1"
AWS_PROFILE = "visa-bulletin-deploy"
STATE_FILE = Path.home() / ".cloudflare_setup_state.json"
TOKEN_FILE = Path.home() / "tokens" / "cloudflare_api_token"
ACCOUNT_ID_FILE = Path.home() / "tokens" / "cloudflare_account_id"
ORIGIN_CERT_DIR = Path("/tmp") / "cloudflare_origin_cert"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("cloudflare_setup")


# --- small utilities -----------------------------------------------------


def read_token() -> str:
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if token:
        return token.strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    sys.exit(
        f"No token. Set $CLOUDFLARE_API_TOKEN or put it in {TOKEN_FILE} "
        f"(chmod 600)."
    )


def read_account_id() -> str | None:
    """Account ID is required for account-scoped tokens (the normal case)."""
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if acct:
        return acct.strip()
    if ACCOUNT_ID_FILE.exists():
        return ACCOUNT_ID_FILE.read_text().strip()
    return None


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))
    STATE_FILE.chmod(0o600)


def require_zone_id(state: dict) -> str:
    zone_id = state.get("zone_id")
    if not zone_id:
        sys.exit("No zone_id in state — run `bootstrap` first.")
    return zone_id


# --- Cloudflare API client ----------------------------------------------


class CFError(RuntimeError):
    pass


@dataclass
class CF:
    token: str

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        allow_codes: tuple[int, ...] = (),
    ) -> dict:
        url = f"{CF_API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            raw = e.read().decode() if e.fp else ""
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            if e.code in allow_codes:
                return parsed
            raise CFError(
                f"{method} {path} -> HTTP {e.code}: {parsed}"
            ) from e
        return json.loads(raw)

    def get(self, path: str, **kw) -> dict:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: dict, **kw) -> dict:
        return self.request("POST", path, body, **kw)

    def put(self, path: str, body: dict, **kw) -> dict:
        return self.request("PUT", path, body, **kw)

    def patch(self, path: str, body: dict, **kw) -> dict:
        return self.request("PATCH", path, body, **kw)


# --- phases --------------------------------------------------------------


def verify_token(cf: CF, account_id: str | None) -> None:
    """Verify the token. Account-scoped tokens must use /accounts/{id}/tokens/verify;
    user-scoped tokens use /user/tokens/verify. Try account-scoped first if we have an ID."""
    if account_id:
        r = cf.get(f"/accounts/{account_id}/tokens/verify", allow_codes=(401, 403))
        if r.get("success"):
            log.info("Token OK (account-scoped, status=%s)", r["result"]["status"])
            return
        log.info("Account-scoped verify failed; trying user-scoped")
    r = cf.get("/user/tokens/verify")
    if not r.get("success"):
        sys.exit(f"Token verification failed: {r}")
    log.info("Token OK (user-scoped, status=%s)", r["result"]["status"])


def get_account_id(cf: CF) -> str:
    """Prefer the explicitly-configured account id (needed for account-scoped tokens,
    which can't list /accounts). Fall back to /accounts for user-scoped tokens."""
    acct = read_account_id()
    if acct:
        log.info("Account id (from tokens dir): %s", acct)
        return acct
    r = cf.get("/accounts")
    accounts = r.get("result", [])
    if not accounts:
        sys.exit(
            "No account id configured and /accounts returned none. "
            f"Put the account id in {ACCOUNT_ID_FILE} or $CLOUDFLARE_ACCOUNT_ID."
        )
    acc = accounts[0]
    log.info("Account: %s (%s)", acc["name"], acc["id"])
    return acc["id"]


def phase_bootstrap(cf: CF, state: dict) -> None:
    """Add the zone to Cloudflare and print nameservers for registrar update."""
    account_id = get_account_id(cf)
    verify_token(cf, account_id)

    existing = cf.get(f"/zones?name={DOMAIN}")
    zones = existing.get("result", [])
    if zones:
        zone = zones[0]
        log.info("Zone already present: %s (status=%s)", zone["id"], zone["status"])
    else:
        log.info("Creating zone %s...", DOMAIN)
        r = cf.post(
            "/zones",
            {
                "name": DOMAIN,
                "account": {"id": account_id},
                "type": "full",
            },
        )
        zone = r["result"]
        log.info("Created zone %s", zone["id"])

    state["zone_id"] = zone["id"]
    state["account_id"] = account_id
    state["nameservers"] = zone.get("name_servers", [])
    save_state(state)

    log.info("=" * 60)
    log.info("ACTION REQUIRED — update nameservers at the registrar:")
    for ns in state["nameservers"]:
        log.info("  %s", ns)
    log.info("Then run: python3 deployment/scripts/cloudflare_setup.py wait-active")
    log.info("=" * 60)


def phase_wait_active(cf: CF, state: dict, timeout_s: int = 1800) -> None:
    """Poll until CF marks the zone active (NS delegation verified)."""
    zone_id = require_zone_id(state)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = cf.get(f"/zones/{zone_id}")
        status = r["result"]["status"]
        log.info("Zone status: %s", status)
        if status == "active":
            return
        time.sleep(30)
    sys.exit(f"Zone still not active after {timeout_s}s — check NS at registrar.")


def _current_origin_ip() -> str:
    """Resolve the current origin IP via the SSH alias host."""
    try:
        r = subprocess.run(
            ["ssh", "-G", SSH_ALIAS],
            capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(f"Could not resolve {SSH_ALIAS} via ssh -G: {e}")
    for line in r.stdout.splitlines():
        if line.startswith("hostname "):
            host = line.split(None, 1)[1].strip()
            try:
                socket.inet_aton(host)
                return host
            except OSError:
                return socket.gethostbyname(host)
    sys.exit(f"No hostname in ssh -G output for {SSH_ALIAS}")


def phase_dns(cf: CF, state: dict) -> None:
    """Ensure A records for @ and www point to the origin and are proxied."""
    zone_id = require_zone_id(state)
    origin_ip = _current_origin_ip()
    log.info("Origin IP (from ssh config): %s", origin_ip)

    wanted = [
        {"type": "A", "name": DOMAIN,           "content": origin_ip, "proxied": True, "ttl": 1},
        {"type": "A", "name": f"www.{DOMAIN}",  "content": origin_ip, "proxied": True, "ttl": 1},
    ]

    existing = cf.get(f"/zones/{zone_id}/dns_records?per_page=200")["result"]
    by_key = {(r["type"], r["name"]): r for r in existing}

    for record in wanted:
        key = (record["type"], record["name"])
        current = by_key.get(key)
        if current:
            if (
                current["content"] == record["content"]
                and current["proxied"] == record["proxied"]
            ):
                log.info("DNS %s %s already correct", record["type"], record["name"])
                continue
            log.info("Updating DNS %s %s", record["type"], record["name"])
            cf.put(f"/zones/{zone_id}/dns_records/{current['id']}", record)
        else:
            log.info("Creating DNS %s %s", record["type"], record["name"])
            cf.post(f"/zones/{zone_id}/dns_records", record)

    log.warning(
        "Only @ and www were touched. Review MX / TXT / CAA / other records "
        "in the CF dashboard against your registrar's zone before the NS switch."
    )


def phase_configure(cf: CF, state: dict) -> None:
    """SSL strict, always-HTTPS, Bot Fight Mode, cache rules, WAF rules."""
    zone_id = require_zone_id(state)

    log.info("SSL -> Full (strict)")
    cf.patch(f"/zones/{zone_id}/settings/ssl", {"value": "strict"})
    cf.patch(f"/zones/{zone_id}/settings/always_use_https", {"value": "on"})
    cf.patch(f"/zones/{zone_id}/settings/automatic_https_rewrites", {"value": "on"})
    cf.patch(f"/zones/{zone_id}/settings/min_tls_version", {"value": "1.2"})
    cf.patch(f"/zones/{zone_id}/settings/tls_1_3", {"value": "on"})
    cf.patch(f"/zones/{zone_id}/settings/brotli", {"value": "on"})

    log.info("Bot Fight Mode -> toggle in dashboard (Security → Bots). "
             "API endpoint is not available on Free plan / without Bot Management entitlement.")

    _install_cache_rules(cf, zone_id)
    _install_waf_rules(cf, zone_id)


def _install_cache_rules(cf: CF, zone_id: str) -> None:
    log.info("Cache Rules -> install entrypoint ruleset")
    rules = [
        {
            "description": "Bypass cache for admin/api/authenticated",
            "expression": (
                '(starts_with(http.request.uri.path, "/admin/")) or '
                '(starts_with(http.request.uri.path, "/api/")) or '
                '(any(http.request.cookies["sessionid"][*] != ""))'
            ),
            "action": "set_cache_settings",
            "action_parameters": {"cache": False},
            "enabled": True,
        },
        {
            "description": "Cache bulletin/predictions/rankings/employers HTML (1h edge)",
            "expression": (
                '(http.request.uri.path eq "/") or '
                '(starts_with(http.request.uri.path, "/bulletin/")) or '
                '(starts_with(http.request.uri.path, "/predictions/")) or '
                '(starts_with(http.request.uri.path, "/rankings/")) or '
                '(starts_with(http.request.uri.path, "/employers/"))'
            ),
            "action": "set_cache_settings",
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "override_origin", "default": 3600},
                "browser_ttl": {"mode": "override_origin", "default": 3600},
            },
            "enabled": True,
        },
        {
            # `matches` (regex) is a paid-plan operator, so enumerate extensions with ends_with.
            "description": "Long-cache static assets",
            "expression": (
                '(ends_with(http.request.uri.path, ".css")) or '
                '(ends_with(http.request.uri.path, ".js")) or '
                '(ends_with(http.request.uri.path, ".woff")) or '
                '(ends_with(http.request.uri.path, ".woff2")) or '
                '(ends_with(http.request.uri.path, ".png")) or '
                '(ends_with(http.request.uri.path, ".jpg")) or '
                '(ends_with(http.request.uri.path, ".jpeg")) or '
                '(ends_with(http.request.uri.path, ".svg")) or '
                '(ends_with(http.request.uri.path, ".ico")) or '
                '(ends_with(http.request.uri.path, ".gif")) or '
                '(ends_with(http.request.uri.path, ".webp"))'
            ),
            "action": "set_cache_settings",
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "override_origin", "default": 2592000},
                "browser_ttl": {"mode": "override_origin", "default": 86400},
            },
            "enabled": True,
        },
    ]
    cf.put(
        f"/zones/{zone_id}/rulesets/phases/http_request_cache_settings/entrypoint",
        {"rules": rules},
    )


def _install_waf_rules(cf: CF, zone_id: str) -> None:
    log.info("WAF Custom Rules -> install entrypoint ruleset")
    rules = [
        {
            "description": "Block known-bad crawler UAs (mirrors nginx blacklist)",
            "expression": (
                '(http.user_agent contains "SemrushBot") or '
                '(http.user_agent contains "YandexBot") or '
                '(http.user_agent contains "Amazonbot") or '
                '(http.user_agent contains "SERankingBacklinksBot") or '
                '(http.user_agent contains "MJ12bot")'
            ),
            "action": "block",
            "enabled": True,
        },
    ]
    cf.put(
        f"/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"rules": rules},
    )


def phase_origin_cert(cf: CF, state: dict) -> None:
    """Generate a Cloudflare Origin CA cert + private key and save locally."""
    ORIGIN_CERT_DIR.mkdir(parents=True, exist_ok=True)

    cert_path = ORIGIN_CERT_DIR / "origin.pem"
    key_path = ORIGIN_CERT_DIR / "origin.key"
    if cert_path.exists() and key_path.exists():
        log.info("Origin cert already at %s — skipping. Delete to regenerate.", ORIGIN_CERT_DIR)
        return

    csr, private_key_pem = _generate_csr_and_key()

    log.info("Requesting Origin CA cert (15y, ECC)")
    # Origin CA needs the user service key OR an API token with Origin CA:Edit.
    r = cf.post(
        "/certificates",
        {
            "hostnames": [DOMAIN, f"*.{DOMAIN}"],
            "requested_validity": 5475,  # 15 years
            "request_type": "origin-ecc",
            "csr": csr,
        },
    )
    cert_pem = r["result"]["certificate"]

    key_path.write_text(private_key_pem)
    key_path.chmod(0o600)
    cert_path.write_text(cert_pem)
    log.info("Wrote %s and %s", cert_path, key_path)
    log.info("Install on origin with: `scp ... %s`", cert_path)


def _generate_csr_and_key() -> tuple[str, str]:
    """Generate an ECDSA P-256 CSR + PEM key via openssl (stdlib only)."""
    if not shutil.which("openssl"):
        sys.exit("openssl not found — required for CSR generation.")
    key_file = ORIGIN_CERT_DIR / "origin.key.tmp"
    csr_file = ORIGIN_CERT_DIR / "origin.csr.tmp"
    try:
        subprocess.run(
            ["openssl", "ecparam", "-name", "prime256v1", "-genkey",
             "-noout", "-out", str(key_file)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "req", "-new", "-key", str(key_file),
             "-subj", f"/CN={DOMAIN}", "-out", str(csr_file)],
            check=True, capture_output=True,
        )
        csr = csr_file.read_text()
        key = key_file.read_text()
        return csr, key
    finally:
        csr_file.unlink(missing_ok=True)
        key_file.unlink(missing_ok=True)


def phase_nginx_realip(cf: CF, state: dict) -> None:
    """Fetch CF IP ranges, generate nginx conf, SCP to origin, reload."""
    del cf, state
    v4 = _http_get("https://www.cloudflare.com/ips-v4").splitlines()
    v6 = _http_get("https://www.cloudflare.com/ips-v6").splitlines()
    v4 = [c.strip() for c in v4 if c.strip()]
    v6 = [c.strip() for c in v6 if c.strip()]
    if not v4 or not v6:
        sys.exit("CF IP ranges empty — aborting.")

    conf_lines = [
        "# Cloudflare real-IP ranges (auto-generated by cloudflare_setup.py).",
        "# Refresh quarterly. Source: https://www.cloudflare.com/ips/",
        "",
    ]
    for cidr in v4 + v6:
        conf_lines.append(f"set_real_ip_from {cidr};")
    conf_lines.extend([
        "",
        "real_ip_header CF-Connecting-IP;",
        "real_ip_recursive on;",
        "",
    ])
    local = Path("/tmp/cloudflare-real-ip.conf")
    local.write_text("\n".join(conf_lines))
    log.info("Wrote %s (%d v4 + %d v6 ranges)", local, len(v4), len(v6))

    remote_path = "/etc/nginx/conf.d/cloudflare-real-ip.conf"
    log.info("Uploading to %s:%s", SSH_ALIAS, remote_path)
    subprocess.run(
        ["scp", str(local), f"{SSH_ALIAS}:/tmp/cloudflare-real-ip.conf"],
        check=True,
    )
    subprocess.run(
        ["ssh", SSH_ALIAS,
         f"sudo cp /tmp/cloudflare-real-ip.conf {remote_path} && "
         f"sudo nginx -t && sudo systemctl reload nginx"],
        check=True,
    )
    log.info("nginx reloaded with CF real-IP config.")


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def phase_verify(cf: CF, state: dict) -> None:
    """Sanity-check edge caching + origin real IP."""
    del cf, state
    log.info("Checking cf-cache-status on https://%s/ ...", DOMAIN)
    _curl_head(f"https://{DOMAIN}/")
    _curl_head(f"https://{DOMAIN}/")  # second hit should be HIT
    log.info("Checking last 20 origin access log lines for real IPs ...")
    subprocess.run(
        ["ssh", SSH_ALIAS, "sudo tail -n 20 /var/log/nginx/access.log"],
        check=False,
    )


def _curl_head(url: str) -> None:
    r = subprocess.run(
        ["curl", "-sI", "-o", "/dev/null", "-w",
         "status=%{http_code} cf-cache-status=%header{cf-cache-status}\n",
         url],
        capture_output=True, text=True, check=False,
    )
    log.info("  %s -> %s", url, r.stdout.strip())


def phase_lockdown(cf: CF, state: dict) -> None:
    """Restrict Lightsail firewall 80/443 to Cloudflare IPv4 ranges."""
    del cf, state
    if not shutil.which("aws"):
        sys.exit("aws CLI not found.")
    v4 = [c.strip() for c in _http_get("https://www.cloudflare.com/ips-v4").splitlines() if c.strip()]
    if not v4:
        sys.exit("CF IPv4 ranges empty — aborting.")

    # put-instance-public-ports REPLACES all rules — we must re-declare SSH.
    port_infos = [
        {"fromPort": 22, "toPort": 22, "protocol": "tcp", "cidrs": ["0.0.0.0/0"]},
    ]
    for cidr in v4:
        port_infos.append({"fromPort": 80, "toPort": 80, "protocol": "tcp", "cidrs": [cidr]})
        port_infos.append({"fromPort": 443, "toPort": 443, "protocol": "tcp", "cidrs": [cidr]})

    payload_file = Path("/tmp/cloudflare-lightsail-ports.json")
    payload_file.write_text(json.dumps(port_infos, indent=2))

    log.warning("=" * 60)
    log.warning("About to LOCK DOWN Lightsail firewall on %s", LIGHTSAIL_INSTANCE)
    log.warning("80/443 will only accept traffic from %d CF CIDRs.", len(v4))
    log.warning("Payload: %s", payload_file)
    log.warning("Aborting in 10s — Ctrl-C to cancel.")
    log.warning("=" * 60)
    for i in range(10, 0, -1):
        log.warning("  %d ...", i)
        time.sleep(1)

    env = os.environ.copy()
    env["AWS_PROFILE"] = AWS_PROFILE
    env["AWS_REGION"] = AWS_REGION
    subprocess.run(
        ["aws", "lightsail", "put-instance-public-ports",
         "--instance-name", LIGHTSAIL_INSTANCE,
         "--region", AWS_REGION,
         "--port-infos", f"file://{payload_file}"],
        check=True, env=env,
    )
    log.info("Firewall updated. Keep SSH rule intact via Lightsail console if needed.")


# --- argparse ------------------------------------------------------------


PHASES = {
    "bootstrap":     phase_bootstrap,
    "wait-active":   phase_wait_active,
    "dns":           phase_dns,
    "configure":     phase_configure,
    "origin-cert":   phase_origin_cert,
    "nginx-realip":  phase_nginx_realip,
    "verify":        phase_verify,
    "lockdown":      phase_lockdown,
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("phase", choices=list(PHASES.keys()))
    args = p.parse_args()

    cf = CF(token=read_token())
    state = load_state()
    PHASES[args.phase](cf, state)


if __name__ == "__main__":
    main()
