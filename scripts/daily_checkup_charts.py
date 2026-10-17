#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp>=1.0.0,<2", "matplotlib>=3.8"]
# ///
"""The daily digest's charts, one PNG per graph.

Readers: one chart for all readers, then one per surface, each plotting daily readers with
their 7-day and 28-day trailing averages. The headless-Chrome scraper and the 2026-07-27..29
Singapore burst (the provenance script's farm and sgwave fingerprints) are excluded
everywhere: no series, no total, no share. Reads the daily_checkup MCP's cached full
GoatCounter export (FirstVisit=1, the digest's basis) through its surface buckets.

GA4: one chart per watched landing surface (the MCP's GA4_SURFACES), daily sessions and
engaged sessions, ending at the last finalized GA4 day. Organic Search only, except the
surfaces in ALL_CHANNEL_PREFIXES, which chart every channel.

Titles carry the raw 7d numbers. Exit 2 when the GoatCounter export is unavailable; a GA4
failure drops only the GA4 charts and is reported as `ga4_error`.

Usage
  uv run scripts/daily_checkup_charts.py                    # writes $TMPDIR/vb_digest/*.png
  uv run scripts/daily_checkup_charts.py --days 180 --out-dir /path --json
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
from daily_checkup_server import (  # noqa: E402
    GA4_FINALIZED_ROW_AGE_DAYS,
    GA4_PROPERTY_ID,
    GA4_SURFACES,
    GA4_TIMEOUT,
    SURFACE_LABELS,
    _bucket_path,
    _gc_export_full_csv,
    _gc_export_max_ts,
    _humanize,
    call_mcp_tools,
)
from gc_traffic_provenance import _is_farm, _is_sgwave, _read_rows  # noqa: E402

# Buckets that are beacons or plumbing, not pages a reader opened.
NOT_PAGEVIEWS = frozenset({"donation_click", "api", "static_meta"})

SHORT_AVG_DAYS = 7
LONG_AVG_DAYS = 28
DEFAULT_PLOT_DAYS = 120
ALL_READERS = "all"

SURFACE_BG = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3dd"
READERS = "#2a78d6"
READERS_DAILY = "#a9c9ef"
ENGAGED = "#eb6834"
ENGAGED_DAILY = "#f6b99f"

# The Cloudflare challenge on these surfaces reloads the page and strips the referrer, so a
# Google visitor lands in GA4 as Direct; an organic-only chart reads ~0 since 2026-07-28.
ALL_CHANNEL_PREFIXES = frozenset({"/job-title/", "/employer/"})


@dataclass(frozen=True)
class SurfaceWeek:
    surface: str
    name: str
    path: str
    readers: int
    readers_prev_week: int
    readers_four_weeks_ago: int
    share_pct: float
    pages: int
    mom: str
    wow: str


@dataclass(frozen=True)
class SurfaceSeries:
    week: SurfaceWeek
    days: list[date]
    readers: list[int]


@dataclass(frozen=True)
class Ga4Week:
    label: str
    channel: str
    sessions: int
    engaged: int
    engaged_time_s: float
    sessions_prev_week: int
    engaged_prev_week: int
    engaged_time_prev_week_s: float
    last_day: date


@dataclass(frozen=True)
class Ga4Series:
    week: Ga4Week
    days: list[date]
    sessions: list[int]
    engaged: list[int]


def _name_and_path(surface: str) -> tuple[str, str]:
    label = SURFACE_LABELS.get(surface, surface)
    name, _, rest = label.partition("`")
    path = rest.split("`", 1)[0] if rest else ""
    return name.strip(), path


def _pct(cur: int, base: int) -> str:
    return f"{(cur - base) / base * 100:+.0f}%" if base else "new"


def _window_sum(daily: dict[date, int], end: date, days: int = 7) -> int:
    return sum(daily.get(end - timedelta(days=i), 0) for i in range(days))


def trailing_mean(values: list[int], window: int) -> list[float]:
    """Mean of the `window` values ending at each index; NaN until a full window exists."""
    out, run = [], 0
    for i, v in enumerate(values):
        run += v
        if i >= window:
            run -= values[i - window]
        out.append(run / window if i >= window - 1 else math.nan)
    return out


def _series(surface: str, daily: dict[date, int], days: list[date], anchor: date,
            pages: int, total: int) -> SurfaceSeries:
    r_week = _window_sum(daily, anchor)
    prev = _window_sum(daily, anchor - timedelta(days=7))
    cycle = _window_sum(daily, anchor - timedelta(days=28))
    name, url = _name_and_path(surface)
    week = SurfaceWeek(
        surface=surface, name=name, path=url, readers=r_week,
        readers_prev_week=prev, readers_four_weeks_ago=cycle,
        share_pct=round(r_week / total * 100, 1) if total else 0.0, pages=pages,
        mom=_pct(r_week, cycle), wow=_pct(r_week, prev),
    )
    return SurfaceSeries(week=week, days=days, readers=[daily.get(d, 0) for d in days])


def collect(csv_path: Path, anchor: date, plot_days: int) -> list[SurfaceSeries]:
    first = anchor - timedelta(days=plot_days + LONG_AVG_DAYS - 2)
    week_start = anchor - timedelta(days=6)
    readers: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pages: dict[str, set[str]] = collections.defaultdict(set)
    for row in _read_rows(csv_path):
        if (row.get("FirstVisit") or "0") != "1":
            continue
        try:
            d = date.fromisoformat((row.get("Date") or "")[:10])
        except ValueError:
            continue
        if not first <= d <= anchor:
            continue
        path = (row.get("Path") or "").split("?", 1)[0].rstrip("/") or "/"
        surface = _bucket_path(path)
        if surface in NOT_PAGEVIEWS or _is_farm(row) or _is_sgwave(row):
            continue
        readers[surface][d] += 1
        if d >= week_start:
            pages[surface].add(path)
    days = [first + timedelta(days=i) for i in range((anchor - first).days + 1)]
    total = sum(_window_sum(readers[s], anchor) for s in readers)
    out = [_series(s, readers[s], days, anchor, len(pages[s]), total)
           for s in readers if _window_sum(readers[s], anchor)]
    out.sort(key=lambda x: -x.week.readers)
    return out


def all_readers(rows: list[SurfaceSeries]) -> SurfaceSeries:
    """The site-wide series: every surface's daily readers summed."""
    days = rows[0].days
    daily = {d: sum(r.readers[i] for r in rows) for i, d in enumerate(days)}
    s = _series(ALL_READERS, daily, days, days[-1], sum(r.week.pages for r in rows),
                sum(r.week.readers for r in rows))
    week = SurfaceWeek(**{**asdict(s.week), "name": "All readers", "path": ""})
    return SurfaceSeries(week=week, days=s.days, readers=s.readers)


