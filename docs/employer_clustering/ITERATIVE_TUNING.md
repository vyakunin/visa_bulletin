# Iterative Clustering Tuning for 99% Precision

This document describes the iterative tuning process to achieve 99% precision in employer clustering.

## Problem Statement

Current clustering results:
- Auto-clustered: ~387K pairs
- Queued for review: ~578K pairs

**Issue:** 578K pairs in review queue is too many for manual review. We need to achieve 99% precision so that auto-clustered pairs are highly reliable, and the review queue contains only truly ambiguous cases.

## Approach

**Iterative tuning loop:**
1. Run clustering (dry-run) with current thresholds
2. Sample pairs from auto-clustered and queued sets
3. Evaluate samples with LLM (Ollama) to determine ground truth
4. Compute precision/recall metrics
5. Adjust thresholds/logic based on results
6. Repeat 3-4 times
7. Produce final report with changes and metrics

## Usage

### Prerequisites

1. **Install Ollama:**
   ```bash
   # macOS
   brew install ollama
   
   # Or download from https://ollama.ai/
   ```

2. **Pull LLM model:**
   ```bash
   ollama pull llama3.2:3b
   # Or use mistral:7b for better accuracy (slower)
   ```

### Run Iterative Tuning

```bash
# Run 4 iterations with 50 samples per category
bazel run //scripts/salary:iterative_clustering_tuning -- \
  --iterations 4 \
  --sample-size 50 \
  --initial-threshold 0.95 \
  --output-dir /tmp/clustering_tuning

# View results
cat /tmp/clustering_tuning/tuning_report.json | jq
```

### Manual Step-by-Step

If you prefer to run steps manually:

```bash
# Step 1: Run clustering and capture pairs
bazel run //scripts/salary:cluster_existing_employers -- \
  --dry-run \
  --threshold 0.95 \
  --pairs-output /tmp/pairs.jsonl

# Step 2: Evaluate with LLM (manual script)
# (See evaluate_clustering_with_llm.py for details)
```

## How It Works

### 1. Pair Capture

The clustering script (`cluster_existing_employers.py`) now supports `--pairs-output` flag that writes all pairs to a JSONL file:

```json
{"type": "auto_clustered", "emp1_name": "...", "emp2_name": "...", "similarity": 0.95, ...}
{"type": "queued_for_review", "emp1_name": "...", "emp2_name": "...", "similarity": 0.85, ...}
```

### 2. LLM Evaluation

For each sampled pair, the script calls Ollama with a prompt:

```
Are these two employer names referring to the same company?

Name 1: CVS Corporation, Inc.
Location 1: New York, NY

Name 2: ICS Corporation
Location 2: Boston, MA

Similarity score: 0.933

Answer with only "YES" or "NO" followed by a brief explanation.
```

LLM responds with "YES" or "NO" indicating if they're the same company.

### 3. Metrics Calculation

**Precision:** `TP / (TP + FP)`
- TP (True Positives): Auto-clustered pairs that LLM confirms are same company
- FP (False Positives): Auto-clustered pairs that LLM says are different companies

**Recall:** `TP / (TP + FN)`
- FN (False Negatives): Queued pairs that LLM says should be clustered (same company)

### 4. Threshold Adjustment

The script automatically adjusts the threshold based on precision:

- **If precision < 99%:** Increase threshold (be more conservative)
- **If precision > 99%:** Can slightly lower threshold (if > 99.5%)

Formula:
```python
precision_gap = 0.99 - current_precision
threshold_increase = min(0.10, precision_gap * 0.02)
new_threshold = min(1.0, current_threshold + threshold_increase)
```

### 5. Logic Adjustments

Beyond threshold, the script can suggest logic changes:

- **High false positives in specific similarity ranges:** Add special handling
- **False negatives with high similarity:** Lower threshold for specific cases
- **Pattern-based issues:** Add domain-specific heuristics

## Expected Results

After 3-4 iterations:

**Target metrics:**
- Precision: ≥ 99%
- Recall: As high as possible while maintaining precision
- Auto-clustered: ~300-400K pairs (high confidence)
- Queued for review: ~100-200K pairs (truly ambiguous)

**Typical progression:**
- Iteration 1: Precision ~95%, threshold 0.95
- Iteration 2: Precision ~97%, threshold 0.97
- Iteration 3: Precision ~98.5%, threshold 0.98
- Iteration 4: Precision ~99%, threshold 0.99

## Output Files

After running, you'll have:

```
/tmp/clustering_tuning/
├── pairs_iter1.jsonl          # Pairs from iteration 1
├── pairs_iter2.jsonl          # Pairs from iteration 2
├── pairs_iter3.jsonl          # Pairs from iteration 3
├── pairs_iter4.jsonl          # Pairs from iteration 4
└── tuning_report.json          # Final report with all metrics
```

**Report format:**
```json
{
  "iterations": [
    {
      "iteration": 1,
      "threshold": 0.95,
      "metrics": {
        "overall": {
          "precision": 0.95,
          "recall": 0.85,
          "f1_score": 0.90
        },
        "auto_clustered": {
          "total_evaluated": 50,
          "true_positives": 47,
          "false_positives": 3,
          "precision": 0.94
        }
      },
      "total_auto_clustered": 387605,
      "total_queued": 578469
    },
    ...
  ],
  "final_threshold": 0.99,
  "final_metrics": {...}
}
```

## Troubleshooting

### Ollama Not Found

```bash
# Check if Ollama is installed
which ollama

# If not, install it
brew install ollama  # macOS
# Or download from https://ollama.ai/
```

### LLM Timeouts

If Ollama calls timeout frequently:
- Use a smaller model: `llama3.2:1b` (faster, less accurate)
- Increase timeout in script (default: 30s)
- Reduce sample size per iteration

### Low Precision After Multiple Iterations

If precision doesn't improve:
- Check LLM responses for consistency
- Review false positive patterns
- Consider adding domain-specific heuristics (see `EMPLOYER_CLUSTERING_FALSE_POSITIVE_REDUCTION.md`)

## Next Steps

After achieving 99% precision:

1. **Apply final threshold** to production clustering
2. **Review remaining false positives** to identify patterns
3. **Add domain-specific heuristics** for common false positive patterns
4. **Consider LLM validation** for borderline cases (0.85-0.95 similarity) in production

## Related Documents

- `EMPLOYER_CLUSTERING_FALSE_POSITIVE_REDUCTION.md` - Additional strategies for reducing false positives
- `CLUSTERING_ALGORITHM_OPTIONS.md` - Algorithm options and performance comparisons









