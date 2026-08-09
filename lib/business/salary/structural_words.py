"""Structural-word comparison for employer names — a leaf of the clustering graph.

Two employers whose names share a stem but differ in a *structural* word ("Macro
Consultants" vs "Macro International") are usually different entities. These two
functions decide that, and they are the only part of employer matching that both
`employer_clustering` (the matcher) and `employer_config` (the
EntityClusteringConfig adapter the generic engine calls) need.

They live here rather than in `employer_clustering` because those two modules
import each other: `employer_clustering` constructs an `EmployerClusteringConfig`
at module level, so importing `employer_config` first raised ImportError on a
partially initialized module. Bazel cannot express a cycle as deps in either
direction, so the pair sat in the dep-checker allowlist until this module split
the shared surface out. Keep this module a leaf — `generic_words` and stdlib only.
"""

import re

from lib.business.salary.generic_words import (
    DISTINGUISHING_GENERIC_WORDS,
    GENERIC_WORDS,
)

# Words that distinguish company types/structures. GENERIC_WORDS can distinguish
# when they DIFFER between two names, so they count as structural here even
# though normalization strips them from the name itself.
STRUCTURAL_WORDS = (
    GENERIC_WORDS
    | DISTINGUISHING_GENERIC_WORDS
    | {
        "north",
        "south",
        "east",
        "west",  # Geographic qualifiers can distinguish
        "america",
        "americas",  # "North America" vs other regions
    }
)

# Corporate entity types all meaning "company" — a subset of GENERIC_WORDS. Two
# names differing only in one of these ("Edgesoft Corp" / "Edgesoft Inc") do not
# conflict, so these drop out before the comparison.
EQUIVALENT_SUFFIXES = {
    "corporation",
    "corp",
    "incorporated",
    "inc",
    "llc",
    "limited",
    "ltd",
    "company",
    "co",
}

# Singular/plural and verb-form variants of one concept. Deliberately narrow:
# most near-synonyms SHOULD conflict, so widening this costs precision.
EQUIVALENT_VARIANTS = [
    {"consultants", "consulting", "consultant"},  # Same concept: consulting business
    {"technologies", "technology", "tech"},  # Same concept: tech company
    {"industries", "industry"},  # Same concept: industry
    {"enterprises", "enterprise"},  # Same concept: enterprise
    {"holdings", "holding"},  # Same concept: holding company
    {"groups", "group"},  # Same concept: group
    {"solutions", "solution"},  # Same concept: solution provider
    {"services", "service"},  # Same concept: service provider
    {"systems", "system"},  # Same concept: system provider
    {"america", "americas"},  # Same concept: geographic region
    {"us", "usa"},  # Same concept: United States (BBC News US vs BBC News USA)
    {"global", "international"},  # Same concept: worldwide operations
]

# Words that indicate DIFFERENT company types, so two names drawing different
# words from one group conflict even though both words are structural.
CONFLICTING_WORD_GROUPS = [
    # Business type conflicts - these indicate different company types
    {"management", "holdings"},  # Management company vs holding company
    {"management", "corporation"},  # Management vs corporation (when both present)
    {"technologies", "consulting"},  # Tech company vs consulting firm
    {"technologies", "partners"},  # Tech company vs partnership
    {"consulting", "partners"},  # Consulting vs partnership
    {"management", "partners"},  # Management vs partnership
    # Industry/domain conflicts
    {"capital", "holdings"},  # Capital management vs holdings
    {"capital", "partners"},  # Capital vs partnership
]


def extract_structural_words(name: str) -> set[str]:
    """
    Extract structural/generic words that could distinguish companies.

    These are words that, if different between two names, suggest different entities.

    Note: This includes GENERIC_WORDS plus additional distinguishing words (geographic,
    distinguishing generic words, etc.) that can help identify different companies.
    """
    # Normalize and extract words
    normalized = name.lower()
    # Remove punctuation, keep words
    words = set(re.findall(r"\b\w+\b", normalized))

    # Return intersection with structural words
    return words & STRUCTURAL_WORDS


def _normalize_group(word_set: set[str], equiv_groups: list[set[str]]) -> set[str]:
    """Replace equivalent words with first item in group"""
    normalized = set(word_set)
    for equiv_group in equiv_groups:
        if normalized & equiv_group:
            # Replace all variants with canonical (first one, sorted for determinism)
            canonical = sorted(equiv_group)[0]
            normalized = normalized - equiv_group
            normalized.add(canonical)
    return normalized


def has_conflicting_structural_words(name1: str, name2: str) -> bool:
    """
    Check if two names have conflicting structural words that suggest different entities.

    Examples:
    - "Macro Consultants" vs "Macro International" → True (Consultants ≠ International)
    - "SYNAPSE GROUP" vs "SYNAPSE TECHNOLOGIES" → True (Group ≠ Technologies)
    - "Edgesoft Corp" vs "Edgesoft Inc" → False (Corp/Inc are equivalent corporate suffixes)
    """
    structural1 = extract_structural_words(name1)
    structural2 = extract_structural_words(name2)

    # Remove equivalent suffixes (they don't distinguish companies)
    structural1_no_suffix = structural1 - EQUIVALENT_SUFFIXES
    structural2_no_suffix = structural2 - EQUIVALENT_SUFFIXES

    # Normalize equivalent variants
    structural1_normalized = _normalize_group(structural1_no_suffix, EQUIVALENT_VARIANTS)
    structural2_normalized = _normalize_group(structural2_no_suffix, EQUIVALENT_VARIANTS)

    # If one name has a word from a conflict group and the other name has a different word
    # from the same conflict group, it's a conflict
    for conflict_group in CONFLICTING_WORD_GROUPS:
        words1_in_group = conflict_group & structural1_normalized
        words2_in_group = conflict_group & structural2_normalized
        # If both names have words from the same conflict group, but different words
        # (e.g., one has "management", other has "holdings" from {management, holdings})
        if words1_in_group and words2_in_group and words1_in_group != words2_in_group:
            return True

    # If both have structural words remaining and they differ, it's a conflict
    if structural1_normalized and structural2_normalized:
        # Check if they have different structural words
        if structural1_normalized != structural2_normalized:
            # Different structural words suggest different entities
            return True

    return False
