# Clustering Benchmark Iteration Workflow

This document describes the iterative process for improving employer clustering through benchmarking and adjustment.

## Workflow Overview

The workflow is an iterative cycle that:
1. Benchmarks current clustering logic against ground truth
2. Identifies false positives/negatives
3. Adjusts clustering thresholds/rules
4. Tests changes with dry-run clustering
5. Collects new examples from clustering results
6. Adds samples to benchmark dataset
7. Repeats to measure improvement

## Step-by-Step Process

### Step 1: Run Benchmark

Run benchmark with current examples to establish baseline:

```bash
# Quick iteration (5-10 examples for fast feedback)
bazel run //scripts/salary:benchmark_clustering -- \
  --examples-file $(pwd)/data/clustering_examples.jsonl \
  --model llama3.2:1b \
  --prompt-template-path $(pwd)/scripts/salary/llm_prompt_template.txt \
  --limit 10

# Full benchmark (all examples)
bazel run //scripts/salary:benchmark_clustering -- \
  --examples-file $(pwd)/data/clustering_examples.jsonl \
  --model llama3.2:1b \
  --prompt-template-path $(pwd)/scripts/salary/llm_prompt_template.txt
```

**Key Metrics to Review:**
- Precision (false positives)
- Recall (false negatives)
- F1 Score (overall balance)
- Per-pair timing (performance)

**What to Look For:**
- Low precision → Too many false positives (clustering too aggressively)
- Low recall → Too many false negatives (clustering too conservatively)
- Specific patterns in errors (e.g., structural word conflicts, similarity thresholds)

### Step 2: Analyze Results

Review benchmark output to identify:
- **False Positives**: Pairs marked as "same" but should be different
  - Common causes: Similar names but different companies (e.g., "Macro Consultants" vs "Macro International")
  - Check for structural word conflicts
- **False Negatives**: Pairs marked as "different" but should be same
  - Common causes: Name variations not caught (e.g., "Google LLC" vs "Google Inc")
  - Check similarity thresholds

**Example Analysis:**
```
Precision: 0.640 (36% false positives)
Recall: 0.533 (47% false negatives)

False Positive Examples:
- "Macro Consultants" vs "Macro International" → Should be different (structural words conflict)
- "SYNAPSE GROUP" vs "SYNAPSE TECHNOLOGIES" → Should be different

False Negative Examples:
- "Google LLC" vs "Google Inc" → Should be same (corporate suffix variation)
- "Microsoft Corporation" vs "Microsoft Corp" → Should be same
```

### Step 3: Adjust Clustering Logic

Based on results, adjust clustering parameters in `lib/business/salary/employer_clustering.py`:

**Common Adjustments:**

1. **Similarity Thresholds** (`should_auto_cluster` threshold):
   ```python
   # More conservative (fewer false positives)
   threshold = 0.98  # Up from 0.95
   
   # More aggressive (fewer false negatives)
   threshold = 0.90  # Down from 0.95
   ```

2. **Hybrid Matching** (`match_employers`): Rule-based checks first, then similarity-based fallback
   - Adjust similarity thresholds for auto-clustering
   - Add/refine structural word conflict detection
   - Improve substring matching logic

3. **Structural Word Conflicts** (`_has_conflicting_structural_words`):
   - Add new structural words that distinguish companies
   - Refine equivalent word groups
   - Adjust conflict detection logic

**Example Adjustment:**
```python
# If seeing false positives from structural word conflicts:
# Add more structural words to detect
STRUCTURAL_WORDS = {
    'consultants', 'consulting', 'consultant',
    'international', 'intl',
    'technologies', 'technology', 'tech',
    # Add new ones based on false positives
    'solutions', 'services', 'systems',
    ...
}

# If seeing false negatives from corporate suffixes:
# Ensure equivalent_suffixes includes all variations
equivalent_suffixes = {
    'corporation', 'corp', 'incorporated', 'inc', 
    'llc', 'limited', 'ltd', 'company', 'co',
    # Add if missing
    'plc', 'p.c.', 'pc'
}
```

### Step 4: Run Clustering Dry Run

Test adjusted logic with dry-run to see impact:

```bash
# Dry run clustering (no database changes)
bazel run //scripts/salary:cluster_existing_employers -- \
  --dry-run \
  --limit 1000

# Review output for:
# - Number of auto-clustered pairs
# - Number of pairs queued for review
# - Sample of matches (check for false positives/negatives)
```

