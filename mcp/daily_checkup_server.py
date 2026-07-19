"""Daily checkup MCP server for visa_bulletin.

Gathers production-health, traffic, and security signals from:
  1. The homeserver (one SSH round-trip): vb_* container health, host
     resources, bulletin-refresh cron freshness, GDrive backup cron freshness,
     Postgres data-freshness signals (newest bulletin + last successful
     IngestRun), nginx access-log summary (status mix, top 500 app-exception
     paths + folded gateway-5xx total, top scraper IPs), and probes for known
     scanner paths (/wp-admin, /.env etc.).
  2. GoatCounter API: total pageviews/visitors week-over-week, top paths
     bucketed by surface (job titles, employers, predictions, blog, search,
     SEO landings, homepage, other), top movers.
  3. External HTTP probes: visa-bulletin.us + key sub-pages return 200 and
     still ship the GoatCounter beacon. A Cloudflare Managed Challenge
     (`cf-mitigated: challenge`, e.g. on /salaries/ since 2026-06-28) is
     availability-positive, not a probe failure — see _is_cf_challenge.

Returns a CheckupReport JSON per the contract at
  ~/.cursor/shared_rules/daily_checkup.mdc

State mutation: NONE. All reads.

Setup:
  - Configure an SSH alias `homeserver` for the production server in
    ~/.ssh/config (host/user/key are in the private ops repo) — or override
    via env var HOMESERVER_SSH_ALIAS.
  - Save GoatCounter API token at ~/tokens/goatcounter.token (mode 600).
  - Register in the orchestrator's registry.yaml — see README.md.
"""
from __future__ import annotations

import asyncio
import csv as csv_mod
import gzip
import io
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# Shared transport-aware MCP-call helper (agent_infra) — handles stdio (gsc) AND
# the google_workspace HTTP daemon. See ~/.claude/rules/daily_checkup.md.
sys.path.insert(0, str(Path.home() / "cursor_projects" / "agent_infra" / "daily_checkup"))
from mcp_call import call_mcp_tools  # noqa: E402

logger = logging.getLogger("visa_bulletin_daily_checkup")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

SSH_ALIAS = os.environ.get("HOMESERVER_SSH_ALIAS", "homeserver")
USER_EMAIL = os.environ.get("DAILY_CHECKUP_USER_EMAIL", "vyakunin@gmail.com")
SUB_MCP_TIMEOUT = 45
PROD_STACK = "/opt/stack/visa_bulletin"
STAGING_STACK = "/opt/stack/visa_bulletin_staging"
PROD_BASE_URL = "https://visa-bulletin.us"
STAGING_BASE_URL = "https://staging.visa-bulletin.us"

GOATCOUNTER_BASE = "https://vyakunin.goatcounter.com/api/v0"
GOATCOUNTER_TOKEN_PATH = Path.home() / "tokens" / "goatcounter.token"

# --- GA4 engagement ("long click" proxy) -----------------------------------
# Google's dwell/long-click signal isn't directly observable; the closest proxy
# is GA4 engaged sessions (>10s / 2+ pageviews / conversion) on organic-search
# landings. Watch list mirrors the 2026-07 profile-decline diagnosis: the
# /job-title/ + /employer/ pSEO surfaces are both the weakest-engagement AND
# the impression-losing ones (user asked 2026-07-04 to monitor these daily).
# Data via the shared `ga4` MCP (stdio, token ~/tokens/ga4_oauth_token.json).
GA4_PROPERTY_ID = "539743892"  # visa-bulletin.us
GA4_TIMEOUT = 45
# (label, landingPage prefix); None = all organic landings (site-wide).
GA4_SURFACES: list[tuple[str, str | None]] = [
    ("site organic", None),
    ("/job-title/*", "/job-title/"),
    ("/employer/*", "/employer/"),
    ("/salaries", "/salaries"),
]
GA4_ENGAGE_DROP_YELLOW_PT = 10.0  # WoW engagement-rate drop (points) → yellow
GA4_MIN_SESSIONS = 50             # below this N the rate is noise; never flag

# Thresholds
DISK_YELLOW_PCT = 70  # small SSD; want headroom for Postgres growth.
DISK_RED_PCT = 85
MEM_YELLOW_PCT = 80
MEM_RED_PCT = 92
CPU_LOAD_YELLOW = 1.0  # per-core (load1 / nproc)
CPU_LOAD_RED = 2.0
BULLETIN_REFRESH_YELLOW_MIN = 90    # cron runs hourly
BULLETIN_REFRESH_RED_MIN = 180
BACKUP_YELLOW_HOURS = 30            # cron runs daily at 01:00 UTC
BACKUP_RED_HOURS = 50
# /sitemap.xml is a PRE-RENDERED file that vb_nginx serves off disk
# (scripts/seo/render_sitemap.py, cron 02:40 + after each bulletin ingest).
# Staleness here is the one failure this project has burned itself on before:
# the retired prod bulletin cron 403'd SILENTLY for months. The renderer
# deliberately refuses to publish a degraded render and exits non-zero, leaving
# the last good file in place — correct, but invisible unless something grades
# the file's age. Loose thresholds: one missed daily run is fine, two is not.
SITEMAP_STALE_YELLOW_HOURS = 30
SITEMAP_STALE_RED_HOURS = 50
# Below this the file is not a plausible full sitemap (prod renders ~6.9k URLs).
# The renderer's own --min-urls gate should make this unreachable, so tripping it
# means someone --force'd a degraded render.
SITEMAP_MIN_PLAUSIBLE_URLS = 1000
# How old the newest bulletin's published_date may be before we worry. DoS
# publishes monthly; > 35 days suggests we missed one (parser broke / source
# rotated).
BULLETIN_DATA_STALE_DAYS_YELLOW = 35
BULLETIN_DATA_STALE_DAYS_RED = 50
# 5xx as % of total responses in last 24h.
NGINX_5XX_YELLOW_PCT = 0.5
NGINX_5XX_RED_PCT = 2.0
# A single path emitting many 5xx is almost always an app bug — an uncaught
# exception on a specific query shape (e.g. the 2026-06-10 EmptyResultSet 500s
# on /salaries/?employer=<unknown>: ~325/day, but only 0.53% of total traffic,
# so the total-% thresholds above never tripped). Flag per-path absolute counts
# directly so a localized regression surfaces even when it's a small slice of
# overall volume.
PATH_5XX_YELLOW = 30
PATH_5XX_RED = 100
# Gateway 5xx (502/503/504) are worker-recycle / deploy blips, not code bugs —
# a handful/day at ~0.001s is normal. Only fold-flag as yellow when BOTH the
# absolute count clears this AND it's a meaningful % of traffic (NGINX_5XX_YELLOW_PCT).
# Mirrors alert_5xx_spike.sh Rule 2 (gateway burst ≥20 & rate ≥2%).
GW_5XX_BURST = 50
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
# GoatCounter sporadically returns 404 (and 429) for valid requests, especially
# on /stats/total for a fresh time window — same symptom whether the caller is
# concurrent or the upstream is shedding. Linear 3×1s (6s total) wasn't enough
# on bad days (2 misses out of 17 morning runs). Exponential 1/2/4/8/16
# tolerates ~31s of upstream churn before giving up.
GC_RETRY_STATUSES = (404, 429, 502, 503, 504)
GC_RETRIES = 5
GC_RETRY_BACKOFF_S = 1.0

# Long-tail accuracy via GC /api/v0/export (per user 2026-05-27): the
# /stats/hits endpoint is server-side capped at 100 paths regardless of
# `limit`, which on visa-bulletin.us covers only ~57% of weekly pageviews.
# The export endpoint is 1/hour rate-limited per token and returns the full
# per-hit CSV. Cache aggressively so daily checkup + ad-hoc invocations
# share one export per ~6 hours.
GC_EXPORT_CACHE_DIR = Path.home() / ".cache" / "vb_daily_checkup"
GC_EXPORT_CACHE_TTL_S = 6 * 3600
GC_EXPORT_POLL_INTERVAL_S = 3.0
# /export jobs on visa-bulletin.us grew past ~2min end-to-end as the hit history
# grew (POST → server generates the full CSV → download a 10 MB+ file). At that
# size the export CANNOT complete inside the digest's response budget, so the
# DIGEST no longer waits for it: it polls only up to GC_EXPORT_DIGEST_BUDGET_S
# then serves the cached CSV (stale is fine for a morning digest). The slow
# export is owned by the OUT-OF-BAND refresher `scripts/refresh_gc_export.py`
# (systemd timer every 3h, generous GC_EXPORT_REFRESH_BUDGET_S), so the cache is
# normally <6h old and the digest hits the fast cache path without ever POSTing.
# The digest's own tight-budget attempt is just a safety net if the refresher died.
GC_EXPORT_DIGEST_BUDGET_S = 35.0
GC_EXPORT_REFRESH_BUDGET_S = 300.0

