# Prediction System Overview and Release Guide

*Last updated: March 2026*

---

## 1. User-Facing Surfaces

### 1.1 Surface Inventory

| Surface | URL(s) | Data Source | Update Cadence | Audience |
|---------|--------|-------------|----------------|----------|
| **Dashboard Queue Model** | `/`, `/employment-based/`, `/employment-based/<country>/` | Live solver (`predict_next_bulletin_and_maturity()`) | Real-time (cached 300s) | All users |
| **Prediction Detail** | `/predictions/employment_based/<YYYY-MM>/` | Stored `PredictedCutoff` rows | Monthly (after `publish_predictions`) | Users tracking specific months |
| **Predictions Archive** | `/predictions/` | `PredictedBulletin` index | Monthly | All users |
| **VQS Predict API** | `/api/vqs/predict/?visa_class=&country=&action_type=&priority_date=&knowledge_date=` | Live solver (JSON) | Real-time (cached 300s) | Developers, integrations |
| **Blog Analysis** | `/analysis/<slug>/` | Pre-generated HTML in `BlogPost.content` | Per-bulletin (narrated by `bulletin_narrator.py`) | All users |
| **Spaghetti Chart** | `/spaghetti/` | Baked JSON from `evaluate_model.py` | On model change | Internal / advanced users |
| **Metric Report** | `/metric-report/` | Generated HTML from `generate_metric_report.py` | On model change | Internal / advanced users |

### 1.2 Data Flow per Surface

```
publish_predictions.py
    │
    ├──► PredictedBulletin + PredictedCutoff (DB)
    │        │
    │        ├──► /predictions/ (archive list)
    │        ├──► /predictions/<cat>/<YYYY-MM>/ (detail: matrix, badges, CI)
    │        └──► /analysis/<slug>/ (blog: embedded at narration time)
    │
predict_next_bulletin_and_maturity() (live solver)
    │
    ├──► / (dashboard: Queue Model column)
    └──► /api/vqs/predict/ (JSON API)

evaluate_model.py ──► spaghetti.html ──► /spaghetti/
generate_metric_report.py ──► metric_report.html ──► /metric-report/
```

### 1.3 Key Templates and Views

| Template | View Function | File |
|----------|--------------|------|
| `vqs/prediction_list.html` | `prediction_list` | `webapp/views/prediction_views.py` |
| `vqs/prediction_detail.html` | `prediction_detail` | `webapp/views/prediction_views.py` |
| `webapp/dashboard.html` | `dashboard_view` | `webapp/views/bulletin/dashboard.py` |
| `spaghetti.html` | `spaghetti_view` | `webapp/views/prediction_views.py` |
| `metric_report.html` | `metric_report_view` | `webapp/views/prediction_views.py` |
| N/A (JSON) | `VQSPredictView` | `webapp/views/bulletin/vqs_api.py` |
| `blog/post_detail.html` | `blog_detail` | `webapp/views/blog_views.py` |

---

## 2. External Data Sources

### 2.1 Data Currently Used by VQS

| Source | Dataset | Ingested As | VQS Feature(s) | Coverage | Ingestion Script |
|--------|---------|-------------|-----------------|----------|------------------|
| **USCIS** | I-140 Receipts (quarterly) | `RawFactsLedger` `i140_receipts` | #11 `i140_ratio`, #18 `demand_ratio_class` | FY2014–FY2025 | `scripts/vqs/ingest_uscis_i140.py` |
| **USCIS** | I-485 Pending Inventory (monthly) | `RawFactsLedger` `i485_pending_inventory_monthly` | #12 `i485_queue_size`, #26 `i485_density_near_cutoff` | ~Jul 2022–present | `scripts/vqs/download_uscis_i485.py` |
| **DOS** | Monthly IV Issuance | `RawFactsLedger` `visa_issuance_monthly` | #16 `utilization_rate`, #25 `issuance_drop_ratio` | ~FY2015–present | `lib/ingest/plugins/dos.py`, `scripts/ingest_dos_issuance.py` |
| **DOS** | Visa Bulletin (historical) | `Bulletin`, `VisaCutoffDate` | #0-10, #13-15, #19-22 (movement, velocity, regime, age, etc.) | Oct 2009–present | `lib/ingest/plugins/visa_bulletin.py` |
| **DOL** | PERM Disclosure | `SalaryRecord` → `RawFactsLedger` `perm_lag_distribution` | Indirect: convolution in `demand.py` | FY2008–FY2025 | `lib/ingest/plugins/dol_perm.py`, `scripts/vqs/compute_perm_lag.py` |
| **DOL** | PERM Supply (certified cases) | `RawFactsLedger` `perm_applications` | Direct PD assignment in `demand.py` | FY2008–FY2025 | `lib/ingest/plugins/dol_perm_supply.py` |

