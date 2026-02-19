# Smart Predictions for Visa Bulletin / Green Card Readiness

Design document for predicting visa bulletin cutoffs and application maturity dates, using all available public data and a machine-learned model as the main approach.

---

## 1. Goals

**Primary product goals:**

1. **Predict the next bulletin numbers** — For each (visa category, visa class, country, action type), predict the **cutoff date** (or “Current” / “Unavailable”) that will appear in the **next** visa bulletin (and optionally in future bulletins). This answers: “What will the chart look like next month?”

2. **Predict maturity date for any application** — Given a user’s **priority date** and their (visa class, country, action type), predict the **date when their priority date will become current** (maturity date). This answers: “When can I expect to file I-485 or receive a visa number?” and is the main user-facing “green card readiness” prediction.

Both goals are related: accurate next-bulletin predictions imply better maturity-date estimates (by projecting the series forward); conversely, maturity-date error can be used as a loss signal to train a model that also produces bulletin-level forecasts.

---

## 2. Current Approach and Data in the DB

### 2.1 Data currently stored and used

**Models:**

- **Bulletin** — One row per monthly visa bulletin. Fields: `publication_date` (first day of month), `url`, `fetched_at`. Table: `bulletin`.
- **VisaCutoffDate** — One row per (bulletin, visa_category, visa_class, action_type, country). Fields: `cutoff_value` (raw: date string, "C", or "U"), `cutoff_date` (parsed date or NULL), `is_current`, `is_unavailable`. Table: `visa_cutoff_date`. Unique on `(bulletin, visa_category, visa_class, action_type, country)`.

**Scope:**

- **Visa categories:** Family-Sponsored, Employment-Based.
- **Countries:** All (ROW), China, India, Mexico, Philippines, El Salvador/Guatemala/Honduras (6).
- **Action types:** Final Action, Dates for Filing (2).
- **Visa classes:** Per category (e.g. EB-1, EB-2, EB-3, EB-4, EB-5; F1, F2A, F2B, F3, F4). Dashboard uses data with `bulletin.publication_date >= 2013-01-01` for display.

**Approximate scale:**

- Bulletins: ~12 per year; history from ~2013 → on the order of **~120–150 bulletin months**.
- Cutoff rows per bulletin: (visa_classes × countries × 2 action_types) per category. With ~10 EB classes × 6 countries × 2 ≈ 120, plus family → **roughly 200–400 rows per bulletin**, so **~25K–60K VisaCutoffDate rows** total (order of magnitude).

### 2.2 Current prediction logic

**Location:** `lib/business/bulletin/cutoff_projection.py`; called from `lib/business/bulletin/cutoff_data_aggregator.py` when building dashboard data.

**Inputs:** For a single (visa_class, country, action_type) series: list of `publication_date`s and list of `cutoff_date`s (None for U/C), plus user’s **submission_date** (priority date).

**Algorithm:**

1. Use only **last 12 months** of (publication_date, cutoff_date) points (excluding None).
2. **Primary:** Compute linear rate: `avg_days_per_month = (last_cutoff - first_cutoff).days / months_elapsed`. If `last_cutoff >= submission_date` → return “current”. If `avg_days_per_month <= 0` → go to step 3.
3. **Fallback:** `calculate_historical_linear_regression()` on **all** valid points (min 6): fit line (pub_date → cutoff_date), extrapolate when cutoff reaches submission_date; return projected publication date and months_to_wait.
4. **Output:** `status` (current / no_movement / projected), `estimated_date`, `months_to_wait`, `avg_progress_days_per_month`.

**What it does not use:** Fiscal year, visa quota, issuance data, demand data (I-140, I-485), retrogression flags, “Current” handling in rate calculation, or any exogenous features.

---

## 3. Proposed Approaches by Reddit Users

### 3.1 Demand/supply + PERM lag (e.g. PhoenixCTB, “My EB3 ROW” analysis)

**Idea:** Use USCIS demand-side data and FY supply assumptions to explain how much the Final Action Date (FAD) can move, then project FAD (and thus maturity for a given PD).

**Data used:**

