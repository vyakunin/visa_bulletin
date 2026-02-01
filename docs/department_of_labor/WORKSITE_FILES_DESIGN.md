# Worksite Files Separation Design

**Date:** December 6, 2025  
**Status:** Design Phase  
**Priority:** Medium

**⚠️ IMPORTANT: Use Unified Ingest Framework**

This implementation **MUST use the unified ingest framework** with plugins (`lib/ingest/`), NOT individual import functions. The framework provides:
- Automatic download, parse, transform, load pipeline
- Checkpoint/resume capability
- Progress tracking and error handling
- Plugin-based architecture for extensibility

**DO NOT create individual importers** like `import_worksite_file()`. Instead, create a plugin in `lib/ingest/plugins/`.

## Problem Statement

### Current Situation

- **78% of salary records (4.5M out of 5.7M) have "Unknown" employers**
- Root cause: Files with "Worksites" in the name have a fundamentally different data structure
- Worksite files contain **worksite location data**, not employer information
- These files are currently being imported into the same `SalaryRecord` table, causing:
  - Confusion in UI (showing "Unknown" employers)
  - Inability to search/filter by employer for worksite records
  - Mixing of two different data types in the same view

### Examples of Worksite Files

Files with 100% "Unknown" employers (worksite format):
- `LCA_Worksites_FY2022_Q4.xlsx` - 601,032 records
- `LCA_FY2020_Worksites.xlsx` - 549,531 records
- `LCA_Worksites_FY2024_Q4.xlsx` - 547,737 records
- `LCA_Worksites_FY2021.xlsx` - 523,692 records
- `LCA_Worksites_FY2023_Q4.xlsx` - 520,264 records
- And 10+ more similar files

### Data Structure Difference

**Regular LCA Files:**
- Primary focus: **Employer information**
- Columns: `EMPLOYER_NAME`, `EMPLOYER_CITY`, `EMPLOYER_STATE`, `WORKSITE_CITY`, `WORKSITE_STATE`
- Use case: Search by employer, analyze employer patterns

**Worksite Files:**
- Primary focus: **Worksite location information**
- Columns: `WORKSITE_CITY`, `WORKSITE_STATE` (no employer columns in same format)
- Use case: Analyze geographic distribution, regional salary trends

## Key Findings (Investigation Complete)

### ✅ Case Number Uniqueness Confirmed

**Investigation Results:**
- **No overlap:** 0 case numbers appear in both worksite and regular files
- **Different prefixes:** Worksite files use "I-200" prefix, regular files use "G-200" prefix
- **Unique within types:** 100% unique case numbers within each file type
- **Database stats:**
  - Worksite files: 3,087,669 records (all unique cases)
  - Regular files: 2,678,316 records (all unique cases)
  - Total: 5,765,985 records = 5,765,985 unique cases

**Conclusion:** ✅ Safe to separate - no migration conflicts expected. Case numbers are completely disjoint between the two file types.

## Proposed Solution

### High-Level Approach

1. **Create separate `WorksiteRecord` model** for worksite file data
2. **Separate import path** for worksite files vs. regular files
3. **Separate UI views** - Don't mix employer-based and worksite-based records
4. **Maintain data integrity** - Keep existing `SalaryRecord` for employer-based data

### Benefits

- ✅ Clear separation of concerns
- ✅ Better UX - no more "Unknown" employers cluttering search results
- ✅ Can optimize queries for each data type separately
- ✅ Enables location-based analytics without employer confusion
- ✅ Maintains backward compatibility with existing salary search

## Data Model Design

### New Model: `WorksiteRecord`

