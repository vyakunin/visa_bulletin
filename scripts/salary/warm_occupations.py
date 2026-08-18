#!/usr/bin/env python3
"""Fill the per-occupation caches the /h1b-salary/<occupation>/ pages read, then
assert the pages actually render fast.

Each occupation page runs nine aggregates over salary_record plus the I-129
matched-triple aggregate. `occupation_stats` caches the results per occupation but
fills them ON THE FIRST MISS, so an uncached request pays the whole cost. That
request is almost always a crawler: the view is `cache_page_skip_bots`, so bot
traffic bypasses the rendered-page cache by design and can never be warmed by it.

WHY THIS SCRIPT MEASURES THE PAGE, NOT THE CACHE KEY
Warming alone is not a guarantee and reporting on it is not a check. vb_redis runs
allkeys-lru over a ~65k-key space (salary_search, job_title_*, employer_page_*), so
these 41 read-rarely entries are among the first evicted. Measured on prod
2026-08-18: five hours after the nightly warm, 34 of 41 stats entries were gone and
the seven present had all been written minutes earlier by crawler cold-fills.
Through all of that this script logged "warmed 41 occupations in 0.2s — 0 were cold
fills", which was true about the keys and false about what a visitor waited for —
pages were still rendering 5-13s on prod. So the pass condition here is the RENDERED
PAGE's latency, which is the thing anyone actually cares about; the cache fill is
just an optimisation performed on the way.

The probe sends a crawler User-Agent on purpose: that is the path with no
rendered-page cache in front of it, and it is nearly all of this surface's traffic.
It therefore measures the real worst case rather than a cache hit.

RUN IT:
  * after anything that empties the cache — a deploy's `redis-cli -n 1 FLUSHDB`
    (.claude/rules/deployment.md), the refresh pipeline's cache.clear(), a data load;
  * daily, ahead of the crawl window, so the TTL never expires into a crawler.

Read-only against the database (the probe issues GETs). Run it INSIDE the app
container, which is where the cache the site reads actually lives:

    docker exec -w /app vb_web python3 -m scripts.salary.warm_occupations
    bazel run //scripts/salary:warm_occupations -- [--check]

--check probes the pages and writes nothing — use it to measure the surface as a
crawler finds it, decoupled from a warm that would mask the answer.

Exit status is the check: 0 when every page renders under --max-render-ms, 1 when
any page is slower (or unreachable), so cron surfaces a regression instead of
logging a reassuring line about cache keys.
"""

import argparse
import logging
import os
import time
import urllib.error
import urllib.request

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django_config.logging_config import setup_logging  # noqa: E402
from lib.business.i129.pay_comparison import (  # noqa: E402
    get_soc_pay_comparison,
    soc_pay_comparison_cached,
)
from lib.business.salary.occupation_stats import (  # noqa: E402
    get_occupation_stats,
    occupation_filing_count,
    occupation_qualifies,
    occupation_stats_cached,
    qualifying_occupation_slugs,
)
from lib.business.salary.soc_occupations import OCCUPATIONS  # noqa: E402

setup_logging(debug=False)
logger = logging.getLogger(__name__)

# Gunicorn inside the app container. The probe deliberately does not go through
# nginx/Cloudflare: the number worth alerting on is the origin render, and an edge
# hit would report a cached response as though the app were fast.
DEFAULT_BASE_URL = "http://localhost:8000"

# The public host, sent as the Host header so the render matches what a crawler
# gets (canonical URLs and absolute links are built from it).
PUBLIC_HOST = "visa-bulletin.us"

# A crawler UA, so `cache_page_skip_bots` skips the rendered-page cache and the
# probe measures a real render rather than a replay of one.
PROBE_USER_AGENT = "Mozilla/5.0 (compatible; VBWarmCheck/1.0; +bot)"

# A warm page renders in well under this; the 5-13s tail that prompted the probe is
# far above it. Wide enough that ordinary load variance does not page anyone, tight
# enough that any return of the seq-scan tail fires on the first run.
DEFAULT_MAX_RENDER_MS = 1500

PROBE_TIMEOUT_S = 30


def _is_warm(slug: str) -> bool:
    """Whether the two per-occupation entries a page render needs are both present.

    The filing count alone is not enough — it is the cheap 404 gate, while the stats
    and the SOC comparison are what cost seconds.
    """
    return occupation_stats_cached(slug) and soc_pay_comparison_cached(slug)


