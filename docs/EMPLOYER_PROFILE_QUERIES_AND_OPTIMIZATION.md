# Employer Profile Page: Queries and Optimization

This document describes the employer profile view (`/employer/<slug>/`), the queries it runs, current indexes, and suggested optimizations. Use it together with the timing instrumentation added to the view to find and fix slow paths.

## Instrumentation

The view logs timing for each major step. Look for log lines prefixed with `[employer_profile]` (logger name: `webapp.views.employers.profile`).

**Log events (cold path = cache miss):**

| Event | Description |
|-------|-------------|
| `cluster_get_by_slug` | Lookup `EmployerCluster` by slug (indexed). |
| `cache_get` | Backend cache get; `hit=True` skips all stats queries. |
| `basic_stats` | Single aggregate over base `records` queryset. |
| `top_titles` | Top 10 job title clusters with counts/medians (GROUP BY + JOINs). |
| `salary_percentiles` | Loads all `wage_annual` for employer into memory, then computes percentiles. |
| `salary_histograms` | Full scan of records for histogram bins (values_list over all rows). |
| `state_dist` | Geographic aggregation (state + count/median). |
| `yoy_trends` | Year-over-year aggregation (fiscal_year + count/median). |
| `cache_set` | Writing computed stats to cache. |
| `stats_compute_total` | Wall time for the whole stats block (only on cache miss). |
| `build_chart salary_histogram` | Time and JSON size for main salary histogram. |
| `build_chart state_filings` | Time and size for filings-by-state bar chart. |
| `build_chart state_median_salary` | Time and size for median-salary-by-state chart. |
| `build_chart filing_volume` | Time and size for YoY filing volume line chart. |
| `build_chart salary_trend` | Time and size for YoY salary trend line chart. |
| `build_chart job_title_histograms` | Time and count for per–job-title histogram charts (loop). |
| `build_charts_total` | Total charts bytes (main charts only, before job_title_histograms). |
| `build_charts` | Total time and `chart_payload_bytes` (all charts including job_title_histograms). |
| `similar_employers` | Subquery + annotate for top 5 employers in same state; log notes "Exists+Count distinct over salary_records". |
| `render` | Template render. |
| `page_total` | Total request time; `cache_hit=True` means full page payload was served from cache. |

**Where to see logs:** Application logs (e.g. gunicorn/stdout, or `journalctl -u visa-bulletin-web.service` when run via systemd). Filter by `[employer_profile]` or logger name to analyze a specific request.

### Observed bottlenecks (staging, top 10 employers by filings, cold load)

| Step | Typical range | Notes |
|------|----------------|--------|
| **build_charts** | **0.7–11 s** | Dominant cost on large employers (Microsoft 10.95s, Google 9.1s, Facebook 10.2s). Plotly JSON for salary histogram + state charts + YoY + per–job-title histograms. Scales with number of job title overlays. |
| **similar_employers** | **2–7 s** | Second largest. Subquery + Count over employers/salary_records by state (e.g. CA, TX, WA, NY). |
| **stats_compute_total** | **~3–4 s** | Sum of basic_stats, top_titles, salary_percentiles, salary_histograms, state_dist, yoy_trends. |
| basic_stats | 0.4–0.9 s | Single aggregate. |
| top_titles | 0.5–0.8 s | GROUP BY job title cluster + JOINs. |
| salary_percentiles | 0.4–0.6 s | Full scan of wage_annual. |
| salary_histograms | 0.4–0.7 s | Full scan for bins + per-title. |
| state_dist | ~0.6 s | Geographic aggregate. |
| yoy_trends | 0.4–0.8 s | Fiscal year aggregate. |
| cluster_get_by_slug | &lt;0.06 s | Negligible. |
| cache_get / cache_set | &lt;0.01 s | Negligible. |
| render | &lt;0.04 s | Negligible. |

