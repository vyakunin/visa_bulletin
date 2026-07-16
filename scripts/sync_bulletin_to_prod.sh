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
#     immediately — that's never transient EXCEPT during a data cutover, which resyncs
#     the prod DB out from under us. Hence the cutover interlock (CUTOVER_MARKER): while
#     `visa_bulletin_platform/hosting/cutover.sh` is armed, the run skips instead of
#     ingesting or alerting. Do not "simplify" that to a bare file-exists check — see
#     cutover_in_flight().
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
# Cutover interlock. visa_bulletin_platform/hosting/cutover.sh resyncs the prod DB from
# staging (pg_dump | psql) and restarts vb_web; it writes its PID to this marker for the
# whole armed window. The path is a cross-repo contract — change it in both or the
# interlock silently disappears.
CUTOVER_MARKER="${VB_CUTOVER_MARKER:-/tmp/vb_cutover_in_flight}"
CUTOVER_MAX_AGE_MIN="${VB_CUTOVER_MAX_AGE_MIN:-120}"

mkdir -p "$STATE_DIR"

log() { echo "[sync_bulletin] $*"; }

# True only while a cutover is GENUINELY armed. Two reasons this must never touch prod
# mid-cutover (2026-07-16):
#   1. Noise: mid-resync the prod DB is transiently half-populated and constraint-less,
#      so refresh_bulletin dies on MultipleObjectsReturned — indistinguishable, to the
#      alerts below, from a real parser/DB break. A healthy release paged as "ingest is
#      broken".
#   2. Damage: discover_bulletin_sources() does get_or_create on DataSource. An INSERT
#      landing after that table's COPY but before the restore rebuilds its unique index
#      makes CREATE UNIQUE INDEX fail — and the resync's psql runs ON_ERROR_STOP=0, so it
#      plows on and leaves prod permanently WITHOUT that constraint.
# A stale marker must not mute ingest forever: cutover.sh's EXIT trap does not run on
# SIGKILL, and this is the only bulletin ingest path, so a forgotten marker would silently
# drop a bulletin. Hence require a live owner AND a sane age, and say so when ignoring one.
cutover_in_flight() {
  [ -f "$CUTOVER_MARKER" ] || return 1
  local pid age
  pid="$(tr -dc '0-9' < "$CUTOVER_MARKER" 2>/dev/null)"
  age=$(( ( $(date +%s) - $(stat -c %Y "$CUTOVER_MARKER" 2>/dev/null || echo 0) ) / 60 ))
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && [ "$age" -lt "$CUTOVER_MAX_AGE_MIN" ]; then
    return 0
  fi
  log "WARN: ignoring stale cutover marker $CUTOVER_MARKER (pid='${pid:-none}' age=${age}min, max=${CUTOVER_MAX_AGE_MIN}) — proceeding with ingest."
  return 1
}

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

if cutover_in_flight; then
  log "cutover in flight (marker $CUTOVER_MARKER) — skipping this run entirely; the prod DB is mid-resync. The next tick picks it up; dedup makes a delayed month a no-op."
  exit 0
fi

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
  # A cutover that armed AFTER the top-of-run check restarts vb_web out from under us.
  if cutover_in_flight; then
    log "...but a cutover armed mid-run — vb_web is being swapped. Transient, not alerting."
    exit 0
  fi
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
  if cutover_in_flight; then
    log "refresh exited ${REFRESH_RC}, but a cutover armed mid-run — the prod DB is mid-resync. Transient, not alerting."
    exit 0
  fi
  alert inject "bulletin-sync:refresh-fail" 60 \
    "🚨 Bulletin bridge: browser fetch passed the wall but prod-side refresh_bulletin exited ${REFRESH_RC}. Ingest is broken (parser/DB, not Akamai). Tail: $(echo "$REFRESH_OUT" | tail -5 | tr '\n' ' ')"
  exit 3
fi

# Pending sources that all failed = a real parse/load break -- EXCEPT during a cutover, when
# the prod DB is transiently constraint-less and every source fails on MultipleObjectsReturned.
if echo "$REFRESH_OUT" | grep -q "No bulletins were successfully ingested."; then
  if cutover_in_flight; then
    log "no bulletins ingested, but a cutover armed mid-run — the prod DB is mid-resync. Transient, not alerting."
    exit 0
  fi
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
