# Post-Migration Tracker

> **Created 2026-05-09** as the single source of truth for follow-up tasks after the Lightsail → homeserver migration on 2026-05-08.
>
> Older planning docs (`HARDENING_PLAN.md`, `INSTANCE_ROTATION.md`, `DEPLOYMENT_ZERO_DOWNTIME.md`, etc.) describe the pre-migration Lightsail world and are **mostly obsolete**. They're kept for git history but should not be treated as active. New tasks belong here.

---

## P0 — Active risks / blocks (do soon)

### 1. ~~Lightsail decommission~~ — DONE 2026-05-09

- ✅ Snapshot `vb-prod-snapshot-2026-05-09` created (60 GB, state: available)
- ✅ All 3 instances deleted (`VisaBulletin2GB`, `VisaBulletinStaging`, `visa-bulletin-prod`)
- ✅ All 3 static IPs released (`VisaBulletin-StaticIP`, `visa-bulletin`, `VisaBulletinStaging-ip`)
- ✅ DR scripts updated for snapshot-based recovery (`failover.sh` now creates a fresh instance from snapshot, allocates IP, restores latest GDrive backup, flips DNS — total ~10–15 min). `failback.sh` deletes the DR instance + releases IP after recovery so billing stops immediately.
- ✅ DR preflight passes against the new clean state.
- **Final monthly cost:** ~$1 for the snapshot (60 GB compressed). Down from ~$25–30/month before. Domain `vyakunin.org` still in Lightsail DNS (free for first 3 zones, untouched, unrelated to visa_bulletin).
- **AWS IAM user `visa-bulletin-deploy`** still exists; safe to keep as long as we may need DR. Can revoke if Lightsail stops being part of the DR plan.

### 2. Postgres backup automation — IMPLEMENTED, needs first-cron verification

- **State (2026-05-09):** rclone configured on homeserver pointing at user's Google Drive (gdrive remote). Backup script at `/opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh`. Cron entry installed: `0 1 * * * /opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh ...` (1 AM UTC = 3 AM Berlin). One manual test run uploaded a 317 MB dump successfully — visible in Drive at `/visa_bulletin_backups/daily/`.
- **Retention:** 7 daily, 4 weekly (Sundays), 3 monthly (1st of month). Total ~14 files at ~317 MB each = ~4.4 GB on Drive.
- **Verify after first scheduled run** (next 1 AM UTC): check `/opt/stack/visa_bulletin/logs/cron/backup.log` for clean exit, confirm new dated file shows up in Drive.
- **Future extensions:** add Z2M `data/` to the same script when smart-home stack comes up; consider also backing up `/opt/stack/visa_bulletin/.env` (encrypted) since it has DB password + DJANGO_SECRET_KEY.

### 3. ~~CF edge adds `X-Robots-Tag: noindex, nofollow` to all responses~~ — RESOLVED

- **Final diagnosis:** NOT a CF setting. Symptom of the routing bug (item now in "Done"). Real `visa-bulletin.us` traffic was being served from staging stack, which had `X-Robots-Tag: noindex,nofollow` configured deliberately.
- **After routing fix:** prod responses are clean (no X-Robots-Tag), staging responses still have it (correct, by design).
- **Closed.**

### 4. Weekly DB refresh — not running anywhere

- **State:** Lightsail's Sunday 02:00 UTC weekly refresh is **disabled** (commented in crontab). Homeserver does not yet run it. The hourly bulletin refresh IS running on homeserver.
- **Plan:** implement the staging-DB-flip pattern documented in `.cursor/rules/deployment.mdc` "Weekly DB Refresh Pattern". First trial run should be done with you watching, before scheduling unattended.
- **Until then:** salary-data freshness will gradually drift behind reality. The bulletin tables (the visible monthly data on the site) stay current via the hourly job.

---

## P1 — Hardening / nice-to-have (no rush)

### Recurring: daily Reddit-watch via F5Bot

- **Why here:** F5Bot alerts (`admin@f5bot.com`) ping us whenever Reddit threads mention "visa bulletin prediction", "green card priority date", or "priority date movement" — exactly the discussions our app is for. These are not noise; they're community traffic we should engage with where it makes sense.
- **Cadence:** check daily during the morning checkup. For each new F5Bot email:
  1. **Log the signal** in the "F5Bot signal log" subsection below (date, keyword, subreddit, thread title + URL). Don't let the content disappear into archive without a written record — the user can scan the log weekly to spot patterns or revisit threads they skipped at first.
  2. Open the linked Reddit thread.
  3. Decide: does our site offer useful context? Worth a comment with link?
  4. If yes — comment (or note to do so manually). If no — log only.
  5. After processing (commented or skipped), archive the F5Bot email.
- **Do NOT filter F5Bot blanket-archive.** The daily_checkup skill has the rule.

#### F5Bot signal log

Newest at top. Format: `YYYY-MM-DD — keyword — r/sub — "thread title" by user (link) — action taken`.

