# Phase 2 Employer Clustering – Where Time Is Spent and Optimizations

## Where time is spent (Phase 2)

Phase 2 processes **272,690 candidate (norm1, norm2) pairs** (LSH output). The progress bar reports ~38 candidate pairs/sec → ~2h total.

### Per-candidate work

1. **Outer loop (once per candidate)**
   - `_get_normalized_name_similarity(norm1, norm2)` → **1× `difflib.SequenceMatcher(None, norm1, norm2).ratio()`**
   - If `similarity >= 0.7`: `employers1 = employers_by_normalized[norm1]`, `employers2 = employers_by_normalized[norm2]`
   - `_process_cross_employer_pairs(employers1, employers2, ...)` → **N×M iterations** (cartesian product)

2. **Per (emp1, emp2) inside _process_cross_employer_pairs**
   - `_process_employer_pair(emp1, emp2, ...)` → `should_auto_cluster(...)` → **`match_employers(emp1, emp2, norm1, norm2)`**
   - `match_employers` runs four checks in order:
     - `_check_hyphen_variation(emp1, emp2, norm1, norm2)` – uses raw names
     - `_check_exact_match(...)` – for Phase 2, `norm1 != norm2` → returns `None`
     - `_check_substring_match(emp1, emp2, norm1, norm2)` – `norm1 in norm2` / `norm2 in norm1` (same for all pairs with same (norm1, norm2)), then qualifiers/structural words per employer
     - **`_check_similarity_match(...)`** – **computes `difflib.SequenceMatcher(None, norm1, norm2).ratio()` again**

So for each candidate we compute **the same `SequenceMatcher(norm1, norm2)` at least twice**: once for the 0.7 filter and once (or N×M times) inside `_check_similarity_match`. When there are multiple employers per normalized name, we recompute the same ratio for every (emp1, emp2) with that (norm1, norm2).

### Cost breakdown (order-of-magnitude)

- **SequenceMatcher**: O(n·m) per call; we do 1 + (number of employer pairs with sim≥0.7) calls per (norm1, norm2) for the same strings → large duplicate work.
- **Substring**: `norm1 in norm2` / `norm2 in norm1` is O(n+m) and is the same for all (emp1, emp2) in the candidate; we still run it and the rest of `_check_substring_match` (qualifiers, structural words) for every employer pair.
- **Structural words / hyphen / exact**: Per (emp1, emp2), relatively cheap (set ops, regex on short strings).

So the dominant redundant work is:
1. **Repeated `SequenceMatcher(norm1, norm2)`** for the same (norm1, norm2).
2. **Repeated substring + qualifier/structural work** when substring cannot match (`norm1 not in norm2 and norm2 not in norm1`).

---

## Implemented optimizations

### 1. Pass precomputed similarity into `match_employers`

- Phase 2 already computes `similarity = _get_normalized_name_similarity(norm1, norm2)` once per candidate.
- Thread an optional `precomputed_similarity: float | None` from the Phase 2 loop → `_process_cross_employer_pairs` → `_process_employer_pair` → `should_auto_cluster` → `match_employers` → `_check_similarity_match`.
- When `precomputed_similarity` is provided, `_check_similarity_match` uses it and does **not** call `SequenceMatcher(norm1, norm2)` again.
- **Effect**: Removes 272,690+ redundant `SequenceMatcher` calls (one per candidate, or more when N×M > 1).

### 2. Pass substring short-circuit into `match_employers`

- For each candidate compute once: `substring_can_match = (norm1 in norm2 or norm2 in norm1)`.
- Pass as optional `substring_can_match: bool | None` into `match_employers`. When `False`, `_check_substring_match` returns `None` immediately without running qualifiers/structural words.
- **Effect**: When substring cannot match (common for LSH candidates that are similar but not substring), we skip the rest of `_check_substring_match` for every (emp1, emp2) in that candidate.

---

## Further optimization options

### 3. Faster ratio implementation (RapidFuzz) — **implemented**

- **RapidFuzz** is now the only implementation (no difflib fallback). Used in `_get_normalized_name_similarity` and `_check_similarity_match` via `fuzz.ratio(norm1, norm2) / 100.0`.
- Local benchmark (see `scripts/salary/benchmark_rapidfuzz.py`): **272,690 pairs** → difflib ~2.7s (101k pairs/sec), rapidfuzz ~0.08s (3.5M pairs/sec) → **~35×** on the ratio call itself.
- **Expected Phase 2 impact**: Ratio was previously a large share of per-candidate work; with precomputed_similarity we only call ratio once per candidate. So Phase 2 should drop from ~2h to roughly **10–30 min** (depending on DB and other work). Measure on next full run.

### 4. Parallelize candidate processing

- Phase 2 outer loop is embarrassingly parallel over candidate pairs.
- **Idea**: Use `concurrent.futures.ProcessPoolExecutor` to process chunks of `candidate_pairs` in parallel. Each worker would need a copy of `employers_by_normalized` (or shared memory / chunked input) and would call the same matching logic.
- **Caveats**: BatchedUpdates and checkpointing are not trivially thread-safe; would need to either merge results in the main process or use a queue. GIL is less of an issue if using processes.

### 5. Reduce candidate set

- Increase LSH threshold (e.g. 0.75 or 0.8) to get fewer, higher-quality candidates → fewer iterations and fewer `match_employers` calls, at the cost of some recall.
- Or run a cheaper pre-filter (e.g. length difference, first token) before calling `match_employers`.

---

### 6. Further optimizations (proposed)

- **Batch DB writes**: Already using BatchedUpdates; ensure flush batch size and transaction boundaries are tuned for 2GB (e.g. 1k–2k clusters per flush).
- **LSH parameters**: Tune `num_perm` and threshold so candidate count stays in a sweet spot (fewer candidates → faster Phase 2; too high threshold → recall drop). Profile Phase 2 time vs candidate count on prod.
- **Skip low-yield candidates**: If `len(employers1) * len(employers2)` is very large (e.g. > 10k) for a (norm1, norm2) pair, consider skipping or sampling to cap N×M work per candidate.
- **Parallelize Phase 2**: Process chunks of `candidate_pairs` in a ProcessPoolExecutor; merge BatchedUpdates in the main process (non-trivial: checkpointing and shared state need design).

---

## Summary

- **Bottleneck (addressed)**: Redundant ratio and repeated substring/structural work for the same (norm1, norm2).
- **Implemented**: (1) Precomputed similarity; (2) `substring_can_match` short-circuit; (3) RapidFuzz only; (4) BatchedUpdates pre-load + lazy clusters; (5) 24h timeout; (6) runner bazel target fix.
- **Next**: Measure Phase 2 duration on prod after deploy; then consider LSH tuning, candidate capping, or parallelization if still slow.
