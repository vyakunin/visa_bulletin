# Scripts Directory

This directory contains all project scripts organized by functionality. All scripts should be run via Bazel for proper dependency management.

> **Where the OTHER repo's tooling lives** (two-repo split, cross-repo map settled
> 2026-07-20). This repo keeps **app-level dev/test/data utilities**; the private ops
> repo `visa_bulletin_platform/scripts/` keeps **traffic, monetization and UX
> measurement** (they read prod + `~/tokens/` credentials). Neither pair below is a
> duplicate — they answer different questions, so pick by question, not by filename:
>
> | Question | Use | Where |
> |---|---|---|
> | Lab CLS/perf for a URL (PageSpeed Insights, no browser) | `scripts/check_cls.sh` | here |
> | Field CLS after an ad-density/placement change (live CDP + ad slots, the <0.05 monetization gate) | `scripts/measure_cls.py` | platform |
> | Traffic share **per section/path** (full-coverage GoatCounter export) | `scripts/gc_section_shares.py` | here |
> | Traffic **channel/referrer mix** (organic vs Reddit vs direct) | `scripts/channel_mix.py` | platform |
>
> SEO docs split the same way: implementation here (`docs/seo/SEO_OPTIMIZATION.md`),
> measurement + strategy in `visa_bulletin_platform/docs/SEO.md`.

## Quick Reference

- **Data Validation**: `bazel run //scripts/salary:validate_data`
- **Data Ingestion**: `bazel run //scripts/ingest:run_pipeline`
- **Employer Clustering**: `bazel run //scripts/salary:cluster_existing_employers`
- **Database Exploration**: `bazel run //scripts:run_sql`

## Table of Contents

