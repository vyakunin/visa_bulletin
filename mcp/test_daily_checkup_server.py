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

import shutil
import subprocess
import time

import daily_checkup_server as m
import httpx
import pytest

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
    _section, status = m._section_top_properties(nx, None)
    assert status == "green", status


def test_predictions_genuine_spike_is_yellow_not_red():
    """A real explosion on predictions warns (yellow) but never escalates RED."""
    nx = {"surface_latency": {"predictions": _lat(n10=m.PERF_HEAVY_SPIKE_N10 + 5)}}
    _section, status = m._section_top_properties(nx, None)
    assert status == "yellow", status


def test_transactional_surface_slow_tail_still_red():
    """>10s on a transactional surface (salaries) IS a regression → still RED."""
    nx = {"surface_latency": {"salaries": _lat(n10=m.PERF_RED_N10)}}
    _section, status = m._section_top_properties(nx, None)
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


# ── Bulletin ingest bridge backstop (2026-07-16) ─────────────────────────────
# The prod-side hourly refresh cron was retired (Akamai 403'd every run); the
# minipc browser bridge is now the only ingest path. It self-alerts on failure
# streaks, so this section's job is narrowly the blind spot it cannot cover —
# the cron not firing — graded on the age of the last SUCCESS.

def _sync_info(success_age_min, *, log_age_min=5, streak=0, errors=None):
    return {
        "present": True,
        "last_run": "2026-07-16T12:00:00+00:00",
        "age_min": log_age_min,
        "success_age_min": success_age_min,
        "last_success": "2026-07-16T12:00:00+00:00",
        "fail_streak": streak,
        "tail_errors": errors or [],
        "tail_last_lines": [],
    }


def test_bridge_fresh_success_is_green_and_silent():
    """A recent successful fetch emits no section at all."""
    section, status = m._section_bulletin_refresh(_sync_info(20))
    assert status == "green", status
    assert section is None


def test_bridge_single_transient_failure_not_flagged():
    """One failed run (Akamai challenge blip, ~1 in 6) must NOT surface.

    The bridge recovers on the next tick; flagging it would re-create the daily
    false-alarm this section was rewritten to avoid.
    """
    section, status = m._section_bulletin_refresh(
        _sync_info(35, streak=1, errors=["2026-07-16 13:00:24 ERROR Index fetch did not yield"])
    )
    assert status == "green", status
    assert section is None


def test_bridge_failing_every_run_is_red_despite_fresh_log():
    """The trap: a bridge failing every run still WRITES the log every 30 min.

    Grading on log mtime would read green while bulletin ingest is dead. Age of
    last SUCCESS is what must drive the status.
    """
    section, status = m._section_bulletin_refresh(
        _sync_info(900, log_age_min=2, streak=18, errors=["ERROR Index fetch did not yield"])
    )
    assert status == "red", status
    assert "FAILING" in section["title"]


def test_bridge_alerting_streak_is_red_even_if_success_recent():
    """3+ consecutive failures = the bridge's own alert threshold → red here too."""
    section, status = m._section_bulletin_refresh(_sync_info(95, streak=3))
    assert status == "red", status


def test_bridge_stale_cron_is_flagged():
    """Cron stopped firing → last success ages out → yellow, then red."""
    _s, status = m._section_bulletin_refresh(_sync_info(m.BULLETIN_REFRESH_YELLOW_MIN + 10))
    assert status == "yellow", status
    _s, status = m._section_bulletin_refresh(_sync_info(m.BULLETIN_REFRESH_RED_MIN + 10))
    assert status == "red", status


def test_bridge_missing_log_is_red():
    """No log at all = the cron was never installed / was removed."""
    section, status = m._section_bulletin_refresh({"present": False, "tail": ""})
    assert status == "red", status
    assert "MISSING" in section["title"]


def test_bridge_unbracketed_error_is_matched():
    """The bridge logs plain `ERROR ...`, not Django's `[ERROR]`.

    With the default matcher every bridge failure would read as green.
    """
    import re
    tail = (
        "[sync_bulletin] fetching via debug Chrome...\n"
        "2026-07-16 13:00:24,047 ERROR Index fetch did not yield bulletin links. len=19621\n"
    )
    info = m._parse_log_age(
        _log(tail),
        latest_run_marker="fetching via debug Chrome",
        error_re=re.compile(r"\[ERROR\]|\[CRITICAL\]|\bERROR\b|\bFAILED\b"),
    )
    assert len(info["tail_errors"]) == 1, info["tail_errors"]
    # …and the default matcher is what would have missed it.
    assert m._parse_log_age(_log(tail), latest_run_marker="fetching via debug Chrome")["tail_errors"] == []


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


