"""DOL H-1B LCA and Worksite data source plugin with openpyxl streaming

Combined plugin that handles both regular LCA files (employer-focused) and worksite files
(location-focused). Routes records to SalaryRecord or WorksiteRecord based on case number prefix.
"""

import logging
import re
from pathlib import Path
from typing import Iterator

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.utils.excel_utils import read_excel_streaming
from lib.ingest.plugins.salary_validation import validate_salary_records_post_ingest
from models.salary import SalaryRecord, WorksiteRecord, Employer
from models.ingest.enums import DataDomain, SourceType, FormatVersion
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.enums.visa_program import VisaProgram, WageUnit, CaseStatus
from lib.parsing.salary.db_importer import (
    LCA_COLUMN_MAPPINGS,
    get_column_value,
    parse_date,
    parse_decimal,
    get_fiscal_year_from_filename,
    _parse_wage_info,
    _parse_case_info,
    _create_salary_record,
)
from lib.parsing.salary.wage_unit_correction import (
    correct_wage_unit,
    calculate_annual_wage,
)
from lib.parsing.salary.file_detection import WORKSITE_COLUMN_MAPPINGS
from lib.utils.http_utils import download_file, get_workspace_dir, fetch_page
from lib.utils.logging_utils import ScriptLogger

logger = logging.getLogger(__name__)


