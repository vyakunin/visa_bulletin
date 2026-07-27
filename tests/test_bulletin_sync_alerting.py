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

import os
import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SYNC = _REPO / "scripts/sync_bulletin_to_prod.sh"
_MCP = _REPO / "mcp/daily_checkup_server.py"


def _sync_src() -> str:
    return _SYNC.read_text(encoding="utf-8")


def test_armed_cutover_skips_the_run_without_alerting(tmp_path) -> None:
    """A data cutover must not page as a broken ingest — and must not touch the prod DB.

    Regression (2026-07-16): `cutover.sh --data` resyncs prod from staging via
    pg_dump | psql. Mid-resync the prod DB is transiently half-populated and
    constraint-less, so refresh_bulletin died on DataSource.MultipleObjectsReturned and
    the bridge fired `bulletin-sync:refresh-fail` — "Ingest is broken (parser/DB, not
    Akamai)" — for a release that was working exactly as designed. cutover.sh's
    hs_ingest_pause() only comments out the HOMESERVER crontab, and bulletin ingest moved
    to this minipc-side bridge the same day, so the pause had silently become a no-op.

    Skipping is also what stops real damage: discover's get_or_create can INSERT into
    DataSource between that table's COPY and its unique-index rebuild, which makes the
    resync's CREATE UNIQUE INDEX fail under ON_ERROR_STOP=0 and leaves prod permanently
    without the constraint.

    Hermetic: the guard runs before any fetch/ssh, so this exercises the real script.
    """
    marker = tmp_path / "vb_cutover_in_flight"
    marker.write_text(str(os.getpid()))  # our own PID — guaranteed alive
    notify_log = tmp_path / "notify_calls.log"
    stub = tmp_path / "notify_stub.py"
    stub.write_text(f"import sys, pathlib\npathlib.Path({str(notify_log)!r}).open('a').write(' '.join(sys.argv[1:]))\n")

    proc = subprocess.run(
        ["bash", str(_SYNC)],
        env={
            **os.environ,
            "VB_CUTOVER_MARKER": str(marker),
            "BULLETIN_SYNC_NOTIFY": str(stub),
            "BULLETIN_SYNC_STATE_DIR": str(tmp_path / "state"),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, (
        "The bridge must exit 0 (clean skip) while a cutover is armed, so cron doesn't "
        f"treat a healthy release as a failure. Got {proc.returncode}.\n{proc.stdout}\n{proc.stderr}"
    )
    assert not notify_log.exists(), (
        "The bridge alerted during an armed cutover. A routine data graduation must not "
        f"page as a broken ingest. Alert(s) sent: {notify_log.read_text() if notify_log.exists() else ''}"
    )
    assert "cutover in flight" in proc.stdout, (
        f"Expected the cutover-interlock skip message. Got:\n{proc.stdout}"
    )


def test_stale_cutover_marker_cannot_mute_ingest_forever() -> None:
    """A leftover marker must never silently disable the only bulletin ingest path.

    cutover.sh's EXIT trap does NOT run on SIGKILL (the script says so itself), so a
    killed cutover leaves its marker behind. If the bridge trusted a bare file-exists
    check, ingest would skip every run forever, silently — and the daily_checkup backstop
    grades on last_success, which a skipping run never updates. So the guard must require
    a LIVE owner and a bounded age.
    """
    fn = re.search(r"^cutover_in_flight\(\)\s*\{.*?^\}", _sync_src(), re.MULTILINE | re.DOTALL)
    assert fn, f"cutover_in_flight() not found in {_SYNC.name} — the cutover interlock is gone."
    body = fn.group(0)
    assert "kill -0" in body, (
        "cutover_in_flight() no longer checks the marker's owner is alive. A marker left "
        "by a SIGKILLed cutover would mute bulletin ingest forever, silently."
    )
    assert "CUTOVER_MAX_AGE_MIN" in body, (
        "cutover_in_flight() no longer bounds the marker's age. PIDs are recycled; an "
        "ancient marker whose PID now belongs to an unrelated process would mute ingest."
    )


def test_prod_touching_alerts_are_cutover_gated() -> None:
    """Every alert that blames prod must first rule out an in-flight cutover.

    The top-of-run guard narrows the window but cannot close it — a cutover can arm
    mid-run, restarting vb_web and resyncing the DB under a bridge run already in
    progress. Each of these three alerts names prod as broken, so each must re-check.
    """
    src = _sync_src()
    for key in ("bulletin-sync:stream-fail", "bulletin-sync:refresh-fail", "bulletin-sync:ingest-fail"):
        before = src.split(f'alert inject "{key}"')[0]
        guard = before.rfind("if cutover_in_flight; then")
        branch = before.rfind("if ")
        assert guard != -1 and guard >= branch - 400, (
            f"The {key!r} alert is no longer gated on cutover_in_flight(). A cutover that "
            "arms mid-run would make this fire against a healthy release."
        )


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


def test_cdp_wedge_detection_requires_the_full_signature() -> None:
    """The auto-restart must fire ONLY on a genuinely wedged browser.

    Regression (2026-07-27): Chrome had been up 10 days with 8 stale tabs; the CDP HTTP
    endpoint still answered /json/version and the websocket still connected, but no page
    target responded, so connect_over_cdp hung to its 180s timeout on every run for ~12h
    until a human restarted the service.

    That exact triple — ws CONNECTED, then a connect_over_cdp TIMEOUT — is what proves
    the browser is unusable by every agent (a co-tenant's tabs are dead too), which is
    what makes an unattended restart of a SHARED service safe. A looser match (any
    non-zero exit, or a bare "Timeout") would restart the browser out from under other
    projects on an unrelated failure — e.g. a refused endpoint, which is a different
    fault entirely and belongs to the alert path.
    """
    src = _sync_src()
    fn = re.search(r"^cdp_is_wedged\(\)\s*\{.*?^\}", src, re.MULTILINE | re.DOTALL)
    assert fn, "cdp_is_wedged() is gone — the wedged-Chrome self-heal has no guard."
    body = fn.group(0)
    for marker in ("connect_over_cdp", "<ws connected>", "Timeout"):
        assert marker in body, (
            f"cdp_is_wedged() no longer requires {marker!r}. All three markers together "
            "are what distinguish a wedged browser from an absent/refused endpoint; "
            "dropping one turns this into a restart-on-any-failure."
        )


def test_cdp_autoheal_never_restarts_chrome_on_the_test_path() -> None:
    """A stubbed CDP endpoint must never restart the real shared browser.

    BULLETIN_FETCH_CDP is how the alert path gets exercised without waiting for a real
    Akamai miss — it points the fetcher at a deliberately dead endpoint. If the self-heal
    ignored it, running the alerting test would kill the debug Chrome (and every other
    project's tabs) as a side effect.
    """
    src = _sync_src()
    heal = re.search(r"cdp_is_wedged \\\n?.*?^fi", src, re.MULTILINE | re.DOTALL)
    assert heal, "The CDP self-heal block is gone from the fetch path."
    block = heal.group(0)
    assert '-z "${BULLETIN_FETCH_CDP:-}"' in block, (
        "The self-heal no longer skips when BULLETIN_FETCH_CDP is set. A test pointed at "
        "a stub endpoint would restart the real shared debug Chrome."
    )
    assert 'BULLETIN_CDP_AUTOHEAL:-1' in block, (
        "The BULLETIN_CDP_AUTOHEAL kill switch is gone. Restarting a shared service "
        "unattended needs an off switch that does not require editing the script."
    )


def test_cdp_autoheal_retries_at_most_once() -> None:
    """One restart per run — never a retry loop against a browser that will not come back.

    A loop here would hammer a shared service every cron tick and could mask a real,
    persistent fault (bad profile, port taken) behind endless restarts instead of letting
    the failure streak reach ALERT_AFTER and page a human.
    """
    src = _sync_src()
    heal = re.search(r"cdp_is_wedged \\\n?.*?^fi", src, re.MULTILINE | re.DOTALL)
    assert heal, "The CDP self-heal block is gone from the fetch path."
    block = heal.group(0)
    assert block.count("systemctl --user restart debug_chrome_cdp.service") == 1, (
        "More than one restart in the self-heal block — it must restart at most once, "
        "then fall through to the streak/alert path."
    )
    assert block.count("run_fetch") == 1, (
        "The self-heal must re-run the fetch exactly once after the restart."
    )
    # The fall-through matters as much as the retry: a failed heal must still alert.
    assert re.search(r'if \[ "\$FETCH_RC" -ne 0 \] \|\| ! echo "\$SUMMARY"', src), (
        "The self-heal no longer falls through to the fetch-failure/alert check, so a "
        "browser that stays wedged after a restart would report success."
    )
