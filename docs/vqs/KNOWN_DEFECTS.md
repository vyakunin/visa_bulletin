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

## THEME 2 — GBM training-label off-by-one + leakage + cache key (LIVE + TUNE) → ticket
- **A3-F3** [LIVE,certain,PATH2] all 3 GBM caches omit `action_type` (`gbm_expert.py:744,
  786,828,876`) → publish loops both action types in one process, so `filing` predictions
  are served from the **final_action-trained** model (calibration.py itself notes the two
  have very different distributions). HIGH.
- **A3-F1** [LIVE+TUNE,likely,PATH2] 1m + horizon training labels span **h+1** transitions:
  `kd = B.pub-1` anchors `current` on bulletin B−1, but the label uses `next_b` = B+1 →
  `actual_move` = B+1 − B−1 = 2 transitions for a 1-transition prediction. Model learns ~2×
  the movement it's asked to produce. `gbm_expert.py:643-655,694-712`. Correct label = cutoff
  at `bulletin.publication_date` (B), not `next_b`. **Sits directly under fix-4's tuning
  objective** (`compute_gbm_only_objective` trains via this path).
- **A3-F2** [TUNE,certain] walk-forward leakage: only *feature* bulletins are filtered
  `< knowledge_date`; the *label* bulletin (`next_bulletins ... > bulletin.pub`) is not, so
  in backtests/backfills the label can be the very target being predicted (horizon builder
  pulls labels up to kd+h+35d). Backtest MAE/F1 optimistically biased → tuning optimizes a
  leaky metric. `gbm_expert.py:633 vs 644, 684 vs 697-704`.
- **A3-F5** [LIVE,certain,PATH2] demand-drop masking applied in **training** too (comment
  says inference-only) → shipped model ≠ the §17 ablation design. `gbm_expert.py:583-587`.

## THEME 3 — backtest/tuning-metric integrity (TUNE, qualifies fix-4) → ticket
These corrupt the objective the §24/fix-4 re-tune optimizes; fix + re-validate BEFORE
trusting any re-tune result.
- **A4-F1** [TUNE,certain] `ExpertAggregator.warmup_history` replays with
  `knowledge_date = the scored bulletin's own pub_date`; `get_cutoff_at_date` is inclusive
  → persistence gets loss 0 every warmup step → weights converge to persistence regardless
  of skill (live path uses t−1day). `aggregator.py:301,292-297`.
- **A4-F2** [TUNE,likely] online update feeds actuals up to 11 months in the future into the
  weights used for the next scored predictions → lookahead leak. `accuracy_metrics.py:364-376`.
- **A4-F5** [BACKTEST,certain] `direction_correct`: (actual==0, pred≠0) → None → *excluded*
  not counted wrong, while (0,0) counts correct → asymmetric, inflates trend accuracy on
  the common held-month case. `accuracy_metrics.py:962-968,892-898`.
- **A4-F6** [BACKTEST,certain] long-term metric records `error_days=0` (perfect) for
  unverifiable predictions between last bulletin and today. `accuracy_metrics.py:608-611`.
- **A4-F9** [BACKTEST,certain] `horizon!=1` runs feed the h-actual as the h=1 actual to
  `aggregator.update`. `accuracy_metrics.py:369-376`.
- **A4-F12** [BACKTEST,certain] multi-horizon bulletin trim off-by-one (`_add_months(b,max_h)`
  should be `max_h-1`) → last evaluable bulletin dropped. `accuracy_metrics.py:802-804`.
- **A4-F7** [TUNE,likely] (re-grouped from Theme 1) warmup/weight-update paths train on
  is_current sentinel actuals the error metrics exclude. `accuracy_metrics.py:166-174`.
- **A3-F2** (see Theme 2) also lands here.
- **A3-F6** [BACKTEST,likely] calibration backtest-error supplement has the same B-1→B+1
  off-by-one as A3-F1. `calibration.py:99-123`.
- **A3-F7** [BACKTEST,likely] calibration includes stored-prediction errors whose actual
  wasn't observable at knowledge_date (filters only on prediction_date). `calibration.py:73-74`.
- **A4-F3/F4** [TUNE,likely] Expert + Contextual aggregator weight keys omit `action_type`
  → final_action/filing share one weight vector + 2nd action's warmup skipped.
  `aggregator.py:35-36,275-276`; `contextual_aggregator.py:46-47`.
- **A4-F8** [TUNE,likely] abstaining experts get Hedge loss 0 → a never-predicting expert's
  weight grows to 1 and swamps the blend when it wakes. `aggregator.py:203-204`.

## THEME 4 — multi-horizon backfill semantics (LIVE, `--horizon>1`) → ticket
- **A2-F3** [LIVE,certain,PATH2] (re-grouped from Theme 1) every FS series publishes
  `predicted_date=None` in any `--horizon>1` run: FS is not physics-eligible so the
  non-eligible branch returns one month (`first_future`); `next(r.month==target)` → None.
  Fix with the multi-horizon dispatch. `publish_predictions.py:393-401`.
