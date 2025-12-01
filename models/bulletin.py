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
    
    url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL to the official bulletin on travel.state.gov"
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
    
    def get_bulletin_url(self) -> str:
        """
        Get or construct the official bulletin URL
        
        Returns the stored URL if available, otherwise constructs it from
        the publication date using the standard travel.state.gov format.
        
        Example:
            >>> bulletin = Bulletin(publication_date=date(2025, 12, 1))
            >>> bulletin.get_bulletin_url()
            'https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/2026/visa-bulletin-for-december-2025.html'
        """
        if self.url:
            return self.url
        
        # Construct URL from publication date
        # Format: visa-bulletin-for-{month}-{year}.html
        month_name = self.publication_date.strftime('%B').lower()  # e.g., "december"
        year = self.publication_date.year
        
        # Note: The URL uses the fiscal year in the path (typically year+1 for Oct-Dec)
        fiscal_year = year + 1 if self.publication_date.month >= 10 else year
        
        return f"https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/{fiscal_year}/visa-bulletin-for-{month_name}-{year}.html"

