#!/bin/bash
# Disaster recovery: take prod traffic OFF homeserver and put it ON a fresh
# Lightsail instance built from our cold-DR snapshot.
#
# Use when:
#   - homeserver SSD has failed
#   - homeserver totally unreachable for >5 min and you can't fix it quickly
#   - any "the site has to come back up NOW" scenario
#
# What this does (in order):
#   1. Create a new Lightsail instance from snapshot LIGHTSAIL_SNAPSHOT_NAME
#   2. Wait for it to reach 'running' (~3-5 min)
#   3. Allocate a fresh static IP and attach it
#   4. Wait for SSH responsive + Docker stack healthy
#   5. Restore latest GDrive backup into the new instance's Postgres
#   6. Confirm with you before flipping DNS
#   7. Flip CF DNS: visa-bulletin.us + www → A <new-ip> (proxied)
#   8. Verify https://visa-bulletin.us/ now serves
#
# Total time: ~10-15 min (snapshot restore = bulk of it).
#
# When recovered, run ./failback.sh which:
#   - flips DNS back to homeserver tunnel
#   - DELETES the DR instance and releases the static IP
#     (so you stop paying immediately)

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/_lib.sh"

log "=== Disaster Recovery: failover homeserver → fresh Lightsail from snapshot ==="
log "Snapshot:           $LIGHTSAIL_SNAPSHOT_NAME"
log "New instance name:  $LIGHTSAIL_NEW_INSTANCE_NAME"
log "Bundle:             $LIGHTSAIL_BUNDLE  ($LIGHTSAIL_AZ)"
echo ""

# ---------- 1. Verify snapshot exists and is available ----------
log "Step 1/8: verifying snapshot is available"
state=$(aws_lightsail get-instance-snapshot --instance-snapshot-name "$LIGHTSAIL_SNAPSHOT_NAME" --query 'instanceSnapshot.state' --output text 2>/dev/null) || die "snapshot $LIGHTSAIL_SNAPSHOT_NAME not found"
[[ "$state" == "available" ]] || die "snapshot state is '$state', expected 'available'. Wait or take new one."
ok "snapshot available"

# ---------- 2. Check no DR instance already exists ----------
existing=$(aws_lightsail get-instances --query "instances[?name=='$LIGHTSAIL_NEW_INSTANCE_NAME'].name" --output text 2>/dev/null)
if [[ -n "$existing" ]]; then
  warn "DR instance '$LIGHTSAIL_NEW_INSTANCE_NAME' already exists. Run ./failback.sh first to clean it up, OR change LIGHTSAIL_NEW_INSTANCE_NAME in _lib.sh."
  exit 1
fi

# ---------- 3. Create instance from snapshot ----------
log "Step 2/8: creating instance from snapshot (~3-5 min)"
aws_lightsail create-instances-from-snapshot \
  --instance-names "$LIGHTSAIL_NEW_INSTANCE_NAME" \
  --availability-zone "$LIGHTSAIL_AZ" \
  --instance-snapshot-name "$LIGHTSAIL_SNAPSHOT_NAME" \
  --bundle-id "$LIGHTSAIL_BUNDLE" \
  --query 'operations[0].status' --output text >/dev/null

log "  waiting for state=running…"
for i in {1..40}; do
  sleep 10
  s=$(aws_lightsail get-instance --instance-name "$LIGHTSAIL_NEW_INSTANCE_NAME" --query 'instance.state.name' --output text 2>/dev/null || echo "pending")
  echo "    attempt $i: $s"
  [[ "$s" == "running" ]] && { ok "instance running after ${i}*10s"; break; }
  [[ $i -eq 40 ]] && die "instance did not reach 'running' in 400s"
done

# ---------- 4. Allocate + attach static IP ----------
log "Step 3/8: allocating + attaching static IP"
# Reuse existing if it happens to exist
if ! aws_lightsail get-static-ip --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" >/dev/null 2>&1; then
  aws_lightsail allocate-static-ip --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" --query 'operations[0].status' --output text >/dev/null
  ok "static IP allocated"
else
  ok "static IP already allocated"
