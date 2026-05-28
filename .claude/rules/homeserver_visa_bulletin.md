# visa_bulletin on the homeserver

Project-specific extension of `~/.claude/rules/homeserver.md`. Anything visa_bulletin-stack-specific (the running containers, the AWS Lightsail migration status, the dual-stack layout) lives here, not in the shared file — keeps generic homeserver content reusable across other projects on the same box.

## `/opt/stack/visa_bulletin/` — production visa-bulletin.us (LIVE since 2026-05-08)

- **Public hostnames served via Cloudflare Tunnel ingress:**
  - `visa-bulletin.us` (apex, primary public)
  - `www.visa-bulletin.us`
  - `staging.visa-bulletin.us` (now served by the dedicated `visa_bulletin_staging` stack — see below)
- **Containers** (compose project `visa_bulletin`):
  - `vb_postgres` — PostgreSQL 14, data on `./postgres-data/`. ~3.9 GB DB (1.5M salary records, 287K employers, 276 bulletins)
  - `vb_redis` — Redis 7-alpine, 512 MB maxmemory, allkeys-lru
  - `vb_web` — Django 4.2.8 + gunicorn 23.0 (3 workers + 2 threads), image `ghcr.io/vyakunin/visa_bulletin:latest`
  - `vb_nginx` — nginx 1.27-alpine, serves static files + reverse-proxies to web. Listens on `:80` internal and `:8080` LAN.
  - `vb_cloudflared` — Cloudflare tunnel connector (4 QUIC connections to CF edge)
- **Bind mounts:** `./staticfiles/` (collectstatic output, owned by uid 999), `./saved_pages/`, `./logs/`, `./postgres-data/`, `./nginx/visa_bulletin.conf`
- **Env vars:** `/opt/stack/visa_bulletin/.env` (mode 600; contains `DJANGO_SECRET_KEY`, `DB_PASSWORD`, `CF_TUNNEL_TOKEN`, `ALLOWED_HOSTS`, etc.)
- **Cron:** `0 * * * *` runs `docker exec -w /app vb_web python3 -m scripts.cron.refresh_bulletin >> /opt/stack/visa_bulletin/logs/cron/bulletin_refresh.log 2>&1` in user vyakunin's crontab
- **Lightsail rollback** (kept until burn-in period passes): old prod still running at `44.209.204.255`. To roll back: change CF DNS records `visa-bulletin.us` and `www.visa-bulletin.us` from CNAME tunnel back to `A 44.209.204.255` (proxied). See API examples in deployment.md.

## `/opt/stack/visa_bulletin_staging/` — staging stack (LIVE)

Compose project `visa_bulletin_staging`. Mirrors prod: `vb_stg_postgres` / `_redis` / `_web` / `_nginx`. Has **no host port binding** — `vb_stg_nginx` exposes only container `:80`, reachable from `vb_cloudflared` via the shared `vb_public` external network. Public hostname `staging.visa-bulletin.us` routes through the same `vb_cloudflared` (in the prod stack) using the container_name alias `vb_stg_nginx` — see Common Mistake about service-name aliases below.

## Dual-stack layout

Prod and staging are separate compose projects sharing the `vb_public` external network for `vb_cloudflared` ingress routing:

```
/opt/stack/visa_bulletin/           # serves visa-bulletin.us, www.visa-bulletin.us
  - vb_postgres / _redis / _web / _nginx / _cloudflared
/opt/stack/visa_bulletin_staging/   # serves staging.visa-bulletin.us
  - vb_stg_postgres / _redis / _web / _nginx
```

`vb_cloudflared` lives inside the prod compose project but routes by Host header to `vb_nginx` (prod) or `vb_stg_nginx` (staging) via the shared `vb_public` network. Container-name aliases are used (NOT service-name aliases — see Common Mistake re: 2026-05-08 misroute).

Why dual-stack: (1) safe code rollouts (deploy new image to staging first, smoke-test, promote to prod); (2) **weekly DB refresh runs against the staging DB**, then atomically promotes (DB volume swap or pg_dump → restore), keeping prod DB read-only during the heavy ingest. The Lightsail orchestrator's instance-rotation logic doesn't translate; this dual-stack pattern replaces it.

## Postgres tuning (applied 2026-05-17)

