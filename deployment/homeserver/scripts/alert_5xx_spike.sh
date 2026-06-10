#!/usr/bin/env bash
# alert_5xx_spike.sh — periodic origin-5xx watchdog for visa-bulletin.us.
#
# WHY: UptimeRobot only pings `/` (always 200 here), so a per-path 5xx
# regression — e.g. the 2026-06-10 EmptyResultSet 500s on /salaries/?employer=
# (~325/day, 0.53% of total traffic) — is completely invisible to it, and the
# daily_checkup digest only catches it once a day. This cron scans the recent
# nginx window and fires a Telegram alert the moment a single path starts
# emitting 5xx in bulk, or the overall 5xx rate spikes.
#
# CHANNEL: reuses the same Telegram alert env the backup scripts use
# (/opt/stack/_shared/backup_blob.env → TG_ALERT_BOT_TOKEN, TG_ALERT_CHAT_ID).
# No SMTP/email needed; the message lands in the visa_bulletin bot chat (the
# listener auto-spawns on it, same as a forwarded UptimeRobot DOWN email).
#
# INPUTS (env-overridable):
#   WINDOW            log look-back passed to `docker logs --since` (default 15m)
#   PATH_5XX_THRESHOLD  per-path 5xx count in the window that trips an alert (10)
#   GLOBAL_MIN_5XX    min total 5xx before the rate rule can fire (20)
#   GLOBAL_RATE_PCT   total-5xx % of responses that trips an alert (2.0)
#   COOLDOWN_MIN      suppress re-alert for the same top path within N min (60)
#   ALERT_ENV         path to the TG_ALERT_* env file
#                     (default /opt/stack/_shared/backup_blob.env)
#   NGINX_CONTAINER   default vb_nginx
#   DRY_RUN=1         print the alert instead of sending (for testing)
#
# OUTPUT: exits 0 always (a watchdog must not page on its own failure); logs to
# stdout (cron redirects to logs/cron/alert_5xx.log). State (last-alert per path)
# lives in /opt/stack/visa_bulletin/logs/cron/.alert_5xx_state so a sustained
# outage alerts once per COOLDOWN_MIN, not every tick.
set -uo pipefail

WINDOW="${WINDOW:-15m}"
PATH_5XX_THRESHOLD="${PATH_5XX_THRESHOLD:-10}"
GLOBAL_MIN_5XX="${GLOBAL_MIN_5XX:-20}"
GLOBAL_RATE_PCT="${GLOBAL_RATE_PCT:-2.0}"
COOLDOWN_MIN="${COOLDOWN_MIN:-60}"
ALERT_ENV="${ALERT_ENV:-/opt/stack/_shared/backup_blob.env}"
NGINX_CONTAINER="${NGINX_CONTAINER:-vb_nginx}"
STATE_FILE="${STATE_FILE:-/opt/stack/visa_bulletin/logs/cron/.alert_5xx_state}"
NOW_EPOCH="$(date -u +%s)"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

send_alert() {
  local msg="$1"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "[DRY_RUN] would alert: ${msg}"
    return
  fi
  if [ -f "$ALERT_ENV" ]; then
    # shellcheck disable=SC1090
    . "$ALERT_ENV"
  fi
  if [ -n "${TG_ALERT_BOT_TOKEN:-}" ] && [ -n "${TG_ALERT_CHAT_ID:-}" ]; then
    curl -s --max-time 20 \
      "https://api.telegram.org/bot${TG_ALERT_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TG_ALERT_CHAT_ID}" \
      --data-urlencode "text=🚨 visa-bulletin 5xx spike: ${msg}" >/dev/null 2>&1 \
      || log "WARN: alert curl failed"
  else
    log "WARN: no TG_ALERT_BOT_TOKEN/CHAT_ID in ${ALERT_ENV}; cannot alert"
  fi
}

# Cooldown: don't re-alert for the same top path within COOLDOWN_MIN.
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

# Single awk pass: total responses, total 5xx, and per-path 5xx counts (path =
# $7 with the query string stripped). nginx combined format:
#   $1=client $4=[date $5=tz] $6="METHOD $7=/uri $8=proto" $9=status $11=req_time
ANALYSIS="$(echo "$LOGS" | awk '
  {
    status=$9
    if (status !~ /^[0-9]+$/) next
    total++
    if (substr(status,1,1)=="5") {
      five++
      path=$7; sub(/\?.*$/, "", path)
      by_path[path]++
    }
  }
  END {
    printf "TOTAL=%d\nFIVE=%d\n", total, five
    for (p in by_path) printf "PATH|%d|%s\n", by_path[p], p
  }
')"

TOTAL="$(echo "$ANALYSIS" | awk -F= '/^TOTAL=/{print $2}')"
FIVE="$(echo "$ANALYSIS" | awk -F= '/^FIVE=/{print $2}')"
TOTAL="${TOTAL:-0}"; FIVE="${FIVE:-0}"
RATE_PCT="$(awk -v f="$FIVE" -v t="$TOTAL" 'BEGIN{ printf "%.2f", (t>0)? f/t*100 : 0 }')"
log "window=${WINDOW} total=${TOTAL} 5xx=${FIVE} rate=${RATE_PCT}%"

ALERTED=0

# Rule 1 — per-path spike (the high-signal app-regression case).
while IFS='|' read -r tag cnt path; do
  [ "$tag" = "PATH" ] || continue
  if [ "$cnt" -ge "$PATH_5XX_THRESHOLD" ]; then
    if recently_alerted "$path"; then
      log "path ${path}: ${cnt} 5xx (>= ${PATH_5XX_THRESHOLD}) — in cooldown, not re-alerting"
    else
      sample="$(echo "$LOGS" | awk -v p="$path" '{u=$7; sub(/\?.*$/,"",u); if (u==p && substr($9,1,1)=="5"){print $7; exit}}')"
      send_alert "${cnt} 5xx on ${path} in last ${WINDOW} (rate ${RATE_PCT}%). e.g. ${sample}. Likely an app exception on a query shape — check: docker logs vb_web --since ${WINDOW} | grep 'Internal Server Error: ${path}'"
      record_alert "$path"
      ALERTED=1
    fi
  fi
done <<< "$(echo "$ANALYSIS" | grep '^PATH|')"

# Rule 2 — overall rate spike (broader outage; one path may not dominate).
if awk -v r="$RATE_PCT" -v m="$GLOBAL_RATE_PCT" 'BEGIN{exit !(r>=m)}' && [ "$FIVE" -ge "$GLOBAL_MIN_5XX" ]; then
  if recently_alerted "__GLOBAL__"; then
    log "global rate ${RATE_PCT}% (>= ${GLOBAL_RATE_PCT}%, ${FIVE} 5xx) — in cooldown"
  else
    top="$(echo "$ANALYSIS" | grep '^PATH|' | sort -t'|' -k2 -rn | head -3 | awk -F'|' '{printf "%s(%s) ", $3, $2}')"
    send_alert "${FIVE} 5xx = ${RATE_PCT}% of ${TOTAL} responses in last ${WINDOW}. Top paths: ${top}"
    record_alert "__GLOBAL__"
    ALERTED=1
  fi
fi

[ "$ALERTED" = "0" ] && log "no breach"
exit 0