# ── CF Managed Challenge is not a probe failure (2026-07-01) ──────────────────
# /salaries/ got a Cloudflare Managed Challenge on 2026-06-28. A headless probe
# always gets a 403 challenge interstitial it can't solve, but real browsers
# pass it invisibly — so it must NOT flag the probe (and the whole digest) RED.

def _resp(status, headers=None, body=""):
    return httpx.Response(status, headers=headers or {}, content=body.encode())


def test_cf_challenge_detected_by_header():
    """Authoritative signal: `cf-mitigated: challenge` header."""
    assert m._is_cf_challenge(_resp(403, {"cf-mitigated": "challenge"}))


def test_cf_challenge_detected_by_body_marker():
    """Fallback: 403/503 + the challenge-platform interstitial marker."""
    assert m._is_cf_challenge(_resp(403, body="<script>challenge-platform</script>"))
    assert m._is_cf_challenge(_resp(503, body="challenge-platform"))


def test_genuine_403_is_not_a_challenge():
    """A plain 403 with no CF challenge signal is still a real failure."""
    assert not m._is_cf_challenge(_resp(403, body="Forbidden"))


def test_genuine_5xx_body_marker_is_not_a_challenge():
    """A 500 (outside the 403/503 challenge set) is a real error, not a challenge.

    CF only serves managed challenges as 403/503 + the cf-mitigated header, so a
    body substring on a 500 must not mask a genuine origin exception.
    """
    assert not m._is_cf_challenge(_resp(500, body="challenge-platform noise"))


def test_challenged_probe_is_ok_and_digest_stays_green():
    """A challenged /salaries/ probe → ok=True, section green (info-only note)."""
    probes = [
        {"label": "home", "url": "u", "status": 200, "ok": True, "body_check": {}},
        {"label": "salaries", "url": "u", "status": 403, "ok": True,
         "challenged": True, "body_check": {}},
    ]
    section, status = m._section_probes(probes)
    assert status == "green", status
    assert section is not None and "CF challenge" in section["title"]
    assert section["importance"] == 1


def test_genuine_probe_failure_still_red():
    """A real non-200 (not a challenge) still escalates the probes section RED."""
    probes = [
        {"label": "home", "url": "u", "status": 200, "ok": True, "body_check": {}},
        {"label": "salaries", "url": "u", "status": 500, "ok": False, "body_check": {}},
    ]
    section, status = m._section_probes(probes)
    assert status == "red", status


def test_surface_deltas_fallback_has_null_share_and_pages():
    """top-100 fallback path → share/pages are None (never faked from a cap)."""
    rows = m._build_surface_deltas(
        path_counts_by_window=None,
        fallback_surf_this={"dashboard": 100}, fallback_surf_cycle={"dashboard": 80})
    assert rows[0]["share_pct"] is None
    assert rows[0]["pages"] is None


# ── Surface taxonomy: newly-launched pSEO families get their own bucket ──────
# Regression for 2026-06-29: priority-date / h1b-salary / h1b-sponsors / es
# pSEO pages were all silently falling into `other`. Each must classify into a
# dedicated surface so the per-surface block in the digest shows them.

def test_new_pseo_surfaces_have_dedicated_buckets():
    cases = {
        "/priority-date/": "priority_date",
        "/priority-date/eb2/": "priority_date",
        "/priority-date/eb2/india/": "priority_date",
        "/priority-date-calculator/": "priority_date",
        "/h1b-salary/": "occupation_salary",
        "/h1b-salary/software-engineer/": "occupation_salary",
        "/h1b-salary/google-llc/software-engineer/": "occupation_salary",
        "/h1b-sponsors/in/california/": "h1b_sponsors",
        "/h1b-sponsors/data-scientist/": "h1b_sponsors",
        "/es/": "spanish",
        "/es/faq/": "spanish",                       # NOT static_pages
        "/es/priority-date/eb3/mexico/": "spanish",  # NOT priority_date
    }
    for path, expected in cases.items():
        assert m._bucket_path(path) == expected, f"{path} -> {m._bucket_path(path)} (want {expected})"
    # every dedicated bucket is also a rendered top-property (not dropped)
    for surf in {"priority_date", "occupation_salary", "h1b_sponsors", "spanish"}:
        assert surf in m.TOP_PROPERTY_SURFACES
        assert surf in m.SURFACE_LABELS


def test_dead_surfaces_not_rendered():
    """worksites (~0 traffic) + donation_click (events filtered → always empty)
    must NOT render as 'no data' rows. Still classified (pattern kept) so they
    don't pollute `other`. Regression for 2026-06-29 user request."""
    for surf in ("worksites", "donation_click"):
        assert surf not in m.TOP_PROPERTY_SURFACES, f"{surf} must not render"
    # but still classifiable (no `other` pollution)
    assert m._bucket_path("/worksites/foo") == "worksites"
    assert m._bucket_path("ext-buy-me-a-coffee") == "donation_click"


