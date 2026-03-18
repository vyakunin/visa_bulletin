# VQS Family-Sponsored Extension – Design

Extension of the Virtual Queue Simulation (VQS) to Family-Sponsored preference categories. Employment-Based (EB) scope remains as implemented in Phases 1–3.

## References

- [VQS Assessment](../PREDICTIONS_ASSESSMENT.md)
- VQS implementation plan (Phase 3.5) – see project plan for Phases 1–3 and Family tasks.
- Current EB implementation: `lib/business/vqs/`, `models/raw_facts.py`, `models/visa_cutoff_date.py`

## Scope

- **Demand:** Family-Sponsored demand sources (e.g. I-130 pending, DOS/NVC data). No PERM lag; demand model is separate from EB (different ledger metrics, e.g. `i130_pending` or DOS family queue).
- **Supply:** Same DOS annual report; family cap and spillover to EB (and vice versa) in Model C. Rule: family limit per FY + unused EB spillover.
- **Solver:** Same monthly loop; different (visa_class, country) series. Add Family preference enums and country list; reuse `VirtualQueueSnapshot` and monthly advance logic.
- **Backtesting & UI:** Extend reference dates and series to Family categories; same MAE/maturity metrics; optional Family view in dashboard.

## Data Layer

- **Ledger metrics (new or extended):** e.g. `i130_pending`, `family_visa_limit`, `family_spillover_to_eb`. Reuse `raw_facts_ledger`; extend `dimensions` for family preference (F1, F2A, F2B, etc.) and country.
- **Bulletin/cutoff:** Reuse `VisaCutoffDate` with `visa_category="family_sponsored"`; same `get_cutoff_at_date` pattern with category parameter.

## Model A (Demand) for Family

- **Option A:** Separate pipeline: ingest Family demand (DOS/NVC or published stats) into ledger; build queue snapshot by (family_class, country) without PERM lag (direct bucket or simple lag if data is receipt-based).
- **Option B:** Reuse `build_virtual_queue_snapshot` with a Family-specific metric (e.g. `i130_receipts`) and no `perm_lag_distribution` (naive or fixed lag only).

## Model C (Supply) for Family

- **Rule:** Annual family cap from DOS; unused family visas spill to EB; unused EB spill to family. Implement in `estimators.get_monthly_supply` or a dedicated `get_family_monthly_supply(month, facts)` reading ledger `metric='visa_limit'` / `metric='family_spillover'`.
- **Country cap:** Same 7% (or DOS rule) per country for family.

## Solver Extension

- **Inputs:** `visa_category` (employment_based | family_sponsored), `visa_class` (e.g. "F2A", "2nd"), `country`, `action_type`.
- **Cutoff loading:** `get_cutoff_at_date(..., visa_category=visa_category, ...)`.
- **Supply:** When `visa_category == "family_sponsored"`, use Model C family supply (and optional spillover from EB).

## Implementation Outline

1. Add Family preference enums (or reuse existing visa_class strings) and document in ledger dimensions.
2. Ingest Family demand into `raw_facts_ledger` (new script or plugin); metric(s) for family queue.
3. Extend Model C: `get_monthly_supply(month, visa_category, facts)` with family cap and spillover from ledger/config.
4. Extend `get_cutoff_at_date` and solver to accept `visa_category`; run monthly loop for Family series.
5. Extend backtest and API to accept `visa_category`; add Family to dashboard/UI (optional).
6. Document runbooks and metric definitions in `docs/vqs_implementation.md` or equivalent.

## Out of Scope (Initial)

- Inter-queue porting (EB2 ↔ EB3) and Family ↔ EB porting; document as future enhancement if needed.
- Confidence intervals for Family predictions (same as EB: optional from simulation variance or parameter uncertainty).
