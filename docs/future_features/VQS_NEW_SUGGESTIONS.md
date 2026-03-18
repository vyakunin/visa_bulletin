# VQS New Suggestions (Post–V3)

**Context:** After implementing the six V2 recommendations (per-class supply, FY seasonality, quarterly I-140 spreading, spillover, retrogression, queue depth calibration), V3 accuracy improved sharply: mean error for recent bulletins (excl. EB4) dropped from ~136 days to ~55 days; over-prediction rate fell from ~60% to ~4%. The model now under-predicts ~72% of the time (conservative bias).

This document proposes **new** improvements to address remaining gaps and edge cases.

---

## 1. EB4 Handling: Exclude or Flag Low-Confidence

**Status: Partially implemented (Mar 2026).** Solver already returns persistence with `confidence="low"` for EB4 in `solver.py`. EB4 is excluded from accuracy metrics. Still published to DB and shown on predictions detail page — pending UI de-emphasis.

**Problem:** EB4 (religious workers, special immigrants) has no I-140 data in the ledger. Predictions are driven only by queue calibration and supply; actual cutoffs are driven by different rules (e.g., special immigrant visa limits, per-country caps for EB4). V3 shows EB4 mean error ~228 days and outliers up to 1977 days (October retrogression).

**Suggestions:**

- **Option A (recommended):** Exclude EB4 from the public prediction API and from accuracy metrics (or compute accuracy separately and report as “EB4: low confidence”). Solver can still return a value for EB4, but the UI/API should label it as “experimental” or “not supported.”
- **Option B:** Add a `confidence` field to the solver result: `high` (EB1–EB3 with I-140 data), `medium` (EB5 if we add data), `low` (EB4, or any series with no I-140 rows). API returns confidence so the front end can hide or de-emphasize EB4.
- **Option C:** Ingest EB4-specific data if USCIS/DOS publish it (different metric/form), then treat EB4 like other classes once data exists.

**Implementation:** In `accuracy_metrics.py`, add `EVALUABLE_VISA_CLASSES_BULLETIN = {"1st", "2nd", "3rd", "5th"}` (drop 4th) for main metrics, and optionally a separate report for 4th. In `vqs_api.py`, if `visa_class == "4th"`, return a flag like `"confidence": "low"` or omit the prediction from the primary response.

---

## 2. Rebalance Supply to Reduce Systematic Under-Prediction

**Problem:** V3 under-predicts ~72% of the time (excl. EB4). That is safer than over-predicting but suggests supply is slightly too low or demand (after calibration) is too high.

**Suggestions:**

- **Seasonality:** Slightly raise Q1 multipliers (e.g. Oct 0.5→0.55, Nov 0.6→0.65, Dec 0.7→0.75) so early-FY supply is a bit higher; or slightly lower Q4 multipliers to avoid over-issuance in the model.
- **Spillover:** Increase `SPILLOVER_BONUS_RATE` from 0.15 to 0.18–0.20, or extend `SPILLOVER_MONTHS` to include June (6) so spillover starts one month earlier.
- **Calibration:** In `calibrate_queue_depth`, use a cap on implied `demand_per_month` (e.g. never more than 2× the observed demand in the queue for that month) so we don’t over-fill and make the model too conservative.
- **Tuning loop:** Run accuracy script with different constants (e.g. 0.15 vs 0.20 spillover, or ±10% on seasonal multipliers), compare mean error and over/under ratio; pick the set that keeps mean error low and brings under-prediction rate closer to 50%.

**Implementation:** Change constants in `estimators.py` (and optionally in `solver.py` for calibration cap). Re-run `compute_prediction_accuracy` and compare `bulletin_accuracy.json` (e.g. mean error and direction breakdown).

---

## 3. Confidence or Uncertainty in API Response

**Status: Partially implemented (Mar 2026).** Calibrated prediction intervals (80% CI) are computed by `calibration.py` using historical signed error distributions stratified by (series, regime, horizon). `confidence_low` and `confidence_high` fields are stored in `PredictedCutoff`. Still pending: display on prediction detail page (Track C1), and per-series confidence level badge (Track C3).