fi
aws_lightsail attach-static-ip --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" --instance-name "$LIGHTSAIL_NEW_INSTANCE_NAME" --query 'operations[0].status' --output text >/dev/null
NEW_IP=$(aws_lightsail get-static-ip --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" --query 'staticIp.ipAddress' --output text)
ok "attached: $NEW_IP"

# ---------- 5. Wait for SSH + Docker stack ----------
log "Step 4/8: waiting for SSH on $NEW_IP"
for i in {1..60}; do
  if /usr/bin/ssh -i "$SSH_KEY_LIGHTSAIL" -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$SSH_USER_LIGHTSAIL@$NEW_IP" 'true' >/dev/null 2>&1; then
    ok "SSH responsive after ${i}*4s"
    break
  fi
  [[ $i -eq 60 ]] && die "SSH did not respond in 240s"
  sleep 4
done

log "Step 5/8: waiting for Docker stack to come up (snapshot includes auto-start)"
status=$(/usr/bin/ssh -i "$SSH_KEY_LIGHTSAIL" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$SSH_USER_LIGHTSAIL@$NEW_IP" '
  set -e
  for i in {1..30}; do
    if docker ps --format "{{.Names}}" | grep -q visa_bulletin_web; then
      code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/ || echo "000")
      [ "$code" = "200" ] && { echo "ok"; exit 0; }
    fi
    sleep 5
  done
  # If we got here, web didnt come up auto. Try compose up manually.
  cd /opt/visa_bulletin && docker compose -f deployment/docker-compose.yml up -d 2>&1 | tail -3
  for i in {1..20}; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/ || echo "000")
    [ "$code" = "200" ] && { echo "ok-after-compose"; exit 0; }
    sleep 3
  done
  echo "FAIL"
') || die "Docker stack health check failed"
echo "$status" | /usr/bin/grep -q "ok" || die "web still not serving on :8000 — investigate manually via ssh"
ok "Lightsail web stack healthy"

# ---------- 6. Restore latest GDrive backup ----------
log "Step 6/8: restoring latest GDrive backup into new instance (~5 min)"
"$DIR/restore_latest_backup_on_lightsail.sh" --target-ip "$NEW_IP" --auto-confirm || die "DB restore failed"

# ---------- 7. DNS flip ----------
log "Step 7/8: ready to flip DNS"
echo ""
echo "  Current DNS state:"
for h in "${PROD_HOSTS[@]}"; do
  echo "    $h: $(cf_record_describe "$h")"
done
echo ""
echo "  After flip:"
for h in "${PROD_HOSTS[@]}"; do
  echo "    $h: A $NEW_IP (proxied)"
done
echo ""
warn "Lightsail DR instance is running. Public will hit it after this DNS change."
warn "DR instance is billed at \$10/mo while it exists. Run ./failback.sh ASAP after homeserver recovers."
echo ""
if ! confirm "Flip DNS now?"; then
  warn "Aborted at DNS step. DR instance is up but not in DNS."
  warn "  re-run this to flip when ready"
  warn "  or ./failback.sh to delete the DR instance and release IP"
  exit 0
fi

log "Flipping DNS…"
for h in "${PROD_HOSTS[@]}"; do
  rid=$(cf_record_id "$h")
  [[ -z "$rid" ]] && die "no DNS record found for $h"
  resp=$(cf_record_set "$rid" "$h" "A" "$NEW_IP")
  if echo "$resp" | /usr/bin/python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('success') else 1)"; then
    ok "$h → A $NEW_IP"
  else
    err "$h DNS update failed: $resp"
    exit 1
  fi
done

# ---------- 8. Verify ----------
log "Step 8/8: verifying public traffic now lands on Lightsail"
sleep 6
for h in "${PROD_HOSTS[@]}"; do
  code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" -A "Mozilla/5.0 dr-failover-verify" --max-time 15 "https://${h}/?_dr=$RANDOM")
  [[ "$code" == "200" ]] && ok "https://${h}/ → $code" || warn "https://${h}/ → $code (CF cache may still be propagating)"
done
echo ""
log "✓ Failover complete. Public traffic is on Lightsail (instance: $LIGHTSAIL_NEW_INSTANCE_NAME, IP: $NEW_IP)."
log "  Saving the new IP to /tmp/dr-active-ip for failback.sh"
echo "$NEW_IP" > /tmp/dr-active-ip
log "  When homeserver is recovered: ./failback.sh"