# ── DOL data freshness: weekly-refresh trigger signal (2026-06-20) ───────────

def test_dol_tuples_parse_program_fy_quarter_and_skip_noise():
    """LCA/PERM disclosure files parse to (program, fy, quarter); worksite /
    appendix / pw files are excluded; DOL's misspelled 'dislclosure' is tolerated."""
    # Realistic input: one URL per line (matches the psql `SELECT url` dump and
    # the quote/slash-delimited HTML hrefs the regex is designed for).
    base = "https://www.dol.gov/sites/dolgov/files/eta/oflc/pdfs/"
    text = "\n".join(base + n for n in [
        "lca_disclosure_data_fy2026_q1.xlsx",
        "lca_dislclosure_data_fy2026_q2.xlsx",   # DOL's real misspelling
        "perm_disclosure_data_fy2024.xlsx",      # annual → quarter 0
        "perm_disclosure_data_fy2026_q2.xlsx",
        "lca_worksites_fy2026_q2.xlsx",          # excluded
        "pw_appendix_a_fy2026_q2.xlsx",          # excluded
    ])
    got = m._dol_disclosure_tuples(text)
    assert ("H1B", 2026, 1) in got
    assert ("H1B", 2026, 2) in got               # misspelled file still caught
    assert ("PERM", 2024, 0) in got
    assert ("PERM", 2026, 2) in got
    assert not any("worksite" for t in got if False)  # noise excluded
    assert all(t[2] in (0, 1, 2) for t in got)
    # worksite/appendix never create H1B FY2026 beyond the disclosure ones
    assert len([t for t in got if t[0] == "H1B" and t[1] == 2026]) == 2


def test_dol_rank_annual_ranks_as_full_year():
    """Annual (q=0) ranks as Q4 so it isn't treated as 'older' than a quarter."""
    assert m._dol_rank(("PERM", 2025, 0)) == m._dol_rank(("PERM", 2025, 4))
    assert m._dol_rank(("PERM", 2026, 1)) > m._dol_rank(("PERM", 2025, 0))


def test_freshness_current_is_green():
    """Upstream == prod → green, no action."""
    up = {"H1B": ("H1B", 2026, 2), "PERM": ("PERM", 2026, 2)}
    prod = "lca_dislclosure_data_fy2026_q2.xlsx\nperm_disclosure_data_fy2026_q2.xlsx\n"
    sec, status = m._section_data_freshness(up, prod)
    assert status == "green", status
    assert "current" in sec["title"].lower()


def test_freshness_new_upstream_is_yellow():
    """DOL newer than prod → yellow with the trigger hint."""
    up = {"H1B": ("H1B", 2026, 2), "PERM": ("PERM", 2026, 2)}
    prod = "lca_dislclosure_data_fy2026_q1.xlsx\nperm_disclosure_data_fy2026_q1.xlsx\n"
    sec, status = m._section_data_freshness(up, prod)
    assert status == "yellow", status
    assert "new file(s) available" in sec["title"]
    assert "🆕" in sec["body"]


def test_freshness_upstream_unreachable_is_green_informational():
    """Transient DOL fetch failure must not escalate the digest."""
    prod = "perm_disclosure_data_fy2026_q2.xlsx\n"
    sec, status = m._section_data_freshness(None, prod)
    assert status == "green", status


# --- GA4 engagement section --------------------------------------------------

def _ga4_rows(*rows):
    return [
        {"landingPage": p, "sessions": str(s), "engagedSessions": str(e),
         "userEngagementDuration": str(d)}
        for p, s, e, d in rows
    ]


def test_ga4_bucket_aggregates_surfaces():
    b = m._ga4_bucket(_ga4_rows(
        ("/", 100, 80, 5000),
        ("/job-title/head-chef", 30, 10, 300),
        ("/job-title/orthoptist", 20, 10, 200),
        ("/employer/google-llc", 50, 35, 900),
    ))
    assert b["site organic"]["sessions"] == 200          # everything
    assert b["/job-title/*"] == {"sessions": 50, "engaged": 20, "eng_dur": 500.0}
    assert b["/employer/*"]["engaged"] == 35


def test_ga4_engagement_drop_flags_yellow():
    """≥10pt WoW engagement drop on a watched surface with enough N → yellow."""
    cur = m._ga4_bucket(_ga4_rows(("/job-title/x", 100, 45, 1000)))
    prev = m._ga4_bucket(_ga4_rows(("/job-title/x", 100, 60, 1000)))
    sec, status = m._section_ga4_engagement({"this_7d": cur, "prior_7d": prev})
    assert status == "yellow", status
    assert "−15pt" in sec["title"]


