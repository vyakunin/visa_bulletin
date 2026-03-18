# Predictions & VQS: Current State Assessment and Next Steps

*Last updated: March 2026*

## 1. Executive Summary

The project has **two layers** of prediction capability at different maturity levels:

| Layer | Status | Accuracy | Description |
|-------|--------|----------|-------------|
| **Simple Linear Projection** | Deployed, live on dashboard | 1-month MAE 77d, 12-month MAE 359d | 12-month rolling average extrapolation |
| **VQS Ensemble (tuned)** | Built, backtested, not shipped | 1m MAE 41.4d (≈ persistence 41.5d), 6m wins 4/6 series | Optuna-tuned meta + aggregator; close to persistence on average MAE, better on composite and at 6m |
| **Regime-Switched Model** | Built, evaluated (Mar 2026) | 1m MAE 40.9d, beats persistence 3/5 series | Undampened expert selector — best average MAE at 1m/3m |
| **Pace** | Baseline in evaluation | 6m MAE 211d, beats persistence 6/6 at 6m | Constant-pace extrapolation; best at 6m horizon |

The **single predictor to use in production** is the **VQS Ensemble**: `predict_next_bulletin_and_maturity(..., meta=VqsMetaParams.defaults(), aggregator=ExpertAggregator())` (same path as `publish_predictions`). It accumulates the tuned meta params, learning rate, and metric-driven warmup. Regime-Switched and Pace are alternative models that sometimes beat the ensemble on raw MAE but are not merged into the published predictor. See Section 11 for post-tune comparison and exact invocation.

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

## 3. VQS (Virtual Queue Simulation) — Status: Live

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

**Webapp integration** (live at `/predictions/`, `/spaghetti/`, `/metric-report/`, `/api/vqs/predict/`):
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

### 3.3 Why Published Predictions Look Conservative

Users often see predicted movement in the -2 to 0 day range even when the actual bulletin later shows large moves (e.g. +14 to +360 days in October). This is by design:

- **Aggregator**: 50% weight is given to the "persistence" expert (no change); the rest is split among other experts (`aggregator.py`).
- **Stickiness**: Moves smaller than a threshold (60–90 days depending on regime) are suppressed to "no change" to reduce noise (`meta_params.py`: `stickiness_days`, `stickiness_stall_days`).
- **Caps**: Forward movement is capped at 45 days/month; backward at 60 days (`cap_forward_days`, `cap_back_days`).
- **Ensemble persistence blend**: Final prediction is blended 40% with current cutoff (`ensemble_persistence_weight: 0.4`), further pulling toward no change.
- **October**: One expert explicitly returns persistence for October; fiscal-year reset logic is limited.
- **Regime-aware adaptation**: Stalled/volatile series get persistence weight 0.80–0.90 and higher stickiness; advancing series get 0.35 (more model signal).

**Improvement directions**: Lower persistence weight or stickiness for high-advancement regimes; add October-specific expert or seasonal adjustment; re-tune meta_params on recent backtests including Oct 2025.

### 3.4 Prediction Explainability

The solver now returns rich metadata with each prediction (via 5-tuple return from `predict_next_bulletin_and_maturity`):

| Signal | Source | Used In |
|--------|--------|---------|
| Regime (ADVANCING/STALLED/RETROGRESSING/RECOVERING/VOLATILE) | `regime.py` `classify_regime()` | `explanation_markdown`, blog posts |
| Regime confidence, avg move, volatility | `RegimeState` dataclass | Blog outlook section |
| Pace (days/month) | `calibrate_queue_depth()` | Blog context, explanation |
| Expert weights (8 experts) | `aggregator.predict()` | Explanation, blog expert consensus |
| Expert predictions (8 individual forecasts) | `aggregator.predict()` | Blog surprise analysis |
| Persistence weight (effective, after regime scaling) | `regime_persistence_weight()` | Explanation markdown |
| Confidence intervals (low/high) | Expert disagreement spread | Prediction detail page, blog |

The `BulletinNarrator` (`lib/business/blog/bulletin_narrator.py`) uses these signals to generate data-driven blog posts with regime analysis, historical pace context, and optional LLM prose polishing via Ollama.

### 3.5 Data Ingested

| Source | Rows | Status |
|--------|------|--------|
| Historical visa bulletins | 286 (2002-2026) | Complete |
| Visa cutoff dates | 27,280 | Complete |
| USCIS I-140 receipts | 144 (FY2025 Q3 only) | Partial — need FY2020-FY2025 |
| PERM lag distribution | 12 | Complete from 2,677 PERM records |

---

## 4. Stale Documentation — Resolved

| Item | Status |
|------|--------|
| `lib/projection.py` | Deleted (Phase 0) |
| `lib/dashboard_service.py` | Deleted (Phase 0) |
| `lib/chart_builder.py` | Deleted (Phase 0) |
---

## 5. Proposed Next Steps

### Phase 0: Clean Up (0.5 day) — Done

1. ~~Delete legacy duplicates~~ — Deleted `lib/projection.py`, `lib/dashboard_service.py`, `lib/chart_builder.py`, `webapp/views.py` (all dead code; URL routing already used new views)

### Phase 1: Ship VQS to Users (1-2 weeks) — In Progress

