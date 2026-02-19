# Library Modules Reference

Concise reference for all modules in `lib/`. Use this to find functionality without scanning code.

## Directory Structure

```
lib/
├── parsing/                    # Parsing and extraction logic
│   ├── bulletin/               # Visa bulletin HTML parsing pipeline
│   └── salary/                 # Salary data parsing (PERM/H1B)
├── business/                   # Domain-specific business logic
│   └── bulletin/               # All business logic is bulletin/cutoff-specific
└── utils/                      # Generic utilities (reusable across projects)
```

All library code is organized in subdirectories following a clear structure:
- `parsing/` - Parsing and extraction logic (bulletin and salary data)
- `business/` - Domain-specific business logic (bulletin/cutoff-specific)
- `utils/` - Generic utilities reusable across projects

## Parsing: Bulletin

### `parsing/bulletin/parser.py`
**Purpose:** Parse visa bulletin HTML pages and extract table data.

**Key functions:**
- `parse_publication_links(html)` - Extract publication URLs from main page
- `extract_tables(html)` - Extract all visa cutoff tables from HTML
- `extract_table(table)` - Parse single table (headers + rows) - modern format (2015+)
- `extract_table_legacy(table)` - Parse single table - legacy format (2001-2015)
- `normalize(text)` - Clean whitespace and normalize text (handles multi-line HTML)
- `convert_to_date(value)` - Parse date strings (DDMmmYY format)

**Table extraction behavior:**
- **Modern parser:** Explicitly extracts headers from first `<tr>`, normalizes them, processes data rows starting from second `<tr>`
- **Legacy parser:** Same explicit header extraction pattern
- Headers are normalized using `normalize()` before being passed to country matching

**Data structures:**
- Returns `BulletinTable` objects (from `bulletin_table.py`)

---

### `parsing/bulletin/bulletin_table.py`
**Purpose:** Data class for parsed visa bulletin tables.

**Class:**
- `BulletinTable(title, headers, rows)` - Simple container for table data
  - `title` (str): Table identifier (e.g., "employment_based_final_action")
  - `headers` (tuple): Column headers (first is visa class, rest are countries)
  - `rows` (list[tuple]): Data rows with date objects or strings

---

### `parsing/bulletin/publication_data.py`
**Purpose:** Data class for visa bulletin publications.

**Class:**
- `PublicationData(url, content, publication_date)` - Container for publication metadata and HTML
  - `url` (str): Full URL to the bulletin page
  - `content` (str): Raw HTML content
  - `publication_date` (datetime): Parsed publication date

---

### `parsing/bulletin/table_to_cutoff_data.py`
**Purpose:** Convert parsed BulletinTable objects to structured VisaCutoffDate dicts.

**Class:**
- `TableToCutoffData(publication_data)` - Extracts structured data from parsed tables
- Accepts either `PublicationData` object or `(date, url)` tuple

**Key methods:**
- `extract_from_table(table)` - Convert BulletinTable to list of dicts ready for database

**Returns:**
- List of dicts with keys: `visa_category`, `visa_class`, `action_type`, `country`, `cutoff_value`, `cutoff_date`, `is_current`, `is_unavailable`

**Important:**
- Uses `Country.from_header()` to match country headers
- **Critical:** Checks `if country is None:` (not `if not country:`) because IntegerChoices can have value 0 which is falsy
- Logs warnings when country headers cannot be matched

---

### `parsing/bulletin/db_importer.py`
**Purpose:** Save parsed bulletins to database (complete pipeline).

**Key functions:**
- `save_bulletin_to_db(publication_data)` - Main function: parse → extract → save to database

**Pipeline:**
1. Create or get Bulletin record
2. Extract data from all tables
3. Save VisaCutoffDate records (idempotent)

---

## Parsing: Salary

### `parsing/salary/db_importer.py`
**Purpose:** Import DOL PERM/LCA salary data from CSV/Excel files.

**Key functions:**
- `import_csv_file(filepath, visa_program, batch_size, skip_existing)` - Main import function
- `update_employer_stats()` - Update aggregated employer statistics
- `get_fiscal_year_from_filename(filename)` - Extract FY from filename
- `parse_date(date_str)` - Parse various date formats
- `parse_decimal(value)` - Parse currency/decimal values