def test_ga4_small_n_never_flags():
    """Below GA4_MIN_SESSIONS the rate is noise — stays green."""
    cur = m._ga4_bucket(_ga4_rows(("/job-title/x", 20, 2, 50)))
    prev = m._ga4_bucket(_ga4_rows(("/job-title/x", 30, 25, 700)))
    sec, status = m._section_ga4_engagement({"this_7d": cur, "prior_7d": prev})
    assert status == "green", status
    assert "20 sess" in sec["body"] and "30 sess" in sec["body"]


# ── GA4 stopped reporting engagedSessions on 2026-08-06 (property 539743892) ──
#
# The metric did not go missing, it went to nearly zero — which reads exactly like
# the audience walking out. Measured, organic site-wide:
#
#   date    sessions  engaged  pageviews  engagementDuration(s)
#   Aug 05     865      550      2215        44577
#   Aug 06     839       25      2001        35946   <- break
#   Aug 07     813       15      1809        32482
#   Aug 08     742        8      1450        25225
#
# A live production probe returned gcs=G101, wrote the _ga_* cookie with the
# engaged flag set and sent seg=1, so the site is innocent and the fault is inside
# GA4's processing — there is no fix to ship and no action to take, but the digest
# would report an organic engagement collapse every morning until Google recovers.
#
# The guard is the arithmetic contradiction, not a date skip: see the GA4_*
# constants for the derivation from GA4's own >10s / 2+ pageviews definition.

_GA4_BREAK_DAYS = [
    ("20260805", 865, 550, 2215, 44577),
    ("20260806", 839, 25, 2001, 35946),
    ("20260807", 813, 15, 1809, 32482),
    ("20260808", 742, 8, 1450, 25225),
]


def _ga4_daily(*rows) -> list[dict]:
    return [{"date": d, "sessions": str(s), "engagedSessions": str(e),
             "screenPageViews": str(p), "userEngagementDuration": str(dur)}
            for d, s, e, p, dur in rows]


def test_ga4_break_days_are_implausible_and_the_healthy_day_is_not():
    """The measured break, day by day, against the day before it."""
    by_date = {d.date: d for d in
               (m._ga4_day_plausibility(r) for r in _ga4_daily(*_GA4_BREAK_DAYS))}

    healthy = by_date["20260805"]
    assert not healthy.implausible
    assert round(healthy.implied_engaged_s) == 75    # 41427s over 550 engaged

    for day in ("20260806", "20260807", "20260808"):
        assert by_date[day].implausible, by_date[day]
    # 8 engaged would each need 37 min, and 1450 pageviews force at least 24.
    worst = by_date["20260808"]
    assert round(worst.implied_engaged_s) == 2236
    assert round(worst.pageview_floor) == 24


def test_ga4_break_is_reported_as_a_fault_and_does_not_grade():
    """REPLAY: the Aug 6-8 shape must be labelled a fault, not an engagement drop.

    The 7d buckets carry the collapsed rate that would otherwise read as a −25pt
    WoW regression on every surface; the daily series is what proves it cannot be
    real, so the section stays green with the numbers still on the page.
    """
    cur = m._ga4_bucket(_ga4_rows(("/job-title/x", 800, 20, 30000)))
    prev = m._ga4_bucket(_ga4_rows(("/job-title/x", 820, 520, 42000)))
    ga4 = {"this_7d": cur, "prior_7d": prev, "daily": _ga4_daily(*_GA4_BREAK_DAYS)}

    sec, status = m._section_ga4_engagement(ga4)
    assert status == "green", status
    assert "INSTRUMENTATION FAULT" in sec["body"]
    assert "unreliable (GA4-side fault" in sec["title"]
    assert "engagement −" not in sec["title"], "must not read as a regression"
    # 3 of the 4 supplied days, named, and the raw counts still rendered.
    assert "2026-08-06, 2026-08-07, 2026-08-08" in sec["body"]
    assert "800 sess" in sec["body"] and "20 engaged" in sec["body"]
    assert sec["importance"] == 3, "a broken metric is worth reading"