```python
class WorksiteRecord(models.Model):
    """
    Worksite location record from DOL Worksites disclosure files.
    
    These files focus on worksite locations rather than employers,
    so they have a different structure and use case.
    """
    
    # Case identification (same as SalaryRecord)
    case_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="DOL case number (unique identifier)"
    )
    
    visa_program = models.IntegerField(
        choices=VisaProgram.choices,
        db_index=True,
        help_text="Visa program type (H-1B, PERM, etc.)"
    )
    
    case_status = models.IntegerField(
        choices=CaseStatus.choices,
        blank=True,
        null=True,
    )
    
    # Worksite information (PRIMARY focus for these files)
    worksite_city = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Worksite city"
    )
    
    worksite_state = models.CharField(
        max_length=2,
        blank=True,
        db_index=True,
        help_text="Worksite state (2-letter code)"
    )
    
    worksite_zip = models.CharField(
        max_length=10,
        blank=True,
        help_text="Worksite ZIP code (if available)"
    )
    
    # Job details
    job_title = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Job title"
    )
    
    soc_code = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Standard Occupational Classification code"
    )
    
    soc_title = models.CharField(
        max_length=255,
        blank=True,
        help_text="SOC occupation title"
    )
    
    # Wage information
    wage_from = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Wage rate (from)"
    )
    
    wage_to = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Wage rate (to)"
    )
    
    wage_unit = models.CharField(
        max_length=20,
        choices=WageUnit.choices,
        blank=True,
        help_text="Wage unit (hour, year, etc.)"
    )
    
    wage_annual = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        db_index=True,
        help_text="Annual wage (calculated)"
    )
    
    prevailing_wage = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    
    prevailing_wage_unit = models.CharField(
        max_length=20,
        blank=True,
    )
    
    # Dates
    case_submitted = models.DateField(null=True, blank=True)
    decision_date = models.DateField(null=True, blank=True)
    employment_start = models.DateField(null=True, blank=True)
    employment_end = models.DateField(null=True, blank=True)
    
    # Metadata
    fiscal_year = models.IntegerField(
        db_index=True,
        help_text="Fiscal year of the record"
    )
    
    source_file = models.CharField(
        max_length=255,
        blank=True,
        help_text="Source file name"
    )
    
    # NOTE: No employer fields - these files don't have employer data
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'worksite_record'
        ordering = ['-decision_date', '-case_submitted']
        indexes = [
            models.Index(fields=['worksite_state', 'fiscal_year']),
            models.Index(fields=['worksite_city', 'worksite_state']),
            models.Index(fields=['job_title', 'worksite_state']),
            models.Index(fields=['soc_code', 'worksite_state']),
            models.Index(fields=['visa_program', 'fiscal_year']),
            models.Index(fields=['wage_annual']),
        ]
    
    def __str__(self):
        location = f"{self.worksite_city}, {self.worksite_state}" if self.worksite_city else self.worksite_state
        return f"{self.case_number} - {location} - {self.job_title}"
```

### Model Comparison

| Feature | SalaryRecord | WorksiteRecord |
|---------|-------------|----------------|
| **Primary Focus** | Employer information | Worksite location |
| **Employer Fields** | ✅ employer, employer_name, employer_city, employer_state | ❌ None |
| **Worksite Fields** | ✅ worksite_city, worksite_state | ✅ worksite_city, worksite_state, worksite_zip |
| **Wage Fields** | ✅ Full wage information | ✅ Full wage information |
| **Job Fields** | ✅ job_title, soc_code, soc_title | ✅ job_title, soc_code, soc_title |
| **Use Case** | Employer-based search/analysis | Location-based search/analysis |

## Import Pipeline Changes

### Use Unified Ingest Framework

**IMPORTANT:** This project uses the unified ingest framework with plugins. Do NOT create individual import functions.

**Framework Location:** `lib/ingest/` (orchestrator, plugins, registry)

**Existing Plugins:**
- `lib/ingest/plugins/dol_lca.py` - H1BSalaryDataSourcePlugin (for regular LCA files → SalaryRecord)
- `lib/ingest/plugins/dol_perm.py` - PERMSalaryDataSourcePlugin (for PERM files → SalaryRecord)

**Approach:**
1. **Add new SourceType enum** for worksite files (`SourceType.WORKSITE`)
2. **Create plugin** `lib/ingest/plugins/dol_worksite.py` - WorksiteLocationDataSourcePlugin
3. **Plugin transforms to** `WorksiteRecord` model (not SalaryRecord)
4. **Framework handles:** download, parse, transform, load stages automatically

### Plugin Implementation

**File:** `lib/ingest/plugins/dol_worksite.py`

Create new plugin following existing pattern:

```python
class WorksiteLocationDataSourcePlugin(DataSourcePlugin):
    """Plugin for Department of Labor Worksites disclosure data"""
    
    domain = DataDomain.DOL
    source_type = SourceType.WORKSITE  # New source type needed
    data_dir = 'salary/dol_data'
    filename_prefix = 'worksite'
    
    def discover_sources(self) -> list[SourceInfo]:
        """Discover worksite files from DOL website"""
        # Similar to H1BSalaryDataSourcePlugin but filter for 'worksite' in URL/filename
    
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream parse worksite Excel/CSV files"""
        # Reuse parsing logic from H1BSalaryDataSourcePlugin (openpyxl streaming)
        # Worksite files use same Excel format, different columns
    
    def transform(self, record: dict) -> WorksiteRecord | None:
        """Transform to WorksiteRecord (NOT SalaryRecord)"""
        # Use WORKSITE_COLUMN_MAPPINGS (no employer fields)
        # Return WorksiteRecord instance or None if invalid
```

