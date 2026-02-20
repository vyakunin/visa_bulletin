# Predictions & VQS: Current State Assessment and Next Steps

*Last updated: February 2026*

## 1. Executive Summary

The project has **two layers** of prediction capability at different maturity levels:

| Layer | Status | Accuracy | Description |
|-------|--------|----------|-------------|
| **Simple Linear Projection** | Deployed, live on dashboard | 1-month MAE 77d, 12-month MAE 359d | 12-month rolling average extrapolation |
| **VQS (Virtual Queue Simulation)** | Core engine built, backtested, not user-facing | V3: 54.8d mean error (recent, excl. EB4), 82.7% within 90d | Deterministic queue model using I-140 demand data |

The live projection uses a single method (linear extrapolation). The VQS system is substantially implemented with real accuracy results (V3), but is not yet exposed to users. It needs to consistently beat the "no change" baseline before shipping.

---

## 2. Current Projection System (Deployed)

### 2.1 Architecture

```
User selects priority date
        │
        ▼
cutoff_data_aggregator.py ──► cutoff_projection.py ──► calculate_projection()
        │                                                    │
        ▼                                                    ▼
  chart_builder.py                              Result: projected / current /
  (dashed lines on chart)                       no_movement / projected_historical
```

### 2.2 Core Files

| File | Role | Lines |
|------|------|-------|
| `lib/business/bulletin/cutoff_projection.py` | Primary projection logic | ~266 |
| `lib/business/bulletin/cutoff_data_aggregator.py` | Aggregates data, calls projection | ~308 |
| `lib/business/bulletin/chart_builder.py` | Renders projection as dashed line | ~301 |
| `tests/test_projection.py` | Unit tests (all passing) | ~219 |
| `lib/projection.py` | **Legacy duplicate** (used by `lib/dashboard_service.py`) | ~241 |
| `lib/dashboard_service.py` | **Legacy duplicate** of `cutoff_data_aggregator.py` | ~277 |

### 2.3 Algorithm Details

**Method 1: 12-Month Rolling Average (primary)**

```python
recent_points = valid_points[-12:]
days_advanced = (last_cutoff - first_cutoff).days
avg_days_per_month = days_advanced / months_elapsed
months_to_wait = days_to_advance / avg_days_per_month
estimated_date = last_pub + timedelta(days=months_to_wait * 30)
```

Limitations:
- Uses only endpoint-to-endpoint delta (ignores intermediate volatility)
- No weighting (recent months count the same as 12 months ago)
- `add_months_to_date` uses crude 30-day approximation
- No confidence intervals or error bounds
- No handling of fiscal year resets, retrogression cycles, or seasonal patterns

**Method 2: Historical Linear Regression (fallback when avg_days_per_month <= 0)**

Limitations:
- Simple OLS on entire history (no weighting for recency)
- Assumes linear relationship globally (visa movement is highly non-linear)
- No R² or goodness-of-fit reporting
- Only kicks in when recent movement is zero or negative

### 2.4 Known Issues

1. **Duplicate code**: `lib/projection.py` is a legacy duplicate of `lib/business/bulletin/cutoff_projection.py`. `lib/dashboard_service.py` is a near-duplicate of `cutoff_data_aggregator.py`. Both are candidates for deletion.

2. **No confidence intervals**: Users see "Est. March 2035" with no indication of uncertainty.

3. **Crude date arithmetic**: `add_months_to_date` uses `days * 30` approximation.

4. **No seasonal/cyclical modeling**: Visa bulletins have known seasonal patterns that are ignored.

---

## 3. VQS (Virtual Queue Simulation) — Status: Built, Not User-Facing

### 3.1 What Exists

**Core engine** (`lib/business/vqs/`):
- `solver.py` — Simulation engine with monthly loop, per-class supply, seasonality, spillover, retrogression
- `demand.py` — Queue builder from raw facts (I-140 receipts + PERM lag convolution)
- `supply/` — Per-country supply allocation with caps, cascading, spillover
- `accuracy_metrics.py` — Bulletin-by-bulletin and long-term accuracy computation with checkpointing
- `expert_pool.py` — Multi-model ensemble
- `seasonal_predictor.py` — Seasonal pattern detection
- `meta_params.py` — Meta-parameter tuning
- `aggregator.py`, `data_cache.py`, `estimators.py`, `ingest_utils.py`, `queue_snapshot.py`, `reporting.py`

**Scripts** (`scripts/vqs/`):
- `ingest_uscis_i140.py` — Ingest I-140 receipts into `raw_facts_ledger`
- `compute_perm_lag.py` — Compute PERM lag histogram
- `run_simulation.py` — Run queue simulation
- `run_backtest.py` — Backtest against historical bulletins
- `compute_prediction_accuracy.py` — Comprehensive accuracy metrics with Plotly plots

**Backtest scripts** (`scripts/`):
- `scripts/bulletin/backtest_projections.py` — Backtest the deployed linear projection
- `scripts/vqs_backtest.py` — VQS-specific backtest helpers

**Data model**:
- `models/raw_facts.py` — `RawFactsLedger`: append-only bi-temporal store (migration 0033)