- **I-140 receipts by class and country** (FY/quarter) — map receipt quarter to **priority date range** via PERM processing time (e.g. 11–13 months) + ~1 month to file I-140.
- **Approved EB petitions awaiting visa** (final priority dates) — pending inventory by preference/country.
- **Pending I-485** by employment-based preference — demand already in pipeline.
- **Supply:** FY visa cap (e.g. 140K base + spillover). Example assumptions: FY23 197K, FY24 161K, FY25 150K, FY26 140K.
- **Philippines:** Often grouped with ROW when under 7% country cap.

**Methodology:**

- Compare “I-140s received with PD in range X–Y” (from PERM lag) to “visas available this FY” and historical FAD movement → infer how much FAD can move (e.g. “~42K ROW demand in FY23–24, FAD moved to Nov 2022”).
- Project FAD at end of next FY (e.g. “EB-3 FAD ~May 2023 by end of FY26”).
- Charlie Oppenheim (former DOS) has given similar qualitative guidance (e.g. EB-3 FAD ~1 week/month until a given date).

**Output:** A single projected FAD (or range) per (class, country), not a full next-bulletin table; maturity date then = when projected FAD crosses user’s PD.

### 3.2 Measurable variables + correlation + decision/ensemble tree

**Idea:** Treat prediction as a regression/classification problem with measurable features; use correlation/multicollinearity analysis, then a tree-based model.

**Steps suggested:**

1. **Collect measurable variables:** Backlogs (I-140 receipts, approved awaiting visa, pending I-485), visa slots/caps per FY, processing times (PERM, I-140/I-485), historical movement (e.g. 12m/36m/60m), retrogression, porting statistics, approval rates.
2. **Correlation and multicollinearity:** Correlate variables with historic delay/movement; drop or combine highly multicollinear features.
3. **Model:** Decision tree or **ensemble tree** (e.g. Random Forest, GBM). Features = variables; target = delay or movement (e.g. “movement in next FY” or “months until current”).
4. **Use:** Feature importance for interpretability; regression tree gives an estimation equation or graph (e.g. “if demand X and supply Y, movement Z”).

**Additional suggestions:** Incorporate **pending inventory**, **porting statistics**, and **approval rates** as they are published.

---

## 4. Available Data We Are Not Ingesting or Using

### 4.1 DOS (Department of State)

| Data | Source | Format | Update | Relevance |
|------|--------|--------|--------|-----------|
| Visa issuance by category | Annual Report Table I | PDF | Yearly | Total EB/FB usage per FY; supply consumed |
| Visa issuance by country | Table III, VII | PDF | Yearly | Per-country EB usage; 7% cap utilization |
| Per-preference breakdown | Report of the Visa Office | HTML/PDF | Yearly | EB-1/2/3, F1/F2A/etc. |

**URLs:** https://travel.state.gov/content/travel/en/legal/visa-law0/visa-statistics.html ; annual reports under visa-statistics/annual-reports/

**Characteristics:** Annual or yearly; country/preference level; no priority-date bins. Useful as **supply-side and utilization** features (e.g. visas_issued_eb2_india_fy2024).

### 4.2 USCIS

| Data | Source | Format | Update | Relevance |
|------|--------|--------|--------|-----------|
| I-140 receipts by class and country | e.g. i140_rec_by_class_country_fy2024_q3.xlsx | XLSX | Quarterly | Demand by EB preference/country; map to PD range via PERM lag |
| Approved EB petitions awaiting visa (final priority dates) | “EB Petitions Awaiting Visa Final Priority Dates” | XLSX | Quarterly | Pending inventory by preference/country |
| Pending I-485 by employment-based preference | “Pending Applications for Employment-Based … as of [date]” | XLSX | Snapshot | Demand in pipeline by category |
| Porting statistics | If published | — | — | AC21 porting; demand shift between categories |
| Approval rates | FOIA / reports | — | — | Effective demand (approved I-140s that use a number) |

**URL:** https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data

**Characteristics:** Quarterly or snapshot; by preference and country; **no priority-date bins** in public files (aggregate counts). I-140 receipts can be converted to approximate PD ranges using PERM processing time (e.g. permtimeline.com: 11–13 months) + 1 month to file.

### 4.3 External / derived

