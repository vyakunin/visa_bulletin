# Blue-Green Instance Rollout (Design)

High-level design for rollout (data + interface) by switching traffic between **instances** (blue VM / green VM), not between containers on a single instance.

---

## Current State

- **Single prod instance** (prod_2Gb_vm – 44.209.204.255, 2GB): blue-green **containers** on ports 8000 (blue) and 8001 (green), one PostgreSQL on the host with **two databases** (`visa_bulletin_blue`, `visa_bulletin_green`), Nginx flips `proxy_pass` between ports.
- **Data refresh** ([scripts/cron/refresh_data.sh](scripts/cron/refresh_data.sh)):
  - Targets the **inactive** database (e.g. `visa_bulletin_green` when app uses blue).
  - Drops non-unique indexes on that DB ([scripts/salary/manage_salary_indexes.py](scripts/salary/manage_salary_indexes.py) `--drop`), runs full ingest + post-processing (cluster job titles, cluster employers, etc.), recreates indexes, VACUUM ANALYZE, warm cache, smoke tests.
  - Long-running (hours on 2GB; ingest + clustering dominate).
  - **Swap:** updates `.env` `DB_NAME` to the refreshed DB and restarts the active container (brief downtime).
- **Interface deploy:** [scripts/deploy-zero-downtime.sh](scripts/deploy-zero-downtime.sh) deploys to the inactive **container set** on the same instance, health check, flips Nginx, stops old containers.
- **Backup instance** (backup_0_5Gb_vm – 3.227.71.176, 0.5GB): testing/failover; [deployment/DOMAIN_SETUP.md](deployment/DOMAIN_SETUP.md) documents manual DNS flip between prod and backup IPs.

---

## Why “Shared Single DB” Conflicts With Current Refresh

Today, refresh is safe for production because:

- Index drops and heavy writes run only on the **inactive** DB.
- The **active** DB (serving traffic) is never touched during refresh.

If we had **one shared database** and two app instances (blue VM, green VM) both connected to it:

- There is no “inactive” copy to refresh. Any refresh runs against the only DB.
- Refresh would: drop indexes on the live DB → bulk load → recreate indexes. While that runs:
  - The **active** app instance would see severe degradation (full table scans, lock contention, I/O saturation).
- So: **shared single DB + long-running refresh with index drops** implies either:
  - **Degraded production** during refresh, or
  - **Planned maintenance** (take app offline or read-only during refresh).

So a true “shared single DB” does **not** match the current refresh design without either accepting degradation or a maintenance window. The options below avoid that by keeping a clear “inactive” target for refresh (separate DB or separate instance).

---

## Target: Blue-Green at Instance Level

- **Blue instance** and **Green instance**: each runs app (and optionally its own DB).
- **Rollout** = switch traffic from one instance to the other (DNS or load balancer).
- **Data updates:** refresh runs against an inactive target (inactive DB or inactive instance’s DB); then traffic is switched so users hit the refreshed side.
- **Interface updates:** deploy new image to the inactive instance, health check, then switch traffic to it.

---

## Design Options (Performance, Cost, Practicality)

### Option 1: DB per instance (two full instances)

**Setup:** Two instances (e.g. 2GB each). Each runs app + PostgreSQL; each has its own DB (no shared DB).

**Data refresh:** Run on the **inactive** instance (e.g. green VM). Refresh uses that instance’s local DB: drop indexes, ingest, post-process, recreate indexes, VACUUM. The **active** instance (blue VM) and its DB are untouched.

**Traffic switch:** After refresh (and optional app deploy), flip DNS (or LB) from blue to green. Green instance (with fresh data) serves traffic. This can be **automated** as part of the cron'ed refresh script (see [Automating the traffic switch in refresh](#automating-the-traffic-switch-in-refresh)).

**Performance:** No impact on live traffic during refresh. Active instance and its DB are isolated.

**Cost (rough):** 2 × 2GB Lightsail ≈ $20/mo if both run 24/7 (vs current single 2GB ≈ $10/mo). **Variant—backup only during refresh:** Start the backup (inactive) instance only for the duration of data refresh; after turnover (DNS/LB flip) and a **safety interval** (e.g. 30 min) when the new instance is confirmed functional, **stop the old instance**. So two instances run only during refresh + safety window (e.g. a few days per month), reducing cost. Lightsail bills by hour, so running the second instance only part of the month lowers the bill. Backup (0.5GB) can stay for non–blue-green failover or be removed.

