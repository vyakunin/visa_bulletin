"""Tests for the /h1b-lottery/ cap-season cluster.

The pages exist to answer lottery-season queries with sourced numbers rather than
asserted ones, so the properties worth locking are the ones that would let an
unsourced number onto a page, or let a sourced one drift:

1. Every rate rendered is DERIVED from the declared USCIS totals, never typed
   into a template — so correcting a total corrects the page.
2. ``filing_waves`` buckets petition receipts by the real season boundaries, and
   its later-wave verdict separates a season that ran an additional round from
   one that only saw a trickle of late receipts.
3. The cap-season phase tracks the calendar, including the year rollover that
   decides which cap FY is in play.
4. The three URLs render, are self-canonical, carry FAQPage JSON-LD whose
   questions match the visible copy, and are in the sitemap with a lastmod that
   is the dataset's revision date rather than today (a page whose banner moves
   daily must not advertise a daily lastmod).
5. The cluster is not orphaned: the pages link to each other, and two indexed
   pages link in.
"""

import json
from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache  # noqa: E402
from django.test import Client, TestCase, override_settings  # noqa: E402

from lib.business.i129.lottery_season import (  # noqa: E402
    H1B_ANNUAL_CAP,
    SELECTION_HISTORY_UPDATED,
    USCIS_SELECTION_HISTORY,
    CapSeasonPhase,
    SelectionBasis,
    current_cap_season,
    filing_waves,
    latest_published_season,
)
from models.i129 import I129Petition  # noqa: E402


def _receipts(cap_fy: int, received: date, count: int, *, start: int = 0) -> None:
    I129Petition.objects.bulk_create(
        [
            I129Petition(
                dol_eta_case_number=f"I-200-{cap_fy}-{received:%Y%m%d}-{start + i:05d}",
                fiscal_year=cap_fy,
                received_date=received,
            )
            for i in range(count)
        ]
    )


class SelectionHistoryTest(TestCase):
    """The published-totals table and everything derived from it."""

    def test_rates_are_derived_from_the_declared_totals(self):
        for season in USCIS_SELECTION_HISTORY:
            expected = round(
                100.0 * season.selected_registrations / season.eligible_registrations, 1
            )
            assert season.selection_rate_pct == expected, season.cap_fy

    def test_over_selection_multiple_is_against_the_statutory_cap(self):
        season = next(s for s in USCIS_SELECTION_HISTORY if s.cap_fy == 2024)
        assert season.over_selection_multiple == round(
            season.selected_registrations / H1B_ANNUAL_CAP, 2
        )

    def test_every_season_is_internally_consistent(self):
        """Selections never exceed the pool, and the pool is never empty."""
        for season in USCIS_SELECTION_HISTORY:
            assert season.eligible_registrations > 0, season.cap_fy
            assert 0 < season.selected_registrations < season.eligible_registrations

    def test_seasons_are_ordered_and_unique(self):
        fys = [s.cap_fy for s in USCIS_SELECTION_HISTORY]
        assert fys == sorted(fys)
        assert len(fys) == len(set(fys))

    def test_selection_basis_switches_at_the_fy2025_rule(self):
        """The beneficiary-centric rule took effect for the FY2025 lottery."""
        for season in USCIS_SELECTION_HISTORY:
            expected = (
                SelectionBasis.PER_BENEFICIARY
                if season.cap_fy >= 2025
                else SelectionBasis.PER_REGISTRATION
            )
            assert season.basis == expected, season.cap_fy

    def test_latest_published_season_is_the_newest(self):
        assert latest_published_season().cap_fy == max(
            s.cap_fy for s in USCIS_SELECTION_HISTORY
        )

    def test_history_updated_is_not_in_the_future(self):
        assert SELECTION_HISTORY_UPDATED <= date.today()


