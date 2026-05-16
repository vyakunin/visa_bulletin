#!/bin/bash
# Restore the most recent GDrive daily backup INTO a running Lightsail's Postgres.
#
# When called manually (no flags): targets $LIGHTSAIL_NEW_INSTANCE_NAME's IP
# (resolved via aws lightsail get-instance), prompts for confirmation.
#
# When called from failover.sh (with --target-ip + --auto-confirm): targets
# whatever IP failover.sh just attached to the new DR instance, no prompts.
#
# Path:  GDrive (Mac rclone) → Mac /tmp → scp → Lightsail /tmp → docker/psql

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/_lib.sh"

# ---------- args ----------
TARGET_IP=""
AUTO_CONFIRM=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-ip)    TARGET_IP="$2"; shift 2 ;;
    --auto-confirm) AUTO_CONFIRM=1; shift ;;
    *)              die "unknown arg: $1" ;;
  esac
done

# Resolve target IP if not given
if [[ -z "$TARGET_IP" ]]; then
  TARGET_IP=$(aws_lightsail get-instance --instance-name "$LIGHTSAIL_NEW_INSTANCE_NAME" --query 'instance.publicIpAddress' --output text 2>/dev/null) || \
    die "could not resolve IP of '$LIGHTSAIL_NEW_INSTANCE_NAME' — is it running? Run failover.sh first."
fi
log "=== Restore latest GDrive backup → Lightsail $TARGET_IP ==="

# ---------- 1. Find latest backup ----------
log "Finding latest daily backup in GDrive…"
latest=$(/opt/homebrew/bin/rclone ls "${GDRIVE_REMOTE}/daily/" 2>/dev/null | /usr/bin/sort -k2 | /usr/bin/awk '{print $2}' | /usr/bin/tail -1)
[[ -z "$latest" ]] && die "no daily backup found in $GDRIVE_REMOTE/daily/"
log "  latest: $latest"

# ---------- 2. Download to Mac ----------
log "Downloading to Mac /tmp/$latest…"
/opt/homebrew/bin/rclone copy "${GDRIVE_REMOTE}/daily/$latest" /tmp/ --progress
[[ -f "/tmp/$latest" ]] || die "download failed"
size=$(/usr/bin/du -h "/tmp/$latest" | /usr/bin/cut -f1)
ok "downloaded $size"

# ---------- 3. SCP to Lightsail ----------
log "SCP /tmp/$latest → Lightsail:/tmp/$latest…"
/usr/bin/scp -i "$SSH_KEY_LIGHTSAIL" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "/tmp/$latest" "$SSH_USER_LIGHTSAIL@$TARGET_IP:/tmp/$latest"
ok "uploaded"

# ---------- 4. Restore ----------
if [[ "$AUTO_CONFIRM" -eq 0 ]]; then
  warn "About to restore: this DROPS and rebuilds public schema in Lightsail's prod DB."
  if ! confirm "Proceed?"; then
    log "  aborted — backup file left at Lightsail:/tmp/$latest"
    exit 0
  fi
fi

log "Restoring (~2-3 min on Lightsail's small CPU)…"
/usr/bin/ssh -i "$SSH_KEY_LIGHTSAIL" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$SSH_USER_LIGHTSAIL@$TARGET_IP" "
  set -e
  cd /opt/visa_bulletin
  source .env
  echo '  Dropping existing schema (public)…'
  PGPASSWORD=\$DB_PASSWORD psql -h localhost -U \$DB_USER -d \$DB_NAME -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;' 2>&1 | tail -3
  echo '  Loading dump…'
  /usr/bin/zcat /tmp/$latest | PGPASSWORD=\$DB_PASSWORD psql -h localhost -U \$DB_USER -d \$DB_NAME -v ON_ERROR_STOP=0 2>&1 | tail -3
  echo '  Row counts:'
  PGPASSWORD=\$DB_PASSWORD psql -h localhost -U \$DB_USER -d \$DB_NAME -c 'SELECT \"bulletin\" AS t, count(*) FROM bulletin UNION ALL SELECT \"salary_record\", count(*) FROM salary_record;'
  docker restart visa_bulletin_web 2>&1 | tail -2
  rm -f /tmp/$latest
"
ok "restore complete"
/bin/rm -f "/tmp/$latest"
log "Lightsail's DB now matches GDrive backup '$latest'"
