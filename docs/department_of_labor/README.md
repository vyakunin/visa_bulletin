# Department of Labor (DOL) Data Documentation

This directory contains documentation specific to Department of Labor (DOL) salary data, including H-1B LCA, PERM, and worksite data.

## Overview

The DOL salary database provides comprehensive data on work visa applications and green card sponsorships, sourced from public DOL disclosure data.

## Documentation Files

### Database Design
- **DATABASE_DESIGN.md** - Database schema, models, and field mappings for salary data
- **VIEWS_PROPOSALS.md** - Proposed database views and query optimizations for common access patterns
- **JOB_TITLE_NORMALIZATION_DESIGN.md** - Design for job title clustering system (reuses employer clustering architecture)

### Data Validation
- **WAGE_THRESHOLDS.md** - Wage validation thresholds and rules for detecting anomalies

### Future Work
- **WORKSITE_FILES_DESIGN.md** - Design for separating worksite location data from employer-focused data (not yet implemented)

## Data Sources

### H-1B LCA (Labor Condition Application)
- Primary focus: Employer information
- Files: `LCA_FY20XX*.xlsx`
- Use case: Search by employer, analyze employer patterns

### PERM (Permanent Labor Certification)
- Primary focus: Green card sponsorship data
- Files: `PERM_FY20XX*.xlsx`
- Use case: Green card sponsorship analysis, approval rates

### Worksite Files
- Primary focus: Worksite location information
- Files: `LCA_Worksites_FY20XX*.xlsx`
- Use case: Geographic distribution, regional salary trends
- **Status:** Currently mixed with employer data, needs separation (see WORKSITE_FILES_DESIGN.md)

## Related Code

- **Models:** `models/salary.py` - Django models for salary records and employers
- **Ingest Plugins:** `lib/ingest/plugins/dol_lca.py`, `lib/ingest/plugins/dol_perm.py`
- **Business Logic:** `lib/business/salary/` - Employer clustering and validation
- **Scripts:** `scripts/salary/` - Import, validation, and analysis scripts

## Quick Start

### Import DOL Data
```bash
# Import all DOL files
bazel run //scripts/salary:import_dol_files

# Import specific file
bazel run //scripts/salary:import_dol_files -- --file data/salary/dol_data/LCA_FY2024.xlsx
```

### Validate Data
```bash
# Run comprehensive validation
bazel run //scripts/salary:validate_data

# Check specific issues
bazel run //scripts/salary:validate_data -- --check-missing-wages
```

### Query Data
```bash
# Explore database interactively
bazel run //:run_sql
```

For ingest pipeline documentation, see `docs/ingest/`.

