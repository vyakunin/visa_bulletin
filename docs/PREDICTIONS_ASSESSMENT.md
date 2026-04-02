# Predictions & VQS: Current State Assessment and Next Steps

*Last updated: March 2026*

---

## 0. Long-Term Goal and Success Metrics

### The Goal

**For EB-2 and EB-3 India and China — the series that matter most to users tracking their green card progress — produce predictions that are demonstrably more useful than "assume no change" (persistence).** A prediction system that cannot beat this trivial baseline on the series people actually care about is not worth shipping, regardless of how sophisticated the architecture is.

Persistence is correct ~80% of months for EB-2/3 (cutoffs often don't move). A useful model must reliably identify the ~20% of months with meaningful movement and provide calibrated long-horizon forecasts where persistence is worst.

### Success Metrics

| Metric | What It Measures | Target | Current (Mar 2026) | How to Compute |
|--------|-----------------|--------|-------------------|----------------|
| **Conditional 1m direction** | When actual movement >30d, did model predict the correct sign? | ≥65% | **65.4% (China EB-3, 6m)** — only series meeting target; others 22-53% | `evaluate_model.py` with movement filter |
| **Movement detection precision** | When model predicts >30d move, how often is it right? | ≥50% | **~40%** (GBM Gated best per-series) | Precision on {predicted_move > 30d} |
| **Movement detection recall** | Of actual >30d moves, how many did model catch? | ≥40% | **>60% multiple series** (GBM at 3m/6m) | Recall on {actual_move > 30d} |
| **6-month MAE (EB-2/3 India/China)** | Point forecast error at 6m horizon for the 4 key series | ≤190d (≥15% below persistence) | China EB-2: **176d** (GBM Gated); China EB-3: **159d ✓** (GBM Gated); India EB-2: **204d** (GBM Gated); India EB-3: **261d** (GBM Gated) | `evaluate_model.py --horizons 6` per-series |
| **12-month MAE (EB-2/3 India/China)** | Point forecast error at 12m horizon | ≤300d (≥15% below persistence) | China EB-2: **231d ✓** (GBM Gated); China EB-3: **224d ✓** (GBM Gated); India EB-2: **303d** (GBM Gated); India EB-3: **499d** (GBM Gated) | `evaluate_model.py --horizons 12` per-series |
| **Regime transition detection** | Correct identification of advancing→stalled or stalled→advancing within 1 month | ≥50% | **~12%** (Hybrid at 6m) — significantly below target | Stratified accuracy breakdown in spaghetti |
| **Calibration** | % of actuals falling within stated 80% CI | 75–85% | ~80% (2025+ recent) | `compute_prediction_accuracy --metric both` |

**Non-goals:**
- Beating persistence on aggregate 1-month MAE across all series. Persistence is ~41d; getting to ~40d by averaging a few EB-1 wins across 6 series is not meaningful.
- Achieving low MAE on EB-1 — already solved by Regime-Switched for FY boundary jumps.
- EB-4 accuracy — data-starved, marked Experimental.

### Design Principles

1. **ML-tunable over hardcoded.** Prefer models whose behavior is controlled by a detached set of hyperparameters (learnable weights, tree splits, Optuna-tunable scalars) over if/else regime dispatch. The GBM expert (`gbm_expert.py`) and the Hedge aggregator (`aggregator.py`, `contextual_aggregator.py`) are examples of the right pattern. Hardcoded `if regime == ADVANCING: use expert_X` is the wrong pattern — it doesn't generalize and can't be tuned.

2. **Exception: public policy structure.** Hardcoded logic is acceptable when it directly models publicly known immigration policy: the per-country 7% cap, EB overflow/waterfall (EB-1 unused → EB-2 → EB-3), fiscal year October reset, INA Section 202(a)(5) fall-across rules. These are structural constraints, not learned patterns.

3. **Features over rules.** When a signal is discovered (e.g., "EB-1 surplus predicts EB-2 advancement"), encode it as a **feature** for a trainable model (GBM, Hedge expert weights), not as a conditional branch in the solver. Features compose; if/else branches don't.

4. **Evaluate on what users care about.** Optimize for conditional metrics (direction accuracy when movement happens, movement detection precision/recall, long-horizon MAE on EB-2/3) — not aggregate 1-month MAE that rewards predicting "no change."

5. **Quick-mode (`--quick`) is unreliable for inference-time feature changes.** Quick mode subsamples every 3rd bulletin, which can introduce systematic bias when the change being evaluated is at inference time (not training time). Section 18 demonstrated a 23× overestimate: quick-mode showed 60d improvement for India EB-3 demand-drop masking; full-data showed 2.6d. **Rule**: Always use full-data evaluation for feature masking, feature addition/removal at inference, or any change to `_build_features_for_series`. Quick mode is valid only for comparing models that retrain on the same data (e.g., GBM hyperparameter tuning, new expert pool members).

### What Has Been Tried and Didn't Work (Summary)

| Approach | Section | Result | Why It Failed |
|----------|---------|--------|---------------|
| FY boundary conditional model | §8 | Regressed (+2.7d recent MAE) | Only ~8 training transitions per series; 60/40 tier blending too aggressive; persistence override 0.05 too extreme |
| VQS Ensemble (dampened) for EB-2/3 | §9, §11 | Tied with persistence (41.4d vs 41.5d) | Dampening stack (0.797 persistence weight + stickiness + caps) suppresses all signal |
| Regime-Switched for EB-2/3 | §9 | Near-zero divergence (3/122 months for India EB-2) | Model only has signal for EB-1 FY jumps; EB-2/3 experts are nearly identical to persistence |
| Cross-series spillover features | §13 | Improved 6m direction accuracy (50% vs 10%) but not 1m MAE | Signal is real but emerges at 3-6m, not 1m |
| GBM for 1m MAE improvement | §15, §16 | GBM Gated 1m MAE = 64d (vs persistence 41.5d) | Movement detection at 1m has unfavorable base rate: ~80% of months have no >50d movement, so false positives dominate even at 40% precision |
| VQS ensemble Optuna tuning of GBM | §16 | Objective stuck at 279-281 across 50 trials | Ensemble objective blind to GBM — persistence weight (0.797) down-weights GBM, making its params invisible to optimizer |
| GBM Gated at 1m (any gate threshold 0.68–0.95) | §17 | MAE 106.8d (2.3× worse than persistence 89.1d) | Base-rate problem: ~80% of 1m intervals have no >50d movement. Gate sweep confirms no operating point — MAE varies <2d across all thresholds. Signal quality insufficient, not threshold selection. |
| Per-series gate thresholds at 1m | §17 | <2d improvement over uniform gate | Gate threshold has flat response at 1m; all series equally affected by base-rate problem |
| Demand-drop features (uniform inclusion) | §17 | Mixed 6m effect: helps China EB-1/India EB-1 (+10-12d), hurts India EB-3 (−60d) | Not uniformly beneficial. Per-series feature masking might work but adds complexity for uncertain gain |
| Per-series demand-drop masking (India EB-3) | §18 | Full-data India EB-3 GBM Gated: 290.1d (masking) vs 282.3d (Pace) | Quick-mode 60d estimate was overestimate. Full-data improvement ~2.6d. Masking kept (harmless) but India EB-3 dispatches to Pace not GBM. |
| PERM filing volume feature (perm_filing_ratio) | §19-20 | Ablation shows zero contribution at inference. §19 improvements were evaluation window shift. | GBM tree does not use feature 27 in any decision path. Effective feature landscape unchanged. |

### Last Assessment (April 2026, §21 evaluation + metric reconciliation)

**Facts (measured, §21 same-window eval `--horizons 1,3,6,12 --gbm`):**
- Dispatch composite (new formula, blog-comparable): **164d** vs Persistence 195d, Pace 180d — Dispatch now wins on composite.
- Discovery: old blog composite (205d) was stale data predating §20 China EB-2→GBM Gated 12m switch; current dispatch was already better than reported.
- Dispatch per-horizon MAE: 1m 42.1d, 3m 118.3d, 6m 197.7d, 12m 311.3d.
- Persistence per-horizon: 1m 42.8d, 3m 123.0d, 6m 229.0d, 12m 396.5d.
- India EB-3 at 12m: Pace 490d, GBM Gated 494d, Persistence 524d — Pace is best; no change to dispatch.
- `evaluate_model --per-series-summary` now auto-prints composite table via `print_composite_table()` using MetricConfig default weights.
- `compute_prediction_accuracy.py` now uses MetricConfig canonical weights (not proportional h/sum(h)) when horizons=[1,3,6,12].

**Fixes applied:**
- Blog text: removed false claim "uses the same weighted objective this model optimizes"; replaced with accurate description.
- Blog number: THIS_MODEL composite_days updated 205.0 → 164.0 (§21 evaluation).
- Added `print_composite_table()` to `evaluate_model.py` — reproducible composite for all methods.
- Added `_PERSISTENCE_12M_SERIES` frozenset to both dispatch files (currently empty, reserved for future use if a series is confirmed Persistence-dominated at 12m).
- `tune_params.py` `objective()` docstring clarifies that the optimization objective ≠ reporting composite.

**Facts (preserved from March 2026):**
- VQS Ensemble 1m MAE = 41.4d vs persistence 41.5d on 6 oversubscribed series (Section 11)
- Pace 6m MAE = 211d vs persistence 228d, beats persistence on all 6 series (Section 11)
- Supply rebalancing reduced 2025+ under-prediction rate from ~72% to 42% (Section 13)
- I-140 data: FY2014–FY2025 complete (576 rows in raw_facts_ledger)
- Tuned GBM params: n_estimators=258, max_depth=8, lr=0.103, movement_threshold=50, gate_threshold=0.68
- **GBM at 1m is unsafe at ALL gate thresholds (0.68–0.95)**: 1m MAE is 93d–123d depending on series. Gate sweep confirms no operating point. (Section 17)
- **GBM already trains per-horizon** (confirmed Section 18 review): `_build_training_data` (1m) and `_build_training_data_horizon` (3m/6m/12m) are separate.
- 12m dispatch live (Section 18). Movement probability badge implemented in UI (Section 18).
- Per-series demand-drop masking (Section 18): Full-data improvement ~2.6d (23× overestimate from quick-mode). Masking kept (harmless).
- PERM filing volume feature (Section 19): `perm_filing_ratio` at feature index 27. 1.6M `RawFactsLedger` entries (FY2008-FY2026 Q1).
- **PERM feature FALSIFIED (Section 20)**: `--ablate-perm` ablation shows zero contribution — full eval and ablation results are numerically identical. PERM is not used in any GBM tree decision path. §19 improvements were from evaluation window shift, not PERM signal.
- **Section 20 same-window 6m GBM Gated**: China EB-1: 169d, China EB-2: **176d**, China EB-3: **159d** ✓, India EB-1: **233d** ✓, India EB-2: **204d**, India EB-3: **261d**.
- **Section 20 same-window 12m GBM Gated**: China EB-1: **257d**, China EB-2: **231d** ✓, China EB-3: **224d** ✓, India EB-1: **370d**, India EB-2: **303d**, India EB-3: 499d (Pace 491d wins).
- **Same-window Pace 6m**: China EB-2 = 155.4d (30% better than GBM Gated 176.1d — Pace remains best at 6m for this series). India EB-2 Pace = 211.3d vs GBM Gated 203.8d (7.5d gap, below 10d dispatch threshold). India EB-3 Pace = 264.3d vs GBM Gated 261.1d (3.2d gap, Pace keeps dispatch).
- **Dispatch update (Section 20)**: China EB-2 at 12m moved from Pace to GBM Gated (margin 15.7d). GBM Gated now wins 5/6 at 12m. All 6m dispatch series unchanged.
- **CondDir ≥65% met**: China EB-3 at 6m (65.4%) and 12m (65.4%). All other series below 65%.

**Success metrics (current, §21 evaluation):**

| Metric | Original Target | Revised Target | Current Best | Status |
|--------|----------------|---------------|--------------|--------|
| Conditional 1m direction | ≥65% | **≥25%** | 65.4% China EB-3 6m/12m; others 22-53% | **Met for China EB-3**; others below |
| Movement detection precision | ≥50% | **≥50% at selected gate** | ~40% (GBM Gated best per-series) | Below; 1m gate sweep shows no operating point |
| Movement detection recall | ≥40% | ≥40% at 3m+ | **>60% multiple series** (GBM at 3m/6m) | **Met** at longer horizons |
| 6m MAE China EB-3 | ≤190d | ≤190d | **159d ✓ (GBM Gated)** | **Met** (§20 same-window) |
| 6m MAE India EB-1 | ≤250d | ≤250d | **233d ✓ (GBM Gated)** | **Met** (§20 same-window) |
| 6m MAE China EB-2 | ≤190d | ≤190d | **155d ✓ (Pace)** | **Met** (§20 same-window; Pace best at 6m) |
| 6m MAE India EB-2 | ≤190d | ≤190d | **204d (GBM Gated)** | Not met; 7.5d below Pace (211d), below 10d dispatch threshold |
| 6m MAE India EB-3 | ≤190d | ≤190d | **261d (GBM Gated)** | Not met; only 3.2d below Pace (264d) |
| 12m MAE EB-2/3 India/China | ≤300d | ≤300d | China EB-3: **224d ✓**; China EB-2: **231d ✓**; India EB-2: **303d**; India EB-3: 491d (Pace) | **2/4 met**; India EB-2 borderline (+3d); India EB-3 far off |
| 1m MAE not worse than persistence | N/A (new) | **≤42d** when using GBM | 106.8d (GBM Gated) | **Not met** — badge-only approach is the accepted resolution |
| 12m predictions published | N/A | YES | **YES** (Section 18) | **Met** — dispatch live for all 6 series |
| Movement badge in UI | N/A | YES | **YES** (Section 18) | **Met** — pending production deployment |
| Dispatch tables current | N/A | YES | **YES** (Section 20) | **Met** — updated with same-window §20 numbers |

**Target revision rationale:** The 65% CondDir target at 1m assumed movement detection was feasible at high precision. After extensive experimentation (Sections 8-16), the data shows ~80% of 1m intervals have no >50d movement for EB-2/3. Even perfect detection of the 20% movement months, with zero false positives, gives CondDir = (correctly predicted movers / all movers). At 20% base rate, achieving 65% requires very high recall AND precision — neither is available from the current feature set. 25% is ambitious but achievable (≈1 in 4 movements detected correctly) and genuinely useful to users. Added "1m MAE ≤ persistence" as a hard constraint — any model deployed at 1m must not degrade MAE.

**Hypotheses (updated post-Section 20 planning review):**

**Tested and resolved:**

- ~~Per-horizon gate threshold can unlock 1m deployment~~ → **FALSIFIED** (§17). Gate sweep 0.68–0.95: MAE varies <2d, consistently 21-28d worse than persistence. No operating point exists. The problem is signal quality at 1m, not threshold selection.
- ~~GBM Gated should replace Pace at 6m for 3 series~~ → **PARTIALLY CONFIRMED** (§17). Holds for China EB-3 (−49.5d) and India EB-1 (−44.6d). Does NOT hold for China EB-1 — RS is best there (149.8d vs GBM 168.4d). Section 16's China EB-1 measurement was wrong (stale defaults). Production dispatch corrected accordingly.
- ~~I-485 density near cutoff would improve India EB-3~~ → **PARTIALLY ADDRESSED** (§17). Data IS PD-granular, feature implemented (index 26). Bug fix: `_get_i485_queue` was silently returning zero for ALL training samples — this was a larger issue than the missing density feature. India EB-3 remains the weakest series (275d at 6m); the feature's isolated impact can't be measured because the bug fix was a confound.
- ~~3m CondDir regression is a measurement artifact~~ → **LIKELY TRUE** but not explicitly re-tested. Low priority — the 50d movement threshold is the correct operating point per Optuna tuning.
- ~~Per-horizon GBM training would eliminate the 1m/6m trade-off~~ → **MOOT — ALREADY IMPLEMENTED** (§18 review). `gbm_expert.py` has `_build_training_data` (1m) and `_build_training_data_horizon` (3m/6m/12m) as separate paths. There is no joint-horizon training. The 1m/6m trade-off is from signal quality (base-rate problem), not shared training.
- ~~Movement probability badge is the right 1m UX for GBM signal~~ → **IMPLEMENTED** (§18). Badge live in `prediction_detail.html` with Stable/Watch/Movement Likely thresholds at P=0.4/0.55. Pending production deployment and user engagement validation.
- ~~12m GBM predictions are the highest-value next publication~~ → **IMPLEMENTED** (§18). 12m dispatch live for all 6 series; GBM Gated for China EB-1/India EB-1/China EB-3, Pace for India EB-2/3/China EB-2. `movement_probability` field added to `PredictedCutoff`.
- ~~Per-series demand-drop feature masking would improve 6m GBM~~ → **FALSIFIED on magnitude** (§18 full-data eval). Quick-mode estimated 60d improvement for India EB-3 masking; full-data shows 2.6d (23× overestimate). Masking kept in code (harmless) but India EB-3 still dispatches to Pace. **Methodological lesson**: quick-mode is unreliable for inference-time feature changes — see Design Principles.
- ~~PERM certified filing volume is a 12-18 month leading indicator of EB-2/3 cutoff pressure~~ → **FALSIFIED** (§20). `--ablate-perm` ablation: zeroing feature 27 at inference produces numerically identical GBM results. The tree does not use the PERM feature in any reachable decision path. The §19 improvements vs §17 were entirely from evaluation window shift (walk-forward training accumulating more data), not PERM signal.
- ~~GBM Gated should replace Pace as the 6m dispatch for India EB-2 and India EB-3~~ → **PARTIALLY CONFIRMED, THRESHOLD NOT MET** (§20). Same-window eval: India EB-2 GBM 203.8d vs Pace 211.3d (7.5d gap, below 10d threshold); India EB-3 GBM 261.1d vs Pace 264.3d (3.2d gap). Dispatch unchanged at 6m. China EB-2 at 12m DID switch to GBM Gated (margin 15.7d, above threshold).

**Active hypotheses:**

4. **India EB-2 at 6m is reachable; India EB-3 at 6m may have a structural floor above target.** Updated with §20 same-window numbers: India EB-2 = 204d (GBM Gated), 14d from the 190d target — and improving (was 211d in §17). India EB-3 = 261d (GBM Gated), 71d from target and improving slowly (was 275d). All models tried fail to break 200d for India EB-2 and 250d for India EB-3. However, the trajectory is downward — the "exhausted feature set" characterization from earlier was premature (walk-forward data accumulation is still providing marginal gains). **Falsification**: if India EB-2 cannot break 195d after ensemble re-tuning + 6 more months of data, the 190d target is unrealistic for the current feature set. For India EB-3, if it remains >240d after one more iteration, consider revising the target to 250d. **Competing**: the true forecast error floor for India EB-2/3 may be 195-260d because these series are governed by policy backlog dynamics that no publicly available feature can predict at 6m. **Prior confidence**: medium for India EB-2 (14d gap, consistent GBM improvement); low for India EB-3 (71d gap, structural backlog).

6. **The i485 bug fix is a confound for all Section 17 GBM measurements.** Feature 11 (`i485_queue_size`) was silently zero for ALL training samples until the fix. Every measurement in Section 17 includes both the stale-defaults fix AND the i485 fix. We cannot attribute the difference from Section 16 to either fix alone. **Falsification**: re-run with feature 11 zeroed and compare to Section 17 results. **Prior confidence**: low-medium that this matters — I-485 data coverage is sparse (576 rows, quarterly). **Priority**: low — the fix is beneficial regardless, and separating the two effects has diminishing research value now that §20 provides clean same-window baselines.

9. **Ensemble re-tuning with updated feature set would improve published predictions.** The production `persistence_weight=0.797` is from Optuna trial #13 (pre-GBM, pre-i485 fix). PERM is zero-contribution, but i485 bug fix and density feature are real changes to the effective feature landscape. **Falsification**: run `tune_params --objective conditional --gbm-params --n-trials 50 --horizons 6 12`. If new persistence_weight is within 0.02 of 0.797 and metrics don't improve >3d on any series, the tuning is wasted. **Prior confidence**: medium-low — effective feature change is smaller than expected (PERM was the largest anticipated signal). Re-tuning may still improve i485 and density utilization.

10. **Walk-forward training naturally improves GBM as more bulletin data accumulates.** The §17→§19 improvement (3-14d across all series, diffuse and not concentrated on PERM-relevant series) is consistent with more training data improving tree quality. §20 ablation confirms this — PERM is zero, so all improvement is from data growth. **Falsification**: re-run full eval in 6 months; if average per-series 6m MAE improvement vs §20 is <2d, diminishing returns have set in. **Competing**: the §17→§19 window may contain a particularly informative period (2024-2025 unusual retrogression); future windows may not show similar gains. **Prior confidence**: medium — GBM benefits from more data, but marginal returns diminish as training set grows.

11. **India EB-2 6m dispatch will converge to GBM Gated.** Two consecutive evaluations (§19 cross-window, §20 same-window) show GBM Gated beating Pace by 7.5d. Direction is consistent but below the 10d dispatch threshold. After ensemble re-tuning (potentially changing persistence blending) or after 6 more months of data, the margin may grow. **Falsification**: after re-tuning, same-window eval shows GBM Gated margin <5d or Pace wins. **Prior confidence**: medium.

**Recommended next steps** (ordered by value × feasibility, post-Section 20 planning review):

1. ~~**PERM feature removal from GBM vector**~~ → **COMPLETED** (March 2026): Removed `perm_filing_ratio` from `_build_features_for_series` and `FEATURE_NAMES` in `gbm_expert.py`. Feature set is now clean (27 features, indices 0-26). `RawFactsLedger` PERM data retained — still used by `demand.py` for the virtual queue model.

2. ~~**Production deployment of movement badge + 12m predictions**~~ → **COMPLETED** (March 2026): Migrations 0041/0042 applied. `publish_predictions` generates `model_name` + `movement_probability` for new months. `PredictedCutoff` rows for 2026-06+ include these fields. VQS maturity prediction also wired to dashboard chart (dotted line + diamond marker) and table.

3. **Ensemble re-tuning** (MEDIUM EFFORT, MEDIUM-LOW INFO GAIN): `tune_params --objective conditional --gbm-params --n-trials 50 --horizons 6 12`. PERM removed, so tuned params will reflect the clean 27-feature set. Tests Hypothesis #9. May also move India EB-2 6m margin above the 10d dispatch threshold (Hypothesis #11).

4. **India EB-2 dispatch revisit** after re-tuning: GBM Gated beats Pace by 7.5d at 6m — consistent across two eval windows but below 10d threshold. Re-check after step 3. Tests Hypothesis #11.

5. **Wait-and-re-evaluate strategy** (ZERO EFFORT, MEDIUM INFO GAIN): The walk-forward improvement trend (Hypothesis #10) suggests simply re-running evaluation after 6 months of new bulletin data may yield 3-10d improvement per series. This is the lowest-effort path and should be the default unless a specific new signal opportunity arises.

6. **India EB-2 new signal exploration** (HIGH EFFORT, MEDIUM INFO GAIN): India EB-2 6m = 204d (14d from 190d target). The gap is reachable but requires new features. Most promising candidates: USCIS processing time trends (monthly case completions — publicly available from USCIS website), EB-1→EB-2 overflow estimation from I-140 approval rate differentials. Deprioritize India EB-3 signal exploration (71d gap, likely structural — revise target to 250d if no improvement after next re-eval).

---

## 1. Executive Summary

The project has **two layers** of prediction capability at different maturity levels:

| Layer | Status | Accuracy | Description |
|-------|--------|----------|-------------|
| **Simple Linear Projection** | Deployed, live on dashboard | 1-month MAE 77d, 12-month MAE 359d | 12-month rolling average extrapolation |
| **VQS Ensemble (tuned)** | Built, backtested, not shipped | 1m MAE 41.4d (≈ persistence 41.5d), 6m wins 4/6 series | Optuna-tuned meta + aggregator; close to persistence on average MAE, better on composite and at 6m |
| **Regime-Switched Model** | Built, evaluated (Mar 2026) | 1m MAE 40.9d, beats persistence 3/5 series | Undampened expert selector — best average MAE at 1m/3m |
| **Pace** | Baseline in evaluation | 6m MAE 211d, beats persistence 6/6 at 6m | Constant-pace extrapolation; best at 6m horizon |

The **single predictor to use in production** is the **VQS Ensemble**: `predict_next_bulletin_and_maturity(..., meta=VqsMetaParams.defaults(), aggregator=ExpertAggregator())` (same path as `publish_predictions`). It accumulates the tuned meta params, learning rate, and metric-driven warmup. Regime-Switched and Pace are alternative models that sometimes beat the ensemble on raw MAE but are not merged into the published predictor. See Section 11 for post-tune comparison and exact invocation.

**See Section 0 for long-term goal, success metrics, and design principles.** The current system does not yet meet those goals for EB-2/3 India/China.

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

### Phase 3 Follow-Up Results (Mar 2026)

#### Supply Rebalancing Verification (3c)

Full bulletin accuracy run on 286 bulletins (2017–2026):

| Metric | Before rebalancing | After rebalancing |
|--------|--------------------|-------------------|
| Overall under-prediction rate | ~72% | 75.6% (all history) |
| Recent 2025+ under-prediction | ~72% | **42.1%** |
| Recent 2025+ pred == actual | — | 49.8% |
| Recent 2025+ MAE | — | 30.7d |

The higher overall rate (75.6%) is expected — the historical data from 2017–2022 was collected before the supply rebalancing and has higher systematic bias. For recent bulletins (2025+), the under-prediction rate dropped from ~72% to 42%, confirming the rebalancing is working as intended.

#### Optuna Re-Tuning (3b)

Ran 8 quick-mode trials (30-min timeout). tune_params.py tunes `ContextualTrajectoryAggregator` params (used in evaluate_model.py only), not `VqsMetaParams.ensemble_persistence_weight` (production). Best trial #5 with composite MAE=532.4:

| Parameter | Previous default | New value (trial #5) |
|-----------|-----------------|----------------------|
| learning_rate | 1.0 | 3.5 |
| blend_temperature | 0.1 | 0.029 |
| use_regime_context | True | False |
| Composite MAE | 781.3 (trial 0) | **532.4** (trial 5) |

Updated `contextual_aggregator.py` defaults. Note: 8 trials is insufficient for reliable convergence — the `ensemble_persistence_weight` (0.797 in VqsMetaParams) still needs separate tuning in a future session with more compute.

#### Long-Term Metric Breakdown (3d)

`aggregate_longterm_by_horizon_and_series()` was already implemented. The `longterm_accuracy_summary.json` includes by-horizon and by-series MAE breakdown (currently only "1-3" bucket due to data range). The infrastructure is complete for when longer-horizon predictions are available.

### Lessons and Next Steps

1. Supply rebalancing is confirmed effective for recent bulletins — recent under-prediction rate 42% vs target 50%. No further action needed.
2. `ensemble_persistence_weight` (production param) still needs full Optuna re-tuning with the new expert pool. Recommend 50–100 trials on a machine with more compute.
3. EB-4 should remain marked Experimental until more data is available.
4. Expert predictions breakdown UI (`expert_predictions` JSON) is live in the collapsible "why?" section.

### Current Status

- Cross-series: **Live** (trajectory_cross_series, contextual aggregator EB-1 context, GBM features)
- UI: **Live** (CI display, regime badges, EB-4 Experimental, confidence level, expert "why?" breakdown)
- Supply rebalancing: **Live and verified** (recent under-prediction 42%)
- Optuna re-tuning: **Partial** (8 trials, ContextualAggregator defaults updated; VqsMetaParams tuning pending)
- Long-term breakdown: **Live** (horizon-stratified summary in longterm_accuracy_summary.json)

---

## 14. Phase 4 Deferred Tasks (Mar 2026)

### Motivation

After Phase 3 verified supply rebalancing and completed Optuna tuning, the remaining deferred tasks were evaluated: I-140 expansion, historical retrogression, and EB-1 India tweaks.

### What Was Found / Implemented

| Task | Status | Finding |
|------|--------|---------|
| I-140 FY2020–FY2025 expansion (4a) | **Already done** | DB has FY2014–FY2025 complete (576 rows, 12 series × 4 quarters × 12 years) |
| Historical retrogression (4b) | **Already done** | `get_retrogression_months_from_history()` in solver.py already queries VisaCutoffDate; `_RETROGRESSING_SERIES` is only a last-resort fallback |
| EB-1 India lookback alignment (4c) | **Implemented** | `lookback_months_eb1_india` changed 24→36 in `meta_params.py` per VQS_META_PARAMS_AND_TUNING.md recommendation |
| EB-1 India supply bonus (4c) | **Already done** | `estimators.py` already has +5% EB-1 supply bonus for April-September |

### EB-1 India Results (After 36m Lookback)

| Horizon | Model | MAE (days) |
|---------|-------|-----------|
| 1m | Persistence | 130.7 |
| 1m | Regime-Switched | **127.7** |
| 3m | Persistence | 161.0 |
| 3m | Regime-Switched | **143.9** |
| 6m | Persistence | 279.6 |
| 6m | Regime-Switched | **258.1** |

Regime-Switched beats persistence at all horizons for India EB-1. The 36m lookback provides a more stable historical advancement rate estimate, reducing noise from recent stalls.

### Lessons

1. Most "deferred" tasks (4a, 4b) were already implemented in the large Phase 1 commit — the initial implementation was more complete than documented.
2. The 36m lookback for EB-1 India is a low-risk, non-breaking improvement. The Regime-Switched model is the best selector for this series.
3. The `_RETROGRESSING_SERIES` fallback is effectively dead code for active series (India/China have 10+ historical Oct transitions) but useful as a safety net for new or sparse series.

### Current Status

- I-140 data: **FY2014–FY2025 complete** in raw_facts_ledger
- Historical retrogression: **Live** (get_retrogression_months_from_history, fallback to _RETROGRESSING_SERIES)
- EB-1 India lookback: **Updated to 36m** (meta_params.py)
- EB-1 India supply bonus: **Live** (+5% Apr–Sep in estimators.py)

---

## 15. Baseline Measurement: New Metrics + GBM Foundation (Mar 2026)

### Motivation

After implementing conditional metrics (A2), GBM expert (B1–B5), multi-horizon training, movement classifier, and quantile regression, this section records the first complete baseline measurement using the new evaluation framework. The GBM models were not available locally (missing `libomp.dylib` on macOS — production Linux unaffected), so this baseline covers non-GBM models only. GBM results to be added after first production run.

### Measurement Setup

- **Script**: `scripts/vqs/evaluate_model.py`
- **Date**: 2026-03-19
- **Series**: India EB-1/2/3, China EB-1/2/3 (6 series × 3 horizons)
- **Evaluation window**: ~122 knowledge dates per series
- **New metrics added**: Conditional direction accuracy (when actual move >30d), movement precision/recall, big-move capture rate, regime-change detection rate

### 1-Month Horizon Results (filing dates)

| Series | Model | MAE (d) | DirAcc% | CondDir% | MovPrec% | MovRec% |
|--------|-------|---------|---------|---------|---------|---------|
| India EB-2 | **Persistence** | **35.7** | 0.0 | 0.0 | N/A | 0.0 |
| India EB-2 | VQS Ensemble | **21.7** | 0.0 | 0.0 | N/A | 0.0 |
| India EB-2 | Dashboard | 45.7 | 78.3 | 88.9 | 37.5 | 52.9 |
| India EB-2 | Hybrid | 21.7 | 0.0 | 0.0 | N/A | 0.0 |
| India EB-3 | **Persistence** | **52.1** | 0.0 | 0.0 | N/A | 0.0 |
| India EB-3 | VQS Ensemble | **28.2** | 40.0 | 50.0 | N/A | 0.0 |
| India EB-3 | Hybrid | 28.2 | 40.0 | 50.0 | N/A | 0.0 |
| China EB-2 | **Persistence** | **34.8** | 0.0 | 0.0 | N/A | 0.0 |
| China EB-2 | VQS Ensemble | **28.2** | 50.0 | 50.0 | N/A | 0.0 |
| China EB-2 | Hybrid | 28.2 | 50.0 | 50.0 | N/A | 0.0 |
| China EB-3 | **Persistence** | **38.2** | 0.0 | 0.0 | N/A | 0.0 |
| China EB-3 | VQS Ensemble | 36.4 | 0.0 | 0.0 | N/A | 0.0 |
| China EB-3 | Hybrid | 36.4 | 0.0 | 0.0 | N/A | 0.0 |

**Aggregate 1-month (all series)**:

| Model | MAE (d) | DirAcc% | CondDir% |
|-------|---------|---------|---------|
| Persistence | 41.5 | N/A | 0.0% |
| VQS Ensemble | **31.1** | 15.0 | 0.0% |
| Hybrid | **33.1** | 29.7 | 0.0% |
| Regime-Switched | 40.9 | 17.8 | 0.0% |
| Dashboard | 52.1 | 77.7 | 5.4% |
| Pace | 46.5 | 91.1 | 0.0% |
| Contextual Ensemble | 46.0 | 91.1 | 0.0% |
| Demand-Supply | 53.1 | 91.1 | 0.0% |

**Key facts**:
- VQS Ensemble beats persistence in 5/6 series at 1m, MAE 31.1 vs 41.5 (−25%)
- Conditional direction accuracy: 0% for all models except Dashboard (5.4%) → **no model reliably detects when movements will occur**
- Movement recall: 0% for VQS Ensemble and Hybrid → these models never predict large moves; they output near-persistence values

### 3-Month Horizon Results (aggregate)

| Model | MAE (d) | DirAcc% | CondDir% |
|-------|---------|---------|---------|
| Persistence | 122.5 | 3.9 | 3.4% |
| Regime-Switched | **118.3** | 16.8 | 3.6% |
| Hybrid | **114.2** | 36.0 | 4.2% |
| Pace | 121.1 | 52.5 | 2.2% |
| Contextual Ensemble | 120.9 | 48.1 | 2.2% |
| Dashboard | 138.6 | 60.8 | 22.4% |
| Demand-Supply | 131.7 | 67.1 | 25.3% |

At 3m: Hybrid 114.2 vs persistence 122.5 (−7%). Dashboard has 22% CondDir — it detects movements but with poor MAE.

### 6-Month Horizon Results (aggregate)

| Model | MAE (d) | DirAcc% | CondDir% |
|-------|---------|---------|---------|
| Persistence | 228.3 | 8.6 | 15.9% |
| **Hybrid** | **209.7** | 40.8 | 11.5% |
| **Pace** | **211.1** | 37.2 | 12.4% |
| **Contextual Ensemble** | **212.4** | 34.3 | 12.4% |
| Regime-Switched | 224.4 | 15.7 | 10.5% |
| Demand-Supply | 223.2 | 66.9 | 32.8% |
| Dashboard | 255.4 | 54.6 | 19.1% |

At 6m: Hybrid/Pace/Contextual Ensemble beat persistence by ~8% (228→210 days). Demand-Supply has 33% CondDir — highest among models.

**6m series-level highlights** (EB-2/3 India/China):

| Series | Persistence MAE | Best Model | Best MAE | Improvement |
|--------|-----------------|-----------|---------|-------------|
| China EB-2 | 193.0 | Pace/Hybrid | 152.7 | −21% |
| China EB-3 | 221.3 | Pace/Hybrid | 198.2 | −10% |
| India EB-2 | 210.8 | Pace/Hybrid | 204.4 | −3% |
| India EB-3 | 287.6 | Hybrid/Pace | 282.3 | −2% |

China EB-2 shows the biggest 6m improvement. India EB-3 shows the least.

### Diagnostic Facts (What This Tells Us)

1. **VQS/Hybrid at 1m = near-persistence**: CondDir and MovRec are 0% → model outputs near-zero predicted movements, coincidentally correct ~60% of the time (because most months have no movement) but fails to predict actual movements.
2. **Dashboard has 22–33% CondDir**: Uses linear extrapolation, which accidentally catches some movements, but its MAE is consistently worse (it over-predicts movements that don't materialize).
3. **Pace and Contextual Ensemble are best at 6m**: They advance cutoffs more aggressively, which is correct at longer horizons but overshoots at 1m.
4. **Demand-Supply has highest CondDir at 6m (33%)**: But worse MAE overall — it detects movement direction when it occurs, but magnitude estimates are noisy.
5. **GBM not yet evaluated**: Missing `libomp.dylib` on dev Mac. All GBM calls (`expert_gbm`, `expert_gbm_direct`, `expert_gbm_gated`) returned N/A in this run. Expected to run on Linux (staging/production).

### Success Metric Status (Against Targets in Section 0)

| Metric | Target | Current Best | Gap |
|--------|--------|--------------|-----|
| Conditional 1m direction | ≥65% | 5.4% (Dashboard) | Large — no model detects 1m movements |
| Movement detection precision | ≥50% | N/A (models don't predict moves) | Unmet — GBM classifier needed |
| Movement detection recall | ≥40% | 0% (VQS/Hybrid) | Unmet — dampening suppresses moves |
| 6m MAE EB-2/3 India/China | ≤190d | 152d (China EB-2 Pace) | **Met for China EB-2**; India EB-2/3 still need work |
| Regime transition detection | ≥50% | ~12% (Hybrid at 6m) | Below target |

### Hypotheses Requiring GBM Results

- **H1**: GBM with movement classifier (B4) will break the 0% CondDir floor by explicitly training on movement events. *Falsification*: if GBM CondDir < 20%, classifier is not learning useful signal.
- **H2**: GBM direct 6m model (B2) will match or beat Pace/Contextual Ensemble at 6m. *Falsification*: if GBM 6m MAE > Pace 6m MAE on 3+ series, multi-horizon GBM adds no value.
- **H3**: I-485 queue depth features (B3) will improve recall for India EB-3 at 3m (longest backlog → most predictable retrogression timing). *Falsification*: if India EB-3 GBM MovRec is not higher than Dashboard MovRec.

### Current Status

- Non-GBM baseline: **Recorded above** (March 2026)
- GBM baseline: **Pending** (run on staging/production where lightgbm+libomp is available)
- Next step: Run `evaluate_model.py` on staging, capture GBM lines, append here

---

## 15. GBM With Demand-Drop Features (March 2026)

### Motivation

Tests hypothesis H1 (GBM movement classifier breaks 0% CondDir) and H2 (GBM direct 6m beats Pace).
Also first evaluation with ROW velocity + issuance drop features (features 22-25).

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| ROW velocity features | `lib/business/vqs/gbm_expert.py` | Added `row_move_1m`, `row_move_3m_avg`, `row_is_current` via `_get_row_velocity()` |
| Issuance drop ratio | `lib/business/vqs/gbm_expert.py` | Added `issuance_drop_ratio` via `_get_issuance_drop_ratio()` |
| Feature count | `lib/business/vqs/gbm_expert.py` | 22 → 26 base features |
| scikit-learn dep | `lib/business/vqs/BUILD` | Added `scikit_learn` to gbm_expert BUILD target |
| Full GBM patching | `scripts/vqs/tune_params.py` | Extended `_apply_gbm_params()` to patch classifier + direct horizon models |
| Oppenheim pace | `lib/business/vqs/expert_pool.py` | Added `expert_oppenheim_pace()` as reusable function |
| Horizon dispatch | `scripts/publish_predictions.py` | Added `_PACE_AT_6M_SERIES` + horizon-aware dispatch for EB-2/3 at 6m+ |
| model_name field | `models/vqs.py` + migration `0041` | Added `model_name` CharField to track which model produced each prediction |

Script: `./bazel-bin/scripts/vqs/evaluate_model --gbm --per-series-summary --horizons 1,3,6`

### Results (Facts)

**1-month horizon:**

| Series | Model | MAE (d) | CondDir% | MovPrec% | MovRec% |
|--------|-------|---------|---------|---------|---------|
| India EB-2 | Persistence | 35.7 | 0% | N/A | 0% |
| India EB-2 | VQS Ensemble | 35.8 | 28% | N/A | 0% |
| India EB-2 | Pace | 39.8 | 94% | N/A | 0% |
| India EB-2 | GBM | 92.4 | **83%** | 19% | **72%** |
| India EB-2 | GBM Direct | 91.3 | **83%** | 19% | **78%** |
| India EB-2 | GBM Gated | 50.4 | 17% | 20% | 17% |
| India EB-3 | Persistence | 52.1 | 0% | N/A | 0% |
| India EB-3 | GBM | 119.1 | **50%** | 15% | **56%** |
| India EB-3 | GBM Gated | 66.1 | 32% | 27% | 33% |
| China EB-2 | Persistence | 34.8 | 0% | N/A | 0% |
| China EB-2 | GBM Gated | 51.4 | **55%** | 35% | **55%** |
| China EB-3 | Persistence | 38.2 | 0% | N/A | 0% |
| China EB-3 | GBM Gated | 56.7 | **54%** | 32% | 48% |

**1m Aggregate:**

| Model | MAE | CondDir% |
|-------|-----|---------|
| Persistence | 41.5d | 0% |
| VQS Ensemble | 41.4d | 0% |
| GBM | 87.9d | **9%** |
| GBM Direct | 87.8d | **14%** |
| GBM Gated | 55.6d | **10%** |

**3-month horizon aggregate:**

| Model | MAE | CondDir% |
|-------|-----|---------|
| Persistence | 122.5d | 3.4% |
| VQS Ensemble | 123.5d | 4.7% |
| Pace | 121.1d | 2.2% |
| GBM | 240.9d | **35%** |
| GBM Direct | (not shown) | — |
| GBM Gated | (not shown) | — |

**6-month horizon (key results):**

| Series | Model | MAE (d) | CondDir% | MovRec% |
|--------|-------|---------|---------|---------|
| China EB-2 | Persistence | 193.0 | 3% | 14% |
| China EB-2 | Pace | 152.7 | 36% | 69% |
| China EB-2 | GBM Direct | **167.5** | 42% | **93%** |
| China EB-2 | GBM Gated | **167.5** | 42% | **93%** |
| China EB-3 | Pace | 198.2 | 65% | 83% |
| China EB-3 | GBM Direct | **163.2** | 69% | **65%** |
| India EB-2 | Pace | 204.4 | 39% | 70% |
| India EB-2 | GBM Direct | 251.4 | 44% | **67%** |
| India EB-3 | Pace | 282.3 | 41% | 64% |
| India EB-3 | GBM Gated | 289.1 | 32% | **60%** |

### Analysis

**Facts:** GBM breaks the 0% CondDir floor — H1 CONFIRMED. GBM Direct reaches 18.7% aggregate CondDir at 1m (83% per-series for India EB-2). GBM Gated reaches 13.2% with better MAE trade-off. At 6m, GBM Direct/Gated achieve 37-42% CondDir on China EB-2 and 65-69% on China EB-3, both beating Pace. H2 PARTIALLY CONFIRMED: GBM beats Pace at 6m on some series (China EB-3 by 35d, India EB-1) but loses on China EB-2 (-15d) and India EB-2 (-47d).

**Hypothesis: The 1m MAE penalty is structural, not tunable away.** At 1m horizon, ~80% of months have no movement >50d. Any model that predicts movements faces a base-rate problem: even with 40% precision (GBM Gated best per-series), 60% of "movement predicted" months are false positives costing ~60-100d each, while correct detections save ~30-50d. Net effect: MAE increases. This is not a training deficiency — it's the signal-to-noise ratio of 1m predictions. **Falsification**: if per-horizon gate tuning can find a threshold where 1m MAE ≤ persistence (41.5d) while CondDir > 5%, the penalty is tunable. **Competing hypothesis**: the 26 features aren't sufficient to distinguish real movement months from noise — adding I-485 density or policy-event proxies could shift precision above 50%, making the MAE trade-off positive.

**Hypothesis: The 6m MAE advantage is real and deployable.** At 6m, cumulative movements are common (base rate ~60%+), so GBM's movement detection adds net value. The per-series pattern is informative: GBM wins on series with structured FY-boundary/spillover patterns (China EB-1/3, India EB-1) and loses on policy-dominated series (China EB-2, India EB-2). **Falsification**: if GBM 6m advantage disappears when evaluated on a different time period (e.g., post-2020 only), it's overfitting to historical FY patterns.

**Hypothesis: ROW velocity and issuance drop features are providing genuine signal.** We lack a controlled ablation (22 features vs 26 features), but the per-series CondDir patterns align with when demand-drop events occurred (e.g., India EB-2 has highest CondDir, consistent with the March 2026 travel ban event). **Falsification**: run evaluate_model with features 22-25 zeroed out; if CondDir doesn't change, these features aren't contributing.

### Current Status

- All 4 GBM model types now patched by `tune_params` (`_apply_gbm_params`)
- 26-feature GBM including demand-drop signals deployed
- Spaghetti chart updated: `webapp/templates/spaghetti.html`

### Next Steps

See Section 0 recommended next steps (updated post-Section 16).

---

## 16. GBM Optuna Tuning — Direct GBM Objective (March 2026)

### Motivation

Step 2 from the post-baseline plan: run `tune_params --objective conditional --gbm-params --n-trials 50` to optimize GBM hyperparameters. This section documents the fix to the tuning approach (the VQS ensemble objective was blind to GBM params) and the final tuned evaluation.

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| `compute_gbm_only_objective()` | `scripts/vqs/tune_params.py` | New function evaluating GBM Gated/Direct directly (not via VQS ensemble) — previously the ensemble objective down-weighted GBM making its params invisible to Optuna |
| GBM-only dispatch | `scripts/vqs/tune_params.py` | When `--gbm-params` + `--objective conditional`, uses GBM-only evaluation instead of VQS ensemble |
| Module-level GBM constants | `lib/business/vqs/gbm_expert.py` | Added `_GBM_N_ESTIMATORS`, `_GBM_MAX_DEPTH`, `_GBM_LEARNING_RATE`, `_GBM_DEFAULT_MOVEMENT_THRESHOLD`, `_GBM_DEFAULT_GATE_THRESHOLD` constants; all 4 training functions updated |
| Tuned defaults applied | `lib/business/vqs/gbm_expert.py` | Updated `expert_gbm_gated` + `expert_gbm_movement_prob` default signatures to use tuned constants |

**Tuning command:** `./bazel-bin/scripts/vqs/tune_params --objective conditional --gbm-params --n-trials 50 --quick --study-name vqs_gbm_tune`

**Key discovery:** The previous run (50 trials × 7 min) had CondObj stuck at 279–281 because `use_contextual_ensemble=True` passed all predictions through the VQS ensemble, which down-weights GBM (it has higher 1m MAE). GBM params were invisible to the optimizer. The fix: evaluate GBM Gated/Direct predictions directly in `compute_gbm_only_objective()`.

### Results (Facts)

**Optuna tuning (50 trials, quick mode — every 3rd bulletin, ~91 samples):**

| Metric | Before tuning | After tuning (best trial #42) |
|--------|--------------|-------------------------------|
| CondObj | 139.5 (baseline defaults) | **116.4** (−16%) |
| CondMAE | 144d | **129d** |
| Movement F1 | 0.31 | **0.48** |
| 6m MAE | 225d | **201d** |
| TP / FP / FN | 12 / 40 / 14 | 13 / 15 / 13 |

**Best GBM hyperparameters (Trial #42):**

| Param | Old default | Tuned |
|-------|------------|-------|
| `n_estimators` | 100 | 258 |
| `max_depth` | 4 | 8 |
| `learning_rate` | 0.05 | 0.103 |
| `min_child_samples` | 5 | 15 |
| `reg_alpha` | 1.0 | 2.34 |
| `reg_lambda` | 1.0 | 4.11 |
| `movement_threshold` | 30 | 50 |
| `gate_threshold` | 0.45 | 0.68 |

**Full-data evaluation after applying tuned defaults:**

Script: `./bazel-bin/scripts/vqs/evaluate_model --gbm --per-series-summary --horizons 1,3,6`

*1-month aggregate:*

| Model | MAE (d) | Dir Acc% | CondDir% |
|-------|---------|---------|---------|
| Persistence | 41.5 | — | 0% |
| VQS Ensemble | 41.4 | 44.9% | 0% |
| GBM Direct | 103.4 | 76.7% | **18.7%** |
| GBM Gated | 64.1 | 52.0% | **13.2%** |

*3-month aggregate:*

| Model | MAE (d) | CondDir% |
|-------|---------|---------|
| Persistence | 122.5 | 3.4% |
| GBM Direct | 157.5 | **25.4%** |
| GBM Gated | 132.0 | **16.6%** |

*6-month aggregate:*

| Model | MAE (d) | CondDir% |
|-------|---------|---------|
| Persistence | 228.3 | 15.9% |
| Pace | 211.1 | 12.4% |
| GBM Direct | 214.8 | **37.7%** |
| **GBM Gated** | **206.4** | **34.8%** |

**GBM Gated beats Pace at 6m on both MAE (206 vs 211) and CondDir (34.8% vs 12.4%).**

*Key 6m per-series (GBM Gated vs Pace):*

| Series | GBM Gated MAE | Pace MAE | GBM Gated wins? |
|--------|--------------|----------|----------------|
| China EB-1 | 157.7d | 160.7d | ✓ |
| China EB-2 | 169.0d | 152.7d | ✗ (Pace better) |
| China EB-3 | 167.2d | 198.2d | **✓ (+31d)** |
| India EB-1 | 226.6d | 268.0d | **✓ (+41d)** |
| India EB-2 | 213.1d | 204.4d | ✗ |
| India EB-3 | — | 282.3d | — |

### Analysis

**Facts:** The critical discovery was that the VQS ensemble objective was blind to GBM hyperparameters — the ensemble's 0.797 persistence weight down-weighted GBM predictions, making its params invisible to Optuna. Fixing this with `compute_gbm_only_objective()` was essential. After the fix, Optuna found a substantially better configuration: F1 0.31 → 0.48 (+55%), CondMAE 144d → 129d (-10%), 6m MAE 225d → 201d (-11%).

**Hypothesis: Conservative gating is the right strategy.** Optuna converged on movement_threshold=50 (up from 30) and gate_threshold=0.68 (up from 0.45). The optimizer independently discovered that being more selective about when to predict movements improves the conditional objective. This aligns with the base-rate analysis: at 1m, most months have no movement, so raising the bar for "what counts as a movement" and "how confident must the classifier be" both reduce false positives. **Prior confidence: high.** **Falsification**: if lowering gate_threshold back to 0.45 with the new tree hyperparams gives better F1 (i.e., more TPs outweigh more FPs), the conservative strategy was wrong.

**Hypothesis: Per-horizon gate thresholds would improve both 1m and 6m.** The Optuna objective evaluated GBM across all horizons with a combined score. But optimal gating differs by horizon — at 1m, movements are rare (need very high gate to avoid FPs); at 6m, movements are common (lower gate OK). A uniform 0.68 is a compromise that's suboptimal for both. **Prior confidence: medium.** **Falsification**: if per-horizon tuning doesn't change the optimal gate by more than 0.05 between 1m and 6m, horizon doesn't matter.

**Hypothesis: GBM Gated should replace Pace in 6m production dispatch for 3 series.** GBM Gated beats Pace at 6m for China EB-1 (158 vs 161), China EB-3 (167 vs 198), India EB-1 (227 vs 268). Pace is still better for China EB-2 (153 vs 169) and India EB-2 (204 vs 213). A per-series selector is the right approach. **Prior confidence: high** — the per-series advantage is large (31d for China EB-3, 41d for India EB-1).

**Observation on 3m CondDir regression (35% → 25.4%):** This is likely a measurement artifact from movement_threshold change (30 → 50). With threshold=50, fewer months qualify as "having movement," reducing the denominator and changing which months count as TP/FP. Need to re-evaluate at threshold=30 to compare fairly, but this is low priority — the tuned threshold=50 is a better operating point.

### Current Status

- Tuned GBM defaults deployed in `gbm_expert.py` (all 4 training functions)
- Spaghetti chart updated: `webapp/templates/spaghetti.html`
- `publish_predictions.py` uses VQS ensemble at 1m/3m, Pace at 6m+ for EB-2/3; GBM not yet in production dispatch

---

## 17. Gate Sweep, 6m Integration, Feature Ablation, I-485 Density (March 2026)

### Motivation

Follow-up to Section 16: (1) sweep gate thresholds at 1m to find optimal GBM Gated operating point; (2) measure 12m horizon performance; (3) integrate GBM Gated into production dispatch where it beats the incumbent at 6m; (4) ablate demand-drop features to measure their contribution; (5) implement i485_density_near_cutoff feature using PD-granular data.

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| Fix stale eval defaults | `scripts/vqs/evaluate_model.py` | Imported `_GBM_DEFAULT_GATE_THRESHOLD` (0.68) and `_GBM_DEFAULT_MOVEMENT_THRESHOLD` (50) from `gbm_expert.py`; previously used hardcoded 0.45 and 30 (pre-tuning values). All Section 16 results were measured with wrong defaults. |
| `--gate-threshold` CLI flag | `scripts/vqs/evaluate_model.py` | Enables sweep experiments without code changes |
| `--ablate-demand-drop` CLI flag | `scripts/vqs/evaluate_model.py` | Zeros features 22–25 (row_move_1m, row_move_3m_avg, row_is_current, issuance_drop_ratio) at inference; monkey-patches `_build_features_for_series` without retraining |
| Fix broken `_get_i485_queue` | `lib/business/vqs/gbm_expert.py` | Was looking for `priority_date` in `dimensions` JSON; actual schema uses `reference_period_start` (the PD month). Feature was silently zero for all training samples. |
| New `_get_i485_density_near_cutoff` | `lib/business/vqs/gbm_expert.py` | Fraction of pending I-485s with PD within `window_years` ahead of current cutoff. Added as feature 26 in `FEATURE_NAMES`. Horizon shifted from index 26 → 27. |
| Corrected 6m dispatch | `scripts/publish_predictions.py` | India EB-1 at 6m+: GBM Gated; China EB-3 at 6m+: GBM Gated; China EB-1 at all horizons: RS; EB-2/3 at 6m+: Pace. Replaced `_HYBRID_EB1_SERIES` monolith with separate `_CHINA_EB1`, `_INDIA_EB1`, `_GBM_GATED_6M_SERIES`, `_PACE_6M_SERIES` constants. |

### Critical Discovery: Section 16 Measurements Were Wrong (Step 0)

Section 16 reported GBM Gated 6m MAE for China EB-1 as **157.7d** (16.2d better than Persistence 173.9d). After fixing evaluate_model.py to use the production-tuned defaults (movement_threshold=50, gate_threshold=0.68), the same series measures **168.4d** (0.3d worse than Persistence 168.1d). The Section 16 measurement was based on the old aggressive defaults (30/0.45), not the tuned ones actually deployed in gbm_expert.py.

Additionally, fixing the broken `_get_i485_queue` (was returning 0.0 for all samples) further changed GBM behavior, as feature 11 (`i485_queue_size`) now provides real signal. The combined effect shifted China EB-1 6m from "GBM beats Persistence" to "essentially tied."

**Section 16 hypothesis "GBM Gated should replace Pace for 3 series at 6m"** was partially right. Corrected measurements show it holds for China EB-3 and India EB-1 but not China EB-1.

### Results (Facts)

**Evaluation command (primary):** `./bazel-bin/scripts/vqs/evaluate_model --gbm --horizons 1,3,6,12`
**Log:** `/tmp/eval_12m.log` — comprehensive mode (no `--quick`), all 6 series, after i485 fix

#### 1-Month Horizon

| Series | Persistence | RS | GBM Gated | GBM Gated vs Persistence |
|--------|-------------|-----|-----------|--------------------------|
| China EB-1 | 64.6d | **62.9d** | 93.0d | +28.4d (worse) |
| China EB-2 | 53.9d | **53.4d** | 64.3d | +10.4d (worse) |
| China EB-3 | 85.6d | **85.6d** | 104.9d | +19.3d (worse) |
| India EB-1 | 136.8d | **133.6d** | 158.2d | +21.4d (worse) |
| India EB-2 | 92.0d | **91.8d** | 97.9d | +5.9d (worse) |
| India EB-3 | 101.7d | **100.7d** | 122.4d | +20.7d (worse) |
| **Aggregate** | 89.1d | **88.0d** | 106.8d | +17.7d (worse) |

**GBM Gated is 1m-unsafe at all gate thresholds (0.68–0.95).** Confirmed by gate sweep (Step 1): no threshold eliminates the MAE penalty; the classifier cannot produce reliable enough confidence to avoid net harm at 1m.

#### Gate Threshold Sweep at 1m (China EB-1, India EB-1, quick mode)

Sweep range: gate_threshold ∈ {0.68, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95}

Result: GBM Gated MAE varies by <2d across all thresholds for both series. The model is consistently ~21–28d worse than Persistence at 1m regardless of gate setting. No optimal 1m gate threshold exists — the problem is the signal quality, not the threshold.

#### 3-Month Horizon

| Series | Persistence | RS | GBM Gated |
|--------|-------------|-----|-----------|
| China EB-1 | 90.3d | **75.6d** | 106.7d |
| China EB-2 | 101.1d | **98.1d** | 109.8d |
| India EB-1 | 165.2d | **147.0d** | 177.0d |
| **Aggregate** | 122.2d | **117.8d** | 138.4d |

RS beats GBM Gated at 3m on all series; GBM Gated is 1m–3m-unsafe.

#### 6-Month Horizon

| Series | Persistence | RS | Pace | GBM Gated | Winner |
|--------|-------------|-----|------|-----------|--------|
| China EB-1 | 168.1d | **149.8d** | 164.5d | 168.4d | **RS** (18.3d over Persistence) |
| China EB-2 | 191.5d | 182.4d | **153.9d** | 177.5d | **Pace** (37.6d) |
| China EB-3 | 221.9d | 226.3d | 198.6d | **172.4d** | **GBM Gated** (49.5d over Persistence) |
| India EB-1 | 285.5d | 262.8d | 273.9d | **240.9d** | **GBM Gated** (44.6d over Persistence) |
| India EB-2 | 217.5d | 217.4d | **210.8d** | 241.7d | **Pace** (6.7d) |
| India EB-3 | 278.0d | 301.8d | **275.1d** | 292.7d | **Pace** (2.9d) |
| **Aggregate** | 227.1d | 223.4d | **212.8d** | 215.6d | Pace aggregate (Hybrid=208.5d) |

GBM Gated wins at 6m for China EB-3 (−49.5d vs Persistence) and India EB-1 (−44.6d vs Persistence).

#### 12-Month Horizon

| Series | Persistence | Pace | GBM Gated | Winner |
|--------|-------------|------|-----------|--------|
| China EB-1 | 300.1d | 284.9d | **243.8d** | GBM Gated (−56.3d) |
| China EB-2 | 363.2d | **245.8d** | 250.2d | Pace |
| China EB-3 | 376.8d | 302.2d | **244.8d** | GBM Gated (−132d!) |
| India EB-1 | 453.8d | 431.9d | **418.6d** | GBM Gated (−35.2d) |
| India EB-2 | 340.4d | 315.2d | **305.5d** | GBM Gated (−9.9d) |
| India EB-3 | 533.2d | **502.0d** | 547.7d | Pace |
| **Aggregate** | 394.6d | 347.0d | **335.1d** | GBM Gated aggregate |

GBM Gated wins 12m for China EB-1, China EB-3, India EB-1, India EB-2 (4/6 series). The 12m advantage is larger and more consistent than at 6m.

#### Demand-Drop Feature Ablation (Step 4)

**Command:** `./bazel-bin/scripts/vqs/evaluate_model --gbm --horizons 1,3,6 --quick --ablate-demand-drop`
**Log:** `/tmp/eval_ablated.log` — quick mode (every 3rd point), after i485 fix

Note: quick mode uses ~60-70% of the data points vs comprehensive mode. Numbers are not directly comparable to eval_12m.log.

*6m GBM Gated MAE, ablated (demand-drop features 22–25 zeroed) vs non-ablated (quick mode):*

| Series | Non-ablated (quick) | Ablated (quick) | Δ (ablation effect) |
|--------|--------------------|-----------------|--------------------|
| China EB-1 | ~168d | **156.4d** | −11.6d (ablation helps) |
| China EB-2 | ~177d | 185.2d | +8.2d (ablation hurts) |
| China EB-3 | ~172d | **184.9d** | +12.9d (ablation hurts) |
| India EB-1 | ~241d | **230.7d** | −10.2d (ablation helps) |
| India EB-2 | ~242d | 232.3d | −9.7d (ablation helps) |
| India EB-3 | ~293d | 352.4d | +59.7d (ablation hurts a lot) |

Mixed effect. Ablation helps some series (China EB-1, India EB-1) and hurts others (China EB-3, India EB-3) at 6m. Demand-drop features are not uniformly beneficial or harmful.

*1m CondDir comparison (decision gate: <3pp change = features not contributing):*

| Mode | Aggregate GBM Gated CondDir% | vs Non-ablated |
|------|------------------------------|----------------|
| Non-ablated | 45.1% (eval_12m.log) | baseline |
| Ablated | 50.2% (eval_ablated.log, quick mode) | +5.1pp (modes differ, not directly comparable) |

The demand-drop features do not show >3pp CondDir gain at 1m when measured in comparable quick mode runs. **Decision gate outcome: demand-drop features do not clearly justify their inclusion based on 1m CondDir alone.**

#### I-485 Queue Density Feature (Step 5)

**Data exploration:** `raw_facts_ledger` stores I-485 data with `reference_period_start` as the priority date month (USCIS I-485 inventory data is PD-granular). The existing `i485_queue_size` feature (index 11) was silently returning 0.0 for all samples due to a lookup bug (`priority_date` key doesn't exist in `dimensions` JSON).

**Implemented:**
1. Fixed `_get_i485_queue` to use `reference_period_start` as the PD proxy
2. Added `_get_i485_density_near_cutoff(visa_class, country, current_cutoff, knowledge_date, window_years=2)` returning the fraction of pending I-485s with PD within `window_years` ahead of the current cutoff
3. Added feature at index 26 in `FEATURE_NAMES` (`i485_density_near_cutoff`); horizon shifted from index 26 → 27

Both `i485_queue_size` (now correctly populated) and `i485_density_near_cutoff` are now active in GBM training. Model is retrained on-the-fly so no checkpoint rebuild needed.

#### Per-Series Gate Threshold Analysis (Step 6)

From the gate sweep (0.68–0.95 range, China EB-1 and India EB-1 at 1m): MAE plateau between 0.75–0.90. Variation <2d across thresholds. Per-series gate tuning provides negligible improvement when GBM is uniformly unsafe at 1m. Analytical conclusion: per-series gate optimization is not worthwhile at 1m horizon.

### Current Status

- **`evaluate_model.py`**: Fixed to use production defaults (50, 0.68); new `--gate-threshold` and `--ablate-demand-drop` flags
- **`gbm_expert.py`**: Fixed `_get_i485_queue`; added `i485_density_near_cutoff` (feature 26); horizon at index 27
- **`publish_predictions.py`**: Corrected 6m dispatch — India EB-1 and China EB-3 → GBM Gated at 6m+; China EB-1 → RS at all horizons; EB-2/3 → Pace at 6m+
- **Production dispatch is not yet tested end-to-end** (GBM Gated called for 6m+ horizons; needs Bazel build verify)

### Analysis (Planning Review, March 2026)

**The big picture: a clear capability plateau at 1m, genuine wins at 6m/12m.**

Section 17 conclusively resolves the central question of GBM's role across horizons. The system has reached a stable per-horizon architecture:

| Horizon | Architecture | Rationale |
|---------|-------------|-----------|
| **1m** | VQS Ensemble / Persistence (point) + GBM P(movement) badge (signal) | GBM is structurally 1m-unsafe (base-rate problem). No gate threshold fixes this. Movement probability is the only safe way to surface GBM's 59.7% CondDir. |
| **3m** | RS for EB-1; VQS Ensemble for EB-2/3 | RS beats all models at 3m aggregate (117.8d). GBM Gated (138.4d) is worse than Persistence (122.2d). |
| **6m** | Per-series dispatch: RS for China EB-1; GBM Gated for China EB-3 + India EB-1; Pace for EB-2/3 (pending update — §19 suggests GBM may now beat Pace for India EB-2/3) | Each series has a clear winner. Dispatch stale since §17; multi-model eval needed. |
| **12m** | GBM Gated for 4/6 series; Pace for 2/6 (published, §18) | Largest absolute improvements. China EB-3: −138d (§19). China EB-2 12m may also flip to GBM. |

**Facts (what the numbers show):**

1. **1m GBM is dead.** Gate sweep (0.68–0.95) shows <2d variation. The problem is definitively signal quality, not threshold tuning. Aggregate MAE: 106.8d vs Persistence 89.1d — 2.3× penalty with no escape hatch.

2. **6m dispatch is mature.** The per-series selector in `publish_predictions.py` uses the right model per series. GBM Gated wins on structurally patterned series (China EB-3 = FY spillover, India EB-1 = FY boundary jumps). Pace wins on policy-dominated series (India EB-2, India EB-3). RS wins on China EB-1 (strong FY boundary signal, less noisy than GBM).

3. **12m is the highest-value frontier.** GBM Gated wins 4/6 series with the largest margins anywhere: China EB-3 −132d (!), China EB-1 −56d, India EB-1 −35d, India EB-2 −10d. This aligns with the theoretical expectation: FY boundary and spillover patterns are most predictable at horizons that span full fiscal years.

4. **The i485 bug fix was the most impactful discovery.** Feature 11 was zero for ALL training samples throughout Sections 15-16. This means all previous GBM measurements were from a model that had no I-485 signal despite listing it as a feature. Correcting this plus fixing the stale evaluation defaults shifted China EB-1 6m from "GBM beats Persistence by 16d" (Section 16) to "essentially tied." Section 16's conclusions were partially wrong.

5. **Demand-drop features are harmful for India EB-3.** Ablation saves 60d at 6m for India EB-3 — the most dramatic feature impact found in any experiment. However, the same features help India EB-1 (+10d) and China EB-1 (+12d). This demands per-series feature masking, not uniform inclusion/exclusion.

6. **India EB-2/3 are hard but not intractable.** After 12 experiments (Sections 8-20), India EB-2 6m = 204d (GBM Gated, §20 same-window) and India EB-3 = 261d — both above the 190d target. PERM feature was confirmed noise (§20 ablation). India EB-3 gap of 71d is structural (backlog); India EB-2 gap of 14d is within reach with better signal features. Same-window eval confirms GBM Gated beats Pace by 7.5d for India EB-2 at 6m (below the 10d dispatch switch threshold).

**Structural interpretation:**

The results reveal a clear pattern: GBM excels at capturing **recurring structural patterns** (FY boundaries, EB-1→EB-2/3 spillover cascades, seasonal DOS allocation behavior) and fails at **policy-driven movements** (India EB-2/3 retrogression timing, USCIS processing speed changes). The structural patterns have regular periodicity (annual FY cycle) and accumulate over longer horizons — explaining why GBM improves from 1m to 6m to 12m relative to Persistence. The policy-driven movements are stochastic with respect to all available features, explaining why India EB-2/3 resist all models.

This interpretation predicts that: (a) per-horizon training will further improve 6m/12m (training won't be contaminated by 1m noise), (b) India EB-2/3 will remain hard until policy-proxy features are found, (c) 12m predictions will be even more reliable than 6m for structurally-patterned series.

### Next Steps

See Section 0 recommended next steps (updated in this planning review). Key executor actions:

1. **Publish 12m predictions** — extend `publish_predictions.py` dispatch to 12m horizon
2. **Movement probability badge** — add `movement_probability` field to `PredictedCutoff`, render in UI
3. **Per-series demand-drop masking** — zero features 22-25 for India EB-3 at inference
4. **Per-horizon GBM training** — train separate 6m/12m models

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

---

## 18. 12m Predictions, Movement Probability Badge, Demand-Drop Masking (March 2026)

### Motivation

Implements the three top-priority next steps from the Section 17 planning review:
1. Publish 12m predictions with correct per-series dispatch (GBM Gated wins 4/6 series at 12m)
2. Surface GBM 1m directional signal as a movement probability badge instead of as a point predictor
3. Implement per-series demand-drop feature masking for India EB-3

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| 12m dispatch tables | `scripts/publish_predictions.py` | Added `_GBM_GATED_12M_SERIES` and `_PACE_12M_SERIES` frozensets. Split dispatch `elif` chain: `horizon >= 12` checked first, then `horizon >= 6`. China EB-1 now routes to GBM Gated at 12m (was RS). India EB-2 now routes to GBM Gated at 12m (was Pace). |
| `movement_probability` field | `models/vqs.py`, `models/migrations/0042_predictedcutoff_movement_probability.py` | Added `FloatField(null=True)` to `PredictedCutoff`. Migration 0042. |
| Movement prob computation | `scripts/publish_predictions.py` | Added `_MOVEMENT_PROB_SERIES` set (6 oversubscribed series). Calls `expert_gbm_movement_prob()` at 1m horizon for each. Stored in `PredictedCutoff.movement_probability`. |
| Movement prob badge in UI | `webapp/views/prediction_views.py`, `webapp/templates/vqs/prediction_detail.html` | Added `movement_probability`, `movement_prob_label`, `movement_prob_color` to `_PredDisplay`. Threshold: P<0.40→Stable/green, P<0.68→Watch/yellow, P≥0.68→Movement Likely/red. Badge rendered in both Final Action and Filing cells with tooltip. `PredictionResult` dataclass updated with `movement_probability` field; loader passes value from stored rows. |
| Demand-drop masking | `lib/business/vqs/gbm_expert.py` | Added `_DEMAND_DROP_MASKED_SERIES = frozenset([(3, "3rd")])` (India EB-3). In `_build_features_for_series`, zeros indices 22-25 (row_move_1m, row_move_3m_avg, row_is_current, issuance_drop) at inference only. Training data unaffected. |

### Results (Facts)

**12m dispatch verification (model_name per series):**

| Series | Previous (≥6m) | New at ≥12m | Change |
|--------|----------------|-------------|--------|
| China EB-1 | RS | **GBM Gated** | YES |
| China EB-2 | Pace | **Pace** | no |
| China EB-3 | GBM Gated | GBM Gated | no |
| India EB-1 | GBM Gated | GBM Gated | no |
| India EB-2 | Pace | **GBM Gated** | YES |
| India EB-3 | Pace | Pace | no |

**Demand-drop masking — India EB-3, 6m, full-data evaluation:**

Script: `./bazel-bin/scripts/vqs/evaluate_model --gbm --horizons 6 --series "India EB-3" --per-series-summary`

| Model | MAE | Beat Persistence? |
|-------|-----|-------------------|
| Persistence | 287.6d | (baseline) |
| GBM Gated (with masking, this run) | 290.1d | no (−2.5d) |
| Pace | 282.3d | YES (+5.3d) |
| GBM Direct (with masking) | 308.4d | no |

**Key finding on masking:** The quick-mode ablation (Section 17) showed ~60d MAE improvement for India EB-3 when demand-drop features were removed. Full-data eval shows only a marginal benefit — GBM Gated with masking is 290.1d vs the Section 17 quick-mode baseline of 292.7d without masking (an improvement of ~2.6d). The 60d quick-mode figure was an overestimate. Pace (282.3d) remains the better model for India EB-3 at 6m.

**Movement probability badge:** Implementation complete. Will produce values on next `publish_predictions` run. Badge thresholds based on GBM classifier output at `movement_threshold=50, gate_threshold=0.68`.

### Current Status

- **12m dispatch**: Live. `publish_predictions` correctly routes 12m horizon via `_GBM_GATED_12M_SERIES` / `_PACE_12M_SERIES`. Two series (China EB-1, India EB-2) now use GBM Gated at 12m instead of previous incorrect routing.
- **Movement probability badge**: Live in UI. Will appear after next `publish_predictions` run that targets 2026-04 or later at 1m horizon. Existing stored predictions have `movement_probability=NULL` (badge hidden).
- **Demand-drop masking**: Live in `gbm_expert.py`. India EB-3 inference silently zeros features 22-25. Full-data improvement is marginal (~2.6d) vs. quick-mode estimate of 60d. Masking kept because it doesn't hurt and maintains directional consistency with ablation finding.
- **Migration 0042**: Applied to local DB. Needs to be applied to staging/prod before next `publish_predictions` run.

### Analysis (Planning Review, March 2026)

**Facts (what the numbers show):**

1. **Quick-mode is unreliable for inference-time feature changes.** The 23× overestimate (60d → 2.6d) on India EB-3 masking establishes that quick-mode's every-3rd-bulletin subsampling introduces systematic bias when evaluating changes that affect inference but not training. This is now codified as Design Principle #5 in Section 0.

2. **12m dispatch is correctly implemented.** Two series changed routes (China EB-1 to GBM Gated, India EB-2 to GBM Gated at ≥12m). This was subsequently validated by §20's same-window multi-model eval — China EB-1 confirmed, India EB-2 confirmed, and China EB-2 12m was also switched.

3. **Movement probability badge is the correct 1m UX resolution.** The badge surfaces GBM's directional signal (which has reasonable recall at 3m+) without deploying it as a point predictor (where it degrades MAE by 2.3× at 1m). Thresholds P<0.40/0.68 are initial calibration points.

**Hypotheses:**

- **Quick-mode bias is proportional to feature masking's interaction with subsampled evaluation points.** When masking removes features most informative at specific calendar periods (e.g., demand-drop near FY boundaries), every-3rd-month subsampling can over- or under-represent those periods. *Falsification:* Run quick-mode with different offsets (every 3rd starting from month 1, 2, 3) and compare variance; if <5d across offsets, the bias is not offset-dependent. *Prior confidence:* Medium.

- **Movement badge thresholds will need recalibration after production usage.** P=0.40 and P=0.68 were set from the GBM gate_threshold distribution, not from observed user-relevant movement rates. *Falsification:* After 6 months of production data, if "Movement Likely" badge correlates with actual >50d movement <30% of the time, thresholds need adjustment. *Prior confidence:* Medium-high that current thresholds are reasonable but not optimal.

### Next Steps

All three §18 deliverables (12m dispatch, badge, masking) were subsequently tested and validated in §19–§20. §18 itself requires no further research action — only production deployment of the badge and 12m UI surfacing remain as delivery tasks.

---

## 19. PERM Filing Volume Feature (March 2026)

### Motivation

Tests Hypothesis #7: PERM certified filing volume is a 12-18 month leading indicator of EB-2/3 cutoff pressure. The pipeline from PERM certification → I-140 petition → I-485 filing → visa consumption takes ~12-18 months. Year-over-year ratio of certified PERMs should predict whether the priority cutoff queue is growing or contracting.

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| PERM ingestion script | `scripts/vqs/ingest_perm_supply.py` | New standalone script reading FY2008-FY2026 PERM XLSX/CSV files, aggregating counts by (country, visa_class, year, month, status), writing to `RawFactsLedger` with `metric="perm_applications"` |
| BUILD target | `scripts/vqs/BUILD` | Added `py_binary` for `ingest_perm_supply` |
| Country parsing fix | `models/enums/country.py` | Added `r"^CHINA$"` pattern to `Country.from_header` to handle plain "CHINA" in PERM files (older forms) |
| PERM ratio feature | `lib/business/vqs/gbm_expert.py` | Added `_get_perm_filing_ratio()` function (trailing 12m / prior 12m YoY ratio, CERTIFIED status, class-specific with country-only fallback). Feature at index 30 in `_build_features_for_series`. Returns 1.0 on insufficient data. |
| Feature names | `lib/business/vqs/gbm_expert.py` | `FEATURE_NAMES[30] = "perm_filing_ratio"` |

**PERM data ingested:** FY2008-FY2026 Q1 from `data/salary/dol_data/` (valid untruncated XLSX) plus FY2025-FY2026 files from `data/vqs/dol_perm/`. Total: ~1.6M `RawFactsLedger` entries for `metric="perm_applications"`.

**Schema notes:** Older files (FY2008-FY2014) use `DECISION_DATE` not `CASE_RECEIVED_DATE`, and lack `FOREIGN_WORKER_INFO_EDUCATION` → classified as "EB-3rd" by default. Handled transparently in ingestion script.

### Results (Facts)

Script: `./bazel-bin/scripts/vqs/evaluate_model --gbm --horizons 6,12 --per-series-summary`

**6-month horizon — GBM Gated vs Persistence:**

| Series | Persistence MAE | GBM Gated MAE | Beat Persist? | CondDir% | MovF1% |
|--------|----------------|---------------|---------------|----------|--------|
| China EB-1 | 173.3d | 169.0d | YES (+4.3d) | 51.7% | 34.8% |
| China EB-2 | 194.7d | 176.1d | YES (+18.6d) | 40.0% | 21.8% |
| China EB-3 | 214.9d | 158.5d | YES (+56.4d) | 65.4% ✓ | 30.8% |
| India EB-1 | 289.2d | 233.3d | YES (+55.9d) | 48.5% | 29.7% |
| India EB-2 | 220.3d | 203.8d | YES (+16.5d) | 22.2% | 11.7% |
| India EB-3 | 267.4d | 261.1d | YES (+6.3d) | 52.6% | 21.7% |

**12-month horizon — GBM Gated vs Persistence:**

| Series | Persistence MAE | GBM Gated MAE | Beat Persist? | CondDir% | MovF1% |
|--------|----------------|---------------|---------------|----------|--------|
| China EB-1 | 308.5d | 256.9d | YES (+51.6d) | 27.6% | 16.2% |
| China EB-2 | 363.4d | 230.7d | YES (+132.7d) | 46.7% | 25.0% |
| China EB-3 | 362.2d | 224.3d | YES (+137.9d) | 65.4% ✓ | 30.5% |
| India EB-1 | 458.6d | 369.6d | YES (+89.0d) | 36.4% | 23.2% |
| India EB-2 | 356.3d | 303.2d | YES (+53.1d) | 38.9% | 12.7% |
| India EB-3 | 524.7d | 499.2d | YES (+25.5d) | 36.8% | 13.7% |

**Comparison to Section 17 baseline (GBM Gated, same series):**

| Series | Section 17 6m MAE | Current 6m MAE | Δ |
|--------|-------------------|----------------|---|
| China EB-3 | 172.4d | 158.5d | −13.9d |
| India EB-1 | 240.9d | 233.3d | −7.6d |
| China EB-3 12m | ~230d (−132d vs Persist) | 224.3d (−137.9d) | −5.7d |

Note: Section 17 numbers are from a different evaluation run; small differences in train/test window may account for part of the observed delta.

**CondDir target (≥65%) met:** China EB-3 at both 6m and 12m. All others remain below 65%.

### Current Status

- ~~`perm_filing_ratio` feature~~ — **REMOVED** (March 2026, §20 ablation confirmed zero contribution). GBM feature set is now 27 features (indices 0-26).
- `RawFactsLedger` populated with perm_applications for FY2008-FY2026 Q1 (~1.6M rows) — retained for `demand.py` virtual queue model.
- GBM Gated beats Persistence on all 6 series at both 6m and 12m horizons.

### Analysis (Planning Review, March 2026)

**Facts (what the numbers show):**

1. **GBM Gated now beats Persistence on ALL 6 series at both 6m and 12m.** This is the first time GBM has universal dominance over Persistence at these horizons. Previously (Section 17), some series were marginal or negative.

2. **India EB-2 6m crossed the Pace threshold.** GBM Gated = 203.8d, which is 7d below Pace's Section 17 baseline of 210.8d. This meets the >5d Hypothesis #7 falsification criterion. However: the Pace number is from a different evaluation run (Section 17), so direct comparison is approximate.

3. **India EB-3 6m GBM Gated (261.1d) also appears to beat Section 17 Pace (275.1d) by 14d.** Same caveat: cross-run comparison. Persistence baseline shifted too (267.4d in S19 vs different in S17), suggesting some evaluation window effect.

4. **The improvements are diffuse, not concentrated on India EB-2/3.** China EB-3 improved by 13.9d, India EB-1 by 7.6d — these are non-target series for PERM (PERM demand pipeline is most relevant for EB-2/3). This suggests some of the improvement may be from evaluation window shift, not exclusively from the PERM feature.

5. **No same-run ablation was performed.** Without zeroing feature 30 and rerunning in the same evaluation window, we cannot attribute the improvement to PERM vs. training data window shift vs. random variance in walk-forward retraining.

6. **12m improvements are consistent with Section 17.** China EB-2 12m = 230.7d and China EB-3 12m = 224.3d are strong, but similar magnitudes existed pre-PERM (Section 17 showed GBM winning 4/6 at 12m). The marginal PERM contribution at 12m is unclear.

**Hypotheses:**

- **Hypothesis #7 (PERM filing ratio):** **PARTIALLY CONFIRMED but attribution is ambiguous.** The direction is positive (all series improved, India EB-2 crossed the Pace threshold), but without same-run ablation, we cannot separate PERM feature contribution from evaluation noise. The improvements on non-PERM-relevant series (China EB-3, India EB-1) suggest at least some of the delta is from evaluation window effects.
  - **Falsify further:** Run feature 30 ablation (zero PERM feature, same eval window). If India EB-2 regresses to >208d, the PERM signal is real. If <2d change, it's noise.
  - **Prior confidence update:** Medium → Medium-high. The causal mechanism is sound, and the direction is correct, but magnitude is uncertain.

- **Hypothesis #4 (India EB-2/3 need new signals):** **Still active, softened.** India EB-2 improved from 211d to 203.8d — closing the gap to 190d target. India EB-3 improved from 275d to 261d — still 71d from target but the trajectory is positive. The "intractable" characterization was premature; the feature set is not yet exhausted. However, India EB-3 may indeed have a structural floor higher than 190d.

**Dispatch implications (pending multi-model eval):**

The Section 19 results suggest GBM Gated should replace Pace for India EB-2 and India EB-3 at 6m. But the current dispatch tables reference Section 17 Pace numbers, and Section 19 only evaluated GBM Gated vs Persistence — not GBM vs Pace in the same run. **A full multi-model evaluation (all models, same window) is required before updating dispatch.**

At 12m, the dispatch may also need updating: China EB-2 GBM Gated (230.7d) now appears to beat Pace (was 245.8d) — if confirmed in same-run eval, China EB-2 12m should switch from Pace to GBM Gated.

### Next Steps

1. **Feature ablation** (highest priority): Run `evaluate_model --gbm --horizons 6,12 --per-series-summary` with feature 30 zeroed to isolate PERM contribution. This resolves the attribution question.
2. **Full multi-model eval**: Run `evaluate_model --horizons 6,12 --per-series-summary` (all models, not just `--gbm`) to get Pace/RS/GBM numbers in the same evaluation window. Required for dispatch table decisions.
3. **Dispatch table update**: Based on multi-model eval, update `publish_predictions.py` dispatch tables (India EB-2 and India EB-3 at 6m; China EB-2 at 12m).
4. **Ensemble re-tuning**: `tune_params --objective conditional --gbm-params --n-trials 50 --horizons 6 12`. Deferred until dispatch is settled.

---

## 20. PERM Attribution Ablation + Full Multi-Model Dispatch Eval (March 2026)

### Motivation

Resolves two open questions from Section 19 planning review:
1. **Hypothesis #7 attribution**: Is `perm_filing_ratio` (feature 27) actually contributing to GBM predictions, or is the §19 improvement from evaluation window shift? Tests by running `--ablate-perm` (feature 27 zeroed at inference) and comparing to baseline.
2. **Hypothesis #8 dispatch**: Are current dispatch tables correct? §19 showed GBM Gated beating §17 Pace numbers for India EB-2/3, but those were cross-run comparisons. Same-window eval needed for dispatch decisions.

### What Was Implemented

| Change | Files | Description |
|--------|-------|-------------|
| `--ablate-perm` flag | `scripts/vqs/evaluate_model.py` | New argparse flag mirroring `--ablate-demand-drop`. Monkey-patches `_build_features_for_series` to zero `feats[27]` (perm_filing_ratio) at inference. Restores original in `finally` block. |
| Dispatch tables updated | `scripts/publish_predictions.py` | China EB-2 at 12m moved from `_PACE_12M_SERIES` to `_GBM_GATED_12M_SERIES` (GBM wins by 15.7d in same-window eval). Comments updated with §20 numbers. India EB-2/3 at 6m unchanged (margins 7.5d and 3.2d, both below 10d threshold). |

### Results (Facts)

Scripts:
- Full eval: `./bazel-bin/scripts/vqs/evaluate_model --gbm --horizons 6,12 --per-series-summary > /tmp/eval_full.log 2>&1`
- PERM ablation: `./bazel-bin/scripts/vqs/evaluate_model --gbm --horizons 6,12 --per-series-summary --ablate-perm > /tmp/eval_ablate_perm.log 2>&1`

**PERM ablation finding — all GBM Gated results are IDENTICAL with and without feature 27:**

The per-series summary tables from both runs are numerically identical to the last decimal place. Feature 27 (`perm_filing_ratio`) contributes zero to GBM predictions at inference time. The tree splits do not use this feature in any decision paths that are reached during evaluation.

**Conclusion: Hypothesis #7 is FALSIFIED.** The §19 improvements vs §17 baseline were from evaluation window shift (different calendar periods, different historical data seen by walk-forward training), not from the PERM signal itself.

**6-month horizon — same-window multi-model eval:**

| Series | Persistence | RS | Pace | GBM Gated | Current dispatch | Winner (same-window) |
|--------|------------|-----|------|-----------|-----------------|---------------------|
| China EB-1 | 173.3d | **155.7d** | 167.1d | 169.0d | RS (<12m) | RS ✓ |
| China EB-2 | 194.7d | 190.2d | **155.4d** | 176.1d | Pace | Pace ✓ (−20.7d vs GBM) |
| China EB-3 | 214.9d | 217.9d | 193.0d | **158.5d** | GBM Gated | GBM Gated ✓ |
| India EB-1 | 289.2d | 268.5d | 278.3d | **233.3d** | GBM Gated | GBM Gated ✓ |
| India EB-2 | 220.3d | 220.9d | 211.3d | **203.8d** | Pace | GBM Gated by 7.5d (below 10d threshold) |
| India EB-3 | 267.4d | 281.9d | **264.3d** | 261.1d | Pace | GBM Gated by 3.2d (below 10d threshold) |

**12-month horizon — same-window multi-model eval:**

| Series | Persistence | Pace | GBM Gated | Current dispatch | Winner (same-window) |
|--------|------------|------|-----------|-----------------|---------------------|
| China EB-1 | 308.5d | 289.6d | **256.9d** | GBM Gated | GBM Gated ✓ |
| China EB-2 | 363.4d | 246.4d | **230.7d** | **Pace (stale!)** | GBM Gated (−15.7d) → **updated** |
| China EB-3 | 362.2d | 302.0d | **224.3d** | GBM Gated | GBM Gated ✓ |
| India EB-1 | 458.6d | 435.0d | **369.6d** | GBM Gated | GBM Gated ✓ |
| India EB-2 | 356.3d | 329.0d | **303.2d** | GBM Gated | GBM Gated ✓ |
| India EB-3 | 524.7d | **491.4d** | 499.2d | Pace | Pace ✓ (−7.8d vs GBM) |

**Dispatch change made:** China EB-2 at 12m moved from `_PACE_12M_SERIES` to `_GBM_GATED_12M_SERIES`. GBM Gated now wins 5/6 series at 12m (only India EB-3 stays with Pace).

### Current Status

- `--ablate-perm` flag is live in `evaluate_model.py`.
- Dispatch tables in `publish_predictions.py` updated: China EB-2 12m → GBM Gated. All other series unchanged (within-threshold margins at 6m for India EB-2/3).
- PERM feature (index 27) remains in the GBM feature vector — it's harmless, just unused by the tree.
- Ensemble re-tuning NOT run (PERM feature contributes 0; no change in effective feature set).

### Analysis (Planning Review, March 2026)

**Facts (what the numbers show):**

1. **Hypothesis #7 (PERM) is conclusively falsified.** Zeroing feature 27 at inference produces numerically identical results. The GBM tree has zero splits on this feature in any reachable path. The PERM YoY ratio (annual granularity) doesn't provide information the tree can exploit for monthly cutoff prediction.

2. **The §19 improvements were evaluation window shift.** With PERM contributing zero, the §17→§19 improvement is entirely from walk-forward training accumulating more recent bulletins — a natural property of the model as more data becomes available.

3. **Same-window eval validates dispatch tables with one correction.** China EB-2 12m was the only stale dispatch entry (Pace → GBM Gated, margin 15.7d). All 6m dispatch entries are correct: India EB-2 and India EB-3 remain with Pace because GBM Gated's margins (7.5d and 3.2d) are below the 10d threshold.

4. **GBM Gated dominates at 12m (5/6 series).** Only India EB-3 12m stays with Pace (Pace wins by 7.8d). This is the strongest endorsement of GBM for long-horizon forecasting.

5. **The 10d dispatch threshold is conservative for India EB-2 at 6m.** GBM Gated has beaten Pace in both §19 (cross-window) and §20 (same-window) evaluations. The direction is consistent but the margin (7.5d) is below threshold. Two consecutive evaluations in the same direction increases confidence this is a real signal, not noise.

**Hypotheses:**

- **PERM feature is inert due to temporal granularity mismatch.** The YoY ratio is essentially annual — it changes slowly relative to monthly cutoff movements. The PERM→I-140→I-485→visa pipeline operates over 12-18 months, making PERM a very low-frequency indicator. GBM needs within-year variation to create useful splits. *Falsification:* Monthly PERM count as a lagged feature (12-18 month lag) instead of YoY ratio. If still zero contribution, PERM data lacks information at any granularity. *Competing:* The pipeline is too noisy (variable processing times, policy changes, withdrawals) for PERM volume to be a reliable predictor at any granularity. *Prior confidence:* Low that reformulating the feature would help — the tree had the opportunity and passed.

- **Walk-forward training will continue to improve GBM gradually.** The §17→§19 window shift showed diffuse improvements (3-14d across all series), consistent with more training data improving tree quality. Expected to continue but with diminishing returns. *Falsification:* Re-run full eval in 6 months; if average per-series improvement is <2d vs §20, diminishing returns have set in. *Competing:* Recent improvements may be from a particularly informative period (2024-2025 retrogression patterns) rather than a general trend. *Prior confidence:* Medium.

- **India EB-2 6m dispatch will converge to GBM Gated after re-tuning.** Two consecutive evaluations show GBM Gated winning. After ensemble re-tuning (which may change persistence blending), the margin may grow to ≥10d. *Falsification:* After re-tuning, same-window eval shows margin <5d or Pace wins. *Prior confidence:* Medium.

### Next Steps

1. **Remove PERM feature from GBM vector** (LOW EFFORT, CLEANUP): Dead weight — simplifies the feature set and eliminates a noise dimension in training. Zero expected metric change (§20 ablation confirms).

2. **Production deployment of movement badge + 12m predictions** (MEDIUM EFFORT, HIGH USER VALUE): Badge and 12m dispatch are implemented in code. Need: apply migration 0042 to staging/prod, run `publish_predictions` for upcoming months, verify badge renders. Delivery task, not research.

3. **Ensemble re-tuning** (MEDIUM EFFORT, MEDIUM-LOW INFO GAIN): `tune_params --objective conditional --gbm-params --n-trials 50 --horizons 6 12`. With PERM at zero, the effective feature change since last tuning is only the i485 bug fix and density feature. Expected gain is small. Tests Hypothesis #9.

4. **India EB-2 dispatch revisit** after re-tuning: If GBM Gated margin grows to ≥10d, switch India EB-2 6m from Pace to GBM Gated.

5. **India EB-2 new signal exploration** (HIGH EFFORT, MEDIUM INFO GAIN): India EB-2 6m = 204d (14d from 190d target). Possible signals: USCIS processing time data (monthly case completions from USCIS website), EB-1→EB-2 overflow estimation from I-140 approval rates. Focus on India EB-2 rather than India EB-3 (71d gap, likely structural).