def totals(weeks: list[SurfaceWeek]) -> dict[str, int | str]:
    """The digest's headline: readers with their MoM/WoW."""
    readers = sum(w.readers for w in weeks)
    prev = sum(w.readers_prev_week for w in weeks)
    cycle = sum(w.readers_four_weeks_ago for w in weeks)
    return {"readers": readers, "readers_prev_week": prev, "readers_four_weeks_ago": cycle,
            "mom": _pct(readers, cycle), "wow": _pct(readers, prev)}


def _ga4_channel(prefix: str | None) -> str:
    return "all channels" if prefix in ALL_CHANNEL_PREFIXES else "organic"


def _ga4_daily_args(prefix: str | None, start: date, end: date) -> dict:
    expressions = []
    if _ga4_channel(prefix) == "organic":
        expressions.append({"filter": {"fieldName": "sessionDefaultChannelGroup",
                                       "stringFilter": {"value": "Organic Search"}}})
    if prefix is not None:
        expressions.append({"filter": {"fieldName": "landingPage",
                                       "stringFilter": {"matchType": "BEGINS_WITH",
                                                        "value": prefix}}})
    return {
        "property_id": GA4_PROPERTY_ID,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "dimensions": ["date"],
        "metrics": ["sessions", "engagedSessions", "userEngagementDuration"],
        "dimension_filter": expressions[0] if len(expressions) == 1
        else {"andGroup": {"expressions": expressions}},
        "row_limit": 1000,
    }


