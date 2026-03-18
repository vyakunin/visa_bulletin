# Hardening and Optimization Plan

## Current State Assessment

The system has a blue-green deployment flipover via `scripts/cron/refresh/orchestrate.py` that runs the full data refresh pipeline on an inactive Lightsail instance, then switches traffic via static IP reassignment. The pipeline has 16 steps (build through smoke tests) with checkpoint/resume support. **No successful end-to-end unattended flipover has been completed yet** -- every run so far has required manual intervention. Key pain points: long runtimes (cluster_job_titles Phase 2 alone estimated at 70+ hours), N+1 query patterns in several scripts, shallow unit test coverage for the refresh pipeline (23 tests, all happy-path), ~30 stale root-level markdown files, 7,000+ lines of always-applied Cursor rules, and no cost optimization for the 0.5GB backup instance.

---

## A. Deployment Flipover Hardening

### A1. Eliminate hardcoded IPs and instance names

**Problem:** `deployment/docker-compose.yml` line 33 hardcodes `ALLOWED_HOSTS` with `54.196.241.197`, `44.209.204.255`. `services.py` line 58 hardcodes legacy container names.

**Fix:** Move all IPs/names to `.env` variables. Use `${ALLOWED_HOSTS}` in docker-compose. Remove legacy container name references. (Staging static IP name: `orchestrate.py` now requires `REFRESH_STAGING_STATIC_IP_NAME` in `.env`; `setup_new_instance.sh` adds the placeholder.)

### A2. Add health-check gate between index restore and read-heavy steps

**Problem:** After `step_restore_indexes()`, the pipeline immediately runs read-heavy steps (employer stats, clustering). If index creation fails silently or is incomplete, read-heavy steps degrade to table scans on a 2GB instance.

**Fix:** Add a verification query after index restore that confirms expected indexes exist (`pg_indexes` check). Fail fast if critical indexes are missing.

**Files:**
- `scripts/cron/refresh/steps.py` -- add index verification after `step_restore_indexes()`
- `scripts/salary/manage_salary_indexes.py` -- add `--verify` flag

### A3. Add pipeline-level timeout and alerting

**Problem:** Individual step timeouts exist (up to 24h for cluster_employers), but there is no pipeline-level wall-clock timeout. A stuck pipeline can run for days unnoticed.

**Fix:** Add a `REFRESH_PIPELINE_MAX_WALL_CLOCK_SEC` env var (default 48h). Log elapsed time at each checkpoint. Optionally send a notification (webhook or simple email via AWS SES) if pipeline exceeds threshold or fails.

**Files:**
- `scripts/cron/refresh/pipeline.py` -- add wall-clock check
- `scripts/cron/refresh/config.py` -- add max wall clock config

### A4. Consolidate timeout constants

**Problem:** Four separate timeout constants in `steps.py` (lines 36, 133, 135, 137): `BUILD_PIPELINE_BINARIES_SSH_TIMEOUT_SEC` (2h), `INGEST_SSH_TIMEOUT_SEC` (12h), `CLUSTER_EMPLOYERS_SSH_TIMEOUT_SEC` (24h), `HEAVY_STEP_SSH_TIMEOUT_SEC` (8h). These are spread across the file and hard to tune.

**Fix:** Move all timeout constants to `config.py` as part of `RefreshConfig`, settable via env vars. Each step reads its timeout from config.

**Files:**
- `scripts/cron/refresh/config.py` -- add timeout fields to RefreshConfig
- `scripts/cron/refresh/steps.py` -- read timeouts from config

---

## B. Data Refresh Pipeline Performance

### B1. cluster_job_titles Phase 1: Chunked bulk lookup + bulk_create

**Problem:** Phase 1 calls `get_or_create()` per unique job title (~162k calls = ~162k queries). This is the classic N+1 pattern.

**Fix:** Process unique job titles in configurable chunks to control peak memory while eliminating N+1 queries:

1. Stream unique job titles from the DB using `.iterator(chunk_size=CHUNK_SIZE)`.
2. For each chunk, batch-query existing `JobTitle` rows by `(title_normalized, experience_level)` using `filter(title_normalized__in=[...])`.
3. Diff the chunk against the existing set. `bulk_create()` the missing ones.
4. Configurable constant: `PHASE1_CHUNK_SIZE = 5000` (default; ~5k normalized strings + their model instances fit comfortably in <50 MB).

This keeps peak memory proportional to `CHUNK_SIZE` (not to the full 162k), while reducing total queries from ~162k to ~(162k / 5000) * 2 = ~65 queries.

**File:** `scripts/salary/cluster_job_titles.py` lines 65, 98-127

### B2. cluster_job_titles Phase 2: Chunked assign_to_cluster with batched saves

**Problem:** `clustering_engine.assign_to_cluster()` calls `entity.save()` individually (line 407 and 435 of `clustering_engine.py`). With ~162k titles, that is ~162k UPDATE queries. Also, line 137 loads all JobTitle objects into memory with `list(JobTitle.objects.select_related('canonical_cluster'))`.

**Fix:** Two changes, both chunk-aware:

1. **Avoid loading all entities into memory.** Instead of `list(JobTitle.objects.all())`, process unclustered titles in chunks: `JobTitle.objects.filter(canonical_cluster__isnull=True).iterator(chunk_size=CHUNK_SIZE)`. The bucket index still needs a full scan, but can be built from `.values('id', 'title_normalized', ...)` (~40 bytes/row vs ~500 bytes for full model instances).

2. **Deferred saves.** Add a `save=False` parameter to `assign_to_cluster()` in `clustering_engine.py` so it sets `entity.canonical_cluster` but does not call `entity.save()`. Collect modified entities in a list; when list reaches `PHASE2_FLUSH_SIZE` (default 1000), call `bulk_update_batched(batch, fields=['canonical_cluster'])` and clear the list.

This keeps peak memory proportional to `CHUNK_SIZE + PHASE2_FLUSH_SIZE` and reduces queries from ~162k to ~162k/1000 = ~162 bulk updates.

**Configurable constants:**
- `PHASE2_CHUNK_SIZE = 5000` -- how many unclustered entities to load per DB round-trip
- `PHASE2_FLUSH_SIZE = 1000` -- how many modified entities to accumulate before bulk_update

**Files:**
- `lib/business/clustering_engine.py` -- add `save=False` option to `assign_to_cluster()`
- `scripts/salary/cluster_job_titles.py` -- chunked iteration + deferred flush

### B3. cluster_job_titles Phase 2: Reduce LSH candidate explosion

**Problem:** Phase 2 processes 130k+ candidate pairs at ~200/sec (~70+ hours observed on staging). The LSH threshold of 0.7 may generate too many low-quality candidates.

**Fix:** Raise LSH threshold from 0.7 to 0.8 (or make it configurable). Add early-exit when similarity is clearly below match threshold. Profile `match_employers()` equivalent for job titles to find CPU hotspots.

**File:** `scripts/salary/cluster_job_titles.py` -- LSH threshold tuning

### B4. backfill_job_title_links: Replace per-title count() with bulk aggregation

**Problem:** Lines 119-125 of `backfill_job_title_links.py` iterate over every `JobTitle` and run `SalaryRecord.objects.filter(job_title_entity=job_title).count()` individually. With ~162k JobTitle entities, that is ~162k COUNT queries plus ~162k individual `save()` calls.

**Fix:** Replace with a single SQL aggregation:

```sql
SELECT job_title_entity_id, COUNT(*) FROM salary_record
WHERE job_title_entity_id IS NOT NULL
GROUP BY job_title_entity_id
```

Then `bulk_update_batched()` all at once.

**File:** `scripts/salary/backfill_job_title_links.py` lines 119-127

### B5. backfill_source_file_date: Hardening and completion