### Add New SourceType Enum

**File:** `models/ingest/enums.py`

Add worksite source type:

```python
class SourceType(models.TextChoices):
    LCA = 'lca', 'LCA (H-1B)'
    PERM = 'perm', 'PERM'
    BULLETIN = 'bulletin', 'Visa Bulletin'
    WORKSITE = 'worksite', 'Worksite Location Data'  # NEW
```

### Column Mappings for Worksite Files

**File:** `lib/parsing/salary/file_detection.py` (already created)

Add column mappings there or in plugin:

```python
WORKSITE_COLUMN_MAPPINGS = {
    'case_number': ['CASE_NUMBER', 'LCA_CASE_NUMBER'],
    'case_status': ['CASE_STATUS', 'STATUS'],
    # NO employer fields - worksite files don't have them
    'worksite_city': ['WORKSITE_CITY', 'WORK_CITY', 'LCA_CASE_WORKLOC1_CITY'],
    'worksite_state': ['WORKSITE_STATE', 'WORK_STATE', 'LCA_CASE_WORKLOC1_STATE'],
    'worksite_zip': ['WORKSITE_ZIP', 'WORK_ZIP', 'ZIP_CODE'],
    'job_title': ['JOB_TITLE', 'LCA_CASE_JOB_TITLE'],
    'soc_code': ['SOC_CODE', 'LCA_CASE_SOC_CODE'],
    'soc_title': ['SOC_TITLE', 'LCA_CASE_SOC_NAME'],
    'wage_from': ['WAGE_RATE_OF_PAY_FROM', 'LCA_CASE_WAGE_RATE_FROM'],
    'wage_to': ['WAGE_RATE_OF_PAY_TO', 'LCA_CASE_WAGE_RATE_TO'],
    'wage_unit': ['WAGE_UNIT_OF_PAY', 'LCA_CASE_WAGE_RATE_UNIT'],
    'prevailing_wage': ['PREVAILING_WAGE', 'PW_WAGE_LEVEL'],
    'prevailing_wage_unit': ['PW_UNIT_OF_PAY'],
    'case_submitted': ['RECEIVED_DATE', 'LCA_CASE_SUBMIT'],
    'decision_date': ['DECISION_DATE', 'LCA_CASE_CERTIFICATION'],
    'employment_start': ['BEGIN_DATE', 'LCA_CASE_EMPLOYMENT_START_DATE'],
    'employment_end': ['END_DATE', 'LCA_CASE_EMPLOYMENT_END_DATE'],
}
```

### File Detection

**File:** `lib/parsing/salary/file_detection.py` (already created)

Function already implemented - use for discovery logic:

```python
def is_worksite_file(filename: str) -> bool:
    """Detect if a file is a worksite file based on filename"""
    filename_lower = filename.lower()
    return 'worksite' in filename_lower or 'worksites' in filename_lower
```

### Plugin Registration

Plugins are auto-registered via `lib/ingest/plugins/__init__.py` - just import the plugin class and it registers automatically.

### Usage

**Via unified ingest orchestrator:**
```python
# Plugin automatically handles:
# 1. Discovery of worksite files from DOL website
# 2. Download with resume support
# 3. Streaming parse (openpyxl)
# 4. Transform to WorksiteRecord
# 5. Bulk insert with checkpoint/resume

# Run via orchestrator:
orchestrator = PipelineOrchestrator()
orchestrator.run_ingest(domain=DataDomain.DOL, source_type=SourceType.WORKSITE)
```

**No separate import script needed** - unified framework handles everything.

## UI Separation

### Current UI: `/salaries/` (Salary Search)

**Keep for:** `SalaryRecord` only (employer-based data)

**Filters:**
- ✅ Employer name
- ✅ Job title
- ✅ State (worksite state)
- ✅ Visa program
- ✅ Fiscal year

**Remove/Clarify:**
- ❌ Don't show worksite records here
- ✅ Clear labeling: "Search by Employer"

### New UI: `/worksites/` (Worksite Search)

**New view for:** `WorksiteRecord` only (location-based data)

**Filters:**
- ✅ Worksite city
- ✅ Worksite state
- ✅ Job title
- ✅ SOC code
- ✅ Visa program
- ✅ Fiscal year
- ✅ Salary range

