"""Regression: the dashboard must emit a keyword-bearing <h1> (page_heading).

The homepage shipped with NO <h1> at all (first heading was an <h2> "Filter
Options") while ranking ~pos 8 for the head term "visa bulletin" — an empty
on-page relevance signal. build_seo_metadata now returns page_heading; these
tests lock it so a refactor can't silently drop the H1 again.
"""
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest
from datetime import date
from unittest.mock import patch

from lib.business.bulletin import cutoff_data_aggregator as agg
from models.enums.country import Country
from models.enums.visa_category import VisaCategory


class TestPageHeading(unittest.TestCase):
    @patch.object(agg, "_latest_bulletin_month", return_value=date(2026, 7, 1))
    def test_root_heading_is_keyword_bearing(self, _m):
        seo = agg.build_seo_metadata(
            VisaCategory.EMPLOYMENT_BASED.value, Country.INDIA.value,
            "http://testserver/", is_root=True,
        )
        self.assertIn("page_heading", seo)
        self.assertTrue(seo["page_heading"].strip(), "homepage H1 must be non-empty")
        self.assertIn("Visa Bulletin", seo["page_heading"])

    @patch.object(agg, "_latest_bulletin_month", return_value=date(2026, 7, 1))
    def test_filtered_heading_is_keyword_bearing(self, _m):
        seo = agg.build_seo_metadata(
            VisaCategory.EMPLOYMENT_BASED.value, Country.INDIA.value,
            "http://testserver/", is_root=False,
        )
        self.assertTrue(seo["page_heading"].strip())
        self.assertIn("Visa Bulletin", seo["page_heading"])
        # filtered heading should carry the country for intent match
        self.assertIn("India", seo["page_heading"])


if __name__ == "__main__":
    unittest.main()