**Problem:** Users and downstream systems don’t know whether a prediction is well-supported (e.g. EB2 India with I-140 data and calibration) or weak (e.g. EB4, or a series with very few I-140 rows).

**Suggestions:**

- Add a **confidence** or **data_quality** field to the API response:
  - `high`: at least N I-140 rows (e.g. N ≥ 10) for (visa_class, country) and not EB4.
  - `medium`: some I-140 data but sparse, or EB5.
  - `low`: no I-140 rows (queue from calibration only) or EB4.
- Optionally add a **prediction_interval**: e.g. “cutoff likely between YYYY-MM-DD and YYYY-MM-DD” by running the solver with supply ±15% and reporting the range (or 25th/75th percentiles from a simple Monte Carlo over supply/demand).

**Implementation:** In `solver.py`, before or after `predict_next_bulletin_and_maturity`, compute a score from `len(facts)` filtered by visa_class/country and metric=i140_receipts. Return it in a small result wrapper. In `vqs_api.py`, add `confidence` (and optionally `interval_low`/`interval_high`) to the JSON response.

---

## 4. More Historical I-140 Data and Refined Lag

**Problem:** Queue depth and calibration rely on limited I-140 history (e.g. one FY file spread across quarters). Older bulletins (2020–2024) still have higher error; more history would improve backtesting and calibration.

**Suggestions:**

- **Ingest all available USCIS I-140 quarterly reports** (FY2020–FY2025+) and any annual summaries, with correct `reference_period_*` and `publication_date` (e.g. quarter end + 90 days). Keep using the existing “spread annual totals across four quarters” and “spread quarter demand across months” logic.
- **Per-category lag:** Replace the single `NAIVE_LAG_MONTHS = 12` with a small table (e.g. EB1: 6 months, EB2: 12, EB3: 18) to reflect different processing times. Optionally derive lags from PERM lag distribution when available (already done for convolution); extend PERM lag to more quarters/years if data exists.
- **Store source and vintage:** In `raw_facts_ledger`, `source` and `reference_period_*` are already there; document which files were ingested so we can add new files without duplicating.

**Implementation:** Add more XLSX/CSV ingestion runs in `ingest_uscis_i140.py` (and any scripts for annual reports). In `demand.py`, introduce `NAIVE_LAG_BY_CLASS = {"1st": 6, "2nd": 12, "3rd": 18, "4th": 12, "5th": 12}` and use it when convolution is not available.

---

## 5. EB1 India–Specific Tweaks

**Problem:** EB1 India has the highest mean error among EB1–EB3 in V3 (~106 days). EB1 has different dynamics (premium processing, company-driven spikes, NIW vs non-NIW).

**Suggestions:**

- **Supply:** Consider a slightly higher per-class share for EB1 (e.g. 0.30 vs 0.286) to reflect spillover from EB2/EB3 to EB1, or add a small “EB1 bonus” in certain months if DOS data suggests it.
- **Calibration:** Use a longer `lookback_months` (e.g. 36) for EB1 India so the historical advancement rate is smoother and less sensitive to recent stalls.
- **Data:** If USCIS publishes EB1 vs EB2/EB3 breakdown by country, ingest it and use it so EB1 India demand is not mixed with EB2/EB3.

**Implementation:** In `estimators.py`, add an optional EB1 bonus (e.g. +5% in months 4–9). In `solver.py`, in `_get_historical_advancement_rate`, pass `lookback_months=36` when `visa_class == "1st"` and `country == Country.INDIA.value`.

---

## 6. Retrogression Magnitude from History

**Problem:** `_RETROGRESSING_SERIES` uses fixed months (e.g. 3 for EB2/EB3 India). Real October retrogression varies by year and series.

**Suggestions:**

- **Historical table:** For each (visa_class, country), compute from bulletin history the typical “cutoff in September vs cutoff in October” delta (in months) for past FY starts. Store in a small config or DB table and use it instead of constants.
- **Fallback:** Keep current constants as fallback when history has fewer than 3 October transitions.

