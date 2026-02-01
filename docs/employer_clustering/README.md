# Employer Clustering Documentation

This directory contains documentation for the employer clustering system that groups similar employer names across different data sources.

## Overview

The employer clustering system uses rule-based matching to identify and group employer records that refer to the same company, handling variations in name formatting, corporate suffixes, punctuation, and more.

## Documentation Files

### System Architecture
- **SYSTEM_EXPLANATION.md** - Complete explanation of how the clustering system works, including production clustering (rule-based) vs benchmark/evaluation (LLM-based)

### Benchmarking and Tuning
- **BENCHMARK_WORKFLOW.md** - Complete workflow for benchmarking clustering performance and collecting examples
- **ITERATIVE_TUNING.md** - Iterative process for improving clustering precision and recall
- **TUNING_RESULTS.md** - Historical tuning results and performance improvements

### Working with Examples
- **VIEWING_EXAMPLES.md** - How to view and analyze clustering examples for debugging and improvement
- **BUCKET_MISMATCH_EXAMPLES.md** - How to harvest and analyze bucket mismatch examples (names that normalize differently)

## Related Code

- **Implementation:** `lib/business/salary/` - Clustering implementation and generic word definitions
- **Scripts:** `scripts/salary/` - Clustering, benchmarking, and evaluation scripts
- **Benchmark Data:** `data/clustering_examples.jsonl` - Labeled examples for benchmarking

## Quick Start

```bash
# Run benchmark to measure current performance
bazel run //scripts/salary:benchmark_clustering -- \
  --mode production \
  --examples-file $(pwd)/data/clustering_examples.jsonl \
  --only-reviewed \
  --limit 0

# Collect new examples for benchmarking
bazel run //scripts/salary:collect_clustering_examples
```

For complete implementation details, see `lib/business/salary/README.md`.