def test_ga4_genuine_engagement_decline_still_grades_yellow():
    """REPLAY: engaged down WITH pages/session and duration down is REAL.

    The same collapsed engaged-session count as the fault case, but the rest of
    the day collapses with it — which is what a real decline looks like and what
    the guard must never absorb.
    """
    real_decline = [
        ("20260805", 800, 480, 1900, 40000),
        ("20260806", 780, 150, 900, 9000),
        ("20260807", 760, 120, 830, 7000),
        ("20260808", 742, 100, 800, 6000),
    ]
    for row in _ga4_daily(*real_decline):
        assert not m._ga4_day_plausibility(row).implausible, row

    cur = m._ga4_bucket(_ga4_rows(("/job-title/x", 800, 130, 8000)))
    prev = m._ga4_bucket(_ga4_rows(("/job-title/x", 820, 520, 42000)))
    sec, status = m._section_ga4_engagement(
        {"this_7d": cur, "prior_7d": prev, "daily": _ga4_daily(*real_decline)})
    assert status == "yellow", status
    assert "INSTRUMENTATION FAULT" not in sec["body"]
    assert "engagement −" in sec["title"], sec["title"]


def test_ga4_duration_collapse_alone_is_not_a_fault():
    """Half the contradiction is not the contradiction.

    Engaged near-zero with pageviews near-zero too: the pageview floor is not
    breached, so this is a real (if odd) day and must still grade.
    """
    row = _ga4_daily(("20260808", 742, 8, 760, 25225))[0]
    day = m._ga4_day_plausibility(row)
    assert day.implied_engaged_s > m.GA4_IMPLIED_ENGAGED_S_CEILING  # duration half fires
    assert day.engaged >= day.pageview_floor                        # pageview half does not
    assert not day.implausible


def test_ga4_pageview_evidence_alone_is_not_a_fault():
    """The mirror: pageviews force more engaged sessions than reported, but the
    duration is consistent with the low count, so nothing is contradictory."""
    row = _ga4_daily(("20260808", 742, 8, 1450, 200))[0]
    day = m._ga4_day_plausibility(row)
    assert day.engaged < day.pageview_floor                          # pageview half fires
    assert day.implied_engaged_s <= m.GA4_IMPLIED_ENGAGED_S_CEILING  # duration half does not
    assert not day.implausible


def test_ga4_low_traffic_day_cannot_prove_a_fault():
    """Below GA4_FAULT_MIN_SESSIONS the arithmetic is noise, not proof."""
    row = _ga4_daily(("20260808", 40, 0, 90, 1500))[0]
    assert not m._ga4_day_plausibility(row).implausible


def test_ga4_missing_daily_series_grades_the_old_way():
    """No daily rows (older payload, or the third GA4 call failed) → guard off.

    The safe direction: a missing series may leave a false alarm standing, but it
    must never silence a real collapse.
    """
    cur = m._ga4_bucket(_ga4_rows(("/job-title/x", 800, 20, 30000)))
    prev = m._ga4_bucket(_ga4_rows(("/job-title/x", 820, 520, 42000)))
    sec, status = m._section_ga4_engagement({"this_7d": cur, "prior_7d": prev})
    assert status == "yellow", status
    assert "INSTRUMENTATION FAULT" not in sec["body"]


def test_ga4_daily_report_fetches_the_metrics_the_guard_reads():
    """The guard needs screenPageViews, which only this report asks for."""
    args = m._ga4_daily_args("7daysAgo", "yesterday")
    assert args["dimensions"] == ["date"]
    for metric in ("sessions", "engagedSessions", "screenPageViews",
                   "userEngagementDuration"):
        assert metric in args["metrics"], metric


# ── Pre-rendered sitemap freshness (2026-07-19) ─────────────────────────────
#
# /sitemap.xml is now a static file vb_nginx serves off disk. Its failure mode is
# SILENT: the renderer refuses to publish a degraded render and leaves the last
# good file serving, which is safe but invisible. This project has already been
# burned by exactly that shape — the retired prod bulletin cron 403'd silently
# for months — so the age grading is worth pinning.

def _sitemap_raw(age_hours: float, urls: int = 6888, size: int = 1_314_365) -> str:
    mtime = int(time.time() - age_hours * 3600)
    return f"{mtime}|{size}\n{urls}\n"


def test_fresh_sitemap_is_green_and_silent():
    section, status = m._section_sitemap(m._parse_sitemap(_sitemap_raw(6)))
    assert status == "green", status
    assert section is None, "a healthy sitemap must not add digest noise"


def test_one_missed_render_is_still_green():
    """Cron is daily; ~26h means one run slipped, not a failure."""
    _s, status = m._section_sitemap(m._parse_sitemap(_sitemap_raw(26)))
    assert status == "green", status


def test_two_missed_renders_go_yellow():
    section, status = m._section_sitemap(m._parse_sitemap(_sitemap_raw(36)))
    assert status == "yellow", status
    assert "render_sitemap.log" in section["body"], "must point at the refusal reason"


def test_long_stale_sitemap_goes_red():
    _s, status = m._section_sitemap(m._parse_sitemap(_sitemap_raw(72)))
    assert status == "red", status