**Practicality:** Matches current refresh mental model (inactive target, then swap). Requires two instances capable of running full refresh (backup at 0.5GB is too small; resize to 2GB or add a second 2GB). If using the “backup only during refresh” variant: cron or a scheduled job must start the inactive instance before refresh, then after the safety interval stop the old instance (or do it manually). Attach **static IPs** to both instances so DNS A records stay valid when instances are stopped/started.

**Rollback:** Flip DNS back to the previous instance.

---

### Option 2: Blue-green databases, shared PostgreSQL host

**Setup:** One PostgreSQL **server** (one instance or managed DB) with **two databases** (`visa_bulletin_blue`, `visa_bulletin_green`). Two **app** instances (blue VM, green VM); blue app → blue DB, green app → green DB. No app instance runs PostgreSQL; both connect to the shared PG host.

**Data refresh:** A “runner” (e.g. the **inactive** app instance, or a dedicated cron host) connects to the shared PG host and runs refresh against the **inactive** DB only (e.g. green DB while traffic is on blue VM → blue DB). Index drops and bulk load touch only the inactive DB; active DB is untouched.

**Traffic switch:** After refresh, flip DNS (or LB) from blue VM to green VM. Green VM (green DB) serves traffic. Can be **automated** in the refresh script (see [Automating the traffic switch in refresh](#automating-the-traffic-switch-in-refresh)).

**Performance:** The **shared PostgreSQL host** is under heavy CPU and memory load during refresh (index drops, bulk loads, VACUUM). The active app instance (other VM) still hits that same host for reads/writes, so prod traffic can be impacted during peak indexing/ingest—slower queries or timeouts. To minimize impact, run refresh during low-traffic windows or size the DB host for concurrent refresh + live load.

**Cost:** 1 × DB host (e.g. 2GB ≈ $10/mo) + 2 × app instances (e.g. 1GB each ≈ $10/mo if smaller, or 2× 2GB if you keep 2GB for safety). Total roughly $20–30/mo. Alternatively, one “fat” instance runs PostgreSQL (two DBs) + one app (blue), and a second instance runs only the app (green) and connects to the first for DB; refresh runs on green instance against green DB.

**Practicality:** Reuses current two-DB refresh logic; only the “where refresh runs” and “where app runs” change. Requires network access from runner to DB host and correct `DB_NAME` / `DB_HOST` so refresh targets the inactive DB only.

**Rollback:** Flip DNS back to the previous instance (previous DB remains as-is).

---

### Option 3: Shared single DB + accept degradation during refresh

**Setup:** One PostgreSQL DB. Two app instances (blue VM, green VM) both connect to it.

**Data refresh:** Run refresh (drop indexes, ingest, recreate) against the single DB during **low-traffic** periods (e.g. night). Do **not** take the app offline. The active app instance will see slow queries and possible timeouts during index drop and bulk load.

**Traffic switch:** For interface: deploy to inactive instance, flip DNS. For data: no switch; same DB is refreshed in place.

**Performance:** Production is **degraded** during refresh (hours). Acceptable only if traffic is low and latency/errors are tolerable.

**Cost:** Lowest (one DB, two app instances; no extra “inactive” DB or second full instance for DB).

**Practicality:** Easiest to implement from an infra perspective; hardest from a UX/reliability perspective. Not recommended unless refresh is very rare and impact is acceptable.

**Rollback:** For app deploy: flip DNS back. For bad refresh: restore DB from backup and fix.

---

## Traffic Switch Mechanism

- **DNS flip (already in use):** Change A records for `visa-bulletin.us` / `www` from IP-blue to IP-green (or vice versa). TTL 300 → ~5 min propagation. Documented in [deployment/DOMAIN_SETUP.md](deployment/DOMAIN_SETUP.md). The switch **must** be part of (or fully automated by) the cron data refresh—not manual. After refresh and smoke tests pass, the script calls the registrar/DNS API to point the domain at the refreshed instance (see [Namecheap API](#namecheap-api) below).
- **Load balancer (e.g. Lightsail LB):** Domain points to the LB; the LB forwards traffic to the **attached** instance(s). Switch = detach the old instance from the LB and attach the new (refreshed) instance via AWS API/CLI (`DetachInstancesFromLoadBalancer`, `AttachInstancesToLoadBalancer`). Cutover is immediate (no DNS propagation). **Cost:** Lightsail LB is **$18/month** flat (no per-request or bandwidth charge). Not included in free tier.

- **Static IP reassignment (Lightsail):** Use **one** static IP (e.g. the current prod IP). Domain A records always point to that IP. The static IP is **attached** to whichever instance is active (blue or green). To switch: **detach** the static IP from the old instance and **attach** it to the new (refreshed) instance via Lightsail API/CLI (`DetachStaticIp`, `AttachStaticIp`). No DNS change—the same IP now routes to the new instance. Lightsail supports this: [DetachStaticIp](https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-create-static-ip.html), [AttachStaticIp](https://docs.aws.amazon.com/cli/latest/reference/lightsail/attach-static-ip.html).

### DNS switch vs static IP reassignment

| Criterion | DNS switch (Namecheap API) | Static IP reassignment (Lightsail API) |
|----------|----------------------------|----------------------------------------|
| **Cutover** | TTL propagation (e.g. ~5 min); some users may hit old instance until caches expire | Effectively instant (IP moves to new instance; routing updates in seconds) |
| **DNS** | A records change (IP_blue ↔ IP_green); need getHosts/setHosts with full record list | A records never change (one IP forever); no DNS API needed |
| **Credentials** | Namecheap API user/key + whitelisted IP | AWS/Lightsail credentials (many setups already have these) |
| **Failure mode** | Wrong A record = wrong instance until next flip; risk of overwriting other records (MX, TXT) if setHosts is wrong | Detach/attach in wrong order = brief unreachability; IP must stay in same region |
| **Cost** | No extra cost (registrar API) | One static IP (same as today); inactive instance needs no static IP for traffic (optional second IP for SSH/management) |
| **Operational** | Script: getHosts → modify A for @ and www → setHosts | Script: DetachStaticIp (from old) → AttachStaticIp (to new). Brief window when IP is unattached (few seconds) unless Lightsail allows attach-before-detach for same IP (check docs). |

**Pros of static IP reassignment:** Instant cutover; no Namecheap API or DNS propagation; domain always points to same IP; only AWS credentials needed. **Cons:** Brief unreachability during detach/attach window (order: detach from old, then attach to new) unless the provider allows a seamless move; need to verify Lightsail behavior (e.g. can the same static IP be attached to a different instance without a gap).

**Pros of DNS switch:** No change to Lightsail (each instance keeps its own static IP); DNS is the single place that decides which instance is live. **Cons:** Up to ~5 min propagation; need Namecheap API and getHosts/setHosts care (do not drop MX/TXT).

Recommendation: **Static IP reassignment** is preferable if you want instant cutover and already use Lightsail (one static IP, move it via API). **DNS switch** is preferable if you want to avoid any detach/attach gap or prefer not to touch instance networking in the switch.

### Automating the traffic switch in refresh

Yes. The traffic switch can be run **automatically** at the end of the cron'ed data refresh script (e.g. [scripts/cron/refresh_data.sh](scripts/cron/refresh_data.sh)), after all steps succeed and smoke tests pass.

**Flow:** Refresh runs on the inactive instance (Option 1) or against the inactive DB (Option 2) → smoke tests pass → script calls DNS or LB API to point the domain at the refreshed instance → exit. No manual flip.

**Prerequisites:**

- **DNS:** Registrar or DNS provider exposes an API so the cron script can update A records. API credentials (e.g. token) must be available to the cron job (env vars or secret store on the instance or runner). Script updates A records for `visa-bulletin.us` / `www` to the IP of the refreshed instance. See [Namecheap API](#namecheap-api) for our setup.
- **LB:** If using a load balancer, script calls the cloud API (e.g. Lightsail `AttachInstancesToLoadBalancer` / `DetachInstancesToLoadBalancer`) to attach the refreshed instance and detach the old one. AWS credentials must be available to the script.

#### Namecheap API

We use **Namecheap**. Namecheap provides an API suitable for automated A record updates: [API intro](https://www.namecheap.com/support/api/intro/), [API knowledge base](https://www.namecheap.com/support/knowledgebase/subcategory/63/namecheap-api/).

**Caveat:** The command `namecheap.domains.dns.setHosts` **overwrites all DNS host records** for the domain; it does not patch a single A record. So the script must: (1) call `namecheap.domains.dns.getHosts` to fetch all current records, (2) change the A record(s) for `@` and `www` to the refreshed instance IP, (3) call `namecheap.domains.dns.setHosts` with the full list. Losing or reordering other records (e.g. MX, TXT) must be avoided.

**Setup:** Enable API in Namecheap (Profile → Tools → Namecheap API Access), whitelist the IP from which the cron runs (API requests are rejected otherwise), and provide API user/key to the script via env or secret store.

**Safety:**

- Only flip **after** refresh and smoke tests succeed (same as today's swap step). If smoke tests fail, do not flip; leave traffic on the current instance.
- Optional: after flipping, run a short health check against the new instance (e.g. `curl` key URLs). On failure, automatically flip back (rollback) and log/alert.

**Propagation:** With DNS, TTL (e.g. 300 s) means some users may still hit the old instance for a few minutes. With LB, cutover is immediate.

---

## Comparison Summary

| Criterion        | Option 1: DB per instance | Option 2: Blue-green DBs, shared PG host | Option 3: Shared DB + degradation |
|-----------------|----------------------------|------------------------------------------|-----------------------------------|
| **Live impact during refresh** | None                       | DB host under load; prod queries can slow | Degraded (slow, timeouts)         |
| **Matches current refresh design** | Yes (inactive DB on inactive instance) | Yes (inactive DB on shared host)        | No                                |
| **Cost (approx)**               | 2× 2GB ≈ $20/mo (or less if backup only during refresh + safety window) | 1× DB + 2× app ≈ $20–30/mo               | Lowest                            |
| **Operational complexity**      | Low (two symmetric stacks) | Medium (DB host + two apps + refresh runner) | Low                                |
| **Rollback (data)**             | Flip DNS back              | Flip DNS back                            | Restore DB                        |
| **Rollback (interface)**        | Flip DNS back              | Flip DNS back                             | Flip DNS back                     |

---

## Recommended Direction

- **Option 1 (DB per instance)** or **Option 2 (blue-green DBs, shared PG host)** both keep "refresh inactive target, then switch." Option 1 has zero impact on live traffic; Option 2 can impact prod during peak refresh (DB host load). Choose Option 1 for maximum isolation and simplicity; choose Option 2 if you want a single DB host and accept scheduling refresh during low-traffic or sizing the DB host for concurrent load.
- **Option 3** (shared DB + degradation) is only reasonable for very low traffic and rare refresh; otherwise avoid.

---

## Prerequisites (non‑negotiable)

- **Full automation:** The end-to-end data refresh process must be **fully automated**. A single cron job (or cron-triggered pipeline) must run the whole process: start inactive instance (if stopped) → refresh → smoke tests → DNS switch → safety interval → stop old instance. Runbooks are nice to have for manual recovery; they do **not** replace the requirement for an end-to-end automated cron job.
- **No significant downtime or degradation:** We do not want more than a few seconds of downtime or noticeable performance degradation for users. So refresh must run on an **inactive** instance (or inactive DB); the active instance serving traffic must be untouched during refresh. Traffic switch (DNS) can take up to TTL (e.g. 5 min) to propagate; the new instance is already up before the flip, so there is no server-side downtime.

With these prerequisites, **only Option 1 (DB per instance)** is acceptable: Option 2 shares a DB host that is under heavy load during refresh (prod queries can slow); Option 3 degrades prod. Option 1 isolates the active instance completely.

---

## Final design

- **Option 1:** Two instances (blue, green), each with app + PostgreSQL and its own DB. No shared DB.
- **Traffic switch:** DNS only (Namecheap API). No load balancer (saves $18/mo; DNS TTL ~5 min is acceptable).
- **Turn off unused instance:** The non-serving instance is **not** kept running 24/7. It is in one of three states:
  - **Staging:** Left running when we want to try new code or data (manual or scheduled).
  - **Active (refresh + short backup):** Running during data refresh and for a short period (e.g. 30 min) after DNS switch as a live backup; then stopped.
  - **Stopped:** Off when not needed to save cost.
- **Fully automated cron:** One cron job runs the full cycle: start inactive instance (if stopped) → wait until healthy → run data refresh on it → smoke tests → DNS flip to refreshed instance → wait safety interval (30 min) → stop the old instance.

---

## Detailed implementation plan

### 1. Instance topology

- **Two Lightsail instances**, each 2GB RAM (or resize existing backup to 2GB). Name them e.g. `visa-bulletin-blue` and `visa-bulletin-green`.
- **Static IP** attached to each instance (Lightsail retains the IP when the instance is stopped so DNS A records remain valid when the instance is started again).
- **One app stack per instance:** One Docker Compose file (e.g. `docker-compose.yml` or `docker-compose.prod.yml`) per instance: app (Gunicorn) + PostgreSQL + Redis (if used). Single port (e.g. 8000) per instance. Nginx on each instance proxies to localhost:8000. No blue/green **containers** on the same host (remove current 8000/8001 flip on one machine).
- **SSH access:** Cron runner (one of the instances or a separate small runner) can SSH to both instances and call Lightsail API (or AWS CLI) to start/stop the other instance. Alternatively, cron runs on the **active** instance and starts/stops the **inactive** one via API.

### 2. Determining active vs inactive

- **Active** = the instance whose IP the domain currently points to (query Namecheap API `getHosts` or DNS resolve for `visa-bulletin.us` → get IP; map IP to blue or green).
- **Inactive** = the other instance. Refresh always runs on the inactive instance. After refresh and DNS flip, the former inactive becomes active and the former active becomes inactive; after the safety interval the (now inactive) instance is stopped.

### 3. Cron job: start inactive instance (if stopped)

- Call Lightsail API (or AWS CLI) to get state of the inactive instance. If state is **stopped**, call **StartInstance** (or equivalent). Wait until instance state is **running**.
- Optional: wait for SSH to be reachable (e.g. retry loop with backoff). Then wait for application health: e.g. `curl -f http://<inactive-ip>:80/` or `:8000/` (or Nginx on 80) returns 200. Timeout e.g. 5–10 minutes. If health check fails, abort and alert (do not proceed to refresh).
- If the inactive instance was already running (e.g. staging), skip start and proceed.

### 4. Cron job: run data refresh on inactive instance

- **Option A (refresh run on active instance, targets inactive via SSH):** On the **active** instance, a script SSHs into the **inactive** instance and runs the full refresh there (so all ingest, index drop, post-process, VACUUM run on the inactive instance's local PostgreSQL). The active instance's DB is never touched.
- **Option B (refresh run on inactive instance):** Cron is triggered on the **inactive** instance (e.g. by a scheduler that wakes the instance first, or by running cron on the active instance that SSHes to inactive and runs a remote command). The refresh script runs locally on the inactive instance (same as today's [scripts/cron/refresh_data.sh](scripts/cron/refresh_data.sh) but with a single DB on that host, no "second DB" swap on same host).
- Prefer **Option B** if the inactive instance is already up (simpler: one host, one DB, same script as today minus the DB-name swap). Option A is valid if the "runner" is always the active instance and it drives the inactive via SSH.
- Refresh steps (unchanged in logic): create/use one DB on inactive instance, drop indexes, ingest, post-process, recreate indexes, VACUUM, warm cache, smoke tests. No "swap DB name and restart container" on same host—instead, after success we do a **DNS** switch so traffic goes to the inactive instance (which now has the fresh DB).

### 5. Cron job: smoke tests

- Run smoke tests against the **inactive** instance (e.g. curl key URLs, check record counts via API or DB). If any fail, **abort**: do not flip DNS, do not stop the old instance. Alert and exit. Optionally retry or leave for manual intervention.

### 6. Cron job: DNS switch (Namecheap API)

- Call Namecheap `namecheap.domains.dns.getHosts` for the domain (SLD/TLD e.g. `visa-bulletin` / `us`). Get current host records.
- Update the A records for `@` and `www` to the **inactive** instance's static IP (the one we just refreshed).
- Call `namecheap.domains.dns.setHosts` with the full list of host records (so MX, TXT, etc. are preserved). API credentials and whitelisted IP must be set (see [Namecheap API](#namecheap-api)).
- After this, the refreshed instance is **active** (traffic will flow to it as DNS propagates, TTL e.g. 300 s). The old instance is now **inactive**.

### 7. Cron job: safety interval, then stop old instance

- Sleep (e.g. 30 minutes). Optionally re-check that the new active instance is still healthy (curl key URLs).
- Call Lightsail API (or AWS CLI) to **stop** the old (now inactive) instance. This saves cost; the instance can be started again at the next refresh cycle or for staging.

### 8. Single end-to-end script or pipeline

- Implement one script (e.g. `scripts/cron/refresh_and_switch.sh` or split into steps called by an orchestrator) that: (1) resolves current active/inactive from DNS, (2) starts inactive if stopped, (3) waits for inactive healthy, (4) runs refresh on inactive (via SSH or on inactive), (5) runs smoke tests on inactive, (6) flips DNS via Namecheap API, (7) waits safety interval, (8) stops old instance. All steps must be automated; no manual steps in the happy path.
- Cron entry (e.g. weekly): run this script at the desired time (e.g. Sunday 2 AM). Log output and exit codes; on failure, alert and do not flip DNS or stop the old instance.

### 9. Namecheap API integration

- **Credentials:** Store Namecheap API user and key in env vars or a secret store accessible to the cron runner. Whitelist the cron runner's outbound IP in Namecheap (Profile → Tools → API Access).
- **getHosts/setHosts:** Implement a small helper (Python or shell calling curl) that: gets all host records, modifies A for `@` and `www` to the target IP, calls setHosts with the full list. Handle errors (e.g. API rate limit, auth failure) and log; do not flip if setHosts fails.

### 10. AWS credentials for Lightsail API (static IP reassignment or start/stop)

If the cron job (or any script) must call Lightsail API—e.g. **static IP reassignment** (detach/attach), **start/stop instances**—that environment needs AWS credentials. **Lightsail instances do not support IAM instance roles** (unlike EC2); you must provide IAM user credentials.

- **Local/CI:** Use the **`visa-bulletin-deploy`** IAM user and profile (see [.cursor/rules/deployment.mdc](.cursor/rules/deployment.mdc) → "AWS IAM and Lightsail CLI"). Set `AWS_PROFILE=visa-bulletin-deploy` (or configure secrets in CI).
- **Cron runs on an instance:** On that instance, configure AWS CLI with credentials for an IAM user that has Lightsail permissions (e.g. reuse `visa-bulletin-deploy` or a dedicated user). Store the access key and secret in a file or env **outside the repo** (e.g. `/opt/visa_bulletin/.aws-credentials` not in git, or env vars from a secret). Use `AWS_PROFILE=...` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in the cron script when calling `aws lightsail attach-static-ip`, `detach-static-ip`, `start-instance`, `stop-instance`.
- **Instance rename:** Lightsail does not support renaming instances after creation. Use static IP reassignment (move the prod static IP to the refreshed instance) or DNS switch (point domain to the other instance’s IP); see [.cursor/rules/deployment.mdc](.cursor/rules/deployment.mdc) → "Giving instances (or cron runner) AWS privileges".

### 11. Interface (code) deploys

- To deploy new code: start the inactive instance (if stopped), deploy new image to it (pull, migrate, health check), then run the same DNS flip + safety interval + stop old instance flow (or a separate "deploy and switch" script that reuses the DNS flip and stop logic). No data refresh needed for code-only deploys; the inactive instance can start from its existing DB (or from a copy if desired). Downtime: none beyond DNS propagation (new instance is up before flip).

### 12. Staging use of inactive instance

- When not running a refresh, the inactive instance can be **started manually** (or by a separate schedule) and used as a staging environment (try new code, run ad-hoc scripts). Before the next scheduled refresh, either leave it running (cron will use it as inactive and run refresh on it) or stop it (cron will start it at the beginning of the cycle). Document that the "inactive" instance is the one not pointed to by DNS.

### 13. Rollback

- **Before DNS flip:** If refresh or smoke tests fail, do nothing; active instance is unchanged. Fix and re-run or investigate.
- **After DNS flip:** If the new instance has issues, flip DNS back to the old instance's IP (Namecheap API again). The old instance may still be running (within the 30 min window) or may need to be started (Lightsail API) and then DNS flipped back. Document rollback steps in a runbook.

### 14. Deprecate current same-host blue-green

- Remove or simplify [scripts/deploy-zero-downtime.sh](scripts/deploy-zero-downtime.sh) (no Nginx port flip on one host). Use one compose file per instance. Update [scripts/cron/refresh_data.sh](scripts/cron/refresh_data.sh) or replace with the new end-to-end script that runs refresh on the inactive instance (single DB on that host) and then triggers DNS switch + stop-old logic.

### 15. Docs and rules

- Update [deployment/README.md](deployment/README.md), [docs/deployment/ROLLOUT_FLOW.md](docs/deployment/ROLLOUT_FLOW.md), [.cursor/rules/deployment.mdc](.cursor/rules/deployment.mdc), [deployment/DOMAIN_SETUP.md](deployment/DOMAIN_SETUP.md): describe Option 1, turn-off-unused-instance, DNS-only switch, and the fully automated cron flow. Document instance names, static IPs, and the single end-to-end script.

---

## Implementation outline (summary)

1. **Decide and document:** Option 1, DNS-only switch, instance roles and static IPs (blue, green).
2. **Per-instance app:** One app stack per instance (one compose file, one port). Traffic switch at DNS only.
3. **End-to-end cron:** Single script runs start inactive (if stopped) → refresh → smoke tests → DNS flip → safety interval (30 min) → stop old instance. Fully automated; no manual steps in happy path.
4. **Traffic switch:** Namecheap API (getHosts → modify A for @ and www → setHosts). Must be part of the cron job, not a runbook-only step.
5. **Docs and rules:** Update deployment README, rollout flow, deployment rules, DOMAIN_SETUP; document Option 1, turn-off-unused-instance, and the end-to-end script.

See [Detailed implementation plan](#detailed-implementation-plan) above for full step-by-step plan.

---

## Diagram (Options 1 vs 2)

**Option 1 – DB per instance:**

```
                    DNS or LB
                        |
         +--------------+--------------+
         |                             |
    [Instance Blue]              [Instance Green]
    App + PostgreSQL             App + PostgreSQL
    DB: visa_bulletin            DB: visa_bulletin
    (active or inactive)         (active or inactive)
    Refresh runs here when       Refresh runs here when
    this is inactive             this is inactive
```

**Option 2 – Blue-green DBs, shared PG host:**

```
                    DNS or LB
                        |
         +--------------+--------------+
         |                             |
    [Instance Blue]              [Instance Green]
    App only                      App only
         |                             |
         +--------------+--------------+
                        |
                 [PostgreSQL host]
                 DB: visa_bulletin_blue
                 DB: visa_bulletin_green
                 Refresh (runner) targets
                 inactive DB only
```

---

## Open Decisions

- **Chosen:** Option 1 (DB per instance) + turn off unused instance. No load balancer.
- **Traffic switch:** Choose one: **DNS switch** (Namecheap API; ~5 min propagation) or **static IP reassignment** (Lightsail API; one static IP, detach from old instance and attach to new; effectively instant cutover, no DNS change). See [DNS switch vs static IP reassignment](#dns-switch-vs-static-ip-reassignment) for pros/cons.
- **Remaining:** Resize backup to 2GB and use prod + backup as blue/green, or add a second 2GB instance and keep backup for other uses? Instance names. If DNS switch: which instance gets which static IP (both keep IPs). If static IP reassignment: one static IP that moves; inactive instance may have a second IP for SSH or use dynamic IP when running.

This document is the single source for the high-level design; iterate here and then reflect changes in implementation and runbooks.
