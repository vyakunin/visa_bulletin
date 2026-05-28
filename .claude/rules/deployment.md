# Deployment and Rollout Rules

> **Migration status:** Production migrated from AWS Lightsail to a self-hosted Dell Wyse 5070 (alias `homeserver`) on 2026-05-08. Lightsail kept reachable on `44.209.204.255` for rollback during the burn-in period; will be decommissioned once burn-in passes. Sections marked **[Lightsail — kept for rollback]** below describe the OLD production and only apply if a rollback is in progress. Everything else describes the **current** production.

## Production Topology (current)

Production is a single Docker Compose stack at `/opt/stack/visa_bulletin/` on `homeserver` (Ubuntu 24.04, Dell Wyse 5070, 8 GB RAM, 64 GB SSD, IP 192.168.1.152). All public traffic enters via Cloudflare Tunnel — there are **no router port forwards**. TLS terminates at the Cloudflare edge.

| Container | Purpose | Image / Notes |
|---|---|---|
| `vb_postgres` | PostgreSQL 14, ~3.9 GB DB on `./postgres-data/` | `postgres:14` |
| `vb_redis` | Page cache, Django sessions | `redis:7-alpine`, 512 MB maxmemory allkeys-lru |
| `vb_web` | Django + gunicorn 23 (3 workers × 2 threads) | `ghcr.io/vyakunin/visa_bulletin:${IMAGE_TAG}` |
| `vb_nginx` | Static file serving + reverse-proxy to web | `nginx:1.27-alpine`, listens on internal `:80` and LAN-side `:8080` |
| `vb_cloudflared` | Cloudflare Tunnel connector (4× QUIC to CF edge) | `cloudflare/cloudflared:latest` |

**Public hostnames** (CF Tunnel ingress; tunnel id stored at `~/tokens/cloudflare_tunnel_homeserver_id` on the Mac):
- `visa-bulletin.us`, `www.visa-bulletin.us` — production
- `staging.visa-bulletin.us` — currently routes to **same** stack as prod (placeholder until dual-environment is built; see below)

**SSH access:** `ssh -i ~/.ssh/homeserver_ed25519 vyakunin@homeserver.local`. User `vyakunin` is in groups `sudo` and `docker`. The pre-cutover Lightsail aliases (`prod_2Gb_vm`, `staging_2Gb_vm`, `backup_0_5Gb_vm`) still work but only for the old Lightsail instances.

## Production Deploy Process (current)

**Code deploy is `docker compose pull web && docker compose up -d web`. It has
~10-15s of customer-facing 502s** while the old container stops and the new
one boots (migrate + collectstatic + gunicorn). CF-cached pages keep serving
from the edge during the window; uncached/POST requests fail.

### Rule: check the low-traffic window before pushing to prod

Per the GSC + GoatCounter daily-checkup data, dashboard traffic is ~5-7k
views/day with a clear monthly cycle. Before doing a prod deploy, consult
the **most recent daily_checkup digest** (or pull `gsc_query_search_analytics`
+ GoatCounter directly) to find the local low-traffic hour. As of mid-2026
the rough pattern is:

| Window (UTC) | Berlin local | PDT local | Typical traffic |
|---|---|---|---|
| 22:00-06:00 | 00:00-08:00 | 15:00-23:00 | **low** (deploy-safe) |
| 06:00-12:00 | 08:00-14:00 | 23:00-05:00 | medium |
| 12:00-22:00 | 14:00-00:00 | 05:00-15:00 | **peak** (avoid) |

Re-verify these bands quarterly — the user base skews US + India so the
peak shifts seasonally. The daily_checkup MCP can be extended to surface a
"current hourly position vs cycle" line if this needs to be automated.

If a deploy genuinely cannot wait for the low-traffic window (security
patch, broken bulletin parser before publication), accept the 502 window
and proceed — but state explicitly *"deploying at peak, expected ~3-5 user
errors"* so the cost is visible.

### Deploy command

```bash
ssh homeserver.local
cd /opt/stack/visa_bulletin
# Update IMAGE_TAG in .env if needed (default is "latest" which tracks prod branch builds)
docker compose pull web
docker compose up -d web   # recreates only web; postgres, redis, nginx, cloudflared untouched
docker compose logs --tail 30 web   # confirm migrate + collectstatic + gunicorn boot
curl -s -o /dev/null -w "%{http_code}\n" https://visa-bulletin.us/   # 200
# After deploy: flush Redis page cache so the new content is served, not the pre-deploy cache
docker exec vb_redis redis-cli -n 1 FLUSHDB
```

### Rule: Capture a pre-deploy perf baseline + post-deploy verification window

**Every prod deploy (code, schema, infra) MUST include a pre-deploy baseline snapshot AND a 30-minute post-deploy verification window** with the same signals. Latency / 5xx regressions after a deploy are common (planner picks a new plan after schema changes, a new view forgets to use `select_related`, a Redis cache clear cold-starts every page) and they are catastrophically cheap to detect early and expensive to detect via user reports. This rule exists because the 2026-05-17 staging-crawl incident showed that perf regressions silently degrade UX for hours unless deliberately monitored — and because that incident's own fix (trigram indexes) needed verification it wasn't trivially providing.