**Conclusion:** Optimize (1) **build_charts** (fewer/simpler charts or lazy-load job title histograms), (2) **similar_employers** (cache or pre-aggregate), (3) stats block (composite index, DB-side percentiles, single-pass histogram).

### Deploy check (staging, Feb 2026)

Cold request (Microsoft, Google): **build_chart** granular logs show **salary_histogram** ~0.3–0.4s and ~12k bytes; **state_filings / state_median_salary / filing_volume / salary_trend** each ~0.02–0.03s and ~7k bytes; **job_title_histograms** count=10 ~0.2s; **chart_payload_bytes** ~125k. **similar_employers** Google/CA 4.1s, Microsoft/WA 2.3s. **Cache hit:** Second request to same URL on the **same worker** gave `cache_hit=True` and `page_total ... took 0.012s`; when a different worker gets the request, cache miss and page is slow again unless the backend is shared (e.g. Redis).

### Cache: why the second request can still be slow

- **Full-page cache:** The view now caches a single payload: `stats`, `chart_data`, and `similar_employers` under `employer_page_v5:{cluster_id}:{program}:{years}`. On cache hit, the view skips stats computation, `build_charts`, and the `similar_employers` query; it only builds context and renders.
- **Backend must be shared:** Django’s default `LocMemCache` is **per-process**. With multiple gunicorn workers, each worker has its own cache. So a second request to the same URL can hit a different worker and get a cache miss, and the page will be slow again.
- **Fix for “second time fast”:** Use a **shared cache backend** in production (e.g. Redis or memcached). Configure `CACHES` in settings so `cache_page` and the employer page payload use the same shared backend; then any worker can serve a cached response. Example (Redis):

  ```python
  CACHES = {
      'default': {
          'BACKEND': 'django.core.cache.backends.redis.RedisCache',
          'LOCATION': 'redis://127.0.0.1:6379/1',
          'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
          'KEY_PREFIX': 'visa_bulletin',
          'TIMEOUT': 60 * 60 * 6,
      }
  }
  ```

- After switching to a shared cache, the second request to the same employer URL should be fast (cluster lookup + cache get + render only).

### Cache backend: shared by whom, and do we need Redis?

**Shared by whom?**  
Shared by **all gunicorn worker processes**. With 2 workers, each process has its own memory. `LocMemCache` stores data in that process’s memory only. So: request 1 to `/employer/microsoft-corporation/` → worker A → cold path → caches page in worker A’s memory. Request 2 to the same URL → may go to worker B → worker B’s cache is empty → cold again (slow). So “shared” means: one cache store that **every** worker reads and writes (e.g. a Redis instance), not per-process memory.

**Can we get away with the existing backend by only changing cache settings?**  
**No.** `LocMemCache` is in-process by design; there is no setting to make it shared across processes. To get “second request fast” consistently with multiple workers you must use a backend that lives outside the app: **Redis** (recommended), **memcached**, or **DatabaseCache** (no extra service but more DB load).

**What is needed to set up Redis (minimal)?**  
1. **On the server:** Install and run Redis (e.g. `apt install redis-server` and start it).  
2. **Python:** Django 4.0+ has a built-in Redis backend; add the `redis` package (e.g. in `requirements.txt`).  
3. **Settings:** Point `CACHES['default']` at Redis. Example (Django built-in, no django-redis required):

```python
import os
REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'KEY_PREFIX': 'visa_bulletin',
        'TIMEOUT': 60 * 60 * 6,
    }
}
```

No view or cache key changes: `cache.get` / `cache.set` and `@cache_page` keep working; they just use the shared backend.

**Setup:** New instances: `scripts/setup_new_instance.sh` installs Redis and adds `REDIS_URL=redis://127.0.0.1:6379/1` to `.env`. Docker: `deployment/docker-compose.blue.yml` and `docker-compose.green.yml` include a Redis service and set `REDIS_URL=redis://redis:6379/1` for the web container.

