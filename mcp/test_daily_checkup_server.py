"""Regression tests for daily_checkup false-alarm fixes (2026-06-15).

Two routine, healthy conditions used to escalate the digest every morning:

  1. The predictions backtest renders heavy server-side Plotly, so its cold
     tail is routinely >10s. At PERF_RED_N10=5 that tripped the WHOLE digest to
     RED ("needs action") essentially every day (~14 >10s/24h is normal).

  2. _parse_log_age scanned the entire ~200-line tail (≈1.5 days of hourly
     runs), so a single transient travel.state.gov read-timeout that the very
     next hourly run recovered from re-surfaced as "stale or noisy" (YELLOW)
     for days.

Run: `uv run pytest test_daily_checkup_server.py` from this dir.
"""

import time

import daily_checkup_server as m

# ── Perf section: heavy-render surface must not false-alarm ──────────────────

def _lat(n10=0, n3=0, count=300):
    return {
        "count": count,
        "sum_ms": count * 200,
        "mean_ms": 200,
        "n_over_1s": 0,
        "n_over_3s": n3,
        "n_over_10s": n10,
    }


def test_predictions_routine_slow_tail_not_red():
    """14 >10s on predictions (routine heavy Plotly) stays green — not RED."""
    nx = {"surface_latency": {"predictions": _lat(n10=14)}}
    _section, status = m._section_top_properties(nx, None, None)
    assert status == "green", status


def test_predictions_genuine_spike_is_yellow_not_red():
    """A real explosion on predictions warns (yellow) but never escalates RED."""
    nx = {"surface_latency": {"predictions": _lat(n10=m.PERF_HEAVY_SPIKE_N10 + 5)}}
    _section, status = m._section_top_properties(nx, None, None)
    assert status == "yellow", status


def test_transactional_surface_slow_tail_still_red():
    """>10s on a transactional surface (salaries) IS a regression → still RED."""
    nx = {"surface_latency": {"salaries": _lat(n10=m.PERF_RED_N10)}}
    _section, status = m._section_top_properties(nx, None, None)
    assert status == "red", status


# ── Log parsing: recovered transient must not be flagged ─────────────────────

_MARKER = "=== Visa Bulletin Refresh ==="


def _log(tail: str) -> str:
    return f"{int(time.time())}\n{tail}"


def test_recovered_transient_not_flagged():
    """Transient error in an OLDER run + clean latest run → no errors counted."""
    tail = (
        "2026-06-14 02:00:32 [ERROR] lib.ingest: Failed to discover sources: Read timed out\n"
        f"{_MARKER}\n"
        "2026-06-15 11:00:02 [INFO] Discovered 291 sources\n"
        "2026-06-15 11:00:03 [INFO] No pending bulletins to ingest. Done.\n"
    )
    info = m._parse_log_age(_log(tail), latest_run_marker=_MARKER)
    assert info["tail_errors"] == [], info["tail_errors"]


def test_error_in_latest_run_still_flagged():
    """A genuinely broken latest run still surfaces the error."""
    tail = (
        f"{_MARKER}\n"
        "2026-06-15 11:00:02 [ERROR] lib.ingest: Failed to discover sources: Read timed out\n"
    )
    info = m._parse_log_age(_log(tail), latest_run_marker=_MARKER)
    assert len(info["tail_errors"]) == 1, info["tail_errors"]


def test_no_marker_falls_back_to_full_tail():
    """Without a marker (e.g. backup log), behavior is unchanged (full scan)."""
    tail = "2026-06-15 [ERROR] something broke\n"
    info = m._parse_log_age(_log(tail))
    assert len(info["tail_errors"]) == 1, info["tail_errors"]


# ── Surface deltas: full-coverage share% + distinct page counts (2026-06-17) ──

def test_surface_deltas_emit_share_and_pages_from_csv():
    """CSV path → each row carries share_pct (sums ~100) + distinct page count.

    Guards the digest's section-share table: the long-tail size (pages) and
    share must come from full coverage, never a top-100 sum.
    """
    pcw = {
        "this_7d": {
            "/": 60, "/employment-based/india/": 40,   # dashboard: 100 over 2 pages
            "/employer/a/": 5, "/employer/b/": 3, "/employer/c/": 2,  # 10 over 3
        },
        "prev_7d": {"/": 50, "/employer/a/": 10},
        "cycle_7d": {"/": 80, "/employer/a/": 4},
        "last_28d": {"/": 200, "/employer/a/": 20},
    }
    rows = {r["surface"]: r for r in m._build_surface_deltas(
        path_counts_by_window=pcw, fallback_surf_this={}, fallback_surf_cycle={})}
    assert rows["dashboard"]["this_week"] == 100
    assert rows["dashboard"]["pages"] == 2
    assert rows["employer_profile"]["this_week"] == 10
    assert rows["employer_profile"]["pages"] == 3   # all three distinct slugs
    # share_pct of all rows sums to ~100 (full coverage, no truncation)
    assert abs(sum(r["share_pct"] for r in rows.values()) - 100.0) < 0.01
    assert abs(rows["dashboard"]["share_pct"] - 100 / 110 * 100) < 0.01


def test_surface_deltas_fallback_has_null_share_and_pages():
    """top-100 fallback path → share/pages are None (never faked from a cap)."""
    rows = m._build_surface_deltas(
        path_counts_by_window=None,
        fallback_surf_this={"dashboard": 100}, fallback_surf_cycle={"dashboard": 80})
    assert rows[0]["share_pct"] is None
    assert rows[0]["pages"] is None
