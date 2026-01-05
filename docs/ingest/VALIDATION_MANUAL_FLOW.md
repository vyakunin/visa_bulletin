# Manual Data Validation Flow

## Overview

This document describes the manual validation workflow for both local development and production databases. Use this to verify data quality, catch issues, and ensure data integrity.

**Key Features:**
- ✅ Reuses existing validation logic from plugins
- ✅ Analyzes latest ingestion logs
- ✅ Compares input file stats (Excel/CSV) to served data stats
- ✅ Detects unusual values (extremely high/low wages, malformed ranges)
- ✅ Tests homepage main entry point queries
- ✅ Maintains golden set and detects significant changes

## Quick Start

### Local Validation

```bash
# Run comprehensive validation (unified script)
bazel run //scripts/salary:validate_data

# Update golden set (after verifying data is correct)
bazel run //scripts/salary:validate_data -- --update-golden

# Test homepage queries only (faster)
bazel run //scripts/salary:validate_data -- --test-homepage-queries
```

### Production Validation

```bash
# SSH to production
ssh lightsail

# Navigate to project
cd /opt/visa_bulletin

# Run validation (uses production database)
bazel run //scripts/salary:validate_data
```

## Validation Scripts

### Unified Validation Script (`scripts/salary/validate_data.py`)

**Purpose:** Unified comprehensive validation script that consolidates all validation functionality.

**Features:**
- Basic statistics (record counts, program distribution, fiscal years)
- Data integrity (required fields, calculations, dates, duplicates)
- Data sanity (wage ranges, valid units, SOC codes, state codes, missing salary data)
- Import completeness (file row counts vs database records - uses cached file counts)
- Record completeness (missing fields by type - comprehensive filter-based checks)
- Ingestion analysis (latest ingestion runs, records created/failed)
- Input vs served comparison (file stats vs database stats)
- Homepage query testing (dashboard queries, salary search queries)
- Golden set tracking (compare current stats to expected baseline)
- Spot checks by groups (visa program, fiscal year, state, employer, wage range, case status)

**Usage:**
```bash
# Full validation (default - runs all checks)
bazel run //scripts/salary:validate_data

# Generate JSON report
bazel run //scripts/salary:validate_data -- --json-report validation_report.json

# Skip spot checks (faster)
bazel run //scripts/salary:validate_data -- --skip-spot-checks

# Check import completeness only (file rows vs DB records)
bazel run //scripts/salary:validate_data -- --check-import-completeness

# Check incomplete records only (missing fields by type)
bazel run //scripts/salary:validate_data -- --check-incomplete-records

# Analyze ingestion logs
bazel run //scripts/salary:validate_data -- --analyze-ingestion

# Compare input vs served stats
bazel run //scripts/salary:validate_data -- --compare-input-served

# Test homepage queries only
bazel run //scripts/salary:validate_data -- --test-homepage-queries

# Update golden set
bazel run //scripts/salary:validate_data -- --update-golden

# Check against specific golden set
bazel run //scripts/salary:validate_data -- --golden-file data/validation/golden.json
```

**Monitoring Long-Running Validations:**

Validation scripts can take several minutes, especially with large datasets. Always run them in background mode for proper monitoring:

```bash
# ✅ GOOD - Run in background with full log
bazel run //scripts/salary:validate_data > /tmp/validation.log 2>&1 &
PID=$!
echo "Started with PID: $PID"
echo "Monitor with: tail -f /tmp/validation.log"

# In another terminal, monitor progress:
tail -f /tmp/validation.log

# Or filter for specific sections while still seeing progress:
tail -f /tmp/validation.log | grep -E "Running|Missing Salary|DATA SANITY|ERROR|WARNING"
```

**❌ BAD - Don't filter in the command (prevents monitoring):**
```bash
# ❌ Can't see progress, can't tell if stuck
bazel run //scripts/salary:validate_data 2>&1 | grep "Missing Salary" | head -50
```

