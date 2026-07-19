#!/usr/bin/env python3
"""Pre-render /sitemap.xml to a static file that nginx serves off disk.

WHY THIS EXISTS
---------------
The sitemap is the single most expensive response on the site (~21.7s cold,
1.3 MB, 6.9k URLs), and Cloudflare will not edge-cache it (cf-cache-status:
DYNAMIC), so every crawler fetch reached the origin.

The cost is not the URL strings — it is four whole-corpus aggregates
(``qualifying_pairs``, ``qualifying_slugs``, ``qualifying_state_codes``,
``qualifying_occupation_slugs``). Each was individually Redis-cached with a 24h
TTL, which was the original defense. But prod's Redis runs ``allkeys-lru``
pinned at its 512 MB cap, evicting ~4k keys/hour at a 61% miss rate, so those
four keys vanish unpredictably and independently (measured 2026-07-19: three
present, ``h1b_sponsors.qualifying_slugs.v1`` already evicted). Any single miss
puts a whole-corpus GROUP BY on Googlebot's request path.

Caching the rendered page has the same exposure — a 1.3 MB entry is ~24x the
average key in a cache that is actively evicting. So rather than defend the
render, this takes it off the request path entirely: render on a schedule, write
a file, let nginx serve it. A file does not get LRU-evicted.

Side benefit: rendering here populates those four Redis keys, which also back
the 404-gates of the /h1b-sponsors/ and /h1b-salary/ views.

SAFETY
------
The sitemap builder swallows OperationalError/ProgrammingError per-section and
logs, returning [] for that section — good for serving, dangerous for writing.
A degraded DB would render a ~50-URL sitemap, and overwriting a good file with
it would tell Google that 6.8k pages vanished. So a write is refused unless the
result clears both an absolute floor (--min-urls) and a relative floor against
the file already on disk (--max-shrink). Refusing leaves the last good file in
place, which is the safe failure mode.

USAGE
    bazel run //scripts/seo:render_sitemap
    bazel run //scripts/seo:render_sitemap -- --dry-run
    bazel run //scripts/seo:render_sitemap -- --base-url https://staging.visa-bulletin.us

    # in prod (the deployed container already has Django on the path):
    docker exec -w /app vb_web python3 -m scripts.seo.render_sitemap

OUTPUT
    Writes <STATIC_ROOT>/sitemap.xml atomically (tmp file + os.replace, same
    directory, so nginx never observes a partial file). STATIC_ROOT is the
    ./staticfiles bind mount, shared rw into vb_web and ro into vb_nginx.

EXIT CODES
    0  wrote (or --dry-run rendered) a sitemap that passed the safety gates
    1  refused to write: failed a safety gate, or the render itself errored
"""

import argparse
import logging
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django.conf import settings  # noqa: E402

from webapp.views.seo.sitemaps import build_sitemap_xml  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://visa-bulletin.us"

# Absolute floor. The static/category/priority-date/state URLs alone are ~100,
# so anything under this means the employer + job-title + sponsor sections came
# back empty — i.e. the DB was degraded, not that the site genuinely shrank.
DEFAULT_MIN_URLS = 1000

# Relative floor: refuse a render that drops more than this fraction of the URLs
# already on disk. Real churn between runs is well under 1%.
DEFAULT_MAX_SHRINK = 0.10


def count_urls(xml: str) -> int:
    return xml.count("<loc>")


def read_existing_url_count(path: str) -> int | None:
    """URL count of the sitemap already on disk, or None if there isn't one."""
    try:
        with open(path, encoding="utf-8") as fh:
            return count_urls(fh.read())
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("could not read existing sitemap at %s", path, exc_info=True)
        return None


def check_safety_gates(new_count: int, old_count: int | None, min_urls: int, max_shrink: float) -> str | None:
    """Return a refusal reason, or None if it is safe to write."""
    if new_count < min_urls:
        return (
            f"rendered only {new_count} URLs, below the --min-urls floor of {min_urls}. "
            "This almost always means a DB error emptied whole sections (the builder "
            "logs and returns [] per section rather than raising)."
        )
    if old_count and new_count < old_count * (1 - max_shrink):
        lost = old_count - new_count
        return (
            f"rendered {new_count} URLs vs {old_count} already on disk — a drop of "
            f"{lost} ({lost / old_count:.1%}), over the --max-shrink limit of {max_shrink:.0%}. "
            "Publishing this would tell Google those pages are gone."
        )
    return None


def write_atomically(path: str, content: str) -> None:
    """Write via a temp file in the same directory, then rename.

    os.replace is atomic within a filesystem, so a concurrent nginx read sees
    either the whole old file or the whole new one — never a truncated sitemap.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def default_output_path() -> str:
    return os.path.join(str(settings.STATIC_ROOT), "sitemap.xml")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SITEMAP_BASE_URL", DEFAULT_BASE_URL),
        help=f"Absolute site root, no trailing slash (default: {DEFAULT_BASE_URL}). "
        "Must match the stack — a staging render written to prod would advertise staging URLs.",
    )
    parser.add_argument("--out", default=None, help="Output path (default: <STATIC_ROOT>/sitemap.xml)")
    parser.add_argument("--min-urls", type=int, default=DEFAULT_MIN_URLS, help=f"Absolute floor (default: {DEFAULT_MIN_URLS})")
    parser.add_argument(
        "--max-shrink",
        type=float,
        default=DEFAULT_MAX_SHRINK,
        help=f"Max fraction of on-disk URLs the render may drop (default: {DEFAULT_MAX_SHRINK})",
    )
    parser.add_argument("--force", action="store_true", help="Write even if a safety gate fails. Use only after reading the reason.")
    parser.add_argument("--dry-run", action="store_true", help="Render and report, write nothing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    base_url = args.base_url.rstrip("/")
    out_path = args.out or default_output_path()

    logger.info("rendering sitemap for %s", base_url)
    start = time.time()
    xml = build_sitemap_xml(base_url)
    elapsed = time.time() - start

    new_count = count_urls(xml)
    logger.info("rendered %d URLs, %.1f KB, in %.1fs", new_count, len(xml.encode("utf-8")) / 1024, elapsed)

    old_count = read_existing_url_count(out_path)
    refusal = check_safety_gates(new_count, old_count, args.min_urls, args.max_shrink)
    if refusal:
        if not args.force:
            logger.error("REFUSING to write %s: %s", out_path, refusal)
            logger.error("Left the existing file untouched. Re-run with --force to override.")
            return 1
        logger.warning("safety gate failed but --force given, writing anyway: %s", refusal)

    if args.dry_run:
        logger.info("--dry-run: not writing (would have written %s)", out_path)
        return 0

    write_atomically(out_path, xml)
    logger.info("wrote %s (%d URLs, was %s)", out_path, new_count, old_count if old_count is not None else "absent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