**Pre-deploy snapshot (T-5min, save to /tmp/predeploy_$(date +%s).txt or paste into chat):**

```bash
ssh homeserver "uptime; \
  free -h | head -2; \
  docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'; \
  echo '--- 5xx last 30 min ---'; \
  docker logs vb_nginx --since 30m 2>&1 | grep -E '\\] \"[A-Z]+ [^\"]+\" 5' | wc -l; \
  echo '--- gunicorn SLOW REQUEST last 30 min ---'; \
  docker logs vb_web --since 30m 2>&1 | grep -c 'SLOW REQUEST'; \
  echo '--- request rate last 5 min ---'; \
  docker logs vb_nginx --since 5m 2>&1 | grep -cE '\\] \"[A-Z]+'"
```

**During deploy:** keep `docker logs -f vb_web` open in one terminal. Expected: the ~10-15s 502 window during container swap. Anything else is a regression — abort and roll back per the rollback section.

**Post-deploy verification (T+5, T+15, T+30):** re-run the snapshot block above and compare against pre-deploy. Acceptable drift:

| Signal | Pre → Post acceptable | Investigate / roll back |
|---|---|---|
| Host load (1m) | within 1.5× of pre | >2× and sustained 5+ min |
| vb_postgres %CPU | within 1.5× of pre | >3× and sustained 5+ min |
| vb_web mem (per container) | within 1.3× of pre | >1.5× and growing |
| nginx 5xx / 30 min | ≤ pre + 5 (cold-start 502s normal) | > pre + 15, or any sustained 5xx after T+5 |
| gunicorn SLOW REQUEST / 30 min | ≤ pre + 10% | > pre + 50% — almost certainly a planner regression |

**For DB-touching deploys** (schema changes, new indexes, query rewrites): also EXPLAIN ANALYZE the affected query path **inside Django** (parameterized) — not just literal psql, because Django's `__icontains` emits `UPPER(field) LIKE UPPER(%s)` and the planner gives different plans for parameterized vs literal strings. Use the recipe:

```bash
ssh homeserver "docker exec vb_web python3 -c \"
import django, os, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()
from django.db import connection
from django.conf import settings
settings.DEBUG = True
from models.salary import SalaryRecord
from django.db.models import Q
qs = SalaryRecord.objects.filter(Q(job_title__icontains='CASHIER') | Q(soc_title__icontains='CASHIER')).exclude(is_worksite=True).exclude(employer_name='Unknown').filter(wage_annual__isnull=False, wage_annual__gt=0).order_by('-wage_annual','-fiscal_year')
t0=time.time(); list(qs[:50]); print(f'{(time.time()-t0)*1000:.0f}ms')
print(connection.queries[-1]['sql'][:300])
\""
```

A query that's <100ms via literal psql but >1s via this Django path is a planner-LIMIT-pessimization signature: the index exists but the planner picks Index Scan Backward on `wage_annual` instead. Trigram indexes alone do not fix this — needs a code-level subquery rewrite (force a Bitmap path).

**Heavy mutations (CREATE INDEX, ALTER TABLE, schema migrations) MUST use the CONCURRENTLY form so reads + writes continue.** A non-concurrent ALTER on `salary_record` (1.5M rows) acquires AccessExclusiveLock and blocks every reader for the duration → effective outage. See migrations 0044, 0046, 0047 for examples of the `RunSQL(... atomic=False)` pattern.

**Rollback triggers — if any of these fire in the verification window, roll back immediately, don't try to fix forward in prod:**
- Sustained 5xx > 5/min for 5 consecutive min.
- p95 request latency >5× pre-deploy.
- vb_postgres CPU saturated (>80%) for 5+ min without an obvious upstream cause (cron, ANALYZE).
- Bot/scraper crawl that the deploy was supposed to mitigate is *worse* afterward.

Rollback is just `IMAGE_TAG=<previous_sha>` in .env + `docker compose pull web && docker compose up -d web` + flush Redis. No fancy orchestrator needed since the registry keeps the prior image.

### Rule: Diff staging vs prod HTML for top properties before graduation

**Before promoting `staging-<sha>` to prod, diff a handful of top URLs between `https://staging.visa-bulletin.us/` and `https://visa-bulletin.us/` and read the diff manually.** Smoke tests confirm the page is HTTP 200; this confirms the page is *correct*. Code deploys can silently change content (template tweaks, view-context shifts, regenerated blog narrator output, new feature flags) in ways that no individual unit test covers but a side-by-side diff makes obvious.

**When to run:** after staging is up on the new image, before `git merge --ff-only staging` on the prod branch. Treat it as the last gate.

