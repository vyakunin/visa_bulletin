# Pipeline Runbook

> ⚠️ **MOSTLY RETIRED (2026-06-20).** This runbook describes the **AWS/Lightsail
> cross-instance blue/green graduation** orchestrator (`refresh_and_switch.py` +
> `scripts/cron/refresh/{instance,traffic_switch,orchestrate}.py`), which was
> **deleted** when Lightsail was retired (prod is now a self-hosted homeserver
> behind a Cloudflare Tunnel). The sections about the orchestrator, traffic
> switch, static-IP swap, post-swap graduation, and emergency rollback no longer
> apply. **Current deploy + data-refresh:** `.claude/rules/deployment.md`,
> `.claude/rules/branching.md`, and the private VB platform repo
> `~/cursor_projects/visa_bulletin_platform/hosting/` (zero-downtime
> `cutover.sh --code <sha>` / `cutover.sh --data`). Still valid + host-agnostic
> below: the **Pipeline Steps** list, the **Job Title Coherence Smoke Test**, and the
> bug-fix/process notes. The orchestrator-specific sections are retained only until
> a homeserver staging-flip runbook replaces them (ticket 36662b8d).

Operational guide for the refresh/flipover pipeline. Covers status checking, resuming from failures, common failure modes per step, and escalation.

## Quick Reference

```bash
# Check if pipeline is running on staging
ssh staging_2Gb_vm "ps aux | grep refresh_and_switch | grep -v grep"

# View current stage progress
ssh staging_2Gb_vm "tail -50 /tmp/refresh_stage.log"

# Check checkpoint (last completed step)
ssh staging_2Gb_vm "cat /opt/visa_bulletin/backups/refresh_checkpoint.json"

# Resume from checkpoint after fixing an issue
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  ./bazel-bin/scripts/cron/refresh_and_switch --resume --no-traffic-switch"

# Full run (no traffic switch, first validation)
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  nohup ./bazel-bin/scripts/cron/refresh_and_switch --no-traffic-switch > /tmp/orchestrator.log 2>&1 &"
```

---

## Pipeline Steps (in order)

| # | Step | Timeout | What It Does |
|---|------|---------|--------------|
| 1 | `build_pipeline_binaries` | 2h | Runs `build_all.sh` on target host |
| 2 | `ensure_db` | — | Creates DB if missing, runs migrations |
| 3 | `index_snapshot_saved` | — | Drops indexes, saves snapshot for later restore |
| 4 | `ingest_complete` | 12h | `discover-and-ingest --all-domains` |
| 5 | `backfill_job_title_links` | 8h | Links salary records → job title entities |
| 6 | `backfill_source_file_date` | 8h | Backfills source file dates on records |
| 7 | `cluster_job_titles` | 8h | Clusters raw job titles into JobTitle/JobTitleCluster |
| 8 | `indexes_restored` | — | Recreates indexes from snapshot (or fallback) |
| 9 | `update_employer_stats` | 8h | Updates employer statistics |
| 10 | `cluster_employers` | 24h | Clusters employers (heaviest step) |
| 11 | `update_job_title_cluster_stats` | 8h | Updates cluster stats (canonical_title, total_filings) |
| 12 | `populate_job_title_slugs` | 8h | Generates URL slugs for job title clusters |
| 13 | `vacuum_analyze` | — | PostgreSQL VACUUM ANALYZE |
| 14 | `start_services` | — | Starts Redis + Gunicorn (Docker compose) |
| 15 | `warm_cache` | — | Warms Django cache |
| 16 | `smoke_tests` | — | Validates record counts, clustering, slugs |

Steps 5–12 are **skipped** when 0 sources were ingested (data already in DB), unless self-heal triggers (0 clustered employers + ≥100k records).

---

## Checking Pipeline Status

### Is it running?

```bash
ssh staging_2Gb_vm "ps aux | grep -E 'refresh_and_switch|run_pipeline|cluster' | grep -v grep"
```

### Current step?