**Column mappings:**
- `LCA_COLUMN_MAPPINGS` - H-1B/LCA file column names
- `PERM_COLUMN_MAPPINGS` - PERM file column names

**Features:**
- Supports CSV and Excel (.xlsx, .xls)
- Batch processing for performance
- Wage unit correction (detects incorrect units)
- Employer normalization and caching

---

### `parsing/salary/wage_unit_correction.py`
**Purpose:** Shared wage unit correction logic for import and fix routines.

**Key functions:**
- `correct_wage_unit(wage_from, wage_unit, row_num, wage_annual)` - Correct wage unit if value suggests it's actually annual
- `should_correct_wage_unit(wage_from, wage_unit, wage_annual)` - Determine if correction is needed
- `calculate_annual_wage(wage_from, wage_unit)` - Calculate annual wage from wage_from and wage_unit

**Features:**
- Detects incorrect wage units (HOUR, WEEK, MONTH, BI_WEEKLY that are actually annual)
- Uses consistent thresholds across import and fix scripts
- Supports implied hourly rate checks (for HOUR unit records)
- Ensures import and fix routines produce identical results

---

## Business Logic: Bulletin

### `business/bulletin/cutoff_data_aggregator.py`
**Purpose:** Business logic for dashboard views. Aggregates visa cutoff data and prepares it for charts.

## Business Logic: Salary

### `business/salary/common_stats.py`
**Purpose:** Shared salary aggregation helpers (percentiles, trends, geographic distributions).

### `business/salary/common_chart_builder.py`
**Purpose:** Shared Plotly chart builders for salary visualizations.

### `business/salary/market_overview.py`
**Purpose:** Market-wide salary overview stats for landing pages.

### `business/salary/` - Employer Clustering Module
**Purpose:** Employer clustering logic for grouping similar employers across name variations and locations.

**See `lib/business/salary/README.md` for comprehensive documentation.**

### `business/salary/` - Job Title Normalization (Implemented)
**Purpose:** Job title normalization and clustering for standardizing job titles across variations and seniority levels.

**Status:** ✅ Core normalization implemented. Models and tests complete.

**Key components:**
- `models/job_title.py` - JobTitle and JobTitleCluster models with normalization logic
- `JobTitle.normalize_title(title)` - Removes seniority indicators, standardizes titles
- `JobTitle.extract_experience_level(title)` - Extracts junior/senior/staff/principal/etc.
- `tests/test_job_title_normalization.py` - Comprehensive test coverage

**Next steps:**
- Backfill existing SalaryRecords with JobTitle entities
- Run clustering to create JobTitleClusters
- Integrate with views for job title profile pages

**Reference:** `docs/department_of_labor/JOB_TITLE_NORMALIZATION_DESIGN.md`

**Key files:**
- `employer_clustering.py` - Core matching algorithm

**Key functions:**
- `match_employers(employer1, employer2)` - Hybrid matching: rule-based checks first (structural words, exact match, substring), then similarity-based fallback (difflib with thresholds)
- `fuzzy_match(employer1, employer2)` - Fuzzy string matching using difflib for similarity scoring
- `should_auto_cluster(employer1, employer2, threshold)` - Determine if two employers should be auto-clustered
- `assign_to_cluster(employer, threshold)` - Find existing cluster or create new one for an employer

**Features:**
- Auto-clusters high-confidence matches (threshold >= 0.95 by default)
- Queues ambiguous matches for human/LLM review
- Handles name variations (e.g., "Google", "Google Inc", "Google LLC")
- Handles cross-location clustering (same employer in different cities/states)
- Uses enhanced normalization for better matching

**Usage:**
```python
from lib.business.salary.employer_clustering import assign_to_cluster
from models.salary import Employer

# Assign employer to cluster (auto-clusters or queues for review)
cluster = assign_to_cluster(employer)
```

**Review queue:**
- Ambiguous matches are stored in `EmployerClusteringReview` model
- Use `scripts/salary/review_clustering.py` to review pending matches
- Supports LLM review (ollama) and human review

---

**Key functions:**
- `get_visa_classes_for_category(category)` - Get visa classes for family/employment category
- `get_aggregated_visa_class_data(category, country, visa_classes)` - Aggregate historical cutoff data
- `build_seo_metadata(category, country, visa_classes)` - Generate SEO metadata

**Data structures:**
- `VisaClassData` - Dataclass with visa class, dates, cutoffs, projections

---