# Watchpoint thresholds for the "non-IND EB vs IND homepage" red flag (user
# request 2026-05-27): today the homepage template == India EB dashboard.
# If the rest of EB starts approaching India in views, the default needs
# revisiting.
MAIN_ENTRY_NONIND_EB_RATIO_YELLOW = 0.50
MAIN_ENTRY_NONIND_EB_RATIO_RED = 0.70

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
    # Spanish (/es/) cluster — check BEFORE the EN landing buckets so `/es/faq/`,
    # `/es/priority-date/<eb>/<country>/` etc. land here, not in static_pages/
    # priority_date. All `/es/*` routes roll into one Spanish-SEO surface.
    ("spanish", re.compile(r"^/es/?")),
    # Priority-date feature family (launched 2026-06-23 pSEO): hub
    # `/priority-date/`, per-EB rollup `/priority-date/<eb>/`, per-(eb×country)
    # landing `/priority-date/<eb>/<country>/`, AND the `/priority-date-calculator/`
    # tool — `^/priority-date` catches all four.
    ("priority_date", re.compile(r"^/priority-date")),
    # {occupation} H-1B-salary pSEO (`/h1b-salary/`, `/h1b-salary/<occ>/`,
    # `/h1b-salary/<employer>/<role>/`).
    ("occupation_salary", re.compile(r"^/h1b-salary")),
    # Top-H-1B-sponsors leaderboards (`/h1b-sponsors/in/<state>/`,
    # `/h1b-sponsors/<role>/`).
    ("h1b_sponsors", re.compile(r"^/h1b-sponsors/")),
    ("static_pages", re.compile(r"^/(faq|about|contact)/?$")),
    ("api", re.compile(r"^/api/")),
    ("static_meta", re.compile(r"^/(robots\.txt|sitemap\.xml|favicon)")),
]

# Finer-grained classifier for the combined "main entry" line (homepage + EB
# dashboards + FS dashboards). The default SURFACE_PATTERNS lumps `/` and
# `/employment-based/*` into one `dashboard` bucket — correct for traffic
# aggregation, but loses the IND-vs-non-IND split we need to flag when the
# rest of EB starts approaching India in views (user request 2026-05-27).
# Returns a bucket key or None.
_MAIN_ENTRY_HOME_RE     = re.compile(r"^/(\?|$)")
_MAIN_ENTRY_EB_INDIA_RE = re.compile(r"^/employment-based/india/?(\?|$)")
_MAIN_ENTRY_EB_OTHER_RE = re.compile(r"^/employment-based/(?!india/?(\?|$))")
_MAIN_ENTRY_FS_RE       = re.compile(r"^/family-sponsored/")


def _main_entry_bucket(path: str) -> str | None:
    """`home` | `eb_india` | `eb_other` | `fs` | None.

    `home` is just `/`. Per `project_homepage_is_india_eb` the homepage
    template == India EB dashboard, so for the IND-EB-vs-non-IND watchpoint
    we sum `home + eb_india` as one side of the ratio.
    """
    if _MAIN_ENTRY_HOME_RE.match(path):
        return "home"
    if _MAIN_ENTRY_EB_INDIA_RE.match(path):
        return "eb_india"
    if _MAIN_ENTRY_EB_OTHER_RE.match(path):
        return "eb_other"
    if _MAIN_ENTRY_FS_RE.match(path):
        return "fs"
    return None


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
    "spanish":             "Spanish cluster `/es/<...>` (landing, FAQ, predictions, priority-date)",
    "priority_date":       "Priority-date pSEO `/priority-date/<eb>/<country>/` + hub/rollup/calculator",
    "occupation_salary":   "{occupation} H-1B-salary pSEO `/h1b-salary/<...>`",
    "h1b_sponsors":        "Top-H-1B-sponsors leaderboards `/h1b-sponsors/<state|role>/`",
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
    # Off-box backup migrated to the shared backup_blob.sh cron (2026-06): it
    # writes to /opt/stack/_shared/logs/, NOT the legacy {stack}/logs/cron/backup.log
    # (which froze at 2026-06-17 and produced a daily false "backup FAILING" RED).
    prod_bak_log = "/opt/stack/_shared/logs/backup_visa_bulletin.log"

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
printf '==SECTION:sitemap==\n'
if [ -f /opt/stack/visa_bulletin/staticfiles/sitemap.xml ]; then
  stat -c '%Y|%s' /opt/stack/visa_bulletin/staticfiles/sitemap.xml
  grep -c '<loc>' /opt/stack/visa_bulletin/staticfiles/sitemap.xml
else
  echo MISSING
