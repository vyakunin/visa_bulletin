"""Visa category enum: Family-Sponsored vs Employment-Based"""

from enum import Enum


class VisaCategory(Enum):
    """Category of visa (Family or Employment)"""
    
    FAMILY_SPONSORED = "family_sponsored"
    EMPLOYMENT_BASED = "employment_based"
    
    def __str__(self):
        return self.value

