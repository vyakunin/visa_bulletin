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
    
    def __str__(self):
        return self.value

