"""Family-sponsored preference categories"""

from django.db import models


class FamilyPreference(models.TextChoices):
    """Family-sponsored visa preference categories"""
    
    F1 = "F1", "F1: Unmarried Sons/Daughters of U.S. Citizens"
    F2A = "F2A", "F2A: Spouses/Children of Permanent Residents"
    F2B = "F2B", "F2B: Unmarried Sons/Daughters (21+) of Permanent Residents"
    F3 = "F3", "F3: Married Sons/Daughters of U.S. Citizens"
    F4 = "F4", "F4: Brothers/Sisters of Adult U.S. Citizens"
    
    @classmethod
    def _get_legacy_mappings(cls) -> dict[str, str]:
        """
        Legacy visa class names from old bulletins (2001-2015).
        Centralized mapping using enum values to avoid hardcoded strings.
        
        Returns:
            Dictionary mapping old format to enum values
        """
        return {
            '1st': cls.F1.value,
            '1 st': cls.F1.value,
            '2A': cls.F2A.value,
            '2 A': cls.F2A.value,
            '2B': cls.F2B.value,
            '2 B': cls.F2B.value,
            '3rd': cls.F3.value,
            '3 rd': cls.F3.value,
            '4th': cls.F4.value,
            '4 th': cls.F4.value,
        }
    
    @classmethod
    def normalize_legacy_name(cls, visa_class: str) -> str:
        """
        Normalize legacy visa class names to modern format
        
        Args:
            visa_class: Raw visa class from old bulletin (e.g., "1st", "4th")
            
        Returns:
            Modern format (e.g., "F1", "F4") or original if no mapping exists
            
        Example:
            >>> FamilyPreference.normalize_legacy_name("4th")
            "F4"
            >>> FamilyPreference.normalize_legacy_name("F4")
            "F4"
        """
        return cls._get_legacy_mappings().get(visa_class, visa_class)

