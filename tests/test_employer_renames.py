"""Tests for the curated employer rename / legal-successor cross-link layer.

Exercises the SHIPPED config (facebook-inc -> meta-platforms-inc), so it doubles
as a golden on employer_renames.yaml.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase

from lib.business.salary.employer_renames import get_rename_link
from models.salary import EmployerCluster


class EmployerRenameResolverTest(TestCase):
    def setUp(self):
        cache.clear()
        self.facebook = EmployerCluster.objects.create(
            canonical_name="Facebook, Inc.",
            slug="facebook-inc",
            total_lca_count=533,
            total_perm_count=10253,
        )
        self.meta = EmployerCluster.objects.create(
            canonical_name="Meta Platforms, Inc.",
            slug="meta-platforms-inc",
            total_lca_count=844,
            total_perm_count=1178,
        )

    def test_successor_page_links_back_to_predecessor(self):
        link = get_rename_link(self.meta)
        self.assertIsNotNone(link)
        self.assertEqual(link.other.id, self.facebook.id)
        self.assertTrue(link.viewing_is_successor)

    def test_predecessor_page_links_forward_to_successor(self):
        link = get_rename_link(self.facebook)
        self.assertIsNotNone(link)
        self.assertEqual(link.other.id, self.meta.id)
        self.assertFalse(link.viewing_is_successor)

    def test_combined_totals_sum_both_clusters(self):
        link = get_rename_link(self.meta)
        self.assertEqual(link.combined_lca_count, 533 + 844)
        self.assertEqual(link.combined_perm_count, 10253 + 1178)
        self.assertEqual(link.combined_total, 533 + 10253 + 844 + 1178)

    def test_no_link_for_uncurated_employer(self):
        other = EmployerCluster.objects.create(
            canonical_name="Some Other Co", slug="some-other-co"
        )
        self.assertIsNone(get_rename_link(other))

    def test_no_link_when_other_side_missing(self):
        # Only the successor exists; predecessor cluster was never created.
        self.facebook.delete()
        self.assertIsNone(get_rename_link(self.meta))


class EmployerRenameBannerRenderTest(TestCase):
    """End-to-end: the cross-link banner renders on both profile pages."""

    def setUp(self):
        self.client = Client()
        cache.clear()
        EmployerCluster.objects.create(
            canonical_name="Facebook, Inc.",
            slug="facebook-inc",
            total_lca_count=533,
            total_perm_count=10253,
        )
        EmployerCluster.objects.create(
            canonical_name="Meta Platforms, Inc.",
            slug="meta-platforms-inc",
            total_lca_count=844,
            total_perm_count=1178,
        )

    def test_successor_page_shows_formerly_banner(self):
        resp = self.client.get("/employer/meta-platforms-inc/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Formerly", html)
        self.assertIn("Facebook, Inc.", html)
        self.assertIn("/employer/facebook-inc/", html)
        # Combined lifetime line (533+10253+844+1178 = 12,808).
        self.assertIn("12,808", html)

    def test_predecessor_page_shows_now_filing_as_banner(self):
        resp = self.client.get("/employer/facebook-inc/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Now filing as", html)
        self.assertIn("Meta Platforms, Inc.", html)
        self.assertIn("/employer/meta-platforms-inc/", html)

    def test_uncurated_employer_has_no_banner(self):
        EmployerCluster.objects.create(
            canonical_name="Plain Co LLC", slug="plain-co-llc"
        )
        resp = self.client.get("/employer/plain-co-llc/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn("Formerly", html)
        self.assertNotIn("Now filing as", html)
