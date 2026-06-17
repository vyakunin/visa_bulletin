#!/usr/bin/env bash
# alert_5xx_spike.sh — periodic origin-5xx watchdog for visa-bulletin.us.
#
# WHY: UptimeRobot only pings `/` (always 200 here), so a per-path 5xx
# regression — e.g. the 2026-06-10 EmptyResultSet 500s on /salaries/?employer=
# (~325/day, 0.53% of total traffic) — is completely invisible to it, and the
# daily_checkup digest only catches it once a day. This cron scans the recent
# nginx window and fires an alert the moment a single path starts emitting 500s
# in bulk, or gateway 5xx spike.
#
# 500 vs 502 SPLIT (added 2026-06-14): a 500 is a Django app exception (real bug,
# has a traceback); a 502/503/504 is nginx↔upstream gateway failure — almost
# always the ~10-15s deploy blip when vb_web restarts, NOT a code bug. Counting
# them together produced two false "app exception on a query shape" alarms in one
# session on pure deploy-blip 502s. So Rule 1 (the high-signal app-bug case) now
# fires on per-path 500s ONLY; gateway 5xx get a separate, correctly-labelled
# Rule 2 so a real outage still pages but a deploy blip isn't mislabelled.
#
# CHANNEL (changed 2026-06-14): delivery now goes through the shared notify_chat
# sink on the minipc (POST /notify, bearer-auth) so the alert is XADD'd onto the
# visa_bulletin relay stream as a synthetic owner message → the agent actually
# REACTS (investigate + act), instead of the old raw `curl sendMessage` which —
# being a bot self-post — never triggered a listener at all (a passive post only).
# Config in /opt/stack/_shared/notify_chat.env (NOTIFY_CHAT_URL, NOTIFY_CHAT_TOKEN).
# Falls back to the old Telegram-bot post (TG_ALERT_* in backup_blob.env) if the
# sink is unreachable, so an alert is never silently dropped.
#
# INPUTS (env-overridable):
#   WINDOW            log look-back passed to `docker logs --since` (default 15m)
#   PATH_500_THRESHOLD  per-path 500 count in the window that trips Rule 1 (10)
#   GATEWAY_MIN_5XX   min gateway (502/503/504) count before Rule 2 fires (20)
#   GLOBAL_RATE_PCT   total-5xx % of responses for the Rule 2 rate gate (2.0)
#   COOLDOWN_MIN      suppress re-alert for the same key within N min (60)
#   NOTIFY_ENV        path to NOTIFY_CHAT_* env (default _shared/notify_chat.env)
#   ALERT_ENV         path to the TG_ALERT_* fallback env
#                     (default /opt/stack/_shared/backup_blob.env)
#   PROJECT           relay project / bot suffix (default visa_bulletin)
#   NGINX_CONTAINER   default vb_nginx
#   DRY_RUN=1         print the alert instead of sending (for testing)
#
# OUTPUT: exits 0 always (a watchdog must not page on its own failure); logs to
# stdout (cron redirects to logs/cron/alert_5xx.log). State (last-alert per key)
# lives in /opt/stack/visa_bulletin/logs/cron/.alert_5xx_state so a sustained
# outage alerts once per COOLDOWN_MIN, not every tick.
set -uo pipefail

WINDOW="${WINDOW:-15m}"
PATH_500_THRESHOLD="${PATH_500_THRESHOLD:-${PATH_5XX_THRESHOLD:-10}}"  # back-compat alias
GATEWAY_MIN_5XX="${GATEWAY_MIN_5XX:-${GLOBAL_MIN_5XX:-20}}"
GLOBAL_RATE_PCT="${GLOBAL_RATE_PCT:-2.0}"
COOLDOWN_MIN="${COOLDOWN_MIN:-60}"
NOTIFY_ENV="${NOTIFY_ENV:-/opt/stack/_shared/notify_chat.env}"
ALERT_ENV="${ALERT_ENV:-/opt/stack/_shared/backup_blob.env}"
PROJECT="${PROJECT:-visa_bulletin}"
NGINX_CONTAINER="${NGINX_CONTAINER:-vb_nginx}"
STATE_FILE="${STATE_FILE:-/opt/stack/visa_bulletin/logs/cron/.alert_5xx_state}"
NOW_EPOCH="$(date -u +%s)"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# Deliver an alert: primary = notify_chat sink (agent reacts via relay inject);
# fallback = the old direct Telegram bot post (passive) if the sink is down.
send_alert() {
  local msg="$1"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "[DRY_RUN] would alert: ${msg}"
    return
  fi
  # Primary path — POST to notify_chat on the minipc.
  if [ -f "$NOTIFY_ENV" ]; then
    # shellcheck disable=SC1090
    . "$NOTIFY_ENV"
  fi
  if [ -n "${NOTIFY_CHAT_URL:-}" ] && [ -n "${NOTIFY_CHAT_TOKEN:-}" ]; then
    # jq-free JSON: escape backslashes, quotes, then control chars via printf.
    local esc
    esc="$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' ')"
    local body="{\"project\":\"${PROJECT}\",\"mode\":\"inject\",\"text\":\"${esc}\"}"
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      -X POST "$NOTIFY_CHAT_URL" \
      -H "Authorization: Bearer ${NOTIFY_CHAT_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$body" 2>/dev/null)"
    if [ "$code" = "200" ]; then
      log "alert delivered via notify_chat (HTTP 200)"
      return
    fi
    log "WARN: notify_chat POST returned '${code}'; falling back to Telegram"
  else
    log "WARN: no NOTIFY_CHAT_URL/TOKEN in ${NOTIFY_ENV}; using Telegram fallback"
  fi
  # Fallback path — direct Telegram bot post (passive; human-read only).
  if [ -f "$ALERT_ENV" ]; then
    # shellcheck disable=SC1090
    . "$ALERT_ENV"
  fi
  if [ -n "${TG_ALERT_BOT_TOKEN:-}" ] && [ -n "${TG_ALERT_CHAT_ID:-}" ]; then
    curl -s --max-time 20 \
      "https://api.telegram.org/bot${TG_ALERT_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TG_ALERT_CHAT_ID}" \
      --data-urlencode "text=🚨 visa-bulletin 5xx (fallback): ${msg}" >/dev/null 2>&1 \
      && log "alert delivered via Telegram fallback" \
      || log "WARN: Telegram fallback curl failed"
  else
    log "WARN: no fallback TG_ALERT_* in ${ALERT_ENV}; alert NOT delivered"
  fi
}