**Webapp integration** (not exposed to users yet):
- `webapp/views/prediction_views.py` — Prediction list and detail views
- `webapp/views/bulletin/vqs_api.py` — VQS API endpoint
- `webapp/templates/vqs/` — Prediction templates

### 3.2 V3 Accuracy Results

| Metric | Baseline Linear | VQS V3 (recent, excl. EB4) |
|--------|----------------|---------------------------|
| Mean error | 77d (1-month) / 359d (12-month) | 54.8d |
| Within 90 days | 92% (1-month) / 57% (12-month) | 82.7% |
| Over-prediction rate | Systematic optimism bias | 4% (conservative) |
| Within 30 days | N/A | 53.3% |

Key series accuracy (V3, recent):
- EB2 India: 71.0d mean error
- EB2 China: 76.1d mean error
- EB3 India: 95.2d mean error
- EB1 All: 30.6d mean error
- EB3 All: 24.9d mean error

### 3.3 Data Ingested

| Source | Rows | Status |
|--------|------|--------|
| Historical visa bulletins | 286 (2002-2026) | Complete |
| Visa cutoff dates | 27,280 | Complete |
| USCIS I-140 receipts | 144 (FY2025 Q3 only) | Partial — need FY2020-FY2025 |
| PERM lag distribution | 12 | Complete from 2,677 PERM records |

---

## 4. Stale Documentation Identified

| Item | Issue | Action |
|------|-------|--------|
| `lib/projection.py` | Legacy duplicate of `lib/business/bulletin/cutoff_projection.py` | Delete after updating importers |
| `lib/dashboard_service.py` | Near-duplicate of `cutoff_data_aggregator.py` | Delete after updating importers |
| `lib/chart_builder.py` | Legacy wrapper | Consolidate with `lib/business/bulletin/chart_builder.py` |

---

## 5. Proposed Next Steps

### Phase 0: Clean Up (0.5 day) — Not yet done

1. **Delete legacy duplicates:**
   - Delete `lib/projection.py`, update imports to `lib.business.bulletin.cutoff_projection`
   - Delete `lib/dashboard_service.py`, update imports to `lib.business.bulletin.cutoff_data_aggregator`
   - Delete or consolidate `lib/chart_builder.py`

### Phase 1: Ship VQS to Users (1-2 weeks)

**Blocker:** VQS must consistently beat the "no change" baseline (next cutoff = previous cutoff). See `docs/future_features/VQS_BEAT_NO_CHANGE_PROPOSAL.md`.

1. **Beat no-change baseline** — Implement stickiness/threshold, low-confidence fallback, blend with baseline
2. **Ingest more I-140 data** — Download FY2020-FY2025 quarterly reports to improve queue depth
3. **Add confidence intervals** — Show prediction range based on historical error distribution
4. **Expose on dashboard** — Side-by-side or blended with current linear projection
5. **Personal wait time calculator** — Enter priority date, get predicted timeline with confidence

### Phase 2: Further VQS Improvements (2-4 weeks)

1. **Better EB4 handling** — Currently low-confidence (no I-140 data for EB4)
2. **Supply rebalancing** — Better spillover modeling from historical DOS visa issuance data
3. **Retrogression prediction** — Learn from historical October retrogression patterns
4. **EB1 India fine-tuning** — Currently has higher error than other India series
5. **Family-based extension** — See `VQS_FAMILY_EXTENSION_DESIGN.md`

### Phase 3: Advanced Features (future)

1. **Scenario modeling** — "What if per-country caps are removed?" / "What if quota doubles?"
2. **Bulletin update alerts** — "Your wait time changed from 25 to 24.2 years"
3. **API endpoint** — Expose predictions via REST API for integrators
4. **Multiple model comparison** — Run several models and pick best per-series

---

## 6. Priority Recommendation

| Priority | Item | Effort | Impact | Status |
|----------|------|--------|--------|--------|
| ~~P0~~ | ~~Backtest current projections~~ | ~~1 day~~ | | **Done** — Section 7 |
| ~~P0~~ | ~~Move VQS stubs to proposal doc~~ | ~~0.5 day~~ | | **Done** |
| ~~P0~~ | ~~Build VQS core engine~~ | ~~2-4 weeks~~ | | **Done** — V3 |
| **P0** | Delete legacy duplicates | 0.5 day | Low (code health) | Not started |
| **P1** | Beat no-change baseline | 2-3 days | Critical (ship blocker) | Proposal written |
| **P1** | Ingest more I-140 data | 1 day | High (accuracy) | Partial (1 quarter) |
| **P1** | Confidence intervals | 1 day | High (user trust) | Not started |
| **P1** | Expose VQS on dashboard | 2-3 days | Very High (user value) | Views exist, not routed |
| **P2** | Personal wait time calculator | 1 week | Very High (user value) | Not started |
| **P2** | EB4 handling | 1 day | Medium | Not started |
| **P3** | Family-based VQS | 1-2 weeks | Medium | Design written |
| **P3** | Scenario modeling | 1 week | Medium | Not started |