```bash
# Checkpoint shows last COMPLETED step
ssh staging_2Gb_vm "cat /opt/visa_bulletin/backups/refresh_checkpoint.json | python3 -m json.tool"

# Stage log shows current activity
ssh staging_2Gb_vm "tail -30 /tmp/refresh_stage.log"
```

### Orchestrator log?

```bash
ssh prod_2Gb_vm "tail -100 /tmp/orchestrator.log"
```

---

## Resuming from Failure

### Standard Resume

The checkpoint records the last successful step. `--resume` skips completed steps:

```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  nohup ./bazel-bin/scripts/cron/refresh_and_switch --resume --no-traffic-switch > /tmp/orchestrator.log 2>&1 &"
```

### Resume After Code Fix

If you fixed code that the pipeline needs on the inactive host:

```bash
# 1. Commit fix to staging branch (see docs/BRANCHING_AND_DEPLOYMENT.md)
git checkout staging && git cherry-pick <fix-commit> && git push origin staging

# 2. Pull fix on the inactive host and rebuild
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git fetch origin staging && git reset --hard origin/staging"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && bazel build //scripts/salary:affected_script && bazel shutdown"

# 3. Resume from active host
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  nohup ./bazel-bin/scripts/cron/refresh_and_switch --resume --no-traffic-switch > /tmp/orchestrator.log 2>&1 &"
```

**Never scp files directly.** All code changes go through git branches. See `docs/BRANCHING_AND_DEPLOYMENT.md`.

### Manual Checkpoint Reset

To re-run a specific step, edit the checkpoint to the step *before* the one you want to re-run:

```bash
ssh staging_2Gb_vm "cat > /opt/visa_bulletin/backups/refresh_checkpoint.json << 'EOF'
{
  \"last_step\": \"backfill_source_file_date\",
  \"timestamp\": \"2025-01-01T00:00:00Z\",
  \"inactive_db\": \"visa_bulletin\",
  \"index_snapshot\": \"/opt/visa_bulletin/backups/salary_indexes_20250101_000000.yaml\"
}
EOF"
```

### Traffic Switch Only

After a successful `--no-traffic-switch` run, do the switch:

```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  ./bazel-bin/scripts/cron/refresh_and_switch --from-step traffic_switch"
```

---

## Common Failure Modes

### Step 1: build_pipeline_binaries

| Symptom | Cause | Fix |
|---------|-------|-----|
| OOM killed | Bazel + compilation on 2GB host | Kill other processes, retry. Consider pre-building. |
| Disk full | Bazel cache + build artifacts | `bazel clean --expunge && bazel shutdown` on target host |
| Timeout (>2h) | First build after code update | Expected on cold cache; increase timeout or pre-build |

### Step 2: ensure_db

| Symptom | Cause | Fix |
|---------|-------|-----|
| `password authentication failed` | Wrong DB_PASSWORD in .env | Check `.env` on target host |
| `could not translate host name` | DB_HOST=host.docker.internal | Set DB_HOST=localhost in .env on target host |
| Migration conflict | Unapplied migration | Run `bazel run //:migrate` manually on target |

