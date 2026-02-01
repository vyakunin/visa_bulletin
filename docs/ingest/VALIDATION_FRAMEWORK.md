# Ingest Pipeline Validation Framework

## Overview

Validation is integrated into the ingest pipeline framework. All plugins must implement post-ingest validation, which runs automatically after the load stage completes.

## Architecture

### Validation Flow

```
Download → Parse → Transform → Load → **Validate** → Version Activation
```

Validation runs after all data is loaded but before version activation. If validation fails (has errors), the pipeline aborts and the version is not activated.

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: bool  # False if errors exist
    errors: list[str]  # Critical issues (abort pipeline)
    warnings: list[str]  # Non-critical issues (log only)
    details: dict  # Additional validation details for reporting
```

**Errors vs Warnings:**
- **Errors**: Critical issues that should abort the pipeline
  - No records created when expected
  - Required fields missing
  - Invalid enum values
  - Data integrity violations
  
- **Warnings**: Non-critical issues that should be logged but not abort
  - Some files produced no records (may be expected)
  - Unusual value distributions
  - High null rates for optional fields
  - Records outside expected ranges (may be valid edge cases)

## Plugin Implementation

All plugins must implement `validate_post_ingest()`:

```python
def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
    """
    Validate data after ingestion completes.
    
    Args:
        run: IngestRun instance with completed ingestion
        
    Returns:
        ValidationResult with errors and warnings
    """
    errors = []
    warnings = []
    details = {}
    
    # Get records created in this run
    source_file = Path(run.checkpoint.get('filepath', '')).name
    records = Model.objects.filter(source_file=source_file)
    
    # CRITICAL: Abort if no records created
    if records.count() == 0:
        errors.append(f"No records created from '{source_file}'")
    
    # Check required fields
    missing_field = records.filter(required_field__isnull=True).count()
    if missing_field > 0:
        errors.append(f"{missing_field} records missing required_field")
    
    # Check for warnings
    null_rate = records.filter(optional_field__isnull=True).count() / records.count() * 100
    if null_rate > 50:
        warnings.append(f"High null rate for optional_field: {null_rate:.1f}%")
    
    return ValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        details=details
    )
```

## Current Plugin Validations

### DOL PERM Plugin

**Validates:**
- Records created (abort if none)
- Required fields: case_number, employer_name, job_title
- Wage range validation
- Null rate checks for important fields
- Fiscal year distribution

### DOL H-1B LCA Plugin

**Validates:**
- Records created (abort if none)
- Required fields: case_number, employer_name, job_title
- Wage range validation

### DOL Worksite Plugin

**Validates:**
- Records created (abort if none)
- Required fields: case_number, job_title
- Worksite state presence (warns if >50% missing)
- Wage range validation

### Visa Bulletin Plugin

**Validates:**
- Cutoff dates created (abort if none)
- Required fields: visa_category, visa_class, country
- Enum value validation (visa_category, action_type, country)
- Distribution checks (categories, classes, countries)

## Pipeline Behavior

### On Validation Success

1. Validation passes (no errors)
2. Warnings logged (if any)
3. Version created and activated
4. Records become visible to serving queries
5. Run marked as completed

### On Validation Failure

1. Validation fails (has errors)
2. Pipeline aborts with ValueError
3. Version NOT created
4. Records remain linked to run but not activated
5. Run marked as failed
6. Error message includes validation errors

### Example Error Output

```
ValueError: Validation failed with 2 error(s): No PERM records created from 'perm_fy2024.xlsx' - expected data but got none; 150 records missing case_number (required field)
```

## Integration with Standalone Validation

The framework validation is **lightweight and fast** - it runs automatically after every ingest.

For **comprehensive validation**, use standalone scripts:
- `scripts/salary/validate_data.py` - Full salary data validation
- Future: Bulletin validation can be added to the unified ingest pipeline validation framework

**When to use each:**
- **Framework validation**: Automatic, catches critical issues, fast
- **Standalone scripts**: Manual, comprehensive checks, detailed reports

## Best Practices

### Error Conditions (Abort)

✅ **DO abort on:**
- No records created when file should produce data
- Required fields missing across all records
- Invalid enum values (data corruption)
- Data integrity violations (duplicates, invalid references)

❌ **DON'T abort on:**
- Some files producing no records (may be expected)
- Optional fields missing
- Unusual but valid data distributions
- Edge cases that are technically valid

### Warning Conditions (Log Only)

✅ **DO warn on:**
- High null rates for important optional fields (>50%)
- Unusual value distributions (may indicate data quality issues)
- Records outside expected ranges (may be valid but worth investigating)
- Files producing no records (may be expected but worth noting)

### Performance

- Keep validation fast (< 5 seconds for typical runs)
- Use efficient queries (aggregates, counts, not full scans)
- Sample large datasets for expensive checks
- Cache results when possible

## Future Enhancements

1. **Validation Metrics Storage**
   - Store validation results in IngestRun metadata
   - Track validation history over time
   - Alert on validation degradation

2. **Configurable Validation Rules**
   - Allow plugins to define validation rules in config
   - Support different validation levels (strict, lenient)
   - Enable/disable specific checks

3. **Cross-Domain Validation**
   - Validate relationships between salary and bulletin data
   - Check consistency across domains
   - Detect data quality issues across sources

4. **Automated Validation Reports**
   - Generate validation reports after each run
   - Store reports for historical analysis
   - Alert on validation failures

