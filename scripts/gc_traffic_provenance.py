#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp>=1.0.0,<2"]
# ///
"""Weekly traffic PROVENANCE per surface — referrer mix + automated-client share.

WHY THIS EXISTS — `gc_section_shares.py` answers "how much traffic per surface".
It cannot answer "was that traffic a person", and on the profile surfaces
(`/job-title/<slug>/`, `/employer/<slug>/`) that difference is the whole story:
GoatCounter's own `Bot` column is 0 for 100% of rows there, so a headless-Chrome
farm that executes the JS beacon is counted as human by every other tool we have.
In the week to 2026-08-27, 80% of `/job-title/` and 44% of `/employer/`
pageviews carried the farm fingerprint below, against 1-7% on every human
surface. A trend read off the unsplit number is a trend in the farm.

TWO FINGERPRINTS, both measured, both overridable:
  farm   : System == "Linux" AND Screen size == "1920,0,1".
           Single-hit sessions, one browser build, hundreds of distinct
           long-tail profile paths. NOT simply "Linux users" — real Linux
           desktop traffic does not concentrate 80/44% on two surfaces and
           1-7% everywhere else, and that asymmetry is what the `--by-surface`
           column is for. Re-check it before trusting the split.
  sgwave : Location startswith "SG" AND Browser startswith "Chrome 145" —
           the 2026-07-24..30 Singapore burst, kept separate because it is a
           distinct, dated event that poisons any window overlapping it.

THE REFERRER COLUMN IS NOT EVIDENCE ON ITS OWN — cross-check against GSC.
A referrer is set by the client and can be forged. Measured 2026-08-28:
`Referrer=Google` on the profile surfaces ran 57x GSC's clicks for the same
pages in the same week (2,062 vs 36), while site-wide the same ratio was 1.2x
(21,237 vs 17,207). So the site-wide Google referrer is real and the profile
one was fabricated. The ratio IS the test:
    GC(Referrer=Google, surface) / GSC(clicks, page contains surface)
  ~1  => real organic.   >>1 => forged referrer; do not read it as discovery.
Pull the GSC side with `mcp__gsc__gsc_query_search_analytics`, dimension
`date`, dimension_filters page/contains/<surface>. This script prints the GC
half and the exact query to run for the other half.

INPUTS  : GoatCounter token at ~/tokens/goatcounter.token (read by the MCP).
          Reuses the daily_checkup MCP's cached full `/api/v0/export` CSV, so
          this is 100%-coverage — never the top-100 `/stats/hits` path
          (`~/.claude/rules/complete_data_queries.md`).
OUTPUTS : per-week, per-surface: the digest's own pageview number, the referrer
          mix, and the farm/sgwave/human split. Exit 0 ok, 2 if no export.

USAGE :
  uv run scripts/gc_traffic_provenance.py                      # profiles, 6 weeks
  uv run scripts/gc_traffic_provenance.py --weeks 9
  uv run scripts/gc_traffic_provenance.py --by-surface         # farm% every surface
  uv run scripts/gc_traffic_provenance.py --surface all --weeks 4
  uv run scripts/gc_traffic_provenance.py --end 2026-08-27     # pin the anchor
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
from daily_checkup_server import (  # noqa: E402
    _bucket_path,
    _gc_export_full_csv,
    _gc_export_max_ts,
)

# Referrers GoatCounter normalises to a bare engine name, plus the raw hosts.
SEARCH = {"Google", "google.com", "www.google.com", "Bing", "www.bing.com", "bing.com",
          "DuckDuckGo", "duckduckgo.com", "search.brave.com", "ecosia.org",
          "www.ecosia.org", "search.yahoo.com", "yandex.ru"}
AI = {"chatgpt.com", "chat.openai.com", "perplexity.ai", "www.perplexity.ai",
      "claude.ai", "gemini.google.com", "copilot.microsoft.com"}
REF_COLS = ["search", "AI", "internal", "direct", "other"]


def _ref_bucket(rf: str | None) -> str:
    rf = (rf or "").strip()
    if not rf:
        return "direct"
    if rf in SEARCH:
        return "search"
    if rf in AI:
        return "AI"
    if rf.startswith("visa-bulletin.us"):
        return "internal"
    return "other"


def _is_farm(row: dict) -> bool:
    return ((row.get("System") or "").strip() == "Linux"
            and (row.get("Screen size") or "") == "1920,0,1")


def _is_sgwave(row: dict) -> bool:
    return ((row.get("Location") or "").startswith("SG")
            and (row.get("Browser") or "").startswith("Chrome 145"))


def _read_rows(csv_path: Path):
    """Yield the export's pageview rows (events dropped, gzip + header quirk handled).

    Mirrors `_aggregate_csv_path_counts`'s filters so the totals here reconcile
    with the digest's, EXCEPT that FirstVisit is returned rather than applied —
    the caller decides, because the provenance question sometimes wants raw hits.
    """
    raw = csv_path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("2Path,"):
        text = text[1:]
    for row in csvm.DictReader(io.StringIO(text)):
        if (row.get("Event") or "0") not in ("0", ""):
            continue
        yield row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weeks", type=int, default=6, help="how many 7d windows back (default 6)")
    ap.add_argument("--surface", action="append",
                    help="surface bucket key (repeatable); 'all' for every surface. "
                         "Default: the two profile surfaces.")
    ap.add_argument("--end", help="ISO date anchor; default = last COMPLETE day in the export")
    ap.add_argument("--all-hits", action="store_true",
                    help="count every hit instead of FirstVisit=1 (the digest's basis)")
    ap.add_argument("--by-surface", action="store_true",
                    help="one row per surface for the newest week — the asymmetry check "
                         "that validates (or breaks) the farm fingerprint")
    args = ap.parse_args()

    async def _load():
        async with httpx.AsyncClient() as client:
            return await _gc_export_full_csv(client)

    csv_path = asyncio.run(_load())
    if csv_path is None or not csv_path.exists():
        print("GC export unavailable (no cache, or export rate-limited/failed). "
              "Per complete_data_queries.md, NOT falling back to top-100.", file=sys.stderr)
        return 2

    cutoff_ts = _gc_export_max_ts(csv_path)
    cutoff = cutoff_ts.date() if cutoff_ts else date.today()
    anchor = date.fromisoformat(args.end) if args.end else cutoff - timedelta(days=1)

    weeks = []
    for i in range(args.weeks):
        end = anchor - timedelta(days=7 * i)
        weeks.append((str(end - timedelta(days=6)), end - timedelta(days=6), end))
    weeks.reverse()

    want = args.surface or ["job_title_profile", "employer_profile"]
    every = "all" in want

    agg: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    newest = collections.defaultdict(collections.Counter)
    for row in _read_rows(csv_path):
        if not args.all_hits and (row.get("FirstVisit") or "0") != "1":
            continue
        try:
            d = date.fromisoformat((row.get("Date") or "")[:10])
        except ValueError:
            continue
        surface = _bucket_path((row.get("Path") or "").split("?", 1)[0].rstrip("/") or "/")
        klass = "farm" if _is_farm(row) else ("sgwave" if _is_sgwave(row) else "human")
        if weeks[-1][1] <= d <= weeks[-1][2]:
            newest[surface]["total"] += 1
            newest[surface][klass] += 1
        if not every and surface not in want:
            continue
        for name, st, en in weeks:
            if st <= d <= en:
                c = agg[(name, surface)]
                c["total"] += 1
                c[klass] += 1
                c[_ref_bucket(row.get("Referrer"))] += 1

    basis = "all hits" if args.all_hits else "FirstVisit=1 (the digest's basis)"
    print(f"GoatCounter traffic provenance — export cutoff {cutoff}, anchor {anchor}, {basis}")
    print("100% path coverage (full /api/v0/export). GC's own Bot column is 0 on the "
          "profile surfaces — it does not catch these.\n")

    if args.by_surface:
        n = weeks[-1][0]
        print(f"ASYMMETRY CHECK — week {n}..{weeks[-1][2]}: farm fingerprint share per surface")
        print("  (a fingerprint that is real users would be flat across surfaces)")
        print(f"  {'surface':<24} {'total':>7} {'farm':>7} {'farm%':>6}")
        for s, c in sorted(newest.items(), key=lambda kv: -kv[1]["total"]):
            print(f"  {s:<24} {c['total']:>7} {c['farm']:>7} {100 * c['farm'] / c['total']:>5.0f}%")
        print()

    surfaces = sorted({s for _, s in agg}) if every else [s for s in want if s != "all"]
    for s in surfaces:
        if not any(agg[(n, s)]["total"] for n, _, _ in weeks):
            continue
        print(f"== {s} " + "=" * (66 - len(s)))
        print(f"  {'week':<12} {'views':>6} | {'search':>6} {'AI':>4} {'internal':>8} "
              f"{'direct':>6} {'other':>5} | {'farm':>6} {'sgwave':>6} {'HUMAN':>6}")
        for n, st, en in weeks:
            c = agg[(n, s)]
            if not c["total"]:
                continue
            print(f"  {n:<12} {c['total']:>6} | {c['search']:>6} {c['AI']:>4} "
                  f"{c['internal']:>8} {c['direct']:>6} {c['other']:>5} | "
                  f"{c['farm']:>6} {c['sgwave']:>6} {c['human']:>6}")
        ser = [agg[(n, s)]["human"] for n, _, _ in weeks if agg[(n, s)]["total"]]
        if len(ser) >= 5:
            base = sum(ser[-5:-1]) / 4
            delta = f"{(ser[-1] - base) / base * 100:+.0f}%" if base else "n/a"
            print(f"  HUMAN-only: last {ser[-1]} vs prior-4wk avg {base:.0f} => {delta} "
                  f"(range {min(ser)}-{max(ser)})")
        print()

    print("REFERRER IS CLIENT-SET — before reading `search` as discovery, run the ratio test:")
    print("  gsc_query_search_analytics(site_url='sc-domain:visa-bulletin.us',")
    print("      dimensions=['date'], data_state='all',")
    print("      dimension_filters=[{'dimension':'page','operator':'contains',")
    print("                          'expression':'/job-title/'}])")
    print("  GC(search) / GSC(clicks) ~1 => real organic;  >>1 => forged referrer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