### 2.2 GBM Feature Vector (30 features)

| Index | Feature | Data Source |
|-------|---------|-------------|
| 0–1 | series_country, series_class | Enum encoding |
| 2–6 | move_1m, move_3m_avg, move_6m_avg, move_12m_avg, regime_state | `VisaCutoffDate` |
| 7–9 | month_of_year, is_fy_reset, is_end_of_fy | Date logic |
| 10 | cutoff_age_days | `VisaCutoffDate` |
| 11 | i140_ratio | `RawFactsLedger` (USCIS I-140) |
| 12 | i485_queue_size | `RawFactsLedger` (USCIS I-485) |
| 13–15 | eb1_move_1m, eb1_move_3m, eb1_regime_state | `VisaCutoffDate` (cross-series) |
| 16 | utilization_rate | `RawFactsLedger` (DOS issuance) |
| 17 | months_into_fy | Date logic |
| 18 | demand_ratio_class | `RawFactsLedger` (USCIS I-140) |
| 19 | cutoff_velocity_6m | `VisaCutoffDate` |
| 20 | retro_distance_months | Date logic |
| 21 | eb1_surplus_indicator | `VisaCutoffDate` (EB-1 "Current") |
| 22–25 | row_move_1m, row_move_3m_avg, row_is_current, issuance_drop_ratio | `VisaCutoffDate` + DOS issuance |
| 26 | i485_density_near_cutoff | `RawFactsLedger` (USCIS I-485) |
| 27–29 | horizon, target_month_of_year, target_months_into_fy | Horizon parameters |

### 2.3 DOL Performance Data: What's Available vs Used

