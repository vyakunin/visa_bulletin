#!/usr/bin/env python3
"""Fetch Visa Bulletin HTML through the minipc debug Chrome (Akamai-wall bypass).

travel.state.gov sits behind Akamai Bot Manager: plain requests, browser-UA curl,
and curl_cffi Chrome-impersonation all get 403 (a JS/sensor challenge, not just a
TLS-fingerprint check). The only client that passes is a real browser executing the
challenge JS. The minipc runs a headed debug Chrome on CDP :9222 (see
~/.claude/rules/browser.md § CDP-over-HTTP); this script drives it via Playwright to
download the bulletin index + requested month pages, saving them into a cache dir
that the prod ingest reads via BULLETIN_HTML_CACHE_DIR (base.download / fetch_page
prefer a cached file over the network). See scripts/README.md and
scripts/sync_bulletin_to_prod.sh for the minipc->prod bridge.

The Akamai flow: a fresh browser with no _abck cookie solves the JS challenge and
gets a valid cookie; a STALE _abck triggers an ERR_TOO_MANY_REDIRECTS loop. So the
robust pattern is: clear cookies -> navigate (may raise) -> wait -> reload (may
raise) -> read content. goto/reload raising on the redirect churn is expected; the
page content settles and page.content() returns the real HTML.

Inputs:
  --cache-dir DIR   Where to write fetched HTML (default: /tmp/bulletin_html_cache).
  --months LIST     Comma-separated YYYY-MM to fetch bulletin pages for
                    (default: current + next month, UTC). Only months whose link
                    exists on the index are fetched; missing = not published yet.
  --cdp URL         CDP endpoint (default: http://127.0.0.1:9222).
Outputs:
  <cache-dir>/visa-bulletin.html                          (index)
  <cache-dir>/visa-bulletin-for-<month>-<year>.html       (each fetched month)
  Prints a JSON summary {index_ok, months_available, months_fetched} to stdout.
Exit codes: 0 = index fetched (regardless of month availability); 2 = index fetch
failed (wall not passed / CDP down) so the caller can alert.

Runs on the MINIPC only (needs the debug Chrome). Not a prod/Bazel script.
"""

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("fetch_bulletin")

INDEX_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
BULLETIN_URL_TMPL = (
    "https://travel.state.gov/content/travel/en/legal/visa-law0/"
    "visa-bulletin/{fy_dir}/visa-bulletin-for-{month}-{year}.html"
)
LINK_RE = re.compile(r"visa-bulletin-for-([a-z]+)-(\d{4})\.html", re.IGNORECASE)


def _fetch_via_browser(page, url: str, settle_ms: int = 7000) -> str:
    """Fetch one URL through the connected browser, surviving the Akamai redirect churn."""
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:  # ERR_TOO_MANY_REDIRECTS while the challenge settles
            logger.info("goto churn (attempt %d) on %s: %s", attempt, url, type(e).__name__)
        page.wait_for_timeout(settle_ms)
        html = page.content()
        if "visa-bulletin-for-" in html or len(html) > 50_000:
            return html
        # First hit may still be the challenge shell; reload uses the fresh cookie.
        try:
            page.reload(wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            logger.info("reload churn on %s: %s", url, type(e).__name__)
        page.wait_for_timeout(settle_ms // 2)
        html = page.content()
        if "visa-bulletin-for-" in html or len(html) > 50_000:
            return html
    return html


def _default_months() -> list[str]:
    now = datetime.now(UTC)
    nxt = now + relativedelta(months=1)
    return [now.strftime("%Y-%m"), nxt.strftime("%Y-%m")]


def _month_link_name(year_month: str) -> str:
    """YYYY-MM -> visa-bulletin-for-<monthname>-<year>.html"""
    dt = datetime.strptime(year_month, "%Y-%m")
    return f"visa-bulletin-for-{dt.strftime('%B').lower()}-{dt.year}.html"


def _bulletin_url_for(year_month: str) -> str:
    """Construct the canonical bulletin URL. FY dir = calendar year of the bulletin's
    fiscal year; State Dept groups by FY (Oct-Sep), so Oct-Dec belong to FY = year+1."""
    dt = datetime.strptime(year_month, "%Y-%m")
    fy = dt.year + 1 if dt.month >= 10 else dt.year
    return BULLETIN_URL_TMPL.format(fy_dir=fy, month=dt.strftime("%B").lower(), year=dt.year)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", default="/tmp/bulletin_html_cache")
    ap.add_argument("--months", default=None, help="comma-separated YYYY-MM")
    ap.add_argument("--cdp", default="http://127.0.0.1:9222")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    months = [m.strip() for m in args.months.split(",")] if args.months else _default_months()

    summary = {"index_ok": False, "months_requested": months,
               "months_available": [], "months_fetched": []}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0]
        ctx.clear_cookies()  # drop any poisoned Akamai _abck to avoid the redirect loop
        page = ctx.new_page()
        try:
            index_html = _fetch_via_browser(page, INDEX_URL)
            links = {m.group(0).lower() for m in LINK_RE.finditer(index_html)}
            if not links:
                logger.error("Index fetch did not yield bulletin links (wall not passed). len=%d", len(index_html))
                return 2
            (cache / "visa-bulletin.html").write_text(index_html, encoding="utf-8")
            summary["index_ok"] = True
            logger.info("Index saved: %d bulletin links", len(links))

            for ym in months:
                link_name = _month_link_name(ym)
                if link_name not in links:
                    logger.info("%s not on index yet (not published) — skipping", ym)
                    continue
                summary["months_available"].append(ym)
                html = _fetch_via_browser(page, _bulletin_url_for(ym))
                # A real bulletin page is large and contains the cutoff tables.
                if len(html) < 50_000:
                    logger.warning("%s page looks like a challenge shell (len=%d) — not saving", ym, len(html))
                    continue
                (cache / link_name).write_text(html, encoding="utf-8")
                summary["months_fetched"].append(ym)
                logger.info("Saved %s (%d bytes)", link_name, len(html))
        finally:
            page.close()

    print(json.dumps(summary))
    return 0 if summary["index_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
