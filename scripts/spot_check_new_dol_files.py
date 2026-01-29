#!/usr/bin/env python3
"""
Spot-check new DOL files to verify they have the same structure as old files.

Downloads a few sample files from new URL structure and compares columns.
"""

import os
import sys
import logging
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from pathlib import Path
import openpyxl
from lib.utils.http_utils import download_file, compute_file_hash, get_workspace_dir
from models.ingest.data_source import DataSource
from models.salary import SalaryRecord

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


def download_and_check_file(url: str, expected_type: str = 'LCA'):
    """Download file and spot-check its structure"""
    logger.info(f"\n{'='*80}")
    logger.info(f"Checking {expected_type} file: {url}")
    logger.info(f"{'='*80}")
    
    workspace_dir = get_workspace_dir()
    temp_dir = workspace_dir / 'data' / 'temp_spot_check'
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    filename = Path(url).name
    dest_path = temp_dir / filename
    
    # Download if not already cached
    if not dest_path.exists():
        logger.info("Downloading...")
        download_file(url, dest_path)
    else:
        logger.info("Using cached file")
    
    # Compute hash
    content_hash = compute_file_hash(dest_path)
    logger.info(f"Content hash: {content_hash}")
    
    # Check if this hash already exists in DB (duplicate content)
    existing_sources = list(DataSource.objects.filter(content_hash=content_hash))
    if existing_sources:
        logger.warning(f"⚠️  DUPLICATE CONTENT - {len(existing_sources)} existing source(s) with same hash:")
        for src in existing_sources:
            logger.warning(f"  - {src.url}")
        logger.warning("  → This file is already ingested under a different URL")
        return
    
    # Parse first few rows to check structure
    logger.info("Parsing first 5 rows to check structure...")
    
    try:
        wb = openpyxl.load_workbook(dest_path, read_only=True)
        ws = wb.active
        
        # Get header row
        rows_iter = ws.iter_rows(values_only=True)
        header = next(rows_iter)
        
        # Get first 5 data rows
        rows = []
        for i, row_values in enumerate(rows_iter):
            row_dict = {header[j]: row_values[j] for j in range(len(header))}
            rows.append(row_dict)
            if i >= 4:  # Get first 5 rows
                break
        
        if not rows:
            logger.error("❌ No rows found in file!")
            wb.close()
            return
        
        # Show columns
        first_row = rows[0]
        logger.info(f"\nFound {len(first_row)} columns:")
        for key in list(first_row.keys())[:20]:  # Show first 20 columns
            value = first_row.get(key, '')
            if value and len(str(value)) > 50:
                value = str(value)[:50] + "..."
            logger.info(f"  - {key}: {value}")
        
        if len(first_row) > 20:
            logger.info(f"  ... and {len(first_row) - 20} more columns")
        
        # Check key columns expected for LCA/PERM
        expected_lca_columns = [
            'CASE_NUMBER', 'CASE_STATUS', 'EMPLOYER_NAME', 'JOB_TITLE',
            'PREVAILING_WAGE', 'PW_UNIT_OF_PAY', 'WAGE_RATE_OF_PAY_FROM',
            'WAGE_UNIT_OF_PAY', 'WORKSITE_CITY', 'WORKSITE_STATE'
        ]
        
        expected_perm_columns = [
            'CASE_NUMBER', 'CASE_STATUS', 'EMPLOYER_NAME', 'JOB_TITLE',
            'PW_AMOUNT', 'PW_UNIT_OF_PAY', 'WAGE_OFFER_FROM',
            'WAGE_OFFER_UNIT_OF_PAY_9089', 'WORKSITE_CITY', 'WORKSITE_STATE'
        ]
        
        expected_cols = expected_lca_columns if expected_type == 'LCA' else expected_perm_columns
        
        missing_cols = [col for col in expected_cols if col not in first_row]
        if missing_cols:
            logger.error(f"❌ MISSING EXPECTED COLUMNS: {missing_cols}")
            logger.error("   File structure may have changed!")
        else:
            logger.info(f"✅ All expected {expected_type} columns present")
        
        # Show sample data from first row
        logger.info("\nSample data from first record:")
        for key in expected_cols[:5]:
            if key in first_row:
                logger.info(f"  {key}: {first_row[key]}")
        
        wb.close()
        
    except Exception as e:
        logger.error(f"❌ Error parsing file: {e}", exc_info=True)


def main():
    # Sample new DOL URLs to check
    # These are from the newly discovered sources (with new URL structure)
    
    logger.info("="*80)
    logger.info("SPOT-CHECKING NEW DOL FILE STRUCTURE")
    logger.info("="*80)
    
    # Check a few recent LCA files (new URL structure)
    lca_samples = [
        "https://www.dol.gov/agencies/eta/foreign-labor/performance/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2024_Q4.xlsx",
        "https://www.dol.gov/agencies/eta/foreign-labor/performance/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2024_Q1.xlsx",
    ]
    
    # Check a recent PERM file (new URL structure)
    perm_samples = [
        "https://www.dol.gov/agencies/eta/foreign-labor/performance/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY2024.xlsx",
    ]
    
    for url in lca_samples:
        try:
            download_and_check_file(url, 'LCA')
        except Exception as e:
            logger.error(f"Failed to check {url}: {e}")
    
    for url in perm_samples:
        try:
            download_and_check_file(url, 'PERM')
        except Exception as e:
            logger.error(f"Failed to check {url}: {e}")
    
    logger.info("\n" + "="*80)
    logger.info("SPOT-CHECK COMPLETE")
    logger.info("="*80)


if __name__ == '__main__':
    main()