Source: [DOL OFLC Performance Data](https://www.dol.gov/agencies/eta/foreign-labor/performance)

| DOL Dataset | Available | We Use It? | Prediction Potential |
|-------------|-----------|------------|---------------------|
| **PERM Disclosure** (FY2008–FY2026 Q1) | Case-level: employer, SOC, wage, PD, status, dates | **YES** — `SalaryRecord` + `perm_lag_distribution` + `perm_applications` | Already partially used. Filing volume aggregation as 12-18mo demand leading indicator is the next high-value extraction. |
| **LCA (H-1B/H-1B1/E-3)** (FY2008–FY2026 Q1) | Case-level: employer, wage, job title, status | **YES** — `SalaryRecord` (salary features only) | **MEDIUM** — H-1B→EB conversion rate (structural demand indicator). Not yet used for VQS. |
| **Prevailing Wage** (FY2010–FY2026 Q1) | PW determinations, processing times | **NO** | **LOW** — Too far upstream (24+ months before cutoff impact). |
| **H-2A Disclosure** (FY2008–FY2026 Q1) | Seasonal ag worker data | **NO** | **NONE** — Different visa track, no EB relevance. |
| **H-2B Disclosure** (FY2008–FY2026 Q1) | Seasonal non-ag worker data | **NO** | **NONE** — Different visa track, no EB relevance. |
| **CW-1 Disclosure** (FY2019–FY2026 Q1) | CNMI worker data | **NO** | **NONE** — CNMI-specific, no EB relevance. |
| **Selected Statistics** (quarterly) | Aggregate program-level counts | **NO** | **MEDIUM** — Cross-check for I-140/PERM volumes. Redundant with USCIS data already ingested. |

### 2.4 Highest-Value Untapped Data for Prediction Improvement

Ordered by expected impact on the weakest predictions (India EB-2/3):

1. **PERM filing volume → EB demand leading indicator** (from DOL PERM Disclosure)
   - We already ingest PERM into `SalaryRecord`. Need a new aggregation: count certified PERM cases by quarter, EB category, and country of birth.
   - PERM certification is ~12-18 months before I-485 filing → cutoff pressure.
   - Directly tests Hypothesis #4 in Section 0.
   - Effort: LOW (data exists, need new feature in `gbm_expert.py`).

2. **USCIS processing time trends** (not on DOL page; from USCIS)
   - Monthly processing times for I-140, I-485 by service center.
   - Processing time spike → future bottleneck → cutoff stall.
   - Effort: MEDIUM (need web scraping or API integration).

3. **H-1B → EB conversion rate** (from DOL LCA Disclosure)
   - Aggregate H-1B LCA volume by employer nationality proxy.
   - Sustained H-1B growth for India-born workers → future EB demand.
   - Effort: HIGH (nationality is not in LCA; would need proxy from employer PERM history).

4. **I-140 approval/denial rates** (from USCIS, not DOL)
   - Approval rate changes signal policy shifts before they hit cutoffs.
   - Effort: MEDIUM (USCIS publishes some data; granularity varies).

---

## 3. Per-Series Model Dispatch (Current Production)

| Series | 1m | 3m | 6m | 12m |
|--------|-----|-----|-----|------|
| **China EB-1** | RS | RS | RS | GBM Gated |
| **China EB-2** | VQS Ensemble | VQS Ensemble | Oppenheim Pace | Oppenheim Pace |
| **China EB-3** | VQS Ensemble | VQS Ensemble | GBM Gated | GBM Gated |
| **India EB-1** | RS | RS | GBM Gated | GBM Gated |
| **India EB-2** | VQS Ensemble | VQS Ensemble | Oppenheim Pace | GBM Gated |
| **India EB-3** | VQS Ensemble | VQS Ensemble | Oppenheim Pace | Oppenheim Pace |

- **RS** = Regime-Switched (undampened expert selector)
- **GBM Gated** = GBM classifier → point prediction (only when P(movement) > gate)
- **Oppenheim Pace** = Constant-pace extrapolation
- **VQS Ensemble** = Tuned meta + Hedge aggregator

Movement probability badge (1m only, GBM-based): shown on prediction detail page as Stable/Watch/Movement Likely.

---

## 4. Deploying Predictions to Staging and Production

### 4.1 Current State

- `publish_predictions` is a local-only script — not part of the refresh pipeline.
- Predictions exist only in the database where the script runs.
- No automated path to transfer predictions between environments.
- Supporting data (`RawFactsLedger`) IS ingested during the pipeline (I-140, I-485, DOS, PERM).

### 4.2 Initial Transfer: pg_dump (One-Time)

For the first deployment, transfer existing prediction data via table dump:

```bash
# Step 1: Dump from local
pg_dump -U visa_bulletin -d visa_bulletin \
  --table=models_predictedbulletin \
  --table=models_predictedcutoff \
  --data-only --no-owner --no-privileges \
  -f /tmp/predictions_dump.sql

# Step 2: Transfer to staging
scp /tmp/predictions_dump.sql staging_2Gb_vm:/tmp/

# Step 3: Ensure migrations are applied on staging
ssh staging_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  DB_HOST=localhost bazel run //:migrate && bazel shutdown"

# Step 4: Load prediction data
ssh staging_2Gb_vm "cd /opt/visa_bulletin && \
  psql -U visa_bulletin_user -d visa_bulletin -f /tmp/predictions_dump.sql"
```

Also transfer `RawFactsLedger` if staging doesn't have it yet:

```bash
pg_dump -U visa_bulletin -d visa_bulletin \
  --table=models_rawfactsledger \
  --data-only --no-owner --no-privileges \
  -f /tmp/raw_facts_dump.sql
```

### 4.3 Ongoing: Add publish_predictions to Pipeline

After the initial transfer, add `publish_predictions` as a post-processing step in the refresh pipeline so new months' predictions are generated automatically on staging:

1. Add `publish_predictions` binary to `scripts/cron/build_all.sh` REQUIRED_BINARIES.
2. Add a step in `scripts/cron/refresh/pipeline.py` after the ingest/post-processing stages.
3. The script reads from `RawFactsLedger` + `VisaCutoffDate` (both populated by the pipeline) and writes `PredictedBulletin` + `PredictedCutoff`.

After graduation (IP flip), the predictions are on prod automatically.

### 4.4 Static Assets (Spaghetti, Metric Report)

`spaghetti.html` and `metric_report.html` are committed to the repo (in `webapp/templates/`). They transfer to staging/prod via git — no separate data transfer needed. Regenerate locally after model changes, commit, cherry-pick to staging.

---

## 5. Database Schema for Predictions

### PredictedBulletin

| Column | Type | Description |
|--------|------|-------------|
| `id` | AutoField | PK |
| `target_bulletin_month` | DateField | The month being predicted (unique) |
| `prediction_date` | DateField | When the prediction was made |
| `generated_at` | DateTimeField | Timestamp of generation |

### PredictedCutoff

| Column | Type | Description |
|--------|------|-------------|
| `id` | AutoField | PK |
| `bulletin` | FK → PredictedBulletin | Parent bulletin |
| `visa_class` | CharField | e.g. "1st", "2nd", "3rd" |
| `country` | IntegerField | Country enum (1=ALL, 2=CHINA, 3=INDIA, etc.) |
| `action_type` | CharField | "filing" or "final_action" |
| `predicted_date` | DateField | Predicted cutoff date |
| `confidence_low` | DateField | 80% CI lower bound |
| `confidence_high` | DateField | 80% CI upper bound |
| `explanation_markdown` | TextField | Human-readable explanation |
| `model_name` | CharField | Which model produced this (e.g. "gbm_gated", "pace") |
| `expert_predictions` | JSONField | Raw expert predictions for transparency |
| `movement_probability` | FloatField (nullable) | P(|cutoff_move| > 50 days), 1m horizon only |
| `actual_date` | DateField (nullable) | Filled after actual bulletin published |
| `accuracy_score` | FloatField (nullable) | Post-hoc accuracy metric |

### RawFactsLedger (Supporting Data)

| Column | Type | Description |
|--------|------|-------------|
| `fact_id` | UUID PK | Unique identifier |
| `source` | IntegerField | `RawFactSource` enum |
| `metric` | CharField | e.g. `i140_receipts`, `i485_pending_inventory_monthly` |
| `dimensions` | JSONField | e.g. `{"country": "India", "category": "EB2"}` |
| `value` | JSONField | Raw number or distribution |
| `reference_period_start` | DateField | Event time |
| `publication_date` | DateField | Knowledge time |

---

## 6. Release Readiness Checklist

### Before First Public Release

- [ ] All 4 horizons (1m, 3m, 6m, 12m) generating correct predictions via `publish_predictions`
- [ ] Movement probability badge rendering correctly on prediction detail page
- [ ] Per-series dispatch verified for each (series, horizon) combination
- [ ] Demand-drop feature masking confirmed for India EB-3
- [ ] Prediction data transferred to staging (pg_dump or pipeline)
- [ ] `spaghetti.html` and `metric_report.html` regenerated and committed
- [ ] Smoke test on staging: `/predictions/`, `/predictions/employment_based/<latest>/`, `/spaghetti/`
- [ ] Blog narrator updated to include 12m and movement badge in narratives
- [ ] `publish_predictions` added to pipeline for ongoing generation

### Quality Gates

| Check | Command | Pass Criteria |
|-------|---------|---------------|
| Migrations applied | `bazel run //:migrate` | No errors, 0042 applied |
| Predictions exist | `run_sql "SELECT COUNT(*) FROM models_predictedcutoff"` | > 0 |
| 12m predictions | `run_sql "SELECT DISTINCT model_name FROM models_predictedcutoff WHERE ..."` | gbm_gated, pace per series |
| Movement badges | `run_sql "SELECT COUNT(*) FROM models_predictedcutoff WHERE movement_probability IS NOT NULL"` | > 0 for 1m rows |
| Spaghetti loads | `curl -sI https://staging-url/spaghetti/` | HTTP 200 |
| Prediction detail | `curl -sI https://staging-url/predictions/employment_based/2026-03/` | HTTP 200 |
| API responds | `curl https://staging-url/api/vqs/predict/?visa_class=2nd&country=3&action_type=filing&priority_date=2015-01-01&knowledge_date=2026-03-01` | JSON with `next_cutoff` |

---

## 7. Known Limitations

1. **India EB-2/3 predictions at 6m remain weak** (211d / 275d MAE vs 190d target). Current feature set has been exhaustively tuned. New data sources needed.
2. **1m predictions are essentially persistence** for EB-2/3. GBM signal surfaced as movement badge only — not as point prediction (MAE 2.3x worse).
3. **RawFactsLedger data must be present** for `publish_predictions` to work. If staging has a fresh DB, run the ingest plugins first or transfer the table.
4. **I-485 data coverage is sparse** (~July 2022 onward, variable publication schedule from USCIS).
5. **Spaghetti and metric report are static** — they don't update automatically when new bulletins arrive. Regenerate after model changes or monthly after new predictions.

---

## 8. Related Files

| File | Purpose |
|------|---------|
| `scripts/publish_predictions.py` | Generates predictions, writes to DB |
| `lib/business/vqs/solver.py` | VQS ensemble solver |
| `lib/business/vqs/gbm_expert.py` | GBM classifier + gated predictor |
| `lib/business/vqs/expert_pool.py` | Expert prediction functions |
| `models/vqs.py` | `PredictedBulletin`, `PredictedCutoff` models |
| `models/raw_facts.py` | `RawFactsLedger` model |
| `webapp/views/prediction_views.py` | Prediction views |
| `webapp/templates/vqs/prediction_detail.html` | Prediction detail template |
| `scripts/vqs/evaluate_model.py` | Generates spaghetti chart |
| `scripts/vqs/generate_metric_report.py` | Generates metric report |
| `docs/PREDICTIONS_ASSESSMENT.md` | Research log (Section 0 = north star) |
| `lib/business/vqs/README.md` | VQS code-level documentation |