**Problem:** This script has multiple issues beyond the N+1 query pattern. See separate document: `docs/BACKFILL_SOURCE_FILE_DATE_HARDENING.md`.

**Summary of issues:**
- Per-record `DataSource.objects.filter(...).first()` query (N+1, line 77-79)
- Local import inside loop (line 73)
- Bare `except Exception: pass` silently swallows errors (line 82-83)
- Uses `print()` instead of `logger` (lines 48-50, 94-95, 100-105)
- `select_related` not used for `ingest_version__run` (causes additional N+1 on line 69-70)
- `skipped_count` is declared but never incremented (line 64)
- No `ScriptLogger` for script usage tracking

**File:** `scripts/salary/backfill_source_file_date.py` -- see dedicated doc

---

## C. Code Refresh Update Cycle

### C1. Automate code deployment to inactive host

**Problem:** Currently code updates to the inactive host require manual `scp` of changed files or `git pull`. The orchestrator builds binaries on the remote host but doesn't ensure the latest code is there.

**Fix:** Add a `step_sync_code()` as the first pipeline step that runs `git pull` (git fetch + git reset --hard) on the inactive host. The branch is controlled by `REFRESH_SYNC_BRANCH` env var (default: "staging"). This ensures the inactive host always has the latest code before building.

**Files:**
- `scripts/cron/refresh/steps.py` -- add `step_sync_code()`
- `scripts/cron/refresh/checkpoint.py` -- add step to `STEPS_ORDER`

### C2. Add version pinning to deployment

**Problem:** No version tracking during refresh. If code changes mid-pipeline (someone pushes while refresh is running), the build step might pick up partial changes.

**Fix:** Record the git commit SHA in the checkpoint file at `step_sync_code()`. Log it at pipeline start and smoke test completion. This provides traceability without adding complexity.

**Files:**
- `scripts/cron/refresh/checkpoint.py` -- add `git_sha` field to CheckpointData
- `scripts/cron/refresh/steps.py` -- capture SHA during sync step

---

## D. Environment File Management

### D1. Create a canonical .env.example

**Problem:** No `.env.example` in the repo. Required env vars are scattered across `setup_new_instance.sh`, `config.py`, `orchestrate.py`, and `deployment.mdc`.

**Fix:** Create `.env.example` with all required and optional variables, grouped by category (DB, Django, Redis, AWS, Refresh Orchestrator), with comments explaining each.

**File:** New file `.env.example`

### D2. Validate env vars at pipeline startup

**Problem:** Missing env vars cause cryptic failures deep in the pipeline (e.g., SSH timeout because `REFRESH_SSH_KEY_PATH` is wrong).

**Fix:** Add an `_validate_env()` function to `config.py` that checks all required env vars exist and are non-empty at `RefreshConfig` construction time. Fail fast with a clear error listing all missing vars.

**File:** `scripts/cron/refresh/config.py` -- add validation

### D3. Document the DB_HOST duality

**Problem:** `DB_HOST=host.docker.internal` in docker-compose vs `DB_HOST=localhost` for host scripts is a recurring source of confusion. Multiple scripts auto-convert, but the pattern is undocumented in one place.

**Fix:** Add a section to `.env.example` and `deployment/README.md` explaining the duality and the auto-conversion pattern.

**Files:**
- `.env.example` -- document DB_HOST
- `deployment/README.md` -- add DB_HOST section

---

## E. AWS Management and Cost Optimization

### E1. Backup instance -- keep as cold spare

**Status:** Already stopped. Keep as cold spare for reference (old config, snapshots). No action needed. Cost: $0/month while stopped (Lightsail only charges for running instances; storage is included in the plan).

### E2. Stop inactive instance when not refreshing

**Problem:** The staging instance (`staging_2Gb_vm`, 2GB) runs 24/7 at ~$10/month but is only used during weekly refresh (~24-48h).

