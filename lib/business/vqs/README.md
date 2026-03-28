# VQS (Virtual Queue Simulation)

Deterministic queue-based simulation for predicting Visa Bulletin movements and Green Card maturity dates. ML is limited to estimating hidden parameters (demand de-aggregation, attrition, supply).

## Components

- **queue_snapshot.py** – `VirtualQueueSnapshot`: histogram of applicants by priority date (month). Methods: `add()`, `get_demand_between()`, `advance_cutoff()`.
- **demand.py** – Model A: builds queue from raw facts. Phase 1 (naive): fixed 12-month lag. Phase 2: convolution using PERM lag distribution when present (metric `perm_lag_distribution`); fallback to naive when missing. `build_virtual_queue_snapshot(knowledge_date, facts, visa_class, country)`.
- **solver.py** – Simulation engine: loads state at knowledge date, runs monthly loop with constant supply. Optional Phase 3: attrition (λ) and supply_fn (Model C). `predict_next_bulletin_and_maturity()` returns next cutoff and maturity month.
- **accuracy_metrics.py** – Prediction accuracy: (1) bulletin-by-bulletin: predict every cutoff as-of day-before-publication, compare to actual, aggregate mean error over bulletin date; (2) long-term "final ready date": per month and (visa_class, country), predict when next cutoff appears, compare to first bulletin where it was reached.
- **estimators.py** – Model B (attrition λ) and Model C (supply) stubs; configurable constants for Phase 3.
- **regime.py** – Regime classification (`ADVANCING`, `STALLED`, `RETROGRESSING`, `RECOVERING`, `VOLATILE`). Also contains FY-phase-aware regime detection (`FYPhase` enum, `classify_regime_fy_aware()`), FY-aware persistence/cap/stickiness overrides. FY-aware mode gated behind `fy_boundary_aware` flag — **currently disabled** (backtesting showed regression).
- **fy_transition_model.py** – Conditional FY transition predictor (Tier 2). Nearest-neighbor on historical FY transitions using utilization rate, backlog depth, cross-series signals. **Experimental, not enabled by default.**
- **fy_utilization.py** – FY utilization tracking from DOS issuance data. Cumulative issuance, utilization rate, backlog depth, historical FY transition collection.
- **prediction_loader.py** – Shared prediction loading for spaghetti chart and predictions table. Builds solver cache, loads stored predictions from DB.
- **metric_config.py** – Configuration for composite accuracy metrics: per-series weights, regime-conditioned loss, FY-boundary vs steady-state weighting, movement-magnitude weighting. Used by `accuracy_metrics.py` and `tune_params.py`.
- **regime.py** also provides `FYPhase` classification (`FY_RESET`, `END_OF_FY`, `STEADY`) for stratified evaluation.
- **calibration.py** – Calibrated prediction intervals. Builds signed error distributions from stored predictions and historical backtest by (series, regime, horizon). `compute_calibrated_interval()` returns (lower, upper) dates for ~80% coverage. Used by `publish_predictions.py` to replace ad-hoc expert-disagreement CI with data-driven intervals.
- **gbm_expert.py** – LightGBM gradient-boosted tree expert. Trained on pooled (series, month) feature vectors: 27 features (indices 0-26) including recent movements, I-140 demand ratio, I-485 queue depth, demand-drop signals (ROW velocity + issuance drop), queue density near cutoff, cross-series EB-1 signal, seasonal, and FY features. Walk-forward training: model retrained each month using all history to that point. Falls back to seasonal_median if lightgbm unavailable or insufficient data (<36 samples). PERM filing ratio feature was removed (March 2026) — zero contribution confirmed by §20 ablation. PERM data still used in `demand.py` virtual queue model.
- **predictors.py** – Typed predictor protocol and implementations: `PersistencePredictor`, `PacePredictor`, `DemandSupplyPredictor`, `RegimeSwitchedPredictor`, `HybridPredictor`. Used by `evaluate_model.py` and `ContextualTrajectoryAggregator`. `HybridPredictor` dispatches by series and horizon: EB-1 → RS, EB-2/3 at 6m+ → Pace, else → VQS.
- **meta_params.py** – `VqsMetaParams` dataclass with all solver tuning parameters. `VqsMetaParams.defaults()` returns Optuna trial #13 tuned values. Parameters: stickiness, caps, blend_lambda, ensemble_persistence_weight, trajectory_blend/decay, fy_boundary_aware flag.
- **reporting.py** – Report generation utilities used by scripts. Formats accuracy results, per-series breakdowns, and comparison tables.
- **contextual_aggregator.py** – `ContextualTrajectoryAggregator`: online Hedge over Persistence/Pace/DemandSupply/RegimeSwitched with Softmax blending. Context key includes (visa_class, country, horizon, regime, eb1_regime). Used in `evaluate_model.py` as "Contextual Ensemble" model.

