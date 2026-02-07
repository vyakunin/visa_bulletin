#!/usr/bin/env python3
"""Inspect Django cache state and TTL for specific URLs.

Shows whether a @cache_page key exists and (for Redis) remaining TTL in seconds.
Useful to verify cache is populated and when it will expire.

Usage:
  bazel run //scripts/cache:inspect_cache -- /salaries/
  bazel run //scripts/cache:inspect_cache -- /salaries/ --domain visa-bulletin.us

  Production (match Host used by nginx; .env must have REDIS_URL):
  ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
    bazel run //scripts/cache:inspect_cache -- /salaries/ --domain visa-bulletin.us"

  On production, pass --domain so the cache key matches the key used when
  serving requests (Host + X-Forwarded-Proto).

Output:
  - Cache backend (Redis or LocMem)
  - For the given path: key exists (yes/no)
  - If Redis: TTL in seconds and human-readable (e.g. "2h 15m left")

Note: Cache key is only found when the URL has been requested at least once
(from the same host/path) so the key exists in the backend. Locally with no
prior request you may see "Cache key: (none)".
"""

import argparse
import os
import sys

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django
django.setup()

from django.core.cache import cache, caches
from django.http import HttpRequest
from django.utils.cache import get_cache_key


def _build_request(path: str, server_name: str, use_https: bool) -> HttpRequest:
    """Build a request that matches how nginx sends traffic (Host, X-Forwarded-Proto)."""
    request = HttpRequest()
    request.method = "GET"
    request.META = {
        "SERVER_NAME": server_name,
        "SERVER_PORT": "443" if use_https else "80",
        "HTTP_HOST": server_name,
        "PATH_INFO": path,
        "HTTP_X_FORWARDED_PROTO": "https" if use_https else None,
    }
    request.META = {k: v for k, v in request.META.items() if v is not None}
    request.path = path
    return request


def _get_redis_ttl(backend, full_key: str) -> int | None:
    """Return remaining TTL in seconds for a key, or None if not Redis / no TTL."""
    if not hasattr(backend, "_cache") or not hasattr(backend._cache, "get_client"):
        return None
    try:
        client = backend._cache.get_client(full_key)
        ttl = client.ttl(full_key)
        if ttl >= 0:
            return ttl
        if ttl == -1:
            return None  # key exists but no expire
        return -1  # key does not exist (Redis returns -2)
    except Exception:
        return None


def _format_ttl(seconds: int) -> str:
    """Format TTL seconds as human-readable."""
    if seconds < 0:
        return "expired or missing"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s" if s else f"{m}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m" if m else f"{h}h"


def inspect_path(path: str, server_name: str, use_https: bool) -> None:
    """Print cache state and TTL for the given path."""
    try:
        backend = caches["default"]
    except Exception:
        backend = None
    backend_name = type(backend).__name__ if backend else "unknown"
    print(f"Backend: {backend_name}")

    request = _build_request(path, server_name, use_https)
    key = get_cache_key(request, key_prefix="", method="GET", cache=cache)
    if not key:
        print(f"Path: {path}")
        print("Cache key: (none — not a cached view or key generation returned None)")
        return

    full_key = backend.make_key(key) if backend else key
    exists = backend.has_key(full_key) if (backend and hasattr(backend, "has_key")) else False

    print(f"Path: {path}")
    print(f"Key exists: {'yes' if exists else 'no'}")

    ttl_seconds = None
    if backend:
        ttl_seconds = _get_redis_ttl(backend, full_key)
    if ttl_seconds is not None:
        if ttl_seconds >= 0:
            print(f"TTL: {ttl_seconds} seconds ({_format_ttl(ttl_seconds)} left)")
        else:
            print("TTL: (key missing in Redis)")
    else:
        if backend_name == "RedisCache":
            print("TTL: (could not read TTL)")
        else:
            print("TTL: (not available for this backend)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect cache state and TTL for a URL path")
    parser.add_argument(
        "path",
        nargs="?",
        default="/salaries/",
        help="URL path (e.g. /salaries/ or /job-titles/)",
    )
    parser.add_argument(
        "--domain",
        default=os.environ.get("SITE_DOMAIN", "localhost"),
        help="Host for cache key (e.g. visa-bulletin.us). Default: SITE_DOMAIN or localhost",
    )
    args = parser.parse_args()
    path = args.path if args.path.startswith("/") else "/" + args.path
    use_https = args.domain != "localhost"
    inspect_path(path, args.domain, use_https)


if __name__ == "__main__":
    main()
    sys.exit(0)
