#!/bin/bash
#
# Setup cron job for daily data refresh (unified ingest pipeline)
#
# This script configures a cron job to run the unified ingest pipeline
# every day at 9 AM to refresh all data sources (visa bulletins, salary data).
#
# The pipeline handles duplicate detection and only processes new sources.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════════════════════════════"
echo "📅 DATA REFRESH CRON JOB SETUP"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "This will configure a daily cron job to refresh all data sources."
echo ""
echo "Configuration:"
echo "  • Project directory: $PROJECT_DIR"
echo "  • Schedule: Daily at 9:00 AM"
echo "  • Script: Unified ingest pipeline (discover-and-ingest --all-domains)"
echo "  • Log file: $PROJECT_DIR/logs/cron_refresh.log"
echo ""

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Cron job command - uses unified ingest pipeline
CRON_CMD="cd $PROJECT_DIR && bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains >> $PROJECT_DIR/logs/cron_refresh.log 2>&1"

# Check if cron job already exists (check for both old and new patterns)
if crontab -l 2>/dev/null | grep -q "refresh_data_incremental\|run_pipeline.*discover-and-ingest"; then
    echo "⚠️  Cron job already exists. Current crontab:"
    echo ""
    crontab -l | grep -E "refresh_data_incremental|run_pipeline.*discover-and-ingest"
    echo ""
    read -p "Replace existing cron job? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
    # Remove existing jobs (both old and new patterns)
    crontab -l | grep -v "refresh_data_incremental\|run_pipeline.*discover-and-ingest" | crontab -
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
echo "   bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains"
echo ""
echo "3. Monitor logs:"
echo "   tail -f $PROJECT_DIR/logs/cron_refresh.log"
echo ""
echo "4. Remove cron job (if needed):"
echo "   crontab -e  # then delete the line with 'run_pipeline'"
echo ""
echo "═══════════════════════════════════════════════════════════════════"