### `business/bulletin/chart_builder.py`
**Purpose:** Build Plotly charts for visa cutoff visualization.

**Key functions:**
- `build_multi_class_chart_with_projections(visa_class_data, submission_date, country, category_label)` - Main chart builder
- `build_chart_with_projection(visa_class, dates, cutoffs, submission_date, country, category_label)` - Single class chart

**Features:**
- Historical cutoff date lines
- Projection lines (future estimates)
- Priority date submission line
- Color-coded visa classes

---

### `business/bulletin/cutoff_projection.py`
**Purpose:** Calculate visa processing timeline projections.

**Key functions:**
- `calculate_projection(dates, cutoff_dates, submission_date)` - Main projection calculator
- `calculate_historical_linear_regression(dates, cutoff_dates)` - Fallback regression method
- `calculate_months_between(start_date, end_date)` - Date utilities
- `add_months_to_date(start_date, months)` - Date arithmetic

**Returns:**
- Dict with `status`, `message`, `estimated_date`, `months_to_wait`, `avg_progress_days_per_month`

---

### `business/bulletin/visa_class_utils.py`
**Purpose:** Handle visa class name variations and normalization.

**Key functions:**
- `get_all_employment_visa_classes_from_db()` - Get all employment classes from DB
- `get_all_family_visa_classes_from_db()` - Get all family classes from DB
- `get_deduplicated_employment_classes()` - Get normalized employment classes
- `normalize_visa_class_for_display(visa_class)` - Normalize class name for UI

**Why needed:**
- Historical data has inconsistent visa class naming
- Handles variations like "EB-2", "EB2", "Employment Second Preference"

---

## Ingest Framework

### `ingest/rejection_tracker.py`
**Purpose:** Track and save record rejection statistics during ingestion for data quality analysis.

**Key class:**
- `RejectionTracker(run)` - Collects rejection counts and sample case numbers per reason

**Key methods:**
- `record_rejection(reason, case_number)` - Record a rejected record with optional case number
- `save_to_db()` - Save collected stats to `IngestRejectionStats` table
- `get_stats()` - Get current rejection statistics (for testing)
- `total_rejections()` - Get total number of rejections

**Usage:**
```python
from lib.ingest.rejection_tracker import RejectionTracker

# Orchestrator creates tracker for each run
tracker = RejectionTracker(run)

# Plugin records rejections during transform
if not employer_name:
    if self._rejection_tracker:
        self._rejection_tracker.record_rejection('missing_employer_name', case_number)
    return None

# Orchestrator saves stats at end of run
tracker.save_to_db()

# Query stats after ingest
for stat in run.rejection_stats.all().order_by('-count'):
    print(f"{stat.get_reason_display()}: {stat.count:,}")
    print(f"  Samples: {stat.sample_case_numbers}")
```

**Common rejection reasons:**
- `missing_case_number` - No case number in record
- `missing_employer_name` - Employer name is null/empty
- `unknown_employer_name` - Employer name is "Unknown"
- `missing_job_title` - Job title is null/empty
- `missing_wage_data` - No wage information

**Benefits:**
- Identify data quality issues and format mismatches
- Track rejection trends across ingests
- Sample case numbers enable investigation of rejected records
- Helps distinguish between missing data vs wrong column mappings

**See also:** `docs/ingest/README.md` for complete rejection tracking documentation.

---

## Utilities

### `utils/http_utils.py`
**Purpose:** Shared HTTP and file system utilities.

**Key functions:**
- `get_workspace_dir()` - Get project root (works in Bazel and non-Bazel)
- `get_data_file_path()` - Access Bazel data dependencies using standard runfiles library
- `get_template_file()` - Convenience wrapper for accessing template files
- `fetch_page(url, timeout)` - Fetch HTML page with caching
- `download_file(url, dest_path, timeout)` - Download file to disk
- `is_file_saved(url, data_dir)` - Check if file already downloaded

**Features:**
- Handles Bazel sandboxing (`BUILD_WORKSPACE_DIRECTORY`)
- Automatic caching (checks local files first)
- Error handling and retries

---

### `utils/logging_utils.py`
**Purpose:** Track script execution for usage analysis.

**Key classes/functions:**
- `ScriptLogger(script_path)` - For permanent scripts (logs to `logs/<script_name>.log`)
- `log_context(context)` - For throwaway scripts (logs to `logs/throwaway_calls.log`)

