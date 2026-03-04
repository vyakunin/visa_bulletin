#!/bin/bash
# Setup cron jobs for ingest pipeline
#
# Cron jobs:
# - Hourly visa bulletin refresh (lightweight, runs on serving instance)
# - Weekly full refresh (Sunday 2 AM UTC)
#
# Usage:
#   cd /opt/visa_bulletin
#   bash deployment/cron/setup-ingest-cron.sh

set -e

PROJECT_ROOT="/opt/visa_bulletin"
LOG_DIR="/var/log/visa-bulletin"

echo "Setting up cron jobs for ingest pipeline..."

# Create logs directory (may need sudo for /var/log)
if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
    sudo mkdir -p "$LOG_DIR"
    sudo chown "$(whoami):$(whoami)" "$LOG_DIR"
fi

# Hourly visa bulletin refresh (lightweight, on serving instance)
# Use `. .env` (not `source`) — cron uses /bin/sh (dash) where `source` is a bashism
BULLETIN_CRON="0 * * * * cd $PROJECT_ROOT && set -a && . ./.env && set +a && DB_HOST=localhost ./bazel-bin/scripts/cron/refresh_bulletin >> $LOG_DIR/bulletin_refresh.log 2>&1"

# Weekly end-to-end refresh (Sunday 2 AM UTC)
REFRESH_CRON="0 2 * * 0 cd $PROJECT_ROOT && bash scripts/cron/refresh_data.sh >> $LOG_DIR/refresh.log 2>&1"

# Remove old cron jobs if they exist
crontab -l 2>/dev/null | grep -v "refresh_data.sh\|refresh_data_incremental\|update_salary_data\|import_salary_data\|run_pipeline.*discover-and-ingest\|cluster_existing_employers\|refresh_bulletin" | crontab - 2>/dev/null || true

# Add cron jobs
CRON_ENTRIES=""

if ! crontab -l 2>/dev/null | grep -q "refresh_bulletin"; then
    CRON_ENTRIES="$BULLETIN_CRON"
    echo "✓ Bulletin refresh cron job added (hourly)"
else
    echo "✓ Bulletin refresh cron job already exists"
fi

if ! crontab -l 2>/dev/null | grep -q "scripts/cron/refresh_data.sh"; then
    CRON_ENTRIES="$CRON_ENTRIES
$REFRESH_CRON"
    echo "✓ Full refresh cron job added (weekly at 2 AM UTC)"
else
    echo "✓ Full refresh cron job already exists"
fi

if [ -n "$CRON_ENTRIES" ]; then
    (crontab -l 2>/dev/null; echo "$CRON_ENTRIES") | crontab -
fi

echo ""
echo "Current crontab:"
crontab -l

echo ""
echo "✓ Setup complete!"
echo ""
echo "Monitor logs:"
echo "  tail -f $LOG_DIR/bulletin_refresh.log  # Hourly bulletin refresh"
echo "  tail -f $LOG_DIR/refresh.log           # Weekly full refresh"
echo ""
echo "Test bulletin refresh manually:"
echo "  cd $PROJECT_ROOT && set -a && . ./.env && set +a && DB_HOST=localhost ./bazel-bin/scripts/cron/refresh_bulletin"
echo ""
echo "Build the binary first (if not built):"
echo "  cd $PROJECT_ROOT && bazel build //scripts/cron:refresh_bulletin && bazel shutdown"

