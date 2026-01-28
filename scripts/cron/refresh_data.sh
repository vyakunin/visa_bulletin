#!/bin/bash
# scripts/cron/refresh_data.sh
# Automated blue-green database refresh with memory optimization
#
# This script uses pre-built binaries from bazel-bin/ when available to avoid
# Bazel JVM memory overhead (~400MB). Falls back to `bazel run` if binaries missing.
#
# PREREQUISITES (for low-memory mode):
#   Run scripts/cron/build_all.sh once during VM setup to build binaries.
#
# Schedule: Weekly on Sunday at 2:00 AM
# Cron entry: 0 2 * * 0 /opt/visa_bulletin/scripts/cron/refresh_data.sh >> /var/log/visa-bulletin/refresh.log 2>&1

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BAZEL_BIN="$PROJECT_ROOT/bazel-bin"
LOG_DIR="/var/log/visa-bulletin"
if ! mkdir -p "$LOG_DIR" 2>/dev/null || [[ ! -w "$LOG_DIR" ]]; then
    LOG_DIR="$PROJECT_ROOT/logs"
    mkdir -p "$LOG_DIR"
fi
LOG_FILE="$LOG_DIR/refresh_$(date +%Y%m%d_%H%M%S).log"
BACKUP_DIR="/var/backups/visa-bulletin"
if ! mkdir -p "$BACKUP_DIR" 2>/dev/null || [[ ! -w "$BACKUP_DIR" ]]; then
    BACKUP_DIR="$PROJECT_ROOT/backups"
    mkdir -p "$BACKUP_DIR"
fi
MAX_BACKUPS=3  # Keep 3 old versions (current + 2 archives)

# Database credentials (read from environment or .env file)
DB_USER="${DB_USER:-visa_bulletin_user}"
DB_PASSWORD="${DB_PASSWORD:-}"  # Should be in environment or ~/.pgpass

# Logging
exec > >(tee -a "$LOG_FILE") 2>&1
echo "======================================================================="
echo "=== Data Refresh Started (Pre-built mode): $(date) ==="
echo "======================================================================="

# Function: Log with timestamp
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

# Function: Run pre-built binary (with fallback to bazel run if binary missing)
run_bin() {
    local target="$1"
    shift
    local bin_path="$BAZEL_BIN/$target"
    
    if [[ -x "$bin_path" ]]; then
        log "Running pre-built: $bin_path $*"
        "$bin_path" "$@"
    else
        log "WARNING: Pre-built binary not found: $bin_path"
        log "Falling back to bazel run (higher memory usage)..."
        local bazel_target="//${target%/*}:${target##*/}"
        bazel run "$bazel_target" -- "$@"
    fi
}

# Verify pre-built binaries exist
log "Checking for pre-built binaries..."
REQUIRED_BINARIES=(
    "scripts/ingest/run_pipeline"
    "migrate"
    "scripts/salary/manage_salary_indexes"
    "scripts/salary/backfill_job_title_links"
    "scripts/salary/backfill_source_file_date"
    "scripts/salary/cluster_job_titles"
    "scripts/salary/cluster_existing_employers"
    "scripts/salary/update_job_title_cluster_stats"
)

MISSING_BINARIES=()
for bin in "${REQUIRED_BINARIES[@]}"; do
    if [[ ! -x "$BAZEL_BIN/$bin" ]]; then
        MISSING_BINARIES+=("$bin")
    fi
done

