# Virtual Queue Simulation (VQS) Proposal

Alternative approach to predicting Visa Bulletin movements and Green Card maturity dates using a queue-based simulation with ML-limited to estimating hidden parameters.

---

## 1. Executive Summary

This document proposes a shift from direct regression modeling to a **Virtual Queue Simulation (VQS)** for predicting Visa Bulletin movements and Green Card maturity dates.

Instead of asking a model "What date will be in the bulletin?", we build a **deterministic simulation** of the underlying queue (people waiting) and processing capacity (visa supply). Machine Learning is restricted to estimating the **"hidden parameters"** of this simulation—specifically the distribution of demand and the rate of attrition—where official data is aggregated or missing.

**Core philosophy:** Immigration is a queueing problem governed by strict legal caps.

$$\text{Wait Time} \approx \frac{\text{Queue Length (Demand)}}{\text{Processing Rate (Supply)}}$$

---

## 2. System Architecture

The system is composed of three layers:

1. **The Time Machine (Data Layer):** A bi-temporal store of all raw facts (USCIS reports, PERM data, DOS limits) versioned by their publication date.
2. **The Estimators (ML Layer):** Small, focused models that convert raw facts into simulation parameters (e.g., converting "Quarterly Receipts" into "Monthly Priority Dates").
3. **The Solver (Simulation Layer):** A deterministic engine that steps through future months, depleting the virtual queue against the predicted supply to generate cutoffs.

---

## 3. Data Layer: The "Time Machine"

To enable accurate backtesting, we must be able to reconstruct the exact state of knowledge at any point in the past. We strictly separate **Event Time** (when the data applies to) from **Knowledge Time** (when we learned it).

### 3.1 Schema: `raw_facts_ledger`

This is an **append-only** table. No data is ever overwritten.

| Column | Type | Description |
|--------|------|-------------|
| `fact_id` | UUID | Unique identifier. |
| `source` | Enum | USCIS_I140_Q4, DOL_PERM_2024, DOS_ANNUAL_REPORT. |
| `metric` | String | i140_receipts, visa_limit, perm_lag_distribution. |
| `dimensions` | JSON | {"country": "India", "category": "EB2"}. |
| `value` | Variant | The raw number or distribution object. |
| `reference_period` | DateRange | **Event Time:** The period this data describes (e.g., Q3 2024). |
| `publication_date` | Date | **Knowledge Time:** The date this data became public. Crucial for backtesting. |

### 3.2 Ingestion Pipelines

**A. USCIS Aggregate Data Scraper**

- **Source:** USCIS "I-140 Receipts by Category and Country" (Quarterly).
- **Action:** Scrape PDFs/CSVs.
- **Output:** Rows in `raw_facts_ledger` with `metric='i140_receipts'`.
- **Note:** These are aggregates (e.g., "5,000 receipts"). They lack Priority Dates.

**B. DOL PERM Transformer (Existing Parser Adaptation)**

- **Source:** DOL PERM Disclosure Files (CSVs).
- **Action:** Repurpose this data to learn the **Lag Distribution** (time from Priority Date to I-140 Receipt).
- **Transformation logic:**
  - Filter for `case_status = 'Certified'`.
  - Calculate `lag_days = decision_date - case_received_date`.
  - Group by `decision_quarter`, `country`, `visa_category`.
  - Generate a histogram of `lag_days` (bucket size: 30 days).
- **Output:** Rows in `raw_facts_ledger` with `metric='perm_lag_distribution'`.

---

## 4. The ML Estimators (Parameter Estimation)

These models fill the gaps in the official data to build a complete "Virtual Queue."

### 4.1 Model A: The Demand "De-Aggregator"

**Goal:** Convert quarterly aggregate receipts (from USCIS) into specific monthly Priority Date buckets.

**Input:**

- USCIS Quarterly Aggregate \(N\) (e.g., 5,000 receipts in Q3 2024).
- PERM Lag Distribution \(D\) for that quarter (from `raw_facts_ledger`).

**Logic (Convolution):**

If \(D\) says "20% of cases took 365 days, 30% took 400 days...", we distribute the 5,000 receipts backwards in time accordingly.

$$Bucket_{Date} \mathrel{+}= N \times P(\text{Lag} = \text{CurrentTime} - \text{Date})$$

**Output:** A `virtual_queue_snapshot`—a histogram of people waiting, binned by Priority Date.

### 4.2 Model B: The Attrition ("Leakage") Model

**Goal:** Estimate how many people leave the queue before getting a Green Card (job loss, death, porting).