| Data | Source | Format | Relevance |
|------|--------|--------|-----------|
| PERM processing time (average) | e.g. permtimeline.com | Web | Map I-140 receipt quarter → priority date range |
| FY visa cap (base + spillover) | Law + DOS reports | Config/table | 140K base; spillover varies by FY (e.g. FY23 197K, FY24 161K) |
| Country cap (7%) | INA | Constant | 9,800 per country/year for EB |

### 4.4 What we still do not have

- Pending inventory **by priority date bin** (only aggregates by category/country).
- USCIS/DOS **internal allocation rules** (how they choose cutoffs month to month).
- True “number of people ahead of you” — but approved awaiting visa + pending I-485 bring us closer to **demand quantity** than bulletin series alone.

---

## 5. Machine-Learned Model: Detailed Design

This section proposes a **single, top-level approach**: a machine-learned model trained on all available data, with loss functions chosen to minimize error on the two main predictions (next bulletin; maturity date). The design is tailored to the actual data scale, feature set, and unpredictability of the process.

### 5.1 Problem formulation

**Task 1 — Next bulletin prediction (per series):**  
For each (visa_category, visa_class, country, action_type), predict the **cutoff** for the **next** bulletin (and optionally for h = 2, 3, … months ahead). Output can be:

- **Regression:** Predict cutoff as a continuous date (e.g. days since epoch) or “months of PD advanced” from last known cutoff.
- **Classification:** Predict bucket (Current / Unavailable / date bin).  
Regression is more informative for maturity; classification can handle C/U explicitly.

**Task 2 — Maturity date (per application):**  
Given (visa_class, country, action_type, user_priority_date), predict the **calendar date** when user_priority_date will first be current (or distribution/quantiles). This is the main user-facing target.

**Relationship:** If we predict next (and future) bulletin cutoffs per series, we can derive maturity date for any PD by finding the first predicted bulletin where cutoff >= user_priority_date. So Task 1 can drive Task 2; alternatively, we can train directly on maturity-date error (see loss below).

### 5.2 Data scale and sparsity (specific numbers)

**In-DB (today):**

- **Bulletins:** ~120–150 months (from ~2013).
- **Series:** ~(10 EB + 5 FB) × 6 countries × 2 action types ≈ **180 series** (order of magnitude).
- **Observations for “next bulletin” target:** One label per (series, bulletin): we know the *actual* cutoff at time t; we want to predict it from data available at t−1. So **effective samples** ≈ number of (series, bulletin) pairs with history before that bulletin. Roughly **180 × (120−12) ≈ 19K** if we require 12 months of history (order of 10^4).
- **Sparsity:** Many series have “Current” or “Unavailable” for long periods (no date to regress). Retrogression and C/U need explicit handling (see features and targets).

**After adding DOS/USCIS:**

- **DOS:** A few tens of rows per FY (issuance by category/country) → ~20–30 FYs → hundreds of rows; **low volume**, high level.
- **USCIS:** I-140 receipts and “awaiting visa” by (preference, country, FY/Q) → hundreds to low thousands of rows; **no PD bins**, so we use them as **features** (demand/supply proxies), not as additional labels.
- **PERM lag:** One scalar or a short time series per FY (e.g. average PERM months); **very low volume**.

**Conclusion:** We have **on the order of 10^4** training points for next-bulletin prediction (per series per month); **features** will be ~20–50 after adding supply/demand, movement lags, FY, etc. Data is **sparse relative to high-dimensional ML** but sufficient for **linear models, shallow trees, or small neural nets** with strong regularization and temporal validation.

### 5.3 Unpredictable factors

- **Policy / law changes:** Quota changes, spillover rules, country-cap changes. We cannot predict these; we can use **scenario inputs** (e.g. “supply = 140K” vs “197K”) as features or run separate scenarios.
- **Spillover:** Family ↔ employment spillover is decided by DOS and not fully public in advance. Model can use **prior FY spillover** or **estimated supply** as a feature.
- **Allocation discretion:** DOS chooses exact cutoff dates; internal rules are unknown. The model learns **empirical relationships** from history.
- **One-off events:** Court orders, agency backlogs, COVID-style shocks. Best handled by **temporal validation** and **robust loss** (e.g. MAE, quantile loss) so that outliers do not dominate.

