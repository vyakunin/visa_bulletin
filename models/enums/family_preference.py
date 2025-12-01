"""Family-sponsored preference categories"""

from enum import Enum


class FamilyPreference(Enum):
    """Family-sponsored visa preference categories"""
    
    F1 = "F1"    # Unmarried Sons and Daughters of U.S. Citizens
    F2A = "F2A"  # Spouses and Children of Permanent Residents
    F2B = "F2B"  # Unmarried Sons and Daughters (21+) of Permanent Residents
    F3 = "F3"    # Married Sons and Daughters of U.S. Citizens
    F4 = "F4"    # Brothers and Sisters of Adult U.S. Citizens
    
    def __str__(self):
        return self.value

