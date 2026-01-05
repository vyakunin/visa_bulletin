# Comprehensive Threshold Analysis

## Questions Answered

### 1. Is `lib/ingest/plugins/salary_validation.py` needed having `validate_data.py`?

**Answer: YES, they serve different purposes.**

#### `lib/ingest/plugins/salary_validation.py`
- **Purpose:** Post-ingest validation that runs **automatically** in the ingest pipeline
- **When:** Runs immediately after data is loaded (before version activation)
- **Scope:** Validates only the **newly ingested records** from current run
- **Action:** Can **abort the pipeline** if critical errors found
- **Usage:** Called by plugins (H1BSalaryDataSourcePlugin, PERMSalaryDataSourcePlugin)
- **Function:** `validate_salary_records_post_ingest(run, visa_program, program_name)`

#### `scripts/salary/validate_data.py`
- **Purpose:** Comprehensive validation script for **manual analysis**
- **When:** Run manually by developers/admins
- **Scope:** Validates **all data** in database (historical + new)
- **Action:** Generates reports, doesn't abort anything
- **Usage:** Ad-hoc validation, troubleshooting, audits
- **Features:** 
  - Import completeness checks
  - Golden set tracking
  - Homepage query testing
  - Spot checks by groups
  - JSON report generation

**Recommendation:** **Keep both.**
- `salary_validation.py` is part of the automated pipeline (critical for data quality)
- `validate_data.py` is a comprehensive diagnostic tool (critical for troubleshooting)

**Action Item:** Refactor `salary_validation.py` to import thresholds from `wage_unit_correction.py` instead of hardcoding them.

---

### 2. Are `fix_high_wage_records.py` and `fix_calculation.py` duplicates?

**Answer: YES, significant overlap. Should consolidate.**

#### `fix_high_wage_records.py`
- **Purpose:** Fix records with wages > $1M
- **Approach:** Categorizes into parsing_errors, data_errors, edge_cases
- **Features:**
  - Categorization logic
  - Legitimacy checks (high-paying employers/roles)
  - Dry-run mode
  - Category filtering
  - Uses `BatchedUpdateCollector` ✅
  - Imports from `wage_unit_correction.py` ✅

#### `fix_calculation.py`
- **Purpose:** Fix salary calculation issues (incorrect wage_annual)
- **Approach:** Analyzes by wage unit, fixes unit-specific issues
- **Features:**
  - Analysis by wage unit
  - Suspicious job title detection
  - Fixes HOUR, BI_WEEKLY, WEEK, MONTH, YEAR units separately
  - Uses `BatchedUpdateCollector` ✅
  - **Has inconsistent monthly threshold: 85000 vs 50000** ❌

**Overlap:**
- Both fix high wage records (>$1M)
- Both use `should_correct_wage_unit()` from `wage_unit_correction.py`
- Both use `BatchedUpdateCollector` for performance
- Both have dry-run modes
- Both analyze and fix wage unit issues

**Recommendation: CONSOLIDATE into `fix_high_wage_records.py`**

**Why keep `fix_high_wage_records.py`:**
- More comprehensive categorization
- Better legitimacy checks
- Already imports from `wage_unit_correction.py`
- More maintainable structure

**What to migrate from `fix_calculation.py`:**
- Suspicious job title detection logic
- Per-unit analysis breakdown
- Any unique fix logic not in `fix_high_wage_records.py`

**Action Items:**
1. Merge unique logic from `fix_calculation.py` into `fix_high_wage_records.py`
2. Delete `fix_calculation.py`
3. Update BUILD file
4. Update `scripts/README.md`

---

### 3. Why do we have 2 MD files?

**Answer: They serve different purposes (audit vs results).**

#### `HARDCODED_THRESHOLDS_SUMMARY.md`
- **Purpose:** Audit document - lists all hardcoded thresholds found
- **Content:** 
  - Where hardcoded thresholds exist
  - What needs refactoring
  - Recommended fixes
  - Action items (priority 1, 2)
- **Audience:** Developers doing refactoring work
- **Lifecycle:** Reference document (keep until refactoring done)

#### `THRESHOLD_AUDIT_RESULTS.md`
- **Purpose:** Execution results - what happened when we ran the script
- **Content:**
  - Statistics collected (mean, std, median)
  - New thresholds calculated
  - Performance metrics
  - Analysis of results
- **Audience:** Stakeholders reviewing threshold updates
- **Lifecycle:** Historical record (archive after work complete)

**Recommendation: Keep both for now, archive after refactoring complete.**

**Better naming:**
- `HARDCODED_THRESHOLDS_AUDIT.md` (what needs fixing)
- `THRESHOLD_UPDATE_2026-01-04.md` (what we did)

---

### 4. What's difference between `reasonable_annual_range` and `validation_thresholds`?

