"""Tests for the "When does the next Visa Bulletin come out?" page + release projection."""

from datetime import UTC, date, datetime

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.bulletin.release_schedule import (
    get_release_schedule,
    recent_live_releases,
    release_odds,
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

    def test_month_specific_targeting(self):
        """Title/H2/FAQ name the governing month so the page matches
        "visa bulletin <month> <year> when will it come out" (the highest-volume
        timing variant the generic homepage was consolidating). Regression for
        the 0-impressions diagnosis, 2026-06-23."""
        html = self.client.get("/when-is-the-next-visa-bulletin/").content.decode()
        # Month-specific <title> (rolls forward with the governing month).
        self.assertIn("When Will the August 2025 Visa Bulletin Come Out", html)
        # Visible month-specific H2 (backs the FAQ answer per Google's policy).
        self.assertIn("When will the August 2025 Visa Bulletin come out?", html)
        # Month-keyed FAQ question in the JSON-LD.
        self.assertIn("When will the August 2025 Visa Bulletin be released?", html)

    def test_internal_links_point_to_timing_page(self):
        """High-authority surfaces link to the dedicated timing page with timing
        anchor text, so Google prefers it over the homepage for the cluster
        (the consolidation fix, 2026-06-23)."""
        home = self.client.get("/").content.decode()
        self.assertIn("/when-is-the-next-visa-bulletin/", home)
        self.assertIn("When does the next Visa Bulletin come out?", home)
        archive = self.client.get("/predictions/").content.decode()
        self.assertIn("/when-is-the-next-visa-bulletin/", archive)


def _make_released(governing: date, released: date, source: str = "wayback") -> Bulletin:
    """Create a Bulletin with a backfilled ``released_on`` (the real release date)."""
    b = Bulletin.objects.create(publication_date=governing)
    Bulletin.objects.filter(pk=b.pk).update(
        released_on=released, released_on_source=source
    )
    return Bulletin.objects.get(pk=b.pk)


class TestReleasedOnPreferredOverFetchedAt(TestCase):
    """released_on is the real release date; fetched_at is only a fallback proxy."""

    def test_released_on_wins_over_fetched_at(self):
        b = Bulletin.objects.create(publication_date=date(2025, 7, 1))
        Bulletin.objects.filter(pk=b.pk).update(
            fetched_at=_dt(2025, 6, 20),      # our cron lagged
            released_on=date(2025, 6, 16),    # archive saw it earlier
            released_on_source="wayback",
        )
        (rec,) = recent_live_releases()
        self.assertEqual(rec.released_on, date(2025, 6, 16))
        self.assertEqual(rec.lead_days, 15)
        self.assertTrue(rec.is_upper_bound)  # wayback -> "on or before"

    def test_live_source_is_not_flagged_as_upper_bound(self):
        _make_released(date(2025, 7, 1), date(2025, 6, 16), source=Bulletin.SOURCE_LIVE)
        (rec,) = recent_live_releases()
        self.assertFalse(rec.is_upper_bound)

    def test_implausible_released_on_is_excluded(self):
        """A CMS-migration artifact (whole archive first captured on one day)
        must not become a release date. Regression for the 2017-12-03 cluster."""
        _make_released(date(2015, 8, 1), date(2017, 12, 3))  # lead is hugely negative
        _make_released(date(2020, 5, 1), date(2020, 5, 1))   # lead 0 — sparse crawl
        self.assertEqual(recent_live_releases(), [])


class TestReleaseOdds(TestCase):
    """"X% of August bulletins were out by now" — the wait-time context line."""

    def setUp(self):
        # Five past August bulletins with leads 20, 18, 16, 12, 10 days.
        for year, lead_release in [
            (2021, date(2021, 7, 12)),  # lead 20
            (2022, date(2022, 7, 14)),  # lead 18
            (2023, date(2023, 7, 16)),  # lead 16
            (2024, date(2024, 7, 20)),  # lead 12
            (2025, date(2025, 7, 22)),  # lead 10
        ]:
            _make_released(date(year, 8, 1), lead_release)
        # A July bulletin must not leak into August's sample.
        _make_released(date(2025, 7, 1), date(2025, 6, 16))

    def test_counts_only_same_calendar_month(self):
        odds = release_odds(date(2026, 8, 1), as_of=date(2026, 7, 18))
        self.assertEqual(odds.n_total, 5)
        self.assertEqual(odds.month_name, "August")
        self.assertEqual(odds.years_covered, (2021, 2025))

    def test_percentage_by_day_of_month(self):
        # As of Jul 18 there are 14 days of runway left; the three bulletins with
        # lead >= 14 (20, 18, 16) had already posted by this point.
        odds = release_odds(date(2026, 8, 1), as_of=date(2026, 7, 18))
        self.assertEqual(odds.n_released_by_now, 3)
        self.assertEqual(odds.pct_released_by_now, 60)
        self.assertTrue(odds.is_late)

    def test_early_in_the_window_is_not_late(self):
        # Jul 10 -> 22 days of runway; none of the five had posted that early.
        odds = release_odds(date(2026, 8, 1), as_of=date(2026, 7, 10))
        self.assertEqual(odds.n_released_by_now, 0)
        self.assertEqual(odds.pct_released_by_now, 0)
        self.assertFalse(odds.is_late)

    def test_all_out_by_the_end_of_the_window(self):
        odds = release_odds(date(2026, 8, 1), as_of=date(2026, 7, 25))
        self.assertEqual(odds.pct_released_by_now, 100)

    def test_future_bulletins_excluded_from_own_sample(self):
        """The target month itself must never count toward its own odds."""
        _make_released(date(2026, 8, 1), date(2026, 7, 14))
        odds = release_odds(date(2026, 8, 1), as_of=date(2026, 7, 18))
        self.assertEqual(odds.n_total, 5)

    def test_lookback_window_bounds_the_sample(self):
        odds = release_odds(date(2026, 8, 1), as_of=date(2026, 7, 18), lookback_years=3)
        self.assertEqual(odds.years_covered, (2023, 2025))
        self.assertEqual(odds.n_total, 3)

    def test_none_when_no_history_for_that_month(self):
        self.assertIsNone(release_odds(date(2026, 2, 1), as_of=date(2026, 1, 18)))


class TestOddsOnPage(TestCase):
    def setUp(self):
        _make_released(date(2025, 7, 1), date(2025, 6, 16))  # latest -> next is Aug 2025
        _make_released(date(2023, 8, 1), date(2023, 7, 14))  # lead 18
        _make_released(date(2024, 8, 1), date(2024, 7, 20))  # lead 12

    def test_page_shows_share_already_published(self):
        html = self.client.get("/when-is-the-next-visa-bulletin/").content.decode()
        # As of the request date the page states how many past August bulletins
        # had landed by this point — the actual question a waiting visitor has.
        self.assertIn("of past August bulletins had already been published", html)
        self.assertIn("of 2", html)  # sample size is stated, never hidden

    def test_page_discloses_archive_provenance(self):
        """A wayback-derived date is "on or before" — the page must say so."""
        html = self.client.get("/when-is-the-next-visa-bulletin/").content.decode()
        self.assertIn("Internet Archive", html)
        self.assertIn("published on or before", html)


class TestFaqSchemaIsValidJson(TestCase):
    """The FAQPage block is hand-templated, and the odds entry is conditional —
    a stray comma there silently kills the rich result, so parse it for real."""

    def setUp(self):
        _make_released(date(2025, 7, 1), date(2025, 6, 16))
        _make_released(date(2023, 8, 1), date(2023, 7, 14))
        _make_released(date(2024, 8, 1), date(2024, 7, 20))

    def _faq_payload(self) -> dict:
        import json
        import re

        html = self.client.get("/when-is-the-next-visa-bulletin/").content.decode()
        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
        )
        for raw in blocks:
            payload = json.loads(raw)  # raises on malformed JSON — that is the test
            if payload.get("@type") == "FAQPage":
                return payload
        self.fail("no FAQPage JSON-LD block found")

    def test_faq_parses_and_carries_the_late_question(self):
        payload = self._faq_payload()
        names = [q["name"] for q in payload["mainEntity"]]
        self.assertIn("Is the August 2025 Visa Bulletin late?", names)
        # Every entry must be a complete Q&A pair.
        for q in payload["mainEntity"]:
            self.assertTrue(q["acceptedAnswer"]["text"].strip())

    def test_faq_still_parses_without_odds(self):
        """No history for the governing calendar month -> no odds entry, still valid."""
        Bulletin.objects.filter(publication_date__month=8).delete()
        payload = self._faq_payload()
        names = [q["name"] for q in payload["mainEntity"]]
        self.assertNotIn("Is the August 2025 Visa Bulletin late?", names)
        self.assertTrue(names)
