"""DOL PERM data source plugin with openpyxl streaming"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from django.db import IntegrityError

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.utils.excel_utils import read_excel_streaming
from lib.ingest.plugins.salary_validation import validate_salary_records_post_ingest
from models.salary import SalaryRecord
from models.ingest.enums import DataDomain, SourceType, FormatVersion
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.salary import SalaryRecord, Employer
from models.enums.visa_program import VisaProgram
from lib.parsing.salary.db_importer import (
    PERM_COLUMN_MAPPINGS,
    get_column_value,
    parse_date,
    parse_decimal,
    get_fiscal_year_from_filename,
    _parse_wage_info,
    _parse_case_info,
    _create_salary_record,
)
from lib.utils.data_source_utils import get_fiscal_year_from_datasource
from lib.utils.http_utils import download_file, get_workspace_dir, fetch_page

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmployerCacheEntry:
    """Cached employer metadata for fast lookup."""

    employer_id: int
    has_cluster: bool


class PERMSalaryDataSourcePlugin(DataSourcePlugin):
    """Plugin for Department of Labor PERM (Permanent Labor Certification) salary disclosure data"""
    
    domain = DataDomain.DOL
    source_type = SourceType.PERM
    data_dir = 'salary/dol_data'  # Override default data directory
    filename_prefix = 'perm'
    
    def __init__(self, skip_clustering: bool = False, case_number_whitelist: set[str] | None = None):
        """
        Initialize plugin with employer cache
        
        Args:
            skip_clustering: If True, skip employer clustering (faster for re-imports)
            case_number_whitelist: If provided, only ingest records matching these case numbers
        """
        self._employer_cache = {}
        self._employer_cache_loaded = False
        self._current_run = None
        self.skip_clustering = skip_clustering
        self.case_number_whitelist = (
            {case.strip().upper() for case in case_number_whitelist}
            if case_number_whitelist
            else None
        )

    def _load_employer_cache(self) -> None:
        """Preload employers to avoid per-record lookups."""
        if self._employer_cache_loaded:
            return

        logger.info("Preloading employer cache for PERM ingest.")
        employer_qs = Employer.objects.values_list(
            'name_normalized',
            'city',
            'state',
            'id',
            'canonical_cluster_id',
        ).iterator(chunk_size=10000)

        for name_normalized, city, state, employer_id, cluster_id in employer_qs:
            employer_key = (name_normalized, city or '', state or '')
            self._employer_cache[employer_key] = EmployerCacheEntry(
                employer_id=employer_id,
                has_cluster=bool(cluster_id),
            )

        self._employer_cache_loaded = True
        logger.info("Loaded %s employers into cache.", len(self._employer_cache))
    
    def discover_sources(self) -> list[SourceInfo]:
        """Discover new PERM data sources from DOL website"""
        sources = []
        base_url = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
        
        try:
            html = fetch_page(base_url)
            
            # Find all PERM disclosure data links
            pattern = r'href=["\']([^"\']*PERM[^"\']*\.(?:xlsx|csv|XLSX|CSV))["\']'
            matches = re.findall(pattern, html, re.IGNORECASE)
            
            for match in matches:
                if match.startswith('http'):
                    url = match
                else:
                    url = f"{base_url}/{match.lstrip('/')}"
                
                fiscal_year_match = re.search(r'FY(\d{4})', match, re.IGNORECASE)
                if fiscal_year_match:
                    fiscal_year = int(fiscal_year_match.group(1))
                    # DOL formats: pre-2015 vs post-2015 (adjust based on actual format changes)
                    if fiscal_year < 2015:
                        format_version = FormatVersion.LEGACY
                    else:
                        format_version = FormatVersion.MODERN
                else:
                    format_version = FormatVersion.UNKNOWN
                
                sources.append(SourceInfo(
                    url=url,
                    domain=self.domain.value,
                    source_type=self.source_type.value,
                    format_version=format_version,
                    metadata={'discovered_from': base_url}
                ))
            
            logger.info(f"Discovered {len(sources)} PERM data sources")
        except Exception as e:
            logger.error(f"Failed to discover PERM sources: {e}")
        
        return sources
    
    # download() method inherited from DataSourcePlugin base class
    # Uses data_dir='salary/dol_data' and filename_prefix='perm'
    
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream parse Excel/CSV file using openpyxl for Excel"""
        self._current_run = run
        
        # Get fiscal year using sophisticated extraction that handles artificial filenames, file:// URLs,
        # reimport:// URLs, alternative DataSources, IngestRun checkpoints, and metadata
        if run.source:
            fiscal_year = get_fiscal_year_from_datasource(filepath.name, run.source, logger_instance=logger)
        else:
            # Fallback to basic extraction if no DataSource available
            fiscal_year = get_fiscal_year_from_filename(filepath.name)
        source_file = filepath.name
        
        if filepath.suffix.lower() in ['.xlsx', '.xls']:
            for record in self._parse_excel_streaming(filepath, run):
                record['_fiscal_year'] = fiscal_year
                record['_source_file'] = source_file
                yield record
        else:
            for record in self._parse_csv_streaming(filepath, run):
                record['_fiscal_year'] = fiscal_year
                record['_source_file'] = source_file
                yield record
    
    def _parse_excel_streaming(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream Excel file using openpyxl"""
        logger.info(f"[Run {run.id}] Parsing Excel with openpyxl streaming: {filepath.name}")
        
        start_row = run.checkpoint.get('last_row', 0) + 2
        if start_row > 2:
            logger.info(f"[Run {run.id}] Resuming Excel parse from row {start_row}")
        
        row_count = 0
        for row_num, record in enumerate(read_excel_streaming(filepath, start_row=start_row), start=start_row):
            row_count += 1
            
            if row_count % 10000 == 0:
                run.checkpoint['last_row'] = row_num - 1
                run.save(update_fields=['checkpoint'])
            
            yield record
        
        logger.info(f"[Run {run.id}] Finished parsing {row_count:,} rows from Excel")
    
    def _parse_csv_streaming(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream CSV file"""
        import csv
        
        logger.info(f"[Run {run.id}] Parsing CSV: {filepath.name}")
        start_row = run.checkpoint.get('last_row', 0)
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            
            for _ in range(start_row):
                try:
                    next(reader)
                except StopIteration:
                    break
            
            row_count = start_row
            for row in reader:
                row_count += 1
                if row_count % 10000 == 0:
                    run.checkpoint['last_row'] = row_count - 1
                    run.save(update_fields=['checkpoint'])
                yield row
        
        logger.info(f"[Run {run.id}] Finished parsing {row_count:,} rows from CSV")
    
    def transform(self, record: dict) -> SalaryRecord | None:
        """Transform raw record into SalaryRecord model
        
        Skips records without required data:
        - Must have case_number
        - Must have employer_name (not empty/None)
        - Must have job_title (not empty/None/"Unknown")
        - Must have salary data (wage_from and wage_unit, or wage_annual)
        
        Note:
            Non-plugin-specific errors (ImportError, configuration issues, etc.) should
            propagate to the framework. The orchestrator handles exceptions and decides
            whether to continue processing or abort the run.
        """
        column_mappings = PERM_COLUMN_MAPPINGS
        
        case_number = get_column_value(record, column_mappings['case_number'])
        if not case_number:
            return None
        case_number_value = str(case_number).strip().upper()
        if self.case_number_whitelist and case_number_value.upper() not in self.case_number_whitelist:
            return None
        
        # Parse employer info - REQUIRED for salary records
        employer_name_raw = get_column_value(record, column_mappings['employer_name'])
        if (
            not employer_name_raw
            or employer_name_raw.strip() == ''
            or employer_name_raw.strip().lower() == 'unknown'
        ):
            # Skip records without employer name (required for salary records)
            logger.debug(f"Skipping record {case_number_value}: missing employer_name")
            return None
        
        employer_name = employer_name_raw.strip()
        employer_city = get_column_value(record, column_mappings['employer_city']) or ''
        employer_state = get_column_value(record, column_mappings['employer_state']) or ''
        
        employer_key = (Employer.normalize_name(employer_name), employer_city, employer_state)
        self._load_employer_cache()

        if employer_key not in self._employer_cache:
            try:
                employer = Employer.objects.create(
                    name=employer_name,
                    name_normalized=employer_key[0],
                    city=employer_key[1],
                    state=employer_key[2],
                )
            except IntegrityError:
                logger.error(
                    "Employer insert failed for %s; falling back to lookup.",
                    employer_key,
                    exc_info=True,
                )
                employer = Employer.objects.get(
                    name_normalized=employer_key[0],
                    city=employer_key[1],
                    state=employer_key[2],
                )

            # Assign to cluster (skip during re-import for performance)
            if not self.skip_clustering and not employer.canonical_cluster:
                from lib.business.salary.employer_clustering import assign_to_cluster

                assign_to_cluster(employer)

            self._employer_cache[employer_key] = EmployerCacheEntry(
                employer_id=employer.id,
                has_cluster=bool(employer.canonical_cluster),
            )

            employer_instance = employer
        else:
            cache_entry = self._employer_cache[employer_key]
            if not self.skip_clustering and not cache_entry.has_cluster:
                from lib.business.salary.employer_clustering import assign_to_cluster

                employer_instance = Employer.objects.get(id=cache_entry.employer_id)
                assign_to_cluster(employer_instance)
                self._employer_cache[employer_key] = EmployerCacheEntry(
                    employer_id=employer_instance.id,
                    has_cluster=bool(employer_instance.canonical_cluster),
                )
            else:
                employer_instance = Employer(id=cache_entry.employer_id)
        
        job_title_raw = get_column_value(record, column_mappings['job_title'])
        if not job_title_raw or job_title_raw.strip() == '' or job_title_raw.strip().lower() == 'unknown':
            logger.debug(f"Skipping record {case_number}: missing job_title")
            return None
        job_title = job_title_raw.strip()

        wage_from, wage_to, wage_unit, wage_annual = _parse_wage_info(
            record, column_mappings, 0
        )
        
        # REQUIRED: Salary records must have salary data (wage_from and wage_unit, or wage_annual)
        # Skip records without any salary information
        if not wage_from and not wage_annual:
            logger.debug(f"Skipping record {case_number_value}: missing salary data (no wage_from or wage_annual)")
            return None
        
        case_status, case_submitted, decision_date, employment_start, employment_end, prevailing_wage, prevailing_wage_unit = _parse_case_info(
            record, column_mappings
        )
        
        fiscal_year = record.get('_fiscal_year', 0)
        source_file = record.get('_source_file', '')
        
        if not fiscal_year:
            fiscal_year = get_fiscal_year_from_filename(self._current_run.checkpoint.get('filepath', '')) if self._current_run else 0
        
        salary_record = _create_salary_record(
            record, column_mappings, case_number_value, VisaProgram.PERM, employer_instance, employer_name, job_title,
            wage_from, wage_to, wage_unit, wage_annual,
            case_status, case_submitted, decision_date, employment_start, employment_end,
            prevailing_wage, prevailing_wage_unit, fiscal_year, source_file
        )
        
        return salary_record
    
    def get_format_version(self, filepath: Path) -> str:
        """
        Detect format version from filename.
        
        Returns:
            FormatVersion enum value ('legacy', 'modern', or 'unknown')
        """
        from models.ingest.enums import FormatVersion
        
        fiscal_year_match = re.search(r'FY(\d{4})', filepath.name, re.IGNORECASE)
        if fiscal_year_match:
            fiscal_year = int(fiscal_year_match.group(1))
            # DOL formats: pre-2015 vs post-2015 (adjust based on actual format changes)
            if fiscal_year < 2015:
                return FormatVersion.LEGACY
            else:
                return FormatVersion.MODERN
        
        # Try to extract fiscal year from filename
        from lib.utils.data_source_utils import get_fiscal_year_from_filename as get_fy
        fiscal_year = get_fy(filepath.name)
        if fiscal_year is not None:
            if fiscal_year < 2015:
                return FormatVersion.LEGACY
            else:
                return FormatVersion.MODERN
        
        return FormatVersion.UNKNOWN
    
    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        """Validate PERM data after ingestion using shared validation logic"""
        return validate_salary_records_post_ingest(
            run=run,
            visa_program=VisaProgram.PERM,
            program_name="PERM"
        )
