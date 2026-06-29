#!/bin/bash
#
# staging_prod_diff.sh — staging<->prod parity diff-gate.
#
# Diffs a known set of top URLs between the staging and prod stacks and prints,
# per URL, the number of *filtered* diff lines (known-cosmetic noise removed) so
# you can read the real content delta before a promotion. This is the committed
# form of the inline loop documented in .claude/rules/deployment.md
# ("Diff staging vs prod HTML for top properties before graduation") and
# referenced by .claude/rules/branching.md + ~/.claude/rules/staging_prod_parity.md.
#
# WHEN: after staging is up on the new image, BEFORE `git merge --ff-only staging`
# on the prod branch. Treat it as the last gate. Inspect every URL with non-zero
# filtered difflines and classify it (see the table in deployment.md) — expected
# code/data deltas pass; an unexplained template/data diff blocks promotion.
#
# Usage:
#   ./scripts/staging_prod_diff.sh                 # summary table (filtered difflines per URL)
#   ./scripts/staging_prod_diff.sh --show          # also dump the filtered diff for URLs that differ
#   ./scripts/staging_prod_diff.sh --show /         # dump the filtered diff for one specific path
#   PROD_BASE=... STAGING_BASE=... ./scripts/staging_prod_diff.sh
#
# Env overrides:
#   PROD_BASE     (default https://visa-bulletin.us)
#   STAGING_BASE  (default https://staging.visa-bulletin.us)
#   PRED_MONTH    current predictions month, "YYYY-M" (default: derived from `date`)
#
# Output: artifacts saved to /tmp/vb_diff/{prod,stg}_<slug>.html for manual inspection.
# Exit code: 0 if every URL is byte-identical after filtering; 1 if any URL differs
# (so CI/automation can gate on it — but a human still classifies the diffs).
#
set -euo pipefail

PROD_BASE="${PROD_BASE:-https://visa-bulletin.us}"
STAGING_BASE="${STAGING_BASE:-https://staging.visa-bulletin.us}"
# Default predictions month = current year-month (no zero-pad on month, matching URL scheme).
PRED_MONTH="${PRED_MONTH:-$(date -u '+%Y-%-m')}"

SHOW=0
ONLY_PATH=""
for arg in "$@"; do
  case "$arg" in
    --show) SHOW=1 ;;
    --help|-h)
      sed -n '2,40p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    /*) ONLY_PATH="$arg"; SHOW=1 ;;
    *) echo "Unknown arg: $arg (use --show, --help, or a /path)"; exit 2 ;;
  esac
done

# Strip the staging hostname down to prod's BEFORE diffing — load-bearing. Without
# it every canonical_url / og:url / og:image / twitter:url / schema.org Dataset URL
# shows as a diff and drowns out real signal.
PROD_HOST="${PROD_BASE#*://}"
STG_HOST="${STAGING_BASE#*://}"

# URL set covering ~80% of risk surface (see deployment.md). Historical prediction
# months should be invariant once published — any diff there is a regression.
URLS=(
  "/"
  "/employment-based/india/"
  "/predictions/employment_based/${PRED_MONTH}/"
  "/predictions/family_sponsored/${PRED_MONTH}/"
  "/predictions/2024-1/"
  "/predictions/2020-1/"
  "/predictions/2005-1/"
  "/analysis/how-my-prediction-model-works/"
)

# Known-cosmetic noise to strip from the diff:
#  - data-cfemail / email-protection: Cloudflare email-obfuscation tokens rotate per request
#  - goatcounter / data-gc-event: analytics that may be merged to staging but not yet prod
#    (that IS the deploy you're about to do — those diffs are expected)
NOISE_RE='goatcounter|data-cfemail|cdn-cgi/l/email-protection|window\.goatcounter|data-gc-event'

mkdir -p /tmp/vb_diff && rm -f /tmp/vb_diff/*

slugify() { local s; s=$(echo "$1" | tr '/' '_' | sed 's/^_//; s/_$//'); [ -z "$s" ] && s=root; echo "$s"; }

any_diff=0
printf '%-52s %8s %8s %s\n' "URL" "prod(b)" "stg(b)" "difflines(filtered)"
for u in "${URLS[@]}"; do
  [ -n "$ONLY_PATH" ] && [ "$u" != "$ONLY_PATH" ] && continue
  slug=$(slugify "$u")
  prod_f="/tmp/vb_diff/prod_${slug}.html"
  stg_f="/tmp/vb_diff/stg_${slug}.html"
  curl -s "${PROD_BASE}${u}" > "$prod_f" || true
  # Rewrite staging host -> prod host so only real content diffs remain.
  curl -s "${STAGING_BASE}${u}" | sed "s|${STG_HOST}|${PROD_HOST}|g" > "$stg_f" || true
  filtered=$(diff <(grep -vE "$NOISE_RE" "$prod_f") <(grep -vE "$NOISE_RE" "$stg_f") || true)
  d=$(printf '%s' "$filtered" | grep -c '^' || true)
  [ -z "$filtered" ] && d=0
  ps=$(wc -c < "$prod_f" | tr -d ' ')
  ss=$(wc -c < "$stg_f" | tr -d ' ')
  printf '%-52s %8s %8s %s\n' "$u" "$ps" "$ss" "$d"
  if [ "$d" -gt 0 ]; then
    any_diff=1
    if [ "$SHOW" -eq 1 ]; then
      echo "----- filtered diff: $u (prod < / staging >) -----"
      printf '%s\n' "$filtered" | head -80
      echo "----- end $u -----"
    fi
  fi
done

if [ "$any_diff" -eq 0 ]; then
  echo "PARITY: all URLs byte-identical after filtering."
else
  echo "DIFFS PRESENT: inspect each non-zero URL and classify per deployment.md before promoting."
  echo "  (re-run with --show, or pass a single /path, to see the filtered diff)"
fi
exit "$any_diff"
