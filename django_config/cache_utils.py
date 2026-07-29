"""Cache utilities: skip caching for bot traffic so bots don't evict human cache.

When cache is at capacity (e.g. Redis with allkeys-lru), bot traffic hitting
many unique URLs can evict human-requested entries. We avoid populating or
reading cache for requests with known bot User-Agents so cache stays warm for
human traffic.
"""

import hashlib
import re

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


def _make_cache_key(request) -> str:
    """Build a cache key from the full URL path + query string.

    Does not depend on Django's UpdateCacheMiddleware or Vary headers.
    Uses MD5 hash to keep keys short and avoid special characters.
    """
    url = request.get_full_path()
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return f"page_cache.{request.method}.{url_hash}"


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
            response = cache.get(key)
            if response is not None:
                return response
            response = view_func(request, *args, **kwargs)
            if hasattr(response, "status_code") and response.status_code == 200:
                cache.set(key, response, timeout)
            return response

        return _wrapped_view

    return decorator


def cache_page_skip_bots(timeout):
    """Like @cache_page(timeout) but skip cache get/set for bot User-Agents.

    Bot requests always hit the view and never read or write cache, so they
    don't evict human cache entries when using LRU eviction.

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