**Fix:** The orchestrator already starts the instance at the beginning and can stop the old one after traffic switch. Verify this works reliably. Add a `step_stop_old_instance()` that stops the now-inactive (old prod) instance after smoke tests pass, saving ~5 days of runtime per week.

**Cost impact:** ~$7/month saved if instance is stopped 5 out of 7 days.

**File:** `scripts/cron/refresh/orchestrate.py` -- verify instance stop logic

### E3. Consolidate Lightsail instance sizes

**Problem:** Two 2GB instances ($10/month each) + one 0.5GB instance ($3.50/month) = $23.50/month. Pipeline currently takes 70+ hours for cluster_job_titles alone, keeping both instances running.

**After performance optimizations (B1-B6):** If pipeline runtime drops to <12 hours, the inactive instance only needs to run ~1 day/week. The rest of the time it can be stopped.

**Projected savings:** After optimizations, total hosting could drop to ~$13-15/month (one always-on prod + one on-demand staging).

### E4. Add Lightsail cost monitoring

**Fix:** Add a simple `scripts/check_aws_costs.sh` that queries Lightsail instance states and calculates monthly cost projection. Run it as part of the orchestrator pre-flight check.

---

## F. Documentation for Humans

### F1. Clean up root-level stale markdown files

**Problem:** 18 root-level `.md` files are duplicates of or superseded by files in `docs/`:

```
Root-level files to delete (have docs/ equivalents):
- ANALYTICS_QUICKSTART.md, DEV_SETUP.md, DOCKER_QUICKSTART.md
- DOCKER_DEPLOYMENT.md, DEPLOY_LIGHTSAIL_STEPS.md, DEPLOYMENT.md
- DEPLOYMENT_AWS.md, FEATURE_IDEAS.md, LIGHTSAIL_SSH_SETUP.md
- PAGESPEED_OPTIMIZATIONS.md, ROLLOUT_FLOW.md, SEO_OPTIMIZATION.md

Files to delete (stale worklogs per project rules):
- IMPROVEMENTS_COMPLETED.md, SEO_IMPROVEMENTS_SUMMARY.md
- DOCKER_IMPLEMENTATION_SUMMARY.md, DEPLOYMENT_SEO_CHECKLIST.md

Files to review (may be stale):
- THRESHOLD_ANALYSIS.md, SEO_PREVIEW.md
```

**Action:** Extract any unique info into permanent docs, then delete.

### F2. Add a single-page architecture overview

**Problem:** No single document explains the full system architecture: how data flows from DOL/State Dept sources through ingestion, processing, clustering, and into the web app. A new developer must read 5+ docs and rule files to piece it together.

**Fix:** Create `docs/ARCHITECTURE.md` with a mermaid diagram showing:
- Data sources (DOL, State Dept) -> Ingest pipeline -> PostgreSQL
- Pipeline steps (with ordering)
- Blue-green deployment (prod/staging instances, traffic switch)
- Web stack (Nginx -> Docker/Gunicorn -> Django -> PostgreSQL)

### F3. Create a runbook for pipeline failures

**Problem:** When the pipeline fails at a specific step, there is no single reference for what to do. Knowledge is scattered across rule files, conversation history, and tribal knowledge.

**Fix:** Create `docs/PIPELINE_RUNBOOK.md` covering: how to check status, how to resume from checkpoint, common failure modes per step, and escalation/rollback procedures.

---

## G. Documentation for LLMs (Cursor Rules Optimization)

### G1. Compress always-applied rule content

**Problem:** 20 rule files totaling ~7,033 lines are ALL `alwaysApply: true`. This burns context budget on every interaction. Switching rules to `alwaysApply: false` with globs is unreliable in agent-first workflows (user does not manually open/close files, so glob-triggered loading would silently miss rules).

**Fix:** Keep all rules `alwaysApply: true` but aggressively compress their content:

