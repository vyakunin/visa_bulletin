# Graduation Known Issues

This file is maintained alongside `deployment.mdc`. Each time the orchestrator hits a new failure mode, a "Known issues from YYYY-MM-DD graduation" entry is added here with the fix or workaround.

**Rule:** Always persist critical graduation/pipeline findings here, not only in agent output. Agent outputs are not preserved across sessions.

---

## Known issues from 2026-02-21 graduation

- **AWS CLI timeout:** `attach-static-ip` can take >30s. Fixed: timeout increased to 120s in `traffic_switch.py`. The operation succeeds server-side even if CLI times out, leaving the orchestrator in an inconsistent state (IP swapped but post-switch steps skipped).
- **Stale Docker `:latest` image:** The `:latest` image is from Dec 2025, before enum migrations. **DO NOT remove the `../:/app` volume mount from prod** until a fresh image is built and pushed (push to `prod` branch triggers GitHub Actions rebuild). Without the volume mount, the baked-in image code will crash with `DataError: invalid input syntax for type integer: "all"` on the Country enum.
- **docker-compose 1.29.2 ContainerConfig bug:** `docker-compose up -d` can hit `KeyError: 'ContainerConfig'` killing the running container. Workaround: `docker rm -f <name>` then `docker-compose up -d`. The orchestrator's `prod-safe override` step must handle this.

---

## Known issues from 2026-03-18 graduation

- **Inter-instance SSH via public IP fails:** Lightsail instances cannot SSH to each other using public IPs. **FIXED in code:** set `REFRESH_INACTIVE_PRIVATE_IP` and `REFRESH_ACTIVE_PRIVATE_IP` in `.env` to the private IPs (Lightsail console → instance → Networking → Private IP). The orchestrator now uses these for SSH and automatically swaps them on graduation. Private IPs survive stop/start. VisaBulletin2GB private IP: `172.26.13.90`. VisaBulletinStaging private IP: check console.
- **Nginx default-server `$host` escaping bug:** If `/etc/nginx/sites-enabled/default-server` was created manually via SSH (heredoc/echo), `$host` may have been written as `\$host`. nginx sends a literal backslash in the Host header, which Django rejects with `DisallowedHost`. Fix: `sudo cp deployment/nginx/default-server.conf /etc/nginx/sites-enabled/default-server && sudo nginx -s reload`.
- **Wrong git branch on inactive host → wrong Docker image tag (FIXED):** The orchestrator derives the image tag as `<branch>-<sha>` from the current branch on the inactive host. If the inactive host is on `prod` or a stale staging commit, it pulls the wrong Docker image. Fixed: `--from-step` path now runs `step_sync_code` (git fetch + reset --hard origin/staging) before `start_remote_services`, matching what the normal pipeline does. The `prod-` branch guard in `start_remote_services` remains as a safety net.

---

## Known issues from 2026-04-16 graduation

- **Lightsail burst capacity: freshly-started instances have 0 CPU credits.** 2GB Lightsail instances are t-class (burstable). Baseline is ~20% of 1 vCPU. After stop/start, burst credits are 0 — the instance is CPU-throttled to baseline. A single uncached employer-profile page with Plotly chart generation saturates baseline CPU, causing every subsequent request to queue and timeout. **Mitigation:** (1) Start the staging instance at least 2-3 hours before graduation so it accumulates burst credits. (2) Run `warm_cache` to populate Redis BEFORE the instance takes production traffic. (3) Do NOT stop the staging instance immediately after graduation — leave it running to accumulate credits for the next cycle, or at minimum keep it running for 2+ hours after any start.
- **Cache-cold instance + bot traffic = immediate overload.** After graduation, all Django/Redis caches are cold. Bots (GPTBot, Amazonbot, Applebot, Googlebot) immediately hit expensive employer/salary pages (5-12s each uncached). With WEB_CONCURRENCY=1 on a throttled instance, every request blocks. **Fix:** Always run `warm_cache` on the staging instance before graduation. Consider increasing `WEB_CONCURRENCY` to 2 if memory allows (monitor via `docker stats`).