**Features:**
- Map view (geographic distribution)
- Regional salary trends
- City/state analytics
- No employer filter (data not available)

### Navigation

```
/salaries/     → Employer-based salary search
/worksites/    → Location-based worksite search
```

## Migration Strategy

### Phase 1: Data Migration

1. **Create `WorksiteRecord` model** and migration
2. **Identify existing worksite records** in `SalaryRecord`:
   ```sql
   SELECT * FROM salary_record 
   WHERE source_file LIKE '%worksite%' 
      OR source_file LIKE '%Worksite%'
      OR employer_name = 'Unknown'
   ```
   **Note:** Case numbers from worksite files start with "I-200" prefix (different from regular files "G-200"), making identification straightforward.
3. **Migrate data** from `SalaryRecord` to `WorksiteRecord`:
   - Copy worksite-based records to new table
   - Map fields appropriately
   - Preserve case numbers (they are unique - no conflicts expected)
   - **Safe migration:** Case numbers are completely disjoint (0 overlap confirmed)
4. **Delete migrated records** from `SalaryRecord` (or mark as migrated)

### Phase 2: Import Pipeline

1. **Update import scripts** to detect worksite files
2. **Create `import_worksite_file()` function**
3. **Update file processing** to route to correct import function
4. **Test with sample worksite files**

### Phase 3: UI Updates

1. **Create `/worksites/` view** (new template and view)
2. **Update `/salaries/` view** to exclude worksite records
3. **Add navigation** between the two views
4. **Update search/filter logic**

### Phase 4: Cleanup

1. **Remove "Unknown" employer handling** from salary search
2. **Update analytics/aggregations** to use correct models
3. **Update documentation**

## Implementation Steps

### Step 1: Model & Migration

- [x] Create `WorksiteRecord` model in `models/salary.py`
- [ ] Add model to Django admin (optional - skipped for now)
- [ ] Create and run migration (blocked by makemigrations issue - user to fix separately)
- [x] Add indexes for performance

### Step 2: Add SourceType Enum

- [x] Add `SourceType.WORKSITE` to `models/ingest/enums.py`
- [ ] Create migration for enum change (blocked by makemigrations issue)

### Step 3: Create Plugin

- [x] Create `lib/ingest/plugins/dol_worksite.py`
- [x] Implement `WorksiteLocationDataSourcePlugin(DataSourcePlugin)`:
  - [x] `discover_sources()` - Find worksite files from DOL website
  - [x] `parse()` - Stream parse Excel/CSV (reuse openpyxl pattern)
  - [x] `transform()` - Transform to `WorksiteRecord` (NOT SalaryRecord)
  - [x] `get_format_version()` - Detect format version
  - [x] `validate_post_ingest()` - Post-ingest validation (added by user)
- [x] Add `WORKSITE_COLUMN_MAPPINGS` in `lib/parsing/salary/file_detection.py` (shared location)
- [x] Plugin available in `lib/ingest/plugins/__init__.py` exports
- [x] Add plugin to BUILD file

### Step 5: Data Migration Script

- [x] ~~Create `scripts/salary/migrate_worksites.py`~~ (Completed and removed)
- [x] Identify existing worksite records
- [x] Migrate to `WorksiteRecord`
- [ ] Delete from `SalaryRecord`
- [ ] Validate migration (counts, sample records)

### Step 6: UI Views

- [ ] Create `webapp/views.py::worksite_search_view()`
- [ ] Create `webapp/templates/webapp/worksite_search.html`
- [ ] Update `webapp/urls.py` with `/worksites/` route
- [ ] Update `salary_search_view()` to exclude worksite records

### Step 7: Testing

- [x] Unit tests for `WorksiteRecord` model (`tests/test_worksite_record.py`)
- [x] Integration tests for worksite import (`tests/test_worksite_plugin.py`)
- [ ] Test migration script on sample data
- [ ] Test UI views with sample data

## File Structure

```
models/
  salary.py                    # Add WorksiteRecord model
  ingest/
    enums.py                   # Add SourceType.WORKSITE enum

lib/ingest/plugins/
  dol_lca.py                   # Existing - regular LCA files → SalaryRecord
  dol_perm.py                  # Existing - PERM files → SalaryRecord
  dol_worksite.py              # NEW - worksite files → WorksiteRecord

lib/parsing/salary/
  file_detection.py            # NEW - is_worksite_file() function
  wage_unit_correction.py      # Shared validation logic

scripts/salary/
  # migrate_worksites.py - Completed and removed

webapp/
  views.py                     # Add worksite_search_view
  templates/webapp/
    salary_search.html         # Existing - employer-based (exclude worksites)
    worksite_search.html       # NEW - location-based
  urls.py                      # Add /worksites/ route
```