def collect_ga4(end: date, plot_days: int) -> list[Ga4Series]:
    """Daily sessions per GA4 watched surface, ending at the last finalized day."""
    start = end - timedelta(days=plot_days + SHORT_AVG_DAYS - 2)
    calls = [("ga4_run_report", _ga4_daily_args(prefix, start, end)) for _, prefix in GA4_SURFACES]
    reports = asyncio.run(call_mcp_tools("ga4", calls, timeout=GA4_TIMEOUT))
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    out = []
    for (label, prefix), report in zip(GA4_SURFACES, reports):
        by_day = {date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:])): r
                  for r in (report or {}).get("rows") or []}

        def metric(d: date, name: str) -> float:
            return float((by_day.get(d) or {}).get(name) or 0)

        def week(first_back: int, name: str) -> float:
            return sum(metric(end - timedelta(days=first_back + i), name) for i in range(7))

        out.append(Ga4Series(
            week=Ga4Week(
                label=label, channel=_ga4_channel(prefix), last_day=end,
                sessions=int(week(0, "sessions")), engaged=int(week(0, "engagedSessions")),
                engaged_time_s=week(0, "userEngagementDuration"),
                sessions_prev_week=int(week(7, "sessions")),
                engaged_prev_week=int(week(7, "engagedSessions")),
                engaged_time_prev_week_s=week(7, "userEngagementDuration"),
            ),
            days=days,
            sessions=[int(metric(d, "sessions")) for d in days],
            engaged=[int(metric(d, "engagedSessions")) for d in days],
        ))
    return out


def _style(ax) -> None:
    ax.set_facecolor(SURFACE_BG)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _humanize(v)))
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4, integer=True))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.tick_params(labelsize=7, colors=INK_2, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)


def _figure(title: str, subtitle: str):
    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=200)
    fig.patch.set_facecolor(SURFACE_BG)
    fig.text(0.02, 0.965, title, fontsize=10, color=INK, va="top", weight="bold")
    fig.text(0.02, 0.895, subtitle, fontsize=7.4, color=INK_2, va="top")
    return fig, ax


def _save(fig, ax, handles, out: Path) -> None:
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, 1.09), ncol=len(handles),
              frameon=False, fontsize=7, labelcolor=INK, borderaxespad=0)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    fig.savefig(out, facecolor=SURFACE_BG)
    plt.close(fig)


def _line(color: str, width: float, label: str):
    return matplotlib.lines.Line2D([], [], color=color, linewidth=width, label=label)


def render_readers(series: SurfaceSeries, plot_days: int, out: Path) -> None:
    lead = len(series.days) - plot_days
    days = series.days[lead:]
    w = series.week
    title = f"{w.name}  {w.path}".strip()
    subtitle = (f"7d to {days[-1]:%b %d}: {_humanize(w.readers)} readers · "
                f"4w ago {_humanize(w.readers_four_weeks_ago)} ({w.mom} MoM) · "
                f"last wk {_humanize(w.readers_prev_week)} ({w.wow} WoW)")
    if w.surface != ALL_READERS:
        subtitle += f" · {w.share_pct:.0f}% of readers"
    fig, ax = _figure(title, subtitle)
    ax.plot(days, series.readers[lead:], color=READERS_DAILY, linewidth=0.7)
    ax.plot(days, trailing_mean(series.readers, SHORT_AVG_DAYS)[lead:], color=READERS,
            linewidth=2)
    ax.plot(days, trailing_mean(series.readers, LONG_AVG_DAYS)[lead:], color=INK,
            linewidth=1.3)
    _style(ax)
    _save(fig, ax, [_line(READERS_DAILY, 0.9, "daily"),
                    _line(READERS, 2, f"{SHORT_AVG_DAYS}d avg"),
                    _line(INK, 1.3, f"{LONG_AVG_DAYS}d avg")], out)


def _rate(engaged: int, sessions: int) -> str:
    return f"{engaged / sessions * 100:.0f}%" if sessions else "n/a"


def _per_visit(seconds: float, sessions: int) -> str:
    return f"{seconds / sessions:.0f}s" if sessions else "n/a"


