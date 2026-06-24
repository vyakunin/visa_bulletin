# SEO Optimization — Current State

Site: `https://visa-bulletin.us`

## Sitemap & robots.txt

Both generated dynamically by `webapp/views/seo/sitemaps.py`.

**robots.txt** (`/robots.txt`):
```
User-agent: *
Allow: /
Disallow: /api/
Sitemap: https://visa-bulletin.us/sitemap.xml
```

**Sitemap** (`/sitemap.xml`) — single `<urlset>`, ~9,500+ URLs:

| Section | Count | Filter criteria | `lastmod` |
|---------|-------|----------------|-----------|
| Static pages | 12 | the 8 English + `/es/`, `/es/faq/`, `/es/predictions/`, `/es/priority-date/` (Spanish cluster) | Latest bulletin date |
| Category/country landings | ~12 | `/employment-based/`, `/family-sponsored/` × countries | Latest bulletin date |
| Priority-date landings | 12 | `/priority-date/{eb1,eb2,eb3}/{india,china,philippines,mexico}/` | Latest bulletin date |
| Priority-date landings (Spanish) | 12 | `/es/priority-date/{eb1,eb2,eb3}/{india,china,philippines,mexico}/` | Latest bulletin date |
| Priority-date hub + rollups | 4 | `/priority-date/` + `/priority-date/{eb1,eb2,eb3}/` (country-agnostic) | Latest bulletin `fetched_at` |
| Employer profiles | ~3,900 | `EmployerCluster` with slug, `total_lca_count >= 5`, top 10k | Latest bulletin date |
| Job title profiles | ~5,200 | `JobTitleCluster` with slug, `total_filings >= 10`, top 10k | Latest bulletin date |
| Blog posts | all published | `BlogPost.is_published=True` | Per-post `published_date` |
| Prediction archive | all bulletin months | One URL per `Bulletin` month | Per-bulletin `publication_date` |
| Month forecast | 1 (rolling) | The upcoming bulletin month (`latest + 1`) | Latest bulletin `fetched_at` |

All static/profile URLs use `changefreq: monthly`, `priority: 0.8`. Blog posts use `changefreq: yearly`, `priority: 0.6`. Prediction archive pages use `changefreq: yearly`, `priority: 0.5`. The month-forecast page uses `changefreq: weekly`, `priority: 0.7` (refreshes as the forecast updates).

**Search engine ping**: The refresh pipeline pings Google and Bing after clearing the sitemap cache (`step_ping_search_engines` in `scripts/cron/refresh/steps.py`). Non-fatal on failure.

## Priority-date landing pages (`/priority-date/<eb_class>/<country>/`)

Per-EB-class × per-country focused landing pages targeting high-intent queries
("eb2 india priority date", "eb3 china priority date" — real GSC demand at pos
~7-8). EB-1/2/3 × India/China/Philippines/Mexico (12 pages). Each shows the
current Final Action + Dates-for-Filing cutoffs, the latest month-over-month
movement, a 6-month history table, an FAQ (FAQPage schema), and links into the
full per-country dashboard + salary data + sibling pages (internal-link mesh).

- View: `webapp/views/bulletin/priority_date_landing.py` (reuses the normalized
  `get_aggregated_visa_class_data` series; headline status from the latest
  bulletin row so C/U vs a date is accurate).
- **Deliberately cheap to render** — no live VQS solver (predictions are linked,
  not embedded), so the page stays fast + cacheable and avoids the per-country
  dashboard's filter-combo query cost.
- Unknown class/country or a combo with no cutoff data → 404 (no thin pages).
- Test: `tests/test_priority_date_landing.py`.
- **Status (2026-06-23):** core shipped to `main` + sitemap, suite green.
  Pending: staging deploy + real-data render verify, internal links FROM the
  main dashboards, then GSC measurement. Possible v2: embed the prediction,
  add EB-4/EB-5 + ALL, expand country set.

## Spanish (/es/) cluster

Spanish-language sibling pages converting real Spanish search demand ("boletín de
visas", "fecha de prioridad eb2 india", "predicciones boletín de visas",
"preguntas frecuentes boletín de visas"). Static-sibling pattern (hardcoded
Spanish copy, no Django i18n middleware) — the live data widgets (dashboard,
salaries, prediction archive) stay English and the Spanish pages link into them
with a note that the visual interface (dates/categories/countries) is navigable
without advanced English.

