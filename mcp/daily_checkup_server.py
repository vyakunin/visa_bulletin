"""Daily checkup MCP server for visa_bulletin.

Gathers production-health, traffic, and security signals from:
  1. The homeserver (one SSH round-trip): vb_* container health, host
     resources, bulletin-refresh cron freshness, GDrive backup cron freshness,
     Postgres data-freshness signals (newest bulletin + last successful
     IngestRun), nginx access-log summary (status mix, top 5xx paths, top
     scraper IPs), and probes for known scanner paths (/wp-admin, /.env etc.).
  2. GoatCounter API: total pageviews/visitors week-over-week, top paths
     bucketed by surface (job titles, employers, predictions, blog, search,
     SEO landings, homepage, other), top movers.
  3. External HTTP probes: visa-bulletin.us + key sub-pages return 200 and
     still ship the GoatCounter beacon.

Returns a CheckupReport JSON per the contract at
  ~/.cursor/shared_rules/daily_checkup.mdc

State mutation: NONE. All reads.

Setup:
  - Add `Host homeserver` to ~/.ssh/config (HostName homeserver.local,
    User vyakunin, IdentityFile ~/.ssh/homeserver_ed25519) — or override
    via env var HOMESERVER_SSH_ALIAS.
  - Save GoatCounter API token at ~/tokens/goatcounter.token (mode 600).
  - Register in the orchestrator's registry.yaml — see README.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

from mcp import ClientSession, StdioServerParameters

logger = logging.getLogger("visa_bulletin_daily_checkup")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

SSH_ALIAS = os.environ.get("HOMESERVER_SSH_ALIAS", "homeserver")
USER_EMAIL = os.environ.get("DAILY_CHECKUP_USER_EMAIL", "vyakunin@gmail.com")
GLOBAL_MCP_REGISTRY = Path.home() / "mcp" / "servers.json"
SUB_MCP_TIMEOUT = 45
PROD_STACK = "/opt/stack/visa_bulletin"
STAGING_STACK = "/opt/stack/visa_bulletin_staging"
PROD_BASE_URL = "https://visa-bulletin.us"
STAGING_BASE_URL = "https://staging.visa-bulletin.us"

GOATCOUNTER_BASE = "https://vyakunin.goatcounter.com/api/v0"
GOATCOUNTER_TOKEN_PATH = Path.home() / "tokens" / "goatcounter.token"

GSC_SITE_URL = "sc-domain:visa-bulletin.us"
# GSC `final` data lags ~2 days, so we shift the comparison window back 3 days
# so both halves of the cycle-aware delta are fully settled. "This week" =
# today-9d..today-3d; "cycle ago" = today-37d..today-31d (one bulletin cycle
# back, same day-of-week phase).
GSC_LAG_DAYS = 3

# Thresholds
DISK_YELLOW_PCT = 70  # SSD is 64 GB; want headroom for Postgres growth.
DISK_RED_PCT = 85
MEM_YELLOW_PCT = 80
MEM_RED_PCT = 92
CPU_LOAD_YELLOW = 1.0  # per-core (load1 / nproc)
CPU_LOAD_RED = 2.0
BULLETIN_REFRESH_YELLOW_MIN = 90    # cron runs hourly
BULLETIN_REFRESH_RED_MIN = 180
BACKUP_YELLOW_HOURS = 30            # cron runs daily at 01:00 UTC
BACKUP_RED_HOURS = 50
# How old the newest bulletin's published_date may be before we worry. DoS
# publishes monthly; > 35 days suggests we missed one (parser broke / source
# rotated).
BULLETIN_DATA_STALE_DAYS_YELLOW = 35
BULLETIN_DATA_STALE_DAYS_RED = 50
# 5xx as % of total responses in last 24h.
NGINX_5XX_YELLOW_PCT = 0.5
NGINX_5XX_RED_PCT = 2.0
# A single real client IP hitting more than this in 24h is a scraper / abuse
# candidate. Now meaningful since 2026-05-14 (real_ip_module rewrites
# $remote_addr from CF-Connecting-IP).
SCRAPER_IP_YELLOW = 2000
SCRAPER_IP_RED = 10000

# Traffic-delta thresholds. The visa bulletin publishes monthly (~8th–15th),
# producing a strong monthly traffic cycle, so WoW is misleading mid-cycle.
# Primary baseline = same 7-day window 28 days ago (one full cycle, same
# day-of-week phase). Thresholds apply to that 28d delta.
TRAFFIC_DROP_YELLOW_PCT = -30
TRAFFIC_DROP_RED_PCT = -60

GC_TIMEOUT = 15
PROBE_TIMEOUT = 8

# Surface buckets — order matters; first match wins. Names are stable keys;
# SURFACE_LABELS below provides human-readable display strings used in the
# digest so future readers do not have to guess what each bucket covers.
#
# `dashboard` merges `/` and `/employment-based/<country>/` because they serve
# the identical EB-dashboard template (see [[project_homepage_is_india_eb]]) —
# the only difference is which country is prefilled. Treating them as separate
# surfaces consistently overstated the homepage and understated the dashboard.
# `donation_click` captures the GoatCounter `ext-*` event records that fire on
# Buy-Me-a-Coffee / GitHub-Sponsors clicks — they appear in the GC `/stats/hits`
# stream as fake paths, so they need their own bucket or they pollute `other`.
SURFACE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("donation_click", re.compile(r"^ext-")),
    ("dashboard", re.compile(r"^/(\?|$)|^/employment-based/")),
    ("job_title_profile", re.compile(r"^/job-title/")),
    ("job_title_directory", re.compile(r"^/job-titles/?$")),
    ("employer_profile", re.compile(r"^/employer/")),
    ("employer_rankings", re.compile(r"^/employers/rankings/?$")),
    ("employer_directory", re.compile(r"^/employers/?$")),
    ("predictions", re.compile(r"^/predictions/")),
    ("blog", re.compile(r"^/analysis/?")),
    ("salaries", re.compile(r"^/salaries/?")),
    ("worksites", re.compile(r"^/worksites/")),
    ("seo_landing_fam", re.compile(r"^/family-sponsored/?")),
    ("static_pages", re.compile(r"^/(faq|about|contact)/?$")),
    ("api", re.compile(r"^/api/")),
    ("static_meta", re.compile(r"^/(robots\.txt|sitemap\.xml|favicon)")),
]

SURFACE_LABELS: dict[str, str] = {
    "donation_click":      "Donation-button clicks (ext-* events, NOT pageviews)",
    "dashboard":           "Dashboard / EB landings `/` + `/employment-based/<country>/` (same template, country prefilled)",
    "job_title_profile":   "Job title profile `/job-title/<slug>/`",
    "job_title_directory": "Job titles directory `/job-titles/`",
    "employer_profile":    "Employer profile `/employer/<slug>/`",
    "employer_directory":  "Employers directory `/employers/`",
    "employer_rankings":   "Employer rankings `/employers/rankings/`",
    "predictions":         "Predictions backtest `/predictions/<...>/` (live predictions are embedded on dashboard)",
    "blog":                "Blog / analysis `/analysis/<slug>/`",
    "salaries":            "Salaries `/salaries/<...>/`",
    "worksites":           "Worksites `/worksites/<...>/`",
    "seo_landing_fam":     "Family-sponsored visa SEO landings `/family-sponsored/<country>/`",
    "static_pages":        "Static pages `/faq`, `/about`, `/contact`",
    "api":                 "API `/api/<...>`",
    "static_meta":         "Static meta (robots/sitemap/favicon)",
    "other":               "Other (long-tail / unclassified)",
}

# ─────────────────────────────────────────────────────────────────────────────
# SSH: gather everything in one round-trip with section markers
# ─────────────────────────────────────────────────────────────────────────────

def _run_ssh(script: str, timeout: int = 45) -> str:
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
        "-o", f"ConnectTimeout={timeout}",
        SSH_ALIAS, "bash", "-s",
    ]
    res = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=timeout + 5)
    if res.returncode != 0:
        raise RuntimeError(f"ssh failed (rc={res.returncode}): {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def _parse_sectioned(raw: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in raw.splitlines():
        if line.startswith("==SECTION:") and line.endswith("=="):
            current = line[len("==SECTION:"):-2]
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _gather_homeserver_snapshot() -> dict[str, str]:
    """One SSH round-trip. Everything we want from the homeserver."""
    # Single multi-line script. Each section marker is a `printf` so we can
    # rely on exact form. `set +e` so a single failing command doesn't kill
    # the whole snapshot — we want partial data.
    prod_bul_log = f"{PROD_STACK}/logs/cron/bulletin_refresh.log"
    prod_bak_log = f"{PROD_STACK}/logs/cron/backup.log"

    # Postgres signals — run inside vb_postgres so we don't need a libpq on
    # the host. We surface (a) newest published bulletin (data freshness),
    # (b) last successful ingest_run.completed_at, (c) active connections.
    psql = (
        "docker exec vb_postgres psql -U visa_bulletin_user -d visa_bulletin "
        "-tA -F'|' -c"
    )

    script = rf"""
set +e
printf '==SECTION:containers==\n'
docker ps -a --filter 'name=vb_' --format '{{{{.Names}}}}|{{{{.Status}}}}|{{{{.State}}}}'
printf '==SECTION:resources==\n'
df -h /
free -m | grep -E '^Mem:'
nproc
cat /proc/loadavg
printf '==SECTION:bulletin_refresh==\n'
if [ -f {shlex.quote(prod_bul_log)} ]; then
  stat -c '%Y' {shlex.quote(prod_bul_log)}
  tail -200 {shlex.quote(prod_bul_log)}
