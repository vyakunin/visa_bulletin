# Test Data Directory

This directory contains test data files used by golden tests and other test suites.

## Files

### `dol_golden_test_data.yaml`

Golden test data for DOL plugin transform methods. Contains sampled rows from PERM and LCA files with manually annotated expected results.

**Format:**
```yaml
test_cases:
  - plugin_type: "PERM"  # or "H1B" (detected from headers)
    record_type: "SalaryRecord"  # or "WorksiteRecord" (manually annotated)
    source_file: "PERM_FY2024.xlsx"
    row_number: 1234
    fiscal_year: 2024
    input:
      CASE_NUMBER: "P-12345-67890"
      EMPLOYER_NAME: "Tech Corp"
      # ... all columns from row
    expected_result:
      case_number: "P-12345-67890"
      employer_name: "Tech Corp"
      wage_from: 120000.0
      # ... all model fields (serialized)
    expected_error: null  # or error description if record should be skipped
    notes: "Standard valid PERM record"
```

**Regeneration:**
```bash
# Collect new samples from all DOL files
bazel run //scripts/salary:collect_dol_golden_test_data

# Customize output location
bazel run //scripts/salary:collect_dol_golden_test_data -- \
  --output tests/data/dol_golden_test_data.yaml \
  --samples-per-file 20
```

**Manual Annotation:**
After running the collection script, manually annotate each test case:
1. Add `record_type`: "SalaryRecord" or "WorksiteRecord"
2. Add `expected_result`: Serialized model dict (use `record.to_dict()`)
3. Add `expected_error`: Error description if record should be skipped
4. Add `notes`: Optional notes explaining edge cases

**Usage:**
```bash
# Run golden test
bazel test //tests:test_dol_transform_golden

# Run specific test categories
bazel test //tests:test_dol_transform_golden --test_filter=TestDOLTransformGolden.test_perm_cases
bazel test //tests:test_dol_transform_golden --test_filter=TestDOLTransformGolden.test_h1b_salary_cases
bazel test //tests:test_dol_transform_golden --test_filter=TestDOLTransformGolden.test_h1b_worksite_cases
```

### `unknown_file_types.txt`

List of files that couldn't be automatically classified as PERM or LCA. Review this file and update `detect_file_type()` in `collect_dol_golden_test_data.py` if needed.

## Test Data Format

### Serialization Format

Test data uses the same serialization format as model `to_dict()` methods:
- Decimal fields → float
- Date fields → ISO format strings (YYYY-MM-DD)
- ForeignKey fields → `field_id` (or None)
- None values explicitly included

### Record Types

- **SalaryRecord**: Standard salary records with employer information
- **WorksiteRecord**: Worksite location records (I-200 case numbers) without employer information

### Validation Failures

Records that should be skipped (validation failures) have:
- `expected_result: null`
- `expected_error: "Error description"` (e.g., "Missing case_number", "Missing employer_name")

## Updating Test Data

1. **Regenerate samples**: Run collection script to get fresh samples
2. **Annotate expected results**: Manually inspect and annotate each test case
3. **Run tests**: Verify all test cases pass
4. **Fix failures**: Update plugin code or expected results as needed

## See Also

- `GOLDEN_TEST_SET_DOL_TRANSFORMS.md` - Complete implementation plan
- `scripts/salary/collect_dol_golden_test_data.py` - Collection script
- `tests/test_dol_transform_golden.py` - Golden test implementation

