"""Bulletin model - represents a monthly visa bulletin publication"""

from django.db import models


class Bulletin(models.Model):
    """
    Monthly visa bulletin publication
    
    Each bulletin contains multiple visa cutoff dates for different
    categories, classes, action types, and countries.
    """
    
    publication_date = models.DateField(
        unique=True,
        help_text="First day of the publication month (e.g., 2025-12-01)"
    )
    
    fetched_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this bulletin was fetched and saved"
    )
    
    class Meta:
        ordering = ['-publication_date']
        db_table = 'bulletin'
    
    def __str__(self):
        return f"Bulletin({self.publication_date.strftime('%B %Y')})"
    
    def __repr__(self):
        return f"<Bulletin: {self.publication_date}>"

