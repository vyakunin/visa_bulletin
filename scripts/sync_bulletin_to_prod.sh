#!/usr/bin/env bash
# Minipc -> prod bulletin ingest bridge (Akamai wall bypass).
#
# travel.state.gov is behind Akamai; the prod box (vb_web, no browser) cannot fetch
# it. The minipc debug Chrome can. This script runs on the MINIPC:
#   1. Browser-fetch the bulletin index + current/next month pages into a local cache
#      (scripts/fetch_bulletin_via_browser.py).
#   2. Stream the cache into the prod vb_web container (tar over ssh; no scp of repo).
#   3. Run the existing scripts.cron.refresh_bulletin in vb_web with
#      BULLETIN_HTML_CACHE_DIR pointed at the streamed cache, so discover/download read
#      the browser-fetched HTML instead of hitting Akamai. Parse/load/predict run
#      prod-side, unchanged, and dedup makes already-ingested months a no-op.
#
# Idempotent: safe to run repeatedly (dedup by DataSource). Intended to run a few
# times/day on the minipc during the mid-month publish window (State Dept publishes
# the next month ~8th-15th). Requires: debug Chrome on :9222, ssh alias `homeserver`.
#
# Usage: scripts/sync_bulletin_to_prod.sh [--months YYYY-MM,YYYY-MM]
# Exit: 0 ok; 2 index fetch failed (wall not passed / CDP down) -> alertable.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="/tmp/bulletin_html_cache"
CONTAINER_CACHE="/tmp/vb_bulletin_cache"
MONTHS_ARG=()
[ "${1:-}" = "--months" ] && MONTHS_ARG=(--months "$2")

echo "[sync_bulletin] $(date -u +%FT%TZ) fetching via debug Chrome..."
rm -rf "$CACHE"
SUMMARY="$(cd "$REPO" && uv run --with playwright --with python-dateutil \
  python scripts/fetch_bulletin_via_browser.py --cache-dir "$CACHE" "${MONTHS_ARG[@]}")"
echo "[sync_bulletin] fetch summary: $SUMMARY"

if ! echo "$SUMMARY" | grep -q '"index_ok": true'; then
  echo "[sync_bulletin] ERROR: index fetch failed (Akamai wall not passed / CDP down)" >&2
  exit 2
fi

echo "[sync_bulletin] streaming cache -> vb_web:$CONTAINER_CACHE"
ssh homeserver "docker exec -i vb_web sh -c 'rm -rf $CONTAINER_CACHE && mkdir -p $CONTAINER_CACHE && tar -C $CONTAINER_CACHE -xf -'" < <(tar -C "$CACHE" -cf - .)

echo "[sync_bulletin] running refresh_bulletin (cache-backed) in vb_web..."
ssh homeserver "docker exec -e BULLETIN_HTML_CACHE_DIR=$CONTAINER_CACHE -w /app vb_web \
  python3 -m scripts.cron.refresh_bulletin"

echo "[sync_bulletin] cleaning up container cache"
ssh homeserver "docker exec vb_web rm -rf $CONTAINER_CACHE" || true
echo "[sync_bulletin] done $(date -u +%FT%TZ)"
