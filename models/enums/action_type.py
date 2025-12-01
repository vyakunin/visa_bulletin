"""Action type enum: Final Action vs Filing"""

from enum import Enum


class ActionType(Enum):
    """Type of action for visa processing"""
    
    FINAL_ACTION = "final_action"
    FILING = "filing"
    
    def __str__(self):
        return self.value

