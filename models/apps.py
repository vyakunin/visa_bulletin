"""Django app configuration for models"""

from django.apps import AppConfig


class ModelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'models'

    def ready(self):
        """Import all models when app is ready to ensure Django can resolve ForeignKey references"""
        # Import ingest models FIRST to ensure they're registered before others reference them
        # Then import other models (these may reference ingest models)
        from .bulletin import Bulletin  # noqa: F401
        from .ingest.data_source import DataSource  # noqa: F401
        from .ingest.ingest_run import IngestRun  # noqa: F401
        from .ingest.ingest_version import IngestVersion  # noqa: F401
        from .ingest.rejection_stats import (  # noqa: F401
            IngestRejectionStats,
            RejectionReason,
        )
        from .job_title import (  # noqa: F401
            JobTitle,
            JobTitleCluster,
            JobTitleClusteringReview,
        )
        from .salary import Employer, SalaryRecord, WorksiteRecord  # noqa: F401
        from .visa_cutoff_date import VisaCutoffDate  # noqa: F401
        from .raw_facts import RawFactsLedger  # noqa: F401
        from .vqs import PredictedBulletin, PredictedCutoff  # noqa: F401
        from .blog import BlogPost  # noqa: F401

