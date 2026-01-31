---
title: New Instance Setup (Living Document)
---

# New Instance Setup (Living Document)

This document captures the exact steps used to set up the new Lightsail instance.
Update this file with any manual corrections, workarounds, or deviations as they occur.

## Instance Details

- **IP Address:** 44.209.204.255 *(static IP: VisaBulletin-StaticIP)*
- **OS:** Ubuntu 22.04 LTS
- **Instance Size:** 2GB RAM / 60GB SSD (small_3_0)
- **SSH Key:** ~/.ssh/lightsail_visa_bulletin
- **Instance Name:** VisaBulletin2GB

**✅ Static IP attached:** `VisaBulletin-StaticIP` (44.209.204.255) - IP won't change on restart.

## Automated Setup Script

**For new instances, use the automated setup script:**

```bash
# Clone repo and run setup
git clone https://github.com/vyakunin/visa_bulletin.git /opt/visa_bulletin
cd /opt/visa_bulletin
./scripts/setup_new_instance.sh
```

This script automates:
- System prerequisites installation
- Swap configuration (2GB, swappiness=60)
- Docker installation
- PostgreSQL installation and tuning (bulk operation optimized)
- Blue-green database creation
- Monitoring tools (sysstat, atop, health_check.sh)
- Bazel memory limits

After running, follow the manual steps below for domain-specific configuration.

---

## Deployment Scenarios

Choose your setup based on instance purpose:

### Scenario 1: Production Web Server
**Purpose:** Public-facing website (visa-bulletin.us)

**Components needed:**
- ✅ PostgreSQL (data storage)
- ✅ Docker + Docker Compose (web service)
- ✅ Nginx (reverse proxy, SSL termination)
- ✅ Certbot (SSL certificates)
- ✅ Cron jobs (data refresh)

**Skip:**
- ❌ Never use Django dev server (`runserver`) in production

### Scenario 2: Ingestion-Only Instance
**Purpose:** Data processing and database management (like current 2GB instance)

**Components needed:**
- ✅ PostgreSQL (data storage)
- ✅ Bazel (build system for data scripts)
- ✅ Cron jobs (scheduled ingestion)

**Skip:**
- ❌ Docker containers (not needed, data processing runs on host)
- ❌ Nginx (no web traffic to serve)
- ❌ SSL/Certbot (no public web access)

### Scenario 3: Development/Testing
**Purpose:** Local development or testing on dedicated instance

**Components needed:**
- ✅ PostgreSQL (data storage)
- ✅ Bazel (build system)
- ⚠️ Django dev server (for testing only)

**Skip:**
- ❌ Production Docker setup
- ❌ Nginx/SSL (unless testing production config)

---

## Manual Setup Steps (Reference)

The following sections document the manual setup steps for reference and troubleshooting.

---

## Handoff: Monitoring the Pipeline (Ingestion-Only Instance)

**Instance Type:** Ingestion-only (44.209.204.255 - 2GB RAM)

**Goal:** Continue the ingest pipeline safely on the 2GB instance using prebuilt binaries and avoid Bazel JVM.

**Note:** This instance does NOT run a web server. It only processes data and updates the PostgreSQL database.

### 1) Confirm instance + SSH
```bash
ssh staging_2Gb_vm
```

### 2) Confirm PostgreSQL is up
```bash
pg_isready -h localhost
sudo systemctl status postgresql --no-pager
```
If down: `sudo systemctl restart postgresql`

### 3) Check memory + swap (OOM risk)
```bash
free -m
swapon --show
```
If swap is near-full or PostgreSQL was killed, check kernel log:
```bash
sudo dmesg -T | tail -200
```

### 4) Verify prebuilt binary exists (no Bazel JVM)
```bash
test -x /opt/visa_bulletin/bazel-bin/scripts/ingest/run_pipeline && echo PREBUILT_OK
```
If missing, run `scripts/cron/build_all.sh` once and wait for completion.

### 5) Start retry-failed ingest (prebuilt)
First ensure only one instance is running and identify whether it's a new or older run:
```bash
ps -ef | grep -E '[r]un_pipeline run --retry-failed'
ps -o pid,lstart,cmd -C python3 | grep -E 'run_pipeline run --retry-failed' || true
```
If a retry-failed run is already active, **do not start another**. Compare the start time to confirm whether the running process is the one you just launched or an older run.

