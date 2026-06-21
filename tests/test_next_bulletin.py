"""Tests for the "When does the next Visa Bulletin come out?" page + release projection."""

from datetime import UTC, date, datetime

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.bulletin.release_schedule import (
    get_release_schedule,
    recent_live_releases,
)
from models.bulletin import Bulletin


def _make(governing: date, released: datetime) -> None:
    """Create a Bulletin whose fetched_at is forced to ``released``.

    fetched_at is auto_now_add, so .create() stamps "now"; a queryset .update()
    bypasses auto_now_add to set the controlled release-date proxy.
    """
    b = Bulletin.objects.create(publication_date=governing)
    Bulletin.objects.filter(pk=b.pk).update(fetched_at=released)


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 14, 0, tzinfo=UTC)


class TestReleaseSchedule(TestCase):
    def setUp(self):
        # Live-ingested: released ~mid the prior month (lead 14-17 days).
        _make(date(2025, 5, 1), _dt(2025, 4, 16))  # lead 15
        _make(date(2025, 6, 1), _dt(2025, 5, 15))  # lead 17
        _make(date(2025, 7, 1), _dt(2025, 6, 16))  # lead 15
        # Bulk-backfill row: one synthetic fetched_at far from its governing month.
        _make(date(2002, 1, 1), _dt(2026, 3, 7))  # huge negative lead -> excluded

    def test_backfill_rows_excluded_from_history(self):
        recs = recent_live_releases()
        govs = {r.governing_month for r in recs}
        self.assertIn(date(2025, 7, 1), govs)
        self.assertNotIn(date(2002, 1, 1), govs)  # synthetic backfill dropped
        self.assertEqual(len(recs), 3)

    def test_projects_next_month_and_release_date(self):
        sched = get_release_schedule(today=date(2025, 6, 20))
        self.assertIsNotNone(sched)
        # Latest governing month is July 2025 -> next is August 2025.
        self.assertEqual(sched.latest_governing_month, date(2025, 7, 1))
        self.assertEqual(sched.next_governing_month, date(2025, 8, 1))
        # Next release posts in the month BEFORE the governing month (July 2025),
        # on the median observed release day (Apr 16, May 15, Jun 16 -> 16).
        self.assertEqual(sched.typical_release_dom, 16)
        self.assertEqual(sched.next_release_estimate, date(2025, 7, 16))
        lo, hi = sched.next_release_window
        self.assertEqual((lo.month, hi.month), (7, 7))
        self.assertLessEqual(lo, sched.next_release_estimate)
        self.assertGreaterEqual(hi, sched.next_release_estimate)

    def test_none_when_no_live_history(self):
        Bulletin.objects.all().delete()
        # Only a synthetic backfill-style row -> no live history -> None.
        _make(date(2003, 1, 1), _dt(2026, 3, 7))
        self.assertIsNone(get_release_schedule(today=date(2026, 3, 8)))


class TestNextBulletinView(TestCase):
    def setUp(self):
        _make(date(2025, 6, 1), _dt(2025, 5, 15))
        _make(date(2025, 7, 1), _dt(2025, 6, 16))

    def test_page_renders_with_projection_and_schema(self):
        resp = self.client.get("/when-is-the-next-visa-bulletin/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Single H1 with the primary query.
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn("When does the next Visa Bulletin come out?", html)
        # Projects the next governing month (August 2025) + FAQPage rich-result schema.
        self.assertIn("August 2025", html)
        self.assertIn('"@type": "FAQPage"', html)
        self.assertIn("when-is-the-next-visa-bulletin", html)  # canonical