1. ~~**Beat no-change baseline**~~ — Fixed double-apply bug in `solver.py` (post-step shaping was applied twice to ensemble predictions, over-dampening the signal). Added `compare_to_no_change_baseline()` to `accuracy_metrics.py` and baseline reporting to `compute_prediction_accuracy.py`. Stickiness/threshold/caps/blend/low-confidence fallback were already implemented in `VqsMetaParams`.
2. ~~**Ingest more I-140 data**~~ — Created `scripts/vqs/download_uscis_i140.py` to batch-download FY2020-FY2025 quarterly reports from USCIS and ingest via existing `ingest_uscis_i140.py`.
3. ~~**Add confidence intervals**~~ — Confidence intervals (from expert disagreement) now surfaced in VQS API response (`confidence_low`, `confidence_high`) and displayed on dashboard.
4. ~~**Expose on dashboard**~~ — VQS predictions shown in "Queue Model" column alongside linear projections for employment-based categories, with confidence indicators (green/yellow/gray dots) and prediction ranges.
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
| ~~P0~~ | ~~Delete legacy duplicates~~ | ~~0.5 day~~ | | **Done** |
| ~~P1~~ | ~~Beat no-change baseline~~ | ~~2-3 days~~ | | **Done** — double-apply fix + baseline comparison |
| ~~P1~~ | ~~Ingest more I-140 data~~ | ~~1 day~~ | | **Partial** — download script created; only FY2025 Q3 (144 rows) ingested. FY2020-FY2024 not yet downloaded. |
| ~~P1~~ | ~~Confidence intervals~~ | ~~1 day~~ | | **Done** — API + dashboard |
| ~~P1~~ | ~~Expose VQS on dashboard~~ | ~~2-3 days~~ | | **Done** — Queue Model column |
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
| Confidence interval coverage | None | Measured in reporting, narrator, and backtest | 80% of actuals within range |

### Completed Improvements

1. **Supply rebalancing** — Done. `country_cap.py` splits 7% cap across visa classes via `PER_CLASS_SHARE` (INA proportions).
2. **CI coverage measurement** — Done. `compute_ci_coverage()` in `accuracy_metrics.py` is now used by `reporting.py`, `vqs_backtest.py`, and the blog narrator. Analysis page shows CI coverage per bulletin.
3. **October expert** — Done. `expert_fy_reset()` covers all 12 months: Oct retrogression, Nov-Jan recovery, Feb-Sep seasonal.
4. **Per-expert signal storage** — Done. `PredictedCutoff.expert_predictions` JSONField stores each expert's predicted date and weight. Analysis page shows full model breakdown per prediction.

### Top Remaining Improvements

1. **I-140 data completeness** — Download script exists (`scripts/vqs/download_uscis_i140.py`) for FY2020-FY2025. Only FY2025 Q3 (144 rows) is ingested. Run the download script to get FY2020-FY2024 data; older files may need URL pattern or format updates.

---

## 8. FY Boundary Experiment (February 2026): Results and Lessons

### Motivation

The VQS model has a structural weakness at fiscal year boundaries (September retrogression, October reset). The model treats these large moves as noise and suppresses them via persistence blending (0.80-0.95 weight), forward/backward caps (45/60 days), and stickiness thresholds. October average jumps are +396 to +551 days — far exceeding the 45-day forward cap.

Diagnosis: five structural mismatches (detailed in `.cursor/plans/vqs_bi-modal_improvement_analysis_fea72611.plan.md`):
1. Regime detection is backward-looking and calendar-blind
2. Persistence blending is self-defeating at FY boundaries
3. Forward/backward caps are too restrictive for FY transitions
4. Seasonal medians are unconditional (ignore FY context)
5. No fiscal year budget tracking

### What Was Implemented

Five changes, gated behind `fy_boundary_aware=True` flag in `predict_next_bulletin_and_maturity()`:

| Change | Files | Description |
|--------|-------|-------------|
| FY-phase regime | `lib/business/vqs/regime.py` | New `FYPhase` enum (`FY_RESET`, `CONSERVATIVE`, `ACCELERATION`, `END_OF_FY`). Deterministic phase from target month. |
| Lifted caps/persistence | `lib/business/vqs/regime.py` | At FY_RESET: forward cap=1500d, persistence=0.05, stickiness=0. At END_OF_FY: backward cap=500d, persistence=0.15. |
| Conditional FY transition model (Tier 2) | `lib/business/vqs/fy_transition_model.py` | Nearest-neighbor predictor using utilization rate, backlog depth, cross-series signals. Separate methods for Oct/Sep/Aug. |
| FY utilization tracking | `lib/business/vqs/fy_utilization.py` | Cumulative DOS issuance vs annual allocation, historical FY transition collection. |
| Two-tier integration | `lib/business/vqs/solver.py` | Tier 2 (60%) + Tier 1 (40%) blending at FY boundaries (target months 8, 9, 10). |

### Results: Model Regressed

**Bulletin-by-Bulletin Accuracy (vs persistence baseline):**

| Metric | Before (no FY-aware) | After (FY-aware) | Delta |
|--------|---------------------|------------------|-------|
| All excl EB4 MAE | 299.4d | 300.6d | +1.2d worse |
| Recent excl EB4 MAE | 33.1d | 35.8d | **+2.7d worse** |
| Model win % (recent) | 3.8% | 4.5% | +0.7pp (more disagreements, but more losses too) |
| Beats baseline? | No | No | — |

**Long-Term Accuracy by Series (impacted series only):**

| Series | Before | After | Delta |
|--------|--------|-------|-------|
| India EB-2 | 169.7d | 216.3d | **+46.6d (+27%)** |
| India EB-3 | 108.9d | 114.6d | +5.7d |
| China EB-3 | 136.9d | 141.7d | +4.8d |
| China EB-2 | 167.3d | 167.6d | +0.3d |
| All others | unchanged | unchanged | 0 |

**Spaghetti Chart MAE (all 6 oversubscribed series):**

| Horizon | Persistence | VQS Ensemble | VQS beats persistence |
|---------|-------------|-------------|----------------------|
| 1m | 41.5d | 47.8d | 0/6 series |
| 3m | 122.5d | 130.7d | 0/6 series |
| 6m | 228.3d | 240.0d | 2/6 series |