1. **Deduplicate** between `AGENTS.md` and `.cursor/rules/*.mdc` (see G2).
2. **Collapse verbose examples.** Many rules repeat the same pattern 3-4 ways. Keep one GOOD/BAD pair; move extra examples to `docs/PIPELINE_RUNBOOK.md` or inline comments.
3. **Remove redundant preambles.** Rules like "These are general X rules that apply across all projects" add no value -- the file name already says that.
4. **Merge small rules.** Several 5-line rules in the same file can be collapsed into a single table or bullet list.

**Target files (largest savings):**
- `general_script_development.mdc` (1,099 lines) -- ~200 lines of monitoring examples can become one pattern
- `general_performance.mdc` (808 lines) -- repeated batching patterns can reference shared utility docs
- `deployment.mdc` (707 lines) -- Docker/blue-green examples can reference `docs/DEPLOYMENT.md`
- `django.mdc` (657 lines) -- enum patterns repeated 4 ways can become a table
- `bazel.mdc` (612 lines) -- cross-platform examples can reference `docs/CROSS_PLATFORM_RUFF_ANALYSIS.md`

**Impact:** Estimated 40-60% reduction (from ~7k to ~3-4k lines) while keeping all rules always-applied. No risk of silently dropped rules.

### G2. Deduplicate AGENTS.md and rule files

**Problem:** `AGENTS.md` (306 lines) duplicates several rules that also appear in `.cursor/rules/` files (e.g., "Never Use git commit --no-verify" appears in both AGENTS.md and `general_precommit.mdc`; SSH alias rules appear in both AGENTS.md and `scripts.mdc`).

**Fix:** Slim down `AGENTS.md` to only contain the 5-6 truly critical rules (commit only when asked, no --no-verify, no foreground servers, no `| head` in pipes, SSH aliases, investigate production warnings). Move everything else to `.cursor/rules/` files. Add a one-line cross-reference for each moved rule.

### G3. Compress verbose rules with examples

**Problem:** Several rules repeat the same pattern 3-4 times with different examples. For instance, `general_script_development.mdc` has ~200 lines of monitoring examples that could be condensed to a single pattern + "see docs/PIPELINE_RUNBOOK.md for examples."

**Fix:** For the top 3 longest rule files, extract verbose examples into referenced documentation. Keep rules as concise patterns with one GOOD/BAD example each.

### G4. Model-tier rule optimization (future consideration)

**Deferred.** If G1-G3 compression proves insufficient, consider maintaining separate "slim" (Opus) and "full" (Composer) rule sets via a build step that strips verbose examples. Not worth the maintenance overhead until compression alone is shown to be inadequate.

---

## H. Refresh Pipeline Unit Testing

### Current coverage

| File | Tests | Covers |
|------|-------|--------|
| `test_refresh_checkpoint.py` | 6 | Checkpoint read/write, skip logic, old step name mapping |
| `test_refresh_pipeline.py` | 2 | MockRunner basic call recording, step ordering |
| `test_refresh_orchestrate.py` | 3 | Orchestrate no-op, no-traffic-switch happy path, missing env |
| `test_refresh_config.py` | 5 | Config loading, env read/write |
| `test_refresh_instance.py` | 7 | Instance resolution, active/inactive detection |
| **Total** | **23** | **Mostly happy-path and plumbing** |

All tests use mocked infrastructure (no real SSH, no real DB). This is fine for unit tests, but the mocks are too permissive -- `MockRunner` always returns `returncode=0`, so no failure path is exercised.

### H1. Pipeline step failure + resume

**Gap:** No test exercises a step failing mid-pipeline and then resuming from checkpoint. `test_run_pipeline_mock_no_resume` immediately hits a `RuntimeError` and asserts that *some* calls were made -- it does not verify that the correct step was checkpointed or that resume actually skips completed steps in a realistic scenario.

**Fix:** Add tests that configure `MockRunner` to fail at a specific step (e.g., `step_cluster_job_titles` returns `returncode=1`), verify the checkpoint records the last *successful* step, then re-run with `resume=True` and confirm previously-completed steps are skipped.