## Supply Submodule (`supply/`)

- **supply/allocator.py** – `SupplyAllocator`: computes monthly visa supply per (visa_class, country, month) with per-class shares, FY seasonal multipliers, and spillover bonuses. Main entry: `get_supply(visa_class, country, target_month, knowledge_date)`.
- **supply/country_cap.py** – Per-country cap logic and priority ordering for visa allocation.
- **supply/fb_spillover.py** – Family-Based to Employment-Based spillover allocation (unused EB cap rolls forward).

## Data

- **raw_facts_ledger** (models/raw_facts.py): append-only bi-temporal store. `publication_date` = knowledge time; `reference_period_*` = event time. Used for backtesting. Metrics: `i140_receipts`, `perm_lag_distribution`, `i485_pending_inventory_monthly`.

## Scripts

- **scripts/vqs/ingest_uscis_i140.py** – Ingest USCIS I-140 receipts into ledger (`--stub` or `--file PATH`).
- **scripts/vqs/compute_perm_lag.py** – Compute PERM lag histogram from SalaryRecord and write to ledger (Phase 2).
- **scripts/vqs/run_simulation.py** – Run simulation: `--knowledge-date`, `--visa-class`, `--country`, `--priority-date`, etc.
- **scripts/vqs/run_backtest.py** – Backtest: `--reference-dates`, `--horizons 1 3 6`; outputs Bulletin MAE (days).
- **scripts/vqs/compute_prediction_accuracy.py** – Compute bulletin and long-term accuracy metrics; optional Plotly plots with drill-down by visa class and country.
- **scripts/vqs/evaluate_model.py** – Generate spaghetti chart comparing 8 models (Persistence, Dashboard, VQS Ensemble, Regime-Switched, Pace, Demand-Supply, Contextual Ensemble, Hybrid). Includes stratified accuracy breakdown by regime, FY phase, and movement magnitude. Writes `webapp/templates/spaghetti.html`. Use `--ablate` to also show "VQS No Cross-Series" for cross-series contribution measurement.
- **scripts/vqs/generate_metric_report.py** – Generate static HTML metric dashboard with series x regime heat map, FY-boundary vs steady-state comparison, and model value summary. Served at `/metric-report/`.
- **scripts/vqs/backtest_fy_boundary.py** – A/B comparison: solver with and without `fy_boundary_aware` for September knowledge dates.
- **scripts/vqs/analyze_fy_transitions.py** – Analyze historical FY transition patterns (Oct jumps, Sep retrogression).
- **scripts/vqs/tune_params.py** – Parameter tuning for meta-parameters.
- **scripts/publish_predictions.py** – Publish VQS predictions to DB (`PredictedBulletin`/`PredictedCutoff`). Supports single-month and backfill modes. Uses hybrid dispatch: regime-switched for EB-1 (India/China), VQS ensemble for EB-2/3. Calibrated 80% CI via `calibration.py`.

## Current Accuracy Status (Mar 2026)

- **I-140 data**: FY2014–FY2025 complete in `raw_facts_ledger` (576 rows, 12 series × 4Q × 12 years)
- **Supply rebalancing**: `SPILLOVER_BONUS_RATE` 0.15→0.20, early-FY seasonal multipliers +0.05. **Result**: 2025+ under-prediction rate 42% (down from 72%)
- **EB-1 India lookback**: 24m→36m (smoother advancement rate estimate, less noise from recent stalls)
- **Historical retrogression**: `get_retrogression_months_from_history()` queries VisaCutoffDate, `_RETROGRESSING_SERIES` is fallback only
- **ContextualAggregator defaults**: Updated to Optuna trial #5 best (learning_rate=3.5, blend_temperature=0.029, use_regime_context=False)
- **Published predictions**: April 2026 (70 rows) with calibrated 80% CI and regime/explanation

## How to Improve Accuracy

