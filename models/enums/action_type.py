"""Action type enum: Final Action vs Filing"""

from django.db import models


class ActionType(models.TextChoices):
    """
    Type of action for visa processing
    
    Uses Django TextChoices for database integration:
    - Stores readable string in DB ('final_action', 'filing')
    - Access as enum in Python (ActionType.FINAL_ACTION)
    - Query with: objects.filter(action_type=ActionType.FINAL_ACTION)
    """
    
    FINAL_ACTION = "final_action", "Final Action"
    FILING = "filing", "Dates for Filing"
    
    @classmethod
    def from_table_title(cls, title: str):
        """Parse action type from table title"""
        # Mapping from table titles to enum values
        mappings = {
            'family_sponsored_final_actions': cls.FINAL_ACTION,
            'family_sponsored_dates_for_filing': cls.FILING,
            'employment_based_final_action': cls.FINAL_ACTION,
            'employment_based_dates_for_filing': cls.FILING,
        }
        return mappings.get(title)

