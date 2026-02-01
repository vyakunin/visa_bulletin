# Viewing Clustering Examples

The golden set (`data/clustering_examples.jsonl`) is stored in JSONL format (one JSON object per line), which is efficient but hard to read. Use the viewer script to display examples in human-readable formats.

## Quick Start

```bash
# View all examples in compact table format
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --format compact

# View with summary statistics
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --format summary

# View detailed format (one example per section)
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --format detailed \
  --limit 20

# Export as Markdown table
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --format markdown \
  --output examples.md
```

## Output Formats

### 1. Summary (`--format summary`)

Shows statistics about the dataset:
- Total number of examples
- Breakdown by type (reviewed, auto-clustered, different_companies)
- Breakdown by ground truth (same, different)

**Use when:** You want a quick overview of the dataset composition.

### 2. Compact Table (`--format compact`)

Shows examples in a table format:
```
#    Type            Truth    Similarity Employer 1                          Employer 2
1    auto_clustered  same     1.000      Amy's House Inc.                    AMY'S HOUSE, INC.
2    auto_clustered  same     1.000      EVE HAIR, INC.                      Eve Hair, Inc.
```

**Use when:** You want to quickly scan many examples.

### 3. Markdown Table (`--format markdown`)

Exports as a Markdown table that can be viewed in GitHub, editors, or documentation:

```markdown
| # | Type | Truth | Similarity | Employer 1 | Employer 2 | Location 1 | Location 2 |
|---|------|-------|------------|-------------|------------|-----------|-------------|
| 1 | auto_clustered | same | 1.000 | Amy's House Inc. | AMY'S HOUSE, INC. | Vernon, CALIFORNIA | VERNON, CALIFORNIA |
```

**Use when:** You want to include examples in documentation or review in a Markdown viewer.

### 4. Detailed (`--format detailed`)

Shows each example with full details in a readable format:

```
================================================================================
Example #1 ⚙ [auto_clustered] ✅ [same]
================================================================================

Employer 1:
  Name:     Amy's House Inc.
  Location: Vernon, CALIFORNIA

Employer 2:
  Name:     AMY'S HOUSE, INC.
  Location: VERNON, CALIFORNIA

Similarity: 1.000
Cluster ID: 49
Canonical:  Amy's House Inc.
```

**Use when:** You want to review individual examples in detail.

### 5. All Formats (`--format all`)

Shows summary, compact table, markdown table, and detailed view.

**Use when:** You want a complete view of the dataset.

## Filtering Options

### Filter by Type

```bash
# Only show hand-reviewed examples
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-type reviewed

# Only show auto-clustered examples
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-type auto_clustered
```

### Filter by Ground Truth

```bash
# Only show "same" examples
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-truth same

# Only show "different" examples
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-truth different
```

### Filter by Similarity

```bash
# Only show high-similarity examples (>= 0.95)
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --min-similarity 0.95

# Only show low-similarity examples (<= 0.5)
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --max-similarity 0.5

# Show examples in a specific similarity range
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --min-similarity 0.8 \
  --max-similarity 0.95
```

### Limit Results

```bash
# Show only first 50 examples
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --limit 50
```

## Common Use Cases

### Review Hand-Reviewed Examples Only

```bash
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-type reviewed \
  --format detailed
```

### Find Edge Cases (Low Similarity but Same)

```bash
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-truth same \
  --max-similarity 0.7 \
  --format detailed
```

### Export for Documentation

```bash
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --filter-type reviewed \
  --format markdown \
  --output docs/reviewed_examples.md
```

### Quick Overview

```bash
bazel run //scripts/salary:view_clustering_examples -- \
  $(pwd)/data/clustering_examples.jsonl \
  --format summary
```

## Tips

1. **Start with summary** to understand dataset composition
2. **Use compact table** for quick scanning
3. **Use detailed format** when reviewing specific examples
4. **Export markdown** for documentation or sharing
5. **Filter by type** to focus on most reliable examples (reviewed)
6. **Use similarity filters** to find edge cases

## Example Output

### Summary
```
====================================================================================================
GOLDEN SET SUMMARY
====================================================================================================

Total Examples: 1975

By Type:
  auto_clustered      : 1500
  different_companies :  475
  reviewed           :    0

By Ground Truth:
  different:  475
  same    : 1500
```

### Compact Table
```
#    Type            Truth    Similarity Employer 1                          Employer 2
1    auto_clustered  same     1.000      Amy's House Inc.                    AMY'S HOUSE, INC.
2    auto_clustered  same     1.000      EVE HAIR, INC.                      Eve Hair, Inc.
```

### Detailed View
```
================================================================================
Example #1 ⚙ [auto_clustered] ✅ [same]
================================================================================

Employer 1:
  Name:     Amy's House Inc.
  Location: Vernon, CALIFORNIA

Employer 2:
  Name:     AMY'S HOUSE, INC.
  Location: VERNON, CALIFORNIA

Similarity: 1.000
Cluster ID: 49
Canonical:  Amy's House Inc.
```



