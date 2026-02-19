#!/usr/bin/env python3
"""
Drop all salary records and orphaned employers from the database.

This script deletes:
- All SalaryRecord objects
- All Employer objects that have no associated salary records

Usage:
    bazel run //scripts/salary:drop_data
    bazel run //scripts/salary:drop_data -- --force  # Skip confirmation prompt
"""

import argparse
import logging
import os
import sys

from django.db import transaction

# Setup Django early (before any model imports)
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django

django.setup()

# Configure logging
from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Import models and utilities
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, SalaryRecord

script_logger = ScriptLogger(__file__)


def drop_all_salary_records() -> int:
    """Delete all salary records from the database"""
    count = SalaryRecord.objects.count()
    if count > 0:
        logger.info(f"Deleting {count:,} salary records...")
        SalaryRecord.objects.all().delete()
        logger.info(f"Deleted {count:,} salary records")
    else:
        logger.info("No salary records to delete")
    return count


def drop_orphaned_employers() -> int:
    """Delete employers that have no associated salary records"""
    # Find employers with no salary records
    orphaned = Employer.objects.filter(salary_records__isnull=True)
    count = orphaned.count()
    if count > 0:
        logger.info(f"Deleting {count:,} orphaned employers...")
        orphaned.delete()
        logger.info(f"Deleted {count:,} orphaned employers")
    else:
        logger.info("No orphaned employers to delete")
    return count


def delete_all_data_files() -> int:
    """Delete all data files in data/salary/dol_data/ directory"""
    dol_data_dir = get_workspace_dir() / 'data' / 'salary' / 'dol_data'
    if not dol_data_dir.exists():
        logger.info("data/salary/dol_data/ directory does not exist, nothing to delete")
        return 0

    deleted_count = 0
    for pattern in ['*.csv', '*.CSV', '*.xlsx', '*.XLSX', '*.xls', '*.XLS']:
        for filepath in dol_data_dir.glob(pattern):
            try:
                filepath.unlink()
                deleted_count += 1
                logger.debug(f"Deleted: {filepath.name}")
            except Exception as e:
                logger.warning(f"Failed to delete {filepath.name}: {e}")

    return deleted_count


def main():
    parser = argparse.ArgumentParser(
        description='Drop all salary records and orphaned employers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Drop all data (with confirmation):
    bazel run //:drop_salary_data
  
  Drop all data without confirmation:
    bazel run //:drop_salary_data -- --force

WARNING: This operation cannot be undone!
        """
    )

    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Skip confirmation prompt (use with caution)'
    )

    parser.add_argument(
        '--delete-files',
        action='store_true',
        help='Also delete all data files in data/salary/dol_data/ directory'
    )

    args = parser.parse_args()

    # Log script execution
    script_logger.log_call(
        args={'force': args.force, 'delete_files': args.delete_files},
        context='Dropping all salary data and orphaned employers'
    )

    # Get counts before deletion
    salary_count = SalaryRecord.objects.count()
    employer_count = Employer.objects.count()
    orphaned_count = Employer.objects.filter(salary_records__isnull=True).count()

    # Check file count if deleting files
    file_count = 0
    if args.delete_files:
        dol_data_dir = get_workspace_dir() / 'dol_data'
        if dol_data_dir.exists():
            file_count = len(list(dol_data_dir.glob('*.csv')) +
                            list(dol_data_dir.glob('*.xlsx')) +
                            list(dol_data_dir.glob('*.xls')))

    logger.info("=" * 60)
    logger.info("Salary Data Deletion")
    logger.info("=" * 60)
    logger.info("Current database state:")
    logger.info(f"  Salary records: {salary_count:,}")
    logger.info(f"  Total employers: {employer_count:,}")
    logger.info(f"  Orphaned employers: {orphaned_count:,}")
    if args.delete_files:
        logger.info("Current file state:")
        logger.info(f"  Data files in data/salary/dol_data/: {file_count}")
    logger.info("")

    # Confirmation prompt
    if not args.force:
        warning_msg = "WARNING: This will delete ALL salary records and orphaned employers!"
        if args.delete_files:
            warning_msg += "\nWARNING: This will also delete ALL data files in data/salary/dol_data/!"
        logger.warning(warning_msg)
        logger.warning("This operation cannot be undone.")
        response = input("Type 'yes' to continue: ")
        if response.lower() != 'yes':
            logger.info("Operation cancelled.")
            sys.exit(0)

    # Delete files first (if requested)
    files_deleted = 0
    if args.delete_files:
        logger.info("Deleting all data files...")
        files_deleted = delete_all_data_files()
        logger.info(f"Deleted {files_deleted} file(s) from data/salary/dol_data/")
        logger.info("")

    # Perform database deletion in transaction
    try:
        with transaction.atomic():
            salary_deleted = drop_all_salary_records()
            employers_deleted = drop_orphaned_employers()

        logger.info("=" * 60)
        logger.info("Deletion complete!")
        logger.info(f"  Salary records deleted: {salary_deleted:,}")
        logger.info(f"  Orphaned employers deleted: {employers_deleted:,}")
        if args.delete_files:
            logger.info(f"  Data files deleted: {files_deleted}")
        logger.info("")
        logger.info("Final database state:")
        logger.info(f"  Salary records: {SalaryRecord.objects.count():,}")
        logger.info(f"  Total employers: {Employer.objects.count():,}")

    except Exception as e:
        logger.error(f"Error during deletion: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
