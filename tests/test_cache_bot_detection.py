"""Regression: crawlers must not populate the human page cache.

`cache_page_skip_bots` exists so a crawler walking thousands of distinct
profile URLs cannot flush the human working set out of Redis under
allkeys-lru. That only holds if `is_bot_request` actually recognises the
crawlers hitting the site.

It stopped holding. The detector was a 9-name allowlist (GPTBot, Googlebot,
Bingbot, DuckDuckBot, Slurp, Baiduspider, YandexBot, facebookexternalhit,
HealthCheck) while nginx's rate-limit map had grown to ~30 names, and the real
crawler population had grown past both. Measured on prod over 24h on
2026-07-27:

    named by the list      14,985 requests / 11,448 distinct URLs  (skipped)
    NOT named by the list  40,333 requests / 31,184 distinct URLs  (cached!)
    human                  11,883 requests /  9,651 distinct URLs

So ~40k distinct crawler URLs competed with ~9.7k human URLs for a cache
holding ~8.3k keys: vb_redis pinned at its 512M cap, 59% keyspace miss rate,
and 14 requests over 10s in one day — worst 24.7s on /employment-based/china/,
all HTTP 200, i.e. real users sitting through cold renders.

The UA strings below are verbatim from that prod window, so this test pins the
actual population rather than a plausible-looking sample. The human cases are
the other half of the guard: matching too broadly would push real visitors onto
the permanently-uncached path, converting a cache problem into a slower one.
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
    cache_page_skip_bots,
    is_bot_request,
)

# Verbatim from prod nginx, 24h ending 2026-07-27. Every one of these was
# READING AND WRITING the page cache before this fix.
CRAWLERS_MISSED_BY_THE_OLD_LIST = {
    "Amzn-SearchBot": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
        "Amzn-SearchBot/0.1) Chrome/119.0.6045.214 Safari/537.36"
    ),
    "Claude-SearchBot": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
        "Claude-SearchBot/1.0; +searchbot@anthropic.com)"
    ),
    "AhrefsBot": "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
    "proximic": "Mozilla/5.0 (compatible; proximic; +https://www.comscore.com/Web-Crawler)",
    "Mediapartners-Google": "Mediapartners-Google",
    "ias-ie": (
        "ias-ie/3.3 (former https://www.admantx.com + https://integralads.com/about-ias/)"
    ),
    "ias-va": (
        "ias-va/3.3 (former https://www.admantx.com + https://integralads.com/about-ias/)"
    ),
    "IAS Crawler": (
        "IAS Crawler (ias_crawler; http://integralads.com/site-indexing-policy/)"
    ),
    "PetalBot": (
        "Mozilla/5.0 (Linux; Android 7.0;) AppleWebKit/537.36 (HTML, like Gecko) "
        "Mobile Safari/537.36 (compatible; PetalBot;+https://webmaster.petalsearch.com/site/petalbot)"
    ),
    "ChatGPT-User": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
        "ChatGPT-User/1.0; +https://openai.com/bot"
    ),
    "OAI-SearchBot": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36; compatible; "
        "OAI-SearchBot/1.4; +https://openai.com/searchbot"
    ),
}

# Already covered before the fix — must stay covered.
CRAWLERS_ALREADY_COVERED = {
    "Googlebot": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.7871.128 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "bingbot": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
        "bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36"
    ),
    "Baiduspider": (
        "Mozilla/5.0 (compatible; Baiduspider/2.0; "
        "+http://www.baidu.com/search/spider.html)"
    ),
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.1; +https://openai.com/gptbot)",
    "facebookexternalhit": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "HealthCheck": "HealthCheck/1.0",
}

# Real visitors, verbatim from the same prod window. None of these may match:
# a false positive here puts a human on the permanently-uncached path.
HUMANS = {
    "chrome-win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "chrome-mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "edge-win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
    ),
    "safari-iphone": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "firefox": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "android-chrome": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
    ),
    # `bot` as a substring of a longer word must NOT trip the word-boundary match.
    "substring-not-a-bot": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BotswanaBrowser/2.1 Safari/537.36"
    ),
    "empty": "",
}

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache-bot-detection",
    }
}


def _counting_view():
    """A view that records how many times it actually executed."""
    calls = []

    def view(request):
        calls.append(1)
        return HttpResponse(f"render-{len(calls)}")

    return view, calls


class BotDetectionTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, ua):
        return self.factory.get("/employer/some-employer/", HTTP_USER_AGENT=ua)

    def test_crawlers_missed_by_the_old_list_are_detected(self):
        for name, ua in CRAWLERS_MISSED_BY_THE_OLD_LIST.items():
            with self.subTest(crawler=name):
                self.assertTrue(
                    is_bot_request(self._request(ua)),
                    f"{name} would populate the page cache and evict human entries",
                )

    def test_previously_covered_crawlers_stay_detected(self):
        for name, ua in CRAWLERS_ALREADY_COVERED.items():
            with self.subTest(crawler=name):
                self.assertTrue(is_bot_request(self._request(ua)), name)

    def test_real_visitors_are_not_treated_as_bots(self):
        for name, ua in HUMANS.items():
            with self.subTest(visitor=name):
                self.assertFalse(
                    is_bot_request(self._request(ua)),
                    f"{name} would be forced onto the uncached path",
                )

    def test_missing_user_agent_is_not_a_bot(self):
        self.assertFalse(is_bot_request(self.factory.get("/")))


class SkipBotsCachingTest(SimpleTestCase):
    """End-to-end: the decorator must not store a crawler's render."""

    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(CACHES=LOCMEM)
    def test_crawler_never_populates_the_cache(self):
        from django.core.cache import cache

        cache.clear()
        view, calls = _counting_view()
        cached = cache_page_skip_bots(60)(view)
        ua = CRAWLERS_MISSED_BY_THE_OLD_LIST["Amzn-SearchBot"]

        for _ in range(3):
            cached(self.factory.get("/employer/x/", HTTP_USER_AGENT=ua))
        self.assertEqual(len(calls), 3, "crawler requests must always hit the view")

        # The human arriving after the crawler still faces a cold cache — proof
        # nothing the crawler rendered was stored under the human's key either.
        human = self.factory.get("/employer/x/", HTTP_USER_AGENT=HUMANS["chrome-win"])
        first = cached(human)
        self.assertEqual(len(calls), 4)
        second = cached(
            self.factory.get("/employer/x/", HTTP_USER_AGENT=HUMANS["chrome-mac"])
        )
        self.assertEqual(len(calls), 4, "the human render must be served from cache")
        self.assertEqual(first.content, second.content)
