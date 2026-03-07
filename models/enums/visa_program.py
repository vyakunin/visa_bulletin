"""
Visa program enum for salary database (H-1B LCA, PERM, etc.)

This file now imports from separate enum modules for better organization.
See:
- models/enums/wage_unit.py - WageUnit enum
- models/enums/case_status.py - CaseStatus enum
"""

from django.db import models

from models.enums.case_status import CaseStatus  # noqa: F401

# Import other enums for backward compatibility
from models.enums.wage_unit import WageUnit  # noqa: F401


# Compact labels for UI (table headers, charts). Keyed by enum value.
_VISA_PROGRAM_SHORT_LABELS = {
    1: "H-1B",
    2: "H-1B1",
    3: "E-3",
    4: "PERM",
}


class VisaProgram(models.IntegerChoices):
    """
    Visa program type for salary records

    Uses IntegerChoices for performance (high-volume data):
    - Stores integer in DB (0=invalid, 1-4 for valid programs)
    - Access as enum in Python (VisaProgram.H1B, VisaProgram.PERM)
    - Faster comparisons and joins
    - Smaller storage (4 bytes vs 10-50 bytes)
    - Value 0 is reserved for invalid/unknown (allows safe truthiness checks)
    """

    INVALID = 0, "Invalid/Unknown"
    H1B = 1, "H-1B (Specialty Occupation)"
    H1B1 = 2, "H-1B1 (Chile/Singapore)"
    E3 = 3, "E-3 (Australia)"
    PERM = 4, "PERM (Permanent Labor Certification)"

    @classmethod
    def short_display(cls, value: int | None) -> str:
        """Return compact label for UI (e.g. 'H-1B', 'PERM'). Unknown/invalid -> 'Other'."""
        if value is None:
            return "Other"
        try:
            return _VISA_PROGRAM_SHORT_LABELS.get(int(value), "Other")
        except (TypeError, ValueError):
            return "Other"

    @classmethod
    def from_string(cls, value: str):
        """Convert string value to enum (for migration compatibility)"""
        if not value:
            return None
        mappings = {
            "h1b": cls.H1B,
            "h1b1": cls.H1B1,
            "e3": cls.E3,
            "perm": cls.PERM,
        }
        return mappings.get(value.lower())