#### `reasonable_annual_range` (lines 11-13)
```yaml
reasonable_annual_range:
  min: 39000   # p5 percentile
  max: 430000  # p99 percentile
```

**Purpose:** Define the "normal" salary range for **correction logic**
- Used by `should_correct_wage_unit()` to detect misclassified wage units
- If a value falls outside this range, it might indicate wrong unit
- Example: $500,000 annual might actually be hourly ($500/hr stored as annual)
- **Captures 94% of data (p5 to p99)**

#### `validation_thresholds` (lines 14-16)
```yaml
validation_thresholds:
  min_valid_annual: 10000    # Absolute minimum
  max_valid_annual: 10000000 # Absolute maximum
```

**Purpose:** Define **absolute boundaries** for data acceptance
- Used during **import** to reject obviously invalid data
- Much wider range than reasonable_annual_range
- Prevents importing garbage data (typos, parsing errors)
- Example: $5 annual → reject (below min_valid_annual)
- Example: $50M annual → reject (above max_valid_annual)

**Analogy:**
- `reasonable_annual_range`: "Normal human height is 4'10" - 6'6" (p5-p99)"
- `validation_thresholds`: "Valid human height is 1' - 9' (absolute limits)"

**Usage:**
```python
# During import (validation_thresholds)
if wage_annual < 10000 or wage_annual > 10000000:
    reject_record()  # Garbage data

# During correction (reasonable_annual_range)
if wage_annual < 39000 or wage_annual > 430000:
    check_if_unit_is_wrong()  # Might be fixable
```

---

### 5. Propose sigma-based thresholds and compare

#### Sigma-Based Threshold Analysis

**Current Statistics (from 11,519 records, FY 2025-2026):**
- Mean: $142,384
- Std Dev: $84,771
- Median: $129,000

**Sigma-Based Thresholds:**

| Sigma | Range | Coverage | Use Case |
|-------|-------|----------|----------|
| **2σ** | $0 - $312K | ~95% | Too tight (excludes legitimate high earners) |
| **2.5σ** | $0 - $354K | ~98.8% | Better, but still might miss some valid cases |
| **3σ** | $0 - $397K | ~99.7% | Good balance |
| **3.5σ** | $0 - $439K | ~99.95% | Very safe |
| **4σ** | $0 - $481K | ~99.99% | Extremely safe |

**Current Thresholds (Percentile-Based):**
- **reasonable_annual_range:** $39K - $430K (p5 to p99, captures 94%)
- **validation_thresholds:** $10K - $10M (absolute limits)

#### Comparison

```
Method                  Min        Max        Coverage
─────────────────────────────────────────────────────────
Current (p5-p99)        $39,000    $430,000   94%
2σ                      $0         $312,000   ~95%
3σ                      $0         $397,000   ~99.7%
3.5σ                    $0         $439,000   ~99.95%
4σ                      $0         $481,000   ~99.99%
```

#### Recommendations

**For `reasonable_annual_range` (correction logic):**

**Option 1: Use 3σ (recommended)**
```yaml
reasonable_annual_range:
  min: 0        # mean - 3σ (capped at 0)
  max: 397000   # mean + 3σ
```
- Captures 99.7% of data
- Slightly tighter than current p99 ($430K)
- More statistically principled
- Automatically adjusts with distribution changes

**Option 2: Use 3.5σ (safer)**
```yaml
reasonable_annual_range:
  min: 0        # mean - 3.5σ (capped at 0)
  max: 439000   # mean + 3.5σ
```
- Captures 99.95% of data
- Very close to current p99 ($430K)
- Extremely safe (almost no false positives)

**For `validation_thresholds` (absolute limits):**

**Recommended: Use 4σ or 5σ**
```yaml
validation_thresholds:
  min_valid_annual: 0       # mean - 4σ (capped at 0)
  max_valid_annual: 481000  # mean + 4σ (or 5σ: $566K)
```
- Captures 99.99% of data
- Much tighter than current $10M (clearly too high)
- Still allows for extreme outliers (executives, specialized roles)

#### Why Current p99 ($430K) is Good

**Advantages of percentile-based:**
- ✅ **Non-parametric:** Doesn't assume normal distribution
- ✅ **Robust to outliers:** Not affected by extreme values
- ✅ **Intuitive:** "Top 1% of earners" is easy to understand
- ✅ **Empirical:** Based on actual data, not statistical assumptions

**Advantages of sigma-based:**
- ✅ **Statistically principled:** Based on distribution parameters
- ✅ **Automatically adjusts:** Changes with mean/std
- ✅ **Predictable:** Known coverage percentages
- ✅ **Symmetric:** Treats both tails equally (if distribution is symmetric)

