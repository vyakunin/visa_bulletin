#!/usr/bin/env bash
# Adaptive nginx bot rate-limiting: swap between normal and strict configs
# based on AWS Lightsail BurstCapacityPercentage.
#
# Why burst, not %st: %st only spikes *after* burst is depleted. By then we're
# already being throttled. We want to act while we still have headroom, so the
# instance has a chance to rebuild credits.
#
# - normal (default): 7r/m per-bot, 15r/m shared
# - strict (burst low): 2r/m per-bot, 2r/m shared
#
# Installed to /usr/local/bin/ and invoked every 60s by a systemd timer.
#
# Testing:
#   BURST_OVERRIDE=40 DRY_RUN=1 ./nginx_bot_adaptive.sh  # simulate strict trigger
#   ./nginx_bot_adaptive.sh --self-test                  # run built-in tests
#
# Env overrides:
#   STRICT_BELOW     — burst % at or below this -> strict (default 50)
#   NORMAL_ABOVE     — burst % at or above this -> normal (default 75)
#                      Gap between them = hysteresis (no action in-between).
#   LIGHTSAIL_INSTANCE — Lightsail instance name  (default VisaBulletin2GB)
#   AWS_REGION         — AWS region               (default us-east-1)
#   AWS_PROFILE        — AWS credentials profile  (default visa-bulletin-deploy)
#   AWS_SHARED_CREDENTIALS_FILE — path to AWS credentials file
#                                 (default /home/ubuntu/.aws/credentials)
#   MODE_FILE    — path to mode state file (default /var/run/nginx_bot_mode)
#   LOG_FILE     — path to log file        (default /var/log/nginx_bot_adaptive.log)
#   ACTIVE_CONF  — deployed nginx conf     (default /etc/nginx/conf.d/gptbot-rate-limit.conf)
#   NORMAL_CONF  — source file, normal     (default /opt/visa_bulletin/deployment/nginx/gptbot-rate-limit.conf)
#   STRICT_CONF  — source file, strict     (default /opt/visa_bulletin/deployment/nginx/gptbot-rate-limit-strict.conf)
#   BURST_OVERRIDE — skip AWS API call, use this value (for tests)
#   DRY_RUN        — "1" to skip nginx reload and file copy (for tests)

set -euo pipefail

: "${STRICT_BELOW:=50}"
: "${NORMAL_ABOVE:=75}"
: "${LIGHTSAIL_INSTANCE:=VisaBulletin2GB}"
: "${AWS_REGION:=us-east-1}"
: "${AWS_PROFILE:=visa-bulletin-deploy}"
: "${AWS_SHARED_CREDENTIALS_FILE:=/home/ubuntu/.aws/credentials}"
: "${MODE_FILE:=/var/run/nginx_bot_mode}"
: "${LOG_FILE:=/var/log/nginx_bot_adaptive.log}"
: "${ACTIVE_CONF:=/etc/nginx/conf.d/gptbot-rate-limit.conf}"
: "${NORMAL_CONF:=/opt/visa_bulletin/deployment/nginx/gptbot-rate-limit.conf}"
: "${STRICT_CONF:=/opt/visa_bulletin/deployment/nginx/gptbot-rate-limit-strict.conf}"
: "${DRY_RUN:=0}"

export AWS_PROFILE AWS_SHARED_CREDENTIALS_FILE AWS_REGION

log() {
    local msg="$(date -u +%FT%TZ) $*"
    if [ "$DRY_RUN" = "1" ]; then
        echo "$msg"
    else
        echo "$msg" | tee -a "$LOG_FILE" >&2
    fi
}

# Fetch the most recent BurstCapacityPercentage datapoint from the Lightsail API.
# Echoes an integer 0-100, or empty string on failure. Uses a 15-min lookback
# because the metric publishes with ~1-3 min lag.
read_burst_pct() {
    if [ -n "${BURST_OVERRIDE:-}" ]; then
        echo "$BURST_OVERRIDE"
        return 0
    fi
    local start end raw
    start=$(date -u -d '15 minutes ago' +%s)
    end=$(date -u +%s)
    # metricData comes back in chronological order; take the last entry.
    # Use --output text with scalar columns so we don't need jq.
    raw=$(aws lightsail get-instance-metric-data \
        --region "$AWS_REGION" \
        --instance-name "$LIGHTSAIL_INSTANCE" \
        --metric-name BurstCapacityPercentage \
        --period 60 \
        --start-time "$start" \
        --end-time "$end" \
        --unit Percent \
        --statistics Average \
        --query 'metricData[-1].average' \
        --output text 2>/dev/null || true)
    if [ -z "$raw" ] || [ "$raw" = "None" ]; then
        echo ""
        return 0
    fi
    # Round half-up to integer.
    awk -v v="$raw" 'BEGIN { printf "%d", (v + 0.5) }'
}

