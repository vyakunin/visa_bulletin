"""Trust-page scaffolding (E-E-A-T / GEO): /methodology/, /corrections/, /ai-citation/.

Locks the pages added for the trust-scaffolding ticket (Notion 39962b8d…faab):
each renders 200 with a single keyword <h1>, emits VALID page-level JSON-LD, is
linked from the global footer, and appears in the sitemap. Also pins the
named-author Person entity on /about/ and the deliberate HONESTY invariant on the
methodology page — no fabricated "X% accurate" headline (the differentiator vs
competitors' unaudited accuracy marketing; re-adding one is a regression).
"""
import json
import re

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse


def _jsonld_blocks(html: str) -> list[dict]:
    """Every application/ld+json payload on the page, parsed (fails the test if any is invalid)."""
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL
    )
    return [json.loads(b) for b in blocks]


class TrustPagesTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()

    def _get(self, name: str) -> str:
        resp = self.client.get(reverse(name))
        self.assertEqual(resp.status_code, 200, f"{name} must return 200")
        return resp.content.decode()

    def test_methodology_renders_with_single_h1(self):
        html = self._get("methodology")
        self.assertEqual(html.count("<h1"), 1, "methodology must have exactly one <h1>")
        self.assertIn("Methodology", html)

    def test_corrections_renders_with_single_h1(self):
        html = self._get("corrections")
        self.assertEqual(html.count("<h1"), 1, "corrections must have exactly one <h1>")
        self.assertIn("Corrections", html)

    def test_ai_citation_renders_with_single_h1(self):
        html = self._get("ai_citation")
        self.assertEqual(html.count("<h1"), 1, "ai-citation must have exactly one <h1>")
        self.assertIn("Citation", html)

    def test_each_trust_page_emits_valid_jsonld(self):
        """All page JSON-LD must be parseable (a broken block is invisible to Google/LLMs)."""
        for name in ("methodology", "corrections", "ai_citation", "about"):
            html = self._get(name)
            blocks = _jsonld_blocks(html)  # raises on invalid JSON
            self.assertTrue(blocks, f"{name} must emit at least one JSON-LD block")

    def test_about_carries_named_author_person(self):
        """/about/ must expose the named-author Person entity (E-E-A-T)."""
        html = self._get("about")
        author_found = any(
            "Vladimir Yakunin" in json.dumps(b) and "Person" in json.dumps(b)
            for b in _jsonld_blocks(html)
        )
        self.assertTrue(author_found, "about page must carry a named-author Person JSON-LD")

    def test_methodology_names_author_in_schema(self):
        html = self._get("methodology")
        self.assertTrue(
            any("Vladimir Yakunin" in json.dumps(b) for b in _jsonld_blocks(html)),
            "methodology JSON-LD must name its author",
        )

    def test_methodology_has_no_fabricated_accuracy_headline(self):
        """HONESTY INVARIANT: the model only ~ties a naive baseline on most series
        (baseline_comparison.json), so the page must NOT claim a vanity "X% accurate"
        figure. Re-introducing one is a regression, not a copy tweak."""
        html = self._get("methodology").lower()
        # No "<n>% accurate" / "accuracy of <n>%" marketing claim.
        self.assertIsNone(
            re.search(r"\d{1,3}\s*%\s*accura", html),
            "methodology must not advertise an 'N% accurate' headline",
        )
        self.assertIsNone(
            re.search(r"accura\w*\s*(?:of|:)?\s*\d{1,3}\s*%", html),
            "methodology must not advertise an 'accuracy of N%' headline",
        )
        # It must still be transparent about accuracy (backtesting language present).
        self.assertIn("backtest", html)

    def test_footer_links_all_trust_pages(self):
        """Trust pages must be reachable from the global footer on every page."""
        html = self._get("about")  # footer is in base.html, present on any page
        for path in ("/methodology/", "/corrections/", "/ai-citation/"):
            self.assertIn(f'href="{path}"', html, f"footer must link {path}")

    def test_trust_pages_in_sitemap(self):
        resp = self.client.get(reverse("sitemap"))
        self.assertEqual(resp.status_code, 200)
        xml = resp.content.decode()
        for path in ("/methodology/", "/corrections/", "/ai-citation/"):
            self.assertIn(path, xml, f"sitemap must include {path}")
