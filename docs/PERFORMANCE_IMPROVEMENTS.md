# Performance Improvements

Captures the production performance issues surfaced during the
2026-04-29 outage investigation, and the fixes proposed / shipped in
response. This doc reflects current state — issues that have been
addressed and merged are marked **Done**.

## Context

On 2026-04-29 production was effectively down for ~5 hours: every page
returned HTTP 504. Root cause was a feedback loop:

1. Bots crawling `/employer/<slug>/`, `/job-title/<slug>/`, and
   `/salaries/?employer=…` issued slow multi-table joins on
   `salary_record`.
2. Cloudflare/gunicorn disconnected at 60 s, but Postgres had **no
   `statement_timeout`** — the cancelled query continued running in the
   backend for **6+ hours** per stuck connection.
3. 11 such zombie queries × disk-bound 2 GB instance →
   `iowait` 80–90 %, all 3 gunicorn workers blocked → 504s on every
   request.

A single `/salaries/?employer=K%20CORPORATION` request observed during
recovery: planning time **5.7 s** (catalog from disk), execution time
**24.7 s**. Trigram index existed and was being used — the bottleneck
was elsewhere.

## Live measurements (2026-04-29 19:44 UTC)

| Metric                              | Value             | Notes                                              |
|-------------------------------------|-------------------|----------------------------------------------------|
| `salary_record` rows                | 1.46 M            | Table 631 MB, indexes 1.6 GB, total 2.23 GB       |
| Database total                      | 5.5 GB            |                                                    |
| `shared_buffers`                    | 128 MB (default)  | ~6 % of `salary_record`; thrashes constantly      |
| `effective_cache_size`              | 512 MB (default)  | Planner thinks half the DB fits in cache; it doesn't |
| `work_mem`                          | 2 MB (default)    |                                                    |
| `random_page_cost`                  | 4 (default)       | Spinning-disk default; we're on NVMe SSD          |
| `salary_record` `last_autoanalyze`  | 39 days ago       | 102 k mods since — planner stats stale            |
| `BurstCapacityPercentage`           | 0.03–0.07 %       | Depleted since 2026-04-24                          |
| `iowait`                            | 80–90 % sustained | Disk-bound                                         |
| `nvme0n1` utilisation               | 88–97 %           | At Lightsail 60 GB SSD baseline (~180 IOPS)       |
| Memory free                         | 73 MB / 1.9 GB    | Swap 580 MB used                                   |
| `salary_employer_cluster` rows      | 224 k             | 14 MB trigram index (`sr_ec_canonical_name_trgm`) |

## Issues identified

### 1. Postgres tuned for a default workstation, not a production server

`shared_buffers=128 MB` on a 1.9 GB box with a 5.5 GB database means
the buffer cache cannot hold even the hot indexes. Every query that
isn't already cached pays a full disk-read penalty.

**Fix:** raise `shared_buffers` to ~20 % of RAM, set
`effective_cache_size` to a realistic OS-cache estimate, raise
`work_mem` for sort/hash steps, and tell the planner the disk is
SSD-shaped.

```
shared_buffers = 384MB
effective_cache_size = 1200MB
work_mem = 8MB
maintenance_work_mem = 128MB
random_page_cost = 1.1
```

**Status: Done** (2026-04-29). Implemented as
`deployment/scripts/apply_postgres_tuning.sh`. Restart of postgres
required (settings annotated in postgresql.conf).
After applying: run `VACUUM (ANALYZE) salary_record;` to refresh
planner stats.

### 2. No `statement_timeout` — cancelled clients leak into 6 h zombies

Gunicorn/Cloudflare disconnect at 60 s, but the Postgres backend keeps
running until it finishes (potentially hours). A handful of these can
saturate disk.

**Fix:** set `statement_timeout = 45 s` on the application role and in
Django `DATABASES.OPTIONS`, with `0` (no limit) for migration commands
so DDL like `CREATE INDEX` is unaffected.

**Status: Done** (2026-04-29) — applied immediately during incident.
Code change in [django_config/settings.py](../django_config/settings.py)
DATABASES OPTIONS.

### 3. The `/salaries/?employer=…` query fans out before aggregating

Anatomy of the slow query:

```sql
SELECT AVG(wage_annual), MIN(wage_annual), MAX(wage_annual)
FROM salary_record
JOIN salary_employer
  ON salary_record.employer_id = salary_employer.id
JOIN salary_employer_cluster
  ON salary_employer.canonical_cluster_id = salary_employer_cluster.id
WHERE UPPER(canonical_name::text) LIKE UPPER('%K CORPORATION%')
  AND NOT is_worksite
  AND employer_name <> 'Unknown'
  AND wage_annual > 0;
```

Even with the trigram index, fanning a single search out to 152
clusters → 225 employers → 1 354 records and then re-aggregating from
disk on every request is wasteful — the same numbers will be the same
again next request.

**Fix:** denormalise four search-scope aggregates onto
`salary_employer_cluster`:

| Field                     | Meaning                                                 |
|---------------------------|---------------------------------------------------------|
| `search_record_count`     | Rows that pass the search filters in this cluster      |
| `search_avg_salary`       | Mean `wage_annual` over those rows (record-weighted)   |
| `search_min_salary`       | Min `wage_annual` over those rows                      |
| `search_max_salary`       | Max `wage_annual` over those rows                      |

Compute them from `salary_record` directly (one SQL aggregation, all
clusters at once) — not a mean-of-means like the existing
`avg_salary` field, which sums per-employer averages. Refresh nightly
via the existing `_update_cluster_statistics` step in the cron
pipeline, so no new cron entry is needed.