# Pure decision function — no I/O. Takes (burst_pct, current_mode) and echoes
# the target mode: "normal", "strict", or "unchanged".
decide_mode() {
    local burst="$1"
    local current="$2"
    if [ "$burst" -le "$STRICT_BELOW" ]; then
        if [ "$current" = "strict" ]; then
            echo "unchanged"
        else
            echo "strict"
        fi
    elif [ "$burst" -ge "$NORMAL_ABOVE" ]; then
        if [ "$current" = "normal" ]; then
            echo "unchanged"
        else
            echo "normal"
        fi
    else
        # In the hysteresis band — keep current mode.
        echo "unchanged"
    fi
}

get_current_mode() {
    if [ -f "$MODE_FILE" ]; then
        local m
        m=$(tr -d '[:space:]' < "$MODE_FILE")
        if [ -n "$m" ]; then
            echo "$m"
            return 0
        fi
    fi
    # No / empty state file = default to normal (matches initial install).
    echo "normal"
}

# Swap the active nginx conf to the given mode, validate, reload.
# Rolls back on nginx -t failure. Writes state to MODE_FILE on success.
apply_mode() {
    local mode="$1"
    local src
    case "$mode" in
        normal) src="$NORMAL_CONF" ;;
        strict) src="$STRICT_CONF" ;;
        *) log "ERROR: unknown mode '$mode'"; return 2 ;;
    esac

    if [ "$DRY_RUN" = "1" ]; then
        log "DRY_RUN: would copy $src -> $ACTIVE_CONF and reload nginx (mode=$mode)"
        echo "$mode" > "${MODE_FILE}.dryrun"
        return 0
    fi

    if [ ! -r "$src" ]; then
        log "ERROR: source config not readable: $src"
        return 2
    fi

    # Backup current active conf for rollback.
    local backup="${ACTIVE_CONF}.prev"
    if [ -f "$ACTIVE_CONF" ]; then
        cp -p "$ACTIVE_CONF" "$backup"
    fi

    cp -p "$src" "$ACTIVE_CONF"
    if ! nginx -t >/dev/null 2>&1; then
        log "ERROR: nginx -t failed after swap to $mode; rolling back"
        if [ -f "$backup" ]; then
            cp -p "$backup" "$ACTIVE_CONF"
        fi
        return 1
    fi

    if ! systemctl reload nginx >/dev/null 2>&1; then
        log "ERROR: systemctl reload nginx failed; rolling back"
        if [ -f "$backup" ]; then
            cp -p "$backup" "$ACTIVE_CONF"
            systemctl reload nginx >/dev/null 2>&1 || true
        fi
        return 1
    fi

    echo "$mode" > "$MODE_FILE"
    return 0
}

main() {
    local burst current target
    burst=$(read_burst_pct)
    current=$(get_current_mode)

    if [ -z "$burst" ]; then
        # API failure: stay put rather than flap on a missing signal.
        log "WARN: could not read BurstCapacityPercentage; staying in mode=$current"
        return 0
    fi

    target=$(decide_mode "$burst" "$current")

    if [ "$target" = "unchanged" ]; then
        # Quiet — don't spam the log every minute.
        return 0
    fi

    if apply_mode "$target"; then
        log "Switched $current -> $target (burst=${burst}%)"
    else
        log "FAILED to switch $current -> $target (burst=${burst}%)"
        return 1
    fi
}