**URL set (covers ~80% of risk surface):**
- `/` — homepage (top traffic, lots of dynamic widgets)
- `/employment-based/india/` — top per-country dashboard
- `/predictions/employment_based/<latest-month>/` — current EB predictions (data-heavy + template-heavy)
- `/predictions/family_sponsored/<latest-month>/` — current FS predictions
- 2-3 **historical** prediction months (e.g. `/predictions/2024-1/`, `/predictions/2020-1/`, `/predictions/2005-1/`) — these should be *invariant* once published; any diff here is a regression
- The methodology blog post `/analysis/how-my-prediction-model-works/` — narrator output + manual edits, easy to drift between DBs
- The latest monthly blog post (whichever `/analysis/visa-bulletin-analysis-<latest-month>/` is freshest)

**Helper (bash, zsh-safe array syntax):**

```bash
bash -c '
mkdir -p /tmp/vb_diff && rm -f /tmp/vb_diff/*
URLS=(
  "/"
  "/employment-based/india/"
  "/predictions/employment_based/2026-6/"
  "/predictions/family_sponsored/2026-6/"
  "/predictions/2024-1/"
  "/predictions/2020-1/"
  "/predictions/2005-1/"
  "/analysis/how-my-prediction-model-works/"
)
for u in "${URLS[@]}"; do
  slug=$(echo "$u" | tr "/" "_" | sed "s/^_//; s/_$//")
  [ -z "$slug" ] && slug=root
  curl -s "https://visa-bulletin.us$u"    > "/tmp/vb_diff/prod_$slug.html"
  curl -s "https://staging.visa-bulletin.us$u" \
    | sed "s|staging\.visa-bulletin\.us|visa-bulletin.us|g" \
    > "/tmp/vb_diff/stg_$slug.html"
  d=$(diff "/tmp/vb_diff/prod_$slug.html" "/tmp/vb_diff/stg_$slug.html" | wc -l | tr -d " ")
  ps=$(wc -c < "/tmp/vb_diff/prod_$slug.html" | tr -d " ")
  ss=$(wc -c < "/tmp/vb_diff/stg_$slug.html" | tr -d " ")
  printf "%-50s prod=%sb stg=%sb difflines=%s\n" "$u" "$ps" "$ss" "$d"
done
'
```

The `sed` rewrite of `staging.visa-bulletin.us → visa-bulletin.us` is **load-bearing** — without it every canonical_url, og:url, og:image, twitter:url, and schema.org Dataset URL shows as a diff and drowns out real signal.

**Then inspect the diffs and classify each block:**

```bash
# For each URL with non-zero difflines:
diff /tmp/vb_diff/prod_<slug>.html /tmp/vb_diff/stg_<slug>.html \
  | grep -vE '(goatcounter|data-cfemail|cdn-cgi/l/email-protection|window\.goatcounter|data-gc-event|Strip query strings|Outbound-link|Trigger via|action_type=)' \
  | head -80
```

The `grep -vE` filter strips known-cosmetic noise: the rotating Cloudflare email-obfuscation tokens (`data-cfemail=...`) which differ on every request, and any GoatCounter / `data-gc-event` content that's been merged to staging but not yet on prod (which IS the deploy you're about to do — those diffs are *expected*).

**Classify what's left:**

| Diff kind | What it means | Action |
|---|---|---|
| Different `<link rel="canonical">` host (other than the substituted hostname) | Origin is generating wrong canonical — typically a stale Redis cache populated by a non-CF probe (Docker healthcheck hits `http://localhost:8000/`). | Investigate; usually `docker exec vb_stg_redis redis-cli -n 1 FLUSHDB` and re-test. Block graduation until canonical is right. |
| Historical prediction (`/predictions/<YYYY-M>/` for past months) HTML body differs | `PredictedCutoff` rows differ between staging DB and prod DB — staging has a regenerated model snapshot that never published to prod, OR prod has manual edits. | Pure data divergence. Code-only deploy doesn't sync DB, so prod stays as-is. Decide separately whether to `publish_predictions` on prod with the staging model output, or to leave both DBs as-is and accept the preview is misleading. **Does NOT block code graduation** unless the user wants the model output to ship too. |
| Latest prediction month (`/predictions/employment_based/<latest>/`) differs in cells, badges, CI widths | Same as above — data divergence. Inspect: if changes are template-driven (new badge class never seen on prod), check the diff prod..staging on `webapp/templates/` to confirm. If pure data, classify as data-only. |
| Methodology / latest-month analysis blog post body differs (paragraph present in one, missing in the other) | `BlogPost.body_html` divergence in the DB. Often staging was regenerated without manual prod-side edits. | Surface to user: "If you regenerate <post> on prod after this deploy, you will lose <description of paragraph>." Block graduation only if user wants prod to match staging exactly. |
| Different view-context numbers (filing counts, employer counts, top-N lists) | Different underlying data — staging DB is a different snapshot than prod DB. | Expected. Don't block on this. |
| New template structure (added/removed `<div>`, new CSS class, different element order) where the diff aligns with files touched in the 14-commit `prod..staging` range | Intentional code change. | Expected for this deploy. ✓ |
| Template/data difference NOT aligned with any commit in `prod..staging` | Mystery. Investigate before graduating. | **Block** until root cause found. |

