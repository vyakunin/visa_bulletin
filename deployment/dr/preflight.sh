#!/bin/bash
# Verify all DR pre-reqs are in place. Run this once now (and every few months).
# Designed to be safe: makes only read-only API calls, no state changes.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/_lib.sh"

failed=0
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    ok "$label"
  else
    err "$label  (FAIL)"
    failed=1
  fi
}

log "=== DR pre-flight ==="
echo ""

# 1. AWS CLI works
check "aws CLI installed" /opt/homebrew/bin/aws --version
check "AWS profile '$AWS_PROFILE_NAME' configured" \
  bash -c "AWS_PROFILE='$AWS_PROFILE_NAME' /opt/homebrew/bin/aws sts get-caller-identity"

# 2. Lightsail instance reachable from API
check "Lightsail snapshot '$LIGHTSAIL_SNAPSHOT_NAME' available" bash -c "
  state=\$(AWS_PROFILE='$AWS_PROFILE_NAME' /opt/homebrew/bin/aws lightsail get-instance-snapshot --region '$LIGHTSAIL_REGION' --instance-snapshot-name '$LIGHTSAIL_SNAPSHOT_NAME' --query 'instanceSnapshot.state' --output text 2>/dev/null)
  [[ \"\$state\" == 'available' ]]
"

# 3. SSH key exists
check "SSH key '$SSH_KEY_LIGHTSAIL' exists" bash -c "[[ -f '$SSH_KEY_LIGHTSAIL' ]]"

# 4. Confirm no leftover DR resources (instances/IPs costing money)
running=$(aws_lightsail get-instances --query 'instances[*].name' --output text 2>/dev/null | /usr/bin/tr '\t' '\n' | /usr/bin/wc -l | /usr/bin/tr -d ' ')
if [[ "$running" -gt 0 ]]; then
  warn "Found $running Lightsail instance(s) — should be 0 in cold-DR steady state"
  aws_lightsail get-instances --query 'instances[*].{name:name,state:state.name}' --output table
fi
ips=$(aws_lightsail get-static-ips --query 'staticIps[*].name' --output text 2>/dev/null | /usr/bin/tr '\t' '\n' | /usr/bin/wc -l | /usr/bin/tr -d ' ')
if [[ "$ips" -gt 0 ]]; then
  warn "Found $ips static IP(s) — should be 0 in cold-DR steady state (each unattached IP costs ~\$5/mo)"
  aws_lightsail get-static-ips --query 'staticIps[*].{name:name,attached:isAttached,to:attachedTo}' --output table
fi

# 5. CF token works + has needed scopes
check "CF token file exists" bash -c "[[ -f '$CF_TOKEN_FILE' ]]"

# Test DNS read (zone scope)
if cf_api GET "/zones/$CF_ZONE_ID/dns_records?per_page=1" \
   | /usr/bin/python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('success') else 1)"; then
  ok "CF API: zone DNS read OK"
else
  err "CF API: zone DNS read FAILED"
  failed=1
fi

# 6. CF DNS record IDs exist for both prod hosts
for h in "${PROD_HOSTS[@]}"; do
  rid=$(cf_record_id "$h")
  if [[ -n "$rid" ]]; then
    ok "CF DNS record exists for $h"
  else
    err "CF DNS record NOT FOUND for $h"
    failed=1
  fi
done

# 7. rclone + gdrive remote
check "rclone installed" /opt/homebrew/bin/rclone version
check "rclone gdrive remote configured" \
  /opt/homebrew/bin/rclone listremotes
if /opt/homebrew/bin/rclone listremotes 2>/dev/null | /usr/bin/grep -q "^gdrive:$"; then
  ok "rclone has 'gdrive:' remote"
  # Test we can list the backup folder
  if /opt/homebrew/bin/rclone lsd "${GDRIVE_REMOTE}/" >/dev/null 2>&1; then
    ok "GDrive folder $GDRIVE_REMOTE accessible"
    latest=$(/opt/homebrew/bin/rclone ls "${GDRIVE_REMOTE}/daily/" 2>/dev/null | /usr/bin/sort -k2 | /usr/bin/awk '{print $2}' | /usr/bin/tail -1)
    if [[ -n "$latest" ]]; then
      ok "Latest daily backup: $latest"
    else
      warn "No daily backups in GDrive yet (first scheduled run hasn't completed?)"
    fi
  else
    err "GDrive folder $GDRIVE_REMOTE not accessible"
    failed=1
  fi
else
  err "rclone has no 'gdrive:' remote"
  failed=1
fi

# 8. Verify scripts are executable
for s in failover.sh failback.sh restore_latest_backup_on_lightsail.sh; do
  if [[ -x "$DIR/$s" ]]; then
    ok "$s executable"
  else
    err "$s NOT executable (chmod +x)"
    failed=1
  fi
done

# 9. Current DNS state (informational)
echo ""
log "Current DNS state (informational):"
for h in "${PROD_HOSTS[@]}"; do
  echo "  $h: $(cf_record_describe "$h")"
done

# 10. Lightsail snapshot age + size
echo ""
log "Snapshot info:"
aws_lightsail get-instance-snapshot --instance-snapshot-name "$LIGHTSAIL_SNAPSHOT_NAME" \
  --query 'instanceSnapshot.{name:name,state:state,size:sizeInGb,created:createdAt}' --output table 2>/dev/null || echo "  (snapshot not found)"

echo ""
if [[ $failed -eq 0 ]]; then
  log "✓ All preflight checks passed. DR scripts are ready when you need them."
else
  err "Preflight FAILED. Fix above issues before relying on DR scripts."
  exit 1
fi