---

## Known issues from 2026-03-21

- **`git push staging:prod` silently failed — instances on stale code (FIXED):** No GitHub credentials on instances meant `_update_git_branch_on_new_prod()` logged a warning and then fetched stale `origin/prod`, leaving both instances on old code after graduation. Fixed: (1) deploy key added to both instances (`/home/ubuntu/.ssh/github_deploy_key`), git remote switched to SSH; (2) orchestrate.py now logs an error and keeps instance on `staging` branch (correct code) rather than checking out stale `origin/prod` when push fails.

---

## Known issues from 2026-03-20 graduation

- **Smoke test HTTP 400 (FIXED):** `_run_http_smoke_tests` used `runner.host` as the `Host:` header. When the orchestrator uses private IP SSH, `runner.host = 172.26.x.x` (private IP) which is NOT in `ALLOWED_HOSTS`. Fixed: always use `localhost` as the host header.
- **`switch_traffic_static_ip` not idempotent (FIXED):** If graduation fails AFTER the IP swap and is re-run, it failed with "VisaBulletin-StaticIP is already attached to VisaBulletin2GB". Fixed: `traffic_switch.py` now does an idempotency pre-check and treats "already attached to target" as success.
- **`update_env` doesn't add new keys (FIXED):** `RemoteRunner.update_env` used `sed` which returns 0 even when no substitution happens, so the `||` fallback never triggered. New keys like `REFRESH_ACTIVE_PRIVATE_IP` were never appended. Fixed: use `grep -q` to check existence first.
- **ContainerConfig bug in prod-safe override (FIXED in code):** `_write_prod_safe_override` runs `docker-compose up -d` after writing the override. docker-compose 1.29.2 hits `KeyError: 'ContainerConfig'` on containers that have exited and have stale metadata. Fixed: force-remove exited web containers before `up -d`.
- **Stale Docker image → 500 after prod-safe override:** The prod-safe override removes the `../:/app` volume mount, causing the container to use the baked-in Docker image. If the image is old (pre-enum migration), it crashes with `DataError: invalid input syntax for type integer: "all"`. **Workaround until fresh image is built:** restore volume mount in `docker-compose.override.yml` and restart.
- **certbot `-d` flag syntax (FIXED):** certbot rejects multiple domains passed to a single `-d` flag. Fixed: `setup_https_on_remote` now uses separate `-d domain` for each domain.
- **`REFRESH_STAGING_STATIC_IP_NAME` not set in orchestrator env → staging IP not reassigned after graduation:** Ensure this env var is in `.env` on the orchestrator host before graduation.

---

## Known issues from 2026-03-19 graduation fix session

- **Post-swap `.env` writes wrong IPs (FIXED):** `orchestrate.py` was writing `REFRESH_ACTIVE_INSTANCE_IP` = staging static IP and `REFRESH_INACTIVE_INSTANCE_IP` = prod static IP after graduation — both backwards. Fixed: IPs are now correctly assigned.
- **Corrupted `.env` from partial runs:** If the orchestrator crashes between `.env` update steps, `.env` can be left in a half-swapped state. The orchestrator now validates `.env` against actual AWS state at startup. Recovery: correct `.env` REFRESH_ACTIVE/INACTIVE_* vars to match what `aws lightsail get-static-ips` reports.
- **`case_submitted` NULL on new staging after graduation:** After graduation, the new staging (old prod) has salary records with NULL `case_submitted` because the old prod was running before `populate_case_submitted` was in the pipeline. A normal pipeline run on the new staging will fix this automatically — `populate_case_submitted` is NOT in the skip-when-zero-ingested set, runs in-place from DOL files on disk, and takes ~30 min. The smoke tests now enforce a 65% minimum coverage floor (`MIN_CASE_SUBMITTED_PERCENT`) to block graduation if this step fails. Current healthy prod baseline: ~74% overall (100% for FY2018-2024, ~26% for FY2025 partial files, 0% pre-2018).
