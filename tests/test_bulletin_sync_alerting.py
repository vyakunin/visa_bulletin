"""Guards on the bulletin bridge's alerting + its contract with the daily_checkup backstop.

`scripts/sync_bulletin_to_prod.sh` is the ONLY bulletin ingest path since the prod-side
hourly cron was retired 2026-07-16 (it 403'd on every run behind Akamai). Nothing else
watches bulletin ingest, so its alerting is load-bearing: if it goes quiet, a missed
bulletin is invisible until a user notices the site is a month stale.

Two layers, two blind spots, and this file pins the seam between them:

  * The bridge alerts in real time on failure streaks — but is structurally blind to
    "the cron never fired at all" (no run = no alert).
  * The daily_checkup MCP covers exactly that blind spot by reading the state files the
    bridge writes ($STATE_DIR/last_success, /fetch_fail_streak) and grading their AGE.

The seam is a filesystem path agreed in two files with no import between them. If either
side moves, the MCP reads nothing, reports `last_success: None`, silently falls back to
log mtime — and a bridge failing every single run still writes its log, so the digest
reads GREEN while ingest is dead. That is a silent, total loss of the backstop from a
one-line edit, and no functional test of either file alone would catch it.

What this CANNOT verify (only a live run can): that the alerts actually deliver, and
that the wall still falls. Verified by hand 2026-07-16 — failure streak fires the inject
at ALERT_AFTER, recovery fires the passive all-clear and resets the streak, and a real
run writes last_success.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SYNC = _REPO / "scripts/sync_bulletin_to_prod.sh"
_MCP = _REPO / "mcp/daily_checkup_server.py"


def _sync_src() -> str:
    return _SYNC.read_text(encoding="utf-8")


def test_state_paths_agree_between_bridge_and_daily_checkup() -> None:
    """The bridge's default STATE_DIR is the dir the daily_checkup MCP reads.

    Cross-file contract with no import to keep it honest. A drift here doesn't fail
    loudly — it makes the backstop read a nonexistent dir and grade the bridge green
    forever.
    """
    sync_state = re.search(
        r'STATE_DIR="\$\{BULLETIN_SYNC_STATE_DIR:-\$HOME/(?P<path>[^}"]+)\}"', _sync_src()
    )
    assert sync_state, (
        f"Could not find the STATE_DIR default in {_SYNC.name}. It is the contract the "
        "daily_checkup backstop reads — if it moved, update BULLETIN_SYNC_STATE in "
        f"{_MCP.name} in the same change, then fix this guard."
    )
    # e.g. ".local/state/visa_bulletin" -> the parts the MCP composes off Path.home()
    sync_parts = tuple(sync_state.group("path").strip("/").split("/"))

    mcp_state = re.search(
        r"BULLETIN_SYNC_STATE\s*=\s*Path\.home\(\)\s*(?P<parts>(?:/\s*\"[^\"]+\"\s*)+)", _MCP.read_text(encoding="utf-8")
    )
    assert mcp_state, f"BULLETIN_SYNC_STATE not found in {_MCP.name} — the backstop's half of the contract."
    mcp_parts = tuple(re.findall(r'"([^"]+)"', mcp_state.group("parts")))

    assert sync_parts == mcp_parts, (
        f"State-dir drift: {_SYNC.name} writes to ~/{'/'.join(sync_parts)} but "
        f"{_MCP.name} reads ~/{'/'.join(mcp_parts)}. The daily_checkup backstop would "
        "silently read nothing, fall back to log mtime, and report the bridge GREEN "
        "even while every run fails. Keep both sides in step."
    )


def test_state_filenames_agree_between_bridge_and_daily_checkup() -> None:
    """The two state FILE names match too — same silent-green failure as the dir."""
    src = _sync_src()
    for var, filename in (("FAIL_STREAK_FILE", "fetch_fail_streak"), ("LAST_SUCCESS_FILE", "last_success")):
        assert re.search(rf'{var}="\$STATE_DIR/{re.escape(filename)}"', src), (
            f"{_SYNC.name} no longer writes $STATE_DIR/{filename} via {var}. "
            f"{_MCP.name}'s _gather_bulletin_sync() reads that exact name."
        )
        assert f'"{filename}"' in _MCP.read_text(encoding="utf-8"), (
            f"{_MCP.name} no longer reads {filename!r}, which {_SYNC.name} writes. "
            "The backstop would grade the bridge on stale/absent data."
        )


def test_alert_failure_never_fails_the_run() -> None:
    """A broken alert path must not also break ingest.

    notify_chat reaches redis/the relay; if that's down, ingest itself is still fine and
    must proceed. `set -uo pipefail` + a bare failing call would abort the run instead.
    """
    src = _sync_src()
    alert_fn = re.search(r"^alert\(\)\s*\{.*?^\}", src, re.MULTILINE | re.DOTALL)
    assert alert_fn, f"alert() not found in {_SYNC.name}."
    assert "|| log" in alert_fn.group(0), (
        "alert() no longer swallows notify_chat failure. If the alert path breaks, a bare "
        "call would abort the ingest run it was only meant to report on."
    )


def test_notify_path_is_overridable() -> None:
    """The alert target is env-overridable so the alert path is testable off the live bot."""
    assert re.search(r'NOTIFY="\$\{BULLETIN_SYNC_NOTIFY:-', _sync_src()), (
        "NOTIFY is hardcoded again. It must stay ${BULLETIN_SYNC_NOTIFY:-...} so the "
        "failure/recovery paths can be exercised against a stub instead of firing real "
        "alerts at the visa_bulletin bot."
    )


def test_transient_fetch_failure_does_not_alert_immediately() -> None:
    """Alert on a STREAK, not on a single miss.

    The Akamai challenge intermittently doesn't settle (~1 run in 6) and the next run
    recovers. Alerting on every miss would train the alert to be ignored — the one
    outcome that makes this whole path worthless when the real August-bulletin miss lands.
    """
    src = _sync_src()
    assert re.search(r'ALERT_AFTER="\$\{BULLETIN_SYNC_ALERT_AFTER:-[2-9]\}"', src), (
        "ALERT_AFTER must default to >= 2. A default of 1 alerts on every transient "
        "wall miss (~1 in 6 runs) and turns the bridge's alerting into noise."
    )
    fail_fn = re.search(r"^fail_fetch\(\)\s*\{.*?^\}", src, re.MULTILINE | re.DOTALL)
    assert fail_fn, f"fail_fetch() not found in {_SYNC.name}."
    assert re.search(r'\[ "\$streak" -ge "\$ALERT_AFTER" \]', fail_fn.group(0)), (
        "fail_fetch() no longer gates its alert on the streak reaching ALERT_AFTER."
    )


def test_hard_failures_alert_immediately() -> None:
    """Never-transient failures bypass the streak gate.

    A non-zero refresh, a discovered-but-unignestable source, or a failed stream into
    vb_web are all real breaks (parser/DB/ssh) — waiting 90min to report them only
    delays the fix.
    """
    src = _sync_src()
    for key in ("bulletin-sync:stream-fail", "bulletin-sync:refresh-fail", "bulletin-sync:ingest-fail"):
        assert key in src, f"The immediate-alert path {key!r} is gone from {_SYNC.name}."


def test_new_bulletin_injects_an_agent_pass() -> None:
    """The payoff event still wakes an agent to verify the live site."""
    src = _sync_src()
    assert "bulletin-sync:new-bulletin" in src, (
        "The new-bulletin alert is gone. A landed bulletin (~12/yr) is the one event this "
        "whole bridge exists for, and it needs an agent pass over site/predictions/post."
    )
    assert re.search(r'alert inject "bulletin-sync:new-bulletin"', src), (
        "The new-bulletin alert must use `inject` (wakes an agent), not passive."
    )
