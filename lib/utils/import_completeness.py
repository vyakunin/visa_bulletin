"""
Import completeness validation utilities.

Provides functions to compare raw file row counts with database record counts,
both per-file and per-year. Logic is separated from scripts for testability.

Usage:
    from lib.utils.import_completeness import (
        compare_file_counts,
        compare_counts_by_year,
        get_db_counts_by_year,
        FileComparisonResult,
        YearComparisonResult,
    )
    
    # Per-file comparison
    results = compare_file_counts(data_dir, db_counts)
    
    # Per-year comparison (returns only years with >5% discrepancy by default)
    results = compare_counts_by_year(data_dir, db_counts_by_year)
    
    # To get ALL years (including those with <5% discrepancy), use get_db_counts_by_year()
    # and manually group files by year, or use validate_data.py which shows all years.
    
    # Get per-year data via validate_data script:
    # bazel run //scripts/salary:validate_data -- --check-import-completeness
    # This shows both per-file and per-year comparison tables.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lib.utils.data_source_utils import count_file_rows, get_fiscal_year_from_filename
from lib.utils.excel_utils import read_excel_streaming
from lib.parsing.salary.file_detection import is_worksite_file
from models.salary import SalaryRecord, WorksiteRecord
from django.db.models import Count
import csv


@dataclass
class FileComparisonResult:
    """Result of comparing a single file's row count to DB records"""
    filename: str
    file_rows: int
    db_records: int
    discrepancy: int
    discrepancy_pct: float
    by_program: dict[int, int]  # visa_program -> count
    reason: Optional[str] = None  # Reason for missing records (e.g., "all_duplicates", "worksite_file", "not_imported")


@dataclass
class YearComparisonResult:
    """Result of comparing file rows to DB records for a fiscal year"""
    fiscal_year: int
    file_rows: int
    db_records: int
    difference: int
    difference_pct: float
    files: list[str]  # List of filenames in this year


def get_file_record_counts() -> dict[str, dict]:
    """
    Get record counts per file from database.
    
    Includes both SalaryRecord and WorksiteRecord (worksite files create WorksiteRecord entries).
    
    Returns:
        Dict mapping filename to {'total': int, 'by_program': {visa_program: count}}
    """
    result = {}
    
    # Get SalaryRecord counts
    salary_counts = (
        SalaryRecord.objects
        .values('source_file', 'visa_program')
        .annotate(count=Count('id'))
    )
    
    for item in salary_counts:
        source_file = item['source_file']
        if not source_file:  # Skip empty source_file
            continue
        if source_file not in result:
            result[source_file] = {
                'total': 0,
                'by_program': {}
            }
        result[source_file]['total'] += item['count']
        result[source_file]['by_program'][item['visa_program']] = result[source_file]['by_program'].get(item['visa_program'], 0) + item['count']
    
    # Get WorksiteRecord counts (worksite files create WorksiteRecord entries)
    worksite_counts = (
        WorksiteRecord.objects
        .values('source_file', 'visa_program')
        .annotate(count=Count('id'))
    )
    
    for item in worksite_counts:
        source_file = item['source_file']
        if not source_file:  # Skip empty source_file
            continue
        if source_file not in result:
            result[source_file] = {
                'total': 0,
                'by_program': {}
            }
        result[source_file]['total'] += item['count']
        result[source_file]['by_program'][item['visa_program']] = result[source_file]['by_program'].get(item['visa_program'], 0) + item['count']
    
    return result


def get_db_counts_by_year() -> dict[int, int]:
    """
    Get database record counts grouped by fiscal year.
    
    Returns:
        Dict mapping fiscal_year to record count (includes both SalaryRecord and WorksiteRecord)
    """
    db_by_year = {}
    
    # Get SalaryRecord counts by year
    salary_by_year = (
        SalaryRecord.objects
        .values('fiscal_year')
        .annotate(count=Count('id'))
        .order_by('fiscal_year')
    )
    for item in salary_by_year:
        fy = item['fiscal_year']
        if fy is not None:
            db_by_year[fy] = db_by_year.get(fy, 0) + item['count']
    
    # Get WorksiteRecord counts by year
    worksite_by_year = (
        WorksiteRecord.objects
        .values('fiscal_year')
        .annotate(count=Count('id'))
        .order_by('fiscal_year')
    )
    for item in worksite_by_year:
        fy = item['fiscal_year']
        if fy is not None:
            db_by_year[fy] = db_by_year.get(fy, 0) + item['count']
    
    return db_by_year


