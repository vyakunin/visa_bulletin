"""
Basic view tests for dashboard, robots.txt, and sitemap

Note: Full database integration tests require Django test runner setup.
These tests verify basic view functionality with mocks.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

from webapp.views.seo.sitemaps import robots_view, sitemap_view

_DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "webapp"
    / "templates"
    / "webapp"
    / "dashboard.html"
)


class TestDashboardBasic(unittest.TestCase):
    """Basic dashboard view tests - documented for future expansion"""

    def test_placeholder(self):
        """Placeholder - full integration tests require Django test runner setup"""
        # TODO: Add full database integration tests when test infrastructure is ready
        self.assertTrue(True)

    def test_priority_date_inbound_links_block_present(self):
        """The EB country dashboard links out to the per-EB priority-date landing
        pages (SEO internal-link mesh). Guards the template block + view context key.
        """
        src = _DASHBOARD_TEMPLATE.read_text()
        self.assertIn("priority_date_links", src)
        self.assertIn("link.url", src)

    def test_country_dashboard_links_block_present(self):
        """The dashboard renders crawlable <a> links to the sibling per-country
        dashboards (India/China/Mexico/Philippines/All) so search engines reach the
        high-intent country pages, which were previously only behind the JS country
        <select>. Guards the template block + view context key. Notion 38b62b8d.
        """
        src = _DASHBOARD_TEMPLATE.read_text()
        self.assertIn("country_dashboard_links", src)
        self.assertIn("link.active", src)

    def test_country_dashboard_label_map_covers_every_nav_slug(self):
        """Regression: `_DASHBOARD_COUNTRY_LABELS` must define a label for every slug
        the view feeds into the country-dashboard nav. A missing entry NameErrors /
        KeyErrors on every EB & FS dashboard render (the core-audience pages). Also
        asserts each label-map slug is a real Country URL slug so the generated
        /<category>/<slug>/ URLs resolve.
        """
        from models.enums.country import Country, _VALUE_TO_SLUG
        from webapp.views.bulletin.dashboard import _DASHBOARD_COUNTRY_LABELS

        # Every slug the view's nav_slugs lists (EB + the FS-only extra) must be keyed.
        nav_slugs = {"india", "china", "mexico", "philippines", "all",
                     "el_salvador_guatemala_honduras"}
        missing = nav_slugs - set(_DASHBOARD_COUNTRY_LABELS)
        self.assertFalse(missing, f"label map missing nav slugs: {missing}")

        # Every label-map slug is a real country slug (so the URL resolves).
        valid_slugs = set(_VALUE_TO_SLUG.values())
        bogus = set(_DASHBOARD_COUNTRY_LABELS) - valid_slugs
        self.assertFalse(bogus, f"label map has non-country slugs: {bogus}")
        # And each resolves back to a valid Country value.
        for slug in _DASHBOARD_COUNTRY_LABELS:
            self.assertIsNotNone(Country.from_string(slug))

    def test_chart_doubleclick_reset_enabled(self):
        """Regression: the dashboard chart's double-tap/double-click reset must stay
        enabled. 'doubleClick': false disabled it entirely (nothing emitted the
        autorange event the plotly_relayout handler relies on), so double-tap did
        nothing. It must trigger autorange so the handler re-applies the smart range.
        """
        src = _DASHBOARD_TEMPLATE.read_text()
        self.assertIn("'doubleClick': 'autosize'", src)
        self.assertNotIn("'doubleClick': false", src)


class TestRobotsTxtView(unittest.TestCase):
    """Test robots.txt view"""

    def test_robots_txt_returns_text(self):
        """robots.txt returns text with sitemap"""
        request = Mock()
        request.build_absolute_uri.return_value = "http://testserver/sitemap.xml"

        response = robots_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        content = response.content.decode("utf-8")
        self.assertIn("User-agent: *", content)
        self.assertIn("Allow: /", content)
        self.assertIn("Sitemap:", content)


class TestSitemapView(unittest.TestCase):
    """Test sitemap.xml view"""

    def test_sitemap_returns_xml(self):
        """Sitemap returns valid XML"""
        request = Mock()
        request.build_absolute_uri.return_value = "http://testserver/"

        response = sitemap_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        content = response.content.decode("utf-8")

        # Should be valid, parseable XML
        try:
            root = ET.fromstring(content)
            # Verify it's a urlset element
            self.assertTrue(root.tag.endswith("urlset"))
            # Should have url children
            urls = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url")
            self.assertGreater(len(urls), 0, "Sitemap should contain at least one URL")
            # Each url should have a loc element
            for url in urls:
                loc = url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                self.assertIsNotNone(loc, "Each URL should have a loc element")
        except ET.ParseError as e:
            self.fail(f"Sitemap is not valid XML: {e}")

    def test_sitemap_includes_key_pages(self):
        """Sitemap includes key pages"""
        request = Mock()
        request.build_absolute_uri.return_value = "http://testserver/"

        response = sitemap_view(request)
        content = response.content.decode("utf-8")

        # Parse XML properly
        root = ET.fromstring(content)
        # Extract all loc URLs
        locs = [
            loc.text
            for loc in root.findall(
                ".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
            )
        ]
        all_urls = "\n".join(locs)

        # Should include key pages
        self.assertIn("/faq/", all_urls)
        self.assertIn("/about/", all_urls)
        self.assertIn("/contact/", all_urls)
        self.assertIn("employment-based", all_urls)
        self.assertIn("family-sponsored", all_urls)


if __name__ == "__main__":
    unittest.main()