**Single-worker workaround:** If you run gunicorn with `--workers 1`, LocMemCache is effectively “shared” (only one process). Second request will usually be fast, but you lose parallelism.

### Cache cleansing (when and how to clear)

**When to clear the cache:**

- **After a major data refresh** (e.g. DOL salary import, employer/job-title clustering, or pipeline that changes employer or salary data). Cached employer and salary pages would otherwise show stale stats/charts until TTL (6 hours) expires.
- **After a deploy that changes the structure of cached payloads** (e.g. new keys, different chart format). Old entries can cause errors or wrong layout.
- **When debugging** to force cold-path behavior or verify fixes.

**How to clear (application cache):**

1. **Recommended:** Run the project script (clears Django cache backend; works with both LocMem and Redis):
   ```bash
   bazel run //scripts:clear_cache
   ```
   With Redis, no server restart is needed; all workers see the cleared cache immediately. On memory-constrained instances (e.g. 2GB): run `bazel shutdown` after to free ~400–500MB.

2. **Optional (Redis only):** Clear the Redis DB used by the app (e.g. DB 1):
   ```bash
   redis-cli -n 1 FLUSHDB
   ```
   Use only if you need to wipe Redis entirely (e.g. key prefix is not used and you want to clear everything in that DB).

**After clearing:** Next request to an employer or salary page will be a cold path (cache miss); subsequent requests will repopulate the cache. No need to restart gunicorn when using Redis.

### Why similar_employers is slow

- The query does:
  1. **Exists(subquery):** For each candidate `EmployerCluster`, check that there exists an `Employer` in that cluster with at least one `SalaryRecord` in `top_state`. That’s a correlated subquery over `employer` → `salary_record`.
  2. **Two Count(..., distinct=True):** For each cluster that passes the Exists filter, count H-1B and PERM salary records via `employers__salary_records__id` with filters. That joins cluster → employers → salary_records and counts distinct IDs.
- So we scan many clusters, run a correlated subquery per cluster, then do two distinct counts over `salary_record` per cluster. No single index covers this path; the planner ends up doing a lot of joins and distinct aggregates.
- **Possible optimizations:** Cache the result per `(cluster_id, top_state)` (now done in the full-page payload when using a shared cache), or pre-aggregate “top employers per state” in a summary table updated by the pipeline so the view does a simple lookup.

### build_charts: what takes time and how much we send

- Use the new logs to see per-chart time and size:
  - `build_chart salary_histogram|state_filings|state_median_salary|filing_volume|salary_trend slug=... took X.XXXs size=N` (size = JSON bytes).
  - `build_chart job_title_histograms slug=... count=K took X.XXXs` (K = number of per–job-title charts).
  - `build_charts_total slug=... charts_bytes=N chart_keys=[...]` (main charts only).
  - `build_charts slug=... took X.XXXs chart_payload_bytes=N` (all charts including job_title_histograms).
- **Typical bottleneck:** Building many `job_title_histograms` (one Plotly JSON per top job title) and the main `salary_histogram` with overlays. Large employers send a lot of chart JSON to the client; `chart_payload_bytes` shows total size.
- **Possible optimizations:** (1) Lazy-load job title histograms (e.g. load via JS after main charts), (2) cap the number of job title overlay charts, (3) simplify Plotly config (fewer traces or smaller JSON), (4) cache the built `chart_data` (already done in the full-page cache when backend is shared).

---

## Base Queryset

All stats (when cache misses) use the same base queryset:

```python
records = SalaryRecord.objects.filter(
    employer__canonical_cluster=cluster,
    fiscal_year__gte=start_year,
    wage_annual__isnull=False,
    is_worksite=False,
)
# Optional: program_filter (h1b/perm) adds visa_program filter
```

So effectively:

- Filter: `employer.canonical_cluster_id = cluster.id`, `fiscal_year >= start_year`, `wage_annual IS NOT NULL`, `is_worksite = false`.
- For large employers (e.g. Intel) this can be 5k–10k+ rows.

