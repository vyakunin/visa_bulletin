#!/bin/bash
# Daily backup of the visa_bulletin Postgres DB to Google Drive.
# Retains 7 daily, 4 weekly (Sun), 3 monthly (1st of month) snapshots.
#
# Deployed location on homeserver:
#   /opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh
# Cron (user crontab):
#   0 1 * * * /opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh \
#       >> /opt/stack/visa_bulletin/logs/cron/backup.log 2>&1

set -euo pipefail

STACK_ROOT="/opt/stack/visa_bulletin"
POSTGRES_CONTAINER="vb_postgres"
DB_NAME="visa_bulletin"
DB_USER="visa_bulletin_user"
RCLONE_REMOTE="gdrive:visa_bulletin_backups"
WORK_DIR="/tmp/vb_backup"
TS=$(date -u +%Y-%m-%d)
DOW=$(date -u +%u)        # 1-7 (Mon=1, Sun=7)
DOM=$(date -u +%d)        # 01-31

mkdir -p "$WORK_DIR"

# Daily dump
DAILY_FILE="vb-prod-daily-${TS}.sql.gz"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Dumping → ${WORK_DIR}/${DAILY_FILE}"
docker exec "$POSTGRES_CONTAINER" pg_dump --no-owner --no-acl -U "$DB_USER" "$DB_NAME" \
  | gzip > "${WORK_DIR}/${DAILY_FILE}"
SIZE=$(du -h "${WORK_DIR}/${DAILY_FILE}" | cut -f1)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Dump size: $SIZE"

# Upload daily
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Uploading daily..."
rclone copy "${WORK_DIR}/${DAILY_FILE}" "${RCLONE_REMOTE}/daily/" --progress=false

# Sundays: also upload as weekly
if [ "$DOW" = "7" ]; then
  WEEKLY_FILE="vb-prod-weekly-${TS}.sql.gz"
  cp "${WORK_DIR}/${DAILY_FILE}" "${WORK_DIR}/${WEEKLY_FILE}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Sunday — uploading weekly..."
  rclone copy "${WORK_DIR}/${WEEKLY_FILE}" "${RCLONE_REMOTE}/weekly/" --progress=false
  rm -f "${WORK_DIR}/${WEEKLY_FILE}"
fi

# 1st of month: also upload as monthly
if [ "$DOM" = "01" ]; then
  MONTHLY_FILE="vb-prod-monthly-${TS}.sql.gz"
  cp "${WORK_DIR}/${DAILY_FILE}" "${WORK_DIR}/${MONTHLY_FILE}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] First-of-month — uploading monthly..."
  rclone copy "${WORK_DIR}/${MONTHLY_FILE}" "${RCLONE_REMOTE}/monthly/" --progress=false
  rm -f "${WORK_DIR}/${MONTHLY_FILE}"
fi

# Retention prune (suppress "directory not found" on subdirs that haven't been
# created yet — first weekly upload is the first Sunday, first monthly is 1st of month)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruning old backups..."
# Daily: keep last 7
rclone delete --min-age 7d "${RCLONE_REMOTE}/daily/" --include "vb-prod-daily-*.sql.gz" 2>/dev/null || true
# Weekly: keep last 4 (28 days)
rclone delete --min-age 28d "${RCLONE_REMOTE}/weekly/" --include "vb-prod-weekly-*.sql.gz" 2>/dev/null || true
# Monthly: keep last 3 (90 days)
rclone delete --min-age 90d "${RCLONE_REMOTE}/monthly/" --include "vb-prod-monthly-*.sql.gz" 2>/dev/null || true

# Local cleanup
rm -f "${WORK_DIR}/${DAILY_FILE}"

# Summary
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Drive contents:"
rclone ls "${RCLONE_REMOTE}/" | head -30

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backup complete"
