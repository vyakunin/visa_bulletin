#!/bin/bash
# Setup cron jobs for unified ingest pipeline
#
# This script adds a single cron job for end-to-end refresh:
# - Weekly refresh (Sunday 2 AM UTC)
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

# Weekly end-to-end refresh (Sunday 2 AM UTC)
REFRESH_CRON="0 2 * * 0 cd $PROJECT_ROOT && bash scripts/cron/refresh_data.sh >> $LOG_DIR/refresh.log 2>&1"

# Remove old cron jobs if they exist
crontab -l 2>/dev/null | grep -v "refresh_data.sh\|refresh_data_incremental\|update_salary_data\|import_salary_data\|run_pipeline.*discover-and-ingest\|cluster_existing_employers\|run_pipeline.*cleanup" | crontab - 2>/dev/null || true

# Check if refresh cron job already exists
if crontab -l 2>/dev/null | grep -q "scripts/cron/refresh_data.sh"; then
    echo "✓ Refresh cron job already exists"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$REFRESH_CRON") | crontab -
    echo "✓ Refresh cron job added (weekly at 2 AM UTC)"
fi

echo ""
echo "Current crontab:"
crontab -l

echo ""
echo "✓ Setup complete!"
echo ""
echo "Monitor logs:"
echo "  tail -f $LOG_DIR/refresh.log"
echo ""
echo "Test manually:"
echo "  cd $PROJECT_ROOT"
echo "  bash scripts/cron/refresh_data.sh"