- **`/es/`** — landing explainer (pre-existing; now links the cluster).
- **`/es/priority-date/<eb>/<country>/`** (12) — Spanish mirror of the English
  per-EB×country landings. Reuses the EN data path (`_latest_status` / `_series` /
  `_chart_json` in `priority_date_landing.py`); only the rendered chrome/copy is
  localized (`spanish_priority_date_landing_view` + Spanish `_trend_es` / `_faq_es`
  / date formatting). FAQPage JSON-LD. Same 404 gate as EN (no thin pages).
- **`/es/priority-date/`** — Spanish hub indexing the 12 landings.
- **`/es/faq/`** — Spanish FAQ (8 Q&A) with FAQPage JSON-LD.
- **`/es/predictions/`** — Spanish explainer of the Bulletin Forecast model,
  linking to the English prediction archive.
- **Views:** `webapp/views/static/spanish.py` (hub/faq/predictions) +
  `spanish_priority_date_landing_view` in `priority_date_landing.py`.
- **hreflang:** bidirectional `es`↔`en` declared on every pair (ES landing↔EN
  landing, ES FAQ↔EN FAQ `/faq/`, ES hub↔EN hub `/priority-date/`, ES
  predictions↔EN `/predictions/`); `x-default` → English. The base template only
  emits hreflang on `/`; each page template overrides the `hreflang` block.
- **Sitemap:** all `/es/` URLs emitted (4 static + 12 landings) with truthful
  `lastmod`. Test: `tests/test_spanish_cluster.py`.
- **Status (2026-06-24):** shipped to `main`, suite green. Pending: staging
  deploy + real-data render verify, GSC measurement after indexing. Possible v2:
  Spanish per-country dashboard data, expand to other high-demand Spanish queries.

## Priority-date HUB + per-EB-class rollups (`/priority-date/` + `/priority-date/<eb_class>/`)

