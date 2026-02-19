"""Cache utilities: skip caching for bot traffic so bots don't evict human cache.

When cache is at capacity (e.g. Redis with allkeys-lru), bot traffic hitting
many unique URLs can evict human-requested entries. We avoid populating or
reading cache for requests with known bot User-Agents so cache stays warm for
human traffic.
"""

import re

from django.core.cache import cache
from django.utils.cache import get_cache_key

# Same bot list as nginx gptbot-rate-limit.conf (case-insensitive match).
BOT_USER_AGENT_PATTERNS = (
    r"GPTBot",
    r"Googlebot",
    r"Bingbot",
    r"DuckDuckBot",
    r"Slurp",
    r"Baiduspider",
    r"YandexBot",
    r"facebookexternalhit",
)
_BOT_RE = re.compile("|".join(f"(?:{p})" for p in BOT_USER_AGENT_PATTERNS), re.I)


def is_bot_request(request) -> bool:
    """Return True if request has a known bot User-Agent (do not cache)."""
    ua = request.META.get("HTTP_USER_AGENT") or ""
    if not isinstance(ua, str):
        ua = ""
    return bool(_BOT_RE.search(ua))


def cache_page_skip_bots(timeout):
    """Like @cache_page(timeout) but skip cache get/set for bot User-Agents.

    Bot requests always hit the view and never read or write cache, so they
    don't evict human cache entries when using LRU eviction.
    """
    from functools import wraps

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if is_bot_request(request) or request.method not in ("GET", "HEAD"):
                return view_func(request, *args, **kwargs)
            key = get_cache_key(request, key_prefix="", method="GET", cache=cache)
            if key:
                response = cache.get(key)
                if response is not None:
                    return response
            response = view_func(request, *args, **kwargs)
            if key:
                cache.set(key, response, timeout)
            return response

        return _wrapped_view

    return decorator
