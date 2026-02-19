# Instance Rotation (Design)

High-level design for rollout (data + interface) by switching traffic between **instances** (e.g. prod VM and staging VM), not between containers on a single instance.

**Current deployment:** One database per instance (`visa_bulletin`). One app stack per instance (`deployment/docker-compose.yml`, web + redis on port 8000). Nginx proxies port 80 → 8000. No same-host blue/green containers. Refresh runs on the inactive instance; traffic switch (DNS or static IP) flips to the refreshed instance.

---

## Current State

- **Prod instance** (prod_2Gb_vm) and **staging instance** (staging_2Gb_vm): each has one PostgreSQL database (`visa_bulletin`) and one app stack (single `deployment/docker-compose.yml`, web + redis on port 8000).
- **Data refresh:** Orchestrator runs on prod, SSHs to **inactive (staging)** instance and runs the pipeline there: ensure_db, drop indexes, incremental ingest, restore indexes, backfills, clustering, VACUUM, start services, warm cache, smoke. No DB swap step; staging has one DB.
- **Traffic switch:** After refresh, traffic is switched to the instance that just ran the pipeline (e.g. static IP or DNS). No `.env` DB swap.
- **Interface deploy:** [scripts/deploy.sh](scripts/deploy.sh) deploys to a host (pull image, compose up -d, health check). For zero-downtime: deploy to the inactive instance, then switch traffic (DNS/static IP).
- **Backup instance** (backup_0_5Gb_vm): testing/failover; [deployment/DOMAIN_SETUP.md](deployment/DOMAIN_SETUP.md) documents manual DNS flip between prod and backup IPs.

---

## Why “Shared Single DB” Conflicts With Current Refresh

Today, refresh is safe for production because:

- Index drops and heavy writes run only on the **inactive** DB.
- The **active** DB (serving traffic) is never touched during refresh.

If we had **one shared database** and two app instances both connected to it:

- There is no “inactive” copy to refresh. Any refresh runs against the only DB.
- Refresh would: drop indexes on the live DB → bulk load → recreate indexes. While that runs, the **active** app instance would see severe degradation (full table scans, lock contention, I/O saturation).
- So: **shared single DB + long-running refresh with index drops** implies either degraded production during refresh or planned maintenance.

So a true “shared single DB” does **not** match the current refresh design without either accepting degradation or a maintenance window. The options below avoid that by keeping a clear “inactive” target for refresh (separate DB or separate instance).

---

## Target: Rollout at Instance Level

- **Instance A** and **Instance B**: each runs app + its own DB (one stack per instance).
- **Rollout** = switch traffic from one instance to the other (DNS or static IP).
- **Data updates:** refresh runs against the inactive instance’s DB; then traffic is switched so users hit the refreshed side.
- **Interface updates:** deploy new image to the inactive instance ([scripts/deploy.sh](scripts/deploy.sh)), health check, then switch traffic to it.

---

## Design Options (Performance, Cost, Practicality)

### Option 1: DB per instance (two full instances) — current approach

**Setup:** Two instances (e.g. 2GB each). Each runs app + PostgreSQL; each has its own DB (no shared DB). One app stack per instance (`deployment/docker-compose.yml`, port 8000).

**Data refresh:** Run on the **inactive** instance. Refresh uses that instance’s local DB: drop indexes, ingest, post-process, recreate indexes, VACUUM. The **active** instance and its DB are untouched.

**Traffic switch:** After refresh (and optional app deploy), flip DNS (or static IP) to the refreshed instance. Can be **automated** as part of the cron'ed refresh script.

**Performance:** No impact on live traffic during refresh. Active instance and its DB are isolated.

**Cost (rough):** 2 × 2GB Lightsail ≈ $20/mo if both run 24/7. **Variant—backup only during refresh:** Start the inactive instance only for the duration of data refresh; after turnover and a **safety interval**, **stop the old instance**. Reduces cost.

**Rollback:** Flip DNS (or static IP) back to the previous instance.

---

## Traffic Switch Mechanism

- **DNS flip:** Change A records for `visa-bulletin.us` / `www` from one instance IP to the other. TTL 300 → ~5 min propagation. Documented in [deployment/DOMAIN_SETUP.md](deployment/DOMAIN_SETUP.md).
- **Static IP reassignment (Lightsail):** Use **one** static IP. Domain A records always point to that IP. The static IP is **attached** to whichever instance is active. To switch: **detach** the static IP from the old instance and **attach** it to the new (refreshed) instance via Lightsail API. No DNS change; cutover is effectively instant.

See the full design in git history (formerly `BLUE_GREEN_INSTANCE_ROLLOUT.md`) for Option 2/3, Namecheap API, automation details, and implementation plan.

---

## Summary

- **One stack per instance:** `deployment/docker-compose.yml` (web + redis on port 8000). No same-host blue/green.
- **Deploy:** [scripts/deploy.sh](scripts/deploy.sh) — deploy to a host; for zero-downtime, deploy to inactive instance then switch traffic.
- **Refresh:** Runs on inactive instance (orchestrator SSHs to staging, runs pipeline there). After success, switch traffic (DNS or static IP).
- **Rollback:** Switch traffic back to the other instance; or deploy previous image with `./scripts/deploy.sh ... <previous-tag>`.
