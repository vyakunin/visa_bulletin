"""Guard the pre-rendered sitemap's write path.

The renderer replaces the file nginx serves to Google. Its dangerous failure is
not crashing — it is succeeding with a *degraded* render: build_sitemap_xml
catches OperationalError/ProgrammingError per section, logs, and returns [] for
that section, so a DB blip yields a well-formed ~50-URL sitemap. Publishing that
over a good 6.9k-URL file tells Google 6.8k pages vanished.

These tests pin the two gates that prevent it, and the atomicity of the write.
"""

import os
import tempfile

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import SimpleTestCase  # noqa: E402

from scripts.seo.render_sitemap import (  # noqa: E402
    check_safety_gates,
    count_urls,
    write_atomically,
)

MIN_URLS = 1000
MAX_SHRINK = 0.10


class SafetyGateTest(SimpleTestCase):
    def test_healthy_render_passes(self):
        self.assertIsNone(check_safety_gates(6888, 6880, MIN_URLS, MAX_SHRINK))

    def test_degraded_render_is_refused_on_absolute_floor(self):
        """The DB-blip case: sections empty out, ~50 static URLs remain."""
        reason = check_safety_gates(52, 6888, MIN_URLS, MAX_SHRINK)
        self.assertIsNotNone(reason, "a 52-URL sitemap must never overwrite a good one")
        self.assertIn("min-urls", reason)

    def test_partial_loss_is_refused_on_relative_floor(self):
        """Above the absolute floor but a big drop — e.g. employers section empty."""
        reason = check_safety_gates(2600, 6888, MIN_URLS, MAX_SHRINK)
        self.assertIsNotNone(reason, "losing 62% of URLs must not publish silently")
        self.assertIn("max-shrink", reason)

    def test_small_organic_shrink_is_allowed(self):
        """Real churn (a few clusters dropping under the thin-page gate) must pass."""
        self.assertIsNone(check_safety_gates(6820, 6888, MIN_URLS, MAX_SHRINK))

    def test_first_run_with_no_existing_file_passes(self):
        """No file on disk yet: only the absolute floor can apply."""
        self.assertIsNone(check_safety_gates(6888, None, MIN_URLS, MAX_SHRINK))

    def test_first_run_still_honours_the_absolute_floor(self):
        self.assertIsNotNone(check_safety_gates(52, None, MIN_URLS, MAX_SHRINK))


class AtomicWriteTest(SimpleTestCase):
    def test_replaces_existing_file_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sitemap.xml")
            write_atomically(path, "<urlset><loc>a</loc></urlset>")
            write_atomically(path, "<urlset><loc>b</loc></urlset>")

            with open(path, encoding="utf-8") as fh:
                self.assertIn("<loc>b</loc>", fh.read())
            self.assertEqual(
                os.listdir(d),
                ["sitemap.xml"],
                "a leftover .tmp file means a crashed run can strand partial output",
            )

    def test_creates_missing_parent_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "sitemap.xml")
            write_atomically(path, "<urlset></urlset>")
            self.assertTrue(os.path.exists(path))


class CountUrlsTest(SimpleTestCase):
    def test_counts_loc_elements(self):
        self.assertEqual(count_urls("<url><loc>a</loc></url><url><loc>b</loc></url>"), 2)
        self.assertEqual(count_urls("<urlset></urlset>"), 0)
