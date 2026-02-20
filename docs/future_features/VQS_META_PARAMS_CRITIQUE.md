# Critique: VQS Meta-Parameters and Tuning Plan

**Status**: Verified against current codebase.
**Verdict**: The engineering plan is solid, but the *tuning strategy* risks overfitting and masking underlying model deficiencies with heuristic "band-aids."

## 1. Strengths of the Plan
- **Architecture**: The `VqsMetaParams` dataclass injection is the correct pattern. It cleanly decouples policy from mechanism.
- **Metric**: MAE (Mean Absolute Error) is the standard heuristic for regression problems and aligns with business value (minimizing surprise).
- **Baselines**: Explicitly comparing against "No Change" is critical, as VQS often competes with a naive random walk model.

## 2. Weaknesses & Risks

### A. Overfitting with "Shaping" Parameters
The plan mixes **physical parameters** (representing reality) with **shaping parameters** (heuristics to force stability).
- **Physical**: `supply_scale_multiplier`, `demand_lag`, `lookback_months`. These model the actual system.
- **Shaping**: `stickiness_days`, `cap_forward_days`, `blend_lambda`. These are artificial clamps.

**Risk**: You can likely minimize MAE on historical data perfectly by cranking up `stickiness` and `caps`, effectively forcing the model to be conservative. However, this essentially "turns off" the solver's ability to predict genuine rapid movements (like recovery after retrogression). You risk tuning the solver into a glorified "current + small epsilon" predictor.

### B. Static Parameters in a Dynamic System
The plan effectively solves for a single global set of optimal parameters ($$\theta^*$$) for the entire validation period (2020-2023).
- **Reality**: The efficient frontier changes. In 2021 (COVID recovery), "fast movement" was the norm. In 2023 (demand surge), "stagnation/retrogression" was the norm.
- **Risk**: A single static `stickiness` or `lookback` value might be average-good but disastrously bad in specific regimes (e.g., failing to catch the onset of retrogression).

### C. Data Scarcity
There are only ~12 bulletins per year. A 3-year validation set = 36 data points per series.
- **Risk**: With ~10+ hyperparams, the generic search space is too large given the sparse signal. Random Search will likely find spurious correlations.

## 3. Suggested Improvements

### Option A: Two-Stage Tuning (Recommended)
Don't tune everything at once.
1.  **Stage 1 (Physics)**: Tune *only* `supply_scale`, `demand_lag`, `lookback_months`, `spillover_bonus`. Maximize the solver's ability to match *trends*, even if it's volatile.
    - *Metric*: Cumulative error or trend correlation, rather than monthly MAE.
2.  **Stage 2 (Control)**: Fix the Stage 1 params. Then tune the `stickiness`, `caps`, and `blend` params to dampen the volatility without destroying the trend signal.
    - *Metric*: MAE, penalized by "Big Miss Rate" (preventing the dampeners from hiding true sharp movements).

### Option B: Regime-Based Params (Advanced)
Instead of static scalar parameters, make them functions of state.
- *Example*: `stickiness_days` shouldn't be constant. It should perhaps be `0` if `current_queue_depth < X` (fast moving) and `60` if `current_queue_depth > Y` (impacted).
- *Simpler Version*: Tune two sets of params: one for "Retrogressing/Stalling" series (EB2/3 India/China) and one for "Current/Flowing" series (ROW).

### Option C: Walk-Forward Validation
Instead of a simple Train/Val/Test split:
- Train on Year $Y$, Test on $Y+1$.
- Train on $Y..Y+1$, Test on $Y+2$.
- This reveals if your "optimal" parameters are stable or if they thrash wildly from year to year.

## 4. Specific Parameter Critiques

| Parameter | Critique | Suggestion |
| :--- | :--- | :--- |
| **`blend_lambda`** | This is a "confidence" proxy. If it tunes to 0.1 (mostly "current"), your solver is broken. | Constrain search to `[0.5, 1.0]`. If it wants `<0.5`, the solver has no signal. |
| **`lookback_months`** | Crucial physical param. | Allow this to vary by Country/Class distinctively (like EB1 India vs ROW). |
| **`cap_forward_days`** | Dangerous. Cap at 90 days prevents predicting a "Visa Current" jump. | Only apply if `predicted > current`. Consider "infinite" as a valid discrete option. |
| **`stickiness_days`** | Good to prevent "jitter". | Best used as a filter: "If `abs(pred - current) < stickiness`, then `pred = current`". |

## 5. Refined Implementation Plan

1.  **Implement `VqsMetaParams`** as designed (it's good infrastructure).
2.  **Implement `backtest.py`** (renamed from 'Tuning script') that runs the **Walk-Forward Validation**.
3.  **Baseline First**: existing hardcoded logic $\to$ MAE.
4.  **Physics Tuning**: Optimize `supply/lookback` params.
5.  **Damping**: Optimize `stickiness/caps` *relative to the physics baseline*.