### Why It Failed

1. **India EB-2 Tier 2 catastrophic (+46.6d).** The conditional FY transition model uses nearest-neighbor on ~8 historical FY transitions per series. With 3-5 features on 8 data points, predictions are noisy and often worse than the damped Tier 1 output.

2. **60/40 Tier2/Tier1 blending too aggressive.** Even moderate Tier 2 errors get amplified because they receive 60% weight.

3. **Persistence weight 0.05 at FY_RESET too extreme.** Dropping from ~0.90 to 0.05 means the model trusts a noisy signal 95%. The "cure" is worse than the "disease" of over-damping.

4. **Non-boundary months unaffected** (correctly). The damage is concentrated in Aug/Sep/Oct predictions but large enough to drag overall metrics down.

### Current Status

The `fy_boundary_aware` flag defaults to `False` in the solver. It was temporarily enabled in `prediction_loader.py`, `accuracy_metrics.py`, and `publish_predictions.py` for this experiment. **These call sites should be reverted to `False` (or the flag removed) before any production deployment.**

The spaghetti chart (`webapp/templates/spaghetti.html`) and historical predictions (`PredictedBulletin`/`PredictedCutoff` for Jan 2024 – Apr 2026) were regenerated with `fy_boundary_aware=True` and reflect the worse performance.

### Lessons and Next Steps

The core diagnosis remains valid — the model suppresses real FY boundary signals. But the proposed fix (conditional model + aggressive parameter override) doesn't have enough data to improve accuracy. Future attempts should:

1. **Start simpler**: Only lift caps and lower persistence modestly (persistence=0.3-0.4, not 0.05) without introducing a Tier 2 model
2. **October only**: Apply boundary treatment only to October predictions (most predictable), not Aug/Sep
3. **Lower Tier 2 weight**: If using a conditional model, weight it at 0.1-0.2 (advisory), not 0.6
4. **More training data**: Wait for more FY transitions (currently only ~8 per series) before trusting a conditional predictor
5. **Validate incrementally**: Test each change separately (lifted caps alone, then persistence alone, then Tier 2) rather than bundling

---

## 9. Regime-Switched Model Experiment (March 2026)

### Motivation

After the FY Boundary experiment (Section 8) regressed, a different approach was tried: instead of adding complex conditional logic for boundary months, use a **regime-switched expert selector** that picks the single best expert per (series, regime) without ensemble dampening. The hypothesis was that the dampening stack (persistence blending, stickiness, caps) was the core problem — not insufficient boundary data.

### What Was Implemented

A new `predict_regime_switched()` function in `solver.py`:
- For each prediction, classifies regime (ADVANCING/STALLED/RETROGRESSING/RECOVERING/VOLATILE) from last 6 months of movement
- Picks a single best expert per (series, regime) based on Phase 1 backtest results (`backtest_experts.py`)
- **No ensemble, no stickiness, no caps, no persistence blending** — raw expert output
- Only applies to oversubscribed India/China EB-1/2/3 series; others get persistence

Evaluation via `evaluate_model.py` generates a spaghetti chart with 4 lines: Actual, Persistence, VQS Ensemble (old dampened model), and Regime-Switched (new).

### Results

**Aggregate MAE across 6 oversubscribed series (2002–2026):**

| Horizon | Persistence MAE | VQS Ensemble MAE | RS Model MAE | RS vs Persistence |
|---------|----------------|-------------------|--------------|-------------------|
| 1-month | 41.5d | 47.8d | **41.0d** | **-0.5d** |
| 3-month | 122.5d | 130.7d | **118.3d** | **-4.2d** |
| 6-month | 228.3d | 240.0d | **224.4d** | **-3.9d** |

The RS model consistently outperforms persistence. The VQS Ensemble (dampened) is worse than persistence at all horizons.

**Per-series divergence count (RS ≠ persistence):**

| Series | 1m diverge | 3m diverge | 6m diverge | Notes |
|--------|-----------|-----------|-----------|-------|
| India EB-1 | 35/122 (29%) | 38/121 | 41/118 | Most active, biggest wins |
| China EB-1 | 29/122 (24%) | 32/121 | 35/118 | Same FY boundary pattern |
| China EB-2 | 6/122 (5%) | 17/121 | 29/118 | Moderate, mostly longer horizons |
| India EB-2 | 3/122 (2%) | 9/121 | 13/118 | Minimal divergence |
| India EB-3 | 2/122 (2%) | 6/121 | 9/118 | Minimal divergence |
| China EB-3 | 0/122 (0%) | 0/121 | 2/118 | Nearly zero divergence |

### Where the Improvement Comes From

Almost all improvement is concentrated in **EB-1 fiscal year boundary predictions** (India and China). The RS model correctly predicts the annual "current" jump:

**Top RS wins (>100d improvement over persistence):**

| Series | Month | Actual | Persist | RS | Persist err | RS err | Saved |
|--------|-------|--------|---------|-----|------------|--------|-------|
| China EB-1 | 2021-09 | 2021-09-01 | 2021-03-01 | **2021-09-01** | 184d | **0d** | 184d |
| India EB-1 | 2022-09 | 2022-09-01 | 2022-03-01 | **2022-09-01** | 184d | **0d** | 184d |
| China EB-1 | 2022-10 | 2022-10-01 | 2022-04-01 | **2022-10-01** | 183d | **0d** | 183d |
| India EB-1 | 2022-10 | 2022-10-01 | 2022-04-01 | **2022-10-01** | 183d | **0d** | 183d |
| China EB-1 | 2021-06 | 2021-06-01 | 2020-11-01 | 2021-05-02 | 212d | 30d | 182d |
| India EB-1 | 2019-05 | 2016-09-01 | 2015-06-15 | 2015-09-01 | 444d | 366d | 78d |

