"""EB-5 resolves to the heading the bulletin actually publishes it under.

EB-5 is the one employment-based series whose ``VisaCutoffDate.visa_class`` is
not its series key: the Department of State prints the sub-category in the row
heading and renames it every few years. A bare ``"5th"`` lookup therefore only
matches bulletins up to April 2011 — all of them flagged Current — so the site
served a fifteen-year-old "Current" for a category that is Unavailable for India
and backlogged to 2016 for China.

The failure is silent by construction: a label matching nothing returns no row
rather than raising, and "no row" reads downstream as "no backlog → Current". So
these tests pin both halves — that a live EB-5 state is read from the current
heading, and that a heading the code has never seen still resolves.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.bulletin import eb_series
from lib.business.vqs import data_cache
from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff

# The headings DOS has used for the EB-5 residual (Unreserved) chart. Final
# action gained the NU/RU set-aside carryover in January 2025; filing did not.
LABEL_2022 = "5th Unreserved (including C5, T5, I5, R5)"
LABEL_2025_FINAL = "5th Unreserved (including C5, T5, I5, R5, NU, RU)"


def _cutoff(bulletin, visa_class, country, action_type, cutoff_date, *,
            is_current=False, is_unavailable=False):
    return VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class=visa_class,
        action_type=action_type,
        country=country,
        cutoff_value=(
            "U" if is_unavailable else "C" if is_current
            else cutoff_date.strftime("%d%b%y").upper()
        ),
        cutoff_date=cutoff_date,
        is_current=is_current,
        is_unavailable=is_unavailable,
    )


def _clear_caches():
    eb_series.clear_label_cache()
    for cache in (
        data_cache._CUTOFF_CACHE,
        data_cache._PUB_DATE_CACHE,
        data_cache._CURRENT_CACHE,
        data_cache._CURRENT_PUB_DATES,
    ):
        cache.clear()
    data_cache._BULLETIN_CACHE = None


class Eb5LabelFixture(TestCase):
    """A DB shaped like prod: a stale bare-'5th' era plus the modern headings."""

    def setUp(self):
        _clear_caches()
        self.addCleanup(_clear_caches)

        # The stale era: bare "5th", last published April 2011, flagged Current
        # for every country. This is what a hardcoded "5th" key still matches.
        self.b2011 = Bulletin.objects.create(publication_date=date(2011, 4, 1))
        for country in (Country.ALL, Country.CHINA, Country.INDIA):
            _cutoff(self.b2011, "5th", country.value,
                    ActionType.FINAL_ACTION.value, None, is_current=True)

        # The middle era: renamed, no NU/RU carryover yet.
        self.b2023 = Bulletin.objects.create(publication_date=date(2023, 6, 1))
        _cutoff(self.b2023, LABEL_2022, Country.CHINA.value,
                ActionType.FINAL_ACTION.value, date(2015, 12, 15))

        # Today: the current heading. India is Unavailable, China backlogged.
        self.latest = Bulletin.objects.create(publication_date=date(2026, 8, 1))
        _cutoff(self.latest, LABEL_2025_FINAL, Country.INDIA.value,
                ActionType.FINAL_ACTION.value, None, is_unavailable=True)
        _cutoff(self.latest, LABEL_2025_FINAL, Country.CHINA.value,
                ActionType.FINAL_ACTION.value, date(2016, 12, 1))
        _cutoff(self.latest, LABEL_2025_FINAL, Country.ALL.value,
                ActionType.FINAL_ACTION.value, None, is_current=True)
        # The filing chart keeps the older heading on the same bulletin.
        _cutoff(self.latest, LABEL_2022, Country.INDIA.value,
                ActionType.FILING.value, date(2024, 5, 1))


class TestResolveCutoffLabel(Eb5LabelFixture):
    def test_eb5_resolves_to_the_current_heading(self):
        self.assertEqual(
            eb_series.resolve_cutoff_label("5th", ActionType.FINAL_ACTION.value),
            LABEL_2025_FINAL,
        )

    def test_resolution_is_action_type_aware(self):
        # Same bulletin, two charts, two headings. Reading the final-action label
        # off the filing chart is how the two get silently crossed.
        self.assertEqual(
            eb_series.resolve_cutoff_label("5th", ActionType.FILING.value),
            LABEL_2022,
        )

    def test_historical_as_of_resolves_to_the_heading_in_use_then(self):
        # A backtest at a 2023 knowledge date must read the 2023 heading, not the
        # one introduced in 2025 (which has no rows that far back).
        self.assertEqual(
            eb_series.resolve_cutoff_label(
                "5th", ActionType.FINAL_ACTION.value, as_of=date(2023, 9, 1)
            ),
            LABEL_2022,
        )

    def test_survives_a_heading_the_code_has_never_seen(self):
        # The next rename. Nothing in the codebase spells this string, so if
        # resolution were a literal the bug would silently return in 2028.
        future = Bulletin.objects.create(publication_date=date(2028, 1, 1))
        renamed = "5th Unreserved (including C5, T5, I5, R5, NU, RU, XX)"
        _cutoff(future, renamed, Country.INDIA.value,
                ActionType.FINAL_ACTION.value, date(2019, 1, 1))
        eb_series.clear_label_cache()
        self.assertEqual(
            eb_series.resolve_cutoff_label("5th", ActionType.FINAL_ACTION.value),
            renamed,
        )

    def test_non_eb5_classes_are_their_own_label(self):
        for key in ("1st", "2nd", "3rd", "4th"):
            self.assertEqual(
                eb_series.resolve_cutoff_label(key, ActionType.FINAL_ACTION.value),
                key,
            )

    def test_missing_series_resolves_to_none_not_a_guess(self):
        VisaCutoffDate.objects.filter(visa_class__startswith="5th Unreserved").delete()
        eb_series.clear_label_cache()
        self.assertIsNone(
            eb_series.resolve_cutoff_label("5th", ActionType.FINAL_ACTION.value)
        )


class TestEb5StateReadFromLiveBulletin(Eb5LabelFixture):
    """The publish path's Current/Unavailable gate, which decides what gets stored."""

    def test_eb5_india_is_unavailable_not_current(self):
        # The whole defect in one assertion: the pipeline asked "is EB-5 India
        # Current?", matched the April 2011 row, and published a Current row for
        # a category that is Unavailable today.
        kd = date(2026, 8, 15)
        self.assertFalse(
            data_cache.is_current_at_date(
                "5th", Country.INDIA.value, ActionType.FINAL_ACTION.value, kd
            )
        )
        self.assertTrue(
            data_cache.is_unavailable_at_date(
                "5th", Country.INDIA.value, ActionType.FINAL_ACTION.value, kd
            )
        )

    def test_eb5_china_reads_the_modern_backlog(self):
        kd = date(2026, 8, 15)
        self.assertFalse(
            data_cache.is_current_at_date(
                "5th", Country.CHINA.value, ActionType.FINAL_ACTION.value, kd
            )
        )
        self.assertEqual(
            data_cache.get_cutoff_at_date(
                "5th", Country.CHINA.value, ActionType.FINAL_ACTION.value, kd
            ),
            date(2016, 12, 1),
        )

    def test_eb5_all_countries_is_still_current(self):
        # Current must keep reading as Current where it genuinely is — the fix
        # must not invert the gate.
        self.assertTrue(
            data_cache.is_current_at_date(
                "5th", Country.ALL.value, ActionType.FINAL_ACTION.value,
                date(2026, 8, 15),
            )
        )