**What to Check:**
- Auto-cluster count (should align with expected precision)
- Review queue size (ambiguous cases)
- Sample matches look correct (spot-check)

### Step 5: Collect New Examples

After dry-run, collect new examples from clustering results:

```bash
# Collect examples from:
# - Auto-clustered pairs (high confidence)
# - Review queue (ambiguous cases)
# - Different-company pairs (for negative examples)
bazel run //scripts/salary:collect_clustering_examples -- \
  --auto-clustered-size 2000 \
  --different-size 1000 \
  --output $(pwd)/data/clustering_examples_new.jsonl
```

**What to Collect:**
- **Auto-clustered pairs**: High-confidence matches (positive examples)
- **Review queue pairs**: Ambiguous cases (edge cases)
- **Different-company pairs**: Negative examples (should not cluster)

### Step 6: Add Samples to Benchmark

Merge new examples into benchmark dataset:

```bash
# Append new examples to existing file
cat data/clustering_examples_new.jsonl >> data/clustering_examples.jsonl

# Or replace if starting fresh
cp data/clustering_examples_new.jsonl data/clustering_examples.jsonl
```

**Best Practices:**
- Keep balanced dataset (similar number of "same" and "different" examples)
- Include edge cases from review queue
- Add false positive/negative examples from previous benchmark
- Remove duplicates before adding

### Step 7: Repeat

Run benchmark again with updated examples and logic:

```bash
# Quick iteration
bazel run //scripts/salary:benchmark_clustering -- \
  --examples-file $(pwd)/data/clustering_examples.jsonl \
  --model llama3.2:1b \
  --prompt-template-path $(pwd)/scripts/salary/llm_prompt_template.txt \
  --limit 10
```

**Compare Results:**
- Precision improved? (fewer false positives)
- Recall improved? (fewer false negatives)
- F1 Score improved? (better overall balance)
- Any new error patterns?

## Iteration Checklist

For each iteration:

- [ ] Run benchmark with current examples
- [ ] Review precision/recall/F1 metrics
- [ ] Identify false positive/negative patterns
- [ ] Adjust clustering logic (thresholds, rules, structural words)
- [ ] Run clustering dry-run to test changes
- [ ] Collect new examples from clustering results
- [ ] Add samples to benchmark dataset
- [ ] Run benchmark again to measure improvement
- [ ] Document changes and results

## Key Files

- **Clustering Logic**: `lib/business/salary/employer_clustering.py`
  - `should_auto_cluster()` - Main threshold logic
  - `match_employers()` - Hybrid matching (rule-based + similarity)
  - `_has_conflicting_structural_words()` - Structural word detection

- **Benchmark Script**: `scripts/salary/benchmark_clustering.py`
  - Runs LLM verifier on examples
  - Measures precision/recall/F1

- **Clustering Script**: `scripts/salary/cluster_existing_employers.py`
  - Runs clustering with current logic
  - Supports `--dry-run` for testing

- **Example Collection**: `scripts/salary/collect_clustering_examples.py`
  - Collects examples from database
  - Exports to JSONL for benchmarking

- **Examples File**: `data/clustering_examples.jsonl`
  - Ground truth dataset
  - JSONL format (one example per line)

## Success Criteria

A successful iteration should show:
- **Precision > 0.80**: Few false positives (high confidence matches)
- **Recall > 0.70**: Most true matches found
- **F1 > 0.75**: Good balance between precision and recall
- **Performance**: < 2s per pair (with parallelism)

## Common Issues and Solutions

### Issue: Too Many False Positives (Low Precision)
**Solution:**
- Increase similarity threshold (0.95 → 0.98)
- Improve structural word conflict detection
- Add more structural words to distinguish companies

### Issue: Too Many False Negatives (Low Recall)
**Solution:**
- Decrease similarity threshold (0.95 → 0.90)
- Improve corporate suffix handling
- Add more equivalent word groups

### Issue: Specific Pattern Errors
**Solution:**
- Add pattern-specific rules to `match_employers()`
- Update structural word lists
- Adjust similarity calculation for specific cases

## Notes

- **Fast Iterations**: Use `--limit 10` for quick feedback during development
- **Full Benchmarks**: Run without `--limit` before committing changes
- **Dry Runs**: Always test with `--dry-run` before applying to production data
- **Example Balance**: Keep similar number of positive/negative examples
- **Documentation**: Document threshold changes and rationale