- **A2-F1** [LIVE,certain,PATH2] `--horizon N` computes an actual month-gap of **N+1** (earlier
  bulletin pub=1st, knowledge=prev-day), so dispatch/GBM-arg/stored `prediction_date` all encode
  N+1 while labeled N; boundary mis-dispatch (`--horizon 11`→h=12 routes China EB-1 to GBM not
  RS; `--horizon 5`→h=6). `publish_predictions.py:169-183,293-296`.
- **A2-F2** [LIVE,likely,PATH2] calibrated CI keyed `horizon=max(1,horizon_months)` while the
  point prediction is at `horizon_m`(=N+1) → CI bucket empty → silent ±270d default.
  `publish_predictions.py:508-516`.
- **A2-F4** [LIVE,likely,DECISION] default backfill end = +2 months → future `prediction_date`,
  row mislabeled 1m, pollutes h=1 calibration. `publish_predictions.py:617-618`.

## THEME 5 — queue-physics value bugs (LIVE physics-eligible, PATH2) → ticket
- **A5-F3** [LIVE,certain] `advance_cutoff` returns the consumed bucket's month, not the first
  unserved, at an exact supply/bucket boundary → cutoff under-advances one month.
  `queue_snapshot.py:71`.
- **A5-F4** [LIVE,certain] naive demand spread `max(1, n//n_months)` adds phantom applicants
  when receipts < months (n=2 over a quarter → 3 added). `demand.py:160-161`.
- **A5-F5** [LIVE,certain] PERM-lag convolution per-bin `round()` loses mass (n=10 over 20 bins
  @0.05 → round(0.5)=0 each → 0 added). `demand.py:151`.
- **A5-F6** [LIVE,likely] convolution anchors all receipts at `reference_period_start` → PDs
  bucketed ~1mo early vs the naive path. `demand.py:149-150`.
- **A1-F7** [LIVE,certain] `get_retrogression_months_from_history` docstring says median but
  computes **mean** (and drops sub-month retrogressions). `solver.py:333,371-379`.
- **A1-F8** [LIVE,certain] October retro clamps day→1 → up to +30d extra retrogression each
  simulated October. `solver.py:277-282`.
- **A1-F6** [LIVE,likely] `expert_i485_queue_depth` sums pending across a 120-day window (multiple
  monthly snapshots) for a `_monthly` metric → ~4× density. `expert_pool.py:315-326`.
- **A3-F10** [LIVE,certain] `_get_i485_rows_most_recent` 6-month freshness guard is vacuous
  (`>= most_recent-180d AND == most_recent`) → arbitrarily stale I-485 snapshots feed features.
  `gbm_expert.py:228-230`.
- **A5-F8** [LIVE-ish,likely] fy_utilization denominator always uses the 7% cap → ROW rates ~8.6×,
  uncapped >1, inconsistent with the supply model's shares. `fy_utilization.py:107-108`.

## THEME 6 — solver output-consistency (LIVE, PATH2) → ticket
- **A1-F1** [LIVE,certain] `maturity_month` is set from the pre-persistence-blend trajectory then
  every result is dampened + the loop `break`s → reported maturity is optimistic and the true
  post-dampening maturity month is never simulated. `solver.py:1026-1046`.
- **A1-F2** [LIVE,certain] headline `predicted_cutoff` (pure-ensemble→persistence) ≠ `results[0]`
  (physics+ens_traj→persistence); when `ensemble_traj is None`, `results[0]` stays pure physics
  while the headline is ensemble → spaghetti month-1 disagrees with the published number.
  `solver.py:1010-1020` vs `1048-1051`.
- **A1-F10** [LIVE,certain] `predict_regime_switched` non-eligible branch ignores `priority_date`
  → maturity None even for an already-matured applicant. `solver.py:484-492`.
- **A1-F3** [LIVE,certain] multi-step trajectories omit `lookback_years=4` that the single-step
  experts pass → steps 1+ chain pre-retrogression seasonal medians (phantom +30d/mo).
  `expert_pool.py:517-520,593-596,628-631`.
- **A1-F11** [LIVE,likely] `expert_physics`/`trajectory_physics` start the loop at `knowledge_date`
  not `first_future` → supply for the wrong month + trajectory index misaligned vs other experts
  the solver blends positionally. `expert_pool.py:142,150,657,660`.
- **A2-F5** [LIVE,certain,SAFE-on-next-publish] explanation text generated before the calibrated CI
  overrides low/high → a wide CI captioned "narrow". `publish_predictions.py:499`.
- **A2-F6** [attribution] FS `model_name` always "vqs_ensemble" though it's pure persistence;
  `m_meta.get("model")` is dead. `publish_predictions.py:404-405`.

## THEME 7 — FY-transition / october-reset (mostly NOT live — experimental) → ticket (low)
`fy_transition_model` is experimental/off by default (README). Fix before enabling.
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
