"""Country/region enum for visa applicant chargeability"""

from enum import Enum


class Country(Enum):
    """Country or region for visa chargeability"""
    
    ALL = "all"
    CHINA = "china"
    INDIA = "india"
    MEXICO = "mexico"
    PHILIPPINES = "philippines"
    EL_SALVADOR_GUATEMALA_HONDURAS = "el_salvador_guatemala_honduras"
    
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
    
    def __str__(self):
        return self.value