def _warm_one(occ) -> float:
    """Fill every cached value one occupation page reads. Returns seconds taken."""
    started = time.perf_counter()
    filing_count = occupation_filing_count(occ)
    if occupation_qualifies(filing_count):
        # A thin occupation 404s, so its stats are never rendered and warming them
        # would pay nine aggregates for a page nobody can reach.
        get_occupation_stats(occ)
        get_soc_pay_comparison(occ)
    return time.perf_counter() - started


def _probe_page(base_url: str, slug: str) -> tuple[int | None, float]:
    """GET /h1b-salary/<slug>/ as a crawler would. Returns (status, seconds).

    A status of None means the request never completed; the caller treats that as a
    failure rather than as a fast page.
    """
    request = urllib.request.Request(
        f"{base_url}/h1b-salary/{slug}/",
        headers={"Host": PUBLIC_HOST, "User-Agent": PROBE_USER_AGENT},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as response:
            response.read()
            return response.status, time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, time.perf_counter() - started
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("  probe %-30s FAILED: %s", slug, exc)
        return None, time.perf_counter() - started


def _probe_all(base_url: str, slugs: list[str], max_render_ms: int) -> int:
    """Probe every published occupation page. Returns a process exit status."""
    if not slugs:
        # No published occupation is a data problem, never a passing check.
        logger.error("no occupation pages qualify — nothing to probe")
        return 1

    results: list[tuple[float, str, int | None]] = []
    for slug in slugs:
        status, took = _probe_page(base_url, slug)
        results.append((took * 1000, slug, status))

    slow = [r for r in results if r[0] > max_render_ms]
    broken = [r for r in results if r[2] != 200]
    results.sort(reverse=True)

    if not slow and not broken:
        logger.info(
            "all %d occupation pages render under %dms (slowest %s %.0fms)",
            len(results),
            max_render_ms,
            results[0][1],
            results[0][0],
        )
        return 0

    if broken:
        logger.error(
            "%d/%d occupation pages did not return 200: %s",
            len(broken),
            len(results),
            ", ".join(f"{slug}={status}" for _, slug, status in broken),
        )
    if slow:
        logger.error(
            "%d/%d occupation pages render slower than %dms — this is what a "
            "crawler waits for on every hit:",
            len(slow),
            len(results),
            max_render_ms,
        )
        for took_ms, slug, _ in sorted(slow, reverse=True):
            logger.error("  slow render %-30s %7.0fms", slug, took_ms)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="probe the pages and report; compute and write nothing",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"origin to probe (default {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--max-render-ms",
        type=int,
        default=DEFAULT_MAX_RENDER_MS,
        help=f"fail if any page renders slower (default {DEFAULT_MAX_RENDER_MS})",
    )
    parser.add_argument(
        "--skip-probe",
        action="store_true",
        help="warm only, do not probe (leaves the run unverified)",
    )
    args = parser.parse_args()

    if args.check:
        # Report coldness for context, but the verdict is the page latency: a
        # fully-warm cache proves nothing about what a crawler waits for, which is
        # exactly the false all-clear this script used to emit.
        cold = [o.slug for o in OCCUPATIONS if not _is_warm(o.slug)]
        if cold:
            logger.warning(
                "%d/%d occupations have no cached aggregates: %s",
                len(cold),
                len(OCCUPATIONS),
                ", ".join(cold),
            )
        return _probe_all(
            args.base_url, list(qualifying_occupation_slugs()), args.max_render_ms
        )

    # Coldness measured BEFORE filling anything. The old report inferred it from how
    # long the fill took, so a cache that had been refilled by crawlers paying 6s
    # each read back as "0 cold fills" — a healthy-looking line describing the exact
    # failure it was meant to detect.
    cold_before = [o.slug for o in OCCUPATIONS if not _is_warm(o.slug)]

    started = time.perf_counter()
    # Fill the qualifying-slug set first: it reads through the same per-occupation
    # filing-count entries, so the sitemap and the pages warm each other.
    slugs = list(qualifying_occupation_slugs())
    for occ in OCCUPATIONS:
        _warm_one(occ)

    logger.info(
        "warmed %d occupations in %.1fs — %d were cold beforehand%s",
        len(OCCUPATIONS),
        time.perf_counter() - started,
        len(cold_before),
        (": " + ", ".join(cold_before)) if cold_before else "",
    )

    if args.skip_probe:
        logger.warning("--skip-probe: page latency NOT verified")
        return 0
    return _probe_all(args.base_url, slugs, args.max_render_ms)


if __name__ == "__main__":
    raise SystemExit(main())
