#!/bin/bash
# Setup cron jobs for unified ingest pipeline
#
# This script adds cron jobs for:
# 1. Daily data discovery and ingest (9 AM UTC)
# 2. Weekly cleanup of old ingest runs (Sunday 2 AM UTC)
#
# Usage:
#   cd /opt/visa_bulletin
#   bash deployment/cron/setup-ingest-cron.sh

set -e

PROJECT_ROOT="/opt/visa_bulletin"
LOG_DIR="$PROJECT_ROOT/logs"

echo "Setting up cron jobs for ingest pipeline..."

# Create logs directory
mkdir -p "$LOG_DIR"

# Daily ingest job (9 AM UTC daily)
# Note: Clustering is disabled during ingest for performance. Run clustering separately after ingest completes.
INGEST_CRON="0 9 * * * cd $PROJECT_ROOT && bazel run //scripts/ingest:run_pipeline -- discover-and-ingest >> $LOG_DIR/ingest.log 2>&1"

# Daily clustering job (10 AM UTC daily - 1 hour after ingest to allow ingest to complete)
# Clusters all employers including newly imported ones
CLUSTERING_CRON="0 10 * * * cd $PROJECT_ROOT && bazel run //scripts/salary:cluster_existing_employers >> $LOG_DIR/clustering.log 2>&1"

# Weekly cleanup job (Sunday 2 AM UTC - cleanup old runs older than 30 days)
CLEANUP_CRON="0 2 * * 0 cd $PROJECT_ROOT && bazel run //scripts/ingest:run_pipeline -- cleanup --days 30 >> $LOG_DIR/ingest_cleanup.log 2>&1"

# Remove old cron jobs if they exist
crontab -l 2>/dev/null | grep -v "refresh_data_incremental\|update_salary_data\|import_salary_data" | crontab - 2>/dev/null || true

# Check if ingest cron job already exists
if crontab -l 2>/dev/null | grep -q "//scripts/ingest:run_pipeline.*discover-and-ingest"; then
    echo "✓ Ingest cron job already exists"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$INGEST_CRON") | crontab -
    echo "✓ Ingest cron job added (daily at 9 AM UTC)"
fi

# Check if cleanup cron job already exists
if crontab -l 2>/dev/null | grep -q "//scripts/ingest:run_pipeline.*cleanup"; then
    echo "✓ Cleanup cron job already exists"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CLEANUP_CRON") | crontab -
    echo "✓ Cleanup cron job added (weekly on Sunday at 2 AM UTC)"
fi

# Check if clustering cron job already exists
if crontab -l 2>/dev/null | grep -q "//scripts/salary:cluster_existing_employers"; then
    echo "✓ Clustering cron job already exists"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CLUSTERING_CRON") | crontab -
    echo "✓ Clustering cron job added (daily at 10 AM UTC - 1 hour after ingest)"
fi

echo ""
echo "Current crontab:"
crontab -l

echo ""
echo "✓ Setup complete!"
echo ""
echo "Monitor logs:"
echo "  tail -f $LOG_DIR/ingest.log"
echo "  tail -f $LOG_DIR/clustering.log"
echo "  tail -f $LOG_DIR/ingest_cleanup.log"
echo ""
echo "Test manually:"
echo "  cd $PROJECT_ROOT"
echo "  bazel run //scripts/ingest:run_pipeline -- discover-and-ingest"
echo "  bazel run //scripts/salary:cluster_existing_employers"
echo "  bazel run //scripts/ingest:run_pipeline -- cleanup --days 30"
echo ""
echo "Or use combined script:"
echo "  bazel run //scripts/ingest:ingest_and_cluster -- --source-id 123"

