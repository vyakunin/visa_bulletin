"""
Generic words used in employer name normalization.

These words are removed during normalization because they don't help distinguish
between companies (e.g., "CVS Corporation" vs "ICS Corporation" → "cvs" vs "ics").

This module provides the canonical definitions used across the codebase.
"""

# Generic words that don't help distinguish between companies
# These are removed to reduce false positives in similarity matching
# (e.g., "CVS Corporation" vs "ICS Corporation" → "cvs" vs "ics")
GENERIC_WORDS = {
    'corporation', 'corp', 'incorporated', 'inc',
    'llc', 'ltd', 'limited', 'lp', 'l.p.',
    'enterprises', 'enterprise',
    'technologies', 'technology', 'tech',
    'international', 'intl',
    'global',  # Similar to 'international' - geographic scope descriptor
    'industries', 'industry',
    'group', 'groups',
    'holdings', 'holding',
    'management',
    'partners', 'partner',
    'associates', 'associate',
    'consulting', 'consultants', 'consultant',
    'capital',
    'financial',
    'company', 'co',
    'the',
    'usa', 'us',
}

# Distinguishing generic words - these CAN help distinguish companies
# (e.g., "LOGIC SOLUTIONS" vs "LOGIC SERVICES" are different companies)
# These are kept when there's only 1 non-generic word to preserve distinctions
DISTINGUISHING_GENERIC_WORDS = {
    'services', 'service',
    'solutions', 'solution',
    'systems', 'system',
}

# Very generic words - names containing these words are too generic to match across states
# These are common entity types that could refer to many different organizations
# (e.g., "CHILDREN'S HOSPITAL" in Boston vs "CHILDREN'S HOSPITAL" in New Orleans are different hospitals)
# Note: Only singular forms are listed - normalization handles plural-to-singular conversion
# (e.g., "schools" -> "school", "centers" -> "center")
VERY_GENERIC_WORDS = {
    'hospital',
    'school',
    'center',
    'clinic',
    'university',
    'college',
    'foundation',
    'association',
    'society',
    'church',
    'temple',
    'mosque',
    'synagogue',
}

# All generic words (for filtering/exclusion purposes)
ALL_GENERIC_WORDS = GENERIC_WORDS | DISTINGUISHING_GENERIC_WORDS