def _analyze_missing_records_reason(
    filepath: Path,
    filename: str,
    file_rows: int,
    db_count: int
) -> Optional[str]:
    """
    Analyze why records from a file are missing from the database.
    
    Checks for:
    - All records are duplicates (case_numbers already exist in DB)
    - Worksite file (should create WorksiteRecord, not SalaryRecord)
    - File not imported yet
    
    Args:
        filepath: Path to the file
        filename: Name of the file
        file_rows: Number of rows in the file
        db_count: Number of records in DB for this file
        
    Returns:
        Reason string if identified, None otherwise
    """
    if db_count > 0:
        return None  # Some records exist, not 100% missing
    
    if file_rows == 0:
        return None  # Empty file, no reason to analyze
    
    # Check if it's a worksite file
    if is_worksite_file(filename):
        # Check if records exist in WorksiteRecord (or SalaryRecord if imported there)
        worksite_count = WorksiteRecord.objects.filter(source_file=filename).count()
        salary_count = SalaryRecord.objects.filter(source_file=filename).count()
        total_count = worksite_count + salary_count
        if total_count > 0:
            if worksite_count > 0 and salary_count > 0:
                return f"worksite_file ({worksite_count:,} in WorksiteRecord, {salary_count:,} in SalaryRecord)"
            elif worksite_count > 0:
                return f"worksite_file ({worksite_count:,} in WorksiteRecord)"
            else:
                return f"worksite_file ({salary_count:,} in SalaryRecord)"
        # Worksite file with no records - might not be imported yet
        return "worksite_file_not_imported"
    
    # For files with 100% missing, sample case_numbers to check for duplicates
    # Sample up to 100 case_numbers from the file
    try:
        sample_size = min(100, file_rows)
        case_numbers_sample = []
        case_cols = ['CASE_NUMBER', 'case_number', 'LCA_CASE_NUMBER', 'CASE_NUM']
        
        if filepath.suffix.lower() in ['.xlsx', '.xls']:
            # Read Excel file using existing utilities
            for i, record in enumerate(read_excel_streaming(filepath)):
                if i >= sample_size:
                    break
                # Try common case_number column names
                for col in case_cols:
                    if col in record and record[col]:
                        case_numbers_sample.append(str(record[col]).strip())
                        break
        elif filepath.suffix.lower() == '.csv':
            # Read CSV file
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if i >= sample_size:
                        break
                    # Try common case_number column names
                    for col in case_cols:
                        if col in row and row[col]:
                            case_numbers_sample.append(str(row[col]).strip())
                            break
        
        if case_numbers_sample:
            # Check if these case_numbers exist in DB (from any file) - check BOTH tables
            salary_existing = SalaryRecord.objects.filter(
                case_number__in=case_numbers_sample
            ).values_list('case_number', flat=True)
            worksite_existing = WorksiteRecord.objects.filter(
                case_number__in=case_numbers_sample
            ).values_list('case_number', flat=True)
            
            # Combine both sets (case_numbers can exist in either table)
            existing_case_numbers = set(salary_existing) | set(worksite_existing)
            existing_count = len(existing_case_numbers)
            
            if existing_count == len(case_numbers_sample):
                # All sampled case_numbers exist - likely all duplicates
                return f"all_duplicates (sampled {len(case_numbers_sample)}/{file_rows:,})"
            elif existing_count > len(case_numbers_sample) * 0.9:
                # >90% are duplicates - likely all duplicates
                return f"mostly_duplicates ({existing_count}/{len(case_numbers_sample)} sampled exist)"
    except Exception:
        # If we can't analyze, return None (unknown reason)
        pass
    
    return None