### Step 3: index_snapshot_saved

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ingest_run status=RUNNING` | Stale ingest run blocking drop | Pipeline auto-fixes (sets status=4). If not, `UPDATE ingest_run SET status = 4 WHERE status = 2` |
| Disk full | Snapshot YAML too large | Clean old snapshots in backups/ |

### Step 4: ingest_complete

| Symptom | Cause | Fix |
|---------|-------|-----|
| Timeout (>12h) | Very large new data files | Check which files are being processed in stage log |
| Network errors | Source sites unreachable | Retry; check if DOL/State Dept sites are up |
| 0 sources ingested | No new data available | Normal if data hasn't been updated. Post-processing skipped. |

### Steps 5–7: backfill + cluster_job_titles

| Symptom | Cause | Fix |
|---------|-------|-----|
| OOM killed | Large dataset on 2GB host | Monitor with `free -h`; kill Bazel server first (`bazel shutdown`) |
| Very slow (<2k/min) | Indexes still present (should be dropped at step 3) | Verify indexes are dropped: `SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'salary_record'` |
| Timeout (>8h) | Phase 2 LSH candidate explosion | Tune LSH banding / candidate-pruning thresholds in the clustering config |

### Step 8: indexes_restored

| Symptom | Cause | Fix |
|---------|-------|-----|
| Snapshot file not found | File deleted or path mismatch | Pipeline auto-falls-back to `--create-clustering-indexes`. If both fail, manually create indexes. |
| Timeout | Large table, index creation slow | Expected on 2GB; can take 1–2 hours |

### Step 10: cluster_employers

| Symptom | Cause | Fix |
|---------|-------|-----|
| Timeout (>24h) | Phase 2 with 400k+ employers | This is the longest step. Consider performance optimizations (batch sizing, index state, LSH tuning). |
| OOM killed | 2GB host with large comparison set | Free memory first; indexes must be present for this step |

### Step 14: start_services

| Symptom | Cause | Fix |
|---------|-------|-----|
| Docker daemon not running | Docker stopped or crashed | `sudo systemctl start docker` on target |
| Port conflict | Old container still bound | `docker-compose down && docker-compose up -d` |
| nginx fail | Config error | `sudo nginx -t` to check config |

### Step 16: smoke_tests

| Symptom | Cause | Fix |
|---------|-------|-----|
| Record count too low | Ingest missed data | Check ingest logs; re-run ingest step |
| Low link percentage | backfill_job_title_links failed silently | Re-run from that step |
| Missing slugs | populate_job_title_slugs didn't run | Re-run from that step |

---

## Self-Heal Mechanism

When 0 sources are ingested (data already in DB), steps 5–12 are normally skipped. However, the pipeline checks:

- If 0 clustered employers AND ≥100k salary records exist → **re-run clustering** (self-heal)
- This catches cases where DB was restored from backup without clustering data

If the self-heal DB query fails (e.g., table doesn't exist), it falls through to the default skip behavior without crashing.

---

## Escalation

1. **Step fails once**: Check stage log, identify root cause, fix, resume
2. **Step fails repeatedly**: Check resource constraints (disk, memory, connections) for known issues
3. **Pipeline stuck >48h**: Kill the process, investigate, consider running steps manually
4. **Data corruption suspected**: Do NOT traffic-switch. Verify data on inactive host. If bad, re-run from `ensure_db` (fresh start)

### Emergency Rollback (after traffic switch)

```bash
# Switch traffic back to old prod
ssh new_prod "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  ./bazel-bin/scripts/cron/refresh_and_switch --from-step traffic_switch"
```

Or manually via AWS CLI:

```bash
aws lightsail detach-static-ip --static-ip-name VisaBulletin-ip
aws lightsail attach-static-ip --static-ip-name VisaBulletin-ip --instance-name OldProdInstance
```

---

## Known Issues and Fixes (Phase 2.5 Babysit Sessions)

### Zombie pipeline processes after SSH timeout

**Discovered**: Feb 15, 2026. `backfill_job_title_links` ran for >4h, SSH timed out, but the remote process continued running for 3+ days.

**Root cause**: `RemoteRunner.run_bin()` runs commands via SSH without TTY allocation. When SSH times out (`subprocess.TimeoutExpired`), the local SSH client is killed, but no SIGHUP is sent to the remote process (no TTY = no signal). The remote bash + binary + tee pipeline continues running indefinitely.

**Fix applied**:
1. `RemoteRunner.run_bin()` now wraps remote commands with Linux `timeout --signal=TERM --kill-after=60` set to 95% of the SSH timeout. The remote process self-terminates before the SSH session gives up.
2. `stop_remote_services()` now kills known pipeline binaries (backfill, cluster, ingest, etc.) at pipeline start as defense-in-depth.

**Manual cleanup** (if zombies are found):
```bash
ssh staging_2Gb_vm "pgrep -af 'backfill_job_title|cluster_job_titles|cluster_existing|run_pipeline' | grep -v grep"
ssh staging_2Gb_vm "pkill -f 'backfill_job_title|cluster_job_titles|cluster_existing|run_pipeline'"
```

### warm_cache skips entirely when Redis package missing

**Discovered**: Feb 18, 2026. Stage log showed `Redis cache backend configured but 'redis' package not available; skipping cache warming.` — cache warming was a complete no-op.

**Root cause**: Code drift between local and staging. The staging `scripts/cache/BUILD` was missing `requirement("redis")` for the warm_cache target, while the local BUILD had it. The binary was built without the redis dependency, so `import redis` failed at runtime. The staging warm_cache.py has a graceful fallback that skips ALL cache warming (not just Redis-specific parts).

**Fix**: Ensure code is synced to staging before `build_pipeline_binaries`. The local BUILD file has `requirement("redis")`. Once C1 (step_sync_code) is implemented, this class of issue is eliminated.

**Workaround** (sync via git):
```bash
# Ensure the fix is on the staging branch, then pull on the instance
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git fetch origin staging && git reset --hard origin/staging"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && bazel build //scripts/cache:warm_cache && bazel shutdown"
```

### Docker web container crash-loops (psycopg2 missing)

**Discovered**: Feb 18, 2026. `visa_bulletin_web` container in `Restarting` state. Error: `Error loading psycopg2 or psycopg module`.

**Root cause**: The Docker image (`ghcr.io/vyakunin/visa_bulletin:latest`, built Feb 15) does not have `psycopg2-binary` installed despite it being in `requirements.txt`. The `python:3.11-slim` base image lacked `libpq5` runtime library. The Dockerfile now includes `libpq5` and a build-time verification (`python -c "import psycopg2"`) so broken images fail the build.

**Fix**: Rebuild and push the Docker image. The Dockerfile has been fixed. Until rebuilt:
```bash
# Temporary: install psycopg2 in the running container
ssh staging_2Gb_vm "docker exec -u root visa_bulletin_web pip install psycopg2-binary && docker restart visa_bulletin_web"
```

**Impact**: Without this fix, the web app is completely non-functional after `start_services`. The health check fails (non-fatal), but if traffic is switched, users see errors.

### Python module errors (`webapp.views.seo not a package`)

**Discovered**: Feb 19, 2026. Web container crashes with `ModuleNotFoundError: No module named 'webapp.views.seo'; 'webapp.views' is not a package`.

**Root cause**: The project deleted `__init__.py` files from `webapp/`, `webapp/views/`, etc. since Bazel handles imports via runfiles. However, the Docker container uses standard Python (gunicorn), which requires `__init__.py` for package imports. The volume mount (`../:/app`) overrides the image code, exposing the missing files.

**Fix**: `step_sync_code` now creates `__init__.py` files in the necessary directories after code sync. These are created on the remote host only, not in the source tree.

### Missing DB table after migration conflict (`models_blogpost`)

**Discovered**: Feb 19, 2026. Web container crashes with `ProgrammingError: relation "models_blogpost" does not exist`.

**Root cause**: Migration 0035 creates `BlogPost`, and 0036 deletes it. Both are marked as applied in `django_migrations`. But the code still references the model (blog views). After code sync, the code expects the table to exist.

**Fix**: Manually create the table and add migration records. Long-term: ensure migration consistency before traffic switch (smoke tests catch missing tables via HTTP checks).

---

## Post-Swap: Old Prod Becomes Staging

After a traffic switch, the previous production host becomes the new inactive/staging host. The orchestrator pipeline handles this automatically:

| Concern | Handled by |
|---|---|
| Stale code | `step_sync_code` (git pull: git fetch + git reset --hard) |
| Stale Docker image | `docker-compose.override.yml` volume-mounts host code |
| Missing `__init__.py` | `step_sync_code` creates them after code sync |
| Stale DB schema | `step_ensure_db` runs migrations |
| DB ownership issues | `_fix_db_ownership` in `step_ensure_db` |
| Old/orphan containers | `start_remote_services` runs `down --remove-orphans` first |
| Zombie processes | `stop_remote_services` kills known pipeline binaries |
| Stale Bazel cache | `build_all.sh` rebuilds from synced code, then `bazel shutdown` |
| Nginx not proxying IP | `start_remote_services` creates default-server block |
| ALLOWED_HOSTS missing IP | `docker-compose.override.yml` adds target host IP |
| Missing stats/counts | Smoke tests verify `total_filings > 0` and autocomplete results |
| Volume mount on new prod | `_write_prod_safe_override` replaces `../:/app` with prod-safe override (no volume mount) after traffic switch |
| NULL `case_submitted` on old prod data | `step_populate_case_submitted` backfills in-place from DOL files on disk (see below) |

**No manual intervention needed** — the pipeline is designed to work on either host regardless of its previous role.

### NULL case_submitted After Graduation (Automated)

After graduation, the new staging (old prod) may have salary records with NULL `case_submitted` if the old prod was running before `populate_case_submitted` was added to the pipeline.

**No full re-ingest needed.** The `populate_case_submitted` step reads DOL source files from `data/salary/dol_data/` (already on disk), finds records where `case_submitted IS NULL`, and updates them in-place. It is NOT in `STEPS_SKIP_WHEN_ZERO_INGESTED`, so it always runs — even when 0 new sources are ingested. Takes ~30 min for ~1.5M records.

**Smoke test gate:** The smoke tests require `case_submitted` coverage ≥ 65% (`MIN_CASE_SUBMITTED_PERCENT`). Healthy prod baseline: ~74% overall (100% for FY2018-2024, ~26% for FY2025 partial files, 0% pre-2018). If coverage is below 65%, graduation is blocked.

**Pre-pipeline check:**

```bash
ssh staging_2Gb_vm "ls /opt/visa_bulletin/data/salary/dol_data/ | wc -l"  # should be 20+
ssh staging_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  DB_HOST=localhost bazel run //:run_sql -- --query \
  'SELECT COUNT(*) as total, COUNT(case_submitted) as with_cs FROM salary_record'"