**Usage:**
```python
# Permanent script
from lib.utils.logging_utils import ScriptLogger
logger = ScriptLogger(__file__)
logger.log_call(args={'query': '...'}, context='Debugging')

# Throwaway script (auto-logs on import)
from lib.utils.logging_utils import log_context
log_context("Debugging salary issue")
```

**Features:**
- Auto-logs throwaway scripts on import
- Captures args and context
- Uses standard `logging` module

---

### `utils/excel_utils.py`
**Purpose:** Reusable utilities for reading Excel files with openpyxl.

**Key functions:**
- `read_excel_headers(filepath)` - Read column headers from first row
- `read_excel_streaming(filepath, start_row=2)` - Stream rows as dicts (memory efficient)
- `read_excel_row(filepath, row_number)` - Read a specific row as dict (wrapper for read_excel_rows)
- `read_excel_rows(filepath, row_numbers)` - Read multiple specific rows
- `get_excel_info(filepath)` - Get file info (headers, row count, etc.)

**Note:** For counting rows, use `count_file_rows()` from `data_source_utils` (has caching support) instead of the private `_count_excel_rows()` function.

**Usage:**
```python
from lib.utils.excel_utils import read_excel_streaming, read_excel_headers

# Stream rows (memory efficient for large files)
for record in read_excel_streaming(filepath):
    print(record['CASE_NUMBER'])

# Get headers only
headers = read_excel_headers(filepath)
```

**Features:**
- Proper workbook closing (uses try/finally)
- Handles None values and type conversion
- Supports read_only mode for performance
- Memory efficient streaming for large files

---

### `utils/bazel_runfiles.py`
**Purpose:** Access Bazel data dependencies using the standard runfiles library.

**Key functions:**
- `get_data_file_path(workspace_path)` - Get path to a Bazel data file using standard runfiles library
- `get_template_file(template_name, template_dir)` - Convenience wrapper for accessing template files

**Usage:**
```python
from lib.utils.bazel_runfiles import get_data_file_path, get_template_file

# Get a data file (e.g., template, config, etc.)
template_path = get_template_file("llm_prompt_template.txt")
if template_path:
    with open(template_path) as f:
        content = f.read()

# Or use directly
data_path = get_data_file_path("scripts/salary/llm_prompt_template.txt")
```

**Features:**
- Uses standard `rules_python.python.runfiles` library (cross-platform compatible)
- Handles all path variations automatically (no need for multiple path attempts)
- Works in both Bazel and non-Bazel environments (fallback to workspace directory)
- Properly handles external repository paths

**Why this exists:**
- Standard Bazel solution for accessing data dependencies
- Eliminates filesystem path guessing
- Cross-platform compatible (handles Windows/Unix differences automatically)

---

### `utils/location_utils.py`
**Purpose:** US state code constants and validation utilities.

**Key constants/functions:**
- `VALID_STATES` - Set of valid 2-letter US state codes (includes DC)
- `US_STATES` - List of (code, name) tuples for dropdowns
- `STATE_NAME_TO_CODE` - Mapping from full state names to 2-letter codes
- `is_valid_state(state_code)` - Check if a state code is valid
- `normalize_state_code(state)` - Normalize state input to 2-letter code (handles both names and codes)

**Usage:**
```python
from lib.utils.location_utils import VALID_STATES, US_STATES, is_valid_state, normalize_state_code

# Check if state is valid
if state_code in VALID_STATES:
    # Process state

# Or use helper function
if is_valid_state(state_code):
    # Process state

# Normalize state (handles "MASSACHUSETTS" -> "MA", "MA" -> "MA", "New York" -> "NY")
normalized = normalize_state_code("MASSACHUSETTS")  # Returns "MA"
normalized = normalize_state_code("MA")  # Returns "MA"
normalized = normalize_state_code("New York")  # Returns "NY"

# Use for dropdowns
for code, name in US_STATES:
    # Render option
```

**Note:** Standard libraries like `us` (pypi.org/project/us) were considered but deemed unnecessary for our simple use case (just validating 2-letter codes). Our implementation is lightweight and sufficient.

---

### `utils/url_utils.py`
**Purpose:** Canonical URL form and path basename for source deduplication (ingest discovery).

