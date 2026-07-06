# FAD↔DFF interdependence: coupling design (proposal)

Status: **proposal** (2026-07-06). Motivated by the "Est. Current Date" invariant
bug (Notion bug ticket 39462b8d…8154, reported via r/USCIS) whose current fix is a
post-hoc scalar clamp (`webapp/views/bulletin/dashboard.py`, commit 4f869fc). This
doc is the answer to "research a better way to leverage the interdependence in the
modeling rather than simply clamp" (VQS follow-up ticket 39462b8d…81b1).

## The invariant
At every published bulletin, for a (category, country): **DFF cutoff ≥ FAD cutoff**
(Filing lets you file no later than Final Action approves). Equivalently a priority
date matures for Filing no later than for Final Action. Empirically **absolute**:
419/419 paired historical observations (EB-1/2/3 × India/China since 2020-10) show
**zero violations**. So any model must reproduce it **by construction**, not on average.

## Why the current clamp is insufficient
FAD and DFF are forecast as **two fully independent runs** (`predict_regime_switched`
in `lib/business/vqs/solver.py:418`; `action_type` threads through every expert /
trajectory with **no cross-series term**). The clamp (`dashboard.py:337-344`)
corrects only the **maturity scalar** on the Filing page. It leaves uncorrected:
1. the 1m/6m/12m cutoff table cells (`next_cutoff`, `cutoff_6m`, `cutoff_12m`),
2. the plotted chart trajectory,
3. the two linear-extrapolation tails (`_linear_maturity_fallback`,
   `_historical_linear_maturity`),
4. `lib/business/bulletin/cutoff_projection.calculate_projection` (via
   `cutoff_data_aggregator.py:255`) — a third fully-independent surface.
So the invariant is patched in 1 of ~4 places it can break.

## Empirics that shape the design
Spread (DFF−FAD, days) is non-negative but **its level and volatility are strongly
series-specific**, and **neither series is universally the reliable anchor**:

| Series | mean spread (d) | sd spread | mean·mo |ΔFAD| | mean·mo |ΔDFF| |
|---|---|---|---|---|
| EB-1 China | 118 | 151 | 12 | 13 |
| EB-1 India | 265 | 654 | **190** | 64 |
| EB-2 China | 98 | 65 | 19 | 22 |
| EB-2 India | 224 | 189 | **46** | 24 |
| EB-3 China | 139 | 112 | 37 | 40 |
| EB-3 India | 324 | 490 | **74** | 21 |

- **India:** DFF is the smooth series, **FAD is the jumpy one** (retrogression
  swings); the spread inherits FAD's noise and is *more* volatile than the DFF level.
- **China:** the two co-move at similar small magnitudes.

**Consequence:** the naive "forecast FAD as anchor + a stable spread → DFF" design
is WRONG as a universal choice — for India it would import FAD's noise into today's
smooth DFF and likely regress DFF accuracy. The anchor would have to *flip* by
country. This rules out that approach as the default.

## Options considered
- **A — FAD + non-negative spread (`DFF = FAD + softplus(spread)`).** Invariant by
  construction, but requires a per-series anchor that must flip India↔China; India's
  spread sd is huge (654 d) so the spread model is itself hard; discards one series'
  tuned model. Medium-high cost, medium risk.
- **B — Constrained joint reconciliation, confidence-weighted (RECOMMENDED).** Below.
- **C — Learned FAD↔DFF map (regress spread on regime/FY-phase/velocity).** Captures
  regime-dependent spread widening, but ~70 obs/series is too thin (same data
  starvation that sank the FY-boundary experiment). Revisit if a spread signal proves
  strong.
- **D — Hierarchical shared-latent joint model.** Theoretically cleanest coupling;
  unjustified rewrite at ~70 monthly obs/series. Long-term north star only.

## Recommendation — Option B: constrained reconciliation at the trajectory level
Keep both per-series models exactly as tuned. After both trajectories are produced,
run a **reconciliation pass** that enforces `DFF_t ≥ FAD_t` at every step (and into
both tails) by projecting any violating pair onto the feasible region, splitting the
correction by each series' relative reliability:

