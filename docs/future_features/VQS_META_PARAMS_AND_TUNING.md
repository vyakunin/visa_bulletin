# VQS Meta-Parameters and ML Tuning

Design for a single holder of VQS meta-parameters and a clean API to tune them on bulletin-accuracy data (minimize prediction error) and to evaluate any parameter set.

---

## 1. Meta-Parameter Family

All tunable knobs are grouped into one **VqsMetaParams** holder. They fall into three categories.

### 1.1 Post-step (Protection & Control)

These act on the raw solver output before returning a predicted cutoff. They implement “beat no change” behavior and dampening.

> [!WARNING]
> **Overfitting Risk**: "Shaping" parameters like stickiness and caps can mask underlying model deficiencies. Over-reliance on them turns the solver into a "current + slight epsilon" predictor. They must be tuned *after* the physical parameters are optimized (see §3 Tuning Strategy).

| Parameter | Type | Default | Description | Valid Range |
|-----------|------|---------|-------------|-------------|
| **stickiness_days** | int | 30 | If raw first-month move ≤ this (in days), predict **no change** (current cutoff). 0 = always use raw. | [0, 60] (function of queue depth?) |
| **cap_forward_days** | int | 90 | Max allowed forward movement (days) in one bulletin step. Raw advance is clamped. | [60, 180], or None (Infinite) |
| **cap_back_days** | int | 60 | Max allowed backward movement (days) in one step (retrogression). | [30, 90] |
| **blend_lambda** | float | 1.0 | Shrink toward current: `pred = current + λ * (raw - current)`. | [0.5, 1.0] (Do not allow < 0.5) |
| **use_no_change_when_low_confidence** | bool | True | If confidence is "low", return current cutoff (ignore raw). | {True, False} |

### 1.2 Solver / confidence / lookback (Physical Params)

These model the "physics" of the system and should be tuned **first** to maximize trend correlation.

| Parameter | Type | Default | Current location | Description |
|-----------|------|---------|------------------|-------------|
| **confidence_high_i140_min** | int | 10 | solver.CONFIDENCE_HIGH_I140_MIN | Min I-140 rows for "high" confidence. |
| **lookback_months_default** | int | 24 | solver _get_historical_advancement_rate | Lookback for advancement rate (non–EB1 India). |
| **lookback_months_eb1_india** | int | 36 | solver _get_historical_advancement_rate | Lookback for EB1 India. |
| **min_retrogression_transitions** | int | 3 | solver.MIN_RETROGRESSION_TRANSITIONS | Min Sept/Oct pairs to compute retrogression from history. |

### 1.3 Supply / demand (Physical Params - Phase 2)

These live in `estimators.py` and `demand.py`. Exposing them in **VqsMetaParams** with defaults equal to current constants allows future tuning without changing call sites.

| Parameter | Type | Default | Current location | Description |
|-----------|------|---------|------------------|-------------|
| **supply_scale_multiplier** | float | 1.0 | — | Multiply get_monthly_supply by this (e.g. 0.8 = conservative). |
| **demand_lag_scale** | float | 1.0 | demand.NAIVE_LAG_* | Scale applied to per-class lag (months). |
| **spillover_bonus_rate** | float | 0.15 | estimators.SPILLOVER_BONUS_RATE | Q4 spillover multiplier. |

---

## 2. Holder Class API

**Module:** `lib/business/vqs/meta_params.py`

- **VqsMetaParams** – dataclass (constant/frozen) with one field per meta-parameter.
- **Defaults** – `VqsMetaParams.defaults()` returning the current “code” behavior.
- **Serialization (for ML):**
  - `to_dict() -> dict[str, Any]` – all params as JSON-serializable values.
  - `from_dict(d: dict[str, Any]) -> VqsMetaParams` – build from dict.
- **Logic:**
  - `apply_post_step(...)`: Encapsulates stickiness/cap/blend logic. The Solver calls this at the very end of a step.

---

## 3. Tuning Strategy (Two-Stage & Walk-Forward)

We avoid solving for a single static set of parameters for all time. Instead, we use **Two-Stage Tuning** with **Walk-Forward Validation**.

### 3.1 Two-Stage Optimization