When the user selects a single cluster (see #5) and applies no other
filter, the search view reads these directly and skips the aggregate
query entirely.

**Status: Done** (2026-04-29). Migration `0045`, fields populated by
extending `_update_cluster_statistics` in
`scripts/salary/cluster_existing_employers.py`.

### 4. Aggregate and listing are two queries with the same expensive filter

`_cached_count_and_stats` runs a `.aggregate(...)` and a `.count()` —
two DB roundtrips with the same `WHERE` clause. Fix:

- Combine `count` + `Avg/Min/Max` into a **single** `.aggregate(...)`
  call so we make one trip instead of two.
- When the user has selected a specific cluster (slug present, no
  other filters), skip the aggregate path entirely and serve from the
  precomputed cluster row.

**Status: Done** (2026-04-29). View change in
`webapp/views/salary/search.py:salary_search_view`.

### 5. Employer filter uses `icontains` even when the user picked one from autocomplete

The autocomplete already returns each cluster's `slug`, but the
frontend only writes the display name into the form. The backend
re-resolves it via `__icontains`, which matches *every* cluster whose
canonical name contains the substring — exactly the slow trigram-heap
path.

**Fix:**

- Render a hidden `<input name="employer_slug">` next to the visible
  employer text input.
- In `autocomplete.js`, when a suggestion is selected, write
  `suggestion.slug` into that hidden input. When the user types
  manually without picking a suggestion, leave it blank and clear it
  on every keystroke.
- In the view, prefer `employer__canonical_cluster__slug=…` (B-tree
  index, microseconds) when the slug is populated. Fall back to the
  existing `__icontains` path only for free-text submissions.

**Status: Done** (2026-04-29).

## Issues identified but not addressed in this round

These are documented for future work; they are **not** part of the
2026-04-29 batch.

### 6. ~500 MB of indexes on `salary_record` are unused

From `pg_stat_user_indexes` (`idx_scan = 0` over ~3 months of DB
lifetime, including 2.5 days of post-graduation prod traffic).

Dropped on 2026-05-02 via `DROP INDEX CONCURRENTLY` directly on prod
(13 indexes, idempotent). Conservative subset: kept anything with
non-zero scans on the previous prod database.

| Index                                       | Size  |
|---------------------------------------------|------:|
| `salary_reco_employe_c93e9a_idx`            | 52 MB |
| `salary_reco_job_tit_7b8349_idx`            | 23 MB |
| `salary_record_employer_name_e42fa6a7` (+ `_like`) | 42 MB |
| `salary_record_job_title_89d21c95` (+ `_like`)     | 38 MB |
| `salary_reco_employe_892342_idx`            | 18 MB |
| `salary_reco_soc_cod_8cdf26_idx`            | 11 MB |
| `salary_record_soc_code_1b8d83ff` (+ `_like`)      | 20 MB |
| `salary_record_source_file_a0692cee`        | 11 MB |
| `salary_record_source_file_date_436fb5ad`   | 10 MB |
| `salary_record_ingest_version_id_ad9dc99b`  | 10 MB |

Result: `salary_record` index size 877 MB → 641 MB (−236 MB / −27%).
The dropped indexes had never been paged into RAM, so memory free
didn't change immediately — the win is reduced cache pressure going
forward and faster writes. No regressions on any main page.

**Status: Done** (2026-05-02, prod only — staging will pick this up
on next graduation; a migration is the durable record).

### A. Free-text employer search picks a fan-out plan

For `/salaries/?employer=<short-text>&page=N` (especially deep pages
crawled by bots), the planner does a **parallel index scan backward
on `wage_annual` + filter on the cluster join** thinking LIMIT+OFFSET
will let it stop early. For a substring like `'%STANDARD%'`, the join
filter rejects ~4 of every 5 rows, so it scans ~530k rows to find
300, doing ~134k cold disk page reads (~1 GB I/O). On idle DB this
runs in ~5 s, but under live disk contention it hits the 45 s
`statement_timeout` and gets cancelled. ~330 of these cancels per day
in prod logs.

**Fix:** restructure the ORM to resolve the cluster set first via the
trigram index on `salary_employer_cluster.canonical_name`, then drive
the salary_record query off `canonical_cluster_id__in=[…]`:

```python
cluster_ids = list(
    EmployerCluster.objects.filter(
        canonical_name__icontains=employer_filter
    ).values_list("id", flat=True)[:_MAX_CLUSTER_IDS]
)
records = records.filter(employer__canonical_cluster_id__in=cluster_ids)
```

Two queries instead of one, but each is cheap: the first hits the
GIN trigram index, the second hits the FK B-tree. The planner can no
longer trick itself into the "scan wage_annual DESC" plan because the
`canonical_cluster_id__in` filter is unambiguously selective. Cap at
2000 cluster ids so a bot typing one character (`'%A%'`) doesn't
produce a runaway IN-list — well above any meaningful real search.

This also covers issue B (the avg/min/max aggregate) — same filter
shape, same root cause.

**Status: Done** (2026-05-02). [webapp/views/salary/search.py](../webapp/views/salary/search.py).

### C. `_get_cluster_or_404` falls back to seq-scan icontains

[webapp/views/employers/profile.py:42](../webapp/views/employers/profile.py)
catches stale `/employer/<slug>/` requests by trying

```python
Employer.objects.filter(name_normalized__icontains=slug_normalized)
```

There's no GIN trigram on `salary_employer.name_normalized`, so this
seq-scans 287k rows per request (~1.1 s each in prod logs). Bots hit
stale Google-indexed slugs constantly so this fires a lot.

**Fix:** add `CREATE INDEX CONCURRENTLY se_name_normalized_trgm` —
mirror of the existing `sr_ec_canonical_name_trgm` on the cluster
table. ~10–15 MB index, drops these queries to <50 ms.

**Status: Done** (2026-05-02). Migration
[0046_employer_name_normalized_trigram_index.py](../models/migrations/0046_employer_name_normalized_trigram_index.py).

### 7. Lightsail 2 GB plan is undersized for this workload

The DB is ~3× RAM, the disk burst budget has been pinned at zero for
days, and the bot floor alone keeps `iowait` at 80 %. Even with the
fixes above, headroom is thin. Options:

- Lightsail 4 GB / 2 vCPU (~2× RAM, doubled IOPS baseline, more
  burst). ~$24/mo vs ~$12/mo.
- Move Postgres to Lightsail Managed Database — separates the web
  container's I/O budget from the DB's.

### 8. `_update_cluster_statistics` averages averages

The existing `avg_salary` on `salary_employer_cluster` is the mean of
per-employer averages, not weighted by record count. Used on the
employer-directory and cluster pages. The new
`search_avg_salary` field added in #3 is correctly record-weighted —
worth migrating other consumers to it (or replacing `avg_salary`
itself) once we've validated the new field on staging.
