# visa_bulletin — mini-PC warm standby for homeserver downtime

> Companion to `RUNBOOK.md` (the AWS-Lightsail cold-DR). This file covers using the
> **Dell OptiPlex 3080 mini-PC** (always-on at home, same LAN as the homeserver) as a
> **warm standby** that keeps visa-bulletin.us serving when the homeserver is down —
> ideally with **no DNS flip and ~zero RTO**, by leveraging Cloudflare Tunnel HA.

## Why this beats the Lightsail cold-DR for "homeserver downtime"

- The mini-PC is already on, on the LAN, costs nothing per failover, and recovers in
  seconds (warm) vs ~10–15 min (Lightsail snapshot boot).
- The hard part of any home failover — **public reachability without a static/public
  IP** (the whole reason prod uses a Cloudflare Tunnel, not port-forwards) — is solved
  *for free* by running a **second cloudflared connector on the same tunnel**.
- visa_bulletin is effectively read-only for users (the only write is the hourly
  bulletin cron, which both hosts can run independently against the same DOL source).
  So two origins serving slightly-independent-but-equivalent DBs is fine.

## Architecture: tunnel-HA warm standby (recommended)

Cloudflare Tunnel supports **multiple cloudflared replicas per tunnel** for HA. Run a
second connector on the mini-PC, pointing at the mini-PC's *own* local nginx→web→pg
stack:

```
                         ┌── homeserver cloudflared ── vb_nginx ── vb_web ── vb_postgres (prod)
User → CF edge ── tunnel ─┤
   (visa-bulletin.us)     └── mini-PC  cloudflared ── vb_nginx ── vb_web ── vb_postgres (standby)
```

- Both connectors register on the SAME tunnel (`ec57186d-7e4e-40f3-ba67-ec9a2ed28db4`,
  token in `~/tokens/cloudflare_tunnel_homeserver`). CF load-balances/fails-over
  between healthy connectors automatically.
- **No DNS change ever needed.** The apex/www CNAMEs stay pointed at
  `<tunnel-id>.cfargotunnel.com`. If the homeserver dies, its connector drops and CF
  routes 100% to the mini-PC.
- Each connector serves from its OWN local stack, so the mini-PC must keep a recent DB
  + the current image running.

> **Caveat to validate first:** with both connectors advertising the same ingress, CF
> may *load-balance* requests across both during normal operation (active-active), not
> just on failover. For visa_bulletin (read-heavy, cache-fronted) that's acceptable and
> even desirable. If you want strict active-passive, either keep the mini-PC connector
> stopped until needed (`systemctl --user stop vb-cloudflared`; lose the auto-failover,
> gain control) or use a CF Load Balancer with origin priorities (paid add-on). Start
> with active-active; it's simplest and correct for this workload.

## One-time setup on the mini-PC

Assumes the mini-PC is already running Ubuntu 24.04 + Docker (see
`agent_infra/docs/MIGRATE_AGENTS_MANAGER_TO_MINIPC.md` Phase 0). Same box can host both.

1. **Install Docker + compose** if not present:
   `sudo apt install -y docker.io docker-compose-v2 && sudo usermod -aG docker vyakunin`.
2. **Copy the deployment config** to `/opt/stack/visa_bulletin/` (this is the source of
   truth, version-tracked under `visa_bulletin/deployment/homeserver/`):
   ```
   docker-compose.yml      nginx/visa_bulletin.conf   nginx/rate-limit.conf
   scripts/backup_to_gdrive.sh   crontab.sample
   ```
   These match the homeserver exactly. The non-secret bits are in git; copy from the
   repo, not from the (possibly-dead) homeserver SSD.
3. **Create `.env`** (NOT in git — populate from `.env.example` + `~/tokens`):
   - `DB_PASSWORD`, `DJANGO_SECRET_KEY` — must MATCH the homeserver's (so the restored
     DB + sessions are consistent). Copy from the homeserver `.env` while it's alive,
     or store a copy in `~/tokens/`.
   - `CF_TUNNEL_TOKEN` = `$(cat ~/tokens/cloudflare_tunnel_homeserver)` — the SAME
     tunnel token as the homeserver (this is what makes it a second replica).
   - `IMAGE_TAG=latest`, `WEB_CONCURRENCY=3`, `ALLOWED_HOSTS`, `ANALYTICS_SCRIPT`.
   - `chmod 600 .env`.
4. **Pull the image** (no rebuild — GitHub Actions already published it):
   `docker pull ghcr.io/vyakunin/visa_bulletin:latest`
   (login first if needed: `echo $(cat ~/tokens/fv_vps_ghcr_pat) | docker login ghcr.io -u vyakunin --password-stdin` — or a ghcr-scoped PAT).
