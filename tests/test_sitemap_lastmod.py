"""Regression tests for sitemap lastmod (2026-06-17).

The sitemap used to emit ``lastmod = latest bulletin publication_date`` for ALL
~10k employer/job-title profile + static URLs. That date is a future month (the
current bulletin applies to next month), so every URL advertised a uniform,
future lastmod — which makes Google distrust the sitemap's lastmod entirely and
gives the long-tail profile pages zero per-page freshness signal.

Fix: profile pages use their own ``updated_at`` (capped at today); the static /
bulletin block is capped at today so the future month never leaks out.
"""

from datetime import date, datetime, timedelta

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache  # noqa: E402
from django.test import Client, TestCase  # noqa: E402
from django.urls import reverse  # noqa: E402

from models.bulletin import Bulletin  # noqa: E402
from models.job_title import JobTitleCluster  # noqa: E402
from models.salary import EmployerCluster  # noqa: E402
from webapp.views.seo.sitemaps import _lastmod_capped  # noqa: E402


class LastmodCappedUnitTest(TestCase):
    def test_future_clamped_to_today(self):
        today = date(2026, 6, 17)
        assert _lastmod_capped(date(2026, 7, 1), today) == "2026-06-17"

    def test_past_preserved(self):
        today = date(2026, 6, 17)
        assert _lastmod_capped(date(2026, 2, 8), today) == "2026-02-08"

    def test_datetime_accepted(self):
        today = date(2026, 6, 17)
        assert _lastmod_capped(datetime(2026, 2, 8, 13, 30), today) == "2026-02-08"

    def test_none_passthrough(self):
        assert _lastmod_capped(None, date(2026, 6, 17)) is None


class SitemapLastmodTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        # Bulletin dated NEXT month — the exact future-date trap the bug emitted.
        self.future = date.today().replace(day=1) + timedelta(days=40)
        self.future = self.future.replace(day=1)
        Bulletin.objects.create(publication_date=self.future)

        self.emp = EmployerCluster.objects.create(
            canonical_name="Test Company LLC", slug="test-company-llc",
            total_lca_count=100,
        )
        self.jt = JobTitleCluster.objects.create(
            canonical_title="Software Engineer", slug="software-engineer",
            total_filings=100,
        )
        # auto_now stamps updated_at to now on create; force a known past date
        # (queryset.update bypasses auto_now) so we can assert it's used.
        EmployerCluster.objects.filter(pk=self.emp.pk).update(
            updated_at=datetime(2026, 2, 8, 12, 0))
        JobTitleCluster.objects.filter(pk=self.jt.pk).update(
            updated_at=datetime(2026, 2, 8, 12, 0))

    def _lastmods(self, body: str) -> list[str]:
        import re
        return re.findall(r"<lastmod>([^<]+)</lastmod>", body)

    def test_no_lastmod_is_in_the_future(self):
        """The core bug: a future bulletin month must never appear as lastmod."""
        body = self.client.get(reverse("sitemap")).content.decode()
        today = date.today().isoformat()
        future_iso = self.future.isoformat()
        lastmods = self._lastmods(body)
        assert lastmods, "sitemap emitted no lastmod at all"
        assert future_iso not in lastmods, f"future bulletin date {future_iso} leaked into sitemap"
        assert all(lm <= today for lm in lastmods), \
            f"future lastmod present: {[lm for lm in lastmods if lm > today]}"

    def test_profile_lastmod_is_its_own_updated_at(self):
        """Profile pages use per-cluster updated_at, NOT the bulletin date."""
        body = self.client.get(reverse("sitemap")).content.decode()
        import re
        for path in ("/employer/test-company-llc/", "/job-title/software-engineer/"):
            m = re.search(
                rf"<loc>[^<]*{re.escape(path)}</loc>\s*<lastmod>([^<]+)</lastmod>", body)
            assert m, f"{path} missing from sitemap"
            assert m.group(1) == "2026-02-08", \
                f"{path} lastmod {m.group(1)} != cluster updated_at 2026-02-08"

    def test_family_sponsored_archive_in_sitemap(self):
        """Family-sponsored prediction months must be listed (were orphaned).

        The archive loop used to emit only the bare-numeric (employment_based)
        form, so /predictions/family_sponsored/<y>-<m>/ appeared nowhere in the
        sitemap despite being live, self-canonical content.
        """
        import re
        body = self.client.get(reverse("sitemap")).content.decode()
        fs_path = f"/predictions/family_sponsored/{self.future.year}-{self.future.month}/"
        assert re.search(rf"<loc>[^<]*{re.escape(fs_path)}</loc>", body), \
            f"family_sponsored archive URL {fs_path} missing from sitemap"

    def test_dashboard_lastmod_is_bulletin_fetched_at_not_publication_date(self):
        """Static/dashboard URLs use the bulletin's real ingest time (fetched_at),
        not its future publication_date capped to today.

        Regression (2026-06-18): the dashboard block used publication_date capped
        to today, so it re-advertised *today* on every crawl until the future
        applies-to month arrived — daily drift Google discounts. The fix uses
        fetched_at (the stable real ingest timestamp). Here the bulletin is dated
        next month but was fetched 10 days ago, so the dashboard lastmod must be
        the fetch date, NOT today.
        """
        import re
        fetch_dt = datetime.combine(date.today() - timedelta(days=10), datetime.min.time())
        fetch_dt = fetch_dt.replace(hour=4, minute=0)
        # auto_now_add stamps fetched_at=now on create; force a known past value
        # (queryset.update bypasses auto_now_add) so we can assert it's the source.
        Bulletin.objects.filter(publication_date=self.future).update(fetched_at=fetch_dt)
        expected = fetch_dt.date().isoformat()

        body = self.client.get(reverse("sitemap")).content.decode()
        for path in ("/", "/salaries/", "/employment-based/"):
            m = re.search(
                rf"<loc>[^<]*{re.escape(path)}</loc>\s*<lastmod>([^<]+)</lastmod>", body)
            assert m, f"{path} missing from sitemap"
            assert m.group(1) == expected, (
                f"{path} lastmod {m.group(1)} != bulletin fetched_at {expected} "
                f"(today is {date.today().isoformat()} — a 'today' value means it "
                f"is still keying off publication_date)")
