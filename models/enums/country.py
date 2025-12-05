"""Country/region enum for visa applicant chargeability"""

import re
from django.db import models


class Country(models.TextChoices):
    """
    Country or region for visa chargeability
    
    Uses Django TextChoices for database integration:
    - Stores readable string in DB ('china', 'india', 'all')
    - Access as enum in Python (Country.CHINA, Country.INDIA)
    - Query with: objects.filter(country=Country.CHINA)
    - DB shows readable values: SELECT * shows 'china', not '1'
    """
    
    ALL = "all", "Other Countries"
    CHINA = "china", "China (mainland born)"
    INDIA = "india", "India"
    MEXICO = "mexico", "Mexico"
    PHILIPPINES = "philippines", "Philippines"
    EL_SALVADOR_GUATEMALA_HONDURAS = "el_salvador_guatemala_honduras", "El Salvador/Guatemala/Honduras"
    
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

