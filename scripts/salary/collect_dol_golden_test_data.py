#!/usr/bin/env python3
"""
Collect golden test data for DOL plugin transforms.

Samples random rows from all PERM and LCA files, saves parsed dicts to YAML
for manual annotation and golden testing.

Usage:
    bazel run //scripts/salary:collect_dol_golden_test_data
    bazel run //scripts/salary:collect_dol_golden_test_data -- --output tests/data/dol_golden_test_data.yaml
    bazel run //scripts/salary:collect_dol_golden_test_data -- --samples-per-file 20
"""

import argparse
import logging
import os
import random
import sys
from pathlib import Path
from typing import Optional

from lib.utils.excel_utils import (
    read_excel_headers,
    read_excel_rows,
)
from lib.utils.data_source_utils import count_file_rows, get_fiscal_year_from_filename
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import log_context
import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Log script execution (throwaway script pattern)
log_context("Collecting golden test data for DOL plugin transforms")


def detect_file_type(headers: list[str]) -> str | None:
    """
    Detect file type from column headers (not filename).
    
    Returns:
        "PERM", "H1B", or None (unknown)
    """
    headers_upper = [h.upper() for h in headers]
    
    # PERM files have specific column patterns
    perm_indicators = [
        'WAGE_OFFER_FROM_9089', 'WAGE_OFFERED_FROM_9089', 'JOB_OPP_WAGE_FROM',
        'PW_JOB_TITLE_9089', 'WAGE_OFFER_UNIT_OF_PAY_9089',
        'WAGE_OFFER_FROM', 'WAGE_OFFERED_FROM', 'WAGE_OFFER_TO',
        'PW_SOC_CODE', 'PW_SOC_TITLE'  # PERM-specific prevailing wage columns
    ]
    if any(ind in headers_upper for ind in perm_indicators):
        return "PERM"
    
    # Check for PERM case number pattern (A- prefix) in filename context
    # Note: We can't check case numbers here, but PERM files often have specific structure
    
    # LCA/H1B files have LCA-specific columns or H-1B visa class
    lca_indicators = [
        'LCA_CASE_NUMBER', 'LCA_CASE_WAGE_RATE_FROM',
        'LCA_CASE_JOB_TITLE', 'LCA_CASE_SOC_CODE',
        'VISA_CLASS',  # H-1B files have VISA_CLASS column
    ]
    if any(ind in headers_upper for ind in lca_indicators):
        # Check if worksite file (no employer fields, has worksite fields)
        has_employer = any('EMPLOYER' in h for h in headers_upper)
        has_worksite = any('WORKSITE' in h or 'WORK_CITY' in h for h in headers_upper)
        
        if not has_employer and has_worksite:
            # Worksite file - still use H1B plugin but will route to WorksiteRecord
            return "H1B"  # Plugin handles routing based on case number prefix
        else:
            return "H1B"
    
    # Fallback: Check for CASE_NUMBER with wage fields (could be H1B or PERM)
    # H1B files typically have VISA_CLASS or employment dates
    # PERM files typically have wage offer columns
    has_case_number = any('CASE_NUMBER' in h or 'CASE_NO' in h for h in headers_upper)
    has_wage = any('WAGE' in h for h in headers_upper)
    has_visa_class = any('VISA_CLASS' in h or 'PROGRAM' in h for h in headers_upper)
    has_employment_dates = any('EMPLOYMENT' in h and 'DATE' in h for h in headers_upper)
    has_worksite_fields = any('WORKSITE' in h or 'WORK_CITY' in h for h in headers_upper)
    has_employer = any('EMPLOYER' in h for h in headers_upper)
    
    if has_case_number and has_wage:
        # Worksite files: CASE_NUMBER + WAGE + WORKSITE fields (no employer)
        if has_worksite_fields and not has_employer:
            return "H1B"  # Worksite file - plugin routes I-200 to WorksiteRecord
        # If it has VISA_CLASS or employment dates, likely H1B
        if has_visa_class or has_employment_dates:
            return "H1B"
        # If it has employer fields and wage offer columns, could be PERM
        has_wage_offer = any('WAGE_OFFER' in h or 'OFFERED_WAGE' in h for h in headers_upper)
        if has_employer and has_wage_offer:
            return "PERM"
        # Default to H1B if unclear (most common)
        if has_employer:
            return "H1B"
    
    return None  # Unknown file type - will be reviewed manually


