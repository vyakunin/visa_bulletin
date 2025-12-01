"""VisaCutoffDate model - time series data for visa priority dates"""

from django.db import models
from .bulletin import Bulletin
from .enums.visa_category import VisaCategory
from .enums.action_type import ActionType
from .enums.country import Country


class VisaCutoffDate(models.Model):
    """
    Individual visa cutoff date entry - the core time series data
    
    Represents a single data point: for a specific bulletin, category,
    class, action type, and country, what is the priority date cutoff?
    
    Uses Django TextChoices for enum fields - readable strings in DB,
    type-safe enums in Python code.
    """
    
    bulletin = models.ForeignKey(
        Bulletin,
        on_delete=models.CASCADE,
        related_name='cutoff_dates'
    )
    
    visa_category = models.CharField(
        max_length=20,
        choices=VisaCategory.choices,
        help_text="Family-Sponsored or Employment-Based"
    )
    
    visa_class = models.CharField(
        max_length=50,
        help_text="F1, F2A, EB1, EB2, etc."
    )
    
    action_type = models.CharField(
        max_length=20,
        choices=ActionType.choices,
        help_text="Final Action or Dates for Filing"
    )
    
    country = models.CharField(
        max_length=50,
        choices=Country.choices,
        help_text="Country/region for chargeability"
    )
    
    cutoff_value = models.CharField(
        max_length=20,
        help_text="Raw value: date string, 'C', or 'U'"
    )
    
    cutoff_date = models.DateField(
        null=True,
        blank=True,
        help_text="Parsed date (NULL for C/U)"
    )
    
    is_current = models.BooleanField(
        default=False,
        help_text="True if cutoff is 'C' (Current)"
    )
    
    is_unavailable = models.BooleanField(
        default=False,
        help_text="True if cutoff is 'U' (Unavailable)"
    )
    
    class Meta:
        ordering = ['bulletin', 'visa_category', 'visa_class', 'country']
        unique_together = ['bulletin', 'visa_category', 'visa_class', 'action_type', 'country']
        db_table = 'visa_cutoff_date'
        indexes = [
            # For time series queries
            models.Index(fields=['visa_class', 'country', 'action_type', 'bulletin']),
            models.Index(fields=['visa_category', 'country']),
        ]
    
    def __str__(self):
        return f"{self.visa_class} {self.country} {self.action_type}: {self.cutoff_value}"
    
    def __repr__(self):
        return f"<VisaCutoffDate: {self.bulletin.publication_date} {self.visa_class} {self.country} = {self.cutoff_value}>"

