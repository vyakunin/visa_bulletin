#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Observe what the live GA4 tag actually sends, for an engaged-session diagnosis.

Loads the live page in the box's debug Chrome (CDP :9222), waits past GA4's
10-second engagement timer, navigates to a second page on the same origin (which
alone qualifies the session as engaged: 2+ page_views), and prints every
``/g/collect`` beacon's decoded parameters plus the ``_ga``/``_ga_<id>`` cookies.

What to read in the output:
  seg=1   session_engaged — the flag GA4 counts engagedSessions from.
  _et     engagement_time_msec.
  gcs     consent state. G100 = analytics_storage DENIED; G101/G111 = granted.
  _ga_<id> cookie present ⇒ analytics_storage was granted and state persists.
  sid/cid changing between pageviews ⇒ cookieless: every hit is a new session.

Two flags make this usable from a EEA-geolocated box, which is the whole
difficulty: the production tag sets a region-scoped ``analytics_storage:denied``
default covering the EEA/UK, so a probe run from Berlin only ever reproduces the
consent-denied path and says nothing about US/India traffic.

  --strip-eea-region  rewrite the served HTML to drop the region-scoped consent
                      default, leaving the global ``granted`` default. This makes
                      a EEA-located browser take the same code path a US visitor
                      takes, so ``seg`` becomes a real test of the tag library.
  --block-beacons     abort every /collect request after recording it, so a
                      diagnostic run sends NOTHING to the live property. On by
                      default; pass --no-block-beacons to actually transmit.

Usage:
  scripts/oneoff/ga4_tag_probe.py                      # control: real page as served
  scripts/oneoff/ga4_tag_probe.py --strip-eea-region   # simulate a non-EEA visitor

Creates its own tab and closes only that tab; other tabs in the shared debug
Chrome profile are left alone.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
INTERESTING = ("tid", "cid", "sid", "sct", "seg", "_et", "en", "gcs", "gcd",
               "_ss", "_fv", "dl", "npa", "dma", "pscdl")
# the region-scoped consent default in the served base template
REGION_DEFAULT = re.compile(
    r'gtag\("consent","default",\{[^}]*?region:\[[^\]]*\]\}\);', re.S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://visa-bulletin.us/")
    ap.add_argument("--second-url", default="https://visa-bulletin.us/faq/")
    ap.add_argument("--dwell", type=float, default=16.0)
    ap.add_argument("--strip-eea-region", action="store_true")
    ap.add_argument("--block-beacons", action=argparse.BooleanOptionalAction,
                    default=True)
    args = ap.parse_args()

    beacons: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = ctx.new_page()

        if args.strip_eea_region:
            def rewrite(route):
                resp = route.fetch()
                body = resp.text()
                new, n = REGION_DEFAULT.subn("", body, count=1)
                print(f"  [rewrite] stripped {n} region-scoped consent default(s)"
                      f" from {route.request.url}")
                route.fulfill(response=resp, body=new,
                              headers={**resp.headers, "content-length": str(len(new))})
            page.route(lambda u: u.startswith("https://visa-bulletin.us/")
                       and "." not in u.rsplit("/", 1)[-1], rewrite)

        def on_collect(route):
            beacons.append(route.request.url)
            route.abort() if args.block_beacons else route.continue_()
        page.route(re.compile(r"google-analytics\.com/.*collect"), on_collect)

        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(int(args.dwell * 1000))
            print(f"\n== after {args.dwell}s on {args.url} ==")
            _dump(beacons)

            n_first = len(beacons)
            page.goto(args.second_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(9_000)
            print(f"\n== after 2nd pageview {args.second_url} ==")
            _dump(beacons[n_first:])

            print("\n== _ga cookies ==")
            cookies = [c for c in ctx.cookies(args.url) if c["name"].startswith("_ga")]
            print("  (none)" if not cookies else
                  "\n".join(f"  {c['name']} = {c['value']}" for c in cookies))
        finally:
            page.close()
    print(f"\n[beacons {'ABORTED — nothing sent to GA4' if args.block_beacons else 'TRANSMITTED'}]")
    return 0


def _dump(urls: list[str]) -> None:
    if not urls:
        print("  (no /collect beacons)")
    for u in urls:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
        print("  " + " ".join(f"{k}={q[k][0]}" for k in INTERESTING if k in q))


if __name__ == "__main__":
    sys.exit(main())
