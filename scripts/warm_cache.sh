#!/bin/bash
#
# warm_cache.sh — post-deploy cache warmer for the top cacheable prod pages.
#
# WHY: a code deploy recreates `vb_web`, which clears Django's local-memory cache,
# and the post-deploy `redis-cli -n 1 FLUSHDB` empties the shared `@cache_page`
# Redis store. The next COLD user hit on a heavy dashboard then pays the full
# 2-3s render. This script curls the top ~20 high-traffic *cacheable* GET pages
# right after a deploy so Django re-populates its `@cache_page` entries in Redis;
# once the origin is warm, Cloudflare re-caches the HTML at the edge and real
# users never feel the cold path.
#
# It requests with `Cache-Control: no-cache` so the request reaches the origin
# (warming Django's Redis under the real path key) instead of being served from
# a stale CF edge copy. It does NOT add a cache-busting query param — that would
# warm a different `@cache_page` key than real visitors hit.
#
# Only genuinely cacheable landing/dashboard/content pages are warmed. Faceted
# `/salaries/?employer=...` query URLs are deliberately EXCLUDED — they are
# per-query, challenge-gated (cf-cache DYNAMIC), and not worth pre-warming.
#
# WHEN: run right after a prod code deploy + Redis flush (see the deploy flow in
# .claude/rules/deployment.md, next to the `redis-cli -n 1 FLUSHDB` step). Safe to
# run any time — these are plain read-only GETs.
#
# Usage:
#   ./scripts/warm_cache.sh                      # warm https://visa-bulletin.us
#   ./scripts/warm_cache.sh --base https://staging.visa-bulletin.us
#   BASE=https://staging.visa-bulletin.us ./scripts/warm_cache.sh
#   PRED_MONTH=2026-8 ./scripts/warm_cache.sh    # override current predictions month
#
# Env overrides:
#   BASE        base URL to warm (default https://visa-bulletin.us)
#   PRED_MONTH  current predictions month "YYYY-M" (default: derived from `date`)
#
# Output: per-URL HTTP status + total time, then a summary line.
# Exit code: 0 if every URL returned 200; 1 if any URL was non-200 (so a broken
# deploy is visible), though warming itself is best-effort.
#
set -uo pipefail

BASE="${BASE:-https://visa-bulletin.us}"
# Default predictions month = current year-month (no zero-pad on month, matching
# the consolidated /predictions/<YYYY-M>/ URL scheme).
PRED_MONTH="${PRED_MONTH:-$(date -u '+%Y-%-m')}"

for arg in "$@"; do
  case "$arg" in
    --base) shift; BASE="${1:?--base needs a URL}" ;;
    --base=*) BASE="${arg#--base=}" ;;
    --help|-h)
      sed -n '2,45p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    https://*|http://*) BASE="$arg" ;;
    *) echo "Unknown arg: $arg (use --base URL, --help)"; exit 2 ;;
  esac
done
BASE="${BASE%/}"  # strip trailing slash

# Top ~20 high-traffic cacheable GET pages. Derived from scripts/staging_prod_diff.sh
# + the sitemap. Keep this a landing/dashboard/content set — NO faceted query URLs.
URLS=(
  "/"                                             # homepage
  "/predictions/"                                 # predictions index
  "/predictions/${PRED_MONTH}/"                   # current EB predictions (consolidated scheme)
  "/predictions/family_sponsored/${PRED_MONTH}/"  # current FS predictions
  "/salaries/"                                     # salary DB landing (no query)
  "/employers/"                                    # employer directory landing
  "/job-titles/"                                   # job-title directory landing
  "/employment-based/all/"                         # EB dashboard (all countries)
  "/employment-based/india/"                       # top per-country dashboard
  "/employment-based/china/"                       # top per-country dashboard
  "/family-sponsored/india/"                       # top FS per-country dashboard
  "/family-sponsored/china/"                        # top FS per-country dashboard
  "/priority-date/eb2/india/"                      # high-intent priority-date hub
  "/priority-date/eb3/india/"                      # high-intent priority-date hub
  "/analysis/how-my-prediction-model-works/"       # methodology post
  "/analysis/visa-bulletin-analysis-july-2026/"    # latest monthly analysis post
  "/faq/"                                          # FAQ
  "/when-is-the-next-visa-bulletin/"               # high-intent evergreen
  "/about/"                                        # about
  "/contact/"                                      # contact
)

echo "Warming ${#URLS[@]} URLs on ${BASE} (predictions month ${PRED_MONTH})"
printf '%-48s %6s %9s\n' "URL" "status" "time(s)"

fail=0
for u in "${URLS[@]}"; do
  # -sS: quiet but show errors; no-cache header so the request reaches the origin
  # and warms Django's @cache_page Redis entry (not a stale CF edge copy).
  read -r code t <<<"$(curl -sS -o /dev/null -w '%{http_code} %{time_total}' \
    --max-time 30 -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' \
    "${BASE}${u}" 2>/dev/null || echo 'ERR -')"
  printf '%-48s %6s %9s\n' "$u" "$code" "$t"
  [ "$code" = "200" ] || fail=$((fail + 1))
done

if [ "$fail" -eq 0 ]; then
  echo "OK: all ${#URLS[@]} URLs returned 200 — cache warmed."
else
  echo "WARN: ${fail}/${#URLS[@]} URL(s) were non-200 — inspect above (warming is best-effort)."
fi
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
