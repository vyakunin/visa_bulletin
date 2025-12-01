"""Action type enum: Final Action vs Filing"""

from enum import Enum


class ActionType(Enum):
    """Type of action for visa processing"""
    
    FINAL_ACTION = "final_action"
    FILING = "filing"
    
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
    
    def __str__(self):
        return self.value