Pattern: EB-1 dates jump to "current" (near-present) at FY boundaries. Persistence lags 6 months behind; the regime classifier recognizes the advancing state and the expert predicts the jump. Many are **exact hits** (0-day error).

### Where the Model Hurts

Losses cluster in the same EB-1 series during **retrogression years** (FY2023) and **India EB-3 stalled periods**:

**Top RS losses (>100d regression vs persistence):**

| Series | Month | Actual | Persist | RS | Persist err | RS err | Cost |
|--------|-------|--------|---------|-----|------------|--------|------|
| India EB-3 | 2019-10 | 2010-02-01 | 2010-04-01 | 2011-07-13 | 59d | 527d | +468d |
| India EB-3 | 2019-07 | 2010-04-01 | 2010-04-01 | 2011-02-10 | 0d | 315d | +315d |
| China EB-2 | 2020-03 | 2016-08-01 | 2017-06-01 | 2017-12-04 | 304d | 490d | +186d |
| China EB-1 | 2024-09 | 2023-01-01 | 2023-01-01 | 2023-07-04 | 0d | 184d | +184d |
| China EB-1 | 2023-06 | 2022-06-01 | 2022-12-01 | 2023-06-01 | 183d | 365d | +182d |

Pattern: the model predicted another "current" jump but USCIS retrogressed instead. The regime classifier saw advancing movement and extrapolated, but a policy change reversed direction.

**Net across all >30-day divergences:** 135 big wins (13,646d saved) vs 70 big losses (8,539d added) = **+5,107d net improvement.** Positive but not overwhelming.

### Honest Assessment

1. **For EB-2 and EB-3 (what most users care about), the RS model is essentially persistence.** India EB-2 diverges 3 times in 122 months at 1-month horizon; China EB-3 diverges zero times. The advertised 0.5d MAE improvement at 1-month averages a handful of EB-1 wins across 6 series.

2. **The model is a one-trick pony** — it predicts EB-1 fiscal year boundary jumps. This is a real, valuable pattern (184-day wins with exact hits), but it's narrow.

3. **The trick fails when policy changes.** FY2023 EB-1 retrogressed instead of jumping. The model can't predict policy reversals, so when its one pattern fails, it fails catastrophically.

4. **At longer horizons (3m, 6m), improvement is slightly larger** (-4.2d, -3.9d) but still modest and concentrated in EB-1.

### Comparison: FY Boundary (Section 8) vs Regime-Switched (This Section)

| Aspect | FY Boundary Experiment | Regime-Switched Model |
|--------|----------------------|----------------------|
| Approach | Complex conditional model + aggressive param overrides | Simple expert selector, no dampening |
| Result | **Regressed** (+1.2d overall, +46.6d India EB-2) | **Small improvement** (-0.5d to -4.2d) |
| Why different | Noisy conditional model with 8 data points; 60% weight too high | No new model, just undampened expert selection |
| EB-1 wins | Some (but swamped by EB-2 regression) | Yes, concentrated and genuine |
| EB-2/3 impact | Worse (India EB-2 +46.6d) | Neutral (near-zero divergence) |
| Key lesson | Don't trust conditional models on <10 training points | Removing dampening helps for clear patterns, neutral elsewhere |

### Current Status

The RS model is implemented as `predict_regime_switched()` in `solver.py` and evaluated via the spaghetti chart (`spaghetti.html`) as a separate line (red, "Regime-Switched"). It is **not used in production predictions** — published `PredictedCutoff` rows still use the dampened VQS Ensemble.

### Lessons for Future Work

1. **The dampened ensemble is a dead end for beating persistence.** It was designed to be conservative, and it achieves that by being indistinguishable from persistence.

2. **The RS model proves the physics-based approach can beat persistence** — but only narrowly, and only for EB-1 FY boundaries.

3. **For EB-2/3, fundamentally new signals are needed.** Historical movement patterns alone can't predict policy-driven changes. Possible directions:
   - USCIS processing time data (leading indicator of demand shifts)
   - Congressional legislation tracking
   - DOS visa issuance actuals vs allocation (utilization rate)
   - Cross-series spillover signals (EB-1 unused visas flowing to EB-2)

4. **Consider shipping the RS model for EB-1 only** and persistence for everything else. This is honest and provides genuine value for EB-1 India/China applicants.

5. **The aggregate MAE numbers are misleading.** "41.0d vs 41.5d" sounds like a blanket improvement but is really "183d wins for EB-1 FY jumps averaged away across 6 series and 120 months." Report per-series, per-pattern metrics instead. **Addressed in Section 10.**

---

## 10. Granular Multi-Dimensional Metrics (March 2026)

### Motivation

Section 9 identified that aggregate MAE masks where models add value. A single number like "41.0d" averages together EB-1 FY boundary wins (183d saved) with EB-3 near-zero divergence. To understand model strengths and guide optimization, we need metrics broken down by regime, FY phase, movement magnitude, and series.

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| Stratified accuracy breakdown | `scripts/vqs/evaluate_model.py` | Per-data-point classification by regime (ADVANCING/STALLED/etc.), FY phase (FY_RESET/END_OF_FY/STEADY), and movement magnitude (big/medium/small/none). New panel in spaghetti chart with tabs for each breakdown. |
| Pace baseline | `scripts/vqs/evaluate_model.py` | Charlie Oppenheim's constant-pace heuristic: extrapolate at recent 6-month advancement rate. |
| Demand-supply baseline | `scripts/vqs/evaluate_model.py` | PhoenixCTB-style heuristic: demand (I-140 receipts) vs supply (FY cap). Currently uses hardcoded demand constants (not live I-140 DB data). |
| Per-series weighting | `lib/business/vqs/metric_config.py` | `DEFAULT_SERIES_WEIGHTS` for different visa classes/countries. `composite_weight()` method combining series, regime, and magnitude weighting. |
| Regime-conditioned loss | `lib/business/vqs/accuracy_metrics.py` | `compute_composite_metric` now uses `MetricConfig.composite_weight()` incorporating series, regime, and movement-magnitude dimensions. |
| Tuning integration | `scripts/vqs/tune_params.py` | New Optuna parameters: `fy_boundary_weight`, `steady_state_weight`, `move_magnitude_weight`. |
| Metric report page | `scripts/vqs/generate_metric_report.py` | Static HTML dashboard with series x regime heat map, FY-boundary vs steady-state comparison, and "where does model add value" summary. Served at `/metric-report/`. |
| Unit tests | `tests/test_vqs_metrics.py` | Tests for series weight, regime weight, magnitude weight, and composite weight logic. |

