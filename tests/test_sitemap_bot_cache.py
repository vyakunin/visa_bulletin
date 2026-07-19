"""Regression: /sitemap.xml must be served from cache to crawlers.

The sitemap is the site's most expensive response (~21.7s uncached, ~0.03s
warm, 1.3 MB). It was decorated with @cache_page_skip_bots, which bypasses the
page cache for any UA in BOT_USER_AGENT_PATTERNS — so Googlebot and bingbot,
the only clients that meaningfully request a sitemap, re-rendered it in full on
every crawl. Measured 2026-07-19 in nginx: every /sitemap.xml request over 5s
in a 24h window was a crawler (Googlebot x2, bingbot x2, Claude-SearchBot x4),
with four 499s where the crawler gave up at its own 10s timeout, and each
render pinning a gunicorn worker.

The bot-skip decorator exists to stop a crawler walking thousands of distinct
profile URLs from evicting the human working set under Redis allkeys-lru. That
reasoning does not apply to a single fixed path, so the SEO views use
cache_page_all_agents instead.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.http import HttpResponse  # noqa: E402
from django.test import (  # noqa: E402
    RequestFactory,
    SimpleTestCase,
    override_settings,
)

from django_config.cache_utils import (  # noqa: E402
    cache_page_all_agents,
    cache_page_skip_bots,
    is_bot_request,
)

GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BINGBOT = (
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
    "bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36"
)
HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0"

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-sitemap-bot-cache",
    }
}


def _counting_view():
    """A view that records how many times it actually executed."""
    calls = []

    def view(request):
        calls.append(1)
        return HttpResponse(f"render-{len(calls)}", content_type="application/xml")

    return view, calls


@override_settings(CACHES=LOCMEM)
class SitemapBotCacheTest(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.rf = RequestFactory()

    def _get(self, view, ua):
        return view(self.rf.get("/sitemap.xml", HTTP_USER_AGENT=ua))

    def test_crawler_uas_are_recognized_as_bots(self):
        """Guard the premise: these UAs really do hit the bot branch."""
        for ua in (GOOGLEBOT, BINGBOT):
            self.assertTrue(
                is_bot_request(self.rf.get("/sitemap.xml", HTTP_USER_AGENT=ua)),
                f"expected {ua[:40]!r} to match BOT_USER_AGENT_PATTERNS",
            )

    def test_googlebot_is_served_from_cache(self):
        """The bug: Googlebot must not re-render the sitemap on every fetch."""
        view, calls = _counting_view()
        cached = cache_page_all_agents(3600)(view)

        first = self._get(cached, GOOGLEBOT)
        second = self._get(cached, GOOGLEBOT)

        self.assertEqual(
            len(calls),
            1,
            "sitemap re-rendered for a second Googlebot fetch — the ~21.7s "
            "cold render is back on the crawler path",
        )
        self.assertEqual(first.content, second.content)

    def test_cache_is_shared_across_bot_and_human(self):
        """One key per path: a warm entry serves crawlers and humans alike."""
        view, calls = _counting_view()
        cached = cache_page_all_agents(3600)(view)

        self._get(cached, HUMAN)
        self._get(cached, GOOGLEBOT)
        self._get(cached, BINGBOT)

        self.assertEqual(len(calls), 1)

    def test_skip_bots_decorator_still_bypasses_for_bots(self):
        """The open-URL-space views keep the eviction guard."""
        view, calls = _counting_view()
        cached = cache_page_skip_bots(3600)(view)

        self._get(cached, GOOGLEBOT)
        self._get(cached, GOOGLEBOT)

        self.assertEqual(len(calls), 2, "skip_bots must not start caching bots")

    def test_skip_bots_decorator_still_caches_humans(self):
        view, calls = _counting_view()
        cached = cache_page_skip_bots(3600)(view)

        self._get(cached, HUMAN)
        self._get(cached, HUMAN)

        self.assertEqual(len(calls), 1)

    def test_seo_views_use_the_bot_caching_decorator(self):
        """Pin the wiring, so a future edit can't silently revert the fix."""
        import inspect

        from webapp.views.seo import sitemaps

        src = inspect.getsource(sitemaps)
        self.assertIn("cache_page_all_agents", src)
        self.assertNotIn(
            "cache_page_skip_bots",
            src,
            "a fixed-path SEO view went back to the bot-skipping cache",
        )