class CapSeasonPhaseTest(TestCase):
    """Which cap season is in play, and which phase of it today falls in."""

    def test_cap_fy_is_next_years_across_the_whole_calendar(self):
        for month in range(1, 13):
            season = current_cap_season(date(2026, month, 15))
            assert season.cap_fy == 2027, month
            assert season.registration_year == 2026

    def test_phase_tracks_the_calendar(self):
        cases = {
            1: CapSeasonPhase.BEFORE_REGISTRATION,
            2: CapSeasonPhase.BEFORE_REGISTRATION,
            3: CapSeasonPhase.REGISTRATION,
            4: CapSeasonPhase.INITIAL_FILING,
            6: CapSeasonPhase.INITIAL_FILING,
            7: CapSeasonPhase.INITIAL_FILING,
            8: CapSeasonPhase.LATER_ROUNDS,
            9: CapSeasonPhase.LATER_ROUNDS,
            10: CapSeasonPhase.EMPLOYMENT_STARTED,
            12: CapSeasonPhase.EMPLOYMENT_STARTED,
        }
        for month, expected in cases.items():
            assert current_cap_season(date(2026, month, 10)).phase == expected, month

    def test_employment_starts_october_1_of_the_registration_year(self):
        season = current_cap_season(date(2026, 8, 10))
        assert season.employment_start == date(2026, 10, 1)

    def test_exactly_one_phase_is_current_and_it_matches(self):
        season = current_cap_season(date(2026, 8, 10))
        current = [p for p in season.phases if p.is_current]
        assert len(current) == 1
        assert current[0].phase == season.phase
        assert season.current_phase is current[0]


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class FilingWavesTest(TestCase):
    """Receipt bucketing — the observed trace of an additional selection round."""

    def setUp(self):
        cache.clear()
        # FY2030: initial window only, plus a handful of stragglers — the shape of
        # a season that ran no additional round.
        _receipts(2030, date(2029, 4, 20), 600)
        _receipts(2030, date(2029, 6, 15), 400, start=600)
        _receipts(2030, date(2029, 9, 5), 10, start=1000)
        # FY2031: an initial window and a real second wave months later.
        _receipts(2031, date(2030, 5, 10), 600)
        _receipts(2031, date(2030, 9, 20), 300, start=600)
        _receipts(2031, date(2031, 1, 8), 100, start=900)
        # Out-of-season noise: a receipt date years off its cap season.
        _receipts(2031, date(2027, 3, 1), 5, start=1000)

    def test_initial_window_runs_april_through_july_of_the_registration_year(self):
        waves = {w.cap_fy: w for w in filing_waves(use_cache=False)}
        assert waves[2030].initial_window == 1000

    def test_later_window_spans_august_through_the_end_of_the_cap_fy(self):
        waves = {w.cap_fy: w for w in filing_waves(use_cache=False)}
        assert waves[2031].later_window == 400

    def test_receipts_outside_the_season_are_excluded_not_miscounted(self):
        waves = {w.cap_fy: w for w in filing_waves(use_cache=False)}
        assert waves[2031].out_of_season == 5
        assert waves[2031].in_season == 1000

    def test_a_trickle_is_not_reported_as_a_later_wave(self):
        waves = {w.cap_fy: w for w in filing_waves(use_cache=False)}
        assert waves[2030].later_share_pct < 5.0
        assert waves[2030].had_later_wave is False

    def test_a_real_second_wave_is_reported(self):
        waves = {w.cap_fy: w for w in filing_waves(use_cache=False)}
        assert waves[2031].later_share_pct == 40.0
        assert waves[2031].had_later_wave is True

    def test_seasons_are_returned_in_order(self):
        assert [w.cap_fy for w in filing_waves(use_cache=False)] == [2030, 2031]

    def test_empty_dataset_yields_no_seasons(self):
        I129Petition.objects.all().delete()
        assert filing_waves(use_cache=False) == ()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class LotteryPagesTest(TestCase):
    PATHS = ("/h1b-lottery/", "/h1b-lottery/odds/", "/h1b-lottery/second-round/")

    def setUp(self):
        cache.clear()
        self.client = Client()
        _receipts(2024, date(2023, 5, 12), 500)
        _receipts(2024, date(2023, 9, 18), 250, start=500)
        _receipts(2023, date(2022, 5, 12), 500, start=1000)

    def _faq_jsonld(self, html: str) -> dict:
        """The page's FAQPage block — base.html emits site-wide blocks too."""
        marker = '<script type="application/ld+json">'
        pos = 0
        while (found := html.find(marker, pos)) != -1:
            start = found + len(marker)
            end = html.index("</script>", start)
            pos = end
            try:
                data = json.loads(html[start:end])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "FAQPage":
                return data
        raise AssertionError("no FAQPage JSON-LD on the page")

    def test_every_page_renders(self):
        for path in self.PATHS:
            assert self.client.get(path).status_code == 200, path

    def test_every_page_is_self_canonical(self):
        for path in self.PATHS:
            html = self.client.get(path).content.decode()
            assert f'<link rel="canonical" href="http://testserver{path}"' in html, path

    def test_every_page_emits_faqpage_schema_matching_its_visible_copy(self):
        for path in self.PATHS:
            html = self.client.get(path).content.decode()
            data = self._faq_jsonld(html)
            assert data["mainEntity"], path
            for item in data["mainEntity"]:
                assert item["acceptedAnswer"]["text"].strip(), path
                # The question is rendered on the page, not schema-only markup.
                assert item["name"] in html, (path, item["name"])

    def test_odds_page_shows_every_published_season(self):
        html = self.client.get("/h1b-lottery/odds/").content.decode()
        for season in USCIS_SELECTION_HISTORY:
            assert f"FY{season.cap_fy}" in html, season.cap_fy
            assert f"{season.selection_rate_pct}%" in html, season.cap_fy

    def test_second_round_page_shows_the_observed_split(self):
        html = self.client.get("/h1b-lottery/second-round/").content.decode()
        # FY2024 fixture: 500 initial, 250 later -> 33.3% arriving later.
        assert "33.3%" in html
        assert "FY2023" in html and "FY2024" in html

    def test_pages_link_to_their_siblings(self):
        for path in self.PATHS:
            html = self.client.get(path).content.decode()
            for other in self.PATHS:
                if other == path:
                    continue
                assert f'href="{other}"' in html, (path, other)

    def test_sitemap_lists_the_cluster_with_the_dataset_lastmod(self):
        html = self.client.get("/sitemap.xml").content.decode()
        for path in self.PATHS:
            assert f"<loc>http://testserver{path}</loc>" in html, path
        # Not today's date: the phase banner moves daily, the content does not.
        assert f"<lastmod>{SELECTION_HISTORY_UPDATED.isoformat()}</lastmod>" in html

    def test_no_page_claims_perm_filings_signal_green_card_sponsorship(self):
        """perm_messaging.md: PERM volume is never pitched as sponsorship intent."""
        for path in self.PATHS:
            html = self.client.get(path).content.decode().lower()
            assert "perm ratio" not in html, path
            assert "perm activity" not in html, path


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)
class LotteryInboundLinksTest(TestCase):
    """A sitemap entry is a hint; an inbound link is the discovery path."""

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_salary_search_links_to_the_lottery_hub(self):
        html = self.client.get("/salaries/").content.decode()
        assert 'href="/h1b-lottery/"' in html

    def test_next_bulletin_page_links_to_the_lottery_hub(self):
        html = self.client.get("/when-is-the-next-visa-bulletin/").content.decode()
        assert 'href="/h1b-lottery/"' in html