### Spaghetti Chart Changes

The spaghetti chart (`/spaghetti/`) now shows **6 models** instead of 4: Persistence, Dashboard, VQS Ensemble, Regime-Switched, Pace, and Demand-Supply. A new "Stratified Accuracy Breakdown" panel provides tabbed views by regime, FY phase, and movement size, showing MAE, direction accuracy, and win rate vs persistence for each stratum.

### Demand-Supply Baseline: I-140 Data Status

The demand-supply baseline in `evaluate_model.py` uses **hardcoded approximate demand constants** (`DEMAND_PER_DAY`) for its spaghetti chart line. However, the **production solver** (`solver.py`, `expert_pool.py`) uses real I-140 data from `raw_facts_ledger` via `build_virtual_queue_snapshot()` in `demand.py`.

**Ingested data:** 576 rows covering FY2014–FY2025 (4 countries × 3 categories × 4 quarters × 12 FYs). Downloaded from USCIS quarterly XLSX files using `scripts/vqs/download_uscis_i140.py`. Each XLSX contains per-country sheets with annual "Total Petitions" by preference, split across 4 quarters during ingestion.

**Parser fix (Mar 2026):** USCIS changed the header row position between FY2024 and FY2025 files. The parser now dynamically finds the header row instead of hardcoding row index 3.

**Current gaps:** FY2025 data is through Q3 only (Oct 2024–Jun 2025). FY2020–FY2023 individual quarterly URLs are no longer active on USCIS, but their data was captured via the cumulative XLSX files. No FY2026 data available yet.

### Current Status

- Spaghetti chart: regenerate with `bazel run //scripts/vqs:evaluate_model` to see all 6 models and stratified breakdowns
- Metric report: generate with `bazel run //scripts/vqs:generate_metric_report`, view at `/metric-report/`
- Composite loss: active in `tune_params.py` search space; run `bazel run //scripts/vqs:tune_params` to optimize
- I-140 data: fully ingested FY2014–FY2025 (576 rows); evaluate_model.py demand-supply baseline still uses hardcoded constants (solver uses real data)

---

## 11. Post-Tune Analysis (March 2026)

### Motivation

