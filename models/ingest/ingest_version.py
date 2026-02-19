"""IngestVersion model - For rollback capability"""

from django.db import models

from .ingest_run import IngestRun


class IngestVersion(models.Model):
    """Version marker for rollback - links records to their ingest run"""

    run = models.OneToOneField(
        IngestRun,
        on_delete=models.CASCADE,
        related_name='version',
        help_text="Ingest run this version represents"
    )
    version_tag = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Human-readable version tag (e.g., 'dol_lca_2024q4_v1')"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this version is currently active (serving queries)"
    )
    supersedes = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='superseded_by',
        help_text="Previous version this supersedes (for rollback chain)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this version was created"
    )

    class Meta:
        app_label = 'models'  # Explicitly set app_label for Django model resolution
        db_table = 'ingest_version'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'version_tag']),
        ]

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"Version {self.version_tag} ({status})"