```bash
cd /opt/visa_bulletin
set -a; source ./.env; set +a
DB_HOST=localhost nohup ./bazel-bin/scripts/ingest/run_pipeline run --retry-failed --domain dol \
  > /var/log/visa-bulletin/retry_failed.log 2>&1 &
```

### 6) Monitor progress to completion (do not exit early)
```bash
# Initial check (sanity)
tail -40 /var/log/visa-bulletin/retry_failed.log
```

**Monitoring strategy (gradually increase intervals):**
- **First 5 min**: Check every 30 seconds (ensure healthy start)
- **Next 10 min**: Check every 1 minute (stable progress)
- **Next 15 min**: Check every 2 minutes (continued stability)
- **After 30 min**: Check every 5 minutes (mature stable run)
- **After 1 hour**: Check every 10 minutes (long-running stable)

**Each check must verify:**
```bash
# Check status, memory, and progress in one command
ssh staging_2Gb_vm "
  echo '=== Memory ===' && free -m | grep -E 'Mem:|Swap:' &&
  echo '=== PostgreSQL ===' && pg_isready -h localhost &&
  echo '=== Process ===' && ps -o pid,etime,cmd -C python3 | grep run_pipeline | head -2 &&
  echo '=== Recent Progress ===' && tail -20 /var/log/visa-bulletin/retry_failed.log
"
```

**Continue monitoring until completion** (do not stop early). Only stop after you see:
- `Pipeline completed: ...`
- A final summary block after the completion line

**If issues detected:**
1. **Errors in log** → Capture error block, fix root cause, re-run step 5, resume monitoring
2. **Very slow progress** (< 50 rec/sec sustained) → Check memory, swap, PostgreSQL status
3. **Low memory** (< 200MB available) → Check for memory leak, consider restart
4. **SSH unavailable** → Check OOM logs (`sudo dmesg -T | tail -200`), restart PostgreSQL if killed
5. **Process disappeared** → Check exit code in log, investigate cause, re-run step 5

### 7) Validate completeness after retry (required)
```bash
DB_HOST=localhost ./bazel-bin/scripts/ingest/run_pipeline check-completeness
```
If any missing files/years are reported, re-run step 5 and repeat this check.

### 8) Confirm pipeline finished cleanly (final check)
- Ensure there are no new errors at the end of the log.
- Verify the final summary lines appear after `Pipeline completed`.
- If the log ends abruptly, re-run step 7 and review the last 100 lines.

**Completion criteria:** steps 6–8 must all pass with no errors.

### 9) Verify indexes before clustering (MANDATORY)

**⚠️ CRITICAL:** Check if indexes were dropped during ingest. If so, recreate BEFORE clustering.

```bash
# Check index count
ssh staging_2Gb_vm \
  "sudo -u postgres psql -d visa_bulletin_blue -t -c \
  \"SELECT COUNT(*) FROM pg_indexes WHERE tablename='salary_record';\""

# Expected: 10+ indexes
# If < 5 indexes: Indexes were dropped, must recreate before clustering
```

**If indexes missing, create clustering indexes:**
```bash
# Create minimal indexes required for clustering
ssh staging_2Gb_vm \
  "cd /opt/visa_bulletin && \
   bazel build //scripts/salary:manage_salary_indexes && bazel shutdown && \
   set -a && source .env && set +a && \
   DB_HOST=localhost ./bazel-bin/scripts/salary/manage_salary_indexes --create-clustering-indexes"

# Verify indexes created (should show 8+ indexes now)
ssh staging_2Gb_vm \
  "sudo -u postgres psql -d visa_bulletin_blue -t -c \
  \"SELECT COUNT(*) FROM pg_indexes WHERE tablename='salary_record';\""
```

**Why critical:** Without indexes, clustering does full table scans (1.5M records) and is 100x+ slower.

### 10) If SSH becomes unstable
- Check OOM logs: `sudo dmesg -T | tail -200`
- If PostgreSQL killed, restart it and re-run step 5.
- If network DNS errors occur, verify DNS: `python3 - <<'PY'` with `socket.gethostbyname('www.dol.gov')`.


## Common Pipeline Issues and Resolutions

### Issue 1: `null value in column "created_at"` constraint violation

**Symptoms:**
```
ERROR: null value in column "created_at" of relation "salary_record" violates not-null constraint
```