These justify: (1) **uncertainty quantification** (ranges or quantiles), (2) **conservative bands** in the UI, (3) **frequent retraining** as new bulletins and USCIS/DOS data arrive.

### 5.4 New data source characteristics

| Source | Granularity | Lag | Update frequency | Use in model |
|--------|--------------|-----|------------------|--------------|
| Bulletin (our DB) | Per (class, country, action_type) per month | 0 (we have it when published) | Monthly | Target + autoregressive features |
| DOS issuance | Per category/country per FY | Months (report lags FY end) | Yearly | Supply/utilization features |
| I-140 receipts | Per preference/country per FY/Q | Quarter lag | Quarterly | Demand proxy; map to PD range via PERM lag |
| Awaiting visa | Per preference/country per snapshot | Snapshot lag | Quarterly | Pending-inventory feature |
| Pending I-485 | Per category per snapshot | Snapshot lag | Irregular | Pipeline-demand feature |
| PERM time | Aggregate or by period | Lagged | Monthly/quarterly | Converts I-140 receipt date → PD range |
| FY cap / spillover | Per FY | Known or estimated | Yearly | Supply feature |

**Alignment:** All features must be aligned to a **reference month** (bulletin publication month). FY and quarter map to calendar months (e.g. FY2024 Q3 → months 4–6 of FY2024). For “next bulletin” at time t, we use only features **available at or before t−1** (no lookahead).

### 5.5 Feature set (for next-bulletin and maturity)

**Per (visa_class, country, action_type) at bulletin month t:**

- **Autoregressive / history (from our DB):**
  - Cutoff at t−1, t−2, … (or “current”/“unavailable” flags).
  - Movement in last 3/6/12 months (months of PD advanced, or days).
  - Retrogression in last 12 months (binary or count).
  - Months since last “Current” or since last retrogression (if useful).
- **Calendar / FY:**
  - Fiscal year of t; month-in-FY (Oct=1 … Sep=12).
  - Calendar month (for seasonality if any).
- **Supply (from DOS + config):**
  - FY visa cap (EB total) for current FY; prior FY cap.
  - Visas issued (DOS) for this preference/country in prior FY (and optionally utilization vs 7% cap).
- **Demand (from USCIS + PERM):**
  - I-140 receipts in prior FY/Q for this (preference, country); optionally mapped to “effective PD range” via PERM lag.
  - Approved awaiting visa (count) for this (preference, country) at last snapshot.
  - Pending I-485 (count) for this category at last snapshot.
- **Cross-series (optional):**
  - Same preference, other countries’ movement (e.g. ROW movement for India series).
  - Same country, other preferences’ movement (for porting / spillover context).

**Encoding:** “Current” and “Unavailable” can be encoded as separate binary flags plus a numeric cutoff (e.g. max date for Current, or last known date). Or predict a three-way outcome (C / U / date) with a hybrid head.

### 5.6 Target variables and loss functions

**Task 1 — Next bulletin:**

- **Primary target:** Movement in the next month: e.g. `y = (cutoff_date[t] - cutoff_date[t-1]).days` (or 0 if retrogressed; special tokens for C/U). Then predict ŷ; **loss:** MAE or Huber on movement (days).
- **Alternative:** Predict cutoff_date[t] directly (e.g. days since epoch); **loss:** MAE on date. Or predict probability of C / U / date bin; **loss:** cross-entropy or ordinal loss.
- **Multi-step:** For h-month-ahead, predict movement from t to t+h or cutoff at t+h; **loss:** sum of MAE over horizons 1..h (or weighted).

**Task 2 — Maturity date:**

- **Derived from Task 1:** Simulate future bulletins using predicted movements; first month where predicted cutoff >= user_PD is maturity date. **Loss:** For a user with known maturity date (from historical data), we can compute error in predicted maturity date (e.g. MAE in days or months).
- **Direct maturity model:** For each (series, user_PD) with observed maturity date in the past, target = maturity date (or months to maturity). Features: same as above plus user_PD and “months until PD from last cutoff”. **Loss:** MAE or quantile loss (e.g. 0.1, 0.5, 0.9) on maturity date or months-to-maturity.

