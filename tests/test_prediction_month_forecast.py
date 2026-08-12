"""Tests for the evergreen per-month forecast landing pages.

Locks: a future month with stored predictions renders 200 with the predicted
cutoff + FAQPage schema + correct canonical; a published month renders the
accuracy archive IN PLACE at the same slug (self-canonical, no 301 — see
tests/test_stable_prediction_url.py); a future month with NO stored forecast
404s (no thin page, no live solver); an invalid month slug 404s; and the tight
URL pattern does not shadow the category/legacy prediction routes.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff


def _actual(bulletin, action_type, country, visa_class, cutoff_date):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class=visa_class,
        action_type=action_type,
        country=country,
        cutoff_value=cutoff_date.strftime("%d%b%y").upper(),
        cutoff_date=cutoff_date,
        is_current=False,
        is_unavailable=False,
    )


def _predict(
    pred_bulletin,
    action_type,
    country,
    visa_class,
    predicted_date,
    *,
    model_name="regime_switched",
    confidence_low=None,
    confidence_high=None,
    movement_probability=None,
    expert_predictions=None,
    explanation_markdown="",
):
    PredictedCutoff.objects.create(
        bulletin=pred_bulletin,
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        predicted_date=predicted_date,
        model_name=model_name,
        confidence_low=confidence_low,
        confidence_high=confidence_high,
        movement_probability=movement_probability,
        expert_predictions=expert_predictions or {},
        explanation_markdown=explanation_markdown,
    )


# The two shapes describe_reset emits, stored verbatim as publish_predictions writes
# them. The page renders THESE — it must not restate the prose in template markup.
_UNFLOORED_EXPLAINER = (
    "**EB-2 China is Unavailable** — it reached its fiscal-year annual limit "
    "(INA §203(b) numerical caps). It is expected to stay Unavailable through "
    "**September 2026**; a cutoff date returns on **October 1, 2026**, when the new "
    "fiscal year's visa quota opens. Where it resets to is uncertain. For reference, "
    "the last cutoff before it went Unavailable was **September 1, 2013**. Historically "
    "the October reset for an exhausted category has ranged from near that date to a "
    "substantial retrogression: the deepest in the employment-based record is "
    "**EB-3 India in 2007**, which came back about six years earlier than its own "
    "pre-Unavailable cutoff. Treat any specific October date as a rough guess."
)

_FLOORED_EXPLAINER = (
    "**EB-3 China is Unavailable** — it reached its fiscal-year annual limit "
    "(INA §203(b) numerical caps). It is expected to stay Unavailable through "
    "**September 2026**; a cutoff date returns on **October 1, 2026**, when the new "
    "fiscal year's visa quota opens. The July 2026 bulletin's notes say the date is "
    "expected to advance to **at least July 15, 2014**. State ties that to demand and "
    "to the new fiscal year's limits, so the date can land below it."
)


class TestPredictionMonthForecast(TestCase):
    def setUp(self):
        # Latest published edition = June 2026 (the "current" baseline).
        self.latest = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2020, 1, 1))
        _actual(self.latest, ActionType.FILING.value, Country.INDIA.value, "2nd", date(2020, 6, 1))

        # Stored forecast for the upcoming (unpublished) July 2026 bulletin.
        self.pb = PredictedBulletin.objects.create(
            target_bulletin_month=date(2026, 7, 1),
            prediction_date=date(2026, 6, 15),
        )
        # EB-2 India (a modeled series + headline card): a real advance, plus a
        # calibrated CI and a movement probability so the card renders both.
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.INDIA.value, "2nd", date(2020, 3, 1),
            confidence_low=date(2020, 2, 1), confidence_high=date(2020, 5, 1),
            movement_probability=0.15,
        )
        _predict(self.pb, ActionType.FILING.value, Country.INDIA.value, "2nd", date(2020, 8, 1))

        # EB-2 China (a modeled series + headline card): Unavailable — hit the FY
        # annual limit, so predicted_date is None and model_name == "unavailable".
        # Its stored explainer names a DEEP downside precedent (EB-3 India 2007) and
        # carries NO published floor — the unfloored shape.
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.CHINA.value, "2nd", date(2020, 1, 1))
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.CHINA.value, "2nd", None,
            model_name="unavailable",
            explanation_markdown=_UNFLOORED_EXPLAINER,
            expert_predictions={
                "october_reset": {
                    "is_unavailable": True,
                    "reset_year": 2026,
                    "stays_u_through": "September",
                    "pre_u_cutoff": "2013-09-01",
                    "reset_reference": "2013-09-01",
                    "n_precedents": 50,
                    "method": "anchor",
                    "diagnostics": {"p10_delta_days": -1247, "p90_delta_days": 307},
                }
            },
        )

        # EB-3 China: Unavailable AND bounded by a floor DOS published in a bulletin's
        # notes. The page must carry that bound — it is the whole point of PublishedFloor.
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.CHINA.value, "3rd", date(2020, 1, 1))
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.CHINA.value, "3rd", None,
            model_name="unavailable",
            explanation_markdown=_FLOORED_EXPLAINER,
            expert_predictions={
                "october_reset": {
                    "is_unavailable": True,
                    "reset_year": 2026,
                    "stays_u_through": "September",
                    "pre_u_cutoff": "2013-09-01",
                    "method": "anchor_floored",
                    "floor": "2014-07-15",
                    "n_precedents": 45,
                    "diagnostics": {"p10_delta_days": 317, "p90_delta_days": 328},
                }
            },
        )

        # EB-2 Other Countries (NOT a modeled series): a persistence baseline with
        # a real predicted date, so the grid tags it with the "baseline" marker.
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.ALL.value, "2nd", date(2024, 1, 1))
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.ALL.value, "2nd", date(2024, 1, 1),
            model_name="persistence",
        )

        # EB-3 Philippines: a baseline series that DOES carry stored CI bounds.
        # The view must SUPPRESS the CI on baseline cells (no dedicated model =>
        # no calibrated range), so these 2099 sentinel dates must never render.
        _actual(self.latest, ActionType.FINAL_ACTION.value, Country.PHILIPPINES.value, "3rd", date(2024, 8, 1))
        _predict(
            self.pb, ActionType.FINAL_ACTION.value, Country.PHILIPPINES.value, "3rd", date(2024, 8, 1),
            confidence_low=date(2099, 1, 1), confidence_high=date(2099, 12, 1),
            model_name="persistence",
        )

    def test_future_month_renders(self):
        resp = self.client.get("/predictions/july-2026/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("July 2026 Visa Bulletin Predictions", body)  # H1
        self.assertIn("March 1, 2020", body)  # predicted EB-2 India Final Action

    def test_predicted_advance_movement_shown(self):
        # 2020-01-01 -> 2020-03-01 is a +2-month advance vs the current bulletin.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("+2m", body)

    def test_unavailable_gets_fy_limit_explainer(self):
        # A category that hit the FY annual limit renders "Unavailable" + an
        # explainer, not a bare word that looks like a broken page.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("Unavailable", body)
        self.assertIn("fiscal-year annual limit", body)

    def test_unavailable_shows_october_reset_framing(self):
        # The October-reset / U-transition model: an Unavailable series states the
        # structural reset date (Oct 1), gives the pre-Unavailable cutoff as a
        # labelled reference, and honestly caveats that the reset target is uncertain
        # (no false-precise date). The words come from the STORED explainer.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("October 1, 2026", body)       # structural reset date
        self.assertIn("September 1, 2013", body)     # pre-Unavailable reference
        self.assertIn("rough guess", body)           # honest uncertainty caveat
        self.assertIn("EB-3 India in 2007", body)    # precedent, named with its own series
        # It must NOT publish a fabricated precise reset cutoff as the prediction.
        self.assertNotIn("Predicted reset date", body)

    def test_floored_series_renders_its_published_floor(self):
        # The bound DOS published in a bulletin's notes must reach the reader. It did
        # not: the box was hand-written template markup built from three fields
        # (reset_year, pre_u_cutoff, p10_delta_days) and could not see a floor at all,
        # so a page kept saying the reset might retrogress below a date State had
        # already announced it would clear.
        body = self.client.get("/predictions/july-2026/").content.decode()
        # Split around the apostrophe: Django escapes it to &#x27; in the rendered page,
        # so an assertion carrying "bulletin's" fails on correct output.
        self.assertIn("The July 2026 bulletin", body)
        self.assertIn("notes say the date is expected to advance to", body)
        # The floor is a floor, so the page must say the date can miss it downward.
        self.assertIn("the date can land below it", body)
        # As rendered HTML, not raw markdown — a substring check on the date alone
        # passes just as well when "**at least July 15, 2014**" leaks onto the page.
        self.assertIn("<strong>at least July 15, 2014</strong>", body)
        self.assertNotIn("**", body)

    def test_reset_prose_is_not_restated_in_template_markup(self):
        # The boundary this fix must not over-reach into, and the defect that made it
        # necessary: the template used to emit "(EB-2 India reset about three years
        # earlier in 2012)" for ANY series whose pooled p10 was below -120 — a literal
        # about one series rendered as every series' own history. Nothing on the page
        # may name a precedent the stored explainer did not name.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertNotIn("2012", body)
        self.assertNotIn("reset about three years earlier", body)
        # ...and the surviving prose is the stored explainer's, not a second copy:
        # the old markup's own wording is gone.
        self.assertNotIn("new numbers are being issued", body)
        # The per-card summary line carried the same blind claim in miniature — it
        # asserted the reset date was uncertain even for a series State had floored.
        self.assertNotIn("reset date uncertain", body)
        self.assertNotIn("Last cutoff before Unavailable:", body)

    def test_card_keeps_the_structural_reset_line(self):
        # The boundary in the other direction: dropping the prose from the card must
        # not take the STRUCTURAL fact with it. When the category comes back is not
        # narrative — it is Oct 1 of the reset year, and it stays on the card.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("Stays Unavailable through September 2026", body)
        self.assertIn("a cutoff returns", body)

    def test_baseline_series_marked_modeled_series_not(self):
        # A non-China/India series is a persistence baseline -> "baseline" marker;
        # the modeled EB-2 India card/cell must not carry it.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("no-change baseline", body)  # legend + marker tooltip

    def test_calibrated_ci_rendered_on_card(self):
        # The stored 80% confidence interval is shown, not hidden.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("80% range", body)
        self.assertIn("May 1, 2020", body)  # confidence_high of EB-2 India

    def test_grid_ci_is_visible_not_hover_only(self):
        # The EB/FS grid previously hid the calibrated 80% range in a
        # <td title="80% range: ..."> tooltip — invisible on touch (the audience
        # is mobile-heavy). It must now render as visible inline cell text.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertNotIn('title="80% range', body)  # no hover-only CI on any cell
        self.assertIn("80% range: Feb 1, 2020", body)  # ci_low of EB-2 India, inline

    def test_baseline_cell_suppresses_confidence_interval(self):
        # A no-dedicated-model (baseline) series must not render a calibrated CI
        # even when one is stored on the row — "no model" and "80% range" on the
        # same cell contradict. The EB-3 Philippines 2099 sentinel bounds prove it.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertNotIn("Jan 1, 2099", body)
        self.assertNotIn("Dec 1, 2099", body)

    def test_movement_prob_badge_has_explainer(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("probability of a more-than-50-day", body)

    def test_knowledge_date_not_future_dated(self):
        # The confusing future-looking "knowledge cutoff: <day>" is gone; the
        # source edition framing is used instead.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertNotIn("knowledge cutoff", body)
        self.assertIn("based on data through", body)

    def test_backtest_window_copy_is_2016_not_2020(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn("since 2016", body)
        self.assertNotIn("since 2020", body)

    def test_grid_suppresses_redundant_no_change_annotation(self):
        # Zero-delta cells (every baseline/persistence series) used to render a
        # per-cell "no change" label that wrapped mid-phrase and duplicated the
        # "baseline" marker on every FS cell. Only real +/− deltas are annotated
        # now; the footnote states that an unannotated date means no change.
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertNotIn("no change</span>", body)
        self.assertIn("forecast unchanged from the current bulletin", body)
        self.assertIn("+2m", body)  # real deltas still annotated

    def test_faq_answers_carry_inline_links(self):
        # The visible FAQ links methodology / accuracy archive / filing explainer;
        # the FAQPage JSON-LD keeps plain text (no escaped anchors in the blob).
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn('<a href="/predictions/">historical accuracy archive</a>', body)
        self.assertIn(
            '<a href="/analysis/how-my-prediction-model-works/">methodology</a>', body
        )
        self.assertIn(
            '<a href="/analysis/uscis-visa-bulletin-filing-dates-explained/">Dates for Filing</a>',
            body,
        )
        self.assertNotIn('<a href=\\"', body)  # JSON-LD answers stay link-free

    def test_faqpage_schema_present(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("When does the July 2026 Visa Bulletin come out?", body)
        self.assertIn("Will EB-2 India advance in the July 2026 Visa Bulletin?", body)

    def test_canonical_is_self(self):
        body = self.client.get("/predictions/july-2026/").content.decode()
        self.assertIn(
            'rel="canonical" href="http://testserver/predictions/july-2026/"', body
        )

    def test_published_month_renders_archive_in_place(self):
        # June 2026 has an actual bulletin -> the SAME slug URL now renders the
        # accuracy archive in place (self-canonical). No peak-intent 301 off the
        # ranking-established forecast URL when the bulletin drops.
        resp = self.client.get("/predictions/june-2026/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            b'<link rel="canonical" href="http://testserver/predictions/june-2026/">',
            resp.content,
        )
        self.assertIn(b"June 2026 Visa Bulletin", resp.content)

    def test_future_month_without_forecast_404(self):
        # September 2026: no stored predictions -> no thin page, no live solver.
        self.assertEqual(self.client.get("/predictions/september-2026/").status_code, 404)

    def test_invalid_month_slug_404(self):
        self.assertEqual(self.client.get("/predictions/foo-2026/").status_code, 404)

    def test_route_does_not_shadow_category_landing(self):
        # /predictions/employment_based/ must still resolve to the category landing
        # (redirect to latest month), NOT be captured by the forecast pattern. The
        # landing now redirects straight to the canonical monthname slug.
        resp = self.client.get("/predictions/employment_based/")
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/predictions/june-2026/", resp["Location"])
