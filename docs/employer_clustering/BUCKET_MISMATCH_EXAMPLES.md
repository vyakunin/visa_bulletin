# Harvesting Bucket Mismatch Examples for Golden Set

## Overview

The `harvest_bucket_mismatch_examples.py` script finds potential false negatives due to hash clustering (normalized name buckets). These are pairs of employers that:

- **Normalize to different values** (different hash buckets)
- **Have high similarity** (potential matches)
- **Would never be compared in production** (different buckets)

These candidates should be reviewed and added to the golden set to ensure good coverage for bucket mismatch scenarios.

## Usage

### Basic Usage

```bash
# Find top 50 candidates with similarity >= 0.90
bazel run //scripts/salary:harvest_bucket_mismatch_examples -- \
  --min-similarity 0.90 \
  --max-candidates 50 \
  --limit 10
```

### Save to File

```bash
# Save candidates to JSONL file for review
bazel run //scripts/salary:harvest_bucket_mismatch_examples -- \
  --min-similarity 0.85 \
  --max-candidates 200 \
  --output $(pwd)/data/bucket_mismatch_candidates.jsonl
```

### Review and Add to Golden Set

1. **Harvest candidates:**
   ```bash
   bazel run //scripts/salary:harvest_bucket_mismatch_examples -- \
     --min-similarity 0.85 \
     --max-candidates 200 \
     --output $(pwd)/data/bucket_mismatch_candidates.jsonl
   ```

2. **Review candidates:**
   ```bash
   bazel run //scripts/salary:view_clustering_examples -- \
     $(pwd)/data/bucket_mismatch_candidates.jsonl \
     --format detailed
   ```

3. **Manually review and mark as same/different:**
   - Use `review_golden_set.py` to mark pairs as approved/rejected
   - Or manually add to `clustering_examples.jsonl` with `ground_truth: 'same'` or `'different'`

4. **Regenerate golden set:**
   ```bash
   bazel run //scripts/salary:collect_clustering_examples -- \
     --output $(pwd)/data/clustering_examples.jsonl \
     --reviewed-limit 500 \
     --auto-clustered-size 1000 \
     --different-size 500
   ```

## Parameters

- `--min-similarity`: Minimum similarity score to consider (0.0-1.0, default: 0.80)
  - Higher values = more confident matches
  - Recommended: 0.85-0.90 for high-quality candidates

- `--max-candidates`: Maximum number of candidates to find (default: 500)
  - Higher values = more candidates but slower execution
  - Recommended: 100-200 for initial review

- `--output`: Optional path to save results as JSONL file
  - If not provided, results are only printed

- `--limit`: Limit number of candidates to display (default: show all)
  - Useful for quick previews

- `--format`: Output format (default: detailed)
  - `summary`: Just counts and statistics
  - `detailed`: Human-readable detailed view
  - `jsonl`: JSON lines format (only if --output not provided)

## Performance

The script uses an optimized approach:
- Samples up to 5 employers per bucket (reduces O(n²) complexity)
- Filters pairs with no common words (quick rejection)
- Compares only across different buckets

For ~430k employers:
- **Time**: ~1-2 minutes for 50-100 candidates
- **Memory**: ~100-200 MB

## What to Look For

Good candidates for the golden set:

1. **Normalization inconsistencies:**
   - Same company name with different punctuation/spacing
   - Example: "dr. unni krishnan" vs "dr unni krishnan"

2. **Generic word handling:**
   - Same company with/without generic words
   - Example: "union enterprises" vs "union"

3. **Structural word variations:**
   - Same company with different structural words
   - Example: "construction company" vs "construction"

4. **High similarity, different buckets:**
   - Names that are very similar but normalize differently
   - Example: "google inc" vs "google llc" (if they normalize differently)

## Integration with Benchmark

After adding bucket mismatch examples to the golden set, run the benchmark to verify coverage:

```bash
# Run production benchmark on all examples
bazel run //scripts/salary:benchmark_clustering -- \
  --mode production \
  --examples-file $(pwd)/data/clustering_examples.jsonl \
  --include-all-types \
  --limit 0
```

The benchmark will show:
- How many pairs are in different buckets
- How many are false negatives (same company, different buckets)
- Examples of bucket mismatches

## Example Output

```
BUCKET MISMATCH CANDIDATES (Potential False Negatives)
================================================================================
Total candidates: 50

1. Similarity: 1.000
   Employer 1: 'DR. UNNI KRISHNAN'
               Location: ELMONT, NY
               Normalized: 'dr. unni krishnan'
   Employer 2: 'DR. UNNI KRISHNAN'
               Location: ELMONT, NY
               Normalized: 'dr unni krishnan'
   Reason: Different normalized buckets: 'dr. unni krishnan' vs 'dr unni krishnan' (similarity: 1.000)
```

This indicates a normalization inconsistency that should be reviewed and potentially added to the golden set.



