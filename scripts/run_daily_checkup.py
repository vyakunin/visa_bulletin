#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp"]
# ///
"""Run the visa_bulletin daily_checkup coroutine locally and dump its report JSON.

WHY THIS EXISTS — the daily_checkup MCP server (`mcp/daily_checkup_server.py`)
exposes its report via the `@mcp.tool()`-decorated `daily_checkup` coroutine, so
the normal way to see the report is through the MCP protocol / the 7am digest.
For local debugging you just want the raw report JSON in a terminal, which meant
re-typing the same `asyncio.run(daily_checkup())` boilerplate every time — that
inline snippet was pasted 4× across 4 sessions (Jun 29 - Jul 5). This is the
committed one-liner so nobody re-types it (`~/.claude/rules/no_adhoc_scripts.md`).

Single source of truth: it imports the SAME `daily_checkup` coroutine the MCP
serves (via `sys.path` into `mcp/`), so what it prints is byte-identical to what
the digest pipeline receives — no reimplementation of the report build.

🚨 HEAVY PROD READ — NOT casual. Invoking the coroutine does a real production
gather: one SSH round-trip to `homeserver` (container health, nginx 24h log awk,
Postgres freshness), a GoatCounter `/api/v0/export` pull (can be a 10 MB+ CSV,
1/hour rate-limited), GA4 + Gmail + GSC sub-MCP calls, and external HTTP probes
against visa-bulletin.us. Expect tens of seconds and side effects on the shared
GC export cache. Run it deliberately, not in a loop.

INPUTS  : GoatCounter token at ~/tokens/goatcounter.token, the `homeserver` SSH
          alias, and the sub-MCP auth the server itself needs (GA4/Gmail/GSC).
          `since` is accepted for parity with the tool but ignored by the server
          (it always reports last-24h homeserver + last-7d GoatCounter).
OUTPUTS : pretty-printed report JSON to stdout (or `--out FILE`). One log line to
          stderr. Exit 0 on a produced report, 1 on gather failure.

USAGE :
  uv run scripts/run_daily_checkup.py                 # pretty JSON to stdout
  uv run scripts/run_daily_checkup.py --raw           # exact MCP string, unformatted
  uv run scripts/run_daily_checkup.py --since 2026-07-01T00:00:00Z
  uv run scripts/run_daily_checkup.py --out /tmp/checkup.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Reuse the MCP server's report coroutine verbatim — single source of truth.
# `@mcp.tool()` (mcp.server.fastmcp) returns the original function unchanged, so
# `daily_checkup` here is the plain `async def` coroutine, directly awaitable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
from daily_checkup_server import daily_checkup  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s run_daily_checkup: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Run the visa_bulletin daily_checkup coroutine locally and "
        "dump its report JSON. HEAVY PROD READ — see the module docstring."
    )
    ap.add_argument(
        "--since",
        default=None,
        help="ISO 8601 timestamp passed to the coroutine (currently ignored by "
        "the server, which always reports last-24h/last-7d).",
    )
    ap.add_argument(
        "--raw",
        action="store_true",
        help="Print the exact MCP string the tool returns, unformatted "
        "(default re-parses + pretty-prints the JSON).",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the report to this file instead of stdout.",
    )
    return ap.parse_args()


async def _run(since: str | None) -> str:
    logger.info("running daily_checkup coroutine (heavy prod read; since=%s)", since)
    return await daily_checkup(since=since)


def main() -> int:
    args = _parse_args()
    try:
        report_str = asyncio.run(_run(args.since))
    except Exception:  # noqa: BLE001 — surface any gather failure with a trace
        logger.exception("daily_checkup coroutine failed")
        return 1

    if args.raw:
        out_text = report_str
    else:
        try:
            out_text = json.dumps(json.loads(report_str), indent=2, ensure_ascii=False)
        except (ValueError, json.JSONDecodeError):
            logger.warning("report was not valid JSON; emitting raw string")
            out_text = report_str

    if args.out:
        args.out.write_text(out_text + "\n")
        logger.info("wrote report to %s (%d bytes)", args.out, len(out_text))
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
