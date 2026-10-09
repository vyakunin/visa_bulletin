#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp>=1.0.0,<2", "matplotlib>=3.8"]
# ///
"""The daily digest's per-surface traffic: daily pageviews over time, one panel per surface.

Each panel plots readers' 7-day and 28-day trailing averages over the daily count, with the
headless-Chrome scraper (the provenance script's farm fingerprint) as a band stacked on the
7-day reader line. Panel titles carry the raw 7d numbers. Reads the daily_checkup MCP's
cached full GoatCounter export (FirstVisit=1, the digest's basis) through its surface
buckets. Exit 2 when the export is unavailable.

Usage
  uv run scripts/daily_checkup_charts.py                    # writes $TMPDIR/vb_digest/surfaces.png
  uv run scripts/daily_checkup_charts.py --days 180 --out /path/x.png --json
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
    SURFACE_LABELS,
    _bucket_path,
    _gc_export_full_csv,
    _gc_export_max_ts,
    _humanize,
)
from gc_traffic_provenance import _is_farm, _read_rows  # noqa: E402

# Buckets that are beacons or plumbing, not pages a reader opened.
NOT_PAGEVIEWS = frozenset({"donation_click", "api", "static_meta"})

SHORT_AVG_DAYS = 7
LONG_AVG_DAYS = 28
DEFAULT_PLOT_DAYS = 120
PANEL_COLUMNS = 2

SURFACE_BG = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3dd"
READERS = "#2a78d6"
READERS_DAILY = "#a9c9ef"
SCRAPER = "#c3c2b7"


@dataclass(frozen=True)
class SurfaceWeek:
    surface: str
    name: str
    path: str
    views: int
    scraper: int
    readers: int
    prev_week: int
    four_weeks_ago: int
    share_pct: float
    pages: int
    mom: str
    wow: str


@dataclass(frozen=True)
class SurfaceSeries:
    week: SurfaceWeek
    days: list[date]
    readers: list[int]
    scraper: list[int]


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


def collect(csv_path: Path, anchor: date, plot_days: int) -> list[SurfaceSeries]:
    first = anchor - timedelta(days=plot_days + LONG_AVG_DAYS - 2)
    week_start = anchor - timedelta(days=6)
    readers: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    scraper: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
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
        if surface in NOT_PAGEVIEWS:
            continue
        (scraper if _is_farm(row) else readers)[surface][d] += 1
        if d >= week_start:
            pages[surface].add(path)
    days = [first + timedelta(days=i) for i in range((anchor - first).days + 1)]
    surfaces = set(readers) | set(scraper)
    total = sum(_window_sum(readers[s], anchor) + _window_sum(scraper[s], anchor)
                for s in surfaces)
    out = []
    for s in surfaces:
        r_week, f_week = _window_sum(readers[s], anchor), _window_sum(scraper[s], anchor)
        views = r_week + f_week
        if not views:
            continue
        prev = (_window_sum(readers[s], anchor - timedelta(days=7))
                + _window_sum(scraper[s], anchor - timedelta(days=7)))
        cycle = (_window_sum(readers[s], anchor - timedelta(days=28))
                 + _window_sum(scraper[s], anchor - timedelta(days=28)))
        name, url = _name_and_path(s)
        week = SurfaceWeek(
            surface=s, name=name, path=url, views=views, scraper=f_week, readers=r_week,
            prev_week=prev, four_weeks_ago=cycle,
            share_pct=round(views / total * 100, 1), pages=len(pages[s]),
            mom=_pct(views, cycle), wow=_pct(views, prev),
        )
        out.append(SurfaceSeries(
            week=week, days=days,
            readers=[readers[s].get(d, 0) for d in days],
            scraper=[scraper[s].get(d, 0) for d in days],
        ))
    out.sort(key=lambda x: -x.week.views)
    return out


def _panel(ax, series: SurfaceSeries, plot_days: int) -> None:
    lead = len(series.days) - plot_days
    days = series.days[lead:]
    daily = series.readers[lead:]
    short = trailing_mean(series.readers, SHORT_AVG_DAYS)[lead:]
    long = trailing_mean(series.readers, LONG_AVG_DAYS)[lead:]
    farm = trailing_mean(series.scraper, SHORT_AVG_DAYS)[lead:]
    ax.set_facecolor(SURFACE_BG)
    ax.plot(days, daily, color=READERS_DAILY, linewidth=0.6)
    if any(series.scraper[lead:]):
        ax.fill_between(days, short, [a + b for a, b in zip(short, farm)],
                        color=SCRAPER, linewidth=0)
    ax.plot(days, short, color=READERS, linewidth=1.6)
    ax.plot(days, long, color=INK, linewidth=1.1)
    w = series.week
    ax.set_title(f"{w.name}  {w.path}", loc="left", fontsize=6.6, color=INK, pad=11)
    ax.text(0, 1.015,
            f"7d {_humanize(w.views)} · readers {_humanize(w.readers)} · {w.share_pct:.0f}% · "
            f"4w ago {_humanize(w.four_weeks_ago)} ({w.mom}) · "
            f"last wk {_humanize(w.prev_week)} ({w.wow})",
            transform=ax.transAxes, fontsize=5.4, color=INK_2, va="bottom")
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _humanize(v)))
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3, integer=True))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.tick_params(labelsize=5.4, colors=INK_2, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)


def render(rows: list[SurfaceSeries], anchor: date, plot_days: int, out: Path) -> None:
    total = sum(r.week.views for r in rows)
    readers = sum(r.week.readers for r in rows)
    n_rows = math.ceil(len(rows) / PANEL_COLUMNS)
    fig, axes = plt.subplots(n_rows, PANEL_COLUMNS, figsize=(7.2, 1.35 * n_rows + 0.8),
                             dpi=200, sharex=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE_BG)
    for ax, series in zip(axes.flat, rows):
        _panel(ax, series, plot_days)
    for ax in list(axes.flat)[len(rows):]:
        ax.set_visible(False)
    for ax in axes.flat:
        ax.xaxis.set_tick_params(labelbottom=True)
    start = anchor - timedelta(days=6)
    fig.suptitle(f"Daily pageviews by surface, last {plot_days} days to {anchor:%b %d}. "
                 f"Week {start:%b %d}–{anchor:%b %d}: {_humanize(total)} "
                 f"({_humanize(readers)} readers). Each panel has its own scale.",
                 x=0.02, ha="left", fontsize=7.6, color=INK, y=0.997)
    handles = [
        matplotlib.lines.Line2D([], [], color=READERS_DAILY, linewidth=0.8, label="readers, daily"),
        matplotlib.lines.Line2D([], [], color=READERS, linewidth=1.6,
                                label=f"readers, {SHORT_AVG_DAYS}d avg"),
        matplotlib.lines.Line2D([], [], color=INK, linewidth=1.1,
                                label=f"readers, {LONG_AVG_DAYS}d avg"),
        matplotlib.patches.Patch(color=SCRAPER,
                                 label=f"headless-Chrome scraper, {SHORT_AVG_DAYS}d avg"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, 0.985), ncol=4,
               frameon=False, fontsize=5.8, labelcolor=INK)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.5 / (1.35 * n_rows + 0.8)), h_pad=1.4, w_pad=1.6)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE_BG)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path,
                    default=Path(tempfile.gettempdir()) / "vb_digest" / "surfaces.png")
    ap.add_argument("--end", help="ISO date anchor; default = last COMPLETE day in the export")
    ap.add_argument("--days", type=int, default=DEFAULT_PLOT_DAYS,
                    help=f"days on the x axis (default {DEFAULT_PLOT_DAYS})")
    ap.add_argument("--json", action="store_true", help="also print the 7d rows as JSON")
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
    rows = collect(csv_path, anchor, args.days)
    render(rows, anchor, args.days, args.out)
    if args.json:
        print(json.dumps({"anchor": str(anchor), "rows": [asdict(r.week) for r in rows]},
                         indent=1))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
