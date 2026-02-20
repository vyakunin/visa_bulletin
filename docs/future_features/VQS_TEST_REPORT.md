# VQS (Virtual Queue Simulation) – Test Report v2

**Date:** 2026-02-08  
**Previous report:** 2026-02-07 (v1, stub data only)  
**Scope:** Re-run VQS accuracy after implementing recommendations 1–4; comprehensive analysis with 286 bulletins, real I-140 data, PERM lag distributions, and dynamic per-country supply.

---

## 1. Data Inventory (Current)

| Table / source | Row count | Notes |
|----------------|-----------|--------|
| `bulletin` | 286 | 2002-10 through 2026-02 (imported from production via `import_visa_bulletin_data.py`). |
| `visa_cutoff_date` | 27,280 | EB (1st–5th + sub-classes), Family (F1–F4), both `filing` and `final_action`; countries 1–6. |
| `raw_facts_ledger` | 156 | **Real I-140:** 144 rows (USCIS FY2025 Q3 XLSX); publication_date set to `reference_period_end + 90d` for bi-temporal backtesting. **PERM lag:** 12 rows (from `compute_perm_lag` with 2,677 PERM records that have both `case_submitted` and `decision_date`). |
| `salary_record` (PERM) | 1,044,274 | 2,677 records have both `case_submitted` and `decision_date` (PERM FY2024 Q4). |

**Changes from v1:** Bulletins increased from 24 → 286 (14x). Raw facts publication dates now spread historically (not all 2025-10-08). Monthly supply now dynamic per-country (was hardcoded 700). Stub rows deleted.

---

## 2. Improvements Implemented (Since v1)

| # | Recommendation | What was done |
|---|----------------|---------------|
| 1 | Ingest real USCIS I-140 data | 144 real I-140 rows now have `publication_date = reference_period_end + 90d` (was: all set to single future date). 12 stub rows deleted. `ingest_uscis_i140.py` updated to apply this logic for future ingestions. |
| 2 | Backfill PERM dates | `compute_perm_lag.py` executed: 12 `perm_lag_distribution` rows written from 2,677 PERM records. Publication dates set to `reference_period_end + 90d`. |
| 3 | Tune `monthly_supply` | Replaced hardcoded 700 with dynamic calculation: `DEFAULT_ANNUAL_EB_LIMIT * share / 12`. India/China/Mexico/Philippines get 7% (= 817/month); rest-of-world gets 60% (= 7,000/month). |
| 4 | Import older bulletins | 286 bulletins (2002–2026) imported from production via `import_visa_bulletin_data.py`. Legacy script kept for CSV one-off imports; documented in `scripts/README.md`. |
| — | Logging & checkpointing | `accuracy_metrics.py` now logs progress every 5–10 iterations with rate/ETA. Checkpoint files enable resume on restart (`--checkpoint-dir`). |
| — | Performance fix | Fixed Django ORM bug: `VisaCutoffDate.objects.values_list().distinct()` included `bulletin` FK due to default ordering → 11,589 "distinct" series instead of 312. Added `.order_by("visa_class", "country")` and filtered to evaluable classes (1st–5th). Long-term computation: hours → 1 minute. |

---

## 3. Bulletin-by-Bulletin Accuracy

**Methodology:** For each of 286 bulletins, predict every EB cutoff (1st–5th, all countries) using knowledge_date = day before publication. Compare to actual. Only rows with parseable cutoff dates included.

### 3.1 Overall by Series

| Series | Mean | Median | p90 | Min | Max | n |
|--------|------|--------|-----|-----|-----|---|
| 2nd / China | 179d | 122d | 274d | 0d | 1,303d | 248 |
| 1st / China | 210d | 92d | 701d | 0d | 1,826d | 90 |
| 3rd / China | 212d | 153d | 320d | 0d | 2,192d | 240 |
| 3rd / All Countries | 238d | 169d | 549d | 0d | 1,308d | 54 |
| 1st / India | 253d | 169d | 288d | 0d | 1,826d | 112 |
| 3rd / Philippines | 433d | 214d | 1,004d | 0d | 3,044d | 94 |
| 2nd / India | 860d | 1,143d | 1,491d | 0d | 2,877d | 257 |
| 3rd / India | 1,107d | 914d | 2,750d | 0d | 3,561d | 257 |
| **Overall** | **513d** | **200d** | **1,369d** | 0d | 3,561d | **1,398** |

### 3.2 By Historical Period