**Recommended primary loss:** **Minimize MAE on maturity date** (or months to maturity) over a held-out set of (series, PD) pairs where we know the true maturity date from history. This directly optimizes the user-facing product. Optionally add an **auxiliary loss** on next-bulletin movement so the model also fits the bulletin process; e.g. **total_loss = α * maturity_MAE + (1−α) * movement_MAE**.

**Quantile loss:** Use quantile regression (e.g. pinball loss) for 0.1, 0.5, 0.9 to output **ranges** (“maturity between date_low and date_high”) and improve robustness to outliers.

### 5.7 Model architecture and training

**Given data scale (~10^4 samples, ~20–50 features) and need for interpretability and uncertainty:**

- **Baseline:** **Ridge or Elastic Net regression** on movement (or maturity). Simple, robust, interpretable coefficients. Good first step to validate feature value.
- **Main proposal:** **Gradient Boosting (GBM)** — e.g. XGBoost, LightGBM, or CatBoost. Handles mixed types, nonlinearities, and missing values; provides **feature importance**; supports **quantile regression** for uncertainty. Hyperparameters: shallow trees (depth 3–5), moderate number of trees (100–500), strong regularization (L2, min_child_weight). Training: minimize maturity MAE (and optionally movement MAE).
- **Alternative:** **Random Forest** for robustness and interpretability; or **small MLP** (1–2 hidden layers, strong dropout) if we want to try deep representation — but with 10^4 samples, tree-based is safer.
- **Time series:** We could use **Seq2Seq or Transformer** on the cutoff series, but the series are short (~120 points) and we have many series (180); **tabular** formulation (one row per series per month with lagged and exogenous features) is more data-efficient and aligns with DOS/USCIS features.

**Training setup:**

- **Temporal split:** Train on bulletins before year T, validate on T, test on T+1 (or strict “predict next month” rolling). No shuffle — **strict temporal order** to avoid lookahead.
- **Stratification:** Ensure validation/test include diverse (visa_class, country) and both moving and stagnant series. Optionally **hold out entire countries or classes** to test generalization.
- **Retraining:** Monthly when new bulletin is ingested; optionally quarterly when USCIS/DOS data update.

### 5.8 Uncertainty and presentation

- **Point estimate:** Median or mean prediction (from GBM or quantile head at 0.5).
- **Range:** Use 0.1 and 0.9 quantile predictions (from quantile loss or bootstrap/Jackknife on ensemble) → “Maturity between date_low and date_high”.
- **Caveats in UI:** “Estimates use public data only; policy and allocation changes can affect outcomes. We do not know exact queue position.”

### 5.9 Implementation pipeline (ML part)

1. **Feature store:** Ingest and align bulletin, DOS, USCIS, PERM, FY cap into a single table: one row per (visa_class, country, action_type, bulletin_month) with features and targets (next-month movement; and, where observable, maturity date for sampled PDs).
2. **Label creation for maturity:** For each (series, bulletin_month), take “user_PD = cutoff_date[bulletin_month]”; true maturity date for that PD is that bulletin_month. Build (series, user_PD, maturity_date) from historical cutoffs; train direct maturity model or use bulletin predictions to simulate maturity.
3. **Train/val/test split:** Temporal; report MAE (and optionally RMSE, quantile coverage) on movement and on maturity date.
4. **Serve:** Export model (e.g. ONNX or native XGBoost/LightGBM); at inference, input (series, current cutoff, user_PD, exogenous features for next month) → predicted next cutoff and/or maturity date (and quantiles).
5. **Monitoring:** Track prediction error each month on the latest bulletin and on maturity dates that “mature” in that month; alert on degradation.

---

## 6. Alternatives Considered

### 6.1 Rule-based multi-window rates (current + extensions)

**Idea:** Keep current linear rate from last 12 months; add 36m and 60m rates; classify trend (slowing/stable/accelerating); show conservative/mid/optimistic from different windows.

**Pros:** No new data; interpretable; low effort.  
**Cons:** Does not use supply/demand or any exogenous signal; cannot improve much when movement is driven by quota and backlog.  
**Verdict:** Good **fallback and baseline**; keep in product alongside ML. Use as a feature (e.g. “rule_based_maturity_months”) or as a benchmark for ML.

### 6.2 Demand/supply heuristic (PhoenixCTB-style)

