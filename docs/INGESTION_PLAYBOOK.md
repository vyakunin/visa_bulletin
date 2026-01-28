# DOL Data Ingestion Playbook

**Complete step-by-step guide for ingesting Department of Labor H-1B/PERM data.**

## Overview

This playbook covers the complete ingestion workflow, from initial setup through post-ingestion processing and verification.

## Table of Contents

1. [Production vs Development](#production-vs-development)
2. [Pre-Ingestion Setup](#pre-ingestion-setup)
3. [Ingestion Process](#ingestion-process)
4. [Post-Ingestion Processing](#post-ingestion-processing)
5. [Verification](#verification)
6. [Troubleshooting](#troubleshooting)
7. [Performance Optimization](#performance-optimization)

---

## Production vs Development

### Production (Automated - Blue-Green Refresh)

**DO NOT run manual ingestion in production.**

Production uses an automated blue-green database refresh strategy with near-zero downtime:

- **Automated cron job** runs weekly (Sunday 2:00 AM)
- **Blue-green databases** allow refresh without affecting live traffic
- **Complete workflow:** Discover sources → Copy DB → Ingest → Process → Test → Swap
- **Rollback capability** with archived versions
- **Near-zero downtime** (~2-3 seconds during swap)

**See:** `docs/DATA_REFRESH_STRATEGY.md` for complete production refresh workflow.

**Monitoring production refresh:**
```bash
# Check refresh logs
tail -f /var/log/visa-bulletin/refresh_*.log

# Check current active database
systemctl show visa-bulletin -p Environment | grep DATABASE_URL
```

### Development (Manual - This Playbook)

**This playbook is for development/testing only.**

Development workflow:
- Single database (no blue-green needed)
- Manual ingestion following steps below
- Can tolerate temporary inconsistent state
- Faster iteration for testing and debugging

**When to use this playbook:**
- Testing new ingestion logic
- Debugging data issues
- Manual backfill operations
- Local development

---

## Pre-Ingestion Setup

### 1. Check Database State

```bash
# Check for running ingests
bazel run //scripts/ingest:run_pipeline -- status | grep "RUNNING"

# If any running, wait for completion or investigate
```

### 2. Check Index Status (Optional for Large Ingests)

For bulk imports of historical data (multiple quarters/years), consider dropping indexes for faster ingestion:

```bash
# List current indexes
bazel run //scripts/salary:manage_salary_indexes -- --list

# Drop non-unique indexes (saves snapshot automatically)
bazel run //scripts/salary:manage_salary_indexes -- --drop \
  --snapshot data/index_snapshots/salary_indexes.yaml --overwrite

# Note: Unique indexes and primary keys are preserved
```

**When to drop indexes:**
- ✅ Importing multiple fiscal years (10+ files)
- ✅ Initial database setup with large historical data
- ❌ Single file imports (overhead not worth it)
- ❌ Small incremental updates

### 3. Check Available Data Sources

```bash
# Check what's available to ingest
bazel run //scripts/ingest:run_pipeline -- check-completeness

# Look for:
# - "Not ingested (available)" - files that need ingestion
# - "Broken links (404)" - files not yet released by DOL
```

---

## Ingestion Process

### Option A: Ingest Specific Source IDs

Use when you know the source IDs from database:

```bash
# Single source
bazel run //scripts/ingest:run_pipeline -- run --source-id 6

# Multiple sources sequentially
for source_id in 6 7 8 9; do
  bazel run //scripts/ingest:run_pipeline -- run --source-id $source_id
  if [ $? -ne 0 ]; then
    echo "❌ Failed at source $source_id"
    break
  fi
done
```

### Option B: Discover and Ingest New Sources

Use when DOL has released new files not yet in database:

```bash
# Discover new sources and add to database
bazel run //scripts/ingest:run_pipeline -- discover

# Ingest all discovered sources
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest
```

### Monitoring Long-Running Ingests

For files with 100k+ records:

```bash
# Run in background with logging
bazel run //scripts/ingest:run_pipeline -- run --source-id 6 \
  > /tmp/ingest_fy2024_q1.log 2>&1 &
PID=$!

# Monitor progress (checks every minute)
for i in {1..60}; do
  sleep 60
  echo "=== Check $i (after $i minutes) ==="
  tail -5 /tmp/ingest_fy2024_q1.log
  
  # Check for completion
  if grep -q "Pipeline completed successfully" /tmp/ingest_fy2024_q1.log; then
    echo "✅ SUCCESS!"
    tail -30 /tmp/ingest_fy2024_q1.log
    break
  fi
  
  # Check for errors
  if grep -q "Pipeline failed\|ERROR" /tmp/ingest_fy2024_q1.log; then
    echo "❌ ERROR detected"
    tail -50 /tmp/ingest_fy2024_q1.log
    break
  fi
done
```

### Resume Failed Ingests

The pipeline supports resumption via checkpoints:

```bash
# Resume from last checkpoint
bazel run //scripts/ingest:run_pipeline -- resume --source-id 6

# Force restart from beginning (clears checkpoints)
bazel run //scripts/ingest:run_pipeline -- run --source-id 6 --force-restart
```

---

## Post-Ingestion Processing

**Run these steps AFTER all ingestion completes:**

### 1. Recreate Indexes (If Dropped)

```bash
# Recreate indexes from snapshot
bazel run //scripts/salary:manage_salary_indexes -- --recreate \
  --snapshot data/index_snapshots/salary_indexes.yaml

# Verify indexes restored
bazel run //scripts/salary:manage_salary_indexes -- --list
```

**Time:** ~5-10 minutes for full database.

### 2. Backfill Job Title Links

Links `SalaryRecord` entries to `JobTitle` entities:

```bash
bazel run //scripts/salary:backfill_job_title_links
```

**Expected output:**
- Processed: ~600k unlinked records
- Linked: ~300k-400k records (50-60%)
- Not found: ~200k-300k records (job titles not yet clustered)

**Time:** ~5-10 minutes for full database.

### 3. Backfill Source File Dates

Updates `source_file_date` for records missing this field:

```bash
bazel run //scripts/salary:backfill_source_file_date
```

**Expected output:**
- Updated: ~400k records

**Time:** ~8-10 minutes for full database.

### 4. Cluster Job Titles

Creates `JobTitle` entities and `JobTitleCluster` groupings. **Note:** This creates entities but does NOT update statistics (done separately in step 6).

```bash
# Development (local machine with RAM):
bazel run //scripts/salary:cluster_job_titles

# Production (<4GB RAM) - Build, shutdown Bazel server, then run:
bazel build //scripts/salary:cluster_job_titles && \
bazel shutdown && \
cd /opt/visa_bulletin && set -a && source .env && set +a && \
DB_HOST=localhost nohup ./bazel-bin/scripts/salary/cluster_job_titles \
  > /var/log/visa-bulletin/cluster_job_titles.log 2>&1 &
```

**Why `bazel shutdown`?** Bazel server uses ~400-500MB RAM. On 2GB instances, this memory is critical for clustering scripts.

**Expected output:**
- Job titles processed: ~120k
- Auto-clustered: ~10k-15k
- New clusters created: ~10k-15k
- SalaryRecords linked: ~400k-500k

**Time:** ~5-10 minutes for full database.

**Performance note:** Phase 3 (linking) iterates through all JobTitle entities but does NOT update statistics (no COUNT queries). Statistics are updated separately in step 6.

### 5. Cluster Employers

Creates `EmployerCluster` groupings and links duplicate employers:

```bash
# Development (local machine with RAM):
bazel run //scripts/salary:cluster_existing_employers \
  > /tmp/employer_clustering.log 2>&1 &

# Production (<4GB RAM) - Build, shutdown Bazel server, then run:
bazel build //scripts/salary:cluster_existing_employers && \
bazel shutdown && \
cd /opt/visa_bulletin && set -a && source .env && set +a && \
DB_HOST=localhost nohup ./bazel-bin/scripts/salary/cluster_existing_employers \
  > /var/log/visa-bulletin/cluster_employers.log 2>&1 &

# Monitor progress
tail -f /var/log/visa-bulletin/cluster_employers.log

# Check for errors
grep "Error\|ValueError" /var/log/visa-bulletin/cluster_employers.log
```

**Why `bazel shutdown`?** Bazel server uses ~400-500MB RAM. On 2GB instances, this memory is critical for clustering scripts.

**Expected output:**
- Employers processed: ~600k
- Auto-clustered: ~50k-100k pairs
- Clusters created: ~500k-550k

**Time:** 30-60 minutes for full database (processes millions of pairs with LSH optimization).

**Note:** Employer clustering improves:
- Employer profile pages (merges duplicate employer names)
- Employer search accuracy
- Data quality metrics

### 6. Update Job Title Statistics

Updates aggregate statistics for `JobTitle` entities:

```bash
bazel run //scripts/salary:update_job_title_cluster_stats
```

**Expected output:**
- Updated statistics for ~100k JobTitle entities

**Time:** ~2-5 minutes.

### 7. Restart Development Server

Pick up new data in the web interface:

```bash
./scripts/restart_server.sh --background

# Verify server running
curl -I http://localhost:8000/
```

---

## Verification

### 1. Check Ingestion Completeness

```bash
# Check all sources ingested successfully
bazel run //scripts/ingest:run_pipeline -- check-completeness

# Should show:
# - ✓ Ingested: (high number)
# - ✗ Not ingested: 0-2 (only newly released files)
```

### 2. Verify Record Counts

```bash
# Check records for specific fiscal year
bazel run //:explore_db -- --query "
  SELECT 
    fiscal_year,
    COUNT(*) as records,
    source_file
  FROM salary_record 
  WHERE fiscal_year IN (2022, 2024)
  GROUP BY fiscal_year, source_file
  ORDER BY fiscal_year, source_file
"
```

**Expected for FY2024:**
- Q1: ~3,000-20,000 records
- Q2: ~3,000-20,000 records
- Q3: ~1,500-25,000 records
- Q4: ~3,000-20,000 records
- PERM Q4: ~80,000-100,000 records

### 3. Check Web Interface

```bash
# Search for data in specific years
curl -s "http://localhost:8000/salaries/?job_title=software+engineer&fiscal_year=2024" \
  | grep "FY 2024"

# Should return search results with FY2024 data
```

### 4. Verify Job Title Links

```bash
bazel run //:explore_db -- --query "
  SELECT 
    COUNT(*) as total_records,
    COUNT(job_title_entity_id) as linked_records,
    ROUND(100.0 * COUNT(job_title_entity_id) / COUNT(*), 1) as link_percentage
  FROM salary_record
"
```

**Expected:**
- Link percentage: 50-75% (many job titles have unique variations)

### 5. Check Employer Clustering

```bash
bazel run //:explore_db -- --query "
  SELECT 
    COUNT(DISTINCT canonical_cluster_id) as unique_clusters,
    COUNT(*) as total_employers,
    COUNT(*) - COUNT(DISTINCT canonical_cluster_id) as employers_merged
  FROM employer
  WHERE canonical_cluster_id IS NOT NULL
"
```

**Expected:**
- Unique clusters: ~500k-550k (from ~600k employers)
- Employers merged: ~50k-100k (duplicates consolidated)

---

## Troubleshooting

### Issue: `invalid input syntax for type numeric`

**Symptom:** Error during COPY operation, numeric field receives string value.

**Root Cause:** Field misalignment due to unescaped special characters (backslashes, tabs) in text fields.

**Fix Applied:** `lib/ingest/orchestrator.py` now escapes backslashes FIRST:
```python
str_value = (str(value)
    .replace('\\', '\\\\')  # Escape backslashes FIRST
    .replace('\t', ' ')
    .replace('\n', ' ')
    .replace('\r', ' '))
```

**Verification:** Check COPY buffer saved to `/tmp/copy_buffer_WorksiteRecord.tsv` for proper escaping.

### Issue: Import Completes with 0 Records

**Symptom:** "No records created from source file" error.

**Common Causes:**
1. Appendix files (contain definitions, not data)
2. Worksite files for quarters without worksites
3. All records already exist (duplicates skipped)

**Resolution:**
- Appendix files: Expected, skip them
- Check `ingest_run` table for previous successful imports
- Use `--force-restart` to clear checkpoints if needed

### Issue: Slow Ingestion Performance

**Symptoms:**
- <1,000 records/sec throughput
- Load stage >85% of total time

**Diagnosis:**
```bash
# Check for indexes during ingestion
bazel run //scripts/salary:manage_salary_indexes -- --list
```

**Fix:**
- Drop indexes before large imports (see Pre-Ingestion Setup)
- Recreate after ingestion completes

### Issue: Employer Clustering Fails with "unsaved related object" (FIXED)

**Symptom:** 
```
ValueError: bulk_update() prohibited to prevent data loss due to unsaved related object 'canonical_cluster'.
```

**Root Cause:** Cache inconsistency in `BatchedUpdates.flush_clusters()` - lookups used normalized keys but cache updates used original canonical_name keys, causing cache misses for different casing variations.

**Status:** ✅ **FIXED** (2026-01-21)
- Updated `lib/utils/db_utils.py` to use normalized keys consistently
- Cache now properly maintains references to saved cluster instances
- Employer clustering should work reliably now

**If you still encounter this issue:**
- Clear clustering state: `bazel run //scripts/salary:cluster_existing_employers -- --reset-clustering`
- Run clustering again: `bazel run //scripts/salary:cluster_existing_employers`

### Issue: Employer Clustering Takes Too Long

**Symptom:** Clustering runs for 2+ hours without completion.

**Diagnosis:**
```bash
# Check progress in logs
tail -f /tmp/employer_clustering.log
grep "Processed.*pairs" /tmp/employer_clustering.log
```

**Optimization:**
- Use `--limit-employers` flag for testing
- Ensure LSH (MinHash) is working (should see "LSH candidate pairs" in logs)
- Check for stuck queries: `SELECT * FROM pg_stat_activity WHERE state = 'active'`

### Issue: Job Title Linking Low Percentage

**Symptom:** <30% of records linked to job titles.

**Cause:** Job titles not yet clustered, or normalization differences.

**Fix:**
```bash
# Re-run job title clustering
bazel run //scripts/salary:cluster_job_titles

# Then backfill links again
bazel run //scripts/salary:backfill_job_title_links
```

---

## Performance Optimization

### Ingestion Performance

**Baseline:** ~20-50 records/sec with indexes
**Optimized:** ~200-500 records/sec without indexes

**Optimization checklist:**
- ✅ Drop non-unique indexes before large imports
- ✅ Use PostgreSQL (not SQLite)
- ✅ Batch size: 10,000 records (auto-tuned)
- ✅ PostgreSQL COPY for bulk inserts
- ✅ Pre-load employer cache (~600k employers in memory)

### Clustering Performance

**Employer Clustering:**
- LSH (MinHash) for candidate generation: ~10,000+ pairs/sec
- String similarity scoring: ~5,000+ pairs/sec
- Expected: 30-60 minutes for 600k employers

**Job Title Clustering:**
- Normalization and grouping: ~2,000-5,000 titles/sec
- Expected: 5-10 minutes for 120k titles

### Memory Usage

**Expected:**
- Ingestion: ~500MB-1GB (employer cache)
- Employer clustering: ~2-3GB (LSH index + employer data)
- Job title clustering: ~300-500MB

**Limits:**
- Max employer cache: ~1M employers (~4-5GB)
- LSH index growth: O(n) with employers

---

## Quick Reference

### Post-Ingestion Checklist

Run these in order after ALL ingestion completes:

```bash
# 1. Recreate indexes (if dropped)
bazel run //scripts/salary:manage_salary_indexes -- --recreate

# 2. Backfill job title links (~5-10 min)
bazel run //scripts/salary:backfill_job_title_links

# 3. Backfill source file dates (~8-10 min)
bazel run //scripts/salary:backfill_source_file_date

# 4. Cluster job titles (~5-10 min)
bazel run //scripts/salary:cluster_job_titles

# 5. Cluster employers (~30-60 min, run in background)
bazel run //scripts/salary:cluster_existing_employers > /tmp/employer_clustering.log 2>&1 &

# 6. Update job title stats (~2-5 min)
bazel run //scripts/salary:update_job_title_cluster_stats

# 7. Restart dev server
./scripts/restart_server.sh --background
```

**Total time:** ~50-90 minutes for full post-ingestion processing.

### Verification Checklist

```bash
# Check completeness
bazel run //scripts/ingest:run_pipeline -- check-completeness

# Check record counts
bazel run //:explore_db -- --query "
  SELECT fiscal_year, COUNT(*) 
  FROM salary_record 
  GROUP BY fiscal_year 
  ORDER BY fiscal_year DESC
"

# Check job title links
bazel run //:explore_db -- --query "
  SELECT 
    COUNT(*) as total,
    COUNT(job_title_entity_id) as linked,
    ROUND(100.0 * COUNT(job_title_entity_id) / COUNT(*), 1) as pct
  FROM salary_record
"

# Check employer clusters
bazel run //:explore_db -- --query "
  SELECT 
    COUNT(DISTINCT canonical_cluster_id) as clusters,
    COUNT(*) as employers
  FROM employer 
  WHERE canonical_cluster_id IS NOT NULL
"

# Verify web interface
curl -I http://localhost:8000/salaries/
```

---

## Related Documentation

- **Production Data Refresh:** `docs/DATA_REFRESH_STRATEGY.md` - Blue-green automated refresh
- **Pipeline Architecture:** `docs/ingest/ARCHITECTURE.md`
- **Plugin Development:** `docs/ingest/PLUGIN_GUIDE.md`
- **Employer Clustering:** `lib/business/salary/README.md`
- **Database Design:** `docs/department_of_labor/SALARY_DATABASE_DESIGN.md`
- **Troubleshooting:** `docs/TROUBLESHOOTING.md`

---

## Change Log

- **2026-01-21:** Fixed employer clustering bug
  - Root cause: Cache inconsistency in BatchedUpdates.flush_clusters()
  - Fix: Use normalized keys consistently in cache operations
  - Employer clustering now works reliably (was failing with "unsaved related object" error)
  - Updated playbook to reflect fixed status

- **2026-01-19:** Initial playbook created after FY2022/FY2024 ingestion
  - Root cause: Backslash escaping bug in COPY operations
  - Fix: Escape backslashes FIRST in orchestrator.py
  - Added comprehensive verification steps
  - Documented employer clustering (30-60 min runtime)