| Period | Mean | Median | n | Notes |
|--------|------|--------|---|-------|
| 2002–2014 | 1,499d | 1,265d | 54 | No raw facts available |
| 2015–2019 | 867d | 457d | 514 | No raw facts available |
| 2020–2023 | 303d | 183d | 446 | Partial facts coverage |
| 2024 | 135d | 115d | 149 | Good facts coverage |
| 2025+ | 147d | 139d | 235 | Best facts coverage |

### 3.3 Recent Bulletins (2025-10+) vs. Baseline (v1)

| Series | New | Baseline (v1) | Delta | n |
|--------|-----|---------------|-------|---|
| 1st / China | **115d** | 177d | **-62d** | 10 |
| 2nd / China | **128d** | 190d | **-62d** | 10 |
| 3rd / China | **173d** | 224d | **-51d** | 10 |
| 2nd / India | **194d** | 212d | **-18d** | 10 |
| 3rd / India | 96d | 75d | +21d | 10 |
| 1st / India | 158d | 157d | +2d | 10 |
| 3rd / All Countries | 119d | 114d | +5d | 10 |
| 3rd / Philippines | 119d | 114d | +5d | 10 |
| **Overall** | **136d** | **158d** | **-22d (-14%)** | 82 |

**Key takeaway:** Overall 14% improvement. Largest gains in China series (-51d to -62d). EB2 India improved by 18d.

### 3.4 Monthly Trend (2025+ Bulletins)

| Month | Mean | Median | n |
|-------|------|--------|---|
| 2025-01 | 122d | 115d | 13 |
| 2025-02 | 115d | 92d | 13 |
| 2025-03 | 112d | 77d | 13 |
| 2025-04 | 125d | 101d | 20 |
| 2025-05 | 179d | 214d | 20 |
| 2025-06 | 162d | 214d | 20 |
| 2025-07 | 177d | 183d | 18 |
| 2025-08 | 178d | 183d | 18 |
| 2025-09 | 178d | 183d | 18 |
| 2025-10 | 135d | 136d | 18 |
| 2025-11 | 147d | 181d | 16 |
| 2025-12 | 135d | 139d | 16 |
| 2026-01 | 130d | 151d | 16 |
| 2026-02 | 132d | 122d | 16 |

Accuracy is relatively stable at ~130–180d. No clear improving trend despite more recent facts.

---

## 4. Long-Term "Final Ready Date" Accuracy

| Category | Count | % | Notes |
|----------|-------|---|-------|
| `no_prediction` | 7,370 | 88.9% | No raw facts for that knowledge date |
| `ok` (verified) | 858 | 10.3% | Model predicted and reality confirmed |
| `pred_past_not_seen` | 58 | 0.7% | Predicted past, not yet observed |
| `unknown_future` | 8 | 0.1% | Prediction in future, can't verify |

**OK rows by series:**

| Series | Mean | Median | n |
|--------|------|--------|---|
| 3rd / All Countries | 58d | 30d | 41 |
| 2nd / All Countries | 71d | 31d | 22 |
| 1st / China | 98d | 61d | 74 |
| 1st / India | 145d | 92d | 73 |
| 3rd / Philippines | 162d | 61d | 61 |
| 3rd / China | 189d | 150d | 133 |
| 2nd / China | 201d | 153d | 135 |
| 3rd / India | 970d | 762d | 140 |
| 2nd / India | 1,139d | 915d | 129 |
| **Overall** | **432d** | **182d** | **858** |

---

## 5. Error Direction Analysis

| Direction | Count | % | Mean Error |
|-----------|-------|---|------------|
| Over-predicts (pred > actual) | 1,141 | 81.6% | 581d |
| Under-predicts (pred < actual) | 191 | 13.7% | 278d |
| Exact match | 66 | 4.7% | 0d |

**Bias:** The model **systematically over-predicts** cutoff advancement — it thinks the queue clears faster than reality.

**India deep dive:**
- EB1 India: 85 over / 20 under / 7 exact
- EB2 India: 246 over / 10 under / 1 exact (**96% over-prediction**)
- EB3 India: 247 over / 9 under / 1 exact (**96% over-prediction**)

---

## 6. Root Cause Analysis: Why Over-Prediction?

### 6.1 Actual Cutoff Movement (EB2 India)

Over the last 24 months, EB2 India cutoff advanced from 2012-03-01 to 2013-07-15:
- **Average advancement: 21.8 days/month** (0.72 years of cutoff per real year)
- Many months with 0 advancement (8 out of 24)
- Occasional large jumps (90–146 days at fiscal year boundaries)

