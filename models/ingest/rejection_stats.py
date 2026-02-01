"""IngestRejectionStats model - Tracks why records are rejected during ingestion"""

from django.db import models
from .ingest_run import IngestRun


class RejectionReason(models.TextChoices):
    """Reasons why records are rejected during transform stage"""
    MISSING_CASE_NUMBER = 'missing_case_number', 'Missing Case Number'
    MISSING_EMPLOYER_NAME = 'missing_employer_name', 'Missing Employer Name'
    UNKNOWN_EMPLOYER_NAME = 'unknown_employer_name', 'Unknown Employer Name'
    MISSING_JOB_TITLE = 'missing_job_title', 'Missing Job Title'
    UNKNOWN_JOB_TITLE = 'unknown_job_title', 'Unknown Job Title'
    MISSING_WAGE_DATA = 'missing_wage_data', 'Missing Wage Data'
    INVALID_WAGE_UNIT = 'invalid_wage_unit', 'Invalid Wage Unit'
    MISSING_DATES = 'missing_dates', 'Missing Decision/Submit Dates'
    INVALID_DATE_SEQUENCE = 'invalid_date_sequence', 'Invalid Date Sequence'
    MISSING_VISA_CLASS = 'missing_visa_class', 'Missing Visa Class'
    WHITELIST_FILTERED = 'whitelist_filtered', 'Filtered by Case Number Whitelist'
    WORKSITE_SKIPPED = 'worksite_skipped', 'Worksite Record Skipped'
    OTHER = 'other', 'Other Rejection Reason'


class IngestRejectionStats(models.Model):
    """
    Tracks rejection statistics for an ingest run.
    
    Each record represents one rejection reason with aggregate counts and examples.
    This helps identify data quality issues and potential format mismatches.
    """
    
    run = models.ForeignKey(
        IngestRun,
        on_delete=models.CASCADE,
        related_name='rejection_stats',
        help_text="Ingest run these rejections occurred in"
    )
    reason = models.CharField(
        max_length=50,
        choices=RejectionReason.choices,
        help_text="Reason for rejection"
    )
    count = models.IntegerField(
        default=0,
        help_text="Number of records rejected for this reason"
    )
    sample_case_numbers = models.JSONField(
        default=list,
        help_text="Sample case numbers (up to 10) for investigation"
    )
    
    class Meta:
        app_label = 'models'
        db_table = 'ingest_rejection_stats'
        unique_together = [['run', 'reason']]
        indexes = [
            models.Index(fields=['run', 'reason']),
            models.Index(fields=['run', 'count']),
        ]
        verbose_name = 'Ingest Rejection Statistics'
        verbose_name_plural = 'Ingest Rejection Statistics'
    
    def __str__(self):
        return f"Run {self.run_id}: {self.get_reason_display()} ({self.count:,} records)"
    
    def add_rejection(self, case_number: str | None = None):
        """
        Increment rejection count and optionally add sample case number.
        
        Args:
            case_number: Case number to add to samples (if provided and not already in list)
        """
        self.count += 1
        
        # Add to samples if provided and not already in list (keep max 10)
        if case_number and case_number not in self.sample_case_numbers:
            if len(self.sample_case_numbers) < 10:
                self.sample_case_numbers.append(case_number)
