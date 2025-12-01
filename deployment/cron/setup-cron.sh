#!/bin/bash
# Setup cron job for daily incremental data refresh
#
# This script adds a cron job to fetch new visa bulletins daily at 9 AM UTC
#
# Usage:
#   cd /opt/visa_bulletin
#   bash deployment/cron/setup-cron.sh

set -e

PROJECT_ROOT="/opt/visa_bulletin"
VENV_PATH="$PROJECT_ROOT/venv"
LOG_DIR="$PROJECT_ROOT/logs"

echo "Setting up cron job for incremental data refresh..."

# Create logs directory
mkdir -p "$LOG_DIR"

# Add cron job (9 AM UTC daily)
CRON_JOB="0 9 * * * cd $PROJECT_ROOT && source $VENV_PATH/bin/activate && python refresh_data_incremental.py --save-to-db >> $LOG_DIR/cron.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "refresh_data_incremental.py"; then
    echo "✓ Cron job already exists"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "✓ Cron job added"
fi

echo ""
echo "Current crontab:"
crontab -l

echo ""
echo "✓ Setup complete!"
echo ""
echo "Monitor logs:"
echo "  tail -f $LOG_DIR/cron.log"
echo ""
echo "Test manually:"
echo "  cd $PROJECT_ROOT && source $VENV_PATH/bin/activate"
echo "  python refresh_data_incremental.py --save-to-db"