**Why:**
- Progress messages are hidden (don't match grep pattern)
- `head -N` closes pipe early, may cause SIGPIPE errors
- Can't tell if script is stuck or just slow
- Can't see what stage script is at

See `.cursor/rules/general_script_development.mdc` for complete monitoring guidelines.

**Key Features:**
- ✅ Preserves `cached_file_rows` functionality for performance (file scanning is slow)
- ✅ Uses comprehensive filter-based incompleteness checks (differentiated by field type)
- ✅ Supports JSON and text report generation
- ✅ Exit codes: 0 = success, 1 = errors found

**Deprecated Scripts (functionality merged):**
- `scripts/verify_import_completeness.py` - **DELETED**, use `--check-import-completeness` flag
- `scripts/validate_data_comprehensive.py` - **DELETED**, use unified script with appropriate flags
- `scripts/check_missing_salary.py` - **DELETED**, use `--check-incomplete-records` flag
- `scripts/investigate_null_salaries.py` - **DELETED**, use unified script
- `scripts/investigate_salary_issues.py` - **DELETED**, use unified script
- `scripts/investigate_validation_issues.py` - **DELETED**, use unified script

**See `scripts/README.md` for complete script documentation.**

## Validation Workflow

### Local Development

#### Step 1: After Data Import

```bash
# Run comprehensive validation
bazel run //scripts/salary:validate_data

# Review output for:
# - Extremely high wages (>$1M) - CRITICAL
# - Malformed wage ranges - CRITICAL
# - Significant changes vs golden set
# - Input/served discrepancies
```

#### Step 2: Fix Issues

If validation finds critical issues:

1. **Extremely High Wages:**
   - These are almost certainly invalid (hourly wages stored as annual)
   - Check wage_unit_correction logic
   - May need to fix data and re-import

2. **Malformed Wage Ranges:**
   - Parsing errors (e.g., "$10400000 - $6666")
   - Check parsing logic in db_importer.py
   - May need to fix data and re-import

3. **Input/Served Discrepancies:**
   - Large differences between input rows and served records
   - Check for rejected records, validation failures
   - Review ingestion logs

#### Step 3: Update Golden Set

Once data is verified correct:

```bash
# Update golden set with current (correct) statistics
bazel run //scripts/salary:validate_data -- --update-golden
```

This creates `data/validation/golden.json` with:
- Current salary statistics
- Current bulletin statistics
- Homepage query results

**Golden set is used to:**
- Detect significant changes in future runs
- Alert when distributions change unexpectedly
- Track data quality over time

#### Step 4: Regular Validation

Run validation periodically:

```bash
# Quick check (homepage queries only)
bazel run //scripts/salary:validate_data -- --check-homepage-queries

# Full validation (weekly/monthly)
bazel run //scripts/salary:validate_data
```

### Production Database

#### Step 1: Connect to Production

```bash
# SSH to production server
ssh lightsail

# Navigate to project
cd /opt/visa_bulletin

# Ensure environment variables are set
export DB_ENGINE=postgresql  # or sqlite3
export DB_NAME=visa_bulletin
export DB_USER=visa_bulletin_user
export DB_PASSWORD=<password>
export DB_HOST=localhost
export DB_PORT=5432
```

#### Step 2: Run Validation

```bash
# Full validation
bazel run //scripts/salary:validate_data

# Generate report
bazel run //scripts/salary:validate_data -- --json-report /tmp/validation_report.json
```

#### Step 3: Review Results

Check for:
- **CRITICAL errors:** Extremely high wages, malformed ranges
- **Warnings:** Significant changes vs golden set
- **Discrepancies:** Input vs served data mismatches

#### Step 4: Investigate Issues

If issues found:

1. **Check ingestion logs:**
   ```bash
   # View recent runs
   bazel run //:explore_db
   # Or query directly:
   python3 -c "
   import django
   django.setup()
   from models.ingest.ingest_run import IngestRun
   for run in IngestRun.objects.order_by('-completed_at')[:10]:
       print(f\"Run {run.id}: {run.records_created} created, {run.records_failed} failed\")
   "
   ```

2. **Check specific records:**
   ```bash
   # Query records with issues
   python3 -c "
   import django
   django.setup()
   from models.salary import SalaryRecord
   from decimal import Decimal
   high_wages = SalaryRecord.objects.filter(wage_annual__gt=Decimal('1000000'))[:10]
   for r in high_wages:
       print(f\"{r.case_number}: ${r.wage_annual:,.0f} - {r.job_title}\")
   "
   ```

3. **Review source files:**
   - Check if source files have issues
   - Verify parsing logic handles edge cases
   - May need to fix and re-import

## Golden Set Management

### Creating Golden Set

**When to create:**
- After major data import
- After fixing data quality issues
- When data is known to be correct

**How to create:**
```bash
bazel run //scripts/salary:validate_data -- --update-golden
```

**Location:** `data/validation/golden.json`

### Using Golden Set

**Automatic comparison:**
- Validation script automatically compares current stats to golden set
- Detects significant changes (>10% for totals, >15% for distributions)
- Flags as errors or warnings based on severity

**Manual comparison:**
```bash
# Run validation (automatically compares to golden if exists)
bazel run //scripts/salary:validate_data

# Review golden_comparison section in output
```

### Updating Golden Set

**When to update:**
- After legitimate data changes (new fiscal year, new data source)
- After fixing data quality issues
- When distributions legitimately change

**How to update:**
```bash
# Verify current data is correct first
bazel run //scripts/salary:validate_data

# If correct, update golden set
bazel run //scripts/salary:validate_data -- --update-golden
```

## Validation Checks

### Critical Errors (Abort Pipeline)

These are caught by plugin validation during ingest:
- No records created when expected
- Required fields missing across all records
- Invalid enum values

### Warnings (Log Only)

These are detected by comprehensive validation:
- Extremely high wages (>$1M) - likely parsing errors
- Malformed wage ranges
- High null rates (>50%)
- Significant changes vs golden set

### Homepage Query Tests

Tests queries corresponding to main entry points:
- Dashboard queries (family/employment, by country)
- Salary search queries (by program, year, state)
- Aggregations (avg/min/max salaries)

## Troubleshooting

### Issue: Extremely High Wages Detected

**Symptoms:**
- Wages > $1M (e.g., $7M, $21M)
- Likely cause: Hourly wages stored as annual (parsing error)

**Fix:**
1. Check wage_unit_correction logic
2. Verify wage_unit field is correct
3. May need to fix and re-import affected records

### Issue: Malformed Wage Ranges

**Symptoms:**
- Ranges like "$10400000 - $6666"
- Likely cause: Parsing error in wage_from/wage_to

**Fix:**
1. Check parsing logic in db_importer.py
2. Review source file format
3. Fix parsing and re-import

### Issue: Input/Served Discrepancy

**Symptoms:**
- Input file has 100K rows, but only 95K records served
- Likely cause: Records rejected during validation

**Fix:**
1. Check ingestion logs for rejected records
2. Review validation logic
3. May need to adjust validation thresholds

### Issue: Significant Changes vs Golden Set

**Symptoms:**
- Total count changed >10% or distribution changed >15%
- May be legitimate (new data) or issue

**Fix:**
1. Verify if change is expected (new fiscal year, etc.)
2. If unexpected, investigate data quality
3. Update golden set if change is legitimate

## Best Practices

1. **Run validation after every major import**
   - Catches issues early
   - Prevents bad data from propagating

2. **Update golden set when data is correct**
   - Provides baseline for future comparisons
   - Helps detect unexpected changes

3. **Review validation reports regularly**
   - Weekly for active development
   - Monthly for production
   - After any data fixes

4. **Investigate warnings, not just errors**
   - Warnings may indicate data quality issues
   - Early detection prevents bigger problems

5. **Keep golden set in version control**
   - Track changes over time
   - Enables comparison across environments

## Integration with CI/CD

**Recommended:**
- Run validation in CI after data imports
- Fail build on critical errors
- Warn on significant changes vs golden set
- Store validation reports as artifacts

**Example CI step:**
```yaml
- name: Validate Data
  run: |
    bazel run //scripts/salary:validate_data -- --json-report validation_report.json
    # Fail on critical errors
    if grep -q "CRITICAL" validation_report.json; then
      exit 1
    fi
```

## Files

- `scripts/salary/validate_data.py` - Unified comprehensive validation script (consolidates all validation functionality)
- `scripts/salary/validate_data.py` - Salary-specific validation (reused)
- `data/validation/golden.json` - Golden set of expected statistics
- `lib/ingest/plugins/salary_validation.py` - Shared validation logic for plugins

