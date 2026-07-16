#!/usr/bin/env bash
# Minipc -> prod bulletin ingest bridge (Akamai wall bypass). THE bulletin ingest path.
#
# travel.state.gov is behind Akamai; the prod box (vb_web, no browser) cannot fetch
# it — the old prod-side hourly `refresh_bulletin` cron 403'd on every run and was
# retired 2026-07-16. The minipc debug Chrome passes the wall. This script runs on
# the MINIPC:
#   1. Browser-fetch the bulletin index + current/next month pages into a local cache
#      (scripts/fetch_bulletin_via_browser.py).
#   2. Stream the cache into the prod vb_web container (tar over ssh; no scp of repo).
#   3. Run scripts.cron.refresh_bulletin in vb_web with BULLETIN_HTML_CACHE_DIR pointed
#      at the streamed cache, so discover/download read the browser-fetched HTML instead
#      of hitting Akamai. Parse/load/predict run prod-side, unchanged, and dedup makes
#      already-ingested months a no-op.
#
# Idempotent: safe to run repeatedly (dedup by DataSource). Requires: debug Chrome on
# :9222, ssh alias `homeserver`.
#
# ALERTING (this is the only thing watching bulletin ingest — see
# ~/.claude/rules/monitoring_means_realtime_alerts.md):
#   * A SINGLE failed run is normal — the Akamai challenge intermittently doesn't
#     settle (~1 in 6 observed) and the next run recovers. So failures alert only
#     after ALERT_AFTER consecutive misses (default 3 = 90min at */30), via
#     notify_chat inject -> the agent investigates.
#   * Recovery after an alerting streak sends a passive all-clear.
#   * A NEW bulletin landing injects too (rare, ~12/yr): the agent verifies the site,
#     predictions, and the generated post.
#   * Ingest-broke (refresh non-zero, or pending sources that all fail) alerts
#     immediately — that's never transient.
#   * The BLIND SPOT this cannot cover is "the cron stopped firing at all" (no run =
#     no alert). The visa_bulletin daily_checkup MCP is the backstop: it reads
#     $STATE_DIR/last_success and flags staleness in the morning digest.
#
# Usage: scripts/sync_bulletin_to_prod.sh [--months YYYY-MM,YYYY-MM]
# Exit: 0 ok; 2 fetch failed (wall not passed / CDP down); 3 prod-side ingest failed.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="/tmp/bulletin_html_cache"
CONTAINER_CACHE="/tmp/vb_bulletin_cache"
STATE_DIR="${BULLETIN_SYNC_STATE_DIR:-$HOME/.local/state/visa_bulletin}"
FAIL_STREAK_FILE="$STATE_DIR/fetch_fail_streak"
LAST_SUCCESS_FILE="$STATE_DIR/last_success"
# Overridable so the alert path can be exercised against a recorder stub instead of
# the live bot (see tests/test_sync_bulletin_alerting.sh).
NOTIFY="${BULLETIN_SYNC_NOTIFY:-$HOME/cursor_projects/agent_infra/scripts/notify_chat.py}"
ALERT_AFTER="${BULLETIN_SYNC_ALERT_AFTER:-3}"
MONTHS_ARG=()
[ "${1:-}" = "--months" ] && MONTHS_ARG=(--months "$2")
# Mirrors fetch_bulletin_via_browser.py --cdp. Set BULLETIN_FETCH_CDP to point at a
# different (or deliberately dead) CDP endpoint — the latter is how the alert path
# gets exercised without waiting for a real Akamai miss.
CDP_ARG=()
[ -n "${BULLETIN_FETCH_CDP:-}" ] && CDP_ARG=(--cdp "$BULLETIN_FETCH_CDP")

mkdir -p "$STATE_DIR"

log() { echo "[sync_bulletin] $*"; }

# alert <mode> <throttle-key> <cooldown-min> <text>
# Never fails the run: a broken alert path must not also break ingest.
alert() {
  local mode="$1" key="$2" cooldown="$3" text="$4"
  if [ ! -f "$NOTIFY" ]; then
    log "WARN: notify_chat not found at $NOTIFY; alert dropped: $text"
    return 0
  fi
  uv run "$NOTIFY" --project visa_bulletin --mode "$mode" \
    --throttle-key "$key" --cooldown-min "$cooldown" "$text" \
    || log "WARN: notify_chat failed; alert not delivered: $text"
}

read_streak() { cat "$FAIL_STREAK_FILE" 2>/dev/null || echo 0; }

# Record a failed fetch; alert once the streak crosses ALERT_AFTER.
fail_fetch() {
  local detail="$1"
  local streak
  streak=$(( $(read_streak) + 1 ))
  echo "$streak" > "$FAIL_STREAK_FILE"
  log "ERROR: index fetch failed (streak=$streak): $detail"
  if [ "$streak" -ge "$ALERT_AFTER" ]; then
    local last_ok
    last_ok="$(cat "$LAST_SUCCESS_FILE" 2>/dev/null || echo 'never')"
    alert inject "bulletin-sync:fetch-fail" 60 \
      "🚨 Bulletin ingest bridge failing: ${streak} consecutive fetch failures (last success: ${last_ok}). travel.state.gov Akamai wall not passed, or the debug Chrome on :9222 is down. The prod-side cron is retired, so this is the ONLY bulletin ingest path — the August bulletin would be missed. Check: systemctl --user status debug_chrome_cdp.service; tail -40 ${REPO}/logs/sync_bulletin_to_prod.log; then run ${REPO}/scripts/sync_bulletin_to_prod.sh by hand. Detail: ${detail}"
  fi
  exit 2
}

