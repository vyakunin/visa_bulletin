#!/bin/bash
# scripts/cron/build_all.sh
# One-time build of all Bazel targets, then shutdown Bazel server
#
# Run this during VM setup, then use pre-built binaries for runtime.
# This avoids JVM memory overhead during cron jobs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

cd "$PROJECT_ROOT"

log "======================================================================="
log "=== Building all Bazel targets ==="
log "======================================================================="

# Build specific targets needed for refresh (avoids broken external dependencies like Ollama)
log "Building refresh script targets (this may take several minutes and use significant memory)..."
bazel build \
    //scripts/ingest:run_pipeline \
    //:migrate \
    //scripts/salary:manage_salary_indexes \
    //scripts/salary:populate_case_submitted \
    //scripts/salary:backfill_job_title_links \
    //scripts/salary:backfill_source_file_date \
    //scripts/salary:cluster_job_titles \
    //scripts/salary:update_employer_stats \
    //scripts/salary:cluster_existing_employers \
    //scripts/salary:update_job_title_cluster_stats \
    //scripts/salary:populate_job_title_slugs \
    //scripts/cache:warm_cache \
    //scripts/cron:refresh_bulletin \
    2>&1

log "Build complete"

# Shutdown Bazel server to free memory (~400MB JVM)
log "Shutting down Bazel server to free memory..."
bazel shutdown

log "======================================================================="
log "=== Build Complete ==="
log "======================================================================="
log ""
log "Pre-built binaries are now available in bazel-bin/"
log "Example usage:"
log "  ./bazel-bin/scripts/ingest/run_pipeline check-completeness"
log "  ./bazel-bin/migrate"
log "  ./bazel-bin/scripts/salary/cluster_existing_employers"
log ""
log "Memory freed by shutting down Bazel server: ~400MB"
log ""

# Verify some key binaries exist
log "Verifying key binaries..."
BINARIES=(
    "bazel-bin/scripts/ingest/run_pipeline"
    "bazel-bin/migrate"
    "bazel-bin/scripts/salary/manage_salary_indexes"
    "bazel-bin/scripts/salary/populate_case_submitted"
    "bazel-bin/scripts/salary/backfill_job_title_links"
    "bazel-bin/scripts/salary/backfill_source_file_date"
    "bazel-bin/scripts/salary/cluster_job_titles"
    "bazel-bin/scripts/salary/update_employer_stats"
    "bazel-bin/scripts/salary/cluster_existing_employers"
    "bazel-bin/scripts/salary/update_job_title_cluster_stats"
    "bazel-bin/scripts/salary/populate_job_title_slugs"
    "bazel-bin/scripts/cache/warm_cache"
    "bazel-bin/scripts/cron/refresh_bulletin"
)

ALL_OK=true
for bin in "${BINARIES[@]}"; do
    if [[ -x "$bin" ]]; then
        log "  ✅ $bin"
    else
        log "  ❌ $bin (missing or not executable)"
        ALL_OK=false
    fi
done

if [[ "$ALL_OK" == "true" ]]; then
    log ""
    log "✅ All binaries built successfully"
else
    log ""
    log "⚠️  Some binaries are missing. Check build output above."
    exit 1
fi
