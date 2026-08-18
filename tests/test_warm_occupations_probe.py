"""The occupation warmer's pass condition is rendered-page latency.

For weeks the warmer logged "warmed 41 occupations in 0.2s — 0 were cold fills"
while /h1b-salary/<occupation>/ was rendering 5-13s on prod. Both statements were
true: the cache keys were present when the cron looked, and Redis (allkeys-lru over
a ~65k-key space) had evicted them again well before the crawl window. A check on
the cache key can only ever report on the moment it runs; a check on the page
reports what a crawler actually waits for.

These tests pin that distinction — a slow page must fail the run.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import SimpleTestCase

from scripts.salary import warm_occupations


class ProbeVerdictTests(SimpleTestCase):
    def _probe_all(self, responses, max_render_ms=1500):
        """Run _probe_all against canned (status, seconds) results per slug."""
        original = warm_occupations._probe_page
        warm_occupations._probe_page = lambda base_url, slug: responses[slug]
        try:
            return warm_occupations._probe_all(
                "http://localhost:8000", list(responses), max_render_ms
            )
        finally:
            warm_occupations._probe_page = original

    def test_fast_pages_pass(self):
        assert self._probe_all({"accountant": (200, 0.12), "cook": (200, 0.31)}) == 0

    def test_a_slow_page_fails_the_run(self):
        # The exact condition that went unreported: the page renders, returns 200,
        # and takes six seconds. A cache-key check calls this healthy.
        verdict = self._probe_all({"accountant": (200, 0.12), "cook": (200, 6.0)})
        assert verdict == 1

    def test_the_measured_prod_tail_would_have_failed(self):
        # The slowest hits from the prod nginx window that opened the ticket.
        verdict = self._probe_all(
            {
                "operations-manager": (200, 13.63),
                "software-engineer": (200, 11.38),
                "network-engineer": (200, 7.30),
            }
        )
        assert verdict == 1

    def test_non_200_fails_even_when_fast(self):
        # A 404 or 500 is instant, so a latency-only check would pass it.
        assert self._probe_all({"accountant": (200, 0.1), "cook": (500, 0.02)}) == 1

    def test_unreachable_page_is_not_a_pass(self):
        # _probe_page returns None when the request never completed; that must not
        # read as a fast page.
        assert self._probe_all({"accountant": (None, 30.0)}) == 1

    def test_no_published_occupations_is_a_failure(self):
        assert self._probe_all({}) == 1


class ProbeRequestTests(SimpleTestCase):
    def test_probe_identifies_as_a_crawler(self):
        # cache_page_skip_bots serves bots from the view, never from the rendered-page
        # cache. A probe with a human UA would measure a cache replay and report the
        # very all-clear this script exists to stop emitting.
        from django_config.cache_utils import is_bot_request

        class _Req:
            META = {"HTTP_USER_AGENT": warm_occupations.PROBE_USER_AGENT}

        assert is_bot_request(_Req())
