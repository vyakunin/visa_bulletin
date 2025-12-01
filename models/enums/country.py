"""Country/region enum for visa applicant chargeability"""

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
    
    ALL = "all", "All Chargeability Areas"
    CHINA = "china", "China (mainland born)"
    INDIA = "india", "India"
    MEXICO = "mexico", "Mexico"
    PHILIPPINES = "philippines", "Philippines"
    EL_SALVADOR_GUATEMALA_HONDURAS = "el_salvador_guatemala_honduras", "El Salvador/Guatemala/Honduras"
    
    @classmethod
    def from_header(cls, header: str):
        """Parse country from table header string"""
        # Normalize whitespace
        normalized = ' '.join(header.split())
        
        # Mapping from table headers to enum values
        mappings = {
            'All Chargeability Areas Except Those Listed': cls.ALL,
            'All Chargeability\xa0Areas Except Those Listed': cls.ALL,  # Non-breaking space
            'CHINA-mainland born': cls.CHINA,
            'CHINA- mainland born': cls.CHINA,
            'CHINA-mainland\xa0born': cls.CHINA,
            'CHINA- mainland\xa0born': cls.CHINA,
            'INDIA': cls.INDIA,
            'MEXICO': cls.MEXICO,
            'PHILIPPINES': cls.PHILIPPINES,
            'EL SALVADOR GUATEMALA HONDURAS': cls.EL_SALVADOR_GUATEMALA_HONDURAS,
            'EL SALVADOR\nGUATEMALA\nHONDURAS': cls.EL_SALVADOR_GUATEMALA_HONDURAS,
        }
        return mappings.get(normalized)

