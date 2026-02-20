"""Tests for generic clustering engine"""

import unittest

from lib.business import clustering_engine


class TestGetFuzzyBucketCandidates(unittest.TestCase):
    """Test fuzzy bucket candidate generation"""

    def test_generates_all_candidates(self):
        """Test that all three types of candidates are generated"""
        candidates = clustering_engine.get_fuzzy_bucket_candidates("hbss connec corp")

        # Should include exact name
        self.assertIn("hbss connec corp", candidates)

        # Should include word initials
        self.assertIn("hcc", candidates)  # h + c + c

        # Should include prefix+suffix
        self.assertIn("hbs...orp", candidates)

    def test_short_name(self):
        """Test with short name (< 6 chars)"""
        candidates = clustering_engine.get_fuzzy_bucket_candidates("abc")

        # Should include exact name but not prefix+suffix
        self.assertIn("abc", candidates)
        self.assertEqual(len([c for c in candidates if "..." in c]), 0)

    def test_single_word(self):
        """Test with single word"""
        candidates = clustering_engine.get_fuzzy_bucket_candidates("microsoft")

        # Should include exact name and prefix+suffix
        self.assertIn("microsoft", candidates)
        self.assertIn("mic...oft", candidates)

        # Should not include word initials (only 1 word)
        self.assertEqual(len([c for c in candidates if len(c) == 1]), 0)


class TestCalculateSimilarity(unittest.TestCase):
    """Test similarity calculation"""

    def test_identical_strings(self):
        """Test identical strings return 1.0"""
        similarity = clustering_engine.calculate_similarity("test", "test")
        self.assertEqual(similarity, 1.0)

    def test_completely_different(self):
        """Test completely different strings return low score"""
        similarity = clustering_engine.calculate_similarity("aaa", "bbb")
        self.assertLess(similarity, 0.5)

    def test_similar_strings(self):
        """Test similar strings return high score"""
        similarity = clustering_engine.calculate_similarity("microsoft", "microsof")
        self.assertGreater(similarity, 0.8)


if __name__ == "__main__":
    unittest.main()