**Idea:** Ingest I-140, awaiting visa, pending I-485; use PERM lag to map receipts to PD range; compare to FY cap and historical movement; produce a single FAD projection per (class, country) per FY.

**Pros:** Uses demand data; matches community methodology; interpretable.  
**Cons:** Manual assumptions (PERM lag, spillover, Philippines=ROW); not trained end-to-end on prediction error; does not output full next-bulletin table or uncertainty.  
**Verdict:** Valuable as **feature engineering** and **sanity check** for the ML model; or as a **separate “expert” view** in the UI. Not a replacement for a single loss-optimized model.

### 6.3 Pure time series (ARIMA, Prophet, etc.)

**Idea:** Model each cutoff series as a univariate (or low-variate) time series; forecast next month(s).

**Pros:** Uses only our DB; standard tools.  
**Cons:** Ignores supply, demand, FY, and cross-series information; many short series (C/U and retrogression make them non-stationary).  
**Verdict:** Can serve as **baseline** for “next bulletin” movement; likely worse than a tabular model that uses DOS/USCIS and lags.

### 6.4 Separate models for “next bulletin” vs “maturity”

**Idea:** One model predicts next bulletin cutoffs; a second model (or simulation) derives maturity from those predictions.

**Pros:** Clear separation of concerns.  
**Cons:** Errors in bulletin prediction compound when deriving maturity; optimizing only bulletin loss may not minimize maturity error.  
**Verdict:** Prefer **single loss on maturity** (with optional auxiliary bulletin loss) so the model is tuned for the main product goal; bulletin forecasts can be read off the same model or a shared representation.

### 6.5 Virtual Queue Simulation (VQS)

**Idea:** Build a deterministic simulation of the queue (demand) and processing rate (supply); use ML only to estimate hidden parameters (demand de-aggregation via PERM lag, attrition/leakage, supply forecast). The solver steps through future months, depleting the virtual queue to produce cutoffs and maturity dates.

**Pros:** Interpretable queueing view; bi-temporal data layer enables strict backtesting; ML is confined to parameter estimation (de-aggregator, attrition, supply).  
**Cons:** Requires building and maintaining a full simulation engine; PERM lag distribution and attrition are hard to estimate from public data; queue state is not directly observable (only aggregates).  
**Verdict:** Strong alternative for teams that prefer a simulation-first, "physics-based" design. See **SMART_PREDICTIONS_VQS_PROPOSAL.md** in this directory for the full VQS design (Time Machine, Estimators, Solver, roadmap).

### 6.6 Why the ML approach (Section 5) is the main focus

- **Single objective:** Minimize maturity-date error (and optionally next-bulletin error) on held-out data.
- **Uses all data:** Bulletin history, DOS issuance, USCIS demand, PERM lag, FY caps — as features in one pipeline.
- **Adapts to scale:** ~10^4 samples and ~20–50 features suit GBM/linear + regularization; no need for very large deep models.
- **Uncertainty:** Quantile loss or ensemble gives ranges for maturity and bulletin.
- **Maintainable:** Feature store + temporal validation + retraining is a standard ML lifecycle; rule-based and heuristic views remain as baselines and inputs.

---

## 7. References

**In-repo:** FEATURE_IDEAS.md (Feature 2: Wait Time Calculator); lib/business/bulletin/cutoff_projection.py; lib/business/bulletin/cutoff_data_aggregator.py; models/visa_cutoff_date.py; models/bulletin.py.

**DOS:** https://travel.state.gov/content/travel/en/legal/visa-law0/visa-statistics.html ; annual reports: visa-statistics/annual-reports/

**USCIS:** https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data ; I-140 example: https://www.uscis.gov/sites/default/files/document/data/i140_rec_by_class_country_fy2024_q3.xlsx

**Community:** PhoenixCTB EB-3 analysis: https://www.reddit.com/r/USCIS/comments/1o1tez6/comment/niiym7f/ ; “My EB3 ROW visa bulletin prediction”: https://www.reddit.com/r/USCIS/comments/1fztc54/my_eb3_row_visa_bulletin_prediction/ ; Charlie Oppenheim (EB-3 FAD): https://youtu.be/mzcfk7RDq5M ; PERM times: https://permtimeline.com/
