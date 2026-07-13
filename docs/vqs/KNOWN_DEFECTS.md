# VQS / prediction-code known-defect register

Current-state register of open correctness defects in the prediction system, from
the 2026-07-13 thorough audit (5 parallel reviewers over `lib/business/vqs/*`,
`scripts/publish_predictions.py`, `scripts/vqs/*`; every finding then
adversarially re-verified against the code). Keep this current: strike items as
they're fixed (cite the commit), add new ones as found. This exists because
prediction bugs kept getting rediscovered on each touch — this is the map.

**Legend** — Impact: LIVE (changes shipped `PredictedCutoff`/dashboard) ·
TUNE (corrupts backtest/tuning objective) · BACKTEST (eval-only) · LATENT
(unreachable with current callers) · DEAD (not on any live path). Confidence:
certain / likely / design (judgment call). Ship class: SAFE (no prediction-value
change — fixable directly) · PATH2 (changes predictions → off-prod regen +
graduate, needs backtest re-validation) · DECISION (needs product judgment).

## ✅ Fixed 2026-07-13 (commit b7bf119) — SAFE subset
- **A5-F7** `load_stored_predictions_bulk` had no `order_by` → nondeterministic pick
  when multiple horizons target one month; the 1m stored line could score a stale 6m
  prediction. Now orders ascending `prediction_date` (1m wins).
- **A5-F11** `get_prediction_for_series` dropped `movement_probability` (bulk path kept it).
- **A3-F12** `get_historical_issuance_median` crashed on null `reference_period_start`.
- **A4-F10** checkpoint reload crashed on null `actual_cutoff` (horizon>1 rows).
- **A4-F13** `compute_composite_metric` returned 0.0 ("perfect", picked as tuning optimum)
  when no evaluated horizon carried a weight → now `inf` + warn.

---

