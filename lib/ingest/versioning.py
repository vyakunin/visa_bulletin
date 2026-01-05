"""Versioning and rollback utilities for ingest pipeline"""

import logging
from django.db import transaction

from models.ingest.ingest_version import IngestVersion
from models.salary import SalaryRecord
from models.visa_cutoff_date import VisaCutoffDate

logger = logging.getLogger(__name__)


def create_version(run, version_tag: str, supersedes: IngestVersion | None = None) -> IngestVersion:
    """
    Create a new ingest version for a completed run.
    
    Handles concurrent version creation by using get_or_create to prevent
    UNIQUE constraint violations when multiple processes complete the same run.
    
    Args:
        run: Completed IngestRun
        version_tag: Human-readable version tag (e.g., 'dol_lca_2024q4_v1')
        supersedes: Previous version this supersedes (for rollback chain)
        
    Returns:
        Created or existing IngestVersion instance
    """
    # Use get_or_create to handle concurrent version creation
    # If another process already created version for this run, return existing
    version, created = IngestVersion.objects.get_or_create(
        run=run,
        defaults={
            'version_tag': version_tag,
            'is_active': False,  # Start inactive, activate after validation
            'supersedes': supersedes
        }
    )
    
    if created:
        logger.info(f"Created version: {version_tag} for run {run.id}")
    else:
        logger.warning(f"Version already exists for run {run.id}: {version.version_tag} (concurrent completion detected)")
    
    return version


def activate_version(version: IngestVersion):
    """
    Activate a version (make it visible to serving queries).
    
    This atomically deactivates the previous version and activates the new one.
    
    Args:
        version: IngestVersion to activate
    """
    with transaction.atomic():
        # Deactivate all versions for the same source
        IngestVersion.objects.filter(
            run__source=version.run.source,
            is_active=True
        ).update(is_active=False)
        
        # Activate new version
        version.is_active = True
        version.save()
        
        logger.info(f"Activated version: {version.version_tag}")


def rollback_version(version_tag: str) -> dict:
    """
    Rollback all records from a specific ingest version.
    
    Args:
        version_tag: Version tag to rollback
        
    Returns:
        Dict with rollback statistics
    """
    try:
        version = IngestVersion.objects.get(version_tag=version_tag)
    except IngestVersion.DoesNotExist:
        raise ValueError(f"Version not found: {version_tag}")
    
    with transaction.atomic():
        # Count records before deletion
        salary_count = SalaryRecord.objects.filter(ingest_version=version).count()
        cutoff_count = VisaCutoffDate.objects.filter(ingest_version=version).count()
        
        # Delete all records from this version
        SalaryRecord.objects.filter(ingest_version=version).delete()
        VisaCutoffDate.objects.filter(ingest_version=version).delete()
        
        # Deactivate version
        version.is_active = False
        version.save()
        
        # Reactivate previous version if exists
        if version.supersedes:
            version.supersedes.is_active = True
            version.supersedes.save()
            logger.info(f"Rolled back to version: {version.supersedes.version_tag}")
        
        logger.info(f"Rolled back version {version_tag}: {salary_count} salary records, {cutoff_count} cutoff dates deleted")
        
        return {
            'version_tag': version_tag,
            'salary_records_deleted': salary_count,
            'cutoff_dates_deleted': cutoff_count,
            'previous_version_activated': version.supersedes.version_tag if version.supersedes else None
        }










