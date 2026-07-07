# Employer Clustering System: Complete Explanation

> ⚠️ **LLM parts RETIRED (2026-06-20).** The Ollama LLM verifier and the
> benchmark/evaluator tooling described here were deleted when Ollama was retired.
> Live clustering is **rule-based + fuzzy only** (`employer_clustering.py`) — the
> "what uses LLMs" sections below are historical. See
> `.claude/rules/employer_clustering.md`.

This document clarifies how the employer clustering system works, what uses LLMs vs rule-based logic, and how to interpret the benchmark results.

## System Overview

Your employer clustering system has **TWO separate components**:

1. **Production Clustering** (rule-based only, no LLMs)
2. **Benchmark/Evaluation** (uses LLMs to measure quality)

**Key Point**: LLMs are **NOT used in production clustering**. They're only used to **evaluate** how good your rule-based clustering is.

---

## 1. Production Clustering (Rule-Based Only)

### How It Works

**Location**: `lib/business/salary/employer_clustering.py`

**Process**:
1. When importing salary data, each new employer is checked against existing employers
2. Uses **rule-based matching** only (no LLMs):
   - Exact normalized name match
   - Substring matching (e.g., "Google" vs "Google Inc")
   - Similarity threshold (0.95+ for auto-clustering)
   - Structural word conflict detection (e.g., "Consultants" vs "International")

**Decision Flow**:
```
New Employer → Check existing employers
  ↓
Rule-based match (similarity + structural words)
  ↓
High confidence (≥0.95)? → Auto-cluster ✅
  ↓
Low confidence (<0.95)? → Queue for review ⏸️
```

**Key Functions**:
- `match_employers()` - Determines if two employers match (hybrid: rule-based + similarity)
- `should_auto_cluster()` - Checks if match confidence is high enough
- `assign_to_cluster()` - Assigns employer to cluster (or creates new one)

**What Gets Clustered**:
- ✅ **Auto-clustered**: High confidence matches (similarity ≥0.95, no structural conflicts)
- ⏸️ **Queued for review**: Ambiguous cases (similarity 0.6-0.95, or structural conflicts)

**No LLMs in Production**: The production clustering code (`employer_clustering.py`) has **zero LLM calls**. It's pure rule-based logic.

---

## 2. Benchmark/Evaluation (Uses LLMs)

### What the Benchmark Does

**Location**: `scripts/salary/benchmark_clustering.py`

**Purpose**: Measures how well an **LLM verifier** can distinguish same vs different companies.

**Process**:
1. Loads examples from `data/clustering_examples.jsonl` (your "golden set")
2. For each example pair, asks LLM: "Are these the same company?"
3. Compares LLM's answer to ground truth
4. Calculates precision, recall, F1 score

**What It Measures**:
- **Precision**: How many "same" predictions are correct (fewer false positives)
- **Recall**: How many actual "same" pairs were found (fewer false negatives)
- **F1 Score**: Overall balance

**Key Point**: The benchmark tests **LLM performance**, not your production clustering. It's a tool to:
- Evaluate if LLMs could improve clustering (future work)
- Test prompt improvements
- Build a dataset for potential LLM-based clustering

**LLM Usage**: Only in `benchmark_clustering.py` and `clustering_evaluator.py` (evaluation tools). **Not used in production**.

---

## 3. The Golden Set (`clustering_examples.jsonl`)

### What It Is

A collection of employer pairs with **ground truth labels** (same/different).

### How It's Created

**Script**: `scripts/salary/collect_clustering_examples.py`

**Sources**:
1. **Reviewed pairs** (`EmployerClusteringReview` table):
   - Human-reviewed pairs (approved/rejected)
   - Most reliable ground truth
   - `ground_truth: 'same'` if approved, `'different'` if rejected

2. **Auto-clustered pairs**:
   - Pairs that were auto-clustered by production system
   - Assumed to be correct (high confidence matches)
   - `ground_truth: 'same'`

3. **Different-company pairs**:
   - Random pairs from different clusters
   - Negative examples (should NOT cluster)
   - `ground_truth: 'different'`

### How Much Can You Trust It?

**Trust Levels by Source**:

| Source | Trust Level | Why |
|--------|------------|-----|
| **Reviewed pairs** | ⭐⭐⭐⭐⭐ **Highest** | Human-verified, most reliable |
| **Auto-clustered pairs** | ⭐⭐⭐⭐ **High** | Production system with high confidence (≥0.95) |
| **Different-company pairs** | ⭐⭐⭐ **Medium** | Random sampling, may include edge cases |

**Overall Trust**: **Medium-High** (depends on mix of sources)

**Potential Issues**:
- ⚠️ Auto-clustered pairs may include false positives (if production rules are wrong)
- ⚠️ Different-company pairs may include true matches that weren't clustered (false negatives)
- ⚠️ Reviewed pairs are most reliable, but may be limited in quantity

**Recommendations**:
1. **Prioritize reviewed pairs** in your golden set (most reliable)
2. **Review auto-clustered examples** periodically to catch false positives
3. **Add edge cases** from benchmark false positives/negatives to improve dataset
4. **Balance dataset** (similar number of "same" and "different" examples)

---

## 4. What Uses What?

### Production Clustering (During Data Import)

```
┌─────────────────────────────────────┐
│  Production Clustering              │
│  (lib/business/salary/              │
│   employer_clustering.py)          │
│                                     │
│  ✅ Rule-based matching only        │
│  ❌ No LLMs                         │
│  ❌ No benchmark calls              │
└─────────────────────────────────────┘
```

