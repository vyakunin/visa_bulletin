#!/usr/bin/env bash
# Weekly ad-surface screenshot sweep — capture, then hand the images to an agent.
#
# The capture alone is worthless: a screenshot nobody looks at catches nothing.
# So this wrapper does the deterministic half (capture + structural probes) and
# then INJECTS a prompt into the visa_bulletin relay so a real agent turn opens
# the images and judges them. Same pattern as daily_checkup (see
# ~/.claude/rules/no_adhoc_claude_subprocess.md — inject into the existing relay,
# never spawn `claude -p`).
#
# Scheduled by ad_surface_screenshots.timer (Mondays 09:15 Berlin).
# Manual run:  bash scripts/run_ad_screenshot_sweep.sh
# Exit 0 = swept + injected; non-zero = capture failed (and we say so in chat).
set -uo pipefail

REPO="$HOME/cursor_projects/visa_bulletin"
NOTIFY="$HOME/cursor_projects/agent_infra/scripts/notify_chat.py"
LAUNCH_CHROME="$HOME/cursor_projects/agent_infra/scripts/launch_chrome_cdp.sh"
OUT_DIR="$HOME/.cache/vb_ad_screenshots/$(date +%F)"

cd "$REPO" || exit 1

# The sweep needs the headed debug Chrome: a real profile is what makes Google
# serve ads, and headless is fingerprint-walled (browser.md). Probe the PORT, not
# pgrep -f (which self-matches — script_development.md).
if ! ss -ltn | grep -q "127.0.0.1:9222"; then
  echo "[ad-sweep] debug Chrome not on :9222 — starting it"
  bash "$LAUNCH_CHROME" >/dev/null 2>&1
  sleep 6
fi
if ! ss -ltn | grep -q "127.0.0.1:9222"; then
  python3 "$NOTIFY" --project visa_bulletin --mode passive --no-echo \
    "⚠️ Weekly ad-surface sweep SKIPPED — debug Chrome never came up on :9222, so no screenshots were taken. Nothing was checked this week." \
    >/dev/null 2>&1
  exit 1
fi

echo "[ad-sweep] $(date -u +%FT%TZ) capturing..."
CAP_LOG=$(mktemp)
uv run scripts/ad_surface_screenshots.py --surfaces 5 --devices desktop,mobile --keep 4 \
  >"$CAP_LOG" 2>&1
RC=$?
tail -30 "$CAP_LOG"

if [ "$RC" -ne 0 ]; then
  # Loud failure: a silent skip is indistinguishable from "all clean", which is
  # the exact false all-clear this sweep exists to prevent.
  SUMMARY=$(tail -6 "$CAP_LOG" | tr '\n' ' ' | cut -c1-400)
  python3 "$NOTIFY" --project visa_bulletin --mode passive --no-echo \
    "⚠️ Weekly ad-surface sweep FAILED (rc=$RC) — no inspection happened this week. Tail: $SUMMARY" \
    >/dev/null 2>&1
  rm -f "$CAP_LOG"
  exit "$RC"
fi
rm -f "$CAP_LOG"

read -r -d '' PROMPT <<EOF
[SCHEDULED — weekly ad-surface visual sweep] Screenshots of the top 5 ad-bearing
surfaces (desktop 1440 + mobile 390, ad stack forced on via the /cdn-cgi/trace
geo override) are in ${OUT_DIR} with manifest.json.

Do the inspection — the capture is done, the judgement is not:
1. Read EVERY *.jpg (Read renders them). Look for product/logical issues AND
   visual appearance: empty/oversized boxes, overlapping or clipped text, ads
   colliding with content, broken/loading-forever widgets, stale dates, layout
   that breaks at 390px.
2. Cross-check manifest.json: overflow_px must be 0 (regression guard for the
   2026-07 sitewide scrollbar); slots_reserved_empty > 0 = a visible hole; CLS
   > 0.1 fails Google's threshold.
3. Two known artifacts — do NOT report either as a bug: (a) full-page shots
   freeze position:fixed anchor ads mid-page (compare the __viewport.jpg);
   (b) ads are served to a German IP, so ad CONTENT is German and FILL RATES are
   not representative — judge layout, not fill.
4. Report findings to Vladimir here. File a Notion ticket (Project=visa_bulletin)
   for anything real; if it is all clean, say so in one line.
EOF

python3 "$NOTIFY" --project visa_bulletin --mode inject --echo \
  --throttle-key ad_sweep_weekly --cooldown-min 60 "$PROMPT" >/dev/null 2>&1
echo "[ad-sweep] injected inspect prompt for ${OUT_DIR}"
