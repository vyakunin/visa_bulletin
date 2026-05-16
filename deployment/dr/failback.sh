#!/bin/bash
# Disaster recovery: take prod traffic OFF the DR Lightsail instance and back
# ON the homeserver.
#
# Use after running failover.sh, when:
#   - homeserver is healthy again
#   - you've verified https://staging.visa-bulletin.us/ works (proves tunnel +
#     homeserver stack)
#
# What this does:
#   1. Pre-flight: confirm homeserver tunnel is healthy
#   2. Confirm with you before flipping DNS
#   3. Flip CF DNS: visa-bulletin.us + www → CNAME tunnel (proxied)
#   4. Verify https://visa-bulletin.us/ now serves from homeserver
#   5. DELETE the DR Lightsail instance (so billing stops immediately)
#   6. RELEASE the static IP (so we don't pay for orphan IP)
#
# Total time: ~2 min.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/_lib.sh"

log "=== Disaster Recovery: failback Lightsail → homeserver ==="
echo ""

# ---------- 1. Pre-flight ----------
log "Step 1/6: confirm homeserver tunnel is alive"
edge_ip=$(/usr/bin/dig +short staging.visa-bulletin.us | /usr/bin/head -1)
[[ -z "$edge_ip" ]] && die "could not resolve a CF edge IP via staging.visa-bulletin.us"
log "  CF edge IP for testing: $edge_ip"

code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  --resolve "visa-bulletin.us:443:$edge_ip" \
  -A "Mozilla/5.0 dr-failback-preflight" \
  "https://visa-bulletin.us/?_dr_pre=$RANDOM")
[[ "$code" == "200" ]] || die "homeserver tunnel did NOT return 200 (got $code). DO NOT failback yet — fix homeserver first."
ok "homeserver tunnel responds 200 → safe to failback"
echo ""

# ---------- 2. Confirm DNS flip ----------
log "Step 2/6: ready to flip DNS"
echo ""
echo "  Current DNS state:"
for h in "${PROD_HOSTS[@]}"; do
  echo "    $h: $(cf_record_describe "$h")"
done
echo ""
echo "  After flip:"
for h in "${PROD_HOSTS[@]}"; do
  echo "    $h: CNAME $CF_TUNNEL_HOSTNAME (proxied)"
done
echo ""
if ! confirm "Flip DNS back to homeserver tunnel now?"; then
  warn "aborted at DNS step. DR instance and IP NOT cleaned up; manual steps if you want to abandon now:"
  warn "  aws lightsail delete-instance --instance-name $LIGHTSAIL_NEW_INSTANCE_NAME"
  warn "  aws lightsail release-static-ip --static-ip-name $LIGHTSAIL_STATIC_IP_NAME"
  exit 0
fi

# ---------- 3. Flip ----------
log "Step 3/6: flipping DNS…"
for h in "${PROD_HOSTS[@]}"; do
  rid=$(cf_record_id "$h")
  [[ -z "$rid" ]] && die "no DNS record found for $h"
  resp=$(cf_record_set "$rid" "$h" "CNAME" "$CF_TUNNEL_HOSTNAME")
  if echo "$resp" | /usr/bin/python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('success') else 1)"; then
    ok "$h → CNAME $CF_TUNNEL_HOSTNAME"
  else
    err "$h DNS update failed: $resp"; exit 1
  fi
done
echo ""

# ---------- 4. Verify ----------
log "Step 4/6: verifying public traffic now lands on homeserver"
sleep 6
for h in "${PROD_HOSTS[@]}"; do
  code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" -A "Mozilla/5.0 dr-failback-verify" --max-time 15 "https://${h}/?_dr=$RANDOM")
  [[ "$code" == "200" ]] && ok "https://${h}/ → $code" || warn "https://${h}/ → $code (CF cache propagating)"
done
echo ""

# ---------- 5. Delete DR instance + IP ----------
log "Step 5/6: cleaning up DR resources"
echo ""
warn "About to DELETE Lightsail DR instance '$LIGHTSAIL_NEW_INSTANCE_NAME' and release IP '$LIGHTSAIL_STATIC_IP_NAME'."
warn "Snapshot ('$LIGHTSAIL_SNAPSHOT_NAME') is preserved — you can run failover.sh again any time."
echo ""
if ! confirm "Delete DR instance + release IP now?"; then
  warn "skipped cleanup. DR instance is still running and billing."
  warn "  you can delete later with:"
  warn "    aws lightsail delete-instance --instance-name $LIGHTSAIL_NEW_INSTANCE_NAME"
  warn "    aws lightsail release-static-ip --static-ip-name $LIGHTSAIL_STATIC_IP_NAME"
  exit 0
fi

# Detach IP first, then release. Order matters.
aws_lightsail detach-static-ip --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" --query 'operations[0].status' --output text >/dev/null 2>&1 || true
aws_lightsail release-static-ip --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" --query 'operations[0].status' --output text >/dev/null && ok "static IP released"

aws_lightsail delete-instance --instance-name "$LIGHTSAIL_NEW_INSTANCE_NAME" --query 'operations[0].status' --output text >/dev/null && ok "instance deletion initiated"
echo ""

# ---------- 6. Final state ----------
log "Step 6/6: final state"
sleep 5
echo ""
AWS_PROFILE=visa-bulletin-deploy /opt/homebrew/bin/aws lightsail get-instances --region us-east-1 --query 'instances[*].{name:name,state:state.name}' --output table 2>/dev/null
echo ""
AWS_PROFILE=visa-bulletin-deploy /opt/homebrew/bin/aws lightsail get-static-ips --region us-east-1 --query 'staticIps[*].{name:name,attached:isAttached}' --output table 2>/dev/null
echo ""
/bin/rm -f /tmp/dr-active-ip
log "✓ Failback complete. Public on homeserver. DR instance + IP cleaned up. Snapshot preserved."