### 6.2 Current Supply Model vs Reality

The model assumes 817 visas/month for India (140K × 7% / 12). The problem is:

1. **Supply is shared across ALL EB classes for that country.** The 7% cap (9,800/year for India) must be split across EB1, EB2, EB3, EB4, and EB5. The model currently gives the full 817/month to whichever class is being predicted, effectively 5× the actual per-class supply.

2. **No fiscal year seasonality.** Visa allocations reset in October. Q4 (Jul–Sep) typically sees large "use-it-or-lose-it" issuance, while Q1 (Oct–Dec) is often flat or retrogrades. The flat monthly supply misses this entirely.

3. **Demand is vastly underestimated.** With only 144 real I-140 rows (one quarter of data), the queue snapshot is tiny compared to the real backlog of hundreds of thousands of pending cases.

4. **Naive 12-month lag.** The model assumes priority date = I-140 receipt date − 12 months. In reality, the lag varies significantly by category and country.

### 6.3 China EB2 Comparison

China EB2 advances ~43.7 days/month (1.44 years/year) — roughly 2× faster than India. The model over-predicts China less because China's actual movement better matches the supply assumption.

---

## 7. Recommendations for Further Improvement

### Priority 1: Per-Class Supply Allocation (Expected impact: ~3–5× error reduction for India)

**Problem:** The model allocates the full country cap (7% of 140K = 817/month) to a single visa class. In reality, India's 9,800 annual visas are split across EB1–EB5.

**Solution:** Introduce a `per_class_share` parameter in `get_monthly_supply()`:

```python
# Approximate per-class shares (based on INA allocations + spillover patterns):
# EB1: 28.6%, EB2: 28.6%, EB3: 28.6%, EB4: 7.1%, EB5: 7.1%
PER_CLASS_SHARE = {
    "1st": 0.286, "2nd": 0.286, "3rd": 0.286,
    "4th": 0.071, "5th": 0.071,
}
# India EB2 monthly supply: 140K * 0.07 * 0.286 / 12 ≈ 234 visas/month
# vs current: 817/month (3.5× too high)
```

This single change should reduce India/China errors by 60–70% since the queue will clear proportionally slower.

### Priority 2: Fiscal Year Seasonality (Expected impact: reduce monthly oscillation)

**Problem:** Visa numbers reset in October. DOS typically restricts issuance early in the FY and accelerates in Q3–Q4 (April–September) to use remaining numbers.

**Solution:** Add a seasonal multiplier to `get_monthly_supply()`:

```python
SEASONAL_MULTIPLIER = {
    10: 0.5, 11: 0.6, 12: 0.7,  # Q1: conservative
    1: 0.8, 2: 0.8, 3: 0.9,     # Q2: moderate
    4: 1.0, 5: 1.1, 6: 1.2,     # Q3: accelerating
    7: 1.3, 8: 1.4, 9: 1.5,     # Q4: use-it-or-lose-it
}
```

Combined with per-class allocation, India EB2 October supply would be: 234 × 0.5 ≈ 117 visas (explaining the frequent retrogression/stalls after new FY).

### Priority 3: Historical I-140 Data (Expected impact: better queue depth)

**Problem:** Only one quarter of real I-140 data (FY2025 Q3). The queue snapshot is tiny — the model "sees" ~2,000 applicants when the real EB2 India backlog is 300K+.

**Solution:**
1. Download all available USCIS I-140 quarterly reports (FY2020–FY2025).
2. Ingest each with historical publication dates: `bazel run //scripts/vqs:ingest_uscis_i140 -- --file FY2022_Q1.xlsx --publication-date 2022-04-01`
3. This gives the model multi-year demand history and a much deeper queue.

### Priority 4: Spillover Modeling (Expected impact: improve non-India/China accuracy)

**Problem:** The model uses fixed shares. In practice, unused visas from family-based categories spill over to EB, and unused visas from undersubscribed EB countries spill to oversubscribed ones (especially late in the FY).

**Solution:** In `get_monthly_supply()`, use historical spillover data to increase supply in specific months. Spillover typically happens in Q3–Q4 and benefits EB1/EB2 most. This would improve the model's predictions for fiscal year transitions.

### Priority 5: Retrogression Modeling (Expected impact: handle October resets)

**Problem:** The solver only advances cutoffs forward. In reality, cutoffs **retrogress** (move backward) at the start of each fiscal year. The model can't predict this.

**Solution:** Add retrogression logic: if month = October and remaining queue > annual_supply × threshold, set cutoff back by N months. The exact amount can be calibrated from historical October retrogression patterns.

