#!/usr/bin/env bash
# Adaptive nginx bot rate-limiting: switch between normal and strict configs
# based on CPU steal (proxy for AWS Lightsail burst-credit depletion).
#
# - normal (default): 7r/m per-bot, 15r/m shared
# - strict (high steal): 2r/m per-bot, 2r/m shared
#
# Installed to /usr/local/bin/ and invoked every 60s by a systemd timer.
#
# Testing:
#   STEAL_OVERRIDE=60 DRY_RUN=1 ./nginx_bot_adaptive.sh  # simulate strict trigger
#   ./nginx_bot_adaptive.sh --self-test                  # run built-in tests
#
# Env overrides:
#   STRICT_ABOVE   — %st at or above this → strict (default 50)
#   NORMAL_BELOW   — %st at or below this → normal (default 30)
#                    Gap between them = hysteresis (no action in-between).
#   MODE_FILE      — path to mode state file (default /var/run/nginx_bot_mode)
#   LOG_FILE       — path to log file      (default /var/log/nginx_bot_adaptive.log)
#   ACTIVE_CONF    — deployed nginx conf   (default /etc/nginx/conf.d/gptbot-rate-limit.conf)
#   NORMAL_CONF    — source file, normal   (default /opt/visa_bulletin/deployment/nginx/gptbot-rate-limit.conf)
#   STRICT_CONF    — source file, strict   (default /opt/visa_bulletin/deployment/nginx/gptbot-rate-limit-strict.conf)
#   STEAL_OVERRIDE — skip /proc/stat, use this value (for tests)
#   DRY_RUN        — "1" to skip nginx reload and file copy (for tests)

set -euo pipefail

: "${STRICT_ABOVE:=50}"
: "${NORMAL_BELOW:=30}"
: "${MODE_FILE:=/var/run/nginx_bot_mode}"
: "${LOG_FILE:=/var/log/nginx_bot_adaptive.log}"
: "${ACTIVE_CONF:=/etc/nginx/conf.d/gptbot-rate-limit.conf}"
: "${NORMAL_CONF:=/opt/visa_bulletin/deployment/nginx/gptbot-rate-limit.conf}"
: "${STRICT_CONF:=/opt/visa_bulletin/deployment/nginx/gptbot-rate-limit-strict.conf}"
: "${DRY_RUN:=0}"

log() {
    local msg="$(date -u +%FT%TZ) $*"
    if [ "$DRY_RUN" = "1" ]; then
        echo "$msg"
    else
        echo "$msg" | tee -a "$LOG_FILE" >&2
    fi
}

# Read CPU steal % from /proc/stat via two 1-second samples.
# Returns integer (0-100).
read_steal_pct() {
    if [ -n "${STEAL_OVERRIDE:-}" ]; then
        echo "$STEAL_OVERRIDE"
        return 0
    fi
    # /proc/stat fields: user nice system idle iowait irq softirq steal guest guest_nice
    local s1 s2
    s1=$(head -n1 /proc/stat)
    sleep 1
    s2=$(head -n1 /proc/stat)
    # shellcheck disable=SC2206
    local a1=($s1) a2=($s2)
    # a[0] is "cpu"; indices 1..10 are the counters
    local total1=0 total2=0
    for i in 1 2 3 4 5 6 7 8 9 10; do
        total1=$((total1 + ${a1[$i]:-0}))
        total2=$((total2 + ${a2[$i]:-0}))
    done
    local dtotal=$((total2 - total1))
    local dsteal=$((${a2[8]:-0} - ${a1[8]:-0}))
    if [ "$dtotal" -le 0 ]; then
        echo "0"
    else
        echo $(( (dsteal * 100 + dtotal / 2) / dtotal ))
    fi
}

# Pure decision function — no I/O. Takes (steal, current_mode) and echoes
# the target mode: "normal", "strict", or "unchanged".
decide_mode() {
    local steal="$1"
    local current="$2"
    if [ "$steal" -ge "$STRICT_ABOVE" ]; then
        if [ "$current" = "strict" ]; then
            echo "unchanged"
        else
            echo "strict"
        fi
    elif [ "$steal" -le "$NORMAL_BELOW" ]; then
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
    local steal current target
    steal=$(read_steal_pct)
    current=$(get_current_mode)
    target=$(decide_mode "$steal" "$current")

    if [ "$target" = "unchanged" ]; then
        # Quiet — don't spam the log every minute.
        return 0
    fi

    if apply_mode "$target"; then
        log "Switched $current -> $target (steal=${steal}%)"
    else
        log "FAILED to switch $current -> $target (steal=${steal}%)"
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
    STRICT_ABOVE=50 NORMAL_BELOW=30

    assert_eq "$(decide_mode 80 normal)" strict     "80%+normal->strict"
    assert_eq "$(decide_mode 50 normal)" strict     "50%+normal->strict (boundary inclusive)"
    assert_eq "$(decide_mode 49 normal)" unchanged  "49%+normal->unchanged (hysteresis)"
    assert_eq "$(decide_mode 31 normal)" unchanged  "31%+normal->unchanged (hysteresis)"
    assert_eq "$(decide_mode 30 normal)" unchanged  "30%+normal->unchanged (already normal)"
    assert_eq "$(decide_mode 10 normal)" unchanged  "10%+normal->unchanged (already normal)"

    assert_eq "$(decide_mode 80 strict)" unchanged  "80%+strict->unchanged (already strict)"
    assert_eq "$(decide_mode 50 strict)" unchanged  "50%+strict->unchanged (boundary, already strict)"
    assert_eq "$(decide_mode 49 strict)" unchanged  "49%+strict->unchanged (hysteresis)"
    assert_eq "$(decide_mode 31 strict)" unchanged  "31%+strict->unchanged (hysteresis)"
    assert_eq "$(decide_mode 30 strict)" normal     "30%+strict->normal (boundary inclusive)"
    assert_eq "$(decide_mode 10 strict)" normal     "10%+strict->normal"
    assert_eq "$(decide_mode 0  strict)" normal     "0%+strict->normal"

    echo
    echo "== hysteresis does not flap near boundaries =="
    # Oscillate steal in the 31..49 band while in each mode — should never flip.
    local mode
    for mode in normal strict; do
        for st in 31 40 45 49 32 48 35; do
            assert_eq "$(decide_mode $st $mode)" unchanged "oscillate st=$st mode=$mode"
        done
    done

    echo
    echo "== read_steal_pct honors STEAL_OVERRIDE =="
    assert_eq "$(STEAL_OVERRIDE=42 read_steal_pct)" "42" "STEAL_OVERRIDE=42"
    assert_eq "$(STEAL_OVERRIDE=0  read_steal_pct)" "0"  "STEAL_OVERRIDE=0"

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
