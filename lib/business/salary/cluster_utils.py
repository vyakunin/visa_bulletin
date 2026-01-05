"""Utilities for employer clustering"""


def normalize_canonical_name(canonical_name: str) -> str:
    """
    Normalize canonical name for case-insensitive lookups.
    
    This ensures that "BBC RETAIL AND INTERNET LLC" and "BBC Retail and Internet LLC"
    are treated as the same canonical name, preventing duplicate clusters.
    
    Args:
        canonical_name: The canonical employer name
        
    Returns:
        Normalized canonical name (lowercase) for use as cache/lookup key
        
    Examples:
        >>> normalize_canonical_name("BBC RETAIL AND INTERNET LLC")
        'bbc retail and internet llc'
        >>> normalize_canonical_name("BBC Retail and Internet LLC")
        'bbc retail and internet llc'
        >>> normalize_canonical_name("Google Inc")
        'google inc'
    """
    return canonical_name.lower()

