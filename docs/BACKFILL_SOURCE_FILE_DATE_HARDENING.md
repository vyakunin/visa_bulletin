# Filing Date Migration: From Publication Year to Filing Date

## Goal

Migrate the primary time-axis filter from `fiscal_year` (an integer extracted from the source filename, e.g. "FY2024") to `case_submitted` (the actual date the employer filed the application). This gives users a more meaningful and accurate time dimension. `source_file_date` continues to serve its role in duplicate resolution but is not the end-user filter.

---

## Current State

### Three date/time concepts on SalaryRecord

| Field | Type | Source | Null? | Indexed? | Purpose |
|-------|------|--------|-------|----------|---------|
| `fiscal_year` | `IntegerField` | Filename pattern (`FY2024`, `20##`) | No | Yes (single + 4 composites) | Primary time filter today |
| `case_submitted` | `DateField` | CSV column (`RECEIVED_DATE`, `LCA_CASE_SUBMIT`, etc.) | Yes | No dedicated index | Filing Year filter (secondary) |
| `source_file_date` | `DateTimeField` | File mtime or filename-derived Jan 1 of FY | Yes | Yes (single) | Duplicate resolution |
| `decision_date` | `DateField` | CSV column (`DECISION_DATE`) | Yes | Yes (single + 1 composite) | Sort order, display |

### How filters work today

**Salary search** (`webapp/views/salary/search.py`):
- Two dropdowns: "Fiscal Year" (`fiscal_year` field) and "Filing Year" (`case_submitted__year`)
- Default sort: `-wage_annual, -fiscal_year`
- Employer profile: filters by `fiscal_year__gte` for the time window

**Business logic** (`lib/business/salary/`):
- `common_stats.py`: YoY trends group by `fiscal_year`
- `job_title_stats.py`: filters by `fiscal_year__gte` for time window
- `market_overview.py`: uses `fiscal_year` for aggregation
- `common_chart_builder.py`: uses `fiscal_year` for chart x-axis

### Problems with fiscal_year as primary filter

1. **Semantically wrong**: FY2024 means "this record was in a file published as FY2024", not "the employer filed this in 2024." A case filed in October 2023 appears in FY2024.
2. **Coarse granularity**: Only year-level, no month/quarter filtering possible.
3. **Filename-dependent**: If DOL changes naming conventions, extraction breaks.
4. **Duplicates across FYs**: The same case can appear in multiple fiscal year files (updated status). `fiscal_year` reflects the last file it was seen in, not when it was filed.

### Why case_submitted is better

- It is the actual date the employer submitted the application.
- It comes from the CSV data (authoritative).
- It enables month/quarter/year filtering.
- It is semantically correct for "when was this filed?"

### Data completeness concern

`case_submitted` is nullable. Some older records or certain file formats may not have it. Before migrating, we need to verify coverage and fill gaps where possible.

---

## Phase 1: Data Foundation (ensure case_submitted is comprehensive)

### 1.1 Audit case_submitted coverage

Run a query to assess how many records lack `case_submitted`:

```sql
SELECT
    fiscal_year,
    COUNT(*) AS total,
    COUNT(case_submitted) AS has_case_submitted,
    ROUND(100.0 * COUNT(case_submitted) / COUNT(*), 1) AS pct
FROM salary_record
GROUP BY fiscal_year
ORDER BY fiscal_year;
```

This tells us per-FY how complete the data is. If coverage is >95% across all FYs, migration is straightforward. If certain FYs have low coverage, we need targeted backfill.

### 1.2 Backfill case_submitted from decision_date (where missing)

For records where `case_submitted IS NULL` but `decision_date IS NOT NULL`, we can approximate: filing date is typically 1-6 months before decision. We should NOT silently copy `decision_date` to `case_submitted` (they are different events), but we can:

- Option A: Leave `case_submitted` null; these records appear under "All Years" but not under any specific filing year. (Safest.)
- Option B: Derive an approximate filing year from `decision_date - interval '3 months'` and store it in a new `filing_year_approx` field. (More complex, questionable value.)

**Recommendation:** Option A. If coverage is >95%, the remaining records are acceptable as "unknown filing date."

### 1.3 Index case_submitted for filtering

`case_submitted` currently has no dedicated index. Add:

```python
# In SalaryRecord Meta.indexes:
models.Index(fields=['case_submitted']),
models.Index(fields=['visa_program', 'case_submitted']),
```

The second composite index supports the common filter pattern: program + year.

**File:** `models/salary.py` lines 524-550 (Meta.indexes)

### 1.4 Harden backfill_source_file_date.py

This script populates `source_file_date` (used for duplicate resolution, not user filtering). It has several bugs that need fixing regardless of the migration:

**Issues (7 total):**

1. **N+1 on DataSource lookup** (lines 77-79): `DataSource.objects.filter(...).first()` per record. Fix: pre-load into dict. DataSource typically has <5k rows (~1 MB via `.values()`).

2. **N+1 on ingest_version.run** (lines 69-70): accessing `record.ingest_version.run` without `select_related`. Fix: add `.select_related('ingest_version__run')` to the queryset.

3. **Silent exception swallowing** (lines 82-83): bare `except Exception: pass`. Fix: log the error.

4. **Local import inside loop** (line 73): `from models.ingest.data_source import DataSource` inside the loop body. Fix: move to top of file.

5. **Uses print() instead of logger** (lines 48-50, 94-95, 100-105). Fix: replace with `logger.info()`.

6. **Dead variable** (line 64): `skipped_count` declared but never incremented. Fix: remove or wire up.

7. **No ScriptLogger** for usage tracking. Fix: use `ScriptLogger(__file__)`.