class TestForecastGridEb5(Eb5LabelFixture):
    """The rendered surface: /predictions/<month>-<year>/ before the drop."""

    def setUp(self):
        super().setUp()
        self.pb = PredictedBulletin.objects.create(
            target_bulletin_month=date(2026, 9, 1),
            prediction_date=date(2026, 8, 15),
        )
        # Predictions stay keyed by the SERIES KEY — PredictedCutoff.visa_class
        # is a 10-char column and could not hold a bulletin heading anyway.
        PredictedCutoff.objects.create(
            bulletin=self.pb, visa_class="5th", country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value, predicted_date=None,
            model_name="unavailable",
        )
        PredictedCutoff.objects.create(
            bulletin=self.pb, visa_class="5th", country=Country.CHINA.value,
            action_type=ActionType.FINAL_ACTION.value,
            predicted_date=date(2017, 6, 1), model_name="persistence",
            confidence_low=date(2099, 1, 1), confidence_high=date(2099, 12, 1),
        )

    def test_eb5_china_movement_is_measured_against_the_live_cutoff(self):
        # The grid compares the forecast to the current actual. With the actuals
        # keyed by a bare "5th" the lookup missed and the cell rendered a bare
        # date with no movement; against the real Dec 2016 row it is +6m.
        body = self.client.get("/predictions/september-2026/").content.decode()
        self.assertIn("June 1, 2017", body)
        self.assertIn("+6m", body)

    def test_eb5_unavailable_row_renders(self):
        body = self.client.get("/predictions/september-2026/").content.decode()
        self.assertIn("Unavailable", body)

    def test_eb5_stays_a_no_model_baseline_cell(self):
        # Reading the live heading puts EB-5 back in front of the solver, which
        # it had been hidden from for fifteen years. EB-5 has no dedicated model,
        # so the cell must keep the baseline marker and must NOT dress a
        # persistence output in a calibrated interval — the 2099 sentinel bounds
        # stored above prove the suppression is real.
        body = self.client.get("/predictions/september-2026/").content.decode()
        self.assertIn("no-change baseline", body)
        self.assertNotIn("Jan 1, 2099", body)
        self.assertNotIn("Dec 1, 2099", body)


class TestUnresolvableEb5NeverRendersCurrent(Eb5LabelFixture):
    """A missing EB-5 row is missing data, and must never read as Current."""

    def test_no_stored_row_renders_a_dash(self):
        pb = PredictedBulletin.objects.create(
            target_bulletin_month=date(2026, 9, 1),
            prediction_date=date(2026, 8, 15),
        )
        # Something else has to be stored or the page 404s as a thin page.
        PredictedCutoff.objects.create(
            bulletin=pb, visa_class="2nd", country=Country.INDIA.value,
            action_type=ActionType.FINAL_ACTION.value,
            predicted_date=date(2013, 1, 1), model_name="regime_switched",
        )
        body = self.client.get("/predictions/september-2026/").content.decode()
        eb5_row = body.split("EB-5", 1)[1].split("</tr>", 1)[0]
        self.assertNotIn("Current", eb5_row)
        self.assertIn("—", eb5_row)