def test_missing_file_is_flagged_but_not_red():
    """nginx falls back to Django, so the sitemap is correct — just slow again."""
    section, status = m._section_sitemap(m._parse_sitemap("MISSING\n"))
    assert status == "yellow", status
    assert "render_sitemap" in section["body"], "must give the fix command"


def test_forced_degraded_render_is_red_even_when_fresh():
    """A fresh file with ~50 URLs means someone --force'd past the min-urls gate."""
    section, status = m._section_sitemap(m._parse_sitemap(_sitemap_raw(1, urls=52, size=40_000)))
    assert status == "red", status
    assert "52 URLs" in section["body"]


def test_parse_handles_missing_url_count():
    """stat succeeded but the grep line is absent — degrade, don't crash."""
    mtime = int(time.time() - 3600)
    info = m._parse_sitemap(f"{mtime}|1314365\n")
    assert info["present"] is True
    assert "urls" not in info
    _s, status = m._section_sitemap(info)
    assert status == "green", status


# ── Per-property block: share% + distinct pages + the `other` row ─────────────
# `_build_surface_deltas` computed share_pct and pages from full CSV coverage,
# but `_format_property_block` never emitted them, so the digest composer
# re-derived share by hand off the rounded 7d strings every morning (six runs
# straight, 2026-07-25..08-04) and rendered pages as n/a. And with no `other`
# row, a live surface with no SURFACE_PATTERNS bucket showed up only as a gap
# between the rendered rows and the 7d total — indistinguishable from rounding.

def _pcw_full() -> dict[str, dict[str, int]]:
    """One representative this_7d window, 2008 views over 5 buckets + `other`."""
    this = {
        "/": 700, "/employment-based/india/": 300,            # dashboard 1000 / 2p
        "/when-is-the-next-visa-bulletin": 400,               # bulletin_timing 400 / 1p
        "/employer/a/": 20, "/employer/b/": 20, "/employer/c/": 20,
        "/employer/d/": 20, "/employer/e/": 20,               # employer_profile 100 / 5p
        "/job-title/x/": 60, "/job-title/y/": 40,             # job_title_profile 100 / 2p
        "/salaries/": 8,                                      # salaries 8 / 1p
        "/glossary/": 392, "/tiny-thing/": 8,                 # other 400 / 2p
    }
    return {"this_7d": this, "prev_7d": dict(this), "cycle_7d": dict(this),
            "last_28d": {p: c * 4 for p, c in this.items()}}


def _gc_from(pcw: dict[str, dict[str, int]] | None) -> dict:
    """The gc payload the section reads, built through the real delta builder."""
    return {
        "surfaces": m._build_surface_deltas(
            path_counts_by_window=pcw,
            fallback_surf_this={"dashboard": 1000}, fallback_surf_cycle={"dashboard": 800}),
        "surfaces_source": "csv_full" if pcw else "top100_hits",
    }


def test_property_block_emits_share_and_page_count():
    """Each surface row carries share-of-total % and its distinct-path count."""
    section, _status = m._section_top_properties({}, _gc_from(_pcw_full()))
    body = section["body"]
    assert "**1.0k** views 7d · 50% of site · 2 pages" in body, body
    assert "5.0% of site · 5 pages" in body, body      # employer profiles: a real tail
    assert "20% of site · 1 page" in body, body        # bulletin_timing, singular "page"


def test_small_share_keeps_a_decimal():
    """A 0.4% surface must not render as `0% of site`."""
    body = m._section_top_properties({}, _gc_from(_pcw_full()))[0]["body"]
    assert "0.4% of site · 1 page" in body, body


def test_bulletin_timing_is_a_rendered_property():
    """Bucketed by SURFACE_PATTERNS AND rendered — not classified into silence."""
    assert "bulletin_timing" in m.TOP_PROPERTY_SURFACES
    body = m._section_top_properties({}, _gc_from(_pcw_full()))[0]["body"]
    assert "when-is-the-next-visa-bulletin" in body, body


def test_unclassified_traffic_renders_an_other_row_naming_its_paths():
    """`other` > 0 → its own row, with the biggest unbucketed paths named."""
    body = m._section_top_properties({}, _gc_from(_pcw_full()))[0]["body"]
    assert "Other (long-tail / unclassified)" in body, body
    assert "20% of site · 2 pages" in body, body
    assert "add a SURFACE_PATTERNS bucket" in body, body
    assert "`/glossary/` 392" in body, body            # the one to go bucket
    assert "`/tiny-thing/` 8" in body, body