- **Type:** Survival Analysis (Kaplan-Meier or Cox PH).
- **Input:** Historical "Inventory vs. Green Card Issuance" ratios.
- **Output:** A monthly decay rate \(\lambda\) (e.g., 0.995 retention per month).
- **Refinement:** Can be upgraded to model **Inter-queue Porting** (EB2 \(\leftrightarrow\) EB3) based on the spread between cutoffs.

### 4.3 Model C: Supply Forecaster

**Goal:** Predict the Annual Visa Limit (\(L_{FY}\)) for future Fiscal Years.

- **Type:** Rule-based + Simple Regression.
- **Input:** Family-Based usage data (DOS), Statutory minimum (140k).
- **Logic:** \(L_{FY} = 140{,}000 + \text{Unused Family Visas}_{FY-1}\).
- **Output:** Integer (e.g., 165,000).

---

## 5. The Simulation Engine (The Solver)

This core loop generates the predictions.

### 5.1 Initialization

1. **Select "Knowledge Date" \(T\):** (Today, or a past date for backtesting).
2. **Load State:** Fetch all `raw_facts` where `publication_date <= T`.
3. **Build Queue:** Run Model A to build the `virtual_queue_snapshot` as of \(T\).
4. **Set Cursor:** Current_Cutoff = Actual Visa Bulletin Cutoff at time \(T\).

### 5.2 The Monthly Loop

For month \(m = T+1, T+2, \ldots\) until target reached:

1. **Calculate Monthly Supply (\(S_m\)):**
   $$S_m = \text{Model C}(FY) \times \text{CountryLimit}(7\%) \div 12$$
   *Adjustment:* Apply seasonality weights (DOS tends to front-load or back-load quarters).

2. **Process the Queue:**
   - Identify the "Head of Queue": The sum of applicants in buckets between Current_Cutoff and Next_Potential_Cutoff.
   - Find the date \(D_{new}\) where \(\sum_{d=\text{Current}}^{D_{new}} \text{Applicants}_d \approx S_m\).
   - Update: Current_Cutoff \(\leftarrow D_{new}\).

3. **Apply Dynamics:**
   - **Leakage:** Multiply all remaining queue buckets by \(\lambda\) (from Model B).
   - **New Demand:** Add projected new I-140s to the back of the queue (using recent trend).

4. **Store Result:** Record \((m, D_{new})\).

### 5.3 Output Generation

- **Next Bulletin Prediction:** The result of the first iteration (\(m=T+1\)).
- **Maturity Date:** The month \(m\) where Current_Cutoff \(\ge\) User's Priority Date.

---

## 6. Evaluation & Backtesting Strategy

We validate the model by **"replaying history."**

**Protocol:**

- **Dataset:** Define a set of reference dates (e.g., Jan 1st of 2021, 2022, 2023, 2024).
- **Execution:** For each date, load only data available then, run the simulation, and store the predictions.

**Metrics:**

- **Bulletin MAE:** Mean Absolute Error (in days) between predicted cutoff and actual published bulletin for \(T+1\), \(T+3\), \(T+6\).
- **Maturity Precision:** For users who became current in 2024, what date did we predict for them in 2022?
- **Inventory Calibration:** Compare our `virtual_queue_snapshot` totals against the sporadic "Pending Inventory" reports USCIS releases (ground truth check).

---

## 7. Implementation Roadmap

### Phase 1: The "Physics" MVP (Weeks 1–4)

**Goal:** A working end-to-end pipeline with naive ML.

**Tasks:**

- Implement `raw_facts_ledger` (Postgres).
- Ingest USCIS I-140 receipts.
- Model A (Naive): Assume strict 12-month lag (no PERM distribution yet).
- Simulation: Constant supply (e.g., 700/month).

**Deliverable:** A script that outputs a predicted date, even if inaccurate.

### Phase 2: The "Data" Upgrade (Weeks 5–8)

**Goal:** Replace naive assumptions with PERM-derived distributions.

**Tasks:**

- Modify PERM parser to populate `perm_lag_distribution`.
- Update Model A to use Convolution (De-aggregation).
- Implement "Time Machine" backtesting suite.

### Phase 3: The "Dynamics" Refinement (Weeks 9+)

**Goal:** Handle complex behaviors (Spillover, Porting).

**Tasks:**

- Implement Model B (Attrition/Porting).
- Implement Model C (Dynamic Supply forecasting based on Family usage).
- Build the UI to display "Wait Time" with confidence intervals derived from simulation variance.
