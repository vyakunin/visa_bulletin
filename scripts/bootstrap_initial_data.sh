#!/bin/bash
# scripts/bootstrap_initial_data.sh
# Bootstrap initial data for a fresh Visa Bulletin instance
#
# This script:
#   1. Runs Django migrations
#   2. Discovers and ingests visa bulletin data (historical bulletins)
#   3. Discovers DOL salary data sources (ready for ingest)
#
# Usage:
#   cd /opt/visa_bulletin
#   ./scripts/bootstrap_initial_data.sh
#
# Prerequisites:
#   - PostgreSQL running with database created
#   - .env file configured with DB credentials
#   - Bazel binaries pre-built (run ./scripts/cron/build_all.sh first)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BAZEL_BIN="$PROJECT_ROOT/bazel-bin"

echo "=============================================================="
echo "Visa Bulletin - Initial Data Bootstrap"
echo "=============================================================="
echo "Started: $(date)"
echo ""

# Check we're in the right directory
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "ERROR: .env file not found. Run this script from the project root:"
    echo "  cd /opt/visa_bulletin && ./scripts/bootstrap_initial_data.sh"
    exit 1
fi

# Load environment
cd "$PROJECT_ROOT"
set -a
source .env
set +a

# Override DB_HOST for host-based execution
export DB_HOST=localhost

echo "Database: $DB_NAME"
echo "DB Host: $DB_HOST"
echo ""

# Function: Run pre-built binary (with fallback to bazel run)
run_bin() {
    local target="$1"
    shift
    local bin_path="$BAZEL_BIN/$target"
    
    if [[ -x "$bin_path" ]]; then
        echo "[$(date +'%H:%M:%S')] Running: $bin_path $*"
        "$bin_path" "$@"
    else
        echo "[$(date +'%H:%M:%S')] Pre-built binary not found: $bin_path"
        echo "[$(date +'%H:%M:%S')] Falling back to bazel run..."
        local bazel_target="//${target%/*}:${target##*/}"
        bazel run "$bazel_target" -- "$@"
    fi
}

# Step 1: Run migrations
echo "=============================================================="
echo "Step 1: Running Django migrations"
echo "=============================================================="
run_bin "migrate"
echo "✅ Migrations complete"
echo ""

# Step 2: Discover and ingest visa bulletin data
echo "=============================================================="
echo "Step 2: Discovering and ingesting visa bulletin data"
echo "=============================================================="
echo "This will download and parse historical visa bulletins from travel.state.gov"
echo ""

run_bin "scripts/ingest/run_pipeline" discover-and-ingest --domain visa_bulletin

echo ""
echo "✅ Visa bulletin data ingested"
echo ""

# Step 3: Discover DOL sources (don't ingest yet - too large for initial setup)
echo "=============================================================="
echo "Step 3: Discovering DOL salary data sources"
echo "=============================================================="
echo "This will discover available DOL data sources (but not ingest them yet)"
echo ""

run_bin "scripts/ingest/run_pipeline" discover --domain dol

echo ""
echo "✅ DOL sources discovered"
echo ""

# Step 4: Show summary
echo "=============================================================="
echo "Bootstrap Complete!"
echo "=============================================================="
echo "Completed: $(date)"
echo ""
echo "Data imported:"
echo "  ✅ Visa Bulletins: All historical bulletins from travel.state.gov"
echo "  ✅ DOL Sources: Discovered (ready for ingest)"
echo ""
echo "Next steps:"
echo "  1. Verify web server: curl -I http://localhost/"
echo "  2. Check visa bulletin data: Visit http://localhost/ in browser"
echo "  3. (Optional) Ingest DOL salary data: ./scripts/cron/refresh_data.sh"
echo "  4. Setup automated refresh: ./scripts/cron/setup-ingest-cron.sh"
echo ""
echo "For more information, see: docs/deployment/NEW_INSTANCE_SETUP.md"
echo ""