**Implementation:** Add a script or function that, for each series, queries VisaCutoffDate for September and October bulletins across years, computes the backward step in months, and writes a JSON/YAML used by the solver. Solver loads this map and uses it in `run_monthly_loop` when applying retrogression.

---

## 7. Long-Term “Final Ready Date” Metric Improvements

**Problem:** Long-term accuracy has many `no_prediction` (no facts for that knowledge date). Mean error among “ok” rows is still high for some series.

**Suggestions:**

- **Report by series and horizon:** Break long-term accuracy into buckets: e.g. 1–3 months ahead, 3–6 months, 6–12 months, and by (visa_class, country). This shows where the model is reliable for “when will my date become current.”
- **Confidence in long-term:** For long-term predictions, set confidence to `low` when the prediction horizon is >12 months or when I-140 data is sparse.

**Implementation:** In `accuracy_metrics.py`, when writing `longterm_accuracy.json`, add columns or a separate summary: `horizon_months` (e.g. 1–3, 3–6, 6–12, 12+), and optionally `confidence`. Add a small analysis script that aggregates long-term error by horizon and series.

---

## 8. Documentation and Runbook

**Status: Mostly done.** `docs/PREDICTIONS_ASSESSMENT.md` serves as the research log (see `.cursor/rules/vqs_research_log.mdc`). `lib/business/vqs/README.md` has the "how to improve accuracy" section. `VQS_RUNBOOK.md` has operational commands.

**Remaining:**

- Keep `PREDICTIONS_ASSESSMENT.md` updated with each experiment (numbered sections).
- Keep `lib/business/vqs/README.md` current when adding components.

---

## 9. Tabular ML Model

**Status: Implemented (Mar 2026).** `lib/business/vqs/gbm_expert.py` implements a LightGBM expert trained on pooled tabular features per (series, knowledge_date): recent movements, I-140 demand ratio, I-485 queue depth, cross-series EB-1 signal (1m/3m/regime), seasonal, and FY features. Walk-forward trained each month. Integrated into the expert pool as the `gbm` expert. Extracted from `SMART_PREDICTIONS_PROPOSALS.md` before deletion.**

**Problem:** VQS is physics-based (queue simulation). An alternative is a direct tabular ML model that learns from features without a simulation engine. This was considered but not pursued — VQS was built instead.

**Approach:**

- **Model:** Gradient Boosting (XGBoost/LightGBM/CatBoost) on tabular features: autoregressive (last N cutoff movements, retrogression count, months since "Current"), calendar (FY month, fiscal year), supply (FY cap, DOS issuance), demand (I-140 receipts mapped via PERM lag), cross-series (ROW movement for India series).
- **Target:** Movement in days (next bulletin cutoff - current cutoff). Or directly predict maturity date for a given priority date.
- **Loss:** MAE or Huber on movement; optionally quantile loss (pinball at 0.1, 0.5, 0.9) for uncertainty ranges.
- **Training:** Temporal split (train on years before T, test on T+1). Monthly retraining when new bulletin ingested.
- **Data scale:** ~10K samples, 20-50 features — well-suited for tree-based models.
- **Feature store:** One row per (visa_class, country, action_type, bulletin_month) with all features aligned.

**Why not pursued:** VQS (physics-based simulation) was chosen for interpretability and because the queue metaphor directly models the visa system. The tabular approach could be a complementary "ensemble member" or a separate baseline to test whether learned features outperform hand-tuned simulation parameters.

**When to revisit:** If VQS accuracy plateaus and more data sources are ingested (DOS issuance, pending I-485, USCIS processing times), a tabular model could use these as features directly without the simulation scaffolding.

---

## 10. Community Prediction Methodologies as Baselines

**Status: Partially implemented (March 2026). Pace and Demand-Supply baselines added to `evaluate_model.py`.**

**PhoenixCTB (demand-supply heuristic):** Balances I-140 demand against FY visa cap, using PERM lag to map receipt dates to priority dates. Currently implemented with hardcoded demand constants; needs real I-140 data for accuracy.

**Charlie Oppenheim (constant-pace):** Extrapolates at recent 6-month advancement rate. Implemented as "Pace" baseline.

