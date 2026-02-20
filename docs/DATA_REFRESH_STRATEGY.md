# Data Refresh Strategy: Blue-Green Database Approach

## Overview

**Current deployment:** We use **one database per instance** (`visa_bulletin`). Refresh runs on the inactive (staging) instance; traffic switch flips to that instance. There are no longer two databases (blue/green) on a single host. The sections below are kept for historical reference and for options (e.g. shared DB host) that we do not use.

This document describes blue-green–style deployment and automated data refresh with near-zero downtime.

## Table of Contents

1. [Architecture Decision: DB Swap vs Schema Swap](#architecture-decision)
2. [Blue-Green Database Architecture](#blue-green-database-architecture)
3. [Automated Refresh Pipeline](#automated-refresh-pipeline)
4. [Rollback Strategy](#rollback-strategy)
5. [Implementation Guide](#implementation-guide)

---

## Architecture Decision

### DB Swap vs Schema Swap

**Recommendation: Use separate databases (DB swap)**

#### Option A: Separate Databases (RECOMMENDED)

**Architecture:**
- Two complete databases: `visa_bulletin_blue` and `visa_bulletin_green`
- Django settings point to active database via `DATABASE_URL` environment variable
- Nginx/Django routing switches between databases

**Pros:**
- ✅ Complete isolation (no shared resources during refresh)
- ✅ Simpler rollback (just change `DATABASE_URL`)
- ✅ No risk of schema conflicts or lock contention
- ✅ Can run smoke tests without affecting production
- ✅ Works well with existing blue-green code deployment
- ✅ Easy to understand and debug

**Cons:**
- ❌ More storage (2x database size)
- ❌ Slower copy operation (full database copy)

**Storage math (based on actual current usage):**
- Current total disk usage: **~13 GB** (includes OS, PostgreSQL, app, logs)
- Estimated DB size: **~5-6 GB** (PostgreSQL data directory)
- Blue + Green databases: **~12 GB** (during refresh, both active)
- Archives (compressed): **~1.5 GB** each × 3 = **~4.5 GB**
- OS + app + logs: **~2 GB**
- **Total required: ~18-19 GB minimum**

**Current 20GB instance: ⚠️ Only ~1-2 GB headroom!**

**Lightsail pricing reference:**
- **Official AWS Lightsail pricing:** https://aws.amazon.com/lightsail/pricing/
- **Linux/Unix instances:** https://aws.amazon.com/lightsail/pricing/#Linux_Unix
- **Note:** Pricing and storage vary by region and instance type. Check the official page for current pricing in your region.

**Current instance:**
- **4GB RAM, 80 GB SSD** - Production server (upgraded Jan 2026)
- **Cost:** $20/month (check your AWS Lightsail console for exact billing)
- **Storage:** 80 GB total, plenty of headroom for blue-green databases

**Recommendation:** Use instance-local PostgreSQL (current setup)
- Storage is included with instance (no separate storage cost)
- 4GB RAM is sufficient for Bazel builds and data refresh operations

#### Option B: Schema Swap

**Architecture:**
- Single database with two schemas: `public` and `staging`
- Django ORM configured with `schema` parameter
- Views or `search_path` switch for routing

**Pros:**
- ✅ Less storage (shared pgdata)
- ✅ Faster copy (within same DB)

**Cons:**
- ❌ Shared resources (connections, locks, WAL)
- ❌ More complex rollback (schema swap requires coordination)
- ❌ Risk of lock contention during refresh
- ❌ Harder to debug (single DB with multiple schemas)
- ❌ Django ORM schema support is limited/awkward
- ❌ More complex backup/restore

### Decision: Separate Databases (DB Swap)

**Rationale:**
1. Storage cost is minimal (~$10-20/month extra)
2. Complete isolation prevents refresh from affecting production
3. Simpler implementation (no schema routing complexity)
4. Better aligns with blue-green code deployment
5. Easier rollback and debugging
6. No Django ORM schema routing complexity

---

## Blue-Green Database Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Production Server                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Django App (reads DATABASE_URL from environment)                │
│                                                                   │
│  DATABASE_URL = postgresql://user:pass@localhost/visa_bulletin   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                              ↓ (symlink swap)
                              ↓
┌──────────────────────┬──────────────────────┬──────────────────┐
│  visa_bulletin       │  visa_bulletin_blue  │  visa_bulletin_  │
│  (symlink)           │  (real database)     │  green           │
│                      │                      │  (real database) │
│  Points to:          │  - Live traffic      │  - Being         │
│  visa_bulletin_blue  │  - Current data      │    refreshed     │
│                      │  - Indexed           │  - No traffic    │
└──────────────────────┴──────────────────────┴──────────────────┘
```

### Database State Machine

```
Initial State:
  visa_bulletin → visa_bulletin_blue (active)
  visa_bulletin_green (idle, ready for refresh)

Refresh Process:
  1. Copy blue → green
  2. Ingest new data into green
  3. Run post-processing on green
  4. Smoke tests on green
  5. Swap: visa_bulletin → visa_bulletin_green (atomic)
  
New State:
  visa_bulletin → visa_bulletin_green (active)
  visa_bulletin_blue (idle, ready for next refresh)
```

### Swap Mechanism

**PostgreSQL doesn't support database rename while connections exist.**

**Solution: Use connection string environment variable:**

```bash
# Current active DB (via systemd environment or docker-compose)
DATABASE_URL=postgresql://user:pass@localhost:5432/visa_bulletin_blue

# After refresh, update and restart
DATABASE_URL=postgresql://user:pass@localhost:5432/visa_bulletin_green
systemctl restart visa-bulletin  # Or docker-compose restart
```

**Downtime:** ~2-3 seconds (service restart time)

**Alternative (zero downtime):** Use connection pooler (PgBouncer) with database switching

---

## Automated Refresh Pipeline

### Cron Job Script: `scripts/cron/refresh_data.sh`

**Schedule:** Weekly on Sunday at 2:00 AM

**Location:** `/opt/visa_bulletin/scripts/cron/refresh_data.sh`

**Cron entry:**
```bash
# Run weekly data refresh
0 2 * * 0 /opt/visa_bulletin/scripts/cron/refresh_data.sh >> /var/log/visa-bulletin/refresh.log 2>&1
```

### Pipeline Steps

```bash
#!/bin/bash
# scripts/cron/refresh_data.sh
# Automated blue-green database refresh with rollback capability

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="/var/log/visa-bulletin/refresh_$(date +%Y%m%d_%H%M%S).log"
BACKUP_DIR="/var/backups/visa-bulletin"
MAX_BACKUPS=3  # Keep 3 old versions (current + 2 archives)

# Logging
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== Data Refresh Started: $(date) ==="

# 1. Detect current active database
CURRENT_DB=$(grep "^DATABASE_URL=" /etc/visa-bulletin/env | cut -d'/' -f4)
if [[ "$CURRENT_DB" == "visa_bulletin_blue" ]]; then
    INACTIVE_DB="visa_bulletin_green"
    NEXT_ACTIVE="green"
elif [[ "$CURRENT_DB" == "visa_bulletin_green" ]]; then
    INACTIVE_DB="visa_bulletin_blue"
    NEXT_ACTIVE="blue"
else
    echo "ERROR: Could not determine active database"
    exit 1
fi

echo "Current active: $CURRENT_DB"
echo "Refresh target: $INACTIVE_DB"

# 2. Discover new data sources
echo "=== Checking for new data sources ==="
cd "$PROJECT_ROOT"
NEW_SOURCES=$(bazel run //scripts/ingest:run_pipeline -- check-completeness | \
    grep "Not ingested (available)" | wc -l)

if [[ "$NEW_SOURCES" -eq 0 ]]; then
    echo "No new data sources found. Exiting."
    exit 0
fi

echo "Found $NEW_SOURCES new data sources to ingest"

# 3. Create fresh database copy
echo "=== Copying database: $CURRENT_DB → $INACTIVE_DB ==="
# Drop and recreate inactive database
psql -U visa_bulletin -c "DROP DATABASE IF EXISTS $INACTIVE_DB;"
psql -U visa_bulletin -c "CREATE DATABASE $INACTIVE_DB TEMPLATE $CURRENT_DB;"

# 4. Configure Django to use inactive database
export DATABASE_URL="postgresql://visa_bulletin:PASSWORD@localhost:5432/$INACTIVE_DB"

# 5. Run complete ingestion pipeline
echo "=== Running ingestion pipeline on $INACTIVE_DB ==="

# 5a. Drop indexes for faster ingestion
echo "Dropping indexes..."
bazel run //scripts/salary:manage_salary_indexes -- \
    --drop \
    --snapshot "$BACKUP_DIR/salary_indexes_$(date +%Y%m%d).yaml" \
    --overwrite

# 5b. Discover and ingest new sources
echo "Discovering and ingesting new sources..."
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest

# 5c. Run post-processing
echo "Post-processing: Backfill job title links..."
bazel run //scripts/salary:backfill_job_title_links

echo "Post-processing: Backfill source file dates..."
bazel run //scripts/salary:backfill_source_file_date

echo "Post-processing: Cluster job titles..."
bazel run //scripts/salary:cluster_job_titles

echo "Post-processing: Cluster employers..."
bazel run //scripts/salary:cluster_existing_employers

echo "Post-processing: Update job title stats..."
bazel run //scripts/salary:update_job_title_cluster_stats

# 5d. Recreate indexes
echo "Recreating indexes..."
bazel run //scripts/salary:manage_salary_indexes -- \
    --recreate \
    --snapshot "$BACKUP_DIR/salary_indexes_$(date +%Y%m%d).yaml"

# 6. Run smoke tests
echo "=== Running smoke tests on $INACTIVE_DB ==="
SMOKE_TEST_PASSED=true

# Test 1: Check record counts
RECORD_COUNT=$(psql -U visa_bulletin -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM salary_record;")
if [[ "$RECORD_COUNT" -lt 100000 ]]; then
    echo "ERROR: Record count too low: $RECORD_COUNT"
    SMOKE_TEST_PASSED=false
fi

# Test 2: Check recent fiscal year data (use most recent FY in DB, not current calendar year)
# DOL fiscal years end in September, so FY2024 = Oct 2023 - Sep 2024
# We should check the MAX fiscal year in the database, not assume current year exists
MAX_FISCAL_YEAR=$(psql -U visa_bulletin -d "$INACTIVE_DB" -t -c \
    "SELECT MAX(fiscal_year) FROM salary_record;")
if [[ -z "$MAX_FISCAL_YEAR" ]]; then
    echo "ERROR: No fiscal year data found"
    SMOKE_TEST_PASSED=false
else
    echo "Most recent fiscal year: $MAX_FISCAL_YEAR"
    RECENT_COUNT=$(psql -U visa_bulletin -d "$INACTIVE_DB" -t -c \
        "SELECT COUNT(*) FROM salary_record WHERE fiscal_year = $MAX_FISCAL_YEAR;")
    if [[ "$RECENT_COUNT" -lt 1000 ]]; then
        echo "WARNING: Very few records for most recent fiscal year $MAX_FISCAL_YEAR: $RECENT_COUNT"
    else
        echo "✅ Recent fiscal year $MAX_FISCAL_YEAR has $RECENT_COUNT records"
    fi
    
    # Check if most recent FY is reasonable (within 2 years of current calendar year)
    CURRENT_YEAR=$(date +%Y)
    YEAR_DIFF=$((CURRENT_YEAR - MAX_FISCAL_YEAR))
    if [[ "$YEAR_DIFF" -gt 2 ]]; then
        echo "WARNING: Most recent fiscal year $MAX_FISCAL_YEAR is ${YEAR_DIFF} years old"
    fi
fi

# Test 3: Basic view smoke tests
echo "Testing salary search view..."
bazel test //tests:test_salary_search_view

# Test 4: Check employer clustering
CLUSTERED_EMPLOYERS=$(psql -U visa_bulletin -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM employer WHERE canonical_cluster_id IS NOT NULL;")
if [[ "$CLUSTERED_EMPLOYERS" -lt 100000 ]]; then
    echo "WARNING: Low clustered employer count: $CLUSTERED_EMPLOYERS"
fi

if [[ "$SMOKE_TEST_PASSED" != "true" ]]; then
    echo "ERROR: Smoke tests failed. Aborting swap."
    exit 1
fi

echo "✅ Smoke tests passed"

# 7. Archive current active database
echo "=== Archiving previous version ==="
ARCHIVE_NAME="visa_bulletin_${CURRENT_DB}_$(date +%Y%m%d_%H%M%S).sql.gz"
pg_dump -U visa_bulletin "$CURRENT_DB" | gzip > "$BACKUP_DIR/$ARCHIVE_NAME"
echo "Archived to: $BACKUP_DIR/$ARCHIVE_NAME"

# 8. Clean up old archives (keep only MAX_BACKUPS)
echo "=== Cleaning up old archives ==="
ARCHIVE_COUNT=$(ls -1 "$BACKUP_DIR"/visa_bulletin_*.sql.gz | wc -l)
if [[ "$ARCHIVE_COUNT" -gt "$MAX_BACKUPS" ]]; then
    DELETE_COUNT=$((ARCHIVE_COUNT - MAX_BACKUPS))
    echo "Deleting $DELETE_COUNT old archives..."
    ls -1t "$BACKUP_DIR"/visa_bulletin_*.sql.gz | tail -n "$DELETE_COUNT" | xargs rm -f
fi

# 9. Perform database swap
echo "=== Swapping databases ==="
echo "Old active: $CURRENT_DB"
echo "New active: $INACTIVE_DB"

# Update environment file
sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://visa_bulletin:PASSWORD@localhost:5432/$INACTIVE_DB|" \
    /etc/visa-bulletin/env

# Restart service (2-3 second downtime)
echo "Restarting service..."
systemctl restart visa-bulletin

# Wait for service to start
sleep 5

# 10. Verify swap succeeded
NEW_ACTIVE=$(systemctl show visa-bulletin -p Environment | grep DATABASE_URL | cut -d'/' -f4)
if [[ "$NEW_ACTIVE" == "$INACTIVE_DB" ]]; then
    echo "✅ Swap successful: Now using $INACTIVE_DB"
else
    echo "ERROR: Swap verification failed"
    # Rollback
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://visa_bulletin:PASSWORD@localhost:5432/$CURRENT_DB|" \
        /etc/visa-bulletin/env
    systemctl restart visa-bulletin
    exit 1
fi

# 11. Final verification
echo "=== Final verification ==="
curl -f http://localhost:8000/salaries/ > /dev/null 2>&1
if [[ $? -eq 0 ]]; then
    echo "✅ Application responding correctly"
else
    echo "ERROR: Application health check failed"
    exit 1
fi

echo "=== Data Refresh Complete: $(date) ==="
echo "Summary:"
echo "  - New sources ingested: $NEW_SOURCES"
echo "  - Active database: $INACTIVE_DB"
echo "  - Archive: $ARCHIVE_NAME"
echo "  - Downtime: ~2-3 seconds (service restart)"
```

### Monitoring and Alerting

**Log files:**
- `/var/log/visa-bulletin/refresh_*.log` - Refresh logs
- Monitor for errors: `grep -i error /var/log/visa-bulletin/refresh_*.log`

**Alerting (future):**
- Email notification on failure
- Slack webhook for status updates
- Datadog/CloudWatch metrics

---

## Rollback Strategy

### Automatic Rollback

**Trigger conditions:**
- Smoke tests fail
- Database swap verification fails
- Application health check fails after swap

**Rollback process:**
1. Revert `DATABASE_URL` to previous database
2. Restart service
3. Keep failed refresh database for investigation

### Manual Rollback

**If issues detected after successful swap:**

```bash
# 1. Check current active database
grep DATABASE_URL /etc/visa-bulletin/env

# 2. Determine previous database
# If current is blue, previous is green (and vice versa)

# 3. Update environment
sudo sed -i 's|visa_bulletin_blue|visa_bulletin_green|' /etc/visa-bulletin/env
# (or reverse)

# 4. Restart service
sudo systemctl restart visa-bulletin

# 5. Verify
curl http://localhost:8000/salaries/
```

**Downtime:** ~2-3 seconds (service restart)

### Rollback from Archive

**If both databases are corrupted:**

```bash
# 1. Find most recent archive
ls -lt /var/backups/visa-bulletin/*.sql.gz | head -1

# 2. Restore from archive
ARCHIVE="/var/backups/visa-bulletin/visa_bulletin_blue_20260120_020000.sql.gz"
gunzip -c "$ARCHIVE" | psql -U visa_bulletin visa_bulletin_blue

# 3. Update environment to use restored database
sudo sed -i 's|DATABASE_URL=.*|DATABASE_URL=postgresql://visa_bulletin:PASSWORD@localhost:5432/visa_bulletin_blue|' \
    /etc/visa-bulletin/env

# 4. Restart service
sudo systemctl restart visa-bulletin
```

**Recovery time:** ~10-30 minutes (depends on database size)

---

## Implementation Guide

### 1. Initial Setup

```bash
# 1. Create databases
psql -U postgres -c "CREATE DATABASE visa_bulletin_blue;"
psql -U postgres -c "CREATE DATABASE visa_bulletin_green;"

# 2. Migrate initial database
export DATABASE_URL="postgresql://visa_bulletin:PASSWORD@localhost:5432/visa_bulletin_blue"
cd /opt/visa_bulletin
bazel run //:migrate

# 3. Copy blue → green (both start identical)
psql -U postgres -c "CREATE DATABASE visa_bulletin_green TEMPLATE visa_bulletin_blue;"

# 4. Create backup directory
sudo mkdir -p /var/backups/visa-bulletin
sudo chown visa-bulletin:visa-bulletin /var/backups/visa-bulletin

# 5. Install refresh script
sudo cp scripts/cron/refresh_data.sh /opt/visa_bulletin/scripts/cron/
sudo chmod +x /opt/visa_bulletin/scripts/cron/refresh_data.sh

# 6. Add to crontab
sudo crontab -u visa-bulletin -e
# Add: 0 2 * * 0 /opt/visa_bulletin/scripts/cron/refresh_data.sh >> /var/log/visa-bulletin/refresh.log 2>&1
```

### 2. Development Workflow

**Development uses single database (no blue-green needed):**

```bash
# Dev settings
export DATABASE_URL="postgresql://user:pass@localhost:5432/visa_bulletin_dev"

# Manual refresh (when needed)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest
```

### 3. Testing the Refresh Pipeline

**Dry run (test mode):**

```bash
# Run refresh script manually (not via cron)
cd /opt/visa_bulletin
sudo -u visa-bulletin bash scripts/cron/refresh_data.sh
```

**Monitoring during test:**

```bash
# Watch logs
tail -f /var/log/visa-bulletin/refresh_*.log

# Check database sizes
psql -U postgres -c "\l+ visa_bulletin_*"

# Check active database
systemctl show visa-bulletin -p Environment | grep DATABASE_URL
```

---

## Storage Management

### Disk Space Requirements

**Per refresh cycle:**
- Active database: ~10 GB
- Inactive database (being refreshed): ~10 GB
- Archive (compressed): ~2-3 GB
- Total: ~22-23 GB per cycle

**With 3 archives:**
- ~28-32 GB total

**Lightsail instance storage options:**
- **512MB RAM:** $3.50-5/month with **20 GB SSD** ❌ Too small for Bazel
- **1GB RAM:** $5/month with **40 GB SSD** (minimal for blue-green)
- **2GB RAM:** $10/month with **60 GB SSD** (comfortable for blue-green)
- **4GB RAM:** $20/month with **80 GB SSD** ✅ **CURRENT INSTANCE** (plenty of headroom)

**Current usage (4GB/80GB instance):**
- Total disk: **80 GB**
- PostgreSQL data: **~5-6 GB estimated** per database
- Plenty of headroom for blue-green + archives

**Storage breakdown for blue-green approach:**
- Blue database (active): **~6 GB**
- Green database (during refresh): **~6 GB**
- Archives (compressed, 3 kept): **~1.5 GB** × 3 = **~4.5 GB**
- OS + app + logs: **~2 GB**
- **Total needed during refresh: ~18.5 GB**
- **Available on 80GB instance: ~60 GB headroom** ✅

### Instance Details

**New instance (Ubuntu 22.04 LTS, 4GB RAM / 80 GB SSD):**
- **IP Address:** `98.93.205.102`
- **OS:** Ubuntu 22.04 LTS (Jammy Jellyfish)
- **Instance Size:** 4GB RAM / 80 GB SSD ($20/month)
- **Status:** New instance - setup pending
- **SSH Key:** `~/.ssh/lightsail_visa_bulletin`
- **SSH Public Key:** `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIHUhxqP1pAIvm8jMq/lCDwFBPJhTedyXRKCSARmyBtX lightsail-visa-bulletin-20251204`

**SSH Setup:**
1. **Add SSH key to instance** (choose one method):
   - **Option A:** Via Lightsail console → Instance → Connect using SSH → Add your public key
   - **Option B:** Use Lightsail browser-based SSH to add key manually:
     ```bash
     # On the new instance, add the public key:
     echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIHUhxqP1pAIvm8jMq/lCDwFBPJhTedyXRKCSARmyBtX lightsail-visa-bulletin-20251204" >> ~/.ssh/authorized_keys
     ```
   - **Option C:** If instance was created with a different key pair, download that key from Lightsail console

2. **Test SSH connection:**
   ```bash
   ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@98.93.205.102
   ```

3. **Add to SSH config** (optional, for easier access):
   ```bash
   # Add to ~/.ssh/config:
   Host lightsail-new
       HostName 98.93.205.102
       User ubuntu
       IdentityFile ~/.ssh/lightsail_visa_bulletin
       StrictHostKeyChecking no
   ```
   Then connect with: `ssh lightsail-new`

**Previous instance (512MB RAM / 20 GB SSD):**
- **Status:** Decommissioned (upgraded to 4GB in Jan 2026)

### Operating System Selection

**Recommended: Ubuntu 22.04 LTS (Jammy Jellyfish)**

When setting up a new Lightsail instance, choose:
- **Platform:** Linux/Unix
- **Blueprint:** Ubuntu 22.04 LTS (not 24.04 LTS)
- **Instance size:** 4GB RAM / 80 GB SSD ($20/month) - see [Bazel Memory Requirements](#bazel-memory-requirements) below

#### Why Ubuntu Over Amazon Linux 2023

**Ubuntu advantages:**
- ✅ **Better Docker support:** More documentation, community examples, and troubleshooting resources
- ✅ **Broader ecosystem:** More Python/Django packages and tools readily available
- ✅ **Easier troubleshooting:** Larger community with more Stack Overflow answers and tutorials
- ✅ **PostgreSQL compatibility:** All required packages (including `postgresql-devel` for `psycopg2`) available in standard repos
- ✅ **Proven stack:** Widely used for Django/Docker/PostgreSQL deployments

**Amazon Linux 2023 issues:**
- ❌ **Missing packages:** `postgresql-devel` not available in standard repos (GitHub issue #351), causing `psycopg2` compilation failures
- ❌ **More Docker security advisories:** More CVEs and security patches required
- ❌ **Less community documentation:** Fewer resources for Django/Docker troubleshooting

#### Why Ubuntu 22.04 LTS Over 24.04 LTS

**Ubuntu 22.04 LTS advantages:**
- ✅ **Production stability:** Mature, widely tested, no known critical Docker issues
- ✅ **No critical bugs:** Avoids AppArmor Docker shutdown bug in 24.04 (Bug #2063099)
- ✅ **PostgreSQL 14:** Stable, proven version (vs PG16 in 24.04 requiring migration)
- ✅ **Proven reliability:** Battle-tested in production environments

**Ubuntu 24.04 LTS issues:**
- ❌ **Critical Docker bug:** AppArmor blocks SIGTERM signals to containers, causing:
  - Containers force-killed after 10 seconds instead of graceful shutdown
  - **Data corruption risk** for PostgreSQL (can't flush state before SIGKILL)
  - Bug not fully fixed in distro packages as of late 2024
- ❌ **Upgrade complexity:** PostgreSQL 14 → 16 migration required
- ❌ **Less mature:** Newer release with fewer production deployments

**Note:** If you need 24.04 features later, wait for 24.04.1 or 24.04.2 point releases after the Docker bug is fixed, or use Docker CE from upstream repositories instead of the distro's `docker.io` package.

#### Performance Implications by OS

**Ubuntu 22.04 LTS:**
- **Docker performance:** Excellent - mature Docker support, reliable container lifecycle management
- **PostgreSQL performance:** Optimal - PostgreSQL 14 is well-tuned, stable query planner
- **Bazel performance:** Good - standard JVM performance, no OS-specific issues
- **Memory efficiency:** Standard - typical Linux memory overhead (~200-300MB base)
- **I/O performance:** Good - standard Linux I/O scheduler, works well with SSD storage
- **Network performance:** Standard - standard Linux networking stack

**Ubuntu 24.04 LTS:**
- **Docker performance:** ⚠️ **Degraded** - AppArmor bug causes improper container shutdowns, potential data loss
- **PostgreSQL performance:** Good - PostgreSQL 16 has query improvements, but requires migration
- **Bazel performance:** Good - newer kernel (6.8) may have slight performance improvements
- **Memory efficiency:** Slightly better - newer kernel has improved memory management
- **I/O performance:** Slightly better - kernel 6.8 has improved I/O schedulers
- **Network performance:** Slightly better - newer networking stack optimizations

**Amazon Linux 2023:**
- **Docker performance:** Good - AWS-optimized, but more security patches required
- **PostgreSQL performance:** ⚠️ **Degraded** - missing `postgresql-devel` causes build issues, may need workarounds
- **Bazel performance:** Good - standard JVM performance
- **Memory efficiency:** Slightly better - AWS-optimized kernel, minimal base footprint
- **I/O performance:** Optimized - AWS-tuned I/O for EBS volumes (less relevant for Lightsail local SSD)
- **Network performance:** Optimized - AWS-optimized networking stack

**Performance Summary:**
- **Best overall:** Ubuntu 22.04 LTS - best balance of stability, performance, and compatibility
- **Best for AWS integration:** Amazon Linux 2023 - but compatibility issues outweigh benefits
- **Best for cutting-edge:** Ubuntu 24.04 LTS - but critical Docker bug makes it unsuitable for production databases

**Recommendation:** Choose Ubuntu 22.04 LTS for production. The stability and proven reliability outweigh the minor performance improvements in newer releases, especially given the critical Docker bug in 24.04 that could cause database corruption.

### Bazel Memory Requirements

**Bazel is required** for the automated refresh pipeline (`scripts/cron/refresh_data.sh`). All data refresh operations use `bazel run` commands.

**Bazel memory requirements:**
- **Minimum JVM heap:** 2 GB (`-Xmx2g` flag)
- **Realistic minimum total RAM:** 4 GB for comfortable operation
- **Current instance:** 4 GB RAM ✅ **Runs Bazel well**

**Current configuration:**
- 4GB RAM instance ($20/month, 80 GB SSD) ✅ **CURRENT INSTANCE**
- Comfortable RAM for Bazel + clustering operations
- Plenty of storage for blue-green + archives
- Good clustering performance

**Important:** Always use Bazel for both local development and production. Never use plain `python` commands - use `bazel run` targets instead. This ensures:
- Consistent environment between local and production
- Proper dependency management
- Reproducible builds

### Monitoring Disk Space

```bash
# Check overall disk usage
df -h /

# Check database sizes
psql -U postgres -c "\l+ visa_bulletin_*"

# Check PostgreSQL data directory
du -sh /var/lib/postgresql/

# Check archive directory
du -sh /var/backups/visa-bulletin/

# Breakdown by component
echo "Blue database:"
psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('visa_bulletin_blue'));"

echo "Green database:"
psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('visa_bulletin_green'));"

echo "Archives:"
du -sh /var/backups/visa-bulletin/*.sql.gz

# Automated check (add to refresh script)
DISK_USAGE=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
if [[ "$DISK_USAGE" -gt 80 ]]; then
    echo "WARNING: Disk usage at ${DISK_USAGE}%"
    # Trigger alert or cleanup old archives
fi
```

**Lightsail-specific monitoring:**
```bash
# Check what's using space
du -sh /var/lib/postgresql/* | sort -h
du -sh /var/backups/* | sort -h

# Check if approaching Lightsail instance limit
TOTAL_GB=$(df -BG / | awk 'NR==2 {print $2}' | sed 's/G//')
USED_GB=$(df -BG / | awk 'NR==2 {print $3}' | sed 's/G//')
echo "Using $USED_GB GB of $TOTAL_GB GB available"
```

---

## Related Documentation

- **Ingestion Playbook:** `docs/INGESTION_PLAYBOOK.md`
- **Database Design:** `docs/department_of_labor/SALARY_DATABASE_DESIGN.md`
- **Rollout Flow:** `docs/deployment/ROLLOUT_FLOW.md`
- **Rollback Procedures:** This document (Rollback Strategy section)

---

## Change Log

- **2026-01-21:** Initial design for blue-green database refresh
  - Chose separate databases over schema swap
  - Designed automated cron job pipeline
  - Defined rollback and archive strategy
