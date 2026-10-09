#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp>=1.0.0,<2", "matplotlib>=3.8"]
# ///
"""The daily digest's per-surface traffic chart: 7d pageviews split into readers and scraper.

Reads the daily_checkup MCP's cached full GoatCounter export (FirstVisit=1, the digest's
basis) through its surface buckets and the provenance script's farm fingerprint. Each row
carries its raw numbers. Exit 2 when the export is unavailable.

Usage
  uv run scripts/daily_checkup_charts.py                    # writes $TMPDIR/vb_digest/surfaces.png
  uv run scripts/daily_checkup_charts.py --out /path/x.png --json
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
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

SURFACE_BG = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
READERS = "#2a78d6"
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


def _name_and_path(surface: str) -> tuple[str, str]:
    label = SURFACE_LABELS.get(surface, surface)
    name, _, rest = label.partition("`")
    path = rest.split("`", 1)[0] if rest else ""
    return name.strip(), path


def _pct(cur: int, base: int) -> str:
    return f"{(cur - base) / base * 100:+.0f}%" if base else "new"


def collect(csv_path: Path, anchor: date) -> list[SurfaceWeek]:
    windows = {
        "this": (anchor - timedelta(days=6), anchor),
        "prev": (anchor - timedelta(days=13), anchor - timedelta(days=7)),
        "cycle": (anchor - timedelta(days=34), anchor - timedelta(days=28)),
    }
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pages: dict[str, set[str]] = collections.defaultdict(set)
    for row in _read_rows(csv_path):
        if (row.get("FirstVisit") or "0") != "1":
            continue
        try:
            d = date.fromisoformat((row.get("Date") or "")[:10])
        except ValueError:
            continue
        path = (row.get("Path") or "").split("?", 1)[0].rstrip("/") or "/"
        surface = _bucket_path(path)
        if surface in NOT_PAGEVIEWS:
            continue
        for win, (start, end) in windows.items():
            if start <= d <= end:
                counts[surface][win] += 1
                if win == "this":
                    pages[surface].add(path)
                    if _is_farm(row):
                        counts[surface]["farm"] += 1
    total = sum(c["this"] for c in counts.values())
    rows = []
    for surface, c in counts.items():
        if not c["this"]:
            continue
        name, url = _name_and_path(surface)
        rows.append(SurfaceWeek(
            surface=surface, name=name, path=url,
            views=c["this"], scraper=c["farm"], readers=c["this"] - c["farm"],
            prev_week=c["prev"], four_weeks_ago=c["cycle"],
            share_pct=round(c["this"] / total * 100, 1),
            pages=len(pages[surface]),
            mom=_pct(c["this"], c["cycle"]), wow=_pct(c["this"], c["prev"]),
        ))
    rows.sort(key=lambda r: -r.views)
    return rows


def render(rows: list[SurfaceWeek], anchor: date, out: Path) -> None:
    total = sum(r.views for r in rows)
    readers = sum(r.readers for r in rows)
    n = len(rows)
    fig, ax = plt.subplots(figsize=(7.2, 0.62 * n + 1.0), dpi=200)
    fig.patch.set_facecolor(SURFACE_BG)
    ax.set_facecolor(SURFACE_BG)
    peak = max(max(r.views, r.four_weeks_ago) for r in rows)
    y = list(range(n))[::-1]
    for yi, r in zip(y, rows):
        ax.barh(yi, r.readers, height=0.5, color=READERS, edgecolor=SURFACE_BG, linewidth=1)
        ax.barh(yi, r.scraper, left=r.readers, height=0.5, color=SCRAPER,
                edgecolor=SURFACE_BG, linewidth=1)
        ax.plot([r.four_weeks_ago] * 2, [yi - 0.32, yi + 0.32], color=INK, linewidth=1.5)
        x = max(r.views, r.four_weeks_ago) + peak * 0.02
        ax.text(x, yi + 0.12,
                f"{_humanize(r.views)} · readers {_humanize(r.readers)} · "
                f"{r.share_pct:.0f}% · {r.pages:,}p",
                va="center", fontsize=7, color=INK)
        ax.text(x, yi - 0.2,
                f"4w ago {_humanize(r.four_weeks_ago)} ({r.mom}) · "
                f"last wk {_humanize(r.prev_week)} ({r.wow})",
                va="center", fontsize=6.2, color=INK_2)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.name}\n{r.path}" if r.path else r.name for r in rows],
                       fontsize=6.6, color=INK)
    ax.set_xlim(0, peak * 1.95)
    ax.set_ylim(-0.7, n - 0.3)
    ax.tick_params(axis="x", labelsize=6, colors=INK_2, length=0)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _humanize(v)))
    ax.grid(axis="x", color="#e4e3dd", linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    start = anchor - timedelta(days=6)
    fig.suptitle(f"Pageviews by surface, {start:%b %d}–{anchor:%b %d}: "
                 f"{_humanize(total)} ({_humanize(readers)} readers)",
                 x=0.02, ha="left", fontsize=9.5, color=INK, y=0.995)
    handles = [
        matplotlib.patches.Patch(color=READERS, label="readers"),
        matplotlib.patches.Patch(color=SCRAPER, label="headless-Chrome scraper"),
        matplotlib.lines.Line2D([], [], color=INK, linewidth=1.5, label="4 weeks ago"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, 0.975), ncol=3,
               frameon=False, fontsize=6.8, labelcolor=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE_BG)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path,
                    default=Path(tempfile.gettempdir()) / "vb_digest" / "surfaces.png")
    ap.add_argument("--end", help="ISO date anchor; default = last COMPLETE day in the export")
    ap.add_argument("--json", action="store_true", help="also print the rows as JSON")
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
    rows = collect(csv_path, anchor)
    render(rows, anchor, args.out)
    if args.json:
        print(json.dumps({"anchor": str(anchor), "rows": [asdict(r) for r in rows]}, indent=1))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
