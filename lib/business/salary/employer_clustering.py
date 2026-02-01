"""Employer clustering logic for grouping similar employers"""

import difflib
import re
from typing import Optional
from models.salary import Employer
from lib.business import clustering_engine
from lib.business.salary.employer_config import EmployerClusteringConfig

# Create config instance for use in public API functions
_config = EmployerClusteringConfig()


def _get_fuzzy_bucket_candidates(normalized_name: str) -> set[str]:
    """
    Generate multiple bucket candidates for fuzzy matching.
    
    This helps catch typos and variations that normalize to different buckets.
    Returns a set of bucket keys that should be checked for potential matches.
    
    Strategy:
    1. Exact normalized name (primary bucket)
    2. Word initials (catches typos like "CONNEC" vs "Connect")
    3. First 3 chars + last 3 chars (catches variations in middle)
    
    Returns: Set of bucket candidate strings
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


def _extract_structural_words(name: str) -> set[str]:
    """
    Extract structural/generic words that could distinguish companies.
    
    These are words that, if different between two names, suggest different entities.
    
    Note: This includes GENERIC_WORDS plus additional distinguishing words (geographic,
    distinguishing generic words, etc.) that can help identify different companies.
    """
    import re
    from lib.business.salary.generic_words import (
        GENERIC_WORDS,
        DISTINGUISHING_GENERIC_WORDS,
    )
    
    # Words that distinguish company types/structures
    # Includes GENERIC_WORDS (which can distinguish when different) plus additional words
    STRUCTURAL_WORDS = (
        GENERIC_WORDS | DISTINGUISHING_GENERIC_WORDS | {
            'north', 'south', 'east', 'west',  # Geographic qualifiers can distinguish
            'america', 'americas',  # "North America" vs other regions
        }
    )
    
    # Normalize and extract words
    normalized = name.lower()
    # Remove punctuation, keep words
    words = set(re.findall(r'\b\w+\b', normalized))
    
    # Return intersection with structural words
    return words & STRUCTURAL_WORDS


def _has_conflicting_structural_words(name1: str, name2: str) -> bool:
    """
    Check if two names have conflicting structural words that suggest different entities.
    
    Examples:
    - "Macro Consultants" vs "Macro International" → True (Consultants ≠ International)
    - "SYNAPSE GROUP" vs "SYNAPSE TECHNOLOGIES" → True (Group ≠ Technologies)
    - "Edgesoft Corp" vs "Edgesoft Inc" → False (Corp/Inc are equivalent corporate suffixes)
    """
    structural1 = _extract_structural_words(name1)
    structural2 = _extract_structural_words(name2)
    
    # Equivalent corporate suffixes - these don't conflict (all mean "company")
    # Use subset of GENERIC_WORDS for corporate suffixes
    from lib.business.salary.generic_words import GENERIC_WORDS
    equivalent_suffixes = {
        'corporation', 'corp', 'incorporated', 'inc', 'llc', 'limited', 'ltd', 'company', 'co'
    }  # Subset of GENERIC_WORDS - corporate entity types
    
    # Equivalent word variants (singular/plural, verb forms, etc.)
    # PRECISION FIX: Reduced equivalent variants - many of these should actually conflict
    # Only keep truly equivalent variants (singular/plural, verb forms of same word)
    equivalent_variants = [
        {'consultants', 'consulting', 'consultant'},  # Same concept: consulting business
        {'technologies', 'technology', 'tech'},  # Same concept: tech company
        {'industries', 'industry'},  # Same concept: industry
        {'enterprises', 'enterprise'},  # Same concept: enterprise
        {'holdings', 'holding'},  # Same concept: holding company
        {'groups', 'group'},  # Same concept: group
        {'solutions', 'solution'},  # Same concept: solution provider
        {'services', 'service'},  # Same concept: service provider
        {'systems', 'system'},  # Same concept: system provider
        {'america', 'americas'},  # Same concept: geographic region
        {'us', 'usa'},  # Same concept: United States (BBC News US vs BBC News USA)
        {'global', 'international'},  # Same concept: worldwide operations
    ]
    
    # PRECISION FIX: Add conflicting word pairs that indicate different companies
    # These words should NOT be treated as equivalent - they distinguish companies
    # Format: each set contains words that conflict with each other
    conflicting_word_groups = [
        # Business type conflicts - these indicate different company types
        {'management', 'holdings'},  # Management company vs holding company
        {'management', 'corporation'},  # Management vs corporation (when both present)
        {'technologies', 'consulting'},  # Tech company vs consulting firm
        {'technologies', 'partners'},  # Tech company vs partnership
        {'consulting', 'partners'},  # Consulting vs partnership
        {'management', 'partners'},  # Management vs partnership
        # Industry/domain conflicts
        {'capital', 'holdings'},  # Capital management vs holdings
        {'capital', 'partners'},  # Capital vs partnership
    ]
    
    # Normalize: replace equivalent words with a canonical form
    def normalize_group(word_set: set[str], equiv_groups: list[set[str]]) -> set[str]:
        """Replace equivalent words with first item in group"""
        normalized = set(word_set)
        for equiv_group in equiv_groups:
            if normalized & equiv_group:
                # Replace all variants with canonical (first one, sorted for determinism)
                canonical = sorted(equiv_group)[0]
                normalized = normalized - equiv_group
                normalized.add(canonical)
        return normalized
    
    # Remove equivalent suffixes (they don't distinguish companies)
    structural1_no_suffix = structural1 - equivalent_suffixes
    structural2_no_suffix = structural2 - equivalent_suffixes
    
    # Normalize equivalent variants
    structural1_normalized = normalize_group(structural1_no_suffix, equivalent_variants)
    structural2_normalized = normalize_group(structural2_no_suffix, equivalent_variants)
    
    # PRECISION FIX: Check for conflicting word groups
    # If one name has a word from a conflict group and the other name has a different word
    # from the same conflict group, it's a conflict
    for conflict_group in conflicting_word_groups:
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


def _check_hyphen_variation(
    employer1: Employer, employer2: Employer, norm1: str, norm2: str
) -> tuple[bool, float, str] | None:
    """
    Check if names are hyphen variations (e.g., "HI-TEK" vs "HITEK").
    
    Returns: (is_match, confidence, reason) if hyphen variation detected, None otherwise
    """
    name1_has_hyphen = '-' in employer1.name
    name2_has_hyphen = '-' in employer2.name
    is_hyphen_variation = (name1_has_hyphen and not name2_has_hyphen) or (name2_has_hyphen and not name1_has_hyphen)
    
    if not (is_hyphen_variation and norm1 == norm2):
        return None
    
    from lib.utils.location_utils import normalize_state_code
    state1 = normalize_state_code(employer1.state)
    state2 = normalize_state_code(employer2.state)
    city1 = (employer1.city or '').upper().strip()
    city2 = (employer2.city or '').upper().strip()
    
    if state1 and state2 and state1 == state2:
        if city1 and city2 and city1 == city2:
            return (True, 0.95, "Hyphen variation with exact location match")
        else:
            return (True, 0.92, "Hyphen variation with same state (city differs)")
    elif not state1 or not state2:
        if city1 and city2 and city1 == city2:
            return (True, 0.95, "Hyphen variation with same city (state missing)")
        else:
            return (False, 0.0, "Hyphen variation with different/missing locations - likely different companies")
    else:
        return (False, 0.0, "Hyphen variation with different states - likely different companies")


def _check_exact_match(
    employer1: Employer, employer2: Employer, norm1: str, norm2: str
) -> tuple[bool, float, str] | None:
    """
    Check if names match exactly after normalization.
    
    Returns: (is_match, confidence, reason) if exact match, None otherwise
    """
    if norm1 != norm2:
        return None
    
    from lib.business.salary.generic_words import VERY_GENERIC_WORDS
    from lib.utils.location_utils import normalize_state_code
    
    words1 = norm1.split()
    words2 = norm2.split()
    
    is_very_generic = (
        any(word in VERY_GENERIC_WORDS for word in words1) or
        any(word in VERY_GENERIC_WORDS for word in words2)
    )
    
    is_single_word_generic = (
        len(words1) == 1 and len(words2) == 1 and
        (words1[0] in VERY_GENERIC_WORDS or words2[0] in VERY_GENERIC_WORDS)
    )
    
    if not (is_very_generic or is_single_word_generic):
        return (True, 1.0, "Exact normalized name match")
    
    state1 = normalize_state_code(employer1.state)
    state2 = normalize_state_code(employer2.state)
    city1 = (employer1.city or '').upper().strip()
    city2 = (employer2.city or '').upper().strip()
    
    if state1 and state2 and state1 == state2:
        return (True, 1.0, "Exact normalized name match (same state)")
    elif not state1 or not state2:
        if city1 and city2 and city1 == city2:
            return (True, 0.90, "Exact normalized name match (same city, state missing - lower confidence)")
        elif city1 and city2:
            return (True, 0.85, "Exact normalized name match (cities differ, state missing - lower confidence)")
        else:
            return (True, 0.80, "Exact normalized name match (location data missing - very low confidence)")
    else:
        return (False, 0.0, f"Exact normalized name match but different states ({state1} vs {state2}) - very generic name requires same state")


def _check_substring_match(
    employer1: Employer, employer2: Employer, norm1: str, norm2: str
) -> tuple[bool, float, str] | None:
    """
    Check if one name is a substring of another after normalization.
    
    Returns: (is_match, confidence, reason) if substring match, None otherwise
    """
    if norm1 not in norm2 and norm2 not in norm1:
        return None
    
    from lib.utils.location_utils import GEOGRAPHIC_QUALIFIERS
    
    name1_lower = employer1.name.lower()
    name2_lower = employer2.name.lower()
    qualifiers1 = {q for q in GEOGRAPHIC_QUALIFIERS if q in name1_lower}
    qualifiers2 = {q for q in GEOGRAPHIC_QUALIFIERS if q in name2_lower}
    
    if (qualifiers1 and not qualifiers2) or (qualifiers2 and not qualifiers1):
        return (False, 0.0, "Substring match rejected: geographic qualifiers differ (indicates different entities)")
    if qualifiers1 and qualifiers2 and qualifiers1 != qualifiers2:
        return (False, 0.0, "Substring match rejected: different geographic qualifiers (indicates different entities)")
    
    has_conflict = _has_conflicting_structural_words(employer1.name, employer2.name)
    if has_conflict:
        return (False, 0.0, "Substring match rejected: conflicting structural words indicate different entities")
    
    longer = norm1 if len(norm1) > len(norm2) else norm2
    shorter = norm1 if len(norm1) <= len(norm2) else norm2
    
    if longer.startswith(shorter):
        diff = longer[len(shorter):].strip()
        from lib.business.salary.generic_words import GENERIC_WORDS
        diff_words = set(diff.split())
        
        if diff_words.issubset(GENERIC_WORDS) or not diff_words:
            return (True, 0.95, f"Substring match: '{shorter}' in '{longer}' (difference: generic words only)")
        
        # Check if difference is very small (typo/abbreviation like "connec" vs "connect")
        # Small differences (1-3 chars) are likely typos, not different entities
        if len(diff) <= 3:
            return (True, 0.90, f"Substring match with small difference ({len(diff)} chars)")
        
        # Difference contains significant non-generic words - these likely indicate different entities
        # (e.g., "bbc" vs "bbc innovation" - "innovation" is significant)
        return (False, 0.0, f"Substring match rejected: difference contains significant words: {' '.join(diff_words)}")
    
    # If not a simple prefix/suffix match, reject (e.g., "bbc" in middle of "innovation bbc corporation")
    return (False, 0.0, "Substring match rejected: not a simple prefix/suffix match")


def _check_similarity_match(
    employer1: Employer, employer2: Employer, norm1: str, norm2: str
) -> tuple[bool, float, str] | None:
    """
    Check if names match based on similarity score.
    
    Returns: (is_match, confidence, reason) if similarity threshold met, None otherwise
    """
    similarity = difflib.SequenceMatcher(None, norm1, norm2).ratio()
    
    has_conflict = _has_conflicting_structural_words(employer1.name, employer2.name)
    if has_conflict and similarity < 0.95:
        return (False, 0.0, "Conflicting structural words indicate different entities")
    
    if similarity >= 0.99:
        return (True, similarity, f"Very high similarity ({similarity:.2f})")
    
    if similarity >= 0.95:
        return (True, similarity, f"High similarity ({similarity:.2f})")
    
    return None


def match_employers(
    employer1: Employer, 
    employer2: Employer,
    norm1: Optional[str] = None,
    norm2: Optional[str] = None
) -> tuple[bool, float, str]:
    """
    Hybrid matching algorithm: rule-based checks first, then similarity-based fallback.
    
    PERFORMANCE WARNING: This function is called in the innermost loop of clustering (Phase 2).
    It processes ~400k pairs in a full run.
    
    Optimization:
    - Pass `norm1` and `norm2` arguments if already computed to avoid redundant re-normalization.
    - Re-normalization involves regex and string operations which add up over 400k calls.
    
    Flow:
    1. Hyphen variation check
    2. Exact normalized name match
    3. Substring match
    4. Similarity-based fallback
    
    Returns: (is_match, confidence, reason)
    - is_match: True if algorithm indicates same employer
    - confidence: 0.0-1.0 (1.0 = high confidence)
    - reason: Explanation of match
    """
    if norm1 is None:
        norm1 = Employer.normalize_name(employer1.name)
    if norm2 is None:
        norm2 = Employer.normalize_name(employer2.name)

    checks = (
        _check_hyphen_variation,
        _check_exact_match,
        _check_substring_match,
        _check_similarity_match,
    )
    for check in checks:
        result = check(employer1, employer2, norm1, norm2)
        if result is not None:
            return result

    return (False, 0.0, "")


def fuzzy_match(employer1: Employer, employer2: Employer) -> tuple[float, str]:
    """
    Fuzzy string matching for ambiguous cases
    
    Returns: (similarity_score, reason)
    - similarity_score: 0.0-1.0 (higher = more similar)
    - reason: Explanation of similarity
    """
    # Re-normalize from original names to ensure we use latest normalization logic
    # (with generic word filtering). Don't use stored name_normalized which may be outdated.
    norm1 = Employer.normalize_name(employer1.name)
    norm2 = Employer.normalize_name(employer2.name)
    
    # Generic words are already removed during normalization, so we can use normalized names directly
    similarity = difflib.SequenceMatcher(None, norm1, norm2).ratio()
    
    reason = f"Fuzzy match similarity: {similarity:.2f}"
    if similarity >= 0.8:
        reason += " (high similarity)"
    elif similarity >= 0.6:
        reason += " (moderate similarity)"
    else:
        reason += " (low similarity)"
    
    return (similarity, reason)


def should_auto_cluster(
    employer1: Employer, 
    employer2: Employer, 
    threshold: float = 0.95,
    norm1: Optional[str] = None,
    norm2: Optional[str] = None
) -> tuple[bool, float, str]:
    """
    Determine if two employers should be auto-clustered
    
    Args:
        employer1: First employer
        employer2: Second employer
        threshold: Confidence threshold for auto-clustering (0.0-1.0)
        norm1: Optional pre-computed normalized name for employer1
        norm2: Optional pre-computed normalized name for employer2
    
    Returns: (should_cluster, confidence, reason)
    """
    is_match, confidence, reason = match_employers(employer1, employer2, norm1, norm2)
    if not is_match:
        return (False, confidence, reason)
    return (confidence >= threshold, confidence, reason)


def assign_to_cluster(employer: Employer, auto_approve_threshold: float = 0.95) -> Optional['EmployerCluster']:
    """
    Find existing cluster or create new one for an employer
    
    Searches for existing clusters with similar normalized names.
    If high-confidence match found → assign to existing cluster
    If ambiguous → create new cluster, add to review queue
    If no match → create new cluster
    
    Returns: EmployerCluster instance
    """
    # Delegate to generic framework
    return clustering_engine.assign_to_cluster(employer, _config, auto_approve_threshold)