---

## 7. Baseline Accuracy (Backtest Results — February 2026)

Backtest script: `scripts/bulletin/backtest_projections.py`
Evaluation period: 2016–present, 58,438 total predictions across 358 series.

### Overall Results

| Horizon | N | Successful | No Movement | MAE (days) | Median AE | Mean Error | <90d | <180d |
|---------|---|------------|-------------|------------|-----------|------------|------|-------|
| 1 month | 15,434 | 15,393 | 41 | **77** | 1 | +58 | 92% | 94% |
| 3 months | 15,072 | 14,992 | 80 | **149** | 3 | +111 | 78% | 90% |
| 6 months | 14,518 | 14,405 | 113 | **221** | 32 | +152 | 66% | 80% |
| 12 months | 13,414 | 13,298 | 116 | **359** | 35 | +231 | 57% | 66% |

### Key Observations

1. **Systematic optimism bias**: Mean error is positive at all horizons (+58 to +231 days), meaning the model consistently predicts dates will be reached *later* than they actually are.

2. **Median AE vs MAE divergence**: The model is accurate for *most* predictions but has large outliers.

3. **Worst series** (12-month MAE > 1000 days): EB-2 India, EB-5 China subcategories, F2B, F1 Mexico.

4. **One-month-ahead is decent**: 92% within 90 days.

### Success Metrics

| Metric | Baseline (Linear) | VQS V3 (recent) | Target (Ship) |
|--------|-------------------|------------------|---------------|
| Mean error (recent bulletins) | ~77d (1-month) | 54.8d | <50d |
| Within 90 days | 92% (1-month) | 82.7% | >85% |
| Beat no-change baseline | Unknown | Not yet | Required |
| Confidence interval coverage | None | None | 80% of actuals within range |

---

## 8. Appendix: File Inventory

### Active Production Files (Deployed Linear Projection)

| File | Purpose | Used By |
|------|---------|---------|
| `lib/business/bulletin/cutoff_projection.py` | Primary projection logic | `cutoff_data_aggregator.py`, `test_projection.py` |
| `lib/business/bulletin/cutoff_data_aggregator.py` | Dashboard data aggregation | `webapp/views/bulletin/dashboard.py` |
| `lib/business/bulletin/chart_builder.py` | Chart building with projections | `webapp/views/bulletin/dashboard.py` |
| `tests/test_projection.py` | Projection unit tests | CI |

### VQS System (Built, Not User-Facing)

| File | Purpose |
|------|---------|
| `lib/business/vqs/solver.py` | Queue simulation engine |
| `lib/business/vqs/demand.py` | Demand model (I-140 + PERM lag) |
| `lib/business/vqs/supply/` | Supply allocation (per-class, seasonal, spillover) |
| `lib/business/vqs/accuracy_metrics.py` | Accuracy computation with checkpointing |
| `lib/business/vqs/expert_pool.py` | Multi-model ensemble |
| `lib/business/vqs/seasonal_predictor.py` | Seasonal pattern detection |
| `scripts/vqs/*.py` | VQS scripts (ingest, simulate, backtest, accuracy) |
| `scripts/bulletin/backtest_projections.py` | Linear projection backtester |
| `models/raw_facts.py` | Bi-temporal data model for VQS |
| `webapp/views/prediction_views.py` | Prediction views (not routed) |
| `webapp/views/bulletin/vqs_api.py` | VQS API endpoint (not routed) |

### Legacy Files (Candidates for Deletion)

| File | Duplicate Of | Used By |
|------|-------------|---------|
| `lib/projection.py` | `lib/business/bulletin/cutoff_projection.py` | `lib/dashboard_service.py` |
| `lib/dashboard_service.py` | `lib/business/bulletin/cutoff_data_aggregator.py` | `webapp/views.py` (legacy) |
| `lib/chart_builder.py` | Wrapper around `lib/business/bulletin/chart_builder.py` | `webapp/views.py` (legacy), `tests/test_chart_builder.py` |

### Documentation

| File | Content |
|------|---------|
| `docs/PREDICTIONS_ASSESSMENT.md` | This file — overall assessment |
| `docs/future_features/VQS_PROPOSAL.md` | VQS feature status and overview |
| `docs/future_features/VQS_TEST_REPORT.md` | Detailed V1-V3 accuracy results |
| `docs/future_features/VQS_RUNBOOK.md` | Operational runbook for VQS |
| `docs/future_features/VQS_BEAT_NO_CHANGE_PROPOSAL.md` | Strategy to beat naive baseline |
| `docs/future_features/VQS_NEW_SUGGESTIONS.md` | Post-V3 improvement ideas |
| `docs/future_features/VQS_META_PARAMS_AND_TUNING.md` | Meta-parameter tuning |
| `docs/future_features/VQS_FAMILY_EXTENSION_DESIGN.md` | Family-based VQS design |
| `docs/future_features/SMART_PREDICTIONS_PROPOSALS.md` | Original prediction proposals |
| `docs/future_features/SMART_PREDICTIONS_VQS_PROPOSAL.md` | Original VQS design |
