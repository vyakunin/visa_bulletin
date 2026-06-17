# visa_bulletin daily checkup MCP server

Implements the contract at `~/.cursor/shared_rules/daily_checkup.mdc`. Exposes a single `daily_checkup(since)` MCP tool returning a JSON `CheckupReport`.

## Signals

### Operational health (one SSH round-trip to the homeserver)
- `vb_*` container state — flags any non-`running` or `unhealthy`.
- Host disk / memory / CPU load (per-core).
- Hourly bulletin-refresh cron freshness + filtered error lines from `/opt/stack/visa_bulletin/logs/cron/bulletin_refresh.log` (known-harmless 200X / 2015 source noise per POST_MIGRATION_TRACKER #8 is suppressed).
- Daily GDrive-backup cron freshness + errors from `/opt/stack/visa_bulletin/logs/cron/backup.log`.
- Postgres data freshness: newest `Bulletin.publication_date` (handles future-month case), last successful `IngestRun.completed_at`, connection count.
- `vb_cloudflared` state + restart count.

### Traffic / performance (GoatCounter API)
- Pageviews for the last 7 days vs:
  - **Same 7-day window 28 days ago** (primary signal — bulletin cycle is monthly, so this compares the same phase).
  - Previous week (secondary, WoW — useful intra-cycle only, since bulletin drops between the 8th–15th).
- Top-100 paths bucketed by surface: `homepage`, `job_title_profile`, `job_title_directory`, `employer_profile`, `employer_directory`, `employer_rankings`, `predictions`, `blog` (`/analysis/`), `salaries`, `worksites`, SEO landings (`/employment-based/`, `/family-sponsored/`), `api`, `static_meta`, `other`.
- Per-surface MoM-cycle delta + top-10 path movers.
- Caveats:
  - GoatCounter API caps at top-100 paths; long-tail invisible without a full export.
  - GoatCounter no longer exposes unique visitors as a distinct metric (privacy update; `count_unique` always equals `count`). For a real "unique humans" proxy we use unique CF-Connecting-IP from nginx (below).

### Security + traffic (origin nginx, 24h)
- Status-code mix (2xx/3xx/4xx/5xx), 5xx percentage.
- Real-page hits broken down human vs bot (UA heuristic).
- **Unique IPs hitting real pages in 24h** — total + human-only — our visitor proxy (since GoatCounter doesn't expose uniques).
- Top 5xx and 4xx paths.
- Top client IPs (real, via `CF-Connecting-IP` — RFC 1918 private ranges are filtered out).
- Bot/scraper user-agent hit count.
- Scanner-path probes (`/wp-admin`, `/.env`, `/phpmyadmin`, etc.) with per-path counts.
- nginx 429 (rate-limited) count.

> Real-IP setup: the `vb_nginx` config has `set_real_ip_from 172.18.0.0/16` + `real_ip_header CF-Connecting-IP`, so `$remote_addr` is the actual client. Wired 2026-05-14 by the daily-checkup work. Pre-fix, `$remote_addr` was always `172.18.0.6` (cloudflared's docker IP), which made per-IP rate limits and log-based traffic analysis useless. The change also makes the existing `bot_per_subnet` rate-limit zone work correctly.

### Gmail signals (24h)
- F5Bot Reddit-mention alerts (per POST_MIGRATION_TRACKER P1: triage daily).
- Uptime-monitor alerts (UptimeRobot/Pingdom/StatusCake/BetterStack/HetrixTools/Site24x7/Cronitor/Healthchecks) — currently no monitor is wired, but query is in place so it lights up the moment one is.
- Other project mentions: `visa-bulletin.us` / `"visa bulletin"` / `subject:visa-bulletin` (user feedback, Google Search Console alerts, GHCR build failures, etc.).

Uses the `google_workspace` MCP as a sub-client; subjects are batch-fetched for the top hits.

### Availability
- External HTTPS probes of `/`, `/job-titles/`, `/employers/`, `/predictions/`, `/analysis/`, `/salaries/` — flags any non-200, and confirms the GoatCounter beacon is still in the homepage HTML.

## Setup

1. **GoatCounter API token** — save at `~/tokens/goatcounter.token` (mode 600). Generate via Settings → API in the GoatCounter dashboard. See `docs/deployment/goatcounter.md`.
2. **SSH alias** — configure a `homeserver` alias for the production server in
   `~/.ssh/config` (concrete host, user, and key live in the private ops repo):
   ```
   Host homeserver
       HostName <prod-host>
       User <user>
       IdentityFile <key>
   ```
   Or override with `HOMESERVER_SSH_ALIAS=<your-alias>`.
3. **google_workspace MCP** — must be registered in `~/mcp/servers.json` and OAuth'd to your Gmail account. The server reads credentials from `~/tokens/google/`.
4. **Install deps** (one-off): `cd mcp && uv sync` — first run via the orchestrator does this automatically.

## Register with the orchestrator

Already added to `~/cursor_projects/personal_projects/daily_checkup/registry.yaml`:

```yaml
  - name: visa_bulletin
    enabled: true
    cwd: /Users/vyakunin/cursor_projects/visa_bulletin/mcp
    command: ["uv", "run", "python", "daily_checkup_server.py"]
    timeout_seconds: 60
    env: {}
```

## Manual test

```bash
cd mcp
uv run python -c '
import asyncio, json
from daily_checkup_server import daily_checkup
print(json.dumps(json.loads(asyncio.run(daily_checkup())), indent=2))'
```

## Tuning

Thresholds are constants at the top of `daily_checkup_server.py`:

| Constant | Default | What it controls |
|---|---|---|
| `DISK_YELLOW_PCT` / `_RED_PCT` | 70 / 85 | Production SSD (small) |
| `MEM_YELLOW_PCT` / `_RED_PCT` | 80 / 92 | Homeserver RAM (8 GB) |
| `CPU_LOAD_YELLOW` / `_RED` | 1.0 / 2.0 | load1 ÷ nproc |
| `BULLETIN_REFRESH_YELLOW_MIN` / `_RED_MIN` | 90 / 180 | Hourly cron staleness |
| `BACKUP_YELLOW_HOURS` / `_RED_HOURS` | 30 / 50 | Daily backup staleness |
| `BULLETIN_DATA_STALE_DAYS_YELLOW` / `_RED` | 35 / 50 | Newest bulletin age |
| `NGINX_5XX_YELLOW_PCT` / `_RED_PCT` | 0.5 / 2.0 | 5xx as % of 24h traffic |
| `SCRAPER_IP_YELLOW` / `_RED` | 2 000 / 10 000 | Single real-client IP hits / 24h |
| `TRAFFIC_DROP_YELLOW_PCT` / `_RED_PCT` | -30 / -60 | MoM cycle pageview delta |