- 2026-05-14 — *priority date movement* — r/ShareAiPrompts — "June 2026 Visa Bulletin" by jamesidayi — https://www.reddit.com/r/ShareAiPrompts/comments/1tcm2wm/ — logged, not commented yet
- 2026-05-13 — *green card priority date* — r/nri — "Any 2019+ EB2/EB3 Families with H4 kids Planning Their Future in the US?" by FarPrune250 — https://www.reddit.com/r/nri/comments/1tca6sb/ — logged, not commented yet

### 5. CSP (Content-Security-Policy)

- **State:** **not set** on either prod or staging. Other security headers (HSTS, X-Frame, Referrer, Permissions, X-Content-Type) are now in place.
- **Why deferred:** CSP requires per-page audit of inline scripts (Plotly, GoatCounter, possibly Django admin) before lock-down without breaking pages.
- **Approach when picked up:** start with `Content-Security-Policy-Report-Only` for ~1 week, look at violation reports, then promote to enforcing.

### 6. Postgres tuning for homeserver's 8 GB RAM

- **State:** running with default `postgres:14` config (`shared_buffers=128MB`, `work_mem=4MB`).
- **Why deferred:** the OS file cache holds the entire 4 GB DB; query perf is already 2-3x faster than Lightsail. Tuning would help maybe 5-10% on cold cache; not the bottleneck today.
- **Worth doing if:** a future workload (heavier ingest, more concurrent users, materialized views) starts spilling out of cache. Suggested values for 8 GB:
  ```
  shared_buffers = 2GB
  effective_cache_size = 6GB
  work_mem = 16MB
  maintenance_work_mem = 256MB
  max_parallel_workers = 4
  max_parallel_workers_per_gather = 2
  max_connections = 50
  ```

### 7. Cloudflare Access on `staging.visa-bulletin.us`

- **State:** staging is publicly reachable. We added `robots.txt: Disallow: /` and `X-Robots-Tag: noindex,nofollow` so search engines stay away, but anyone with the URL can still hit it. Bots ignore both signals freely.
- **Why care:** staging has its own DB clone of prod data. Doesn't expose any new data, but it's noise on logs and a target for scanning attacks.
- **Action:** in Cloudflare Zero Trust → Access → Application, gate `staging.visa-bulletin.us` behind email-OTP (just your email). Real cost is one click on first visit.

### 8. Fix legacy-bulletin hourly cron noise (PARTIALLY ADDRESSED 2026-05-05)

- **State (2026-05-14):** parser support for the 2004 colspan-title format was added in commit `2400477` (2026-05-05) but cron noise persists for a *different reason* — the post-parse validator at `lib/ingest/plugins/visa_bulletin.py:339` requires a pre-existing `Bulletin` DB row for the publication date, and rows for 10 ancient months are missing. So the failures are now **validation failures**, not parse failures. Pattern: `Bulletin not found for publication date YYYY-MM-01`.
- **Affected sources (10, not 7 as previously listed):** 198 (Jul 2015), 199 (Jun 2015), 200 (May 2015), 201 (Apr 2015), 202 (Mar 2015), 203 (Feb 2015), 204 (Jan 2015), 328 (Apr 2004), 329 (Mar 2004), 330 (Feb 2004). Modern bulletins unaffected; script exits 0.
- **Cheap fix:** insert synthetic `Bulletin` rows for those 10 publication dates so the validator passes. Or insert `IngestRun` rows with status `COMPLETED` for those sources to hide them from the discovery query.
- **Right fix:** add `discovery_status` enum to `ingest_data_source` (`ACTIVE` / `SKIP_INCOMPATIBLE_FORMAT` / `MISSING_BULLETIN_ROW`); migration + script update.
- **Suppressed in daily checkup:** `mcp/daily_checkup_server.py` filters these source IDs and the `Bulletin not found for publication date 200X / 201[0-5]` pattern from its bulletin-refresh error count, so the daily checkup does not fire yellow hourly.

### 9. SEO meta-tag review + Search Console indexing alert (2026-05-10)

- **State:** Google Search Console alert received 2026-05-10 (Gmail msg `19e14d7f30bb5a89`): *"New reasons prevent pages from being indexed on site visa-bulletin.us"*. This is downstream of items #3 (X-Robots-Tag, resolved) and the staging-vs-prod routing fix.
- **Action:**
  1. Sign in to Search Console → **Pages** report → inspect the new "reasons" (likely candidates: `Discovered - currently not indexed`, `Crawled - currently not indexed`, soft-404, canonical conflicts, or lingering `noindex` from the pre-fix routing window).
  2. Use URL Inspection on 2-3 affected URLs to see Google's last crawl date and which header/meta was seen at that time.
  3. If the issue is just stale data from the pre-fix routing window, request reindexing on the key pages and wait.
  4. If there's a real config issue, fix templates / sitemap / canonical tags accordingly.
- **Impact:** affects organic discoverability. Bulletin landing pages and employer profile pages are the most important to keep indexed.

### 10. Decide fate of Lightsail-orchestrator code

- **State:** `scripts/cron/refresh/orchestrate.py`, `scripts/cron/refresh_and_switch.py`, and the IP-flip helpers exist in the repo. They will not work on the homeserver topology (no second instance to flip with).
- **Options:** (a) delete entirely — git history preserves them, (b) move to `legacy/` directory with a README, (c) gut and rewrite as the new dual-stack flip.
- **Not urgent** — no one runs them today.