# Cooldown: don't re-alert for the same key within COOLDOWN_MIN.
recently_alerted() {
  local key="$1"
  [ -f "$STATE_FILE" ] || return 1
  local last
  last="$(grep -F "${key}|" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d'|' -f2)"
  [ -n "$last" ] || return 1
  [ $(( (NOW_EPOCH - last) / 60 )) -lt "$COOLDOWN_MIN" ]
}
record_alert() {
  mkdir -p "$(dirname "$STATE_FILE")"
  # keep only the last 50 lines so the file doesn't grow unbounded
  { grep -vF "$1|" "$STATE_FILE" 2>/dev/null; echo "$1|${NOW_EPOCH}"; } | tail -50 > "${STATE_FILE}.tmp" \
    && mv "${STATE_FILE}.tmp" "$STATE_FILE"
}

LOGS="$(docker logs "$NGINX_CONTAINER" --since "$WINDOW" 2>/dev/null)"
if [ -z "$LOGS" ]; then
  log "no nginx logs in window ${WINDOW}; nothing to check"
  exit 0
fi

# Single awk pass. nginx combined format:
#   $1=client $4=[date $5=tz] $6="METHOD $7=/uri $8=proto" $9=status $11=req_time
# Buckets: total responses; all-5xx; gateway (502/503/504); per-path 500 counts.
ANALYSIS="$(echo "$LOGS" | awk '
  {
    status=$9
    if (status !~ /^[0-9]+$/) next
    total++
    if (substr(status,1,1)=="5") {
      five++
      if (status=="502" || status=="503" || status=="504") gw++
      if (status=="500") { path=$7; sub(/\?.*$/, "", path); by_path500[path]++ }
    }
  }
  END {
    printf "TOTAL=%d\nFIVE=%d\nGW=%d\n", total, five, gw
    for (p in by_path500) printf "P500|%d|%s\n", by_path500[p], p
  }
')"

TOTAL="$(echo "$ANALYSIS" | awk -F= '/^TOTAL=/{print $2}')"; TOTAL="${TOTAL:-0}"
FIVE="$(echo "$ANALYSIS"  | awk -F= '/^FIVE=/{print $2}')";  FIVE="${FIVE:-0}"
GW="$(echo "$ANALYSIS"    | awk -F= '/^GW=/{print $2}')";    GW="${GW:-0}"
RATE_PCT="$(awk -v f="$FIVE" -v t="$TOTAL" 'BEGIN{ printf "%.2f", (t>0)? f/t*100 : 0 }')"
log "window=${WINDOW} total=${TOTAL} 5xx=${FIVE} (gateway502/3/4=${GW}) rate=${RATE_PCT}%"

ALERTED=0

# Rule 1 — per-path 500 spike. THE high-signal app-regression case (real bug,
# has a Django traceback). Gateway 5xx are deliberately excluded here.
while IFS='|' read -r tag cnt path; do
  [ "$tag" = "P500" ] || continue
  if [ "$cnt" -ge "$PATH_500_THRESHOLD" ]; then
    if recently_alerted "500:$path"; then
      log "path ${path}: ${cnt} 500s (>= ${PATH_500_THRESHOLD}) — in cooldown, not re-alerting"
    else
      sample="$(echo "$LOGS" | awk -v p="$path" '{u=$7; sub(/\?.*$/,"",u); if (u==p && $9=="500"){print $7; exit}}')"
      send_alert "${cnt} app-500s on ${path} in last ${WINDOW} (overall 5xx rate ${RATE_PCT}%). e.g. ${sample}. App exception (has a traceback) — check: docker logs vb_web --since ${WINDOW} | grep 'Internal Server Error: ${path}'"
      record_alert "500:$path"
      ALERTED=1
    fi
  fi
done <<< "$(echo "$ANALYSIS" | grep '^P500|')"

# Rule 2 — gateway 5xx (502/503/504) spike: vb_web unreachable/restarting. Usually
# a deploy blip (~10-15s, self-clears); a SUSTAINED burst means a real crash loop.
# Labelled as gateway so it is NEVER mistaken for an app-code bug.
if [ "$GW" -ge "$GATEWAY_MIN_5XX" ] && awk -v r="$RATE_PCT" -v m="$GLOBAL_RATE_PCT" 'BEGIN{exit !(r>=m)}'; then
  if recently_alerted "__GATEWAY__"; then
    log "gateway 5xx ${GW} (>= ${GATEWAY_MIN_5XX}, rate ${RATE_PCT}%) — in cooldown"
  else
    send_alert "${GW} gateway 5xx (502/503/504) = part of ${RATE_PCT}% in last ${WINDOW}. vb_web unreachable/restarting — likely a deploy blip if it self-clears; a real crash loop if sustained. Check: docker ps --filter name=vb_web; docker logs vb_web --since ${WINDOW} | tail -50"
    record_alert "__GATEWAY__"
    ALERTED=1
  fi
fi

[ "$ALERTED" = "0" ] && log "no breach"
exit 0
