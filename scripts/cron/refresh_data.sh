#!/bin/bash
# scripts/cron/refresh_data.sh
# Automated blue-green database refresh with rollback capability
#
# This script runs weekly to discover and ingest new DOL data sources.
# Uses blue-green database strategy for near-zero downtime deployment.
#
# Schedule: Weekly on Sunday at 2:00 AM
# Cron entry: 0 2 * * 0 /opt/visa_bulletin/scripts/cron/refresh_data.sh >> /var/log/visa-bulletin/refresh.log 2>&1

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="/var/log/visa-bulletin/refresh_$(date +%Y%m%d_%H%M%S).log"
BACKUP_DIR="/var/backups/visa-bulletin"
MAX_BACKUPS=3  # Keep 3 old versions (current + 2 archives)

# Database credentials (read from environment or config file)
DB_USER="${DB_USER:-visa_bulletin}"
DB_PASSWORD="${DB_PASSWORD:-}"  # Should be in environment or ~/.pgpass

# Logging
exec > >(tee -a "$LOG_FILE") 2>&1
echo "======================================================================="
echo "=== Data Refresh Started: $(date) ==="
echo "======================================================================="

# Function: Log with timestamp
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

# Function: Check disk space
check_disk_space() {
    local threshold=80
    local usage=$(df -h /var/lib/postgresql 2>/dev/null | awk 'NR==2 {print $5}' | sed 's/%//')
    
    if [[ -z "$usage" ]]; then
        log "WARNING: Could not determine disk usage"
        return 0
    fi
    
    if [[ "$usage" -gt "$threshold" ]]; then
        log "ERROR: Disk usage at ${usage}% (threshold: ${threshold}%)"
        return 1
    fi
    
    log "Disk usage: ${usage}% (OK)"
    return 0
}

# 1. Check disk space before starting
log "Checking disk space..."
if ! check_disk_space; then
    log "ERROR: Insufficient disk space. Aborting."
    exit 1
fi

# 2. Detect current active database
log "Detecting current active database..."
ENV_FILE="/etc/visa-bulletin/env"
if [[ ! -f "$ENV_FILE" ]]; then
    log "ERROR: Environment file not found: $ENV_FILE"
    exit 1
fi

CURRENT_DB=$(grep "^DATABASE_URL=" "$ENV_FILE" | cut -d'/' -f4)
if [[ "$CURRENT_DB" == "visa_bulletin_blue" ]]; then
    INACTIVE_DB="visa_bulletin_green"
    NEXT_ACTIVE="green"
elif [[ "$CURRENT_DB" == "visa_bulletin_green" ]]; then
    INACTIVE_DB="visa_bulletin_blue"
    NEXT_ACTIVE="blue"
else
    log "ERROR: Could not determine active database from: $CURRENT_DB"
    exit 1
fi

log "Current active: $CURRENT_DB"
log "Refresh target: $INACTIVE_DB"

# 3. Discover new data sources
log "======================================================================="
log "=== Checking for new data sources ==="
log "======================================================================="

