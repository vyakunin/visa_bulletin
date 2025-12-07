# Models package
# Import models so Django can discover them for migrations and system checks
#
# IMPORTANT: These imports are REQUIRED for Django's model discovery:
# - makemigrations needs models to be importable to generate migrations
# - System checks run BEFORE AppConfig.ready(), so models must be importable here
# - AppConfig.ready() is too late - it runs after Django is fully initialized
#
# Import ingest models FIRST (before other models that reference them)
# This ensures IngestVersion is registered before SalaryRecord/VisaCutoffDate try to reference it
from .ingest.data_source import DataSource
from .ingest.ingest_run import IngestRun
from .ingest.ingest_version import IngestVersion

# Note: Other models (SalaryRecord, Bulletin, VisaCutoffDate) are NOT imported here
# to avoid circular import issues. Django will discover them automatically via AppConfig.ready()

# Explicitly make ingest models available at package level
__all__ = ['DataSource', 'IngestRun', 'IngestVersion']


