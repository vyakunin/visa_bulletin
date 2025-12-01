"""Visa category enum: Family-Sponsored vs Employment-Based"""

from enum import Enum


class VisaCategory(Enum):
    """Category of visa (Family or Employment)"""
    
    FAMILY_SPONSORED = "family_sponsored"
    EMPLOYMENT_BASED = "employment_based"
    
    @classmethod
    def from_table_title(cls, title: str):
        """Parse category from table title"""
        # Mapping from table titles to enum values
        mappings = {
            'family_sponsored_final_actions': cls.FAMILY_SPONSORED,
            'family_sponsored_dates_for_filing': cls.FAMILY_SPONSORED,
            'employment_based_final_action': cls.EMPLOYMENT_BASED,
            'employment_based_dates_for_filing': cls.EMPLOYMENT_BASED,
        }
        return mappings.get(title)
    
    def __str__(self):
        return self.value