**Salary data characteristics:**
- **Right-skewed:** Mean ($142K) > Median ($129K)
- **Not normal:** Has long right tail (high earners)
- **Bounded below:** Can't be negative
- **Unbounded above:** No theoretical maximum

**Conclusion:** **Percentile-based (current) is better for salary data**
- Salary distributions are NOT normal (right-skewed)
- Percentiles handle skewness naturally
- Sigma-based assumes normality (not valid here)

**However:** Sigma-based could be useful for **outlier detection**:
```python
# Flag for review (not rejection)
if abs(salary - mean) > 3 * std:
    flag_for_manual_review()
```

---

### 6. Are stats computed on raw or normalized/processed data?

**Answer: NORMALIZED/PROCESSED data (wage_annual)**

#### What the script analyzes:

```python
# From update_wage_thresholds.py line 147-150
records = SalaryRecord.objects.filter(
    wage_annual__isnull=False,
    wage_annual__gt=0,
    wage_annual__lt=10000000,  # Exclude obvious errors
)
```

**This means:**
- ✅ Uses `wage_annual` (normalized/calculated field)
- ✅ Excludes null wages
- ✅ Excludes zero wages
- ✅ Excludes obvious errors (>$10M)
- ✅ Only recent data (FY 2025-2026)

#### Data Processing Pipeline:

```
Raw Input → Parse → Correct Unit → Calculate Annual → Store
  ↓           ↓         ↓              ↓                ↓
wage_from   wage_from  wage_unit     wage_annual    Database
$50         $50        HOUR→YEAR      $104,000       ✓
```

**So statistics are based on:**
1. **After unit correction:** Hourly stored as annual → fixed
2. **After annual calculation:** All wages normalized to annual
3. **After filtering:** Obvious errors excluded
4. **Recent data only:** Last 2 fiscal years

#### Why this is correct:

**✅ Pros:**
- Statistics reflect **actual valid salaries**
- Not polluted by parsing errors
- Not skewed by incorrect units
- Represents what users see in the UI

**⚠️ Potential issue:**
- If unit correction has bugs, statistics inherit those bugs
- Circular dependency: thresholds based on corrected data, but correction uses thresholds

**Mitigation:**
- Thresholds have fallback defaults
- Correction logic is well-tested
- Manual validation catches issues

---

## Summary & Recommendations

### Immediate Actions

1. **✅ Keep both validation files** (different purposes)
   - Refactor `salary_validation.py` to import thresholds

2. **✅ Consolidate fix scripts**
   - Merge `fix_calculation.py` into `fix_high_wage_records.py`
   - Delete `fix_calculation.py`

3. **✅ Keep both MD files for now**
   - Rename for clarity
   - Archive after refactoring complete

4. **✅ Document threshold differences**
   - Add comments to config file explaining each section

5. **✅ Keep percentile-based thresholds**
   - Current p5/p99 approach is correct for salary data
   - Consider adding sigma-based outlier flagging (separate from thresholds)

6. **✅ Update validation_thresholds**
   - Current max ($10M) is too high
   - Recommend: $500K (4σ) or $600K (5σ)

### Config File Improvements

```yaml
# Wage thresholds calculated from recent data distributions
_last_updated: "2026-01-04"
_source: "Calculated from salary data distributions (wage_annual, normalized)"

# Reasonable range for correction logic (p5-p99, captures 94% of data)
# Used to detect misclassified wage units (e.g., hourly stored as annual)
reasonable_annual_range:
  min: 39000   # 5th percentile
  max: 430000  # 99th percentile

# Absolute limits for data acceptance (reject obvious errors)
# Much wider than reasonable_annual_range
# Current max ($10M) is too high - recommend updating to 4σ (~$500K)
validation_thresholds:
  min_valid_annual: 10000     # Reject below this (likely data errors)
  max_valid_annual: 500000    # Reject above this (4σ, captures 99.99%)

# Statistics for reference and outlier detection
statistics:
  mean: 142383.71
  std: 84770.98
  median: 129000.0
  count: 11519
  
  # Sigma-based ranges (for reference, not used as thresholds)
  sigma_2: 311926   # mean + 2σ (~95% coverage)
  sigma_3: 396697   # mean + 3σ (~99.7% coverage)
  sigma_4: 481468   # mean + 4σ (~99.99% coverage)
```

### Long-term Improvements

1. **Add outlier detection using sigma**
   ```python
   def is_statistical_outlier(salary, mean, std):
       return abs(salary - mean) > 3 * std
   ```

2. **Track distribution changes over time**
   - Store historical mean/std/percentiles
   - Alert if distribution shifts significantly

3. **Separate thresholds by visa program**
   - H-1B vs PERM may have different distributions
   - Calculate separate thresholds for each

4. **Add confidence intervals**
   - Report uncertainty in threshold estimates
   - Useful for small sample sizes

