#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp"]
# ///
"""Out-of-band refresher for the GoatCounter full-export CSV cache.

WHY THIS EXISTS
The daily_checkup digest needs the full per-hit GoatCounter export (the
`/stats/hits` endpoint caps at 100 paths, dropping ~43% of the long tail). But
as visa-bulletin.us's hit history grew, one `/api/v0/export` round-trip
(POST job -> server generates the full CSV -> download a 10 MB+ file) climbed
past ~2 min end-to-end — far more than the digest's response budget. Three
straight 7am digests (2026-07-07/08/09) RED-timed-out because the MCP blocked on
that export before it could serve.

The fix decouples the slow export from the digest:
  - the DIGEST (`daily_checkup_server._gc_export_full_csv`, tight
    GC_EXPORT_DIGEST_BUDGET_S) now polls only briefly then serves the CACHED CSV;
  - THIS SCRIPT owns the slow pull, on a systemd timer every 3h, with a generous
    GC_EXPORT_REFRESH_BUDGET_S. It writes the SAME cache file the digest reads,
    so the cache is normally <6h old and the digest hits the fast cache path
    without ever POSTing an export itself.

Single source of truth: it reuses the MCP's `_gc_export_full_csv` verbatim (same
cache path, same atomic write, same validation) — no logic drift.

INPUTS  : GoatCounter token at ~/tokens/goatcounter.token (read by the MCP).
OUTPUTS : refreshes ~/.cache/vb_daily_checkup/gc_export.csv (atomic). Logs one
          summary line. Exit 0 on a successful/served-cache refresh, 2 if no CSV
          could be produced AND no cache exists (genuine "no data").

USAGE   : uv run scripts/refresh_gc_export.py            # normal (systemd timer)
          uv run scripts/refresh_gc_export.py --budget 120
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import httpx

# Reuse the MCP's export machinery verbatim — single source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
from daily_checkup_server import (  # noqa: E402
    GC_EXPORT_REFRESH_BUDGET_S,
    _gc_export_full_csv,
    _read_gc_token,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s refresh_gc_export: %(message)s",
)
logger = logging.getLogger(__name__)


async def _refresh(budget_s: float) -> Path | None:
    token = _read_gc_token()
    headers = {"Authorization": f"Bearer {token}"}
    # Client timeout must exceed the generous poll budget so httpx's own timeout
    # doesn't cut the export off early; the function bounds the poll wall-clock.
    async with httpx.AsyncClient(headers=headers, timeout=budget_s + 120) as client:
        return await _gc_export_full_csv(client, budget_s=budget_s, force=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--budget",
        type=float,
        default=GC_EXPORT_REFRESH_BUDGET_S,
        help="max wall-clock seconds to poll for the export job (default %(default)s)",
    )
    args = ap.parse_args()

    t0 = time.monotonic()
    path = asyncio.run(_refresh(args.budget))
    dt = time.monotonic() - t0

    if path is None:
        logger.error("no export CSV produced and no cache exists (%.0fs)", dt)
        return 2
    try:
        size = path.stat().st_size
        age_s = time.time() - path.stat().st_mtime
    except OSError:
        size, age_s = 0, -1
    logger.info(
        "cache ready: %s (%d bytes, %ds old) in %.0fs",
        path, size, int(age_s), dt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
