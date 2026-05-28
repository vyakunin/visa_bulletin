# Job Title Data Coherence Rules

Rules for job title clustering, representative titles, and end-to-end coherence (autocomplete, directory, profile, Similar Job Titles).

## Rule: Pipeline Order for Job Title Data

**Job title stats and slugs must be updated in this order:**

1. **cluster_job_titles** – clusters raw job titles into `JobTitle` / `JobTitleCluster`
2. **update_job_title_cluster_stats** – sets `total_filings`, `avg_salary`, and **canonical_title** per cluster
3. **populate_job_title_slugs** – backfills `slug` for clusters that have none (slug derived from `canonical_title`)

**Scripts:** `scripts/cron/refresh_data.sh` runs them in this order. Do not reorder or skip.

## Rule: Representative Title Selection

**update_job_title_cluster_stats** chooses the representative title:

- **JobTitleCluster.canonical_title:** Most frequent raw `SalaryRecord.job_title` among records whose normalized title equals the cluster's most frequent normalized form. Order: (1) count DESC, (2) shorter length as tiebreaker.
- **JobTitle.title:** Most frequent raw `job_title` among records for that entity.

See `lib/business/salary/README.md` for the full query trace (Total Filings, Top Employers, Representative Name).

## Rule: Check Job Title Coherence on Deployment

After deploying or running `refresh_data`, verify job title coherence. See `docs/PIPELINE_RUNBOOK.md` for the full smoke test commands (autocomplete API, profile count match, URL resolution, Similar Job Titles check).

**Quick check:**
```bash
# Run the integration test
bazel test //tests:test_job_title_profile_view
```
