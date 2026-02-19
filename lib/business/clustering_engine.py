"""
Generic clustering engine for entity matching and grouping.

This module provides a reusable framework for clustering any type of entity
(employers, job titles, etc.) based on normalized name similarity.

Key features:
- Generic implementation works for any entity type
- Entity-specific behavior via EntityClusteringConfig protocol
- Fuzzy matching with bucket candidates
- High-confidence auto-clustering
- Review queue for ambiguous matches
"""

import difflib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeVar

# Generic type variables for entities and clusters
EntityType = TypeVar('EntityType')
ClusterType = TypeVar('ClusterType')


class ClusterableEntity(Protocol):
    """Protocol for entities that can be clustered."""
    id: int
    name: str  # Original name
    name_normalized: str  # Normalized name for matching
    canonical_cluster: ClusterType | None


class EntityClusteringConfig(Protocol[EntityType, ClusterType]):
    """
    Configuration interface for entity-specific clustering behavior.
    
    Implement this protocol to customize clustering for different entity types.
    """

    def normalize_name(self, name: str) -> str:
        """Normalize entity name for matching."""
        ...

    def extract_structural_words(self, name: str) -> set[str]:
        """Extract words that distinguish different entities."""
        ...

    def has_conflicting_structural_words(self, name1: str, name2: str) -> bool:
        """Check if two names have conflicting structural words."""
        ...

    def should_apply_additional_filter(
        self,
        entity1: EntityType,
        entity2: EntityType,
        norm1: str,
        norm2: str
    ) -> bool:
        """
        Apply entity-specific filtering (e.g., location for employers, SOC for job titles).
        
        Returns: True if entities pass the filter (should be compared), False otherwise.
        """
        ...

    def get_entity_model(self) -> type[EntityType]:
        """Return the entity model class."""
        ...

    def get_cluster_model(self) -> type[ClusterType]:
        """Return the cluster model class."""
        ...

    def get_review_model(self):
        """Return the review model class for ambiguous pairs."""
        ...

    def create_review_entry(
        self,
        entity1: EntityType,
        entity2: EntityType,
        similarity_score: float,
        match_reason: str
    ):
        """Create a review queue entry for ambiguous pairs (entity-specific field names)."""
        ...


@dataclass
class MatchResult:
    """Result of comparing two entities."""
    is_match: bool
    confidence: float  # 0.0-1.0
    reason: str


def build_bucket_index(
    entities: Iterable[EntityType],
    config: EntityClusteringConfig[EntityType, ClusterType]
) -> tuple[dict[str, list[EntityType]], dict[int, str], dict[int, set[str]]]:
    """
    Build a bucket index and normalization caches for faster matching.

    Returns:
        bucket_index: Mapping bucket -> list of entities in bucket
        normalized_cache: Mapping entity.id -> normalized name
        bucket_cache: Mapping entity.id -> bucket candidates
    """
    bucket_index: dict[str, list[EntityType]] = {}
    normalized_cache: dict[int, str] = {}
    bucket_cache: dict[int, set[str]] = {}

    for entity in entities:
        normalized = config.normalize_name(entity.name)
        normalized_cache[entity.id] = normalized
        buckets = get_fuzzy_bucket_candidates(normalized)
        bucket_cache[entity.id] = buckets

        for bucket in buckets:
            bucket_index.setdefault(bucket, []).append(entity)

    return bucket_index, normalized_cache, bucket_cache


def get_fuzzy_bucket_candidates(normalized_name: str) -> set[str]:
    """
    Generate multiple bucket candidates for fuzzy matching.
    
    This helps catch typos and variations that normalize to different buckets.
    Returns a set of bucket keys that should be checked for potential matches.
    
    Strategy:
    1. Exact normalized name (primary bucket)
    2. Word initials (catches typos like "CONNEC" vs "Connect")
    3. First 3 chars + last 3 chars (catches variations in middle)
    
    Returns: Set of bucket candidate strings
    
    Examples:
        >>> get_fuzzy_bucket_candidates("hbss connec corp")
        {'hbss connec corp', 'hcc', 'hbs...orp'}
        
        >>> get_fuzzy_bucket_candidates("mercede benz van")
        {'mercede benz van', 'mbv', 'mer...van'}
    """
    candidates = {normalized_name}

    # Word initials: "hbss connec corp" -> "hcc", "hbss connect corp" -> "hcc"
    # This catches typos in the middle of words
    words = normalized_name.split()
    if len(words) >= 2:
        initials = ''.join(w[0] if w else '' for w in words[:5])  # First letter of first 5 words
        if len(initials) >= 2:  # Only use if at least 2 words
            candidates.add(initials)

    # Prefix + suffix: "mercedesbenz van" -> "mer...van", "mercede benz van" -> "mer...van"
    # This catches spacing/hyphen variations
    if len(normalized_name) >= 6:
        prefix = normalized_name[:3]
        suffix = normalized_name[-3:]
        candidates.add(f"{prefix}...{suffix}")

    return candidates


