"""Cache utilities: skip caching for bot traffic so bots don't evict human cache.

When cache is at capacity (e.g. Redis with allkeys-lru), bot traffic hitting
many unique URLs can evict human-requested entries. We avoid populating or
reading cache for requests with known bot User-Agents so cache stays warm for
human traffic.
"""

import hashlib
import pickle
import re
import zlib

from django.core.cache import cache

# Case-insensitive match against the User-Agent.
#
# Most of this is a GENERIC test rather than a roster of crawler names, because
# the roster is what rots: a hand-maintained allowlist only ever covers the
# crawlers someone thought of, and every one it misses writes into a page cache
# that is evicting under LRU. Measured on prod 2026-07-27 over 24h, when this
# was a 9-name list: 40,333 requests across 31,184 distinct URLs came from
# crawlers the list did not name (Amzn-SearchBot 16.7k, Claude-SearchBot 7.0k,
# AhrefsBot 5.8k, proximic, Mediapartners-Google, IAS, PetalBot, ChatGPT-User,
# OAI-SearchBot) against 9,651 distinct human URLs — so ~76% of the cache's
# write pressure was crawler traffic, and vb_redis sat pinned at its cap with a
# 59% miss rate while real users waited 10-25s on cold renders.
#
# Nearly every crawler self-identifies in one of a few ways, so match the SHAPE:
# `bot` as a whole word (Googlebot/2.1, Amzn-SearchBot), crawler, spider,
# scraper, slurp, plus the bare HTTP clients that never render a page anyway.
# `bot\b` deliberately requires a word boundary so ordinary words ending in
# other letters cannot match.
_GENERIC_BOT_RE = r"bot\b|crawler|spider|scraper|slurp|feedfetcher"
_HTTP_CLIENT_RE = r"python-requests|python-urllib|curl/|wget/|go-http-client|okhttp|java/|libwww-perl"

# Crawlers that do NOT self-identify by any of the shapes above, so they have to
# be named. HealthCheck is ours: docker-compose healthchecks hit localhost with
# no real Host header and would bake "localhost:8000" into <link rel="canonical">.
NAMED_BOT_USER_AGENT_PATTERNS = (
    r"facebookexternalhit",
    r"meta-externalagent",
    r"Mediapartners-Google",  # AdSense crawler
    r"ChatGPT-User",
    r"anthropic-ai",
    r"proximic",  # comScore
    r"ias[-_](?:ie|va)",  # Integral Ad Science
    r"ia_archiver",
    r"HealthCheck",
)

BOT_USER_AGENT_PATTERNS = (
    _GENERIC_BOT_RE,
    _HTTP_CLIENT_RE,
) + NAMED_BOT_USER_AGENT_PATTERNS
_BOT_RE = re.compile("|".join(f"(?:{p})" for p in BOT_USER_AGENT_PATTERNS), re.I)


def is_bot_request(request) -> bool:
    """Return True if request has a known bot User-Agent (do not cache)."""
    ua = request.META.get("HTTP_USER_AGENT") or ""
    if not isinstance(ua, str):
        ua = ""
    return bool(_BOT_RE.search(ua))


def _url_hash(request) -> str:
    return hashlib.md5(request.get_full_path().encode()).hexdigest()


def _make_cache_key(request) -> str:
    """Build a cache key from the full URL path + query string.

    Does not depend on Django's UpdateCacheMiddleware or Vary headers.
    Uses MD5 hash to keep keys short and avoid special characters.
    """
    return f"page_cache.zlib.{request.method}.{_url_hash(request)}"


def _make_seen_key(request) -> str:
    return f"page_cache.seen.{request.method}.{_url_hash(request)}"


# scripts/warm_cache.sh sends this in its User-Agent; a warm request stores on its
# first render, since the warmer requests each page once.
CACHE_WARMER_UA_TOKEN = "visa-bulletin-cache-warmer/"


def is_cache_warmer_request(request) -> bool:
    return CACHE_WARMER_UA_TOKEN in (request.META.get("HTTP_USER_AGENT") or "")