if [[ ${#MISSING_BINARIES[@]} -gt 0 ]]; then
    log "WARNING: Missing pre-built binaries:"
    for bin in "${MISSING_BINARIES[@]}"; do
        log "  - $bin"
    done
    log ""
    log "Run 'scripts/cron/build_all.sh' to build all binaries."
    log "Continuing with fallback to bazel run (higher memory usage)..."
fi

if [[ "$EUID" -eq 0 ]]; then
    log "ERROR: refresh_data.sh must run as a non-root user."
    exit 1
fi

detect_active_env() {
    local nginx_conf="$PROJECT_ROOT/deployment/nginx/visa-bulletin-locations.conf"
    if [[ -f "$nginx_conf" ]]; then
        if grep -q "8001" "$nginx_conf"; then
            echo "green"
            return
        fi
        if grep -q "8000" "$nginx_conf"; then
            echo "blue"
            return
        fi
    fi

    if docker ps --format '{{.Names}}' | grep -q '^visa_bulletin_web_green$'; then
        echo "green"
        return
    fi
    if docker ps --format '{{.Names}}' | grep -q '^visa_bulletin_web_blue$'; then
        echo "blue"
        return
    fi
    echo "blue"
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
ENV_FILE="$PROJECT_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    log "ERROR: Environment file not found: $ENV_FILE"
    exit 1
fi

get_env_value() {
    local key="$1"
    awk -F= -v key="$key" '$1 == key {print substr($0, index($0, $2)); exit}' "$ENV_FILE"
}

if [[ -z "$DB_USER" ]]; then
    DB_USER="$(get_env_value DB_USER)"
fi
if [[ -z "$DB_PASSWORD" ]]; then
    DB_PASSWORD="$(get_env_value DB_PASSWORD)"
fi
if [[ -z "${DB_HOST:-}" ]]; then
    DB_HOST="$(get_env_value DB_HOST)"
fi
if [[ -z "${DB_PORT:-}" ]]; then
    DB_PORT="$(get_env_value DB_PORT)"
fi
if [[ "$DB_HOST" == "host.docker.internal" ]]; then
    DB_HOST="localhost"
fi
export DB_USER
export DB_PASSWORD
export DB_HOST
export DB_PORT
if [[ -n "$DB_PASSWORD" ]]; then
    export PGPASSWORD="$DB_PASSWORD"
fi

CURRENT_DB="$(get_env_value DB_NAME)"
if [[ -z "$CURRENT_DB" ]]; then
    log "ERROR: DB_NAME not found in $ENV_FILE"
    exit 1
fi
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

log "Current active DB_NAME: $CURRENT_DB"
log "Refresh target: $INACTIVE_DB"

# 3. Discover new data sources
log "======================================================================="
log "=== Checking for new data sources ==="
log "======================================================================="

cd "$PROJECT_ROOT"
NEW_SOURCES_OUTPUT=$(run_bin "scripts/ingest/run_pipeline" check-completeness 2>&1 || true)
NEW_SOURCES=$(echo "$NEW_SOURCES_OUTPUT" | grep -c "Not ingested (available)" || true)

log "Discovery output:"
echo "$NEW_SOURCES_OUTPUT" | grep -E "(Not ingested|Ingested|Broken)" || true

log "Found $NEW_SOURCES new data sources to ingest"

# 4. Create fresh database from scratch
log "======================================================================="
log "=== Creating fresh database: $INACTIVE_DB ==="
log "======================================================================="

log "Dropping inactive database if it exists..."
sudo -u postgres psql -c "DROP DATABASE IF EXISTS $INACTIVE_DB;" 2>&1

log "Creating empty database..."
sudo -u postgres psql -c "CREATE DATABASE $INACTIVE_DB;" 2>&1

log "Granting privileges to $DB_USER..."
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $INACTIVE_DB TO $DB_USER;" 2>&1

log "Empty database created"

# 5. Configure Django to use inactive database
update_env_value() {
    local key="$1"
    local value="$2"
    KEY="$key" VALUE="$value" ENV_FILE="$ENV_FILE" python3 - <<'PY'
from os import environ
from pathlib import Path

path = Path(environ["ENV_FILE"])
key = environ["KEY"]
value = environ["VALUE"]

lines = []
found = False
for line in path.read_text().splitlines():
    if line.startswith(f"{key}="):
        lines.append(f"{key}={value}")
        found = True
    else:
        lines.append(line)
if not found:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n")
PY
}

log "Updating $ENV_FILE DB_NAME to $INACTIVE_DB"
update_env_value "DB_NAME" "$INACTIVE_DB"
export DB_NAME="$INACTIVE_DB"
log "Configured DB_NAME: $INACTIVE_DB"

# 5b. Run migrations on the inactive database
log "--- Running migrations on $INACTIVE_DB ---"
run_bin "migrate" 2>&1

# 6. Run complete ingestion pipeline
log "======================================================================="
log "=== Running ingestion pipeline on $INACTIVE_DB ==="
log "======================================================================="

# 6a. Drop indexes for faster ingestion
log "--- Dropping indexes for faster ingestion ---"
mkdir -p "$BACKUP_DIR"
INDEX_SNAPSHOT="$BACKUP_DIR/salary_indexes_$(date +%Y%m%d_%H%M%S).yaml"

run_bin "scripts/salary/manage_salary_indexes" \
    --drop \
    --snapshot "$INDEX_SNAPSHOT" \
    --overwrite 2>&1

log "Indexes dropped. Snapshot saved to: $INDEX_SNAPSHOT"

# 6b. Discover and ingest new sources
log "--- Discovering and ingesting new sources ---"
set +e
run_bin "scripts/ingest/run_pipeline" discover-and-ingest --all-domains 2>&1 | tee -a "$LOG_FILE"
INGEST_EXIT_CODE=${PIPESTATUS[0]}
set -e

if [[ "$INGEST_EXIT_CODE" -ne 0 ]]; then
    log "ERROR: Ingestion command failed with exit code $INGEST_EXIT_CODE"
    exit 1
fi

log "Ingestion complete"

# 6c. Recreate indexes (BEFORE clustering - required for performance)
log "--- Recreating indexes (required for clustering performance) ---"
run_bin "scripts/salary/manage_salary_indexes" \
    --recreate \
    --snapshot "$INDEX_SNAPSHOT" 2>&1

log "Indexes recreated"

# 6d. Run post-processing (clustering requires indexes from step 6c)
log "--- Post-processing: Backfill job title links ---"
run_bin "scripts/salary/backfill_job_title_links" 2>&1

log "--- Post-processing: Backfill source file dates ---"
run_bin "scripts/salary/backfill_source_file_date" 2>&1

log "--- Post-processing: Cluster job titles ---"
run_bin "scripts/salary/cluster_job_titles" 2>&1

log "--- Post-processing: Cluster employers (long-running) ---"
run_bin "scripts/salary/cluster_existing_employers" 2>&1

log "--- Post-processing: Update job title stats ---"
run_bin "scripts/salary/update_job_title_cluster_stats" 2>&1

# 6e. Run VACUUM ANALYZE to update statistics after bulk operations
log "--- Running VACUUM ANALYZE (cleans up and updates statistics) ---"
psql -h localhost -U "$DB_USER" -d "$INACTIVE_DB" -c "VACUUM ANALYZE;" 2>&1
log "VACUUM ANALYZE complete"

# 7. Run smoke tests
log "======================================================================="
log "=== Running smoke tests on $INACTIVE_DB ==="
log "======================================================================="

SMOKE_TEST_PASSED=true

# Test 1: Check record counts
log "Test 1: Checking total record count..."
RECORD_COUNT=$(psql -h localhost -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM salary_record;" | tr -d ' ')

log "Total salary records: $RECORD_COUNT"
if [[ "$RECORD_COUNT" -lt 100000 ]]; then
    log "ERROR: Record count too low: $RECORD_COUNT (expected >100,000)"
    SMOKE_TEST_PASSED=false
fi

# Test 2: Check recent fiscal year data
log "Test 2: Checking recent fiscal year data..."
MAX_FISCAL_YEAR=$(psql -h localhost -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT MAX(fiscal_year) FROM salary_record;" | tr -d ' ')

if [[ -z "$MAX_FISCAL_YEAR" ]]; then
    log "ERROR: No fiscal year data found in database"
    SMOKE_TEST_PASSED=false
else
    log "Most recent fiscal year in DB: $MAX_FISCAL_YEAR"
    RECENT_COUNT=$(psql -h localhost -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
        "SELECT COUNT(*) FROM salary_record WHERE fiscal_year = $MAX_FISCAL_YEAR;" | tr -d ' ')
    
    log "Records for FY $MAX_FISCAL_YEAR: $RECENT_COUNT"
    if [[ "$RECENT_COUNT" -lt 1000 ]]; then
        log "WARNING: Very few records for most recent fiscal year $MAX_FISCAL_YEAR: $RECENT_COUNT"
    fi
    
    CURRENT_YEAR=$(date +%Y)
    YEAR_DIFF=$((CURRENT_YEAR - MAX_FISCAL_YEAR))
    if [[ "$YEAR_DIFF" -gt 2 ]]; then
        log "WARNING: Most recent fiscal year $MAX_FISCAL_YEAR is ${YEAR_DIFF} years old (data may be stale)"
    fi
fi

# Test 3: Check employer clustering
log "Test 3: Checking employer clustering..."
CLUSTERED_EMPLOYERS=$(psql -h localhost -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
    "SELECT COUNT(*) FROM employer WHERE canonical_cluster_id IS NOT NULL;" | tr -d ' ')

log "Clustered employers: $CLUSTERED_EMPLOYERS"
if [[ "$CLUSTERED_EMPLOYERS" -lt 100000 ]]; then
    log "WARNING: Low clustered employer count: $CLUSTERED_EMPLOYERS (expected >100,000)"
fi

# Test 4: Check job title links
log "Test 4: Checking job title links..."
LINKED_RECORDS=$(psql -h localhost -U "$DB_USER" -d "$INACTIVE_DB" -t -c \
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

# 7b. Cleanup old ingest run metadata
log "--- Cleanup: Removing old ingest runs ---"
run_bin "scripts/ingest/run_pipeline" cleanup --days 30 2>&1

# 8. Archive current active database
log "======================================================================="
log "=== Archiving previous version ==="
log "======================================================================="

ARCHIVE_NAME="visa_bulletin_archive_${CURRENT_DB}_$(date +%Y%m%d_%H%M%S).sql.gz"
ARCHIVE_PATH="$BACKUP_DIR/$ARCHIVE_NAME"

log "Creating archive: $ARCHIVE_NAME"
pg_dump -h localhost -U "$DB_USER" "$CURRENT_DB" | gzip > "$ARCHIVE_PATH"

ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
log "Archive created: $ARCHIVE_PATH ($ARCHIVE_SIZE)"

# 9. Clean up old archives (keep only MAX_BACKUPS)
log "--- Cleaning up old archives (keeping $MAX_BACKUPS most recent) ---"
mapfile -t archives < <(ls -1t "$BACKUP_DIR"/visa_bulletin_archive_*.sql.gz 2>/dev/null || true)
ARCHIVE_COUNT=${#archives[@]}

log "Current archive count: $ARCHIVE_COUNT"
if [[ "$ARCHIVE_COUNT" -gt "$MAX_BACKUPS" ]]; then
    log "Deleting $((ARCHIVE_COUNT - MAX_BACKUPS)) old archives..."
    for old_archive in "${archives[@]:$MAX_BACKUPS}"; do
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
update_env_value "DB_NAME" "$INACTIVE_DB"

# Restart service (container-level restart)
ACTIVE_ENV="$(detect_active_env)"
ACTIVE_PORT="8000"
if [[ "$ACTIVE_ENV" == "green" ]]; then
    ACTIVE_PORT="8001"
fi
COMPOSE_FILE="$PROJECT_ROOT/deployment/docker-compose.${ACTIVE_ENV}.yml"

log "Restarting docker service for active env: $ACTIVE_ENV"
RESTART_START=$(date +%s)
docker-compose -f "$COMPOSE_FILE" restart "web-$ACTIVE_ENV"
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

NEW_ACTIVE="$(get_env_value DB_NAME)"
log "New active database: $NEW_ACTIVE"

if [[ "$NEW_ACTIVE" == "$INACTIVE_DB" ]]; then
    log "✅ Swap successful: Now using $INACTIVE_DB"
else
    log "ERROR: Swap verification failed (expected: $INACTIVE_DB, got: $NEW_ACTIVE)"
    
    # Rollback
    log "Performing automatic rollback..."
    update_env_value "DB_NAME" "$CURRENT_DB"
    docker-compose -f "$COMPOSE_FILE" restart "web-$ACTIVE_ENV"
    
    log "Rolled back to: $CURRENT_DB"
    exit 1
fi

# 12. Final verification
log "--- Final application health check ---"
if python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${ACTIVE_PORT}/salaries/').read()" >/dev/null 2>&1; then
    log "✅ Application responding correctly"
else
    log "ERROR: Application health check failed"
    
    # Rollback
    log "Performing automatic rollback due to health check failure..."
    update_env_value "DB_NAME" "$CURRENT_DB"
    docker-compose -f "$COMPOSE_FILE" restart "web-$ACTIVE_ENV"
    
    log "Rolled back to: $CURRENT_DB"
    exit 1
fi

# 13. Success summary
log "======================================================================="
log "=== Data Refresh Complete (Pre-built mode): $(date) ==="
log "======================================================================="
log ""
log "Summary:"
log "  - New sources ingested: $NEW_SOURCES"
log "  - Total records: $RECORD_COUNT"
log "  - Active database: $INACTIVE_DB"
log "  - Archive: $ARCHIVE_NAME ($ARCHIVE_SIZE)"
log "  - Service downtime: ${DOWNTIME}s"
log "  - Mode: Pre-built binaries (low memory)"
log ""
log "Logs saved to: $LOG_FILE"
log "======================================================================="

exit 0
