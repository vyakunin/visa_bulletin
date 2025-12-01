# Visa Bulletin Time Series Data Implementation Plan

## Goal
Convert parsed visa bulletin tables into structured time-series data for analysis.

## Data Model

### Core Concepts
1. **Bulletin**: Monthly publication (e.g., "December 2025")
2. **Visa Cutoff Date**: Individual data point representing:
   - Which bulletin it's from
   - Which visa category (Family/Employment)
   - Which specific class (F1, EB-2, etc.)
   - Action type (Final Action vs Filing)
   - Country/region
   - The actual priority date cutoff

### Database Schema

```sql
-- Bulletin (monthly publication)
CREATE TABLE bulletin (
    id INTEGER PRIMARY KEY,
    publication_date DATE UNIQUE NOT NULL,  -- First day of month
    fetched_at TIMESTAMP NOT NULL
);

-- Visa Cutoff Date (time series data point)
CREATE TABLE visa_cutoff_date (
    id INTEGER PRIMARY KEY,
    bulletin_id INTEGER NOT NULL,
    visa_category VARCHAR(20) NOT NULL,     -- FAMILY_SPONSORED, EMPLOYMENT_BASED
    visa_class VARCHAR(20) NOT NULL,        -- F1, F2A, EB1, EB2, etc.
    action_type VARCHAR(20) NOT NULL,       -- FINAL_ACTION, FILING
    country VARCHAR(50) NOT NULL,           -- ALL, CHINA, INDIA, MEXICO, PHILIPPINES
    cutoff_value VARCHAR(20) NOT NULL,      -- Date string, "C", or "U"
    cutoff_date DATE,                       -- Parsed date (NULL for C/U)
    is_current BOOLEAN NOT NULL,            -- True if "C"
    is_unavailable BOOLEAN NOT NULL,        -- True if "U"
    FOREIGN KEY (bulletin_id) REFERENCES bulletin(id),
    UNIQUE(bulletin_id, visa_category, visa_class, action_type, country)
);

-- Index for time-series queries
CREATE INDEX idx_cutoff_timeseries ON visa_cutoff_date(
    visa_class, country, action_type, bulletin_id
);
```

## Enums (One per file)

1. **VisaCategory**: FAMILY_SPONSORED, EMPLOYMENT_BASED
2. **ActionType**: FINAL_ACTION, FILING
3. **Country**: ALL, CHINA, INDIA, MEXICO, PHILIPPINES, EL_SALVADOR_GUATEMALA_HONDURAS
4. **FamilyPreference**: F1, F2A, F2B, F3, F4
5. **EmploymentPreference**: EB1, EB2, EB3, OTHER_WORKERS, EB4, RELIGIOUS_WORKERS, EB5_*

## Implementation Phases

### Phase 1: Setup Django & Enums (TDD)
- [ ] Install Django
- [ ] Create Django project structure
- [ ] Write failing tests for enums
- [ ] Implement enums (one file each)
- [ ] Create Bazel targets for enums

### Phase 2: Django Models (TDD)
- [ ] Write failing tests for Bulletin model
- [ ] Write failing tests for VisaCutoffDate model
- [ ] Implement Django models
- [ ] Configure SQLite database
- [ ] Test migrations

### Phase 3: Extractor Logic (TDD)
- [ ] Write failing test: extract F1 data from sample table
- [ ] Write failing test: handle "C" (Current) values
- [ ] Write failing test: handle "U" (Unavailable) values
- [ ] Write failing test: parse date strings (DDMmmYY)
- [ ] Implement BulletinExtractor class
- [ ] Test with real saved bulletins

### Phase 4: Integration
- [ ] Write failing test: save new bulletin to DB
- [ ] Implement save_bulletin_to_db handler
- [ ] Integrate with refresh_data.py
- [ ] Add DB queries for analysis
- [ ] Create Bazel targets

## Example Usage

```python
# Extract from parsed table
extractor = BulletinExtractor(publication_date="2025-12-01")
cutoff_dates = extractor.extract_from_table(table)

# Save to database
bulletin = Bulletin.objects.create(publication_date="2025-12-01")
for cutoff_data in cutoff_dates:
    VisaCutoffDate.objects.create(bulletin=bulletin, **cutoff_data)

# Query time series
f1_china_history = VisaCutoffDate.objects.filter(
    visa_class=FamilyPreference.F1,
    country=Country.CHINA,
    action_type=ActionType.FINAL_ACTION
).order_by('bulletin__publication_date')
```

## Testing Strategy

### Unit Tests
- Enum validation
- Model creation and constraints
- Extractor logic with mock tables

### Integration Tests
- Extract real bulletin → save to DB → query back
- Handle duplicate bulletins (idempotent)
- Test with actual saved_pages/*.html files

## Benefits

1. **Structured Data**: Easy to query and analyze trends
2. **Time Series**: Track how cutoff dates change over time
3. **Flexible Queries**: Filter by any combination of dimensions
4. **Historical Analysis**: Compare trends across visa classes
5. **Data Integrity**: Django models ensure consistency

## Next Steps

Start with Phase 1: Create enums with failing tests first (TDD approach).