def calculate_similarity(norm1: str, norm2: str) -> float:
    """
    Calculate similarity score between two normalized names.
    
    Uses Python's difflib.SequenceMatcher for sequence similarity.
    
    Returns: float between 0.0 (completely different) and 1.0 (identical)
    """
    return difflib.SequenceMatcher(None, norm1, norm2).ratio()


def match_entities(
    entity1: EntityType,
    entity2: EntityType,
    config: EntityClusteringConfig[EntityType, ClusterType],
    norm1: str | None = None,
    norm2: str | None = None
) -> MatchResult:
    """
    Hybrid matching algorithm: rule-based checks first, then similarity-based fallback.
    
    This is the core matching logic extracted from employer_clustering.py.
    
    Flow:
    1. Hyphen variation check
    2. Exact normalized name match
    3. Substring match
    4. Similarity-based fallback
    
    Args:
        entity1: First entity to compare
        entity2: Second entity to compare
        config: Entity-specific configuration
        norm1: Optional pre-computed normalized name for entity1
        norm2: Optional pre-computed normalized name for entity2
    
    Returns: MatchResult with is_match, confidence, and reason
    """
    # Normalize names if not provided
    if norm1 is None:
        norm1 = config.normalize_name(entity1.name)
    if norm2 is None:
        norm2 = config.normalize_name(entity2.name)

    # Apply entity-specific filtering (e.g., location, SOC code)
    if not config.should_apply_additional_filter(entity1, entity2, norm1, norm2):
        return MatchResult(is_match=False, confidence=0.0, reason="Failed entity-specific filter")

    # Rule 1: Exact normalized name match
    if norm1 == norm2:
        # Check for structural word conflicts
        if config.has_conflicting_structural_words(entity1.name, entity2.name):
            return MatchResult(
                is_match=False,
                confidence=0.0,
                reason="Structural word conflict (same normalized name, different structural words)"
            )
        return MatchResult(is_match=True, confidence=1.0, reason="Exact normalized match")

    # Rule 2: Substring match (one name contains the other)
    if norm1 in norm2 or norm2 in norm1:
        # Check for structural word conflicts
        if config.has_conflicting_structural_words(entity1.name, entity2.name):
            return MatchResult(
                is_match=False,
                confidence=0.0,
                reason="Structural word conflict (substring match)"
            )
        # High confidence for substring matches without conflicts
        return MatchResult(is_match=True, confidence=0.95, reason="Substring match")

    # Rule 3: High similarity score
    similarity = calculate_similarity(norm1, norm2)

    # Very high similarity (>= 0.98) without structural conflicts
    if similarity >= 0.98:
        if config.has_conflicting_structural_words(entity1.name, entity2.name):
            return MatchResult(
                is_match=False,
                confidence=0.0,
                reason=f"Structural word conflict (high similarity: {similarity:.2f})"
            )
        return MatchResult(
            is_match=True,
            confidence=similarity,
            reason=f"Very high similarity ({similarity:.2f})"
        )

    # High similarity (>= 0.90) without structural conflicts
    if similarity >= 0.90:
        if config.has_conflicting_structural_words(entity1.name, entity2.name):
            return MatchResult(
                is_match=False,
                confidence=0.0,
                reason=f"Structural word conflict (similarity: {similarity:.2f})"
            )
        return MatchResult(
            is_match=True,
            confidence=similarity,
            reason=f"High similarity ({similarity:.2f})"
        )

    # No match
    return MatchResult(is_match=False, confidence=similarity, reason=f"Low similarity ({similarity:.2f})")


def should_auto_cluster(
    entity1: EntityType,
    entity2: EntityType,
    config: EntityClusteringConfig[EntityType, ClusterType],
    threshold: float = 0.95,
    norm1: str | None = None,
    norm2: str | None = None
) -> MatchResult:
    """
    Determine if two entities should be auto-clustered.
    
    Args:
        entity1: First entity
        entity2: Second entity
        config: Entity-specific configuration
        threshold: Confidence threshold for auto-clustering (0.0-1.0)
        norm1: Optional pre-computed normalized name for entity1
        norm2: Optional pre-computed normalized name for entity2
    
    Returns: MatchResult (is_match True if should auto-cluster)
    """
    result = match_entities(entity1, entity2, config, norm1, norm2)

    if result.is_match and result.confidence >= threshold:
        return result

    # Don't auto-cluster if confidence is below threshold
    return MatchResult(
        is_match=False,
        confidence=result.confidence,
        reason=result.reason
    )