**Root Cause:**
The upsert logic was copying ALL fields from incoming records to existing records, including auto timestamp fields (`created_at` with `auto_now_add=True`, `updated_at` with `auto_now=True`). Since incoming records have these set to None (Django populates them on save), we were setting existing records' timestamps to NULL.

**Fix Applied (2026-01-27):**
Modified `lib/ingest/orchestrator.py` to skip auto timestamp fields when updating:
```python
# Skip auto timestamp fields - Django sets these automatically
if isinstance(field, models.DateTimeField) and (field.auto_now or field.auto_now_add):
    continue
```

**Status:** ✅ Fixed in commit [to be committed]

### Issue 2: `null value in column "prevailing_wage_unit"` constraint violation

**Symptoms:**
```
ERROR: null value in column "prevailing_wage_unit" of relation "salary_record" violates not-null constraint
```

**Root Cause:**
The Django model had `prevailing_wage_unit = models.CharField(blank=True)` but was missing `null=True`, creating an inconsistency. The parser sets this field to `None` when raw data is empty (legitimate for many records), but the database had a NOT NULL constraint.

**Fix Applied (2026-01-27):**
1. Updated `models/salary.py` to add `null=True`:
   ```python
   prevailing_wage_unit = models.CharField(
       max_length=20,
       choices=WageUnit.choices,
       blank=True,
       null=True,  # Allow NULL when prevailing_wage is not provided
       help_text="Unit for prevailing wage (year, hour, etc.)"
   )
   ```
2. Created migration `0026_alter_salaryrecord_prevailing_wage_and_more.py`
3. Applied migration: `DB_HOST=localhost bazel run //:migrate`

**Status:** ✅ Fixed via migration 0026

### Issue 3: PostgreSQL memory exhaustion from large bulk_update

**Symptoms:**
- Pipeline stuck at very slow progress (< 50 rec/sec)
- PostgreSQL process consuming 75%+ of RAM
- Massive `UPDATE ... CASE WHEN ...` statement with 10,000 records × many fields

**Root Cause:**
Django's `bulk_update()` with large batch sizes creates a single SQL statement with a CASE expression per record per field. With `batch_size=10000` and ~30 fields, this creates a 1.5GB+ query that causes memory thrashing on 2GB instances.

**Fix Applied (2026-01-27):**
Capped bulk_update batch size at 1,000 in `lib/ingest/orchestrator.py`:
```python
# Cap bulk_update batch size at 1000 to prevent memory exhaustion
update_batch_size = min(self.batch_size, 1000)
model_class.objects.bulk_update(update_batch, update_fields, batch_size=update_batch_size)
```

**Status:** ✅ Fixed with batch size cap

### Issue 4: "could not translate host name 'host.docker.internal'" during migrations

**Symptoms:**
```
psycopg2.OperationalError: could not translate host name "host.docker.internal" to address
```

**Root Cause:**
The `.env` file has `DB_HOST=host.docker.internal` (for Docker containers), but when running Bazel commands outside Docker, this hostname doesn't resolve.

**Solution:**
Override DB_HOST when running migrations outside Docker:
```bash
DB_HOST=localhost bazel run //:migrate
```

**Status:** ✅ Documented in `.cursor/rules/django.mdc`

### Diagnostic Commands Used

**Check pipeline status:**
```bash
ps -eo pid,etime,pcpu,pmem,cmd | grep -E 'run_pipeline|postgres' | grep -v grep
```

**Check memory and swap:**
```bash
free -m
```

**Check PostgreSQL activity:**
```bash
psql -d visa_bulletin_blue -c "SELECT pid, usename, datname, state, wait_event, query FROM pg_stat_activity WHERE datname = 'visa_bulletin_blue' ORDER BY query_start;"
```

**Check for stuck queries:**
```bash
ps aux --sort=-%mem | head -10
```

**Terminate stuck PostgreSQL query:**
```bash
psql -d visa_bulletin_blue -c "SELECT pg_terminate_backend(PID);"
```

**Check database schema:**
```bash
psql -d visa_bulletin_blue -c "\d+ salary_record"
```


## SSH Setup

```bash
ssh staging_2Gb_vm
```

**Note:** Update IP if instance was stopped/started (check AWS CLI: `aws lightsail get-instance --instance-name VisaBulletin2GB --query 'instance.publicIpAddress'`)

## System Update

```bash
sudo apt update
sudo apt upgrade -y
```

## Docker Installation

```bash
sudo apt install -y docker.io docker-compose curl build-essential
sudo usermod -aG docker ubuntu
sudo systemctl enable docker
sudo systemctl start docker
```

