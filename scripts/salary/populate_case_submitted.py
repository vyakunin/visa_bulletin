#!/usr/bin/env python3
"""
Populate case_submitted field for existing SalaryRecord records.

This script reads DOL source files and updates the case_submitted field
for existing records that are missing this data.

Usage:
    bazel run //scripts/salary:populate_case_submitted
    bazel run //scripts/salary:populate_case_submitted -- --dry-run
    bazel run //scripts/salary:populate_case_submitted -- --file PERM_Disclosure_Data_FY2024_Q4.xlsx
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django.db import transaction
from django_config.logging_config import setup_logging
from models.salary import SalaryRecord
from lib.parsing.salary.db_importer import (
    LCA_COLUMN_MAPPINGS,
    PERM_COLUMN_MAPPINGS,
    get_column_value,
    parse_date,
)
from lib.utils.excel_utils import read_excel_streaming
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger

setup_logging(debug=False)
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def get_date_columns(file_path: Path) -> tuple[list[str], bool]:
    """
    Determine which column mappings to use based on filename.
    
    Returns:
        Tuple of (column_mappings, is_perm)
    """
    filename = file_path.name.upper()
    if 'PERM' in filename:
        return PERM_COLUMN_MAPPINGS, True
    else:
        return LCA_COLUMN_MAPPINGS, False


def populate_dates_from_file(
    file_path: Path,
    dry_run: bool = False,
    batch_size: int = 5000,
) -> tuple[int, int, int]:
    """
    Read source file and update case_submitted for matching records.
    
    Returns:
        Tuple of (updated_count, skipped_count, error_count)
    """
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return 0, 0, 1
    
    source_file = file_path.name
    column_mappings, is_perm = get_date_columns(file_path)
    
    # Get records that need updating (case_submitted is NULL)
    records_to_update = set(
        SalaryRecord.objects.filter(
            source_file=source_file,
            case_submitted__isnull=True
        ).values_list('case_number', flat=True)
    )
    
    if not records_to_update:
        logger.info(f"No records need updating for {source_file}")
        return 0, 0, 0
    
    logger.info(f"Found {len(records_to_update):,} records without case_submitted in {source_file}")
    
    # Read source file and extract case_number -> date mappings
    case_dates = {}
    row_count = 0
    
    logger.info(f"Reading {source_file}...")
    
    if file_path.suffix.lower() in ['.xlsx', '.xls']:
        for record in read_excel_streaming(file_path, read_only=True, data_only=True):
            row_count += 1
            case_number = get_column_value(record, column_mappings['case_number'])
            if not case_number:
                continue
            
            if case_number not in records_to_update:
                continue
            
            # Get case_submitted date
            case_submitted = parse_date(get_column_value(record, column_mappings['case_submitted']))
            if case_submitted:
                case_dates[case_number] = case_submitted
            
            if row_count % 100000 == 0:
                logger.info(f"  Processed {row_count:,} rows, found {len(case_dates):,} dates...")
    else:
        import csv
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for record in reader:
                row_count += 1
                case_number = get_column_value(record, column_mappings['case_number'])
                if not case_number:
                    continue
                
                if case_number not in records_to_update:
                    continue
                
                case_submitted = parse_date(get_column_value(record, column_mappings['case_submitted']))
                if case_submitted:
                    case_dates[case_number] = case_submitted
                
                if row_count % 100000 == 0:
                    logger.info(f"  Processed {row_count:,} rows, found {len(case_dates):,} dates...")
    
    logger.info(f"Found {len(case_dates):,} dates to update from {row_count:,} rows")
    
    if not case_dates:
        logger.info(f"No dates found in {source_file}")
        return 0, len(records_to_update), 0
    
    if dry_run:
        logger.info(f"[DRY RUN] Would update {len(case_dates):,} records")
        return 0, 0, 0
    
    # Update records in batches
    updated = 0
    case_numbers = list(case_dates.keys())
    
    for i in range(0, len(case_numbers), batch_size):
        batch = case_numbers[i:i + batch_size]
        
        with transaction.atomic():
            for case_number in batch:
                date_value = case_dates[case_number]
                count = SalaryRecord.objects.filter(
                    case_number=case_number,
                    source_file=source_file,
                    case_submitted__isnull=True
                ).update(case_submitted=date_value)
                updated += count
        
        logger.info(f"  Updated {updated:,} records...")
    
    skipped = len(records_to_update) - updated
    return updated, skipped, 0


def get_source_files(data_dir: Path, specific_file: Optional[str] = None) -> list[Path]:
    """Get list of DOL source files to process."""
    files = []
    
    if specific_file:
        file_path = data_dir / specific_file
        if file_path.exists():
            files.append(file_path)
        else:
            logger.error(f"Specified file not found: {file_path}")
    else:
        # Get all LCA and PERM files
        for ext in ['*.xlsx', '*.xls', '*.csv']:
            for file_path in data_dir.glob(ext):
                # Skip appendix and worksite files
                if 'appendix' in file_path.name.lower() or 'worksite' in file_path.name.lower():
                    continue
                files.append(file_path)
    
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description='Populate case_submitted field for existing SalaryRecord records'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    parser.add_argument(
        '--file',
        help='Process specific file only (e.g., PERM_Disclosure_Data_FY2024_Q4.xlsx)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=5000,
        help='Batch size for updates (default: 5000)'
    )
    
    args = parser.parse_args()
    script_logger.log_call(args=vars(args), context='Populate case_submitted')
    
    data_dir = get_workspace_dir() / 'data' / 'salary' / 'dol_data'
    
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)
    
    source_files = get_source_files(data_dir, args.file)
    
    if not source_files:
        logger.error("No source files found")
        sys.exit(1)
    
    logger.info(f"Processing {len(source_files)} source files...")
    
    total_updated = 0
    total_skipped = 0
    total_errors = 0
    
    for file_path in source_files:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {file_path.name}")
        logger.info(f"{'='*60}")
        
        try:
            updated, skipped, errors = populate_dates_from_file(
                file_path,
                dry_run=args.dry_run,
                batch_size=args.batch_size
            )
            total_updated += updated
            total_skipped += skipped
            total_errors += errors
        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}", exc_info=True)
            total_errors += 1
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total files processed: {len(source_files)}")
    logger.info(f"Total records updated: {total_updated:,}")
    logger.info(f"Total records skipped: {total_skipped:,}")
    logger.info(f"Total errors: {total_errors}")
    
    if args.dry_run:
        logger.info("\n[DRY RUN MODE - No changes were made]")


if __name__ == '__main__':
    main()