**Implementation order:** Issues 2-7 are trivial one-line fixes. Issue 1 is a moderate refactor (pre-load DataSource lookup).

**File:** `scripts/salary/backfill_source_file_date.py`

---

## Phase 2: Migrate filters from fiscal_year to case_submitted

### 2.1 Replace "Fiscal Year" dropdown with "Filing Year" as primary

Currently the search page has two dropdowns. After migration:

- **Primary:** "Filing Year" (from `case_submitted__year`) -- already exists as secondary filter
- **Deprecated:** "Fiscal Year" dropdown removed or moved to "Advanced" toggle

**Files:**
- `webapp/views/salary/search.py` -- make filing_year the default, remove or hide fiscal_year
- `webapp/templates/webapp/salary_search.html` -- update dropdown order/visibility
- `webapp/forms.py` -- update form field ordering

### 2.2 Update business logic to use case_submitted

**YoY trends** (`lib/business/salary/common_stats.py` line 38):
```python
# Before:
queryset.values("fiscal_year")

# After:
from django.db.models.functions import ExtractYear
queryset.annotate(filing_year=ExtractYear('case_submitted')).values("filing_year")
```

**Job title stats** (`lib/business/salary/job_title_stats.py` line 83):
```python
# Before:
'fiscal_year__gte': start_year,

# After:
'case_submitted__year__gte': start_year,
```

**Employer profile** (`webapp/views/employers/profile.py` line 83):
```python
# Before:
fiscal_year__gte=params['start_year'],

# After:
case_submitted__year__gte=params['start_year'],
```

**Files to update:**
- `lib/business/salary/common_stats.py` -- YoY grouping
- `lib/business/salary/job_title_stats.py` -- time window filter
- `lib/business/salary/market_overview.py` -- aggregation
- `lib/business/salary/common_chart_builder.py` -- chart x-axis
- `webapp/views/employers/profile.py` -- employer profile filters

### 2.3 Handle records with null case_submitted

Records where `case_submitted IS NULL` should:
- Still appear in unfiltered views (no year selected)
- NOT appear when a specific filing year is selected (they have unknown filing date)
- Display "N/A" or the fiscal year as fallback in the results table

This is already the behavior of `apply_filing_year_filter()` (it filters by `case_submitted__year`, which excludes nulls).

### 2.4 Update default sort order

Currently: `-wage_annual, -fiscal_year` (line 249 of search.py)

After: `-wage_annual, -case_submitted` (nulls last)

```python
records.order_by('-wage_annual', F('case_submitted').desc(nulls_last=True))
```

### 2.5 Update cache keys

Filing year list changes less often than fiscal year (both change only when new data is imported). Cache key names should be updated for clarity:

- `salary_fiscal_years` -> `salary_filing_years` (already exists)
- Remove the `salary_fiscal_years` cache population if fiscal year dropdown is removed

---

## Phase 3: Update composite indexes

### 3.1 Add case_submitted composite indexes

To match the performance of fiscal_year composites, add equivalents:

```python
models.Index(fields=['visa_program', 'case_submitted']),
models.Index(fields=['worksite_state', 'case_submitted']),
```

### 3.2 Evaluate dropping fiscal_year composites

After migration, the following indexes may become unused:
- `['visa_program', 'fiscal_year']`
- `['worksite_state', 'fiscal_year']`
- `['fiscal_year', 'decision_date']`
- `['employer', 'is_worksite', 'fiscal_year']` (INCLUDE `wage_annual`)

**Do not drop immediately.** Keep for one release cycle. Monitor query plans using `EXPLAIN ANALYZE` to confirm they are no longer used. Then remove in a follow-up migration.

### 3.3 Update the employer profile covering index

The covering index `sr_emp_wk_fy_inc_wage` on `(employer, is_worksite, fiscal_year) INCLUDE (wage_annual)` needs a `case_submitted` equivalent:

```python
models.Index(
    fields=['employer', 'is_worksite'],
    include=['wage_annual', 'case_submitted'],
    name='sr_emp_wk_inc_wage_cs',
),
```

This supports the employer profile query: `WHERE employer_id IN (...) AND is_worksite=false AND case_submitted >= ?`.

---

## Phase 4: Worksite records

`WorksiteRecord` also has `fiscal_year` and `case_submitted`. The same migration applies, but worksite search is simpler (only fiscal_year dropdown, no filing_year dropdown currently).

**Files:**
- `webapp/views/salary/search.py` -- `worksite_search()` function
- `webapp/templates/webapp/worksite_search.html`
- `models/salary.py` -- WorksiteRecord Meta.indexes

---

## Phase 5: Keep fiscal_year for internal use

`fiscal_year` should NOT be deleted from the model. It remains useful for:
- Identifying which DOL file a record came from (data provenance)
- Ingestion deduplication logic
- Admin/debugging queries

It just stops being the user-facing time filter.

---

## Implementation Order

1. **Audit** (Phase 1.1): Run coverage query. Determine if case_submitted coverage is sufficient (>95%).
2. **Harden backfill script** (Phase 1.4): Fix the 7 issues in `backfill_source_file_date.py`.
3. **Add indexes** (Phase 1.3 + 3.1): Create migration for `case_submitted` composite indexes.
4. **Migrate filters** (Phase 2.1-2.5): Update views, business logic, templates, sort order, caches.
5. **Worksite** (Phase 4): Apply same changes to worksite search.
6. **Monitor and clean up** (Phase 3.2): After one release cycle, drop unused fiscal_year indexes.

---

## Cleanup (Post-Implementation)

- [ ] Extract any reusable patterns into permanent docs or rule files
- [ ] Update `scripts/README.md` if backfill script interface changes
- [ ] Run updated pipeline on staging to verify end-to-end
- [ ] Delete this document after implementation is complete