**Quick "what code differs prod..staging" cheat-sheet:**

```bash
cd ~/cursor_projects/visa_bulletin_staging
git log --oneline origin/prod..origin/staging
git diff --name-only origin/prod..origin/staging | grep -E '(webapp/views|webapp/templates|models)' | head -20
```

Cross-reference unexplained HTML diffs against this list. If the diff is in `webapp/templates/webapp/blog_post.html` and that file is in `git diff`, you know which commit to read. If it isn't in `git diff`, the divergence is data.

**Why this rule exists:** 2026-05-27 — after a 7-cherry-pick chain to staging, smoke tests passed but a manual diff against prod surfaced (1) a 9-line "Scope of accuracy claims" paragraph missing from staging's methodology BlogPost (DB drift), (2) substantively different EB prediction values + confidence intervals (data drift in `PredictedCutoff`), and (3) `<link rel="canonical" href="http://localhost:8000/">` on staging's homepage cache (Docker healthcheck populating cache with no Host header). None of those would have failed a 200-status smoke test. The diff caught all three in ~5 minutes.

### Optional: zero-downtime via blue/green (NOT YET BUILT)

Notion follow-up ticket exists for building a reusable
`tools/blue_green_deploy.sh` script that uses the existing dual-stack
(`visa_bulletin` + `visa_bulletin_staging` compose projects sharing
`vb_public`). High-level dance: repoint staging container's DB to prod
postgres → CF Tunnel ingress swap (prod hostnames → `vb_stg_nginx`) →
recreate `vb_web` with no traffic on it → swap CF ingress back → revert
staging DB. Per-deploy overhead ~30-60s, customer downtime 0s. Build it
when deploy frequency or off-peak constraints justify the orchestration
cost.

**Building images** still happens via the GitHub Actions workflow on push to `staging`/`prod` branches — see "Docker Image Strategy" below. Nothing about the build/registry side changed; only the runtime moved.

## Future: Dual-Environment (NOT YET IMPLEMENTED)

The current single-stack setup serves both production and staging hostnames against the same DB. The intended future state is **two parallel stacks** sharing one cloudflared:

```
/opt/stack/visa_bulletin_prod/      → visa-bulletin.us, www.visa-bulletin.us
/opt/stack/visa_bulletin_staging/   → staging.visa-bulletin.us
/opt/stack/_shared/                 → vb_cloudflared (ingress: route by Host header to prod_nginx or stg_nginx)
```

**Why:** (1) safer code rollouts (new image deployed to staging stack first, smoke-tested, then promoted to prod), (2) **weekly DB refresh runs against staging DB** so production reads are never blocked. The Lightsail orchestrator's instance-rotation logic doesn't translate; the dual-stack pattern replaces it. See "Weekly DB refresh pattern" below for the spec.

## Weekly DB Refresh Pattern (spec — not yet implemented)

The weekly visa-bulletin + salary refresh is a heavy job (millions of rows, index drop/rebuild, ~30 min) that would lock the prod DB during ingest. The new pattern keeps prod read-only throughout:

1. **Reset staging DB:** `pg_dump prod | pg_restore staging` (~5 min). Now staging has a snapshot of current prod.
2. **Run refresh on staging stack:** the existing `scripts/cron/refresh_data.sh` pipeline runs against the staging DB. Drops indexes, ingests, rebuilds indexes, runs clustering, vacuums.
3. **Smoke staging:** verify `staging.visa-bulletin.us` renders correct data, no regressions, row counts make sense.
4. **Atomic flip:** stop both stacks (~30 s blip), `mv prod/postgres-data → archive_<date>/`, `mv staging/postgres-data → prod/postgres-data`, restart both.
5. **Re-seed staging DB** as a fresh copy of new-prod for the next cycle.

**Hourly bulletin refresh** is light (one HTTP fetch + ~1 row insert) and stays on prod. **Cron entry on homeserver:**

```
0 * * * * docker exec -w /app vb_web python3 -m scripts.cron.refresh_bulletin >> /opt/stack/visa_bulletin/logs/cron/bulletin_refresh.log 2>&1
```

