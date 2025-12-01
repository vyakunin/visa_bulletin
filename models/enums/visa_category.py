"""Visa category enum: Family-Sponsored vs Employment-Based"""

from django.db import models


class VisaCategory(models.TextChoices):
    """
    Category of visa (Family or Employment)
    
    Uses Django TextChoices for database integration:
    - Stores readable string in DB ('family_sponsored')
    - Access as enum in Python (VisaCategory.FAMILY_SPONSORED)
    - Query with: objects.filter(visa_category=VisaCategory.FAMILY_SPONSORED)
    """
    
    FAMILY_SPONSORED = "family_sponsored", "Family-Sponsored"
    EMPLOYMENT_BASED = "employment_based", "Employment-Based"
    
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