else
  echo MISSING
fi
printf '==SECTION:backup==\n'
if [ -f {shlex.quote(prod_bak_log)} ]; then
  stat -c '%Y' {shlex.quote(prod_bak_log)}
  tail -50 {shlex.quote(prod_bak_log)}
else
  echo MISSING
fi
printf '==SECTION:postgres==\n'
{psql} "SELECT MAX(publication_date) FROM bulletin;" 2>&1
{psql} "SELECT MAX(completed_at) FROM ingest_run WHERE status=3;" 2>&1
{psql} "SELECT count(*), max(EXTRACT(EPOCH FROM (now()-state_change))) FROM pg_stat_activity WHERE datname='visa_bulletin';" 2>&1
printf '==SECTION:nginx==\n'
# nginx logs go to stdout (access.log is a symlink to /dev/stdout in
# nginx:alpine), so the file is not seekable — read via `docker logs`.
# `--since 24h` lets the daemon do time-window filtering (~1s for ~70k lines).
# Single awk pass emits everything: status mix, top 5xx/4xx paths, scanner
# probes, 429 count, bot-UA hits, AND unique-IP counts. $1 (remote_addr) is
# now the real client IP since the real_ip_module rewrites it from
# CF-Connecting-IP (config block in visa_bulletin.conf, added 2026-05-14).
docker logs --since 24h vb_nginx 2>/dev/null | awk '
  {{
    total++
    # Fields: $1=real-client-IP $4=[date $5=tz] $6="METHOD $7=/uri $8=HTTP/x.x" $9=status $10=bytes $11=request_time $12=referer $13+ =UA
    status = $9
    if (status !~ /^[0-9]+$/) next
    code_class = substr(status, 1, 1) "xx"
    by_class[code_class]++
    if (substr(status,1,1)=="5") by_5xx_status[status]++
    if (status == "429") rate_limit_429++
    path = $7
    sub(/\?.*$/, "", path)
    if (substr(status,1,1)=="5") top_5xx_path[path]++
    if (substr(status,1,1)=="4") top_4xx_path[path]++
    is_scanner = (path ~ /(wp-admin|wp-login|wp-content|wp-includes|wordpress|phpmyadmin|administrator|xmlrpc\.php|\.env|\.git|\.aws|\.ssh|actuator|hudson|jenkins|owa\/auth)/)
    if (is_scanner) scanner_path[path]++
    # Real-page hits = 2xx/3xx on something that is not API/static/scanner.
    is_page = (substr(status,1,1) ~ /^[23]$/) && path !~ /^\/(api|static|favicon|robots\.txt|sitemap\.xml|\.well-known)/ && !is_scanner
    # Surface classification for per-property latency tracking. Mirror order of
    # SURFACE_PATTERNS in Python; first match wins. Only count is_page (2xx/3xx
    # real pages, scanner/api/static already filtered).
    if (is_page) {{
      if      (path == "/" || path ~ /^\/employment-based\//) surf = "dashboard"
      else if (path ~ /^\/job-title\//)                  surf = "job_title_profile"
      else if (path ~ /^\/job-titles\/?$/)               surf = "job_title_directory"
      else if (path ~ /^\/employer\//)                   surf = "employer_profile"
      else if (path ~ /^\/employers\/rankings\/?$/)      surf = "employer_rankings"
      else if (path ~ /^\/employers\/?$/)                surf = "employer_directory"
      else if (path ~ /^\/predictions\//)                surf = "predictions"
      else if (path ~ /^\/analysis\//)                   surf = "blog"
      else if (path ~ /^\/salaries\/?/)                  surf = "salaries"
      else if (path ~ /^\/worksites\//)                  surf = "worksites"
      else if (path ~ /^\/family-sponsored\//)           surf = "seo_landing_fam"
      else if (path ~ /^\/(faq|about|contact)\/?$/)      surf = "static_pages"
      else                                                surf = "other"
      rt = $11 + 0
      surf_count[surf]++
      surf_sum_ms[surf] += rt * 1000
      if (rt >= 1)  surf_n1[surf]++
      if (rt >= 3)  surf_n3[surf]++
      if (rt >= 10) surf_n10[surf]++
    }}
    # Bot/scraper UA heuristic. Legit search engines (Googlebot, Bingbot) match
    # intentionally -- we want bot visibility. UA fields are $12 and beyond.
    is_bot = (tolower($0) ~ /(curl|wget|python-requests|python-urllib|libwww|httpclient|scrapy|java\/|go-http|bot[ )\/]|crawler|spider|httrack|nikto|sqlmap|nmap|masscan|zmeu)/)
    if (is_bot) bot_hits++
    ip = $1
    # Skip docker-internal IPs (cloudflared sidecar / internal probes). These
    # appear in older log windows pre-2026-05-14 (before real_ip_module config)
    # and continue to appear for internal /health hits. Anything in private
    # ranges is uninteresting for client-IP analysis.
    is_internal = (ip ~ /^172\.(1[6-9]|2[0-9]|3[01])\./ || ip ~ /^10\./ || ip ~ /^192\.168\./)
    # Well-known crawler allowlist — UA OR known subnets. Googlebot publishes
    # ranges at gstatic.com/ipranges/googlebot.json; 66.249.64-95.* covers the
    # bulk. Bingbot 40.77.* / 207.46.*. Claude-SearchBot AWS 216.73.216-219.*.
    # Kept on one line because mawk on the homeserver chokes on multi-line
    # parenthesized assignments.
    is_known_bot = (tolower($0) ~ /(googlebot|bingbot|claude-searchbot|gptbot|chatgpt-user|perplexitybot|applebot|duckduckbot|yandexbot|baiduspider|petalbot|amazonbot|facebookexternalhit)/ || ip ~ /^66\.249\.(6[4-9]|[7-8][0-9]|9[0-5])\./ || ip ~ /^40\.77\./ || ip ~ /^207\.46\./ || ip ~ /^216\.73\.21[6-9]\./)
    if (!is_internal) {{ if (is_known_bot) bot_ip_hits[ip]++; else ip_hits[ip]++ }}
    if (is_page) {{
      page_hits++
      if (is_bot) page_hits_bot++
      else        page_hits_human++
      if (!is_internal) {{
        unique_ip_page[ip] = 1
        if (!is_bot) unique_ip_human[ip] = 1
      }}
    }}
  }}
  END {{
    print "total=" total+0
    print "page_hits=" page_hits+0
    print "page_hits_human=" page_hits_human+0
    print "page_hits_bot=" page_hits_bot+0
    n=0; for (k in unique_ip_page) n++
    print "unique_ips_page_24h=" n
    n=0; for (k in unique_ip_human) n++
    print "unique_ips_human_page_24h=" n
    for (c in by_class) print "class=" c "|" by_class[c]
    for (s in by_5xx_status) print "5xx_status=" s "|" by_5xx_status[s]
    # Top-K via selection sort: O(n*K). The earlier bubble sort was O(n*n)
    # and blew past 60s on ip_hits (~30k unique client IPs/day after CF
    # real_ip rewrite). Selection-sort top-10 stays sub-second even at 100k.
    n=0; for (p in top_5xx_path) {{ paths[n]=p; counts[n]=top_5xx_path[p]; n++ }}
    for (i=0;i<n && i<10;i++) {{
      mi=i; for (j=i+1;j<n;j++) if (counts[j]>counts[mi]) mi=j
      if (mi!=i) {{ t=counts[i];counts[i]=counts[mi];counts[mi]=t;t=paths[i];paths[i]=paths[mi];paths[mi]=t }}
      print "5xx_path=" paths[i] "|" counts[i]
    }}
    n=0; delete paths; delete counts
    for (p in top_4xx_path) {{ paths[n]=p; counts[n]=top_4xx_path[p]; n++ }}
    for (i=0;i<n && i<10;i++) {{
      mi=i; for (j=i+1;j<n;j++) if (counts[j]>counts[mi]) mi=j
      if (mi!=i) {{ t=counts[i];counts[i]=counts[mi];counts[mi]=t;t=paths[i];paths[i]=paths[mi];paths[mi]=t }}
      print "4xx_path=" paths[i] "|" counts[i]
    }}
    for (p in scanner_path) print "scanner_path=" p "|" scanner_path[p]
    # Top scraper IPs (real client IPs, descending by hit count). Excludes
    # well-known crawlers (Googlebot, Bingbot, Claude-SearchBot, etc.) which
    # go to a separate botip= bucket so they remain visible but do not trip
    # warnings. NOTE: do not use apostrophes anywhere inside this awk program
    # — the surrounding shell wraps it in single quotes, so any apostrophe
    # terminates the awk string prematurely and bash parses the remainder.
    n=0; delete paths; delete counts
    for (ip in ip_hits) {{ paths[n]=ip; counts[n]=ip_hits[ip]; n++ }}
    for (i=0;i<n && i<10;i++) {{
      mi=i; for (j=i+1;j<n;j++) if (counts[j]>counts[mi]) mi=j
      if (mi!=i) {{ t=counts[i];counts[i]=counts[mi];counts[mi]=t;t=paths[i];paths[i]=paths[mi];paths[mi]=t }}
      print "ip=" paths[i] "|" counts[i]
    }}
    n=0; delete paths; delete counts
    for (ip in bot_ip_hits) {{ paths[n]=ip; counts[n]=bot_ip_hits[ip]; n++ }}
    for (i=0;i<n && i<5;i++) {{
      mi=i; for (j=i+1;j<n;j++) if (counts[j]>counts[mi]) mi=j
      if (mi!=i) {{ t=counts[i];counts[i]=counts[mi];counts[mi]=t;t=paths[i];paths[i]=paths[mi];paths[mi]=t }}
      print "botip=" paths[i] "|" counts[i]
    }}
    print "rate_limit_429=" rate_limit_429+0
    print "bot_hits=" bot_hits+0
    # Per-surface latency (page hits only). Format:
    #   surf=<name>|count|sum_ms|n_over_1s|n_over_3s|n_over_10s
    for (s in surf_count) {{
      print "surf=" s "|" surf_count[s]+0 "|" surf_sum_ms[s]+0 "|" surf_n1[s]+0 "|" surf_n3[s]+0 "|" surf_n10[s]+0
    }}
  }}
'
printf '==SECTION:cloudflared==\n'
docker inspect vb_cloudflared --format '{{{{.RestartCount}}}}|{{{{.State.Status}}}}' 2>/dev/null
"""
    return _parse_sectioned(_run_ssh(script, timeout=60))


# ─────────────────────────────────────────────────────────────────────────────
# Homeserver section parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_containers(text: str) -> list[dict]:
    rows = []
    for line in text.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        rows.append({"name": parts[0], "status": parts[1], "state": parts[2]})
    return rows


def _parse_resources(text: str) -> dict:
    out: dict = {"disk": None, "mem": None, "cpu": None}
    nproc = None
    for line in text.strip().splitlines():
        cols = line.split()
        if not cols:
            continue
        if line.startswith("Mem:") and len(cols) >= 3:
            total = int(cols[1])
            used = int(cols[2])
            out["mem"] = {"total_mb": total, "used_mb": used, "used_pct": round(100 * used / total)}
        elif len(cols) >= 6 and cols[-1] == "/":
            # filesystem size used avail use% /
            pct = int(cols[-2].rstrip("%"))
            out["disk"] = {"used_pct": pct, "used": cols[2], "avail": cols[3]}
        elif len(cols) == 1 and cols[0].isdigit():
            nproc = int(cols[0])
        elif len(cols) >= 3:
            try:
                out["cpu"] = {
                    "load1": float(cols[0]),
                    "load5": float(cols[1]),
                    "load15": float(cols[2]),
                }
            except ValueError:
                pass
    if out["cpu"] and nproc:
        out["cpu"]["nproc"] = nproc
        out["cpu"]["load1_per_cpu"] = out["cpu"]["load1"] / nproc
    return out


def _parse_log_age(text: str) -> dict:
    """Section format: first line = epoch mtime, rest = tail of log."""
    lines = text.strip().splitlines()
    if not lines or lines[0] == "MISSING":
        return {"present": False, "tail": ""}
    try:
        mtime = int(lines[0])
    except ValueError:
        return {"present": False, "tail": text}
    last_run = datetime.fromtimestamp(mtime, tz=UTC)
    age_min = (datetime.now(UTC) - last_run).total_seconds() / 60
    tail = "\n".join(lines[1:])
    # Look for error markers. Only count [ERROR]/[CRITICAL] lines — bare
    # tracebacks always pair with a parent ERROR. Filter known-harmless legacy
    # bulletin noise (POST_MIGRATION_TRACKER #8): 10 ancient sources (Jan–July
    # 2015 and Feb–April 2004) fail validation hourly because their Bulletin
    # DB rows are missing — not a parser issue. Modern bulletins unaffected,
    # script exits 0.
    benign = re.compile(
        r"publication date (200[0-9]|201[0-5])"
        r"|source (19[89]|20[0-4]|32[89]|330)\b"
        r"|Validation failed in 0\.00s"
        r"|Pipeline failed at stage 5: Validation failed with 1 error\(s\)"
    )
    error_lines = [
        line for line in tail.splitlines()
        if re.search(r"\[ERROR\]|\[CRITICAL\]|\bFAILED\b", line) and not benign.search(line)
    ]
    return {
        "present": True,
        "last_run": last_run.isoformat(),
        "age_min": age_min,
        "tail_errors": error_lines[-10:],
        "tail_last_lines": tail.splitlines()[-10:],
    }


def _parse_postgres(text: str) -> dict:
    """Three psql lines: newest published_date, last completed ingest_run, conn count + max idle secs."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    out: dict = {"newest_bulletin": None, "last_ingest_completed": None, "connections": None, "max_idle_sec": None}
    if len(lines) >= 1 and lines[0] and "ERROR" not in lines[0] and "FATAL" not in lines[0]:
        try:
            out["newest_bulletin"] = date.fromisoformat(lines[0]).isoformat()
        except ValueError:
            pass
    if len(lines) >= 2 and lines[1] and "ERROR" not in lines[1]:
        try:
            # Postgres returns "2026-05-13 22:00:14.123+00"
            ts = lines[1].split(".")[0].replace(" ", "T")
            out["last_ingest_completed"] = datetime.fromisoformat(ts).replace(tzinfo=UTC).isoformat()
        except (ValueError, IndexError):
            out["last_ingest_completed_raw"] = lines[1]
    if len(lines) >= 3 and "|" in lines[2]:
        parts = lines[2].split("|")
        try:
            out["connections"] = int(parts[0])
        except ValueError:
            pass
        try:
            out["max_idle_sec"] = float(parts[1]) if parts[1] else None
        except ValueError:
            pass
    return out


def _parse_nginx(text: str) -> dict:
    """Parse the awk output of the merged nginx section."""
    out: dict = {
        "total": 0,
        "page_hits": 0,
        "page_hits_human": 0,
        "page_hits_bot": 0,
        "unique_ips_page_24h": 0,
        "unique_ips_human_page_24h": 0,
        "by_class": {},
        "5xx_status": {},
        "top_5xx_paths": [],
        "top_4xx_paths": [],
        "scanner_paths": [],
        "top_ips": [],
        "top_bot_ips": [],
        "rate_limit_429": 0,
        "bot_hits": 0,
        "surface_latency": {},  # surface -> {count, sum_ms, n_over_1s, n_over_3s, n_over_10s, mean_ms}
    }
    int_keys = {
        "total", "page_hits", "page_hits_human", "page_hits_bot",
        "unique_ips_page_24h", "unique_ips_human_page_24h",
        "rate_limit_429", "bot_hits",
    }
    for line in text.strip().splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key in int_keys:
            try:
                out[key] = int(val)
            except ValueError:
                pass
        elif key == "class":
            klass, _, cnt = val.partition("|")
            try:
                out["by_class"][klass] = int(cnt)
            except ValueError:
                pass
        elif key == "5xx_status":
            code, _, cnt = val.partition("|")
            try:
                out["5xx_status"][code] = int(cnt)
            except ValueError:
                pass
        elif key == "5xx_path":
            path, _, cnt = val.partition("|")
            try:
                out["top_5xx_paths"].append((path, int(cnt)))
            except ValueError:
                pass
        elif key == "4xx_path":
            path, _, cnt = val.partition("|")
            try:
                out["top_4xx_paths"].append((path, int(cnt)))
            except ValueError:
                pass
        elif key == "scanner_path":
            path, _, cnt = val.partition("|")
            try:
                out["scanner_paths"].append((path, int(cnt)))
            except ValueError:
                pass
        elif key == "ip":
            ip, _, cnt = val.partition("|")
            try:
                out["top_ips"].append((ip, int(cnt)))
            except ValueError:
                pass
        elif key == "botip":
            ip, _, cnt = val.partition("|")
            try:
                out["top_bot_ips"].append((ip, int(cnt)))
            except ValueError:
                pass
        elif key == "surf":
            # name|count|sum_ms|n_over_1s|n_over_3s|n_over_10s
            parts = val.split("|")
            if len(parts) >= 6:
                name = parts[0]
                try:
                    count = int(parts[1])
                    sum_ms = int(parts[2])
                    n1 = int(parts[3])
                    n3 = int(parts[4])
                    n10 = int(parts[5])
                except ValueError:
                    continue
                out["surface_latency"][name] = {
                    "count": count,
                    "sum_ms": sum_ms,
                    "mean_ms": (sum_ms / count) if count else 0.0,
                    "n_over_1s": n1,
                    "n_over_3s": n3,
                    "n_over_10s": n10,
                }
    out["scanner_paths"].sort(key=lambda x: -x[1])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# GoatCounter
# ─────────────────────────────────────────────────────────────────────────────

def _read_gc_token() -> str:
    if not GOATCOUNTER_TOKEN_PATH.exists():
        raise RuntimeError(f"GoatCounter token not found at {GOATCOUNTER_TOKEN_PATH}")
    return GOATCOUNTER_TOKEN_PATH.read_text().strip()


async def _gc_get(client: httpx.AsyncClient, path: str, **params) -> dict:
    r = await client.get(f"{GOATCOUNTER_BASE}{path}", params=params, timeout=GC_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _bucket_path(p: str) -> str:
    for name, pattern in SURFACE_PATTERNS:
        if pattern.match(p):
            return name
    return "other"


async def _gather_goatcounter() -> dict:
    """Pull weekly totals + top paths bucketed by surface.

    Baselines compared:
      - this 7d
      - same 7d window 28 days ago (one bulletin cycle ago, cycle-aware)
      - prev 7d (WoW, kept as secondary signal — useful intra-cycle)

    Bulletin publishes monthly (~8th–15th) so WoW is misleading mid-cycle.
    """
    token = _read_gc_token()
    today = date.today()
    this_end = today
    this_start = today - timedelta(days=6)
    prev_end = this_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    cycle_end = today - timedelta(days=28)
    cycle_start = cycle_end - timedelta(days=6)

    headers = {"Authorization": f"Bearer {token}"}
    # GoatCounter returns 404 on concurrent requests; serialize (6 calls, ~3s).
    async with httpx.AsyncClient(headers=headers) as client:
        totals_this = await _gc_get(client, "/stats/total",
                                    start=this_start.isoformat(), end=this_end.isoformat())
        totals_prev = await _gc_get(client, "/stats/total",
                                    start=prev_start.isoformat(), end=prev_end.isoformat())
        totals_cycle = await _gc_get(client, "/stats/total",
                                     start=cycle_start.isoformat(), end=cycle_end.isoformat())
        hits_this = await _gc_get(client, "/stats/hits", limit=100,
                                  start=this_start.isoformat(), end=this_end.isoformat())
        hits_cycle = await _gc_get(client, "/stats/hits", limit=100,
                                   start=cycle_start.isoformat(), end=cycle_end.isoformat())

    def _bucket_hits(payload: dict) -> tuple[dict[str, int], dict[str, int]]:
        by_surface: dict[str, int] = defaultdict(int)
        by_path: dict[str, int] = {}
        for h in payload.get("hits", []) or []:
            path = h.get("path") or ""
            count = h.get("count") or 0
            by_surface[_bucket_path(path)] += count
            by_path[path] = count
        return dict(by_surface), by_path

    surf_this, paths_this = _bucket_hits(hits_this)
    surf_cycle, paths_cycle = _bucket_hits(hits_cycle)

    # Per-surface deltas vs 4-weeks-ago (cycle-aware baseline)
    all_surfaces = set(surf_this) | set(surf_cycle)
    surface_deltas = []
    for s in all_surfaces:
        cur = surf_this.get(s, 0)
        cyc = surf_cycle.get(s, 0)
        delta_pct = ((cur - cyc) / cyc * 100) if cyc else None
        surface_deltas.append({"surface": s, "this_week": cur, "cycle_ago": cyc, "delta_pct": delta_pct})
    surface_deltas.sort(key=lambda r: -r["this_week"])

    # Top movers (vs 4 weeks ago, paths present in either window)
    movers = []
    for p in set(paths_this) | set(paths_cycle):
        cur = paths_this.get(p, 0)
        cyc = paths_cycle.get(p, 0)
        if cur + cyc < 50:
            continue
        delta_pct = ((cur - cyc) / cyc * 100) if cyc else None
        movers.append({"path": p, "this_week": cur, "cycle_ago": cyc, "delta_pct": delta_pct})
    movers.sort(key=lambda r: -abs(r["this_week"] - r["cycle_ago"]))
    movers = movers[:10]

    return {
        "totals_this_week": totals_this,
        "totals_prev_week": totals_prev,
        "totals_cycle_ago": totals_cycle,
        "surfaces": surface_deltas,
        "top_movers": movers,
        "top_paths_this_week_truncated": hits_this.get("more", False),
        "window": {
            "this": [this_start.isoformat(), this_end.isoformat()],
            "prev": [prev_start.isoformat(), prev_end.isoformat()],
            "cycle_ago": [cycle_start.isoformat(), cycle_end.isoformat()],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Google Search Console (sub-MCP: gsc)
# ─────────────────────────────────────────────────────────────────────────────

async def _call_gsc_tools(calls: list[tuple[str, dict]]) -> list[str]:
    """Spawn one gsc MCP, run multiple tool calls reusing the same session.

    The canonical gsc registry entry uses `uv run --project <dir> python
    gsc_server.py` — the `python gsc_server.py` part resolves relative to the
    *spawner's* cwd, not `--project`. We're being spawned from
    `visa_bulletin/mcp`, where `gsc_server.py` does not exist, so pin cwd to
    the gsc project dir explicitly.
    """
    entry = _load_global_mcp("gsc")
    env = {**os.environ, **(entry.get("env") or {})}
    gsc_cwd = "/Users/vyakunin/cursor_projects/personal_projects/gsc_mcp"
    params = StdioServerParameters(
        command=entry["command"],
        args=list(entry.get("args") or []),
        env=env,
        cwd=gsc_cwd,
    )
    out: list[str] = []
    async with asyncio.timeout(SUB_MCP_TIMEOUT):
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                for tool, args in calls:
                    res = await session.call_tool(tool, args)
                    texts = [c.text for c in res.content if hasattr(c, "text")]
                    out.append("\n".join(texts))
    return out


def _gsc_totals(rows: list[dict]) -> dict:
    """Aggregate GSC rows (any dimension) into totals."""
    clicks = sum((r.get("clicks") or 0) for r in rows)
    impr = sum((r.get("impressions") or 0) for r in rows)
    ctr = (clicks / impr) if impr else 0.0
    # Average position is impression-weighted.
    pos_num = sum((r.get("position") or 0) * (r.get("impressions") or 0) for r in rows)
    avg_pos = (pos_num / impr) if impr else 0.0
    return {"clicks": clicks, "impressions": impr, "ctr": ctr, "avg_position": avg_pos}


async def _gather_gsc() -> dict:
    """Pull GSC search analytics for this 7d vs same 7d window 4 weeks ago."""
    today = date.today()
    this_end = today - timedelta(days=GSC_LAG_DAYS)
    this_start = this_end - timedelta(days=6)
    cycle_end = today - timedelta(days=GSC_LAG_DAYS + 28)
    cycle_start = cycle_end - timedelta(days=6)

    common = {"site_url": GSC_SITE_URL, "search_type": "web", "data_state": "final"}
    calls = [
        # Totals + per-day for this week
        ("gsc_query_search_analytics", {
            **common, "start_date": this_start.isoformat(), "end_date": this_end.isoformat(),
            "dimensions": ["date"], "row_limit": 100,
        }),
        # Totals for cycle-ago window
        ("gsc_query_search_analytics", {
            **common, "start_date": cycle_start.isoformat(), "end_date": cycle_end.isoformat(),
            "dimensions": ["date"], "row_limit": 100,
        }),
        # Top queries this week
        ("gsc_query_search_analytics", {
            **common, "start_date": this_start.isoformat(), "end_date": this_end.isoformat(),
            "dimensions": ["query"], "row_limit": 25,
        }),
        # Top pages this week
        ("gsc_query_search_analytics", {
            **common, "start_date": this_start.isoformat(), "end_date": this_end.isoformat(),
            "dimensions": ["page"], "row_limit": 25,
        }),
        # Top pages cycle-ago (for movers)
        ("gsc_query_search_analytics", {
            **common, "start_date": cycle_start.isoformat(), "end_date": cycle_end.isoformat(),
            "dimensions": ["page"], "row_limit": 50,
        }),
    ]
    raw_results = await _call_gsc_tools(calls)

    def _rows(raw: str) -> list[dict]:
        try:
            return (json.loads(raw) or {}).get("rows", []) or []
        except json.JSONDecodeError:
            return []

    rows_this_byday = _rows(raw_results[0])
    rows_cycle_byday = _rows(raw_results[1])
    rows_queries = _rows(raw_results[2])
    rows_pages_this = _rows(raw_results[3])
    rows_pages_cycle = _rows(raw_results[4])

    totals_this = _gsc_totals(rows_this_byday)
    totals_cycle = _gsc_totals(rows_cycle_byday)

    # Top queries by clicks
    top_queries = sorted(
        ({"q": (r.get("keys") or [""])[0], **r} for r in rows_queries),
        key=lambda r: -(r.get("clicks") or 0),
    )[:10]

    # Page movers: same page in both windows, delta on clicks
    pages_this_by_url = {(r.get("keys") or [""])[0]: r for r in rows_pages_this}
    pages_cycle_by_url = {(r.get("keys") or [""])[0]: r for r in rows_pages_cycle}
    movers = []
    for url in set(pages_this_by_url) | set(pages_cycle_by_url):
        cur = pages_this_by_url.get(url, {})
        cyc = pages_cycle_by_url.get(url, {})
        c_now = cur.get("clicks") or 0
        c_cyc = cyc.get("clicks") or 0
        i_now = cur.get("impressions") or 0
        i_cyc = cyc.get("impressions") or 0
        if (c_now + c_cyc) < 5:
            continue
        delta_clicks = c_now - c_cyc
        movers.append({
            "url": url, "clicks_this": c_now, "clicks_cycle": c_cyc,
            "impressions_this": i_now, "impressions_cycle": i_cyc,
            "delta_clicks": delta_clicks,
        })
    movers.sort(key=lambda r: -abs(r["delta_clicks"]))
    movers = movers[:8]

    return {
        "this_window": [this_start.isoformat(), this_end.isoformat()],
        "cycle_window": [cycle_start.isoformat(), cycle_end.isoformat()],
        "totals_this": totals_this,
        "totals_cycle": totals_cycle,
        "top_queries": top_queries,
        "top_movers": movers,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gmail (sub-MCP: google_workspace)
# ─────────────────────────────────────────────────────────────────────────────

_MSGID_RE = re.compile(r"Message ID:\s*([0-9a-f]+)", re.IGNORECASE)


def _load_global_mcp(name: str) -> dict:
    if not GLOBAL_MCP_REGISTRY.exists():
        raise RuntimeError(f"MCP registry not found at {GLOBAL_MCP_REGISTRY}")
    data = json.loads(GLOBAL_MCP_REGISTRY.read_text())
    entry = data.get("mcpServers", {}).get(name)
    if not entry:
        raise RuntimeError(f"MCP '{name}' not in registry")
    return entry


async def _call_gw_tools(calls: list[tuple[str, dict]]) -> list[str]:
    """Spawn one google_workspace MCP, run multiple tool calls reusing the
    same session, return raw text payloads.
    """
    entry = _load_global_mcp("google_workspace")
    env = {**os.environ, **(entry.get("env") or {})}
    params = StdioServerParameters(
        command=entry["command"],
        args=list(entry.get("args") or []),
        env=env,
    )
    out: list[str] = []
    async with asyncio.timeout(SUB_MCP_TIMEOUT):
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                for tool, args in calls:
                    res = await session.call_tool(tool, args)
                    texts = [c.text for c in res.content if hasattr(c, "text")]
                    out.append("\n".join(texts))
    return out


# Queries we run against Gmail. Each tuple is (label, query, importance_if_hit,
# importance_if_empty).
GMAIL_QUERIES: list[tuple[str, str, int, int]] = [
    # F5Bot: Reddit mentions of our target keywords. Hits = community signal,
    # not a problem — daily-checkup workflow expects you to triage these.
    ("f5bot", "from:admin@f5bot.com newer_than:1d", 4, 1),
    # Uptime monitors. Per POST_MIGRATION_TRACKER #15, monitoring isn't yet
    # set up — but search anyway so it lights up the moment one is wired.
    ("uptime",
     "from:(noreply@uptimerobot.com OR @pingdom.com OR @statuscake.com "
     "OR @betterstack.com OR @hetrixtools.com OR @site24x7.com OR "
     "@cronitor.io OR @healthchecks.io) newer_than:1d",
     5, 1),
    # Anything else mentioning the project (user feedback, GSC alerts, GHCR
    # build failures, etc.). Exclude F5Bot to avoid double-count.
    ("project_mentions",
     "(visa-bulletin.us OR \"visa bulletin\" OR subject:visa-bulletin) "
     "-from:admin@f5bot.com newer_than:1d",
     3, 1),
]


async def _gather_gmail() -> dict:
    """Run all Gmail searches + (for project_mentions hits) fetch bodies so the
    digest can show outreach snippets proactively, not just subjects."""
    calls = [
        ("search_gmail_messages", {
            "query": q,
            "user_google_email": USER_EMAIL,
            "page_size": 10,
        })
        for _, q, _, _ in GMAIL_QUERIES
    ]
    # Append a full-text fetch step in a second round-trip — IDs aren't known yet.
    raw_results = await _call_gw_tools(calls)

    by_label: dict[str, dict] = {}
    all_ids: list[str] = []
    project_mention_ids: list[str] = []
    for (label, query, _, _), raw in zip(GMAIL_QUERIES, raw_results):
        ids = _MSGID_RE.findall(raw or "")
        ids = ids[:8]
        by_label[label] = {"ids": ids, "query": query, "raw_search": raw}
        all_ids.extend(ids)
        if label == "project_mentions":
            project_mention_ids.extend(ids)

    # Second sub-MCP session: (a) metadata batch for all hits (for subjects),
    # (b) full body fetch per project_mentions hit (so we can show snippets +
    # outreach context). Body fetches are 1 call each; cap to 5 per run.
    metas: dict[str, str] = {}
    bodies: dict[str, str] = {}
    follow_up_calls: list[tuple[str, dict]] = []
    if all_ids:
        follow_up_calls.append(("get_gmail_messages_content_batch", {
            "user_google_email": USER_EMAIL,
            "message_ids": list(dict.fromkeys(all_ids)),
            "format": "metadata",
        }))
    for mid in project_mention_ids[:5]:
        follow_up_calls.append(("get_gmail_message_content", {
            "message_id": mid,
            "user_google_email": USER_EMAIL,
            "body_format": "text",
        }))

    if follow_up_calls:
        results = await _call_gw_tools(follow_up_calls)
        idx = 0
        if all_ids:
            batch_raw = results[idx]
            idx += 1
            blocks = re.split(r"(?:^|\n)(?:Message |)ID:\s*", batch_raw)
            for blk in blocks:
                if not blk.strip():
                    continue
                m_id = re.match(r"([0-9a-f]+)", blk)
                if not m_id:
                    continue
                mid = m_id.group(1)
                subj = re.search(r"Subject:\s*(.+)", blk)
                frm = re.search(r"From:\s*(.+)", blk)
                metas[mid] = (
                    f"{(frm.group(1).strip() if frm else '?')[:60]}: "
                    f"{(subj.group(1).strip() if subj else '(no subject)')[:120]}"
                )
        for mid in project_mention_ids[:5]:
            raw = results[idx] if idx < len(results) else ""
            idx += 1
            # Body starts after "--- BODY ---" in workspace-mcp output; fall
            # back to the whole payload if marker absent. Strip quoted replies
            # to keep the snippet focused on the new content.
            body = raw.partition("--- BODY ---")[2] or raw
            body = re.split(r"(?m)^(?:On .+ wrote:|>\s)", body)[0].strip()
            bodies[mid] = body[:400]
    return {"by_label": by_label, "metas": metas, "bodies": bodies}


# ─────────────────────────────────────────────────────────────────────────────
# External HTTP probes
# ─────────────────────────────────────────────────────────────────────────────

PROBE_TARGETS: list[tuple[str, str, list[str]]] = [
    # (label, path, list of substrings that MUST be present in body)
    ("home", "/", ["goatcounter"]),
    ("job_titles_directory", "/job-titles/", []),
    ("employers_directory", "/employers/", []),
    ("predictions", "/predictions/", []),
    ("blog", "/analysis/", []),
    ("salaries", "/salaries/", []),
]


async def _probe_one(client: httpx.AsyncClient, label: str, path: str, must_contain: list[str]) -> dict:
    url = f"{PROD_BASE_URL}{path}"
    try:
        r = await client.get(url, timeout=PROBE_TIMEOUT, follow_redirects=True)
        body_check = {s: (s in r.text) for s in must_contain}
        return {
            "label": label, "url": url, "status": r.status_code,
            "size": len(r.content), "body_check": body_check,
            "ok": r.status_code == 200 and all(body_check.values()),
        }
    except Exception as e:
        return {"label": label, "url": url, "status": 0, "ok": False, "error": f"{type(e).__name__}: {e}"}


async def _gather_probes() -> list[dict]:
    async with httpx.AsyncClient() as client:
        return list(await asyncio.gather(*(
            _probe_one(client, label, path, must) for label, path, must in PROBE_TARGETS
        )))


# ─────────────────────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────────────────────

def _humanize(n: int | float) -> str:
    n = float(n)
    if abs(n) < 1000:
        return f"{n:.0f}"
    if abs(n) < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.2f}M"


def _section_containers(rows: list[dict]) -> tuple[dict | None, str]:
    """Return (section_dict_or_None, status)."""
    if not rows:
        return ({"title": "Containers UNREACHABLE",
                 "body": "Could not enumerate vb_* containers.",
                 "importance": 5}, "red")
    down = [c for c in rows if c["state"].lower() != "running" or "unhealthy" in c["status"].lower()]
    if down:
        body = "\n".join(f"- **{c['name']}** ({c['state']}): {c['status']}" for c in down)
        return ({"title": "Containers DOWN / unhealthy", "body": body, "importance": 5}, "red")
    return (None, "green")


def _section_resources(res: dict) -> tuple[dict, str]:
    status = "green"
    lines = []
    if res["disk"]:
        pct = res["disk"]["used_pct"]
        if pct >= DISK_RED_PCT:
            status = "red"
        elif pct >= DISK_YELLOW_PCT:
            status = "yellow" if status == "green" else status
        lines.append(f"- Disk: **{pct}%** used ({res['disk']['used']} used, {res['disk']['avail']} free)")
    if res["mem"]:
        pct = res["mem"]["used_pct"]
        if pct >= MEM_RED_PCT:
            status = "red"
        elif pct >= MEM_YELLOW_PCT and status == "green":
            status = "yellow"
        lines.append(f"- Memory: **{pct}%** used ({res['mem']['used_mb']} / {res['mem']['total_mb']} MB)")
    if res["cpu"]:
        c = res["cpu"]
        suffix = ""
        per_cpu = c.get("load1_per_cpu")
        if per_cpu is not None:
            if per_cpu >= CPU_LOAD_RED:
                status = "red"
            elif per_cpu >= CPU_LOAD_YELLOW and status == "green":
                status = "yellow"
            suffix = f" — **{per_cpu:.2f}** per CPU on {c['nproc']} cores"
        lines.append(f"- CPU load: {c['load1']:.2f} / {c['load5']:.2f} / {c['load15']:.2f} (1/5/15min){suffix}")
    importance = {"red": 5, "yellow": 3, "green": 2}[status]
    title = "Homeserver resources" + ({"red": " — CRITICAL", "yellow": " — high", "green": ""}[status])
    return ({"title": title, "body": "\n".join(lines), "importance": importance}, status)


def _section_bulletin_refresh(info: dict) -> tuple[dict, str]:
    if not info.get("present"):
        return ({"title": "Bulletin refresh log MISSING",
                 "body": "Expected `/opt/stack/visa_bulletin/logs/cron/bulletin_refresh.log`. Hourly cron may not be running.",
                 "importance": 5}, "red")
    age = info["age_min"]
    status = "green"
    if age > BULLETIN_REFRESH_RED_MIN:
        status = "red"
    elif age > BULLETIN_REFRESH_YELLOW_MIN:
        status = "yellow"
    body_lines = [f"- Last cron output: **{age:.0f} min ago** (`{info['last_run']}`)"]
    if info.get("tail_errors"):
        status = "red" if status != "green" else "yellow"
        body_lines.append(f"- {len(info['tail_errors'])} error line(s) in last 200 log lines:")
        for err_line in info["tail_errors"][-5:]:
            body_lines.append(f"  `{err_line[:200]}`")
    if status == "green":
        return (None, "green")  # type: ignore[return-value]
    title = "Bulletin refresh " + ({"red": "FAILING", "yellow": "stale or noisy"}[status])
    return ({"title": title, "body": "\n".join(body_lines),
             "importance": 5 if status == "red" else 3}, status)


def _section_backup(info: dict) -> tuple[dict | None, str]:
    if not info.get("present"):
        return ({"title": "GDrive backup log MISSING",
                 "body": "Expected `/opt/stack/visa_bulletin/logs/cron/backup.log`. Daily backup may not be running.",
                 "importance": 5}, "red")
    age_hr = info["age_min"] / 60
    status = "green"
    if age_hr > BACKUP_RED_HOURS:
        status = "red"
    elif age_hr > BACKUP_YELLOW_HOURS:
        status = "yellow"
    if info.get("tail_errors"):
        status = "red"
    if status == "green":
        return (None, "green")
    body_lines = [f"- Last backup run: **{age_hr:.1f} hr ago** (`{info['last_run']}`)"]
    if info.get("tail_errors"):
        body_lines.append("- Recent error lines:")
        for err_line in info["tail_errors"][-3:]:
            body_lines.append(f"  `{err_line[:200]}`")
    return ({"title": "GDrive backup " + ({"red": "FAILING", "yellow": "overdue"}[status]),
             "body": "\n".join(body_lines),
             "importance": 5 if status == "red" else 3}, status)


def _section_postgres(pg: dict) -> tuple[dict | None, str]:
    status = "green"
    lines = []
    if pg.get("newest_bulletin"):
        try:
            d = date.fromisoformat(pg["newest_bulletin"])
            age_days = (date.today() - d).days
            if age_days > BULLETIN_DATA_STALE_DAYS_RED:
                status = "red"
            elif age_days > BULLETIN_DATA_STALE_DAYS_YELLOW:
                status = "yellow"
            # publication_date is the *month the bulletin governs*, so it can
            # legitimately be in the future (e.g. May 14 — DoS already published
            # the June bulletin).
            age_label = f"{age_days}d ago" if age_days >= 0 else f"in {-age_days}d (future month)"
            lines.append(f"- Newest bulletin published: **{d.isoformat()}** ({age_label})")
        except ValueError:
            pass
    if pg.get("last_ingest_completed"):
        lines.append(f"- Last successful IngestRun: `{pg['last_ingest_completed']}`")
    if pg.get("connections") is not None:
        lines.append(f"- Postgres connections: {pg['connections']}")
    if not lines:
        return (None, "green")
    if status == "green":
        # Postgres signals are informational when healthy — mid importance.
        return ({"title": "Postgres / data freshness", "body": "\n".join(lines), "importance": 2}, "green")
    return ({"title": "Bulletin data stale", "body": "\n".join(lines),
             "importance": 5 if status == "red" else 3}, status)


def _section_nginx(nx: dict) -> tuple[dict, str]:
    status = "green"
    total = nx.get("total", 0) or 0
    lines = [f"- Total requests (24h): **{_humanize(total)}**"]
    # Real-page traffic + visitor proxy from unique real-client IPs.
    page = nx.get("page_hits", 0)
    page_human = nx.get("page_hits_human", 0)
    page_bot = nx.get("page_hits_bot", 0)
    uniq_page = nx.get("unique_ips_page_24h", 0)
    uniq_human = nx.get("unique_ips_human_page_24h", 0)
    if page:
        bot_pct = (page_bot / page * 100) if page else 0
        lines.append(
            f"- Page hits 24h: **{_humanize(page)}** (human {_humanize(page_human)}, "
            f"bot {_humanize(page_bot)} = {bot_pct:.0f}%)"
        )
        lines.append(
            f"- Unique IPs on real pages 24h: **{_humanize(uniq_page)}** total, "
            f"**{_humanize(uniq_human)}** human (proxy for visitors — GoatCounter no longer exposes uniques)"
        )
    if total > 0:
        by = nx["by_class"]
        five = sum(v for k, v in by.items() if k.startswith("5"))
        pct_5xx = (five / total * 100) if total else 0
        if pct_5xx >= NGINX_5XX_RED_PCT:
            status = "red"
        elif pct_5xx >= NGINX_5XX_YELLOW_PCT:
            status = "yellow"
        klass_summary = ", ".join(f"{k}={_humanize(v)}" for k, v in sorted(by.items()))
        lines.append(f"- Status mix: {klass_summary} — **{pct_5xx:.2f}% 5xx**")
    if nx.get("top_5xx_paths"):
        lines.append("- Top 5xx paths:")
        for p, c in nx["top_5xx_paths"][:5]:
            lines.append(f"  - `{p}` — {c}")
    if nx.get("top_4xx_paths"):
        lines.append("- Top 4xx paths:")
        for p, c in nx["top_4xx_paths"][:5]:
            lines.append(f"  - `{p}` — {c}")
    if nx.get("top_ips"):
        # Flag abnormally heavy single-IP volume. Well-known crawlers
        # (Googlebot, Bingbot, Claude-SearchBot, etc.) are filtered out upstream
        # in the awk into `top_bot_ips`, so anything here is either a real
        # scraper or a heavy individual user.
        for ip, c in nx["top_ips"]:
            if c >= SCRAPER_IP_RED:
                status = "red"
                break
            if c >= SCRAPER_IP_YELLOW and status == "green":
                status = "yellow"
        top_5 = nx["top_ips"][:5]
        lines.append("- Top client IPs (real, excl. known crawlers):")
        for ip, c in top_5:
            mark = " ⚠️" if c >= SCRAPER_IP_YELLOW else ""
            lines.append(f"  - `{ip}` — {_humanize(c)}{mark}")
    if nx.get("top_bot_ips"):
        lines.append("- Top known-crawler IPs (informational, not flagged):")
        for ip, c in nx["top_bot_ips"][:5]:
            lines.append(f"  - `{ip}` — {_humanize(c)}")
    if nx.get("rate_limit_429"):
        rl = nx["rate_limit_429"]
        lines.append(f"- nginx 429 (rate-limited): {_humanize(rl)}")
    scanner = nx.get("scanner_paths") or []
    if scanner:
        total_scans = sum(c for _, c in scanner)
        if total_scans >= 3000 and status == "green":
            status = "yellow"
        lines.append(f"- Scanner-path probes (wp-admin, .env, etc.): **{_humanize(total_scans)}** total")
        for p, c in scanner[:5]:
            lines.append(f"  - `{p}` — {c}")
    importance = {"red": 5, "yellow": 3, "green": 2}[status]
    title = "Traffic + security (origin nginx, 24h)" + ({"red": " — CRITICAL", "yellow": " — review", "green": ""}[status])
    return ({"title": title, "body": "\n".join(lines), "importance": importance}, status)


def _section_goatcounter(gc: dict) -> tuple[dict, str]:
    """Surface pageview deltas vs a cycle-aware baseline + per-surface breakdown."""
    status = "green"
    pv_this = gc["totals_this_week"].get("total") or 0
    pv_prev = gc["totals_prev_week"].get("total") or 0
    pv_cycle = gc["totals_cycle_ago"].get("total") or 0
    # Primary signal: vs 4 weeks ago (one bulletin cycle, same day-of-week phase).
    delta_cycle = ((pv_this - pv_cycle) / pv_cycle * 100) if pv_cycle else None
    delta_wow = ((pv_this - pv_prev) / pv_prev * 100) if pv_prev else None
    if delta_cycle is not None and delta_cycle <= TRAFFIC_DROP_RED_PCT:
        status = "red"
    elif delta_cycle is not None and delta_cycle <= TRAFFIC_DROP_YELLOW_PCT:
        status = "yellow"

    def _fmt(d: float | None, label: str) -> str:
        if d is None:
            return f"(no {label} baseline)"
        sign = "+" if d >= 0 else ""
        return f"({sign}{d:.0f}% {label})"

    lines = [
        f"- Pageviews 7d: **{_humanize(pv_this)}** "
        f"vs 4 weeks ago **{_humanize(pv_cycle)}** {_fmt(delta_cycle, 'MoM cycle')}, "
        f"vs last week **{_humanize(pv_prev)}** {_fmt(delta_wow, 'WoW')}",
        "_Note: bulletin publishes monthly (~8th–15th) so WoW is misleading mid-cycle; MoM cycle is the primary signal._",
        "",
        "**By surface (top 100 paths, vs same 7d window 4 weeks ago — every delta is MoM cycle):**",
    ]
    for s in gc["surfaces"]:
        label = SURFACE_LABELS.get(s["surface"], s["surface"])
        lines.append(
            f"- {label}: **{_humanize(s['this_week'])}** "
            f"vs {_humanize(s['cycle_ago'])} 4w ago {_fmt(s['delta_pct'], 'MoM')}"
        )
    if gc["top_movers"]:
        lines.append("")
        lines.append("**Top movers vs 4 weeks ago (absolute change):**")
        for m in gc["top_movers"][:6]:
            lines.append(
                f"- `{m['path']}`: {_humanize(m['this_week'])} vs "
                f"{_humanize(m['cycle_ago'])} {_fmt(m['delta_pct'], 'MoM')}"
            )
    if gc["top_paths_this_week_truncated"]:
        lines.append("")
        lines.append("_Note: GoatCounter API caps at top-100 paths; longer tail not visible without full export._")
    importance = {"red": 5, "yellow": 4, "green": 3}[status]
    return ({"title": "Traffic (GoatCounter, 7d vs 4 weeks ago)", "body": "\n".join(lines), "importance": importance}, status)


# Thresholds for the per-surface performance signal. Yellow: any one surface
# has >=PERF_YELLOW_N3 page hits taking >3s in 24h. Red: same with >10s.
PERF_YELLOW_N3 = 50
PERF_RED_N10 = 5

# Surfaces we treat as user-facing "top properties" — the others (api,
# static_meta, other) are not interesting in this section.
TOP_PROPERTY_SURFACES = [
    "dashboard",
    "predictions",
    "salaries",
    "employer_profile",
    "employer_directory",
    "employer_rankings",
    "job_title_profile",
    "job_title_directory",
    "seo_landing_fam",
    "blog",
    "worksites",
    "donation_click",
    "static_pages",
]


def _section_top_properties(nx: dict, gc: dict | None) -> tuple[dict | None, str]:
    """Per-surface joined view: popularity (from GoatCounter, cycle-aware MoM)
    plus performance (from origin nginx 24h: mean latency + slow-tail counts).

    Answers the daily question "trends in popularity, performance" for top
    properties (salaries, employer/, job-titles, predictions, SEO landings).
    """
    lat: dict = nx.get("surface_latency") or {}
    if not lat and (not gc or not gc.get("surfaces")):
        return (None, "green")

    # Build GC popularity lookup by surface name.
    gc_by_surface: dict[str, dict] = {}
    if gc:
        for s in gc.get("surfaces") or []:
            gc_by_surface[s["surface"]] = s

    status = "green"
    rows: list[dict] = []
    for surf in TOP_PROPERTY_SURFACES:
        lat_row = lat.get(surf)
        gc_row = gc_by_surface.get(surf)
        # Always include every top property — even if both GC and nginx
        # are zero, the row makes the absence visible. salaries in particular
        # has historically had 9k+ nginx hits/day but zero GC tracking, which
        # is the kind of anomaly that hides if we silently drop missing rows.
        n3 = lat_row["n_over_3s"] if lat_row else 0
        n10 = lat_row["n_over_10s"] if lat_row else 0
        if n10 >= PERF_RED_N10:
            status = "red"
        elif n3 >= PERF_YELLOW_N3 and status == "green":
            status = "yellow"
        rows.append({"surface": surf, "lat": lat_row, "gc": gc_row})

    # Sort by GC 7d traffic desc (fallback to nginx 24h count if GC missing,
    # 0 otherwise — keeps fully-empty rows at the bottom but visible).
    def _sort_key(r: dict) -> int:
        if r["gc"]:
            return -int(r["gc"].get("this_week") or 0)
        if r["lat"]:
            return -int(r["lat"].get("count") or 0)
        return 0
    rows.sort(key=_sort_key)
    # Show all top properties (no truncation) — the list is bounded by
    # TOP_PROPERTY_SURFACES (~12 entries).

    def _fmt_pct(d: float | None) -> str:
        if d is None:
            return "(no MoM baseline)"
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.0f}% MoM"

    lines = [
        "_Popularity = GoatCounter 7d vs same 7d window 4 weeks ago (cycle-aware). "
        "Performance = origin nginx 24h, all real-page hits including bots._",
        "",
    ]
    for r in rows:
        surf = r["surface"]
        label = SURFACE_LABELS.get(surf, surf)
        lat_row = r["lat"]
        gc_row = r["gc"]
        pop_bit = ""
        if gc_row:
            cur = int(gc_row.get("this_week") or 0)
            cyc = int(gc_row.get("cycle_ago") or 0)
            pop_bit = (
                f"**{_humanize(cur)}** views 7d "
                f"(vs {_humanize(cyc)} 4w ago, {_fmt_pct(gc_row.get('delta_pct'))})"
            )
        else:
            pop_bit = "(no GC data — outside top-100)"
        perf_bit = ""
        if lat_row:
            mean_ms = int(lat_row["mean_ms"])
            cnt = lat_row["count"]
            n1, n3, n10 = lat_row["n_over_1s"], lat_row["n_over_3s"], lat_row["n_over_10s"]
            tail_bits = []
            if n1:
                tail_bits.append(f"{n1} >1s")
            if n3:
                tail_bits.append(f"{n3} >3s")
            if n10:
                tail_bits.append(f"**{n10} >10s**")
            tail = ", ".join(tail_bits) if tail_bits else "no slow tail"
            perf_bit = (
                f"mean **{mean_ms}ms** over {_humanize(cnt)} hits 24h ({tail})"
            )
            # Flag the salaries-style anomaly: high nginx volume but no GC.
            if not gc_row and cnt > 1000:
                perf_bit += " ⚠️ **anomaly: high nginx traffic but invisible to GC**"
        else:
            perf_bit = "(no nginx data)"
        lines.append(f"- {label}: {pop_bit} · {perf_bit}")

    title_suffix = {"red": " — CRITICAL (slow tail)", "yellow": " — slow tail", "green": ""}[status]
    importance = {"red": 5, "yellow": 3, "green": 2}[status]
    return (
        {
            "title": f"Top properties (popularity + performance){title_suffix}",
            "body": "\n".join(lines),
            "importance": importance,
        },
        status,
    )


# GSC traffic-drop thresholds (cycle-aware, on clicks).
GSC_CLICKS_DROP_YELLOW_PCT = -30
GSC_CLICKS_DROP_RED_PCT = -60


def _section_gsc(gsc: dict) -> tuple[dict | None, str]:
    """Render GSC clicks/impressions/CTR/position vs same window 4 weeks ago."""
    if not gsc:
        return (None, "green")
    tt = gsc["totals_this"]
    tc = gsc["totals_cycle"]
    clicks_this = tt["clicks"]
    clicks_cyc = tc["clicks"]
    impr_this = tt["impressions"]
    impr_cyc = tc["impressions"]
    pos_this = tt["avg_position"]
    pos_cyc = tc["avg_position"]
    ctr_this = tt["ctr"] * 100
    ctr_cyc = tc["ctr"] * 100

    status = "green"
    delta_clicks_pct = ((clicks_this - clicks_cyc) / clicks_cyc * 100) if clicks_cyc else None
    if delta_clicks_pct is not None and delta_clicks_pct <= GSC_CLICKS_DROP_RED_PCT:
        status = "red"
    elif delta_clicks_pct is not None and delta_clicks_pct <= GSC_CLICKS_DROP_YELLOW_PCT:
        status = "yellow"
    # Position climbing significantly (worse rank) is also a yellow flag.
    if pos_cyc and pos_this - pos_cyc >= 3.0 and status == "green":
        status = "yellow"

    def _fmt_pct(d: float | None) -> str:
        if d is None:
            return "(no baseline)"
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.0f}%"

    def _fmt_delta(cur: float, prev: float, unit: str = "") -> str:
        d = cur - prev
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.2f}{unit}"

    this_window = gsc["this_window"]
    cycle_window = gsc["cycle_window"]
    lines = [
        f"_Windows (GSC `final` data, ~2d lag): this={this_window[0]}..{this_window[1]}, "
        f"4w ago={cycle_window[0]}..{cycle_window[1]}._",
        "",
        f"- Clicks: **{_humanize(clicks_this)}** vs {_humanize(clicks_cyc)} "
        f"({_fmt_pct(delta_clicks_pct)} MoM cycle)",
        f"- Impressions: **{_humanize(impr_this)}** vs {_humanize(impr_cyc)} "
        f"({_fmt_pct(((impr_this - impr_cyc) / impr_cyc * 100) if impr_cyc else None)} MoM)",
        f"- CTR: **{ctr_this:.2f}%** vs {ctr_cyc:.2f}% ({_fmt_delta(ctr_this, ctr_cyc, 'pp')})",
        f"- Avg position: **{pos_this:.1f}** vs {pos_cyc:.1f} "
        f"({_fmt_delta(pos_this, pos_cyc)} — lower is better)",
    ]
    if gsc.get("top_queries"):
        lines.append("")
        lines.append("**Top queries this week (by clicks):**")
        for q in gsc["top_queries"][:8]:
            lines.append(
                f"- `{q['q'][:60]}` — {q.get('clicks',0)} clicks / "
                f"{_humanize(q.get('impressions',0))} impr, "
                f"pos {q.get('position',0):.1f}, CTR {(q.get('ctr',0)*100):.1f}%"
            )
    if gsc.get("top_movers"):
        lines.append("")
        lines.append("**Top page movers (Δ clicks vs 4 weeks ago):**")
        for m in gsc["top_movers"][:6]:
            sign = "+" if m["delta_clicks"] >= 0 else ""
            # Strip the domain prefix for readability if present
            url = m["url"]
            for prefix in ("https://visa-bulletin.us", "https://www.visa-bulletin.us"):
                if url.startswith(prefix):
                    url = url[len(prefix):] or "/"
                    break
            lines.append(
                f"- `{url[:70]}`: {m['clicks_this']} vs {m['clicks_cycle']} clicks "
                f"({sign}{m['delta_clicks']})"
            )
    importance = {"red": 5, "yellow": 4, "green": 3}[status]
    title = "SEO (Google Search Console, 7d vs 4 weeks ago)"
    if status == "red":
        title += " — CRITICAL drop"
    elif status == "yellow":
        title += " — regression"
    return ({"title": title, "body": "\n".join(lines), "importance": importance}, status)


def _section_probes(probes: list[dict]) -> tuple[dict | None, str]:
    failed = [p for p in probes if not p.get("ok")]
    if not failed:
        return (None, "green")
    lines = []
    for p in failed:
        if "error" in p:
            lines.append(f"- **{p['label']}** ({p['url']}): {p['error']}")
        else:
            missing = [k for k, v in (p.get("body_check") or {}).items() if not v]
            extra = f" — missing markers: {missing}" if missing else ""
            lines.append(f"- **{p['label']}** ({p['url']}): HTTP {p['status']}{extra}")
    return ({"title": "External probes FAILED",
             "body": "\n".join(lines),
             "importance": 5}, "red")


def _section_gmail(gmail: dict) -> tuple[dict | None, str]:
    """Render Gmail search hits across the configured queries."""
    by_label = gmail.get("by_label") or {}
    metas = gmail.get("metas") or {}
    bodies = gmail.get("bodies") or {}
    # Find the worst importance: max across queries that actually have hits.
    status = "green"
    sections: list[str] = []
    label_titles = {
        "f5bot": "F5Bot — Reddit mentions of \"visa bulletin\" / \"green card priority date\"",
        "uptime": "Uptime-monitor alerts",
        "project_mentions": "Other project mail (feedback, GSC, build, etc.)",
    }
    any_hits = False
    max_importance_if_hit = 1
    for label, query, imp_hit, _imp_empty in GMAIL_QUERIES:
        info = by_label.get(label) or {}
        ids = info.get("ids") or []
        title = label_titles.get(label, label)
        if not ids:
            sections.append(f"- **{title}** — none in last 24h")
            continue
        any_hits = True
        max_importance_if_hit = max(max_importance_if_hit, imp_hit)
        # Uptime hits are an actual alert → escalate status.
        if label == "uptime":
            status = "red"
        elif label == "f5bot" and status == "green":
            status = "yellow"  # not urgent, but triage today
        sections.append(f"- **{title}** — {len(ids)} message(s):")
        for mid in ids[:5]:
            meta = metas.get(mid) or "(metadata unavailable)"
            sections.append(f"    - `{mid}` — {meta}")
            # For project_mentions, show the leading snippet so outreach,
            # feedback, GSC alerts etc. are visible at-a-glance — saves a
            # round-trip into the inbox.
            if label == "project_mentions" and bodies.get(mid):
                snippet = re.sub(r"\s+", " ", bodies[mid]).strip()[:280]
                sections.append(f"      > {snippet}")
    if not any_hits:
        return (None, "green")
    importance = max_importance_if_hit if any_hits else 1
    body = (
        "_Daily Reddit-watch + uptime + project mentions (per POST_MIGRATION_TRACKER P1 \"Recurring: daily Reddit-watch via F5Bot\")._\n\n"
        + "\n".join(sections)
    )
    return ({"title": "Gmail signals (24h)", "body": body, "importance": importance}, status)


def _section_cloudflared(text: str) -> tuple[dict | None, str]:
    """Restart count + state from `docker inspect vb_cloudflared`."""
    line = text.strip()
    if "|" not in line:
        return (None, "green")
    rc, _, state = line.partition("|")
    try:
        rc_int = int(rc)
    except ValueError:
        return (None, "green")
    if state.lower() != "running":
        return ({"title": "vb_cloudflared not running",
                 "body": f"State: `{state}` (restart count {rc_int}). Tunnel may be down.",
                 "importance": 5}, "red")
    if rc_int > 10:
        return ({"title": f"vb_cloudflared restarted {rc_int}× since last reboot",
                 "body": "High restart count suggests tunnel instability; check CF Zero Trust dashboard.",
                 "importance": 3}, "yellow")
    return (None, "green")


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

mcp = FastMCP("visa_bulletin_daily_checkup")


@mcp.tool()
async def daily_checkup(since: str | None = None) -> str:
    """Return a JSON CheckupReport for visa_bulletin.

    Args:
        since: optional ISO 8601 timestamp; ignored — always reports last 24h
               (homeserver) and last 7 days (GoatCounter).
    """
    errors: list[str] = []
    sections: list[dict] = []
    statuses: list[str] = []

    # 1) Homeserver snapshot (one SSH round-trip)
    snap: dict | None = None
    try:
        snap = await asyncio.to_thread(_gather_homeserver_snapshot)
    except Exception as e:
        logger.exception("homeserver snapshot failed")
        errors.append(f"homeserver: {type(e).__name__}: {e}")
        sections.append({
            "title": "Homeserver UNREACHABLE",
            "body": f"SSH to `{SSH_ALIAS}` failed: {e}",
            "importance": 5,
        })
        statuses.append("red")

    # 2) GoatCounter + 3) external probes can run in parallel with parsing snap
    async def _safe_gc():
        try:
            return await _gather_goatcounter()
        except Exception as e:
            logger.exception("goatcounter gather failed")
            errors.append(f"goatcounter: {type(e).__name__}: {e}")
            return None

    async def _safe_probes():
        try:
            return await _gather_probes()
        except Exception as e:
            logger.exception("probes failed")
            errors.append(f"probes: {type(e).__name__}: {e}")
            return None

    async def _safe_gmail():
        try:
            return await _gather_gmail()
        except Exception as e:
            logger.exception("gmail gather failed")
            errors.append(f"gmail: {type(e).__name__}: {e}")
            return None

    async def _safe_gsc():
        try:
            return await _gather_gsc()
        except Exception as e:
            logger.exception("gsc gather failed")
            errors.append(f"gsc: {type(e).__name__}: {e}")
            return None

    gc_data, probe_data, gmail_data, gsc_data = await asyncio.gather(
        _safe_gc(), _safe_probes(), _safe_gmail(), _safe_gsc()
    )

    # Build sections from snapshot
    if snap is not None:
        # Containers
        rows = _parse_containers(snap.get("containers", ""))
        s, st = _section_containers(rows)
        if s:
            sections.append(s)
        statuses.append(st)
        # Resources
        s, st = _section_resources(_parse_resources(snap.get("resources", "")))
        sections.append(s)
        statuses.append(st)
        # Bulletin refresh cron
        s, st = _section_bulletin_refresh(_parse_log_age(snap.get("bulletin_refresh", "")))
        if s:
            sections.append(s)
        statuses.append(st)
        # Backup cron
        s, st = _section_backup(_parse_log_age(snap.get("backup", "")))
        if s:
            sections.append(s)
        statuses.append(st)
        # Postgres
        s, st = _section_postgres(_parse_postgres(snap.get("postgres", "")))
        if s:
            sections.append(s)
        statuses.append(st)
        # Nginx 24h (status mix + top 5xx/4xx paths + scanner probes + 429s + bot UAs)
        nx_parsed = _parse_nginx(snap.get("nginx", ""))
        s, st = _section_nginx(nx_parsed)
        sections.append(s)
        statuses.append(st)
        # Cloudflared
        s, st = _section_cloudflared(snap.get("cloudflared", ""))
        if s:
            sections.append(s)
        statuses.append(st)

    # GoatCounter section
    if gc_data is not None:
        s, st = _section_goatcounter(gc_data)
        sections.append(s)
        statuses.append(st)

    # Top properties (popularity from GC + performance from nginx 24h).
    # Needs at least nginx surface_latency or gc.surfaces; will skip if neither.
    if snap is not None:
        s, st = _section_top_properties(nx_parsed, gc_data)
        if s:
            sections.append(s)
            statuses.append(st)

    # Probes
    if probe_data is not None:
        s, st = _section_probes(probe_data)
        if s:
            sections.append(s)
        statuses.append(st)

    # Gmail signals
    if gmail_data is not None:
        s, st = _section_gmail(gmail_data)
        if s:
            sections.append(s)
        statuses.append(st)

    # GSC SEO signals
    if gsc_data is not None:
        s, st = _section_gsc(gsc_data)
        if s:
            sections.append(s)
        statuses.append(st)

    # Overall status (most severe wins)
    if "red" in statuses:
        overall = "red"
    elif "yellow" in statuses:
        overall = "yellow"
    else:
        overall = "green"

    # Summary: pick the worst section + key traffic number
    sections.sort(key=lambda s: -s.get("importance", 1))
    bits = []
    if overall == "red":
        bits.append("RED — needs action")
    elif overall == "yellow":
        bits.append("Yellow — review")
    else:
        bits.append("All systems normal")
    if gc_data:
        pv = gc_data["totals_this_week"].get("total") or 0
        pv_cycle = gc_data["totals_cycle_ago"].get("total") or 0
        if pv_cycle:
            delta = (pv - pv_cycle) / pv_cycle * 100
            bits.append(f"7d pageviews {_humanize(pv)} ({'+' if delta >= 0 else ''}{delta:.0f}% MoM cycle)")
        else:
            bits.append(f"7d pageviews {_humanize(pv)}")
    summary = ". ".join(bits) + "."

    report = {
        "project": "visa_bulletin",
        "status": overall,
        "summary": summary,
        "sections": sections,
        "errors": errors,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return json.dumps(report)


if __name__ == "__main__":
    mcp.run()