def render_ga4(series: Ga4Series, plot_days: int, out: Path) -> None:
    lead = len(series.days) - plot_days
    days = series.days[lead:]
    w = series.week
    subtitle = (f"7d to {w.last_day:%b %d} (last final GA4 day): "
                f"{_humanize(w.sessions)} sessions vs {_humanize(w.sessions_prev_week)} · "
                f"engaged {_rate(w.engaged, w.sessions)} vs "
                f"{_rate(w.engaged_prev_week, w.sessions_prev_week)} · "
                f"{_per_visit(w.engaged_time_s, w.sessions)} vs "
                f"{_per_visit(w.engaged_time_prev_week_s, w.sessions_prev_week)}/visit")
    fig, ax = _figure(f"GA4 {w.channel} landings  {w.label}", subtitle)
    ax.plot(days, series.sessions[lead:], color=READERS_DAILY, linewidth=0.7)
    ax.plot(days, series.engaged[lead:], color=ENGAGED_DAILY, linewidth=0.7)
    ax.plot(days, trailing_mean(series.sessions, SHORT_AVG_DAYS)[lead:], color=READERS,
            linewidth=2)
    ax.plot(days, trailing_mean(series.engaged, SHORT_AVG_DAYS)[lead:], color=ENGAGED,
            linewidth=2)
    _style(ax)
    _save(fig, ax, [_line(READERS_DAILY, 0.9, "sessions, daily"),
                    _line(READERS, 2, f"{SHORT_AVG_DAYS}d avg"),
                    _line(ENGAGED_DAILY, 0.9, "engaged, daily"),
                    _line(ENGAGED, 2, f"{SHORT_AVG_DAYS}d avg")], out)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text).strip("_") or "site"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=Path(tempfile.gettempdir()) / "vb_digest")
    ap.add_argument("--end", help="ISO date anchor; default = last COMPLETE day in the export")
    ap.add_argument("--days", type=int, default=DEFAULT_PLOT_DAYS,
                    help=f"days on the x axis (default {DEFAULT_PLOT_DAYS})")
    ap.add_argument("--json", action="store_true",
                    help="print the 7d totals, rows, GA4 weeks and chart paths as JSON")
    args = ap.parse_args()

    async def _load():
        async with httpx.AsyncClient() as client:
            return await _gc_export_full_csv(client)

    csv_path = asyncio.run(_load())
    if csv_path is None or not csv_path.exists():
        print("GC export unavailable — no chart (never falls back to top-100).", file=sys.stderr)
        return 2
    cutoff_ts = _gc_export_max_ts(csv_path)
    cutoff = cutoff_ts.date() if cutoff_ts else date.today()
    anchor = date.fromisoformat(args.end) if args.end else cutoff - timedelta(days=1)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.out_dir.glob("*.png"):
        stale.unlink()
    rows = collect(csv_path, anchor, args.days)
    charts: list[Path] = []
    for i, series in enumerate([all_readers(rows), *rows]):
        out = args.out_dir / f"{i:02d}_{series.week.surface}.png"
        render_readers(series, args.days, out)
        charts.append(out)

    ga4_weeks, ga4_error = [], None
    ga4_end = min(anchor, date.today() - timedelta(days=GA4_FINALIZED_ROW_AGE_DAYS))
    try:
        for i, series in enumerate(collect_ga4(ga4_end, args.days)):
            out = args.out_dir / f"ga4_{i}_{_slug(series.week.label)}.png"
            render_ga4(series, args.days, out)
            charts.append(out)
            ga4_weeks.append(series.week)
    except Exception as e:  # noqa: BLE001 — GA4 failure drops only the GA4 charts
        ga4_error = f"{type(e).__name__}: {e}"
        print(f"ga4 charts skipped: {ga4_error}", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "anchor": str(anchor), "totals": totals([r.week for r in rows]),
            "rows": [asdict(r.week) for r in rows],
            "ga4": [asdict(w) for w in ga4_weeks], "ga4_error": ga4_error,
            "charts": [str(c) for c in charts],
        }, indent=1, default=str))
    else:
        print("\n".join(str(c) for c in charts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