```
if DFF_t < FAD_t:
    gap = FAD_t - DFF_t
    w   = confidence weight in [0,1]     # share of the gap FAD concedes
    FAD_t' = FAD_t - w*gap
    DFF_t' = DFF_t + (1-w)*gap           # both meet at the weighted point
```

- `w` from the per-series calibrated interval width (`calibration.py`) or a static
  per-series table until that's wired: **India → w≈1** (concede FAD, trust the smooth
  DFF), **China → w≈0.5** (symmetric). The **current clamp is exactly the
  `w=1`-toward-FAD special case**, so B is a strict generalization.
- Applied to the VQS 24-step trajectory **and** the linear tail **and** the
  `cutoff_projection` surface via one shared helper → closes all four violation sites.

**Why B over A:** the empirics kill A's core assumption (no universal anchor; spread
not stable). B guarantees the invariant everywhere, keeps each per-series model's
tuned quality, and is a bounded-risk generalization of what's already in prod.

**Cost:** low-medium. **Risk:** low. **Backtest-neutral:** because DFF≥FAD holds in
419/419 history, the pass **never fires on correctly-ordered forecasts** → per-series
MAE unchanged (FAD identical under w→1; DFF within noise). It only touches the
pathological extrapolation-tail cases the clamp was invented for.

### Implementation sketch
- New pure module `lib/business/vqs/coupling.py`:
  `reconcile_pair(fad_traj, dff_traj, w_fad_concedes) -> (fad', dff')` — projects
  aligned step arrays onto `DFF_t ≥ FAD_t`. Single source of truth, imported by every
  consumer so no surface is missed.
- `dashboard.py dashboard_view`: fetch **both** action_types on both pages (it already
  fetches the counterpart on the Filing page, `:450-475`), align by month, call
  `reconcile_pair`, feed reconciled trajectories into `_build_unified_prediction_rows`
  so `next_cutoff`/`cutoff_6m`/`cutoff_12m`/`trajectory` are all corrected. **Delete
  the ad-hoc clamp** at `:337-344`.
- Reconcile the two linear tails (`_linear_maturity_fallback`,
  `_historical_linear_maturity`) through the same helper.
- Reconcile `cutoff_data_aggregator.py:255`'s FAD/DFF projections too.
- Optional (upgrade, not needed for correctness): pass the counterpart's current
  cutoff as a floor/context into `predict_regime_switched`'s trajectory chain so the
  *raw* trajectory rarely dips below FAD before projection (smoother chart, fewer
  projections fire).

### Tests (prove the invariant by construction, not by clamp)
- Property test, all 6 series × a grid of knowledge_dates: `DFF_t ≥ FAD_t` at every
  trajectory step **and** tail. (Generalizes `tests/test_dashboard_maturity_invariant.py`
  from 4 scalar cases to full-trajectory + tails.)
- Regression fixture EB-1 India PD 2025-04-29: FAD maturity unchanged (≈2027-03) AND
  DFF ≤ FAD at every horizon cell.
- `reconcile_pair` units: `w=1` reproduces the current clamp exactly; `w=0` moves only
  DFF; `w=0.5` meets in the middle; already-ordered pairs pass through untouched.

### Migration / validation
- Re-run `scripts/vqs/evaluate_model.py` + `compute_prediction_accuracy --metric
  composite`: FAD MAE identical (untouched at w→1), DFF MAE within noise (proves we
  did NOT import FAD's noise into India's smooth DFF). Add a backtest slice counting
  pre-reconciliation violations across history — expect ≈0 (confirms it's a safety net
  for extrapolation artifacts, rarely load-bearing on real data).
- Republish predictions + regenerate `spaghetti.html` only if the in-solver floor
  upgrade is taken (reconciliation itself lives in the display/consumer layer).

## Interaction with other VQS work
Orthogonal + compatible with seasonal conditioning / fallback-series seasonal-median /
direction-first hybrid (they change *how each series' trajectory is produced*; B
operates *after* production). The India FY-phase spread-widening is the one
intersection: a good regime-conditioned spread signal from that work is the natural
upgrade path from B's static/calibration `w` toward Option C.