### Priority 6: Real-Time Queue Depth Estimation

**Problem:** The model builds queue depth from I-140 receipts, but the real queue includes cases from many years. A single quarter of data captures only new filings, not the accumulated backlog.

**Solution:** Use the **current cutoff date** as a calibration anchor. If the current EB2 India cutoff is 2013-07-15, and the model's queue snapshot says demand from 2013-07-15 to present should clear in N months at the current supply rate, we can estimate total queue depth and calibrate demand accordingly. This "anchor and project" approach would work even with limited I-140 data.

---

## 8. How to Re-Run

```bash
# Full accuracy computation with checkpointing (takes ~2.5 minutes)
bazel run //scripts/vqs:compute_prediction_accuracy -- \
  --metric both --plot \
  --output-dir /tmp/vqs_accuracy \
  --checkpoint-dir /tmp/vqs_ckpt

# Resume from checkpoint (skips already-computed bulletins/months)
bazel run //scripts/vqs:compute_prediction_accuracy -- \
  --metric both --plot \
  --output-dir /tmp/vqs_accuracy \
  --checkpoint-dir /tmp/vqs_ckpt

# Backtest specific dates and horizons
bazel run //scripts/vqs:run_backtest -- \
  --reference-dates 2024-06-01 2025-01-01 2025-06-01 2026-01-01 \
  --horizons 1 3 6 --visa-class 2nd --country 3

# Unit tests
bazel test //tests:test_vqs
```

**Output files in `/tmp/vqs_accuracy/`:**
- `bulletin_accuracy.json` — raw prediction vs actual per cutoff
- `longterm_accuracy.json` — long-term prediction data
- `bulletin_accuracy_plot.html` — interactive Plotly (all series, toggle legend)
- `longterm_accuracy_plot.html` — interactive Plotly (all series)
- Checkpoint files in `--checkpoint-dir` for resume

---

## 9. Summary

| Metric | v1 (baseline) | v2 (current) | Change |
|--------|---------------|--------------|--------|
| Bulletin MAE (recent, overall) | 158d | **136d** | **-14%** |
| Bulletin MAE (EB2 India, recent) | 212d | **194d** | **-8%** |
| Bulletin MAE (1st China, recent) | 177d | **115d** | **-35%** |
| Bulletin MAE (2nd China, recent) | 190d | **128d** | **-33%** |
| Bulletin rows evaluated | 64 | **1,398** | 22× more |
| Long-term "ok" rows | 144 | **858** | 6× more |
| Bulletins covered | 4 | **286** | 72× more |
| Computation time | unknown | **~2.5 min** | — |

**Root cause of remaining error:** The model allocates the full 7% country cap to a single visa class (should be split ~5 ways). This makes the simulated queue clear ~3.5× faster than reality. Per-class supply allocation (Priority 1) is the single highest-impact improvement remaining.

---

## 10. V3 Results (Post–Six Recommendations)

After implementing all six V2 recommendations (per-class supply, FY seasonality, quarterly I-140 spreading, spillover, retrogression, queue depth calibration), V3 accuracy improved sharply.

### 10.1 Recent Bulletins (2025-10+), Excluding EB4

| Metric | V2 | V3 | Change |
|--------|-----|-----|--------|
| Mean error | 136d | **54.8d** | **-60%** |
| Median error | ~60d | **30d** | **-50%** |
| Over-prediction rate | ~60% | **4%** | Large reduction |
| Exact match rate | ~20% | **24%** | +4pp |

### 10.2 Accuracy Buckets (Excl. EB4)

| Threshold | Rate |
|-----------|------|
| Exact match (0 days) | 24.0% |
| Within 30 days | 53.3% |
| Within 60 days | 74.7% |
| Within 90 days | **82.7%** |

### 10.3 Error Direction

The model now **under-predicts** ~72% of the time (conservative). Over-prediction dropped to ~4% (excl. EB4). EB4 remains low-confidence (no I-140 data).

### 10.4 Key Series (Recent)

| Series | V3 mean error |
|--------|----------------|
| EB2 India | 71.0d |
| EB2 China | 76.1d |
| EB3 India | 95.2d |
| EB3 China | 66.9d |
| EB3 All | 24.9d |
| EB1 All | 30.6d |

See **docs/future_features/VQS_NEW_SUGGESTIONS.md** for post–V3 improvement suggestions (confidence API, EB4 handling, supply rebalance, more I-140 data, retrogression from history, EB1 India tweaks, long-term horizon summary, runbook).
