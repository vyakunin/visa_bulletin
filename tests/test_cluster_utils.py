"""Tests for employer clustering utilities"""

import unittest

from lib.business.salary.cluster_utils import normalize_canonical_name


class TestNormalizeCanonicalName(unittest.TestCase):
    """Test canonical name normalization for case-insensitive lookups"""

    def test_lowercase_conversion(self):
        """Test that names are converted to lowercase"""
        self.assertEqual(
            normalize_canonical_name("BBC RETAIL AND INTERNET LLC"),
            "bbc retail and internet llc",
        )

    def test_mixed_case_normalization(self):
        """Test that mixed case names normalize to same value"""
        names = [
            "BBC Retail and Internet LLC",
            "BBC RETAIL AND INTERNET LLC",
            "bbc retail and internet llc",
            "Bbc Retail And Internet LLC",
        ]

        # All should normalize to same value
        normalized = [normalize_canonical_name(name) for name in names]
        self.assertEqual(len(set(normalized)), 1)
        self.assertEqual(normalized[0], "bbc retail and internet llc")

    def test_preserves_spaces_and_punctuation(self):
        """Test that spaces and punctuation are preserved"""
        self.assertEqual(
            normalize_canonical_name("J.P. Morgan Chase & Co"), "j.p. morgan chase & co"
        )

    def test_empty_string(self):
        """Test that empty string remains empty"""
        self.assertEqual(normalize_canonical_name(""), "")

    def test_single_word(self):
        """Test single word names"""
        self.assertEqual(normalize_canonical_name("GOOGLE"), "google")
        self.assertEqual(normalize_canonical_name("Google"), "google")
        self.assertEqual(normalize_canonical_name("google"), "google")

    def test_numbers_preserved(self):
        """Test that numbers are preserved"""
        self.assertEqual(normalize_canonical_name("3M Company"), "3m company")

    def test_unicode_characters(self):
        """Test that unicode characters are handled"""
        self.assertEqual(
            normalize_canonical_name("Café Corporation"), "café corporation"
        )


if __name__ == "__main__":
    unittest.main()