class H1BSalaryDataSourcePlugin(DataSourcePlugin):
    """
    Combined plugin for Department of Labor H-1B LCA and Worksite disclosure data.
    
    Handles both:
    - Regular LCA files (employer-focused) → creates SalaryRecord
    - Worksite files (location-focused) → creates WorksiteRecord
    
    Routes records based on case number prefix:
    - I-200* → WorksiteRecord (worksite case numbers)
    - Other prefixes → SalaryRecord (regular LCA records)
    """
    
    domain = DataDomain.DOL
    source_type = SourceType.LCA
    data_dir = 'salary/dol_data'  # Override default data directory
    filename_prefix = 'lca'
    
    def __init__(self, skip_clustering: bool = False):
        """
        Initialize plugin with employer cache
        
        Args:
            skip_clustering: If True, skip employer clustering (faster for re-imports)
        """
        self._employer_cache = {}
        self._current_run = None  # Track current run for context
        self.skip_clustering = skip_clustering
    
    def discover_sources(self) -> list[SourceInfo]:
        """
        Discover new LCA and worksite data sources from DOL website.
        
        Returns:
            List of SourceInfo objects for discovered sources (both LCA and worksite files)
        """
        sources = []
        base_url = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
        
        try:
            html = fetch_page(base_url)
            
            # Find all LCA disclosure data links
            # Look for patterns like: LCA_Disclosure_Data_FY2024.xlsx, LCA_FY2013.xlsx
            lca_pattern = r'href=["\']([^"\']*LCA[^"\']*\.(?:xlsx|csv|XLSX|CSV))["\']'
            lca_matches = re.findall(lca_pattern, html, re.IGNORECASE)
            
            for match in lca_matches:
                # Skip worksite files (will be handled by worksite pattern)
                if 'worksite' in match.lower():
                    continue
                
                # Make absolute URL if relative
                if match.startswith('http'):
                    url = match
                else:
                    url = f"{base_url}/{match.lstrip('/')}"
                
                # Extract fiscal year from filename
                fiscal_year_match = re.search(r'FY(\d{4})', match, re.IGNORECASE)
                if fiscal_year_match:
                    fiscal_year = int(fiscal_year_match.group(1))
                    format_version = FormatVersion.LEGACY if fiscal_year < 2015 else FormatVersion.MODERN
                else:
                    format_version = FormatVersion.UNKNOWN
                
                sources.append(SourceInfo(
                    url=url,
                    domain=self.domain.value,
                    source_type=self.source_type.value,
                    format_version=format_version,
                    metadata={'discovered_from': base_url}
                ))
            
            # Find all worksite disclosure data links
            # Look for patterns like: LCA_Worksites_FY2024.xlsx
            worksite_pattern = r'href=["\']([^"\']*(?:worksite|worksites)[^"\']*\.(?:xlsx|csv|XLSX|CSV))["\']'
            worksite_matches = re.findall(worksite_pattern, html, re.IGNORECASE)
            
            for match in worksite_matches:
                # Make absolute URL if relative
                if match.startswith('http'):
                    url = match
                else:
                    url = f"{base_url}/{match.lstrip('/')}"
                
                # Extract fiscal year from filename
                fiscal_year_match = re.search(r'FY(\d{4})', match, re.IGNORECASE)
                if fiscal_year_match:
                    fiscal_year = int(fiscal_year_match.group(1))
                    format_version = FormatVersion.LEGACY if fiscal_year < 2015 else FormatVersion.MODERN
                else:
                    format_version = FormatVersion.UNKNOWN
                
                # Use LCA source_type (same plugin handles both)
                sources.append(SourceInfo(
                    url=url,
                    domain=self.domain.value,
                    source_type=self.source_type.value,  # Use LCA source_type
                    format_version=format_version,
                    metadata={'discovered_from': base_url, 'worksite_file': True}
                ))
            
            logger.info(f"Discovered {len(sources)} LCA/worksite data sources ({len(lca_matches)} LCA, {len(worksite_matches)} worksite)")
        except Exception as e:
            logger.error(f"Failed to discover LCA/worksite sources: {e}")
        
        return sources
    
    # download() method inherited from DataSourcePlugin base class
    # Uses data_dir='salary/dol_data' and filename_prefix='lca'
    
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """
        Stream parse Excel/CSV file using openpyxl for Excel (required streaming).
        
        Uses LCA_COLUMN_MAPPINGS which includes all fields (employer + worksite).
        
        Args:
            filepath: Path to file to parse
            run: IngestRun for checkpoint updates
            
        Yields:
            Dictionary records from the file
        """
        # Store run context for transform stage
        self._current_run = run
        
        # Get fiscal year and source file for records
        # Use sophisticated extraction that handles artificial filenames, file:// URLs, reimport:// URLs,
        # alternative DataSources, IngestRun checkpoints, and metadata
        if run.source:
            fiscal_year = get_fiscal_year_from_datasource(filepath.name, run.source, logger_instance=logger)
        else:
            # Fallback to basic extraction if no DataSource available
            fiscal_year = get_fiscal_year_from_filename(filepath.name)
        source_file = filepath.name
        
        if filepath.suffix.lower() in ['.xlsx', '.xls']:
            # Use openpyxl for true streaming (required, not optional)
            for record in self._parse_excel_streaming(filepath, run):
                record['_fiscal_year'] = fiscal_year
                record['_source_file'] = source_file
                yield record
        else:
            # CSV files - use standard CSV reader
            for record in self._parse_csv_streaming(filepath, run):
                record['_fiscal_year'] = fiscal_year
                record['_source_file'] = source_file
                yield record
    
    def _parse_excel_streaming(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream Excel file row-by-row using openpyxl (true streaming)"""
        logger.info(f"[Run {run.id}] Parsing Excel with openpyxl streaming: {filepath.name}")
        
        # Resume from checkpoint if present
        start_row = run.checkpoint.get('last_row', 0) + 2  # +2 for header and 0-indexing
        if start_row > 2:
            logger.info(f"[Run {run.id}] Resuming Excel parse from row {start_row}")
        
        row_count = 0
        for row_num, record in enumerate(read_excel_streaming(filepath, start_row=start_row), start=start_row):
            row_count += 1
            
            # Update checkpoint periodically
            if row_count % 10000 == 0:
                run.checkpoint['last_row'] = row_num - 1
                run.save(update_fields=['checkpoint'])
                logger.debug(f"[Run {run.id}] Parsed {row_count:,} rows")
            
            yield record
        
        logger.info(f"[Run {run.id}] Finished parsing {row_count:,} rows from Excel")
    
    def _parse_csv_streaming(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream CSV file row-by-row"""
        import csv
        
        logger.info(f"[Run {run.id}] Parsing CSV: {filepath.name}")
        
        # Resume from checkpoint if present
        start_row = run.checkpoint.get('last_row', 0)
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            
            # Skip to checkpoint if resuming
            for _ in range(start_row):
                try:
                    next(reader)
                except StopIteration:
                    break
            
            row_count = start_row
            for row in reader:
                row_count += 1
                
                # Update checkpoint periodically
                if row_count % 10000 == 0:
                    run.checkpoint['last_row'] = row_count - 1
                    run.save(update_fields=['checkpoint'])
                
                yield row
        
        logger.info(f"[Run {run.id}] Finished parsing {row_count:,} rows from CSV")
    
    def transform(self, record: dict) -> SalaryRecord | WorksiteRecord | None:
        """
        Transform raw record into SalaryRecord or WorksiteRecord model.
        
        Routes based on case number prefix:
        - I-200* → WorksiteRecord (worksite case numbers)
        - Other prefixes → SalaryRecord (regular LCA records)
        
        Args:
            record: Raw record dictionary from parse stage
            
        Returns:
            SalaryRecord or WorksiteRecord instance, or None if record should be filtered out
            
        Note:
            Non-plugin-specific errors (ImportError, configuration issues, etc.) should
            propagate to the framework. The orchestrator handles exceptions and decides
            whether to continue processing or abort the run.
        """
        column_mappings = LCA_COLUMN_MAPPINGS
        
        # Get case number (required)
        case_number = get_column_value(record, column_mappings['case_number'])
        if not case_number:
            return None
        
        # Route I-200 records to WorksiteRecord
        if case_number.startswith('I-200'):
            return self._transform_to_worksite_record(record, column_mappings)
        else:
            return self._transform_to_salary_record(record, column_mappings)
    
    def _transform_to_salary_record(self, record: dict, column_mappings: dict) -> SalaryRecord | None:
        """Transform record to SalaryRecord (regular LCA records)
        
        Skips records without required data:
        - Must have case_number
        - Must have employer_name (not empty/None)
        - Must have salary data (wage_from and wage_unit, or wage_annual)
        
        Note:
            Non-plugin-specific errors should propagate to the framework.
            The orchestrator handles exceptions and decides whether to continue or abort.
        """
        case_number = get_column_value(record, column_mappings['case_number'])
        if not case_number:
            return None
        
        # Parse employer info - REQUIRED for salary records
        employer_name_raw = get_column_value(record, column_mappings['employer_name'])
        if not employer_name_raw or employer_name_raw.strip() == '':
            # Skip records without employer name (required for salary records)
            logger.debug(f"Skipping record {case_number}: missing employer_name")
            return None
        
        employer_name = employer_name_raw
        employer_city = get_column_value(record, column_mappings['employer_city']) or ''
        employer_state = get_column_value(record, column_mappings['employer_state']) or ''
        
        # Get or create employer (with caching)
        employer_key = (Employer.normalize_name(employer_name), employer_city, employer_state)
        
        if employer_key not in self._employer_cache:
            employer, created = Employer.objects.get_or_create(
                name_normalized=employer_key[0],
                city=employer_key[1],
                state=employer_key[2],
                defaults={'name': employer_name}
            )
            # Assign to cluster only if employer is new or doesn't have a cluster yet
            # Skip clustering for existing employers with clusters (much faster for re-imports)
            # Also skip if skip_clustering=True (for re-imports where clustering already done)
            if not self.skip_clustering and (created or not employer.canonical_cluster):
                from lib.business.salary.employer_clustering import assign_to_cluster
                assign_to_cluster(employer)
            self._employer_cache[employer_key] = employer
        
        employer = self._employer_cache[employer_key]
        
        # Parse wage info (row_num not critical for wage parsing, use 0)
        wage_from, wage_to, wage_unit, wage_annual = _parse_wage_info(
            record, column_mappings, 0
        )
        
        # REQUIRED: Salary records must have salary data (wage_from and wage_unit, or wage_annual)
        # Skip records without any salary information
        if not wage_from and not wage_annual:
            logger.debug(f"Skipping record {case_number}: missing salary data (no wage_from or wage_annual)")
            return None
        
        # Parse case info
        case_status, case_submitted, decision_date, employment_start, employment_end, prevailing_wage, prevailing_wage_unit = _parse_case_info(
            record, column_mappings
        )
        
        # Get fiscal year and source file from record (set during parse)
        fiscal_year = record.get('_fiscal_year', 0)
        source_file = record.get('_source_file', '')
        
        if not fiscal_year:
            # Fallback: try to get from run checkpoint
            fiscal_year = get_fiscal_year_from_filename(self._current_run.checkpoint.get('filepath', '')) if self._current_run else 0
        
        # Create record
        salary_record = _create_salary_record(
            record, column_mappings, case_number, VisaProgram.H1B, employer, employer_name,
            wage_from, wage_to, wage_unit, wage_annual,
            case_status, case_submitted, decision_date, employment_start, employment_end,
            prevailing_wage, prevailing_wage_unit, fiscal_year, source_file
        )
        
        return salary_record
    
    def _transform_to_worksite_record(self, record: dict, column_mappings: dict) -> WorksiteRecord | None:
        """Transform record to WorksiteRecord (I-200 case numbers)
        
        Note:
            Non-plugin-specific errors should propagate to the framework.
            The orchestrator handles exceptions and decides whether to continue or abort.
        """
        case_number = get_column_value(record, column_mappings['case_number'])
        if not case_number:
            return None
        
        # Parse wage info (row_num not critical for wage parsing, use 0)
        wage_from, wage_to, wage_unit, wage_annual = _parse_wage_info(
            record, column_mappings, 0
        )
        
        # Parse case info
        case_status, case_submitted, decision_date, employment_start, employment_end, prevailing_wage, prevailing_wage_unit = _parse_case_info(
            record, column_mappings
        )
        
        # Get fiscal year and source file from record (set during parse)
        fiscal_year = record.get('_fiscal_year', 0)
        source_file = record.get('_source_file', '')
        
        if not fiscal_year:
            # Fallback: try to get from run checkpoint
            fiscal_year = get_fiscal_year_from_filename(self._current_run.checkpoint.get('filepath', '')) if self._current_run else 0
        
        # Determine visa program from case number prefix
        visa_program = VisaProgram.H1B  # Default to H-1B
        if case_number.startswith('P-'):
            visa_program = VisaProgram.PERM
        elif case_number.startswith('I-200'):
            visa_program = VisaProgram.H1B
        
        # Parse worksite location fields (using LCA mappings - works for both)
        worksite_city = get_column_value(record, column_mappings['worksite_city']) or ''
        worksite_state = get_column_value(record, column_mappings['worksite_state']) or ''
        
        # Try to get worksite_zip if available (LCA_COLUMN_MAPPINGS doesn't include zip, but files may have it)
        # Use WORKSITE_COLUMN_MAPPINGS for zip column names
        worksite_zip = get_column_value(record, WORKSITE_COLUMN_MAPPINGS.get('worksite_zip', [])) or ''
        
        # Parse job fields
        job_title = get_column_value(record, column_mappings['job_title']) or ''
        soc_code = get_column_value(record, column_mappings['soc_code']) or ''
        soc_title = get_column_value(record, column_mappings['soc_title']) or ''
        
        # Create WorksiteRecord
        worksite_record = WorksiteRecord(
            case_number=case_number,
            visa_program=visa_program,
            case_status=case_status,
            worksite_city=worksite_city,
            worksite_state=worksite_state,
            worksite_zip=worksite_zip,
            job_title=job_title,
            soc_code=soc_code,
            soc_title=soc_title,
            wage_from=wage_from,
            wage_to=wage_to,
            wage_unit=wage_unit or '',
            wage_annual=wage_annual,
            prevailing_wage=prevailing_wage,
            prevailing_wage_unit=prevailing_wage_unit or '',
            case_submitted=case_submitted,
            decision_date=decision_date,
            employment_start=employment_start,
            employment_end=employment_end,
            fiscal_year=fiscal_year,
            source_file=source_file,
        )
        
        # Note: ingest_version is not set here (IngestRun doesn't have ingest_version attribute)
        # If needed in the future, it should be set via versioning.create_version() after the run completes
        
        return worksite_record
    
    def get_format_version(self, filepath: Path) -> FormatVersion:
        """
        Detect format version from filename or file structure.
        
        Args:
            filepath: Path to file
            
        Returns:
            FormatVersion enum value
        """
        
        fiscal_year_match = re.search(r'FY(\d{4})', filepath.name, re.IGNORECASE)
        if fiscal_year_match:
            fiscal_year = int(fiscal_year_match.group(1))
            # DOL formats: pre-2015 vs post-2015 (adjust based on actual format changes)
            if fiscal_year < 2015:
                return FormatVersion.LEGACY
            else:
                return FormatVersion.MODERN
        
        # Fallback: try to extract fiscal year from filename using utility
        from lib.utils.data_source_utils import get_fiscal_year_from_filename
        fiscal_year = get_fiscal_year_from_filename(filepath.name)
        if fiscal_year is not None:
            if fiscal_year < 2015:
                return FormatVersion.LEGACY
            else:
                return FormatVersion.MODERN
        
        return FormatVersion.UNKNOWN
    
    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        """
        Validate both SalaryRecord and WorksiteRecord data after ingestion.
        
        Validates both model types since the plugin creates both.
        Files can legitimately contain only one type (e.g., only I-200 records → only WorksiteRecord).
        """
        errors = []
        warnings = []
        
        # Validate SalaryRecords
        salary_result = validate_salary_records_post_ingest(
            run=run,
            visa_program=VisaProgram.H1B,
            program_name="H-1B LCA",
            model_class=SalaryRecord
        )
        # Only treat SalaryRecord errors as fatal if there are also no WorksiteRecords
        # (files can legitimately contain only I-200 records)
        salary_errors = salary_result.errors.copy() if salary_result.errors else []
        if salary_result.warnings:
            warnings.extend(salary_result.warnings)
        
        # Validate WorksiteRecords
        worksite_result = validate_salary_records_post_ingest(
            run=run,
            visa_program=VisaProgram.H1B,
            program_name="Worksite",
            model_class=WorksiteRecord
        )
        worksite_errors = worksite_result.errors.copy() if worksite_result.errors else []
        if worksite_result.warnings:
            warnings.extend(worksite_result.warnings)
        
        # Check if we have records in at least one model type
        salary_count = salary_result.details.get('records_created', 0) if salary_result.details else 0
        worksite_count = worksite_result.details.get('records_created', 0) if worksite_result.details else 0
        total_records = salary_count + worksite_count
        
        # Only fail if NO records were created at all (both models empty)
        if total_records == 0:
            source_file = salary_result.details.get('source_file') if salary_result.details else None
            errors.append(
                f"No records created from source file '{source_file}' - expected data but got none "
                f"(checked both SalaryRecord and WorksiteRecord)"
            )
        else:
            # If we have records in at least one model, don't treat missing records in the other as errors
            # (files can contain only one type)
            if salary_count == 0 and salary_errors:
                # File contains only worksite records - this is OK, convert error to warning
                warnings.append(
                    f"File contains only WorksiteRecord entries ({worksite_count:,} records), "
                    f"no SalaryRecord entries. This is expected for worksite-only files."
                )
            elif worksite_count == 0 and worksite_errors:
                # File contains only salary records - this is OK, convert error to warning
                warnings.append(
                    f"File contains only SalaryRecord entries ({salary_count:,} records), "
                    f"no WorksiteRecord entries. This is expected for regular LCA files."
                )
            else:
                # Both have records or both have errors - keep original errors
                errors.extend(salary_errors)
                errors.extend(worksite_errors)
        
        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            details={
                'salary_records': salary_result.details or {},
                'worksite_records': worksite_result.details or {},
                'total_records': total_records
            }
        )