After Optuna tuning (trial #13) we updated default meta params, MetricConfig, and aggregator learning rate. This section records performance with the new settings, compares to baseline predictors on main dimensions, and states exactly which predictor to use and whether it accumulates all the goodness.

### What Was Measured

- **Multi-horizon composite** (filing, horizons 1–3–6–12): composite MAE 307.4 days; per-horizon MAE 33.5 (1m), 121.1 (3m), 232.3 (6m), 414.3 (12m). Trend accuracy 48.4%. Uses `compute_prediction_accuracy --metric composite --learning-rate 4.58`.
- **Spaghetti evaluation** (evaluate_model): 6 models × 6 series × 3 horizons (1m, 3m, 6m). Aggregate MAE and win rate vs persistence below.
- **Expert backtest** (backtest_experts --spaghetti-kd): demand_signal beats persistence on aggregate (32.1d vs 40.1d); regime-wise, demand_signal wins in advancing/volatile, persistence in retrogressing/recovering.

### Comparison to Baseline Predictors (Main Dimensions)

All numbers are **aggregate over 6 series** (India/China × EB-1/2/3), filing action, from `evaluate_model` (spaghetti) with tuned defaults.

| Model | 1m MAE (d) | 3m MAE (d) | 6m MAE (d) | 1m Dir Acc | 3m Dir Acc | 6m Dir Acc | Beats persistence (series) |
|-------|------------|------------|------------|------------|------------|------------|----------------------------|
| **Persistence** | 41.5 | 122.5 | 228.3 | — | 3.9% | 8.6% | — |
| **Dashboard** | 52.1 | 138.6 | 255.4 | 77.7% | 60.8% | 54.6% | 0/6, 0/6, 0/6 |
| **VQS Ensemble** | **41.4** | 123.3 | 231.4 | 47.9% | 19.5% | 25.2% | 2/6, 2/5, **4/6** |
| **Regime-Switched** | **40.9** | **118.3** | **224.4** | 17.8% | 16.8% | 15.7% | **3/5**, **4/5**, 3/6 |
| **Pace** | 46.5 | 121.1 | **211.1** | 91.1% | 52.5% | 37.2% | 0/6, 3/6, **6/6** |
| **Demand-Supply** | 56.4 | 140.0 | 239.5 | 91.1% | 71.9% | 68.5% | 0/6, 1/6, 3/6 |

**Takeaways:**

- **1m:** VQS Ensemble is effectively tied with Persistence (41.4 vs 41.5). Regime-Switched has the best average MAE (40.9) and wins 3/5 series.
- **3m:** Regime-Switched has best MAE (118.3) and best win rate vs persistence (4/5). VQS and Pace are close to persistence.
- **6m:** Pace has best MAE (211.1) and beats persistence on all 6 series. Regime-Switched next (224.4). VQS Ensemble beats persistence on 4/6 series but slightly worse average MAE than persistence (231.4 vs 228.3).
- **Dashboard** is worse than persistence at all horizons (no-change baseline is strong).
- **Direction accuracy** is high for Pace and Demand-Supply (they move with trend) but that does not imply lower MAE; Persistence has N/A by definition.

### Composite Metric (Weighted Multi-Horizon)

With tuned settings (meta + aggregator LR 4.58), `compute_prediction_accuracy --metric composite` reports:

- **Composite MAE:** 307.4 days (horizon weights in that run are proportional, not the Optuna-tuned weights; Optuna best was 321.4 with tuned weights).
- **Per horizon:** 1m 33.5d, 3m 121.1d, 6m 232.3d, 12m 414.3d.

So the tuned ensemble improves the **composite** objective used in tuning; on simple average MAE across series it remains close to persistence at 1m and is slightly worse at 3m/6m.

### Exact Predictor to Use

**Use the VQS Ensemble.** It is the single production path that includes all tuned goodness:

| Component | Where it lives | What it does |
|-----------|----------------|--------------|
| Meta params | `VqsMetaParams.defaults()` in `meta_params.py` | Stickiness, caps, blend, ensemble persistence weight, trajectory blend/decay (all set from Optuna trial #13) |
| Aggregator | `ExpertAggregator()` in `aggregator.py` | Hedge over experts; default `learning_rate=4.58`, `MetricConfig.defaults()` for warmup and loss |
| Solver entry | `predict_next_bulletin_and_maturity(..., meta=..., aggregator=...)` in `solver.py` | Uses ensemble (not force_physics); applies meta for post-step shaping |

**Invocation:**

- **Publishing predictions:** `scripts/publish_predictions.py` — calls `predict_next_bulletin_and_maturity(knowledge_date=..., visa_class=..., country=..., action_type=..., facts=..., meta=VqsMetaParams.defaults(), aggregator=ExpertAggregator())`. No extra args; defaults are the tuned values.
- **Ad-hoc / API:** Same: pass no `meta` and no `aggregator` (solver uses `VqsMetaParams.defaults()` and `ExpertAggregator()` internally when omitted).

So the **exact predictor** is: run the solver with **default meta and default aggregator**; that path is what `publish_predictions` uses and what should be used for any single “official” VQS prediction.

### Does It Accumulate All the Goodness?

**Yes, for the ensemble path.** The tuned meta (stickiness, caps, blend_lambda, ensemble_persistence_weight, ensemble_trajectory_*, etc.) and the tuned aggregator (learning rate, MetricConfig for horizon/regime/magnitude weights) are all in the defaults. So one call to `predict_next_bulletin_and_maturity` with defaults gets:

- Tuned post-step shaping (less over-dampening than pre-tune)
- Tuned Hedge learning rate and metric-driven warmup
- All experts (persistence, seasonal_median, linear_extrap, momentum_3m, fy_reset, demand_signal) weighted by the aggregator

**What is not in that single predictor:**

- **Regime-Switched** and **Pace** are separate models. They are not merged into the ensemble. Regime-Switched has better 1m/3m average MAE; Pace has best 6m MAE. If you want “all” goodness in one number you would have to define a hybrid (e.g. use Regime-Switched for 1m and Pace for 6m, or blend them with the ensemble). That is not implemented; the **single** predictor we use is the **VQS Ensemble** only.
- **Stored vs live:** For past months, the predictions table may show stored `PredictedCutoff` rows (from an earlier publish run). For future months, the same solver with defaults produces the prediction. So “the predictor” is the same; only the source of the number (DB vs live run) differs by month.

### Current Status

- Defaults in code reflect Optuna trial #13 (meta, MetricConfig, aggregator LR).
- Spaghetti chart and metric report regenerated with new settings; view at `/spaghetti/` and `/metric-report/`.
- **Recommendation:** Use the VQS Ensemble (default solver + default aggregator) as the single production predictor. It accumulates the full tuned setup. For analysis, compare to Regime-Switched and Pace via the spaghetti chart when considering per-horizon tradeoffs.

### Is VQS Helpful for Beating Persistence on EB-2/3 India/China?

**Short answer: no.** For the goal of meaningfully beating persistence on the important series (EB-2 and EB-3 for India and China), the current VQS Ensemble is **not** helpful:

- **Aggregate:** VQS Ensemble is effectively tied with persistence at 1m (41.4 vs 41.5d) and slightly worse at 3m/6m on average MAE. It beats persistence on 2/6 series at 1m, 4/6 at 6m — but the wins are diluted by EB-1 and by series where it loses.
- **EB-2/3 specifically (Section 9):** Regime-Switched “is essentially persistence” for EB-2/3: India EB-2 diverges only 3 times in 122 months at 1m; China EB-3 zero times. The ensemble uses the same experts and is dampened, so it does not meaningfully outperform persistence on these series either.
- **Where value is:** Improvement is concentrated in **EB-1 FY boundary** predictions (Regime-Switched, and to a lesser extent the ensemble when it diverges). For EB-2/3 India/China, historical movement patterns in the current model set do not add consistent edge.

So for the stated goal — meaningfully beat persistence on EB-2/3 India/China — **VQS as currently used is not the answer**. Persistence is a very strong baseline; the ensemble does not reliably beat it on those series.

### How Can We Use Regime-Switched / Pace / Demand-Supply?

These are **separate** models from the published VQS Ensemble. To get real benefit on important series, we have to use them explicitly (hybrid or selector), not rely on the single ensemble.

| Model | Strength | How to use it |
|-------|----------|----------------|
| **Regime-Switched** | Best 1m/3m average MAE; wins vs persistence mainly on **EB-1** (FY boundary jumps). Neutral for EB-2/3. | **Ship for EB-1 only:** use `predict_regime_switched()` for India/China EB-1; keep persistence (or ensemble) for EB-2/3. Honest and adds value where the model actually wins. |
| **Pace** | Best 6m MAE (211d); beats persistence on **all 6 series** at 6m. Weaker at 1m. | **Use for longer horizons:** for 6m (and optionally 12m) forecasts, use Pace instead of persistence or ensemble. Could be a “6-month outlook” line in the UI while 1m stays persistence. |
| **Demand-Supply (demand_signal expert)** | In expert backtest, **demand_signal beats persistence** on India EB-2 (13.2d vs 31.7d), India EB-3 (27.5d vs 46.9d), China EB-2 (28.1d vs 33.4d), and on aggregate (32.1d vs 40.1d). Wins in advancing/volatile regimes. | **Regime-based selector for EB-2/3:** for (visa_class, country) in {EB-2 India, EB-3 India, EB-2 China}, if regime is ADVANCING or VOLATILE, predict with demand_signal (or a small ensemble weighted toward demand_signal); otherwise use persistence. This would require a thin wrapper that calls the solver’s expert pool or the demand model and selects by regime (from `classify_regime()`). |

**Concrete implementation options:**

1. **Hybrid by (series, horizon)**  
   - 1m: Regime-Switched for EB-1 India/China; persistence for EB-2/3.  
   - 3m: Regime-Switched or persistence (RS slightly better on average).  
   - 6m: **Pace** for all series (or at least EB-2/3 India/China).  
   Single “predictor” becomes a small router: `if series in EB1 and horizon <= 3: use RS; elif horizon >= 6: use Pace; else: use persistence` (and optionally blend).

2. **Regime-based expert for EB-2/3**  
   - Use `backtest_experts`-style logic in production: for EB-2/3 India/China, classify regime; if advancing/volatile, return demand_signal expert’s prediction; else return persistence.  
   - Requires exposing demand_signal (and optionally other experts) from the solver/aggregator and calling `classify_regime()` at prediction time.

3. **Ship RS for EB-1, persistence for EB-2/3 (minimal change)**  
   - No hybrid: EB-1 India/China use Regime-Switched; everything else uses persistence.  
   - Beats persistence only on EB-1; EB-2/3 stay at persistence until we add a dedicated signal (e.g. demand_signal selector above).

4. **Enrich the ensemble for EB-2/3**  
   - The ensemble already includes demand_signal; it’s dampened by stickiness and persistence weight. Options: (a) lower persistence weight or stickiness for EB-2/3 when regime is advancing/volatile, or (b) add a “EB-2/3 selector” that overrides ensemble with demand_signal when regime favors it. Both need regime-conditioned logic in the solver or in a wrapper.

**Recommendation:** For “meaningfully beat persistence on EB-2/3 India/China,” the only model that has shown clear wins on those series is **demand_signal** in the expert backtest. So either: (i) implement a **regime-based selector** that uses demand_signal for EB-2/3 India/China in advancing/volatile regimes and persistence otherwise, or (ii) add **Pace for 6m** so at least the 6-month view beats persistence on those series. Using Regime-Switched alone does not fix EB-2/3; it only helps EB-1.

---

## 13. Cross-Series Spillover and UI Enhancements (Mar 2026)

### Motivation

After the FY Boundary Experiment (Sec. 8) failed and the Regime-Switched model (Sec. 9) showed only marginal overall improvement (+2% on EB-1), the focus shifted to:
1. Adding cross-series EB-1→EB-2/3 spillover signal to improve expert quality.
2. Surfacing richer uncertainty information (CI, regime) in the user-facing predictions UI.
3. Reducing the systematic 72% under-prediction bias through supply model rebalancing.

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| Multi-step cross-series trajectory | `expert_pool.py` | `trajectory_cross_series` blends 20% EB-1 avg movement into seasonal-median predictions for oversubscribed EB-2/3 (India/China only) |
| EB-1 regime in context key | `contextual_aggregator.py` | `_get_context_key` includes EB-1 regime state for EB-2/3 series, allowing aggregator to learn different weights based on EB-1 behavior |
| Cross-series GBM features | `gbm_expert.py` | Added `eb1_move_1m`, `eb1_move_3m`, `eb1_regime_enc` features to FEATURE_NAMES (16 total features) |
| Ablation support | `prediction_loader.py`, `evaluate_model.py` | `build_solver_cache_ablated` + `--ablate` flag to measure isolated cross-series contribution |
| CI display on predictions UI | `prediction_views.py`, `prediction_detail.html` | `confidence_low`/`confidence_high` from stored PredictedCutoff now rendered as date range tooltip + inline text |
| Regime badge on predictions UI | `prediction_views.py`, `prediction_detail.html` | Regime extracted from `explanation_markdown` via regex; colored badge shown per cell |
| EB-4 Experimental badge | `prediction_detail.html` | EB-4 rows muted with `Experimental` badge (limited data, lower accuracy) |
| Spillover bonus rate increased | `estimators.py`, `meta_params.py` | `SPILLOVER_BONUS_RATE` 0.15 → 0.20; early-FY seasonal multipliers increased (Oct–Feb: +0.05 each) |
| Real I-140 demand in evaluate_model | `evaluate_model.py` | `_get_i140_demand_per_day` queries RawFactsLedger and scales baseline by I-140 trend ratio; capped [0.5×, 2.0×] |
| Published April 2026 predictions | DB | 70 PredictedCutoff rows for 2026-04-01 with CI and explanation_markdown |

### Results (Mar 2026 Evaluation — --quick mode, 6 series × 3 horizons)

**1-month horizon (all 6 series)**:

| Model | MAE (days) | Dir Acc % |
|-------|-----------|----------|
| Persistence | 87.3 | 50.7% |
| VQS Ensemble | 87.6 | 60.8% |
| Regime-Switched | 86.4 | 53.7% |
| Contextual Ensemble | 87.8 | 85.1% |
| Hybrid | 86.6 | 62.2% |

**3-month horizon aggregate**:

| Model | MAE | 
|-------|-----|
| Persistence | 125.3 |
| Regime-Switched | 121.1 |
| Contextual Ensemble | 121.1 |
| Hybrid | — |

**6-month horizon aggregate**:

| Model | MAE | Dir Acc % |
|-------|-----|-----------|
| Persistence | 231.7 | 10.2% |
| Regime-Switched | 228.3 | 20.1% |
| Contextual Ensemble | 219.9 | 49.6% |
| Hybrid | 212.2 | 54.5% |
| Pace | 214.2 | 58.3% |

### Why It Worked / Failed

1. **Cross-series experts (contextual ensemble)** improved 6-month directional accuracy significantly (49.6% vs 10.2% for persistence), validating the EB-1 regime signal.
2. **At 1-month horizon, all models remain near persistence MAE** — the 1-step problem is dominated by noise, not by cross-series signal. The value emerges at 3–6 months.
3. **Regime-Switched wins on EB-1** at 3m and 6m but struggles on EB-2/3 (too conservative). The new Contextual Ensemble outperforms it at 6m.
4. **Hybrid (1m: Regime-Switched for EB-1, Contextual for EB-2/3) achieves best 6m MAE** (212 days vs 232 for persistence).

### Lessons and Next Steps

1. Re-tune `ensemble_persistence_weight` with Optuna using the new cross-series-aware model; the current 0.797 was tuned before these features existed.
2. The supply model rebalancing (spillover 0.15→0.20, seasonal multipliers) needs a full evaluation run to verify the under-prediction rate improved toward 50%.
3. EB-4 should remain marked Experimental until more data is available.
4. C4 (stretch): Show expert predictions breakdown per cell — the `expert_predictions` JSON field is already stored; only needs a UI collapsed view.

### Current Status

- Cross-series: **Live** (trajectory_cross_series, contextual aggregator EB-1 context, GBM features)
- UI: **Live** (CI display, regime badges, EB-4 Experimental, confidence level derivation)
- Supply rebalancing: **Live** (not yet re-evaluated with full Optuna run)
- Optuna re-tuning: **Pending** (to be done after production predictions settle)

---

## 12. Appendix: File Inventory

### Active Production Files (Deployed Linear Projection)

| File | Purpose | Used By |
|------|---------|---------|
| `lib/business/bulletin/cutoff_projection.py` | Primary projection logic | `cutoff_data_aggregator.py`, `test_projection.py` |
| `lib/business/bulletin/cutoff_data_aggregator.py` | Dashboard data aggregation | `webapp/views/bulletin/dashboard.py` |
| `lib/business/bulletin/chart_builder.py` | Chart building with projections | `webapp/views/bulletin/dashboard.py` |
| `tests/test_projection.py` | Projection unit tests | CI |

### VQS System (Live)

| File | Purpose |
|------|---------|
| `lib/business/vqs/solver.py` | Queue simulation engine |
| `lib/business/vqs/demand.py` | Demand model (I-140 + PERM lag) |
| `lib/business/vqs/supply/` | Supply allocation (per-class, seasonal, spillover) |
| `lib/business/vqs/accuracy_metrics.py` | Accuracy computation with checkpointing |
| `lib/business/vqs/expert_pool.py` | Multi-model ensemble |
| `lib/business/vqs/seasonal_predictor.py` | Seasonal pattern detection |
| `lib/business/vqs/regime.py` | Regime classification (ADVANCING/STALLED/etc.) |
| `lib/business/vqs/prediction_loader.py` | Stored prediction loading + solver cache builders |
| `scripts/vqs/evaluate_model.py` | Spaghetti chart generator (8-model comparison with stratified breakdowns, ablation support) |
| `scripts/vqs/backtest_experts.py` | Per-expert backtest for RS model expert selection |
| `scripts/vqs/generate_metric_report.py` | Static HTML metric dashboard (series x regime heat map, FY comparison) |
| `scripts/vqs/*.py` | VQS scripts (ingest, simulate, backtest, accuracy, tuning) |
| `scripts/bulletin/backtest_projections.py` | Linear projection backtester |
| `models/raw_facts.py` | Bi-temporal data model for VQS |
| `webapp/views/prediction_views.py` | Prediction views (live at /predictions/) |
| `webapp/views/bulletin/vqs_api.py` | VQS API endpoint (live at /api/vqs/predict/) |

### Legacy Files

_All legacy files (`lib/projection.py`, `lib/dashboard_service.py`, `lib/chart_builder.py`, `webapp/views.py`) were deleted in Phase 0. No legacy files remain._
### Documentation

| File | Content |
|------|---------|
| `docs/PREDICTIONS_ASSESSMENT.md` | This file — research log and overall assessment |
| `docs/future_features/VQS_RUNBOOK.md` | Operational runbook for VQS |
| `docs/future_features/VQS_NEW_SUGGESTIONS.md` | Active improvement ideas and unexplored approaches |
| `docs/future_features/VQS_META_PARAMS_AND_TUNING.md` | Meta-parameter design, tuning strategy, and critique |
| `docs/future_features/VQS_FAMILY_EXTENSION_DESIGN.md` | Family-based VQS design (not implemented) |
| `lib/business/vqs/README.md` | Code-level documentation |