def _admit(request, timeout) -> bool:
    """Count this miss; True once the URL has missed PAGE_CACHE_ADMIT_AFTER times.

    Measured on prod 2026-11-01 over 8.5h: 25.6k distinct cacheable URLs from
    26.2k requests, 85% of them a scraper walking /employers/ pagination. Storing
    from the 2nd request left 113 entries and kept 79% of the cache hits.
    """
    from django.conf import settings

    admit_after = settings.PAGE_CACHE_ADMIT_AFTER
    if admit_after <= 1 or is_cache_warmer_request(request):
        return True
    seen_key = _make_seen_key(request)
    if cache.add(seen_key, 1, timeout):
        return False
    try:
        seen = cache.incr(seen_key)
    except ValueError:  # the counter expired between add() and incr()
        cache.add(seen_key, 1, timeout)
        return False
    return seen >= admit_after


# Rendered pages average ~195 KB and compress 5.3-5.6x. Stored raw they filled
# vb_redis's 1.5G, and allkeys-lru evicted entries within ~4h of a 24h TTL.
def _compress_response(response) -> bytes:
    return zlib.compress(pickle.dumps(response, pickle.HIGHEST_PROTOCOL))


def _decompress_response(blob: bytes):
    return pickle.loads(zlib.decompress(blob))


def _cache_page(timeout, *, skip_bots: bool):
    """Shared body of the two page-cache decorators below.

    Uses a simple URL-based cache key (not Django's Vary-header system) so
    it works without UpdateCacheMiddleware/FetchFromCacheMiddleware.
    """
    from functools import wraps

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.method not in ("GET", "HEAD"):
                return view_func(request, *args, **kwargs)
            if skip_bots and is_bot_request(request):
                return view_func(request, *args, **kwargs)
            key = _make_cache_key(request)
            blob = cache.get(key)
            if blob is not None:
                return _decompress_response(blob)
            response = view_func(request, *args, **kwargs)
            if getattr(response, "status_code", None) != 200:
                return response
            # An all-agents view is one fixed path; only an open URL space needs
            # the admission threshold.
            if not skip_bots or _admit(request, timeout):
                cache.set(key, _compress_response(response), timeout)
                if skip_bots:
                    cache.delete(_make_seen_key(request))
            return response

        return _wrapped_view

    return decorator


def cache_page_skip_bots(timeout):
    """Like @cache_page(timeout) but skip cache get/set for bot User-Agents.

    Bot requests always hit the view and never read or write cache, so they
    don't evict human cache entries when using LRU eviction. A page is stored
    only on its PAGE_CACHE_ADMIT_AFTER-th miss within `timeout`, so a
    browser-UA scraper walking distinct URLs writes counters, not pages.

    Use this for views with a LARGE, OPEN URL SPACE — employer/job-title
    profiles, faceted salary search — where a crawler walking thousands of
    distinct URLs would otherwise flush the human working set out of Redis.
    """
    return _cache_page(timeout, skip_bots=True)


def cache_page_all_agents(timeout):
    """Like @cache_page(timeout), caching for bots as well as humans.

    For a FIXED-PATH view whose audience IS crawlers — /sitemap.xml,
    /llms.txt — the bot-skip rationale inverts. Those URLs are one
    cache key each, so they cannot cause the many-unique-URL LRU eviction that
    `cache_page_skip_bots` guards against; skipping cache there just guarantees
    the site's single most expensive response is re-rendered from scratch on
    every crawl, by the only clients that ever request it.

    Concretely (measured 2026-07-19): /sitemap.xml renders in ~21.7s uncached
    and ~0.03s warm. Under `cache_page_skip_bots`, Googlebot and bingbot are on
    the permanent 21.7s path — long enough that crawlers were disconnecting at
    their 10s timeout (nginx 499) and each render pinned a gunicorn worker.

    NOT for a view whose body depends on the request HOST: `_make_cache_key`
    keys on the path alone, so every hostname reaching this stack shares one
    entry (that is why /robots.txt, which now varies by host, is uncached —
    see `webapp.views.seo.sitemaps.robots_view`).
    """
    return _cache_page(timeout, skip_bots=False)
