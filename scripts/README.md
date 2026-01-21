# Scripts Directory

This directory contains all project scripts organized by functionality. All scripts should be run via Bazel for proper dependency management.

## Quick Reference

- **Data Validation**: `bazel run //scripts/salary:validate_data`
- **Data Ingestion**: `bazel run //scripts/ingest:run_pipeline`
- **Employer Clustering**: `bazel run //scripts/salary:cluster_existing_employers`
- **Database Exploration**: `bazel run //scripts:explore_db`

## Table of Contents

1. [Data Validation](#data-validation)
2. [Data Ingestion](#data-ingestion)
3. [Data Fixes](#data-fixes)
4. [Employer Clustering](#employer-clustering)
5. [Database Management](#database-management)
6. [Deployment](#deployment)
7. [Development Utilities](#development-utilities)
8. [Performance Benchmarking](#performance-benchmarking)
9. [Investigation/Debugging](#investigationdebugging)

---

## Data Validation

### Unified Validation Script

**`scripts/salary/validate_data.py`** - **PRIMARY VALIDATION SCRIPT**

**Purpose:** Unified comprehensive validation script that consolidates all data quality validation functionality. This is the primary tool for verifying data integrity, completeness, and sanity across the entire salary database.

**When to use:**
- After ingesting new data files (verify import completeness)
- Before deploying to production (ensure data quality)
- During development to catch data issues early
- For generating validation reports for stakeholders
- To track data quality metrics over time (golden set tracking)

**What it validates:**

1. **Basic Statistics**
   - Record counts by program, fiscal year, source file
   - Employer counts and distribution
   - Data coverage metrics

2. **Data Integrity**
   - Required fields (case_number, employer_name, job_title)
   - Wage calculation accuracy (sampling 1000 records)
   - Date validation (case_submitted < decision_date, employment_start < employment_end)
   - Duplicate case numbers (should be none due to unique constraint)

3. **Data Sanity**
   - Wage ranges ($20K-$1M validation with separate high/low checks)
   - Valid wage units (WageUnit enum validation)
   - SOC code format (XX-XXXX or XX-XXXX.XX pattern)
   - State codes (VALID_STATES validation with examples)
   - Missing salary data (wage_annual null/0 - critical UI issue: displays as "$--")
   - Orphaned employers (Employer records with no SalaryRecords)
   - Empty critical fields (case_number='', employer_name='', job_title='')

4. **Import Completeness** (3 levels of granularity)
   - Total: File row counts vs database record counts (allow 5% deviation)
   - By Year: Per fiscal-year comparison (side-by-side table)
   - By File: Per-file comparison with discrepancy analysis and reason detection

5. **Record Completeness** (differentiated by field type)
   - SalaryRecord: case_number, job_title, wage_annual, employer_name, employer, fiscal_year
   - WorksiteRecord: case_number, job_title, fiscal_year (salary optional for worksite)

6. **Ingestion Analysis**
   - Latest 50 completed ingestion runs
   - Records created/failed per run
   - Breakdown by source type and domain

7. **Input vs Served Comparison**
   - Compare file statistics to served database statistics
   - Detect discrepancies (allow 5% deviation)
   - Analyze by source file

8. **Homepage Query Testing**
   - Dashboard queries (Family/Employment categories, countries, action types)
   - Salary search queries (H1B/PERM, by year, by state)
   - Aggregations (avg/min/max salary)

9. **Golden Set Tracking**
   - Save baseline statistics (`--update-golden`)
   - Compare current stats to golden set
   - Detect significant changes (>10% total count, >15% program distribution)
   - Track data quality trends over time

10. **Spot Checks** (optional, can skip with `--skip-spot-checks`)
    - Sample records by visa program, fiscal year, state, employer, wage range, case status
    - Verify data looks reasonable across different slices

**Usage:**
```bash
# Run all validations (default) - comprehensive data quality check
bazel run //scripts/salary:validate_data

# Generate JSON report for automated processing
bazel run //scripts/salary:validate_data -- --json-report report.json

# Skip spot checks (faster, for CI/CD)
bazel run //scripts/salary:validate_data -- --skip-spot-checks

# Check import completeness only (3 modes: total, by-year, by-file)
bazel run //scripts/salary:validate_data -- --check-import-completeness
bazel run //scripts/salary:validate_data -- --check-import-completeness-by-file

# Check incomplete records only (missing fields by type)
bazel run //scripts/salary:validate_data -- --check-incomplete-records

# Analyze ingestion logs (latest 50 runs)
bazel run //scripts/salary:validate_data -- --analyze-ingestion

# Compare input vs served stats (detect discrepancies)
bazel run //scripts/salary:validate_data -- --compare-input-served

# Test homepage queries only (faster, UI-focused)
bazel run //scripts/salary:validate_data -- --test-homepage-queries

# Golden set operations (track data quality baseline)
bazel run //scripts/salary:validate_data -- --golden-file data/validation/golden.json
bazel run //scripts/salary:validate_data -- --update-golden
```

**Key Features:**
- **Performance:** Uses `cached_file_rows` (file scanning is slow, results cached)
- **Comprehensive:** Filter-based incompleteness checks differentiated by field type
- **Flexible:** Run all checks or specific subsets via flags
- **Reporting:** Supports both JSON and text report generation
- **Exit codes:** 0 = success, 1 = errors found (CI/CD friendly)
- **N+1 Prevention:** Uses bulk queries, aggregations, and prefetch_related()

**Output:**
- Text report with validation results (pass/fail per check)
- Detailed error messages and warnings
- Statistics and sample data for failed checks
- JSON report (optional) for automated processing

**Deleted Scripts (functionality merged into validate_data.py):**
These scripts have been deleted and their functionality is available via flags in the unified script:
- `scripts/verify_import_completeness.py` - Deleted, use `--check-import-completeness` flag
- `scripts/validate_data_comprehensive.py` - Deleted, use unified script with appropriate flags
- `scripts/check_missing_salary.py` - Deleted, use `--check-incomplete-records` flag
- `scripts/investigate_null_salaries.py` - Deleted, use unified script
- `scripts/investigate_salary_issues.py` - Deleted, use unified script
- `scripts/investigate_validation_issues.py` - Deleted, use unified script

**Related Tools:**
- For detailed missing salary investigation (by source file, visa program): Use `scripts/salary/investigate_missing_salary.py`
- For data quality fixes: Use `scripts/salary/fix_all_data_quality_issues.py`

---

## Data Ingestion

### Main Pipeline

**`scripts/ingest/run_pipeline.py`** - Unified ingest pipeline orchestrator

**Usage:**
```bash
# Download data
bazel run //scripts/ingest:run_pipeline -- download --domain dol

# List available sources
bazel run //scripts/ingest:run_pipeline -- download --list-available

# Ingest data
bazel run //scripts/ingest:run_pipeline -- ingest --source-type lca

# Full pipeline (download + ingest)
bazel run //scripts/ingest:run_pipeline -- full --domain dol

# Re-ingest specific local files (drops non-unique indexes first, recreates after)
bazel run //scripts/ingest:run_pipeline -- reingest-files -- \
  --files data/salary/dol_data/LCA_Disclosure_Data_FY2024_Q4.xlsx data/salary/dol_data/PERM_Disclosure_Data_FY2024_Q4.xlsx
```

**Index management during re-ingest:**
- The `reingest-files` command **automatically drops non-unique indexes** on `salary_record`/`worksite_record`
  using `scripts/salary/manage_salary_indexes.py`, runs ingest, then recreates the indexes.
- Snapshot path defaults to `data/index_snapshots/salary_indexes.yaml`. Use
  `--index-snapshot` and `--overwrite-index-snapshot` to control it.
- Re-ingest runs in **update mode** to refresh existing records for the supplied files.

### Supporting Scripts

**`scripts/ingest/register_local_files.py`** - Register local files for ingestion
```bash
bazel run //scripts/ingest:register_local_files -- --file-path data/salary/file.xlsx
```

**`scripts/ingest/check_run_status.py`** - Check status of ingestion runs
```bash
bazel run //scripts/ingest:check_run_status
```

**`scripts/ingest/reset_incomplete_runs.py`** - Reset incomplete/failed ingestion runs
```bash
bazel run //scripts/ingest:reset_incomplete_runs
```

**`scripts/ingest/reset_missing_files.py`** - Reset runs with missing files
```bash
bazel run //scripts/ingest:reset_missing_files
```

**`scripts/ingest/inspect_raw_file_headers.py`** - Inspect column headers in raw files
```bash
bazel run //scripts/ingest:inspect_raw_file_headers -- --file data/salary/file.xlsx
```

**`scripts/ingest/inspect_unknown_source_rows.py`** - Inspect raw rows for unknown employer/job title values

Use this to locate a few `SalaryRecord` entries with `employer_name` or `job_title` set to `Unknown` and print the raw source columns to see if the data exists in alternative fields.

```bash
# Inspect both employer + job title unknowns (default)
bazel run //scripts/ingest:inspect_unknown_source_rows

# Limit to 5 cases
bazel run //scripts/ingest:inspect_unknown_source_rows -- --limit 5

# Inspect only employer unknowns
bazel run //scripts/ingest:inspect_unknown_source_rows -- --mode employer
```

**`scripts/ingest/rollback.py`** - Rollback ingestion runs
```bash
bazel run //scripts/ingest:rollback -- --run-id 123
```

**`scripts/ingest/ingest_and_cluster.sh`** - Shell script for ingest + clustering workflow
```bash
./scripts/ingest/ingest_and_cluster.sh
```

---

## Data Fixes

### Master Fix Script

**`scripts/salary/fix_all_data_quality_issues.py`** - Master orchestrator for all data quality fixes

Runs all fix scripts in optimal order:
1. Fix missing fiscal years (from source URL)
2. Fix invalid wages (unit correction + data errors)
3. Fix missing salary data (recalculate wage_annual)
4. Fix invalid state codes
5. Fix missing employer links
6. Check import completeness (report only)
7. Run validation to verify fixes

**Usage:**
```bash
# Dry-run (analyze only, see what would be fixed)
bazel run //scripts/salary:fix_all_data_quality_issues

# Actually fix all issues
bazel run //scripts/salary:fix_all_data_quality_issues -- --fix

# Skip specific fixes
bazel run //scripts/salary:fix_all_data_quality_issues -- --fix --skip-wages --skip-employers
```

**Benefits:**
- Runs fixes in optimal order (dependencies handled)
- Validates results after fixes
- Single command for comprehensive data quality repair
- Can skip individual fixes if needed

### Individual Fix Scripts

**`scripts/salary/fix_fiscal_year_from_url.py`** - Fix missing fiscal years from source URL

Records from files with artificial names (e.g., `lca_367.xlsx`) have no fiscal year in filename. This script:
1. Finds records from files with artificial names
2. Looks up the DataSource to get original URL
3. Extracts fiscal year from URL (e.g., `/FY2015/` → 2015)
4. Updates records with correct fiscal year

**Usage:**
```bash
# Dry-run (see what would be fixed)
bazel run //scripts/salary:fix_fiscal_year_from_url -- --dry-run

# Actually fix
bazel run //scripts/salary:fix_fiscal_year_from_url
```

**`scripts/salary/fix_missing_salary_data.py`** - Fix records with missing wage_annual

Identifies records where `wage_annual` is NULL/0 but `wage_from` and `wage_unit` are present. Recalculates `wage_annual` using shared `calculate_annual_wage` function.

**Causes of missing wage_annual:**
- Import failures (row parsing errors)
- Data migration issues
- Manual data entry errors

**Usage:**
```bash
# Dry-run (analyze only)
bazel run //scripts/salary:fix_missing_salary_data

# Actually fix
bazel run //scripts/salary:fix_missing_salary_data -- --fix

# Limit to first 1000 records (for testing)
bazel run //scripts/salary:fix_missing_salary_data -- --fix --limit 1000
```

**`scripts/salary/fix_missing_employers.py`** - Fix missing employer links

Identifies records with `employer_name` but no `employer` FK. Creates or finds matching Employer records and links them using batch updates.

**Causes:**
- Records imported before employer clustering
- Data migration issues
- Import failures

**Usage:**
```bash
# Dry-run (analyze only)
bazel run //scripts/salary:fix_missing_employers

# Actually fix
bazel run //scripts/salary:fix_missing_employers -- --fix

# Limit to first 1000 records
bazel run //scripts/salary:fix_missing_employers -- --fix --limit 1000
```

**`scripts/salary/fix_state_codes.py`** - Fix invalid state codes

Identifies and fixes records with invalid `worksite_state` values (typos, full names, abbreviations).

**Common issues fixed:**
- Typos: "Califonia" → "CA"
- Full names: "California" → "CA"
- Abbreviations: "Calif" → "CA"
- Case/whitespace issues

**Usage:**
```bash
# Dry-run (see what would be fixed)
bazel run //scripts/salary:fix_state_codes -- --dry-run

# Actually fix
bazel run //scripts/salary:fix_state_codes

# Limit to first 1000 records
bazel run //scripts/salary:fix_state_codes -- --limit 1000
```

**`scripts/salary/fix_invalid_wages.py`** - Comprehensive fix for invalid wage records (both too high and too low)

**Purpose:** Identifies and corrects salary records with `wage_annual` outside the valid range ($5,000 - $480,719) configured in `wage_thresholds_config.yaml`. Uses the same validation logic as the ingest pipeline via shared `lib.parsing.salary.wage_unit_correction` module to ensure consistency.

**Invalid wages are caused by:**
- **Incorrect wage units**: Hourly/monthly/weekly wages stored as annual (or vice versa)
- **Data entry errors**: Unrealistic values (e.g., $21.3M for Marketing Manager, or $7.25 annual for minimum wage)
- **Parsing errors**: Decimal point errors, extra zeros, missing unit conversion

**Categorization and fixes:**
- **Parsing errors** (wrong wage unit) → Auto-corrects unit and recalculates `wage_annual`
  - Example: $7.25 stored as annual → Corrected to hourly, recalculated as $15,080/year
  - Example: $21,300,000 for Marketing Manager → Likely $21.30/hr stored as annual
- **Data errors** (unrealistic even with correct unit) → Marks as invalid (NULL)
  - Example: $4.5B annual salary (clearly impossible)
- **Edge cases** (possibly legitimate high salaries) → Flags for manual review
  - Example: $600K for C-level executive (may be legitimate, needs verification)

**Uses batched updates** (`BatchedUpdateCollector`) for efficient database operations - processes thousands of records without N+1 query problems.

```bash
# Fix all invalid wages (both high and low) - RECOMMENDED
bazel run //scripts/salary:fix_invalid_wages

# Dry-run to see what would be fixed (no database changes)
bazel run //scripts/salary:fix_invalid_wages -- --dry-run

# Fix only parsing errors (auto-correct wrong units)
bazel run //scripts/salary:fix_invalid_wages -- --category parsing

# Fix only data errors (mark unrealistic values as invalid)
bazel run //scripts/salary:fix_invalid_wages -- --category data

# Limit to first 100 records (for testing)
bazel run //scripts/salary:fix_invalid_wages -- --limit 100
```

**`scripts/salary/fix_state_codes.py`** - Fix invalid state codes
```bash
bazel run //scripts/salary:fix_state_codes -- --fix
```

**`scripts/salary/reimport_perm_salary_data.py`** - Re-import PERM files to extract missing data
```bash
bazel run //scripts/salary:reimport_perm_salary_data -- --fix
```

**`scripts/salary/reimport_i200_files.py`** - Re-import I-200 files
```bash
bazel run //scripts/salary:reimport_i200_files -- --fix
```

---

## Employer Clustering

### Main Clustering Script

**`scripts/salary/cluster_existing_employers.py`** - Cluster existing employers using similarity matching

**Usage:**
```bash
# Dry-run (preview matches)
bazel run //scripts/salary:cluster_existing_employers -- --dry-run

# Actually cluster
bazel run //scripts/salary:cluster_existing_employers

# With limits (for testing)
bazel run //scripts/salary:cluster_existing_employers -- --limit-employers 1000 --min-pairs 5
```

**Key Features:**
- Uses LSH (Locality Sensitive Hashing) for efficient similarity matching
- Two-phase approach: same normalized names, then cross-normalized names
- Auto-clusters high-confidence matches, queues uncertain matches for review
- Supports dry-run mode for preview
- Long-running script - run in background with monitoring

### Clustering Evaluation and Tuning

**`scripts/salary/evaluate_clustering_threshold.py`** - Evaluate clustering threshold
```bash
bazel run //scripts/salary:evaluate_clustering_threshold
```

**`scripts/salary/benchmark_clustering.py`** - Benchmark clustering performance
```bash
bazel run //scripts/salary:benchmark_clustering -- --mode production --examples-file data/clustering_examples.jsonl
```

**`scripts/salary/iterative_clustering_tuning.py`** - Iterative tuning workflow
```bash
bazel run //scripts/salary:iterative_clustering_tuning
```

**`scripts/salary/binary_search_threshold.py`** - Binary search for optimal threshold
```bash
bazel run //scripts/salary:binary_search_threshold
```

### Clustering Review and Management

**`scripts/salary/review_clustering.py`** - Review clustering decisions
```bash
bazel run //scripts/salary:review_clustering
```

**`scripts/salary/apply_review_decisions.py`** - Apply manual review decisions
```bash
bazel run //scripts/salary:apply_review_decisions
```

**`scripts/salary/reset_clustering.py`** - Reset clustering (remove all clusters)
```bash
bazel run //scripts/salary:reset_clustering
```

**`scripts/salary/cleanup_orphaned_employers.py`** - Clean up orphaned employers
```bash
bazel run //scripts/salary:cleanup_orphaned_employers
```

### Clustering Examples and Data Collection

**`scripts/salary/collect_clustering_examples.py`** - Collect examples for benchmarking
```bash
bazel run //scripts/salary:collect_clustering_examples
```

**`scripts/salary/view_clustering_examples.py`** - View clustering examples
```bash
bazel run //scripts/salary:view_clustering_examples
```

### Golden Test Data Collection

**`scripts/salary/collect_dol_golden_test_data.py`** - Collect golden test data for DOL plugin transforms

Samples random rows from all PERM and LCA files for golden testing of transform() methods.

**Usage:**
```bash
# Collect 10 samples per file (default)
bazel run //scripts/salary:collect_dol_golden_test_data

# Customize output and sample size
bazel run //scripts/salary:collect_dol_golden_test_data -- \
  --output tests/data/dol_golden_test_data.yaml \
  --samples-per-file 20 \
  --random-seed 42
```

**What it does:**
- Finds all Excel files in `data/salary/dol_data/`
- Detects file type from headers (PERM vs LCA/Worksite)
- Samples random rows from each file
- Saves parsed dicts to YAML for manual annotation

**Next steps:**
1. Manually annotate expected results in the YAML file
2. Add `record_type`, `expected_result`, `expected_error` fields
3. Run golden test: `bazel test //tests:test_dol_transform_golden`

**See also:**
- `tests/data/README.md` - Test data format documentation
- `GOLDEN_TEST_SET_DOL_TRANSFORMS.md` - Complete implementation plan

### LLM-Based Clustering

**`scripts/salary/evaluate_clustering_with_llm.py`** - Evaluate clustering using LLM
```bash
bazel run //scripts/salary:evaluate_clustering_with_llm
```

**`scripts/salary/benchmark_llm_verifier.py`** - Benchmark LLM verifier performance
```bash
bazel run //scripts/salary:benchmark_llm_verifier
```

**`scripts/salary/test_llm_prompts.py`** - Test LLM prompt variations
```bash
bazel run //scripts/salary:test_llm_prompts
```

### Bucket Mismatch Handling

**`scripts/salary/check_bucket_mismatch_status.py`** - Check bucket mismatch review status
```bash
bazel run //scripts/salary:check_bucket_mismatch_status
```

**`scripts/salary/review_pending_bucket_mismatches.py`** - Review pending bucket mismatches
```bash
bazel run //scripts/salary:review_pending_bucket_mismatches
```

**`scripts/salary/fix_pending_bucket_mismatches.py`** - Fix pending bucket mismatches
```bash
bazel run //scripts/salary:fix_pending_bucket_mismatches -- --fix
```

**`scripts/salary/finalize_bucket_mismatch_reviews.py`** - Finalize bucket mismatch reviews
```bash
bazel run //scripts/salary:finalize_bucket_mismatch_reviews
```

**`scripts/salary/harvest_bucket_mismatch_examples.py`** - Harvest examples for analysis
```bash
bazel run //scripts/salary:harvest_bucket_mismatch_examples
```

**`scripts/salary/add_bucket_mismatch_to_golden_set.py`** - Add examples to golden set
```bash
bazel run //scripts/salary:add_bucket_mismatch_to_golden_set
```

### Clustering Utilities

**`scripts/salary/merge_duplicate_clusters.py`** - Merge duplicate employer clusters (data cleanup)

**Purpose:** Identifies and merges duplicate `EmployerCluster` records with the same `canonical_name`. Critical for fixing data integrity issues that cause duplicate entries in autocomplete and breaking data consistency.

**When to use:**
- After discovering duplicate clusters in autocomplete
- Before applying unique constraint migration on `canonical_name`
- After bulk imports that may have created duplicate clusters
- To clean up data integrity issues in employer clustering

**Process:**
1. Finds all duplicate clusters (same `canonical_name`)
2. Selects primary cluster (most employers, or lowest ID if tied)
3. Reassigns all employers from duplicate clusters to primary
4. Deletes empty duplicate clusters

**Performance:** Uses bulk operations (`bulk_update_batched`, bulk delete) optimized for large datasets. Processes 24k+ duplicates in ~5 queries with N+1 query prevention via `prefetch_related()`.

```bash
# Dry run to preview changes (recommended first)
bazel run //scripts/salary:merge_duplicate_clusters -- --dry-run

# Actually perform the merge
bazel run //scripts/salary:merge_duplicate_clusters

# Debug mode with verbose logging
bazel run //scripts/salary:merge_duplicate_clusters -- --debug
```

**`scripts/salary/test_normalization.py`** - Test name normalization
```bash
bazel run //scripts/salary:test_normalization
```

**`scripts/salary/review_golden_set.py`** - Review golden set examples
```bash
bazel run //scripts/salary:review_golden_set
```

**`scripts/salary/fix_ground_truth_labels.py`** - Fix ground truth labels in golden set
```bash
bazel run //scripts/salary:fix_ground_truth_labels -- --fix
```

---

## Database Management

### Migration Scripts

**`scripts/makemigrations_wrapper.py`** - Wrapper for Django makemigrations (handles Bazel sandbox)
```bash
bazel run //:makemigrations_wrapper
```

### Database Utilities

**`scripts/explore_db.py`** - Interactive database exploration tool
```bash
bazel run //scripts:explore_db -- --query "SELECT COUNT(*) FROM salary_record"
```

**`scripts/clear_cache.py`** - Clear Django cache
```bash
bazel run //scripts:clear_cache
```

**`scripts/salary/drop_data.py`** - Drop all data (use with caution!)
```bash
bazel run //scripts/salary:drop_data
```

**`scripts/salary/manage_salary_indexes.py`** - Drop/recreate non-unique salary indexes for bulk ingest
```bash
bazel run //scripts/salary:manage_salary_indexes -- --list
bazel run //scripts/salary:manage_salary_indexes -- --drop
bazel run //scripts/salary:manage_salary_indexes -- --recreate
```

---

## Deployment

### Deployment Scripts

**`scripts/deploy-zero-downtime.sh`** - Zero-downtime blue-green deployment
```bash
./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin 1.2.3
```

**`scripts/pre-deploy-check.sh`** - Pre-deployment validation checks
```bash
./scripts/pre-deploy-check.sh ~/.ssh/lightsail_visa_bulletin
```

### Setup Scripts

**`scripts/setup_dev_environment.sh`** - Set up development environment
```bash
./scripts/setup_dev_environment.sh
```

**`scripts/setup_dev_tools.sh`** - Install development tools
```bash
./scripts/setup_dev_tools.sh
```

**`scripts/setup_postgresql_local.sh`** - Set up local PostgreSQL
```bash
./scripts/setup_postgresql_local.sh
```

**`scripts/setup_postgresql_production.sh`** - Set up production PostgreSQL
```bash
./scripts/setup_postgresql_production.sh
```

**`scripts/setup_lightsail_ssh.sh`** - Set up SSH access to Lightsail
```bash
./scripts/setup_lightsail_ssh.sh
```

**`scripts/add_ssh_key_to_lightsail.sh`** - Add SSH key to Lightsail
```bash
./scripts/add_ssh_key_to_lightsail.sh
```

**`scripts/setup_cron.sh`** - Set up cron jobs
```bash
./scripts/setup_cron.sh
```

### Server Management

**`scripts/restart_server.sh`** - Restart Django development server
```bash
./scripts/restart_server.sh              # Foreground (interactive)
./scripts/restart_server.sh --background  # Background (for automation)
```

**`scripts/check_debug_mode.py`** - Verify DEBUG=False in production
```bash
bazel run //scripts:check_debug_mode
```

---

## Development Utilities

### File Inspection

**`scripts/ingest/inspect_source_columns.py`** - Inspect columns and sample data in DOL source files

**Purpose:** Inspect what columns exist in DOL source files (PERM, LCA), filter by keywords, and view sample data from those columns. Useful for understanding data structure, identifying available fields, and estimating storage impact for new features.

**Usage:**
```bash
# Check columns in default PERM and LCA files
bazel run //scripts/ingest:inspect_source_columns

# Inspect specific files with keyword filters
bazel run //scripts/ingest:inspect_source_columns -- \
  --files data/salary/dol_data/PERM_Disclosure_Data_FY2020.xlsx \
  --match-terms job,title \
  --show-all-columns

# Estimate storage impact
bazel run //scripts/ingest:inspect_source_columns -- --estimate-storage
```

**Output shows:**
- Total columns in each file
- Matching columns (keyword filters) with sample values
- Total record counts per file
- Optional storage impact estimates

**When to use:**
- Before adding new fields to database schema
- To understand what data is available in source files
- To estimate storage impact for new features
- To identify potential data quality issues

**`scripts/salary/inspect_perm_columns.py`** - Inspect PERM file columns
```bash
bazel run //scripts/salary:inspect_perm_columns -- --file data/salary/PERM_FY2009.xlsx
```

### Utilities

**`scripts/salary/update_wage_thresholds.py`** - Update wage thresholds
```bash
bazel run //scripts/salary:update_wage_thresholds
```

**`scripts/generate_favicon_png.sh`** - Generate favicon variants
```bash
./scripts/generate_favicon_png.sh
```

**`scripts/check_cls.sh`** - Check Cumulative Layout Shift for SEO
```bash
./scripts/check_cls.sh
```

---

## Performance Benchmarking

**`scripts/benchmark_db_ingest.py`** - Benchmark database ingestion performance
```bash
bazel run //scripts:benchmark_db_ingest
```

**`scripts/benchmark_db_serving.py`** - Benchmark database serving performance
```bash
bazel run //scripts:benchmark_db_serving
```

**`scripts/benchmark_excel_standalone.py`** - Benchmark Excel parsing (standalone)
```bash
bazel run //scripts:benchmark_excel_standalone
```

**`scripts/benchmark_parsing.py`** - Benchmark parsing performance
```bash
bazel run //scripts:benchmark_parsing
```

**`scripts/test_excel_performance.py`** - Test Excel performance
```bash
bazel run //scripts:test_excel_performance
```

**`scripts/test_streaming_performance.py`** - Test streaming performance
```bash
bazel run //scripts:test_streaming_performance
```

**`scripts/run_performance_benchmarks.py`** - Run all performance benchmarks
```bash
bazel run //scripts:run_performance_benchmarks
```

**`scripts/show_performance_comparison.py`** - Show performance comparison
```bash
bazel run //scripts:show_performance_comparison
```

---

## Investigation/Debugging

**Note:** Most investigation functionality has been merged into the unified validation script. Use `bazel run //scripts/salary:validate_data` with appropriate flags.

### Deleted Investigation Scripts

These scripts have been deleted and their functionality is available in the unified validation script:

- `scripts/investigate_null_salaries.py` - Deleted, use `--check-incomplete-records` flag
- `scripts/investigate_salary_issues.py` - Deleted, use unified validation script
- `scripts/investigate_validation_issues.py` - Deleted, use unified validation script
- `scripts/check_missing_salary.py` - Deleted, use `--check-incomplete-records` flag

---

## Script Development Guidelines

### Before Creating a New Script

1. **Search for existing scripts** - Check this README and search the codebase for similar functionality
2. **Consider extending existing scripts** - Add new modes/flags to existing scripts rather than creating new ones
3. **Only create new scripts if functionality is truly distinct** - Avoid duplication

### Script Documentation Requirements

Every script must include:
- **Docstring** with purpose, usage examples, and key flags
- **Entry in this README** (appropriate category)
- **BUILD target** with proper dependencies
- **Script usage logging** (if permanent script - use `ScriptLogger`)

### Script Naming Conventions

- **Validation scripts**: `validate_*.py`, `check_*.py`
- **Fix scripts**: `fix_*.py`
- **Investigation scripts**: `investigate_*.py`, `debug_*.py`
- **Utility scripts**: Descriptive names (e.g., `explore_db.py`, `clear_cache.py`)
- **Avoid**: `test_*.py` for non-unit-test scripts (use `check_*.py` or `evaluate_*.py`)

### Running Scripts

**Always use Bazel:**
```bash
bazel run //scripts/salary:validate_data
bazel run //scripts:explore_db
```

**Never run Python directly:**
```bash
# ❌ BAD
python scripts/salary/validate_data.py

# ✅ GOOD
bazel run //scripts/salary:validate_data
```

### Long-Running Scripts

For scripts that take > 10 seconds:
- Run in background with logging
- Monitor progress actively
- Use slow exponential backoff for monitoring intervals

Example:
```bash
bazel run //scripts/salary:cluster_existing_employers > /tmp/clustering.log 2>&1 &
PID=$!
tail -f /tmp/clustering.log
```

---

## Temporary/One-Off Scripts

Temporary debugging scripts should be placed in `scripts/oneoff/` and logged to `logs/throwaway_calls.log` using `log_context()`.

See `.cursor/rules/general_logging.mdc` for details on script usage logging.

---

## Related Documentation

- [Validation Manual Flow](../../docs/VALIDATION_MANUAL_FLOW.md) - Detailed validation workflow
- [Fix Procedures](../../docs/FIX_PROCEDURES.md) - Data quality fix procedures
- [Employer Clustering](../../lib/business/salary/README.md) - Clustering documentation
- [Ingest Pipeline](../../docs/UNIFIED_INGEST_PIPELINE_DESIGN.md) - Ingest pipeline design

