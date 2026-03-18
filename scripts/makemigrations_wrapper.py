#!/usr/bin/env python3
"""
Wrapper script for makemigrations that writes to the workspace directory.

Bazel runs commands in a sandbox, so Django's makemigrations creates files
in the sandbox. This wrapper uses BUILD_WORKSPACE_DIRECTORY to write
migrations to the actual workspace.
"""

import logging
import os
import shutil
from pathlib import Path

# Get workspace directory from Bazel
workspace_dir = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", os.getcwd()))

# Setup Django
# Note: makemigrations doesn't need a real database connection, but Django still
# needs to load the database backend. PostgreSQL backend requires psycopg2-binary.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

# Configure logging
from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

from django.core.management import call_command

# Debug: Check what Django sees
logger.debug(f"Workspace dir: {workspace_dir}")
logger.debug(f"Current dir: {os.getcwd()}")

from django.apps import apps

for app_config in apps.get_app_configs():
    if app_config.name == "models":
        logger.debug(f"Models app path: {app_config.path}")
        migrations_path = Path(app_config.path) / "migrations"
        logger.debug(f"Migrations path: {migrations_path}")
        if migrations_path.exists():
            existing = list(migrations_path.glob("*.py"))
            logger.debug(f"Existing migration files: {[f.name for f in existing]}")

# Check if models are loaded
# IMPORTANT: Import ALL models so makemigrations can detect them
# makemigrations runs BEFORE AppConfig.ready(), so models must be imported here
from models.blog import BlogPost
from models.bulletin import Bulletin
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.ingest.ingest_version import IngestVersion
from models.job_title import JobTitle, JobTitleCluster, JobTitleClusteringReview
from models.raw_facts import RawFactsLedger
from models.salary import Employer, SalaryRecord
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff

logger.debug(f"BlogPost model: {BlogPost}")
logger.debug(f"Bulletin model: {Bulletin}")
logger.debug(f"DataSource model: {DataSource}")
logger.debug(f"Employer model: {Employer}")
logger.debug(f"IngestRun model: {IngestRun}")
logger.debug(f"IngestVersion model: {IngestVersion}")
logger.debug(f"JobTitle model: {JobTitle}")
logger.debug(f"JobTitleCluster model: {JobTitleCluster}")
logger.debug(f"JobTitleClusteringReview model: {JobTitleClusteringReview}")
logger.debug(f"PredictedBulletin model: {PredictedBulletin}")
logger.debug(f"PredictedCutoff model: {PredictedCutoff}")
logger.debug(f"RawFactsLedger model: {RawFactsLedger}")
logger.debug(f"SalaryRecord model: {SalaryRecord}")
logger.debug(f"VisaCutoffDate model: {VisaCutoffDate}")

# Log script execution
script_logger.log_call(args={}, context="Creating Django migrations for models app")

# Run makemigrations with verbosity 2
call_command("makemigrations", "models", verbosity=2)

# Copy migration files from sandbox to workspace
# Django creates migrations in the app's migrations directory
# In Bazel sandbox, this is relative to where Django thinks the app is
# We need to find where Django created them and copy to workspace

# The models app path in the sandbox
models_app_path = None
for app_config in django.apps.apps.get_app_configs():
    if app_config.name == "models":
        models_app_path = Path(app_config.path)
        break

if models_app_path:
    # Copy main models migrations
    migrations_src = models_app_path / "migrations"
    migrations_dst = workspace_dir / "models" / "migrations"

    if migrations_src.exists():
        # Ensure destination exists
        migrations_dst.mkdir(parents=True, exist_ok=True)

        # Copy new migration files
        for migration_file in migrations_src.glob("*.py"):
            if migration_file.name != "__init__.py":
                dst_file = migrations_dst / migration_file.name
                if (
                    not dst_file.exists()
                    or migration_file.stat().st_mtime > dst_file.stat().st_mtime
                ):
                    shutil.copy2(migration_file, dst_file)
                    logger.info(f"Copied {migration_file.name} to workspace")

    # Copy ingest subdirectory migrations if they exist
    ingest_migrations_src = models_app_path / "ingest" / "migrations"
    ingest_migrations_dst = workspace_dir / "models" / "ingest" / "migrations"

    if ingest_migrations_src.exists():
        # Ensure destination exists
        ingest_migrations_dst.mkdir(parents=True, exist_ok=True)

        # Copy new migration files
        for migration_file in ingest_migrations_src.glob("*.py"):
            if migration_file.name != "__init__.py":
                dst_file = ingest_migrations_dst / migration_file.name
                if (
                    not dst_file.exists()
                    or migration_file.stat().st_mtime > dst_file.stat().st_mtime
                ):
                    shutil.copy2(migration_file, dst_file)
                    logger.info(f"Copied ingest/{migration_file.name} to workspace")
