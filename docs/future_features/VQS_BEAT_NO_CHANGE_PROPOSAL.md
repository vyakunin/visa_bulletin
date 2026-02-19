# VQS: Beating the "No Change" Baseline

**Goal:** Make VQS prediction better than the naive baseline: "next bulletin cutoff = previous bulletin cutoff."

**Current state (from latest accuracy run):**

| Subset | Baseline (prev=next) mean error | Model mean error | Model wins |
|--------|----------------------------------|------------------|------------|
| All (7,371 rows) | **71.4 days** | 167.2 days | 9.2% |
| Recent excl EB4 (150) | **44.2 days** | 59.3 days | 0.7% |

**Root cause:** When the model predicts **movement** (a different cutoff than previous), it is wrong by a lot:

- Model predicts **same as prev**: mean error **50 days** (5,070 rows).
- Model predicts **different**: mean error **425 days** (2,301 rows); median 45d but p90=1,430d, max=3,958d.

So the simulation often produces large advances that don’t materialize; a few huge errors dominate the overall mean. The baseline wins because (1) actual is no-change 22% of the time (baseline is perfect there), and (2) when we predict movement we frequently overshoot.

---

## Proposed Improvements

### 1. **Stickiness / movement threshold (high impact, low risk)**

Only predict **movement** if the simulated first-month advance exceeds a threshold; otherwise predict **no change** (current cutoff).

- **Implementation:** In `predict_next_bulletin_and_maturity` (or in accuracy call site), after getting `next_cutoff` from the first solver month: if `next_cutoff` is within K days of `current_cutoff`, return `current_cutoff` instead of `next_cutoff`. Suggested K: **14–30 days** (tune on held-out bulletins).
- **Rationale:** Small simulated moves are noisy; treating them as "no change" avoids large errors when the bulletin stays flat. When we do predict movement, we do so only when the simulation shows a clear step.
- **Risk:** We may under-predict real small advances; threshold tuning can balance that.

### 2. **Cap predicted movement (regress toward current)**

Limit how far the predicted cutoff can move from the current cutoff in one bulletin step.

- **Implementation:** After solver returns `next_cutoff`, set  
  `predicted_cutoff = current_cutoff + clamp(next_cutoff - current_cutoff, -MAX_DAYS_BACK, +MAX_DAYS_FWD)`.  
  Example: `MAX_DAYS_FWD = 90`, `MAX_DAYS_BACK = 60` (retro can be sharp in Oct). Optionally use per-series caps from historical max one-step movement.
- **Rationale:** Prevents 1,000+ day overshoots that blow up mean error. One bulletin rarely moves cutoffs by years.
- **Risk:** Caps may be too tight in rare big-jump months; use historical percentiles (e.g. p95 one-step move) to set them.

### 3. **Fallback to "no change" when confidence is low**

When `compute_confidence()` returns `"low"` (e.g. no I-140 data or EB4), return **current cutoff** as the prediction instead of running the full simulation (or in addition to stickiness).

- **Implementation:** At the start of `predict_next_bulletin_and_maturity`, if confidence is `"low"`, return `(current_cutoff, None, [], "low")` (or run solver but then overwrite with current_cutoff when emitting the prediction).
- **Rationale:** With little data, "no change" is a safe default and matches baseline behavior for those series.
- **Risk:** Low; only affects series we’re already uncertain about.

### 4. **Blend with baseline (optional)**

Blend model output with the no-change baseline so prediction is between current cutoff and model cutoff.

- **Implementation:** e.g. `predicted_cutoff = current_cutoff + λ * (model_cutoff - current_cutoff)` with λ in (0, 1], e.g. 0.5. Requires mapping cutoffs to a comparable scale (e.g. ordinal days since a reference date), then mapping back to a date.
- **Rationale:** Shrinks extreme moves toward "no change," reducing variance and large errors.
- **Risk:** Can under-predict real movement if λ is too small; tune λ per series or by confidence.

### 5. **Improve simulation calibration (medium effort)**

Reduce systematic over-advancement so the first-month step is less aggressive.

- **Candidates:**
  - **Supply:** Use a conservative multiplier (e.g. 0.8×) on `get_monthly_supply()` so we don’t advance too fast.
  - **Queue depth:** Calibration from historical advancement may under-fill the queue; consider increasing effective queue depth (e.g. scale demand up) so the same supply advances the cutoff less.
  - **First-month only:** Use a separate, more conservative rule for "first bulletin step" (e.g. advance by min(simulated_step, historical_median_one_step)).
- **Rationale:** If the raw solver rarely overshoots, we need fewer post-hoc caps and stickiness can use a smaller threshold.
- **Risk:** Requires validation so we don’t swing to under-prediction.

### 6. **Per-series no-change rate (optional)**

Estimate P(no change) per (visa_class, country) from history. When that probability is high, bias toward current cutoff (e.g. higher stickiness threshold or larger λ in the blend).

- **Implementation:** Precompute from bulletin history: fraction of consecutive bulletin pairs where cutoff stayed the same. In solver or post-step, if P(no change) > 0.5, require a larger simulated move before predicting movement (or blend more toward current).
- **Rationale:** Some series move rarely; others move often. Adapting by series can improve both mean error and win rate vs baseline.
- **Risk:** Overfitting to history; use simple buckets (e.g. high/medium/low stickiness) rather than raw probability.

---

## Suggested order of implementation

1. **Movement threshold (stickiness)** — quick change, immediate reduction in large errors when we wrongly predict movement.
2. **Cap predicted movement** — prevents extreme overshoots; tune MAX_DAYS from historical one-step moves.
3. **Low-confidence → no change** — simple guard for low-data series.
4. Re-run accuracy and compare to baseline (overall and recent excl EB4). If we’re still worse, add **blend with baseline** (4) and/or **simulation calibration** (5).
5. Optionally add **per-series no-change rate** (6) for finer tuning.

---

## Validation

After each change:

1. Clear checkpoint and run:  
   `bazel run //scripts/vqs:compute_prediction_accuracy -- --metric bulletin --plot --output-dir /tmp/vqs_accuracy --checkpoint-dir /tmp/vqs_ckpt`
2. Compare to baseline (script in runbook or inline):  
   Mean error (model vs baseline), and % of rows where model wins when predictions differ.
3. Target: **Model mean error < baseline mean error** on "all" and on "recent excl EB4," and model win rate > 50% when predictions differ.

---

## References

- Baseline comparison: `docs/future_features/VQS_RUNBOOK.md` (quick comparison snippet).
- Accuracy pipeline: `lib/business/vqs/accuracy_metrics.py` (`compute_bulletin_accuracy`), `lib/business/vqs/solver.py` (`predict_next_bulletin_and_maturity`).
- Current metrics: `VQS_TEST_REPORT.md` (V3 results).
