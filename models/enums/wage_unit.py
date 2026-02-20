"""Wage unit enum for salary database"""

from django.db import models


class WageUnit(models.TextChoices):
    """
    Wage unit of pay from DOL disclosure data
    """

    YEAR = "year", "Per Year"
    MONTH = "month", "Per Month"
    BI_WEEKLY = "bi_weekly", "Bi-Weekly"
    WEEK = "week", "Per Week"
    HOUR = "hour", "Per Hour"

    @classmethod
    def from_dol_value(cls, value: str):
        """Parse wage unit from DOL CSV value"""
        if not value:
            return None

        normalized = value.strip().upper()
        mappings = {
            "YEAR": cls.YEAR,
            "YEARLY": cls.YEAR,
            "YR": cls.YEAR,
            "MONTH": cls.MONTH,
            "MONTHLY": cls.MONTH,
            "MTH": cls.MONTH,
            "BI-WEEKLY": cls.BI_WEEKLY,
            "BIWEEKLY": cls.BI_WEEKLY,
            "BW": cls.BI_WEEKLY,
            "WEEK": cls.WEEK,
            "WEEKLY": cls.WEEK,
            "WK": cls.WEEK,
            "HOUR": cls.HOUR,
            "HOURLY": cls.HOUR,
            "HR": cls.HOUR,  # FIX: Handle 'HR' abbreviation (found in PERM_FY2008.xlsx)
        }
        return mappings.get(normalized)