**Key functions:**
- `normalize_source_url(url)` - Canonical form: https, lowercase host, no query/fragment, no trailing slash (so same logical source in different URL form is not re-added)
- `path_basename_from_url(url)` - Last path segment (filename) for same-file dedup when the same file appears under different paths (e.g. DOL urljoin with/without trailing slash on base)

**Usage:** Used by `scripts/ingest/run_pipeline.py` in `discover_sources()` so already-seen/ingested sources are not treated as new.

---

### `utils/pagination.py`
**Purpose:** Reusable pagination utilities for Django views.

**Key functions:**
- `calculate_pagination_info(total_results, page, per_page)` - Calculate pagination metadata (page numbers, offset, page range)
- `build_pagination_query_string(params, param_mapping=None)` - Build query string for pagination links (without page param)

**Usage:**
```python
from lib.utils.pagination import calculate_pagination_info, build_pagination_query_string

# Calculate pagination
pagination = calculate_pagination_info(total_results=1000, page=5, per_page=50)
# Returns: {'page': 5, 'total_pages': 20, 'offset': 200, 'page_range': [1, '...', 4, 5, 6, '...', 20]}

# Build query string for pagination links
query_string = build_pagination_query_string({
    'query': 'engineer',
    'state_filter': 'CA',
    'year_filter': '2023'
})
# Returns: "q=engineer&state=CA&year=2023"

# Custom param mapping
query_string = build_pagination_query_string(
    {'internal_key': 'value'},
    param_mapping={'internal_key': 'url_param'}
)
```

---

### `utils/db_utils.py`
**Purpose:** Database utility functions for bulk operations and performance optimization.

**Key functions:**
- `bulk_update_batched(queryset_or_list, batch_size=1000, fields=None)` - Update multiple model instances in batches using bulk_update
- `bulk_create_batched(items, batch_size=1000, ignore_conflicts=False)` - Create multiple model instances in batches using bulk_create
- `BatchedUpdateCollector(fields, batch_size=1000, dry_run=False, use_transaction=True)` - Generic helper for collecting model updates with automatic batching
- `BatchedUpdates(batch_size=1000, dry_run=False)` - Helper class for automatic batched flushing (legacy, use `BatchedUpdateCollector` for new code)
- `process_in_batches(queryset, batch_size=1000, func=None)` - Process a queryset in batches to avoid loading all records into memory
- `bulk_delete_batched(queryset, batch_size=1000)` - Delete records from a queryset in batches

**Usage:**

**Option 1: BatchedUpdateCollector (Recommended for new code)**
```python
from lib.utils.db_utils import BatchedUpdateCollector

# Collect records and auto-flush when batch_size reached
collector = BatchedUpdateCollector(
    fields=['employer'],
    batch_size=1000,
    dry_run=False,
    use_transaction=True
)

for record in records:
    record.employer = employer
    collector.add(record)  # Auto-flushes at batch_size

collector.flush()  # Flush remaining records
fixed_count = collector.count  # Get total count
```

**Option 2: Manual batching**
```python
from lib.utils.db_utils import bulk_update_batched

employers_to_update = []
for employer in employers:
    employer.canonical_cluster = cluster
    employers_to_update.append(employer)
    if len(employers_to_update) >= 1000:
        bulk_update_batched(employers_to_update, fields=['canonical_cluster'])
        employers_to_update = []
if employers_to_update:
    bulk_update_batched(employers_to_update, fields=['canonical_cluster'])
```

**Option 3: BatchedUpdates (Legacy - use BatchedUpdateCollector for new code)**
```python
from lib.utils.db_utils import BatchedUpdates

batched = BatchedUpdates(batch_size=1000, dry_run=False)
for employer in employers:
    employer.canonical_cluster = cluster
    batched.add_employer_update(employer)  # Auto-flushes at batch_size
batched.flush_all(employer_fields=['canonical_cluster'])  # Final flush
```

**Benefits:**
- 10-20x faster than individual save()/create() calls
- Reduces database round-trips from N to N/batch_size
- Prevents connection pool exhaustion
- `BatchedUpdateCollector` handles transactions, dry_run mode, and counting automatically
- Consistent batching pattern across scripts
- Eliminates boilerplate code (no manual batch size checking, transaction wrapping, or count tracking)

---

### `utils/filter_utils.py`
**Purpose:** Generic filter application utilities for Django querysets.

