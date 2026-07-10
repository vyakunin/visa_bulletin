#!/bin/bash
#
# staging_page_audit.sh — per-URL SEO/marker audit of the staging stack.
#
# Curls a representative set of staging URLs (via the staging Host) and reports,
# per URL: HTTP status, robots-meta state (index/noindex/none), whether the page
# is an employer/job-title profile, and whether a Plotly chart is present. This is
# the committed form of the ad-hoc check that ran 3x across two sessions (Jul 1-4):
# `curl -H 'Host: staging.visa-bulletin.us' <url>` then grepping the rendered HTML
# for robots noindex, an employer/job-title profile marker, and Plotly inclusion.
#
# Profile detection uses the rendered JSON-LD schema type that actually
# distinguishes these pages: an employer profile carries `"@type": "AggregateRating"`,
# a job-title profile carries `"@type": "Occupation"` (the literal `ev-profile`
# string from the originating ticket was a paraphrase — no such class exists in the
# rendered HTML; a literal `ev-profile` grep is kept as a forward-compat fallback).
# The `profile` column reports: emp / jobtitle / no.
#
# Sibling of staging_prod_diff.sh (same STAGING_BASE env pattern, same /tmp
# artifact convention) but a different job: that script diffs staging<->prod for
# parity; this one audits staging pages standalone for SEO/render markers.
#
# WHEN: after a staging deploy that touches robots meta, page indexability, the
# employer/job-title profile templates, or chart rendering — to confirm each key
# page type is indexable-as-intended, is (or isn't) an ev-profile, and renders
# its Plotly chart.
#
# Usage:
#   ./scripts/staging_page_audit.sh                 # audit the default URL set
#   ./scripts/staging_page_audit.sh --show          # + dump the matched marker lines per URL
#   ./scripts/staging_page_audit.sh --url /employer/google-llc/ --url /salaries/   # audit only these
#   AUDIT_URLS="/ /salaries/" ./scripts/staging_page_audit.sh                       # override the set via env
#
# Env overrides:
#   STAGING_BASE  base URL to curl (default https://staging.visa-bulletin.us)
#   HOST_HEADER   send an explicit `Host:` header (default unset). Set this to hit
#                 the origin directly and bypass Cloudflare, e.g.
#                 STAGING_BASE=http://127.0.0.1:8080 HOST_HEADER=staging.visa-bulletin.us
#   AUDIT_URLS    whitespace-separated URL path list, overrides the default set
#   PRED_MONTH    predictions month "YYYY-M" (default: derived from `date`), used
#                 by the default predictions URL
#
# Output: fetched HTML saved to /tmp/vb_page_audit/<slug>.html for inspection.
# Exit code: 0 if every URL returned HTTP 200; 1 if any URL was non-200 or unfetchable.
#
set -euo pipefail

STAGING_BASE="${STAGING_BASE:-https://staging.visa-bulletin.us}"
HOST_HEADER="${HOST_HEADER:-}"
# Default predictions month = current year-month (no zero-pad, matching URL scheme).
PRED_MONTH="${PRED_MONTH:-$(date -u '+%Y-%-m')}"

SHOW=0
CLI_URLS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --show) SHOW=1 ;;
    --url) shift; [ $# -gt 0 ] || { echo "--url needs a path"; exit 2; }; CLI_URLS+=("$1") ;;
    --help|-h)
      sed -n '2,44p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    /*) CLI_URLS+=("$1") ;;
    *) echo "Unknown arg: $1 (use --show, --url /path, --help, or a bare /path)"; exit 2 ;;
  esac
  shift
done

# URL set precedence: CLI flags > AUDIT_URLS env > built-in representative set.
# Representative set: homepage, an employer profile, a job-title profile, a
# predictions month page, and the salaries list.
if [ "${#CLI_URLS[@]}" -gt 0 ]; then
  URLS=("${CLI_URLS[@]}")
elif [ -n "${AUDIT_URLS:-}" ]; then
  # shellcheck disable=SC2206  # deliberate word-split of the env list
  URLS=(${AUDIT_URLS})
else
  URLS=(
    "/"
    "/employer/google-llc/"
    "/job-title/software-engineer/"
    "/predictions/${PRED_MONTH}/"
    "/salaries/"
  )
