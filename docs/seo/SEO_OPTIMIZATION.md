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
| Static pages | 8 | `/`, `/salaries/`, `/employers/`, `/job-titles/`, `/faq/`, `/when-is-the-next-visa-bulletin/`, `/about/`, `/contact/` | Latest bulletin date |
| Category/country landings | ~12 | `/employment-based/`, `/family-sponsored/` × countries | Latest bulletin date |
| Priority-date landings | 12 | `/priority-date/{eb1,eb2,eb3}/{india,china,philippines,mexico}/` | Latest bulletin date |
| Employer profiles | ~3,900 | `EmployerCluster` with slug, `total_lca_count >= 5`, top 10k | Latest bulletin date |
| Job title profiles | ~5,200 | `JobTitleCluster` with slug, `total_filings >= 10`, top 10k | Latest bulletin date |
| Blog posts | all published | `BlogPost.is_published=True` | Per-post `published_date` |
| Prediction archive | all bulletin months | One URL per `Bulletin` month | Per-bulletin `publication_date` |

All static/profile URLs use `changefreq: monthly`, `priority: 0.8`. Blog posts use `changefreq: yearly`, `priority: 0.6`. Prediction pages use `changefreq: yearly`, `priority: 0.5`.

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