1. **Tune VqsMetaParams** – Run 50–100 Optuna trials targeting `ensemble_persistence_weight`, `ensemble_trajectory_blend/decay`, `stickiness_stall_days`. The current 0.797 was tuned before cross-series experts existed.
2. **Re-run accuracy** – After changes, clear checkpoint and run `bazel run //scripts/vqs:compute_prediction_accuracy -- --metric both --output-dir /tmp/vqs_accuracy --checkpoint-dir /tmp/vqs_ckpt`. Compare `bulletin_accuracy.json` (mean error, over/under rate) and `longterm_accuracy_summary.json` (by horizon and series).
3. **Spaghetti/metric report** – Regenerate after any model change: `./bazel-bin/scripts/vqs/evaluate_model --quick`.

See **docs/future_features/VQS_RUNBOOK.md** for step-by-step "add I-140 file" and "re-run accuracy" commands.

## FY Boundary Experiment (Feb 2026)

A two-tier architecture was implemented to fix FY boundary signal suppression. Gated behind `fy_boundary_aware=True` in `predict_next_bulletin_and_maturity()`. **Result: model regressed** (recent MAE +2.7d, India EB-2 long-term +46.6d). Root causes: insufficient training data for conditional model (~8 transitions/series), 60/40 Tier2/Tier1 blending too aggressive, persistence override too extreme (0.05). Flag defaults to `False`. See `docs/PREDICTIONS_ASSESSMENT.md` §8 for full analysis and next-step recommendations.

## Architecture Overview (Rule-Critical)

- **Predictions table** (`/predictions/employment_based/YYYY-MM/`): shows `PredictedBulletin` / `PredictedCutoff` stored in DB — these are what was actually served to users at prediction time.
- **Spaghetti chart** (`/spaghetti/`): generated by `scripts/vqs/evaluate_model.py` → writes `webapp/templates/spaghetti.html`. Contains baked-in JSON for 8 models across multiple horizons, plus stratified accuracy breakdowns.
- **PredictedBulletin** (`models/vqs.py`): one row per target month. Associated `PredictedCutoff` rows hold per-series predictions. Coverage: Jan 2024 → present.

## Per-Series Dispatch Table

Updated §20 same-window eval (from `scripts/publish_predictions.py`):

| Series | Horizon | Predictor | MAE |
|---|---|---|---|
| China EB-1 | <12m | `predict_regime_switched()` | 155.7d at 6m |
| China EB-1 | ≥12m | `expert_gbm_gated()` | 257d at 12m |
| India EB-1 | 1m/3m | `predict_regime_switched()` | — |
| India EB-1 | 6m+ | `expert_gbm_gated()` | 233d at 6m, 370d at 12m |
| China EB-3 | 6m+ | `expert_gbm_gated()` | 159d at 6m, 224d at 12m |
| China EB-2 | 6m | `expert_oppenheim_pace()` | 155d |
| China EB-2 | 12m | `expert_gbm_gated()` | 231d |
| India EB-2 | 6m | `expert_oppenheim_pace()` | 211d |
| India EB-2 | 12m | `expert_gbm_gated()` | 303d |
| India EB-3 | 6m/12m | `expert_oppenheim_pace()` | 264d / 491d |
| All others | any | VQS ensemble | — |

Notes:
- **1m GBM is NOT used as a point predictor** — structurally unsafe (MAE 2.3× worse). Signal surfaced only as P(movement) badge.
- Demand-drop masking for India EB-3 (features 22-25 zeroed at inference) remains.

## Key Constants in evaluate_model.py

| Constant | Value | Notes |
|---|---|---|
| `ACTION_TYPE` | `"filing"` | Only filing dates evaluated (not final_action) |
| `SERIES` | 6 series | India/China × EB-1/EB-2/EB-3 |
| `MODELS` | 8 models | Persistence, Dashboard, VQS Ensemble, Regime-Switched, Pace, Demand-Supply, Contextual Ensemble, Hybrid |
| `DEFAULT_HORIZONS` | `[1, 3, 6]` | Months ahead; stored predictions cover only 1m |
| `ERR_START` (in HTML) | `2017-07-01` | Cumulative error computed from this date onward |

**Country enum values** (used in `PredictedCutoff.country`): ALL=1, CHINA=2, INDIA=3, MEXICO=4, PHILIPPINES=5.

## References

- docs/PREDICTIONS_ASSESSMENT.md — Research log (experiments, results, lessons)
- docs/future_features/VQS_NEW_SUGGESTIONS.md — Active improvement ideas
- docs/future_features/VQS_RUNBOOK.md — Operational runbook
- docs/future_features/VQS_META_PARAMS_AND_TUNING.md — Meta-parameter design and tuning