Notes:
- Docker version: 28.2.2 (Ubuntu package)
- docker-compose version: 1.29.2
- Group change may require logout/login for non-sudo docker usage

## Repository Setup

```bash
sudo mkdir -p /opt/visa_bulletin
sudo git clone https://github.com/vyakunin/visa_bulletin.git /opt/visa_bulletin
sudo chown -R ubuntu:ubuntu /opt/visa_bulletin
```

## Environment Configuration

Create `/opt/visa_bulletin/.env` with:

- `DJANGO_SECRET_KEY` (new value)
- `DEBUG=False`
- `ALLOWED_HOSTS=44.209.204.255,visa-bulletin.us` *(static IP - won't change)*
- PostgreSQL connection variables (DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT)

Generated by `setup_new_instance.sh`:
- `DJANGO_SECRET_KEY` - random 32-byte key
- `DB_PASSWORD` - random password
- `DB_HOST=host.docker.internal` - Docker containers access host's PostgreSQL via this
- `IMAGE_TAG=manual-f77adbc-feature` - set after image build

**Note:** `DB_HOST=host.docker.internal` is correct for Docker. Bazel scripts automatically convert to `localhost` when running on the host.

## PostgreSQL Setup

Follow `docs/POSTGRESQL_SETUP.md` and note any deviations here:

- Install PostgreSQL 14+
- Create `visa_bulletin` database and user
- Verify authentication

## Production Web Server Setup

**⚠️ IMPORTANT: NEVER use Django dev server (`runserver`) in production!**

Production web server uses **Gunicorn** (WSGI server) managed by **systemd**, with Nginx as a reverse proxy.

### Production Web Server (Systemd + Gunicorn)

**For production instances with public web access:**

```bash
cd /opt/visa_bulletin

# Ensure .env has correct DB_HOST
grep DB_HOST .env  # Should be: DB_HOST=localhost

# Start production web server
sudo systemctl start visa-bulletin-web

# Verify service is running
sudo systemctl status visa-bulletin-web

# Check logs
sudo journalctl -u visa-bulletin-web -f

# Check web service responds
curl -I http://localhost:8000  # Gunicorn
curl -I http://localhost/      # Nginx (proxies to Gunicorn)
```

**Service management:**
```bash
# Start service
sudo systemctl start visa-bulletin-web

# Stop service
sudo systemctl stop visa-bulletin-web

# Restart service
sudo systemctl restart visa-bulletin-web

# View logs
sudo journalctl -u visa-bulletin-web -f

# View recent logs
sudo journalctl -u visa-bulletin-web --since "10 minutes ago"
```

**Service details:**
- Service file: `/etc/systemd/system/visa-bulletin-web.service`
- Uses Gunicorn WSGI server (production-ready)
- 2 workers, 2 threads per worker (optimized for 2GB instance)
- Runs Django migrations before starting (`ExecStartPre`)
- Exposes port 8000 for Nginx reverse proxy
- Auto-restarts on failure
- Memory limit: 500MB (prevents OOM)

**Configuration:**
- Environment: `/opt/visa_bulletin/.env`
- Must have `DB_HOST=localhost` for host-based PostgreSQL connection
- `ALLOWED_HOSTS` must include public IP and domain

### Development Server (Testing Only)

**For non-production instances or development:**

```bash
cd /opt/visa_bulletin

# Start dev server using helper script
./scripts/start_dev_server.sh

# Or manually:
# bazel build //:runserver && bazel shutdown
# DB_HOST=localhost ./bazel-bin/runserver runserver 0.0.0.0:8000
```

**⚠️ Dev server limitations:**
- Single-threaded (slow under load)
- Not suitable for production traffic
- No auto-restart on crash
- Security warnings in Django

### Ingestion-Only Instance (No Web Server)

**For dedicated ingestion instances (like this one):**

No web server needed. Only run:
- PostgreSQL (for data storage)
- Cron jobs (for scheduled data refresh)

Skip Docker and Nginx setup entirely.

## Bazel Installation

Install Bazel (6.x or 7.x) for cron jobs and data refresh.
Record any additional steps or packages required.

Notes:
- Bazel requires `gcc` (install `build-essential`).
- Run `refresh_data.sh` as the non-root `ubuntu` user; Bazel fails under root.

## Pre-Build All Binaries (Memory Optimization)

**CRITICAL for 2GB instances:** Build all binaries once during setup, then run them directly without Bazel.

```bash
cd /opt/visa_bulletin

# Build all targets (uses memory temporarily, but only runs once)
./scripts/cron/build_all.sh

# Verify binaries exist
ls -la bazel-bin/scripts/ingest/run_pipeline
ls -la bazel-bin/migrate
```

**Why this matters:**
- Bazel JVM uses ~400MB RAM at runtime
- Pre-built binaries run directly without JVM overhead
- Prevents OOM during cron jobs

**After running `build_all.sh`:**
- Bazel server is shut down (frees ~400MB)
- Binaries are in `bazel-bin/`
- `refresh_data.sh` will automatically use pre-built binaries

## Cron Configuration

Set up a single weekly cron job to run the end-to-end refresh:

```bash
0 2 * * 0 cd /opt/visa_bulletin && bash scripts/cron/refresh_data.sh >> /var/log/visa-bulletin/refresh.log 2>&1
```

**Memory behavior:**
| Scenario | Peak Memory | Notes |
|----------|-------------|-------|
| Pre-built binaries exist | ~500MB | Uses `bazel-bin/` directly, no JVM |
| Binaries missing (fallback) | ~1.5GB | Falls back to `bazel run` |

**Note:** `refresh_data.sh` automatically detects and uses pre-built binaries when available, falling back to `bazel run` if they're missing.

## Nginx Setup (Production Web Server Only)

**Only needed if running production web service with Docker containers.**
Skip this for ingestion-only instances.

```bash
sudo apt install -y nginx

# Copy configuration files
sudo cp /opt/visa_bulletin/deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
# Note: Update server_name in the config with your domain

# Enable site
sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t
if [ $? -eq 0 ]; then
    sudo systemctl restart nginx
    sudo systemctl enable nginx
    echo "✅ Nginx configured and running"
else
    echo "❌ Nginx configuration error - check /var/log/nginx/error.log"
    exit 1
fi

# Verify Nginx is proxying to port 8000
curl -I http://localhost/
```

**What this does:**
- Nginx listens on port 80 (HTTP) and 443 (HTTPS after SSL setup)
- Reverse proxies to Django app on port 8000 (Docker container)
- Serves static files directly (performance optimization)
- Handles SSL/TLS termination
- Provides caching and security headers

## SSL Setup (Production Web Server Only)

**Only needed for production web servers with public domains.**
Skip this for ingestion-only or development instances.

### Prerequisites
1. Domain DNS must point to this instance's IP
2. Nginx must be installed and configured
3. Docker web service must be running on port 8000

### Install Certbot
```bash
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

### Obtain SSL Certificate
```bash
# Replace with your domain
sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us

# Certbot will:
# 1. Verify domain ownership (via HTTP challenge)
# 2. Obtain Let's Encrypt certificate
# 3. Update Nginx config for HTTPS
# 4. Configure auto-renewal
```

### Verify SSL
```bash
# Check certificate
sudo certbot certificates

# Test HTTPS
curl -I https://visa-bulletin.us

# Check auto-renewal
sudo certbot renew --dry-run
```

## Testing Checklist

- Core pages (`/`, `/salaries/`, `/faq/`, `/about/`, `/contact/`)
- Employer directory + specific large employer profile
- Job title directory + specific job title profile
- Search functionality

## Manual Course Corrections

Record any manual fixes or deviations here:

- **Issue:** [Describe problem]
  - **Fix:** [Exact command or change applied]
  - **Reason:** [Why this deviation was necessary]
  - **Follow-up:** [If anything needs to be updated in scripts/config]

- **Issue:** Default `/opt/visa_bulletin/docker-compose.yml` uses SQLite and legacy data-refresh loop.
  - **Fix:** Use `deployment/docker-compose.blue.yml` and `deployment/docker-compose.green.yml`.
  - **Reason:** Production must use PostgreSQL and the new blue/green deployment flow.
  - **Follow-up:** Ensure compose files include `.env` for DB settings and updated healthcheck.

- **Issue:** Healthcheck used `curl`, which is not present in the image.
  - **Fix:** Install `curl` in the image and use curl healthcheck with short timeout.
  - **Reason:** Default curl timeout is too long and blocked health checks.
  - **Follow-up:** Rule: always use `curl -f --max-time 5 http://localhost:8000/` for healthchecks.

- **Issue:** GHCR `latest` image still uses SQLite (legacy schema).
  - **Fix:** Build and push a new image tag from current branch before deploying.
  - **Reason:** Web app must use PostgreSQL schema and new code.
  - **Follow-up:** Use `IMAGE_TAG` when bringing up blue/green compose.

- **Issue:** Docker build failed copying non-existent `extractors/` directory.
  - **Fix:** Remove `cp -r extractors /app/dist/` from `Dockerfile`.
  - **Reason:** Directory was removed from repo, but Dockerfile still referenced it.
  - **Follow-up:** Rebuild and push image after Dockerfile change.

- **Issue:** Web container could not reach PostgreSQL from Docker network.
  - **Fix:** Set `DB_HOST=host.docker.internal` and add `extra_hosts` to compose services.
  - **Reason:** Containers cannot reach host DB via `localhost`.
  - **Follow-up:** Ensure these settings are captured in compose files and .env.

- **Issue:** `pg_hba.conf` rejected Docker network connections.
  - **Fix:** Add `host all all 172.17.0.0/16 scram-sha-256`, `host all all 172.18.0.0/16 scram-sha-256`, and temporary `host all all 0.0.0.0/0 scram-sha-256`.
  - **Reason:** Docker networks used 172.18.0.0/16 and were blocked.
  - **Follow-up:** Tighten `pg_hba.conf` to least-privilege after final network choice.

- **Issue:** GHCR login on instance stores credentials in root's Docker config.
  - **Fix:** Logged in with `docker login` to push image, accepted warning.
  - **Reason:** Needed to push image from the instance.
  - **Follow-up:** Consider configuring a credential helper or removing credentials post-deploy.

- **Issue:** Legacy `data-refresh` compose services conflicted with end-to-end cron refresh.
  - **Fix:** Removed `data-refresh-*` services from blue/green compose and removed the orphan container.
  - **Reason:** All refresh logic must run through `scripts/cron/refresh_data.sh`.
  - **Follow-up:** Keep compose files free of background ingest loops.

- **Issue:** `refresh_data.sh` exited immediately after ingest due to `set -e` + `pipefail` on the `bazel run ... | tee` pipeline.
  - **Fix:** Temporarily disable `-e` around the pipeline, capture exit code, then restore `-e`.
  - **Reason:** Bash exited before post-processing even though the pipeline output completed.
  - **Follow-up:** Keep the explicit exit-code handling for ingest pipelines.

- **Issue:** DOL discovery produced 404 URLs under `/agencies/eta/foreign-labor/performance/...`.
  - **Fix:** Use `urljoin()` in DOL LCA/PERM discovery to resolve `/sites/dolgov/...` URLs against `https://www.dol.gov/`.
  - **Reason:** Concatenating `base_url` with absolute paths created invalid URLs.
  - **Follow-up:** Confirm DOL files download and SalaryRecord count increases after re-run.

- **Issue:** Visa bulletin ingest failed with `value too long for type character varying(50)` on `visa_class`.
  - **Fix:** Increase `VisaCutoffDate.visa_class` max length to 100 and add migration `0025_alter_visacutoffdate_visa_class_and_more.py`.
  - **Reason:** Newer bulletin classes include long labels (e.g., "5th Set Aside: High Unemployment (10%, including NH, RH)").
  - **Follow-up:** Re-run refresh to ingest affected bulletins.

- **Issue:** DOL salary ingest failed with `value too long for type character varying(2)` on state fields.
  - **Fix:** Normalize `employer_state` and `worksite_state` using `normalize_state_code()` in DOL parsing (`dol_lca.py`, `dol_perm.py`, `db_importer.py`).
  - **Reason:** Some files include full state names or unexpected values that exceed 2 characters.
  - **Follow-up:** Re-run refresh to verify PERM/LCA loads without state truncation errors.

- **Issue:** COPY ingest treated empty strings as NULL, causing `soc_title` not-null violations.
  - **Fix:** Use `null='\\N'` for COPY and emit `\\N` only for actual nulls; keep empty strings intact.
  - **Reason:** `soc_title` is blank-allowed but not null; empty strings must stay empty.
  - **Follow-up:** Re-run refresh to ensure PERM records load without null violations.

- **Issue:** Worksite files produced zero records and failed validation.
  - **Fix:** Route any `*worksite*` source file to `WorksiteRecord` transform (not just `I-200*` case numbers).
  - **Reason:** PW_Worksites files may not have I-200 case numbers but should still generate WorksiteRecord rows.
  - **Follow-up:** Re-run refresh; verify WorksiteRecord counts > 0 for worksite files.

- **Issue:** SSH became unreachable; instance rebooted and IP changed (Jan 21).
  - **Fix:** Updated instance IP to `13.221.107.235` and refreshed known_hosts entry.
  - **Reason:** System log showed power key press and system powering down; SSH returned after reboot.
  - **Follow-up:** Keep `ALLOWED_HOSTS` and DNS swap instructions aligned with new IP.

- **Issue:** SSH became unreachable again; OOM killer triggered (Jan 22).
  - **Fix:** Added 2GB swap, Bazel memory limits, updated IP to `3.83.127.124`.
  - **Reason:** Bazel build (Java + Python workers) exceeded 2GB RAM with no swap; OOM killer crashed system.
  - **Follow-up:** See "Instance Stability Issue" section for full root cause analysis and prevention protocol.

- **Issue:** Temporary DNS failures during ingest and clustering.
  - **Fix:** Re-run failed DOL sources after DNS recovers; re-run clustering after dependency fetch succeeds.
  - **Reason:** `www.dol.gov` and PyPI resolution failed during refresh, causing failed downloads and Bazel fetch errors.
  - **Follow-up:** Monitor logs for DNS stability and validate completeness before final swap.

- **Issue:** COPY failed for `job_title_entity_id` with empty string in PERM ingest.
  - **Fix:** Treat `None` and empty-string FK values as `\\N` in COPY buffer.
  - **Reason:** PERM rows can emit empty FK values; PostgreSQL expects NULL for bigint FK fields.
  - **Follow-up:** Re-run pending DOL ingest.

- **Issue:** PERM ingest hit duplicate employer unique constraint during create.
  - **Fix:** Pre-check employer existence before `create`, then fall back to lookup on IntegrityError.
  - **Reason:** Cache missed existing employers for some records; create hit uniqueness guard.
  - **Follow-up:** Re-run pending DOL ingest and verify status.

- **Issue:** PERM ingest failed with NULL `prevailing_wage_unit` (NOT NULL column).
  - **Fix:** Treat `None` as empty string for non-null `CharField`/`TextField` in COPY.
  - **Reason:** Some PERM rows omit prevailing wage unit; DB expects empty string, not NULL.
  - **Follow-up:** Re-run pending DOL ingest and confirm no NULL violations.

- **Issue:** PERM ingest failed with NULL `created_at` (NOT NULL column).
  - **Fix:** For `DateTimeField` with `auto_now`/`auto_now_add`, write `timezone.now()` when value is None.
  - **Reason:** COPY bypasses model defaults; auto timestamps were not set.
  - **Follow-up:** Re-run pending DOL ingest and confirm COPY succeeds.

- **Issue:** PERM ingest failed with `worksite_state` length > 2 (e.g., "FLORIDA").
  - **Fix:** Sync updated `db_importer.py` to normalize worksite state codes before COPY.
  - **Reason:** Instance still had old `db_importer.py` without state normalization.
  - **Follow-up:** Re-run pending DOL ingest and confirm no `varchar(2)` failures.

- **Issue:** SSH became unreachable multiple times with low CPU (Jan 26).
  - **Root Cause Investigation:** Found **swap exhaustion + OOM kills** in previous boots:
    - Jan 23 10:18: `Free swap = 152kB` → OOM killed `python3`
    - Jan 24 06:04: `Free swap = 0kB` → **OOM killed PostgreSQL!**
    - PostgreSQL logs showed multiple "automatic recovery in progress" events
  - **Why swappiness=10 was bad:** System avoided swapping until memory was critical, then OOM-killed when swap finally filled up.
  - **Fixes Applied:**
    1. Increased swappiness: `vm.swappiness=60` (was 10) - swap earlier, avoid OOM
    2. Added explicit Bazel memory limits to `.bazelrc`:
       ```
       build --local_ram_resources=1024
       build --jobs=2
       build --worker_max_instances=1
       ```
    3. Tuned PostgreSQL memory to reduce OOM risk:
       ```
       shared_buffers = 128MB
       work_mem = 4MB
       maintenance_work_mem = 64MB
       effective_cache_size = 512MB
       max_connections = 50
       ```
    3. Attached static IP: `44.209.204.255` (`VisaBulletin-StaticIP`)
    4. Enabled `sysstat` for memory monitoring: `sar -r` shows historical memory usage
  - **Monitoring:** 
    - Memory history: `sar -r` (after sysstat collects data)
    - Instance state: `aws lightsail get-instance-state --instance-name VisaBulletin2GB --region us-east-1`
  - **Recovery:** If running but SSH unresponsive: `aws lightsail stop-instance` then `aws lightsail start-instance`

- **Issue:** Job title clustering extremely slow (no progress in 10+ minutes) - Jan 28.
  - **Root Cause:** Indexes were dropped for fast ingest but never recreated before clustering.
  - **Fix:** Manually recreated critical indexes via SQL (emergency), then updated scripts to use `bazel shutdown` after builds.
  - **Prevention:** Always follow post-ingestion step 1 (recreate indexes) in `INGESTION_PLAYBOOK.md` before clustering.
  - **Emergency recovery:** If clustering is stuck:
    ```bash
    # Create critical indexes manually
    sudo -u postgres psql -d $DB_NAME << 'SQL'
    CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_job_title_idx ON salary_record(job_title);
    CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_employer_name_idx ON salary_record(employer_name);
    CREATE INDEX CONCURRENTLY IF NOT EXISTS salary_record_employer_job_title_idx ON salary_record(employer_name, job_title);
    SQL
    ```

## Instance Stability Issue: OOM Killer (Jan 22, 2026)

### Root Cause Analysis

**Symptoms:**
- Instance became unreachable (SSH timeout, ping timeout)
- AWS showed instance as "running" but CPU at 60-100%
- Instance took 3+ minutes to stop (hung processes)

**Root Cause:** Out of Memory (OOM) Killer triggered by Bazel builds

**Evidence from logs:**
```
Jan 22 22:14:15 kernel: Out of memory: Killed process 10322 (java) total-vm:2994316kB, anon-rss:423620kB
Jan 22 22:14:15 kernel: oom-kill: task=java,pid=10322,uid=1000
```

**Contributing factors:**
1. **Instance undersized:** 2GB RAM (not 4GB as initially documented)
2. **No swap configured:** System had 0 swap space
3. **Bazel memory usage:** Java JVM (423MB) + multiple Python workers (~290MB) = >700MB
4. **PostgreSQL:** Additional ~50-100MB
5. **Total pressure:** >1.5GB on 2GB system

**Timeline:**
1. Bazel process started (likely cron job or manual refresh)
2. Memory pressure exceeded available RAM
3. OOM killer activated, killed Java process
4. System entered thrashing state (constant page swapping with no swap)
5. SSH daemon couldn't get CPU time to respond
6. Instance appeared hung despite AWS reporting "running"

### Fixes Applied

1. **Added 2GB swap file:**
   ```bash
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

2. **Set swappiness to 10** (prefer RAM, use swap only when needed):
   ```bash
   echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
   sudo sysctl vm.swappiness=10
   ```

3. **Added Bazel memory limits** in `/opt/visa_bulletin/.bazelrc`:
   ```
   build --local_ram_resources=1024
   build --jobs=2
   ```

### Prevention Protocol

**Monitoring (add to cron):**
```bash
# Check memory usage every 5 minutes, alert if >80%
*/5 * * * * MEM=$(free | awk '/Mem:/ {printf "%.0f", $3/$2 * 100}'); [ $MEM -gt 80 ] && echo "$(date): Memory at ${MEM}%" >> /var/log/memory-alerts.log
```

**AWS CLI commands for debugging unreachable instances:**
```bash
# Check instance state
aws lightsail get-instance-state --instance-name VisaBulletin2GB

# Get CPU metrics (last hour)
aws lightsail get-instance-metric-data --instance-name VisaBulletin2GB \
  --metric-name CPUUtilization --period 300 \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --unit Percent --statistics Average

# Force stop if hung
aws lightsail stop-instance --instance-name VisaBulletin2GB

# Start after stop
aws lightsail start-instance --instance-name VisaBulletin2GB

# Get new IP after restart
aws lightsail get-instance --instance-name VisaBulletin2GB --query 'instance.publicIpAddress'
```

**Long-term recommendations:**
1. **Attach static IP** to prevent IP changes on restart
2. **Consider 4GB instance** if running Bazel builds regularly
3. **Move Bazel builds off production** - build Docker images in CI/CD instead
4. **Set up CloudWatch alarms** for CPU >80% and memory alerts
