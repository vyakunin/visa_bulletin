"""robots.txt must only invite crawling on the canonical production hosts.

Regression guard: staging.visa-bulletin.us served a byte-identical copy of
production's robots.txt — ``Allow: /`` plus ``Sitemap:
https://staging.visa-bulletin.us/sitemap.xml`` — so the staging mirror
advertised itself as a crawlable site with its own sitemap. It stayed out of the
index only because Google elected the production URL as canonical for the
duplicate content, which is Google's inference, not an instruction from us.

Also pins that the view is NOT wrapped in a path-keyed page cache: the body now
varies by host while ``cache_utils._make_cache_key`` hashes the path only, so a
cached entry would be shared across hostnames and a localhost health check could
poison the production response.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client, SimpleTestCase, override_settings  # noqa: E402

from webapp.views.seo.sitemaps import robots_view  # noqa: E402

# The view is reached over the test client (scheme http), and a non-canonical
# host is rejected by ALLOWED_HOSTS with a 400 before the view ever runs — so
# every host under test has to be allowed for the view's own logic to be what
# is being measured.
_TEST_HOSTS = [
    *sorted(settings.CANONICAL_HOSTS),
    "staging.visa-bulletin.us",
    "preview.visa-bulletin.us",
    "localhost",
    "127.0.0.1",
]


@override_settings(ALLOWED_HOSTS=_TEST_HOSTS)
class RobotsCanonicalHostTests(SimpleTestCase):
    def _body(self, host: str) -> str:
        return Client().get("/robots.txt", HTTP_HOST=host).content.decode()

    def test_canonical_host_advertises_sitemap_and_allows_crawling(self):
        for host in sorted(settings.CANONICAL_HOSTS):
            with self.subTest(host=host):
                body = self._body(host)
                self.assertIn("Allow: /", body)
                self.assertIn(f"://{host}/sitemap.xml", body)
                self.assertNotIn("Disallow: /\n", body)

    def test_staging_host_is_disallowed_and_advertises_no_sitemap(self):
        body = self._body("staging.visa-bulletin.us")
        self.assertIn("User-agent: *", body)
        self.assertIn("Disallow: /", body)
        self.assertNotIn("Allow: /", body)
        self.assertNotIn("Sitemap:", body)
        self.assertNotIn("staging.visa-bulletin.us/sitemap.xml", body)

    def test_other_non_canonical_hosts_are_disallowed(self):
        for host in ("localhost", "127.0.0.1", "preview.visa-bulletin.us"):
            with self.subTest(host=host):
                body = self._body(host)
                self.assertIn("Disallow: /", body)
                self.assertNotIn("Sitemap:", body)

    def test_host_with_port_is_matched_on_hostname_only(self):
        self.assertIn("Allow: /", self._body("visa-bulletin.us:443"))
        self.assertIn("Disallow: /", self._body("staging.visa-bulletin.us:443"))

    def test_view_is_not_page_cached(self):
        # A path-keyed cache would serve one host's body to every host.
        self.assertFalse(
            hasattr(robots_view, "__wrapped__"),
            "robots_view must not be wrapped in a path-keyed page cache; "
            "its body varies by Host and _make_cache_key ignores the host.",
        )


class CanonicalHostSettingTests(SimpleTestCase):
    def test_canonical_hosts_are_servable(self):
        # Outside the override above: the real settings must actually serve the
        # hosts they declare canonical, or robots.txt advertises a 400.
        for host in settings.CANONICAL_HOSTS:
            self.assertIn(host, settings.ALLOWED_HOSTS)
