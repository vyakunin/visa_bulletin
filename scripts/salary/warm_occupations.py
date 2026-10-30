#!/usr/bin/env python3
"""Store the aggregates the /h1b-salary/<occupation>/ pages read, then assert the
pages actually render fast.

Each occupation page runs nine aggregates over salary_record plus the I-129
matched-triple aggregate. This script computes them for every occupation and writes
them to the `aggregates` store (Postgres), which a request reads first and nothing
evicts. The view is `cache_page_skip_bots`, so crawler traffic, nearly all of this
surface's hits, can never be served from the rendered-page cache.

WHY THIS SCRIPT MEASURES THE PAGE, NOT THE STORED ROW
A stored row is not proof that a crawler gets a fast page: when the aggregates lived
in Redis, this script logged "0 cold fills" for weeks while pages rendered 5-13s,
because allkeys-lru evicted the keys hours after the warm. So the pass condition is
the RENDERED PAGE's latency.

The probe sends a crawler User-Agent on purpose: that is the path with no
rendered-page cache in front of it, and it is nearly all of this surface's traffic.
It therefore measures the real worst case rather than a cache hit.

RUN IT:
  * after anything that changes salary or I-129 data — a data load, a graduation;
  * daily, ahead of the crawl window, so the stored pages track the data and the
    year window.

Writes only the `aggregates` store. Run it INSIDE the app container:

    docker exec -w /app vb_web python3 -m scripts.salary.warm_occupations
    bazel run //scripts/salary:warm_occupations -- [--check]

--check probes the pages without storing anything, so it measures the surface as a
crawler finds it rather than one this run just made fast.

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
    soc_pay_comparison_stored,
    warm_soc_pay_comparison,
)
from lib.business.salary.occupation_stats import (  # noqa: E402
    occupation_page_stored,
    occupation_qualifies,
    qualifying_occupation_slugs,
    store_qualifying_occupation_slugs,
    warm_occupation_page,
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


def _is_stored(slug: str) -> bool:
    """Whether both stored entries a page render reads are present."""
    return occupation_page_stored(slug) and soc_pay_comparison_stored(slug)


def _warm_all() -> list[str]:
    """Store every occupation's page aggregates. Returns the qualifying slugs."""
    slugs = []
    for occ in OCCUPATIONS:
        page = warm_occupation_page(occ)
        if occupation_qualifies(page.filing_count):
            # A thin occupation 404s, so its comparison is never rendered.
            warm_soc_pay_comparison(occ)
            slugs.append(occ.slug)
    store_qualifying_occupation_slugs(slugs)
    return slugs


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
        help="probe the pages without storing anything (see --help notes)",
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
        # Report what is missing for context, but the verdict is the page latency.
        missing = [o.slug for o in OCCUPATIONS if not _is_stored(o.slug)]
        if missing:
            logger.warning(
                "%d/%d occupations have no stored aggregates: %s",
                len(missing),
                len(OCCUPATIONS),
                ", ".join(missing),
            )
        return _probe_all(
            args.base_url, list(qualifying_occupation_slugs()), args.max_render_ms
        )

    started = time.perf_counter()
    slugs = _warm_all()
    logger.info(
        "stored %d occupations (%d published) in %.1fs",
        len(OCCUPATIONS),
        len(slugs),
        time.perf_counter() - started,
    )

    if args.skip_probe:
        logger.warning("--skip-probe: page latency NOT verified")
        return 0
    return _probe_all(args.base_url, slugs, args.max_render_ms)


if __name__ == "__main__":
    raise SystemExit(main())
