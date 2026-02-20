"""
Job title-specific clustering configuration.

This module implements the EntityClusteringConfig protocol for job title clustering,
leveraging the JobTitle model's normalization logic.
"""

from lib.business.salary.generic_words import GENERIC_WORDS
from models.job_title import JobTitle, JobTitleCluster, JobTitleClusteringReview

# Job-title-specific generic words (extend employer generic words)
JOB_TITLE_GENERIC_WORDS = GENERIC_WORDS | {
    "specialist",
    "associate",
    "analyst",
    "coordinator",
    "representative",
    "technician",
    "assistant",
    "consultant",
    "advisor",
    "officer",
}


class JobTitleClusteringConfig:
    """Configuration for job title clustering using the generic framework."""

    def normalize_name(self, title: str) -> str:
        """Normalize job title for matching."""
        return JobTitle.normalize_title(title)

    def extract_structural_words(self, title: str) -> set[str]:
        """
        Extract structural words that distinguish different job titles.

        For job titles, structural words are less relevant than for employers
        because we already extract experience level separately. However, we
        still use generic words to help filter out noise.
        """
        import re

        # Normalize and extract words
        normalized = title.lower()
        # Remove punctuation, keep words
        words = set(re.findall(r"\b\w+\b", normalized))

        # Return intersection with generic words (these can help distinguish)
        return words & JOB_TITLE_GENERIC_WORDS

    def has_conflicting_structural_words(self, title1: str, title2: str) -> bool:
        """
        Check if two job titles have conflicting structural words.

        For job titles, we're less strict than employers. We mainly check if
        there are completely different core words (e.g., "Engineer" vs "Nurse").
        This is less critical since we already separate by experience level.
        """
        # Extract core words (excluding generic words)
        words1 = set(title1.lower().split()) - JOB_TITLE_GENERIC_WORDS
        words2 = set(title2.lower().split()) - JOB_TITLE_GENERIC_WORDS

        # If no overlap in core words, they're likely different titles
        if words1 and words2 and not (words1 & words2):
            # Exception: If one is a subset of the other, not conflicting
            if not (words1.issubset(words2) or words2.issubset(words1)):
                return True

        return False

    def should_apply_additional_filter(
        self, entity1: JobTitle, entity2: JobTitle, norm1: str, norm2: str
    ) -> bool:
        """
        Additional filtering for job title clustering.

        We intentionally cluster across experience levels so that
        "Software Engineer", "Senior Software Engineer", and "Software Engineer II"
        all belong to one job-family cluster.  The experience level is preserved on
        each JobTitle entity for drill-down analysis.
        """
        return True

    def get_entity_model(self) -> type[JobTitle]:
        """Return the JobTitle model class."""
        return JobTitle

    def get_cluster_model(self) -> type[JobTitleCluster]:
        """Return the JobTitleCluster model class."""
        return JobTitleCluster

    def get_review_model(self) -> type[JobTitleClusteringReview]:
        """Return the JobTitleClusteringReview model class."""
        return JobTitleClusteringReview

    def create_cluster(self, entity: JobTitle) -> JobTitleCluster:
        """
        Create a new cluster for a job title.

        Uses job-title-specific field name (canonical_title instead of canonical_name).
        """
        return JobTitleCluster.objects.create(canonical_title=entity.title)

    def create_review_entry(
        self,
        entity1: JobTitle,
        entity2: JobTitle,
        similarity_score: float,
        match_reason: str,
    ):
        """
        Create a review queue entry for ambiguous job title pairs.

        Uses job-title-specific field names (job_title1, job_title2).
        """
        JobTitleClusteringReview.objects.get_or_create(
            job_title1=entity1,
            job_title2=entity2,
            defaults={
                "similarity_score": similarity_score,
                "match_reason": match_reason,
                "status": "pending",
            },
        )