def compare_file_counts(
    data_dir: Path,
    db_counts: Optional[dict[str, dict]] = None,
    min_discrepancy_threshold: int = 100,
    min_discrepancy_pct: float = 1.0,
    return_all: bool = False
) -> list[FileComparisonResult]:
    """
    Compare file row counts to database record counts per file.
    
    Args:
        data_dir: Directory containing data files
        db_counts: Pre-computed DB counts (if None, will fetch from DB)
        min_discrepancy_threshold: Minimum absolute discrepancy to report (only used if return_all=False)
        min_discrepancy_pct: Minimum percentage discrepancy to report (only used if return_all=False)
        return_all: If True, return all files regardless of discrepancy threshold
    
    Returns:
        List of FileComparisonResult for files (all files if return_all=True, otherwise only significant discrepancies)
    """
    if db_counts is None:
        db_counts = get_file_record_counts()
    
    data_files = list(data_dir.glob('*.xlsx')) + list(data_dir.glob('*.csv'))
    results = []
    
    for filepath in sorted(data_files):
        filename = filepath.name
        
        # Count rows in file (with caching for performance)
        file_rows = count_file_rows(filepath)
        if file_rows is None:
            continue
        
        # Get database count
        db_count = db_counts.get(filename, {}).get('total', 0)
        by_program = db_counts.get(filename, {}).get('by_program', {})
        
        # Calculate discrepancy
        discrepancy = file_rows - db_count
        discrepancy_pct = (discrepancy / file_rows * 100) if file_rows > 0 else 0
        
        # Include all files if return_all=True, otherwise only significant discrepancies
        include_file = True
        if not return_all:
            include_file = abs(discrepancy) >= min_discrepancy_threshold or abs(discrepancy_pct) >= min_discrepancy_pct
        
        if include_file:
            # Analyze reason for missing records (if 100% missing)
            reason = None
            if db_count == 0 and file_rows > 0:
                reason = _analyze_missing_records_reason(filepath, filename, file_rows, db_count)
            
            results.append(FileComparisonResult(
                filename=filename,
                file_rows=file_rows,
                db_records=db_count,
                discrepancy=discrepancy,
                discrepancy_pct=discrepancy_pct,
                by_program=by_program,
                reason=reason
            ))
    
    # Sort by absolute discrepancy (largest first)
    results.sort(key=lambda x: abs(x.discrepancy), reverse=True)
    
    return results


def compare_counts_by_year(
    data_dir: Path,
    db_counts_by_year: Optional[dict[int, int]] = None,
    min_discrepancy_pct: float = 5.0
) -> list[YearComparisonResult]:
    """
    Compare file row counts to database record counts grouped by fiscal year.
    
    Args:
        data_dir: Directory containing data files
        db_counts_by_year: Pre-computed DB counts by year (if None, will fetch from DB)
        min_discrepancy_pct: Minimum percentage discrepancy to report
    
    Returns:
        List of YearComparisonResult for years with significant discrepancies
    """
    if db_counts_by_year is None:
        db_counts_by_year = get_db_counts_by_year()
    
    # Group files by fiscal year
    files_by_year: dict[int, list[tuple[Path, int]]] = defaultdict(list)
    
    xlsx_files = list(data_dir.glob('**/*.xlsx'))
    for file_path in xlsx_files:
        rows = count_file_rows(file_path)
        if rows is None:
            continue
        
        # Extract fiscal year from filename
        fiscal_year = get_fiscal_year_from_filename(file_path.name)
        if fiscal_year is None:
            # Skip files without extractable fiscal year (don't use current year as fallback)
            continue
        
        files_by_year[fiscal_year].append((file_path, rows))
    
    # Build comparison results
    all_years = sorted(set(list(files_by_year.keys()) + list(db_counts_by_year.keys())))
    results = []
    
    for year in all_years:
        file_rows = sum(rows for _, rows in files_by_year.get(year, []))
        db_records = db_counts_by_year.get(year, 0)
        
        diff = file_rows - db_records
        diff_pct = (diff / file_rows * 100) if file_rows > 0 else 0
        
        file_names = [f.name for f, _ in files_by_year.get(year, [])]
        
        # Only include if significant discrepancy
        if file_rows > 0 and abs(diff_pct) >= min_discrepancy_pct:
            results.append(YearComparisonResult(
                fiscal_year=year,
                file_rows=file_rows,
                db_records=db_records,
                difference=diff,
                difference_pct=diff_pct,
                files=file_names
            ))
    
    # Sort by fiscal year
    results.sort(key=lambda x: x.fiscal_year)
    
    return results

