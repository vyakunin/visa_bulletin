# Future Features Documentation

This directory contains design documents for features that are planned but not yet implemented.

## VQS / Prediction Documents

The main research log and assessment lives in **`docs/PREDICTIONS_ASSESSMENT.md`** (not in this directory). It contains numbered experiment sections documenting what was tried, results, and lessons.

| File | Status | Content |
|------|--------|---------|
| **VQS_RUNBOOK.md** | Current | Operational runbook: how to add I-140 data, re-run accuracy |
| **VQS_NEW_SUGGESTIONS.md** | Current | Active improvement ideas (EB4, supply rebalance, I-140 data, retrogression, tabular ML, community baselines) |
| **VQS_META_PARAMS_AND_TUNING.md** | Current | Meta-parameter design, tuning strategy, search space, critique/risks |
| **VQS_FAMILY_EXTENSION_DESIGN.md** | Current | Design for extending VQS to family-based categories (not implemented) |

### Deleted (March 2026 cleanup)

The following files were superseded by `docs/PREDICTIONS_ASSESSMENT.md` and deleted. Their content is preserved in git history and key ideas were extracted into the documents above.

- `VQS_PROPOSAL.md` — Feature status/overview (superseded by PREDICTIONS_ASSESSMENT §3)
- `VQS_TEST_REPORT.md` — V2 accuracy results (superseded by PREDICTIONS_ASSESSMENT §7-9)
- `VQS_BEAT_NO_CHANGE_PROPOSAL.md` — Strategy to beat persistence (all proposals implemented; outcome in PREDICTIONS_ASSESSMENT §8-9)
- `VQS_META_PARAMS_CRITIQUE.md` — Design critique (merged into VQS_META_PARAMS_AND_TUNING.md §6)
- `SMART_PREDICTIONS_PROPOSALS.md` — Original ML prediction design (unexplored ML ideas extracted to VQS_NEW_SUGGESTIONS.md §9)
- `SMART_PREDICTIONS_VQS_PROPOSAL.md` — Original VQS design (implementation is the source of truth)

## Other Feature Documents

| File | Status | Content |
|------|--------|---------|
| **COMPANY_REPORT_CARD_DESIGN.md** | Design phase | Company green card sponsorship grading system |
| **PHASE2_CLUSTERING_OPTIMIZATION.md** | Current | Employer clustering Phase 2 performance optimization |

## When to Implement

Features should be prioritized based on:
1. **User demand** — How many users are requesting this feature?
2. **Data availability** — Do we have the necessary data?
3. **Implementation complexity** — How much effort is required?
4. **Strategic value** — Does it align with product goals?
5. **Dependencies** — What existing features must be in place first?

## Related

- **docs/PREDICTIONS_ASSESSMENT.md** — Main prediction research log (experiments, results, lessons)
- **lib/business/vqs/README.md** — VQS code-level documentation
- **docs/FEATURE_IDEAS.md** — Shorter feature ideas