### 11. Documentation cleanup

- `HARDENING_PLAN.md`, `INSTANCE_ROTATION.md`, `DEPLOYMENT_ZERO_DOWNTIME.md`, `PRODUCTION_CLEANUP.md`, `REFRESH_DATA_PYTHON_REFACTOR.md`, `docs/GRADUATION_KNOWN_ISSUES.md`, `docs/DEPLOY_KEY_SETUP.md`, `docs/BRANCHING_AND_DEPLOYMENT.md` — all describe pre-migration architecture.
- **Action:** decide which to delete (most), which to gut + rewrite (BRANCHING_AND_DEPLOYMENT.md is referenced from rules), which to leave as historical notes.

---

## P2 — Future work (when motivated)

### 12. Cache warmer after deploy

- After `docker compose up -d web` (which clears Django's local memory cache and may invalidate CF edge cache), the next cold user hit on the dashboard takes 2-3s. Run a script that hits the top ~20 URLs after each deploy to pre-warm Django's `@cache_page` in Redis. Once Redis is warm, CF edge caches the HTML, and humans never feel the cold path.

### 13. Cron-driven `docker system prune` on homeserver

- Weekly. `docker system prune -af --filter "until=168h"`. The 64 GB SSD will fill with dangling images otherwise after a few months of deploys.

### 14. Adaptive bot rate-limit (port `nginx_bot_adaptive.sh`)

- Lightsail's `deployment/scripts/nginx_bot_adaptive.sh` dynamically tightens limits when traffic spikes. Worth porting to homeserver if static limits prove too generous or too strict in practice. **Currently we're at <0.5 RPS — way under any limit.**

### 15. Monitoring / alerting

- Nothing alerts when site goes down. Cheap options: UptimeRobot free tier on `https://visa-bulletin.us/health` (would need a `/health` endpoint added to Django, or `nginx`'s `location = /health`). Could also use Cloudflare Workers with email.

### 16. Promote `homeserver` from DHCP lease to router-side reservation

- Currently homeserver gets `192.168.1.152` via standard DHCP. If that lease changes, the smart-home stack (when up) would be inconvenient to point at. Set a static reservation on the router for the homeserver MAC. **Doesn't affect visa_bulletin** (CF tunnel routes by name not IP).

---

## Done (post-migration session, 2026-05-08 / 09)

- ✅ DNS cutover: `visa-bulletin.us` + `www` → CF tunnel. Lightsail traffic = 0.
- ✅ Hourly bulletin refresh moved to homeserver cron.
- ✅ Lightsail crons disabled.
- ✅ Lightsail instances stopped (still billing, but freed compute).
- ✅ Dual-environment built: prod stack at `/opt/stack/visa_bulletin/`, staging stack at `/opt/stack/visa_bulletin_staging/`. Each has own DB, redis, web, nginx. Shared `cloudflared` + `vb_public` Docker network for ingress.
- ✅ Bot rate limits + per-bot/per-/16/per-IP tiers, `main_timed` log format with `$request_time`, basic security headers (HSTS, X-Frame, Referrer, Permissions, X-Content-Type) on prod nginx.
- ✅ Staging stack has `Disallow: /` robots.txt + `X-Robots-Tag: noindex, nofollow`.
- ✅ ALLOWED_HOSTS bug from cutover documented as global rule (`~/.cursor/shared_rules/django.mdc`).
- ✅ Rules updated to reflect homeserver topology: `homeserver.mdc`, `deployment.mdc`, `branching.mdc`, `AGENTS.md`, `~/.claude/CLAUDE.md`.
- ✅ Home-automation project scaffolded at `~/cursor_projects/home_automation/` with HANDOFF.md.
- ✅ **Critical bug found & fixed:** CF tunnel ingress was routing real `visa-bulletin.us` traffic to staging stack for ~30 min after dual-env build. Cause: ingress used Compose service-name `nginx` which on the shared `vb_public` external network resolved to the staging container (because Compose only adds the service-name alias on networks declared in the `networks:` block, not on networks attached via `docker network connect`). Fix: switched ingress to container-name aliases (`vb_nginx`, `vb_stg_nginx`). Lesson added to `~/.cursor/shared_rules/homeserver.mdc` "Common Mistakes" section.
- ✅ rclone + Google Drive backups: rclone authorized on Mac AND homeserver (both have `gdrive:` remote), daily cron at 1 AM UTC, one manual test upload verified in Drive.
- ✅ **Disaster recovery scripts** at `deployment/dr/`: `preflight.sh` (read-only checks, all green), `failover.sh` (start Lightsail + DNS flip, ~3 min), `restore_latest_backup_on_lightsail.sh` (refreshes Lightsail DB from latest GDrive backup, +5 min), `failback.sh` (DNS back + stop Lightsail). RUNBOOK.md documents 3 scenarios. **Tested end-to-end 2026-05-09:** Lightsail boot to "web responds 200" took ~30s (instance was warm); failover→failback round trip took 7 min total without disrupting prod (declined the actual DNS flip during the drill).
