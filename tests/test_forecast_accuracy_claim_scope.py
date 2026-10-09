"""The published 6-12 month accuracy figure names the model it measures.

Two models answer "where will this cutoff be in 6-12 months". The monthly
prediction pages (/predictions/<month>-<year>/) publish a horizon-specific
dispatch; its backtest is the 155-264 day MAE the FAQ quotes against a ~280 day
no-change baseline. The country dashboards' 6-Month / 12-Month columns roll the
next-bulletin forecast forward instead, and backtest at 302 / 448 days
(docs/PREDICTIONS_ASSESSMENT.md section 27). The FAQ text, its FAQPage JSON-LD
and the Spanish mirror must scope the figure to the monthly pages, and the
dashboard must state its own columns' error. Notion 3ac62b8d409f8183884ddd7831183ee5.
"""

import json
import re

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

_LD_JSON = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


def _faq_answers(body: str) -> list[str]:
    answers = []
    for block in _LD_JSON.findall(body):
        data = json.loads(block)
        if data.get("@type") != "FAQPage":
            continue
        answers.extend(q["acceptedAnswer"]["text"] for q in data["mainEntity"])
    return answers


def _sentences_with(text: str, needle: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if needle in s]


class TestFaqAccuracyClaimIsScopedToMonthlyPages(TestCase):
    def _assert_scoped(self, path: str, figure: str, scope: str) -> None:
        body = self.client.get(path).content.decode()
        answers = [a for a in _faq_answers(body) if figure in a]
        self.assertEqual(len(answers), 1, f"{path}: expected one FAQPage answer quoting {figure}")
        for sentence in _sentences_with(answers[0], figure):
            self.assertIn(scope, sentence)
        self.assertIn("visa-bulletin.us/predictions/", answers[0])

    def test_english_faqpage_json_ld(self):
        self._assert_scoped("/faq/", "155–264 days", "monthly prediction pages")

    def test_spanish_faqpage_json_ld(self):
        self._assert_scoped("/es/faq/", "155 a 264 días", "esas páginas")

    def test_english_visible_answer(self):
        body = self.client.get("/faq/").content.decode()
        visible = _LD_JSON.sub("", body)
        sentences = _sentences_with(re.sub(r"\s+", " ", visible), "155–264 days")
        self.assertEqual(len(sentences), 1)
        self.assertIn("On the monthly prediction pages", sentences[0])


class TestDashboardStatesRollForwardError(TestCase):
    def _render(self, show_vqs_column: bool) -> str:
        request = RequestFactory().get("/employment-based/india/")
        return render_to_string(
            "webapp/dashboard.html",
            {"unified_rows": [{"label": "EB-2"}], "show_vqs_column": show_vqs_column},
            request=request,
        )

    def test_note_names_the_method_and_its_error(self):
        body = re.sub(r"\s+", " ", self._render(show_vqs_column=True))
        self.assertIn("roll the next-bulletin forecast forward", body)
        self.assertIn("302 days at 6 months", body)
        self.assertIn("448 days at 12 months", body)
        self.assertNotIn("155", body)

    def test_note_absent_without_forecast_columns(self):
        body = self._render(show_vqs_column=False)
        self.assertNotIn("302 days at 6 months", body)