Both `vb_postgres` and `vb_stg_postgres` run with these non-default planner / cost settings, persisted via `ALTER SYSTEM` to `postgresql.auto.conf` inside `./postgres-data/`:

| Setting | Value | Why |
|---|---|---|
| `random_page_cost` | 1.1 | SSD (default 4 assumes spinning rust → biases planner away from index-only scans) |
| `effective_io_concurrency` | 200 | SSD parallel I/O capacity (default 1 = HDD) |
| `effective_cache_size` | 3 GB | OS file-cache hint — conservatively below total RAM since pb_postgres / pf / ha share the box |
| `work_mem` | 16 MB | Sort + hash buckets per query (default 4MB caused spill-to-disk on hash joins) |
| `default_statistics_target` | 200 | Better selectivity estimates for trigram / multi-column predicates (default 100) |

**`shared_buffers` is NOT tuned yet** (still at default 128 MB) — bumping it requires a postgres restart. Defer to the next maintenance window; if you tune it, pick ≤ 512 MB per instance so the prod + staging pair doesn't pin >1 GB of RAM on this 8 GB host (mind co-tenancy with `pb_postgres`, `pf`, `ha_homeassistant`, etc.).

**Re-applying after a `postgres-data/` wipe** (e.g. weekly-refresh restore destroys `postgresql.auto.conf`): re-run the ALTER SYSTEM block from `docs/deployment/postgres_tuning.md` (or grep this file's table) and `SELECT pg_reload_conf();`. The dual-stack refresh playbook should re-emit these settings as part of the staging-DB rebuild.

## Common mistakes (visa_bulletin-specific)

- **Don't touch `/opt/stack/visa_bulletin/` or `/opt/stack/visa_bulletin_staging/` when adding a new LAN service.** visa_bulletin is the only public production stack on this box. Do not edit either compose file, restart any `vb_*` container, attach those compose projects to `homelab_proxy`, or change `vb_public`. Public ingress (Cloudflare Tunnel → `vb_nginx:80` / `vb_stg_nginx:80` over `vb_public`) must stay exactly as it is. New LAN services are additive: separate compose, separate network, Traefik labels — never a touch on visa_bulletin.

- **Cloudflare-tunnel ingress targets must use container-name aliases, not service-name aliases, when more than one Compose stack shares a network.** Two Compose projects can both declare a service called `nginx`; on a shared external network, the alias `nginx` resolves to whichever container has the service-name alias on that specific network — and a container added to a network via `docker network connect` does NOT get its compose service-name alias on that network. Result: `service: http://nginx:80` may silently route prod traffic to staging. **Always use `vb_nginx` / `vb_stg_nginx` (container_name) in tunnel ingress on the homeserver.** Bug observed 2026-05-08 dual-env build: real `visa-bulletin.us` traffic landed on staging stack for ~30 min before catch.

- Don't suggest `bazel run` for cron jobs on homeserver — there is no Bazel build env on homeserver. Run management/cron commands via `docker exec -w /app vb_web python3 -m <module>` instead.

- Don't suggest changing `ALLOWED_HOSTS` to `*` — it's been explicitly listed (localhost, homeserver.local, 192.168.1.152, visa-bulletin.us, www.visa-bulletin.us, staging.visa-bulletin.us). Add hostnames as needed.

- **Backup expectation:** the homeserver's 64 GB SSD is a single point of failure. Postgres `pg_dump` of `visa_bulletin` should be copied off-box (e.g., to Mac, B2 bucket) on a schedule. **Backup automation is not yet in place — do this before the Lightsail rollback path is deleted.**

## Migration status (visa_bulletin AWS Lightsail → homeserver)

- ✅ DNS cutover 2026-05-08: `visa-bulletin.us` and `www.visa-bulletin.us` now CNAME to tunnel
- ✅ DB migrated (~316 MB compressed dump, 3.9 GB on disk after restore)
- ✅ Hourly bulletin refresh cron migrated; Lightsail crons disabled (commented out, not removed)
- ⏳ Burn-in period in progress — Lightsail kept reachable on `44.209.204.255` for rollback
- ✅ Dual-environment (prod + staging stacks) deployed
- ⏳ Weekly refresh-on-staging-DB-then-flip pattern not yet implemented
- ⏳ Postgres backup automation not yet in place
- ⏳ Lightsail decommission (final snapshot, instance delete, static IP delete) — once burn-in passes
