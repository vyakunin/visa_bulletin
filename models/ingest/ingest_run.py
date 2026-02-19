"""IngestRun model - Tracks each pipeline execution"""

from django.db import models
from django.utils import timezone

from .data_source import DataSource
from .enums import IngestStage, IngestStatus


class IngestRun(models.Model):
    """
    Single execution of the complete ingest pipeline (all stages).
    
    Each IngestRun represents one full pass through: download → parse → transform → load.
    The pipeline can be interrupted and resumed at any stage via checkpoints.
    """

    source = models.ForeignKey(
        DataSource,
        on_delete=models.CASCADE,
        related_name='runs',
        help_text="Data source being ingested"
    )
    status = models.IntegerField(
        choices=IngestStatus.choices,
        default=IngestStatus.PENDING,
        help_text="Overall status of the ingest run"
    )
    stage = models.IntegerField(
        choices=IngestStage.choices,
        default=IngestStage.PENDING,
        help_text="Current pipeline stage"
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the ingest run started"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the ingest run completed"
    )

    # Progress tracking
    records_processed = models.IntegerField(
        default=0,
        help_text="Total records processed across all stages"
    )
    records_created = models.IntegerField(
        default=0,
        help_text="Records successfully created in database"
    )
    records_updated = models.IntegerField(
        default=0,
        help_text="Records updated (if applicable)"
    )
    records_failed = models.IntegerField(
        default=0,
        help_text="Records that failed to process"
    )
    records_skipped = models.IntegerField(
        default=0,
        help_text="Records skipped (duplicates, etc.)"
    )

    # Resumption support
    checkpoint = models.JSONField(
        default=dict,
        blank=True,
        help_text="Checkpoint data for resumption: {stage, last_row, batch, filepath, ...}"
    )

    # Error tracking
    error_message = models.TextField(
        blank=True,
        help_text="Error message if ingest failed"
    )
    error_traceback = models.TextField(
        blank=True,
        help_text="Full traceback if ingest failed"
    )

    class Meta:
        app_label = 'models'  # Explicitly set app_label for Django model resolution
        db_table = 'ingest_run'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['source', 'status']),
            models.Index(fields=['status', 'stage']),
            models.Index(fields=['started_at']),
        ]

    def __str__(self):
        return f"Run {self.id}: {self.source} ({self.status}, {self.stage})"

    def mark_completed(self):
        """Mark run as completed"""
        self.status = IngestStatus.COMPLETED
        self.stage = IngestStage.COMPLETED
        self.completed_at = timezone.now()
        self.save()

    def mark_failed(self, error: Exception):
        """Mark run as failed with error"""
        import traceback
        self.status = IngestStatus.FAILED
        self.error_message = str(error)
        self.error_traceback = traceback.format_exc()
        self.completed_at = timezone.now()
        self.save()









