# Shared variables + helpers for the DR scripts.
# Sourced by failover.sh / failback.sh / restore_latest_backup_on_lightsail.sh.
# This file does NOT execute on its own.

# ---------- Constants ----------
LIGHTSAIL_REGION="us-east-1"
# Cold-DR strategy: spin up a NEW instance from a saved snapshot when needed.
# We don't keep instances stopped (Lightsail bills stopped instances at full
# bundle rate), only a snapshot ($0.05/GB-month).
LIGHTSAIL_SNAPSHOT_NAME="vb-prod-snapshot-2026-05-09"
LIGHTSAIL_NEW_INSTANCE_NAME="vb-dr"
LIGHTSAIL_BUNDLE="small_3_0"          # 2 GB / 1 vCPU / 60 GB SSD ($10/mo). Match what we ran on.
LIGHTSAIL_AZ="us-east-1a"
LIGHTSAIL_STATIC_IP_NAME="vb-dr-ip"   # Allocated on demand during failover, released at failback.
AWS_PROFILE_NAME="visa-bulletin-deploy"
SSH_KEY_LIGHTSAIL="${HOME}/.ssh/lightsail_visa_bulletin"
SSH_USER_LIGHTSAIL="ubuntu"

CF_TOKEN_FILE="${HOME}/tokens/cloudflare_api_token"
# Read CF zone id and tunnel hostname from token files so this script is safe to
# publish in a public repo. Pre-populate:
#   echo -n "<zone-id>" > ~/tokens/cloudflare_zone_id_visa_bulletin
#   echo -n "<tunnel-uuid>.cfargotunnel.com" > ~/tokens/cloudflare_tunnel_homeserver_hostname
#   chmod 600 ~/tokens/cloudflare_zone_id_visa_bulletin ~/tokens/cloudflare_tunnel_homeserver_hostname
CF_ZONE_ID="$(cat "${HOME}/tokens/cloudflare_zone_id_visa_bulletin" 2>/dev/null || echo MISSING_CF_ZONE_ID)"
CF_TUNNEL_HOSTNAME="$(cat "${HOME}/tokens/cloudflare_tunnel_homeserver_hostname" 2>/dev/null || echo MISSING_CF_TUNNEL_HOSTNAME)"
PROD_HOSTS=("visa-bulletin.us" "www.visa-bulletin.us")

GDRIVE_REMOTE="gdrive:visa_bulletin_backups"

# ---------- Output helpers ----------
log()  { printf '\033[1;36m[%s]\033[0m %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ⚠\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m  ✗\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# Yes/No prompt. Returns 0 (yes) or 1 (no).
confirm() {
  local prompt="${1:-Continue?}"
  read -r -p "$prompt [y/N] " ans
  [[ "$ans" =~ ^[Yy] ]]
}

# ---------- AWS / CF clients ----------
aws_lightsail() {
  AWS_PROFILE="$AWS_PROFILE_NAME" /opt/homebrew/bin/aws lightsail --region "$LIGHTSAIL_REGION" "$@"
}

cf_api() {
  local method="$1"; shift
  local path="$1"; shift
  local token; token=$(/bin/cat "$CF_TOKEN_FILE")
  /usr/bin/curl -s -X "$method" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4${path}" "$@"
}

# Fetch DNS record id for a name (echos id, or empty)
cf_record_id() {
  local name="$1"
  cf_api GET "/zones/$CF_ZONE_ID/dns_records?name=${name}" \
    | /usr/bin/python3 -c "import json,sys; d=json.load(sys.stdin); r=d['result']; print(r[0]['id'] if r else '')"
}

# Get current type+content for a record
cf_record_describe() {
  local name="$1"
  cf_api GET "/zones/$CF_ZONE_ID/dns_records?name=${name}" \
    | /usr/bin/python3 -c "
import json,sys
d=json.load(sys.stdin)
r=d['result']
if r:
    print(f\"{r[0]['type']} {r[0]['content']} (proxied={r[0]['proxied']})\")
else:
    print('NOT FOUND')
"
}

# Replace a DNS record (requires record id)
cf_record_set() {
  local rec_id="$1" name="$2" type="$3" content="$4"
  cf_api PUT "/zones/$CF_ZONE_ID/dns_records/${rec_id}" \
    --data "{\"type\":\"${type}\",\"name\":\"${name}\",\"content\":\"${content}\",\"ttl\":1,\"proxied\":true}"
}