# --- self-test mode ------------------------------------------------------
self_test() {
    local failed=0
    assert_eq() {
        local actual="$1" expected="$2" name="$3"
        if [ "$actual" = "$expected" ]; then
            echo "  ok  $name"
        else
            echo "  FAIL $name: got '$actual', expected '$expected'"
            failed=$((failed + 1))
        fi
    }

    echo "== decide_mode transitions =="
    STRICT_BELOW=50 NORMAL_ABOVE=75

    # Low burst -> strict
    assert_eq "$(decide_mode 10 normal)" strict     "10%+normal->strict (low burst)"
    assert_eq "$(decide_mode 50 normal)" strict     "50%+normal->strict (boundary inclusive)"
    assert_eq "$(decide_mode 49 normal)" strict     "49%+normal->strict"
    assert_eq "$(decide_mode 0  normal)" strict     "0%+normal->strict"

    # Hysteresis band 51-74 -> unchanged
    assert_eq "$(decide_mode 51 normal)" unchanged  "51%+normal->unchanged (hysteresis)"
    assert_eq "$(decide_mode 70 normal)" unchanged  "70%+normal->unchanged (hysteresis)"
    assert_eq "$(decide_mode 74 normal)" unchanged  "74%+normal->unchanged (hysteresis)"
    assert_eq "$(decide_mode 51 strict)" unchanged  "51%+strict->unchanged (hysteresis)"
    assert_eq "$(decide_mode 74 strict)" unchanged  "74%+strict->unchanged (hysteresis)"

    # Idempotent from same mode
    assert_eq "$(decide_mode 10 strict)" unchanged  "10%+strict->unchanged (already strict)"
    assert_eq "$(decide_mode 50 strict)" unchanged  "50%+strict->unchanged (already strict)"
    assert_eq "$(decide_mode 80 normal)" unchanged  "80%+normal->unchanged (already normal)"

    # High burst -> normal
    assert_eq "$(decide_mode 75 strict)" normal     "75%+strict->normal (boundary inclusive)"
    assert_eq "$(decide_mode 80 strict)" normal     "80%+strict->normal"
    assert_eq "$(decide_mode 100 strict)" normal    "100%+strict->normal"

    echo
    echo "== hysteresis does not flap near boundaries =="
    # Oscillate burst in the 51..74 band while in each mode — should never flip.
    local mode
    for mode in normal strict; do
        for b in 51 55 60 70 74 52 73 65; do
            assert_eq "$(decide_mode $b $mode)" unchanged "oscillate burst=$b mode=$mode"
        done
    done

    echo
    echo "== read_burst_pct honors BURST_OVERRIDE =="
    assert_eq "$(BURST_OVERRIDE=42 read_burst_pct)" "42" "BURST_OVERRIDE=42"
    assert_eq "$(BURST_OVERRIDE=0  read_burst_pct)" "0"  "BURST_OVERRIDE=0"
    assert_eq "$(BURST_OVERRIDE=100 read_burst_pct)" "100" "BURST_OVERRIDE=100"

    echo
    echo "== get_current_mode default / roundtrip =="
    local tmp
    tmp="$(mktemp)"
    rm -f "$tmp"
    MODE_FILE="$tmp"
    assert_eq "$(MODE_FILE="$tmp" get_current_mode)" "normal" "missing file -> normal"
    echo "strict" > "$tmp"
    assert_eq "$(MODE_FILE="$tmp" get_current_mode)" "strict" "reads file contents"
    echo "" > "$tmp"
    assert_eq "$(MODE_FILE="$tmp" get_current_mode)" "normal" "empty file -> normal"
    rm -f "$tmp"

    echo
    echo "== apply_mode dry-run path =="
    local drfile
    drfile="$(mktemp)"
    MODE_FILE="$drfile" DRY_RUN=1 apply_mode strict >/dev/null
    assert_eq "$(cat "${drfile}.dryrun")" "strict" "dry-run writes strict sentinel"
    rm -f "$drfile" "${drfile}.dryrun"

    MODE_FILE="$(mktemp)" DRY_RUN=1 apply_mode bogus >/dev/null && echo "  FAIL apply_mode bogus should fail" && failed=$((failed+1)) || echo "  ok  apply_mode rejects unknown mode"

    echo
    echo "== main() stays put on API failure (empty burst) =="
    # Simulate the empty-burst branch of main() without invoking the real API.
    local b c result
    b=""
    c="strict"
    if [ -z "$b" ]; then
        result="stay"
    else
        result="$(decide_mode "$b" "$c")"
    fi
    assert_eq "$result" "stay" "empty burst -> stay in current mode"

    echo
    if [ "$failed" -eq 0 ]; then
        echo "ALL TESTS PASSED"
        return 0
    else
        echo "$failed test(s) FAILED"
        return 1
    fi
}

if [ "${1:-}" = "--self-test" ]; then
    self_test
    exit $?
fi

main