**Note:** No individual importer needed - unified ingest framework handles everything via plugins.

## Database Impact

### New Table

- `worksite_record` - New table for worksite data
- **Actual size:** 3,087,669 records (confirmed from database investigation)
- All case numbers start with "I-200" prefix (unique identifier)
- Similar structure to `salary_record` but without employer fields

### Existing Table

- `salary_record` - Remove 3,087,669 worksite records
- Result: Cleaner data, all records have actual employer information
- **Actual remaining:** 2,678,316 records (employer-based)
- All remaining case numbers start with "G-200" prefix

### Indexes

Both tables will need similar indexes for performance:
- Worksite state/city
- Fiscal year
- Job title
- SOC code
- Wage/annual wage

## Open Questions

1. **Case Number Uniqueness**: ✅ **RESOLVED**
   - ✅ **NO OVERLAP** - Case numbers are completely unique between file types
   - ✅ **Different prefixes**: Worksite files use "I-200" prefix, regular files use "G-200" prefix
   - ✅ **Within-type uniqueness**: 100% unique within each file type
   - **Investigation Results:**
     - Worksite files: 3,087,669 records = 3,087,669 unique cases (all start with "I-200")
     - Regular files: 2,678,316 records = 2,678,316 unique cases (all start with "G-200")
     - Overlap check: **0 cases** appear in both types
     - Total database: 5,765,985 records = 5,765,985 unique cases
   - **Conclusion:** Safe to separate - no migration conflicts expected

2. **Worksite File Format Variations**:
   - Do all worksite files have the same column structure?
   - Are there variations by fiscal year?
   - **Action:** Sample multiple worksite files to verify

3. **Backward Compatibility**:
   - Should we maintain a flag on old records indicating they were migrated?
   - Or just delete and re-import from worksite files?
   - **Recommendation:** Re-import from source files for data integrity

4. **Historical Data**:
   - Should we migrate existing worksite records or just start fresh?
   - **Recommendation:** Start fresh - re-import worksite files to `WorksiteRecord`

5. **Analytics/Aggregations**:
   - How should reports handle both data types?
   - Separate reports or combined with clear labeling?
   - **Recommendation:** Separate reports with option to combine

## Success Criteria

- [ ] Zero "Unknown" employers in `/salaries/` view
- [ ] All worksite records accessible via `/worksites/` view
- [ ] Import pipeline correctly routes files to appropriate models
- [ ] No data loss during migration
- [ ] Performance acceptable for both views
- [ ] Clear separation in UI (no mixing of data types)

## Timeline Estimate

- **Model & Migration:** 2-3 days
- **Plugin Development:** 2-3 days (using unified ingest framework)
- **Data Migration:** 1-2 days (testing + execution)
- **UI Updates:** 3-4 days
- **Testing & Refinement:** 2-3 days

**Total:** ~2-3 weeks

**Note:** Plugin development is faster than individual importers - framework handles download, parse, transform, load pipeline automatically.

## Risks & Mitigations

### Risk 1: Case Number Collisions ✅ **MITIGATED**
- **Risk:** Same case number in both file types
- **Investigation Result:** ✅ **No collisions found** - case numbers are completely unique
- **Evidence:** 
  - Worksite files: All case numbers start with "I-200" (different prefix)
  - Regular files: All case numbers start with "G-200" (different prefix)
  - Overlap query: 0 cases found in both types
- **Conclusion:** No mitigation needed - separation is safe

### Risk 2: Data Loss
- **Risk:** Migration might lose data
- **Mitigation:** 
  - Backup database before migration
  - Validate counts before/after
  - Keep migrated records flagged initially (soft delete)

### Risk 3: Performance Impact
- **Risk:** Large migration might impact database
- **Mitigation:** 
  - Run during off-peak hours
  - Batch processing
  - Monitor database performance

### Risk 4: Import Complexity
- **Risk:** Worksite files might have unexpected formats
- **Mitigation:** 
  - Sample multiple files first
  - Flexible column mapping
  - Robust error handling

## Next Steps

1. **Review this design** - Get feedback on approach
2. **Investigate file formats** - Sample worksite files to verify structure
3. **Check case number overlap** - Verify uniqueness across file types
4. **Create prototype** - Start with model and basic import function
5. **Plan migration** - Detail the migration script approach