fi

mkdir -p /tmp/vb_page_audit && rm -f /tmp/vb_page_audit/*

slugify() { local s; s=$(echo "$1" | tr '/?&=' '____' | sed 's/^_*//; s/_*$//'); [ -z "$s" ] && s=root; echo "$s"; }

# curl the URL (following redirects) with an optional explicit Host header; capture the
# final body to $2 and echo the final HTTP status. -L so a consolidated-URL 301 (e.g. the
# predictions month-URL scheme) is audited on the page the user actually lands on.
fetch() {
  local url="$1" out="$2" code
  # Assign inside the subst, then overwrite on curl failure — never concatenate the
  # -w http_code with a fallback (that produced a "200000" artifact).
  if [ -n "$HOST_HEADER" ]; then
    code=$(curl -sL -H "Host: ${HOST_HEADER}" -o "$out" -w '%{http_code}' --max-time 30 "${STAGING_BASE}${url}") || code="000"
  else
    code=$(curl -sL -o "$out" -w '%{http_code}' --max-time 30 "${STAGING_BASE}${url}") || code="000"
  fi
  echo "$code"
}

# robots-meta state from an HTML file: noindex / index / none (no robots meta = indexable by default).
robots_state() {
  local f="$1" meta
  meta=$(grep -io '<meta[^>]*name=["'"'"']robots["'"'"'][^>]*>' "$f" | head -1 || true)
  if [ -z "$meta" ]; then echo "none"
  elif echo "$meta" | grep -qi 'noindex'; then echo "noindex"
  else echo "index"; fi
}

# profile type from an HTML file: emp / jobtitle / no, via the distinguishing rendered
# JSON-LD schema type (employer profile => AggregateRating, job-title profile => Occupation).
# A literal `ev-profile` class, if it ever reappears, is treated as a generic profile.
profile_type() {
  local f="$1"
  if grep -qi 'ev-profile' "$f"; then echo "yes"
  elif grep -q '"@type":[[:space:]]*"AggregateRating"' "$f"; then echo "emp"
  elif grep -q '"@type":[[:space:]]*"Occupation"' "$f"; then echo "jobtitle"
  else echo "no"; fi
}

any_fail=0
printf '%-46s %6s %-8s %-10s %-7s\n' "URL" "status" "robots" "profile" "plotly"
for u in "${URLS[@]}"; do
  slug=$(slugify "$u")
  f="/tmp/vb_page_audit/${slug}.html"
  status=$(fetch "$u" "$f")

  if [ "$status" = "200" ] && [ -s "$f" ]; then
    robots=$(robots_state "$f")
    profile=$(profile_type "$f")
    # Plotly chart present = a rendered chart div or Plotly.newPlot call, not just the
    # bundled lib <script> (so a chartless page reads "no" even if the lib is linked).
    if grep -qi 'plotly-graph-div\|Plotly\.newPlot' "$f"; then plotly="yes"; else plotly="no"; fi
  else
    robots="-"; profile="-"; plotly="-"
    any_fail=1
  fi

  printf '%-46s %6s %-8s %-10s %-7s\n' "$u" "$status" "$robots" "$profile" "$plotly"

  if [ "$SHOW" -eq 1 ] && [ "$status" = "200" ] && [ -s "$f" ]; then
    echo "  ----- markers: $u -----"
    grep -io '<meta[^>]*name=["'"'"']robots["'"'"'][^>]*>' "$f" | head -1 | sed 's/^/  robots: /' || true
    grep -o '"@type":[[:space:]]*"\(AggregateRating\|Occupation\)"' "$f" | sort -u | sed 's/^/  profile-schema: /' || true
    grep -io '[a-zA-Z0-9_.-]*plotly[a-zA-Z0-9_.-]*' "$f" | sort -u | head -3 | sed 's/^/  plotly: /' || true
    echo "  ----- end $u -----"
  fi
done

if [ "$any_fail" -eq 0 ]; then
  echo "OK: all URLs returned HTTP 200."
else
  echo "NON-200 present: at least one URL was not 200 (check the status column)."
fi
exit "$any_fail"
