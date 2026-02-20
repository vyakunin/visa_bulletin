# VQS (Virtual Queue Simulation)

Deterministic queue-based simulation for predicting Visa Bulletin movements and Green Card maturity dates. ML is limited to estimating hidden parameters (demand de-aggregation, attrition, supply).

## Components

- **queue_snapshot.py** – `VirtualQueueSnapshot`: histogram of applicants by priority date (month). Methods: `add()`, `get_demand_between()`, `advance_cutoff()`.
- **demand.py** – Model A: builds queue from raw facts. Phase 1 (naive): fixed 12-month lag. Phase 2: convolution using PERM lag distribution when present (metric `perm_lag_distribution`); fallback to naive when missing. `build_virtual_queue_snapshot(knowledge_date, facts, visa_class, country)`.
- **solver.py** – Simulation engine: loads state at knowledge date, runs monthly loop with constant supply. Optional Phase 3: attrition (λ) and supply_fn (Model C). `predict_next_bulletin_and_maturity()` returns next cutoff and maturity month.
- **accuracy_metrics.py** – Prediction accuracy: (1) bulletin-by-bulletin: predict every cutoff as-of day-before-publication, compare to actual, aggregate mean error over bulletin date; (2) long-term “final ready date”: per month and (visa_class, country), predict when next cutoff appears, compare to first bulletin where it was reached.
- **estimators.py** – Model B (attrition λ) and Model C (supply) stubs; configurable constants for Phase 3.

## Data

- **raw_facts_ledger** (models/raw_facts.py): append-only bi-temporal store. `publication_date` = knowledge time; `reference_period_*` = event time. Used for backtesting. Metrics: `i140_receipts`, `perm_lag_distribution`.

## Scripts

- **scripts/vqs/ingest_uscis_i140.py** – Ingest USCIS I-140 receipts into ledger (`--stub` or `--file PATH`).
- **scripts/vqs/compute_perm_lag.py** – Compute PERM lag histogram from SalaryRecord and write to ledger (Phase 2).
- **scripts/vqs/run_simulation.py** – Run simulation: `--knowledge-date`, `--visa-class`, `--country`, `--priority-date`, etc.
- **scripts/vqs/run_backtest.py** – Backtest: `--reference-dates`, `--horizons 1 3 6`; outputs Bulletin MAE (days).
- **scripts/vqs/compute_prediction_accuracy.py** – Compute bulletin and long-term accuracy metrics; optional Plotly plots with drill-down by visa class and country.

## How to Improve Accuracy

1. **Add I-140 data** – Ingest all available USCIS I-140 quarterly reports (FY2020–FY2025+) via `scripts/vqs/ingest_uscis_i140.py` with correct `--publication-date`. More history improves queue depth and backtesting.
2. **Tune constants** – In `estimators.py`: per-class share, `FY_SEASONAL_MULTIPLIER`, `SPILLOVER_BONUS_RATE`, EB1 bonus. In `solver.py`: `_RETROGRESSING_SERIES` (fallback when history has few Sept/Oct transitions).
3. **Re-run accuracy** – After changes, clear checkpoint and run `bazel run //scripts/vqs:compute_prediction_accuracy -- --metric both --output-dir /tmp/vqs_accuracy --checkpoint-dir /tmp/vqs_ckpt`. Compare `bulletin_accuracy.json` (mean error, over/under rate) and `longterm_accuracy_summary.json` (by horizon and series).

See **docs/future_features/VQS_RUNBOOK.md** for step-by-step “add I-140 file” and “re-run accuracy” commands.

## References

- docs/future_features/SMART_PREDICTIONS_VQS_PROPOSAL.md
- docs/future_features/VQS_NEW_SUGGESTIONS.md
- docs/future_features/VQS_RUNBOOK.md
