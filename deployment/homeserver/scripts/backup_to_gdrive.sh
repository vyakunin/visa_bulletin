#!/bin/bash
# Daily off-box backup of the visa_bulletin Postgres DB.
#
# Thin producer wrapper around the SHARED backup CLI (agent_infra):
#   /opt/stack/_shared/backup_blob.sh   (canonical source: agent_infra/scripts/)
# The shared CLI owns naming, GFS rotation (7 daily / 4 weekly / 3 monthly),
# rclone upload to gdrive:_backups/visa_bulletin/, pruning, and failure alerting
# to the agent_infra Telegram bot. This script supplies only the producer.
#
# Deployed location on homeserver:
#   /opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh
# Cron (user crontab):
#   0 1 * * * /opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh \
#       >> /opt/stack/visa_bulletin/logs/cron/backup.log 2>&1
#
# NOTE: backups now land in gdrive:_backups/visa_bulletin/ (unified location).
# Pre-migration history remains in the old gdrive:visa_bulletin_backups/ dir.

set -euo pipefail

POSTGRES_CONTAINER="vb_postgres"
DB_NAME="visa_bulletin"
DB_USER="visa_bulletin_user"

# pg_dump | gzip | shared CLI. --min-bytes guards against an empty/failed dump
# (the real compressed dump is hundreds of MB; 100 KB is a safe "not empty"
# floor). pipefail ensures a pg_dump failure fails the whole pipeline.
docker exec "$POSTGRES_CONTAINER" \
    pg_dump --no-owner --no-acl -U "$DB_USER" "$DB_NAME" \
  | gzip \
  | /opt/stack/_shared/backup_blob.sh visa_bulletin --ext sql.gz --min-bytes 100000
