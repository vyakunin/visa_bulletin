#!/usr/bin/env python3
"""Clear Django cache.

Clears the default cache backend (Redis in production/staging, LocMem in dev).
This resets all @cache_page and programmatic cache keys, including:

- Job title autocomplete (/api/job-title-autocomplete/)
- Job title directory (/job-titles/)
- Employer directory (/employers/)
- Employer profile pages
- Salary search results
- Market overview, fiscal years, count caches
- Sitemaps, dashboard, other cached views

When to run:
- After update_job_title_cluster_stats or populate_job_title_slugs (so autocomplete
  and directory show new canonical_title).
- After refresh_data or any deploy that changes cached payloads.
- With Redis: cache is shared; no app restart needed.
- With LocMem: reload gunicorn (kill -HUP) so workers see cleared cache.

Usage:
  bazel run //scripts:clear_cache
  bazel run //scripts:clear_cache -- --sitemap-only   # Clear only sitemap.xml and robots.txt cache

  On production, set SITE_DOMAIN so the cache key matches (e.g. SITE_DOMAIN=visa-bulletin.us).
"""

import argparse
import logging
import os

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django.core.cache import cache
from django.http import HttpRequest
from django.utils.cache import get_cache_key

from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)


def _delete_view_cache(path: str, server_name: str = "localhost", use_https: bool = False) -> bool:
    """Delete cache for a single path (e.g. /sitemap.xml). Returns True if key was deleted."""
    request = HttpRequest()
    request.path = path
    request.method = "GET"
    # Cache key is derived from full URI; match how nginx sends requests (Host + X-Forwarded-Proto)
    request.META = {
        "SERVER_NAME": server_name,
        "SERVER_PORT": "443" if use_https else "80",
        "HTTP_HOST": server_name,
        "HTTP_X_FORWARDED_PROTO": "https" if use_https else None,
    }
    request.META = {k: v for k, v in request.META.items() if v is not None}
    key = get_cache_key(request, key_prefix="", method="GET", cache=cache)
    if key:
        cache.delete(key)
        return True
    return False


def clear_sitemap_cache() -> None:
    """Clear only sitemap.xml and robots.txt @cache_page entries."""
    script_logger.log_call(args={"sitemap_only": True}, context="Clearing sitemap/robots cache")
    # On prod set SITE_DOMAIN=visa-bulletin.us so the cache key matches (key is built from full URI)
    server_name = os.environ.get("SITE_DOMAIN", "localhost")
    use_https = server_name != "localhost"  # Prod traffic comes via nginx with X-Forwarded-Proto: https
    deleted = 0
    for path in ("/sitemap.xml", "/robots.txt"):
        if _delete_view_cache(path, server_name=server_name, use_https=use_https):
            logger.info("✓ Cleared cache for %s", path)
            deleted += 1
        else:
            logger.info("No cache key found for %s (may not be cached yet)", path)
    logger.info("Sitemap/robots cache cleared (%d key(s))", deleted)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear Django cache")
    parser.add_argument(
        "--sitemap-only",
        action="store_true",
        help="Clear only sitemap.xml and robots.txt cache (no full cache clear)",
    )
    args = parser.parse_args()

    if args.sitemap_only:
        clear_sitemap_cache()
        return

    script_logger.log_call(args={}, context="Clearing Django cache")
    cache.clear()
    logger.info("✓ Django cache cleared")
    logger.info(
        "With Redis: cache is shared; no restart needed. "
        "After data refresh or deploy that changes cached payloads, run this script (or see docs for cache cleansing)."
    )
    logger.info(
        "On memory-constrained instances (e.g. 2GB): run 'bazel shutdown' after this to free ~400-500MB."
    )

if __name__ == '__main__':
    main()