```

**Monitoring during pipeline:**

```bash
ssh staging_2Gb_vm "grep -E 'populate_case_submitted|Found.*without case_submitted|Updated.*records|No records need updating' /tmp/refresh_stage.log | tail -20"
```

- `Found N without case_submitted` + `Updated N records` = GOOD
- `No records need updating for X` for every file = BAD — likely `source_file` column mismatch

**Troubleshooting — "No records need updating" for every file:**

1. **`source_file` mismatch:** Script matches by `salary_record.source_file`. If values differ from filenames on disk, no records match. Compare: `SELECT DISTINCT source_file FROM salary_record ORDER BY source_file LIMIT 20` vs `ls data/salary/dol_data/`.
2. **DOL files purged:** If `ls data/salary/dol_data/ | wc -l` = 0, reset checkpoint to before `ingest_complete` so next pipeline re-downloads them.
3. **Column mapping change:** New DOL file format doesn't match `LCA_COLUMN_MAPPINGS`/`PERM_COLUMN_MAPPINGS`. Look for "Found 0 records to update from N rows" in stage log.

### New Prod: Override Cleanup (Automated)

After the traffic switch, the orchestrator automatically replaces `docker-compose.override.yml` on the new prod with a **prod-safe** version that drops the `../:/app` volume mount but keeps `mem_limit`, `memswap_limit`, `ALLOWED_HOSTS`, and `WEB_CONCURRENCY`. It then restarts the web container so it uses Docker image code instead of volume-mounted host code.

**Why this matters:** with the volume mount active, `git pull` on prod would affect gunicorn workers when they recycle (via `--max-requests 500`). Without the volume mount, `git pull` + `bazel build` is completely invisible to the web container, making orchestrator hotfixes safe. See `docs/BRANCHING_AND_DEPLOYMENT.md` for the full deployment path decision table.

**If the automated step fails** (non-fatal warning in logs), manually replace the override:

```bash
ssh <new-prod> "cat > /opt/visa_bulletin/deployment/docker-compose.override.yml << 'EOF'
version: '3.8'
services:
  web:
    mem_limit: 512m
    memswap_limit: 768m
    environment:
      - WEB_CONCURRENCY=1
      - ALLOWED_HOSTS=<prod-ip>,localhost,127.0.0.1,visa-bulletin.us,www.visa-bulletin.us