Country-AGNOSTIC priority-date pages sitting above the per-country landings.
**Why (GSC, 2026-06):** the generic query "eb2 priority date" (no country) pulled
~1.4k impr/month at pos ~5 onto the `/salaries/` and `/employers/` list pages,
which answer it terribly (**0% CTR**) — nothing on the site targeted the
no-country query. Combined, those two list pages carried ~10k impr/month of
priority-date-intent queries at ~0% CTR (the real cause of their <0.5% aggregate
CTR — on their OWN intent they're healthy: `/salaries/` salary queries ≈ 3.55%).

- **Hub** `/priority-date/`: index of all EB classes × countries; targets
  "priority date" / "visa bulletin priority date". Gives `/salaries/` +
  `/employers/` a clean link target to steer priority-date intent away.
- **Rollup** `/priority-date/<eb_class>/` (eb1/eb2/eb3): ONE EB class across all
  five chargeability areas (India/China/Mexico/Philippines/All-Others) in one
  table; targets the generic "ebN priority date".
- View: `webapp/views/bulletin/priority_date_rollup.py` (reuses the landing
  page's cheap helpers — no live VQS solver). FAQPage schema on both. Unknown EB
  class or no cutoff data → 404 (no thin page). Distinct URL segment counts from
  the per-country landing route, so no shadowing.
- Cross-links added FROM `/salaries/` + `/employers/` → the hub (intent steering
  + reassignment signal + no dead-end).
- Test: `tests/test_priority_date_rollup.py`.
- **Status (2026-06-23):** shipped to `main` + sitemap, suite green. Pending:
  staging deploy + real-data render verify, then GSC measurement of whether the
  generic PD queries reassign off `/salaries/`+`/employers/` onto these pages
  (the CTR-recovery thesis).

## Per-month forecast landing pages (`/predictions/<month>-<year>/`)

Evergreen forecast page for the **upcoming** bulletin month, targeting the
recurring high-intent query "visa bulletin {month} {year} predictions" (the
predictions cluster we already rank top-3 for, per `visa_bulletin_platform/docs/SEO.md`).
e.g. `/predictions/october-2026/`. Distinct from the prediction *archive*
(`/predictions/<category>/<year>-<month>/`), which is the backtest accuracy view
and 404s for any month without a published bulletin — the forecast page covers
exactly that gap (the not-yet-published month).

- View: `webapp/views/bulletin/prediction_month_forecast.py`. URL: a tight
  `re_path` (`^predictions/(?P<slug>[a-z]+-20\d{2})/$`) registered **before**
  `predictions/<str:category>/` so it never shadows the category/legacy routes.
- Renders the model's predicted Final Action / Filing cutoffs across all EB + FS
  categories × countries, headline cards for the oversubscribed India/China EB-2/3
  series (with movement-probability badges), an FAQ (FAQPage schema), and links
  into the live dashboards + per-country priority-date pages + methodology.
- **Deliberately cheap to render** — NEVER calls the live VQS solver (the 23s path
  removed from FS pages in `4524f04`). Reads only **stored** `PredictedCutoff`
  rows, which the hourly refresh publishes for `latest_bulletin_month + 1`
  (`_publish_predictions_for_latest_bulletin`). `@cache_page_skip_bots`; the cron's
  `cache.clear()` on each new ingest keeps it fresh.
- Once the target month's actual bulletin lands → **301 → the accuracy archive**
  (no duplicate page for the same month). A future month with no stored forecast,
  or an invalid month slug → 404 (no thin page, no solver).
- Sitemap emits ONE rolling URL (`upcoming_forecast_month()`), auto-advancing as
  bulletins land. Inbound links FROM `/predictions/` (archive) and
  `/when-is-the-next-visa-bulletin/`.
- Test: `tests/test_prediction_month_forecast.py`.
- **Status (2026-06-23):** core shipped to `main` + sitemap + inbound links, suite
  green. Pending: staging deploy + real-data render verify, prod graduation
  (Path-1 image swap — pure rendering), CF edge purge + GSC sitemap submit, then
  GSC measurement. Possible v2: emit +2/+3 month pages, embed the per-series
  chart, surface confidence intervals.

## Top-H-1B-sponsors-per-role pages (`/h1b-sponsors/<job-title-slug>/`)

Dedicated ranked leaderboard answering the high-intent query the existing pages
don't: **"top H-1B sponsors for {role}" / "which companies sponsor H-1B for
{role}" / "companies that sponsor H-1B for {title}"**. The `/job-title/<slug>/`
profile is salary-stats-first and `/salaries/by-state/<code>/` is state-first;
neither is a clean ranked "companies that sponsor H-1B for X" answer — so this is
a new page, not a thin duplicate.

- **Content:** headline stats (H-1B filings, # sponsoring employers, median
  H-1B wage + p25–p75); a ranked top-25 employer table (employer → `/employer/`
  link, H-1B filing count, mean wage); a top-states block; an FAQ (FAQPage
  schema). Ranked by certified H-1B LCA filing count from DOL data.
- **View:** `webapp/views/salary/h1b_sponsors.py`. **Deliberately cheap** — a
  handful of indexed, single-cluster aggregates (`visa_program`, `wage_annual`,
  `job_title_entity`/`employer` FKs); no live VQS solver, no full scan.
  `@cache_page_skip_bots`.
- **No thin pages:** a role 404s unless it has **≥50 H-1B filings AND ≥8 distinct
  sponsoring employers**. This gate is shared (`lib/business/salary/h1b_sponsors.py`)
  with the sitemap emit-set, so the sitemap NEVER lists a page that 404s.
- **Sitemap:** emits the qualifying slug set (cached 24h via the shared helper —
  the gate is a GROUP BY over the H-1B corpus, too heavy per bot fetch; the
  refresh pipeline's `cache.clear()` refreshes it). `changefreq monthly`,
  `priority 0.6`, lastmod = latest bulletin `fetched_at`. Capped to the top 5,000
  roles by H-1B volume.
- **Internal-link mesh:** inbound from each role's `/job-title/<slug>/` profile
  (a CTA in the "Top Employers" card, rendered only when the role qualifies so we
  never link to a 404) + the sitemap; outbound to the profile, salary search, and
  each `/employer/<slug>/`.
- **Test:** `tests/test_h1b_sponsors_landing.py` (qualifying renders + FAQPage +
  self-canonical; thin role 404; PERM-heavy role 404 = H-1B-only; sitemap lists
  qualifying only).
- **Status (2026-06-24):** core shipped to `main` + sitemap + inbound link, suite
  green. Pending: staging deploy + real-data render verify, prod graduation
  (Path 1 — pure rendering), CF purge + GSC sitemap submit, then GSC measurement.
  **Follow-ups (v2):** (a) the state variant — re-angle `/salaries/by-state/` for
  "highest-paying H-1B employers in {state}" (wage-ranked, H-1B-filtered); (b)
  denormalize per-cluster H-1B filing/sponsor counts onto `JobTitleCluster` in the
  stats refresh, which lets the sitemap drop the heavy cached aggregate and
  enables a related-role sponsor-page cross-link mesh.

## Timing-query consolidation (`/when-is-the-next-visa-bulletin/`)

The dedicated release-schedule page targets the **"when will the {month} {year}
visa bulletin come out / be released"** cluster (~1,100+ impr/mo, GSC). It was
**indexed but getting 0 impressions** — the homepage had consolidated the timing
intent and ranked the cluster at pos ~10; the better-targeted page never
surfaced. Schema was NOT the gap (it already had FAQPage). Two real levers
applied (2026-06-23):

- **Month-specificity** — `<title>` + an H2 + a month-keyed FAQ question now name
  the governing month (`When Will the {Month Year} Visa Bulletin Come Out?`),
  rolling forward each month like the forecast page, to match the high-volume
  month-specific variant. H1 stays generic ("When does the next Visa Bulletin
  come out?") so the generic query is still covered. View:
  `webapp/views/static/pages.py:next_bulletin_view`.
- **Internal-link consolidation** — contextual timing-anchor links now point to
  the page from high-authority surfaces (homepage body, the per-month forecast
  page CTA, the prediction archive forecast alert), not just the site-wide
  nav/footer — so Google prefers the dedicated page over the homepage for the
  cluster. Previously only `base.html` + `faq.html` linked it.
- Test: `tests/test_next_bulletin.py` (month-specific title/H2/FAQ + inbound-link
  mesh). **Status (2026-06-23):** shipped to `main`, suite green. Pending staging
  deploy + GSC measurement of the homepage→dedicated-page shift over ~2-3 wks.

## AI Crawler Support (`/llms.txt`)

`/llms.txt` is served by `llms_txt_view` in `webapp/views/seo/sitemaps.py`. It follows the [llmstxt.org](https://llmstxt.org) convention for telling AI crawlers (ChatGPT, Perplexity, Claude, etc.) what data this site contains and how to cite it.

Content includes:
- Section-by-section description of the site (dashboard, salary DB, employer profiles, job title profiles, analysis)
- Canonical URLs for each section
- Data source descriptions (State Dept, DOL) and update frequency
- Citation guidance

## Caching Strategy

`@cache_page_skip_bots(settings.CACHE_TIMEOUT)` (24 hours) applied to: sitemap, robots.txt, llms.txt, profile pages, directory pages, autocomplete, dashboard, salary search.

**Bot bypass**: `cache_page_skip_bots` (in `django_config/cache_utils.py`) skips the cache entirely for known bot User-Agents (Googlebot, Bingbot, GPTBot, DuckDuckBot, Baiduspider, YandexBot, facebookexternalhit, Slurp). Bots always hit the live view and get fresh data.

**Cache clearing**: `scripts/clear_cache.py` with `--sitemap-only` flag (clears sitemap + robots cache) or full `cache.clear()`. Run automatically in the refresh pipeline after `warm_cache`.

## Meta Tags (base.html)

`webapp/templates/webapp/base.html` provides site-wide defaults. Profile templates override via context variables.

| Tag | Source |
|-----|--------|
| `<title>` | `page_title` context var (default: "U.S. Immigration Data — Visa Bulletin Dashboard") |
| `<meta description>` | `page_description` context var |
| `<meta keywords>` | Hardcoded: visa bulletin, priority date tracker, EB2, EB3, green card, ... |
| `<meta author>` | "U.S. Immigration Data" |
| `<meta theme-color>` | `#003366` |
| `<link rel="canonical">` | `canonical_url` context var (rendered only if set) |
| `<meta robots>` | `meta_robots` context var (rendered only if set; default = no tag = `index, follow`) |

## Crawl-budget hygiene — noindex the free-text search space

The free-text keyword search `/salaries/?q=<keyword>` (and `/worksites/?q=<keyword>`) is an **unbounded URL space** — every distinct query string is a new page. Left indexable, Google burns crawl budget on infinite low-value permutations. Both search views set `meta_robots = "noindex, follow"` whenever a non-empty `q` param is present (`webapp/views/salary/search.py`, constant `_NOINDEX_FOLLOW`), and `base.html` renders `<meta name="robots" content="noindex, follow">` from it. `follow` keeps link equity flowing from results to the canonical employer/job-title/state slug pages.

Stays indexable (no robots tag): the bare `/salaries/` landing, slug pages (`/salaries/employer/<slug>/`, `/salaries/role/<slug>/`, `/salaries/by-state/<slug>/`), and curated filter combos without a free-text `q` (employer-slug / state / program) — the dynamic-SEO design intentionally ranks those. Regression test: `tests/test_salary_search_view.py::SalarySearchNoindexTest`.

## Canonical URLs

All dynamic pages that can receive query parameters set `canonical_url` to the clean path (no query params):

| Page | Canonical set by |
|------|-----------------|
| Employer profile | `profile.py` → `request.build_absolute_uri(request.path)` → context `canonical_url` |
| Job title profile | `profile.py` → `request.build_absolute_uri(request.path)` → context `canonical_url` |
| Salary search | `search.py` → `request.build_absolute_uri(reverse("salary_search"))` |
| Worksite search | `search.py` → `request.build_absolute_uri(reverse("worksite_search"))` |
| Dashboard | Set in `dashboard.py` |

Profile templates do **not** emit a second `<link rel="canonical">` in `extra_head` — they rely entirely on `base.html` rendering it from the `canonical_url` context var.

## Open Graph & Twitter Cards

Set in `base.html`, overridable via context:

- `og:image` / `twitter:image` → `/static/og-image.png` (1200×630)
- `og:type` → website
- `og:site_name` → "U.S. Immigration Data"
- `twitter:card` → summary_large_image

Profile templates (`job_title_profile.html`) override with page-specific title, description, canonical, and image.

## Structured Data (JSON-LD)

### Global (every page via `base.html`)

1. **Organization** — name, url, logo, contactPoint, sameAs
2. **WebSite** with **SearchAction** — `urlTemplate` for category/country search

### Per-page schemas

| Page | Schemas |
|------|---------|
| Dashboard | `Dataset` (built in Python by `_build_structured_data()` in `lib/business/bulletin/cutoff_data_aggregator.py`) |
| Salaries landing (`/salaries/`, bare) | corpus `Dataset` (1.5M+ DOL salary records) via `webapp/views/seo/jsonld.py:build_dataset_jsonld` |
| Salaries (employer-scoped) | per-employer `Dataset` (`search.py:_build_dataset_jsonld`) |
| Employers directory (`/employers/`) | corpus `Dataset` (221K+ visa sponsors) via `build_dataset_jsonld` |
| Job title profile | `Occupation` + `MonetaryAmountDistribution` (salary percentiles) + `BreadcrumbList` |
| Employer profile | `Organization` + optional `AggregateRating` (only when `total_filings > 0`) + `BreadcrumbList` |
| FAQ | `FAQPage` |
| Next-bulletin (`/when-is-the-next-visa-bulletin/`) | `FAQPage` (projected release date, cadence, official source) — projection in `lib/business/bulletin/release_schedule.py` from recent `Bulletin.fetched_at` |

**Dataset on the `/salaries/` + `/employers/` landings (added 2026-06-18, commit `5f74599`).**
These landings rank for the dataset-intent head queries ("h1b salary database",
"perm salary database", "green card salary database", sponsor lookups) but had no
page-level structured data — the bare `/salaries/` landing explicitly emitted none.
Each now carries a `schema.org/Dataset` describing the whole corpus, eligible for a
Dataset rich result on exactly those queries. Shared builder + `<script>`-safe
embedding live in `webapp/views/seo/jsonld.py`. Same change tightened both page
`<title>`s to ≤60 chars (were truncating in SERP), keeping "Database" + the
question hook front-loaded. CTR impact to be re-measured in GSC ~2 weeks out.

> Note on the `/employers/` aggregate CTR (~0.075% on ~27k impr): most of those
> impressions are structurally **wrong-intent** — the page surfaces at pos ~8–10 for
> generic visa-bulletin queries ("boletin de visas", "bulletin visa uscis", "current
> date for eb1 india") it inherits from the domain brand, which no title/meta can win.
> The Dataset + title work targets the dataset-intent queries the page *should* own;
> the wrong-intent drag is a relevance/position concern (the head-terms ticket).

**`AggregateRating` on employer profiles**: uses visa approval rate (0–100) as `ratingValue` on a 0–100 scale. `ratingCount` is always `total_filings > 0` (guard added after Google Search Console warning). Worth monitoring in Search Console Rich Results report to confirm Google renders it.

**`BreadcrumbList`**: emitted as a separate JSON-LD block in the profile `extra_head`. Uses `request.scheme`/`request.get_host` for portability across environments.

## Favicon System

Referenced in `base.html`:

| File | Purpose |
|------|---------|
| `favicon.ico` | Legacy browsers |
| `favicon-32x32.png` | Modern browsers |
| `favicon-16x16.png` | Small tabs |
| `favicon.svg` | Vector format |
| `apple-touch-icon.png` | iOS home screen (180×180) |

Source SVG: `webapp/static/favicon.svg`. Regenerate PNGs: `./scripts/generate_favicon_png.sh`.

## Profile Page SEO

**Job title profiles** (`/job-title/{slug}/`):
- Custom `<title>`, `<meta description>`, `<link rel="canonical">` via `seo` context dict
- Page-specific OG/Twitter tags in `{% block extra_head %}`
- `Occupation` + `BreadcrumbList` JSON-LD schemas

**Employer profiles** (`/employer/{slug}/`):
- Custom `seo` dict with title, description, canonical_url
- `canonical_url` set in context (path-only, no query params)
- `Organization` + optional `AggregateRating` + `BreadcrumbList` JSON-LD schemas
- Fuzzy slug redirect: old/mismatched slugs → 301 to canonical cluster slug

**Directories** (`/job-titles/`, `/employers/`):
- Custom `page_title` and `page_description`
- Paginated with query params

## HTTPS & Redirects

Handled by nginx, not Django. Django HTTPS settings are commented out in `settings.py`. Nginx handles:
- HTTP → HTTPS redirect
- SSL termination (Let's Encrypt via certbot)

## Known Issues

1. **Stale Google index entries**: ~74 old job-title/employer slugs that no longer exist still return 404. These are not in the current sitemap and will self-resolve. Use Search Console "Validate Fix" to speed up.
2. **`AggregateRating` eligibility**: approval-rate-as-rating may not qualify for Google rich snippets (it's not a user-review rating). Monitor in Search Console → Rich Results.
3. **Blog and prediction pages**: no per-page `page_description` or OG image — sharing falls back to site defaults. Consider adding per-post description to `BlogPost` model and per-month description to prediction detail view.
4. **`WebSite` `SearchAction`**: uses `category`/`country` URL template — validate at https://search.google.com/test/rich-results that it qualifies for sitelinks search box.

## Testing & Verification

| Tool | URL | What to check |
|------|-----|---------------|
| Google Rich Results Test | https://search.google.com/test/rich-results | Organization, WebSite, Occupation, BreadcrumbList schemas |
| Facebook Sharing Debugger | https://developers.facebook.com/tools/debug/ | OG image, title, description |
| PageSpeed Insights | https://pagespeed.web.dev/ | Core Web Vitals, image sizes |
| Google Search Console | https://search.google.com/search-console | Index coverage, sitemap status, 404s, rich results |

## Design Decisions

**Homepage title is intentionally narrow (country/category-specific).** The dashboard view builds a title like "India Employment-Based Visa Bulletin Predictions & Tracker - March 2026" based on the active filter. This is deliberate — the vast majority of real visitors are Indian EB-2/EB-3 applicants, so the default title matches their intent and reduces friction. A broad generic title would serve SEO auditors but not actual users.

**`/llms.txt` over robots meta tags for AI.** AI crawlers (GPTBot, Claude-Web, PerplexityBot) are already in the `cache_page_skip_bots` bypass list and allowed by robots.txt. The `llms.txt` file adds structured guidance on what content is available and citable, without restricting access.

## Key Files

| File | Purpose |
|------|---------|
| `webapp/views/seo/sitemaps.py` | Sitemap, robots.txt, and llms.txt views |
| `webapp/templates/webapp/base.html` | Site-wide meta tags, structured data, favicon refs |
| `webapp/views/job_titles/profile.py` | Job title profile SEO context |
| `webapp/views/employers/profile.py` | Employer profile SEO context |
| `webapp/views/salary/search.py` | Salary/worksite search canonical URLs |
| `django_config/cache_utils.py` | `cache_page_skip_bots` implementation |
| `scripts/cron/refresh/steps.py` | `step_ping_search_engines` and `step_clear_sitemap_cache` |
| `scripts/clear_cache.py` | Manual cache clearing (`--sitemap-only` flag) |
| `scripts/generate_favicon_png.sh` | Regenerate favicon PNGs from SVG |
