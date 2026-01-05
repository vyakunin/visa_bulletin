#!/usr/bin/env python3
"""
Rollback utility for ingest pipeline

Usage:
    bazel run //scripts/ingest:rollback -- --version dol_lca_2024q4_v1
"""

import argparse
import logging
import os
import sys

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django_config.logging_config import setup_logging
from lib.ingest.versioning import rollback_version
from lib.utils.logging_utils import ScriptLogger

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def main():
    parser = argparse.ArgumentParser(
        description='Rollback ingest version',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--version',
        required=True,
        help='Version tag to rollback (e.g., dol_lca_2024q4_v1)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    
    args = parser.parse_args()
    
    script_logger.log_call(args=vars(args), context='Rolling back ingest version')
    
    try:
        if args.dry_run:
            logger.info(f"DRY RUN: Would rollback version {args.version}")
            # TODO: Add dry-run logic to show what would be deleted
        else:
            result = rollback_version(args.version)
            logger.info(f"Rollback completed:")
            logger.info(f"  Version: {result['version_tag']}")
            logger.info(f"  Salary records deleted: {result['salary_records_deleted']:,}")
            logger.info(f"  Cutoff dates deleted: {result['cutoff_dates_deleted']:,}")
            if result['previous_version_activated']:
                logger.info(f"  Previous version activated: {result['previous_version_activated']}")
    except Exception as e:
        logger.error(f"Rollback failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

