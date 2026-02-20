"""Tests for lib.utils.url_utils (source URL normalization and dedup)."""

import unittest

from lib.utils.url_utils import normalize_source_url, path_basename_from_url


class TestNormalizeSourceUrl(unittest.TestCase):
    """Test normalize_source_url produces canonical form for dedup."""

    def test_http_becomes_https(self):
        self.assertEqual(
            normalize_source_url("http://www.dol.gov/agencies/eta/PERM_FY2024.xlsx"),
            "https://www.dol.gov/agencies/eta/PERM_FY2024.xlsx",
        )

    def test_netloc_lowercase(self):
        self.assertEqual(
            normalize_source_url("https://WWW.DOL.GOV/agencies/eta/PERM_FY2024.xlsx"),
            "https://www.dol.gov/agencies/eta/PERM_FY2024.xlsx",
        )

    def test_strips_query_and_fragment(self):
        self.assertEqual(
            normalize_source_url("https://dol.gov/file.xlsx?tracking=1#section"),
            "https://dol.gov/file.xlsx",
        )

    def test_strips_trailing_slash(self):
        self.assertEqual(
            normalize_source_url("https://dol.gov/path/"),
            "https://dol.gov/path",
        )

    def test_empty_returns_as_is(self):
        self.assertEqual(normalize_source_url(""), "")
        self.assertEqual(normalize_source_url("   "), "   ")


class TestPathBasenameFromUrl(unittest.TestCase):
    """Test path_basename_from_url for same-file dedup."""

    def test_returns_last_segment(self):
        self.assertEqual(
            path_basename_from_url(
                "https://www.dol.gov/agencies/eta/foreign-labor/PERM_FY2024.xlsx"
            ),
            "PERM_FY2024.xlsx",
        )

    def test_same_filename_different_paths(self):
        url1 = "https://www.dol.gov/agencies/eta/foreign-labor/PERM_FY2024.xlsx"
        url2 = "https://www.dol.gov/agencies/eta/foreign-labor/performance/PERM_FY2024.xlsx"
        self.assertEqual(path_basename_from_url(url1), "PERM_FY2024.xlsx")
        self.assertEqual(path_basename_from_url(url2), "PERM_FY2024.xlsx")

    def test_empty_returns_empty(self):
        self.assertEqual(path_basename_from_url(""), "")
        self.assertEqual(path_basename_from_url("https://dol.gov"), "")
