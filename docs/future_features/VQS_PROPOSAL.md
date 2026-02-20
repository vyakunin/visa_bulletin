# VQS (Virtual Queue Simulation) — Feature Status

*Status: Core engine implemented and backtested. V3 accuracy: 82.7% within 90 days for recent bulletins (excl. EB4). Not yet user-facing.*
*See also: `docs/PREDICTIONS_ASSESSMENT.md` for comparison with the deployed linear projection.*

## Overview

VQS predicts Visa Bulletin cutoffs and Green Card maturity dates using a deterministic queue simulation. Unlike the deployed simple linear projection (12-month rolling average), VQS models the actual supply/demand dynamics of the visa system.

## Current State (February 2026)

### What's Built

| Component | Location | Status |
|-----------|----------|--------|
| Queue simulation engine | `lib/business/vqs/solver.py` | Implemented (V3) |
| Demand model (I-140 + PERM lag) | `lib/business/vqs/demand.py` | Implemented |
| Supply model (per-class, seasonal, spillover) | `lib/business/vqs/supply/` | Implemented |
| Accuracy metrics (bulletin + long-term) | `lib/business/vqs/accuracy_metrics.py` | Implemented with checkpointing |
| Expert pool (multi-model ensemble) | `lib/business/vqs/expert_pool.py` | Implemented |
| Seasonal predictor | `lib/business/vqs/seasonal_predictor.py` | Implemented |
| Meta-parameter tuning | `lib/business/vqs/meta_params.py` | Implemented |
| I-140 ingest script | `scripts/vqs/ingest_uscis_i140.py` | Implemented |
| PERM lag computation | `scripts/vqs/compute_perm_lag.py` | Implemented |
| Simulation runner | `scripts/vqs/run_simulation.py` | Implemented |
| Backtest runner | `scripts/vqs/run_backtest.py` | Implemented |
| Accuracy computation | `scripts/vqs/compute_prediction_accuracy.py` | Implemented |
| Raw facts data model | `models/raw_facts.py` | Implemented (migration 0033) |
| Prediction views (webapp) | `webapp/views/prediction_views.py` | Implemented but not exposed to users |

### V3 Accuracy (Recent Bulletins, Excl. EB4)

| Metric | Value |
|--------|-------|
| Mean error | 54.8 days |
| Within 30 days | 53.3% |
| Within 60 days | 74.7% |
| Within 90 days | 82.7% |
| Over-prediction rate | 4% (conservative bias) |

See `docs/future_features/VQS_TEST_REPORT.md` for detailed accuracy breakdown by series and period.

### Data Ingested

| Source | Rows | Notes |
|--------|------|-------|
| Bulletins | 286 | 2002-10 through 2026-02 |
| Visa cutoff dates | 27,280 | EB + Family, filing + final_action |
| Raw facts (I-140) | 144 | USCIS FY2025 Q3 (one quarter) |
| Raw facts (PERM lag) | 12 | From 2,677 PERM records |

## Concept

The visa bulletin is fundamentally a queue: applicants wait in line by priority date, and each month a fixed quota of visas is allocated. VQS models this queue explicitly:

- **Demand side**: I-140 filings by country/class/priority-date (from USCIS FOIA data)
- **Supply side**: Annual visa allocation (140K EB total, 7% per-country cap, spillover rules, per-class shares, fiscal year seasonality)
- **Queue simulation**: For each month, allocate available visas to oldest priority dates first; the new cutoff is where supply runs out

## Scripts

### Ingest USCIS I-140

```bash
bazel run //scripts/vqs:ingest_uscis_i140 -- --file path/to/i140_rec_fy2024_q3.xlsx
bazel run //scripts/vqs:ingest_uscis_i140 -- --stub  # stub data for testing
```

### Run Simulation

```bash
bazel run //scripts/vqs:run_simulation -- --knowledge-date 2026-02-07 --visa-class 2nd --country 3 --action-type final_action
```

### Compute Accuracy

```bash
bazel run //scripts/vqs:compute_prediction_accuracy -- --metric both --plot --output-dir /tmp/vqs_accuracy --checkpoint-dir /tmp/vqs_ckpt
```

See `docs/future_features/VQS_RUNBOOK.md` for complete runbook.

## Remaining Work to Ship to Users

### P0: Beat the "No Change" Baseline
The naive "next cutoff = previous cutoff" baseline currently has lower mean error for some series. The model must consistently beat this before shipping. See `VQS_BEAT_NO_CHANGE_PROPOSAL.md`.

### P1: More I-140 Data
Only one quarter of I-140 data is ingested. Downloading FY2020-FY2025 quarterly reports would significantly improve queue depth estimation.

### P2: User-Facing Integration
- Expose predictions on dashboard alongside current linear projection
- Add confidence intervals to displayed predictions
- Personal wait time calculator (enter priority date, get timeline)

### P3: Further Accuracy Improvements
- Better EB4 handling (currently low-confidence due to no I-140 data)
- Supply rebalancing and better spillover modeling
- Retrogression prediction from historical patterns

## Related Documentation

- `VQS_TEST_REPORT.md` — Detailed accuracy results (V1 through V3)
- `VQS_RUNBOOK.md` — Commands for data ingestion and re-running accuracy
- `VQS_BEAT_NO_CHANGE_PROPOSAL.md` — Strategy to beat naive baseline
- `VQS_NEW_SUGGESTIONS.md` — Post-V3 improvement ideas
- `VQS_META_PARAMS_AND_TUNING.md` — Meta-parameter tuning details
- `VQS_FAMILY_EXTENSION_DESIGN.md` — Design for family-based category support
- `SMART_PREDICTIONS_PROPOSALS.md` — Original prediction proposals
- `SMART_PREDICTIONS_VQS_PROPOSAL.md` — Original VQS design proposal
- `lib/business/vqs/README.md` — Code-level documentation