fi
printf '==SECTION:postgres==\n'
{psql} "SELECT MAX(publication_date) FROM bulletin;" 2>&1
{psql} "SELECT MAX(completed_at) FROM ingest_run WHERE status=3;" 2>&1
{psql} "SELECT count(*), max(EXTRACT(EPOCH FROM (now()-state_change))) FROM pg_stat_activity WHERE datname='visa_bulletin';" 2>&1
printf '==SECTION:dol_sources==\n'
{psql} "SELECT url FROM ingest_data_source WHERE source_type IN ('lca','perm','perm_disclosure');" 2>&1
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
    # Split per-path 5xx by class: 500 = app exception (real bug, path-specific —
    # e.g. the 2026-06-10 EmptyResultSet regression on /salaries/). 502/503/504 =
    # gateway/worker-recycle/deploy blips: NOT path-specific (upstream briefly
    # unreachable affects every path), fire at ~0.001s, and must NEVER be flagged
    # as a code regression. Track 500 per-path; gateway codes are summed in
    # by_5xx_status and folded into one total at render. See analytics.md
    # 500-vs-502 doctrine (already applied to alert_5xx_spike.sh 2026-06-14).
    if (status=="500") top_500_path[path]++
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
    n=0; for (p in top_500_path) {{ paths[n]=p; counts[n]=top_500_path[p]; n++ }}
    for (i=0;i<n && i<10;i++) {{
      mi=i; for (j=i+1;j<n;j++) if (counts[j]>counts[mi]) mi=j
      if (mi!=i) {{ t=counts[i];counts[i]=counts[mi];counts[mi]=t;t=paths[i];paths[i]=paths[mi];paths[mi]=t }}
      print "500_path=" paths[i] "|" counts[i]
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
# Force success: we ran with `set +e` to tolerate per-command failures and
# collect partial data. Without this, the script's exit code is the last
# command's rc — e.g. `docker inspect` returns 1 when vb_cloudflared isn't
# present, which made _run_ssh raise RuntimeError despite a full snapshot.
exit 0
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


def _parse_log_age(text: str, latest_run_marker: str | None = None) -> dict:
    """Section format: first line = epoch mtime, rest = tail of log.

    `latest_run_marker`: a run-boundary string (e.g. the cron's banner line). When
    given, errors are counted only from the MOST RECENT run, not the whole tail.
    An hourly job hitting an external gov site logs the occasional transient
    timeout that the very next run recovers from; scanning the full ~200-line
    window (~1.5 days of hourly runs) re-surfaces a healed blip as "noisy" for
    days. Only the latest run reflects current health — and a genuinely broken
    run fails the latest run too, so real outages still flag.
    """
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
    scan = tail
    if latest_run_marker and latest_run_marker in tail:
        scan = tail[tail.rindex(latest_run_marker):]
    error_lines = [
        line for line in scan.splitlines()
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
        "top_500_paths": [],  # app exceptions only (502/503/504 folded via 5xx_status)
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
        elif key == "500_path":
            path, _, cnt = val.partition("|")
            try:
                out["top_500_paths"].append((path, int(cnt)))
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
    url = f"{GOATCOUNTER_BASE}{path}"
    last_exc: Exception | None = None
    for attempt in range(GC_RETRIES + 1):
        try:
            r = await client.get(url, params=params, timeout=GC_TIMEOUT)
            if r.status_code in GC_RETRY_STATUSES and attempt < GC_RETRIES:
                backoff = GC_RETRY_BACKOFF_S * (2 ** attempt)
                logger.info("goatcounter %s -> %d, retry %d/%d after %.1fs",
                            path, r.status_code, attempt + 1, GC_RETRIES, backoff)
                await asyncio.sleep(backoff)
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_exc = e
            if attempt < GC_RETRIES:
                backoff = GC_RETRY_BACKOFF_S * (2 ** attempt)
                logger.info("goatcounter %s transport error %s, retry %d/%d after %.1fs",
                            path, type(e).__name__, attempt + 1, GC_RETRIES, backoff)
                await asyncio.sleep(backoff)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("goatcounter retry loop exited without response")


def _bucket_path(p: str) -> str:
    for name, pattern in SURFACE_PATTERNS:
        if pattern.match(p):
            return name
    return "other"


# A real visa-bulletin.us export is ~9 MB / hundreds of thousands of hit rows.
# A truncated/empty/error-body "download" (200 status but garbage) must NEVER
# replace the last good pull — that's the one we fall back to on rate-limit.
# Require a plausible floor of data-rows before trusting a fresh download.
GC_EXPORT_MIN_VALID_ROWS = 1000


def _gc_export_looks_valid(raw: bytes) -> bool:
    """True iff `raw` is a plausible untruncated GC export CSV.

    Guards the cache-overwrite: GoatCounter can return a 200 with an empty
    or partial body, and clobbering the cached good pull with it would leave
    nothing to fall back to on the next rate-limited run. Checks: non-empty,
    decompresses if gzip, has the `Path` header (with the known `2` prefix
    quirk tolerated), and carries at least GC_EXPORT_MIN_VALID_ROWS rows.
    """
    if not raw:
        return False
    try:
        if raw[:2] == b"\x1f\x8b":  # gzip magic
            raw = gzip.decompress(raw)
    except (OSError, EOFError):
        return False
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("2Path,"):
        text = text[1:]
    if not text.startswith("Path,"):
        return False
    # newline count ≈ row count; cheap and avoids a full CSV parse here.
    return text.count("\n") >= GC_EXPORT_MIN_VALID_ROWS


async def _gc_export_full_csv(
    client: httpx.AsyncClient,
    *,
    budget_s: float = GC_EXPORT_DIGEST_BUDGET_S,
    force: bool = False,
) -> Path | None:
    """Run /api/v0/export round-trip and return the path to the cached CSV.

    GoatCounter caps `/stats/hits` at 100 paths, missing ~43% of the long
    tail on visa-bulletin.us. /export gives the full per-hit CSV but is
    1/hour rate-limited per token; we cache for GC_EXPORT_CACHE_TTL_S so
    daily-checkup + ad-hoc invocations share one export. Falls back to the
    last good pull (validated, atomically written — see below) on rate-limit
    / fetch failure / a garbage download; returns None only if no cache
    exists at all and the fresh fetch failed.

    `budget_s` caps the wall-clock spent POLLING for the export job to finish
    before serving the stale cache. The DIGEST passes the tight default
    (GC_EXPORT_DIGEST_BUDGET_S) so it never blocks past its response budget;
    the out-of-band refresher (`scripts/refresh_gc_export.py`) passes a generous
    budget + `force=True` to bypass the TTL and actually pull a fresh CSV.
    """
    GC_EXPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = GC_EXPORT_CACHE_DIR / "gc_export.csv"
    if csv_path.exists() and not force:
        age_s = time.time() - csv_path.stat().st_mtime
        if age_s < GC_EXPORT_CACHE_TTL_S:
            logger.info("gc export: using fresh cache (%ds old)", int(age_s))
            return csv_path

    try:
        create = await client.post(
            f"{GOATCOUNTER_BASE}/export",
            json={"format": "csv"},
            timeout=GC_TIMEOUT,
        )
    except (httpx.TransportError, httpx.TimeoutException) as e:
        logger.warning("gc export POST transport error: %s", e)
        return csv_path if csv_path.exists() else None

    if create.status_code == 429:
        logger.info("gc export rate-limited; serving stale cache (or None): %s",
                    create.text[:200])
        return csv_path if csv_path.exists() else None
    if create.status_code >= 400:
        logger.warning("gc export POST %d: %s", create.status_code, create.text[:200])
        return csv_path if csv_path.exists() else None

    try:
        job = create.json()
    except (ValueError, json.JSONDecodeError):
        logger.warning("gc export response not JSON: %s", create.text[:200])
        return csv_path if csv_path.exists() else None
    job_id = job.get("id")
    if job_id is None:
        logger.warning("gc export response missing id: %s", job)
        return csv_path if csv_path.exists() else None

    finished = False
    deadline = time.monotonic() + budget_s
    attempt = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(GC_EXPORT_POLL_INTERVAL_S)
        attempt += 1
        try:
            r = await client.get(f"{GOATCOUNTER_BASE}/export/{job_id}", timeout=GC_TIMEOUT)
            r.raise_for_status()
        except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            logger.info("gc export poll attempt %d failed: %s", attempt, e)
            continue
        if (r.json() or {}).get("finished_at"):
            finished = True
            break
    if not finished:
        logger.warning(
            "gc export not ready within %.0fs budget (%d polls); serving stale cache. "
            "The out-of-band refresher (scripts/refresh_gc_export.py) owns the slow pull.",
            budget_s, attempt,
        )
        return csv_path if csv_path.exists() else None

    try:
        dl = await client.get(
            f"{GOATCOUNTER_BASE}/export/{job_id}/download",
            timeout=GC_TIMEOUT * 4,
        )
        dl.raise_for_status()
    except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
        logger.warning("gc export download failed: %s", e)
        return csv_path if csv_path.exists() else None

    if not _gc_export_looks_valid(dl.content):
        # 200 but truncated/empty/error body — keep the last good pull rather
        # than clobbering it (it's our rate-limit fallback). (user 2026-06-17.)
        logger.warning(
            "gc export download invalid (%d bytes); keeping last good pull",
            len(dl.content),
        )
        return csv_path if csv_path.exists() else None

    # Atomic replace: write to a temp sibling then rename, so a crash/partial
    # write mid-download can't corrupt the cached good pull.
    tmp_path = csv_path.with_suffix(".csv.tmp")
    tmp_path.write_bytes(dl.content)
    tmp_path.replace(csv_path)
    logger.info("gc export downloaded: %d bytes (validated)", len(dl.content))
    return csv_path


def _aggregate_csv_path_counts(
    csv_path: Path,
    windows: list[tuple[str, date, date]],
) -> dict[str, dict[str, int]]:
    """Read GC export CSV and return `{window_name: {path: count}}`.

    CSV schema (as of 2026-05): Path, Title, Event, UserAgent, Browser,
    System, Session, Bot, Referrer, Referrer scheme, Screen size, Location,
    FirstVisit, Date (ISO 8601 UTC). Each row is one hit. Bot rows (Bot != "0")
    are dropped to match /stats/total numbers (which exclude bots).

    Quirks:
    - The file is gzip-compressed (download serves `.csv.gz` regardless of
      Accept-Encoding). Auto-detect via magic bytes.
    - The header is prefixed with a literal `'2'` byte (GoatCounter quirk;
      seen on every export). Strip if present so the first column name
      reads as `Path` not `2Path`.
    - Paths include query strings on older rows (pre-2026-05 query-strip
      change); strip query for consistency with current GC UI counts.
    - **`/stats/total` counts FirstVisit=1 (first hit per session), not raw
      hits**. To make per-surface sums match the headline "8.7k pageviews"
      number, filter to FirstVisit=1 here. CSV with Bot=0 alone yields ~50%
      more rows (subsequent-hit-in-session) than the API reports.
    """
    out: dict[str, dict[str, int]] = {name: defaultdict(int) for name, _, _ in windows}
    raw = csv_path.read_bytes()
    if raw[:2] == b"\x1f\x8b":  # gzip magic
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("2Path,"):
        text = text[1:]
    rdr = csv_mod.DictReader(io.StringIO(text))
    for row in rdr:
        raw_date = (row.get("Date") or "")[:10]
        try:
            d = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if (row.get("Bot") or "0") != "0":
            continue
        if (row.get("FirstVisit") or "0") != "1":
            continue
        # Events (ad-view / ad-fill / aff-view beacons) are NOT pageviews —
        # GoatCounter records them as paths, but counting them inflates the
        # totals + dumps them into the "other" surface. Exclude so per-surface
        # sums and the headline pageview total are real pages only.
        # (user 2026-06-17: long-tail accuracy.)
        if (row.get("Event") or "0") not in ("0", ""):
            continue
        path = (row.get("Path") or "").split("?", 1)[0]
        # Canonicalize the trailing slash so direct-hit / redirect variants
        # (`/employment-based/india` vs `/employment-based/india/`) merge into
        # one path instead of splitting the long tail. All SURFACE_PATTERNS /
        # main-entry regexes are slash-tolerant, so this only affects keying.
        path = path.rstrip("/") or "/"
        for name, start, end in windows:
            if start <= d <= end:
                out[name][path] += 1
    return {name: dict(counts) for name, counts in out.items()}


def _gc_export_max_ts(csv_path: Path) -> datetime | None:
    """Newest row timestamp in the export CSV — marks the data cutoff.

    GoatCounter beacons are near-real-time, but the daily run pulls the export
    mid-morning, so the CURRENT day is partial (only hits up to this timestamp).
    Comparison windows must anchor at the last COMPLETE day (= cutoff.date() - 1
    day) and report the partial current day separately, else "this week"
    includes a ~6h day and understates the trend. (user 2026-06-17.)
    """
    try:
        raw = csv_path.read_bytes()
    except OSError:
        return None
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("2Path,"):
        text = text[1:]
    mx: datetime | None = None
    for row in csv_mod.DictReader(io.StringIO(text)):
        ds = row.get("Date") or ""
        if not ds:
            continue
        try:
            ts = datetime.fromisoformat(ds.replace("Z", "+00:00"))
        except ValueError:
            continue
        if mx is None or ts > mx:
            mx = ts
    return mx


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
    headers = {"Authorization": f"Bearer {token}"}
    # GoatCounter returns 404 on concurrent requests; serialize.
    async with httpx.AsyncClient(headers=headers) as client:
        # Long-tail accuracy: the full per-hit CSV via /export is the ONLY
        # analytical source for per-path / per-surface / pageview-total numbers.
        # The /stats/hits endpoint is capped at 100 paths and is NEVER used as a
        # fallback (user 2026-06-17: "never, ever use top 100 ... we care a lot
        # about long tail"). If the export is unavailable, per-page data is
        # reported as unavailable rather than silently truncated.
        # Fetch it FIRST so we know the data cutoff before anchoring windows.
        csv_path = await _gc_export_full_csv(client)
        # Anchor ALL comparison windows at the last COMPLETE day. The export's
        # newest row is the data cutoff; the current day is partial (the daily
        # run pulls mid-morning), so including it understates "this week" and
        # makes the trend look worse than reality. Anchor = cutoff.date() - 1.
        # No export → fall back to `today` (per-page data is unavailable anyway).
        # (user 2026-06-17: only compare full data, surface the partial day.)
        cutoff_ts = (_gc_export_max_ts(csv_path)
                     if csv_path is not None and csv_path.exists() else None)
        cutoff_date = cutoff_ts.date() if cutoff_ts else None
        anchor = (cutoff_date - timedelta(days=1)) if cutoff_date else today
        this_end = anchor
        this_start = anchor - timedelta(days=6)
        prev_end = this_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        cycle_end = anchor - timedelta(days=28)
        cycle_start = cycle_end - timedelta(days=6)
        # 28-day-average-per-week baseline (user 2026-05-27 — comparable to
        # both `prev_7d` and `cycle_7d` but smoother / less cycle-noisy).
        last28_end = anchor
        last28_start = anchor - timedelta(days=27)
        totals_this = await _gc_get(client, "/stats/total",
                                    start=this_start.isoformat(), end=this_end.isoformat())
        totals_prev = await _gc_get(client, "/stats/total",
                                    start=prev_start.isoformat(), end=prev_end.isoformat())
        totals_cycle = await _gc_get(client, "/stats/total",
                                     start=cycle_start.isoformat(), end=cycle_end.isoformat())
        totals_last28 = await _gc_get(client, "/stats/total",
                                      start=last28_start.isoformat(), end=last28_end.isoformat())

    # No top-100 fallback: per-path / per-surface come solely from the export
    # CSV. These stay empty so the CSV-absent path reports "unavailable".
    surf_this: dict[str, int] = {}
    surf_cycle: dict[str, int] = {}
    paths_this: dict[str, int] = {}
    paths_cycle: dict[str, int] = {}

    # CSV-derived path counts across all 4 windows (used for both main-entry
    # breakdown and full-coverage per-surface counts). Available iff the
    # /export endpoint succeeded (or stale cache is present).
    path_counts_by_window: dict[str, dict[str, int]] | None = None
    csv_status = "missing"
    csv_age_s: float | None = None
    partial_pv: int | None = None  # pageviews on the excluded partial current day
    if csv_path is not None and csv_path.exists():
        csv_age_s = time.time() - csv_path.stat().st_mtime
        csv_status = "ok" if csv_age_s < GC_EXPORT_CACHE_TTL_S else "stale"
        windows = [
            ("this_7d",  this_start,   this_end),
            ("prev_7d",  prev_start,   prev_end),
            ("cycle_7d", cycle_start,  cycle_end),
            ("last_28d", last28_start, last28_end),
        ]
        # Count the partial current day too (so we can report what was excluded),
        # then pop it before any window math so it never leaks into the trend.
        if cutoff_date is not None:
            windows.append(("_partial", cutoff_date, cutoff_date))
        path_counts_by_window = _aggregate_csv_path_counts(csv_path, windows)
        if cutoff_date is not None:
            partial_pv = sum(path_counts_by_window.pop("_partial", {}).values())

    # Pageview totals derived from the (event-excluded, untruncated) CSV —
    # authoritative and consistent with the per-surface sums. /stats/total
    # counts ad/affiliate event beacons as hits, so it is used only as a
    # labelled fallback when the export is unavailable.
    pageviews_by_window: dict[str, int] | None = None
    if path_counts_by_window is not None:
        pageviews_by_window = {
            w: sum(c.values()) for w, c in path_counts_by_window.items()
        }

    # Per-surface deltas. Prefer CSV path_counts (100% coverage, all 4
    # windows). Fall back to top-100 hit counts when CSV unavailable.
    csv_source = path_counts_by_window is not None
    surface_deltas = _build_surface_deltas(
        path_counts_by_window=path_counts_by_window,
        fallback_surf_this=surf_this,
        fallback_surf_cycle=surf_cycle,
    )

    # Top movers (vs 4 weeks ago, paths present in either window). Use CSV
    # paths when available so the mover list isn't capped at top-100 either.
    if csv_source:
        paths_this_full = path_counts_by_window["this_7d"]
        paths_cycle_full = path_counts_by_window["cycle_7d"]
    else:
        paths_this_full = paths_this
        paths_cycle_full = paths_cycle
    movers = []
    for p in set(paths_this_full) | set(paths_cycle_full):
        cur = paths_this_full.get(p, 0)
        cyc = paths_cycle_full.get(p, 0)
        if cur + cyc < 50:
            continue
        delta_pct = ((cur - cyc) / cyc * 100) if cyc else None
        movers.append({"path": p, "this_week": cur, "cycle_ago": cyc, "delta_pct": delta_pct})
    movers.sort(key=lambda r: -abs(r["this_week"] - r["cycle_ago"]))
    movers = movers[:10]

    # Main-entry (home + EB + FS) breakdown — IND-EB-vs-rest watchpoint.
    main_entry: dict[str, dict[str, int]] | None = None
    if path_counts_by_window is not None:
        main_entry = {}
        for win_name, counts in path_counts_by_window.items():
            buckets: dict[str, int] = defaultdict(int)
            for path, cnt in counts.items():
                b = _main_entry_bucket(path)
                if b:
                    buckets[b] += cnt
            buckets["all"] = (
                buckets.get("home", 0) + buckets.get("eb_india", 0)
                + buckets.get("eb_other", 0) + buckets.get("fs", 0)
            )
            main_entry[win_name] = dict(buckets)

    return {
        "totals_this_week": totals_this,
        "totals_prev_week": totals_prev,
        "totals_cycle_ago": totals_cycle,
        "totals_last_28d": totals_last28,
        "surfaces": surface_deltas,
        "surfaces_source": "csv_full" if csv_source else "top100_hits",
        "top_movers": movers,
        "pageviews": pageviews_by_window,
        "totals_source": "csv_pageviews" if pageviews_by_window else "stats_total_events_incl",
        "top_paths_this_week_truncated": False,
        "top100_coverage_this_pct": None,
        "main_entry": main_entry,
        "csv_status": csv_status,
        "csv_age_s": csv_age_s,
        # Windows anchor at the last COMPLETE day (anchor); the partial current
        # day is excluded from every comparison and reported separately so the
        # trend is full-days-only. (user 2026-06-17.)
        "anchor_last_complete_day": anchor.isoformat(),
        "partial_day": (
            {
                "date": cutoff_date.isoformat(),
                "pageviews_so_far": partial_pv,
                "cutoff_utc": cutoff_ts.isoformat() if cutoff_ts else None,
            }
            if cutoff_date is not None
            else None
        ),
        "window": {
            "this": [this_start.isoformat(), this_end.isoformat()],
            "prev": [prev_start.isoformat(), prev_end.isoformat()],
            "cycle_ago": [cycle_start.isoformat(), cycle_end.isoformat()],
            "last_28d": [last28_start.isoformat(), last28_end.isoformat()],
        },
    }


def _build_surface_deltas(
    *,
    path_counts_by_window: dict[str, dict[str, int]] | None,
    fallback_surf_this: dict[str, int],
    fallback_surf_cycle: dict[str, int],
) -> list[dict]:
    """Per-surface counts across all 4 windows + MoM cycle delta.

    When CSV is available, sums every path's count into its surface bucket —
    so the surface totals match `/stats/total` (no top-100 cap). Otherwise
    falls back to the top-100 `/stats/hits` buckets (this_week and cycle_ago
    only; prev_week / last_28d_per_week left as None).
    """
    if path_counts_by_window is None:
        all_surfaces = set(fallback_surf_this) | set(fallback_surf_cycle)
        rows = []
        for s in all_surfaces:
            cur = fallback_surf_this.get(s, 0)
            cyc = fallback_surf_cycle.get(s, 0)
            delta_pct = ((cur - cyc) / cyc * 100) if cyc else None
            rows.append({
                "surface": s,
                "this_week": cur,
                "cycle_ago": cyc,
                "prev_week": None,
                "last28_per_week": None,
                "delta_pct": delta_pct,
                # WoW needs prev_7d, unavailable in the top-100 fallback path.
                "wow_pct": None,
                # share/pages need full coverage; never from a top-100 sum.
                "share_pct": None,
                "pages": None,
            })
        rows.sort(key=lambda r: -r["this_week"])
        return rows

    by_surface: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Distinct this_7d pages per surface — the long-tail size (how many separate
    # /employer/<slug>/ etc. pages roll up into the bucket). Surfaced in the
    # digest so a tiny per-page tail that nonetheless sums to a real share stays
    # legible (user 2026-06-17 wanted the section table with page counts).
    pages_this: dict[str, set[str]] = defaultdict(set)
    for win_name, path_counts in path_counts_by_window.items():
        for path, cnt in path_counts.items():
            surf = _bucket_path(path)
            by_surface[surf][win_name] += cnt
            if win_name == "this_7d":
                pages_this[surf].add(path)
    total_this = sum(wm.get("this_7d", 0) for wm in by_surface.values())
    rows = []
    for surf, win_map in by_surface.items():
        cur = win_map.get("this_7d", 0)
        cyc = win_map.get("cycle_7d", 0)
        prev = win_map.get("prev_7d", 0)
        last28 = win_map.get("last_28d", 0)
        delta_pct = ((cur - cyc) / cyc * 100) if cyc else None
        wow_pct = ((cur - prev) / prev * 100) if prev else None
        rows.append({
            "surface": surf,
            "this_week": cur,
            "cycle_ago": cyc,
            "prev_week": prev,
            "last28_per_week": last28 / 4 if last28 else 0,
            "delta_pct": delta_pct,
            "wow_pct": wow_pct,
            # Full-coverage extras (CSV path only — None in the fallback above).
            "share_pct": (cur / total_this * 100) if total_this else None,
            "pages": len(pages_this[surf]),
        })
    rows.sort(key=lambda r: -r["this_week"])
    return rows




# ─────────────────────────────────────────────────────────────────────────────
# Gmail (sub-MCP: google_workspace)
# ─────────────────────────────────────────────────────────────────────────────

_MSGID_RE = re.compile(r"Message ID:\s*([0-9a-f]+)", re.IGNORECASE)


def _ga4_report_args(start: str, end: str) -> dict:
    """runReport args: organic-search landings, engagement metrics, one window."""
    return {
        "property_id": GA4_PROPERTY_ID,
        "start_date": start,
        "end_date": end,
        "dimensions": ["landingPage"],
        "metrics": ["sessions", "engagedSessions", "userEngagementDuration"],
        "dimension_filter": {"filter": {
            "fieldName": "sessionDefaultChannelGroup",
            "stringFilter": {"value": "Organic Search"},
        }},
        # Full coverage (complete_data_queries): every distinct landing page,
        # aggregated into surface buckets client-side. ~2-3k/wk today.
        "row_limit": 100000,
    }


def _ga4_bucket(rows: list[dict]) -> dict[str, dict]:
    """Aggregate landing-page rows into the monitored surface buckets."""
    out: dict[str, dict] = {
        label: {"sessions": 0, "engaged": 0, "eng_dur": 0.0} for label, _ in GA4_SURFACES
    }
    for r in rows:
        page = r.get("landingPage", "") or ""
        sess = int(r.get("sessions") or 0)
        eng = int(r.get("engagedSessions") or 0)
        dur = float(r.get("userEngagementDuration") or 0)
        for label, prefix in GA4_SURFACES:
            if prefix is None or page.startswith(prefix):
                b = out[label]
                b["sessions"] += sess
                b["engaged"] += eng
                b["eng_dur"] += dur
    return out


async def _gather_ga4_engagement() -> dict:
    """This-7d vs prior-7d organic engagement per surface, via the ga4 MCP."""
    calls = [
        ("ga4_run_report", _ga4_report_args("7daysAgo", "yesterday")),
        ("ga4_run_report", _ga4_report_args("14daysAgo", "8daysAgo")),
    ]
    this_raw, prior_raw = await call_mcp_tools("ga4", calls, timeout=GA4_TIMEOUT)
    return {
        "this_7d": _ga4_bucket((this_raw or {}).get("rows") or []),
        "prior_7d": _ga4_bucket((prior_raw or {}).get("rows") or []),
    }


def _ga4_rate_pct(b: dict) -> float:
    return b["engaged"] / b["sessions"] * 100 if b["sessions"] else 0.0


def _section_ga4_engagement(ga4: dict) -> tuple[dict, str]:
    """Engagement per surface, raw numbers for BOTH windows (analytics rule)."""
    cur, prev = ga4["this_7d"], ga4["prior_7d"]
    status = "green"
    flags: list[str] = []
    lines: list[str] = []
    for label, _ in GA4_SURFACES:
        c, p = cur[label], prev[label]
        c_dur = c["eng_dur"] / c["sessions"] if c["sessions"] else 0.0
        p_dur = p["eng_dur"] / p["sessions"] if p["sessions"] else 0.0
        lines.append(
            f"- {label}: {c['sessions']} sess, {c['engaged']} engaged "
            f"({_ga4_rate_pct(c):.0f}%), {c_dur:.0f}s engaged-time/sess | prior 7d: "
            f"{p['sessions']} sess, {p['engaged']} engaged ({_ga4_rate_pct(p):.0f}%), {p_dur:.0f}s"
        )
        if c["sessions"] >= GA4_MIN_SESSIONS and p["sessions"] >= GA4_MIN_SESSIONS:
            drop_pt = _ga4_rate_pct(p) - _ga4_rate_pct(c)
            if drop_pt >= GA4_ENGAGE_DROP_YELLOW_PT:
                status = "yellow"
                flags.append(f"{label} engagement −{drop_pt:.0f}pt WoW")
    title = "GA4 engagement — organic landings (long-click proxy)"
    if flags:
        title += ": " + "; ".join(flags)
    lines.append(
        "Engaged = >10s / 2+ pages / conversion. Watch list: /job-title/ + "
        "/employer/ (weakest + impression-losing surfaces, 2026-07 diagnosis)."
    )
    section = {
        "title": title,
        "body": "\n".join(lines),
        "importance": 3 if status == "yellow" else 2,
    }
    return section, status


async def _call_gw_tools(calls: list[tuple[str, dict]]) -> list[str]:
    """Run multiple google_workspace tool calls over one session; raw text payloads."""
    return await call_mcp_tools("google_workspace", calls, timeout=SUB_MCP_TIMEOUT, parse=False)


# Queries we run against Gmail. Each tuple is (label, query, importance_if_hit,
# importance_if_empty).
GMAIL_QUERIES: list[tuple[str, str, int, int]] = [
    # NOTE: F5Bot / Reddit-mention triage moved to visa_bulletin_PLATFORM
    # (marketing is owned there; F5Bot emails real-time-dispatch to the platform
    # bot via gmail_dispatcher). Intentionally NOT scanned here (user 2026-06-17:
    # "route to vb platform, they don't belong here"). The `-from:admin@f5bot.com`
    # exclusion below keeps F5Bot out of project_mentions too.
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


def _is_cf_challenge(r: httpx.Response) -> bool:
    """True if the response is a Cloudflare Managed Challenge interstitial.

    A managed challenge (e.g. applied to /salaries/ on 2026-06-28) answers with
    HTTP 403/503 + `cf-mitigated: challenge` and a JS interstitial. A headless
    probe cannot solve it, but a real browser passes it invisibly — so a
    challenge means CF is up and gating, NOT that the origin is down. We must
    NOT treat it as a failed probe. Detect via the authoritative response
    header, with the challenge-platform body marker as a fallback.
    """
    if r.headers.get("cf-mitigated", "").strip().lower() == "challenge":
        return True
    if r.status_code in (403, 503) and "challenge-platform" in r.text:
        return True
    return False


async def _probe_one(client: httpx.AsyncClient, label: str, path: str, must_contain: list[str]) -> dict:
    url = f"{PROD_BASE_URL}{path}"
    try:
        r = await client.get(url, timeout=PROBE_TIMEOUT, follow_redirects=True)
        if _is_cf_challenge(r):
            # CF is serving + gating this surface — availability-positive, never
            # a failure. Skip body_check (markers live behind the challenge).
            return {
                "label": label, "url": url, "status": r.status_code,
                "size": len(r.content), "body_check": {},
                "challenged": True, "ok": True,
            }
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


_STAGING_PREFIX = "vb_stg_"
# Staging stack (vb_stg_*) is brought up on demand for the dual-env validation
# / DB-refresh dance — see homeserver_visa_bulletin.md. Steady state is
# "Exited (0)" (cleanly stopped). Only alarm on the prod containers; for
# staging, alarm only if a container is running-but-unhealthy or exited with
# a non-zero rc.
_CLEAN_EXIT_RE = re.compile(r"^Exited \(0\)")


def _is_unhealthy(container: dict) -> bool:
    state = container["state"].lower()
    status = container["status"]
    if container["name"].startswith(_STAGING_PREFIX):
        # Staging: only "running but unhealthy" or "exited non-zero" counts.
        if state == "running" and "unhealthy" in status.lower():
            return True
        if state == "exited" and not _CLEAN_EXIT_RE.match(status):
            return True
        return False
    # Prod: anything not cleanly running is a problem.
    return state != "running" or "unhealthy" in status.lower()


def _section_containers(rows: list[dict]) -> tuple[dict | None, str]:
    """Return (section_dict_or_None, status)."""
    if not rows:
        return ({"title": "Containers UNREACHABLE",
                 "body": "Could not enumerate vb_* containers.",
                 "importance": 5}, "red")
    down = [c for c in rows if _is_unhealthy(c)]
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
                 "body": "Expected `/opt/stack/_shared/logs/backup_visa_bulletin.log`. Daily backup may not be running.",
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


def _parse_sitemap(raw: str) -> dict:
    """Parse the sitemap section: `mtime|bytes` then a `<loc>` count, or MISSING."""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if not lines or lines[0] == "MISSING":
        return {"present": False}
    try:
        mtime_s, size_s = lines[0].split("|", 1)
        info = {
            "present": True,
            "age_hours": (time.time() - int(mtime_s)) / 3600,
            "size_kb": int(size_s) / 1024,
        }
    except (ValueError, IndexError):
        return {"present": False, "parse_error": True}
    if len(lines) > 1:
        try:
            info["urls"] = int(lines[1])
        except ValueError:
            pass
    return info


def _section_sitemap(info: dict) -> tuple[dict | None, str]:
    """Grade the pre-rendered /sitemap.xml that nginx serves off disk."""
    if not info.get("present"):
        return ({
            "title": "Pre-rendered sitemap.xml MISSING",
            "body": (
                "Expected `/opt/stack/visa_bulletin/staticfiles/sitemap.xml`. nginx falls back "
                "to the Django view, so the sitemap is still CORRECT — but crawlers are back on "
                "the ~21.7s render that pins a gunicorn worker, which is the whole problem the "
                "static file solves.\n"
                "- Fix: `ssh homeserver \"docker exec -w /app vb_web python3 -m scripts.seo.render_sitemap\"`\n"
                "- Then check the 02:40 cron is installed (`crontab -l | grep render_sitemap`)."
            ),
            "importance": 3,
        }, "yellow")

    age_hr = info["age_hours"]
    urls = info.get("urls")
    status = "green"
    if age_hr > SITEMAP_STALE_RED_HOURS:
        status = "red"
    elif age_hr > SITEMAP_STALE_YELLOW_HOURS:
        status = "yellow"

    body_lines = [
        f"- Last rendered: **{age_hr:.1f} hr ago** ({info['size_kb']:.0f} KB"
        + (f", {urls} URLs)" if urls is not None else ")")
    ]
    if urls is not None and urls < SITEMAP_MIN_PLAUSIBLE_URLS:
        status = "red"
        body_lines.append(
            f"- **Only {urls} URLs** — far below the ~6.9k expected. The renderer's own "
            "`--min-urls` gate should make this impossible, so this file was probably written "
            "with `--force` over a degraded render. Google is being told most of the site is gone."
        )
    if status == "green":
        return (None, "green")
    if age_hr > SITEMAP_STALE_YELLOW_HOURS:
        body_lines.append(
            "- The renderer refuses to publish a degraded render (DB blip → ~50 URLs), so a "
            "stale-but-good file is its SAFE failure mode. Check "
            "`/opt/stack/visa_bulletin/logs/cron/render_sitemap.log` for the refusal reason."
        )
    return ({
        "title": "Pre-rendered sitemap " + ({"red": "BROKEN", "yellow": "stale"}[status]),
        "body": "\n".join(body_lines),
        "importance": 5 if status == "red" else 3,
    }, status)


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
    # App exceptions (500) are the real signal — surface per-path and escalate on
    # absolute count even when they're a small slice of total traffic (the
    # EmptyResultSet case). Gateway 5xx (502/503/504) are worker-recycle / deploy
    # blips, NOT path-specific code bugs — fold into one total and only escalate on
    # a sustained burst (mirrors alert_5xx_spike.sh Rule 2: ≥ GW_5XX_BURST and a
    # meaningful % of traffic). Never label gateway blips a "code regression".
    if nx.get("top_500_paths"):
        lines.append("- Top 500 (app exception) paths:")
        for p, c in nx["top_500_paths"][:5]:
            mark = ""
            if c >= PATH_5XX_RED:
                status = "red"
                mark = " ⚠️ app-level 500 spike (likely a code regression)"
            elif c >= PATH_5XX_YELLOW and status != "red":
                status = "yellow"
                mark = " ⚠️"
            lines.append(f"  - `{p}` — {c}{mark}")
    gw_5xx = sum(v for k, v in nx.get("5xx_status", {}).items() if k in ("502", "503", "504"))
    if gw_5xx:
        gw_pct = (gw_5xx / total * 100) if total else 0
        burst = gw_5xx >= GW_5XX_BURST and gw_pct >= NGINX_5XX_YELLOW_PCT
        if burst and status != "red":
            status = "yellow"
        note = (
            " ⚠️ sustained — check for an upstream/deploy issue"
            if burst else " (worker-recycle / deploy blips, expected)"
        )
        lines.append(f"- Gateway 5xx (502/503/504): {gw_5xx} ({gw_pct:.2f}%){note}")
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
    # Prefer the untruncated, event-excluded CSV pageview totals. /stats/total
    # counts ad/affiliate event beacons as hits (inflated), so use it only as a
    # labelled fallback when the export was unavailable.
    pv = gc.get("pageviews") or {}
    if pv:
        pv_this = pv.get("this_7d") or 0
        pv_prev = pv.get("prev_7d") or 0
        pv_cycle = pv.get("cycle_7d") or 0
        pv_28 = pv.get("last_28d") or 0
    else:
        pv_this = gc["totals_this_week"].get("total") or 0
        pv_prev = gc["totals_prev_week"].get("total") or 0
        pv_cycle = gc["totals_cycle_ago"].get("total") or 0
        pv_28 = (gc.get("totals_last_28d") or {}).get("total") or 0
    pv_28_wk = pv_28 / 4 if pv_28 else 0
    # Primary signal: vs 4 weeks ago (one bulletin cycle, same day-of-week phase).
    delta_cycle = ((pv_this - pv_cycle) / pv_cycle * 100) if pv_cycle else None
    delta_wow = ((pv_this - pv_prev) / pv_prev * 100) if pv_prev else None
    delta_28 = ((pv_this - pv_28_wk) / pv_28_wk * 100) if pv_28_wk else None
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
        f"vs **{_humanize(pv_cycle)}** 4w ago {_fmt(delta_cycle, 'MoM cycle')} · "
        f"vs **{_humanize(pv_prev)}** last week {_fmt(delta_wow, 'WoW')} · "
        f"vs **{_humanize(pv_28_wk)}/wk** 28d-avg {_fmt(delta_28, '28d')}",
        "_Note: bulletin publishes monthly (~8th–15th) so WoW is misleading mid-cycle; MoM cycle + 28d-avg are the primary signals._",
        "",
    ]
    # Surface that the trend is full-days-only and today's partial day was
    # excluded (else the reader assumes "7d" ends today). (user 2026-06-17.)
    anchor = gc.get("anchor_last_complete_day")
    partial = gc.get("partial_day") or {}
    if anchor and partial.get("date"):
        psf = partial.get("pageviews_so_far")
        cutoff = (partial.get("cutoff_utc") or "")[:16].replace("T", " ")
        lines.insert(
            0,
            f"- _Full days only: 7d window ends **{anchor}** (last complete day). "
            f"Today {partial['date']} excluded — partial, "
            f"{_humanize(psf) if psf is not None else '?'} pageviews so far "
            f"through {cutoff} UTC._",
        )
    if not pv:
        lines.insert(0, "- ⚠️ _Export CSV unavailable — pageview total falls back "
                        "to /stats/total, which counts ad/affiliate event beacons "
                        "as hits (inflated). Per-page data unavailable this run._")

    # Combined main-entry line (user request 2026-05-27): home + EB + FS
    # dashboards are one funnel. We additionally break out the IND-EB-vs-
    # rest-of-EB split and flag if non-IND-EB approaches IND-EB+home — the
    # homepage today serves India-EB by default, so if other countries
    # become comparable, the homepage default needs revisiting.
    me = gc.get("main_entry") or {}
    csv_st = gc.get("csv_status", "missing")
    if me.get("this_7d"):
        this7 = me["this_7d"]
        cyc7 = me.get("cycle_7d") or {}
        prev7 = me.get("prev_7d") or {}
        last28 = me.get("last_28d") or {}

        def _v(d: dict, k: str) -> int:
            return int(d.get(k) or 0)

        def _delta(cur: float, base: float, label: str) -> str:
            if not base:
                return f"(no {label} baseline)"
            return _fmt((cur - base) / base * 100, label)

        all_this = _v(this7, "all")
        all_cyc = _v(cyc7, "all")
        all_prev = _v(prev7, "all")
        all_28 = _v(last28, "all")
        all_28_wk = all_28 / 4 if all_28 else 0

        lines.append(
            f"- **Main entry (home + EB + FS dashboards): {_humanize(all_this)} 7d** · "
            f"vs **{_humanize(all_cyc)}** 4w ago {_delta(all_this, all_cyc, 'MoM')} · "
            f"vs **{_humanize(all_prev)}** last week {_delta(all_this, all_prev, 'WoW')} · "
            f"vs **{_humanize(all_28_wk)}/wk** 28d-avg {_delta(all_this, all_28_wk, '28d')}"
        )

        home_pv = _v(this7, "home")
        ind_pv = _v(this7, "eb_india")
        nonind_pv = _v(this7, "eb_other")
        fs_pv = _v(this7, "fs")
        # Homepage today serves the India-EB dashboard, so combine home + eb_india
        # for the IND side of the watchpoint ratio.
        ind_side = home_pv + ind_pv
        ratio = (nonind_pv / ind_side) if ind_side else None
        flag = ""
        if ratio is not None:
            if ratio >= MAIN_ENTRY_NONIND_EB_RATIO_RED:
                flag = "  🔴 **adjust homepage** — non-IND-EB ≥70% of IND-EB+home"
                if status != "red":
                    status = "red"
            elif ratio >= MAIN_ENTRY_NONIND_EB_RATIO_YELLOW:
                flag = "  🟡 watch — non-IND-EB ≥50% of IND-EB+home"
                if status == "green":
                    status = "yellow"
        lines.append(
            f"  - Breakdown 7d: `/` **{_humanize(home_pv)}** · "
            f"`/employment-based/india/` **{_humanize(ind_pv)}** · "
            f"other EB **{_humanize(nonind_pv)}** · "
            f"FS **{_humanize(fs_pv)}**"
            + (f" · non-IND-EB / (IND-EB+home) = {ratio*100:.0f}%" if ratio is not None else "")
            + flag
        )
        if csv_st == "stale":
            age_s = gc.get("csv_age_s")
            age_h = (age_s / 3600) if age_s else None
            lines.append(
                f"  _CSV cache ~{age_h:.0f}h old (TTL {GC_EXPORT_CACHE_TTL_S//3600}h) — "
                f"fresh export rate-limited; counts may lag a few hours._"
                if age_h is not None
                else "  _CSV cache stale; fresh export rate-limited._"
            )
    else:
        lines.append(
            "- _Main-entry combined line unavailable: GC `/api/v0/export` "
            "not yet cached (1/hr rate limit). Will populate on the next "
            "successful export — usually within one daily-checkup cycle._"
        )

    # Per-surface counts moved to "Per-property dashboard" section (which
    # joins GC + GSC + nginx-perf per route). Keep only the top-mover list
    # here — same-path absolute swings, useful as the "what changed most"
    # row that doesn't fit a fixed surface taxonomy.
    if gc["top_movers"]:
        lines.append("")
        lines.append("**Top movers vs 4 weeks ago (absolute change):**")
        for m in gc["top_movers"][:6]:
            lines.append(
                f"- `{m['path']}`: {_humanize(m['this_week'])} vs "
                f"{_humanize(m['cycle_ago'])} {_fmt(m['delta_pct'], 'MoM')}"
            )
    importance = {"red": 5, "yellow": 4, "green": 3}[status]
    return ({"title": "Traffic (GoatCounter, 7d vs 4 weeks ago)", "body": "\n".join(lines), "importance": importance}, status)


# Thresholds for the per-surface performance signal. Yellow: any one surface
# has >=PERF_YELLOW_N3 page hits taking >3s in 24h. Red: same with >10s.
PERF_YELLOW_N3 = 50
PERF_RED_N10 = 5

# Surfaces that render heavy server-side Plotly (the predictions backtest):
# a >10s cold tail is routine there, NOT a regression — it's the known heavy
# render the cache-warmer ticket tracks, and at PERF_RED_N10=5 it tripped the
# whole digest RED essentially every day (~14 >10s/24h is normal). Don't let it
# escalate past YELLOW; only warn on a genuine spike well above the routine
# tail. Every transactional surface (dashboard/salaries/profiles), where >10s
# IS a real regression, keeps the strict PERF_RED_N10 default.
PERF_HEAVY_SURFACES = {"predictions"}
PERF_HEAVY_SPIKE_N10 = 30

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
    "priority_date",
    "occupation_salary",
    "h1b_sponsors",
    "spanish",
    "blog",
    "static_pages",
]
# NOT rendered in the per-property block (removed 2026-06-29, user request):
#   - worksites: live `/worksites/` route but ~0 traffic (6 hits/6mo) — a dead
#     row. Still classified by SURFACE_PATTERNS so it never pollutes `other`.
#   - donation_click: the CSV aggregator filters OUT events (Event!=0), and the
#     ext-* donation clicks ARE events, so this bucket is structurally always
#     empty on the CSV path → a permanent "no data" row. The donation buttons
#     still exist on prod; monetization reporting lives in the platform digest.
#     Pattern kept for the top-100 `/stats/hits` fallback (where ext-* appear as
#     pseudo-paths and must stay out of `other`).


def _section_top_properties(
    nx: dict, gc: dict | None
) -> tuple[dict | None, str]:
    """Per-surface joined view: popularity (GC, all 4 windows) + performance
    (origin nginx 24h). One row per surface, multi-line so phone-readable.

    (SEO/GSC per-surface column retired 2026-06-26 — GSC reporting moved to the
    visa_bulletin_platform digest; marketing is owned by the platform overlay,
    see daily_checkup.md.)
    """
    lat: dict = nx.get("surface_latency") or {}
    gc_by_surface: dict[str, dict] = {}
    if gc:
        for s in gc.get("surfaces") or []:
            gc_by_surface[s["surface"]] = s

    if not lat and not gc_by_surface:
        return (None, "green")

    status = "green"
    for surf in TOP_PROPERTY_SURFACES:
        lat_row = lat.get(surf)
        n3 = lat_row["n_over_3s"] if lat_row else 0
        n10 = lat_row["n_over_10s"] if lat_row else 0
        if surf in PERF_HEAVY_SURFACES:
            # Known-heavy Plotly render — routine slow tail is not a regression.
            # Never RED; only warn (yellow) on a genuine spike. The per-property
            # block below still shows the raw >10s count, so it's not hidden.
            if n10 >= PERF_HEAVY_SPIKE_N10 and status == "green":
                status = "yellow"
            continue
        if n10 >= PERF_RED_N10:
            status = "red"
        elif n3 >= PERF_YELLOW_N3 and status == "green":
            status = "yellow"

    # Sort by GC 7d traffic desc; fallback to nginx 24h count, then 0.
    def _sort_key(surf: str) -> int:
        gc_row = gc_by_surface.get(surf)
        if gc_row:
            return -int(gc_row.get("this_week") or 0)
        lat_row = lat.get(surf)
        if lat_row:
            return -int(lat_row.get("count") or 0)
        return 0
    ordered_surfaces = sorted(TOP_PROPERTY_SURFACES, key=_sort_key)

    surfaces_source = (gc or {}).get("surfaces_source", "top100_hits")
    source_blurb = (
        "GC 7d/prev/MoM/28d = full path coverage via /api/v0/export (100% of pageviews). "
        if surfaces_source == "csv_full"
        else "GC 7d/MoM = top-100 paths from /stats/hits (long tail not visible until next CSV export lands). "
    )
    lines = [
        f"_{source_blurb}Perf = origin nginx 24h, real pages (incl. bots)._",
        "",
    ]
    for surf in ordered_surfaces:
        block = _format_property_block(
            surf=surf,
            gc_row=gc_by_surface.get(surf),
            lat_row=lat.get(surf),
        )
        lines.extend(block)

    title_suffix = {"red": " — CRITICAL (slow tail)", "yellow": " — slow tail", "green": ""}[status]
    importance = {"red": 5, "yellow": 4, "green": 3}[status]
    return (
        {
            "title": f"Per-property dashboard{title_suffix}",
            "body": "\n".join(lines),
            "importance": importance,
        },
        status,
    )


def _fmt_pct_signed(d: float | None, label: str) -> str:
    if d is None:
        return f"(no {label})"
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.0f}% {label}"


def _format_property_block(
    *,
    surf: str,
    gc_row: dict | None,
    lat_row: dict | None,
) -> list[str]:
    """Multi-line block for one property in the per-property dashboard.

    Layout per surface:
      - **<label>**
          GC: <7d> · MoM · WoW · 28d-avg
          Perf: mean Xms over N hits 24h (n1>1s · n3>3s · n10>10s)
    Each sub-line is omitted (replaced with a one-word marker) when the
    source has no data — better to see the gap than to hide it.
    """
    label = SURFACE_LABELS.get(surf, surf)
    lines = [f"- **{label}**"]

    # GoatCounter — volume + cycle/WoW/28d deltas
    if gc_row:
        cur = int(gc_row.get("this_week") or 0)
        cyc = int(gc_row.get("cycle_ago") or 0)
        prev = gc_row.get("prev_week")
        l28_wk = gc_row.get("last28_per_week")
        delta_mom = gc_row.get("delta_pct")
        delta_wow = ((cur - prev) / prev * 100) if prev else None
        delta_28 = ((cur - l28_wk) / l28_wk * 100) if l28_wk else None
        bits = [
            f"**{_humanize(cur)}** views 7d",
            f"vs {_humanize(cyc)} 4w ago {_fmt_pct_signed(delta_mom, 'MoM')}",
        ]
        if prev is not None:
            bits.append(f"vs {_humanize(prev)} last wk {_fmt_pct_signed(delta_wow, 'WoW')}")
        if l28_wk:
            bits.append(f"vs {_humanize(l28_wk)}/wk 28d-avg {_fmt_pct_signed(delta_28, '28d')}")
        lines.append(f"  GC: {' · '.join(bits)}")
    else:
        lines.append("  GC: no data")

    # Performance — mean latency + slow-tail
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
        perf_bit = f"mean **{mean_ms}ms** over {_humanize(cnt)} hits 24h ({tail})"
        if not gc_row and cnt > 1000:
            perf_bit += " ⚠️ **anomaly: nginx traffic but invisible to GC**"
        lines.append(f"  Perf: {perf_bit}")
    else:
        lines.append("  Perf: no nginx traffic 24h")

    return lines




def _section_probes(probes: list[dict]) -> tuple[dict | None, str]:
    failed = [p for p in probes if not p.get("ok")]
    if not failed:
        challenged = [p for p in probes if p.get("challenged")]
        if challenged:
            # Informational only — a CF Managed Challenge is expected + healthy.
            names = ", ".join(p["label"] for p in challenged)
            return ({"title": "Probes OK (CF challenge on: " + names + ")",
                     "body": ("Behind Cloudflare Managed Challenge (expected — "
                              "real browsers pass invisibly). Not a failure."),
                     "importance": 1}, "green")
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
        "_Uptime alerts + project mentions. (F5Bot / Reddit-mention triage lives "
        "in visa_bulletin_platform now, not here.)_\n\n"
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


# --- DOL data-freshness check (manual weekly-refresh trigger signal) ---
# The weekly DOL salary refresh runs manually (see branching.md Path 2 + the
# weekly-refresh ticket). This surfaces when DOL has published an LCA/PERM
# disclosure file newer than prod has ingested, so the refresh can be triggered.
DOL_PERFORMANCE_URL = "https://www.dol.gov/agencies/eta/foreign-labor/performance"


def _dol_disclosure_tuples(text: str) -> set[tuple[str, int, int]]:
    """Extract (program, fiscal_year, quarter) for LCA/PERM *disclosure* files.

    Works on both the DOL HTML page and a newline list of ingested URLs. Excludes
    worksite / appendix / prevailing-wage files (separate datasets). quarter=0 =
    an annual (no-quarter) file. Tolerant of DOL's misspelled 'dislclosure' names.
    """
    out: set[tuple[str, int, int]] = set()
    for fname in re.findall(r"([^\"'/>]*\.(?:xlsx|csv))", text, re.IGNORECASE):
        f = fname.lower()
        if "lca" not in f and "perm" not in f:
            continue
        if any(x in f for x in ("worksite", "appendix", "pw_", "prevailing")):
            continue
        fy = re.search(r"fy(\d{4})", f)
        if not fy:
            continue
        q = re.search(r"q([1-4])", f)
        program = "PERM" if "perm" in f else "H1B"
        out.add((program, int(fy.group(1)), int(q.group(1)) if q else 0))
    return out


def _dol_rank(t: tuple[str, int, int]) -> int:
    """Rank (fy, quarter) for 'latest' comparison; annual (q=0) == full year (Q4)."""
    return t[1] * 10 + (t[2] if t[2] else 4)


def _dol_label(t: tuple[str, int, int] | None) -> str:
    if not t:
        return "none"
    return f"FY{t[1]}" + (f" Q{t[2]}" if t[2] else " (annual)")


async def _gather_data_freshness() -> dict | None:
    """Fetch the DOL performance page; return the latest disclosure file per
    program as {'H1B': tuple|None, 'PERM': tuple|None}, or None on failure.

    NOTE: DOL anti-bot 403s browser User-Agents but allows the default httpx UA —
    do NOT set a browser User-Agent here.
    """
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        r = await client.get(DOL_PERFORMANCE_URL)
        r.raise_for_status()
        up = _dol_disclosure_tuples(r.text)
    return {p: max([t for t in up if t[0] == p], key=_dol_rank, default=None) for p in ("H1B", "PERM")}


def _section_data_freshness(upstream: dict | None, prod_dol_text: str) -> tuple[dict, str]:
    """Compare upstream DOL disclosure availability vs prod's ingested sources.

    yellow when DOL has published an LCA/PERM disclosure file newer than prod has
    ingested (trigger the manual weekly refresh); green when current.
    """
    prod = _dol_disclosure_tuples(prod_dol_text or "")
    prod_latest = {
        p: max([t for t in prod if t[0] == p], key=_dol_rank, default=None)
        for p in ("H1B", "PERM")
    }

    if upstream is None:
        body = (
            "Could not reach the DOL performance page (transient). Prod ingested: "
            + ", ".join(f"{p} {_dol_label(prod_latest[p])}" for p in ("H1B", "PERM"))
        )
        return ({"title": "DOL data freshness", "body": body, "importance": 1}, "green")

    lines: list[str] = []
    new_count = 0
    for prog, label in (("H1B", "H-1B (LCA)"), ("PERM", "PERM")):
        up_t, pr_t = upstream.get(prog), prod_latest.get(prog)
        if up_t and pr_t and _dol_rank(up_t) > _dol_rank(pr_t):
            new_count += 1
            lines.append(
                f"- 🆕 **{label}**: DOL has {_dol_label(up_t)}, prod has {_dol_label(pr_t)}"
            )
        elif up_t and pr_t:
            lines.append(f"- {label}: current ({_dol_label(pr_t)})")
        else:
            lines.append(f"- {label}: DOL {_dol_label(up_t)}, prod {_dol_label(pr_t)}")

    if new_count:
        body = (
            "New DOL disclosure data is available — the manual weekly refresh can "
            "be triggered (branching.md Path 2 / weekly-refresh ticket).\n"
            + "\n".join(lines)
        )
        return (
            {"title": f"DOL data freshness — {new_count} new file(s) available",
             "body": body, "importance": 4},
            "yellow",
        )
    body = "Prod is up to date with DOL disclosure data.\n" + "\n".join(lines)
    return ({"title": "DOL data freshness — current", "body": body, "importance": 2}, "green")


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

    # ALL gathers run CONCURRENTLY, including the SSH homeserver snapshot. The
    # snapshot used to run SERIALLY before the others (up to 60s of the heavy
    # nginx-log awk) — so at the traffic levels since ~2026-07-07 the serial
    # SSH + parallel gathers + cold-uv spawn no longer fit the aggregator's
    # 120s budget, and the first 7am run timed out 3 days straight (07-07/08/09;
    # a manual retry recovered). The snapshot has no data dependency on the
    # others, so folding it into the gather makes wall-clock ≈ max(snapshot,
    # slowest gather) instead of snapshot + slowest gather. On failure it
    # returns None + records the error; the UNREACHABLE section is built after.
    snap_err: str | None = None

    async def _safe_snapshot():
        nonlocal snap_err
        try:
            return await asyncio.to_thread(_gather_homeserver_snapshot)
        except Exception as e:
            logger.exception("homeserver snapshot failed")
            snap_err = f"{type(e).__name__}: {e}"
            errors.append(f"homeserver: {snap_err}")
            return None

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

    async def _safe_freshness():
        try:
            return await _gather_data_freshness()
        except Exception as e:
            logger.exception("data freshness gather failed")
            errors.append(f"data_freshness: {type(e).__name__}: {e}")
            return None

    async def _safe_ga4():
        try:
            return await _gather_ga4_engagement()
        except Exception as e:
            logger.exception("ga4 engagement gather failed")
            errors.append(f"ga4_engagement: {type(e).__name__}: {e}")
            return None

    snap, gc_data, probe_data, gmail_data, freshness_data, ga4_data = await asyncio.gather(
        _safe_snapshot(), _safe_gc(), _safe_probes(), _safe_gmail(),
        _safe_freshness(), _safe_ga4()
    )

    # Homeserver-unreachable section (deferred from the gather so all gathers
    # run concurrently). Only when the snapshot genuinely errored — a None from
    # any other cause is not an SSH failure.
    if snap is None and snap_err is not None:
        sections.append({
            "title": "Homeserver UNREACHABLE",
            "body": f"SSH to `{SSH_ALIAS}` failed: {snap_err}",
            "importance": 5,
        })
        statuses.append("red")

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
        s, st = _section_bulletin_refresh(
            _parse_log_age(snap.get("bulletin_refresh", ""),
                           latest_run_marker="=== Visa Bulletin Refresh ===")
        )
        if s:
            sections.append(s)
        statuses.append(st)
        # Backup cron
        s, st = _section_backup(_parse_log_age(snap.get("backup", "")))
        if s:
            sections.append(s)
        statuses.append(st)
        # Pre-rendered sitemap.xml (nginx serves it off disk; cron 02:40)
        s, st = _section_sitemap(_parse_sitemap(snap.get("sitemap", "")))
        if s:
            sections.append(s)
        statuses.append(st)
        # Postgres
        s, st = _section_postgres(_parse_postgres(snap.get("postgres", "")))
        if s:
            sections.append(s)
        statuses.append(st)
        # DOL data freshness — is a new LCA/PERM disclosure file available to
        # trigger the manual weekly refresh? (upstream fetch from the gather +
        # prod ingested sources from the snapshot.)
        s, st = _section_data_freshness(freshness_data, snap.get("dol_sources", ""))
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

    # GoatCounter section (totals + main-entry + top movers; per-surface
    # detail lives in the Per-property dashboard below).
    if gc_data is not None:
        s, st = _section_goatcounter(gc_data)
        sections.append(s)
        statuses.append(st)

    # GA4 engagement (long-click proxy) — organic landings per watched surface.
    if ga4_data is not None:
        s, st = _section_ga4_engagement(ga4_data)
        sections.append(s)
        statuses.append(st)

    # Per-property dashboard: GC volume + nginx latency, one block per route.
    # Needs at least one of the two. (GSC/SEO moved to the platform digest.)
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
        # Use the untruncated, event-excluded CSV pageview totals — NOT
        # /stats/total (which counts ad/affiliate event beacons as hits).
        pv_map = gc_data.get("pageviews") or {}
        if pv_map:
            pv = pv_map.get("this_7d") or 0
            pv_cycle = pv_map.get("cycle_7d") or 0
        else:
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