def assign_to_cluster(
    entity: EntityType,
    config: EntityClusteringConfig[EntityType, ClusterType],
    auto_approve_threshold: float = 0.95,
    bucket_index: dict[str, list[EntityType]] | None = None,
    normalized_cache: dict[int, str] | None = None,
    bucket_cache: dict[int, set[str]] | None = None
) -> ClusterType:
    """
    Find existing cluster or create new one for an entity.
    
    Searches for existing clusters with similar normalized names.
    If high-confidence match found → assign to existing cluster
    If ambiguous → create new cluster, add to review queue
    If no match → create new cluster
    
    Args:
        entity: Entity to assign to a cluster
        config: Entity-specific configuration
        auto_approve_threshold: Confidence threshold for auto-clustering
    
    Returns: Cluster instance
    """
    # If already assigned, return existing cluster
    if entity.canonical_cluster:
        return entity.canonical_cluster

    # Get model classes from config
    EntityModel = config.get_entity_model()
    ClusterModel = config.get_cluster_model()

    # Normalize entity name
    if normalized_cache is not None and entity.id in normalized_cache:
        entity_normalized = normalized_cache[entity.id]
    else:
        entity_normalized = config.normalize_name(entity.name)
        if normalized_cache is not None:
            normalized_cache[entity.id] = entity_normalized

    # Use fuzzy bucket matching to catch typos and variations
    if bucket_cache is not None and entity.id in bucket_cache:
        bucket_candidates = bucket_cache[entity.id]
    else:
        bucket_candidates = get_fuzzy_bucket_candidates(entity_normalized)
        if bucket_cache is not None:
            bucket_cache[entity.id] = bucket_candidates

    # Get candidates from bucket index if provided
    if bucket_index is not None:
        candidate_entities: dict[int, EntityType] = {}
        for bucket in bucket_candidates:
            for other_entity in bucket_index.get(bucket, []):
                if other_entity.id != entity.id:
                    candidate_entities[other_entity.id] = other_entity
        similar_entities = list(candidate_entities.values())
    else:
        # Fallback: full scan if no index provided
        all_entities = EntityModel.objects.exclude(id=entity.id).select_related('canonical_cluster')
        similar_entities = []
        for other_entity in all_entities:
            if normalized_cache is not None and other_entity.id in normalized_cache:
                other_normalized = normalized_cache[other_entity.id]
            else:
                other_normalized = config.normalize_name(other_entity.name)
                if normalized_cache is not None:
                    normalized_cache[other_entity.id] = other_normalized

            if bucket_cache is not None and other_entity.id in bucket_cache:
                other_buckets = bucket_cache[other_entity.id]
            else:
                other_buckets = get_fuzzy_bucket_candidates(other_normalized)
                if bucket_cache is not None:
                    bucket_cache[other_entity.id] = other_buckets

            # If any bucket candidate overlaps, they might be the same entity
            if bucket_candidates & other_buckets:
                similar_entities.append(other_entity)

    # Check if any similar entities are already in clusters
    for similar_entity in similar_entities:
        if similar_entity.canonical_cluster:
            # Found existing cluster - check if we should join it
            if normalized_cache is not None and similar_entity.id in normalized_cache:
                similar_normalized = normalized_cache[similar_entity.id]
            else:
                similar_normalized = config.normalize_name(similar_entity.name)
                if normalized_cache is not None:
                    normalized_cache[similar_entity.id] = similar_normalized

            result = should_auto_cluster(
                entity,
                similar_entity,
                config,
                threshold=auto_approve_threshold,
                norm1=entity_normalized,
                norm2=similar_normalized
            )

            if result.is_match:
                # Auto-assign to existing cluster
                entity.canonical_cluster = similar_entity.canonical_cluster
                entity.save()
                return entity.canonical_cluster
            else:
                # Ambiguous - add to review queue (only if reasonably similar)
                match_result = match_entities(
                    entity,
                    similar_entity,
                    config,
                    norm1=entity_normalized,
                    norm2=similar_normalized
                )
                if match_result.confidence >= 0.6:  # Only queue reasonably similar names
                    config.create_review_entry(
                        min(entity, similar_entity, key=lambda e: e.id),
                        max(entity, similar_entity, key=lambda e: e.id),
                        match_result.confidence,
                        match_result.reason or f"Fuzzy match: {match_result.confidence:.3f}"
                    )

    # No match found - create new cluster
    # Use config's create_cluster method if available, otherwise use default
    if hasattr(config, 'create_cluster'):
        cluster = config.create_cluster(entity)
    else:
        cluster = ClusterModel.objects.create(
            canonical_name=entity.name
        )
    entity.canonical_cluster = cluster
    entity.save()

    return cluster

