"""Country/region enum for visa applicant chargeability"""

import re
from django.db import models


class Country(models.IntegerChoices):
    """
    Country or region for visa chargeability
    
    Uses IntegerChoices for performance (high-volume data):
    - Stores integer in DB (0=invalid, 1-6 for valid countries)
    - Access as enum in Python (Country.CHINA, Country.INDIA)
    - Query with: objects.filter(country=Country.CHINA)
    - Faster comparisons and joins
    - Smaller storage (4 bytes vs 10-50 bytes)
    - Value 0 is reserved for invalid/unknown (allows safe truthiness checks)
    """
    
    INVALID = 0, "Invalid/Unknown"
    ALL = 1, "Other Countries"
    CHINA = 2, "China (mainland born)"
    INDIA = 3, "India"
    MEXICO = 4, "Mexico"
    PHILIPPINES = 5, "Philippines"
    EL_SALVADOR_GUATEMALA_HONDURAS = 6, "El Salvador/Guatemala/Honduras"
    
    @classmethod
    def from_header(cls, header: str):
        """
        Parse country from table header string using robust pattern matching
        
        Uses regex patterns to handle variations in spacing, punctuation, and formatting.
        Falls back to exact matching for edge cases.
        """
        # Normalize whitespace and special characters
        normalized = re.sub(r'[\s\xa0\n]+', ' ', header).strip().upper()
        
        # Pattern-based matching (order matters - most specific first)
        patterns = [
            (r'CHINA.*MAINLAND', cls.CHINA),
            (r'^INDIA$', cls.INDIA),
            (r'^MEXICO$', cls.MEXICO),
            (r'^PHILIPPINES$', cls.PHILIPPINES),
            (r'EL SALVADOR.*GUATEMALA.*HONDURAS', cls.EL_SALVADOR_GUATEMALA_HONDURAS),
            (r'ALL.*CHARGEABILITY.*EXCEPT', cls.ALL),
        ]
        
        for pattern, country in patterns:
            if re.search(pattern, normalized):
                return country
        
        # Fallback: exact matching for edge cases
        exact_mappings = {
            'ALL CHARGEABILITY AREAS EXCEPT THOSE LISTED': cls.ALL,
            'ALL AREAS': cls.ALL,
        }
        
        return exact_mappings.get(normalized)

    @classmethod
    def slug_for_value(cls, value: int) -> str | None:
        """Return URL slug for a country value, or None for invalid."""
        return _VALUE_TO_SLUG.get(value)

    @classmethod
    def from_string(cls, value: str):
        """Convert string value to enum (for migration compatibility and URL slug parsing)."""
        if not value:
            return None
        mappings = {
            'all': cls.ALL,
            'china': cls.CHINA,
            'india': cls.INDIA,
            'mexico': cls.MEXICO,
            'philippines': cls.PHILIPPINES,
            'el_salvador_guatemala_honduras': cls.EL_SALVADOR_GUATEMALA_HONDURAS,
        }
        return mappings.get(value.lower())


# URL slug per country value (outside class so IntegerChoices doesn't treat the dict as a member)
_VALUE_TO_SLUG = {
    1: "all",
    2: "china",
    3: "india",
    4: "mexico",
    5: "philippines",
    6: "el_salvador_guatemala_honduras",
}