log "$(date -u +%FT%TZ) fetching via debug Chrome..."
rm -rf "$CACHE"
# stdout = the JSON summary; stderr = the fetcher's own INFO/ERROR log lines. Keep
# them apart so `grep '"index_ok"'` stays exact, but replay stderr into the cron log
# and reuse its tail as the alert detail.
FETCH_ERR="$(mktemp)"
trap 'rm -f "$FETCH_ERR"' EXIT
SUMMARY="$(cd "$REPO" && uv run --with playwright --with python-dateutil \
  python scripts/fetch_bulletin_via_browser.py --cache-dir "$CACHE" \
  "${MONTHS_ARG[@]}" "${CDP_ARG[@]}" 2>"$FETCH_ERR")"
FETCH_RC=$?
cat "$FETCH_ERR"
log "fetch summary: $SUMMARY"

# Two distinct failure shapes: a non-zero exit (CDP down, crash) and a clean exit
# whose summary says the wall wasn't passed. Both are the same alert.
if [ "$FETCH_RC" -ne 0 ] || ! echo "$SUMMARY" | grep -q '"index_ok": true'; then
  fail_fetch "rc=${FETCH_RC} $(tail -3 "$FETCH_ERR" | tr '\n' ' ')"
fi

# Fetch OK. If we were in an alerting streak, say so, then reset.
PREV_STREAK=$(read_streak)
if [ "$PREV_STREAK" -ge "$ALERT_AFTER" ]; then
  alert passive "bulletin-sync:recovered" 0 \
    "✅ Bulletin ingest bridge recovered after ${PREV_STREAK} failed runs — wall passed, index fetched."
fi
echo 0 > "$FAIL_STREAK_FILE"
date -u +%FT%TZ > "$LAST_SUCCESS_FILE"

log "streaming cache -> vb_web:$CONTAINER_CACHE"
if ! ssh homeserver "docker exec -i vb_web sh -c 'rm -rf $CONTAINER_CACHE && mkdir -p $CONTAINER_CACHE && tar -C $CONTAINER_CACHE -xf -'" < <(tar -C "$CACHE" -cf - .); then
  log "ERROR: streaming cache to vb_web failed"
  alert inject "bulletin-sync:stream-fail" 60 \
    "🚨 Bulletin bridge: fetched the HTML but could not stream it into vb_web (ssh homeserver / docker exec failed). Bulletin ingest is stalled — check the homeserver and vb_web container."
  exit 3
fi

log "running refresh_bulletin (cache-backed) in vb_web..."
REFRESH_OUT="$(ssh homeserver "docker exec -e BULLETIN_HTML_CACHE_DIR=$CONTAINER_CACHE -w /app vb_web \
  python3 -m scripts.cron.refresh_bulletin" 2>&1)"
REFRESH_RC=$?
echo "$REFRESH_OUT"

log "cleaning up container cache"
ssh homeserver "docker exec vb_web rm -rf $CONTAINER_CACHE" || true

if [ "$REFRESH_RC" -ne 0 ]; then
  alert inject "bulletin-sync:refresh-fail" 60 \
    "🚨 Bulletin bridge: browser fetch passed the wall but prod-side refresh_bulletin exited ${REFRESH_RC}. Ingest is broken (parser/DB, not Akamai). Tail: $(echo "$REFRESH_OUT" | tail -5 | tr '\n' ' ')"
  exit 3
fi

# Pending sources that all failed to ingest = a real parse/load break, never transient.
if echo "$REFRESH_OUT" | grep -q "No bulletins were successfully ingested."; then
  alert inject "bulletin-sync:ingest-fail" 60 \
    "🚨 Bulletin bridge: a new bulletin source was discovered but NONE ingested successfully — parser or DB break. Tail: $(echo "$REFRESH_OUT" | tail -5 | tr '\n' ' ')"
  exit 3
fi

# The payoff event: a new month landed. Rare (~12/yr) and worth an agent pass over
# the live site (predictions published? post generated? CF purged?).
if echo "$REFRESH_OUT" | grep -qE "Ingested [0-9]+ bulletin\(s\)"; then
  INGESTED_LINE="$(echo "$REFRESH_OUT" | grep -E "Ingested [0-9]+ bulletin\(s\)" | tail -1)"
  alert inject "bulletin-sync:new-bulletin" 0 \
    "📗 New Visa Bulletin ingested on prod (${INGESTED_LINE}). Verify the end-state: visa-bulletin.us renders the new month, predictions published, the analysis post generated and reading correctly, CF edge purged."
fi

log "done $(date -u +%FT%TZ)"
