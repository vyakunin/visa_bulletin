"""Regression: exactly one <h1> per page; the brand masthead is NOT an <h1>.

Every page rendered the site masthead ("U.S. Immigration Data") as an <h1> in
base.html's hero block. On pages that ALSO have their own body <h1> (the
dashboards, the highest-value India EB page) that produced TWO H1s, diluting the
on-page relevance signal. The masthead is now a non-heading element
(div.hero-masthead) so each page emits a single keyword-bearing <h1>. These tests
lock that: a refactor re-promoting the masthead to <h1>, or dropping a page's body
<h1>, breaks them. Notion 38b62b8d.
"""
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse


class SingleH1Test(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()

    def _h1_count(self, content: str) -> int:
        return content.count("<h1")

    def test_brand_masthead_is_not_an_h1(self):
        """The hero masthead must render as a non-heading element, not <h1>."""
        content = self.client.get(reverse("about")).content.decode()
        self.assertIn("U.S. Immigration Data", content)
        self.assertIn('class="hero-masthead', content)
        # The old diluting form must not come back.
        self.assertNotIn('<h1 class="display-4">', content)

    def test_about_has_exactly_one_h1(self):
        content = self.client.get(reverse("about")).content.decode()
        self.assertEqual(self._h1_count(content), 1, "about page must have exactly one <h1>")

    def test_contact_has_exactly_one_h1(self):
        content = self.client.get(reverse("contact")).content.decode()
        self.assertEqual(self._h1_count(content), 1, "contact page must have exactly one <h1>")

    def test_dashboard_root_has_exactly_one_h1(self):
        """The dashboard (the page this lever targets) previously had two H1s
        (brand masthead + page_heading). Now exactly one."""
        content = self.client.get("/").content.decode()
        self.assertEqual(self._h1_count(content), 1, "dashboard must have exactly one <h1>")
