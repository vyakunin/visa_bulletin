"""Tests for generic clustering engine"""

import unittest
from dataclasses import dataclass

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


@dataclass
class _Entity:
    id: int
    name: str
    canonical_cluster: object | None = None


class _Config:
    """Config without a review hook: ambiguous pairs are not recorded."""

    def normalize_name(self, name: str) -> str:
        return name.lower()

    def has_conflicting_structural_words(self, name1: str, name2: str) -> bool:
        return False

    def should_apply_additional_filter(self, entity1, entity2, norm1, norm2) -> bool:
        return True

    def get_entity_model(self):
        return _Entity

    def get_cluster_model(self):
        return str

    def create_cluster(self, entity):
        return f"cluster:{entity.name}"


class _ReviewingConfig(_Config):
    def __init__(self):
        self.reviews = []

    def create_review_entry(self, entity1, entity2, similarity_score, match_reason):
        self.reviews.append((entity1.id, entity2.id))


def _assign(config, clustered, entity):
    index, normalized, buckets = clustering_engine.build_bucket_index(
        [clustered, entity], config
    )
    return clustering_engine.assign_to_cluster(
        entity,
        config,
        bucket_index=index,
        normalized_cache=normalized,
        bucket_cache=buckets,
        save=False,
    )


class TestAmbiguousPairs(unittest.TestCase):
    """A near-miss below the auto-cluster threshold gets its own cluster."""

    def setUp(self):
        # Same bucket ("sof...eer"), similarity ~0.81: queued for review, not merged.
        self.clustered = _Entity(1, "software engineer", canonical_cluster="existing")
        self.entity = _Entity(2, "software support engineer")

    def test_a_config_with_a_review_hook_queues_the_pair(self):
        config = _ReviewingConfig()
        cluster = _assign(config, self.clustered, self.entity)
        self.assertEqual(cluster, "cluster:software support engineer")
        self.assertEqual(config.reviews, [(1, 2)])

    def test_a_config_without_a_review_hook_clusters_without_recording(self):
        cluster = _assign(_Config(), self.clustered, self.entity)
        self.assertEqual(cluster, "cluster:software support engineer")


if __name__ == "__main__":
    unittest.main()
