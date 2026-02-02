# Employer Clustering Module

This module provides employer name clustering and matching functionality for grouping similar employer names across different data sources and variations.

## Overview

The employer clustering system groups employer records that refer to the same company, handling variations in:
- Name formatting (e.g., "Google Inc" vs "Google, Inc.")
- Corporate suffixes (e.g., "LLC", "Corporation", "Inc")
- Punctuation and spacing (e.g., "J.P. Morgan" vs "JP Morgan")
- Plural/singular forms (e.g., "Solutions" vs "Solution")
- Geographic indicators (e.g., "Roca USA" vs "Roca")

## Key Components

### `employer_clustering.py`
Core matching algorithm that determines if two employer names refer to the same company.

**Main Functions:**
- `match_employers(employer1, employer2)` - Returns (is_match, confidence, reason)
- `should_auto_cluster(employer1, employer2, threshold)` - Determines if pair should be auto-clustered
- `_has_conflicting_structural_words(name1, name2)` - Detects structural word conflicts

**Matching Rules:**
1. **Exact normalized match** - Names normalize to identical strings
2. **Substring match** - One name is substring of another (with generic word differences)
3. **High similarity** - Very high similarity (>= 0.98) or high similarity (>= 0.90)
4. **Location filtering** - For very generic names (hospital, school, etc.), requires same state

### `generic_words.py`
Centralized definitions of generic words used in normalization and matching.

**Word Sets:**
- `GENERIC_WORDS` - Words removed during normalization (don't help distinguish)
- `DISTINGUISHING_GENERIC_WORDS` - Words kept when only 1 non-generic word (help distinguish)
- `VERY_GENERIC_WORDS` - Words requiring location match (too generic to match across states)

**Usage:**
```python
from lib.business.salary.generic_words import (
    GENERIC_WORDS,
    DISTINGUISHING_GENERIC_WORDS,
    VERY_GENERIC_WORDS,
)
```

### `clustering_evaluator.py`
Evaluates clustering quality and identifies false positives/negatives.

### `llm_verifier.py`
LLM-based verification of employer pair matches using Ollama.

## Normalization

Employer names are normalized in `models/salary.py` via `Employer.normalize_name()`:

**Normalization Steps:**
1. Lowercase and strip whitespace
2. Convert "&" to "and" with proper spacing
3. Remove hyphens (compound words)
4. Remove corporate suffixes (Inc, LLC, Corp, etc.)
5. Remove punctuation (periods, apostrophes, etc.)
6. Remove numbers (location identifiers)
7. Remove generic words (if multiple distinguishing words remain)
8. Convert plural to singular (for non-generic words)
9. Keep critical generic words when only 1 non-generic word (preserves distinctions)

**Examples:**
- "Google, Inc." → "google"
- "J.P. Morgan" → "jp morgan"
- "Echo IT Solutions Inc" → "echo it solution"
- "GRAHAM CAPITAL MANAGEMENT, L.P." → "graham capital management"

## Location-Based Filtering

For very generic names (hospital, school, center, clinic), the system requires location match to prevent false positives:

- "CHILDREN'S HOSPITAL" (Boston) vs "CHILDREN'S HOSPITAL" (New Orleans) → Different (different states)
- "CHILDREN'S HOSPITAL" (Boston, MA) vs "CHILDREN'S HOSPITAL" (Boston, MASSACHUSETTS) → Same (same state)

State normalization uses `normalize_state_code()` from `lib/utils/location_utils.py` to handle variations like "MA" vs "MASSACHUSETTS".

## Benchmarking

Use `benchmark_clustering.py` to measure clustering performance:

```bash
bazel run //scripts/salary:benchmark_clustering -- \
  --mode production \
  --examples-file $(pwd)/data/clustering_examples.jsonl \
  --only-reviewed \
  --limit 0
```

**Key Metrics:**
- **Precision** - Percentage of matches that are correct (few false positives)
- **Recall** - Percentage of true matches found (few false negatives)
- **F1 Score** - Harmonic mean of precision and recall

**Current Targets:**
- Precision > 0.60
- Recall > 0.90
- F1 > 0.70

## Iterative Improvement Workflow

1. Run benchmark to measure current performance
2. Analyze false positives/negatives to identify patterns
3. Adjust clustering logic (thresholds, rules, normalization)
4. Add tests for new behavior
5. Run tests to verify changes
6. Re-run benchmark to measure improvement
7. Collect new examples for future iterations

See `.cursor/rules/employer_clustering.mdc` for detailed workflow rules.

## Common Issues and Solutions

**False Positives (Low Precision):**
- Increase similarity threshold
- Add more structural words to distinguish companies
- Improve location-based filtering for generic names
- Keep geographic indicators (USA, US) when they help distinguish

**False Negatives (Low Recall):**
- Decrease similarity threshold
- Improve normalization consistency (hyphens, punctuation, plural/singular)
- Handle bucket mismatches (names that normalize differently)
- Improve handling of corporate suffixes and abbreviations

## Company = None on Job Title Profile

On job title profile pages, "Compare how top companies pay" and "Top Employers" are built by grouping `SalaryRecord` by `employer__canonical_cluster__canonical_name`. Records that have **no employer cluster** form one group with `canonical_name = None`, which the UI used to show as "None".

**Two root causes (trace to raw data):**

1. **`SalaryRecord.employer_id` is NULL**  
   - Raw data: `employer_name` is present on the record (from DOL), but the employer FK was never set.  
   - Typical causes: legacy import path that didn’t set employer, or bulk load that skipped employer linking.  
   - Fix: run `scripts/salary/fix_missing_employers.py` (with `--fix`) to create/link `Employer` from `employer_name` + worksite city/state, then run employer clustering.

2. **`SalaryRecord.employer_id` set but `Employer.canonical_cluster_id` is NULL**  
   - Raw data: employer name was ingested and an `Employer` row exists, but that employer was never assigned to a cluster.  
   - Typical causes: ingest with `skip_clustering=True` and `cluster_existing_employers` not run; or `fix_missing_employers` creates new employers but does not call `assign_to_cluster`.  
   - Fix: run `scripts/salary/cluster_existing_employers.py` so every employer gets a cluster (or create a single-employer cluster).

**How to verify on the DB (for a given job title cluster):**

```sql
-- Replace :cluster_id with the JobTitleCluster id for the slug (e.g. software-development-engineer-ii)
SELECT
  CASE WHEN sr.employer_id IS NULL THEN 'employer_id NULL'
       WHEN e.canonical_cluster_id IS NULL THEN 'canonical_cluster NULL'
       ELSE 'has cluster' END AS bucket,
  COUNT(*)
FROM salary_record sr
LEFT JOIN salary_employer e ON e.id = sr.employer_id
JOIN salary_job_title jt ON jt.id = sr.job_title_entity_id
WHERE jt.canonical_cluster_id = :cluster_id
  AND sr.wage_annual IS NOT NULL AND sr.wage_annual >= 30000 AND sr.wage_annual <= 1000000
GROUP BY 1;
```

The UI now excludes the "None" group from the Company Comparison and Top Employers tables so "None" is not shown as a company name; totals and other sections still include those records.

## Related Files

- `models/salary.py` - `Employer.normalize_name()` - Name normalization logic
- `lib/utils/location_utils.py` - `normalize_state_code()` - State code normalization
- `scripts/salary/benchmark_clustering.py` - Benchmarking script
- `scripts/salary/collect_clustering_examples.py` - Example collection script
- `data/clustering_examples.jsonl` - Benchmark dataset