EOF"
ssh <new-prod> "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml -f deployment/docker-compose.override.yml up -d"
```

---

## Monitoring Checklist

During a babysit session, check these at each interval:

- [ ] Process still running? (`ps aux | grep refresh`)
- [ ] Stage log progressing? (`tail -20 /tmp/refresh_stage.log`)
- [ ] No errors? (`grep -i "error\|exception\|traceback" /tmp/refresh_stage.log | tail -5`)
- [ ] Memory OK? (`free -h` — should have >200MB free)
- [ ] Disk OK? (`df -h /` — should have >2GB free)
- [ ] Checkpoint advancing? (`cat backups/refresh_checkpoint.json`)

---

## Verify and Update Pipeline Scripts When Fixing Bugs

After fixing ANY bug in data processing, check if pipeline/refresh/setup scripts need to be updated.

**Decision tree:**
- Bug fixed in a script → Check if `refresh_data.sh` calls it → If not, add it
- Bug fixed in a library → Check callers are in pipeline → Verify integration
- Bug requires data fix → Run fix script on production → Schedule in pipeline

**Scripts to check:**
1. `scripts/cron/refresh_data.sh` — Does it run the fixed code?
2. `scripts/cron/build_all.sh` — Does it build the fixed binary? Add to `REQUIRED_BINARIES` if needed.
3. `scripts/setup_new_instance.sh` — Does it initialize correctly?

**Complete fix workflow:**
1. Fix the bug in source code
2. Test fix locally
3. Check: Is fixed code/script called in `refresh_data.sh`? If NO: add it.
4. Run fix on production to correct existing data
5. Commit all changes together

---

## Sync Setup Scripts When Fixing Data Ingestion Issues

When fixing data ingestion, processing, or database issues, update the corresponding setup scripts immediately.

**Scripts to update:**
1. `scripts/setup_new_instance.sh` — initial instance setup
2. `scripts/cron/refresh_data.sh` — initial data load + weekly refresh
3. `deployment/cron/setup-ingest-cron.sh` — cron schedule

**What to check/update in each:**
- Environment variables needed for fix
- Database initialization steps / migration requirements
- Data loading commands and flags
- Error handling and retry logic

**Verification checklist before committing ingestion fixes:**
- [ ] Setup scripts include all new environment variables
- [ ] `refresh_data.sh` includes all new initialization steps
- [ ] Cron scripts include all new flags/options
- [ ] Documentation reflects new behavior

---

## Job Title Coherence Smoke Test

After deploying or running `refresh_data` (including `update_job_title_cluster_stats` + `populate_job_title_slugs`), verify coherence on the deployment.

### A. Autocomplete – fields and order

```bash
GET /api/job-title-autocomplete/?q=software&limit=5
```
Response must be JSON array with **title** (= `canonical_title`), **slug**, **total_filings**, ordered by `total_filings` DESC then `canonical_title`.

### B. Profile count matches autocomplete

Pick a slug from autocomplete and note its `total_filings`. Visit `/job-title/<slug>/` — page must show the same Total Filings.

### C. Generated URLs resolve

URLs must be `/job-title/<slug>/` with slug from `canonical_title` (lowercase, hyphenated). Must return 200.

### D. Similar Job Titles section

On a job title profile, "Similar Job Titles" block must list `canonical_title` for other clusters (not raw SOC-style variants).

### E. Integration test

```bash
bazel test //tests:test_job_title_profile_view
```

### F. Clear cache after updates

```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && bazel run //scripts:clear_cache"
# If using LocMem (no Redis), reload gunicorn:
ssh prod_2Gb_vm "kill -HUP \$(pgrep -f 'gunicorn.*django_config' | head -1)"
```
