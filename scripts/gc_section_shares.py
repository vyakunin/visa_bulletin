#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp"]
# ///
"""Full-coverage GoatCounter section/path traffic shares for visa-bulletin.us.

WHY THIS EXISTS — never analyze from a top-100 query (see
`~/.claude/rules/complete_data_queries.md` + `.claude/rules/analytics.md`).
GoatCounter's `/stats/hits` endpoint is server-side capped at 100 paths
regardless of `limit`, which on visa-bulletin.us silently drops ~1,000+
long-tail paths (every individual `/employer/<slug>/` and `/job-title/<slug>/`
profile page) — i.e. exactly the surfaces a section-share breakdown is about.
A top-100 sum reported as a section breakdown UNDERSTATES the profile tail and
OVERSTATES the dashboard. This script is the committed full-coverage path so
ad-hoc breakdowns stop reaching for the capped `?limit=` query.

HOW — reuses the daily_checkup MCP's proven, full-coverage machinery so there
is ONE source of truth for the export pull + filtering + surface buckets (no
pattern drift):
  - `_gc_export_full_csv`  : pull (and 6h-cache) the full `/api/v0/export` CSV
                             — every hit, 100% coverage, NOT top-100.
  - `_aggregate_csv_path_counts` : Bot=0, FirstVisit=1 (matches /stats/total),
                                   Event=0 (drop ad/affiliate beacons),
                                   query-strip + slash-canonicalize.
  - `_bucket_path` / `SURFACE_LABELS` : the same surface taxonomy the digest uses.

INPUTS  : GoatCounter token at ~/tokens/goatcounter.token (read by the MCP).
OUTPUTS : prints a full-coverage section-share table + grand total + the exact
          number of pageviews/paths a top-100 query WOULD have dropped (so the
          truncation cost is always visible). Exit 0 on success, 2 if the
          export is unavailable (so a caller can tell "no data" from "0 data").

USAGE :
  uv run scripts/gc_section_shares.py                  # this_7d (default)
  uv run scripts/gc_section_shares.py --window last_28d
  uv run scripts/gc_section_shares.py --start 2026-06-01 --end 2026-06-16
  uv run scripts/gc_section_shares.py --paths            # also list top tail paths

Cross-ref: platform `monetization/affiliate_epv_reconcile.py` is the OTHER
full-coverage GC path — chunked `include_paths` for a KNOWN path set (affiliate
SubIds). Use that when you already know the paths; use THIS (export CSV) for an
open-ended breakdown over unknown long-tail paths.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import csv as csvm
import gzip
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

# Reuse the MCP's full-coverage machinery verbatim — single source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
from daily_checkup_server import (  # noqa: E402
    SURFACE_LABELS,
    _aggregate_csv_path_counts,
    _bucket_path,
    _gc_export_full_csv,
    _gc_export_max_ts,
)

WINDOWS = ("this_7d", "prev_7d", "cycle_7d", "last_28d")


def _resolve_window(name: str, anchor: date) -> tuple[date, date]:
    if name == "this_7d":
        return anchor - timedelta(days=6), anchor
    if name == "prev_7d":
        end = anchor - timedelta(days=7)
        return end - timedelta(days=6), end
    if name == "cycle_7d":
        end = anchor - timedelta(days=28)
        return end - timedelta(days=6), end
    if name == "last_28d":
        return anchor - timedelta(days=27), anchor
    raise ValueError(f"unknown window {name!r}")


async def _load_csv() -> Path | None:
    async with httpx.AsyncClient() as client:
        return await _gc_export_full_csv(client)


def _raw_pageviews(csv_path: Path, start: date, end: date) -> int:
    """All-visit (not FirstVisit-deduped) page-hits — for the top-100-loss math
    against the same basis a naive /stats/hits sum would use."""
    raw = csv_path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("2Path,"):
        text = text[1:]
    n = 0
    for row in csvm.DictReader(io.StringIO(text)):
        rd = (row.get("Date") or "")[:10]
        try:
            d = date.fromisoformat(rd)
        except ValueError:
            continue
        if (row.get("Bot") or "0") != "0":
            continue
        if (row.get("Event") or "0") not in ("0", ""):
            continue
        if start <= d <= end:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", choices=WINDOWS, default="this_7d")
    ap.add_argument("--start", help="ISO date; overrides --window with --end")
    ap.add_argument("--end", help="ISO date; overrides --window with --start")
    ap.add_argument("--paths", action="store_true",
                    help="also print the top long-tail paths the cap would drop")
    args = ap.parse_args()

    csv_path = asyncio.run(_load_csv())
    if csv_path is None or not csv_path.exists():
        print("GC export unavailable (no cache, export rate-limited/failed). "
              "Per complete_data_queries.md, NOT falling back to top-100.",
              file=sys.stderr)
        return 2

    cutoff_ts = _gc_export_max_ts(csv_path)
    cutoff = cutoff_ts.date() if cutoff_ts else date.today()
    anchor = cutoff - timedelta(days=1)  # last COMPLETE day (today is partial)

    if args.start and args.end:
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
        label = f"{start}..{end}"
    else:
        start, end = _resolve_window(args.window, anchor)
        label = f"{args.window} {start}..{end}"

    counts = collections.Counter(
        _aggregate_csv_path_counts(csv_path, [("w", start, end)])["w"]
    )
    total = sum(counts.values())
    if total == 0:
        print(f"No pageviews in window {label} (export cutoff {cutoff}).")
        return 0

    surf = collections.Counter()
    surf_pages = collections.defaultdict(set)
    for path, cnt in counts.items():
        b = _bucket_path(path)
        surf[b] += cnt
        surf_pages[b].add(path)

    print(f"GoatCounter full-coverage section shares — {label}")
    print(f"(export cutoff {cutoff}; FirstVisit pageviews, bots+events excluded)")
    print(f"100% coverage: {total} pageviews across {len(counts)} distinct paths\n")
    print(f"  {'surface':22s} {'views':>7s} {'share':>6s}  pages   label")
    for key, v in surf.most_common():
        print(f"  {key:22s} {v:7d} {v / total * 100:5.1f}%  {len(surf_pages[key]):5d}   "
              f"{SURFACE_LABELS.get(key, key)}")

    # Make the truncation cost explicit — what a top-100 query would have lost.
    top100 = sum(c for _, c in counts.most_common(100))
    dropped = total - top100
    print(f"\nTop-100 cap would report {top100} = {top100 / total * 100:.1f}% of "
          f"pageviews,\n  dropping {dropped} views across {max(0, len(counts) - 100)} "
          f"long-tail paths (employer/job-title profiles). Do NOT use it for shares.")

    if args.paths:
        ranked = counts.most_common()
        print("\nLong-tail paths beyond the top-100 cap (next 30):")
        for path, c in ranked[100:130]:
            print(f"  {c:5d}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