def process_file(
    filepath: Path,
    samples_per_file: int,
    random_seed: int,
    unknown_files: list[dict]
) -> list[dict]:
    """
    Process a single Excel file and return test cases.
    
    Returns:
        List of test case dicts
    """
    logger.info(f"Processing: {filepath.name}")
    
    try:
        # Read headers
        logger.info(f"  Reading headers from {filepath.name}...")
        headers = read_excel_headers(filepath)
        logger.debug(f"  Read {len(headers)} headers")
        
        # Detect file type
        plugin_type = detect_file_type(headers)
        
        if plugin_type is None:
            # Unknown file type - collect for review
            logger.warning(f"Unknown file type: {filepath.name}")
            
            # Read sample rows for review
            logger.debug(f"  Reading sample rows for unknown file type...")
            sample_rows = read_excel_rows(filepath, [2, 3, 4])  # First 2-3 data rows
            logger.debug(f"  Read {len(sample_rows)} sample rows")
            
            unknown_files.append({
                'filename': filepath.name,
                'headers': headers[:20],  # First 20 headers
                'sample_rows': [
                    dict(list(row.items())[:10])  # First 10 columns
                    for row in sample_rows
                ],
            })
            return []
        
        # Get row count
        # NOTE: Use count_file_rows (cached) instead of count_excel_rows (uncached)
        logger.info(f"  Counting rows in {filepath.name}...")
        row_count = count_file_rows(filepath)
        logger.info(f"  Found {row_count:,} data rows")
        
        if row_count == 0:
            logger.warning(f"No data rows in {filepath.name}")
            return []
        
        # Sample random rows
        sample_size = min(samples_per_file, row_count)
        # Row numbers are 1-indexed, but data rows start at 2 (row 1 is header)
        logger.info(f"  Sampling {sample_size} random rows from {row_count:,} total rows...")
        data_row_numbers = list(range(2, row_count + 2))
        sampled_row_numbers = random.sample(data_row_numbers, sample_size)
        logger.debug(f"  Selected rows: {sampled_row_numbers[:5]}{'...' if len(sampled_row_numbers) > 5 else ''}")
        
        # Read sampled rows
        logger.info(f"  Reading {len(sampled_row_numbers)} sampled rows from {filepath.name}...")
        sampled_rows = read_excel_rows(filepath, sampled_row_numbers)
        logger.debug(f"  Read {len(sampled_rows)} rows successfully")
        
        # Extract fiscal year from filename
        fiscal_year = get_fiscal_year_from_filename(filepath.name)
        
        # Create test cases
        test_cases = []
        for row, row_num in zip(sampled_rows, sampled_row_numbers):
            test_case = {
                'plugin_type': plugin_type,
                'source_file': filepath.name,
                'row_number': row_num,
                'fiscal_year': fiscal_year,
                'input': row,  # All column values as dict
            }
            test_cases.append(test_case)
        
        logger.info(f"  Collected {len(test_cases)} samples from {row_count} total rows")
        return test_cases
        
    except Exception as e:
        logger.error(f"Error processing {filepath.name}: {e}", exc_info=True)
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Collect golden test data for DOL plugin transforms"
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,  # Will be set to absolute path below
        help='Output YAML file path (default: <workspace>/tests/data/dol_golden_test_data.yaml)'
    )
    parser.add_argument(
        '--samples-per-file',
        type=int,
        default=10,
        help='Number of random rows to sample per file (default: 10)'
    )
    parser.add_argument(
        '--random-seed',
        type=int,
        default=42,
        help='Random seed for reproducibility (default: 42)'
    )
    parser.add_argument(
        '--unknown-output',
        type=Path,
        default=Path('tests/data/unknown_file_types.txt'),
        help='Output file for unknown file types review (default: tests/data/unknown_file_types.txt)'
    )
    parser.add_argument(
        '--limit-files',
        type=int,
        default=None,
        help='Limit number of files to process (for testing)'
    )
    
    args = parser.parse_args()
    
    # Resolve output path to absolute path in workspace
    workspace_dir = get_workspace_dir()
    if args.output is None:
        args.output = workspace_dir / 'tests' / 'data' / 'dol_golden_test_data.yaml'
    elif not args.output.is_absolute():
        # If relative path provided, make it relative to workspace
        args.output = workspace_dir / args.output
    
    # Resolve unknown_output path to absolute path in workspace
    if not args.unknown_output.is_absolute():
        args.unknown_output = workspace_dir / args.unknown_output
    
    # Set random seed for reproducibility
    random.seed(args.random_seed)
    
    # Find data directory
    logger.info("Finding data directory...")
    data_dir = workspace_dir / 'data' / 'salary' / 'dol_data'
    logger.debug(f"Data directory: {data_dir}")
    
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)
    
    # Find all Excel files
    logger.info(f"Scanning for Excel files in {data_dir}...")
    all_excel_files = sorted(data_dir.glob('*.xlsx')) + sorted(data_dir.glob('*.xls'))
    logger.debug(f"Found {len(all_excel_files)} Excel files")
    
    if not all_excel_files:
        logger.error(f"No Excel files found in {data_dir}")
        sys.exit(1)
    
    # Limit files if requested (for testing)
    # Prefer files with PERM or LCA in name for better detection
    if args.limit_files:
        perm_files = [f for f in all_excel_files if 'PERM' in f.name.upper()]
        lca_files = [f for f in all_excel_files if ('LCA' in f.name.upper() or 'H-1B' in f.name.upper()) and 'PERM' not in f.name.upper()]
        
        # Try to get mix of PERM and LCA if available
        selected = []
        if perm_files and len(selected) < args.limit_files:
            selected.extend(perm_files[:1])
        if lca_files and len(selected) < args.limit_files:
            selected.extend(lca_files[:args.limit_files - len(selected)])
        
        # Fill remaining slots with any files
        if len(selected) < args.limit_files:
            remaining = [f for f in all_excel_files if f not in selected]
            selected.extend(remaining[:args.limit_files - len(selected)])
        
        excel_files = selected[:args.limit_files]
        logger.info(f"Limited to {len(excel_files)} files (--limit-files={args.limit_files})")
        logger.info(f"Selected files: {[f.name for f in excel_files]}")
    else:
        excel_files = all_excel_files
    
    logger.info(f"Found {len(excel_files)} Excel files in {data_dir}")
    
    # Process all files
    all_test_cases = []
    unknown_files = []
    
    logger.info(f"Processing {len(excel_files)} files...")
    for i, filepath in enumerate(excel_files, 1):
        logger.info(f"[{i}/{len(excel_files)}] Starting {filepath.name}...")
        test_cases = process_file(
            filepath,
            args.samples_per_file,
            args.random_seed,
            unknown_files
        )
        all_test_cases.extend(test_cases)
        logger.debug(f"[{i}/{len(excel_files)}] Completed {filepath.name}")
    
    logger.info(f"Finished processing all files. Total test cases collected: {len(all_test_cases)}")
    
    # Save test cases to YAML
    output_file = args.output
    logger.info(f"Preparing to save {len(all_test_cases)} test cases to {output_file}...")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Writing YAML file (this may take a while for large datasets)...")
    with open(output_file, 'w') as f:
        yaml.dump(
            {'test_cases': all_test_cases},
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    
    logger.info(f"Saved {len(all_test_cases)} test cases to {output_file}")
    
    # Save unknown files for review (always create file, even if empty)
    unknown_output = args.unknown_output
    unknown_output.parent.mkdir(parents=True, exist_ok=True)
    
    with open(unknown_output, 'w') as f:
        if unknown_files:
            logger.info(f"Saving {len(unknown_files)} unknown file types to {unknown_output}...")
            f.write("# Unknown file types - review manually\n\n")
            for unknown in unknown_files:
                f.write(f"## {unknown['filename']}\n\n")
                f.write(f"Headers (first 20):\n")
                for i, header in enumerate(unknown['headers'], 1):
                    f.write(f"  {i}. {header}\n")
                f.write(f"\nSample rows (first 10 columns):\n")
                for i, row in enumerate(unknown['sample_rows'], 2):
                    f.write(f"  Row {i}:\n")
                    for key, value in row.items():
                        f.write(f"    {key}: {value}\n")
                f.write("\n")
            logger.warning(f"\nFound {len(unknown_files)} unknown file types - saved to {unknown_output}")
            logger.warning("Please review and update detect_file_type() if needed")
        else:
            f.write("# Unknown file types - review manually\n\n")
            f.write("# No unknown file types found - all files were successfully classified.\n")
            logger.info(f"No unknown file types found - created empty file at {unknown_output}")
    
    # Summary
    perm_count = sum(1 for tc in all_test_cases if tc['plugin_type'] == 'PERM')
    h1b_count = sum(1 for tc in all_test_cases if tc['plugin_type'] == 'H1B')
    
    logger.info(f"\nSummary:")
    logger.info(f"  Total test cases: {len(all_test_cases)}")
    logger.info(f"  PERM cases: {perm_count}")
    logger.info(f"  H1B cases: {h1b_count}")
    logger.info(f"  Unknown files: {len(unknown_files)}")
    logger.info(f"\nNext steps:")
    logger.info(f"  1. Review and manually annotate expected results in {output_file}")
    logger.info(f"  2. Add record_type, expected_result, expected_error fields to each test case")
    logger.info(f"  3. Run golden test: bazel test //tests:test_dol_transform_golden")


if __name__ == '__main__':
    main()