Lightsail crons are **disabled** (commented out in `ubuntu@prod_2Gb_vm`'s crontab; can be re-enabled if rollback is needed during burn-in).

## Rollback to Lightsail (during burn-in only)

If something goes wrong on homeserver and we need to flip back to Lightsail:

```bash
# Set CF DNS records back to A 44.209.204.255 (proxied)
CF_TOKEN=$(cat ~/tokens/cloudflare_api_token)
ZONE_ID=$(cat ~/tokens/cloudflare_zone_id_visa_bulletin)  # mode 600
for name in "visa-bulletin.us" "www.visa-bulletin.us"; do
  # Find current record id (CNAME → tunnel)
  REC_ID=$(curl -s -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?name=$name" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")
  # Replace with A record back to Lightsail
  curl -s -X PUT -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$REC_ID" \
    -d "{\"type\":\"A\",\"name\":\"$name\",\"content\":\"44.209.204.255\",\"ttl\":1,\"proxied\":true}"
done
# Re-enable Lightsail crons
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@prod_2Gb_vm 'crontab -l | sed "s|^# DISABLED-CUTOVER ||" | crontab -'
```

DNS propagates in ~10s when proxied. Effective rollback in <60 seconds.

## Docker Image Strategy

Images built by GitHub Actions on pushes to `staging`/`prod` branches or version tags.

- `:latest` — prod branch builds only. Used by `docker-compose.yml` default.
- `staging-<sha>` / `prod-<sha>` — branch-specific SHA tags.

**Image contains:** Python runtime, system deps (libpq5), pip packages, gunicorn, baked-in app code.

**Prod and staging both run baked-in image code** (no `../:/app` volume mount). To deploy code changes: push to branch → wait for CI → `docker pull` + `docker-compose up -d web` on instance.

**⚠️ CRITICAL:** `docker restart` does NOT update the image. To deploy a new image you MUST recreate the container via `docker-compose up -d` with the correct `IMAGE_TAG`. Verify: `docker inspect <name> --format '{{.Config.Image}}'`.

**Transient CI failures:** Bazel builds inside Docker can fail due to transient network errors (502 from GitHub). These are not code bugs — retry via GitHub Actions UI or re-push.

## Rule: Never Edit Files Directly on Instances

**🚨 CRITICAL: NEVER SSH into an instance and edit files (sed, vi, echo >>, etc.) as a fix. ALL changes go through git branches.**

Workflow: fix on `main` → commit → cherry-pick to target branch via worktree → push → `git fetch && git reset --hard origin/<branch>` on instance → restart container.

**❌ BAD:** `ssh staging_2Gb_vm "sed -i 's/200m/512m/' deployment/docker-compose.yml"` (lost on next `git reset --hard`)
**✅ GOOD:** Fix in main → commit → cherry-pick to staging → push → pull on instance

## Rule: Never Restart or Recreate Prod Containers Without Explicit User Instruction

**🚨 CRITICAL: NEVER run `docker-compose up/restart`, `docker restart`, or any container lifecycle command on the production-serving instance unless the user explicitly asks you to.**

- "Graduate staging to prod" means updating the git branch (merge/fast-forward), NOT restarting containers.
- `docker-compose up -d` on docker-compose 1.29.2 triggers the `ContainerConfig` KeyError bug, killing the running container.

**What to do instead:** Update git branch (merge/cherry-pick + push) → `git fetch && git reset --hard` on instance → **stop and ask the user** before touching any containers.

## Rule: Audit Container Topology Before ANY Docker Operation on Prod

**🚨 CRITICAL: Never run `docker-compose up/down/stop/rm`, `docker stop`, or `docker rm` on prod without first running:**

```bash
ssh prod_2Gb_vm "docker ps -a --format '{{.Names}} {{.Status}} {{.Ports}}'"
ssh prod_2Gb_vm "ss -tlnp | grep 8000"
```

Understand which container is *actually serving traffic* before touching anything. Legacy containers may depend on Docker DNS (`redis` hostname). Stopping ANY container on the shared network can break DNS for the serving container.

**Safe:** `docker pull`, `docker logs`, `docker inspect`
**Dangerous:** `docker-compose up -d`, `docker-compose down`, `docker stop/rm` on any container

## Rule: Deploy to Staging After Implementing User-Requested Changes

**Never deploy to prod directly.** All changes go through staging first, then graduate via IP flip. The `prod` branch must only be updated when code is actually deployed to the prod-serving instance.

**Workflow:**
1. Implement change on `main`, run tests, verify locally
2. Cherry-pick to `staging` via worktree: `cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <hash> && git push origin staging`
3. After CI builds: `docker pull ghcr.io/vyakunin/visa_bulletin:<tag>` then `IMAGE_TAG=<tag> docker-compose -f deployment/docker-compose.yml up -d web` on staging instance
4. Verify on staging

**Critical hotfix (prod-down only):** Cherry-pick to `prod` via worktree → push → deploy to prod-serving instance. Only for crashes/5xx.

**Do NOT deploy when:** user says "local only", change is docs-only, user only asked to plan/document.

## Rule: DEBUG Must Be False in Production — Never Derive DEBUG From Other Signals

**🚨 CRITICAL: `settings.DEBUG` must be an explicit env var (`DEBUG=True/False`), defaulting to False. Never derive it from SECRET_KEY, hostname, or any other signal.**

**Why:** If DEBUG silently flips on when an unrelated env var (e.g. `DJANGO_SECRET_KEY`) is missing, a minor config drift will leak URL conf, settings, env vars, and tracebacks to every public 404/500 visitor. This happened on 2026-04-19 — prod served the Django debug 404 page with the full URLconf exposed.

**Required invariants (enforced in `django_config/settings.py` + `debug_safety.py`):**
- `DEBUG` defaults to **False**; only set to True via explicit `DEBUG=True` env var.
- `django_config.debug_safety.assert_debug_is_safe(DEBUG, ALLOWED_HOSTS)` runs at import time and raises `ImproperlyConfigured` if `DEBUG=True` and any production hostname (`visa-bulletin.us`, `www.visa-bulletin.us`) is in `ALLOWED_HOSTS`. Container will refuse to boot.
- Prod `.env` must set `DEBUG=False` explicitly. Local dev `.env` sets `DEBUG=True`.
- Only one docker-compose file is canonical: `deployment/docker-compose.yml` (wires `env_file: ../.env`). Do not add a root-level `docker-compose.yml` without `env_file` — it launches containers with defaults and no secrets.

**Verifying in prod:**
```bash
ssh prod_2Gb_vm "docker exec visa_bulletin_web python -c 'from django.conf import settings; print(\"DEBUG=\", settings.DEBUG)'"
# Expect: DEBUG= False
```

**Regression test:** `tests/test_debug_safety.py` — asserts `assert_debug_is_safe` raises on DEBUG+prod-hostname and is a no-op otherwise. Must stay green.

## Rule: Graduation (Staging to Prod) via Orchestrator [Lightsail — kept for rollback]

> **DEPRECATED post-migration (2026-05-08).** This entire section describes the OLD Lightsail dual-instance graduation flow (rotate static IPs to swap "prod" and "staging" hosts). On homeserver there is only one box; the new flow is `docker compose pull web && docker compose up -d web` (see "Production Deploy Process" above), and the new weekly DB refresh uses the staging-DB-flip pattern (see above). **Only follow the steps below if a Lightsail rollback is in progress during burn-in.**

**Graduation is automated.** Run on the **current prod** instance (the one with prod static IP).

**Required `.env` vars before graduation:**

| Variable | Example | Purpose |
|---|---|---|
| `REFRESH_STATIC_IP_NAME` | `VisaBulletin-StaticIP` | Prod static IP name |
| `REFRESH_STAGING_STATIC_IP_NAME` | `VisaBulletinStaging-ip` | Staging static IP name |
| `REFRESH_ACTIVE_PRIVATE_IP` | `172.26.7.74` | Private IP of current prod |
| `REFRESH_INACTIVE_PRIVATE_IP` | `172.26.13.90` | Private IP of inactive/staging host |
| `REFRESH_MY_INSTANCE_NAME` | `VisaBulletinStaging` | Name of instance running orchestrator |
| `REFRESH_ACTIVE_INSTANCE_NAME` | `VisaBulletinStaging` | Current prod instance name |
| `REFRESH_INACTIVE_INSTANCE_NAME` | `VisaBulletin2GB` | Current staging instance name |

**Also verify before graduation:**
- Inactive host is on `staging` branch (not `prod`): `ssh staging_2Gb_vm "cd /opt/visa_bulletin && git rev-parse --abbrev-ref HEAD"`
- Inactive host Docker is healthy: `ssh staging_2Gb_vm "docker ps"`
- Deploy key present: `ssh prod_2Gb_vm "test -f /home/ubuntu/.ssh/github_deploy_key && echo ok"` (if missing, see `docs/DEPLOY_KEY_SETUP.md`)

```bash
# On current prod instance:
cd /opt/visa_bulletin && set -a && source .env && set +a
./bazel-bin/scripts/cron/refresh_and_switch_py --from-step warm_cache --safety-interval 600
```

**Graduation flow (automated):**
1. Warm cache on inactive → pre-populates Redis
2. Smoke test on inactive → DB health + HTTP endpoints via localhost
3. **GATE: if smoke fails, STOP** (nothing irreversible happened)
4. **Swap static IPs** → inactive becomes new prod (irreversible)
5. HTTPS setup on new prod (certbot)
6. Public URL smoke → curls `https://visa-bulletin.us/`
7. Update `.env` on BOTH instances (swap active/inactive roles)
8. Staging IP reassign → old prod gets staging IP
9. Prod-safe override → drops volume mount, restarts container
10. Git branch update → push `prod=staging` to origin; new prod checks out `prod` branch
11. Rebuild orchestrator binary on new prod
12. Safety interval → waits before shutting down
13. Stop old instance (orchestrator's machine, now staging)

All steps after IP swap (5-13) are non-fatal — warnings only, since the swap already happened.

**`--from-step` options:** `warm_cache` (recommended), `smoke_tests`, `traffic_switch`

**See `docs/GRADUATION_KNOWN_ISSUES.md` for known graduation failure modes and their fixes.**
**See `docs/DEPLOY_KEY_SETUP.md` for deploy key setup (one-time per instance).**

## Post-Graduation Babysitting Checklist [Lightsail — kept for rollback]

> **DEPRECATED post-migration.** Only follow during a Lightsail rollback. The current homeserver post-deploy verification is just `curl https://visa-bulletin.us/ → 200` plus `docker compose logs --tail 30 web` for any Django errors.

After every graduation, verify these 6 things:

**1. Static IPs**
```bash
export AWS_PROFILE=visa-bulletin-deploy
aws lightsail get-static-ips --region us-east-1 --query 'staticIps[*].{name:name,ip:ipAddress,attached:isAttached,to:attachedTo}' --output table
```
- Prod IP (44.209.204.255) → must be attached to new prod instance
- Staging IP (54.196.241.197) → must be attached to old prod (now staging)

**2. Git branch on new prod**
```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git rev-parse --abbrev-ref HEAD"
# Expected: prod
```

**3. Docker health**
```bash
ssh prod_2Gb_vm "docker ps --format '{{.Names}} {{.Status}}'"
# Expected: visa_bulletin_web Up ... (healthy)
```

**4. Bulletin refresh cron**
```bash
ssh prod_2Gb_vm "tail -5 /var/log/visa-bulletin/bulletin_refresh.log"
```

**5. Site smoke**
```bash
curl -sI https://visa-bulletin.us/ | head -3
# Expected: HTTP/2 200
```

**6. `.env` private IPs on new prod (for next cycle)**
```bash
ssh prod_2Gb_vm "grep -E 'REFRESH_(ACTIVE|INACTIVE)_PRIVATE_IP' /opt/visa_bulletin/.env"
# VisaBulletin2GB private IP: 172.26.13.90; VisaBulletinStaging: 172.26.7.74
```

**7. Public-URL HTTP coverage — main entries, autocompletes, latest blog posts, tail pages.** The orchestrator's smoke test only hits `localhost:8000` *during* graduation, against the inactive host. After the IP swap, run this sweep against the *public* URL to catch DNS/HTTPS/cache regressions and prove the new prod actually serves real traffic. All endpoints must return the expected status; cold-first hits up to ~12s on heavy aggregation pages are acceptable, but warm-cache re-hits must be sub-second.

```bash
BASE="https://visa-bulletin.us"
chk() {
  local url="$1" expect="$2"
  local out; out=$(curl -s -o /tmp/body.html -w "%{http_code}|%{time_total}" --max-time 30 "$BASE$url")
  printf "%-55s %s (expect %s)\n" "$url" "$out" "$expect"
}
# Main entry points
for u in / /salaries/ /worksites/ /employers/ /employers/rankings/ /job-titles/ \
         /analysis/ /faq/ /about/ /contact/ /health/ /predictions/ \
         /employment-based/ /family-sponsored/ /spaghetti/ \
         /employment-based/india/ /employment-based/china/ /family-sponsored/india/ \
         /sitemap.xml /robots.txt /llms.txt; do chk "$u" 200; done
chk /predictions/employment_based/ 302   # redirects to latest YYYY-M

# Autocomplete APIs (must return non-empty JSON)
for q in google amazon microsoft; do
  curl -s "$BASE/api/company-autocomplete/?q=$q" | head -c 60; echo
done
for q in software data manager; do
  curl -s "$BASE/api/job-title-autocomplete/?q=$q" | head -c 60; echo
done

# Latest blog posts (every post linked from /analysis/ landing must render)
curl -s "$BASE/analysis/" | grep -oE '/analysis/[a-z0-9-]+/' | sort -u | while read s; do chk "$s" 200; done

# Tail pages — pick top employer + top job-title slugs from autocomplete results,
# plus the freshest /predictions/{employment,family}_based/YYYY-M/ detail pages.
# Cold first hit can be slow; warm should be <300ms. Confirm Plotly chart renders:
curl -s "$BASE/predictions/employment_based/$(date +%Y-%-m)/" | grep -c plotly  # expect ≥1
```

**8. Latest-bulletin blog post regenerated on the new staging instance.** Graduation does **not** re-run the blog narrator on the new staging — it only updates code and restarts services. Whatever post is in the new staging's DB is whatever the *old prod* had. If the narrator changed in this cycle (or any post needs a re-render before the next data-refresh pipeline), regenerate on the new staging explicitly:

```bash
# After confirming new staging container runs the new image:
ssh staging_2Gb_vm "docker ps --format '{{.Names}} {{.Image}}'"
# If still on the old image, pull + recreate (handles docker-compose 1.29.2 ContainerConfig bug):
ssh staging_2Gb_vm "docker pull ghcr.io/vyakunin/visa_bulletin:staging-<sha>"
ssh staging_2Gb_vm "docker rm -f visa_bulletin_web 2>/dev/null; \
                    cd /opt/visa_bulletin && \
                    IMAGE_TAG=staging-<sha> docker-compose -f deployment/docker-compose.yml up -d web"
# Then regenerate (use the in-container Django setup, not host bazel):
ssh staging_2Gb_vm "docker exec -e DJANGO_SETTINGS_MODULE=django_config.settings visa_bulletin_web \
                    python scripts/oneoff/generate_initial_blog_post.py --month $(date +%Y-%m)"
```

The orchestrator stops the new staging instance after `safety_interval` (default 600s). Do this regen *before* the safety interval elapses, or restart the instance later.

**9. Performance baseline (warm cache).** After 1–2 minutes of bot/user traffic the page caches warm up. Pick a handful of representative cold-then-warm URLs and confirm warm-cache times are <300ms — sustained warm-cache slowness indicates Redis is unreachable, the worker is OOM, or burst credits are exhausted (see "Lightsail burst capacity" in `docs/GRADUATION_KNOWN_ISSUES.md`).

```bash
for u in /worksites/ /employers/rankings/ /predictions/family_sponsored/$(date +%Y-%-m)/ /employer/google-llc/; do
  curl -s -o /dev/null "$BASE$u"  # cold (warms cache)
  t=$(curl -s -o /dev/null -w "%{time_total}" "$BASE$u")  # warm
  printf "%-55s warm=%ss\n" "$u" "$t"
done
```

**Known non-regressions (do not flag during babysit):**
- `/metric-report/` returns 404 unless `bazel run //scripts/vqs:generate_metric_report` has been run and the artefact baked into the image. Most prod deploys ship without it.
- Regime-description bullets in blog posts emit literal `**markdown**` asterisks (template renders the string unprocessed). Pre-existing across all bulletin analyses.

## Rule: Never Use Development Scripts on Production

**NEVER use `restart_server.sh` on production instances.** Production uses Gunicorn in Docker containers — manage via `docker-compose restart`.

**Development (local):** `./scripts/restart_server.sh`, `bazel run //:runserver`
**Production:** `docker-compose -f deployment/docker-compose.yml restart web`, `docker-compose up -d`

## Rule: Check Running Processes on Inactive Host Before Starting Pipeline

Before starting the orchestrator, check for existing `run_pipeline` processes on the inactive host:

```bash
ssh staging_2Gb_vm "ps aux | grep run_pipeline | grep -v grep"
```

If any `discover-and-ingest` processes exist from previous runs, kill the old PIDs first: `kill <PID>`. Multiple ingest processes overload the 2GB box and cause SSH lag or timeouts.

## Rule: Deploy Updated Binary and Run Yourself When Instructed

When instructions say "deploy the updated binary and run again" or "rebuild and re-run":
1. Check current status first (tail orchestrator log, check if a run is in progress)
2. Deploy updated code (cherry-pick to branch via worktree, push, then `git pull` on instance)
3. Rebuild binary on prod: `ssh prod_2Gb_vm "cd /opt/visa_bulletin && bazel build //scripts/cron:refresh_and_switch_py && bazel shutdown"`
4. Run again as appropriate and monitor

## Rule: Always Verify Target Instance Before SSH Commands

Always use the correct SSH alias based on the target instance. When in doubt, verify with user: "Working with prod_2Gb_vm (44.209.204.255), correct?"

**❌ Don't use raw IPs or old `lightsail` aliases.**

## AWS IAM (visa-bulletin-deploy profile) [Lightsail — kept for rollback / decommission]

> **DEPRECATED post-migration.** Only used during Lightsail rollback or final decommission (snapshot + delete instances + delete static IPs). Once the Lightsail account is closed, this section can go.

IAM user `visa-bulletin-deploy` with `lightsail:*`. Profile: `visa-bulletin-deploy` in `~/.aws/credentials`.

```bash
export AWS_PROFILE=visa-bulletin-deploy
aws lightsail get-instances --region us-east-1
aws lightsail get-static-ips --region us-east-1
```

**Giving instances AWS privileges:** Lightsail instances do not support IAM instance roles. To let a script call Lightsail API, provide IAM credentials via `aws configure` with a dedicated profile on the instance (stored outside the repo), or run the orchestrator from a machine that already has credentials.

## Rule: Refresh Orchestrator Preliminary Steps [Lightsail — superseded]

> **SUPERSEDED post-migration.** The orchestrator's two-instance preliminary steps (stop Redis/Gunicorn on inactive, terminate Postgres connections on inactive) only made sense when prod and staging lived on separate Lightsail instances. The new homeserver dual-environment design (see "Future: Dual-Environment" above) keeps both environments running simultaneously; the staging-DB-flip pattern eliminates the need to stop services for ingest. Only refer to this section if a Lightsail rollback is in progress.

The refresh orchestrator (run on active, pipeline on inactive/staging) before the pipeline:
1. Waits for SSH + DB reachable (`run_psql(db_name, "SELECT 1")` with retries)
2. Stops Redis, Gunicorn, Bazel on inactive to free memory
3. Terminates idle Postgres connections on inactive
4. After pipeline: starts Redis and Gunicorn (Docker compose up -d) before traffic switch

## GitHub Actions and Testing

**ALWAYS** test workflow changes with `act --dryrun` before pushing tags. Transient Bazel network failures (502 from GitHub) are not code bugs — retry the workflow.

**Rule:** Test workflow changes → `act -W .github/workflows/docker-build-push.yml -j build-and-push --dryrun` before tagging.