5. **Seed the standby DB** from the latest off-box backup:
   ```bash
   rclone copy gdrive:_backups/visa_bulletin/daily/$(rclone lsf gdrive:_backups/visa_bulletin/daily/ | sort | tail -1) /tmp/
   docker compose up -d postgres && sleep 30   # wait for healthcheck
   zcat /tmp/visa_bulletin_*.sql.gz | docker exec -i vb_postgres psql -U visa_bulletin_user visa_bulletin
   ```
6. **Bring the stack up:** `docker compose up -d` (postgres, redis, web, nginx,
   cloudflared). The cloudflared container registers as the 2nd tunnel replica.
7. **Verify the standby is serving:**
   - `docker exec vb_postgres pg_isready -U visa_bulletin_user -d visa_bulletin`
   - LAN check (bypasses CF): `curl -sI http://agenthost.local:8080/` → 200
   - Edge check: in the CF Zero Trust dashboard → Networks → Tunnels →
     the homeserver tunnel should now show **2 connectors** (homeserver + mini-PC).
8. **Keep the standby DB fresh** — install on the mini-PC (`crontab.sample`):
   - daily 01:30 UTC: re-restore the latest GDrive backup (offset 30 min after the
     homeserver's 01:00 backup so it pulls a fresh dump), OR
   - hourly bulletin cron (same `refresh_bulletin` as prod) so the standby tracks
     bulletins independently. Pick one; the hourly cron keeps it within an hour.

## Failure scenarios

### A. Homeserver down, standby healthy (the design case)
**Nothing to do.** The homeserver's connector drops from the tunnel; CF routes all
traffic to the mini-PC connector. Confirm with `curl -sI https://visa-bulletin.us/`
(200) and the CF tunnel showing 1 connector. Data is at most ~1 h stale (hourly cron)
or ~24 h (daily-restore option). When the homeserver returns, its connector
re-registers and CF resumes balancing — again **no action**.

### B. You want strict active-passive (standby idle until needed)
Keep `vb-cloudflared` on the mini-PC stopped in steady state. On homeserver death:
`docker compose start cloudflared` (or `systemctl --user start vb-cloudflared`). ~5 s
to register. Stop it again after the homeserver recovers.

### C. Mini-PC AND homeserver both down
Fall back to the **Lightsail cold-DR** (`./failover.sh`, see `RUNBOOK.md`). The two
strategies stack: warm standby for the common case, Lightsail for the catastrophic one.

## What this requires that you must maintain

| Item | Why | Upkeep |
|---|---|---|
| Same `CF_TUNNEL_TOKEN` on both hosts | makes the mini-PC a 2nd replica of the prod tunnel | copy once; rotate together |
| Same `DB_PASSWORD` + `DJANGO_SECRET_KEY` | restored DB + Django sessions must match | keep a copy in `~/tokens/` |
| Standby image current | serve the same app version | `docker pull` on each prod deploy (or a cron `docker compose pull web && up -d web`) |
| Standby DB fresh | avoid serving stale data | daily restore or hourly bulletin cron (above) |
| Config in git (already true) | survive homeserver SSD death | `deployment/homeserver/` is version-tracked; `.env` secrets kept in `~/tokens/` |

## Gaps (shared with the existing RUNBOOK)

- **No alerting.** Add UptimeRobot/Healthchecks on `https://visa-bulletin.us/` so you
  *know* when the homeserver dropped (even though failover is automatic, you want to
  know you're running on the standby). High priority — same gap the Lightsail RUNBOOK flags.
- **Tunnel-HA active-active behavior** must be validated against the live tunnel config
  before trusting it (does CF balance or only fail over? does the ingress route cleanly
  to two origins?). Test: bring the mini-PC connector up, watch CF tunnel show 2
  connectors, stop the homeserver's `vb_cloudflared`, confirm the site stays up.
- **Image registry dependency** (ghcr.io) — pre-pulled on the mini-PC, so a registry
  outage doesn't block failover as long as the cached image is current.

## Quick reference

```bash
# Is the standby registered on the tunnel? (run on mini-PC)
docker logs vb_cloudflared 2>&1 | grep -i "registered\|connection"
# Standby serving on LAN?
curl -sI http://agenthost.local:8080/ | head -1
# Current public origin count (CF dashboard → Tunnels → connectors), or:
curl -sI https://visa-bulletin.us/ | head -1   # should be 200 regardless of which origin
# Refresh standby DB now:
rclone copy gdrive:_backups/visa_bulletin/daily/$(rclone lsf gdrive:_backups/visa_bulletin/daily/|sort|tail -1) /tmp/ \
  && zcat /tmp/visa_bulletin_*.sql.gz | docker exec -i vb_postgres psql -U visa_bulletin_user visa_bulletin
```