cd "$PROJECT_ROOT"
NEW_SOURCES_OUTPUT=$(bazel run //scripts/ingest:run_pipeline -- check-completeness 2>&1 || true)
NEW_SOURCES=$(echo "$NEW_SOURCES_OUTPUT" | grep -c "Not ingested (available)" || echo "0")

log "Discovery output:"
echo "$NEW_SOURCES_OUTPUT" | grep -E "(Not ingested|Ingested|Broken)" || true

if [[ "$NEW_SOURCES" -eq 0 ]]; then
    log "No new data sources found. Nothing to ingest."
    log "=== Data Refresh Complete (No Action Needed): $(date) ==="
    exit 0
fi

log "Found $NEW_SOURCES new data sources to ingest"

# 4. Create fresh database copy
log "======================================================================="
log "=== Copying database: $CURRENT_DB → $INACTIVE_DB ==="
log "======================================================================="

log "Dropping inactive database if it exists..."
psql -U "$DB_USER" -c "DROP DATABASE IF EXISTS $INACTIVE_DB;" 2>&1

log "Creating fresh copy from active database..."
psql -U "$DB_USER" -c "CREATE DATABASE $INACTIVE_DB TEMPLATE $CURRENT_DB;" 2>&1

log "Database copy complete"

# 5. Configure Django to use inactive database
export DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/$INACTIVE_DB"
log "Configured Django to use: $INACTIVE_DB"

# 6. Run complete ingestion pipeline
log "======================================================================="
log "=== Running ingestion pipeline on $INACTIVE_DB ==="
log "======================================================================="

# 6a. Drop indexes for faster ingestion
log "--- Dropping indexes for faster ingestion ---"
mkdir -p "$BACKUP_DIR"
INDEX_SNAPSHOT="$BACKUP_DIR/salary_indexes_$(date +%Y%m%d_%H%M%S).yaml"

bazel run //scripts/salary:manage_salary_indexes -- \
    --drop \
    --snapshot "$INDEX_SNAPSHOT" \
    --overwrite 2>&1

log "Indexes dropped. Snapshot saved to: $INDEX_SNAPSHOT"

# 6b. Discover and ingest new sources
log "--- Discovering and ingesting new sources ---"
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest 2>&1 | tee -a "$LOG_FILE"

if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
    log "ERROR: Ingestion failed"
    exit 1
fi

log "Ingestion complete"

# 6c. Run post-processing
log "--- Post-processing: Backfill job title links ---"
bazel run //scripts/salary:backfill_job_title_links 2>&1 | tail -20

log "--- Post-processing: Backfill source file dates ---"
bazel run //scripts/salary:backfill_source_file_date 2>&1 | tail -20

log "--- Post-processing: Cluster job titles ---"
bazel run //scripts/salary:cluster_job_titles 2>&1 | tail -20

log "--- Post-processing: Cluster employers (long-running) ---"
bazel run //scripts/salary:cluster_existing_employers 2>&1 | tail -30

log "--- Post-processing: Update job title stats ---"
bazel run //scripts/salary:update_job_title_cluster_stats 2>&1 | tail -20

# 6d. Recreate indexes
log "--- Recreating indexes ---"
bazel run //scripts/salary:manage_salary_indexes -- \
    --recreate \
    --snapshot "$INDEX_SNAPSHOT" 2>&1

log "Indexes recreated"

# 7. Run smoke tests
log "======================================================================="
log "=== Running smoke tests on $INACTIVE_DB ==="
log "======================================================================="

SMOKE_TEST_PASSED=true

# Test 1: Check record counts
log "Test 1: Checking total record count..."
RECORD_COUNT=$(psql -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM salary_record;" | tr -d ' ')

log "Total salary records: $RECORD_COUNT"
if [[ "$RECORD_COUNT" -lt 100000 ]]; then
    log "ERROR: Record count too low: $RECORD_COUNT (expected >100,000)"
    SMOKE_TEST_PASSED=false
fi

# Test 2: Check recent fiscal year data (use MAX fiscal year, not current calendar year)
log "Test 2: Checking recent fiscal year data..."
# DOL fiscal years end in September (FY2024 = Oct 2023 - Sep 2024)
# Check the most recent fiscal year in the database, not current calendar year
MAX_FISCAL_YEAR=$(psql -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT MAX(fiscal_year) FROM salary_record;" | tr -d ' ')

if [[ -z "$MAX_FISCAL_YEAR" ]]; then
    log "ERROR: No fiscal year data found in database"
    SMOKE_TEST_PASSED=false
else
    log "Most recent fiscal year in DB: $MAX_FISCAL_YEAR"
    RECENT_COUNT=$(psql -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
        "SELECT COUNT(*) FROM salary_record WHERE fiscal_year = $MAX_FISCAL_YEAR;" | tr -d ' ')
    
    log "Records for FY $MAX_FISCAL_YEAR: $RECENT_COUNT"
    if [[ "$RECENT_COUNT" -lt 1000 ]]; then
        log "WARNING: Very few records for most recent fiscal year $MAX_FISCAL_YEAR: $RECENT_COUNT"
    fi
    
    # Sanity check: most recent FY should be within 2 years of current calendar year
    CURRENT_YEAR=$(date +%Y)
    YEAR_DIFF=$((CURRENT_YEAR - MAX_FISCAL_YEAR))
    if [[ "$YEAR_DIFF" -gt 2 ]]; then
        log "WARNING: Most recent fiscal year $MAX_FISCAL_YEAR is ${YEAR_DIFF} years old (data may be stale)"
    fi
fi

# Test 3: Check employer clustering
log "Test 3: Checking employer clustering..."
CLUSTERED_EMPLOYERS=$(psql -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM employer WHERE canonical_cluster_id IS NOT NULL;" | tr -d ' ')

log "Clustered employers: $CLUSTERED_EMPLOYERS"
if [[ "$CLUSTERED_EMPLOYERS" -lt 100000 ]]; then
    log "WARNING: Low clustered employer count: $CLUSTERED_EMPLOYERS (expected >100,000)"
fi

# Test 4: Check job title links
log "Test 4: Checking job title links..."
LINKED_RECORDS=$(psql -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM salary_record WHERE job_title_entity_id IS NOT NULL;" | tr -d ' ')
LINK_PERCENTAGE=$((LINKED_RECORDS * 100 / RECORD_COUNT))

log "Linked records: $LINKED_RECORDS ($LINK_PERCENTAGE%)"
if [[ "$LINK_PERCENTAGE" -lt 30 ]]; then
    log "WARNING: Low job title link percentage: $LINK_PERCENTAGE% (expected >30%)"
fi

if [[ "$SMOKE_TEST_PASSED" != "true" ]]; then
    log "ERROR: Smoke tests failed. Aborting swap."
    exit 1
fi

log "✅ All smoke tests passed"

# 8. Archive current active database
log "======================================================================="
log "=== Archiving previous version ==="
log "======================================================================="

ARCHIVE_NAME="visa_bulletin_archive_${CURRENT_DB}_$(date +%Y%m%d_%H%M%S).sql.gz"
ARCHIVE_PATH="$BACKUP_DIR/$ARCHIVE_NAME"

log "Creating archive: $ARCHIVE_NAME"
pg_dump -U "$DB_USER" "$CURRENT_DB" | gzip > "$ARCHIVE_PATH"

ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
log "Archive created: $ARCHIVE_PATH ($ARCHIVE_SIZE)"

# 9. Clean up old archives (keep only MAX_BACKUPS)
log "--- Cleaning up old archives (keeping $MAX_BACKUPS most recent) ---"
ARCHIVE_COUNT=$(ls -1 "$BACKUP_DIR"/visa_bulletin_archive_*.sql.gz 2>/dev/null | wc -l)

log "Current archive count: $ARCHIVE_COUNT"
if [[ "$ARCHIVE_COUNT" -gt "$MAX_BACKUPS" ]]; then
    DELETE_COUNT=$((ARCHIVE_COUNT - MAX_BACKUPS))
    log "Deleting $DELETE_COUNT old archives..."
    
    # Delete oldest archives (keeping MAX_BACKUPS most recent)
    ls -1t "$BACKUP_DIR"/visa_bulletin_archive_*.sql.gz | tail -n "$DELETE_COUNT" | while read -r old_archive; do
        log "Deleting: $old_archive"
        rm -f "$old_archive"
    done
    
    log "Cleanup complete. Kept $MAX_BACKUPS most recent archives."
else
    log "No cleanup needed ($ARCHIVE_COUNT <= $MAX_BACKUPS)"
fi

# 10. Perform database swap
log "======================================================================="
log "=== Performing database swap ==="
log "======================================================================="

log "Swap details:"
log "  Old active: $CURRENT_DB"
log "  New active: $INACTIVE_DB"

# Update environment file
log "Updating environment file: $ENV_FILE"
sed -i.bak "s|DATABASE_URL=postgresql://.*|DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/$INACTIVE_DB|" \
    "$ENV_FILE"

# Restart service (2-3 second downtime)
log "Restarting visa-bulletin service..."
RESTART_START=$(date +%s)
systemctl restart visa-bulletin
RESTART_END=$(date +%s)
DOWNTIME=$((RESTART_END - RESTART_START))

log "Service restarted (downtime: ${DOWNTIME}s)"

# Wait for service to start
log "Waiting for service to stabilize..."
sleep 5

# 11. Verify swap succeeded
log "======================================================================="
log "=== Verifying database swap ==="
log "======================================================================="

NEW_ACTIVE=$(grep "^DATABASE_URL=" "$ENV_FILE" | cut -d'/' -f4)
log "New active database: $NEW_ACTIVE"

if [[ "$NEW_ACTIVE" == "$INACTIVE_DB" ]]; then
    log "✅ Swap successful: Now using $INACTIVE_DB"
else
    log "ERROR: Swap verification failed (expected: $INACTIVE_DB, got: $NEW_ACTIVE)"
    
    # Rollback
    log "Performing automatic rollback..."
    sed -i.bak "s|DATABASE_URL=postgresql://.*|DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/$CURRENT_DB|" \
        "$ENV_FILE"
    systemctl restart visa-bulletin
    
    log "Rolled back to: $CURRENT_DB"
    exit 1
fi

# 12. Final verification
log "--- Final application health check ---"
if curl -f -s http://localhost:8000/salaries/ > /dev/null 2>&1; then
    log "✅ Application responding correctly"
else
    log "ERROR: Application health check failed"
    
    # Rollback
    log "Performing automatic rollback due to health check failure..."
    sed -i.bak "s|DATABASE_URL=postgresql://.*|DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/$CURRENT_DB|" \
        "$ENV_FILE"
    systemctl restart visa-bulletin
    
    log "Rolled back to: $CURRENT_DB"
    exit 1
fi

# 13. Success summary
log "======================================================================="
log "=== Data Refresh Complete: $(date) ==="
log "======================================================================="
log ""
log "Summary:"
log "  - New sources ingested: $NEW_SOURCES"
log "  - Total records: $RECORD_COUNT"
log "  - Active database: $INACTIVE_DB"
log "  - Archive: $ARCHIVE_NAME ($ARCHIVE_SIZE)"
log "  - Service downtime: ${DOWNTIME}s"
log ""
log "Logs saved to: $LOG_FILE"
log "======================================================================="

exit 0
