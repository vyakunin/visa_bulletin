# Employer Clustering Rules

## Rule: Collect Employer Clustering Examples

**ALWAYS collect employer clustering matching examples when running clustering or evaluation scripts.**

Collect after running `cluster_existing_employers.py`, `evaluate_clustering_threshold.py`, reviewing `EmployerClusteringReview` pairs, periodically, and **before committing clustering changes** (use dry-run mode).

```bash
# Collect all available examples
bazel run //scripts/salary:collect_clustering_examples

# Collect with custom limits
bazel run //scripts/salary:collect_clustering_examples -- \
  --auto-clustered-size 2000 --different-size 1000

# Before committing: dry-run sample
bazel run //scripts/salary:cluster_existing_employers -- \
  --dry-run --min-pairs 500 --pairs-output /tmp/clustering_sample.jsonl \
  --shuffle --shuffle-seed 42
```

Output saves to `data/clustering_examples.jsonl` (JSON lines with pair data + ground truth). Use for benchmarking LLM verifiers (`benchmark_llm_verifier.py`), testing prompt improvements, measuring precision/recall.

## Rule: Clustering Benchmark Iteration Workflow

**ALWAYS follow iterative improvement when changing clustering logic. Repeat 2+ times per cycle:**

1. **Benchmark** current performance:
   ```bash
   bazel run //scripts/salary:benchmark_clustering -- \
     --mode production --examples-file $(pwd)/data/clustering_examples.jsonl \
     --only-reviewed --limit 0
   ```
2. **Analyze**: Low Precision → too aggressive. Low Recall → too conservative. Review false positive/negative patterns.
3. **Adjust** clustering logic in `lib/business/salary/employer_clustering.py` (thresholds in `should_auto_cluster()`, structural words in `_has_conflicting_structural_words()`, rules in `match_employers()`).
4. **Dry-run** to test changes (use `--limit-employers 1000` for fast <1s iteration, `10000` for representative sample):
   ```bash
   bazel run //scripts/salary:cluster_existing_employers -- \
     --dry-run --limit-employers 1000 --min-pairs 5 --threshold 0.1
   ```
5. **Collect new examples** and append to benchmark dataset.
6. **Repeat** benchmark to measure improvement.

**Key Metrics:** Precision > 0.90, Recall > 0.90, F1 > 0.90, Performance > 10k pairs/sec.

**Tuning guide:**
- **Low Precision** → Increase threshold (e.g. 0.98), add structural words, improve conflict detection, add location filtering
- **Low Recall** → Decrease threshold (e.g. 0.90), improve suffix handling, add equivalent word groups

**Files:** `lib/business/salary/employer_clustering.py`, `models/salary.py` (`normalize_name()`), `lib/business/salary/generic_words.py`, `data/clustering_examples.jsonl`. See `lib/business/salary/README.md` for docs.

## Rule: Run Clustering Script in Monitorable Mode

**ALWAYS run `cluster_existing_employers.py` in background with log monitoring** — it processes 400k+ employers, takes 30min to hours.

```bash
bazel run //scripts/salary:cluster_existing_employers > /tmp/clustering.log 2>&1 &
PID=$!
echo "Started with PID: $PID, monitoring: tail -f /tmp/clustering.log"
```

**❌ BAD:** `bazel run //scripts/salary:cluster_existing_employers` (foreground blocks terminal)

**Monitor for:** Phase 1/2 progress, "Processed X/Y pairs", "CLUSTERING SUMMARY" (completion), ERROR/Exception/Traceback.

**Resumability:** Partially safe — skips already-clustered pairs, uses batched updates. Not fully idempotent: may re-process unclustered pairs. Best practice: let it complete. If interrupted, re-run (duplicate work but won't break data).

**Performance:** Phase 1: ~50k-100k pairs/sec. Phase 2 (LSH): ~10k-50k pairs/sec. Total: 30min–2+ hours.

## Rule: Keep All Generic Word Definitions in `lib/business/salary/generic_words.py`

**ALWAYS define all generic word sets in `generic_words.py`, never inline.**

**✅ GOOD:**
```python
from lib.business.salary.generic_words import GENERIC_WORDS, DISTINGUISHING_GENERIC_WORDS, VERY_GENERIC_WORDS
```

**❌ BAD:**
```python
very_generic_words = {'hospital', 'school', 'center', 'clinic'}  # Don't inline
```

**Available sets:**
- `GENERIC_WORDS` — Removed during normalization
- `DISTINGUISHING_GENERIC_WORDS` — Kept when only 1 non-generic word remains
- `VERY_GENERIC_WORDS` — Require location match (too generic for cross-state matching)

## Rule: Use State Normalization Utility for Location Matching

**ALWAYS use `normalize_state_code()` from `lib/utils/location_utils.py`, never inline state mapping.**

**✅ GOOD:**
```python
from lib.utils.location_utils import normalize_state_code
state1 = normalize_state_code(employer1.state)  # "MASSACHUSETTS" -> "MA"
```

**❌ BAD:**
```python
state_map = {'MASSACHUSETTS': 'MA', 'LOUISIANA': 'LA'}  # Don't inline
```

Handles full names, abbreviations, case variations. Returns empty string for None/empty. Fallback: first 2 chars uppercased.