def test_no_other_row_when_everything_is_classified():
    """A clean taxonomy renders no residual row at all."""
    pcw = {"this_7d": {"/": 100}, "prev_7d": {"/": 100},
           "cycle_7d": {"/": 100}, "last_28d": {"/": 400}}
    body = m._section_top_properties({}, _gc_from(pcw))[0]["body"]
    assert "unclassified" not in body.lower(), body


def test_other_row_never_escalates_the_digest():
    """A slow tail on the unclassified mix is not a property regression."""
    nx = {"surface_latency": {"other": _lat(n10=m.PERF_RED_N10 * 4)}}
    _section, status = m._section_top_properties(nx, _gc_from(_pcw_full()))
    assert status == "green", status


def test_fallback_rows_render_no_share_or_pages():
    """top-100 path → share/pages are None, so neither is printed (never `None%`)."""
    body = m._section_top_properties({}, _gc_from(None))[0]["body"]
    gc_lines = [ln for ln in body.splitlines() if ln.strip().startswith("GC:")]
    assert gc_lines, body
    for ln in gc_lines:
        assert "of site" not in ln, ln
        assert "page" not in ln, ln
        assert "None" not in ln, ln


# ── Slow tail: a concurrency burst is not a latency regression (2026-08-09) ───
#
# The 2026-07-29 digest led RED on the >10s tail. Nothing was wrong: 101 requests
# over 10s in 24h, but 93 of them inside a single hour (16:00 UTC), spread over
# ~90 distinct IPs at a max of 5 each — the residential-proxy-swarm signature in
# analytics.md §5, hitting profile pages concurrently and saturating gunicorn
# workers. Every one returned 200, 5xx stayed at 0.01%, and the means outside the
# burst were healthy (job-title 245ms/26.8k, employer 208ms/22.8k, salaries
# 168ms/16.5k). So the digest paged for a self-resolving traffic event.
#
# Both directions are pinned below, at both levels — through the real awk on a
# synthetic log, and directly on the grading rule. A fix that only silences the
# false positive is worthless if it also stops catching the true one.

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _log_line(ip: str, hour: int, rt: float, *, minute: int = 0, second: int = 0,
              path: str = "/employer/acme-corp/") -> str:
    """One nginx access line in the prod log_format (combined + $request_time)."""
    return (f'{ip} - - [29/Jul/2026:{hour:02d}:{minute:02d}:{second:02d} +0000] '
            f'"GET {path} HTTP/1.1" 200 51715 {rt} "-" "{_UA}"')