**File:** `tests/test_refresh_pipeline.py`

### H2. MockRunner failure modes

**Gap:** `MockRunner` always returns success. No test passes `returncode != 0` to verify the pipeline aborts correctly, logs the right error, and writes the correct checkpoint.

**Fix:** Add `run_bin_side_effects` to `MockRunner` -- a dict mapping `rel_path` to a `CompletedProcess` with nonzero returncode. Tests use this to simulate failures at specific steps and verify correct abort behavior.

**File:** `scripts/cron/refresh/runner.py` (MockRunner), `tests/test_refresh_pipeline.py`

### H3. Self-heal logic

**Gap:** The `STEPS_SKIP_WHEN_ZERO_INGESTED` + cluster self-heal block (`pipeline.py` lines 93-121) has no test coverage. This is complex conditional logic with DB queries that should be tested with mock returns.

**Fix:** Add tests that set `ctx.sources_ingested_count = 0` and configure `MockRunner.run_psql_return` to simulate (a) 0 clustered employers + many records (self-heal triggers), (b) >0 clustered employers (skip triggers), (c) query error (fallback behavior).

**File:** `tests/test_refresh_pipeline.py`

### H4. Individual step error handling

**Gap:** `steps.py` contains 16 step functions. None have dedicated unit tests. Each wraps `runner.run_bin()` and checks return codes -- these checks should be tested with both success and failure runner returns.

**Fix:** Add targeted tests for the most critical steps: `step_run_ingest` (parses source counts from output), `step_restore_indexes` (handles missing snapshot), `step_start_services` (handles Docker failures), `step_run_smoke_tests` (parses pass/fail). Each test uses MockRunner with controlled return values.

**File:** `tests/test_refresh_steps.py` (new file)

### H5. Orchestrate service lifecycle

**Gap:** `test_run_orchestrate_no_traffic_switch_runs_pipeline_then_exits` mocks `run_pipeline` entirely. No test verifies that the orchestrator correctly handles service stop/start or what happens when health checks fail after starting services.

**Fix:** Add tests where `wait_instance_healthy` returns `False` and verify the orchestrator aborts with a clear error rather than proceeding to traffic switch.

**File:** `tests/test_refresh_orchestrate.py`

---

## Implementation Priority

**Phase 1 -- Quick Wins (1-2 days):**
- G1-G3: Rule content compression and deduplication (save context budget early; G4 deferred)
- F1: Delete stale root-level docs
- D1: Create .env.example
- A1: Remove hardcoded IPs

**Phase 2 -- Pipeline Performance (3-5 days):**
- B1: cluster_job_titles Phase 1 chunked bulk operations
- B2: cluster_job_titles Phase 2 chunked iteration + deferred flush
- B4: backfill_job_title_links bulk aggregation
- B5: backfill_source_file_date hardening (see dedicated doc)
- H4-H5: Unit tests for individual steps and orchestrate lifecycle (find bugs before babysitting)

**Phase 2.5 -- First Successful Unattended Flipover (1-2 babysit sessions):**
- Run orchestrator end-to-end (`--no-traffic-switch`), babysit to completion
- Fix issues as they surface; each fix becomes a runbook entry (F3)
- Implement unit tests for discovered failure modes (H1-H3)
- Second run: full flipover with traffic switch
- Goal: 2 consecutive successful runs before declaring pipeline "proven"

**Phase 3 -- Deployment Hardening (2-3 days):**
- A2: Index verification gate (if not already added during Phase 2.5)
- A3: Pipeline wall-clock timeout
- A4: Consolidate timeouts into config
- C1: Configurable code sync to inactive host
- D2: Env var validation at startup

**Phase 4 -- Documentation and Cost (2-3 days):**
- F2: Architecture overview doc
- F3: Pipeline runbook (seeded from Phase 2.5 notes)
- E2-E4: AWS cost optimization (E1 done -- backup instance already stopped)
