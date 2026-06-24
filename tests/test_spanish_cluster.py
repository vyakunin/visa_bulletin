"""Tests for the Spanish (/es/) SEO cluster.

Locks: the ES priority-date landing reuses the EN data path but renders Spanish
chrome (heading, dates, trend, FAQPage schema) with bidirectional hreflang; the
ES FAQ / hub / predictions pages render with FAQPage schema (FAQ) and reciprocal
hreflang; the EN priority-date landing now emits the reciprocal hreflang to its
ES sibling; the sitemap lists the ES URLs. Mirrors the slug sets in
webapp/views/bulletin/priority_date_landing.py.
"""

from datetime import date

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate


def _cutoff(bulletin, action_type, country, cutoff_date):
    VisaCutoffDate.objects.create(
        bulletin=bulletin,
        visa_category="employment_based",
        visa_class="2nd",  # EmploymentPreference.EB2 -> "EB-2: ..."
        action_type=action_type,
        country=country,
        cutoff_value=cutoff_date.strftime("%d%b%y").upper(),
        cutoff_date=cutoff_date,
        is_current=False,
        is_unavailable=False,
    )


class TestSpanishPriorityDateLanding(TestCase):
    def setUp(self):
        b1 = Bulletin.objects.create(publication_date=date(2026, 6, 1))
        b2 = Bulletin.objects.create(publication_date=date(2026, 7, 1))
        # EB-2 India Final Action advanced Jan->Feb 2013 month-over-month.
        _cutoff(b1, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 1, 1))
        _cutoff(b2, ActionType.FINAL_ACTION.value, Country.INDIA.value, date(2013, 2, 1))
        _cutoff(b1, ActionType.FILING.value, Country.INDIA.value, date(2013, 6, 1))
        _cutoff(b2, ActionType.FILING.value, Country.INDIA.value, date(2013, 7, 1))

    def test_renders_spanish(self):
        resp = self.client.get("/es/priority-date/eb2/india/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Fecha de Prioridad EB-2 India", body)  # Spanish H1
        self.assertIn("1 de febrero de 2013", body)  # current Final Action, Spanish date
        self.assertIn("1 de julio de 2013", body)  # current Dates for Filing
        self.assertIn("avanzó", body)  # Spanish trend copy (advance)
        self.assertIn('lang="es"', body)

    def test_faqpage_schema_and_spanish_questions(self):
        body = self.client.get("/es/priority-date/eb2/india/").content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("¿Cuál es la fecha de prioridad", body)
        # Featured-snippet parity with EN: lead paragraph + FAQ as <h3> headings.
        self.assertIn('class="lead"', body)
        self.assertIn("la Fecha de Acción Final de EB-2 para India es", body)
        self.assertIn('<h3 class="h6 fw-semibold mb-1">', body)

    def test_canonical_is_self(self):
        body = self.client.get("/es/priority-date/eb2/india/").content.decode()
        self.assertIn(
            'rel="canonical" href="http://testserver/es/priority-date/eb2/india/"', body
        )

    def test_bidirectional_hreflang(self):
        body = self.client.get("/es/priority-date/eb2/india/").content.decode()
        self.assertIn(
            'hreflang="es" href="http://testserver/es/priority-date/eb2/india/"', body
        )
        self.assertIn(
            'hreflang="en" href="http://testserver/priority-date/eb2/india/"', body
        )

    def test_en_landing_links_to_es_sibling(self):
        # The EN page must declare the reciprocal hreflang for the pair to count.
        body = self.client.get("/priority-date/eb2/india/").content.decode()
        self.assertIn(
            'hreflang="es" href="http://testserver/es/priority-date/eb2/india/"', body
        )

    def test_unknown_class_404(self):
        self.assertEqual(self.client.get("/es/priority-date/eb9/india/").status_code, 404)

    def test_unknown_country_404(self):
        self.assertEqual(self.client.get("/es/priority-date/eb2/atlantis/").status_code, 404)

    def test_no_data_combo_404(self):
        # eb1/mexico has no cutoff rows in this fixture -> no thin page (mirrors EN).
        self.assertEqual(self.client.get("/es/priority-date/eb1/mexico/").status_code, 404)


class TestSpanishStaticPages(TestCase):
    def test_faq_renders_with_schema(self):
        resp = self.client.get("/es/faq/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('"@type": "FAQPage"', body)
        self.assertIn("Preguntas frecuentes", body)
        self.assertIn('hreflang="en" href="http://testserver/faq/"', body)

    def test_hub_renders_with_all_landing_links(self):
        body = self.client.get("/es/priority-date/").content.decode()
        self.assertEqual(self.client.get("/es/priority-date/").status_code, 200)
        # All 12 EB x country combos linked.
        for eb in ("eb1", "eb2", "eb3"):
            for ctry in ("india", "china", "philippines", "mexico"):
                self.assertIn(f"/es/priority-date/{eb}/{ctry}/", body)

    def test_predictions_renders(self):
        resp = self.client.get("/es/predictions/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Bulletin Forecast", body)
        self.assertIn('hreflang="en" href="http://testserver/predictions/"', body)


class TestSpanishSitemap(TestCase):
    def setUp(self):
        Bulletin.objects.create(publication_date=date(2026, 7, 1))

    def test_sitemap_lists_es_urls(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("/es/faq/", body)
        self.assertIn("/es/predictions/", body)
        self.assertIn("/es/priority-date/", body)
        self.assertIn("/es/priority-date/eb2/india/", body)