**Used by**:
- `lib/parsing/salary/db_importer.py` (during salary data import)
- `scripts/salary/cluster_existing_employers.py` (batch clustering script)

### Benchmark/Evaluation

```
┌─────────────────────────────────────┐
│  Benchmark Script                   │
│  (scripts/salary/                    │
│   benchmark_clustering.py)        │
│                                     │
│  ✅ Uses LLMs to evaluate           │
│  ✅ Tests on golden set             │
│  ❌ Does NOT affect production      │
└─────────────────────────────────────┘
```

**Used for**:
- Measuring LLM verifier performance
- Testing prompt improvements
- Building evaluation dataset

### Example Collection

```
┌─────────────────────────────────────┐
│  Collect Examples                   │
│  (scripts/salary/                    │
│   collect_clustering_examples.py)    │
│                                     │
│  ✅ Extracts from database          │
│  ✅ Creates golden set              │
│  ❌ Does NOT use LLMs               │
└─────────────────────────────────────┘
```

**Used for**:
- Building/updating golden set
- Collecting examples for benchmarking

---

## 5. Workflow Summary

### Production Flow (What Actually Happens)

**Note:** Clustering is now **disabled during ingest** for performance (re-imports are much faster). Clustering must be run separately after ingest completes.

```
1. Import salary data (clustering disabled for performance)
   ↓
2. Run employer clustering separately:
   bazel run //scripts/salary:cluster_existing_employers
   ↓
3. For each employer:
   - Check existing employers
   - Run rule-based matching
   - Auto-cluster if high confidence (≥0.95)
   - Queue for review if ambiguous
   ↓
4. Done (no LLMs involved)
```

**End-to-End Workflow:**
```bash
# Option 1: Use combined script (recommended)
bazel run //scripts/ingest:ingest_and_cluster -- --source-id 123

# Option 2: Run separately
bazel run //scripts/ingest:run_pipeline -- run --source-id 123
bazel run //scripts/salary:cluster_existing_employers
```

### Evaluation Flow (Measuring Quality)

```
1. Collect examples from database
   - Reviewed pairs (human-verified)
   - Auto-clustered pairs (production results)
   - Different-company pairs (negative examples)
   ↓
2. Run benchmark with LLM verifier
   - Test LLM on examples
   - Measure precision/recall/F1
   ↓
3. Analyze results
   - Identify false positives/negatives
   - Adjust production rules if needed
   ↓
4. Update production clustering rules
   - Adjust thresholds
   - Improve structural word detection
   - Refine matching logic
```

---

## 6. Key Takeaways

### What Your Benchmark Does

✅ **Tests LLM verifier performance** on a golden set  
✅ **Measures precision/recall** of LLM-based matching  
✅ **Helps identify edge cases** (false positives/negatives)  
❌ **Does NOT test production clustering directly**  
❌ **Does NOT affect production clustering**

### How Production Clustering Works

✅ **Rule-based only** (no LLMs)  
✅ **Auto-clusters high confidence matches** (≥0.95 similarity)  
✅ **Queues ambiguous cases** for review  
❌ **Does NOT use LLMs**  
❌ **Does NOT call benchmark**

### Your Golden Set Trust Level

✅ **Reviewed pairs**: Very high trust (human-verified)  
✅ **Auto-clustered pairs**: High trust (production high-confidence matches)  
⚠️ **Different-company pairs**: Medium trust (may include edge cases)  
⚠️ **Overall**: Medium-high trust (depends on mix)

**Recommendation**: Focus on reviewed pairs for most reliable ground truth. Use auto-clustered pairs as additional positive examples, but periodically review them for false positives.

---

## 7. Common Confusions Clarified

### ❌ "The benchmark tests my production clustering"

**Reality**: The benchmark tests **LLM verifier performance**, not production clustering. Production clustering is rule-based and doesn't use LLMs.

### ❌ "LLMs are used in production clustering"

**Reality**: LLMs are **only used in benchmarking/evaluation**. Production clustering is pure rule-based logic.

### ❌ "The golden set is perfect ground truth"

**Reality**: The golden set has varying trust levels:
- Reviewed pairs: Very reliable
- Auto-clustered pairs: High confidence but may include false positives
- Different-company pairs: May include true matches that weren't clustered

### ✅ "I can use benchmark results to improve production rules"

**Reality**: Yes! Benchmark results (false positives/negatives) help identify edge cases to improve production rule-based matching.

---

## 8. Next Steps

### To Improve Production Clustering

1. **Review benchmark false positives/negatives** to identify edge cases
2. **Adjust production rules** in `employer_clustering.py`:
   - Similarity thresholds
   - Structural word detection
   - Matching logic
3. **Test with dry-run** clustering before applying to production
4. **Collect new examples** from updated clustering results
5. **Re-run benchmark** to measure improvement

### To Improve Golden Set

1. **Prioritize reviewed pairs** (most reliable)
2. **Periodically review auto-clustered pairs** for false positives
3. **Add edge cases** from benchmark results
4. **Balance dataset** (similar number of positive/negative examples)
5. **Document source** of each example for trust assessment

---

## Summary

- **Production clustering**: Rule-based only, no LLMs
- **Benchmark**: Tests LLM verifier, doesn't affect production
- **Golden set**: Medium-high trust (depends on source mix)
- **LLM usage**: Only in evaluation, not in production
- **Workflow**: Use benchmark results to improve production rules

