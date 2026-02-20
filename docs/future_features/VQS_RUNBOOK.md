# VQS Runbook

One-page reference for adding I-140 data and re-running accuracy.

---

## How to Add a New I-140 File

1. **Obtain the file** – Download USCIS “I-140 Receipts by Category and Country” quarterly (or annual) data. Place under `data/vqs/` or any path accessible from the project root.

2. **Ingest with publication date** – Use `reference_period_end + 90d` as publication date so backtesting sees the data only after it would have been public:
   ```bash
   bazel run //scripts/vqs:ingest_uscis_i140 -- \
     --file /path/to/i140_rec_by_class_country_FY2024_Q2.xlsx
   ```
   The script sets `publication_date = reference_period_end + 90` by default. Override if needed:
   ```bash
   bazel run //scripts/vqs:ingest_uscis_i140 -- \
     --file /path/to/file.xlsx --publication-date 2024-06-15
   ```

3. **Verify** – Check row count:
   ```bash
   bazel run //:run_sql -- --query "SELECT metric, COUNT(*) FROM raw_facts_ledger GROUP BY metric"
   ```

---

## How to Re-Run Accuracy After a Change

1. **Clear checkpoint** (optional; required for full recompute):
   ```bash
   rm -f /tmp/vqs_ckpt/bulletin_accuracy_ckpt.json /tmp/vqs_ckpt/longterm_accuracy_ckpt.json
   ```

2. **Run accuracy** (bulletin + long-term, with plots):
   ```bash
   bazel run //scripts/vqs:compute_prediction_accuracy -- \
     --metric both --plot \
     --output-dir /tmp/vqs_accuracy \
     --checkpoint-dir /tmp/vqs_ckpt
   ```

3. **Outputs** (under `--output-dir`):
   - `bulletin_accuracy.json` – Raw prediction vs actual per cutoff.
   - `longterm_accuracy.json` – Long-term prediction data (with `horizon_months`, `horizon_bucket`).
   - `longterm_accuracy_summary.json` – Aggregated by horizon bucket and by (visa_class, country).
   - `bulletin_accuracy_plot.html`, `longterm_accuracy_plot.html` – Interactive Plotly (if `--plot`).

4. **Quick comparison** (recent bulletins, excl. EB4):
   ```bash
   python3 -c "
   import json
   with open('/tmp/vqs_accuracy/bulletin_accuracy.json') as f:
       rows = json.load(f)
   valid = [r for r in rows if r['error_days'] is not None]
   recent = [r for r in valid if r['bulletin_date'] >= '2025-10-01' and r['visa_class'] != '4th']
   n = len(recent)
   if n:
       mean_err = sum(r['error_days'] for r in recent) / n
       over = sum(1 for r in recent if r.get('predicted_cutoff') and r.get('actual_cutoff') and r['predicted_cutoff'] > r['actual_cutoff'])
       print(f'Recent (excl EB4): n={n}, mean_err={mean_err:.1f}d, over_predict={over} ({100*over/n:.1f}%)')
   "
   ```

---

## Beating the "No Change" Baseline

The naive baseline (next cutoff = previous cutoff) currently has **lower mean error** than the model. To improve and validate:

- **Proposal:** `docs/future_features/VQS_BEAT_NO_CHANGE_PROPOSAL.md` – root cause, stickiness/threshold, caps, low-confidence fallback, blend, calibration.
- **Compare model vs baseline:** Run accuracy, then compare mean error and win rate (see proposal § Validation).

---

## Paths and Commands Summary

| Purpose | Command / path |
|--------|-----------------|
| Ingest I-140 | `bazel run //scripts/vqs:ingest_uscis_i140 -- --file PATH` |
| Compute accuracy | `bazel run //scripts/vqs:compute_prediction_accuracy -- --metric both --plot --output-dir DIR --checkpoint-dir CKPT` |
| Output dir | e.g. `/tmp/vqs_accuracy` |
| Checkpoint dir | e.g. `/tmp/vqs_ckpt` |
| Bulletin raw | `{output-dir}/bulletin_accuracy.json` |
| Long-term raw | `{output-dir}/longterm_accuracy.json` |
| Long-term summary | `{output-dir}/longterm_accuracy_summary.json` |
