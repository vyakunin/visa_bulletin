"""One stable keyword-rich prediction URL across the whole lifecycle.

Regression guard for the peak-intent 301 wound: the evergreen forecast slug
``/predictions/<monthname>-<year>/`` (e.g. ``/predictions/november-2025/``) used
to 301 to the cold bare-numeric archive URL ``/predictions/2025-11/`` at exactly
the moment the real bulletin published — bleeding the Reddit-seeded, ranking-
established forecast URL's equity onto a fresh URL when "visa bulletin <month>
<year>" search intent spikes.

The fix: the monthname slug is CANONICAL across the entire lifecycle. Before the
drop it renders the forecast; after the drop it renders the accuracy archive AT
THE SAME URL — it never 301s. The bare-numeric ``/predictions/<y>-<m>/`` and the
``/predictions/employment_based/<y>-<m>/`` alias each 301 to the slug in a SINGLE
hop, and the sitemap emits the slug so sitemap == canonical.

family_sponsored keeps its own ``/predictions/family_sponsored/<y>-<m>/`` segment
(distinct content, self-canonical, already stable across the lifecycle — it never
had a forecast-slug→numeric flip to fix).
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase
from django.urls import reverse

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff


class TestStablePredictionUrl(TestCase):
    def setUp(self):
        # June 2025 = an older published month; November 2025 = latest published.
        self.jun = Bulletin.objects.create(publication_date=date(2025, 6, 1))
        self.nov = Bulletin.objects.create(publication_date=date(2025, 11, 1))

    # (a) bare-numeric 301s to the slug in a SINGLE hop -------------------------
    def test_numeric_301s_to_slug_single_hop(self):
        resp = self.client.get("/predictions/2025-11/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/predictions/november-2025/")
        # Single hop: the redirect target renders 200, it does NOT redirect again.
        final = self.client.get(resp["Location"])
        self.assertEqual(final.status_code, 200)

    def test_historical_numeric_301s_to_slug_single_hop(self):
        resp = self.client.get("/predictions/2025-6/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/predictions/june-2025/")
        self.assertEqual(self.client.get(resp["Location"]).status_code, 200)

    # (e) employment_based/<y>-<m> alias collapses to the slug in ONE hop -------
    def test_employment_based_alias_301s_to_slug_single_hop(self):
        resp = self.client.get("/predictions/employment_based/2025-11/")
        self.assertEqual(resp.status_code, 301)
        # Directly to the slug — NOT chained through the bare-numeric URL.
        self.assertEqual(resp["Location"], "/predictions/november-2025/")
        self.assertEqual(self.client.get(resp["Location"]).status_code, 200)

    # (b) slug is self-canonical in the PUBLISHED / archive phase --------------
    def test_slug_renders_archive_self_canonical_after_publication(self):
        resp = self.client.get("/predictions/november-2025/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" href="http://testserver/predictions/november-2025/">',
            resp.content,
        )
        # It renders the accuracy archive (predictions-vs-actual), not the forecast.
        self.assertIn(b"November 2025 Visa Bulletin", resp.content)

    def test_historical_slug_renders_archive_self_canonical(self):
        resp = self.client.get("/predictions/june-2025/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" href="http://testserver/predictions/june-2025/">',
            resp.content,
        )

    # (c) THE key regression: NO 301 fires on the slug at publication ----------
    def test_no_301_on_slug_at_publication(self):
        # The month is published (self.nov exists) yet the slug URL renders in
        # place — the whole point. A 301 here is the wound this fix removes.
        resp = self.client.get("/predictions/november-2025/")
        self.assertNotEqual(resp.status_code, 301)
        self.assertEqual(resp.status_code, 200)

    # (b) slug is self-canonical in the FORECAST phase too ---------------------
    def test_slug_self_canonical_in_forecast_phase(self):
        # December 2025 is the upcoming (unpublished) month: latest (Nov) + 1.
        pb = PredictedBulletin.objects.create(
            target_bulletin_month=date(2025, 12, 1),
            prediction_date=date(2025, 11, 15),
        )
        PredictedCutoff.objects.create(
            bulletin=pb,
            visa_class="2nd",
            country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value,
            predicted_date=date(2020, 3, 1),
            model_name="regime_switched",
            expert_predictions={},
        )
        VisaCutoffDate.objects.create(
            bulletin=self.nov,
            visa_category="employment_based",
            visa_class="2nd",
            action_type=ActionType.FINAL_ACTION.value,
            country=Country.INDIA.value,
            cutoff_value="01JAN20",
            cutoff_date=date(2020, 1, 1),
            is_current=False,
            is_unavailable=False,
        )
        resp = self.client.get("/predictions/december-2025/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            b'rel="canonical" href="http://testserver/predictions/december-2025/"',
            resp.content,
        )

    # (d) sitemap emits the slug, NOT the bare-numeric archive URL -------------
    def test_sitemap_emits_slug_not_numeric(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("<loc>http://testserver/predictions/november-2025/</loc>", body)
        self.assertIn("<loc>http://testserver/predictions/june-2025/</loc>", body)
        # The old bare-numeric archive loc must be gone (sitemap == canonical).
        self.assertNotIn("<loc>http://testserver/predictions/2025-11/</loc>", body)
        self.assertNotIn("<loc>http://testserver/predictions/2025-6/</loc>", body)

    # family_sponsored keeps its own segment — unchanged, self-canonical -------
    def test_family_sponsored_unchanged_self_canonical(self):
        resp = self.client.get("/predictions/family_sponsored/2025-11/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" '
            b'href="http://testserver/predictions/family_sponsored/2025-11/">',
            resp.content,
        )


class TestUpcomingForecastInboundLinks(TestCase):
    """The upcoming-month forecast page must be REACHABLE from indexed content.

    A stable, self-canonical URL in the sitemap is not enough on its own: with no
    inbound internal link, Google left ``/predictions/september-2026/`` at "URL is
    unknown to Google" for two weeks while the already-indexed August archive page
    pointed its own "See the live forecast for the next bulletin" link at the
    homepage instead. The forecast has to be crawled and ranked BEFORE the
    bulletin drops, because the anticipation wave peaks in the days before
    publication — so the link is load-bearing SEO, not decoration.
    """

    def setUp(self):
        self.aug = Bulletin.objects.create(publication_date=date(2026, 8, 1))
        self.jun = Bulletin.objects.create(publication_date=date(2026, 6, 1))

    def test_latest_archive_page_links_to_upcoming_forecast(self):
        body = self.client.get("/predictions/august-2026/").content.decode()
        self.assertIn('href="/predictions/september-2026/"', body)
        # The prominent pre-drop banner, not just an inline link.
        self.assertIn("September 2026 predictions are up", body)

    def test_archive_forecast_link_does_not_point_at_the_homepage(self):
        """The exact defect: the 'next bulletin forecast' link went to `/`."""
        body = self.client.get("/predictions/august-2026/").content.decode()
        self.assertNotIn(
            '<a href="/?category=employment_based&country=all" class="small">', body
        )

    def test_older_archive_month_links_forward_without_the_banner(self):
        body = self.client.get("/predictions/june-2026/").content.decode()
        self.assertIn('href="/predictions/september-2026/"', body)
        # The loud banner belongs only on the newest month.
        self.assertNotIn("September 2026 predictions are up", body)

    def test_homepage_links_to_upcoming_forecast(self):
        body = self.client.get("/").content.decode()
        self.assertIn('href="/predictions/september-2026/"', body)

    def test_link_target_is_the_canonical_slug_not_the_numeric_alias(self):
        """Link to the URL that holds the equity, never the 301'ing alias."""
        body = self.client.get("/predictions/august-2026/").content.decode()
        self.assertNotIn('href="/predictions/2026-9/"', body)