---

## Queries on Cold Path (Cache Miss)

1. **basic_stats** – One aggregate:
   - `COUNT(id)`, `COUNT(id) FILTER (case_status=1)`, `AVG(wage_annual)`, `MIN(wage_annual)`, `MAX(wage_annual)` on `records`.

2. **top_titles** – One query:
   - From `records` filtered by `job_title_entity_id IS NOT NULL` and `job_title_entity__canonical_cluster_id IS NOT NULL`.
   - `VALUES('job_title_entity__canonical_cluster__canonical_title', '...slug', '...id')`, `ANNOTATE(count, median_salary, min_salary, max_salary)`, `ORDER BY -count, title`, `[:10]`.
   - Joins: `salary_record` → `employer` → `job_title` → `job_title_cluster`.

3. **salary_percentiles** – One query + in-memory:
   - `records.values_list('wage_annual', flat=True).order_by('wage_annual')` → **full result set loaded into memory** (all salaries for this employer in range).
   - Then percentiles (p10, p25, p50, p75, p90) computed in Python.

4. **salary_histograms** – One query + in-memory:
   - `_count_histogram_bins(records, bins, bin_width)` runs:
   - `records.values_list('wage_annual', 'job_title_entity__canonical_cluster__canonical_title', 'job_title_entity__canonical_cluster__slug')` → **full result set** again.
   - Iterates in Python to fill bins and per-title histograms.

5. **state_dist** – One query:
   - `records.values('worksite_state').annotate(count=Count('id'), median_salary=Avg('wage_annual')).order_by('-count')[:15]`.

6. **yoy_trends** – One query:
   - `records.values('fiscal_year').annotate(count=Count('id'), median_salary=Avg('wage_annual'), approval_rate=...) order_by('fiscal_year')`.

7. **similar_employers** – One query (only when `top_state` is set):
   - Subquery: employers in cluster with `salary_records.worksite_state = top_state`.
   - Main: `EmployerCluster` with `Exists(employers_in_state)`, exclude current cluster, annotate `actual_lca_count` / `actual_perm_count` (Count on `employers__salary_records` with filters), order by total, `[:5]`.
   - Heavy: multiple JOINs and counts across employer → salary_records.

So on a cold request we have **at least 6–7 DB round-trips** (plus possibly 2 full scans of the same record set for percentiles and histograms).

---

## Current Indexes (Relevant to This Page)

**EmployerCluster**

- `slug` (unique, db_index).
- `canonical_name` (db_index).

**Employer**

- `name_normalized` (db_index) – used for redirect lookup (`name_normalized__icontains`; `icontains` cannot use index for leading wildcard).
- `canonical_cluster_id` (FK + index in Meta).

**SalaryRecord**

- `employer_id` (FK; index).
- `employer_id + is_worksite` composite: `Index(fields=['employer', 'is_worksite'])`.
- `job_title_entity_id`: `Index(fields=['job_title_entity'])`.
- `fiscal_year`, `wage_annual`, `visa_program`, `worksite_state`, etc. (single-column and composite indexes exist but none tailored to “employer cluster + fiscal_year + is_worksite + wage_annual”).

**Missing for this view:**

- No composite index that matches the base filter: `(employer_id, is_worksite, fiscal_year)` or `(employer_id, is_worksite, fiscal_year, wage_annual)` to serve “all records for this employer cluster in range with wage” in one scan.
- Percentiles and histograms each do a separate full scan over the same logical set.

---

## Suggested Optimizations

### 1. Composite index for base employer-profile filter

**Goal:** Speed up the base `records` queryset (and thus every query built from it).

- Add an index that allows the planner to use one index for:
  - `employer_id` (join to employer where `canonical_cluster_id = ?`),
  - `is_worksite = false`,
  - `fiscal_year >= ?`,
  - optionally `wage_annual IS NOT NULL` (or rely on predicate).