**Key functions:**
- `apply_text_search_filter(queryset, query, fields)` - Apply case-insensitive text search across multiple fields
- `apply_visa_program_filter(queryset, program_filter, program_field='visa_program')` - Apply visa program filter (h1b/perm)
- `apply_fiscal_year_filter(queryset, year_filter, year_field='fiscal_year')` - Apply fiscal year filter

**Usage:**
```python
from lib.utils.filter_utils import (
    apply_text_search_filter,
    apply_visa_program_filter,
    apply_fiscal_year_filter,
)

# Text search across multiple fields
records = apply_text_search_filter(
    SalaryRecord.objects.all(),
    query='engineer',
    fields=['job_title', 'soc_title']
)

# Visa program filter
records = apply_visa_program_filter(records, 'h1b')  # Filters to H1B, H1B1, E3
records = apply_visa_program_filter(records, 'perm')  # Filters to PERM

# Fiscal year filter
records = apply_fiscal_year_filter(records, 2023)
```

---

## Quick Reference by Use Case

**Parsing bulletins:**
- `parsing/bulletin/parser.py` → `parsing/bulletin/bulletin_table.py` → `parsing/bulletin/publication_data.py`
- `parsing/bulletin/table_to_cutoff_data.py` → `parsing/bulletin/db_importer.py`

**Building dashboard:**
- `business/bulletin/cutoff_data_aggregator.py` → `business/bulletin/chart_builder.py` → `business/bulletin/cutoff_projection.py`

**Importing salary data:**
- **Unified ingest framework:** `lib/ingest/` (orchestrator, plugins)
- **Plugins:** `lib/ingest/plugins/` (dol_lca.py, dol_perm.py for salary data)
- **Legacy:** `parsing/salary/db_importer.py` (deprecated, use framework instead)
- **Note:** Always use unified ingest framework for new data sources - create plugins, not individual importers

**Script utilities:**
- `utils/logging_utils.py` (tracking) + `utils/http_utils.py` (HTTP/files) + `utils/db_utils.py` (bulk operations) + `utils/bazel_runfiles.py` (Bazel data dependencies)

**Web view utilities:**
- `utils/pagination.py` (pagination calculation) + `utils/filter_utils.py` (queryset filtering)

**Visa class handling:**
- `business/bulletin/visa_class_utils.py`

---

## Data Structures

### `BulletinTable` (from `parsing/bulletin/bulletin_table.py`)
Simple data class representing a parsed visa bulletin table.

**Fields:**
- `title` (str): Table identifier extracted from HTML (e.g., "employment_based_final_action")
- `headers` (tuple): Column headers from the table (first column is visa class, rest are countries)
- `rows` (list[tuple]): Data rows where each row contains visa class name and cutoff values

**Usage:**
- Created by `parser.py` when extracting tables from HTML
- Passed to `table_to_cutoff_data.py` to convert to structured VisaCutoffDate dicts

### `PublicationData` (from `parsing/bulletin/publication_data.py`)
Container for a single visa bulletin publication with its metadata and content.

**Fields:**
- `url` (str): Full URL to the bulletin page on travel.state.gov
- `content` (str): Raw HTML content of the bulletin page
- `publication_date` (datetime): Parsed publication date (first day of the publication month)

**Usage:**
- Created when fetching bulletins (e.g., in `refresh_data.py`)
- Passed to `db_importer.py` which extracts tables and saves to database

### `VisaCutoffDate` (Django model in `models/visa_cutoff_date.py`)
Django model representing a single visa cutoff date entry - the core time series data point.

**Fields:**
- `bulletin` (ForeignKey): Reference to the `Bulletin` model
- `visa_category` (str): "FAMILY_SPONSORED" or "EMPLOYMENT_BASED"
- `visa_class` (str): Visa class name (e.g., "F1", "EB2")
- `action_type` (str): "FINAL_ACTION" or "DATES_FOR_FILING"
- `country` (str): Country/region for chargeability
- `cutoff_value` (str): Raw value from table - date string, "C", or "U"
- `cutoff_date` (Date, nullable): Parsed date object (NULL for "C" or "U")
- `is_current` (bool): True if cutoff_value is "C"
- `is_unavailable` (bool): True if cutoff_value is "U"

**Usage:**
- Created by `db_importer.py` from structured dicts produced by `table_to_cutoff_data.py`
- Queried by `cutoff_data_aggregator.py` to build dashboard visualizations
