"""
Employer-specific clustering configuration.

This module implements the EntityClusteringConfig protocol for employer clustering,
so the generic engine in lib/business/clustering_engine.py can drive employers.

It must not import employer_clustering: that module instantiates
EmployerClusteringConfig at import time, so the pair would form a cycle. The
name-comparison logic both need lives in the structural_words leaf.
"""

from lib.business.salary import structural_words
from lib.business.salary.generic_words import VERY_GENERIC_WORDS
from lib.utils.location_utils import normalize_state_code
from models.salary import Employer, EmployerCluster, EmployerClusteringReview


class EmployerClusteringConfig:
    """Configuration for employer clustering using the generic framework."""

    def normalize_name(self, name: str) -> str:
        """Normalize employer name for matching."""
        return Employer.normalize_name(name)

    def extract_structural_words(self, name: str) -> set[str]:
        """Extract structural words that distinguish different employers."""
        return structural_words.extract_structural_words(name)

    def has_conflicting_structural_words(self, name1: str, name2: str) -> bool:
        """Check if two employer names have conflicting structural words."""
        return structural_words.has_conflicting_structural_words(name1, name2)

    def should_apply_additional_filter(
        self, entity1: Employer, entity2: Employer, norm1: str, norm2: str
    ) -> bool:
        """
        Apply location-based filtering for very generic employer names.

        For names like "hospital", "school", "center", requires same state.
        This prevents matching generic names across different locations.
        """
        # Check if either normalized name contains very generic words
        norm1_words = set(norm1.split())
        norm2_words = set(norm2.split())

        has_very_generic1 = bool(norm1_words & VERY_GENERIC_WORDS)
        has_very_generic2 = bool(norm2_words & VERY_GENERIC_WORDS)

        if has_very_generic1 or has_very_generic2:
            # Very generic name - require same state
            state1 = normalize_state_code(entity1.state) if entity1.state else None
            state2 = normalize_state_code(entity2.state) if entity2.state else None

            if state1 != state2:
                # Different states - don't match
                return False

        # Pass filter
        return True

    def get_entity_model(self) -> type[Employer]:
        """Return the Employer model class."""
        return Employer

    def get_cluster_model(self) -> type[EmployerCluster]:
        """Return the EmployerCluster model class."""
        return EmployerCluster

    def get_review_model(self) -> type[EmployerClusteringReview]:
        """Return the EmployerClusteringReview model class."""
        return EmployerClusteringReview

    def create_review_entry(
        self,
        entity1: Employer,
        entity2: Employer,
        similarity_score: float,
        match_reason: str,
    ):
        """
        Create a review queue entry for ambiguous employer pairs.

        Uses employer-specific field names (employer1, employer2).
        """
        EmployerClusteringReview.objects.get_or_create(
            employer1=entity1,
            employer2=entity2,
            defaults={
                "similarity_score": similarity_score,
                "match_reason": match_reason,
                "status": "pending",
            },
        )
