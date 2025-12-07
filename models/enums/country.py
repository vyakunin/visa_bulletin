"""Country/region enum for visa applicant chargeability"""

import re
from django.db import models


class Country(models.IntegerChoices):
    """
    Country or region for visa chargeability
    
    Uses IntegerChoices for performance (high-volume data):
    - Stores integer in DB (0, 1, 2, 3, 4, 5)
    - Access as enum in Python (Country.CHINA, Country.INDIA)
    - Query with: objects.filter(country=Country.CHINA)
    - Faster comparisons and joins
    - Smaller storage (4 bytes vs 10-50 bytes)
    """
    
    ALL = 0, "Other Countries"
    CHINA = 1, "China (mainland born)"
    INDIA = 2, "India"
    MEXICO = 3, "Mexico"
    PHILIPPINES = 4, "Philippines"
    EL_SALVADOR_GUATEMALA_HONDURAS = 5, "El Salvador/Guatemala/Honduras"
    
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
    def from_string(cls, value: str):
        """Convert string value to enum (for migration compatibility)"""
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

