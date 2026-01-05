#!/usr/bin/env python3
"""
Check available columns and sample data in DOL source files.

Inspects PERM and LCA files to identify available columns, show sample values,
and estimate storage impact for potential new features.

Usage:
    bazel run //scripts:check_source_columns

Output:
    - Total columns in each file
    - Name-related columns (employee/beneficiary/alien)
    - Sample values from each column
    - Total record counts per file
    - Storage impact estimates

When to use:
    - Before adding new fields to database schema
    - To understand what data is available in source files
    - To estimate storage impact for new features
    - To identify potential data quality issues

Example output:
    Checking PERM_Disclosure_Data_FY2020.xlsx...
    ================================================================================
    Total columns: 67
    All columns:
      1. CASE_NUMBER
      2. EMPLOYER_NAME
      3. FOREIGN_WORKER_BIRTH_COUNTRY
      4. FOREIGN_WORKER_EDUCATION
      ...
    
    ================================================================================
    Name-related columns (employee/beneficiary/alien):
      ✓ FOREIGN_WORKER_BIRTH_COUNTRY
        Sample: ['POLAND', 'INDIA']
      ✓ FOREIGN_WORKER_EDUCATION
        Sample: ['Bachelor's', 'Master's']
      ...
    
    Total records in PERM FY2020: 123,456
"""
import logging
import sys
from pathlib import Path
from lib.utils.http_utils import get_workspace_dir
from lib.utils.excel_utils import read_excel_headers, read_excel_rows
from lib.utils.data_source_utils import get_file_stats  # ALWAYS use this cached version, never call _count_excel_rows directly
from django_config.logging_config import setup_logging

# Setup logging
setup_logging(debug=False)
logger = logging.getLogger(__name__)

def main():
    # Get workspace directory
    workspace_dir = get_workspace_dir()
    
    # Check PERM file (use FY2020 which exists)
    perm_file = workspace_dir / 'data/salary/dol_data/PERM_Disclosure_Data_FY2020.xlsx'
    logger.info(f'Checking {perm_file.name}...')
    logger.info('=' * 80)

    # Use utility to read headers
    columns = read_excel_headers(perm_file)

    logger.info(f'Total columns: {len(columns)}')
    logger.info('All columns:')
    for i, col in enumerate(columns, 1):
        logger.info(f'{i:3d}. {col}')

    # Look for name-related columns
    logger.info('=' * 80)
    logger.info('Name-related columns (employee/beneficiary/alien):')
    name_cols = [col for col in columns if any(word in str(col).lower() for word in ['name', 'alien', 'beneficiary', 'employee', 'worker'])]
    if name_cols:
        # Read first 3 data rows to show samples
        sample_rows = read_excel_rows(perm_file, [2, 3, 4])  # Skip header row 1
        for col in name_cols:
            # Filter out employer name columns
            if 'employer' not in col.lower():
                logger.info(f'  ✓ {col}')
                # Show sample values (first 2 non-empty)
                samples = [row.get(col, '') for row in sample_rows if row.get(col, '')][:2]
                if samples:
                    logger.info(f'    Sample: {samples}')
    else:
        logger.info('  (none found)')

    # Check total record count using cached utility
    logger.info('=' * 80)
    perm_stats = get_file_stats(perm_file)
    logger.info(f'Total records in PERM FY2020: {perm_stats["row_count"]:,}')

    # Check LCA file too
    logger.info('')
    logger.info('=' * 80)
    lca_file = workspace_dir / 'data/salary/dol_data/LCA_Disclosure_Data_FY2024_Q4.xlsx'
    if lca_file.exists():
        logger.info(f'Checking {lca_file.name}...')
        logger.info('=' * 80)
        
        # Use utility to read headers
        lca_columns = read_excel_headers(lca_file)
        logger.info(f'Total columns: {len(lca_columns)}')
        
        # Look for name-related columns
        logger.info('Name-related columns (employee/beneficiary/alien):')
        name_cols_lca = [col for col in lca_columns if any(word in str(col).lower() for word in ['name', 'alien', 'beneficiary', 'employee', 'worker'])]
        if name_cols_lca:
            # Read first 3 data rows to show samples
            lca_sample_rows = read_excel_rows(lca_file, [2, 3, 4])
            for col in name_cols_lca:
                # Filter out employer name columns
                if 'employer' not in col.lower():
                    logger.info(f'  ✓ {col}')
                    # Show sample values
                    samples = [row.get(col, '') for row in lca_sample_rows if row.get(col, '')][:2]
                    if samples:
                        logger.info(f'    Sample: {samples}')
        else:
            logger.info('  (none found)')
        
        # Check total record count using cached utility
        lca_stats = get_file_stats(lca_file)
        logger.info(f'Total records in LCA FY2024 Q4: {lca_stats["row_count"]:,}')
    else:
        logger.warning(f'{lca_file.name} not found')

    # Estimate storage impact
    logger.info('')
    logger.info('=' * 80)
    logger.info('STORAGE IMPACT ESTIMATE:')
    logger.info('=' * 80)
    
    # Count total records across all files using cached utility
    import glob
    total_records = 0
    data_dir = workspace_dir / 'data/salary/dol_data'
    for file_path in sorted(glob.glob(str(data_dir / '*.xlsx'))):
        try:
            file_path_obj = Path(file_path)
            file_stats = get_file_stats(file_path_obj, logger_instance=logger)
            count = file_stats['row_count']
            total_records += count
            logger.info(f'{file_path_obj.name}: {count:,} records')
        except Exception as e:
            logger.error(f'{Path(file_path).name}: Error reading - {e}', exc_info=True)
    
    logger.info(f'Total records across all files: {total_records:,}')
    
    # Estimate storage for names
    # Assume average name length: 30 characters (first + last name)
    # VARCHAR(100) would be safe for most names
    avg_name_length = 30
    varchar_size = 100  # Safe size for names
    
    # PostgreSQL VARCHAR storage: 1 byte per character + 1-4 bytes overhead
    bytes_per_name = avg_name_length + 4
    total_bytes = total_records * bytes_per_name
    total_mb = total_bytes / (1024 * 1024)
    total_gb = total_mb / 1024
    
    logger.info('')
    logger.info('Estimated storage for employee names:')
    logger.info(f'  Average name length: {avg_name_length} characters')
    logger.info(f'  Column type: VARCHAR({varchar_size})')
    logger.info(f'  Storage per record: ~{bytes_per_name} bytes')
    logger.info(f'  Total storage: {total_mb:.1f} MB ({total_gb:.2f} GB)')
    
    # Compare to current database size
    logger.info('')
    logger.info('  For comparison:')
    logger.info('    Current SalaryRecord has ~20 columns')
    logger.info('    Adding 1 name column = ~5% increase in table size')

if __name__ == '__main__':
    main()

