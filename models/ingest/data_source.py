"""DataSource model - Registry of all data sources"""

from django.db import models
from .enums import DataDomain, SourceType, FormatVersion


class DataSource(models.Model):
    """Registry of known data sources (URLs, files, APIs)"""
    
    url = models.URLField(unique=True, help_text="Source URL")
    domain = models.CharField(
        max_length=50,
        choices=DataDomain.choices,
        help_text="Data source domain (organization/system)"
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        help_text="Type of data source within domain"
    )
    format_version = models.CharField(
        max_length=20,
        choices=FormatVersion.choices,
        default=FormatVersion.UNKNOWN,
        help_text="Schema format version (determines parser selection)"
    )
    discovered_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this source was first discovered"
    )
    downloaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When file was last downloaded"
    )
    local_file_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Cached local path if downloaded (for reference)"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible metadata storage"
    )
    
    class Meta:
        app_label = 'models'  # Explicitly set app_label for Django model resolution
        db_table = 'ingest_data_source'
        ordering = ['-discovered_at']
        indexes = [
            models.Index(fields=['domain', 'source_type']),
            models.Index(fields=['domain', 'format_version']),
        ]
    
    def __str__(self):
        return f"{self.get_domain_display()} {self.get_source_type_display()}: {self.url}"