1. [Data Validation](#data-validation)
2. [Data Ingestion](#data-ingestion)
3. [Data Fixes](#data-fixes)
4. [Employer Clustering](#employer-clustering)
5. [Job Title Management](#job-title-management)
6. [VQS (Virtual Queue Simulation)](#vqs-virtual-queue-simulation)
7. [Database Management](#database-management)
8. [Deployment](#deployment)
9. [Development Utilities](#development-utilities)
10. [Performance Benchmarking](#performance-benchmarking)
11. [Golden Test Data Management](#golden-test-data-management)
12. [Testing and Verification Utilities](#testing-and-verification-utilities)
13. [Investigation/Debugging](#investigationdebugging)
14. [Ad-surface visual sweep](#ad-surface-visual-sweep)

---

## Ad-surface visual sweep

### `ad_surface_screenshots.py` — weekly screenshots + structural probes of the top ad-bearing surfaces

The ad layer is the only part of the site that renders differently per visitor
and is invisible to the test suite (slots are injected by Google at runtime).
This captures what a reader actually gets, on the top-N surfaces **by real
traffic** (derived from the full GoatCounter export — never the top-100 cap).

```bash
uv run scripts/ad_surface_screenshots.py                 # top 5, desktop+mobile, ads on
uv run scripts/ad_surface_screenshots.py --geo EEA       # the real ad-free EEA view
uv run scripts/ad_surface_screenshots.py --surfaces 3
uv run scripts/ad_surface_screenshots.py --prune-dry-run # retention preview
```

Output: `~/.cache/vb_ad_screenshots/<date>/<surface>__<device>[__viewport].jpg`
plus `manifest.json` (overflow_px, slot fill, reserved-empty px, CLS, doc height,
and hero geometry — `hero_ad_injected` / `hero_h` / `nav_top_px` / `h1_top_px` /
`content_below_fold`). Retention: keeps the 4 newest run dirs (`--keep`,
`--prune-dry-run`).

**Two metrics under-reported until 2026-08-10 — do not compare an older manifest
against a newer one on these fields.** Both read clean off a visibly broken page:

- **`reserved_empty_px`** counted unfilled `ins` elements taller than 1px, but
  `ad_slot.html` gives an unfilled unit `display:none`, so the rule could never
  fire — it read 0 on all 27 shots from 2026-07-27 to 2026-08-10, 20 of which had
  unfilled slots, while the screenshots showed labelled 280-300px voids. The band
  is reserved by the `.vb-ad-slot` **wrapper**, which is what is measured now.
  `labelled_empty_px` splits out the subset showing an "ADVERTISEMENT" caption
  over blank — a bare band is a deliberate trade and is reported but not flagged;
  a labelled one is the bug (`ad_slot.html`'s own rule).
- **`over_wide_px`** is new and replaces `overflow_px` as the horizontal-overflow
  signal. `overflow_px` is `scrollWidth - clientWidth`, which `base.html`'s
  `overflow-x: clip` pins to 0 **by design**, so the guard that exists to catch
  the 2026-07 sitewide scrollbar could not see a recurrence. It derives from
  `escaping_el_px` (widest element not contained by a scroller below `body`) and
  **not** from `widest_el_px`, which counts wide tables inside their own
  `overflow-x:auto` scrollers — legitimate behaviour reading 462-839px against a
  390px mobile viewport. `escaping_el` names the culprit element.

`.vb-ad-slot` / `vb-ad-collapsed` / `vb-ad-live` / `data-vb-hi` are a **cross-repo
contract** with `visa_bulletin_platform/monetization/ad_slot.html`. A rename there
silently zeroes these metrics again; `//tests:test_ad_guard_metrics` pins this
side only.

A **filled** slot can still be the defect: 2026-07-20 found Google Auto-ads
injecting a filled 390×390 unit *inside* `div.hero-section` on mobile, which
scored clean on fill, reserved-empty and overflow alike while pushing the H1 to
y=755 in an 844px viewport. Hence the hero fields above and the `⚠ AD-IN-HERO`
flag (ticket `3a362b8d409f81769212e5e503b62f95`).

**Three traps this script exists to document — read before interpreting output:**

1. **The EEA gate.** The site withholds `adsbygoogle.js` entirely from EEA/UK/CH
   (`overrides/ad_slot.html` reads `/cdn-cgi/trace`). This box is in Berlin, so
   an un-overridden capture renders the ad-free view, reports `slots=0`, and
   looks perfectly clean while measuring **nothing**. `--geo US` (default)
   intercepts only that trace so the page's own gate loads the ad stack. A run
   that finds zero slots with the override on **exits 2** rather than reporting
   a false all-clear.
2. **Fill rates are not a business metric.** Ad requests come from this box's
   real German IP, so ad content is German and fill is unrepresentative. Judge
   layout / overflow / holes / CLS — never fill%. Likewise, full-page shots
   freeze `position:fixed` anchor ads mid-page (an artifact, not an overlap) —
   compare the `__viewport.jpg`.
3. **Lazy charts are force-rendered, so a rendered chart proves nothing about
   the real page.** The capture runs under CDP `setDeviceMetricsOverride`, where
   the page does not actually scroll (`scrollY` stays 0) and
   `IntersectionObserver` never fires — so the observer-gated Plotly charts on
   `/` and the country landings used to photograph as a permanent "Loading
   chart…" spinner and read as a broken widget. `_scroll_through()` now wakes
   them, and the **scroll pass alone does not work** under the metrics override:
   the direct `loadPlotly()` call is what actually renders them. Two
   consequences — a spinner in an *old* run (≤2026-07-27) is that artifact, not
   a defect; and a chart present in a *new* shot does not confirm a real user's
   chart loads on its own, which only the headed debug Chrome can show.

**Scheduled:** `ad_surface_screenshots.timer` (systemd user unit, Mondays 09:15
Berlin) → `run_ad_screenshot_sweep.sh`, which captures and then *injects* an
inspect prompt into the visa_bulletin relay so an agent actually looks at the
images (a screenshot nobody opens catches nothing). A failed capture posts a
loud "nothing was checked this week" rather than passing silently.

```bash
systemctl --user list-timers ad_surface_screenshots.timer
bash scripts/run_ad_screenshot_sweep.sh          # manual run
journalctl --user -u ad_surface_screenshots.service
```

---

## Data Validation

### Unified Validation Script

**`scripts/salary/validate_data.py`** - **PRIMARY VALIDATION SCRIPT**

**Purpose:** Unified comprehensive validation script that consolidates all data quality validation functionality. This is the primary tool for verifying data integrity, completeness, and sanity across the entire salary database.

**When to use:**
- After ingesting new data files (verify import completeness)
- Before deploying to production (ensure data quality)
- During development to catch data issues early
- For generating validation reports for stakeholders
- To track data quality metrics over time (golden set tracking)

**What it validates:**

1. **Basic Statistics**
   - Record counts by program, fiscal year, source file
   - Employer counts and distribution
   - Data coverage metrics

2. **Data Integrity**
   - Required fields (case_number, employer_name, job_title)
   - Wage calculation accuracy (sampling 1000 records)
   - Date validation (case_submitted < decision_date, employment_start < employment_end)
   - Duplicate case numbers (should be none due to unique constraint)

3. **Data Sanity**
   - Wage ranges ($20K-$1M validation with separate high/low checks)
   - Valid wage units (WageUnit enum validation)
   - SOC code format (XX-XXXX or XX-XXXX.XX pattern)
   - State codes (VALID_STATES validation with examples)
   - Missing salary data (wage_annual null/0 - critical UI issue: displays as "$--")
   - Orphaned employers (Employer records with no SalaryRecords)
   - Empty critical fields (case_number='', employer_name='', job_title='')

4. **Import Completeness** (3 levels of granularity)
   - Total: File row counts vs database record counts (allow 5% deviation)
   - By Year: Per fiscal-year comparison (side-by-side table)
   - By File: Per-file comparison with discrepancy analysis and reason detection

5. **Record Completeness** (differentiated by field type)
   - SalaryRecord: case_number, job_title, wage_annual, employer_name, employer, fiscal_year
   - WorksiteRecord: case_number, job_title, fiscal_year (salary optional for worksite)

6. **Ingestion Analysis**
   - Latest 50 completed ingestion runs
   - Records created/failed per run
   - Breakdown by source type and domain

7. **Input vs Served Comparison**
   - Compare file statistics to served database statistics
   - Detect discrepancies (allow 5% deviation)
   - Analyze by source file

8. **Homepage Query Testing**
   - Dashboard queries (Family/Employment categories, countries, action types)
   - Salary search queries (H1B/PERM, by year, by state)
   - Aggregations (avg/min/max salary)

9. **Golden Set Tracking**
   - Save baseline statistics (`--update-golden`)
   - Compare current stats to golden set
   - Detect significant changes (>10% total count, >15% program distribution)
   - Track data quality trends over time

10. **Spot Checks** (optional, can skip with `--skip-spot-checks`)
    - Sample records by visa program, fiscal year, state, employer, wage range, case status
    - Verify data looks reasonable across different slices

**Usage:**
```bash
# Run all validations (default) - comprehensive data quality check
bazel run //scripts/salary:validate_data

# Generate JSON report for automated processing
bazel run //scripts/salary:validate_data -- --json-report report.json

# Skip spot checks (faster, for CI/CD)
bazel run //scripts/salary:validate_data -- --skip-spot-checks

# Check import completeness only (3 modes: total, by-year, by-file)
bazel run //scripts/salary:validate_data -- --check-import-completeness
bazel run //scripts/salary:validate_data -- --check-import-completeness-by-file

# Check incomplete records only (missing fields by type)
bazel run //scripts/salary:validate_data -- --check-incomplete-records

# Analyze ingestion logs (latest 50 runs)
bazel run //scripts/salary:validate_data -- --analyze-ingestion

# Compare input vs served stats (detect discrepancies)
bazel run //scripts/salary:validate_data -- --compare-input-served

# Test homepage queries only (faster, UI-focused)
bazel run //scripts/salary:validate_data -- --test-homepage-queries

# Golden set operations (track data quality baseline)
bazel run //scripts/salary:validate_data -- --golden-file data/validation/golden.json
bazel run //scripts/salary:validate_data -- --update-golden
```

**Key Features:**
- **Performance:** Uses `cached_file_rows` (file scanning is slow, results cached)
- **Comprehensive:** Filter-based incompleteness checks differentiated by field type
- **Flexible:** Run all checks or specific subsets via flags
- **Reporting:** Supports both JSON and text report generation
- **Exit codes:** 0 = success, 1 = errors found (CI/CD friendly)
- **N+1 Prevention:** Uses bulk queries, aggregations, and prefetch_related()

**Output:**
- Text report with validation results (pass/fail per check)
- Detailed error messages and warnings
- Statistics and sample data for failed checks
- JSON report (optional) for automated processing

**Deleted Scripts (functionality merged into validate_data.py):**
These scripts have been deleted and their functionality is available via flags in the unified script:
- `scripts/verify_import_completeness.py` - Deleted, use `--check-import-completeness` flag
- `scripts/validate_data_comprehensive.py` - Deleted, use unified script with appropriate flags
- `scripts/check_missing_salary.py` - Deleted, use `--check-incomplete-records` flag
- `scripts/investigate_null_salaries.py` - Deleted, use unified script
- `scripts/investigate_salary_issues.py` - Deleted, use unified script
- `scripts/investigate_validation_issues.py` - Deleted, use unified script

**Related Tools:**
- For detailed missing salary investigation (by source file, visa program): Use `scripts/salary/investigate_missing_salary.py`
- For data quality fixes: Use `scripts/salary/fix_all_data_quality_issues.py`

---

## Data Ingestion

### Bulletin fetch — Akamai wall bypass (minipc browser → prod)

travel.state.gov sits behind Akamai Bot Manager: plain `requests`, browser-UA `curl`,
and `curl_cffi` Chrome-impersonation all get **403** (JS/sensor challenge). Only a real
browser passes, so the fetch runs on the **minipc debug Chrome** (CDP `:9222`) and the
HTML is fed to the prod ingest via `BULLETIN_HTML_CACHE_DIR` (both `fetch_page` and
`base.download` prefer a cached file — a no-op when the env var is unset).

**`scripts/fetch_bulletin_via_browser.py`** (minipc only) — drives the debug Chrome to
download the index + requested month pages into a cache dir. The Akamai flow needs a
fresh `_abck` cookie, so the pattern is `clear cookies → navigate → wait → reload →
read` (goto/reload raising on the redirect churn is expected). Exit 2 if the wall isn't
passed / CDP is down.
```bash
uv run --with playwright --with python-dateutil \
  python scripts/fetch_bulletin_via_browser.py --cache-dir /tmp/bulletin_html_cache
```

**`scripts/sync_bulletin_to_prod.sh`** (minipc only) — the bridge: fetch via browser →
stream the cache into `vb_web` (tar over ssh) → run `scripts.cron.refresh_bulletin`
there with `BULLETIN_HTML_CACHE_DIR` set → discover/download read the cached HTML, parse
/load/predict run prod-side unchanged. Idempotent (dedup by DataSource). Scheduled a few
times/day on the minipc during the mid-month publish window (State Dept publishes the
next month ~8th–15th).
```bash
scripts/sync_bulletin_to_prod.sh                       # current + next month
scripts/sync_bulletin_to_prod.sh --months 2026-08      # specific month
```

### Backfill real release dates (`Bulletin.released_on`)

**`scripts/bulletin/backfill_release_dates.py`** — fills the date the State Department
actually *published* each bulletin. `publication_date` is the governing month and
`fetched_at` only approximates the release for editions our own cron ingested live (4 of
290 rows before this backfill), so earlier editions come from the **first Internet
Archive capture** of the bulletin's travel.state.gov URL.

Both sources are upper bounds on the true release, so the **earlier** of the two wins.
A candidate whose implied lead falls outside 3–45 days before the governing month is
rejected and the row left NULL — "unknown" stays distinguishable from "known". This
drops the late-2017 CMS-migration artifact (every pre-2018 bulletin was first archived
on 2017-12-03), which is why coverage starts at ~2018; recovering older editions needs
the pre-migration numbered URLs (`/visa/frvi/bulletin/bulletin_NNNN.html`), which are
not derivable from the publication date.

CDX responses are cached under `--cache-dir` (default `~/.cache/visa_bulletin/wayback_cdx`),
so re-runs are cheap and resumable; the archive is rate-limited and 503s often, so every
lookup retries with backoff.

```bash
bazel run //scripts/bulletin:backfill_release_dates -- --dry-run
bazel run //scripts/bulletin:backfill_release_dates
bazel run //scripts/bulletin:backfill_release_dates -- --since 2018-01-01 --refresh
```

Consumed by `lib/business/bulletin/release_schedule.py` → the
`/when-is-the-next-visa-bulletin/` page (projected release date, countdown, and the
"X% of past August bulletins were out by this point" line).

### Record a floor DOS published in a bulletin's notes (`PublishedFloor`)

**`scripts/bulletin/record_published_floor.py`** — stores a lower bound the State
Department stated in a bulletin's *prose* about a **future** month, so the forecast
cannot contradict it.

The parser reads only the four named cutoff tables and the prose is persisted
nowhere (the fetched HTML is transient), so this is deliberately **not** a parser:
an agent reads the notes section, resolves the referenced date, and passes the
values in. The script validates and writes. Statements look like this — July 2026,
section F:

> It is likely that in October the final action date will advance to at least the
> final action date announced in the May 2026 Visa Bulletin

Note that the sentence names a *bulletin*, not a date: look up that bulletin's own
cell for the series (here May 2026 EB-2 India final action = 15 Jul 2014) and pass
the result to `--floor-date`.

```bash
# record (idempotent: same source+target+series updates in place)
bazel run //scripts/bulletin:record_published_floor -- \
    --source-bulletin 2026-07 --target 2026-10 \
    --visa-class 2nd --country india --action-type final_action \
    --floor-date 2014-07-15 --section F --quote-file /tmp/quote.txt

bazel run //scripts/bulletin:record_published_floor -- --list
bazel run //scripts/bulletin:record_published_floor -- --dry-run ...   # validate only
# what the floor does to the forecast, without writing anything:
bazel run //scripts/bulletin:record_published_floor -- --effect \
    --visa-class 2nd --country india --knowledge-date 2026-08-31
```

Rejects (exit 2) a target that is not after the source bulletin, a floor date not
earlier than the target, an uningested source bulletin, an unknown country/action
type, and a quote under 40 characters — the verbatim sentence is the audit trail
for a hand-entered claim, so it is mandatory.

Consumed by `lib/business/vqs/october_reset.py`: a floor **truncates** the reset
distribution (every precedent outcome below it moves up to it) and the point
estimate cannot sit below it, so a published forecast cannot fall under a bound
State has announced. Reading a floor is walk-forward safe — it is invisible until
its source bulletin has published, so backtests cannot see the future.

### Import Visa Bulletin Data from CSV

**`scripts/import_visa_bulletin_data.py`** – Import Visa Bulletin data from CSV files exported from another instance (e.g. production to development). Not part of the automated pipeline; use for one-off data transfers.

```bash
# Export from production (via SSH + psql \COPY), then import locally:
bazel run //scripts:import_visa_bulletin_data -- --bulletin /tmp/bulletin.csv --cutoff /tmp/visa_cutoff_date.csv
```

### Main Pipeline

**`scripts/ingest/run_pipeline.py`** - Unified ingest pipeline orchestrator

**Usage:**
```bash
# Discover sources
bazel run //scripts/ingest:run_pipeline -- discover --domain dol

# Ingest pending sources (excludes sources that have FAILED runs; use --include-failed to retry them)
bazel run //scripts/ingest:run_pipeline -- run --all-pending --domain dol

# Retry sources that have failed runs (no completed runs)
bazel run //scripts/ingest:run_pipeline -- run --retry-failed

# Discover and ingest all domains (pending only; failed sources are not re-run by default)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains

# Mark RUNNING and PENDING ingest runs as FAILED so they are not re-run by default
bazel run //scripts/ingest:run_pipeline -- mark-unfinished-failed
bazel run //scripts/ingest:run_pipeline -- mark-unfinished-failed --dry-run
bazel run //scripts/ingest:run_pipeline -- mark-unfinished-failed --running-only  # Only mark RUNNING

# Cleanup old ingest run metadata

# Re-ingest specific local files (drops non-unique indexes first, recreates after)
bazel run //scripts/ingest:run_pipeline -- reingest-files -- \
  --files data/salary/dol_data/LCA_Disclosure_Data_FY2024_Q4.xlsx data/salary/dol_data/PERM_Disclosure_Data_FY2024_Q4.xlsx
```

**Discovery deduplication (why "new" sources should not appear for already-seen data):**
- Discovery deduplicates by **normalized URL** (https, lowercase host, no query/fragment) so the same URL in a different form (e.g. http vs https, with `?tracking=1`) is not re-added.
- Discovery also deduplicates by **same (domain, source_type, path basename)** so the same file under different paths is not re-added. Example: DOL `urljoin(base_url, "PERM_FY2024.xlsx")` yields `.../foreign-labor/PERM_FY2024.xlsx` while `urljoin(base_url, "performance/PERM_FY2024.xlsx")` yields `.../foreign-labor/performance/PERM_FY2024.xlsx`; both are treated as one source (same filename, same domain/type). See `lib/utils/url_utils.py` and `discover_sources()` in `run_pipeline.py`.

**Index management during re-ingest:**
- The `reingest-files` command **automatically drops non-unique indexes** on `salary_record`/`worksite_record`
  using `scripts/salary/manage_salary_indexes.py`, runs ingest, then recreates the indexes.
- Snapshot path defaults to `data/index_snapshots/salary_indexes.yaml`. Use
  `--index-snapshot` and `--overwrite-index-snapshot` to control it.
- Re-ingest runs in **update mode** to refresh existing records for the supplied files.

### Supporting Scripts

**`scripts/ingest/register_local_files.py`** - Register local files for ingestion
```bash
bazel run //scripts/ingest:register_local_files -- --file-path data/salary/file.xlsx
```

**`scripts/ingest/check_run_status.py`** - Check status of ingestion runs
```bash
bazel run //scripts/ingest:check_run_status
```

**`scripts/ingest/reset_incomplete_runs.py`** - Reset incomplete/failed ingestion runs
```bash
bazel run //scripts/ingest:reset_incomplete_runs
```

**`scripts/ingest/reset_missing_files.py`** - Reset runs with missing files
```bash
bazel run //scripts/ingest:reset_missing_files
```

**`scripts/ingest/inspect_raw_file_headers.py`** - Inspect column headers in raw files
```bash
bazel run //scripts/ingest:inspect_raw_file_headers -- --file data/salary/file.xlsx
```

**`scripts/ingest/inspect_unknown_source_rows.py`** - Inspect raw rows for unknown employer/job title values

Use this to locate a few `SalaryRecord` entries with `employer_name` or `job_title` set to `Unknown` and print the raw source columns to see if the data exists in alternative fields.

```bash
# Inspect both employer + job title unknowns (default)
bazel run //scripts/ingest:inspect_unknown_source_rows

# Limit to 5 cases
bazel run //scripts/ingest:inspect_unknown_source_rows -- --limit 5

# Inspect only employer unknowns
bazel run //scripts/ingest:inspect_unknown_source_rows -- --mode employer
```

**`scripts/ingest/rollback.py`** - Rollback ingestion runs
```bash
bazel run //scripts/ingest:rollback -- --run-id 123
```

**`scripts/i129/backfill_employer_links.py`** - Link I-129 petitions to LCA employer clusters

Maps each `i129_petition.employer_name` to an `EmployerCluster` by NORMALIZED name
(exact match yields ~0 rows — the USCIS and LCA spellings differ), so the employer
profile page can scope the actual-pay vs LCA-posted comparison. Heavyweight write on
the full petition table — run OFF-PROD on staging and graduate the data. Re-run after
every I-129 refresh. Same linker (`lib/business/i129/employer_linker.py`) is reused for
the USCIS Employer Data Hub approval rows.
```bash
bazel run //scripts/i129:backfill_employer_links -- --dry-run   # report match rates only
bazel run //scripts/i129:backfill_employer_links                # apply
```

**`scripts/i129/warm_demographic_pay.py`** - Warm the site-wide demographic actual-pay panel

The "what different H-1B workers are actually paid" component on `/job-title/` reads its
site-wide figures from cache ONLY — it never computes them on a request, because the three
dimension queries cost ~3s each against `i129_petition` and that surface competes on speed.
So **the section is hidden until this runs**. Run it after any cache flush: a prod deploy
(next to the `redis-cli -n 1 FLUSHDB` step), the refresh pipeline's `cache.clear()`, or an
I-129 load. Read-only against the database; must run inside the app container, where the
cache the site reads lives.
```bash
ssh homeserver "docker exec -w /app vb_web python3 -m scripts.i129.warm_demographic_pay"
ssh homeserver "docker exec -w /app vb_web python3 -m scripts.i129.warm_demographic_pay --check"
bazel run //scripts/i129:warm_demographic_pay                   # local
```

**`scripts/salary/warm_occupations.py`** - Warm the per-occupation caches `/h1b-salary/`
reads, then assert the pages actually render fast

Each `/h1b-salary/<occupation>/` page runs nine aggregates over `salary_record` plus the
I-129 matched-triple aggregate. `occupation_stats` caches that per occupation but fills it
ON THE FIRST MISS — and the view is `cache_page_skip_bots`, so that first request is almost
always a crawler paying the whole bill.

**The verdict is the rendered page, not the cache key.** Warming is not a guarantee:
vb_redis runs allkeys-lru over ~65k keys, so these 41 read-rarely entries are among the
first evicted. Measured on prod 2026-08-18, five hours after the nightly warm, 34 of 41
were gone and the seven present had been written minutes earlier by crawler cold-fills —
while this script logged "warmed 41 occupations in 0.2s — 0 were cold fills" and the pages
rendered 5-13s. So it now probes each page with a crawler User-Agent (the path with no
rendered-page cache in front of it) and **exits 1 if any renders slower than
`--max-render-ms`, default 1500ms**, so cron surfaces a regression instead of a reassuring
line about cache keys.
```bash
ssh homeserver "docker exec -w /app vb_web python3 -m scripts.salary.warm_occupations"
# probe only — measures the surface as a crawler finds it, no warming to mask the answer
ssh homeserver "docker exec -w /app vb_web python3 -m scripts.salary.warm_occupations --check"
bazel run //scripts/salary:warm_occupations                     # local
```

**`scripts/ingest/ingest_and_cluster.sh`** - Shell script for ingest + clustering workflow
```bash
./scripts/ingest/ingest_and_cluster.sh
```

---

## Data Fixes

### Master Fix Script

**`scripts/salary/fix_all_data_quality_issues.py`** - Master orchestrator for all data quality fixes

Runs all fix scripts in optimal order:
1. Fix missing fiscal years (from source URL)
2. Fix invalid wages (unit correction + data errors)
3. Fix missing salary data (recalculate wage_annual)
4. Fix invalid state codes
5. Fix missing employer links
6. Check import completeness (report only)
7. Run validation to verify fixes

**Usage:**
```bash
# Dry-run (analyze only, see what would be fixed)
bazel run //scripts/salary:fix_all_data_quality_issues

# Actually fix all issues
bazel run //scripts/salary:fix_all_data_quality_issues -- --fix

# Skip specific fixes
bazel run //scripts/salary:fix_all_data_quality_issues -- --fix --skip-wages --skip-employers
```

**Benefits:**
- Runs fixes in optimal order (dependencies handled)
- Validates results after fixes
- Single command for comprehensive data quality repair
- Can skip individual fixes if needed

### Individual Fix Scripts

**`scripts/salary/fix_fiscal_year_from_url.py`** - Fix missing fiscal years from source URL

Records from files with artificial names (e.g., `lca_367.xlsx`) have no fiscal year in filename. This script:
1. Finds records from files with artificial names
2. Looks up the DataSource to get original URL
3. Extracts fiscal year from URL (e.g., `/FY2015/` → 2015)
4. Updates records with correct fiscal year

**Usage:**
```bash
# Dry-run (see what would be fixed)
bazel run //scripts/salary:fix_fiscal_year_from_url -- --dry-run

# Actually fix
bazel run //scripts/salary:fix_fiscal_year_from_url
```

**`scripts/salary/fix_missing_salary_data.py`** - Fix records with missing wage_annual

Identifies records where `wage_annual` is NULL/0 but `wage_from` and `wage_unit` are present. Recalculates `wage_annual` using shared `calculate_annual_wage` function.

**Causes of missing wage_annual:**
- Import failures (row parsing errors)
- Data migration issues
- Manual data entry errors

**Usage:**
```bash
# Dry-run (analyze only)
bazel run //scripts/salary:fix_missing_salary_data

# Actually fix
bazel run //scripts/salary:fix_missing_salary_data -- --fix

# Limit to first 1000 records (for testing)
bazel run //scripts/salary:fix_missing_salary_data -- --fix --limit 1000
```

**`scripts/salary/fix_missing_employers.py`** - Fix missing employer links

Identifies records with `employer_name` but no `employer` FK. Creates or finds matching Employer records and links them using batch updates.

**Causes:**
- Records imported before employer clustering
- Data migration issues
- Import failures

**Usage:**
```bash
# Dry-run (analyze only)
bazel run //scripts/salary:fix_missing_employers

# Actually fix
bazel run //scripts/salary:fix_missing_employers -- --fix

# Limit to first 1000 records
bazel run //scripts/salary:fix_missing_employers -- --fix --limit 1000
```

**`scripts/salary/fix_state_codes.py`** - Fix invalid state codes

Identifies and fixes records with invalid `worksite_state` values (typos, full names, abbreviations).

**Common issues fixed:**
- Typos: "Califonia" → "CA"
- Full names: "California" → "CA"
- Abbreviations: "Calif" → "CA"
- Case/whitespace issues

**Usage:**
```bash
# Dry-run (see what would be fixed)
bazel run //scripts/salary:fix_state_codes -- --dry-run

# Actually fix
bazel run //scripts/salary:fix_state_codes

# Limit to first 1000 records
bazel run //scripts/salary:fix_state_codes -- --limit 1000
```

**`scripts/salary/fix_invalid_wages.py`** - Comprehensive fix for invalid wage records (both too high and too low)

**Purpose:** Identifies and corrects salary records with `wage_annual` outside the valid range ($5,000 - $1,000,000) configured in `wage_thresholds_config.yaml`. Uses the same validation logic as the ingest pipeline via shared `lib.parsing.salary.wage_unit_correction` module to ensure consistency.

**Invalid wages are caused by:**
- **Incorrect wage units**: Hourly/monthly/weekly wages stored as annual (or vice versa)
- **Data entry errors**: Unrealistic values (e.g., $21.3M for Marketing Manager, or $7.25 annual for minimum wage)
- **Parsing errors**: Decimal point errors, extra zeros, missing unit conversion

**Categorization and fixes:**
- **Parsing errors** (wrong wage unit) → Auto-corrects unit and recalculates `wage_annual`
  - Example: $7.25 stored as annual → Corrected to hourly, recalculated as $15,080/year
  - Example: $21,300,000 for Marketing Manager → Likely $21.30/hr stored as annual
- **Data errors** (unrealistic even with correct unit) → Marks as invalid (NULL)
  - Example: $4.5B annual salary (clearly impossible)
- **Edge cases** (possibly legitimate high salaries) → Flags for manual review
  - Example: $600K for C-level executive (may be legitimate, needs verification)

**Uses batched updates** (`BatchedUpdateCollector`) for efficient database operations - processes thousands of records without N+1 query problems. Does **not** drop or recreate indexes; only runs filtered SELECT and batched UPDATEs (row-level locks). Safe to run in production.

**After running fix_invalid_wages on production:** Re-compute stats that depend on `wage_annual`, or job title and employer aggregates will be stale:
1. `bazel run //scripts/salary:update_employer_stats` — refreshes `Employer.avg_salary` (and related counts).
2. `bazel run //scripts/salary:update_job_title_cluster_stats` — refreshes `JobTitleCluster.total_filings`, `avg_salary`, `canonical_title`.
Then clear cache and optionally warm: `bazel run //scripts:clear_cache`; reload gunicorn if using LocMem cache.

```bash
# Fix all invalid wages (both high and low) - RECOMMENDED
bazel run //scripts/salary:fix_invalid_wages

# Dry-run to see what would be fixed (no database changes)
bazel run //scripts/salary:fix_invalid_wages -- --dry-run

# Fix only parsing errors (auto-correct wrong units)
bazel run //scripts/salary:fix_invalid_wages -- --category parsing

# Fix only data errors (mark unrealistic values as invalid)
bazel run //scripts/salary:fix_invalid_wages -- --category data

# Limit to first 100 records (for testing)
bazel run //scripts/salary:fix_invalid_wages -- --limit 100
```

**`scripts/salary/fix_state_codes.py`** - Fix invalid state codes
```bash
bazel run //scripts/salary:fix_state_codes -- --fix
```

**`scripts/salary/reimport_perm_salary_data.py`** - Re-import PERM files to extract missing data
```bash
bazel run //scripts/salary:reimport_perm_salary_data -- --fix
```

**`scripts/salary/reimport_i200_files.py`** - Re-import I-200 files
```bash
bazel run //scripts/salary:reimport_i200_files -- --fix
```

**`scripts/salary/delete_incomplete_records.py`** - Delete records with missing critical data

Deletes SalaryRecord/WorksiteRecord entries that have missing wage_annual and cannot be fixed.

```bash
# Dry-run (analyze only)
bazel run //scripts/salary:delete_incomplete_records

# Actually delete
bazel run //scripts/salary:delete_incomplete_records -- --fix
```

**`scripts/salary/investigate_missing_salary.py`** - Detailed investigation of missing salary data

Provides detailed breakdown of missing salary data by source file, visa program, and fiscal year.

```bash
bazel run //scripts/salary:investigate_missing_salary
```

---

## Employer Clustering

### Main Clustering Script

**`scripts/salary/cluster_existing_employers.py`** - Cluster existing employers using similarity matching

**Usage:**
```bash
# Dry-run (preview matches)
bazel run //scripts/salary:cluster_existing_employers -- --dry-run

# Actually cluster
bazel run //scripts/salary:cluster_existing_employers

# With limits (for testing)
bazel run //scripts/salary:cluster_existing_employers -- --limit-employers 1000 --min-pairs 5
```

**Key Features:**
- Uses LSH (Locality Sensitive Hashing) for efficient similarity matching
- Two-phase approach: same normalized names, then cross-normalized names
- Auto-clusters high-confidence matches, queues uncertain matches for review
- Supports dry-run mode for preview
- Long-running script - run in background with monitoring

### Clustering Evaluation and Tuning

> The Ollama LLM-verifier clustering tools (`evaluate_clustering_threshold`,
> `benchmark_clustering`, `evaluate_clustering_with_llm`, `benchmark_llm_verifier`,
> `test_llm_prompts`) were removed 2026-06-20 when Ollama was retired. Live
> clustering is rule-based + fuzzy; tune via `collect_clustering_examples` +
> dry-run `cluster_existing_employers` against `data/clustering_examples.jsonl`
> (see `.claude/rules/employer_clustering.md`).

**`scripts/salary/iterative_clustering_tuning.py`** - Iterative tuning workflow
```bash
bazel run //scripts/salary:iterative_clustering_tuning
```

**`scripts/salary/binary_search_threshold.py`** - Binary search for optimal threshold
```bash
bazel run //scripts/salary:binary_search_threshold
```

### Clustering Review and Management

**`scripts/salary/review_clustering.py`** - Review clustering decisions
```bash
bazel run //scripts/salary:review_clustering
```

**`scripts/salary/apply_review_decisions.py`** - Apply manual review decisions
```bash
bazel run //scripts/salary:apply_review_decisions
```

**`scripts/salary/cleanup_orphaned_employers.py`** - Clean up orphaned employers
```bash
bazel run //scripts/salary:cleanup_orphaned_employers
```

### Clustering Examples and Data Collection

**`scripts/salary/collect_clustering_examples.py`** - Collect examples for benchmarking
```bash
bazel run //scripts/salary:collect_clustering_examples
```

**`scripts/salary/view_clustering_examples.py`** - View clustering examples
```bash
bazel run //scripts/salary:view_clustering_examples
```

### Golden Test Data Collection

**`scripts/salary/collect_dol_golden_test_data.py`** - Collect golden test data for DOL plugin transforms

Samples random rows from all PERM and LCA files for golden testing of transform() methods.

**Usage:**
```bash
# Collect 10 samples per file (default)
bazel run //scripts/salary:collect_dol_golden_test_data

# Customize output and sample size
bazel run //scripts/salary:collect_dol_golden_test_data -- \
  --output tests/data/dol_golden_test_data.yaml \
  --samples-per-file 20 \
  --random-seed 42
```

**What it does:**
- Finds all Excel files in `data/salary/dol_data/`
- Detects file type from headers (PERM vs LCA/Worksite)
- Samples random rows from each file
- Saves parsed dicts to YAML for manual annotation

**Next steps:**
1. Manually annotate expected results in the YAML file
2. Add `record_type`, `expected_result`, `expected_error` fields
3. Run golden test: `bazel test //tests:test_dol_transform_golden`

**See also:**
- `tests/data/README.md` - Test data format documentation
- `GOLDEN_TEST_SET_DOL_TRANSFORMS.md` - Complete implementation plan

### LLM-Based Clustering — REMOVED (2026-06-20)

The Ollama LLM clustering tools (`evaluate_clustering_with_llm`,
`benchmark_llm_verifier`, `test_llm_prompts`, and the `llm_verifier` /
`clustering_evaluator` libs) were deleted when Ollama was retired. Live clustering
is rule-based + fuzzy with no LLM step (see `.claude/rules/employer_clustering.md`).

### Bucket Mismatch Handling

**`scripts/salary/check_bucket_mismatch_status.py`** - Check bucket mismatch review status
```bash
bazel run //scripts/salary:check_bucket_mismatch_status
```

**`scripts/salary/review_pending_bucket_mismatches.py`** - Review pending bucket mismatches
```bash
bazel run //scripts/salary:review_pending_bucket_mismatches
```

**`scripts/salary/fix_pending_bucket_mismatches.py`** - Fix pending bucket mismatches
```bash
bazel run //scripts/salary:fix_pending_bucket_mismatches -- --fix
```

**`scripts/salary/finalize_bucket_mismatch_reviews.py`** - Finalize bucket mismatch reviews
```bash
bazel run //scripts/salary:finalize_bucket_mismatch_reviews
```

**`scripts/salary/harvest_bucket_mismatch_examples.py`** - Harvest examples for analysis
```bash
bazel run //scripts/salary:harvest_bucket_mismatch_examples
```

**`scripts/salary/add_bucket_mismatch_to_golden_set.py`** - Add examples to golden set
```bash
bazel run //scripts/salary:add_bucket_mismatch_to_golden_set
```

### Clustering Utilities

**`scripts/salary/merge_duplicate_clusters.py`** - Merge duplicate employer clusters (data cleanup)

**Purpose:** Identifies and merges duplicate `EmployerCluster` records with the same `canonical_name`. Critical for fixing data integrity issues that cause duplicate entries in autocomplete and breaking data consistency.

**When to use:**
- After discovering duplicate clusters in autocomplete
- Before applying unique constraint migration on `canonical_name`
- After bulk imports that may have created duplicate clusters
- To clean up data integrity issues in employer clustering

**Process:**
1. Finds all duplicate clusters (same `canonical_name`)
2. Selects primary cluster (most employers, or lowest ID if tied)
3. Reassigns all employers from duplicate clusters to primary
4. Deletes empty duplicate clusters

**Performance:** Uses bulk operations (`bulk_update_batched`, bulk delete) optimized for large datasets. Processes 24k+ duplicates in ~5 queries with N+1 query prevention via `prefetch_related()`.

```bash
# Dry run to preview changes (recommended first)
bazel run //scripts/salary:merge_duplicate_clusters -- --dry-run

# Actually perform the merge
bazel run //scripts/salary:merge_duplicate_clusters

# Debug mode with verbose logging
bazel run //scripts/salary:merge_duplicate_clusters -- --debug
```

**`scripts/salary/review_golden_set.py`** - Review golden set examples
```bash
bazel run //scripts/salary:review_golden_set
```

**`scripts/salary/fix_ground_truth_labels.py`** - Fix ground truth labels in golden set
```bash
bazel run //scripts/salary:fix_ground_truth_labels -- --fix
```

---

## Job Title Management

Scripts for managing job title clustering, slugs, and SEO features.

### Job Title Clustering

**`scripts/salary/cluster_job_titles.py`** - Cluster job titles by similarity
```bash
bazel run //scripts/salary:cluster_job_titles
```

**`scripts/salary/update_job_title_cluster_stats.py`** - Update statistics and representative titles for job title clusters

Updates **JobTitleCluster** (total_filings, avg_salary, canonical_title) and **JobTitle** (title) from linked SalaryRecords. Both `canonical_title` and `JobTitle.title` are set to the **most frequent raw title** (SalaryRecord.job_title) among records in that cluster or entity, so users see e.g. "Software Engineer" instead of a rare typo. Uses bulk SQL (GROUP BY + window functions) and batched bulk_update; run after clustering.

```bash
bazel run //scripts/salary:update_job_title_cluster_stats
bazel run //scripts/salary:update_job_title_cluster_stats -- --dry-run
```

**`scripts/salary/analyze_job_title_normalization.py`** - Analyze job title normalization results
```bash
bazel run //scripts/salary:analyze_job_title_normalization
```

**`scripts/salary/fix_job_title_normalization.py`** - Fix job title normalization issues
```bash
bazel run //scripts/salary:fix_job_title_normalization
```

### Job Title Backfill and Setup

**`scripts/salary/backfill_job_title_links.py`** - Backfill job_title FK links on SalaryRecords
```bash
bazel run //scripts/salary:backfill_job_title_links
```

**`scripts/salary/populate_job_title_slugs.py`** - Populate URL-friendly slugs for job titles
```bash
bazel run //scripts/salary:populate_job_title_slugs
```

### Job Title Debugging and Verification

**`scripts/salary/check_job_title_status.py`** - Check status of job title data
```bash
bazel run //scripts/salary:check_job_title_status
```

**`scripts/salary/debug_job_title_data.py`** - Debug job title data issues
```bash
bazel run //scripts/salary:debug_job_title_data
```

**`scripts/salary/find_valid_job_title_slug.py`** - Find valid job title by slug
```bash
bazel run //scripts/salary:find_valid_job_title_slug -- --slug software-engineer
```

**`scripts/salary/check_sitemap_eligibility.py`** - Check which job titles are eligible for sitemap
```bash
bazel run //scripts/salary:check_sitemap_eligibility
```

---

## VQS (Virtual Queue Simulation)

VQS predicts Visa Bulletin cutoffs and Green Card maturity dates using a deterministic queue simulation. See `docs/PREDICTIONS_ASSESSMENT.md` for the research log and `lib/business/vqs/README.md` for code-level documentation.

### Ingest USCIS I-140

**`scripts/vqs/ingest_uscis_i140.py`** – Ingest I-140 receipts into raw_facts_ledger (for VQS).
```bash
# Stub data for MVP testing (no real USCIS file)
bazel run //scripts/vqs:ingest_uscis_i140 -- --stub
# From XLSX file
bazel run //scripts/vqs:ingest_uscis_i140 -- --file path/to/i140_rec_fy2024_q3.xlsx [--publication-date YYYY-MM-DD]
```

### Run Simulation

**`scripts/vqs/run_simulation.py`** – Run VQS and print next bulletin cutoff and maturity date.
```bash
bazel run //scripts/vqs:run_simulation -- --knowledge-date 2026-02-07 --visa-class 2nd --country 3 --action-type final_action [--priority-date YYYY-MM-DD] [--months 24]
```
Use a knowledge-date on or after the publication date of ingested facts (e.g. after running `--stub`).

### Compute PERM Lag Distribution (Phase 2)

**`scripts/vqs/compute_perm_lag.py`** – Compute PERM lag histogram from SalaryRecord and write to raw_facts_ledger (metric `perm_lag_distribution`). Used by Model A convolution.
```bash
bazel run //scripts/vqs:compute_perm_lag [--publication-date YYYY-MM-DD]
```
Run after PERM data is ingested; optional before running simulation for better demand de-aggregation.

### Run Backtest

**`scripts/vqs/run_backtest.py`** – Compare predicted vs actual cutoffs at reference dates (Bulletin MAE in days).
```bash
bazel run //scripts/vqs:run_backtest -- --reference-dates 2021-01-01 2022-01-01 --horizons 1 3 6 [--visa-class 2nd] [--country 3] [--output json]
```

**`scripts/vqs/compute_prediction_accuracy.py`** – Prediction accuracy metrics and plots.
- **Metric 1 (bulletin-by-bulletin):** For each bulletin, predict every cutoff as-of day-before-publication; compare to actual; plot average error over bulletin date.
- **Metric 2 (long-term):** For each month and (visa_class, country), predict when next cutoff will appear; compare to first bulletin where that cutoff was reached; if predicted past but not yet seen, error ≥ 1.5× (last bulletin − prediction).
```bash
bazel run //scripts/vqs:compute_prediction_accuracy -- --metric both --plot --output-dir /tmp/vqs_accuracy
bazel run //scripts/vqs:compute_prediction_accuracy -- --metric bulletin --filter-visa-class 2nd --filter-country 3
```
Output: JSON/CSV of raw rows; with `--plot`, Plotly HTML with drill-down by visa class and country.

**`scripts/vqs/backtest_interval_coverage.py`** – Score the published 80% prediction intervals against realised actuals. Pure read of stored `PredictedCutoff` rows (no solver run), so it is safe against a live DB and reproduces exactly what was served.

Reports both tails separately against the 10% each should hold — a headline coverage number cannot distinguish a correctly-centred interval from one that buys coverage on an over-covered tail. Also reports interval shape (how often the floor equals the point estimate; how often the no-change outcome is excluded) and flat-call scoring against the previous-actual anchor. Separates `forward` (generated before the target bulletin published) from `backfilled`.
```bash
scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_interval_coverage --horizon 1 --by-series
scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_interval_coverage --horizon 1 --forward-only
scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_interval_coverage --since 2026-05-01 --modelled-only
```
Re-run after each newly graded bulletin month and append the numbers to the tracking ticket, so the next month compares against a recorded series instead of re-deriving the baseline. Baseline measurements: `docs/PREDICTIONS_ASSESSMENT.md` §28.

---

## Database Management

### Migration Scripts

**`scripts/makemigrations_wrapper.py`** - Wrapper for Django makemigrations (handles Bazel sandbox)
```bash
bazel run //:makemigrations_wrapper
```

### Database Utilities

**`scripts/run_sql.py`** - Database query tool (SELECT and mutations)
```bash
bazel run //scripts:run_sql -- --query "SELECT COUNT(*) FROM salary_record"
```

**`scripts/clear_cache.py`** - Clear Django cache (job title autocomplete and directory, employer profile, salary search, market overview, sitemaps, etc.). Use after update_job_title_cluster_stats, refresh_data, or any deploy that changes cached payloads. With Redis, no server restart needed; with LocMem, reload gunicorn after. See `.cursor/rules/deployment.mdc` (Cache reset) and job title coherence rule.
```bash
bazel run //scripts:clear_cache
# Clear only sitemap.xml and robots.txt cache (no full clear):
bazel run //scripts:clear_cache -- --sitemap-only
# On production, set SITE_DOMAIN so the key matches:
SITE_DOMAIN=visa-bulletin.us bazel run //scripts:clear_cache -- --sitemap-only
```
On memory-constrained instances (e.g. 2GB production): run then shut down Bazel to free memory:
```bash
bazel run //scripts:clear_cache && bazel shutdown
```

**`scripts/cache/inspect_cache.py`** - Inspect Django cache state and TTL for a URL path (e.g. `/salaries/`). Shows backend (Redis or LocMem), whether the key exists, and for Redis the remaining TTL. Use after at least one request to the URL so the key exists.
```bash
bazel run //scripts/cache:inspect_cache -- /salaries/
bazel run //scripts/cache:inspect_cache -- /salaries/ --domain visa-bulletin.us
# On production (with .env and Redis):
# SITE_DOMAIN=visa-bulletin.us bazel run //scripts/cache:inspect_cache -- /salaries/
```
See `deployment/README.md` (Caching) for HTTP cache headers and full cache setup.

**`scripts/salary/drop_data.py`** - Drop all data (use with caution!)
```bash
bazel run //scripts/salary:drop_data
```

**`scripts/salary/manage_salary_indexes.py`** - Drop/recreate non-unique salary indexes for bulk ingest
```bash
bazel run //scripts/salary:manage_salary_indexes -- --list
bazel run //scripts/salary:manage_salary_indexes -- --drop
bazel run //scripts/salary:manage_salary_indexes -- --recreate
```

---

## Deployment

### Deployment Scripts

> Note: the canonical release path is the VB platform `visa_bulletin_platform/hosting/`
> tooling — zero-downtime `cutover.sh --code <sha>` (prod) — documented in
> `.claude/rules/branching.md` + `.claude/rules/deployment.md`. The scripts below predate
> the homeserver migration; `<ssh-key>` is whatever key reaches the target host.

> The old `scripts/deploy.sh` (Lightsail SSH + `git reset --hard`) was **deleted 2026-06-27**.
> Production deploys/promotions now run from `visa_bulletin_platform/hosting/` (zero-downtime
> `cutover.sh`), not from this repo — see `.claude/rules/branching.md`.

**`scripts/pre-deploy-check.sh`** - Pre-deployment validation checks
```bash
./scripts/pre-deploy-check.sh <ssh-key>
```

**`scripts/smoke_check_production.py`** - Production smoke check (status + content)
Verifies key pages return 200 and expected content (titles, key strings). Use after deploy or to validate prod.
```bash
bazel run //scripts:smoke_check_production
bazel run //scripts:smoke_check_production -- --base https://visa-bulletin.us --timeout 60
bazel run //scripts:smoke_check_production -- --base http://localhost:8000 --timeout 15
```

**`scripts/staging_prod_diff.sh`** - staging↔prod parity diff-gate
The committed form of the inline diff-gate documented in `.claude/rules/deployment.md`
("Diff staging vs prod HTML for top properties before graduation"). Curls a known set of
top URLs on both stacks, rewrites the staging hostname → prod, strips cosmetic noise
(rotating Cloudflare email tokens, GoatCounter), and prints the *filtered* diffline count
per URL. Run it as the last gate **before** `git merge --ff-only staging` on the prod
branch; inspect every URL with non-zero difflines and classify it per the table in
`deployment.md`. Exit 1 if any URL differs (a human still classifies the diffs).
```bash
./scripts/staging_prod_diff.sh                 # summary table
./scripts/staging_prod_diff.sh --show          # + dump filtered diffs for URLs that differ
./scripts/staging_prod_diff.sh --show /         # one specific path
PROD_BASE=... STAGING_BASE=... PRED_MONTH=2026-7 ./scripts/staging_prod_diff.sh
```

**`scripts/warm_cache.sh`** - post-deploy cache warmer
Curls the top ~20 high-traffic **cacheable** GET pages (homepage, predictions index +
current EB/FS month pages, per-country dashboards, priority-date hubs, salary/employer/
job-title landings, methodology + latest analysis posts, FAQ/about/contact) so Django
re-populates its `@cache_page` Redis entries after a deploy clears them — once the origin
is warm, Cloudflare re-caches the HTML and cold users never pay the 2-3s render. Requests
with `Cache-Control: no-cache` so they reach the origin (not a stale edge copy); no
cache-busting query param, so it warms the same key real visitors hit. Faceted
`/salaries/?...` query URLs are deliberately excluded (per-query, challenge-gated). Run it
right after a prod deploy + Redis flush (see the deploy flow in `.claude/rules/deployment.md`,
next to the `redis-cli -n 1 FLUSHDB` step). Prints per-URL status + timing; exit 1 if any
URL is non-200. Safe to run any time — plain read-only GETs.
```bash
./scripts/warm_cache.sh                                    # warm https://visa-bulletin.us
./scripts/warm_cache.sh --base https://staging.visa-bulletin.us
BASE=... PRED_MONTH=2026-8 ./scripts/warm_cache.sh         # env overrides
```

**`scripts/seo/render_sitemap.py`** - pre-render `/sitemap.xml` to a static file
Writes `<STATIC_ROOT>/sitemap.xml` (the `./staticfiles` bind mount, shared rw into `vb_web`
and ro into `vb_nginx`), which nginx serves **off disk** instead of proxying the render to
gunicorn. The sitemap is the most expensive response on the site (~21.7s cold, 1.3 MB, 6.9k
URLs) and Cloudflare will not edge-cache it (DYNAMIC), so every crawler fetch reached the
origin. The cost is four whole-corpus GROUP BYs behind the URL sets (`qualifying_pairs`,
`qualifying_slugs`, `qualifying_state_codes`, `qualifying_occupation_slugs`); each was
Redis-cached with a 24h TTL, but prod's Redis runs `allkeys-lru` pinned at its 512 MB cap
(~4k evictions/hour, 61% miss rate), so those keys vanish unpredictably and any single miss
puts an aggregate on Googlebot's request path. A file cannot be LRU-evicted.

Renders via `build_sitemap_xml()` — the same function the fallback view uses, so the file and
the view can never disagree. **Refuses to publish a degraded render**: the builder catches
`OperationalError`/`ProgrammingError` per section and returns `[]`, so a DB blip yields a
well-formed ~50-URL sitemap; overwriting a good file with it would tell Google 6.8k pages
vanished. A write must clear both an absolute floor (`--min-urls`, default 1000) and a
relative floor against the file on disk (`--max-shrink`, default 10%). Refusing leaves the
last good file serving — a non-zero exit is not a live-traffic incident. Writes atomically
(temp file + `os.replace` in the same directory), so nginx never sees a partial sitemap.

Scheduled daily at 02:40 on the homeserver, and run immediately after a new bulletin lands
(`scripts/sync_bulletin_to_prod.sh`), since a bulletin moves `lastmod` on every
bulletin-derived URL and adds a `/predictions/` pair. nginx falls back to the Django view if
the file is absent, so a fresh stack degrades to slow-but-correct rather than a 404.
```bash
bazel run //scripts/seo:render_sitemap -- --dry-run
bazel run //scripts/seo:render_sitemap -- --base-url https://staging.visa-bulletin.us
docker exec -w /app vb_web python3 -m scripts.seo.render_sitemap    # in prod
```

**`scripts/staging_page_audit.sh`** - per-URL SEO/marker audit of the staging stack
The committed form of the ad-hoc `curl -H 'Host: staging.visa-bulletin.us' <url>` + grep
check that ran repeatedly across sessions. Curls a representative set of staging URLs
(homepage, an employer profile, a job-title profile, the current predictions month page,
`/salaries/`) via the staging Host and reports, per URL: HTTP status, robots-meta state
(`index`/`noindex`/`none`), whether it's an employer/job-title **profile** page
(`emp`/`jobtitle`/`no`, via the distinguishing rendered JSON-LD schema type —
`AggregateRating` for employers, `Occupation` for job titles), and whether a **Plotly**
chart is rendered. Sibling of `staging_prod_diff.sh` (same `STAGING_BASE` env pattern,
same `/tmp` artifact convention) but a standalone per-page audit, not a staging↔prod diff.
Use after a staging deploy that touches robots meta/indexability, the profile templates,
or chart rendering. Exit 1 if any URL is non-200. Artifacts saved to
`/tmp/vb_page_audit/<slug>.html`.
```bash
./scripts/staging_page_audit.sh                                   # audit the default URL set
./scripts/staging_page_audit.sh --show                           # + dump matched marker lines per URL
./scripts/staging_page_audit.sh --url /employer/google-llc/ --url /salaries/   # audit only these
AUDIT_URLS="/ /salaries/" ./scripts/staging_page_audit.sh        # override the set via env
# Bypass Cloudflare and hit the origin directly with an explicit Host header:
STAGING_BASE=http://127.0.0.1:8080 HOST_HEADER=staging.visa-bulletin.us ./scripts/staging_page_audit.sh
```

### Instance Setup Scripts

> **AWS/Lightsail deployment is RETIRED** (2026-06-20). Production is a self-hosted
> homeserver behind a Cloudflare Tunnel. The cross-instance blue/green orchestrator
> (`refresh_and_switch.py` / `scripts/cron/refresh/{instance,traffic_switch,orchestrate}.py`)
> and the Lightsail bootstrap (`setup_new_instance.sh`) were deleted. Current deploy +
> data-refresh procedure: `.claude/rules/deployment.md`, `.claude/rules/branching.md`,
> and `deployment/homeserver/`. The local data-refresh pipeline below is host-agnostic
> and still used.

**`scripts/setup_postgresql_production.sh`** - PostgreSQL-only setup (standalone)
```bash
./scripts/setup_postgresql_production.sh
```

**`scripts/cron/build_all.sh`** - Pre-build all Bazel binaries (reduces runtime memory)
```bash
./scripts/cron/build_all.sh
```

**`scripts/cron/refresh_data.sh`** - Thin wrapper: sources .env and runs **`scripts/cron/refresh_data.py`** (local pipeline: ingest, clustering, swap on this host). Writes a checkpoint after each step. Use **`--resume`** to continue from the last completed step (checkpoint: `$BACKUP_DIR/refresh_checkpoint.json`).
```bash
./scripts/cron/refresh_data.sh           # Full run (local)
./scripts/cron/refresh_data.sh --resume  # Resume from last checkpoint
```

### Development Setup Scripts

**`scripts/setup_dev_environment.sh`** - Set up development environment
```bash
./scripts/setup_dev_environment.sh
```

**`scripts/setup_dev_tools.sh`** - Install development tools
```bash
./scripts/setup_dev_tools.sh
```

**`scripts/setup_postgresql_local.sh`** - Set up local PostgreSQL
```bash
./scripts/setup_postgresql_local.sh
```

**`scripts/setup_cron.sh`** - Set up cron jobs
```bash
./scripts/setup_cron.sh
```

### Server Management

**`scripts/restart_server.sh`** - Restart Django development server
```bash
./scripts/restart_server.sh              # Foreground (interactive)
./scripts/restart_server.sh --background  # Background (for automation)
```

**`scripts/check_debug_mode.py`** - Verify DEBUG=False in production
```bash
bazel run //scripts:check_debug_mode
```

---

## Analytics

### GoatCounter full-coverage section shares

**`scripts/gc_section_shares.py`** — full-coverage GoatCounter section/path traffic shares for visa-bulletin.us.

**Purpose:** the canonical way to get a traffic breakdown WITHOUT the `/stats/hits` top-100 cap (which silently drops ~1,000+ long-tail paths — every `/employer/<slug>/` and `/job-title/<slug>/` profile — ~11% of weekly pageviews). Reuses the daily_checkup MCP's full `/api/v0/export` pull + filtering + surface buckets (single source of truth), and prints the exact pageviews a top-100 query would have dropped. Use this for ANY share/total/breakdown/A-B conclusion per `~/.claude/rules/complete_data_queries.md`; the capped `?limit=` query in `.claude/rules/analytics.md` is a head-only eyeball.

**Usage:**
```bash
uv run scripts/gc_section_shares.py                          # this_7d (default)
uv run scripts/gc_section_shares.py --window last_28d        # this_7d|prev_7d|cycle_7d|last_28d
uv run scripts/gc_section_shares.py --start 2026-06-01 --end 2026-06-16 --paths
```
Exit 2 if the export is unavailable (does NOT fall back to top-100). For a **known** path set (affiliate SubIds), use the chunked-`include_paths` path in `visa_bulletin_platform/monetization/affiliate_epv_reconcile.py` instead.

### Daily Checkup — run the report locally

**`scripts/run_daily_checkup.py`** — run the `daily_checkup` MCP coroutine locally and dump its report JSON.

**Purpose:** the committed one-liner around `asyncio.run(daily_checkup())`, so nobody re-types that boilerplate to inspect the checkup report while debugging (`~/.claude/rules/no_adhoc_scripts.md`). It imports the SAME `daily_checkup` coroutine `mcp/daily_checkup_server.py` serves (`@mcp.tool()` returns the plain coroutine), so the output is byte-identical to what the digest pipeline receives.

**🚨 HEAVY PROD READ — not casual.** Invoking it does a real production gather: one SSH round-trip to `homeserver` (containers, nginx 24h-log awk, Postgres freshness), a GoatCounter `/api/v0/export` pull (10 MB+ CSV, 1/hour rate-limited, shared cache side effect), GA4/Gmail/GSC sub-MCP calls, and HTTP probes against visa-bulletin.us. Expect tens of seconds; run deliberately, never in a loop.

**Usage:**
```bash
uv run scripts/run_daily_checkup.py                          # pretty JSON to stdout
uv run scripts/run_daily_checkup.py --raw                    # exact MCP string, unformatted
uv run scripts/run_daily_checkup.py --since 2026-07-01T00:00:00Z   # (since currently ignored by server)
uv run scripts/run_daily_checkup.py --out /tmp/checkup.json
```
Exit 0 on a produced report, 1 on gather failure. Requires `~/tokens/goatcounter.token`, the `homeserver` SSH alias, and the sub-MCP auth the server needs.

## Development Utilities

### Git Hooks

**`scripts/install_git_hooks.sh`** — install the repo's tracked pre-commit gate

**Purpose:** git does not clone `.git/hooks`, so a fresh clone runs no gate at
all. This installs the tracked hook (`tools/hooks/pre-commit`) into
`$GIT_COMMON_DIR/hooks`, where a machine-global `core.hooksPath` dispatcher (if
configured) chains it from.

Symlinks by default so the installed hook cannot drift from the tracked one.
It does **not** set a repo-local `core.hooksPath` — that would shadow a global
hooks directory and silently disable whatever else it runs.

**Usage:**
```bash
./scripts/install_git_hooks.sh            # symlink (default)
./scripts/install_git_hooks.sh --copy     # copy, for filesystems without symlinks
./scripts/install_git_hooks.sh --check    # verify only; exit 1 if missing or stale
```

The hook runs ruff, then `tools/bazel_dep_check.py`, then `bazel test //tests:all`,
and fails closed on any Bazel exit it cannot attribute. Pinned by
`//tests:test_pre_commit_hook`.

### File Inspection

**`scripts/ingest/inspect_source_columns.py`** - Inspect columns and sample data in DOL source files

**Purpose:** Inspect what columns exist in DOL source files (PERM, LCA), filter by keywords, and view sample data from those columns. Useful for understanding data structure, identifying available fields, and estimating storage impact for new features.

**Usage:**
```bash
# Check columns in default PERM and LCA files
bazel run //scripts/ingest:inspect_source_columns

# Inspect specific files with keyword filters
bazel run //scripts/ingest:inspect_source_columns -- \
  --files data/salary/dol_data/PERM_Disclosure_Data_FY2020.xlsx \
  --match-terms job,title \
  --show-all-columns

# Estimate storage impact
bazel run //scripts/ingest:inspect_source_columns -- --estimate-storage
```

**Output shows:**
- Total columns in each file
- Matching columns (keyword filters) with sample values
- Total record counts per file
- Optional storage impact estimates

**When to use:**
- Before adding new fields to database schema
- To understand what data is available in source files
- To estimate storage impact for new features
- To identify potential data quality issues

**`scripts/salary/inspect_perm_columns.py`** - Inspect PERM file columns
```bash
bazel run //scripts/salary:inspect_perm_columns -- --file data/salary/PERM_FY2009.xlsx
```

### Utilities

**`scripts/salary/update_wage_thresholds.py`** - Update wage thresholds
```bash
bazel run //scripts/salary:update_wage_thresholds
```

**`scripts/generate_favicon_png.sh`** - Generate favicon variants
```bash
./scripts/generate_favicon_png.sh
```

**`scripts/check_cls.sh`** - Check Cumulative Layout Shift for SEO
```bash
./scripts/check_cls.sh
```

---

## Performance Benchmarking

**`scripts/benchmark_db_ingest.py`** - Benchmark database ingestion performance
```bash
bazel run //scripts:benchmark_db_ingest
```

**`scripts/benchmark_fenced_queries.py`** - Benchmark the SalaryRecord fenced-query resolvers

**Purpose:** Time the three ways the `/salaries/` (and `/worksites/`) list views resolve a filtered page + count/avg/min/max aggregate over `salary_record`, so a regression in the fenced-query optimization (`lib/utils/filter_utils.py`) is measurable: `two_scan` (`fenced_aggregate` + `fenced_page_ids`), `single_scan` (`fenced_page_and_aggregate`, the current cold `?q=` path), and the opt-in `naive` baseline (`.aggregate()` + sliced `.order_by()`). For each representative filter shape (common job-title token, rare token, employer filter, state filter, the combined trigram+employer+state case, and a deep-page case) it prints the wall-clock ms (min + median over N iterations) per path, mirroring the exact queryset `webapp/views/salary/search.py:salary_search_view` builds.

**When to use:** after touching `filter_utils.py` (the fenced resolvers) or before/after a query-shape change, to confirm `single_scan` still beats `two_scan` and neither regressed. The fence + `AS MATERIALIZED` CTE are PostgreSQL-specific, so authoritative timing wants prod/staging Postgres with a populated `salary_record` — against an empty/small dev DB the numbers are structural-only (they confirm each SQL path executes).

```bash
# all shapes on the local dev DB (structural-only timings)
bazel run //scripts:benchmark_fenced_queries

# more iterations + the naive baseline
bazel run //scripts:benchmark_fenced_queries -- --iterations 5 --include-naive

# a single shape
bazel run //scripts:benchmark_fenced_queries -- --shape rare_title

# authoritative numbers on prod/staging (inside the web container, after `bazel shutdown`)
#   docker exec -w /app vb_web python3 -m scripts.benchmark_fenced_queries -- --iterations 5
```

**Note:** The following benchmarking scripts exist but don't have BUILD targets yet. They were used during development for performance optimization:
- `scripts/benchmark_db_serving.py` - Database serving performance
- `scripts/benchmark_excel_standalone.py` - Excel parsing (standalone)
- `scripts/benchmark_parsing.py` - Parsing performance
- `scripts/test_excel_performance.py` - Excel performance
- `scripts/test_streaming_performance.py` - Streaming performance
- `scripts/run_performance_benchmarks.py` - Run all benchmarks
- `scripts/show_performance_comparison.py` - Show comparison

If you need to use these scripts, add BUILD targets following the pattern in `scripts/BUILD`.

---

## Golden Test Data Management

Scripts for managing golden test data for DOL plugin transforms.

### Golden Test Data Collection

**`scripts/salary/collect_dol_golden_test_data.py`** - Collect golden test data for DOL plugin transforms

Samples random rows from all PERM and LCA files for golden testing of transform() methods.

**Usage:**
```bash
# Collect 10 samples per file (default)
bazel run //scripts/salary:collect_dol_golden_test_data

# Customize output and sample size
bazel run //scripts/salary:collect_dol_golden_test_data -- \
  --output tests/data/dol_golden_test_data.yaml \
  --samples-per-file 20 \
  --random-seed 42
```

**`scripts/ingest/extract_smoke_test_samples.py`** - Extract one sample row from each DOL file
```bash
bazel run //scripts/ingest:extract_smoke_test_samples > tests/data/dol_smoke_test_samples.yaml
```

### Golden Test Data Annotation

**`scripts/salary/annotate_golden_test_data.py`** - Manually annotate golden test data
```bash
bazel run //scripts/salary:annotate_golden_test_data
```

**`scripts/salary/auto_annotate_golden_test_data.py`** - Auto-annotate golden test data using plugins
```bash
bazel run //scripts/salary:auto_annotate_golden_test_data
```

**`scripts/salary/fix_yaml_enums.py`** - Fix YAML enum serialization issues in test data
```bash
bazel run //scripts/salary:fix_yaml_enums
```

---

## Testing and Verification Utilities

Development utilities for testing file detection and data quality.

### File Detection Testing

**`scripts/salary/verify_file_discovery.py`** - Verify all DOL files are correctly detected
```bash
bazel run //scripts/salary:verify_file_discovery
```

**`scripts/salary/test_detection_logic.py`** - Test file type detection on specific files
```bash
bazel run //scripts/salary:test_detection_logic
```

**`scripts/salary/test_worksite_detection.py`** - Test worksite file detection specifically
```bash
bazel run //scripts/salary:test_worksite_detection
```

### Data Verification

**`scripts/salary/verify_filtered_cases.py`** - Verify filtered-out cases are correctly annotated
```bash
bazel run //scripts/salary:verify_filtered_cases
```

**`scripts/salary/examine_unknown_files.py`** - Examine files with unknown format
```bash
bazel run //scripts/salary:examine_unknown_files
```

---

## Investigation/Debugging

**Note:** Most investigation functionality has been merged into the unified validation script. Use `bazel run //scripts/salary:validate_data` with appropriate flags.

### Deleted Investigation Scripts

These scripts have been deleted and their functionality is available in the unified validation script:

- `scripts/investigate_null_salaries.py` - Deleted, use `--check-incomplete-records` flag
- `scripts/investigate_salary_issues.py` - Deleted, use unified validation script
- `scripts/investigate_validation_issues.py` - Deleted, use unified validation script
- `scripts/check_missing_salary.py` - Deleted, use `--check-incomplete-records` flag

---

## Script Development Guidelines

### Before Creating a New Script

1. **Search for existing scripts** - Check this README and search the codebase for similar functionality
2. **Consider extending existing scripts** - Add new modes/flags to existing scripts rather than creating new ones
3. **Only create new scripts if functionality is truly distinct** - Avoid duplication

### Script Documentation Requirements

Every script must include:
- **Docstring** with purpose, usage examples, and key flags
- **Entry in this README** (appropriate category)
- **BUILD target** with proper dependencies
- **Script usage logging** (if permanent script - use `ScriptLogger`)

### Script Naming Conventions

- **Validation scripts**: `validate_*.py`, `check_*.py`
- **Fix scripts**: `fix_*.py`
- **Investigation scripts**: `investigate_*.py`, `debug_*.py`
- **Utility scripts**: Descriptive names (e.g., `run_sql.py`, `clear_cache.py`)
- **Avoid**: `test_*.py` for non-unit-test scripts (use `check_*.py` or `evaluate_*.py`)

### Running Scripts

**Always use Bazel:**
```bash
bazel run //scripts/salary:validate_data
bazel run //scripts:run_sql
```

**Never run Python directly:**
```bash
# ❌ BAD
python scripts/salary/validate_data.py

# ✅ GOOD
bazel run //scripts/salary:validate_data
```

### Long-Running Scripts

For scripts that take > 10 seconds:
- Run in background with logging
- Monitor progress actively
- Use slow exponential backoff for monitoring intervals

Example:
```bash
bazel run //scripts/salary:cluster_existing_employers > /tmp/clustering.log 2>&1 &
PID=$!
tail -f /tmp/clustering.log
```

---

## Test-DB hygiene — `drop_orphan_test_dbs.py`

The test suite (`tests/django_setup.py`) creates a per-pid `test_postgres_<pid>`
database on the shared local postgres for each bazel target. Clean exits now drop
their own DB via an `atexit` hook, but a target **killed** by a timeout/OOM
orphans one. Left unswept these accumulate (2065 DBs / 21 GB by 2026-07-07 on the
minipc).

`scripts/drop_orphan_test_dbs.py` is the backstop. It drops a `test_postgres_%`
DB only when it has **no active connection** AND the `<pid>` in its name is **no
longer a live process** (`/proc/<pid>` absent) — so a running test is never hit.
Peer-auths to postgres over the unix socket as the current OS user.

```bash
uv run scripts/drop_orphan_test_dbs.py --dry-run   # preview
uv run scripts/drop_orphan_test_dbs.py             # sweep
```

Installed as an **hourly user cron** on the minipc (logs to
`logs/drop_orphan_test_dbs.log`, gitignored):
```
37 * * * * cd .../visa_bulletin && ~/.local/bin/uv run scripts/drop_orphan_test_dbs.py >> .../logs/drop_orphan_test_dbs.log 2>&1
```

---

## Temporary/One-Off Scripts

Temporary debugging scripts should be placed in `scripts/oneoff/` and logged to `logs/throwaway_calls.log` using `log_context()`.

See `.cursor/rules/general_logging.mdc` for details on script usage logging.

---

## Related Documentation

- [Validation Manual Flow](../../docs/VALIDATION_MANUAL_FLOW.md) - Detailed validation workflow
- [Fix Procedures](../../docs/FIX_PROCEDURES.md) - Data quality fix procedures
- [Employer Clustering](../../lib/business/salary/README.md) - Clustering documentation
- [Ingest Pipeline](../../docs/UNIFIED_INGEST_PIPELINE_DESIGN.md) - Ingest pipeline design


### `scripts/bulletin/fad_history.py`

Prints the Final Action / Dates for Filing history for one preference + country from the
archived DoS pages in `data/bulletin/saved_pages/`, so claims about how a category has
moved can be sourced from the archive instead of from memory.

```bash
uv run scripts/bulletin/fad_history.py --pref 2nd --country row --from 2022-01
uv run scripts/bulletin/fad_history.py --pref 1st --country india --chart filing
```

`--country` = row | china | india | mexico | philippines. `--chart` = final | filing.
Pass `--family` for F1/F2A/F2B/F3/F4 — the family and employment charts share row labels
in older bulletins, so the kind of chart has to be selected explicitly.
Missing/unparseable months are reported on stderr and skipped; exit 1 if nothing matched.