## ✅ THEME 1 — "Current/Unavailable" stale-cutoff (systemic, LIVE) — CODE FIXED 2026-07-13
Root cause: `get_cutoff_at_date` reads a cache filtered `cutoff_date__isnull=False`
(`data_cache.py:64`), so for a series that has gone **Current/Unavailable** it returns
the last *real* cutoff (years old) instead of None. The correct helpers
`is_current_at_date` / `is_unavailable_at_date` / `_latest_full_entry_at_date` exist
but were applied inconsistently. Every consumer that reasoned "None ⇒ Current" was wrong.
Fix: applied the knowledge-date-aware `is_current_at_date` / `is_unavailable_at_date`
predicates at every consumer site. Regression tests in
`tests/test_prediction_audit_fixes.py::TestCurrentUnavailableGuard`.
**Code + tests landed on `main`; PATH2 graduation (regen + graduate the corrected
predictions) is bundled into the combined graduation (ticket #7 / fix-4).**
- ✅ **A3-F4** [LIVE,PATH2] GBM `_get_eb1_surplus_indicator` + `_get_row_velocity` now use
  `is_current_at_date` (were `cutoff is None`, which never fired). `gbm_expert.py`.
- ✅ **A2-F7** [LIVE,PATH2] Unavailable guard now applies to FS too; EB october-reset
  framing kept EB-only, generic Unavailable explanation for FS. `publish_predictions.py`.
- ✅ **A1-F4** [LIVE,PATH2] `predict_next_bulletin_and_maturity` non-eligible branch now
  has the Current+Unavailable→None guard (mirrors `predict_regime_switched`). `solver.py`.
- ✅ **A5-F2** [PATH2] `CascadeModel` bonus now fires for a Current higher-pref series
  (uses `is_current_at_date`). `supply/cascade.py`.
- ✅ **A5-F9** [experimental] `compute_backlog_depth` → 0 for Current, None for Unavailable
  (was huge phantom backlog). `fy_utilization.py`.
- **A2-F3** [LIVE,certain,PATH2] → **RE-GROUPED to Theme 4** (multi-horizon): every FS
  series publishes `predicted_date=None` in `--horizon>1` runs because the non-eligible
  persistence branch returns only one month (`first_future`); this is a multi-horizon
  dispatch bug, fixed with the rest of Theme 4. `publish_predictions.py:393-401`.
- **A4-F7** [TUNE,likely] → **RE-GROUPED to Theme 3** (tuning-metric): warmup/weight-update
  paths train on is_current sentinel actuals the error metrics exclude — a metric-integrity
  issue, fixed with the accuracy_metrics cluster. `accuracy_metrics.py:166-174`.

## ✅ THEME 2 — GBM training-label off-by-one + leakage + cache key — CODE FIXED 2026-07-13
Code + regression tests landed on `main`; PATH2 graduation bundled into the combined
rollout (ticket #7). Tests: `TestGbmTrainingLabels` (label arithmetic + cache-key +
walk-forward exclusion). **Theme 2 fixes sit directly under fix-4's tuning objective, so
fix-4 MUST re-run on this corrected code.**
- ✅ **A3-F3** [LIVE,certain,PATH2,HIGH] all 4 GBM caches (`reg1m`/`direct`/`clf`/`quantile`)
  now include `action_type` in the key → filing no longer served from the final_action model.
- ✅ **A3-F1** [LIVE+TUNE,PATH2] 1m label now `cutoff(B) − cutoff(B−1)` (was `cutoff(B+1) −
  cutoff(B−1)` = 2 transitions); horizon target now anchored on B (`bulletin.publication_date
  + (h−1) months`) so h=1 collapses to B and h transitions = h, not h+1. `gbm_expert.py`.
- ✅ **A3-F2** [TUNE,certain] 1m: label bulletin B is `< knowledge_date` by construction now
  (no `next_b`). Horizon: added `if target_b.publication_date >= knowledge_date: continue`
  walk-forward guard so the label is always observable at kd.
- ✅ **A3-F5** [LIVE,certain,PATH2] `_build_features_for_series(mask_demand_drop=True)` default;
  the two training builders pass `False` → training keeps all features (matches §17 ablation),
  inference still masks. `gbm_expert.py`.
- NOTE: calibration backtest twins A3-F6 (same off-by-one) + A3-F7 (unobservable actuals)
  remain in Theme 3 (`calibration.py`).

## ✅ THEME 3 — backtest/tuning-metric integrity — CODE FIXED 2026-07-13 (commits 1f6406f + this)
These corrupted the objective the §24/fix-4 re-tune optimizes; **fixed BEFORE re-running
fix-4**. Aggregator part = commit 1f6406f (Theme 3a); accuracy_metrics + calibration =
this commit (Theme 3b). Tests: `TestAggregatorWeightIntegrity`, `TestDirectionCorrectSymmetry`.
- ✅ **A4-F1** [TUNE→LIVE,certain] `warmup_history` now scores each bulletin at `pub_date−1`
  (was pub_date, giving persistence loss 0 every step → weight collapse). `aggregator.py`.
- ✅ **A4-F2** [TUNE] online walk-forward update no longer feeds future (3/6/12-mo-ahead)
  actuals — restricted to the immediately-observable next-bulletin actual. `accuracy_metrics.py`.
- ✅ **A4-F5** [BACKTEST] `_direction_correct` extracted + made symmetric: held-month
  (actual==0) counts a predicted move as WRONG, not None. `accuracy_metrics.py`.
- ✅ **A4-F6** [BACKTEST] long-term metric: predictions whose ready-month is between the last
  bulletin and today now score `None` (unverifiable), not a phantom `error_days=0`.
- ✅ **A4-F9** [BACKTEST] online update runs ONLY at horizon 1, so the h-actual is never fed
  as the h=1 actual. `accuracy_metrics.py`.
- ✅ **A4-F12** [BACKTEST] multi-horizon trim now `_add_months(b, max_h−1)` → last evaluable
  bulletin kept. `accuracy_metrics.py`.
- ✅ **A4-F7** [TUNE] (re-grouped from Theme 1) resolved by removing the leaky
  `_build_actuals_by_horizon` online path (its only caller was the A4-F2 update).
- ✅ **A3-F6** [BACKTEST] calibration backtest supplement 1m actual now = cutoff(B) not
  cutoff(B+1) (same fix as A3-F1). `calibration.py`.
- ✅ **A3-F7** [BACKTEST] calibration skips stored predictions whose target month is on/after
  knowledge_date (actual not yet observable). `calibration.py`.
- ✅ **A4-F3/F4** [TUNE] Expert + Contextual aggregator weight keys now include `action_type`.
  `aggregator.py`; `contextual_aggregator.py`.
- ✅ **A4-F8** [TUNE] abstaining experts get the field's mean active-loss factor → relative
  weight unchanged (was factor 1.0, which ballooned a sleeper's weight). `aggregator.py`.
- **A3-F2** (Theme 2) also landed here — fixed in Theme 2.

## ✅ THEME 4 — multi-horizon backfill semantics — CODE FIXED 2026-07-13
Code + tests landed on `main`. Test: `TestMultiHorizonKnowledgeDate` (primary + fallback
horizon-gap). PATH2 graduation bundled into the combined rollout.
- ✅ **A2-F1** [LIVE,certain,PATH2] `get_knowledge_date_for_target` now uses `earlier =
  target − (N−1) months` (+ consistent fallback), so the computed `horizon_m` equals N, not
  N+1. Fixes the boundary mis-dispatch (`--horizon 11`→h=12 etc.). `publish_predictions.py`.
- ✅ **A2-F2** [LIVE,PATH2] calibrated CI now keyed `horizon=max(1, horizon_m)` — the horizon
  the point prediction was dispatched at (agrees with A2-F1; robust to future divergence).
- ✅ **A2-F3** [LIVE,certain,PATH2] (from Theme 1) FS extraction now falls back to
  `outcome.predicted_cutoff` (flat persistence, None for Current/Unavailable) instead of None,
  so `--horizon>1` FS rows publish the correct flat value. `publish_predictions.py`.
- ✅ **A2-F4** [LIVE,DECISION] default backfill end capped at the current month (was +2 months)
  → no future-target rows with a future `prediction_date` mislabeled 1m polluting h=1
  calibration. The genuine next-month forecast is produced by the default no-args path.

## ✅ THEME 5 — queue-physics value bugs — CODE FIXED 2026-07-13 (commit 4006065 + this)
Physics-value fixes. Commit 4006065 (5a) = A5-F3/F4/F5/F6 + A1-F7/F8; this commit (5b) =
A1-F6 + A3-F10. Tests: `TestQueuePhysics`. PATH2 graduation bundled into the combined rollout.
- ✅ **A5-F3** [LIVE,certain] `advance_cutoff` advances to the first of the NEXT month when a
  bucket is fully served (was the consumed bucket's month). `queue_snapshot.py`.
- ✅ **A5-F4** [LIVE,certain] naive demand spread floor-divides + distributes the remainder
  (was `max(1, n//n_months)` → phantom applicants). `demand.py`.
- ✅ **A5-F5** [LIVE,certain] PERM-lag convolution accumulates float mass per bucket + apportions
  via largest-remainder (`_apportion_ints`) instead of per-bin round(). `demand.py`.
- ✅ **A5-F6** [LIVE,likely] convolution anchors at the reference-period MIDPOINT. `demand.py`.
- ✅ **A1-F7** [LIVE,certain] `get_retrogression_months_from_history` returns the MEDIAN
  (day-based, includes sub-month retros). `solver.py`.
- ✅ **A1-F8** [LIVE,certain] October retro preserves the day-of-month (was clamped to day 1).
  `solver.py`.
- ✅ **A1-F6** [LIVE,likely] `expert_i485_queue_depth` uses only the single freshest monthly
  snapshot (was a 120-day window → ~4× density). `expert_pool.py`.
- ✅ **A3-F10** [LIVE,certain] `_get_i485_rows_most_recent` freshness now measured vs
  `knowledge_date` (returns [] if the newest snapshot is >180d stale). `gbm_expert.py`.
- **A5-F8** [likely] → **RE-GROUPED to Theme 7**: `compute_utilization_rate`'s 7%-cap
  denominator feeds ONLY the experimental (off-by-default) FY-transition path, and the correct
  fix needs the allocator's per-country shares. Fix with Theme 7 / when FY-transition is enabled.
  `fy_utilization.py:107-108`.

## ✅ THEME 6 — solver output-consistency — CODE FIXED 2026-07-13 (this commit)
Solver-internal consistency + attribution. PATH2 graduation bundled into the combined rollout.
Verified by the existing solver suites staying green + the combined backtest (solver internals
are impractical to unit-test without heavy fixtures).
- ✅ **A1-F1** [LIVE,certain] `maturity_month` computed AFTER the persistence blend from the final
  dampened + headline-consistent trajectory; removed the premature in-loop break. `solver.py`.
- ✅ **A1-F2** [LIVE,certain] `results[0]` pinned to the headline `final_next_cutoff` so the
  spaghetti month-1 point agrees with the published number. `solver.py`.
- ✅ **A1-F10** [LIVE,certain] `predict_regime_switched` non-eligible branch now honours
  `priority_date` (matures an already-current applicant). `solver.py`.
- ✅ **A1-F3** [LIVE,certain] multi-step trajectories now pass `lookback_years=4` (matching the
  single-step experts) so they don't chain pre-retrogression seasonal medians. `expert_pool.py`.
- ✅ **A1-F11** [LIVE,likely] `expert_physics`/`trajectory_physics` start the loop at
  `first_future` (+ supply for that month), aligned with the other experts. `expert_pool.py`.
- ✅ **A2-F5** [LIVE,certain] explanation generated AFTER the calibrated CI override (injected into
  metadata) so a wide CI isn't captioned "narrow". `publish_predictions.py`.
- ✅ **A2-F6** [attribution] FS `model_name` now `persistence` (was the dead "vqs_ensemble"
  fallback). `publish_predictions.py`.

## THEME 7 — FY-transition / october-reset (mostly NOT live — experimental) → ticket (low)
`fy_transition_model` is experimental/off by default (README). Fix before enabling.
- **A5-F8** [likely] (re-grouped from Theme 5) `compute_utilization_rate` divides by the 7%
  per-country cap even for ROW/All-Chargeability (which isn't 7%-capped) → ROW rates ~8.6×,
  uncapped >1. Feeds ONLY the experimental FY-transition path. The correct denominator needs
  the allocator's per-country share (`supply/country_cap.py`), so fix it together with the
  FY-transition enablement, not as a blind constant swap. `fy_utilization.py:107-108`.
- **A5-F1** [BACKTEST,certain] LOO excludes the wrong year (fiscal_year=cal year vs
  `get_fiscal_year` key) → Aug/Sep target leakage. `fy_transition_model.py:119-120`.
- **A5-F12** [certain] September momentum `*1.2` amplifies an *advance* under a deceleration
  signal (wrong direction). `fy_transition_model.py:264-266`.
- **A5-F13/F14** [low] knowledge-date `>=` vs `<=` boundary; current-util partial-FY vs
  training end-of-FY scale mismatch. `fy_utilization.py:60`; `fy_transition_model.py:132-136`.
- **A3-F9** [BACKTEST→LIVE-precedent,likely] `find_reset_events` mislabels U-spells that extend
  past September (FY from spell's last month pushes the reset search a year forward).
  `october_reset.py:183-185`.

## THEME 8 — design / judgment calls (DECISION) → ticket
- **A1-F9** VOLATILE uses `cv = vol/avg_abs`, so a symmetric oscillation (cv≈1<2) classifies
  STALLED not VOLATILE. `regime.py:81-97`. Intended? both route to persistence but weights differ.
- **A1-F13** asymmetric CI comment ("overshoots more likely" ⇒ truth<pred) contradicts the band
  `[P−30%, P+70%]` (extends up). `solver.py:886-894`. One of comment/sign is wrong.
- **A3-F8** insufficient-data calibration fallback `max(60, 90*h//2)` gives ±60d for h=1 while its
  own comment + the exception path say ±90d. `calibration.py:186-189`.
- **A3-F11** `_get_issuance_drop_ratio` ignores its `visa_class` param (sums all classes).
  `gbm_expert.py:449-475`. Class-blind proxy or bug?
- **A5-F10** `seasonal_adjustment_map` keyed by the predicted cutoff's month, not the target
  bulletin month (contradicts docstring); also bypasses forward/back caps. LATENT (empty default).
  `meta_params.py:176-180`.
- **A4-F11** `use_contextual_ensemble` param of `compute_bulletin_accuracy` accepted but never
  used → contextual A/B silently compares the solver to itself. `accuracy_metrics.py:190`.
- **A1-F12** `trajectory_oppenheim_pace` missing `facts` param → TypeError if selected via the
  6-arg convention (LATENT — selector never returns it today). `expert_pool.py:708-732`.
- **A1-F14/F15** `calibrate_queue_depth` returns None on demand≤0 despite valid rate;
  `_cached_physics_prediction` lru_cache not invalidated across an ingest. `solver.py:229-231`;
  `expert_pool.py:157-165`.
- **A3-F13** leap-day crash in `lookback_years` cutoff (no day-clamp) — unreachable until 2104
  with current callers. `seasonal_predictor.py:52`.

## Cleared by reviewers (checked, NOT defects)
All 7 `date(y,month+1,1)` sites are December-guarded; `get_cutoff_at_date` as-of `<=` semantics
correct; no publish dispatch fall-through / no `lower>upper` CI / no DB unique-constraint dup;
GBM feature builders bound their own reads by `pub_date < knowledge_date` (omitted `facts=` in
publish causes no leakage); Hedge/softmax signs correct; `expert_gbm_gated` gate direction correct;
`classify_regime` most-recent-first ordering correct.
