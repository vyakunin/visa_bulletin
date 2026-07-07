# Job Title Data Coherence Rules

Rules for job title clustering, representative titles, and end-to-end coherence (autocomplete, directory, profile, Similar Job Titles).

## 🚨 Rule: Touching a clustering INPUT obligates re-running the dependent clustering pipeline

**Clustering is a derived layer built on top of `salary_record`. Any change to a clustering INPUT leaves the derived layer stale until you re-run the matching pipeline. Whenever you tweak a clustering dependency — assess + re-cluster in the same workstream; never ship the input change alone and assume the cluster layer "self-heals".**

The two input→pipeline dependencies:

| If you change… (input) | This derived layer goes stale | Re-run pipeline |
|---|---|---|
| `salary_record.job_title` (bulk edit, reingest, backfill, normalization fix) | `JobTitle` / `JobTitleCluster`, canonical_title, slugs, directory + profile pages, autocomplete, "Similar Job Titles" | `cluster_job_titles` → `update_job_title_cluster_stats` → `populate_job_title_slugs` (order below) |
| `salary_record.employer_name` / employer FK (reingest, rename, merge) | `Employer` clusters | `cluster_existing_employers` (see `employer_clustering.md`) |

**The in-place-mutation gotcha (the trap that motivated this rule):** `cluster_job_titles` phase 3 (`_phase3_link_records`) only links rows where `job_title_entity_id IS NULL`. It is built for the **append** case (a normal weekly refresh INSERTs new rows with NULL entity, links them) — it does **NOT** re-link rows whose title was **mutated in place**. So after any in-place edit of `job_title` on existing rows, those rows keep their **stale** entity link and a plain re-cluster will NOT fix them. You MUST first reset the changed rows' link:

```sql
-- NULL the entity link on the rows whose title changed (e.g. all PERM rows after a PERM-title reingest)
UPDATE salary_record SET job_title_entity_id = NULL WHERE visa_program = 4;
```

then run the pipeline so phase 3 re-links them by current `(title_normalized, experience_level)`. (The same trap applies to employer clustering if employer names are ever mutated in place — verify whether its linker also skips already-linked rows before relying on a re-cluster to heal an in-place rename.) NULLing 1.5M FK values is a single heavy WAL-bound UPDATE on the constrained box (~8–15 min) — run it **off-prod on staging** per the heavyweight-task rule, not on the serving prod DB.

**This is a heavyweight Path-2 data task** (`branching.md`): run the re-cluster off-prod on staging against a prod-copy DB, validate coherence (counts, 0 stale links, spot-check sample rows + a rendered profile page), then graduate the DATA via `cutover.sh --data` — plus the `seo_publish.md` sitemap/freshness/CF-purge steps for the new job-title pages. Don't shortcut to a direct prod re-cluster.

Origin: 2026-06-25 — the `reingest-perm-titles` backfill mutated 393k PERM `job_title` values in place and shipped to prod; the job-title cluster layer (552k PERM rows ~37% pointing at clusters whose label no longer matched, 224k distinct PERM titles with no page) was left stale because a plain re-cluster's phase 3 skips non-NULL rows. Vladimir: *"update the rules to keep an eye on clustering whenever tweaking dependencies."*

## Rule: Pipeline Order for Job Title Data

**Job title stats and slugs must be updated in this order:**

1. **cluster_job_titles** – clusters raw job titles into `JobTitle` / `JobTitleCluster`
2. **update_job_title_cluster_stats** – sets `total_filings`, `avg_salary`, and **canonical_title** per cluster
3. **populate_job_title_slugs** – backfills `slug` for clusters that have none (slug derived from `canonical_title`)
4. **After any RE-cluster: `populate_job_title_slugs --refresh-all --min-filings 100 --skip-collisions`** – a re-cluster changes `canonical_title` on existing clusters, leaving their slugs stale (the 06-25 re-cluster left 513/1,265 indexable clusters on requisition-ID / typo'd URLs, incl. the 117k-filing Software Engineer cluster on `software-engineer-161559609`). The scoped refresh reclaims the clean derived slug where free (biggest-first, never renames INTO a counter-suffixed slug, multi-pass); old slugs 301 via the `slug_redirects` ladder. Indexable scope only — renaming noindexed thin pages is pure churn. Then flush Redis + CF purge + resubmit the sitemap (`seo_publish.md`).

**Scripts:** `scripts/cron/refresh_data.sh` runs 1–3 in this order. Do not reorder or skip.

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