1.  **Stage 1: Physics Tuning (Trend Matching)**
    *   **Params**: `lookback_months`, `confidence_min`, `supply_scale`, `demand_lag`.
    *   **Goal**: Maximize the solver's ability to predict the *direction and magnitude* of moves, even if volatile.
    *   **Metric**: MAE, but prioritizing "Big Moves" (weighting errors on months where actual movement > 30 days).

2.  **Stage 2: Control Tuning (Damping)**
    *   **Params**: `stickiness_days`, `cap_forward`, `blend_lambda`.
    *   **Goal**: Dampen noise/jitter without destroying the signal from Stage 1.
    *   **Metric**: MAE + Penalty for "Missed Signals" (e.g., if Stage 1 predicted a jump and Stage 2 zeroed it out, that's bad if the jump actually happened).

### 3.2 Walk-Forward Validation
Instead of a random train/test split, we respect time correlation.
*   **Fold 1**: Train 2018-2019 -> Test 2020.
*   **Fold 2**: Train 2019-2020 -> Test 2021.
*   **Fold 3**: Train 2020-2021 -> Test 2022.

This reveals if "optimal" parameters are stable or if they thrash wildly from year to year.

---

## 4. Search Space (Revised)

| Parameter | Type | Stage | Range / Logic |
|-----------|------|-------|---------------|
| **supply_scale_multiplier** | float | 1 (Physics) | [0.8, 1.2] |
| **lookback_months_default** | int | 1 | [12, 24, 36, 48] |
| **lookback_months_eb1_india** | int | 1 | [24, 36, 48, 60] |
| **min_retrogression_transitions** | int | 1 | [2, 3, 4] |
| **stickiness_days** | int | 2 (Control) | [0, 15, 30, 45, 60] |
| **cap_forward_days** | int | 2 | [60, 90, 120, Infinite] |
| **blend_lambda** | float | 2 | [0.5, 0.75, 1.0] (Constrained: avoid <0.5) |

---

## 5. Implementation Status

**All infrastructure is implemented:**

- `VqsMetaParams` dataclass in `lib/business/vqs/meta_params.py` with `from_dict`/`to_dict` and `apply_post_step()`
- `solver.py` accepts optional `meta: VqsMetaParams` and uses it for all tunable parameters
- `accuracy_metrics.py` propagates `meta` param through `compute_bulletin_accuracy`
- `scripts/vqs/tune_params.py` uses Optuna for hyperparameter optimization with walk-forward validation
- `scripts/vqs/run_backtest.py` evaluates parameter sets against historical data

**Tuning search space** (as of March 2026) also includes `MetricConfig` parameters: `fy_boundary_weight`, `steady_state_weight`, `move_magnitude_weight` for composite multi-horizon loss.

---

## 6. Critique and Risks (Design Review)

### A. Overfitting with "Shaping" Parameters

The plan mixes **physical parameters** (representing reality) with **shaping parameters** (heuristics to force stability). Physical: `supply_scale_multiplier`, `demand_lag`, `lookback_months`. Shaping: `stickiness_days`, `cap_forward_days`, `blend_lambda`.

**Risk:** Cranking up stickiness/caps minimizes MAE on historical data by forcing the model into "current + small epsilon" — a glorified persistence predictor. The PREDICTIONS_ASSESSMENT §8-9 confirmed this: the dampened ensemble is indistinguishable from persistence.

### B. Static Parameters in a Dynamic System

A single global parameter set is average-good but disastrously bad in specific regimes (e.g., failing to catch the onset of retrogression). The Regime-Switched model (PREDICTIONS_ASSESSMENT §9) partially addresses this by selecting experts per-regime, but the meta-params themselves are still static.

**Mitigation:** Regime-based parameter overrides (e.g., `stickiness=0` in ADVANCING, `stickiness=60` in STALLED). Partially implemented via `regime_persistence_weight()` in `regime.py`.

### C. Data Scarcity

Only ~12 bulletins per year. A 3-year validation set = 36 data points per series. With ~10+ hyperparams, the search space is too large.

**Mitigation:** Two-stage tuning (physics first, then control), walk-forward validation, and the new composite metric weighting (PREDICTIONS_ASSESSMENT §10) which focuses optimization on high-value strata rather than averaging across all data points.
