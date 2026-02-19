"""Case status enum for salary database"""

from django.db import models


class CaseStatus(models.IntegerChoices):
    """
    Case status from DOL disclosure data
    
    Uses IntegerChoices for performance (high-volume data):
    - Stores integer in DB (0=invalid, 1-4 for valid statuses)
    - Faster comparisons and joins
    - Smaller storage (4 bytes vs 10-50 bytes)
    - Value 0 is reserved for invalid/unknown (allows safe truthiness checks)
    """

    INVALID = 0, "Invalid/Unknown"
    CERTIFIED = 1, "Certified"
    DENIED = 2, "Denied"
    WITHDRAWN = 3, "Withdrawn"
    CERTIFIED_WITHDRAWN = 4, "Certified-Withdrawn"

    @classmethod
    def from_dol_value(cls, value: str):
        """Parse case status from DOL CSV value"""
        if not value:
            return None

        normalized = value.strip().upper().replace('-', '_').replace(' ', '_')
        mappings = {
            'CERTIFIED': cls.CERTIFIED,
            'DENIED': cls.DENIED,
            'WITHDRAWN': cls.WITHDRAWN,
            'CERTIFIED_WITHDRAWN': cls.CERTIFIED_WITHDRAWN,
            'CERTIFIED_EXPIRED': cls.CERTIFIED,  # Treat as certified
        }
        return mappings.get(normalized)

    @classmethod
    def from_string(cls, value: str):
        """Convert string value to enum (for migration compatibility)"""
        if not value:
            return None
        mappings = {
            'certified': cls.CERTIFIED,
            'denied': cls.DENIED,
            'withdrawn': cls.WITHDRAWN,
            'certified_withdrawn': cls.CERTIFIED_WITHDRAWN,
        }
        return mappings.get(value.lower())

