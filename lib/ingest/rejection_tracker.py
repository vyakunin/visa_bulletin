"""RejectionTracker - Collects and saves rejection statistics during ingestion"""

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.ingest.ingest_run import IngestRun

logger = logging.getLogger(__name__)


class RejectionTracker:
    """
    Tracks record rejections during transform stage.
    
    Collects counts and sample case numbers for each rejection reason,
    then saves to database at the end of the run for analysis.
    
    Usage:
        tracker = RejectionTracker(run)
        tracker.record_rejection('missing_employer_name', case_number='I-200-12345')
        tracker.save_to_db()
    """
    
    def __init__(self, run: 'IngestRun'):
        """
        Initialize rejection tracker.
        
        Args:
            run: IngestRun instance to track rejections for
        """
        self.run = run
        # Dict of reason -> {'count': int, 'samples': list[str]}
        self._stats: dict[str, dict] = defaultdict(lambda: {'count': 0, 'samples': []})
    
    def record_rejection(self, reason: str, case_number: str | None = None):
        """
        Record a rejected record.
        
        Args:
            reason: Rejection reason code (from RejectionReason enum)
            case_number: Optional case number for sampling
        """
        stats = self._stats[reason]
        stats['count'] += 1
        
        # Add to samples if provided and not already in list (keep max 10)
        if case_number and case_number not in stats['samples']:
            if len(stats['samples']) < 10:
                stats['samples'].append(case_number)
    
    def save_to_db(self):
        """
        Save collected rejection statistics to database.
        
        Creates IngestRejectionStats records for this run.
        """
        if not self._stats:
            logger.debug(f"[Run {self.run.id}] No rejections to save")
            return
        
        # Import here to avoid circular dependency
        from models.ingest.rejection_stats import IngestRejectionStats
        
        # Create rejection stats records
        rejection_records = []
        for reason, stats in self._stats.items():
            rejection_records.append(
                IngestRejectionStats(
                    run=self.run,
                    reason=reason,
                    count=stats['count'],
                    sample_case_numbers=stats['samples']
                )
            )
        
        # Bulk create
        IngestRejectionStats.objects.bulk_create(rejection_records, ignore_conflicts=True)
        
        # Log summary
        total_rejections = sum(s['count'] for s in self._stats.values())
        logger.info(
            f"[Run {self.run.id}] Saved {len(rejection_records)} rejection reasons "
            f"({total_rejections:,} total rejections)"
        )
        
        # Log breakdown for visibility
        for reason, stats in sorted(self._stats.items(), key=lambda x: x[1]['count'], reverse=True):
            logger.info(f"[Run {self.run.id}]   {reason}: {stats['count']:,} records")
    
    def get_stats(self) -> dict:
        """
        Get current rejection statistics (for testing/debugging).
        
        Returns:
            Dict of reason -> {'count': int, 'samples': list[str]}
        """
        return dict(self._stats)
    
    def total_rejections(self) -> int:
        """Get total number of rejections across all reasons"""
        return sum(s['count'] for s in self._stats.values())