**"My EB3 ROW" Reddit prediction:** Long-horizon directional prediction (May 2023 FAD by end FY2026). Roughly correct — reached June 2023 by March 2026. This type of long-horizon, directional prediction is not currently evaluated by our metrics (which focus on 1/3/6-month horizons).

**References:**
- PhoenixCTB: https://www.reddit.com/r/USCIS/comments/1o1tez6/comment/niiym7f/
- "My EB3 ROW": https://www.reddit.com/r/USCIS/comments/1fztc54/my_eb3_row_visa_bulletin_prediction/
- Charlie Oppenheim: https://youtu.be/mzcfk7RDq5M

---

## Priority Order (Suggested)

| Priority | Suggestion | Status | Effort | Impact |
|----------|------------|--------|--------|--------|
| ✅ Done | GBM expert (9) | Implemented in gbm_expert.py | — | LightGBM as ensemble member |
| ✅ Done | Calibrated intervals (3) | 80% CI in calibration.py, stored in DB; displayed on prediction detail | — | — |
| ✅ Done | EB4 low-confidence flag (1) | Solver returns confidence=low; Experimental badge on UI | — | — |
| ✅ Done | EB4 UI de-emphasis (1) | Experimental badge + muted row style on prediction detail | — | — |
| ✅ Done | Display confidence intervals (3) | CI range shown below predicted date on prediction detail | — | — |
| ✅ Done | Rebalance supply (2) | Spillover 0.15→0.20, seasonal multipliers +0.05 (Oct–Feb) | — | Verified: 2025+ under-prediction rate 42% (down from 72%) |
| ✅ Done | Full I-140 ingestion for demand-supply baseline (8) | Real I-140 data from RawFactsLedger in evaluate_model.py | — | — |
| ✅ Done | More I-140 data (4) | FY2014–FY2025 complete in raw_facts_ledger (576 rows) | — | Already ingested in Phase 1 |
| ✅ Done | Retrogression from history (6) | `get_retrogression_months_from_history()` in solver.py uses VisaCutoffDate; `_RETROGRESSING_SERIES` is fallback only | — | Already done in Phase 1 |
| ✅ Done | EB1 India tweaks (5) | `lookback_months_eb1_india` 24→36; +5% supply bonus Apr–Sep already in estimators.py | — | Regime-Switched beats persistence at all horizons |
| ✅ Done | Long-term metric breakdown (7) | Horizon-stratified summary in longterm_accuracy_summary.json | — | Already implemented |
---

## How to Re-Run Accuracy After Changes

```bash
# Clear checkpoint to force full recompute
rm -f /tmp/vqs_ckpt/bulletin_accuracy_ckpt.json /tmp/vqs_ckpt/longterm_*.json

# Run accuracy (bulletin + long-term)
bazel run //scripts/vqs:compute_prediction_accuracy -- \
  --metric both --plot \
  --output-dir /tmp/vqs_accuracy_v4 \
  --checkpoint-dir /tmp/vqs_ckpt

# Compare direction and mean error (e.g. recent 2025-10+, excl. EB4)
python3 -c "
import json
with open('/tmp/vqs_accuracy_v4/bulletin_accuracy.json') as f:
    rows = json.load(f)
valid = [r for r in rows if r['error_days'] is not None]
recent = [r for r in valid if r['bulletin_date'] >= '2025-10-01' and r['visa_class'] != '4th']
over = sum(1 for r in recent if r.get('predicted_cutoff') and r.get('actual_cutoff') and r['predicted_cutoff'] > r['actual_cutoff'])
under = sum(1 for r in recent if r.get('predicted_cutoff') and r.get('actual_cutoff') and r['predicted_cutoff'] < r['actual_cutoff'])
exact = sum(1 for r in recent if r.get('predicted_cutoff') and r.get('actual_cutoff') and r['predicted_cutoff'] == r['actual_cutoff'])
n = len(recent)
print(f'Recent (excl EB4): n={n}, mean_err={sum(r[\"error_days\"] for r in recent)/n:.1f}d')
print(f'Over={over} ({100*over/n:.1f}%) Under={under} ({100*under/n:.1f}%) Exact={exact}')
"
```
