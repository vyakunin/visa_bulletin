#!/bin/bash
#
# Setup cron job for daily visa bulletin data refresh
#
# This script configures a cron job to run the incremental data refresh
# every day at 9 AM (when new bulletins are typically published).
#
# The refresh runs concurrently with the web server using SQLite WAL mode.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════════════════════════════"
echo "📅 VISA BULLETIN CRON JOB SETUP"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "This will configure a daily cron job to refresh visa bulletin data."
echo ""
echo "Configuration:"
echo "  • Project directory: $PROJECT_DIR"
echo "  • Schedule: Daily at 9:00 AM"
echo "  • Script: refresh_data_incremental.py"
echo "  • Log file: $PROJECT_DIR/logs/cron_refresh.log"
echo ""

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Cron job command
CRON_CMD="cd $PROJECT_DIR && bazel run //:refresh_data_incremental >> $PROJECT_DIR/logs/cron_refresh.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "refresh_data_incremental"; then
    echo "⚠️  Cron job already exists. Current crontab:"
    echo ""
    crontab -l | grep "refresh_data_incremental"
    echo ""
    read -p "Replace existing cron job? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
    # Remove existing job
    crontab -l | grep -v "refresh_data_incremental" | crontab -
fi

# Add new cron job (9 AM daily)
(crontab -l 2>/dev/null; echo "0 9 * * * $CRON_CMD") | crontab -

echo ""
echo "✅ Cron job configured successfully!"
echo ""
echo "Schedule: Daily at 9:00 AM"
echo "Command: $CRON_CMD"
echo ""
echo "Logs will be written to:"
echo "  $PROJECT_DIR/logs/cron_refresh.log"
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "📋 NEXT STEPS"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "1. View current cron jobs:"
echo "   crontab -l"
echo ""
echo "2. Test the refresh manually:"
echo "   bazel run //:refresh_data_incremental"
echo ""
echo "3. Monitor logs:"
echo "   tail -f $PROJECT_DIR/logs/cron_refresh.log"
echo ""
echo "4. Remove cron job (if needed):"
echo "   crontab -e  # then delete the line with 'refresh_data_incremental'"
echo ""
echo "═══════════════════════════════════════════════════════════════════"