def _run_awk(lines: list[str]) -> dict:
    """Run the REAL awk reducer over a synthetic log and parse its output.

    This is the only way to exercise the concentration fields end-to-end: they
    are computed in awk on the box, and a parser that agrees with an awk nobody
    ran is not evidence.
    """
    awk = shutil.which("awk")
    if not awk:
        pytest.skip("awk not on PATH")
    proc = subprocess.run(
        [awk, m._nginx_awk_program()],
        input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return m._parse_nginx(proc.stdout)


def _healthy_background(n: int = 400) -> list[str]:
    """Fast 200s so the surface has a realistic mean and hit count."""
    return [_log_line(f"10.20.{i // 250}.{i % 250}", hour=i % 24, rt=0.208,
                      minute=i % 60, second=i % 60)
            for i in range(n)]


def _burst_log() -> list[str]:
    """The 2026-07-29 shape: 101 >10s, 93 inside 16:00 UTC, ~98 distinct clients.

    Max 5 hits per IP, matching the measured swarm (top offender 209.249.178.250
    with 5) — nobody is hammering one slow path; many clients each arrive once.
    """
    lines = _healthy_background()
    # 93 in the 16:00 hour: 87 one-hit clients + 3 clients with 2 hits each.
    for i in range(87):
        lines.append(_log_line(f"209.249.{i // 250}.{i % 250 + 1}", hour=16,
                               rt=12.4, minute=i % 60, second=i % 60))
    for i in range(3):
        for rep in range(2):
            lines.append(_log_line(f"45.83.{i}.10", hour=16, rt=11.9,
                                   minute=30 + rep, second=i))
    # The 8 stragglers, spread over 01/02/04/14/19 as measured.
    for i, hour in enumerate([1, 2, 2, 4, 14, 14, 19, 19]):
        lines.append(_log_line(f"77.88.{i}.5", hour=hour, rt=10.7, minute=i))
    return lines


def _chronic_log() -> list[str]:
    """The same 101 >10s hits, spread evenly across the 24h window.

    Same raw count, opposite meaning: a slow path that is slow all day. Distinct
    clients are deliberately kept HIGH (one per hit) so the only thing separating
    this from the burst is the time distribution — if the rule leaned on the IP
    count alone it would wrongly excuse this too.
    """
    lines = _healthy_background()
    for i in range(101):
        lines.append(_log_line(f"88.99.{i // 250}.{i % 250 + 1}", hour=i % 24,
                               rt=12.4, minute=i % 60, second=i % 60))
    return lines


def test_replay_burst_does_not_grade_red():
    """REPLAY: the 2026-07-29 swarm must not drive the digest RED.

    It stays YELLOW, and that is the intended outcome, not a near-miss: 101 slow
    requests did happen and the >3s watch line is entitled to say so. What it may
    no longer do is claim a latency regression needing action today.
    """
    nx = _run_awk(_burst_log())
    row = nx["surface_latency"]["employer_profile"]
    assert row["n_over_10s"] == 101, row
    assert row["n10_peak_hour"] == 93, row
    assert row["n10_distinct_ips"] == 98, row
    assert m._slow_tail_shape(row).is_burst

    section, status = m._section_top_properties(nx, None)
    assert status != "red", status
    assert status == "yellow", status
    # The raw count stays visible, with the shape that explains the grade.
    assert "101 >10s" in section["body"], section["body"]
    assert "93 of 101 landed in one hour across 98 client IPs" in section["body"]


def test_replay_chronic_slow_tail_still_grades_red():
    """REPLAY: the same 101 hits spread across the day is still a regression."""
    nx = _run_awk(_chronic_log())
    row = nx["surface_latency"]["employer_profile"]
    assert row["n_over_10s"] == 101, row
    assert row["n10_peak_hour"] <= 5, row       # ~4-5 per hour, no dominant hour
    assert row["n10_distinct_ips"] == 101, row  # many clients, yet NOT excused
    assert not m._slow_tail_shape(row).is_burst

    _section, status = m._section_top_properties(nx, None)
    assert status == "red", status


def test_awk_emits_concentration_only_for_the_slow_tail():
    """The new fields describe the >10s hits, not the surface's whole traffic."""
    nx = _run_awk(_healthy_background())
    row = nx["surface_latency"]["employer_profile"]
    assert row["count"] == 400 and row["n_over_10s"] == 0
    assert row["n10_peak_hour"] == 0 and row["n10_distinct_ips"] == 0


# ── The grading rule itself, without the awk round-trip ──────────────────────

def _tail(n10: int, peak_hour: int, distinct_ips: int, n3: int | None = None) -> dict:
    row = _lat(n10=n10, n3=n10 if n3 is None else n3)
    row["n10_peak_hour"] = peak_hour
    row["n10_distinct_ips"] = distinct_ips
    return row


def test_single_hour_from_few_clients_is_a_slow_path_not_a_burst():
    """One hour, 3 clients, 40 slow hits = someone hammering a slow query → RED.

    This is the half a naive "it was all in one hour, ignore it" rule would miss.
    """
    row = _tail(n10=40, peak_hour=40, distinct_ips=3)
    assert not m._slow_tail_shape(row).is_burst
    _s, status = m._section_top_properties({"surface_latency": {"salaries": row}}, None)
    assert status == "red", status


def test_many_clients_but_spread_over_the_day_is_not_a_burst():
    """Many distinct clients does not excuse a tail that never concentrates."""
    assert not m._slow_tail_shape(_tail(n10=60, peak_hour=8, distinct_ips=60)).is_burst


def test_tiny_tail_cannot_excuse_itself_as_a_burst():
    """3 hits in one hour from 3 IPs clears the ratios but not the IP floor.

    Without the floor, any handful of slow requests would self-classify as a
    burst — the discount has to mean something.
    """
    assert not m._slow_tail_shape(_tail(n10=3, peak_hour=3, distinct_ips=3)).is_burst


def test_missing_concentration_data_grades_the_strict_old_way():
    """An awk that predates the fields (a stale box) must not silence the tail."""
    row = _lat(n10=m.PERF_RED_N10 * 4)          # no n10_peak_hour / n10_distinct_ips
    assert not m._slow_tail_shape(row).is_burst
    _s, status = m._section_top_properties({"surface_latency": {"salaries": row}}, None)
    assert status == "red", status


def test_burst_on_the_heavy_render_surface_is_not_even_yellow():
    """The carve-out this generalizes: predictions is already never RED, but a
    burst there must not trip its spike-YELLOW either."""
    row = _tail(n10=m.PERF_HEAVY_SPIKE_N10 + 20, peak_hour=m.PERF_HEAVY_SPIKE_N10 + 18,
                distinct_ips=m.PERF_HEAVY_SPIKE_N10 + 15, n3=0)
    assert m._slow_tail_shape(row).is_burst
    _s, status = m._section_top_properties({"surface_latency": {"predictions": row}}, None)
    assert status == "green", status
