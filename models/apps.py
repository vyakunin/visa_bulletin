"""Django app configuration for models"""

from django.apps import AppConfig


class ModelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'models'
    
    def ready(self):
        """Import all models when app is ready to ensure Django can resolve ForeignKey references"""
        # Import ingest models FIRST to ensure they're registered before others reference them
        from .ingest.data_source import DataSource  # noqa: F401
        from .ingest.ingest_run import IngestRun  # noqa: F401
        from .ingest.ingest_version import IngestVersion  # noqa: F401
        from .ingest.rejection_stats import IngestRejectionStats, RejectionReason  # noqa: F401
        
        # Then import other models (these may reference ingest models)
        from .bulletin import Bulletin  # noqa: F401
        from .salary import SalaryRecord, Employer, WorksiteRecord  # noqa: F401
        from .job_title import JobTitle, JobTitleCluster, JobTitleClusteringReview  # noqa: F401
        from .visa_cutoff_date import VisaCutoffDate  # noqa: F401