**Example (conceptual):**

- On `salary_record`: composite index on `(employer_id, is_worksite, fiscal_year)`.

Because the filter is on `employer__canonical_cluster`, the join is `salary_record.employer_id → employer.id` and `employer.canonical_cluster_id = cluster.id`. So the most direct help is an index that starts with `employer_id` and includes `is_worksite` and `fiscal_year`. Exact column order can be tuned with `EXPLAIN (ANALYZE)` on the actual `basic_stats` (or any) query.

**Migration:** Add `Index(fields=['employer', 'is_worksite', 'fiscal_year'])` (or similar) on `SalaryRecord` and run migrations.

### 2. Reduce full scans: percentiles

**Current:** `calculate_salary_percentiles(records)` loads all salaries into memory.

**Options:**

- **Approximate percentiles in DB:** Use `percentile_cont` / `percentile_disc` in raw SQL or a single aggregate so PostgreSQL does one pass and returns 5 numbers (e.g. p10, p25, p50, p75, p90) without transferring all rows.
- **Sample:** If acceptable for display, compute percentiles on a random sample (e.g. 2k–5k rows) via `records.order_by('?')[:5000]` (or a deterministic sample) to cap memory and time while keeping cold-path logic.

### 3. Reduce full scans: histograms

**Current:** `_count_histogram_bins` does a second full scan over the same `records` with a wide `values_list`.

**Options:**

- **Single pass:** Build histogram and, if needed, per-title counts in one query (e.g. raw SQL with width_bucket or CASE bins) so we don’t iterate all rows in Python.
- **Reuse percentiles result:** If percentiles are computed in DB, consider one query that returns both percentile values and binned counts (e.g. with conditional aggregation), so we avoid a second full scan.

### 4. Similar employers

**Current:** Complex subquery + Exists + two Count annotations over `employers__salary_records`.

**Options:**

- **Pre-aggregate:** Store per-cluster, per-state filing counts (or similar) in a summary table updated by pipeline; then “similar employers” becomes a lookup + order by that column.
- **Simplify query:** If we only need “top employers in this state,” a simpler query (e.g. aggregate by cluster and state once, cache or materialize) can replace the current annotate/Exists pattern.
- **Cache:** Cache the “similar employers” list per (cluster_id, top_state) with a shorter TTL so repeated visits don’t re-run this query.

### 5. Consolidate aggregates (optional)

**Current:** basic_stats, state_dist, yoy_trends are separate queries.

**Option:** One or two queries using conditional aggregation (e.g. `Case/When` for state, fiscal_year) could return multiple aggregates in a single round-trip. This reduces number of queries and may allow one index scan to be shared. Worth measuring with instrumentation before/after.

### 6. Redirect lookup

**Current:** On slug miss, `Employer.objects.filter(name_normalized__icontains=slug_normalized)` – `icontains` cannot use a B-tree index for the leading wildcard.

**Options:** Keep as-is for correctness; if this path is hit often, consider a dedicated lookup table (slug → cluster_id) or trigram index (`pg_trgm`) on `name_normalized` for faster fuzzy match.

---

## Quick Wins (in order)

1. **Add composite index** `(employer_id, is_worksite, fiscal_year)` (or similar) on `salary_record` and re-measure `basic_stats`, `top_titles`, `state_dist`, `yoy_trends` with the new logs.
2. **Replace in-memory percentiles** with a single DB aggregate (e.g. `percentile_cont`) to remove one full scan and large transfer.
3. **Single-pass histogram** (DB-side bins or one values_list that feeds both overall and per-title histograms) to remove the second full scan.
4. **Cache or pre-aggregate similar_employers** to avoid the heavy subquery on every cold request.

After each change, trigger a cold load (e.g. new slug or cache clear) and compare `[employer_profile]` timings to confirm improvements.
