"""Employment-based preference categories"""

from enum import Enum


class EmploymentPreference(Enum):
    """Employment-based visa preference categories"""
    
    EB1 = "1st"                              # Priority Workers
    EB2 = "2nd"                              # Professionals with Advanced Degrees
    EB3 = "3rd"                              # Skilled Workers, Professionals
    OTHER_WORKERS = "Other Workers"          # Other Workers (EB-3 subcategory)
    EB4 = "4th"                              # Special Immigrants
    RELIGIOUS_WORKERS = "Certain Religious Workers"  # Religious Workers (EB-4 subcategory)
    EB5_UNRESERVED = "5th Unreserved (including C5, T5, I5, R5)"
    EB5_RURAL = "5th Set Aside: Rural (20%)"
    EB5_HIGH_UNEMPLOYMENT = "5th Set Aside: High Unemployment (10%)"
    EB5_INFRASTRUCTURE = "5th Set Aside: Infrastructure (2%)"
    
    def __str__(self):
        return self.value

